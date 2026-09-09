// Package corpus 提供本地语料目录扫描：递归读取 .txt/.md 文本文件，
// 按 sha256 去重、限量并稳定排序，产出可入 DAG 的 Article 列表。
//
// 纯 Go 本地文件读取，不引入 URL 抓取/HTTP（URL→html ingest 属后续 feed
// 扩展，见 Sub-Plan B 约束）。本包供 job#1（encounter-pack）消费。
package corpus

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Article 是一篇已读取的语料文本。
type Article struct {
	Path  string // 磁盘绝对路径（去重后作稳定排序键）
	Title string // 标题 = 文件名去扩展名（如 a.md → "a"）
	Text  string // 正文原文
	Hash  string // sha256(Text) 的 64 位十六进制，用于内容去重
}

// Options 控制 ScanDir 的行为。零值即默认：Extensions 为空时默认
// {".txt", ".md"}；MaxArticles/MaxFileBytes<=0 表示不限。
type Options struct {
	// Extensions 是参与扫描的文件扩展名（含点）。匹配大小写不敏感：
	// ".txt" 亦纳入 ".TXT"（Windows 用户常见全大写扩展名）。
	// 空切片或 nil 视为默认 {".txt", ".md"}。
	Extensions []string
	// MaxArticles 是读取前截断候选后的最大篇数上限（内存护栏，见 ScanDir
	// 语义 4）；<=0 表示不限。
	MaxArticles int
	// MaxFileBytes 是单文件内容大小上限（字节）：登记候选时即排除超限文件，
	// 绝不让单篇巨文进内存（评审 ④ 单文件护栏）；<=0 表示不限。
	MaxFileBytes int64
}

// defaultExtensions 是空 Extensions 时的兜底。
var defaultExtensions = []string{".txt", ".md"}

// extensions 归一化 opts.Extensions：空则回退默认，并把每个扩展名
// 统一为小写（配合大小写不敏感的按扩展过滤）。
func (o Options) extensions() []string {
	exts := o.Extensions
	if len(exts) == 0 {
		exts = defaultExtensions
	}
	out := make([]string, 0, len(exts))
	for _, e := range exts {
		e = strings.ToLower(strings.TrimSpace(e))
		if e != "" {
			out = append(out, e)
		}
	}
	if len(out) == 0 {
		out = append(out, defaultExtensions...)
	}
	return out
}

// hashText 返回 text 的 sha256 十六进制串。
func hashText(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

// ScanDir 递归扫描 dir，收集符合 Options 的文本文件并返回排序去重后的
// Article 列表。
//
// 语义（Sub-Plan B B2 + vault-team 评审 ④ 两阶段有界扫描）：
//  1. 阶段一只登记候选路径（WalkDir 全程不读文件内容），按扩展名过滤
//     （默认 .txt/.md，大小写不敏感）；单文件超过 MaxFileBytes（>0）时
//     当场排除——**先按字节筛，再谈读**；
//  2. 阶段二按路径稳定排序（去重 keep-first 判定键 = 排后的路径序），
//     若 MaxArticles>0 则在**读取前**截断候选——读取的内存上界至多为
//     MaxArticles 个文件，绝不先把整目录全量读入再截断（评审 ④）；
//  3. 逐文件读取：sha256(text) 内容去重（同内容保留排序序靠前者）；
//  4. 返回按 Path 升序的 Article 列表。
//
// 截断先于去重执行，故返回篇数可能少于 MaxArticles（重复内容消耗名额）。
//
// 实现尊重 ctx：取消后尽快中止并返回 ctx.Err()（经 errors.Is 可判
// context.Canceled / context.DeadlineExceeded）。读取阶段错误（含 stat/读
// 权限失败）带路径上下文原样返回，与既往语义一致。
func ScanDir(ctx context.Context, dir string, opts Options) ([]Article, error) {
	exts := opts.extensions()

	// 阶段一：登记候选（只 walk 不读）。dir 错误/权限错误在此阶段冒出。
	var cands []string
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, walkErr error) error {
		if ctx.Err() != nil {
			return ctx.Err() // 中止遍历，向上冒泡 ctx 错误
		}
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		if !d.Type().IsRegular() {
			return nil // 只读普通文件（跳过符号链接/设备等）
		}
		if !extMatch(path, exts) {
			return nil // 扩展名不过滤器
		}
		if opts.MaxFileBytes > 0 {
			info, err := d.Info()
			if err != nil {
				return fmt.Errorf("corpus: stat %s: %w", path, err)
			}
			if info.Size() > opts.MaxFileBytes {
				return nil // 单文件超护栏：不读不进内存（评审 ④）
			}
		}
		cands = append(cands, path)
		return nil
	})
	if err != nil {
		// WalkDir 因 ctx 取消/超时而返回的错误需原样透传，使调用方可用
		// errors.Is(err, context.Canceled) / context.DeadlineExceeded 判定；
		// 其余文件错误亦原样返回（含路径上下文，供调用方定位）。
		return nil, err
	}

	// 阶段二：排序 → 读取前截断（内存护栏）→ 逐文件读取去重。
	sort.Strings(cands)
	if opts.MaxArticles > 0 && len(cands) > opts.MaxArticles {
		cands = cands[:opts.MaxArticles]
	}

	seen := make(map[string]struct{}, len(cands))
	arts := make([]Article, 0, len(cands))
	for _, path := range cands {
		if ctx.Err() != nil {
			return nil, ctx.Err() // 读取途中被取消
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("corpus: read %s: %w", path, err)
		}
		text := string(data)
		h := hashText(text)
		if _, dup := seen[h]; dup {
			continue // 内容重复，保排序序靠前者，跳过本次
		}
		seen[h] = struct{}{}
		arts = append(arts, Article{
			Path:  path,
			Title: titleOf(path),
			Text:  text,
			Hash:  h,
		})
	}
	return arts, nil
}

// extMatch 报告 path 的扩展名（含点，小写）是否在 exts 集合内。
func extMatch(path string, exts []string) bool {
	ext := strings.ToLower(filepath.Ext(path))
	for _, e := range exts {
		if ext == e {
			return true
		}
	}
	return false
}

// titleOf 返回文件名去掉扩展名的部分：a.md → "a"；无扩展名时返回全名。
func titleOf(path string) string {
	base := filepath.Base(path)
	ext := filepath.Ext(base)
	if ext == "" {
		return base
	}
	return strings.TrimSuffix(base, ext)
}
