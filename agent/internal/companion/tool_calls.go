package companion

import (
	"encoding/json"
	"fmt"

	"github.com/sashabaranov/go-openai"
)

// AggregateToolCalls aggregates streaming delta tool call chunks by their original indices.
func AggregateToolCalls(calls map[int]*openai.ToolCall, tc openai.ToolCall) map[int]*openai.ToolCall {
	if calls == nil {
		calls = make(map[int]*openai.ToolCall)
	}
	idx := 0
	if tc.Index != nil {
		idx = *tc.Index
	}
	existing, ok := calls[idx]
	if !ok {
		newCall := tc
		calls[idx] = &newCall
		return calls
	}
	if tc.ID != "" {
		existing.ID = tc.ID
	}
	if tc.Function.Name != "" {
		existing.Function.Name += tc.Function.Name
	}
	if tc.Function.Arguments != "" {
		existing.Function.Arguments += tc.Function.Arguments
	}
	return calls
}

// FilterValidToolCalls materializes the contiguous call prefix used by the chat message contract.
func FilterValidToolCalls(calls map[int]*openai.ToolCall) []openai.ToolCall {
	var valid []openai.ToolCall
	for i := 0; i < len(calls); i++ {
		if call, ok := calls[i]; ok {
			valid = append(valid, *call)
		}
	}
	return valid
}

// FormatToolErrorMessage formats a tool execution failure into a structured self-healing JSON message
// adhering to the Pi-Agent Errors-as-Messages principle.
func FormatToolErrorMessage(toolName string, err error) string {
	msg := ""
	if err != nil {
		msg = err.Error()
	}
	payload := map[string]any{
		"status":     "error",
		"error_code": "TOOL_EXECUTION_FAILED",
		"tool":       toolName,
		"message":    msg,
		"hint":       "工具执行暂时失败。请向学习者说明情况并给出基于已有上下文的专业解答，或调整参数重试。",
	}
	bytes, _ := json.Marshal(payload)
	return string(bytes)
}

// FormatToolArgErrorMessage formats tool argument unmarshaling errors into structured JSON.
func FormatToolArgErrorMessage(toolName string, rawArgs string, err error) string {
	msg := ""
	if err != nil {
		msg = err.Error()
	}
	payload := map[string]any{
		"status":     "error",
		"error_code": "INVALID_TOOL_ARGUMENTS",
		"tool":       toolName,
		"message":    fmt.Sprintf("工具参数 JSON 解析失败: %s", msg),
		"raw":        rawArgs,
		"hint":       "请确保为该工具传入合法 JSON 格式的对象参数。",
	}
	bytes, _ := json.Marshal(payload)
	return string(bytes)
}
