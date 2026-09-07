// runner.go 承载 job#1 的跨篇调度 runner（B6）：把语料扫描（B2 corpus）→ 并发
// 限量 → 共享 token 预算 → 每篇 encounter DAG（B5）→ 可选投递
// POST /api/encounter/import-pack（含 429/5xx 退避重试）串成一条端到端流水线，
// 并聚合每篇错误报告。
//
// 顶层职责（fail isolation）：仅剩不可恢复的全局错误（如语料目录扫描失败、DAG
// 构建失败）会让 RunEncounterPack 返回 error；单篇分析/预算/落盘/投递失败一律进
// Result.Failed，绝不让整体 run 失败，也绝不影响他篇成功。
//
// 并发护栏（goroutine 零泄露）：worker-pool 模式——固定启动 cfg.Concurrency 个
// worker goroutine（唯一 stdlib，不引入 x/sync），共享 jobs channel 消费；主
// goroutine 以 ctx select 喂料，ctx 取消即停止喂新 job 并 close(channel)，worker
// drain 后全部经 sync.WaitGroup 收尾。慢/阻塞步骤（如 fake 分析）也尊重 ctx，
// 随取消尽快退出。
package job

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/corpus"
	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// ---- 配置 / 结果 ----------------------------------------------------------------

// RunConfig 是 RunEncounterPack 的一次运行配置。零值字段启用各自默认：
//
//	Concurrency<=0 → 1（串行，最保守、结果确定）
//	BudgetTokens<=0 → defaultBudgetTokens（100_000）
//	MaxArticles<=0 → 不限（透传 corpus.Options）
//	DryRun → 仅回传清单不执行
//	DeliverURL 空 → 不做投递
type RunConfig struct {
	CorpusDir    string // 语料根目录（必填；B2 ScanDir）
	OutDir       string // pack 落盘目录（必填；export 步骤自动建）
	Concurrency  int    // 并发 worker 上限（默认 1）
	MaxArticles  int    // 语料限量（默认不限）
	BudgetTokens int    // 共享 token 预算（默认 100_000）
	DryRun       bool   // 仅回传清单，不扫描执行
	DeliverURL   string // 非空时对成功 pack POST /api/encounter/import-pack
}

// defaultBudgetTokens 是 BudgetTokens<=0 时的兜底（与 B7 命令行 --budget-tokens
// 默认 100_000 对齐）。DeepSeek 真调用防失控护栏：一次 job 总 token 消耗上限。
const defaultBudgetTokens = 100_000

// Result 是一次 RunEncounterPack 的聚合结果。
//
//	Packs  成功产出的 pack 文件路径（正常模式）；DryRun 下为清单 = 预排文章源路径。
//	Failed 每篇失败的可读行 "<来源>：<错误>"（path: err），含预算/落盘/投递失败。
type Result struct {
	Packs  []string
	Failed []string
}

// ---- 投递参数（镜像 supervisor 的退避风格） ---------------------------------------

const (
	// deliverEndpoint 是 import-pack 投递端点（A2 产物，本机闸）。
	deliverEndpoint = "/api/encounter/import-pack"
	// deliverTimeout 是单次投递 HTTP 请求的总超时。
	deliverTimeout = 5 * time.Second
	// deliverRetries 是初始请求失败后的退避重试次数。语义（钉死）：
	// 每篇投递 = 1 次初始 + 至多 deliverRetries 次退避重试 = 至多 4 次请求。
	// 429/5xx 及瞬时网络错误触发重试；其余 4xx（非 429）视为不可恢复。
	deliverRetries = 3
)

// deliverBackoffDefault 是投递退避纯函数，镜像 supervisor（pythonsvc）的指数
// 退避：500ms 基数 × 2^attempt，封顶 8s；attempt>4 直接封顶（防移位溢出）。
func deliverBackoffDefault(attempt int) time.Duration {
	const base = 500 * time.Millisecond
	const cap = 8 * time.Second
	switch {
	case attempt < 0:
		attempt = 0
	case attempt > 4:
		return cap
	}
	return base << attempt
}

// deliverBackoff 是投递退避 seam（测试可缩短以免长 sleep）；默认即纯函数。
var deliverBackoff = deliverBackoffDefault

// deliverHTTP 是投递专用 HTTP client（包级 seam，测试注入 httptest 的 client）。
var deliverHTTP = &http.Client{Timeout: deliverTimeout}

// ---- 主入口 ---------------------------------------------------------------------

// RunEncounterPack 执行 encounter-pack 内容生产引擎：
//
//	ScanDir（B2）→ DryRun 仅回传清单 → worker-pool 并发每篇 encounter DAG（B5）→
//	成功 pack 可选投递 import-pack → 聚合 Result。
//
// ctx 取消（SIGINT/SIGTERM 冒泡）：worker 尊重 ctx，取消后迅速收尾返回，goroutine
// 零泄露（worker-pool + WaitGroup）。返回部分结果确定性。
func RunEncounterPack(ctx context.Context, t *registry.Registry, g GlossLLM, cfg RunConfig) (Result, error) {
	concurrency := cfg.Concurrency
	if concurrency <= 0 {
		concurrency = 1
	}
	budgetCap := cfg.BudgetTokens
	if budgetCap <= 0 {
		budgetCap = defaultBudgetTokens
	}

	// B2 语料扫描：去重/过滤/限量/排序由 corpus 负责。
	articles, err := corpus.ScanDir(ctx, cfg.CorpusDir, corpus.Options{MaxArticles: cfg.MaxArticles})
	if err != nil {
		return Result{}, fmt.Errorf("job: 扫描语料目录 %q: %w", cfg.CorpusDir, err)
	}

	// DryRun：仅回传清单（预排文章源路径），不执行任何分析/落盘/投递。
	if cfg.DryRun {
		r := Result{Packs: make([]string, 0, len(articles))}
		for _, a := range articles {
			r.Packs = append(r.Packs, a.Path)
		}
		return r, nil
	}

	// 共享预算 + 共享 DAG（dag.DAG 建图后只读，Run 可并发安全重复调用）。
	budget := NewTokenBudget(budgetCap)
	deps := EncounterDeps{Reg: t, Gloss: g, Budget: budget, OutDir: cfg.OutDir}
	dagG, err := BuildEncounterDAG(deps)
	if err != nil {
		return Result{}, fmt.Errorf("job: 构建 encounter DAG: %w", err)
	}

	return runArticles(ctx, dagG, articles, cfg, concurrency)
}

// runArticles 以 worker-pool 并发跑过每篇文章的 encounter DAG，聚合成功 pack 与失败。
// cfg.DeliverURL 非空时在 worker 内对成功 pack 做投递。
func runArticles(ctx context.Context, g *dag.DAG, articles []corpus.Article, cfg RunConfig, concurrency int) (Result, error) {
	jobs := make(chan corpus.Article)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var res Result

	// worker：从 jobs 消费，单篇要么成功进 Packs（可选投递）要么失败进 Failed。
	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for a := range jobs {
				// 尊重取消：ctx 已取消则不再启动新篇（drain 保 worker 收尾）。
				if ctx.Err() != nil {
					mu.Lock()
					res.Failed = append(res.Failed, fmt.Sprintf("%s: %v", a.Path, ctx.Err()))
					mu.Unlock()
					continue
				}
				pr, err := RunOneArticle(ctx, g, a)
				if err != nil {
					mu.Lock()
					res.Failed = append(res.Failed, fmt.Sprintf("%s: %v", a.Path, err))
					mu.Unlock()
					continue
				}
				// 成功：记录 pack；可选投递——投递彻底失败则把该 pack 移入 Failed。
				if cfg.DeliverURL == "" {
					mu.Lock()
					res.Packs = append(res.Packs, pr.Path)
					mu.Unlock()
					continue
				}
				if err := deliverPack(ctx, cfg.DeliverURL, pr.Path); err != nil {
					mu.Lock()
					res.Failed = append(res.Failed, fmt.Sprintf("%s: 投递 import-pack: %v", pr.Path, err))
					mu.Unlock()
					continue
				}
				mu.Lock()
				res.Packs = append(res.Packs, pr.Path)
				mu.Unlock()
			}
		}()
	}

	// producer：ctx select 喂料；ctx 取消即停止喂新 job 并关闭 channel。
outer:
	for _, a := range articles {
		select {
		case <-ctx.Done():
			break outer
		case jobs <- a:
		}
	}
	close(jobs)
	wg.Wait()

	return res, nil
}

// ---- 投递 ----------------------------------------------------------------------

// deliverPack 把已成功落盘的 pack 文件 POST 到 {DeliverURL}/api/encounter/import-pack。
//
// 重试语义（钉死）：1 次初始 + 至多 deliverRetries(3) 次退避重试；每次请求带
// deliverTimeout(5s) 超时（经 NewRequestWithContext）。429、5xx、与瞬时网络错误
// 触发退避重试；其余 4xx（非 429）视为不可恢复立即返回。所有重试耗尽仍失败则
// 返回最后一次错误。ctx 取消在退避/请求中尽早返回 ctx.Err()。
func deliverPack(ctx context.Context, baseURL, packPath string) error {
	data, err := os.ReadFile(packPath)
	if err != nil {
		return fmt.Errorf("读取 pack %s: %w", packPath, err)
	}
	url := baseURL + deliverEndpoint

	var lastErr error
	for attempt := 0; attempt <= deliverRetries; attempt++ {
		if attempt > 0 {
			// 相邻尝试间按 deliverBackoff(attempt-1) 退避（ctx 可中断）。
			timer := time.NewTimer(deliverBackoff(attempt - 1))
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			}
			timer.Stop()
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(data))
		if err != nil {
			return fmt.Errorf("构建投递请求: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := deliverHTTP.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("请求 import-pack: %w", err)
			continue // 瞬时网络错误视为可重试
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		_ = resp.Body.Close()

		switch {
		case resp.StatusCode == http.StatusOK:
			return nil
		case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
			lastErr = fmt.Errorf("import-pack 返回 %d", resp.StatusCode)
			continue
		default:
			// 其余 4xx（非 429）为不可恢复，立即返回。
			return fmt.Errorf("import-pack 返回不可恢复状态 %d", resp.StatusCode)
		}
	}
	if lastErr == nil {
		lastErr = errors.New("import-pack 投递失败")
	}
	return lastErr
}
