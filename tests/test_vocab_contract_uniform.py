# -*- coding: utf-8 -*-
"""词对象契约统一（Task 3 / ADR-0011 决策 2，输出侧）。

钉住三件事：
1. ``get_vocab_by_cefr`` 各分支（A1 core/all、A2、B1 通用分支）产出**同一字段集**
   ``{id, hw, pos, gender, plural, de, zh, core, cefr}``，缺失字段显式空值；
2. 条数与权威基线一致（A1 235/704 硬编码；A2/B1 从 core_dict 动态推导）、
   B1 仍走通用分支（id 形如 ``b1-{lemma}``）；
3. ``hw`` 拼装规则未被改动（A2 名词仍 ``das Abenteuer`` 形态，format_vocab_headword 单一装饰点）。

CRV 黄牌承接①：core_dict 数据模块缺失 = 打包损坏，必须直接炸（ImportError），
不得静默回退为空表（红线 2 同型根除）。
"""

import sys
from typing import Any, Dict, List

import pytest

from delector.core import database
from delector.core.database import get_vocab_by_cefr
from delector.data.core_dict import CORE_VOCAB_DB

# 唯一契约字段集（ADR-0011 决策 2：一份 schema，缺失字段显式空值）
CONTRACT_FIELDS = {"id", "hw", "pos", "gender", "plural", "de", "zh", "core", "cefr"}

# 条数基线（T2 后）：A1 core = 213 seed core ids + 22 customs；A1 all = 682 seeds + 22 customs。
# A1 走 a1_dict 工作台分支，与 core_dict 无关，故仍为硬编码基线。
A1_CORE_TOTAL = 235
A1_ALL_TOTAL = 704
# A2/B1 条数从权威数据源（core_dict 中对应 CEFR 的条目数）**动态推导**：
# 官方词表接入后 A2/B1 分布随数据变更（R5-v2 字段级合并），硬编码基线会静默漂移。
# 断言仍守住原意——「通用/A2 分支不得静默漏读或重复读 core_dict 条目」。
A2_TOTAL = sum(1 for val in CORE_VOCAB_DB.values() if val[0].upper() == "A2")
B1_TOTAL = sum(1 for val in CORE_VOCAB_DB.values() if val[0].upper() == "B1")


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


def test_a2_contract_uniform_and_count():
    """A2：并入统一契约后条数 == core_dict A2 条目数，字段集与 A1 完全一致。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    assert res["total"] == A2_TOTAL
    _assert_contract_uniform(res["words"], 10)


def test_a2_hw_assembly_unchanged():
    """hw 拼装规则未被改动：A2 名词仍 'das Krankenhaus' 形态（定冠词 + 大写）。

    抽样词取当前仍属 A2 的名词（abenteuer/abfahrt/abfall 已按官方 cefr 改档）。
    """
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}
    assert word_map["a2-krankenhaus"]["hw"] == "das Krankenhaus"
    assert word_map["a2-ampel"]["hw"] == "die Ampel"
    assert word_map["a2-besuch"]["hw"] == "der Besuch"


def test_b1_generic_branch_contract_uniform():
    """B1：仍走通用分支，id 形如 b1-{lemma}，字段集同契约。"""
    res = get_vocab_by_cefr(cefr="B1", scope="all")
    # 【CRV 黄牌承接 Y2】条数钉死为权威基线，防止通用分支静默漏读/重复读；
    # 权威词表接入后随数据变更同 commit 更新 B1_TOTAL。
    assert res["total"] == B1_TOTAL, (
        f"B1 词库条数漂移：{res['total']} != {B1_TOTAL}"
        "（权威词表接入后随数据变更同 commit 更新 B1_TOTAL）"
    )
    _assert_contract_uniform(res["words"], 10)
    ids = [w["id"] for w in res["words"]]
    assert all(i.startswith("b1-") and len(i) > 3 for i in ids), "B1 存在非 b1-{lemma} 形态的 id"
    assert len(set(ids)) == len(ids), "B1 id 有重复"


def test_cefr_all_contract_uniform():
    """【CRV 黄牌承接 Y3】cefr="ALL" 聚合分支（A1 视图 ⊕ A2 ⊕ 其余 core_dict 级别）
    同样必须产出统一契约字段集 —— 聚合路径漏掉 _contract_from_core_entry 之类的
    装饰点就会在这里爆出字段集漂移。"""
    res = get_vocab_by_cefr(cefr="ALL", scope="all")
    assert res["total"] > 0, "ALL 聚合不应为空表"
    _assert_contract_uniform(res["words"], 10)


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
