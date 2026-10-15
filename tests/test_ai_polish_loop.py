# -*- coding: utf-8 -*-
"""`delector.services.polish_loop` 的契约测试（**全 stub，绝不发真请求 / 不依赖真 Key**）。

背景（Task 4 · ADR-0023 §4.2 / §8.2）：`ai-polish` 从 one-shot「取神谕」改为
**模型驱动流转 + 确定性裁判终审**的有界循环。本文件钉住它的停止策略、预算、哨兵与
零静默失败承诺，并**现算现比**地钉住三个预算常量（不抄过期数字）。

隔离纪律：与 `tests/test_llm_client.py` 同一惯例 —— 注入 stub（本文件连 httpx 都不需要），
用 `asyncio.run(...)` 跑协程（本仓无 pytest-asyncio）。任何一条测试都**不许**碰真实
`DEEPSEEK_API_KEY`（依赖真 key 的测试在门禁上恒 skip，等于没有测试）。

判别力纪律：每条语义测试都要能分辨「对应守卫被抽掉」——见模块底部的变异自证说明。
"""

import asyncio
import json
import math
import os
import re
from typing import Any, Callable

import pytest

from delector.services import llm_client
from delector.services.polish_loop import (
    CHARS_PER_TOKEN_ESTIMATE,
    DEFAULT_DEADLINE_S,
    DEFAULT_MAX_TOKENS_TOTAL,
    EVIDENCE_MAX_BYTES,
    EVIDENCE_MAX_LINES,
    MAX_TURNS_DEFAULT,
    REASONS,
    Budget,
    LoopResult,
    completion_tokens_of,
    default_violations_of,
    estimate_tokens,
    run_polish_loop,
    truncate_evidence,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 桩件 ──────────────────────────────────────────────────────────────────────
class Recorder:
    """录制 chat 桩：记下每次 `(messages, max_tokens, timeout, model)`，按脚本回放回复。

    脚本用完后一律回最后一条（"模型从此只会这一招"），便于把循环逼到轮次/预算闸上。
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        script: list[dict[str, Any]],
        *,
        on_call: Callable[[], None] | None = None,
    ) -> Callable[..., Any]:
        async def _chat(
            *,
            messages: list[dict[str, Any]] | None = None,
            model: str | None = None,
            timeout: float | None = None,
            max_tokens: int | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "messages": [dict(m) for m in (messages or [])],
                    "model": model,
                    "timeout": timeout,
                    "max_tokens": max_tokens,
                }
            )
            if on_call is not None:
                on_call()
            idx = len(self.calls) - 1
            return script[idx] if idx < len(script) else script[-1]

        return _chat

    @property
    def timeouts(self) -> list[float]:
        return [float(c["timeout"]) for c in self.calls]

    @property
    def max_tokens(self) -> list[int]:
        return [int(c["max_tokens"]) for c in self.calls]

    def all_contents(self) -> list[str]:
        out: list[str] = []
        for call in self.calls:
            for msg in call["messages"]:
                content = msg.get("content")
                if isinstance(content, str):
                    out.append(content)
        return out

    def prompt_chars(self) -> list[int]:
        return [sum(len(c) for c in self._contents_of(i)) for i in range(len(self.calls))]

    def prompt_bytes(self) -> list[int]:
        return [sum(len(c.encode("utf-8")) for c in self._contents_of(i)) for i in range(len(self.calls))]

    def _contents_of(self, index: int) -> list[str]:
        return [str(m.get("content", "")) for m in self.calls[index]["messages"]]


def make_judge(counts: dict[str, int], log: list[str] | None = None) -> Callable[[str, list[str] | None], dict]:
    """确定性裁判桩：按**文本**查表给出 error 级违规数（顺带记录被裁过的文本）。"""

    def _judge(text: str, leitpunkte: list[str] | None = None) -> dict:
        if log is not None:
            log.append(text)
        n = counts.get(text, 0)
        return {
            "word_count": len(text.split()),
            "suggestions": [{"rule": f"rule_{i}", "level": "error", "message": f"违规 {i}"} for i in range(n)],
        }

    return _judge


def boom_judge(text: str, leitpunkte: list[str] | None = None) -> dict:
    """Unknown D 按「会抛」设计：裁判可能抛任意异常，循环 MUST NOT 让它冒泡。"""
    raise RuntimeError("judge exploded")


def echo_tool(result: dict[str, Any]) -> Callable[..., Any]:
    async def _tool(payload: dict[str, Any]) -> dict[str, Any]:
        return result

    return _tool


def run(**kwargs: Any) -> Any:
    """同步跑一次循环（本仓无 pytest-asyncio，沿用 `asyncio.run` 惯例）。

    返回类型写成 `Any`：测试文件用 `--follow-imports=skip` 检查，`LoopResult` 在那个档位下
    是 `Any`，标成具体类型只会逼出一个多余的 `type: ignore`（本仓禁裸 ignore）。
    """
    return asyncio.run(run_polish_loop(**kwargs))


TOOL_CALL: dict[str, Any] = {"tool_call": {"name": "known", "payload": {}}}


# ── 最坏输入：2000 字符的真实德语 A1 电子邮件 ──────────────────────────────────
# 口径 = `delector/routes/main.py:2383` 的 `text = req.text[:2000]`（端点真实输入上限）。
# 素材复用 `tests/test_goethe_a1_writing.py` 里的真实样本句式，补齐到恰好 2000 字符。
_FILLER = "Ich freue mich sehr auf deine Antwort und hoffe, dass alles gut klappt. "


def build_worst_case_text(total: int = 2000) -> str:
    greeting = "Liebe Maria,\n"
    valediction = "\nViele Grüße\nAnna"
    body_src = (
        "ich lade dich herzlich zu meiner Geburtstagsparty ein. "
        "Die Party beginnt am Samstag um 18 Uhr bei mir zu Hause. "
        "Kannst du einen Kuchen mitbringen? "
        "Ich freue mich sehr auf deinen Besuch und hoffe, dass du Zeit hast. "
    )
    blob = body_src + _FILLER * 40
    cut = total - len(greeting) - len(valediction)
    return greeting + blob[:cut] + valediction


WORST_CASE_TEXT = build_worst_case_text()
WORST_CASE_LEITPUNKTE = ["Geburtstagsparty einladen", "Zeit und Ort nennen", "Was mitbringen"]


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def measure_worst_case_three_turns() -> dict[str, Any]:
    """录制桩跑满 3 轮最坏输入，返回**原始数字**（字符/字节/折算 token 各一份）。

    不出网、不用真 Key。3 轮脚本 = 前两轮取证、第 3 轮收尾（最坏体量：完整重写 + 中文说明）。
    """
    rewritten = WORST_CASE_TEXT.replace("Party", "Feier")
    script: list[dict[str, Any]] = [
        {"tool_call": {"name": "writing_check", "payload": {"leitpunkte": WORST_CASE_LEITPUNKTE}}},
        {"tool_call": {"name": "writing_check", "payload": {"leitpunkte": WORST_CASE_LEITPUNKTE}}},
        {
            "corrected_text": rewritten,
            "notes_zh": ["称呼语已补齐逗号", "结语去掉逗号", "正文首词改为小写"],
        },
    ]
    rec = Recorder()
    result = run(
        text=WORST_CASE_TEXT,
        leitpunkte=WORST_CASE_LEITPUNKTE,
        tools={"writing_check": echo_tool({"rule": "a1_greeting_body_lowercase", "level": "error"})},
        chat=rec.chat(script),
        budget=Budget(),
    )
    completion_chars = [len(dump(script[i])) for i in range(len(rec.calls))]
    completion_bytes = [len(dump(script[i]).encode("utf-8")) for i in range(len(rec.calls))]
    completion_tokens = [completion_tokens_of(script[i]) for i in range(len(rec.calls))]
    return {
        "rounds": result.rounds,
        "reason": result.reason,
        "prompt_chars": rec.prompt_chars(),
        "prompt_bytes": rec.prompt_bytes(),
        "completion_chars": completion_chars,
        "completion_bytes": completion_bytes,
        "completion_tokens": completion_tokens,
        "completion_tokens_sum": sum(completion_tokens),
        "per_turn_worst_tokens": max(completion_tokens),
    }


def read_frontend_timeout_ms() -> int:
    """从 `static/js/core.js` **现读** `DEFAULT_TIMEOUT_MS`（不许抄成常量）。"""
    path = os.path.join(ROOT, "static", "js", "core.js")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"DEFAULT_TIMEOUT_MS\s*=\s*(\d+)\s*;", src)
    assert m is not None, "static/js/core.js 里找不到 DEFAULT_TIMEOUT_MS —— 外层超时口径丢失，死线闸无从谈起"
    return int(m.group(1))


# ── 语义测试 ──────────────────────────────────────────────────────────────────
def test_converges_when_violations_drop_to_zero() -> None:
    """收敛成功：v_1 == 0 且严格下降 ⇒ `converged=True, reason='ok'`。"""
    log: list[str] = []
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}]),
        judge=make_judge({"T0": 1, "T1": 0}, log),
    )

    assert result.converged is True
    assert result.reason == "ok"
    assert result.text == "T1"
    assert result.rounds == 1
    assert result.violations == []
    assert log == ["T0", "T1"], f"原文与收尾候选都应过裁判（D3）：{log}"


def test_converged_zero_violation_pair_returns_candidate_not_original() -> None:
    """并列零违规：v_0 == v_1 == 0 ⇒ 收敛且返回**候选**（不是原文）。

    判别力：把出口的收敛归属改回 argmin ⇒ 本用例 MUST 红 —— `min` 在并列时取
    **最早**条目 = 原文，等于把用户点的润色原样退回（Task 6 端点兜底删掉后，
    这个归属只能由循环自己给出）。
    """
    log: list[str] = []
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}]),
        judge=make_judge({"T0": 0, "T1": 0}, log),
    )

    assert result.converged is True
    assert result.reason == "ok"
    assert result.text == "T1", f"收敛 ⇒ 返回那个零违规候选，不是原文：{result.text}"
    assert result.rounds == 1
    assert result.violations == []
    assert log == ["T0", "T1"], f"原文与收尾候选都应过裁判（D3）：{log}"


def test_no_improvement_stops_and_rolls_back_to_argmin() -> None:
    """不降即停：v_1 >= v_0 ⇒ break + 回退到 argmin(violations) 的历史候选。"""
    log: list[str] = []
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}]),
        judge=make_judge({"T0": 1, "T1": 2}, log),
    )

    assert result.converged is False
    assert result.reason == "no_improvement", f"未收敛 MUST 带原因码（零静默失败）：{result.reason}"
    assert result.text == "T0", f"必须回退到违规最少的历史候选：{result.text}"
    assert result.rounds == 1
    assert len(result.violations) == 1


def test_judge_unreliable_sentinel_when_violations_stall() -> None:
    """哨兵：v_n == v_{n-1} 且 n>=2 ⇒ 裁判不再下降 ⇒ `judge_unreliable`。"""
    log: list[str] = []
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}, {"corrected_text": "T2"}]),
        judge=make_judge({"T0": 3, "T1": 2, "T2": 2}, log),
    )

    assert result.converged is False
    assert result.reason == "judge_unreliable", f"第 2 个候选仍不下降 ⇒ 裁判不可信：{result.reason}"
    assert result.rounds == 2
    assert result.text == "T1", f"回退到 argmin（T1 与 T2 并列取先者）：{result.text}"


def test_turn_limit_when_model_never_finishes() -> None:
    """轮次硬闸：模型一直要证据 ⇒ 跑满 `max_turns` 后带 `turn_limit` 退出。"""
    rec = Recorder()

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat([TOOL_CALL]),
        judge=make_judge({"T0": 1}),
    )

    assert result.converged is False
    assert result.reason == "turn_limit"
    assert result.rounds == MAX_TURNS_DEFAULT
    assert result.text == "T0"


def test_token_budget_breaks_loop_and_clamps_per_call_cap() -> None:
    """预算前置检查：累计 completion 超 `max_tokens_total` ⇒ `token_budget`；per-call 上限被夹到剩余量。"""
    rec = Recorder()
    script = [{"tool_call": {"name": "known", "payload": {}}, "usage": {"completion_tokens": 60}}]

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat(script),
        judge=make_judge({"T0": 1}),
        budget=Budget(max_tokens_total=100),
    )

    assert result.converged is False
    assert result.reason == "token_budget"
    assert result.rounds == 2
    assert rec.max_tokens == [100, 40], f"每轮上限必须夹到 min(4096, 剩余总量)：{rec.max_tokens}"


def test_deadline_breaks_loop_and_clamps_per_call_timeout() -> None:
    """到点次序：内层 deadline 先到点，且每次 chat 的 timeout = min(30, 剩余 deadline)。"""
    state = {"t": 0.0}
    rec = Recorder()

    def _clock() -> float:
        return state["t"]

    def _advance() -> None:
        state["t"] += 10.0

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat([TOOL_CALL], on_call=_advance),
        judge=make_judge({"T0": 1}),
        clock=_clock,
    )

    assert result.converged is False
    assert result.reason == "deadline"
    assert result.rounds == 2, f"第 3 轮开始前剩余 ≤0 ⇒ 直接退出：{result.rounds}"
    assert rec.timeouts == [18.0, 8.0], f"timeout 必须是 min(30, 剩余 deadline)：{rec.timeouts}"
    assert max(rec.timeouts) < 30.0, "内层 MUST 比每轮默认超时更紧，否则到点次序不成立"


def test_judge_exception_degrades_single_round_without_500() -> None:
    """Unknown D（按"会抛"设计）：裁判抛异常 ⇒ errors-as-messages 单轮降级，记 `judge_error`。"""
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}]),
        judge=boom_judge,
    )

    assert result.converged is False
    assert result.reason == "judge_error", f"轮次耗尽只是表象，真实原因是裁判一直抛：{result.reason}"
    assert result.rounds == MAX_TURNS_DEFAULT
    assert any("裁判异常" in c for c in rec.all_contents()), "裁判异常 MUST 作为消息喂回模型（不是 500、不冒泡）"


def test_finish_candidate_without_fresh_verdict_is_rejected() -> None:
    """D3 收尾终审守卫（**删掉守卫必须变红**）：收尾候选 MUST 先过本轮裁判。

    判别力：删掉守卫 ⇒ 裁判根本不会被调用在收尾候选上 ⇒ `log[-1]` 停在前一个文本，
    且循环会拿"没有裁决"当成"零违规" ⇒ 静默假收敛。这里同时钉住两件事。
    """
    log: list[str] = []
    rec = Recorder()

    result = run(
        text="T0",
        chat=rec.chat([{"corrected_text": "T1"}]),
        judge=make_judge({"T0": 1, "T1": 1}, log),
    )

    assert log[-1] == "T1", f"收尾候选 MUST 被裁（无本轮新鲜裁决不许收尾）：{log}"
    assert log.count("T1") == 1
    assert result.converged is False, "T1 有 1 条违规，不得静默判成收敛"
    assert result.reason == "no_improvement"


def test_cancelled_by_should_stop() -> None:
    """`should_stop()` 为真 ⇒ break，`reason='cancelled'`（Task 6 取消按钮的挂点）。"""
    seen: list[int] = []
    rec = Recorder()

    def _should_stop() -> bool:
        seen.append(1)
        return len(seen) >= 2

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat([TOOL_CALL]),
        judge=make_judge({"T0": 1}),
        should_stop=_should_stop,
    )

    assert result.converged is False
    assert result.reason == "cancelled"
    assert result.rounds == 1


def test_unknown_tool_name_is_fed_back_not_raised() -> None:
    """未知工具名 ⇒ errors-as-messages（不抛异常、不炸循环），模型据此改过。"""
    rec = Recorder()
    script: list[dict[str, Any]] = [
        {"tool_call": {"name": "nope", "payload": {}}},
        {"corrected_text": "T1"},
    ]

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat(script),
        judge=make_judge({"T0": 1, "T1": 0}),
    )

    assert result.converged is True, "未知工具只是证据，不得终止循环"
    assert result.rounds == 2
    assert any("未知工具" in c for c in rec.all_contents()), "未知工具 MUST 作为消息喂回模型"


def test_evidence_truncation_respects_line_limit() -> None:
    """证据双限之一：**行数上限**真起作用（此时字节限不咬合，证明两个限互相独立）。"""
    rec = Recorder()
    script: list[dict[str, Any]] = [
        {"tool_call": {"name": "known", "payload": {}}},
        {"corrected_text": "T1"},
    ]

    result = run(
        text="T0",
        tools={"known": echo_tool({"items": ["a"] * 200})},
        chat=rec.chat(script),
        judge=make_judge({"T0": 1, "T1": 0}),
    )
    body = _evidence_body(rec)

    assert len(body.splitlines()) == EVIDENCE_MAX_LINES, f"行数上限没起作用：{len(body.splitlines())} 行"
    assert len(body.encode("utf-8")) < EVIDENCE_MAX_BYTES, "这一例应当是**行限**咬合，字节限不该同时触发"
    assert result.converged is True


def test_evidence_truncation_respects_byte_limit() -> None:
    """证据双限之二：**字节上限**真起作用（行数远低于上限，证明是字节限在咬）。"""
    rec = Recorder()
    script: list[dict[str, Any]] = [
        {"tool_call": {"name": "known", "payload": {}}},
        {"corrected_text": "T1"},
    ]

    result = run(
        text="T0",
        tools={"known": echo_tool({"blob": "x" * 15000})},
        chat=rec.chat(script),
        judge=make_judge({"T0": 1, "T1": 0}),
    )
    body = _evidence_body(rec)

    assert len(body.encode("utf-8")) == EVIDENCE_MAX_BYTES, f"字节上限没起作用：{len(body.encode('utf-8'))}"
    assert len(body.splitlines()) < EVIDENCE_MAX_LINES, "这一例应当是**字节限**咬合，行限不该同时触发"
    assert result.converged is True


def _evidence_body(rec: Recorder) -> str:
    """取注入的证据正文（消息形如 `[工具结果:<name>]\n<evidence>`）。"""
    for content in rec.all_contents():
        if content.startswith("[工具结果:"):
            head, _, tail = content.partition("\n")
            assert head.endswith("]")
            return tail
    raise AssertionError("没有找到注入的证据消息 —— 工具结果没被喂回模型")


def test_token_accounting_prefers_usage_completion_tokens() -> None:
    """计量路径一：优先 `usage.completion_tokens`（真链路形态），不靠估算。"""
    rec = Recorder()
    script: list[dict[str, Any]] = [
        {"tool_call": {"name": "known", "payload": {}}, "usage": {"completion_tokens": 4096}}
    ]

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat(script),
        judge=make_judge({"T0": 1}),
    )

    # 回复体积极小，若走估算（几十 token）绝不可能一轮就把 4096 的循环预算烧穿。
    assert result.reason == "token_budget", f"必须按 usage 精确计量：{result.reason}"
    assert result.rounds == 1


def test_token_accounting_falls_back_to_estimate() -> None:
    """计量路径二：`usage` 缺失 ⇒ `estimate_tokens()` 字符折算（与预算实测共用同一常量）。"""
    big = {"tool_call": {"name": "known", "payload": {}}, "notes_zh": ["说" * 900]}
    rec = Recorder()

    result = run(
        text="T0",
        tools={"known": echo_tool({"ok": True})},
        chat=rec.chat([big]),
        judge=make_judge({"T0": 1}),
        budget=Budget(max_tokens_total=100),
    )

    assert result.reason == "token_budget", f"无 usage 时 MUST 走估算计量：{result.reason}"
    assert result.rounds == 1

    sample = "a" * 100
    assert estimate_tokens(sample) == math.ceil(len(sample) / CHARS_PER_TOKEN_ESTIMATE)
    assert completion_tokens_of({"x": sample}) == estimate_tokens(dump({"x": sample}))


@pytest.fixture(scope="module")
def nlp() -> Any:
    """真 spaCy 德语模型（沿用 `tests/test_writing_rules.py` 的 nlp fixture 惯例）；缺失 ⇒ skip。"""
    import spacy

    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


def test_real_judge_is_wired_at_the_assembly_point(nlp: Any, monkeypatch: Any) -> None:
    """**装配点**（旧 pin `test_real_judge_is_wired_by_default` 的裁决改造）。

    旧 pin 逐字钉住「内核默认裁判 == `writing.analyze_a1_email`」——那钉的是「业务住在机制
    内核」。Task 1 的接缝方向相反：内核只留**可注入的缝**，业务由**产品层装配**。按计划
    Global Constraints 的裁决规则，把它从「默认值」改为「装配点」：断言生产链路 `_run_polish`
    传给 `run_polish_loop` 的 `judge=` 真是一个经 `analyze_a1_email(text, leitpunkte, nlp)`
    装配、且**带 nlp** 的裁判（证据 = 裁决体 `judge_engine == "rules+spacy"` 且语法违规出现）。

    **这不是放宽**：旧 pin 钉「内核自带业务」，新 pin 钉「业务在产品层装配**且真送进循环**」
    —— 后者更强，能拦住「只改 `writing.py` 却没接到生产链路」的 dead-green。
    """
    from delector.nlp_engine import processor
    from delector.routes.main import _run_polish

    captured: dict[str, Any] = {}

    async def _fake_loop(**kwargs: Any) -> Any:
        captured.update(kwargs)
        # 模拟循环至少裁一次原文 ⇒ 触发 `_JudgeRecorder` 记下 judge_engine。
        kwargs["judge"](kwargs["text"])
        return LoopResult(text=kwargs["text"], converged=True, reason="ok", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", _fake_loop)
    monkeypatch.setattr("delector.routes.main.get_effective_api_base_url", lambda: "http://stub")
    monkeypatch.setattr(processor, "get_loaded_nlp", lambda: nlp)

    outcome = asyncio.run(_run_polish("Ich habe ein Hund.", "sk-stub"))

    judge = captured.get("judge")
    assert judge is not None, "端点 MUST 真的把 judge= 注入循环（否则生产上语法裁判恒不生效）"
    verdict = judge("Ich habe ein Hund.")
    assert verdict["judge_engine"] == "rules+spacy", "装配出的裁判 MUST 带 nlp"
    assert any(v["rule"] == "artikel" for v in verdict["violations"]), "语法族 MUST 在装配出的裁判里生效"
    assert outcome.judge_engine == "rules+spacy"


def test_endpoint_assembly_degrades_to_rules_only_when_no_nlp(monkeypatch: Any) -> None:
    """装配点对照：nlp 来源不可用 ⇒ 装配出的裁判 `judge_engine == "rules_only"`（如实降级）。"""
    from delector.nlp_engine import processor
    from delector.routes.main import _run_polish

    captured: dict[str, Any] = {}

    async def _fake_loop(**kwargs: Any) -> Any:
        captured.update(kwargs)
        kwargs["judge"](kwargs["text"])
        return LoopResult(text=kwargs["text"], converged=True, reason="ok", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", _fake_loop)
    monkeypatch.setattr("delector.routes.main.get_effective_api_base_url", lambda: "http://stub")
    monkeypatch.setattr(processor, "get_loaded_nlp", lambda: None)
    monkeypatch.setattr(processor, "try_load_nlp_no_download", lambda: None)

    outcome = asyncio.run(_run_polish("Ich habe ein Hund.", "sk-stub"))

    assert captured.get("judge") is not None
    assert outcome.judge_engine == "rules_only"


def test_default_violations_extractor_ignores_warnings() -> None:
    """默认抽取器只取 `level == 'error'`（warning 是建议，不阻止收敛）。"""
    assert default_violations_of({"suggestions": [{"rule": "a1_word_count", "level": "warning"}]}) == []


def test_chat_failure_propagates_instead_of_faking_a_reason() -> None:
    """`chat` 抛 `LLMError` ⇒ 原样冒泡：原因码集合里没有"上游失败"，编一个就是替上游撒谎。"""

    async def _boom(**kwargs: Any) -> dict[str, Any]:
        raise llm_client.LLMError("AI 服务异常 (503)")

    with pytest.raises(llm_client.LLMError):
        run(text="T0", chat=_boom, judge=make_judge({"T0": 1}))


def test_on_progress_reports_final_reason() -> None:
    """进度回调 MUST 在结尾给出 `converged` / `reason`（Task 6 的进度条与 toast 靠它）。"""
    events: list[dict[str, Any]] = []

    result = run(
        text="T0",
        chat=Recorder().chat([{"corrected_text": "T1"}]),
        judge=make_judge({"T0": 1, "T1": 2}),
        on_progress=events.append,
    )

    assert events, "进度回调 MUST 被至少调用一次"
    assert events[-1]["converged"] is False
    assert events[-1]["reason"] == "no_improvement"
    assert events[-1]["reason"] == result.reason


def test_declared_reason_codes_match_task6_contract() -> None:
    """原因码集合是 Task 6 的响应体契约，改动 MUST 同时改前端文案。`cancelled` 本次就要在位。"""
    assert REASONS == {
        "ok",
        "no_improvement",
        "turn_limit",
        "token_budget",
        "deadline",
        "judge_unreliable",
        "judge_error",
        "cancelled",
    }
    # 出口结构同样是 Task 6 的响应体契约（字段名改了前端就拿不到）
    assert set(LoopResult.__dataclass_fields__) == {"text", "converged", "reason", "rounds", "violations"}


# ── 预算闸（**现算现比**，不硬编码过期数字） ────────────────────────────────────
def test_worst_case_fixture_is_exactly_endpoint_truncation_limit() -> None:
    """最坏输入口径：`main.py:2383` 的 `req.text[:2000]` ⇒ 夹具必须恰好 2000 字符。"""
    assert len(WORST_CASE_TEXT) == 2000, f"最坏输入夹具长度失真：{len(WORST_CASE_TEXT)}"


def test_per_call_max_tokens_has_2x_headroom_over_measured_worst_turn() -> None:
    """闸① `DEFAULT_MAX_TOKENS >= 2 × 实测单轮最坏需求`（余量 2×）。"""
    m = measure_worst_case_three_turns()

    assert m["rounds"] == MAX_TURNS_DEFAULT, f"必须真的跑满 3 轮才能谈实测：{m['rounds']}"
    assert llm_client.DEFAULT_MAX_TOKENS >= 2 * m["per_turn_worst_tokens"], (
        f"per-call 上限 {llm_client.DEFAULT_MAX_TOKENS} 必须留 2× 余量："
        f"实测单轮最坏 {m['per_turn_worst_tokens']} token，2× = {2 * m['per_turn_worst_tokens']}"
    )


def test_cycle_token_budget_bites_before_per_call_times_turns() -> None:
    """闸② `DEFAULT_MAX_TOKENS_TOTAL < DEFAULT_MAX_TOKENS × MAX_TURNS_DEFAULT`。

    否则「每轮上限 × 轮数」永远先到点 ⇒ 循环级预算是**永不触发的真空闸**。
    """
    assert DEFAULT_MAX_TOKENS_TOTAL < llm_client.DEFAULT_MAX_TOKENS * MAX_TURNS_DEFAULT, (
        f"循环级预算 {DEFAULT_MAX_TOKENS_TOTAL} 必须小于 {llm_client.DEFAULT_MAX_TOKENS}×{MAX_TURNS_DEFAULT}"
        f"={llm_client.DEFAULT_MAX_TOKENS * MAX_TURNS_DEFAULT}，否则它是真空闸"
    )


def test_cycle_token_budget_covers_measured_three_turn_worst() -> None:
    """闸③ `DEFAULT_MAX_TOKENS_TOTAL >= 实测 3 轮最坏合计需求`（够用）。"""
    m = measure_worst_case_three_turns()

    assert m["rounds"] == MAX_TURNS_DEFAULT
    assert DEFAULT_MAX_TOKENS_TOTAL >= m["completion_tokens_sum"], (
        f"循环级预算 {DEFAULT_MAX_TOKENS_TOTAL} 装不下实测 3 轮合计 {m['completion_tokens_sum']} token"
    )
    # 保守口径：实测里两轮取证的回复体量很小，真实模型完全可能每轮都回"完整重写"。
    # 故再按"3 轮都取单轮最坏"验一次 —— 不许拿乐观样本给预算放行。
    conservative = MAX_TURNS_DEFAULT * m["per_turn_worst_tokens"]
    assert DEFAULT_MAX_TOKENS_TOTAL >= conservative, (
        f"循环级预算 {DEFAULT_MAX_TOKENS_TOTAL} 装不下保守口径"
        f" {MAX_TURNS_DEFAULT}×{m['per_turn_worst_tokens']}={conservative} token"
    )


def test_deadline_is_strictly_inside_frontend_timeout() -> None:
    """跨边界闸：`DEFAULT_DEADLINE_S < DEFAULT_TIMEOUT_MS / 1000`（**内层必须先到点**）。

    数字从 `static/js/core.js` **现读**，不许抄常量 —— 前端改了超时，这里立刻红。
    """
    timeout_ms = read_frontend_timeout_ms()

    assert DEFAULT_DEADLINE_S < timeout_ms / 1000, (
        f"内层 deadline {DEFAULT_DEADLINE_S}s 必须严格小于外层 {timeout_ms}ms"
        f"（否则前端只拿到 abort，拿不到人话原因码）"
    )


def test_truncate_evidence_is_pure_and_both_limits_are_independent() -> None:
    """双限截断是纯函数：单独喂超长输入时，哪个限先咬合只取决于输入形状。"""
    many_lines = "\n".join("a" for _ in range(500))
    one_huge_line = "x" * 10000

    cut_lines = truncate_evidence(many_lines)
    assert len(cut_lines.splitlines()) == EVIDENCE_MAX_LINES
    assert len(cut_lines.encode("utf-8")) <= EVIDENCE_MAX_BYTES

    cut_bytes = truncate_evidence(one_huge_line)
    assert len(cut_bytes.splitlines()) == 1
    assert len(cut_bytes.encode("utf-8")) <= EVIDENCE_MAX_BYTES
