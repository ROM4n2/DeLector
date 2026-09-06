# -*- coding: utf-8 -*-
"""TTS tool：薄包装 services.tts.synthesize（标准库版 Edge TTS 客户端）。"""
import base64

from delector.services.tts import synthesize


async def run(payload: dict) -> dict:
    text = payload["text"]
    voice = payload.get("voice", "de-DE-KatjaNeural")
    rate = payload.get("rate", "+0%")
    audio = synthesize(text, voice, rate)
    return {
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "voice": voice,
        "rate": rate,
    }
