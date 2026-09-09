// job.go 注册 `delector job` 命令族（Sub-Plan B Task B7）：首个真执行 job
// `delector job run encounter-pack`——扫描本地语料目录 → 去重/限量/并发 → 每篇
// encounter-pack DAG（analyze→vocab_stats→gloss→export_pack，B5）→ 可选投递
// import-pack，汇总打印 packs/failed 计数并按失败数决定退出码。
//
// 接线顺序（镜像计划 Sub-Plan B Task B7 的运行流程）：
//
//  1. python 可达性：--python-url 为空 → 仿 `delector run` 以 supervisor 起托管
//     Python 于 127.0.0.1:8001（复用 app.NewSupervisor / BaseURLForPort，不复制
//     run 的装配长逻辑）；非空则直连给定 URL。
//  2. registry = DefaultRegistry（须含 vocab_stats 等 6 工具，否则报错）。
//  3. signal.NotifyContext(SIGINT/SIGTERM) 取消 ctx（SIGINT/SIGTERM 冒泡给 job）。
//  4. *llm.Client：BaseURL=--llm-base-url（空→DeepSeek 官方）；DEEPSEEK_API_KEY
//     仅经环境变量，绝不打/写。dry-run 不构造 LLM（返回清单不调 gloss）。
//  5. job.RunEncounterPack（内部 corpus.ScanDir）跑过语料。
//  6. 打印 Result（packs/failed 计数）；退出码：Failed 非空 或 错误 → 1，否则 0。
//
// 设计决策：
//   - python 可达性在 dry-run 同样需要（计划流程把 python 排在 RunEncounterPack
//     的 dry-run 清单之前，本命令遵循：supervisor/直连就绪后才谈清单）。
//   - supervisor 清理仿 run：以独立 Background procCtx spawn（子进程寿命经
//     supervisor.Stop 经 cmd.Cancel 管理，不耦合调用方信号 ctx——2a T7 教训），
//     defer stop 保证无论成败/取消都被清理。
//   - LLM 在 dry-run 下不构造（dry-run 不调 gloss，避免无 key 时 dry-run 也失败）。
//   - 真执行路径（spawn/registry/LLM/RunEncounterPack）统收进 runEncounterJob，
//     供未来注入 seam/集成门禁复用；RunE 只做信号 ctx 装配 + 打印 + 退出码映射。
//     单测不真跑 python：仅测 flag 解析 / 必填校验 / --help 文案 / 命令树。
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/app"
	"github.com/ROM4n2/DeLector/agent/internal/job"
	"github.com/ROM4n2/DeLector/agent/internal/llm"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
	"github.com/spf13/cobra"
)

// encounter 常量：spawn 端口与各 flag 默认值（Task B7 钉死）。
const (
	// jobSpawnPort 是 --python-url 为空时 supervisor 起的托管端口（归 agent 专用）。
	jobSpawnPort = 8001
	// defaultEncounterConcurrency 默认并发 worker 数。
	defaultEncounterConcurrency = 4
	// defaultEncounterBudget 默认共享 token 预算（DeepSeek 真调用防失控护栏）。
	defaultEncounterBudget = 100_000
	// defaultEncounterMaxArticles 默认语料限量护栏（评审 ⑥）：默认不扫空整个
	// 目录——限量在 corpus 读取前截断，控时间/预算/落盘规模；0 才表示不限。
	defaultEncounterMaxArticles = 200
	// defaultEncounterMaxFileBytes 默认单文件大小护栏（评审 ④/⑥）：超限语料
	// 文件直接跳过，防单篇巨文拖垮内存/超时；0 才表示不限。
	defaultEncounterMaxFileBytes = 1 << 20 // 1 MiB
	// defaultDeliverURL 默认 import-pack 投递端点根（用户直接起的 8000 实例）。
	defaultDeliverURL = "http://127.0.0.1:8000"
)

// newJobCmd 注册 `delector job` 父命令；其下挂 encounter-pack 执行子命令。
func newJobCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "job",
		Short: "运行 DAG 数据流水线 job（首个：encounter-pack 语料→分级卡包内容生产）",
		Long: `delector job 运行 agent 侧的 DAG job 流水线。

目前支持的 job：

  run encounter-pack    扫描本地语料 → 逐篇 encounter-pack 内容生产（可投递）`,
	}
	cmd.AddCommand(newRunEncounterCmd())
	return cmd
}

// encounterOptions 承载 encounter-pack 子命令一次运行的 flag 值。
type encounterOptions struct {
	corpus       string        // 语料根目录（必填）
	out          string        // pack 落盘目录（必填）
	concurrency  int           // 并发 worker 上限
	maxArticles  int           // 语料限量（0=不限；默认 200 护栏）
	maxFileBytes int64         // 语料单文件大小上限字节（0=不限；默认 1MiB）
	budgetTokens int           // 共享 token 预算
	timeout      time.Duration // job 墙钟上限（0=job 内置默认 2h）
	dryRun       bool          // 仅回传清单不执行
	pythonURL    string        // 空=自动 supervisor 起 python 于 8001；非空直连
	deliverURL   string        // 非空时对成功 pack POST import-pack
	llmBaseURL   string        // 空=DeepSeek 官方；测试/桩用
}

// newRunEncounterCmd 注册 `delector job run encounter-pack` 子命令。
func newRunEncounterCmd() *cobra.Command {
	var o encounterOptions
	cmd := &cobra.Command{
		Use:   "run encounter-pack",
		Short: "扫描语料目录并逐篇产出 encounter-pack 卡包（job#1 真执行，可 dry-run/投递）",
		Long: `扫描 --corpus 目录下的本地语料（.txt/.md），去重/限量后并发逐篇跑
encounter-pack 内容生产 DAG（analyze→vocab_stats→gloss→export_pack），
把分级卡包 Pack 写入 --out。--deliver-url 非空时对成功 pack 投递
POST /api/encounter/import-pack。

--dry-run 时仅回传预排语料清单，不执行任何分析/落盘/投递。

退出码：全部成功 → 0；存在单篇失败 或 发生错误 → 1。`,
		PreRunE: func(cmd *cobra.Command, _ []string) error {
			return validateEncounterRequired(o)
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			// 参数加固：把"encounter-pack"位置参数校到位（cobra 多词 Use 以
			// 首词 Name="run" 路由，encounter-pack 经 args[0] 传入）。
			if len(args) != 1 || args[0] != "encounter-pack" {
				return fmt.Errorf("未知子命令 %q：用法见 delector job run --help", strings.Join(args, " "))
			}
			// SIGINT/SIGTERM → ctx 取消 → RunEncounterPack 尊重 ctx 快速收尾，
			// supervisor（如已起）经 defer stop 清理（仿 run 命令优雅退出）。
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()

			res, err := runEncounterJob(ctx, o)
			if err != nil {
				return err
			}
			printEncounterResult(cmd, res)
			if len(res.Failed) > 0 {
				return fmt.Errorf("encounter-pack 完成，但 %d 篇失败（退出码 1）", len(res.Failed))
			}
			return nil
		},
	}
	fl := cmd.Flags()
	fl.StringVar(&o.corpus, "corpus", "", "语料根目录（必填；扫描 .txt/.md）")
	fl.StringVar(&o.out, "out", "", "pack 落盘目录（必填；自动创建）")
	fl.IntVar(&o.concurrency, "concurrency", defaultEncounterConcurrency, "并发 worker 上限（默认 4）")
	fl.IntVar(&o.maxArticles, "max-articles", defaultEncounterMaxArticles, "语料限量（默认 200=护栏，读取前截断；0=不限）")
	fl.Int64Var(&o.maxFileBytes, "max-file-bytes", defaultEncounterMaxFileBytes, "语料单文件大小上限字节（默认 1048576=1MiB 护栏；超限文件跳过；0=不限）")
	fl.IntVar(&o.budgetTokens, "budget-tokens", defaultEncounterBudget, "共享 token 预算上限（默认 100_000）")
	fl.DurationVar(&o.timeout, "timeout", 0, "job 墙钟超时（默认 0=内置 2h 护栏；显式传如 30m/1h30m 覆盖）")
	fl.BoolVar(&o.dryRun, "dry-run", false, "仅回传预排语料清单，不执行分析/落盘/投递")
	fl.StringVar(&o.pythonURL, "python-url", "", "Python NLP 服务地址；空=自动 supervisor 起于 127.0.0.1:8001，非空则直连")
	fl.StringVar(&o.deliverURL, "deliver-url", defaultDeliverURL, "投递 import-pack 的根地址（空则跳过投递）")
	fl.StringVar(&o.llmBaseURL, "llm-base-url", "", "DeepSeek 兼容 API 根地址；空=DeepSeek 官方（测试/桩用）")
	return cmd
}

// validateEncounterRequired 校验必填 flag（--corpus/--out）。缺任一在 RunE 装配
// （supervisor/registry/LLM）之前即报错——单测据此断言错误而不触 python。
func validateEncounterRequired(o encounterOptions) error {
	if o.corpus == "" {
		return errors.New("缺少必填参数 --corpus（语料根目录）")
	}
	if o.out == "" {
		return errors.New("缺少必填参数 --out（pack 落盘目录）")
	}
	return nil
}

// printEncounterResult 打印 job 汇总（packs/failed 计数 + 逐条失败行）。
func printEncounterResult(cmd *cobra.Command, res job.Result) {
	fmt.Fprintf(cmd.OutOrStdout(), "[delector] encounter-pack: packs=%d failed=%d\n",
		len(res.Packs), len(res.Failed))
	for _, f := range res.Failed {
		fmt.Fprintf(cmd.OutOrStdout(), "[delector]   failed: %s\n", f)
	}
}

// runEncounterJob 执行 encounter-pack 流水线（python 可达性 → registry → ctx →
// LLM → RunEncounterPack → Result）。真执行路径统收此处，供未来注入 seam 复用；
// 单测不真跑 python，故本函数只在用户真跑命令 / 集成门禁时被调用。
func runEncounterJob(ctx context.Context, o encounterOptions) (job.Result, error) {
	// 防御性校验（正常经 PreRunE 拦截；此处防直接调用漏检），绝不触碰 python。
	if err := validateEncounterRequired(o); err != nil {
		return job.Result{}, err
	}

	// 步骤 1: python 可达性。
	baseURL := o.pythonURL
	if baseURL == "" {
		// 仿 run 流程：以独立 Background procCtx spawn 托管 python 于 8001；
		// 子进程寿命经 supervisor.Stop（cmd.Cancel）管理，不耦合调用方信号 ctx。
		exe := exeDir()
		sup := app.NewSupervisor(app.Options{
			Port:           jobSpawnPort,
			PythonCmd:      resolvePythonCmd(exe),
			PythonSrcDir:   resolvePythonSrcDir(exe),
			PythonExtraEnv: extraEnvFromOS(),
		})
		if err := sup.Start(context.Background()); err != nil {
			return job.Result{}, fmt.Errorf("job: 启动托管 python: %w", err)
		}
		// defer 清理：无论正常结束 / RunEncounterPack 失败 / ctx 取消都 Stop，
		// 与 run 的优雅退出同构。
		defer sup.Stop()
		baseURL = app.BaseURLForPort(jobSpawnPort)
	}

	// 步骤 2: registry = DefaultRegistry（须含 vocab_stats 等 6 工具）。
	reg := registry.DefaultRegistry(pythonsvc.NewClient(baseURL, nil))
	if err := validateEncounterRegistry(reg); err != nil {
		return job.Result{}, err
	}

	// 步骤 3: ctx 已由调用方经 signal.NotifyContext 装配（SIGINT/SIGTERM → ctx 取消）。
	// 步骤 4: LLM client —— 仅非 dry-run 需要（dry-run 返回清单不调 gloss，无 key
	// 也可跑 dry-run）。BaseURL 空→官方；DEEPSEEK_API_KEY 仅环境变量读，不打/写。
	var gloss job.GlossLLM
	if !o.dryRun {
		c, err := llm.NewClient(llm.Config{BaseURL: o.llmBaseURL})
		if err != nil {
			return job.Result{}, fmt.Errorf("job: 初始化 LLM: %w", err)
		}
		gloss = c
	}

	// 步骤 5: RunEncounterPack（内部 corpus.ScanDir 去重/限量/排序 → per-article DAG
	// → 可选投递）。dry-run 时 gloss 为 nil 亦安全（RunEncounterPack 提前返回清单）。
	cfg := job.RunConfig{
		CorpusDir:    o.corpus,
		OutDir:       o.out,
		Concurrency:  o.concurrency,
		MaxArticles:  o.maxArticles,
		MaxFileBytes: o.maxFileBytes,
		BudgetTokens: o.budgetTokens,
		Timeout:      o.timeout,
		DryRun:       o.dryRun,
		DeliverURL:   o.deliverURL,
	}
	res, err := job.RunEncounterPack(ctx, reg, gloss, cfg)
	if err != nil {
		return res, fmt.Errorf("job: 执行 encounter-pack: %w", err)
	}
	// 步骤 6: 打印 + 退出码由调用方（RunE）处理。
	return res, nil
}

// validateEncounterRegistry 断言 DefaultRegistry 已含 vocab_stats（6 工具），
// 防止 Python 侧 TOOL_REGISTRY 与 Go 侧 defaultTools 漂移时 job 静默走偏。
func validateEncounterRegistry(reg *registry.Registry) error {
	if !reg.Has("vocab_stats") {
		return errors.New("job: registry 缺 vocab_stats——需含 6 工具（analyze/vocab_stats 等）才能执行 encounter-pack")
	}
	return nil
}
