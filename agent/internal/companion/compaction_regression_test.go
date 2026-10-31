package companion_test

import (
	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
	"testing"
)

func TestReproUserPromptLostInToolCompaction(t *testing.T) {
	largeToolJSON := string(make([]byte, 8000))
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System"},
		{Role: openai.ChatMessageRoleUser, Content: "请帮我分析选中文本的主从句拓扑结构与核心动词位置。"},
		{Role: openai.ChatMessageRoleAssistant, ToolCalls: []openai.ToolCall{{ID: "c1"}, {ID: "c2"}, {ID: "c3"}}},
		{Role: openai.ChatMessageRoleTool, ToolCallID: "c1", Content: largeToolJSON},
		{Role: openai.ChatMessageRoleTool, ToolCallID: "c2", Content: "stats"},
		{Role: openai.ChatMessageRoleTool, ToolCallID: "c3", Content: "rules"},
	}

	compacted := companion.CompactMessages(msgs, 4000)

	hasUser := false
	for _, m := range compacted {
		if m.Role == openai.ChatMessageRoleUser {
			hasUser = true
			break
		}
	}
	if !hasUser {
		t.Fatalf("CRITICAL BUG REPRODUCED: CompactMessages stripped away the active user prompt!")
	}
}
