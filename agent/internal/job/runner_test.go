package job

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// ---- 本地 fixture 装配 -----------------------------------------------------------

// writeArt 在 corpus 目录下写一篇 .txt 语料（内容即正文，文件名去扩展为 Title）。
func writeArt(t *testing.T, root, name, content string) string {
	t.Helper()
	path := filepath.Join(root, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
	return path
}

// fastAnalyze 是快速成功的 analyze fake（返回与 python analyze 同构的 sentences）。
func fastAnalyze() registry.ToolFunc {
	return func(context.Context, map[string]any) (map[string]any, error) {
		return fixedAnalyzeOut(), nil
	}
}

// fastVocab 是快速成功的 vocab_stats fake（返回覆盖统计 + unknown_ranked）。
func fastVocab() registry.ToolFunc {
	return func(context.Context, map[string]any) (map[string]any, error) {
		return map[string]any{
			"tokens_total": 4,
			"known_count":  3,
			"known_rate":   0.75,
			"level_hint":   "A2",
			"unknown_ranked": []any{
				map[string]any{"lemma": "gehen", "count": 1},
			},
		}, nil
	}
}

// regWith 构造带 analyze/vocab_stats 两个 fake 的 registry。
func regWith(t *testing.T, analyze, vocab registry.ToolFunc) *registry.Registry {
	t.Helper()
	reg := registry.NewRegistry()
	if err := reg.Register("analyze", analyze); err != nil {
		t.Fatalf("注册 analyze: %v", err)
	}
	if err := reg.Register("vocab_stats", vocab); err != nil {
		t.Fatalf("注册 vocab_stats: %v", err)
	}
	return reg
}

// defaultRunnerCfg 给出一份通用运行配置（CorpusDir/OutDir 就地以 tmp 填充）。
func defaultRunnerCfg(corpusDir, outDir string) RunConfig {
	return RunConfig{
		CorpusDir:    corpusDir,
		OutDir:       outDir,
		Concurrency:  2,
		BudgetTokens: 100_000,
	}
}

// resultPaths 排序取出 Result.Packs（断言用，忽略顺序）。
func resultPacks(r Result) []string {
	out := append([]string(nil), r.Packs...)
	sort.Strings(out)
	return out
}

// resultFailedPaths 从 Failed 行（格式 "<path>: <err>"）中抽 path 前缀（排序）。
// 注：不能按首个冒号切——Windows 绝对路径本身含盘符冒号（如 C:\…）；路径内冒号
// 后从不紧跟空格，故按首个 ": "（冒号+空格）作为 path 与 err 的分界。
func resultFailedPaths(r Result) []string {
	var out []string
	for _, line := range r.Failed {
		if i := strings.Index(line, ": "); i >= 0 {
			out = append(out, strings.TrimSpace(line[:i]))
		} else {
			out = append(out, line)
		}
	}
	sort.Strings(out)
	return out
}

// ---- 1) 并发上限 ----------------------------------------------------------------

// TestRunner_ConcurrencyCap 断言 worker-pool 把最大在飞文章数钳制在 Concurrency 内：
// 慢 fake analyze（sleep）记录并发峰值，用 2 并发跑 5 篇，峰值应恰好等于 2。
func TestRunner_ConcurrencyCap(t *testing.T) {
	root := t.TempDir()
	for i := 0; i < 5; i++ {
		writeArt(t, root, string(rune('a'+i))+".txt", strings.Repeat(string(rune('a'+i)), 40))
	}

	var mu sync.Mutex
	cur, max := 0, 0
	analyze := func(ctx context.Context, _ map[string]any) (map[string]any, error) {
		mu.Lock()
		cur++
		if cur > max {
			max = cur
		}
		mu.Unlock()

		// 慢步：保证并发 worker 同时处于 analyze（受短窗口约束，禁长 sleep）。
		select {
		case <-time.After(40 * time.Millisecond):
		case <-ctx.Done():
		}
		mu.Lock()
		cur--
		mu.Unlock()
		return fixedAnalyzeOut(), nil
	}
	reg := regWith(t, analyze, fastVocab())
	gloss := &fakeGloss{rec: &recorder{}}

	outDir := t.TempDir()
	cfg := defaultRunnerCfg(root, outDir)
	cfg.Concurrency = 2
	res, err := RunEncounterPack(context.Background(), reg, gloss, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack: %v", err)
	}
	if max != 2 {
		t.Errorf("最大在飞应为 2（Concurrency），实得 %d", max)
	}
	if max > cfg.Concurrency {
		t.Fatalf("并发超限：max=%d > concurrency=%d", max, cfg.Concurrency)
	}
	if len(res.Packs) != 5 {
		t.Errorf("5 篇全部成功应 5 个 pack，实得 %d", len(res.Packs))
	}
}

// ---- 2) 预算耗尽降级 ------------------------------------------------------------

// TestRunner_BudgetExhaustedDegrades 断言共享预算耗尽后的降级语义：
//   - 4 篇正文各 40 个无空白字符 → 每篇 gloss Reserve 估算 = 40/4+1 = 11；
//   - BudgetTokens=22 → 恰前 2 篇 Reserve 成功并调 LLM；第 3、4 篇在跑完
//     analyze/vocab_stats 后于 gloss 因 ErrBudgetExceeded 快速失败（不调 LLM、不落盘）；
//   - 总 LLM 调用恰 2 次——预算耗尽后绝不再调 LLM。
func TestRunner_BudgetExhaustedDegrades(t *testing.T) {
	root := t.TempDir()
	for i := 0; i < 4; i++ {
		// 每篇 40 字符单 token 文本（无空白→ 1 词），内容互异防内容去重。
		writeArt(t, root, string(rune('a'+i))+".txt", strings.Repeat(string(rune('a'+i)), 40))
	}
	reg := regWith(t, fastAnalyze(), fastVocab())
	rec := &recorder{}
	gloss := &fakeGloss{rec: rec}

	outDir := t.TempDir()
	cfg := defaultRunnerCfg(root, outDir)
	cfg.Concurrency = 1 // 串行保证"前 2 篇先于后 2 篇"确定
	cfg.BudgetTokens = 22

	res, err := RunEncounterPack(context.Background(), reg, gloss, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack: %v", err)
	}
	if len(res.Packs) != 2 {
		t.Errorf("预算 22 / 每篇 11 → 应恰 2 篇成功，实得 %d", len(res.Packs))
	}
	if len(res.Failed) != 2 {
		t.Fatalf("应恰 2 篇失败（预算耗尽），实得 %d：%v", len(res.Failed), res.Failed)
	}
	for _, line := range res.Failed {
		if !strings.Contains(line, ErrBudgetExceeded.Error()) {
			t.Errorf("失败行应以 ErrBudgetExceeded 语义标识，实得 %q", line)
		}
	}
	_, _, calls := gloss.snapshot()
	if calls != 2 {
		t.Errorf("预算耗尽后不应再调 LLM：总调用应恰 2 次，实得 %d", calls)
	}
	// 预算失败篇不落盘：outDir 只有 2 个 pack。
	if matches, _ := filepath.Glob(filepath.Join(outDir, "*.pack.json")); len(matches) != 2 {
		t.Errorf("预算失败篇不应落盘，实得 %d 个文件：%v", len(matches), matches)
	}
}

// ---- 3) 失败隔离 ----------------------------------------------------------------

// TestRunner_FailIsolation 断言单篇 analyze 失败只记进 Failed，不影响他篇成功。
func TestRunner_FailIsolation(t *testing.T) {
	root := t.TempDir()
	writeArt(t, root, "good1.txt", "first good article body")
	writeArt(t, root, "good2.txt", "second good article body")
	marker := writeArt(t, root, "bad.txt", "this one fails analyze")

	reg := regWith(t,
		func(_ context.Context, payload map[string]any) (map[string]any, error) {
			if text, _ := payload["text"].(string); text == "this one fails analyze" {
				return nil, errors.New("analyze boom")
			}
			return fixedAnalyzeOut(), nil
		},
		fastVocab(),
	)
	gloss := &fakeGloss{rec: &recorder{}}
	outDir := t.TempDir()
	cfg := defaultRunnerCfg(root, outDir)
	cfg.Concurrency = 3

	res, err := RunEncounterPack(context.Background(), reg, gloss, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack 不应因单篇失败整体报错: %v", err)
	}
	if len(res.Packs) != 2 {
		t.Errorf("应 2 篇成功，实得 %d：%v", len(res.Packs), res.Packs)
	}
	fail := resultFailedPaths(res)
	if len(fail) != 1 || fail[0] != marker {
		t.Errorf("Failed 应恰含坏篇 %q，实得 %v", marker, fail)
	}
}

// ---- 4) 投递：body envelope schema + 429 重试成功 + 500 耗尽重试 ------------------

// TestRunner_DeliverBackoff 断言投递语义（httptest 桩）：
//   - 每成功 pack 都被 POST /api/encounter/import-pack，body 为 {"pack": <pack>}
//     信封：外层含 pack 键，且内层 pack 解析后 schema == encounter-pack/v1；
//   - retry 篇：服务端先回 429、429 再 200 → 经 2 次重试成功，留 Packs；
//   - alwaysfail 篇：服务端恒 500 → 恰 1 初始 + 3 重试 = 4 次请求后记入 Failed；
//   - 幂等/多请求计数断言。
func TestRunner_DeliverBackoff(t *testing.T) {
	root := t.TempDir()
	writeArt(t, root, "retry.txt", "retry target article body")
	writeArt(t, root, "alwaysfail.txt", "always fail target article body")

	// 缩短退避（seam）以免长 sleep。
	orig := deliverBackoff
	deliverBackoff = func(int) time.Duration { return time.Millisecond }
	defer func() { deliverBackoff = orig }()

	var mu sync.Mutex
	counts := map[string]int{} // key = article title
	schemas := []string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != deliverEndpoint {
			t.Errorf("投递路径应为 %q，实得 %q", deliverEndpoint, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var env struct {
			Pack json.RawMessage `json:"pack"`
		}
		if err := json.Unmarshal(body, &env); err != nil {
			t.Errorf("投递 body 外层应含 pack 信封键，解析失败: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if len(env.Pack) == 0 {
			t.Errorf("投递 body 外层应含非空 pack 键")
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		var p Pack
		if err := json.Unmarshal(env.Pack, &p); err != nil {
			t.Errorf("投递 body 内层 pack 应可解析为 Pack: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		mu.Lock()
		schemas = append(schemas, p.Schema)
		counts[p.Article.Title]++
		n := counts[p.Article.Title]
		mu.Unlock()
		switch {
		case p.Article.Title == "retry" && n < 3:
			w.WriteHeader(http.StatusTooManyRequests) // 前两次 429
		case p.Article.Title == "retry":
			w.WriteHeader(http.StatusOK) // 第三次 200
		case p.Article.Title == "alwaysfail":
			w.WriteHeader(http.StatusInternalServerError) // 恒 500
		default:
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer srv.Close()

	reg := regWith(t, fastAnalyze(), fastVocab())
	gloss := &fakeGloss{rec: &recorder{}}
	outDir := t.TempDir()
	cfg := defaultRunnerCfg(root, outDir)
	cfg.Concurrency = 1 // 串行使每篇投递请求计数确定
	cfg.DeliverURL = srv.URL

	res, err := RunEncounterPack(context.Background(), reg, gloss, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()
	// body schema 全对。
	if len(schemas) != counts["retry"]+counts["alwaysfail"] {
		t.Errorf("投递请求总数与记录不符")
	}
	for _, s := range schemas {
		if s != CARD_PACK_SCHEMA {
			t.Errorf("投递 body schema 应 %q，实得 %q", CARD_PACK_SCHEMA, s)
		}
	}
	// retry：3 次请求（429,429,200）后成功 → 在 Packs。
	if counts["retry"] != 3 {
		t.Errorf("retry 应恰 3 次请求（1 初始 + 2 重试），实得 %d", counts["retry"])
	}
	// alwaysfail：恒 500 → 1 初始 + 3 重试 = 4 次后记 Failed。
	if counts["alwaysfail"] != 4 {
		t.Errorf("alwaysfail 应恰 4 次请求（1 初始 + 3 重试），实得 %d", counts["alwaysfail"])
	}
	// Packs 只含 retry；Failed 含 alwaysfail。
	packs := resultPacks(res)
	fails := resultFailedPaths(res)
	if len(packs) != 1 || !strings.Contains(packs[0], "retry") {
		t.Errorf("成功 pack 应只含 retry，实得 %v", res.Packs)
	}
	if len(fails) != 1 || !strings.Contains(fails[0], "alwaysfail") {
		t.Errorf("Failed 应只含 alwaysfail（含 pack 路径），实得 %v", res.Failed)
	}
}

// ---- 5) ctx cancel：goroutine 零泄露 + 迅速收尾 ---------------------------------

// TestRunner_ContextCancel 断言 ctx 中途取消：RunEncounterPack 迅速返回（无挂死），
// 部分失败结果确定（-race 配合证 goroutine 零泄露）。
func TestRunner_ContextCancel(t *testing.T) {
	root := t.TempDir()
	for i := 0; i < 6; i++ {
		writeArt(t, root, string(rune('a'+i))+".txt", strings.Repeat(string(rune('a'+i)), 30))
	}

	var started int32
	blockingAnalyze := func(ctx context.Context, _ map[string]any) (map[string]any, error) {
		atomic.AddInt32(&started, 1)
		<-ctx.Done() // 尊重 ctx：取消后立即返回
		return nil, ctx.Err()
	}
	reg := regWith(t, blockingAnalyze, fastVocab())
	gloss := &fakeGloss{rec: &recorder{}}
	outDir := t.TempDir()
	cfg := defaultRunnerCfg(root, outDir)
	cfg.Concurrency = 3

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	var res Result
	var runErr error
	go func() {
		defer close(done)
		res, runErr = RunEncounterPack(ctx, reg, gloss, cfg)
	}()

	// 等至少 1 篇已进入阻塞 analyze（说明 worker 已在跑），再取消。
	deadline := time.Now().Add(2 * time.Second)
	for atomic.LoadInt32(&started) < 1 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	cancel()

	select {
	case <-done:
		// 正常返回：worker-pool 已全部收尾（runArticles wg.Wait 保证）。
	case <-time.After(3 * time.Second):
		t.Fatal("ctx 取消后 RunEncounterPack 未迅速返回（可能 goroutine 泄露/挂死）")
	}
	if runErr != nil {
		t.Fatalf("取消不应使整体 run 返回 error（单篇失败聚合进 Failed）: %v", runErr)
	}
	// 部分结果确定：至少 1 篇进入过 analyze 并因取消记入 Failed。
	if n := atomic.LoadInt32(&started); n < 1 {
		t.Errorf("应至少 1 篇进入 analyze，实得 %d", n)
	}
	if len(res.Failed) < 1 {
		t.Errorf("取消时在跑篇应记入 Failed，实得 %v", res.Failed)
	}
}

// ---- 6) DryRun：仅回传清单，不执行 -------------------------------------------------

// TestRunner_DryRun 断言 DryRun：不写 OutDir、不调 LLM、不回投递，仅回传文章源清单
// （Result.Packs = 预排文章路径）。
func TestRunner_DryRun(t *testing.T) {
	root := t.TempDir()
	want := []string{
		writeArt(t, root, "a.txt", "alpha article body"),
		writeArt(t, root, "b.txt", "bravo article body"),
		writeArt(t, root, "c.txt", "charlie article body"),
	}
	sort.Strings(want)

	gloss := &fakeGloss{rec: &recorder{}} // 若被调用会 rec 记录，以此断言未调 LLM
	outDir := t.TempDir()

	// 故意让 analyze 若被执行会 fail——DryRun 不应触碰 registry。
	boom := regWith(t,
		func(context.Context, map[string]any) (map[string]any, error) {
			return nil, errors.New("dry run must not call tools")
		},
		fastVocab(),
	)

	cfg := defaultRunnerCfg(root, outDir)
	cfg.DryRun = true
	cfg.DeliverURL = "http://127.0.0.1:9999" // 即便配置了投递也不应执行

	res, err := RunEncounterPack(context.Background(), boom, gloss, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack(dry-run): %v", err)
	}
	if len(res.Failed) != 0 {
		t.Errorf("DryRun 不应有失败，实得 %v", res.Failed)
	}
	got := resultPacks(res)
	if len(got) != len(want) {
		t.Fatalf("DryRun 清单应含 %d 篇，实得 %d：%v", len(want), len(got), res.Packs)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("DryRun 清单第 %d 项应为 %q，实得 %q", i, want[i], got[i])
		}
	}
	// OutDir 无写入；LLM 未被调用。
	if matches, _ := filepath.Glob(filepath.Join(outDir, "*.pack.json")); len(matches) != 0 {
		t.Errorf("DryRun 不应落盘，实得 %v", matches)
	}
	if _, _, calls := gloss.snapshot(); calls != 0 {
		t.Errorf("DryRun 不应调 LLM，实得 %d 次", calls)
	}
}

// ---- 全局错误语义：ScanDir 失败 → 返回 error -------------------------------------

// TestRunner_ScanDirError 断言非可恢复全局错误（语料目录不存在）直接返回 error。
func TestRunner_ScanDirError(t *testing.T) {
	reg := regWith(t, fastAnalyze(), fastVocab())
	gloss := &fakeGloss{rec: &recorder{}}
	cfg := defaultRunnerCfg(filepath.Join(t.TempDir(), "no-such-dir"), t.TempDir())
	_, err := RunEncounterPack(context.Background(), reg, gloss, cfg)
	if err == nil {
		t.Fatal("不存在的语料目录应返回错误")
	}
}
