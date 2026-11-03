# Companion SSE Resume Implementation Plan

> **Goal**: 客户端中途断流时，保留已收到的 assistant 片段与 proposal，并凭 `X-Session-ID` 恢复当前轮次，不重放模型请求。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite / pytest；原生 JavaScript ES Modules / node:vm。
> **Spec Reference**: 用户任务 4（SSE 断流／重连）要求；`docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md`。
> **Global Constraints**: 七类 SSE 事件及帧语义不变；不新增表或 SSE 游标；不后台续跑、不重复计费；正常流仍只保存一轮；主动取消仍停止上游；代码与测试走 PR，不合并。
> **Branch**: `feature/companion-sse-resume` — 从 `origin/master@073465d` 创建，落地仅通过 PR。
> **Repo Invariants Pointer**: `AGENTS.md`、`docs/agents/architecture.md`、`docs/agents/ops.md`、`WORKMEMORY/PROTOCOL.md`。

---

## [NOTE] Decisions So Far

### 现状证据

- `delector/routes/companion.py` 的 `_wrapped_stream` 在 `async for` 正常结束后才调用 `save_turn` 与 `create_proposal`。后端自探活路径若让 `dispatch_companion_stream` 正常返回，已有部分回答会落库；但 Starlette 的 disconnect listener 抢先取消响应生成器时，循环后的持久化代码被跳过，已流出的 assistant 与 proposal 全部丢失。
- 当前先 `yield chunk`、后解析该 chunk；若生成器在 yield 点被关闭，客户端已收到的最后一帧甚至可能未进入聚合器。解析必须前移到转发之前，再统一在 `finally` 持久化。
- `static/js/cp-api.js` 已读取 `X-Session-ID` 并回填 `companionState.currentSessionId`；但 `cp-drawer.js` 的 Promise reject 分支只渲染 `[连接失败: ...]`，不读取历史。因此 session 指针虽然存在，当前轮 assistant 既不在内存消息里，也无法在当前气泡恢复；后续请求的历史上下文同样缺这轮 assistant。

### 最小修复边界

- 后端：先解析完整 SSE 帧再原样转发；`finally` 中按既有 `save_turn` / `create_proposal` 路径恰好持久化一次。取消异常继续向上传播，不改七类事件，不制造额外 `done`。响应头新增 `X-History-Length`，在流开始前给出实际 session 的持久化消息数；它只是 HTTP 元数据，不是 SSE 游标。
- 前端：传输 Promise reject 后，用本次流实际 session id 拉取既有 history 端点；只在历史长度达到后端基线 + 2、末尾 user/assistant 对匹配本次 prompt 且 assistant 非空时恢复。为覆盖取消与落库的短暂竞态，最多顺序读取三次，不加计时器、不重新 POST chat。
- 串轮防线：以 turn generation 隔离迟到的旧流事件、恢复与清理；已完成气泡不被迟到的 transport error 覆盖。持久化基线不计乐观 user，同文旧轮、未落库首轮与既有 scope 复用均有独立反例。
- 本方案是“断点恢复”，不是“断点后续生成”。主动断连仍取消上游，未生成的尾部不会补全。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: 取消路径部分轮次持久化 [Tier: 2-Standard] [Mode: AFK] [Role: Python TDD Builder]

**Files:**
- Modify: `delector/routes/companion.py`
- Test: `tests/test_companion_routes.py`

**Interfaces:**
- Consumes: `dispatch_companion_stream(...)`、`_SSEEventAccumulator.feed(chunk)`、`CompanionSessionService.save_turn(...)`、`CompanionProposalService.create_proposal(...)`。
- Produces: 响应生成器在正常结束、上游异常与 `aclose()` / cancellation 路径均保留已解析内容；原始转发字节不变，正常路径持久化次数不变；`X-History-Length` 给出本轮前的真实消息数。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Cancellation Safety]`: 在 yield 点关闭生成器也必须保存客户端已收到的完整帧；不得吞掉取消。
- [ ] `[Instinct: Exactly Once]`: 每轮只写一对 user/assistant；proposal 继续按 SSE id 去重。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 取消路径部分轮次持久化。Mode: AFK。先用真实路由 body_iterator 在 thought/delta/proposal 已转发后 aclose，证明旧实现零落库；再把解析前移并把既有持久化收进 finally。不得改变 SSE 字节或七类事件。返回原始退出码、pass 数与 diff。"

**Step Breakdown:**
- [ ] 写中途关闭、部分 assistant/thought/proposal 应落库的失败测试并验证 RED。
- [ ] 最小调整解析与 `finally` 持久化，验证正常分帧/字节/次数测试不回归。
- [ ] 运行伴学路由与服务测试并保存收据。
- [ ] 在隔离分支提交后端与对应测试。

---

### Task 2: 前端按 session 恢复断点 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/js/cp-api.js`、`static/js/cp-drawer.js`
- Test: `tests/test_companion_context_probe.mjs`、`tests/test_companion_context_probe.py`

**Interfaces:**
- Consumes: `fetchCompanionHistory(sessionId)`、`onSessionId(responseSessionId, historyLength)`、本次 `userText`、持久化基线与 turn generation。
- Produces: Promise reject 后最多三次顺序读取历史；仅恢复新增且末尾匹配的当前轮 assistant，更新 `companionState.messages` 与当前气泡；无匹配记录时保留原连接错误，旧流不得覆盖新流或已完成气泡。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Real Source]`: node:vm 驱动真实 `cp-drawer.js`，验证 header 回填的 session id 被用于恢复。
- [ ] `[Instinct: No Replay]`: 恢复路径不得再次调用 `streamCompanionChat`，不得重复 append assistant，不得用旧会话历史覆盖新会话。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 前端按 session 恢复断点。Mode: AFK。先扩真实源码探针，模拟响应头回填 session、delta 后 reject、首次历史未就绪随后就绪；旧实现必须红。最小实现历史匹配与气泡/消息恢复，不重发 chat，不改 SSE 解析。"

**Step Breakdown:**
- [ ] 写断流恢复、历史竞态、无匹配回退与零重复请求探针并验证 RED。
- [ ] 实现最小恢复逻辑，跑完整伴学真源码探针。
- [ ] 对恢复调用/匹配条件做变异，确认具名断言变红，还原复绿。
- [ ] 在隔离分支提交前端与探针。

---

### Task 3: 全量门禁与未合并 PR [Tier: 2-Standard] [Mode: AFK] [Role: Verifier]

**Files:**
- Modify: `docs/plans/2026-11-03-companion-sse-resume.md`
- Test: 全量 Python、全部前端探针、Go、三闸、SSE 契约、builder、ruff、diff 检查。

**Interfaces:**
- Consumes: Task 1/2 的生产改动与探针。
- Produces: 实际验证数字、偏差表与一个未合并 PR；不得直推 master。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Physical Evidence]`: 全量 pytest 串行，记录实际 passed/skipped；Go 与前端以真实退出码为准。
- [ ] `[Instinct: Scope]`: diff 只含断流恢复、测试、计划与必要簿记；不触版本面。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 全量门禁与未合并 PR。Mode: AFK。串行跑全量 pytest，再跑全部前端探针、go test、三闸、七事件契约、builder 与 ruff；填写偏差表，提交并开 PR，不合并。"

**Step Breakdown:**
- [ ] 串行执行全量门禁并记录真实数字。
- [ ] 审核 diff、七类 SSE 集合与取消语义，填偏差表。
- [ ] 推送功能分支、创建 PR、回读初始 CI 状态，不合并。

---

## [NOTE] Fog of War (Not Yet Specified)

- 无阻塞未知项；真实浏览器网络断连属于交付后的增强验证，不妨碍单元/ASGI/真源码探针先行。

## [NOTE] Out of Scope

- 断连后后台继续模型生成、SSE offset/event-id 游标、重新 POST 已中断 prompt。
- 新数据库表/列、新 SSE 事件或帧字段、Go RunLoop 改动。
- 版本号、CHANGELOG/Release、Android 真机点检、合并 PR。

## Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| 断点后的尾部续生成 | 需要后台任务生命周期、游标与取消语义重设计，不是最小修复 | 用户明确要求断连后仍完成整段回答，而非只保留断点 | 后续伴学运行时任务 |
| 真实浏览器断网验收 | 本批先以 ASGI 取消与真源码行为探针证明机制 | PR 合并后做浏览器/真机专项验收 | 验证任务 |
| 跨进程恢复未持久化尾部 | 当前只保证已进入 FastAPI 聚合器的完整帧，崩溃恢复不是本任务范围 | 需要进程崩溃后恢复流式中间态 | 后续持久化任务 |

## Deviation Table (post-execution)

| plan text | what was actually built | why |
| --- | --- | --- |
| 后端取消落库 + 前端按 session/prompt 恢复 | 同方案交付，并增加 `X-History-Length` 权威基线、持久化计数与 turn generation；探针扩展为 335 checks / 39 scenarios | 独立 maker-checker 依次证实同文旧轮误恢复、新旧流互相覆盖、乐观 user 污染基线与既有 scope 复用四类现实竞态，最小修复必须包含轮次身份与所有权 |
| GeneratorExit 断连测试 | 同时覆盖 `aclose()` 与 task `CancelledError`，断言取消继续传播且消息/proposal 各保存一次 | 取消语义不能只测正常关闭分支 |
| 全量验证 | 2731 passed / 2 skipped；35/35 前端探针；Go race 10/10 包；Ruff、mypy、机械闸与七事件契约全绿；独立复审 CLEAN PASS | 最终代码而非中间态收据 |
