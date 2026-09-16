# 官方歌德词表 · IPA 人工复核清单（Rich Side-car）

> **生成日期**：2026-09-16
> **数据来源**：`delector/data/official_vocab_rich.py`（`OFFICIAL_RICH_A1` / `OFFICIAL_RICH_A2` / `OFFICIAL_RICH_B1`）；官方 5 元组取自 `delector/core/lexicon.py::official_level()`。
> **性质**：机器启发式筛查产物，**仅供参考、需人工复核**。本清单只读报告，**不改动任何 rich 数据**。
> **生成方式**：一次性脚本实测生成（脚本未入库）。

## 1. 空 IPA 清单（需人工补音标）

共 **10** 条（A1 6 / A2 3 / B1 1）。

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

## 2. artifacts 候选清单（启发式 · 只报告不修改）

### 2.1 IPA 内连续相同辅音（疑似叠写 / 重复）

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

### 2.2 IPA 内出现第二个重音符号 `ˈ`（词内二次重音）

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

### 2.3 IPA 含空格但词性非名词（名词带冠词发音为既定风格，非名词带空格可疑）

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
