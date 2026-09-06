# -*- coding: utf-8 -*-
"""Anki 导出 tool：薄包装 core.database.export_anki_deck。

`output_path` 为**必填**——服务端不做临时路径兜底。`tempfile.mktemp()` 已被官方
废弃且存在 TOCTOU 竞态（文件名返回与真正创建之间可被抢注），vault-grill
ADR-0009 Q2A 决策：调用方显式给落点，缺失就抛错，绝不在服务端猜路径。
"""
from delector.core.database import export_anki_deck


async def run(payload: dict) -> dict:
    output_path = payload.get("output_path")
    if not output_path:
        raise ValueError("output_path is required（拒绝服务端自选临时路径）")
    path = export_anki_deck(output_path, payload.get("db_path"))
    return {"path": path}
