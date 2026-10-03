# 排名缓存正确性 + 卡片计数端点 Implementation Plan

> **Goal**: ① 修 `_RANK_CACHE` 在 >256 篇材料时的**命中率塌陷**与并发下的 `RuntimeError`（静默丢材料）；② 给 `refreshCardCounters` 一个只数个数的轻量端点，消灭写路径上 7 次全表 `SELECT *`。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL) · 原生 ES Modules 前端
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（P1「`_RANK_CACHE` 悬崖 + `min()` 迭代竞争」、「`refreshCardCounters` 计数端点」）
> **Global Constraints**:
> - **Task 2 本计划只动后端**。前端 `static/js/reader.js` 的 1 行 URL 切换会改动静态资产面 ⇒ 触发项目红线「必须发版 + Android 覆盖安装」，**拆为 HITL 后续任务**（见文末）。**本计划零 `static/` 改动 ⇒ 零发版。**
> - 门禁：`ruff check .` ＋ `mypy --strict delector tools` ＋ `mypy --follow-imports=skip tests` ＋ 分半 pytest ＋ 全 `tools/*.mjs` 探针。
> - 测试库隔离契约 C1–C4；用 `tests/db_cleanup.py::remove_db_files` 语义（PR #78）。
> - 诚实留空 / 零静默吞错：并发竞态**必须**让测试红，不接受"偶发所以测不了"。

---

## 🏛️ Decisions So Far

- **根因（已取证，非推测）**：`_rank_source` 内 `now = time.monotonic()`（`syntax_hard.py:97`）**逐材料各取一次**，写入的 `expires` 因此**逐条递增**；而 `_list_article_ids()` 是 `ORDER BY id` **升序**（`:134`）⇒ 第 257 条写入时，最早写的那批 `expires` 最小 ⇒ 被 `min()` 淘汰（`:50`）⇒ 下一轮 sweep 从第 1 条就 miss。**这不是"插入一条淘汰一条"的问题**（先写后判，容量本身守得住），是**淘汰策略 × 访问模式**的组合。
- **锁不能解悬崖**（策略问题非竞态）；**动态上限会把悬崖换成内存随语料线性增长**（本地单用户 SQLite 更差）。⇒ 唯一同时解两者的手段是 **`source=all` 走聚合层缓存**：整榜一个 key，N 再大都不逐条淘汰。
- **锁仍要加**，但优先级从"必须"降为"应该"：`source=all` 加聚合缓存后，逐材料写入窗口大幅缩短，可 `source=all` 与单材料/详情路径仍并发写。
- **`refreshCardCounters` 真正热点不是初始加载**（Reviewer 独立核验）：`static/js/reader.js:713` 只要一个 `length` 角标却 `api("/api/cards")` 拉全量（`SELECT *` + 逐卡 FSRS 递推），且挂在 **7 个"每次存卡后"**的调用点上（`reader.js:617/664/700/1173`、`cards.js:1245`、`a1_hoeren.js:566`、`a1_cards.js:754`、`writer.js:936`）⇒ 存 N 张卡是 O(N²) 的写路径放大。
- **端点写法照既有范式**：`main.py:882-884` 已有"单扫条件聚合 `SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered`"，直接照抄，不新造写法。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: `_RANK_CACHE` 并发安全 + `source=all` 聚合层缓存 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/syntax_hard.py`（`_RANK_CACHE` 区域 `:36-56`；`_rank_source` `:92-100`；`source == "all"` 分支 `:168-192`）
- Test: `tests/test_syntax_hard_api.py`（既有 `test_rank_cache_bounded_eviction` 邻近处追加）

**Interfaces:**
- Consumes: `_rank_source(source, source_id)`（**签名与语义不变**）、`_list_article_ids()`、`_list_encounter_ids()`、`_put_rank_cache`（**保留**，供单材料路径用）
- Produces: `def _get_rank_cache(key: str) -> Optional[List[Dict[str, Any]]]` — 模块级 `threading.Lock` 保护下的读；`None` 表示 miss
- Produces: `def _put_rank_cache(key: str, expires: float, items: List[Dict[str, Any]]) -> None` — **同签名**，内部加锁；淘汰仍按 `min(expires)`（保持既有测试 `test_rank_cache_bounded_eviction` 通过）
- Produces: 聚合 key 常量 `_ALL_RANK_CACHE_KEY = "all"`；`source == "all"` 分支 MUST 改为**先查聚合 key**，miss 才逐材料 `_rank_source` + 排序 + **写聚合 key**
- Produces: 每次 sweep 结束后 **`_RANK_CACHE` 逐材料条目 MUST 被清空**（聚合层已覆盖它们，留着只会被 `min()` 淘汰时误伤）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Lock-Scope]`: 锁 MUST 覆盖"读-判-写"整段（`_get_rank_cache` 读、`_put_rank_cache` 的 min+pop），**MUST NOT** 只锁 `pop` 那一行（那正是竞态本身）。
- [ ] `[Instinct: No-Cross-Semantics]`: 聚合层 MUST 复用 `_rank_source` 的**逐材料异常隔离**（任一材料炸只丢该材料，`continue`），MUST NOT 因为聚合而放宽成"整体失败"。
- [ ] `[Instinct: Cache-Key-Scope]`: 聚合 key MUST 与"语言/筛选"无关（当前 `source=all` 无其它筛选参数）；若将来加筛选，MUST 进 key。
- [ ] `[Instinct: No-Silent-Drop]`: 并发竞态 MUST 由测试钉住（多线程 hammer），**不接受** `try/except: continue` 式的掩盖。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `_RANK_CACHE` 并发安全 + `source=all` 聚合层缓存。
> Mode: AFK | Role: TDD Builder
> Goal: (a) 材料数 > 256 时命中率从 0% 恢复到近 100%；(b) 并发下不再出现 `RuntimeError: dictionary changed size during iteration`（该异常被 `except Exception: continue` 吞掉 ⇒ 材料静默从难度榜消失）。
> Target Files: Modify `delector/routes/syntax_hard.py`；Test `tests/test_syntax_hard_api.py`。
> Interfaces: 新增 `_get_rank_cache(key)`（锁保护读，miss 返回 `None`）；`_put_rank_cache(key, expires, items)` **签名不变**、内部加锁；新增 `_ALL_RANK_CACHE_KEY = "all"`；`source == "all"` 分支改为整榜一个聚合 key。
> Injected Instincts: Lock-Scope（锁覆盖读-判-写整段，不只锁 pop）/ No-Cross-Semantics（保留逐材料异常隔离）/ Cache-Key-Scope / No-Silent-Drop。
> TDD Steps:
> 1. 写 3 个失败用例（RED）：
>    - **① 悬崖（核心，修复前必红）**：monkeypatch `_rank_source` 返回固定 items + `_list_article_ids`/`_list_encounter_ids` 返回 300 个假 id ⇒ 连续调两次聚合路径 ⇒ 断言**第二次 `_rank_source` 调用次数为 0**（整榜命中）。修复前第二次会再次调 300 次（因为每条都被上一轮淘汰）。
>    - **② 并发（修复前必红或不稳定重现，须如实回报）**：`threading.Barrier` 起 16 线程，每线程循环 200 次 `_put_rank_cache` 写不同 key ⇒ 断言**无任何 `RuntimeError`** 且最终 `len(_RANK_CACHE) <= _RANK_CACHE_MAX_ENTRIES`。
>    - **③ 逐材料条目不残留**：跑完聚合路径后断言 `len(_RANK_CACHE) == 1`（只剩聚合 key）。
> 2. 跑 `python -m pytest tests/test_syntax_hard_api.py -q -k \"rank_cache\"`，贴真实失败输出。
> 3. 实现（GREEN）。
> 4. 复跑；并确认既有 `test_rank_cache_bounded_eviction` **仍绿**（淘汰语义未变）。
> 5. 变异验证（`cp` 备份还原，禁 `git checkout --`）：① 去掉聚合缓存（恢复逐条写）⇒ ① 红；② 锁只包 `pop` 不包读-判-写 ⇒ ② 红或如实说明为何在本机不可复现；③ 把 sweep 后的逐材料清理去掉 ⇒ ③ 红。
> 6. 门禁：`python -m pytest tests/test_syntax_hard_api.py -q` ＋ `ruff` ＋ 两道 mypy ＋ `node tools/*.mjs` 探针全跑。
> Return: Summary + 物理执行回执（原始 exit code、通过数、`git diff --stat`）。"

**Step Breakdown:**
- [ ] **Step 1: 写 3 个失败用例（RED）**
- [ ] **Step 2: 跑测试并确认失败原因正确**
- [ ] **Step 3: 实现锁 + 聚合层（GREEN）**
- [ ] **Step 4: 复跑全绿 + 既有淘汰测试不回归**
- [ ] **Step 5: 变异验证三条**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

### Task 2: 卡片计数端点（后端 only） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（紧邻 `get_cards`（`:690-709`）之后新增端点）
- Test: `tests/test_server.py`（沿用既有 `client` / 库隔离夹具）

**Interfaces:**
- Consumes: `db_conn()`、`vocab_cards` / `grammar_cards`（**只读**）
- Produces: `GET /api/cards/counts` → `Dict[str, int]` 形如
  ```python
  {"vocab_total": int, "vocab_mastered": int,
   "grammar_total": int, "grammar_mastered": int, "total": int}
  ```
  实现 MUST 用**单扫条件聚合**（照 `main.py:882-884` 既有写法：`SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM <表>`），每表 1 次查询、共 2 次；**MUST NOT** `SELECT *`、**MUST NOT** 跑 `get_fsrs_next_intervals`
- MUST NOT 改动 `GET /api/cards` 的响应结构（`cards.js:79-83` 全量消费它）
- MUST NOT 加本机闸（与 `GET /api/cards` 同级：局域网只读、非敏感）

**Injected Instincts:**
- [ ] `[Instinct: Contract-Frozen]`: `GET /api/cards` 与 `GET /api/cards/due` 的响应键**逐字不变**（`cards.js:79-83` / `:110` 消费）。
- [ ] `[Instinct: Reuse-Ladder]`: 计数 SQL MUST 照抄 `get_progress_stats` 的既有单扫写法，**禁**新造第二份聚合风格。
- [ ] `[Instinct: Honest-Null]`: 空表时 `SUM(mastered = 1)` 返回 `NULL` ⇒ 端点 MUST 返回 `0` 而非 `null`（`vc["mastered"] or 0` 的既有处理）。
- [ ] `[Instinct: Read-Only]`: 纯 GET，MUST NOT 触发任何写或迁移。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: `GET /api/cards/counts` 计数端点（后端 only，零 `static/` 改动）。
> Mode: AFK | Role: TDD Builder
> Goal: 给前端角标提供一个 O(1)-shape 的轻量端点，取代「为了拿一个 `length` 而 `SELECT *` 全表 + 逐卡 FSRS 递推」。
> Target Files: Modify `delector/routes/main.py`（`get_cards` 之后新增）；Test `tests/test_server.py`。
> Interfaces: Produces `GET /api/cards/counts` → `{vocab_total, vocab_mastered, grammar_total, grammar_mastered, total}`；实现用每表单扫条件聚合（共 2 次查询）。
> Injected Instincts: Contract-Frozen / Reuse-Ladder（照 `get_progress_stats:882-884` 既有写法）/ Honest-Null（`SUM` 空表返 `NULL` ⇒ 端点返 `0`）/ Read-Only。
> TDD Steps:
> 1. 写用例（RED）：① 空库 ⇒ 全部 `0`（**`mastered` 必须是 `0` 不是 `null`**，修复前端点不存在 ⇒ 404/红）；② 插 2 张 vocab（1 张 `mastered=1`）+ 1 张 grammar ⇒ 逐字段断言五个值；③ 断言该端点**不做 FSRS 递推**：monkeypatch `delector.routes.main.get_fsrs_next_intervals` 成抛异常的桩 ⇒ 请求计数端点 MUST 仍 200。
> 2. 跑 `python -m pytest tests/test_server.py -q -k counts`，贴真实失败输出。
> 3. 实现端点（GREEN）。
> 4. 复跑；并确认既有 `test_known_lemmas_*` / `test_due_cards_*` 等卡片类用例全绿（契约未破）。
> 5. 变异验证：① 端点改成 `SELECT *` 再取 `len` ⇒ 用例③必红；② 去掉 `or 0` ⇒ 用例①必红（`None` 而非 `0`）。
> 6. 门禁：`python -m pytest tests/test_server.py -q` ＋ `ruff` ＋ 两道 mypy ＋ 探针。
> Return: Summary + 物理执行回执。"

**Step Breakdown:**
- [ ] **Step 1: 写失败用例（RED）**
- [ ] **Step 2: 确认红**
- [ ] **Step 3: 实现端点（GREEN）**
- [ ] **Step 4: 复跑 + 卡片类回归**
- [ ] **Step 5: 变异验证两条**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Fog 1] 前端切换（1 行，需发版）**：`static/js/reader.js:713` 把 `api("/api/cards")` 换成 `api("/api/cards/counts")`，失败时保留旧角标不报错。**改 `static/` ⇒ 触发「必须发版 + Android 覆盖安装」**，故不在本计划内。须与后续其它 `static/` 改动**打包同一次发版**。
- **[Fog 2] `/api/cards` 自身的排序右段无索引**：`ORDER BY mastered ASC, wrong_count DESC, id DESC` 中 `wrong_count`/`id` 无索引 ⇒ 走临时 B-tree（EXPLAIN 实测 20k 行 93.8 ms）。修法 = 补 `idx_vocab_list(mastered, wrong_count DESC, id DESC)` / `idx_grammar_list`。**但先量收益**：那 93.8 ms 里有多少是 filesort、多少是回表 + `dict(r)` 物化 19 列 + 2 万次 `get_fsrs_next_intervals`，**未知** ⇒ 不盲目加索引。
- **[Fog 3] keyset 分页**：真正的解法是把返回行数从 O(N) 降到 O(page)。**影响面大**：`cards.js:139-148` 客户端 segment 过滤 + `:197-199` `deckIndex` 依赖全量数组算 `total` + `exam_catalog.py:84` 共享 `api_prefix`（跨 3 个前端模块）。等 Fog 2 量化后再决定。
- **[Fog 4] `known-lemmas` 与 counts 端点是否合并**：两者都是"池的轻量投影"。若将来要按 `source` 拆口径（ADR-0016 Phase 4），合并会更省一次往返。**当前分开**（口径不同、演进方向不同），合并属提前设计。

---

## 🚫 Out of Scope

- **不改 `source=all` 的排序契约**（跨材料合并后按 `score` 降序 —— 难度榜契约，见 `:189-190`）。
- **不实现真正的 LRU**（`OrderedDict.move_to_end`）：现有"最早过期优先"在有 TTL 的场景下语义可接受，且既有测试钉住了它。改 LRU 属行为变更，需单独立项。
- **不动 `_CACHE_TTL_SEC = 300.0`**（材料级 TTL 是产品选择：`_rank_source` 懒读正文已让冷路径够快，2026-09-28 审计已推翻过"加聚合缓存"的收益假设，本任务只修**正确性**与**悬崖**，不重开 TTL 讨论）。
- **不做端点鉴权变更**（`/api/cards/counts` 与 `GET /api/cards` 同级：局域网只读）。
