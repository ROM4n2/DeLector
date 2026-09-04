"""Exam catalog 路由（ADR-0005 Task 3）—— 等级→模块 导航发现。

纯只读端点：无写操作、无 _require_localhost 闸。旧 /api/a1/* 取题端点
**不迁移不改动**，本 router 只挂目录发现。
"""
from fastapi import APIRouter

from exam_catalog import get_catalog

router = APIRouter(prefix="/api/exams", tags=["exam"])


@router.get("/catalog")
def get_exam_catalog():
    return get_catalog()
