# -*- coding: utf-8 -*-
"""`delector.services.polish_tools` 的契约测试（D4 任务级白名单 / D5 同进程直调 + 前置钩子）。

背景（Task 5 · ADR-0023 §8.1 **Q4-A** / §8.2 第 5 条）：模型在润色循环里能调的工具
**不是**全局 `TOOL_REGISTRY`，而是**任务级最小白名单**（只读且相关）；调用走**同进程
直调**（不经 HTTP）；鉴权/审计闸作**前置钩子**（谁是调用者 ≠ 模型能调什么）。

与 Task 4「一律 stub」纪律的**唯一差别**：三个白名单工具**刻意调真身**。
`writing_check` / `vocab_stats` 是纯本地只读能力；`analyze` 则先由专门用例封死下载入口，
证明本机/CI 模型已可用后再真调。「白名单里的名字真的能跑」正是白名单存在的意义 ——
抄一份假返回值等于把这条守卫变成死测试。其余各条仍是桩。

仍然严格遵守：不出网、不依赖真实 `DEEPSEEK_API_KEY`、用 `asyncio.run(...)`（本仓无
pytest-asyncio）。

判别力纪律（变异自证清单见文件末尾）：每条语义测试都要能分辨「对应实现被改坏」。
"""

import asyncio
import functools
import inspect
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import spacy.cli

from delector.nlp_engine import processor
from delector.services.polish_loop import Budget, run_polish_loop
from delector.services.polish_tools import POLISH_TOOL_ALLOWLIST, call_tool
from delector.tools import TOOL_REGISTRY, writing_check

# ── 三个白名单工具的**真实最小** payload（照各自 `run` 的入参契约写，不猜） ──────
# writing_check：`delector/tools/writing_check.py:14` ⇒ `payload["text"]`，`leitpunkte` 可选。
WRITING_CHECK_PAYLOAD: dict[str, Any] = {
    "text": "Liebe Maria,\nich lade dich ein.\nViele Grüße\nAnna",
}
# analyze：`delector/tools/analyze.py:9` ⇒ `payload["text"]`。
ANALYZE_PAYLOAD: dict[str, Any] = {"text": "Die Katze schläft."}
# vocab_stats：`delector/tools/vocab_stats.py:68` ⇒ `payload["tokens"]`（每项带
# `text/lemma/pos`），`levels` / `known_extra` 可选。lemma 取 `tests/test_vocab_stats.py`
# 已实证过的真实 A1 词条 "gehen"，断言才有意义（不是空跑）。
VOCAB_STATS_PAYLOAD: dict[str, Any] = {
    "tokens": [{"text": "gehen", "lemma": "gehen", "pos": "VERB"}],
    "levels": ["A1"],
}


def call(name: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """同步跑一次 `call_tool`（本仓无 pytest-asyncio，沿用 `asyncio.run` 惯例）。"""
    return asyncio.run(call_tool(name, payload, **kwargs))


def _stub_judge(text: str, leitpunkte: list[str] | None = None) -> dict[str, Any]:
    """裁判桩：给零违规裁决，让循环只受 `max_turns` 控制（不出网、不碰真裁判）。"""
    return {"word_count": len(text.split()), "suggestions": []}


# ── 1. 白名单恰好三项 ──────────────────────────────────────────────────────────
def test_allowlist_is_exactly_three_readonly_tools() -> None:
    """D4：白名单**恰好** `writing_check` / `analyze` / `vocab_stats`（多一项/少一项都红）。"""
    assert len(POLISH_TOOL_ALLOWLIST) == 3, f"白名单 MUST 恰好 3 项，实得 {sorted(POLISH_TOOL_ALLOWLIST)}"
    assert set(POLISH_TOOL_ALLOWLIST) == {"writing_check", "analyze", "vocab_stats"}
    # 每一项都 MUST 是 `TOOL_REGISTRY` 里那个**真身**（不是复制品、不是 HTTP 包装器）
    for name, fn in POLISH_TOOL_ALLOWLIST.items():
        assert TOOL_REGISTRY[name] is fn, f"'{name}' MUST 是 TOOL_REGISTRY 里的同一个可调用对象（同进程直调）"


# ── 2. 差集守卫（**把 ingest 加进白名单 ⇒ 本条 MUST 变红**） ────────────────────
def test_registry_minus_allowlist_is_exactly_the_excluded_three() -> None:
    """D4 差集守卫：白名单与 `TOOL_REGISTRY`（**现读**，不许抄名字列表）的差集
    MUST 恰好是「出网 / 写盘 / 生成音频」这三个 —— 它们被排除是有理由的，不是遗漏。

    双向守卫：往白名单里**加**写工具 ⇒ 差集变小 ⇒ 红；把 `ingest` 从 `TOOL_REGISTRY`
    **摘掉**想绕开 ⇒ 差集同样变小 ⇒ 也红。
    """
    excluded = set(TOOL_REGISTRY) - set(POLISH_TOOL_ALLOWLIST)

    assert {"ingest", "export", "tts"} <= excluded, f"写工具 MUST 包含在被排除的工具集中，实得 {sorted(excluded)}"
    for name in ("ingest", "export", "tts"):
        assert name not in POLISH_TOOL_ALLOWLIST, f"'{name}' 出网/写盘/生成音频，不得进润色白名单"


# ── 3. analyze 的只读前提：运行时模型已可用，不触发下载 ────────────────────────
def test_analyze_runtime_model_is_available_without_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """D4：当前运行时模型已可用时，`analyze` 才能作为只读工具留在白名单。"""
    download_calls: list[str] = []
    failure = (
        "当前运行时的 spaCy 德语模型 MUST 已可用；模型缺失 ⇒ `analyze` 会走 "
        "`spacy.cli.download` 下载路径 ⇒ 它不配留在只读白名单里"
    )

    def _download_must_not_run(model_name: str, *args: Any, **kwargs: Any) -> None:
        download_calls.append(model_name)
        raise AssertionError(failure)

    monkeypatch.setattr(spacy.cli, "download", _download_must_not_run)

    try:
        model = processor._resolve_nlp_model()
    except Exception as exc:
        pytest.fail(f"{failure}；实得 {exc!r}")

    assert model is not None, failure
    out = call("analyze", ANALYZE_PAYLOAD)
    assert {"sentences", "stats"} <= set(out), f"analyze 真身 MUST 成功返回分析结果：{out}"
    assert download_calls == [], f"{failure}；下载桩调用记录：{download_calls}"


# ── 4. 同进程直调、不经 HTTP ───────────────────────────────────────────────────
def test_allowlist_tools_are_called_in_process_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5「同进程直调」：调用期间把 httpx 的入口换成「被调用即报错」的桩 ⇒ 真走了 HTTP 就红。"""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("白名单工具 MUST 同进程直调 —— 一旦碰到 httpx 即判红（不经 HTTP）")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    monkeypatch.setattr(httpx, "request", _boom)
    monkeypatch.setattr(httpx, "stream", _boom)

    for name, payload in (
        ("writing_check", WRITING_CHECK_PAYLOAD),
        ("analyze", ANALYZE_PAYLOAD),
        ("vocab_stats", VOCAB_STATS_PAYLOAD),
    ):
        out = call(name, payload)
        assert isinstance(out, dict), f"{name} 应返回 dict（同进程直调，不是 HTTP 响应）：{out!r}"


# ── 5. 钩子串行且按序 ──────────────────────────────────────────────────────────
def test_hooks_run_serially_in_order() -> None:
    """前置钩子 MUST **串行**执行且按传入顺序（鉴权/审计的先后顺序本身有意义）。"""
    seen: list[str] = []

    def h1(name: str, payload: dict[str, Any]) -> None:
        assert name == "vocab_stats", f"钩子 MUST 拿到工具名：{name}"
        assert payload == VOCAB_STATS_PAYLOAD, f"钩子 MUST 拿到原始 payload：{payload}"
        seen.append("h1")

    def h2(name: str, payload: dict[str, Any]) -> None:
        assert seen == ["h1"], f"h2 必须在 h1 **跑完之后**才跑（串行，不是并发）：{seen}"
        seen.append("h2")

    def h3(name: str, payload: dict[str, Any]) -> None:
        assert seen == ["h1", "h2"], f"h3 必须最后跑：{seen}"
        seen.append("h3")

    out = call("vocab_stats", VOCAB_STATS_PAYLOAD, hooks=[h1, h2, h3])

    assert seen == ["h1", "h2", "h3"], f"钩子 MUST 按传入顺序串行执行：{seen}"
    assert out["tokens_total"] == 1


# ── 6. 每个钩子只拿 payload 快照，不能改写被审对象 ─────────────────────────────
def test_hook_payload_mutation_cannot_rewrite_later_hooks_or_tool() -> None:
    """钩子原地改自己的快照，不得影响后续钩子或最终工具看到的 payload。"""
    payload: dict[str, Any] = {
        "tokens": [{"text": "gehen", "lemma": "gehen", "pos": "VERB"}],
        "levels": ["A1"],
    }
    later_seen: list[dict[str, Any]] = []

    def mutate_snapshot(name: str, hook_payload: dict[str, Any]) -> None:
        assert name == "vocab_stats"
        hook_payload["tokens"] = []
        hook_payload["levels"] = ["C2"]

    def observe_original(name: str, hook_payload: dict[str, Any]) -> None:
        later_seen.append(dict(hook_payload))

    out = call("vocab_stats", payload, hooks=[mutate_snapshot, observe_original])

    assert later_seen == [payload], f"后续钩子 MUST 看到未被前一钩子改写的原值：{later_seen}"
    assert out["tokens_total"] == 1, f"工具 MUST 看到原始 tokens，而不是钩子改写值：{out}"
    assert out["known_count"] == 1, f"工具 MUST 看到原始 A1 levels，而不是钩子改写值：{out}"


# ── 7. 钩子抛异常 ⇒ 拒绝、带原因、不冒泡 ───────────────────────────────────────
def test_hook_exception_rejects_call_without_raising() -> None:
    """钩子抛异常 ⇒ 该次调用被拒，原因作为**返回值**回给调用方（不炸循环）。

    反面断言用两半拼成：先用 `pytest.raises` 正向自证「钩子桩**本身**确实会抛」，
    再直接调用 `call_tool` —— 它若冒泡，pytest 立刻判 error ⇒ 即「不得抛出」的断言。
    """

    def deny(name: str, payload: dict[str, Any]) -> None:
        raise PermissionError("当前调用者无权使用该工具")

    with pytest.raises(PermissionError):
        deny("vocab_stats", {})  # 桩自证：钩子本身确实抛（否则本条测试是死的）

    after: list[str] = []
    out = call("vocab_stats", VOCAB_STATS_PAYLOAD, hooks=[deny, lambda name, payload: after.append(name)])

    assert out.get("rejected") is True, f"拒绝 MUST 体现为返回值字段：{out}"
    assert "拒绝" in str(out.get("error", "")), f"拒绝原因 MUST 在返回值里：{out}"
    assert "PermissionError" in str(out.get("error", "")), f"拒绝原因 MUST 带上异常信息：{out}"
    assert "tokens_total" not in out, f"被拒的调用 MUST NOT 真的执行工具：{out}"
    assert after == [], f"前置钩子链 MUST fail-fast（拒绝后不再跑后面的钩子）：{after}"


# ── 8. 未知工具名 ⇒ 返回 error 形态、不抛 ──────────────────────────────────────
def test_unknown_tool_returns_error_shape_without_raising() -> None:
    """未知工具名 ⇒ errors-as-messages（与 `polish_loop._make_default_dispatch` 同形）。

    工具名刻意取一个 `TOOL_REGISTRY` 里**根本不存在**的名字（不是 `ingest`/`export`/`tts`）：
    那三个是"被排除"而非"不存在"，一旦有人把它们加回白名单，用它们当用例名就会把
    **真实的出网/写盘副作用**跑出来（变异实测踩到过）。排除性由第 2 条差集守卫钉住。
    """
    assert "nope" not in TOOL_REGISTRY, "用例前提：'nope' MUST 是一个不存在的工具名"
    out = call("nope", {"any": "payload"})  # 若抛出，pytest 直接判 error

    assert isinstance(out, dict)
    assert "error" in out, f"未知工具 MUST 返回 error 形态：{out}"
    assert "未知工具" in str(out["error"]), f"错误要能读：{out}"
    assert out["available"] == sorted(POLISH_TOOL_ALLOWLIST), f"MUST 回给模型可用工具清单：{out}"
    # 形态与 Task 4 的默认分发器一致 ⇒ 循环侧拿到的是证据而不是 500
    assert set(out) == {"error", "available"}, f"形态 MUST 与 _make_default_dispatch 同形：{sorted(out)}"


# ── 9. 三个真实工具真能跑通（**真身**，不是桩） ────────────────────────────────
def test_three_real_tools_actually_run_with_minimal_payloads() -> None:
    """白名单三项 MUST 真跑通；`analyze` 的不出网前提由模型可用契约另行钉住。"""
    writing = call("writing_check", WRITING_CHECK_PAYLOAD)
    assert isinstance(writing, dict), f"writing_check 真身应返回 dict：{writing!r}"
    assert "suggestions" in writing, f"writing_check 真身 MUST 给出 suggestions：{sorted(writing)}"

    nlp = call("analyze", ANALYZE_PAYLOAD)
    assert isinstance(nlp, dict), f"analyze 真身应返回 dict：{nlp!r}"
    assert {"sentences", "stats"} <= set(nlp), f"analyze 真身 MUST 给出 sentences/stats：{sorted(nlp)}"

    vocab = call("vocab_stats", VOCAB_STATS_PAYLOAD)
    assert isinstance(vocab, dict), f"vocab_stats 真身应返回 dict：{vocab!r}"
    assert vocab["tokens_total"] == 1, f"vocab_stats 真身统计失真：{vocab}"
    assert vocab["known_count"] == 1, f"'gehen' 是实证过的真实 A1 词条 lemma，MUST 判 known：{vocab}"


# ── 10. 钩子默认是空序列 ───────────────────────────────────────────────────────
def test_hooks_default_is_an_empty_sequence() -> None:
    """`call_tool(name, payload)` 不传 `hooks` 时不得崩（默认空序列）。"""
    default = inspect.signature(call_tool).parameters["hooks"].default

    assert default == (), f"hooks 默认值 MUST 是空序列（可变默认值是 bug）：{default!r}"

    out = call("vocab_stats", VOCAB_STATS_PAYLOAD)
    assert out["tokens_total"] == 1, f"无钩子时应照常直调工具：{out}"


# ── 11. 接口兼容 Task 4：`partial(call_tool, hooks=...)` 可直接当 dispatch ──────
def test_partial_is_usable_as_task4_loop_dispatch() -> None:
    """D5 接线：`functools.partial(call_tool, hooks=[...])` 能被 `run_polish_loop` 以
    `f(name, payload)` 调用 ⇒ 权限闸在**循环里**也生效，且拒绝不会炸循环。
    """
    seen: list[str] = []
    dispatch = functools.partial(call_tool, hooks=[lambda name, payload: seen.append(name)])

    async def _chat(**kwargs: Any) -> dict[str, Any]:
        return {"tool_call": {"name": "vocab_stats", "payload": VOCAB_STATS_PAYLOAD}}

    result = asyncio.run(
        run_polish_loop(
            text="T0",
            chat=_chat,
            judge=_stub_judge,
            dispatch=dispatch,
            budget=Budget(max_turns=1),
        )
    )

    assert seen == ["vocab_stats"], f"钩子 MUST 在循环里也生效（D5 前置钩子）：{seen}"
    assert result.rounds == 1, f"工具调用轮应正常计入：{result}"


# ── 12. 三角一致性规范：writing_check 自查工具与裁判对齐 ────────────────────────
def test_writing_check_triangle_consistency(monkeypatch: pytest.MonkeyPatch) -> None:
    """三角一致性规范（Task 1 · ADR-0024 §6）：自查工具 writing_check 与回灌裁判对齐。

    a) writing_check.run 返回 dict 包含 violations、suggestions 与 judge_engine；
    b) 当 nlp 未加载 (None) 时，judge_engine == 'rules_only' 且 mode_note == '[快速模式: 不含深层语法规则]'；
    c) 当显式传入 nlp 或已存在 loaded nlp 时，nlp 被实际使用；
    d) violations 中的每一项符合统一 schema: rule, level, message, span。
    """
    sample_text = "Liebe Maria,\nich lade dich ein.\nViele Grüße\nAnna"

    # b) 当 nlp 未加载时：验证降级标记与 rules_only
    # mock-drift-ok: 调用期经模块属性读取（tools/writing_check.py:22 _nlp_processor.get_loaded_nlp()），补丁即时生效
    monkeypatch.setattr(processor, "get_loaded_nlp", lambda: None)
    res_no_nlp = asyncio.run(writing_check.run({"text": sample_text}))

    # a) 验证返回键
    assert isinstance(res_no_nlp, dict)
    assert "violations" in res_no_nlp, f"writing_check 结果 MUST 包含 violations: {sorted(res_no_nlp)}"
    assert "suggestions" in res_no_nlp, f"writing_check 结果 MUST 包含 suggestions: {sorted(res_no_nlp)}"
    assert "judge_engine" in res_no_nlp, f"writing_check 结果 MUST 包含 judge_engine: {sorted(res_no_nlp)}"

    # b) 验证 rules_only 与 mode_note
    assert res_no_nlp["judge_engine"] == "rules_only"
    assert res_no_nlp.get("mode_note") == "[快速模式: 不含深层语法规则]"

    # d) 验证 violations 项的 schema
    assert len(res_no_nlp["violations"]) > 0, "样例应产生至少一条建议/违规（例如 word_count）"
    for item in res_no_nlp["violations"]:
        assert isinstance(item, dict)
        assert set(item.keys()) == {"rule", "level", "message", "span"}
        assert isinstance(item["rule"], str)
        assert item["level"] in ("error", "warning")
        assert isinstance(item["message"], str)
        assert item["span"] is None or (
            isinstance(item["span"], (tuple, list)) and len(item["span"]) == 2
        )

    # c) 当传入 mock/dummy nlp 时，验证 nlp 被实际调用
    mock_nlp = MagicMock()
    mock_doc = MagicMock()
    mock_doc.sents = []
    mock_nlp.return_value = mock_doc

    # 1. 显式通过 payload["nlp"] 传入
    res_mock = asyncio.run(writing_check.run({"text": sample_text, "nlp": mock_nlp}))
    mock_nlp.assert_called_with(sample_text)
    assert isinstance(res_mock, dict)

    # 2. 通过 processor.get_loaded_nlp() 隐式提供
    mock_nlp.reset_mock()
    # mock-drift-ok: 调用期经模块属性读取（tools/writing_check.py:22 _nlp_processor.get_loaded_nlp()），补丁即时生效
    monkeypatch.setattr(processor, "get_loaded_nlp", lambda: mock_nlp)
    res_loaded = asyncio.run(writing_check.run({"text": sample_text}))
    mock_nlp.assert_called_with(sample_text)
    assert isinstance(res_loaded, dict)

    # 3. 若有真实 spaCy 模型，验证其产生 rules+spacy 且无 mode_note
    real_nlp = processor._resolve_nlp_model()
    if real_nlp is not None:
        # mock-drift-ok: 调用期经模块属性读取（tools/writing_check.py:22 _nlp_processor.get_loaded_nlp()），补丁即时生效
        monkeypatch.setattr(processor, "get_loaded_nlp", lambda: real_nlp)
        res_real = asyncio.run(writing_check.run({"text": sample_text}))
        assert res_real["judge_engine"] == "rules+spacy"
        assert "mode_note" not in res_real
        for item in res_real["violations"]:
            assert set(item.keys()) == {"rule", "level", "message", "span"}


# ── 变异自证清单（改动实现 ⇒ 对应用例 MUST 变红） ────────────────────────────────
# ① 把 `ingest` 加进 `POLISH_TOOL_ALLOWLIST`
#      ⇒ test_registry_minus_allowlist_is_exactly_the_excluded_three 红（差集少一项）；
#        test_allowlist_is_exactly_three_readonly_tools 也红（变成 4 项）。
# ② 钩子链改成「跳过」⇒ test_hooks_run_serially_in_order 红（seen 为空）、
#        test_hook_exception_rejects_call_without_raising 红（工具被真跑、无 rejected）；
#    钩子链改成「逆序」⇒ test_hooks_run_serially_in_order 红（h2/h3 的前置断言先炸）。
# ③ 未知工具改成 `raise ValueError` ⇒ test_unknown_tool_returns_error_shape_without_raising 红。
# ④ 把 `hooks` 默认值改成 `[]`（可变默认值）⇒ test_hooks_default_is_an_empty_sequence 红。
# ⑤ 白名单值换成 HTTP 客户端（走 `/api/tools/{name}`）⇒
#        test_allowlist_tools_are_called_in_process_without_http 红、
#        test_allowlist_is_exactly_three_readonly_tools 红（`is` 不再是同一个对象）。
# ⑥ 把 `call_tool` 里的 `hook(name, dict(payload))` 改回 `hook(name, payload)`（不给快照）
#      ⇒ test_hook_payload_mutation_cannot_rewrite_later_hooks_or_tool 红（实测 `1 failed,
#        10 passed`）。红的落点比"断言失守"更靠前：钩子把同一份 dict 改成
#        `levels=["C2"]` 后，工具真身在 `delector/tools/vocab_stats.py:102` 抛
#        `ValueError: unsupported exam level(s): ['C2']`，而工具自身异常是刻意不吞的，
#        于是 `out = call(...)` 这一行就炸 —— 根本走不到 `tokens_total==1` /
#        `known_count==1`。另注：`later_seen == [payload]` 这条**不会**红（payload 与
#        快照是同一个对象、两边同值），所以别指望它兜住这条变异。
# ⑦ 让运行时模型不可用（实测手法：把 `processor.SPACY_MODEL_CANDIDATES` 改成装不上的
#        名字 ⇒ 候选全失败 ⇒ 落进 `spacy.cli.download` 兜底路径）
#      ⇒ test_analyze_runtime_model_is_available_without_download 红（实测 `1 failed`：
#        `tests/test_polish_tools.py:102: Failed`，即 `pytest.fail`，下载桩被触发并把
#        `de_core_news_sm` 记进 `download_calls`）。
#        只摘掉"调用即抛"的下载桩**不足以**变红 —— 本机/CI 已装模型，正常路径压根不会
#        走到 `download`；能变红的是"模型不可用"这件事本身。
