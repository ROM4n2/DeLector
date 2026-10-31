package companion_test

import (
	"encoding/json"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestCompanionToolsSchemas(t *testing.T) {
	tools := companion.CompanionTools()
	if len(tools) != 4 {
		t.Fatalf("expected 4 companion tools, got %d", len(tools))
	}

	expectedNames := map[string]bool{
		"analyze":             false,
		"writing_check":       false,
		"vocab_stats":         false,
		"propose_vocab_cards": false,
	}

	for _, tool := range tools {
		if tool.Type != openai.ToolTypeFunction {
			t.Errorf("tool %s type = %s, want function", tool.Function.Name, tool.Type)
		}
		name := tool.Function.Name
		if _, ok := expectedNames[name]; !ok {
			t.Errorf("unexpected tool name: %s", name)
		}
		expectedNames[name] = true

		if tool.Function.Description == "" {
			t.Errorf("tool %s has empty description", name)
		}

		paramsBytes, err := json.Marshal(tool.Function.Parameters)
		if err != nil {
			t.Fatalf("failed to marshal parameters for %s: %v", name, err)
		}
		var paramMap map[string]any
		if err := json.Unmarshal(paramsBytes, &paramMap); err != nil {
			t.Fatalf("failed to unmarshal parameters for %s: %v", name, err)
		}
		if paramMap["type"] != "object" {
			t.Errorf("tool %s parameters type = %v, want object", name, paramMap["type"])
		}
	}

	for name, found := range expectedNames {
		if !found {
			t.Errorf("expected tool %s was not found in CompanionTools", name)
		}
	}
}

func TestEventSerialization(t *testing.T) {
	ev := companion.Event{
		Event: companion.EventDelta,
		Text:  "Guten Tag!",
	}
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if m["event"] != "delta" || m["text"] != "Guten Tag!" {
		t.Errorf("unexpected json: %s", string(b))
	}
}
