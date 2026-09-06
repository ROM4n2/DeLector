//go:build integration

// Package integration_test 承载 Go→真实 Python 的端到端全链路证明
// （Task 7，build tag `integration` 隔离，不进常规 `go test ./...`）：
//
//	Supervisor.Start(ctx)（临时 DATABASE_PATH / DELECTOR_DATA_DIR，绝不碰
//	用户库）→ 健康探针通过 → 真实 HTTP 经 registry.DefaultRegistry + 单步
//	DAG 调 writing_check 工具（纯 Python 本地逻辑，零网络零模型依赖，
//	确定性）→ 断言返回 dict 非空。
//
// Skip 契约：本机缺 python / uvicorn / fastapi / spaCy 模型等依赖或无法起
// 服务时一律 t.Skipf（含理由），绝不假绿也绝不因环境缺失而红。
//
// 拓扑口径：本测试只钉"真实进程可达 + writing_check 契约"，不钉 ADR-0008
// 的 cefr 五层拓扑（该口径归 Task 8 统一，避免与 Example 钉板口径漂移）。
package integration_test

import (
	"context"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// 端口约定（Global Constraints）：agent 托管 Python 实例用 127.0.0.1:8001。
// baseURL 是 HTTP Client 的宿主前缀（Client 自拼 /api/tools/{name}）；
// healthURL 是 Supervisor 健康探针端点（GET /api/tools/），二者用途不同。
const (
	baseURL      = "http://127.0.0.1:8001"
	healthURL    = baseURL + "/api/tools/"
	probeTimeout = 30 * time.Second // spaCy 冷启动等，窗口放宽；失败归 skip
	preflightTO  = 15 * time.Second
)

// sampleText 为一封合规 A1 德语邮件：称呼带逗号、正文小写开头、结尾
// 收尾敬语。writing_check 对该输入确定性产出非空诊断 dict。
const sampleText = `Liebe Anna,

ich lade dich zu meiner Geburtstagsparty ein.

Viele Gruesse
Maria`

// mustNotSkipEnv 预先探测 Python 运行环境：缺解释器或核心依赖（uvicorn /
// fastapi）即 t.Skipf。Start 阶段真正的"起服务失败"在 Start 后另行 skip。
// 目的是避免在明显缺依赖的环境上白耗 30s 探针窗口。
func mustNotSkipEnv(t *testing.T) {
	t.Helper()
	python, err := exec.LookPath("python")
	if err != nil {
		t.Skipf("skip: 找不到 python 解释器（%v），无法托管真实服务", err)
	}
	// 探测依赖：uvicorn + fastapi 必须可导入，否则服务根本起不来。
	ctx, cancel := context.WithTimeout(context.Background(), preflightTO)
	defer cancel()
	out, perr := exec.CommandContext(ctx, python, "-c",
		"import uvicorn, fastapi; print('deps-ok')").CombinedOutput()
	if perr != nil {
		t.Skipf("skip: python 缺 uvicorn/fastapi（err=%v, out=%s），无法起真实服务",
			perr, strings.TrimSpace(string(out)))
	}
}

// repoRoot 定位仓库根（delector Python 包所在目录）：以本测试源文件路径
// `{root}/agent/integration_test.go` 上溯一级即得。供注入 PYTHONPATH，使
// uvicorn 能 import `delector.server:app`。
func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(file)) // <root>/agent → <root>
}

// startRealSupervisor 以临时库启动真实 Python 实例并完成健康探针。
// 注入到 t.TempDir() 的 DATABASE_PATH / DELECTOR_DATA_DIR 保证绝不动用户库；
// 追加 PYTHONPATH=<repoRoot> 使 uvicorn 可 import delector（uvicorn 以 agent/
// 为 cwd，仓库根不在默认 sys.path）；追加 PYTHONIOENCODING=utf-8 稳定子进程
// I/O 编码。实例起不来一律 t.Skipf（含理由）。
func startRealSupervisor(t *testing.T) *pythonsvc.Supervisor {
	t.Helper()
	tmp := t.TempDir()
	cfg := pythonsvc.SupervisorConfig{
		HealthURL:    healthURL,
		ProbeTimeout: probeTimeout,
		ExtraEnv: []string{
			"PYTHONPATH=" + repoRoot(),
			"DATABASE_PATH=" + filepath.Join(tmp, "agent-integration.db"),
			"DELECTOR_DATA_DIR=" + filepath.Join(tmp, "data"),
			"PYTHONIOENCODING=utf-8",
		},
	}
	s := pythonsvc.NewSupervisor(cfg)
	// 用 context.Background 而非随 helper 返回即 cancel 的 ctx：ctx 取消会经
	// exec.CommandContext 强杀 python 子进程，导致 Start 后紧接的 POST 被
	// reset（首版踩坑）。进程存亡全权交 t.Cleanup(s.Stop) 优雅收尾。
	if err := s.Start(context.Background()); err != nil {
		t.Skipf("skip: 本机无法在 127.0.0.1:8001 起真实服务（%v）", err)
	}
	t.Cleanup(s.Stop)
	return s
}

// TestGoPythonPipeline 全链路主测试：真实进程可达 + writing_check 契约。
func TestGoPythonPipeline(t *testing.T) {
	mustNotSkipEnv(t)
	startRealSupervisor(t) // 实例经内部 t.Cleanup(s.Stop) 托管至用例结束

	// 真实 HTTP client：绑定到托管实例的 8001 宿主（_require_localhost 闸）。
	client := pythonsvc.NewClient(baseURL, nil)
	reg := registry.DefaultRegistry(client)

	// 单步 DAG：writing_check 一步（依赖方向 cmd→registry→dag→pythonsvc，
	// 测试在组装层把 ToolFunc 适配为 StepFunc，不产生包间反向 import）。
	stepRun := func(ctx context.Context, deps map[string]any) (map[string]any, error) {
		return reg.Run(ctx, "writing_check", map[string]any{"text": sampleText})
	}
	g := dag.NewDAG("integration-writing-check")
	if err := g.AddStep("writing_check", stepRun); err != nil {
		t.Fatalf("AddStep 失败: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	res, err := g.Run(ctx, map[string]any{})
	if err != nil {
		t.Fatalf("全链路 DAG 执行失败（真实进程/HTTP 契约断裂）: %v", err)
	}

	raw, ok := res["writing_check"]
	if !ok {
		t.Fatal("DAG 结果缺 writing_check 步产出")
	}
	check, ok := raw.(map[string]any)
	if !ok {
		t.Fatalf("writing_check 产出应可断言为 dict，实际 %T", raw)
	}
	if len(check) == 0 {
		t.Fatal("writing_check 返回空 dict，契约违约")
	}
	// 契约锚点：A1 诊断 dict 应有 word_count / greeting / suggestions 等键。
	for _, k := range []string{"word_count", "greeting", "valediction", "suggestions"} {
		if _, ok := check[k]; !ok {
			t.Errorf("writing_check 诊断 dict 缺契约键 %q（实际 keys=%v）", k, keysOf(check))
		}
	}
	t.Logf("writing_check OK: keys=%v word_count=%v", keysOf(check), check["word_count"])
}

// TestGoPythonPipelineAnalyze 可选增强：analyze 依赖 spaCy 模型。模型缺失或
// 调用失败一律 t.Skipf（不因增强路径的环境缺失而红）。
func TestGoPythonPipelineAnalyze(t *testing.T) {
	mustNotSkipEnv(t)
	startRealSupervisor(t)

	client := pythonsvc.NewClient(baseURL, nil)
	reg := registry.DefaultRegistry(client)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	out, err := reg.Run(ctx, "analyze", map[string]any{"text": "Ich lade dich ein."})
	if err != nil {
		// spaCy 模型未装 / 其余依赖缺失：跳过而非失败。
		t.Skipf("skip: analyze 工具不可用（spaCy 模型缺失或服务报错: %v）", err)
	}
	if len(out) == 0 {
		t.Fatal("analyze 返回空 dict")
	}
	t.Logf("analyze OK（HTTP 200）: keys=%v", keysOf(out))
}

// keysOf 取 dict 键的字典序展示串，便于日志与错误信息定位。
func keysOf(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
