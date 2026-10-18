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

**Files:**
- Modify: `tests/test_server_ai_polish.py:1019-1031`（`test_frontend_polish_reason_copy_covers_every_reason_code`）
- Modify: `tests/test_server_ai_polish.py:1034-1040`（`test_frontend_polish_progress_takes_max_turns_from_server`）
- Modify: `tests/test_audit_hardening.py:415,496`、`tests/test_server_android_fallback.py:614`（读法统一为 `read_source`，当前仅传 `static/js/writer.js`，**行为逐字不变**）
- Test: `tests/test_server_ai_polish.py` · `tests/test_audit_hardening.py` · `tests/test_server_android_fallback.py`

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
- [ ] **Step 1**: 记录 3 个探针文件的全绿基线与用例数
- [ ] **Step 2**: 4 处读法改为 `read_source()`（RED → GREEN）
- [ ] **Step 3**: 零漂移比对（新旧键集合逐字相等）
- [ ] **Step 4**: 变异自证（删键 ⇒ 变红 ⇒ 复原）
- [ ] **Step 5**: 门禁（pytest / ruff / mypy tests）
- [ ] **Step 6**: Physical Evidence Gate（退出码 + 计数 + diff）
- [ ] **Step 7**: 原子提交（`refactor(wr): route writer.js probes through the multi-file source seam`）

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
- [ ] **Step 1**: 记录基线用例数
- [ ] **Step 2**: 建 `wr-format.js`（源码逐字节等价）
- [ ] **Step 3**: `writer.js` 接线（import，删本地定义）
- [ ] **Step 4**: 导出面冻结核验（master vs 现状 diff 为空）
- [ ] **Step 5**: 探针实参扩展 + 变异自证
- [ ] **Step 6**: 门禁 + 用例数守恒
- [ ] **Step 7**: Physical Evidence Gate
- [ ] **Step 8**: 原子提交（`refactor(wr): extract pure format layer to wr-format.js`）

---

### Task 3: 抽出 `static/js/wr-api.js`（持久化访问层）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/js/wr-api.js`
- Modify: `static/js/writer.js:806-1050,1284-1395,1431-1660`（14 处 `api(...)` 调用点改为调用新模块的具名函数）
- Test: `tests/test_frontend_module_graph.py` · `tests/test_server_ai_polish.py` · `tests/test_writer_mobile.py`

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
- [ ] **Step 1**: 记录基线（用例数 + `await api(` 计数）
- [ ] **Step 2**: 建 `wr-api.js`（14 个端点函数）
- [ ] **Step 3**: `writer.js` 逐点替换
- [ ] **Step 4**: 实参逐字比对 + 端点路径复核
- [ ] **Step 5**: 错误轨保留核验（catch/notify 逐字不变）
- [ ] **Step 6**: 门禁 + 用例数守恒
- [ ] **Step 7**: Physical Evidence Gate
- [ ] **Step 8**: 原子提交（`refactor(wr): extract persistence layer to wr-api.js`）

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
- [ ] **Step 1**: 记录 RED 起点（脚本不存在）
- [ ] **Step 2**: 写闸脚本（LAYER_SPEC + scan_module + main）
- [ ] **Step 3**: 写单测（合成夹具 + 真树集成断言）
- [ ] **Step 4**: 变异自证 ①（注入 DOM 调用 ⇒ 红 ⇒ 复原）
- [ ] **Step 5**: 变异自证 ②（复制端点函数回 writer.js ⇒ 红 ⇒ 复原）
- [ ] **Step 6**: 接入 CI（`frontend-layers` job）
- [ ] **Step 7**: 门禁 + 用例数守恒
- [ ] **Step 8**: Physical Evidence Gate
- [ ] **Step 9**: 原子提交（`feat(tools): add frontend layer invariants gate`）

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