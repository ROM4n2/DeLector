# 🏛️ Multi-Expert Swarm Audit Report: DeLector（current master 全量）

**Date**: 2026-10-03
**Target Scope**: 整个 master（`e61a409`）——Python/FastAPI 后端（`delector/`）+ 原生 ES 前端 PWA（`static/`）+ Go agent（`agent/`）+ Android Chaquopy 打包面 + Docker 部署面 + 测试基建 + 文档/记忆约定
**Seats Dispatched（6/6）**: `product-ux` · `frontend-architect` · `dba-optimizer` · `perf-profiler` · `code-reviewer` · `sre-resilience`
**Seats Skipped**: 无（目标含全部制品类）。两个**可选** recon 席位（`codebase-researcher` / `codegraph-explorer`）未派发——目标范围由编排者先行 recon 明确（结构 + 自上次审计 `6cd7709` 以来的增量）。
**Adversarial Verification**: 3 个独立怀疑者复核了 **2 条 P0 + 6 条最关键 P1**；每条给出 CONFIRMED / PLAUSIBLE / PARTIALLY，并**修正了 seat 的措辞与根因归属**（见各条「怀疑者修正」）
**Findings**: **31** 条（3 P0 / 14 P1 / 14 P2），由 6 个 seat 的 **58** 条原始发现 collapse 而来（31 < 58 ✓）
**基线对照**: 上次全量审计 `docs/reviews/2026-09-28-swarm-audit-master.md`（基线 `6cd7709`）的 6 条 P1 **已全部处理**：Docker 入口(#69) · WAL(#69) · Android 契约守卫(#70) · 长难句聚合(#71) · i+1 词池隔离(#72/#75/#77) · 双词库数据打通(#72/#75)

---

## 🚨 Critical Findings（P0 / P1）

### P0

- **[dba + sre] [CONFIRMED] 存量 Docker 用户升级后读到空库——无任何自检或迁移闸**
  `docker-compose.yml:11-12,16` · `delector/core/database.py:35,46`
  - 卷从单文件 `./delector.db:/app/delector.db` 改为目录 `./data:/app/data`，并**无条件**设 `DELECTOR_DATA_DIR=/app/data`。`get_db_path()` 优先级 = 显式入参 > `DATABASE_PATH` > `DELECTOR_DATA_DIR/delector.db` > `_REPO_ROOT/delector.db` ⇒ 容器内读 `/app/data/delector.db`，**旧库不再被挂载**。
  - `init_db()` 只建全新空 schema + 灌 4 篇预置文章（`server.py:343`）⇒ 用户看到**功能正常、数据全空**的应用。全仓搜 `legacy|搬移|旧库` **零命中**——无探测、无告警、无迁移。
  - *怀疑者修正*：**数据文件没被删除**（宿主机旧库原封不动），危害是"服务读空库 + 无提示 + 无文档"而非"数据蒸发"；且旧 compose 只挂主库（`progress.db` 一直在容器层、`compose down` 即丢）⇒ **新挂载对 progress 是改善**。`CHANGELOG.md` 搜 `docker|卷挂载|data 目录` **零命中** ⇒ 破坏性部署变更无任何用户可见迁移说明。
  - *Impact*: 不可自愈的用户数据"看起来丢了"；无 CI 闸（`tests/test_ci_hardening.py:234` 的 Dockerfile 守卫只校验 CMD 入口模块存在）。
  - *Verification Status*: **CONFIRMED** via skeptic read（compose 差异 / 优先级链 / 迁移逻辑缺失 / `COPY . .` 行为逐条核验）；仅"存量用户规模"无遥测。

- **[sre] [UNVERIFIED] 无 `.dockerignore` ⇒ 开发者的 `.env` 明文密钥被烤进镜像层并被容器真的加载**
  `Dockerfile:14`（`COPY . .`）· 仓库根**不存在 `.dockerignore`**（全仓 0 命中）
  - `.gitignore:14` 忽略 `.env`，但 `docker build` 复制**工作树**而非 git tree ⇒ 本地 `.env`（含 `DEEPSEEK_API_KEY`）进 `/app/.env`；`delector/server.py:18-42` 的 `load_env()` 显式读 `os.getcwd()/.env`，WORKDIR 正是 `/app` ⇒ **容器启动时真会把该 key 载入 `os.environ`**，并被 `get_setting()` 的 env 兜底（`database.py:457`）实际使用。
  - 同一原因下 `*.db` 也进镜像 ⇒ `/app/delector.db` 成为躺在镜像层里的孤儿用户数据。
  - *Impact*: 密钥进入镜像层 ⇒ `docker history` / 推 registry / 分发任一环节泄露。
  - *Verification Status*: **UNVERIFIED**（未实跑 `docker build`；依赖"build 使用工作树"这一标准行为）。按 P0 定义（secret leak）定级，触发前提是"本地有 `.env` 且执行 `--build`"。

- **[product-ux] [CONFIRMED] 同一个词被两台互不知情的排程引擎调度，且卡面对用户说谎**
  `delector/core/vocab_pool.py:61-68,155-168` · `delector/routes/main.py:1698-1722` · `static/js/cards.js:284`
  - 投影**不写 `due_date`**（`_FILLABLE_COLUMNS` 与 INSERT 列清单均无它；DDL `database.py:245` 无 DEFAULT ⇒ 必为 NULL）。
  - `GET /api/cards/due` 谓词 `mastered = 0 AND (due_date IS NULL OR due_date <= ?)` ⇒ 投影词（`mastered` DEFAULT 0）**全部落进「今日到期」**；端点无 `_require_localhost`、无 source 过滤、无上限。
  - 卡面 `cards.js:284`：`card.due_date ? "⏳ 到期…" : "⏳ 待复习"` + `${correct_count||0} 正 / ${wrong_count||0} 误` ⇒ `fsrs_s=12.3` 的行照样显示「⏳ 待复习 · 0 正 / 0 误」。
  - 卡盒复习只写 DSR 列（`main.py:1665-1673`），**不回写**工作台 FSRS；全仓无任何从 `vocab_cards` 回写工作台的代码 ⇒ 同一词两套到期日、两套进度、两界面互不可见。
  - *减记项*：计划已登记为未决语义缺口（`docs/plans/archive/2026-09-29-...md:229` *Unknown B*），且词条内容正确、可正常复习。
  - *Verification Status*: **CONFIRMED**——5 条反驳尝试全部落空（投影不写 due_date 确证 / due 端点不排除 NULL 确证 / 卡面不读 `fsrs_s` 确证 / 无任何兜底过滤确证 / 每次 `PUT /api/wb/state` 都触发确证）。

### P1

- **[frontend] [CONFIRMED] `openText` 无任何重入守卫 ⇒ 点 A 读到 B，且两个 id 都被标记已读**
  `static/js/encounter.js:521-545` · `:464-482`（`renderReaderShell` 整体覆写 `rd.innerHTML`，无"已渲染就 return"早退）· `:535`（`markRead`）
  - 零守卫：全文件搜 `AbortController|_openToken|_seq|dataset.renderedFor` **零命中**；`_detailOpen`（`:38`）在 `openText` 内**根本没被读**。请求在途期间列表卡片完全可点。
  - 本轮新增的 `await Promise.all([resolveDeck(), fetchKnownLemmas()])`（`:496`）把窗口从"1 次 RTT"拉长到"**3 次 RTT + 1 次 spaCy 禁缓存全量标注**"（`routes/encounter.py:148-169` docstring 自陈"P0 直跑、禁缓存"）⇒ 窗口是**秒级**。
  - 加重项：catch 分支（`:539-542`）同样**无条件覆写** `rd.innerHTML` ⇒ A 的失败提示能盖掉 B 的成功正文。
  - `markRead` 幂等写盘且**不检查"是不是用户最后点的那个"** ⇒ B 被静默标记已读 → 被 `pickUnread` 永久剔出 i+1 推荐。
  - *Verification Status*: **CONFIRMED**（每个技术前提逐条验证为真，未找到兜底；并主动伪证了"渲染失败也误标已读"这一子主张）。

- **[code-reviewer] [CONFIRMED，根因需重写] `known-lemmas` 漏计「`reps>0` 但缺 `s`」的卡；其 docstring 把"当前恰好如此"写成了"恒如此"**
  `delector/routes/main.py:719-725` · `delector/core/vocab_pool.py:92-99,141-143,213-222`
  - `_desired_fields` 用 `_as_float(card.get("s"))`，缺 `s` ⇒ 落库 `NULL`；范围闸只要求 `custom is True` 或 `reps > 0` ⇒ 该行入池但 `NULL > 0` 非 true ⇒ **i+1 覆盖率漏计这个已学词**。
  - `main.py:722-725` 的"⇒ 恒 `s ≥ 0.001` ⇒ **故等价于** `reps>0`"只对**工作台自造卡**成立（穷举 `S.cards[...] =` 的 13 处写入点，`fsrsReview` 与字面量恒含 `s`）。
  - **怀疑者推翻的部分**：seat 点名的"LAN 合并搬来 SM-2 老卡"**路径不成立**——本仓工作台自 v4.6.0 引入即 FSRS-6，从无老卡生产者；手动短码 LAN 面板已被 `lanDisableLegacyPanel()` 全部 `disabled` 且端点强制 `X-WB-Key`（点击必 403）。真实可达路径是三条**零校验**入口：`applyOverwrite`（`workbench.html:4400`，`S.cards = data.cards || {}`，而导入文件是用户可见的正式功能）、`PUT /api/wb/state`（`main.py:1484`，payload 裸 `Dict` 零形状校验）、`loadAll`（裸读 localStorage）。
  - **另一处推翻**：`test_vocab_pool_projection.py:325` **恰恰用无 `s` 的卡并断言入池** ⇒ 测试没绕开边界，而是**把该行为钉成了契约**；端到端（投影 → `known-lemmas`）这一格**完全为空**。
  - *定性*：**防御缺失 + 契约文档说谎**，不是"正常用户流的活 bug"。
  - *修法铁律*：❌ 不得用"`reps>0` 就补 `fsrs_s=1.0`"糊——那是编造 FSRS 状态（`s` 决定间隔，且此后 `fsrs_s>0` 变成永久说谎的已知标记），违反 FSRS≠DSR。方向是**收敛范围闸 + 降级文档措辞 + 写入侧补形状校验**。
  - *Verification Status*: **CONFIRMED**（缺陷真实）+ seat 的触发路径与根因归属被修正。

- **[dba + perf] [CONFIRMED] `_pool_index` 整表扫主导 `save_wb_state`（每次背词复习都付）**
  `delector/core/vocab_pool.py:239,320` · `delector/core/database.py:534-564`
  - 每次调用无条件 `SELECT lemma, <7 列> FROM vocab_cards` 并在 Python 侧逐行 `lemma_key` 归一。**实测线性**：`project_wb_deck(M=200)` ≈ `_pool_index` 本身 ⇒ 逐词 insert/update 是免费的，成本 100% 在开头的全表扫。
  - 端到端 `save_wb_state`（perf 实测，池 1k/10k/50k）⇒ **4.9 / 27.0 / 154.5 ms**，`_pool_index` 占比 **42% / 87% / 97%**；`lemma_key` 占 `_pool_index` 约 **61%**（1.81 µs/次 × N）。
  - 可达性：`workbench.html:1362-1364` 确认 5 个 `saveXxx()` 末尾都挂 `wbsync.push()`（800ms 防抖）⇒ **每次复习都触发**。阈值约 1 万行池。
  - *修法红线*：**不可只加 `lemma` 索引**——`main.py:651` 原样写 `req.lemma`，池内确实混有 `Haus`/`haus` 两形态，`WHERE lemma='haus'` 会漏命中未归一行，**破坏 ADR-0015 §2.2 的按内容归一去重**（`vocab_pool.py:231-237` 的撞行规则正为此存在）。
  - *Verification Status*: **CONFIRMED**（数字来自 perf 实测；修法约束由 dba 独立指出并被采纳）。

- **[perf] [CONFIRMED，机制描述已修正] `_RANK_CACHE` 在 257 篇材料处出现容量悬崖 + 跨线程 `RuntimeError` 被静默吞掉**
  `delector/routes/syntax_hard.py:40-52`（淘汰）· `:134`（`ORDER BY id` 升序）· `:97`（`now` 逐条取）· `:175-188`（`source=all` 串行全量遍历）· `:178,186`（`except Exception: continue`）
  - 悬崖机制**不是** seat 说的"插入一条淘汰一条"（先写后判，容量本身守得住），而是**升序遍历 + 逐条递增的 `expires` + 按 `min(expires)` 淘汰**三者组合 ⇒ 第 257 条写入时弹出最早写的那批 ⇒ 第二轮 sweep 从第 1 条就重算（spaCy）→ 雪崩。实测命中率 256 篇 **90%** → 257 篇 **0%**。
  - `RuntimeError: dictionary changed size during iteration` 只能**跨线程**触发（同函数内 L49 写在 `min()` 之前、L52 `pop` 在其之后，单线程不自触发）。被 `except Exception: continue` 吞掉 ⇒ **该材料静默从难度榜消失**——本轮唯一带"结果错"而非只是"慢"的缺陷。
  - **锁解不了悬崖**（策略问题非竞态）；**动态上限会把悬崖换成内存随语料线性增长**（本地单用户 SQLite 更差）；**只有 `source=all` 走聚合层缓存能同时解两者**（锁仍需加，优先级降为"应该"）。
  - 现有测试 `tests/test_syntax_hard_api.py:431` 只断言"`m:0` 被弹"——**恰好是当前策略的"正确"行为**，修悬崖后仍会绿 ⇒ **无回归护栏**，需补"N=257 时第二轮 sweep 应命中"。
  - *Verification Status*: **CONFIRMED**（机制描述经怀疑者修正后仍成立）。

- **[perf] [PARTIALLY CONFIRMED] `get_spacy_nlp` 无锁懒加载 ⇒ 并发重复建模型；Android 上暴露更严重的"两个 NLP 口径"问题**
  `delector/nlp_engine/syntax_tree.py:48-66`（裸 `if _nlp_instance is None`，全文件无 `threading`）· 对照 `delector/nlp_engine/processor.py:26-68`（三级回退，专为 Chaquopy 无 `dist-info`）
  - TOCTOU 确证（`spacy.load` 内部大量 C 扩展/文件 IO 释放 GIL，窗口足够宽）。并发可达：`syntax_hard.py:146,156,202` + `main.py:1949`（均同步 `def` → anyio 线程池）。
  - *怀疑者修正*：① seat 把 `tools.py` 算作触发点**属虚高**（`async def` 且经 `processor.nlp`）；② "两份 pipeline 驻留"**在 Android 上不成立**——`syntax_tree` 缺 `module.load()` 回退 ⇒ `_nlp_instance` 恒 `None`、走纯 Python 降级。**真正更严重的问题是：同一进程内 `/api/syntax/*`（降级）与 `/api/tools/analyze`（真 spaCy）口径不一致。**
  - **加锁 ≠ 复用 `processor.nlp`**：后者会让 Android 上 `/api/syntax/*` 从降级变真 spaCy，输出形态与难度分口径随之改变 ⇒ **行为变更，须单独立项**。且 `processor.py:18` `from .syntax_tree import ...` ⇒ **不能顶层 import processor**，必须函数内延迟导入（循环方向已核实）。
  - *Verification Status*: **PARTIALLY CONFIRMED**——主体静态确证；8 线程 16 次 `spacy.load` / wall 3399ms / 内存量级等**数字未复核**。

- **[perf] [UNVERIFIED] spaCy 共享单例跨线程并发 ⇒ 并发吞吐塌到 0.18×**
  `delector/nlp_engine/processor.py:71,427`（模块级 `nlp` 单例）· 调用方 `delector/routes/main.py:205`（`asyncio.to_thread`）与线程池路由
  - perf 实测 k=4/8/16/40 吞吐加速比 **1.33× / 0.60× / 0.18× / 0.17×**；k=16 时单请求 14.75ms → **82.6ms**。`Language` 非线程安全 ⇒ **数据竞争**（可能产出错误 Doc），只是 Python 层未炸。
  - *Verification Status*: **UNVERIFIED**（仅 seat 自测，无对抗复核，数字未独立复现）。

- **[dba + perf + frontend] [CONFIRMED] `/api/cards` 无分页全量 `SELECT *`；真正热点是写路径上 7 个"每次存卡后"的计数调用**
  `delector/routes/main.py:690-709`（`SELECT * ... ORDER BY mastered ASC, wrong_count DESC, id DESC`，无 `LIMIT`）· 索引仅 `idx_vocab_srs(mastered, due_date)` / `idx_vocab_article(article_id)`
  - EXPLAIN（dba 实测 20k 行）：`SCAN ... USING INDEX idx_vocab_srs` + **`USE TEMP B-TREE FOR RIGHT PART OF ORDER BY`**，93.8ms；`SELECT *`（19 列）必然**回表 2 万次**。
  - **怀疑者挖出 seat 漏掉的真正热点**：`static/js/reader.js:713` `refreshCardCounters()` **只要一个 `length` 角标却拉全表**，且在 **7 个调用点**触发（`reader.js:617/664/700/1173`、`cards.js:1204`、`a1_hoeren.js:566`、`a1_cards.js:754`、`writer.js:936` + 每次页面加载 `main.js:1178`）⇒ **存 100 张卡 ⇒ O(N²) 的写路径放大**。
  - 怀疑者另指出 93.8ms 主因可能**不是 filesort**：`main.py:705-708` 对**每张卡**跑 `get_fsrs_next_intervals`（4 次 `_calc_fsrs_step` + 4 次 `datetime.now()`）⇒ 2 万卡 = **8 万次递推 + 8 万次 now()**，加 `dict(r)` 物化 19 列。
  - *修法优先级（怀疑者重排，采纳）*：**第 0 优先不是补索引也不是分页，而是给计数走独立端点**（复用 `main.py:850-853` 现成的单扫条件聚合，改 5 行、零契约破坏、直接消灭 7 个高频全表读）→ 第 1 补 `idx_vocab_list(mastered, wrong_count DESC, id DESC)` → **keyset 分页最后**（`cards.js:139-148` 客户端 segment 过滤 + `:197-199` `deckIndex` 依赖全量 + `exam_catalog.py:84` 共享 `api_prefix` 跨 3 个前端模块）。
  - *Verification Status*: **CONFIRMED**（4 项静态核验全过；93.8ms 与 EXPLAIN 形状为 dba 实测，耗时未独立复现）。

- **[frontend + dba] [CONFIRMED] `known-lemmas` 在 i+1 关键路径上被反复调用，且 OR 谓词无索引可走**
  `delector/routes/main.py:735-740` · `static/js/encounter.js:204-211,415-419,496`
  - EXPLAIN：`SCAN vocab_cards` + `USE TEMP B-TREE FOR DISTINCT`（dba 实测 20k 行 = 10.0ms）。OR 三支无法合并成单索引扫描；`repetition_count` / `fsrs_s` **均无索引**。
  - 且 `DISTINCT` **去重不掉任何东西**——`lemma` 列存原始大小写形态（`Haus` vs `haus` 共存）⇒ 临时 B-tree 白建。
  - 前端**无 in-flight 去重/缓存** ⇒ 同一次「进遇见区 → 读 N 篇」会话里被请求 **N+1 次**（同仓 `a1_cards.js:62-64` 的 `_examVocabLoadingPromises` 是现成范式）。
  - *诚实定级*：**当前规模不是问题**（真实池通常千行级，阈值约 5 万行才显性）；价值在"修法便宜 + 修掉 N+1 放大"。

- **[dba] [CONFIRMED] `exam_trials` 零索引（上次审计遗留，仍未修）**
  `delector/core/database.py:135-147` · `:1691-1702`（`get_exam_history`）· `:1732-1734`（`migrate_a1_records_to_exam_trials` 的 `COUNT(*)`，**每次进程启动**都跑）
  - EXPLAIN 实测 `sqlite_master` 中该表**无任何 index** ⇒ `WHERE level=? AND module=? ORDER BY id DESC` 全扫 + 排序，`LIMIT` 救不了。
  - *诚实定级*：只增表，正常用户 1000 行以下全扫 0.1ms 级；阈值约 1 万行。一条 DDL 即可让前缀等值 + `id` 递减天然有序。

- **[perf + sre] [CONFIRMED] Go agent 的 `Failures()` 无人消费 ⇒ Python 子进程死透后 agent 变成"僵尸"**
  `agent/internal/pythonsvc/supervisor.go:183`（定义）· `agent/internal/app/app.go:55-58`（接口只有 `Start`/`Stop`）· `:93-101`
  - 重启配额（5 次指数退避 500ms×2^n 封顶 8s）耗尽后 `supervise()` 干净 `return`，**agent 继续存活**、registry 照常收任务，全部打到已死的 `:8001` ⇒ 无日志、无退出码、无自愈。`Failures()` 全仓仅 `supervisor_test.go:348` 一处消费（测试内）。
  - *肯定*：supervisor 的退避/封顶/强杀本身扎实，缺的只是**错误出口**。
  - *Verification Status*: **CONFIRMED**（两轮审计都提过，仍未修）。

- **[sre] [CONFIRMED] `_db_snapshot_guard` 的**回滚失败**被 `except Exception: pass` 静默吞掉**
  `delector/core/database.py:1584-1591`
  - 还原中途失败（磁盘满/库被占）触发回滚；**回滚本身也失败**（同一块满盘）⇒ 异常被吞 ⇒ 原始异常上抛、用户收到 500，**以为"什么都没发生"，实际库已半还原**——正是该 guard 存在的理由（`:1568`）被静默打破。
  - *肯定*：快照写在 `tempfile.mkdtemp()`（系统 temp，**非 DATA_DIR**）⇒ DATA_DIR 满盘时快照仍能成功；`finally` 无条件 `rmtree`；「还原后补投影失败」的原子性**正确**（不吞异常 ⇒ 整体回滚，代价只是用户拿到不透明 500）。

- **[sre] [CONFIRMED] `/api/audio/tts` 无并发上限/速率限制，最坏单请求约 76 秒；`docker-compose.yml:8` 把 `0.0.0.0:8000` 全网暴露**
  `delector/routes/main.py:1121-1130` · `:1045`（edge_tts 无显式超时）· `delector/services/tts.py:313-316`（对**任意异常**重试一次，socket 30s ⇒ 最坏 60s）· `main.py:1067`（3 个 HTTP provider 各 6s ⇒ 合计最坏 ~76s）
  - 全仓搜 `Semaphore|Limiter|slowapi|ratelimit` → **0 命中**；`asyncio.to_thread` 用默认线程池（`min(32, cpu+4)`）⇒ 池满后**无界排队**而非拒绝。
  - *肯定*：输入侧防护到位（`MAX_TTS_TEXT_LEN=1000`、voice 白名单、rate 正则）；**出站超时全覆盖**（LLM 30/15/20/10/30s、SSRF 15s、TTS 兜底 6s）✅；**SSRF 防护质量高**（逐跳过闸、流式 2MB 双重拦截、5 跳封顶）✅；写面闸法正确（restore / cache clear / 删除类均走 `_require_localhost`）✅，但 `POST /api/ingest`（10 万字符上限）LAN 可达且无限流。

- **[frontend] [UNVERIFIED] 遇见区弹层无垂直视口夹取 ⇒ 手机上点每屏最后一行等于无反馈**
  `static/js/encounter.js:966-969`（`top = Math.round(rect.bottom + 6)`，只对 `left` 做了 `Math.min/max`）· `static/style.css:10553-10567`（`position: fixed`，无 `max-height`/`overflow`）
  - 手机竖屏（约 640px 可视高）读短文滚到最后一行，点该行 `.enc-unk` ⇒ `top ≈ 596`、弹层高 150–200px ⇒ **100% 落在屏幕外**，用户看不到任何反馈，像是点击无效。这是 `.enc-unk` **唯一的**交互入口，每屏可复现。

- **[frontend] [UNVERIFIED，危害已下调] 列表与详情的 known 池来源不同源 ⇒ 同一功能两个真相**
  `static/js/encounter.js:446`（列表：`buildKnownSet(loadDeck(...))`，**无服务端镜像兜底**）vs `:496`（详情：`resolveDeck()`，本机空时回落 `GET /api/wb/state`）
  - `GET /api/wb/state`（`main.py:1478-1480`）**无 key 校验**（对比 PUT 有 `verify_wb_key`），注释明说放行局域网。
  - 场景：清过站点数据 / 换浏览器 profile / 跨设备（桌面用过工作台）⇒ 列表 i+1 徽章"偏难 0%"、点进去"已背词覆盖 82%"。
  - *怀疑者修正*：两条路径**都** merge 了 `known-lemmas`，差异**只在工作台 deck 那一半**；归一口径两边一致（剥冠词+小写）**不会**造假矛盾 ⇒ 危害低于 seat 描述的极端形态，**定级下调**。
  - 测试盲区确认：`tests/test_encounter_ui_probes.py:210-235` 两条用例是**源码字符串切片断言**，只钉住"两处都调了 `mergeKnownLemmas`"，**测不到 deck 来源不同**；编排器 `resolveDeck`（含 `empty` 判据与兜底时序）**全仓零覆盖**。

- **[product-ux] [UNVERIFIED] 统一池打通后，用户的"删除"与"重置"对池完全无效；且工作台词被贴上假的 A1 标签**
  `delector/core/vocab_pool.py:279-283`（`existing is None` ⇒ 原样重建）· `static/js/cards.js:509-517`（`deleteCard` 只删一行、无墓碑）· `static/german/workbench.html:4490-4502`（两个重置只清 localStorage/IDB）· `static/js/cards.js:268` + `delector/routes/main.py:696,863-869`
  - KARTEI 删词 → 下一次工作台 `PUT /api/wb/state`（每次 FSRS 评分都触发）⇒ **原样重建**，还弹一个假成功 toast。
  - 工作台「重置进度」后：i+1 覆盖率**纹丝不动**、首页「掌握词汇」不动、KARTEI「待复习全量」不减——三个数字全部说谎。
  - 投影刻意不写 `cefr_level`（声明"读取期从 lexicon 派生"），但**读取期根本没有派生**（`main.py:696` 裸 `SELECT *`）⇒ B2 词在 KARTEI 永远显示 **A1 徽章**，并把工作台词全部计进首页欧标分布的 **A1 柱** ⇒ **给用户看的错误事实**。

- **[product-ux] [UNVERIFIED] KARTEI 里"我存的生词"与"工作台背过的词"无法分辨、无筛选；反馈与文案系统性偏差**
  `delector/routes/main.py:690-709`（`SELECT *` 无分页无 source 过滤）· `static/js/encounter.js:231`（`I1_HINT_GUIDE` 仍写"先在背词工作台背一些词"，而卡盒复习已同样计入覆盖率）· `static/js/cards.js:84-87,161-165`（`loadCards` 失败把缓存兜底成空数组 ⇒ **把网络故障说成"你还没有卡片"**；同文件 `:1086-1094` 已有正确写法，此处重演了被批评过的反模式）· `:367-369`（`submitCardReview` 失败只 `console.error`，用户看到卡片翻页但评分可能没存进去）· `main.py:852-857`（首页「掌握词汇斩获」= `SUM(mastered=1)`，对工作台主力用户**恒为 0**）· `encounter.js:518`（「词位」是内部术语，与工作台「已学习/已稳固」、统计页叫法三处不统一）
  - 上次审计 P1②「双词库心智」的**数据侧已闭合、认知侧仍完全开放**：全站零文案说明两个入口的关系。

---

## ⚠️ Improvements & Suggestions（P2，UNVERIFIED）

| 领域 | 发现 | 位置 |
|---|---|---|
| code-reviewer | **dead-green**：e2e `group5`（备份往返）缺 `COUNT(*)` 守卫，`_pool_rows()` 以 `lemma` 作字典键 ⇒ 同 lemma 重复行被折叠，"逐字保留"守护不住"无重复" | `tests/test_unified_pool_e2e.py:83-86,247-259` |
| code-reviewer | **结构上恒真**：`static/` 零改动守卫用 `merge-base HEAD origin/master` 作基座 ⇒ **在 master 上 base==HEAD、diff 恒空**，合并后永久零判别力却给人"有门禁"的错觉 | `tests/test_unified_pool_e2e.py:263-294` |
| code-reviewer | **去重没做完**：`db_cleanup.py` docstring 宣称终结静默吞异常，实际仍有 **6 文件 9 处** `except OSError: pass`；`test_goethe_a1.py` 那块多删 `-journal` 后缀，与 helper 的"三件套"定义不一致 | `tests/test_audit_regressions.py:167`、`test_corpus.py:138`、`test_goethe_a1{,_hoeren,_lesen,_writing}.py` |
| code-reviewer | 时序脆弱：helper 用例④ 靠「持锁 0.15s vs 重试点 0/0.1/0.2/0.3s，余量 ≥50ms」赌 Windows 调度；且把 `_RETRY_SLEEP_SECONDS` 这个实现常量钉成了契约（真正无争议的判别力在用例⑤） | `tests/test_db_cleanup_helper.py:112-139` |
| code-reviewer | **魔数下标三处孪生 + 注释撒谎**：`_READ_INDEX` 注释自称"避免手写魔数下标"，但 `_fill_updates` 手写 `existing[1..6]`、`existing[0]`、`int(value[0])` 仍在；列序重排会静默错位且**无测试会红** | `delector/core/vocab_pool.py:41-57,177-184,247,291` |
| code-reviewer + dba | **`source` 两个写入者口径分歧**（collapse）：`routes/main.py:642` 传 `req.lemma`（已归一）、`vocab_pool.py:140` 传 `str(hw)`（原始形态）；`primary_source` 对原始形态敏感（`Haus`→official、`Hause`/`zum Haus`→user）⇒ 同一屈折形态的词，**最终 `source` 取决于哪条路径先跑**，不可复现 | `main.py:642` vs `vocab_pool.py:140` |
| code-reviewer + perf | `reconcile_report` **无生产调用方**（collapse）：49 行 + 6 辅助 + 300 行测试。判定倾向保留（ADR-0016 §5 Guardrail 2 的验收工具），但**最差选择是现状**——应给真实入口（localhost-only 端点）或降级为 `tools/` CLI | `delector/core/vocab_pool.py:361-409` |
| code-reviewer | 注释矛盾且过时：`:1530-1531` 用"本项目 `get_db()` 只结束事务、不 close（句柄靠 GC）"论证 backup API 的必要性，而 44 处换成 `db_conn`（**确定性 close**）后该论证已失真 | `delector/core/database.py:1530-1531` vs `:472-479` |
| sre | **零健康检查端点**：`/api/tools/` 只枚举工具、不碰 DB，却被 Go agent 当健康探针 ⇒ 返回 200 **不代表数据库可用**；无 `HEALTHCHECK`、compose 无 `healthcheck` | `routes/tools.py:29`、`supervisor.go:39` |
| sre | `ci.yml` **无 `timeout-minutes`**：注释自陈"PR 反馈预期 < 8min"，但 runner 默认烧满 6 小时 | `.github/workflows/ci.yml:36-115` |
| sre | pin 纪律不一致：8 个包里**仅 2 个完全 pin**，其余下界浮动 ⇒ `Dockerfile:11` 的 `pip install -r` **不可复现**且无 `--require-hashes`；`edge-tts>=7.2.8` 风险最高（TTS 是 Android 静音问题历史高发区） | `requirements.txt:8-10` |
| sre | `.env.example` **漂移**：只有 1 行，实际支持 9 个键，`docker-compose.yml:16` 用到的 `DELECTOR_DATA_DIR` 未记载；且 `.gitignore:8` 的 `.env.*` **匹配 `.env.example`**，该文件一旦被删则 `git add` 静默失败 | `.env.example`、`.gitignore:8` |
| sre | 无结构化日志配置（搜 `basicConfig|dictConfig` → 0 命中）⇒ 只输出 WARNING+。**错误链规范很好**（全仓 `raise ... from` 到位，唯一违反者恰是上面那条回滚吞错） | `delector/server.py` |
| sre | TTS 在 `ssl.create_default_context()` 失败时退回 `_create_unverified_context()`（关证书校验），注释理由是 Android 证书路径 | `delector/services/tts.py:130-131` |
| sre | `GET /api/settings` 签名**无 `request: Request`** ⇒ 未挂 `_require_localhost`，LAN 可读（返回掩码 key）——设计边界模糊，建议复核 | `delector/routes/main.py:1270` |
| dba + perf | `/api/progress/stats` 对两张表做 **5 次全表扫**（perf 实测 10 万行 54ms）；`fetchKnownLemmas` 无缓存（已并入上方 P1） | `main.py:852-873` |
| frontend | 触摸目标过小（`.enc-unk` `padding:0`，相邻词间隙约 4–5px）；`showView` 无 generation counter（当前损害低，未来个性化写入会放大）；`encIdbOpen` 缓存 IDB 句柄且无 `onversionchange`（升版当天静默挂起）；覆盖率行不携带"来源/是否降级"信息 | `style.css:10529-10536`、`encounter.js:400-450,1029-1051,512-519` |
| frontend | 归一口径分裂：deck 路径 `stripGermanArticle().toLowerCase()` vs 池路径 `lemma_key()`（多剥 `(sich)`、空白折叠为 `-`）⇒ `(sich) anmelden` 这类词**池路径命中、deck 路径不命中**；现有测试只覆盖冠词+大小写，**多词/反身/连字符折叠零覆盖** | `deck-bridge.js:72-83` vs `lexicon_merge.py:94-109` |
| frontend | `annotate` 为空的降级守卫写在新增 `await` **之后** ⇒ 无 token 的短文白等两跳才退回渲染 | `encounter.js:498-501` |
| dba | 还原路径实为**三个独立事务**（主库 replace / progress replace / 补投影）跨两个物理文件，原子性来自外层 snapshot guard（**设计正确**），但单事务内 `DELETE+executemany` 持写锁到 commit ⇒ 池 >5k 行时并发的 `save_wb_state` 会撞 5s busy_timeout | `main.py:1568-1620` |
| dba | 存量行的 `source` 永远停在 `'user'`（迁移后非空 ⇒ 只补空策略永不升级）⇒ 将来若按 `source` 过滤会失真 | `vocab_pool.py:22`、`database.py:415-425` |

---

## 💡 Consensus Action Plan（按 ROI 排序）

1. **【P0·防不可自愈的"数据看起来丢了"】Docker 迁移闸 + `.dockerignore`**
   `docker-compose.yml` / `README.md:90` / `docs/agents/ops.md:38` / `CHANGELOG.md` 写明升级迁移步骤；`database.py` 启动自检：`DATA_DIR/delector.db` 不存在但**旧位置**存在且非空 ⇒ `logging.error`（含两个绝对路径 + 明确 `mv` 命令）并**拒绝建空库**（宁可 crash-loop 也不要静默空库——crash-loop 有日志、能被看见）；新增 `.dockerignore`（至少 `.git/`、`.env`、`.env.*`、`*.db`、`*.db-wal`、`*.db-shm`、`*.apk`、`*.jks`、`.cache/`、`__pycache__/`、`docs/`）；CI 加静态守卫断言 `.dockerignore` 存在且含 `.env` 与 `*.db`。

2. **【P0·止"同一词两套排程"】让 due 队列与卡面认得工作台来源**
   `GET /api/cards/due` 与 `GET /api/cards` 补一个可判定的来源标记（`fsrs_s IS NOT NULL`），**工作台来源且无 DSR 进度**的行不进「今日到期」；卡面把「⏳ 待复习 · 0 正/0 误」换成读 `fsrs_s` 的 FSRS 状态。**一次改动同时解掉 P0-3 与 P1"来源无法分辨"两半。**

3. **【P1·护栏可信度】`known-lemmas` 等价性文档 + 写入侧形状校验**
   修 `main.py:722-725` 的绝对化措辞；`applyOverwrite` / `wb_put_state` 对 `cards[*]` 做形状检查，缺 `s`/`d` 的卡拒收或标记（**唯一能真正堵住可达路径的地方**）；补端到端测试格（投影 → `known-lemmas`），并改掉 `test_vocab_pool_projection.py:325` 那条"把 bug 钉成契约"的断言（在 docstring 写明**为何旧断言是错的**）。❌ 禁止用"`reps>0` 就补 `fsrs_s=1.0`"糊。

4. **【P1·正确性止血】`_RANK_CACHE` 加锁 + `source=all` 走聚合层缓存**
   先加模块级 `Lock`（消除跨线程 `RuntimeError` 导致的**静默丢材料**——本轮唯一"结果错"的缺陷），再给 `source=all` 加聚合层缓存（解 257 悬崖）。**锁解不了悬崖，动态上限会把悬崖换成内存线性增长，两者都不要单独做**；必须补"N=257 时第二轮 sweep 应命中"的回归护栏。

5. **【P1·零成本高收益】计数端点 + 索引**
   `refreshCardCounters` 改打独立计数端点（复用 `main.py:850-853` 现成的单扫条件聚合，改 5 行）⇒ 消灭 7 个"每次存卡后"的全表 `SELECT *`（写路径 O(N²)）。**这一步 ROI 比补索引和分页都高一数量级**，且不动任何 SQL 契约。之后才补 `idx_vocab_list(mastered, wrong_count DESC, id DESC)`；**keyset 分页放最后**。顺带给 `exam_trials` 一条 DDL（`CREATE INDEX idx_exam_trials_lvl_mod ON exam_trials(level, module, id DESC)`）。

6. **【P1·消除竞态】`openText` 加请求代号 + 取消旧 in-flight**
   `static/js/core.js:api()` **已原生支持 `opts.signal`** ⇒ 零新依赖、约 10 行：递增 `_openSeq` + `_openCtrl.abort()`，两处 `if (seq !== _openSeq) return`（跨 RTT），空 annotate 守卫上移到 `await` 之前，`markRead` 只给真正上屏的那篇记；`showView` 复用同一 seq。

7. **【P1·可观测】agent 错误出口 + 回滚失败留痕 + TTS 并发闸 + 健康端点**
   `app.go` 的 `supervisor` 接口加 `Failures()`，`Run` 消费后**非零退出**让 `restart: unless-stopped` 接管；`database.py:1589-1590` 回滚失败改 `logging.error(..., exc_info=True)` 并打印快照目录路径（**回滚失败是 P0 级事件，必须留"库可能已损坏 + 快照在哪"的线索**）；`/api/audio/tts` 加 `asyncio.Semaphore(4~8)`，拿不到即 `HTTPException(429, ...)`；加真正探 DB 的健康端点；`ci.yml` 补 `timeout-minutes`。

8. **【P2·测试基建补账】** `group5` 补 `COUNT(*)` 护栏；`static/` 守卫改钉 Phase 3 起点 SHA（否则删掉比留着诚实）；清掉剩余 6 文件 9 处 `except OSError: pass` 并给 helper 补 `-journal` 后缀；`_fill_updates` 改用 `_READ_INDEX`（消掉 8 个魔数）并补"列序重排后行为不变"测试；helper 用例④ 改事件驱动。

9. **【P2·治理】** 结构化日志（`logging.config`）；`.env.example` 补齐 9 个键并修 `.gitignore:8` 对它的遮蔽；统一 `source` 写入口径（两处都走 `lemma_key`）；`reconcile_report` 给真实入口或降级为 `tools/` CLI；pin 纪律扩到 `edge-tts`/`uvicorn`；`lemma_key` 加 `functools.lru_cache`（perf 实测 2.11×）。

---

## ♻️ Reuse Ladder Check

- **启动自检 + `.dockerignore`（Action 1）**：stdlib `os.path` + `logging` 即可 ⇒ **Prefer reuse**，无新依赖。
- **due 来源标记（Action 2）**：复用**已存在的** `fsrs_s` 列，不加列、不加接口 ⇒ **Prefer reuse**。
- **计数端点（Action 5）**：`main.py:850-853` 已有同款单扫条件聚合 ⇒ 照抄该写法，**Prefer reuse**。
- **`openText` 取消（Action 6）**：`core.js:api()` 已实现 `signal` 合并 + 监听摘除 ⇒ **Prefer reuse（零新依赖）**。
- **`get_spacy_nlp` 加锁**：stdlib `threading.Lock` + double-check ⇒ **Prefer reuse**。**注意**：复用 `processor.nlp` 看似省钱，实为**行为变更**（Android 上从纯 Python 降级变真 spaCy），须单独立项。
- **`lemma_key` 加 `lru_cache`**：stdlib `functools` ⇒ **Prefer reuse**，纯函数、语义不变。
- **`exam_trials` 索引 / `idx_vocab_list`**：SQLite 内建 ⇒ 无新依赖。
- 其余 P2 多为"补索引 / 改文案 / 补测试"，**不引入新依赖**。

---

## ✅ 明确「不是问题」（附理由，避免过度优化）

- **WAL 写锁**（perf 实测 16 并发 writer 零 `database is locked`，p99 434ms）⇒ 非问题。
- **WAL checkpoint / `-wal` 增长**：`wal_autocheckpoint` 缺省 1000 页构成天然上限，且 `db_conn` 确定性 close ⇒ 无长连接悬挂。
- **backup API 取代 `copy2`**：机制正确（规避陈旧快照与 `disk I/O error`），实跑有效 ✅。
- **TTS 缓存目录扫描**：内容寻址，命中路径只 `os.path.exists`、**不 listdir** ⇒ 上次审计的"每次请求扫目录"在本版本**不成立**；`prune_audio_cache(max_files=300)` 有上限 ✅。
- **词库启动加载**：`delector.core.lexicon` 导入 0.039s / 4867 条，内存可忽略 ⇒ 无启动瓶颈（真正成本是 spaCy 首次加载）。
- **前端 `rankEntries`/`coverageOf` 随已知池增长**：perf 实测 knownSet 100 → 50000（500×），`rankEntries(200 篇×400 token)` 仅 1.42 → 3.49ms（`Set.has` O(1)）⇒ **本轮"已知池扩大"对 i+1 排序无算法级影响**，成本在**网络**（N+1 次 `known-lemmas`）而非 CPU。
- **`annotateWithDeck` 第三参向后兼容**：2 参调用多一次 Set 拷贝、元素一致，且有契约测试逐字断言 ✅。
- **前端监听器/定时器泄漏**：`ensurePullBound` 模块级一次、`ensurePopoverBound` 有幂等闸、`api()` 在 `finally` 清 timer 并摘 signal ⇒ 逐项核查无泄漏。
- **`file://` 直开时 `known-lemmas`**：立即 reject（不挂起、不白屏），被 catch 返回 `[]` ⇒ 无离线挂死风险。
- **Go agent 并发**：`go test -race ./...` 8 包全绿、无 race；`Supervisor` 锁/channel 用法正确（问题只在错误无出口）。
- **出站超时覆盖**：LLM/SSRF/TTS/打包脚本逐一核对，**无一处裸调用** ✅。
- **SSRF 防护**：逐跳手动跟随且每跳请求前过闸、流式 2MB 双重拦截、5 跳封顶 ✅。
- **密钥进备份**：还原白名单只允许 `TTS_VOICE`/`TTS_RATE`，防止恶意备份把 base_url 指向攻击者服务器偷走真 key；`DEEPSEEK_API_KEY` 从不在白名单 ✅（有测试覆盖）。
- **`static/` 硬编码端点/密钥**：正则扫 `https?://(?!localhost|127.0.0.1)` → **0 命中** ✅。
- **同步缓存内存边界**：`MAX_SYNC_CACHE_ENTRIES=50` + `MAX_SDP_PAYLOAD_BYTES=32KB` + TTL + FIFO，有测试钉住 ✅。
- **投影失败是否回滚 blob**：✅ 正确（`database.py:546` `with conn:` 包住 547-561，异常不吞 ⇒ 原子）。
- **`fsrs_*` 写入者唯一性**：✅ 唯一（`vocab_pool.py` INSERT/UPDATE + 备份还原原样回灌；DSR 复习端点不碰）。
- **`ALTER TABLE` 幂等闸**：✅ 正确（`PRAGMA table_info` 一次取全列后逐个判 + `IF NOT EXISTS`）。
- **HTTP/RPC 夹在事务内**：✅ 未发现（`log_study_event` 刻意置于 `with` 外，注释明说防 `SQLITE_BUSY`）。
- **深分页 `LIMIT 100000,20` / N+1 查询**：✅ 全仓无。
