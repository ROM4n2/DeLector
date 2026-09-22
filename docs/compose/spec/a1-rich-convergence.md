---
feature: a1-rich-convergence
status: delivered
updated: 2026-09-21
branch: feature/a1-rich-convergence
commits: # filled at delivery
---

# A1 Rich Convergence

## Report

**What was built** — A1 内容从三源双写收敛为「FRAGMENTS 单源 + membership side-car」：
`lemma_key` 唯一切分；`workbench-a1`/`goethe-a1` 进入 `lexicon.FRAGMENTS` 与 RICH（字段级**只补空**）；
身份层（FSRS `a1-NNNN`/`core-*`、`letter` 原值、GOETHE 成员序/topic、custom22）保留在 `a1_sidecar`。
工作台 A1 继续按 id 逐条回放（704/235，同形异义 `bitte`/`essen`/`leben`/`sie` 不丢）；考纲 A1 投影 702 条并新增 `ipa`，卡片渲染音标。
HTML `SEED_WORDS` 降为构建产物（`build_workbench_seed` 从投影注入，幂等）。

**Verification** — `pytest tests/` **1081 passed + 1 skipped**；`ruff check delector tools tests` 0；
`mypy --strict delector tools` 0；`agent/` gofmt/vet/`go test -race` 8 包全绿；`tools/*.mjs` 探针 **16/16**；
工作台 704 条 id/letter/字段与迁移前逐条等价（人工快照核对）；`CORE_VOCAB_DB == LEXICON`（4867）。

**Journey log**
1. 成员集合 seed∩GOETHE≈391，否决「一张主干表投影两边」——完整派生是伪需求。
2. GOETHE `plural` 是完整形（`die Abfahrten`），不得写入 5 元组**后缀位** → `plural` 优先级保持 manual>official。
3. 同形异义 lemma 不能承载 FSRS 行内容 → membership 必须逐 id 带 `ipa/ex`。
4. 主干字面量 `"None"` 是无性别哨兵（契约层归一化），合并层不得当空滤掉。
5. 独立评审 subagent 超时取消；以关键不变式自审 + 全量门禁替代（Journey 记录 impasse）。

## [S1] Problem

A1 词表内容三源并存且**成员集合不同**（实测 seed 700 key / GOETHE 702 / 交集 **391**；GOETHE-only 311 / seed-only 309）：

- `A1_WORKBENCH_SEED`(+CUSTOM) 与 `GOETHE_A1_VOCAB` 对共享词双写 ipa/例句/释义；
- 考纲 A1 卡无 IPA，与 A2/B1 字段面不齐；
- 改一处词常要「改数据模块 + 重跑 HTML 注入」两步，漏跑靠逐字守卫兜底。

ADR-0013/0014 明确 defer 的「派生收敛」不能做成「一张主干表投影两边」——集合分叉 + FSRS `a1-NNNN` id + 10 条人工 `letter` 原值使完整派生不可行。真实需求是 **消内容双写 + 字段对齐**，不是重做 id 空间。

## [S2] Design

### 2.1 目标拓扑（ADR-0015）

```
FRAGMENTS (provenance: workbench-a1 | goethe-a1 | official | manual | ai)
    → lexicon_merge.FIELD_PRIORITY（内容字段，只补空）
    → LEXICON / RICH
         ├─ + WORKBENCH_MEMBERSHIP(id,lemma,letter,page) + CUSTOM_22 + CORE_IDS + SEED_ID_ALIASES
         │    → 工作台 A1 投影（id=a1-NNNN / core-NNN，letter 原值，12 字段契约）
         └─ + GOETHE_MEMBERSHIP(lemma 有序) + GOETHE_TOPICS(lemma→topic)
              → 考纲 A1 投影（lemma 键，+ipa 等富字段）
```

HTML 内联 `SEED_WORDS` = 投影的**构建产物**（`file://` fallback），非数据源。

### 2.2 `lemma_key`（唯一切分实现）

放置：`delector/data/lexicon_merge.py`（或 `delector/core/lexicon.py` re-export）。**禁止第二份。**

规范化步骤（顺序固定，带单元测试钉死）：

1. 去 `(sich)` / `(sich …)` 前缀；
2. 去前置冠词 `der|die|das|ein|eine`（大小写不敏感）；
3. 去逗号后屈折/复数尾巴（`die Adresse,-en` → `Adresse`）；
4. 去尾部孤立连字符（`all-` → `all`）；
5. 空白折叠为单个连字符后转小写（`an sein` → `an-sein`，与 official 一致）；
6. 已是 lemma 的键（GOETHE dict key / official）原样走 1–5（幂等）。

**验收**：用该函数对 seed∪custom 与 `GOETHE_A1_VOCAB` 求交，**恰 391**；全函数幂等；无第二实现（探针或 AST 守卫可选）。

### 2.3 字段权威序（`lexicon_merge` 扩展）

内容字段（进 LEXICON/RICH，**只补空、非空永不覆盖**）：

| 字段 | 优先级（高→低） |
|---|---|
| `ipa` | `workbench-a1` > `goethe-a1` > `rich` > 其它既有 |
| `example_de` / `example_zh`（含多对） | `workbench-a1` > `goethe-a1` > `rich` > 其它 |
| `gender` / `plural` / `def_zh`/`zh` | `goethe-a1` > `official` > `workbench-a1` > `A1_LEMMA_META` > `ai` |

展示层字段（**view-owned**，不参与跨视图强行统一）：

| 字段 | 工作台 A1 | 考纲 A1 |
|---|---|---|
| 表层词形 | seed `hw`（含冠词/构词横线） | GOETHE `word` |
| `pos` 标签 | seed 原值（`Präp`/`V`/`f.`） | GOETHE 原值（`PREP`/`NOUN`） |
| `letter` / `page` | membership **原值** | n/a |
| `topic` | n/a | `GOETHE_TOPICS` |

IPA 全局去 tie-bar（延续 ADR-0013）。

### 2.4 Side-car（不可派生，显式保留）

| 常量 | 规模 | 说明 |
|---|---|---|
| `WORKBENCH_MEMBERSHIP` | 682 | `{id, lemma, letter, page}`，id/letter **逐字不变** |
| `A1_WORKBENCH_CORE_IDS` | 213 | 语义不变 |
| `A1_WORKBENCH_CUSTOM` / `CUSTOM_22` | 22 | `core-*` 全量条目（官方 A1 不含） |
| `A1_WORKBENCH_ID_ALIASES` | 2 | 进度迁移不变 |
| `GOETHE_MEMBERSHIP` | 702 | 有序 lemma 列表 |
| `GOETHE_TOPICS` | 702 | `lemma→topic` |

`a1_workbench_dict.py` / `a1_dict.py` **保留模块名**（打包 hiddenimports / `data_dict_modules` 冻结清单兼容），瘦身为 side-car + 必要 re-export；内容字典迁出。

### 2.5 投影契约

**工作台 A1**（`get_vocab_by_cefr("A1")` / `_contract_item` A1 分支 / `/api/cards/vocab?cefr=A1`）：

- 输出 **12 字段**严格相等：`{id,hw,pos,gender,plural,de,zh,ipa,example_zh,core,cefr,letter}`；
- `id` = membership（`a1-0001`…`core-022`）；`letter` = membership 原值（禁 `letterOf`）；
- `scope=all` **704**、`scope=core` **235**；`hw`/`ipa`/`de`/`example_zh` 与迁移前逐条等价（见 2.7）；
- 多对 `ex` 保留于工作台词条源；契约 `de`/`example_zh` 仍取约定主对（与现状一致）。

**考纲 A1**（`GET /api/a1/vocab`）：

- 仍按 `GOETHE_MEMBERSHIP` 顺序；键/字段含 `topic,word,lemma,pos,gender,plural,definition_zh,example_de,example_zh` **且新增 `ipa`**；
- `ipa` 优先取 workbench-a1 人工值，否则 rich/其它；缺则 `""`（禁止编造）；
- `exam_catalog` `count_fn` = `len(GOETHE_MEMBERSHIP)`（702）。

### 2.6 前端

- `a1_cards.js` 考纲 A1 卡渲染 `ipa`（对齐 A2/B1 字段面）；空串不渲染孤立标签。
- 工作台首装/内联 fallback / G1–G3 / `normalizeWord` / `wb.schema.v1` / `SEED_ID_ALIASES` **行为不变**。
- 改动含 `static/` → **Android 需覆盖安装**（交付说明必写）。

### 2.7 等价与守卫

| 守卫 | 验收 |
|---|---|
| 投影等价 | 迁移前后工作台 704 条在 `id,hw,pos,gloss/de,ipa,example_zh,letter,core` 逐条相等；考纲 702 条除新增 `ipa` 外逐条相等 |
| 字段优先级 | 冲突胜出 / 空补非空不覆盖 / 确定性（两次调用同结果） |
| `lemma_key` | 交集=391；幂等；样本含 `die Adresse,-en`、`all-`、`(sich) anmelden`、`an sein` |
| 契约 | `test_vocab_contract_uniform` 12 字段**严格相等** |
| 内联纪律 | G1/G2/G3 仍绿；`build_workbench_seed` 幂等字节稳定 |
| 打包 | `package_windows.py` / `build-release.yml` / `test_server.py::data_dict_modules` 与数据模块清单一致 |
| 门禁 | `pytest` 全量、`ruff`、`mypy --strict delector tools`、`tools/*.mjs` 探针、Go 三件套 |

### 2.8 错误行为

- 投影缺 membership 映射 → **抛错**（不静默丢词）；测试/构建期即红。
- 内容字段全源为空 → 显式空串/None，不回退编造。
- HTML 注入源缺失 → 构建脚本非零退出。

## [S3] Out of Scope

- `a1-NNNN` ↔ official/lemma id 重映射或 FSRS 键空间变更；
- 12 字段输出契约的字段集变更；
- SQLite 词表 / FTS5；
- A2/B1 成员逻辑（已收敛）；
- `SEED_ID_ALIASES` 语义变更；
- 考纲卡 UI 除 IPA 外的改版；GOETHE `topic` 信息架构调整；
- 预置 encounter 包 gloss 富化、检索 `_highlight` 边界（另案）。

## Tasks

- [x] T1: 扩展 `lexicon_merge` 字段优先级（ipa/example_* + gender/plural/zh 序）与 `lemma_key` 唯一实现 — acceptance: 单元测试覆盖冲突/只补空/幂等/lemma_key 样例与交集=391；无第二 lemma_key (covers: S2.2; S2.3)
- [x] T2: seed/GOETHE 内容迁入 FRAGMENTS provenance，side-car 收敛为 membership/topic/custom22/core_ids/aliases — acceptance: `a1_workbench_dict`/`a1_dict` 仅 side-car+re-export；内容字典单一；打包清单仍可收集 (covers: S2.1; S2.4; depends: T1)
- [x] T3: 工作台 A1 与考纲 A1 取数切投影路径 — acceptance: 704/235 与 702 顺序/字段等价探针绿；契约 12 字段；id/letter 来自 membership (covers: S2.5; S2.7; depends: T2)
- [x] T4: `/api/a1/vocab` 下发 `ipa` 且考纲卡渲染 IPA — acceptance: 空值不渲染孤立标签；UI/API 行为测试或探针绿 (covers: S2.5; S2.6; depends: T3)
- [x] T5: `build_workbench_seed` 改为从投影生成 HTML fallback — acceptance: 两次运行字节一致；G1/G2/G3 与 HTML↔投影等价守卫绿 (covers: S2.1; S2.7; depends: T3)
- [x] T6: 打包三处/冻结清单同步 + 全量门禁 + 文档（CHANGELOG/PROJECT_OVERVIEW/本 Report） — acceptance: pytest/ruff/mypy/探针/Go 全绿；Android 覆盖安装提示写入交付说明 (covers: S2.7; S2.8; depends: T4; T5)
