# -*- coding: utf-8 -*-
"""名词格位纠偏回归：报告句的复数第四格误标 + 反例集不回归。

背景见 docs/reviews/2026-11-06-german-plural-akkusativ-mislabeled-nominativ.md：
de_core_news_sm 的 morphologizer 把 "die Bücher" 的复数宾语标成 Case=Nom，
parser 只改依存为 oa、不回写 Case，DeLector 原样透传。
"""
import pytest

from delector.nlp_engine.syntax_tree import analyze_syntax_tree

FIELDS = ("vorfeld", "linke_klammer", "mittelfeld", "rechte_klammer", "nachfeld")


def _tokens(sentence):
    result = analyze_syntax_tree(sentence)
    merged = {}
    for sent in result["sentences"]:
        for field in FIELDS:
            for tok in sent["topology"][field]:
                merged[tok["id"]] = tok
    return [merged[key] for key in sorted(merged)]


def _case_of(sentence, word, occurrence=1):
    hits = [tok for tok in _tokens(sentence) if tok["text"] == word]
    assert len(hits) >= occurrence, f"{word!r} 未出现在 {sentence!r} 的分析结果中"
    return hits[occurrence - 1]["case"]


# ── 修复目标：报告句与同族无冠词句 ────────────────────────────────────────────


def test_reported_sentence_plural_accusative():
    assert _case_of("Die Lehrerin gibt den Schülern die Bücher.", "Bücher") == "Acc"


def test_no_determiner_object_with_subject():
    assert _case_of("Wir geben Schülern Bücher.", "Bücher") == "Acc"


def test_dative_only_verb_without_determiner():
    assert _case_of("Ich danke Lehrern.", "Lehrern") == "Dat"
    assert _case_of("Ich helfe Schülerinnen.", "Schülerinnen") == "Dat"


def test_accusative_weak_noun_singular():
    assert _case_of("Ich sehe den Studenten.", "Studenten") == "Acc"


def test_subject_lookup_through_auxiliary_chain():
    assert _case_of("Ich habe den Studenten gesehen.", "Studenten") == "Acc"
    assert _case_of("Bücher habe ich gelesen.", "Bücher") == "Acc"
    assert _case_of("Den Studenten habe ich gesehen.", "Studenten") == "Acc"


# ── 反例集：修复前正确的情形必须保持正确 ──────────────────────────────────────


@pytest.mark.parametrize(
    "sentence,word",
    [
        ("Hunde bellen.", "Hunde"),
        ("Wolken ziehen.", "Wolken"),
        ("Wellen rollen.", "Wellen"),
        ("Die starken Winde wehen.", "Winde"),
        ("Den Schülern helfen die Lehrer.", "Lehrer"),
        ("Die Kinder sehen den Film.", "Kinder"),
    ],
)
def test_bare_subject_stays_nominative(sentence, word):
    assert _case_of(sentence, word) == "Nom"


@pytest.mark.parametrize(
    "sentence,word,expected",
    [
        ("Ich helfe Lehrern.", "Lehrern", "Dat"),
        ("Ich folge Hunden.", "Hunden", "Dat"),
        ("Ich gedenke alter Männer.", "Männer", "Gen"),
        ("Ich helfe den Schülern.", "Schülern", "Dat"),
        ("Ich helfe guten Schülern.", "Schülern", "Dat"),
        ("Ich danke den Lehrern.", "Lehrern", "Dat"),
        ("Ich sehe den Film.", "Film", "Acc"),
        ("Ich lese die Bücher.", "Bücher", "Acc"),
        ("Ich habe die Bücher gelesen.", "Bücher", "Acc"),
        ("Ich will Bücher lesen.", "Bücher", "Acc"),
        ("Ich helfe dem Studenten.", "Studenten", "Dat"),
        ("Ich gedenke des Mannes.", "Mannes", "Gen"),
    ],
)
def test_correct_objects_unchanged(sentence, word, expected):
    assert _case_of(sentence, word) == expected


@pytest.mark.parametrize(
    "sentence,word,expected",
    [
        ("Ich fahre mit dem Bus.", "Bus", "Dat"),
        ("Ich fahre für den Mann.", "Mann", "Acc"),
        ("Ich gehe wegen des Regens.", "Regens", "Gen"),
        ("Ich warte auf den Bus.", "Bus", "Acc"),
    ],
)
def test_prepositional_phrases_unchanged(sentence, word, expected):
    assert _case_of(sentence, word) == expected


# ── 已确认边界：两词片段不可判定 ──────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bücher geben. 与 Kinder essen. 词形/依存完全同形（NOUN Plur dep=oa Case=Nom + "
        "VERB VerbForm=Inf，且均无主语）；任何无主语即判宾格的规则都会把 Kinder essen. "
        "的正确主格改错。需要语义/生命度信息，当前离线模型不提供，故不修。"
    ),
)
def test_bare_fragment_known_limitation():
    assert _case_of("Bücher geben.", "Bücher") == "Acc"


def test_bare_fragment_counterpart_keeps_subject_reading():
    assert _case_of("Kinder essen.", "Kinder") == "Nom"
