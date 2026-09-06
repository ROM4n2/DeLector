# -*- coding: utf-8 -*-
"""文章摄入 tool：薄包装 security.fetch_remote_html。

Phase 2 Go Agent 拿到文章 URL 后，经此 tool 拉取 HTML（落库由 server 既有 ingest
流程负责；本 tool 只负责"取"，返回原文 HTML 供下游处理）。
"""
from delector.core.security import fetch_remote_html


async def run(payload: dict) -> dict:
    url = payload["url"]
    html = await fetch_remote_html(url)
    return {"url": url, "html": html}
