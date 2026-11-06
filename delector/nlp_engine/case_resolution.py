# -*- coding: utf-8 -*-
"""名词格位解析：用动词支配格（Rektion）纠正模型在 Nom/Akk 同形上的误标。

背景（2026-11-06 复现，见 docs/reviews/2026-11-06-german-plural-akkusativ-mislabeled-nominativ.md）：
``de_core_news_sm`` 的 morphologizer 把 "Die Lehrerin gibt den Schülern die Bücher."
中的复数第四格宾语 "Bücher" 标成 ``Case=Nom``；parser 只把依存改成 ``oa``，不回写
``Case``，DeLector 原样透传。德语复数强变化 Nom 与 Akk 同形，模型确有歧义空间，
但动词支配格（geben = Dat+Acc，宾语由依存区分）提供了独立证据。

本模块在 "spaCy Token → DeLector token 字典" 的边界上做一次**保守**纠偏：

- 只处理 ``pos_ == "NOUN"`` 且 ``dep_ ∈ {"oa", "da"}`` 的 token；
- 沿 head 链向上找最近的、在 ``A1_VERB_CASES`` 登记的支配动词；
- 严格单格动词（Acc / Dat）直接采用登记格；``Dat+Acc`` 按依存区分（oa→Acc，da→Dat）；
- 守卫：支配动词（或其助动词祖先）必须有显式主语。没有主语的两词片段
  ``Bücher geben.`` 与 ``Kinder essen.`` 实测词形/依存完全同形（NOUN Plur dep=oa
  Case=Nom + VERB VerbForm=Inf），任何"无主语即宾格"的规则都会破坏后者的正确主格；
  离线模型不含生命度/语义信息，故无主语时不改动（保留模型输出）。
- 双宾否决票：``Dat+Acc`` 动词按 dep 判 Acc 前，若目标 NP 的限定词被标成 Dat/Gen，
  则放弃改写。限定词的格标记比名词自身可靠（``den Schülerinnen`` 的 ``den`` 是 Dat，
  ``die Bücher`` 的 ``die`` 是 Nom/Acc），可挡住"第三格接收者被 parser 误标 oa"导致的
  Dat→Acc 误伤。
- 代词、限定词、形容词不在此处理：它们的词形自带更强的格位证据，误改风险更高。

放在 ``nlp_engine`` 层：它是模型输出的第一落点，syntax_tree（句法实验台）与
processor（阅读器持久化）两条路径共用同一实现，避免规则分叉。

**单点开关**：``CASE_RESOLUTION_ENABLED``（模块级常量，默认 True）。也可用环境变量
``DELECTOR_CASE_RESOLUTION=0`` 在进程启动时关闭；关闭后所有调用点统一回退模型原值。
"""

import os
from typing import Any, Optional, Tuple

from delector.data.a1_verb_case import A1_VERB_CASES

# 规则总开关：False 时 resolve_case 直接返回 morphologizer 原值。
# 环境变量只做启动期覆盖，便于线上止血（processed_json 已写入的错误不会回溯重算）。
CASE_RESOLUTION_ENABLED = os.getenv("DELECTOR_CASE_RESOLUTION", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# 依存标签 → 宾语格位（仅这两个标签参与纠偏）
_DEP_TO_CASE = {"oa": "Acc", "da": "Dat"}


def _morph_case(tok: Any) -> str:
    """morphologizer 给出的原始格位（无则空串）。"""
    value = tok.morph.to_dict().get("Case", "")
    return value if isinstance(value, str) else str(value or "")


def _governing_verb(tok: Any) -> Tuple[Optional[Any], Optional[str]]:
    """沿 head 链向上找最近的、在支配格表登记的动词。

    返回 ``(verb_token, mapping)``；找不到返回 ``(None, None)``。
    经过 AUX 时继续上溯（完成时/情态的实义动词可能挂在助动词下）。
    """
    seen = set()
    head = tok.head
    while head is not None and head.i not in seen:
        seen.add(head.i)
        if head.pos_ in ("VERB", "AUX"):
            mapping = A1_VERB_CASES.get((head.lemma_ or "").lower())
            if mapping:
                return head, mapping
        if head is head.head:
            break
        head = head.head
    return None, None


def _has_explicit_subject(verb: Any) -> bool:
    """在支配动词及其助动词祖先上查找显式主语 ``sb``。"""
    seen = set()
    cur = verb
    while cur is not None and cur.i not in seen:
        seen.add(cur.i)
        for child in cur.children:
            if child.dep_ == "sb" and child.pos_ in ("NOUN", "PRON", "PROPN"):
                return True
        parent = cur.head
        if parent is None or parent is cur or parent.pos_ not in ("VERB", "AUX"):
            return False
        cur = parent
    return False


def _np_determiner(tok: Any) -> Optional[Any]:
    """返回名词所在 NP 的限定词子节点（spaCy 德语依存为 nk），没有返回 None。"""
    for child in tok.children:
        if child.pos_ == "DET" and child.dep_ in ("nk", "det", "pnc"):
            return child
    return None


def _determiner_vetoes_accusative(tok: Any) -> bool:
    """双宾分支的否决票：限定词被标成 Dat/Gen 时，该 NP 不可能是第四格宾语。"""
    det = _np_determiner(tok)
    if det is None:
        return False
    det_case = det.morph.to_dict().get("Case", "")
    return det_case in ("Dat", "Gen")


def resolve_case(tok: Any) -> str:
    """返回 token 的最终格位；无法安全纠偏时返回 morphologizer 的原值。"""
    base = _morph_case(tok)
    if not CASE_RESOLUTION_ENABLED:
        return base
    if tok.pos_ != "NOUN" or tok.dep_ not in _DEP_TO_CASE:
        return base
    verb, mapping = _governing_verb(tok)
    if verb is None or not mapping:
        return base
    if mapping == "Dat+Acc":
        desired = _DEP_TO_CASE.get(tok.dep_)
    else:
        desired = mapping
    if not desired or desired == base:
        return base
    if not _has_explicit_subject(verb):
        return base
    if mapping == "Dat+Acc" and desired == "Acc" and _determiner_vetoes_accusative(tok):
        return base
    return desired
