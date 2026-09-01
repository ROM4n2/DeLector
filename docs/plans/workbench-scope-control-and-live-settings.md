# Workbench 范围切换前置与设置即时生效 · 实施计划

> **Goal**：把核心词模式切换从词库工具栏提到顶栏常驻，并让「每日新词上限」「新词顺序」改动即时作用于当前队列而不丢复习位置。
> **Tech Stack**：Vanilla ES（零构建，单文件 `static/german/workbench.html`）+ Python 3.11 pytest 静态契约测试 + Node 动态探针
> **Spec Reference**：`d:\Obsidian\Coding\08-Projects\DeLector\01-ADR\0002-workbench-scope-control-and-live-settings.md`
> **Baseline**：HEAD `c52ecf0`，410 tests green，v4.9.0 已发布

---

## Global Constraints (MUST)

- **零构建**：`workbench.html` 是单文件内联 `<script>`，不引入模块化/打包。
- **复习位置不丢**：任何队列重算只动 `revIdx` 之后的未评部分。禁止调用 `buildReviewQueue()` 做"刷新"——它 `revIdx = 0` 且重洗牌。
- **配额守恒**：`today.nw` 只计**已评**新词；队列中未评新词不计入，重算不得重复扣减。
- **多写入点齐修**：凡写 `S.settings.dailyNew` 的入口全部挂上重算，且**每处单独变异验证**（只挂一处也能让"函数存在"类断言变绿 → 恒真）。
- **反死测**：写断言前先 `len(re.findall(pattern, slice))`，>1 即不可判别。docstring 里声称的变异必须真跑过。
- **Python 入口 UTF-8 stdout**（德语 IPA 在 Windows GBK 下 `UnicodeEncodeError`）。
- **禁止** `git checkout --` / `git stash` / `git reset --hard`；变异用 `cp` 备份、`cp` 还原、md5 校验。

## 现有落点坐标（已核验 @ c52ecf0）

| 位置 | 内容 |
|---|---|
| `workbench.html:52-61` | `header.top` CSS（`flex-wrap:wrap`）与 `.badge` |
| `workbench.html:245-251` | 移动端媒体块（`nav.tabs` 为 `position:fixed;bottom:0` 底部 dock） |
| `workbench.html:276-281` | `<header class="top">` 标记：h1 + `#dueBadge` |
| `workbench.html:445-451` | 词库工具栏，含待删的 `<select id="wScope">` |
| `workbench.html:1200-1202` | `inScopeWord(w)` —— scope 判定唯一 truth source |
| `workbench.html:1683-1705` | `buildReviewQueue()`：`错题 + dueIds + newIds`，新词天然在尾部 |
| `workbench.html:1707-1718` | `refilterReviewQueueForScope()` —— 尾部手术的既有范本 |
| `workbench.html:1859-1868` | `extraNewWords()` —— 超配额手动追加 |
| `workbench.html:2465` | `const wordFilters = {..., scope: "all"}` |
| `workbench.html:2528-2545` | `renderWords()` 过滤链（搜索与 scope 串联 AND） |
| `workbench.html:2563-2575` | 筛选控件事件绑定数组 |
| `workbench.html:2765-2771` | `setDailyNew` change handler（不动队列） |
| `workbench.html:2772-2777` | `setNewOrder` change handler（toast「次日生效」） |
| `workbench.html:2808-2814` | `btnApplyPlan`（同样写 dailyNew、同样不动队列） |
| `workbench.html:3346-3360` | `renderHeaderBadge()` |
| `test_german_workbench.py:624-633` | 钉 `#wScope` 存在于词库 toolbar（**Task 2 需迁移**） |
| `test_german_workbench.py:663-674` | 钉 `#wScope` 进绑定数组并写回 scope（**Task 2 需迁移**） |
| `test_german_workbench.py:855-862` | 钉 `#wScope` change handler 调 `refilterReviewQueueForScope()`（**Task 2 需迁移**） |

**测试命令**：`PYTHONIOENCODING=utf-8 python -m pytest test_german_workbench.py -q`
**全量**：`PYTHONIOENCODING=utf-8 python -m pytest -q`（当前 410）
**语法闸**：抽取内联 `<script>` 跑 `node --check`

---

### Task 1: 顶栏分段控件 + 徽标模式前缀 [Role: TDD Builder]

**Files**
- Modify: `static/german/workbench.html:52-61`（`.seg` 系列 CSS）
- Modify: `static/german/workbench.html:276-281`（header 标记插入控件）
- Modify: `static/german/workbench.html:3346-3360`（`renderHeaderBadge` 文案带模式）
- Test: `test_german_workbench.py`

**Interfaces**
- Consumes: `wordFilters.scope`、`inScopeWord(w)`、`refilterReviewQueueForScope()`、`renderWords()`、`renderHeaderBadge()`
- Produces: `<div id="scopeSeg">` 含 `data-scope="all"` / `data-scope="core"` 两个 `<button>`；`syncScopeControls()`（把当前 scope 反映到控件 `.active` 态）

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 1: 顶栏范围分段控件 + 徽标模式前缀。
> Goal: 把核心词模式切换提到 `<header class="top">` 同一 flex 行常驻可见，徽标文案改为 `⭐核心 · 今日待学 12` / `全部 · 今日已完成 ✓`。
> Target Files: Modify `static/german/workbench.html`，Test `test_german_workbench.py`。
> 先读 ADR `d:\Obsidian\Coding\08-Projects\DeLector\01-ADR\0002-workbench-scope-control-and-live-settings.md` 第 3.1 节。
> 约束：
> - 控件插进**已有的** `<header class="top">` flex 行（`workbench.html:276-281`），不新建一行容器；`header.top` 已是 `flex-wrap:wrap`，窄屏换行是接受的代价。
> - 点击 handler 必须复用既有链路：写 `wordFilters.scope` → `refilterReviewQueueForScope()` → `renderWords()` → `renderHeaderBadge()`。**不要**调 `buildReviewQueue()`（它 `revIdx=0` 会跳回第一张）。
> - 本任务**保留**词库里的 `#wScope`（Task 2 才删），但两个控件必须同步：切顶栏后回写 `select.value`，切 select 后刷新分段控件 `.active`。抽一个 `syncScopeControls()` 统一做。
> - 徽标同时承载模式与待学数，`renderHeaderBadge()` 的 `pending>0` / `已完成` 两个分支都要带模式前缀。
> TDD Steps:
> 1. 写失败测试（RED）：① `#scopeSeg` 存在于 `<header class=\"top\">` **切片内**（不是全文件搜——全文件搜到处都真）；② 两个 button 的 `data-scope` 覆盖 all/core；③ 点击 handler 里出现 `refilterReviewQueueForScope` 且**不出现** `buildReviewQueue`；④ `renderHeaderBadge` 函数体内两个分支都引用模式文案。
> 2. 跑 `PYTHONIOENCODING=utf-8 python -m pytest test_german_workbench.py -q` 确认 RED。
> 3. 最小实现（GREEN）。
> 4. 变异验证：把 handler 里的 `refilterReviewQueueForScope()` 换成 `buildReviewQueue()` → 断言③必须红；删掉一个 `data-scope` → 断言②必须红。用 `cp` 备份还原并 md5 校验。
> 5. `node --check` 抽取的内联 script。
> Return: 测试执行证据 + 变异红证据 + `git diff --stat`（证明改动留在树里）。"

**Step Breakdown**
- [ ] Step 1: 写 4 条失败测试（切片锚定 header，不做全文件搜索）
- [ ] Step 2: 跑测试确认 RED 且报错信息符合预期
- [ ] Step 3: 加 `.seg` CSS + header 标记 + `syncScopeControls()` + handler（GREEN）
- [ ] Step 4: `renderHeaderBadge` 两分支加模式前缀
- [ ] Step 5: 变异验证 2 发致红，`cp` 还原 + md5
- [ ] Step 6: `node --check` + 原子提交

---

### Task 2: scope 收敛为单一写入口，删除词库 `#wScope` [Role: TDD Builder]

**Files**
- Modify: `static/german/workbench.html:445-451`（删 select）
- Modify: `static/german/workbench.html:2563-2575`（绑定数组去掉 `wScope`）
- Modify: `test_german_workbench.py:624-633, 663-674, 855-862`（三条测试迁移到顶栏控件）

**Interfaces**
- Consumes: Task 1 产出的 `#scopeSeg` / `syncScopeControls()`
- Produces: `wordFilters.scope` 全局唯一写入口（仅顶栏控件）

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 2: 删除词库工具栏的 `#wScope`，scope 收敛为单一写入口。
> Goal: 顶栏控件已全局可见（Task 1 已落），保留 select 等于同一状态两个写入口、需双向同步、漏一处就出现「顶栏显示核心、词库下拉显示全部」。
> Target Files: Modify `static/german/workbench.html`、`test_german_workbench.py`。
> 约束：
> - 删 `<select id=\"wScope\">`（`workbench.html:445-451`）与绑定数组里的 `\"wScope\"`（`:2563`），并删掉 handler 里 `wordFilters.scope = $(\"wScope\").value;` 这行。
> - `renderWords()` **继续**读 `wordFilters.scope`，不动（scope 是全局模式，词库列表跟随）。
> - Task 1 的 `syncScopeControls()` 里对 select 的回写一并删干净，别留悬空 `$(\"wScope\")` —— 本项目有过「用了但没 import / 取了但元素不存在」导致整段 handler 挂掉的回归（v4.8.3）。删完必须确认全文件不再出现 `wScope`。
> - **迁移而非删除测试**：钉 `#wScope` 的测试共**三**条 —— `test_german_workbench.py:624-633`（toolbar 里存在、两档齐）、`:663-674`（进绑定数组、写回 `wordFilters.scope`）、`:855-862`（change handler 调 `refilterReviewQueueForScope()`）。三条全部改成钉顶栏 `#scopeSeg` 的等价覆盖。覆盖不得净减少，尤其第三条守的是「切模式必须同步复习队列」这个真不变式，不许趁机丢掉。
> TDD Steps:
> 1. 先把**三条**测试改为钉顶栏控件（此时应仍 GREEN，因 Task 1 已落）；再删 select（RED 若有遗漏引用）。
> 2. 跑全量 `PYTHONIOENCODING=utf-8 python -m pytest -q`。
> 3. `grep -c wScope static/german/workbench.html` 必须为 0，`grep -c wScope test_german_workbench.py` 也必须为 0。
> 4. `node --check`。
> 5. 变异验证**两发**：① 删顶栏 handler 里 `wordFilters.scope = ...` 那行 → 迁移后的第二条必须红；② 删顶栏 handler 里的 `refilterReviewQueueForScope()` → 迁移后的第三条必须红。两发都要真跑，证明迁移后的断言仍有判别力、不是走过场。
> Return: 测试证据 + 两处 wScope 计数 + 逐发变异红证据 + `git diff --stat`。"

**Step Breakdown**
- [ ] Step 1: 三条测试迁移到 `#scopeSeg`，确认仍 GREEN
- [ ] Step 2: 删 select + 绑定数组条目 + handler 赋值行 + `syncScopeControls` 里的 select 回写
- [ ] Step 3: 源码与测试两处 `grep -c wScope` 均为 0，确认无悬空引用
- [ ] Step 4: 全量测试 + `node --check`
- [ ] Step 5: 变异验证两发各自致红
- [ ] Step 6: 原子提交

---

### Task 3: 搜索旁路 scope [Role: TDD Builder]

**Files**
- Modify: `static/german/workbench.html:2533`（过滤链 scope 条件）
- Modify: `static/german/workbench.html`（结果行淡色小标）

**Interfaces**
- Consumes: `wordFilters.q`、`wordFilters.scope`
- Produces: 搜索非空时不应用 scope 过滤；非核心命中行带视觉标记

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 3: 核心模式下搜索旁路 scope。
> Goal: `renderWords()` 过滤链上搜索与 scope 是串联 AND（`workbench.html:2530` 与 `:2533`），核心模式下搜非核心词结果为空。删掉词库 select 后（Task 2），用户查非核心词只能去顶栏切模式，而切模式会触发尾部重算、可能落卡吃配额 —— 浏览行为污染复习进度。
> Target Files: Modify `static/german/workbench.html`，Test `test_german_workbench.py`。
> 约束：
> - 改动限于过滤链一行：scope 条件加上「搜索为空」前提。**不新增状态变量**、**不碰 `revQueue`**、**不改 `wordFilters.scope`**。
> - 搜索命中的非核心词行加淡色小标（复用既有 CSS token，不新造颜色），让用户看得出这条不在当前模式内。
> - `wordFilters.q` 已在 handler 里 `.trim()`，判空以 trim 后为准。
> TDD Steps:
> 1. 写失败测试（RED）：在 `renderWords` **函数体切片内**断言 scope 过滤条件带搜索前提。注意反死测——先数该 pattern 在切片里出现几次，>1 就锚定整个条件表达式而非片段。
> 2. 跑测试确认 RED。
> 3. 最小实现（GREEN）。
> 4. 变异验证：去掉搜索前提（还原成无条件 scope 过滤）→ 必须红。
> 5. 这条**行为**（核心模式下搜 `Absender` 能出结果）静态正则证明不了，留给 Task 6 的动态探针覆盖，本任务在测试 docstring 里注明该分工。
> Return: 测试证据 + 变异红证据 + `git diff --stat`。"

**Step Breakdown**
- [ ] Step 1: 写失败测试（函数体切片锚定 + 出现次数预检）
- [ ] Step 2: 确认 RED
- [ ] Step 3: 过滤链加搜索前提（GREEN）
- [ ] Step 4: 非核心命中行加淡色小标
- [ ] Step 5: 变异验证致红
- [ ] Step 6: 原子提交

---

### Task 4: `renormalizeQueueTail()` —— dailyNew 即时生效（含手动追加豁免）[Role: TDD Builder]

**Files**
- Create（函数）: `static/german/workbench.html`，紧邻 `refilterReviewQueueForScope()`（`:1707-1718`）之后
- Modify: `static/german/workbench.html:1859-1868`（`extraNewWords` 登记豁免 id）
- Modify: `static/german/workbench.html:2765-2771`（`setDailyNew` 挂载）
- Modify: `static/german/workbench.html:2808-2814`（`btnApplyPlan` 挂载）

**Interfaces**
- Consumes: `revQueue`、`revIdx`、`S.cards`、`S.settings.dailyNew`、`logToday()`、`inScopeWord(w)`、`shuffle()`、`curView`、`renderReview()`
- Produces: `function renormalizeQueueTail()`；`const manualExtraIds = new Set()`（内存态，与 `revQueue` 同生命周期）

**参考实现骨架**（供 builder 对齐语义，非逐字要求）

```js
/* 尾部重算：只动 revIdx 之后的未评部分，已复习的一律不动、位置不丢。
 * today.nw 只计已评新词，队列中未评新词不计入，故重算不重复扣减配额。
 * revIdx >= revQueue.length（今日刷完）时 slice(0, revIdx+1) 即整队、tail 为空，
 * 补进来的词正好落在 revIdx 位置 —— 不需要特判。 */
function renormalizeQueueTail() {
  const head = revQueue.slice(0, revIdx + 1);
  const tail = revQueue.slice(revIdx + 1);
  const keptDue = tail.filter(id => S.cards[id]);              // 到期卡不受配额管
  const newInTail = tail.filter(id => !S.cards[id]);
  const pinned = newInTail.filter(id => manualExtraIds.has(id)); // 手动追加豁免
  const normal = newInTail.filter(id => !manualExtraIds.has(id));
  const quota = Math.max(0, S.settings.dailyNew - (logToday().nw || 0));
  let next = normal.slice(0, quota);                            // 调低则裁
  if (next.length < quota) {                                    // 调高则补
    const inQ = new Set(revQueue);
    let pool = S.words.filter(w => !S.cards[w.id] && !inQ.has(w.id) && inScopeWord(w)).map(w => w.id);
    if (S.settings.newOrder !== "seed") pool = shuffle(pool);
    next = next.concat(pool.slice(0, quota - next.length));
  }
  revQueue = head.concat(keptDue, next, pinned);
  if (curView === "review") renderReview();
}
```

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 4: `renormalizeQueueTail()`，让「每日新词上限」改动即时生效。
> Goal: 现状是 `setDailyNew` 存设置、`renderPlan()`、toast，**从不碰 `revQueue`**；而 `renderReview()` 只在 `queueDay !== today || revIdx >= revQueue.length` 时重建 —— 于是队列没刷完时改数量毫无反应，刚好刷完时又立刻生效，**同一操作两种结果**。
> Target Files: Modify `static/german/workbench.html`，Test `test_german_workbench.py`。
> 先读 ADR 第 3.4 与 3.6 节，以及计划文档里的参考实现骨架。
> 约束（每条都要落到断言）：
> - **只动 `revIdx` 之后**：`revIdx` / `ratedCount` / `queueDay` 一律不写。禁止调 `buildReviewQueue()`。
> - **配额口径与 `buildReviewQueue` 一致**：`Math.max(0, S.settings.dailyNew - (logToday().nw || 0))`。
> - **`extraNewWords()` 追加的词豁免裁剪**：用内存 `Set` 登记；`revQueue` 本就不持久化、刷新即重建，Set 与之同生命周期 —— **在注释里写明这一点**，避免后人误以为该持久化。
> - **两个写入点都挂**：`setDailyNew`（`:2765`）与 `btnApplyPlan`（`:2808`），且两处都要补 `renderHeaderBadge()`（顶栏「今日待学」用的就是 dailyNew，现在也是陈的）。
> - **切范围不补齐**：`refilterReviewQueueForScope()` 保持只过滤、不调 `renormalizeQueueTail()`。这是 ADR 3.6 明确保留的不对称（收窄意图 ≠ 数量意图），不要"顺手统一"。
> TDD Steps:
> 1. 写失败测试（RED）：① `renormalizeQueueTail` 存在且函数体内不出现 `buildReviewQueue`；② 函数体内 `revIdx` 只被读不被赋值；③ 配额表达式与 `buildReviewQueue` 里那条一致；④ `setDailyNew` handler 体内同时出现 `renormalizeQueueTail()` 与 `renderHeaderBadge()`；⑤ `btnApplyPlan` handler 体内同样；⑥ `refilterReviewQueueForScope` 体内**不**出现 `renormalizeQueueTail`。
> 2. 跑测试确认 RED。
> 3. 实现（GREEN）。
> 4. **变异验证，④⑤ 必须分别各验一次**：只删 `setDailyNew` 里的调用 → ④红⑤绿；只删 `btnApplyPlan` 里的 → ⑤红④绿。若一发变异同时打红两条，说明断言没锚到各自函数体，重写。这是本项目的老坑（ADR-0001 交付时回填只挂了一个调用点）。
> 5. 另外变异：函数体内加 `revIdx = 0` → ②红；把配额改成 `dailyNew` 不减 nw → ③红。
> 6. `node --check`。
> Return: 测试证据 + **逐发**变异红证据（尤其④⑤各自独立） + `git diff --stat`。"

**Step Breakdown**
- [ ] Step 1: 写 6 条失败测试（各自锚定所属函数体切片）
- [ ] Step 2: 确认 RED
- [ ] Step 3: 实现 `renormalizeQueueTail()` + `manualExtraIds` Set（GREEN）
- [ ] Step 4: `extraNewWords()` 登记豁免 id
- [ ] Step 5: 两个写入点挂载 + 补 `renderHeaderBadge()`
- [ ] Step 6: 变异验证（④⑤ 独立各一发，另 2 发）
- [ ] Step 7: `node --check` + 原子提交

---

### Task 5: newOrder 即时生效 + 文案更正 [Role: TDD Builder]

**Files**
- Modify: `static/german/workbench.html:2772-2777`

**Interfaces**
- Consumes: Task 4 的 `renormalizeQueueTail()`
- Produces: newOrder change 即时作用于"今后追加的新词"，不重排已在队列中的词

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 5: 新词顺序（newOrder）改为即时生效。
> Goal: 现在 toast 明说「次日队列生效」（`workbench.html:2775`）。Task 4 让 dailyNew 即时后，同一设置面板里两种脾气仍在。
> Target Files: Modify `static/german/workbench.html`，Test `test_german_workbench.py`。
> 约束：
> - **只影响今后追加的词**，不重排已在队列中的词（重排会打乱当前位置，违反不变式）。`renormalizeQueueTail()` 里的补词分支已经读 `S.settings.newOrder`，所以挂上它即可 —— 不要另写排序逻辑。
> - toast 文案改为「新词顺序：乱序（影响今后追加的词）」/「…按词表（影响今后追加的词）」。旧文案「次日队列生效」**必须从文件里消失**，否则用户读到的仍是旧承诺。
> TDD Steps:
> 1. 写失败测试（RED）：① `setNewOrder` handler 体内出现 `renormalizeQueueTail()`；② 全文件不再出现「次日队列生效」。
> 2. 确认 RED → 实现 → GREEN。
> 3. 变异验证：删掉 handler 里的调用 → ①红；把文案改回「次日队列生效」→ ②红。
> Return: 测试证据 + 变异红证据 + `git diff --stat`。"

**Step Breakdown**
- [ ] Step 1: 写 2 条失败测试
- [ ] Step 2: 确认 RED
- [ ] Step 3: handler 挂 `renormalizeQueueTail()` + 改 toast 文案（GREEN）
- [ ] Step 4: 变异验证 2 发致红
- [ ] Step 5: 原子提交

---

### Task 6: 行为级动态探针 `tools/wb_queue_probe.mjs` [Role: TDD Builder]

**Files**
- Create: `tools/wb_queue_probe.mjs`
- Test: `test_german_workbench.py`（调用探针 `--json` 并断言）

**Interfaces**
- Consumes: 从 `workbench.html` 切片出的 `SEED_WORDS`、`inScopeWord`、`buildReviewQueue`、`refilterReviewQueueForScope`、`renormalizeQueueTail`、`extraNewWords`、`renderWords` 过滤谓词
- Produces: `--json` 输出 `{liveDailyNew, extraExempt, scopeNoTopUp, searchBypass}`

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 6: 行为级动态探针 `tools/wb_queue_probe.mjs`。
> Goal: 静态正则只能证明「代码长这样」，证明不了「改数量后队列真的变了」。参照**已有的** `tools/wb_merge_probe.mjs`（v4.9.0 交付），沿用其全部反死测手法。
> Target Files: Create `tools/wb_queue_probe.mjs`，Test `test_german_workbench.py`。
> 约束（照抄 `wb_merge_probe.mjs` 的做法，不要另起炉灶）：
> - **切片而非重抄**：用括号配对扫描器（跳过字符串与注释）从 `workbench.html` 抽真实函数体，丢进 `node:vm` 执行。探针里**不得**有任何一份重抄的实现 —— 重抄的话实现回退了探针照样绿。
> - **切片护栏断言**：抽出的 `renormalizeQueueTail` 必须含 `manualExtraIds`、`refilterReviewQueueForScope` 必须**不含** `renormalizeQueueTail`。切歪直接抛错，不许静默假绿。
> - `--json` 时 stdout 只有一个 JSON，日志走 stderr，退出码 0。
> 必须覆盖的行为（每条都是静态测试证明不了的）：
> 1. `liveDailyNew`：队列**未刷完**时把 dailyNew 15→30，尾部未学新词数变为 `30 - 今日已评新词数`；`revIdx` / 已评部分**逐字节不变**。再 30→5，尾部裁到 5，仍不动已评部分。
> 2. `extraExempt`：先 `extraNewWords()` 追加 20 个超配额词，再把 dailyNew 调低，**那 20 个一个都不能少**。
> 3. `scopeNoTopUp`：切到 core 后队列只过滤不补齐 —— 断言尾部新词数 **小于** 配额允许值（这是 ADR 3.6 刻意保留的不对称，探针要把它钉住，防止后人"顺手统一"）。
> 4. `searchBypass`：core 模式下用非核心词（如 `Absender`）走 `renderWords` 过滤谓词，命中数 > 0；清空搜索后同一个词命中数为 0。
> 5. 幂等：连调两次 `renormalizeQueueTail()`，第二次队列快照逐字节不变。
> 6. `finishedStateScopeSwitch`（**Task 1 复核新发现，必须覆盖**）：`refilterReviewQueueForScope()` 结尾有 `if (curView === "review") renderReview();`，而 `renderReview()` 的门是 `if (queueDay !== today || revIdx >= revQueue.length) buildReviewQueue()`。Task 1 之前 `#wScope` 在词库视图、`curView` 永远不是 `"review"`，这条分支是**死代码**；顶栏控件让它第一次活了。后果：**今日队列刷完后切模式会走 `buildReviewQueue()` 补满配额，直接违反 ADR 3.6「切范围不补齐」**。探针要构造 `revIdx >= revQueue.length` 的完成态、切 scope、观测尾部新词数。先**如实报告**观测到的实际行为与配额值，**不要**自行决定怎么改——是收紧（完成态也不补）还是承认例外（并改掉 `workbench.html` 里那句写死「禁止 buildReviewQueue()」的绝对化注释），由编排者裁决。
> TDD Steps:
> 1. 先写调用探针的 pytest 测试（RED，探针不存在）。
> 2. 实现探针（GREEN）。
> 3. **对每条行为逐一变异**：改坏对应实现，确认探针红。至少 5 发。
> 4. 若探针断言不过，先怀疑**实现**有 bug，把哪个字段对不上、实际值多少报出来 —— **不要**改期望值或往探针里塞假数据凑绿。
> Return: 探针 `--json` 实际输出摘要 + 逐发变异红证据 + 测试证据 + `ls -la tools/wb_queue_probe.mjs`。"

**Step Breakdown**
- [ ] Step 1: 写调用探针的 pytest 测试（RED）
- [ ] Step 2: 实现切片器 + 护栏断言
- [ ] Step 3: 实现 5 组行为场景
- [ ] Step 4: 逐条变异验证（≥5 发）
- [ ] Step 5: `node --check` + 原子提交

---

### Task 7: 全量回归与发布面同步 [Role: Verifier]

**Files**
- Modify: `README.md`（Tests badge、`test_german_workbench.py` 用例数、特性节补"设置即时生效"、路线图条目）
- Modify: `.agent-context.md`（Version Baseline）
- Modify: `android/app/build.gradle`、`static/sw.js`、`static/index.html`（版本三处落点，若发版）

**Subagent Prompt Scaffold (for /vault-exec)**

> "Implement Task 7: 全量回归与发布面同步。
> Steps:
> 1. `PYTHONIOENCODING=utf-8 python -m pytest -q`（基线 410，报增量）。
> 2. 抽取 `workbench.html` 内联 `<script>` 跑 `node --check`（v4.8.3 出过 pytest 全绿但整站交互死光的回归）。
> 3. `node tools/wb_queue_probe.mjs --json` 与 `node tools/wb_merge_probe.mjs --json` 各跑一次，确认都是退出码 0。
> 4. README 同步：Tests badge、`test_german_workbench.py` 用例数、特性节补"设置即时生效"、路线图新增条目。**注意下载表**（v4.9.0 就漏在这里）—— 它现在由 `test_writer_mobile.py::test_readme_download_table_points_at_current_version` 钉着，漏 bump 会红。
> 5. **不要**自行决定是否 bump 版本与打 tag —— 那是发布动作，报告给编排者由用户拍板。
> Return: 逐项结果 + PASS/FAIL 判定。不提交、不丢弃任何改动。"

**Step Breakdown**
- [ ] Step 1: 全量 pytest，报增量
- [ ] Step 2: `node --check` 语法闸
- [ ] Step 3: 两个探针各跑一次
- [ ] Step 4: README / `.agent-context.md` 同步
- [ ] Step 5: 版本与 tag 交由用户决定

---

## 任务依赖图

```
Task 1 (顶栏控件) ──► Task 2 (删 select)
                          │
Task 3 (搜索旁路) ◄───────┘   （Task 2 删了 select，Task 3 才是必需的补救）

Task 4 (尾部重算) ──► Task 5 (newOrder 即时)
        │                    │
        └────────┬───────────┘
                 ▼
          Task 6 (动态探针)  ← 覆盖 Task 3/4/5 的行为
                 ▼
          Task 7 (全量回归)
```

Task 1→2→3 与 Task 4→5 两条链**互不依赖**，可并行派发；Task 6 必须等两条链都落地。

## 已知风险与预置对策

| 风险 | 对策 |
|---|---|
| 删 `#wScope` 留下悬空 `$("wScope")` 引用 → handler 整段抛错、交互静默全死（v4.8.3 同类回归） | Task 2 Step 3 强制 `grep -c wScope == 0`；Task 7 `node --check` |
| 「两个写入点都挂」被单点满足的恒真断言蒙混 | Task 4 Step 6 要求 ④⑤ **各自独立**变异一发，一发同时打红两条即判定断言失效需重写 |
| 后人"顺手统一"让切范围也补齐配额，推翻 ADR 3.6 | Task 6 场景 3 把这条不对称**正向钉死**在探针里 |
| 豁免 Set 被误改成持久化 | Task 4 要求在注释里写明与 `revQueue` 同生命周期的理由 |
| `inScopeWord(w)` 对 `!w` 返回 true，孤儿 id 能活过 refilter 但活不过重建 | 既有不一致，**本轮不改**；Task 6 若观测到可在报告中列为后续项，不擅自扩大范围 |

## 验收标准（Definition of Done）

- 全量 pytest 绿，增量用例数据实报告
- 每条新断言都有**实跑过**的变异红证据；docstring 里声称的变异不得是空话
- `node --check` 两个内联 script 块通过
- 两个动态探针退出码 0
- README 发布面同步（下载表已有测试守）
- 版本与 tag 由用户拍板，agent 不自行发布
