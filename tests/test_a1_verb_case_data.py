# -*- coding: utf-8 -*-
"""`A1_VERB_CASES` 数据自检（Task 4）。

词表是**人工登记的事实数据**（歌德 A1 词表 + 教科书级支配格常识），不是生成物 ——
这些用例是它的可证伪边界：键越界 / 值非法 / 空键 / 条目过少都会红。
"""

from delector.data.a1_dict import GOETHE_A1_VOCAB
from delector.data.a1_verb_case import A1_VERB_CASES


def _a1_lemma_set():
    lemmas = set()
    for key, entry in GOETHE_A1_VOCAB.items():
        lemma = entry.get("lemma") if isinstance(entry, dict) else None
        lemmas.add(str(lemma or key).strip().lower())
    return lemmas


def test_verb_cases_keys_are_a1_lemmas():
    """键 MUST ⊆ 歌德 A1 词表的 lemma 集（不许登记课外动词）。"""
    lemmas = _a1_lemma_set()
    unknown = sorted(k for k in A1_VERB_CASES if k.strip().lower() not in lemmas)
    assert unknown == [], f"词表键必须在歌德 A1 词表内，未知键={unknown}"


def test_verb_cases_values_are_valid():
    """值 MUST ∈ {Dat, Acc, Dat+Acc}（第三种 = 两可支配 ⇒ 检测器不判）。"""
    assert set(A1_VERB_CASES.values()) <= {"Dat", "Acc", "Dat+Acc"}


def test_verb_cases_min_size_and_no_empty_keys():
    """条目数 ≥ 5，且无空键（少而准是设计目标，但空数据不算数据）。"""
    assert len(A1_VERB_CASES) >= 5
    assert all(k.strip() for k in A1_VERB_CASES)
