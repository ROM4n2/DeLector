# 统一池 P0 收口：部署面数据不丢 + 读取面不说谎 Implementation Plan

> **Goal**: 修掉 2026-10-03 全量审计（`docs/reviews/2026-10-03-swarm-audit-master.md`）的 3 条 P0——存量 Docker 升级后静默空库、`.env` 密钥进镜像层、工作台词被投进 KARTEI「今日到期」并配一句说谎的卡面。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL) · Docker(Compose) · 原生 ES Modules 前端（**本计划 T1~T4 不改前端**）
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（P0-1 / P0-2 / P0-3）＋ `docs/adr/2026-09-29-adr-0016-unified-vocab-pool-architecture.md`（§4/§5）＋ Vault `01-Rules/DATABASE-MIGRATION-IDEMPOTENCY` §4、`01-Rules/STORED-DATA-BACKFILL`（只补空）
> **Global Constraints**:
> - **改动含 `static/` ⇒ 必须发版 + Android 覆盖安装**（项目红线）。故 T1~T4 **一律零 `static/` 改动**；唯一需动前端的任务是 T5，已标 `[Mode: HITL]`。
> - 门禁全绿才算完成：`ruff check .` ＋ `mypy --strict delector tools` ＋ `mypy --follow-imports=skip tests` ＋ 分半 pytest（`--ignore=tests/test_server.py` / 单跑 `tests/test_server.py`）＋ 全 `tools/*.mjs` 探针。
> - 测试库隔离契约 C1–C4：**模块级 MUST NOT 赋值 DB env**；需要独立库的模块用 autouse fixture「钉 env → `init_db()` → 还原」。
> - **诚实留空 / 只补空 / 幂等**；**FSRS≠DSR**：MUST NOT 把工作台 `reps` 写进 `repetition_count`，MUST NOT 拿 DSR 语义猜 FSRS 语义（**禁止**「`reps>0` 就补 `fsrs_s=1.0`」——那是编造 FSRS 状态，`s` 决定间隔，且此后 `fsrs_s>0` 变成永久说谎的标记）。
> - UTF-8 写入（Windows GBK 陷阱）；提交信息 `feat|fix|test|refactor|docs|ci(scope): 中文描述`，**禁 `--no-verify`**。
> - **「工作台来源」判据的唯一依据**：`vocab_cards.fsrs_s` 的**唯一按工作台卡语义写入者**是 `delector/core/vocab_pool.py`；卡盒 DSR 复习（`routes/main.py` 的 `review_card_sm2`）**不写** `fsrs_*`。⇒ `fsrs_s IS NOT NULL` ⇔ 该行来自工作台投影。

---

## 🏛️ Decisions So Far

- **ADR-0016**：`vocab_cards` = 「我的词汇」的服务端权威派生态；工作台 localStorage 降级为离线缓存。
- **ADR-0015**：归一唯一实现 = `delector/data/lexicon_merge.py::lemma_key`（禁第二份）。**故本计划禁止用 SQL `lower()` 近似归一**。
- **P0-1 修法选「fail-loud 而非自动迁移」**：检测到「新位置无库 + 旧位置有非空库」⇒ 打 `logging.error`（含两个绝对路径 + 可直接复制的 `cp` 命令）并**抛异常拒绝建空库**。理由：宁可见的 crash-loop，也不要静默空库；且避免在启动路径上做用户没要求的写操作。
- **P0-3 修法只动后端**：`fsrs_s IS NOT NULL AND repetition_count = 0` 的行**不进 due 队列**。卡面文案（T5）需动 `static/` ⇒ 单独 HITL 任务并承担发版面。
- **`GET /api/wb/state` 的 LAN 免 key 放行是刻意设计**（`main.py:1468-1469` 注释），本计划不动它。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 数据目录迁移闸（fail-loud） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py:35-51`（`DATA_DIR` / `get_db_path` 邻近）、`:216`（`init_db` 入口）
- Create: `tests/test_data_dir_migration_gate.py`
- Modify: `docker-compose.yml`（卷段注释）、`README.md:88-92`、`docs/agents/ops.md:36-40`、`.env.example`、`CHANGELOG.md`

**Interfaces:**
- Consumes: `os.path.exists(path) -> bool`、`os.path.getsize(path) -> int`、`logging.getLogger("delector")`
- Produces: `def preflight_data_dir(data_dir: str, repo_root: str) -> None` —— 纯函数、**不碰 DB**、**不写文件**；`data_dir == repo_root`（规范化后）直接 return
  - 抛错条件（四者同时成立）：`os.path.join(data_dir, "delector.db")` 不存在 **且** `os.path.join(repo_root, "delector.db")` 存在 **且** `os.path.getsize(...) > 0` **且** 两路径不同
  - 抛 `RuntimeError`，消息 MUST 含：两个绝对路径 + 一条可直接复制的 `cp "<旧>" "<新>"` 命令
  - `init_db()` MUST 在建表**之前**调用它
- Produces (docs): `README.md` / `docs/agents/ops.md` / `docker-compose.yml` 卷段注释三处 MUST 出现「从旧版单文件挂载升级」的迁移步骤；`.env.example` MUST 补 `DELECTOR_DATA_DIR`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Fail-Loud]`: 发现数据在旧位置 ⇒ **抛异常**，绝不 `logging.warning` 后继续建空库。
- [ ] `[Instinct: Honest-Null]`: 旧库文件存在但 size==0 ⇒ 视为「无数据」，**不**拦启动（避免空文件误报）。
- [ ] `[Instinct: No-Silent-Write]`: 迁移闸**只读不写**；修数据由用户照日志里的 `cp` 自己做。
- [ ] `[Instinct: Idempotent]`: 正常路径必须零输出，重复启动不得重复报警。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 数据目录迁移闸（fail-loud）。
> Mode: AFK | Role: TDD Builder
> Goal: 当「新数据目录无库、旧位置有非空库」时**拒绝启动**并给出可操作的迁移指引，杜绝 Docker 升级后的静默空库。
> Target Files: Modify `delector/core/database.py`；Create `tests/test_data_dir_migration_gate.py`；Modify `docker-compose.yml` / `README.md` / `docs/agents/ops.md` / `.env.example` / `CHANGELOG.md`。
> Interfaces: Produces `preflight_data_dir(data_dir: str, repo_root: str) -> None`（纯函数、不写文件）；`init_db()` 在建表前调用它。
> Injected Instincts: Fail-Loud；Honest-Null（size==0 不拦）；No-Silent-Write；Idempotent（正常路径零输出）。
> TDD Steps:
> 1. 写 4 个用例（RED）：① 新位置无库 + 旧位置非空 ⇒ `pytest.raises(RuntimeError)` 且消息含两个路径与 `cp`；② 旧位置 size==0 ⇒ **不**抛；③ `data_dir == repo_root` ⇒ **不**抛；④ 旧位置非空但新位置**已有**库 ⇒ **不**抛。
> 2. 跑 `python -m pytest tests/test_data_dir_migration_gate.py -q`，确认 4 条全红且失败原因是函数不存在。
> 3. 实现 `preflight_data_dir`（路径规范化后比较，不引新依赖）。
> 4. 在 `init_db()` 建表前调用；复跑确认 4 条全绿。
> 5. 变异验证：把「size>0」判据去掉，确认用例①转红，再还原。
> 6. 补 6 处文档（compose 卷段注释 / README / ops.md / `.env.example` 补 `DELECTOR_DATA_DIR` / CHANGELOG 新增小节）。
> 7. 门禁：`ruff check .` ＋ 两道 mypy ＋ 分半 pytest ＋ 全 `tools/*.mjs` 探针。
> Return: Summary + MANDATORY Physical Execution Receipt（原始 exit code + 通过数 + `git diff --stat`）。"

**Step Breakdown:**
- [ ] **Step 1: 写 4 个失败用例（RED）**
- [ ] **Step 2: 跑测试并确认失败原因是函数不存在**
- [ ] **Step 3: 实现 `preflight_data_dir` + 在 `init_db()` 前调用（GREEN）**
- [ ] **Step 4: 跑目标测试确认全绿**
- [ ] **Step 5: Refactor —— 路径规范化抽小函数，守卫子句扁平化**
- [ ] **Step 6: Physical Evidence Gate**：原始 exit code + 通过数 + `git diff --stat` + 6 处文档 diff
- [ ] **Step 7: Git 原子 commit**

---

### Task 2: `.dockerignore` + CI 静态守卫（密钥与库文件不入镜像） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `.dockerignore`（仓库根）
- Modify: `tests/test_ci_hardening.py`（`DOCKERFILE` 守卫邻近处）

**Interfaces:**
- Consumes: `REPO_ROOT`（`tests/test_ci_hardening.py:27` 已有）、`_read_guard_file(path)`
- Produces: `.dockerignore` 至少覆盖 `REQUIRED = {".git", ".env", ".env.*", "*.db", "*.db-wal", "*.db-shm", "*.apk", "*.jks", "*.keystore", "__pycache__", ".cache"}`
- Produces (test): `def test_dockerignore_excludes_secrets_and_databases() -> None`（缺文件即红；逐条 `REQUIRED` 命中即绿）

**Injected Instincts:**
- [ ] `[Instinct: Redaction]`: MUST NOT 用 `*` 把 `Dockerfile` / `delector/` 排掉（构建会坏）；只排**明确敏感/产物**项。
- [ ] `[Instinct: Supply-Chain]`: 本任务只管构建上下文，不引入任何依赖。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: `.dockerignore` + CI 静态守卫。
> Mode: AFK | Role: TDD Builder
> Goal: 让 `docker build` 的构建上下文**不含** `.env`（明文密钥）、`*.db`（用户数据）与缓存/产物。
> Target Files: Create `.dockerignore`；Modify `tests/test_ci_hardening.py`。
> Interfaces: Produces `test_dockerignore_excludes_secrets_and_databases()`；`REQUIRED` 集合见任务书。
> Injected Instincts: Redaction（不得用 `*` 把 Dockerfile/delector 排掉）；Supply-Chain。
> TDD Steps:
> 1. 先写 `test_dockerignore_excludes_secrets_and_databases`（RED）——缺 `.dockerignore` 即红。
> 2. 跑 `python -m pytest tests/test_ci_hardening.py -q -k dockerignore` 确认红。
> 3. 创建 `.dockerignore` 逐条覆盖 `REQUIRED`（GREEN）。
> 4. 复跑全绿；再删掉其中一条确认守卫转红（**变异验证**），然后加回。
> 5. 门禁：`ruff check .` ＋ 两道 mypy ＋ 分半 pytest ＋ 探针。
> Return: Summary + Physical Execution Receipt（含变异转红的原始输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写守卫测试（RED）**
- [ ] **Step 2: 确认红（缺文件）**
- [ ] **Step 3: 创建 `.dockerignore`（GREEN）**
- [ ] **Step 4: 复跑全绿**
- [ ] **Step 5: 变异验证（删一条 ⇒ 守卫必红）**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

### Task 3: due 队列排除「工作台来源且无卡盒进度」的行 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py:1698-1722`（`get_due_cards`）
- Test: `tests/test_server.py`（追加用例，沿用既有 `clean_db` / `client` 夹具）

**Interfaces:**
- Consumes: `db_conn()`、`get_fsrs_next_intervals(...)`
- Produces: `get_due_cards()` 的 `vocab_cards` 分支追加谓词 **`AND NOT (fsrs_s IS NOT NULL AND repetition_count = 0)`**；**响应键 `due_vocab` / `due_grammar` / `due_count` / `today` MUST 逐字不变**（前端 `cards.js:80,110` 在消费）；`grammar_cards` 分支 **MUST NOT 改**（无 `fsrs_s` 列）

**Injected Instincts:**
- [ ] `[Instinct: No-Cross-Semantics]`: 判据 MUST 用 `fsrs_s`（工作台 FSRS 侧）**与** `repetition_count`（卡盒 DSR 侧）**并置**；MUST NOT 依赖 `mastered`（已在 WHERE 里）或任何新列。
- [ ] `[Instinct: Contract-Frozen]`: 只改**行集合**，不改键名与结构。
- [ ] `[Instinct: Idempotent]`: 纯读端点，MUST NOT 引入写或迁移。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: due 队列排除工作台来源行。
> Mode: AFK | Role: TDD Builder
> Goal: 工作台投影进来的词（有 `fsrs_s`、无卡盒 DSR 进度）MUST NOT 落进 KARTEI「今日到期」。
> Target Files: Modify `delector/routes/main.py`（`get_due_cards`）；Test `tests/test_server.py`。
> Interfaces: Produces 谓词 `AND NOT (fsrs_s IS NOT NULL AND repetition_count = 0)`；响应键逐字不变。
> Injected Instincts: No-Cross-Semantics；Contract-Frozen；Idempotent。
> TDD Steps:
> 1. 写 3 个用例（RED）：① 插一行 `fsrs_s=12.3, repetition_count=0, mastered=0, due_date=NULL` ⇒ `GET /api/cards/due` **不含**它；② `fsrs_s=12.3, repetition_count=2`（曾在卡盒复习）⇒ **仍含**；③ reader 普通卡（`fsrs_s` NULL、`repetition_count=0`）⇒ **仍含**（旧语义不回归）。
> 2. 跑 `python -m pytest tests/test_server.py -q -k due`，确认 ① 红。
> 3. 改 `get_due_cards` 的 vocab 分支 SQL（GREEN）。
> 4. 复跑确认 3 条全绿；再删掉谓词确认 ① 转红（变异验证），然后加回。
> 5. 门禁：`ruff check .` ＋ 两道 mypy ＋ 分半 pytest ＋ 探针。
> Return: Summary + Physical Execution Receipt（含变异转红原始输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写 3 个用例（RED）**
- [ ] **Step 2: 确认 ① 红、②③ 绿**
- [ ] **Step 3: 改 SQL（GREEN）**
- [ ] **Step 4: 复跑全绿**
- [ ] **Step 5: 变异验证（去谓词 ⇒ ① 必红）**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

### Task 4: `known-lemmas` 等价性 docstring 照实改写 + 端到端测试格 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py:712-740`（`get_known_lemmas` 的 **docstring only**）
- Test: `tests/test_unified_pool_e2e.py`（追加端到端格）

**Interfaces:**
- Consumes: 现有 `PUT /api/wb/state` → `save_wb_state` → `project_wb_deck` → `GET /api/cards/known-lemmas` 全链路（**不改任何实现**）
- Produces (docstring): MUST 降级为「该等价性**仅对本仓工作台自造卡**成立（`fsrsReview` 与字面量恒含 `s`）；导入/外部推送的卡未经形状校验，故不等价」，并 MUST 点明可达入口（`applyOverwrite` / `wb_put_state` / `loadAll` 零形状校验）
- Produces (test): 一条**端到端**用例（真 `PUT /api/wb/state` → 真 `GET /api/cards/known-lemmas`），显式覆盖 `reps>0 ∧ s 缺失` 的卡，用例 docstring 注明「当前行为＝漏计，属**已知缺口**；是否收紧范围闸见 Fog 1」

**Injected Instincts:**
- [ ] `[Instinct: Doc-Truth]`: docstring MUST NOT 写任何实现不能保证的断言；「当前恰好如此」≠「恒如此」。
- [ ] `[Instinct: No-Silent-Behavior-Change]`: 本任务**只改文档 + 加测试**，MUST NOT 改 `known-lemmas` 的 SQL 或投影行为。
- [ ] `[Instinct: Test-Honesty]`: 端到端用例 MUST 走真实端点与真实投影，MUST NOT 直接调内部函数伪造。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: `known-lemmas` 等价性文档 + 端到端测试格。
> Mode: AFK | Role: TDD Builder
> Goal: 修掉 `get_known_lemmas` docstring 里「故该条件等价于工作台 `reps>0`」这个**只对自造卡成立**的绝对化断言，并补端到端测试格。
> Target Files: Modify `delector/routes/main.py`（**仅 docstring**）；Test `tests/test_unified_pool_e2e.py`。
> Interfaces: Produces 降级后的 docstring + 一条走真实端点的端到端用例。
> Injected Instincts: Doc-Truth；No-Silent-Behavior-Change（**禁止**改 SQL/投影行为）；Test-Honesty。
> TDD Steps:
> 1. 在 `tests/test_unified_pool_e2e.py` 写端到端用例：deck 含 ①`hw='Bahn', cards={'reps':2,'s':2.3,'d':5,'lapses':0}`（有 s）②`hw='Ufer', cards={'reps':2}`（**无 s**）③ 冷种子词（无卡、非 custom）→ 断言 `known-lemmas` **含 ①、不含 ③**；对 ② 显式断言当前行为（不入）并在用例 docstring 注明「已知缺口」。
> 2. 跑 `python -m pytest tests/test_unified_pool_e2e.py -q -k known`，确认真实链路被跑通。
> 3. 照实改写 docstring（三条来源 + 等价性边界 + 可达入口）。
> 4. 变异验证：临时去掉 `main.py:738` 的 `OR fsrs_s > 0`，确认新用例中 ① 转红，然后还原。
> 5. 门禁：`ruff check .` ＋ 两道 mypy ＋ 分半 pytest ＋ 探针。
> Return: Summary + Physical Execution Receipt（含变异转红原始输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写端到端用例（走真实端点）**
- [ ] **Step 2: 跑通并记录当前真实行为**
- [ ] **Step 3: 照实改写 docstring**
- [ ] **Step 4: 复跑全绿**
- [ ] **Step 5: 变异验证（去掉 `OR fsrs_s > 0` ⇒ 用例必红）**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

### Task 5: 卡面区分工作台来源（含发版面） [Mode: HITL] [Role: Checker]

> ⚠️ **本任务改 `static/js/cards.js` ⇒ 触发项目红线「改动含 `static/` 必须发版 + Android 覆盖安装」**，且需用户拍板「是否随本 PR 发版」。**未经用户确认 MUST NOT 执行。**

**Files:**
- Modify: `static/js/cards.js:284` 附近（`⏳ 待复习 · N 正 / N 误` 的渲染分支）
- Modify（仅当决定发版）: `static/sw.js`、`static/index.html`、`android/app/build.gradle`、`README.md`、`CHANGELOG.md`、`WORKMEMORY/PROJECT_OVERVIEW.md`（发版五件套）

**Interfaces:**
- Consumes: T3 之后 due 队列已排除工作台词的事实；卡行已有的 `fsrs_s` 字段（`/api/cards` 是 `SELECT *` ⇒ **字段已在响应里，无需改后端**）
- Produces: 卡面在该行 `fsrs_s` 非空时显示工作台 FSRS 状态（如 `📚 工作台 · s=25`），MUST NOT 再显示 `0 正 / 0 误`

**Injected Instincts:**
- [ ] `[Instinct: Release-Discipline]`: 动 `static/` 前 MUST 先确认发版窗口；五件套缺一不可，`tag` MUST 打在含 bump 的 commit 上。
- [ ] `[Instinct: No-Silent-Data-Reveal]`: 显示 `s` 时 MUST NOT 暗示它等价于 DSR 的 `repetition_count`。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 卡面区分工作台来源。**先向用户确认是否发版**，未确认不得动 `static/`。
> Mode: HITL | Role: Checker
> TDD Steps: 1) 确认发版决策；2) 改 `static/js/cards.js` 卡面分支（有 `fsrs_s` ⇒ 显示工作台 FSRS 状态，不显示 `0 正/0 误`）；3) 若发版 ⇒ 走发版五件套并跑守护测试 `tests/test_writer_mobile.py`；4) 门禁 + 探针 + 物理证据回执。"

**Step Breakdown:**
- [ ] **Step 0: 用户确认发版窗口（HITL 闸）**
- [ ] **Step 1: 改卡面渲染分支**
- [ ] **Step 2: 测试/探针钉住新文案**
- [ ] **Step 3: （若发版）五件套同步 + 守护测试**
- [ ] **Step 4: Physical Evidence Gate**
- [ ] **Step 5: Git 原子 commit**

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Fog 1] 是否收紧投影范围闸**：`reps>0` 但缺 `s` 的卡当前**入池但不被 `known-lemmas` 计入**。收紧（要求「能读出正浮点 `s`」才入池）会让 `tests/test_vocab_pool_projection.py:325` 那条**把现状钉成契约**的断言变红——改它需用户拍板是否接受契约变更。**依赖：Task 4 先跑出真实行为。**
- **[Fog 2] 写入侧卡形状校验**：`applyOverwrite`（`static/german/workbench.html:4400`）与 `PUT /api/wb/state`（`main.py:1484`）零校验。「拒收」还是「标记后放行」是产品决策；且前者要改前端 ⇒ 触发发版面。
- **[Fog 3] 删除/重置对池无效**（KARTEI 删词被投影重建、工作台「重置」不清池）——需**墓碑表 or 软删**的产品决策（ADR-0016 §5「不引入墓碑」是否要为这条破例）。
- **[Fog 4] CEFR 派生**（工作台词在 KARTEI 恒显 A1、污染首页欧标分布）：投影期写入 vs 读取期派生两条路各有代价（前者动 `project_wb_deck` 的只补空语义，后者动所有消费端）。**依赖：与 Fog 3 一并做产品决策。**
- **[Fog 5] 审计 Action Plan 3~7 待拆子计划**（当前计划只收 P0）：

| 子计划 | 内容 | 触及面 |
|---|---|---|
| **B** 后端性能/并发 | `_RANK_CACHE` 加锁 + `source=all` 聚合缓存（**锁解不了 257 悬崖**，两者必须配套）；`refreshCardCounters` 计数端点（复用 `main.py:850-853` 现成单扫聚合）+ `idx_vocab_list` + `exam_trials` 索引；`_pool_index`/`lemma_key` 提速（**禁止**用 `lemma` 索引代替归一）；`get_spacy_nlp` 加锁（**禁止**顺手复用 `processor.nlp`＝行为变更） | 后端 + 测试 |
| **C** 前端竞态与反馈 | `openText` 请求代号 + `AbortController`（`core.js:api()` 已支持 `signal`，**零新依赖**）；弹层垂直夹取；列表/详情 deck 同源（改用 `resolveDeck`）；`fetchKnownLemmas` in-flight 去重；离线/加载失败文案 | **前端 ⇒ 需发版** |
| **D** 韧性 | Go `Failures()` 出口；`_db_snapshot_guard` 回滚失败留痕；`/api/audio/tts` 并发闸；真健康端点；`ci.yml` `timeout-minutes`；pin 纪律 | agent + 后端 + CI |
| **E** 测试基建补账 | e2e `group5` 补 `COUNT(*)` 护栏；`static/` 守卫改钉 Phase 3 起点 SHA；清 6 文件 9 处 `except OSError: pass` + `-journal` 后缀；`_fill_updates` 改用 `_READ_INDEX` + 列序重排测试；helper 用例④ 改事件驱动 | 仅测试 |

---

## 🚫 Out of Scope

- **不做自动数据迁移**（P0-1 只做 fail-loud 闸 + 指引命令；自动 copy 属用户未要求的写操作，另立决策）。
- **不新增数据库列**（工作台来源判据复用已有 `fsrs_s`；CEFR 派生见 Fog 4）。
- **不改 `fsrs_*` 与 DSR 列的写入语义**（FSRS≠DSR 铁律）。
- **不迁移工作台存储层**（ADR-0016 Phase 3 的 T3 已决定跳过）。
- **不改 `GET /api/wb/state` 的 LAN 免 key 放行**（刻意设计）。
- **不做发版**（除 T5 获得用户确认外；本计划默认零发版面）。
