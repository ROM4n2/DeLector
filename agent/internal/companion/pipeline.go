package companion

import (
	"context"
	"strings"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

// TurnContext 承载单轮 Agent 执行的瞬时上下文与可变状态。
type TurnContext struct {
	Ctx              context.Context
	Turn             int
	MaxTurns         int
	Req              Request
	Spec             provider.ModelSpec
	Messages         []openai.ChatCompletionMessage
	FullContent      *strings.Builder
	HadToolExecution bool
	Emit             func(Event) error

	// 执行指标（支持中间件与核心执行体覆写或度量）
	TokensIn  int
	TokensOut int
	ToolCount int
}

// TurnMiddleware 定义伴学单轮执行拦截中间件签名。
type TurnMiddleware func(tc *TurnContext, next func() error) error

// TurnPipeline 统管单轮对话中间件洋葱模型的装配与链式执行。
type TurnPipeline struct {
	middlewares []TurnMiddleware
}

// NewTurnPipeline 创建空的 TurnPipeline 实例。
func NewTurnPipeline() *TurnPipeline {
	return &TurnPipeline{
		middlewares: make([]TurnMiddleware, 0),
	}
}

// NewDefaultTurnPipeline 构建挂载了标准上下文防护与追踪日志中间件的 TurnPipeline。
func NewDefaultTurnPipeline() *TurnPipeline {
	p := NewTurnPipeline()
	p.Use(ContextGuardMiddleware)
	p.Use(TraceLoggingMiddleware)
	return p
}

// Use 注册一个中间件到执行链尾部。
func (p *TurnPipeline) Use(mw TurnMiddleware) {
	if mw != nil {
		p.middlewares = append(p.middlewares, mw)
	}
}

// Execute 依次以洋葱模型驱动中间件链，最终调用 coreFn。
func (p *TurnPipeline) Execute(tc *TurnContext, coreFn func() error) error {
	if coreFn == nil {
		coreFn = func() error { return nil }
	}
	if p == nil || len(p.middlewares) == 0 {
		return coreFn()
	}

	curr := coreFn
	for i := len(p.middlewares) - 1; i >= 0; i-- {
		mw := p.middlewares[i]
		next := curr
		curr = func() error {
			return mw(tc, next)
		}
	}
	return curr()
}

// ContextGuardMiddleware 在下一环节执行前动态执行 Pi 范式 60% 上下文压缩流控。
func ContextGuardMiddleware(tc *TurnContext, next func() error) error {
	if tc != nil {
		tc.Messages = CompactMessagesDynamic(tc.Messages, tc.Spec)
	}
	if next == nil {
		return nil
	}
	return next()
}

// TraceLoggingMiddleware 测量 next() 执行延迟、统计 Token 消耗并落盘 JSONL 追踪记录。
func TraceLoggingMiddleware(tc *TurnContext, next func() error) error {
	start := time.Now()

	var tokensIn int
	initialMsgCount := 0
	initialContentLen := 0

	if tc != nil {
		tokensIn = tc.TokensIn
		if tokensIn == 0 && len(tc.Messages) > 0 {
			tokensIn = EstimateTokens(tc.Messages)
		}
		initialMsgCount = len(tc.Messages)
		if tc.FullContent != nil {
			initialContentLen = tc.FullContent.Len()
		}
	}

	var nextErr error
	if next != nil {
		nextErr = next()
	}

	durationMs := time.Since(start).Milliseconds()

	if tc != nil {
		tokensOut := tc.TokensOut
		if tokensOut == 0 {
			if len(tc.Messages) > initialMsgCount {
				tokensOut = EstimateTokens(tc.Messages[initialMsgCount:])
			} else if tc.FullContent != nil && tc.FullContent.Len() > initialContentLen {
				tokensOut = estimateStringTokens(tc.FullContent.String()[initialContentLen:])
			}
		}

		toolCount := tc.ToolCount
		if toolCount == 0 && len(tc.Messages) > initialMsgCount {
			for _, m := range tc.Messages[initialMsgCount:] {
				toolCount += len(m.ToolCalls)
			}
		}
		if toolCount == 0 && tc.HadToolExecution {
			toolCount = 1
		}

		model := tc.Req.Model
		if model == "" {
			model = tc.Spec.Name
		}
		if model == "" {
			model = DefaultModel
		}

		record := TurnTraceRecord{
			SessionID:       tc.Req.SessionID,
			Turn:            tc.Turn,
			Model:           model,
			ReasoningEffort: tc.Req.ReasoningEffort,
			DurationMs:      durationMs,
			TokensIn:        tokensIn,
			TokensOut:       tokensOut,
			ToolCount:       toolCount,
			Timestamp:       time.Now().UTC().Format(time.RFC3339),
		}
		LogTurnTrace(record)
	}

	return nextErr
}
