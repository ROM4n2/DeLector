package companion_test

import (
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

func TestCompactContextUnderBudget(t *testing.T) {
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "You are a German tutor."},
		{Role: openai.ChatMessageRoleUser, Content: "Hallo!"},
		{Role: openai.ChatMessageRoleAssistant, Content: "Guten Tag! Wie kann ich helfen?"},
	}

	compacted := companion.CompactContext(msgs, 4000)
	if len(compacted) != len(msgs) {
		t.Fatalf("expected length %d, got %d", len(msgs), len(compacted))
	}
}

func TestCompactContextFolding(t *testing.T) {
	longText := strings.Repeat("Sehr lange deutsche Erklärung über Grammatik und Syntax. ", 40) // ~2400 chars

	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System Prompt with Study Context"},
		// Middle turns to be compacted
		{Role: openai.ChatMessageRoleUser, Content: "Erste Frage: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Erste Antwort: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Zweite Frage: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Zweite Antwort: " + longText},
		// Recent 2 turns to be preserved (4 messages)
		{Role: openai.ChatMessageRoleUser, Content: "Dritte Frage: Was bedeutet das Wort?"},
		{Role: openai.ChatMessageRoleAssistant, Content: "Dritte Antwort: Es bedeutet XYZ."},
		{Role: openai.ChatMessageRoleUser, Content: "Vierte Frage: Bitte gib mir ein Beispiel."},
		{Role: openai.ChatMessageRoleAssistant, Content: "Vierte Antwort: Hier ist ein Beispielsatz."},
	}

	compacted := companion.CompactContext(msgs, 3000)

	// Invariant: System prompt (1) + Summary anchor (1) + Last 2 turns (4 messages) = 6 messages
	if len(compacted) != 6 {
		t.Fatalf("expected 6 messages after compaction, got %d", len(compacted))
	}

	if compacted[0].Content != "System Prompt with Study Context" {
		t.Errorf("system prompt was not preserved at index 0")
	}

	if !strings.Contains(compacted[1].Content, "前序上下文压缩锚点") {
		t.Errorf("expected summary system message at index 1, got %s", compacted[1].Content)
	}

	if compacted[len(compacted)-1].Content != "Vierte Antwort: Hier ist ein Beispielsatz." {
		t.Errorf("last message was not preserved")
	}
}

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

func TestEstimateTokens(t *testing.T) {
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "You are a helpful tutor."},
		{Role: openai.ChatMessageRoleUser, Content: "Erkläre mir bitte die Relativsätze im Deutschen mit Beispielen."},
	}
	tok := companion.EstimateTokens(msgs)
	if tok <= 0 {
		t.Fatalf("expected positive token count, got %d", tok)
	}
	if tok < 15 || tok > 50 {
		t.Errorf("unexpected token estimate for sample text: %d", tok)
	}
}

func TestCompactMessagesDynamicWith1MContextDeepSeek(t *testing.T) {
	longText := strings.Repeat("Deutsche Grammatik ist systematisch und faszinierend. ", 100) // ~5400 chars, ~1500 tokens
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System Prompt"},
		{Role: openai.ChatMessageRoleUser, Content: "Q1: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "A1: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Q2: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "A2: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Q3: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "A3: " + longText},
	}

	deepseekSpec := provider.ModelSpec{
		Name:            "deepseek-flash",
		ProviderID:      "deepseek",
		ContextWindow:   1048576, // 1M tokens
		CompactionRatio: 0.60,    // 600k tokens threshold
	}

	// 5000 tokens is << 600,000 tokens: MUST NOT compact!
	compacted := companion.CompactMessagesDynamic(msgs, deepseekSpec)
	if len(compacted) != len(msgs) {
		t.Fatalf("expected no compaction under 1M context (length %d), got %d", len(msgs), len(compacted))
	}
}

func TestCompactMessagesDynamicSmallContextTriggersAt60Percent(t *testing.T) {
	longText := strings.Repeat("Langer deutscher Text zur Syntaxanalyse. ", 50) // ~2000 chars, ~600 tokens
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System Prompt"},
		{Role: openai.ChatMessageRoleUser, Content: "Q1: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "A1: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Q2: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "A2: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Active Q3: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Active A3: " + longText},
	}

	smallSpec := provider.ModelSpec{
		Name:            "toy-model",
		ProviderID:      "toy",
		ContextWindow:   1000, // 1000 tokens, 60% = 600 tokens
		CompactionRatio: 0.60,
	}

	// Total tokens > 1500 tokens >> 600 tokens threshold: MUST trigger compaction!
	compacted := companion.CompactMessagesDynamic(msgs, smallSpec)
	if len(compacted) >= len(msgs) {
		t.Fatalf("expected compaction triggered for small model exceeding 60%% threshold, got length %d", len(compacted))
	}
	if !strings.Contains(compacted[1].Content, "前序上下文压缩锚点") {
		t.Errorf("expected anchor message at index 1, got %s", compacted[1].Content)
	}
}
