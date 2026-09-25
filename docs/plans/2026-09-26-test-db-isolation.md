# 测试库隔离修复 实施计划

> **Goal**: 消除 `tests/` 的跨模块 env 串扰，让半 A 那 2 例 `no such table: exam_trials` 转绿（这是「安全升级 fastapi/starlette」的唯一前置），并把踩过的坑钉成 AST 契约守卫。
> **Tech Stack**: Python 3.10+ / pytest（**仅测试基础设施**；零生产代码改动、零新依赖）
> **Spec Reference**: `docs/specs/2026-09-26-test-db-isolation-design.md`
> **Global Constraints**:
> - **MUST NOT 改 `delector/**`**（`server.app` 单例已证实无辜：`get_db_path()` 每次调用读 env）
> - **MUST NOT 改任何测试断言或测试意图** —— 只改隔离机制（fixture 的 env/建表/清理）
> - **契约 C1–C4**（spec §3.1）：① 模块级 MUST NOT 直接赋值 `DATABASE_PATH` / `PROGRESS_DB_PATH`；② 需要独立库的模块 → autouse fixture 内「捕获 saved → 钉 env → **`init_db()`** → yield → 清理 → 还原 saved」；③ fixture 可删自己的库；④ 纯逻辑模块可不加夹具
> - **不许引入 pytest 插件 / 不改 `conftest.py` 的 sys.path 注入**（那段注释明确"长期需要，别删"）
> - 环境：Windows / bash；Python 前 `export PYTHONIOENCODING=utf-8`
> - 纪律：子代理**不 git add / commit / push / 切分支**；每 Task 收尾跑 目标测试 → ruff → `mypy --strict delector tools` → 全 `tools/*.mjs` 零漂移

---

### Task 1: 消除污染源 + 让受害模块自洽 [Role: TDD Builder]

**Files:**
- Modify: `tests/conftest.py`（追加兜底 env，**不动** sys.path 段）
- Modify: `tests/test_audit_hardening.py`（删模块级 env 赋值 2 行）
- Modify: `tests/test_exam_catalog.py`（同）
- Modify: `tests/test_exam_trials.py`（同）
- Modify: `tests/test_server.py`（同；**只动那 2 行**，勿碰其它 —— 该文件另有在飞改动）
- Modify: `tests/test_goethe_a1_hoeren.py`（fixture 扩展）
- Modify: `tests/test_goethe_a1_lesen.py`（fixture 扩展）

**Interfaces:**
- Consumes: `delector.server.init_db` / `init_progress_db`、`os.environ` 的 `DATABASE_PATH` / `PROGRESS_DB_PATH`
- Produces: 每个测试模块的隔离夹具自洽（钉 env + 建表 + 还原）；`tests/` 中**不再有模块级 env 赋值**

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 消除污染源 + 让受害模块自洽。
> Goal: 修掉半 A 的 2 例 `no such table: exam_trials`（根因：模块级赋值 env → `server` 顶层 `init_db()` 建了别人的库 → 受害模块 `setdefault` 失效 → 那个库又被别人的 fixture 删掉 → 空库无表）。**只改测试隔离机制，不改任何断言。**
> 先读 spec `docs/specs/2026-09-26-test-db-isolation-design.md`（§3.1 契约 C1–C4 + §4 边界）。
> TDD Steps:
> 1. **先固化判别点**：记录修复前 `python -m pytest tests/test_audit_hardening.py tests/test_goethe_a1_hoeren.py -q` 的输出（期望 `1 failed, 34 passed`）与半 A 的 2 例红。这就是本次的 RED 基线。
> 2. **conftest 兜底**：在 `tests/conftest.py` 现有 sys.path 注入之后追加（用 `setdefault`，尊重外部已设值）：
>    ```python
>    os.environ.setdefault("DATABASE_PATH", "test_conftest_default.db")
>    os.environ.setdefault("PROGRESS_DB_PATH", "test_conftest_default_progress.db")
>    ```
>    并补一段 docstring/注释解释：它保证「任何测试模块 import server 之前 env 已有值」，使 `server` 顶层 `init_db()` 不会落到仓库根真实 `delector.db`；同时给各模块 fixture 的 env 还原提供稳定目标。**MUST NOT 改动已有的 sys.path 注入段与其注释。**
> 3. **删污染源**：删掉 `test_audit_hardening.py` / `test_exam_catalog.py` / `test_exam_trials.py` / `test_server.py` 里**模块级**的 `os.environ["DATABASE_PATH"] = ...` 与 `os.environ["PROGRESS_DB_PATH"] = ...` 赋值（各 2 行）。它们的 autouse fixture 本来就会在用例前后钉 env 并 `init_db`，故模块级赋值是冗余且有害的；**若删后某文件出现"未使用的 import os"或空行异常，顺手清理（仅限格式）**。
> 4. **受害者自洽**：把 `test_goethe_a1_hoeren.py` 与 `test_goethe_a1_lesen.py` 的 autouse fixture（现名 `_m5_isolated_db_teardown`，module-scoped，当前**只** `yield` 后清理）扩展为「**前置**：捕获 `saved` env → 钉自己的库名 → `init_db(<自己的库>)` → yield → **后置**：`gc.collect()` + 删自己的库（含 `-journal/-wal/-shm`）→ 还原 `saved`」，并在 docstring 写明"不再依赖上一位 import 者留下的 env；自建库，故与模块执行顺序无关"。
>    库名沿用现有 `test_delector_goethe_a1_hoeren.db` / `test_delector_goethe_a1_lesen.db`；**保留**原有的 `gc.collect()` + Windows 句柄释放注释的意图。
> 5. **GREEN 验证（这是本 Task 的判别点）**：
>    - `python -m pytest tests/test_audit_hardening.py tests/test_goethe_a1_hoeren.py -q` → 期望 **35 passed**（原 `1 failed, 34 passed`）
>    - 污染源 × 受害者组合矩阵全绿：`{test_audit_hardening,test_exam_catalog,test_exam_trials} × {test_goethe_a1_hoeren,test_goethe_a1_lesen}` 逐对跑（6 组），每组 `-q | tail -3`，**全部 0 failed**
>    - 半 A：`python -u -m pytest -q --ignore=tests/test_server.py 2>&1 | tail -4` → **期望 `0 failed`**（原 `2 failed, 891 passed`；passed 数会因环境而异，重点是 0 failed）
>    - 半 B：`python -u -m pytest -q tests/test_server.py 2>&1 | tail -3` → 期望 `228 passed, 1 skipped`（不得回归）
> 6. 清理实验/运行残留的临时库文件（`test_*.db` / `test_*.db-wal` / `test_*.db-shm` 若出现在仓库根）—— 这些是测试产物，`git status` 里不应有它们（若 `.gitignore` 未覆盖则在回报里指出，**不要**擅自改 `.gitignore`）。
> 7. 门禁：`python -m ruff check .` / `python -m mypy --strict delector tools` / `for f in tools/*.mjs; do node "$f" >/dev/null 2>&1 || echo FAIL $f; done`
> **变异验证（判别力，必做，`cp` 备份还原、禁 `git checkout --`）**：把 `test_audit_hardening.py` 的模块级 env 赋值加回去 → 组合测试**必红**（复现原故障）；还原后必绿。
> Return: Summary with test execution evidence（修复前后组合输出、半 A/半 B 统计行、变异验证结论）+ 是否残留临时库文件的说明。"

**Step Breakdown:**
- [ ] **Step 1: 记录 RED 基线**（组合 `1 failed` + 半 A 2 例红）
- [ ] **Step 2: conftest 追加兜底 env**
- [ ] **Step 3: 删 4 个模块的模块级 env 赋值**
- [ ] **Step 4: hoeren/lesen fixture 扩展为「钉 env + init_db + 还原」**
- [ ] **Step 5: 组合矩阵 6 组 + 半 A + 半 B 全绿**
- [ ] **Step 6: 变异验证（加回模块级赋值 → 必红）+ 清理临时库 + 门禁**

---

### Task 2: 根因级 AST 守卫 + 收官 [Role: TDD Builder]

**Files:**
- Create: `tests/test_test_isolation.py`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（就地更新测试契约节：把"env 必须用 setdefault / 不得删库"精确化为 C1–C4）

**Interfaces:**
- Consumes: `ast`（标准库）、`tests/*.py` 源码
- Produces: 一条**根因级守卫** —— 任何模块级直接赋值 `os.environ["DATABASE_PATH"]` / `PROGRESS_DB_PATH` 即判红

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 根因级 AST 守卫 + 收官。
> Goal: 把 2026-09-26 那个坑钉成契约——测试模块**不得在模块级**直接赋值库 env（会让后续模块 `setdefault` 失效、命中被删的空库）；并就地更新文档。
> Target Files: Create `tests/test_test_isolation.py`; Modify `WORKMEMORY/PROJECT_OVERVIEW.md`.
> TDD Steps:
> 1. **写失败测试（RED）**：`tests/test_test_isolation.py`，用 `ast` 解析 `tests/*.py`，检测**模块级**（`ast.Module.body` 顶层，含 `if`/`try` 等顶层块的直接子语句）对 `os.environ["DATABASE_PATH"]` / `os.environ["PROGRESS_DB_PATH"]` 的**赋值**（`ast.Assign` / `ast.AugAssign` / 带 `Subscript` 目标的 `AnnAssign`）。**函数/fixture 内的赋值不算违规**（契约 C2 允许）。
>    - 断言消息要写清后果与修法（fixture 内 set + 还原 + `init_db`，见 spec §3.1 C2）
>    - 先在**当前已修复的状态**下跑 → 应**绿**（Task 1 已删污染源）→ 故 RED 需用变异造：见第 3 步
>    - 额外断言：`tests/conftest.py` 存在且含 `setdefault("DATABASE_PATH"` （兜底契约）；`tests/conftest.py` 仍含 `sys.path` 注入（防误删那段"长期需要"的代码）
> 2. 跑 `python -m pytest tests/test_test_isolation.py -q` → 确认绿。
> 3. **变异验证（判别力，必做，`cp` 备份还原、禁 `git checkout --`）**：临时给 `tests/test_audit_hardening.py` 顶部加回 `os.environ["DATABASE_PATH"] = "x.db"` → 守卫**必红**（点名该文件）；还原后必绿。
> 4. **就地更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 的测试契约节**：把原有的「跨文件 DATABASE_PATH 环境串扰 → 用分半跑」那条**精确化**为修复后的契约（**就地把原因写清，不要新增重复段落**）：
>    - 真凶 = **模块级直接赋值库 env**（永久污染 + 让后来者 `setdefault` 失效 + 那个库又被自己的 fixture 删掉 → 空库 `no such table`）；**MUST NOT** 模块级赋值，改 autouse fixture「钉 env → `init_db()` → 还原」
>    - `tests/conftest.py` 提供兜底默认库（防 `server` 顶层 `init_db()` 落到真实 `delector.db`）
>    - 新增守卫 `tests/test_test_isolation.py`；**分半跑仍保留**（作为跨文件串扰时的定位手段），但不再是"必须分半才可信"的唯一理由
>    - 顺带更新该文件的测试基线数字（以你实测为准）
> 5. 门禁：分半跑全量（半 A 期望 **0 failed**、半 B `228 passed, 1 skipped`）+ `python -m ruff check .` + `python -m mypy --strict delector tools` + 全 `tools/*.mjs` 零漂移。
> 6. **明示**：不改 `CHANGELOG.md`、不 bump 版本号（本计划是测试基础设施修复，不发版）。
> Return: Summary with 守卫的变异验证结论 + 两段分半统计行 + 文档改动落点。"

**Step Breakdown:**
- [ ] **Step 1: 写 AST 守卫测试**（+ conftest 两条契约断言）
- [ ] **Step 2: 跑绿 + 变异验证（加回模块级赋值 → 必红）**
- [ ] **Step 3: 就地精确化 OVERVIEW 的测试契约节 + 更新基线**
- [ ] **Step 4: 分半跑全量（半 A 0 failed）+ ruff/mypy/探针**
- [ ] **Step 5: 明示未改 CHANGELOG / 未 bump 版本**
- [ ] **Step 6: 复核**

---

## 范围外 (Out of Scope)

- 不改 `delector/**`（生产代码零改动）
- 不改任何测试断言/意图；不重构为 per-test `create_app()`
- 不引入 pytest 插件；不动 `conftest.py` 的 sys.path 段
- 不处理"全量（不分半）跑"的本地不可靠性（验收以分半为准；全量作为附加观察）
- 不升级 fastapi/starlette（本修复是其**前置**，升级另行同笔处理）
- 不动与本故障无关的模块（如 `test_tools.py`）

## 验证基线 (Verification Baseline)

| 阶段 | 命令 | 期望 |
|---|---|---|
| T1 | `pytest tests/test_audit_hardening.py tests/test_goethe_a1_hoeren.py -q` | `1 failed, 34 passed` → **35 passed** |
| T1 | 污染源 × 受害者 6 组组合 | 全部 **0 failed** |
| T1 | 半 A `pytest -q --ignore=tests/test_server.py` | **0 failed**（原 `2 failed, 891 passed`） |
| T1 | 半 B `pytest -q tests/test_server.py` | `228 passed, 1 skipped`（不回归） |
| T2 | `pytest tests/test_test_isolation.py -q` | 绿；变异（加回模块级赋值）**必红** |
| T2 | 分半跑 | 半 A 0 failed / 半 B 228+1skip |
| 收官 | `ruff` / `mypy --strict delector tools` / 全 `tools/*.mjs` | 0 告警 / 62 files 0 error / 零漂移 |

## 回滚 (Rollback)

- 逐 Task 原子提交，任一可 `git revert <sha>`。
- 全部改动集中在 `tests/`（+ OVERVIEW 文档）→ 回滚后即回到"模块级 env 抢占 + 2 例红"的旧状态，生产功能零影响。

## 关联索引

- `docs/specs/2026-09-26-test-db-isolation-design.md`
- `docs/specs/2026-09-24-toolchain-guard-truth-design.md`（本修复是其 fastapi 升版的前置）
- `WORKMEMORY/PROJECT_OVERVIEW.md`（测试契约节）
- `01-Rules/TESTING-PATTERNS.md`（测试隔离纪律）
