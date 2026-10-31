# 伴学 Agent Go Runtime 接管与原生 Tool Calling 实施计划 (方案 A)

> **Goal**: 由现有的 Go Agent（`agent/`）全面接管伴学 Agent 编排，利用 Go 工业级 `go-openai` 驱动原生 Tool Calling (`tools=[...]`) 与真 Token 流式 SSE 架构，调度 Python 本地 NLP 微服务，彻底根治格式解析崩溃与网络超时。
> **Tech Stack**: Go 1.24+ / 1.26, go-openai v1.43.0, FastAPI, Vanilla JS (Zero innerHTML)
> **Spec Reference**: `docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md`
> **Global Constraints**: Zero innerHTML, 测试严禁真实出网（100% httptest / Mock 隔离）, 四道机械门禁 100% 全绿，Go 单测 100% 全绿。
> **Branch**: `feat/companion-study-agent`

---

## [NOTE] Decisions So Far
- [ADR-0008 / ADR-0010](docs/adr/2026-09-07-adr-0010-encounter-zone-layered-go-agent-producer.md): Go 作为高性能 Agent Runtime 与 Supervisor，Python 作为本地 NLP 分析微服务。
- [ADR-0025](docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md): 定案方案 A ── Go 侧 `agent/internal/companion` 全面接管伴学会话编排、DeepSeek 原生 Tool Calling 与流式 SSE 下发。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: Go 侧 Companion Tools 与事件契约定义 [Tier: 2-Standard] [Mode: AFK]

**Files:**
- Create: `agent/internal/companion/tools.go`
- Test: `agent/internal/companion/tools_test.go`

**Interfaces:**
- Produces: `CompanionTools() []openai.Tool`（包含 `analyze`, `writing_check`, `vocab_stats`, `propose_vocab_cards`）
- Produces: `Event` 结构（`delta`, `thought`, `tool_start`, `tool_end`, `proposal`, `done`, `error`）

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `agent/internal/companion/tools_test.go` (RED)**
- [ ] **Step 2: Implement schemas in `agent/internal/companion/tools.go` (GREEN)**
- [ ] **Step 3: Run `go test ./internal/companion/...` and verify exit 0**
- [ ] **Step 4: Git atomic commit**

---

### Task 2: Go 侧 Companion Agent Loop 核心调度器 [Tier: 2-Standard] [Mode: AFK]

**Files:**
- Create: `agent/internal/companion/loop.go`
- Test: `agent/internal/companion/loop_test.go`

**Interfaces:**
- Consumes: `*openai.Client`, `*pythonsvc.Client`
- Produces: `RunLoop(ctx context.Context, req Request, emit func(Event) error) (*Outcome, error)`
- Features: 
  - 纯 Markdown 流式直吐（`delta.Content`）；
  - 原生思考链流式直吐（`delta.ReasoningContent`）；
  - 原生 `delta.ToolCalls` 聚合与调度；
  - 诊断工具委托 `pythonsvc.Client.RunTool`，结果作为 `Role: tool` 反馈模型自愈；
  - 制卡提议生成 `proposal` 事件。

**Step Breakdown:**
- [ ] **Step 1: Write failing test with mock httptest server (RED)**
- [ ] **Step 2: Implement `RunLoop` in `agent/internal/companion/loop.go` (GREEN)**
- [ ] **Step 3: Run `go test ./internal/companion/...` and verify exit 0**
- [ ] **Step 4: Git atomic commit**

---

### Task 3: Go 侧 HTTP SSE Server / Handler [Tier: 2-Standard] [Mode: AFK]

**Files:**
- Create: `agent/internal/companion/server.go`
- Test: `agent/internal/companion/server_test.go`

**Interfaces:**
- Produces: `NewHandler(agent *CompanionAgent) http.Handler`
- Endpoints: `POST /api/companion/chat`（SSE 协议）, `GET /api/companion/health`

**Step Breakdown:**
- [ ] **Step 1: Write failing HTTP SSE test in `agent/internal/companion/server_test.go` (RED)**
- [ ] **Step 2: Implement SSE streaming handler (GREEN)**
- [ ] **Step 3: Run `go test ./internal/companion/...` and verify exit 0**
- [ ] **Step 4: Git atomic commit**

---

### Task 4: Go CLI 命令集成 `delector agent` [Tier: 2-Standard] [Mode: AFK]

**Files:**
- Modify: `agent/cmd/delector/main.go`
- Create: `agent/cmd/delector/agent.go`
- Test: `agent/cmd/delector/agent_test.go`

**Interfaces:**
- Produces: `delector agent --port 8002 --python-url http://127.0.0.1:8001`
- 挂载伴学 Agent 常驻服务。

**Step Breakdown:**
- [ ] **Step 1: Write CLI command tests (RED)**
- [ ] **Step 2: Implement `newAgentCmd()` (GREEN)**
- [ ] **Step 3: Run CLI test and verify exit 0**
- [ ] **Step 4: Git atomic commit**

---

### Task 5: Python 路由层透明反代网关 [Tier: 2-Standard] [Mode: AFK]

**Files:**
- Modify: `delector/routes/companion.py`
- Test: `tests/test_companion_routes.py`

**Interfaces:**
- 在 `/api/companion/chat` 中：
  - 若配置了 `GO_AGENT_URL`（默认 `http://127.0.0.1:8002`）且健康探针可达，以异步流式反代将 SSE 帧原汁原味转发至客户端；
  - 保持现有前端无缝升级。

**Step Breakdown:**
- [ ] **Step 1: 编写路由代理与回退单元测试 (RED)**
- [ ] **Step 2: 实现异步流式反代逻辑 (GREEN)**
- [ ] **Step 3: 运行 `pytest tests/test_companion_routes.py` 并验证 exit 0**
- [ ] **Step 4: Git atomic commit**

---

### Task 6: 双语全景门禁与综合回归验证 [Tier: 1-Light] [Mode: AFK]

**Files:**
- Verify: Go 与 Python 双全景回归

**Step Breakdown:**
- [ ] **Step 1: `cd agent && go test ./...` 100% PASS**
- [ ] **Step 2: `pytest tests/test_companion_*.py tests/test_llm_client*.py` 100% PASS**
- [ ] **Step 3: `check_frontend_layers.py` 等四道机械门禁 100% PASS**
- [ ] **Step 4: `mypy --strict` & `ruff check` 100% PASS**
- [ ] **Step 5: 追加 `WORKMEMORY/work.log` 记录完整架构升级**

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| Logit 级语法约束 (Outlines/vLLM) | 本地运行环境无需自建推理引擎依赖 | 当引入本地专用推理加速服务时 | Agent Team |

---

## [NOTE] Out of Scope
- 修改德语依存句法本地分析内核（Spacy / Stanza）本身算法。
- 修改主阅读器核心分词与高亮架构。
