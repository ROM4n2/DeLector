# -*- coding: utf-8 -*-
"""练习生成/批改 tool：薄包装 services.writing.analyze_a1_email。

A1 邮件写作批改是现有最接近"练习生成"的能力；Phase 2 可在此接更多题型。
"""
from delector.services.writing import analyze_a1_email


async def run(payload: dict) -> dict:
    text = payload["text"]
    leitpunkte = payload.get("leitpunkte")
    return analyze_a1_email(text, leitpunkte)
