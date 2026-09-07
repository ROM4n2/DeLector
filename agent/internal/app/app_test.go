package app

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// fakeSupervisor 记录 Start/Stop 调用，供装配顺序与优雅退出断言；不触网。
type fakeSupervisor struct {
	events   *[]string
	startErr error
	stopped  bool
}

func (f *fakeSupervisor) Start(ctx context.Context) error {
	*f.events = append(*f.events, "start")
	return f.startErr
}

func (f *fakeSupervisor) Stop() {
	*f.events = append(*f.events, "stop")
	f.stopped = true
}

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
