// encounter.go 承载 job#1 的 encounter-pack 每篇内容生产 DAG 预设与便捷 runner：
// analyze → vocab_stats → gloss → export_pack，全部 fake 可单测（不碰 python/网络）。
//
// 数据流（每篇一 DAG，跨篇并发由 B6 runner 负责）：
//
//	input（=load 步骤产出）: {text, title, hash, path, file}
//	 1) analyze       依赖 load       → payload {text} → python analyze 输出
//	      （python analyze 产出含嵌套句子 token：顶层 sentences[]，每句 tokens[]，
//	        每个 token 携带 text/lemma/pos 字段——本预设据此展平映射给 vocab_stats）
//	 2) vocab_stats   依赖 analyze    → payload {tokens:[{text,lemma,pos},…]} → 覆盖统计
//	 3) gloss         依赖 vocab_stats+load → 先 Budget.Reserve(估算) 再 GlossLLM.Complete
//	      → GlossResult（EstimatedCEFR + Glosses）
//	 4) export_pack   依赖 gloss+vocab_stats+load → 组装 Pack → Validate → 原子落盘
//
// 落盘命名 / pack_id（确定性）：
//
//	文件名  = <slug(title)>-<hash8>.pack.json，目录自动创建
//	pack_id = <slug(title)>-<hash8>  （同文件名去扩展名，跨运行稳定）
//
// estimated_cefr 优先级：以 gloss 步骤 LLM 返回的 estimated_cefr 为准（ParseGlossLLMOutput
// 已归一 A1|A2|B1）；vocab_stats 的 level_hint 只写入 Pack.Analysis.LevelHint，不覆盖顶层。
//
// 同 outDir 已存在同名文件可被原子覆盖（写临时文件后 rename，rename 语义即覆盖）。
package job

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/ROM4n2/DeLector/agent/internal/corpus"
	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// EncounterDeps 是 DAG 步骤依赖的资源集合（registry / LLM / budget / 输出目录），
// 跨文章共享（B6 并发时同一实例被多个 Run 并发安全使用）。
type EncounterDeps struct {
	Reg    *registry.Registry // 注册 analyze / vocab_stats 工具（fake 或 python 实装）
	Gloss  GlossLLM           // 定级/释义 LLM（测试用 stub）
	Budget *TokenBudget       // gloss 步骤共享成本护栏
	OutDir string             // pack 落盘目录（自动创建）
}

// PackResult 是一次 RunOneArticle 成功落盘后的摘要。
type PackResult struct {
	Path   string // 落盘的绝对路径
	PackID string // 确定性 pack_id
}

// step 常量：DAG 节点 id（防拼写漂移，供 BuildEncounterDAG / 测试复用）。
const (
	stepLoad       = "load"
	stepAnalyze    = "analyze"
	stepVocabStats = "vocab_stats"
	stepGloss      = "gloss"
	stepExportPack = "export_pack"
)

// BuildEncounterDAG 构建 encounter-pack 每篇 DAG（load→analyze→vocab_stats→gloss→export_pack）。
// 构建一次即可被 RunOneArticle 重复、并发安全地 Run（文章数据经每次 Run 的 input 注入）。
// 入参工具名须与 registry 实际注册一致（analyze / vocab_stats），否则运行期经
// ErrUnknownTool 暴露。
func BuildEncounterDAG(d EncounterDeps) (*dag.DAG, error) {
	g := dag.NewDAG("encounter-pack")

	// load：把 Run 传入的 input（文章 map，含 text/title/hash/path/file）透传为根步骤产出，
	// 供 analyze/gloss/export_pack 经 deps["load"] 读取（无依赖步骤的 deps 即 input 浅拷贝）。
	load := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return deps, nil
	}
	if err := g.AddStep(stepLoad, load); err != nil {
		return nil, fmt.Errorf("job: encounter 预设构建失败: %w", err)
	}

	// analyze：payload {text} → python analyze。
	analyze := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		art, err := articleFromDeps(deps[stepLoad])
		if err != nil {
			return nil, err
		}
		return d.Reg.Run(ctx, "analyze", map[string]any{"text": art.Text})
	}
	if err := g.AddStep(stepAnalyze, analyze, stepLoad); err != nil {
		return nil, fmt.Errorf("job: encounter 预设构建失败: %w", err)
	}

	// vocab_stats：把 analyze 输出展平为 {text,lemma,pos} token 列表喂给工具。
	vocabStats := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		analyzeOut, ok := deps[stepAnalyze].(map[string]any)
		if !ok {
			return nil, errors.New("job: encounter analyze 输出不是 dict")
		}
		tokens := flattenAnalyzeTokens(analyzeOut)
		return d.Reg.Run(ctx, "vocab_stats", map[string]any{"tokens": tokens})
	}
	if err := g.AddStep(stepVocabStats, vocabStats, stepAnalyze); err != nil {
		return nil, fmt.Errorf("job: encounter 预设构建失败: %w", err)
	}

	// gloss：先 Reserve 再 GlossLLM.Complete → ParseGlossLLMOutput。
	gloss := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		art, err := articleFromDeps(deps[stepLoad])
		if err != nil {
			return nil, err
		}
		vs, ok := deps[stepVocabStats].(map[string]any)
		if !ok {
			return nil, errors.New("job: encounter vocab_stats 输出不是 dict")
		}
		req, err := glossRequestFromVocab(vs, art.Text)
		if err != nil {
			return nil, err
		}
		// 预算护栏：以实际入 prompt 的抽样文本估 token，超限即本步失败（不吞错）。
		// 评审 ③：Reserve 成功后若 LLM 调用失败/被取消，这次预留没有真正消耗
		// token，必须 Release 退回——否则连续失败的文章会逐步烧光共享预算。
		sampled := SampleText(req.Text)
		est := EstimateTokens(sampled)
		if err := d.Budget.Reserve(est); err != nil {
			return nil, err
		}
		system, user := BuildGlossPrompt(req)
		raw, err := d.Gloss.Complete(ctx, system, user)
		if err != nil {
			d.Budget.Release(est)
			return nil, err
		}
		res, err := ParseGlossLLMOutput(raw)
		if err != nil {
			// LLM 返回已到但解析失败：按未消耗退回（解析不产生 token）。
			d.Budget.Release(est)
			return nil, err
		}
		return map[string]any{"result": res}, nil
	}
	if err := g.AddStep(stepGloss, gloss, stepVocabStats, stepLoad); err != nil {
		return nil, fmt.Errorf("job: encounter 预设构建失败: %w", err)
	}

	// export_pack：组装 Pack → Validate → 原子落盘 → 返回 {path, pack_id}。
	export := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		art, err := articleFromDeps(deps[stepLoad])
		if err != nil {
			return nil, err
		}
		vs, ok := deps[stepVocabStats].(map[string]any)
		if !ok {
			return nil, errors.New("job: encounter vocab_stats 输出不是 dict")
		}
		glossMap, ok := deps[stepGloss].(map[string]any)
		if !ok {
			return nil, errors.New("job: encounter gloss 输出不是 dict")
		}
		glossRes, ok := glossMap["result"].(GlossResult)
		if !ok {
			return nil, errors.New("job: encounter gloss 缺 result")
		}

		p := assemblePack(art, vs, glossRes)
		if err := p.Validate(); err != nil {
			return nil, fmt.Errorf("job: encounter 组装 pack 校验失败: %w", err)
		}
		name := encounterFilename(art.Title, art.Hash)
		path := filepath.Join(d.OutDir, name)
		data, err := json.MarshalIndent(p, "", "  ")
		if err != nil {
			return nil, fmt.Errorf("job: encounter 序列化 pack: %w", err)
		}
		if err := writeAtomic(path, data); err != nil {
			return nil, fmt.Errorf("job: encounter 写 pack: %w", err)
		}
		return map[string]any{"path": path, "pack_id": p.PackID}, nil
	}
	if err := g.AddStep(stepExportPack, export, stepGloss, stepVocabStats, stepLoad); err != nil {
		return nil, fmt.Errorf("job: encounter 预设构建失败: %w", err)
	}

	return g, nil
}

// RunOneArticle 把单篇文章跑过一个已构建的 encounter DAG（g），返回落盘摘要。
// 文章数据经 input 注入，因此同一 g 可被并发 Run 多篇文章（B6 并发调度）。
func RunOneArticle(ctx context.Context, g *dag.DAG, a corpus.Article) (PackResult, error) {
	input := map[string]any{
		"text":  a.Text,
		"title": a.Title,
		"hash":  a.Hash,
		"path":  a.Path,
		"file":  filepath.Base(a.Path),
	}
	res, err := g.Run(ctx, input)
	if err != nil {
		return PackResult{}, err
	}
	exp, ok := res[stepExportPack].(map[string]any)
	if !ok {
		return PackResult{}, errors.New("job: encounter DAG 缺 export_pack 输出")
	}
	return PackResult{
		Path:   strOf(exp["path"]),
		PackID: strOf(exp["pack_id"]),
	}, nil
}

// ---- 文章 / 中间量访问 --------------------------------------------------------

// article 是 export 组装所需的文章元数据（从 load 产出 map 提取）。
type article struct {
	Text  string
	Title string
	Hash  string
	Path  string
	File  string
}

// articleFromDeps 从 load 步骤产出（map）解析出文章字段。load 的 key 与 Run input 一致。
func articleFromDeps(v any) (article, error) {
	m, ok := v.(map[string]any)
	if !ok {
		return article{}, errors.New("job: encounter load 输出不是 dict")
	}
	return article{
		Text:  strOf(m["text"]),
		Title: strOf(m["title"]),
		Hash:  strOf(m["hash"]),
		Path:  strOf(m["path"]),
		File:  strOf(m["file"]),
	}, nil
}

// flattenAnalyzeTokens 把 python analyze 产出（sentences[].tokens[].{text,lemma,pos}）
// 展平为喂给 vocab_stats 的 [{text,lemma,pos},…]。分析侧句子为嵌套结构，本处只做确定性
// 展平映射，不引入业务抽取。空输入允许（→ 空 token 列表，python 侧空输入按最乐观定级）。
func flattenAnalyzeTokens(analyzeOut map[string]any) []map[string]any {
	var out []map[string]any
	sentences, ok := analyzeOut["sentences"].([]any)
	if !ok {
		return out
	}
	for _, s := range sentences {
		sm, ok := s.(map[string]any)
		if !ok {
			continue
		}
		for _, tok := range asSlice(sm["tokens"]) {
			tm, ok := tok.(map[string]any)
			if !ok {
				continue
			}
			out = append(out, map[string]any{
				"text":  anyStr(tm["text"]),
				"lemma": anyStr(tm["lemma"]),
				"pos":   anyStr(tm["pos"]),
			})
		}
	}
	return out
}

// glossRequestFromVocab 从 vocab_stats 结果构建 GlossRequest（Text=抽样正文调用方自取，
// UnknownLemmas 来自 unknown_ranked，KnownRate 来自 known_rate）。
func glossRequestFromVocab(vs map[string]any, text string) (GlossRequest, error) {
	lemmas, err := toLemmaCounts(vs["unknown_ranked"])
	if err != nil {
		return GlossRequest{}, err
	}
	return GlossRequest{
		Text:          text,
		UnknownLemmas: lemmas,
		KnownRate:     floatOf(vs["known_rate"]),
	}, nil
}

// ---- Pack 组装 ----------------------------------------------------------------

// assemblePack 把各步骤结果组装成 encounter-pack/v1 Pack。
//
// estimated_cefr 优先级：gloss 步骤 LLM 返回的 EstimatedCEFR 为准（已归一，非空）；
// vocab_stats 的 level_hint 只进 Analysis.LevelHint，不覆盖顶层估计。
func assemblePack(a article, vs map[string]any, glossRes GlossResult) *Pack {
	unknownLemmas, _ := toLemmaCounts(vs["unknown_ranked"]) // 已在上游校验，此处忽略错误
	return &Pack{
		Schema:    CARD_PACK_SCHEMA,
		PackID:    packIDFor(a.Title, a.Hash),
		Source:    PackSource{Kind: "job1", Path: a.Path, File: a.File},
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
		Article: PackArticle{
			Title:     a.Title,
			RawText:   a.Text,
			CharCount: utf8.RuneCountInString(a.Text),
		},
		Analysis: PackAnalysis{
			TokensTotal:   intOf(vs["tokens_total"]),
			KnownCount:    intOf(vs["known_count"]),
			KnownRate:     floatOf(vs["known_rate"]),
			LevelHint:     strOf(vs["level_hint"]),
			UnknownLemmas: unknownLemmas,
		},
		Glosses:       glossRes.Glosses,
		EstimatedCEFR: glossRes.EstimatedCEFR,
	}
}

// ---- 确定性命名 / 落盘 ----------------------------------------------------------

// slug 把标题转成 ASCII 小写 kebab 段（音译常见德语变元音）；空/全符号回退 "untitled"。
func slug(title string) string {
	repl := strings.NewReplacer("ä", "ae", "ö", "oe", "ü", "ue", "ß", "ss")
	s := repl.Replace(strings.ToLower(strings.TrimSpace(title)))
	var sb strings.Builder
	lastDash := false
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			sb.WriteRune(r)
			lastDash = false
		default:
			if !lastDash {
				sb.WriteByte('-')
				lastDash = true
			}
		}
	}
	out := strings.Trim(sb.String(), "-")
	if out == "" {
		return "untitled"
	}
	return out
}

// hash8 取内容 sha256 的前 8 位十六进制作为短指纹。
func hash8(hash string) string {
	if len(hash) >= 8 {
		return hash[:8]
	}
	return hash
}

// packIDFor 返回确定性 pack_id = <slug>-<hash8>。
func packIDFor(title, hash string) string {
	return slug(title) + "-" + hash8(hash)
}

// encounterFilename 返回落盘文件名 <slug>-<hash8>.pack.json。
func encounterFilename(title, hash string) string {
	return packIDFor(title, hash) + ".pack.json"
}

// writeAtomic 先写临时文件再 rename 到最终路径：目录不存在则自动创建；rename 的替换
// 语义即允许覆盖已存在的同名文件（行为定义：existing file overwrite ok）。任一步失败
// 清理临时文件后返回错误。
func writeAtomic(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".encounter-*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() {
		if tmpName != "" {
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		return err
	}
	tmpName = "" // 成功：勿清理已 rename 的文件
	return nil
}

// ---- 通用类型提取小工具（python dict 经 JSON 解码为 map[string]any / []any） -------

func asSlice(v any) []any {
	switch t := v.(type) {
	case []any:
		return t
	case []map[string]any:
		out := make([]any, 0, len(t))
		for _, m := range t {
			out = append(out, m)
		}
		return out
	default:
		return nil
	}
}

func anyStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func strOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func intOf(v any) int {
	switch t := v.(type) {
	case int:
		return t
	case int64:
		return int(t)
	case float64:
		return int(t)
	default:
		return 0
	}
}

func floatOf(v any) float64 {
	switch t := v.(type) {
	case float64:
		return t
	case float32:
		return float64(t)
	case int:
		return float64(t)
	case int64:
		return float64(t)
	default:
		return 0
	}
}

// toLemmaCounts 把 unknown_ranked（[]any of map{lemma,count} 等形态）转成 []LemmaCount。
func toLemmaCounts(v any) ([]LemmaCount, error) {
	var out []LemmaCount
	for _, item := range asSlice(v) {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		out = append(out, LemmaCount{Lemma: strOf(m["lemma"]), Count: intOf(m["count"])})
	}
	return out, nil
}
