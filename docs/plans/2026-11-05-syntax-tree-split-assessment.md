# 2026-11-05 `syntax_tree.py` 拆分可行性评估

> **性质**：只读评估 + 计划，**零生产代码改动**。本文之外不新增/修改任何 `.py`。
> **目标文件**：`delector/nlp_engine/syntax_tree.py`（1,569 行）。
> 任务书写的是 `delector/core/syntax_tree.py`，仓库中该路径不存在（`Grep` 报 `os error 2`）；
> 实际文件按 `delector/nlp_engine/syntax_tree.py` 采集，下文所有行号均以此为准。

## 1. 现状度量（实测）

工具：仓库 `.venv` 内 `radon 6.0.1`。

```
$ python -m radon cc -s -a delector/nlp_engine/syntax_tree.py
    F 593:0 analyze_sentence_topology - F (210)
    F 1079:0 _classify_single_clause - F (91)
    F 1319:0 build_clause_tree - F (45)
    F 519:0 _is_subjunctive_token - C (11)
    F 1468:0 split_sentences_pure_python - B (8)
    F 48:0 get_spacy_nlp - A (5)
    F 1545:0 analyze_syntax_tree - A (5)
    F 1501:0 _analyze_syntax_tree_pure_python - A (3)
    C 1025:0 ClauseNode - A (3)
    M 1058:4 ClauseNode.to_dict - A (3)
    F 38:0 get_spacy_load_error - A (1)
    F 550:0 format_token_dict - A (1)
    F 574:0 _empty_topology - A (1)
    M 1028:4 ClauseNode.__init__ - A (1)

14 blocks (classes, functions, methods) analyzed.
Average complexity: D (27.714285714285715)

$ python -m radon mi -s delector/nlp_engine/syntax_tree.py
delector/nlp_engine/syntax_tree.py - C (0.00)
```

| 符号 | 行范围 | 行数 | CC | 模块外 import 点 | 模块外提及行数¹ | 被 patch 次数² |
| --- | --- | --- | --- | --- | --- | --- |
| `get_spacy_load_error` | 38–45 | 8 | A (1) | 1（`routes/syntax_hard.py`） | 2 | 0（但模块全局被测试写 2 次，见 §3） |
| `get_spacy_nlp` | 48–66 | 19 | A (5) | 2（`syntax_hard.py`、`tests/test_syntax_tree.py`） | 31 | 0 |
| `_is_subjunctive_token` | 519–542 | 24 | C (11) | 0 | 0 | 0 |
| `format_token_dict` | 550–571 | 22 | A (1) | 0 | 0 | 0 |
| `_empty_topology` | 574–585 | 12 | A (1) | 0 | 0 | 0 |
| **`analyze_sentence_topology`** | **593–1017** | **425** | **F (210)** | **4**（`processor.py`、`nlp_engine/__init__.py`、`test_audit_regressions.py`、`test_syntax_tree.py`） | 14 | 0 |
| `ClauseNode` | 1025–1076 | 52 | A (3) | 0 | 0 | 0 |
| `_classify_single_clause` | 1079–1316 | 238 | F (91) | 0（仅 `syntax_score.py:213` 文档字符串提及） | 1 | 0 |
| `build_clause_tree` | 1319–1454 | 136 | F (45) | 3（`processor.py`、`__init__.py`、`tests/test_syntax_tree.py`） | 19 | 0 |
| `split_sentences_pure_python` | 1468–1498 | 31 | B (8) | 7（`processor.py`、`__init__.py`、`listen.py`、`syntax_hard.py`、`essay_diff.py`、`syntax_score.py`、`test_server_android_fallback.py`） | 32 | 0 |
| `_analyze_syntax_tree_pure_python` | 1501–1542 | 42 | A (3) | **1 私有符号**（`tests/test_server_android_fallback.py:47`） | 4³ | 0 |
| `analyze_syntax_tree` | 1545–1569 | 25 | A (5) | 5（`__init__.py`、`routes/main.py`、`syntax_hard.py`、`syntax_score.py`、`tests/test_syntax_tree.py`） | 61 | 0 |

¹ 模块外提及行数包含注释/文档字符串/fixture 文本，不等于"真实调用点"；真实 import 点一列已单独列出。
² 指 `patch("delector.nlp_engine.syntax_tree.<name>")` 或 `monkeypatch.setattr(<syntax_tree 模块>, "<name>", ...)` 的直指本模块次数。
³ `syntax_score.py:12` 与 `tools/bench_rank_sentences.py:220` 均为文档字符串提及；唯一真实 import 是 `tests/test_server_android_fallback.py:47`。

**关键事实**：CI 里**没有** radon/复杂度门禁（全仓 `radon|cyclomatic|complexity` 在 `.py` 中零命中）。拆分只会改变分布，不会让任何门禁变绿。

---

## 2. 问题一：425 行里真分支 vs 顺序取字段

统计脚本（AST，逐行归属 + 分支统辖）：函数体 593–1017，共 **425 物理行**。

### 2.1 结构计数

| 项 | 数量 |
| --- | --- |
| `if` 语句节点（含 23 个 `elif`） | 79 |
| 独立 `else:` 头 | 12 |
| `for` 语句 | 15 |
| `while` / `try` / `match` | 0 / 0 / 0 |
| 最大控制嵌套深度 | **11 层** |
| `BoolOp` 节点（`or` 30 / `and` 26） | 56 |
| 三元表达式 `IfExp` | 12 |
| 推导式内 `if` | 9 |
| 比较运算 `Compare` | 118 |
| 赋值语句（含分支体内） | 129 |
| `.append()` 调用 | 12 |
| 推导式总数 | 29 |

**CC 210 的来源**：79 个 `if` + 15 个 `for` + 56 个布尔节点（每个多值 `BoolOp` 贡献 n−1）+ 12 个三元 + 9 个推导式 `if`。**不是 425 行本身**——大量多行布尔条件是复杂度主因。

### 2.2 行级占比（两种口径，互不矛盾）

**口径 A：逐行唯一归属**

| 类别 | 行数 | 占比 |
| --- | --- | --- |
| 控制语法头（`if`/`elif`/`else`/`for`） | 106 | 24.9% |
| docstring | 21 | 4.9% |
| 空行/注释（不含 docstring 内 1 空行） | 69 | 16.2% |
| 其余（顺序语句、分支体语句、多行续行、闭括号） | 229 | 53.9% |
| 合计 | 425 | 100% |

**口径 B：分支统辖**

| 类别 | 行数 | 占比 |
| --- | --- | --- |
| 被任一控制块统辖（含头与全部嵌套体） | 313 | 73.6% |
| 其中：分支体内非头行 | 207 | 48.7% |
| **无任何分支包夹的直线代码** | **61** | **14.4%** |

**结论（数据层面）**：
- "真分支语法"只占 106 行（24.9%），真正无条件的顺序代码只有 61 行（14.4%）；
- 大头是**分支体内的字段组装**（207 行），其内容以 129 条赋值 + 12 次 `append` + 推导式为主，不是新逻辑；
- 因此"整块搬走"是可行的：分支体是数据装配，不是条件判断本身；条件判断集中在少数几处（见下表 B2/B3/B4/B9/B12）。

### 2.3 可整块搬走的候选块

行号为首行；局部变量只列函数内局部名（`tokens`/`clause_type` 等入参也算输入）。

| 块 | 行范围 | 行数 | 读（局部变量） | 写（局部变量） |
| --- | --- | --- | --- | --- |
| B1 非标点过滤 | 640–642 | 3 | `tokens` | `non_punct_tokens` |
| B2 主句有限动词候选扫描 | 645–659 | 15 | `tokens` | `has_main_finite_verb`、`main_fin_candidate` |
| B3 不定式检测 | 662–684 | 23 | `clause_type`、`non_punct_tokens`、`tokens` | `is_infinitiv`、`is_subordinate`（初始化）、`connector_tokens` |
| B4 从句检测 | 687–709 | 23 | `is_infinitiv`、`has_main_finite_verb`、`non_punct_tokens`、`tokens` | `is_subordinate`、`connector_tokens` |
| B5 `clause_type` 覆盖 | 712–720 | 9 | `clause_type` | `is_infinitiv`、`is_subordinate` |
| B6 字段初始化 | 725–732 | 8 | — | `vf/lk/mf/rk/nf_tokens`、`sentence_type`、`bracket_desc` |
| B7 INFINITIVGRUPPE 分配 | 734–772 | 39 | `connector_tokens`、`tokens` | `vf/lk/mf/rk/nf_tokens`、`sentence_type`、`bracket_desc` |
| B8 SUBORDINATE 分配 | 774–816 | 43 | `connector_tokens`、`non_punct_tokens`、`tokens` | `vf/lk/mf/rk/nf_tokens`、`sentence_type`、`bracket_desc` |
| B9 MAIN V2/V1 分配 | 818–942 | 125 | `main_fin_candidate`、`tokens`、`non_punct_tokens`、`mf_tokens`、`nf_tokens` | `fin_verb`、`vf/lk/rk_tokens`、`sentence_type`、`bracket_desc`、`extraposed_start_id` |
| B10 嵌套函数 `to_text` | 947–956 | 10 | `toks`（参数） | 纯返回字符串 |
| B11 `field_texts` 组装 | 958–964 | 7 | `vf/lk/mf/rk/nf_tokens`、`to_text` | `field_texts` |
| B12 bracket 判定 | 966–1005 | 40 | `lk/rk/mf_tokens`、`is_infinitiv`、`is_subordinate`、`_is_subjunctive_token` | `bracket_desc`（含 7 个临时布尔量） |
| B13 返回 dict | 1007–1017 | 11 | `vf/lk/mf/rk/nf_tokens`、`field_texts`、`sentence_type`、`bracket_desc`、`clause_type` | 纯返回 dict |

另：模块级常量 `SUBORDINATING_CONJUNCTIONS` 等 7 个表占 **74–516 行（443 行，28.2%）**，模块外零引用，是更大的一块纯搬移候选（见 P1-0）。

---

## 3. 问题二：测试 patch 点与模块外私有符号引用

### 3.1 全部 `patch` / `monkeypatch.setattr` 命中（实测）

| 文件:行号 | 被 patch 的名字 | 指向的模块 | 搬移影响 |
| --- | --- | --- | --- |
| `tests/test_syntax_score.py:293` | `analyze_syntax_tree` | `delector.services.syntax_score`（消费方） | **不受影响**：patch 的是消费方已导入名 |
| `tests/test_syntax_score.py:319` | `analyze_syntax_tree` | 同上 | 不受影响 |
| `tests/test_syntax_score.py:335` | `analyze_syntax_tree` | 同上 | 不受影响 |
| `tests/test_syntax_score.py:359` | `analyze_syntax_tree` | 同上 | 不受影响 |
| `tests/test_syntax_hard_api.py:300` | `analyze_syntax_tree` | `delector.routes.syntax_hard`（消费方） | 不受影响 |
| `tests/test_syntax_hard_api.py:438` | `get_spacy_nlp` | `delector.routes.syntax_hard`（消费方） | 不受影响 |
| `tests/test_syntax_hard_api.py:439/444/447` | `syntax_tree._spacy_load_error`（**直接赋值模块全局，不是 patch**） | `delector.nlp_engine.syntax_tree` | **必须留在原模块**：`get_spacy_load_error` 必须与该全局同一模块，否则 v5.7.5 诊断回归测试失效 |

**全仓不存在 `patch("delector.nlp_engine.syntax_tree.<名字>")` 形式的直接 patch。** 内部 helper 的 patch 次数全部为 0。

### 3.2 模块外 import 私有符号的点

| 文件:行号 | 符号 | 性质 | 判定 |
| --- | --- | --- | --- |
| `tests/test_server_android_fallback.py:47` | `_analyze_syntax_tree_pure_python` | **真实 import** | 搬走则断测试 → 必须原地 re-export，或同步改测试（P2） |
| `delector/services/syntax_score.py:12` | `_analyze_syntax_tree_pure_python` | 文档字符串提及 | 无影响 |
| `delector/services/syntax_score.py:213` | `_classify_single_clause` | 文档字符串提及 | 无影响 |
| `tools/bench_rank_sentences.py:220` | `_analyze_syntax_tree_pure_python` | 文档字符串提及 | 无影响 |

`format_token_dict` / `_empty_topology` / `_is_subjunctive_token` / `ClauseNode` / `_classify_single_clause：模块外 import 点均为 0。

### 3.3 公开符号的消费点（搬移时必须保持同一对象）

- `analyze_syntax_tree`：`delector/nlp_engine/__init__.py`（再导出）、`delector/routes/main.py:69`、`delector/routes/syntax_hard.py:30`、`delector/services/syntax_score.py:23`、`tests/test_syntax_tree.py:5`。
- `analyze_sentence_topology`：`delector/nlp_engine/processor.py:19`、`delector/nlp_engine/__init__.py`、`tests/test_audit_regressions.py:21`、`tests/test_syntax_tree.py:5`。
- `build_clause_tree`：`processor.py:19`、`__init__.py`、`tests/test_syntax_tree.py:5`。
- `split_sentences_pure_python`：`processor.py:19`、`__init__.py`、`routes/listen.py:25`、`routes/syntax_hard.py:30`、`services/essay_diff.py:14`、`services/syntax_score.py:23`、`tests/test_server_android_fallback.py:47`。
- `get_spacy_nlp` / `get_spacy_load_error`：`routes/syntax_hard.py:30`。
- 工具脚本 `tools/bench_cold_start.py`、`bench_long_read.py`、`bench_rank_sentences.py` 通过 `importlib.import_module("delector.nlp_engine.syntax_tree")` + 属性访问，只要 re-export 保留即不变。

**问题二结论**：拆分对测试的破坏面只有两处——
1. `_analyze_syntax_tree_pure_python` 被测试直接 import（唯一私有符号泄露）；
2. `_spacy_load_error` 模块全局被测试直接赋值，与 `get_spacy_load_error` 强耦合。
其余 patch 点全在消费方模块，搬内部 helper 不受影响。

---

## 4. 问题三：拆完之后能不能有等价性证据

### 4.1 可用判据（coKernel 式 + 补强）

1. **搬移块 AST 差集为零**：提取前后，对"原块语句序列"与"新函数 body"做 `ast.dump` 比对；允许的差异只有（a）外层 `FunctionDef` 包裹、（b）为写出调用方变量而新增的 `return`、（c）形参接收（变量名不变）。**任何谓词/操作符/常量变化都必须为 0**。比字节 SHA 更强：缩进无关，且能证明"没有顺手改逻辑"。
2. **字节级 SHA（辅证）**：原块源码 `textwrap.dedent` 后与新函数 body `textwrap.dedent` 后做归一化 SHA-256；仅用于人读的快速校验。
3. **消费点逐个 `hasattr` + 同一性断言**（一次性加进 `tests/test_syntax_tree.py`）：
   ```python
   import delector.nlp_engine.syntax_tree as st
   import delector.routes.syntax_hard as sh
   import delector.services.syntax_score as ss
   import delector.routes.listen as ln
   import delector.services.essay_diff as ed
   import delector.nlp_engine.processor as pr
   assert sh.analyze_syntax_tree is st.analyze_syntax_tree
   assert ss.analyze_syntax_tree is st.analyze_syntax_tree
   assert ln.split_sentences_pure_python is st.split_sentences_pure_python
   assert ed.split_sentences_pure_python is st.split_sentences_pure_python
   assert pr.analyze_sentence_topology is st.analyze_sentence_topology
   ```
4. **差分行为测试（golden corpus）**：固定语料 + 固定 tokenizer 输出（有 spaCy 用已装模型、无则显式 `pure` 路径），对拆分前后各跑一次 `json.dumps(result, sort_keys=True, ensure_ascii=False)`，逐句字符串相等。语料至少覆盖：V1、V2、VL、Infinitiv（`um/ohne/anstatt...zu`）、Passiv（Vorgangs/Zustands）、Konjunktiv、关系从句、前置从句、后置从句、嵌套从句、空输入、纯标点输入、单句无动词。
5. **逐块提交**：一块一个 commit，每 commit 后跑 3+4；**搬移 commit 内禁止顺手重构**（这是 SHA 判据能成立的前提）。

### 4.2 盲区（必须写清）

- **`assertIs` / `hasattr` 抓不到"被搬走模块自己的实现被就地改"**：把 `<=` 改成 `<`、`or` 改成 `and`，签名和对象身份都不变，同一性断言照过。
- **同一性断言也抓不到"旧实现副本仍留在原模块"**：消费者拿到的对象是新函数的，但旧函数体若未被删除，不会有人发现两套实现并存。
- **字节 SHA 只覆盖搬移那一次 commit**：后续任何编辑都会让 SHA 失效，所以必须逐块搬、逐块验，不能"一次搬完再统一验证"。
- **差分测试只覆盖语料内句子**：824 行语料外的新德语结构，行为变化不可见。

### 4.3 逐块等价性判定

| 块 | 能否证明等价 | 结论 |
| --- | --- | --- |
| B1、B2、B3、B4、B5、B6、B7、B8、B10、B11、B12、B13 | 能：AST 差集为零或仅新增 `return`；现有 15 句语料即可覆盖各分支 | 可搬（P1） |
| 常量 74–516 | 能：纯字面量搬移，模块外零引用；AST 差集为零 | 可搬（P1） |
| B9（125 行） | **现有语料不足**：5 级优先链的兜底分支（Priority 3/4/5）在 15 句语料中未必全部命中；需 ≥50 句覆盖 corpus 才能证明 | **暂不搬**（P2 前置条件未满足） |
| `_spacy_load_error` 三件套 | 搬移本身可证，但测试直接写模块全局，搬后必须改测试，收益仅 27 行 | **不拆** |
| B9 内部五级优先链重写 | 不能：顺序即语义，改成 provider 列表是逻辑重写 | **不拆**（P3） |
| `_classify_single_clause`（CC 91）拆分 | 不能：分支判定需重写，无黄金语料 | **不拆**（P3） |
| `build_clause_tree`（CC 45）拆分 | 不能：同样缺少语料与判据 | **不拆**（P3） |

---

## 5. 分级计划

> 分级口径沿用任务书：P1 = 纯搬移、零行为风险、有等价性证据；P2 = 需要同步改测试的搬迁（本计划把"需要更高证据门槛（扩语料）"的 B9 也归入 P2，并显式标注）；P3 = 必须重写逻辑才能拆。

### P1：纯搬移（建议执行）

| # | 内容 | 规模 | 前置条件 | 验证 | 回滚 |
| --- | --- | --- | --- | --- | --- |
| P1-0 | 新建 `delector/nlp_engine/syntax_tables.py`，搬 74–516 的 7 个常量表 | 443 行 | 确认模块外零引用（已实测） | AST 差集为零；`grep` 常量名只在新旧两处；全量 pytest | 单 commit `git revert` |
| P1-1 | 新建 `delector/nlp_engine/syntax_fields.py`，搬 B1/B2 | 18 行 | P1-0 完成（模块依赖方向单向：fields → tables） | 块 AST 差集为零 | 单 commit revert |
| P1-2 | 搬 B3/B4/B5 | 55 行 | 同上 | 同上 + 从句检出用例 | 同上 |
| P1-3 | 搬 B7/B8 | 82 行 | 同上 | 同上 | 同上 |
| P1-4 | 搬 B10/B11/B13 | 28 行 | 同上 | 同上 | 同上 |
| P1-5 | 搬 B12 bracket 判定 | 40 行 | 同上 | 同上 + Passiv/Modal/Konjunktiv 用例 | 同上 |

- 累计净移动：**443 + 223 = 666 行**；`analyze_sentence_topology` 从 425 行降到约 **215 行**（含 docstring/空行），`syntax_tree.py` 从 1,569 行降到约 **900 行**。
- 新增 2 个文件；`syntax_tree.py` 保留 façade（`from .syntax_tables import *` 的显式具名导入 + `from .syntax_fields import <helper>`），消费方 import 路径全部不变。
- **依赖方向**：`syntax_fields.py` 只 import `syntax_tables.py`；`syntax_tree.py` import 两者。`_is_subjunctive_token` 若被 helpers 使用，需随 B12 一起搬到 `syntax_fields.py`（它模块外零引用，属纯搬移）。

### P2：需要同步改测试或提高证据门槛（建议暂缓）

| # | 内容 | 规模 | 阻塞点 |
| --- | --- | --- | --- |
| P2-1 | 搬 `_analyze_syntax_tree_pure_python` 到 `syntax_api.py` | 42 行 | 必须同步改 `tests/test_server_android_fallback.py:47` 的 import，或原地 re-export |
| P2-2 | 搬 B9（V2/V1 主句分配） | 125 行 | 语料需扩到 ≥50 句并覆盖 5 级优先链兜底分支；否则等价性不可证 |
| P2-3 | 公开 API 三件套搬入 `syntax_api.py` | 约 200 行 | 需保留 re-export + 新增 4 条同一性断言；`tests/test_nlp_model_sm_only.py:23/51` 按文件路径断言 `SPACY_MODEL_NAME`，要求 `get_spacy_nlp` **留在 `syntax_tree.py`** |

### P3：必须重写逻辑（本轮明确不做）

| # | 内容 | 规模 | 不做的理由 |
| --- | --- | --- | --- |
| P3-1 | `_classify_single_clause`（238 行，CC 91）内部拆分 | — | 分类判定需重写；无黄金语料；模块外零引用，搬整函数可以但 CC 不降 |
| P3-2 | `build_clause_tree`（136 行，CC 45）内部拆分 | — | 同上 |
| P3-3 | B9 内部五级优先链改为 provider 列表 | — | 顺序即语义，属逻辑重写，不是搬移 |
| P3-4 | B7/B8 尾段（758–770 与 802–815 逐字相同，13×2 行）去重 | 26 行 | 合并涉及语义统一（`extraposed_start_id` vs `min/max_rk_id` 边界差异），需行为重写与语料 |

---

## 6. 明确"不做"的部分（当结论写）

1. **不拆 `_spacy_load_error` / `get_spacy_nlp` / `get_spacy_load_error` 三件套**。测试直接写 `syntax_tree._spacy_load_error`，这是 v5.7.5 真机诊断回归的锚点；搬走必须改测试，收益仅 27 行，风险大于收益。
2. **不重写 B9 内部的五级优先链**（Priority 1–5）。顺序即语义；改成可插拔 provider 是逻辑重写，现有语料无法证明等价。
3. **不拆 `_classify_single_clause` 与 `build_clause_tree` 的内部**。两者是 CC 91/45 的真分支源，拆分等于重写分类器；没有黄金语料前不动。
4. **不做"一个字段一个函数"**。61 行无条件直线代码切成 10+ 次调用，净收益为负。
5. **不把 `ClauseNode` 改成 dataclass**。与拆分无关，且会改变 `to_dict` 序列化行为。
6. **不引入 radon 门禁**。CI 无复杂度判据，拆分不会让 radon 变绿。**实测修正（2026-11-05）**：原句写"CC 只是从主函数搬到 helper，总复杂度不变"是未执行的推测，已被实测证伪——P1 落地后 `analyze_sentence_topology` 的 CC 从 **210 降到 86**（行数 425 → 234），并非不变；各 helper 的 CC 见 §9.1。

---

## 7. 一句话结论

**建议只动 P1**：先把 7 张常量表（443 行）与 11 个纯搬移块（223 行）迁到 `syntax_tables.py` / `syntax_fields.py`，`syntax_tree.py` 保留 façade 与编排；主函数 425 → 约 215 行、文件 1,569 → 约 900 行，**零逻辑变更**，每块可用"AST 差集为零 + 消费点同一性 + 差分语料"三重证据闭环。P2 等语料补齐后再议，P3 与第 6 节各项**不拆**。

**改动规模预估（P1）**：新增 2 个 `.py`，移动 666 行，`syntax_tree.py` 净减约 660 行；约 6 个可独立回滚的 commit；不新增依赖、不改测试断言。

---

## 8. 执行顺序与验证（P1 落地时的清单）

1. `git switch -c refactor/syntax-tree-p1-fields`（若走 PR）。
2. P1-0 常量搬移 → 单测 → commit。
3. P1-1 … P1-5 逐块搬移 → 每块跑：
   - `ruff check delector tools tests`
   - `mypy --strict delector`（沿用仓库现有口径）
   - `pytest tests/test_syntax_tree.py tests/test_syntax_hard_api.py tests/test_syntax_score.py tests/test_audit_regressions.py tests/test_server_android_fallback.py`
   - 块级 AST 差集脚本（本地脚本，不提交）
   - golden corpus 差分（本地脚本，不提交）
4. 全部完成后再跑一次全量 7 分片 CI。
5. 回滚：按 commit 逆序 `git revert <sha>`；因块间行范围互不重叠，单块 revert 通常无冲突。

**前置依赖**：P1 不需要改任何测试；若发现任何块需要改测试，降级为 P2 并单独提交。

---

## 9. 执行结果与遗留（2026-11-05 实测）

> 本节为事后追记：§5/§7 是执行前的**预估**，以下为 P1 落地后的**实测**；P2 经运行时计数判定**不可做**（未执行），仅作挂账。证据脚本在仓库外 `D:\Code\_artifacts\`，未提交。

### 9.1 P1 已执行（已合并）

P1 按 6 个可独立回滚的提交推进，PR #231（分支 `refactor/syntax-tree-p1`）以 merge commit `fa6c6c2` 合入 master。

| 指标 | 拆分前 | 拆分后（实测） |
| --- | --- | --- |
| `syntax_tree.py` 行数 | 1,569 | **926** |
| `syntax_tables.py` | — | **453**（7 张表 443 行 + 文件头/导入） |
| `syntax_fields.py` | — | **347**（11 个搬移块 223 行 + `_is_subjunctive_token` 24 行 + 包装/导入） |
| `analyze_sentence_topology` 行数 | 425（593–1017） | **234**（140–373） |
| `analyze_sentence_topology` CC | 210 | **86** |

- 搬移后各 helper 的 CC（radon）：`_is_subjunctive_token` 11、`filter_non_punct_tokens` 5、`find_main_finite_verb` 7、`detect_clause_type` 43、`allocate_infinitiv_fields` 20、`allocate_subordinate_fields` 22、`to_text` 6、`build_field_texts` 1、`build_topology_result` 6、`detect_bracket_structure` 28。
- 与 §7 预估的偏差：主函数预估「约 215 行」→ 实测 **234 行**；文件预估「约 900 行」→ 实测 **926 行**；差额来自 facade 显式导入、调用点改写与注释，无新增逻辑。
- 等价性证据：18/18 逐块 AST 全等（7 张 tables + 11 个搬移块；`_is_subjunctive_token` 另 1 项全等）；106 句语料 / 466 次结果比较 **0 不等**；全量 `pytest tests` **2782 passed / 3 skipped**；`mypy --follow-imports=skip` Success；`ruff check delector tools tests` All checks passed。两条变异（`INFINITIVE_CONNECTORS` 键 `anstatt`→`anstattX`；`abs(v.i - cluster[-1].i) <= 2` → `< 2`）分别被具名用例与差分语料判红，均已还原、`git diff` 为空。
- 依赖方向：`syntax_tables` ← `syntax_fields` ← `syntax_tree`，无反向 import；两个新模块均不 import `syntax_tree`。

### 9.2 P2 判定：不可做（不执行）

P2-2（搬 B9，125 行）的准入条件是「语料扩到 ≥50 句并覆盖 5 级优先链兜底分支」。运行时实测：

- **语料口径 106 句**：测试句 42 + `OFFICIAL_CORPUS` 64（12 篇、64 句全部纳入），**无余量可补**。
- B9 五级优先链运行时逐级计数（真实执行；插桩版与原模块在 106 句上输出 **0 不等**，证明插桩不改行为）：

| 级别 | 命中句数 |
| --- | --- |
| 预置（`main_fin_candidate` 非空） | 13 |
| L1（`text.lower()` ∈ `FINITE_MODAL_AND_AUX_FORMS` 且 `tag_` ∉ {VAINF, VMINF, VVINF}） | 25 |
| L2（`dep_ == "ROOT"` 且 `tag_` ∈ {VVFIN, VAFIN, VMFIN}） | 53 |
| L3（`tag_` ∈ {VVFIN, VAFIN, VMFIN} 且 `dep_` ∉ {rc, re, cp}） | **0** |
| L4（`dep_ == "ROOT"` 且 `pos_` ∈ {VERB, AUX}） | 1 |
| L5（`pos_` ∈ {VERB, AUX} 或 `text.lower()` ∈ 有限情态/助动词表） | **0** |
| 兜底（`fin_verb is None and tokens`） | 8 |
| none（`tokens` 为空） | 0 |

进入 B9 共 **100/106**（其余 6 句走 `is_infinitiv` / `is_subordinate` 分支）。

- **L3/L5 零命中的原因**：德语主句的正常解析会把限定动词标为 `ROOT` + `VVFIN/VAFIN/VMFIN`，**L2 先命中**，L3/L5 永远轮不到；L5 即使 L1–L4 全落空，也会先被兜底（`non_punct_tokens[0]`）截走，即被兜底遮住。
- L4 的唯一例句：`Aus diesem Grund etablieren viele moderne Unternehmen hybride Modelle mit zwei bis drei Präsenztagen pro Woche.`（`etablieren` i=3、dep=`ROOT`、tag=`VVINF`、pos=`VERB`：L2/L3 的 `tag_` 条件不满足，落到 L4）。
- 兜底例句：`Kommst du morgen zur Party mit?`、`Lies bitte diesen deutschen Text aufmerksam durch!`。
- **补真实语料无法解决**：要覆盖 L3/L5 只能构造 `Token` fixture（人工指定 `dep_` / `tag_` / `pos_`），真实语料补不进自然句——自然主句解析就是 L2 先命中。
- 结论：按「行为差分」判据 **P2 不可做**；即便改以 AST 等价为主判据，也缺 L3≥2、L5≥2、L4 再补 2 的运行时证据（至少 6 例，保守 8 例），且这些证据只能来自人工 fixture，不等价于真实输入覆盖。

### 9.3 遗留（挂账）

- **L3 与 L5 处于「代码存在、但从未被真实输入执行」状态**（本 106 句口径下命中 0）。
- **是否属于历史遗留死代码、能否删除——未判定，需要反证**。删除前必须证明该分支在真实语料（含更长句子、特殊断句、不同 spaCy 解析结果）中不可达，或确认它与兜底语义等价；**不可仅凭「零命中」删除**。
- 该项不阻塞 P1 交付，P2 也不推进；后续若要处置，按独立任务补反证与回归语料。

### 9.4 临时脚本（仓库外，未提交）

- `D:\Code\_artifacts\p2_b9_coverage.py`：B9 五级链运行时插桩与 106 句计数。
- `D:\Code\_artifacts\syntax_tree_instrumented.py`：运行时生成的插桩副本（相对 import 改绝对、插入 `_B9_TRACE`）；用于证明插桩不改行为（106 句 0 不等）。
