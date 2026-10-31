# 内置伴学宠物智能体化（Companion Study Agent）· 实施计划

> **Goal**: 实现德语伴学宠物（Eule）智能体化交互抽屉，打通基于 SSE 的确定性有界 Agent 循环与 Proposal 确认制卡闭环。  
> **Tech Stack**: Python 3.11 / FastAPI / Starlette / spaCy / Vanilla JS ES Modules / Web Components & DOM  
> **Spec Reference**: `docs/specs/2026-10-31-companion-study-agent-design.md`  
> **Global Constraints**:  
> - 零第三方 Agent 框架（坚决不引入 LangChain / CrewAI / LangGraph / LlamaIndex 等）  
> - 严格遵守 ADR-0010 §5 红线（交互请求不加 Go 代理跳，交互层留 Python）  
> - 严格遵守 ADR-0023 架构规范（有界循环 MAX_TURNS=3、硬超时 15s、确定性工具白名单与裁判独立终审）  
> - 严格遵守 `docs/design-system.md` 去 AI 同质化规范（德式墨线、真实纸质与学术排版节奏，杜绝全能聊天窗与黑色毛玻璃）  
> - 严格遵循前端分层契约（`cp-state.js` 属于 L1 纯状态容器，`cp-api.js` 属于 L2 持久化访问层，零顶层可变状态）  
> - 保持全量基线与六道机械闸全绿（`layer_invariants`、`mock_drift`、`silent_degradation`、`frontend_api_contract`、`frontend_layers`、`index_html_sync` 全部 exit 0）  
> - 编码安全：UTF-8 编码，命令前置 `PYTHONIOENCODING=utf-8`，避免 Windows GBK 重定向截断  
> **Branch**: `feat/companion-study-agent` — 从 `master` 签出，严格通过 PR 合入。

---

## [NOTE] Decisions So Far

- [ADR-0008](docs/adr/2026-09-06-adr-0008-go-agent-runtime-architecture.md): 确定 Go Agent Runtime + Python NLP Engine 混合架构，Go 专司批处理内容生产。
- [ADR-0010 §5](docs/adr/2026-09-07-adr-0010-encounter-zone-layered-go-agent-producer.md): 交互请求不加 Go 代理跳；已知词判定不离开本机 DB。
- [ADR-0021](docs/adr/2026-10-10-adr-0021-stay-on-python-language-choice-criteria.md): 保持 Python 为主体语言，交付物与运行时为第一判据。
- [ADR-0023](docs/adr/2026-10-14-adr-0023-interactive-layer-verification-driven-agent-loop.md): 交互层引入有界、带确定性裁判的验证驱动循环（首个落点已在写作润色模块跑通）。
- [Design Spec](docs/specs/2026-10-31-companion-study-agent-design.md): 确认采纳方案 B（导学抽屉）作为当前唯一交付面；强制中立 SSE 协议与 Proposal 写操作确认门禁，作为日后平滑过渡到方案 C（Go 常驻 DAG 批处理）的绞杀者第一阶段。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: 伴学 Agent 循环内核与有界性 TDD (`companion_agent.py`) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/services/companion_agent.py`
- Create: `tests/test_companion_agent_loop.py`

**Interfaces:**
- Consumes:
  - `delector.services.llm_client.chat(messages, model, max_tokens, timeout, response_format)`
  - `delector.tools.TOOL_REGISTRY`（只读白名单：`analyze`、`writing_check`、`vocab_stats`）
- Produces:
  - `async def run_companion_agent_loop(messages: list[dict], *, on_event: Callable[[dict], None], deadline_s: float = 15.0, max_turns: int = 3, chat_fn: Optional[Callable] = None) -> CompanionAgentOutcome`
  - 数据结构：`CompanionAgentOutcome(status, text, proposals, turns, token_count, reason)`

**Injected Instincts:**
- [ ] `[Instinct: Bounded Loop]`: 严格限制 `max_turns=3` 与 `deadline_s=15.0`，超支即带 `reason="budget_exceeded"` 或 `reason="deadline"` 收敛退出，严禁死循环。
- [ ] `[Instinct: Zero-Silent-Failure]`: 模型解析异常或工具调用异常必须记录并在 event 流抛出对应人话错误码，不得假绿或静默吞异常。
- [ ] `[Instinct: Keyless Offline Stub]`: 当 `chat_fn` 未注入且系统未配置 `API_KEY` 时，快速返回本地模板规则生成的预置问答，确保离线环境可测试。

**Subagent Prompt Scaffold:**
> "Implement Task 1: Companion Agent Core Loop.  
> Mode: AFK | Role: TDD Builder  
> Goal: Implement pure Python verification-driven companion agent loop with strict turn/budget bounds and tool whitelist.  
> Target Files: Create `tests/test_companion_agent_loop.py`, Create `delector/services/companion_agent.py`.  
> TDD Steps:  
> 1. Write failing tests in `tests/test_companion_agent_loop.py`: test bounded turns (mock LLM returning continuous tool_call stops at turn 3), test tool execution (`analyze`), test proposal generation, and test zero-key fallback.  
> 2. Run `PYTHONIOENCODING=utf-8 pytest tests/test_companion_agent_loop.py -q` and verify failure (RED).  
> 3. Implement minimal code in `delector/services/companion_agent.py` (GREEN).  
> 4. Flatten with Guard Clauses and enforce strict typing (mypy --strict compatible).  
> 5. Verify tests pass (GREEN).  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write failing tests in `tests/test_companion_agent_loop.py` (RED)**
- [ ] **Step 2: Run pytest and verify expected failures**
- [ ] **Step 3: Implement `delector/services/companion_agent.py` (GREEN)**
- [ ] **Step 4: Run pytest and confirm all passed**
- [ ] **Step 5: Code cleanup & mypy strict typing check**
- [ ] **Step 6: Capture physical execution receipt**
- [ ] **Step 7: Git atomic commit**: `feat(companion): implement verification-driven agent core loop`

---

### Task 2: 后端路由与 SSE 流式端点 (`companion.py`) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/routes/companion.py`
- Modify: `delector/routes/__init__.py:20-112`
- Create: `tests/test_companion_routes.py`

**Interfaces:**
- Consumes:
  - `delector.services.companion_agent.run_companion_agent_loop`
  - `delector.core.database._require_localhost`
- Produces:
  - `POST /api/companion/chat` -> `StreamingResponse(media_type="text/event-stream")`
  - `POST /api/companion/proposal/execute` -> `{"status": "ok", "result": ...}` (依赖 `_require_localhost`)
  - `GET /api/companion/context` -> `{"status": "ok", "context": ...}`

**Injected Instincts:**
- [ ] `[Instinct: Client Disconnect Cancellation]`: 遵循 `writing.py:501` 模式，轮询 `request.is_disconnected()`，客户端断开立即取消任务，严禁无主协程后台空转烧 Token。
- [ ] `[Instinct: Router Order]`: `companion.router` 必须在 `main.router` 之前注册，遵守分域路由在前、通用 handler 垫底纪律。
- [ ] `[Instinct: Localhost Guard]`: 执行 Proposal 写操作的端点必须声明 `dependencies=[Depends(_require_localhost)]`。

**Subagent Prompt Scaffold:**
> "Implement Task 2: Companion Routes & SSE Streaming.  
> Mode: AFK | Role: TDD Builder  
> Goal: Implement `/api/companion` endpoints with resilient SSE streaming and localhost-guarded proposal execution.  
> Target Files: Create `tests/test_companion_routes.py`, Create `delector/routes/companion.py`, Modify `delector/routes/__init__.py`.  
> TDD Steps:  
> 1. Write failing tests in `tests/test_companion_routes.py` using FastAPI TestClient to verify SSE event stream structure (`thought`, `delta`, `tool_start`, `tool_end`, `proposal`, `done`), localhost security gate on execute endpoint, and context query.  
> 2. Run pytest to verify RED.  
> 3. Implement `delector/routes/companion.py` and register in `delector/routes/__init__.py` before `main.router`.  
> 4. Verify all tests pass (GREEN).  
> 5. Verify disconnect cleanup logic is properly wired.  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write failing tests in `tests/test_companion_routes.py` (RED)**
- [ ] **Step 2: Run pytest and verify expected failures**
- [ ] **Step 3: Implement `delector/routes/companion.py` and register in `delector/routes/__init__.py` (GREEN)**
- [ ] **Step 4: Run pytest and confirm all passed**
- [ ] **Step 5: Verify route registration order and static security guards**
- [ ] **Step 6: Capture physical execution receipt**
- [ ] **Step 7: Git atomic commit**: `feat(companion): add companion sse streaming and proposal endpoints`

---

### Task 3: 前端分层机械闸扩展与状态/API 模块 (`cp-state.js` · `cp-api.js`) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/check_frontend_layers.py:304-360`
- Create: `static/js/cp-state.js`
- Create: `static/js/cp-api.js`
- Create: `tests/test_companion_api_contract.py`

**Interfaces:**
- Consumes:
  - `static/js/core.js` (`api`, `escHtml`)
- Produces:
  - `static/js/cp-state.js`: 导出的纯状态容器 `companionState`（维护 `isOpen`, `activeTab`, `messages`, `inFlight`, `proposals`），零顶层可变变量。
  - `static/js/cp-api.js`: `streamCompanionChat({ messages, context, onEvent, onError, onDone, signal })`, `executeProposal(proposalId, action, payload)`。

**Injected Instincts:**
- [ ] `[Instinct: L1/L2 Layer Invariants]`: `cp-state.js` 必须注册为 L1（零 DOM、零网络、零导入）；`cp-api.js` 必须注册为 L2（只允许导入 `./core.js`，零 DOM 触碰）。
- [ ] `[Instinct: Gate-Before-Code]`: 先在 `tools/check_frontend_layers.py` 登记分层契约，确认机械闸识别新模块。

**Subagent Prompt Scaffold:**
> "Implement Task 3: Frontend L1/L2 Modules and Layer Invariants Gate Extension.  
> Mode: AFK | Role: TDD Builder  
> Goal: Create pure state container `cp-state.js` (L1) and network API client `cp-api.js` (L2), registered in `check_frontend_layers.py`.  
> Target Files: Modify `tools/check_frontend_layers.py`, Create `static/js/cp-state.js`, Create `static/js/cp-api.js`, Create `tests/test_companion_api_contract.py`.  
> TDD Steps:  
> 1. Add `cp-state.js` to `LAYER_SPEC` as L1 and `cp-api.js` as L2 in `tools/check_frontend_layers.py`. Add both to `MUTABLE_STATE_MODULES`.  
> 2. Run `python tools/check_frontend_layers.py` and verify it fails due to missing files (RED).  
> 3. Create `static/js/cp-state.js` with pure state object and freeze invariants.  
> 4. Create `static/js/cp-api.js` with SSE reader using `fetch` + `ReadableStream` (`getReader()`).  
> 5. Run `python tools/check_frontend_layers.py` and verify exit 0 (GREEN).  
> 6. Run API contract checker to confirm route consistency.  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Update `tools/check_frontend_layers.py` with `cp-state.js` and `cp-api.js` (RED)**
- [ ] **Step 2: Run layer checker to confirm red state**
- [ ] **Step 3: Implement `static/js/cp-state.js` and `static/js/cp-api.js` (GREEN)**
- [ ] **Step 4: Run layer checker and verify exit code 0**
- [ ] **Step 5: Write contract verification tests and run them**
- [ ] **Step 6: Capture physical execution receipt**
- [ ] **Step 7: Git atomic commit**: `feat(companion): introduce cp-state container and cp-api sse client with layer enforcement`

---

### Task 4: 伴学抽屉视图组件与德式排版渲染 (`cp-drawer.js` · CSS) [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Builder]

**Files:**
- Create: `static/js/cp-drawer.js`
- Modify: `static/style.css` (追加 Companion Drawer 印刷墨线样式小节)
- Test: `tools/check_frontend_layers.py`, DOM integrity tests

**Interfaces:**
- Consumes:
  - `static/js/cp-state.js` (`companionState`)
  - `static/js/cp-api.js` (`streamCompanionChat`, `executeProposal`)
  - `static/js/core.js` (`escHtml`, `notify`)
- Produces:
  - `CompanionDrawer`: `init()`, `open(contextPayload)`, `close()`, `toggle()`, `appendUserMessage(text)`, `renderStreamingDelta(delta)`, `renderToolChip(tool, label)`, `renderProposalCard(proposal)`.

**Injected Instincts:**
- [ ] `[Instinct: Editorial Design System]`: 严禁黑色毛玻璃或彩色弥散光！采用物理纸张底色（`var(--paper)`）、印刷墨线边框（`1.5px solid var(--ink)`）、硬直角微倒角与学术排版（`docs/design-system.md`）。
- [ ] `[Instinct: Zero-innerHTML XSS Guard]`: 用户输入与不可信模型文本必须经 `escHtml` 过滤，富文本渲染使用白名单标记替换，杜绝 XSS 注入。
- [ ] `[Instinct: Responsive Drawer]`: 桌面端右侧 360px Docked 抽屉；移动端（`max-width: 768px`）自底向上 Bottom Sheet，避免遮挡正文。

**Subagent Prompt Scaffold:**
> "Implement Task 4: Companion Drawer UI Component & Editorial Styling.  
> Mode: AFK | Role: Frontend Builder  
> Goal: Implement `cp-drawer.js` and corresponding CSS adhering strictly to the editorial design system.  
> Target Files: Create `static/js/cp-drawer.js`, Modify `static/style.css`.  
> Steps:  
> 1. Add CSS rules in `static/style.css` for `#companion-drawer`, message thread, tool status chips, and proposal cards using DeLector tokens (`--paper`, `--ink`, `--serif-heading`, `--coral`).  
> 2. Implement `cp-drawer.js` to manage DOM rendering, drawer toggle animations, message streaming updates, and proposal action dispatching.  
> 3. Verify zero top-level mutable leaks in `cp-drawer.js`.  
> 4. Run `python tools/check_frontend_layers.py` to ensure module contracts pass.  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Add editorial drawer CSS classes to `static/style.css`**
- [ ] **Step 2: Implement DOM creation and stream rendering in `static/js/cp-drawer.js`**
- [ ] **Step 3: Implement proposal confirmation card event handlers**
- [ ] **Step 4: Verify mobile breakpoint and responsive layout**
- [ ] **Step 5: Run frontend mechanical gates**
- [ ] **Step 6: Capture physical execution receipt**
- [ ] **Step 7: Git atomic commit**: `feat(companion): implement editorial companion drawer view component`

---

### Task 5: 宠物主控接线与精读上下文捕获 (`companion.js`) [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Builder]

**Files:**
- Modify: `static/js/companion.js:680-782`
- Modify: `static/index.html` (以及通过 `tools/build_index_html.py` 重新生成)
- Test: `tools/check_index_html_sync.py`, `tools/index_dom_probe.mjs`

**Interfaces:**
- Consumes:
  - `static/js/cp-drawer.js` (`CompanionDrawer`)
  - `static/js/reader.js` / `static/js/rd-state.js` (提取选中文本及段落元数据)
- Produces:
  - 宠物本体交互升级：点击宠物形象在「气泡闲聊/表情」与「展开伴学抽屉」间顺畅切换。
  - 自动捕获当前视口上下文（选中的德语难句、当前文章标题、所属 CEFR 级别）并注入抽屉初始态。

**Injected Instincts:**
- [ ] `[Instinct: Index Sync Guard]`: 修改 `index.html` 必须确保符合 `tools/build_index_html.py` 规则，修改后必须执行 `python tools/build_index_html.py --check`，违背即假绿。
- [ ] `[Instinct: Non-Intrusive Coupling]`: `companion.js` 仅作为事件中继器（Event Relay），不直接侵入抽屉内部 DOM 细节。

**Subagent Prompt Scaffold:**
> "Implement Task 5: Mascot Integration & Context Relay.  
> Mode: AFK | Role: Frontend Builder  
> Goal: Wire mascot click events to `CompanionDrawer` and capture active reading context.  
> Target Files: Modify `static/js/companion.js`, Modify `static/index.html` via `tools/build_index_html.py`.  
> Steps:  
> 1. In `static/js/companion.js`, import `CompanionDrawer` and wire click on mascot avatar to open drawer with active reader context.  
> 2. Add companion drawer DOM mount container in `static/layout/` or `index.html` and run `python tools/build_index_html.py`.  
> 3. Verify `python tools/check_index_html_sync.py` returns exit 0.  
> 4. Ensure mascot animations (`is-happy`, `is-wiggle`) trigger during drawer interactions.  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Wire `CompanionDrawer` import and toggle in `static/js/companion.js`**
- [ ] **Step 2: Add context harvester (extract selected text and reader metadata)**
- [ ] **Step 3: Mount drawer markup and run `python tools/build_index_html.py`**
- [ ] **Step 4: Run `python tools/check_index_html_sync.py` and confirm exit code 0**
- [ ] **Step 5: Verify mascot status synchronization**
- [ ] **Step 6: Capture physical execution receipt**
- [ ] **Step 7: Git atomic commit**: `feat(companion): wire companion mascot to study drawer with reader context`

---

### Task 6: 前端契约与事件类型双向断言探针 (`check_companion_contract.py`) [Tier: 1-Light] [Mode: AFK] [Role: Quality Gate Builder]

**Files:**
- Create: `tools/check_companion_contract.py`
- Modify: `tests/server_helpers.py` (若需要注册新守卫)

**Interfaces:**
- Consumes:
  - `delector/services/companion_agent.py`（静态扫描发出的 SSE 事件常量）
  - `static/js/cp-api.js`（静态扫描 switch/case 监听的事件名称）
- Produces:
  - 机械断言：双向事件集合差集必须为空。若后端增加了 `proposal_update` 而前端未处理，或前端监听了后端已废弃的事件，门禁报 1 退出。

**Injected Instincts:**
- [ ] `[Instinct: Physical Static Analysis]`: 使用 Python `tokenize` / `ast` 分析文件源码，严禁粗暴正则匹配导致假阳性或假阴性。

**Subagent Prompt Scaffold:**
> "Implement Task 6: Companion Contract Static Enforcement Gate.  
> Mode: AFK | Role: Quality Gate Builder  
> Goal: Create a deterministic mechanical check ensuring SSE event types between backend and frontend never drift.  
> Target Files: Create `tools/check_companion_contract.py`.  
> Steps:  
> 1. Implement `tools/check_companion_contract.py` to extract event names from `delector/services/companion_agent.py` and `static/js/cp-api.js`.  
> 2. Assert that symmetric difference between sets is empty.  
> 3. Run `python tools/check_companion_contract.py` and verify exit 0.  
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write `tools/check_companion_contract.py` with AST/token extraction**
- [ ] **Step 2: Run verification script and assert exit code 0**
- [ ] **Step 3: Intentionally inject a mutation to verify gate fails (mutation test)**
- [ ] **Step 4: Revert mutation and confirm clean exit 0**
- [ ] **Step 5: Capture physical execution receipt**
- [ ] **Step 6: Git atomic commit**: `test(companion): add companion sse event contract static gate`

---

### Task 7: 全量门禁回归、真机点检与 HITL 验收门 [Tier: 3-Critical] [Mode: HITL] [Role: Gatekeeper]

**Files:**
- Modify: `docs/specs/2026-10-31-companion-study-agent-design.md` (标记实施状态)
- Modify: `WORKMEMORY/work.log` (追加本次会话交付日志)

**Interfaces:**
- Consumes:
  - 全量 pytest 测试套件
  - 六道既有机械闸 + 新增契约闸
  - ruff 与 mypy strict 静态检查

**Injected Instincts:**
- [ ] `[Instinct: Zero-Regression Baseline]`: 测试通过数不得低于基线（2584 passed + 2 skipped）；用例数必须增加。
- [ ] `[Instinct: No-Bypass CI]`: 严禁 `--no-verify`，严禁降低 mypy strict 门槛。

**Subagent Prompt Scaffold:**
> "Implement Task 7: Full Regression & HITL Verification Gate.  
> Mode: HITL | Role: Gatekeeper  
> Goal: Execute full suite regression, verify all mechanical gates, and prepare PR.  
> Steps:  
> 1. Run `PYTHONIOENCODING=utf-8 pytest tests/ -q` and verify >= 2600 passed, 0 failed.  
> 2. Run `ruff check .` -> zero warnings.  
> 3. Run `mypy --strict delector tools` -> zero issues.  
> 4. Run all mechanical gates (6 existing + 1 companion contract) -> all exit 0.  
> 5. Present physical receipts and await human partner approval before PR creation.  
> Return: Full audit receipt summary."

**Step Breakdown:**
- [ ] **Step 1: Run full pytest suite serially (`PYTHONIOENCODING=utf-8 pytest tests/ -q`)**
- [ ] **Step 2: Run ruff check and mypy strict on all touched modules**
- [ ] **Step 3: Run all mechanical gates**
- [ ] **Step 4: Update design spec and append WORKMEMORY log**
- [ ] **Step 5: HITL checkpoint: human partner verification**
- [ ] **Step 6: Git atomic commit**: `chore(companion): complete companion agent implementation and audit gates`

---

## [NOTE] Deferred Gap Register

| Gap | Why Deferred | Trigger That Forces Revisiting | Owner |
| :--- | :--- | :--- | :--- |
| **Go Supervisor 常驻 DAG 批处理 (方案 C)** | 当前处于绞杀者阶段 1，首要任务是在 Python 跑通交互体验与中立协议；直接做 C 违反 ADR-0010 §5 红线且工程面过大 | 用户下达整书分析或批量爬虫等长程批处理需求（耗时 >30s） | Architect |
| **离线本地小模型（Ollama/qwen）驱动** | 本机已配置 `qwen3.5:4b`，但当前优先接入云端/聚合 API 跑通首发；本地小模型在德语语法准确度上有待系统化基准标定 | 云端 API 连通性不可用或用户明确要求完全断网伴学 | NLP Eng |
| **全双工实时语音交互 (Duplex Voice)** | DeLector 核心是精读与备考，打字与点击阅读为高频；实时双工语音在 Web/WebView 存在回声消除与延迟断层 | 德福/歌德口语备考专项题库功能立项 | UX Lead |

---

## [NOTE] Deviation Table

| Plan Text | What Was Actually Built | Why |
| :--- | :--- | :--- |
| *(待执行阶段填写)* | *(待执行阶段填写)* | *(待执行阶段填写)* |

---

## [NOTE] Fog of War (Not Yet Specified)

- *当前所有关键路径与技术边界均已在 Phase 1~3 收敛，无阻塞性技术未知数。*

---

## [NOTE] Out of Scope

- 严禁在未经用户点击 Proposal 的情况下自动改写 SQLite 数据库。
- 严禁引入第三方 Agent 框架（LangChain, LangGraph, AutoGen 等）。
- 严禁在交互层引入 Go 代理跳（遵守 ADR-0010 §5 红线）。
- 严禁修改 Android 原生 Gradle 依赖或引入非标准 WebView 权限。
