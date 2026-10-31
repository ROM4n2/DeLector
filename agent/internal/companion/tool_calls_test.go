package companion_test

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestAggregateToolCallsSingleAndStreamingChunks(t *testing.T) {
	idx0 := 0
	chunk1 := openai.ToolCall{
		Index: &idx0,
		ID:    "call_abc",
		Type:  openai.ToolTypeFunction,
		Function: openai.FunctionCall{
			Name:      "analyze",
			Arguments: `{"text": "`,
		},
	}
	chunk2 := openai.ToolCall{
		Index: &idx0,
		Function: openai.FunctionCall{
			Arguments: `Guten Morgen."}`,
		},
	}

	var calls []openai.ToolCall
	calls = companion.AggregateToolCalls(calls, chunk1)
	calls = companion.AggregateToolCalls(calls, chunk2)

	if len(calls) != 1 {
		t.Fatalf("expected 1 call, got %d", len(calls))
	}
	tc := calls[0]
	if tc.ID != "call_abc" {
		t.Errorf("expected ID call_abc, got %s", tc.ID)
	}
	if tc.Function.Name != "analyze" {
		t.Errorf("expected Name analyze, got %s", tc.Function.Name)
	}
	expectedArgs := `{"text": "Guten Morgen."}`
	if tc.Function.Arguments != expectedArgs {
		t.Errorf("expected Args %s, got %s", expectedArgs, tc.Function.Arguments)
	}
}

func TestAggregateToolCallsParallelAndOutOfOrder(t *testing.T) {
	idx0 := 0
	idx1 := 1

	chunkB := openai.ToolCall{
		Index: &idx1,
		ID:    "call_b",
		Type:  openai.ToolTypeFunction,
		Function: openai.FunctionCall{
			Name:      "vocab_stats",
			Arguments: `{"text":"test"}`,
		},
	}
	chunkA := openai.ToolCall{
		Index: &idx0,
		ID:    "call_a",
		Type:  openai.ToolTypeFunction,
		Function: openai.FunctionCall{
			Name:      "analyze",
			Arguments: `{"text":"test"}`,
		},
	}

	var calls []openai.ToolCall
	// Receive index 1 first, then index 0
	calls = companion.AggregateToolCalls(calls, chunkB)
	calls = companion.AggregateToolCalls(calls, chunkA)

	if len(calls) != 2 {
		t.Fatalf("expected 2 calls, got %d", len(calls))
	}
	if calls[0].ID != "call_a" || calls[0].Function.Name != "analyze" {
		t.Errorf("index 0 incorrect: %+v", calls[0])
	}
	if calls[1].ID != "call_b" || calls[1].Function.Name != "vocab_stats" {
		t.Errorf("index 1 incorrect: %+v", calls[1])
	}
}

func TestFormatToolErrorMessage(t *testing.T) {
	err := errors.New("network timeout")
	msg := companion.FormatToolErrorMessage("analyze", err)

	var parsed map[string]any
	if err := json.Unmarshal([]byte(msg), &parsed); err != nil {
		t.Fatalf("failed to parse JSON from FormatToolErrorMessage: %v", err)
	}

	if parsed["status"] != "error" {
		t.Errorf("expected status=error, got %v", parsed["status"])
	}
	if parsed["error_code"] != "TOOL_EXECUTION_FAILED" {
		t.Errorf("expected error_code=TOOL_EXECUTION_FAILED, got %v", parsed["error_code"])
	}
	if parsed["tool"] != "analyze" {
		t.Errorf("expected tool=analyze, got %v", parsed["tool"])
	}
	if parsed["message"] != "network timeout" {
		t.Errorf("expected message='network timeout', got %v", parsed["message"])
	}
	if !strings.Contains(parsed["hint"].(string), "工具执行暂时失败") {
		t.Errorf("unexpected hint: %v", parsed["hint"])
	}
}

func TestFormatToolArgErrorMessage(t *testing.T) {
	err := errors.New("invalid character 'x'")
	msg := companion.FormatToolArgErrorMessage("writing_check", "{bad json", err)

	var parsed map[string]any
	if err := json.Unmarshal([]byte(msg), &parsed); err != nil {
		t.Fatalf("failed to parse JSON: %v", err)
	}

	if parsed["error_code"] != "INVALID_TOOL_ARGUMENTS" {
		t.Errorf("expected INVALID_TOOL_ARGUMENTS, got %v", parsed["error_code"])
	}
	if parsed["raw"] != "{bad json" {
		t.Errorf("expected raw='{bad json', got %v", parsed["raw"])
	}
}
