package pythonsvc

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"sync"
	"time"
)

// ---- 哨兵错误 ----
//
// 启动/崩溃重启失败必须可经 errors.Is 区分语义，杜绝把"已停止 / ctx 取消"
// 与真实"配额耗尽"混报（崩溃恢复与 Stop 竞态时的误报源）。禁字符串比较。
var (
	// ErrSupervisorStopped：Supervisor 已被 Stop（或正在停止），据此中止/
	// 拒绝启动重试。errors.Is(err, ErrSupervisorStopped) 判定。
	ErrSupervisorStopped = errors.New("pythonsvc: supervisor stopped")
	// ErrBudgetExhausted：连续 MaxRestarts 次真实启动/探针失败后配额耗尽。
	// 仅"配额耗尽"路径包装此哨兵；调用方可 errors.Is 判定并取其文案。
	ErrBudgetExhausted = errors.New("pythonsvc: restart budget exhausted")
)

// ---- 默认配置常量 ----

// defaultPythonCmd 为 agent 托管 Python 实例的默认启动命令：开发态即真实
// uvicorn，分发态（Phase 2b）同协议替换可执行路径。端口 8001 归 agent 专用，
// 8000 留给用户直接启动的实例（Global Constraints 端口约定）。
var defaultPythonCmd = []string{
	"python", "-m", "uvicorn", "delector.server:app",
	"--host", "127.0.0.1", "--port", "8001",
}

const (
	defaultHealthURL     = "http://127.0.0.1:8001/api/tools/"
	defaultProbeInterval = 1 * time.Second
	defaultMaxRestarts   = 5
	defaultStopTimeout   = 5 * time.Second
)

// DefaultProbeTimeout 探针窗口默认值：10s（Phase2b T1 由 2s 上调）。
// 依据 spaCy 冷启动实测：模型首次加载耗时可秒级到十秒级，2s 窗口稳定
// 误判启动失败；2a 集成测试（integration_test.go probeTimeout）已放宽
// 至 30s，默认值取折中 10s，兼顾误判率与失败反馈速度。
const DefaultProbeTimeout = 10 * time.Second

// backoff 退避基数与封顶：500ms × 2^attempt，封顶 8s。
const (
	backoffBase = 500 * time.Millisecond
	backoffCap  = 8 * time.Second
)

// SupervisorConfig 托管 Python 常驻进程的配置；零值字段启用默认值。
type SupervisorConfig struct {
	// PythonCmd 启动命令（argv 形式）。默认 defaultPythonCmd（uvicorn :8001）。
	PythonCmd []string
	// HealthURL 健康探针地址，默认 defaultHealthURL（GET /api/tools/）。
	HealthURL string
	// ExtraEnv 以 KEY=VALUE 追加到子进程环境，供注入临时 DATABASE_PATH /
	// DELECTOR_DATA_DIR——绝不让测试或 agent 托管实例触碰用户库。
	ExtraEnv []string
	// ProbeInterval 探针轮询间隔，默认 1s。
	ProbeInterval time.Duration
	// ProbeTimeout 单次"启动→健康"探测窗口总时长，默认 DefaultProbeTimeout
	// （10s，Phase2b T1 上调，依据 spaCy 冷启动实测）；窗口耗尽视为本次
	// 启动失败（错误链可 errors.Is 判定 context.DeadlineExceeded）。
	ProbeTimeout time.Duration
	// MaxRestarts 启动/崩溃重启的总尝试配额，默认 5；耗尽返回最终错误。
	MaxRestarts int
	// StopTimeout 优雅关闭的限时等待与 cmd.WaitDelay 兜底时长，默认 5s。
	// 规格外增量字段：为满足"Stop 带超时 Wait 必须可测（禁长 sleep）"。
	StopTimeout time.Duration
}

// withDefaults 填补零值字段的默认配置（值语义，不改调用方原 cfg）。
func (cfg SupervisorConfig) withDefaults() SupervisorConfig {
	if len(cfg.PythonCmd) == 0 {
		cfg.PythonCmd = defaultPythonCmd
	}
	if cfg.HealthURL == "" {
		cfg.HealthURL = defaultHealthURL
	}
	if cfg.ProbeInterval <= 0 {
		cfg.ProbeInterval = defaultProbeInterval
	}
	if cfg.ProbeTimeout <= 0 {
		cfg.ProbeTimeout = DefaultProbeTimeout
	}
	if cfg.MaxRestarts <= 0 {
		cfg.MaxRestarts = defaultMaxRestarts
	}
	if cfg.StopTimeout <= 0 {
		cfg.StopTimeout = defaultStopTimeout
	}
	return cfg
}

// backoff 返回第 attempt 次失败后的指数退避时长：500ms × 2^attempt，封顶
// 8s。负数 attempt 钳制为 0；attempt ≥ 4 直接封顶（同时防移位溢出）。
// 导出供调用方预估重启耗时；纯函数，无副作用。
func backoff(attempt int) time.Duration {
	switch {
	case attempt < 0:
		attempt = 0
	case attempt > 4:
		return backoffCap
	}
	return backoffBase << attempt
}

// ---- 进程句柄与启动 seam ----

// procHandle 抽象一次已启动的进程：wait 阻塞至进程退出；cancel 触发优雅
// 终止（真实实现为 exec.CommandContext 取消钩子：unix 发 SIGTERM、
// windows Kill——Phase2b T1 平台分治）；kill 强杀兜底（unix 上进程无视
// SIGTERM 时由 awaitExit 超时分支调用的 Kill，windows 同为 Kill），对已
// 退出进程允许返回无害错误（调用方一律丢弃返回值）。wait/cancel 均应幂等。
type procHandle struct {
	wait   func() error
	cancel func()
	kill   func() error
}

// startFunc 是 Supervisor 唯一的进程启动 seam：签名刻意极薄（ctx 进、
// wait/cancel/kill/err 出），生产实现包装 exec.CommandContext，测试桩注入
// 假句柄。只此一处 seam，防过度抽象。
type startFunc func(ctx context.Context) (wait func() error, cancel func(), kill func() error, err error)

// newProcHandle 构造 procHandle 并为 wait 建立幂等闸：sync.Once 保证即使
// 多个 goroutine 并发调用 p.wait()（Stop 的 awaitExit 与 supervise 的驻留
// wait 会指向同一 exec.Cmd），也仅触发一次真正底层 Wait——对同一
// exec.Cmd 并发 Wait 在 Unix 下为未指定行为。各调用方共享同一份 waitErr。
func newProcHandle(wait func() error, cancel func(), kill func() error) *procHandle {
	var once sync.Once
	var waitErr error
	return &procHandle{
		wait: func() error {
			once.Do(func() { waitErr = wait() })
			return waitErr
		},
		cancel: cancel,
		kill:   kill,
	}
}

// probeHTTP 健康探针专用 HTTP client：无自身超时，探针生命周期完全由
// probeUntil 的窗口 ctx 约束（全局约束：出站请求必须 NewRequestWithContext）。
var probeHTTP = &http.Client{}

// Supervisor 管理 Python 常驻进程的全生命周期：启动 + 健康探针 + 崩溃
// 退避重启 + 优雅关闭。零值不可用，经 NewSupervisor 构造。
type Supervisor struct {
	cfg       SupervisorConfig
	startProc startFunc
	failC     chan error

	mu      sync.Mutex
	proc    *procHandle
	running bool
	stopped bool
}

// NewSupervisor 构造 Supervisor 并补全默认配置；startProc 绑定生产实现
// realStartProc。
func NewSupervisor(cfg SupervisorConfig) *Supervisor {
	cfg = cfg.withDefaults()
	return &Supervisor{
		cfg: cfg,
		startProc: func(ctx context.Context) (func() error, func(), func() error, error) {
			return realStartProc(ctx, cfg)
		},
		failC: make(chan error, 1),
	}
}

// Failures 返回崩溃恢复最终失败的错误出口（缓冲 1）。Start 成功后若托管
// 进程反复崩溃且重启配额耗尽，最终错误送达此通道；发送非阻塞，无人接收
// 时丢弃，杜绝 goroutine 泄漏。
func (s *Supervisor) Failures() <-chan error { return s.failC }

// ---- 生命周期 ----

// Start 启动 Python 常驻进程并阻塞至健康探针通过。启动失败或探针窗口耗尽
// 按 backoff(attempt) 指数退避重试，恰好 MaxRestarts 次尝试后返回最终错误。
// 探针通过后托管转入后台 supervise：进程意外退出（调用方 ctx 未取消且未
// Stop）时自动按退避重启，配额耗尽经 Failures() 上报。
func (s *Supervisor) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.running || s.stopped {
		state := "已在运行"
		if s.stopped {
			state = "已停止（不可复用）"
		}
		s.mu.Unlock()
		return fmt.Errorf("pythonsvc: supervisor %s，拒绝重复 Start", state)
	}
	s.running = true
	s.mu.Unlock()

	p, err := s.startWithRetry(ctx)
	if err != nil {
		s.mu.Lock()
		s.running = false
		s.mu.Unlock()
		return err
	}
	s.setProc(p)
	go s.supervise(ctx, p)
	return nil
}

// Stop 优雅关闭托管进程：先 cancel（unix 发 SIGTERM / windows Kill，
// Phase2b T1 平台分治）再限时等待 wait 返回；超时进入强杀分支调 killProc
// 强杀（unix 两段式闭环：SIGTERM → 等 StopTimeout → Kill，进程无视
// SIGTERM 时不再无限等待）。幂等；Stop 后 Supervisor 不可再 Start。
// 注：cmd.WaitDelay 强杀兜底仅在 ctx 取消路径成立（CommandContext 机制）；
// 手动 cancel 路径不取消 ctx，其强杀兜底由超时分支的 killProc 承担。
func (s *Supervisor) Stop() {
	s.mu.Lock()
	s.stopped = true
	s.running = false
	p := s.proc
	s.proc = nil
	s.mu.Unlock()
	if p == nil {
		return
	}
	p.cancel()
	s.awaitExit(p)
}

// supervise 后台托管循环：阻塞等待进程退出；调用方 ctx 存活且未 Stop 时的
// 退出视为崩溃，按 backoff 退避重启（复用 startWithRetry 配额），配额耗尽
// 经 Failures() 上报并停止托管。
func (s *Supervisor) supervise(ctx context.Context, p *procHandle) {
	for {
		waitErr := p.wait()
		if s.isStopped() || ctx.Err() != nil {
			return // Stop 或调用方 ctx 取消：正常退出路径
		}
		next, err := s.startWithRetry(ctx)
		if err != nil {
			// Stop 或调用方 ctx 取消与崩溃恢复竞态：startWithRetry 会以哨兵/
			// ctx 取消语义返回，属正常收场，非配额耗尽，静默返回不上报（防误报）。
			if errors.Is(err, ErrSupervisorStopped) || errors.Is(err, context.Canceled) {
				return
			}
			s.report(fmt.Errorf("pythonsvc: 托管进程意外退出（wait: %v）且重启配额耗尽: %w", waitErr, err))
			return
		}
		s.setProc(next)
		if s.isStopped() {
			return
		}
		p = next
	}
}

// startWithRetry 单轮"启动+探针"重试循环：恰好 MaxRestarts 次尝试，相邻
// 尝试间等待 backoff(tries)。任一次探针通过即成功返回；全部失败返回包装
// 最后一次错误的最终错误。
//
// 失败语义可区分（禁字符串比较）：
//   - 已 Stop：返回哨兵 ErrSupervisorStopped（中止启动重试）。
//   - 调用方 ctx 取消：返回 ctx.Err() 链（errors.Is(context.Canceled) 判定）。
//   - 其余（真实启动/探针连败耗尽配额）：最终错误包 ErrBudgetExhausted 哨兵。
func (s *Supervisor) startWithRetry(ctx context.Context) (*procHandle, error) {
	var lastErr error
	for tries := 0; tries < s.cfg.MaxRestarts; tries++ {
		if s.isStopped() {
			return nil, fmt.Errorf("%w: 中止启动重试", ErrSupervisorStopped)
		}
		p, err := s.tryLaunch(ctx)
		if err == nil {
			return p, nil
		}
		// 启动/探针因 ctx 取消而中止属正常收场，非配额耗尽，直接上抛其语义。
		if errors.Is(err, context.Canceled) || ctx.Err() != nil {
			return nil, fmt.Errorf("%w: 启动托管进程", ctx.Err())
		}
		lastErr = err
		if tries+1 < s.cfg.MaxRestarts {
			if werr := s.sleepBackoff(ctx, tries); werr != nil {
				return nil, werr
			}
		}
	}
	return nil, fmt.Errorf("%w: 连续 %d 次启动托管进程失败: %w",
		ErrBudgetExhausted, s.cfg.MaxRestarts, lastErr)
}

// sleepBackoff 等待第 attempt 次失败的退避时长；调用方 ctx 取消时提前返回。
func (s *Supervisor) sleepBackoff(ctx context.Context, attempt int) error {
	timer := time.NewTimer(backoff(attempt))
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return fmt.Errorf("pythonsvc: 等待重启退避期间 ctx 取消: %w", ctx.Err())
	}
}

// tryLaunch 启动一次进程并阻塞探测健康；探针失败时终止本次进程再返回
// 错误，防僵尸进程与句柄泄漏。
func (s *Supervisor) tryLaunch(ctx context.Context) (*procHandle, error) {
	wait, cancel, kill, err := s.startProc(ctx)
	if err != nil {
		return nil, fmt.Errorf("pythonsvc: 启动 python 进程: %w", err)
	}
	p := newProcHandle(wait, cancel, kill)
	if perr := s.probeUntil(ctx); perr != nil {
		s.terminate(p)
		return nil, perr
	}
	return p, nil
}

// probeUntil 以 ProbeInterval 间隔轮询 GET HealthURL 直至 200。整个探测
// 阶段共享 ProbeTimeout 窗口；窗口耗尽返回可 errors.Is 判定
// context.DeadlineExceeded 的错误链（全局约束：禁字符串比较）。
func (s *Supervisor) probeUntil(ctx context.Context) error {
	pctx, cancel := context.WithTimeout(ctx, s.cfg.ProbeTimeout)
	defer cancel()
	for {
		lastErr := s.probeOnce(pctx)
		if lastErr == nil {
			return nil
		}
		if pctx.Err() != nil {
			return s.probeWindowErr(lastErr, pctx.Err())
		}
		select {
		case <-pctx.Done():
			return s.probeWindowErr(lastErr, pctx.Err())
		case <-time.After(s.cfg.ProbeInterval):
		}
	}
}

// probeWindowErr 统一构造探针窗口耗尽错误：保留最后一次失败原因与
// context.DeadlineExceeded 错误链。
func (s *Supervisor) probeWindowErr(lastErr, windowErr error) error {
	return fmt.Errorf("pythonsvc: 健康探针 %s 在 %v 窗口内未通过（最后一次: %v）: %w",
		s.cfg.HealthURL, s.cfg.ProbeTimeout, lastErr, windowErr)
}

// probeOnce 单次健康探测：GET HealthURL，200 即健康；其余状态码与请求
// 错误（连接拒绝/超时）均视为未就绪。
func (s *Supervisor) probeOnce(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.HealthURL, nil)
	if err != nil {
		return fmt.Errorf("pythonsvc: 构建探针请求: %w", err)
	}
	resp, err := probeHTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("探针状态码 %d", resp.StatusCode)
	}
	return nil
}

// terminate 终止一次启动产生的进程：cancel（unix SIGTERM / windows Kill，
// 平台分治见 terminateProc）后限时等待 wait 返回；超时走强杀分支调
// killProc（真实进程 Kill 收尾；cmd.WaitDelay 兜底仅在 ctx 取消路径成立，
// 见 Stop 注），绝不让启动/关闭路径无限阻塞。
func (s *Supervisor) terminate(p *procHandle) {
	p.cancel()
	s.awaitExit(p)
}

// awaitExit 限时等待进程句柄收尾：超时则调 killProc 强杀后等待最终返回
// ——真实进程被 Kill 后 wait 有限时间内返回（unix：SIGTERM 未生效时的
// 两段式强杀兜底 SIGTERM → StopTimeout → Kill；windows：与 cancel 同为
// Kill，二次 Kill 无害）。
func (s *Supervisor) awaitExit(p *procHandle) {
	done := make(chan error, 1)
	go func() { done <- p.wait() }()
	select {
	case <-done:
	case <-time.After(s.cfg.StopTimeout):
		_ = p.kill()
		<-done
	}
}

// report 非阻塞上报崩溃恢复最终错误（缓冲 1），无人接收时丢弃。
func (s *Supervisor) report(err error) {
	select {
	case s.failC <- err:
	default:
	}
}

func (s *Supervisor) isStopped() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.stopped
}

// setProc 登记新进程句柄；若期间 Supervisor 已 Stop，则直接终止该句柄，
// 防关闭竞态下复活僵尸进程。
func (s *Supervisor) setProc(p *procHandle) {
	s.mu.Lock()
	if s.stopped {
		s.mu.Unlock()
		s.terminate(p)
		return
	}
	s.proc = p
	s.mu.Unlock()
}

// ---- 生产实现 ----

// realStartProc 生产启动实现：exec.CommandContext 托管 Python 常驻进程。
// ExtraEnv 以 KEY=VALUE 追加到父进程环境（注入临时 DATABASE_PATH /
// DELECTOR_DATA_DIR 的通道，绝不触碰用户库）。
// 关闭语义平台分治（Phase2b T1）：cmd.Cancel 统一入口 terminateProc——
// unix 发 SIGTERM 优雅关闭（发送失败回退 Kill），windows 保持 Kill；
// cmd.WaitDelay 保证 ctx 取消路径最多 StopTimeout 内强杀收尾（Go 1.20+
// 机制，两平台不动）；手动 cancel 路径（Stop/terminate 不取消 ctx，
// WaitDelay 不介入）的超时强杀兜底由 awaitExit 调 killProc 承担。
func realStartProc(ctx context.Context, cfg SupervisorConfig) (func() error, func(), func() error, error) {
	cmd := exec.CommandContext(ctx, cfg.PythonCmd[0], cfg.PythonCmd[1:]...)
	cmd.Env = append(os.Environ(), cfg.ExtraEnv...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.WaitDelay = cfg.StopTimeout
	cmd.Cancel = func() error { return terminateProc(cmd) }
	if err := cmd.Start(); err != nil {
		return nil, nil, nil, fmt.Errorf("pythonsvc: exec %v: %w", cfg.PythonCmd, err)
	}
	return cmd.Wait, func() { _ = cmd.Cancel() }, func() error { return killProc(cmd) }, nil
}
