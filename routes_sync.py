"""
DeLector - WebRTC LAN Sync Router
Handles short-lived in-memory SDP exchange for zero-copy-paste P2P progress sync.
"""
from typing import Dict, Any
import uuid
import json
import secrets
import time
import threading
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import get_wb_sync_key, verify_wb_key

router = APIRouter(prefix="/api/wb/sync", tags=["WebRTC Sync"])

MAX_SYNC_CACHE_ENTRIES = 50
MAX_SDP_PAYLOAD_BYTES = 32 * 1024
_sync_sdp_cache: Dict[str, Dict[str, Any]] = {}
_sync_lock = threading.Lock()

# 本进程实例指纹：短码只存于「生成它的那个 server 进程」内存。前端用它判断
# 两端是否连到同一实例——跨实例时 B fetch 必然 404「断码无效」，有了它才能
# 给出可行动指引而不是笼统的「无效码」。
_SYNC_INSTANCE_ID = uuid.uuid4().hex[:12]
_SYNC_STARTED_AT = time.time()


def _verify_wb_key(request: Request) -> None:
    """信令端点鉴权：X-WB-Key 须与本机同步密钥一致，否则 403。

    信令要在 LAN 上中继 SDP，不能套 _require_localhost（那样手机永远进不来），
    改为沿用 PUT /api/wb/state 的「凭 key 说话」模型。
    """
    if not verify_wb_key(request.headers.get("X-WB-Key"), get_wb_sync_key()):
        raise HTTPException(403, "invalid X-WB-Key")


def _cleanup_sync_cache() -> None:
    now = time.time()
    expired = [k for k, v in _sync_sdp_cache.items() if now - v.get("ts", 0) > 300]
    for k in expired:
        _sync_sdp_cache.pop(k, None)
    # FIFO 容量限制：当条目数超标时淘汰最老的条目
    while len(_sync_sdp_cache) >= MAX_SYNC_CACHE_ENTRIES:
        oldest_key = min(_sync_sdp_cache.keys(), key=lambda k: _sync_sdp_cache[k].get("ts", 0))
        _sync_sdp_cache.pop(oldest_key, None)


class SyncStoreReq(BaseModel):
    sdp: Dict[str, Any]
    role: str = "offer"


@router.get("/info")
def sync_instance_info():
    """返回本进程实例指纹，供前端判断两端是否连同一台 DeLector 服务端。"""
    return {
        "instance_id": _SYNC_INSTANCE_ID,
        "started_at": _SYNC_STARTED_AT,
        "ttl_seconds": 300,
    }


@router.post("/store")
def sync_store_sdp(req: SyncStoreReq, request: Request):
    _verify_wb_key(request)
    raw_json = json.dumps(req.sdp)
    if len(raw_json.encode("utf-8")) > MAX_SDP_PAYLOAD_BYTES:
        raise HTTPException(400, "SDP payload 超过最大体积限制 (32KB)")
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    with _sync_lock:
        _cleanup_sync_cache()
        _sync_sdp_cache[code] = {
            "sdp": req.sdp,
            "ts": time.time(),
            "role": req.role,
        }
    return {"code": code}


@router.get("/fetch/{code}")
def sync_fetch_sdp(code: str, request: Request):
    _verify_wb_key(request)
    key = code.strip().upper()
    with _sync_lock:
        _cleanup_sync_cache()
        entry = _sync_sdp_cache.pop(key, None)
    if not entry:
        raise HTTPException(404, "短码无效或已过期（5 分钟有效）")
    return {"sdp": entry["sdp"], "role": entry["role"]}
