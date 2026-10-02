# 官方歌德词表 · IPA 人工复核清单（Rich Side-car）

> **生成日期**：2026-09-16
> **数据来源**：`delector/data/official_vocab_rich.py`（`OFFICIAL_RICH_A1` / `OFFICIAL_RICH_A2` / `OFFICIAL_RICH_B1`）；官方 5 元组取自 `delector/core/lexicon.py::official_level()`。
> **性质**：机器启发式筛查产物，**仅供参考、需人工复核**。本清单只读报告，**不改动任何 rich 数据**。
> **生成方式**：一次性脚本实测生成（脚本未入库）。

## 1. 空 IPA 清单（需人工补音标）

共 **10** 条（A1 6 / A2 3 / B1 1）。

> **状态更新（2026-09-16）：✅ 已回填。** 上表 10 条空 IPA 已由内部可溯源来源补全（借自 §2.1，
> 取值见下），现 `OFFICIAL_RICH_A1` / `OFFICIAL_RICH_A2` / `OFFICIAL_RICH_B1` 空 IPA 计数均为 **0**
> （A1 660 / A2 736 / B1 1617 全非空）。
> **来源**：`A1_WORKBENCH_SEED` 同 lemma 的音标（去 tie-bar）。
> ⚠️ **重生成注意**：rich 为外部 `gen_rich.py` 生成物；重跑该脚本时**必须带上这 10 条借用的 ipa**，
> 否则本次回填会被覆盖丢失（`tests/test_official_vocab_rich.py::test_no_empty_ipa_in_any_fragment`
> 与 `test_backfilled_ipa_borrowed_from_a1_seed` 会立刻变红）。下表保留原始「空 IPA」清单作为历史记录，
> 不再代表当前状态。

| 等级 | lemma | pos | gender | plural | 释义 |
|---|---|---|---|---|---|
| A1 | fax | NOUN | Neut | -e | 传真 |
| A1 | polizei | NOUN | Fem | - | 警察；警方 |
| A1 | praxis | NOUN | Fem | - | 诊所；实践 |
| A1 | rezeption | NOUN | Fem | - | 前台；接待处 |
| A1 | taxi | NOUN | Neut | -s | 出租车 |
| A1 | zigarette | NOUN | Fem | -n | 香烟 |
| A2 | polizei | NOUN | Fem | - | 警察，警方 |
| A2 | praxis | NOUN | Fem | -en | 诊所，诊所门诊 |
| A2 | rezeption | NOUN | Fem | -en | （旅馆）前台，接待处 |
| B1 | zigarette | NOUN | Fem | -n | 香烟 |

## 2. 可补来源清单（内部借用 / 需外部提供）

> **生成方式**：脚本实测生成（脚本未入库），对第 1 节 10 条空 IPA 在内部数据源中按归一化键查找可复用 ipa。
> **只报告不改数据** —— rich 为外部生成物（`gen_rich.py`），擅自补写会与重生成漂移。
> **归一化键**：剥去冠词 `der/die/das`、`(sich)`、逗号及其后复数标记后小写。
> **数据源**：`delector/data/a1_workbench_dict.py::A1_WORKBENCH_SEED`（按 `hw` 归一化）、`delector/data/a1_dict.py::GOETHE_A1_VOCAB`（按 `lemma`；该表**无 ipa 字段**，实测零命中）。

### 2.1 可从内部借用（10 条）

| 等级 | lemma | 可借来源（源条目） | 借用 ipa 值 |
|---|---|---|---|
| A1 | fax | `A1_WORKBENCH_SEED::das Fax, -e` | `ˈfaks` |
| A1 | polizei | `A1_WORKBENCH_SEED::die Polizei` | `ˈpolɪtsaɪ̯` |
| A1 | praxis | `A1_WORKBENCH_SEED::die Praxis` | `ˈpʁaksɪz` |
| A1 | rezeption | `A1_WORKBENCH_SEED::die Rezeption` | `ˈʁetseptɪon` |
| A1 | taxi | `A1_WORKBENCH_SEED::das Taxi, -s` | `ˈtaksɪ` |
| A1 | zigarette | `A1_WORKBENCH_SEED::die Zigarette, -n` | `ˈtsɪɡaʁette` |
| A2 | polizei | `A1_WORKBENCH_SEED::die Polizei` | `ˈpolɪtsaɪ̯` |
| A2 | praxis | `A1_WORKBENCH_SEED::die Praxis` | `ˈpʁaksɪz` |
| A2 | rezeption | `A1_WORKBENCH_SEED::die Rezeption` | `ˈʁetseptɪon` |
| B1 | zigarette | `A1_WORKBENCH_SEED::die Zigarette, -n` | `ˈtsɪɡaʁette` |

### 2.2 需外部提供（0 条）

实测结论：10 条空 IPA **全部**可从 `A1_WORKBENCH_SEED` 借用；`GOETHE_A1_VOCAB` 无 ipa 字段（零命中）。故本栏为空。

> ⚠️ **与初拟期望的偏差（以实测为准）**：初拟认为 `fax` / `praxis` / `taxi` 内部无来源、需外部，但实测 seed 中存在 `das Fax, -e`（`a1-0215`）、`die Praxis`（`a1-0484`）、`das Taxi, -s`（`a1-0581`）三条，故三者均可内部借用。

## 3. artifacts 候选清单（启发式 · 只报告不修改）

### 3.1 IPA 内连续相同辅音（疑似叠写 / 重复）

条数：**381**（下列前 15 条）

| 等级 | lemma | ipa |
|---|---|---|
| A1 | allein | `ˈallaɪn` |
| A1 | ankommen | `ˈaŋkɔmmən` |
| A1 | appetit | `deːɐ ˈappətiːt` |
| A1 | ausfüllen | `ˈaʊsfʏllən` |
| A1 | beginnen | `beːgˈɪnnən` |
| A1 | bekannt | `beːkˈannt` |
| A1 | bekannte | `dˈeːɐ beːkˈanntə` |
| A1 | bekommen | `beːkˈɔmmən` |
| A1 | bestellen | `bɛstˈəllən` |
| A1 | bett | `das bɛˈtt` |
| A1 | billig | `bˈɪllɪç` |
| A1 | bitte | `bˈɪttə` |
| A1 | bitten | `bˈɪttən` |
| A1 | bitter | `bˈɪttəɐ` |
| A1 | butter | `diː bˈʊttəɐ` |

### 3.2 IPA 内出现第二个重音符号 `ˈ`（词内二次重音）

条数：**69**（下列前 15 条）

| 等级 | lemma | ipa |
|---|---|---|
| A1 | an-sein | `ˈan zˈaɪn` |
| A1 | auf-sein | `ˈaʊf zˈaɪn` |
| A1 | aus-sein | `ˈaʊs zˈaɪn` |
| A1 | bekannte | `dˈeːɐ beːkˈanntə` |
| A1 | pommes-frites | `diː pˈɔmməs fʁˈiːtəs` |
| A1 | rad-fahren | `ʁˈaːt fˈaːʁən` |
| A1 | sich-kümmern | `zˈɪç kˈʏmməɐn` |
| A1 | was-für-ein | `vˈas fˈyːɐ ˈaɪn` |
| A1 | weg-sein | `vˈɛk zˈaɪn` |
| A1 | weh-tun | `vˈeː tˈuːn` |
| A1 | wie-viel | `vˈiː fˈiːl` |
| A1 | zu-sein | `tsˈuː zˈaɪn` |
| A2 | am-besten | `ˈam bɛstˈən` |
| A2 | am-liebsten | `ˈam lˈiːpstən` |
| A2 | auf-keinen-fall | `ˈaʊf kˈaɪnən fˈall` |

### 3.3 IPA 含空格但词性非名词（名词带冠词发音为既定风格，非名词带空格可疑）

条数：**74**（下列前 15 条）

| 等级 | lemma | pos | ipa |
|---|---|---|---|
| A1 | an-sein | VERB | `ˈan zˈaɪn` |
| A1 | auf-sein | VERB | `ˈaʊf zˈaɪn` |
| A1 | aus-sein | VERB | `ˈaʊs zˈaɪn` |
| A1 | rad-fahren | VERB | `ʁˈaːt fˈaːʁən` |
| A1 | sich-kümmern | VERB | `zˈɪç kˈʏmməɐn` |
| A1 | was-für-ein | PRON | `vˈas fˈyːɐ ˈaɪn` |
| A1 | weg-sein | VERB | `vˈɛk zˈaɪn` |
| A1 | weh-tun | VERB | `vˈeː tˈuːn` |
| A1 | wie-viel | PRON | `vˈiː fˈiːl` |
| A1 | zu-sein | VERB | `tsˈuː zˈaɪn` |
| A2 | am-besten | ADV | `ˈam bɛstˈən` |
| A2 | am-liebsten | ADV | `ˈam lˈiːpstən` |
| A2 | auf-keinen-fall | ADV | `ˈaʊf kˈaɪnən fˈall` |
| A2 | auf-sein | VERB | `ˈaʊf zˈaɪn` |
| A2 | dank | PREP | `deːɐ dˈaŋk` |

---

**判定启发式**

- 空 IPA：`rich[lemma]["ipa"] == ""`。
- 2.1：IPA 中相邻两字符相同且该字符为辅音（非元音字母）。
- 2.2：IPA 内 `ˈ` 出现 ≥ 2 次。
- 2.3：IPA 去首尾空白后含空格，且该 lemma 官方 `pos != "NOUN"`。

以上均为**启发式信号而非错误定论**，须逐条人工听辨 / 对照官方音频复核。
