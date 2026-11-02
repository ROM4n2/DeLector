# -*- coding: utf-8 -*-
"""伴学智能体 HTTP 路由与 SSE 流式端点 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from delector.core.database import _require_localhost
from delector.services.companion_agent import dispatch_companion_stream
from delector.services.companion_proposal import CompanionProposalService
from delector.services.companion_session import CompanionSessionService

router = APIRouter(prefix="/api/companion", tags=["companion"])
_session_svc = CompanionSessionService()
_proposal_svc = CompanionProposalService()


class CompanionChatReq(BaseModel):
    messages: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    article_id: Optional[str] = None
    # 加法式字段：缺省时行为与第一阶段完全一致。
    view: Optional[str] = None
    context_source: Optional[str] = None
    draft_text: Optional[str] = None
    scope_key: Optional[str] = None


class ProposalExecReq(BaseModel):
    proposal_id: str
    action: str
    payload: Dict[str, Any]


class SessionCreateReq(BaseModel):
    article_id: Optional[str] = None
    title: str = "新伴学会话"
    scope_key: Optional[str] = None


@router.get("/context")
def get_companion_context() -> Dict[str, Any]:
    """返回当前学习与视口上下文摘要 (生词总量与已掌握数)."""
    return {"status": "ok", "context": _session_svc.get_context_summary()}


@router.get("/sessions")
def api_list_sessions(
    article_id: Optional[str] = Query(None),
    scope_key: Optional[str] = Query(None),
    limit: int = Query(20),
) -> Dict[str, Any]:
    """查询指定文章、指定 scope 或全局的最新活跃伴学会话列表."""
    return {
        "status": "ok",
        "sessions": _session_svc.list_recent_sessions(
            article_id=article_id, scope_key=scope_key, limit=limit
        ),
    }


@router.post("/sessions")
def api_create_session(req: SessionCreateReq) -> Dict[str, Any]:
    """创建或获取关联指定文章 / scope 的伴学会话."""
    return {
        "status": "ok",
        "session": _session_svc.get_or_create_session(
            article_id=req.article_id, title=req.title, scope_key=req.scope_key
        ),
    }


@router.get("/sessions/scoped/{scope_key}")
def api_list_scoped_sessions(scope_key: str, limit: int = Query(20)) -> Dict[str, Any]:
    """按 scope_key 查询最新活跃伴学会话（供前端会话切换器按页面隔离）。"""
    return {
        "status": "ok",
        "sessions": _session_svc.list_recent_sessions(scope_key=scope_key, limit=limit),
    }


@router.get("/sessions/{session_id}/messages")
@router.get("/sessions/{session_id}/history")
def api_get_session_history(session_id: str) -> Dict[str, Any]:
    """按时序获取指定会话的完整消息与思维链历史."""
    return {"status": "ok", "messages": _session_svc.get_history(session_id)}


@router.get("/sessions/{session_id}/proposals")
def api_list_proposals(session_id: str, status: Optional[str] = Query(None)) -> Dict[str, Any]:
    """查询指定会话的提议列表."""
    return {"status": "ok", "proposals": _proposal_svc.list_proposals(session_id, status=status)}


@router.post("/chat")
async def api_companion_chat(req: CompanionChatReq, request: Request) -> StreamingResponse:
    """伴学会话流式交互端点 (多轮 Turn 自动沉淀入库)."""
    sid = req.session_id or _session_svc.get_or_create_session(
        article_id=req.article_id, scope_key=req.scope_key
    )["id"]
    user_text = next((m.get("content", "") for m in reversed(req.messages) if m.get("role") == "user"), "")

    # 加法式透传：view / context_source 与旧 context 合并；缺省时 context 原样不变。
    context_payload = dict(req.context or {})
    if req.view:
        context_payload["view"] = req.view
    if req.context_source:
        context_payload["context_source"] = req.context_source
    if req.draft_text:
        context_payload["draft_text"] = req.draft_text

    async def _wrapped_stream() -> AsyncIterator[bytes]:
        full_text, full_thought = [], []
        async for chunk in dispatch_companion_stream(req.messages, request=request, context=context_payload):
            yield chunk
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data: "):
                    with contextlib.suppress(Exception):
                        ev = json.loads(line[6:].strip())
                        if ev.get("event") == "delta":
                            full_text.append(ev.get("text", ""))
                        elif ev.get("event") == "thought":
                            full_thought.append(ev.get("text", ""))
        if user_text or full_text:
            with contextlib.suppress(Exception):
                _session_svc.save_turn(sid, user_text, "".join(full_text), thought="".join(full_thought))

    return StreamingResponse(
        _wrapped_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Session-ID": sid},
    )


@router.post("/proposal/execute", dependencies=[Depends(_require_localhost)])
def api_companion_execute_proposal(req: ProposalExecReq) -> Dict[str, Any]:
    """执行用户确认的 Proposal 提议 (受 127.0.0.1 本机闸保护)."""
    try:
        return _proposal_svc.execute_proposal(req.proposal_id, req.action, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
