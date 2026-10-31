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
	ArticleTitle string `json:"article_title,omitempty"`
	CEFRLevel    string `json:"cefr_level,omitempty"`
	SelectedText string `json:"selected_text,omitempty"`
	SentenceID   string `json:"sentence_id,omitempty"`
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

	// 1. 构建初始对话消息列表
	systemContent := CompanionSystemPrompt
	if req.Context.SelectedText != "" || req.Context.ArticleTitle != "" {
		systemContent += "\n\n【当前学习视口上下文】"
		if req.Context.ArticleTitle != "" {
			systemContent += fmt.Sprintf("\n- 文章: %s", req.Context.ArticleTitle)
		}
		if req.Context.CEFRLevel != "" {
			systemContent += fmt.Sprintf("\n- 目标级别: %s", req.Context.CEFRLevel)
		}
		if req.Context.SelectedText != "" {
			systemContent += fmt.Sprintf("\n- 当前聚焦句子: %s", req.Context.SelectedText)
		}
	}

	chatMessages := []openai.ChatCompletionMessage{
		{
			Role:    openai.ChatMessageRoleSystem,
			Content: systemContent,
		},
	}
	for _, m := range req.Messages {
		chatMessages = append(chatMessages, openai.ChatCompletionMessage{
			Role:    m.Role,
			Content: m.Content,
		})
	}

	tools := CompanionTools()
	var (
		proposals   []Proposal
		fullContent strings.Builder
		totalTokens int
	)

	activeClient := a.client
	activeModel := a.model
	if req.Model != "" {
		activeModel = req.Model
	}

	reg := a.Registry()
	spec := reg.ResolveModel(activeModel, req.BaseURL)

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
				return fmt.Errorf("%s", errStr)
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
					return err
				}
			}
			if err != nil {
				errStr := fmt.Sprintf("调用模型失败: %v", err)
				_ = emit(Event{Event: EventError, Code: "upstream_error", MessageZH: errStr})
				_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
				if fullContent.Len() == 0 {
					fullContent.WriteString(errStr)
				}
				return err
			}

			var (
				turnContent   strings.Builder
				turnReasoning strings.Builder
				turnToolCalls = make(map[int]*openai.ToolCall)
				hadReasoning  = false
			)

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
					return recvErr
				}

				if len(response.Choices) == 0 {
					continue
				}
				delta := response.Choices[0].Delta

				// 思考链推送（DeepSeek-R1 / Reasoner 原生字段）
				if delta.ReasoningContent != "" {
					hadReasoning = true
					turnReasoning.WriteString(delta.ReasoningContent)
					_ = emit(Event{
						Event: EventThought,
						Text:  delta.ReasoningContent,
						Stage: "思考推导",
					})
				}

				// 纯 Markdown 正文流推送（零 JSON 封装）
				if delta.Content != "" {
					turnContent.WriteString(delta.Content)
					fullContent.WriteString(delta.Content)
					_ = emit(Event{
						Event: EventDelta,
						Text:  delta.Content,
					})
				}

				// 原生 Tool Calls 增量分片聚合
				for _, tcCall := range delta.ToolCalls {
					idx := 0
					if tcCall.Index != nil {
						idx = *tcCall.Index
					}
					existing, ok := turnToolCalls[idx]
					if !ok {
						newCall := tcCall
						turnToolCalls[idx] = &newCall
					} else {
						if tcCall.ID != "" {
							existing.ID = tcCall.ID
						}
						if tcCall.Function.Name != "" {
							existing.Function.Name += tcCall.Function.Name
						}
						if tcCall.Function.Arguments != "" {
							existing.Function.Arguments += tcCall.Function.Arguments
						}
					}
				}
			}
			stream.Close()

			// 3. 判断本轮是否有工具调用
			if len(turnToolCalls) == 0 {
				tc.HadToolExecution = false
				return nil
			}

			// 4. 执行本轮工具调用
			tc.HadToolExecution = true
			assistantMsg := openai.ChatCompletionMessage{
				Role: openai.ChatMessageRoleAssistant,
			}
			if turnContent.Len() > 0 {
				assistantMsg.Content = turnContent.String()
			}
			if hadReasoning {
				assistantMsg.ReasoningContent = turnReasoning.String()
			}

			var callsList []openai.ToolCall
			for i := 0; i < len(turnToolCalls); i++ {
				if c, ok := turnToolCalls[i]; ok {
					callsList = append(callsList, *c)
				}
			}
			assistantMsg.ToolCalls = callsList
			tc.Messages = append(tc.Messages, assistantMsg)

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
					toolRes := map[string]any{
						"status":     "error",
						"error_code": "INVALID_TOOL_ARGUMENTS",
						"tool":       name,
						"message":    fmt.Sprintf("工具参数 JSON 解析失败: %v", parseErr),
						"raw":        tcCall.Function.Arguments,
						"hint":       "请确保为该工具传入合法 JSON 格式的对象参数。",
					}
					_ = emit(Event{
						Event:  EventToolEnd,
						Tool:   name,
						Result: toolRes,
					})
					resBytes, _ := json.Marshal(toolRes)
					tc.Messages = append(tc.Messages, openai.ChatCompletionMessage{
						Role:       openai.ChatMessageRoleTool,
						ToolCallID: tcCall.ID,
						Content:    string(resBytes),
					})
					continue
				}

				if name == "propose_vocab_cards" {
					title, _ := payload["title"].(string)
					if title == "" {
						title = "加入核心生词卡"
					}
					propID := fmt.Sprintf("prop_%d", time.Now().UnixNano())
					prop := Proposal{
						ID:      propID,
						Action:  "create_vocab_cards",
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
						toolRes = map[string]any{
							"status":     "error",
							"error_code": "TOOL_EXECUTION_FAILED",
							"tool":       name,
							"message":    toolErr.Error(),
							"hint":       "工具执行暂时失败。请向学习者说明情况并给出基于已有上下文的专业解答，或调整参数重试。",
						}
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
			return nil
		}

		execErr := a.Pipeline().Execute(tc, coreFn)
		if execErr != nil {
			return &Outcome{Status: "error", Text: fullContent.String(), Reason: "error"}, execErr
		}

		if !tc.HadToolExecution {
			// 模型未调用任何工具，已完成回答
			_ = emit(Event{
				Event:  EventDone,
				Turns:  turn,
				Tokens: totalTokens,
				Reason: "ok",
			})
			return &Outcome{
				Status:     "ok",
				Text:       fullContent.String(),
				Proposals:  proposals,
				Turns:      turn,
				TokenCount: totalTokens,
				Reason:     "ok",
			}, nil
		}

		chatMessages = tc.Messages
	}

	cleanedText := strings.TrimSpace(fullContent.String())
	if cleanedText == "?" || cleanedText == "？" || cleanedText == "." || cleanedText == "。" || cleanedText == "..." || cleanedText == "" {
		fallbackText := "已完成对当前句子的多维度语言学推演与分析。请参阅上方提取的语法拓扑信息，如需针对特定成分深入探讨，可随时追问。"
		_ = emit(Event{
			Event: EventDelta,
			Text:  fallbackText,
		})
		fullContent.Reset()
		fullContent.WriteString(fallbackText)
	}

	_ = emit(Event{
		Event:  EventDone,
		Turns:  DefaultMaxTurns,
		Tokens: totalTokens,
		Reason: "turn_limit",
	})
	return &Outcome{
		Status:     "ok",
		Text:       fullContent.String(),
		Proposals:  proposals,
		Turns:      DefaultMaxTurns,
		TokenCount: totalTokens,
		Reason:     "turn_limit",
	}, nil
}
