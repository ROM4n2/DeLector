package companion

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/provider"
	"github.com/sashabaranov/go-openai"
)

const (
	DefaultMaxTurns = 6
	DefaultModel    = "deepseek-flash"
)

// StudyContext 承载学习者前端当前视口上下文。
type StudyContext struct {
	ArticleTitle  string `json:"article_title,omitempty"`
	CEFRLevel     string `json:"cefr_level,omitempty"`
	SelectedText  string `json:"selected_text,omitempty"`
	SentenceID    string `json:"sentence_id,omitempty"`
	View          string `json:"view,omitempty"`
	ContextSource string `json:"context_source,omitempty"`
	DraftText     string `json:"draft_text,omitempty"`
	CardContext   string `json:"card_context,omitempty"`
}

// Message 表示多轮对话中的一条消息。
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Request 是伴学对话的入参结构。
type Request struct {
	Messages        []Message    `json:"messages"`
	Context         StudyContext `json:"context,omitempty"`
	APIKey          string       `json:"api_key,omitempty"`
	BaseURL         string       `json:"base_url,omitempty"`
	Model           string       `json:"model,omitempty"`
	SessionID       string       `json:"session_id,omitempty"`
	ReasoningEffort string       `json:"reasoning_effort,omitempty"`
}

// Proposal 对应用户需显式确认的写操作提议。
type Proposal struct {
	ID      string         `json:"id,omitempty"`
	Action  string         `json:"action"`
	Title   string         `json:"title"`
	Payload map[string]any `json:"payload"`
}

// Outcome 记录伴学 Agent 循环结束后的终态与交付物。
type Outcome struct {
	Status     string     `json:"status"`
	Text       string     `json:"text"`
	Proposals  []Proposal `json:"proposals"`
	Turns      int        `json:"turns"`
	TokenCount int        `json:"token_count"`
	Reason     string     `json:"reason"`
}

// ToolRunner 定义执行本地微服务工具的最小接口（生产实现由 *pythonsvc.Client 满足）。
type ToolRunner interface {
	RunTool(ctx context.Context, name string, payload map[string]any) (map[string]any, error)
}

// CompanionAgent 统管伴学 Agent 的原生 Tool Calling 循环与流式分发。
type CompanionAgent struct {
	client         *openai.Client
	runner         ToolRunner
	model          string
	registry       *provider.Registry
	fallbackClient *openai.Client
	fallbackModel  string
	pipeline       *TurnPipeline
}

// NewCompanionAgent 构造伴学智能体实例。
func NewCompanionAgent(client *openai.Client, runner ToolRunner, model string) *CompanionAgent {
	if model == "" {
		model = DefaultModel
	}
	return &CompanionAgent{
		client:   client,
		runner:   runner,
		model:    model,
		registry: provider.NewDefaultRegistry(),
		pipeline: NewDefaultTurnPipeline(),
	}
}

// WithRegistry 挂载自定义模型供应商注册中心。
func (a *CompanionAgent) WithRegistry(reg *provider.Registry) *CompanionAgent {
	if reg != nil {
		a.registry = reg
	}
	return a
}

// Registry 获取当前模型供应商注册中心。
func (a *CompanionAgent) Registry() *provider.Registry {
	if a.registry == nil {
		a.registry = provider.NewDefaultRegistry()
	}
	return a.registry
}

// WithFallback 为伴学智能体挂载备用模型客户端（如本地 Ollama 级联热备）。
func (a *CompanionAgent) WithFallback(fallbackClient *openai.Client, fallbackModel string) *CompanionAgent {
	a.fallbackClient = fallbackClient
	a.fallbackModel = fallbackModel
	return a
}

// WithPipeline 挂载自定义 TurnPipeline 中间件链。
func (a *CompanionAgent) WithPipeline(pipeline *TurnPipeline) *CompanionAgent {
	if pipeline != nil {
		a.pipeline = pipeline
	}
	return a
}

// Pipeline 获取当前 TurnPipeline。
func (a *CompanionAgent) Pipeline() *TurnPipeline {
	if a.pipeline == nil {
		a.pipeline = NewDefaultTurnPipeline()
	}
	return a.pipeline
}

// RunLoop 执行原生 Tool Calling 与流式推送有界循环。
func (a *CompanionAgent) RunLoop(ctx context.Context, req Request, emit func(Event) error) (*Outcome, error) {
	if emit == nil {
		emit = func(Event) error { return nil }
	}

	activeClient := a.client
	activeModel := a.model
	if req.Model != "" {
		activeModel = req.Model
	}

	reg := a.Registry()
	spec := reg.ResolveModel(activeModel, req.BaseURL)

	// 1. 构建初始对话消息列表
	chatMessages := buildTurnPrompt(req, spec)

	tools := CompanionTools()
	var (
		proposals   []Proposal
		fullContent strings.Builder
		totalTokens int
	)

	if req.APIKey != "" {
		p, ok := reg.Get(spec.ProviderID)
		if ok && p != nil {
			var err error
			activeClient, err = p.CreateClient(req.APIKey, req.BaseURL)
			if err != nil {
				cfg := openai.DefaultConfig(req.APIKey)
				if req.BaseURL != "" {
					cfg.BaseURL = req.BaseURL
				}
				activeClient = openai.NewClientWithConfig(cfg)
			}
		} else {
			cfg := openai.DefaultConfig(req.APIKey)
			if req.BaseURL != "" {
				cfg.BaseURL = req.BaseURL
			}
			activeClient = openai.NewClientWithConfig(cfg)
		}
	}

	// 2. 有界循环：最多 DEFAULT_MAX_TURNS 轮
	for turn := 1; turn <= DefaultMaxTurns; turn++ {
		select {
		case <-ctx.Done():
			_ = emit(Event{Event: EventDone, Turns: turn, Reason: "cancelled"})
			return &Outcome{Status: "cancelled", Text: fullContent.String(), Reason: "cancelled"}, ctx.Err()
		default:
		}

		tc := &TurnContext{
			Ctx:              ctx,
			Turn:             turn,
			MaxTurns:         DefaultMaxTurns,
			Req:              req,
			Spec:             spec,
			Messages:         chatMessages,
			FullContent:      &fullContent,
			HadToolExecution: false,
			Emit:             emit,
		}

		coreFn := func() error {
			received, err := a.receiveTurn(ctx, tc, turn, activeClient, activeModel, tools, emit, &fullContent)
			if err != nil {
				return err
			}
			// 3. 判断本轮是否有工具调用
			if len(received.toolCalls) == 0 {
				tc.HadToolExecution = false
				return nil
			}

			// 4. 执行本轮工具调用
			proposals = append(proposals, a.executeToolCalls(ctx, tc, received, emit)...)
			return nil
		}

		execErr := a.Pipeline().Execute(tc, coreFn)
		if execErr != nil {
			return &Outcome{Status: "error", Text: fullContent.String(), Reason: "error"}, execErr
		}

		if !tc.HadToolExecution {
			// 模型未调用任何工具，已完成回答
			return finalize(emit, &fullContent, proposals, turn, totalTokens, "ok"), nil
		}

		chatMessages = tc.Messages
	}

	return finalize(emit, &fullContent, proposals, DefaultMaxTurns, totalTokens, "turn_limit"), nil
}

func (a *CompanionAgent) executeToolCalls(ctx context.Context, tc *TurnContext, received *receivedTurn, emit func(Event) error) []Proposal {
	tc.HadToolExecution = true
	assistantMsg := openai.ChatCompletionMessage{
		Role: openai.ChatMessageRoleAssistant,
	}
	if received.content.Len() > 0 {
		assistantMsg.Content = received.content.String()
	}
	if received.hadReasoning {
		assistantMsg.ReasoningContent = received.reasoning.String()
	}

	callsList := FilterValidToolCalls(received.toolCalls)
	assistantMsg.ToolCalls = callsList
	tc.Messages = append(tc.Messages, assistantMsg)

	var proposals []Proposal
	for _, tcCall := range callsList {
		name := tcCall.Function.Name
		var payload map[string]any
		var parseErr error
		if err := json.Unmarshal([]byte(tcCall.Function.Arguments), &payload); err != nil {
			parseErr = err
			payload = map[string]any{"raw": tcCall.Function.Arguments}
		}

		_ = emit(Event{
			Event:   EventToolStart,
			Tool:    name,
			Payload: payload,
		})

		if parseErr != nil {
			// Pi-Agent Errors-as-Messages: 参数解析失败直接作为 Tool 错误消息反馈
			resJSON := FormatToolArgErrorMessage(name, tcCall.Function.Arguments, parseErr)
			var toolRes map[string]any
			_ = json.Unmarshal([]byte(resJSON), &toolRes)
			_ = emit(Event{
				Event:  EventToolEnd,
				Tool:   name,
				Result: toolRes,
			})
			tc.Messages = append(tc.Messages, openai.ChatCompletionMessage{
				Role:       openai.ChatMessageRoleTool,
				ToolCallID: tcCall.ID,
				Content:    resJSON,
			})
			continue
		}

		action := ""
		defaultTitle := ""
		switch name {
		case "propose_vocab_cards":
			action = "create_vocab_cards"
			defaultTitle = "加入核心生词卡"
		case "propose_writing_revision":
			action = "apply_writing_revision"
			defaultTitle = "修订选中句子"
		case "propose_weekly_goal":
			action = "set_weekly_goal"
			defaultTitle = "本周学习目标"
		}
		if action != "" {
			title, _ := payload["title"].(string)
			if title == "" {
				title = defaultTitle
			}
			propID := fmt.Sprintf("prop_%d", time.Now().UnixNano())
			prop := Proposal{
				ID:      propID,
				Action:  action,
				Title:   title,
				Payload: payload,
			}
			proposals = append(proposals, prop)
			_ = emit(Event{
				Event:    EventProposal,
				ID:       propID,
				Action:   prop.Action,
				Title:    prop.Title,
				Payload:  prop.Payload,
				Proposal: &prop,
			})

			// 提议工具直接反馈成功标记
			tc.Messages = append(tc.Messages, openai.ChatCompletionMessage{
				Role:       openai.ChatMessageRoleTool,
				ToolCallID: tcCall.ID,
				Content:    `{"status":"ok","message":"proposal presented to user"}`,
			})
		} else {
			// 本地 Python 诊断工具（analyze / writing_check / vocab_stats）
			toolRes, toolErr := a.runner.RunTool(ctx, name, payload)
			if toolErr != nil {
				// Pi-Agent Errors-as-Messages 原则：工具错误转化为结构化消息送回模型自愈
				resJSON := FormatToolErrorMessage(name, toolErr)
				toolRes = nil
				_ = json.Unmarshal([]byte(resJSON), &toolRes)
			}

			summary := "完成数据提取"
			if toolErr != nil {
				summary = fmt.Sprintf("执行受阻: %v", toolErr)
			}
			_ = emit(Event{
				Event:   EventToolEnd,
				Tool:    name,
				Result:  toolRes,
				Summary: summary,
			})

			resBytes, _ := json.Marshal(toolRes)
			tc.Messages = append(tc.Messages, openai.ChatCompletionMessage{
				Role:       openai.ChatMessageRoleTool,
				ToolCallID: tcCall.ID,
				Content:    string(resBytes),
			})
		}
	}
	return proposals
}

type receivedTurn struct {
	content      strings.Builder
	reasoning    strings.Builder
	toolCalls    map[int]*openai.ToolCall
	hadReasoning bool
}

func (a *CompanionAgent) receiveTurn(
	ctx context.Context,
	tc *TurnContext,
	turn int,
	activeClient *openai.Client,
	activeModel string,
	tools []openai.Tool,
	emit func(Event) error,
	fullContent *strings.Builder,
) (*receivedTurn, error) {
	streamReq := openai.ChatCompletionRequest{
		Model:      activeModel,
		Messages:   tc.Messages,
		Tools:      tools,
		ToolChoice: "auto",
		Stream:     true,
	}

	if activeClient == nil {
		errStr := "未配置任何可用的 LLM 模型客户端或 API Key"
		_ = emit(Event{Event: EventError, Code: "missing_client", MessageZH: errStr})
		_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
		if fullContent.Len() == 0 {
			fullContent.WriteString(errStr)
		}
		return nil, fmt.Errorf("%s", errStr)
	}

	stream, err := activeClient.CreateChatCompletionStream(ctx, streamReq)
	if err != nil && a.fallbackClient != nil {
		primaryErr := err
		_ = emit(Event{
			Event: EventThought,
			Text:  "主通道不可达，正在级联切换至备用模型...",
		})
		fallbackReq := streamReq
		if a.fallbackModel != "" {
			fallbackReq.Model = a.fallbackModel
		}
		stream, err = a.fallbackClient.CreateChatCompletionStream(ctx, fallbackReq)
		if err != nil {
			errStr := fmt.Sprintf("主通道失败 (%v)；备用模型 (%s) 不可达 (%v)", primaryErr, fallbackReq.Model, err)
			_ = emit(Event{Event: EventError, Code: "upstream_error", MessageZH: errStr})
			_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
			if fullContent.Len() == 0 {
				fullContent.WriteString(errStr)
			}
			return nil, err
		}
	}
	if err != nil {
		errStr := fmt.Sprintf("调用模型失败: %v", err)
		_ = emit(Event{Event: EventError, Code: "upstream_error", MessageZH: errStr})
		_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
		if fullContent.Len() == 0 {
			fullContent.WriteString(errStr)
		}
		return nil, err
	}

	received := &receivedTurn{toolCalls: make(map[int]*openai.ToolCall)}
	for {
		response, recvErr := stream.Recv()
		if errors.Is(recvErr, io.EOF) {
			break
		}
		if recvErr != nil {
			stream.Close()
			errStr := fmt.Sprintf("流式读取异常: %v", recvErr)
			_ = emit(Event{Event: EventError, Code: "stream_error", MessageZH: errStr})
			_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
			if fullContent.Len() == 0 {
				fullContent.WriteString(errStr)
			}
			return nil, recvErr
		}

		if len(response.Choices) == 0 {
			continue
		}
		delta := response.Choices[0].Delta

		// 思考链推送（DeepSeek-R1 / Reasoner 原生字段）
		if delta.ReasoningContent != "" {
			received.hadReasoning = true
			received.reasoning.WriteString(delta.ReasoningContent)
			_ = emit(Event{
				Event: EventThought,
				Text:  delta.ReasoningContent,
				Stage: "思考推导",
			})
		}

		// 纯 Markdown 正文流推送（零 JSON 封装）
		if delta.Content != "" {
			received.content.WriteString(delta.Content)
			fullContent.WriteString(delta.Content)
			_ = emit(Event{
				Event: EventDelta,
				Text:  delta.Content,
			})
		}

		// 原生 Tool Calls 增量分片聚合
		for _, tcCall := range delta.ToolCalls {
			received.toolCalls = AggregateToolCalls(received.toolCalls, tcCall)
		}
	}
	stream.Close()
	return received, nil
}

func buildTurnPrompt(req Request, spec provider.ModelSpec) []openai.ChatCompletionMessage {
	systemContent := BuildSystemPrompt(FormatStudyContext(req.Context), spec)
	messages := []openai.ChatCompletionMessage{
		{
			Role:    openai.ChatMessageRoleSystem,
			Content: systemContent,
		},
	}
	for _, message := range req.Messages {
		messages = append(messages, openai.ChatCompletionMessage{
			Role:    message.Role,
			Content: message.Content,
		})
	}
	return messages
}

func finalize(emit func(Event) error, fullContent *strings.Builder, proposals []Proposal, turns, totalTokens int, reason string) *Outcome {
	if reason == "turn_limit" {
		cleanedText := strings.TrimSpace(fullContent.String())
		if cleanedText == "?" || cleanedText == "？" || cleanedText == "." || cleanedText == "。" || cleanedText == "..." || cleanedText == "" {
			fallbackText := BuildPromptNudge()
			_ = emit(Event{
				Event: EventDelta,
				Text:  fallbackText,
			})
			fullContent.Reset()
			fullContent.WriteString(fallbackText)
		}
	}

	_ = emit(Event{
		Event:  EventDone,
		Turns:  turns,
		Tokens: totalTokens,
		Reason: reason,
	})
	return &Outcome{
		Status:     "ok",
		Text:       fullContent.String(),
		Proposals:  proposals,
		Turns:      turns,
		TokenCount: totalTokens,
		Reason:     reason,
	}
}
