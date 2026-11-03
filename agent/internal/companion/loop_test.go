package companion_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

// fakeToolRunner 模拟 Python 微服务的本地工具执行
type fakeToolRunner struct {
	calls  []string
	err    error
	result map[string]any
}

func (f *fakeToolRunner) RunTool(_ context.Context, name string, _ map[string]any) (map[string]any, error) {
	f.calls = append(f.calls, name)
	if f.err != nil {
		return f.result, f.err
	}
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

func TestCompanionLoopCardProposalFromCardContext(t *testing.T) {
	turn := 0
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		turn++
		if turn == 1 {
			// 第一轮：基于卡盒上下文调用 propose_vocab_cards，参数必须原样进入提议
			callChunk := `{"id":"p1","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_p1","type":"function","function":{"name":"propose_vocab_cards","arguments":"{\"title\":\"扩展 die Eule 相关生词\",\"cards\":[{\"word\":\"die Nacht\",\"definition_zh\":\"夜晚\",\"sentence_context\":\"Die Eule jagt in der Nacht.\"}]}"}}]},"index":0}]}`
			fmt.Fprintf(w, "data: %s\n\n", callChunk)
			flusher.Flush()
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
		} else {
			contentChunk := `{"id":"p2","choices":[{"delta":{"content":"已生成待确认的生词卡提议。"},"index":0}]}`
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

	cardContext := "【当前卡盒词条】\n分段: due\n词: die Eule\n词元: Eule\n释义: 猫头鹰"
	req := companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "基于当前卡盒词条扩展生词"}},
		Context: companion.StudyContext{
			View:          "cards",
			ContextSource: "card-current",
			CardContext:   cardContext,
		},
	}

	outcome, err := agent.RunLoop(context.Background(), req, emit)
	if err != nil {
		t.Fatalf("RunLoop failed: %v", err)
	}

	if len(outcome.Proposals) != 1 {
		t.Fatalf("expected 1 proposal, got %d", len(outcome.Proposals))
	}
	prop := outcome.Proposals[0]
	if prop.Action != "create_vocab_cards" {
		t.Errorf("action = %s, want create_vocab_cards", prop.Action)
	}
	if prop.Title != "扩展 die Eule 相关生词" {
		t.Errorf("title = %s", prop.Title)
	}
	cards, ok := prop.Payload["cards"].([]any)
	if !ok || len(cards) != 1 {
		t.Fatalf("expected 1 proposed card, got %v", prop.Payload["cards"])
	}
	card, _ := cards[0].(map[string]any)
	if card["word"] != "die Nacht" || card["definition_zh"] != "夜晚" {
		t.Errorf("proposal card payload lost fields: %v", card)
	}

	hasProposal := false
	for _, ev := range events {
		if ev.Event == companion.EventProposal && ev.ID == prop.ID {
			hasProposal = true
		}
	}
	if !hasProposal {
		t.Error("missing proposal event")
	}

	// propose_vocab_cards 是待确认提议，绝不能直接调用本地写入工具。
	if len(runner.calls) != 0 {
		t.Errorf("propose_vocab_cards must not execute a write tool, got %v", runner.calls)
	}
}

func TestCompanionLoopMultiActionProposals(t *testing.T) {
	tests := []struct {
		name       string
		toolName   string
		arguments  string
		wantAction string
		payloadKey string
	}{
		{
			name:       "writing revision",
			toolName:   "propose_writing_revision",
			arguments:  `{"title":"修订选中句子","original_text":"Der Hund bellt.","revised_text":"Der kleine Hund bellt."}`,
			wantAction: "apply_writing_revision",
			payloadKey: "revised_text",
		},
		{
			name:       "weekly goal",
			toolName:   "propose_weekly_goal",
			arguments:  `{"title":"本周学习目标","goal":"本周复习 20 张卡片"}`,
			wantAction: "set_weekly_goal",
			payloadKey: "goal",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			runner := &fakeToolRunner{}
			result := runScriptedLoop(t, companion.Request{
				Messages: []companion.Message{{Role: "user", Content: tt.name}},
			}, runner, []scriptedLoopTurn{
				{toolCalls: []openai.ToolCall{equivalenceToolCall(0, "call_multi_action", tt.toolName, tt.arguments)}},
				{content: "已生成待确认提议。"},
			})
			if result.err != nil {
				t.Fatalf("RunLoop failed: %v", result.err)
			}
			if len(result.outcome.Proposals) != 1 {
				t.Fatalf("expected 1 proposal, got %d", len(result.outcome.Proposals))
			}
			prop := result.outcome.Proposals[0]
			if prop.ID == "" || prop.Action != tt.wantAction {
				t.Errorf("proposal id/action = %q/%q, want non-empty/%q", prop.ID, prop.Action, tt.wantAction)
			}
			if _, ok := prop.Payload[tt.payloadKey]; !ok {
				t.Errorf("proposal payload missing %q: %v", tt.payloadKey, prop.Payload)
			}
			if len(runner.calls) != 0 {
				t.Errorf("proposal tool must not execute a write tool, got %v", runner.calls)
			}
			foundEvent := false
			for _, ev := range result.events {
				if ev.Event == companion.EventProposal && ev.ID == prop.ID && ev.Action == tt.wantAction {
					foundEvent = true
				}
			}
			if !foundEvent {
				t.Errorf("missing matching proposal event for %s", tt.wantAction)
			}
		})
	}
}

func TestCompanionLoopToolErrorSelfHealing(t *testing.T) {
	turn := 0
	var receivedToolMsg string

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		turn++
		if turn == 1 {
			// 第一轮：模型调用 writing_check 工具
			callChunk := `{"id":"c1","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_err_1","type":"function","function":{"name":"writing_check","arguments":"{\"text\":\"Ich habe hunger\"}"}}]},"index":0}]}`
			fmt.Fprintf(w, "data: %s\n\n", callChunk)
			flusher.Flush()
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
		} else {
			// 第二轮：模型收到 Errors-as-Messages 工具错误回传后自愈回答
			contentChunk := `{"id":"c2","choices":[{"delta":{"content":"微服务暂时不可用，但我发现 Hunger 必须大写：Ich habe Hunger。"},"index":0}]}`
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

	// 工具模拟返回网络重置异常
	runner := &fakeToolRunner{err: errors.New("connection reset by peer")}
	agent := companion.NewCompanionAgent(client, runner, "deepseek-chat")

	var events []companion.Event
	emit := func(ev companion.Event) error {
		events = append(events, ev)
		return nil
	}

	req := companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "检查这句德语"}},
	}

	outcome, err := agent.RunLoop(context.Background(), req, emit)
	if err != nil {
		t.Fatalf("RunLoop should self-heal and not fail: %v", err)
	}

	if outcome.Status != "ok" {
		t.Errorf("status = %s, want ok", outcome.Status)
	}
	if !strings.Contains(outcome.Text, "Ich habe Hunger") {
		t.Errorf("expected self-healed text, got %s", outcome.Text)
	}

	// 验证 EventToolEnd 是否携带错误结果且未中断链路
	hasErrorResult := false
	for _, ev := range events {
		if ev.Event == companion.EventToolEnd {
			if ev.Result != nil && ev.Result["error_code"] == "TOOL_EXECUTION_FAILED" {
				hasErrorResult = true
			}
		}
	}
	if !hasErrorResult {
		t.Errorf("expected EventToolEnd to contain structured error_code TOOL_EXECUTION_FAILED, but it didn't")
	}
	_ = receivedToolMsg
}

type scriptedLoopTurn struct {
	content   string
	toolCalls []openai.ToolCall
}

type scriptedLoopResult struct {
	outcome  *companion.Outcome
	err      error
	events   []companion.Event
	requests []openai.ChatCompletionRequest
	spec     provider.ModelSpec
}

func runScriptedLoop(t *testing.T, req companion.Request, runner companion.ToolRunner, turns []scriptedLoopTurn) scriptedLoopResult {
	t.Helper()
	if len(turns) == 0 {
		t.Fatal("scripted loop requires at least one turn")
	}

	var requests []openai.ChatCompletionRequest
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var chatReq openai.ChatCompletionRequest
		if err := json.NewDecoder(r.Body).Decode(&chatReq); err != nil {
			t.Errorf("decode chat request: %v", err)
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		requests = append(requests, chatReq)
		turnIndex := len(requests) - 1
		if turnIndex >= len(turns) {
			turnIndex = len(turns) - 1
		}
		turn := turns[turnIndex]

		delta := make(map[string]any)
		if turn.content != "" {
			delta["content"] = turn.content
		}
		if turn.toolCalls != nil {
			delta["tool_calls"] = turn.toolCalls
		}
		chunk, err := json.Marshal(map[string]any{
			"id": fmt.Sprintf("turn-%d", len(requests)),
			"choices": []any{map[string]any{
				"delta": delta,
				"index": 0,
			}},
		})
		if err != nil {
			t.Errorf("marshal SSE chunk: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, "data: %s\n\n", chunk)
		fmt.Fprint(w, "data: [DONE]\n\n")
	}))
	defer ts.Close()

	cfg := openai.DefaultConfig("mock-key")
	cfg.BaseURL = ts.URL
	agent := companion.NewCompanionAgent(openai.NewClientWithConfig(cfg), runner, "deepseek-chat")
	activeModel := req.Model
	if activeModel == "" {
		activeModel = "deepseek-chat"
	}

	var events []companion.Event
	outcome, err := agent.RunLoop(context.Background(), req, func(ev companion.Event) error {
		events = append(events, ev)
		return nil
	})
	return scriptedLoopResult{
		outcome:  outcome,
		err:      err,
		events:   events,
		requests: requests,
		spec:     agent.Registry().ResolveModel(activeModel, req.BaseURL),
	}
}

func equivalenceToolCall(index int, id, name, arguments string) openai.ToolCall {
	return openai.ToolCall{
		Index: &index,
		ID:    id,
		Type:  openai.ToolTypeFunction,
		Function: openai.FunctionCall{
			Name:      name,
			Arguments: arguments,
		},
	}
}

const equivalencePromptNudgeGolden = "已完成对当前句子的多维度语言学推演与分析。请参阅上方提取的语法拓扑信息，如需针对特定成分深入探讨，可随时追问。"

func TestRunLoopEquivalenceSystemPrompt(t *testing.T) {
	tests := []struct {
		name         string
		ctx          companion.StudyContext
		contextBlock string
	}{
		{
			name: "card context prefix",
			ctx: companion.StudyContext{
				ArticleTitle:  "Spiegel Magazin",
				CEFRLevel:     "B2",
				SelectedText:  "Die Eule jagt.",
				View:          "cards",
				ContextSource: "card-current",
				DraftText:     "Ich habe Hunger.",
				CardContext:   "【当前卡盒词条】\n词: die Eule",
			},
			contextBlock: `【当前学习视口上下文】
- 文章: Spiegel Magazin
- 目标级别: B2
- 当前聚焦句子: Die Eule jagt.
- 当前页面: cards
- 上下文来源: card-current
- 当前写作草稿: Ich habe Hunger.
- 【当前卡盒词条】
词: die Eule`,
		},
		{
			name:         "CEFR only",
			ctx:          companion.StudyContext{CEFRLevel: "C1"},
			contextBlock: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := runScriptedLoop(t, companion.Request{
				Messages: []companion.Message{{Role: "user", Content: "Hallo"}},
				Context:  tt.ctx,
			}, &fakeToolRunner{}, []scriptedLoopTurn{{content: "Fertig."}})
			if result.err != nil {
				t.Fatalf("RunLoop failed: %v", result.err)
			}
			if len(result.requests) != 1 || len(result.requests[0].Messages) == 0 {
				t.Fatalf("captured requests = %+v", result.requests)
			}

			got := result.requests[0].Messages[0].Content
			helperWant := companion.BuildSystemPrompt(companion.FormatStudyContext(tt.ctx), result.spec)
			if got != helperWant {
				t.Errorf("system prompt mismatch\n--- RunLoop actual ---\n%s\n--- helper expected ---\n%s", got, helperWant)
			}
			goldenWant := companion.CompanionSystemPrompt
			if tt.contextBlock != "" {
				goldenWant += "\n\n" + tt.contextBlock
			}
			if got != goldenWant {
				t.Errorf("system prompt HEAD golden mismatch\n--- RunLoop actual ---\n%s\n--- HEAD golden ---\n%s", got, goldenWant)
			}
		})
	}
}

func TestRunLoopEquivalenceToolStartAggregation(t *testing.T) {
	tests := []struct {
		name   string
		calls  []openai.ToolCall
		golden []companion.Event
	}{
		{
			name: "normal",
			calls: []openai.ToolCall{
				equivalenceToolCall(0, "call_a", "analyze", `{"text":"Der Hund bellt."}`),
			},
			golden: []companion.Event{{
				Event:   companion.EventToolStart,
				Tool:    "analyze",
				Payload: map[string]any{"text": "Der Hund bellt."},
			}},
		},
		{
			name: "out of order",
			calls: []openai.ToolCall{
				equivalenceToolCall(1, "call_b", "vocab_stats", `{"text":"Der Hund bellt."}`),
				equivalenceToolCall(0, "call_a", "analyze", `{"text":"Der Hund bellt."}`),
			},
			golden: []companion.Event{
				{
					Event:   companion.EventToolStart,
					Tool:    "analyze",
					Payload: map[string]any{"text": "Der Hund bellt."},
				},
				{
					Event:   companion.EventToolStart,
					Tool:    "vocab_stats",
					Payload: map[string]any{"text": "Der Hund bellt."},
				},
			},
		},
		{
			name: "negative index",
			calls: []openai.ToolCall{
				equivalenceToolCall(-1, "call_negative", "analyze", `{"text":"Der Hund bellt."}`),
			},
			golden: []companion.Event{},
		},
		{
			name: "sparse index",
			calls: []openai.ToolCall{
				equivalenceToolCall(2, "call_sparse", "analyze", `{"text":"Der Hund bellt."}`),
			},
			golden: []companion.Event{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := runScriptedLoop(t, companion.Request{
				Messages: []companion.Message{{Role: "user", Content: "Analysieren"}},
			}, &fakeToolRunner{}, []scriptedLoopTurn{
				{toolCalls: tt.calls},
				{content: "Fertig."},
			})
			if result.err != nil {
				t.Fatalf("RunLoop failed: %v", result.err)
			}
			if len(result.requests) != 2 {
				t.Fatalf("request count = %d, want 2 (second request must be reached)", len(result.requests))
			}
			if result.outcome.Reason != "ok" {
				t.Fatalf("outcome reason = %q, want ok", result.outcome.Reason)
			}

			expectedCalls := make(map[int]*openai.ToolCall)
			for _, call := range tt.calls {
				expectedCalls = companion.AggregateToolCalls(expectedCalls, call)
			}
			expectedList := companion.FilterValidToolCalls(expectedCalls)
			helperWant := make([]companion.Event, 0, len(expectedList))
			for _, call := range expectedList {
				var payload map[string]any
				if err := json.Unmarshal([]byte(call.Function.Arguments), &payload); err != nil {
					t.Fatalf("decode expected tool payload: %v", err)
				}
				helperWant = append(helperWant, companion.Event{
					Event:   companion.EventToolStart,
					Tool:    call.Function.Name,
					Payload: payload,
				})
			}

			got := make([]companion.Event, 0)
			for _, ev := range result.events {
				if ev.Event == companion.EventToolStart {
					got = append(got, ev)
				}
			}
			if !reflect.DeepEqual(got, helperWant) {
				t.Errorf("tool_start mismatch\nRunLoop actual: %#v\nhelper expected: %#v", got, helperWant)
			}
			if !reflect.DeepEqual(got, tt.golden) {
				t.Errorf("tool_start HEAD golden mismatch\nRunLoop actual: %#v\nHEAD golden: %#v", got, tt.golden)
			}
		})
	}
}

func TestRunLoopEquivalenceEmptyCallsListUntilTurnLimit(t *testing.T) {
	turns := make([]scriptedLoopTurn, companion.DefaultMaxTurns)
	for i := range turns {
		turns[i].toolCalls = []openai.ToolCall{
			equivalenceToolCall(-1, fmt.Sprintf("call_negative_%d", i), "analyze", `{"text":"Der Hund bellt."}`),
		}
	}
	result := runScriptedLoop(t, companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Analysieren"}},
	}, &fakeToolRunner{}, turns)
	if result.err != nil {
		t.Fatalf("RunLoop failed: %v", result.err)
	}
	if len(result.requests) != companion.DefaultMaxTurns {
		t.Errorf("request count = %d, want %d", len(result.requests), companion.DefaultMaxTurns)
	}
	if result.outcome.Reason != "turn_limit" {
		t.Errorf("outcome reason = %q, want turn_limit", result.outcome.Reason)
	}
	if result.outcome.Text != equivalencePromptNudgeGolden {
		t.Errorf("turn-limit outcome text = %q, HEAD golden = %q", result.outcome.Text, equivalencePromptNudgeGolden)
	}
	var fallbackDeltas []string
	for _, ev := range result.events {
		if ev.Event == companion.EventDelta {
			fallbackDeltas = append(fallbackDeltas, ev.Text)
		}
	}
	if !reflect.DeepEqual(fallbackDeltas, []string{equivalencePromptNudgeGolden}) {
		t.Errorf("turn-limit delta events = %#v, HEAD golden [%q]", fallbackDeltas, equivalencePromptNudgeGolden)
	}
}

func TestRunLoopEquivalencePromptNudgeAtTurnLimit(t *testing.T) {
	turns := make([]scriptedLoopTurn, companion.DefaultMaxTurns)
	for i := range turns {
		turns[i].toolCalls = []openai.ToolCall{
			equivalenceToolCall(0, fmt.Sprintf("call_%d", i), "analyze", `{"text":"Der Hund bellt."}`),
		}
	}
	result := runScriptedLoop(t, companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Analysieren"}},
	}, &fakeToolRunner{}, turns)
	if result.err != nil {
		t.Fatalf("RunLoop failed: %v", result.err)
	}
	if result.outcome.Reason != "turn_limit" {
		t.Fatalf("outcome reason = %q, want turn_limit", result.outcome.Reason)
	}

	helperWant := companion.BuildPromptNudge()
	if result.outcome.Text != helperWant {
		t.Errorf("turn-limit outcome text = %q, helper nudge = %q", result.outcome.Text, helperWant)
	}
	if result.outcome.Text != equivalencePromptNudgeGolden {
		t.Errorf("turn-limit outcome text = %q, HEAD golden = %q", result.outcome.Text, equivalencePromptNudgeGolden)
	}
	var fallbackDeltas []string
	for _, ev := range result.events {
		if ev.Event == companion.EventDelta {
			fallbackDeltas = append(fallbackDeltas, ev.Text)
		}
	}
	if !reflect.DeepEqual(fallbackDeltas, []string{helperWant}) {
		t.Errorf("turn-limit delta events = %#v, helper nudge [%q]", fallbackDeltas, helperWant)
	}
	if !reflect.DeepEqual(fallbackDeltas, []string{equivalencePromptNudgeGolden}) {
		t.Errorf("turn-limit delta events = %#v, HEAD golden [%q]", fallbackDeltas, equivalencePromptNudgeGolden)
	}
}

func TestRunLoopEquivalenceInvalidToolArguments(t *testing.T) {
	const rawArguments = `{"text":`
	const goldenJSON = `{"error_code":"INVALID_TOOL_ARGUMENTS","hint":"请确保为该工具传入合法 JSON 格式的对象参数。","message":"工具参数 JSON 解析失败: unexpected end of JSON input","raw":"{\"text\":","status":"error","tool":"analyze"}`
	call := equivalenceToolCall(0, "call_bad_args", "analyze", rawArguments)
	result := runScriptedLoop(t, companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Analysieren"}},
	}, &fakeToolRunner{}, []scriptedLoopTurn{
		{toolCalls: []openai.ToolCall{call}},
		{content: "Ich antworte ohne gültige Tool-Daten."},
	})
	if result.err != nil {
		t.Fatalf("RunLoop failed: %v", result.err)
	}
	if len(result.requests) != 2 {
		t.Fatalf("request count = %d, want 2", len(result.requests))
	}

	var payload map[string]any
	parseErr := json.Unmarshal([]byte(rawArguments), &payload)
	if parseErr == nil {
		t.Fatal("test arguments unexpectedly valid")
	}
	helperJSON := companion.FormatToolArgErrorMessage(call.Function.Name, rawArguments, parseErr)
	messages := result.requests[1].Messages
	gotMessage := messages[len(messages)-1]
	if gotMessage.Role != openai.ChatMessageRoleTool || gotMessage.ToolCallID != call.ID || gotMessage.Content != goldenJSON {
		t.Errorf("invalid-argument tool message HEAD golden mismatch = %#v\nwant role=%q tool_call_id=%q content=%s", gotMessage, openai.ChatMessageRoleTool, call.ID, goldenJSON)
	}
	if gotMessage.Content != helperJSON {
		t.Errorf("invalid-argument tool message helper mismatch = %#v\nhelper content=%s", gotMessage, helperJSON)
	}

	goldenResult := map[string]any{
		"status":     "error",
		"error_code": "INVALID_TOOL_ARGUMENTS",
		"tool":       "analyze",
		"message":    "工具参数 JSON 解析失败: unexpected end of JSON input",
		"raw":        rawArguments,
		"hint":       "请确保为该工具传入合法 JSON 格式的对象参数。",
	}
	goldenEvent := companion.Event{Event: companion.EventToolEnd, Tool: "analyze", Result: goldenResult}
	var helperResult map[string]any
	if err := json.Unmarshal([]byte(helperJSON), &helperResult); err != nil {
		t.Fatalf("decode helper error JSON: %v", err)
	}
	helperEvent := companion.Event{Event: companion.EventToolEnd, Tool: call.Function.Name, Result: helperResult}
	var gotEvents []companion.Event
	for _, ev := range result.events {
		if ev.Event == companion.EventToolEnd {
			gotEvents = append(gotEvents, ev)
		}
	}
	if !reflect.DeepEqual(gotEvents, []companion.Event{helperEvent}) {
		t.Errorf("invalid-argument tool_end = %#v\nhelper expected: %#v", gotEvents, []companion.Event{helperEvent})
	}
	if !reflect.DeepEqual(gotEvents, []companion.Event{goldenEvent}) {
		t.Errorf("invalid-argument tool_end HEAD golden mismatch = %#v\nHEAD golden: %#v", gotEvents, []companion.Event{goldenEvent})
	}
}

func TestRunLoopEquivalenceToolExecutionFailure(t *testing.T) {
	const goldenJSON = `{"error_code":"TOOL_EXECUTION_FAILED","hint":"工具执行暂时失败。请向学习者说明情况并给出基于已有上下文的专业解答，或调整参数重试。","message":"connection reset by peer","status":"error","tool":"analyze"}`
	toolErr := errors.New("connection reset by peer")
	call := equivalenceToolCall(0, "call_failed", "analyze", `{"text":"Der Hund bellt."}`)
	result := runScriptedLoop(t, companion.Request{
		Messages: []companion.Message{{Role: "user", Content: "Analysieren"}},
	}, &fakeToolRunner{
		err:    toolErr,
		result: map[string]any{"stale": "must not leak into the structured error"},
	}, []scriptedLoopTurn{
		{toolCalls: []openai.ToolCall{call}},
		{content: "Ich antworte trotz des Tool-Fehlers."},
	})
	if result.err != nil {
		t.Fatalf("RunLoop failed: %v", result.err)
	}
	if len(result.requests) != 2 {
		t.Fatalf("request count = %d, want 2", len(result.requests))
	}

	helperJSON := companion.FormatToolErrorMessage(call.Function.Name, toolErr)
	messages := result.requests[1].Messages
	gotMessage := messages[len(messages)-1]
	if gotMessage.Role != openai.ChatMessageRoleTool || gotMessage.ToolCallID != call.ID || gotMessage.Content != goldenJSON {
		t.Errorf("execution-error tool message HEAD golden mismatch = %#v\nwant role=%q tool_call_id=%q content=%s", gotMessage, openai.ChatMessageRoleTool, call.ID, goldenJSON)
	}
	if gotMessage.Content != helperJSON {
		t.Errorf("execution-error tool message helper mismatch = %#v\nhelper content=%s", gotMessage, helperJSON)
	}

	goldenResult := map[string]any{
		"status":     "error",
		"error_code": "TOOL_EXECUTION_FAILED",
		"tool":       "analyze",
		"message":    "connection reset by peer",
		"hint":       "工具执行暂时失败。请向学习者说明情况并给出基于已有上下文的专业解答，或调整参数重试。",
	}
	goldenEvent := companion.Event{
		Event:   companion.EventToolEnd,
		Tool:    "analyze",
		Result:  goldenResult,
		Summary: "执行受阻: connection reset by peer",
	}
	var helperResult map[string]any
	if err := json.Unmarshal([]byte(helperJSON), &helperResult); err != nil {
		t.Fatalf("decode helper error JSON: %v", err)
	}
	helperEvent := companion.Event{
		Event:   companion.EventToolEnd,
		Tool:    call.Function.Name,
		Result:  helperResult,
		Summary: fmt.Sprintf("执行受阻: %v", toolErr),
	}
	var gotEvents []companion.Event
	for _, ev := range result.events {
		if ev.Event == companion.EventToolEnd {
			gotEvents = append(gotEvents, ev)
		}
	}
	if !reflect.DeepEqual(gotEvents, []companion.Event{helperEvent}) {
		t.Errorf("execution-error tool_end = %#v\nhelper expected: %#v", gotEvents, []companion.Event{helperEvent})
	}
	if !reflect.DeepEqual(gotEvents, []companion.Event{goldenEvent}) {
		t.Errorf("execution-error tool_end HEAD golden mismatch = %#v\nHEAD golden: %#v", gotEvents, []companion.Event{goldenEvent})
	}
}
