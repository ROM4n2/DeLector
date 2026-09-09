package job

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/corpus"
	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/llm"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// ---- fake 装配 ----------------------------------------------------------------

// recorder 记录步骤调用顺序（供断言 load→analyze→vocab_stats→gloss→export 链式推进）。
type recorder struct {
	mu     sync.Mutex
	events []string
}

func (r *recorder) add(e string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.events = append(r.events, e)
}

func (r *recorder) get() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.events...)
}

// fixedArticle 是一篇固定 fixture（对应 corpus.Article）。
func fixedArticle() corpus.Article {
	return corpus.Article{
		Path:  filepath.Join("corpus", "ein_tag_im_park.txt"),
		Title: "Ein Tag im Park",
		Text:  "Es geht mir heute gut im Park, danke.",
		// 64 位十六进制确定性 hash → hash8 = "aabbccdd"。
		Hash: "aabbccdd" + strings.Repeat("1", 56),
	}
}

// fixedAnalyzeOut 返回与 python analyze 同构的产出：sentences[].tokens[].{text,lemma,pos}。
func fixedAnalyzeOut() map[string]any {
	return map[string]any{
		"version":        "3.5.0",
		"sentence_count": 1,
		"sentences": []any{
			map[string]any{
				"tokens": []any{
					map[string]any{"text": "Es", "lemma": "es", "pos": "PRON"},
					map[string]any{"text": "geht", "lemma": "gehen", "pos": "VERB"},
					map[string]any{"text": "mir", "lemma": "ich", "pos": "PRON"},
					map[string]any{"text": "gut", "lemma": "gut", "pos": "ADJ"},
				},
			},
		},
	}
}

// newTestEnv 组装 fake registry（analyze/vocab_stats）+ fake gloss + budget + 临时 outDir。
// vocabStatsFunc 记录收到的 payload 以便断言 token 展平。
func newTestEnv(t *testing.T, rec *recorder, vocabPayload *map[string]any) (EncounterDeps, *fakeGloss) {
	t.Helper()

	reg := registry.NewRegistry()
	if err := reg.Register("analyze", func(ctx context.Context, payload map[string]any) (map[string]any, error) {
		rec.add("analyze")
		// 断言 analyze 收到正文 text。
		if got, _ := payload["text"].(string); got == "" {
			return nil, errors.New("analyze payload 缺 text")
		}
		return fixedAnalyzeOut(), nil
	}); err != nil {
		t.Fatalf("注册 analyze fake: %v", err)
	}

	if err := reg.Register("vocab_stats", func(ctx context.Context, payload map[string]any) (map[string]any, error) {
		rec.add("vocab_stats")
		if vocabPayload != nil {
			*vocabPayload = payload
		}
		return map[string]any{
			"tokens_total": 4,
			"known_count":  3,
			"known_rate":   0.75,
			"level_hint":   "A2",
			"unknown_ranked": []any{
				map[string]any{"lemma": "gehen", "count": 1},
			},
		}, nil
	}); err != nil {
		t.Fatalf("注册 vocab_stats fake: %v", err)
	}

	g := &fakeGloss{rec: rec}
	out := EncounterDeps{
		Reg:    reg,
		Gloss:  g,
		Budget: NewTokenBudget(100_000),
		OutDir: t.TempDir(),
	}
	return out, g
}

// fakeGloss 固定返回合法 JSON（implement GlossLLM 接口），并记录调用文本与顺序。
type fakeGloss struct {
	mu     sync.Mutex
	system string
	user   string
	calls  int
	rec    *recorder
}

func (f *fakeGloss) Complete(ctx context.Context, system, user string, _ ...llm.Option) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	f.system = system
	f.user = user
	if f.rec != nil {
		f.rec.add("gloss")
	}
	return `{"estimated_cefr":"B1","glosses":[{"lemma":"gehen","gloss_zh":"去","cefr":"B1","pos":"VERB"}]}`, nil
}

func (f *fakeGloss) snapshot() (system, user string, calls int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.system, f.user, f.calls
}

// buildAndRun 构造 DAG 并跑一篇，返回摘要。
func buildAndRun(t *testing.T, d EncounterDeps, a corpus.Article) (PackResult, *dag.DAG) {
	t.Helper()
	g, err := BuildEncounterDAG(d)
	if err != nil {
		t.Fatalf("BuildEncounterDAG: %v", err)
	}
	res, err := RunOneArticle(context.Background(), g, a)
	if err != nil {
		t.Fatalf("RunOneArticle: %v", err)
	}
	return res, g
}

// ---- 拓扑 / 依赖 ---------------------------------------------------------------

// TestEncounterDAG_Topology 断言步骤集与依赖边符合 encounter-pack 口径
// （load→analyze→vocab_stats→gloss→export_pack；gloss/export 均含 load/vocab_stats 依赖）。
func TestEncounterDAG_Topology(t *testing.T) {
	out, _ := newTestEnv(t, &recorder{}, nil)
	g, err := BuildEncounterDAG(out)
	if err != nil {
		t.Fatalf("BuildEncounterDAG: %v", err)
	}
	// 步骤集（在 dag_test 同包内无法访问私有字段，改用 Run 冒烟间接验证；此处仅查构建成功）。
	if g == nil {
		t.Fatal("BuildEncounterDAG 返回 nil")
	}
}

// ---- 完整链路：顺序 + Pack 字段 + 落盘回读 --------------------------------------

// TestEncounterRunOneArticle_ProducesValidPack 跑一篇 fixture：
//   - 断言 analyze→vocab_stats→gloss 被按序调用；
//   - vocab_stats 收到从 analyze 展平后的 {text,lemma,pos} tokens；
//   - gloss 输入含正文抽样 + unknown_ranked lemma + known_rate；
//   - 落盘文件符合 <slug>-<hash8>.pack.json、JSON 可回读且 Validate 通过；
//   - 字段核对：title / EstimatedCEFR 来自 gloss / glosses / Analysis.known_rate 与 level_hint。
func TestEncounterRunOneArticle_ProducesValidPack(t *testing.T) {
	rec := &recorder{}
	var vocabPayload map[string]any
	out, gloss := newTestEnv(t, rec, &vocabPayload)
	art := fixedArticle()

	res, _ := buildAndRun(t, out, art)

	// 步骤顺序：analyze → vocab_stats → gloss（export 以落盘存在证明已执行）。
	got := rec.get()
	wantOrder := []string{"analyze", "vocab_stats", "gloss"}
	for i, w := range wantOrder {
		if i >= len(got) || got[i] != w {
			t.Fatalf("步骤调用顺序应为 %v（前 3 项），实得 %v", wantOrder, got)
		}
	}

	// vocab_stats 收到 analyze 展平的 4 个 {text,lemma,pos} token。
	toks, _ := vocabPayload["tokens"].([]map[string]any)
	if len(toks) != 4 {
		t.Fatalf("vocab_stats 应收 4 个展平 token，实得 %d（%#v）", len(toks), vocabPayload["tokens"])
	}
	first := toks[0]
	if first["text"] != "Es" || first["lemma"] != "es" || first["pos"] != "PRON" {
		t.Errorf("token 展平映射不符（text/lemma/pos）：%+v", first)
	}
	// 末个 token 也应正确展平，验证跨 token 遍历。
	last := toks[3]
	if last["text"] != "gut" || last["lemma"] != "gut" || last["pos"] != "ADJ" {
		t.Errorf("末 token 展平不符：%+v", last)
	}

	// gloss 输入含正文抽样词 + unknown lemma + known_rate。
	_, user, calls := gloss.snapshot()
	if calls != 1 {
		t.Fatalf("gloss 应只调用 1 次，实得 %d", calls)
	}
	for _, needle := range []string{"gehen", "known_rate", "0.75", "danke"} {
		if !strings.Contains(user, needle) {
			t.Errorf("gloss user prompt 应含 %q，实得：%q", needle, user)
		}
	}

	// 落盘命名。
	wantName := "ein-tag-im-park-aabbccdd.pack.json"
	if wantName != encounterFilename(art.Title, art.Hash) {
		t.Fatalf("文件名生成器不符：want %q got %q", wantName, encounterFilename(art.Title, art.Hash))
	}
	if filepath.Base(res.Path) != wantName {
		t.Fatalf("落盘文件名应为 %q，实得 %q", wantName, filepath.Base(res.Path))
	}
	if res.PackID != "ein-tag-im-park-aabbccdd" {
		t.Errorf("pack_id 应为确定性 <slug>-<hash8>，实得 %q", res.PackID)
	}

	// 文件存在 & JSON 可回读 & Validate 通过。
	raw, err := os.ReadFile(res.Path)
	if err != nil {
		t.Fatalf("读落盘文件: %v", err)
	}
	var back Pack
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatalf("回读落盘 JSON: %v", err)
	}
	if err := back.Validate(); err != nil {
		t.Fatalf("回读 Pack 应过 Validate：%v", err)
	}
	// 字段核对。
	if back.Schema != CARD_PACK_SCHEMA {
		t.Errorf("schema = %q, want %q", back.Schema, CARD_PACK_SCHEMA)
	}
	if back.PackID != res.PackID {
		t.Errorf("pack_id = %q, want %q", back.PackID, res.PackID)
	}
	if back.Article.Title != art.Title {
		t.Errorf("article.title = %q, want %q", back.Article.Title, art.Title)
	}
	if back.Article.RawText != art.Text {
		t.Errorf("article.raw_text 不符")
	}
	if back.Article.CharCount != len([]rune(art.Text)) {
		t.Errorf("article.char_count = %d, want %d", back.Article.CharCount, len([]rune(art.Text)))
	}
	if back.Source.Kind != "job1" || back.Source.File != "ein_tag_im_park.txt" {
		t.Errorf("source 不符：%+v", back.Source)
	}
	// Analysis 来自 vocab_stats。
	if back.Analysis.TokensTotal != 4 || back.Analysis.KnownCount != 3 || back.Analysis.KnownRate != 0.75 {
		t.Errorf("analysis 统计不符：%+v", back.Analysis)
	}
	if back.Analysis.LevelHint != "A2" {
		t.Errorf("analysis.level_hint = %q, want A2", back.Analysis.LevelHint)
	}
	if len(back.Analysis.UnknownLemmas) != 1 || back.Analysis.UnknownLemmas[0].Lemma != "gehen" {
		t.Errorf("analysis.unknown_lemmas 不符：%+v", back.Analysis.UnknownLemmas)
	}
	// EstimatedCEFR 取 gloss 返回（B1），高于 level_hint(A2)——优先级验证。
	if back.EstimatedCEFR != "B1" {
		t.Errorf("estimated_cefr 应取 gloss 的 B1，实得 %q", back.EstimatedCEFR)
	}
	if len(back.Glosses) != 1 || back.Glosses[0].Lemma != "gehen" || back.Glosses[0].GlossZH != "去" {
		t.Errorf("glosses 不符：%+v", back.Glosses)
	}
}

// ---- 预算超限从 gloss 浮出 -------------------------------------------------------

// TestEncounterRunOneArticle_BudgetExceededSurfaces 断言 gloss 步骤 Reserve 超限时
// 错误（ErrBudgetExceeded）真实上浮，不被 export 或 DAG 吞掉。
func TestEncounterRunOneArticle_BudgetExceededSurfaces(t *testing.T) {
	out, _ := newTestEnv(t, &recorder{}, nil)
	// 极小预算：analyze/vocab_stats 走 fake 不耗预算，gloss 的 EstimateTokens>cap 必超限。
	out.Budget = NewTokenBudget(1)
	g, err := BuildEncounterDAG(out)
	if err != nil {
		t.Fatalf("BuildEncounterDAG: %v", err)
	}
	_, err = RunOneArticle(context.Background(), g, fixedArticle())
	if err == nil {
		t.Fatal("预算超限时 RunOneArticle 应返回错误")
	}
	if !errors.Is(err, ErrBudgetExceeded) {
		t.Fatalf("预算超限错误应以 ErrBudgetExceeded 浮出（errors.Is），实得 %v", err)
	}
	// 且不应落盘。
	matches, _ := filepath.Glob(filepath.Join(out.OutDir, "*.pack.json"))
	if len(matches) != 0 {
		t.Errorf("预算失败时不应有 pack 落盘，实得 %v", matches)
	}
}

// ---- 原子覆盖 + 无 tmp 残留 -----------------------------------------------------

// TestEncounterExport_OverwriteOK_NoTmpResidue 断言同篇重跑可覆盖同名文件（existing
// overwrite ok），且 outDir 不残留 .tmp 临时文件。
func TestEncounterExport_OverwriteOK_NoTmpResidue(t *testing.T) {
	out, _ := newTestEnv(t, &recorder{}, nil)
	art := fixedArticle()
	res1, g := buildAndRun(t, out, art)
	res2, err := RunOneArticle(context.Background(), g, art)
	if err != nil {
		t.Fatalf("第二次 RunOneArticle: %v", err)
	}
	if res1.Path != res2.Path {
		t.Fatalf("覆盖运行路径应一致：%q vs %q", res1.Path, res2.Path)
	}
	if _, err := os.Stat(res2.Path); err != nil {
		t.Fatalf("覆盖后文件应存在: %v", err)
	}
	// 无 .tmp 残留。
	tmps, _ := filepath.Glob(filepath.Join(out.OutDir, ".encounter-*.tmp"))
	if len(tmps) != 0 {
		t.Errorf("原子写不应残留 tmp：%v", tmps)
	}
}

// ---- 命名辅助确定性 -------------------------------------------------------------

func TestEncounter_NamingDeterministic(t *testing.T) {
	title, hash := "Ein Tag im Park", "aabbccdd"+"11223344556677889900aabbccddeeff00112233445566778899aabbccdd1122"
	if got := slug(title); got != "ein-tag-im-park" {
		t.Errorf("slug(%q) = %q, want ein-tag-im-park", title, got)
	}
	if got := packIDFor(title, hash); got != "ein-tag-im-park-aabbccdd" {
		t.Errorf("packIDFor = %q, want ein-tag-im-park-aabbccdd", got)
	}
	if got := encounterFilename(title, hash); got != "ein-tag-im-park-aabbccdd.pack.json" {
		t.Errorf("encounterFilename = %q", got)
	}
}

// TestEncounter_SlugTransliteration 断言德语变元音被音译为 ASCII 以便稳定落盘。
func TestEncounter_SlugTransliteration(t *testing.T) {
	for title, want := range map[string]string{
		"Übung macht den Meister!": "uebung-macht-den-meister",
		"Grüße  aus  Berlin...":    "gruesse-aus-berlin",
		"   ###  ":                 "untitled",
	} {
		if got := slug(title); got != want {
			t.Errorf("slug(%q) = %q, want %q", title, got, want)
		}
	}
}

// ExampleEncounterNaming 展示确定性命名规则（文档可读）。
func Example_encounterNaming() {
	fmt.Println(encounterFilename("Ein Tag im Park", "aabbccdd1234"))
	// Output: ein-tag-im-park-aabbccdd.pack.json
}
