# Phase 2a: Go Agent Runtime 核心实现计划

> **Goal**: 用 Go 构建自研 DAG Agent Runtime，经 HTTP localhost 调用 Python NLP 微服务的 `/api/tools/*` 契约，产出 ~1000 行有含金量的 Go 工程代码。
> **Tech Stack**: Go ≥1.22（以本机 `go version` 为准，先探测）/ Python 3.11（现有基线零改动）/ cobra / testify（可选，标准库 testing 优先）
> **Spec Reference**: `docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md`（Accepted）；Vault 模式沉淀 `99-Inbox/2026-09-06-go-python-hybrid-architecture-pattern.md`
> **Global Constraints**:
> - **契约即法律**：Python 侧 `TOOL_REGISTRY` 当前实为 5 工具 `ingest / analyze / writing_check / export / tts`（ADR-0009 后 exercise→writing_check）。ADR-0008 图中的 `review` 工具**尚不存在于 Python 侧**——Task 1 先修订 ADR-0008 工具清单，禁止 Go 侧凭图编程。
> - **goroutine 泄露防线**：所有出站 HTTP 必须 `http.NewRequestWithContext` + 显式超时；错误判定用 `errors.Is(err, context.DeadlineExceeded)`，禁字符串比较。
> - **禁 cgo、禁 langchaingo**（ADR-0008 已裁定自研 DAG，~800–1200 行）。
> - **凭证不入库**：`DEEPSEEK_API_KEY` 走环境变量，代码只读 `os.Getenv`。
> - **Python 基线零改动**：测试基线 **599 passed + 1 skipped** 保持；集成测试起 Python 实例必须注入临时 `DATABASE_PATH`/`DELECTOR_DATA_DIR`，绝不动用户库。
> - 端口约定：agent 托管的 Python 实例用 **127.0.0.1:8001**（8000 留给用户直接启动的实例）；`_require_localhost` 闸要求 Go client 绑定回环。
> - 提交信息：`feat|fix|test|docs(agent): 中文描述`；每 Task 原子提交并 push。
> - 执行环境事实：本环境无写码子代理，/vault-exec 降级为**主线程直写 + TDD 纪律 + 每 Task 原子提交**，本计划的 Scaffold 仍按规范保留，交付说明须注明降级。

---

## 架构与文件边界

```
agent/                              ← Go module（新建，go.mod 在此）
├── go.mod                          module github.com/ROM4n2/DeLector/agent
├── cmd/delector/main.go            ← cobra 根命令（T8）
├── internal/pythonsvc/
│   ├── client.go                   ← /api/tools HTTP client（T9）
│   ├── client_test.go
│   ├── supervisor.go               ← Python 常驻进程管理（T13）
│   └── supervisor_test.go
├── internal/registry/
│   ├── registry.go                 ← Tool Registry + 契约 golden 测试（T12）
│   └── registry_test.go
├── internal/dag/
│   ├── dag.go                      ← DAG scheduler（T10）
│   └── dag_test.go
├── internal/llm/
│   ├── deepseek.go                 ← go-openai 兼容客户端（T11）
│   └── deepseek_test.go
└── integration_test.go             ← 全链路（T15，build tag `integration`）

依赖方向：cmd → registry → dag → pythonsvc / llm。禁止反向 import。
```

**Consumes（Python 侧既有，零改动）**：`GET /api/tools/`、`POST /api/tools/{name}`（body `{"payload": {...}}`，`_require_localhost` 闸、未知工具 404、失败 400 detail）。
**Produces（Go 侧）**：`pythonsvc.Client.RunTool(ctx, name string, payload map[string]any) (map[string]any, error)`；`dag.DAG.AddStep/Run(ctx, input)`；`supervisor.Start/Stop`。

---

### Task 1: Go 脚手架 + 契约钉板 [Role: TDD Builder]

**Files:**
- Create: `agent/go.mod`、`agent/cmd/delector/main.go`、`agent/internal/pythonsvc/doc.go`
- Modify: `docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md`（工具清单对齐 5 工具实况）

**Interfaces:**
- Produces: `cmd/delector` cobra 根命令 `delector version` / `delector run --dag <name>`（本 Task 只通 version）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: Go 脚手架与契约钉板.
> Goal: 建立 agent/ Go module 与 cobra 入口；把 ADR-0008 工具清单修订为 Python 实况（ingest/analyze/writing_check/export/tts），删去不存在的 review。
> Target Files: Create `agent/go.mod`, `agent/cmd/delector/main.go`. Modify ADR-0008 工具表.
> TDD Steps: 1. 写 `main_test.go` 断言 `delector version` 输出含版本号 (RED). 2. `cd agent && go test ./...` 验红. 3. 实现 cobra root (GREEN). 4. 修订 ADR-0008 并在计划文档勾选.
> Return: 测试执行证据 + ADR diff 摘要."

**Step Breakdown:**
- [ ] Step 1: `go version` 探测本机工具链；写失败测试（RED）
- [ ] Step 2: 验红
- [ ] Step 3: cobra root + go.mod（GREEN）
- [ ] Step 4: 修订 ADR-0008 工具清单（写明与 `TOOL_REGISTRY` 的对齐关系、ADR-0009 更名）
- [ ] Step 5: `go vet ./...` + 提交 `feat(agent): go 脚手架与 cobra 入口`

---

### Task 2: pythonsvc HTTP Client [Role: TDD Builder]

**Files:**
- Create: `agent/internal/pythonsvc/client.go`、`client_test.go`

**Interfaces:**
- Consumes: `POST /api/tools/{name}`（200 dict / 404 unknown / 400 detail / 403 非 localhost）
- Produces: `type Client struct` + `NewClient(baseURL string, hc *http.Client)` + `RunTool(ctx, name, payload) (map[string]any, error)`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: pythonsvc HTTP client.
> Goal: 封装 POST /api/tools/{name}；404→ErrToolNotFound、400→ToolError(detail)、超时→包 context.DeadlineExceeded；请求体 {\"payload\":...}。
> TDD: httptest.Server 起桩（表驱动 200/404/400/403/超时 五例）；全部 NewRequestWithContext。
> Return: 测试证据."

**Step Breakdown:**
- [ ] Step 1: 表驱动失败测试：200 成功 / 404 → `ErrToolNotFound` / 400 → `*ToolError` 含 detail / 403 → 错误含 localhost 提示 / 桩延迟 → `errors.Is(context.DeadlineExceeded)`（RED）
- [ ] Step 2: 验红
- [ ] Step 3: 最小实现（GREEN）：client 默认 `http.Client{Timeout: 120s}`，每请求 `NewRequestWithContext`
- [ ] Step 4: 全绿 + `go vet`
- [ ] Step 5: 卫语句扁平化审查（错误分支提前 return）
- [ ] Step 6: 提交 `feat(agent): pythonsvc http client 与契约错误映射`

---

### Task 3: Tool Registry [Role: TDD Builder]

**Files:**
- Create: `agent/internal/registry/registry.go`、`registry_test.go`

**Interfaces:**
- Consumes: `pythonsvc.Client.RunTool`
- Produces: `type Tool func(ctx, payload) (map[string]any, error)`；`Registry.Register/List/Run(ctx, name, payload)`；`DefaultRegistry(c *pythonsvc.Client)` 预注册 5 工具

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: Tool Registry.
> Goal: 5 个工具注册（ingest/analyze/writing_check/export/tts），未注册名返回错误（与 Python 404 对齐）；List() 供 CLI help。
> TDD: 单测用桩 Tool，不经网络。
> Return: 测试证据."

**Step Breakdown:**
- [ ] Step 1: 失败测试（RED）→ Step 2: 验红 → Step 3: 实现（GREEN）
- [ ] Step 4: golden 断言 `List()` 恰为 5 个名字且与 ADR-0008 修订后清单一致（防漂移哨兵）
- [ ] Step 5: 提交 `feat(agent): tool registry 与五工具预注册`

---

### Task 4: DAG Scheduler（核心） [Role: TDD Builder]

**Files:**
- Create: `agent/internal/dag/dag.go`、`dag_test.go`

**Interfaces:**
- Produces: `NewDAG(name)`；`AddStep(id string, fn StepFunc, deps ...string)`；`Run(ctx, input map[string]any) (map[string]any, error)`——无依赖步并行、依赖步等待上游结果、环检测报错、任一步失败整体 fail-fast、ctx 超时全链取消

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: DAG scheduler（goroutine + channel，参考 vault worker-pool 模板）.
> Goal: 拓扑执行引擎 ~300 行：环检测、并行无依赖步（errgroup 或 WaitGroup+error channel）、结果经 channel 汇聚、ctx 超时取消、fail-fast。
> TDD: 表驱动——①线性链 ②菱形并行（用原子计数验证两支确并发）③环 → 报错 ④中步失败 → 下游不执行 ⑤ctx 超时。
> Return: 测试证据 + 并发验证说明."

**Step Breakdown:**
- [ ] Step 1: 五组失败测试（RED）→ Step 2: 验红
- [ ] Step 3: 实现（GREEN）：`AddStep` 建图时做环检测（DFS）；`Run` 按入度逐层放行 goroutine，`chan stepResult` 汇聚，`select ctx.Done()` 提前退出
- [ ] Step 4: 全绿 + `go test -race ./internal/dag/`（竞态必查）
- [ ] Step 5: 文章分析示例 DAG（ingest → [nlp, tts] → writing_check → export）写成 Example 测试钉住 ADR-0008 拓扑
- [ ] Step 6: 提交 `feat(agent): 自研 dag 调度器（并行/环检测/fail-fast/超时）`

---

### Task 5: Python Supervisor [Role: TDD Builder]

**Files:**
- Create: `agent/internal/pythonsvc/supervisor.go`、`supervisor_test.go`

**Interfaces:**
- Consumes: `python -m uvicorn delector.server:app --host 127.0.0.1 --port 8001`
- Produces: `Supervisor.Start(ctx)`（阻塞至健康探针通过）/ `Stop()`（优雅关闭 + 超时 kill）；`backoff(attempt) time.Duration`（指数退避，max 5 次）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: Python 进程 supervisor.
> Goal: exec.CommandContext 起 uvicorn :8001，GET /api/tools/ 探针 1s 间隔直至通过；crash 指数退避重启 max5；Stop 先 SIGTERM 等价物（cmd.Cancel）再超时 kill。注入 env：临时 DATABASE_PATH/DELECTOR_DATA_DIR（不污染用户库）。
> TDD: backoff 纯函数单测 + 探针轮询用 httptest 桩；真实进程联调留给 Task 7 集成。
> Return: 测试证据."

**Step Breakdown:**
- [ ] Step 1: 失败测试（backoff 序列、探针超时、重启计数）（RED）→ Step 2: 验红
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 全绿 + `-race` → Step 5: 提交 `feat(agent): python 常驻进程 supervisor（心跳/退避重启/优雅关闭）`

---

### Task 6: LLM 客户端（DeepSeek） [Role: TDD Builder]

**Files:**
- Create: `agent/internal/llm/deepseek.go`、`deepseek_test.go`、`agent/go.mod`（追加依赖 go-openai）

**Interfaces:**
- Consumes: DeepSeek OpenAI 兼容 API（key 走 `DEEPSEEK_API_KEY`）
- Produces: `Client.Complete(ctx, system, user string, opts ...Option) (string, error)`（含超时与重试上限）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: go-openai 兼容客户端.
> Goal: 封装 Complete()，baseURL 可注入（测试用 httptest 桩），key 仅从环境变量读，缺 key 返回哨兵错误；单测桩验证请求体与超时。
> Return: 测试证据."

**Step Breakdown:**
- [ ] Step 1: 失败测试（RED）→ Step 2: 验红 → Step 3: 实现（GREEN）
- [ ] Step 4: 断言源码无硬编码 key（`test_source_hygiene` 精神的 Go 版）→ Step 5: 提交 `feat(agent): deepseek llm 客户端`

---

### Task 7: 集成测试（Go→Python 全链路） [Role: TDD Builder]

**Files:**
- Create: `agent/integration_test.go`（`//go:build integration`）

**Interfaces:**
- Consumes: Supervisor + Registry + DAG 真实组装；Python 实例注入临时 `DATABASE_PATH`
- Produces: `TestArticleAnalysisPipeline`——起真实 Python → `dag.Run` 全链 → 断言各步产出键

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 7: 全链路集成测试.
> Goal: `go test -tags integration` 起 supervisor（临时库）→ 跑 analyze+tts 桩化 LLM 的最小 DAG → 断言 200 与产出结构。跳过条件：本机无 python/依赖时 t.Skip。
> Return: 测试证据（含 skip 路径）."

**Step Breakdown:**
- [ ] Step 1: 写集成测试（build tag 隔离，不进常规 `go test ./...`）
- [ ] Step 2: 本机跑通真实链路；无环境时验证 skip
- [ ] Step 3: 回归 Python 基线：仓库根分片 pytest 全绿（599+1 不变）
- [ ] Step 4: 提交 `test(agent): go→python 全链路集成`并 push

---

### Task 8: 文档收尾与状态回填 [Role: Docs]

**Files:**
- Modify: `README.md`（目录树加 agent/ 一行 + 简历叙事链接）、本计划勾选、`WORKMEMORY/work.log`

**Step Breakdown:**
- [ ] Step 1: 回填计划状态（含偏差）→ Step 2: README 更新 → Step 3: work.log 事件 → Step 4: docs 提交并 push

---

## 后续子计划（本计划不含）
- **Phase 2b 打包**（T14）：Go 二进制 + Python venv 目录 + GitHub Actions 三平台——待 2a 全绿后另立计划。
- **Phase 2c 简历打磨**（T16）：架构图 + 面试问答——归 09-Career，非代码交付。
