# ADR-0016: 统一词库（单一权威池）架构

> **Status:** Proposed (2026-09-29) — 方向「**合并成一个权威词库**」已由用户拍板；机制取 **路径 C**。
> 转 Accepted 的前提是确认 §5「待确认前提 P1（离线优先不可破）」。
> **决策者:** Haoyu Xi
> **关联:** `docs/reviews/2026-09-28-swarm-audit-master.md`（P1「双词库心智」）、PR #72（i+1 已知词池打通，本决策的前置补丁）、ADR-0011/0012/0013/0015（词表来源与主干分层）

---

## 1. Context

### 1.1 两套互不相通的"我的词汇"

| 维度 | KARTEI（卡盒） | VOKABELN（德语背词工作台） |
| --- | --- | --- |
| 前端 | `static/js/cards.js`（1217 行） | `static/german/workbench.html`（**4731 行**） |
| 权威存储 | 服务端 SQLite `vocab_cards` / `grammar_cards` | 浏览器 localStorage `wb.words.v1`/`wb.cards.v1` + IndexedDB |
| 服务端镜像 | —（本身就是服务端） | `wb_state` 单行整份 JSON（`PUT /api/wb/state`） |
| SRS | 服务端 DSR（`repetition_count/interval_days/ease_factor/due_date`） | 前端 **FSRS-6**（每卡 `{s,d,due,last,reps,lapses}`） |
| 语法卡 | 有 `grammar_cards` | **无** |
| 离线 | 依赖 `api()`，非离线应用 | **离线优先**：`file://` 直开、断网为正常态，服务端只作"最近镜像" |

**问题**：两个并列的"背词/卡"入口，用户不知词存哪；关键功能因割裂而静默失效/口径不一 —— i+1 覆盖率只读工作台 deck（PR #72 仅部分补上）；首页「掌握词汇」与 Anki 导出只认 `vocab_cards`；备份对两池不对称（`_BACKUP_TABLES` 不含 `wb_state`）。

### 1.2 词表**来源**已统一且分层（与本决策正交，但必须保留）

**本决策合并的是「用户学习状态的存储」，不是「词表来源」** —— 词表来源早已是单一主干 + 分层 provenance（`delector/core/lexicon.py`，ADR-0012）：

| 层 | 来源模块 | 性质 |
| --- | --- | --- |
| `official` | `delector/data/official_vocab.py`（`OFFICIAL_VOCAB`，2732） | **官方歌德词表**（源自官方 Wortliste PDF 整理） |
| `manual` | `delector/data/core_dict.py::CORE_VOCAB_MANUAL`（≈442） | **手编核心** |
| `ai` | `delector/data/core_dict_ext.py::CORE_VOCAB_EXT`（3968） | **AI 批量生成**（cefr 由 AI 分级） |

字段级优先级（`delector/data/lexicon_merge.py`）：**cefr `official > manual > ai`**；富字段 `manual > official > ai`；`PROVENANCE` 记录每 lemma 的来源集合（运行期旁路，不进 5 元组 schema）。
另有：`corpus_dict.OFFICIAL_CORPUS`（官方真题语料）、`a1_workbench_dict`/`a1_dict`（A1 成员/考纲视图）、`official_vocab_rich.py`（富字段 side-car，**由 agent 依官方 PDF 产出**、ipa 为规则式 g2p）—— 两池的 A1/A2/B1 词表**同源**于此。

---

## 2. Decision Drivers

1. **单一心智**：用户要一处"我的词汇"。
2. **不破坏离线优先**（硬约束，见 §5）：`file://`/断网下工作台必须仍可用。
3. **不丢记忆参数**：FSRS-6 `{s,d,lapses}` 必须无损迁移。
4. **不混淆来源**：合并后 AI 条目**不得冒充**官方；须延续 `lexicon` 的三层 provenance 与字段级优先级（ADR-0012）。
5. **数据不丢**：迁移可回滚、可对账（学习数据不可再生）。
6. **收敛面要全**：i+1、统计、Anki、备份都必须认同一池。

---

## 3. Considered Options

### Option A：以服务端 `vocab_cards` 为权威，工作台改读写它
- 👍 复用服务端 SQL/语法卡/统计/Anki/备份链路
- 👎 **破坏离线**；FSRS-6 `{s,d}` 与服务端 DSR 列**不同构**，强映射**丢参数**；`file://` 失效。改动面覆盖 4731 行工作台（500+ 处 `S.*`）。**风险高。**

### Option B：以 `wb_state` JSON 为权威，KARTEI 改读它
- 👍 单一 blob，改一处
- 👎 单行整份 JSON：无查询、**无 `grammar_cards`**、无 `mastered/article_id`、无到期队列索引；工作台**根本没有语法卡** ⇒ 池天然残缺。**风险高且不自然。**

### Option C：统一表 + 迁移，localStorage 降级为**离线缓存**（采纳）
- 👍 **保留离线**；服务端获可查询统一池；可承载两类卡与 FSRS-6 列；迁移可分阶段、可对账
- 👎 需"本地缓存 ↔ 服务端权威"同步一致性面；一次性迁移有风险（缓解见 §5）

---

## 4. Decision Outcome

**Chosen: Option C** —— 建立**单一权威池（服务端统一表）**，工作台 localStorage **降级为离线缓存**：读优先本地、写本地后后台同步；`file://`/断网仍完整可用。

**第一性理由**：
- 工作台存储层**已高度封装**（读 `loadAll()` + 5 个 `saveXxx()`，`workbench.html:1353-1357`；镜像 `wbsync` 自封闭 `:1370-1685`）⇒ **可整体重定向**，不必逐处改 500+ 处 `S.*`。这是 C 可行的关键。
- 服务端已有 `vocab_cards` + 统计 + Anki + 备份的成熟链路，扩展它比让 KARTEI 退化为 blob 解析更自然。
- 离线优先是工作台**明示的设计前提**（`workbench.html:11,1360-1368`），除非明确放弃，否则不可破 —— 直接排除 A。

---

## 5. Consequences and Trade-offs

- 🟢 **Positive**：一处"我的词汇"；i+1/统计/Anki/备份收敛同源；`vocab_cards` 增 FSRS-6 列后可无损承载工作台卡。
- 🔴 **Negative**：引入"本地缓存 ↔ 服务端权威"的同步一致性面（LWW 冲突、离线分叉）+ 一次性迁移风险。缓解：本地始终是读源与兜底，同步失败不阻断离线；迁移**先备份 + 对账**再切。
- 🛡️ **Compliance Guardrail**：
  1. 迁移必须有「迁移前后两池词集合对账」测试（可复用既有 `tools/audit_official_vocab.py` 对账范式）。
  2. 工作台存储层重定向后，`file://` 直开用例（现有 `wb_*.mjs` 探针族）必须仍全绿。
  3. 「已学」判据保持单一实现（续用 `deck-bridge.js` 的 `stripGermanArticle`+`reps>0` 口径；PR #72 已建 `mergeKnownLemmas`）。
  4. **来源分层不得被合并抹平**：统一池须保留 `lexicon` 的 official/manual/ai provenance 与 `cefr: official > manual > ai` 优先级（ADR-0012）；AI 条目不得冒充官方。

### 待确认前提（决定 A/C 生死，只有用户能答）
- **P1（最关键）**：**离线优先是不可谈判的硬约束吗？** 是 ⇒ 路径 C（本文采纳）；若"可放弃" ⇒ 才可能走 A。
- **P2**：**语法卡要不要进统一池？**（工作台无语法卡概念；若不要，统一池按 `type` 分治）
- **P3**：**FSRS-6 `{s,d,lapses}` 是否必须无损保留？**（本文按"必须"设计）

### 分阶段落地（每阶段独立 PR、可回退，**不一次性大改**）
1. **Phase 0**：本 ADR（方向 + 前提确认）。
2. **Phase 1**：`vocab_cards` **加性**增列 `fsrs_s/fsrs_d/fsrs_lapses`（走既有 `ALTER TABLE ADD COLUMN` 迁移机制，向后兼容、零行为变化）。
3. **Phase 2**：只读对账 + 单向 `服务端→本地` 回流（复用 `get_vocab_by_cefr(scope=reader)` 范式）。
4. **Phase 3**：工作台存储层重定向 + 一次性迁移（**先备份、后对账校验**）。
5. **Phase 4**：收敛消费面 —— i+1、`/api/progress/stats`、Anki 导出、`_BACKUP_TABLES`（含 `wb_state`/统一池）。

**未决**：两池**词重叠度**未知（工作台词 vs KARTEI 词）；Phase 2 的只读对账应先量化它，再决定迁移是否需去重映射。
