# 词卡重复缺陷：合并与唯一约束方案（方案稿，不实施）

> **Goal**: 给出 `vocab_cards` 同一词多卡的**完整处置方案**——先量化重复规模，再列三种合并策略的代价，最后写清「统计 → 备份 → 合并 → 建唯一索引 → 写入改 upsert」的迁移顺序与回滚。**本计划不写 DDL、不改写入路径**，只等裁决。
> **Tech Stack**: FastAPI + SQLite（本机 3.43.1）；后端 `delector/routes/cards.py` / `delector/core/vocab_pool.py` / `delector/core/db/schema.py`；备份 `delector/core/db/backup.py`；原生 ES Module 前端。
> **Spec Reference**: `docs/plans/archive/2026-11-08-wordcard-review-state-ledger.md`（读侧去重台账，#307）；`docs/agents/architecture.md`「DB schema / 卡盒 DSR 双路径」；`docs/README.md` §分层。
> **Global Constraints**:
> - **不猜数据规模**：本机没有的数据一律写「未统计」并说明为什么，不得用「大概」「应该」。
> - **不替用户做策略选择**：三种合并策略的后果并列，只给判定依据。
> - 任何写库动作（迁移/合并/建索引）都必须是**显式授权后才运行**的独立工具，默认 dry-run；服务启动路径不得静默改用户数据。
> - 合法多卡（同一 lemma、不同 `word`，如介词搭配）不得被唯一键一刀切禁掉。
> - 读侧 `GET /api/cards/vocab?scope=reader` 的 12 字段契约不动；`tests/test_vocab_contract_uniform.py` 用 `set(w.keys()) == CONTRACT_FIELDS` 钉死，**不放松**。
> - 本计划 PR 只含本文档，不改 `delector/`、`static/`、`tests/`。

---

## 0. 摘要：现在能确定什么、还缺什么

| 项目 | 结论 |
|---|---|
| 重复是否真实存在 | **是**。`vocab_cards` 的 `word` / `lemma` 无 UNIQUE，`POST /api/cards/vocab` 是裸 INSERT（`delector/routes/cards.py:176-202`）；前端注释自己写明「重复不会被拦」（`static/js/cards.js:1227-1231`）。 |
| 重复规模 | **未统计**。本机 `delector.db` 的 `vocab_cards` 为 **0 行**、`wb_state` 为空；`progress.db` 无 `vocab_cards`。本机是开发检出，不是用户真实学习库，无法据此推断。统计 SQL 与只读运行方式见 §2。 |
| 唯一键能否只用 `lemma` | **不能**。介词搭配天然是「同 lemma 多卡」：`bestehen auf / aus / in` 的 `lemma` 都是 `bestehen`（`static/js/reader.js:989-1008`、`static/js/cards.js:1409-1438`）。`UNIQUE(lemma)` 会把合法用法判成冲突。 |
| 是否需要备份 | **取决于策略**。策略 A/B 物理删除后无法从表内恢复，只能靠迁移前快照；策略 C（逻辑合并）可逆，备份非必需。见 §3/§4。 |
| 最需要先拍板的两件事 | ①「同一词」的同一性口径：原始 `lemma` 还是 `lemma_key`（见 §5.1）；②唯一键列集合（见 §5.2）。 |

---

## 1. 现状核实（master `af509dcd`，2026-11-09）

### 1.1 写入路径（4 处生产代码）

| 入口 | 位置 | 去重现状 |
|---|---|---|
| `POST /api/cards/vocab` | `delector/routes/cards.py:176` | **裸 INSERT**，10 列，无 `ON CONFLICT`，写入前不查重。前端 6 个存词入口全部打这一个端点：正文点词（`reader.js:946`）、介词搭配（`reader.js:1001`）、A1 卡盒（`a1_cards.js:753`）、听力芯片（`a1_hoeren.js:547`）、介词矩阵（`cards.js:1422`）、遇见区（`encounter.js:1207`）。 |
| 工作台投影 `_insert_row` | `delector/core/vocab_pool.py:148-173` | **已按 `lemma_key` 去重**：`_pool_index()` 在投影前建「归一键 → 行」映射，撞行规则确定（`raw == lemma_key` 优先，其次最小 `id`，`vocab_pool.py:232-258`）。这条路径不是重复来源，但它的口径与读侧台账不一致（§1.5）。 |
| 伴学提案落卡 | `delector/services/companion_proposal.py:252-260` | 按提案批次 INSERT，跨批次不查重 → 同一词多次采纳会重复。 |
| 前端会话内防重 | `static/js/cards.js:1227-1231` 的 `_prepSavedKeys` | 只在当前会话有效；刷新/重进后失效，注释明确「裸 INSERT，重复不会被拦」。 |

### 1.2 表结构与索引

`delector/core/db/schema.py:170-198`：

```sql
CREATE TABLE IF NOT EXISTS vocab_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER, word TEXT NOT NULL, lemma TEXT NOT NULL,
    pos, gender, plural, cefr_level, definition_zh NOT NULL, sentence_context NOT NULL,
    mastered INTEGER DEFAULT 0, mastered_at TIMESTAMP,
    correct_count, wrong_count, due_date, interval_days, ease_factor, repetition_count,
    source TEXT DEFAULT 'user', fsrs_s REAL, fsrs_d REAL, fsrs_lapses INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

现有索引（`schema.py:389-403` + 真实库 `PRAGMA index_list` 复核一致）：`idx_vocab_srs(mastered, due_date)`、`idx_vocab_queue(mastered, wrong_count DESC, id DESC)`、`idx_vocab_article(article_id)`。
**没有 `lemma` / `word` 索引** → 按 lemma 分组统计、按 lemma 查代表卡在真实库上是全表扫描（见 §2.3）。

### 1.3 读侧现状

- `GET /api/cards` 返回**全部行**，前端卡盒按行渲染 → 重复卡在卡盒里就是两张卡（`cards.py:229-248`）。
- `GET /api/cards/counts` 直接 `COUNT(*)` → 角标把重复卡算两次（`cards.py:251-274`）。
- `GET /api/cards/known-lemmas` 用 `DISTINCT lemma`（`cards.py:278-292`）→ 只影响「已认识」判定，重复不放大。
- 抽屉台账 `GET /api/cards/vocab/ledger/{lemma}` 已做读侧去重（#307，`cards.py:295-365`），代表卡定序 `last_signal_day DESC, created_at DESC, id DESC`，并在 `card_count > 1` 时显示「共 N 张」。

### 1.4 合法多卡（必须保留的情形）

| 情形 | `word` | `lemma` | 说明 |
|---|---|---|---|
| 介词搭配 | `bestehen auf` / `bestehen aus` / `bestehen in` | 都是 `bestehen` | 三条意思完全不同的卡，用户明确要分开背（`reader.js:979-988` 注释）。 |
| 同词不同来源 | `die Wohnung`（听力） / `Wohnung`（正文） | 去冠词后都是 `Wohnung` | `a1_hoeren.js:552` 的 lemma 去了冠词，`word` 保留冠词。 |
| 同一搭配不同格 | `sich freuen auf` | `freuen` | 格只进释义后缀 `(+Akk)`，不进 `word`（`cards.js:1416-1419`）。 |

结论：**任何唯一键都必须包含 `word`（或等价卡面键），不能只用 `lemma`。**

### 1.5 两套「同一性」口径并存（既存缺陷）

| 位置 | 口径 | 代码 |
|---|---|---|
| 抽屉台账（读侧去重） | 原始 `lemma` 精确相等（SQL `WHERE lemma = ?`） | `cards.py:322` |
| 工作台投影（写侧去重） | `lemma_key()` 归一（小写、去冠词、空白折叠为 `-`） | `vocab_pool.py:251`、`delector/data/lexicon_merge.py:94-109` |

后果：`POST /api/cards/vocab` 原样写入用户/前端给的 `lemma`（可能 `Haus` / `haus` / `Häuser` 并存），台账按原始串查会**看不到**另一形态的卡；工作台按归一键又会把它们当同一词。这是本方案必须先统一的口径，否则「合并到一张」之后仍然会从另一形态再长出一张。

### 1.6 外部软引用（无外键）

| 引用 | 形式 | 物理删除重复卡后的后果 |
|---|---|---|
| `quiz_log.card_id` | 整数，无 FK（`schema.py:58-65`，索引 `idx_quiz_card`） | 指向被删 id 的历史答题变孤儿；按卡统计口径失真。 |
| `study_log.ref_id` | 整数 + `event_type`，无 FK（`schema.py:51-57`） | `add_card` / `master_card` 事件指向被删 id，历史事件失真。 |
| `wb_state.payload` | 单行 JSON，卡状态按 `str(word_id)` 为键（`vocab_pool.py:131-135`） | 被删 id 的工作台 FSRS 状态（`s/d/lapses`）丢失 → 用户复习进度倒退。 |

---

## 2. 重复规模统计

### 2.1 本机实测（只读）

已用 `sqlite3.connect('file:<db>?mode=ro', uri=True)` 对 `delector.db` / `progress.db` 只读扫描，**未写任何数据**：

```
delector.db   vocab_cards total_rows = 0
              索引 = idx_vocab_article, idx_vocab_queue, idx_vocab_srs（均非唯一）
              wb_state = 空
progress.db   无 vocab_cards 表（只有 quiz_log / study_log / daily_summary 等）
```

**结论：本机未统计出重复（分母为 0）**。原因不是「没有缺陷」，而是这份检出里没有任何词卡——用户真实学习库不在本机（或 `DELECTOR_DATA_DIR` 指向别处、数据在 Android 端）。**不接受**把 0 当「缺陷不存在」的证据。

### 2.2 可直接在真实库运行的统计口径

以下 SQL 只读、只用现有列。`lemma_key` 是 Python 函数，SQL 内无法直接算 → 归一化口径需把 `id, word, lemma, source, article_id` 拉回 Python 分组（见 §2.3）。

**口径 A：按原始 `lemma`**

```sql
-- 汇总：有多少组重复、多余多少行、最大一组几张
SELECT COUNT(*) AS dup_groups,
       COALESCE(SUM(n - 1), 0) AS surplus_rows,
       SUM(CASE WHEN n > 2 THEN 1 ELSE 0 END) AS groups_gt2,
       MAX(n) AS max_per_lemma
FROM (SELECT lemma, COUNT(*) AS n FROM vocab_cards GROUP BY lemma HAVING COUNT(*) > 1);

-- 明细（看重复长什么样）
SELECT lemma, COUNT(*) AS n, COUNT(DISTINCT word) AS distinct_words,
       MIN(id) AS min_id, MAX(id) AS max_id,
       SUM(mastered = 1) AS mastered_cnt,
       MAX(COALESCE(fsrs_s, 0)) AS max_fsrs_s
FROM vocab_cards GROUP BY lemma HAVING COUNT(*) > 1
ORDER BY n DESC, lemma LIMIT 50;
```

**口径 B：按 `(lemma, word)`**（判断「真重复」还是「合法搭配」的关键口径）

```sql
SELECT COUNT(*) AS dup_groups, COALESCE(SUM(n - 1), 0) AS surplus_rows, MAX(n) AS max_per_key
FROM (SELECT lemma, word, COUNT(*) AS n FROM vocab_cards
      GROUP BY lemma, word HAVING COUNT(*) > 1);
```

**口径 C：按 `word` 单列**（同词不同 lemma，通常是词形/大小写问题）

```sql
SELECT COUNT(*) AS dup_groups, COALESCE(SUM(n - 1), 0) AS surplus_rows, MAX(n) AS max_per_word
FROM (SELECT word, COUNT(*) AS n FROM vocab_cards GROUP BY word HAVING COUNT(*) > 1);
```

**口径 D：按 `(lemma, source)`**（同一词被不同入口重复写入）

```sql
SELECT COUNT(*) AS dup_groups, COALESCE(SUM(n - 1), 0) AS surplus_rows
FROM (SELECT lemma, source, COUNT(*) AS n FROM vocab_cards
      GROUP BY lemma, source HAVING COUNT(*) > 1);
```

**口径 E：按 `(lemma, article_id)`**（同一篇文章内重复，最能证明「同一次操作被重放」）

```sql
SELECT COUNT(*) AS dup_groups, COALESCE(SUM(n - 1), 0) AS surplus_rows
FROM (SELECT lemma, article_id, COUNT(*) AS n FROM vocab_cards
      GROUP BY lemma, article_id HAVING COUNT(*) > 1);
```

**口径 F：归一形态（Python 侧）**

```python
from delector.data.lexicon_merge import lemma_key
# 只读：id, word, lemma；按 lemma_key(lemma) 分组，再按 (key, word) 分组
```

**「语言」「方向」口径不适用**：`vocab_cards` 没有 `language` 列（全库德语单语），也没有 `direction` 列（`de/→zh` 只体现在 `quiz_log.mode`，属答题模式，不是卡片维度）。因此本方案用 A–F 六种真实存在的列组合替代，不虚构口径。

### 2.3 在真实库上跑会碰到什么

| 问题 | 具体表现 | 处置 |
|---|---|---|
| 无 `lemma` 索引 | A/D/E 都是全表扫描 + 分组临时表。本地小库（万行以内）毫秒级；十万行级需 `PRAGMA temp_store` 与磁盘临时表，可能数十秒。 | 只读统计可接受；迁移前若要在大库上重复跑，先 `CREATE INDEX idx_vocab_lemma ON vocab_cards(lemma)`（这属于 DDL，需授权，不在本轮）。 |
| 服务正在写（WAL） | 裸文件拷贝会拿到不一致快照，且 `-wal` 可能含未合并页。 | 用 `mode=ro` URI 连接（SQLite 给只读连接一致视图）；或直接调用现有 `_backup_db_file()`（SQLite backup API，`backup.py:432-447`）导出一致副本再统计。**禁止** `shutil.copy`。 |
| 归一化无法在 SQL 内完成 | `lemma_key` 是 Python 实现（去冠词、折叠空白、小写）。 | 只拉 `id, word, lemma, source, article_id` 五列回 Python；1 万行约数百 KB～1 MB，可一次性；再大就按 `id` 分批（`LIMIT/OFFSET` 或 `WHERE id > ? ORDER BY id`）。 |
| 数据在 Android 端 / 别的 `DATA_DIR` | 本机检出为空库。 | 先在目标设备上确定 `DELECTOR_DATA_DIR` / `DATABASE_PATH`，再对**那个文件**跑只读统计；本方案不假定路径。 |
| 大小写不同的 `lemma` | SQLite 默认 `BINARY` collation，`Haus` ≠ `haus`；口径 A 会漏掉这类重复。 | 同时跑口径 F；若 F 显著大于 A，说明主要问题在归一化，唯一键必须建立在归一列上。 |

---

## 3. 合并策略候选

三种都先假设「代表卡」选择规则与读侧台账一致（`last_signal_day DESC, created_at DESC, id DESC`），否则台账显示的那张和实际保留的那张会不同，用户会看到状态突变。

### A. 保留信号最新的一张，其余物理删除

**动作**：按代表卡规则选 `keep_id` → `UPDATE quiz_log SET card_id = keep_id`、`UPDATE study_log SET ref_id = keep_id WHERE event_type IN ('add_card','master_card')`、重写 `wb_state.payload` 里的卡片键 → `DELETE` 其余行。

| 维度 | 后果 |
|---|---|
| 用户可见 | 卡盒/计数/到期队列里重复卡消失，卡片总数下降 = `surplus_rows`；被删卡的独立复习历史（若它才是信号最新的那张的反面）丢失。**必须**把代表卡规则与台账对齐，否则抽屉状态会跳变。 |
| 可逆性 | **不可逆**（除非迁移前整库快照）。删除后没有表内回退路径。 |
| 备份必要性 | **必需**（若接受不可逆，则至少要有一份可整库还原的快照）。 |
| 外部引用 | `quiz_log` / `study_log` 重映射后可保留全部历史；不重映射则产生孤儿（统计口径会失真）。`wb_state` 必须重映射，否则工作台 FSRS 进度丢失。 |
| 额外风险 | 若被删卡的 `definition_zh` / `sentence_context` 更好（用户后编辑过），删除即丢内容。 |

### B. 保留一张，把复习历史合并成一张

**动作**：先选 `keep_id`，再按列规则合并，然后删除其余行。

| 列 | 合并规则候选 | 语义问题 |
|---|---|---|
| `correct_count` / `wrong_count` | 求和 | 同一道题在两卡各答一次会被计 2 次，计数虚高。 |
| `repetition_count` | 求和？取 max？ | 两卡各自独立推进，求和会造出「复习了 40 次」的假历史；取 max 丢掉另一条。 |
| `interval_days` | 取 max | 与 `repetition_count` 不自洽。 |
| `ease_factor` | 取代表卡 | 可接受。 |
| `fsrs_s` / `fsrs_d` | **只能取代表卡**，不可平均/求和 | 稳定性不是可加量；平均会造出不存在的记忆状态。 |
| `fsrs_lapses` | 求和 | 可接受（确实是累计遗忘次数）。 |
| `mastered` / `mastered_at` | `OR` / 取最早或最晚 | 取最早「已掌握」更符合用户实际达成时间。 |
| `due_date` | 取代表卡 | 与 S/D 一致。 |
| `definition_zh` / `sentence_context` / `article_id` | 保留代表卡的，空则用另一张补 | 不覆盖用户已有内容（与 `vocab_pool._fill_updates` 的「只补空」一致，`vocab_pool.py:176-193`）。 |

| 维度 | 后果 |
|---|---|
| 用户可见 | 与 A 相同的卡片数下降，但复习次数、正确/错误数会比用户直觉更大（两卡历史相加）。 |
| 可逆性 | **不可逆**（物理删除；除非备份）。 |
| 备份必要性 | **必需**，且备份必须保留每张原卡的全部列，否则无法还原计数。 |
| 外部引用 | 同 A，仍需重映射；但 `quiz_log` 里同一张卡会有两条时间交错的历史，按卡统计时要接受。 |
| 额外风险 | 合并结果不是任何一张真实卡的状态，是**构造出来的近似值**。若用户依赖 FSRS 排程，可能造成下一次复习时间不合理。 |

### C. 逻辑合并：不删数据，加 `merged_into` 标记

**动作**：`ALTER TABLE vocab_cards ADD COLUMN merged_into INTEGER DEFAULT NULL`；每组除代表卡外 `UPDATE ... SET merged_into = keep_id`；所有读路径过滤 `merged_into IS NULL`。

| 维度 | 后果 |
|---|---|
| 用户可见 | 与 A 相同的「只出一张」，但底层行仍在。 |
| 可逆性 | **可逆**：清空 `merged_into` 即恢复。不依赖备份。 |
| 备份必要性 | 非必需（但建议仍留整库快照，防止改错 `merged_into`）。 |
| 外部引用 | `quiz_log` / `study_log` 原样保留（被合并卡的答题历史仍挂在原 id 上）；`wb_state` 读时解析代表卡即可，不重写。 |
| 主要代价 | **改所有读路径**：`GET /api/cards`、`/api/cards/due`、`/api/cards/counts`、`/api/cards/known-lemmas`、Anki 导出、`/api/progress/stats`、备份导出（含不含隐藏行？）。漏一处就出现「已合并的卡复活」。 |
| 与唯一索引的关系 | 若同时要加唯一索引，必须用 **partial index**（`WHERE merged_into IS NULL`）；SQLite 支持，但 upsert 的 `ON CONFLICT` 目标必须带同样的 `WHERE` 谓词，写法更绕、更易错。 |
| 额外风险 | 表里长期留冗余行；`SELECT *` 的直接消费者（含备份/导出）都会多一列。旧版本程序读到新列会忽略（备份还原按白名单列写入），但语义丢失。 |

### 三选一的判定依据（不替用户选）

| 若你在意 | 倾向 |
|---|---|
| 只要结果干净、可接受不可逆 | A（最简单，改动面最小）。 |
| 绝不能丢用户复习劳动 | B（但产出近似值）或 C（可逆）。 |
| 要能反悔 / 不想让用户数据物理消失 | C。 |
| 想让写入侧尽快加唯一约束、少改读路径 | A/B + 唯一索引；C 需要 partial index。 |

---

## 4. 约束落法：迁移顺序与回滚

> 大前提：**加 UNIQUE 前必须先解决存量重复**，否则 `CREATE UNIQUE INDEX` 直接失败；SQLite 的 `ALTER TABLE` 也不支持事后加表级唯一约束，只能用唯一索引。

### Step 0 — 只读统计（不改库）

- 跑 §2.2 的 A–F；记录 `total_rows`、`surplus_rows`、`dup_groups`、最大组大小。
- 产物：一份统计报告（数字 + 每条口径的 SQL），作为后面「合并前后行数差 = surplus_rows」的对账基线。
- 失败处理：无写入，直接退出。

### Step 1 — 迁移前快照（是否需要由策略决定）

两种形态，**二选一**，都要明确格式版本：

1. **整库快照**：复用 `_backup_db_file()`（SQLite backup API）→ 落一个 `delector.db.premerge-<UTC时间>` 文件 + `PRAGMA integrity_check` + 行数校验。优点：可整库回滚，格式零变更。缺点：占空间（当前库 380 KB，真实库未知）；含全库明文。
2. **表内快照表**（沿用 `processed_json_backup` 思路）：新增

   ```sql
   CREATE TABLE IF NOT EXISTS vocab_cards_merge_backup (
       card_id      INTEGER PRIMARY KEY,   -- 原行 id
       group_key    TEXT NOT NULL,         -- 归一后的合并键
       kept_id      INTEGER NOT NULL,      -- 代表卡 id（自引用，允许被删后仍可追溯）
       strategy     TEXT NOT NULL,         -- 'keep_latest' / 'merge_history' / 'logical'
       schema_ver   TEXT NOT NULL,         -- 迁移脚本版本，例如 'vocab-dedupe/v1'
       row_json     TEXT NOT NULL,         -- 原行全部列（JSON）
       backed_up_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```

   优点：随迁移同事务写入，天然一致；可只还原被删行。缺点：新增表；不纳入 `BACKUP_FORMAT_VERSION=2` 的白名单（否则旧客户端还原会多表）→ **JSON 导出格式版本不变**，这张表只是本机迁移凭据。

> **格式版本说明**：`BACKUP_FORMAT_VERSION` 保持 2。若采用方案 2 的表内快照，它不参与 `/api/backup` 的 JSON 往返；若未来要把它纳入，必须升到 3 并让旧还原按「未知表忽略」处理——本轮不做。

### Step 2 — 合并（可分批复跑，逐批一个事务）

- 按「代表卡规则」计算每组 `keep_id`（与读侧台账同一套定序；若统一到 `lemma_key`，则分组键用归一列）。
- 写快照（若采用方案 2）→ 重映射引用 → 按策略 A/B 删除或按策略 C 打 `merged_into`。
- **每批一个事务**：`BEGIN IMMEDIATE` → 写 → `COMMIT`；批大小建议 200 组。
- **幂等**：以 `(group_key, strategy)` 为幂等键；重跑时已处理组跳过（若采用方案 2，查 `vocab_cards_merge_backup` 已存在即跳过）。
- 失败回滚：该批 `ROLLBACK`，记录已提交批次；**不删备份、不建索引**，修因后从下一批继续。
- 中断（进程被杀）：未提交事务在 WAL 下不可见；重启后按「已处理组」继续。不得用「整表 DELETE + 重灌」式操作（会放大中断损失）。

### Step 3 — 建唯一索引

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_vocab_identity
    ON vocab_cards(<唯一键列...>);           -- 策略 A/B
-- 或（策略 C）
CREATE UNIQUE INDEX IF NOT EXISTS ux_vocab_identity_active
    ON vocab_cards(<唯一键列...>) WHERE merged_into IS NULL;
```

- **前提校验**：建索引前再跑一次重复检测（`GROUP BY <唯一键> HAVING COUNT(*) > 1`，若为策略 C 加 `WHERE merged_into IS NULL`），必须为空；否则不建。
- 失败回滚：SQLite 的 DDL 可在事务内，失败即 `ROLLBACK`，保持无约束状态；**服务仍可运行**（只是没有约束），不得把服务卡在启动失败循环。
- 锁与耗时：建索引需排他写锁。本机单用户可接受；Android/多客户端场景要选在无活动请求时（或启动迁移阶段）。

### Step 4 — 写入路径改 upsert

```sql
INSERT INTO vocab_cards (<列...>) VALUES (<值...>)
ON CONFLICT(<唯一键列...>) DO UPDATE SET
    -- 只补空，不覆盖用户内容（同 vocab_pool._fill_updates 的「只补空」规则）
    definition_zh   = CASE WHEN TRIM(COALESCE(vocab_cards.definition_zh,''))   = '' THEN excluded.definition_zh   ELSE vocab_cards.definition_zh END,
    sentence_context= CASE WHEN TRIM(COALESCE(vocab_cards.sentence_context,''))='' THEN excluded.sentence_context ELSE vocab_cards.sentence_context END,
    plural          = CASE WHEN TRIM(COALESCE(vocab_cards.plural,''))          = '' THEN excluded.plural          ELSE vocab_cards.plural END
    -- source / article_id / cefr_level / pos 不覆盖（保留首次归属）
RETURNING id, (created_at = ...)  -- 是否需要 created 标记见 §5.4
```

- `ON CONFLICT` 的列集合**必须**与 Step 3 的唯一索引完全一致（含 `WHERE` 谓词），否则 SQLite 报 `ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`。
- 三处生产写入点都要改：`cards.py`、`companion_proposal.py`、`vocab_pool._insert_row`（后者已有内存去重，但并发/跨进程仍会撞索引，必须能吞冲突）。
- 失败回滚：代码回滚是单提交 revert；但**旧代码在同一库上会因唯一索引 INSERT 失败** → 回滚顺序必须是「先 revert 代码，再 `DROP INDEX`」，或发布一个同时兼容的降级脚本。这两步要写进发布说明。

### Step 5 — 验收与对账

- `total_rows_after = total_rows_before - surplus_rows`（策略 A/B）；策略 C 校验 `COUNT(*) WHERE merged_into IS NULL` 与之一致。
- `PRAGMA integrity_check` = ok；`PRAGMA foreign_key_check`（无 FK，仍建议跑）。
- 抽查 10 组：台账代表卡 id == `keep_id` == 卡盒实际显示的那张。
- 引用完整性：`quiz_log` / `study_log` 孤儿数不增加；`wb_state` 能解析所有卡片键。

### 每步失败回滚总表

| 步骤 | 失败表现 | 回滚 |
|---|---|---|
| 0 统计 | 只读失败 | 无写入，退出。 |
| 1 快照 | 磁盘满 / backup API 失败 | 不进入 Step 2。 |
| 2 合并 | 约束冲突 / 磁盘满 / 进程被杀 | 该批 ROLLBACK；已提交批保留；从下一批续跑（幂等）。 |
| 3 建索引 | 仍有重复 / 锁超时 | 事务内 ROLLBACK；库保持无约束；不阻塞服务启动。 |
| 4 upsert | 代码缺陷 | revert 代码 → `DROP INDEX`（顺序不可反）。 |
| 5 验收 | 行数对不上 | 用 Step 1 快照还原（整库或按 `vocab_cards_merge_backup.row_json` 逐行重建）。 |

---

## 5. 写入侧语义与唯一键

### 5.1 先统一「同一词」的口径

| 选项 | 唯一键基础 | 优点 | 代价 |
|---|---|---|---|
| 原始 `lemma` | `lemma` 列 | 零 schema 变更 | 大小写/冠词/屈折会绕过约束：`Haus` 与 `haus` 仍是两张；与工作台 `lemma_key` 口径不一致。 |
| 归一列 `lemma_key` | 新增 `lemma_key TEXT`（写入时计算） | 与工作台投影口径统一（`vocab_pool.py:251`）；真实去重 | 加列 + 回填；历史行需重算；`lemma_key` 是派生值，必须与 `lexicon.py` 同源，不能在前端另算。 |
| `COLLATE NOCASE` | `lemma COLLATE NOCASE` | 不改列 | 只解决大小写；不解决冠词/空白折叠；且 `NOCASE` 只对 ASCII 生效。 |

**推荐候选（不替代裁决）**：新增 `lemma_key` 列，写入侧统一计算，读侧台账也改用它。否则「合并」之后仍会从另一个形态再长一张。

### 5.2 唯一键列集合（关键，不能一刀切）

| 候选 | 允许的合法多卡 | 会误伤的合法用法 | 结论 |
|---|---|---|---|
| `UNIQUE(lemma)` | 无 | 介词搭配（`bestehen auf/aus/in`）、同词不同来源的卡面 | **禁止**。 |
| `UNIQUE(lemma, word)` | 介词搭配（word 不同）、冠词差异（word 不同） | 若用户手动改了 `word` 大小写/空格，会再建一张 | 可用，但需 word 归一。 |
| `UNIQUE(lemma_key, word_key)` | 同上，且折叠大小写/冠词差异 | `word_key` 的归一规则要明确（去冠词？小写？保留空格？） | **首选候选**。 |
| `UNIQUE(lemma_key, word_key, direction)` | 为将来双向卡预留 | 当前无 `direction` 列，属于新增 schema | 仅作扩展点记录，本轮不实施。 |
| 含 `source` / `article_id` | 会允许同词重复 | 直接违背去重目标 | **禁止**。 |

**`direction` 的正式结论**：当前数据模型没有方向维度；`quiz_log.mode` 是答题模式，不是卡片身份。若产品将来要「德→中 / 中→德」各一张，必须在**那时**加 `direction` 列并纳入唯一键。本轮不能凭空造列，也不能声称「方向已被唯一键覆盖」。

### 5.3 合法多卡的区分方式（写清）

- **介词搭配**：`word` 携带介词（`bestehen auf`），`lemma_key` 相同 → `(lemma_key, word_key)` 天然区分。
- **同词不同来源**：`word` 可能带冠词（`die Wohnung`）→ 若 `word_key` 去冠词，则与正文的 `Wohnung` 合成一张（这通常正是用户想要的）；若保留冠词，则仍是两张。**这是 `word_key` 归一规则的产品选择点，必须裁决**。
- **不同文章同一词**：`article_id` 不进键；首次归属保留，不覆盖。
- **`source`**：不进键；首次写入后不覆盖（或按 `official > manual > ai > user > companion` 优先级提升，需另定）。

### 5.4 upsert 的响应语义

- 现有 `POST /api/cards/vocab` 返回 `{"status":"ok","id":<新行>,"word":...,"plural":...}`。upsert 后应返回**实际保留行**的 `id`。
- 建议增加 `created: true|false`（或 `deduped`），让前端知道「这次没新增」。**这会改前端契约** → 必须同时更新 `tests/test_reader_api_split.py` 的导出面清单与相关契约测试；属于「改既有测试断言清单」的范畴，实施前要单独报备。
- 前端 6 个入口目前都不检查返回值语义（只 `await` + 刷新角标），因此「不返回 created」也能工作；若不加字段，本轮只保证 `id` 是既有卡 id。

---

## 6. 验收设计（三个必测情形）

### 6.1 并发重复提交

- 用例：两个线程/两个 TestClient 同时 `POST /api/cards/vocab` 同一 `(lemma, word)`；断言最终 `COUNT(*) = 1`，两条响应拿到的 `id` 相同（或一条 `created=true`）。
- 实现要点：`db_conn()` 的连接隔离与 `busy_timeout` 要确认（`connection.py`）；SQLite 单写锁下第二个连接可能 `database is locked`，要么 `BEGIN IMMEDIATE` + 重试，要么确认 busy_timeout 足够。
- 反例（必须先红）：先在不加唯一索引的库上跑，断言会得到 2 行——证明用例真的在测并发窗口，而不是被单线程顺序掩盖。

### 6.2 迁移中途中断

- 注入方式：① monkeypatch 在「写完快照、删完一半」抛异常；② 子进程在批间 `kill -9`。
- 断言：重跑后 `GROUP BY 唯一键 HAVING COUNT(*) > 1` 为空；`total_rows = before - surplus`；`PRAGMA integrity_check = ok`；`vocab_cards_merge_backup` 无重复 `card_id`。
- 必须测「中断在 Step 3 之前」：此时无唯一索引，旧代码仍能写入 → 重跑前要再跑一次增量合并，否则新建索引会失败。

### 6.3 旧备份还原到新库

- 旧 JSON（`BACKUP_FORMAT_VERSION=2`，无 `merged_into`、无唯一索引）还原到新 schema：
  - 若唯一索引已存在，`_replace_tables` 的 `DELETE + INSERT` 会撞索引 → **还原失败**。
  - 处置候选：① 还原流程在写入前按唯一键去重（复用迁移的合并函数）；② 还原时临时 `DROP INDEX` → 灌入 → 再重建（需在同一事务/锁内）；③ 备份格式升 v3，导出前就按唯一键折叠。
  - 必须选一个并写成测试；**不能**让「还原旧备份」变成不可用路径（这是用户唯一的数据恢复手段）。
- 新备份（含新列）还原到旧库/旧代码：旧代码按白名单列写入 → 新列被忽略，不报错但语义丢失；需在发布说明写「回滚代码会丢失合并标记」。
- 空库首次建表：`CREATE UNIQUE INDEX` 必须成功（无存量数据）。

---

## 7. 明确不做 / 已知风险

- 本轮**不做**：DDL、`ALTER TABLE`、`CREATE UNIQUE INDEX`、改任何写入路径、改读侧台账 SQL。
- 不新增 UNIQUE 约束、不改 `POST /api/cards/vocab` 的行为；台账「共 N 张」文字提示保持不变。
- 不改 `GET /api/cards/vocab?scope=reader` 的 12 字段契约（`tests/test_vocab_contract_uniform.py` 钉死，不放松）。
- 不改 `BACKUP_FORMAT_VERSION`（若采用表内快照，仍保持 2）。
- 已知风险（不在本轮修）：原始 `lemma` 未归一导致读侧台账可能漏看另一形态；`quiz_log` / `study_log` 无外键，脏引用只能靠迁移重映射；`wb_state` 是整块 JSON，重写需整体解析-替换-写回，失败会丢全部工作台状态（迁移时必须先备份该行）。

---

## 8. 待裁决（实施前必须回答）

1. **策略 A / B / C 选哪个？**（决定是否物理删行、是否需要备份、是否改所有读路径）
2. **同一性口径**：原始 `lemma` 还是新增 `lemma_key`？（决定是否加列 + 回填）
3. **唯一键列集合**：`(lemma, word)` / `(lemma_key, word_key)` / 其他？（决定合法多卡的边界）
4. **`word_key` 归一规则**：是否去冠词、是否小写、空格如何处理？（决定「die Wohnung」与「Wohnung」是否合并）
5. **备份形态**：整库快照 / 表内快照表 / 不备份（仅策略 C 可接受）？
6. **旧备份还原策略**：去重后灌入 / 临时删索引 / 备份格式升 v3？
7. **`POST` 是否新增 `created` 字段**？（改前端契约与导出面清单，需单独报备）

---

_本文件只描述方案，不包含可执行迁移。任何 DDL / 数据写入在裁决后另起实施计划与独立工具（默认 dry-run）。_
