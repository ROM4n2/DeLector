# -*- coding: utf-8 -*-
"""A1 写作批改 tool：薄包装 services.writing.analyze_a1_email。

命名对齐真实语义——这是**批改/检查**，不是"练习生成"（原名 exercise 属语义造假，
vault-grill ADR-0009 Q2A 纠正）。Phase 2 若出现真正的练习生成需求，另立新 tool，
不在本模块上长。
"""
from delector.services.writing import analyze_a1_email


async def run(payload: dict) -> dict:
    text = payload["text"]
    leitpunkte = payload.get("leitpunkte")
    return analyze_a1_email(text, leitpunkte)
