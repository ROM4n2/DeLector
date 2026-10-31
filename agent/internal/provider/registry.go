package provider

import (
	"errors"
	"fmt"
	"strings"
	"sync"
)

// Registry 提供并发安全的多模型供应商注册表与规格决策中枢。
type Registry struct {
	mu        sync.RWMutex
	providers map[string]Provider
}

// NewRegistry 构造空 Registry 实例。
func NewRegistry() *Registry {
	return &Registry{
		providers: make(map[string]Provider),
	}
}

// NewDefaultRegistry 构造预注册 DeepSeek、Ollama、OpenRouter 与 Custom 供应商的默认注册中心。
func NewDefaultRegistry() *Registry {
	r := NewRegistry()
	_ = r.Register(NewDeepSeekProvider())
	_ = r.Register(NewOllamaProvider())
	_ = r.Register(NewOpenRouterProvider())
	_ = r.Register(NewCustomProvider())
	return r
}

// Register 向注册表注册一个供应商实现。并发安全。
// 若供应商为 nil、ID 为空或已被注册，则返回明确错误。
func (r *Registry) Register(p Provider) error {
	if p == nil {
		return errors.New("registry: provider must not be nil")
	}
	id := strings.TrimSpace(p.ID())
	if id == "" {
		return errors.New("registry: provider ID must not be empty")
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	if _, exists := r.providers[id]; exists {
		return fmt.Errorf("registry: provider %q already registered", id)
	}
	r.providers[id] = p
	return nil
}

// Get 查询指定 ID 的供应商。并发安全。
func (r *Registry) Get(id string) (Provider, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	p, ok := r.providers[id]
	return p, ok
}

// List 返回所有已注册供应商的快照列表。并发安全。
func (r *Registry) List() []Provider {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]Provider, 0, len(r.providers))
	for _, p := range r.providers {
		list = append(list, p)
	}
	return list
}

// ResolveModel 动态解析给定供应商与模型的硬件规格 ModelSpec。并发安全。
// 若 providerID 未显式指定，将尝试依据模型名称前缀进行智能启发式路由；
// 若未命中已知供应商，则回退至注册表中的 custom 供应商或兜底规格。
func (r *Registry) ResolveModel(providerID string, model string) ModelSpec {
	r.mu.RLock()
	defer r.mu.RUnlock()

	normID := strings.TrimSpace(providerID)
	normModel := strings.TrimSpace(model)

	// 1. 若指定了有效 providerID，优先查找对应供应商
	if normID != "" {
		if p, ok := r.providers[normID]; ok {
			return p.ResolveModelSpec(normModel)
		}
	}

	// 2. 若未指定 providerID，通过模型名称启发式推断供应商
	lowerModel := strings.ToLower(normModel)
	if strings.HasPrefix(lowerModel, "deepseek") {
		if p, ok := r.providers[ProviderIDDeepSeek]; ok {
			return p.ResolveModelSpec(normModel)
		}
	} else if strings.Contains(normModel, "/") {
		if p, ok := r.providers[ProviderIDOpenRouter]; ok {
			return p.ResolveModelSpec(normModel)
		}
	} else if strings.HasPrefix(lowerModel, "qwen") || strings.HasPrefix(lowerModel, "llama") {
		if p, ok := r.providers[ProviderIDOllama]; ok {
			return p.ResolveModelSpec(normModel)
		}
	}

	// 3. 回退至 custom 供应商
	if p, ok := r.providers[ProviderIDCustom]; ok {
		return p.ResolveModelSpec(normModel)
	}

	// 4. 终极兜底规格
	if normModel == "" {
		normModel = "default"
	}
	return ModelSpec{
		Name:                normModel,
		ProviderID:          ProviderIDCustom,
		ContextWindow:       CustomContextWindow,
		MaxOutputTokens:     CustomMaxOutputTokens,
		SupportsToolCalling: true,
		SupportsThinking:    false,
		CompactionRatio:     DefaultCompactionRatio,
	}
}
