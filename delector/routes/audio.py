# -*- coding: utf-8 -*-
"""Edge Neural TTS 语音合成与音频缓存路由模块（Layer 5 运行装配层）。"""

import asyncio
import contextlib
import hashlib
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from delector.core.database import (
    AUDIO_CACHE_DIR,
    _require_localhost,
    get_cache_info,
    prune_audio_cache,
)

router = APIRouter()


class TTSReq(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-KatjaNeural"
    rate: Optional[str] = "+0%"


# 朗读输入上限：局域网可达端点，防超大文本打满合成队列与磁盘缓存（场景是词/句级）
MAX_TTS_TEXT_LEN = 1000


async def generate_edge_tts_audio(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> str:
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(400, "Text cannot be empty")
    if len(clean_text) > MAX_TTS_TEXT_LEN:
        raise HTTPException(400, f"朗读文本过长（最多 {MAX_TTS_TEXT_LEN} 字符）")

    cache_key = hashlib.sha256(f"{voice}_{rate}_{clean_text}".encode("utf-8")).hexdigest()
    cache_file = os.path.join(AUDIO_CACHE_DIR, f"{cache_key}.mp3")

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 100:
        return cache_file

    try:
        try:
            import edge_tts

            communicate = edge_tts.Communicate(clean_text, voice=voice, rate=rate)
            await communicate.save(cache_file)
        except ImportError:
            # Android/Chaquopy 没有 edge_tts 的 wheel（aiohttp 等依赖缺）→ 用 stdlib 版客户端
            # （services.tts 复刻同一 WebSocket+Sec-MS-GEC 协议，零依赖；原名 edge_tts_mini）
            from delector.services import tts as edge_tts_mini

            audio_data = await asyncio.to_thread(edge_tts_mini.synthesize, clean_text, voice, rate)
            with open(cache_file, "wb") as f:
                f.write(audio_data)
    except Exception:
        # Multi-provider pure-Python httpx fallback (accessible in mainland China)
        from urllib.parse import quote

        q = quote(clean_text[:250])
        candidate_urls = [
            f"https://dict.youdao.com/dictvoice?audio={q}&le=de",
            f"https://fanyi.baidu.com/gettts?lan=de&text={q}&spd=3&source=web",
            f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=de&client=tw-ob",
        ]
        for tts_url in candidate_urls:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(
                        tts_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    )
                    if resp.status_code == 200 and len(resp.content) > 200:
                        with open(cache_file, "wb") as f:
                            f.write(resp.content)
                        prune_audio_cache()
                        return cache_file
            except Exception as exc:
                logging.getLogger("delector").warning("TTS fallback provider 失败：%s（%s）", tts_url, exc)
                continue
        # 兜底全部失败：固定文案上屏，内部异常只留服务端日志
        logging.getLogger("delector").warning("TTS all providers failed", exc_info=True)
        raise HTTPException(500, "语音合成失败，请稍后重试")

    # 主路径（edge_tts 或 edge_tts_mini）成功：落地缓存后返回
    prune_audio_cache()
    return cache_file


_TTS_RATE_RE = re.compile(r"^[+-]\d+%$")
_TTS_VOICE_WHITELIST = frozenset(
    {
        "de-DE-KatjaNeural",
        "de-DE-ConradNeural",
        "de-DE-AmalaNeural",
        "de-DE-KillianNeural",
    }
)

_TTS_CONCURRENCY_LIMIT = 4
_TTS_SEMAPHORE = asyncio.Semaphore(_TTS_CONCURRENCY_LIMIT)
_TTS_BUSY_DETAIL = "TTS 并发已满，请稍后重试"


@contextlib.asynccontextmanager
async def _tts_slot() -> AsyncIterator[None]:
    """占用一个 TTS 名额；拿不到立刻抛 429（不等待）。"""
    if _TTS_SEMAPHORE.locked():
        raise HTTPException(status_code=429, detail=_TTS_BUSY_DETAIL)
    await _TTS_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _TTS_SEMAPHORE.release()


async def _serve_tts(text: str, voice: str, rate: str) -> Any:
    """POST 与 GET 两个路由共享的 TTS 服务逻辑。"""
    if not _TTS_RATE_RE.match(rate or ""):
        raise HTTPException(status_code=400, detail="rate must look like '+0%', '-10%' or '+50%'")
    if (voice or "") not in _TTS_VOICE_WHITELIST:
        raise HTTPException(status_code=400, detail="unsupported voice")

    async with _tts_slot():
        try:
            audio_path = await generate_edge_tts_audio(text, voice, rate)
            return FileResponse(audio_path, media_type="audio/mpeg", filename="speech.mp3")
        except HTTPException:
            raise
        except Exception:
            logging.getLogger("delector").exception("TTS synthesis failed")
            raise HTTPException(500, "语音合成失败，请稍后重试")


@router.post("/api/audio/tts")
async def get_audio_tts(req: TTSReq) -> Any:
    return await _serve_tts(req.text, req.voice or "de-DE-KatjaNeural", req.rate or "+0%")


@router.get("/api/audio/tts")
async def audio_tts_get(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> Any:
    """GET 版 TTS：供 <audio src="/api/audio/tts?text=..."> 直接用。
    与 POST 共享同一缓存池（cache key 仍为 sha256(f"{voice}_{rate}_{clean_text}")）。"""
    return await _serve_tts(text, voice, rate)


@router.get("/api/audio/cache")
def get_audio_cache() -> Any:
    return get_cache_info(AUDIO_CACHE_DIR)


@router.post("/api/audio/cache/clear")
def clear_audio_cache(request: Request) -> Dict[str, Any]:
    """清空音频缓存。"""
    _require_localhost(request)
    info_before = get_cache_info(AUDIO_CACHE_DIR)
    cleared_count = 0
    failed_files: List[str] = []
    if os.path.exists(AUDIO_CACHE_DIR):
        for fname in os.listdir(AUDIO_CACHE_DIR):
            fpath = os.path.join(AUDIO_CACHE_DIR, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    cleared_count += 1
            except Exception as exc:
                logging.getLogger("delector").warning("[audio-cache] 删除失败 %s: %s", fpath, exc)
                failed_files.append(fname)
    info_after = get_cache_info(AUDIO_CACHE_DIR)
    freed_bytes = int(info_before["total_size_bytes"]) - int(info_after["total_size_bytes"])
    return {
        "status": "ok",
        "cleared_count": cleared_count,
        "failed_count": len(failed_files),
        "failed_files": failed_files,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }
