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
	"path/filepath"
	"runtime"
	"syscall"

	"github.com/ROM4n2/DeLector/agent/internal/app"
	"github.com/spf13/cobra"
)

// defaultVersion 为语义化版本号默认常量；打包脚本可用
// -X main.version=... 覆盖下面的 version 变量。
const defaultVersion = "0.1.0"

// version 为语义化版本号；未注入时回落到 defaultVersion，注入后由
// -X main.version 覆盖（见打包脚本）。输出与测试引用同一变量，防止契约漂移。
var version = defaultVersion

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
			exe := exeDir()
			// DataDir 默认包目录（绿色便携包自包含数据；dev 模式未给
			// --data-dir 时也落到打包目录，绝不碰用户库）。
			dataDirResolved := dataDir
			if dataDirResolved == "" {
				dataDirResolved = exe
			}
			// 包内 venv python / 源根解析；dev 模式缺目录则回退系统 python
			// 与仓库根（2a T7 上溯），零改动。
			pythonExe := resolvePythonCmd(exe)
			srcDir := resolvePythonSrcDir(exe)
			cmd.Printf("[delector] python=%s src=%s data=%s\n", pythonExe, srcDir, dataDirResolved)
			opts := app.Options{
				Port:           port,
				DataDir:        dataDirResolved,
				PythonCmd:      pythonExe,
				PythonSrcDir:   srcDir,
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

// exeDir 返回当前可执行文件所在目录。绿色便携包下它就是 delector-agent/，
// 包内 python/（venv）、delector-src/（源根）、data（默认库目录）都相对它
// 解析；dev 模式取不到时回退 "."，不影响系统 python + 仓库根兜底。
func exeDir() string {
	if exe, err := os.Executable(); err == nil {
		if d := filepath.Dir(exe); d != "" {
			return d
		}
	}
	return "."
}

// resolvePythonCmd 解析包内 venv python 解释器：若 <exeDir>/python 目录存在
// 则取其中解释器，否则回退 "python"（系统解释器，dev 模式）。产制品必须走
// 包内 venv，不依赖系统 python（Phase 2b T3）。
//
// venv 解释器位置因 OS 而异：unix 为 python/bin/python；Windows 标准
// `python -m venv` 落在 python/Scripts/python.exe（Global Constraints 文字写
// 的 python/python.exe 仅当包被重排为嵌入式布局时才成立），故 Windows 优先
// 取计划所述顶层 python.exe，缺则回退 Scripts/python.exe，确保产制品总能用
// 包内 venv。
func resolvePythonCmd(exe string) string {
	pyDir := filepath.Join(exe, "python")
	if st, err := os.Stat(pyDir); err != nil || !st.IsDir() {
		return "python"
	}
	var candidates []string
	if runtime.GOOS == "windows" {
		candidates = []string{
			filepath.Join(pyDir, "python.exe"),
			filepath.Join(pyDir, "Scripts", "python.exe"),
		}
	} else {
		candidates = []string{filepath.Join(pyDir, "bin", "python")}
	}
	for _, c := range candidates {
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return "python"
}

// resolvePythonSrcDir 解析包内 python 源根：若 <exeDir>/delector-src 目录存在
// 则用之（含 delector 包 + static + start.py），经 PYTHONPATH 注入使 uvicorn
// 可 import delector.server:app；否则返回空串，由 app.Run 回退仓库根（2a T7
// 上溯），dev 模式零改动。
func resolvePythonSrcDir(exe string) string {
	src := filepath.Join(exe, "delector-src")
	if st, err := os.Stat(src); err == nil && st.IsDir() {
		return src
	}
	return ""
}

var rootCmd = newRootCmd()

func main() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
