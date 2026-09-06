package pythonsvc

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"runtime"
	"sync/atomic"
	"testing"
	"time"
)

// ---- 测试桩基础设施 ----

// probeStub 健康探针桩：failFirst < 0 恒 404；否则前 failFirst 次返回
// 404、其后返回 200。hits 以原子计数记录总命中次数（跨 goroutine 读写）。
type probeStub struct {
	failFirst int32
	hits      int32
}

// serve 启动 httptest 桩服务器，模拟 GET /api/tools/ 健康端点。
func (p *probeStub) serve() *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		n := atomic.AddInt32(&p.hits, 1)
		if p.failFirst < 0 || n <= p.failFirst {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
}

// startScript 描述第 i 次 startProc 桩调用的行为：err 非 nil 表示直接
// 启动失败；否则返回 wait/cancel/kill 句柄（kill 缺省为无害空实现，仅
// 显式验证强杀分支的用例才注入计数桩）。onCall 为可选的第 n 次调用副作用。
type startScript struct {
	err    error
	wait   func() error
	cancel func()
	kill   func() error
	onCall func(n int32)
}

// newStubSupervisor 经 startProc seam（唯一注入点，防过度抽象）构造
// 全桩化 Supervisor：script 逐次消费，耗尽后复用最后一项；calls 记录
// startProc 总调用次数供重启计数断言。
func newStubSupervisor(cfg SupervisorConfig, script []startScript, calls *int32) *Supervisor {
	cfg = cfg.withDefaults()
	s := &Supervisor{
		cfg:   cfg,
		failC: make(chan error, 1),
	}
	s.startProc = func(_ context.Context) (func() error, func(), func() error, error) {
		n := atomic.AddInt32(calls, 1)
		i := int(n) - 1
		if i >= len(script) {
			i = len(script) - 1
		}
		sc := script[i]
		if sc.onCall != nil {
			sc.onCall(n)
		}
		if sc.err != nil {
			return nil, nil, nil, sc.err
		}
		kill := sc.kill
		if kill == nil {
			kill = func() error { return nil }
		}
		return sc.wait, sc.cancel, kill, nil
	}
	return s
}

// fastCfg 统一短窗口配置：单测时长受控（探针/退避毫秒级），禁长 sleep。
func fastCfg(healthURL string) SupervisorConfig {
	return SupervisorConfig{
		HealthURL:     healthURL,
		ProbeInterval: 10 * time.Millisecond,
		ProbeTimeout:  150 * time.Millisecond,
		MaxRestarts:   2,
		StopTimeout:   150 * time.Millisecond,
	}
}

// TestBackoff 钉住指数退避纯函数序列：500ms 基数 × 2^attempt，封顶 8s；
// 负数 attempt 钳制为基数，超大 attempt 防移位溢出并保持封顶。
func TestBackoff(t *testing.T) {
	tests := []struct {
		name    string
		attempt int
		want    time.Duration
	}{
		{"attempt 0 → 500ms 基数", 0, 500 * time.Millisecond},
		{"attempt 1 → 1s", 1, 1 * time.Second},
		{"attempt 2 → 2s", 2, 2 * time.Second},
		{"attempt 3 → 4s", 3, 4 * time.Second},
		{"attempt 4 → 8s", 4, 8 * time.Second},
		{"attempt 5 → 封顶 8s", 5, 8 * time.Second},
		{"attempt 12 → 封顶 8s（防移位溢出）", 12, 8 * time.Second},
		{"attempt -1 → 钳制为基数 500ms", -1, 500 * time.Millisecond},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := backoff(tt.attempt); got != tt.want {
				t.Errorf("backoff(%d) = %v，期望 %v", tt.attempt, got, tt.want)
			}
		})
	}
}

// TestSupervisorStartProbe 健康探针轮询语义（httptest 桩，禁真实 uvicorn）：
// ① 立即 200 → Start 快速成功；② 前 N 次 404 后 200 → 窗口内轮询成功；
// ③ 恒 404 且探针窗口耗尽 → 报错，错误链可 errors.Is 判定
// context.DeadlineExceeded（全局约束：禁字符串比较），且 startProc
// 恰好尝试 MaxRestarts 次。
func TestSupervisorStartProbe(t *testing.T) {
	tests := []struct {
		name        string
		failFirst   int32 // 探针桩：-1 恒 404
		maxRestarts int   // 0 表示用 fastCfg 默认（仅成功用例）
		wantErr     bool
	}{
		{name: "立即 200: Start 快速成功", failFirst: 0},
		{name: "前 3 次 404 后 200: 轮询成功", failFirst: 3},
		{name: "恒 404: 探针窗口耗尽报错且重试配额用尽", failFirst: -1, maxRestarts: 2, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			stub := &probeStub{failFirst: tt.failFirst}
			srv := stub.serve()
			defer srv.Close()

			cfg := fastCfg(srv.URL)
			if tt.maxRestarts > 0 {
				cfg.MaxRestarts = tt.maxRestarts
			}
			var calls int32
			gate := make(chan struct{})
			var gateOnce int32
			s := newStubSupervisor(cfg, []startScript{{
				wait: func() error { <-gate; return nil },
				cancel: func() {
					if atomic.CompareAndSwapInt32(&gateOnce, 0, 1) {
						close(gate)
					}
				},
			}}, &calls)

			if tt.wantErr {
				err := s.Start(context.Background())
				if err == nil {
					t.Fatal("期望 Start 失败，实际成功")
				}
				if !errors.Is(err, context.DeadlineExceeded) {
					t.Errorf("探针窗口耗尽错误应可 errors.Is(err, context.DeadlineExceeded)，实际: %v", err)
				}
				if got := atomic.LoadInt32(&calls); int(got) != tt.maxRestarts {
					t.Errorf("startProc 尝试次数 = %d，期望恰 MaxRestarts=%d 次", got, tt.maxRestarts)
				}
				return
			}

			if err := s.Start(context.Background()); err != nil {
				t.Fatalf("期望 Start 成功，实际错误: %v", err)
			}
			defer s.Stop()
		})
	}
}

// TestSupervisorRestartBudget 重启计数：进程"启动即退出"连败时，恰好
// MaxRestarts 次尝试后返回最终错误（探针窗口耗尽链可 DeadlineExceeded 判定）。
func TestSupervisorRestartBudget(t *testing.T) {
	stub := &probeStub{failFirst: -1} // 探针恒 404：秒退进程等不来健康
	srv := stub.serve()
	defer srv.Close()

	cfg := fastCfg(srv.URL)
	cfg.MaxRestarts = 3
	var calls int32
	s := newStubSupervisor(cfg, []startScript{{
		wait:   func() error { return errors.New("python: process exited immediately") },
		cancel: func() {},
	}}, &calls)

	err := s.Start(context.Background())
	if err == nil {
		t.Fatal("期望重启配额耗尽后 Start 报最终错误")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("最终错误应含探针窗口耗尽链，实际: %v", err)
	}
	if got := atomic.LoadInt32(&calls); int(got) != cfg.MaxRestarts {
		t.Errorf("startProc 尝试次数 = %d，期望恰 MaxRestarts=%d 次", got, cfg.MaxRestarts)
	}
}

// TestSupervisorStop Stop 语义（全桩化，不依赖真实进程）：
// 优雅路径 cancel 恰一次且限时等待 wait 收尾、不触发强杀；wait 超时路径
// 走强杀分支调 killProc 恰一次（unix 两段式 SIGTERM→StopTimeout→Kill 的
// 回归钉子；cmd.WaitDelay 兜底仅在 ctx 取消路径成立，手动 cancel 路径
// 由本分支承担）。
func TestSupervisorStop(t *testing.T) {
	t.Run("优雅关闭: cancel 恰一次，wait 正常收尾，不触发强杀", func(t *testing.T) {
		stub := &probeStub{}
		srv := stub.serve()
		defer srv.Close()

		var calls, cancels, kills int32
		released := make(chan struct{})
		s := newStubSupervisor(fastCfg(srv.URL), []startScript{{
			wait: func() error { <-released; return nil },
			cancel: func() {
				if atomic.CompareAndSwapInt32(&cancels, 0, 1) {
					close(released)
				}
			},
			kill: func() error { atomic.AddInt32(&kills, 1); return nil },
		}}, &calls)

		if err := s.Start(context.Background()); err != nil {
			t.Fatalf("Start 应成功: %v", err)
		}
		s.Stop()
		if got := atomic.LoadInt32(&cancels); got != 1 {
			t.Errorf("优雅关闭应恰好 cancel 一次，实际 %d 次", got)
		}
		if got := atomic.LoadInt32(&kills); got != 0 {
			t.Errorf("优雅关闭不应触发强杀分支（killProc），实际 %d 次", got)
		}
	})

	t.Run("wait 超时: 强杀分支调 killProc（cancel 恰一次 + kill 恰一次）", func(t *testing.T) {
		stub := &probeStub{}
		srv := stub.serve()
		defer srv.Close()

		cfg := fastCfg(srv.URL)
		cfg.StopTimeout = 50 * time.Millisecond // 短超时驱动强杀分支，禁长 sleep
		var calls, cancels, kills int32
		s := newStubSupervisor(cfg, []startScript{{
			wait: func() error {
				// 模拟进程无视优雅 cancel，仅在强杀（killProc）后收尾；
				// 带期限轮询，回归（超时分支不再调 killProc）时测试限时
				// 失败而非挂死。
				deadline := time.Now().Add(2 * time.Second)
				for atomic.LoadInt32(&kills) < 1 {
					if time.Now().After(deadline) {
						return errors.New("stub: 强杀分支未在期限内调 killProc")
					}
					time.Sleep(time.Millisecond)
				}
				return nil
			},
			cancel: func() { atomic.AddInt32(&cancels, 1) },
			kill:   func() error { atomic.AddInt32(&kills, 1); return nil },
		}}, &calls)

		if err := s.Start(context.Background()); err != nil {
			t.Fatalf("Start 应成功: %v", err)
		}
		s.Stop()
		if got := atomic.LoadInt32(&cancels); got != 1 {
			t.Errorf("超时强杀路径应优雅 cancel 恰一次，实际 %d 次", got)
		}
		if got := atomic.LoadInt32(&kills); got != 1 {
			t.Errorf("超时强杀路径应调 killProc 恰一次（unix 两段式 SIGTERM→StopTimeout→Kill 的强杀兜底），实际 %d 次", got)
		}
	})
}

// TestSupervisorCrashRecovery 崩溃恢复：运行中进程意外退出（ctx 未取消且
// 未 Stop）→ 按 backoff 重启且探针重新通过；随后 Stop 正常收尾不再重启。
func TestSupervisorCrashRecovery(t *testing.T) {
	stub := &probeStub{}
	srv := stub.serve()
	defer srv.Close()

	var calls int32
	started2 := make(chan struct{})
	gate := make(chan struct{})
	var gateOnce int32
	script := []startScript{
		{ // 第 1 次：探针通过后 wait 立即返回错误（模拟运行中崩溃）
			wait:   func() error { return errors.New("python: crashed") },
			cancel: func() {},
		},
		{ // 第 2 次：重启后正常驻留至 Stop
			wait: func() error { <-gate; return nil },
			cancel: func() {
				if atomic.CompareAndSwapInt32(&gateOnce, 0, 1) {
					close(gate)
				}
			},
			onCall: func(n int32) {
				if n == 2 {
					close(started2)
				}
			},
		},
	}
	s := newStubSupervisor(fastCfg(srv.URL), script, &calls)
	if err := s.Start(context.Background()); err != nil {
		t.Fatalf("首次 Start 应成功: %v", err)
	}
	defer s.Stop()

	select {
	case <-started2:
	case <-time.After(2 * time.Second):
		t.Fatal("进程崩溃后未按 backoff 重启")
	}
	// 重启后的探针应重新通过：等待探针桩第 2 轮命中（短轮询带上限，非长 sleep）。
	deadline := time.Now().Add(time.Second)
	for atomic.LoadInt32(&stub.hits) < 2 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if atomic.LoadInt32(&stub.hits) < 2 {
		t.Fatal("重启后健康探针未重新通过")
	}
}

// TestSupervisorCrashExhausted 崩溃重启配额耗尽：最终错误经 Failures()
// 非阻塞上报（缓冲 1），错误链含最后一次重启失败原因。
func TestSupervisorCrashExhausted(t *testing.T) {
	stub := &probeStub{}
	srv := stub.serve()
	defer srv.Close()

	cfg := fastCfg(srv.URL)
	cfg.MaxRestarts = 1 // 崩溃后仅 1 次重启尝试，控制测试时长
	var calls int32
	restartErr := errors.New("python: restart refused")
	script := []startScript{
		{wait: func() error { return errors.New("python: crashed") }, cancel: func() {}},
		{err: restartErr},
	}
	s := newStubSupervisor(cfg, script, &calls)
	if err := s.Start(context.Background()); err != nil {
		t.Fatalf("首次 Start 应成功: %v", err)
	}
	defer s.Stop()

	select {
	case err := <-s.Failures():
		if !errors.Is(err, restartErr) {
			t.Errorf("Failures() 错误应含重启失败原因链，实际: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("崩溃重启配额耗尽后未上报 Failures()")
	}
}

// ---- Phase2b T1：supervisor 递延项（探针默认窗口 + 关闭语义平台分治）----

// TestDefaultProbeTimeout 钉住探针窗口默认值 10s（Phase2b T1 由 2s 上调）：
// 依据 spaCy 冷启动实测——模型首次加载耗时可秒级到十秒级，2s 窗口稳定
// 误判启动失败；2a 集成测试（integration_test.go）已放宽至 30s，默认值
// 取折中 10s，兼顾误判率与失败反馈速度。
func TestDefaultProbeTimeout(t *testing.T) {
	if DefaultProbeTimeout != 10*time.Second {
		t.Fatalf("DefaultProbeTimeout = %v，期望 10s（spaCy 冷启动实测，2a 集成测试放宽 30s，折中取 10s）",
			DefaultProbeTimeout)
	}
}

// TestTerminateProcPlatformBranch 平台关闭行为断言（经 startProc 生产
// seam realStartProc 验证终止接线与收尾时限；直接启 ping.exe 本体而非
// cmd /c 包装，Kill 即杀本体，不留 30s 孤儿 ping.exe 进程树）：
//
//   - windows：cancel 触发 Kill 分支（阶段一），kill 闭包触发 killProc
//     强杀分支（阶段二，awaitExit 超时分支同款接线）；真子进程均限时收尾
//     （Kill 是 TerminateProcess 而非信号，不违反"单测不发真信号"边界，
//     本机可验证）。
//
//   - unix：SIGTERM 真信号不在单测断言——验证边界：unix 分支的编译正确性
//     由 GOOS=linux/darwin 交叉编译保证（build tag 文件接线与签名），
//     真信号语义（SIGTERM 优雅退出、StopTimeout 后 killProc 强杀两段式
//     闭环）由 CI unix runner 与 -tags integration 冒烟覆盖。
//
// 禁长 sleep：存活确认与收尾等待均用短窗口限时断言。
func TestTerminateProcPlatformBranch(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("unix SIGTERM 真信号不在单测断言（验证边界：GOOS=linux/darwin 交叉编译 + CI unix runner 保证，见测试注释）")
	}

	cfg := SupervisorConfig{
		PythonCmd:   []string{"ping", "-n", "30", "127.0.0.1"}, // 长跑轻量子进程（直启本体）
		StopTimeout: 300 * time.Millisecond,
	}.withDefaults()

	// 阶段一：统一入口接线——cmd.Cancel → terminateProc → windows Kill 分支。
	wait, cancel, kill, err := realStartProc(context.Background(), cfg)
	if err != nil {
		t.Fatalf("realStartProc 应成功启动长跑子进程: %v", err)
	}
	defer func() { _ = kill() }() // 兜底防孤儿（正常路径进程已被杀，重复 Kill 无害）

	done := make(chan error, 1)
	go func() { done <- wait() }()
	select {
	case <-done:
		t.Fatal("cancel 前 wait 不应返回：ping 30s 长跑子进程应仍存活")
	case <-time.After(200 * time.Millisecond):
		// 进程存活确认完毕，进入终止验证。
	}

	cancel() // 统一入口接线：cmd.Cancel → terminateProc → windows Kill 分支
	select {
	case <-done:
		// Kill 生效：wait 限时返回（进程被 TerminateProcess，wait 返回
		// ExitError 属预期，不校验具体错误值）。
	case <-time.After(2 * time.Second):
		t.Fatal("cancel 后 wait 未限时收尾：windows Kill 分支未生效")
	}

	// 阶段二：强杀兜底接线 killProc（awaitExit 超时分支同款接线）。unix
	// 两段式 SIGTERM→StopTimeout→Kill 在本机不可真跑，Windows 侧 Kill 即
	// 强杀、接线语义一致——实进程直接调 kill 闭包，断言强杀限时收尾。
	wait2, _, kill2, err := realStartProc(context.Background(), cfg)
	if err != nil {
		t.Fatalf("realStartProc 第二阶段应成功启动长跑子进程: %v", err)
	}
	defer func() { _ = kill2() }()

	done2 := make(chan error, 1)
	go func() { done2 <- wait2() }()
	select {
	case <-done2:
		t.Fatal("kill 前 wait 不应返回：ping 30s 长跑子进程应仍存活")
	case <-time.After(200 * time.Millisecond):
		// 进程存活确认完毕，进入强杀验证。
	}

	if err := kill2(); err != nil {
		t.Fatalf("killProc 强杀存活进程应成功: %v", err)
	}
	select {
	case <-done2:
		// 强杀生效：wait 限时返回（ExitError 属预期，不校验具体错误值）。
	case <-time.After(2 * time.Second):
		t.Fatal("kill 后 wait 未限时收尾：killProc 强杀分支未生效")
	}
}
