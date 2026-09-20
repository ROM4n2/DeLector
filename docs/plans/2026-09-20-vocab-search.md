# 例句 / 搭配 / 语料 全文检索 实施计划

> **Goal**: 新增「🔍 检索」子系统——对词条 + 例句 + 介词搭配 + 语料全文做内存扫描检索（含德语变音折叠与中文两字词子串命中），服务端 `GET /api/search` + 前端检索视图。
> **Tech Stack**: Python 3.10+（FastAPI + stdlib sqlite3，**零新依赖**）/ 原生 ES Modules 前端 / Node `node:vm` 行为探针
> **Spec Reference**: `docs/specs/2026-09-20-vocab-search-design.md`（含 FTS5 可行性 Spike）
> **Global Constraints**:
> - **mypy `--strict` 零 error**（全函数/字段类型注解；与文件既有风格协调，允许 `typing.Dict/List/Optional`）
> - **只读、无副作用**：不落库、不做 DB 迁移、不进备份（派生索引无状态）
> - **零新依赖**：仅 stdlib + 既有 `lexicon` / `prep_dict`
> - **路由注册**：新 router 在 `delector/routes/__init__.py::register_routes` 中于 **`main` 之前** include
> - **前端安全**：所有展示字段一律 `esc()`；后端 SQLite 参数化
> - **不碰既有热区**：不改工作台 `workbench.html` sync 函数、不改词库 12 字段契约、不动仓库根 `delector.db`
> - 每 Task 收尾必跑：目标测试 → `for f in tools/*.mjs; do node "$f" >/dev/null 2>&1 || echo FAIL $f; done`（零漂移）→ `python -m ruff check` → `python -m mypy --strict delector tools`
> - 纪律：**不 git add / commit / push / 切分支**（Task 6 的"atomic commit"由主线程统一执行）

---

### Task 1: 词库侧检索纯函数 [Role: TDD Builder]

**Files:**
- Create: `delector/services/search.py`
- Test: `tests/test_search_service.py`

**Interfaces:**
- Consumes: `delector.core.lexicon.LEXICON: dict[str, tuple]`（`cefr,pos,gender,plural,def_zh`）、`lexicon.RICH: dict[str, dict]`（`ipa,example_de,example_zh,topic`）、`delector.data.prep_dict.PREP_COLLOCATIONS: dict[str, tuple[tuple, ...]]`
- Produces:
  - `fold(s: str) -> str`（小写 + `ä→a ö→o ü→u ß→ss` + 压缩空白）
  - `SearchDoc`（`TypedDict`：`kind/id/lemma/hw/pos/cefr/fields/payload`）
  - `iter_vocab_docs() -> Iterator[SearchDoc]`（lexicon→vocab、RICH→example、PREP→colloc）
  - `match_score(q_folded: str, doc: SearchDoc) -> int`
  - `search(q: str, *, scope: str = "all", limit: int = 20, corpus_docs: Iterable[SearchDoc] = ()) -> dict`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 词库侧检索纯函数。
> Goal: 实现 `fold` / `iter_vocab_docs` / `match_score` / `search`，对 lexicon+RICH+PREP 做子串匹配与加权排序。
> Target Files: Create `delector/services/search.py`, Test `tests/test_search_service.py`.
> TDD Steps:
> 1. Write failing test `tests/test_search_service.py`（RED）——覆盖：`fold('Schön')=='schon'`、`fold('STRASSE')=='strasse'` 且 `fold('Straße')=='strasse'`；中文两字词 `search('公寓')` 命中 `wohnung`；变音 `search('schon')` 命中含 `schön` 的例句；`hw` 精确排在子串前；`scope='example'` 只回 example 组；`limit` 钳制；空/单字符 q 返回空 groups。
> 2. Run `python -m pytest tests/test_search_service.py -q` 验证失败（RED）。
> 3. Implement minimal code in `delector/services/search.py`（GREEN）：权重表见 spec §3.2；同分按 `kind` 固定序 + `id` 升序（稳定）。
> 4. Run tests，全绿。
> 5. Flatten with Guard Clauses（≤2 层），全量类型注解（mypy --strict）。
> **变异验证**：删 `fold` 的变音折叠 / 把 `hw` 精确权重降到子串之下 → 对应断言必红。
> Return: Summary with test execution evidence."

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 覆盖 fold / 中文两字词 / 变音 / 排序 / scope / limit / 空 q
- [ ] **Step 2: 跑测试确认按预期失败**
- [ ] **Step 3: 实现 `fold` + `iter_vocab_docs` + `match_score` + `search`（GREEN）**
- [ ] **Step 4: 跑测试全绿；执行变异验证（改权重 / 删 fold → 必红）**
- [ ] **Step 5: Guard Clause 扁平化 + 全量类型注解（REFACTOR）**
- [ ] **Step 6: 收尾门禁（ruff / mypy --strict / 全探针零漂移）**

---

### Task 2: 语料全文接入 + 单请求上限 [Role: TDD Builder]

**Files:**
- Modify: `delector/services/search.py`（新增 `iter_corpus_docs(conn)`）
- Test: `tests/test_search_service.py`（追加语料场景）

**Interfaces:**
- Consumes: `delector.core.database.db_conn`、表 `articles(id,title,raw_text)` / `encounter_texts(id,pack_id,title,level,content)`
- Produces: `iter_corpus_docs(conn, *, max_docs: int, max_chars: int) -> tuple[list[SearchDoc], bool]`（返回 docs 与 `truncated`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 语料全文接入 + 单请求上限。
> Goal: 把 `articles.raw_text` 与 `encounter_texts.content` 规范成 `kind='corpus'` 的 SearchDoc，并实现 hard cap（超限置 truncated）。
> Target Files: Modify `delector/services/search.py`, Test `tests/test_search_service.py`.
> TDD Steps:
> 1. Write failing test（RED）：临时 sqlite 库塞 2 篇 article + 1 篇 encounter → `search('某片段')` 命中 corpus 组、`payload.title` 正确、正文命中分低于标题命中；注入超 `max_docs` 的语料 → `truncated=True`。
> 2. Run 验证失败（RED）。
> 3. Implement `iter_corpus_docs` + 接入 `search(corpus_docs=...)`（GREEN）。
> 4. Run 全绿。
> 5. 语料读取用只读短连接 + 参数化查询；Guard Clause 扁平化。
> Return: Summary with test execution evidence."

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 临时库语料命中 + title/text 权重 + truncated
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `iter_corpus_docs` + `search` 接线（GREEN）**
- [ ] **Step 4: 跑测试全绿**
- [ ] **Step 5: 只读连接 + 参数化 + 扁平化（REFACTOR）**
- [ ] **Step 6: 收尾门禁**

---

### Task 3: `GET /api/search` 路由 + 注册 + API 测试 [Role: TDD Builder]

**Files:**
- Create: `delector/routes/search.py`
- Modify: `delector/routes/__init__.py`（import + `register_routes` 中于 `main` 之前 include）
- Test: `tests/test_search_api.py`

**Interfaces:**
- Consumes: `delector.services.search.search` / `iter_corpus_docs`、`delector.core.database.db_conn`
- Produces: `router: APIRouter`；`GET /api/search?q=&scope=&limit=` → `{"q","scope","total","groups":{"vocab","example","colloc","corpus"},"truncated"}`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: `GET /api/search` 路由 + 注册 + API 测试。
> Goal: 薄路由调用 service 纯函数；`scope` 非法 → 400；`limit` 钳制 1..100；`fold(q)` 后 len<2 → 空 groups（不 500）。
> Target Files: Create `delector/routes/search.py`, Modify `delector/routes/__init__.py`, Test `tests/test_search_api.py`.
> TDD Steps:
> 1. Write failing test（RED）：TestClient 打 `/api/search`（env 钉 tmp_path 的临时库，**不碰仓库根 delector.db**）——断言四组键集、`q='公寓'` 命中 vocab、`q='x'` 空结果、`scope='bad'` → 400、`limit=999` 被钳到 100。
> 2. Run 验证失败（RED）。
> 3. Implement `delector/routes/search.py` + 在 `register_routes` 的 `main` 之前 include（GREEN）。
> 4. Run 全绿（含既有路由守卫测试不回归）。
> 5. 注册顺序注释写清"分域路由在前、通用垫底"；Guard Clause 扁平化。
> **注意**：项目有 fastapi 依赖漂移 post-mortem（`include_router` 后 endpoint 身份漂移致路由守卫误判）——新增 router 后必须跑**全量**路由相关测试。
> Return: Summary with test execution evidence."

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 router + 在 `routes/__init__.py` 注册（GREEN）**
- [ ] **Step 4: 跑 API 测试 + 全量路由守卫测试全绿**
- [ ] **Step 5: 参数校验/钳制 + 注释（REFACTOR）**
- [ ] **Step 6: 收尾门禁**

---

### Task 4: 前端检索视图 + 渲染 + 注册 [Role: TDD Builder]

**Files:**
- Modify: `static/index.html`（新增 `<main id="view-search" class="view">` + 顶栏导航项）
- Create: `static/js/search.js`
- Modify: `static/js/main.js`（import + 视图路由注册）
- Test: `tests/test_search_ui.py`（静态切片/结构断言）

**Interfaces:**
- Consumes: `./core.js` 的 `api/esc/jsAttr`（或既有请求封装）、`./player.js` 的 `playGermanAudio`
- Produces: `export function initSearch(): void`；`export function renderSearchGroups(resp): void`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 前端检索视图 + 渲染 + 注册。
> Goal: 顶栏进入 `view-search`；输入 ≥2 字符（300ms 防抖）调 `/api/search`；四组结果渲染（词条/例句/搭配/语料）+ 命中高亮 + 🔊 发音 + 词条「+ 加入 FSRS 盒」+ 语料点击跳阅读；**全部展示字段经 `esc()`**。
> Target Files: Modify `static/index.html`, `static/js/main.js`; Create `static/js/search.js`; Test `tests/test_search_ui.py`.
> TDD Steps:
> 1. Write failing test（RED）：断言 `static/index.html` 含 `id=\"view-search\"`、`static/js/search.js` 存在且四组渲染/防抖/`esc(` 出现在渲染路径、`main.js` 注册了 search 视图。
> 2. Run 验证失败（RED）。
> 3. Implement markup + `search.js` + `main.js` 注册（GREEN）。
> 4. Run 全绿（含既有 `test_writer_mobile.py` 视图守卫不回归）。
> 5. 空态 + `file://`/端点缺失降级（try/catch）→ REFACTOR。
> Return: Summary with test execution evidence."

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 markup + `search.js` + `main.js` 注册（GREEN）**
- [ ] **Step 4: 跑测试全绿**
- [ ] **Step 5: 空态 / 降级 / 防抖（REFACTOR）**
- [ ] **Step 6: 收尾门禁（含 `static/` 改动 → 记录"Android 需覆盖安装"）**

---

### Task 5: 行为探针 + 性能守卫 + 注册守卫（接入 CI） [Role: TDD Builder]

**Files:**
- Create: `tools/wb_search_probe.mjs`
- Modify: `tests/test_search_ui.py` 或 `tests/test_search_api.py`（追加探针驱动用例）；`tests/test_german_workbench.py` 不变
- Test: 上述

**Interfaces:**
- Consumes: `static/js/search.js` 真实函数体切片（`node:vm`）
- Produces: `tools/wb_search_probe.mjs`（人类可读 + `--json`：`{fail,total,cases}`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: 行为探针 + 性能守卫 + 注册守卫（接入 CI）。
> Goal: ① `tools/wb_search_probe.mjs` 从 `static/js/search.js` 抽真实切片 + `node:vm` 真跑（禁重抄），覆盖：高亮**转义安全**（`<script>` 不注出）、四组渲染、空态；② 性能守卫：断言全量（8175 词库 + 注入 ~200KB 语料）单次 `search()` **< 50ms**；③ 注册守卫：断言 `routes/__init__.py` 中 `search` 在 `main` 之前。
> Target Files: Create `tools/wb_search_probe.mjs`; Modify `tests/test_search_api.py`（性能 + 注册）、`tests/test_search_ui.py`（探针驱动）。
> TDD Steps:
> 1. Write failing test（RED）：探针驱动用例（node 缺失 skip，`--json` 断言 `fail==0 && total>=3` 且关键场景名存在）；性能断言（先跑一次失败基线）；注册顺序断言。
> 2. Run 验证失败（RED）。
> 3. Implement 探针 + 接线（GREEN）。
> 4. Run 全绿；`for f in tools/*.mjs; do node \"$f\" ...` 零漂移。
> 5. 探针加**防死测守卫**（切片缺关键实现 → throw）。
> Return: Summary with test execution evidence."

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 探针驱动 + 性能 + 注册
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `tools/wb_search_probe.mjs` + 接线（GREEN）**
- [ ] **Step 4: 跑全绿 + 全探针零漂移**
- [ ] **Step 5: 加防死测守卫（REFACTOR）**
- [ ] **Step 6: 收尾门禁（全量分半回归 + ruff + mypy strict）**

---

## 收尾（主线程执行，非子代理）
- 分半全量回归：`pytest -q --ignore=tests/test_server.py` + `pytest tests/test_server.py -q`（2 条既有 `exam_trials` 环境失败不算回归）
- 更新 `FEATURES.md`（新功能条目）+ `CHANGELOG.md`（待发版时）+ `WORKMEMORY/PROJECT_OVERVIEW.md`
- 主线程统一 commit；如需发布 → 五件套 bump + tag
