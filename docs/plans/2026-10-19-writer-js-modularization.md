# writer.js 模块化实施计划：UI 渲染 ⇄ 纯函数 / 持久化 分层解耦

> **Goal**: 把 `static/js/writer.js`（1,657 行）里混杂的三种关注点按层切开——**纯格式化/领域文案层**（无 DOM / 无网络 / 无可变状态）、**持久化访问层**（只发请求、不碰 DOM）、**视图与编排层**（writer.js 自身）——并用新增的**前端分层机械闸** `tools/check_frontend_layers.py` 把新边界钉成可被变异推翻的硬契约。
> **Tech Stack**: 原生 ES Modules（零构建）/ Python 3.11 / pytest / Node 18+（`.mjs` 探针）
> **Spec Reference**:
> - `docs/plans/2026-10-18-index-html-split-and-modularization.md` §Fog of War Unknown 1（本计划的直接上游：index.html 拆分落地后，JS 业务逻辑下沉的下一步）
> - `docs/plans/2026-10-18-c7-workbench-html-split.md`（**迁移模板的来源**：探针读取层 `tests/wb_source.py`、多文件 seam、变异自证纪律）
> - `docs/agents/architecture.md`（前端拓扑 / 跨端契约）；`delector/routes/writing.py`（写作域 API 面）
> - `01-Rules/LAYERED-ARCHITECTURE.md`（后端 Layer 0~5 层序；本计划为其**前端同构**）
> **Global Constraints**:
> - **入口路径不可迁移（MUST）**：`static/js/writer.js` 保留原路径与**全部既有具名导出**。它被 `static/js/main.js` 的 `from './writer.js'` 具名导入集合钉死（`tests/test_frontend_module_graph.py:341-363`），且经 `main.js` 的 `Object.assign(window, {...})` 暴露给 HTML 的 `onclick`。抽层 MUST 只改**内部实现来源**，对外导出面逐字不变。
> - **零构建 / 零新依赖（MUST）**：不引入 webpack / vite / rollup / esbuild / npm 包。多文件原生 ES Module。
> - **探针判别力不可降级（MUST）**：迁移任何探针 MUST 走 `tests/wb_source.py::read_source()` 的**多文件拼接**读法，禁止退化成 `assert "x" in src` 这类存在性断言（本仓红线「死测」形态）。迁移后 MUST 补一条**变异自证**证明断言仍能变红。
> - **零静默失败（MUST）**：抽取只搬实现，不得顺手吞掉 `catch`、不得把失败路径改成 `console.log` 了事。`writer.js` 现有的 `notify(...)`（用户可见）与 `console.error(...)`（服务端可查）双轨 MUST 原样保留。
> - **文件契约**：全文件 UTF-8 **CRLF**（0 lone LF）；`ruff check .` 零告警；`mypy --strict delector tools` 与 `mypy --follow-imports=skip tests` 零错误。
> - **用例数守恒**：本工作流的拆分动作**不新增业务断言**；只允许因新增机械闸而产生的 `tests/test_frontend_layers.py` 用例。
> - **并行占面**：本工作流**独占** `static/js/writer.js`、`static/js/wr-format.js`（新）、`static/js/wr-api.js`（新）、`tools/check_frontend_layers.py`（新）、`tests/test_frontend_layers.py`（新）、`tests/test_server_ai_polish.py`（仅探针读取口一行）。MUST NOT 触碰 `static/index.html`、`static/views/**`、`static/modals/**`、`static/layout/**`、`tools/build_index_html.py`、`tools/check_index_html_sync.py`（另一分支 `refactor/index-html-split` 的占面）。
> **Branch**: `refactor/writer-js-modularization` —— 自 `master` 切出（经独立 worktree 隔离，避免与并行分支共用工作目录）。全套门禁全绿后提 PR 合入，严禁直推 `master`。

---

## 🏛️ Decisions So Far

- **本仓既有前端「分层」不是层序而是惯例**：`static/js/` 现有 30 个模块只有「按功能命名」的约定（`wb-*` = 背词工作台、`enc-*` = 情景、`a1-*` = A1 考级），**没有任何机械闸**约束「纯函数层不许碰 DOM」。后端有 `tools/check_layer_invariants.py`，前端没有对应物。本计划首次把前端分层从惯例升级为**可复验契约**。
- **切分依据 = 关注点，不是行数**：`writer.js` 内三类关注点混杂在同一个模块作用域里——`selectedSpanRef` / `currentEssayId` / `polishState` 这些可变状态被纯字符串构造函数与 DOM 渲染函数**同时**读写，导致纯函数无法单测、持久化调用散落在 14 个事件处理器中。按「能否在不碰 DOM、不碰网络的前提下独立存在」切成三块。
- **`wr-api.js` 只抽「请求/响应」形态，不抽流式 SSE**：`readPolishStream`（`writer.js:1400`）是**带进度回调的流式编排**，其回调直接改 AI 按钮文案，属视图编排面；且 `tests/test_server_ai_polish.py:1034-1040` 以 `export async function aiPolishEssay` → `export async function applyPolishChanges` 之间的切片做契约断言，把它搬走会让该探针失去锚点。故 SSE 留在视图层，只抽其**非流式降级路径**所用的 `api()` 调用。
- **探针读取层复用而非新建**：`tests/wb_source.py`（C7 建）的 `read_source(*paths)` 本就按「实参顺序 = 拼接顺序」工作，对 writer.js 同样适用。**不新建 `wr_source.py`**（YAGNI）。
- **门禁先例**：`tools/check_layer_invariants.py`（后端，C5 Task 4）与 `tools/check_mock_drift.py`（C9）均为「改动落地后再立闸 + 变异自证证明其能变红」——本计划沿用该先例：Task 4 立闸，Task 5 全景复核。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 探针多文件读取口 + `POLISH_REASON_COPY` 探针改造 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(前置中的前置：Task 2 会移动 `POLISH_REASON_COPY`，必须先让读它的探针学会跨文件读)*

**Files（实测收敛后的实际改动面）:**
- Modify: `tests/test_server_ai_polish.py:26,505-517`（`test_writer_js_surfaces_degraded_hint_and_advisories_without_toast` 的 `render_block` 取体）
- Modify: `tests/test_server_ai_polish.py:1026`（`test_frontend_polish_reason_copy_covers_every_reason_code`）
- Modify: `tests/test_server_ai_polish.py:1038-1041`（`test_frontend_polish_progress_takes_max_turns_from_server`）
- Modify: `tests/test_server_android_fallback.py:6,615-621`（`test_frontend_ai_error_paths_reuse_api_and_show_alert`）
- Test: `tests/test_server_ai_polish.py` · `tests/test_server_android_fallback.py`（基线 150 用例，跑 4 文件 + `test_writer_mobile.py` 组合）
- **实测收敛说明（计划外的事实，照实登记）**：原计划列出的 `tests/test_audit_hardening.py:415,496` 经实测**不受 Task 2/3 搬迁影响**（那两处锚的 `alert('请输入德语作文内容后再保存。')` 与 `_analyzeToken` 都留在 `writer.js` 的 DOM 层），故**未改**——不制造无收益的改动面。真正受影响的只有上列 4 个站点。
- **两处顺带修强（变异实测暴露的既有弱点，非本次搬迁引入）**：
  - `assert "max_turns" in body` 曾被函数体内**注释**里那句「轮次分母取自服务端事件的 max_turns」满足 —— 变异实测（把 `ev.max_turns || ev.round` 换成字面量 `3`）当时**不会变红**。收紧为 `assert "ev.max_turns" in body`。
  - `assert "alert" in polish_fn` 同理会被含 "alert" 的注释满足。收紧为 `assert "alert(" in polish_fn`。

**Interfaces:**
- Consumes: `tests/wb_source.py::read_source(*rel_paths) -> str`（多路径按实参顺序用 `\n` 拼接）
- Produces: 无新生产符号。**契约变化仅一处**：上述探针的源码来源从「写死单文件 `open(...)`」变为「`read_source("static/js/writer.js")`」——当前实参只有一个，**读出的字节内容与旧写法逐一相等**。

**Injected Instincts:**
- [x] `[Instinct: Zero-Drift]`: 改写前后 MUST 对同一个 `POLISH_REASON_COPY` 探针做**键集合逐字比对**，证明迁移没有顺带改变判据（否则「迁移」会变成「偷偷放宽」）。
- [x] `[Instinct: Fail-Loud]`: `read_source` 找不到文件即抛（由 `wb_source._resolve` 保证）；MUST NOT 用 `try/except` 兜成空串。
- [x] `[Instinct: Strengthen-Not-Weaken]`: 迁移后补一条变异自证——把 `POLISH_REASON_COPY` 删掉一个键，`read_source` 版本 MUST 与旧写法**同样**变红。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 探针多文件读取口 + POLISH_REASON_COPY 探针改造.
> Mode: AFK | Role: TDD Builder
> Goal: 让读 `static/js/writer.js` 的 4 处探针改走 `tests/wb_source.py::read_source()`，为 Task 2/3 的跨文件锚定预留读取口；对当前单文件布局行为**逐字不变**。
> Steps:
> 1. 先跑 `python3 -m pytest tests/test_server_ai_polish.py tests/test_audit_hardening.py tests/test_server_android_fallback.py -q` 记录全绿基线与用例数。
> 2. 把 4 处 `open(os.path.join(ROOT, \"static\", \"js\", \"writer.js\"), encoding=\"utf-8\").read()` / `Path(...).read_text(...)` 改为 `read_source(\"static/js/writer.js\")`。
> 3. 零漂移证明：对 `POLISH_REASON_COPY` 断言，用新旧两种读法各跑一次，键集合必须逐字相同。
> 4. 变异自证：删掉 `POLISH_REASON_COPY` 里任一键 ⇒ 新写法必须变红；复原。
> 5. 跑 `ruff check tests/` 与 `mypy --follow-imports=skip tests`。
> Return: 摘要 + MANDATORY 物理执行凭据（命令 + 退出码 + 用例计数 + 零漂移比对输出）。"

**Step Breakdown:**
- [x] **Step 1**: 记录基线 —— 5 文件定向套件 `150 passed in 29.77s`；全量 `2367 tests collected`
- [x] **Step 2**: 4 处读法改为 `read_source()` / `decl_body()`（GREEN）
- [x] **Step 3**: 零漂移比对 —— 旧读法 vs `read_source` 均 `len=55642`、sha256 前 16 位同为 `220c1af085b3417b`、`old == new` 为 True
- [x] **Step 4**: 变异自证 4/4 —— 删 `POLISH_REASON_COPY` 键 / 去掉 `ev.max_turns` 读取 / 把 `judge_advisories` 移出 `renderPolishReview` / 去掉 `alert(` 调用，注入后 exit=1、复原后 exit=0，`writer.js` 字节复原一致
- [x] **Step 5**: 门禁 —— `ruff check .` All checks passed；`mypy --follow-imports=skip tests` 153 文件 0 错；`mypy --strict delector tools` 115 文件 0 错；CRLF 0 lone LF（中途被 `write_text(newline='')` 破坏 1045/681 行，已 `--fix` 复原并人工核 diff 仅含预期行）
- [x] **Step 6**: Physical Evidence Gate（退出码 + 用例计数 + diff stat `2 files changed, 18 insertions(+), 12 deletions(-)`）
- [x] **Step 7**: 原子提交（`refactor(wr): route writer.js probes through the multi-file source seam`）

---

### Task 2: 抽出 `static/js/wr-format.js`（纯格式化 / 领域文案层）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/js/wr-format.js`
- Modify: `static/js/writer.js:54-86,1030-1087,1249-1271`（删除被搬走的定义，改为 import）
- Test: `tests/test_frontend_layers.py`（Task 4 立；本任务先以 `tests/test_frontend_module_graph.py` 的自治图校验为准）

**Interfaces:**
- Consumes: `core.js::esc(str) -> str`（纯函数：5 条 `String.replace`，无 DOM）
- Produces（`wr-format.js` 导出，签名与 `writer.js` 现状逐字相同）:
  ```js
  export const ERROR_TYPE_LABELS: Record<string, string>;   // 4 键
  export function getErrorTypeLabel(type: string): string;
  export const WRITER_TABS: string[];                        // ['diag','problems','versions']
  export const POLISH_REASON_COPY: Record<string, string>;   // 覆盖 polish_loop.REASONS + no_api_key
  export function polishReasonText(reason: string): string;
  export function renderWordDiff(oldSent: string, newSent: string): { oldHtml: string, newHtml: string };
  ```
- **层级硬契约（本模块 MUST）**：零 `document` / `window` / `navigator` / `localStorage` / `getElementById` / `querySelector` / `innerHTML` / `addEventListener`；零 `fetch(` / `api(` / `XMLHttpRequest`；零 `notify(` / `alert(` / `confirm(`；**零顶层 `let`**（无可变模块状态）。唯一允许的 import 是 `./core.js` 的 `esc`。
- **`writer.js` 侧契约**：MUST 从 `./wr-format.js` 具名 import 上述符号，且 MUST NOT 保留同名本地定义（防「抽了但留副本」的假解耦）。

**Injected Instincts:**
- [x] `[Instinct: Byte-Equality-Or-Explain]`: 搬走的 6 个符号，其**源码文本** MUST 逐字节等于原处内容（除缩进归一）；任何语义改写都要在提交信息里写明理由。
- [x] `[Instinct: Export-Surface-Frozen]`: `writer.js` 的具名导出集合 MUST 逐字不变（`main.js` 的导入集合依赖它）；被搬走的符号若有 `export` 前缀，MUST 由 `writer.js` 以 `export { ... } from './wr-format.js'` 或 import-后-再输出 的方式继续对外提供。检查手段：`git show master:static/js/writer.js | grep -oP '^export (function|const|let|async function) \K\w+' | sort` 与改动后 diff 为空。
- [x] `[Instinct: Zero-State]`: `wr-format.js` 内 MUST NOT 出现 `let`；若某函数确实需要可变状态，说明它不属于纯层，必须留在 `writer.js`。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 抽出 static/js/wr-format.js.
> Mode: AFK | Role: TDD Builder
> Goal: 把 writer.js 里的 6 个纯符号（ERROR_TYPE_LABELS / getErrorTypeLabel / WRITER_TABS / POLISH_REASON_COPY / polishReasonText / renderWordDiff）搬到新模块 static/js/wr-format.js，writer.js 改为 import；对外导出面逐字不变。
> Steps:
> 1. 记录基线：`python3 -m pytest tests/test_server_ai_polish.py tests/test_frontend_module_graph.py tests/test_writer_mobile.py tests/test_audit_hardening.py -q`。
> 2. 建 `static/js/wr-format.js`，源码文本逐字节照搬（只归一缩进）。
> 3. `writer.js` 删除原定义，加 `import { ... } from './wr-format.js';`。
> 4. 导出面冻结核验：对 master 与改动后的 `writer.js` 具名导出集合做 diff，必须为空。
> 5. 把 Task 1 建立的 `read_source()` 探针实参扩为 `read_source(\"static/js/wr-format.js\", \"static/js/writer.js\")`，并跑变异自证（删键 ⇒ 红）。
> 6. 跑 `ruff check .` / `mypy --strict delector tools` / 定向 pytest。
> Return: 摘要 + MANDATORY 物理凭据（退出码 + 用例数 + 导出面 diff 为空 + 源码逐字节比对输出）。"

**Step Breakdown:**
- [x] **Step 1**: 基线 —— 5 文件定向套件 `150 passed in 30.31s`；全量 `2367 tests collected`
- [x] **Step 2**: 建 `wr-format.js` —— 由确定性切片脚本产出（对 4 个行区间各做内容断言，切歪即抛），**4/4 块逐字节等价**（只允许两类已枚举差异：5 处 `export ` 前缀 + 1 处失效文档指针 `tests/test_server.py` → `tests/test_server_ai_polish.py`）
- [x] **Step 3**: `writer.js` 接线 —— 1657 行 → **1563 行**（-94）；`import { getErrorTypeLabel, WRITER_TABS, polishReasonText, renderWordDiff } from './wr-format.js';` + `export { getErrorTypeLabel };`；反向检查确认 6 个符号在 `writer.js` **零残留定义**（假解耦检查通过）
- [x] **Step 4**: 导出面冻结核验 —— 用 `test_frontend_module_graph.py` 自己的 `_parse_own_exports` + `_parse_named_reexports` 解析 master 与现状：**各 60 个，缺失 0、新增 0**。另用 `node --check`（复制为 `.mjs`）确认两文件都是合法 ESM
- [x] **Step 5**: 探针实参扩展 —— **只有 `POLISH_REASON_COPY` 那一处**扩为 `read_source("static/js/wr-format.js", "static/js/writer.js")`；另 3 处（`judge_advisories` / `ev.max_turns` / android `aiPolishEssay`）**回到单文件读**。原因见下方「只扩必要执行面」纪律
- [x] **Step 6**: 变异自证 2/2 —— ①在 `wr-format.js` 删 `POLISH_REASON_COPY` 键 ⇒ 文案探针 exit 1；②把 `getErrorTypeLabel` 从 `wr-format.js` 导出里去掉 ⇒ `test_every_named_import_resolves_to_a_real_export` exit 1；复原后均 exit 0、字节一致
- [x] **Step 7**: 门禁 + 用例数守恒 —— `ruff check .` 全绿 · `mypy --strict delector tools` 115 文件 0 错 · `mypy --follow-imports=skip tests` 153 文件 0 错 · 定向 150 passed · 收集数 2367 **严格不变**
- [x] **Step 8**: Physical Evidence Gate + 原子提交（`refactor(wr): extract pure format layer to wr-format.js`）

**⚠️ 「只扩必要执行面」纪律（本次实测确立，非计划预设）**：把 4 处探针的读法**一律**扩成多文件 concat 后，`tests/test_server_android_fallback.py` 的
`assert "api_key" not in writer_src.lower() or ...` 这条 OR 链的**第一子句被静默中和**——
新模块里的 `no_api_key` 是**原因码名**（不是凭据），却让 `"api_key" in src` 永真，于是整条 OR 退化到只剩后两个子句。断言仍绿，**判别力却悄悄降了**（正是本仓红线 11 的「死测」形态）。
故纪律定为：**seam 只扩到「该探针真正锚定的符号将要搬到」的文件**；其余保持单文件读。多文件 concat 是「让搬家不破探针」的手段，不是「顺手拓宽」的理由。

---

### Task 3: 抽出 `static/js/wr-api.js`（持久化访问层）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files（实测收敛后的实际改动面）:**
- Create: `static/js/wr-api.js`（120 行 / 14 个端点函数）
- Modify: `static/js/writer.js`（**17 处** `await api(...)` 调用点，非计划预估的 14 —— 实测计数为准；1563 行 → **1526 行**）
- Modify: `tests/`：**未改**。既有 `test_frontend_module_graph.py` 的自治图校验已覆盖新模块（glob 自动纳入）
- **实测收敛说明**：计划里写的「14 处」是把端点种类当成了调用点数；实际调用点 17 个（`POST /api/essays` 出现 4 次等）。`internals` 端点数 = 14 个去重后端点（与 `delector/routes/writing.py` 注册的 15 条中除流式 `ai-polish` 外的全部）。

**Interfaces:**
- Consumes: `core.js::api(path, opts) -> Promise<any>`
- Produces（`wr-api.js` 导出；**每个函数 = 一个端点，返回 `api()` 的原样结果**）:
  ```js
  export async function fetchWriterEssays(): Promise<any[]>;                       // GET    /api/essays
  export async function fetchWriterEssay(id): Promise<any>;                        // GET    /api/essays/:id
  export async function createWriterEssay(title, content): Promise<any>;           // POST   /api/essays
  export async function updateWriterEssay(id, title, content): Promise<any>;       // PUT    /api/essays/:id
  export async function removeWriterEssay(id): Promise<any>;                       // DELETE /api/essays/:id
  export async function analyzeWritingRemote(text): Promise<any>;                  // POST   /api/writing/analyze
  export async function saveWritingGrammarCard(body): Promise<any>;                // POST   /api/writing/cards
  export async function fetchEssayVersions(essayId): Promise<any[]>;               // GET    /api/essays/:id/versions
  export async function createEssayVersion(essayId, body): Promise<any>;           // POST   /api/essays/:id/versions
  export async function fetchEssayVersion(essayId, versionId): Promise<any>;       // GET    /api/essays/:id/versions/:vid
  export async function removeEssayVersion(essayId, versionId): Promise<any>;      // DELETE /api/essays/:id/versions/:vid
  export async function restoreEssayVersion(essayId, versionId): Promise<any>;     // POST   /api/essays/:id/restore
  export async function applyWritingPolish(body): Promise<any>;                    // POST   /api/writing/apply
  export async function fetchWritingPolishDiff(text): Promise<any>;                // POST   /api/writing/ai-polish/diff（非流式降级路径）
  ```
- **层级硬契约（本模块 MUST）**：零 `document` / `window` / `navigator` / `localStorage` / `getElementById` / `querySelector` / `innerHTML` / `addEventListener`；零 `notify(` / `alert(` / `confirm(`（**失败的用户可见提示属视图层**，必须留在 `writer.js` 的 `catch` 里）；零 `setTimeout` / `setInterval`（计时是编排面）。唯一允许的 import 是 `./core.js` 的 `api`。
- **不抽走的**：`readPolishStream`（SSE 编排，含进度回调）、`polishState`、`currentEssayId` 等模块状态、所有 `document.getElementById` 渲染路径、所有 `alert` / `notify` 失败提示。

**Injected Instincts:**
- [x] `[Instinct: Behavior-Frozen]`: 14 个调用点 MUST 逐个比对「改写前 `api(path, opts)` 的实参」与「改写后 `wr-api.js` 内同一端点的实参」逐字相等（方法、路径、`headers`、`body` 的 JSON 形状）。任何参数顺序/默认值的顺手改动都视为回归。
- [x] `[Instinct: Error-Rail-Preserved]`: `catch` 块 MUST 留在 `writer.js` 且**逐字不变**——抽持久化层不能变成「把错误也抽走」（本仓红线：零静默失败）。
- [x] `[Instinct: Route-Parity]`: 14 个端点路径 MUST 与 `delector/routes/writing.py` + `delector/routes/articles.py` 的实际注册路径一致；对不上就是抽错了端点（用 `grep -n "@router\." delector/routes/writing.py` 复核）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 抽出 static/js/wr-api.js.
> Mode: AFK | Role: TDD Builder
> Goal: 把 writer.js 里 14 处非流式 `api(...)` 调用抽成 wr-api.js 的具名端点函数（返回值原样透传），writer.js 的 catch/notify 错误轨逐字保留。
> Steps:
> 1. 记录基线：定向 pytest + `grep -c 'await api(' static/js/writer.js`（当前 14）。
> 2. 建 `static/js/wr-api.js`（只 import `api`；零 DOM / 零 notify / 零计时器）。
> 3. 逐点替换 writer.js 的调用为具名函数；每个端点的实参与原处逐字比对。
> 4. 复核端点路径与 `delector/routes/writing.py` 注册一致。
> 5. 变异自证：在 `wr-api.js` 里注入一处 `document.getElementById` ⇒ Task 4 的分层闸必须变红（若闸已在则直接验；否则记录待验）。
> 6. 跑定向套件 + `ruff` + `mypy --strict delector tools` + `mypy --follow-imports=skip tests`。
> Return: 摘要 + MANDATORY 物理凭据（退出码 + 用例数 + 14 个调用点的实参比对表）。"

**Step Breakdown:**
- [x] **Step 1**: 基线 —— `await api(` 计数 **17**（计划预估 14，实测为准）；定向套件 157 passed / 收集 2367
- [x] **Step 2**: 建 `wr-api.js` —— 14 个端点函数，只 import `./core.js` 的 `api`；零 DOM / 零 notify / 零计时器
- [x] **Step 3**: `writer.js` 逐点替换 17 处（脚本对每处做**命中计数断言**，不符即抛，防漏改/错改）；`writer.js` 1563 → 1526 行；`core.js` 的 `api` 已无引用，从 import 摘除
- [x] **Step 4**: **实参保真 PASS** —— 用括号配平扫描比对 master 每处调用点与 `wr-api.js` 的（方法 / 路径 / 载荷键集合）：**17/17 一致**，唯一例外是 SSE 流式的 `{ text, stream: true }`（刻意留在 `writer.js` 用 `fetch` 直连）
- [x] **Step 5**: **路由一致 PASS** —— 14 个端点与 `delector/routes/writing.py` 注册表逐条比对（路径参数名归一后）全部命中；后端 15 条里唯一未封装的是流式 `POST /api/writing/ai-polish`
- [x] **Step 5b**: **错误轨保真 PASS** —— 逐行比对 master 与现状的 `alert(` / `notify(` / `console.error(` 行：**27 条对 27 条，丢失 0、新增 0**（持久化层不吞异常、不改呈现）
- [x] **Step 6**: 门禁 —— `ruff check .` 全绿 · `mypy --strict delector tools` 115 文件 0 错 · `mypy --follow-imports=skip tests` 153 文件 0 错 · 定向 157 passed · 收集数 **2367 不变** · 三文件 0 lone LF
- [x] **Step 7**: Physical Evidence Gate + 原子提交（`refactor(wr): extract persistence layer to wr-api.js`）

**⚠️ 真缺陷（由 `node --check` 抓到，非人工发现）**：`wr-api.js` 最初把函数命名为 `restoreEssayVersion`，而 `writer.js` **已有同名的视图层编排函数**（`export async function restoreEssayVersion(versionId)`，含 confirm + 编辑器回填、经 window 暴露给 onclick）。同名导入 + 本地声明 = ES 的 **SyntaxError（重复声明）**，会让**整张模块图一起挂**（正是本仓 v4.7.0「空模块 → 链接期 SyntaxError → Android 交互全死」那类事故）。已改名为 `restoreEssayVersionRemote`（沿用既有 `analyzeWritingRemote` 的先例）并在模块内写明由来。

**⚠️ 变异自证结果：现存门禁 CAUGHT 2/5，UNCAUGHT 3/5（如实登记，不粉饰）**：

| 变异 | 结果 | 捕获者 |
| --- | --- | --- |
| M3 导入名与本地声明重名 | **CAUGHT** | `test_every_named_import_resolves_to_a_real_export` |
| M5 抽了但留副本（`writer.js` 重新定义 `renderWordDiff`） | **CAUGHT** | `node --check`（**注意：本仓 CI 并不跑 `node --check`**） |
| M1 L2 层混入 DOM（`wr-api.js` 注入 `document.getElementById`） | **UNCAUGHT** | 无 → Task 4 规则① |
| M4 L1 纯层混入网络（`wr-format.js` 注入 `fetch`） | **UNCAUGHT** | 无 → Task 4 规则② |
| M2 前端端点方法改错（`DELETE` → `POST`） | **UNCAUGHT** | 无 → Task 4 规则③（路由一致闸） |

三条 UNCAUGHT 即 Task 4 闸的规则输入；M5 的现状捕获者 `node --check` 不在 CI 里，故 Task 4 另需一条**重复声明规则**（等价于把 `node --check` 的这条判别力搬进 Python 闸）。

---

### Task 4: 新增 `tools/check_frontend_layers.py` 前端分层机械闸 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/check_frontend_layers.py`
- Create: `tests/test_frontend_layers.py`
- Modify: `.github/workflows/ci.yml`（新增 `frontend-layers` job，与 `Layer Invariants Gate` 并列）

**Interfaces:**
- Consumes: `static/js/*.js` 源码文本
- Produces:
  ```python
  LAYER_SPEC: dict[str, LayerSpec]   # 模块 -> (层名, 硬禁令集合, 允许的 import 白名单)
  def scan_module(path: Path) -> list[Violation]   # 按禁令集合逐条扫描，返回 (文件, 行号, 禁令名, 原始行)
  def main(argv) -> int                            # exit 0 = 全绿；exit 1 = 有违规并逐条打印
  ```
- **判据（本闸钉的契约）**：
  | 模块 | 层 | 硬禁令 | 允许的 import |
  | --- | --- | --- | --- |
  | `wr-format.js` | L1 纯层 | DOM 全家（`document`/`window`/`navigator`/`localStorage`/`getElementById`/`querySelector`/`innerHTML`/`addEventListener`）、网络（`fetch(`/`api(`/`XMLHttpRequest`）、用户提示（`notify(`/`alert(`/`confirm(`）、计时器（`setTimeout`/`setInterval`）、顶层 `let` | 仅 `./core.js` |
  | `wr-api.js` | L2 持久化层 | DOM 全家、用户提示（`notify(`/`alert(`/`confirm(`）、计时器 | 仅 `./core.js` |
- **反向依赖禁令（双向）**：L1 / L2 MUST NOT import `writer.js`（否则分层倒置，且会与 `main.js` 的导入形成环）。
- **防「假解耦」判据**：`writer.js` MUST NOT 再定义被搬走的符号名（`wr-format.js` 的 6 个 + 14 个端点函数名）；命中即报「抽了但留副本」。
- **规则④ 重复声明禁令（Task 3 变异 M3/M5 实测驱动的补充）**：任一本模块**导入的名字** MUST NOT 同时被本模块**本地声明**。ES 对重复声明是**链接期 SyntaxError**，会让整张模块图一起挂（本仓 v4.7.0 事故同类：空模块 → 链接期崩 → Android 交互全死）。现状唯一捕获者是 `node --check`，而**本仓 CI 不跑它** —— 故 MUST 把这条判别力搬进 Python 闸。
- **规则⑤ 前端↔后端路由一致（Task 3 变异 M2 实测驱动的补充）**：`wr-api.js` 里每个 `api()` 调用的（方法 + 路径）MUST 在后端 `delector/routes/*.py` 的 `@router.<method>("...")` 注册表里存在（路径参数名归一后比对）。判别力：把 `method: 'DELETE'` 改成 `'POST'` ⇒ 闸必须红（实测现存门禁 UNCAUGHT）。

**Injected Instincts:**
- [x] `[Instinct: Gate-Not-Description]`: 闸的判据 MUST 独立于当前代码内容——用**合成夹具**（`tmp_path` 里造一个含 `document.` 的假 `wr-format.js`）证明它能变红，而不是「跑一遍当前树恰好绿」。
- [x] `[Instinct: Mutation-Proof]`: MUST 提供两条变异自证：①往 `wr-format.js` 注入 `document.getElementById` ⇒ 闸 exit 1；②把某端点函数复制回 `writer.js` ⇒ 防假解耦判据 exit 1。
- [x] `[Instinct: Line-Level-Blame]`: 违规 MUST 报「文件:行号:禁令名 + 原始行」，禁止只报「有 N 处违规」（否则下一个人不知道该改哪一行）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 新增 tools/check_frontend_layers.py 前端分层机械闸.
> Mode: AFK | Role: TDD Builder
> Goal: 把 Task 2/3 建立的层边界钉成机械闸，并接入 CI，附合成夹具单测与两条变异自证。
> Steps:
> 1. 先跑 `python3 tools/check_frontend_layers.py`（此刻脚本尚不存在 ⇒ 记录为 RED 的起点）。
> 2. 写 `tools/check_frontend_layers.py`（判据见计划 Task 4 的 Interfaces 表）。
> 3. 写 `tests/test_frontend_layers.py`：合成夹具（tmp_path 造假模块）+ 真树集成断言 + 两条变异自证。
> 4. 变异自证 ①：注入 `document.getElementById` 到真 `wr-format.js` ⇒ 闸 exit 1 ⇒ 复原。
> 5. 变异自证 ②：把 `fetchWriterEssays` 复制回 `writer.js` ⇒ 闸 exit 1 ⇒ 复原。
> 6. 在 `.github/workflows/ci.yml` 加 `frontend-layers` job（照抄 `Layer Invariants Gate` 的形态）。
> 7. 跑 `python3 tools/check_frontend_layers.py`（exit 0）+ `python3 -m pytest tests/test_frontend_layers.py -q`。
> 8. 跑 `ruff check .` / `mypy --strict delector tools` / `mypy --follow-imports=skip tests`。
> Return: 摘要 + MANDATORY 物理凭据（两条变异各自的红/绿退出码 + 用例数）。"

**Step Breakdown:**
- [x] **Step 1**: 落地 `tools/check_frontend_layers.py`（约 500 行）—— 规则表见上；**刻意不重复** `check_frontend_api_contract.py` 已有的**路径**维度，只补**方法**维度
- [x] **Step 2**: 关键实现口径 —— ①`strip_comments` 先剥 `//` 与 `/* */`（**保留行号与列位**），否则 L1/L2 模块头注释里逐字写着的 `document`/`fetch`/`notify` 会让闸**对自己的文档开火**（假红）；②字符串**不**剥离，并在 docstring 里写明这是保守方向（假红可改、假绿是漏洞）；③违规一律报 `文件:行号:规则:原始行`；④启动时 `_bootstrap_env()` 把 DB 路径钉进临时目录（与路由契约闸同口径，防 import `delector.server` 污染仓库根）
- [x] **Step 3**: `tests/test_frontend_layers.py` **20 条**用例 —— 纯函数 3 条 + 合成夹具 14 条（含**两条阴性对照**：干净副本零违规、L2 允许网络）+ 真树集成 3 条（端到端 exit 0、行级归因格式、CLI 红态）
- [x] **Step 4**: **真树变异自证 8/8 PASS** —— 往**生产文件**注入缺陷，每条都断言三件事：注入后 `exit=1` **且 stderr 报出期望的那条规则名**、复原后 `exit=0`、三文件逐字节复原一致。只断言「exit 1」不算证明（闸可能因别的原因红）：
  | # | 变异 | 期望规则 | 结果 |
  | --- | --- | --- | --- |
  | ① | L1 混入 DOM | `L1 纯格式化层禁dom` | PASS |
  | ② | L1 混入网络 | `L1 纯格式化层禁network` | PASS |
  | ③ | L1 顶层可变状态 | `L1 纯格式化层禁mutable-state` | PASS |
  | ④ | L2 混入 DOM | `L2 持久化访问层禁dom` | PASS |
  | ⑤ | 反向依赖（L2 import writer.js） | `reverse-dependency` | PASS |
  | ⑥ | 重复声明（导入名又本地声明） | `duplicate-declaration(getErrorTypeLabel)` | PASS |
  | ⑦ | 假解耦（重定义已迁出符号） | `false-decoupling(renderWordDiff` | PASS |
  | ⑧ | 方法不一致（`DELETE`→`POST`） | `method-mismatch(POST` | PASS |
- [x] **Step 5**: 接入 CI —— **挂在已装依赖的 `ci` job 内**（`Frontend API contract gate` 之后、`tsc` 之前），而**不是**新建纯 stdlib job：规则⑤ 要 `delector.server` 取真实路由表，新 job 得整套重装依赖。已用 `yaml.safe_load` 复核 YAML 合法
- [x] **Step 6**: 门禁 + 用例数 —— `ruff check .` 全绿（修掉 1×F401 + 3×E501 + 1×E741）· `mypy --strict delector tools` 116 文件 0 错 · `mypy --follow-imports=skip tests` 154 文件 0 错 · 收集数 **2367 → 2387**（+20 = 本闸自身验收面，计划允许的唯一新增断言来源）· 全部触碰文件 0 lone LF
- [x] **Step 7**: Physical Evidence Gate + 原子提交（`feat(tools): add frontend layer invariants gate`）

---

### Task 5: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log` · `docs/plans/2026-10-19-writer-js-modularization.md`（Fog of War 核销）

**Step Breakdown:**
- [ ] **Step 1: 逐字复刻 CI 门禁命令**：`python3 -m ruff check .`；`python3 -m mypy --strict delector tools`；`python3 -m mypy --follow-imports=skip tests`；`python3 tools/check_layer_invariants.py`；`python3 tools/check_mock_drift.py`；`python3 tools/check_silent_degradation.py`；`python3 tools/check_frontend_layers.py`；`cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] **Step 2: 全量 pytest**（拆前端产物触及 5 个测试文件，定向套件不足以证明无回归）
- [ ] **Step 3: 模块图自治校验**：`python3 -m pytest tests/test_frontend_module_graph.py -v`（新模块自动入 glob）
- [ ] **Step 4: 用例数守恒核验**：拆分前后全量用例数必须相等 + 新增闸用例数（记录两个数）
- [ ] **Step 5: CRLF 卫生**（0 lone LF，全量触碰文件）
- [ ] **Step 6: 追加 `WORKMEMORY/work.log` DONE 事件**
- [ ] **Step 7: 推送分支并创建 PR**（base=master）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: `buildSentenceHighlightedText` 的纯化]**：`writer.js:185` 这个 HTML 字符串构造函数读了模块级可变状态 `selectedSpanRef`（判「当前选中 span」）并产出 `onclick="selectWriterSpan(...)"`。要在不改变其导出签名的前提下纯化，需要把「选中态」显式入参——但 `reader.js` / `workbench` 是否也消费它**尚未测量**（本次实测仅 `writer.js` 内 2 处调用点）。**待 Task 2/3 落地后**按实际调用面决定是「加一个可选 `selected` 参数」还是「另立 `wr-markup.js`」。本计划不投机拆它。
- **[Unknown 2: `cards.js` / `reader.js` 的同构切分收益]**：`cards.js`（1,335 行）与 `reader.js`（1,403 行）关注点结构与 `writer.js` 类似，但**各自的纯函数占比未经测量**。本计划只做 `writer.js` 一个样本；若 Task 1~5 的模板被证明可复用，再为其开第二份计划。**判据草案**：以「纯函数行数 / 总行数」与「探针损伤面（A 类锚点数）」两个指标决定顺序。
- **[Unknown 3: 前端分层闸是否应扩到全部 30 个模块]**：本闸当前只声明 `wr-*` 两个模块。扩到全量会让存量 30 个模块几乎全红（`core.js` 本身就含 DOM）。**待 Task 4 落地后**评估「按目录/前缀渐进纳管」还是「只纳管显式声明的层」。本计划不扩大纳管面。
- **[Unknown 4: Android WebView 上的多模块加载]**：ES Module 的多文件 unpacked 加载在 Chaquopy WebView 上**从未真机验证**（C7 的 Unknown 2 已登记同一问题）。本计划新增 2 个模块会小幅增加加载扇出，但**不引入仅 ES Module 才有的语义**（无循环 import、无顶层 await），保持回退路径可用。真机验证属 C4 面，不在本计划内。

---

## 🚫 Out of Scope

- 不改 `delector/**` 后端任何文件（写作域 API 已冻结，本计划只消费）。
- 不改 `static/index.html` / `static/views/**` / `static/modals/**` / `static/layout/**` / `tools/build_index_html.py` / `tools/check_index_html_sync.py`（另一分支 `refactor/index-html-split` 的占面）。
- 不做 `cards.js` / `reader.js` / `encounter.js` 的切分（见 Fog of War Unknown 2）。
- 不引入任何构建工具或 npm 依赖（零构建立场）。
- 不改变任何端点的请求/响应形状（纯前端搬家）。
- 不新增业务断言；新增测试只允许出现在 `tests/test_frontend_layers.py`（机械闸自身的验收面）。