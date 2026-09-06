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
	defaultProbeTimeout  = 2 * time.Second
	defaultMaxRestarts   = 5
	defaultStopTimeout   = 5 * time.Second
)

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
	// ProbeTimeout 单次"启动→健康"探测窗口总时长，默认 2s；窗口耗尽视为
	// 本次启动失败（错误链可 errors.Is 判定 context.DeadlineExceeded）。
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
		cfg.ProbeTimeout = defaultProbeTimeout
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
// 终止（真实实现为 exec.CommandContext 取消钩子，即 Windows 上的 SIGTERM
// 等价物）。二者均应幂等。
type procHandle struct {
	wait   func() error
	cancel func()
}

// startFunc 是 Supervisor 唯一的进程启动 seam：签名刻意极薄（ctx 进、
// wait/cancel/err 出），生产实现包装 exec.CommandContext，测试桩注入假
// 句柄。只此一处 seam，防过度抽象。
type startFunc func(ctx context.Context) (wait func() error, cancel func(), err error)

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
		startProc: func(ctx context.Context) (func() error, func(), error) {
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

// Stop 优雅关闭托管进程：先 cancel（SIGTERM 等价物）再限时等待 wait 返回；
// 超时进入强杀分支再次 cancel（真实进程由 cmd.WaitDelay 兜底保证最终收尾，
// 防 Windows 句柄挂死）。幂等；Stop 后 Supervisor 不可再 Start。
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
func (s *Supervisor) startWithRetry(ctx context.Context) (*procHandle, error) {
	var lastErr error
	for tries := 0; tries < s.cfg.MaxRestarts; tries++ {
		if s.isStopped() {
			return nil, errors.New("pythonsvc: supervisor 已停止，中止启动重试")
		}
		p, err := s.tryLaunch(ctx)
		if err == nil {
			return p, nil
		}
		lastErr = err
		if tries+1 < s.cfg.MaxRestarts {
			if werr := s.sleepBackoff(ctx, tries); werr != nil {
				return nil, werr
			}
		}
	}
	return nil, fmt.Errorf("pythonsvc: 连续 %d 次启动托管进程失败: %w", s.cfg.MaxRestarts, lastErr)
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
	wait, cancel, err := s.startProc(ctx)
	if err != nil {
		return nil, fmt.Errorf("pythonsvc: 启动 python 进程: %w", err)
	}
	p := &procHandle{wait: wait, cancel: cancel}
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

// terminate 终止一次启动产生的进程：cancel（SIGTERM 等价物）后限时等待
// wait 返回；超时走强杀分支（真实进程由 cmd.WaitDelay 兜底保证收尾），
// 绝不让启动/关闭路径无限阻塞。
func (s *Supervisor) terminate(p *procHandle) {
	p.cancel()
	s.awaitExit(p)
}

// awaitExit 限时等待进程句柄收尾：超时则强杀（cancel 幂等再触发）后等待
// 最终返回——真实进程的 WaitDelay 保证 wait 有限时间内返回。
func (s *Supervisor) awaitExit(p *procHandle) {
	done := make(chan error, 1)
	go func() { done <- p.wait() }()
	select {
	case <-done:
	case <-time.After(s.cfg.StopTimeout):
		p.cancel()
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
// DELECTOR_DATA_DIR 的通道，绝不触碰用户库）。cmd.Cancel 即 SIGTERM 等价物
// （Windows 无 SIGTERM，Kill 为最接近语义）；cmd.WaitDelay 保证 cancel 后
// 最多 StopTimeout 内强杀收尾，防 Windows 句柄挂死（Go 1.20+ 机制）。
func realStartProc(ctx context.Context, cfg SupervisorConfig) (func() error, func(), error) {
	cmd := exec.CommandContext(ctx, cfg.PythonCmd[0], cfg.PythonCmd[1:]...)
	cmd.Env = append(os.Environ(), cfg.ExtraEnv...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.WaitDelay = cfg.StopTimeout
	cmd.Cancel = func() error { return cmd.Process.Kill() }
	if err := cmd.Start(); err != nil {
		return nil, nil, fmt.Errorf("pythonsvc: exec %v: %w", cfg.PythonCmd, err)
	}
	return cmd.Wait, func() { _ = cmd.Cancel() }, nil
}
