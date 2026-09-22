"""
DeLector - Goethe-Zertifikat A1 Workshop Router
Endpoints for A1 Wortliste (702 vocab), Sprechen (Teil 2 & Teil 3), and Schreiben (Teil 1 Formular & Teil 2 E-Mail).
"""

# mypy: disable-error-code="misc,untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 pydantic/fastapi 被降级为 Any 才误报
# （BaseModel 子类化 / @router 装饰器）；正常 import 跟随下两错误码在本模块从不触发。

import os
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from delector.core.database import export_a1_anki_deck
from delector.data import a1_dict, a1_writing_dict
from delector.services.writing import analyze_a1_email, check_a1_formular_answer

router = APIRouter(prefix="/api/a1", tags=["Goethe A1"])


# --- Goethe-Zertifikat A1 Wortliste & Sprechen Lab ---
@router.get("/topics")
def get_a1_topics() -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for entry in a1_dict.GOETHE_A1_VOCAB.values():
        t = entry.get("topic", "phrases")
        counts[t] = counts.get(t, 0) + 1

    return [
        {
            "key": key,
            "label": label,
            "keywords": kw,
            "count": counts.get(key, 0),
        }
        for key, label, kw in a1_dict.A1_TOPICS
    ]


@router.get("/vocab")
def get_a1_vocab(topic: Optional[str] = None, q: Optional[str] = None) -> List[Dict[str, Any]]:
    from delector.core.lexicon import lemma_key, rich_of

    res = list(a1_dict.GOETHE_A1_VOCAB.values())
    if topic:
        res = [w for w in res if w.get("topic") == topic]
    if q:
        query = q.strip().lower()
        res = [
            w
            for w in res
            if query in w.get("word", "").lower()
            or query in w.get("lemma", "").lower()
            or query in w.get("definition_zh", "").lower()
        ]
    # ADR-0015：考纲卡富字段补 IPA（人工 workbench-a1 > rich；缺则空串，不编造）。
    out: List[Dict[str, Any]] = []
    for w in res:
        item = dict(w)
        rich = rich_of(lemma_key(str(item.get("lemma") or item.get("word") or "")))
        item["ipa"] = (rich or {}).get("ipa") or ""
        out.append(item)
    return out


@router.get("/sprechen/teil2")
def get_a1_sprechen_teil2(topic: Optional[str] = None) -> Any:
    cards = a1_dict.A1_SPRECHEN_TEIL2
    if topic:
        cards = [c for c in cards if c.get("topic_id") == topic]
    return cards


@router.get("/sprechen/teil3")
def get_a1_sprechen_teil3() -> Any:
    return a1_dict.A1_SPRECHEN_TEIL3


@router.get("/export/anki")
def export_a1_anki() -> FileResponse:
    from delector.core.utils import _attachment_headers

    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "Goethe_A1_Wortliste.apkg")
    export_a1_anki_deck(path)
    return FileResponse(
        path,
        filename="Goethe_A1_Wortliste.apkg",
        media_type="application/octet-stream",
        headers=_attachment_headers("Goethe_A1_Wortliste.apkg"),
    )


# --- Goethe-Zertifikat A1 Schreiben Workshop Endpoints ---
class A1FormularCheckReq(BaseModel):
    exercise_id: str
    answers: Dict[str, str]


class A1EmailDiagnoseReq(BaseModel):
    text: str
    leitpunkte: Optional[List[str]] = None


@router.get("/schreiben/teil1")
def get_a1_schreiben_teil1() -> Any:
    return a1_writing_dict.A1_SCHREIBEN_TEIL1


@router.post("/schreiben/teil1/check")
def check_a1_schreiben_teil1(req: A1FormularCheckReq) -> Dict[str, Any]:
    ex_map = {ex["id"]: ex for ex in a1_writing_dict.A1_SCHREIBEN_TEIL1}
    ex = ex_map.get(req.exercise_id)
    if not ex:
        raise HTTPException(404, "填表题目未找到")

    results = {}
    score = 0
    total = len(ex["fields"])

    for fld in ex["fields"]:
        key = fld["key"]
        user_val = req.answers.get(key, "")
        chk = check_a1_formular_answer(user_val, fld["answer"], fld.get("aliases", []))
        chk["tip"] = fld.get("tip", "")
        chk["label"] = fld.get("label", "")
        if chk["correct"]:
            score += 1
        results[key] = chk

    return {
        "exercise_id": req.exercise_id,
        "score": score,
        "total": total,
        "all_correct": score == total,
        "results": results,
    }


@router.get("/schreiben/teil2")
def get_a1_schreiben_teil2() -> Any:
    return a1_writing_dict.A1_SCHREIBEN_TEIL2


@router.post("/schreiben/teil2/diagnose")
def diagnose_a1_schreiben_teil2(req: A1EmailDiagnoseReq) -> Any:
    return analyze_a1_email(req.text[:2000], req.leitpunkte)
