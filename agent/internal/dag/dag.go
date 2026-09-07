// Package dag 提供自研 DAG 调度器：按依赖关系并行执行 StepFunc 图
// （ADR-0008 裁定的自研实现，禁 cgo / langchaingo）。
//
// 调度语义：每步一个 goroutine——无依赖步骤与已就绪步骤并行，依赖
// 未就绪的步骤等待直接依赖完成；任一步失败立即 fail-fast，取消的
// context 传播给在跑步骤，Run 返回首个错误；ctx 超时/取消则整体收场，
// 超时错误经 %w 包装，调用方以 errors.Is(err, context.DeadlineExceeded)
// 判定（禁字符串比较）。
//
// 依赖方向：dag 位于 registry 之下（cmd → registry → dag → pythonsvc/llm）。
// 本包作为消费侧 import registry（见 presets.go：ArticleAnalysisDAG 工厂），
// registry 不反向 import dag（无环）；调用方在组装层把 ToolFunc 适配为 StepFunc。
package dag

import (
	"context"
	"errors"
	"fmt"
	"sync"
)

// StepFunc 是 DAG 步骤的统一执行签名。deps 是直接依赖步骤的输出按
// step id 合并的视图（key 为上游 step id）；无依赖步骤收到的 deps 是
// Run 传入 input 的浅拷贝（虚拟上游）。实现必须尊重 ctx：取消后尽快返回。
type StepFunc func(ctx context.Context, deps map[string]any) (map[string]any, error)

// dagStep 是图中的一个节点：id 唯一，deps 指向直接上游的 step id
// （允许前向引用尚未加入的步骤，Run 前必须全部闭合）。图建成后只读。
type dagStep struct {
	id   string
	fn   StepFunc
	deps []string
}

// runState 是单次 Run 内每步的运行期状态：done 在该步终止（成功或失败）
// 后关闭，作为下游的就绪信号；output 仅由本步 goroutine 在关闭 done 前
// 写入一次，所有读方均先收 <-done，经 channel 关闭的 happens-before
// 保证无锁安全。按次分配使同一 DAG 可安全重复 Run。
type runState struct {
	done   chan struct{}
	output map[string]any
}

// DAG 是以 step id 为节点的有向无环图。零值不可用，经 NewDAG 构造。
// 并发语义：AddStep 非并发安全，仅限构造期串行调用；图建成后 steps
// 只读，Run 可安全并发调用（各次运行的步骤输出经 runState 隔离）。
type DAG struct {
	name  string
	steps map[string]*dagStep
}

// NewDAG 构造名为 name 的空 DAG（name 用于错误信息定位）。
func NewDAG(name string) *DAG {
	return &DAG{name: name, steps: make(map[string]*dagStep)}
}

// AddStep 向图中加入一个步骤：id 非空且唯一，fn 非空，deps 为直接上游
// step id（可为空 = 无依赖步骤）。建图期做环检测：沿已建图 DFS 新步骤
// 的依赖链，若回到自身则拒绝加入并返回错误，图保持原状。
// 非并发安全，须在构造期串行调用。
func (d *DAG) AddStep(id string, fn StepFunc, deps ...string) error {
	if id == "" {
		return errors.New("dag: step id must not be empty")
	}
	if fn == nil {
		return fmt.Errorf("dag: step %q: fn must not be nil", id)
	}
	if _, exists := d.steps[id]; exists {
		return fmt.Errorf("dag: step %q already exists", id)
	}
	for _, dep := range deps {
		if dep == "" {
			return fmt.Errorf("dag: step %q: dependency id must not be empty", id)
		}
		if dep == id {
			return fmt.Errorf("dag: step %q must not depend on itself", id)
		}
	}
	// DFS 环检测：新步骤依赖链上出现自己即成环，拒绝加入。
	for _, dep := range deps {
		if d.depChainReaches(dep, id, make(map[string]bool)) {
			return fmt.Errorf("dag %q: add step %q would create a dependency cycle via %q", d.name, id, dep)
		}
	}
	// 拷贝 deps，建图后拓扑不可变（防调用方持有可变切片）。
	d.steps[id] = &dagStep{id: id, fn: fn, deps: append([]string(nil), deps...)}
	return nil
}

// depChainReaches 自 current 沿依赖边 DFS，报告 current 的传递依赖闭包
// 是否抵达 target。已建图无环（构造期不变量，visited 防共享祖先重访）；
// 未加入图的依赖 id 视为叶子（前向引用，存在性由 Run 校验）。
func (d *DAG) depChainReaches(current, target string, visited map[string]bool) bool {
	if current == target {
		return true
	}
	if visited[current] {
		return false
	}
	visited[current] = true
	s, ok := d.steps[current]
	if !ok {
		return false
	}
	for _, dep := range s.deps {
		if d.depChainReaches(dep, target, visited) {
			return true
		}
	}
	return false
}

// validateDeps 校验全部依赖 id 均已加入图（前向引用必须在 Run 前闭合），
// 否则调度会死等，直接报错而非挂死。
func (d *DAG) validateDeps() error {
	for _, s := range d.steps {
		for _, dep := range s.deps {
			if _, ok := d.steps[dep]; !ok {
				return fmt.Errorf("dag %q: step %q depends on missing step %q", d.name, s.id, dep)
			}
		}
	}
	return nil
}

// Run 按依赖拓扑执行全图。input 作为无依赖步骤的虚拟上游可见数据
// （其 deps 视图即 input 浅拷贝）；返回 map[step id]该步输出。
// 调度语义：每步一个 goroutine，就绪即跑、未就绪等待；任一步失败
// fail-fast（取消 ctx 传播给在跑步骤，返回首个错误）；ctx 超时/取消
// 则整体收场，超时错误经 %w 包装，可用 errors.Is(err, context.DeadlineExceeded)
// 判定。
func (d *DAG) Run(ctx context.Context, input map[string]any) (map[string]any, error) {
	if err := d.validateDeps(); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	states := make(map[string]*runState, len(d.steps))
	for _, s := range d.steps {
		states[s.id] = &runState{done: make(chan struct{})}
	}

	// 容量 1 + 非阻塞发送：并发失败时只保留首个错误（fail-fast 语义）。
	errCh := make(chan error, 1)
	var wg sync.WaitGroup
	for _, s := range d.steps {
		wg.Add(1)
		go d.runStep(ctx, cancel, s, states, input, errCh, &wg)
	}
	wg.Wait()

	// 首错误优先；无步骤级错误时以 ctx 超时/取消兜底（%w 包装保 errors.Is 判定）。
	select {
	case err := <-errCh:
		return nil, err
	default:
	}
	if err := ctx.Err(); err != nil {
		return nil, fmt.Errorf("dag %q: %w", d.name, err)
	}
	results := make(map[string]any, len(d.steps))
	for _, s := range d.steps {
		results[s.id] = states[s.id].output
	}
	return results, nil
}

// runStep 是单步的 goroutine 主体：等待直接依赖就绪 → 合并 deps 视图 →
// 执行 → 记录输出。close(done) 由 defer 保证，无论成败都放行下游等待者；
// 下游再经 ctx.Done() / ctx.Err() 感知失败并放弃执行。
func (d *DAG) runStep(ctx context.Context, cancel context.CancelFunc, s *dagStep, states map[string]*runState, input map[string]any, errCh chan error, wg *sync.WaitGroup) {
	defer wg.Done()
	defer close(states[s.id].done)

	for _, depID := range s.deps {
		select {
		case <-states[depID].done:
		case <-ctx.Done():
			return // fail-fast / 超时：放弃执行
		}
	}
	if ctx.Err() != nil {
		return
	}
	out, err := s.fn(ctx, d.mergeDeps(s, states, input))
	if err != nil {
		select {
		case errCh <- err:
		default: // 已有更早的错误，丢弃本错误（保首个）
		}
		cancel() // fail-fast：取消传播给在跑步骤
		return
	}
	states[s.id].output = out
}

// mergeDeps 构造本步的 deps 视图：直接依赖的输出按 step id 合并；
// 无依赖步骤收到 input 的浅拷贝（虚拟上游），隔离步骤间对 input 的变更。
func (d *DAG) mergeDeps(s *dagStep, states map[string]*runState, input map[string]any) map[string]any {
	if len(s.deps) == 0 {
		view := make(map[string]any, len(input))
		for k, v := range input {
			view[k] = v
		}
		return view
	}
	view := make(map[string]any, len(s.deps))
	for _, depID := range s.deps {
		view[depID] = states[depID].output
	}
	return view
}
