# M4-3 评审：`build_clause_tree` 从句拓扑去重

> 计划：`docs/plans/2026-09-03-audit-hardening-m1-m5.md` Task M4-3（可选/回归高风险）
> 评审日期：2026-09-03　状态：**维持「跳过」为正确决定（带证据）**
> 结论速览：原始假设不成立——生产读路径**不存在**「每从句重跑 spaCy」的重复解析；
> 残余可去重面是每从句 O(子句长度) 的纯 Python 字段分配，去重需把子句切分与五字段
> 分配深度耦合重写，行为回归面与收益严重不匹配。

---

## 1. 原始假设（计划 Task M4-3）

> `build_clause_tree` :1143 每从句重算 `analyze_sentence_topology(sent)` → 复用整句
> 一次计算结果下传，消掉每从句重复的 topology 计算（含可能的重复 spaCy 解析）。

## 2. 证据：组合路径已每句只解析一次 spaCy

调用链核查（`nlp.py` 为唯一生产组合点）：

```text
process_german_text(text)                        nlp.py:253
  doc = nlp(text)                                nlp.py:256   ← 全句只在此解析一次
  for sent in doc.sents                          nlp.py:259   sent 是 Span
    top   = analyze_sentence_topology(sent)      nlp.py:310   Span → 不触发 str 分支
    tree  = build_clause_tree(sent)              nlp.py:311   Span → 不触发 str 分支
```

- `analyze_sentence_topology`（syntax_tree.py:363）的 str 分支（:389-395）只在入参是
  str 时才调 `get_spacy_nlp()`；Span/Doc/list 直接取 token。
- `build_clause_tree`（syntax_tree.py:1036）str 分支同理（:1062-1066）；Span/Doc 直接用。
- 从句级调用（:1143）`analyze_sentence_topology(sent, clause_tokens=tokens,
  clause_type=node.type)` 走 `clause_tokens is not None → tokens = clause_tokens`
  （:406-407）分支，token 已由整句一次解析得到，**全程零额外 spaCy 解析**。
- 另一个组合函数 `_analyze_syntax_tree_doc`（syntax_tree.py:1260-1273）同样以
  `doc.sents` 的 Span 传入，无重复解析。
- 全仓生产代码（server.py:410 / database.py:483 及其他）均经 `process_german_text`
  或上述 doc 级入口；独立 str 直调仅存在于测试模块（test_syntax_tree.py、
  test_audit_regressions.py），非生产热点。

**结论**：M4-3 原假设所针对的「每从句重算 = 可能的整句二次 spaCy 解析」在生产读路径
**不成立**。spaCy 解析开销本就每句恰一次。

## 3. 残余可去重面的量级与难度

真正「每次从句调用」重复做的只有：`analyze_sentence_topology` 对**该子句 token 子集**
的多次线性扫描（connector 判定、`rk_candidates` 过滤、逐 token 落场等，均为
O(子句长度) 常数次），以及 `_classify_single_clause` 的同级扫描。量级估算：典型从句
20-60 token、每函数若干次 list 推导，单次调用 <0.1ms 级（dict 构造与 list 扫描），
相对整句 spaCy（几十 ms 级）可忽略。

去重若要共享「一次整句 pass」，必须同时满足：

1. 子句切分依赖整句依赖树与 token 序号（syntax_tree.py:1126-1136 的
   `head.subtree` 排序 + 逗号并入），与字段分配在 pass 顺序上强耦合；
2. `analyze_sentence_topology` 支持 `clause_type` 显式覆盖（:477-485），
   build_clause_tree 逐节点传 `node.type`（:1143）——同一句内不同子句类型各异，
   单一 pass 需同时满足 V2/VL/Infinitiv 多套字段边界规则；
3. 行为依赖子句边界的局部修正（逗号处理），去重任一改错即造成错句整体 topology
   污染（MF/RK 越界、bracket_structure 描述错），回归检测只能靠全量 golden diff。

即：这是一个**行为最敏感、需 golden 快照才能可靠验证**的重构，符合计划「跳过留证」
条款（plan M4-3：「若评估为不可安全去重，记录结论并跳过」）。

## 4. 结论

- **维持跳过**。不是「没空做」，而是证据显示目标开销在生产读路径基本不存在，
  残余优化面回报 <2% 且风险集中在读路径全链路输出形状。
- 读路径主开销中的「每次调用重建成本」已由同批次零风险改动覆盖：
  - M4-1：writing_rules / linguistics / nlp / syntax_tree 的常量与正则模块级提升；
  - M4-2：`split_komposita` JSON 背衬 lru + `lookup_core_vocab` 共享命中条目缓存
    （均带防共享变异保护 + RED→GREEN 测试）。
- 若未来仍要压 analyze 常数开销，前置条件是**先固化全量 golden 快照**再谈行为 diff；
  不建议在无快照下推进。

## 5. 验证记录（证据引用）

- `nlp.py:253-311`（组合点，Span 传入）
- `syntax_tree.py:389-407`（analyze 的 str/clause_tokens 分支）、`:1062-1075`
  （build_clause_tree 的 str/Span/Doc 分支）、`:1143`（从句级调用带 clause_tokens）、
  `:1260-1273`（_analyze_syntax_tree_doc 组合）
- 服务端全部消费经 `process_german_text` / doc 级入口；str 直调仅测试用
- 相关测试全绿：test_syntax_tree（15）、test_audit_regressions（含
  `analyze_sentence_topology` 回归，11）等定向子集
