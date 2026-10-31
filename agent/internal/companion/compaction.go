package companion

import (
	"fmt"

	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

// DefaultContextMaxChars 默认伴学会话上下文字符预算上限（约 8000-10000 tokens）
const DefaultContextMaxChars = 32000

// EstimateTokens 估算一组 ChatCompletionMessage 的 Token 占用量（Pi 流控标准轻量估算法）
func EstimateTokens(messages []openai.ChatCompletionMessage) int {
	tokens := 0
	for _, m := range messages {
		tokens += 4 // 消息协议包装 overhead
		tokens += estimateStringTokens(m.Content)
		tokens += estimateStringTokens(m.ReasoningContent)
		for _, tc := range m.ToolCalls {
			tokens += 10 // ToolCall 协议 overhead
			tokens += estimateStringTokens(tc.Function.Name)
			tokens += estimateStringTokens(tc.Function.Arguments)
		}
	}
	tokens += 2 // Assistant 回复引导
	return tokens
}

func estimateStringTokens(s string) int {
	if len(s) == 0 {
		return 0
	}
	runeCount := 0
	for _, r := range s {
		if r > 127 {
			runeCount += 2 // 非 ASCII / CJK / 德语变音字符加权
		} else {
			runeCount += 1
		}
	}
	return (runeCount + 2) / 3
}

// CompactMessagesDynamic 执行基于模型硬件规格（ModelSpec）与 Pi 范式 60% 水位线的动态上下文流控压缩。
// 规则：
// 1. 首部 System Prompt 永远保留；
// 2. 活跃交互块（倒数第 2 条 User 提示词起至末尾的全部消息，含活跃 Tool 链）永远完整保留；
// 3. 仅当总 Token 估算超过 ContextWindow * CompactionRatio（默认 60%）时，才将更早的历史轮次折叠为结构化状态锚点。
func CompactMessagesDynamic(messages []openai.ChatCompletionMessage, spec provider.ModelSpec) []openai.ChatCompletionMessage {
	if len(messages) <= 3 {
		return messages
	}

	ratio := spec.CompactionRatio
	if ratio <= 0 || ratio >= 1.0 {
		ratio = provider.DefaultCompactionRatio
	}
	window := spec.ContextWindow
	if window <= 0 {
		window = provider.CustomContextWindow
	}
	threshold := int(float64(window) * ratio)

	currentTokens := EstimateTokens(messages)
	if currentTokens <= threshold {
		return messages
	}

	return compactHistory(messages)
}

// CompactMessages 执行 Turn 间主动滑动窗口上下文压缩（向后兼容字符预算接口）
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

	return compactHistory(messages)
}

func compactHistory(messages []openai.ChatCompletionMessage) []openai.ChatCompletionMessage {
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
