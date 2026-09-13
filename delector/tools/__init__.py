# -*- coding: utf-8 -*-
"""Agent 工具接口层（ADR-0008 Phase 1 Task 7）。

把现有业务能力包装成统一签名的 tool，供 Go Agent（Phase 2）通过
`POST /api/tools/{tool_name}` 以 HTTP 调用。每个 tool 暴露
`async def run(payload: dict) -> dict`：薄包装 + 统一契约。

TOOL_REGISTRY：tool 名 → run 协程，routes/tools.py 据此分发。
"""

from delector.tools import (
    analyze,
    export,
    ingest,
    tts_tool,
    vocab_stats,
    writing_check,
)

TOOL_REGISTRY = {
    "ingest": ingest.run,
    "analyze": analyze.run,
    "writing_check": writing_check.run,
    "export": export.run,
    "tts": tts_tool.run,
    "vocab_stats": vocab_stats.run,
}

__all__ = [
    "TOOL_REGISTRY",
    "analyze",
    "export",
    "ingest",
    "tts_tool",
    "vocab_stats",
    "writing_check",
]
