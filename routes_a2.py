# -*- coding: utf-8 -*-
"""
DeLector - Goethe-Zertifikat A2 Workshop Router
Endpoints for A2 Wortliste (974 vocab).
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter
from database import get_vocab_by_cefr

router = APIRouter(prefix="/api/a2", tags=["Goethe A2"])


@router.get("/vocab")
def get_a2_vocab(topic: Optional[str] = None, q: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取 A2 考纲词汇列表（974 词条，规范化定冠词与词性）。"""
    raw_words = get_vocab_by_cefr(cefr="A2", scope="all")["words"]
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
            w for w in res
            if query in w.get("word", "").lower()
            or query in w.get("lemma", "").lower()
            or query in w.get("definition_zh", "").lower()
        ]

    return res
