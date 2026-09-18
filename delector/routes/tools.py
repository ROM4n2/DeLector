# -*- coding: utf-8 -*-
"""Agent 工具 HTTP 端点（ADR-0008 Phase 1 Task 7）。

`POST /api/tools/{tool_name}` 按 TOOL_REGISTRY 分发到对应 tool.run。

敏感/可写端点（ingest 拉外网、export 读库）按项目惯例限 127.0.0.1 本机 ——
Go Agent 与 Web 同机跑，localhost 可达。Phase 2 若需跨机再放宽闸。
"""

# mypy: disable-error-code="misc,untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 pydantic/fastapi 被降级为 Any 才误报
# （BaseModel 子类化 / @router 装饰器）；正常 import 跟随下两错误码在本模块从不触发。

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from delector.core.database import _require_localhost
from delector.tools import TOOL_REGISTRY

router = APIRouter(prefix="/api/tools", tags=["agent-tools"])


class ToolCall(BaseModel):
    payload: Dict[str, Any] = {}


@router.get("/")
def list_tools() -> Dict[str, Any]:
    return {"tools": sorted(TOOL_REGISTRY.keys())}


@router.post("/{tool_name}", dependencies=[Depends(_require_localhost)])
async def run_tool(tool_name: str, call: ToolCall) -> Any:
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool: {tool_name}")
    try:
        return await tool(call.payload or {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{tool_name} failed: {exc}")
