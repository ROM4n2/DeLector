//go:build integration

// Package integration_test 承载 job#1（encounter-pack）的真链路端到端门禁
// （Task B8，build tag `integration` 隔离，不进常规 `go test ./...`）：
//
//	DAG → 真实 python 工具（analyze→vocab_stats）→ stub DeepSeek LLM →
//	落盘 → import-pack 投递 → GET /api/encounter/texts 命中。
//
// 门禁语义（Master 验收门 B-2/B-3，逐条）：
//  1. 起真实 python 实例：复用 integration_test.go 的 startRealSupervisor
//     （临时 DATABASE_PATH / DELECTOR_DATA_DIR 注入 t.TempDir，绝不碰用户库），
//     进程存亡由内部 t.Cleanup(s.Stop) 托管。
//  2. GET /api/tools/ → 断言含 6 工具（vocab_stats 在列）。
//  3. stub DeepSeek httptest（仿 llm/deepseek_test.go 的 chat/completions 形状）：
//     llm client BaseURL 指向桩；桩从 user prompt 里抽出待释义 lemma，回吐
//     estimated_cefr=A1 且 glosses 与之逐条对齐的 GlossResult JSON（可被
//     job.ParseGlossLLMOutput 解析），无需真实 DeepSeek key。
//  4. t.TempDir 语料 fixture（2 篇真实德语 A1 短文）→ registry.DefaultRegistry
//     接真实 python → job.RunEncounterPack(deliver-url = python 8001 实例) →
//     断言 2 pack 落盘、JSON 可回读且 Pack.Validate 通过、import-pack 200
//     （Result.Packs==2 且 Result.Failed==0）。
//  5. GET /api/encounter/texts（同 python 实例）→ 断言 2 行命中、title 匹配、
//     level 归一为 A1。
//
// Skip 契约：本机缺 python/uvicorn/fastapi 或起服务失败一律 t.Skipf（同既有
// integration_test.go），绝不假绿也绝不因环境缺失而红。DeepSeek 走桩，无需 key。
package integration_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/sashabaranov/go-openai"

	"github.com/ROM4n2/DeLector/agent/internal/job"
	"github.com/ROM4n2/DeLector/agent/internal/llm"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// TestEncounterRealChain 是 job#1 的真链路端到端门禁：真实 python 工具 +
// stub DeepSeek LLM + 落盘 + import-pack 投递 + encounter texts 命中。
func TestEncounterRealChain(t *testing.T) {
	mustNotSkipEnv(t)
	startRealSupervisor(t) // 临时库 + t.Cleanup(s.Stop)，绝不动用户库

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	// ---- 门禁 2：GET /api/tools/ 含 6 工具（vocab_stats 在列） ----
	tools := getToolsList(t, ctx)
	if len(tools) != 6 {
		t.Fatalf("GET /api/tools/ 应含 6 工具，实得 %d：%v", len(tools), tools)
	}
	if !containsStr(tools, "vocab_stats") {
		t.Fatalf("GET /api/tools/ 应含 vocab_stats，实得 %v", tools)
	}

	// ---- 门禁 3：stub DeepSeek（仿 deepseek_test.go chat/completions 形状） ----
	stub := stubDeepSeek(t)
	t.Setenv(llmEnvKey, "test-token") // 仅占位，非真实凭据；真请求被桩拦截
	gloss, err := llm.NewClient(llm.Config{BaseURL: stub.URL})
	if err != nil {
		t.Fatalf("构造 llm client（指向桩）: %v", err)
	}

	// ---- 门禁 4：语料 fixture + RunEncounterPack（投递到真实 python 8001） ----
	corpusDir := t.TempDir()
	outDir := t.TempDir()
	writeCorpus(t, corpusDir, "mein_tag.txt", corpusArticle1)
	writeCorpus(t, corpusDir, "im_supermarkt.txt", corpusArticle2)

	client := pythonsvc.NewClient(baseURL, nil)
	reg := registry.DefaultRegistry(client)

	res, err := job.RunEncounterPack(ctx, reg, gloss, job.RunConfig{
		CorpusDir:  corpusDir,
		OutDir:     outDir,
		DeliverURL: baseURL, // 投递 import-pack 到托管 python 实例
	})
	if err != nil {
		t.Fatalf("RunEncounterPack 真链路不应整体报错: %v", err)
	}
	if len(res.Packs) != 2 {
		t.Fatalf("应落盘+投递 2 个 pack，实得 Packs=%v Failed=%v", res.Packs, res.Failed)
	}
	if len(res.Failed) != 0 {
		t.Fatalf("2 篇真链路应全成功，实得失败：%v", res.Failed)
	}

	// 每篇 pack 落盘、JSON 可回读且 Pack.Validate 通过。
	assertValidPacks(t, res.Packs)

	// ---- 门禁 5：GET /api/encounter/texts 命中 2 行、title 匹配、level 归一 A1 ----
	rows := encounterTexts(t, ctx)
	if len(rows) != 2 {
		t.Fatalf("import-pack 后 /api/encounter/texts 应命中 2 行，实得 %d：%v", len(rows), rows)
	}
	titles := make([]string, 0, len(rows))
	for _, r := range rows {
		titles = append(titles, r.Title)
		if r.Level != "A1" {
			t.Errorf("行 %q level 应为 A1（stub estimated_cefr=A1 归一），实得 %q", r.Title, r.Level)
		}
	}
	sort.Strings(titles)
	if !containsStr(titles, "im_supermarkt") || !containsStr(titles, "mein_tag") {
		t.Errorf("encounter texts 应命中两篇 fixture title，实得 %v", titles)
	}
	t.Logf("真链路 OK: tools=%v packs=%d texts=%v", tools, len(res.Packs), titles)
}

// ---- stub DeepSeek（桩）：解析 user prompt 的未知词并回吐对齐的 GlossResult ----

// llmEnvKey 镜像 llm 包内部读 key 的环境变量名；只用占位 token，桩拦截一切请求。
const llmEnvKey = "DEEPSEEK_API_KEY"

// stubDeepSeek 起一个 chat/completions 桩：从 user 消息中抽 "请为下列未知词…" 之后
// 形如 "- <lemma>" 的行，构造 glosses（逐条 lemma 对齐、cefr A1），并回 estimated_cefr=A1。
// 返回的 content 是可直接被 job.ParseGlossLLMOutput 解析的纯 JSON。
func stubDeepSeek(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/chat/completions" {
			http.Error(w, "unexpected", http.StatusNotFound)
			return
		}
		var body openai.ChatCompletionRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "bad json", http.StatusBadRequest)
			return
		}
		lemmas := unknownLemmasFromUser(body.Messages)
		glosses := make([]map[string]string, 0, len(lemmas))
		for _, lm := range lemmas {
			glosses = append(glosses, map[string]string{
				"lemma":    lm,
				"gloss_zh": "释义占位（桩）",
				"cefr":     "A1",
				"pos":      "NOUN",
			})
		}
		payload := struct {
			EstimatedCEFR string              `json:"estimated_cefr"`
			Glosses       []map[string]string `json:"glosses"`
		}{EstimatedCEFR: "A1", Glosses: glosses}
		raw, _ := json.Marshal(payload)

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(fmt.Sprintf(
			`{"id":"cmpl-test","object":"chat.completion","created":1,"model":"deepseek-chat",`+
				`"choices":[{"index":0,"message":{"role":"assistant","content":%s},"finish_reason":"stop"}],`+
				`"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`,
			jsonString(string(raw)))))
	}))
	t.Cleanup(srv.Close)
	return srv
}

// jsonString 把 s 转成可内嵌 JSON 的带引号字符串字面量。
func jsonString(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

// unknownLemmasFromUser 从 chat 消息中收集 gloss prompt user 段里待释义的 lemma：
// 定位含 "请为下列未知词" 的标记行之后，逐行取 "- <lemma>" 前缀。
func unknownLemmasFromUser(msgs []openai.ChatCompletionMessage) []string {
	var out []string
	started := false
	for _, m := range msgs {
		if m.Role != openai.ChatMessageRoleUser {
			continue
		}
		for _, line := range strings.Split(m.Content, "\n") {
			trim := strings.TrimSpace(line)
			if strings.Contains(trim, "请为下列未知词") {
				started = true
				continue
			}
			if started && strings.HasPrefix(trim, "- ") {
				if lm := strings.TrimSpace(strings.TrimPrefix(trim, "- ")); lm != "" {
					out = append(out, lm)
				}
			}
		}
	}
	return out
}

// ---- 真实 python 实例交互辅助（同包复用 startRealSupervisor / baseURL） ----------

// getToolsList 以 GET 拉取 /api/tools/ 并解析 {"tools": [...]}。
func getToolsList(t *testing.T, ctx context.Context) []string {
	t.Helper()
	var resp struct {
		Tools []string `json:"tools"`
	}
	getPythonJSON(t, ctx, baseURL+"/api/tools/", &resp)
	return resp.Tools
}

// encounterTextRow 是 /api/encounter/texts 列表端点的最小契约字段。
type encounterTextRow struct {
	Title string
	Level string
}

// encounterTexts 以 GET 拉取 /api/encounter/texts 并解析 {"texts":[...]}。
func encounterTexts(t *testing.T, ctx context.Context) []encounterTextRow {
	t.Helper()
	var resp struct {
		Texts []struct {
			Title string `json:"title"`
			Level string `json:"level"`
		} `json:"texts"`
	}
	getPythonJSON(t, ctx, baseURL+"/api/encounter/texts", &resp)
	out := make([]encounterTextRow, 0, len(resp.Texts))
	for _, r := range resp.Texts {
		out = append(out, encounterTextRow{Title: r.Title, Level: r.Level})
	}
	return out
}

// getPythonJSON 对真实 python 实例发起 GET 并把 200 JSON 解到 out。
func getPythonJSON(t *testing.T, ctx context.Context, url string, out any) {
	t.Helper()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("构建 GET %s: %v", url, err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("GET %s 失败: %v", url, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("GET %s 状态 %d：%s", url, resp.StatusCode, string(raw))
	}
	if err := json.Unmarshal(raw, out); err != nil {
		t.Fatalf("解析 %s 响应: %v（body=%s）", url, err, string(raw))
	}
}

// assertValidPacks 断言每个 pack 文件存在、JSON 可回读且 job.Pack.Validate 通过。
func assertValidPacks(t *testing.T, paths []string) {
	t.Helper()
	for _, p := range paths {
		raw, err := os.ReadFile(p)
		if err != nil {
			t.Fatalf("读落盘 pack %s: %v", p, err)
		}
		var back job.Pack
		if err := json.Unmarshal(raw, &back); err != nil {
			t.Fatalf("回读 pack %s JSON: %v", p, err)
		}
		if err := back.Validate(); err != nil {
			t.Fatalf("pack %s 应过 Validate: %v", p, err)
		}
		if back.EstimatedCEFR != "A1" {
			t.Errorf("pack %s estimated_cefr 应为 stub 的 A1，实得 %q", p, back.EstimatedCEFR)
		}
	}
}

// ---- fixture / 小工具 -----------------------------------------------------------

// corpusArticle1 / corpusArticle2 是两篇真实德语 A1 级短文（含 1-2 个超 A1/A2 考纲的
// 生词，使 vocab_stats 报告未知词、被送进 gloss prompt；整体仍为 A1 内容）。
const corpusArticle1 = "Guten Morgen! Ich trinke Kaffee und esse Brot. Dann gehe ich zur Arbeit. Am Abend bin ich zu Hause und ich bin müde."
const corpusArticle2 = "Ich gehe in den Supermarkt. Ich kaufe Brot, Milch und frisches Obst. Ich bezahle an der Kasse und gehe nach Hause."

// writeCorpus 在 root 下写一篇 .txt 语料（文件名去扩展即 title）。
func writeCorpus(t *testing.T, root, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, name), []byte(content), 0o644); err != nil {
		t.Fatalf("写语料 %s: %v", name, err)
	}
}

// containsStr 报告 slice 是否含目标串。
func containsStr(ss []string, want string) bool {
	for _, s := range ss {
		if s == want {
			return true
		}
	}
	return false
}
