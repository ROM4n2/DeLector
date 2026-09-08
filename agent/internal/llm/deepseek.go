// Package llm 封装对 DeepSeek OpenAI 兼容 chat/completions 端点的调用。
//
// 选型 go-openai（github.com/sashabaranov/go-openai，ADR-0008）：DeepSeek
// 暴露 OpenAI 兼容 API，SDK 允许注入 BaseURL 与 HTTPClient，便于 httptest
// 桩测；底层经 ctx 驱动出站请求，天然透传超时/取消错误链。
package llm

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/sashabaranov/go-openai"
)

const (
	// defaultBaseURL 为 DeepSeek 官方 API 根地址；可经 Config.BaseURL 注入
	// 覆盖（例如 httptest 桩），禁止在测试环境直连生产。
	defaultBaseURL = "https://api.deepseek.com"
	// defaultModel 为 DeepSeek 通用对话模型。
	defaultModel = "deepseek-chat"
	// envAPIKey 是唯一允许读取的凭据来源：生产 key 一律经此环境变量注入，
	// 代码与仓库任何位置绝不硬编码真实 key。
	envAPIKey = "DEEPSEEK_API_KEY"
	// defaultTimeout 兜底单次补全调用的 HTTP 总超时；调用方仍应以更小粒度
	// 用 ctx 控制单次请求。零值 http.Client.Timeout 语义为无限制，故必设。
	defaultTimeout = 120 * time.Second
	// llmRetries 是初始请求失败后针对可重试状态（429/5xx）的退避重试次数
	// （评审 ⑧，镜像 runner.deliverRetries 语义）：每调用 = 1 次初始 +
	// 至多 llmRetries 次重试 = 至多 4 次请求。其余错误（4xx 非 429、ctx
	// 取消/超时）不重试，原样返回。
	llmRetries = 3
)

// ErrMissingAPIKey 哨兵错误：DEEPSEEK_API_KEY 环境变量未配置。
// 调用方以 errors.Is(err, ErrMissingAPIKey) 判定，禁字符串比较。
var ErrMissingAPIKey = errors.New("llm: DEEPSEEK_API_KEY environment variable not set")

// Config 控制 Client 的构造。零值亦可传入 NewClient，字段落默认值。
type Config struct {
	// BaseURL 覆写 API 根地址，默认 https://api.deepseek.com。
	// 必须可注入：测试借此指向 httptest 桩，杜绝真实外呼。
	BaseURL string
	// Model 覆写对话模型，默认 deepseek-chat。
	Model string
}

// Client 持有构造好的 go-openai 客户端，通过 Complete 发起补全。
// 零值不可用，须经 NewClient 构造。
type Client struct {
	config Config
	openAI *openai.Client
}

// NewClient 读取 DEEPSEEK_API_KEY 并构造 Client。key 为空（含未设置或空串）
// 返回哨兵 ErrMissingAPIKey，绝不回退硬编码占位。
func NewClient(cfg Config) (*Client, error) {
	if cfg.BaseURL == "" {
		cfg.BaseURL = defaultBaseURL
	}
	if cfg.Model == "" {
		cfg.Model = defaultModel
	}

	// key 只经 os.Getenv 读取（Global Constraints: 凭证不入库）。
	key := os.Getenv(envAPIKey)
	if key == "" {
		return nil, ErrMissingAPIKey
	}

	ocfg := openai.DefaultConfig(key)
	ocfg.BaseURL = cfg.BaseURL
	ocfg.HTTPClient = &http.Client{Timeout: defaultTimeout}

	return &Client{config: cfg, openAI: openai.NewClientWithConfig(ocfg)}, nil
}

// req 承载单次补全的可变选项，避免 Complete 长出海量布尔/标量参数。
type req struct {
	temperature *float32
}

// Option 以函数式方式修饰一次补全请求。
type Option func(*req)

// WithTemperature 设定采样温度（DeepSeek 接受 0–2）。未调用则 SDK 采用默认。
func WithTemperature(t float32) Option {
	return func(r *req) { r.temperature = &t }
}

// llmBackoffDefault 是 LLM 调用退避纯函数，镜像 runner 的 deliverBackoff 风格：
// 500ms 基数 × 2^attempt，封顶 8s；attempt>4 直接封顶（防移位溢出）。
func llmBackoffDefault(attempt int) time.Duration {
	const base = 500 * time.Millisecond
	const cap = 8 * time.Second
	switch {
	case attempt < 0:
		attempt = 0
	case attempt > 4:
		return cap
	}
	return base << attempt
}

// llmBackoff 是退避 seam（测试可缩短以免长 sleep）；默认即纯函数。
var llmBackoff = llmBackoffDefault

// isRetryableStatus 报告错误是否为可重试的 API 状态（429 限流 / 5xx 服务端
// 抖动——评审 ⑧）。非 go-openai APIError（网络错误/ctx 取消/超时等）一律
// 视为不可重试：网络层错误不重试是刻意取舍——4xx 类凭据/参数错误重试只会
// 重复失败，ctx 取消/超时重试反而拖长超时窗口。
func isRetryableStatus(err error) bool {
	var apiErr *openai.APIError
	if !errors.As(err, &apiErr) {
		return false
	}
	return apiErr.HTTPStatusCode == http.StatusTooManyRequests ||
		apiErr.HTTPStatusCode >= 500
}

// Complete 组装 chat/completions：system 提示（若非空）以 system 角色置于首位，
// user 输入以 user 角色紧随其后；返回 assistant 首条消息内容。
//
// 重试语义（评审 ⑧）：429/5xx 时按 llmBackoff 退避重试，至多 1+llmRetries 次
// 请求；其它错误（4xx 非 429、ctx 取消/超时）立即返回不重试。
//
// 超时纪律：出站请求由入参 ctx 驱动，调用方可用 context.WithTimeout/WithCancel
// 控制单次调用；底层错误链经 %w 保留，可 errors.Is(err, context.DeadlineExceeded)
// 判定超时、errors.As 判定 go-openai 的 *APIError（如 401）。
func (c *Client) Complete(ctx context.Context, system, user string, opts ...Option) (string, error) {
	r := &req{}
	for _, o := range opts {
		o(r)
	}

	msgs := make([]openai.ChatCompletionMessage, 0, 2)
	if system != "" {
		msgs = append(msgs, openai.ChatCompletionMessage{
			Role:    openai.ChatMessageRoleSystem,
			Content: system,
		})
	}
	msgs = append(msgs, openai.ChatCompletionMessage{
		Role:    openai.ChatMessageRoleUser,
		Content: user,
	})

	cr := openai.ChatCompletionRequest{
		Model:    c.config.Model,
		Messages: msgs,
	}
	if r.temperature != nil {
		cr.Temperature = *r.temperature
	}

	var lastErr error
	for attempt := 0; attempt <= llmRetries; attempt++ {
		if attempt > 0 {
			// 相邻尝试间按 llmBackoff(attempt-1) 退避（ctx 可中断）。
			timer := time.NewTimer(llmBackoff(attempt - 1))
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				return "", ctx.Err() // 退避中被取消：返回 ctx 错误（errors.Is 可判）
			}
			timer.Stop()
		}

		resp, err := c.openAI.CreateChatCompletion(ctx, cr)
		if err != nil {
			lastErr = err
			if !isRetryableStatus(err) || attempt == llmRetries {
				return "", fmt.Errorf("llm: chat completion failed: %w", lastErr)
			}
			continue // 429/5xx → 退避重试
		}
		if len(resp.Choices) == 0 {
			return "", errors.New("llm: chat completion returned no choices")
		}
		return resp.Choices[0].Message.Content, nil
	}
	// 不可达（循环内必返回），仅防静态分析缺 return。
	return "", fmt.Errorf("llm: chat completion failed: %w", lastErr)
}
