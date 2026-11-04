# -*- coding: utf-8 -*-
"""伴学智能体 HTTP 路由与 SSE 流式端点 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
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
_SSE_FRAME_BOUNDARY = re.compile(rb"(?:\r\n|\r(?!\n)|\n){2}")


class _SSEEventAccumulator:
    """跨网络 chunk 累积 SSE 帧；只有空行闭合的帧才可解析."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> List[Dict[str, Any]]:
        self._buffer.extend(chunk)
        events: List[Dict[str, Any]] = []
        while match := _SSE_FRAME_BOUNDARY.search(self._buffer):
            frame = bytes(self._buffer[: match.start()])
            del self._buffer[: match.end()]
            data_lines = []
            for line in frame.splitlines():
                if line.startswith(b"data:"):
                    value = line[5:]
                    data_lines.append(value[1:] if value.startswith(b" ") else value)
            if not data_lines:
                continue
            with contextlib.suppress(Exception):
                event = json.loads(b"\n".join(data_lines).decode("utf-8", errors="replace"))
                if isinstance(event, dict):
                    events.append(event)
        return events


class CompanionChatReq(BaseModel):
    messages: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    article_id: Optional[str] = None
    # 加法式字段：缺省时行为与第一阶段完全一致。
    view: Optional[str] = None
    context_source: Optional[str] = None
    draft_text: Optional[str] = None
    card_context: Optional[str] = None
    scope_key: Optional[str] = None


class ProposalExecReq(BaseModel):
    proposal_id: str
    action: str
    payload: Dict[str, Any]


class ProposalRejectReq(BaseModel):
    proposal_id: str


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
    if req.card_context:
        context_payload["card_context"] = req.card_context

    async def _wrapped_stream() -> AsyncIterator[bytes]:
        full_text, full_thought = [], []
        proposals_payload: List[Dict[str, Any]] = []
        seen_proposal_ids: set[str] = set()
        sse_events = _SSEEventAccumulator()

        try:
            async for chunk in dispatch_companion_stream(req.messages, request=request, context=context_payload):
                # 先解析再转发：即便客户端在 yield 点断开，最后一帧也已进入本轮快照。
                for ev in sse_events.feed(chunk):
                    if ev.get("event") == "delta":
                        full_text.append(ev.get("text", ""))
                    elif ev.get("event") == "thought":
                        full_thought.append(ev.get("text", ""))
                    elif ev.get("event") == "proposal":
                        prop = ev.get("proposal")
                        if not isinstance(prop, dict):
                            prop = {
                                "id": ev.get("id"),
                                "action": ev.get("action"),
                                "title": ev.get("title"),
                                "payload": ev.get("payload"),
                            }
                        pid = str(prop.get("id") or "")
                        if pid and pid in seen_proposal_ids:
                            continue
                        if pid:
                            seen_proposal_ids.add(pid)
                        proposals_payload.append(prop)
                yield chunk
        finally:
            # Starlette 的 disconnect listener 会直接在 yield 点关闭生成器；
            # 正常结束与取消路径都必须保留已解析的断点，取消异常本身继续传播。
            save_messages = bool(user_text or full_text)
            if save_messages or proposals_payload:
                try:
                    _session_svc.save_turn_snapshot(
                        sid,
                        user_text,
                        "".join(full_text),
                        thought="".join(full_thought),
                        proposals=proposals_payload,
                        save_messages=save_messages,
                    )
                except Exception as exc:  # silent-ok: 快照整体回滚，不落库错误打断已完成的 SSE 流
                    if proposals_payload:
                        logging.getLogger("delector").warning(
                            "伴学 proposal/消息快照落库失败，已整体回滚: %s", exc
                        )

    # 本轮起点由后端权威历史给出：session_id 缺省时也可能复用既有 scope 会话。
    history_length = len(_session_svc.get_history(sid))
    return StreamingResponse(
        _wrapped_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-ID": sid,
            "X-History-Length": str(history_length),
        },
    )


@router.post("/proposal/execute", dependencies=[Depends(_require_localhost)])
def api_companion_execute_proposal(req: ProposalExecReq) -> Dict[str, Any]:
    """执行用户确认的 Proposal 提议 (受 127.0.0.1 本机闸保护)."""
    try:
        return _proposal_svc.execute_proposal(req.proposal_id, req.action, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/proposal/reject", dependencies=[Depends(_require_localhost)])
def api_companion_reject_proposal(req: ProposalRejectReq) -> Dict[str, Any]:
    """用户拒绝 Proposal：只流转状态，不写任何卡片（受 127.0.0.1 本机闸保护）。"""
    result = _proposal_svc.reject_proposal(req.proposal_id)
    if not result.get("rejected"):
        raise HTTPException(status_code=404, detail="proposal not found or already resolved")
    return result
