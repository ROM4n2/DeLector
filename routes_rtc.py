"""
DeLector - WebRTC LAN 信令中继（Stage B M3）

与 routes_sync 的 6 位短码中转不同：这里用**持久配对密钥**作邮箱 id——两端长期共用
同一把 key，不需要每次会话再生成/抄写短码。信令只是建连握手用的 SDP/ICE，体量小、
时效短，内存缓存即可，不落盘。

邮箱 id 取密钥的 sha256 摘要而非密钥原文：没必要让密钥在内存结构里再多留一份明文。
"""
import hashlib
import json
import threading
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import get_wb_sync_key, verify_wb_key

router = APIRouter(prefix="/api/wb/rtc", tags=["WebRTC Sync"])

MAX_RTC_MAILBOXES = 50
MAX_RTC_MESSAGES = 50
MAX_RTC_PAYLOAD_BYTES = 32 * 1024
RTC_TTL_SECONDS = 120

_rtc_mailboxes: Dict[str, List[Dict[str, Any]]] = {}
_rtc_lock = threading.Lock()


def _verify_wb_key(request: Request) -> None:
    if not verify_wb_key(request.headers.get("X-WB-Key"), get_wb_sync_key()):
        raise HTTPException(403, "invalid X-WB-Key")


def _mailbox_id(request: Request) -> str:
    return hashlib.sha256(request.headers.get("X-WB-Key", "").encode("utf-8")).hexdigest()


def _purge(now: float) -> None:
    """清掉过期邮箱，并在邮箱数超标时淘汰最久没动静的那个。"""
    for box_id in list(_rtc_mailboxes.keys()):
        kept = [m for m in _rtc_mailboxes[box_id] if now - m["ts"] <= RTC_TTL_SECONDS]
        if kept:
            _rtc_mailboxes[box_id] = kept
        else:
            _rtc_mailboxes.pop(box_id, None)
    while len(_rtc_mailboxes) > MAX_RTC_MAILBOXES:
        oldest = min(_rtc_mailboxes.keys(), key=lambda b: _rtc_mailboxes[b][-1]["ts"])
        _rtc_mailboxes.pop(oldest, None)


class RtcSignalReq(BaseModel):
    client: str
    type: str
    payload: Dict[str, Any] = {}


@router.post("/signal")
def rtc_post_signal(req: RtcSignalReq, request: Request):
    _verify_wb_key(request)
    if len(json.dumps(req.payload)) > MAX_RTC_PAYLOAD_BYTES:
        raise HTTPException(400, "信令 payload 超过最大体积限制 (32KB)")
    msg = {"sender": req.client, "type": req.type, "payload": req.payload, "ts": time.time()}
    with _rtc_lock:
        _purge(time.time())
        box = _rtc_mailboxes.setdefault(_mailbox_id(request), [])
        box.append(msg)
        del box[:-MAX_RTC_MESSAGES]
    return {"ok": True}


@router.get("/signal")
def rtc_get_signal(request: Request, client: str = "", after: float = 0):
    _verify_wb_key(request)
    with _rtc_lock:
        _purge(time.time())
        box = list(_rtc_mailboxes.get(_mailbox_id(request), []))
    # 只投递「别人发的 + 游标之后的」：发信端若收到自己的回声，两端会互相把对方
    # 的旧 offer 当成新 offer 反复重建连接。
    messages = [m for m in box if m["sender"] != client and m["ts"] > after]
    return {"messages": messages, "now": time.time()}
