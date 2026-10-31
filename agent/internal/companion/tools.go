package companion

import (
	"github.com/sashabaranov/go-openai"
)

// EventType 定义前端伴学抽屉与 SSE 流式契约一致的事件类型。
type EventType string

const (
	EventDelta     EventType = "delta"
	EventThought   EventType = "thought"
	EventToolStart EventType = "tool_start"
	EventToolEnd   EventType = "tool_end"
	EventProposal  EventType = "proposal"
	EventDone      EventType = "done"
	EventError     EventType = "error"
)

// Event 封装一次 SSE 下发的规范数据载荷，保持与 cp-api.js 和 check_companion_contract 100% 对齐。
type Event struct {
	Event     EventType      `json:"event"`
	ID        string         `json:"id,omitempty"`
	Text      string         `json:"text,omitempty"`
	Stage     string         `json:"stage,omitempty"`
	Tool      string         `json:"tool,omitempty"`
	Payload   map[string]any `json:"payload,omitempty"`
	Result    map[string]any `json:"result,omitempty"`
	Action    string         `json:"action,omitempty"`
	Title     string         `json:"title,omitempty"`
	Proposal  *Proposal      `json:"proposal,omitempty"`
	Turns     int            `json:"turns,omitempty"`
	Tokens    int            `json:"tokens,omitempty"`
	Reason    string         `json:"reason,omitempty"`
	Code      string         `json:"code,omitempty"`
	MessageZH string         `json:"message_zh,omitempty"`
	Summary   string         `json:"summary,omitempty"`
}

// CompanionTools 返回伴学导学 Agent 允许调用的标准 OpenAI Function Schema 描述清单。
// 包含 3 种诊断/语言学只读工具，以及 1 种制卡提议受控工具。
func CompanionTools() []openai.Tool {
	return []openai.Tool{
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "analyze",
				Description: "对给定的德语句子进行依存语法树拓扑解析与五领域（Vorfeld, Linke Satzklammer, Mittelfeld, Rechte Satzklammer, Nachfeld）结构切分。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"text": map[string]any{
							"type":        "string",
							"description": "待分析的德语句子或短语文本",
						},
					},
					"required": []string{"text"},
				},
			},
		},
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "writing_check",
				Description: "依据歌德/德福德语考试标准，检验句子的正字法拼写、大小写规则、标点符号及从句逗号规范。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"text": map[string]any{
							"type":        "string",
							"description": "待检验的德语篇章或练习句子",
						},
					},
					"required": []string{"text"},
				},
			},
		},
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "vocab_stats",
				Description: "提取德语文本中的词汇元数据，并统计其在欧洲共同语言参考标准（CEFR A1~C2）中的等级分布。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"text": map[string]any{
							"type":        "string",
							"description": "待统计等级的德语文本段落",
						},
					},
					"required": []string{"text"},
				},
			},
		},
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "get_learner_profile",
				Description: "查询当前学习者的德语水平画像、已知词汇总量（FSRS 间隔复习数据库中已掌握词数）、复习负荷及高频易错词根。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"include_weak_roots": map[string]any{
							"type":        "boolean",
							"description": "是否包含薄弱词根列表，默认为 true",
						},
					},
				},
			},
		},
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "query_dictionary",
				Description: "查询 DeLector 本地离线德汉权威词典与动词配价表（德汉释义、动词支配格、前置介词搭配等），严禁编造不存在的搭配。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"lemma": map[string]any{
							"type":        "string",
							"description": "德语单词原型或原形词元（如 anfallen, Buch）",
						},
					},
					"required": []string{"lemma"},
				},
			},
		},
		{
			Type: openai.ToolTypeFunction,
			Function: &openai.FunctionDefinition{
				Name:        "propose_vocab_cards",
				Description: "向学习者提议将文本中的核心生词制作成生词卡（Flashcards）并加入复习卡盒。该操作需学习者显式确认（HITL），绝不可静默入库。",
				Parameters: map[string]any{
					"type": "object",
					"properties": map[string]any{
						"title": map[string]any{
							"type":        "string",
							"description": "提议卡片标题，如「加入核心生词卡」",
						},
						"cards": map[string]any{
							"type":        "array",
							"description": "建议收录的生词条目列表",
							"items": map[string]any{
								"type": "object",
								"properties": map[string]any{
									"word": map[string]any{
										"type":        "string",
										"description": "德语原词（如 der Tisch 或 entscheiden）",
									},
									"lemma": map[string]any{
										"type":        "string",
										"description": "词元原形",
									},
									"definition_zh": map[string]any{
										"type":        "string",
										"description": "精准中文释义与词性",
									},
									"sentence_context": map[string]any{
										"type":        "string",
										"description": "在原句中的上下文例句",
									},
								},
								"required": []string{"word", "definition_zh"},
							},
						},
					},
					"required": []string{"cards"},
				},
			},
		},
	}
}
