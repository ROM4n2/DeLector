# -*- coding: utf-8 -*-
"""
DeLector - Goethe-Zertifikat A2 Workshop Router
Endpoints for A2 Wortliste (默认官方精选 736 vocab；sources=official).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from delector.core.database import get_vocab_by_cefr

router = APIRouter(prefix="/api/a2", tags=["Goethe A2"])


@router.get("/vocab")
def get_a2_vocab(
    topic: Optional[str] = None,
    q: Optional[str] = None,
    sources: Optional[str] = "official",
) -> List[Dict[str, Any]]:
    """获取 A2 考纲词汇列表（规范化定冠词与词性）。

    默认官方精选 736 词条（``sources=official``）。本端点语义即「A2 考纲词表」，
    故不传参 / 显式传 ``sources=`` 空串、None 或任意非官方取值时均取官方视图；
    ``sources`` 参数保留仅为向后兼容既有 query 形状。
    """
    sources_set = {s.strip() for s in sources.split(",") if s.strip()} if sources else None
    if not sources_set or "official" not in sources_set:
        sources_set = {"official"}
    raw_words = get_vocab_by_cefr(cefr="A2", scope="all", sources=sources_set)["words"]
    res: List[Dict[str, Any]] = []
    for w in raw_words:
        lemma = w.get("id", "").replace("a2-", "")
        item = {
            "id": w.get("id"),
            "word": w.get("hw"),
            "hw": w.get("hw"),
            "lemma": lemma,
            "pos": w.get("pos"),
            "gender": w.get("gender"),
            "plural": w.get("plural", ""),
            "definition_zh": w.get("zh", ""),
            "zh": w.get("zh", ""),
            "example_de": w.get("de", ""),
            "de": w.get("de", ""),
            "example_zh": "",
            "topic": "general",
            "core": True,
            "cefr": "A2",
        }
        res.append(item)

    if q:
        query = q.strip().lower()
        res = [
            w
            for w in res
            if query in w.get("word", "").lower()
            or query in w.get("lemma", "").lower()
            or query in w.get("definition_zh", "").lower()
        ]

    return res
