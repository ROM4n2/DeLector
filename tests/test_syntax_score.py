"""
Tests for sentence-level difficulty scoring (syntax_score.py).

TDD 规格（docs/specs/2026-09-14-hard-sentences-design.md §3）：
  - 评分特征→分映射：clause 深度↑分↑ / 被动加分 / 虚拟式加分 / VL 句框加分 / 句长↑分↑
  - estimate_level 分数带划分（A1/A2/B1/B2，阈值钉死）
  - path 字段透传（spacy/pure，红线 1 降级标注）
  - 空/非法 analysis 容错（最低分 + 空维度，不抛异常）

fixture 按 syntax_tree.analyze_syntax_tree 实际输出形状手工构造（不跑 spaCy）：
  sentences[i] = {sentence_id, text, clause_tree{...features/token_ids/topology/children}, topology{sentence_type, ...}}
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from delector.services.syntax_score import SentenceScore, estimate_level, score_sentence

# ──────────────────────────────────────────────────────────────────────────────
# fixture：按侦察到的特征键构造最小 analysis dict
# ──────────────────────────────────────────────────────────────────────────────


def _clause(
    *,
    type_: str = "hauptsatz",
    features: Optional[Dict[str, Any]] = None,
    children: Optional[List[Dict[str, Any]]] = None,
    token_ids: Optional[List[int]] = None,
    sentence_type: str = "V2",
    bracket: str = "Einfacher Satz",
) -> Dict[str, Any]:
    """构造 clause_tree 节点 dict（与 analyze_syntax_tree 输出的节点键一致）。"""
    if features is None:
        features = {"is_passive": False, "is_subjunctive": False}
    if token_ids is None:
        token_ids = list(range(8))
    return {
        "id": "clause_0",
        "type": type_,
        "connector": "",
        "finite_verb": "",
        "features": features,
        "token_ids": token_ids,
        "topology": {
            "sentence_type": sentence_type,
            "bracket_structure": bracket,
            "clause_type": type_,
        },
        "children": children or [],
    }


def _analysis(
    *,
    path: str = "spacy",
    sentence_type: str = "V2",
    features: Optional[Dict[str, Any]] = None,
    children: Optional[List[Dict[str, Any]]] = None,
    n_tokens: int = 8,
) -> Dict[str, Any]:
    """构造单句 analysis dict（analyze_syntax_tree 输出 sentences[i] 的形状）。"""
    return {
        "path": path,
        "clause_tree": _clause(
            type_="hauptsatz",
            features=features,
            children=children,
            token_ids=list(range(n_tokens)),
            sentence_type=sentence_type,
        ),
        "topology": {
            "sentence_type": sentence_type,
            "bracket_structure": "Einfacher Satz",
            "clause_type": "hauptsatz",
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 评分特征 → 分映射
# ──────────────────────────────────────────────────────────────────────────────


def test_score_returns_pydantic_model_with_expected_fields():
    result = score_sentence(_analysis())
    assert isinstance(result, SentenceScore)
    assert isinstance(result, BaseModel)
    assert 0.0 <= result.score <= 100.0
    assert isinstance(result.level, str)
    assert isinstance(result.dimensions, dict)
    assert result.path == "spacy"


def test_depth_increases_score():
    d1 = score_sentence(_analysis(children=[]))
    d2 = score_sentence(_analysis(children=[_clause(type_="konjunktionalsatz")]))
    d3 = score_sentence(
        _analysis(children=[_clause(type_="konjunktionalsatz", children=[_clause(type_="relativsatz")])])
    )
    assert d1.score < d2.score < d3.score
    assert d3.dimensions["clause_depth"]["value"] == 3


def test_passive_adds_score():
    plain = score_sentence(_analysis(features={"is_passive": False, "is_subjunctive": False}))
    passive = score_sentence(_analysis(features={"is_passive": True, "is_subjunctive": False}))
    assert passive.score > plain.score
    assert passive.dimensions["passive"]["value"] is True
    assert plain.dimensions["passive"]["value"] is False


def test_subjunctive_adds_score():
    plain = score_sentence(_analysis(features={"is_passive": False, "is_subjunctive": False}))
    subj = score_sentence(_analysis(features={"is_passive": False, "is_subjunctive": True}))
    assert subj.score > plain.score
    assert subj.dimensions["subjunctive"]["value"] is True


def test_verb_last_adds_score():
    v2 = score_sentence(_analysis(sentence_type="V2"))
    vl = score_sentence(_analysis(sentence_type="VL"))
    assert vl.score > v2.score
    assert vl.dimensions["verb_last"]["value"] is True


def test_verb_last_detected_from_subclause_topology():
    # 整句 V2，但子句 topology.sentence_type == "VL" → 也应命中 verb_last
    child_vl = _clause(type_="konjunktionalsatz", sentence_type="VL")
    result = score_sentence(_analysis(children=[child_vl], sentence_type="V2"))
    assert result.dimensions["verb_last"]["value"] is True


def test_relative_clause_adds_score():
    # 控制变量：子句数量/深度相同，仅从句类型不同
    with_konj = score_sentence(_analysis(children=[_clause(type_="konjunktionalsatz")]))
    with_rel = score_sentence(_analysis(children=[_clause(type_="relativsatz")]))
    assert with_rel.score > with_konj.score
    assert with_rel.dimensions["relative_clause"]["value"] is True


def test_length_increases_score():
    short = score_sentence(_analysis(n_tokens=5))
    long = score_sentence(_analysis(n_tokens=20))
    assert short.score == 0.0  # 5 词且无其它特征 → 最低分 0
    assert long.score > short.score
    assert long.dimensions["length"]["value"] == 20


def test_subclause_passive_aggregates():
    # 子句节点命中被动 → 整句聚合为被动（递归聚合 features）
    child_passive = _clause(type_="konjunktionalsatz", features={"is_passive": True, "is_subjunctive": False})
    child_plain = _clause(type_="konjunktionalsatz", features={"is_passive": False, "is_subjunctive": False})
    agg = score_sentence(_analysis(children=[child_passive]))
    plain = score_sentence(_analysis(children=[child_plain]))
    assert agg.score > plain.score
    assert agg.dimensions["passive"]["value"] is True


def test_score_extreme_sentence_stays_in_range_and_is_high():
    # 深嵌套 + 被动 + 虚拟式 + VL + 关系从句 + 40 词
    # 计算口径：0.25*0.6 + 0.20*0.5 + 0.15*0.3 + 0.10*0.2 + 0.10*0.3 + 0.05*0.2 + 0.15*1.0 → 50.5
    deep = _clause(type_="konjunktionalsatz", sentence_type="VL", children=[_clause(type_="relativsatz")])
    result = score_sentence(
        _analysis(
            sentence_type="VL",
            features={"is_passive": True, "is_subjunctive": True},
            children=[deep],
            n_tokens=40,
        )
    )
    assert 0.0 <= result.score <= 100.0
    assert result.score > 50.0


# ──────────────────────────────────────────────────────────────────────────────
# estimate_level 分数带划分（阈值钉死）
# ──────────────────────────────────────────────────────────────────────────────


def test_estimate_level_band_boundaries():
    assert estimate_level(0.0) == "A1"
    assert estimate_level(24.9) == "A1"
    assert estimate_level(25.0) == "A2"
    assert estimate_level(44.9) == "A2"
    assert estimate_level(45.0) == "B1"
    assert estimate_level(69.9) == "B1"
    assert estimate_level(70.0) == "B2"
    assert estimate_level(100.0) == "B2"


def test_score_sentence_sets_level_from_estimate():
    result = score_sentence(_analysis(n_tokens=5))  # score 0 → A1
    assert result.level == "A1"
    assert result.level == estimate_level(result.score)


# ──────────────────────────────────────────────────────────────────────────────
# path 透传（红线 1 降级标注）
# ──────────────────────────────────────────────────────────────────────────────


def test_path_passthrough():
    assert score_sentence(_analysis(path="pure")).path == "pure"
    assert score_sentence(_analysis(path="spacy")).path == "spacy"


def test_path_defaults_to_spacy():
    analysis = _analysis()
    del analysis["path"]
    assert score_sentence(analysis).path == "spacy"


# ──────────────────────────────────────────────────────────────────────────────
# 空/非法 analysis 容错
# ──────────────────────────────────────────────────────────────────────────────


def test_empty_analysis_falls_back_to_minimum():
    for bad in (None, {}, {"clause_tree": None}, {"clause_tree": {}}, {"clause_tree": {"children": "oops"}}):
        result = score_sentence(bad)  # type: ignore[arg-type]
        assert result.score == 0.0
        assert result.level == "A1"
        assert result.dimensions == {}
        assert result.path == "spacy"
