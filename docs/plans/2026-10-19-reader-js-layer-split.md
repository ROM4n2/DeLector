# reader.js 分层解耦实施计划（第二样本 · 同构复用 writer.js 模板）

> **Goal**: 按 `writer.js`（PR #160）已验证的模板，把 `static/js/reader.js`（1,403 行）里**自洽闭包**的纯格式化簇（9 个符号 / 339 行）切到新的 L1 纯层 `static/js/rd-syntax.js`，`reader.js` 保留视图与编排、具名导出面**逐字冻结**，并把新模块注册进已存在的前端分层机械闸 `tools/check_frontend_layers.py`。
> **Tech Stack**: 原生 ES Modules（零构建）/ Python 3.11 / pytest（Node 仅用于 `node --check` 语法验证）
> **Spec Reference**:
> - `docs/plans/2026-10-19-writer-js-modularization.md`（**模板来源**：Task 1~5 的可复制做法与踩坑清单）
> - 同计划 §Fog of War Unknown 2（**本计划的立项依据**：「`cards.js` / `reader.js` 同构切分收益 —— 判据草案：纯函数行数 / 总行数、探针损伤面」）
> - vault `01-Rules/LAYERED-ARCHITECTURE.md`（分层判据是**依赖方向**；§2 底层定原子上层只加不改；**§3 分层正确性验证 = 「可独立使用」测试**——只有物理移除上层依赖后底层仍能通过测试才算独立，**MUST NOT 以「能编译通过」冒充**）
> - `docs/agents/architecture.md`（前端拓扑与跨端契约）
> **Global Constraints**:
> - **入口与导出面不可变（MUST）**：`static/js/reader.js` 保留原路径与**全部 40 个既有具名导出**（实测：`grep -oP '^export (async )?function \K\w+' static/js/reader.js | wc -l` = 40）。它被 6 处跨模块 import 钉住：`a1_cards.js`(refreshCardCounters) · `a1_hoeren.js`(refreshCardCounters) · `cards.js`(refreshCardCounters) · `main.js`(具名批量) · `search.js`(openReader) · `writer.js`(refreshCardCounters)。
> - **零构建 / 零新依赖（MUST）**：不引入 webpack / vite / rollup / esbuild / npm 包。
- **新模块的 import 白名单（MUST）**：`rd-syntax.js` 只允许 `./core.js`，且 **MUST 一并 import `esc` / `jsAttr` / `normalizeCefrPct` 三个** —— 少一个不会让闸变红，只会让模块带未定义名上线。
> - **探针判别力不可降级（MUST）**：迁移任何探针 MUST 走 `tests/wb_source.py::read_source()` 的多文件拼接读法；seam **只扩到「该探针真正锚定的符号将要搬到」的文件**，MUST NOT 顺手拓宽（writer.js 实操教训：一律拓宽会静默中和 `test_server_android_fallback.py` 的 `api_key` OR 链第一子句）。
> - **零静默失败（MUST）**：抽取只搬实现，不得吞 `catch`、不得把失败路径改成 `console.log`。`reader.js` 现有 `notify(...)`（用户可见）与 `console.error(...)`（服务端可查）双轨 MUST 原样保留（用「提示/错误行集合进出相等」证明）。
> - **文件契约**：全文件 UTF-8 **CRLF**（0 lone LF）；`ruff check .` 零告警；`mypy --strict delector tools` 与 `mypy --follow-imports=skip tests` 零错误。
> - **用例数**：本计划的搬迁动作**不新增业务断言**；新增用例只允许出现在 `tests/test_frontend_layers.py`（闸的纳管面验收）与 `tests/test_reader_layer_split.py`（本拆分的等价性验收）。
> - **并行占面**：独占 `static/js/reader.js`、`static/js/rd-syntax.js`（新）、`tools/check_frontend_layers.py`、`tests/test_frontend_layers.py`、`tests/test_reader_layer_split.py`（新）、`tests/test_server_android_fallback.py`（仅 seam 一行）。MUST NOT 触碰 `static/js/cards.js`（见 Fog of War）。
> **Branch**: `refactor/reader-js-layer-split` —— 自 `master` 切出，独立 git worktree 隔离；全套门禁全绿后提 PR 合入，严禁直推 `master`。

---

## 🏛️ Decisions So Far

### D1 · 目标顺序：**先 reader.js，cards.js 后置**（实测判据，非偏好）

计划自己的判据是「纯函数行数占比 + 探针损伤面（A 类锚点数）」。实测（方法：复用 `tools/check_frontend_layers.py` 的词法分析器取**花括号净深度 0** 的顶层声明，span = 本声明起始行 .. 下一顶层声明起始行 - 1；纯 = 该 span 内无 DOM/网络/提示/计时器/动态求值标识符）：

| 文件 | 总行 | 顶层声明 | 导出 | 纯行/顶层行 | 纯占比 | 读数站点 | 真 A 类锚点 | 跨文件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`reader.js`** | 1,403 | 48 | 40 | **345 / 1,389** | **24.8%** | **10** | **1** | 6 |
| `cards.js` | 1,335 | 62 | 36 | 128 / 1,307 | 9.8% | **22** | **3** | **14** |
| `writer.js`（已完成样本） | 1,526 | 55 | 39 | 167 / 1,477 | 11.3% | 8 | 1 | 5 |

**三条独立理由都指向 reader.js 先行**：
1. **纯簇是闭包且占比最高**：reader.js 的 9 个纯候选实测**零泄漏**到模块其它符号（唯一外部依赖是 `core.js` 的 `esc`）⇒ 可干净搬为独立模块；cards.js 的 128「纯行」里**大半是模块级状态声明**（`cardSegment`/`undoToastTimer`/`_prepSearchTimer`/`quizState`…），真正的纯函数仅约 8 个 ≈ 75 行（**≈6%**）⇒ 它不是纯层抽取的合适对象。
2. **探针面干净得多**：reader.js 10 处读数站点 / 1 处真 A 类；cards.js **22 处跨 14 个文件** / 3 处真 A 类。
3. **模板第三次应用**：reader.js 与 writer.js 同为「大头文件 + 一个纯函数簇 + 大量 DOM/网络」形状，可直接复用 PR #160 的 Task 序列；cards.js 主要是**视图 + 状态**（13 处 `await api(`），其分解是**另一个设计问题**，留给它自己的计划（见 Fog of War）。

### D2 · 纯簇清单（实测行区间，字节级可核）

| # | 符号 | 行区间 | 行数 | 现为 reader.js 具名导出 |
| --- | --- | --- | --- | --- |
| 1 | `CEFR_LEVELS` | 15 | 1 | 否（内部） |
| 2 | `safeCefr` | 16 | 1 | 否（内部；被 `renderReaderHeatbar` 用） |
| 3 | `safeTokens` | 17-19 | 3 | 否（内部） |
| 4 | `renderMiniBar` | 89-111 | 23 | **是** |
| 5 | `renderFelderSpectrum` | 969-1015 | 47 | **是** |
| 6 | `renderDetailedFelderGrid` | 1016-1070 | 55 | **是** |
| 7 | `renderClauseTreeNode` | 1071-1118 | 48 | **是** |
| 8 | `computeArticleSyntaxStats` | 1203-1265 | 63 | **是** |
| 9 | `renderRadarSvg` | 1266-1363 | 98 | **是** |
| | **合计** | | **339** | 6 个需继续对外提供 |

**候选集合闭包证明（实测）**：9 个 span 的 token 全集里，除 `esc`(core.js) 与 JS 内建外，**无任何其它 reader.js 模块符号** ⇒ 新模块需 `import { esc, jsAttr, normalizeCefrPct } from './core.js'` —— **三个都需要**（`jsAttr` 与 `normalizeCefrPct` 由独立评审实测抓出，见下方「评审修正」）；实测 `api` / `notify` / `Companion` / `ShadowPlayer` / `DEFAULT_TIMEOUT_MS` 均未被候选区使用。

**留下的 5 个具名消费者（仍在 `reader.js`，改为从新模块 import）**：`renderReaderHeatbar`→`safeCefr` · `loadArticles`→`renderMiniBar` · `_openReaderBody`→`renderFelderSpectrum` · `openSyntaxDrawerForSentence`→`computeArticleSyntaxStats`/`renderClauseTreeNode`/`renderDetailedFelderGrid` · `saveAndRenderSyntaxRadar`→`renderRadarSvg`。

### D3 · `reader.js` 唯一真 A 类锚点**零损伤**
`tests/test_server_android_fallback.py:617` 切片 `reader_src.index("export async function aiNoteAssist")` → `saveCurrentNote`。这两个目标（行 881 / 924）属 **DOM/网络**，本计划**不移**它们 ⇒ 该锚点天然不受影响；仍 MUST 用变异自证证明这一点（不得只靠推理）。

### D4 · 不抽 L2（持久化层）
`reader.js` 有 16 处 `await api(`。它们**分散**在视图函数体内（`inspect` 216 行、`_openReaderBody` 95 行等），不像 `writer.js` 那样是「薄且可命名的端点调用」⇒ 抽 L2 会把大段视图逻辑连带搬走，收益与风险倒挂。**本计划只做 L1**；L2 是否值得做登记进 Fog of War。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 把 `rd-syntax.js` 注册进分层闸（gate-as-spec，先红后绿） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/check_frontend_layers.py`（`LAYER_SPEC` 加一条；`MUTABLE_STATE_MODULES` 是否含新模块由 Task 2 实测决定）
- Test: `tests/test_frontend_layers.py`

**Interfaces:**
- Consumes: `LAYER_SPEC: Dict[str, LayerSpec]`、`BAN_IDENTIFIERS`（均已存在）
- Produces: `LAYER_SPEC["rd-syntax.js"] = LayerSpec(layer="L1 纯格式化层", ban_rules=("dom","network","toast","timer","dynamic-eval"), allowed_imports=("./core.js",))`

**Injected Instincts:**
- [x] `[Instinct: Gate-Before-Code]`: 闸先声明目标形态 ⇒ 建模块前该声明必须让闸**变红**（`missing-layer-module`）。这是「闸是规范不是描述」的落地，MUST 留下红灯退出码凭据。
- [x] `[Instinct: No-Narrowing]`: 新模块的 `ban_rules` MUST 与 `wr-format.js` **完全一致**（同一个 L1 定义），MUST NOT 为了绿灯放宽任何一条。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 把 rd-syntax.js 注册进分层闸。Mode: AFK | Role: TDD Builder。
> Steps: ① 记基线 `python3 tools/check_frontend_layers.py`（应 exit 0）与 `pytest tests/test_frontend_layers.py -q`（记用例数）。
> ② 在 `LAYER_SPEC` 加 `rd-syntax.js`（ban_rules 与 `wr-format.js` 逐字相同）。
> ③ 跑闸 → MUST exit 1 且报 `missing-layer-module`（红灯凭据）。
> ④ 在 `tests/test_frontend_layers.py` 加：a) 合成夹具证明 `rd-syntax.js` 注入 `document.` ⇒ 红；b) 真树集成断言（`js_dir` 夹具已复制该文件后自然覆盖）。
> Return: 摘要 + 物理凭据（两次退出码 + 用例数）。"

**Step Breakdown:**
- [x] **Step 1**: 基线 —— 闸 exit **0**（`PASS`）；`tests/test_frontend_layers.py` **58 passed**
- [x] **Step 2**: `LAYER_SPEC` 注册 `rd-syntax.js`（`layer`/`ban_rules`/`allowed_imports` 与 `wr-format.js` **逐字节相同**）；`MUTABLE_STATE_MODULES` 一并纳入（比计划更严，属收紧）
- [x] **Step 3**: **红灯凭据** —— 闸 exit **1**，`- static/js/rd-syntax.js:1:missing-layer-module:声明的分层模块不存在`（编排者与评审各自独立复现）
- [x] **Step 4**: 补 5 条用例（1 条 No-Narrowing 现已绿 + 4 条预期红待 Task 2）；用例数 58 → **63**
- [x] **Step 5**: 门禁 —— `ruff check .` exit 0 · `mypy --strict delector tools` exit 0（118 files）· 两文件 0 lone LF
- [x] **Step 6**: **独立评审 PASS**（六项逐条独立复现：RED 归属、crux 绿灯可达性、无放松、断言不可被替代机制满足、fixture 无静默跳过、`len(LAYER_SPEC)` 改写可接受）；cherry-pick 为 `4701c1f`
- [x] **Step 7（评审修正）**: 评审在复现 crux 时抓到本计划**两处事实性错误**（`import` 只需 `esc` ✗；`export` 前缀 5 处 ✗）—— 已在本文件修正，见「评审修正」一节

---

### Task 2: 抽出 `static/js/rd-syntax.js`（L1 纯层，339 行闭包） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/js/rd-syntax.js`
- Modify: `static/js/reader.js:15-19,89-111,969-1118,1203-1363`
- Test: `tests/test_reader_layer_split.py`（新）

**Interfaces:**
- Consumes: `core.js::{esc, jsAttr, normalizeCefrPct}` —— **三个都必须 import**。`esc` 是 HTML 转义（5 条 `String.replace`）；`jsAttr` 是 JS 属性位转义（数值位刻意不用它，见 reader.js:9-14 的增长注释）；`normalizeCefrPct` 归一 CEFR 百分比。⚠️ **闸无法发现未定义标识符** —— 少 import 一个不会变红，只会让模块带未定义名上线（评审发现）。
- Produces（签名与 `reader.js` 现状**逐字相同**，行区间见 D2）:
  ```js
  export const CEFR_LEVELS;                                  // 白名单档位
  export function safeCefr(v);                               // 收敛到白名单档位
  export function safeTokens(v);                             // 收敛为纯数字数组
  export function renderMiniBar(stats);                      // 23 行
  export function renderFelderSpectrum(topology, sentId);    // 47 行
  export function renderDetailedFelderGrid(topology);        // 55 行
  export function renderClauseTreeNode(node, depth, sentId); // 48 行
  export function computeArticleSyntaxStats(sentences);      // 63 行
  export function renderRadarSvg(current, historical);       // 98 行
  ```
- **层级硬契约（MUST）**：零 DOM / 零网络（含 `api(`）/ 零提示 / 零计时器 / 零动态求值；**零顶层 `let`/`var`**（无可变模块状态）；唯一允许的 import 是 `./core.js` 的 `esc`。

**Injected Instincts:**
- [x] `[Instinct: Byte-Equality-Or-Explain]`: 搬走的 339 行 MUST **逐字节等于**原处内容（除缩进归一与 **3** 处 `export ` 前缀 —— 仅 `CEFR_LEVELS`/`safeCefr`/`safeTokens` 需加；其余 6 处源码起始行本就带 `export function`。原计划写「5 处」是笔误，由独立评审实测纠正）；任何语义改写都要在提交信息里写明理由。用确定性切片脚本（对 9 个行区间各做内容断言，切歪即抛）产出，MUST NOT 手抄。
- [x] `[Instinct: Closed-Set]`: 建模块后 MUST 复跑闭包检查——新模块里 MUST NOT 出现任何 `reader.js` 的模块符号（证明 D2 的闭包结论在搬运后仍成立）。
- [x] `[Instinct: XSS-Defence-Preserved]`: 这些渲染器是**恶意 backup 数据流的 sink 侧防线**（`reader.js:9-14` 注释明说：`stats`/`tokens`/`clause_tree` 可携带任意字符串，模板全部经 `innerHTML` 落 DOM，靠 `Number()` 收敛数值位 + CEFR 白名单 + token_ids 纯数字 JSON）。搬迁 MUST 保留这三道收敛，MUST NOT 「顺手简化」。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 抽出 static/js/rd-syntax.js。Mode: AFK | Role: TDD Builder。
> Steps: ① 记基线：`grep -c '^export ' static/js/reader.js`、`wc -l static/js/reader.js`、定向套件用例数。
> ② 写确定性切片脚本：按 D2 的 9 个行区间各做内容断言后切出，拼成 `rd-syntax.js`（加 `import { esc } from './core.js';` 与 5 处 `export ` 前缀）。
> ③ 逐字节等价证明：断言新模块可直接给出与原处相同的文本（仅两类已枚举差异）。
> ④ 闭包复验：新模块 token 里不得出现 reader.js 的其它模块符号。
> ⑤ 跑闸 → 该模块 MUST 转绿。
> Return: 摘要 + 物理凭据（等价证明输出 + 闸退出码 + 行数）。"

**Step Breakdown:**
- [ ] **Step 1**: 记基线（行数 / 导出数 / 用例数）
- [ ] **Step 2**: 确定性切片脚本产出 `rd-syntax.js`
- [ ] **Step 3**: 逐字节等价证明（9/9 块）
- [ ] **Step 4**: 闭包复验（无 reader.js 符号泄漏）
- [ ] **Step 5**: 闸转绿（Task 1 的红灯消解）
- [ ] **Step 6**: Physical Evidence Gate + 原子提交（`refactor(rd): extract pure syntax renderers to rd-syntax.js`）

---

### Task 3: `reader.js` 接线 + 导出面冻结 + 5 个消费者改向 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/reader.js`（删原定义，加 import + `export { … }`；5 处消费者改为使用导入名）

**Interfaces:**
- Consumes: `rd-syntax.js` 的 9 个导出
- Produces: `reader.js` 具名导出集合**逐字不变（40 个）**；`reader.js` 内部仍能调用这些符号
  ```js
  import { CEFR_LEVELS, safeCefr, safeTokens, renderMiniBar, renderFelderSpectrum,
           renderDetailedFelderGrid, renderClauseTreeNode, computeArticleSyntaxStats,
           renderRadarSvg } from './rd-syntax.js';
  export { renderMiniBar, renderFelderSpectrum, renderDetailedFelderGrid,
           renderClauseTreeNode, computeArticleSyntaxStats, renderRadarSvg };
  ```
  （`CEFR_LEVELS` / `safeCefr` / `safeTokens` 现状非导出，故只 import 不 re-export）

**Injected Instincts:**
- [x] `[Instinct: Export-Surface-Frozen]`: MUST 用 `tests/test_frontend_module_graph.py` 自带的 `_parse_own_exports` + `_parse_named_reexports` 解析器比对 master 与现状（writer.js 做法）⇒ 缺失 0、新增 0。
- [x] `[Instinct: No-Reexport-Shim-Cycle]`: `rd-syntax.js` MUST NOT 反向 import `reader.js`（避免 Façade ⇄ Slice 环）；闸的 `reverse-dependency` 规则覆盖此点，MUST 跑一次验证。
- [x] `[Instinct: ESM-Link-Time]`: 重名 = 链接期 SyntaxError 拖垮整图。MUST 先做「新模块导出名 ∩ reader.js 本地声明名」交集检查（writer.js 实操曾因此改名 `restoreEssayVersionRemote`）；`node --check`（复制为 `.mjs`）为快验证。
- [x] `[Instinct: Error-Rail-Preserved]`: `notify(` / `alert(` / `console.error(` 行集合进出相等（丢失 0、新增 0）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: reader.js 接线 + 导出面冻结。Mode: AFK | Role: TDD Builder。
> Steps: ① 重名交集检查：`rd-syntax.js` 导出名 ∩ `reader.js` 顶层声明名 MUST 为空（非空则改名并记录，writer.js 曾因此改名 `restoreEssayVersionRemote`）。
> ② 删 `reader.js` 的 9 处原定义，加 import + `export { … }`（只 re-export 现状已导出的 6 个）。
> ③ 5 个消费者（`renderReaderHeatbar`/`loadArticles`/`_openReaderBody`/`openSyntaxDrawerForSentence`/`saveAndRenderSyntaxRadar`）逐个核到未漏。
> ④ 导出面冻结核验：用 `tests/test_frontend_module_graph.py` 的解析器比对 master 与现状 ⇒ 缺失 0、新增 0。`node --check`（复制为 .mjs）。
> ⑤ 错误轨保真：`grep -nE 'notify\(|alert\(|console\.error\('` 行集合进出相等。
> Return: 摘要 + 物理凭据（导出面 diff、node --check 退出码、错误轨行数）。"

**Step Breakdown:**
- [ ] **Step 1**: 重名交集检查（0 交集；否则改名并记录）
- [ ] **Step 2**: `reader.js` 删定义 + import + re-export
- [ ] **Step 3**: 5 个消费者改向（逐个核未漏）
- [ ] **Step 4**: 导出面冻结核验（40 = 40）+ `node --check`
- [ ] **Step 5**: 错误轨保真（行集合相等）
- [ ] **Step 6**: 门禁 + 用例数 + Physical Evidence Gate
- [ ] **Step 7**: 原子提交（`refactor(rd): wire reader.js to the pure syntax layer`）

---

### Task 4: 「可独立使用」验收 + 探针 seam + 变异自证 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_reader_layer_split.py`
- Modify: `tests/test_server_android_fallback.py`（仅 seam 一行；**仅当**实测证明需要）

**Interfaces:**
- Consumes: `tests/wb_source.py::read_source` / `decl_body`；`tools/check_frontend_layers.py::collect_violations`
- Produces（`tests/test_reader_layer_split.py`）:
  ```python
  def test_rd_syntax_is_an_independent_module() -> None:   # node --check + import 白名单仅 core.js
  def test_rd_syntax_does_not_reference_reader_js() -> None:  # token 级：无 reader.js 符号
  def test_rd_syntax_candidate_set_is_closed() -> None:    # 闭包：除 esc/JS 内建外无外部模块符号
  def test_rd_syntax_has_no_mutable_module_state() -> None:   # 顶层 let/var 计数 = 0
  ```
- 时长上限：单模块级检查，MUST 秒级、确定性、不依赖仓库状态（夹具走 `tmp_path` 或只读静态面）。

**Injected Instincts:**
- [x] `[Instinct: Independent-Usability]`（**vault `LAYERED-ARCHITECTURE.md` §3 MUST**）: 「去掉上层，这一层还能否正常工作」MUST 被**物理执行**，MUST NOT 以「能编译通过」冒充。落地形态：`rd-syntax.js` 必须能**单独**通过 `node --check` 与「其 import 白名单仅 `./core.js`」两条独立检验；并在 `tests/test_reader_layer_split.py` 里断言它**不引用** `reader.js` 的任何符号。
- [x] `[Instinct: Seam-Minimal]`: 先跑一次 D3 的切片探针，**若绿灯则一行都不改**（reader.js 唯一的 A 类锚点目标不搬 ⇒ 预期零改动）；MUST NOT 预防性拓宽 seam。
- [x] `[Instinct: Mutation-Proof]`: 每条新断言 MUST 有变异自证（注入 ⇒ 红 ⇒ 复原 ⇒ 绿，且**报出期望的断言名/规则名**）；只断言「exit 1」不算证明。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 独立可用性验收 + seam + 变异自证。Mode: AFK | Role: TDD Builder。
> Steps: ① 写 `tests/test_reader_layer_split.py`（四个 Produces 函数）。
> ② 先跑一次 `tests/test_server_android_fallback.py`，确认 reader.js 的切片探针仍绿 ⇒ seam **零改动**（预期如此；不预防性拓宽）。
> ③ 变异自证 ≥4 条：新模块注入 `document.` / 注入顶层 `let` / 重新定义已迁出符号 / 破坏 `esc` 引用 —— 各断言 MUST 以**期望的规则名或断言名**变红，复原后绿。
> ④ 全量套件（单条串行）+ 用例数核验（如实报两个数）。
> Return: 摘要 + 物理凭据（每条变异的注入后 exit、报出的断言名、复原后 exit）。"

**Step Breakdown:**
- [ ] **Step 1**: 写 `tests/test_reader_layer_split.py`（独立可用性 + 不引用 reader.js + 闭包三条）
- [ ] **Step 2**: 跑 D3 切片探针一次，记录是否需要改 seam
- [ ] **Step 3**: 变异自证（≥4 条：新模块注入 DOM / 注入 `let` / 重新定义已迁出符号 / 破坏 `esc` 引用）
- [ ] **Step 4**: 全量套件 + 用例数核验（如实报两个数）
- [ ] **Step 5**: Physical Evidence Gate + 原子提交（`test(rd): independent-usability and seam proof`）

---

### Task 5: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log` · `docs/plans/2026-10-19-reader-js-layer-split.md`（Fog of War 核销）

**Interfaces:**
- Consumes: 六道 Python 闸 + `ruff` + 两个 `mypy` + `go test` + `gofmt`
- Produces: 一条 PR（base=master）+ `WORKMEMORY/work.log` 的 DONE 事件（≤4KB）；Fog of War 逐条核销或转登记

**Injected Instincts:**
- [x] `[Instinct: Serial-Only]`: 全量 pytest MUST **单条串行** —— 并发跑会撞 `tests/conftest.py` 的仓库根 DB 守卫（2026-10-19 实测，属共享数据目录争用而非代码缺陷）。
- [x] `[Instinct: Verify-It-Really-Ran]`: 「CI 绿」不等於「新断言被执行」。MUST 用 `gh api repos/<o>/<r>/actions/jobs/<id> --jq '.steps[]'` 逐步骤确认新步骤出现在清单里且为 success。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 门禁全景复核与交付 PR。Mode: AFK | Role: Cleaner。
> Steps: 逐字复刻 CI 门禁命令 → 全量 pytest（**单条串行**）→ 用例数核验 → CRLF 卫生 → work.log DONE 事件 → 推分支建 PR → 用 `gh api .../actions/jobs/<id>` 逐步骤确认新断言在 CI 真被执行（不只「exit 0」）。
> Return: 摘要 + 物理凭据（各门禁退出码、全量 passed/skipped/collected 三数、CI 步骤清单）。"

**Step Breakdown:**
- [ ] **Step 1**: 逐字复刻 CI 门禁命令（六道 Python 闸 + ruff + 两个 mypy + Go 8 包 + gofmt）
- [ ] **Step 2**: 全量 pytest（**单条串行**；并发跑会撞 `tests/conftest.py` 的仓库根 DB 守卫，2026-10-19 实测教训）
- [ ] **Step 3**: 用例数核验（拆分前后如实报两个数 + 新增闸用例数）
- [ ] **Step 4**: CRLF 卫生（全部改动文件 0 lone LF）
- [ ] **Step 5**: `WORKMEMORY/work.log` DONE 事件（≤4KB）
- [ ] **Step 6**: 推送分支并创建 PR（base=master）；用 `gh api .../actions/jobs/<id>` 逐步骤确认 CI 真跑了新断言（不只「exit 0」）

---

## 🔎 评审修正（Task 1 · 独立评审记录，2026-10-19）

Task 1 的独立评审在**独立复现 crux**（用 D2 行区间重建 `rd-syntax.js` 验证新用例可达绿灯）时，抓到本计划**两处事实性错误**。两处都已实测复核并修正：

| # | 计划原文（错） | 实测真相 | 后果 |
| --- | --- | --- | --- |
| 1 | 「新模块只需 `import { esc } from './core.js'`」 | 真外部依赖是 **`esc` + `jsAttr` + `normalizeCefrPct`**（三者均出自 `core.js`） | 照错发货会让 `rd-syntax.js` 带**两个未定义标识符**上线；**闸无法发现**（它不解析标识符绑定）⇒ 只能靠评审/人工 |
| 2 | 「5 处 `export ` 前缀」 | 只有 **3** 处（`CEFR_LEVELS`/`safeCefr`/`safeTokens`）；其余 6 处起始行本就带 `export function` | 无实质后果（切片脚本以内容断言为准），但需纠正以免误导 |

**根因（值得记的形态）**：第 1 条的错来自**手工挑选的探测清单**——编排者当时只检查了 `esc/api/notify/Companion/ShadowPlayer/DEFAULT_TIMEOUT_MS` 这几个**猜出来的**符号，而没从 token 流**穷举**自由标识符。同一天内这是第三次「自建的验证工具带盲点、却给出看起来合理的结论」（前两次：把嵌套局部声明当顶层算纯占比；按 `git grep` 命中行而非断言分类 idiom）。**纪律**：依赖面/引用面这类结论 MUST 从 token 流穷举后与 `core.js` 的导出清单求交，MUST NOT 靠手挑清单。

**评审的其余结论**：RED 归属airtight（对照父提交 `d8135f0` 的闸同树 exit 0）；无任何放松（`BAN_IDENTIFIERS` 五项全未变，`git show -U0` 只有一处「移除并替换为超集」）；新断言不可被替代机制满足（四条禁用式变异 M1/M2/M3/M6 各自只打红对应那条）；fixture 的「只复制已存在模块」**无静默跳过**（缺文件时 `FileNotFoundError` 响亮报错、全文件零 `skip/xfail`、删掉既有模块会 32 failed）。

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: `cards.js` 的切分设计]**：实测它**不是纯层抽取的合适对象**（纯函数仅 ≈75 行 / 6%；128「纯行」里大半是模块级状态声明；13 处 `await api(`；22 处读数站点跨 **14** 个文件；3 处真 A 类锚点：`test_german_workbench.py:415` 切 `backupLocalStorageKeys`、`test_server_backup_restore.py:441` 切 `downloadBackupJson`、`:480` 切 `uploadBackupJson`）。它的分解要回答的是**「状态与视图怎么分」**（`cardSegment`/`cardViewMode`/`deckIndex`/`quizState`/`_prep*` 一族 + 词卡/复习/测验/介词矩阵四块 UI 是否该切文件），与 writer.js/reader.js 的「抽纯簇」是**两个不同的设计问题** ⇒ MUST 另立计划，MUST NOT 塞进本计划顺手做。
- **[Unknown 2: `reader.js` 是否值得另抽 L2]**：16 处 `await api(` 分散在 `inspect`(216 行) / `_openReaderBody`(95 行) / `saveVocab` / `savePrepCollocation` / `saveGrammar` / `loadArticleNotes` / `aiNoteAssist` 等视图函数体内。抽 L2 需要先测量「可命名端点数 / 调用点数」，writer.js 是 14:17。本计划只做 L1；L2 的取舍等 L1 落地后按实测决定。
- **[Unknown 3: 分层闸的纳管面]**：闸现纳 `wr-format.js` / `wr-api.js` / 「本计划加的 `rd-syntax.js`」共 3 个模块。是否继续按「每个被拆文件产出一个模块」线性增长，还是改成「按目录/前缀声明整层」，**待三个样本齐备后**按维护成本决定；本计划不扩到全量（`static/js` 现 33 个模块，全量纳管会大面积假红）。
- **[Unknown 4: `renderReaderHeatbar` 为何不纯]**：实测它引用 `safeCefr`（纯）但自身被判非纯（DOM）。是否可再切一层（先算数据、再由极薄的 DOM 壳落屏）值得评估，但属**第二跳**，本计划不做。
- **[Unknown 5: Android WebView 多模块加载]**：本次再增 1 个模块（累计 `wr-format`/`wr-api`/`rd-syntax`）。真机验证属 C4 面（用户已指示暂缓），本计划不引入仅 ES Module 才有的语义（无循环 import、无顶层 await），保持回退路径可用。

---

## 🚫 Out of Scope

- **不做 `cards.js` 的任何改动**（见 Fog of War Unknown 1）。
- 不动 `static/js/writer.js` / `wr-format.js` / `wr-api.js`（已完成，PR #160）。
- 不动任何后端文件（`delector/**`）。
- 不引入任何构建工具或 npm 依赖（零构建立场）。
- 不改变任何端点或 hook 的请求/响应形状（纯前端搬家）。
- 不新增业务断言；新增测试只允许出现在 `tests/test_frontend_layers.py` 与 `tests/test_reader_layer_split.py`。
- 不改 `reader.js` 的 16 处 `await api(` 调用（D4）。
- 不改造读者对 `reader.js` 的 6 处 import（导出面冻结即保住它们）。