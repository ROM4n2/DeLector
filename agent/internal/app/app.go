// Package app 是 `delector run` 的组装层：把 Python 托管进程（pythonsvc
// Supervisor）、工具注册表（registry）与 DAG 预设（dag）装配为常驻服务。
//
// 装配顺序（单测经注入 seam 钉死）：
//
//	supervisor.Start → registry → DAG 预设构建 → 常驻（<-ctx.Done()）→ supervisor.Stop
//
// ctx 取消即优雅退出：先 Stop supervisor（经 cmd.Cancel：SIGTERM/kill，详见
// pythonsvc），再返回；子进程 ctx 与调用方退出信号 ctx 解耦（见 Run 注释）。
// 错误一律以 %w 透传，禁止吞错。
//
// 依赖方向：cmd → app → {pythonsvc, registry, dag}；app 不反向被依赖。
package app

import (
	"context"
	"fmt"
	"path/filepath"
	"runtime"
	"strconv"

	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// defaultPort 是 agent 托管 Python 实例默认端口（Global Constraints：8001
// 归 agent 专用，8000 留给用户直接启动的实例）。
const defaultPort = 8001

// Options 是 Run 的装配参数。
type Options struct {
	// Port 托管实例监听端口；0 表示用 defaultPort（8001）。
	Port int
	// DataDir 数据目录：注入子进程 DATABASE_PATH / DELECTOR_DATA_DIR，
	// 绝不触碰用户库。空串时跳过注入（测试 / 无状态场景）。
	DataDir string
	// PythonCmd 包内 venv python 解释器绝对路径（Phase 2b T3 绿色便携包
	// 自包含 python）。空串时 supervisorConfig 回退 "python"（系统解释器，
	// dev 模式零改动）。仅作 argv[0]，完整 uvicorn 命令由 supervisorConfig 拼。
	PythonCmd string
	// PythonSrcDir 包内 python 源根（<exeDir>/delector-src：含 delector 包 +
	// static + start.py）；非空时经 PYTHONPATH 注入，使 uvicorn 可 import
	// delector.server:app。空串时 pythonEnv 回退到仓库根（2a T7 runtime.Caller
	// 上溯），dev 模式零改动。
	PythonSrcDir string
	// PythonExtraEnv 追加到托管 Python 子进程环境的 KEY=VALUE；用于透传
	// 凭证（如 DEEPSEEK_API_KEY）。DataDir 注入与 PYTHONIOENCODING /
	// PYTHONPATH 由 Run 自动补，勿在此重复。
	PythonExtraEnv []string
}

// supervisor 是 app 对托管进程的最小抽象（生产实现为 *pythonsvc.Supervisor）。
// 单测经 newSupervisor seam 注入 fake，避免真实起 Python。
type supervisor interface {
	Start(ctx context.Context) error
	Stop()
}

// newSupervisor 构造托管进程（生产：*pythonsvc.Supervisor）。单测覆盖以注入 fake。
var newSupervisor = func(opts Options) supervisor {
	return pythonsvc.NewSupervisor(supervisorConfig(opts))
}

// newRegistry 构造默认工具注册表（生产：registry.DefaultRegistry(client)）。
// 单测覆盖以注入 fake。
var newRegistry = func(port int) *registry.Registry {
	return registry.DefaultRegistry(pythonsvc.NewClient(baseURLForPort(port), nil))
}

// buildArticleDAG 构建 article-analysis DAG 预设（生产：dag.ArticleAnalysisDAG）。
// 单测覆盖以钉 DAG 构建发生在 registry 之后。
var buildArticleDAG = func(tools *registry.Registry) (*dag.DAG, error) {
	return dag.ArticleAnalysisDAG(tools)
}

// Run 装配 supervisor + registry + DAG 预设并常驻，直至 ctx 取消后优雅退出。
// 装配期错误（Start 失败 / DAG 构建失败）以 %w 透传；ctx 取消时 Stop supervisor。
//
// 子进程 ctx 解耦：sup.Start 收到派生于 context.Background 的 procCtx，与调用方
// 退出信号 ctx 完全独立——Python 子进程寿命由 supervisor.Stop 经 cmd.Cancel
// （SIGTERM/kill，详见 pythonsvc）管理，不再经 exec.CommandContext 的调用方 ctx
// 强杀。信号 ctx 取消仅作退出信号（触发 sup.Stop），取消时机不再与探针竞态，
// 避免误杀仍在探针/运行中的子进程（2a T7 教训：勿用调用方 ctx 代管子进程寿命）。
func Run(ctx context.Context, opts Options) error {
	if err := validateOpts(opts); err != nil {
		return fmt.Errorf("app: 参数校验失败: %w", err)
	}
	// procCtx：子进程专用 ctx，派生自 Background，独立于调用方退出信号 ctx。
	// 仅 supervisor.Stop 经 cmd.Cancel 终止子进程；procCtx 自身不再被取消，
	// 从而解耦 sub-process 寿命与退出信号（2a T7）。
	procCtx := context.Background()
	sup := newSupervisor(opts)
	if err := sup.Start(procCtx); err != nil {
		return fmt.Errorf("app: 启动 Python 托管进程: %w", err)
	}
	reg := newRegistry(opts.Port)
	g, err := buildArticleDAG(reg)
	if err != nil {
		// DAG 预设构建失败：已起的 Python 必须释放，避免子进程泄漏。
		sup.Stop()
		return fmt.Errorf("app: 构建 article-analysis DAG 预设: %w", err)
	}
	// 常驻：暴露 registry + DAG 预设，直到调用方 ctx 取消（Ctrl+C / SIGTERM）。
	// g 已构建并持有，供上层编排触发（本 Task 仅常驻暴露，不循环执行）。
	_ = g
	<-ctx.Done()
	sup.Stop()
	return nil
}

// validateOpts 装配前参数校验：端口必须合法（0=默认，否则 1..65535）。
func validateOpts(opts Options) error {
	if opts.Port < 0 || opts.Port > 65535 {
		return fmt.Errorf("端口 %d 超出合法范围 [0, 65535]", opts.Port)
	}
	return nil
}

// supervisorConfig 由 Options 构造 SupervisorConfig：端口覆盖 PythonCmd，
// 注入 DataDir 的 DATABASE_PATH / DELECTOR_DATA_DIR + PYTHONIOENCODING +
// PYTHONPATH（仓库根上溯，2a T7 同款）。
func supervisorConfig(opts Options) pythonsvc.SupervisorConfig {
	port := opts.Port
	if port == 0 {
		port = defaultPort
	}
	// pythonExe：包内 venv python 绝对路径，空串回退系统 "python"（dev）。
	pythonExe := opts.PythonCmd
	if pythonExe == "" {
		pythonExe = "python"
	}
	return pythonsvc.SupervisorConfig{
		PythonCmd: []string{
			pythonExe, "-m", "uvicorn", "delector.server:app",
			"--host", "127.0.0.1", "--port", strconv.Itoa(port),
		},
		HealthURL: healthURLForPort(port),
		ExtraEnv:  pythonEnv(opts),
	}
}

// pythonEnv 拼装子进程环境：opts.PythonExtraEnv 在前，其后追 DataDir 注入、
// PYTHONIOENCODING=utf-8、PYTHONPATH=<repoRoot>（2a T7 上溯）。
func pythonEnv(opts Options) []string {
	env := append([]string(nil), opts.PythonExtraEnv...)
	if opts.DataDir != "" {
		env = append(env,
			"DATABASE_PATH="+filepath.Join(opts.DataDir, "delector.db"),
			"DELECTOR_DATA_DIR="+opts.DataDir,
		)
	}
	env = append(env, "PYTHONIOENCODING=utf-8")
	if src := opts.PythonSrcDir; src != "" {
		// 包内源根（<exeDir>/delector-src）：优先注入，使 venv python 可
		// import delector 包（Phase 2b T3 绿色便携包）。
		env = append(env, "PYTHONPATH="+src)
	} else if root := repoRoot(); root != "" {
		// dev 模式兜底：仓库根上溯（2a T7 同款）。
		env = append(env, "PYTHONPATH="+root)
	}
	return env
}

func baseURLForPort(port int) string {
	if port == 0 {
		port = defaultPort
	}
	return fmt.Sprintf("http://127.0.0.1:%d", port)
}

// BaseURLForPort 返回给定端口（0=默认 8001）的托管 Python 服务根地址。
// 导出供 `delector job`（B7）等需在 spawn 后直连注册表/客户端而 `delector run`
// 已在内部使用的调用方复用，避免复制粘贴端口→URL 映射（单一事实源）。
func BaseURLForPort(port int) string { return baseURLForPort(port) }

// NewSupervisor 由 Options 构造托管 Python supervisor 的生产实现（未启动），
// 复用 app 为 `delector run` 装配的同一套 supervisor 配置（supervisorConfig：
// uvicorn 命令 / HealthURL / DataDir + PYTHONPATH 环境注入），返回
// *pythonsvc.Supervisor 供调用方自主管理生命周期（Start/Stop）。
//
// 用途：`delector job`（B7）在 --python-url 为空时需仿 run 起托管 Python 于
// 8001、跑完任务后再主动 Stop——app.Run 是常驻 serve 语义（等 ctx.Done），无法
// 复用于"spawn→执行→停止"的一次性任务，故经此导出同一 supervisor 装配。
func NewSupervisor(opts Options) *pythonsvc.Supervisor {
	return pythonsvc.NewSupervisor(supervisorConfig(opts))
}

func healthURLForPort(port int) string {
	return baseURLForPort(port) + "/api/tools/"
}

// repoRoot 上溯定位仓库根（delector Python 包所在目录），供 PYTHONPATH 注入，
// 使 uvicorn 可 import delector.server:app（2a T7 同款 runtime.Caller 上溯）。
func repoRoot() string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return ""
	}
	dir := filepath.Dir(file) // .../agent/internal/app
	for i := 0; i < 3; i++ {
		dir = filepath.Dir(dir) // app → internal → agent → repo
	}
	return dir
}
