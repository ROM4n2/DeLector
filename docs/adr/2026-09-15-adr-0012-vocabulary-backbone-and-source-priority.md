---
title: "ADR-0012: 词汇主干分层与来源优先级（Lexicon Backbone & Source Priority）"
created: 2026-09-15
updated: 2026-09-15
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/data-model
  - topic/api-contract
status: stable
audience:
  - architect
  - developer
source: "vault-plan 开工前架构复审（用户拍板：采纳修订结构，先出 ADR）"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0012: 词汇主干分层与来源优先级（Lexicon Backbone & Source Priority）

- **状态**: Accepted
- **日期**: 2026-09-15
- **作者**: vault-plan 架构复审 + 用户拍板
- **领域**: 数据模型 / 数据管线 / 服务端 API 契约
- **上游**: ADR-0011（词库单一真相化 + `SCOPE_PREDICATES`）、ADR-0005（多等级可扩展 / `exam_catalog`）、ADR-0009（包重构 / shim 过渡 / 删除测试）
- **落地计划**: `docs/plans/2026-09-15-goethe-official-vocab-migration.md`（§7 评估 / §8 修订 Phase 1）

---

## 1. 背景与问题定义 (Context & Problem Statement)

### 1.1 现状（一手实测，2026-09-15）

用户制作并交付官方歌德词表（5 元组 schema，与 `core_dict` 存储同构）：

| 交付文件 | 内容 | 条数 |
|---|---|---|
| `a1_fragment.py` | 官方歌德 A1（`A1_SD1_Wortliste_02.pdf` 精选） | 660 |
| `a1_augment_core.py` | A1 级常用基础词 overlay（显式增补层） | 10 |
| `a2b1_fragment.py` | 官方歌德 A2/B1 权威词表 | A2 736 / B1 1617 |

delector 现有**三套互不相干的 A1 词表表示** + 一条 `core_dict` 链：

| 源 | 条数 | 结构 | 消费端 |
|---|---|---|---|
| `a1_workbench_dict.A1_WORKBENCH_SEED` | 682 | 富（`id=a1-0001` 序号 / hw / pos / gloss / ipa / ex / letter / page） | 背词工作台（**FSRS 进度键 = id**） |
| `a1_dict.GOETHE_A1_VOCAB` | 702 | 富（topic / lemma / gender / plural / definition_zh / example_de / example_zh） | 备考域「官方考纲词表」+ `vocab_stats` |
| `core_dict.CORE_VOCAB_DB` | 4411 | 5 元组 `lemma -> (cefr, pos, gender, plural, def_zh)` | NLP 难度标注 / `get_vocab_by_cefr` / `lookup_core_vocab` |

`CORE_VOCAB_DB` = 手编 `core_dict.py`（442）⊕ AI `core_dict_ext.py`（3969；**源实为歌德词表** `b1_sorted`/`a2_words`/`b2_all`，仅中文释义由 DeepSeek 生成）。各等级：A1 459 / A2 974 / B1 1712 / B2 860 / C1 406。

### 1.2 问题

- **P1 同一批词三种表示，消费端各取各的（联动债）**：`vocab_stats` 读 `GOETHE_A1_VOCAB`（lemma 集）、NLP 读 `CORE_VOCAB_DB`、工作台读 `A1_WORKBENCH_SEED`；改一处不难，**保证三处一致只能靠人记**。ADR-0011 的"单一真相"只做到了 A1 工作台内部，未做到全局。
- **P2 来源不可见 → 无法支撑"仅官方精选"**：官方表与 AI 表（A2 交集 363/974、B1 交集 842/1712）需并存且**按来源分别出视图**（备考域要只出官方 736/1617）。原方案"合并进单一 dict"会使来源信息丢失，按来源过滤退化为 O(n) 反查。
- **P3 `core_dict` 语义重载**：它被 **17 个文件**依赖（9 个 delector 模块含 NLP 热路径 + 6 个构建工具 + 测试）。让它同时充当"全量难度词典"与"官方精选源"，改动影响面不清晰 = 长期维护陷阱。
- **P4 两条冻结线**：① 存储 5 元组**冻结**（ADR-0011 §5-#6）；② 输出契约 9 字段被 `tests/test_vocab_contract_uniform.py:23,48` 以 `set(keys) == CONTRACT_FIELDS`**严格相等**钉死。任何"加来源字段"的做法都会直接违反它们。
- **P5 A1 三套收敛无路径**：因 P1/P4，A1 富结构（workbench seed / `GOETHE_A1_VOCAB`）长期只能"悬空"，没有可执行的收敛路径。

### 1.3 触发点

用户交付官方 A1/A2/B1 词表，并拍板 **备考域「仅官方精选」展示口径（736/1617）**；同时明确诉求为"可扩展、为未来考虑、利于联动"。若不先定结构，接词表会把 P1–P3 同步放大，且落下将来必须返工的中间结构。

## 2. 决策驱动因素 (Decision Drivers)

- **可扩展（首要）**：新增一个等级或一个来源 = **加一个数据分片**，消费端与判定逻辑零改动（延续 ADR-0011"加一级 = 改数据"）。
- **可维护 / 可审计**：词汇只有**一个主干入口**；任一词条的"来自哪个源、被谁覆盖"必须可查询、可对账。
- **不破两条冻结线**：5 元组存储不变；9 字段输出契约不变（默认逐字不变）。
- **不丢覆盖**：AI 表独有 A2/B1 共 1301 条为真实词、B2/C1 共 1164 条无官方对应——**必须保留在主干**（供 NLP 难度标注），只是不作为"官方精选视图"输出。
- **风险可控**：17 个 `core_dict` 依赖点需零破坏过渡（复用 ADR-0009 既有的 shim 模式）。

## 3. 备选方案 (Considered Options)

- **Option A：把官方词表并入 `core_dict`，合并成单一 dict（原计划）**
  - 👍 Pros：改动最小（仅 `core_dict.py` 底部合并链加一行）；复用现有 `{**EXT, **BASE}` 模式，零新范式。
  - 👎 Cons：**来源信息丢失**，无法支撑"仅官方精选"（P2）；`core_dict` 语义重载加深（P3）；A1 三套收敛仍悬空（P5）；将来要抽主干 = **返工**。

- **Option B：抽出 `lexicon` 主干 + 显式 provenance + 来源感知视图（选定）**
  - 👍 Pros：来源原生可见（按来源过滤 O(1)）；`core_dict` 降级为"分片之一"，语义清晰；扩展 = 注册一片；A1 收敛有明确路径；两条冻结线均不破。
  - 👎 Cons：改动量中等（新增 `lexicon.py` + shim + 查询层参数）；需一次性梳理 17 个 `core_dict` 依赖点（shim 兜底）。

## 4. 决策 (Decision Outcome)

**选定 Option B。** 核心设计 5 条：

1. **分片注册表（来源 = 模块边界）**：维持存储 5 元组冻结，**用"分片模块"表达来源**（不引入存储字段）。分片：`core_dict`（手工）/ `core_dict_ext`（AI）/ `official_vocab`（官方 A1 670 + A2 736 + B1 1617）。未来加 B2/C1 官方 = 加一片。
2. **加载期 provenance 旁路**：`delector/core/lexicon.py` 是**唯一主干加载器**，加载期合并全部分片并计算 `LEXICON[lemma] = {value, provenance: frozenset[str]}`。`provenance` 是**运行期派生结构**，不写入存储（守 P4-①）。
3. **优先级 = 字段级（2026-09-15 裁决，取代原整体优先级）**：`cefr` 按 **官方 > 手编 > AI**；其余字段（`pos` / `gender` / `plural` / `def_zh`）按 **手编 > 官方 > AI**。理由（一手实测）：官方 Wortliste 的 plural 列 **约 30% 为占位 `-`**，直接覆盖手编会劣化数据——`haus` 手编 `-..er`→官方 `-ä`、`schule` `-n`→`-`、`arzt` `-..e`→`Ä`、`apfel` `-..`→`Ä`（均错或不完整）；而手编 443 条系人工校订。故**等级以官方为权威（用户核心诉求），富字段保留人工质量**。实现：逐字段取"第一个含该 lemma 的来源"的对应值；**冲突明细须可输出**（对账工具），以支撑 ADR-0011 §5-#7 的"lemma 即 id"变更审计。
4. **来源感知视图（唯一查询入口）**：`get_vocab_by_cefr(cefr, scope, sources=None)`；`sources=None` = 全部（NLP 难度标注用）；`sources={"official"}` ⇒ A2 736 / B1 1617（备考域「官方精选」用）。**输出契约默认仍为 9 字段**（不破 P4-②）；若未来需在 API 暴露来源，须另立 ADR 加**可选**字段并同步契约测试。
5. **`core_dict.CORE_VOCAB_DB` 降级为兼容 shim**：`CORE_VOCAB_DB = LEXICON 的 5 元组视图`，模块头标记 deprecated（ADR-0009 模式），保证 17 个既有 import 点零改动；新代码一律走 `lexicon`。

6. **多级核心词白名单（预留，本轮不实现名单）**：核心词身份按等级配置 `CORE_IDS_BY_LEVEL: Dict[str, frozenset[str]]`（现状仅 `A1` → 213；22 自定义另表），`SCOPE_PREDICATES` 预留 `a2core` / `b1core` / `b2core` 谓词位（骨架就位）。用户拍板：为后期 B2 / B2核心 等必然扩展留位——**本轮只预留结构、不挑 A2/B1/B2 核心名单**；A1 现有 213/22 改为从该配置读取（零行为变化）。

**明确不做（scope 控制）**：本轮**不动** A1 富结构（`A1_WORKBENCH_SEED` / `GOETHE_A1_VOCAB`）——它们依赖富字段与序号 id，收敛留 **Phase 2**；但 Option B 使 Phase 2 从"悬空"变为"自然的派生改造"。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

**正面**
- 「仅官方精选」与「全量难度标注」**同一主干两个视图**，无需两套数据；备考域口径切换零数据改动。
- 扩展成本收敛为"注册一片 + 一条排序位置"；消费端不动。
- 来源可审计：任一词条可答"来自官方还是 AI、被谁覆盖"，为词表迭代/回滚提供依据。
- A1 三套收敛（Phase 2）获得架构支撑，不再悬空。

**代价 / 风险**
- 引入 `lexicon.py` 主干层 + shim，比"塞 core_dict"多一层；需一次性验证 17 个依赖点零回归（shim 兜底 + 全量 pytest）。
- `provenance` 为运行期结构，**不得被误写入存储或契约**（否则破冻结线）→ 用测试钉死。
- 优先级顺序是隐式契约（写在注册表）→ 必须由测试显式钉住，防后人改乱。

**防御性规范（MUST）**
1. **存储 5 元组冻结**：`lemma -> (cefr, pos, gender, plural, def_zh)` 不变；`provenance`/来源等元数据**只能**存在于加载期旁路，**禁止**写入数据模块或 SQLite。
2. **输出契约 9 字段冻结**：`{id, hw, pos, gender, plural, de, zh, core, cefr}` 默认产出逐字不变；扩展字段须另立 ADR 并同步 `tests/test_vocab_contract_uniform.py`。
3. **唯一主干入口**：`routes/`、`services/`、`nlp_engine/` **禁止直接 import 分片模块**（`core_dict` / `core_dict_ext` / `official_vocab`），只允许经 `lexicon`；由静态断言测试钉住。
4. **优先级顺序守卫**：`官方 > 手编 > AI` 写死在 `tests/test_lexicon_priority.py`（含至少一条同 lemma 冲突用例，断言取官方值）。
5. **来源视图守卫**：`sources={"official"}` 的产出条数与官方分片精确一致（A1 670 / A2 736 / B1 1617），防来源过滤失效。
6. **id 只增不改（承接 ADR-0011 §5-#7）**：cefr 以官方为准带来的 `vocab_id` 变化只影响**新增 id**；既有 id 不得改名，历史进度孤儿按用户拍板接受（真实用户进度集中在 A1 工作台）。
7. **打包三处同步**：新增数据模块 `delector.data.official_vocab` MUST 同步 `package_windows.py` / `build-release.yml` / `tests/test_server.py::data_dict_modules`。
8. **字段级优先级由测试钉死（2026-09-15 增补）**：`cefr`（官方优先）与其余字段（手编优先）的取值规则 MUST 由测试覆盖，含真实冲突样例（`haus` 的 `plural` 取手编 `-..er`、`cefr` 取官方；`schule` 的 `plural` 取手编 `-n`）。
9. **默认视图语义**：`get_vocab_by_cefr(cefr)`（`sources=None`）返回**主干合并后按等级过滤**的视图；**各等级"官方原样词表"必须经 `sources={"official"}`（或 `lexicon.official_level`）获取**（二者数值不同：A2 默认比官方原样少，因官方把部分原 A2 词改判 B1/A1）。消费端须明确自己需要哪一种，不得混用。

## 6. 实施顺序（共识，供 /vault-exec 拆解）

1. **R1（前置）**：本 ADR 定稿归档。
2. **R2**：官方分片 `delector/data/official_vocab.py`（纯数据，5 元组）+ 源校验测试。
3. **R3**：主干 `delector/core/lexicon.py`（分片注册表 + provenance + 优先级）+ `tests/test_lexicon_priority.py`。
4. **R4**：查询层 `sources` 过滤接入；`exam_catalog.count_fn` 与 `routes/a2.py` 改「仅官方」。
5. **R5**：`core_dict.CORE_VOCAB_DB` 降级 shim（deprecated 标记）+ 17 依赖点零回归验证。
6. **R6**：单入口守卫测试（`routes/services/nlp_engine` 禁直连分片）。
7. **R7**：对账工具 `tools/audit_official_vocab.py`（条数/交集/独有/588 条 cefr 冲突明细）。
8. **R8**：打包三处同步 + AI 噪声保守清理（仅删确证项）。
9. **R9**：文档收口（本 ADR + `PROJECT_OVERVIEW`）+ 删除仓库根 3 个源文件 + 全量回归。
10. **验收门**：全量 pytest 零回归 + `ruff` 零告警 + `mypy` 零错误 + 单入口/优先级/来源视图三条守卫全绿 + 桌面与 Android 覆盖安装后备考域 A2/B1 显示 736/1617。

## 7. 相关 (References)

- **上游决策**：ADR-0011（词库单一真相化、`SCOPE_PREDICATES`、§5-#6 存储冻结 / §5-#7 lemma 即 id）、ADR-0009（包重构 / shim 过渡 / 删除测试）、ADR-0005（多等级 / `exam_catalog`）。
- **落地计划**：`docs/plans/2026-09-15-goethe-official-vocab-migration.md`（§7 开工前架构评估、§8 修订 Phase 1 R1–R9）。
- **现状取证**：`delector/core/database.py:1728–1937`（`_load_a1_workbench_words` / `_load_a2_vocab_words` / `get_vocab_by_cefr` / `_contract_item`）、`delector/data/core_dict.py:516–524`（合并链）、`delector/services/exam_catalog.py:27–89`、`delector/data/a1_dict.py:28`（`GOETHE_A1_VOCAB`）、`tools/build_dict.py`、`tests/test_vocab_contract_uniform.py:23,48`。
- **评估数据**：AI 独有 A2 522 / B1 779（真实词）；AI B2 773 / C1 391 无官方对应；588 条同 lemma cefr 冲突。
