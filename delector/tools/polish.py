# -*- coding: utf-8 -*-
"""润色循环的任务级工具白名单与前置钩子（Layer 4 工具接口层）。

依据 docs/agents/architecture.md Layer 0~5 层序声明，本模块属于 Layer 4 [工具接口层]：
聚合具体的只读工具（writing_check, analyze, vocab_stats），向 Agent 润色循环提供任务级能力白名单与直调执行器。
"""

from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Sequence

from delector.tools import analyze, vocab_stats, writing_check

# 前置钩子：调用之前执行，拿到 `(工具名, payload 快照)`；抛异常 ⇒ 该次调用被拒。
Hook = Callable[[str, dict[str, Any]], None]

# 显式标注值类型：三个 run 的返回注解并不一致，统一抽象为 dict
_TOOLS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "writing_check": writing_check.run,
    "analyze": analyze.run,
    "vocab_stats": vocab_stats.run,
}

#: 任务级最小白名单（恰好 3 项，只读视图；值 = delector.tools.<mod>.run 真身）。
POLISH_TOOL_ALLOWLIST: Mapping[str, Callable[..., Awaitable[dict[str, Any]]]] = MappingProxyType(_TOOLS)


def _brief(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _hook_name(hook: Hook) -> str:
    name = getattr(hook, "__name__", "")
    return str(name) if name else type(hook).__name__


async def call_tool(
    name: str,
    payload: dict[str, Any],
    *,
    hooks: Sequence[Hook] = (),
) -> dict[str, Any]:
    """按白名单同进程直调一个润色工具；hooks 在调用之前串行执行。"""
    for hook in hooks:
        try:
            hook(name, dict(payload))
        except Exception as exc:
            return {
                "error": f"工具 '{name}' 调用被前置钩子拒绝: {_brief(exc)}",
                "rejected": True,
                "hook": _hook_name(hook),
            }

    fn = POLISH_TOOL_ALLOWLIST.get(name)
    if fn is None:
        return {"error": f"未知工具 '{name}'", "available": sorted(POLISH_TOOL_ALLOWLIST)}

    return await fn(payload)
