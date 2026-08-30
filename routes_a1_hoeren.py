"""
DeLector - Goethe A1 Hörverstehen (Listening) API Routes
"""

from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json

from a1_hoeren_dict import (
    get_hoeren_set_list,
    get_hoeren_set_by_id,
    grade_hoeren_answers
)
from database import (
    record_a1_hoeren_trial,
    get_a1_hoeren_history
)

hoeren_router = APIRouter(prefix="/api/a1/hoeren", tags=["a1_hoeren"])


class HoerenGradeRequest(BaseModel):
    set_id: int
    duration_seconds: int = 0
    answers: Dict[str, str] = {}


@hoeren_router.get("/sets")
def api_get_hoeren_sets():
    """获取 5 套 A1 听力试卷概览列表"""
    return {"sets": get_hoeren_set_list()}


@hoeren_router.get("/set/{set_id}")
def api_get_hoeren_set(set_id: int):
    """获取指定套题内容（做题模式脱敏，不包含答案与原文）"""
    data = get_hoeren_set_by_id(set_id, sanitize=True)
    if not data:
        raise HTTPException(status_code=404, detail="Set not found")
    return data


@hoeren_router.post("/grade")
def api_grade_hoeren(req: HoerenGradeRequest):
    """提交答案并进行 25 分制评分与结果记录"""
    graded = grade_hoeren_answers(req.set_id, req.answers)
    if "error" in graded:
        raise HTTPException(status_code=404, detail=graded["error"])

    try:
        record_a1_hoeren_trial(
            set_id=req.set_id,
            score_raw=graded["score_raw"],
            score_official=graded["score_official"],
            total_questions=graded["total_questions"],
            duration_seconds=req.duration_seconds,
            answers_json=json.dumps(req.answers, ensure_ascii=False),
            wrong_questions_json=json.dumps(graded["wrong_questions"], ensure_ascii=False)
        )
    except Exception as e:
        print(f"[Warn] Failed to record a1 hoeren trial: {e}")

    return graded


@hoeren_router.get("/history")
def api_get_hoeren_history(limit: int = 50):
    """获取 A1 听力模考历史记录"""
    return {"history": get_a1_hoeren_history(limit=limit)}
