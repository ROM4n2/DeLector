"""
DeLector - Goethe A1 Lesen (Reading) API Routes
"""

# mypy: disable-error-code="misc,untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 pydantic/fastapi 被降级为 Any 才误报
# （BaseModel 子类化 / @router 装饰器）；正常 import 跟随下两错误码在本模块从不触发。

import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from delector.core.database import get_a1_lesen_history, record_a1_lesen_trial
from delector.data.a1_lesen_dict import get_lesen_set_by_id, get_lesen_set_list, grade_lesen_answers

lesen_router = APIRouter(prefix="/api/a1/lesen", tags=["a1_lesen"])


class LesenGradeRequest(BaseModel):
    set_id: int
    duration_seconds: int = 0
    answers: Dict[str, str] = {}


@lesen_router.get("/sets")
def api_get_lesen_sets() -> Dict[str, Any]:
    """获取 6 套 A1 阅读试卷概览列表"""
    return {"sets": get_lesen_set_list()}


@lesen_router.get("/set/{set_id}")
def api_get_lesen_set(set_id: int) -> Any:
    """获取指定套题内容（脱敏）"""
    data = get_lesen_set_by_id(set_id, sanitize=True)
    if not data:
        raise HTTPException(status_code=404, detail="Set not found")
    return data


@lesen_router.post("/grade")
def api_grade_lesen(req: LesenGradeRequest) -> Any:
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
            wrong_questions_json=json.dumps(graded["wrong_questions"], ensure_ascii=False),
        )
    except Exception as e:
        print(f"[Warn] Failed to record a1 lesen trial: {e}")

    return graded


@lesen_router.get("/history")
def api_get_lesen_history(limit: int = 50) -> Dict[str, Any]:
    """获取 A1 阅读模考历史记录"""
    return {"history": get_a1_lesen_history(limit=limit)}
