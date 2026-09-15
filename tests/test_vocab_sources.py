# -*- coding: utf-8 -*-
"""Task R4a：服务端 sources 贯通（ADR-0012）契约测试 —— 纯增量，默认行为逐字不变。

钉住六件事：
1. ``sources={"official"}`` 官方**原样**视图 = A1 670 / A2 736 / B1 1617
   （``lexicon.official_level`` 各档保留官方原样、容忍跨档重叠）；
2. 官方视图逐条 == 9 字段契约集（与
   ``tests/test_vocab_contract_uniform.py::CONTRACT_FIELDS`` 同口径）；
3. id 形态：A2 -> ``a2-{lemma}``、B1 -> ``b1-{lemma}``；
4. **默认路径回归护栏**：``sources=None``（默认）A2 仍 974、B1 仍 1712，
   与改造前逐字一致；
5. 官方视图与 scope 无关（``core`` 与 ``all`` 同结果）；
6. 未知来源名（不含 ``"official"`` 的非 None 集合）→ 与 ``sources=None`` 同路
   （降级为默认视图，绝不静默返回空表）—— 本文件把该决策钉成契约。
"""

from typing import Any, Dict, List

import pytest

from delector.core import database
from delector.core.database import get_vocab_by_cefr
from delector.core.lexicon import official_level

# 唯一契约字段集（同 test_vocab_contract_uniform.CONTRACT_FIELDS）
CONTRACT_FIELDS = {"id", "hw", "pos", "gender", "plural", "de", "zh", "core", "cefr"}

# 官方原样视图条数（各档保留官方原样，容忍跨档重叠）
OFFICIAL_A1_TOTAL = 670  # OFFICIAL_A1_VOCAB(660) ⊕ OFFICIAL_A1_AUGMENT(10)
OFFICIAL_A2_TOTAL = 736
OFFICIAL_B1_TOTAL = 1617

# 默认路径（sources=None）既有基线，改造不得触碰
DEFAULT_A2_TOTAL = 974
DEFAULT_B1_TOTAL = 1712


@pytest.fixture(autouse=True)
def fresh_vocab_caches():
    """隔离模块级缓存，防跨测试泄漏（同 test_vocab_contract_uniform）。"""
    database._reset_a1_workbench_cache()
    database._A2_VOCAB_CACHE = None
    yield
    database._reset_a1_workbench_cache()
    database._A2_VOCAB_CACHE = None


# ── 交付 1：lexicon.official_level ──────────────────────────────────────────


def test_official_level_counts():
    """各档实测条数：A1 670 / A2 736 / B1 1617。"""
    assert len(official_level("A1")) == OFFICIAL_A1_TOTAL
    assert len(official_level("A2")) == OFFICIAL_A2_TOTAL
    assert len(official_level("B1")) == OFFICIAL_B1_TOTAL


def test_official_level_case_insensitive_and_unknown():
    """大小写/空白不敏感；未知等级返回空 dict（不炸）。"""
    assert official_level(" a2 ") == official_level("A2")
    assert official_level("a1") == official_level("A1")
    assert official_level("B2") == {}
    assert official_level("") == {}


def test_official_level_keeps_cross_level_overlap():
    """官方各档「原样」：A1⊕A2B1 的 291 条跨档重叠不会让任一侧变少 ——
    A1 视图包含 ruhig/zurzeit（这两条在 A2B1 片里也出现）。"""
    a1 = official_level("A1")
    assert "ruhig" in a1 and "zurzeit" in a1
    assert a1["ruhig"][0] == "A1"


# ── 交付 2：get_vocab_by_cefr(sources=...) ─────────────────────────────────


def _assert_contract_uniform(words: List[Dict[str, Any]]) -> None:
    assert words, "官方视图不应为空表"
    for w in words:
        assert set(w.keys()) == CONTRACT_FIELDS, (
            f"{w.get('id')} 字段集漂移：{sorted(w.keys())}（契约要求 {sorted(CONTRACT_FIELDS)}）"
        )


@pytest.mark.parametrize(
    "cefr,expected",
    [("A1", OFFICIAL_A1_TOTAL), ("A2", OFFICIAL_A2_TOTAL), ("B1", OFFICIAL_B1_TOTAL)],
)
def test_sources_official_counts(cefr, expected):
    """sources={"official"} 各档条数。"""
    res = get_vocab_by_cefr(cefr=cefr, sources={"official"})
    assert res["cefr"] == cefr
    assert res["total"] == expected
    assert len(res["words"]) == expected


def test_sources_official_contract_uniform():
    """官方视图每条为 9 字段契约集（不新增字段）。"""
    for cefr in ("A1", "A2", "B1"):
        _assert_contract_uniform(get_vocab_by_cefr(cefr=cefr, sources={"official"})["words"])


def test_sources_official_id_shape():
    """A2 条目 id 形如 a2-{lemma}、B1 形如 b1-{lemma}。"""
    a2 = get_vocab_by_cefr(cefr="A2", sources={"official"})["words"]
    b1 = get_vocab_by_cefr(cefr="B1", sources={"official"})["words"]
    assert all(w["id"].startswith("a2-") and len(w["id"]) > 3 for w in a2), "存在非 a2-{lemma} 形态 id"
    assert all(w["id"].startswith("b1-") and len(w["id"]) > 3 for w in b1), "存在非 b1-{lemma} 形态 id"
    ids_a2 = [w["id"] for w in a2]
    ids_b1 = [w["id"] for w in b1]
    assert len(set(ids_a2)) == len(ids_a2), "A2 官方视图 id 有重复"
    assert len(set(ids_b1)) == len(ids_b1), "B1 官方视图 id 有重复"


def test_sources_official_scope_agnostic():
    """官方视图是该级全量：scope=core 与 scope=all 同结果（736/1617）。"""
    for cefr, expected in (("A2", OFFICIAL_A2_TOTAL), ("B1", OFFICIAL_B1_TOTAL)):
        core = get_vocab_by_cefr(cefr=cefr, scope="core", sources={"official"})
        all_ = get_vocab_by_cefr(cefr=cefr, scope="all", sources={"official"})
        assert core["total"] == expected
        assert all_["total"] == expected
        assert core["words"] == all_["words"]


# ── 交付 2 铁律：默认路径回归护栏（sources=None 逐字不变） ───────────────────


def test_default_path_unchanged_regression_guard():
    """不给 sources 时必须完全走现有分支：A2 974 / B1 1712 逐字不变。"""
    assert get_vocab_by_cefr("A2")["total"] == DEFAULT_A2_TOTAL
    assert get_vocab_by_cefr("A2", scope="all")["total"] == DEFAULT_A2_TOTAL
    assert get_vocab_by_cefr("B1")["total"] == DEFAULT_B1_TOTAL
    assert get_vocab_by_cefr("B1", scope="all")["total"] == DEFAULT_B1_TOTAL


def test_unknown_source_falls_back_to_default():
    """未知来源名（不含 official 的非 None 集合）→ 与 sources=None 同路（降级默认视图）。"""
    for cefr, expected in (("A2", DEFAULT_A2_TOTAL), ("B1", DEFAULT_B1_TOTAL)):
        base = get_vocab_by_cefr(cefr=cefr)
        unknown = get_vocab_by_cefr(cefr=cefr, sources={"nope"})
        assert unknown["total"] == base["total"] == expected
        assert unknown["words"] == base["words"]
