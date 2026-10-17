# -*- coding: utf-8 -*-
"""A1 写作批改 tool：薄包装 services.writing.analyze_a1_email。

命名对齐真实语义——这是**批改/检查**，不是"练习生成"（原名 exercise 属语义造假，
vault-grill ADR-0009 Q2A 纠正）。Phase 2 若出现真正的练习生成需求，另立新 tool，
不在本模块上长。
"""

from typing import Any, Dict

from delector.services.writing import analyze_a1_email


async def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    text: str = payload["text"]
    leitpunkte = payload.get("leitpunkte")
    nlp = payload.get("nlp")
    if nlp is None:
        try:
            from delector.nlp_engine import processor as _nlp_processor

            nlp = _nlp_processor.get_loaded_nlp()
        except Exception:
            nlp = None

    verdict: Dict[str, Any] = analyze_a1_email(text, leitpunkte, nlp=nlp)
    if verdict.get("judge_engine") == "rules_only":
        verdict["mode_note"] = "[快速模式: 不含深层语法规则]"
    return verdict
