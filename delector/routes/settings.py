# -*- coding: utf-8 -*-
"""应用设置与模型连通性路由模块（Layer 5 运行装配层）。"""

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from delector.core.database import (
    _require_localhost,
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    get_setting,
    set_setting,
)
from delector.nlp_engine import processor as _nlp_processor
from delector.services import llm_client

router = APIRouter()


class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    api_model: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_rate: Optional[str] = None


def _is_loopback_origin(request: Request) -> bool:
    """来源是否为本机回环（判定口径与 `_require_localhost` 逐字一致）。

    ⚠️ 这里只用来**按来源收敛字段**，MUST NOT 当成整门闸：局域网手机端合法读
    `/api/settings`（前端 static/js/main.js:632-634 靠它渲染设置面板），
    给它 403 会把手机端的配置面板整个打掉。
    """
    host = ""
    if request.client is not None:
        host = getattr(request.client, "host", None) or ""
    return host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")


@router.get("/api/settings")
def get_app_settings(request: Request) -> Dict[str, Any]:
    """读设置。**按来源收敛字段**，不是整门拦截。

    回环来源（127.0.0.1 / ::1）→ 字段集合与历史逐字一致；
    非回环来源（同 Wi-Fi 的手机/平板）→ 响应中**不含** `api_key_masked`
    （哪怕是 first4+last4 的掩码版也不给：局域网来源本就不该看到 key 的任何面）。
    收敛只针对 api key 这一项：手机端自己也要读 base_url / model / tts_* 渲染设置面板
    （前端 static/js/main.js:632-634），挂 `_require_localhost` 会把手机端配置面板打掉。
    """
    key = get_effective_api_key()
    masked = ""
    if key:
        if len(key) > 8:
            masked = key[:4] + "•" * (len(key) - 8) + key[-4:]
        else:
            masked = "••••••••"
    data: Dict[str, Any] = {
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "api_base_url": get_effective_api_base_url(),
        "api_model": get_effective_api_model(),
        "tts_voice": get_setting("TTS_VOICE", "de-DE-KatjaNeural"),
        "tts_rate": get_setting("TTS_RATE", "+0%"),
        # live 读（非导入期快照）：模型惰性加载后，成功/失败状态在首次使用时才回填，见顶部注释。
        "nlp_engine": _nlp_processor.NLP_ENGINE,
        "nlp_engine_detail": _nlp_processor.NLP_ENGINE_DETAIL,
    }
    if not _is_loopback_origin(request):
        # 非回环来源：只减这一项（字段只增不减的回环侧契约见方法 docstring）。
        data.pop("api_key_masked", None)
    return data


@router.post("/api/settings")
def update_app_settings(settings: SettingsUpdate, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    if settings.api_key is not None and settings.api_key.strip() != "":
        set_setting("DEEPSEEK_API_KEY", settings.api_key.strip())
    if settings.api_base_url is not None and settings.api_base_url.strip() != "":
        set_setting("API_BASE_URL", settings.api_base_url.strip())
    if settings.api_model is not None and settings.api_model.strip() != "":
        set_setting("API_MODEL", settings.api_model.strip())
    if settings.tts_voice is not None and settings.tts_voice.strip() != "":
        set_setting("TTS_VOICE", settings.tts_voice.strip())
    if settings.tts_rate is not None and settings.tts_rate.strip() != "":
        set_setting("TTS_RATE", settings.tts_rate.strip())
    return {"success": True, "message": "偏好与 API 设置已保存！"}


@router.post("/api/settings/test-key")
async def test_api_key(settings: SettingsUpdate, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    key = settings.api_key.strip() if (settings.api_key and settings.api_key.strip()) else get_effective_api_key()
    if not key:
        return {"success": False, "error": "请先输入 API Key"}
    base_url = (settings.api_base_url.strip() if settings.api_base_url else get_effective_api_base_url()).rstrip("/")
    model = settings.api_model.strip() if settings.api_model else get_effective_api_model()

    start_t = time.time()
    try:
        await llm_client.chat(
            [{"role": "user", "content": "Sag 'OK'."}],
            model=model,
            # 连通性自检：沿用收口前的现值（5），它只要证明"能连上"，不是生成路径
            max_tokens=llm_client.CONNECTIVITY_MAX_TOKENS,
            timeout=10.0,  # 收口前本端点的现值（10s），语义不变
            # 收口前本端点**只认 HTTP 200**，正文根本不解析（探针真实回的是 `OK`，
            # 不是 JSON）⇒ 不开 content 解析，否则可用 key 会被报成"连接失败"。
            parse_json=False,
            api_key=key,
            base_url=base_url,
        )
    except llm_client.LLMError as e:
        # 现状两条文案保持原样：传输层失败 ⇒「连接失败: <原文>」；HTTP 非 200 ⇒
        # 「连接返回错误代码: <码> (<正文前 100 字符>)」。e.raw 就是收口前的那两处原料。
        if e.status_code is None:
            return {"success": False, "error": f"连接失败: {e.raw}"}
        return {"success": False, "error": f"连接返回错误代码: {e.status_code} ({e.raw[:100]})"}
    latency = int((time.time() - start_t) * 1000)
    return {"success": True, "latency_ms": latency, "message": f"连接成功！响应延迟: {latency}ms"}
