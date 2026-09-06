// Command delector 是 DeLector 的 Go Agent Runtime CLI 入口。
//
// Phase 2a Task 1 仅钉住脚手架契约：
//   - delector version  → 输出 "delector <semver>"
//   - delector run      → 占位，待 DAG scheduler（Task 4）接入后实现
//
// 架构见 docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md。
package main

import (
	"errors"
	"os"

	"github.com/spf13/cobra"
)

// version 为语义化版本号；输出与测试引用同一常量，防止契约漂移。
const version = "0.1.0"

// errNotImplemented 是 run 子命令的占位哨兵错误。
var errNotImplemented = errors.New("run: not implemented")

func newRootCmd() *cobra.Command {
	rootCmd := &cobra.Command{
		Use:   "delector",
		Short: "DeLector Go Agent Runtime（DAG 编排 + Python NLP 微服务）",
	}
	rootCmd.AddCommand(newVersionCmd(), newRunCmd())
	return rootCmd
}

func newVersionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "打印 delector 版本号",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cmd.Printf("delector %s\n", version)
			return nil
		},
	}
}

// newRunCmd 注册 run 子命令占位。
// TODO(phase2a-task4): 接入 DAG scheduler 后实现 --dag <name> 执行链路。
func newRunCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "run",
		Short: "执行一条预定义 DAG 工具链（尚未实现）",
		RunE: func(_ *cobra.Command, _ []string) error {
			return errNotImplemented
		},
	}
}

var rootCmd = newRootCmd()

func main() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
