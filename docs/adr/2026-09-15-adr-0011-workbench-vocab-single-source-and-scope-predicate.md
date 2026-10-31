---
title: "ADR-0011: 词库单一真相化与等级判定数据驱动（Workbench 词库数据架构收敛）"
created: 2026-09-15
updated: 2026-09-15
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/data-model
  - topic/frontend
status: stable
audience:
  - architect
  - developer
source: "vault-grill 双镜拷打（用户拍板 Q1=A / Q2=A）"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0011: 词库单一真相化与等级判定数据驱动（Workbench 词库数据架构收敛）

- **状态**: Accepted
- **日期**: 2026-09-15
- **作者**: Lead Socratic Inquisitor（vault-grill 双镜拷打，用户拍板 Q1=A / Q2=A）
- **领域**: 数据模型 / 前端状态 / 服务端 API 契约
- **拷打对象**: 现状三层词库存储（前端 HTML 内联种子 / 服务端正则解析 HTML / `CORE_VOCAB_DB` 数据层）

---

## 1. 背景与问题定义 (Context & Problem Statement)

### 1.1 现状（一手取证）

| 层 | 位置 | 形状 |
|---|---|---|
| ① 前端 | `static/german/workbench.html` 内联 `SEED_WORDS`（`make_seed.py` 注入）+ `CORE_WORD_SEED_IDS`（235 核心词白名单）+ `CORE_CUSTOM_WORDS`（22 条补缺）+ `SEED_ID_ALIASES`（下架 id 归并） | 富结构 `{id:"a1-0001", hw, pos:"V"/"n."/"Präp", gloss, ipa, ex:[{de,zh}], letter, page, tags, custom}` |
| ② 服务端 | `delector/core/database.py:1699` `_load_a1_workbench_words()` **用正则解析 workbench.html** 的三个 `const` JSON 字面量；`:1809` `_load_a2_vocab_words()` 读 `CORE_VOCAB_DB` | 精简 `{id, hw, pos, de, zh, core, cefr}`（A2 另带 `gender/plural`，`de` 恒空串） |
| ③ 数据层 | `CORE_VOCAB_DB = core_dict.py`（~440 手工）⊕ `core_dict_ext.py`（AI 生成 3969） | `lemma -> (cefr, pos, gender, plural, definition_zh)`；实测 A1:459 / A2:974 / B1:1712 / B2:860 / C1:406 |

运行时持久化：localStorage `wb.words.v1` + IndexedDB mirror；`saveWords()` 末尾 `wbsync.push()` → 800ms 防抖 `PUT /api/wb/state`（X-WB-Key）；启动 + 5s 轮询做 stable-diff 后 `applyMerge`（[[08-Projects/lover-instance/LOCAL-FIRST-SHAREABLE-SINGLE-FILE-REPORT]]，远端仅为镜像）。

### 1.2 问题

- **P1 多源真相（最高危）**：A1 词库有 3 个副本（HTML 内联 / `a1_dict.GOETHE_A1_VOCAB` / `core_dict` 的 A1 459 条），内容与 id 语义均不同。服务端**把前端文件当数据库**：`:1716` 用 `re.search(r"const\s+SEED_WORDS\s*=\s*(\[.*?\]);\s*\n", txt, re.DOTALL)` 匹配 HTML 字面量，外层 `except Exception: pass` + `loaded=False` → 一旦字面量被格式化/换行/加注释即匹配失败，**静默回退到 `a1_dict`**（回退路径 id 是重新编号的 `a1-0001..`，与 SEED id 非同一语义），API 与页面词库从此分叉且无测试会红 —— 违反项目红线 1 反对的"静默降级"精神。
- **P2 两套 shape 不对齐**：A1 走 `gloss/ipa/ex[]/tags/letter/page`，A2/B1 走 `zh/de/core/gender/plural`。同一张卡片，A2/B1 无音标、无例句（`de` 空串），信息量低于 A1。
- **P3 等级判定不可扩展**：`workbench.html:1619` `inScopeWord` 把 core/reader/a2/all 四分支挤进一个嵌套三元，A2 判定写成 `w.cefr==="A2" || tags.includes("a2") || id.startsWith("a2-")` 三路 OR 冗余，`all` 分支硬编码排除 A2。**加 B1/B2 须在每处再抄一遍**（Ladder of Reuse 的反面）。
- **P4 A2 特判冗余**：`_load_a2_vocab_words` + 专用缓存的产出与通用分支完全同形（只差 `de` 与缓存），属"加 A2 时忘了回头统一"。
- **P6 无通用迁移**：`wb.words.v1` 内对象无 schema 版本字段，统一 shape 时存量用户对象迁移无方案。

### 1.3 触发点

用户已完成权威 A2/B1 词表整理 → 需要确定的落点；同时 B1（1712 词）**数据层已有但前端零入口**（workbench 仅 core/all/a2/reader 四档，`exam_catalog` 仅注册 A1/A2）。若不先收敛架构，接词表与开 B1 入口会把 P1–P3 同步放大。

## 2. 决策驱动因素 (Decision Drivers)

- **产品镜**：A1→B2 多等级必须可低成本扩张（用户实际水平在推进）；权威词表要有明确落点；各级卡片信息量应大致对齐。
- **工程镜**：消灭"前端文件即数据库"的反模式与静默回退；判定逻辑去分支化，使"加一级 = 改数据"；权威数据进数据模块，前后端同源。
- **复用阶梯（MUST）**：`format_vocab_headword` 单一装饰点、5-tuple schema、分级惰性加载、[[01-Rules/STORED-DATA-BACKFILL]] + 幂等合并、`SEED_ID_ALIASES` 迁移 —— 全部保留复用，不重写。
- **硬约束**：**id 稳定性**——`wb.cards.v1` / `wb.wrong.v1` 以词 id 为键，任何收敛动作不得改变既有 id（否则 FSRS 进度全丢，违反 ADR-0002 的"进度零丢失"）。

## 3. 备选方案 (Considered Options)

### Q1 词库单一真相化

| 方案 | 说明 | 结论 |
|---|---|---|
| **A 搬出去（选定）** | `SEED_WORDS` 从 HTML 迁至数据模块，构建期注入 HTML；服务端 `import` 取代 regex 解析；A1/A2/B1 收敛到一份词对象契约 | ✅ 采纳（用户拍板） |
| B 维持现状 + 守卫 | HTML 仍为源头，仅加"解析失败必须炸"的守卫测试 | ❌ 只把静默变响，多源真相未解 |

### Q2 等级判定去分支化

| 方案 | 说明 | 结论 |
|---|---|---|
| **A 数据驱动（选定）** | 抽 `SCOPE_PREDICATES` 配置表 + `isInScope(w, scope)` / `cefrOf(w)`，消灭嵌套三元与三路 OR | ✅ 采纳（用户拍板） |
| B 沿用嵌套三元 | 加 B1 时再嵌一层 | ❌ 判定路径数随等级线性膨胀 |

## 4. 决策 (Decision Outcome)

**Q1 = A、Q2 = A，合并为一次"词库数据架构收敛"。**

1. **A1 词库单一真相**：新建数据模块（如 `delector/data/a1_workbench_dict.py`）承载 A1 工作台词条（含 `ipa/ex/letter/page/tags/custom` 富字段），由 `make_seed.py`/构建脚本**单向注入** `workbench.html`。服务端 `_load_a1_workbench_words()` 改为直接 `import` 该模块，**删除 regex 解析与 `except: pass` 静默回退**（数据模块缺失 = 启动即失败，与红线 1 一致）。`a1_dict.GOETHE_A1_VOCAB` 降级为"考题语料"，不再充当工作台词库回退源。
2. **统一词对象契约（一份 schema）**：定义 workbench/API 共用字段集（`id, hw, pos, ipa, gloss/zh, ex[], gender, plural, cefr, tags, custom, src`），并明确 A1/A2/B1 三级各自如何填充（缺项显式为空，不留"两套命名"）。`get_vocab_by_cefr` 各分支（含 A2 特判）统一产出该契约后，A2 专用 loader 与缓存可并入通用分支（P4 消除）。
3. **等级判定数据驱动**：`workbench.html` 定义 `SCOPE_PREDICATES`（每 scope 一条声明式谓词）+ `isInScope(w, scope)` + `cefrOf(w)`，替换 `inScopeWord` 的嵌套三元与三路 OR；新增等级只加一行配置。
4. **权威词表落点**：权威 A2/B1 词条写入**数据模块**（`core_dict.py` 手工区优先，可覆盖 `core_dict_ext.py` 的 AI 条目），产出前与现有库做差集审计；cefr 以权威词表为准（不再是 AI 分级）。
5. **打开 B1 入口**：workbench 增设 B1 档位 + `exam_catalog` 注册 B1（服务端 `get_vocab_by_cefr("B1")` 已可用，零新增服务端逻辑）。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

**正面**
- "加一级等级 = 改数据，不改逻辑"，B1/B2 入口成本从"改 5 处"降为"加 1 行配置 + 1 个档位"。
- 消除"正则解析 HTML + 静默回退"这一静默分叉源；词库前后端同源可被测试钉死。
- 权威词表获得明确、可审计、可重复生成的落点；A1/A2/B1 卡片信息量具备对齐条件。

**代价 / 风险**
- 需一次性迁移存量 localStorage 词对象（P6）→ 引入 `normalizeWord()` + 版本化 migrate，**必须在启动路径幂等且失败不损坏数据**。
- HTML 注入链路（make_seed.py / 构建脚本）与数据模块必须保持同步，需守卫测试钉住"注入即数据模块内容"。
- 改动面横跨前端状态、服务端数据加载与测试护栏，必须分批提交、每批零回归。

**防御性规范（MUST）**
1. **id 只增不改**：`a1-0001` 等既有 id 逐字保留；新增/迁移一律走别名表（沿用 `SEED_ID_ALIASES` 机制）。任何改变既有 id 的方案直接否决。
2. **禁止把非数据文件当数据源**：服务端不得从 HTML/JS/CSS 文本中正则提取业务数据；数据只能来自可 import 的数据模块。解析失败不得静默降级。
3. **一份契约**：词对象字段命名唯一（同一语义不得有两种字段名），新增等级不得引入新的字段命名。
4. **判定唯一入口**：scope 判定只经 `isInScope()`；禁止在渲染/队列/自测各处重抄等级判定。
5. **护栏先行**：`tools/wb_queue_probe.mjs` 13 条切片护栏 + `tests/test_german_workbench.py` 在重构期间必须持续全绿零漂移。
6. **存储 schema 冻结（解耦外部词表工作）**：本 ADR 的"统一契约"只作用于**输出侧**（`get_vocab_by_cefr` 产出与前端消费形状）。底层存储 `lemma -> (cefr, pos, gender, plural, definition_zh)` 5 元组在本次重构期**保持不变**；扩展存储字段（如为 A2/B1 补 `ipa` / 例句）须另立 ADR 并配套幂等迁移（id 不变）。目的：让并行的「权威 A2/B1 词表整理」与本次重构完全解耦——词条内容是可迁移资产，格式变更由本项目提供转换器负责。
7. **lemma 即 id、只增不改**：`id = f"{cefr.lower()}-{lemma.lower()}"`（`database.py:1927/1949`），故**修改既有 lemma 拼写 = 修改词 id = 用户 FSRS 进度变孤儿**。发现现有 lemma 有误时，只能（a）保留旧 lemma 并在别名表中记录映射，或（b）新增正确词条而不改旧词条；禁止直接改名。

## 6. 实施顺序（共识，供 /vault-plan 拆解）

1. **T1 词库数据模块化**：A1 工作台词条迁出 HTML（id 逐字保留）→ 构建期注入 → 服务端改 `import` → 删 regex 与静默回退 → 补守卫（缺数据模块即失败）。
2. **T2 词对象契约统一 + migrate**：定义唯一 schema + `normalizeWord()`；存量 localStorage/IDB 幂等升级（id 不变，进度零丢失）。
3. **T3 判定数据驱动**：`SCOPE_PREDICATES` + `isInScope()`/`cefrOf()` 落地；13 条切片护栏零漂移。
4. **T4 权威词表接入 + B1 入口**：权威 A2/B1 写入数据模块（差集审计）→ workbench B1 档位 → `exam_catalog` 注册 B1。
5. **验收门**：全量 pytest 零回归 + `node tools/wb_queue_probe.mjs` 13/13 + 双端（桌面 / Android 覆盖安装）词库与进度可见。

## 7. 相关 (References)

- ADR-0001（核心词模式，`CORE_WORD_SEED_IDS` 的来源与语义）；ADR-0002（scope 控制 + "进度零丢失"硬约束）；ADR-0005（多等级可扩展 / `exam_catalog` 目录注册）。
- 现状取证：`delector/core/database.py:1699–1960`、`static/german/workbench.html:828–1119 / :1619 / :3049–3164`、`delector/services/exam_catalog.py`、`tools/build_dict.py`。
- 权威词表整理规范：见 `.codebuddy/memory/2026-09-15.md`「给其他 agent 的提示词」节。
