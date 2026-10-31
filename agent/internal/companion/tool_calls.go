package companion

import (
	"encoding/json"
	"fmt"

	"github.com/sashabaranov/go-openai"
)

// AggregateToolCalls aggregates a streaming delta tool call chunk into a slice of tool calls.
// It accumulates indices, ID, Type, Function Name, and Function Arguments.
func AggregateToolCalls(calls []openai.ToolCall, tc openai.ToolCall) []openai.ToolCall {
	idx := 0
	if tc.Index != nil {
		idx = *tc.Index
	}
	if idx < 0 {
		idx = 0
	}

	for len(calls) <= idx {
		calls = append(calls, openai.ToolCall{
			Type: openai.ToolTypeFunction,
		})
	}

	target := &calls[idx]
	if tc.Index != nil {
		i := *tc.Index
		target.Index = &i
	}
	if tc.ID != "" {
		target.ID = tc.ID
	}
	if tc.Type != "" {
		target.Type = tc.Type
	}
	if tc.Function.Name != "" {
		target.Function.Name += tc.Function.Name
	}
	if tc.Function.Arguments != "" {
		target.Function.Arguments += tc.Function.Arguments
	}

	return calls
}

// FilterValidToolCalls filters out uninitialized or empty tool calls from the aggregated list.
func FilterValidToolCalls(calls []openai.ToolCall) []openai.ToolCall {
	var valid []openai.ToolCall
	for _, tc := range calls {
		if tc.ID != "" || tc.Function.Name != "" {
			valid = append(valid, tc)
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
