package companion_test

import (
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/ROM4n2/DeLector/agent/internal/provider"
)

func TestBuildSystemPrompt(t *testing.T) {
	spec := provider.ModelSpec{
		Name:       "deepseek-flash",
		ProviderID: "deepseek",
	}

	// Case 1: Empty context
	promptEmpty := companion.BuildSystemPrompt("", spec)
	if !strings.Contains(promptEmpty, "你是 DeLector 德语研读系统的伴学导学伙伴「Eule」") {
		t.Errorf("expected base prompt, got %s", promptEmpty)
	}
	if strings.Contains(promptEmpty, "【当前学习视口上下文】") {
		t.Errorf("did not expect context block when activeContext is empty")
	}

	// Case 2: Formatted context
	ctx := companion.StudyContext{
		ArticleTitle: "Spiegel Magazin",
		SelectedText: "Das ist ein Beispielsatz.",
		CEFRLevel:    "B2",
	}
	activeCtx := companion.FormatStudyContext(ctx)
	promptWithCtx := companion.BuildSystemPrompt(activeCtx, spec)
	if !strings.Contains(promptWithCtx, "【当前学习视口上下文】") {
		t.Errorf("expected context block in prompt")
	}
	if !strings.Contains(promptWithCtx, "Spiegel Magazin") {
		t.Errorf("expected article title in prompt")
	}
	if !strings.Contains(promptWithCtx, "Das ist ein Beispielsatz.") {
		t.Errorf("expected selected text in prompt")
	}
	if !strings.Contains(promptWithCtx, "B2") {
		t.Errorf("expected CEFR level in prompt")
	}

	// Case 3: Raw unformatted context string
	promptRaw := companion.BuildSystemPrompt("- 文章: Goethe Test", spec)
	if !strings.Contains(promptRaw, "【当前学习视口上下文】\n- 文章: Goethe Test") {
		t.Errorf("expected header prepended to raw context, got %s", promptRaw)
	}
}

func TestBuildPromptNudge(t *testing.T) {
	nudge := companion.BuildPromptNudge()
	if nudge == "" {
		t.Fatal("expected non-empty prompt nudge")
	}
	if !strings.Contains(nudge, "已完成对当前句子的多维度语言学推演与分析") {
		t.Errorf("unexpected nudge text: %s", nudge)
	}
}
