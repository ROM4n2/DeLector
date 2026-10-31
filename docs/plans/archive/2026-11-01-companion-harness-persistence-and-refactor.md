# 伴学智能体体系架构演进与单体解耦实施计划 (Companion Harness Persistence & Modular Refactor)

> **Goal**: 落地伴学智能体 Phase A 业务持久化与画像深耕，解耦前端 `cp-drawer.js` (1050行)、后端 `loop.go` (518行) 与路由 `routes/companion.py` 过于臃肿的模块，构建轻量高内聚的 TurnPipeline 中间件管道。
> **Tech Stack**: Python 3.11+, FastAPI, SQLite WAL, Go 1.24+, Vanilla ES Modules (Zero Build, Zero innerHTML)
> **Spec Reference**: `docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md`
> **Global Constraints**: Zero innerHTML, 测试严禁真实出网（100% httptest / MockTransport 隔离）, 四道机械门禁 100% 全绿，Go 单测 100% 全绿，代码缩进严控（首行确切对齐）。
> **Branch**: `feat/companion-provider-registry-and-pi-compaction`

---

## [NOTE] Decisions So Far
- [2026-11-01 架构决断](docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md): 采纳 **先 A 后 B** 路径：先打通会话持久化与学习画像深耕，同步对过度臃肿的前后端模块进行外科手术式解耦，再将 Go Runtime 重构为中间件管线。
- [解耦目标 1 (前端)]: `static/js/cp-drawer.js` 从 1050 行单体拆分出 `cp-drawer-markdown.js`、`cp-drawer-proposals.js`、`cp-drawer-capsule.js`，主体保留为纯粹的协调控制器（< 350 行）。
- [解耦目标 2 (Go 运行时)]: `agent/internal/companion/loop.go` 拆分出 `compaction.go`、`tool_calls.go`、`prompts.go`，并在 Phase B 抽象出 `TurnPipeline` 中间件链。
- [解耦目标 3 (Python 服务)]: `delector/routes/companion.py` 拆出 `delector/services/companion_session.py` 与 `companion_proposal.py`，保持路由层薄化。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: SQLite 会话表与提议生命周期 DDL 迁移 [Tier: 2-Standard] [Mode: AFK] [Role: Python TDD Builder]

**Files:**
- Create: `delector/core/db/companion.py`
- Modify: `delector/core/database.py:40-60`
- Test: `tests/test_companion_db.py`

**Interfaces:**
- Consumes: `delector.core.db.connection.get_db()`
- Produces:
  - `init_companion_tables(conn: sqlite3.Connection) -> None`: 幂等创建 `companion_sessions`、`companion_messages`、`companion_proposals`；
  - `create_session(article_id: str | None, title: str) -> dict`;
  - `get_session(session_id: str) -> dict | None`;
  - `list_sessions(article_id: str | None, limit: int = 20) -> list[dict]`;
  - `append_message(session_id: str, role: str, content: str, thought: str = "", reasoning_effort: str = "medium") -> dict`;
  - `get_messages(session_id: str) -> list[dict]`.

**Injected Instincts:**
- [ ] `[Instinct: Zero-Lock DDL]`: 使用 `CREATE TABLE IF NOT EXISTS` 与复合索引，事务遵循 SQLite WAL 快速提交。

**Subagent Prompt Scaffold:**
> "Implement Task 1: SQLite companion tables and persistence helper in delector/core/db/companion.py.
> Mode: AFK | Role: Python TDD Builder
> Goal: Create companion_sessions, companion_messages, and companion_proposals tables with clean CRUD methods.
> Target Files: Create delector/core/db/companion.py, Test tests/test_companion_db.py, Modify delector/core/database.py.
> TDD Steps:
> 1. Write failing test tests/test_companion_db.py covering table creation and session/message CRUD (RED).
> 2. Run pytest tests/test_companion_db.py and verify failure.
> 3. Implement init_companion_tables and CRUD functions in delector/core/db/companion.py (GREEN).
> 4. Export symbols in delector/core/database.py.
> 5. Verify pytest tests/test_companion_db.py passes with exit code 0.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `tests/test_companion_db.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `delector/core/db/companion.py` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `pytest tests/test_companion_db.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 2: 抽离 Companion 业务服务并瘦身 `routes/companion.py` [Tier: 2-Standard] [Mode: AFK] [Role: Python TDD Builder]

**Files:**
- Create: `delector/services/companion_session.py`
- Create: `delector/services/companion_proposal.py`
- Modify: `delector/routes/companion.py`
- Test: `tests/test_companion_services.py`
- Test: `tests/test_companion_routes.py`

**Interfaces:**
- Consumes: `delector.core.db.companion.*`, `delector.core.database.get_db()`
- Produces:
  - `CompanionSessionService`: 封装会话初始化、历史消息提取、上下文注入与标题自动提炼；
  - `CompanionProposalService`: 封装 Proposal 的创建、幂等确认入库 (`execute_proposal`)、已处理状态防重放；
  - `routes/companion.py`: 仅保留 HTTP 路由与 SSE 转发逻辑，代码行数压缩至 150 行以内。

**Injected Instincts:**
- [ ] `[Instinct: Single Responsibility]`: 路由层不直接操作 SQLite 事务，全量委托给 Service 层。

**Subagent Prompt Scaffold:**
> "Implement Task 2: Extract CompanionSessionService and CompanionProposalService from routes/companion.py.
> Mode: AFK | Role: Python TDD Builder
> Goal: Decouple business logic and persistence from routes/companion.py into clean service classes.
> Target Files: Create delector/services/companion_session.py, delector/services/companion_proposal.py, Modify delector/routes/companion.py, Test tests/test_companion_services.py.
> TDD Steps:
> 1. Write failing tests for SessionService and ProposalService in tests/test_companion_services.py (RED).
> 2. Implement services and refactor routes/companion.py to use them (GREEN).
> 3. Verify tests/test_companion_services.py and tests/test_companion_routes.py pass.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `tests/test_companion_services.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement services and refactor `routes/companion.py` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `pytest tests/test_companion_services.py tests/test_companion_routes.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 3: 领域原生探针工具开发 (`get_learner_profile` & `query_dictionary`) [Tier: 2-Standard] [Mode: AFK] [Role: Python & Go TDD Builder]

**Files:**
- Create: `delector/tools/learner_profile.py`
- Create: `delector/tools/dictionary.py`
- Modify: `delector/tools/vocab_cards.py` (增强已知词过滤)
- Modify: `delector/routes/tools.py`
- Modify: `agent/internal/companion/tools.go`
- Test: `tests/test_companion_domain_tools.py`

**Interfaces:**
- Consumes: FSRS 数据库 `get_progress_db()`, 本地词典 `lookup_lemma()`, 动介搭配表
- Produces:
  - 工具 `get_learner_profile`: 输出当前学习者已掌握词数、FSRS 复习负荷、薄弱词根；
  - 工具 `query_dictionary`: 输出德汉权威释义、动词配价与常用搭配；
  - 增强 `propose_vocab_cards`: 自动调用掌握度过滤，杜绝提议已掌握词。

**Injected Instincts:**
- [ ] `[Instinct: Robust Input]`: 工具入参支持缺省降级，返回严格符合 RFC JSON 契约的结构化对象。

**Subagent Prompt Scaffold:**
> "Implement Task 3: Domain-native tools get_learner_profile and query_dictionary.
> Mode: AFK | Role: Fullstack TDD Builder
> Goal: Provide domain tools for the agent to inspect the learner's FSRS mastery and query offline dictionary definitions.
> Target Files: Create delector/tools/learner_profile.py, delector/tools/dictionary.py, Modify delector/tools/vocab_cards.py, agent/internal/companion/tools.go, Test tests/test_companion_domain_tools.py.
> TDD Steps:
> 1. Write failing tests in tests/test_companion_domain_tools.py (RED).
> 2. Implement tools and expose them in delector/routes/tools.py and agent tools.go (GREEN).
> 3. Verify tests pass with exit code 0.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `tests/test_companion_domain_tools.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement tools and wire into Go `tools.go` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `pytest tests/test_companion_domain_tools.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 4: 前端抽屉单体解耦：抽离 Markdown 渲染与浮动胶囊模块 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Refactorer]

**Files:**
- Create: `static/js/cp-drawer-markdown.js`
- Create: `static/js/cp-drawer-capsule.js`
- Modify: `static/js/cp-drawer.js`
- Test: `tools/check_frontend_layers.py`
- Test: `tools/check_companion_contract.py`

**Interfaces:**
- Consumes: 原生 DOM API (`document.createElement`, `textContent`)
- Produces:
  - `cp-drawer-markdown.js`: 导出 `renderSafeMarkdownToElement(container, markdownText)`（严格零 innerHTML，支持代码块、粗体、列表、引用）；
  - `cp-drawer-capsule.js`: 导出 `initFloatingCapsule(options)`，管理视口跟随与拖拽；
  - `cp-drawer.js`: 移除上述大段代码，行数缩减 350+ 行。

**Injected Instincts:**
- [ ] `[Instinct: Zero innerHTML]`: 纯 DOM API 构建节点，坚决杜绝 XSS 风险。
- [ ] `[Instinct: Layer Architecture]`: 遵循 L1-L4 前端分层约束。

**Subagent Prompt Scaffold:**
> "Implement Task 4: Modularize cp-drawer.js by extracting cp-drawer-markdown.js and cp-drawer-capsule.js.
> Mode: AFK | Role: Frontend Refactorer
> Goal: Decouple markdown rendering and floating mascot capsule logic from cp-drawer.js while maintaining strict Zero innerHTML.
> Target Files: Create static/js/cp-drawer-markdown.js, static/js/cp-drawer-capsule.js, Modify static/js/cp-drawer.js.
> TDD Steps:
> 1. Create separate modules adhering to ES module syntax.
> 2. Import them into cp-drawer.js and verify node -c on all files.
> 3. Run python3 tools/check_frontend_layers.py and verify PASS.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Extract `static/js/cp-drawer-markdown.js`**
- [ ] **Step 2: Extract `static/js/cp-drawer-capsule.js`**
- [ ] **Step 3: Refactor `static/js/cp-drawer.js` to import sub-modules**
- [ ] **Step 4: Verify syntax with `node -c static/js/cp-*.js`**
- [ ] **Step 5: Physical Evidence Gate**: `python3 tools/check_frontend_layers.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 5: 前端 Proposal 卡片模块化与生命周期持久化 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Refactorer]

**Files:**
- Create: `static/js/cp-drawer-proposals.js`
- Modify: `static/js/cp-drawer.js`
- Modify: `static/js/cp-api.js`
- Test: `tools/check_companion_contract.py`

**Interfaces:**
- Consumes: `static/js/cp-api.js:executeProposal`
- Produces:
  - `renderProposalCard(container, proposal, onAction)`: 渲染卡片，支持 `pending`（显示操作按钮）、`accepted`（显示绿色已确认标记）、`rejected`（显示置灰已忽略标记）；
  - `renderProposalList(container, proposals)`: 恢复历史会话时的批量卡片渲染；
  - 彻底将 180 行卡片交互代码从 `cp-drawer.js` 中剔除。

**Injected Instincts:**
- [ ] `[Instinct: Idempotent UI]`: 点击确认后立即进入 loading 态并禁用按钮，防止多次快速点击导致并发写入。

**Subagent Prompt Scaffold:**
> "Implement Task 5: Extract cp-drawer-proposals.js with full lifecycle state support (pending, accepted, rejected).
> Mode: AFK | Role: Frontend Refactorer
> Goal: Decouple proposal card DOM construction and action dispatch from cp-drawer.js.
> Target Files: Create static/js/cp-drawer-proposals.js, Modify static/js/cp-drawer.js, static/js/cp-api.js.
> TDD Steps:
> 1. Extract proposal card rendering and action handling to cp-drawer-proposals.js.
> 2. Add visual badge support for accepted and rejected states.
> 3. Verify node -c syntax and mechanical gates.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Create `static/js/cp-drawer-proposals.js`**
- [ ] **Step 2: Refactor `cp-drawer.js` to delegate card rendering**
- [ ] **Step 3: Update `static/js/cp-api.js` with proposal query endpoints**
- [ ] **Step 4: Verify syntax and gates**
- [ ] **Step 5: Physical Evidence Gate**: `python3 tools/check_companion_contract.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 6: 前端会话持久化与会话切换器 UI (Session Switcher) [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Builder]

**Files:**
- Modify: `static/js/cp-drawer.js`
- Modify: `static/js/cp-state.js`
- Modify: `static/modals/drawer.html`
- Modify: `static/style.css`
- Test: `tools/check_index_html_sync.py`

**Interfaces:**
- Consumes: `cp-api.js:fetchSessionHistory`, `cp-api.js:createSession`
- Produces:
  - 抽屉顶部新增【历史会话】下拉/抽屉切换与【新建对话】按钮；
  - 切换文章或刷新后自动调用 `resumeSession(articleId)` 恢复消息与卡片状态；
  - `cp-drawer.js` 最终收敛为标准的生命周期控制器（< 300 行）。

**Injected Instincts:**
- [ ] `[Instinct: Academic Styling]`: 符合 `docs/design-system.md`，使用纸质暖色调与墨线质感，杜绝 AI 浮夸霓虹渐变。

**Subagent Prompt Scaffold:**
> "Implement Task 6: Session persistence and switcher UI in companion drawer.
> Mode: AFK | Role: Frontend Builder
> Goal: Enable multi-session resume and switcher in companion drawer, rebuilding static/index.html.
> Target Files: Modify static/js/cp-drawer.js, static/js/cp-state.js, static/modals/drawer.html, static/style.css.
> TDD Steps:
> 1. Add session switcher elements to static/modals/drawer.html.
> 2. Rebuild index.html with python3 tools/build_index_html.py.
> 3. Implement session resume logic in cp-drawer.js.
> 4. Verify check_index_html_sync.py passes.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Add HTML modal controls in `static/modals/drawer.html`**
- [ ] **Step 2: Rebuild `static/index.html`**
- [ ] **Step 3: Wire session resume and switcher in `cp-drawer.js`**
- [ ] **Step 4: Verify styles and mechanical gates**
- [ ] **Step 5: Physical Evidence Gate**: `python3 tools/check_index_html_sync.py` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 7: 解耦 Go 运行时单体：拆分 `compaction.go`, `tool_calls.go`, `prompts.go` [Tier: 2-Standard] [Mode: AFK] [Role: Go TDD Builder]

**Files:**
- Create: `agent/internal/companion/compaction.go`
- Create: `agent/internal/companion/tool_calls.go`
- Create: `agent/internal/companion/prompts.go`
- Modify: `agent/internal/companion/loop.go`
- Test: `agent/internal/companion/loop_test.go`
- Test: `agent/internal/companion/compaction_test.go`

**Interfaces:**
- Consumes: `go-openai` streaming structures
- Produces:
  - `compaction.go`: `CompactContext(messages, maxTokens) []openai.ChatCompletionMessage`（滑动窗口与系统提示锚点折叠）；
  - `tool_calls.go`: `AggregateToolCalls(chunk) []openai.ToolCall` 与自愈错误包装；
  - `prompts.go`: `BuildSystemPrompt(context, modelSpec)` 与 `BuildNudgePrompt()`;
  - `loop.go`: 从 518 行压缩至 220 行以内，专注于轮次推进与通信调度。

**Injected Instincts:**
- [ ] `[Instinct: Pure Function Testing]`: 提取的子模块优先为无副作用纯函数，方便编写单测。

**Subagent Prompt Scaffold:**
> "Implement Task 7: Deconstruct agent/internal/companion/loop.go into compaction.go, tool_calls.go, and prompts.go.
> Mode: AFK | Role: Go TDD Builder
> Goal: Decompose the monolithic loop.go into clean domain files and reduce loop.go to < 220 lines.
> Target Files: Create agent/internal/companion/compaction.go, tool_calls.go, prompts.go, Modify loop.go, Test loop_test.go, compaction_test.go.
> TDD Steps:
> 1. Extract compaction logic to compaction.go and add tests in compaction_test.go.
> 2. Extract tool call aggregation to tool_calls.go.
> 3. Extract system prompt construction to prompts.go.
> 4. Simplify loop.go and verify go test -v ./internal/companion/... passes 100%.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Extract `compaction.go` and write `compaction_test.go` (RED -> GREEN)**
- [ ] **Step 2: Extract `tool_calls.go` and wire into `loop.go`**
- [ ] **Step 3: Extract `prompts.go`**
- [ ] **Step 4: Verify `loop.go` line count is < 220**
- [ ] **Step 5: Physical Evidence Gate**: `go test -v ./internal/companion/...` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 8: 引入 `TurnPipeline` 中间件体系与运行时 JSONL 可观测追踪 [Tier: 2-Standard] [Mode: AFK] [Role: Go TDD Builder]

**Files:**
- Create: `agent/internal/companion/pipeline.go`
- Create: `agent/internal/companion/tracer.go`
- Modify: `agent/internal/companion/loop.go`
- Test: `agent/internal/companion/pipeline_test.go`

**Interfaces:**
- Consumes: `TurnContext`
- Produces:
  - `type TurnMiddleware func(ctx *TurnContext, next func() error) error`
  - 核心中间件链：
    `ContextGuardMiddleware` -> `ToolExecutionMiddleware` -> `PromptNudgeMiddleware` -> `TraceLoggingMiddleware`；
  - 物理审计输出：向 `$DATA_DIR/logs/companion_trace.jsonl` 追加每轮执行耗时、token 统计与状态机跃迁记录。

**Injected Instincts:**
- [ ] `[Instinct: Concurrency]`: 避免全局锁竞争，Trace 写入采用异步 channel 或轻量 Mutex 保护。

**Subagent Prompt Scaffold:**
> "Implement Task 8: TurnPipeline middleware chain and JSONL execution tracing.
> Mode: AFK | Role: Go TDD Builder
> Goal: Build modular middleware pipeline for agent loop turns and persist execution metrics to JSONL.
> Target Files: Create agent/internal/companion/pipeline.go, tracer.go, Modify loop.go, Test pipeline_test.go.
> TDD Steps:
> 1. Write failing tests for TurnPipeline middleware execution order in pipeline_test.go (RED).
> 2. Implement TurnPipeline and TraceLoggingMiddleware (GREEN).
> 3. Integrate pipeline into loop.go.
> 4. Verify go test -v ./internal/companion/... passes.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `agent/internal/companion/pipeline_test.go` (RED)**
- [ ] **Step 2: Implement `TurnPipeline` and `tracer.go` (GREEN)**
- [ ] **Step 3: Wire into `loop.go`**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `go test -v ./internal/companion/...` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 9: 全量回归门禁与机械闸闭环验证 [Tier: 1-Light] [Mode: AFK] [Role: Gatekeeper]

**Files:**
- Modify: `WORKMEMORY/work.log`
- Verify: Python, Go, and Frontend Gates

**Step Breakdown:**
- [ ] **Step 1: 前端四大机械门禁全绿核验**：
  `python3 tools/check_frontend_layers.py && python3 tools/check_frontend_api_contract.py && python3 tools/check_index_html_sync.py && python3 tools/check_companion_contract.py`
- [ ] **Step 2: Python 测试套件全绿核验**：
  `python3 -m pytest tests/test_companion_*.py tests/test_tools*.py -v`
- [ ] **Step 3: Go 运行时测试全绿核验**：
  `cd agent && go test -v ./... && go build -o delector.exe ./cmd/delector`
- [ ] **Step 4: 模块行数与复杂度核算**：
  验证 `cp-drawer.js` < 350 行，`loop.go` < 220 行，`routes/companion.py` < 150 行。
- [ ] **Step 5: 追加 `WORKMEMORY/work.log` 记录交付物**

---

## [NOTE] Fog of War (Not Yet Specified)
- **[Unknown 1: 本地词典高并发查询性能]**：在多生词长句中并发调用 `query_dictionary` 对 TTFT 的影响，留待 Task 3 落地后进行基准测试分析。
- **[Unknown 2: FSRS 掌握度自适应权重]**：排除已知词的 Stability 阈值经验值（当前暂定 S > 21.0），待真实精读使用后调优。

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| 云端会话多端实时同步 (WebRTC) | 当前单机 SQLite WAL 足够满足本地使用 | 当跨设备局域网同步协议升级为实时流时 | Sync Team |
| 跨文章全库向量 RAG 检索 | 本地 deterministic NLP 与词典已覆盖当前精读需求 | 当遇见区引入开放式学术文献问答时 | Search Team |

---

## [NOTE] Out of Scope
- 修改底层 spaCy 与规则引擎词法解析算法；
- 引入重量级 Python ORM（SQLAlchemy）或外部 Redis 缓存；
- 破坏纯原生 DOM 与零 `innerHTML` 铁律。

---

## Deviation Table (post-execution, filled before merge)
| plan text | what was actually built | why |
|---|---|---|
| *(Pending Execution)* | *(Pending Execution)* | *(Pending Execution)* |
