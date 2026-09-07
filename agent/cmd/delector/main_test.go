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

// TestRunCommandStartupValidation 断言 run 启动失败路径（参数校验）：
// Phase 2b T2 后 run 已真实现；非法 --port 在装配前被 validateOpts 拒绝，
// 必须返回错误且不含「not implemented」占位哨兵。此测试不触网（失败发生在
// 起 Python 之前），保证常规 `go test ./...` 快速且确定性绿。
func TestRunCommandStartupValidation(t *testing.T) {
	rootCmd.SetArgs([]string{"run", "--port", "70000"})
	err := rootCmd.Execute()
	if err == nil {
		t.Fatal("run 子命令对非法 --port 应返回启动失败错误")
	}
	if strings.Contains(err.Error(), "not implemented") {
		t.Errorf("run 已实现，不应再返回 not implemented，实际错误: %v", err)
	}
}
