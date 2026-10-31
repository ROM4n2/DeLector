package provider_test

import (
	"fmt"
	"sync"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/provider"
)

func TestProviderInterface(t *testing.T) {
	// 验证所有内置 Provider 均实现 Provider 接口契约
	providers := []provider.Provider{
		provider.NewDeepSeekProvider(),
		provider.NewOllamaProvider(),
		provider.NewOpenRouterProvider(),
		provider.NewCustomProvider(),
	}

	for _, p := range providers {
		t.Run(p.ID(), func(t *testing.T) {
			if p.ID() == "" {
				t.Fatalf("expected non-empty ID for %T", p)
			}
			if p.DisplayName() == "" {
				t.Fatalf("expected non-empty DisplayName for %s", p.ID())
			}
			if p.ID() != "custom" && p.DefaultBaseURL() == "" {
				t.Fatalf("expected non-empty DefaultBaseURL for %s", p.ID())
			}
			if p.ID() != "custom" && p.DefaultModel() == "" {
				t.Fatalf("expected non-empty DefaultModel for %s", p.ID())
			}

			// 测试 ResolveModelSpec
			spec := p.ResolveModelSpec("")
			if spec.Name == "" {
				t.Fatalf("expected default model spec Name to be non-empty for %s", p.ID())
			}
			if spec.ProviderID != p.ID() {
				t.Fatalf("expected ProviderID %q, got %q", p.ID(), spec.ProviderID)
			}

			// 测试 CreateClient 携带有效凭据
			client, err := p.CreateClient("test-key", "")
			if err != nil {
				t.Fatalf("CreateClient failed for %s: %v", p.ID(), err)
			}
			if client == nil {
				t.Fatalf("expected non-nil openai.Client for %s", p.ID())
			}
		})
	}
}

func TestDeepSeekCreateClientKeyValidation(t *testing.T) {
	p := provider.NewDeepSeekProvider()
	t.Setenv("DEEPSEEK_API_KEY", "")

	// 无 API Key 时应明确报错，禁止静默伪造客户端
	_, err := p.CreateClient("", "")
	if err == nil {
		t.Fatal("expected error when DEEPSEEK_API_KEY is empty and no key passed, got nil")
	}
}

func TestOllamaCreateClientWithoutKey(t *testing.T) {
	p := provider.NewOllamaProvider()
	// 本地 Ollama 无需 API Key 即可成功构造客户端
	client, err := p.CreateClient("", "")
	if err != nil {
		t.Fatalf("expected Ollama CreateClient without key to succeed, got %v", err)
	}
	if client == nil {
		t.Fatal("expected non-nil client for Ollama")
	}
}

func TestModelSpecFields(t *testing.T) {
	spec := provider.ModelSpec{
		Name:                "test-model",
		ProviderID:          "deepseek",
		ContextWindow:       1048576,
		MaxOutputTokens:     384000,
		SupportsToolCalling: true,
		SupportsThinking:    true,
		CompactionRatio:     0.60,
	}

	if spec.Name != "test-model" {
		t.Errorf("Name = %q, want test-model", spec.Name)
	}
	if spec.ProviderID != "deepseek" {
		t.Errorf("ProviderID = %q, want deepseek", spec.ProviderID)
	}
	if spec.ContextWindow != 1048576 {
		t.Errorf("ContextWindow = %d, want 1048576", spec.ContextWindow)
	}
	if spec.MaxOutputTokens != 384000 {
		t.Errorf("MaxOutputTokens = %d, want 384000", spec.MaxOutputTokens)
	}
	if !spec.SupportsToolCalling {
		t.Error("SupportsToolCalling should be true")
	}
	if !spec.SupportsThinking {
		t.Error("SupportsThinking should be true")
	}
	if spec.CompactionRatio != 0.60 {
		t.Errorf("CompactionRatio = %f, want 0.60", spec.CompactionRatio)
	}
}

func TestNewDefaultRegistry(t *testing.T) {
	reg := provider.NewDefaultRegistry()
	if reg == nil {
		t.Fatal("expected non-nil default registry")
	}

	t.Run("resolve deepseek deepseek-flash 2026 spec", func(t *testing.T) {
		spec := reg.ResolveModel("deepseek", "deepseek-flash")
		if spec.ContextWindow != 1048576 {
			t.Errorf("deepseek-flash ContextWindow = %d, want 1048576", spec.ContextWindow)
		}
		if spec.MaxOutputTokens != 384000 {
			t.Errorf("deepseek-flash MaxOutputTokens = %d, want 384000", spec.MaxOutputTokens)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("deepseek-flash CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
		if !spec.SupportsToolCalling {
			t.Error("deepseek-flash must support tool calling")
		}
		if !spec.SupportsThinking {
			t.Error("deepseek-flash must support thinking mode")
		}
	})

	t.Run("resolve deepseek deepseek-v4-pro 2026 spec", func(t *testing.T) {
		spec := reg.ResolveModel("deepseek", "deepseek-v4-pro")
		if spec.ContextWindow != 1048576 {
			t.Errorf("deepseek-v4-pro ContextWindow = %d, want 1048576", spec.ContextWindow)
		}
		if spec.MaxOutputTokens != 384000 {
			t.Errorf("deepseek-v4-pro MaxOutputTokens = %d, want 384000", spec.MaxOutputTokens)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("deepseek-v4-pro CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
		if !spec.SupportsToolCalling {
			t.Error("deepseek-v4-pro must support tool calling")
		}
	})

	t.Run("resolve deepseek deepseek-chat legacy alias", func(t *testing.T) {
		spec := reg.ResolveModel("deepseek", "deepseek-chat")
		if spec.ContextWindow != 1048576 {
			t.Errorf("deepseek-chat ContextWindow = %d, want 1048576", spec.ContextWindow)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("deepseek-chat CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
	})

	t.Run("resolve ollama qwen3.5:4b", func(t *testing.T) {
		spec := reg.ResolveModel("ollama", "qwen3.5:4b")
		if spec.ContextWindow != 32768 {
			t.Errorf("qwen3.5:4b ContextWindow = %d, want 32768", spec.ContextWindow)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("qwen3.5:4b CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
		if !spec.SupportsToolCalling {
			t.Error("qwen3.5:4b must support tool calling")
		}
	})

	t.Run("resolve openrouter provider", func(t *testing.T) {
		p, ok := reg.Get("openrouter")
		if !ok || p == nil {
			t.Fatal("expected openrouter provider to be registered")
		}
		spec := reg.ResolveModel("openrouter", "deepseek/deepseek-chat")
		if spec.ProviderID != "openrouter" {
			t.Errorf("ProviderID = %q, want openrouter", spec.ProviderID)
		}
		if spec.ContextWindow != 1048576 {
			t.Errorf("ContextWindow = %d, want 1048576", spec.ContextWindow)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
	})

	t.Run("resolve custom provider", func(t *testing.T) {
		p, ok := reg.Get("custom")
		if !ok || p == nil {
			t.Fatal("expected custom provider to be registered")
		}
		spec := reg.ResolveModel("custom", "my-custom-model")
		if spec.ProviderID != "custom" {
			t.Errorf("ProviderID = %q, want custom", spec.ProviderID)
		}
		if spec.Name != "my-custom-model" {
			t.Errorf("Name = %q, want my-custom-model", spec.Name)
		}
		if spec.ContextWindow != 32768 {
			t.Errorf("ContextWindow = %d, want 32768", spec.ContextWindow)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
	})

	t.Run("resolve unknown provider fallback", func(t *testing.T) {
		spec := reg.ResolveModel("unknown-upstream", "some-model")
		if spec.ContextWindow <= 0 {
			t.Errorf("expected positive ContextWindow fallback, got %d", spec.ContextWindow)
		}
		if spec.CompactionRatio != 0.60 {
			t.Errorf("CompactionRatio = %f, want 0.60", spec.CompactionRatio)
		}
	})
}

func TestRegistryRegistrationValidation(t *testing.T) {
	reg := provider.NewRegistry()

	if err := reg.Register(nil); err == nil {
		t.Fatal("expected error registering nil provider")
	}

	mockP := provider.NewCustomProvider()
	if err := reg.Register(mockP); err != nil {
		t.Fatalf("failed to register provider: %v", err)
	}

	// 重复注册应返回错误
	if err := reg.Register(mockP); err == nil {
		t.Fatal("expected error registering duplicate provider")
	}
}

func TestRegistryConcurrentAccess(t *testing.T) {
	reg := provider.NewDefaultRegistry()
	var wg sync.WaitGroup

	// 并发 50 个 reader / resolver
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			models := []string{"deepseek-flash", "deepseek-v4-pro", "deepseek-chat", "qwen3.5:4b", "custom-model"}
			providerIDs := []string{"deepseek", "ollama", "openrouter", "custom", "unknown"}

			for j := 0; j < 20; j++ {
				pID := providerIDs[(idx+j)%len(providerIDs)]
				m := models[(idx+j)%len(models)]

				_ = reg.ResolveModel(pID, m)
				_, _ = reg.Get(pID)
			}
		}(i)
	}

	// 并发若干 writer 注册动态自定义 Provider
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			dynID := fmt.Sprintf("dynamic-%d", idx)
			_ = reg.Register(provider.NewDynamicCustomProvider(dynID, fmt.Sprintf("Dynamic %d", idx)))
			_, _ = reg.Get(dynID)
		}(i)
	}

	wg.Wait()
}
