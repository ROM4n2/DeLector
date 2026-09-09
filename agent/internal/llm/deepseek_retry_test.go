// deepseek_retry_test.go 钉死 429/5xx 的退避重试语义（vault-team 评审 ⑧）：
//   - 429 后恢复 200：自动重试成功，请求次数 = 初始 1 + 重试次数；
//   - 持续 5xx：退避重试耗尽后返回错误（请求总数 = 1 + llmRetries），不无限重试；
//   - 401 等不可重试 4xx 立即返回（deepseek_test.go 既有 401 用例回归此语义）。
package llm

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sashabaranov/go-openai"
)

// withTinyBackoff 临时把退避 seam 缩到 ~1ms，避免测试长 sleep。
func withTinyBackoff(t *testing.T) {
	t.Helper()
	old := llmBackoff
	llmBackoff = func(int) time.Duration { return time.Millisecond }
	t.Cleanup(func() { llmBackoff = old })
}

// chatStub 返回按次数切换状态的补全桩：前 nErr 次回 status，之后回 successContent
// 或持续回 status（nErr<0 表示永远错误）。计数经原子变量供断言。
func chatStub(status int, nErr int, successContent string) (*httptest.Server, *int64) {
	var calls int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt64(&calls, 1)
		if nErr >= 0 && int(n) > nErr {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(fmt.Sprintf(
				`{"id":"cmpl-r","object":"chat.completion","created":1,"model":"deepseek-chat",`+
					`"choices":[{"index":0,"message":{"role":"assistant","content":%q},"finish_reason":"stop"}],`+
					`"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`, successContent)))
			return
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"error":{"message":"stub failure","type":"server_error"}}`))
	}))
	return srv, &calls
}

func TestComplete_Retries429ThenSucceeds(t *testing.T) {
	withTinyBackoff(t)
	srv, calls := chatStub(http.StatusTooManyRequests, 2, "recovered content")
	t.Cleanup(srv.Close)
	c := newClientWithToken(t, srv.URL)

	got, err := c.Complete(context.Background(), "sys", "hi")
	if err != nil {
		t.Fatalf("429 两次后 200 应重试成功：%v", err)
	}
	if got != "recovered content" {
		t.Errorf("content = %q，期望 %q", got, "recovered content")
	}
	if want := int64(1 + 2); *calls != want {
		t.Errorf("请求次数 = %d，期望 1 初始 + 2 重试 = %d", *calls, want)
	}
}

func TestComplete_500ExhaustsRetries(t *testing.T) {
	withTinyBackoff(t)
	srv, calls := chatStub(http.StatusInternalServerError, -1, "")
	t.Cleanup(srv.Close)
	c := newClientWithToken(t, srv.URL)

	_, err := c.Complete(context.Background(), "", "hi")
	if err == nil {
		t.Fatal("持续 5xx 应返回错误")
	}
	if want := int64(1 + llmRetries); *calls != want {
		t.Errorf("请求次数 = %d，期望 1 + llmRetries(%d) = %d（不无限重试）", *calls, llmRetries, want)
	}
	var apiErr *openai.APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("错误应链上 *openai.APIError，实得 %v", err)
	}
	if apiErr.HTTPStatusCode != http.StatusInternalServerError {
		t.Errorf("APIError.HTTPStatusCode = %d，期望 500", apiErr.HTTPStatusCode)
	}
	if !strings.Contains(err.Error(), "chat completion failed") {
		t.Errorf("错误应带统一前缀文案，实得: %v", err)
	}
}
