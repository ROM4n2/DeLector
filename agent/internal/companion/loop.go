package companion

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/sashabaranov/go-openai"
)

const (
	DefaultMaxTurns = 3
	DefaultModel    = "deepseek-chat"

	CompanionSystemPrompt = `你是 DeLector 德语研读系统的伴学导学伙伴「Eule」（猫头鹰博士）。
你的任务是为备考歌德/德福的德语学习者提供针对性的语用深挖、句法结构问诊与生词卡提议。
你可以调用以下工具辅助语言学分析：
- analyze: 依存语法与五领域结构分析
- writing_check: 考试写作规则检验
- vocab_stats: 词汇 CEFR 等级分布
- propose_vocab_cards: 向学习者提议将核心生词制作生词卡并存入本地复习卡盒（需由学习者显式确认）

解答风格要求：
- 请使用自然流畅、严谨的 Markdown 德式学术排版风格直接回答学习者的问题。
- 如果需要生词制卡提议，请显式调用 propose_vocab_cards 工具，系统会渲染为确认卡片。
- 回答保持精炼、深入，结合学习者正在阅读的德语上下文。`
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
	Messages []Message    `json:"messages"`
	Context  StudyContext `json:"context,omitempty"`
}

// Proposal 对应用户需显式确认的写操作提议。
type Proposal struct {
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
	client *openai.Client
	runner ToolRunner
	model  string
}

// NewCompanionAgent 构造伴学智能体实例。
func NewCompanionAgent(client *openai.Client, runner ToolRunner, model string) *CompanionAgent {
	if model == "" {
		model = DefaultModel
	}
	return &CompanionAgent{
		client: client,
		runner: runner,
		model:  model,
	}
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

	// 2. 有界循环：最多 DEFAULT_MAX_TURNS 轮
	for turn := 1; turn <= DefaultMaxTurns; turn++ {
		select {
		case <-ctx.Done():
			_ = emit(Event{Event: EventDone, Turns: turn, Reason: "cancelled"})
			return &Outcome{Status: "cancelled", Text: fullContent.String(), Reason: "cancelled"}, ctx.Err()
		default:
		}

		compactedMsgs := CompactMessages(chatMessages, DefaultContextMaxChars)
		streamReq := openai.ChatCompletionRequest{
			Model:      a.model,
			Messages:   compactedMsgs,
			Tools:      tools,
			ToolChoice: "auto",
			Stream:     true,
		}

		stream, err := a.client.CreateChatCompletionStream(ctx, streamReq)
		if err != nil {
			errStr := fmt.Sprintf("调用模型失败: %v", err)
			_ = emit(Event{Event: EventError, Code: "upstream_error", MessageZH: errStr})
			_ = emit(Event{Event: EventDone, Turns: turn, Reason: "error"})
			return &Outcome{Status: "error", Text: errStr, Reason: "error"}, err
		}

		var (
			turnContent    strings.Builder
			turnReasoning  strings.Builder
			turnToolCalls  = make(map[int]*openai.ToolCall)
			hadReasoning   = false
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
				return &Outcome{Status: "error", Text: errStr, Reason: "error"}, recvErr
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
			for _, tc := range delta.ToolCalls {
				idx := 0
				if tc.Index != nil {
					idx = *tc.Index
				}
				existing, ok := turnToolCalls[idx]
				if !ok {
					newCall := tc
					turnToolCalls[idx] = &newCall
				} else {
					if tc.ID != "" {
						existing.ID = tc.ID
					}
					if tc.Function.Name != "" {
						existing.Function.Name += tc.Function.Name
					}
					if tc.Function.Arguments != "" {
						existing.Function.Arguments += tc.Function.Arguments
					}
				}
			}
		}
		stream.Close()

		// 3. 判断本轮是否有工具调用
		if len(turnToolCalls) == 0 {
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

		// 4. 执行本轮工具调用
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
			if tc, ok := turnToolCalls[i]; ok {
				callsList = append(callsList, *tc)
			}
		}
		assistantMsg.ToolCalls = callsList
		chatMessages = append(chatMessages, assistantMsg)

		for _, tc := range callsList {
			name := tc.Function.Name
			var payload map[string]any
			var parseErr error
			if err := json.Unmarshal([]byte(tc.Function.Arguments), &payload); err != nil {
				parseErr = err
				payload = map[string]any{"raw": tc.Function.Arguments}
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
					"raw":        tc.Function.Arguments,
					"hint":       "请确保为该工具传入合法 JSON 格式的对象参数。",
				}
				_ = emit(Event{
					Event:  EventToolEnd,
					Tool:   name,
					Result: toolRes,
				})
				resBytes, _ := json.Marshal(toolRes)
				chatMessages = append(chatMessages, openai.ChatCompletionMessage{
					Role:       openai.ChatMessageRoleTool,
					ToolCallID: tc.ID,
					Content:    string(resBytes),
				})
				continue
			}

			if name == "propose_vocab_cards" {
				title, _ := payload["title"].(string)
				if title == "" {
					title = "加入核心生词卡"
				}
				prop := Proposal{
					Action:  "create_vocab_cards",
					Title:   title,
					Payload: payload,
				}
				proposals = append(proposals, prop)
				_ = emit(Event{
					Event:   EventProposal,
					Action:  prop.Action,
					Title:   prop.Title,
					Payload: prop.Payload,
				})

				// 提议工具直接反馈成功标记
				chatMessages = append(chatMessages, openai.ChatCompletionMessage{
					Role:       openai.ChatMessageRoleTool,
					ToolCallID: tc.ID,
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

				_ = emit(Event{
					Event:  EventToolEnd,
					Tool:   name,
					Result: toolRes,
				})

				resBytes, _ := json.Marshal(toolRes)
				chatMessages = append(chatMessages, openai.ChatCompletionMessage{
					Role:       openai.ChatMessageRoleTool,
					ToolCallID: tc.ID,
					Content:    string(resBytes),
				})
			}
		}
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
