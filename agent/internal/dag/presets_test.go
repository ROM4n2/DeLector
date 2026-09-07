package dag

import (
	"context"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// noopTool 注册用空工具：仅返回空 dict，供预设构建与拓扑断言，不触网。
func noopTool(ctx context.Context, p map[string]any) (map[string]any, error) {
	return map[string]any{}, nil
}

// TestArticleAnalysisDAG_Topology 防漂移钉板：断言步骤集与依赖边严格符合
// ADR-0008 修订版 4 层口径（ingest→[analyze,tts]→writing_check→export），
// 且每个步骤名都存在于 registry.DefaultRegistry 实际注册名中（防注册表漂移）。
func TestArticleAnalysisDAG_Topology(t *testing.T) {
	reg := registry.NewRegistry()
	for _, name := range []string{"ingest", "analyze", "writing_check", "export", "tts"} {
		if err := reg.Register(name, noopTool); err != nil {
			t.Fatalf("注册工具 %q 失败: %v", name, err)
		}
	}

	g, err := ArticleAnalysisDAG(reg)
	if err != nil {
		t.Fatalf("ArticleAnalysisDAG 构建失败: %v", err)
	}

	// 步骤集断言
	wantSteps := []string{"ingest", "analyze", "tts", "writing_check", "export"}
	for _, s := range wantSteps {
		if _, ok := g.steps[s]; !ok {
			t.Errorf("DAG 缺步骤 %q", s)
		}
	}
	if len(g.steps) != len(wantSteps) {
		t.Errorf("DAG 步骤数应为 %d，实际 %d（%v）", len(wantSteps), len(g.steps), keysOfSteps(g.steps))
	}

	// 依赖边断言（顺序敏感：AddStep 按传入顺序记 deps）
	assertDeps(t, g, "ingest")
	assertDeps(t, g, "analyze", "ingest")
	assertDeps(t, g, "tts", "ingest")
	assertDeps(t, g, "writing_check", "analyze", "tts")
	assertDeps(t, g, "export", "writing_check")

	// 防漂移：每个步骤名必须在 DefaultRegistry 实际注册名中（工具更名/删除
	// 时本测试立刻红，防止预设与注册表口径撕裂）。
	realReg := registry.DefaultRegistry(pythonsvc.NewClient("http://127.0.0.1:8001", nil))
	for name := range g.steps {
		if !realReg.Has(name) {
			t.Errorf("DAG 步骤 %q 不在 registry.DefaultRegistry 注册名中（漂移！）", name)
		}
	}
}

func assertDeps(t *testing.T, g *DAG, id string, want ...string) {
	t.Helper()
	s, ok := g.steps[id]
	if !ok {
		t.Fatalf("步骤 %q 不存在", id)
	}
	if len(s.deps) != len(want) {
		t.Fatalf("步骤 %q 依赖数应为 %d，实际 %d（%v）", id, len(want), len(s.deps), s.deps)
	}
	for i := range want {
		if s.deps[i] != want[i] {
			t.Errorf("步骤 %q 第 %d 个依赖应为 %q，实际 %q", id, i, want[i], s.deps[i])
		}
	}
}

func keysOfSteps(m map[string]*dagStep) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
