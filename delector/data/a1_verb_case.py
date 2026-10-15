# -*- coding: utf-8 -*-
"""A1 高频动词 → 支配格（Rektion）**人工登记表**。

**这是事实数据，不是生成物**：每条都按「歌德 A1 词表（`delector/data/a1_dict.py::GOETHE_A1_VOCAB`）
＋ 教科书级支配格常识」逐条确认，禁止用 LLM 批量生成。收录标准 = **少而准**（FP 是敌人）：

- 只收**严格单格**支配的动词（`Dat` 或 `Acc`）——检测器仅在「有冠词的宾语 NP ＋ 单数」时才报；
- 标 `Dat+Acc` 的动词（人三格物四格 / 自由第三格 freier Dativ / 格支配两可）**登记但不判**
  —— 这些动词的宾语格位依句式而定，硬判必误报；
- 可分前缀动词（an|rufen）/ 反身动词（sich freuen）/ 名词化动词一律**不入表**
  （检测器另有守卫，见 `delector/services/writing.py::detect_verb_case_government` 的 docstring）；
- 动词同时可接介词搭配（如 `helfen bei`、`danken für`）不影响本表 —— 那是
  `detect_preposition_case` / 固定搭配表的领域。

来源注释（按组给出，每组均为教科书级支配格常识 + 歌德 A1 词表在册动词）：
- `Dat` 组：`jemandem helfen / danken / gratulieren`（人三格）、`Das gefällt / gehört /
  passt / fehlt mir`（A1 教材固定搭配）。
- `Acc` 组：A1 教科书典型句式中只接四格宾语的及物动词（`etwas sehen / brauchen / suchen /
  finden / lieben / grüßen / kennen / lesen / trinken / essen / hören / verstehen /
  wiederholen / unterschreiben`）。**凡 A1 教科书级出现自由第三格（人三格附加宾）或双宾
  用法的动词一律不进本组**：`jdm. die Tür öffnen` / `jdm. etw. bezahlen` 是 A1 教科书级
  搭配 ⇒ `öffnen` / `bezahlen` 移入 `Dat+Acc`；`schmecken` 两可（`Das schmeckt mir.`
  三格 / `Ich schmecke den Wein.` 四格）⇒ 同样移入 `Dat+Acc`。
- `Dat+Acc` 组（不判）：双宾「人三物四」（`jemandem etwas geben / bringen / zeigen /
  schreiben / kaufen`）＋ 自由第三格（`jdm. die Tür öffnen` / `jdm. etw. bezahlen`）＋
  两可支配（`schmecken`）。
"""

A1_VERB_CASES: dict[str, str] = {
    # ── Dat（严格三格；`helfen / danken / gratulieren` = 人三格，A1 教材固定搭配）────────
    "helfen": "Dat",
    "danken": "Dat",
    "gratulieren": "Dat",
    # Dat（`Das gefällt / gehört / passt / fehlt mir.` 句式）─────────────────────────────
    "gefallen": "Dat",
    "gehören": "Dat",
    "passen": "Dat",
    "fehlen": "Dat",
    # ── Acc（严格四格；A1 教材典型句式只接四格宾语的及物动词）──────────────────────────
    "sehen": "Acc",
    "brauchen": "Acc",
    "suchen": "Acc",
    "finden": "Acc",
    "lieben": "Acc",
    "grüßen": "Acc",
    "kennen": "Acc",
    "lesen": "Acc",
    "trinken": "Acc",
    "essen": "Acc",
    "hören": "Acc",
    "verstehen": "Acc",
    "wiederholen": "Acc",
    "unterschreiben": "Acc",
    # ── Dat+Acc（双宾 / 自由第三格 / 两可支配 ⇒ 登记但**不判**）────────────────────────
    "geben": "Dat+Acc",
    "bringen": "Dat+Acc",
    "zeigen": "Dat+Acc",
    "schreiben": "Dat+Acc",
    "kaufen": "Dat+Acc",
    "öffnen": "Dat+Acc",
    "bezahlen": "Dat+Acc",
    "schmecken": "Dat+Acc",
}
