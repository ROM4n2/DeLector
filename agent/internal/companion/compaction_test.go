package companion_test

import (
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestCompactMessagesWithinBudget(t *testing.T) {
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "You are a German tutor."},
		{Role: openai.ChatMessageRoleUser, Content: "Hallo!"},
		{Role: openai.ChatMessageRoleAssistant, Content: "Guten Tag! Wie kann ich helfen?"},
	}

	compacted := companion.CompactMessages(msgs, 4000)
	if len(compacted) != len(msgs) {
		t.Fatalf("expected length %d, got %d", len(msgs), len(compacted))
	}
}

func TestCompactMessagesExceedingBudget(t *testing.T) {
	longText := strings.Repeat("Sehr lange deutsche Erklärung über Grammatik und Syntax. ", 40) // ~2400 chars

	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System Prompt with Study Context"},
		// Middle turns to be compacted
		{Role: openai.ChatMessageRoleUser, Content: "Erste Frage: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Erste Antwort: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Zweite Frage: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Zweite Antwort: " + longText},
		// Recent 2 turns to be preserved
		{Role: openai.ChatMessageRoleUser, Content: "Dritte Frage: Was bedeutet das Wort?"},
		{Role: openai.ChatMessageRoleAssistant, Content: "Dritte Antwort: Es bedeutet XYZ."},
		{Role: openai.ChatMessageRoleUser, Content: "Vierte Frage: Bitte gib mir ein Beispiel."},
		{Role: openai.ChatMessageRoleAssistant, Content: "Vierte Antwort: Hier ist ein Beispielsatz."},
	}

	// Budget is 3000 chars, total text is > 10000 chars
	compacted := companion.CompactMessages(msgs, 3000)

	// Expected: System prompt (1) + Anchor (1) + Last 4 messages = 6 messages
	if len(compacted) != 6 {
		t.Fatalf("expected 6 messages after compaction, got %d", len(compacted))
	}

	if compacted[0].Content != "System Prompt with Study Context" {
		t.Errorf("system prompt was not preserved at index 0")
	}

	if !strings.Contains(compacted[1].Content, "前序上下文压缩锚点") {
		t.Errorf("expected anchor message at index 1, got %s", compacted[1].Content)
	}

	if compacted[len(compacted)-1].Content != "Vierte Antwort: Hier ist ein Beispielsatz." {
		t.Errorf("last message was not preserved")
	}
}
