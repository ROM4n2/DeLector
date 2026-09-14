"""
DeLector - Sentence-level Difficulty Scoring Engine (v3.6.0)
句子难度评分纯函数：score_sentence / estimate_level / rank_sentences。

100% 纯标准库 + Pydantic v2，零外部依赖。
输入为 syntax_tree.analyze_syntax_tree 的单句输出（sentences[i]）：
  特征键（侦察确认）：
    - clause_tree: {type, features{is_passive, is_subjunctive, ...}, token_ids,
                    topology{sentence_type, bracket_structure}, children[]}
    - topology: {sentence_type: "V2"|"V1"|"VL"|"Infinitiv", bracket_structure, ...}
    - path: "spacy" | "pure"（红线 1 降级标注，缺省 "spacy"）
  纯 Python 降级路径（_analyze_syntax_tree_pure_python）的 clause_tree 无 features/topology
  —— 提取特征时全部容错；rank_sentences 负责按分支/特征键自行注入 path（见 _detect_path）。

权重对齐 Grammatik-Radar 维度口径（clause 深度/复合度/被动/虚拟式/VL 句框/关系从句/长度）。
"""

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from delector.nlp_engine.syntax_tree import analyze_syntax_tree, split_sentences_pure_python


class SentenceScore(BaseModel):
    """句子难度评分结果（score 0–100 + CEFR 级别 + 维度明细 + 分析来源路径 + 原文）。"""

    score: float
    level: str
    dimensions: Dict[str, Any]
    path: Literal["spacy", "pure"]
    sentence: str = ""


def _fallback_score(path: Literal["spacy", "pure"] = "spacy") -> SentenceScore:
    """空/非法 analysis 的最低分兜底：0 分 + A1 + 空维度，不抛异常。"""
    return SentenceScore(score=0.0, level=estimate_level(0.0), dimensions={}, path=path)


def _normalize_path(path: Optional[str], analysis: Any) -> Literal["spacy", "pure"]:
    """来源路径规范化（红线 1）：显式 path 参数优先 > analysis["path"] > 默认 "spacy"。"""
    if path == "spacy":
        return "spacy"
    if path == "pure":
        return "pure"
    raw: Any = analysis.get("path", "spacy") if isinstance(analysis, dict) else "spacy"
    if raw == "pure":
        return "pure"
    return "spacy"


def _walk_clause(node: Dict[str, Any], depth: int, agg: Dict[str, Any]) -> None:
    """递归遍历 clause_tree 节点，聚合评分特征（深度/节点数/被动/虚拟式/VL/关系从句）。"""
    agg["node_count"] += 1
    if depth > int(agg["max_depth"]):
        agg["max_depth"] = depth
    features = node.get("features")
    if isinstance(features, dict):
        # 子句节点命中特征 → 整句聚合命中（任一节点命中即算）
        agg["is_passive"] = bool(agg["is_passive"]) or features.get("is_passive") is True
        agg["is_subjunctive"] = bool(agg["is_subjunctive"]) or features.get("is_subjunctive") is True
    if node.get("type") == "relativsatz":
        agg["has_relativ"] = True
    topology = node.get("topology")
    if isinstance(topology, dict):
        # VL 句框：sentence_type=="VL" 或 bracket_structure 含 "Verbletzt"
        agg["verb_last"] = bool(agg["verb_last"]) or topology.get("sentence_type") == "VL"
        bracket = topology.get("bracket_structure")
        agg["verb_last"] = bool(agg["verb_last"]) or (isinstance(bracket, str) and "Verbletzt" in bracket)
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _walk_clause(child, depth + 1, agg)


def _sentence_length(root: Dict[str, Any]) -> int:
    """句长（词数）：根节点 token_ids 长度优先，退化到 text 分词。"""
    token_ids = root.get("token_ids")
    if isinstance(token_ids, list) and token_ids:
        return len(token_ids)
    text = root.get("text")
    if isinstance(text, str) and text.strip():
        return len(text.split())
    return 0


# ── pure 降级路径文本启发式（红线 1：无 features/从句树时的粗估） ──────────
_SUBORD_CONJUNCTIONS = (
    "weil", "dass", "obwohl", "wenn", "nachdem", "bevor", "während", "wobei",
    "indem", "damit", "falls", "sobald", "solange", "sofern", "ob", "wo",
    "worüber", "wovon", "womit", "wodurch",
)
_RELATIVE_PRONOUNS = ("der", "die", "das", "den", "dem", "dessen", "deren", "welcher", "welche", "welches")
_PASSIVE_WORD_HINTS = ("wird", "werden", "wurde", "wurden", "worden")
_SUBJUNCTIVE_WORD_HINTS = (
    "würde", "wäre", "hätte", "könnte", "sollte", "müsste", "dürfte", "sei", "wären", "hätten", "könnten",
)
_VL_SUBORD_OPENERS = ("dass", "ob", "weil", "wenn", "obwohl", "nachdem", "bevor", "während")


def _pure_text_hints(text: str) -> Dict[str, int]:
    """从纯文本提取难度线索（无依存句法时的粗估，供 pure 路径评分）。

    返回命中计数：clause_hint（逗号分隔从句 + 从属连词）、relativ（逗号后关系代词）、
    passive/subjunctive/verb_last（词形/结构线索 0/1）。这是**启发式粗估**——只用于
    给 pure 路径 0–7 分的无区分度区间提供排序依据，不改变 path="pure" 的"评分仅参考"语义。
    """
    t = (text or "").lower()
    clause_hint = t.count(",") + t.count("，") + t.count("；")
    clause_hint += sum(1 for c in _SUBORD_CONJUNCTIONS if re.search(rf"\b{c}\b", t))
    relativ = sum(1 for p in _RELATIVE_PRONOUNS if re.search(rf",\s*{p}\b", t))
    passive = 1 if re.search(r"\b(" + "|".join(_PASSIVE_WORD_HINTS) + r")\b", t) else 0
    subjunctive = 1 if re.search(r"\b(" + "|".join(_SUBJUNCTIVE_WORD_HINTS) + r")\b", t) else 0
    verb_last = 1 if re.search(r",\s*(" + "|".join(_VL_SUBORD_OPENERS) + r")\b", t) else 0
    return {
        "clause_hint": clause_hint,
        "relativ": relativ,
        "passive": passive,
        "subjunctive": subjunctive,
        "verb_last": verb_last,
    }


def score_sentence(analysis: Any, path: Optional[str] = None) -> SentenceScore:
    """从单句 analysis dict 提取特征，加权归一为 0–100 难度分 + CEFR 级别 + 维度明细。

    analysis 为 analyze_syntax_tree 输出 sentences[i] 的形状（含 clause_tree/topology/path）。
    path 为显式来源路径（"spacy"/"pure"），优先级高于 analysis["path"]（红线 1 降级标注）。
    空/非法输入（None、缺 clause_tree 等）返回最低分兜底，不抛异常。
    """
    if not isinstance(analysis, dict):
        return _fallback_score(_normalize_path(path, analysis))
    tree = analysis.get("clause_tree")
    # 非法判定：非 dict / 空 dict / 缺 type 键（真实输出的 clause_tree 必有 type）
    if not isinstance(tree, dict) or not tree or "type" not in tree:
        return _fallback_score(_normalize_path(path, analysis))

    agg: Dict[str, Any] = {
        "node_count": 0,
        "max_depth": 0,
        "is_passive": False,
        "is_subjunctive": False,
        "verb_last": False,
        "has_relativ": False,
    }
    _walk_clause(tree, 1, agg)
    sent_topology = analysis.get("topology")
    if isinstance(sent_topology, dict) and sent_topology.get("sentence_type") == "VL":
        agg["verb_last"] = True

    depth: int = int(agg["max_depth"])
    count: int = int(agg["node_count"])
    length: int = _sentence_length(tree)

    # 红线 1：来源路径（显式 path 参数 > analysis["path"]，非法值回落 "spacy"）
    path_lit: Literal["spacy", "pure"] = _normalize_path(path, analysis)

    # pure 降级路径文本启发式（v5.7.3 真机反馈：纯 Python 降级句普遍 0–7 分，
    # 难度榜失去区分度）。无 features/从句树信息时用纯文本线索粗估 count 与命中
    # 维度，给排序提供依据；path="pure" 的"评分仅参考"语义不变。
    if path_lit == "pure":
        hints = _pure_text_hints(analysis.get("text") or "")
        count = max(count, hints["clause_hint"] + 1)
        agg["is_passive"] = bool(agg["is_passive"]) or bool(hints["passive"])
        agg["is_subjunctive"] = bool(agg["is_subjunctive"]) or bool(hints["subjunctive"])
        agg["verb_last"] = bool(agg["verb_last"]) or bool(hints["verb_last"])
        agg["has_relativ"] = bool(agg["has_relativ"]) or bool(hints["relativ"])

    # 各维度子分（0–1）：深度/复合度/长度递增封顶，被动/虚拟式/VL/关系从句为命中加分
    depth_score: float = min(1.0, (depth - 1) * 0.3)
    count_score: float = min(1.0, (count - 1) * 0.25)
    length_score: float = min(1.0, max(0.0, (length - 5) / 25))
    passive_score: float = 0.3 if bool(agg["is_passive"]) else 0.0
    subjunctive_score: float = 0.2 if bool(agg["is_subjunctive"]) else 0.0
    verb_last_score: float = 0.3 if bool(agg["verb_last"]) else 0.0
    relative_score: float = 0.2 if bool(agg["has_relativ"]) else 0.0

    # 加权归一 → 0–100（权重和 = 1）
    total = (
        0.25 * depth_score
        + 0.20 * count_score
        + 0.15 * passive_score
        + 0.10 * subjunctive_score
        + 0.10 * verb_last_score
        + 0.05 * relative_score
        + 0.15 * length_score
    )
    score = round(total * 100.0, 1)

    dimensions: Dict[str, Any] = {
        "clause_depth": {"value": depth, "score": round(depth_score, 3)},
        "clause_count": {"value": count, "score": round(count_score, 3)},
        "passive": {"value": bool(agg["is_passive"]), "score": passive_score},
        "subjunctive": {"value": bool(agg["is_subjunctive"]), "score": subjunctive_score},
        "verb_last": {"value": bool(agg["verb_last"]), "score": verb_last_score},
        "relative_clause": {"value": bool(agg["has_relativ"]), "score": relative_score},
        "length": {"value": length, "score": round(length_score, 3)},
    }

    return SentenceScore(score=score, level=estimate_level(score), dimensions=dimensions, path=path_lit)


def _detect_path(analysis: Any) -> Literal["spacy", "pure"]:
    """探测单句 analysis 的来源路径（红线 1：analyze_syntax_tree 输出不含 path 键）。

    优先显式 path 键；否则按 clause_tree 形状推断（Task 2 黄卡修复）：
      - 缺失/非 dict：无特征可判，回落 "pure"；
      - 空 dict {}：只可能来自 spaCy 分支的无 token 句（build_clause_tree 返回 {}），
        pure 分支切句恒非空必带完整 clause_tree —— 空 dict 不误标 pure，判 "spacy"；
      - 非空 dict：spaCy 分支的 clause_tree 必有 features dict
        （_classify_single_clause 恒构造）→ 命中判 "spacy"，否则为 pure 分支形状判 "pure"。
    """
    if isinstance(analysis, dict):
        raw = analysis.get("path")
        if raw == "pure":
            return "pure"
        if raw == "spacy":
            return "spacy"
        tree = analysis.get("clause_tree")
        if not isinstance(tree, dict):
            return "pure"
        # 空 dict（spaCy 无 token 句）或带 features（spaCy 恒构造）→ spacy；其余为 pure 形状
        if not tree or isinstance(tree.get("features"), dict):
            return "spacy"
    return "pure"


def rank_sentences(text: str) -> List[SentenceScore]:
    """整段文本 → 逐句切分/双路径分析/评分 → 按难度降序返回 SentenceScore 列表。

    红线 10：切句唯一实现为 split_sentences_pure_python（禁止自造切句）。
    红线 1：analyze_syntax_tree 输出无 path 键 → 此处自行探测标注 spacy/pure。
    空文本 → []；单句分析异常 → 跳过该句，不炸整批。
    """
    if not text or not text.strip():
        return []
    scored: List[SentenceScore] = []
    for sent in split_sentences_pure_python(text):
        try:
            analysis = analyze_syntax_tree(sent)
        except Exception:
            continue
        batch = analysis.get("sentences")
        if not isinstance(batch, list) or not batch:
            continue
        if len(batch) > 1:
            # Task 2 黄卡修复：spaCy 的 doc.sents 切句粒度可能与纯 Python 切句
            # （split_sentences_pure_python）不一致（缩写/省略号边界等），此时
            # 以纯 Python 切句粒度为准只取 batch[0]，绝不静默丢句 —— sentence
            # 字段仍回填完整原句 sent（调用方拿到的始终是切句粒度下的一句）。
            pass
        base = score_sentence(batch[0], path=_detect_path(batch[0]))
        # 不用 model_copy（pydantic v2 专属，Android 打包 pydantic<2.0.0 无此方法会
        # AttributeError → 列表端点 500）：直接构造，v1/v2 通用（对齐 routes/main.py
        # 的 hasattr 兼容纪律）。sentence 回填纯 Python 切句粒度下的完整原句。
        scored.append(
            SentenceScore(
                score=base.score,
                level=base.level,
                dimensions=base.dimensions,
                path=base.path,
                sentence=sent,
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def estimate_level(score: float) -> str:
    """分数 → CEFR 级别带（A1/A2/B1/B2 粗分，供门控）。阈值：<25 A1 / <45 A2 / <70 B1 / ≥70 B2。"""
    if score < 25.0:
        return "A1"
    if score < 45.0:
        return "A2"
    if score < 70.0:
        return "B1"
    return "B2"
