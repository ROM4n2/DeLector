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
// {".txt", ".md"}；MaxArticles<=0 表示不限数量。
type Options struct {
	// Extensions 是参与扫描的文件扩展名（含点）。匹配大小写不敏感：
	// ".txt" 亦纳入 ".TXT"（Windows 用户常见全大写扩展名）。
	// 空切片或 nil 视为默认 {".txt", ".md"}。
	Extensions []string
	// MaxArticles 是去重后允许保留的最大篇数；<=0 表示不限。
	MaxArticles int
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
// 语义（Sub-Plan B 定死）：
//  1. 递归扫描整个目录树；
//  2. 按扩展名过滤（默认 .txt/.md，大小写不敏感）；
//  3. 按 sha256(text) 去重——内容相同的保留首个出现者；
//  4. MaxArticles>0 时在去重后截断到最多该篇数；
//  5. 最终按 Path 排序（稳定）。
//
// 实现尊重 ctx：取消后尽快中止并返回 ctx.Err()（经 errors.Is 可判
// context.Canceled / context.DeadlineExceeded）。
func ScanDir(ctx context.Context, dir string, opts Options) ([]Article, error) {
	exts := opts.extensions()

	var arts []Article
	seen := make(map[string]struct{})
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

		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("corpus: read %s: %w", path, err)
		}
		text := string(data)
		h := hashText(text)
		if _, dup := seen[h]; dup {
			return nil // 内容重复，保首个，跳过本次
		}
		seen[h] = struct{}{}

		arts = append(arts, Article{
			Path:  path,
			Title: titleOf(path),
			Text:  text,
			Hash:  h,
		})
		return nil
	})
	if err != nil {
		// WalkDir 因 ctx 取消/超时而返回的错误需原样透传，使调用方可用
		// errors.Is(err, context.Canceled) / context.DeadlineExceeded 判定；
		// 其余文件错误亦原样返回（含路径上下文，供调用方定位）。
		return nil, err
	}

	// 截断（去重后、排序前）。
	if opts.MaxArticles > 0 && len(arts) > opts.MaxArticles {
		arts = arts[:opts.MaxArticles]
	}

	// 按 Path 排序（稳定）：sort.Slice 对相同 Path（本不会出现）之外的
	// 唯一键排序，天然稳定；此处按字符串升序。
	sort.Slice(arts, func(i, j int) bool {
		return arts[i].Path < arts[j].Path
	})

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
