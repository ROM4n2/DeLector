# -*- coding: utf-8 -*-
"""ADR-0015 T1：lemma_key 唯一实现 + 富字段只补空合并。"""

from delector.data.a1_dict import GOETHE_A1_VOCAB
from delector.data.a1_workbench_dict import A1_WORKBENCH_CUSTOM, A1_WORKBENCH_SEED
from delector.data.lexicon_merge import (
    FIELD_PRIORITY,
    RICH_FIELD_PRIORITY,
    lemma_key,
    merge_fragments,
    merge_rich_fragments,
)


def test_lemma_key_samples() -> None:
    assert lemma_key("die Adresse,-en") == "adresse"
    assert lemma_key("all-") == "all"
    assert lemma_key("(sich) anmelden") == "anmelden"
    assert lemma_key("an sein") == "an-sein"
    assert lemma_key("der Apfel, -Ä") == "apfel"
    assert lemma_key("ab") == "ab"


def test_lemma_key_idempotent() -> None:
    for w in A1_WORKBENCH_SEED:
        k = lemma_key(w["hw"])
        assert lemma_key(k) == k
    for k0 in GOETHE_A1_VOCAB:
        k = lemma_key(k0)
        assert lemma_key(k) == k


def test_lemma_key_intersection_is_391() -> None:
    seed = {lemma_key(w["hw"]) for w in A1_WORKBENCH_SEED}
    seed |= {lemma_key(w["hw"]) for w in A1_WORKBENCH_CUSTOM}
    goe = {lemma_key(k) for k in GOETHE_A1_VOCAB}
    assert len(seed & goe) == 391
    assert len(seed) == 700
    assert len(goe) == 702


def test_rich_merge_fill_empty_only() -> None:
    frags = {
        "workbench-a1": {
            "ab": {
                "ipa": "ˈap",
                "example_de": "Ab morgen.",
                "example_zh": "从明天起。",
                "examples": [{"de": "Ab morgen.", "zh": "从明天起。"}],
                "topic": "",
            },
        },
        "goethe-a1": {
            "ab": {
                "ipa": "",
                "example_de": "Der Zug fährt ab.",
                "example_zh": "火车开出。",
                "examples": [],
                "topic": "travel",
            },
            "nur_goethe": {
                "ipa": "",
                "example_de": "x",
                "example_zh": "y",
                "examples": [{"de": "x", "zh": "y"}],
                "topic": "phrases",
            },
        },
        "official_rich_a1": {
            "ab": {"ipa": "G2P", "example_de": "rich", "example_zh": "richzh", "examples": [], "topic": "general"},
        },
    }
    merged = merge_rich_fragments(frags)
    ab = merged["ab"]
    assert ab["ipa"] == "ˈap"  # 人工 > g2p
    assert ab["example_de"] == "Ab morgen."
    assert ab["topic"] == "travel"  # workbench 空 topic 不挡 goethe
    assert ab["examples"] == [{"de": "Ab morgen.", "zh": "从明天起。"}]
    only = merged["nur_goethe"]
    assert only["ipa"] is None  # 全空显式 None，不编造
    assert only["topic"] == "phrases"


def test_rich_merge_never_overwrites_nonempty() -> None:
    frags = {
        "official_rich_a1": {"w": {"ipa": "low", "example_de": "L", "example_zh": "l", "examples": [], "topic": "g"}},
        "workbench-a1": {
            "w": {
                "ipa": "HIGH",
                "example_de": "H",
                "example_zh": "h",
                "examples": [{"de": "H", "zh": "h"}],
                "topic": "",
            }
        },
    }
    merged = merge_rich_fragments(frags)
    assert merged["w"]["ipa"] == "HIGH"
    assert merged["w"]["example_de"] == "H"


def test_rich_field_priority_covers_sources() -> None:
    assert RICH_FIELD_PRIORITY["ipa"][0] == "workbench-a1"
    assert "goethe-a1" in RICH_FIELD_PRIORITY["ipa"]
    assert FIELD_PRIORITY["gender"][0] == "goethe-a1"
    assert FIELD_PRIORITY["pos"] == ("manual", "official", "ai")
    # plural 后缀位不收 GOETHE 完整形
    assert FIELD_PRIORITY["plural"] == ("manual", "official", "ai")

def test_merge_fragments_skips_empty_takes_next_source() -> None:
    # 5 元组合并 = first non-empty（ADR-0015）：空值不得挡低优先级补全。
    frags = {
        "goethe-a1": {"w": ("A1", "NOUN", None, "", "考纲")},
        "manual": {"w": ("A1", "NOUN", "Masc", "-", "手")},
        "official": {"w": ("A2", "NOUN", "Fem", "-n", "官")},
    }
    merged = merge_fragments(frags, FIELD_PRIORITY)
    assert merged["w"][0] == "A2"  # cefr: official > goethe-a1
    assert merged["w"][2] == "Masc"  # goethe gender None → manual
    assert merged["w"][3] == "-"  # goethe plural 空 → manual 占位 '-' 仍算有值
    assert merged["w"][4] == "考纲"  # goethe def_zh 胜出
