# C7 实施计划：workbench.html 拆分（含探针现代化前置）

> **Goal**: 把 `static/german/workbench.html`（4730 行单文件 PWA）拆分为多模块，并在拆分**之前**把 140 个耦合探针现代化为「按段读取 / 按目标文件读取」，使拆分既不产生假红（位置断言失效）也不产生假绿（位置断言被降级为存在性断言）。
> **Tech Stack**: 原生 ES Modules（零构建）/ Python 3.11 / pytest / Node（`tools/wb_*.mjs` 探针运行器）
> **Spec Reference**:
> - `docs/reviews/2026-10-16-open-items-backlog.md`（C7 行）
> - `docs/agents/architecture.md`（前端拓扑与跨端契约）
> - `WORKMEMORY/handoff_c7-workbench-html-split.md`（本工作流的交接包，含完整探针盘点）
> **Global Constraints**:
> - **入口路径不可迁移（MUST）**：`static/german/workbench.html` 必须保留在原路径。它被 5 处**路由字符串**钉死：`static/index.html` 的 `data-src="/german/workbench.html"`、`static/js/main.js` 的 `ensureGermanWorkbench`（`getElementById("german-workbench-frame")`）、`tests/test_frontend_guards.py:42`、`tests/test_cards_workbench_no_review_probe.py:90`、`tools/cards_workbench_no_review_probe.mjs:258`。拆分后的形态 = 同一路径的**薄壳 HTML** + `<script type="module">` 引入新模块。
> - **探针强度不可降级（MUST）**：重定向探针时，A 类「相对位置序」与 D 类「计数/唯一性/字节等价」断言 MUST 保持同等判别力。把 A 类降级为 C 类（存在性）会让真红变假绿——这正是本仓「死测」事故的老形态（见 `PROJECT_OVERVIEW.md` 红线 11）。
> - **零新依赖 / 零构建（MUST）**：不引入 webpack / vite / rollup。多文件原生 ES Module，浏览器直接加载（与 ADR 记录的零构建立场一致）。
> - **文件契约**：全文件 UTF-8 CRLF（0 lone LF）；`mypy --strict delector tools` 与 `mypy --follow-imports=skip tests` 零错误；`ruff check .` 零告警。
> - **并行占面（MUST，与另一工作流协调）**：本工作流**独占**下列文件；同时 MUST NOT 触碰 `tests/test_server.py`、`tests/test_desktop_shell.py`、`delector/**`、`.github/**`（并行 C8/C6 工作流的占面）。
>   - 独占：`static/german/workbench.html` · `static/js/**` · `static/css/**`（新增件）· `tools/wb_*.mjs`（13 个）· `tools/build_workbench_seed.py` · `tools/build_embedded_audio.py` · `tests/test_german_workbench.py` · `tests/test_workbench_tokens.py` · `tests/test_a1_workbench_source.py` · `tests/test_frontend_module_graph.py` · `tests/test_exam_domain.py` · `tests/test_audit_hardening.py` · `tests/test_wb_pair_persist_probe.py` · `tests/test_probe_wiring_guard.py` · `tests/probe_runner.py` · `tests/probe_json_contract.py`
> **Branch**: `refactor/c7-workbench-html-split` —— 从 `master` 切出，全套门禁全绿后提 PR 合入，严禁直推 `master`。

---

## 🏛️ Decisions So Far

- **探针盘点（2026-10-18 实测，非引述）**：`static/german/workbench.html` 的耦合探针共 **140 个**，分类如下（判据见交接包）：

  | 类 | 含义 | 数量 | 分布 |
  | --- | --- | --- | --- |
  | **A** | 全文相对位置序 / 标记切片（`split(marker)[1].split(marker2)[0]`、`_top_fn_segment`、`_slice_balanced`） | **91** | `test_german_workbench.py` 77 · `test_wb_pair_persist_probe.py` 1 · `tools/wb_*.mjs` 13 |
  | **B** | 行号钉（`splitlines()` 下标、要求两段源码在**同一物理行**） | **4** | 全在 `test_frontend_module_graph.py:388-433` |
  | **C** | 内容存在性（子串/正则） | **21** | tokens 7 · a1_source 6 · audit_hardening 2 · exam_domain 1 · german_workbench 5 |
  | **D** | 尺寸/结构/计数/字节等价 | **12** | german_workbench 7 · a1_source 2 · 探针注册表 1 · 2 个构建脚本 |
  | **E** | 不受影响（路由字符串 / iframe / docstring / 注释） | **12** | 分散 |

- **拆分策略裁决 = 按「探针损伤面」升序分阶段**，而非按文件体积。先抽损伤面最小的块，用首个真实拆分验证迁移模板，再逐级推进。理由：探针是本次的**契约面**，先动它们、再动产物，可让每一步都有可比对的绿基线与可复现的红。
- **入口路径保持**（见 Global Constraints）：拆分后 `workbench.html` 仍是唯一路由入口。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 探针读取层与 B 类行号钉结构化 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(前置中的前置：定义后续所有迁移的写法)*

**Files:**
- Modify: `tests/test_frontend_module_graph.py:388-433`
- Create: `tests/wb_source.py`（探针读取公共层）
- Test: `tests/test_frontend_module_graph.py`

**Interfaces:**
- Consumes: `pathlib.Path.read_text(encoding="utf-8")`
- Produces:
  ```python
  def read_source(*rel_paths: str) -> str
      """按仓库相对路径读源文本；多路径时按给定顺序拼接（拆分后跨文件锚定用）。"""
  def segment(text: str, start_marker: str, end_marker: str) -> str
      """返回 start_marker 之后到 end_marker 之前的片段；缺任一标记即抛 AssertionError 并打印所查标记。"""
  def decl_body(text: str, decl: str) -> str
      """按大括号配平取出一个顶层声明体（替代 _top_fn_segment/_slice_balanced）。"""
  def line_of(text: str, needle: str) -> int
      """返回 needle 首次出现的行号（B 类行号钉的结构化替代）。"""
  def same_line(text: str, a: str, b: str) -> bool
      """a 与 b 是否落在同一物理行（替代「下标相等」的写法）。"""
  ```
- **改造要求（B 类 4 处，`test_frontend_module_graph.py:388-433`）**：把
  - `_line_no(lines, ...)` 下标比较 → 改为基于 `line_of` / `same_line` 的**结构性**断言；
  - `assert "wbsync.push()" in lines[i]`（要求与 `function saveX() {` **同一物理行**）→ 改为 `segment(decl_body(...))` 内断言，**判别力不得下降**（原断言钉的是「同一行」这一物理事实，新写法须显著更强，例如断言 push 调用落在该函数体内且首次出现位置早于任一 `await`）。

**Injected Instincts:**
- [ ] `[Instinct: Strengthen-Not-Weaken]`: 迁移后必须新增一条**变异自证**——把 `wbsync.push()` 从该函数体移出，新断言须变红。
- [ ] `[Instinct: Fail-Loud]`: `segment()` 找不到标记时必须抛出并打印所查标记原文，禁止返回空串（空串会让下游存在性断言静默通过）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 探针读取层与 B 类行号钉结构化.
> Mode: AFK | Role: TDD Builder
> Goal: 建立 `tests/wb_source.py` 探针读取公共层，并把 `tests/test_frontend_module_graph.py:388-433` 的 4 个 B 类行号钉改写为结构性断言（判别力不得下降）。
> Steps:
> 1. 先跑 `python3 -m pytest tests/test_frontend_module_graph.py -v` 记录当前全绿基线。
> 2. 写 `tests/wb_source.py`（接口见计划 Task 1 的 Produces 段），并为其写单测 `tests/test_wb_source.py`（含：标记缺失时抛 AssertionError、多文件拼接顺序、`decl_body` 大括号配平对嵌套函数正确、`same_line` 边界）。
> 3. 改写 `tests/test_frontend_module_graph.py:388-433` 的 4 处断言为结构性写法。
> 4. 变异自证：把 `wbsync.push()` 调用从 `saveX()` 函数体移出，确认新断言变红；复原。
> 5. 跑 `python3 -m pytest tests/test_frontend_module_graph.py tests/test_wb_source.py -v`，全绿。
> 6. 跑 `ruff check tests/wb_source.py tests/test_wb_source.py tests/test_frontend_module_graph.py` 与 `mypy --follow-imports=skip tests`。
> Return: 摘要 + MANDATORY 物理执行凭据（命令 + 退出码 + 用例计数 + git diff）。"

**Step Breakdown:**
- [x] **Step 1**: 记录 `test_frontend_module_graph.py` 全绿基线（用例数）
- [x] **Step 2**: 写 `tests/wb_source.py` + 其单测（RED → GREEN）
- [x] **Step 3**: 改写 4 处 B 类行号钉
- [x] **Step 4**: 变异自证（移出 push 调用 ⇒ 变红 ⇒ 复原）
- [x] **Step 5**: 门禁（pytest / ruff / mypy tests）
- [x] **Step 6**: Physical Evidence Gate（退出码 + 计数 + diff）
- [x] **Step 7**: 原子提交（`refactor(c7): structuralize line-pin probes`）

---

### Task 2: 前端 mjs 探针读取口统一 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/wb_a1_bootstrap_probe.mjs` · `tools/wb_merge_probe.mjs` · `tools/wb_queue_probe.mjs` · `tools/wb_tags_probe.mjs` · `tools/wb_sync_probe.mjs` · `tools/wb_pair_persist_probe.mjs` · `tools/wb_pair_push_probe.mjs` · `tools/wb_phone_pull_probe.mjs` · `tools/wb_phone_pull_silent_probe.mjs` · `tools/wb_rtc_connect_probe.mjs` · `tools/wb_rtc_reconnect_probe.mjs` · `tools/wb_rich_backfill_probe.mjs` · `tools/wb_reader_rich_backfill_probe.mjs`
- Modify: `tests/probe_runner.py` · `tests/probe_json_contract.py`（若探针契约形状变化）
- Test: `tests/test_german_workbench.py`（6 个 probe 包装用例）· `tests/test_wb_pair_persist_probe.py` · `tests/test_probe_wiring_guard.py`

**Interfaces:**
- Consumes: 环境变量或参数提供的**探针源根**
- Produces: 每个探针内新增
  ```js
  const SRC_ROOT = process.env.WB_SRC_ROOT ?? "static/german";   // 未来可指向模块目录
  function readSources(names) { /* 读多文件并按序拼接 */ }
  function sliceDecl(src, name) { /* 大括号配平取声明体；找不到抛错并打印 name */ }
  ```
- **要求**：13 个探针当前都以「读 `workbench.html` + 按标记切片」取源码（各文件行号见交接包表 3）。改造后必须**先支持多文件来源**（现在传单文件即可，拆分后只需改 `WB_SRC_ROOT` 与文件清单），且 `sliceDecl` 找不到声明时**必须非零退出并打印所查声明名**（现行为是 `"找不到声明 const X"` 抛错——保持并加退出码）。

**Injected Instincts:**
- [ ] `[Instinct: Interface-Before-Move]`: 探针读取口必须先于产物搬迁改造，否则 13 个探针在拆分瞬间同时抛错且无可归因信息。
- [ ] `[Instinct: No-Silent-Skip]`: 探针找不到源文件 MUST 非零退出，禁止返回空 JSON 让包装层判「通过」。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 前端 mjs 探针读取口统一.
> Mode: AFK | Role: TDD Builder
> Goal: 让 13 个 `tools/wb_*.mjs` 探针从「单文件 + 标记切片」改为「可多文件来源 + 同语义切片」，为后续拆分预留读取口；行为对当前单文件布局**逐字不变**。
> Steps:
> 1. 先跑 `python3 -m pytest tests/test_german_workbench.py tests/test_wb_pair_persist_probe.py tests/test_probe_wiring_guard.py -v` 记录全绿基线。
> 2. 为每个探针加入 `SRC_ROOT` 与 `readSources()`（默认值保持当前行为），把切片函数统一为 `sliceDecl()`（缺失即非零退出）。
> 3. 证明零行为漂移：新旧输出 JSON 逐字相等（对每个探针各跑一次比对）。
> 4. 验证 `tests/probe_json_contract.py` 的契约未被破坏。
> 5. 跑定向套件 + `ruff check` + `mypy --follow-imports=skip tests`。
> Return: 摘要 + 物理凭据（每个探针的旧/新输出比对结果 + 退出码）。"

**Step Breakdown:**
- [ ] **Step 1**: 记录探针类用例全绿基线
- [ ] **Step 2**: 13 个探针加读取口 + `sliceDecl()`（RED → GREEN）
- [ ] **Step 3**: 新旧输出逐字比对（零漂移证明）
- [ ] **Step 4**: 探针 JSON 契约校验
- [ ] **Step 5**: 门禁
- [ ] **Step 6**: Physical Evidence Gate
- [ ] **Step 7**: 原子提交（`refactor(c7): give wb probes a multi-file source seam`）

---

### Task 3: 首次真实拆分——CSS 抽取（最小损伤面） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/css/workbench.css`
- Modify: `static/german/workbench.html`（`<style>…</style>` → `<link rel="stylesheet" href="../css/workbench.css">`）
- Modify: `tests/test_workbench_tokens.py:48-244`（7 个 C 类 + 1 hybrid A）
- Modify: `tests/test_german_workbench.py:1827-1832`（`<style>` 抽取的 A 类）
- Test: 同上

**Interfaces:**
- Consumes: `static/german/workbench.html` 内联 `<style>` 块
- Produces: `static/css/workbench.css`（内容逐字节等于被搬走的 `<style>` 内容，除首尾换行归一）

**Injected Instincts:**
- [ ] `[Instinct: Byte-Equality-Or-Explain]`: 抽取必须证明「搬走的 CSS 内容逐字节等于原内联块内容」，任何归一化（换行/缩进）都要在提交信息里写明并给出理由。
- [ ] `[Instinct: Token-Contract]`: `tests/test_workbench_tokens.py` 是设计系统 token 契约闸，重定向后 MUST 仍能抓住「token 值被改」这一类变异。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 首次真实拆分——CSS 抽取.
> Mode: AFK | Role: TDD Builder
> Goal: 把 `static/german/workbench.html` 的内联 `<style>` 抽到 `static/css/workbench.css`，并重定向 8 个受影响探针；以此验证 Task 1 建立的迁移模板。
> Steps:
> 1. 记录基线：`python3 -m pytest tests/test_workbench_tokens.py tests/test_german_workbench.py -v`（记用例数）。
> 2. 抽取 CSS 到新文件（内容逐字节相等），HTML 改 `<link>`。
> 3. 重定向 `tests/test_workbench_tokens.py` 的正则探针（`body` / `header\.top\s+h1` / `\.face` / `\.qopt`）到 CSS 文件；`test_german_workbench.py:1827` 的 `<style>` 抽取改为读 CSS 文件。
> 4. 变异自证：改掉 CSS 里任一 token 值 ⇒ 对应断言必须变红；复原。
> 5. 跑定向套件；确认用例数与基线一致（不多不少）。
> Return: 摘要 + 物理凭据。"

**Step Breakdown:**
- [ ] **Step 1**: 记录基线用例数
- [ ] **Step 2**: 抽取 CSS（字节等价证明）
- [ ] **Step 3**: 重定向 8 个探针
- [ ] **Step 4**: 变异自证（token 值变异 ⇒ 红 ⇒ 复原）
- [ ] **Step 5**: 门禁 + 用例数守恒核对
- [ ] **Step 6**: Physical Evidence Gate
- [ ] **Step 7**: 原子提交（`refactor(c7): extract workbench inline CSS`）

---

### Task 4: 种子数据抽取与 A/D 类探针重定向 [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]
*(触碰构建产物契约：`build_workbench_seed.py` / `build_embedded_audio.py` 会就地改写这四个内联 const)*

**Files:**
- Create: `static/js/wb-seed-data.js`（或等价模块，承载 `SEED_WORDS` / `CORE_WORD_SEED_IDS` / `CORE_CUSTOM_WORDS` / `SEED_ID_ALIASES` / `EMBEDDED_AUDIO`）
- Modify: `static/german/workbench.html`
- Modify: `tools/build_workbench_seed.py:47,94,292` · `tools/build_embedded_audio.py:31,88`
- Modify: `tests/test_german_workbench.py`（`_slice_balanced` 锚点 ~6 处 + D 类计数 ~5 处）
- Modify: `tests/test_a1_workbench_source.py:62-251`（6 C + 2 D，含**逐字节注入等价**与**注入幂等**两条 D 类）
- Test: 同上

**Interfaces:**
- Consumes: `tools/build_workbench_seed.py --extract`（解析）与 `render_html`（就地改写）
- Produces: 构建工具改为**改写数据模块**而非 HTML；`tests/test_a1_workbench_source.py` 的 `assert injected == html` 改为对数据模块的逐字节等价断言。

**Injected Instincts:**
- [ ] `[Instinct: Build-Product-Contract]`: 「内联 const 是构建产物」是本仓既有契约（`test_a1_workbench_source.py:220-251` 的字节等价 + 幂等两条 D 类）。搬迁 MUST 让这两条断言**继续约束真实产物**，不得删改为「文件存在」。
- [ ] `[Instinct: HITL-Gate]`: 本任务会同时改动**构建工具 + 数据模块 + 契约测试**三面，属 Critical 档——先向用户呈报变更面与不可逆风险，拿到确认再动文件。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 种子数据抽取与 A/D 类探针重定向.
> Mode: HITL | Role: TDD Builder
> Goal: 把四个内联数据 const（+ `EMBEDDED_AUDIO`）抽到独立模块，同步改造两个构建工具与 8 个探针，**保持字节等价与幂等两条 D 类契约**。
> Steps:
> 1. 记录基线：`python3 -m pytest tests/test_german_workbench.py tests/test_a1_workbench_source.py -v`。
> 2. 抽取数据模块；`build_workbench_seed.py` / `build_embedded_audio.py` 改为改写该模块。
> 3. 重定向 6 个 `_slice_balanced` 锚点 + 5 个 D 类计数 + `test_a1_workbench_source.py` 的 6 C / 2 D。
> 4. 变异自证：改一个种子词 ⇒ 字节等价断言与计数断言同时变红；复原。
> 5. 跑定向套件，确认用例数守恒。
> Return: 摘要 + 物理凭据（含注入前后 HTML 的 sha256 比对）。"

**Step Breakdown:**
- [ ] **Step 1**: 记录基线
- [ ] **Step 2**: 抽取数据模块（HITL 确认后再动）
- [ ] **Step 3**: 改造两个构建工具
- [ ] **Step 4**: 重定向 13 个探针
- [ ] **Step 5**: 变异自证
- [ ] **Step 6**: 门禁 + 用例数守恒
- [ ] **Step 7**: Physical Evidence Gate
- [ ] **Step 8**: 原子提交（`refactor(c7): extract workbench seed data module`）

---

### Task 5: 大子系统抽取与剩余 A 类锚点重定向 [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]
*(边界决策延后：见 Fog of War Unknown 1 —— 待 Task 3/4 完成后按「逐块锚点数」定)*

**Files:**
- Create: `static/js/wb-*.js`（TTS 链 / wbsync / scope 过滤 / 复习队列 …，具体切分由前置测量决定）
- Modify: `static/german/workbench.html`
- Modify: `tests/test_german_workbench.py`（剩余 ~60 处 A 类锚点）
- Modify: `tests/test_audit_hardening.py:477,775` · `tests/test_exam_domain.py:501`

**Step Breakdown:**
- [ ] **Step 1**: 逐块测量锚点密度（每候选子系统各携带多少 A 类锚点）
- [ ] **Step 2**: HITL 确认切分边界
- [ ] **Step 3**: 抽取单个子系统 + 同批重定向其锚点（**一次一块**，不做大爆炸式重构）
- [ ] **Step 4**: 每块结束跑一次定向套件 + 用例数守恒
- [ ] **Step 5**: 全部块完成后跑全量套件
- [ ] **Step 6**: Physical Evidence Gate
- [ ] **Step 7**: 原子提交（每块一颗）

---

### Task 6: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log` · `docs/reviews/2026-10-16-open-items-backlog.md`（C7 行改「已转计划」/完成态）

**Step Breakdown:**
- [ ] **Step 1: 逐字复刻 CI 门禁命令**：`mypy --strict delector tools`；`mypy --follow-imports=skip tests`；`ruff check .`；`cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] **Step 2: 全量 pytest**（**本任务必须跑全量**，因为拆分触及 11 个测试文件与前端产物，定向套件不足以证明无回归）
- [ ] **Step 3: 探针全集复跑**：`tests/test_probe_wiring_guard.py`（断言每个 `.mjs` 探针都被接线）
- [ ] **Step 4: 用例数守恒核验**：拆分前后全量用例数必须相等（本工作流**不新增业务用例**；只允许因迁移新增的 `tests/test_wb_source.py` 单测）
- [ ] **Step 5: CRLF 卫生**（0 lone LF）
- [ ] **Step 6: 追加 `WORKMEMORY/work.log` DONE 事件**
- [ ] **Step 7: 推送分支并创建 PR**（base=master）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: Task 5 的切分边界]**：每候选子系统的**锚点密度**未逐块测量。切分顺序与粒度 MUST 等 Task 3/4 完成后按实测锚点数决定——不投机拆任务。（判据草案：优先抽「A 类锚点为 0 且 D 类计数为 0」的子系统。）
- **[Unknown 2: WebView / Android 上的 ES Module 加载行为]**：本仓前例——SSE 的 `fetch` + `ReadableStream` 在 Android WebView 上的表现**从未真机验证**（C4 面）。`<script type="module">` 若在 Chaquopy WebView 上不可用，需回退 `<script src>` + 全局命名空间方案。**该验证属 C4，不在本计划内**，但拆分方案 MUST 保留回退路径（即：模块间不得依赖仅 ES Module 才有的语义，如顶层 `import` 循环引用）。
- **[Unknown 3: 拆分后单文件行数/加载扇出是否成为新问题]**：4730 行 → N 个文件的收益未经测量（本仓 `bench_*` 有现成工具可量首屏）。若拆后首屏回退显著，需重新评估。
- **[Unknown 4: 裸箭头表达式体回调不被 `depth_at` 覆盖]**：`tests/wb_source.py` 的 `depth_at` 按**花括号净深度**判定「是否顶层语句」，`setTimeout(() => wbsync.push(), 0)` 这类**无花括号的表达式体回调**不产生花括号 ⇒ 深度仍为 0 ⇒ 抓不到「被塞进回调」。相对原「同一物理行」钉：判别力**无净损失，仅未升**（原钉对该形态同样抓不到）。Task 3/4 迁移 wbsync 相关 A 类锚点时 MUST 把断言消息写成「嵌进块 / 带花括号的子函数或回调」，不得泛称「嵌进块/回调」。（待办：若后续要覆盖该形态，需引入表达式体箭头识别，属新工具，不在本计划内。）

---

## 🚫 Out of Scope

- 不改 `delector/**` 后端任何文件（后端与 workbench 前端无耦合面）。
- 不改入口路径 `static/german/workbench.html`（见 Global Constraints）。
- 不引入任何构建工具（webpack / vite / rollup / esbuild）。
- **不做 C6**：`tests/test_german_workbench.py` 已由本工作流独占，C6（测试文件按被测面切分）在其目标清单中**移除该文件**，只保留 `tests/test_server.py` 与 `tests/test_desktop_shell.py`。
- 不修 C8 批次缺陷（TTS 退避 / 抓取大小闸 / settings 脱敏 / CI 密钥扫描等）——属并行工作流。
- 不新增业务断言；本工作流只做「等价迁移 + 结构性重写」，任何新增断言都必须是为**保持原判别力**所必需。