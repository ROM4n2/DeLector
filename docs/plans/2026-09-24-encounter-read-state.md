# 遇见区「已读状态 + 推荐顺延」实施计划

> **Goal**: 给遇见区补上「读过没」这个一等状态——打开即记已读、列表显示 `✓ 已读`、推荐条**跳过已读**顺延到下一篇（全读完则显示完成态），使 v5.11.0 的 i+1 推荐从"一次性指路"变成可推进的阅读队列。
> **Tech Stack**: 原生 ES Modules（零构建 / 零新依赖）/ Node `node:vm` 行为探针 / Python 3.10+（FastAPI，**本计划不改服务端**）
> **Spec Reference**: `docs/specs/2026-09-24-encounter-read-state-design.md`
> **Global Constraints**:
> - **零依赖纪律**：`static/js/enc-read.js` 必须**零 import**、模块顶层不碰浏览器全局（`localStorage`/`window`/`document` 一律不出现，storage 由调用方注入）→ 保证 `node:vm` 探针能切真实源码（红线 11：跨边界契约必须行为探针）
> - **键名即契约**：`delector_encounter_read_v1`（`delector_` 前缀 = 随备份导出/还原；**MUST NOT** 改成 `enc.` 前缀，否则丢备份语义）
> - **向后兼容**：`renderTextList` / `renderI1Hint` 的新形参**必须有默认值**；不传时行为与 v5.11.0 **逐字一致**
> - **不新增 `.encounter-card` 的 grid 子项**：v5.11.0 该卡片是 4 列网格 + `.encounter-card-title + .encounter-card-meta:last-child` 补位规则；`✓ 已读` 标记 **MUST** 放进 `.encounter-card-meta` 段内（通过 `is-read` 类做视觉降权），避免破坏既有布局
> - **改动面**：只碰 `static/js/enc-read.js`(新) / `static/js/encounter.js` / `static/style.css` / `tools/wb_enc_read_probe.mjs`(新) / `tests/test_enc_read_probe.py`(新) / `tests/test_encounter_ui_probes.py`
> - **MUST NOT 触碰**：`static/german/workbench.html`（切片护栏）、`static/js/enc-i1.js`、`static/js/deck-bridge.js`、`delector/**`（本计划服务端零改动）、`CHANGELOG.md`、任何版本号
> - **展示字段一律 `esc()`**；阈值/文案常量单点定义，不散落字面量
> - **环境**：Windows / bash；Python 前 `export PYTHONIOENCODING=utf-8`；全量 pytest **分半跑**
> - **纪律**：子代理**不 git add / commit / push / 切分支**（主线程统一执行）；每 Task 收尾跑 目标测试 → 全探针零漂移 → ruff → mypy --strict

---

### Task 1: `enc-read.js` 纯函数 + 行为探针 [Role: TDD Builder]

**Files:**
- Create: `static/js/enc-read.js`
- Create: `tools/wb_enc_read_probe.mjs`
- Create: `tests/test_enc_read_probe.py`

**Interfaces:**
- Consumes: 无（`storage` 由调用方注入，形如 `{getItem(k), setItem(k,v), removeItem(k)}`）
- Produces（`static/js/enc-read.js`，纯 ESM 零 import）：
  - `READ_KEY = "delector_encounter_read_v1"`
  - `loadRead(storage) -> {v:1, read:{[id:string]: number}}`（坏 JSON / 缺键 / 非对象 → 空态，不抛）
  - `markRead(storage, id, nowMs) -> boolean`（**幂等**：已读 → `false` 且**不写盘**）
  - `isRead(state, id) -> boolean`
  - `unmarkRead(storage, id) -> boolean`（删不存在 → `false` 且不写盘）
  - `pickUnread(ranked, readState) -> object|null`（顺序扫描返回首个未读条目；非数组/空/全已读 → `null`；**不改入参**）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: `enc-read.js` 纯函数 + 行为探针。
> Goal: 实现遇见区已读状态的零依赖纯函数（含幂等写盘与"取首个未读"），并用 `node:vm` 切真实源码的探针钉死契约。
> Target Files: Create `static/js/enc-read.js`, Create `tools/wb_enc_read_probe.mjs`, Create `tests/test_enc_read_probe.py`.
> 先读参照（务必照抄切法与输出约定）：`static/js/enc-i1.js`（零依赖纪律）、`tools/wb_enc_i1_probe.mjs`（`node:vm` 切真实源码 + `--json`）、`tests/test_enc_i1_probe.py`（pytest 接线）。
> TDD Steps:
> 1. 先写探针（RED）：`tools/wb_enc_read_probe.mjs` 读 `static/js/enc-read.js` **真实源码**（去 ESM `export` 后注入 `node:vm`，照抄既有切法），注入桩 storage（可断言写入次数/最终字符串），覆盖 ≥6 场景：
>    ① 空态（无键 / 坏 JSON `"{bad"` / 非对象 `"[1,2]"`）→ `loadRead` 返回 `{v:1,read:{}}` 且不抛；
>    ② **幂等**：`markRead(s,'7',1000)` 首次 `true` 且存储含 `7`；再次 `markRead(s,'7',2000)` → **`false` 且存储字符串逐字节不变**（用写入计数或快照比较断言）；
>    ③ 多篇：标记 id 1/2/3 → `read` 含 3 键、时间戳与注入的 `nowMs` 一致；
>    ④ `isRead`：命中 true / 未命中 false / `id=null` false / 空 state false；
>    ⑤ `unmarkRead`：删已存在 → `true` 且键消失；删不存在 → `false` 且存储字节不变；
>    ⑥ `pickUnread`：全未读 → 首条；首条已读 → 第二条；跳过多条已读；全已读 → `null`；`ranked` 非数组/空 → `null`；**纯度**（调用前后入参数组与其元素深比较相等）；
>    ⑦ 写盘失败（`setItem` 抛异常 / `storage` 为 `null`）→ `markRead` 返回 `false` 且**不抛**。
>    运行 `node tools/wb_enc_read_probe.mjs` 确认 RED；输出 `--json`（含 `failures`/`total`）。
> 2. 写 `tests/test_enc_read_probe.py`（照抄 `tests/test_enc_i1_probe.py` 接线：跑 `node ... --json`，断言 `failures == 0` 且场景数 ≥ 6）→ 确认 RED。
> 3. 实现 `static/js/enc-read.js`（GREEN）：零 import、无浏览器全局、坏输入降级不抛、`pickUnread` 不改入参。`markRead` 幂等判据用 `Object.prototype.hasOwnProperty.call(read, String(id))`（**不能**用真值判断——时间戳可能为 0）。
> 4. 跑探针全绿 + pytest 全绿。
> 5. REFACTOR：JSDoc 写清每个导出函数的语义/边界/幂等性；Guard Clause 扁平化；`READ_KEY` 与内部 schema 常量单点定义。
> **变异验证（必做并回报，用 `cp` 备份还原、禁 `git checkout --`）**：① 去掉幂等早退（无条件写盘）→ 场景②必红；② `pickUnread` 改成返回首条（不管已读）→ 场景⑥必红；③ `loadRead` 坏 JSON 分支改成 `throw` → 场景①必红。
> Return: Summary with test execution evidence + 变异验证结论。"

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED）** —— ≥6 场景（含幂等/纯度/写失败不抛）
- [ ] **Step 2: 写 pytest 接线并确认 RED**
- [ ] **Step 3: 实现 `enc-read.js`（GREEN）**
- [ ] **Step 4: 探针 + pytest 全绿；执行三项变异验证**
- [ ] **Step 5: JSDoc + Guard Clause 扁平化（REFACTOR）**
- [ ] **Step 6: 收尾门禁**（目标测试 / ruff / `mypy --strict delector tools` / 全 `tools/*.mjs` 零漂移）

---

### Task 2: 前端集成（已读标记 + 推荐顺延）[Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js`（`i1CardHtml` / `renderTextList` / `renderI1Hint` / `openText` / 新增 import）
- Modify: `static/style.css`（`.enc-read-mark` / `.is-read` 降权 / 移动端断点）
- Modify: `tests/test_encounter_ui_probes.py`（追加契约断言）

**Interfaces:**
- Consumes: `static/js/enc-read.js`（`loadRead` / `markRead` / `isRead` / `pickUnread`）、既有 `encStorage()`（`encounter.js:553`）
- Produces（保持向后兼容的签名）：
  - `i1CardHtml(t, cov, readFlag)` —— `readFlag === true` 时：卡片加类 `is-read`，并在 `.encounter-card-meta` **段内最前**插入 `<span class="enc-read-mark">${esc(READ_MARK_TEXT)}</span>`
  - `renderTextList(texts, ranked = null, readState = null)` —— `readState` 缺省时**逐字**保持 v5.11.0 行为
  - `renderI1Hint(ranked, knownSet = null, readState = null)` —— 用 `pickUnread(ranked, readState)` 取代 `topPick`；`pick === null` → 完成态文案；`pick.band !== "i1"` → 降级文案；`hasCoverage === false` 仍优先引导文案
  - `openText(id)` —— 在 `renderTextDetailAnnotated(...)` **await 成功之后**调用 `markRead(encStorage(), id, Date.now())`（失败静默，不影响渲染）
  - 文案常量集中：`READ_MARK_TEXT = "✓ 已读"`、`I1_HINT_ALL_READ`（完成态）、`I1_HINT_FALLBACK`（降级模板）、`I1_HINT_NEUTRAL_PICK`（中性降级文案）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 前端集成（已读标记 + 推荐顺延）。
> Goal: 打开短篇即记已读；列表显示 `✓ 已读`；推荐条跳过已读顺延（i+1 读完 → 降级文案；全读完 → 完成态）；索引失败时行为不变但已读标记仍在。
> Target Files: Modify `static/js/encounter.js`, Modify `static/style.css`, Modify `tests/test_encounter_ui_probes.py`.
> 前置（Task 1 已合入）：`static/js/enc-read.js` 导出 `READ_KEY`/`loadRead`/`markRead`/`isRead`/`pickUnread`。
> 关键约束：① **不新增 `.encounter-card` 的 grid 子项** —— v5.11.0 该卡片是 4 列网格 + `.encounter-card-title + .encounter-card-meta:last-child` 补位；`✓ 已读` **MUST** 放进 `.encounter-card-meta` 段内，视觉降权靠 `.is-read` 类；② `renderTextList`/`renderI1Hint` 新形参**必须有默认值**，不传时行为与 v5.11.0 逐字一致；③ 展示字段一律 `esc()`；④ **MUST NOT** 改 `enc-i1.js` / `deck-bridge.js` / `workbench.html` / 任何服务端文件。
> TDD Steps:
> 1. 写失败测试（RED，追加到 `tests/test_encounter_ui_probes.py`，沿用该文件既有的'切函数体再断言'风格与 `_slice_function` 辅助）：① `encounter.js` 含 `./enc-read.js` 的 import（模块可达性，同时满足 `tests/test_frontend_module_graph.py`）；② 卡片渲染路径含 `enc-read-mark` 与 `is-read` 类名，且标记文本经 `esc(`；③ `renderTextList` 形参带默认值（正则断言 `ranked = null` 与 `readState = null`）；④ 推荐条路径含 `pickUnread(`，且完成态与降级两条文案常量存在并经 `esc(`；⑤ `openText` 函数体内含 `markRead(` 调用。跑 `python -m pytest tests/test_encounter_ui_probes.py -q` 确认 RED。
> 2. 跑测试确认失败。
> 3. 实现（GREEN）：
>    - `encounter.js`：顶部 `import { loadRead, markRead, isRead, pickUnread } from "./enc-read.js";`；`showView()` 里读一次 `readState = loadRead(encStorage())` 并传给 `renderTextList` / `renderI1Hint`（**索引失败分支也要传** `readState`，保证已读标记不丢）；`openText` 成功路径末尾 `markRead(...)` 用 `try/catch` 或依赖纯函数的静默语义。
>    - `style.css`：`.enc-read-mark`（小号、柔和、沿用既有 token，**不得新造硬编码色值**）；`.is-read .encounter-card-title { opacity: .62 }` 之类轻降权；`.is-read` 卡片可选左侧细线；移动端断点内确认触屏目标与不贴边。
> 4. 跑 `python -m pytest tests/test_encounter_ui_probes.py tests/test_frontend_module_graph.py tests/test_encounter_i1_consistency.py -q` 全绿；跑全探针零漂移。
> 5. REFACTOR：文案常量集中定义；`renderI1Hint` 的四个分支（无覆盖率 / 完成态 / 降级 / i1）写成 Guard Clause 早退；JSDoc 说明 `readState` 缺省语义。
> **变异验证（必做并回报，`cp` 备份还原）**：① 把 `pickUnread` 换回 `topPick` → 顺延/完成态断言必红；② 删掉标记的 `esc(` → 对应断言必红；③ 让 `renderTextList` 的 `readState` 形参无默认值 → 向后兼容断言必红。
> Return: Summary with test execution evidence + 变异验证结论。"

**Step Breakdown:**
- [ ] **Step 1: 写契约断言（RED）** —— import / 标记 / 默认形参 / pickUnread / 文案常量 / openText 内 markRead
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `encounter.js` + `style.css`（GREEN）**
- [ ] **Step 4: 跑 UI 契约 + 模块图 + I-1 一致性全绿；执行三项变异验证**
- [ ] **Step 5: 文案常量集中 + Guard Clause（REFACTOR）**
- [ ] **Step 6: 收尾门禁**

---

### Task 3: 收官（全量门禁 + 文档回写）[Role: TDD Builder]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（就地更新：新增里程碑条目 + 测试基线）
- Modify: `FEATURES.md`（「十七、遇见区 i+1 就近选材」补已读能力一行）

**Interfaces:**
- Consumes: 前两个 Task 的产物
- Produces: 文档事实与实测基线一致；**不改 `CHANGELOG.md`、不 bump 任何版本号**

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 收官。
> Goal: 跑全量门禁取准基线，并**就地**回写文档（不追加重复副本）。
> Target Files: Modify `WORKMEMORY/PROJECT_OVERVIEW.md`, Modify `FEATURES.md`.
> Steps:
> 1. 分半跑全量（本机 Windows 有跨文件 `DATABASE_PATH` 串扰，**必须分半**）：`export PYTHONIOENCODING=utf-8 && python -u -m pytest -q --ignore=tests/test_server.py 2>&1 | tail -6` 与 `python -u -m pytest -q tests/test_server.py 2>&1 | tail -4`。记录两段统计行，并明确区分**既有** Windows 环境失败（`test_goethe_a1_{hoeren,lesen}::... - no such table: exam_trials`）。
> 2. `python -m ruff check .` / `python -m mypy --strict delector tools` / `for f in tools/*.mjs; do node "$f" >/dev/null 2>&1 || echo FAIL $f; done` —— 回报原始输出。
> 3. `WORKMEMORY/PROJECT_OVERVIEW.md`：**就地**新增一条遇见区「已读状态 + 推荐顺延」里程碑（放在 v5.11.0 i+1 条目附近）+ 更新测试基线数字（以实测为准）。
> 4. `FEATURES.md`：在「十七、遇见区 i+1 就近选材」表内补一行已读能力（打开即记已读 / 列表 `✓ 已读` / 推荐跳过已读并顺延 / 全读完完成态 / 已读随备份迁移）。
> 5. **明示**：不改 `CHANGELOG.md`、不 bump 版本（`sw.js`/`index.html`/`build.gradle`/`README.md` 一律不动）——本计划未发版，发版五件套由主线程决策。
> Return: 两段全量统计行 + ruff/mypy/探针输出 + 文档改动落点说明。"

**Step Breakdown:**
- [ ] **Step 1: 分半跑全量**（识别既有失败）
- [ ] **Step 2: ruff / mypy --strict / 全探针**
- [ ] **Step 3: 回写 `PROJECT_OVERVIEW.md`（里程碑 + 基线）**
- [ ] **Step 4: 回写 `FEATURES.md`（遇见区小节补已读）**
- [ ] **Step 5: 明示未改 CHANGELOG / 未 bump 版本**
- [ ] **Step 6: 复核**

---

## 范围外 (Out of Scope)

- **跨端同步已读**：不走 LAN 同步（同步面只覆盖 `wb.*`）；跨端不一致列为后续候选。
- **"读完"显式按钮 / 读次数 / 停留时长 / 最近读排序**：schema 存时间戳已留位，本次不消费。
- **手动"标为未读"UI**：`unmarkRead` 纯函数备而不用。
- **服务端任何改动**：无新端点、无新表、无迁移、不动索引端点。
- **发版**：本计划只到"代码 + 测试 + 文档"；改动含 `static/` → 发版走五件套 + Android 覆盖安装（主线程决策）。

## 验证基线 (Verification Baseline)

| 阶段 | 命令 | 期望 |
|---|---|---|
| 每 Task | `python -m pytest <目标文件> -q` | 全绿 |
| 每 Task | `for f in tools/*.mjs; do node "$f" >/dev/null 2>&1 \|\| echo FAIL $f; done` | 无 FAIL（零漂移，含新探针） |
| 每 Task | `python -m ruff check .` / `python -m mypy --strict delector tools` | 0 告警 / 0 error |
| 收官 | 分半跑 pytest | 基线 **1109 passed + 1 skipped**（v5.11.0）→ 预计 **≈1125 passed + 1 skipped**；**实测 1119 passed + 1 skipped**（净增 T1/T2 用例；2 条既有 `exam_trials` 环境失败保留） |

## 回滚 (Rollback)

- 逐 Task 原子提交（主线程执行），任一可 `git revert <sha>`。
- **已读存储无需迁移/回滚**：新键 `delector_encounter_read_v1` 与既有数据完全隔离；若需清空，删除该 localStorage 键即可（不影响任何其它状态）。
- 前端回滚后 `renderTextList`/`renderI1Hint` 的默认参数保证旧调用形态继续可用。

## 关联索引

- `docs/specs/2026-09-24-encounter-read-state-design.md`
- `docs/specs/2026-09-23-encounter-i1-content-and-selection-design.md` / `docs/plans/2026-09-23-encounter-i1-content-and-selection.md`
- `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态 / 开放待办）
- `01-Rules/TESTING-PATTERNS.md`（行为探针 + 变异验证纪律）
