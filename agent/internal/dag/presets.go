package dag

import (
	"context"
	"fmt"

	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// ArticleAnalysisDAG 构建 article-analysis 预设：按 ADR-0008 修订版 4 层口径
// （评论口径：ingest→[analyze,tts]→writing_check→export）。
//
// 口径锚点：ADR-0008 修订版明确 cefr 不独立成层（Phase 2b 已知收敛，归 Phase 2c
// 再议），故本预设仅 4 层。工具名须与 registry.DefaultRegistry 实际注册名一致
// （ingest/analyze/writing_check/export/tts，见 registry.defaultTools），否则
// 工具未注册将在运行时经 ErrUnknownTool 暴露（presets_test 钉此不变量防漂移）。
//
// 依赖方向：本预设工厂位于 dag 包，import registry（消费侧），不引入反向依赖；
// registry 不 import dag，app 装配层负责把 ToolFunc 适配为 StepFunc（见 app.Run）。
func ArticleAnalysisDAG(tools *registry.Registry) (*DAG, error) {
	g := NewDAG("article-analysis")

	// 第 1 层：ingest——入站抓取（payload 含 url），无依赖。
	ingest := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return tools.Run(ctx, "ingest", deps)
	}
	if err := g.AddStep("ingest", ingest); err != nil {
		return nil, fmt.Errorf("dag: article-analysis 预设构建失败: %w", err)
	}

	// 第 2 层：[analyze, tts]——文本分析 / 语音合成，并行，均依赖 ingest 产出。
	analyze := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return tools.Run(ctx, "analyze", map[string]any{"text": extractText(deps["ingest"])})
	}
	if err := g.AddStep("analyze", analyze, "ingest"); err != nil {
		return nil, fmt.Errorf("dag: article-analysis 预设构建失败: %w", err)
	}
	tts := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return tools.Run(ctx, "tts", map[string]any{"text": extractText(deps["ingest"])})
	}
	if err := g.AddStep("tts", tts, "ingest"); err != nil {
		return nil, fmt.Errorf("dag: article-analysis 预设构建失败: %w", err)
	}

	// 第 3 层：writing_check——A1 写作诊断，依赖 analyze + tts（评论口径）。
	writingCheck := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return tools.Run(ctx, "writing_check", map[string]any{"text": extractText(deps["ingest"])})
	}
	if err := g.AddStep("writing_check", writingCheck, "analyze", "tts"); err != nil {
		return nil, fmt.Errorf("dag: article-analysis 预设构建失败: %w", err)
	}

	// 第 4 层：export——Anki 牌组导出，依赖 writing_check；output_path 由上游/
	// input 提供（Python 侧拒绝服务端自选临时路径，缺省由该工具报错）。
	export := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		payload := map[string]any{}
		if out, ok := deps["writing_check"].(map[string]any); ok {
			if op, ok := out["output_path"].(string); ok {
				payload["output_path"] = op
			}
		}
		return tools.Run(ctx, "export", payload)
	}
	if err := g.AddStep("export", export, "writing_check"); err != nil {
		return nil, fmt.Errorf("dag: article-analysis 预设构建失败: %w", err)
	}

	return g, nil
}

// extractText 从上游步骤产出中提取喂给下游工具的文本：优先 text，其次 html、
// url（best-effort 透传；真实链路中 ingest 产出 html，文本抽取由 NLP 侧完成，
// 此处仅做确定性透传，避免预设层引入业务抽取逻辑）。
func extractText(v any) string {
	m, ok := v.(map[string]any)
	if !ok {
		return ""
	}
	for _, key := range []string{"text", "html", "url"} {
		if s, ok := m[key].(string); ok {
			return s
		}
	}
	return ""
}
