# Companion Multi-Action HITL Implementation Plan

> **Goal**: 复用现有 proposal 生命周期，为写作台修订建议与进度页周学习目标提供逐条确认/拒绝能力。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite / pytest；Go 1.24+ / go-openai；原生 JavaScript ES Modules / node:vm。
> **Spec Reference**: 用户本轮多动作 HITL 要求；`docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md`。
> **Global Constraints**: 复用 proposal 表、SSE `proposal` 事件与 `cp-drawer-proposals`；不新增 SSE 事件；proposal.id 为幂等键；空/畸形输入 fail-closed；reject 只流转状态；不合并 PR。
> **Branch**: `feature/companion-multi-action-hitl` — 从 `master@12456ea` 创建，落地仅通过 PR。
> **Repo Invariants Pointer**: `AGENTS.md`、`docs/agents/architecture.md`、`WORKMEMORY/PROTOCOL.md`。

---

## [NOTE] Decisions So Far

- 不新增 proposal `type` 列：`action` 已承载动作类型，`id` 已承载 SSE↔DB 幂等键。
- 新 action 为 `apply_writing_revision` 与 `set_weekly_goal`；对应模型工具为 `propose_writing_revision` 与 `propose_weekly_goal`。
- 写作修订更新既有 `essays`；周目标写入 `app_settings`，均不新增业务表。
- 未保存作文不支持服务端修订，前端必须明确要求先保存；七类 SSE 事件不变。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: Proposal 多动作生命周期 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/services/companion_proposal.py`
- Test: `tests/test_companion_services.py`、`tests/test_companion_routes.py`

**Interfaces:**
- Consumes: `CompanionProposalService.create_proposal(...)`、`ProposalExecReq`、既有 SQLite 连接。
- Produces: `execute_proposal(...)` 支持 `apply_writing_revision` 与 `set_weekly_goal`，重复确认返回 `created_count=0`，拒绝后确认抛 `ValueError`。

**SSOT Effect:** —（只记录测试计数，不写产品报表。）

**Injected Instincts:**
- [ ] `[Instinct: Fail Closed]`: 空/畸形输入在任何状态写入前抛 `ValueError`，状态保持 `pending`。
- [ ] `[Instinct: Idempotency]`: proposal.id 防重放；拒绝后不可再确认。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: Proposal 多动作生命周期。Mode: AFK。先为写作修订、周目标、重复确认、拒绝后确认、400/pending 写失败测试，再最小实现。不得新增表或 SSE 事件。返回原始退出码、pass 数与 diff。"

**Step Breakdown:**
- [ ] 写多动作与状态机失败测试并验证 RED。
- [ ] 实现两个 action 与统一拒绝后防确认。
- [ ] 跑服务/路由测试并验证 GREEN。
- [ ] 审核事务边界、副作用次数与 diff。

---

### Task 2: Go/Python proposal 生成契约 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `agent/internal/companion/tools.go`、`agent/internal/companion/loop.go`、`agent/internal/companion/prompts.go`、`delector/services/companion_agent.py`
- Test: `agent/internal/companion/tools_test.go`、`agent/internal/companion/loop_test.go`、`tests/test_companion_agent_loop.py`、`tests/test_companion_routes.py`

**Interfaces:**
- Consumes: OpenAI function calls `propose_writing_revision` / `propose_weekly_goal`。
- Produces: 既有 `EventProposal`，action 分别为 `apply_writing_revision` / `set_weekly_goal`，不得调用本地写工具。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Contract]`: proposal.id/action/title/payload 在 SSE 与 SQLite 间逐字段守恒。
- [ ] `[Instinct: No Silent Write]`: 模型提议路径不得直接执行写库工具。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: Go/Python proposal 生成契约。Mode: AFK。先加工具 schema、SSE action 与不直接写库的测试，再实现最小映射；Python fallback 只扩 JSON proposal 形状，不改七类事件。返回 go test 与 pytest 收据。"

**Step Breakdown:**
- [ ] 写 Go schema/loop 与 Python fallback 失败测试并验证 RED。
- [ ] 实现两个工具声明和 proposal 映射。
- [ ] 跑 Go、Python 与 SSE 路由测试并验证 GREEN。

---

### Task 3: 前端多动作提议与页面入口 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/js/cp-drawer-proposals.js`、`static/js/cp-drawer.js`、`static/js/writer.js`、`static/js/main.js`、`static/modals/drawer.html`、`static/index.html`
- Test: `tests/test_companion_context_probe.mjs`、`tests/test_companion_context_probe.py`

**Interfaces:**
- Consumes: `renderProposalCard(...)`、`window.getWriterRevisionState()`、现有 `submitPrompt(...)`。
- Produces: `sendWriterRevisionProposal()`、`sendProgressWeeklyGoal()`、`applyCompanionRevision(content)`；按 action 渲染并禁用畸形确认。

**SSOT Effect:** —（探针 checks/scenarios 仅作测试证据。）

**Injected Instincts:**
- [ ] `[Instinct: Real Source]`: 探针驱动真实模块，断言原句/改写/目标文本与按钮状态。
- [ ] `[Instinct: Fail Closed]`: 空/畸形确认禁用；reject 后确认按钮不可恢复。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 前端多动作提议与页面入口。Mode: AFK。先扩真实源码探针并验证旧实现 RED；复用 cp-drawer-proposals，新增写作/进度快捷入口和草稿刷新，重建 index。不得新造第二套 proposal UI 或协议。"

**Step Breakdown:**
- [ ] 写 action 渲染、快捷入口、禁用和 reject 场景并验证 RED。
- [ ] 最小实现并重建 `static/index.html`。
- [ ] 跑探针与变异验证，确认反例变红、还原复绿。

---

### Task 4: 契约闸与全量交付 [Tier: 2-Standard] [Mode: AFK] [Role: Verifier]

**Files:**
- Modify: `tools/check_companion_contract.py`、`docs/plans/2026-11-03-companion-multi-action-hitl.md`
- Test: 全量 Python、前端探针、Go、三闸、契约、builder、ruff。

**Interfaces:**
- Consumes: 两个新 action 与两个前端导出。
- Produces: 机械契约覆盖及最终 PR 验证收据。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Anti False Green]`: 契约闸同时检查生产 action 与前端分支，不只检查字符串存在。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 契约闸与全量交付。Mode: AFK。补两个 action/导出契约，串行跑全量 pytest 和全部指定门禁，记录实际数字；只开 PR，不合并。"

**Step Breakdown:**
- [ ] 补契约断言并跑定向测试。
- [ ] 串行执行全量 pytest，随后跑探针、Go、三闸、builder、ruff 与 diff 检查。
- [ ] 填偏差表，提交并开 PR，不合并。

---

## [NOTE] Fog of War (Not Yet Specified)

- 无阻塞未知项；写作未保存草稿明确列为不支持范围，不进入本批实现。

---

## [NOTE] Out of Scope

- 新 proposal 表/列、新 SSE 事件、断流重连、真实浏览器 live-selection、Android 真机点检。
- 未保存作文的服务端修订、周目标独立业务表与独立确认 UI。
- 合并 PR、直推 master、版本号与 Release。

## Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| 未保存作文的修订 | 服务端无法稳定定位 essays 行，避免静默新建或覆盖 | 用户明确要求未保存草稿也接受修订，且先定义持久化语义 | 后续写作任务 |
| 周目标独立历史与编辑界面 | 本批只要求生成周目标并写入，复用设置存储即可 | 需要多周历史、目标勾选或独立统计时 | 后续进度任务 |
| Android/真实浏览器验收 | 本批以契约与真源码探针为边界 | 发版前真机/浏览器专项点检 | 验证任务 |

## Deviation Table (post-execution)

| plan text | what was actually built | why |
| --- | --- | --- |
| 全部四项任务 | 两个 action、Go/Python proposal 生成、前端渲染与快捷入口、契约及探针均按计划交付 | 额外统一禁止 rejected 的 vocab proposal 再确认，消除既有状态机重放缺口 |
