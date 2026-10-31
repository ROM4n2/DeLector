package companion

import (
	"fmt"

	"github.com/sashabaranov/go-openai"
)

// DefaultContextMaxChars 默认伴学会话上下文字符预算上限（约 1000-1500 tokens）
const DefaultContextMaxChars = 4000

// CompactMessages 执行 Turn 间主动滑动窗口上下文压缩（Pi-Agent 流控范式）
// 保持首部 System Prompt 与尾部最近两轮完整交互，将中间过长的历史记录折叠为结构化状态锚点。
func CompactMessages(messages []openai.ChatCompletionMessage, maxChars int) []openai.ChatCompletionMessage {
	if maxChars <= 0 {
		maxChars = DefaultContextMaxChars
	}

	totalChars := 0
	for _, m := range messages {
		totalChars += len(m.Content)
		for _, tc := range m.ToolCalls {
			totalChars += len(tc.Function.Arguments)
		}
	}

	// 未超预算或消息条数不足以安全压缩时原样返回
	if totalChars <= maxChars || len(messages) <= 5 {
		return messages
	}

	// 保留尾部最近 4 条交互（约最近 2 轮问答对）
	tailCount := 4
	if len(messages) <= tailCount+1 {
		return messages
	}

	systemMsg := messages[0]
	middle := messages[1 : len(messages)-tailCount]
	tail := messages[len(messages)-tailCount:]

	anchorContent := fmt.Sprintf(
		"[前序上下文压缩锚点: 早前 %d 条对话历史已归档，包含学习者针对核心词汇/句型的初步分析与工具诊断]",
		len(middle),
	)
	anchorMsg := openai.ChatCompletionMessage{
		Role:    openai.ChatMessageRoleSystem,
		Content: anchorContent,
	}

	result := make([]openai.ChatCompletionMessage, 0, 2+len(tail))
	result = append(result, systemMsg, anchorMsg)
	result = append(result, tail...)
	return result
}
