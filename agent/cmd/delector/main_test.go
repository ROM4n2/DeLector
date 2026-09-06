package main

import (
	"bytes"
	"strings"
	"testing"
)

// TestVersionCommand 钉住 `delector version` 契约：
// 输出必须包含 "delector" 与语义化版本号（引用与实现同一常量）。
func TestVersionCommand(t *testing.T) {
	var out bytes.Buffer
	rootCmd.SetOut(&out)
	rootCmd.SetErr(&out)
	rootCmd.SetArgs([]string{"version"})

	if err := rootCmd.Execute(); err != nil {
		t.Fatalf("version 命令执行失败: %v", err)
	}

	got := out.String()
	if !strings.Contains(got, "delector") {
		t.Errorf("version 输出应包含 %q，实际输出: %q", "delector", got)
	}
	if !strings.Contains(got, version) {
		t.Errorf("version 输出应包含版本号 %q，实际输出: %q", version, got)
	}
}

// TestRunCommandNotImplemented 钉住 run 子命令占位契约：
// 本 Task（Phase 2a Task 1）只注册占位，调用必须返回 not implemented 错误。
func TestRunCommandNotImplemented(t *testing.T) {
	rootCmd.SetArgs([]string{"run"})
	err := rootCmd.Execute()
	if err == nil {
		t.Fatal("run 子命令为占位实现，执行应当返回错误")
	}
	if !strings.Contains(err.Error(), "not implemented") {
		t.Errorf("run 占位错误信息应包含 %q，实际错误: %v", "not implemented", err)
	}
}
