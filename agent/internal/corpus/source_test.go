package corpus

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// writeFile 在 fixture 目录下创建 path（相对）内容为 content 的文本文件，
// 自动创建父目录。
func writeFile(t *testing.T, root, path, content string) {
	t.Helper()
	full := filepath.Join(root, path)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(full), err)
	}
	if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", full, err)
	}
}

// sampleFixture 构造基本语料目录：
//   - hello.txt：A.txt 与其内容相同但不同名的 A_dup.txt（同目录重复→应去重保首个）
//   - B.TXT：扩展名大写（验证大小写不敏感过滤）
//   - nested/C.md：子目录下文件（验证递归）
//   - skip.json：无关扩展名（应被过滤）
//
// 返回各文件路径供断言。
func sampleFixture(t *testing.T) (root string, paths []string) {
	t.Helper()
	root = t.TempDir()
	writeFile(t, root, "A.txt", "hello world a")
	writeFile(t, root, "A_dup.txt", "hello world a") // 与 A.txt 内容相同
	writeFile(t, root, "B.TXT", "hello world b")
	writeFile(t, root, "nested/C.md", "# nested markdown c")
	writeFile(t, root, "skip.json", `{"not":"an article"}`)
	for _, p := range []string{"A.txt", "A_dup.txt", "B.TXT", "nested/C.md", "skip.json"} {
		paths = append(paths, filepath.Join(root, p))
	}
	return root, paths
}

// articlePaths 提取排序后的 article.Path 列表，便于断言排序结果。
func articlePaths(arts []Article) []string {
	out := make([]string, 0, len(arts))
	for _, a := range arts {
		out = append(out, a.Path)
	}
	sort.Strings(out) // 仅用于成员比较（忽略顺序），顺序断言另行比较
	return out
}

func pathExists(paths []string, name string) bool {
	for _, p := range paths {
		if strings.HasSuffix(p, name) {
			return true
		}
	}
	return false
}

func TestScanDir_RecurseFilterDedupeSort(t *testing.T) {
	root, _ := sampleFixture(t)
	arts, err := ScanDir(context.Background(), root, Options{})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}

	// 过滤：应得 A.txt、A_dup.txt(去重后只留一个)、B.TXT、nested/C.md，skip.json 排除。
	got := articlePaths(arts)
	if len(arts) != 3 {
		t.Fatalf("期望 3 篇（A 与重复合并、B、C），实得 %d：%v", len(arts), got)
	}

	// 去重 keep-first：同内容只留一篇，且保留的是走查先出现的 A.txt（而非 A_dup.txt）。
	var keptA bool
	for _, a := range arts {
		switch {
		case a.Path == filepath.Join(root, "A.txt"):
			keptA = true
		case a.Path == filepath.Join(root, "A_dup.txt"):
			t.Errorf("重复内容不应保留后到者 %s", a.Path)
		}
	}
	if !keptA {
		t.Errorf("去重应保留首个出现者 A.txt，实得：%v", got)
	}

	// 扩展名大小写不敏感：.TXT 应被纳入。
	if !pathExists(got, "B.TXT") {
		t.Errorf("B.TXT（大写扩展名）应被纳入，实得：%v", got)
	}
	// 递归：子目录 nested/C.md 应被纳入。
	if !pathExists(got, "nested"+string(filepath.Separator)+"C.md") {
		t.Errorf("子目录 nested/C.md 应被纳入，实得：%v", got)
	}
	// 无关扩展名 .json 应被过滤。
	if pathExists(got, "skip.json") {
		t.Errorf("skip.json 应被过滤，实得：%v", got)
	}

	// 排序：最终按 Path 升序（绝对路径）。A.txt、B.TXT、nested/C.md 的词典序应为
	// A.txt < B.TXT < nested/C.md。
	expected := []string{
		filepath.Join(root, "A.txt"),
		filepath.Join(root, "B.TXT"),
		filepath.Join(root, "nested", "C.md"),
	}
	sort.Strings(expected) // 依赖系统排序规则生成期望序
	if !equalStringSlice(pathStrings(arts), expected) {
		t.Errorf("按路径排序结果不符：\n got  %v\n want %v", pathStrings(arts), expected)
	}
}

// pathStrings 保持 arts 现有顺序取出 Path（断言排序用）。
func pathStrings(arts []Article) []string {
	out := make([]string, 0, len(arts))
	for _, a := range arts {
		out = append(out, a.Path)
	}
	return out
}

func equalStringSlice(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestScanDir_ArticleFields(t *testing.T) {
	root, _ := sampleFixture(t)
	arts, err := ScanDir(context.Background(), root, Options{})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}
	byPath := map[string]Article{}
	for _, a := range arts {
		byPath[a.Path] = a
	}
	a, ok := byPath[filepath.Join(root, "A.txt")]
	if !ok {
		t.Fatalf("A.txt 缺失")
	}
	if a.Title != "A" {
		t.Errorf("Title=文件名去扩展，期望 A，实得 %q", a.Title)
	}
	if a.Text != "hello world a" {
		t.Errorf("Text 不符，实得 %q", a.Text)
	}
	if a.Hash == "" {
		t.Errorf("Hash 不应为空")
	}
	// sha256 是 64 位十六进制。
	if len(a.Hash) != 64 {
		t.Errorf("Hash 应为 64 位 hex，实得长度 %d", len(a.Hash))
	}
}

func TestScanDir_DedupeByHash(t *testing.T) {
	root := t.TempDir()
	// 不同目录下同样内容也应按 hash 去重（跨目录重复）。
	writeFile(t, root, "x/one.txt", "identical body")
	writeFile(t, root, "y/two.txt", "identical body")
	writeFile(t, root, "y/diff.txt", "different body")
	arts, err := ScanDir(context.Background(), root, Options{})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}
	// 只应剩 2 篇（identical 去重 + different）。
	if len(arts) != 2 {
		t.Fatalf("跨目录同内容应去重，期望 2 篇，实得 %d", len(arts))
	}
}

func TestScanDir_MaxArticlesTruncate(t *testing.T) {
	root := t.TempDir()
	for _, n := range []string{"m1", "m2", "m3", "m4"} {
		writeFile(t, root, n+".txt", "content-"+n)
	}
	arts, err := ScanDir(context.Background(), root, Options{MaxArticles: 2})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}
	if len(arts) != 2 {
		t.Fatalf("MaxArticles=2 应截断到 2，实得 %d", len(arts))
	}
}

func TestScanDir_MaxArticlesZeroUnlimited(t *testing.T) {
	root := t.TempDir()
	for _, n := range []string{"m1", "m2", "m3"} {
		writeFile(t, root, n+".txt", "content-"+n)
	}
	// MaxArticles<=0 表示不限：0 与负数均不截断。
	for _, m := range []int{0, -1} {
		arts, err := ScanDir(context.Background(), root, Options{MaxArticles: m})
		if err != nil {
			t.Fatalf("ScanDir(Max=%d): %v", m, err)
		}
		if len(arts) != 3 {
			t.Fatalf("Max=%d 应不限，期望 3，实得 %d", m, len(arts))
		}
	}
}

func TestScanDir_CustomExtensions(t *testing.T) {
	root := t.TempDir()
	writeFile(t, root, "a.txt", "text body")
	writeFile(t, root, "b.md", "markdown body")
	writeFile(t, root, "c.go", "code body")
	// 自定义只收 .go。
	arts, err := ScanDir(context.Background(), root, Options{Extensions: []string{".go"}})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}
	if len(arts) != 1 || !strings.HasSuffix(arts[0].Path, "c.go") {
		t.Fatalf("仅 .go 应被纳入，实得 %d：%v", len(arts), pathStrings(arts))
	}
}

// TestScanDir_MaxFileBytes_SkipsOversized 评审 ④：MaxFileBytes>0 时单文件超限
// 在登记候选阶段即被排除（不读不进内存）；大小恰等于护栏的文件应保留。
func TestScanDir_MaxFileBytes_SkipsOversized(t *testing.T) {
	root := t.TempDir()
	writeFile(t, root, "big.txt", strings.Repeat("x", 4096))
	writeFile(t, root, "small.txt", "tiny body")
	writeFile(t, root, "boundary.txt", strings.Repeat("y", 1024))
	arts, err := ScanDir(context.Background(), root, Options{MaxFileBytes: 1024})
	if err != nil {
		t.Fatalf("ScanDir: %v", err)
	}
	if len(arts) != 2 {
		t.Fatalf("超限文件应被排除：期望 2 篇（small+boundary），实得 %d：%v", len(arts), pathStrings(arts))
	}
	for _, a := range arts {
		if strings.HasSuffix(a.Path, "big.txt") {
			t.Errorf("big.txt（4096>1024）不应进入结果：%v", pathStrings(arts))
		}
	}
}

// TestScanDir_MaxFileBytesZeroUnlimited MaxFileBytes<=0 表示不限（0 与负值）。
func TestScanDir_MaxFileBytesZeroUnlimited(t *testing.T) {
	root := t.TempDir()
	writeFile(t, root, "big.txt", strings.Repeat("x", 3000))
	for _, capB := range []int64{0, -5} {
		arts, err := ScanDir(context.Background(), root, Options{MaxFileBytes: capB})
		if err != nil {
			t.Fatalf("ScanDir(MaxFileBytes=%d): %v", capB, err)
		}
		if len(arts) != 1 {
			t.Fatalf("MaxFileBytes=%d 应不限（含大文件），期望 1 篇，实得 %d", capB, len(arts))
		}
	}
}

func TestScanDir_ContextCancel(t *testing.T) {
	root := t.TempDir()
	writeFile(t, root, "a.txt", "body a")
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // 预先取消
	_, err := ScanDir(ctx, root, Options{})
	if err == nil {
		t.Fatalf("已取消的 ctx 应返回错误")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("应返回 context.Canceled，实得 %v", err)
	}
}

func TestScanDir_NonexistentDir(t *testing.T) {
	_, err := ScanDir(context.Background(), filepath.Join(t.TempDir(), "does-not-exist"), Options{})
	if err == nil {
		t.Fatalf("不存在的目录应报错")
	}
}
