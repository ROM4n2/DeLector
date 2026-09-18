# -*- coding: utf-8 -*-
"""
DeLector - 官方真题语料库路由 (Official Exam Reading Corpus Router)
提供涵盖 Goethe A1-B2 及 TestDaF 权威样题的目录查询与正文解析端点。
"""

# mypy: disable-error-code="untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 fastapi @router 装饰器被降级为 untyped 才误报；
# 正常 import 跟随下本错误码从不触发。

from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from delector.data import corpus_dict

router = APIRouter(prefix="/api/corpus", tags=["Corpus"])


@router.get("/list")
def list_corpus(cefr: Optional[str] = None, category: Optional[str] = None) -> Any:
    """获取官方真题篇章元数据列表（支持按 CEFR 等级与主题分类筛选）。"""
    return corpus_dict.get_corpus_list(cefr=cefr, category=category)


@router.get("/{corpus_id}")
def get_corpus(corpus_id: str) -> Any:
    """获取指定真题篇章的完整正文、考点词与阅读理解验证题目。"""
    item = corpus_dict.get_corpus_by_id(corpus_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"语料篇章未找到: {corpus_id}")
    return item
