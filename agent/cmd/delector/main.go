// Command delector 是 DeLector 的 Go Agent Runtime CLI 入口。
//
// 子命令：
//   - delector version  → 输出 "delector <semver>"
//   - delector run      → 起 Python 托管进程 + 挂工具 registry + 暴露
//     article-analysis DAG 预设，常驻至 SIGINT/SIGTERM（Phase 2b T2 真实现）。
//
// 架构见 docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md。
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/ROM4n2/DeLector/agent/internal/app"
	"github.com/spf13/cobra"
)

// version 为语义化版本号；输出与测试引用同一常量，防止契约漂移。
const version = "0.1.0"

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

// newRunCmd 注册 run 子命令（Phase 2b T2 真实现）：起 Python 托管进程 +
// 挂工具 registry + 暴露 article-analysis DAG 预设，常驻至 Ctrl+C。
// 支持 --port / --data-dir flag。
func newRunCmd() *cobra.Command {
	var port int
	var dataDir string
	cmd := &cobra.Command{
		Use:   "run",
		Short: "起 Python 托管进程并暴露 article-analysis DAG 工具链（常驻至 Ctrl+C）",
		RunE: func(cmd *cobra.Command, _ []string) error {
			opts := app.Options{
				Port:           port,
				DataDir:        dataDir,
				PythonExtraEnv: extraEnvFromOS(),
			}
			// SIGINT/SIGTERM → ctx 取消 → supervisor 优雅退出（见 app.Run）。
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			return app.Run(ctx, opts)
		},
	}
	cmd.Flags().IntVar(&port, "port", 8001, "托管 Python 实例监听端口（默认 8001）")
	cmd.Flags().StringVar(&dataDir, "data-dir", "", "数据目录（注入 DATABASE_PATH / DELECTOR_DATA_DIR，空串跳过）")
	return cmd
}

// extraEnvFromOS 透传凭证类环境变量到托管 Python 子进程（仅环境变量，
// 绝不内嵌 key）。当前仅 DEEPSEEK_API_KEY；缺失则返回 nil（Run 自动补
// PYTHONIOENCODING / PYTHONPATH）。
func extraEnvFromOS() []string {
	if v := os.Getenv("DEEPSEEK_API_KEY"); v != "" {
		return []string{"DEEPSEEK_API_KEY=" + v}
	}
	return nil
}

var rootCmd = newRootCmd()

func main() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
