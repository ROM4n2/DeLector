# 登记项收口（第二轮）Implementation Plan

> **Goal**: 处理 v5.14.0 发版后仍在册的 5 项技术债——补 3 条"防漂移"守卫（localhost 受保护集合 / CI 必需运行时 / 探针 JSON 契约）、消掉 1 份双写判据、修 1 处用户可见的并发串味。
> **Tech Stack**: Python 3.11 / FastAPI + 原生 ES Modules 前端
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（本轮债的来源）；`tests/test_server.py:5837-5838`（localhost 惯例的现址注释）
> **Global Constraints**:
> - ⚠️ **Task 2 / Task 3 改 `static/` ⇒ 触发发版红线**。v5.14.0 刚发布（`c6f8d4d`），这两个任务**打包下一次发版**，不单独发。
> - **本计划不改任何端点的鉴权行为**。Task 1 是"钉住现状"，不是"加固"——哪些写端点该不该挂闸属产品决策，见 Fog。
> - 门禁：pytest 分半（半 A = 非 server，半 B = `test_server`）+ 全 `tools/*.mjs` 探针 + `ruff` + `mypy` 两道。
> - 每条新不变量 MUST 有**专属守卫 + 变异验证真红**；MUST NOT 拿"变异绿了"交差。
> - Windows/Git Bash：备份还原用 `cp`，**MUST NOT 用 `git checkout --`**；核验输出 **MUST NOT 用 `| head -N` 截断**（编排者踩过：截断导致漏看失败项）。
> - 每个 Task 一个原子 commit。

---

## 🏛️ Decisions So Far

**调研推翻的两条前提（编排者此前记录有误，以此为准）**

| 原记录 | 实际 |
|---|---|
| 「只读 GET 不挂 `_require_localhost`，共 16 处」 | 受保护路由实为 **20 个**：`main.py` 16 处函数体内调用 + `encounter.py` 3 处 + `tools.py` 1 处（`Depends` 形式）。注释里的"16"已漂移 |
| 「该惯例无守卫 ⇒ 无任何测试」 | 端点级 403/200 测试**已有多处**（`test_server.py:4363-4377`、`:4758-4773`、`test_encounter_index.py:149-155` 等）。缺的是**全量集合守卫** |

**判据口径：不按 HTTP 方法粗分类。** 反例共 4 个受保护的 GET（`/api/backup/export`、`/api/backup/download/{token}`、`/api/wb/backup/download/{token}`、`/api/wb/state/key`），全部属**备份/密钥**敏感类——是有意设计，不是"只读 GET"。故守卫 MUST 断言**精确受保护路由集合（allowlist）**，而非"GET 开放、非 GET 本机"。

**为什么 Task 1 只钉现状而不加固**：调研发现大量未鉴权写端点（`POST /api/articles/ingest`、`POST /api/cards/vocab`、`PATCH /api/cards/{t}/{id}/master`、`POST /api/cards/{t}/{id}/review`、作文/批注/训练记录）。但 `listen.py:5` 与 `syntax_hard.py:6` **明确自陈"非敏感，不挂闸"**，`PUT /api/wb/state` 用 `X-WB-Key` 而非 localhost ⇒ 当前模型**不是**"所有写都本机"。把它变成什么，是产品决策，不是实现细节。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: localhost 受保护路由集合守卫 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/localhost_guard_scan.py`（或直接内嵌在测试里，**自行选最小形态**）
- Test: `tests/test_localhost_guard.py`

**Interfaces:**
- Consumes: `delector/routes/*.py` 的 AST（路由装饰器 + 函数体内 `_require_localhost(request)` 调用 + 装饰器 `Depends(_require_localhost)`）；`_require_localhost` 定义在 `delector/core/database.py:1507-1522`
- Produces: `PROTECTED_ROUTES: frozenset[tuple[str, str]]` —— 20 条 `(METHOD, path)` 的显式 allowlist；以及扫描函数 `collect_guarded_routes() -> set[tuple[str, str]]`

**Injected Instincts:**
- [ ] `[Instinct: Pin-Not-Harden]`: 本任务**只钉现状**，MUST NOT 给任何端点加减 `_require_localhost`，MUST NOT 改业务路由。
- [ ] `[Instinct: Allowlist-Not-Heuristic]`: MUST 断言精确集合相等，MUST NOT 用"GET 不该挂闸"这类启发式（会误伤 4 个敏感 GET、带 `X-WB-Key` 的 PUT、自陈不挂闸的训练记录写入）。
- [ ] `[Instinct: Both-Forms]`: 扫描 MUST 同时覆盖两种挂载形式——函数体内直接调用与 `dependencies=[Depends(...)]`。只扫一种会漏掉 `encounter.py` 3 处与 `tools.py` 1 处。
- [ ] `[Instinct: Guard-Must-Be-Killable]`: allowlist 里删一条 / 源码里加一处闸 ⇒ 守卫 MUST 红（双方向都要变异验证）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: localhost 受保护路由集合守卫。
> Mode: AFK | Role: TDD Builder
> Goal: 把『哪些端点挂 `_require_localhost`』从一段注释变成红灯守卫，防止有人顺手加/摘本机闸而不被察觉。
> Target Files: Test `tests/test_localhost_guard.py`（扫描逻辑可内嵌或放 `tools/`）。
> Injected Instincts: Pin-Not-Harden / Allowlist-Not-Heuristic / Both-Forms / Guard-Must-Be-Killable。
> TDD Steps:
> 1. 先读 `delector/core/database.py:1507-1522`（`_require_localhost` 定义与 403 语义），再枚举全部 20 个受保护路由（`delector/routes/main.py` 16 处函数体内调用；`delector/routes/encounter.py` 3 处 + `tools.py` 1 处为 `Depends` 形式）。**你自己遍历确认，不要照抄我给的 20 条**——若实际不是 20 条，以实测为准并报告。
> 2. RED：先写一条**故意错误**的 allowlist（如只写 3 条），跑测试确认红且**列出缺失/多余的路由**。
> 3. GREEN：换成实测全集，确认绿。
> 4. 变异①：从 allowlist 删一条 ⇒ 必红；变异②：在某个未受保护的端点函数体里加一行 `_require_localhost(request)` ⇒ 必红；变异③：摘掉某个已受保护端点的闸 ⇒ 必红。每条 `cp` 还原 + `diff` 确认 IDENTICAL。
> 5. 门禁：`python -m pytest tests/test_localhost_guard.py tests/test_server.py -q`（半 B）+ `ruff check .` + `mypy --follow-imports=skip tests`。
> Return: Summary + 实测的受保护路由全集（表格）+ 三条变异原始输出 + commit hash。"

**Step Breakdown:**
- [ ] Step 1: 读定义 + 枚举实测全集（不照抄计划里的数字）
- [ ] Step 2: RED（故意错 allowlist）
- [ ] Step 3: GREEN（实测全集）
- [ ] Step 4: 变异验证三条（删一条 / 加一处 / 摘一处）
- [ ] Step 5: Physical Evidence Gate
- [ ] Step 6: Git 原子 commit

---

### Task 2: 工作台来源判据单点化 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/cards.js:242`（1 行）+ `tools/cards_workbench_no_review_probe.mjs:365-398`（E1 重写）+ `tools/cards_catalog_tag_probe.mjs:108-116, 235-238, 324-332`（注入 helper 切片 + 更新 SHA 基线）

**Interfaces:**
- Consumes: `isWorkbenchSourced(card)`（`cards.js:203-206`）、`cardStatsTag(card)`（`cards.js:240-247`）
- Produces: `cardStatsTag` 改为 `if (isWorkbenchSourced(card)) {`（`wbS` 变量 MUST 保留，第 244 行 `wbS.toFixed(1)` 仍需要它）
- Produces: E1 断言重写为"**复用**而非**雷同**"——`cardStatsTag` 源码 MUST 含 `isWorkbenchSourced(` 且 MUST NOT 含 `Number.isFinite` / `wbS > 0`

**Injected Instincts:**
- [ ] `[Instinct: Single-Source-Now]`: E1 的旧形态是"两份文本雷同"（复制 + 比对）。单点化后 MUST 改成"**只有一份、另一处复用**"的判据——否则把双写改成"单写 + 一条永远通过的比对"，等于换个姿势维持双真相源。
- [ ] `[Instinct: Keep-Behavior-Equivalence]`: E2（14 值边界带行为等价）MUST 保留并仍绿。单点化不是放开阈值。
- [ ] `[Instinct: VM-Dependency]`: `cards_catalog_tag_probe.mjs` 当前只切 `cardStatsTag` + `renderCatalogGrid` ⇒ 单点化后 `cardStatsTag` 会调未注入的 helper 而 **`ReferenceError`**。MUST 一并注入 helper 切片。
- [ ] `[Instinct: SHA-Is-Not-Invariant]`: `cards_catalog_tag_probe.mjs` 的 `BASELINE_STATS_SHA256` 钉的是"源码一字不动"，与本任务**目标直接冲突**。MUST 把它换成**行为等价**守卫（复用判据 + 边界带），MUST NOT 通过"更新哈希值"来放行。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 工作台来源判据单点化。
> Mode: AFK | Role: TDD Builder
> Goal: 消除 `cards.js` 里 `isWorkbenchSourced` 与 `cardStatsTag` 各写一份 `Number.isFinite(wbS) && wbS > 0` 的双真相源。
> Target Files: `static/js/cards.js`（1 行）、`tools/cards_workbench_no_review_probe.mjs`（E1 重写）、`tools/cards_catalog_tag_probe.mjs`（注入 helper + 换掉 SHA 守卫）。
> Injected Instincts: Single-Source-Now / Keep-Behavior-Equivalence / VM-Dependency / SHA-Is-Not-Invariant。
> TDD Steps:
> 1. 读 `cards.js:203-206` 与 `:240-247`、探针 E1（`:365-398`）/ E2（`:400-413`）/ F1（`:426-436`）、catalog 探针的 SHA 守卫（`:235-238, 324-332`）与切片（`:108-116`）。
> 2. RED：先只重写 E1 为『cardStatsTag 调 isWorkbenchSourced 且不含阈值』，不改 cards.js ⇒ 必红（此刻 cardStatsTag 还在自己判）。贴原始红输出。
> 3. GREEN：改 `cards.js:242` 为 `if (isWorkbenchSourced(card)) {`，给 catalog 探针注入 helper 切片，把 SHA 守卫换成行为等价守卫 ⇒ 全绿。
> 4. 变异①：改回双写（复制一份阈值进 cardStatsTag）⇒ 新 E1 必红；变异②：只把 `isWorkbenchSourced` 的阈值改掉 ⇒ E2 必红（证明行为等价仍被钉住）；变异③：删掉 catalog 探针的 helper 注入 ⇒ 必红（ReferenceError 也要被切片护栏抓住，不能只是 silent pass）。
> 5. 门禁：全 `tools/*.mjs` + `python -m pytest tests/test_frontend_module_graph.py tests/test_cards_wb_source_probe.py tests/test_cards_catalog_tag_probe.py tests/test_cards_workbench_no_review_probe.py -q` + `ruff`。
> 6. **MUST NOT 改 `static/style.css`**（H2/H3 守卫钉着 `.deck-workbench-link`）。
> Return: Summary + RED/GREEN 原始输出 + 三条变异 + commit hash + `--stat`。"

**Step Breakdown:**
- [ ] Step 1: 读代码 + 三个探针的相关段
- [ ] Step 2: RED（只改 E1 不改实现）
- [ ] Step 3: GREEN（改 cards.js + 两个探针）
- [ ] Step 4: 变异验证三条
- [ ] Step 5: 门禁（全探针 + 指定 pytest + ruff）
- [ ] Step 6: Git 原子 commit

---

### Task 3: 降级标志与本次调用绑定 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js:154-161`（`_deckDegraded` / `_knownDegraded` / `degradedSources`）、`:163-193`（`resolveDeck`）、`:638-652`（快照点）
- Test: 新建 `tools/enc_degraded_concurrency_probe.mjs`；可能需调 `tools/enc_coverage_degraded_probe.mjs`

**Interfaces:**
- Consumes: `degradedSources()`、`resolveDeck()`、`fetchKnownLemmas()`、`renderCoverage(stats, degraded)`；快照点在 `encounter.js:646`
- Produces: 降级状态与**本次异步调用**绑定（而非模块级全局），使"A 的失败"不会污染"B 的成功"

**Injected Instincts:**
- [ ] `[Instinct: Do-Not-Touch-Count-Stub]`: `tools/enc_known_same_source_probe.mjs:239-249` 把 `resolveDeck` 换成**计数包装器**，断言 showView 后 =1、详情后累计 =2（`:388-402`），且声明 MUST 仍匹配 `async function resolveDeck(`（`:433-435`）。**MUST NOT** 增加 `resolveDeck` 调用次数、**MUST NOT** 改其 resolved 值形状（下游 `buildKnownSet(deck)` 依赖）、**MUST NOT** 改成非 `async function`。违反任一即红。
- [ ] `[Instinct: Reproduce-Before-Fix]`: MUST 先写一个**能复现串味**的场景（两个 `resolveDeck` 以相反结果交错结束），确认它在修复前红、修复后绿。没复现就改，等于盲修。
- [ ] `[Instinct: Human-Readable-Degraded]`: 降级文案 MUST 仍是 `⚠ … · 数据不完整` + `title` 原因，MUST NOT 出现技术字段名（既有 `enc_coverage_degraded_probe.mjs` 钉着）。
- [ ] `[Instinct: Async-Promise-Trap]`: `async` 函数返回的是**外层 Promise**，给内层 Promise 挂属性不会自动转移。MUST NOT 用"给内层 Promise 挂属性"的方案。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 把降级标志从模块级全局改为与本次调用绑定。
> Mode: AFK | Role: TDD Builder
> Goal: 消掉一个可实际触发的串味窗口——`showView` 的 `resolveDeck()` 与详情的 `resolveDeck()` 并发、且以相反结果交错结束时，详情会拿到**自己的成功 deck** 却显示『deck 降级』。
> Target Files: `static/js/encounter.js`；新建 `tools/enc_degraded_concurrency_probe.mjs`。
> Injected Instincts: Do-Not-Touch-Count-Stub / Reproduce-Before-Fix / Human-Readable-Degraded / Async-Promise-Trap。
> TDD Steps:
> 1. 读 `encounter.js:154-161`（三个符号）、`:163-193`（resolveDeck 写标志）、`:296-320`（fetchKnownLemmas 写标志）、`:638-652`（快照）；读 `tools/enc_known_same_source_probe.mjs:239-249, 388-402, 433-435` 的计数桩约束。
> 2. RED：写并发串味场景（列表的 resolveDeck 失败 **晚于** 详情的 resolveDeck 成功返回，但在详情快照**之前**写入标志）⇒ 断言详情拿到成功 deck 却标了降级。**先确认它真红**。
> 3. GREEN：改状态绑定方式，使详情只读自己那次调用的降级结果。MUST 满足 Do-Not-Touch-Count-Stub 的三条禁止。
> 4. 变异①：改回模块级全局 ⇒ 并发场景必红；变异②：让详情读不到任何降级状态（恒 false）⇒ 既有 `enc_coverage_degraded_probe.mjs` 的 B2/B3 必红（证明没把功能改没）。
> 5. 门禁：全 `tools/*.mjs` + encounter 相关 pytest + `ruff`。**MUST 跑 `node tools/enc_known_same_source_probe.mjs` 确认同源契约未破**（它最容易被本任务撞坏）。
> 6. 若你判断在不违反 Do-Not-Touch-Count-Stub 的前提下无解，**停下报告**，MUST NOT 靠放宽该探针的断言来通过。
> Return: Summary + 复现场景的 RED/GREEN 原始输出 + 两条变异 + 同源探针前后两次输出 + commit hash。"

**Step Breakdown:**
- [ ] Step 1: 读三个符号 + 计数桩约束
- [ ] Step 2: RED（复现串味）
- [ ] Step 3: GREEN（绑定本次调用）
- [ ] Step 4: 变异两条 + 同源探针前后对比
- [ ] Step 5: 门禁
- [ ] Step 6: Git 原子 commit

---

### Task 4: CI 必需运行时缺失 MUST 红（不可静默 skip） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `conftest.py`（根目录，当前全文仅 ~28 行，只做 `sys.path` 与测试库环境）
- Test: `tests/test_ci_hardening.py`

**Interfaces:**
- Consumes: `shutil.which("node")`；CI 判据用环境变量（GitHub Actions 恒有 `CI=true`）
- Produces: `conftest.py` 里的 session 级检查——CI 环境且 `node` 不在 PATH ⇒ 直接 fail（而非让 29 处 `pytest.skip` 静默吞掉）

**Injected Instincts:**
- [ ] `[Instinct: Narrow-Not-Global]`: MUST NOT 做"CI 下零 skip"的全局禁令——会误伤合理的平台/可选依赖 skip（Windows 专用用例、本地构建产物缺失、env 覆盖）。只把**CI 必需**的运行时（本轮：node）升级为 fail。
- [ ] `[Instinct: Local-Stays-Skip]`: 非 CI 环境 MUST 保持 skip（本地没 node 不该红）。
- [ ] `[Instinct: Guard-The-Guard]`: 加一条静态守卫钉住 `conftest.py` 的这个检查存在且判据是 `CI` 环境变量（防止将来被删或改成恒真）。
- [ ] `[Instinct: One-Place]`: MUST NOT 逐个改那 29 处 `shutil.which`——在根 `conftest.py` 一处解决。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: CI 下 node 缺失必须红，不许静默 skip。
> Mode: AFK | Role: TDD Builder
> Goal: `tests/` 下有 29 处 `if not shutil.which('node'): pytest.skip(...)`。CI 上若 node 缺失 ⇒ 测试全绿而 27 个 .mjs 探针根本没跑（**比红更坏：回归无声溜过**）。C 组已给 `ci.yml` 加了 `setup-node@v4` 并用 YAML 守卫钉住，但 pytest 侧仍会静默 skip。
> Target Files: `conftest.py`（根）+ `tests/test_ci_hardening.py`。
> Injected Instincts: Narrow-Not-Global / Local-Stays-Skip / Guard-The-Guard / One-Place。
> TDD Steps:
> 1. 读根 `conftest.py` 全文（约 28 行），确认它现在只做 sys.path 与测试库环境。
> 2. RED：先写静态守卫（断言 conftest.py 含该 session 检查且判据是 `CI` 环境变量）⇒ 此时 conftest 还没改，必红。
> 3. GREEN：在 conftest.py 加 session 级检查（建议 `pytest_sessionstart` 或 `pytest_collection_modifyitems`，你选并说明理由）。
> 4. 变异①：临时把 `CI` 判据改成恒真 ⇒ 本地（无 CI 变量）会红 ⇒ 证明 Local-Stays-Skip 被钉住；变异②：删掉检查 ⇒ 静态守卫必红；变异③：临时造假让 `shutil.which('node')` 返回 None 且 `CI=true` ⇒ session 检查必红。每条 `cp` 还原。
> 5. 门禁：`python -m pytest tests/test_ci_hardening.py -q` + 全探针 + **至少跑一次正常 pytest 确认没把整场测试搞红**（MUST 验证：有 node 的本地环境不应被这个检查影响）。
> Return: Summary + RED/GREEN 原始输出 + 三条变异 + '本地不误伤'的验证证据 + commit hash。"

**Step Breakdown:**
- [ ] Step 1: 读根 conftest.py
- [ ] Step 2: RED（静态守卫）
- [ ] Step 3: GREEN（session 检查）
- [ ] Step 4: 变异三条 + 本地不误伤验证
- [ ] Step 5: Physical Evidence Gate
- [ ] Step 6: Git 原子 commit

---

### Task 5: 探针 `--json` 契约冻结（新增即标准，存量登记过渡） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Test: 新建 `tests/test_probe_json_contract.py`
- Modify: `tests/probe_runner.py`（仅注释/说明，MUST NOT 改可执行逻辑）

**Interfaces:**
- Consumes: `tools/*_probe.mjs` 的 `--json` 输出（**实跑**判定，不读源码猜）
- Produces: `LEGACY_NONSTANDARD: frozenset[str]` —— 23 个当前非标准契约探针的**显式过渡清单**（含每条的登记理由）；守卫断言"任何不在过渡清单里的探针 MUST 输出 `{failures, total, cases}`"

**Injected Instincts:**
- [ ] `[Instinct: Freeze-Not-Migrate]`: 本任务 **MUST NOT** 改任何 `tools/*.mjs` 的输出结构。严格迁移会波及 23 个 probe + 约 13 个 wrapper，且把丰富的结构化样例压成 `{name, ok}` 会**降低诊断能力**——那是净损失。本轮只做"冻结"。
- [ ] `[Instinct: Empirical-Not-Source]`: 契约分类 **MUST 实跑** `node <probe> --json` 判定，MUST NOT 读源码猜（调研的 27 项分类是读源码得出的，你 MUST 复核）。注意 `enc_coverage_degraded_probe` / `enc_known_lemmas_dedupe_probe` 的**早退路径**输出 `{ok, error}`，成功路径才是三键——按成功路径判定，但要在注释里记这条。
- [ ] `[Instinct: Shrinking-Allowlist]`: 过渡清单 MUST 是**只减不增**（加一条守卫要求清单长度 MUST NOT 增长），否则"登记"会变成永久豁免。
- [ ] `[Instinct: Register-One]`: 若你顺手把某个探针统一到标准契约，MUST 单独成为一个 commit 并**同时**改其 wrapper，MUST NOT 混在本 commit 里。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 探针 --json 契约冻结。
> Mode: AFK | Role: TDD Builder
> Goal: `tools/` 27 个探针的 --json 输出有 5 种形态（精确三键 4 个、超集 3 个、`fail` 而非 `failures` 4 个、扁平业务键 14 个、其它 2 个）。全面统一要动 23 个 probe + 约 13 个 wrapper，风险高于收益；本轮改为**冻结**：存量登记进显式过渡清单，新增即标准。
> Target Files: 新建 `tests/test_probe_json_contract.py`；`tests/probe_runner.py` 只改注释。
> Injected Instincts: Freeze-Not-Migrate / Empirical-Not-Source / Shrinking-Allowlist / Register-One。
> TDD Steps:
> 1. **逐个实跑** `node tools/X.mjs --json` 记录 27 个探针的实际顶层键（MUST NOT 读源码猜，也 MUST NOT 照抄调研给的分类）。
> 2. RED：先写守卫但过渡清单留空 ⇒ 23 个非标准探针全红，贴原始输出（证明判定真在工作）。
> 3. GREEN：把这 23 个登记进 `LEGACY_NONSTANDARD` 并写明每条理由 ⇒ 绿。
> 4. 变异①：从清单删一条 ⇒ 必红；变异②：往清单里加一个**不存在的**探针名 ⇒ 必红（防清单虚增，配合 Shrinking-Allowlist）；变异③：临时把某个标准探针的 --json 改成非标准 ⇒ 必红。
> 5. 门禁：全 `tools/*.mjs` + `python -m pytest tests/test_probe_json_contract.py tests/test_probe_wiring_guard.py tests/test_probe_runner*.py -q` + `ruff` + `mypy --follow-imports=skip tests`。
> 6. **MUST NOT 改任何 `tools/*.mjs`**（违反即越界）。
> Return: Summary + 27 个探针的**实测**顶层键表 + RED/GREEN 原始输出 + 三条变异 + commit hash。"

**Step Breakdown:**
- [ ] Step 1: 逐个实跑记录实测契约
- [ ] Step 2: RED（清单留空）
- [ ] Step 3: GREEN（登记 23 条）
- [ ] Step 4: 变异三条
- [ ] Step 5: 门禁
- [ ] Step 6: Git 原子 commit

---

## 🌫️ Fog of War

- **[RESOLVED 2026-10-05] LAN 写权限：用户裁决「内网可信」⇒ 不加固。** 暴露面 28 个（🔴6 / 🟡11 / 🟢11），但**不可逆毁数据能力全在闸内**（所有 DELETE、备份导出与清库式还原、`POST /api/settings` 改写 API Key 与网关、`wb/state/key`）；覆盖最大的 `PUT /wb/state` 由 128-bit `X-WB-Key` 保护且该 key **无法经 HTTP 从 LAN 取得**。**关键结论：加固不会断手机同步**（手机端只写 3 个 `X-WB-Key` 端点，A1–A23 无一被手机端调用）。已知代价（用户知悉）：LAN 第二台设备从"可读可写"降级为"可读但保存按钮 403"。`GET /api/settings` 未挂闸会泄露模型网关地址与模型名（key 是掩码），单独知悉未处置。**本条不再是 Fog**；PR #103 的守卫现为"钉住**已决策**的现状"。如日后要正式化安全 posture，再写 `docs/adr/`。
- **[RESOLVED 2026-10-06] `GET /api/articles/{id}` 的惰性写 —— 追根因发现真 bug，已修（#108）。** 原登记为"按 HTTP 方法判只读不可靠"的前提条件（已因 Task 1 改用精确 allowlist 而失效）。追进去发现：写入端 `processor.py:421/:480` 两条路径都返回 `"3.5.0"`，而判据端 `main.py:278` 写死 `!= "3.4.0"` ⇒ **判据恒真** ⇒ 「惰性迁移」退化成「**每次 GET 都重跑完整 spaCy 并 UPDATE articles**」。列表路径早在 `:245` 就优化掉这个 N+1，但单篇 GET 一直全量重算——**惰性迁移从未真正生效**。修法＝导出 `PROCESSED_JSON_VERSION` 单一真相源（两条返回路径 + 判据共用），惰性迁移语义完整保留，向后兼容已核。守卫：AST 白名单（带写 GET 端点集合 == `{GET /api/articles/{id}}`，即 Fog 2 的原始价值）+ 行为测试（**数真实 SQL 首词**而非断言版本字符串——字符串对、判据错正是该 bug 潜伏的原因）。**教训：把 Fog 标记为"已规避"而不追根因，会把真实缺陷一起留下。**
- **[CLOSED 2026-10-06] Fog 3：目标已由 Task B 达成；C-F 形式统一经用户裁决**不做**（#110 已合）。** 原文论证是"统一成 `Depends` 后守卫可从 AST 降到 `route.dependant.dependencies`（更可靠）"。**实测否定了这个前提**：运行时 `dependant` 枚举**只找出 4 条**（全是 `Depends` 形式），**看不到函数体内调用的 16 条** ⇒ 运行时方案只在完成 16 处统一后才可行，而那时守卫也须一并改；且运行时方案**本身也不更好**（它天然看不到函数体调用）。另一实测：模块级 router 变量共 **14 个**（12×`router` + `hoeren_router` + `lesen_router`），**当前 20 条 allowlist 是正确的**（那两个 router 上确实没闸），漏检是**将来的**。
  - **已交付（Task B，零行为变化，只改 `tests/`）**：关掉三个实测确认的漏检洞——只认字面 `router` 变量名、prefix 只从单个 router 取（一模块双 router 时**键失真且恰好蒙对**）、闸调用名字面量（`import ... as` 别名漏检）。三洞均以临时改 `delector/` 完成"改前绿/改后红"取证，`delector/` 零残留。allowlist 20 条逐字未动。洞 3 明确未覆盖 `functools.partial` / 包装函数间接调用 / `include_router` 跨模块前缀（需跨模块数据流分析，性价比低，不假装做了）。
  - **C-F 形式统一：用户裁决不做**。理由：①Fog 3 的**目标**是"守卫更可靠"，Task B 已零风险达成同等可靠性；②唯一真行为变化 **LAN + 非法参数 422 → 403**（实测确认，语义收紧但是用户可见的）；③16 处改动有误挂风险——`POST /api/wb/state` **刻意不挂闸**（用 `X-WB-Key`，`test_server.py:4798-4820` 会红）是最易误伤的具体点；④`request: Request` 形参删除有 lint 盲区（`pyproject.toml` 无 `[tool.ruff]`，默认规则集不报未使用形参 ⇒ 漏删不会被门禁拦住）。**保留现状**：20 条 allowlist 继续由加固后的 AST 守卫守护，两种挂载形式都被覆盖。
- **[RESOLVED 2026-10-06] Fog 4：两条前提均被推翻，结论是「负向守卫」（#109 已合）。** ①**`shutil.which("rm")` 全仓 0 次**——本计划原文与上一条 work.log 记的"第 8 处同类漏网"**是虚构的**，`tests/db_cleanup.py` 用跨平台 `os.remove`（教训：不要把未核实的记忆当事实写进文档）。②**`bash` 不属"CI 必需"**——CI 是 ubuntu 且 GitHub Actions `run:` 本身以 bash 为默认 shell；`test_server.py:2591` 的 skip 是 `_find_bash()` **五套策略的最后一招**，语义为"本机找不到任何可用 bash"，Windows 无 Git-Bash 时跳过是**正确**行为。⇒ 扩进清单 **0 项**、未改 `conftest.py`。交付物是**否定式守卫**：`rm` 与 `bash` 均显式标注"平台相关、非 CI 必需"并断言不在清单，防将来有人误升级为 fail。

---

## 🚫 Out of Scope

- **不改任何端点的鉴权行为**（不给端点加减 `_require_localhost`，不改 `X-WB-Key` 路径）
- 不改 `static/style.css`
- 不做 `.mjs` 契约的**全面统一**（只冻结，见 Task 5 的 Freeze-Not-Migrate）
- 不做后端 `degraded` 字段（前端启发式判定维持现状）
- 不动 `resolveDeck` 的复用阶梯与列表/详情同源契约（Task 3 的硬约束，非可选）
- 不做 Go / Android 侧改动
- 不在本轮发版（Task 2/3 的 `static/` 改动打包下一次发版）
