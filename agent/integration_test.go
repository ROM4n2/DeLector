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
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/dag"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/ROM4n2/DeLector/agent/internal/registry"
)

// 端口口径（本任务修订，原为硬编码 127.0.0.1:8001 的"端口约定"）：agent 托管
// Python 实例默认走**动态空闲端口**（resolvePort 经 net.Listen("127.0.0.1:0")
// 取端口）—— 从根上消除与任何外来进程撞车：撞车会让门禁把业务请求打到别人的
// 服务上，替别人的服务背书（假绿）或收到别人的应答（假红）。8001 退化为可覆盖
// 的默认值：仅在显式设置 DELECTOR_AGENT_TEST_PORT 时使用（复现"端口被占"的失败
// 语义用）。baseURL 是 HTTP Client 的宿主前缀（Client 自拼 /api/tools/{name}），
// 由 startRealSupervisor 每次运行注入当前端口；健康探针端点亦据当前端口拼出。
var baseURL = fmt.Sprintf("http://127.0.0.1:%d", defaultPort)

// defaultPort 是端口后备默认值（8001：Global Constraints 端口约定）。正常运行
// 不使用它：端口由 DELECTOR_AGENT_TEST_PORT 覆盖或由内核动态分配。
const defaultPort = 8001

const (
	probeTimeout = 30 * time.Second // spaCy 冷启动等，窗口放宽；失败归 skip
	preflightTO  = 15 * time.Second
)

// sampleText 为一封合规 A1 德语邮件：称呼带逗号、正文小写开头、结尾
// 收尾敬语。writing_check 对该输入确定性产出非空诊断 dict。
const sampleText = `Liebe Anna,

ich lade dich zu meiner Geburtstagsparty ein.

Viele Gruesse
Maria`

// pythonEnvKey 是显式覆盖 Python 解释器的环境变量：设置后作为最高优先候选。
// 注意它不是"信任即用"——候选即使来自显式覆盖，仍 MUST 实测依赖（见 mustNotSkipEnv）。
const pythonEnvKey = "DELECTOR_PYTHON"

// pythonCandidates 返回解释器候选链（按优先级）：$DELECTOR_PYTHON（显式覆盖）
// → python3 → python。名字层面"看起来对"不代表依赖可用，故调用方 MUST 逐个实测。
func pythonCandidates() []string {
	cands := make([]string, 0, 3)
	if v := os.Getenv(pythonEnvKey); v != "" {
		cands = append(cands, v)
	}
	return append(cands, "python3", "python")
}

// mustNotSkipEnv 逐候选探测 Python 运行环境并**返回选定的解释器路径**：候选顺序
// 为 $DELECTOR_PYTHON（显式覆盖，最高优先）→ python3 → python；对每个候选 MUST
// **实测** `-c "import uvicorn, fastapi"`（短超时，绝不让探测挂住门禁），第一个通过
// 者即为选定解释器；全部候选都不行才 t.Skipf，且诊断 MUST 逐个列出候选及其失败原因。
//
// 设计动因（ADR-0023 §4.4 红灯② 修正）：此前硬编码 `LookPath("python")` 单名探测——
// 若该名字对应的解释器恰好缺依赖即恒 skip（拿不到真实信号），且该缺陷与 shell/PATH
// 强相关（本机 `python` 带依赖时缺陷不复现）。"只看名字"不可靠，故必须**实测依赖**。
//
// 返回的路径 MUST 传给起服路径（startRealSupervisor 的 PythonCmd / app.Options.
// PythonCmd），否则会出现"探测用一个解释器、起服却用另一个"的新型静默失败。
func mustNotSkipEnv(t *testing.T) string {
	t.Helper()
	var diags []string
	for _, cand := range pythonCandidates() {
		path, err := exec.LookPath(cand)
		if err != nil {
			diags = append(diags, fmt.Sprintf("  - %q：PATH 上找不到（%v）", cand, err))
			continue
		}
		// 实测依赖：uvicorn + fastapi 必须可导入，否则服务根本起不来。逐候选
		// 独立短超时，避免某个候选挂住拖垮整轮探测。
		ctx, cancel := context.WithTimeout(context.Background(), preflightTO)
		out, perr := exec.CommandContext(ctx, path, "-c",
			"import uvicorn, fastapi; print('deps-ok')").CombinedOutput()
		cancel()
		if perr != nil {
			diags = append(diags, fmt.Sprintf("  - %q（%s）：缺 uvicorn/fastapi（err=%v, out=%s）",
				cand, path, perr, strings.TrimSpace(string(out))))
			continue
		}
		t.Logf("选定 Python 解释器：候选 %q → %s（uvicorn/fastapi 实测可导入）", cand, path)
		return path
	}
	t.Skipf("skip: 无可用 Python 解释器（候选逐个实测依赖均失败），无法托管真实服务：\n%s",
		strings.Join(diags, "\n"))
	return "" // 不可达：t.Skipf 经 runtime.Goexit 终止用例；此行仅为满足编译器
}

// repoRoot 定位仓库根（delector Python 包所在目录）：以本测试源文件路径
// `{root}/agent/integration_test.go` 上溯一级即得。供注入 PYTHONPATH，使
// uvicorn 能 import `delector.server:app`。
func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(file)) // <root>/agent → <root>
}

// startRealSupervisor 以临时库、动态空闲端口启动真实 Python 实例，完成健康探针
// 并校验身份。注入到 t.TempDir() 的 DATABASE_PATH / DELECTOR_DATA_DIR 保证绝不
// 动用户库；追加 PYTHONPATH=<repoRoot> 使 uvicorn 可 import delector（uvicorn 以
// agent/ 为 cwd，仓库根不在默认 sys.path）；追加 PYTHONIOENCODING=utf-8 稳定子
// 进程 I/O 编码。
//
// 失败语义（本任务修订）：
//   - 起服失败（端口被占/绑定失败/依赖缺失）→ 立刻 t.Skipf 并给可操作诊断，
//     **绝不继续发任何业务请求**（否则请求会打到占用该端口的外来进程上）。
//   - 起服成功后 MUST 校验身份（assertSupervisorIdentity）：确认端口上就是
//     「我们」的 DeLector，否则 fail-fast。
//
// 参数 python 是 mustNotSkipEnv 探测选定的解释器路径（argv[0]）：MUST 与探测
// 用的解释器一致（杜绝"探测用一个、起服用另一个"的静默失败）。
func startRealSupervisor(t *testing.T, python string) *pythonsvc.Supervisor {
	t.Helper()
	tmp := t.TempDir()
	port := resolvePort(t)
	baseURL = fmt.Sprintf("http://127.0.0.1:%d", port)
	healthURL := baseURL + "/api/tools/"
	cfg := pythonsvc.SupervisorConfig{
		// 端口参数化：默认命令硬编码 8001，此处显式覆盖为动态/指定端口，
		// 保证托管实例与 client 用的 baseURL 同端口。argv[0] 用探测选定的
		// 解释器（python），保证"探测/起服"同源。
		PythonCmd: []string{
			python, "-m", "uvicorn", "delector.server:app",
			"--host", "127.0.0.1", "--port", strconv.Itoa(port),
		},
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
		// 起服失败即停：绝不继续发业务请求。t.Skipf 沿用仓库既有"环境不可用归
		// skip"约定（既不假绿也不因环境缺失而红）。
		t.Skipf("skip: 无法在 %s 起真实服务（起服失败即停，不再发任何业务请求）: %v", baseURL, err)
	}
	t.Cleanup(s.Stop)

	// 起服成功 ≠ 端口上就是我们：MUST 校验身份（防替别人的服务背书）。
	assertSupervisorIdentity(t, baseURL)
	return s
}

// TestGoPythonPipeline 全链路主测试：真实进程可达 + writing_check 契约。
func TestGoPythonPipeline(t *testing.T) {
	python := mustNotSkipEnv(t)
	startRealSupervisor(t, python) // 实例经内部 t.Cleanup(s.Stop) 托管至用例结束

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
	python := mustNotSkipEnv(t)
	startRealSupervisor(t, python)

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

// ---- 端口分配（动态空闲端口 / 环境变量覆盖） -------------------------------------

// portEnvKey：显式指定端口的环境变量。为空则走动态空闲端口；设置后用于
// 确定性地复现"端口被占"的失败语义（RED/GREEN 验收）。
const portEnvKey = "DELECTOR_AGENT_TEST_PORT"

// resolvePort 决定本次运行使用的端口：portEnvKey 非空则用之（供复现撞车），
// 否则取一个动态空闲端口。非法值直接 fail。
func resolvePort(t *testing.T) int {
	t.Helper()
	if v := os.Getenv(portEnvKey); v != "" {
		p, err := strconv.Atoi(v)
		if err != nil || p <= 0 || p > 65535 {
			t.Fatalf("%s=%q 非法端口（err=%v）", portEnvKey, v, err)
		}
		return p
	}
	return freePort(t)
}

// freePort 取一个本机空闲 TCP 端口：让内核分配（:0）后读出端口并立即关闭
// listener。存在极小的 TOCTOU 窗口（关闭到 uvicorn bind 之间可能被抢占），但
// 配合身份校验，即便撞车也会被 fail-fast 而非静默假绿。
func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("分配动态空闲端口失败: %v", err)
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port
}

// ---- 身份校验（ADR-0020 §4 前置①） ---------------------------------------------
//
// 契约（务必对齐 delector/routes/main.py 的 /api/health）：该端点在 200 与 503
// 两种状态**都**返回身份字段 {"app":"delector","version":APP_VERSION}。Python 侧
// server_lifecycle.probe_identity 的语义是「接受 503、只看身份」——库坏但进程仍
// 是 DeLector 仍算 DeLector。本处 MUST 同语义：接受 503，只读 app/version；身份
// 不符即 fail-fast，门禁绝不替别人的服务背书。

const (
	identityApp     = "delector"
	identityPath    = "/api/health"
	identityProbeTO = 5 * time.Second
)

// healthIdentity 是 /api/health 身份字段的解码目标。
type healthIdentity struct {
	App     string `json:"app"`
	Version string `json:"version"`
}

// probeHealthIdentity GET {base}/api/health，接受 200 与 503（只看身份）。
// 返回解码出的身份与 HTTP 状态码；非 200/503 视为"非本服务"（返回零值身份与
// 真实状态码，不报错）。网络错误返回 err。
func probeHealthIdentity(ctx context.Context, base string) (healthIdentity, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+identityPath, nil)
	if err != nil {
		return healthIdentity{}, 0, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return healthIdentity{}, 0, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusServiceUnavailable {
		return healthIdentity{}, resp.StatusCode, nil
	}
	var id healthIdentity
	if err := json.Unmarshal(raw, &id); err != nil {
		return healthIdentity{}, resp.StatusCode, nil // 非 JSON：身份视为空 → 判定非 DeLector
	}
	return id, resp.StatusCode, nil
}

// assertSupervisorIdentity 起服成功后校验端口上确实是「我们」的 DeLector：
// 身份不符（app != "delector"）或不可达即 fail-fast，并打印可操作诊断。
func assertSupervisorIdentity(t *testing.T, base string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), identityProbeTO)
	defer cancel()
	id, status, err := probeHealthIdentity(ctx, base)
	if err != nil {
		t.Fatalf("身份校验失败：GET %s%s 不可达（%v）——该端口上可能不是本测试托管的服务，门禁拒绝继续", base, identityPath, err)
	}
	if id.App != identityApp {
		t.Fatalf("%s 上是一个外来服务（app=%q version=%q status=%d），不是本测试托管的 DeLector；门禁拒绝继续（防替别人的服务背书）", base, id.App, id.Version, status)
	}
	t.Logf("身份校验通过：%s%s app=%q version=%q status=%d", base, identityPath, id.App, id.Version, status)
}
