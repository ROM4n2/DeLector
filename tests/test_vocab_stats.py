# -*- coding: utf-8 -*-
"""B1：vocab_stats 工具（第 6 个 leaf tool）——按 A1/A2 考纲词集 + known_extra
统计 token 的 known 覆盖率与未知词频排名；纯函数、无 DB（ADR-0009 纪律）。

已知 = lemma ∈ (A1∪A2 考纲词 lemma 集) ∪ known_extra（hw 小写比对）。词集取自既有
delector.services.exam_catalog 口径所引用的数据源（A1 = GOETHE_A1_VOCAB 的
lemma 字段；A2 = core_dict A2 条目 lemma），**不内嵌新词表**——故测试用真实
A1/A2 词断言 known/unknown 判定（非死测试）。
"""

import asyncio

import pytest

from delector.tools.vocab_stats import run


def _tokens(spec):
    """按 [(lemma, count)...] 规格展开 token 列表。"""
    out = []
    for lemma, count in spec:
        for _ in range(count):
            out.append({"text": lemma, "lemma": lemma, "pos": "NOUN"})
    return out


def _payload(tokens, known_extra=None, levels=None):
    p = {"tokens": tokens}
    if known_extra is not None:
        p["known_extra"] = known_extra
    if levels is not None:
        p["levels"] = levels
    return p


# ---------- known/unknown 判定（真实 A1/A2 词，非死测试） ----------
def test_known_a1_word_when_level_contains_a1():
    # "gehen" 是 GOETHE_A1_VOCAB 真实词条 lemma
    out = asyncio.run(run(_payload(_tokens([("gehen", 1)]), levels=["A1"])))
    assert out["tokens_total"] == 1
    assert out["known_count"] == 1
    assert out["known_rate"] == 1.0
    assert out["unknown_ranked"] == []


def test_a2_word_only_known_when_level_contains_a2():
    # "abbiegen" 是 core_dict A2 真实词条 lemma
    lev_a1 = asyncio.run(run(_payload(_tokens([("abbiegen", 1)]), levels=["A1"])))
    assert lev_a1["known_count"] == 0
    lev_both = asyncio.run(run(_payload(_tokens([("abbiegen", 1)]), levels=["A1", "A2"])))
    assert lev_both["known_count"] == 1


def test_level_selection_defaults_to_a1_a2():
    # levels 缺省 = A1∪A2
    out = asyncio.run(run(_payload(_tokens([("gehen", 1), ("abbiegen", 1)]))))
    assert out["known_count"] == 2


# ---------- known_extra 追加（hw 小写比对） ----------
def test_known_extra_lowercased_matched():
    # 虚构 lemma 不在考纲内，但 known_extra 大写补入 → 命中
    out = asyncio.run(
        run(
            _payload(
                _tokens([("Brimborium", 1)]),
                known_extra=["brimborium"],
                levels=["A1"],
            )
        )
    )
    assert out["known_count"] == 1


# ---------- 未知词频序 + 封顶 60 ----------
def test_unknown_ranked_sorted_by_frequency_desc():
    out = asyncio.run(
        run(
            _payload(
                _tokens(
                    [
                        ("zebranope", 1),  # 频 1
                        ("alpha_nope", 5),  # 频 5
                        ("mid_nope", 3),  # 频 3
                    ]
                ),
                levels=["A1"],
            )
        )
    )
    got = [(e["lemma"], e["count"]) for e in out["unknown_ranked"]]
    assert got == [("alpha_nope", 5), ("mid_nope", 3), ("zebranope", 1)]
    assert out["known_count"] == 0


def test_unknown_ranked_capped_at_60():
    # 65 个互异未知 lemma，各 1 次 → 封顶返回 60 条
    spec = [(f"u{i:03d}", 1) for i in range(65)]
    out = asyncio.run(run(_payload(_tokens(spec), levels=["A1"])))
    assert len(out["unknown_ranked"]) == 60
    assert all(e["count"] == 1 for e in out["unknown_ranked"])


# ---------- level_hint 阈值（含边界） ----------
def _hint_for_unknown_count(total, unknown_count):
    """total 个 token，前 (total-unknown_count) 个用 A1 已知词 'gehen'，
    其余用互异未知 lemma。"""
    known = _tokens([("gehen", total - unknown_count)])
    unknown = _tokens([(f"q{i}", 1) for i in range(unknown_count)])
    return asyncio.run(run(_payload(known + unknown, levels=["A1"])))["level_hint"]


def test_level_hint_boundaries():
    assert _hint_for_unknown_count(20, 3) == "A1"  # 0.15 ≤0.15 → A1
    assert _hint_for_unknown_count(20, 4) == "A2"  # 0.20
    assert _hint_for_unknown_count(20, 7) == "A2"  # 0.35 ≤0.35 → A2
    assert _hint_for_unknown_count(20, 8) == "B1"  # 0.40 >0.35 → B1


# ---------- 空 tokens 边界（文档化：unknown_rate 视 0） ----------
def test_empty_tokens():
    out = asyncio.run(run(_payload([], levels=["A1", "A2"])))
    assert out["tokens_total"] == 0
    assert out["known_count"] == 0
    assert out["known_rate"] == 0.0
    assert out["unknown_ranked"] == []
    assert out["level_hint"] == "A1"  # 无 token → unknown_rate 定义 0


# ---------- 返回字段形状 / known_rate 舍入 ----------
def test_known_rate_rounded_to_3_decimals():
    # 已知 80 / 120 → 0.666... → 0.667（对齐契约示例）
    known = _tokens([("gehen", 80)])
    unknown = _tokens([(f"x{i}", 1) for i in range(40)])
    out = asyncio.run(run(_payload(known + unknown, levels=["A1"])))
    assert out["tokens_total"] == 120
    assert out["known_count"] == 80
    assert out["known_rate"] == 0.667
    assert set(out.keys()) == {
        "tokens_total",
        "known_count",
        "known_rate",
        "unknown_ranked",
        "level_hint",
    }


# ---------- Guard Clauses（畸形 payload） ----------
def test_guard_tokens_not_list():
    with pytest.raises(ValueError):
        asyncio.run(run({"tokens": "nope"}))


def test_guard_token_missing_lemma():
    with pytest.raises(ValueError):
        asyncio.run(run(_payload([{"text": "x", "pos": "NOUN"}])))


def test_guard_unsupported_level():
    with pytest.raises(ValueError):
        asyncio.run(run(_payload(_tokens([("gehen", 1)]), levels=["B1"])))
