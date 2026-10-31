package companion

import (
	"fmt"

	"github.com/sashabaranov/go-openai"
)

// DefaultContextMaxChars 默认伴学会话上下文字符预算上限（约 8000-10000 tokens）
const DefaultContextMaxChars = 32000

// CompactMessages 执行 Turn 间主动滑动窗口上下文压缩（Pi-Agent 流控范式）
// 核心铁律：
// 1. 首部 System Prompt（messages[0]）永远保留；
// 2. 当前正在进行的活跃交互块（从最后一条 User 消息开始的所有消息，包含 User、Assistant ToolCalls、Tool Results）永远保留，绝不可折叠，防止割裂 Tool 链或丢失用户意图；
// 3. 仅对发生在该活跃交互之前的历史对话（messages[1 : lastUserIdx]）执行结构化 Compaction 折叠为状态锚点。
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
	if totalChars <= maxChars || len(messages) <= 3 {
		return messages
	}

	// 从后往前寻找最近保留的交互起点（最多保留最近 2 轮问答，即从倒数第 2 条 User 消息开始）
	tailUserIdx := -1
	userCount := 0
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == openai.ChatMessageRoleUser {
			userCount++
			tailUserIdx = i
			if userCount >= 2 {
				break
			}
		}
	}

	// 若未发现 User 消息，或 User 消息就在起始位置（索引 <= 1），说明没有更早的历史轮次可供压缩
	if tailUserIdx <= 1 {
		return messages
	}

	systemMsg := messages[0]
	historyToCompact := messages[1:tailUserIdx]
	activeBlock := messages[tailUserIdx:]

	anchorContent := fmt.Sprintf(
		"[前序上下文压缩锚点: 早前 %d 条对话历史已归档，包含学习者针对核心词汇/句型的初步分析与工具诊断]",
		len(historyToCompact),
	)
	anchorMsg := openai.ChatCompletionMessage{
		Role:    openai.ChatMessageRoleSystem,
		Content: anchorContent,
	}

	result := make([]openai.ChatCompletionMessage, 0, 2+len(activeBlock))
	result = append(result, systemMsg, anchorMsg)
	result = append(result, activeBlock...)
	return result
}
