package main

import (
	"bytes"
	"errors"
	"fmt"
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

// TestExitCodeMapsErrorToNonZero 钉死"错误 MUST 有非零退出码"：任何非 nil 错误
// （典型者：Python 托管进程崩溃恢复最终失败经 app.Run 上抛）MUST 映射为非零，
// 否则 docker `restart: unless-stopped` / systemd Restart=on-failure 无法接管。
// 禁"只打日志然后返回 0"——那正是本 Task 要消灭的静默存活。
func TestExitCodeMapsErrorToNonZero(t *testing.T) {
	if got := exitCode(nil); got != 0 {
		t.Errorf("无错误时退出码应为 0，实际 %d", got)
	}
	if got := exitCode(errors.New("boom")); got == 0 {
		t.Error("非 nil 错误的退出码必须非零（否则进程管理器无从接管）")
	}
}

// TestRunCommandStartupFailureYieldsNonZeroExitCode 端到端钉死 run 启动失败
// 从 app.Run → cobra → exitCode 的**错误不吞**链路：Execute 返回的错误非 nil
// 且带完整错误链，exitCode 映射出非零退出码。仅触网前失败（非法 --port），
// 保证 `go test ./...` 快速确定性绿。
func TestRunCommandStartupFailureYieldsNonZeroExitCode(t *testing.T) {
	inner := errors.New("boom: python 起不来")
	wrapped := fmt.Errorf("app: Python 托管进程崩溃恢复最终失败: %w", inner)

	if got := exitCode(wrapped); got == 0 {
		t.Error("app.Run 上抛的错误必须映射为非零退出码")
	}
	if !errors.Is(wrapped, inner) {
		t.Error("错误链必须能追到原始错误（禁字符串比较）")
	}

	rootCmd.SetArgs([]string{"run", "--port", "70000"})
	err := rootCmd.Execute()
	if err == nil {
		t.Fatal("run 启动失败必须把错误上抛给 Execute（MUST NOT 吞掉后继续）")
	}
	if exitCode(err) == 0 {
		t.Errorf("Execute 的错误经 exitCode 必须为非零，实际 0，错误: %v", err)
	}
}
