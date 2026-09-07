// Package job 承载 job#1（encounter-pack 内容生产引擎）的骨架：卡包 schema
// 与校验、Token 预算护栏。先于 DAG 步骤落地，供 B4（gloss）/B5（DAG 预设）
// 依赖。跨边界契约 `encounter-pack/v1` 与 A2 Python 导入端点逐字段一致——
// json 标签即 python 端 `POST /api/encounter/import-pack` 期望的 snake_case 键。
package job

import (
	"fmt"
	"strings"
)

// CARD_PACK_SCHEMA 是 encounter-pack 卡包的固定 schema 版本（A/B 端共同钉住）。
const CARD_PACK_SCHEMA = "encounter-pack/v1"

// allowedCEFR 是 estimated_cefr 白名单；校验做 trim+upper 归一（镜像 A2 Python
// 路由 _normalize_level 语义），空值默认 A2。
var allowedCEFR = map[string]bool{"A1": true, "A2": true, "B1": true}

// PackSource 记录语料来源（文件定位）。
type PackSource struct {
	Kind string `json:"kind"`
	Path string `json:"path"`
	File string `json:"file"`
}

// PackArticle 是卡包正文。
type PackArticle struct {
	Title     string `json:"title"`
	RawText   string `json:"raw_text"`
	CharCount int    `json:"char_count"`
}

// LemmaCount 是未知词出现频次（词表口径与 A2/A5 一致）。
type LemmaCount struct {
	Lemma string `json:"lemma"`
	Count int    `json:"count"`
}

// PackAnalysis 是正文统计结果（来自 vocab_stats）。
type PackAnalysis struct {
	TokensTotal   int          `json:"tokens_total"`
	KnownCount    int          `json:"known_count"`
	KnownRate     float64      `json:"known_rate"`
	LevelHint     string       `json:"level_hint"`
	UnknownLemmas []LemmaCount `json:"unknown_lemmas"`
}

// PackGloss 是单个生词释义条目。
type PackGloss struct {
	Lemma   string `json:"lemma"`
	GlossZH string `json:"gloss_zh"`
	CEFR    string `json:"cefr"`
	Pos     string `json:"pos"`
}

// Pack 是 encounter-pack/v1 卡包，json 标签与 A2 Python 导入契约逐字段一致。
type Pack struct {
	Schema        string       `json:"schema"`
	PackID        string       `json:"pack_id"`
	Source        PackSource   `json:"source"`
	CreatedAt     string       `json:"created_at"`
	Article       PackArticle  `json:"article"`
	Analysis      PackAnalysis `json:"analysis"`
	Glosses       []PackGloss  `json:"glosses"`
	EstimatedCEFR string       `json:"estimated_cefr"`
}

// Validate 校验卡包结构，口径与 A2 Python `validate_pack`（缺必需键）+ 路由
// `_normalize_level`（estimated_cefr 白名单，大小写归一）一致：
//   - schema 必须固定为 encounter-pack/v1；
//   - pack_id 必填且非空白；
//   - article.title / article.raw_text 必填且非空白（article 为强类型恒存在）；
//   - estimated_cefr：只有**原本为空/缺失**的值才按 python 语义默认 A2；
//     一个非空但 trim 后为空白（如 "  "）的值是**非法**的（镜像 python 端
//     400——空白值既非白名单也不应被静默当作 A2）。非空白值 trim+upper 后
//     须落 A1|A2|B1 白名单。
//
// 不做估计等级之外的过度约束（analysis/glosses 允许空——与 python 落库一致）。
func (p *Pack) Validate() error {
	if p.Schema != CARD_PACK_SCHEMA {
		return fmt.Errorf("job: pack.schema 必须为 %q，收到 %q", CARD_PACK_SCHEMA, p.Schema)
	}
	if strings.TrimSpace(p.PackID) == "" {
		return fmt.Errorf("job: pack.pack_id 必填且不能为空")
	}
	if strings.TrimSpace(p.Article.Title) == "" {
		return fmt.Errorf("job: pack.article.title 必填且不能为空")
	}
	if strings.TrimSpace(p.Article.RawText) == "" {
		return fmt.Errorf("job: pack.article.raw_text 必填且不能为空")
	}
	// estimated_cefr：空/缺失（p.EstimatedCEFR==""）→ 默认 A2；否则视为显式值，
	// trim+upper 后须在白名单（非空白但 trim 为空的空白串因此被拒）。
	if p.EstimatedCEFR != "" {
		norm := strings.ToUpper(strings.TrimSpace(p.EstimatedCEFR))
		if !allowedCEFR[norm] {
			return fmt.Errorf("job: pack.estimated_cefr 仅支持 A1/A2/B1，收到 %q", p.EstimatedCEFR)
		}
	}
	return nil
}
