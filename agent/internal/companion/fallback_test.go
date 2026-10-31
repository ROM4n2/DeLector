package companion_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestCompanionLoopFallbackToLocal(t *testing.T) {
	// 1. 模拟主模型服务崩溃（返回 HTTP 500 或连接断开）
	brokenPrimary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		fmt.Fprintf(w, `{"error":{"message":"Cloud API down"}}`)
	}))
	defer brokenPrimary.Close()

	// 2. 模拟本地 Ollama 备用服务正常响应
	fallbackServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		chunk := `{"id":"c1","choices":[{"delta":{"content":"这是来自本地热备模型的回答。"},"index":0}]}`
		fmt.Fprintf(w, "data: %s\n\n", chunk)
		flusher.Flush()
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer fallbackServer.Close()

	primaryCfg := openai.DefaultConfig("primary-key")
	primaryCfg.BaseURL = brokenPrimary.URL
	primaryClient := openai.NewClientWithConfig(primaryCfg)

	fallbackCfg := openai.DefaultConfig("fallback-key")
	fallbackCfg.BaseURL = fallbackServer.URL
	fallbackClient := openai.NewClientWithConfig(fallbackCfg)

	runner := &fakeToolRunner{}
	agent := companion.NewCompanionAgent(primaryClient, runner, "deepseek-chat").
		WithFallback(fallbackClient, "qwen3.5:4b")

	var events []companion.Event
	emit := func(ev companion.Event) error {
		events = append(events, ev)
		return nil
	}

	req := companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Hallo"}},
	}

	outcome, err := agent.RunLoop(context.Background(), req, emit)
	if err != nil {
		t.Fatalf("RunLoop failed despite fallback: %v", err)
	}

	if outcome.Status != "ok" {
		t.Errorf("expected status ok, got %s", outcome.Status)
	}
	if !strings.Contains(outcome.Text, "本地热备模型") {
		t.Errorf("expected text from fallback server, got %s", outcome.Text)
	}

	// 验证是否发送了降级提示
	hasFallbackNotice := false
	for _, ev := range events {
		if ev.Event == companion.EventThought && strings.Contains(ev.Text, "备用模型") {
			hasFallbackNotice = true
		}
	}
	if !hasFallbackNotice {
		t.Errorf("expected thought notice about fallback transition")
	}
}
