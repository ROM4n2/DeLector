package companion_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestCompanionServerHealth(t *testing.T) {
	agent := companion.NewCompanionAgent(nil, nil, "m")
	handler := companion.NewHandler(agent)

	req := httptest.NewRequest("GET", "/api/companion/health", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("health status = %d, want 200", rr.Code)
	}

	var res map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &res); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if res["status"] != "ok" || res["service"] != "delector-go-companion-agent" {
		t.Errorf("unexpected health response: %v", res)
	}
}

func TestCompanionServerChatSSE(t *testing.T) {
	// 启动 mock LLM
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		chunk := `{"id":"1","choices":[{"delta":{"content":"Hallo aus Go!"},"index":0}]}`
		w.Write([]byte("data: " + chunk + "\n\n"))
		flusher.Flush()
		w.Write([]byte("data: [DONE]\n\n"))
		flusher.Flush()
	}))
	defer ts.Close()

	cfg := openai.DefaultConfig("mock-key")
	cfg.BaseURL = ts.URL
	client := openai.NewClientWithConfig(cfg)
	agent := companion.NewCompanionAgent(client, &fakeToolRunner{}, "deepseek-chat")

	handler := companion.NewHandler(agent)

	chatReq := companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Sag hallo"}},
	}
	body, _ := json.Marshal(chatReq)

	req := httptest.NewRequest("POST", "/api/companion/chat", bytes.NewReader(body))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("chat status = %d, want 200", rr.Code)
	}

	contentType := rr.Header().Get("Content-Type")
	if !strings.HasPrefix(contentType, "text/event-stream") {
		t.Errorf("expected text/event-stream, got %s", contentType)
	}

	// 逐行消费 SSE 帧并验证格式
	scanner := bufio.NewScanner(rr.Body)
	var events []companion.Event
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data: ") {
			payload := strings.TrimPrefix(line, "data: ")
			var ev companion.Event
			if err := json.Unmarshal([]byte(payload), &ev); err == nil {
				events = append(events, ev)
			}
		}
	}

	hasDelta := false
	hasDone := false
	for _, ev := range events {
		if ev.Event == companion.EventDelta && ev.Text == "Hallo aus Go!" {
			hasDelta = true
		}
		if ev.Event == companion.EventDone && ev.Reason == "ok" {
			hasDone = true
		}
	}

	if !hasDelta {
		t.Error("missing delta event with 'Hallo aus Go!'")
	}
	if !hasDone {
		t.Error("missing done event")
	}
}
