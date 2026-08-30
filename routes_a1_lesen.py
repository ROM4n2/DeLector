"""
DeLector - Goethe A1 Lesen (Reading) API Routes
"""

from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json

from a1_lesen_dict import (
    get_lesen_set_list,
    get_lesen_set_by_id,
    grade_lesen_answers
)
from database import (
    record_a1_lesen_trial,
    get_a1_lesen_history
)

lesen_router = APIRouter(prefix="/api/a1/lesen", tags=["a1_lesen"])


class LesenGradeRequest(BaseModel):
    set_id: int
    duration_seconds: int = 0
    answers: Dict[str, str] = {}


@lesen_router.get("/sets")
def api_get_lesen_sets():
    """获取 6 套 A1 阅读试卷概览列表"""
    return {"sets": get_lesen_set_list()}


@lesen_router.get("/set/{set_id}")
def api_get_lesen_set(set_id: int):
    """获取指定套题内容（脱敏）"""
    data = get_lesen_set_by_id(set_id, sanitize=True)
    if not data:
        raise HTTPException(status_code=404, detail="Set not found")
    return data


@lesen_router.post("/grade")
def api_grade_lesen(req: LesenGradeRequest):
    """提交答案并进行 25 分制评分与结果记录"""
    graded = grade_lesen_answers(req.set_id, req.answers)
    if "error" in graded:
        raise HTTPException(status_code=404, detail=graded["error"])

    try:
        record_a1_lesen_trial(
            set_id=req.set_id,
            score_raw=graded["score_raw"],
            score_official=graded["score_official"],
            total_questions=graded["total_questions"],
            duration_seconds=req.duration_seconds,
            answers_json=json.dumps(req.answers, ensure_ascii=False),
            wrong_questions_json=json.dumps(graded["wrong_questions"], ensure_ascii=False)
        )
    except Exception as e:
        print(f"[Warn] Failed to record a1 lesen trial: {e}")

    return graded


@lesen_router.get("/history")
def api_get_lesen_history(limit: int = 50):
    """获取 A1 阅读模考历史记录"""
    return {"history": get_a1_lesen_history(limit=limit)}
