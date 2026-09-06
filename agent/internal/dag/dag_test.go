package dag

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"slices"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mustAdd 是测试辅助：AddStep 失败即终止测试（属编程错误，非被测行为）。
func mustAdd(t *testing.T, d *DAG, id string, fn StepFunc, deps ...string) {
	t.Helper()
	if err := d.AddStep(id, fn, deps...); err != nil {
		t.Fatalf("AddStep(%s): %v", id, err)
	}
}

// stepOut 断言 Run 结果中 res[id] 是该步输出的 map 并返回。
func stepOut(t *testing.T, res map[string]any, id string) map[string]any {
	t.Helper()
	out, ok := res[id].(map[string]any)
	if !ok {
		t.Fatalf("res[%s] 应为该步输出 map，实际: %#v", id, res[id])
	}
	return out
}

// testCtx 返回带兜底超时的测试 ctx：调度器若意外死锁，
// 测试以超时失败而非挂死。
func testCtx() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 5*time.Second)
}

// TestDAG_LinearChain 钉住：线性链 a→b→c 严格按依赖顺序串行执行，
// 每步 deps 是直接上游输出按 step id 合并的视图，Run 返回各步输出。
func TestDAG_LinearChain(t *testing.T) {
	d := NewDAG("linear")
	var mu sync.Mutex
	var order []string
	record := func(id string) {
		mu.Lock()
		defer mu.Unlock()
		order = append(order, id)
	}

	mustAdd(t, d, "a", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		record("a")
		return map[string]any{"x": 1}, nil
	})
	mustAdd(t, d, "b", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		record("b")
		aOut, ok := deps["a"].(map[string]any)
		if !ok {
			return nil, fmt.Errorf("b 未收到 a 的输出视图: %v", deps)
		}
		return map[string]any{"y": aOut["x"].(int) + 1}, nil
	}, "a")
	mustAdd(t, d, "c", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		record("c")
		bOut, ok := deps["b"].(map[string]any)
		if !ok {
			return nil, fmt.Errorf("c 未收到 b 的输出视图: %v", deps)
		}
		return map[string]any{"z": bOut["y"].(int) + 1}, nil
	}, "b")

	ctx, cancel := testCtx()
	defer cancel()
	res, err := d.Run(ctx, nil)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}

	mu.Lock()
	got := slices.Clone(order)
	mu.Unlock()
	if want := []string{"a", "b", "c"}; !slices.Equal(got, want) {
		t.Errorf("执行顺序 = %v，期望严格串行 %v", got, want)
	}
	if stepOut(t, res, "a")["x"] != 1 {
		t.Errorf("res[a] 输出不符: %v", res["a"])
	}
	if stepOut(t, res, "b")["y"] != 2 {
		t.Errorf("res[b] 未合并 a 的输出: %v", res["b"])
	}
	if stepOut(t, res, "c")["z"] != 3 {
		t.Errorf("res[c] 未合并 b 的输出: %v", res["c"])
	}
}

// TestDAG_DiamondParallel 钉住：菱形 a→[b,c] 的两支确并发。
// 验证手段是原子计数器 + 双向屏障：b、c 各自 close 自己的 channel 后
// 等对方的 start 信号，双方都启动才放行——若调度串行，先到者必然
// 等不到对方，2s 屏障超时返回错误使测试失败（超时仅作为串行调度的
// 失败信号；正常并发路径零等待通过，绝非 sleep 断言并发）。
func TestDAG_DiamondParallel(t *testing.T) {
	d := NewDAG("diamond")
	var started atomic.Int32
	bStarted := make(chan struct{})
	cStarted := make(chan struct{})

	mustAdd(t, d, "a", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return map[string]any{"x": 1}, nil
	})
	barrier := func(self, other chan struct{}, selfID, otherID string) StepFunc {
		return func(_ context.Context, deps map[string]any) (map[string]any, error) {
			started.Add(1)
			close(self)
			select {
			case <-other:
			case <-time.After(2 * time.Second):
				return nil, fmt.Errorf("屏障超时：%s 未与 %s 并发启动（调度疑似串行）", selfID, otherID)
			}
			aOut, ok := deps["a"].(map[string]any)
			if !ok {
				return nil, fmt.Errorf("%s 未收到 a 的输出视图: %v", selfID, deps)
			}
			return map[string]any{"from": selfID, "x": aOut["x"]}, nil
		}
	}
	mustAdd(t, d, "b", barrier(bStarted, cStarted, "b", "c"), "a")
	mustAdd(t, d, "c", barrier(cStarted, bStarted, "c", "b"), "a")

	ctx, cancel := testCtx()
	defer cancel()
	res, err := d.Run(ctx, nil)
	if err != nil {
		t.Fatalf("Run: %v（b、c 应确并发执行）", err)
	}
	if started.Load() != 2 {
		t.Errorf("原子计数器应记录 b、c 均已启动，实际: %d", started.Load())
	}
	if stepOut(t, res, "b")["from"] != "b" || stepOut(t, res, "c")["from"] != "c" {
		t.Errorf("并行支输出应各自独立: b=%v c=%v", res["b"], res["c"])
	}
}

// TestDAG_CycleDetection 钉住：空 id、依赖含自身、依赖链成环均被
// AddStep 拒绝（返回 error），被拒步骤不得入图且不影响已加入步骤。
func TestDAG_CycleDetection(t *testing.T) {
	d := NewDAG("cycle")
	noop := func(_ context.Context, _ map[string]any) (map[string]any, error) { return nil, nil }

	// 卫语句组：空 id、自依赖。
	if err := d.AddStep("", noop); err == nil {
		t.Error("空 step id 应被拒绝")
	}
	if err := d.AddStep("self", noop, "self"); err == nil {
		t.Error("依赖含自身应被拒绝")
	}

	// 构造 a→b→c→a：a 前向引用尚未加入的 c，b 依赖 a；
	// 加入 c 时其依赖链 b→a→c 回到自身，DFS 必须拒绝。
	if err := d.AddStep("a", noop, "c"); err != nil {
		t.Fatalf("AddStep(a)（前向引用 c）: %v", err)
	}
	if err := d.AddStep("b", noop, "a"); err != nil {
		t.Fatalf("AddStep(b): %v", err)
	}
	if err := d.AddStep("c", noop, "b"); err == nil {
		t.Fatal("成环步骤 c 应被 AddStep 拒绝")
	}

	// 白盒：被拒的 c 不得入图，已加入步骤不受影响。
	if _, exists := d.steps["c"]; exists {
		t.Error("被拒的 c 不得加入图")
	}
	if _, exists := d.steps["a"]; !exists {
		t.Error("拒绝 c 不得影响已加入的 a")
	}
	if _, exists := d.steps["b"]; !exists {
		t.Error("拒绝 c 不得影响已加入的 b")
	}
	// a 的前向引用 c 因拒绝而未闭合，Run 必须报错而非死等。
	if _, err := d.Run(context.Background(), nil); err == nil {
		t.Error("前向引用未闭合（缺步 c）时 Run 应报错")
	}
}

// TestDAG_FailFast 钉住：中步失败时 fail-fast——Run 返回该步错误，
// 下游步骤不执行（原子标记断言）。
func TestDAG_FailFast(t *testing.T) {
	d := NewDAG("failfast")
	var cRan atomic.Bool
	boom := errors.New("boom: b 失败")

	mustAdd(t, d, "a", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return map[string]any{"ok": true}, nil
	})
	mustAdd(t, d, "b", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return nil, boom
	}, "a")
	mustAdd(t, d, "c", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		cRan.Store(true)
		return map[string]any{"unreachable": true}, nil
	}, "b")

	ctx, cancel := testCtx()
	defer cancel()
	_, err := d.Run(ctx, nil)
	if !errors.Is(err, boom) {
		t.Fatalf("Run 应返回 b 的错误，实际: %v", err)
	}
	if cRan.Load() {
		t.Error("fail-fast：b 失败后下游 c 不应执行")
	}
}

// TestDAG_ContextTimeout 钉住：ctx 超时后整体取消，步骤在 ctx 取消时
// 返回 ctx.Err()，且 Run 的错误可 errors.Is(err, context.DeadlineExceeded)
// 判定（禁字符串比较）。
func TestDAG_ContextTimeout(t *testing.T) {
	d := NewDAG("timeout")
	mustAdd(t, d, "slow", func(ctx context.Context, _ map[string]any) (map[string]any, error) {
		select {
		case <-time.After(10 * time.Second): // 永不应到达
			return map[string]any{"done": true}, nil
		case <-ctx.Done():
			return nil, ctx.Err() // 步骤在 ctx 取消时返回 ctx.Err()
		}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_, err := d.Run(ctx, nil)
	if err == nil {
		t.Fatal("ctx 超时后 Run 应返回错误")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("应可 errors.Is(err, context.DeadlineExceeded) 判定，实际: %v", err)
	}
}

// TestExampleArticleAnalysisDAG 是对 ADR-0008 文章分析拓扑的防漂移钉板：
// ingest → [nlp, tts] 并行 → writing_check → export。
// 步骤均为桩函数（真实工具经 internal/registry 组装，非本测试职责）。
// 断言：并行支都执行、writing_check 的 deps 合并视图键齐全（恰为
// nlp+tts 两支）、Run 返回 map 覆盖全部 5 个 step id。
// 拓扑任何漂移（增删支、改依赖）必须同步修订 ADR-0008 与本测试。
func TestExampleArticleAnalysisDAG(t *testing.T) {
	d := NewDAG("article-analysis")
	var nlpRan, ttsRan atomic.Bool

	mustAdd(t, d, "ingest", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return map[string]any{"article": "hello world"}, nil
	})
	mustAdd(t, d, "nlp", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		nlpRan.Store(true)
		in, ok := deps["ingest"].(map[string]any)
		if !ok {
			return nil, fmt.Errorf("nlp 未收到 ingest 输出: %v", deps)
		}
		return map[string]any{"summary": "摘要(" + in["article"].(string) + ")"}, nil
	}, "ingest")
	mustAdd(t, d, "tts", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		ttsRan.Store(true)
		in, ok := deps["ingest"].(map[string]any)
		if !ok {
			return nil, fmt.Errorf("tts 未收到 ingest 输出: %v", deps)
		}
		return map[string]any{"audio": in["article"].(string) + ".mp3"}, nil
	}, "ingest")
	mustAdd(t, d, "writing_check", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		// 回显合并视图键：钉住 nlp+tts 两支输出同时就绪且键齐全。
		return map[string]any{"deps_seen": slices.Sorted(maps.Keys(deps))}, nil
	}, "nlp", "tts")
	mustAdd(t, d, "export", func(_ context.Context, deps map[string]any) (map[string]any, error) {
		wc, ok := deps["writing_check"].(map[string]any)
		if !ok {
			return nil, fmt.Errorf("export 未收到 writing_check 输出: %v", deps)
		}
		return map[string]any{"exported": wc["deps_seen"] != nil}, nil
	}, "writing_check")

	ctx, cancel := testCtx()
	defer cancel()
	res, err := d.Run(ctx, nil)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !nlpRan.Load() || !ttsRan.Load() {
		t.Errorf("ADR-0008 并行支 nlp/tts 都应执行（nlp=%v tts=%v）", nlpRan.Load(), ttsRan.Load())
	}
	for _, id := range []string{"ingest", "nlp", "tts", "writing_check", "export"} {
		if _, ok := res[id]; !ok {
			t.Errorf("Run 输出应覆盖全部 step id，缺 %q", id)
		}
	}
	if got := stepOut(t, res, "writing_check")["deps_seen"].([]string); !slices.Equal(got, []string{"nlp", "tts"}) {
		t.Errorf("writing_check 的 deps 合并视图键应恰为 [nlp tts]，实际: %v", got)
	}
	if stepOut(t, res, "export")["exported"] != true {
		t.Errorf("export 应消费到 writing_check 的输出: %v", res["export"])
	}
}
