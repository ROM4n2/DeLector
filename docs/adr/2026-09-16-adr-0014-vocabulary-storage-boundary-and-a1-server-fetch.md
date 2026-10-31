---
title: "ADR-0014: 词表存储边界与 A1 取数统一（词表不入库 + 内联种子 API 化）"
created: 2026-09-16
updated: 2026-09-16
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/data-model
  - topic/storage
status: stable
audience:
  - architect
  - developer
source: "ADR-0012（主干分层）/ ADR-0013（富字段契约）后续：用户提问「A1 能否统一走服务端」「词表要不要进 SQL」，并伴随 Task A 富字段回填落地"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0014: 词表存储边界与 A1 取数统一（词表不入库 + 内联种子 API 化）

- **状态**: Accepted
- **日期**: 2026-09-16
- **领域**: 数据存储边界 / 前端首装路径 / 同步语义
- **上游**: ADR-0011（5 元组存储冻结 / id 只增不改 / 整表契约）、ADR-0012（主干唯一入口 + 来源优先级）、ADR-0013（11 字段输出契约 + 富字段 side-car）
- **关联提交**: `32a8f0f`（Task A：A2/B1 富字段回填，固化本 ADR §4-3 的同步语义）

---

## 1. 背景与问题定义 (Context & Problem Statement)

### 1.1 现状（实测）

**词表数据（只读 / 版本化）全部在代码数据模块，经主干组装后由 API 下发**：

```
delector/data/a1_workbench_dict.py     A1 seed 682 + custom 22 + core_ids 213（富结构：id/ipa/ex）
delector/data/official_vocab.py        官方 5 元组 A1 660 / A2 736 / B1 1617（合并视图 2732）
delector/data/official_vocab_rich.py   官方富字段 A1 660 / A2 736 / B1 1617（ipa / example_de / example_zh）
delector/data/core_dict*.py            手编 443 + AI 3968
                ↓ delector/core/lexicon.py（主干：字段级合并 + rich_of 单入口）
        /api/cards/vocab · /api/a2/vocab · /api/a1/vocab
```

**用户/行为数据（可变 / 事务）在 SQLite**：

```
delector.db     articles / encounter_texts / app_settings（API key、wb_sync_key）/ wb_state 镜像
progress.db     FSRS 卡片进度 / 学习日志 / 每日统计 / 错题
```

**A1 在前端还有一份内联运行期副本**：`static/german/workbench.html` 内的 `SEED_WORDS`（682 条，124,464 字符）+ `CORE_WORD_SEED_IDS`(213) + `CORE_CUSTOM_WORDS`(22)，由 `tools/build_workbench_seed.py` 注入，并由 `tests/test_a1_workbench_source.py` 做"模块 ↔ HTML 逐字一致"守卫。

**关键实测（决定本 ADR 可行性的前提）**——服务端**早已完整提供 A1，且 id 与内联副本同源**：

```
get_vocab_by_cefr("A1", scope="all")   → 704 条（seed 682 + custom 22）
    id: a1-0001 … core-022     704/704 带 de(德例句) + example_zh + ipa
get_vocab_by_cefr("A1", scope="core")  → 235 条（213 + 22），同样 235/235 全覆盖
```

### 1.2 问题

- **P1 双副本纪律面**：A1 数据改一次要"改模块 + 重跑注入脚本"两步（PR #56 改 IPA 即需重注入 HTML），漏跑即**静默漂移**，只能靠"逐字一致"守卫兜底。
- **P2 取数路径不统一**：A1 为「内联常量同步建表」，A2/B1/reader 为「API 异步填充」——同一件事两种机制，缺陷只能逐条治。
- **P3 同步语义隐式**：服务端 → 本地原为 **append-only**（`if (!existingIds.has(wid))` 无 else）→ 存量词条永久冻结在首次同步的状态，导致"A2/B1 只有部分词有例句"（已于 `32a8f0f` 修为"只补空"，但该语义此前**无书面规范**）。
- **P4 存储边界无决策记录**：词表为何不放 SQLite、将来何时才该放，全无 ADR；后人（或 AI）极易"顺手把词表搬进数据库"。

## 2. 决策驱动因素 (Decision Drivers)

- **数据性质决定存储介质**：词表 = 不可变 + 版本化 + 全量读 + 随发布走；行为数据 = 可变 + 事务 + 增量查询 + 用户产生。
- **可审计**：词表变更应当能 `git diff` 逐条审阅、CI 静态校验；入库则丧失这一能力。
- **零依赖启动**：桌面/Android 单机自用，词表不应引入"初始化数据库/迁移脚本/资源复制"这类启动期不确定性。
- **唯一取值入口**（ADR-0012 §5-1）：消费端只经主干，禁止再建副本。
- **id 不变式**（ADR-0011 §5-6）：`a1-NNNN` / `core-NNN` 是 FSRS 进度键，且 `SEED_ID_ALIASES` 依赖其稳定性。
- **首装可用性**：程序内起服务（桌面 `start.py` / Android Chaquopy），但服务未起或异常时不得白屏。
- **可测守线**：行为语义要能被探针真跑钉住（本项目既有 node 切片探针范式）。

## 3. 备选方案 (Considered Options)

- **Option A：把词表搬进 SQLite（作为运行时真值）**
  - 👍 运行时可改词库、无需发版；支持增量/条件查询；存储层"看起来"统一。
  - 👎 收益（不发版改词库）在单用户 + CI 高频发版场景**不成立**；代价是 schema 迁移、初始化/资源复制、Android 打包、冷启动与缓存一致性；**失去 git diff 审阅与 CI 静态校验**；与"词表随版本走"的既有语义冲突（用户升级程序即升级词表）。
- **Option B（选定）：词表留在代码常量，取数统一到服务端 API，首装用本地缓存**
  - 👍 单一真相 + 唯一入口；删掉内联副本与"逐字一致"守卫这一整套复杂度；A1/A2/B1 完全同构（同一同步机制、同一缺陷面）；离线能力改由**缓存**提供，而非内联副本。
  - 👎 首装从"同步建表"变"异步填充"（须错误态 + 缓存）；一次性重写 10+ 守卫与 2 个 node 探针；`file://` 直接打开不再可用（本已有 http 守卫，属半失效）；Android 需覆盖安装。
- **Option C：维持现状，只固化同步语义**
  - 👍 零风险，改动极小。
  - 👎 双副本长期存在，注入脚本永远是发布纪律的一环；A1 与 A2/B1 机制分叉长期存在，缺陷需逐条治。

## 4. 决策 (Decision Outcome)

**选定 Option B。**

1. **存储边界（明确规定）**
   - **代码数据模块**承载：不可变、版本化、全量读、随发布走的数据 → **词表**（含 A1 富结构、官方 5 元组、富字段 side-car）。
   - **SQLite**承载：可变、事务、增量查询、用户产生的数据 → 学习进度、学习日志、文章/短文、设置、同步密钥、`wb_state` 镜像。
   - **唯一允许的例外**：当词表规模或检索需求超出"内存全量读"能力（例如需要按屈折变体/例句语料全文检索）时，**允许 SQLite FTS5 作为派生索引**——从代码常量构建、可随时重建、**源头仍为代码常量**。
   - **MUST NOT**：把词表源头写入 SQLite 并作为唯一真值（禁"源头入库"）。
2. **A1 取数统一（内联种子 API 化）**
   - 前端首装改为调用服务端：`GET /api/cards/vocab?cefr=A1&scope=core|all`（服务端已提供 704/235，id 与契约同源）；
   - **首装成功后缓存到 localStorage**——离线能力由**缓存**承担，不再由内联副本承担；
   - **id 契约逐字不变**：`a1-NNNN` / `core-NNN`，`SEED_ID_ALIASES` 语义与 FSRS 进度键不受影响；
   - 首装失败必须给出**显式可恢复态**（不得白屏），下一轮成功即自愈。
3. **词表同步语义（固化 `32a8f0f`）**
   - 服务端 → 本地词表同步 MUST 为「**只增 + 只补空字段**」：新 id 走新建分支；**已存在词条仅回填空字段**（`ex` / `ipa`，B1 另含 `gender` / `plural`）；
   - **MUST NOT 覆盖非空字段**——保护用户手编的例句/音标/释义；
   - MUST **幂等**（二次进入该档 `changed === false`，不写盘）；
   - **MUST NOT 触碰 `cards` / `log` / `wrong`**（FSRS 进度红线），回填只动词表。

**明确不做（scope 控制）**：不动 5 元组存储 schema；不改 11 字段输出契约（ADR-0013）；不引入 SQLite 词表/FTS5（仅在 §4-1 保留未来例外路径）；不做 A1 与 `GOETHE_A1_VOCAB` 的数据合并（ADR-0012 Phase 2 另一支，另议）。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

🟢 **正面**：A1/A2/B1 取数与同步机制完全同构（缺陷面收敛为一处）；删除"注入脚本 + 逐字一致守卫"这套纪律面；词表/行为数据的存储边界书面化，杜绝"顺手搬进 SQL"；离线能力改由缓存提供，语义更清晰（缓存可失效可重建，副本不可）。

🔴 **代价与缓解**：
- 首装依赖本地服务 → 以 localStorage 缓存 + 显式失败态缓解；
- 一次性重写守卫与探针（`tests/test_german_workbench.py` / `tests/test_a1_workbench_source.py` / `tools/wb_queue_probe.mjs` / `tools/wb_merge_probe.mjs` / `tools/build_workbench_seed.py`）→ 由 `/vault-exec` 分步实施，每步带回归；
- **改动含 `static/` → Android 必须覆盖安装**。

**防御性规范（MUST）**

1. **词表源头不入库**：SQLite 只存行为/进度；FTS5（若引入）仅作派生索引，须可从代码常量重建。
2. **唯一取值入口**：消费端只经 `lexicon`（ADR-0012 §5-1 延续），禁止直连 `official_vocab*` / `core_dict*` / `a1_workbench_dict`。
3. **id 只增不改**：`a1-NNNN` / `core-NNN` 契约稳定；下架须经 `SEED_ID_ALIASES` 迁移进度（ADR-0011 §5-6 延续）。
4. **同步语义钉死**：任何"服务端 → 本地词表"同步 MUST 满足「只增 + 只补空 + 幂等 + 不碰 FSRS」，并由**行为级探针**（真源码切片 + node 真跑）覆盖，且探针 MUST 接入 pytest（CI 必跑，不得只留命令行脚本）。
5. **首装可恢复**：首装失败必须有显式错误态与重试路径，不得白屏或静默空词表。
6. **打包同步**：新增/删除数据模块 MUST 同步 `package_windows.py` / `build-release.yml` / `tests/test_server.py::data_dict_modules`（承接 ADR-0012 §5-7）。
7. **契约 11 字段不破**：本 ADR 不改输出契约；如需变更另立 ADR（承接 ADR-0013 §5-2）。

## 6. 实施顺序（S1–S4，供 `/vault-exec`）

> §4-3（同步语义）与 §5-4（探针进 CI）**已完成** —— 见 `32a8f0f`。§4-2（A1 取数统一）待实施，分四步。
>
> **实施前实测校正（2026-09-16）**：
> ① 服务端 A1 704 条与内联 seed 682 条在 `id / hw / pos / gloss(=zh) / ipa / de / example_zh` 上**逐条等价**，内联独有 0 条（682 ⊂ 704，多出的 22 条即 `core-*` custom）。
> ② **`letter` 存在 10 条静默漂移**：内联值与前端 `letterOf(hw)` 派生值不一致（`a1-0462/0466` `O`↔`Ö`、`a1-0602` `U`↔`Ü`、`a1-0349` `K`↔`-`、`a1-0034/0052/0067/0547` `A`↔`S`）→ **必须由服务端下发 `letter`**，否则字母分组会静默变化（违反 ADR-0011「输出逐条不变」纪律）。
> ③ **`page` 是 write-only**（`workbench.html` 全文无读取点，仅见注释文字）→ 首装不再携带，前端恒写 `0`。
> ④ **`CORE_WORD_SEED_IDS`(213) 与 `SEED_ID_ALIASES`(2) 不删**（修正初稿）：前者是存量词 `core` tag 补丁的轻量数据（~2.5KB），后者是"历史下架 id → 保留 id"进度迁移的**唯一来源**，服务端均不承载该语义；二者与 124K 字符的 `SEED_WORDS` 不是同一量级的负担。
> ⑤ `CORE_CUSTOM_WORDS`(22) 可删：服务端 704 条已含 `core-001`…`core-022`（`core: true`）。

| # | 内容 | 前置 |
| --- | --- | --- |
| **S1** | **服务端下发 `letter`**：`_a1_workbench_row` 透传 seed 的 `letter` 原值；A2/B1/reader 分支填**与前端现行派生逐字一致**的 `hw[0].toUpperCase()`；输出契约 **11 → 12 字段**（+`letter`，本 ADR 授权；同步 `test_vocab_contract_uniform.py` / `test_vocab_sources.py` / `test_a1_workbench_source.py` 的字段集守卫） | — |
| **S2** | **前端首装 API 化**：无本地词表 → `GET /api/cards/vocab?cefr=A1&scope=all` → 按旧内联口径建表（`tags` 由服务端 `core`/`cefr` 派生、`letter` 取服务端、`page: 0`、逐条过 `normalizeWord`）→ 落 localStorage 缓存 + `wb.schema.v1` 标记；**失败回退内联种子 + 显式可恢复提示**。等价性由探针钉住（首装结果逐字段 == 旧内联建表结果） | S1 |
| **S3** | **内联副本降级为"离线 fallback"、不删**（2026-09-16 裁决：与 ADR-0011 的 `file://` 离线保证冲突，见下）：`SEED_WORDS`(682 / 124,464 字符) 与 `CORE_CUSTOM_WORDS`(22) **保留**，但**仅**在「非 http（`file://` 直开）或服务端不可用」时由 `bootstrapA1Words()` 兜底调用；`loadAll()` **不得**再同步建表。等价性由探针（**704 vs 704 全字段**）钉住，漂移即红。新增守卫：① `loadAll` 函数体内不得出现 `SEED_WORDS.map(` / `a1WordsFromInline()`；② 全文件 `a1WordsFromInline(` **恰 2 处**（1 定义 + 1 调用）且调用点必须落在 `bootstrapA1Words` 的函数体切片内；③ 两个内联常量头注释标注「**离线 fallback，非数据源**」+ 指向本 ADR | S2 |
| **S4** | 收口：分半全量门禁 + worktree A/B、`PROJECT_OVERVIEW` / `CHANGELOG` / 本 ADR 状态回填、**Android 覆盖安装点检**（A1 五档可见 / 例句音标齐 / 进度零丢失 / 字母分组一致） | S3 |

## 7. 相关 (References)

- **上游**：ADR-0011（5 元组冻结 / id 只增不改）、ADR-0012（主干分层 / 来源优先级 / 单入口）、ADR-0013（11 字段契约 / 富字段 side-car）。
- **本 ADR 依据的实测**：`get_vocab_by_cefr("A1", scope=...)` → 704 / 235，id `a1-0001`…`core-022`，704/704 富字段齐全；`RICH` 2722（A1 660 ∪ A2 736 ∪ B1 1617）；官方 A2 视图 736 → 例句命中 732（4 条源缺：`disko`/`ehepartner`/`rentnerin`/`vermieterin`，不编造）。
- **取证代码**：`delector/core/lexicon.py`、`delector/core/database.py`（`_a1_workbench_row` / `_load_a1_workbench_words` / `_contract_from_core_entry`）、`static/german/workbench.html`（`sync{A2,B1}CardsFromServer` / 首装分支）、`static/js/a1_cards.js`、`tools/build_workbench_seed.py`、`tools/wb_rich_backfill_probe.mjs`。
- **关联提交**：`32a8f0f`（A2/B1 富字段回填 + 空例句块条件渲染 + 探针进 CI）。
