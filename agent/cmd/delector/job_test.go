// job_test.go 单测 `delector job run encounter-pack` 的 cobra 装配与校验。
//
// 纪律（Task B7）：不真跑 python、不触 LLM/网络。本文件只测：
//   - flag 解析（默认值 & 自定义值）；
//   - 缺 --corpus/--out 时 RunE/preRunE 的必填校验错误文案；
//   - `--help` 输出含 encounter-pack 子命令与父命令 job 的关键 flag/描述串；
//   - 命令构建函数返回的命令树（delector → job → run encounter-pack）。
//
// 真执行路径（supervisor spawn / registry / LLM / RunEncounterPack）属 B8 集成
// 门禁覆盖，本文件一律不触发 RunE 的真跑分支。
package main

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"github.com/spf13/cobra"
)

// runCmdSetArgs 把 args 装到共享 rootCmd 并抓取 stdout/stderr 到一个 buffer，
// 返回执行错误与合并输出。复用全局 rootCmd 时须先 SetOut/SetErr 到独立 buffer，
// 避免用例间串扰；其余命令状态（flag 值残留）不影响下列只读断言。
func runCmdSetArgs(t *testing.T, args ...string) (string, error) {
	t.Helper()
	var out bytes.Buffer
	rootCmd.SetOut(&out)
	rootCmd.SetErr(&out)
	rootCmd.SetArgs(args)
	err := rootCmd.Execute()
	return out.String(), err
}

// TestJobTree_BuilderReturnsExpectedChildren 钉死命令树：rootCmd 含 version/run/job；
// job 含 Name()=="run"（Use "run encounter-pack"）；父 job 帮助文案含两子命令描述。
func TestJobTree_BuilderReturnsExpectedChildren(t *testing.T) {
	root := newRootCmd()
	if !hasChild(root, "job") {
		t.Fatal("rootCmd 应含 job 子命令")
	}
	jobCmd := childOf(root, "job")
	if jobCmd == nil {
		t.Fatal("job 子命令不存在")
	}
	if !hasChild(jobCmd, "run") {
		t.Fatal("job 应含 run 子命令")
	}
	runCmd := childOf(jobCmd, "run")
	if !strings.Contains(runCmd.Use, "encounter-pack") {
		t.Errorf("job 的 run 子命令 Use 应含 encounter-pack，实际 %q", runCmd.Use)
	}
	// 父命令 job 仍保留既有 version/run 不被破坏。
	if !hasChild(root, "version") || !hasChild(root, "run") {
		t.Error("rootCmd 应同时保留 version 与 run 子命令")
	}
}

func hasChild(cmd *cobra.Command, name string) bool {
	for _, c := range cmd.Commands() {
		if c.Name() == name {
			return true
		}
	}
	return false
}

func childOf(cmd *cobra.Command, name string) *cobra.Command {
	for _, c := range cmd.Commands() {
		if c.Name() == name {
			return c
		}
	}
	return nil
}

// TestRunEncounter_FlagDefaults 断言 encounter-pack 子命令 flag 默认值。
func TestRunEncounter_FlagDefaults(t *testing.T) {
	runCmd := childOf(childOf(newRootCmd(), "job"), "run")
	if runCmd == nil {
		t.Fatal("job run 子命令不存在")
	}
	defaults := []struct {
		name string
		want string
	}{
		{"concurrency", "4"},
		{"max-articles", "200"},
		{"max-file-bytes", "1048576"},
		{"budget-tokens", "100000"},
		{"timeout", "0s"},
		{"dry-run", "false"},
		{"python-url", ""},
		{"deliver-url", "http://127.0.0.1:8000"},
		{"llm-base-url", ""},
	}
	for _, d := range defaults {
		f := runCmd.Flags().Lookup(d.name)
		if f == nil {
			t.Errorf("缺少 flag --%s", d.name)
			continue
		}
		if got := f.DefValue; got != d.want {
			t.Errorf("--%s 默认值 = %q，期望 %q", d.name, got, d.want)
		}
	}
}

// TestRunEncounter_FlagCustomValues 断言子命令 flag 可被 Set 到自定义值（解析路径）。
func TestRunEncounter_FlagCustomValues(t *testing.T) {
	runCmd := childOf(childOf(newRootCmd(), "job"), "run")
	fl := runCmd.Flags()
	if err := runCmd.ParseFlags([]string{
		"--corpus", "c", "--out", "o",
		"--concurrency", "8", "--max-articles", "3", "--budget-tokens", "999",
		"--max-file-bytes", "2048", "--timeout", "1h30m0s",
		"--dry-run",
		"--python-url", "http://x:9", "--deliver-url", "http://d", "--llm-base-url", "http://l",
	}); err != nil {
		t.Fatalf("解析 flag 失败: %v", err)
	}
	strCases := map[string]string{
		"corpus":       "c",
		"out":          "o",
		"python-url":   "http://x:9",
		"deliver-url":  "http://d",
		"llm-base-url": "http://l",
	}
	for name, want := range strCases {
		got, _ := fl.GetString(name)
		if got != want {
			t.Errorf("--%s = %q，期望 %q", name, got, want)
		}
	}
	intCases := map[string]int{
		"concurrency":   8,
		"max-articles":  3,
		"budget-tokens": 999,
	}
	for name, want := range intCases {
		got, _ := fl.GetInt(name)
		if got != want {
			t.Errorf("--%s = %d，期望 %d", name, got, want)
		}
	}
	maxFileBytes, _ := fl.GetInt64("max-file-bytes")
	if maxFileBytes != 2048 {
		t.Errorf("--max-file-bytes = %d，期望 2048", maxFileBytes)
	}
	timeout, _ := fl.GetDuration("timeout")
	if timeout != 90*time.Minute {
		t.Errorf("--timeout = %s，期望 1h30m0s", timeout)
	}
	dry, _ := fl.GetBool("dry-run")
	if !dry {
		t.Error("--dry-run 应解析为 true")
	}
}

// TestRunEncounter_MissingRequired 断言缺 --corpus / --out 时在装配 python 之前
// 就被必填校验拒绝（返回清晰错误，不触网不 spawn）。
func TestRunEncounter_MissingRequired(t *testing.T) {
	tests := []struct {
		name string
		args []string
		frag string
	}{
		{"缺 --corpus 与 --out", []string{"job", "run", "encounter-pack"}, "--corpus"},
		{"仅缺 --out", []string{"job", "run", "encounter-pack", "--corpus", "c"}, "--out"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := runCmdSetArgs(t, tt.args...)
			if err == nil {
				t.Fatalf("缺必填参数应返回错误，实际无错误; 输出=%q", got)
			}
			if !strings.Contains(err.Error(), tt.frag) {
				t.Errorf("错误应含 %q，实际: %v", tt.frag, err)
			}
			// 缺参路径不得产出任何 run 输出（确认在 spawn/执行前被拦）。
			if strings.Contains(got, "[delector]") {
				t.Errorf("必填校验失败不应有执行输出，实际: %q", got)
			}
		})
	}
}

// TestRunEncounter_HelpContainsFlags 断言 `--help` 输出含 encounter-pack 描述串
// 与各关键 flag 名（含必填与默认说明）。
func TestRunEncounter_HelpContainsFlags(t *testing.T) {
	got, err := runCmdSetArgs(t, "job", "run", "encounter-pack", "--help")
	if err != nil {
		t.Fatalf("--help 应成功（返回 nil），实际: %v", err)
	}
	// cobra help 走 stdout（rootCmd.Out）。
	for _, frag := range []string{
		"encounter-pack", "corpus", "out",
		"concurrency", "max-articles", "max-file-bytes",
		"budget-tokens", "timeout", "dry-run",
		"python-url", "deliver-url", "llm-base-url",
	} {
		if !strings.Contains(got, frag) {
			t.Errorf("encounter-pack --help 应含 %q，实际输出:\n%s", frag, got)
		}
	}
}

// TestJobParent_HelpContainsDescriptions 断言父命令 `job --help` 列出
// encounter-pack 子命令及其中文描述串。
func TestJobParent_HelpContainsDescriptions(t *testing.T) {
	got, err := runCmdSetArgs(t, "job", "--help")
	if err != nil {
		t.Fatalf("job --help 应成功，实际: %v", err)
	}
	for _, frag := range []string{
		"job", "encounter-pack", "内容生产",
	} {
		if !strings.Contains(got, frag) {
			t.Errorf("job --help 应含 %q，实际输出:\n%s", frag, got)
		}
	}
}

// TestRunCommandStartupValidationAfterJobAdded 复用 run 命令的启动校验用例语义，
// 确认新增 job 命令未破坏既有 `delector run` 的装配前参数校验（run 回归哨兵）。
func TestRunCommandStartupValidationAfterJobAdded(t *testing.T) {
	got, err := runCmdSetArgs(t, "run", "--port", "70000")
	if err == nil {
		t.Fatal("run 对非法 --port 应返回启动失败错误")
	}
	if strings.Contains(err.Error(), "not implemented") {
		t.Errorf("run 不应再返回 not implemented，实际错误: %v", err)
	}
	_ = got
}
