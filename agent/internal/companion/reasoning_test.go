package companion_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/sashabaranov/go-openai"
)

func TestMapReasoningEffort(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{"none", "none"},
		{"low", "low"},
		{"medium", "high"},
		{"high", "max"},
		{" HIGH ", "max"},
		{"bogus", "high"},
		{"", "high"},
	}
	for _, tc := range cases {
		if got := companion.MapReasoningEffort(tc.in); got != tc.want {
			t.Errorf("MapReasoningEffort(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// TestRunLoopSendsEffectiveReasoningEffort 钉住「界面档位 → 真实请求体」链路：
// 请求显式值优先；缺省用 Agent 挂载的设置页值；发送前统一映射为上游合法取值。
func TestRunLoopSendsEffectiveReasoningEffort(t *testing.T) {
	cases := []struct {
		name       string
		agentEff   string
		requestEff string
		want       string
	}{
		{name: "request none", agentEff: "high", requestEff: "none", want: "none"},
		{name: "request low", agentEff: "high", requestEff: "low", want: "low"},
		{name: "request medium", agentEff: "high", requestEff: "medium", want: "high"},
		{name: "request high", agentEff: "low", requestEff: "high", want: "max"},
		{name: "agent default medium", agentEff: "medium", requestEff: "", want: "high"},
		{name: "agent default high", agentEff: "high", requestEff: "", want: "max"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var gotEffort string
			ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body struct {
					ReasoningEffort string `json:"reasoning_effort"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Errorf("decode request body: %v", err)
				}
				gotEffort = body.ReasoningEffort

				w.Header().Set("Content-Type", "text/event-stream")
				w.WriteHeader(http.StatusOK)
				if f, ok := w.(http.Flusher); ok {
					fmt.Fprint(w, "data: {\"id\":\"1\",\"choices\":[{\"delta\":{\"content\":\"ok\"},\"index\":0}]}\n\n")
					f.Flush()
					fmt.Fprint(w, "data: [DONE]\n\n")
					f.Flush()
				}
			}))
			defer ts.Close()

			cfg := openai.DefaultConfig("mock-key")
			cfg.BaseURL = ts.URL
			client := openai.NewClientWithConfig(cfg)

			agent := companion.NewCompanionAgent(client, &fakeToolRunner{}, "deepseek-flash")
			agent.WithReasoningEffort(tc.agentEff)

			req := companion.Request{
				Messages:        []companion.Message{{Role: "user", Content: "Hi"}},
				ReasoningEffort: tc.requestEff,
			}
			if _, err := agent.RunLoop(context.Background(), req, func(companion.Event) error { return nil }); err != nil {
				t.Fatalf("RunLoop failed: %v", err)
			}

			if gotEffort != tc.want {
				t.Errorf("upstream reasoning_effort = %q, want %q", gotEffort, tc.want)
			}
		})
	}
}
