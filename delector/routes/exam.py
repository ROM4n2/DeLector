"""Exam catalog 路由（ADR-0005 Task 3）—— 等级→模块 导航发现。

纯只读端点：无写操作、无 _require_localhost 闸。旧 /api/a1/* 取题端点
**不迁移不改动**，本 router 只挂目录发现。
"""

# mypy: disable-error-code="untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 fastapi @router 装饰器被降级为 untyped 才误报；
# 正常 import 跟随下本错误码从不触发。

from typing import Any

from fastapi import APIRouter

from delector.services.exam_catalog import get_catalog

router = APIRouter(prefix="/api/exams", tags=["exam"])


@router.get("/catalog")
def get_exam_catalog() -> Any:
    return get_catalog()
