# Companion 传输边界、RunLoop 接线与 submitPrompt 收敛 Implementation Plan

> **Goal**: 在不改变七类 SSE 事件契约和用户可见行为的前提下，修复跨 chunk 丢帧、让 Go 已抽 helper 进入生产路径，并用完整行为探针收敛前端提交流。
> **Tech Stack**: Python 3.11 / FastAPI / pytest；Go 1.24+ / go-openai / httptest；原生 JavaScript ES Modules / node:vm。
> **Spec Reference**: 用户本轮三项重构要求；`docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md`；`docs/plans/archive/2026-10-31-companion-study-agent.md`。
> **Global Constraints**: 七类事件 `thought/tool_start/tool_end/delta/proposal/done/error` 不变；转发字节不变；不碰 `version.py`、`build.gradle`、`sw.js`、`index.html`、`CHANGELOG.md`、`README.md`；不推送、不建 PR；每项独立提交；禁止 `--no-verify`。
> **Branch**: `refactor/companion-boundaries` — 从 `master` 的 `e7bd1cb` 创建，在 `.worktrees/companion-boundaries` 独立执行；只本地提交，合入方式由用户后续决定。
> **Repo Invariants Pointer**: `AGENTS.md`、`docs/agents/ops.md`、`WORKMEMORY/PROTOCOL.md`。

---

## [NOTE] Decisions So Far

- 顺序固定为 **SSE → Go RunLoop → submitPrompt**：先闭合已确认的数据丢失边界，再改 Agent 核心循环，最后改 UI 状态链；后一项不依赖前一项的实现细节，但按用户指定优先级串行提交。
- 所有生产重构都以现有行为为基线。Go 对照测试若暴露 helper 与内联逻辑差异，先归类；未获明确证据前不以接线名义改变生产语义。
- 前端探针复用 `tests/test_companion_context_probe.mjs` 的真源码 `node:vm` 沙箱，避免维护第二套 DOM/模块桩。
- 若改到 `static/modals/drawer.html`，必须运行 `python tools/build_index_html.py` 和 `python tools/build_index_html.py --check`；本计划预计不需要改该 HTML，也不改生成后的 `static/index.html`。

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: SSE 缓冲分帧与持久化守恒 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/companion.py:131-188`
- Test: `tests/test_companion_routes.py`
- Contract: `tools/check_companion_contract.py`（只运行，不修改）

**Interfaces:**
- Consumes: `dispatch_companion_stream(...) -> AsyncIterator[bytes]`；既有 `CompanionSessionService.save_turn`、`CompanionProposalService.create_proposal`。
- Produces: 同文件缓冲式累积器，接收任意 `bytes` 分片并只释放按空行闭合的完整 SSE 帧；`_wrapped_stream` 对每个完整帧最多解析、聚合一次，原始 `chunk` 继续原样 `yield`。

**SSOT Effect:** —（不产出报表数字；测试只统计事件与持久化调用次数。）

**Injected Instincts:**
- [ ] `[Instinct: Contract]`: 原始网络字节逐块不变；不完整帧不解析，跨 UTF-8/JSON 分片不丢帧。
- [ ] `[Instinct: Persistence]`: `save_turn` 每轮最多一次；每个 proposal id 只落库一次；重复分帧不得重复副作用。
- [ ] `[Instinct: RED]`: 先运行一条在逐 chunk 实现上确定失败的复现测试，保存原始红灯输出。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: SSE 缓冲分帧与持久化守恒。Mode: AFK。只改 companion.py 与 test_companion_routes.py。先增加 JSON 中间断开的真实路由复现并运行确认 RED，再加 2/3/N 段、逐字节和固定种子随机分片测试，断言响应字节拼接守恒、delta/thought/proposal 聚合不丢不重、save_turn 与 create_proposal 次数正确；最后实现按空行分帧的缓冲累积器并跑契约、全量门禁。返回原始退出码、pass 数、diff 与提交哈希。"

**Step Breakdown:**
- [ ] **RED**: 在现有路由测试中让 `delta`、`thought`、`proposal` 的 JSON 跨 chunk，断言数据库中的正文/思维链/proposal 完整；运行并确认当前实现失败。
- [ ] **GREEN**: 用字节缓冲区按空行找完整帧，只消费完整 `data:` 负载；不完整尾部留到下一次；转发仍直接 `yield chunk`。
- [ ] ** fragmentation matrix**: 覆盖整帧 2、3、N 段、逐字节、固定种子随机分片，至少一例切在 JSON token 中间；断言事件序列不丢不重、持久化只发生一次。
- [ ] **Verify**: `python -m pytest tests/test_companion_routes.py -q`；`python tools/check_companion_contract.py`。
- [ ] **Full gates**: `python -m pytest tests`；全部现有 `tools/*.mjs` 与 `tests/test_*probe.mjs` 探针；三闸 `check_frontend_layers.py`、`check_mock_drift.py`、`check_silent_degradation.py`；`(cd agent && go test ./...)`；`ruff check .`；`git diff --check`。
- [ ] **Commit**: 独立 `fix(companion): ...` 提交并给阶段报告。

**Risk / Rollback:** 风险集中在 SSE 空行变体与尾部不完整帧；不改变客户端字节和持久化 API。回滚只需还原该提交的 `companion.py` 与测试，不影响另外两项。

---

### Task 2: Go RunLoop 等价接线与阶段拆分 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder + Equivalence Reviewer]

**Files:**
- Modify: `agent/internal/companion/loop.go:137-549`
- Modify if equivalence requires: `agent/internal/companion/prompts.go`、`agent/internal/companion/tool_calls.go`
- Test: `agent/internal/companion/loop_test.go`、`prompts_test.go`、`tool_calls_test.go`

**Interfaces:**
- Consumes: `FormatStudyContext`、`BuildSystemPrompt`、`BuildPromptNudge`、`AggregateToolCalls`、`FilterValidToolCalls`、`FormatToolErrorMessage`、`FormatToolArgErrorMessage`。
- Produces: 生产路径实际调用上述 7 个 helper；`RunLoop` 由 `buildTurnPrompt` / `receiveTurn` / `executeToolCalls` / `finalize` 等单一职责阶段组成，公开 `RunLoop(ctx, req, emit)` 签名与 `Outcome`/`Event` 契约不变。

**SSOT Effect:** —（行数与测试数只在阶段报告中按实测口径记录，不写回产品数据。）

**Injected Instincts:**
- [ ] `[Instinct: Equivalence]`: 接线前对照同一输入的 helper 输出与 RunLoop 内联结果，覆盖 CardContext 前缀、CEFR-only、稀疏/负/乱序 tool-call index、nudge、参数错误与执行错误。
- [ ] `[Instinct: No Semantic Drift]`: 差异逐条归类为 helper 漂移或内联疑似 bug；疑似内联 bug 先报告，不顺手修复。
- [ ] `[Instinct: Integration]`: 使用 `httptest` 的本地 SSE 服务，不出网；保留事件、消息、工具调用与 proposal 断言。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: Go RunLoop 等价接线与阶段拆分。Mode: AFK。先在 loop_test.go 增加 helper 与内联行为的对照测试并保存差异清单；生产语义以 RunLoop 当前表现为基线，除非发现明确 bug 并先报告。逐条解决 helper 漂移后接线 7 个 helper，再按 buildTurnPrompt/receiveTurn/executeToolCalls/finalize 拆阶段。每一步跑 go test ./...，最终跑 Python/前端/三闸/ruff 全量门。报告 412 行基线、最终行数、复杂度变化和每组测试证据。"

**Step Breakdown:**
- [ ] **Equivalence RED/evidence**: 捕获 mock LLM 收到的 system prompt，与 helper 组合结果比较；对 tool-call 聚合、错误 JSON、nudge 分别对照内联输入/输出。
- [ ] **Difference register**: 报告每条差异及归类；CEFR-only 等既有可疑行为若需另修，登记但不混入本次语义保持重构。
- [ ] **Wire**: 让 7 个 helper 全部进入生产路径；对照测试与既有 `loop_test.go` 全绿后才拆阶段。
- [ ] **Split**: 依次抽 `buildTurnPrompt`、`receiveTurn`、`executeToolCalls`、`finalize`，每次运行 `go test ./...`，不得跨阶段携带未验证改写。
- [ ] **Full gates**: 同 Task 1 的 pytest、全部探针、三闸、Go、ruff、diff 检查；另记录 `RunLoop` 起止行与阶段函数长度。
- [ ] **Commit**: 独立 `refactor(agent): ...` 提交并给阶段报告。

**Risk / Rollback:** 风险集中在稀疏 index 聚合、错误消息形状、fallback/nudge 和 middleware `TurnContext` 消息回写；任一阶段红即停止扩大拆分。回滚该 Go 独立提交即可，SSE 修复不受影响。

---

### Task 3: submitPrompt 完整探针与命名事件控制器 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/js/cp-drawer.js:725-921`
- Test: `tests/test_companion_context_probe.mjs`、`tests/test_companion_context_probe.py`
- Contract: `tools/check_companion_contract.py`（只运行，不修改）

**Interfaces:**
- Consumes: `streamCompanionChat({..., onSessionId, onEvent})`、`companionState`、既有 DOM/typewriter/proposal/markdown 协作者。
- Produces: 同文件命名事件控制器，集中处理七类事件及每轮清理；`submitPrompt(userText)` 的公开签名、请求字段、消息顺序、DOM 状态和 `inFlight`/`finally` 行为不变。

**SSOT Effect:** —（探针场景与断言数只作测试证据。）

**Injected Instincts:**
- [ ] `[Instinct: Real Source]`: 真 `cp-drawer.js` 进 `SourceTextModule`，探针驱动实际 `submitPrompt`，不得用字符串存在断言替代行为。
- [ ] `[Instinct: Full Lifecycle]`: 覆盖七事件、`inFlight` 发送中防重入、发送前 writer/cards 上下文刷新、done、error、Promise reject/异常中断和 finally 清理。
- [ ] `[Instinct: Anti False Green]`: 保留反例断言，确保没有空 DOM、假 onEvent 或未兑现 Promise 造成的假绿。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: submitPrompt 完整探针与命名事件控制器。Mode: AFK。先扩展现有 companion_context_probe，让可编程 streamCompanionChat 真实发出七类事件并驱动 submitPrompt，覆盖上下文刷新、防重入、done/error/reject/finally；先运行证明探针有效。再只在 cp-drawer.js 同文件抽事件控制器，保持行为不变，靠探针和契约闸把关。最后按显式判据评估 cp-turn.js，不满足就不拆。跑全量门并独立提交。"

**Step Breakdown:**
- [ ] **Probe first**: 增加可控异步流桩，驱动 `thought/tool_start/tool_end/delta/proposal/done/error`；断言 DOM、消息、typewriter/proposal 协作、按钮、状态和清理。
- [ ] **Interruption**: 覆盖 `error` 事件与 stream Promise reject；验证 `cancel/fail/cleanup`、按钮恢复、`inFlight=false`、无重复 assistant 提交。
- [ ] **Refresh/reentrancy**: 覆盖 writer/cards 发送前上下文刷新、请求载荷最新值、发送中第二次提交被忽略。
- [ ] **REFACTOR**: 同文件抽命名事件控制器；`submitPrompt` 只保留校验/上下文/消息准备/流启动，事件顺序和副作用不变。
- [ ] **cp-turn decision**: 仅当控制器有独立稳定接口、无大量私有 DOM 参数透传、能独立测试且分层归属清晰时才拆；否则记录“不拆”的结论。
- [ ] **Full gates**: 同 Task 1；另跑 `python tools/build_index_html.py --check`（未改 drawer.html 时不得重建或修改 index.html）。
- [ ] **Commit**: 独立 `refactor(companion): ...` 提交并给阶段报告。

**Risk / Rollback:** 风险是异步事件与 `finally` 竞态、打字机重复 flush/cancel、消息重复追加；探针必须先于重构存在。回滚该前端独立提交即可，不影响 Python/Go 两项。

---

## [NOTE] Fog of War (Not Yet Specified)

- **Go 差异归类**: 只有对照测试实测后才能确定每条是 helper 漂移还是内联疑似 bug；若属于后者，先报告并保持本任务语义不变。
- **cp-turn.js 拆分**: 由 Task 3 的控制器接口与探针结果决定，不预设新文件。

## [NOTE] Out of Scope

- 版本面、CHANGELOG、发版文档与任何 push/PR。
- 新增/删除 SSE 事件，修改请求或响应公开契约。
- 顺手修复与本次等价接线无关的 Go 语义问题。
- 修改 `static/modals/drawer.html`、重建 `static/index.html`（除非后续实际必要且按约束处理）。
- Android 真机验证与无关 UI 重构。

## Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| 已发版 RunLoop 中可能存在的 CEFR-only 等语义问题 | 本任务是等价接线，不能借重构改变行为 | 对照测试证明其为 bug 且用户明确批准行为修复 | 后续 Agent 任务 |
| `cp-turn.js` 独立模块 | 未知拆分是否只会增加参数透传 | 控制器能脱离 submitPrompt 私有 DOM 状态独立测试且分层清晰 | 后续前端任务 |
| Android 真机伴学链路 | 本轮是本地契约/行为重构，用户未要求真机 | 相关改动进入发版并触发 static 覆盖安装点检 | 发版/验证任务 |

## Deviation Table (post-execution)

| plan text | what was actually built | why |
| --- | --- | --- |
| Task 1 缓冲分帧与分片矩阵 | 同计划交付，另补 CRLF/混合空行、多行 data 与 proposal 去重变异反例 | 独立审查发现 CRLF 回溯会把单个换行误判为空行 |
| Task 2 helper 等价接线与阶段拆分 | 7 个 helper 全部接线；聚合 helper 改为 map 形式；另加 HEAD 字面 golden 与空 callsList 路径 | map 形式保持旧内联语义；独立 golden 防止接线后 helper 与 RunLoop 同源假绿 |
| Task 3 同文件事件控制器，按判据决定是否拆 `cp-turn.js` | `createCompanionTurnController` 同文件落地；`submitPrompt` 197→147 行；不拆新文件 | 控制器仍耦合多个私有 DOM/状态协作者，拆文件只增加参数透传且无复用方 |
