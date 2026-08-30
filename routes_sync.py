"""
DeLector - WebRTC LAN Sync Router
Handles short-lived in-memory SDP exchange for zero-copy-paste P2P progress sync.
"""
from typing import Dict, Any
import json
import secrets
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/wb/sync", tags=["WebRTC Sync"])

MAX_SYNC_CACHE_ENTRIES = 50
MAX_SDP_PAYLOAD_BYTES = 32 * 1024
_sync_sdp_cache: Dict[str, Dict[str, Any]] = {}


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


@router.post("/store")
def sync_store_sdp(req: SyncStoreReq):
    raw_json = json.dumps(req.sdp)
    if len(raw_json.encode("utf-8")) > MAX_SDP_PAYLOAD_BYTES:
        raise HTTPException(400, "SDP payload 超过最大体积限制 (32KB)")
    _cleanup_sync_cache()
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    _sync_sdp_cache[code] = {
        "sdp": req.sdp,
        "ts": time.time(),
        "role": req.role,
    }
    return {"code": code}


@router.get("/fetch/{code}")
def sync_fetch_sdp(code: str):
    _cleanup_sync_cache()
    key = code.strip().upper()
    entry = _sync_sdp_cache.pop(key, None)
    if not entry:
        raise HTTPException(404, "短码无效或已过期（5 分钟有效）")
    return {"sdp": entry["sdp"], "role": entry["role"]}
