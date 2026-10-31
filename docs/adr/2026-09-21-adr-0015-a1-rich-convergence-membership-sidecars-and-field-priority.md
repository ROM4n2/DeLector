---
title: "ADR-0015: A1 富结构收敛——成员集 side-car + FRAGMENTS 单源 + 字段级优先级"
created: 2026-09-21
updated: 2026-09-26
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/data-model
  - topic/api-contract
status: active
audience:
  - architect
  - developer
source: "/vault-grill 双镜拷问（2026-09-21），落实 ADR-0013 / ADR-0014 明确 defer 的「A1_WORKBENCH_SEED / GOETHE_A1_VOCAB 派生收敛」"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0015: A1 富结构收敛——成员集 side-car + FRAGMENTS 单源 + 字段级优先级

- **状态**: Accepted
- **日期**: 2026-09-21
- **领域**: 词表数据模型 / 构建管线 / 输出契约 / 前端卡片
- **上游**: ADR-0011（5 元组冻结 / id 只增不改）、ADR-0012（主干分层 + 字段优先级）、ADR-0013（11→12 字段契约 +「A1 不切 rich / 派生收敛另议」）、ADR-0014（词表不入库 + A1 取数统一 + 同步只补空）
- **落地形态**: `/compose-next` 特性文档 `docs/compose/spec/a1-rich-convergence.md`

---

## 1. 背景与问题定义 (Context & Problem Statement)

### 1.1 现状（取证压实）

A1 词表存在**三源存储**，内容大量重叠但**成员集合并不相同**：

| 源 | 规模 | 键 | 富字段 |
|---|---|---|---|
| `delector/data/a1_workbench_dict.py` `A1_WORKBENCH_SEED` | 682 + custom 22 + core 213 | `a1-0001`… / `core-022` | `ipa` + 多对 `ex` + 原值 `letter`（无 gender/plural） |
| `delector/data/a1_dict.py` `GOETHE_A1_VOCAB` | 702 | lemma | `topic` / gender / plural / `definition_zh` / `example_de/zh`（**无 ipa/id/letter**） |
| `official_vocab` + `official_vocab_rich`（经 `lexicon`） | A1 670 / RICH 660 | lemma | 5 元组 + g2p `ipa` + `example_*` |

**关键实测**：seed ∩ GOETHE ≈ **391** lemma；GOETHE-only ≈ 279；seed-only ≈ 311。二者**不是同一集合的双份拷贝**，而是两套教参表。二者之间**无 id↔lemma 映射表**。

### 1.2 问题

- **P1 内容双写**：共享 391 lemma 的 ipa/例句/释义在 seed 与 GOETHE（及 RICH）多处可改，PR 历史已出现「改模块 + 重跑 HTML 注入」两步纪律面。
- **P2 取数与字段面分叉**：考纲 A1 卡无 IPA；工作台 A1 无 gender/plural（靠 `A1_LEMMA_META` 运行期拼）；A2/B1 已走 `lexicon.rich_of`。
- **P3 身份不可派生**：FSRS 进度键 = seed `a1-NNNN`/`core-NNN`；`letter` 有 10 条人工原值 ≠ `letterOf` 派生（ADR-0014 实测）。
- **P4 「从主干一张表投影两边」在集合分叉下不成立**：完整派生要么并集重映射 id（破 FSRS），要么砍教学面（丢 GOETHE-only/seed-only）。

## 2. 决策驱动因素 (Decision Drivers)

- **真实痛点是维护面与字段对齐**，不是用户可见 bug（L0 YAGNI 校正）。
- **FSRS id 不变式**（ADR-0011）与 **letter 原值** 不可派生 → 必须 side-car。
- **人工值 > 规则/官方**（禁编造；[[01-Rules/STORED-DATA-BACKFILL]]「只补空、不抹非空」）。
- **单一 merge 路径**（Ladder L1：复用 `lexicon_merge.FIELD_PRIORITY`；L2：零新依赖）。
- **契约 12 字段不破**（ADR-0013/0014）；消费端只经 `lexicon`（ADR-0012 §5-3）。

## 3. 备选方案 (Considered Options)

### 3.1 收敛拓扑
| | | |
|---|---|---|
| **A 成员清单 + 共享字段单源（选定）** | 两个成员集保留为一等 side-car；内容进主干 | ✅ 零 id 迁移；消双写 |
| B 并集单表 + 双视图 | ~992 收一张主表 | ❌ FSRS/双 id 空间风险，一次到位过大 |
| C 只做考纲侧投影 | 仅 GOETHE 补富字段 | ❌ seed 双写与 HTML 注入纪律仍在 |

### 3.2 富字段权威序
| | | |
|---|---|---|
| **A 字段级优先级（选定）** | 见 §4-3 | ✅ 对齐 ADR-0012 + 红线 12 |
| B RICH/官方为准 | g2p 压人工 IPA | ❌ 违反人工值优先 |

### 3.3 专有词归属
| | | |
|---|---|---|
| **A 全部进 FRAGMENTS（选定）** | seed/GOETHE 内容以 provenance 进 `lexicon.FRAGMENTS` | ✅ 唯一 merge 路径 |
| B 专有词留双模块 | 仅 391 进主干 | ❌ 双内容存储继续存在 |

### 3.4 考纲 A1 字段面
| | | |
|---|---|---|
| **A 露出 IPA（选定）** | 对齐 A2/B1；`a1_cards.js` 增 IPA 行 | ✅ 用户可见改进 |
| B 仅下发不渲染 | UI 不动 | ❌ 字段面继续分叉 |

## 4. 决策 (Decision Outcome)

**选定 §3 全部 Option A。**

1. **身份与成员 side-car（不可派生，显式保留）**
   - `WORKBENCH_MEMBERSHIP`：`a1-NNNN`/`core-NNN` → lemma（+ `letter` 原值、`page` 若仍需写回）；
   - `CORE_IDS`（213）与 `SEED_ID_ALIASES`（2）**不改语义**（ADR-0014 §6 修正点 ④）；
   - `GOETHE_MEMBERSHIP`：702 lemma 有序清单 + `topic` 映射；
   - `CUSTOM_22`：`core-*` 词全量条目（官方 A1 不含）。
2. **内容单源**：seed / GOETHE 的 lemma 键内容（词形、pos、gender、plural、释义、ipa、例句）**全部**以 `FRAGMENTS` provenance（`workbench-a1` / `goethe-a1`）并入 `lexicon`；官方/手编/AI 沿用 ADR-0012。
3. **字段级优先级（冲突裁决）**（`lexicon_merge` 扩展，纯函数）：
   - `ipa`：workbench-a1（人工） > goethe-a1 > rich（g2p） > 其它；
   - `example`（德/中）：workbench-a1 多对 `ex` > goethe-a1 > rich > 其它；
   - `gender` / `plural` / `zh`：goethe-a1 > official > workbench-a1 > A1_LEMMA_META > AI；
   - **只补空、非空永不覆盖**；缺值 → 显式空，**禁止编造**。
4. **产出投影**
   - 工作台 A1：`lexicon` 投影 + `WORKBENCH_MEMBERSHIP` + `CUSTOM_22` → 仍输出 `a1-NNNN` id 与原 `letter`（12 字段契约不变）；
   - 考纲 A1：`lexicon` 投影 + `GOETHE_MEMBERSHIP` → `GET /api/a1/vocab` 增 `ipa`（及与契约一致的富字段）；前端考纲卡**露出 IPA**。
5. **HTML 内联 `SEED_WORDS`**：降级为**构建产物**（`tools/build_workbench_seed.py` 从投影生成，保持幂等与 file:// fallback）；G1/G2/G3 内联不当主路径守卫**继续有效**。
6. **单入口**：消费端只经 `lexicon` / `_contract_item`；禁直连 `a1_workbench_dict` / `a1_dict`（迁移完成后二者仅存 side-car 与兼容 re-export）。

**明确不做（scope 控制）**：不做 `a1-NNNN` ↔ official id 重映射；不改 FSRS 键空间；不改 12 字段输出契约字段集；不引入 SQLite 词表；不合并 A2/B1 成员逻辑（已收敛）；不重写 `SEED_ID_ALIASES` 语义。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

🟢 **正面**：共享 lemma 内容单源；考纲 A1 补 IPA；merge/优先级与 ADR-0012 同构；HTML 注入降为纯构建产物；专有教学面（GOETHE topic / seed 多例句 / custom 22）零丢失。

🔴 **代价**：data 模块形态变化 → **打包三处注册**（`package_windows.py` / `build-release.yml` / `test_server.py::data_dict_modules`）必须同步；`count_fn=len(GOETHE_A1_VOCAB)` 等计数守卫改为 `len(GOETHE_MEMBERSHIP)`；前端改动 → **Android 需覆盖安装**；一次性迁移投影等价性探针（704/704、702/702）必须先红后绿。

**防御性规范（MUST）**
1. **id 只增不改**：`a1-NNNN` / `core-NNN` 契约稳定；下架仅经 `SEED_ID_ALIASES`。
2. **letter 服务端原值下发**：禁止前端 `letterOf` 派生覆盖（10 条漂移红线）。
3. **字段优先级唯一点**：实现落在 `lexicon_merge`（或同等纯函数），禁止消费端各写一套。
4. **只补空**：任何投影/回填不得抹掉非空字段（红线 12）。
5. **契约 12 字段严格相等**：`test_vocab_contract_uniform` 不得放宽为子集断言。
6. **投影等价探针**：迁移前后工作台 A1 704 条、考纲 702 条在约定字段上逐条等价（除有意新增的考纲 `ipa`）。
7. **打包三处同步** + 数据模块清单冻结测试同步。
8. **IPA 无 tie-bar**（ADR-0013 §5-4 延续）。

## 6. 实施顺序（供 /compose-next Tasks 引用）

| # | 内容 | 验收要点 |
|---|---|---|
| S1 | `lexicon_merge` 字段优先级扩展 + 单元测试 | 冲突/只补空/确定性 |
| S2 | seed/GOETHE 内容迁入 FRAGMENTS provenance；side-car 收敛为成员/id/letter/topic/custom22 | 内容单源；旧导出兼容或删除并更新引用 |
| S3 | 投影 API：工作台 A1 / 考纲 A1 取数切新路径 | 704/702 等价探针；契约 12 字段 |
| S4 | 考纲卡露出 IPA + `/api/a1/vocab` 富字段 | UI + 探针 |
| S5 | `build_workbench_seed` 改为从投影生成 HTML fallback | 幂等字节稳定；G1/G2/G3 仍绿 |
| S6 | 打包三处 + 全量门禁 + 文档回填 | ruff/mypy/pytest/探针/Go |

## 7. 相关 (References)

- ADR-0011 / 0012 / 0013 / 0014（Vault `08-Projects/DeLector/01-ADR/`）。
- `docs/compose/spec/a1-rich-convergence.md`（实施契约与任务）。
- 取证：`lexicon.py`、`lexicon_merge.py`、`a1_workbench_dict.py`、`a1_dict.py`、`database.py`（`_a1_workbench_row` / `_contract_*`）、`tools/build_workbench_seed.py`、`tests/test_a1_workbench_source.py`、`tests/test_vocab_contract_uniform.py`。
