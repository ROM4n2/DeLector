# 子计划 2/5 · `/api/cards` 排序成本量化与索引决策 Implementation Plan

> **Goal**: 先**实测** `GET /api/cards` 的 93.8 ms 由什么构成（排序 filesort / 回表 / Python 物化 / 逐卡 FSRS 递推各占多少），**再据数据决定**是否加索引；不允许"先加索引再看效果"。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL)
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（P1「`/api/cards` 无分页 + 排序右段无索引」）
> **Global Constraints**:
> - **零 `static/` 改动 ⇒ 零发版**（纯后端 + 测试 + 工具脚本）。
> - 测量必须用**临时目录 / 内存库**（`tempfile.mkdtemp()` + `DATABASE_PATH` 环境变量），**严禁**打开仓库根的真实 `delector.db`。
> - 门禁：`ruff` ＋ 两道 mypy ＋ 分半 pytest ＋ 探针。

---

## 🏛️ Decisions So Far

- **EXPLAIN 已实测**（审计 dba 座，20k 行）：`SCAN vocab_cards USING INDEX idx_vocab_srs` + **`USE TEMP B-TREE FOR RIGHT PART OF ORDER BY`**，SQLite 侧 93.8 ms。现有索引仅 `idx_vocab_srs(mastered, due_date)` / `idx_vocab_article(article_id)`。
- **但 Reviewer 独立推演质疑成立**：`SELECT *`（19 列）必然回表 2 万次，加 `dict(r)` 物化，再加逐卡 `get_fsrs_next_intervals`（**2 万卡 = 8 万次递推 + 8 万次 `datetime.now()`**）。**filesort 到底占多少，未知 ⇒ 必须先量。**
- **不预判结论**：若 FSRS 递推占大头，加索引收益有限 —— **本子计划可能只交付"测量结论"而不改 schema**，这是合法结局。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 分段计时，拆解 `/api/cards` 的成本构成 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_cards_endpoint.py`（**可复跑的基准脚本**，非一次性；`tempfile` 隔离）
- Create: `tests/test_cards_endpoint_cost.py`（把结论钉成**可回归的断言**）

**Interfaces:**
- Consumes: `delector.core.database.init_db` / `get_db`、`delector.routes.main.get_cards`、`get_fsrs_next_intervals`
- Produces: 脚本输出**四段**计时（同一份数据）：① `SELECT id ... ORDER BY mastered ASC, wrong_count DESC, id DESC`（覆盖索引）② 同上但 `SELECT *`（差值 = 多列回表）③ `SELECT *` 无 ORDER BY（差值 = 排序 filesort）④ `get_cards()` 全程（含 `dict(r)` 物化 + FSRS 递推）。每段**≥5 轮取中位数**，规模覆盖 **1k / 20k / 50k**（看线性还是拐点）。

**Injected Instincts:**
- [ ] `[Instinct: Realistic-Data]`: 造的数据 MUST 贴近真实分布（`mastered` 多数 0、`wrong_count` 有零有非零、19 列填满），**MUST NOT** 全 0 值（会让 filesort 成本失真）。
- [ ] `[Instinct: Isolated-DB]`: **MUST** 用 `tempfile.mkdtemp()` + `DATABASE_PATH`/`PROGRESS_DB_PATH`，`finally` 清理；**MUST NOT** 碰仓库根的真实库。
- [ ] `[Instinct: Median-Not-Mean]`: 取**中位数**（单次计时会被 GC/磁盘噪声污染）。
- [ ] `[Instinct: No-Silent-Conclusion]`: 报告**必须**给出「filesort 占比 X%」这类**可判定结论**，MUST NOT 只贴原始数字。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 量化 `GET /api/cards` 的成本构成。
> Mode: AFK | Role: TDD Builder
> Goal: 用可复跑脚本拆出「排序 filesort / 回表 / Python 物化 / 逐卡 FSRS 递推」四段各占多少，为是否加索引提供数据依据。
> Target Files: Create `tools/bench_cards_endpoint.py`、`tests/test_cards_endpoint_cost.py`。
> Interfaces: Produces 脚本按 1k/20k/50k 三规模 × 四段输出中位数与 filesort 占比结论。
> Injected Instincts: Realistic-Data / Isolated-DB（严禁碰真实 `delector.db`）/ Median-Not-Mean / No-Silent-Conclusion。
> TDD Steps:
> 1. 写 `tests/test_cards_endpoint_cost.py`（RED）：断言脚本**存在且可跑**、输出**含四个分段标签**、且给出**一个可解析的 filesort 占比数字**。先跑确认红。
> 2. 写 `tools/bench_cards_endpoint.py`：`tempfile.mkdtemp()` 隔离 → `init_db` → 批量插 N 行（真实分布）→ 四段计时（5 轮取中位数）→ 打印规模/分段/占比 → `finally` 清理。
> 3. 跑脚本，把**完整输出**贴回来。
> 4. 跑测试确认绿。
> 5. 变异验证：把脚本里的 `SELECT *` 改成 `SELECT id` ⇒ 测试必须红（证明真在检视分段差异，不是恒真）。
> 6. 门禁：`ruff` + 两道 mypy + 探针。
> Return: Summary + **完整基准输出** + filesort 占比结论。"

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）**
- [ ] **Step 2: 写基准脚本并跑出真实数据**
- [ ] **Step 3: 测试转绿**
- [ ] **Step 4: 变异验证**
- [ ] **Step 5: Physical Evidence Gate**
- [ ] **Step 6: Git 原子 commit**

---

## 🌫️ Fog of War

- **[Fog 1] 加不加索引取决于 Task 1 的数据**：
  - filesort 占比 **> 50%** ⇒ 加 `CREATE INDEX idx_vocab_list ON vocab_cards(mastered, wrong_count DESC, id DESC)`（`grammar_cards` 同理），预期消除 `USE TEMP B-TREE`。
  - 占比 **< 30%** ⇒ **不加索引**（收益有限、写代价真实），把结论写进报告后结案。
  - 中间区间 ⇒ 需带**写代价**评估（每次 INSERT/UPDATE 多维护一个 3 列 B-tree）后再定。
- **[Fog 2] keyset 分页**（真解法，O(N)→O(page)）：影响 `cards.js:139-148` 客户端 segment 过滤、`:197-199` `deckIndex` 依赖全量数组算 `total`、`exam_catalog.py:84` 共享 `api_prefix`（跨 3 个前端模块）⇒ **需发版**，等 Fog 1 量化后另立子计划。
- **[Fog 3] FSRS 递推本身能否批量化**：若它是大头，是否值得为 `/api/cards` 单独算一列"下次复习间隔"（写时算、读时读）？这属 schema 变更，另立。

---

## 🚫 Out of Scope

- 不改 `GET /api/cards` 的响应结构（`cards.js:78-83` 消费方式零改动）
- 不做 keyset 分页（见 Fog 2）
- 不在本任务加任何索引（**Task 1 只测量**，加索引是 Fog 1 的决策产物）
