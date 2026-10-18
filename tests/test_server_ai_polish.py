# -*- coding: utf-8 -*-
"""AI 润色域的端点测试（C6 Task 5 自 `tests/test_server.py` 逐字搬出）。

搬出的四段（搬前 `test_server.py` 行号，实测，含各段头注释与段间空行）：
  `1799`-`1949`  v4.4 Task6 的 6.3 子段：AI 402 / timeout / non-JSON ⇒ 502
          （Task6 大段头下其余子段 6.1 备份边界 / 6.2 Android spaCy / 6.4 前端
          展示已由 C6 Task 3 / Task 2 先行搬出，6.3 是留下的最后一段，逐字随搬）
  `2758`-`2905`  AI 润色循环（Task 6）：返回契约 / 适用性闸门 / 流式进度 / 断连取消
  `2906`-`3017`  Task 1/2 评审 RED#1 闭环：端点级接线回归 + 引擎降级诚实性
  `3018`-`3615`  Task 7：文本族感知的提示词参数化

冻结面纪律（C1 #147 / C3 #148）：本文件断言逐字未改 —— `judge_feedback` /
`text_type` / `usage` / 收敛契约相关断言与搬前逐字节一致；只新增本文件的显式
import。共享夹具（clean_db / client）住在 `tests/server_helpers.py` 与
`tests/conftest.py`，按名即可见。
"""

import asyncio
import contextlib
import json
import re
from typing import Any, Dict, List

import pytest
from server_helpers import clean_db as clean_db
from starlette.responses import StreamingResponse
from wb_source import decl_body, read_source

from delector.routes.main import AIPolishReq, _polish_event_stream, api_writing_ai_polish
from delector.services import polish_loop

# ── v4.4 Task6: Backup source, Android spaCy loading, AI failure paths ─────────

# --- 6.3 AI 402 / timeout / non-JSON (server returns 502, not 200) ---


def _make_402_client():
    class _R:
        status_code = 402
        text = '{"error":{"code":"insufficient_balance"}}'

        def json(self):
            return {"error": "Insufficient Balance"}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


def _make_timeout_client():
    import httpx as _httpx

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            raise _httpx.TimeoutException("simulated timeout")

    return _C


def _make_non_json_client():
    class _R:
        status_code = 200
        text = "not json"

        def json(self):
            raise ValueError("not json")

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


def _make_non_json_content_client():
    """HTTP 200 但 choices[0].message.content 不是 JSON。"""

    class _R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "THIS IS NOT JSON"}}]}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_note_assist_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.articles.get_effective_api_key", lambda *a, **k: "«redacted:sk-…»")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/ai/note-assist", json={"sentence": "Guten Tag.", "selected_text": "Guten Tag"})
    assert res.status_code == 502, f"AI 失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    # 不得泄露 API Key
    assert "«redacted:sk-…»" not in res.text


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_ai_polish_diff_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "«redacted:sk-…»")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish/diff", json={"text": "Ich habe ein Hund."})
    assert res.status_code == 502, f"AI 润色失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    assert "«redacted:sk-…»" not in res.text


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_ai_polish_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "«redacted:sk-…»")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 502
    assert "«redacted:sk-…»" not in res.text


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client])
def test_grammar_lookup_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-grammar")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/lookup/grammar", json={"sentence": "Ich gehe.", "target_phrase": "gehe"})
    assert res.status_code == 502
    assert "sk-grammar" not in res.text


def test_ai_no_key_stub_still_succeeds(client, monkeypatch):
    """无 key 时仍返回 200 stub（与网络失败的 502 区分）。"""
    monkeypatch.setattr("delector.routes.articles.get_effective_api_key", lambda *a, **k: "")
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/ai/note-assist", json={"sentence": "Hallo.", "selected_text": "Hallo"})
    assert res.status_code == 200
    assert res.json().get("_stub") is True
    res2 = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


# ── AI 润色循环（Task 6）：返回契约 / 适用性闸门 / 流式进度 / 断连取消 ───────────
_ESSAY_TEXT = "Ich habe ein Hund. Er ist gut."
# 书信体夹具：正文首词小写已对，但结语后带逗号 ⇒ 恰好 1 条 error（裁判有话可说）。
_LETTER_TEXT = "Liebe Maria,\nich lade dich ein.\nViele Grüße,\nAnna"


class _ScriptedChat:
    """`llm_client.chat` 的脚本桩：逐轮按顺序回复（脚本用完后重复最后一条）。"""

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        self.script = script
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        return self.script[idx] if idx < len(self.script) else self.script[-1]

    def contents(self) -> List[str]:
        """所有轮次里出现过的消息正文（用于断言「证据被回喂给了模型」）。"""
        out: List[str] = []
        for call in self.calls:
            for msg in call.get("messages", []):
                content = msg.get("content")
                if isinstance(content, str):
                    out.append(content)
        return out


def _stub_api_key(monkeypatch: Any) -> None:
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "sk-stub")


def _parse_sse(raw: str) -> List[Dict[str, Any]]:
    """把 SSE 文本解析成事件列表（帧以空行分隔，只认 `data:` 行）。"""
    events: List[Dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        lines = [ln for ln in frame.split("\n") if ln.startswith("data:")]
        if not lines:
            continue
        events.append(json.loads(lines[0][len("data:") :].strip()))
    return events


def test_ai_polish_response_carries_convergence_contract(client, monkeypatch):
    """只增不改：两个端点的 `result` 新增 converged / unconverged_reason，既有字段不动。"""
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"], "error_count": 1}]
    )
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["corrected_text"] == "Ich habe einen Hund. Er ist gut."
    assert result["notes_zh"] == ["ein → einen"]
    # error_count 今天仍是**模型报的数**（既有断言 test_ai_polish_diff_mocked 的口径），
    # 换成裁判口径会静默破坏既有契约。
    assert result["error_count"] == 1
    assert result["converged"] is True
    assert result["unconverged_reason"] is None

    diff = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT}).json()["result"]
    assert diff["original"] == _ESSAY_TEXT
    assert diff["corrected"] == "Ich habe einen Hund. Er ist gut."
    assert diff["hunks"], "diff 端点仍要给出逐句 hunk（既有逐 hunk 采纳 UI 依赖它）"
    assert diff["converged"] is True
    assert diff["unconverged_reason"] is None


def test_ai_polish_no_key_reports_endpoint_level_reason(client, monkeypatch):
    """无 Key ⇒ 循环**根本没跑** ⇒ 端点层原因码 `no_api_key`（不进 REASONS）。"""
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["corrected_text"] == "Hallo."
    assert "DeepSeek API Key" in result["notes_zh"][0]
    assert result["error_count"] == 0
    assert result["converged"] is False
    assert result["unconverged_reason"] == "no_api_key"
    assert "no_api_key" not in polish_loop.REASONS, (
        "no_api_key 是端点层原因码（循环没跑），混进 REASONS 会让「原因码 = 循环出口」这条契约失真"
    )


def test_ai_polish_non_letter_grammar_error_is_counted_by_the_loop(client, monkeypatch):
    """★ Task 7 闸门收窄（**三态死绿守卫的改写其一**）：非书信体 + 语法错 ⇒ 语法违规**真被计数**。

    场景：桩模型改了措辞但**不修**冠词错（`ein Hund` 原样保留）⇒ v_0 == v_1 == 1 ⇒
    `no_improvement`（语法违规进了 v 才会发生）。

    判别力（变异自证②）：把闸门改回"非书信体一律零违规" ⇒ v_0 == v_1 == 0 ⇒ 首轮即收敛
    ⇒ 本用例 MUST 红 —— 旧闸门下的行为就是"零违规"，本用例的存在即"真被计数"与它的对比。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe ein Hund. Er ist sehr lieb.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["converged"] is False, "非书信体的语法违规 MUST 被计数（否则修不动也会被判收敛）"
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")
    assert result["judge_degraded"] is False


def test_ai_polish_non_letter_unfixable_falls_back_to_original(client, monkeypatch):
    """★ 产品语义钉子（**三态死绿守卫的改写其二**；ADR §10.3 的落点，MUST 有断言）：
    非书信体语法错**修不动** ⇒ 回退**原文**（**不是**"首轮即接受"）。

    这是闸门收窄后的**明知而接受**的行为（2026-10-15 用户拍板；同款登记在
    `violations_for` 与 `_make_judge` 的 docstring）：循环按 Task 4 钉死的
    `no_improvement` 语义走 argmin ⇒ 原文；用户拿到的人话是前端
    `POLISH_REASON_COPY.no_improvement`（"AI 改了几轮仍没能减少硬性错误，已保留更接近原文的一版。"）。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe ein Hund. Er ist sehr lieb.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["corrected_text"] == _ESSAY_TEXT, "修不动 ⇒ 按循环语义回退原文（不是首轮即接受）"
    assert result["converged"] is False
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")


def test_ai_polish_letter_text_still_judged_by_a1_rules(client, monkeypatch):
    """反向对照：书信体**不受**闸门豁免 ⇒ 改不动就照旧回退原文并给 no_improvement。

    少了这条，「闸门一律返回 []」也能让上一条变绿 —— 那等于把裁判整个关掉。
    """
    _stub_api_key(monkeypatch)
    # 改了用词但没修结语逗号 ⇒ v_1 == v_0 == 1 ⇒ 不降即停
    chat = _ScriptedChat([{"corrected_text": "Liebe Maria,\nich lade dich herzlich ein.\nViele Grüße,\nAnna"}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    result = client.post("/api/writing/ai-polish", json={"text": _LETTER_TEXT}).json()["result"]

    assert result["corrected_text"] == _LETTER_TEXT, "书信体改不动 ⇒ 回退原文（闸门必须对它失效）"
    assert result["converged"] is False
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")


# ── Task 1/2 评审 RED#1 闭环：端点级接线回归 + 引擎降级诚实性 ──────────────────
# 书信体 + 冠词格错（"ein Hund" → "einen Hund"）的文本夹具。
# 用**书信体**而非非书信体：RED#1 只要求"证明接缝是活的"，书信体已足够 ——
# 且能把本用例与 Task 7（HITL）的闸门收窄彻底解耦（非书信体的语法计数属 Task 7，此处不碰）。
# 该文本无任何**格式/字数族 error**（称呼语合法、正文首词小写、结语无逗号）
# ⇒ 不接 nlp 时 v_0 == 0（这是本用例能判死"没接线"的前提）。
_GRAMMAR_LETTER_TEXT = "Liebe Maria,\nich habe ein Hund.\nViele Grüße\nAnna"


def _real_nlp_or_skip() -> Any:
    """加载真模型（沿用 `tests/test_writing_rules.py` 的 nlp fixture 惯例）；缺失 ⇒ skip。"""
    import spacy

    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


def test_ai_polish_endpoint_counts_grammar_violations_on_letter_text(client, monkeypatch):
    """★ 评审 RED#1 闭环点：端点级接线回归 —— 生产链路 MUST 把语法裁判真的送进循环。

    用**书信体 + 冠词格错**文本（书信体 ⇒ 闸门不豁免 ⇒ 语法违规照常计数）：
    桩模型**不修**该冠词错 ⇒ v_0 == v_1 == 1 ⇒ `no_improvement`（断言形态①：语法违规真被计数）。
    若端点**不注入** `judge=`（退回内核默认裁判，不带 nlp）⇒ 语法违规静默消失，而该书信体文本
    又无格式 error ⇒ v_0 == v_1 == 0 ⇒ **首轮即收敛** ⇒ 本用例 MUST 红（这就是 dead-green 的判别力）。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    # 桩模型只改结尾措辞、**不修**冠词错 ⇒ 裁判应判「改不动」
    chat = _ScriptedChat(
        [{"corrected_text": "Liebe Maria,\nich habe ein Hund und freue mich.\nViele Grüße\nAnna", "notes_zh": ["x"]}]
    )
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish", json={"text": _GRAMMAR_LETTER_TEXT}).json()["result"]

    assert result["converged"] is False, "带冠词格错的书信体文本不该被判为已收敛"
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable"), (
        "语法违规 MUST 被计数（否则端点没把语法裁判送进循环 = dead-green）"
    )
    assert result["judge_degraded"] is False, "引擎可用 ⇒ judge_degraded 必须为 False"


def test_ai_polish_endpoint_reports_degraded_when_no_nlp(client, monkeypatch):
    """引擎不可用 ⇒ 循环**照常收敛**（运行期 fail-open），但 `judge_degraded` MUST 如实为 True。

    红线 1：不得让「没检查」看起来像「检查通过」⇒ 声明层 fail-closed 靠这个布尔透出。
    """
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    result = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["judge_degraded"] is True
    # 降级不阻止收敛（fail-open）：非书信体 + 无语法裁判 ⇒ 首轮即接受
    assert result["converged"] is True


def test_ai_polish_endpoint_surfaces_advisories_without_blocking_convergence(client, monkeypatch):
    """★ Task 6 HITL 收尾（B 维 advisory 可见性）：`judge_advisories` MUST 到达响应体，
    且 advisory **不阻断收敛** —— 判定与「去掉该句」逐字段相同。

    判别力（变异自证①）：把 advisory 的 level 改成 error ⇒ 它翻进 error 计数 ⇒
    v_0 == v_1 == 1 ⇒ no_improvement ⇒ 本用例的 `converged is True` 与
    `unconverged_reason is None` 断言 MUST 红。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    text_with = "Gestern gehe ich zur Schule."
    text_without = "Ich gehe zur Schule."

    # 桩模型「不修任何东西」：候选 = 原文 ⇒ 本用例只观察判定不受 advisory 影响。
    chat_with = _ScriptedChat([{"corrected_text": text_with, "notes_zh": []}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat_with)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)
    res_with = client.post("/api/writing/ai-polish", json={"text": text_with}).json()["result"]

    chat_without = _ScriptedChat([{"corrected_text": text_without, "notes_zh": []}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat_without)
    res_without = client.post("/api/writing/ai-polish", json={"text": text_without}).json()["result"]

    assert res_with["judge_advisories"], "B 维 advisory MUST 到达响应体（否则 warning 是 no-op）"
    assert all(isinstance(a, str) for a in res_with["judge_advisories"])
    assert any("过去" in a for a in res_with["judge_advisories"]), (
        f"advisory 文案应解释时间锚与时态冲突: {res_with['judge_advisories']}"
    )
    assert res_without["judge_advisories"] == [], "对照组不得有 advisory（防断言恒真）"
    assert res_with["converged"] is True and res_with["unconverged_reason"] is None
    assert res_with["judge_degraded"] is False
    # 「与去掉该句逐字相同」：advisory 不得进 error 计数、不得改变停止策略。
    assert (res_with["error_count"], res_with["converged"], res_with["unconverged_reason"]) == (
        res_without["error_count"],
        res_without["converged"],
        res_without["unconverged_reason"],
    ), "advisory 影响了判定（警告被当成错误计数？）"


def test_ai_polish_response_carries_judge_advisories_contract(client, monkeypatch):
    """响应契约（只增不改）：无 Key 路径也要带 `judge_advisories: []`（前端消费不炸）。"""
    monkeypatch.setattr("delector.routes.writing.get_effective_api_key", lambda *a, **k: "")

    result = client.post("/api/writing/ai-polish", json={"text": "Hallo."}).json()["result"]

    assert result["judge_advisories"] == []
    assert result["judge_degraded"] is True


# ── Task 7：文本族感知的提示词参数化（立论冲突解法 b；业务知识住产品层）──────────


def test_pick_system_prompt_letter_vs_prose():
    """提示词选择：书信体 ⇒ 既有 A1 提示词**逐字**；散文 ⇒ 不含称呼语/结语指令。

    为什么散文版必须去书信指令（评审黄卡 #2）：内核里逐字 A1 书信指令对非书信体会
    **诱导模型加一个称呼语**，而格式族规则此时已被闸门关掉 ⇒ 污染无守卫。
    """
    from delector.routes.main import POLISH_PROSE_SYSTEM_PROMPT, pick_system_prompt

    letter_prompt = pick_system_prompt("letter")
    prose_prompt = pick_system_prompt("prose")

    assert letter_prompt == polish_loop.POLISH_LOOP_SYSTEM_PROMPT, "书信体 MUST 用既有 A1 提示词（逐字）"
    assert prose_prompt == POLISH_PROSE_SYSTEM_PROMPT, "散文体 MUST 用散文向提示词（产品层常量）"
    assert prose_prompt != letter_prompt
    assert "称呼语" not in prose_prompt and "结语" not in prose_prompt, "散文提示词不得含称呼语/结语指令"
    assert "逐句润色" in prose_prompt and "保持句子的结构与出现顺序" in prose_prompt, "diff 关键约束 MUST 保留"
    assert "corrected_text" in prose_prompt, "JSON 契约 MUST 保留（循环按它解析）"


def test_run_polish_passes_text_family_aware_system_prompt(monkeypatch):
    """装配点：`_run_polish` MUST 按文本族把系统提示词**真的送进循环**（否则参数化是死代码）。

    判别力（变异自证③）：`pick_system_prompt` 恒返回 A1 提示词 ⇒ 本用例第一条断言（散文
    提示词）MUST 红。
    """
    from delector.routes.main import POLISH_PROSE_SYSTEM_PROMPT, _run_polish

    captured: List[Dict[str, Any]] = []

    async def _fake_loop(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return polish_loop.LoopResult(text=kwargs["text"], converged=True, reason="ok", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", _fake_loop)
    monkeypatch.setattr("delector.routes.writing.get_effective_api_base_url", lambda: "http://stub")
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    essay = "Ich habe ein Hund. Er ist gut."
    letter = "Liebe Maria,\nich lade dich ein.\nViele Grüße\nAnna"
    asyncio.run(_run_polish(essay, "sk-stub"))
    asyncio.run(_run_polish(letter, "sk-stub"))

    assert captured[0]["system_prompt"] == POLISH_PROSE_SYSTEM_PROMPT, (
        "非书信体 ⇒ 散文提示词 MUST 真送进循环（参数化不许是死代码）"
    )
    assert captured[1]["system_prompt"] == polish_loop.POLISH_LOOP_SYSTEM_PROMPT, "书信体 ⇒ 既有 A1 提示词"


def test_writer_js_surfaces_degraded_hint_and_advisories_without_toast():
    """前端生产者（评审黄卡的闭环）：`judge_degraded` / `judge_advisories` MUST 被
    writer.js 消费，且走 **overlay notes 区的非阻断呈现**（Global Constraints 明说
    "不是 error toast"）。

    与 `test_frontend_polish_reason_copy_covers_every_reason_code` 同为源码级守卫：
    后端加了字段而前端不渲染 ⇒ 字段等于没加（这正是评审黄卡点名的"无生产者"）。

    no-key 抑制（评审黄卡 Y3 的闭环）：no-key 路径**循环根本没跑**（`_no_key_outcome`
    什么都没检查）⇒ 降级提示里"本次仅做格式/字数检查"不实 ⇒ `unconverged_reason ==
    "no_api_key"` 时 MUST 抑制该提示（no-key 已有自己的 toast / notes 文案，抑制不丢信息）。
    """
    src = read_source("static/js/writer.js")
    assert "judge_advisories" in src, "writer.js MUST 消费 judge_advisories（advisory 可见性）"
    assert "judge_degraded" in src, "writer.js MUST 消费 judge_degraded（降级可见性）"

    # 结构性取体（替代「切到下一条横幅注释」）：那条横幅会随被抽出的纯层一起搬家，
    # 而 decl_body 按花括号配平取 renderPolishReview 的函数体 —— 判别力只升不降
    # （旧写法把「函数尾」到「下一条横幅」之间的所有缝隙也算进块内）。
    render_block = decl_body(src, "export function renderPolishReview()")
    assert "polishState.judge_advisories" in render_block, "advisory MUST 在 renderPolishReview 里逐条呈现"
    assert "polishState.judge_degraded" in render_block, "降级提示 MUST 在 renderPolishReview 里呈现"
    assert "语法检查未启用" in render_block, "降级提示 MUST 是一句可见的人话（非阻断，不是 toast）"
    assert (
        "polishState.judge_degraded && polishState.unconverged_reason !== 'no_api_key'" in render_block
    ), "no-key 路径循环根本没跑 ⇒ 提示 MUST 受 unconverged_reason 守卫（否则'仅做格式/字数检查'不实）"

    # 生产侧（抑制条件的输入）：响应装配 MUST 把 unconverged_reason 存进 polishState
    assign = src[src.index("const { original, corrected, hunks, notes_zh"):]
    assert "unconverged_reason" in assign[: assign.index("};")], (
        "polishState MUST 携带 unconverged_reason（no-key 抑制分支的输入）"
    )


def test_get_loaded_nlp_is_read_only(monkeypatch):
    """`get_loaded_nlp()` 只读已加载模型：未解析/加载失败 ⇒ None，且**绝不触发加载**。"""
    from delector.nlp_engine import processor

    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)
    calls = {"n": 0}

    def _spy(name: str) -> Any:
        calls["n"] += 1
        raise RuntimeError("不应被调用")

    monkeypatch.setattr(processor, "_load_spacy_model", _spy)

    assert processor.get_loaded_nlp() is None
    assert calls["n"] == 0, "get_loaded_nlp 不得触发任何加载"

    sentinel = object()
    monkeypatch.setattr(processor, "_nlp_resolved", True)
    monkeypatch.setattr(processor, "_nlp_model", sentinel)
    assert processor.get_loaded_nlp() is sentinel


def test_try_load_nlp_no_download_loads_locally(monkeypatch):
    """本地能加载 ⇒ 写入既有缓存（`_nlp_model` / `_nlp_resolved=True`）并返回模型。"""
    from delector.nlp_engine import processor

    sentinel = object()
    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)
    monkeypatch.setattr(processor, "_load_spacy_model", lambda name: (sentinel, f"{name}(stub)"))

    assert processor.try_load_nlp_no_download() is sentinel
    assert processor.get_loaded_nlp() is sentinel


def test_try_load_nlp_no_download_never_downloads(monkeypatch):
    """★ 变异守卫：本地加载全失败 ⇒ MUST 返回 None，且**绝不**触发 `spacy.cli.download`。

    把 `try_load_nlp_no_download` 改成会走 download 的版本 ⇒ 本地加载既已失败，爆炸桩
    `spacy.cli.download` 会被命中 ⇒ 本用例红线。
    """
    from spacy import cli as spacy_cli

    from delector.nlp_engine import processor

    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)

    def _boom(name: str) -> Any:
        raise RuntimeError("no local model")

    monkeypatch.setattr(processor, "_load_spacy_model", _boom)

    def _bomb(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("try_load_nlp_no_download 绝不能触发 spacy.cli.download（出网 + pip）")

    monkeypatch.setattr(spacy_cli, "download", _bomb)

    assert processor.try_load_nlp_no_download() is None, "本地失败 ⇒ 诚实返回 None（不抛、不下载）"
    assert processor.get_loaded_nlp() is None, "失败 ⇒ 不写任何全局"


def test_ai_polish_runs_tool_hooks_on_the_real_path(client, monkeypatch, caplog):
    """前置钩子链 MUST 在**真链路**上被跑过（不是只在单测里）：审计留痕 + 证据回喂。"""
    import logging

    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [
            {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}},
            {"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"]},
        ]
    )
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    with caplog.at_level(logging.INFO):
        res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})

    assert res.status_code == 200
    audited = [r.getMessage() for r in caplog.records if "writing_check" in r.getMessage()]
    assert audited, f"审计钩子没在真链路上留下痕迹（logs={[r.getMessage()[:80] for r in caplog.records]}）"
    assert any(c.startswith("[工具结果:writing_check]") for c in chat.contents()), (
        "工具结果必须作为证据回喂给模型（证明 dispatch 走的是白名单真身）"
    )


def test_ai_polish_stream_emits_progress_then_full_result(client, monkeypatch):
    """`stream=true` ⇒ SSE：逐轮进度事件 + 收尾 `done` + 最后一条完整 result。

    TestClient 的传输层会把**整个响应**缓冲完再返回（starlette 1.6 的
    `_TestClientTransport.handle_request` 一次性跑完 ASGI app），故这里断言的是
    「帧序列正确」，不是「帧是增量到达的」——增量与断连由下一条用例直接驱动生成器覆盖。
    """
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [
            {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}},
            {"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"], "error_count": 1},
        ]
    )
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})

    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    events = _parse_sse(res.text)
    assert events, f"SSE 帧为空：{res.text[:200]!r}"
    assert events[-1]["event"] == "result", f"最后一条必须是完整 result：{events[-1]}"
    done = [e for e in events if e.get("event") == "done"]
    assert done and done[-1]["converged"] is True and done[-1]["reason"] == "ok"
    progress = [e for e in events if e.get("event") == "tool"]
    assert progress, "取证的那一轮必须吐进度事件"
    assert progress[0]["max_turns"] == polish_loop.MAX_TURNS_DEFAULT, "max_turns 必须由服务端给出（前端不许硬编码）"
    assert progress[0]["round"] >= 1
    payload = events[-1]["result"]
    assert payload["corrected"] == "Ich habe einen Hund. Er ist gut."
    assert payload["hunks"]
    assert payload["converged"] is True
    assert payload["unconverged_reason"] is None


def test_ai_polish_feedback_and_prose_routing(client: Any, monkeypatch: Any) -> None:
    """Task 4: 端到端路由接入与分流透传。

    散文体裁（prose）在多轮润色中：
    1. 发生违规时，SSE 流中吐出 event == "judge_feedback" 事件；
    2. 反馈内容严格遵循 text_type="prose" 过滤，绝不包含 a1_ 书信格式规则（如 a1_greeting_missing）；
    3. 模型依据反馈修正后，最终成功收敛 (converged=True, reason="ok")。
    """
    _stub_api_key(monkeypatch)

    chat = _ScriptedChat(
        [
            {"corrected_text": "Ich gehe nach Schule.", "notes_zh": ["in -> nach"]},
            {"corrected_text": "Ich gehe in die Schule.", "notes_zh": ["nach -> in die"]},
        ]
    )
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    def _fake_make_judge(leitpunkte: Any, nlp: Any) -> Any:
        def _judge(text: str) -> Dict[str, Any]:
            if "nach Schule" in text:
                return {
                    "word_count": 5,
                    "greeting": {"valid": True},  # 候选含格式特征，由 text_type="prose" 守门过滤
                    "violations": [
                        {"rule": "a1_greeting_missing", "level": "error", "message": "书信缺少称呼语"},
                        {"rule": "grammar_error", "level": "error", "message": "语法错误"},
                    ],
                }
            elif "in Schule" in text:
                # 原文基线：维持 prev_v >= 2，使首轮违规数不恶化并触发反馈机制
                return {
                    "word_count": 5,
                    "greeting": {"valid": False},
                    "violations": [
                        {"rule": "grammar_error", "level": "error", "message": "语法错误"},
                        {"rule": "spelling_mistake", "level": "error", "message": "拼写错误"},
                    ],
                }
            return {"word_count": 5, "greeting": {"valid": False}, "violations": []}

        return _judge

    monkeypatch.setattr("delector.routes.writing._make_judge", _fake_make_judge)

    res = client.post("/api/writing/ai-polish", json={"text": "Ich gehe in Schule.", "stream": True})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse(res.text)
    assert events, f"SSE 帧为空：{res.text[:200]!r}"

    # a) In SSE stream, an event with event == "judge_feedback" is emitted.
    fb_events = [e for e in events if e.get("event") == "judge_feedback"]
    assert fb_events, f"SSE 流中必须包含 judge_feedback 事件，实际事件: {[e.get('event') for e in events]}"

    # b) The feedback content does NOT contain a1_ letter format rules (e.g. a1_greeting_missing).
    feedback = fb_events[0]["feedback"]
    assert "grammar_error" in feedback
    assert "a1_greeting_missing" not in feedback
    assert "a1_" not in feedback, f"散文体裁反馈中严禁包含 a1_ 规则：{feedback}"

    # c) Final result converges or completes successfully.
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events and done_events[-1]["converged"] is True and done_events[-1]["reason"] == "ok"
    assert events[-1]["event"] == "result"
    assert events[-1]["result"]["corrected_text"] == "Ich gehe in die Schule."
    assert events[-1]["result"]["converged"] is True


def test_ai_polish_stream_defaults_off_and_keeps_json(client, monkeypatch):
    """`stream` 默认关：不传就是既有 JSON 行为（既有测试逐字不变的前提）。"""
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})

    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["result"]["corrected_text"] == "Ich habe einen Hund. Er ist gut."


def test_ai_polish_stream_cancels_loop_when_client_disconnects(monkeypatch):
    """客户端中途断开 ⇒ 服务端循环任务被 `cancel()`（不泄漏、不继续烧配额）。

    为什么不用 TestClient：它的传输层把整个响应缓冲完才返回（实测见上一条用例注释），
    `request.is_disconnected()` 在响应生成期间恒为 False（httpx 的 receive() 要等
    response_complete）⇒ 「中途断开」在 TestClient 下**物理上无法复现**。
    故这里直接驱动端点的流式生成器，配一个「第 2 轮 chat 卡住时才报已断开」的 Request 桩；
    其余链路（chat 桩、白名单、钩子、循环）全是真的。
    """
    gate = asyncio.Event()
    entered_second_call = asyncio.Event()
    state = {"calls": 0, "cancelled": False}

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            return {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}}
        entered_second_call.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return {"corrected_text": _ESSAY_TEXT}

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", _chat)

    class _DisconnectedRequest:
        """仅提供端点用到的两个面：`client.host`（本机闸）与 `is_disconnected()`。"""

        client = type("Client", (), {"host": "127.0.0.1"})

        async def is_disconnected(self) -> bool:
            return entered_second_call.is_set()

    async def _drive() -> Dict[str, Any]:
        resp = await api_writing_ai_polish(AIPolishReq(text=_ESSAY_TEXT, stream=True), _DisconnectedRequest())

        async def _drain() -> str:
            raw = ""
            async for chunk in resp.body_iterator:
                raw += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            return raw

        # 上限 5s：取消逻辑被抽掉时生成器会永远轮询 ⇒ 宁可**红**也不要挂住整轮门禁。
        raw = await asyncio.wait_for(_drain(), timeout=5.0)
        # 快照必须在**事件循环关掉之前**取：asyncio.run() 收尾会顺手 cancel 掉所有
        # 未完成任务，那时再读 cancelled 恒为真 ⇒ 断言会变成假绿。
        return {
            "events": _parse_sse(raw),
            "cancelled": state["cancelled"],
            "calls": state["calls"],
        }

    snap = asyncio.run(_drive())

    assert snap["cancelled"] is True, "断开后服务端循环 MUST 被取消（否则继续烧配额）"
    assert snap["calls"] < polish_loop.MAX_TURNS_DEFAULT, (
        f"取消后不该继续跑满轮次：calls={snap['calls']} / max={polish_loop.MAX_TURNS_DEFAULT}"
    )
    assert all(e.get("event") != "result" for e in snap["events"]), "已断开就不该再产出完整 result"


def test_ai_polish_stream_cancels_loop_when_starlette_listener_preempts(monkeypatch):
    """starlette 的 `listen_for_disconnect` **抢先**取消生成器 ⇒ finally 同步收尸掐断在途 chat。

    与上一条用例的分工（为什么必须单开这条）：
    - 上一条直接迭代 `resp.body_iterator`，**绕开了** `StreamingResponse.__call__`
      ⇒ `listen_for_disconnect` 根本不参与，「监听器抢先 cancel 生成器」这条路
      物理上测不到；
    - 这里直接驱动 `StreamingResponse.__call__`：uvicorn 的 HTTP 协议栈（h11 /
      httptools impl，实测源码 `spec_version='2.3'`）⇒ starlette 1.6 的 `__call__`
      走 task-group 分支（`spec_version < (2, 4)`）：`stream_response` 与
      `listen_for_disconnect` **同时**跑。断连从监听器那条路进来：receive 第 2 次
      被调用 ⇒ 返回 `http.disconnect` ⇒ 监听器 break ⇒
      `task_group.cancel_scope.cancel()` ⇒ `stream_response` 里的生成器在 await 点
      被投递 `CancelledError` ⇒ 生成器的 `finally` 必须**同步** `task.cancel()`
      把在途 chat 掐断；
    - 生成器的 request 桩 `is_disconnected()` 恒 False：堵死「轮询自报断开」那条路，
      确保取消只能来自监听器 —— 把 `finally` 里的 `task.cancel()` 抽掉，本用例必红
      （变异自证）。
    """
    gate = asyncio.Event()
    entered_second_call = asyncio.Event()
    cancelled_seen = asyncio.Event()
    state = {"calls": 0, "cancelled": False}

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            return {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}}
        entered_second_call.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            cancelled_seen.set()
            raise
        return {"corrected_text": _ESSAY_TEXT}

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.routes.writing.llm_client.chat", _chat)

    class _NeverDisconnectedRequest:
        """生成器只用得到 `is_disconnected()`：恒 False ⇒ 取消只能来自 starlette 监听器。"""

        async def is_disconnected(self) -> bool:
            return False

    async def _drive() -> Dict[str, Any]:
        resp = StreamingResponse(
            _polish_event_stream(request=_NeverDisconnectedRequest(), text=_ESSAY_TEXT, with_diff=False),
            media_type="text/event-stream",
        )
        receive_calls = {"n": 0}

        async def receive() -> Dict[str, Any]:
            receive_calls["n"] += 1
            if receive_calls["n"] == 1:
                # 首条非断连消息：监听器只在拿到 http.disconnect 时才 break
                return {"type": "http.request", "body": b"", "more_body": False}
            # 第 2 次被调用才报断开 —— 但先等循环真的跑起来（第 2 次 chat 已卡在途），
            # 把取消钉在「流已开头、在途 chat 进行中」这个真实窗口，避开生成器还没
            # 起步的竞态窗口（那时取消可能整段跳过生成器体，finally 无从谈起）。
            await entered_second_call.wait()
            return {"type": "http.disconnect"}

        sent: List[Dict[str, Any]] = []

        async def send(message: Dict[str, Any]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/writing/ai-polish",
            "raw_path": b"/api/writing/ai-polish",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 51234),
            "server": ("127.0.0.1", 8000),
        }

        # 取消沿 task group 回传：resp(...) 可能原样抛出 CancelledError（starlette 用
        # create_collapsing_task_group 折叠单异常组），压掉即可 —— 断言看的是收尸效果。
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(resp(scope, receive, send), timeout=10.0)

        # finally 只同步 cancel、不 await：给事件循环节拍让取消真正传导到在途 chat。
        # 上限 5s：finally 的 cancel 被抽掉时在途 chat 会永远卡住 ⇒ 宁可红也不挂死门禁。
        try:
            await asyncio.wait_for(cancelled_seen.wait(), timeout=5.0)
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True

        bodies = b"".join(m.get("body", b"") for m in sent if m.get("type") == "http.response.body")
        return {
            "started": bool(sent) and sent[0].get("type") == "http.response.start",
            "receive_calls": receive_calls["n"],
            "frames": _parse_sse(bodies.decode("utf-8")),
            "cancelled": state["cancelled"],
            "calls": state["calls"],
            "timed_out": timed_out,
        }

    snap = asyncio.run(_drive())

    assert snap["started"], "stream_response 必须真跑过（证明驱动的是 StreamingResponse.__call__ 而非裸生成器）"
    assert snap["receive_calls"] >= 2, f"监听器必须真参与（receive 被调用次数={snap['receive_calls']}）"
    assert not snap["timed_out"], "finally 必须收尸：在途 chat 5s 内没收到 CancelledError（cancel 被抽掉？）"
    assert snap["cancelled"] is True, "finally MUST 同步 task.cancel()（否则在途 chat 裸跑烧配额）"
    assert snap["calls"] < polish_loop.MAX_TURNS_DEFAULT, (
        f"取消后不该继续跑满轮次：calls={snap['calls']} / max={polish_loop.MAX_TURNS_DEFAULT}"
    )
    assert all(e.get("event") != "result" for e in snap["frames"]), "已断开就不该再产出完整 result"


def test_ai_polish_stream_error_frame_carries_llm_detail(client, monkeypatch):
    """接缝③：流已开头 ⇒ 上游 LLMError MUST 以 **error 帧**抵达用户（`e.detail` 人话）。

    事实链：`_run_polish` 捕获 `llm_client.LLMError` 后 `raise HTTPException(502, detail=e.detail)`
    ⇒ 流层原本写的 `except llm_client.LLMError` **永不命中** ⇒ error 帧永不发出 ⇒ 用户只拿到
    前端那句通用「润色流结束但没有返回结果」。修法选 **(b) 流层捕获 `HTTPException`**：
    `_run_polish` 的契约对两种调用方保持同一形状（失败 ⇒ HTTPException(502)），流已经开了头
    改不了状态码，只能在流内用 error 帧把人话送出去；前端 `writer.js` 也早已按
    `ev.event === 'error'` / `ev.detail` 消费。
    """
    from delector.services import llm_client

    _stub_api_key(monkeypatch)
    # 裁判引擎 deliberately 置为不可用：本条只关心「错误怎么抵达用户」，
    # 让 chat 第一轮就抛，别把时间花在加载真 spaCy 模型上。
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        raise llm_client.LLMError("DeepSeek 服务暂时不可用 (503)")

    monkeypatch.setattr("delector.routes.writing.llm_client.chat", _chat)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})

    assert res.status_code == 200
    events = _parse_sse(res.text)
    errors = [e for e in events if e.get("event") == "error"]
    assert errors, f"上游失败 MUST 以 error 帧抵达用户，实际帧：{events}"
    assert "DeepSeek 服务暂时不可用 (503)" in errors[0]["detail"], f"error 帧 MUST 带 e.detail 人话：{errors[0]}"
    assert all(e.get("event") != "result" for e in events), "失败路径不该再产出 result 帧"


def test_ai_polish_records_and_uses_real_usage_tokens(client: Any, monkeypatch: Any) -> None:
    """生产端点 Usage 权威透出与精确计量接入。

    断言：
    - _PolishReplyRecorder 初始化 self.usage = None；
    - _PolishReplyRecorder.__call__ 透传 include_usage=True 给 llm_client.chat；
    - _PolishReplyRecorder 捕获 recorder.usage == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}；
    - 在 SSE 流中，tokens_used 消费恰好 50 tokens（来自 usage.completion_tokens），而非字符估算。
    """
    from delector.routes import writing as routes_writing

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    # 1. 验证单元层面 recorder 初始态与 _capture 行为
    unit_recorder = routes_writing._PolishReplyRecorder("test-key", "https://api.deepseek.com")
    assert unit_recorder.usage is None

    chat_calls: List[Dict[str, Any]] = []

    async def mock_chat(**kwargs: Any) -> Dict[str, Any]:
        chat_calls.append(kwargs)
        payload: Dict[str, Any] = {
            "corrected_text": "Ich habe einen Hund. Er ist gut.",
            "notes_zh": ["ein → einen"],
            "error_count": 0,
        }
        if kwargs.get("include_usage"):
            payload["usage"] = {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        return payload

    monkeypatch.setattr("delector.routes.writing.llm_client.chat", mock_chat)

    captured_recorders: List[Any] = []
    original_recorder_cls = routes_writing._PolishReplyRecorder

    class _SpyRecorder(original_recorder_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            captured_recorders.append(self)

    monkeypatch.setattr("delector.routes.writing._PolishReplyRecorder", _SpyRecorder)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})
    assert res.status_code == 200

    # a) _PolishReplyRecorder 捕获 recorder.usage
    assert len(captured_recorders) == 1
    recorder = captured_recorders[0]
    expected_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    assert recorder.usage == expected_usage

    # 透传断言：llm_client.chat 必须收到 include_usage=True
    assert len(chat_calls) >= 1
    assert chat_calls[0].get("include_usage") is True

    # b) SSE stream 中 tokens_used 恰好消费 50 tokens
    events = _parse_sse(res.text)
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, f"缺少 done 事件帧：{events}"
    assert done_events[0]["tokens_used"] == 50, (
        f"tokens_used 期望为精确 usage (50)，实际为 {done_events[0]['tokens_used']}"
    )


def test_frontend_polish_reason_copy_covers_every_reason_code():
    """writer.js 的中文文案 MUST 覆盖 `polish_loop.REASONS` 全部成员 + 端点层 no_api_key。

    将来往 REASONS 里加码而忘了配文案 ⇒ 这里立刻红（前端否则只能弹一句空话）。
    """
    src = read_source("static/js/wr-format.js", "static/js/writer.js")
    block = re.search(r"const POLISH_REASON_COPY\s*=\s*\{(.*?)\n\};", src, re.S)
    assert block, "writer.js 里找不到 POLISH_REASON_COPY 映射表"
    keys = set(re.findall(r"^\s*([a-z_]+)\s*:", block.group(1), re.M))
    expected = set(polish_loop.REASONS) | {"no_api_key"}
    assert keys == expected, (
        f"文案表与原因码集合不一致：缺 {sorted(expected - keys)}，多 {sorted(keys - expected)}"
    )


def test_frontend_polish_progress_takes_max_turns_from_server():
    """进度文案的轮次分母 MUST 取自服务端事件的 `max_turns`，不许前端写死 3。"""
    src = read_source("static/js/writer.js")
    body = decl_body(src, "export async function aiPolishEssay()")
    assert "AbortController" in body, "取消必须有 AbortController（或等价机制）"
    # `"max_turns" in body` 曾被注释里那句「轮次分母取自服务端事件的 max_turns」满足
    # ——变异实测（把 `ev.max_turns || ev.round` 换成字面量 3）当时**不会变红**。
    # 故收紧为「必须真的读 `ev.max_turns` 字段」：只出现在注释里不算。
    assert "ev.max_turns" in body, "轮次分母必须真的读服务端事件字段 ev.max_turns（注释里提一句不算）"
    assert "/3 轮" not in body, "不许把轮次上界硬编码成 3（内核改 MAX_TURNS_DEFAULT 这里就撒谎）"
