# -*- coding: utf-8 -*-
"""共享小工具：平台探测 + 附件下载响应头。

本模块零包内依赖（只吃标准库），供任意层引用，用于打破
`nlp → start`、`routes_a1 → server` 的反向/跨边界 import（ADR-0008 Phase 1 Task 1）。
"""
import os
import sys
from typing import Dict
from urllib.parse import quote

__all__ = ["is_android", "_attachment_headers", "_NO_STORE_HEADERS"]


def is_android() -> bool:
    """是否跑在 Chaquopy/Android 运行时里。"""
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ


# ── 附件下载响应头 ────────────────────────────────────────────────────────────
# 所有会触发浏览器/ WebView 下载的端点都要走这里，两件事一起做：
#
# 1) no-store：Android 导出链路里同一个 URL 会被取两次（WebView 先嗅探一次
#    Content-Disposition，App 侧的落盘逻辑再取一次）。若中间有一次拿到的是
#    404 错误体，WebView 的 HTTP 缓存可能把它记住，第二次连服务端都不问，
#    直接把缓存的错误 JSON 存成「备份」—— 静默假备份，最难排查的一种失败。
#
# 2) filename 加引号 + filename*：老写法是裸的 `filename=xxx.json`。RFC 6266
#    要求加引号，且非 ASCII 名必须走 filename*=UTF-8''percent-encoded。
#    Android 的 URLUtil.guessFileName 对无引号值的解析各版本不一致。
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _attachment_headers(filename: str) -> Dict[str, str]:
    """生成 Content-Disposition: attachment 的完整响应头（含 no-store）。"""
    safe = (filename or "delector_export").replace('"', "")
    quoted = safe.replace("\\", "\\\\").replace('"', '\\"')
    headers = dict(_NO_STORE_HEADERS)
    headers["Content-Disposition"] = (
        f'attachment; filename="{quoted}"; filename*=UTF-8\'\'{quote(safe)}'
    )
    return headers
