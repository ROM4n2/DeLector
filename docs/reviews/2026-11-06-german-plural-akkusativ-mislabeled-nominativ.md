# 德语复数第四格名词被标为主格：最小复现记录

> 状态：**OPEN** —— 本轮只做复现与记录，未修改任何标注行为。
> 基线：`origin/master` @ `3007fb0`；工作树仅有一个与本次无关的未跟踪文件。
> 环境：Windows / Python 3.11.8 / spaCy 3.8.18 / `de_core_news_sm` 3.8.0。
> 复现入口：`delector.nlp_engine.syntax_tree.analyze_syntax_tree`。

## 0. 文档位置

放在 `docs/reviews/`，沿用 [2026-10-20-rd-api-export-guard-escape.md](2026-10-20-rd-api-export-guard-escape.md) 的「一次性缺陷/守卫逃逸复现记录」先例；未新建目录。

## 1. 原始句追溯

用户记忆中的弃用句包含 `den Schülern … die Bücher`，但没有留下完整原文。已检索：

- `static/views/home.html`、`static/js/satz-lab.js`、`static/index.html`、`WORKMEMORY/work.log`：没有该句。
- `git log --all -S "Schülern"`：只命中两条与介词词表相关的提交，不是首屏示例句。
- `git log --all -S "Bücher" -- static/js/satz-lab.js static/views/home.html static/index.html`：无命中。
- 当前 [satz-lab.js](../../static/js/satz-lab.js#L10-L14) 的三条示例是：
  - `Die Lehrerin gibt dem Schüler das Buch.`
  - `Das Buch wurde von dem Lehrer empfohlen.`
  - `Weil es heute regnet, bleiben wir zu Hause.`

第一条是**单数**双宾句，实测 `Buch` 为 `Acc`，不复现。原弃用句不可追溯，因此本文自构造：

```text
Die Lehrerin gibt den Schülern die Bücher.
```

选择它的理由：`den Schülern` 是明确的复数第三格（`den` + `-n`），`die Bücher` 只能是复数第四格宾语；并且**已用真实引擎实测它复现错标**，不是按预期凑出来的。

## 2. 复现：精确输入与实际输出

### 2.1 输入

```text
Die Lehrerin gibt den Schülern die Bücher.
```

### 2.2 实际输出（token 投影）

下表逐字段取自 `analyze_syntax_tree()` 的真实返回；完整 JSON 原文见[附录 A](#附录-a完整输出原文)。

| id | text | pos | dep | case |
| --- | --- | --- | --- | --- |
| 0 | Die | DET | nk | Nom |
| 1 | Lehrerin | NOUN | sb | Nom |
| 2 | gibt | VERB | ROOT | （空） |
| 3 | den | DET | nk | Dat |
| 4 | Schülern | NOUN | da | Dat |
| 5 | die | DET | nk | Acc |
| 6 | **Bücher** | **NOUN** | **oa** | **Nom** |
| 7 | . | PUNCT | punct | （空） |

矛盾点：`Bücher` 的依存标签是 `oa`（accusative object，第四格宾语），同一 token 的 `case` 却是 `Nom`；同一名词短语的限定词 `die` 又是 `Acc`。前端只给 `NOUN/PRON/PROPN` 上格位标签，所以用户看到的是「Bücher · 主格」。

### 2.3 对照组

同一构造改用单数 `Buch`：

```text
Die Lehrerin gibt dem Schüler das Buch.
```

实测 `Buch` 为 `NOUN / oa / Acc`，正确。说明问题不是「所有双宾句都错」，而是与具体词形/模型预测有关。

## 3. 期望输出与依据

期望 `Bücher` 的 `case` 为 `Acc`（第四格）。依据：

1. `geben` 是双宾动词：`jemandem (Dat) etwas (Akk) geben`。
2. `den Schülern` 是复数第三格：`den` 是复数第三格冠词，`Schülern` 带第三格复数词尾 `-n`；引擎自身也给出 `dep=da`、`case=Dat`。
3. 剩下的 `die Bücher` 是「被给的东西」，只能是第四格宾语；引擎自身也把 `die` 标成 `Acc`、把 `Bücher` 的依存标成 `oa`。
4. 因此同一 NP 内「限定词 `Acc` + 名词 `Nom`」自相矛盾。`Bücher` 的 Nom/Akk 复数同形，单看词形无法区分，但句法位置和限定词已经足以定为 `Acc`。

## 4. 最小化

### 4.1 对原句逐词删除（穷举子集）

对原句 7 个词的所有非空保序子集（必须保留 `Bücher`）逐一调用真实引擎，判定条件为：

```text
Bücher.dep == "oa" and Bücher.case == "Nom"
```

全部 9 条命中如下（按词数升序）：

```text
4  gibt den Schülern Bücher.
4  gibt den die Bücher.
5  Die gibt den Schülern Bücher.
5  Lehrerin gibt den Schülern Bücher.
5  gibt den Schülern die Bücher.
6  Die Lehrerin gibt den Schülern Bücher.
6  Die gibt den Schülern die Bücher.
6  Lehrerin gibt den Schülern die Bücher.
7  Die Lehrerin gibt den Schülern die Bücher.
```

其中 4 词的 `gibt den die Bücher.` 已不合语法，只是穷举产物；`gibt den Schülern Bücher.` 是无主语的 V1 片段。**仅靠删除原句中的词，最短复现是 4 词。**

### 4.2 能复现的最短输入

继续把动词还原为不定式、去掉主语和冠词，实测 2 词即可复现：

```text
Bücher geben.
```

实际输出：

```text
Bücher[NOUN/oa/Nom]
```

边界（再删一个词就不复现）：

| 输入 | `Bücher` 的结果 | 是否复现 | 说明 |
| --- | --- | --- | --- |
| `Bücher geben.` | `NOUN / oa / Nom` | 是 | 最短输入（不定式短语，非完整句） |
| `Bücher.` | `NOUN / ROOT / Nom` | 否 | 没有动词，也没有第四格句法位置；此时 `Nom` 不是错标 |
| `geben.` | 无目标词 | 否 | 目标词被删掉 |

### 4.3 最短完整陈述句

```text
Wir geben Schülern Bücher.
```

实际输出：

```text
Wir[PRON/sb/Nom]  Schülern[NOUN/da/Dat]  Bücher[NOUN/oa/Nom]
```

边界：

| 输入 | `Bücher` 的结果 | 是否复现 | 说明 |
| --- | --- | --- | --- |
| `Wir geben Schülern Bücher.` | `NOUN / oa / Nom` | 是 | 最短完整陈述句（4 词） |
| `Wir geben Bücher.` | `NOUN / oa / Acc` | 否 | 删掉第三格宾语后恢复正确 |
| `Wir geben Schülern.` | 无目标词 | 否 | 目标词被删掉 |

删掉 `Wir` 得到的 `Geben Schülern Bücher.` 仍会复现，但已不是完整陈述句，因此不作为最短「句子」的边界。

### 4.4 保留原句冠词结构的最短复现

```text
Gibt den Schülern Bücher.
```

实际输出：

```text
den[DET/nk/Dat]  Schülern[NOUN/da/Dat]  Bücher[NOUN/oa/Nom]
```

边界：删掉 `den` 得到 `Gibt Schülern Bücher.`，`Bücher` 变为 `NOUN / oa / Acc`，不再复现。这是「保留原句 `den … Bücher` 词形、再删一个词就恢复」的最短边界；该输入本身是无主语 V1 片段。

## 5. 根因定位

### 5.1 实测链路：`Nom` 来自 spaCy morphologizer，不是 DeLector 改写的

对同一句逐组件运行 `de_core_news_sm`：

```text
pipeline: ['tok2vec', 'tagger', 'morphologizer', 'parser', 'lemmatizer', 'attribute_ruler', 'ner']
tok2vec         []
tagger          []
morphologizer   [('Die','Nom','-'), ('Lehrerin','Nom','-'), ('den','Dat','-'), ('Schülern','Dat','-'), ('die','Acc','-'), ('Bücher','Nom','-')]
parser          [('Die','Nom','nk'), ('Lehrerin','Nom','sb'), ('den','Dat','nk'), ('Schülern','Dat','da'), ('die','Acc','nk'), ('Bücher','Nom','oa')]
lemmatizer      [('Die','Nom','nk'), ('Lehrerin','Nom','sb'), ('den','Dat','nk'), ('Schülern','Dat','da'), ('die','Acc','nk'), ('Bücher','Nom','oa')]
attribute_ruler [('Die','Nom','nk'), ('Lehrerin','Nom','sb'), ('den','Dat','nk'), ('Schülern','Dat','da'), ('die','Acc','nk'), ('Bücher','Nom','oa')]
ner             [('Die','Nom','nk'), ('Lehrerin','Nom','sb'), ('den','Dat','nk'), ('Schülern','Dat','da'), ('die','Acc','nk'), ('Bücher','Nom','oa')]
```

关键结论（**实测确认**）：

- `morphologizer` 阶段就已经给 `Bücher` 输出 `Case=Nom`，此时 parser 还没运行。
- `parser` 随后把 `Bücher` 的依存标成 `oa`（第四格宾语），但**没有改写** `Case=Nom`。
- 后续 `lemmatizer` / `attribute_ruler` / `ner` 都没有修正它。

### 5.2 代码定位：DeLector 只透传 token 级 morph，没有 NP 级格位归一化

格位字段的来源只有两处，都是直接复制 spaCy 的 token morph：

[syntax_tree.py](../../delector/nlp_engine/syntax_tree.py#L100-L121)：

```python
def format_token_dict(tok: Token) -> Dict[str, Any]:
    """Convert a spaCy Token into a clean, serializable dictionary."""
    morph_dict = tok.morph.to_dict()
    return {
        ...
        "gender": morph_dict.get("Gender", ""),
        "case": morph_dict.get("Case", ""),
        "number": morph_dict.get("Number", ""),
        ...
    }
```

[processor.py](../../delector/nlp_engine/processor.py#L419-L433)（阅读器 token 走同一来源）：

```python
for t in spacy_tokens:
    morph = t.morph.to_dict()
    ...
    tok = {
        ...
        "gender": morph.get("Gender", ""),
        "case": morph.get("Case", ""),
        ...
    }
```

`syntax_fields.py` 只做拓扑五场域分配；`linguistics.py` 没有参与 `format_token_dict` 的格位判定。仓库中**不存在**「用限定词格位或依存标签回写名词格位」的规则，也不存在「先判定 NP 格位再分配给限定词/名词」的规则。

### 5.3 结论：是哪一种失败

- **是「词形没被识别成复数第四格」**：`Bücher` 的 Nom/Akk 复数同形，模型在该句的 morphologizer 输出为 `Case=Nom`；DeLector 原样展示。
- **不是「格位分配规则把限定词/名词对错了位置」**：`die` 与 `Bücher` 的 `nk` 依存关系正确，`die` 也确实是 `Acc`；错的是名词自身的 token 级 `Case`，不是配对关系。
- 更准确地说：DeLector 把 **token 级形态格**当成了 **名词短语级句法格** 来展示，且没有用同一 NP 内限定词的 `Acc` 或 `dep=oa` 做一致性校验/回写。

### 5.4 证据等级

| 结论 | 等级 | 依据 |
| --- | --- | --- |
| 真实引擎输出 `Bücher` 为 `oa/Nom` | **实测确认** | 本文第 2 节命令与完整 JSON |
| `Nom` 在 morphologizer 阶段已产生，parser 未改写 | **实测确认** | 第 5.1 节逐组件输出 |
| DeLector 无格位归一化/回写规则 | **读码确认** | 第 5.2 节两处赋值；`syntax_fields.py`/`linguistics.py` 无相关逻辑 |
| 前端把名词 `case` 直接显示为主格 | **读码确认** | `satz-lab.js:128-131`、`reader.js:395-397` |
| 写作规则不会被本句误触发 | **实测确认 + 读码** | 第 6 节，实测返回空列表；规则优先用 `dep` 推导格位 |
| Anki / 考点剖析不直接读取 `token.case` | **读码确认** | 第 6 节 |

## 6. 影响面

### 6.1 直接可见

- **首屏「句子解剖台」**：[satz-lab.js](../../static/js/satz-lab.js#L24-L25) 的 `CASE_POS` 只包含 `NOUN/PRON/PROPN`，[caseLabel()](../../static/js/satz-lab.js#L128-L131) 直接返回 `CASE_ZH[token.case]`。`Bücher` 会显示「主格」。
- **阅读器单词详情**：[reader.js](../../static/js/reader.js#L395-L397) 把 `token.case` 原样拼进 `d-meta`，会显示 `Nom`。
- **阅读器持久化数据**：`process_german_text()` 用同一 token morph 写入 `tokens[].case`（第 5.2 节实测同一句返回 `Nom`）。已处理文章的 `processed_json` 不会因本轮记录而重算，存量数据同样可能带错标。

### 6.2 不直接受影响（读码/实测）

- **写作批改**：`detect_determiner_noun_agreement()` 先取 `slot_case = dep_case_map.get(head.dep_)`，本句 `oa` 已给出 `Akk`，优先于名词自身的 `nc`（[writing.py](../../delector/services/writing.py#L342-L343)）。实测本句返回 `[]`，未产生冠词/格位误报；`detect_verb_case_government()` 也返回 `[]`。
- **Anki 导出**：`_vocab_anki_note()` 使用 `pos`、`gender`、`cefr_level`；`_grammar_anki_note()` 使用 `grammar_name`、`explanation_zh`、`rule_formula`，均不读取语法 token 的 `case`（[content.py](../../delector/core/db/content.py#L564-L593)）。
- **考点剖析/语法查询**：`/api/lookup/grammar` 把原句和目标短语交给 LLM，不读取 `analyze_syntax_tree()` 的 `token.case`（[main.py](../../delector/routes/main.py#L257)）。
- **难句解剖**：接口返回的 JSON 含 `case`，但当前 `hard-sentences.js` 只渲染五场域文本和从句树，未渲染格位标签（读码确认）。

结论：当前最确定的用户可见影响是**首屏句子解剖台和阅读器单词详情**；不会直接污染 Anki 卡片或考点剖析的生成内容，但会污染阅读器已持久化的 token 数据。

## 7. 复算命令

在仓库根目录执行（PowerShell）：

```powershell
.venv\Scripts\python.exe -c "from delector.nlp_engine.syntax_tree import analyze_syntax_tree as a; d=a('Die Lehrerin gibt den Schülern die Bücher.'); ts=[t for f in ('vorfeld','linke_klammer','mittelfeld','rechte_klammer','nachfeld') for t in d['sentences'][0]['topology'][f]]; print([(t['text'],t['pos'],t['dep'],t['case']) for t in sorted(ts,key=lambda x:x['id']) if t['pos'] in ('NOUN','DET','PRON')])"
```

实际输出：

```text
[('Die', 'DET', 'nk', 'Nom'), ('Lehrerin', 'NOUN', 'sb', 'Nom'), ('den', 'DET', 'nk', 'Dat'), ('Schülern', 'NOUN', 'da', 'Dat'), ('die', 'DET', 'nk', 'Acc'), ('Bücher', 'NOUN', 'oa', 'Nom')]
```

最短复算：

```powershell
.venv\Scripts\python.exe -c "from delector.nlp_engine.syntax_tree import analyze_syntax_tree as a; d=a('Wir geben Schülern Bücher.'); ts=[t for f in ('vorfeld','linke_klammer','mittelfeld','rechte_klammer','nachfeld') for t in d['sentences'][0]['topology'][f]]; print([(t['text'],t['pos'],t['dep'],t['case']) for t in sorted(ts,key=lambda x:x['id']) if t['pos']=='NOUN'])"
```

实际输出：

```text
[('Schülern', 'NOUN', 'da', 'Dat'), ('Bücher', 'NOUN', 'oa', 'Nom')]
```

## 8. 本轮边界

- 未修改任何格位判定、标注、前端展示或下游逻辑。
- 未跑全量 pytest；未启动模拟器、未跑 `adb`、未碰 Android 构建。
- 未修改 `docs/reviews/2026-11-05-code-quality-decoupling-review.md`。
- 是否修复、如何修复（例如在 NP 级用限定词格位/依存标签回写名词格位）是另一个决定，不在本轮范围。

## 附录 A：完整输出原文

以下是 `analyze_syntax_tree('Die Lehrerin gibt den Schülern die Bücher.')` 的真实返回（`json.dumps(..., ensure_ascii=False, indent=2)`），未做手工改写：

```json
{
  "version": "3.5.0",
  "sentence_count": 1,
  "sentences": [
    {
      "sentence_id": 0,
      "text": "Die Lehrerin gibt den Schülern die Bücher.",
      "clause_tree": {
        "id": "clause_0",
        "type": "hauptsatz",
        "label": "Hauptsatz (V2)",
        "subtype": "kernsatz_v2",
        "connector": "",
        "finite_verb": "gibt",
        "formula": "[VF] + [LK: Verb_fin] + [MF] + [RK: Verb_nonfin/Pfx] + [NF]",
        "bracket_structure": "Hauptsatz-Klammer (V2)",
        "features": {
          "is_passive": false,
          "is_subjunctive": false,
          "voice": "Aktiv",
          "mood": "Indikativ",
          "tense": "Präsens",
          "has_modal": false
        },
        "token_ids": [
          0,
          1,
          2,
          3,
          4,
          5,
          6,
          7
        ],
        "text": "Die Lehrerin gibt den Schülern die Bücher.",
        "topology": {
          "vorfeld": [
            {
              "id": 0,
              "text": "Die",
              "lemma": "der",
              "pos": "DET",
              "tag": "ART",
              "dep": "nk",
              "head_id": 1,
              "head_text": "Lehrerin",
              "gender": "Fem",
              "case": "Nom",
              "number": "Sing",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            },
            {
              "id": 1,
              "text": "Lehrerin",
              "lemma": "Lehrerin",
              "pos": "NOUN",
              "tag": "NN",
              "dep": "sb",
              "head_id": 2,
              "head_text": "gibt",
              "gender": "Fem",
              "case": "Nom",
              "number": "Sing",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            }
          ],
          "linke_klammer": [
            {
              "id": 2,
              "text": "gibt",
              "lemma": "geben",
              "pos": "VERB",
              "tag": "VVFIN",
              "dep": "ROOT",
              "head_id": 2,
              "head_text": "gibt",
              "gender": "",
              "case": "",
              "number": "Sing",
              "person": "3",
              "tense": "Pres",
              "mood": "Ind",
              "verb_form": "Fin",
              "is_punct": false,
              "is_space": false
            }
          ],
          "mittelfeld": [
            {
              "id": 3,
              "text": "den",
              "lemma": "der",
              "pos": "DET",
              "tag": "ART",
              "dep": "nk",
              "head_id": 4,
              "head_text": "Schülern",
              "gender": "Masc",
              "case": "Dat",
              "number": "Plur",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            },
            {
              "id": 4,
              "text": "Schülern",
              "lemma": "Schüler",
              "pos": "NOUN",
              "tag": "NN",
              "dep": "da",
              "head_id": 2,
              "head_text": "gibt",
              "gender": "Masc",
              "case": "Dat",
              "number": "Plur",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            },
            {
              "id": 5,
              "text": "die",
              "lemma": "der",
              "pos": "DET",
              "tag": "ART",
              "dep": "nk",
              "head_id": 6,
              "head_text": "Bücher",
              "gender": "Neut",
              "case": "Acc",
              "number": "Plur",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            },
            {
              "id": 6,
              "text": "Bücher",
              "lemma": "Buch",
              "pos": "NOUN",
              "tag": "NN",
              "dep": "oa",
              "head_id": 2,
              "head_text": "gibt",
              "gender": "Neut",
              "case": "Nom",
              "number": "Plur",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": false,
              "is_space": false
            },
            {
              "id": 7,
              "text": ".",
              "lemma": "--",
              "pos": "PUNCT",
              "tag": "$.",
              "dep": "punct",
              "head_id": 2,
              "head_text": "gibt",
              "gender": "",
              "case": "",
              "number": "",
              "person": "",
              "tense": "",
              "mood": "",
              "verb_form": "",
              "is_punct": true,
              "is_space": false
            }
          ],
          "rechte_klammer": [],
          "nachfeld": [],
          "field_texts": {
            "vorfeld": "Die Lehrerin",
            "linke_klammer": "gibt",
            "mittelfeld": "den Schülern die Bücher.",
            "rechte_klammer": "",
            "nachfeld": ""
          },
          "sentence_type": "V2",
          "bracket_structure": "Einfache Verbklammer",
          "clause_type": "hauptsatz"
        },
        "children": []
      },
      "topology": {
        "vorfeld": [
          {
            "id": 0,
            "text": "Die",
            "lemma": "der",
            "pos": "DET",
            "tag": "ART",
            "dep": "nk",
            "head_id": 1,
            "head_text": "Lehrerin",
            "gender": "Fem",
            "case": "Nom",
            "number": "Sing",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          },
          {
            "id": 1,
            "text": "Lehrerin",
            "lemma": "Lehrerin",
            "pos": "NOUN",
            "tag": "NN",
            "dep": "sb",
            "head_id": 2,
            "head_text": "gibt",
            "gender": "Fem",
            "case": "Nom",
            "number": "Sing",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          }
        ],
        "linke_klammer": [
          {
            "id": 2,
            "text": "gibt",
            "lemma": "geben",
            "pos": "VERB",
            "tag": "VVFIN",
            "dep": "ROOT",
            "head_id": 2,
            "head_text": "gibt",
            "gender": "",
            "case": "",
            "number": "Sing",
            "person": "3",
            "tense": "Pres",
            "mood": "Ind",
            "verb_form": "Fin",
            "is_punct": false,
            "is_space": false
          }
        ],
        "mittelfeld": [
          {
            "id": 3,
            "text": "den",
            "lemma": "der",
            "pos": "DET",
            "tag": "ART",
            "dep": "nk",
            "head_id": 4,
            "head_text": "Schülern",
            "gender": "Masc",
            "case": "Dat",
            "number": "Plur",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          },
          {
            "id": 4,
            "text": "Schülern",
            "lemma": "Schüler",
            "pos": "NOUN",
            "tag": "NN",
            "dep": "da",
            "head_id": 2,
            "head_text": "gibt",
            "gender": "Masc",
            "case": "Dat",
            "number": "Plur",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          },
          {
            "id": 5,
            "text": "die",
            "lemma": "der",
            "pos": "DET",
            "tag": "ART",
            "dep": "nk",
            "head_id": 6,
            "head_text": "Bücher",
            "gender": "Neut",
            "case": "Acc",
            "number": "Plur",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          },
          {
            "id": 6,
            "text": "Bücher",
            "lemma": "Buch",
            "pos": "NOUN",
            "tag": "NN",
            "dep": "oa",
            "head_id": 2,
            "head_text": "gibt",
            "gender": "Neut",
            "case": "Nom",
            "number": "Plur",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": false,
            "is_space": false
          },
          {
            "id": 7,
            "text": ".",
            "lemma": "--",
            "pos": "PUNCT",
            "tag": "$.",
            "dep": "punct",
            "head_id": 2,
            "head_text": "gibt",
            "gender": "",
            "case": "",
            "number": "",
            "person": "",
            "tense": "",
            "mood": "",
            "verb_form": "",
            "is_punct": true,
            "is_space": false
          }
        ],
        "rechte_klammer": [],
        "nachfeld": [],
        "field_texts": {
          "vorfeld": "Die Lehrerin",
          "linke_klammer": "gibt",
          "mittelfeld": "den Schülern die Bücher.",
          "rechte_klammer": "",
          "nachfeld": ""
        },
        "sentence_type": "V2",
        "bracket_structure": "Einfache Verbklammer",
        "clause_type": "auto"
      }
    }
  ]
}
```
