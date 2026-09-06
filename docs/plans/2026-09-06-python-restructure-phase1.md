# DeLector Python 重构 + Go Agent Runtime 实施计划

> **Goal**: 将扁平 `delector/` 包重组为分层 sub-package 结构，为 Go Agent 层提供干净的 Python NLP 接口
> **Tech Stack**: Python 3.10/3.11 (Phase 1) → Go 1.24+ (Phase 2)
> **Spec Reference**: [ADR-0008](../specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md)
> **Global Constraints**: 582 测试基线零改动必须全绿；import 路径变更必须 atomic（一步到位）；data 层纯搬迁不改逻辑

---

## 依赖层级图（重构的安全网）

```
Layer 0 (零依赖):  a1_dict, a1_hoeren_dict, a1_lesen_dict, a1_writing_dict,
                   core_dict_ext, corpus_dict, edge_tts_mini, prep_dict

Layer 1:           core_dict → core_dict_ext
                   syntax_tree (零 delector 依赖)

Layer 2:           linguistics → core_dict, prep_dict
                   essay_diff → syntax_tree

Layer 3:           nlp → core_dict, syntax_tree, start.py ⚠️跨边界
                   writing_rules → core_dict, linguistics
                   security (零 delector 依赖)

Layer 4:           database → nlp, a1_dict, core_dict

Layer 5:           exam_catalog → a1_*, database
                   routes_* → database + 各自数据字典

Layer 6:           server → 全部（上帝文件，2418 行）
```

**已知 Hazard:**
1. `routes_a1.py:70` 反向依赖 `server._attachment_headers` ← 必须先修
2. `nlp.py` 跨包边界 import `start.is_android` ← 必须消除
3. 测试从 `delector.server` import 60+ 符号（含私有）← 搬迁时保持 re-export

---

## Phase 1: Python 重构（7 个 Task）

### Task 1: 消除 Hazard — 修 back-edge 和跨边界 import

**Files:**
- Create: `delector/utils.py`
- Modify: `delector/nlp.py:1-10` (删除 `from start import is_android`)
- Modify: `delector/routes_a1.py:70` (改 import 路径)
- Modify: `delector/server.py` (改 `_attachment_headers` 位置)

**Interfaces:**
- Produces: `delector.utils.is_android()`, `delector.utils.attachment_headers()`

**Subagent Prompt Scaffold:**
> "Implement Task 1: Eliminate refactoring hazards before structural moves.
> Goal: Remove the back-edge `routes_a1.py → server._attachment_headers` and the cross-boundary `nlp.py → start.is_android`.
> Target Files: Create `delector/utils.py`, Modify `delector/nlp.py`, `delector/routes_a1.py`, `delector/server.py`.
> Steps:
> 1. Create `delector/utils.py` with `is_android()` function (extract from `start.py`) and `_attachment_headers()` (extract from `server.py`).
> 2. In `nlp.py`: replace `from start import is_android` with `from delector.utils import is_android`.
> 3. In `routes_a1.py`: replace `from delector.server import _attachment_headers` with `from delector.utils import _attachment_headers`.
> 4. In `server.py`: add `from delector.utils import _attachment_headers` and keep re-exporting for backward compat.
> 5. Run `pytest -x` — all 582 must pass.
> 6. Git commit: `refactor: extract utils.py to break back-edge and cross-boundary imports`"

**Step Breakdown:**
- [ ] Step 1: Create `delector/utils.py` with extracted functions
- [ ] Step 2: Update `nlp.py` import
- [ ] Step 3: Update `routes_a1.py` import
- [ ] Step 4: Update `server.py` to re-export from utils
- [ ] Step 5: Run full test suite — 582 全绿
- [ ] Step 6: Git atomic commit

---

### Task 2: 搬迁数据层 — `delector/data/` sub-package

**Files:**
- Create: `delector/data/__init__.py`
- Move: 8 个 `*_dict.py` → `delector/data/`
  - `a1_dict.py` → `data/a1.py`
  - `a1_hoeren_dict.py` → `data/a1_hoeren.py`
  - `a1_lesen_dict.py` → `data/a1_lesen.py`
  - `a1_writing_dict.py` → `data/a1_writing.py`
  - `core_dict.py` → `data/core.py`
  - `core_dict_ext.py` → `data/core_ext.py`
  - `corpus_dict.py` → `data/corpus.py`
  - `prep_dict.py` → `data/prep.py`
- Modify: 所有 import 这些模块的文件（约 12 个）

**Interfaces:**
- `data/__init__.py` re-exports all public symbols for backward compat

**Subagent Prompt Scaffold:**
> "Implement Task 2: Move data layer into `delector/data/` sub-package.
> Goal: Group all 8 pure-data dictionary modules into a dedicated sub-package.
> Target Files: Create `delector/data/__init__.py`, Move 8 files, Update ~12 consumer files.
> Steps:
> 1. Create `delector/data/__init__.py` with re-exports.
> 2. Move each `*_dict.py` to `delector/data/` with rename (drop `_dict` suffix).
> 3. Update all imports across the codebase:
>    - `from delector.a1_dict` → `from delector.data.a1`
>    - `from delector.core_dict` → `from delector.data.core`
>    - etc. (full list in import map below)
> 4. Keep old modules as re-export shims for 1 release (optional, for Android compat).
> 5. Run `pytest -x` — 582 must pass.
> 6. Git commit: `refactor: move data layer into delector/data/ sub-package`"

**Import 搬迁清单:**
| 旧路径 | 新路径 | 消费方 |
|---|---|---|
| `delector.a1_dict` | `delector.data.a1` | database.py, exam_catalog.py, routes_a1.py, tests |
| `delector.a1_hoeren_dict` | `delector.data.a1_hoeren` | exam_catalog.py, routes_a1_hoeren.py, tests |
| `delector.a1_lesen_dict` | `delector.data.a1_lesen` | exam_catalog.py, routes_a1_lesen.py, tests |
| `delector.a1_writing_dict` | `delector.data.a1_writing` | exam_catalog.py, routes_a1.py, tests |
| `delector.core_dict` | `delector.data.core` | nlp.py, linguistics.py, writing_rules.py, server.py, tests |
| `delector.core_dict_ext` | `delector.data.core_ext` | data/core.py (内部) |
| `delector.corpus_dict` | `delector.data.corpus` | routes_corpus.py, tests |
| `delector.prep_dict` | `delector.data.prep` | linguistics.py (lazy) |

**Step Breakdown:**
- [ ] Step 1: Create `delector/data/__init__.py` with backward-compat re-exports
- [ ] Step 2: Move 8 data files with git mv
- [ ] Step 3: Update all consumer imports (12+ files)
- [ ] Step 4: Run full test suite — 582 全绿
- [ ] Step 5: Git atomic commit

---

### Task 3: 搬迁 NLP 层 — `delector/nlp/` sub-package

**Files:**
- Create: `delector/nlp_engine/__init__.py` (避免与 stdlib `nlp` 混淆)
- Move: `nlp.py` → `nlp_engine/processor.py`
- Move: `syntax_tree.py` → `nlp_engine/syntax_tree.py`
- Move: `linguistics.py` → `nlp_engine/linguistics.py`
- Modify: ~10 个消费方文件

**Interfaces:**
- `nlp_engine/__init__.py` re-exports: `process_german_text`, `analyze_syntax_tree`, `lookup_irregular_verb`, `split_komposita`, etc.

**Subagent Prompt Scaffold:**
> "Implement Task 3: Move NLP layer into `delector/nlp_engine/` sub-package.
> Goal: Group spaCy processing, syntax tree, and linguistics into a dedicated sub-package.
> Target Files: Create `delector/nlp_engine/__init__.py`, Move 3 files, Update ~10 consumers.
> Steps:
> 1. Create `delector/nlp_engine/__init__.py` with re-exports.
> 2. Move `nlp.py` → `nlp_engine/processor.py`, `syntax_tree.py` → `nlp_engine/syntax_tree.py`, `linguistics.py` → `nlp_engine/linguistics.py`.
> 3. Update all imports.
> 4. Run `pytest -x` — 582 must pass.
> 5. Git commit: `refactor: move NLP layer into delector/nlp_engine/ sub-package`"

**Step Breakdown:**
- [ ] Step 1: Create `delector/nlp_engine/__init__.py`
- [ ] Step 2: Move 3 NLP files
- [ ] Step 3: Update all consumer imports
- [ ] Step 4: Run full test suite — 582 全绿
- [ ] Step 5: Git atomic commit

---

### Task 4: 拆分 server.py — 路由层独立

**Files:**
- Create: `delector/routes/__init__.py` (统一注册 `register_routes(app)`)
- Move: 8 个 `routes_*.py` → `delector/routes/`
  - `routes_a1.py` → `routes/a1.py`
  - `routes_a1_hoeren.py` → `routes/a1_hoeren.py`
  - `routes_a1_lesen.py` → `routes/a1_lesen.py`
  - `routes_a2.py` → `routes/a2.py`
  - `routes_corpus.py` → `routes/corpus.py`
  - `routes_exam.py` → `routes/exam.py`
  - `routes_rtc.py` → `routes/rtc.py`
  - `routes_sync.py` → `routes/sync.py`
- Extract: server.py 中 ~60 个直接挂在 `@app` 上的 handler → `routes/main.py`
- Modify: `server.py` → 瘦身为 app 工厂（~200 行）

**Interfaces:**
- `routes/__init__.py`: `def register_routes(app: FastAPI) -> None`
- `server.py`: `def create_app() -> FastAPI` (工厂函数，替代模块级 `app = FastAPI()`)

**Subagent Prompt Scaffold:**
> "Implement Task 4: Extract routes from server.py into delector/routes/ sub-package.
> Goal: Reduce server.py from 2418 lines to ~200 lines (app factory only).
> Target Files: Create `delector/routes/__init__.py`, Move 8 route files, Create `delector/routes/main.py` (extracted handlers), Rewrite `delector/server.py`.
> Steps:
> 1. Create `delector/routes/__init__.py` with `register_routes(app)`.
> 2. Move 8 `routes_*.py` → `delector/routes/`.
> 3. Extract ~60 inline handlers from server.py → `delector/routes/main.py`.
> 4. Rewrite `server.py` as app factory: `create_app()` returns configured FastAPI instance.
> 5. Update `start.py` to use `create_app()`.
> 6. Update tests that import from `delector.server` to import from new locations.
> 7. Run `pytest -x` — 582 must pass.
> 8. Git commit: `refactor: extract routes from server.py into delector/routes/`"

**Step Breakdown:**
- [x] Step 1: Create routes sub-package with register_routes()
- [x] Step 2: Move 8 route files
- [x] Step 3: Extract inline handlers → routes/main.py
- [x] Step 4: Rewrite server.py as app factory
- [x] Step 5: Update start.py（见下「偏差」①：保留模块级 `app` 单例，未改 create_app）
- [x] Step 6: Update test imports
- [x] Step 7: Run full test suite — 由 583 基线升到 586（582 + 迁移哨兵 + 1 新增注册守卫）
- [x] Step 8: Git atomic commit

**Status（2026-09-06 完成）：** T4 落地。server.py 2418 行 → 330 行 app 工厂；通用 handler 抽到 routes/main.py（67 路由）；8 个路由模块搬进 `delector/routes/` 并经 `register_routes(app)` 统一挂载（main 最后，保注册序）。

**偏差 / 决策：**
1. **start.py 未改用 `create_app()`**：保留 `from delector.server import app`。原因——`start.py` 调 `create_app()` 会再建一份 app、重复跑 `init_db`/`seed_preset_articles`；模块级单例由工厂产出、与 uvicorn 入口一致，是更稳的做法。
2. **routes/main.py 与 server.py 的未用 re-export 导入已 prune**（pyflakes 干净）：server.py 仅保留真实被 handler/测试消费的 re-export 面；main.py 删掉 20 个未用符号。
3. **打包 hidden-import 补 `delector.routes.main`**：`package_windows.py` 与 `.github/workflows/build-release.yml` 两处均补，避免打包后漏模块（routes_a2 同类事故）。
4. **新增守卫测试** `tests/test_server.py::test_register_routes_covers_every_module_in_routes_package`：比对端点函数对象（非路径字符串，router 的 path 不含 prefix 比不出），并做「删 `include_router(main.router)` 必红」变异验证，防新增路由模块忘了挂。
5. **docs 静态契约测试跟迁**：`test_german_workbench.py` 改读 `routes/main.py` 的 `@router.get("/api/audio/tts")`；`test_audit_hardening.py` 改读 `routes/main.py` 的 `review_card_sm2`；`tools/vault-proactive-scan.py` 的 `VocabCardReq` 来源改 `routes.main`。

---

### Task 5: 搬迁服务层 — `delector/services/`

**Files:**
- Create: `delector/services/__init__.py`
- Move/.rename:
  - `writing_rules.py` → `services/writing.py`
  - `essay_diff.py` → `services/essay_diff.py`
  - `exam_catalog.py` → `services/exam_catalog.py`
  - `edge_tts_mini.py` → `services/tts.py`
- Modify: ~8 个消费方

**Subagent Prompt Scaffold:**
> "Implement Task 5: Move service layer into delector/services/.
> Goal: Group business logic services (writing, essay diff, exam catalog, TTS).
> Steps:
> 1. Create `delector/services/__init__.py`.
> 2. Move/rename 4 service files.
> 3. Update all consumer imports.
> 4. Run `pytest -x` — 582 must pass.
> 5. Git commit: `refactor: move service layer into delector/services/`"

**Step Breakdown:**
- [ ] Step 1: Create services sub-package
- [ ] Step 2: Move/rename 4 service files
- [ ] Step 3: Update consumer imports
- [ ] Step 4: Run full test suite — 582 全绿
- [ ] Step 5: Git atomic commit

---

### Task 6: 搬迁基础设施层 — `delector/core/`

**Files:**
- Create: `delector/core/__init__.py`
- Move:
  - `database.py` → `core/database.py`
  - `security.py` → `core/security.py`
  - `utils.py` (Task 1 创建) → `core/utils.py`
- Keep: `server.py` 在顶层（app 工厂，不搬进 core）

**Subagent Prompt Scaffold:**
> "Implement Task 6: Move infrastructure into delector/core/.
> Goal: Group database, security, utils into core sub-package.
> Steps:
> 1. Create `delector/core/__init__.py`.
> 2. Move 3 infrastructure files.
> 3. Update all consumer imports (most impacted: server.py, routes/*, nlp_engine/).
> 4. Run `pytest -x` — 582 must pass.
> 5. Git commit: `refactor: move infrastructure into delector/core/`"

**Step Breakdown:**
- [ ] Step 1: Create core sub-package
- [ ] Step 2: Move 3 infrastructure files
- [ ] Step 3: Update consumer imports
- [ ] Step 4: Run full test suite — 582 全绿
- [ ] Step 5: Git atomic commit

---

### Task 7: 创建 Agent 工具接口层 — `delector/tools/`

**Files:**
- Create: `delector/tools/__init__.py`
- Create: `delector/tools/ingest.py` (文章摄入，薄包装 security.fetch_remote_html)
- Create: `delector/tools/analyze.py` (NLP 分析，薄包装 nlp_engine)
- Create: `delector/tools/exercise.py` (练习生成，薄包装 services)
- Create: `delector/tools/export.py` (导出，薄包装 database.export_anki_deck)
- Create: `delector/tools/tts_tool.py` (TTS，薄包装 services.tts)

**Interfaces:**
- 每个 tool 暴露统一签名：`async def run(payload: dict) -> dict`
- 这是 Go Agent 调用 Python 的 HTTP API 契约原型

**Subagent Prompt Scaffold:**
> "Implement Task 7: Create delector/tools/ interface layer for Go Agent integration.
> Goal: Define the Python-side tool interface that Go Agent Runtime will call via HTTP.
> Steps:
> 1. Create `delector/tools/__init__.py` with `TOOL_REGISTRY` dict.
> 2. Create 5 tool modules, each wrapping existing logic behind `async def run(payload: dict) -> dict`.
> 3. Add FastAPI routes in `delector/routes/tools.py` for HTTP access: `POST /api/tools/{tool_name}`.
> 4. Register in `routes/__init__.py`.
> 5. Write tests for each tool endpoint.
> 6. Run `pytest -x` — 582 + new tests must pass.
> 7. Git commit: `feat: add delector/tools/ interface layer for Go Agent integration`"

**Step Breakdown:**
- [ ] Step 1: Create tools sub-package with TOOL_REGISTRY
- [ ] Step 2: Implement 5 tool wrappers
- [ ] Step 3: Add HTTP routes for tools
- [ ] Step 4: Register tools routes
- [ ] Step 5: Write tool endpoint tests
- [ ] Step 6: Run full test suite
- [ ] Step 7: Git atomic commit

---

## 重构后的目标结构

```
delector/
├── __init__.py              ← 版本号 + 顶层导出
├── server.py                ← ~200 行 app 工厂 (create_app)
│
├── core/                    ← 基础设施
│   ├── __init__.py
│   ├── database.py          ← 1449 行 SQLite 操作
│   ├── security.py          ← 333 行 SSRF 防护 + RSS
│   └── utils.py             ← is_android + attachment_headers
│
├── nlp_engine/              ← 语言学引擎
│   ├── __init__.py
│   ├── processor.py         ← process_german_text()
│   ├── syntax_tree.py       ← 句法树 + 五领域分析
│   └── linguistics.py       ← 556 动词 + 复合词拆分
│
├── data/                    ← 纯数据字典 (~9000 行)
│   ├── __init__.py
│   ├── a1.py, a1_hoeren.py, a1_lesen.py, a1_writing.py
│   ├── core.py, core_ext.py
│   ├── corpus.py, prep.py
│
├── routes/                  ← HTTP 路由 (薄层)
│   ├── __init__.py          ← register_routes(app)
│   ├── main.py              ← 从 server.py 提取的 ~60 个 handler
│   ├── a1.py, a1_hoeren.py, a1_lesen.py, a2.py
│   ├── corpus.py, exam.py, sync.py, rtc.py
│   └── tools.py             ← Agent 工具 HTTP 端点
│
├── services/                ← 业务逻辑
│   ├── __init__.py
│   ├── writing.py, essay_diff.py, exam_catalog.py, tts.py
│
└── tools/                   ← Agent 工具接口 (Go 调用契约)
    ├── __init__.py
    ├── ingest.py, analyze.py, exercise.py, export.py, tts_tool.py
```

---

## Phase 2: Go Agent Runtime（概要，Phase 1 完成后细化）

| Task | 内容 | 依赖 |
|---|---|---|
| T8 | Go 脚手架：cobra CLI + go.mod + 项目结构 | 无 |
| T9 | HTTP client 封装：调用 Python `POST /api/tools/{name}` | T8 |
| T10 | DAG Scheduler：自研 ~800 行 Go（goroutine + channel） | T8 |
| T11 | LLM 集成：go-openai-compatible 调 DeepSeek | T8 |
| T12 | Tool Registry：将 5 个 Python tools 注册为 Go Agent tools | T9, T10 |
| T13 | Python 进程管理：supervisor（heartbeat + crash recovery） | T9 |
| T14 | 跨平台打包：Go 二进制 + Python venv | T8-T13 |
| T15 | 集成测试：Go→Python 全链路 | T14 |

---

## 执行约束

1. **每个 Task 独立可回滚** — 每步完成后 `pytest -x` 全绿才 commit
2. **import 变更用 `from delector.xxx import yyy` 而非 `import delector.xxx`** — 保持显式
3. **`__init__.py` 必须定义 `__all__`** — 显式导出，不允许隐式
4. **搬迁期间保留 re-export shim** — 旧路径 import 在 `__init__.py` 中 re-export，给 Android 端缓冲时间
5. **数据库文件不搬** — `delector.db` / `progress.db` 留在仓库根，由 `core/database.py` 的 `DATA_DIR` 指向
