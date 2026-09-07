package job

import (
	"encoding/json"
	"strings"
	"testing"
)

// validPack 构造一个逐字段齐备的合法 encounter-pack/v1 卡包。
// json 标签即 A2 Python 导入契约的 snake_case 键（见 TestPack_JSONTagParity）。
func validPack() *Pack {
	return &Pack{
		Schema:    "encounter-pack/v1",
		PackID:    "job1-cardpack-0001",
		Source:    PackSource{Kind: "job1", Path: "corpus/a.txt", File: "a.txt"},
		CreatedAt: "2026-09-07T12:00:00Z",
		Article: PackArticle{
			Title:     "Ein Tag im Park",
			RawText:   "Es war einmal ein sonniger Tag im Park.",
			CharCount: 43,
		},
		Analysis: PackAnalysis{
			TokensTotal:   8,
			KnownCount:    2,
			KnownRate:     0.25,
			LevelHint:     "A2",
			UnknownLemmas: []LemmaCount{{Lemma: "sonniger", Count: 1}},
		},
		Glosses: []PackGloss{
			{Lemma: "sonnig", GlossZH: "晴朗的", CEFR: "B1", Pos: "ADJ"},
		},
		EstimatedCEFR: "B1",
	}
}

// pythonFixtureJSON 是 A2 侧 import-pack 实际会接收的 snake_case JSON 外形，
// 只含真实产生器（job#1）会填的键；用于反序列化交叉验证 json 标签逐键一致。
const pythonFixtureJSON = `{
  "schema": "encounter-pack/v1",
  "pack_id": "job1-cardpack-0001",
  "source": {"kind": "job1", "path": "corpus/a.txt", "file": "a.txt"},
  "created_at": "2026-09-07T12:00:00Z",
  "article": {"title": "Ein Tag im Park", "raw_text": "Es war einmal ein sonniger Tag im Park.", "char_count": 43},
  "analysis": {"tokens_total": 8, "known_count": 2, "known_rate": 0.25, "level_hint": "A2", "unknown_lemmas": [{"lemma": "sonniger", "count": 1}]},
  "glosses": [{"lemma": "sonnig", "gloss_zh": "晴朗的", "cefr": "B1", "pos": "ADJ"}],
  "estimated_cefr": "B1"
}`

// TestPack_Validate_AcceptsValid 断言一个字段齐备的合法包通过 Validate。
func TestPack_Validate_AcceptsValid(t *testing.T) {
	if err := validPack().Validate(); err != nil {
		t.Fatalf("合法包不应被拒：%v", err)
	}
}

// TestPack_Validate_JSONTagParity 先序列化再回读，证明 json 标签与 A2 Python
// snake_case 键逐字段一致：Marshal 后字段名即 python 端 import-pack 期望的键名。
func TestPack_Validate_JSONTagParity(t *testing.T) {
	// 1) Marshal：Go 结构 → snake_case JSON，字段名须与 python 契约一致。
	raw, err := json.Marshal(validPack())
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}
	for _, key := range []string{
		"schema", "pack_id", "source", "created_at", "article", "analysis",
		"glosses", "estimated_cefr", "kind", "path", "file", "title", "raw_text",
		"char_count", "tokens_total", "known_count", "known_rate", "level_hint",
		"unknown_lemmas", "lemma", "count", "gloss_zh", "cefr", "pos",
	} {
		if !strings.Contains(string(raw), `"`+key+`"`) {
			t.Errorf("序列化 JSON 缺 python 键 %q，全量：\n%s", key, raw)
		}
	}

	// 2) 反序列化 python 外形 JSON → Go 结构 → 字段值等价（交叉验证）。
	var back Pack
	if err := json.Unmarshal([]byte(pythonFixtureJSON), &back); err != nil {
		t.Fatalf("Unmarshal python 外形 JSON: %v", err)
	}
	if err := back.Validate(); err != nil {
		t.Fatalf("python 外形 JSON 反序列化后应合法：%v", err)
	}
	if back.PackID != "job1-cardpack-0001" || back.Schema != "encounter-pack/v1" {
		t.Errorf("顶层字段回读不符：%+v", back)
	}
	if back.Article.RawText != "Es war einmal ein sonniger Tag im Park." {
		t.Errorf("article.raw_text 回读不符：%q", back.Article.RawText)
	}
	if back.Article.CharCount != 43 {
		t.Errorf("article.char_count 回读不符：%d", back.Article.CharCount)
	}
	if back.Analysis.KnownRate != 0.25 || back.Analysis.LevelHint != "A2" {
		t.Errorf("analysis 回读不符：%+v", back.Analysis)
	}
	if len(back.Analysis.UnknownLemmas) != 1 || back.Analysis.UnknownLemmas[0].Lemma != "sonniger" {
		t.Errorf("analysis.unknown_lemmas 回读不符：%+v", back.Analysis.UnknownLemmas)
	}
	if len(back.Glosses) != 1 || back.Glosses[0].GlossZH != "晴朗的" || back.Glosses[0].Pos != "ADJ" {
		t.Errorf("glosses 回读不符：%+v", back.Glosses)
	}
	if back.Source.Kind != "job1" || back.Source.Path != "corpus/a.txt" || back.Source.File != "a.txt" {
		t.Errorf("source 回读不符：%+v", back.Source)
	}
}

// TestPack_Validate_RejectsSchemaError 断言 schema 必须固定为 encounter-pack/v1。
func TestPack_Validate_RejectsSchemaError(t *testing.T) {
	// 空 schema
	p := validPack()
	p.Schema = ""
	if err := p.Validate(); err == nil {
		t.Errorf("空 schema 应被拒")
	}
	// 错误 schema
	p2 := validPack()
	p2.Schema = "encounter-pack/v2"
	if err := p2.Validate(); err == nil {
		t.Errorf("错误 schema 应被拒")
	}
}

// TestPack_Validate_RejectsMissingRequired 断言缺失必填键被拒，口径与 A2 Python
// validate_pack 一致：pack_id / article.title / article.raw_text 不可为空。
func TestPack_Validate_RejectsMissingRequired(t *testing.T) {
	p := validPack()
	p.PackID = ""
	if err := p.Validate(); err == nil {
		t.Errorf("空 pack_id 应被拒")
	}
	p2 := validPack()
	p2.PackID = "   "
	if err := p2.Validate(); err == nil {
		t.Errorf("空白 pack_id 应被拒")
	}
	p3 := validPack()
	p3.Article.Title = ""
	if err := p3.Validate(); err == nil {
		t.Errorf("空 article.title 应被拒")
	}
	p4 := validPack()
	p4.Article.RawText = ""
	if err := p4.Validate(); err == nil {
		t.Errorf("空 article.raw_text 应被拒")
	}
}

// TestPack_Validate_EstimatedCEFRWhitelist 断言 estimated_cefr 需落在 A1|A2|B1
// （大小写归一，镜像 A2 路由 _normalize_level 的 trim+upper 语义）。
func TestPack_Validate_EstimatedCEFRWhitelist(t *testing.T) {
	// 白名单内各值（含小写归一）都应合法。
	for _, v := range []string{"A1", "A2", "B1", "a1", "a2", "b1", " a2 ", "B1"} {
		p := validPack()
		p.EstimatedCEFR = v
		if err := p.Validate(); err != nil {
			t.Errorf("estimated_cefr=%q 应合法（大小写归一），实得 err=%v", v, err)
		}
	}
	// 空值按 python 语义默认 A2 → 合法（不 over-constrain）。
	p := validPack()
	p.EstimatedCEFR = ""
	if err := p.Validate(); err != nil {
		t.Errorf("空 estimated_cefr 按 python 语义默认 A2，不应被拒：%v", err)
	}
	// 白名单外值应被拒。
	for _, v := range []string{"C1", "B2", "C2", "xx"} {
		p := validPack()
		p.EstimatedCEFR = v
		if err := p.Validate(); err == nil {
			t.Errorf("estimated_cefr=%q 不在白名单应被拒", v)
		}
	}
}

// TestPack_Validate_EstimatedCEFRWhitespaceOnlyRejected 钉住 B3 reviewer YELLOW
// 收敛：非空但 trim 后为纯空白（如 "  "）的 estimated_cefr 是**非法**的——
// python 端会 400，Go 不可静默落成默认 A2。只有原本为空的串才默认 A2。
func TestPack_Validate_EstimatedCEFRWhitespaceOnlyRejected(t *testing.T) {
	for _, v := range []string{"  ", "\t", "\n", " \t\n "} {
		p := validPack()
		p.EstimatedCEFR = v
		if err := p.Validate(); err == nil {
			t.Errorf("estimated_cefr=%q（纯空白但非空）应被拒，而非默认 A2", v)
		}
	}
}
