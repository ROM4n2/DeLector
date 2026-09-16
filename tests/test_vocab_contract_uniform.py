# -*- coding: utf-8 -*-
"""词对象契约统一（Task 3 / ADR-0011 决策 2；S4 契约 9 → 11，ADR-0013 §4-1，输出侧）。

钉住三件事：
1. ``get_vocab_by_cefr`` 各分支（A1 core/all、A2、B1 通用分支）产出**同一 11 字段集**
   ``{id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr}``，缺失字段显式空值；
2. 条数与权威基线一致（A1 235/704 硬编码；A2/B1 从 core_dict 动态推导）、
   B1 仍走通用分支（id 形如 ``b1-{lemma}``）；
3. ``hw`` 拼装规则未被改动（A2 名词仍 ``das Abenteuer`` 形态，format_vocab_headword 单一装饰点）。

S4 新增两字段语义（ADR-0013 §4-1）：
- ``ipa``：音标；``example_zh``：例句中文对照。
- ``de`` 语义统一为**德语例句**（A1 = ``ex[0].de``；A2/B1/官方 = rich ``example_de``）。
- A2/B1/官方富字段取自 ``lexicon.rich_of(lemma)``；未登记 lemma（rich 无）显式空串
  （ADR-0013 §5-3：禁止编造 / 静默降级）；A1 的两字段来自 ``A1_WORKBENCH_SEED``（S3）。

CRV 黄牌承接①（R6 迁移后）：主干 **lexicon** 缺失 = 打包损坏，必须直接炸（ImportError），
不得静默回退为空表（红线 2 同型根除）。R6 已把 database 的 A2/通用分支导入来源由
``delector.data.core_dict`` 迁到 ``delector.core.lexicon``（``LEXICON as CORE_VOCAB_DB``），
故打桩目标须同步为真实导入来源，否则旧打桩失效、用例假绿。
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from delector.core import database
from delector.core.database import get_vocab_by_cefr
from delector.data.core_dict import CORE_VOCAB_DB

# 唯一契约字段集（ADR-0013 §4-1：9 → 11；一份 schema，缺失字段显式空值）
CONTRACT_FIELDS = {"id", "hw", "pos", "gender", "plural", "de", "zh", "ipa", "example_zh", "core", "cefr"}

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


def test_a2_missing_backbone_raises(monkeypatch):
    """CRV 黄牌承接①（R6 迁移后）：主干 lexicon 缺失 = 打包损坏，ImportError 必须炸出，
    不得返回空表（红线 2）。

    打桩目标是 database.py A2 分支的**真实导入来源** ``delector.core.lexicon``
    （``from delector.core.lexicon import LEXICON as CORE_VOCAB_DB``，R6 由 core_dict 迁入）。
    """
    monkeypatch.setitem(sys.modules, "delector.core.lexicon", None)
    with pytest.raises(ImportError):
        get_vocab_by_cefr(cefr="A2", scope="all")


def test_b1_missing_backbone_raises(monkeypatch):
    """CRV 黄牌承接①（R6 迁移后）：通用分支（B1）同样不得静默回退。

    打桩目标同 ``test_a2_missing_backbone_raises``（真实导入来源 ``delector.core.lexicon``）。
    """
    monkeypatch.setitem(sys.modules, "delector.core.lexicon", None)
    with pytest.raises(ImportError):
        get_vocab_by_cefr(cefr="B1", scope="all")


def test_backbone_import_chain_is_hard_dependency():
    """双保险（源码层静态钉）：主干缺失的硬依赖链是 ``lexicon → core_dict``。

    上面两条运行期用例证明「主干缺失 → ImportError 炸出」；本条从**源码文本**再钉一次
    根因，防止未来有人在分片导入上悄悄加 ``try/except`` 兜底——那会把「打包损坏」
    静默降级成空表，正是红线 2 要根除的形态：

    1. ``delector/core/lexicon.py`` 顶层**模块级直接** ``from delector.data.core_dict import ...``
       （无 try/except，缺失即 ImportError）；
    2. 该文件源码中**不存在** ``except ImportError``，即任何分片导入都不做静默回退。

    实现刻意用「读文件文本 + 字符串匹配」，避免 import 内部结构带来的脆弱性。
    """
    lexicon_src = (
        Path(__file__).resolve().parents[1] / "delector" / "core" / "lexicon.py"
    ).read_text(encoding="utf-8")
    assert "from delector.data.core_dict import" in lexicon_src, (
        "主干 lexicon 未直连 core_dict 分片：硬依赖链断裂（契约已漂移）"
    )
    assert "except ImportError" not in lexicon_src, (
        "lexicon 出现 except ImportError 兜底：主干缺失将被静默降级为空表，违反红线 2"
    )


# ── S4：契约 9 → 11（ipa / example_zh 富字段贯通；ADR-0013 §4-1 / §5-3）──────────


def test_a2_rich_fields_present_and_sourced():
    """A2 条目 ipa / example_zh / de 非空，且逐字来自主干富字段 rich_of（抽样 ≥3）。"""
    from delector.core.lexicon import rich_of

    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}
    for lemma in ("ampel", "anmelden", "aktuell"):
        w = word_map[f"a2-{lemma}"]
        r = rich_of(lemma)
        assert r is not None, f"{lemma} 富字段缺失（样本前提失效）"
        assert w["ipa"] and w["ipa"] == r["ipa"], f"{lemma} ipa 未接通富字段"
        assert w["example_zh"] and w["example_zh"] == r["example_zh"], f"{lemma} example_zh 未接通富字段"
        assert w["de"] and w["de"] == r["example_de"], f"{lemma} de 应为富字段德语例句"


def test_b1_rich_fields_present_and_sourced():
    """B1 条目 ipa / example_zh / de 非空，且逐字来自主干富字段 rich_of（抽样 ≥3）。"""
    from delector.core.lexicon import rich_of

    res = get_vocab_by_cefr(cefr="B1", scope="all")
    word_map = {w["id"]: w for w in res["words"]}
    for lemma in ("abenteuer", "abfall", "abschreiben"):
        w = word_map[f"b1-{lemma}"]
        r = rich_of(lemma)
        assert r is not None, f"{lemma} 富字段缺失（样本前提失效）"
        assert w["ipa"] and w["ipa"] == r["ipa"], f"{lemma} ipa 未接通富字段"
        assert w["example_zh"] and w["example_zh"] == r["example_zh"], f"{lemma} example_zh 未接通富字段"
        assert w["de"] and w["de"] == r["example_de"], f"{lemma} de 应为富字段德语例句"


def test_a1_example_zh_and_ipa_from_seed():
    """A1 的 example_zh / ipa 来自 A1_WORKBENCH_SEED（S3）：抽样非空且与种子逐字一致。"""
    from delector.data.a1_workbench_dict import A1_WORKBENCH_SEED

    res = get_vocab_by_cefr(cefr="A1", scope="all")
    assert res["words"], "A1 全量不应为空"
    for w in res["words"][:10]:
        assert w["ipa"], f"{w['id']} A1 ipa 为空（seed 音标未接通）"
        assert w["example_zh"], f"{w['id']} A1 example_zh 为空（seed 例句中文未接通）"

    first_seed = A1_WORKBENCH_SEED[0]
    first = res["words"][0]
    assert first["id"] == first_seed["id"]
    assert first["ipa"] == first_seed["ipa"]
    assert first["example_zh"] == first_seed["ex"][0]["zh"]


def test_unregistered_lemma_yields_empty_rich_fields():
    """主干 LEXICON 中未登记富字段的 lemma：de/ipa/example_zh 显式空串（不抛错、不编造）。"""
    from delector.core.lexicon import LEXICON, rich_of

    lemma = next((k for k, v in LEXICON.items() if v[0].upper() == "A2" and rich_of(k) is None), None)
    assert lemma is not None, "样本前提失效：A2 全部 lemma 均有富字段"
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    w = {x["id"]: x for x in res["words"]}[f"a2-{lemma}"]
    assert w["ipa"] == "" and w["example_zh"] == "" and w["de"] == "", (
        f"{lemma} 富字段缺失时应显式空串（禁止编造 / 静默降级，ADR-0013 §5-3）"
    )


def test_missing_rich_does_not_raise_and_yields_empty(monkeypatch):
    """``rich_of`` 恒返回 None → 各条目 de/ipa/example_zh 显式空串且不抛错。

    打桩 ``delector.core.lexicon.rich_of``：惰性 import 于调用期取值，故打桩即时生效；
    A2 分支缓存由 autouse fixture 在用例前清空。
    """
    from delector.core import lexicon

    monkeypatch.setattr(lexicon, "rich_of", lambda lemma: None)
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    assert res["words"], "A2 视图不应为空"
    for w in res["words"]:
        assert w["ipa"] == "", f"{w['id']} ipa 应为空串（rich 未登记）"
        assert w["example_zh"] == "", f"{w['id']} example_zh 应为空串（rich 未登记）"
        assert w["de"] == "", f"{w['id']} de 应为空串（rich 未登记）"
