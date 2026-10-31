# -*- coding: utf-8 -*-
"""伴学 Agent 循环内核有界性与契约测试 (Task 1).

依据: docs/plans/2026-10-31-companion-study-agent.md Task 1.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from delector.services.companion_agent import (
    REASON_BUDGET_EXCEEDED,
    REASON_CANCELLED,
    REASON_DEADLINE,
    REASON_OFFLINE,
    REASON_OK,
    REASON_TURN_LIMIT,
    CompanionAgentOutcome,
    run_companion_agent_loop,
)


def test_loop_zero_key_offline_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 API Key 且未注入 chat_fn 时，安全降级为离线问答，零异常冒泡。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    events: List[Dict[str, Any]] = []

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "Hallo Eule, wer bist du?"}],
            on_event=events.append,
        )
    )

    assert isinstance(outcome, CompanionAgentOutcome)
    assert outcome.status == "ok"
    assert outcome.reason == REASON_OFFLINE
    assert len(outcome.text) > 0
    assert any(e.get("event") == "done" for e in events)


def test_loop_single_turn_reply_and_delta() -> None:
    """单轮直接收尾：验证事件流（thought、delta、done）与结果载荷。"""
    events: List[Dict[str, Any]] = []

    async def mock_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "thought": "Ich analysiere die Frage des Benutzers.",
            "reply_de": "Hallo! Ich bin deine Lernbegleiterin Eule.",
            "reply_zh": "你好！我是你的伴学助手 Eule 猫头鹰。有什么德语学习问题需要我协助解答吗？",
        }

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "你好"}],
            chat_fn=mock_chat,
            on_event=events.append,
        )
    )

    assert outcome.status == "ok"
    assert outcome.reason == REASON_OK
    assert outcome.turns == 1
    assert "Eule" in outcome.text
    event_names = [e.get("event") for e in events]
    assert "thought" in event_names
    assert "delta" in event_names
    assert "done" in event_names


def test_loop_turn_limit_guard() -> None:
    """模型持续发起 tool_call 时，必须在达到最大轮次 (3 轮) 时强制终止，严禁死循环。"""
    call_count = 0

    async def endless_tool_caller(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "tool_call": {
                "name": "analyze",
                "payload": {"text": "Das ist ein Beispielsatz."},
            }
        }

    async def fake_analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"syntax": "ok", "level": "A1"}

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "循环测试"}],
            chat_fn=endless_tool_caller,
            tools_override={"analyze": fake_analyze},
            max_turns=3,
        )
    )

    assert call_count == 3
    assert outcome.turns == 3
    assert outcome.reason in (REASON_TURN_LIMIT, REASON_BUDGET_EXCEEDED)


def test_loop_deadline_guard() -> None:
    """超时硬闸门：当总耗时超过 deadline_s 时，优雅退出，不抛裸 Timeout 异常。"""

    async def slow_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        return {
            "tool_call": {
                "name": "analyze",
                "payload": {"text": "Langsam"},
            }
        }

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "超时测试"}],
            chat_fn=slow_chat,
            deadline_s=0.02,
            max_turns=5,
        )
    )

    assert outcome.reason == REASON_DEADLINE


def test_loop_tool_execution_success() -> None:
    """测试真实的工具调用过程（tool_start -> 执行 -> tool_end -> 交付下一轮）。"""
    events: List[Dict[str, Any]] = []
    step = 0

    async def two_step_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return {
                "thought": "Ich muss zuerst den Satz analysieren.",
                "tool_call": {
                    "name": "analyze",
                    "payload": {"text": "Weil ich krank bin, bleibe ich zu Hause."},
                },
            }
        return {
            "reply_zh": "分析完成：这是一个典型的 weil 引导的原因状语从句（动词后置）。",
        }

    async def mock_analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"clause_type": "subordinate", "verb_position": "end"}

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "分析从句"}],
            chat_fn=two_step_chat,
            tools_override={"analyze": mock_analyze},
            on_event=events.append,
        )
    )

    assert outcome.status == "ok"
    assert outcome.turns == 2
    event_names = [e.get("event") for e in events]
    assert "tool_start" in event_names
    assert "tool_end" in event_names
    assert "动词后置" in outcome.text


def test_loop_unknown_tool_rejected() -> None:
    """未知或未授权工具必须被拒绝，把错误信息作为消息回传给模型，不发生越权或崩溃。"""
    step = 0

    async def unauthorized_caller(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return {
                "tool_call": {
                    "name": "delete_all_cards",
                    "payload": {},
                }
            }
        return {
            "reply_zh": "对不起，我无法执行未授权的工具调用。",
        }

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "删除全部卡片"}],
            chat_fn=unauthorized_caller,
        )
    )

    assert outcome.status == "ok"
    assert outcome.turns == 2
    assert "未授权" in outcome.text


def test_loop_proposal_generation() -> None:
    """模型生成提议时，正确抛出 proposal 事件并记录到 outcome.proposals 中。"""
    events: List[Dict[str, Any]] = []

    async def proposal_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "reply_zh": "我已经为你提取了文章中的核心生词。",
            "proposal": {
                "action": "create_vocab_cards",
                "title": "加入 2 个 B1 核心生词",
                "payload": {
                    "cards": [
                        {"word": "die Herausforderung", "reading": "挑战"},
                        {"word": "bewältigen", "reading": "克服，应对"},
                    ]
                },
            },
        }

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "帮我提取生词并做卡"}],
            chat_fn=proposal_chat,
            on_event=events.append,
        )
    )

    assert outcome.status == "ok"
    assert len(outcome.proposals) == 1
    assert outcome.proposals[0]["action"] == "create_vocab_cards"
    assert any(e.get("event") == "proposal" for e in events)


def test_loop_client_cancellation() -> None:
    """客户端取消 (should_stop=True) 时，循环主动掐断并返回 cancelled 原因码。"""
    stop_flag = False

    async def interruptible_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        nonlocal stop_flag
        stop_flag = True
        return {
            "tool_call": {
                "name": "analyze",
                "payload": {"text": "Test"},
            }
        }

    async def mock_quick_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok"}

    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "打断测试"}],
            chat_fn=interruptible_chat,
            tools_override={"analyze": mock_quick_tool},
            should_stop=lambda: stop_flag,
        )
    )

    assert outcome.reason == REASON_CANCELLED


def test_loop_injects_viewport_study_context() -> None:
    """验证传入视口难句与研读上下文时，系统提示词中正确注入难句且对齐问诊。"""
    captured_messages: List[Dict[str, Any]] = []

    async def mock_inspect_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        msgs = kwargs.get("messages", [])
        captured_messages.extend(msgs)
        return {
            "reply_de": "Der Satz ist formell.",
            "reply_zh": "该句为标准官方客套通知，语气客观克制。",
        }

    sample_sentence = "Sie können den Artikel leider nicht mehr aufrufen."
    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "这个句子的语用正式度如何？"}],
            context={
                "selected_text": sample_sentence,
                "article_title": "Spiegel Online B1",
                "cefr_level": "B1",
            },
            chat_fn=mock_inspect_chat,
        )
    )

    assert outcome.status == "ok"
    assert len(captured_messages) > 0
    system_msg = next((m for m in captured_messages if m.get("role") == "system"), None)
    assert system_msg is not None
    assert sample_sentence in str(system_msg.get("content", ""))
    assert "Spiegel Online B1" in str(system_msg.get("content", ""))
    assert "B1" in str(system_msg.get("content", ""))


def test_loop_graceful_recovery_when_model_outputs_plain_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """当模型返回纯自然语言 Markdown（未按格式输出 JSON）时，循环自愈降级并交付答案，不抛异常崩溃。"""
    from delector.services import llm_client

    async def _mock_plain_markdown_chat(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        plain_text = (
            "<think>\n分析从句位置\n</think>\n"
            "# 德语难句分析\n这是一个典型的主从复合句，从句位于末尾。"
        )
        raise llm_client.LLMError("AI 服务返回内容非 JSON", status_code=200, raw=plain_text)

    monkeypatch.setattr("delector.services.companion_agent.llm_client.chat", _mock_plain_markdown_chat)
    monkeypatch.setattr("delector.services.companion_agent.get_effective_api_key", lambda: "fake-key")

    events: List[Dict[str, Any]] = []
    outcome = asyncio.run(
        run_companion_agent_loop(
            [{"role": "user", "content": "帮我分析这句话"}],
            on_event=events.append,
        )
    )

    assert outcome.status == "ok"
    assert "典型的主从复合句" in outcome.text
    event_types = [e["event"] for e in events]
    assert "thought" in event_types
    assert "delta" in event_types
    assert "done" in event_types
    assert "error" not in event_types

