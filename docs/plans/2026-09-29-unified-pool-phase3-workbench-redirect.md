# 统一词库 Phase 3：工作台存储层重定向 + 一次性迁移 Implementation Plan

> **Goal**: 让统一池（服务端 `vocab_cards`）成为"用户词汇"的**权威**；工作台 localStorage 降级为**离线缓存**；存量数据一次性**幂等**迁移（先备份、后对账）。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL) · 原生 JS ES Modules（`static/german/workbench.html` 单文件）· pytest + Node 探针
> **Spec Reference**: `docs/specs/2026-09-29-adr-0016-unified-vocab-pool-architecture.md`（§4/§5）＋ Vault 规则 `01-Rules/DATABASE-MIGRATION-IDEMPOTENCY`、`01-Rules/STORED-DATA-BACKFILL`、`08-Projects/DeLector/DELECTOR-DEV-RULES.md` §2.1（本地优先 / 数据自主）
> **Global Constraints**:
> - **离线优先不可破**（ADR-0016 §5）：`file://` / 断网下工作台必须完整可用 ⇒ localStorage **永远是读兜底**，服务端只是增强。
> - **迁移谓词 MUST 按内容去重**（Migration-Idempotency §1）：workbench 与统一池**双写并存** ⇒ **禁计数对账**（`==`/`>=` 都不适用），MUST 按 `lemma` / `id` 去重（`NOT EXISTS` 或 UNIQUE）。
> - **回填 MUST 走读取期派生**（Backfill §2）：MUST NOT 只依赖写入期一次性填充。
> - **只增 + 只补空 + 不碰用户数据**（Backfill §4）：`wb.cards.v1`/`log`/`wrong` 与用户手编内容 MUST NOT 被覆盖；二次运行 MUST 零变化、不写盘。
> - **不跨语义来源混用**（Backfill §5）：workbench `gloss`/`ex[].de`（**语境原句**）与官方 `de`/`example_zh`（**词典例句**）语义不同，MUST NOT 顶替同一槽位；`reps`（FSRS）与 `repetition_count`（DSR）语义不同，MUST NOT 互写（FSRS 只进 `fsrs_*` 列）。
> - **迁移单事务原子**（§2）；**还原路径 MUST 补迁移**且与迁移同快照守卫（§4）——复用 PR #69 的 `_db_snapshot_guard`。
> - 门禁：`ruff` 0 + 两道 mypy 0 + 全量 pytest + `tools/*.mjs` 探针全绿；`export PYTHONIOENCODING=utf-8`。

---

## 🏛️ Decisions So Far

- **ADR-0016**：路径 C（服务端权威 + localStorage 降级为缓存）＋ 粒度 B ＋ 来源只留内部（不加 UI 徽标）。
- **Phase 1（PR #73）**：`vocab_cards` 加 `source` + FSRS-6 列；修 `init_db` 建索引次序 bug。
- **Phase 2（PR #74）**：B1 懒物化 —— `source` 在词条进池时按 `lexicon.primary_source` 落定。
- **本阶段架构取向**：**不重写 4731 行工作台的存储层**，而是：
  1. 在既有 `wbsync`（`workbench.html:1370-1685`，快照 `{words,cards,log,wrong,settings}`）**之后追加服务端幂等投影**（deck → 统一池）；
  2. 工作台读路径改 **服务端优先 + localStorage 兜底**（`loadAll()` 是唯一读入口 ⇒ 改动收口）；
  3. 存量数据靠**读取期幂等投影**自愈（Backfill §2），不做一次性"搬运脚本"。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 服务端幂等投影 `project_wb_deck` [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/core/vocab_pool.py`
- Test: `tests/test_vocab_pool_projection.py`

**Interfaces:**
- Consumes: `delector.core.lexicon.primary_source(raw: str) -> str`（Phase 2）；`delector.core.database.db_conn()`；wb 快照 `{words:[{id,hw,pos,gloss,ipa,ex:[{de,zh}],custom:bool,...}], cards:{id:{s,d,due,last,reps,lapses}}}`
- Produces: `project_wb_deck(conn: sqlite3.Connection, payload: dict) -> {"inserted": int, "updated": int, "unchanged": int, "skipped": int}`（幂等；单事务由调用方控制）

**范围闸（2026-09-29 修订 · 用户拍板）**：只投影「**已学**（`cards[String(id)].reps > 0`）」或「**自建**（`word.custom === true`）」的词条；**自动加载的 A1/A2/B1 种子词（非 custom 且未学）MUST NOT 入池**——否则 `GET /api/cards`/`stats`（尚无 source 过滤）会被几百~几千条种子词淹没。被排除的计入 `skipped`。

**Injected Instincts:**
- [ ] `[Instinct: Content-Dedup]`: **按 `lemma` 去重**（`NOT EXISTS`/UNIQUE），**禁止**计数对账（Migration-Idempotency §1）。
- [ ] `[Instinct: Fill-Empty-Only]`: 已存在行**只补空**、不覆盖；**绝不触碰**用户手编 `definition_zh`/进度列（Backfill §4/§5）。
- [ ] `[Instinct: No-Cross-Semantics]`: `gloss`/`ex[].de` **不写** `example_zh`/官方语义槽；`reps` **不写** `repetition_count`（FSRS→仅 `fsrs_*`）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `project_wb_deck`.
> Mode: AFK | Role: TDD Builder
> Goal: 把 wb 快照的 words/cards **幂等投影**进 `vocab_cards`（按 lemma 去重、只补空、不碰用户数据、FSRS→`fsrs_*`）。
> Target Files: Create `delector/core/vocab_pool.py`; Test `tests/test_vocab_pool_projection.py`.
> TDD Steps: 1) 写失败测试（首投影 inserted=N/二次 unchanged=N 且零写盘；已存在行不被覆盖；`reps` 未写进 `repetition_count`）(RED) 2) 跑并确认失败 3) 实现最小投影 (GREEN) 4) 全绿 5) guard clause 扁平化 6) 贴原始执行回执 7) 原子 commit。
> Return: Summary + MANDATORY Physical Execution Receipt（exit code + pytest 统计行）。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 幂等（二次 `unchanged` 且无 UPDATE）/ 只补空 / 不混语义 / 不碰用户列
- [ ] **Step 2: 跑测试确认按预期失败**
- [ ] **Step 3: 实现 `project_wb_deck`（GREEN）** —— 单函数、只读 payload、不 commit（事务交调用方）
- [ ] **Step 4: 全绿**
- [ ] **Step 5: Refactor**（guard clauses ≤2 层）
- [ ] **Step 6: 物理证据门**（命令 + exit 0 + 通过数 + `git diff --stat`）
- [ ] **Step 7: 原子 commit**

---

### Task 2: 接线到 `PUT /api/wb/state`（单事务） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py::save_wb_state`（**实定义处**；`routes/main.py::wb_put_state` 仅调用、不改）—— 写镜像 blob 与池投影同事务
- Test: `tests/test_server.py`（新增：`PUT /api/wb/state` 后统一池出现对应行；重复 PUT 无新增；投影失败整体回滚）

**Interfaces:**
- Consumes: `project_wb_deck`（Task 1）
- Produces: `PUT /api/wb/state` 语义扩展 —— 写镜像 blob **同一事务内**完成统一池投影；失败整体回滚（Migration-Idempotency §2）

**Injected Instincts:**
- [ ] `[Instinct: Atomic Migration]`: 投影与 blob 写在**同一事务**；异常整体回滚，无"半迁"。
- [ ] `[Instinct: Three-Phase Regression]`: 回归 MUST 覆盖「投影 → 又产生新写入 → 再 PUT」三段时序（§3）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 把 `project_wb_deck` 接进 `PUT /api/wb/state` 的单事务。
> Mode: AFK | Role: TDD Builder
> Injected Instincts: 单事务原子；三段时序回归。
> TDD Steps: 1) 写失败测试（PUT 后统一池有行；重复 PUT 不新增；新写入后再 PUT 仍正确）(RED) …
> Return: Summary + MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 含三段时序
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 接线（GREEN）**，单事务
- [ ] **Step 4: 全绿**
- [ ] **Step 5: Refactor**
- [ ] **Step 6: 物理证据门**
- [ ] **Step 7: 原子 commit**

---

### Task 3: 工作台读路径 —— 服务端优先 + localStorage 兜底 [**已废弃 · 2026-09-29 用户决定跳过**]

> **跳过理由**：T2 已把 deck 投影进统一池 ⇒ 服务端**事实上**已是权威。而本任务要把 `loadAll()` 从「本地为准」翻成「服务端优先」，与 `wbsync` 明写的 *"本地为准（local-first）：localStorage/IDB 的键永不因同步被删改，远端只是最近镜像"* 正面冲突，且动的是**离线保证**，收益可疑。**不改工作台读路径。**（下方原始任务描述保留作记录，不执行。）

### ~~Task 3（原描述）: 工作台读路径 —— 服务端优先 + localStorage 兜底~~ [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（仅 `loadAll()`，`:1174-1200`；**不改** 5 个 `saveXxx` 的写语义）
- Modify: `tools/wb_*.mjs` 探针（新增"离线兜底"场景）
- Test: `tests/test_german_workbench.py` / `tests/test_a1_workbench_source.py`

**Interfaces:**
- Consumes: 既有 `wbsync.pull()`（`/api/wb/state`）；既有 `loadAll()` 读 localStorage
- Produces: `loadAll()` 语义 —— **服务端可达**时以服务端快照为准（缺失字段按 Backfill 只补空），**不可达**（`file://`/断网）时逐字退回现状

**Injected Instincts:**
- [ ] `[Instinct: Capability-Gate]`: 闸门 MUST 按**能力**（此刻上游是否可达）判定，MUST NOT 按历史状态标记（Backfill §3）。
- [ ] `[Instinct: Offline-Intact]`: `file://` / 断网用例 MUST 仍全绿（ADR-0016 守卫 #2）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 工作台 `loadAll()` 服务端优先 + 离线兜底。
> Mode: AFK | Role: TDD Builder
> Target Files: Modify `static/german/workbench.html`（**只改 `loadAll`**）；Test 既有 workbench 探针族。
> Injected Instincts: 能力闸门；离线用例全绿。
> TDD Steps: 1) 先加"断网仍读本地"探针场景(RED 若实现破坏离线) 2) … 3) 改 `loadAll` (GREEN) …
> Return: Summary + MANDATORY Physical Execution Receipt（含 `node tools/*.mjs` 全绿）。"

**Step Breakdown:**
- [ ] **Step 1: 加探针场景（RED）** —— 断网读本地 + 在线读服务端
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 改 `loadAll()`（GREEN）**
- [ ] **Step 4: 全绿（含全部 `wb_*.mjs`）**
- [ ] **Step 5: Refactor**
- [ ] **Step 6: 物理证据门**
- [ ] **Step 7: 原子 commit**

---

### Task 4: 首次运行的一次性投影 + 对账 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/vocab_pool.py`（新增对账辅助）
- Test: `tests/test_vocab_pool_projection.py`

**Interfaces:**
- Consumes: `project_wb_deck`
- Produces: `reconcile_report(conn, payload) -> {"deck_words": int, "pool_player": int, "missing": [...], "extra": [...]}`（**只读**，量化缺口；供日志/守卫断言）

**Injected Instincts:**
- [ ] `[Instinct: Content-Dedup]`: 对账按 `lemma` 集合求交/差，**不用计数相等**（§1）。
- [ ] `[Instinct: Honest-Null]`: 上游查不到 MUST 留空，MUST NOT 编造兜底（Backfill §6）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: wb deck ↔ 统一池的**只读对账**。
> Mode: AFK | Role: TDD Builder
> Injected Instincts: 按 lemma 集合对账（非计数）；诚实留空。
> TDD Steps: 1) 写失败测试（造缺口 → `missing` 命中）(RED) … 3) 实现 (GREEN) …
> Return: Summary + MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现（GREEN）**
- [ ] **Step 4: 全绿**
- [ ] **Step 5: Refactor**
- [ ] **Step 6: 物理证据门**
- [ ] **Step 7: 原子 commit**

---

### Task 5: 还原路径补迁移（restore-then-migrate） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（`/api/backup/restore`）/ `delector/core/vocab_pool.py`
- Test: `tests/test_server.py`（备份还原后统一池与 deck 一致；失败整体回滚）

**Interfaces:**
- Consumes: `_db_snapshot_guard`（PR #69 的 backup-API 快照守卫）
- Produces: restore 成功后**同快照守卫内**补跑幂等投影；失败与 restore 一起回滚（Migration-Idempotency §4）

**Injected Instincts:**
- [ ] `[Instinct: Restore-Then-Migrate]`: 旧备份（只有旧数据）还原后 MUST 补迁移，否则"还原成功但读新表为空"的**静默数据丢失**（§4）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: restore 路径补迁移。
> Mode: AFK | Role: TDD Builder
> Injected Instincts: restore+migrate 同快照守卫、失败一起回滚。
> TDD Steps: 1) 写失败测试（旧备份还原后统一池补齐；注入失败 → 整体回滚）(RED) … 3) 实现 (GREEN) …
> Return: Summary + MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现（GREEN）**
- [ ] **Step 4: 全绿**
- [ ] **Step 5: Refactor**
- [ ] **Step 6: 物理证据门**
- [ ] **Step 7: 原子 commit**

---

### Task 6: 端到端验收点检 [Mode: HITL] [Role: Checker]

**Files:**
- Test: `tests/test_unified_pool_e2e.py`

**Interfaces:**
- Consumes: Task 1–5 全部产物
- Produces: 一份端到端断言集：`file://` 离线可用 / 在线服务端权威 / 迁移幂等（三段时序）/ 用户数据零覆盖 / `source` 正确

**Step Breakdown:**
- [ ] **Step 1: 写端到端用例（RED）**
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 修到全绿**
- [ ] **Step 4: 人工点检**（桌面 `file://` 直开 + 断网 + 覆盖安装后数据完整）
- [ ] **Step 5: 物理证据门**
- [ ] **Step 6: 原子 commit**

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A]**: `wb_state` 是**单行整份 JSON**（`database.py:330-336`）。投影进 `vocab_cards` 后，`/api/wb/state` blob 是否仍保留（双份真相）还是改为由统一池**反向生成**？（待 Task 3 落地后按"读路径是否还需要 blob"决定；ADR-0016 未定。）
- **[Unknown B]**: 工作台 FSRS-6 的 `due`/`last` 两字段在 Phase 1 未建列（只建了 `s/d/lapses`）。是否复用 `vocab_cards.due_date` 或另加列？（待 Task 1 投影时按"是否无损"决定；若需无损则补 `fsrs_due`/`fsrs_last`。）
- **[Unknown C]**: 语法卡（`grammar_cards`）是否并入本阶段（工作台无语法卡概念；ADR-0016 P2 待定）。

---

## 🚫 Out of Scope

- **Phase 4**：收敛消费面 —— i+1 覆盖率、`/api/progress/stats`、Anki 导出、`_BACKUP_TABLES` 纳入 `wb_state`/统一池；视图按 `source` 过滤。
- 来源徽标等 **UI 呈现**（ADR-0016 附带 Q 已定：来源只留内部）。
- 修改 `lexicon` / 参考词表**来源分层**（ADR-0012 不动）。
- Android/Chaquopy 打包面变更。
