# -*- coding: utf-8 -*-
"""伴学智能体 HTTP 路由与 SSE 流式端点 (Task 2).

依据: docs/specs/2026-10-31-companion-study-agent-design.md
      docs/plans/2026-10-31-companion-study-agent.md Task 2
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import date
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from delector.core.database import _require_localhost, get_db, log_study_event
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
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[bytes]:
    """流式产出伴学 Agent 事件帧，带客户端断连主动取消守卫."""
    events: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    state = {"stop": False}

    async def _runner() -> Any:
        return await run_companion_agent_loop(
            messages,
            context=context,
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


async def _dispatch_companion_stream(
    messages: List[Dict[str, Any]],
    request: Request,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[bytes]:
    """优先委托 Go Agent Runtime（方案 A 统管中枢）；未启动时平滑回退 Python 本地内核."""
    go_url = os.getenv("DELECTOR_GO_AGENT_URL", "http://127.0.0.1:8002").strip()
    if go_url:
        try:
            req_payload = {
                "messages": messages,
                "context": context or {},
            }
            from delector.core.db.settings import (
                get_effective_api_base_url,
                get_effective_api_key,
                get_effective_api_model,
            )

            headers: Dict[str, str] = {}
            eff_key = get_effective_api_key()
            if eff_key:
                headers["X-API-Key"] = eff_key
            eff_base = get_effective_api_base_url()
            if eff_base:
                headers["X-Base-URL"] = eff_base
            eff_model = get_effective_api_model()
            if eff_model:
                headers["X-Model"] = eff_model

            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{go_url.rstrip('/')}/api/companion/chat",
                    json=req_payload,
                    headers=headers,
                ) as resp:
                    if resp.status_code == 200:
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                return
                            if chunk:
                                yield chunk
                        return
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            # Go Agent 未启动或连接受挫时，平滑降级由 Python 本地内核继续服务
            pass

    # 兜底：本地 Python 内核流式分发
    async for frame in _companion_event_stream(messages, request, context=context):
        yield frame


@router.post("/chat")
async def api_companion_chat(req: CompanionChatReq, request: Request) -> StreamingResponse:
    """伴学会话流式交互端点（Go Agent 优先反代与 Python 本地双轨流式）."""
    return StreamingResponse(
        _dispatch_companion_stream(req.messages, request, context=req.context),
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
            lemma = str(c.get("lemma") or word).strip()
            pos = str(c.get("pos") or "").strip()
            gender = str(c.get("gender") or "").strip()
            plural = str(c.get("plural") or "").strip()
            cefr_level = str(c.get("cefr_level") or "B1").strip()
            definition_zh = str(c.get("definition_zh") or c.get("reading") or "").strip() or word
            sentence = str(c.get("sentence_context") or c.get("context_sentence") or "").strip()

            cur = conn.execute(
                """
                INSERT INTO vocab_cards (
                    word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'companion')
                """,
                (word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence),
            )
            created_count += 1
            card_id = cur.lastrowid
            if card_id:
                try:
                    log_study_event("add_card", card_id, word, db_path=None)
                except Exception:
                    pass
        conn.commit()

    return {
        "status": "ok",
        "proposal_id": req.proposal_id,
        "action": req.action,
        "created_count": created_count,
    }
