# Workbench 核心词模式 实施计划

> **Goal**: 在德语背词工作台（Workbench）中加入"核心词模式"——在现有 684 个种子词基础上，通过 tag 标记 + 过滤的方式，提供一个约 235 词的核心词子集视图，切换模式不影响 FSRS 进度。
> **Tech Stack**: Vanilla JavaScript (ES5+), single HTML file (`static/german/workbench.html`, 3326 lines), localStorage, FSRS-6
> **Spec Reference**: ADR-0001: `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0001-workbench-core-words-mode.md`
> **Global Constraints**: 不引入外部依赖；不破坏现有 wb-sync/wb-full 导入导出格式；词有且只有一条 FSRS 记录；所有计数动态计算不硬编码

---

## Task 0: 准备核心词 ID 列表 + 新词定义

**Files:**
- Modify: `static/german/workbench.html:735` (SEED_WORDS 定义上方插入常量)
- Test: `test_german_workbench.py` (新增断言)

**Interfaces:**
- Produces: `const CORE_WORD_SEED_IDS = new Set(["a1-0003", "a1-0004", ...]);` (213 个精确+模糊匹配的种子词 ID)
- Produces: `const CORE_CUSTOM_WORDS = [...]` (22 个新词定义，从 customWords 中筛选而来)
- Consumes: `SEED_WORDS` (line 735)

**Step Breakdown:**
- [ ] **Step 1: 生成精确匹配列表** — 从已验证的 211 个精确匹配 + 2 个人工确认模糊匹配（a1-0473 Partnerin, a1-0603 übernachten）生成 `CORE_WORD_SEED_IDS` Set
- [ ] **Step 2: 筛选并整理 22 个新词** — 从 24 个未匹配词中剔除 `mit Karte`（短语，不是单词）和 `aufmachen`（假阳性），剩余 22 个整理为 SEED_WORDS 格式的对象（id 用 `core-001` 起），定义 `CORE_CUSTOM_WORDS` 数组
- [ ] **Step 3: 在 SEED_WORDS 上方插入两个常量** — 加注释说明来源和数量
- [ ] **Step 4: 写测试（RED）** — 在 `test_german_workbench.py` 新增断言：`CORE_WORD_SEED_IDS` 存在且大小为 213；`CORE_CUSTOM_WORDS` 存在且大小为 22；每个 CORE_CUSTOM_WORDS 有必要字段
- [ ] **Step 5: 跑测试确认通过（GREEN）**

**Subagent Prompt Scaffold:**
> "Implement Task 0: Core word constants and new word definitions.
> Goal: Add CORE_WORD_SEED_IDS (Set of 213 seed word IDs) and CORE_CUSTOM_WORDS (array of 22 new word objects) to workbench.html, plus tests.
> Target Files:
> - Modify: `static/german/workbench.html` — insert two consts right BEFORE line 735 (the `const SEED_WORDS = [...]` line). Put them on separate lines with comments.
> - Test: `test_german_workbench.py` — add new test function `test_core_words_constants_exist`
>
> Exact data:
> CORE_WORD_SEED_IDS = Set containing these 213 IDs:
> a1-0003,a1-0004,a1-0007,a1-0009,a1-0011,a1-0013,a1-0014,a1-0017,a1-0022,a1-0023,a1-0024,a1-0025,a1-0029,a1-0030,a1-0035,a1-0037,a1-0040,a1-0042,a1-0043,a1-0044,a1-0045,a1-0046,a1-0047,a1-0054,a1-0057,a1-0058,a1-0060,a1-0064,a1-0068,a1-0069,a1-0071,a1-0073,a1-0076,a1-0077,a1-0080,a1-0081,a1-0083,a1-0084,a1-0085,a1-0086,a1-0087,a1-0094,a1-0101,a1-0108,a1-0109,a1-0110,a1-0112,a1-0113,a1-0116,a1-0128,a1-0129,a1-0131,a1-0133,a1-0136,a1-0137,a1-0139,a1-0141,a1-0145,a1-0147,a1-0171,a1-0173,a1-0176,a1-0181,a1-0185,a1-0188,a1-0189,a1-0190,a1-0194,a1-0198,a1-0203,a1-0208,a1-0209,a1-0212,a1-0213,a1-0215,a1-0223,a1-0226,a1-0227,a1-0229,a1-0231,a1-0233,a1-0234,a1-0235,a1-0239,a1-0240,a1-0241,a1-0244,a1-0247,a1-0255,a1-0257,a1-0263,a1-0264,a1-0265,a1-0269,a1-0271,a1-0281,a1-0296,a1-0300,a1-0305,a1-0308,a1-0314,a1-0317,a1-0321,a1-0323,a1-0328,a1-0330,a1-0335,a1-0337,a1-0338,a1-0342,a1-0346,a1-0347,a1-0350,a1-0352,a1-0356,a1-0358,a1-0359,a1-0364,a1-0365,a1-0366,a1-0367,a1-0369,a1-0370,a1-0371,a1-0372,a1-0374,a1-0380,a1-0381,a1-0384,a1-0394,a1-0400,a1-0404,a1-0419,a1-0420,a1-0428,a1-0429,a1-0436,a1-0445,a1-0448,a1-0450,a1-0451,a1-0457,a1-0460,a1-0473,a1-0475,a1-0479,a1-0480,a1-0481,a1-0482,a1-0484,a1-0485,a1-0487,a1-0493,a1-0499,a1-0500,a1-0501,a1-0502,a1-0504,a1-0505,a1-0509,a1-0512,a1-0514,a1-0518,a1-0525,a1-0530,a1-0536,a1-0555,a1-0557,a1-0562,a1-0564,a1-0566,a1-0571,a1-0572,a1-0573,a1-0580,a1-0581,a1-0582,a1-0585,a1-0586,a1-0588,a1-0591,a1-0592,a1-0593,a1-0595,a1-0598,a1-0599,a1-0603,a1-0604,a1-0613,a1-0614,a1-0615,a1-0616,a1-0617,a1-0618,a1-0620,a1-0621,a1-0622,a1-0624,a1-0625,a1-0631,a1-0642,a1-0643,a1-0644,a1-0645,a1-0651,a1-0655,a1-0664,a1-0665,a1-0667,a1-0668,a1-0677,a1-0681,a1-0683
> (211 exact + a1-0473 fuzzy Partnerin + a1-0603 fuzzy übernachten = 213 total)
>
> CORE_CUSTOM_WORDS = 22 words from the unmatched list (excluding 'mit Karte' phrase and 'aufmachen' false positive), each with fields: id ('core-001' through 'core-022'), hw, pos, gloss, ipa (from customWords if present else ''), ex (from customWords ex[0] if present else []), letter (first letter of headword after article, uppercase), page: 0, tags: ['core'], custom: true, up: Date.now() placeholder (use 0, will be set on load)
>
> The 22 unmatched words to include (with their data from delector_custom_words.json):
> u-008 der Wohnort m. 居住地
> u-012 die Staatsangehörigkeit f. 国籍
> u-013 die Nationalität f. 国籍
> u-017 geschieden Adj 离异的
> u-018 verwitwet Adj 丧偶的
> u-066 das Mittagessen n. 午餐
> u-067 das Abendessen n. 晚餐
> u-081 der Käse m. 奶酪
> u-089 der Zucker m. 糖
> u-111 der Stuhl m. 椅子
> u-119 zumachen V 关上
> u-142 umsteigen V 换乘
> u-160 der Supermarkt m. 超市
> u-174 der Euro m. 欧元
> u-175 der Cent m. 欧分
> u-186 das Büro n. 办公室
> u-193 der Feierabend m. 下班
> u-207 das Paket n. 包裹
> u-220 die Apotheke f. 药店
> u-221 das Medikament n. 药物
> u-235 ergänzen V 补充完整
> u-236 zuordnen V 连线；归类
>
> IMPORTANT: Read the original delector_custom_words.json at d:/Ran/Goethe_A1/delector_custom_words.json to get the exact data (ipa, ex arrays) for these 22 words. Do NOT fabricate IPA or example sentences.
>
> TDD Steps:
> 1. First write the test in test_german_workbench.py (it will fail because consts don't exist yet)
> 2. Run pytest test_german_workbench.py -k test_core_words_constants_exist -v and verify RED
> 3. Add the two consts to workbench.html
> 4. Run test and verify GREEN
>
> Return: Test output evidence and the exact line numbers where consts were inserted."

---

## Task 1: 词初始化时自动打 core tag + 新词注入

**Files:**
- Modify: `static/german/workbench.html:881-885` (S.words = SEED_WORDS.map(...))
- Test: `test_german_workbench.py`

**Interfaces:**
- Consumes: `CORE_WORD_SEED_IDS`, `CORE_CUSTOM_WORDS`, `SEED_WORDS`
- Produces: `S.words` 中对应种子词的 `tags` 包含 `"core"`；`S.words` 末尾追加 `CORE_CUSTOM_WORDS`
- Side effect: `S.words.length` 从 684 变成 ~706

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** — 断言：`S.words` 中 id 在 CORE_WORD_SEED_IDS 里的词都有 `tags.includes("core")`；CORE_CUSTOM_WORDS 的词都能在 `S.words` 中找到且 `custom === true`；`S.words.length > 684`
- [ ] **Step 2: 跑测试确认失败（RED）**
- [ ] **Step 3: 修改 SEED_WORDS.map 的回调** — 在返回的对象里加 `tags: CORE_WORD_SEED_IDS.has(w.id) ? ["core"] : []`（替换原来的 `tags: []`）
- [ ] **Step 4: 在 map 之后追加新词** — `S.words.push(...CORE_CUSTOM_WORDS.map(w => ({...w, tags: ["core"], custom: true, up: 0})))`
- [ ] **Step 5: 跑测试确认通过（GREEN）**
- [ ] **Step 6: 更新 `test_workbench_data_intact` 测试** — 原来硬编码 684 的断言改为 `>= 684` 或动态值

**Subagent Prompt Scaffold:**
> "Implement Task 1: Tag seed words with 'core' and inject custom core words into S.words.
> Goal: During word initialization (loadAll), words in CORE_WORD_SEED_IDS get 'core' tag, and CORE_CUSTOM_WORDS are appended to S.words.
> Target Files:
> - Modify: `static/german/workbench.html` — the SEED_WORDS.map block at lines 881-885 and the lines immediately after
> - Test: `test_german_workbench.py` — add test `test_core_words_tagged_on_init`
>
> Changes needed:
> 1. In the SEED_WORDS.map callback (line ~881-885), change `tags: []` to `tags: CORE_WORD_SEED_IDS.has(w.id) ? ['core'] : []`
> 2. After the map (after line ~885), add: `S.words.push(...CORE_CUSTOM_WORDS.map(w => ({ ...w, tags: ['core'], custom: true, up: w.up || 0 })));`
> 3. Ensure the letter field is correctly set for custom words (first letter of headword after stripping article)
>
> TDD Steps:
> 1. Write failing test that checks: (a) at least 213 words have 'core' tag, (b) core custom words are in S.words with custom=true, (c) S.words.length > 684
> 2. Run test, verify RED
> 3. Make the code changes
> 4. Run test, verify GREEN
> 5. Update test_workbench_data_intact if it hardcodes 684 (change to >= 684 or similar)
>
> Return: Test output evidence and exact changed line numbers."

---

## Task 2: 词表视图（Words View）的核心模式过滤

**Files:**
- Modify: `static/german/workbench.html:445-464` (toolbar HTML 区域)
- Modify: `static/german/workbench.html:2298` (wordFilters 对象)
- Modify: `static/german/workbench.html:2361-2377` (filter predicate + count)
- Modify: `static/german/workbench.html:2394-2404` (listener bindings)
- Test: `test_german_workbench.py`

**Interfaces:**
- Consumes: `wordFilters` (line 2298)
- Produces: `wordFilters.scope` 字段（`"all"` | `"core"`）
- Produces: HTML 中的 scope toggle（segmented control：全部 / ⭐ 核心）

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** — 断言 HTML 中有 scope toggle 的标记（比如 `id="wScope"` 或 class）；JS 中 `wordFilters` 有 scope 字段；过滤逻辑里有 scope 检查
- [ ] **Step 2: 跑测试确认失败（RED）**
- [ ] **Step 3: 在 toolbar 加 scope 切换控件** — 在 `wTag` select 之前（或旁边）加一个分段控件/select，id 为 `wScope`，选项：`全部` (value="all")、`⭐ 核心词` (value="core")
- [ ] **Step 4: 在 wordFilters 对象加 scope 字段** — 初始值 `"all"`
- [ ] **Step 5: 在 filter predicate 里加 scope 检查** — 跟 tag 检查类似的模式：`if (wordFilters.scope === "core" && !(w.tags || []).includes("core")) return false;`
- [ ] **Step 6: 绑定 listener** — 把 `wScope` 加入事件绑定数组，change 时设置 `wordFilters.scope` 并重新渲染
- [ ] **Step 7: 跑测试确认通过（GREEN）**

**Subagent Prompt Scaffold:**
> "Implement Task 2: Core-mode filter for words view (table/list view).
> Goal: Add a scope toggle (all / core) to the words view toolbar that filters the word list to only show core-tagged words.
> Target Files:
> - Modify: `static/german/workbench.html` — toolbar HTML (~lines 445-464), wordFilters (~line 2298), filter predicate (~lines 2361-2377), listener bindings (~lines 2394-2404)
> - Test: `test_german_workbench.py` — add test `test_core_scope_filter_in_words_view`
>
> Implementation details:
> 1. Add a `<select id="wScope">` in the toolbar (before wTag at line ~448) with two options:
>    <option value="all">全部词</option>
>    <option value="core">⭐ 核心词</option>
> 2. Add `scope: "all"` to the wordFilters object (~line 2298)
> 3. In the filter predicate inside renderWords (~line 2361-2376, after the tag check), add:
>    if (wordFilters.scope === "core" && !(w.tags || []).includes("core")) return false;
> 4. Add "wScope" to the list of elements that get change listeners (~line 2394-2404)
> 5. In the change handler, add: case "wScope": wordFilters.scope = $("wScope").value; break;
>
> TDD Steps:
> 1. Write test that checks: (a) wScope select exists in HTML, (b) wordFilters has scope field, (c) scope check exists in filter code
> 2. Run test, verify RED
> 3. Implement all changes
> 4. Run test, verify GREEN
>
> Return: Test output evidence and changed line numbers."

---

## Task 3: 复习队列（Review Queue）的核心模式过滤

**Files:**
- Modify: `static/german/workbench.html:1547` (buildReviewQueue function)
- Modify: `static/german/workbench.html:1596` (renderReview queueDay check)
- Test: `test_german_workbench.py`

**Interfaces:**
- Consumes: `wordFilters.scope` 或新增 `reviewScope` 状态
- Produces: 复习队列只包含当前 scope 下的词
- Produces: 复习中途切换 scope 时，从 `revIdx+1` 之后静默过滤掉非 scope 词

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** — 断言 buildReviewQueue 中有 scope 过滤逻辑；复习中切换 scope 有过滤处理
- [ ] **Step 2: 跑测试确认失败（RED）**
- [ ] **Step 3: 在 buildReviewQueue 的 due cards 过滤里加 scope 检查** — line ~1550-1552，`wordById(id)` 检查之后加：`&& (!coreOnly || (wordById(id).tags || []).includes("core"))`
- [ ] **Step 4: 在 buildReviewQueue 的 new-word pool 过滤里加 scope 检查** — line ~1558，`S.words.filter(w => !S.cards[w.id] && ...)` 里加 scope 条件
- [ ] **Step 5: 决定 scope 状态存在哪里** — 复用 `wordFilters.scope`（全局同一个 scope 状态，词表和复习共享）还是单独一个 `reviewScope`。**选前者**（全局一个 scope 切换，所有视图一致）
- [ ] **Step 6: 复习中切换的静默过滤** — 在 scope change handler 里，如果当前在 review 视图且 revIdx < revQueue.length - 1，从 revIdx+1 之后剔除非 core 词的 id，保留 revIdx 及之前的历史不变
- [ ] **Step 7: 跑测试确认通过（GREEN）**

**Subagent Prompt Scaffold:**
> "Implement Task 3: Core-mode filtering for review queue and mid-review switching.
> Goal: buildReviewQueue respects the current scope, and switching scope mid-review silently filters upcoming cards without losing history.
> Target Files:
> - Modify: `static/german/workbench.html` — buildReviewQueue (~line 1547), and the scope change handler
> - Test: `test_german_workbench.py` — add test `test_core_scope_in_review_queue`
>
> Implementation details:
> 1. buildReviewQueue uses wordFilters.scope (from Task 2) as the global scope state
> 2. In the due cards filter (~line 1550-1552), add scope check:
>    const isCoreOnly = wordFilters.scope === "core";
>    Object.keys(S.cards).filter(id => {
>      const w = wordById(id);
>      return S.cards[id].reps > 0 && !S.cards[id].manual && S.cards[id].due <= eod && w && (!isCoreOnly || (w.tags || []).includes("core"));
>    })
> 3. In the new-word pool filter (~line 1558), add scope check:
>    let pool = S.words.filter(w => {
>      if (!S.cards[w.id] && !seen.has(w.id)) {
>        return !isCoreOnly || (w.tags || []).includes("core");
>      }
>      return false;
>    }).map(w => w.id);
> 4. In the scope change handler (wScope change), add:
>    - If current view is "review" and revIdx < revQueue.length - 1:
>      - Filter revQueue from revIdx+1 onward to only include words matching the new scope
>      - Do NOT change revIdx or ratedCount or queueDay
>      - Do NOT touch cards before revIdx (history is preserved)
>    - Call renderReview() to refresh
>
> TDD Steps:
> 1. Write test that checks: (a) buildReviewQueue contains scope-related filtering code, (b) mid-review switch has a filter from revIdx onwards
> 2. Run test, verify RED
> 3. Implement changes
> 4. Run test, verify GREEN
>
> Return: Test output evidence and changed line numbers."

---

## Task 4: 统计与徽章的核心模式适配

**Files:**
- Modify: `static/german/workbench.html:3136` (renderHeaderBadge)
- Modify: `static/german/workbench.html:2080` (renderStats + letterHeatmap)
- Test: `test_german_workbench.py`

**Interfaces:**
- Consumes: `wordFilters.scope`
- Produces: `renderHeaderBadge` 的 pending/到期计数按 scope 过滤
- Produces: `renderStats` 的 KPI + 字母热力图按 scope 过滤（stats 视图独立决定自己的 scope）

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** — 断言 renderHeaderBadge 中有 scope 感知的计数逻辑；letterHeatmap 或 renderStats 有 scope 参数/检查
- [ ] **Step 2: 跑测试确认失败（RED）**
- [ ] **Step 3: renderHeaderBadge 按 scope 过滤** — due count 和 new-remaining count 都只算当前 scope 的词
- [ ] **Step 4: stats 视图的 scope 决策** — stats 视图显示全局统计还是当前 scope 统计？**选全局**（stats 是总览，scope 是复习范围，不是统计范围）。但在 stats 页加一行核心词进度（`X/235 已掌握`）。
- [ ] **Step 5: letterHeatmap 不加 scope** — 热力图是全局学习分布概览，保持全局
- [ ] **Step 6: 词表视图的 #wCount 自动正确** — Task 2 已经在 filter 后计数，不需要额外改
- [ ] **Step 7: 跑测试确认通过（GREEN）**

**Subagent Prompt Scaffold:**
> "Implement Task 4: Stats and badge updates for core mode.
> Goal: Header badge shows scope-aware counts; stats page shows core-mode progress summary.
> Target Files:
> - Modify: `static/german/workbench.html` — renderHeaderBadge (~line 3136), renderStats (~line 2080)
> - Test: `test_german_workbench.py` — add test `test_core_scope_stats_and_badge`
>
> Implementation details:
> 1. renderHeaderBadge (~line 3136-3148):
>    - Add scope-aware counting for due cards: only count cards where wordById(id) has core tag (if scope==='core')
>    - Add scope-aware counting for new words remaining: count words in scope without S.cards
>    - The badge text should still show due count + new count
> 2. renderStats (~line 2080-2220):
>    - Stats view shows GLOBAL stats (total words, total learned, etc.) — these stay S.words.length
>    - Add a small "核心词进度" line somewhere in the stats KPI area showing:
>      const coreWords = S.words.filter(w => (w.tags || []).includes("core"));
>      const coreLearned = coreWords.filter(w => S.cards[w.id] && S.cards[w.id].reps > 0).length;
>      `核心词: ${coreLearned} / ${coreWords.length}`
> 3. letterHeatmap stays global (no scope filter) — it's an overview of the whole deck
>
> TDD Steps:
> 1. Write test that checks: (a) renderHeaderBadge has scope-aware counting, (b) stats page has core progress display
> 2. Run test, verify RED
> 3. Implement changes
> 4. Run test, verify GREEN
>
> Return: Test output evidence and changed line numbers."

---

## Task 5: 错题集 + 测试模式的核心模式适配 + 导入导出兼容性

**Files:**
- Modify: `static/german/workbench.html:1569` (injectWrongWords)
- Modify: `static/german/workbench.html:1739` (quizPool)
- Modify: `static/german/workbench.html:3044-3051` (wb-sync export)
- Modify: `static/german/workbench.html:3083-3117` (applyMerge)
- Test: `test_german_workbench.py`

**Interfaces:**
- Consumes: `wordFilters.scope`
- Produces: 错题注入 + 测试题池都按 scope 过滤
- Produces: wb-sync 导出时，核心词身份对种子词不导出（因为种子词不导出），对自定义词通过 tags 字段导出
- Produces: applyMerge 时，已有词的 core tag 不被覆盖（因为种子词不走 merge）

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** — 断言 injectWrongWords 有 scope 检查；quizPool 有 scope 检查
- [ ] **Step 2: 跑测试确认失败（RED）**
- [ ] **Step 3: injectWrongWords 加 scope 过滤** — 从错题库选词时只选当前 scope 内的词
- [ ] **Step 4: quizPool 加 scope 过滤** — 测试题池只从当前 scope 的词里选
- [ ] **Step 5: 确认 wb-sync 导出行为** — 种子词不导出（现有行为），所以种子词的 core tag 不会被导出。自定义词导出时 tags 字段会带上 `"core"`。这是可以接受的（符合 ADR 决策：核心词身份不同步，但内建常量保证所有设备一致）
- [ ] **Step 6: 确认 applyMerge 行为** — 导入的自定义词如果已有，up 大的覆盖；core tag 作为 tags 的一部分会被正常 merge。种子词不走 merge，所以 core tag 不受影响。正确。
- [ ] **Step 7: 跑测试确认通过（GREEN）**

**Subagent Prompt Scaffold:**
> "Implement Task 5: Core mode for wrong words injection, quiz pool, and verify import/export behavior.
> Goal: Wrong-word injection and quiz mode respect the core scope. Verify that wb-sync import/export has correct behavior for core tags.
> Target Files:
> - Modify: `static/german/workbench.html` — injectWrongWords (~line 1569), quizPool (~line 1739)
> - Test: `test_german_workbench.py` — add test `test_core_scope_in_quiz_and_wrong`
>
> Implementation details:
> 1. injectWrongWords function (~line 1569):
>    - When picking wrong answer candidates, only pick from words in current scope
>    - Add scope filter to the word selection logic (similar pattern to buildReviewQueue)
> 2. quizPool (~line 1739 area):
>    - Quiz questions should only draw from words in the current scope
>    - Add scope check to the pool selection
> 3. wb-sync export (line ~3045):
>    - customWords = S.words.filter(w => w.custom) — this already exists
>    - Core tags on custom words are exported as part of the word's tags field — no change needed
>    - Core tags on seed words are NOT exported (seed words aren't in sync export) — this is INTENTIONAL per ADR
> 4. applyMerge (~line 3104-3112):
>    - Merges customWords by ID, using Object.assign when up > cur.up
>    - Core tags on custom words merge normally — no change needed
>    - Seed words are never touched by merge — core tags on seeds are safe
>
> TDD Steps:
> 1. Write test that checks: (a) injectWrongWords has scope filtering, (b) quiz/quizPool has scope filtering
> 2. Run test, verify RED
> 3. Implement changes
> 4. Run test, verify GREEN
>
> Return: Test output evidence and changed line numbers."

---

## Task 6: 完整测试 + 回归验证

**Files:**
- Test: `test_german_workbench.py`
- Run: 完整 fast baseline 套件

**Step Breakdown:**
- [ ] **Step 1: 跑全部 workbench 测试** — `pytest test_german_workbench.py -v`
- [ ] **Step 2: 跑完整 fast baseline** — 确认没有回归
- [ ] **Step 3: 检查所有新增测试的命名和位置** — 确保按模块组织
- [ ] **Step 4: 手动验证（可选）** — 打开 workbench.html 确认：默认全部词；切换到核心词后数量减少；复习队列只有核心词；统计页有核心词进度行

**Subagent Prompt Scaffold:**
> "Task 6: Full regression test suite run.
> Goal: Run the full test suite and confirm all tests pass with zero regressions.
>
> Steps:
> 1. Run: pytest test_german_workbench.py -v — confirm all tests pass including the 5+ new tests
> 2. Run the full fast baseline: pytest test_core_dict_ext.py test_dict_pipeline.py test_edge_tts_mini.py test_essay_diff.py test_frontend_module_graph.py test_frontend_security.py test_german_workbench.py test_goethe_a1.py test_goethe_a1_writing.py test_goethe_a1_hoeren.py test_goethe_a1_lesen.py test_corpus.py test_prep_matrix.py test_source_hygiene.py test_start.py test_syntax_tree.py test_writer_mobile.py test_writing_rules.py -q
> 3. Report total pass count and any failures
>
> Return: Full test output with pass/fail counts."

---

## 依赖关系图

```
Task 0 (常量+新词) ──→ Task 1 (初始化打tag) ──→ Task 2 (词表视图过滤) ──→ Task 3 (复习队列过滤)
                                                          │                      │
                                                          ▼                      ▼
                                                     Task 4 (统计徽章) ←── Task 5 (错题+测试+同步)
                                                          │
                                                          ▼
                                                     Task 6 (全量回归测试)
```

**可并行组**：
- Task 2 和 Task 5 的前半部分（错题/测试池过滤模式确认）可以和 Task 3 部分并行
- 推荐顺序：0 → 1 → 2 → 3 → 4+5（并行）→ 6
