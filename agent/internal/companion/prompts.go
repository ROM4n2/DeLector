package companion

import (
	"fmt"
	"strings"

	"github.com/ROM4n2/DeLector/agent/internal/provider"
)

const (
	CompanionSystemPrompt = `你是 DeLector 德语研读系统的伴学导学伙伴「Eule」（猫头鹰博士）。
你的任务是为备考歌德/德福的德语学习者提供针对性的语用深挖、句法结构问诊与生词卡提议。
你可以调用以下工具辅助语言学分析：
- analyze: 依存语法与五领域结构分析（输入 text: 德语句子）
- writing_check: 考试写作规则检验（输入 text: 德语文本）
- vocab_stats: 词汇 CEFR 等级分布（输入 text: 德语文本）
- propose_vocab_cards: 向学习者提议将核心生词制作生词卡并存入本地复习卡盒（需由学习者显式确认）

解答风格要求：
- 请使用自然流畅、严谨的 Markdown 德式学术排版风格直接回答学习者的问题。
- 无论工具执行成功与否（即使工具调用遇到异常或空结果），你都必须依靠自身深厚的德语语言学知识给出完整、严谨、多维度（拓扑场、句框、核心动词位置、语用）的深度解析，严禁仅输出问号、标点符号、错误日志或空白。
- 如果需要生词制卡提议，请显式调用 propose_vocab_cards 工具，系统会渲染为确认卡片。
- 回答保持精炼、深入，结合学习者正在阅读的德语上下文。`

	DefaultPromptNudge = "已完成对当前句子的多维度语言学推演与分析。请参阅上方提取的语法拓扑信息，如需针对特定成分深入探讨，可随时追问。"
)

// FormatStudyContext 格式化前端视口上下文为 Markdown 文本块。
func FormatStudyContext(ctx StudyContext) string {
	if ctx.SelectedText == "" && ctx.ArticleTitle == "" && ctx.CEFRLevel == "" {
		return ""
	}
	var sb strings.Builder
	sb.WriteString("【当前学习视口上下文】")
	if ctx.ArticleTitle != "" {
		sb.WriteString(fmt.Sprintf("\n- 文章: %s", ctx.ArticleTitle))
	}
	if ctx.CEFRLevel != "" {
		sb.WriteString(fmt.Sprintf("\n- 目标级别: %s", ctx.CEFRLevel))
	}
	if ctx.SelectedText != "" {
		sb.WriteString(fmt.Sprintf("\n- 当前聚焦句子: %s", ctx.SelectedText))
	}
	return sb.String()
}

// BuildSystemPrompt 构建伴学智能体的完整系统提示词（合并基础人设、学习视口上下文与模型规格要求）。
func BuildSystemPrompt(activeContext string, modelSpec provider.ModelSpec) string {
	prompt := CompanionSystemPrompt
	trimmed := strings.TrimSpace(activeContext)
	if trimmed != "" {
		if !strings.HasPrefix(trimmed, "【当前学习视口上下文】") && !strings.Contains(trimmed, "【当前学习视口上下文】") {
			prompt += "\n\n【当前学习视口上下文】\n" + trimmed
		} else {
			prompt += "\n\n" + trimmed
		}
	}
	return prompt
}

// BuildPromptNudge 返回针对模型无实质回答（如仅输出问号或空白）时的学术解析兜底督促文本。
func BuildPromptNudge() string {
	return DefaultPromptNudge
}
