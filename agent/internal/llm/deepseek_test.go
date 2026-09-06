package llm

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/sashabaranov/go-openai"
)

// placeholderToken 仅作测试占位，绝非真实凭据：凭证卫生测试要求源码
// （含本测试文件）不得出现任何真实 key 形态。
const placeholderToken = "test-token"

// stubSuccess 返回一个 httptest 桩：断言请求形态并回吐标准 OpenAI 结构。
func stubSuccess(t *testing.T, wantSystem, wantUser string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/chat/completions" {
			t.Errorf("path = %q, want /chat/completions", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer "+placeholderToken {
			t.Errorf("Authorization = %q, want %q", got, "Bearer "+placeholderToken)
		}

		var body openai.ChatCompletionRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode request body: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if body.Model != defaultModel {
			t.Errorf("model = %q, want %q", body.Model, defaultModel)
		}
		if len(body.Messages) != 2 {
			t.Errorf("len(messages) = %d, want 2", len(body.Messages))
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if body.Messages[0].Role != openai.ChatMessageRoleSystem || body.Messages[0].Content != wantSystem {
			t.Errorf("messages[0] = %+v, want system role with %q", body.Messages[0], wantSystem)
		}
		if body.Messages[1].Role != openai.ChatMessageRoleUser || body.Messages[1].Content != wantUser {
			t.Errorf("messages[1] = %+v, want user role with %q verbatim", body.Messages[1], wantUser)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"cmpl-test","object":"chat.completion","created":1,
			"model":"deepseek-chat","choices":[{"index":0,"message":{"role":"assistant","content":"Hello, 世界"},"finish_reason":"stop"}],
			"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}`))
	}))
	t.Cleanup(srv.Close)
	return srv
}

// newClientWithToken 设置占位 token 并构造 Client，供桩用例复用。
func newClientWithToken(t *testing.T, baseURL string) *Client {
	t.Helper()
	t.Setenv(envAPIKey, placeholderToken)
	c, err := NewClient(Config{BaseURL: baseURL})
	if err != nil {
		t.Fatalf("NewClient with injected baseURL: %v", err)
	}
	return c
}

func TestNewClient_MissingAPIKey(t *testing.T) {
	t.Setenv(envAPIKey, "") // 清掉环境变量，模拟生产未配置
	_, err := NewClient(Config{})
	if err == nil {
		t.Fatal("NewClient with empty DEEPSEEK_API_KEY: got nil error, want ErrMissingAPIKey")
	}
	if !errors.Is(err, ErrMissingAPIKey) {
		t.Fatalf("NewClient error = %v, want errors.Is(err, ErrMissingAPIKey)", err)
	}
}

func TestComplete_Success(t *testing.T) {
	const wantSystem = "You are a concise writing assistant."
	const wantUser = "Rewrite: 快速跑的棕狐狸。"
	srv := stubSuccess(t, wantSystem, wantUser)
	c := newClientWithToken(t, srv.URL)

	got, err := c.Complete(context.Background(), wantSystem, wantUser)
	if err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if got != "Hello, 世界" {
		t.Errorf("Complete content = %q, want %q", got, "Hello, 世界")
	}
}

func TestComplete_WithTemperature_SetsField(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body openai.ChatCompletionRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.Temperature != 0.2 {
			t.Errorf("temperature = %v, want 0.2", body.Temperature)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","created":1,"model":"deepseek-chat",
			"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],
			"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`))
	}))
	t.Cleanup(srv.Close)
	c := newClientWithToken(t, srv.URL)

	if _, err := c.Complete(context.Background(), "", "hi", WithTemperature(0.2)); err != nil {
		t.Fatalf("Complete: %v", err)
	}
}

func TestComplete_API401_WrappedError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"error":{"message":"Incorrect API key provided","type":"invalid_request_error"}}`))
	}))
	t.Cleanup(srv.Close)
	c := newClientWithToken(t, srv.URL)

	_, err := c.Complete(context.Background(), "", "hi")
	if err == nil {
		t.Fatal("Complete on 401: got nil error, want APIError wrapped in chain")
	}
	var apiErr *openai.APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("Complete error = %v, want it to wrap *openai.APIError", err)
	}
	if apiErr.HTTPStatusCode != http.StatusUnauthorized {
		t.Errorf("APIError.HTTPStatusCode = %d, want 401", apiErr.HTTPStatusCode)
	}
}

func TestComplete_ContextDeadline(t *testing.T) {
	// 桩故意拖慢响应，保证响应到达前客户端 ctx 先到期，从而触发超时判定。
	// 不用 <-r.Context().Done() 阻塞：那依赖 keep-alive 连接在客户端取消后
	// 立即关闭的时序，会导致 srv.Close() 永久等待 handler 退出。
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(300 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	c := newClientWithToken(t, srv.URL)

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	_, err := c.Complete(ctx, "", "hi")
	if err == nil {
		t.Fatal("Complete with expiring ctx: got nil error, want DeadlineExceeded in chain")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Complete error = %v, want errors.Is(err, context.DeadlineExceeded)", err)
	}
}

// TestCredentialHygiene 是「源码无硬编码 key」的守卫：读取 deepseek.go 源码，
// 断言不含任何真实 key 形态（sk-/gsk- 前缀、连续 32+ hex），且除环境变量
// 标识符 DEEPSEEK_API_KEY 外不引用其它 key 名称。
func TestCredentialHygiene(t *testing.T) {
	src, err := os.ReadFile("deepseek.go")
	if err != nil {
		t.Fatalf("read deepseek.go: %v", err)
	}
	text := string(src)

	for _, forbidden := range []string{"sk-", "gsk-", "sk-"} {
		if strings.Contains(text, forbidden) {
			t.Errorf("deepseek.go contains forbidden real-key prefix %q", forbidden)
		}
	}
	// 32 个及以上连续 hex 字符（不含空格/符号）即疑似硬编码 token。
	if hasLongHexRun(text) {
		t.Error("deepseek.go contains a run of 32+ consecutive hex chars (possible hardcoded token)")
	}
}

// hasLongHexRun 报告 s 中是否出现长度 >= 32 的连续 hex 字符段。
func hasLongHexRun(s string) bool {
	run := 0
	for _, r := range s {
		if (r >= '0' && r <= '9') || (r >= 'a' && r <= 'f') || (r >= 'A' && r <= 'F') {
			run++
			if run >= 32 {
				return true
			}
		} else {
			run = 0
		}
	}
	return false
}
