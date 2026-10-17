---
to: any
from: deepseek-v4.1-flash__hermes
created: 2026-10-18 00:25
role: IMPLEMENT
status: open
---
# Handoff: C7 —— `static/german/workbench.html` 拆分（含 140 个耦合探针的现代化前置）

> **本包可与另一 agent 并行执行**，但只有一个硬约束：**文件占面不许交叉**（见「并行协调契约」）。请严格遵守。

---

## 任务上下文

**目标**：把 `static/german/workbench.html`（**4730 行单文件 PWA**）拆分为多模块。但它**不是**一个「搬代码」任务——本仓有 **140 个探针**把该文件的内部结构钉成了契约（位置序、行号、计数、字节等价），一拆即大面积红。因此真正的工作量在**探针现代化**，不在拆分本身。

**计划正本（先读这个）**：`docs/plans/2026-10-18-c7-workbench-html-split.md`
—— 已按 dfs-plan schema 写好 6 个 Task（含 Tier/Mode 标记、Files/Interfaces、Subagent Prompt Scaffold、TDD Step Breakdown）。**直接按它执行**，不必重新规划。

**分支**：`refactor/c7-workbench-html-split`（从 `master` 切出，PR 落地，严禁直推 master）。
**基线**：`master` = `c27cf63`（本地已同步 origin，工作区干净）。

### 为什么这条是最可分离的工作流

它的文件占面是**一个自洽域**（workbench 前端产物 + 其专属探针族），与后端（`delector/**`）零交叉。另一路工作流做的是后端缺陷修复（C8）与测试文件归属切分（C6），三者只在一个点上曾经重叠，已按文件切开（见下）。

---

## 已完成（含证据：实测命令与结果）

### 1. 探针盘点已完成（**这是本包最值钱的产出，实测非引述**）

对 `tests/` 全目录扫描 + 读取 13 个 `tools/wb_*.mjs`，共定位 **140 个耦合探针**：

| 类 | 含义 | 数量 | 分布 |
| --- | --- | --- | --- |
| **A** | 全文相对位置序 / 标记切片（`split(marker)[1].split(marker2)[0]`、`_top_fn_segment`、`_slice_balanced`、跨声明 `index(a) < index(b)`） | **91** | `test_german_workbench.py` **77** · `test_wb_pair_persist_probe.py` 1 · `tools/wb_*.mjs` **13** |
| **B** | 行号钉（`splitlines()` 下标；要求两段源码在**同一物理行**） | **4** | 全在 `test_frontend_module_graph.py:388-433` |
| **C** | 内容存在性（子串/正则） | **21** | `test_workbench_tokens.py` 7 · `test_a1_workbench_source.py` 6 · `test_german_workbench.py` 5 · `test_audit_hardening.py` 2 · `test_exam_domain.py` 1 |
| **D** | 尺寸/结构/计数/字节等价 | **12** | `test_german_workbench.py` 7 · `test_a1_workbench_source.py` 2 · 探针注册表 1 · 2 个构建脚本 |
| **E** | 不受影响（路由字符串 / iframe / docstring / 注释） | **12** | 分散 |

**两个混合型（`C+A`，实际按 A 处理）**：`tests/test_workbench_tokens.py:86-105`、`tests/test_audit_hardening.py:775-782`。

**据 `workbench.html` 字符串命中的测试文件（11 个）**：
`test_german_workbench.py` 28 处 · `test_workbench_tokens.py` 20 · `test_a1_workbench_source.py` 7 · `test_exam_domain.py` 4 · `test_frontend_guards.py` 3 · `test_frontend_module_graph.py` 3 · `test_audit_hardening.py` 2 · `test_encounter_ui_probes.py` 2 · `test_cards_workbench_no_review_probe.py` 1 · `test_encounter_addcard.py` 1 · `test_wb_pair_persist_probe.py` 1

### 2. **最硬的一条事实：13 个 `tools/wb_*.mjs` 探针会直接崩**

它们各自 `readFileSync(workbench.html)` 后按标记做**大括号配平切片**；声明一旦搬走就抛 `"找不到声明 const …"`，导致 6 个 pytest 包装用例同时红：

| 探针 | 切片目标（行号为实测） |
| --- | --- |
| `tools/wb_a1_bootstrap_probe.mjs` | `:35,100,113` A1 引导相关 const/fn |
| `tools/wb_merge_probe.mjs` | `:22,74,90` `normHw` / `applyMerge` / `migrateSeedIdAliases` |
| `tools/wb_queue_probe.mjs` | `:29,80,93,105` SEED/CORE const + 队列 fns |
| `tools/wb_tags_probe.mjs` | `:26,72,84` CORE const + 标签 fns |
| `tools/wb_sync_probe.mjs` | `:33,71` `const wbsync` |
| `tools/wb_pair_persist_probe.mjs` | `:33,69` `const wbsync` |
| `tools/wb_pair_push_probe.mjs` | `:34,70` `const wbsync` |
| `tools/wb_phone_pull_probe.mjs` | `:32,68` `const wbsync` |
| `tools/wb_phone_pull_silent_probe.mjs` | `:29` 整读 |
| `tools/wb_rtc_connect_probe.mjs` | `:34,70` `const wbsync` |
| `tools/wb_rtc_reconnect_probe.mjs` | `:35,71` `const wbsync` |
| `tools/wb_rich_backfill_probe.mjs` | `:32,77,91` A2/B1 同步 fns |
| `tools/wb_reader_rich_backfill_probe.mjs` | `:33,80` `syncReaderCardsFromServer` |

（`tools/cards_workbench_no_review_probe.mjs:258` 只硬编码路由字符串，**不受影响**。）

### 3. 入口路径**不可改名**（5 处路由字符串钉死）

- `static/index.html` 的 `data-src="/german/workbench.html"`
- `static/js/main.js` 的 `ensureGermanWorkbench`（`getElementById("german-workbench-frame")`）
- `tests/test_frontend_guards.py:42`
- `tests/test_cards_workbench_no_review_probe.py:90`
- `tools/cards_workbench_no_review_probe.mjs:258`

⇒ 拆分后的形态必须 = **同一路径的薄壳 HTML + `<script type="module">`**。保持路径不变，E 类 12 个探针全绿，破坏面被压缩在 A/B 两类内。

### 4. 构建工具与产物契约

`tools/build_workbench_seed.py`（`:47,94,292`）与 `tools/build_embedded_audio.py`（`:31,88`）会**就地改写** `workbench.html` 里的内联 const（`SEED_WORDS` / `CORE_WORD_SEED_IDS` / `CORE_CUSTOM_WORDS` / `SEED_ID_ALIASES` / `EMBEDDED_AUDIO`）。`tests/test_a1_workbench_source.py:220-251` 用**逐字节等价 + 幂等**两条 D 类断言把这个契约钉住了——搬走数据就必须同步改这两个构建工具。

### 5. 迁移依赖顺序（实测得出，按此顺序做才不会互相掩盖）

1. `tests/test_frontend_module_graph.py` —— **唯一的 B 类文件**，行号钉必须先结构化（没有它，任何插入/删除都会红，无法判断是不是自己造成的）。
2. `tests/test_german_workbench.py` —— 77 个 A 类，体量最大。
3. `tools/wb_*.mjs`（13 个）—— 必须在产物搬迁**之前**改造，否则一拆就同时崩且无归因信息。
4. `tests/test_workbench_tokens.py`（7 C + 1 hybrid A）→ 重定向到抽出的 CSS。
5. `tests/test_a1_workbench_source.py`（6 C + 2 D）→ 连同两个构建工具一起改。
6. `tests/test_audit_hardening.py:477,775` + `tests/test_exam_domain.py:501`（3 C）。
7. 探针包装层复跑：`test_wb_pair_persist_probe.py` / `test_probe_wiring_guard.py` / `probe_runner.py` / `probe_json_contract.py`。

> **重要边界**：本仓的文件是仓库副本，我方的 worktree 与主检出 `tests/` 内容一致，未做任何编辑。**本次侦察全程只读**：未改文件、未提交。

---

## 未完成 / 下一步

**下一步就是执行 `docs/plans/2026-10-18-c7-workbench-html-split.md` 的 Task 1 → Task 6。** 该计划已把上表直接编译成可派发的任务：

- **Task 1**（Tier 2 / AFK）：建 `tests/wb_source.py` 探针读取公共层（`read_source` / `segment` / `decl_body` / `line_of` / `same_line`）+ 结构化 B 类 4 处行号钉。**这是后续所有迁移的写法基线，必须第一个做。**
- **Task 2**（Tier 2 / AFK）：13 个 `.mjs` 探针加 `SRC_ROOT` + `sliceDecl()`，要求新旧输出 JSON **逐字相等**（零行为漂移）。
- **Task 3**（Tier 2 / AFK）：**首次真实拆分 = 抽 CSS**（损伤面最小：8 个探针），用它验证迁移模板。
- **Task 4**（Tier 3 / HITL）：抽种子数据模块 + 同步改两个构建工具 + 13 个探针。**动文件前先呈报变更面拿确认。**
- **Task 5**（Tier 3 / HITL）：大子系统抽取。**边界决策在运行时做**（见计划 Fog of War Unknown 1）——先逐块测量锚点密度，再定顺序与粒度；一次一块，不做大爆炸重构。
- **Task 6**（Tier 1 / AFK）：门禁复核（**必须跑全量 pytest**）+ 用例数守恒核验 + PR。

**验收判据（硬）**：
1. 全量 pytest 用例数**守恒**（本工作流不新增业务用例；只允许新增 `tests/wb_source.py` 自身的单测）。
2. 每条被重写的 A/D 类断言都附**变异自证**（把原断言要抓的事实破坏掉 ⇒ 断言变红 ⇒ 复原）。
3. 入口路径 `static/german/workbench.html` 未被改名/迁移。
4. 13 个 `.mjs` 探针在新布局下**全部正常退出 0**（不是 skip）。

---

## 风险与坑

1. **把 A 类降级成 C 类是本次最大的陷阱**。「位置序断言在拆分后不好写」的惯性解法是改成 `assert "xxx" in src` —— 这会让真红变假绿，正是本仓记过在案的死测事故形态（`PROJECT_OVERVIEW.md` 红线 11）。**判别力只许升不许降**；若某断言确实无法保持，写进包内响应节说明理由，不要静默降级。
2. **先改探针、后动产物**。反过来做的话，一拆瞬间 13 个 mjs 探针 + 77 个 A 类同时红，红海一片无法归因是「迁移没做完」还是「真回归」。
3. **`segment()` 类工具禁止返回空串**。找不到标记必须抛错并打印所查标记原文——空串会让下游 `in` 断言静默通过（假绿）。
4. **B 类那 4 处特别阴**：`test_frontend_module_graph.py:401-405` 要求 `wbsync.push()` 与 `function saveX() {` 落在**同一物理行**。任何格式化/换行调整都会红，且错误信息不指向真正的成因。必须先结构化它。
5. **构建工具的就地改写**：`build_workbench_seed.py --extract` 与 `render_html` 会重写 HTML。抽数据模块时若漏改这两个工具，`test_a1_workbench_source.py:220` 的**逐字节等价**断言会红，而直觉会误判为「测试坏了」。
6. **Android/WebView 上 `<script type="module">` 未验证**（C4 面，本计划不解决）。因此模块间**不得**引入仅 ES Module 才存在的语义（顶层 `import` 循环引用、`import.meta`），以便必要时整体回退到 `<script src>` + 全局命名空间。
7. **`.gitattributes` CRLF 契约**：全文件 UTF-8 CRLF，0 lone LF。`.js`/`.html` 新增件都要守这条。
8. **本仓空仓库提交纪律**：门禁提交走 `.githooks`，禁 `--no-verify`；commit message 必须用 `-F <file>`，**禁止 `-m`**（引号会提前闭合参数）。

---

## 并行协调契约（**MUST 遵守**）

两路工作流同时在跑，按**文件**切分占面，不许交叉：

| 工作流 | 独占文件 | 禁触 |
| --- | --- | --- |
| **本包（C7）** | `static/german/workbench.html` · `static/js/**`（**2026-10-18 修正：`main.js` 与 `api-types.js` 已划归 C8**——C8 的 settings 来源脱敏改了契约，其前端消费点必须同批修）· `static/css/workbench.css`（新增）· `tools/wb_*.mjs`（13）· `tools/build_workbench_seed.py` · `tools/build_embedded_audio.py` · `tests/test_german_workbench.py` · `tests/test_workbench_tokens.py` · `tests/test_a1_workbench_source.py` · `tests/test_frontend_module_graph.py` · `tests/test_exam_domain.py` · `tests/test_audit_hardening.py` · `tests/test_wb_pair_persist_probe.py` · `tests/test_probe_wiring_guard.py` · `tests/probe_runner.py` · `tests/probe_json_contract.py` | `tests/test_server.py` · `tests/test_desktop_shell.py` · `delector/**` · `.github/**` |
| C8（后端缺陷，本侧执行） | `delector/services/tts.py` · `delector/routes/encounter.py` · `delector/routes/main.py` · `delector/core/security.py` · `.github/workflows/ci.yml` · `.gitignore` · `tests/test_desktop_shell.py` | 本包左列全部 |
| C6（测试归属切分，本侧执行） | `tests/test_server.py` · `tests/test_desktop_shell.py` | 本包左列全部 |

**关键变更（相对 `docs/reviews/2026-10-16-open-items-backlog.md` 的原登记）**：原 C6 行写「`test_server.py` / `test_german_workbench.py` / `test_desktop_shell.py` 三选」，**现已把 `test_german_workbench.py` 划归 C7 独占**（它的重写正是 C7 前置），C6 只做另两个文件。此变更需在 C6 的计划里注明。

---

## 参考

- 计划正本：`docs/plans/2026-10-18-c7-workbench-html-split.md`
- 登记行：`docs/reviews/2026-10-16-open-items-backlog.md`（C7）
- 前端拓扑：`docs/agents/architecture.md`
- 运维与文件契约：`docs/agents/ops.md`
- 仓库入口与红线：`AGENTS.md` · `WORKMEMORY/PROJECT_OVERVIEW.md`
- 工作记忆协议（本包格式来源）：`WORKMEMORY/PROTOCOL.md` §4

---

## 修订记录（发送方）

- **2026-10-18 00:5x｜文件占面契约修正**：`static/js/main.js` 与 `static/js/api-types.js` **从 C7 独占面移出，划归 C8**。原因：C8 的 `GET /api/settings` 来源脱敏（非回环来源不再返回 `api_key_masked`）改变了前端消费契约，`main.js` 对 LAN 客户端会渲染 `undefined`——该修复属 C8 闭环的一部分，不能跨工作流。**C7 侧若需改这两个文件，请先在包内响应节说明原因。** 其余 `static/js/**`（含新增 `wb-*.js` 模块）仍归 C7。若两侧真的同时改到同一文件，合并时以「C7 新增模块 / C8 只改 settings 渲染那一处」为界手工解冲突。

- **2026-10-18｜新增 CI 闸带来的保留义务**：新增了 CI job **`mock-drift`**（`tools/check_mock_drift.py`），判据 = 「测试里 `monkeypatch.setattr` 的目标符号在生产模块内已无可达引用」。`tests/test_a1_workbench_source.py` 的 **4 处**（`:329/:330/:331/:391`，patch `wb_dict` 的 `A1_WORKBENCH_SEED` / `A1_WORKBENCH_CUSTOM` / `A1_WORKBENCH_CORE_IDS`）已加 `mock-drift-ok: <理由>` 抑制注释。**若你重写该文件的探针，MUST 保留或重建这 4 条注释**——否则新闸在该文件上会转红（判据本身不针对 workbench，是这些补丁的形态触发的）。同批还改了 `tests/test_server.py` 等 C6 面文件的抑制注释（不涉 C7）；`tests/test_desktop_shell.py` 经判据收窄后**无需改动**。
