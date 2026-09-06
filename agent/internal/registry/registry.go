// Package registry 提供 Go 侧工具注册表：把 Python NLP 微服务的
// POST /api/tools/{name} 契约（经 pythonsvc.Client）封装为可注入、
// 可枚举的 ToolFunc，供 DAG 调度器（internal/dag）与 CLI help 消费。
//
// 依赖方向：registry → pythonsvc（ADR-0008 架构图允许的正向依赖）。
package registry

import (
	"context"
	"errors"
	"fmt"
	"slices"

	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
)

// ErrUnknownTool 哨兵错误：Run 收到未注册的工具名。文案与 Python 侧
// HTTP 404 detail "unknown tool: {name}"（delector/routes/tools.py）对齐，
// 调用方以 errors.Is(err, ErrUnknownTool) 判定，禁字符串比较。
var ErrUnknownTool = errors.New("unknown tool")

// ToolFunc 是工具的统一执行签名：入参 payload、出参结果 dict，
// 与 Python 侧 `async def run(payload: dict) -> dict` 契约同构。
type ToolFunc func(ctx context.Context, payload map[string]any) (map[string]any, error)

// Registry 是工具名 → ToolFunc 的注册表。零值不可用，经 NewRegistry 构造。
type Registry struct {
	tools map[string]ToolFunc
}

// NewRegistry 构造空 Registry。
func NewRegistry() *Registry {
	return &Registry{tools: make(map[string]ToolFunc)}
}

// Register 注册名为 name 的工具。重名、空名或 nil fn 均返回错误
// （不 panic）：注册冲突属于运行期可恢复错误，由调用方决定处置。
// 被拒的注册不写入表，已注册的实现不受影响。
func (r *Registry) Register(name string, fn ToolFunc) error {
	if name == "" {
		return errors.New("registry: tool name must not be empty")
	}
	if fn == nil {
		return fmt.Errorf("registry: tool %q: fn must not be nil", name)
	}
	if _, exists := r.tools[name]; exists {
		return fmt.Errorf("registry: tool %q already registered", name)
	}
	r.tools[name] = fn
	return nil
}

// List 返回全部已注册工具名，按字典序排序（供 CLI help 稳定输出）。
// 空 Registry 返回非 nil 空切片。
func (r *Registry) List() []string {
	names := make([]string, 0, len(r.tools))
	for name := range r.tools {
		names = append(names, name)
	}
	slices.Sort(names)
	return names
}

// Has 判断工具名是否已注册。
func (r *Registry) Has(name string) bool {
	_, ok := r.tools[name]
	return ok
}

// Run 分发执行已注册工具。未注册名返回 fmt.Errorf("%w: %s", ErrUnknownTool, name)，
// 文案恰为 Python 404 detail 的 "unknown tool: {name}"；工具自身错误原样上抛。
func (r *Registry) Run(ctx context.Context, name string, payload map[string]any) (map[string]any, error) {
	fn, ok := r.tools[name]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownTool, name)
	}
	return fn(ctx, payload)
}

// defaultTools 与 Python 侧 delector/tools/__init__.py 的 TOOL_REGISTRY
// 实况对齐（5 工具；ADR-0009 后 exercise 已更名 writing_check）。
// 新增/更名工具必须同步 ADR-0008 工具表与 registry_test.go 的
// TestDefaultRegistry_Golden 防漂移哨兵。
var defaultTools = [...]string{"ingest", "analyze", "writing_check", "export", "tts"}

// DefaultRegistry 构造预注册 5 个默认工具的 Registry：每个工具都是
// c.RunTool 的薄包装（闭包固定工具名）。预注册名是包级常量，重名只可能
// 是编程错误，故经 mustRegister 构造期快速失败。
func DefaultRegistry(c *pythonsvc.Client) *Registry {
	r := NewRegistry()
	for _, name := range defaultTools {
		r.mustRegister(name, func(ctx context.Context, payload map[string]any) (map[string]any, error) {
			return c.RunTool(ctx, name, payload)
		})
	}
	return r
}

// mustRegister 供 DefaultRegistry 构造期使用：注册失败即 panic
// （预注册名编译期固定，冲突属不变量破坏，须在启动时暴露）。
func (r *Registry) mustRegister(name string, fn ToolFunc) {
	if err := r.Register(name, fn); err != nil {
		panic(err)
	}
}
