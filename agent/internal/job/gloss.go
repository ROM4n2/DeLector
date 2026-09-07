// gloss.go 承载 job#1 的 gloss 步骤核心：把语料正文抽样 + vocab_stats 未知词
// 列表构建成一份 DeepSeek「分级 + 逐词中文释义」的 prompt，并容错解析其返回
// 的严格 JSON 为 GlossResult。LLM 经 GlossLLM 接口抽象，便于单测用 stub/httptest
// 桩注入，绝不直连生产（Global Constraints：测试一律 stub）。
package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"unicode"

	"github.com/ROM4n2/DeLector/agent/internal/llm"
)

// ---- GlossLLM 抽象 ---------------------------------------------------------

// GlossLLM 是 gloss 步骤依赖的最小 LLM 能力：一次 system+user 补全。真实实现是
// *llm.Client；测试用 stub 或 httptest 桩实现，避免任何真外呼。
type GlossLLM interface {
	Complete(ctx context.Context, system, user string, opts ...llm.Option) (string, error)
}

// ---- 请求 / 结果 -----------------------------------------------------------

// GlossRequest 描述一次定级/释义调用所需的全部输入。
type GlossRequest struct {
	// Text 是正文前若干段抽样（防超长：按词截断至 sampleMaxWords 词 ≈ ~1200 token）。
	Text string
	// UnknownLemmas 来自 vocab_stats 的未知词列表（封顶 60），是本次要释义的对象。
	UnknownLemmas []LemmaCount
	// KnownRate 是已知词覆盖率（0..1），供模型定级时参考（对应 vocab_stats.known_rate）。
	KnownRate float64
}

// GlossResult 是 LLM 返回解析后的结构化结果。json 标签即 DeepSeek 应回吐的键。
type GlossResult struct {
	// EstimatedCEFR 是对正文的整体定级，归一后为 A1|A2|B1。
	EstimatedCEFR string `json:"estimated_cefr"`
	// Glosses 是逐词释义条目（lemma+gloss_zh+cefr+pos，CEFR 归一）。
	Glosses []PackGloss `json:"glosses"`
}

// ---- 文本抽样与估算（供 prompt 与预算复用） ----------------------------------

// sampleMaxWords 是送进 prompt 的正文抽样词数上限。启发式与文档依据：
//
//	计划目标 "按词截断 ~1200 token"；德语平均 ~1.5 token/词（复合长词偏多），
//	故 800 词 ≈ 1200 token 为保守上界，避免 prompt 超模型窗口并守住 token 预算。
//
// 定长截断保证确定性，可测试。
const sampleMaxWords = 800

// SampleText 返回 text 前若干词（以 Unicode 空白切分）的抽样串。超过 sampleMaxWords
// 词即截断并去掉首尾多余空白；不足则原样返回。空文本返回空串。
func SampleText(text string) string {
	words := strings.FieldsFunc(text, func(r rune) bool { return unicode.IsSpace(r) })
	if len(words) > sampleMaxWords {
		words = words[:sampleMaxWords]
	}
	return strings.Join(words, " ")
}

// EstimateTokens 估算一次文本约消耗的 token 数，供调用方在每次 LLM 调用前
// budget.Reserve。公式（确定性、偏保守上估）：
//
//	EstimateTokens(s) = len(s)/4 + 词数
//
// 依据：中文/西文混排下约 4 字符 ≈ 1 token（计划全局 chars/4 估算），再按每词加 1
// 弥补德语分词与标点开销。空文本返回 0。
func EstimateTokens(text string) int {
	if text == "" {
		return 0
	}
	words := strings.FieldsFunc(text, func(r rune) bool { return unicode.IsSpace(r) })
	return len(text)/4 + len(words)
}

// ---- BuildGlossPrompt ------------------------------------------------------

// BuildGlossPrompt 组装 DeepSeek 定级/释义调用的 system+user 提示：
//   - system：严格要求只输出单一 JSON 对象（附可解析示例 + 禁多余文本/围栏外散文）；
//   - user：正文抽样 + known_rate + 待释义 lemma 列表 + 输出示例。
//
// 返回的 system/user 均非空；正文抽样遵循 SampleText 词数上限。
func BuildGlossPrompt(r GlossRequest) (system, user string) {
	// 注意：不得在字面量中出现反引号（会切断 Go 原始串）；改用可解析的 markdown
	// 代码围栏描述，不写死反引号符号。
	system = `你是德语分级与生词释义引擎。你只输出一个 JSON 对象，不要输出任何 JSON 之外
的文字、解释或问候。如用 markdown 代码围栏，则整个 JSON 必须完整包在围栏内；
围栏外不得有任何散文。对象结构严格为：
{"estimated_cefr":"A1|A2|B1","glosses":[{"lemma":"单词原形","gloss_zh":"中文释义","cefr":"A1|A2|B1","pos":"词性(可选,如 VERB/ADJ/NOUN)"}]}

规则：
- estimated_cefr 只允许 A1/A2/B1 之一，代表整篇正文的难度定级。
- glosses 数组对 user 提供的每个 lemma 逐条给出条目；每条约含：lemma（原形，必填）、
  gloss_zh（中文释义，可空）、cefr（该词难度，仅 A1/A2/B1）、pos（词性，可空）。
- 未知词不足或有歧义时按上下文合理推断，不要省略。
返回必须是合法 JSON。严格 JSON。`

	// 抽样正文（词数上限已保证）。
	sampled := SampleText(r.Text)

	var sb strings.Builder
	fmt.Fprintf(&sb, "正文难度定级请综合已知词覆盖率。known_rate=%.2f（0..1）。\n", r.KnownRate)
	sb.WriteString("正文（抽样）：\n")
	if sampled == "" {
		sb.WriteString("（无正文）\n")
	} else {
		sb.WriteString(sampled)
		sb.WriteString("\n")
	}
	sb.WriteString("\n请为下列未知词逐条给出中文释义与难度（lemma 依此列表）：\n")
	for _, lc := range r.UnknownLemmas {
		fmt.Fprintf(&sb, "- %s\n", lc.Lemma)
	}
	sb.WriteString("\n输出示例（仅作格式示范）：\n")
	sb.WriteString(`{"estimated_cefr":"A2","glosses":[{"lemma":"laufen","gloss_zh":"奔跑","cefr":"A1","pos":"VERB"}]}`)
	return system, sb.String()
}

// ---- ParseGlossLLMOutput ---------------------------------------------------

// normalizeCEFR 把等级值归一为 A1|A2|B1（trim+upper），返回是否合法。空值归一
// 为 A2（镜像 pack.Validate 空值默认 A2 的语义），非白名单返回 false。
func normalizeCEFR(v string) (string, bool) {
	norm := strings.ToUpper(strings.TrimSpace(v))
	if norm == "" {
		return "A2", true
	}
	if !allowedCEFR[norm] {
		return "", false
	}
	return norm, true
}

// ParseGlossLLMOutput 容错解析 LLM 返回为 GlossResult：
//   - 剥离 ```json / ``` 围栏（两种都处理）与首尾空白；
//   - json.Unmarshal 成 GlossResult（坏 JSON / 纯散文报错）；
//   - estimated_cefr 归一（空→A2，非白名单报错）；
//   - 逐条校验 glosses：lemma 非空白（必填），cefr 归一（空→A2，非白名单报错）；
//     gloss_zh 与 pos 可空，不强制。
//
// 空 glosses 列表合法（镜像 Pack.Validate 允许 glosses 为空）。
func ParseGlossLLMOutput(raw string) (GlossResult, error) {
	var res GlossResult
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return res, fmt.Errorf("job: gloss LLM 输出为空")
	}
	// 剥 markdown 围栏：```json\n...\n``` 或 ```\n...\n```。
	lower := strings.ToLower(trimmed)
	if strings.HasPrefix(lower, "```") {
		trimmed = strings.TrimPrefix(trimmed, "```")
		// 去掉围栏语言标记（可选）后的整行。
		if idx := strings.IndexByte(trimmed, '\n'); idx >= 0 {
			trimmed = trimmed[idx+1:]
		} else if idx := strings.IndexByte(trimmed, '\r'); idx >= 0 {
			trimmed = trimmed[idx+1:]
		}
		// 去尾部 ```。
		if i := strings.LastIndex(trimmed, "```"); i >= 0 {
			trimmed = trimmed[:i]
		}
		trimmed = strings.TrimSpace(trimmed)
	}

	if err := json.Unmarshal([]byte(trimmed), &res); err != nil {
		return res, fmt.Errorf("job: gloss LLM 输出不是合法 JSON: %w", err)
	}

	cefr, ok := normalizeCEFR(res.EstimatedCEFR)
	if !ok {
		return res, fmt.Errorf("job: gloss estimated_cefr 仅支持 A1/A2/B1，收到 %q", res.EstimatedCEFR)
	}
	res.EstimatedCEFR = cefr

	for i := range res.Glosses {
		g := &res.Glosses[i]
		if strings.TrimSpace(g.Lemma) == "" {
			return res, fmt.Errorf("job: glosses[%d].lemma 必填且不能为空", i)
		}
		cefr, ok := normalizeCEFR(g.CEFR)
		if !ok {
			return res, fmt.Errorf("job: glosses[%d].cefr 仅支持 A1/A2/B1，收到 %q", i, g.CEFR)
		}
		g.CEFR = cefr
		g.Lemma = strings.TrimSpace(g.Lemma)
	}
	return res, nil
}
