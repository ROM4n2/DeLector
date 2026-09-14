# -*- coding: utf-8 -*-
"""词对象契约统一（Task 3 / ADR-0011 决策 2，输出侧）。

钉住三件事：
1. ``get_vocab_by_cefr`` 各分支（A1 core/all、A2、B1 通用分支）产出**同一字段集**
   ``{id, hw, pos, gender, plural, de, zh, core, cefr}``，缺失字段显式空值；
2. 条数与 T2 后基线一致（A1 235/704、A2 974）、B1 仍走通用分支（id 形如 ``b1-{lemma}``）；
3. ``hw`` 拼装规则未被改动（A2 名词仍 ``das Abenteuer`` 形态，format_vocab_headword 单一装饰点）。

CRV 黄牌承接①：core_dict 数据模块缺失 = 打包损坏，必须直接炸（ImportError），
不得静默回退为空表（红线 2 同型根除）。
"""

import sys
from typing import Any, Dict, List

import pytest

from delector.core import database
from delector.core.database import get_vocab_by_cefr

# 唯一契约字段集（ADR-0011 决策 2：一份 schema，缺失字段显式空值）
CONTRACT_FIELDS = {"id", "hw", "pos", "gender", "plural", "de", "zh", "core", "cefr"}

# 条数基线（T2 后）：A1 core = 213 seed core ids + 22 customs；A1 all = 682 seeds + 22 customs
A1_CORE_TOTAL = 235
A1_ALL_TOTAL = 704
A2_TOTAL = 974


@pytest.fixture(autouse=True)
def fresh_vocab_caches():
    """隔离两级模块缓存，防跨测试泄漏。"""
    database._reset_a1_workbench_cache()
    database._A2_VOCAB_CACHE = None
    yield
    database._reset_a1_workbench_cache()
    database._A2_VOCAB_CACHE = None


def _assert_contract_uniform(words: List[Dict[str, Any]], min_count: int) -> None:
    assert len(words) >= min_count, f"样本不足：{len(words)} < {min_count}"
    for w in words:
        assert set(w.keys()) == CONTRACT_FIELDS, (
            f"{w.get('id')} 字段集漂移：{sorted(w.keys())}（契约要求 {sorted(CONTRACT_FIELDS)}）"
        )


def test_a1_core_scope_contract_uniform():
    """A1 core：字段集 == 契约集，gender/plural 显式空值（不做冠词推导）。"""
    res = get_vocab_by_cefr(cefr="A1", scope="core")
    assert res["total"] == A1_CORE_TOTAL
    _assert_contract_uniform(res["words"], 10)
    for w in res["words"][:10]:
        assert w["gender"] is None, f"{w['id']} A1 gender 应显式 None"
        assert w["plural"] == "", f"{w['id']} A1 plural 应显式空串"
        assert w["cefr"] == "A1"


def test_a1_all_scope_contract_uniform():
    """A1 all：同一契约集，条数与 T2 后一致。"""
    res = get_vocab_by_cefr(cefr="A1", scope="all")
    assert res["total"] == A1_ALL_TOTAL
    _assert_contract_uniform(res["words"], 10)


def test_a2_contract_uniform_and_count_974():
    """A2：并入统一契约后仍为 974 条，字段集与 A1 完全一致。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    assert res["total"] == A2_TOTAL
    _assert_contract_uniform(res["words"], 10)


def test_a2_hw_assembly_unchanged():
    """hw 拼装规则未被改动：A2 名词仍 'das Abenteuer' 形态（定冠词 + 大写）。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}
    assert word_map["a2-abenteuer"]["hw"] == "das Abenteuer"
    assert word_map["a2-abfahrt"]["hw"] == "die Abfahrt"
    assert word_map["a2-abfall"]["hw"] == "der Abfall"


def test_b1_generic_branch_contract_uniform():
    """B1：仍走通用分支，id 形如 b1-{lemma}，字段集同契约。"""
    res = get_vocab_by_cefr(cefr="B1", scope="all")
    assert res["total"] >= 1000, "B1 词库条数异常（权威词表接入前应为 1712 量级）"
    _assert_contract_uniform(res["words"], 10)
    ids = [w["id"] for w in res["words"]]
    assert all(i.startswith("b1-") and len(i) > 3 for i in ids), "B1 存在非 b1-{lemma} 形态的 id"
    assert len(set(ids)) == len(ids), "B1 id 有重复"


def test_a2_missing_core_dict_raises(monkeypatch):
    """CRV 黄牌承接①：core_dict 缺失 = 打包损坏，ImportError 必须炸出，不得返回空表。"""
    monkeypatch.setitem(sys.modules, "delector.data.core_dict", None)
    with pytest.raises(ImportError):
        get_vocab_by_cefr(cefr="A2", scope="all")


def test_b1_missing_core_dict_raises(monkeypatch):
    """CRV 黄牌承接①：通用分支（B1）同样不得静默回退。"""
    monkeypatch.setitem(sys.modules, "delector.data.core_dict", None)
    with pytest.raises(ImportError):
        get_vocab_by_cefr(cefr="B1", scope="all")
