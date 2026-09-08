// runner_guardrail_test.go 钉死 runner 的资源护栏默认语义（vault-team 评审 ④⑥）：
//   - cfg.Timeout<=0 归默认 defaultEncounterTimeout（2h 墙钟）；
//   - cfg.MaxFileBytes<=0 透传（不限），>0 时语料单文件超限被 corpus 阶段一排除。
//
// 纯函数层断言（不真跑 python/LLM）。
package job

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestResolveEncounterTimeout_Defaults(t *testing.T) {
	// 零值/负值 → 内置默认 2h 护栏（评审 ⑥：真跑没设限也不能无限期卡死）。
	for _, v := range []time.Duration{0, -1, -2 * time.Hour} {
		if got := resolveEncounterTimeout(v); got != defaultEncounterTimeout {
			t.Errorf("resolveEncounterTimeout(%v) = %s，期望默认 %s", v, got, defaultEncounterTimeout)
		}
	}
	// 显式正时长原样采用（CLI --timeout 覆盖护栏）。
	if got := resolveEncounterTimeout(45 * time.Minute); got != 45*time.Minute {
		t.Errorf("resolveEncounterTimeout(45m) = %s，期望 45m", got)
	}
	if got := defaultEncounterTimeout; got != 2*time.Hour {
		t.Errorf("defaultEncounterTimeout 应为 2h，实得 %s", got)
	}
}

// TestRunEncounter_MaxFileBytesSkipsOversized 评审 ④：cfg.MaxFileBytes>0 时
// 超大语料文件在扫描阶段一即被排除（不进内存/不进 pack）。此测试走 DryRun，
// 只依赖 corpus.ScanDir，不触 python/LLM。
func TestRunEncounter_MaxFileBytesSkipsOversized(t *testing.T) {
	root := t.TempDir()
	// 制造 3 个候选：big 远超 1KiB 护栏；small/ok 均 ≤ 护栏（ok 恰等于护栏应保留）。
	for name, content := range map[string]string{
		"big.txt":   strings.Repeat("x", 4096),
		"small.txt": "tiny",
		"ok.txt":    strings.Repeat("y", 1024),
	} {
		if err := os.WriteFile(filepath.Join(root, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	cfg := RunConfig{
		CorpusDir:    root,
		OutDir:       t.TempDir(),
		MaxFileBytes: 1024,
		DryRun:       true,
	}
	res, err := RunEncounterPack(context.Background(), nil, nil, cfg)
	if err != nil {
		t.Fatalf("RunEncounterPack(dry-run): %v", err)
	}
	if len(res.Packs) != 2 {
		t.Fatalf("超限文件应被排除，期望 2 篇（small+ok），实得 %d：%v", len(res.Packs), res.Packs)
	}
	for _, p := range res.Packs {
		if strings.HasSuffix(p, "big.txt") {
			t.Errorf("big.txt（超 1KiB 护栏）不应进清单：%v", res.Packs)
		}
	}
}
