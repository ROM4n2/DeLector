package companion_test

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

// TestTurnPipeline_ChainingAndOrder 验证中间件洋葱模型的调用链顺序（Pre 正序，Post 逆序）。
func TestTurnPipeline_ChainingAndOrder(t *testing.T) {
	pipeline := companion.NewTurnPipeline()

	var order []string
	mw1 := func(tc *companion.TurnContext, next func() error) error {
		order = append(order, "mw1_pre")
		err := next()
		order = append(order, "mw1_post")
		return err
	}
	mw2 := func(tc *companion.TurnContext, next func() error) error {
		order = append(order, "mw2_pre")
		err := next()
		order = append(order, "mw2_post")
		return err
	}
	mw3 := func(tc *companion.TurnContext, next func() error) error {
		order = append(order, "mw3_pre")
		err := next()
		order = append(order, "mw3_post")
		return err
	}

	pipeline.Use(mw1)
	pipeline.Use(mw2)
	pipeline.Use(mw3)

	tc := &companion.TurnContext{Turn: 1}
	coreExecuted := false
	err := pipeline.Execute(tc, func() error {
		order = append(order, "core")
		coreExecuted = true
		return nil
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !coreExecuted {
		t.Fatal("expected coreFn to be executed")
	}

	expectedOrder := []string{"mw1_pre", "mw2_pre", "mw3_pre", "core", "mw3_post", "mw2_post", "mw1_post"}
	if len(order) != len(expectedOrder) {
		t.Fatalf("expected order length %d, got %d: %v", len(expectedOrder), len(order), order)
	}
	for i, v := range expectedOrder {
		if order[i] != v {
			t.Errorf("order[%d] = %s, want %s", i, order[i], v)
		}
	}
}

// TestTurnPipeline_ErrorTermination 验证中间件阻断时熔断短路，后续中间件与 coreFn 不被执行。
func TestTurnPipeline_ErrorTermination(t *testing.T) {
	pipeline := companion.NewTurnPipeline()

	mw1Executed := false
	mw2Executed := false
	coreExecuted := false

	sentinelErr := errors.New("guard check failed")

	pipeline.Use(func(tc *companion.TurnContext, next func() error) error {
		mw1Executed = true
		// 阻断：直接返回错误且不调用 next()
		return sentinelErr
	})

	pipeline.Use(func(tc *companion.TurnContext, next func() error) error {
		mw2Executed = true
		return next()
	})

	tc := &companion.TurnContext{Turn: 1}
	err := pipeline.Execute(tc, func() error {
		coreExecuted = true
		return nil
	})

	if !errors.Is(err, sentinelErr) {
		t.Fatalf("expected sentinelErr, got %v", err)
	}
	if !mw1Executed {
		t.Error("expected mw1 to execute")
	}
	if mw2Executed {
		t.Error("mw2 should NOT execute after mw1 error termination")
	}
	if coreExecuted {
		t.Error("coreFn should NOT execute after mw1 error termination")
	}
}

// TestTurnPipeline_CoreErrorPropagation 验证 coreFn 的错误原样沿调用链向外传递。
func TestTurnPipeline_CoreErrorPropagation(t *testing.T) {
	pipeline := companion.NewTurnPipeline()

	postExecuted := false
	sentinelErr := errors.New("upstream llm error")

	pipeline.Use(func(tc *companion.TurnContext, next func() error) error {
		err := next()
		postExecuted = true
		return err
	})

	tc := &companion.TurnContext{Turn: 1}
	err := pipeline.Execute(tc, func() error {
		return sentinelErr
	})

	if !errors.Is(err, sentinelErr) {
		t.Fatalf("expected sentinelErr, got %v", err)
	}
	if !postExecuted {
		t.Error("expected post middleware logic to execute on error return")
	}
}

// TestTurnPipeline_EmptyPipeline 验证空 Pipeline 或 nil coreFn 边界场景的鲁棒性。
func TestTurnPipeline_EmptyPipeline(t *testing.T) {
	p := companion.NewTurnPipeline()
	p.Use(nil) // nil 中间件安全忽略

	called := false
	err := p.Execute(&companion.TurnContext{}, func() error {
		called = true
		return nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !called {
		t.Error("expected coreFn to be called in empty pipeline")
	}

	// nil coreFn 不 panic
	err = p.Execute(&companion.TurnContext{}, nil)
	if err != nil {
		t.Fatalf("unexpected error with nil coreFn: %v", err)
	}
}

// TestContextGuardMiddleware 验证 ContextGuardMiddleware 在进入下一环节前执行动态压缩。
func TestContextGuardMiddleware(t *testing.T) {
	pipeline := companion.NewTurnPipeline()
	pipeline.Use(companion.ContextGuardMiddleware)

	longText := strings.Repeat("Deutsche Grammatik Regeln und Satzbau Strukturen. ", 40)
	msgs := []openai.ChatCompletionMessage{
		{Role: openai.ChatMessageRoleSystem, Content: "System Prompt"},
		{Role: openai.ChatMessageRoleUser, Content: "Frage 1: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Antwort 1: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Frage 2: " + longText},
		{Role: openai.ChatMessageRoleAssistant, Content: "Antwort 2: " + longText},
		{Role: openai.ChatMessageRoleUser, Content: "Frage 3: Was bedeutet das?"},
		{Role: openai.ChatMessageRoleAssistant, Content: "Antwort 3: Beispiel."},
	}

	smallSpec := provider.ModelSpec{
		Name:            "small-model",
		ContextWindow:   4000,
		CompactionRatio: 0.60,
	}

	tc := &companion.TurnContext{
		Turn:     1,
		Spec:     smallSpec,
		Messages: msgs,
	}

	var msgsSeenInCore []openai.ChatCompletionMessage
	err := pipeline.Execute(tc, func() error {
		msgsSeenInCore = tc.Messages
		return nil
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// 小模型超预算应触发折叠：长度应小于原消息数且包含压缩锚点
	if len(msgsSeenInCore) >= len(msgs) {
		t.Errorf("expected messages to be compacted, got length %d", len(msgsSeenInCore))
	}
	hasAnchor := false
	for _, m := range msgsSeenInCore {
		if strings.Contains(m.Content, "前序上下文压缩锚点") {
			hasAnchor = true
			break
		}
	}
	if !hasAnchor {
		t.Error("expected compacted anchor message in coreFn input")
	}
}

// TestTraceLoggingMiddleware_And_LogTurnTrace 验证追踪中间件度量延迟、统计 Token 并写出 JSONL 追踪记录。
func TestTraceLoggingMiddleware_And_LogTurnTrace(t *testing.T) {
	tempDir := t.TempDir()
	traceFile := filepath.Join(tempDir, "test_trace.jsonl")
	companion.SetTraceFilePath(traceFile)
	defer companion.ResetTraceFilePath()

	pipeline := companion.NewTurnPipeline()
	pipeline.Use(companion.TraceLoggingMiddleware)

	var fullContent strings.Builder
	tc := &companion.TurnContext{
		Turn: 1,
		Req: companion.Request{
			SessionID:       "sess-unit-test-101",
			Model:           "deepseek-flash",
			ReasoningEffort: "high",
		},
		Spec: provider.ModelSpec{
			Name: "deepseek-flash",
		},
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleSystem, Content: "System Tutor Prompt"},
			{Role: openai.ChatMessageRoleUser, Content: "Guten Tag, bitte korrigieren Sie diesen Satz."},
		},
		FullContent: &fullContent,
	}

	err := pipeline.Execute(tc, func() error {
		time.Sleep(15 * time.Millisecond) // 模拟模型生成耗时
		tc.FullContent.WriteString("Sehr gerne! Der Satz ist fast richtig.")
		tc.HadToolExecution = false
		return nil
	})

	if err != nil {
		t.Fatalf("unexpected pipeline execute error: %v", err)
	}

	// 验证 JSONL 文件已落盘并解析内容
	data, err := os.ReadFile(traceFile)
	if err != nil {
		t.Fatalf("failed to read trace file %s: %v", traceFile, err)
	}

	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 1 {
		t.Fatalf("expected 1 trace line, got %d. Content: %s", len(lines), string(data))
	}

	var rec companion.TurnTraceRecord
	if err := json.Unmarshal([]byte(lines[0]), &rec); err != nil {
		t.Fatalf("failed to parse trace record JSON: %v", err)
	}

	if rec.SessionID != "sess-unit-test-101" {
		t.Errorf("expected session_id sess-unit-test-101, got %s", rec.SessionID)
	}
	if rec.Turn != 1 {
		t.Errorf("expected turn 1, got %d", rec.Turn)
	}
	if rec.Model != "deepseek-flash" {
		t.Errorf("expected model deepseek-flash, got %s", rec.Model)
	}
	if rec.ReasoningEffort != "high" {
		t.Errorf("expected reasoning_effort high, got %s", rec.ReasoningEffort)
	}
	if rec.DurationMs < 10 {
		t.Errorf("expected duration >= 10ms, got %d", rec.DurationMs)
	}
	if rec.TokensIn <= 0 {
		t.Errorf("expected positive tokens_in, got %d", rec.TokensIn)
	}
	if rec.TokensOut <= 0 {
		t.Errorf("expected positive tokens_out, got %d", rec.TokensOut)
	}
	if rec.Timestamp == "" {
		t.Error("expected non-empty timestamp")
	}
}

// TestLogTurnTrace_ConcurrentSafe 验证多 goroutine 并发写 trace 文件互斥安全不串行损坏。
func TestLogTurnTrace_ConcurrentSafe(t *testing.T) {
	tempDir := t.TempDir()
	traceFile := filepath.Join(tempDir, "concurrent_trace.jsonl")
	companion.SetTraceFilePath(traceFile)
	defer companion.ResetTraceFilePath()

	const numWorkers = 20
	var wg sync.WaitGroup
	wg.Add(numWorkers)

	for i := 0; i < numWorkers; i++ {
		go func(idx int) {
			defer wg.Done()
			companion.LogTurnTrace(companion.TurnTraceRecord{
				SessionID:  fmt.Sprintf("concurrent-sess-%d", idx),
				Turn:       idx,
				Model:      "deepseek-flash",
				DurationMs: int64(10 + idx),
				TokensIn:   100 + idx,
				TokensOut:  50 + idx,
			})
		}(i)
	}

	wg.Wait()

	f, err := os.Open(traceFile)
	if err != nil {
		t.Fatalf("failed to open trace file: %v", err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	count := 0
	for scanner.Scan() {
		line := scanner.Text()
		var rec companion.TurnTraceRecord
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("corrupted JSON line in concurrent output: %s (err: %v)", line, err)
		}
		count++
	}

	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	if count != numWorkers {
		t.Errorf("expected %d records written concurrently, got %d", numWorkers, count)
	}
}

// TestCompanionAgent_WithPipelineIntegration 验证 CompanionAgent 深度装配自定义 Pipeline。
func TestCompanionAgent_WithPipelineIntegration(t *testing.T) {
	tempDir := t.TempDir()
	traceFile := filepath.Join(tempDir, "agent_pipeline_trace.jsonl")
	companion.SetTraceFilePath(traceFile)
	defer companion.ResetTraceFilePath()

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)
		chunk := `{"id":"c1","choices":[{"delta":{"content":"Pipeline 伴学就绪。"},"index":0}]}`
		fmt.Fprintf(w, "data: %s\n\n", chunk)
		flusher.Flush()
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer ts.Close()

	cfg := openai.DefaultConfig("test-key")
	cfg.BaseURL = ts.URL
	client := openai.NewClientWithConfig(cfg)

	customMiddlewareRan := false
	customPipeline := companion.NewDefaultTurnPipeline()
	customPipeline.Use(func(tc *companion.TurnContext, next func() error) error {
		customMiddlewareRan = true
		return next()
	})

	agent := companion.NewCompanionAgent(client, nil, "deepseek-flash").
		WithPipeline(customPipeline)

	req := companion.Request{
		SessionID: "sess-agent-pipe",
		Messages:  []companion.Message{{Role: "user", Content: "Hallo"}},
	}

	outcome, err := agent.RunLoop(context.Background(), req, nil)
	if err != nil {
		t.Fatalf("RunLoop failed: %v", err)
	}

	if outcome.Status != "ok" {
		t.Errorf("outcome status = %s, want ok", outcome.Status)
	}
	if outcome.Text != "Pipeline 伴学就绪。" {
		t.Errorf("unexpected outcome text: %s", outcome.Text)
	}
	if !customMiddlewareRan {
		t.Error("expected custom middleware to run during CompanionAgent.RunLoop")
	}

	// 确认 TraceLoggingMiddleware 也在 RunLoop 中生效落盘
	data, err := os.ReadFile(traceFile)
	if err != nil {
		t.Fatalf("failed to read trace file: %v", err)
	}
	if !strings.Contains(string(data), "sess-agent-pipe") {
		t.Errorf("expected trace file to contain session_id sess-agent-pipe, got: %s", string(data))
	}
}
