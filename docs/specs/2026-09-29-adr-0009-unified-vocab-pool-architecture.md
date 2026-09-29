# ADR-0009: 统一词库（单一权威池）架构

> **Status:** Proposed (2026-09-29) — 方向「**合并成一个权威词库**」已由用户拍板；机制取 **路径 C**。
> 转 Accepted 的前提是确认下方「待确认前提 P1（离线优先不可破）」。
> **决策者:** Haoyu Xi
> **关联:** `docs/reviews/2026-09-28-swarm-audit-master.md`（P1「双词库心智」）、PR #72（i+1 已知词池打通，本决策的前置补丁）

---

## 1. Context

DeLector 目前有**两套互不相通的"我的词汇"**：

| 维度 | KARTEI（卡盒） | VOKABELN（德语背词工作台） |
| --- | --- | --- |
| 前端 | `static/js/cards.js`（1217 行） | `static/german/workbench.html`（**4731 行**） |
| 权威存储 | 服务端 SQLite `vocab_cards` / `grammar_cards` | 浏览器 localStorage `wb.words.v1`/`wb.cards.v1` + IndexedDB |
| 服务端镜像 | —（本身就是服务端） | `wb_state` 单行整份 JSON（`PUT /api/wb/state`） |
| SRS | 服务端 DSR（`repetition_count/interval_days/ease_factor/due_date`） | 前端 **FSRS-6**（每卡 `{s,d,due,last,reps,lapses}`） |
| 语法卡 | 有 `grammar_cards` | **无** |
| 离线 | 依赖 `api()`，非离线应用 | **离线优先**：`file://` 直开、断网为正常态，服务端只作"最近镜像" |

**问题**：用户面对两个并列的"背词/卡"入口，不知词存在哪；且关键功能因两池割裂而静默失效/口径不一 —— 遇见区 i+1 覆盖率只读工作台 deck（PR #72 仅部分补上）；首页「掌握词汇」统计与 Anki 导出只认 `vocab_cards`；备份对两池不对称（`_BACKUP_TABLES` 不含 `wb_state`）。用户决策：**合并成一个权威词库**。

---

## 2. Decision Drivers

1. **单一心智**：用户要一处"我的词汇"，而非两套。
2. **不破坏离线优先**（硬约束，见「待确认前提」）：工作台在 `file://`/断网下必须仍然可用。
3. **不丢记忆参数**：工作台 FSRS-6 的 `{s,d,lapses}` 是既有学习成果，迁移必须无损。
4. **数据不丢**：任何迁移必须可回滚、可校验（学习数据不可再生）。
5. **收敛面要全**：词库统一后，i+1 覆盖率、进度统计、Anki 导出、备份都必须认同一池，否则只是把割裂挪了个地方。

---

## 3. Considered Options

### Option A：以服务端 `vocab_cards` 为权威，工作台改读写它
- 👍 服务端已有 SQL 查询、语法卡、统计、Anki、备份链路
- 👎 **破坏离线**（工作台从"本地为准"退化为"必须联网"）；FSRS-6 `{s,d}` 与服务器 DSR 列**不同构**，强映射**丢参数**；`file://` 直开场景直接失效。改动面覆盖 4731 行工作台的存储/复习/统计（500+ 处 `S.*` 引用）。**风险高。**

### Option B：以 `wb_state` JSON 为权威，KARTEI 改读它
- 👍 单一 blob，改一处
- 👎 `wb_state` 是**单行整份 JSON**：无查询、无 `grammar_cards`、无 `mastered/article_id`、无到期队列索引；工作台**根本没有语法卡** ⇒ 池天然残缺；等于让 KARTEI 退化成 blob 解析器。**风险高且不自然。**

### Option C：统一表 + 迁移，localStorage 降级为**离线缓存**（采纳）
- 👍 **保留离线**（本地缓存仍在，`file://`/断网可读本地）；服务端获得可查询的统一池；可承载两类卡（`type ∈ {vocab, grammar}`）与 FSRS-6 列；迁移可分批、可校验
- 👎 需要**双向同步收敛**（本地写 → 后台同步统一池）与一次性迁移；改动面仍较大（工作台 5 个 `saveXxx` + `loadAll` 重定向，但存储层**已高度封装**，见下）

---

## 4. Decision Outcome

**Chosen: Option C** —— 建立**单一权威池（服务端统一表）**，工作台 localStorage **降级为离线缓存**：读优先本地、写本地后后台同步；`file://`/断网仍完整可用。

**第一性理由**：
- 工作台的存储层**已被封装**（读写各一个入口：`loadAll()` 与 5 个 `saveXxx()`，`workbench.html:1353-1357`；镜像 `wbsync` 自封闭 `:1370-1685`）⇒ **可整体重定向**，不必逐处改 500+ 处 `S.*` 引用。这是 C 可行的关键。
- 服务端已有 `vocab_cards` + 统计 + Anki + 备份的成熟链路，扩展它比让 KARTEI 退化为 blob 解析更自然。
- 离线优先是工作台的**明示设计前提**（`workbench.html:11,1360-1368`），除非用户明确放弃，否则不可破 —— 这直接排除 A。

---

## 5. Consequences and Trade-offs

- 🟢 **Positive**：一处"我的词汇"；i+1 覆盖率/进度统计/Anki/备份收敛到同源；`vocab_cards` 增 FSRS-6 列后可无损承载工作台卡。
- 🔴 **Negative**：引入"本地缓存 ↔ 服务端权威"的同步一致性面（last-write-wins 冲突、离线期间的分叉）；迁移有一次性风险。缓解：本地始终是读源与兜底，同步失败不阻断离线使用；迁移**先备份 + 校验行数/词集合**再切。
- 🛡️ **Compliance Guardrail**：① 迁移必须有「迁移前后两池词集合对账」测试；② 工作台存储层重定向后，`file://` 直开用例（现有 `wb_*.mjs` 探针族）必须仍全绿；③ 统一池的「已学」判据保持单一实现（续用 `deck-bridge.js` 的 `stripGermanArticle`+`reps>0` 口径，PR #72 已建立 `mergeKnownLemmas`）。

### 待确认前提（决定 A/C 生死，只有用户能答）
- **P1（最关键）**：**离线优先是不可谈判的硬约束吗？** 若"是" ⇒ 路径 C（本文采纳）。若"可以为了统一而放弃 `file://`/断网可用" ⇒ 才可能走 A（更省同步，但丢离线 + 需解决 FSRS 参数映射）。
- **P2**：**语法卡要不要进统一池？**（工作台无语法卡概念；若不要，统一池需按 `type` 分治）
- **P3**：**FSRS-6 `{s,d,lapses}` 是否必须无损保留？**（本文按"必须"设计）

### 分阶段落地（每阶段独立 PR、可回退，**本 ADR 只定方向，不一次性大改**）
1. **Phase 0**：本 ADR（方向 + 前提确认）。
2. **Phase 1**：`vocab_cards` **加性**增列 `fsrs_s/fsrs_d/fsrs_lapses`（走既有 `ALTER TABLE ADD COLUMN` 迁移机制，向后兼容、零行为变化）+ 回填单测。
3. **Phase 2**：新增「统一卡」读写端点（本地 `wb.*` ↔ 服务端互转，先只做**只读对账**与**单向**服务端→本地，复用 `get_vocab_by_cefr(scope=reader)` 范式）。
4. **Phase 3**：工作台存储层重定向（`loadAll`/`saveXxx`/`wbsync` 改走统一池，localStorage 降级为缓存）+ 一次性迁移（先备份、后对账）。
5. **Phase 4**：收敛消费面 —— i+1 覆盖率、`/api/progress/stats`、Anki 导出、`_BACKUP_TABLES`（含 `wb_state`/统一池）。

**未决**：两池**重叠度**未知（工作台词 vs KARTEI 词的实数/交集）。Phase 2 的只读对账探针应先量化它，再决定迁移是否需要去重映射。
