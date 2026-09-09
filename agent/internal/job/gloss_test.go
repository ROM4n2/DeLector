package job

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/sashabaranov/go-openai"

	"github.com/ROM4n2/DeLector/agent/internal/llm"
)

// ---- ParseGlossLLMOutput -------------------------------------------------

// TestParseGlossLLMOutput_PlainJSON 断言纯 JSON（无围栏）可被解析且字段逐条归一。
func TestParseGlossLLMOutput_PlainJSON(t *testing.T) {
	raw := `{"estimated_cefr":"B1","glosses":[
		{"lemma":"gehen","gloss_zh":"走","cefr":"a1","pos":"VERB"},
		{"lemma":"laufen","gloss_zh":"奔跑","cefr":"B1","pos":""}
	]}`
	res, err := ParseGlossLLMOutput(raw)
	if err != nil {
		t.Fatalf("ParseGlossLLMOutput(plain json): %v", err)
	}
	if res.EstimatedCEFR != "B1" {
		t.Errorf("EstimatedCEFR = %q, want B1", res.EstimatedCEFR)
	}
	if len(res.Glosses) != 2 {
		t.Fatalf("len(glosses) = %d, want 2", len(res.Glosses))
	}
	if res.Glosses[0].Lemma != "gehen" || res.Glosses[0].GlossZH != "走" || res.Glosses[0].CEFR != "A1" || res.Glosses[0].Pos != "VERB" {
		t.Errorf("glosses[0] 解析/归一不符：%+v", res.Glosses[0])
	}
	if res.Glosses[1].Lemma != "laufen" || res.Glosses[1].CEFR != "B1" {
		t.Errorf("glosses[1] 解析/归一不符：%+v", res.Glosses[1])
	}
}

// TestParseGlossLLMOutput_JSONFence 断言 ```json 围栏与首尾空白被剥离后仍可解析。
func TestParseGlossLLMOutput_JSONFence(t *testing.T) {
	raw := "\n```json\n{\"estimated_cefr\":\"A2\",\"glosses\":[{\"lemma\":\"Haus\",\"gloss_zh\":\"房子\",\"cefr\":\"A1\"}]}\n```\n"
	res, err := ParseGlossLLMOutput(raw)
	if err != nil {
		t.Fatalf("ParseGlossLLMOutput(fenced json): %v", err)
	}
	if res.EstimatedCEFR != "A2" || len(res.Glosses) != 1 || res.Glosses[0].Lemma != "Haus" {
		t.Errorf("围栏剥离后解析不符：%+v", res)
	}
}

// TestParseGlossLLMOutput_BareFence 断言不带语言的 ``` 围栏同样被剥离。
func TestParseGlossLLMOutput_BareFence(t *testing.T) {
	raw := "```\n{\"estimated_cefr\":\"A1\",\"glosses\":[{\"lemma\":\"gut\",\"cefr\":\"A1\"}]}\n```"
	res, err := ParseGlossLLMOutput(raw)
	if err != nil {
		t.Fatalf("ParseGlossLLMOutput(bare fence): %v", err)
	}
	if res.EstimatedCEFR != "A1" {
		t.Errorf("EstimatedCEFR = %q, want A1", res.EstimatedCEFR)
	}
}

// TestParseGlossLLMOutput_BadJSON 断言畸形 JSON 报错。
func TestParseGlossLLMOutput_BadJSON(t *testing.T) {
	_, err := ParseGlossLLMOutput("this is not json at all {{{")
	if err == nil {
		t.Fatal("ParseGlossLLMOutput(bad json): got nil error, want error")
	}
}

// TestParseGlossLLMOutput_ProseOnly 断言 LLM 误吐纯文本（无 JSON 结构）报错而非误收。
func TestParseGlossLLMOutput_ProseOnly(t *testing.T) {
	_, err := ParseGlossLLMOutput("以下是分级结果，正文以自然语言描述，不含 JSON。")
	if err == nil {
		t.Fatal("ParseGlossLLMOutput(prose): got nil error, want error")
	}
}

// TestParseGlossLLMOutput_EstimatedCEFRWrong 断言 estimated_cefr 不在白名单时报错。
func TestParseGlossLLMOutput_EstimatedCEFRWrong(t *testing.T) {
	for _, v := range []string{"C1", "C2", "B2", "xx"} {
		raw := `{"estimated_cefr":"` + v + `","glosses":[{"lemma":"a","cefr":"A1"}]}`
		if _, err := ParseGlossLLMOutput(raw); err == nil {
			t.Errorf("estimated_cefr=%q 不在白名单应报错", v)
		}
	}
}

// TestParseGlossLLMOutput_MissingGlossLemma 断言 gloss 缺 lemma（空白）时报错。
func TestParseGlossLLMOutput_MissingGlossLemma(t *testing.T) {
	for _, raw := range []string{
		`{"estimated_cefr":"A1","glosses":[{"gloss_zh":"走","cefr":"A1"}]}`,
		`{"estimated_cefr":"A1","glosses":[{"lemma":"  ","gloss_zh":"走","cefr":"A1"}]}`,
	} {
		if _, err := ParseGlossLLMOutput(raw); err == nil {
			t.Errorf("gloss 缺 lemma 应报错，raw=%s", raw)
		}
	}
}

// TestParseGlossLLMOutput_GlossCEFRWrong 断言逐条 gloss 的 cefr 不在白名单时报错。
func TestParseGlossLLMOutput_GlossCEFRWrong(t *testing.T) {
	raw := `{"estimated_cefr":"A1","glosses":[{"lemma":"gehen","gloss_zh":"走","cefr":"C1"}]}`
	if _, err := ParseGlossLLMOutput(raw); err == nil {
		t.Error("gloss.cefr=C1 不在白名单应报错")
	}
}

// TestParseGlossLLMOutput_EmptyGlossesValid 钉住决策：空 glosses 列表合法
// （镜像 Pack.Validate 允许 glosses 为空），estimated_cefr 仍需在白名单。
func TestParseGlossLLMOutput_EmptyGlossesValid(t *testing.T) {
	res, err := ParseGlossLLMOutput(`{"estimated_cefr":"A1","glosses":[]}`)
	if err != nil {
		t.Fatalf("空 glosses 应合法：%v", err)
	}
	if res.EstimatedCEFR != "A1" || len(res.Glosses) != 0 {
		t.Errorf("空 glosses 解析不符：%+v", res)
	}
}

// TestParseGlossLLMOutput_EstimatedCEFRCaseNormalize 断言 estimated_cefr 大小写归一。
func TestParseGlossLLMOutput_EstimatedCEFRCaseNormalize(t *testing.T) {
	res, err := ParseGlossLLMOutput(`{"estimated_cefr":"b1","glosses":[]}`)
	if err != nil {
		t.Fatalf("小写 estimated_cefr 应归一合法：%v", err)
	}
	if res.EstimatedCEFR != "B1" {
		t.Errorf("EstimatedCEFR = %q, want B1（归一后）", res.EstimatedCEFR)
	}
}

// TestParseGlossLLMOutput_WhitespaceVariants 断言纯空白/换行变体围绕的 JSON 可解析。
func TestParseGlossLLMOutput_WhitespaceVariants(t *testing.T) {
	raw := "\n\n  {\"estimated_cefr\":\"A2\",\"glosses\":[{\"lemma\":\"Brot\",\"gloss_zh\":\"面包\",\"cefr\":\"a1\"}]}  \n\t"
	res, err := ParseGlossLLMOutput(raw)
	if err != nil {
		t.Fatalf("首尾空白变体应可解析：%v", err)
	}
	if res.EstimatedCEFR != "A2" || len(res.Glosses) != 1 {
		t.Errorf("空白变体解析不符：%+v", res)
	}
}

// ---- BuildGlossPrompt -----------------------------------------------------

// TestBuildGlossPrompt_NonEmpty 断言返回的 system/user 均非空。
func TestBuildGlossPrompt_NonEmpty(t *testing.T) {
	sys, user := BuildGlossPrompt(GlossRequest{Text: "Es war einmal.", UnknownLemmas: []LemmaCount{{Lemma: "einmal", Count: 1}}, KnownRate: 0.5})
	if strings.TrimSpace(sys) == "" {
		t.Error("system 提示不应为空")
	}
	if strings.TrimSpace(user) == "" {
		t.Error("user 提示不应为空")
	}
}

// TestBuildGlossPrompt_JSONInstruction 断言系统提示要求输出严格 JSON 且禁多余文本。
func TestBuildGlossPrompt_JSONInstruction(t *testing.T) {
	sys, _ := BuildGlossPrompt(GlossRequest{Text: "x", UnknownLemmas: []LemmaCount{{Lemma: "y", Count: 1}}, KnownRate: 0})
	for _, needle := range []string{"JSON", "estimated_cefr", "gloss_zh", "A1", "B1"} {
		if !strings.Contains(sys, needle) {
			t.Errorf("system 提示应包含 %q 指示/示例", needle)
		}
	}
	// 禁多余文本：应提示不得输出围栏外文字。
	if !strings.Contains(sys, "围栏") && !strings.Contains(strings.ToLower(sys), "no") && !strings.Contains(strings.ToLower(sys), "only") {
		t.Errorf("system 提示应含禁多余文本语义（未检测到）")
	}
}

// TestBuildGlossPrompt_ExampleIncluded 断言用户提示包含一个示例 JSON 结构。
func TestBuildGlossPrompt_ExampleIncluded(t *testing.T) {
	_, user := BuildGlossPrompt(GlossRequest{Text: "x", UnknownLemmas: []LemmaCount{{Lemma: "y", Count: 1}}, KnownRate: 0})
	if !strings.Contains(user, "lemma") || !strings.Contains(user, "cefr") {
		t.Errorf("user 提示应含示例 JSON 字段（lemma/cefr），实得：%q", user)
	}
	if !strings.Contains(user, "a1") && !strings.Contains(user, "A1") {
		t.Errorf("user 提示示例应含 A1 级字段示意")
	}
}

// TestBuildGlossPrompt_SamplingRespectsCap 断言超长文本被按词截断至采样上限。
func TestBuildGlossPrompt_SamplingRespectsCap(t *testing.T) {
	// 造远超过限的一串词（> sampleMaxWords+缓冲）。
	words := make([]string, sampleMaxWords*2)
	for i := range words {
		words[i] = "Wort"
	}
	longText := strings.Join(words, " ")
	_, user := BuildGlossPrompt(GlossRequest{Text: longText, UnknownLemmas: []LemmaCount{{Lemma: "y", Count: 1}}, KnownRate: 0})
	// 采样文本应只含 <= sampleMaxWords 个词。
	if got := strings.Count(user, "Wort"); got > sampleMaxWords {
		t.Errorf("user 提示含 %d 个样本词，超采样上限 %d", got, sampleMaxWords)
	}
}

// TestBuildGlossPrompt_IncludesKnownRateAndLemmas 断言用户提示包含 known_rate 与待释词。
func TestBuildGlossPrompt_IncludesKnownRateAndLemmas(t *testing.T) {
	_, user := BuildGlossPrompt(GlossRequest{
		Text:          "Sammlung.",
		UnknownLemmas: []LemmaCount{{Lemma: "Sammlung", Count: 3}, {Lemma: "gewaltig", Count: 2}},
		KnownRate:     0.42,
	})
	for _, needle := range []string{"Sammlung", "gewaltig", "known_rate", "0.42", "0.4"} {
		if !strings.Contains(user, needle) {
			t.Errorf("user 提示应包含 %q，实得：%q", needle, user)
		}
	}
}

// ---- EstimateTokens -------------------------------------------------------

// TestEstimateTokens_Deterministic 断言估算是确定且非负的。
func TestEstimateTokens_Deterministic(t *testing.T) {
	a := EstimateTokens("Hallo Welt, wie geht es dir?")
	b := EstimateTokens("Hallo Welt, wie geht es dir?")
	if a != b {
		t.Errorf("EstimateTokens 应确定：%d != %d", a, b)
	}
	if a <= 0 {
		t.Errorf("EstimateTokens = %d, want > 0", a)
	}
}

// TestEstimateTokens_EmptyIsZero 断言空文本估算为 0。
func TestEstimateTokens_EmptyIsZero(t *testing.T) {
	if got := EstimateTokens(""); got != 0 {
		t.Errorf("EstimateTokens(\"\") = %d, want 0", got)
	}
}

// TestEstimateTokens_GrowsWithText 断言更长文本估算更大。
func TestEstimateTokens_GrowsWithText(t *testing.T) {
	short := EstimateTokens(strings.Repeat("a ", 10))
	long := EstimateTokens(strings.Repeat("a ", 100))
	if long <= short {
		t.Errorf("长文本估算应更大：short=%d long=%d", short, long)
	}
}

// ---- httptest stub smoke（真 llm.Client + 桩 BaseURL） --------------------

const testLLMAPIKey = "job-test-token" // 仅测试占位，绝非真实 key

// TestGlossRealClient_HTTTPSmoke 用一个指向 httptest 桩的真 *llm.Client 走完
// Complete → ParseGlossLLMOutput 全链路；桩断言请求携带了 system/user 内容
// 并回吐 DeepSeek chat/completions 形状（与 llm/deepseek_test.go 一致）。
func TestGlossRealClient_HTTTPSmoke(t *testing.T) {
	const wantSystemTag = "严格 JSON"
	const wantUserTag = "Es war einmal ein sonniger Tag."
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/chat/completions" {
			t.Errorf("path = %q, want /chat/completions", r.URL.Path)
		}
		var body openai.ChatCompletionRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode request body: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if len(body.Messages) != 2 {
			t.Errorf("len(messages) = %d, want 2", len(body.Messages))
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if body.Messages[0].Role != openai.ChatMessageRoleSystem || !strings.Contains(body.Messages[0].Content, wantSystemTag) {
			t.Errorf("messages[0] 应为 system 且含 %q", wantSystemTag)
		}
		if body.Messages[1].Role != openai.ChatMessageRoleUser || !strings.Contains(body.Messages[1].Content, wantUserTag) {
			t.Errorf("messages[1] 应为 user 且含 %q", wantUserTag)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"cmpl-gloss","object":"chat.completion","created":1,
			"model":"deepseek-chat","choices":[{"index":0,"message":{"role":"assistant","content":"{\"estimated_cefr\":\"A2\",\"glosses\":[{\"lemma\":\"sonnig\",\"gloss_zh\":\"晴朗的\",\"cefr\":\"B1\",\"pos\":\"ADJ\"}]}"},"finish_reason":"stop"}],
			"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}`))
	}))
	t.Cleanup(srv.Close)

	t.Setenv("DEEPSEEK_API_KEY", testLLMAPIKey)
	c, err := llm.NewClient(llm.Config{BaseURL: srv.URL})
	if err != nil {
		t.Fatalf("NewClient with stub baseURL: %v", err)
	}

	sys, user := BuildGlossPrompt(GlossRequest{
		Text:          wantUserTag,
		UnknownLemmas: []LemmaCount{{Lemma: "sonnig", Count: 1}},
		KnownRate:     0.4,
	})
	if !strings.Contains(sys, wantSystemTag) {
		t.Fatalf("system 提示应含 %q 以触发桩断言", wantSystemTag)
	}

	var g GlossLLM = c // 编译期：*llm.Client 必须满足 GlossLLM 接口
	raw, err := g.Complete(context.Background(), sys, user)
	if err != nil {
		t.Fatalf("Complete via stub: %v", err)
	}
	res, err := ParseGlossLLMOutput(raw)
	if err != nil {
		t.Fatalf("ParseGlossLLMOutput(stub output): %v", err)
	}
	if res.EstimatedCEFR != "A2" || len(res.Glosses) != 1 || res.Glosses[0].Lemma != "sonnig" {
		t.Errorf("stub 链路解析结果不符：%+v", res)
	}
}
