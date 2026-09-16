# 歌德官方词表迁移 + 词汇数据架构收敛 实施计划

> **Goal**: 把用户制作的官方歌德 A1/A2/B1 词表（+A1 常用词 overlay）安全迁入 delector，并把当前「东一个西一个」的词表存储收敛为**统一主干 + 按来源分片 + 视图派生**的可扩展架构。
> **Tech Stack**: Python 3.11（纯数据模块 + 核心层）；无 Go 改动。
> **Spec Reference**: ADR-0011（词库单一真相化）、ADR-0005（多等级可扩展）、`01-Rules/DATABASE-MIGRATION-IDEMPOTENCY`；本计划产出 **ADR-0012（词汇主干分层与来源优先级）**。
> **Global Constraints**:
> - **5 元组存储 schema 冻结**（ADR-0011 #6）：`lemma -> (cefr, pos, gender, plural, def_zh)` 不得加字段；扩展字段须另立 ADR。
> - **id 只增不改**（ADR-0011 #7）：`vocab_id = f"{cefr.lower()}-{lemma.lower()}"`；改 cefr = 改 id = 进度孤儿。
> - 数据模块**导入期零副作用**（零网络/零 IO）；纯 `.py`（Chaquopy 不能运行期 open JSON）。
> - 新增数据模块 **MUST 同步打包三处**（`package_windows.py` hiddenimports + `build-release.yml` + `tests/test_server.py::data_dict_modules`）。
> - UTF-8 stdout：`export PYTHONIOENCODING=utf-8`。

---

## 0. 背景（实测数据，2026-09-15 侦察）

### 0.1 用户交付物（3 个未追踪文件，均为 5 元组 schema）
| 文件 | 内容 | 条数 |
| --- | --- | --- |
| `a1_fragment.py` | 官方歌德 A1 单一真相（源自 `A1_SD1_Wortliste_02.pdf` 精选） | 660 |
| `a1_augment_core.py` | A1 级常用基础词 overlay（显式增补，不污染官方源） | 10 |
| `a2b1_fragment.py` | 官方歌德 A2/B1 权威词表 | A2 736 / B1 1617 = 2353 |

> **⚠️ 官方文件内部重叠（2026-09-15 实测）**：`a1_fragment`(660) ∩ `a2b1_fragment`(2353) = **291 条同 lemma 跨档重复，且 cefr 标注不一致**（如 `ruhig` A1↔A2、`zurzeit` A1↔B1、`brief`/`besuchen`/`auskunft` A1↔A2）。三文件并集**去重后 = 2732**（非 3023）。
> **处置（默认策略）**：① 各分片常量 `OFFICIAL_A1_VOCAB`(660) / `OFFICIAL_A1_AUGMENT`(10) / `OFFICIAL_A2B1_VOCAB`(2353) **保留官方原样**（等级视图按 cefr 过滤，容忍官方语境下的跨档重叠——歌德各级词表本就是累进的）；② 合并常量 `OFFICIAL_VOCAB`(2732) 的 key 冲突**低等级优先**（A1 > A2 > B1，即"最早学的等级"语义）。

### 0.2 delector 现有词表源（三套独立表示 —— 这就是「散」的根源）
| 源 | 条数 | 结构 | 消费端 |
| --- | --- | --- | --- |
| `a1_workbench_dict.A1_WORKBENCH_SEED` | 682 | **富**（`id=a1-0001` 序号 / hw / pos / gloss / ipa / ex / letter / page）+ 213 核心 / 22 自定义 / 2 别名 | 背词工作台（FSRS 进度键 = id） |
| `a1_dict.GOETHE_A1_VOCAB` | 702 | **富**（topic / word / lemma / pos / gender / plural / def_zh / example_de / example_zh） | 备考域「官方考纲词表」+ `vocab_stats` 考纲词集 |
| `core_dict.CORE_VOCAB_DB` | 4411（A1 459 / A2 974 / B1 1712 / B2 860 / C1 406） | 5 元组 | NLP CEFR 难度标注 / `lookup_core_vocab` / `get_vocab_by_cefr` |

其中 `core_dict` 的 **手编 base 仅 442 条**，其余 3969 条来自 **AI 生成的 `core_dict_ext.py`**（A1 299 / A2 885 / B1 1621 / B2 773 / C1 391）。

### 0.3 新旧重合度（核心难点）
| | 现有 | 官方 | 交集 | 官方独有 | 现有独有 |
| --- | --- | --- | --- | --- | --- |
| A1（workbench 按 hw） | 681 | 670 | 309 | 361 | 372 |
| A1（GOETHE_A1_VOCAB） | 702 | 670 | 391 | 279 | 311 |
| A2（core） | 974 | 736 | 363 | 373 | **522** |
| B1（core） | 1712 | 1617 | 842 | 775 | **779** |
| **同 lemma 但等级不同（cefr 冲突）** | — | — | — | — | **588** |

### 0.4 关键评估结论：**AI 词库（core_dict_ext）不是垃圾，必须保留**
- **来源可信**：`tools/build_dict.py` 的源是歌德词表（`b1_sorted.txt` 2833 行 / `a2_words.txt` 1215 / `b2_all.csv` 1924），只有**中文释义由 DeepSeek 生成**。它覆盖面**比用户的精选表更全**（这才是交集只有 ~44%/52% 的原因，而非"AI 乱编"）。
- **质量实测**：结构校验 0 缺陷（NOUN 缺性别 0 / 非名词带性别 0 / 空释义 0）；抽样 AI 独有词（`ausmachen` / `flüstern` / `sprechstunde` / `muttersprache` / `briefumschlag` / `verpflichtung`…）全为真实德语词且释义准确。
- **噪声面很小**：抽样发现极少数英语词混入（如 `dishwasher`），需清理。
- **AI 还有 B2 773 / C1 391 共 1164 条无官方对应，必留**。

---

## 1. 决策记录

| # | 决策 | 依据 |
| --- | --- | --- |
| **D1** | **id 冲突以官方为准，接受进度孤儿** | 用户拍板（真实用户进度集中在 A1 工作台 localStorage；A2/B1 备考域卡片无持久进度） |
| **D2** | **AI 词库保留，采用「官方优先 + AI 补充」并集语义**（不删 AI 的 A2/B1） | §0.4 实测：AI 独有 1301 条（A2 522 + B1 779）是真实词，删除即丢覆盖面 |
| **D3** | **架构收敛方向：统一主干 + 按来源分片 + 视图派生**（而非"一个文件装所有"） | 用户诉求「可扩展性 / 为未来 / 利于联动」；分层 ≠ 分散 |
| **D4** | **A1 富结构（workbench seed / GOETHE_A1_VOCAB）本轮不动**，收敛留 Phase 2 ADR | 撞 FSRS 进度红线 + 富字段（IPA/例句）需 join 派生，且 ADR-0011 刚收敛完 |
| **D5** | 迁移落地位置 = **`core_dict` 合并链**（复用现有 `ext` 合并模式，最大复用） | The Ladder of Reuse；`core_dict` 已是事实主干 |

---

## 2. 目标架构

```
                        ┌──────────────────────────────────────────┐
   分片来源（纯数据）    │  core_dict.py        手编核心   442      │
   统一 5 元组 schema   │  core_dict_ext.py    AI 扩展    3969     │
   （守冻结红线）       │  official_vocab.py   官方  A1 670/A2 736/B1 1617 │
                        └───────────────────┬──────────────────────┘
                                            │ 合并（后者覆盖前者 = 优先级）
                                            ▼
                        ┌──────────────────────────────────────────┐
   词汇主干（唯一入口）  │  CORE_VOCAB_DB (core_dict.py 底部合并)   │
                        │  优先级：官方 > 手编 > AI                 │
                        └───────────────────┬──────────────────────┘
                                            │ 视图派生（不复制数据）
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
   get_vocab_by_cefr(A2/B1)      NLP lookup / get_core_cefr_level   vocab_stats 考纲词集
   （备考域词表）                   （难度标注）                       （A1 考纲）
              │
              ▼  ← Phase 2（ADR-0012 后）
   workbench seed 视图 / GOETHE_A1_VOCAB 视图（join 富字段 IPA/例句/topic）
```

**原则**：
1. **一份 schema**（5 元组）贯穿所有分片；来源由**模块边界**表达（不引入 schema 字段，守冻结红线）。
2. **优先级由合并顺序**表达：官方 > 手编 > AI（后合并者覆盖同 lemma）。
3. **消费端只读主干**，通过派生函数取视图；禁止再新增独立词表副本。
4. **可扩展**：未来加 B2/C1 官方表 = 新增一个分片常量并挂进合并链，零消费端改动。

---

## 3. Phase 1（本轮执行）：官方词表入库 + 主干成形

### Task 1: 官方词表分片数据模块 [Role: TDD Builder]

**Files:**
- Create: `delector/data/official_vocab.py`
- Test: `tests/test_official_vocab.py`
- Source（只读输入）: `a1_fragment.py` / `a1_augment_core.py` / `a2b1_fragment.py`（仓库根，迁移后删除）

**Interfaces:**
- Produces:
  - `OFFICIAL_A1_VOCAB: Dict[str, tuple]`（660）
  - `OFFICIAL_A1_AUGMENT: Dict[str, tuple]`（10）
  - `OFFICIAL_A2B1_VOCAB: Dict[str, tuple]`（2353，各条自带 cefr）
  - `OFFICIAL_VOCAB: Dict[str, tuple]` = `{**OFFICIAL_A2B1_VOCAB, **OFFICIAL_A1_VOCAB, **OFFICIAL_A1_AUGMENT}`（**A1 后写 = 低等级优先**，去重 2732 条）

**规范化规则（必须固化在种子生成/校验里）:**
- lemma 全小写、去首尾空格；连字符可分动词统一保留连字符（`an-sein`）；
- pos 统一大写枚举（`NOUN/VERB/ADJ/ADV/PREP/CONJ/PRON/INTERJ/PART/NUM`）；
- 名词 gender ∈ `{Masc,Fem,Neut,Plur}`；非名词 gender 必须为 `None`；
- 重复 lemma → 报错（fail-fast，不静默去重）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 官方词表分片数据模块。
> Goal: 把仓库根 3 个未追踪 py（a1_fragment/a1_augment_core/a2b1_fragment，5 元组 schema）规范化为 `delector/data/official_vocab.py` 的 4 个常量（OFFICIAL_A1_VOCAB 660 / OFFICIAL_A1_AUGMENT 10 / OFFICIAL_A2B1_VOCAB 2353 / OFFICIAL_VOCAB 合并），模块头写清来源与 schema 注释，导入期零副作用。
> Target Files: Create `delector/data/official_vocab.py`, Test `tests/test_official_vocab.py`。
> TDD Steps:
> 1. 写失败测试：断言 4 常量条数精确（660/10/2353/3023）、每条为 5 元组、cefr ∈ {A1,A2,B1}、名词 gender 合法、非名词 gender 为 None、无重复 lemma（RED）。
> 2. `pytest tests/test_official_vocab.py -v` 验证失败。
> 3. 用一次性脚本从 3 个源文件生成该模块（保留 lemma 覆盖率，做规范化；不改任何释义文字）（GREEN）。
> 4. 跑测试全绿。
> 5. 保持纯数据（无 import 副作用、无函数）。
> 6. 原子 commit。
> Return: 测试执行证据 + 4 常量实际条数。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试并确认按预期失败**
- [ ] **Step 3: 生成数据模块（GREEN）**
- [ ] **Step 4: 跑测试全绿**
- [ ] **Step 5: 纯数据审查（无副作用）**
- [ ] **Step 6: 原子 commit**

---

### Task 2: 主干合并接入（官方优先） [Role: TDD Builder]

**Files:**
- Modify: `delector/data/core_dict.py:516-524`（现有 ext 合并段之后，追加官方合并）
- Test: `tests/test_lexicon_official_merge.py`

**Interfaces:**
- Consumes: `delector.data.official_vocab.OFFICIAL_VOCAB`
- Produces: 合并后的 `CORE_VOCAB_DB`（唯一主干）

**要点:**
- 合并顺序 = `{**CORE_VOCAB_EXT, **手编, **OFFICIAL_VOCAB}` → 官方最高优先（同 lemma 等级/释义以官方为准 = D1）。
- `except ImportError` 处理须与现有 ext 一致（**红线 2**：官方分片是包内必存模块，缺失应炸，不得静默回退）。
- 合并后预期量：A1 459→**827**、A2 974→**1347**、B1 1712→**2487**、B2 860、C1 406。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 官方词表合并进主干（官方优先）。
> Goal: 在 `delector/data/core_dict.py` 合并段追加 `from delector.data.official_vocab import OFFICIAL_VOCAB; CORE_VOCAB_DB = {**CORE_VOCAB_DB, **OFFICIAL_VOCAB}`，使官方等级/释义覆盖同 lemma 的 AI/手编值；缺模块必须抛错（不静默回退）。
> Target Files: Modify `delector/data/core_dict.py`, Test `tests/test_lexicon_official_merge.py`。
> TDD Steps:
> 1. 写失败测试：① `tabelle` 等级 == 官方值（B1）；② 官方独有词存在（如 `ausmachen`→B1）；③ AI 独有词未丢（如 `dishwasher` 仍在，后续 Task 清理）；④ 各等级计数 == 827/1347/2487/860/406；⑤ B2/C1 无官方覆盖仍存在（RED）。
> 2. `pytest tests/test_lexicon_official_merge.py -v` 验证失败。
> 3. 改 `core_dict.py` 合并链（最小改动）（GREEN）。
> 4. 跑测试 + `pytest tests/test_core_dict_ext.py tests/test_dict_pipeline.py -v` 全绿（确认无回归）。
> 5. 原子 commit。
> Return: 测试证据 + 合并后各等级计数。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 改合并链（GREEN）**
- [ ] **Step 4: 定向回归（core_dict_ext / dict_pipeline / vocab_stats）**
- [ ] **Step 5: 原子 commit**

---

### Task 3: 迁移对账报告工具 [Role: TDD Builder]

**Files:**
- Create: `tools/audit_official_vocab.py`
- Test: `tests/test_audit_official_vocab.py`

**要点（可复现、可审计 = 用户"为未来考虑"的抓手）:**
- 输出一份 JSON/Markdown 报告：各来源条数、交集/独有、588 条 cefr 冲突明细（旧等级→新等级）、AI 噪声候选（英语词/超纲 pos）。
- 纯函数 + `--json` 输出，CI 可跑，未来每次换词表都能一键对比。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 官方词表对账工具。
> Goal: `tools/audit_official_vocab.py` 打印/导出「官方 vs 手编 vs AI」的分片对账（条数、交集、独有、cefr 冲突清单、噪声候选），支持 `--json`。纯函数，零网络。
> Target Files: Create `tools/audit_official_vocab.py`, Test `tests/test_audit_official_vocab.py`。
> TDD Steps: 1) 写失败测试（给定小型 fixture dict，断言交集/独有/冲突计数正确）（RED）→ 2) 跑失败 → 3) 实现（GREEN）→ 4) 全绿 → 5) 出报告并附进计划执行状态 → 6) commit。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现（GREEN）**
- [ ] **Step 4: 生成真实对账报告**
- [ ] **Step 5: 原子 commit**

---

### Task 4: 打包面三处注册同步 [Role: TDD Builder]

**Files:**
- Modify: `package_windows.py`（hiddenimports 增 `delector.data.official_vocab`）
- Modify: `.github/workflows/build-release.yml`（同一 hiddenimport/拷贝清单）
- Modify: `tests/test_server.py`（`data_dict_modules` 集合 9 → 10）
- Test: 复用 `tests/test_server.py` 现有守卫 + `tests/test_packaging_*`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 打包三处注册同步。
> Goal: 新增数据模块 `delector.data.official_vocab` 在三处打包面同步注册（package_windows.py hiddenimports / build-release.yml / tests/test_server.py::data_dict_modules），漏改即打包后 ModuleNotFoundError 而本地全绿。
> Target Files: Modify 上述三处, Test 复用现有打包守卫。
> TDD Steps: 1) 断言 `data_dict_modules` 含新模块（RED，若先改测试）→ 2) 跑失败 → 3) 三处同步（GREEN）→ 4) `pytest tests/test_server.py -k "dict_module or packaging" -v` 全绿 → 5) commit。"

**Step Breakdown:**
- [ ] **Step 1: 写/改守卫测试（RED）**
- [ ] **Step 2: 三处同步注册（GREEN）**
- [ ] **Step 3: 跑打包守卫**
- [ ] **Step 4: 原子 commit**

---

### Task 5: AI 噪声清理（最小、保守） [Role: TDD Builder]

**Files:**
- Modify: `delector/data/core_dict_ext.py`（仅移除确认的噪声条目，逐条留证）
- Test: `tests/test_core_dict_ext.py`（追加噪声黑名单断言）

**要点:** 只删**确证**的噪声（如英语词 `dishwasher`）；**不做**大规模删词（避免误伤真实词）。每删一条在 commit message 留证据。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: AI 噪声清理（保守）。
> Goal: 由 Task 3 报告 + 人工复核，仅移除确证的噪声条目（英语词/非德语），逐条在 commit message 留证；不动其他条目。
> Target Files: Modify `delector/data/core_dict_ext.py`, Test `tests/test_core_dict_ext.py`。
> TDD Steps: 1) 测试断言噪声词不在 DB（RED）→ 2) 跑失败 → 3) 删条目（GREEN）→ 4) 全绿 → 5) commit（message 列明删除项与理由）。"

**Step Breakdown:**
- [ ] **Step 1: 写噪声黑名单测试（RED）**
- [ ] **Step 2: 移除确认条目（GREEN）**
- [ ] **Step 3: 原子 commit**

---

### Task 6: 文档与回归收口 [Role: TDD Builder]

**Files:**
- Create: `docs/adr/0012-vocabulary-backbone-and-source-priority.md`（ADR-0012 草案）
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（数据源清单：三套→主干+分片）
- Modify: 计划本文件「执行状态」块
- 删除仓库根 3 个源文件（内容已迁入 `official_vocab.py`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: 文档与回归收口。
> Goal: 写 ADR-0012（词汇主干分层与来源优先级：分片=schema 冻结下的来源表达；优先级=合并顺序；消费端视图派生），更新 PROJECT_OVERVIEW 数据源清单，回填本计划执行状态，删除根目录 3 个已迁移源文件。
> Target Files: Create ADR-0012, Modify PROJECT_OVERVIEW + 本计划文件, Delete 根 3 py。
> TDD Steps: 1) 全量 `pytest -v`（记录新基线）+ `ruff check .` + `python -m mypy`（RED 若异常）→ 2) 全绿 → 3) 文档与清理 → 4) commit。"

**Step Breakdown:**
- [ ] **Step 1: 全量回归（pytest / ruff / mypy）记录新基线**
- [ ] **Step 2: 写 ADR-0012 草案**
- [ ] **Step 3: 更新 PROJECT_OVERVIEW + 计划执行状态**
- [ ] **Step 4: 删除已迁移源文件**
- [ ] **Step 5: 原子 commit**

---

## 4. Phase 2（后续，需 ADR 拍板）：A1 富结构收敛

**目标**：让 `a1_workbench_dict.A1_WORKBENCH_SEED`（682）与 `a1_dict.GOETHE_A1_VOCAB`（702）**从主干派生**（join 富字段），消灭"同一批 A1 词三种表示"。

**待拍板子问题（Phase 2 计划前必须定）:**
1. **A1 官方 660+10 该落哪？** 推荐：作为主干 A1 层（Task 2 已落），再让 `GOETHE_A1_VOCAB` 视图 = 官方 lemma ∩ 旧 702 的富字段（example/topic）join；新独有 279 条 example 先留空。
2. **workbench 序号 id（`a1-0001`）与 FSRS 进度**：收敛必须保留 id 映射（复用 `A1_WORKBENCH_ID_ALIASES` 模式）。
3. **备考域 A2/B1 词表展示口径**：并集（1347/2487，含 AI）还是官方精选（736/1617）？若选后者，需主干加**来源感知查询**（`get_vocab_by_cefr(..., source="official")` 之类的 scope 扩展）——这正是 ADR-0012 要定的事。

---

## 5. 开放项 / 风险

| 项 | 说明 | 处置 |
| --- | --- | --- |
| 588 条 cefr 冲突 | 官方覆盖后等级变化 → id 变 | D1 已定：接受孤儿；Task 3 报告留明细 |
| 官方表也是"精选子集" | A2 736 远小于歌德官方全量；与 AI 表互补 | D2：并集，不删 AI |
| 备考域展示口径 | 并集 vs 官方精选 | 留 §4-3，Phase 2 ADR 定 |
| 源文件可重放性 | 用户源来自 `D:/Ran/German/_build/entries_raw.json`（外部） | 建议把生成脚本 / 源 JSON 摘要一并归档，保证可重放 |
| workbench 富字段 | IPA/例句在 seed 里，主干没有 | Phase 2 join 派生，不冗余存储 |

---

## 6. 执行状态（2026-09-15/16 收官）

**分支**：`feature/official-vocab-lexicon-backbone`（本地逐 Task 原子 commit）

| Task | commit | 内容 |
| --- | --- | --- |
| 文档 | `326347b` | 本计划 + ADR-0012 引用 + 官方内部 291 条重叠处置 |
| R2 | `f6cffc0` | 官方分片 `official_vocab.py`（A1 660 / 增补 10 / A2B1 2353 → 合并 2732 低等级优先） |
| R3 | `8ec66cb` | 主干 `lexicon.py`（FRAGMENTS / provenance / 优先级）；`core_dict` 暴露 `CORE_VOCAB_MANUAL` |
| R4 | `b1f0b49` | `sources` 贯通；备考域/工作台 A2·B1 切官方（736/1617）；`/api/a2/vocab` 默认官方 |
| R5 | `5d0f0b8` | **字段级合并**（cefr 官方优先 / 富字段手编优先）+ 单真值（`CORE_VOCAB_DB == LEXICON`） |
| R6 | `44c2248` | 主干单入口化（7 处消费端迁移 + `test_lexicon_single_entry` 守卫）；`vocab_stats` A2 对齐官方 |
| R7 | `942a4d6` | 对账工具 `tools/audit_official_vocab.py`（cefr 冲突 952 / 噪声 1） |
| R8 | `301891b` | 打包三处同步 + `dishwasher` 清理 + `core_ids_by_level()` 多级核心词预留 |

**关键数据（收官实测）**
- 分片：ai **3968**（清 dishwasher 后）/ manual **443** / official **2732**
- 主干：`LEXICON` == `CORE_VOCAB_DB` == **4762**（单真值，由同一纯函数 `lexicon_merge.merge_fragments` 算出）
- 官方各档（`official_level`）：A1 **670** / A2 **736** / B1 **1617**（备考域·工作台口径）
- 默认视图（合并后按 cefr 过滤）：A1 827 / A2 615 / B1 2181 / B2 736 / C1 404
- 字段级冲突样例：`haus` = 官方 cefr `A1` + 手编 plural `-..er`；`schule` plural `-n`；`arzt` `-..e`

**门禁**：定向测试全绿（各 Task 均记录）；`ruff check .` 零告警；`python -m mypy` 0 error（115 源文件）；单入口守卫（0 直连分片）绿。

**已知既有问题（非本次引入）**：本机 Windows 全量 `pytest` 存在跨文件 `DATABASE_PATH` 环境串扰 —— `test_exam_trials + test_goethe_a1_hoeren + test_goethe_a1_lesen` 三文件组合在 **`master` 基线（`358777e`）同样 2 failed**（`no such table: exam_trials`，经 `git worktree` A/B 证实）。权威门禁以 CI（ubuntu `ci.yml`）为准。

**未做（明确留待）**
- Phase 2：A1 富结构（`A1_WORKBENCH_SEED` / `GOETHE_A1_VOCAB`）从主干派生收敛（需 id 映射 + 富字段 join）。
- A2/B1 富字段（IPA/例句）：本机侧无来源，待用户 + 外部 agent 按 §9.5 提示词补齐后另行挂载。
- A2/B1/B2 核心词名单：仅预留结构（`core_ids_by_level()`），未挑名单。

---

## 10. Phase 2 富字段挂载方案（`official_vocab_rich.py` 检验 + 方案，2026-09-16）

### 10.1 交付物检验（外部 agent 产出，525KB / 3034 行）
Schema：`lemma -> {"ipa", "example_de", "example_zh", "topic"}`；常量 `OFFICIAL_RICH_A1`(660) / `OFFICIAL_RICH_A2`(736) / `OFFICIAL_RICH_B1`(1617)。头注：IPA 由 `g2p.py` 规则生成（源 `ipa_map.json`）；例句德文来自官方 PDF `entries_raw.json`；中文 **逐字取自** `tr_*.json` / `a2b1_enrich.json`（非机翻）。

| 等级 | rich | 官方分片 | 交集 | rich 多余 | 官方未覆盖 |
| --- | --- | --- | --- | --- | --- |
| A1 | 660 | 670 | 660 | 0 | **10**（=`OFFICIAL_A1_AUGMENT` 表外常用词） |
| A2 | **736** | 736 | 736 | 0 | **0** |
| B1 | **1617** | 1617 | 1617 | 0 | **0** |

字段完整度：IPA A1 654 / A2 733 / B1 1616（**空 10 条**）；`example_de` A1 660 / A2 732 / B1 1617；`example_zh` A2 729 / B1 1617 / **A1 仅 198 ⚠️**。

### 10.2 三条关键结论
1. **A2/B1 是主要收益**（项目原先**完全没有** A2/B1 的 IPA/例句）→ 覆盖 736/1617 = **100%**，join key 零偏差。
2. **A1 基本冗余**：`A1_WORKBENCH_SEED`(682 全覆盖 ipa+ex) 与 `GOETHE_A1_VOCAB`(702 全覆盖 example_zh) 已有富数据；rich 的 A1 与之 **IPA 差异 586 相同 / 50 不同，且 50 条全是表示法差异**（rich 用 `t͡s`/`p͡f` tie-bar，现有用 `ts`/`pf`）。→ **A1 建议不换**（避免表示法不一致与无谓风险）；A1 中文例句缺口可用内部数据补到 **640/660**（`seed.ex[0].zh` 或 `GOETHE_A1_VOCAB.example_zh`）。
3. **IPA 是规则 g2p 生成**（非官方来源），存在 artifacts：`abfall`→`ˈapfall`（未简化双辅音）、`an-sein`→`ˈan zˈaɪn`、`abenteuer`→`das ˈaːbəntɔɪeːɐ`、`am-besten`→`ˈam bɛstˈən`。**含空格 = 名词带冠词发音**（`diː`/`deːɐ`/`das`），与现有 A1 风格一致（A1 329/660、A2 342/736、B1 846/1617）。

### 10.3 方案（Phase 2，分 5 步）

| # | 步骤 | 产出 / 要点 |
| --- | --- | --- |
| **S1** | **富字段分片入库** | `delector/data/official_vocab_rich.py`（保留 3 常量，纯数据零副作用）；**建议向外部 agent 索取 `gen_rich.py` 归档 `tools/`**（可重放性）；打包三处同步 |
| **S2** | **主干富字段视图** | `lexicon` 增 `RICH` + `rich_of(lemma)`（加载期从 side-car 取，**不入 5 元组存储**）；不改 provenance 语义 |
| **S3** | **A1 中文例句补齐**（仅当 A1 也走 rich） | 用 `A1_WORKBENCH_SEED.ex[0].zh` / `GOETHE_A1_VOCAB.example_zh` 回填 198→640（内部数据，零外部依赖） |
| **S4** | **输出契约扩展（需 ADR 增补）** | 9 字段冻结的例外路径：`_contract_item` 扩为 `example_de` / `example_zh`（或 `ex:[{de,zh}]` 对齐 A1 工作台形状）；同步 `tests/test_vocab_contract_uniform.py` |
| **S5** | **消费端接线** | `/api/cards/vocab` 下发富字段；`a1_cards.js` 的 `example_zh`（现硬编码 `""`）接上；工作台 A2/B1 档同步填 `ipa`/`ex`（`wb.words.v1` 形状已支持） |

### 10.4 用户裁决（2026-09-16「按推荐来开做」）
1. **A1 不切 rich** ✅（现有 seed/GOETHE_A1_VOCAB 已全覆盖；rich 的 A1 仅表示法差异）
2. **IPA 统一为现有表示** ✅ → 落地为**去 tie-bar（U+0361）**：`t͡s→ts`、`p͡f→pf`、`t͡ʃ→tʃ`（252 条受影响）；不反向改 A1
3. **IPA 质量门** ✅ → 产出**人工复核清单**（10 条空 IPA + artifacts 抽样），不做重质量门

契约扩展决策落 **ADR-0013**（Vault `01-ADR/0013-rich-vocab-fields-output-contract.md`）：契约 9 → **11 字段**（新增 `ipa` / `example_zh`，`de` 语义统一为德语例句）。

### 10.5 Phase 2 任务分解（S1–S6，/vault-exec）

| # | 任务 | 产出 |
| --- | --- | --- |
| **S1** | 富字段分片入库（含 IPA 去 tie-bar） | `delector/data/official_vocab_rich.py` + `tests/test_official_vocab_rich.py` |
| **S2** | 主干富字段视图 | `lexicon.RICH` / `rich_of(lemma)` + 测试 |
| **S3** | A1 中文例句补齐（内部数据回填） | A1 分支 `example_zh` 覆盖 198 → ~640 |
| **S4** | 契约扩展 9→11 | `_contract_item` + 三分支填值 + **同步 `tests/test_vocab_contract_uniform.py`** |
| **S5** | 消费端接线 | `/api/a2/vocab` 下发 `ipa`；workbench A2/B1 档（`ipa` + `ex:[{de,zh}]`）；`a1_cards.js` 接 `example_zh`；探针同步 |
| **S6** | QA 与收口 | IPA 人工复核清单 + 文档回填 + 全量门禁 |

### 10.6 风险与守线
- 契约扩展（S4）**破 9 字段冻结** → 已由 **ADR-0013** 决策 + 必须同步契约守卫测试（严格相等改为 11 字段，**不得放宽为子集**）。
- 富字段是 **side-car 分片**，**不改 5 元组存储 schema**（ADR-0011 §5-6 / ADR-0012 §5-1 不破）。
- 前端改动（S5）→ **Android 需覆盖安装**。
- 打包三处同步新分片（S1）。

---

## 7. 架构评估（开工前复审 · 2026-09-15）

> 触发：用户拍板**备考域「仅官方精选」（736/1617）**，并要求复审"新结构是否利于长期维护与扩展"。结论：**原 Phase 1（把官方塞进 `core_dict` 合并成一体）在新口径下不成立**，需修订（见 §8）。

### 7.1 原结构确实改善的点
1. **复用现有范式**：直接接 `core_dict.py` 已有的 `ext` 合并链（`{**EXT, **BASE}`），零新范式（The Ladder of Reuse）。
2. **对账工具**：`tools/audit_official_vocab.py` 让每次换词表可复现对比（D2 决策的可审计抓手）。
3. **打包三处同步**：沿用既有纪律，风险已知可控。
4. **方向正确**：统一主干 + 视图派生，方向与 ADR-0011 一致。

### 7.2 原结构的硬缺陷（4 条，均已实测）
1. **无法支撑"仅官方精选"**：`CORE_VOCAB_DB` 合并成一体后**来源信息丢失**，要"只出官方 736/1617"就得反查各分片是否含该 lemma 来重算 provenance（O(n) 且易错）。
2. **契约冻结 vs 来源可见冲突**：`tests/test_vocab_contract_uniform.py:23,48` 用 `set(w.keys()) == CONTRACT_FIELDS`（**严格相等**）钉死 9 字段；API 想暴露来源 → 必先破 ADR-0011 契约（需 ADR）。
3. **`core_dict` 语义重载**：它被 **17 个文件**依赖（9 个 delector 模块含 NLP 热路径 + 6 个构建工具 + 测试）。让它同时当"全量难度词典"和"官方精选源"→ 改动影响面不清晰（长期维护陷阱）。
4. **没解决用户最在意的"散"**：A1 三套表示被推到 Phase 2 → Phase 1 落地后**短期看更散**（4 个分片 + 3 个 A1 源），与用户诉求相反。

### 7.3 修订结构（推荐）

```
分片（纯数据，5 元组冻结，来源=模块边界）
  core_dict(手编442) | core_dict_ext(AI 3969) | official_vocab(A1 670/A2 736/B1 1617)
                    │
                    ▼  lexicon.py（唯一主干加载器；加载期计算 provenance 旁路）
   LEXICON: Dict[lemma, Entry{value, provenance:frozenset[str]}]
                    │  视图查询（唯一入口；消费端禁止直连分片）
   get_vocab_by_cefr(cefr, scope, sources=None)  ← sources={"official"} ⇒ 736/1617
   lookup_core_vocab / vocab_stats / exam_catalog
                    │  ADR-0009 shim（兼容）
   core_dict.CORE_VOCAB_DB = LEXICON 的 5 元组视图（deprecated 标记）
```

**四条纪律**：
- **不破 5 元组冻结**：`provenance` 是加载期旁路结构，不进存储 schema。
- **不破 9 字段契约**：默认输出逐字不变；若未来要在 API 暴露来源 → 另立 ADR 加可选字段并同步改契约测试。
- **顺序守卫测试**：把优先级「官方 > 手编 > AI」写死在 `tests/test_lexicon_priority.py`。
- **单入口守卫测试**：`routes/`、`services/` 禁止直连分片模块（用 import 静态断言钉住）。

### 7.4 权衡（诚实）
| 维度 | 塞进 core_dict（原） | lexicon 主干（修订） |
| --- | --- | --- |
| 改动量 | 小（1 个合并段） | 中（新增 `lexicon.py` + shim + 契约决策） |
| 支撑"仅官方精选" | ❌ 需反查重建来源 | ✅ 原生支持 |
| 语义清晰度 | 差（core_dict 重载） | 好（core_dict 降级为分片之一） |
| 返工风险 | **高**（将来要抽主干=返工） | 低 |
| 兼容风险 | 低 | 低（17 个 import 点靠 shim 兜住，ADR-0009 成熟模式） |

### 7.5 结论
- **原 Phase 1 不足以支撑"仅官方精选"**，且把最痛的"三套 A1 表示"推迟 = 半成品。
- **修订结构（lexicon 主干 + 显式 provenance + 契约不破）才真正利于长期维护与扩展**。
- **建议：先落 ADR-0012（结构设计）再执行**，避免先落一个"将来要返工"的中间结构。

---

## 8. 修订后的 Phase 1（待拍板后替换 §3）

| # | Task | 关键产物 | 相对原计划 |
| --- | --- | --- | --- |
| **R1** ✅ | ADR-0012 结构设计（先决策后编码） | Vault `08-Projects/DeLector/01-ADR/0012-vocabulary-backbone-and-source-priority.md` | **新增（前置，已完成 2026-09-15）** |
| **R2** | 官方分片模块化 | `delector/data/official_vocab.py` + `tests/test_official_vocab.py` | 同原 T1 |
| **R3** | 主干加载器 `delector/core/lexicon.py`（分片注册表 + provenance + 优先级） | `LEXICON` + `tests/test_lexicon_priority.py` | **替换原 T2** |
| **R4** | 查询层接入 `sources` 过滤 + 备考域改「仅官方」 | 改 `get_vocab_by_cefr` / `exam_catalog.count_fn` / `routes/a2.py` | **新增** |
| **R5** | `core_dict.CORE_VOCAB_DB` 降级为 shim（deprecated） | 改 `core_dict.py` + 兼容测试 | **替换原 T2 尾部** |
| **R6** | 单入口守卫（routes/services 禁直连分片） | `tests/test_lexicon_single_entry.py` | **新增** |
| **R7** | 对账工具 | `tools/audit_official_vocab.py` | 同原 T3 |
| **R8** | 打包三处 + AI 噪声清理 | 同原 T4/T5 | 同原 |
| **R9** | 文档收口 + 删源文件 | ADR-0012 定稿 + OVERVIEW + 清理 | 同原 T6 |

**Phase 2（A1 富结构收敛）** 在修订结构下变为**自然延伸**：workbench seed / `GOETHE_A1_VOCAB` 改为从 `LEXICON` 派生 + join 富字段，不再需要另立架构。

---

## 9. 产品目标形态（背词工作台四档）与增量 Gap（2026-09-15 用户澄清）

### 9.1 用户目标形态
**最终 = A1 / A1核心 / A2 / B1 可切换背词**（每档均为官方权威）。

### 9.2 现状实测（归一化后）
- 工作台档位**已存在**：`#scopeSeg` = ⭐A1核心(`core`) / A1全量(`all`) / 📘A2词库(`a2`) / 📗B1词库(`b1`) / 精读生词(`reader`)，由 `SCOPE_PREDICATES` + `isInScope` 数据驱动（ADR-0011）。
- **工作台 A1 = 官方 A1（实测确认）**：`A1_WORKBENCH_SEED`(682) 与用户官方 A1(660+10) 归一化后 **∩ 636/678（≈94%）**，剩余差异几乎全是写法（`(sich) anmelden`↔`sich-anmelden`、`an sein`↔`an-sein`、`café`↔`caf`、`circa/ca.`↔`circaca`）。
- **核心词 = A1 精简子集**：`A1_WORKBENCH_CORE_IDS`(213) ∩ 官方 **210/213**（差异仅 `café`/`pommes frites`/`weh tun`），再 + `A1_WORKBENCH_CUSTOM`(22) = **235 核心词**（构建期打 `core` tag）。
- **A1 三套表示的真相**：**内容本就是同一批官方词**，问题在**表示层**（富 list + 序号 id / 富 dict + topic / 5 元组），不在数据层 → Phase 2 收敛只需统一"表示 + id 映射"。

### 9.3 增量 Gap（本轮迁移的正确定位）
| # | Gap | 现状 | 处置 |
| --- | --- | --- | --- |
| **G1** | **A2/B1 档位当前非官方** | 走 `get_vocab_by_cefr("A2"/"B1")` = `core_dict`（AI 混合 974/1712） | **R4 的 `sources={"official"}` 过滤直接解决** → A2 736 / B1 1617 |
| **G2** | **多级核心词机制** | 只有 A1 有核心白名单（213+22） | **用户拍板（2026-09-15）：预留可扩展结构，本轮不实现名单**（B2/B2核心等后期必然扩展）。设计见 §9.4 |
| **G3** | **A2/B1 无富字段** | 服务端 9 字段契约（无 ipa/ex）；A1 有 | **用户拍板：由外部从权威源补齐**（§9.5 提示词）→ 补回后作 side-car 分片经 `lexicon` 挂载 |
| **G4** | **A2/B1 id 会变** | 官方替换 AI 后 `vocab_id` 由 cefr+lemma 变 | 已按 D1 接受进度孤儿（真实用户进度集中在 A1） |

### 9.4 G2 预留设计（本轮只落结构，不落名单）
- **数据位**：`CORE_IDS_BY_LEVEL: Dict[str, frozenset[str]]`（现仅 `"A1"` → 213；22 自定义另表），位于 A1 数据模块或 `lexicon` 的等级配置。
- **谓词位**：`SCOPE_PREDICATES` 预留 `a2core` / `b1core` / `b2core`（**骨架就位，谓词体可先恒真或直接不注册**，加名单时只补数据）。
- **档位位**：`#scopeSeg` 加按钮 = 加 `data-scope` + 一行谓词（现有机制天然支持）。
- **本轮只做**：把 A1 现有的 `213/22` 改为**从 `CORE_IDS_BY_LEVEL` 读取**（零行为变化），其余等级留空位。**不挑 A2/B1/B2 的核心名单**。
- **迁移成本**：现在预留 ≈ 加两个空配置位；将来补名单 = 纯数据改动 + 一个按钮。

### 9.5 G3 富字段补齐（外部 agent 提示词）
delector 侧**无** A2/B1 的 IPA/例句来源（官方 5 元组、AI `core_dict_ext` 亦为 5 元组）→ 需用户 + 外部 agent 从权威源补齐，产出 **side-car 富字段分片**（不改 5 元组存储）。提示词见下，可直接复制给生成词表的 agent：

```text
# 任务：为歌德 A2/B1（及 A1 如需）官方词表补齐「音标 + 例句」富字段 side-car

## 输入（已存在，勿改）
- A1: 660 条 / A2: 736 条 / B1: 1617 条
- schema: lemma -> (cefr, pos, gender, plural, definition_zh)
- lemma 全小写、名词不带冠词、可分动词用连字符（an-sein、sich-anmelden）

## 目标输出（side-car，独立文件）
OFFICIAL_RICH = {
  "<lemma>": {"ipa": "", "example_de": "", "example_zh": "", "topic": "general"},
  ...
}

## 第 0 步（强制自检，先做再动手）
检查你生成词表时所用的权威源文件，回答：
  (1) 是否真的包含「音标」列？
  (2) 是否真的包含「例句」列（德文 / 中文）？
把结论写在交付说明第一条。分支：
  - 都有 → 从源照抄提取，禁止改写/编造。
  - 只有其一 → 只提取有的，缺项留空串并说明。
  - 都没有 → 不要生成！直接报告「源文件不含音标/例句」，请用户另定来源（词典/语料/AI）。

## 硬性约束
1. 禁止编造：无法溯源即留空，宁缺毋滥。
2. join key = lemma，必须与词表逐一对应。
3. 完整性：覆盖每一条 lemma（缺失显式空值），条数与源一致（660/736/1617），不得静默漏条。
4. 输出必须是 Python dict 字面量（Android/Chaquopy 无法运行期读 JSON），建议文件 official_vocab_rich.py。
5. 不改动现有 5 元组文件（存储 schema 冻结）。
6. 可复现：附源文件引用（页/行）、可重跑脚本、统计（有音标数/有例句数/缺失数）。
7. 若例句只有德文无中文：example_de 填原文、example_zh 留空；若你翻译了，必须标注哪些是机翻。

## 交付
1. official_vocab_rich.py（Python dict 字面量）
2. 交付说明：自检结论 + 来源引用 + 统计 + 机翻标注
```

### 9.6 结论
- 用户要的「A1 / A1核心 / A2 / B1 四档」**架构上已实现**，缺的是 **A2/B1 的"官方化"（G1）**——由本轮 R4 覆盖。
- **G2**：本轮只预留多级核心词结构（§9.4）。
- **G3**：由外部补齐富字段（§9.5），补回后再评估挂载（Phase 2 富字段派生）。
