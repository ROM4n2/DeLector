# ADR-0016: 统一词库（单一权威池）架构

> **Status:** Accepted (2026-09-29) — 用户拍板：方向「合并成一个权威词库」+ 粒度 **B（连词表条目也并成一张全局表）** + 来源只留内部（**不加 UI 徽标**）。离线优先按"不可破"处理。
> **⚠️ 本 ADR 收窄了 ADR-0014 的边界**（见 §4.1），若你要的是"**连代码数据模块也废掉、DB 当权威**"，那会**推翻** ADR-0014，需另议。
> **决策者:** Haoyu Xi
> **关联:** `docs/reviews/2026-09-28-swarm-audit-master.md`（P1「双词库心智」）、PR #72（i+1 词池打通）、**ADR-0011/0012/0013/0014/0015**（词表来源与存储边界）

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

### 1.2 词表**来源**已分层（合并必须保留）

`delector/core/lexicon.py`（ADR-0012）已定义三层 provenance：

| 层 | 来源模块 | 条数 | 性质 |
| --- | --- | --- | --- |
| `official` | `data/official_vocab.py::OFFICIAL_VOCAB` | 2732 | **官方歌德词表**（源自官方 Wortliste PDF 整理） |
| `manual` | `data/core_dict.py::CORE_VOCAB_MANUAL` | ≈442 | **手编核心** |
| `ai` | `data/core_dict_ext.py::CORE_VOCAB_EXT` | 3968 | **AI 批量生成**（cefr 由 AI 分级） |

字段级优先级（`data/lexicon_merge.py`）：**cefr `official > manual > ai`**；富字段 `manual > official > ai`；`PROVENANCE` 为运行期旁路（不进 5 元组 schema）。
另：`corpus_dict.OFFICIAL_CORPUS`（官方真题语料）、`a1_workbench_dict`/`a1_dict`（A1 成员/考纲视图）、`official_vocab_rich.py`（富字段 side-car，**agent 依官方 PDF 产出**、ipa 为规则式 g2p 非官方音标）—— 两池 A1/A2/B1 词表**同源**于此。

---

## 2. Decision Drivers

1. **单一心智**：用户要一处"我的词汇"（且用户明确选**彻底合并**：长痛不如短痛）。
2. **不破坏离线优先**：`file://`/断网下工作台必须仍可用。
3. **不丢记忆参数**：FSRS-6 `{s,d,lapses}` 无损迁移。
4. **不混淆来源**：AI 条目不得冒充官方；延续 `lexicon` 字段级优先级（ADR-0012）。来源**只留内部**（不加 UI 徽标）。
5. **数据不丢**：迁移可回滚、可对账（学习数据不可再生）。
6. **收敛面要全**：i+1、统计、Anki、备份都必须认同一池。
7. **不与 ADR-0014 正面冲突**：词表的**权威**（authoring）仍在代码数据模块。

---

## 3. Considered Options

### Option A：以服务端 `vocab_cards` 为权威，工作台改读写它
- 👍 复用服务端 SQL/语法卡/统计/Anki/备份链路
- 👎 **破坏离线**；FSRS-6 与服务端 DSR 列**不同构**，强映射**丢参数**；`file://` 失效。**风险高。**

### Option B：以 `wb_state` JSON 为权威，KARTEI 改读它
- 👍 单一 blob，改一处
- 👎 单行整份 JSON：无查询、**无 `grammar_cards`**、无 `mastered/article_id`、无到期队列索引。**风险高且不自然。**

### Option C：统一表 + 迁移，localStorage 降级为**离线缓存**（采纳；粒度 = B）
- 👍 **保留离线**；服务端获可查询统一池；可承载两类卡、FSRS-6 列与 `source` 列；迁移可分阶段、可对账
- 👍 粒度取 **B**：词表条目**也**进这张统一表（含 `source`），视图按 `source` 过滤 —— 真正的"一处我的词汇"
- 👎 需"本地缓存 ↔ 服务端权威"同步一致性面；一次性迁移有风险（缓解见 §5）；**触到 ADR-0014 边界**（见 §4.1）

---

## 4. Decision Outcome

**Chosen: Option C，粒度 B** —— 建立**单一权威池（服务端统一表）**，其中：
- **词表条目 + 用户学习状态**同表；每行带 **`source` 列**（`official` / `manual` / `ai` / `user`）；
- 工作台 localStorage **降级为离线缓存**（读优先本地、写本地后后台同步）；`file://`/断网仍完整可用；
- **来源只留内部**（`source` 列 + `lexicon` provenance），**不加 UI 徽标**（用户已选附带 A）。

**第一性理由**：
- 工作台存储层**已高度封装**（读 `loadAll()` + 5 个 `saveXxx()`，`workbench.html:1353-1357`；镜像 `wbsync` 自封闭 `:1370-1685`）⇒ 可整体重定向。
- 离线优先是工作台**明示的设计前提**（`workbench.html:11,1360-1368`）⇒ 排除 A。
- 用户选 B（彻底合并）：单一表 + `source` 列让"我的词汇"与"来源视图"在同一处表达，代价是需给表加 `source` 并让各视图按来源过滤。

### 4.1 与 ADR-0014 的边界（**收窄，不推翻**）

ADR-0014 原文立界：**词表（只读/版本化）在代码数据模块；用户/行为数据在 SQLite**，其 §1.2 P4 明确警告"后人极易顺手把词表搬进数据库"。本 ADR 的 B 粒度**触到这条边界**，处置如下：

- **权威（authoring）仍在代码数据模块**：`official_vocab.py` / `core_dict*.py` / `a1_*.py` 仍是唯一编写源，`lexicon` 仍是组装入口（ADR-0012 不动）。
- **统一表中的词表条目是「派生 materialization」**：由构建期/迁移期把 `lexicon`（含 provenance）**幂等投影**进表（可随时重建、可校验），**不成为权威源**。对 `source` 的写入同样来自 `lexicon.PROVENANCE`，不引入第二份真值。
- ⇒ **不推翻 ADR-0014，只新增"派生投影"这一允许项**。若你要的是"废掉代码模块、DB 当权威"，那才是推翻 0014 —— **请明确说**。

---

## 5. Consequences and Trade-offs

- 🟢 **Positive**：一处"我的词汇"；`source` 列使来源视图与个人池同表；i+1/统计/Anki/备份收敛同源；`vocab_cards` 增 FSRS-6 列后可无损承载工作台卡。
- 🔴 **Negative**：引入"本地缓存 ↔ 服务端权威"的同步一致性面（LWW 冲突、离线分叉）+ 一次性迁移风险；统一表需**可重建**（派生语义）以免与代码模块漂移。缓解：本地始终是读源与兜底；迁移与 materialization 都**先备份 + 对账**。
- 🛡️ **Compliance Guardrail**：
  1. **统一表是派生物**：`source` 与词表条目内容必须由代码模块投影而来（幂等、可重建）；**不得**在表中就地编辑词表内容。
  2. 迁移必须有「迁移前后两池词集合对账」测试（可复用既有 `tools/audit_official_vocab.py` 范式）。
  3. 工作台存储层重定向后，`file://` 直开用例（现有 `wb_*.mjs` 探针族）必须仍全绿。
  4. 「已学」判据保持单一实现（续用 `deck-bridge.js` 的 `stripGermanArticle`+`reps>0`；PR #72 已建 `mergeKnownLemmas`）。
  5. 来源分层不得被合并抹平：`cefr: official > manual > ai`、富字段 `manual > official > ai`（ADR-0012）逐字段保留。

### 已定 / 待确认
- **已定**：粒度 **B**；来源**不加 UI 徽标**（内部保留）；离线优先**不可破**（P1）。
- **待确认（可后置）**：**P2 语法卡**是否进统一池（工作台无语法卡概念；默认按 `type` 分治同表）；**P3** FSRS-6 `{s,d,lapses}` 是否必须无损（默认"必须"）。

### 分阶段落地（每阶段独立 PR、可回退，**不一次性大改**）
1. **Phase 0**：本 ADR（含 §4.1 边界）。
2. **Phase 1**：`vocab_cards` **加性**增列 —— `source`（official/manual/ai/user）+ FSRS-6 `fsrs_s/fsrs_d/fsrs_lapses`（走既有 `ALTER TABLE ADD COLUMN` 机制，向后兼容、零行为变化）；存量行回填 `source='user'`。
3. **Phase 2**：**派生 materialization** —— 构建期把 `lexicon`（含 `PROVENANCE`）幂等投影进统一表（可重建）+ 只读对账（量化重复/缺口）。
4. **Phase 3**：工作台存储层重定向（`loadAll`/`saveXxx`/`wbsync` → 统一表；localStorage 降级为缓存）+ 一次性迁移（**先备份、后对账校验**）。
5. **Phase 4**：收敛消费面 —— i+1、`/api/progress/stats`、Anki 导出、`_BACKUP_TABLES`（含 `wb_state`/统一表），视图按 `source` 过滤。

**未决**：两池**词重叠度**未知；Phase 2 的只读对账应先量化它，再决定 materialization 是否需去重映射。
