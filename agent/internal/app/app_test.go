package app

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"reflect"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// fakeSupervisor 记录 Start/Stop 调用，供装配顺序与优雅退出断言；不触网。
// failC 为崩溃恢复最终失败的错误出口（生产：pythonsvc.Supervisor.Failures）；
// nil 表示"永不上报"，消费方 select 于该 nil 通道将永久阻塞（合法语义）。
type fakeSupervisor struct {
	events   *[]string
	startErr error
	stopped  bool
	failC    chan error
}

func (f *fakeSupervisor) Start(ctx context.Context) error {
	*f.events = append(*f.events, "start")
	return f.startErr
}

func (f *fakeSupervisor) Stop() {
	*f.events = append(*f.events, "stop")
	f.stopped = true
}

func (f *fakeSupervisor) Failures() <-chan error { return f.failC }

// withSeams 临时替换装配 seam（supervisor / registry / DAG 构建）并在测试结束
// 时还原，避免用例间串扰。registry / DAG 构建事件记录到共享 events 切片，与
// fakeSupervisor 的 start/stop 同处 Run 单 goroutine，故顺序确定。
func withSeams(t *testing.T, events *[]string, sup supervisor, reg *registry.Registry) {
	t.Helper()
	origSup, origReg, origDAG := newSupervisor, newRegistry, buildArticleDAG
	t.Cleanup(func() {
		newSupervisor, newRegistry, buildArticleDAG = origSup, origReg, origDAG
	})
	newSupervisor = func(opts Options) supervisor { return sup }
	newRegistry = func(port int) *registry.Registry {
		*events = append(*events, "registry")
		return reg
	}
	buildArticleDAG = func(tools *registry.Registry) (*dag.DAG, error) {
		*events = append(*events, "dag")
		return dag.NewDAG("fake"), nil
	}
}

// TestRun_AssemblyOrderAndGracefulStop 钉死装配顺序：
// start → registry → dag → (ctx.Done) → stop，并断言 ctx 取消时优雅退出
// （Stop 必调）且 Run 返回 nil。
func TestRun_AssemblyOrderAndGracefulStop(t *testing.T) {
	var events []string
	fs := &fakeSupervisor{events: &events}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Run(ctx, Options{Port: 8080}) }()

	cancel() // 触发常驻退出
	if err := <-done; err != nil {
		t.Fatalf("Run 应优雅退出返回 nil，实际: %v", err)
	}
	if !fs.stopped {
		t.Fatal("ctx 取消后 Stop 必须被调用（优雅退出）")
	}
	want := []string{"start", "registry", "dag", "stop"}
	if !reflect.DeepEqual(events, want) {
		t.Fatalf("装配顺序应为 %v，实际 %v", want, events)
	}
}

// TestRun_StartFailurePropagates 断言 Start 失败以 %w 透传，且不调用 Stop
// （子进程从未起，无需释放）。
func TestRun_StartFailurePropagates(t *testing.T) {
	var events []string
	fs := &fakeSupervisor{events: &events, startErr: errors.New("boom")}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	if err := Run(context.Background(), Options{Port: 8080}); err == nil {
		t.Fatal("Start 失败应透传错误")
	}
	if fs.stopped {
		t.Fatal("Start 失败不应调用 Stop")
	}
	if !reflect.DeepEqual(events, []string{"start"}) {
		t.Fatalf("Start 失败后只应有 start 事件，实际 %v", events)
	}
}

// TestRun_DAGBuildFailureStopsSupervisor 断言 DAG 预设构建失败时，已起的
// supervisor 必须释放（Stop 必调），且错误透传。
func TestRun_DAGBuildFailureStopsSupervisor(t *testing.T) {
	var events []string
	fs := &fakeSupervisor{events: &events}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	// 覆盖 buildArticleDAG 返回错误（不记录 "dag" 事件）。
	origDAG := buildArticleDAG
	t.Cleanup(func() { buildArticleDAG = origDAG })
	buildArticleDAG = func(tools *registry.Registry) (*dag.DAG, error) {
		return nil, errors.New("bad dag")
	}

	if err := Run(context.Background(), Options{Port: 8080}); err == nil {
		t.Fatal("DAG 构建失败应透传错误")
	}
	if !fs.stopped {
		t.Fatal("DAG 构建失败应释放已起的 supervisor（Stop 必调）")
	}
	want := []string{"start", "registry", "stop"}
	if !reflect.DeepEqual(events, want) {
		t.Fatalf("事件应为 %v，实际 %v", want, events)
	}
}

// TestRun_ValidateOptsPortRange 断言非法端口在装配前被拒（不触网）。
func TestRun_ValidateOptsPortRange(t *testing.T) {
	var events []string
	fs := &fakeSupervisor{events: &events}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	if err := Run(context.Background(), Options{Port: 70000}); err == nil {
		t.Fatal("非法端口应被参数校验拒绝")
	}
	if fs.stopped {
		t.Fatal("参数校验失败不应启动 supervisor")
	}
	if len(events) != 0 {
		t.Fatalf("参数校验失败不应触碰 supervisor，实际事件 %v", events)
	}
}

// TestRun_SupervisorFailurePropagatesAndExits 钉死"Python 崩溃有出口"：
// supervisor 经 Failures() 上报崩溃恢复最终失败时，Run MUST 以非 nil 错误
// 返回（而非继续常驻），错误链 MUST 能 errors.Is 追到原始错误，MUST 打出
// 完整错误链到日志（不留给 restart: unless-stopped / systemd 之外的静默
// 失败），且已起的 supervisor MUST 释放（Stop 必调）。
func TestRun_SupervisorFailurePropagatesAndExits(t *testing.T) {
	var events []string
	bootErr := errors.New("boom: python 起不来")
	// 生产形状：supervisor 把底层 wait 错误包进最终错误再上报。
	upstream := fmt.Errorf("pythonsvc: 托管进程意外退出（wait: signal: killed）: %w", bootErr)
	failC := make(chan error, 1)
	fs := &fakeSupervisor{events: &events, failC: failC}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	logged, restoreLog := captureLog(t)
	defer restoreLog()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- Run(ctx, Options{Port: 8080}) }()

	// 常驻后崩溃：往 Failures 上报最终失败。
	failC <- upstream

	select {
	case err := <-done:
		if err == nil {
			t.Fatal("supervisor 上报崩溃恢复失败时 Run 必须返回非 nil 错误（MUST 非零退出的前提）")
		}
		if !errors.Is(err, bootErr) {
			t.Fatalf("错误链必须能追到原始错误，errors.Is(%v) 为假，实际错误: %v", bootErr, err)
		}
		if errors.Is(err, pythonsvc.ErrBudgetExhausted) {
			t.Fatalf("fake 未上报 ErrBudgetExhausted，测试构造有误: %v", err)
		}
	case <-time.After(3 * time.Second):
		cancel()
		t.Fatal("Run 未消费 Failures()：崩溃恢复最终失败没有出口（进程静默存活）")
	}

	if !fs.stopped {
		t.Error("崩溃失败退出时必须释放已起的 supervisor（Stop 必调）")
	}
	if !strings.Contains(logged(), "boom: python 起不来") {
		t.Errorf("日志必须打出完整错误链（含原始错误文案），实际日志: %q", logged())
	}
}

// TestRun_FailuresChannelClosedKeepsResidency 钉死 Failures() 通道**正常关闭**
// （生产 Supervisor 不关该通道，但 fake 可关）时 MUST NOT panic、MUST NOT 提前
// 返回：Run 仍按既有语义常驻至 ctx 取消后优雅退出（Stop 必调、返回 nil）。
func TestRun_FailuresChannelClosedKeepsResidency(t *testing.T) {
	var events []string
	failC := make(chan error)
	close(failC) // 关闭即"不会再有失败"
	fs := &fakeSupervisor{events: &events, failC: failC}
	reg := registry.NewRegistry()
	withSeams(t, &events, fs, reg)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Run(ctx, Options{Port: 8080}) }()

	select {
	case err := <-done:
		t.Fatalf("Failures 通道关闭（无错误）不得让 Run 提前返回，实际返回: %v", err)
	case <-time.After(100 * time.Millisecond):
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Failures 通道关闭场景下 ctx 取消应优雅退出返回 nil，实际: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("ctx 取消后 Run 未退出（消费 goroutine 可能泄漏/阻塞）")
	}
	if !fs.stopped {
		t.Error("ctx 取消后 Stop 必须被调用")
	}
}

// TestRun_FailuresWatcherGoroutineDoesNotLeak 钉死 Race-Free：Run 返回后消费
// Failures() 的 goroutine MUST 干净退出（不泄漏、不阻塞在已弃通道的发送上）。
// 以 goroutine 计数为准（两轮 Run，退出后回落至基线），容忍测试框架自身的
// 极短生命周期 goroutine：给出宽松上界，只在**持续增长**时判红。
func TestRun_FailuresWatcherGoroutineDoesNotLeak(t *testing.T) {
	baseline := runtime.NumGoroutine()

	// 每轮：ctx 取消路径（Run 已 return，消费 goroutine 必须随之退出）。
	for i := 0; i < 5; i++ {
		var events []string
		fs := &fakeSupervisor{events: &events, failC: make(chan error)} // 永不投递
		withSeams(t, &events, fs, registry.NewRegistry())

		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan error, 1)
		go func() { done <- Run(ctx, Options{Port: 8080}) }()
		cancel()
		if err := <-done; err != nil {
			t.Fatalf("第 %d 轮：ctx 取消应返回 nil，实际: %v", i, err)
		}
	}
	// 崩溃失败路径：消费 goroutine 投递完即退出。
	for i := 0; i < 5; i++ {
		var events []string
		failC := make(chan error, 1)
		fs := &fakeSupervisor{events: &events, failC: failC}
		withSeams(t, &events, fs, registry.NewRegistry())

		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		done := make(chan error, 1)
		go func() { done <- Run(ctx, Options{Port: 8080}) }()
		failC <- errors.New("boom")
		if err := <-done; err == nil {
			t.Fatalf("第 %d 轮：崩溃失败必须返回非 nil 错误", i)
		}
	}

	// 轮询等待回落（goroutine 退出是异步的）。
	deadline := time.Now().Add(3 * time.Second)
	for runtime.NumGoroutine() > baseline && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if leaked := runtime.NumGoroutine() - baseline; leaked > 0 {
		t.Errorf("Run 返回后 Failures 消费 goroutine 泄漏 %d 个（基线 %d，现 %d）",
			leaked, baseline, runtime.NumGoroutine())
	}
}

// captureLog 把标准 logger 输出重定向到内存，返回（读取日志内容, 还原函数）。
func captureLog(t *testing.T) (func() string, func()) {
	t.Helper()
	var mu sync.Mutex
	var buf strings.Builder
	prevOut := log.Writer()
	prevFlags := log.Flags()
	log.SetOutput(&lockWriter{w: &buf, mu: &mu})
	log.SetFlags(0)
	read := func() string {
		mu.Lock()
		defer mu.Unlock()
		return buf.String()
	}
	return read, func() {
		log.SetOutput(prevOut)
		log.SetFlags(prevFlags)
	}
}

// lockWriter 是并发安全的 io.Writer（-race 下 log 写入与测试读取不可数据竞争）。
type lockWriter struct {
	mu *sync.Mutex
	w  io.Writer
}

func (l *lockWriter) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.w.Write(p)
}
