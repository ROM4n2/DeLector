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

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from delector.services import syntax_score as sc
from delector.services.syntax_score import SentenceScore, estimate_level, rank_sentences, score_sentence

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
    # bad 为任意非法输入形态（None/空 dict/形状异常 dict），score_sentence 须容错返回最低分
    bads: List[Any] = [None, {}, {"clause_tree": None}, {"clause_tree": {}}, {"clause_tree": {"children": "oops"}}]
    for bad in bads:
        result = score_sentence(bad)
        assert result.score == 0.0
        assert result.level == "A1"
        assert result.dimensions == {}
        assert result.path == "spacy"


# ──────────────────────────────────────────────────────────────────────────────
# rank_sentences 全文切句评分（计划 Task 2）
# ──────────────────────────────────────────────────────────────────────────────


def _pure_analysis(sent: str) -> Dict[str, Any]:
    """pure 降级路径形状的 analysis（clause_tree 无 features/topology/text 键）。"""
    words = sent.split()
    return {
        "sentence_id": 0,
        "text": sent,
        "clause_tree": {
            "id": "root",
            "type": "hauptsatz",
            "label": "Hauptsatz (主句)",
            "label_zh": "主句核心",
            "connector": "",
            "finite_verb": "",
            "token_ids": list(range(len(words))),
            "formula": "[Vorfeld] + [Linke Klammer] + [Mittelfeld] + [Rechte Klammer] + [Nachfeld]",
            "children": [],
        },
        "topology": {
            "vorfeld": [],
            "linke_klammer": [],
            "mittelfeld": [{"text": w, "id": i} for i, w in enumerate(words)],
            "rechte_klammer": [],
            "nachfeld": [],
            "field_texts": {
                "vorfeld": "",
                "linke_klammer": "",
                "mittelfeld": sent,
                "rechte_klammer": "",
                "nachfeld": "",
            },
            "sentence_type": "V2",
            "bracket_structure": "Einfacher Satz",
            "clause_type": "hauptsatz",
        },
    }


def test_rank_sentences_descending_with_hardest_first(monkeypatch):
    # 三段文本：难句（深嵌套 + 被动 + VL + 20 词）> 中句（单层从句）> 易句（简单句 0 分）
    hard = "Weil der Mann, der gestern ankam, das Buch lesen wollte, blieb er zu Hause."
    mid = "Obwohl es regnete, ging sie spazieren."
    easy = "Das Wetter ist heute schoen."
    text = f"{easy} {hard} {mid}"
    analyses = {
        hard: _analysis(
            sentence_type="VL",
            features={"is_passive": True, "is_subjunctive": False},
            children=[_clause(type_="konjunktionalsatz", children=[_clause(type_="relativsatz")])],
            n_tokens=20,
        ),
        mid: _analysis(children=[_clause(type_="konjunktionalsatz")], n_tokens=10),
        easy: _analysis(n_tokens=5),
    }
    monkeypatch.setattr(sc, "split_sentences_pure_python", lambda t: [easy, hard, mid])
    monkeypatch.setattr(sc, "analyze_syntax_tree", lambda s: {"sentences": [analyses[s]]})

    result = rank_sentences(text)
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)  # 降序
    assert scores[0] > scores[-1]
    assert result[0].sentence == hard  # 首条为最难句
    for r in result:
        assert isinstance(r, SentenceScore)
        assert r.sentence  # 每项含原文
        assert 0.0 <= r.score <= 100.0
        assert isinstance(r.level, str)
        assert r.path in ("spacy", "pure")


def test_rank_sentences_uses_split_sentences_pure_python(monkeypatch):
    # 红线 10：切句唯一入口是 split_sentences_pure_python（monkeypatch 记录调用，禁止自造切句）
    sents = ["Erste.", "Zweite."]
    calls: List[str] = []

    def _fake_split(t: str) -> List[str]:
        # 记录切句收到的原文，并返回预设 sents（避免 list.append 无返回值的技巧）
        calls.append(t)
        return sents

    monkeypatch.setattr(sc, "split_sentences_pure_python", _fake_split)
    monkeypatch.setattr(sc, "analyze_syntax_tree", lambda s: {"sentences": [_analysis(n_tokens=5)]})

    result = rank_sentences("Erste. Zweite.")
    assert calls == ["Erste. Zweite."]  # 切句函数收到原文且仅此一次调用
    assert [r.sentence for r in result] == sents


def test_rank_sentences_marks_path_spacy_and_pure(monkeypatch):
    # 红线 1：analyze_syntax_tree 输出无 path 键 → rank_sentences 必须自行探测标注 spacy/pure
    spacy_sent = "Der Mann liest das Buch."
    pure_sent = "Das Wetter ist schoen."
    spacy_analysis = _analysis(n_tokens=6)
    del spacy_analysis["path"]  # 模拟真实输出：无 path 键，需按 clause_tree 特征键探测
    pure_analysis = _pure_analysis(pure_sent)
    monkeypatch.setattr(sc, "split_sentences_pure_python", lambda t: [spacy_sent, pure_sent])
    monkeypatch.setattr(
        sc, "analyze_syntax_tree", lambda s: {"sentences": [spacy_analysis if s == spacy_sent else pure_analysis]}
    )

    result = rank_sentences(f"{spacy_sent} {pure_sent}")
    by_sentence = {r.sentence: r.path for r in result}
    assert by_sentence[spacy_sent] == "spacy"  # spaCy 路径不得误标 pure
    assert by_sentence[pure_sent] == "pure"  # 纯 Python 降级不得缺省误标 spacy


def test_rank_sentences_empty_text_returns_empty():
    assert rank_sentences("") == []
    assert rank_sentences("   \n\t ") == []


def test_rank_sentences_skips_failing_sentence(monkeypatch):
    # 异常句容错：单句分析失败 → 跳过该句，不炸整批
    good1, bad, good2 = "Gut.", "Kaputt.", "Auch gut."

    def fake_analyze(sent: str) -> Dict[str, Any]:
        if sent == bad:
            raise RuntimeError("syntax engine boom")
        return {"sentences": [_analysis(n_tokens=5)]}

    monkeypatch.setattr(sc, "split_sentences_pure_python", lambda t: [good1, bad, good2])
    monkeypatch.setattr(sc, "analyze_syntax_tree", fake_analyze)

    result = rank_sentences(f"{good1} {bad} {good2}")
    assert [r.sentence for r in result] == [good1, good2]


# ──────────────────────────────────────────────────────────────────────────────
# Task 2 验收黄卡修复（CRV 黄牌折入 Task 3 Step 0）
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_path_empty_clause_tree_is_not_pure():
    # 黄卡：spaCy 分支对无 token 句返回 clause_tree={}（build_clause_tree 空 dict），
    # 不得误标 pure —— 空 dict 只可能来自 spaCy 分支（pure 分支切句恒非空，必带
    # 完整 clause_tree）。缺失/非 dict 无特征可判 → pure；pure 形状（非空无 features）→ pure。
    assert sc._detect_path({"clause_tree": {}}) == "spacy"
    assert sc._detect_path({}) == "pure"
    assert sc._detect_path({"clause_tree": None}) == "pure"
    assert sc._detect_path(_pure_analysis("Das Wetter ist schoen.")) == "pure"
    # 非空 + features → spaCy（对照）
    spacy_analysis = _analysis(n_tokens=6)
    del spacy_analysis["path"]
    assert sc._detect_path(spacy_analysis) == "spacy"


def test_rank_sentences_spacy_split_differ_keeps_full_sentence(monkeypatch):
    # 黄卡：spaCy doc.sents 粒度与 split_sentences_pure_python 不一致时（batch>1），
    # 以纯 Python 切句粒度为准只取 batch[0]，sentence 字段仍为完整原句 —— 不静默丢句。
    sent = "Er kam, weil es regnete, nicht."
    monkeypatch.setattr(sc, "split_sentences_pure_python", lambda t: [sent])
    monkeypatch.setattr(
        sc,
        "analyze_syntax_tree",
        lambda s: {"sentences": [_analysis(n_tokens=8), _analysis(n_tokens=3)]},
    )
    result = rank_sentences(sent)
    assert len(result) == 1  # batch 多句不重复/不丢句，仍以纯 Python 切句粒度为准
    assert result[0].sentence == sent  # 完整原句回填


# ──────────────────────────────────────────────────────────────────────────────
# 跨端打包兼容守卫（DELECTOR-DEV-RULES §2.4 跨端打包同步守卫）
# ──────────────────────────────────────────────────────────────────────────────


def test_syntax_score_no_pydantic_v2_only_api():
    """Android Chaquopy 打包 `pydantic<2.0.0`（1.x），而 pydantic v2 专属 API
    （model_copy/model_dump/model_validate/model_construct）在 1.x 不存在。

    回归：v5.7.0/v5.7.1 真机「长难句清单加载失败 Internal Server Error」——rank_sentences
    第 205 行曾用 `.model_copy(update=...)`，Android pydantic 1.x 下 AttributeError →
    /api/syntax/hard-sentences 全源 500（桌面 pydantic 2.x 无法复现）。守卫钉死：
    syntax_score.py 不得出现任何 pydantic v2 专属 API token（此模块无需 dict/validate，
    需要时用 v1/v2 双兼容写法，参照 routes/main.py 的 `hasattr` 守卫）。
    """
    src_path = Path(sc.__file__).resolve()
    src = src_path.read_text(encoding="utf-8")
    # 只匹配调用形式 `.model_x(`（英文括号）；注释里写成"不用 model_copy（"（中文括号）
    # 是说明文字，不误报。v1/v2 双兼容的 `hasattr` 守卫写法不在禁止列。
    pattern = re.compile(r"\.(model_copy|model_dump|model_validate|model_construct|model_fields)\s*\(")
    match = pattern.search(src)
    assert not match, (
        f"syntax_score.py 含 pydantic v2 专属 API 调用：{match.group(0)!r}（Android pydantic 1.x 会炸）"
    )
