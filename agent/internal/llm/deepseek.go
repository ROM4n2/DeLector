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

// Complete 组装 chat/completions：system 提示（若非空）以 system 角色置于首位，
// user 输入以 user 角色紧随其后；返回 assistant 首条消息内容。
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

	resp, err := c.openAI.CreateChatCompletion(ctx, cr)
	if err != nil {
		return "", fmt.Errorf("llm: chat completion failed: %w", err)
	}
	if len(resp.Choices) == 0 {
		return "", errors.New("llm: chat completion returned no choices")
	}
	return resp.Choices[0].Message.Content, nil
}
