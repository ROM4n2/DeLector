# -*- coding: utf-8 -*-
"""NLP 分析 tool：薄包装 nlp_engine.processor.process_german_text。"""
from delector.nlp_engine.processor import process_german_text


async def run(payload: dict) -> dict:
    text = payload["text"]
    return process_german_text(text)
