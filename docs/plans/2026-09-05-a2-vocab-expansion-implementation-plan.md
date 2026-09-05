# A2 词汇与全域背词系统扩展实施计划 (A2 Vocab Expansion Implementation Plan)

> **Goal**: 全栈落地 A2 词汇支持（方案 B：全域贯通），在背词工作台实现 4 档范围切换并保护 13 处切片护栏，在服务端提供规范化名词冠词拼装与 A2 端点，在备考域激活 A2 考纲词表模块。
> **Tech Stack**: Python 3.10+ (FastAPI + SQLite), 原生 ES Modules JS (无框架), HTML5/CSS3
> **Spec Reference**: [`docs/specs/2026-09-05-a2-vocab-expansion-design.md`](file:///d:/Code/DeLector/docs/specs/2026-09-05-a2-vocab-expansion-design.md)
> **Global Constraints**:
> 1. Conventional Commits, 严禁 `--no-verify`。
> 2. 基线测试全绿（当前基线 574 项全绿，10/10 Node.js 探针全绿）。
> 3. `tools/wb_queue_probe.mjs` 13/13 处切片护栏 100% 绝对保护（不得改动 `inScopeWord` 的 `wordFilters.scope === "core"` 核心真值源特征）。
> 4. 打包目标闭环（`package_windows.py` 等需同步注册新增后端模块）。

---

## ⚠️ User Review Required

> [!IMPORTANT]
> **零外部 AI 依赖与即开即用**：
> 核心词库 `core_dict.py` / `core_dict_ext.py` 已内置 974 个歌德 A2 词条（497 名词、246 动词、143 形容词、66 副词及介副连词），性数格与释义均已齐备。本计划重点在于**冠词形态学拼装**、**工作台范围选择器安全切入**与**备考域目录联动**。

> [!WARNING]
> **工作台 13 条探针切片防破坏纪律**：
> `static/german/workbench.html` 包含严密的切片探针（`wb_queue_probe.mjs`）与静态契约（`test_german_workbench.py`）。扩展 `inScopeWord` 时必须保证其仍然以 `wordFilters.scope === "core"` 判定 A1 核心词，新增的 A2 逻辑必须为非破坏性分支。

---

## 任务执行序列概览

| 任务 | 目标组件 | 角色 | 关键产出 |
| :--- | :--- | :--- | :--- |
| **Task 1** | `database.py` 词汇格式化与契约 | Backend TDD Builder | `format_vocab_headword`、`get_vocab_by_cefr("A2")` 冠词拼装、`test_a2_vocab_data.py` |
| **Task 2** | `routes_a2.py`、`exam_catalog.py` 服务端路由 | Backend TDD Builder | `GET /api/a2/vocab`、`EXAM_CATALOG["A2"]` 注册、`test_exam_catalog.py` 更新 |
| **Task 3** | `workbench.html` 工作台 4 档选择器扩展 | Frontend TDD Builder | `#scopeSeg` 4 档胶囊、`inScopeWord` A2 分支、`syncA2CardsFromServer`、探针 13/13 全绿 |
| **Task 4** | `main.js` & `a1_cards.js` 备考域 A2 激活 | Frontend TDD Builder | A2 考纲词表在备考域展示、卡盒浏览与抽认卡模式对接 |
| **Task 5** | 打包同步、回归闭环与台账归档 | Guard Subagent | 模块注册守卫、全量 574+ pytest 全绿、10/10 探针全绿、WORKMEMORY 归档 |

---

## 详细实施任务规范

### Task 1: A2 词汇格式化函数与数据契约扩展 [Role: Backend TDD Builder]

**Files:**
- Create: `test_a2_vocab_data.py`
- Modify: `database.py:1153-1240`

**Interfaces:**
- Consumes: `core_dict.CORE_VOCAB_DB` (974 A2 entries)
- Produces: `format_vocab_headword(lemma: str, pos: str, gender: Optional[str]) -> str`
- Produces: `get_vocab_by_cefr(cefr="A2", scope="all|core") -> Dict[str, Any]` with normalized nouns (`der/die/das`), capitalized lemmas, POS, gender, plural, and Chinese gloss.

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: A2 词汇格式化函数与数据契约扩展.
> Goal: In database.py, implement `format_vocab_headword` to correctly format nouns with definite articles ('der'/'die'/'das') and capitalized lemmas, and update `get_vocab_by_cefr(cefr='A2')` to return high-quality normalized word dictionaries.
> Target Files: Create `test_a2_vocab_data.py`, Modify `database.py`.
> TDD Steps:
> 1. Write failing test in `test_a2_vocab_data.py` (RED):
>    - `test_get_vocab_by_cefr_a2_returns_974_words()`: Assert `get_vocab_by_cefr(cefr='A2')` total == 974.
>    - `test_a2_noun_articles_and_capitalization()`: Sample nouns (e.g. 'abenteuer' -> 'das Abenteuer', 'abfahrt' -> 'die Abfahrt', 'abfall' -> 'der Abfall'), assert article and uppercase.
>    - `test_a2_verbs_and_adjectives_stay_lowercase()`: Sample verbs/adjectives ('abbiegen', 'aktuell'), assert lowercase.
> 2. Run `pytest test_a2_vocab_data.py -q` and verify failure.
> 3. In `database.py`:
>    - Add `format_vocab_headword(lemma: str, pos: str, gender: Optional[str]) -> str`.
>    - Update `get_vocab_by_cefr(cefr="A2", ...)` to use `format_vocab_headword` for `hw` and populate `gender`, `plural`, `pos`, `zh`, `cefr='A2'`.
>    - Cache the result in `_A2_WORKBENCH_WORDS_CACHE`.
> 4. Run `pytest test_a2_vocab_data.py -q` and verify all green.
> 5. Run `python -m pytest test_server.py -k test_get_vocab_by_cefr -q` to ensure no regression.
> Return: Test evidence and diff summary."

**Step Breakdown:**
- [ ] **Step 1: Write failing tests in `test_a2_vocab_data.py` (RED)**
- [ ] **Step 2: Run pytest to verify RED state**
- [ ] **Step 3: Implement `format_vocab_headword` and update `get_vocab_by_cefr` in `database.py` (GREEN)**
- [ ] **Step 4: Run pytest and verify GREEN state**
- [ ] **Step 5: Guard clause refactoring & verify regression safety**
- [ ] **Step 6: Git atomic commit**

---

### Task 2: 服务端 A2 考纲端点与 Catalog 注册 [Role: Backend TDD Builder]

**Files:**
- Create: `routes_a2.py`
- Modify: `exam_catalog.py:25-70`
- Modify: `server.py`
- Modify: `test_exam_catalog.py`
- Modify: `package_windows.py:55-80`

**Interfaces:**
- Consumes: `database.get_vocab_by_cefr("A2")`
- Produces: `GET /api/a2/vocab` -> `List[Dict[str, Any]]`
- Produces: `EXAM_CATALOG["A2"]` registration in `exam_catalog.py`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 服务端 A2 考纲端点与 Catalog 注册.
> Goal: Register A2 under EXAM_CATALOG in exam_catalog.py with 974 vocab count, implement `routes_a2.py` with `GET /api/a2/vocab`, mount in `server.py`, and register in `package_windows.py`.
> Target Files: Create `routes_a2.py`, Modify `exam_catalog.py`, `server.py`, `test_exam_catalog.py`, `package_windows.py`.
> TDD Steps:
> 1. In `test_exam_catalog.py`, update contract assertion:
>    - Assert `[lv['id'] for lv in levels] == ['A1', 'A2']` (or `set(lv['id'] for lv in levels) == {'A1', 'A2'}`).
>    - Assert A2 has `vocab` module with count == 974 and `api_prefix == '/api/a2'`.
>    - Add test for `GET /api/a2/vocab` in `test_server.py`.
> 2. Run pytest to verify failure (RED).
> 3. In `exam_catalog.py`:
>    - Add `"A2"` to `EXAM_CATALOG` with `vocab` module:
>      `title: "📖 官方考纲词表 (Wortliste)"`, `panel: "exam-cards-family"`, `api_prefix: "/api/a2"`, `count_fn: lambda: len(get_vocab_by_cefr('A2')['words'])`.
> 4. In `routes_a2.py`:
>    - Create `APIRouter(prefix="/api/a2", tags=["Goethe A2"])`.
>    - Implement `GET /api/a2/vocab` returning words list from `get_vocab_by_cefr("A2")["words"]`.
> 5. In `server.py`:
>    - Include router: `app.include_router(routes_a2.router)`.
> 6. In `package_windows.py`:
>    - Add `routes_a2` to `--hidden-import`.
> 7. Run `pytest test_exam_catalog.py test_server.py -k "catalog or a2_vocab" -q` and verify GREEN.
> Return: Test evidence and changes made."

**Step Breakdown:**
- [ ] **Step 1: Write/update failing tests in `test_exam_catalog.py` & `test_server.py` (RED)**
- [ ] **Step 2: Run pytest to verify RED state**
- [ ] **Step 3: Implement `routes_a2.py`, register in `exam_catalog.py`, mount in `server.py` and `package_windows.py` (GREEN)**
- [ ] **Step 4: Run pytest and verify GREEN state**
- [ ] **Step 5: Code review & verify packaging registration**
- [ ] **Step 6: Git atomic commit**

---

### Task 3: 背词工作台 4 档范围扩展与 13 处切片护栏保护 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:335-345` (scopeSeg markup)
- Modify: `static/german/workbench.html:1612-1616` (inScopeWord definition)
- Modify: `static/german/workbench.html:3045-3110` (syncScopeControls, syncA2CardsFromServer)
- Modify: `test_workbench_tokens.py`

**Interfaces:**
- Consumes: `GET /api/cards/vocab?cefr=A2&scope=all`
- Produces: `scopeSeg` with `data-scope="a2"` button: `📘 A2 词库`
- Produces: `inScopeWord(w)` with non-breaking `wordFilters.scope === "a2"` support

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 背词工作台 4 档范围扩展与 13 处切片护栏保护.
> Goal: In `static/german/workbench.html`, add `📘 A2 词库` to `#scopeSeg`, extend `inScopeWord` to support A2, add `syncA2CardsFromServer()`, and maintain 100% compliance with `tools/wb_queue_probe.mjs` and `test_german_workbench.py`.
> CRITICAL INVARIANTS:
> 1. NEVER alter the signature or location of functions extracted by `wb_queue_probe.mjs` (pad2, todayStr, buildReviewQueue, refilterReviewQueueForScope, etc.).
> 2. `inScopeWord` MUST retain `wordFilters.scope === 'core'` as the primary truth source check for core words.
> TDD Steps:
> 1. In `test_workbench_tokens.py`, add `test_workbench_scope_selector_has_a2_option()`:
>    - Assert `#scopeSeg button[data-scope="a2"]` exists in `workbench.html`.
>    - Assert `inScopeWord` handles `wordFilters.scope === 'a2'` matching `w.cefr === 'A2'` or `w.tags.includes('a2')`.
> 2. Run pytest to verify RED.
> 3. In `static/german/workbench.html`:
>    - In `#scopeSeg`: add `<button type="button" data-scope="a2">📘 A2 词库</button>`.
>    - In `inScopeWord(w)`:
>      ```javascript
>      function inScopeWord(w) {
>        return !w || (wordFilters.scope === "core" ? (w.tags || []).includes("core") : (wordFilters.scope === "reader" ? !!(w.custom || (w.tags || []).includes("reader") || String(w.id || "").startsWith("card-")) : (wordFilters.scope === "a2" ? (w.cefr === "A2" || (w.tags || []).includes("a2") || String(w.id || "").startsWith("a2-")) : (wordFilters.scope === "all" ? !(w.cefr === "A2" || (w.tags || []).includes("a2") || String(w.id || "").startsWith("a2-") || (w.custom && (w.tags || []).includes("reader"))) : wordFilters.scope !== "core"))));
>      }
>      ```
>    - Add `syncA2CardsFromServer()`: fetches `/api/cards/vocab?cefr=A2&scope=all`, normalizes into `S.words` with `cefr: "A2"`, `tags: ["a2"]`, saves to `localStorage`, refilters queue, and calls `renderWords()`.
>    - In `#scopeSeg` click listener: call `if (next === "a2") syncA2CardsFromServer();`.
> 4. Run `pytest test_workbench_tokens.py test_german_workbench.py -q`.
> 5. Run `node tools/wb_queue_probe.mjs` (MUST pass 13/13).
> 6. Commit atomic changes."

**Step Breakdown:**
- [ ] **Step 1: Add failing test in `test_workbench_tokens.py` (RED)**
- [ ] **Step 2: Run pytest to verify RED state**
- [ ] **Step 3: Update `workbench.html` markup, `inScopeWord`, and `syncA2CardsFromServer` (GREEN)**
- [ ] **Step 4: Run `node tools/wb_queue_probe.mjs` (must pass 13/13)**
- [ ] **Step 5: Run `pytest test_german_workbench.py test_workbench_tokens.py -q` (all green)**
- [ ] **Step 6: Git atomic commit**

---

### Task 4: 备考域前端 A2 考纲词表与卡盒激活 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/js/main.js:290-330`
- Modify: `static/js/a1_cards.js` (or general exam cards logic)
- Modify: `test_exam_domain.py`

**Interfaces:**
- Consumes: `/api/exams/catalog` (with A1 and A2)
- Consumes: `/api/a2/vocab`
- Produces: Active A2 level navigation in `view-exam` capable of rendering the 974-word Wortliste card deck.

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 备考域前端 A2 考纲词表与卡盒激活.
> Goal: Update `static/js/main.js` and `static/js/a1_cards.js` so that when A2 is selected in `#exam-level-tabs`, the A2 Wortliste module is fully interactive instead of disabled, loading 974 A2 cards from `/api/a2/vocab`.
> Target Files: Modify `static/js/main.js`, `static/js/a1_cards.js`, `test_exam_domain.py`.
> TDD Steps:
> 1. In `test_exam_domain.py`, add `test_exam_a2_vocab_integration()`:
>    - Assert `initExamCatalog` hooks up active click handling when level is A2.
>    - Assert `loadA2VocabData` or level parameter in `loadA1Data` correctly routes to `/api/a2/vocab`.
> 2. Run pytest to verify RED.
> 3. In `static/js/main.js` & `static/js/a1_cards.js`:
>    - Wire up `#exam-level-a2` to switch active exam level to A2.
>    - Allow `a1_cards.js` to accept level ('A1' or 'A2') to fetch from `/api/a1/vocab` or `/api/a2/vocab`.
> 4. Run `pytest test_exam_domain.py -q` and verify GREEN.
> 5. Run `python -m pytest test_frontend_security.py -q` to verify zero XSS sinks.
> Return: Test evidence and diff summary."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `test_exam_domain.py` (RED)**
- [ ] **Step 2: Run pytest to verify RED state**
- [ ] **Step 3: Update `main.js` and `a1_cards.js` to support A2 vocab loading (GREEN)**
- [ ] **Step 4: Run `pytest test_exam_domain.py test_frontend_security.py -q`**
- [ ] **Step 5: Verify clean frontend code**
- [ ] **Step 6: Git atomic commit**

---

### Task 5: 打包同步、回归闭环与台账归档 [Role: Guard Subagent]

**Files:**
- Modify: `.github/workflows/build-release.yml` (if needed for cp to Chaquopy)
- Modify: `test_server.py` (module registration test)
- Create: `docs/plans/2026-09-05-a2-vocab-expansion-ledger.md`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`
- Modify: `WORKMEMORY/work.log`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: 打包同步、回归闭环与台账归档.
> Goal: Ensure `routes_a2.py` is safely registered across all packaging configurations (test_server packaging needle test, PyInstaller, and GitHub Actions workflow), run full regression suites (all 574+ pytest tests and 10/10 Node.js probes), update ledger and WORKMEMORY.
> TDD Steps:
> 1. Run `python -m pytest test_server.py -k test_all_backend_modules_registered_in_all_packaging_targets -q`.
> 2. If red, add `routes_a2` to the modules list and packaging targets.
> 3. Run full regression:
>    - `pytest -q`
>    - `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
> 4. Create `docs/plans/2026-09-05-a2-vocab-expansion-ledger.md` recording all task statuses, commits, and verification evidence.
> 5. Update `WORKMEMORY/PROJECT_OVERVIEW.md` and append WORK_START/WORK_END in `WORKMEMORY/work.log`.
> Return: Full regression results and ledger path."

**Step Breakdown:**
- [ ] **Step 1: Check backend module packaging test and update registration**
- [ ] **Step 2: Run full regression pytest suite (record passed count and time)**
- [ ] **Step 3: Run all 10 `tools/*.mjs` probes**
- [ ] **Step 4: Create and update execution ledger**
- [ ] **Step 5: Update `WORKMEMORY/PROJECT_OVERVIEW.md` and `work.log`**
- [ ] **Step 6: Git atomic commit**

---

## 验证与验收标准 (Verification & Acceptance Criteria)

1. **数据与契约**：
   - `GET /api/cards/vocab?cefr=A2&scope=all` 返回 200，含 974 个 A2 词条。
   - 所有名词以 `der`/`die`/`das` 前缀且首字母大写。
   - `GET /api/exams/catalog` 返回 `A1` 与 `A2`，A2 题量显示 `974`。
2. **工作台切片护栏**：
   - `node tools/wb_queue_probe.mjs` 13/13 处切片护栏 100% 保持通过。
   - `pytest test_german_workbench.py` 79 项静态契约全部通过。
3. **回归基线**：
   - 全量 pytest 测试数由 574 增加至 580+，0 失败、0 告警、0 回归。
   - 10/10 外部探针通过。
