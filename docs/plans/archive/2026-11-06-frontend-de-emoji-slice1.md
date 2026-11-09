# 前端去 Emoji 第一垂直切片实施计划（exam · nav_mobile · cards 三态 · companion 控件）

> **Goal**：在不改变任何功能语义的前提下，于 4 个界面建立一套可复用的「删字形 / 补可访问名 / 补排版」替换语法，并让 4 个界面的可见彩色 emoji 归零，为后续批量推广提供已验证的样板。
> **Tech Stack**：原生 HTML 片段（`static/views|layout/*.html`）+ 原生 JS（无构建器）+ 单一 `static/style.css` + Python 3.11（仅用于构建/校验脚本与 pytest）。
> **Spec Reference**：[ADR-0029](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)（§3 决策、§5 实施顺序、§6 失败信号、§10 决策确认、§11 有效期、§12 推翻留痕）；[第一轮调研](../research/2026-11-06-emoji-and-ai-tone-frontend-research.md)；[第二轮外部证据](../research/2026-11-06-emoji-round2-external-evidence-and-mapping.md)
> **Global Constraints**：
> - **不变量 I1**：「任何字形都不得是意义的唯一载体。」删除任一 emoji 后，该控件的可访问名必须来自可见文字、`aria-label` 或 `aria-labelledby` 之一；`title` **不计入**（触屏与部分 AT 组合不可靠，见 ADR §13.2）。
> - **不变量 I2**：本切片不新增任何运行时依赖、不改构建链、不改 `static/sw.js`、不引入 CSP。
> - **不变量 I3**：`static/index.html` 是生成物（`tools/build_index_html.py` 组装 3 个 `static/views|layout` 片段），**每次改片段后必须重跑构建并连同生成物一起提交**，否则 `tests/test_check_index_html_sync.py` 立即变红。
> - **不变量 I4**：推翻既有结论必须留痕（ADR §12）——不改旧文字，在 `Deviation Table` 记录「原计划 / 实际 / 理由」，必要时追加 ADR「修正记录」。
> - **不变量 I5**：本轮只做 4 个界面；其余 37 个文件、图标集、token 迁移**不得**顺手带进本切片。
> **Branch**：
> - 代码切片：`feat/frontend-de-emoji-slice1`（从最新 `master` 开，PR 合入 `master`）。
> - README 任务（T8）：`docs/readme-zh-only`（**独立 PR**，见「排序与并行」）。
> - 本计划文档自身：`docs/adr-0029-and-slice1-plan`（纯文档 PR，不合并）。

---

## [NOTE] Decisions So Far

- ADR-0029 §10：四项拍板已闭合——角色字形保留但补可访问名；README 仅中文、德文只留术语；图标集后续引入并 vendor；垂直切片验收后推广。
- ADR-0029 §11：本文有效期绑定 2026-11-06 快照（551 簇 / 523 可见 / 382 冗余 / `aria-label` 11 处且服务字形者 0）。E1–E7 任一触发即应作废本计划的前提。
- ADR-0029 §12：ADR 状态四态化；被推翻不删除原文；新 ADR 显式 `Supersedes`；同 PR 更新索引；计划偏差落表。
- ADR-0029 §13.1：`cards.js:131-150` 三态**有**独立中文标题，emoji 是 2.5rem 装饰 → 本计划只删装饰，**不重建三态**（徽章方案进 Deferred Gap）。
- ADR-0029 §13.2：`.panel-char-btn` 已有 `title`、缺选中态；`#panel-sound` 才是真正无名控件。

---

## [NOTE] Repo Invariants Pointer

执行本计划的每个 subagent 开工前只读这三处，不另行复述规则：

1. `AGENTS.md`（路由）→ `docs/agents/architecture.md`（构建链与前端拓扑）。
2. ADR-0029 全文（尤其 §3 决策、§6 失败信号、§12 推翻留痕）。
3. 本计划的 `Global Constraints` I1–I5 与各任务的「停止门」。

派生自仓库既有机制的约束（不另造）：
- 生成物同步：`tools/build_index_html.py` → `tools/check_index_html_sync.py`（`tests/test_check_index_html_sync.py` 强制）。
- 文档归档：`docs/README.md` 规定计划发版后 `git mv` 进 `plans/archive/`。

---

## [NOTE] 排序与并行（README 与代码）

| 关系 | 结论 | 依据 |
|---|---|---|
| 先后 | **README（T8）先做**，代码切片可与之并行 | ADR-0029 §5：D 段零代码风险、面试官可见，且不依赖任何代码任务 |
| 并行 | **可以并行，但必须分 PR** | 文件零交集（README vs `static/*`）；分 PR 才能各自独立回退（`git revert` 一个 PR 不影响另一个） |
| 阻塞 | T8 不阻塞 T2–T7，T2–T7 不阻塞 T8；两者都被 T1 与 T0 前置 | T1 提供基线数字，T0 提供状态视图 |
| 唯一硬顺序 | T2 → T3（同文件 `exam.html`）；T1 → 其余全部；T10 最后 | 见各任务 `Depends` |

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 0: 建 ADR 状态索引 [Tier: 1-Light] [Mode: AFK] [Role: Docs]

**Files:**
- Create: `docs/adr/INDEX.md`
- Modify: `docs/README.md:13`（`adr/` 行补一句「状态视图见 `adr/INDEX.md`」）
- Test: 无新增测试；用下方的 grep 计数做物理验收

**Interfaces:**
- Consumes: `docs/adr/2026-*-adr-XXXX-*.md` 的顶部状态行与 H1 标题
- Produces: `docs/adr/INDEX.md`，表列 `编号 | 标题 | 状态 | 取代/被取代 | 日期 | 文件`

**SSOT Effect:** —
（本任务不产生新数字；表中的日期与编号逐字抄自各 ADR 文件头，不做推断。）

**Injected Instincts:**
- [ ] 只读各 ADR 前 12 行取 `状态` 与标题，**不修改任何 ADR 正文**（ADR §12.2 规则 1）。
- [ ] 状态词表固定为 ADR §12.1 四态；文件里写成 `ACCEPTED` 等变体的，**索引里归一为 `Accepted`，并保留原始写法一列**，避免"看起来改过原文"。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 0: 建 ADR 状态索引。
> Mode: AFK | Role: Docs
> Goal: 为 `docs/adr/` 下 29 份 ADR 建一份只含状态的最小索引，能一眼看出哪些仍生效、哪些被取代。
> Target Files: Create `docs/adr/INDEX.md`; Modify `docs/README.md`（`adr/` 行加一行指引）。
> Constraints: 禁止修改任何 ADR 文件；状态归一为 Proposed / Accepted / Superseded by ADR-XXXX / Deprecated；索引顶部写明「本索引只反映仓内副本，正式件在 Vault」。
> Verify: `python -c "import pathlib;print(len(list(pathlib.Path('docs/adr').glob('*adr-*.md'))))"` 与索引数据行数一致；`python -c "print(open('docs/adr/INDEX.md',encoding='utf-8').read().count('| ADR-'))"` 等于该数。
> Return: 摘要 + 文件行数 + 上述两条命令的原始输出与退出码。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：先写 `docs/adr/INDEX.md` 的空表头，用 `Test-Path`/`ls` 取得 29 份文件清单，断言「索引数据行数 = 0 ≠ 29」。
- [ ] **Step 2**：逐份读前 12 行，填入 29 行。
- [ ] **Step 3（GREEN）**：重跑计数命令，确认 29 = 29，退出码 0。
- [ ] **Step 4**：抽查 3 份（0026 / 0028 / 0029），索引状态与文件头逐字一致。
- [ ] **Step 5**：`git add docs/adr/INDEX.md docs/README.md` 单独提交。

**停止门（出现即停）：**
- 任一份 ADR 头部**没有**状态行 → 停下问用户，不替它猜状态。
- 索引需要"解释"某份 ADR 才能填表 → 说明该 ADR 的状态表述有歧义，登记进 Deferred Gap，不自行裁定。

---

### Task 1: 基线快照与逐控件清点（本切片的验收基准） [Tier: 1-Light] [Mode: AFK] [Role: Audit]

**Files:**
- Modify: 本文件（在本计划末尾 `## 执行记录` 追加清点表）
- Create: 无（**不新增审计工具**；理由见下）
- Test: 无（本任务的产出是表，不是代码）

**Interfaces:**
- Consumes: `static/views/exam.html`、`static/layout/nav_mobile.html`、`static/js/cards.js`、`static/layout/companion.html`、`static/layout/progress.html:192-234,339`
- Produces: 一张「控件 id | 可见文字（删字形后） | 可访问名来源 | 结论」表，逐行覆盖切片内全部 `<button>` / `<a>`

**SSOT Effect:**
- Reads: `docs/adr/2026-11-06-adr-0029-*.md#11.1`（551 / 523 / 382 / 11 / 10 五个基线数字）
- Writes: 本计划 `## 执行记录`
- Hardcoded-literal exemption: 各任务的期望 emoji 计数即为本表快照值，必须与本表一致，不得沿用 ADR 旧数

**Injected Instincts:**
- [ ] **不新增工具**：切片内交互控件约 30 个，一张人工表可覆盖；把"意义载体"写成正则只会得到假阳性。若第二批推广时控件数 >50，再考虑固化为脚本（见 Deferred Gap）。
- [ ] 计数口径必须写死在表头：**彩色 emoji 簇**（含 VS16），排除 `← ✕ ✓ ↺ ↶ → ⚠` 等排版符号、排除 HTML/JS 注释。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 基线快照与逐控件清点。
> Mode: AFK | Role: Audit
> Goal: 为第一垂直切片建立可复核的验收基准，供后续 6 个任务逐项对照。
> Work: 对本计划 §切片文件 列出的文件，逐个 `<button>`/`<a>` 记录 (a) 删去彩色 emoji 后是否仍有可见文字；(b) 是否已有 aria-label/aria-labelledby；(c) 仅有 title 的标记为 WARN。同时统计每个文件的彩色 emoji 簇数。
> Constraints: 只读代码，不改任何 `static/**`；不得把 title 记为已命名；注释内 emoji 不计入。
> Verify: 表中控件总数 = `Select-String -Pattern '<button' static/views/exam.html,static/layout/nav_mobile.html,static/layout/companion.html` 命中数 + 其它两文件里的 JS 模板按钮数（逐条列出）。
> Return: 表格 + 每文件 emoji 计数 + 与 ADR §11.1 的差异说明（若有差异，按 ADR §11.2 E1/E7 判定是否停下）。"

**Step Breakdown:**
- [ ] **Step 1**：统计 5 个文件的彩色 emoji 簇数，写入表头。
- [ ] **Step 2**：逐控件填表（预计 30 行上下）。
- [ ] **Step 3（GREEN）**：与 ADR §11.1 对照；`static/` 侧 `aria-label` 应为 11 处，若已变化 >20% → **停止门触发**。
- [ ] **Step 4**：把表写进本计划 `## 执行记录`。
- [ ] **Step 5**：随所属 PR 提交（T1 本身不单独开 PR）。

**停止门（出现即停）：**
- 彩色 emoji 簇总数相对 ADR §11.1 的 551 变化超过 ±20% → 触发 ADR §11.2 **E1**，本计划全部任务作废，先写新 ADR。
- 4 个切片文件在 `master` 上已被重写/删除 → 触发 **E7**，file:line 映射失效，重写计划。

---

### Task 2: `exam` 模块网格——删 7 个字形，换 `01`–`07` 编号 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend]

**Files:**
- Modify: `static/views/exam.html:11-19`
- Modify: `static/style.css:3655-3671`（`.exam-module-card` 内新增 `.exam-module-index` 与布局；**本任务独占 `style.css`**）
- Modify: `static/index.html`（构建产物，重跑生成）
- Test: `tests/test_exam_domain.py`（既有，不需要改）

**Interfaces:**
- Consumes: 既有 `id="exam-card-<module>"`、`onclick="setExamModule('<module>')"`、`.exam-module-card.active`
- Produces: 同一批 id/onclick 不变；新增 `.exam-module-index`（`<span>`，`aria-hidden="true"`）承载序号——序号是**装饰性排序线索**，模块名本身仍是唯一语义载体，符合 I1

**SSOT Effect:** —（序号 01–07 是视觉排序，不进入任何数据/文案真值源）

**Injected Instincts:**
- [ ] 保留 `.exam-module-card` 的 `text-align:left` 与 3px/4px 硬阴影；新增样式只允许：`display:grid;grid-template-columns:auto 1fr;gap:.25rem .625rem`、`.exam-module-index{font-family:var(--mono);font-size:.6875rem;letter-spacing:.12em;color:var(--muted)}`、中文名与德文名分两行（`<span class="exam-module-label">`）。**不得**引入新颜色、不得改字号阶梯外的值。
- [ ] 德文名保留在括号内 → 属于术语，符合"README 只中文"的同一原则（德文仅术语）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: exam 模块网格去字形。
> Mode: AFK | Role: Frontend
> Goal: 让 `#exam-module-grid` 内 7 个按钮的可见彩色 emoji 归零，同时用 01–07 序号 + 中/德双行文字保持信息量。
> Target Files: Modify `static/views/exam.html:11-19`, `static/style.css`（仅 `.exam-module-card` 邻域）; regenerate `static/index.html`.
> 不变量 I1: 删字形后每个按钮仍有「写作专项」等中文名 + 德文术语，可访问名 100% 来自可见文字。
> Steps: (1) 记录当前按钮文本快照；(2) 改写 7 个按钮为 `<span class="exam-module-index" aria-hidden="true">01</span><span class="exam-module-label">写作专项<span class="exam-module-de">Schreiben</span></span>`；(3) 加 CSS；(4) `python tools/build_index_html.py`；(5) `python tools/check_index_html_sync.py` 必须 exit 0；(6) `python -m pytest tests/test_exam_domain.py -q`。
> Verify: `#exam-module-grid` 块内 📝🎧📖💬✍️ 计数为 0；7 个 id 与 onclick 逐字不变；上述两条命令退出码 0。
> Return: 摘要 + 两条命令原始输出 + `git diff --stat`."

**Step Breakdown:**
- [ ] **Step 1（RED）**：`python -m pytest tests/test_exam_domain.py -q` 先跑一遍记录基线（预期绿）。
- [ ] **Step 2**：改写 7 个按钮（保留 id / onclick / `active` 类）。
- [ ] **Step 3（GREEN）**：加 CSS；`python tools/build_index_html.py`；`python tools/check_index_html_sync.py`。
- [ ] **Step 4**：`python -m pytest tests/test_exam_domain.py tests/test_check_index_html_sync.py -q`。
- [ ] **Step 5（REFACTOR）**：确认未新增字号/颜色字面量；如需间距，只用既有 4px 倍数。
- [ ] **Step 6**：物理回执（两条命令 + exit code + diff stat）。
- [ ] **Step 7**：单独提交 `feat(exam): replace module emoji with numbered labels`。

**验收判据（I1 派生）：**
1. `#exam-module-grid` 内彩色 emoji 簇 = **0**。
2. 7 个 `<button>` 的 `id` / `onclick` 与改动前逐字相同（`git diff` 只应出现文本与新增 span）。
3. 每个按钮删字形后仍有可见中文名 → 可访问名 100% 来自可见文字。
4. `tests/test_exam_domain.py` 全绿（含 `.exam-module-card` CSS 规则存在断言）。

**停止门（出现即停）：**
- 若 7 个按钮中有任何一个在删字形后**只剩德文**或只剩序号 → 停止，回退该按钮，补中文再继续。
- 若要为排版引入新的间距/字号字面量 → 停止，改为从 `tokens.css` 取值或不做该调整（ADR §3.5 只增不迁）。
- 构建同步校验失败且原因不是"忘了重跑构建" → 停止，登记而不绕过。

---

### Task 3: `exam.html` 其余装饰字形清零 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend]

**Files:**
- Modify: `static/views/exam.html`（约 26 处非注释 emoji；行号以 T1 快照为准）
- Modify: `static/index.html`（构建产物）
- Test: `tests/test_exam_domain.py`、`tests/test_check_index_html_sync.py`

**Interfaces:**
- Consumes: T2 完成后的 `exam.html`
- Produces: `exam.html` 非注释彩色 emoji = 0；所有 `<button>`/`<a>` 文本不变（仅去前缀字形）

**SSOT Effect:** —

**Injected Instincts:**
- [ ] **只删前缀/点缀字形，不改任何一个汉字的措辞**。A1 面板内的 `📖 官方考纲词表 (700+)`、`🎯 立即批改 (5 分)` 等，删掉的是 `📖`/`🎯`，保留其后全部文字。
- [ ] `<input placeholder="🔍 搜索 A1 单词…">` 的 `🔍` 删除后 placeholder 仍以文字开头 → 允许删；若某处删完 placeholder 为空则保留并登记。
- [ ] 注释内的 emoji（如 `<!-- ── 模块面板：🎧 听力微训 ── -->`）**不动**——不进渲染，不影响 I1，且改动纯增噪声。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: exam.html 其余装饰字形清零。
> Mode: AFK | Role: Frontend
> Goal: 让 `static/views/exam.html` 的非注释彩色 emoji 归零，作为切片内"零 emoji 文件"的样板。
> Target Files: Modify `static/views/exam.html`; regenerate `static/index.html`.
> Rule: 只删字形，不改任何文字；每处删除前确认同一元素内仍有中文（I1）。
> Verify: 用 T1 的字形集合统计，非注释计数 = 0；`python tools/check_index_html_sync.py` exit 0；`python -m pytest tests/test_exam_domain.py -q` 全绿。
> Return: 摘要 + 逐处删除清单（行号 + 删除的字形）+ 命令回执。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：统计当前非注释 emoji 数 N，写入回执。
- [ ] **Step 2**：逐处删除；每删一处核对同元素内文字。
- [ ] **Step 3（GREEN）**：重跑构建 + 同步校验 + pytest。
- [ ] **Step 4（REFACTOR）**：检查是否留下连续空格或空 `<span>`。
- [ ] **Step 5**：物理回执（N → 0）。
- [ ] **Step 6**：单独提交 `feat(exam): strip decorative emoji from exam panels`。

**验收判据（I1 派生）：**
1. `exam.html` 非注释彩色 emoji 簇 = **0**。
2. `git diff` 中**没有**任何中文字的增删（只允许删除 emoji 与其后紧跟的一个空格）。
3. 所有 `<button>` 的可见文字长度 ≥ 2 个汉字（脚本抽查 `#exam-` 前缀按钮）。

**停止门（出现即停）：**
- 发现某按钮删字形后可见文字为空 → 立即恢复该处字形并登记 Deferred Gap，**不得**为了凑"零 emoji"而改文案。
- diff 中出现文案改写（非 emoji 字符的增删）→ 停止，拆分提交。

---

### Task 4: `nav_mobile` 删 8 个图标字形 [Tier: 1-Light] [Mode: AFK] [Role: Frontend]

**Files:**
- Modify: `static/layout/nav_mobile.html:7,15,23,31,39,47,55,63`（8 个 `.mob-icon` 整行）
- Modify: `static/index.html`（构建产物）
- Test: `tests/test_exam_domain.py`、`tests/test_german_workbench.py`、`tests/test_search_ui.py`（均只断言 id/onclick/顺序，不受影响）

**Interfaces:**
- Consumes: 每个按钮的 `.mob-label` 已含中文（`文书库/台账/写作/备考/卡片(N)/背词/检索/设置`）
- Produces: 8 个按钮结构为 `<button ...><span class="mob-label">…</span></button>`

**SSOT Effect:** —

**Injected Instincts:**
- [ ] **不改 `style.css`**：`.mob-icon` 规则会变成死规则，但删除它会把 `style.css` 拉进本任务的回退面，破坏"可独立回退"。死规则登记 Deferred Gap。
- [ ] 保留 `id="mob-card-count"` 的嵌套（`卡片 (<span id="mob-card-count">0</span>)`），否则 `cards.js` 计数更新会静默失效。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: nav_mobile 去图标字形。
> Mode: AFK | Role: Frontend
> Goal: 删掉 8 个 `.mob-icon` 装饰字形，保留 `.mob-label` 中文标签。
> Target Files: Modify `static/layout/nav_mobile.html`; regenerate `static/index.html`.
> 不变量 I1: 每个 dock 按钮的可访问名来自 `.mob-label`，删除 icon 后仍完整。
> Verify: 文件内 🎯🎴📖📚🔍⚙️📊✍️ 计数 = 0；8 个 `id="mob-btn-*"` 与 `onclick` 逐字不变；`mob-card-count` 仍在；`python tools/check_index_html_sync.py` exit 0；`python -m pytest tests/test_exam_domain.py tests/test_german_workbench.py tests/test_search_ui.py -q` 全绿。
> Return: 摘要 + 命令回执 + diff stat。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：跑上述 pytest 子集，记录基线绿。
- [ ] **Step 2**：删 8 行 `<span class="mob-icon">…</span>`。
- [ ] **Step 3（GREEN）**：重跑构建 + 同步校验 + pytest 子集。
- [ ] **Step 4（REFACTOR）**：肉眼确认 dock 仍是 8 项等宽、label 垂直居中（`flex-direction:column` 不会因少一行而错位）。
- [ ] **Step 5**：物理回执。
- [ ] **Step 6**：单独提交 `feat(nav): drop decorative dock emoji`。

**验收判据（I1 派生）：**
1. `nav_mobile.html` 彩色 emoji = **0**。
2. 8 个 `id`、8 个 `onclick`、`mob-card-count` 全部存在且逐字未变。
3. dock 内每个按钮的 `textContent` trim 后非空。

**停止门（出现即停）：**
- 任一按钮删字形后 `textContent` 为空 → 停止并恢复该处。
- 有人提出"顺手把 `.mob-icon` 规则也删了" → 拒绝，超出本任务文件边界（登记）。

---

### Task 5: `cards` 空态三态——删 2.5rem 装饰字形 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend]

**Files:**
- Modify: `static/js/cards.js:131-155`（删 `emptyIcon` 变量与渲染行）
- Test: 无既有测试断言该块；用 `tests/test_cards_state_split.py` / `test_cards_count_probe.py` 做回归（应保持绿）

**Interfaces:**
- Consumes: `cardState.catalog.segment ∈ {due, mastered, all}` 与三个 `emptyTitle` 常量
- Produces: 空态 DOM 变为 `<div>标题</div><p>说明</p>`，无 2.5rem 字形节点

**SSOT Effect:** —（三个 `emptyTitle` 是唯一文案真值源，本任务不改其字）

**Injected Instincts:**
- [ ] 只删 `emptyIcon` 与 `<div style="font-size:2.5rem;margin-bottom:0.5rem;">${emptyIcon}</div>` 一行；`emptyTitle` / `emptyDesc` / 外框虚线 / 内联样式**全部不动**。
- [ ] 按 ADR §13.1：**不**新增状态徽章、**不**加左竖线、**不**引入颜色语义——那是审美升级，属 Deferred Gap。
- [ ] 删除后 `container.innerHTML` 的首个子节点变成标题，需确认 `padding:4rem 1rem` 的视觉重心仍成立（HITL 看截图）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 删卡片空态装饰字形。
> Mode: AFK | Role: Frontend
> Goal: 移除 `cards.js` 空态里 2.5rem 的 🎉/🛡️/🎴，三态仍靠中文标题区分。
> Target Files: Modify `static/js/cards.js:131-155`.
> 不变量 I1: 三个 emptyTitle 已分别承载「已完成 / 已掌握 / 新卡」语义，删字形不丢信息（ADR §13.1 已实证）。
> Verify: `Select-String -Pattern 'emptyIcon' static/js/cards.js` 命中 0；三句 emptyTitle 原文仍在且各出现 1 次；`python -m pytest tests/test_cards_state_split.py tests/test_cards_count_probe.py -q` 全绿。
> Return: 摘要 + grep 回执 + pytest 回执 + 三态截图（due/mastered/all）。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：先跑 pytest 子集记录基线；同时 grep 记录 `emptyIcon` 当前 2 处。
- [ ] **Step 2**：删变量与渲染行。
- [ ] **Step 3（GREEN）**：grep = 0；pytest 子集全绿。
- [ ] **Step 4（REFACTOR）**：确认没有反向依赖 `emptyIcon`（全仓 grep）。
- [ ] **Step 5**：三态截图（`?segment=due|mastered|all` 或直接切标签）。
- [ ] **Step 6**：单独提交 `feat(cards): remove emoji from empty states`。

**验收判据（I1 派生）：**
1. `emptyIcon` 在全仓出现 0 次。
2. 三句 `emptyTitle` 各出现 1 次，逐字未变。
3. 三态各自的空态渲染仍有一个标题 + 一段说明（截图回执）。

**停止门（出现即停）：**
- 删除后发现某个 segment 的空态**没有任何文字**（例如分支写错导致标题为空）→ 停止并回退。
- 发现 `cards.js` 其它位置依赖 `emptyIcon` → 停止，改为保留变量名只删渲染（并记录偏差）。

---

### Task 6: `companion` 面板控件补可访问名 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend+A11y]

**Files:**
- Modify: `static/layout/companion.html:22-24`（`.panel-close`）、`27-75`（`.panel-char-btn` 4 个 + 自定义/上传）、`129-135`（`#panel-sound`）、`136-143`（`#panel-hide`）
- Modify: `static/js/companion.js:942-957`（`syncPanel` 同步 `aria-pressed` 与图标 span）
- Modify: `static/index.html`（构建产物）
- Test: 无既有 JS 测试基建（`tests/test_frontend_guards.py` 首段已声明），验收靠结构 grep + HITL

**Interfaces:**
- Consumes: `Companion.charId`、`Companion.soundEnabled`、既有 `title="歌德猫头鹰"` 等文案
- Produces:
  - `.panel-char-btn` → `aria-label="<角色名>"`（与 `title` 同文）+ `aria-pressed="true|false"`，字形包 `<span aria-hidden="true">`
  - `#panel-sound` → `aria-label="伴读发声"` + `aria-pressed="true|false"` + 内部 `<span id="panel-sound-icon" aria-hidden="true">🔊</span>`
  - `.panel-close` → `aria-label="关闭伴读设置"`；`#panel-hide` → `aria-label="收起伴读悬浮球"`
- **破坏点**：`companion.js:954-957` 现在用 `soundBtn.textContent = …` 整体替换按钮内容，包 span 后会把 span 抹掉 → 必须改为更新 `#panel-sound-icon`。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] **保留 emoji 字形本身**（ADR §10 决策 1）：本任务只加可访问名与 `aria-hidden`，**不 SVG 化**。
- [ ] `aria-pressed` 必须在 `syncPanel()` 里每次同步，否则初始状态与 DOM 会不一致（`active` 类只更新角色按钮，未覆盖声音开关）。
- [ ] `title` 保留不动（桌面 hover 仍有价值），只是不再作为唯一可访问名。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6: companion 面板控件无障碍补齐。
> Mode: AFK | Role: Frontend+A11y
> Goal: 让 `companion.html` 里所有字形控件在删去字形后仍可被命名；本任务**不删除**角色字形，只补 `aria-label`/`aria-pressed`/`aria-hidden`。
> Target Files: Modify `static/layout/companion.html`, `static/js/companion.js:942-957`; regenerate `static/index.html`.
> 不变量 I1: `.panel-char-btn` 与 `#panel-sound` 的可访问名来自 `aria-label`；`title` 不再单独承担命名。
> Steps: (1) 4 个角色按钮加 aria-label（与 title 同文）+ aria-pressed="false"（当前项 true），字形包 span aria-hidden；(2) 自定义/上传按钮同样处理；(3) `#panel-sound` 加 aria-label + aria-pressed，内部 span id=panel-sound-icon；(4) `.panel-close`/`#panel-hide` 加 aria-label；(5) 改 `syncPanel()`：角色按钮同步 aria-pressed，声音按钮只改 `#panel-sound-icon` 的 textContent 并同步 aria-pressed；(6) 重建 index.html。
> Verify: grep `aria-label` 在该文件 ≥ 8；`panel-sound` 块含 aria-pressed；`grep -n "soundBtn.textContent" static/js/companion.js` = 0；`python tools/check_index_html_sync.py` exit 0。
> Return: 摘要 + 每条 grep 回执 + HITL 截图（4 个角色选中态 + 静音态）。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：grep 记录现状（`aria-label` 0 处、`aria-pressed` 0 处）作为红。
- [ ] **Step 2**：改 4 个角色按钮（aria-label + pressed + span）。
- [ ] **Step 3**：改自定义/上传/关闭/收起按钮。
- [ ] **Step 4**：改 `#panel-sound` 与 `syncPanel()`。
- [ ] **Step 5（GREEN）**：构建 + 同步校验；grep 断言全部满足。
- [ ] **Step 6（REFACTOR）**：确认 `aria-pressed` 与 `.active` 类同步策略一致（同一函数内更新）。
- [ ] **Step 7**：HITL 截图（默认态 / 切到猫 / 静音）。
- [ ] **Step 8**：单独提交 `feat(companion): name icon-only controls`。

**验收判据（I1 派生）：**
1. `companion.html` 内每个 `<button>` 都满足「可见文字非空 **或** 有 `aria-label`」——逐条列在回执里。
2. 4 个角色按钮 + `#panel-sound` 均有 `aria-pressed`，且初始值与 `charId` / `soundEnabled` 一致。
3. `grep "soundBtn.textContent" static/js/companion.js` = 0（防止 span 被抹掉）。
4. 切换角色、切换静音后，`aria-pressed` 随之变化（HITL 截图或 DOM 断言）。

**停止门（出现即停）：**
- 若为了让 `#panel-sound` 有名字而**给它加可见文字**（如「发声」）→ 停止，先问用户是否接受按钮变宽；本计划的默认方案是 `aria-label`，不改视觉。
- 若 `syncPanel()` 的改动导致 `#panel-sound` 图标不随状态切换 → 停止，回退该步重做，不允许"图标不换但 aria 对"的半成品。
- 若发现角色按钮的 `aria-pressed` 需要与 `.active` 在两个不同函数里同步（`syncStudio` 也会跑）→ 停止，先把两个 sync 的职责边界写清再改。

---

### Task 7: `companion` 第二宿主（`progress.html` studio）——**已定：纳入本切片（选项 A）** [Tier: 2-Standard] [Mode: AFK] [Role: Frontend+A11y]

**Files:**
- Modify: `static/views/progress.html:192-234`（`.mascot-choice-btn` 5 个）、`339`（`#studio-sound-icon`）
- Modify: `static/js/companion.js:904-922`（`syncStudio` 同步 `aria-pressed`）
- Modify: `static/index.html`（构建产物）

**Interfaces:**
- Consumes: 与 T6 同一套 `Companion.charId` / `soundEnabled`
- Produces: `progress.html` 的角色/声音选择器与 `companion.html` 具有相同的可访问名契约

**SSOT Effect:** —

**为什么单列：** 用户给的第一切片边界是"`companion` 声音/角色按钮"，而 studio 版是**同一个组件的第二个宿主**（`muted` 组件在 `progress` 视图里渲染）。只修 panel 会留下"同一功能两套无障碍质量"。

**拍板结果（2026-11-06）**：用户选择 **A（纳入）**，依据见 [ADR-0029 §14](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md#14-决策确认补充t7-纳入第一切片2026-11-06)。下表保留为决策前记录，不再作为待决事项：

| 选项 | 后果 |
|---|---|
| A. 纳入（已选） | 切片结束时「伴读角色选择器」在全部宿主上都合规；多改 1 个文件 + 1 个函数 |
| B. 不纳入（未选） | 本切片只保证 `companion.html`；`progress.html` 登记 Deferred Gap，第二批处理 |

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 7（用户已拍板 A，见 ADR-0029 §14）: progress studio 角色/声音选择器补可访问名。
> Mode: AFK | Role: Frontend+A11y
> Goal: 让 `.mascot-choice-btn` 与 `#studio-sound-icon` 所在的按钮具备与 T6 相同的可访问名契约。
> Target Files: Modify `static/views/progress.html:192-234,339`, `static/js/companion.js:904-922`; regenerate `static/index.html`.
> Constraint: 与 T6 逐字一致的 aria-label 文案与 aria-pressed 语义；不自创另一套。
> Verify: `progress.html` 的 `<button>` 全部满足「有可见文字或有 aria-label」；`syncStudio()` 同步 aria-pressed；构建同步 exit 0。
> Return: 摘要 + grep 回执 + 截图。"

**Step Breakdown:**
- [ ] **Step 1**：拍板已记录在 ADR-0029 §14（A），不再询问用户；grep 记录现状作为 RED 基线。
- [ ] **Step 2（RED）**：`aria-pressed` 在 `progress.html` studio 段计数为 0。
- [ ] **Step 3**：改 5 个角色按钮 + 声音按钮。
- [ ] **Step 4**：改 `syncStudio()`。
- [ ] **Step 5（GREEN）**：构建 + 同步校验 + 截图。
- [ ] **Step 6**：单独提交 `feat(progress): mirror companion a11y contract`。

**验收判据（I1 派生）：**
1. `progress.html` 内每个 `<button>` 都满足「可见文字非空 或 有 `aria-label`」。
2. 角色按钮 `aria-pressed` 与 `charId` 一致；声音按钮 `aria-pressed` 与 `soundEnabled` 一致。
3. 与 T6 的 aria 文案逐字一致（`git diff` 对比两处字符串）。

**停止门（出现即停）：**
- 用户未拍板 → 停在 Step 1，不作为失败。
- 发现 `progress.html` 的 studio 标记被另一特性（如 `cp-drawer-capsule`）运行时替换 → 停止，先查 `static/js/cp-drawer-capsule.js:87` 的宿主假设。

---

### Task 8: README 仅中文（**独立 PR，可与代码切片并行**） [Tier: 1-Light] [Mode: AFK] [Role: Docs]

**Files:**
- Modify: `README.md`（H2 标题 10 处、正文英文括注、内部锚点链接）
- Test: 无（纯文档）；用 grep 计数做物理验收

**Interfaces:**
- Consumes: 当前 `README.md` 的 10 个 `##` 标题（`32/55/75/94/117/133/166/190/210/224`）与正文中的 `中文 (English)` 括注
- Produces: 10 个 `##` 标题 emoji = 0；非术语英文括注 = 0；**因标题改名而失效的内部锚点全部修正**

**SSOT Effect:** —
（版本号 / 测试数等数字不在本任务范围内，不得顺手改；它们由 `docs/agents/ci-speed-budget.md` 与发版流程维护。）

**Injected Instincts:**
- [ ] **锚点联动**：GitHub 锚点由标题文本生成，删 emoji 会改变锚点（`#-多平台下载发布包-downloads` → `#多平台下载发布包-downloads`）。必须 `grep -n "](#" README.md` 全量核对，不能只改标题。
- [ ] **只删英文括注，不删英文内容**：`uv venv --python 3.11`、`start.py`、`docker compose up -d --build` 等命令与代码块**一律不动**；APACHE 2.0、MIT 等许可证名、`FSRS`、`CEFR`、`spaCy` 等产品/术语名保留。
- [ ] **保留德文术语**：`PRÜFUNGSDOMÄNE`、`VOKABELN`、`Wortliste` 等属于产品语言，不视为"英文双写"。
- [ ] 徽章下移与「核心特性取消全量粗体」属 ADR §5 D 段，但**本任务只做"仅中文"**；其余 README 工程化改动单列后续任务（避免一个 PR 混两种意图）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 8: README 仅中文。
> Mode: AFK | Role: Docs
> Goal: README 只保留中文；德文仅限术语；删除标题 emoji 与非术语英文括注；修复因此失效的内部锚点。
> Target Files: Modify `README.md` only.
> Constraints: 不改命令/代码块/版本号/测试数；不改徽章；不删正文里的产品术语与德文术语；ADRs/CHANGELOG 等路径链接保持。
> Verify: (1) `Select-String -Pattern '^## ' README.md | % { $_.Line -match '[\u2600-\u27BF\u{1F300}-\u{1FAFF}]' }` 为 0；(2) `grep -oE '\]\(#[^)]*\)' README.md` 逐条能在标题文本里找到对应 slug；(3) 行数变化绝对值 ≤ 12。
> Return: 摘要 + 三条命令回执 + 改前改后标题对照表。"

**Step Breakdown:**
- [ ] **Step 1（RED）**：记录 10 个带 emoji 的 `##` 标题与所有内部锚点。
- [ ] **Step 2**：删 10 个标题 emoji。
- [ ] **Step 3**：删正文非术语英文括注（逐条列出判断依据）。
- [ ] **Step 4（GREEN）**：修正锚点；跑三条验证命令。
- [ ] **Step 5（REFACTOR）**：通读 diff，确认没有把"英文术语"误删成中文半句。
- [ ] **Step 6**：单独提交 `docs(readme): keep Chinese only and drop heading emoji`。

**验收判据（I1 类比 + ADR §5 D）：**
1. `##` 标题 emoji = **0**。
2. 内部锚点全部可解析（逐条对照）。
3. 代码块与命令 0 改动（`git diff` 中 ``` 围栏内无变化）。
4. README 总行数未因"散文补空"上升（ADR §6 失败信号 4）。

**停止门（出现即停）：**
- 某标题删掉英文后语义变窄（例如 `(Downloads)` 承担了"这是下载区"的信息）→ 停止，先补一个中文词再删，不得只删不补。
- 总行数上升 → 触发 ADR §6 信号 4，停止该 PR。
- 发现需要改 `FEATURES.md` / `CHANGELOG.md` 才能自洽 → 停止，登记，不在本 PR 扩散。

---

### Task 9: 把不变量写进设计系统文档 [Tier: 1-Light] [Mode: AFK] [Role: Docs]

**Files:**
- Modify: `docs/design-system.md`（新增一节「字形与图标」）

**Interfaces:**
- Consumes: ADR-0029 §3 决策 1、§3.6 白名单、§12 推翻留痕
- Produces: 一节可被后续 PR 引用的规则文本（≤40 行）

**SSOT Effect:** —（token 现值仍以 `static/css/tokens.css` 为准，本节不复述数值）

**Injected Instincts:**
- [ ] **不复述** ADR 的论证，只写可执行条款：① 任何字形不得是意义唯一载体；② 有文字的位置删字形，不换 SVG；③ 无文字控件优先补 `aria-label`，其次才考虑图标；④ 图标只允许 inline SVG（否决 sprite / icon font，理由见 ADR §4）；⑤ 状态类控件必须 `aria-pressed`。
- [ ] 不新增 token、不描述未实现的组件。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 9: 设计系统补「字形与图标」条款。
> Mode: AFK | Role: Docs
> Goal: 让后续前端 PR 有一个 40 行以内、可直接引用的规则节，避免每次回读 ADR。
> Target Files: Modify `docs/design-system.md`.
> Constraint: 只写条款，不复述 ADR 论证、不复述 token 数值、不新增未实现组件蓝图。
> Verify: 新增节内每一条都能在 ADR-0029 找到出处（回执里给映射）；文件其它部分 0 改动。
> Return: 摘要 + 映射表 + diff stat。"

**Step Breakdown:**
- [ ] **Step 1**：读 `docs/design-system.md` 结构，确定插入位置。
- [ ] **Step 2**：写 5 条条款 + 每条 ADR 出处。
- [ ] **Step 3（GREEN）**：核对无新增数字/无未实现内容。
- [ ] **Step 4**：单独提交 `docs(design-system): codify glyph semantics rule`。

**验收判据：**
1. 新增节 ≤ 40 行。
2. 每条条款后附 ADR-0029 的 §号。
3. 该节外 0 改动。

**停止门（出现即停）：**
- 发现 `docs/design-system.md` 已有等价条款 → 停止，改为在原条款后加 ADR 引用（复用现成，不另造）。

---

### Task 10: 切片验收（人工签字门） [Tier: 3-Critical] [Mode: HITL] [Role: Reviewer]

**Files:**
- Modify: 本计划（`## Deviation Table` 与 `## 验收回执`）

**Interfaces:**
- Consumes: T0–T9 的全部提交与回执
- Produces: 一份「通过 / 不通过 + 依据」的验收结论；不通过时给出回退到哪个提交

**SSOT Effect:**
- Reads: 本计划 `## 执行记录` 的基线表
- Writes: 本计划 `## 验收回执`

**Injected Instincts:**
- [ ] 逐条对照 ADR §6 的 6 个失败信号，**逐条**给"未触发 / 触发"与证据，不允许只写"整体感觉可以"。
- [ ] 每个片区的验收都以 I1 为唯一语义判据；视觉好坏只作为补充意见，不作为通过条件。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 10: 第一垂直切片验收。
> Mode: HITL | Role: Reviewer
> Goal: 判定切片是否达到 ADR-0029 §6 的通过条件，并决定是否可推广到第二批。
> Steps: (1) 复跑 4 个文件的 emoji 计数，与 T1 快照对比；(2) 复跑 T2–T7 的全部验证命令；(3) 逐条判定 ADR §6 的 6 个信号；(4) 逐条判定 §11.2 的 E1/E2/E7 是否触发；(5) 检查 Deviation Table 是否为空，非空则逐行确认理由；(6) 给出通过/不通过结论。
> Return: 结论 + 逐条证据 + 未通过时的回退提交号。"

**Step Breakdown:**
- [ ] **Step 1**：复跑全部计数与测试命令，保存原始输出。
- [ ] **Step 2**：逐条判定 §6 六信号。
- [ ] **Step 3**：逐条判定 E1/E2/E7。
- [ ] **Step 4**：核对 Deviation Table（每一行：计划文本 / 实际 / 理由）。
- [ ] **Step 5**：签署 `## 验收回执`，提交 `docs(plan): sign off slice1`。

**验收判据（切片级）：**
1. `exam.html` / `nav_mobile.html` 的非注释彩色 emoji = 0；`cards.js` 空态无字形；`companion.html` 每个按钮都有可访问名。
2. ADR §6 六条失败信号全部"未触发"且有命令级证据。
3. 无新增依赖、无 `static/sw.js` 改动、无 token 全站迁移（I2/I5）。

**停止门（出现即停，且升级为项目级）：**
- ADR §6 任一信号触发 → **停止推广**，按 §11.3 判定是"改计划"还是"写新 ADR 取代 0029"。
- 切片 3 天未收敛 → 触发 **E2**：「垂直切片先行」假设被证伪，暂停第二批，回到设计层重开。
- 验收期间发现某控件仍无名（I1 违反）→ 不通过，任务打回对应 T，不得"记录后继续"。

---

## [NOTE] Fog of War (Not Yet Specified)

- **[Unknown 1] 第二批页面清单与顺序**：依赖 T10 通过后才排序。候选 = 其余 37 个含 emoji 的源片段；排序依据（密度 vs 用户可见度）未定。
- **[Unknown 2] 图标集选型（Lucide vs Tabler）与 vendor 方式**：用户已授权"后续引入"，但未到执行时点；需先产出「无文字且承载语义」的实测清单（≥1 个才值得引入）。
- **[Unknown 3] 角色字形 SVG 化**：依赖 `docs/svg-character-spec.md` 与图标集落地；本轮只保证 `aria-label`。
- **[Unknown 4] token 只增不迁的具体数值**：ADR §5 Token 段给了方向，未给最终阶梯；需在第二批开始前定稿。
- **[Unknown 5] 生成物 `static/index.html` 的 Android 同步**：`tools/sync_android_sources.py` 整树复制，切片改动会自动进 Android assets；是否需要单独验证 Android 渲染（emoji 在 WebView 的字形差异）未定。

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| `tests/test_listen_lab_probe.mjs:316` 断言精确 emoji 串（`🎧 精听/跟读`、`✍️ 听写`、`⬚ 填空`） | listen lab 不在第一切片；本仓边界禁碰 `tests/test_*` | 第二批改到 listen lab 的任何字形时，**必须同 PR 改测试** | 第二批执行者 |
| `cards.js` 空态徽章方案（文字徽章 + 颜色 + 3px 左竖线） | ADR §13.1 已证明非无障碍必需，属审美升级 | T10 验收若有 ≥2 名评审称"删完太空"（ADR §6 信号 3） | 用户拍板 |
| `cards.js:1174-1186` 介词矩阵空态 `📡/🧭` | 不在"三态"范围内 | 第二批 cards 深化或用户点名 | 第二批执行者 |
| `cards.js:219-222` 卡片徽记 `🛡️/⏳/📚`（文本前缀） | 属"有文字位置的冗余字形"，不在本切片 | 第二批 cards 清理 | 第二批执行者 |
| `style.css` 的 `.mob-icon` 死规则（4 行） | 删除会把 `style.css` 拉进 T4 的回退面 | 第二个需要改 `style.css` 的任务落地时顺带删 | 第二批执行者 |
| 图标集 vendor（Lucide/Tabler，MIT/ISC + 许可与来源 commit） | 用户已授权引入，但触发条件未到（先要看是否仍有 ≥1 个无文字控件） | T10 通过后，且「无文字控件清单」非空 | 用户拍板选型 |
| 角色字形 🦉🐱🦊🤖 SVG 化 | 用户明确"先保留，但要之后做" | 图标集落地后，或用户再次点名 | 用户 |
| README 正文/表格内的装饰 emoji（🍎🐧📱🪟📖📜💬 等约 8 处） | T8 只执行"仅中文 + 标题去 emoji"，避免一个 PR 混两种意图 | README 二次工程化（徽章下移、核心特性去粗体）同批 | 文档维护者 |
| 把「无文字且承载语义」的清点固化为 `tools/check_ui_glyph_semantics.py` | 切片内约 30 个控件，人工表足够；提前建工具是过度工程 | 第二批页面数 >10 或控件数 >50 | 第二批执行者 |
| `companion.js:612-613` toast 文案 `🔊 伴读发声已开启` / `🔇…` | 属文本消息，不是控件字形；不影响 I1 | 第二批 companion 清理 | 第二批执行者 |
| `a1_hoeren.js:508-509` 的 `🇩🇪/🇨🇳`（Windows 缺字形） | ADR §5 B 段列了，但文件不在第一切片 4 文件内 | 第二批 / 收到 Windows 显示缺陷报告时 | 第二批执行者 |
| `.cards-topbar h2` 抬到 2.5rem 编辑抬头（标题独占一行、操作下移） | 现状是三栏工具栏（返回键 + 标题 + 5 个操作按钮）；760px 容器内 40px 标题必然挤爆按钮。**需先改 HTML 结构，属设计决策**，不是纯 CSS 调整 | 用户拍板改 cards 抬头结构时；或第二批 cards 深化同批 | 用户拍板 |

---

## [NOTE] Emoji 残留全量清点（第二批后，2026-11-06）

**本批不处理，仅记账。** 第二批只清了「无文字控件」与已点名的空态/角色字形；其余装饰性 emoji 仍大量存在。

### 扫描口径

- 范围：`static/` 全量（`.js` / `.html` / `.css`），**排除生成物 `static/index.html`**（避免与自己内联的分块重复计数）
- 排除：JS 行注释、块注释、`console.*` 输出（不对用户呈现）
- 分类：**A = 删除会丢信息**（字形本身承载状态/语义，且无中文或 `aria-label` 兜底）；**B = 纯装饰**（同句或相邻节点已有中文标签，删掉不影响理解）

### 统计

| 指标 | 数值 |
|---|---|
| UI 面残留总处数 | **376** |
| 涉及文件 | 40 |
| 不同字形 | 87 |
| A 类（删除会丢信息） | **16** |
| B 类（纯装饰、已有中文标签） | **360**（其中 57 行本身无中文，靠相邻节点承载） |

> 已知点名项：`static/js/cards.js:296` 实为 `🎴 3D 扑克翻牌盒 · POKER FLIP STACK`（不是 📕 / "翻牌墨盒"，以代码为准），属 B 类。

### A. 删除会丢信息（16 处，已于第三批清零 2026-11-06）

| 文件:行 | 字形 | 上下文 | 为什么算丢信息 |
|---|---|---|---|
| `static/modals/drawer.html:65` | ✕ | `<button class="drawer-close" … title="关闭工作台 (Esc)">✕` | 纯字形 + `title`，无 `aria-label`，I1 直接违规 |
| `static/modals/import_modal.html:18` | ✕ | 同上（`closeModal()`） | 同上 |
| `static/modals/polish_modal.html:25` | ✕ | 同上 | 同上 |
| `static/modals/settings_modal.html:25` | ✕ | 同上（`closeSettingsModal()`） | 同上 |
| `static/modals/version_preview_modal.html:31` | ✕ | 同上（`closeVersionPreview()`） | 同上 |
| `static/js/main.js:725` | 🔒 | `btn.textContent = "🔒"` | 密码可见性切换，状态只由字形表达 |
| `static/js/main.js:728` | 👁️ | `btn.textContent = "👁️"` | 同上 |
| `static/modals/settings_modal.html:63` | 👁️ | `#btn-toggle-key-vis` 初始字形，仅 `title="显示/隐藏 Key"` | 按钮既无可见文字也无 `aria-label` |
| `static/js/listen-lab.js:474` | ✓ ✗ | `<span class="listen-mark ok/no">` 判题标记 | 正误只靠字形 + 颜色，无文字 |
| `static/js/listen-lab.js:476` | ✓ ✗ | 同上（第二个渲染分支） | 同上 |
| `static/js/a1_writer.js:306` | ⚪ | `<span class="lp-icon">⚪</span>` 等级点 | 等级区分只靠颜色/字形 |
| `static/js/a1_writer.js:428` | 🟢 ⚪ | `icon.textContent = lp.matched ? '🟢' : '⚪'` | 匹配状态只靠字形 |
| `static/js/cp-drawer.js:372` | ✕ | `clearBtn.textContent = '✕'` | 清空按钮无文字、无 `aria-label` |
| `static/js/cp-drawer.js:1341` | ✓ | `iconEl.textContent = '✓'` | 完成态只靠字形 |
| `static/js/reader.js:907` | ✓ | `btn.textContent = "✓"` | 收藏/完成态只靠字形 |
| `static/js/encounter.js:148` | ⚠ | `COVERAGE_DEGRADED_MARK = "⚠"` | 覆盖率降级标记只靠字形 |

> **第三批处置（2026-11-06，PR 待合）**：可删 2（cp-drawer 推演完成 ✓、encounter 覆盖率 ⚠，相邻已有中文）；需加文字 5（listen-lab 判题 2、a1_writer 导向点 2、reader 收藏 1）；需加 `aria-label` 6（5 个模态框关闭键 + cp-drawer 解除绑定）；需加文字+`aria-label` 3（密码显隐 2 + settings 初始态 1）。B 类 360 处未动。

### B. 纯装饰（360 处，按文件聚合）

| 文件 | 处数 | 字形 | 行号 |
|---|---|---|---|
| `static/german/workbench.html` | 20 | ⚠ ✓ ✗ ⭐ 📘 📗 🔥 🎉 ✕ ▶ | 24, 26, 27, 173, 389, 1297, 1300, 1355, 1358, 1363, 1387, 1932, 2101, 2103, 2504, 2508, 2522, 2530, 2535, 2630 |
| `static/js/a1_cards.js` | 21 | ✓ 🌟 ◀ 🔀 🎲 ▶ 💬 🙋 | 167, 179, 415, 450, 483, 491, 492, 493, 494, 542, 587, 631, 632, 633, 634, 670, 712, 713, 714, 715, 751 |
| `static/js/a1_hoeren.js` | 17 | ✓ ⚠ 🔊 🎧 ▶ 📋 🔁 ✅ ❌ 🇩 🇪 🇨 🇳 💡 📌 🔄 | 35, 59, 106, 141, 144, 158, 224, 226, 381, 413, 503, 508, 509, 512, 514, 532, 562 |
| `static/js/a1_lesen.js` | 12 | ⚠ 📖 ✓ 📋 ✉ 🌐 🎯 🪧 ✅ ❌ 💡 🔄 | 27, 51, 97, 150, 164, 211, 254, 257, 300, 457, 462, 480 |
| `static/js/a1_writer.js` | 10 | ✓ ✕ 🎉 📊 ⚠ | 199, 212, 229, 359, 397, 400, 410, 413, 416, 439 |
| `static/js/cards.js` | 20 | ✓ ✕ 🛡 📚 🔀 🎴 ⚠ ✗ | 235, 236, 238, 296, 319, 336, 367, 373, 405, 435, 463, 560, 569, 587, 596, 870, 875, 979, 1243, 1309 |
| `static/js/cloze.js` | 3 | ⚡ 💡 🏆 | 29, 113, 167 |
| `static/js/companion.js` | 6 | ❌ ✓ 🔊 🔇 | 514, 521, 543, 553, 605, 623 |
| `static/js/cp-drawer-proposals.js` | 2 | 📝 ✓ | 34, 125 |
| `static/js/cp-drawer.js` | 13 | ✓ 📄 🦉 ✍ 📝 🎯 ✗ | 488, 491, 494, 503, 643, 645, 661, 666, 830, 832, 1302, 1307, 1312 |
| `static/js/encounter.js` | 4 | ✅ ✓ 🎉 ⚠ | 360, 369, 372, 1129 |
| `static/js/folio.js` | 3 | ✓ 🔥 ○ | 168, 387, 415 |
| `static/js/hard-sentences.js` | 10 | 🔍 ✔ ➕ ➤ ✦ ▶ ✅ 🏁 | 315, 391, 392, 407, 413, 415, 430, 446, 658, 663 |
| `static/js/listen-lab.js` | 14 | ▶ ✓ 🏁 ⚠ 🎙 ✗ 🎉 | 270, 276, 442, 443, 509, 510, 522, 546, 556, 558, 570, 611, 612, 624 |
| `static/js/main.js` | 9 | ✓ 📥 ⚠ ✕ ⚡ | 616, 648, 700, 701, 704, 762, 765, 806, 811 |
| `static/js/player.js` | 3 | ⚠ 🎙 | 50, 357, 457 |
| `static/js/rd-syntax.js` | 2 | ➔ 🔍 | 87, 186 |
| `static/js/reader.js` | 22 | ✓ ⚡ ⚠ 🔗 🧩 ✨ 🌳 🧭 📌 | 285, 392, 416, 446, 447, 448, 450, 451, 485, 500, 531, 561, 862, 937, 991, 1142, 1190, 1199, 1218, 1230, 1250, 1362 |
| `static/js/search.js` | 1 | ⚠ | 325 |
| `static/js/wb-queue.js` | 1 | 🎉 | 164 |
| `static/js/wb-rate.js` | 1 | 🎉 | 76 |
| `static/js/wb-views.js` | 3 | 🔥 ⭐ 📘 📗 ✓ | 113, 381, 384 |
| `static/js/writer.js` | 28 | ✓ ⚠ ✨ 💡 ❌ 💾 ✕ | 309, 402, 405, 438, 439, 518, 527, 549, 715, 839, 840, 942, 974, 993, 1069, 1115, 1118, 1126, 1132, 1133, 1154, 1162, 1212, 1253, 1405, 1406, 1471, 1474 |
| `static/layout/companion.html` | 1 | 💬 | 143 |
| `static/layout/nav_desktop.html` | 3 | 🔍 🧩 ⚙ | 39, 48, 55 |
| `static/modals/cloze_overlay.html` | 6 | ✕ 🎯 📚 ⚡ 💡 ✓ | 21, 31, 38, 45, 73, 87 |
| `static/modals/drawer.html` | 20 | 📝 🌳 🧠 🎯 📖 🦉 ✦ 📡 ✨ ✓ ⚡ ⚖ ✍ 📊 🃏 | 16, 24, 32, 40, 48, 206, 286, 300, 337, 354, 386, 387, 388, 392, 396, 397, 398, 399, 400, 401 |
| `static/modals/import_modal.html` | 4 | ❖ 📰 | 28, 35, 42, 49 |
| `static/modals/player_and_tooltip.html` | 7 | 🎙 ▶ 🔂 🌳 🦉 📝 🔊 | 71, 79, 87, 149, 156, 163, 170 |
| `static/modals/polish_modal.html` | 4 | ✓ ✨ ✕ | 18, 38, 44, 66 |
| `static/modals/quiz_overlay.html` | 4 | ✕ ✗ ✓ | 7, 32, 69, 75 |
| `static/modals/settings_modal.html` | 8 | ⚡ ⚙ 🤖 ⚖ 🧠 🔊 ✓ | 18, 31, 156, 157, 158, 179, 201, 254 |
| `static/views/cards.html` | 5 | ⚔ 🗑 ⚠ 🎴 📑 | 20, 28, 40, 101, 109 |
| `static/views/encounter.html` | 1 | 📥 | 12 |
| `static/views/exam.html` | 5 | ◀ ▶ ⚡ | 53, 62, 120, 126, 183 |
| `static/views/progress.html` | 5 | ⚔ 📚 💬 ✓ | 31, 38, 348, 366, 447 |
| `static/views/reader.html` | 3 | ▶ ⚔ 📥 | 17, 25, 33 |
| `static/views/writer.html` | 18 | 📋 💾 ✍ 🔍 ✨ ✕ ⚡ 💡 📚 📜 📊 🧭 🕒 | 33, 43, 46, 53, 60, 76, 84, 115, 130, 153, 160, 170, 178, 189, 202, 222, 239, 269 |

> 另有 41 处「行内无中文但相邻节点有文案」的装饰（如 `quiz_overlay.html:11/16/21` 模式图标、`import_modal.html:114` 拖拽区 📄、`a1_cards.js:382/508` 空态 🔍、`cp-drawer.js:468/477` 分节图标），已并入上表按文件计数，不单列。

### 下一批建议先动的 3 处

1. **5 个模态框关闭键**（`drawer:65` / `import:18` / `polish:25` / `settings:25` / `version_preview:31`）
   理由：唯一同时满足「纯字形 + 只有 title」的 I1 硬违规；同一个 `.drawer-close` 类一次覆盖 5 处，改动最小、可验证性最高（可加一条静态断言禁止无 `aria-label` 的 `.drawer-close`）。
2. **`#btn-toggle-key-vis` 与 `main.js:725/728` 的 🔒/👁️**
   理由：既是按钮的唯一可见标签，又是密码可见性状态的唯一载体；删或改一个字都会让"当前是明文还是密文"失去表达，屏幕阅读器目前只知道"按钮"。
3. **`listen-lab.js:474/476` 的 ✓/✗ 判题标记**
   理由：正确/错误只由字形 + `.ok/.no` 颜色承担，没有任何文字；对色觉障碍用户是双重失效，且听写/填空两条渲染路径各有一份，属同源缺陷。

---

## [NOTE] Deviation Table (post-execution, filled before merge)

| plan text | what was actually built | why |
|---|---|---|
| T2：`<span class="exam-module-de">Schreiben</span>`（scaffold 示例无括号） | 实际保留括号：`(Schreiben)` | 任务 Injected Instincts 明确「德文名保留在括号内」；以更具体的约束为准，信息量不降 |
| T6：仅列 `.panel-close` / `.panel-char-btn` / `#panel-sound` / `#panel-hide` | 额外给 4 个 `.panel-color-dot` 与 `#panel-color-custom` 补 `aria-label` | 它们是「无文字、无 aria」的按钮，T6 验收第 1 条要求全部按钮可命名；不改视觉、不扩文件 |
| T7：仅列 role 按钮与 `#studio-sound-btn` | 额外给 5 个 `.mascot-color-dot` 与 `#studio-color-picker` 补 `aria-label`，🎨 加 `aria-hidden` | 同上：T7 验收第 3 条要求 studio 段每个 button 有可见文字或 `aria-label`；颜色色块原本只有 `title` |
| T1：`aria-label` 基线「11 处」 | 实测源片段 11 处；若把生成物 `static/index.html` 计入则为 18 处 | 计量口径差异，非基线漂移；以源片段为准（与 ADR §11.1 一致），未触发 E1 |

---

## [NOTE] 验收回执（T10）

- **日期**：2026-11-06
- **执行者回执**：Agent（结构项）；**人工视觉签字**：待用户（T10 为 HITL，未代签）
- **分支**：`feat/frontend-de-emoji-slice1`
- **提交范围**：T0–T7、T9、T10 回执；T8 在独立分支 `docs/readme-zh-only`（PR #248）

### 1. ADR §6 六条失败信号（逐条）

| # | 信号 | 判定 | 证据 |
|---|---|---|---|
| 1 | 删字形后控件既无可见文字、又无 `aria-label` / `aria-pressed` | **未触发** | `companion.html` 15 按钮 unnamed = 0；studio 区域 14 按钮 unnamed = 0；exam / nav 全部有可见文字 |
| 2 | token 迁移导致未要求页面 >5% 视觉差异 | **未触发** | 未做 token 迁移；`style.css` 仅新增 `.exam-module-card` 邻域 3 条规则 |
| 3 | 三个独立评审者判断「删完更空、像没做完」 | **未触发（无评审数据）** | 未组织 3 份独立评审；不以此作为通过依据，视觉判断留给用户签字 |
| 4 | README 删 emoji 后总行数上升 | **未触发** | PR #248：226 行 → 226 行，11 行增 / 11 行删，无散文填充 |
| 5 | 图标集 >15 个或 >12KB | **未触发** | 本切片未引入任何图标集 / SVG 资产 |
| 6 | 第一切片 3 天未收敛 | **未触发** | 同一日内完成 T0–T7、T9 |

### 2. ADR §11.2 失效条件（E1 / E2 / E7）

| 条件 | 判定 | 证据 |
|---|---|---|
| E1：emoji 基数变化 >±20%（全站 551 → 441–661 之外） | **未触发** | 切片 5 文件合计 61 簇；源片段 `aria-label` 仍为 11 处，与 §11.1 一致 |
| E2：垂直切片 3 天未收敛 | **未触发** | 同日收敛 |
| E7：切片文件被重写 / 删除导致 file:line 失效 | **未触发** | 4 个文件均存在，T1 行号与执行时一致 |

### 3. 不变量 I2 / I5

- I2：`git diff --name-only origin/master...HEAD` 共 12 个文件，无依赖清单、无 `static/sw.js`、无 CSP。
- I5：改动仅限 `exam.html` / `nav_mobile.html` / `cards.js` / `companion.html` / `companion.js` / `progress.html` / `style.css` + 生成物 + 4 份文档；未扫其余 37 个文件。

### 4. 命令级回执

- `python tools/check_index_html_sync.py` → `PASS ... sha256 契约一致`，exit 0。
- `.venv\Scripts\python.exe -m pytest tests/test_exam_domain.py tests/test_german_workbench.py tests/test_search_ui.py tests/test_cards_state_split.py tests/test_cards_count_probe.py tests/test_check_index_html_sync.py tests/test_frontend_guards.py -q` → **185 passed, 1 warning**，exit 0。
- emoji 计数：`exam.html` 非注释 0；`nav_mobile.html` 0；`cards.js` 空态 0；`companion.html` 仅保留 4 个角色字形；`progress.html` studio 仅保留 4 个角色字形 + 🎨（已 `aria-hidden`）。

### 5. 结论

- **结构验收：通过**（I1 在全部切片控件上成立；无停止门触发）。
- **人工视觉签字：待用户**。签字前**不推广第二批**，不开始图标集 vendor，不做角色 SVG 化。
- 已登记偏差见 `Deviation Table` 与 ADR-0029 §15。

---

## [NOTE] 执行记录（T1 产出，执行时填写）

| 文件 | 彩色 emoji 簇（前） | 后 | 交互控件数 | 无可见文字控件（前） | 仅有 title（WARN） |
|---|---|---|---|---|---|
| `static/views/exam.html` | 33（非注释；全文件 35） | 0 | 31 | 0 | 3（均有可见文字，title 仅为补充） |
| `static/layout/nav_mobile.html` | 8 | 0 | 8 | 0 | 0 |
| `static/js/cards.js`（空态块） | 3（🎉/🛡️/🎴） | 0 | 0 | 0 | 0 |
| `static/layout/companion.html` | 8 | 保留 4 角色字形 | 15 | 6（`.panel-close`、`#panel-sound`、4 个 `.panel-color-dot`） | 7（4 角色 + 自定义 + 上传 + 收起） |
| `static/views/progress.html`（studio 段） | 9（studio 段） | 保留 4 角色字形（T7 只补 aria） | 10 | 0 | 5 |

**基线核对（T1 Step 3）：**
- 源片段（排除生成物 `static/index.html`）的 `aria-label` = **11 处**，与 ADR §11.1 快照一致；另有 1 处 `aria-labelledby`（`home.html` 的 `#satz-lab`）。
- 本切片 5 个文件的彩色 emoji 簇合计 = **61**（exam 33 + nav 8 + cards 空态 3 + companion 8 + progress studio 9），远小于全站 551，未触发 E1。
- 4 个切片文件在 `master` 上均存在且行号与计划一致，未触发 E7。

---

## [NOTE] Out of Scope（明确不做，不毕业为任务）

- 全站 token 迁移、78 处 11px 收敛（ADR §4 已否决）。
- 图标字体、SVG sprite、CSS mask 方案（ADR §4 已否决）。
- 第二批 37 个文件的 emoji 清理。
- README 的徽章重排、核心特性去粗体、新增「什么场景不该用 DeLector」章节（属 README 工程化的后续批次）。
- `FEATURES.md` / `CHANGELOG.md` / `docs/agents/*` 的字形清理。
- Android 端 UI 验证（本切片只保证 Web 侧源片段；Android assets 随整树复制被动更新）。
- 任何视觉回归测试基建的引入（本仓无此基建，不在此计划内新建）。
- 角色 SVG 化、图标集 vendor、`svg-character-spec.md` 的修改。

### T1 逐控件清点（明细）

| 文件 | 行 | id | 删字形后可见文字 | title | 可访问名来源 | 结论 |
|---|---|---|---|---|---|---|
| `static/views/exam.html` | 5 | （无 id） | ← 返回文库 | — | 可见文字 | OK |
| `static/views/exam.html` | 9 | exam-level-a1 | A1 | — | 可见文字 | OK |
| `static/views/exam.html` | 12 | exam-card-writing | 写作专项 (Schreiben) | — | 可见文字 | OK |
| `static/views/exam.html` | 13 | exam-card-hoeren | 听力模考 (Hörverstehen) | — | 可见文字 | OK |
| `static/views/exam.html` | 14 | exam-card-lesen | 阅读工坊 (Leseverstehen) | — | 可见文字 | OK |
| `static/views/exam.html` | 15 | exam-card-sprechen | 口语问答 (Sprechen) | — | 可见文字 | OK |
| `static/views/exam.html` | 16 | exam-card-vocab | 官方考纲词表 (Wortliste) | — | 可见文字 | OK |
| `static/views/exam.html` | 17 | exam-card-listen | 听力微训 (Hörlabor) | — | 可见文字 | OK |
| `static/views/exam.html` | 18 | exam-card-hardsent | 长难句 (Satz-Labor) | — | 可见文字 | OK |
| `static/views/exam.html` | 24 | exam-tab-formular | 歌德 A1 Teil 1 填表专项 (Formular-Training) | — | 可见文字 | OK |
| `static/views/exam.html` | 31 | exam-tab-email | 歌德 A1 Teil 2 30词短电邮 (E-Mail/Brief Lab) | — | 可见文字 | OK |
| `static/views/exam.html` | 52 | （无 id） | ◀ 上一题 | — | 可见文字 | OK |
| `static/views/exam.html` | 55 | （无 id） | 随机练习 | — | 可见文字 | OK |
| `static/views/exam.html` | 61 | （无 id） | 下一题 ▶ | — | 可见文字 | OK |
| `static/views/exam.html` | 88 | a1-form-check-btn | 立即批改 (5 分) | — | 可见文字 | OK |
| `static/views/exam.html` | 95 | （无 id） | 重填 | — | 可见文字 | OK |
| `static/views/exam.html` | 119 | （无 id） | ◀ 上一题 | — | 可见文字 | OK |
| `static/views/exam.html` | 122 | （无 id） | 随机场景 | — | 可见文字 | OK |
| `static/views/exam.html` | 125 | （无 id） | 下一题 ▶ | — | 可见文字 | OK |
| `static/views/exam.html` | 182 | （无 id） | ⚡ 智能诊断与判分 | — | 可见文字 | OK |
| `static/views/exam.html` | 185 | （无 id） | 套用考场满分模板 | — | 可见文字 | OK |
| `static/views/exam.html` | 191 | （无 id） | ️ 清空 | — | 可见文字 | OK |
| `static/views/exam.html` | 221 | a1-tab-vocab | 官方考纲词表 (700+) | — | 可见文字 | OK |
| `static/views/exam.html` | 228 | a1-tab-hoeren | 听力全真模考 (15题×5套) | — | 可见文字 | OK |
| `static/views/exam.html` | 235 | a1-tab-lesen | 实用阅读工坊 (15题×6套) | — | 可见文字 | OK |
| `static/views/exam.html` | 242 | a1-tab-teil2 | 口语 Teil 2 问答 | — | 可见文字 | OK |
| `static/views/exam.html` | 249 | a1-tab-teil3 | 口语 Teil 3 请求 | — | 可见文字 | OK |
| `static/views/exam.html` | 276 | exam-mode-btn-deck | 扑克牌盒 | 扑克牌叠层翻页模式 | 可见文字 | OK |
| `static/views/exam.html` | 284 | exam-mode-btn-grid | 全景目录 | 目录全景平铺列表 | 可见文字 | OK |
| `static/views/exam.html` | 309 | （无 id） | ⟲ 换材料 | 返回材料选择 | 可见文字 | OK |
| `static/views/exam.html` | 330 | （无 id） | ⟲ 换材料 | 返回材料选择 | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 2 | mob-btn-home | 文库 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 10 | mob-btn-progress | 台账 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 18 | mob-btn-writer | 写作 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 26 | mob-btn-exam | 备考 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 34 | mob-btn-cards | 卡片 (0) | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 42 | mob-btn-german | 背词 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 50 | mob-btn-search | 检索 | — | 可见文字 | OK |
| `static/layout/nav_mobile.html` | 58 | mob-btn-settings | 设置 | — | 可见文字 | OK |
| `static/layout/companion.html` | 11 | companion-avatar | — | — | `aria-label` | OK |
| `static/layout/companion.html` | 22 | （无 id） | ✕ | — | 无 | UNNAMED |
| `static/layout/companion.html` | 27 | （无 id） | — | 歌德猫头鹰 | 仅有 title | WARN |
| `static/layout/companion.html` | 35 | （无 id） | — | 学者猫 | 仅有 title | WARN |
| `static/layout/companion.html` | 43 | （无 id） | — | 灵动狐 | 仅有 title | WARN |
| `static/layout/companion.html` | 51 | （无 id） | — | 包豪斯机甲 | 仅有 title | WARN |
| `static/layout/companion.html` | 59 | panel-btn-custom | ✦ | 自定义角色 | 仅有 title | WARN |
| `static/layout/companion.html` | 69 | （无 id） | — | 上传自定义 SVG 角色 | 仅有 title | WARN |
| `static/layout/companion.html` | 94 | （无 id） | — | — | 无 | UNNAMED |
| `static/layout/companion.html` | 99 | （无 id） | — | — | 无 | UNNAMED |
| `static/layout/companion.html` | 104 | （无 id） | — | — | 无 | UNNAMED |
| `static/layout/companion.html` | 109 | （无 id） | — | — | 无 | UNNAMED |
| `static/layout/companion.html` | 122 | panel-say | 说句话 | — | 可见文字 | OK |
| `static/layout/companion.html` | 129 | panel-sound | — | — | 无 | UNNAMED |
| `static/layout/companion.html` | 136 | panel-hide | ✕ | 收起伴读悬浮球 | 仅有 title | WARN |
| `static/views/progress.html` | 190 | （无 id） | Eule (歌德猫头鹰) | — | 可见文字 | OK |
| `static/views/progress.html` | 198 | （无 id） | Katze (学者猫) | — | 可见文字 | OK |
| `static/views/progress.html` | 206 | （无 id） | Fuchs (灵动狐) | — | 可见文字 | OK |
| `static/views/progress.html` | 214 | （无 id） | Roboter (包豪斯机甲) | — | 可见文字 | OK |
| `static/views/progress.html` | 222 | studio-btn-custom | ✦ 自定义 | — | 可见文字 | OK |
| `static/views/progress.html` | 232 | （无 id） | 上传 SVG | 上传自定义 SVG 矢量伴读角色 | 可见文字 | OK |
| `static/views/progress.html` | 269 | （无 id） | — | 歌德紫 | 仅有 title | WARN |
| `static/views/progress.html` | 276 | （无 id） | — | 朱砂橘 | 仅有 title | WARN |
| `static/views/progress.html` | 283 | （无 id） | — | 学者绿 | 仅有 title | WARN |
| `static/views/progress.html` | 290 | （无 id） | — | 包豪斯蓝 | 仅有 title | WARN |
| `static/views/progress.html` | 297 | （无 id） | — | 墨黑 | 仅有 title | WARN |
| `static/views/progress.html` | 326 | （无 id） | 试听伴读鼓励 | — | 可见文字 | OK |
| `static/views/progress.html` | 333 | studio-sound-btn | 发声已开启 | — | 可见文字 | OK |
| `static/views/progress.html` | 342 | （无 id） | ✓ 保存伴读设置 | — | 可见文字 | OK |
