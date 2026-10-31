# -*- coding: utf-8 -*-
"""伴学智能体 HTTP 路由与 SSE 流式端点 (Task 2).

依据: docs/specs/2026-10-31-companion-study-agent-design.md
      docs/plans/2026-10-31-companion-study-agent.md Task 2
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import date
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from delector.core.database import _require_localhost, get_db
from delector.services.companion_agent import (
    DEFAULT_DEADLINE_S,
    run_companion_agent_loop,
)

router = APIRouter(prefix="/api/companion", tags=["companion"])

_SSE_POLL_INTERVAL_S: float = 0.05


def _sse_frame(event_type: str, data: Dict[str, Any]) -> bytes:
    """标准 SSE 数据帧格式: event: <type>\ndata: <json>\n\n."""
    payload_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload_str}\n\n".encode("utf-8")


class CompanionChatReq(BaseModel):
    messages: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None


class ProposalExecReq(BaseModel):
    proposal_id: str
    action: str
    payload: Dict[str, Any]


@router.get("/context")
def get_companion_context() -> Dict[str, Any]:
    """返回当前学习与视口上下文摘要."""
    today_str = date.today().isoformat()
    vocab_total = 0
    vocab_mastered = 0

    with get_db() as conn:
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM vocab_cards"
            ).fetchone()
            if row:
                vocab_total = row["total"] or 0
                vocab_mastered = row["mastered"] or 0
        except Exception:
            pass

    return {
        "status": "ok",
        "context": {
            "date": today_str,
            "vocab_total": vocab_total,
            "vocab_mastered": vocab_mastered,
        },
    }


async def _companion_event_stream(
    messages: List[Dict[str, Any]],
    request: Request,
) -> AsyncIterator[bytes]:
    """流式产出伴学 Agent 事件帧，带客户端断连主动取消守卫."""
    events: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    state = {"stop": False}

    async def _runner() -> Any:
        return await run_companion_agent_loop(
            messages,
            on_event=events.put_nowait,
            deadline_s=DEFAULT_DEADLINE_S,
            should_stop=lambda: state["stop"],
        )

    task = asyncio.ensure_future(_runner())
    try:
        while True:
            # 客户端断连探活
            if await request.is_disconnected():
                state["stop"] = True
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return

            try:
                event = events.get_nowait()
            except asyncio.QueueEmpty:
                if task.done():
                    break
                await asyncio.sleep(_SSE_POLL_INTERVAL_S)
                continue

            event_name = str(event.get("event", "delta"))
            yield _sse_frame(event_name, event)
            if event_name == "done":
                break

        # 检查是否有未捕获异常
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                yield _sse_frame(
                    "error",
                    {"code": "stream_error", "message_zh": f"流式处理异常: {exc}"},
                )
    finally:
        state["stop"] = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@router.post("/chat")
async def api_companion_chat(req: CompanionChatReq, request: Request) -> StreamingResponse:
    """伴学会话流式交互端点."""
    return StreamingResponse(
        _companion_event_stream(req.messages, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/proposal/execute", dependencies=[Depends(_require_localhost)])
def api_companion_execute_proposal(req: ProposalExecReq) -> Dict[str, Any]:
    """执行用户确认的 Proposal 提议（写操作受 127.0.0.1 本机闸保护）."""
    if req.action != "create_vocab_cards":
        raise HTTPException(
            status_code=400,
            detail=f"不支持的提议动作类型: {req.action}",
        )

    cards = req.payload.get("cards")
    if not isinstance(cards, list):
        raise HTTPException(
            status_code=400,
            detail="提议 payload 缺少有效的 'cards' 列表",
        )

    created_count = 0
    with get_db() as conn:
        for c in cards:
            if not isinstance(c, dict):
                continue
            word = str(c.get("word", "")).strip()
            if not word:
                continue
            reading = str(c.get("reading", "")).strip()
            sentence = str(c.get("context_sentence", "")).strip()

            conn.execute(
                """
                INSERT INTO vocab_cards (word, reading, context_sentence, source)
                VALUES (?, ?, ?, 'companion')
                """,
                (word, reading, sentence),
            )
            created_count += 1
        conn.commit()

    return {
        "status": "ok",
        "proposal_id": req.proposal_id,
        "action": req.action,
        "created_count": created_count,
    }
