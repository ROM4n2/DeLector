# -*- coding: utf-8 -*-
"""导出 tool：薄包装 core.database.export_anki_deck。"""
import tempfile

from delector.core.database import export_anki_deck


async def run(payload: dict) -> dict:
    output_path = payload.get("output_path") or tempfile.mktemp(suffix=".apkg")
    db_path = payload.get("db_path")
    path = export_anki_deck(output_path, db_path)
    return {"path": path}
