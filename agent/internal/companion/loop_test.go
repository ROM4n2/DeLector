package companion_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

// fakeToolRunner 模拟 Python 微服务的本地工具执行
type fakeToolRunner struct {
	calls []string
}

func (f *fakeToolRunner) RunTool(_ context.Context, name string, _ map[string]any) (map[string]any, error) {
	f.calls = append(f.calls, name)
	if name == "analyze" {
		return map[string]any{
			"status":  "ok",
			"clauses": []any{"Vorfeld: Gestern", "LinkeKlammer: kam", "Mittelfeld: der Zug"},
		}, nil
	}
	return map[string]any{"status": "ok"}, nil
}

func TestCompanionLoopDirectResponse(t *testing.T) {
	// 启动本地 mock LLM SSE 服务（100% 隔离，绝不出网）
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)

		// 模拟 DeepSeek-R1 思考流与纯 Markdown 正文流
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Fatal("expected flusher")
		}

		chunk1 := `{"id":"1","choices":[{"delta":{"reasoning_content":"分析语序"},"index":0}]}`
		fmt.Fprintf(w, "data: %s\n\n", chunk1)
		flusher.Flush()

		chunk2 := `{"id":"2","choices":[{"delta":{"content":"这是一个"},"index":0}]}`
		fmt.Fprintf(w, "data: %s\n\n", chunk2)
		flusher.Flush()

		chunk3 := `{"id":"3","choices":[{"delta":{"content":"主从复合句。"},"index":0}]}`
		fmt.Fprintf(w, "data: %s\n\n", chunk3)
		flusher.Flush()

		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer ts.Close()

	cfg := openai.DefaultConfig("mock-key")
	cfg.BaseURL = ts.URL
	client := openai.NewClientWithConfig(cfg)

	runner := &fakeToolRunner{}
	agent := companion.NewCompanionAgent(client, runner, "deepseek-chat")

	var events []companion.Event
	emit := func(ev companion.Event) error {
		events = append(events, ev)
		return nil
	}

	req := companion.Request{
		Messages: []companion.Message{
			{Role: "user", Content: "帮我分析这句话"},
		},
		Context: companion.StudyContext{
			ArticleTitle: "Der Spiegel Test",
			SelectedText: "Gestern kam der Zug an.",
		},
	}

	outcome, err := agent.RunLoop(context.Background(), req, emit)
	if err != nil {
		t.Fatalf("RunLoop failed: %v", err)
	}

	if outcome.Status != "ok" {
		t.Errorf("expected outcome status ok, got %s", outcome.Status)
	}
	if outcome.Text != "这是一个主从复合句。" {
		t.Errorf("unexpected outcome text: %s", outcome.Text)
	}

	hasThought := false
	hasDelta := false
	hasDone := false
	for _, ev := range events {
		if ev.Event == companion.EventThought && ev.Text == "分析语序" {
			hasThought = true
		}
		if ev.Event == companion.EventDelta {
			hasDelta = true
		}
		if ev.Event == companion.EventDone {
			hasDone = true
		}
	}
	if !hasThought {
		t.Error("missing thought event")
	}
	if !hasDelta {
		t.Error("missing delta event")
	}
	if !hasDone {
		t.Error("missing done event")
	}
}

func TestCompanionLoopToolCallingAndProposal(t *testing.T) {
	turn := 0
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		turn++
		if turn == 1 {
			// 第一轮：模型决定调用 analyze 工具
			callChunk := `{"id":"c1","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"analyze","arguments":"{\"text\":\"Der Hund bellt.\"}"}}]},"index":0}]}`
			fmt.Fprintf(w, "data: %s\n\n", callChunk)
			flusher.Flush()
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
		} else {
			// 第二轮：收到工具反馈后，模型流出最终解答
			contentChunk := `{"id":"c2","choices":[{"delta":{"content":"分析完毕，主语是 Der Hund。"},"index":0}]}`
			fmt.Fprintf(w, "data: %s\n\n", contentChunk)
			flusher.Flush()
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
		}
	}))
	defer ts.Close()

	cfg := openai.DefaultConfig("mock-key")
	cfg.BaseURL = ts.URL
	client := openai.NewClientWithConfig(cfg)

	runner := &fakeToolRunner{}
	agent := companion.NewCompanionAgent(client, runner, "deepseek-chat")

	var events []companion.Event
	emit := func(ev companion.Event) error {
		events = append(events, ev)
		return nil
	}

	req := companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "分析这个简单句"}},
	}

	outcome, err := agent.RunLoop(context.Background(), req, emit)
	if err != nil {
		t.Fatalf("RunLoop failed: %v", err)
	}

	if outcome.Status != "ok" {
		t.Errorf("status = %s, want ok", outcome.Status)
	}
	if len(runner.calls) != 1 || runner.calls[0] != "analyze" {
		t.Errorf("expected analyze tool call, got %v", runner.calls)
	}
	if outcome.Text != "分析完毕，主语是 Der Hund。" {
		t.Errorf("unexpected outcome text: %s", outcome.Text)
	}

	hasToolStart := false
	hasToolEnd := false
	for _, ev := range events {
		if ev.Event == companion.EventToolStart && ev.Tool == "analyze" {
			hasToolStart = true
		}
		if ev.Event == companion.EventToolEnd && ev.Tool == "analyze" {
			hasToolEnd = true
		}
	}
	if !hasToolStart || !hasToolEnd {
		t.Error("missing tool_start or tool_end event")
	}
}
