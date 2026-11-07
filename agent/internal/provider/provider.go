// Package provider 提供伴学 Agent 的多模型供应商抽象与模型规格字典。
// 对接 2026 最新 DeepSeek 1M 上下文规格与 Ollama / OpenRouter / 自定义 OpenAI 兼容端点。
package provider

import (
	"errors"
	"os"
	"strings"

	"github.com/sashabaranov/go-openai"
)

// DefaultCompactionRatio 是全局 Pi 式流控水位线（60% 上下文用量触发折叠）。
const DefaultCompactionRatio = 0.60

// 常用供应商 ID 常量
const (
	ProviderIDDeepSeek   = "deepseek"
	ProviderIDOllama     = "ollama"
	ProviderIDOpenRouter = "openrouter"
	ProviderIDCustom     = "custom"
)

// 2026 DeepSeek 规约常量
const (
	DeepSeekDefaultBaseURL   = "https://api.deepseek.com"
	DeepSeekDefaultModel     = "deepseek-flash"
	DeepSeekContextWindow    = 1048576 // 1M tokens
	DeepSeekMaxOutputTokens  = 384000  // 384k tokens
	OllamaDefaultBaseURL     = "http://localhost:11434/v1"
	OllamaDefaultModel       = "qwen3.5:4b"
	OllamaContextWindow      = 32768
	OllamaMaxOutputTokens    = 8192
	OpenRouterDefaultBaseURL = "https://openrouter.ai/api/v1"
	OpenRouterDefaultModel   = "deepseek/deepseek-chat"
	CustomContextWindow      = 32768
	CustomMaxOutputTokens    = 4096
)

// ModelSource 标记最终生效的默认模型名由哪一层决定（启动日志与 /health 共用）。
type ModelSource string

const (
	// ModelSourceFlag 表示用户显式传入 --model。
	ModelSourceFlag ModelSource = "flag"
	// ModelSourceEnv 表示由非空 API_MODEL 环境变量注入（标准部署由 Python supervisor 写入）。
	ModelSourceEnv ModelSource = "env"
	// ModelSourceDefault 表示既无显式 --model 也无非空 API_MODEL，落回内置常量。
	ModelSourceDefault ModelSource = "default"
)

// ResolveModelName 解析最终生效的模型名，优先级：显式 --model > 非空 API_MODEL > 内置默认常量。
//
// flagSet 记录的是「用户是否显式传了 --model」，而不是拿值与默认常量比较：显式传入的值
// 即使恰好等于默认常量，也不会再被 API_MODEL 静默顶掉；未设置、空串或纯空白的
// API_MODEL 一律回落到 DeepSeekDefaultModel，默认值不会被静默绕过。
func ResolveModelName(flagValue string, flagSet bool, envValue string) (string, ModelSource) {
	if flagSet {
		if v := strings.TrimSpace(flagValue); v != "" {
			return v, ModelSourceFlag
		}
	}
	if v := strings.TrimSpace(envValue); v != "" {
		return v, ModelSourceEnv
	}
	return DeepSeekDefaultModel, ModelSourceDefault
}

// ModelSpec 封装特定模型的静态硬件上下文配额与特性能力。
type ReasoningEffort string

const (
	ReasoningEffortNone   ReasoningEffort = "none"
	ReasoningEffortLow    ReasoningEffort = "low"
	ReasoningEffortMedium ReasoningEffort = "medium"
	ReasoningEffortHigh   ReasoningEffort = "high"
)

type ModelSpec struct {
	Name                   string          // 模型标识（如 deepseek-flash, qwen3.5:4b）
	ProviderID             string          // 归属供应商 ID（如 deepseek, ollama）
	ContextWindow          int             // 最大上下文窗口大小（Token 数）
	MaxOutputTokens        int             // 最大单次输出 Token 配额
	SupportsToolCalling    bool            // 是否支持原生 Tool Calling
	SupportsThinking       bool            // 是否原生支持深度思考链（Reasoning / Thinking）
	DefaultReasoningEffort ReasoningEffort // 默认思考强度（low/medium/high）
	CompactionRatio        float64         // 上下文压缩流控水位线（默认 0.60 即 60%）
}

// Provider 抽象多模型供应商统一协议与客户端构造。
type Provider interface {
	ID() string
	DisplayName() string
	DefaultBaseURL() string
	DefaultModel() string
	ResolveModelSpec(model string) ModelSpec
	CreateClient(apiKey string, baseURL string) (*openai.Client, error)
}

// --- deepseekProvider ---

type deepseekProvider struct{}

// NewDeepSeekProvider 创建 DeepSeek 官方供应商实例。
func NewDeepSeekProvider() Provider {
	return &deepseekProvider{}
}

func (p *deepseekProvider) ID() string {
	return ProviderIDDeepSeek
}

func (p *deepseekProvider) DisplayName() string {
	return "DeepSeek"
}

func (p *deepseekProvider) DefaultBaseURL() string {
	return DeepSeekDefaultBaseURL
}

func (p *deepseekProvider) DefaultModel() string {
	return DeepSeekDefaultModel
}

func (p *deepseekProvider) ResolveModelSpec(model string) ModelSpec {
	if model == "" {
		model = DeepSeekDefaultModel
	}

	// 2026 最新官方主力模型与兼容别名统一遵循 1M 上下文与 384k 输出规约
	return ModelSpec{
		Name:                   model,
		ProviderID:             ProviderIDDeepSeek,
		ContextWindow:          DeepSeekContextWindow,
		MaxOutputTokens:        DeepSeekMaxOutputTokens,
		SupportsToolCalling:    true,
		SupportsThinking:       true,
		DefaultReasoningEffort: ReasoningEffortMedium,
		CompactionRatio:        DefaultCompactionRatio,
	}
}

func (p *deepseekProvider) CreateClient(apiKey string, baseURL string) (*openai.Client, error) {
	if baseURL == "" {
		baseURL = p.DefaultBaseURL()
	}
	if apiKey == "" {
		apiKey = os.Getenv("DEEPSEEK_API_KEY")
	}
	if apiKey == "" {
		return nil, errors.New("provider deepseek: API key required (DEEPSEEK_API_KEY unset)")
	}

	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return openai.NewClientWithConfig(cfg), nil
}

// --- ollamaProvider ---

type ollamaProvider struct{}

// NewOllamaProvider 创建本地 Ollama 供应商实例。
func NewOllamaProvider() Provider {
	return &ollamaProvider{}
}

func (p *ollamaProvider) ID() string {
	return ProviderIDOllama
}

func (p *ollamaProvider) DisplayName() string {
	return "Ollama"
}

func (p *ollamaProvider) DefaultBaseURL() string {
	return OllamaDefaultBaseURL
}

func (p *ollamaProvider) DefaultModel() string {
	return OllamaDefaultModel
}

func (p *ollamaProvider) ResolveModelSpec(model string) ModelSpec {
	if model == "" {
		model = OllamaDefaultModel
	}

	return ModelSpec{
		Name:                   model,
		ProviderID:             ProviderIDOllama,
		ContextWindow:          OllamaContextWindow,
		MaxOutputTokens:        OllamaMaxOutputTokens,
		SupportsToolCalling:    true,
		SupportsThinking:       false,
		DefaultReasoningEffort: ReasoningEffortNone,
		CompactionRatio:        DefaultCompactionRatio,
	}
}

func (p *ollamaProvider) CreateClient(apiKey string, baseURL string) (*openai.Client, error) {
	if baseURL == "" {
		baseURL = p.DefaultBaseURL()
	}
	// 本地 Ollama 无需真实 key，提供默认占位确保 go-openai 配置合法
	if apiKey == "" {
		apiKey = "ollama"
	}

	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return openai.NewClientWithConfig(cfg), nil
}

// --- openrouterProvider ---

type openrouterProvider struct{}

// NewOpenRouterProvider 创建 OpenRouter 聚合供应商实例。
func NewOpenRouterProvider() Provider {
	return &openrouterProvider{}
}

func (p *openrouterProvider) ID() string {
	return ProviderIDOpenRouter
}

func (p *openrouterProvider) DisplayName() string {
	return "OpenRouter"
}

func (p *openrouterProvider) DefaultBaseURL() string {
	return OpenRouterDefaultBaseURL
}

func (p *openrouterProvider) DefaultModel() string {
	return OpenRouterDefaultModel
}

func (p *openrouterProvider) ResolveModelSpec(model string) ModelSpec {
	if model == "" {
		model = OpenRouterDefaultModel
	}

	// 针对 OpenRouter 上托管的 DeepSeek 系列透传 1M 上下文规格
	if strings.Contains(strings.ToLower(model), "deepseek") {
		return ModelSpec{
			Name:                   model,
			ProviderID:             ProviderIDOpenRouter,
			ContextWindow:          DeepSeekContextWindow,
			MaxOutputTokens:        DeepSeekMaxOutputTokens,
			SupportsToolCalling:    true,
			SupportsThinking:       true,
			DefaultReasoningEffort: ReasoningEffortMedium,
			CompactionRatio:        DefaultCompactionRatio,
		}
	}

	return ModelSpec{
		Name:                   model,
		ProviderID:             ProviderIDOpenRouter,
		ContextWindow:          131072,
		MaxOutputTokens:        8192,
		SupportsToolCalling:    true,
		SupportsThinking:       false,
		DefaultReasoningEffort: ReasoningEffortNone,
		CompactionRatio:        DefaultCompactionRatio,
	}
}

func (p *openrouterProvider) CreateClient(apiKey string, baseURL string) (*openai.Client, error) {
	if baseURL == "" {
		baseURL = p.DefaultBaseURL()
	}
	if apiKey == "" {
		apiKey = os.Getenv("OPENROUTER_API_KEY")
	}
	if apiKey == "" {
		return nil, errors.New("provider openrouter: API key required (OPENROUTER_API_KEY unset)")
	}

	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return openai.NewClientWithConfig(cfg), nil
}

// --- customProvider ---

type customProvider struct {
	id          string
	displayName string
}

// NewCustomProvider 创建默认自定义 OpenAI 兼容供应商实例。
func NewCustomProvider() Provider {
	return NewDynamicCustomProvider(ProviderIDCustom, "Custom")
}

// NewDynamicCustomProvider 创建指定 ID 与名称的自定义 OpenAI 兼容供应商实例。
func NewDynamicCustomProvider(id, displayName string) Provider {
	if id == "" {
		id = ProviderIDCustom
	}
	if displayName == "" {
		displayName = "Custom"
	}
	return &customProvider{
		id:          id,
		displayName: displayName,
	}
}

func (p *customProvider) ID() string {
	return p.id
}

func (p *customProvider) DisplayName() string {
	return p.displayName
}

func (p *customProvider) DefaultBaseURL() string {
	return ""
}

func (p *customProvider) DefaultModel() string {
	return "default"
}

func (p *customProvider) ResolveModelSpec(model string) ModelSpec {
	if model == "" {
		model = p.DefaultModel()
	}

	supportsThinking := strings.Contains(strings.ToLower(model), "deepseek") ||
		strings.Contains(strings.ToLower(model), "r1") ||
		strings.Contains(strings.ToLower(model), "reasoner") ||
		strings.Contains(strings.ToLower(model), "thinking")

	defaultEffort := ReasoningEffortNone
	if supportsThinking {
		defaultEffort = ReasoningEffortMedium
	}

	return ModelSpec{
		Name:                   model,
		ProviderID:             p.id,
		ContextWindow:          CustomContextWindow,
		MaxOutputTokens:        CustomMaxOutputTokens,
		SupportsToolCalling:    true,
		SupportsThinking:       supportsThinking,
		DefaultReasoningEffort: defaultEffort,
		CompactionRatio:        DefaultCompactionRatio,
	}
}

func (p *customProvider) CreateClient(apiKey string, baseURL string) (*openai.Client, error) {
	if apiKey == "" {
		apiKey = "custom-key"
	}

	cfg := openai.DefaultConfig(apiKey)
	if baseURL != "" {
		cfg.BaseURL = baseURL
	}
	return openai.NewClientWithConfig(cfg), nil
}
