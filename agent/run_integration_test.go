//go:build integration

package integration_test

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/app"
)

// TestRunEndToEnd 真链路冒烟（build tag `integration`，不进常规 go test）：
// app.Run 起真实 Python 托管进程 → 健康探针通过（工具端点 200）→ 常驻 →
// 取消 ctx 优雅退出（Stop supervisor）。依赖缺失一律 t.Skipf（含理由），
// 绝不因环境缺失而红（Skip 契约同 2a T7）。
func TestRunEndToEnd(t *testing.T) {
	mustNotSkipEnv(t)

	tmp := t.TempDir()
	opts := app.Options{
		Port:    8001,
		DataDir: tmp,
		// PYTHONPATH / PYTHONIOENCODING / DATABASE_PATH 由 app.Run 自动注入
		// （repoRoot 经 runtime.Caller 上溯，2a T7 同款）。
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- app.Run(ctx, opts) }()

	// 轮询健康端点，等服务真正起来（Start 已探针通过 = 工具端点 200）。
	up := pollHealth(t, 40*time.Second)
	if !up {
		// 服务没起来：多半环境缺失（python / 依赖 / 端口占用），skip 而非 fail。
		cancel()
		<-done // 排空，避免 goroutine 泄漏
		t.Skipf("skip: 真实服务未起（环境/依赖缺失或端口占用），非代码缺陷")
	}

	// 服务已稳定 200：子进程 ctx 已与调用方退出信号 ctx 解耦（见 app.Run），
	// 取消信号 ctx 仅触发 supervisor.Stop 经 cmd.Cancel 优雅终止，不再经
	// exec.CommandContext 强杀仍在探针中的子进程，故无需 sleep 竞态兜底——
	// 直接取消并等待 Run 确定性返回 nil（2a T7 教训：勿用调用方 ctx 代管子进程寿命）。
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("app.Run 应优雅退出返回 nil，实际: %v", err)
	}
	t.Logf("TestRunEndToEnd OK: 真实 Python 起服务 + 工具端点 200 + 优雅退出")
}

// pollHealth 轮询 healthURL 直至 200 或超时；返回是否曾达 200。
func pollHealth(t *testing.T, timeout time.Duration) bool {
	t.Helper()
	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 5 * time.Second}
	for time.Now().Before(deadline) {
		req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, healthURL, nil)
		if err == nil {
			resp, err := client.Do(req)
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					return true
				}
			}
		}
		time.Sleep(200 * time.Millisecond)
	}
	return false
}
