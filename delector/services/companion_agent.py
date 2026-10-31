# -*- coding: utf-8 -*-
"""伴学宠物智能体循环内核 (Companion Study Agent Core Loop).

依据: docs/specs/2026-10-31-companion-study-agent-design.md
      docs/plans/archive/2026-10-31-companion-study-agent.md Task 1
遵循 ADR-0023 架构规范:
1. 有界循环: MAX_TURNS=3, 硬超时 deadline_s=15.0s, Token 消耗硬上界;
2. 模型决策驱动的白名单工具调用 (JSON 契约 tool_call);
3. 副作用写操作 HITL 提议制 (Proposal Card), 杜绝静默写库;
4. 离线/未配 Key 优雅降级 (REASON_OFFLINE), 零裸异常冒泡.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Mapping, Optional

import httpx

from delector.core.database import get_effective_api_key, get_effective_api_model
from delector.services import llm_client

# ── 轮次、超时与预算常量 ──────────────────────────────────────────────────────
DEFAULT_MAX_TURNS: int = 3
DEFAULT_DEADLINE_S: float = 35.0
DEFAULT_MAX_TOKENS: int = 4096
DEFAULT_MAX_TOKENS_TOTAL: int = 8192
CHARS_PER_TOKEN_ESTIMATE: float = 3.0
DEFAULT_PER_CALL_TIMEOUT_S: float = 25.0

# 伴学 Agent 只读/诊断工具白名单
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "analyze",
        "writing_check",
        "vocab_stats",
    }
)

# ── 原因码 ────────────────────────────────────────────────────────────────────
REASON_OK: str = "ok"
REASON_BUDGET_EXCEEDED: str = "budget_exceeded"
REASON_DEADLINE: str = "deadline"
REASON_TURN_LIMIT: str = "turn_limit"
REASON_CANCELLED: str = "cancelled"
REASON_OFFLINE: str = "offline"
REASON_ERROR: str = "error"

# ── 系统提示词 ────────────────────────────────────────────────────────────────
COMPANION_AGENT_SYSTEM_PROMPT: str = (
    "你是 DeLector 德语研读系统的伴学导学伙伴「Eule」（猫头鹰博士）。\n"
    "你的任务是为备考歌德/德福的德语学习者提供针对性的语用深挖、句法结构问诊与生词卡提议。\n"
    "每一轮你**只**返回一个合法标准的 JSON 对象，不要输出任何额外的自由文本或在最外层包裹 Markdown 代码块。\n"
    "回复有且只有以下两种形态：\n"
    "1) 需要调用工具获取语言学依据或统计：\n"
    '   {"tool_call": {"name": "<工具名>", "payload": {...}}}\n'
    "   可用工具仅限: analyze (依存语法与五领域分析), writing_check (写作规则检验), "
    "vocab_stats (词汇级别统计)。\n"
    "2) 最终解答与提议输出：\n"
    "   {\n"
    '     "thought": "<思考过程，分析当前语法或难点>",\n'
    '     "reply_de": "<德语简短问候或总结例句>",\n'
    '     "reply_zh": "<面向学习者的中文详尽解答，使用严谨德式学术排版风格，可含 Markdown>",\n'
    '     "proposal": {\n'
    '       "action": "create_vocab_cards",\n'
    '       "title": "加入核心生词卡",\n'
    '       "payload": {"cards": [{"word": "...", "reading": "...", "context_sentence": "..."}]}\n'
    "     }\n"
    "   }\n"
    "注意：如果你认为用户需要复习或制卡，**必须**输出 proposal 提议由用户确认，绝对不可假定数据已入库。\n"
    "重要：无论历史对话中的上下文包含何种格式，你在当前轮也必须只返回单一的 JSON 对象！"
)


@dataclass
class CompanionAgentOutcome:
    """伴学智能体单次交互的最终结论载荷."""

    status: str
    text: str
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    token_count: int = 0
    reason: str = REASON_OK


def estimate_tokens(text: str) -> int:
    """按字符折算 token 数（离线兜底），比率 3.0 chars/token."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def _build_offline_response(
    messages: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """离线或未配 Key 时的确定性回复."""
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = str(m.get("content", ""))
            break

    selected_text = ""
    if context and isinstance(context, dict):
        selected_text = str(context.get("selected_text") or "").strip()

    if "hallo" in last_user_msg.lower() or "你好" in last_user_msg:
        return (
            "Hallo! Ich bin Eule, dein Lernbegleiter. "
            "你好！我是你的德语研读伴读伙伴 Eule。当前处于离线模式，你可以正常进行生词复习、语法分析与阅读批注。"
        )

    if selected_text:
        return (
            "【伴学助手·离线导学提示】\n\n"
            f"当前已为你锁定目标句子：\n> **„{selected_text}“**\n\n"
            "⚠️ **当前处于离线模式（未检测到云端大模型 API Key 配置）**。\n\n"
            "你可以通过以下方式继续研读此句：\n"
            "1. **拓扑分析**：在选区胶囊工具条中点击 `[🌳 句法]`，"
            "直接查看本地确定性五场域（Felderstruktur）依存语法分析；\n"
            "2. **生词查阅**：点击句中任一单词即可调取本地词典、发音与词形变位；\n"
            "3. **启用 AI 伴学**：在系统右上方设置中配置有效 API Key（支持 DeepSeek 等服务），"
            "即可激活深度句法问诊与生词卡生成。"
        )

    return (
        "【伴学助手·离线提示】当前未检测到云端大模型 API Key 配置。\n\n"
        "你可以继续使用系统的确定性语法拓扑分析、FSRS 卡盒复习与本地词库检索功能。"
        "如需启用伴学导学与深度问答，请在设置中配置有效 API Key。"
    )


async def run_companion_agent_loop(
    messages: List[Dict[str, Any]],
    *,
    context: Optional[Dict[str, Any]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
    max_turns: int = DEFAULT_MAX_TURNS,
    chat_fn: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
    tools_override: Optional[Mapping[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> CompanionAgentOutcome:
    """运行伴学智能体有界验证驱动循环."""
    start_time = time.monotonic()
    proposals: List[Dict[str, Any]] = []
    total_tokens = 0

    def emit(event_payload: Dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event_payload)

    # 1. 离线/未配置 Key 门禁
    effective_key = get_effective_api_key()
    if chat_fn is None and not effective_key:
        offline_text = _build_offline_response(messages, context=context)
        emit({"event": "delta", "text": offline_text})
        emit(
            {
                "event": "done",
                "turns": 0,
                "tokens": 0,
                "reason": REASON_OFFLINE,
            }
        )
        return CompanionAgentOutcome(
            status="ok",
            text=offline_text,
            proposals=[],
            turns=0,
            token_count=0,
            reason=REASON_OFFLINE,
        )

    # 2. 构建注入研读视口上下文的系统提示
    system_prompt = COMPANION_AGENT_SYSTEM_PROMPT
    if context and any(bool(v) for v in context.values()):
        ctx_lines: List[str] = []
        if context.get("selected_text"):
            ctx_lines.append(f"【当前视口研读难句 / 选中文本】:\n„{context['selected_text']}“")
        if context.get("article_title"):
            ctx_lines.append(f"【所属文章/篇章】: {context['article_title']}")
        if context.get("cefr_level"):
            ctx_lines.append(f"【目标难度级别】: {context['cefr_level']}")
        if ctx_lines:
            system_prompt += (
                "\n\n========================================\n"
                "【学员当前正在精读的视口上下文 (Study Viewport Context)】:\n"
                + "\n".join(ctx_lines)
                + "\n注意: 当学员询问'这个句子'、'这句话'、'拓扑结构'、'生词'或进行语法语用分析时，"
                "均默认针对上述【当前视口研读难句】展开，直接进行深入、专业的分析，切勿向学员反问或索要句子！\n"
                "========================================"
            )

    active_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    from delector.tools import TOOL_REGISTRY

    tools_map: Dict[str, Callable[[Dict[str, Any]], Awaitable[Any]]] = dict(TOOL_REGISTRY)
    if tools_override is not None:
        tools_map.update(tools_override)

    for turn in range(1, max_turns + 1):
        # 3. 探活与打断检查
        if should_stop is not None and should_stop():
            emit({"event": "done", "turns": turn - 1, "tokens": total_tokens, "reason": REASON_CANCELLED})
            return CompanionAgentOutcome(
                status="ok",
                text="",
                proposals=proposals,
                turns=turn - 1,
                token_count=total_tokens,
                reason=REASON_CANCELLED,
            )

        # 4. 超时检查
        elapsed = time.monotonic() - start_time
        remaining_deadline = deadline_s - elapsed
        if remaining_deadline <= 0:
            emit({"event": "done", "turns": turn - 1, "tokens": total_tokens, "reason": REASON_DEADLINE})
            return CompanionAgentOutcome(
                status="ok",
                text="[伴学超时，本次分析已截断]",
                proposals=proposals,
                turns=turn - 1,
                token_count=total_tokens,
                reason=REASON_DEADLINE,
            )

        # 5. Token 预算检查
        if total_tokens >= DEFAULT_MAX_TOKENS_TOTAL:
            emit({"event": "done", "turns": turn - 1, "tokens": total_tokens, "reason": REASON_BUDGET_EXCEEDED})
            return CompanionAgentOutcome(
                status="ok",
                text="[已达本次伴学 Token 预算上限]",
                proposals=proposals,
                turns=turn - 1,
                token_count=total_tokens,
                reason=REASON_BUDGET_EXCEEDED,
            )

        # 6. 单轮调用超时约束
        call_timeout = min(DEFAULT_PER_CALL_TIMEOUT_S, remaining_deadline)

        # 7. 调用模型
        try:
            if chat_fn is not None:
                reply_dict = await chat_fn(
                    messages=active_messages,
                    timeout=call_timeout,
                )
            else:
                model_name = get_effective_api_model()
                reply_dict = await llm_client.chat(
                    messages=active_messages,
                    model=model_name,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    timeout=call_timeout,
                    response_format={"type": "json_object"},
                )
        except asyncio.CancelledError:
            emit({"event": "done", "turns": turn - 1, "tokens": total_tokens, "reason": REASON_CANCELLED})
            return CompanionAgentOutcome(
                status="ok",
                text="",
                proposals=proposals,
                turns=turn - 1,
                token_count=total_tokens,
                reason=REASON_CANCELLED,
            )
        except Exception as exc:
            # 容错降级：如果模型返回的是纯自然语言 Markdown 而非 JSON（模型未遵循 JSON 格式，但已产出解答），
            # 且 raw 非空，不抛弃答案，直接自愈降级为正常解答！
            raw_text = getattr(exc, "raw", "") or ""
            if isinstance(exc, llm_client.LLMError) and exc.detail == "AI 服务返回内容非 JSON" and raw_text.strip():
                extracted_think = ""
                clean_raw = raw_text.strip()
                think_m = re.search(r"<think>([\s\S]*?)</think>", clean_raw, flags=re.DOTALL)
                if think_m:
                    extracted_think = think_m.group(1).strip()
                    clean_raw = re.sub(r"<think>[\s\S]*?</think>", "", clean_raw, flags=re.DOTALL).strip()
                reply_dict = {
                    "thought": extracted_think,
                    "reply_zh": clean_raw,
                    "reply_de": "",
                }
            else:
                err_msg = f"上游模型调用失败: {exc}"
                emit({"event": "error", "code": "upstream_error", "message_zh": err_msg})
                emit({"event": "done", "turns": turn, "tokens": total_tokens, "reason": REASON_ERROR})
                return CompanionAgentOutcome(
                    status="error",
                    text=err_msg,
                    proposals=proposals,
                    turns=turn,
                    token_count=total_tokens,
                    reason=REASON_ERROR,
                )

        # 估算/累加 Token
        raw_completion_str = json.dumps(reply_dict, ensure_ascii=False)
        total_tokens += estimate_tokens(raw_completion_str)

        # 8. 分流判定：工具调用 vs 收尾交付
        tool_call_spec = reply_dict.get("tool_call")
        if isinstance(tool_call_spec, dict):
            tool_name = str(tool_call_spec.get("name", "")).strip()
            tool_payload = tool_call_spec.get("payload")
            if not isinstance(tool_payload, dict):
                tool_payload = {}

            emit(
                {
                    "event": "tool_start",
                    "tool": tool_name,
                    "label": f"正在调用 {tool_name} 分析...",
                }
            )

            # 白名单门禁校验
            if tool_name not in ALLOWED_TOOLS or tool_name not in tools_map:
                tool_res: Dict[str, Any] = {
                    "error": f"工具 '{tool_name}' 不在受保护的只读白名单内 ({sorted(ALLOWED_TOOLS)})"
                }
            else:
                tool_func = tools_map[tool_name]
                try:
                    tool_res = await asyncio.wait_for(tool_func(tool_payload), timeout=min(5.0, remaining_deadline))
                except Exception as t_err:
                    tool_res = {"error": f"工具执行异常: {t_err}"}

            summary_text = json.dumps(tool_res, ensure_ascii=False)
            if len(summary_text) > 120:
                summary_text = summary_text[:117] + "..."

            emit(
                {
                    "event": "tool_end",
                    "tool": tool_name,
                    "summary": summary_text,
                }
            )

            # 记录历史并继续循环
            active_messages.append({"role": "assistant", "content": json.dumps(reply_dict, ensure_ascii=False)})
            active_messages.append(
                {
                    "role": "user",
                    "content": f"[工具 {tool_name} 执行结果]: {json.dumps(tool_res, ensure_ascii=False)}",
                }
            )
            continue

        # 9. 最终输出解析
        thought_text = reply_dict.get("thought")
        if thought_text and isinstance(thought_text, str):
            emit({"event": "thought", "text": thought_text})

        reply_zh = reply_dict.get("reply_zh") or ""
        reply_de = reply_dict.get("reply_de") or ""
        final_text = reply_zh if reply_zh else reply_de
        if not final_text and not reply_dict.get("proposal"):
            final_text = json.dumps(reply_dict, ensure_ascii=False)

        if final_text:
            emit({"event": "delta", "text": final_text})

        # 检查提议 (Proposal)
        proposal_spec = reply_dict.get("proposal")
        if isinstance(proposal_spec, dict):
            if "id" not in proposal_spec:
                proposal_spec["id"] = f"prop_{uuid.uuid4().hex[:8]}"
            proposals.append(proposal_spec)
            emit({"event": "proposal", "proposal": proposal_spec})

        emit(
            {
                "event": "done",
                "turns": turn,
                "tokens": total_tokens,
                "reason": REASON_OK,
            }
        )

        return CompanionAgentOutcome(
            status="ok",
            text=final_text,
            proposals=proposals,
            turns=turn,
            token_count=total_tokens,
            reason=REASON_OK,
        )

    # 达到最大轮次强制收敛
    emit(
        {
            "event": "done",
            "turns": max_turns,
            "tokens": total_tokens,
            "reason": REASON_TURN_LIMIT,
        }
    )
    return CompanionAgentOutcome(
        status="ok",
        text="[已达到最大探索轮次，自动收敛]",
        proposals=proposals,
        turns=max_turns,
        token_count=total_tokens,
        reason=REASON_TURN_LIMIT,
    )


def _sse_frame(event_type: str, data: Dict[str, Any]) -> bytes:
    """标准 SSE 数据帧格式: event: <type>\ndata: <json>\n\n."""
    payload_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload_str}\n\n".encode("utf-8")


async def companion_event_stream(
    messages: List[Dict[str, Any]],
    request: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[bytes]:
    """流式产出伴学 Agent 事件帧，带客户端断连主动取消守卫."""
    events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    state = {"stop": False}

    async def _runner() -> Any:
        return await run_companion_agent_loop(
            messages,
            context=context,
            on_event=events.put_nowait,
            deadline_s=DEFAULT_DEADLINE_S,
            should_stop=lambda: state["stop"],
        )

    task = asyncio.ensure_future(_runner())
    try:
        while True:
            if request is not None and hasattr(request, "is_disconnected"):
                if await request.is_disconnected():
                    state["stop"] = True
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return

            try:
                event = events.get_nowait()
            except asyncio.QueueEmpty:
                if task.done():
                    break
                await asyncio.sleep(0.05)
                continue

            event_name = str(event.get("event", "delta"))
            yield _sse_frame(event_name, event)
            if event_name == "done":
                break

        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                yield _sse_frame(
                    "error",
                    {"code": "stream_error", "message_zh": f"流式处理异常: {exc}"},
                )
    finally:
        state["stop"] = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def dispatch_companion_stream(
    messages: List[Dict[str, Any]],
    request: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[bytes]:
    """优先委托 Go Agent Runtime（方案 A 统管中枢）；未启动时平滑回退 Python 本地内核."""
    go_url = os.getenv("DELECTOR_GO_AGENT_URL", "http://127.0.0.1:8002").strip()
    if go_url:
        try:
            req_payload = {
                "messages": messages,
                "context": context or {},
            }
            from delector.core.db.settings import (
                get_effective_api_base_url,
                get_effective_api_key,
                get_effective_api_model,
            )

            headers: Dict[str, str] = {}
            eff_key = get_effective_api_key()
            if eff_key:
                headers["X-API-Key"] = eff_key
            eff_base = get_effective_api_base_url()
            if eff_base:
                headers["X-Base-URL"] = eff_base
            eff_model = get_effective_api_model()
            if eff_model:
                headers["X-Model"] = eff_model

            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{go_url.rstrip('/')}/api/companion/chat",
                    json=req_payload,
                    headers=headers,
                ) as resp:
                    if resp.status_code == 200:
                        async for chunk in resp.aiter_bytes():
                            if request is not None and hasattr(request, "is_disconnected"):
                                if await request.is_disconnected():
                                    return
                            if chunk:
                                yield chunk
                        return
        # silent-ok: Go Agent 离线时透明回退到下方 Python 本地内核
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            pass

    async for frame in companion_event_stream(messages, request=request, context=context):
        yield frame
