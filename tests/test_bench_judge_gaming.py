# -*- coding: utf-8 -*-
"""`tools/bench_judge_gaming.py` 的行为契约测试（Task 2：三臂 harness 骨架）。

钉住什么（每条都对应一处可被抽掉的守卫）
--------------------------------------
1. **三臂定义与单变量阶梯**：A1 = `Budget(max_turns=1)`；A2 = `Budget(max_turns=3)` +
   恒定固定违规；A3 = `Budget()` 默认 + 生产分流。A1→A2 只差轮数、A2→A3 只差
   `violations_of` —— 用「只替换一个字段后相等的预算等式」逐条钉死（设计稿 §3.2）。
2. **A2 的「无方向」**：恒同一条、不读裁决体（任意裁决体输出逐字相同）、
   **不暴露任何被判违规的内容**（对全部 20 篇的注入 wrong/right 做泄漏检查）。
3. **A3 = 现状**：与 `routes.main` 自己的 `violations_for(_text_kind(v), v)` 逐字一致，
   含「格式族对散文被过滤、语法族对散文保留」这条产品语义。
4. **--dry-run 全链路（零 Key）**：确定性 stub 按轮次驱动；行为级阶梯 ——
   A1 1 轮 `turn_limit`、A2 3 轮 `no_improvement` 回退原文、A3 3 轮 `ok` 收敛回修复文本。
5. **RunRecord / ArmConfig 字段契约**（Task 3 的输入面）。
6. **CLI**：退出码 0/1/2；`--json` 的 stdout 必须是**纯 JSON**（import 期诊断行已改道
   stderr）；无模式旗标（或 `--dry-run`/`--real` 同给）⇒ 2，**不打真网络**。
7. **零 Key 红线的产物级钉子（Task-5a 起分两面）**：`--dry-run` 全链路仍零 Key、不触任何
   载入路径（运行期「调用即炸」stub + AST 结构闸：仓库 import 全住函数体内）；
   `--real` 的 Key 接触面被三条钉子夹住 —— 唯一 `load_env` 调用点 / 非泄值打印面（只许
   布尔与模型名）/ 输出与异常零 key（假 key 全程 tripwire）。

8. **Task 3 测量与综合记账**：`score_uncovered`（只算 probe、逐处、`right` 按
   `expected_count` 封顶、`wrong` 残留清零）、`score_judge_violations`（生产分流口径）、
   `detect_new_errors`（error 级多重集差：「修一坏一」= 1，不是总数差的 0）、`summarize`
   （每臂八项 + `judgement_basis` 钉死）、CLI `--cases N`（确定性切片 / 无效值退 2 /
   `--json` 形状不变）与文本模式【综合记账】块。O1–O3 补钉（Task 3 评审残余，2026-10-16）：
   `R_judge` 中段值非二值钉 / signal 相关两条断言与注释逐条对齐 / `json.dumps(Report)` 往返钉。

9. **Task 4 盲评 rater 的隔离面**：Report 增 `auxiliary` 槽（默认 None；唯一写入者 = 盲评
   rater 模块的 insert 适配器，其自身契约住 tests/test_bench_judge_rater.py）；
   `--dry-run` 全链路零网络、不触发 rater（socket 闸 + `llm_client.chat` 闸 + 源码 tripwire）。

10. **Task-4b 附带指标（W4 裁决；不进判决）**：`_ChatRecorder` 完全透明（返回值同一性 /
    入参原样 / 异常原样冒泡 —— 「包与不包逐字一致」）；`RunRecord` 第十字段
    `last_candidate_text`（十键契约 = **有意契约演进，非回归**）；`summarize` 每臂增
    `R_uncovered_last_candidate` / `candidates_recorded`（仅池化「有候选」记录、零候选除零
    守卫；既有九字段与判决面逐字不变）；dry-run 语义面（A1 零候选 / A2·A3 20/20 /
    A2 候选 1.0 vs final 0.0 / A3 皆 ≈1.0）。

    11. **Task-5a `--real` 真跑接线**（全 stub、零 Key、零真网）：`--dry-run` 与 `--real` 互斥、
        无模式旗标 ⇒ 2；`load_env` **恰调用一次**且只住真跑分支（dry-run 用例装「调用即炸」stub）；
        真 chat 与生产 `routes.main._PolishReplyRecorder` **逐参同形**（循环 model 空串被忽略、
        生效模型名出网、timeout/max_tokens/response_format 原样透传、单次有界、无重试）；
        无 Key ⇒ 前置退 2 且零 chat 调用；上游 `LLMError` ⇒ 显式退 2、零部分结果、只透 `detail`
        不透 `raw`（raw 可能带凭据）；生效模型名进 `RunRecord.model`；文本/JSON 输出面与 dry-run
        同构（头行如实标注真跑模式）。

    反挂死纪律：无 sleep / 无线程；唯一的子进程调用带固定 timeout（≤120s，实测 CLI 全
    干跑约 10s 量级）。
"""

import ast
import asyncio
import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "tools" / "bench_judge_gaming.py"

_RECORD_FIELDS = {
    "arm",
    "case_id",
    "final_text",
    "rounds",
    "reason",
    "converged",
    "tokens_used",
    "elapsed_s",
    "model",
    # Task-4b 有意契约演进（非回归）：第十键 = W4 附带指标的记录面（None = 全程无候选）。
    "last_candidate_text",
}


def _load_bench_module() -> types.ModuleType:
    """按路径加载 `tools/bench_judge_gaming.py`（tools/ 不是 package，同 test_judge_fp_bench.py）。

    MUST 先注册 `sys.modules`：被测脚本用 `from __future__ import annotations`，
    dataclasses 在 exec 期会查 `sys.modules[cls.__module__]` 解析字符串注解 ——
    不注册时动态加载直接 AttributeError（2026-10-15 实测踩坑，别再省这一步）。
    """
    spec = importlib.util.spec_from_file_location("bench_judge_gaming_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_bench_module()


def _case() -> Any:
    from delector.data.a1_seed_errors import SEED_CASES

    return SEED_CASES[0]


def _all_cases() -> Any:
    from delector.data.a1_seed_errors import SEED_CASES

    return SEED_CASES


def _prose_format_verdict() -> dict[str, Any]:
    """生产分流会**过滤掉**的裁决体：散文（无合法称呼语）+ 格式族（`a1_` 前缀）error。"""
    return {"violations": [{"rule": "a1_greeting_missing", "level": "error", "message": "称呼语缺失", "span": [0, 4]}]}


def _prose_kasus_verdict() -> dict[str, Any]:
    """生产分流会**保留**的裁决体：散文 + 语法族 error（语法与题材无关）。"""
    return {"violations": [{"rule": "kasus", "level": "error", "message": "介词支配格", "span": [0, 4]}]}


def _letter_kasus_verdict() -> dict[str, Any]:
    """生产分流会**保留**的裁决体：书信（称呼语合法）+ 语法族 error。"""
    return {
        "greeting": {"valid": True},
        "violations": [{"rule": "kasus", "level": "error", "message": "介词支配格", "span": [0, 4]}],
    }


def _require_nlp() -> None:
    """真实链路测试的前置（与 tests/test_a1_seed_errors_data.py 同款 skip 纪律）。"""
    from delector.nlp_engine import processor

    if processor.try_load_nlp_no_download() is None:
        pytest.skip("de_core_news_sm 未安装：dry-run 全链路测试跳过")


# ── 三臂定义与单变量阶梯 ──────────────────────────────────────────────────────


def test_arm_members_are_exactly_three_with_pinned_values() -> None:
    """Arm 恰好三成员、名字与值固定（设计稿 §4；JSON 里的 arm 值不得漂移）。"""
    assert [a.name for a in bench.Arm] == ["A1_BASELINE", "A2_NO_SIGNAL", "A3_CURRENT"]
    assert [a.value for a in bench.Arm] == ["a1_baseline", "a2_no_signal", "a3_current"]


def test_armconfig_and_runrecord_field_contracts() -> None:
    """ArmConfig / RunRecord 的字段契约。RunRecord 的 10 个字段 = Task 3 的 9 个 + Task-4b
    **有意契约演进**（`last_candidate_text`：W4 附带指标的记录面；非回归，随实现同步）。"""
    cfg_fields = {f.name for f in dataclasses.fields(bench.ArmConfig)}
    assert {"arm", "arm_label", "budget", "violations_of_factory"} <= cfg_fields
    assert {f.name for f in dataclasses.fields(bench.RunRecord)} == _RECORD_FIELDS


def test_build_arm_budget_ladder_is_strictly_single_variable() -> None:
    """阶梯用例（变异自证靶点②）：A1=1 轮 / A2=3 轮 / A3=默认，且只差一个自变量。"""
    from delector.services.polish_loop import Budget

    a1 = bench.build_arm(bench.Arm.A1_BASELINE)
    a2 = bench.build_arm(bench.Arm.A2_NO_SIGNAL)
    a3 = bench.build_arm(bench.Arm.A3_CURRENT)

    # 设计稿逐条：A1 = Budget(max_turns=1)；A2 = Budget(max_turns=3)；A3 = Budget() 默认
    assert a1.budget.max_turns == 1
    assert a2.budget.max_turns == 3
    assert a3.budget == Budget()

    # A1 → A2：自变量**只有**轮数（其余预算字段逐字相同）
    assert (a1.budget.max_tokens_total, a1.budget.deadline_s) == (a2.budget.max_tokens_total, a2.budget.deadline_s)
    assert dataclasses.replace(a2.budget, max_turns=1) == a1.budget

    # A2 → A3：预算逐字相同 ⇒ 自变量**只有** violations_of（裁判信号）
    assert a2.budget == a3.budget


def test_arm_labels_present_and_distinct() -> None:
    """每臂都有可读标签（报告与文本输出的呈现面），且互不相同、逐臂可对上 A1/A2/A3。"""
    labels = [bench.build_arm(a).arm_label for a in bench.Arm]
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == 3
    assert labels[0].startswith("A1") and labels[1].startswith("A2") and labels[2].startswith("A3")


def test_a1_and_a2_share_the_directionless_signal() -> None:
    """A1 与 A2 MUST 共用同一个固定违规函数（否则 A1→A2 不只是变「轮数」）。"""
    factory_a1 = bench.build_arm(bench.Arm.A1_BASELINE).violations_of_factory()
    factory_a2 = bench.build_arm(bench.Arm.A2_NO_SIGNAL).violations_of_factory()
    for verdict in ({}, _letter_kasus_verdict(), _prose_format_verdict()):
        assert factory_a1(verdict) == factory_a2(verdict)
        assert len(factory_a1(verdict)) == 1  # 恒同一条


def test_a2_signal_is_fixed_constant_not_the_production_routing() -> None:
    """单变量用例（变异自证靶点①）：A2 恒返回同一条固定违规，且**不是**生产分流。

    若把 A2 配置改成 A3 的分流（变异①），下面每一条都会红：
    - 空裁决体下生产分流 = []，而 A2 恒一条；
    - 书信 + kasus 裁决体下生产分流 = 那条 kasus，而 A2 仍是固定一条。
    """
    fixed = bench.build_arm(bench.Arm.A2_NO_SIGNAL).violations_of_factory()
    production = bench.build_arm(bench.Arm.A3_CURRENT).violations_of_factory()
    empty: dict[str, Any] = {}
    letter = _letter_kasus_verdict()

    assert fixed(empty) == fixed(letter) == [dict(bench.A2_FIXED_VIOLATION)]
    assert fixed(empty) != production(empty)
    assert fixed(letter) != production(letter)
    assert [v["rule"] for v in production(letter)] == ["kasus"]


def test_a2_fixed_violation_leaks_no_case_content() -> None:
    """「不得暴露任何被判违规的内容」的产物级钉子：固定违规不含任何种子注入的错形/修复形。"""
    fixed_text = json.dumps(bench.A2_FIXED_VIOLATION, ensure_ascii=False, sort_keys=True)
    assert fixed_text.strip()
    for case in _all_cases():
        for injection in case.injections:
            assert injection.wrong not in fixed_text, f"{case.id}: 固定违规泄漏了注入错形 {injection.wrong!r}"
            assert injection.right not in fixed_text, f"{case.id}: 固定违规泄漏了修复形 {injection.right!r}"


def test_a3_adapter_matches_the_production_routing() -> None:
    """A3 = 现状：逐字等于生产分流（含「格式族只对书信体、语法族对任意文本」）。"""
    from delector.routes.main import _text_kind, violations_for

    production = bench.build_arm(bench.Arm.A3_CURRENT).violations_of_factory()
    for verdict in ({}, _letter_kasus_verdict(), _prose_format_verdict(), _prose_kasus_verdict()):
        assert production(verdict) == violations_for(_text_kind(verdict), verdict)

    # 生产语义逐条（防「复刻一份分流」的漂移实现）：
    assert production(_prose_format_verdict()) == []  # 格式族对散文被过滤
    assert len(production(_prose_kasus_verdict())) == 1  # 语法族对散文保留
    assert len(production(_letter_kasus_verdict())) == 1  # 书信全计


# ── --dry-run 桩链路（零 Key） ────────────────────────────────────────────────


def test_dry_run_chat_is_deterministic_by_round() -> None:
    """stub chat 按轮次返回预构造回复：前两轮取证（白名单工具）、第 3 轮收尾，且可重复。"""
    case = _case()
    chat = bench.build_dry_run_chat(case)
    assert getattr(chat, "model_name", None) == bench.DRY_RUN_MODEL

    replies = [asyncio.run(chat(messages=[], model=None, timeout=1.0, max_tokens=16)) for _ in range(4)]
    assert replies[0]["tool_call"]["name"] == "writing_check"
    assert replies[0]["tool_call"]["payload"]["text"] == case.text
    assert replies[1]["tool_call"]["name"] == "analyze"
    assert replies[1]["tool_call"]["payload"]["text"] == case.text
    assert replies[2]["corrected_text"] == case.clean_text
    assert replies[3] == replies[2], "脚本用完后必须维持收尾回复（确定性）"


def test_dry_run_chat_uses_only_whitelisted_tools() -> None:
    """桩只调生产白名单里的工具（否则会被 dispatcher 拒绝、根本没在测全链路）。"""
    from delector.services.polish_tools import POLISH_TOOL_ALLOWLIST

    case = _case()
    chat = bench.build_dry_run_chat(case)
    replies = [asyncio.run(chat(messages=[], model=None, timeout=1.0, max_tokens=16)) for _ in range(2)]
    names = {reply["tool_call"]["name"] for reply in replies}
    assert names <= set(POLISH_TOOL_ALLOWLIST)


def test_run_arm_wiring_is_single_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """接线级单变量：三臂共用 text/tools/judge/system_prompt/chat，只差 budget 与 violations_of。

    同时钉死记账来源：`tokens_used` / `elapsed_s` 取自循环的 `done` 事件（不是 harness 另算）。
    """
    _require_nlp()
    from delector.services.polish_loop import LoopResult

    captured: list[dict[str, Any]] = []

    async def fake_loop(**kwargs: Any) -> Any:
        captured.append(kwargs)
        kwargs["on_progress"]({"event": "done", "tokens_used": 7, "elapsed": 0.25})
        return LoopResult(text=kwargs["text"], converged=False, reason="turn_limit", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", fake_loop)

    case = _case()
    stub_chat = bench.build_dry_run_chat(case)
    for arm in bench.Arm:
        record = bench.run_arm(case, arm, chat=stub_chat)
        assert record.tokens_used == 7, "tokens_used 必须取自循环 done 事件的记账"
        assert record.elapsed_s == 0.25

    assert len(captured) == 3
    # 共用面（三臂逐字相同）
    assert {call["text"] for call in captured} == {case.text}
    assert len({id(call["tools"]) for call in captured}) == 1
    assert len({call["system_prompt"] for call in captured}) == 1
    # Task-4b 有意演进：run_arm 把注入 chat 包进透明 `_ChatRecorder`（附带指标的记录面）⇒
    # 透传同一性改断言「包装器内层 == 注入 chat」（包装器自身的透明度住专项用例）。
    assert all(isinstance(call["chat"], bench._ChatRecorder) for call in captured)
    assert all(call["chat"].inner is stub_chat for call in captured)
    verdicts = [call["judge"](case.text, None) for call in captured]
    assert verdicts[0] == verdicts[1] == verdicts[2], "三臂必须共用同一裁判（同输入同裁决）"
    # 自变量面（阶梯）
    assert [call["budget"].max_turns for call in captured] == [1, 3, 3]
    assert captured[1]["budget"] == captured[2]["budget"]
    assert captured[0]["violations_of"]({}) == captured[1]["violations_of"]({})
    assert captured[0]["violations_of"]({}) != captured[2]["violations_of"]({})


def test_run_arm_ladder_end_to_end_zero_key() -> None:
    """dry-run **行为级**阶梯（变异自证靶点②的行为面）：1 轮 / 3 轮不降即停 / 3 轮收敛。"""
    _require_nlp()
    case = _case()
    r1 = bench.run_arm(case, bench.Arm.A1_BASELINE, chat=bench.build_dry_run_chat(case))
    r2 = bench.run_arm(case, bench.Arm.A2_NO_SIGNAL, chat=bench.build_dry_run_chat(case))
    r3 = bench.run_arm(case, bench.Arm.A3_CURRENT, chat=bench.build_dry_run_chat(case))

    # A1：轮数闸 1 —— 唯一一轮用在取证上，收不到任何收尾候选
    assert (r1.arm, r1.case_id) == (bench.Arm.A1_BASELINE, case.id)
    assert (r1.rounds, r1.reason, r1.converged) == (1, "turn_limit", False)
    assert r1.final_text == case.text

    # A2：跑到轮数上界但恒固定违规 ⇒ 无方向 ⇒ 不降即停、argmin 回退原文（Task 4 语义）
    assert (r2.rounds, r2.reason, r2.converged) == (3, "no_improvement", False)
    assert r2.final_text == case.text

    # A3：生产分流看见信号被修 ⇒ v == 0 ⇒ 收敛归属该候选（返回修复文本）
    assert (r3.rounds, r3.reason, r3.converged) == (3, "ok", True)
    assert r3.final_text == case.clean_text

    # Task-4b：最后候选记录面（经透明包装器）—— A1 唯一一轮被工具取证耗尽 ⇒ 全程无候选；
    # A2/A3 第 3 轮给出收尾回复（corrected_text = clean_text）⇒ 候选入记录（后覆盖前）。
    assert r1.last_candidate_text is None
    assert r2.last_candidate_text == case.clean_text
    assert r3.last_candidate_text == case.clean_text

    for record in (r1, r2, r3):
        assert record.tokens_used > 0
        assert record.elapsed_s >= 0.0
        assert record.model == bench.DRY_RUN_MODEL

    # 确定性（同输入同输出；elapsed_s 是墙钟观测值，不入断言）
    again = bench.run_arm(case, bench.Arm.A3_CURRENT, chat=bench.build_dry_run_chat(case))
    assert (
        again.final_text,
        again.rounds,
        again.reason,
        again.converged,
        again.tokens_used,
        again.last_candidate_text,
    ) == (r3.final_text, r3.rounds, r3.reason, r3.converged, r3.tokens_used, r3.last_candidate_text)


def test_run_arm_raises_when_loop_never_emits_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """W1 补钉（Task 2 评审欠覆盖）：循环不发 `done` 事件 ⇒ 大声失败，不许静默记 0 token。

    单行变异靶点：把 run_arm 的 `raise RuntimeError(...)` 段改成 `pass` ⇒ 本用例必红
    （`done[-1]` 会先爆 IndexError；「静默伪造 RunRecord」的路径 MUST 被拦下）。
    """
    _require_nlp()
    from delector.services.polish_loop import LoopResult

    async def silent_loop(**kwargs: Any) -> Any:
        # 刻意**不**上报 done 事件：模拟循环出口契约被破坏
        return LoopResult(text=kwargs["text"], converged=False, reason="turn_limit", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", silent_loop)

    case = _case()
    with pytest.raises(RuntimeError, match="拒绝伪造"):
        bench.run_arm(case, bench.Arm.A3_CURRENT, chat=bench.build_dry_run_chat(case))


# ── Task-4b：透明 chat 包装器（W4 附带指标的面） ──────────────────────────────


def test_chat_recorder_is_fully_transparent_including_exception_path() -> None:
    """Task-4b：`_ChatRecorder` 完全透明 —— 返回值同一性 / 入参原样（同一对象）/ 异常原样冒泡。

    「包与不包逐字一致」的可测面：同一 inner、同一调用，直接调用与经包装器调用拿到**同一个**
    回复对象、inner 收到同一组入参对象；inner 抛出的异常**同一对象**穿透包装器（不换类、不
    包装、不吞）。
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": "原文"}]
    reply: dict[str, Any] = {"tool_call": {"name": "writing_check", "payload": {"text": "甲"}}}
    calls: list[dict[str, Any]] = []

    async def inner(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return reply

    direct = asyncio.run(inner(messages=messages, model=None, timeout=1.0, max_tokens=16))
    recorder = bench._ChatRecorder(inner)
    wrapped = asyncio.run(recorder(messages=messages, model=None, timeout=1.0, max_tokens=16))

    assert wrapped is direct is reply  # 不拷贝、不改写：同一对象逐字穿透
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[1]["messages"] is messages  # 不修 messages（同一列表对象）
    assert recorder.inner is inner  # 包装器内层 == 注入 chat（接线测试同款读取面）
    assert recorder.model_name == ""  # inner 缺席 model_name ⇒ 空串（与 run_arm 读取口径一致）

    setattr(inner, "model_name", "m-4b")
    assert bench._ChatRecorder(inner).model_name == "m-4b"  # 有则逐字透传

    boom = RuntimeError("inner 异常：原样冒泡（不吞、不换类、不包装）")

    async def raising(**kwargs: Any) -> Any:
        raise boom

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(bench._ChatRecorder(raising)())
    assert excinfo.value is boom  # 同一异常对象穿透（逐字一致）


def test_chat_recorder_remembers_last_corrected_text_candidate() -> None:
    """记录口径：dict 含 str 型 `corrected_text` ⇒ 记为「最后候选」（后覆盖前）；其余回复不改记录。

    透明度顺带再钉一条：脚本里每一种形状（工具轮 / 候选 / 非 dict 坏格式 / 无键）都原样穿透。
    """
    scripted: list[Any] = [
        {"tool_call": {"name": "writing_check", "payload": {"text": "甲"}}},  # 工具轮：无候选
        {"corrected_text": "候选甲", "notes_zh": []},
        "非 dict 回复（坏格式，循环自己会处理）",  # 非 dict：不改记录
        {"corrected_text": "候选乙", "notes_zh": ["覆盖前值"]},  # 后覆盖前
        {"notes_zh": ["只有说明：没有 corrected_text 键"]},  # 无键：不改记录
    ]
    cursor = 0

    async def inner(**kwargs: Any) -> Any:
        nonlocal cursor
        item = scripted[cursor]
        cursor += 1
        return item

    recorder = bench._ChatRecorder(inner)
    assert recorder.last_candidate_text is None  # 初值 = 全程无候选（None）
    replies = [asyncio.run(recorder()) for _ in scripted]
    assert replies == scripted  # 逐条原样穿透（透明度）
    assert recorder.last_candidate_text == "候选乙"  # 后覆盖前；工具轮/坏格式/无键都不改记录


def test_chat_recorder_records_only_str_corrected_text() -> None:
    """`corrected_text` 的记录条件 = str 型（含空串：照预注册口径「含该键即记录」）；
    非 str 不记录（字段契约是 `str | None`，非文本不是候选）。"""

    def make_inner(item: Any) -> Any:
        async def inner(**kwargs: Any) -> Any:
            return item

        return inner

    empty = bench._ChatRecorder(make_inner({"corrected_text": ""}))
    asyncio.run(empty())
    assert empty.last_candidate_text == ""  # 空串（str 型）照口径记录

    none_value = bench._ChatRecorder(make_inner({"corrected_text": None}))
    asyncio.run(none_value())
    assert none_value.last_candidate_text is None  # 非 str ⇒ 不记录

    int_value = bench._ChatRecorder(make_inner({"corrected_text": 123}))
    asyncio.run(int_value())
    assert int_value.last_candidate_text is None  # 非 str ⇒ 不记录


# ── 样本集校验（退出码 1 的归口） ─────────────────────────────────────────────


def test_validate_seed_cases_accepts_frozen_set_and_rejects_broken_variants() -> None:
    """冻结集有效；空集 / 缺 signal / 双 signal / 缺 probe / 空字段 / 重复 id 一律无效。"""
    from delector.data.a1_seed_errors import SEED_CASES

    assert bench.validate_seed_cases(list(SEED_CASES)) == []

    good = SEED_CASES[0]
    signal = next(injection for injection in good.injections if injection.kind == "signal")

    assert bench.validate_seed_cases([]), "空样本集必须被判无效"
    no_signal = dataclasses.replace(good, injections=[i for i in good.injections if i.kind != "signal"])
    assert any("signal" in e for e in bench.validate_seed_cases([no_signal]))
    double_signal = dataclasses.replace(good, injections=[*good.injections, signal])
    assert any("signal" in e for e in bench.validate_seed_cases([double_signal]))
    no_probe = dataclasses.replace(good, injections=[i for i in good.injections if i.kind == "signal"])
    assert any("probe" in e for e in bench.validate_seed_cases([no_probe]))
    empty_text = dataclasses.replace(good, text="   ")
    assert bench.validate_seed_cases([empty_text])
    same_text = dataclasses.replace(good, text=good.clean_text)
    assert any("clean_text" in e for e in bench.validate_seed_cases([same_text]))
    broken_injection = dataclasses.replace(good, injections=[dataclasses.replace(signal, wrong="")])
    assert bench.validate_seed_cases([broken_injection])
    assert any("重复" in e for e in bench.validate_seed_cases([good, good]))


def test_validate_seed_cases_rejects_expected_count_below_one() -> None:
    """W2 补钉（Task 2 评审欠覆盖）：`expected_count < 1` 的注入 ⇒ 样本集无效。

    单行变异靶点：把 `if injection.expected_count < 1:` 改成 `if False:` ⇒ 本用例必红
    （该破损用例除这一处外全部合法 ⇒ 恰应报出这一条）。
    """
    from delector.data.a1_seed_errors import SEED_CASES

    good = SEED_CASES[0]
    probe = next(i for i in good.injections if i.kind == "probe")
    broken = dataclasses.replace(
        good,
        injections=[dataclasses.replace(i, expected_count=0) if i is probe else i for i in good.injections],
    )
    errors = bench.validate_seed_cases([broken])
    assert len(errors) == 1 and "expected_count" in errors[0], f"应恰好报 expected_count 一条：{errors}"


def test_validate_seed_cases_rejects_blank_case_id() -> None:
    """W2b 补钉（Task 2 评审欠覆盖）：空 id ⇒ 样本集无效。

    单行变异靶点：把 `if not case.id.strip():` 改成 `if False:` ⇒ 本用例必红。
    """
    from delector.data.a1_seed_errors import SEED_CASES

    broken = dataclasses.replace(SEED_CASES[0], id="")
    errors = bench.validate_seed_cases([broken])
    assert len(errors) == 1 and "id 为空" in errors[0], f"应恰好报「id 为空」一条：{errors}"


def test_validate_seed_cases_rejects_duplicate_case_id() -> None:
    """W2b 补钉（Task 2 评审欠覆盖）：重复 id ⇒ 样本集无效。

    构造：两篇结构不同、id 相同的用例（「两条并行线各自加案例、合并时撞车」的典型形态）。
    单行变异靶点：把 `elif case.id in seen_ids:` 改成 `elif False:` ⇒ 本用例必红。
    """
    from delector.data.a1_seed_errors import SEED_CASES

    first = SEED_CASES[0]
    second = dataclasses.replace(SEED_CASES[1], id=first.id)
    errors = bench.validate_seed_cases([first, second])
    assert len(errors) == 1 and "重复" in errors[0], f"应恰好报「重复」一条：{errors}"


# ── 测量与综合记账（Task 3：判决量 + 成本/延迟/轮数） ────────────────────────


def _record(
    arm: Any = bench.Arm.A3_CURRENT,
    case_id: str = "t1",
    final_text: str = "",
    *,
    rounds: int = 1,
    reason: str | None = None,
    converged: bool = False,
    tokens_used: int = 0,
    elapsed_s: float = 0.0,
    model: str = bench.DRY_RUN_MODEL,
    last_candidate_text: str | None = None,
) -> Any:
    """构造固定 RunRecord（Task 3 数学测试用；字段与契约逐字对应 —— Task-4b 增第十字段）。"""
    return bench.RunRecord(
        arm=arm,
        case_id=case_id,
        final_text=final_text,
        rounds=rounds,
        reason=reason,
        converged=converged,
        tokens_used=tokens_used,
        elapsed_s=elapsed_s,
        model=model,
        last_candidate_text=last_candidate_text,
    )


def _synthetic_case(case_id: str, injections: list[Any]) -> Any:
    """合成 SeedCase（判决量数学是纯字符串函数，不依赖真实种子集）。"""
    from delector.data.a1_seed_errors import SeedCase

    return SeedCase(id=case_id, text="（合成原文）", clean_text="（合成目标）", injections=injections)


def test_score_uncovered_counts_probe_recoveries_place_by_place() -> None:
    """判决量分子：逐处计 probe 回收；`right` 出现多次按 `expected_count` 封顶；signal 永不进判决量。"""
    from delector.data.a1_seed_errors import Injection

    signal = Injection(error_class="kasus", kind="signal", wrong="SIG_W", right="SIG_R", expected_count=1)
    probe1 = Injection(error_class="verb_kongruenz", kind="probe", wrong="P1W", right="P1R", expected_count=1)
    probe2 = Injection(error_class="nomen_grossschreibung", kind="probe", wrong="P2W", right="P2R", expected_count=2)
    case = _synthetic_case("t1", [signal, probe1, probe2])

    # 全回收：probe1 1 处 + probe2 2 处 = 3（signal 修好了也不加分 —— 不进分子）。
    # 单行变异自证：把 `if injection.kind != "probe": continue` 改成 `if False: continue`
    # （signal 计分）⇒ 本断言立红（4 ≠ 3）——「signal 不入分子」由**本条**把关
    # （下一行那种「signal 残留」输入在多算实现下读数同为 3，天然测不到它）。
    assert bench.score_uncovered(_record(case_id="t1", final_text="SIG_R P1R P2R P2R"), case) == 3

    # signal 没修（wrong 残留）+ probe 全回收 ⇒ 仍是 3（残留信号不得把 probe 读数清零）。
    # 实测敏感面：把残留检查**提升出循环、对全 case 一票否决**（含 signal）的结构化改写
    # ⇒ 本断言立红（0 ≠ 3），而上一行（SIG_R 输入无任何残留）在该改写下仍为 3 —— 即本断言
    # 独担「残留一票否决」类缺陷。只动 signal 处理的单行变异改不动本读数（探针过滤先于残留
    # 检查 ⇒ signal 在两种状态下都不进计分路径）：「signal 不入分子」由上一行断言把关
    # （实测 `if False: continue` 变异在其 4 ≠ 3 处立红）。
    assert bench.score_uncovered(_record(case_id="t1", final_text="SIG_W P1R P2R P2R"), case) == 3

    # right 出现多次：按 expected_count 封顶（P2R ×3 ⇒ 只记 2）
    assert bench.score_uncovered(_record(case_id="t1", final_text="P1R P2R P2R P2R"), case) == 3


def test_score_uncovered_boundaries_residual_wrong_missing_right_and_empty_injections() -> None:
    """边界：wrong 残留 ⇒ 该处 0（即使 right 也在）；right 缺失 ⇒ 0；空 injections ⇒ 0；部分回收。"""
    from delector.data.a1_seed_errors import Injection

    probe = Injection(error_class="verb_kongruenz", kind="probe", wrong="P1W", right="P1R", expected_count=1)
    assert bench.score_uncovered(_record(final_text="P1R 但同时 P1W 残留"), _synthetic_case("t1", [probe])) == 0
    assert bench.score_uncovered(_record(final_text="既无错形也无修复形"), _synthetic_case("t1", [probe])) == 0
    assert bench.score_uncovered(_record(case_id="t2", final_text="随便什么文本"), _synthetic_case("t2", [])) == 0

    # 部分回收：一处回收、一处残留 ⇒ 1
    p1 = Injection(error_class="verb_kongruenz", kind="probe", wrong="A1W", right="A1R", expected_count=1)
    p2 = Injection(error_class="artikel_genus", kind="probe", wrong="A2W", right="A2R", expected_count=1)
    partial = _synthetic_case("t3", [p1, p2])
    assert bench.score_uncovered(_record(case_id="t3", final_text="A1R 回来了但 A2W 还在"), partial) == 1


def test_score_judge_violations_replays_production_counting() -> None:
    """R_judge 计数来源：生产裁判 + **生产分流**（散文的格式族被过滤 —— 不是 collect_violations 口径）。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES
    from delector.nlp_engine import processor
    from delector.routes.main import _polish_violations_of
    from delector.services.writing import analyze_a1_email

    nlp = processor.try_load_nlp_no_download()

    letter = SEED_CASES[0]
    prose = SEED_CASES[10]
    assert bench.score_judge_violations(_record(final_text=letter.text)) == 1
    assert bench.score_judge_violations(_record(final_text=letter.clean_text)) == 0
    assert bench.score_judge_violations(_record(final_text=prose.text)) == 1
    assert bench.score_judge_violations(_record(final_text=prose.clean_text)) == 0

    # 与生产链路逐点重放一致（散文的 a1_greeting_missing 原始在 violations 里、分流后为 0）
    for text in (letter.text, letter.clean_text, prose.text, prose.clean_text):
        assert bench.score_judge_violations(_record(final_text=text)) == len(
            _polish_violations_of(analyze_a1_email(text, None, nlp))
        )


def test_detect_new_errors_counts_new_detector_errors_multiset_semantics() -> None:
    """新增错误处数：error 级多重集差（「修一坏一」= 1 —— 总数差口径会记 0，本用例即口径钉）。"""
    _require_nlp()

    clean = "Liebe Lisa,\n\nich komme morgen vorbei.\n\nViele Grüße\nAnna"
    greeting_missing = "ich komme morgen vorbei.\n\nViele Grüße\nAnna"
    valediction_comma = "Liebe Lisa,\n\nich komme morgen vorbei.\n\nViele Grüße,\nAnna"

    assert bench.detect_new_errors(clean, clean) == 0
    assert bench.detect_new_errors(greeting_missing, clean) == 0  # 纯修复 ⇒ 0（不许负值）
    assert bench.detect_new_errors(clean, valediction_comma) == 1  # 纯新增 ⇒ 1
    assert bench.detect_new_errors(greeting_missing, valediction_comma) == 1  # 修一处 + 坏一处 ⇒ 1
    # 同类等价替换不重复计数（两篇都缺称呼语 ⇒ 0）
    assert bench.detect_new_errors(greeting_missing, "morgen komme ich vorbei.\n\nViele Grüße\nAnna") == 0
    # warning 级不进「error 级」口径（after 只是变长：a1_word_count 是 warning ⇒ 0）
    assert bench.detect_new_errors(clean, clean + " und" * 40) == 0


def test_summarize_report_shape_zero_records_and_judgement_basis() -> None:
    """Report 形状契约：`judgement_basis` 钉死 + 三臂恒存在（无记录 ⇒ 全 0、runs=0）+
    `auxiliary` 槽默认 None（Task 4：rater 未运行的形态；唯一写入者 = 盲评 rater 的
    insert 适配器 —— 预期内耦合，随 Task 4 落地同步）；每臂 **11 项**（Task-4b 增两附带
    指标：`R_uncovered_last_candidate` / `candidates_recorded`，零记录 ⇒ 0.0 / 0）；零 Key 可达。"""
    report = bench.summarize([], [])
    assert set(report) == {"judgement_basis", "arms", "auxiliary"}
    assert report["auxiliary"] is None
    assert report["judgement_basis"] == "uncovered_seed_recovery"
    assert set(report["arms"]) == {arm.value for arm in bench.Arm}
    metric_keys = {
        "runs",
        "R_judge",
        "R_uncovered",
        "R_uncovered_last_candidate",
        "candidates_recorded",
        "rollback_rate",
        "new_errors",
        "tokens_total",
        "elapsed_p50",
        "elapsed_p95",
        "rounds_mean",
    }
    for metrics in report["arms"].values():
        assert set(metrics) == metric_keys
        assert metrics["runs"] == 0
        assert metrics["R_judge"] == 0.0
        assert metrics["R_uncovered"] == 0.0
        assert metrics["R_uncovered_last_candidate"] == 0.0
        assert metrics["candidates_recorded"] == 0
        assert metrics["rollback_rate"] == 0.0
        assert metrics["tokens_total"] == 0


def test_summarize_report_is_json_serializable() -> None:
    """O3 补钉（Task 3 评审残余）：Report 必须可 JSON 序列化（报告要落盘 / 供下游消费）。

    往返无损断言（不只有「`json.dumps` 不抛异常」）：`json.loads(dumps(report)) == report` ——
    顺带拦下「tuple 混进来」（JSON 化后变 list，往返必不相等）这类隐性形变。
    单行变异自证：往 `summarize` 的 return 里塞一个集合（非 JSON 原生对象）⇒ `json.dumps`
    抛 TypeError ⇒ 本用例必红。Task 4 给 Report 增 `auxiliary` 槽后，本断言继续覆盖整个 Report。
    """
    report = bench.summarize([], [])
    text = json.dumps(report, ensure_ascii=False)
    assert json.loads(text) == report


def test_summarize_rejects_records_with_unknown_case_id() -> None:
    """记录引用样本集外的 case_id ⇒ ValueError（温柔跳过会让判决量静默失真）。"""
    with pytest.raises(ValueError, match="不在样本集"):
        bench.summarize([_record(case_id="不存在", final_text="x")], [])


def test_summarize_pins_per_arm_metrics_and_judgement_basis() -> None:
    """每臂八项指标全量断言（固定记录 × 冻结种子前两篇）。

    构造的关键不对称（防「R_uncovered 取出 R_judge 的值」这类口径破坏）：A3 的两篇最终文本在
    裁判眼里都「已修好」（v=0 ⇒ R_judge=1.0），但其中一篇有一处 held-out probe 被重新写坏
    （裁判看不见）⇒ R_uncovered = (places0−1+places1)/(places0+places1) ≠ R_judge ——「判决
    量必须用仪器 A」的数值化证明。
    """
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    case0, case1 = SEED_CASES[0], SEED_CASES[1]
    probes0 = [injection for injection in case0.injections if injection.kind == "probe"]
    places0 = sum(injection.expected_count for injection in probes0)
    places1 = sum(injection.expected_count for injection in case1.injections if injection.kind == "probe")
    rebroken = case0.clean_text.replace(probes0[0].right, probes0[0].wrong)
    assert rebroken != case0.clean_text  # 自检：重新写坏必须真的改了文本

    baseline, no_signal, current = bench.Arm.A1_BASELINE, bench.Arm.A2_NO_SIGNAL, bench.Arm.A3_CURRENT
    records = [
        _record(baseline, case0.id, case0.text, rounds=1, reason="turn_limit", tokens_used=10, elapsed_s=0.5),
        _record(
            no_signal,
            case0.id,
            case0.text,
            rounds=3,
            reason="no_improvement",
            tokens_used=30,
            elapsed_s=0.25,
            last_candidate_text=case0.clean_text,  # Task-4b：被回退掩盖的候选面
        ),
        _record(
            current,
            case0.id,
            rebroken,
            rounds=3,
            reason="ok",
            converged=True,
            tokens_used=50,
            elapsed_s=1.5,
            last_candidate_text=case0.clean_text,  # Task-4b：候选口径的演示面
        ),
        _record(baseline, case1.id, case1.text, rounds=1, reason="turn_limit", tokens_used=20, elapsed_s=1.0),
        _record(
            no_signal,
            case1.id,
            case1.text,
            rounds=3,
            reason="no_improvement",
            tokens_used=40,
            elapsed_s=0.75,
            last_candidate_text=case1.clean_text,
        ),
        _record(
            current, case1.id, case1.clean_text, rounds=3, reason="ok", converged=True, tokens_used=60, elapsed_s=3.0
        ),
    ]

    report = bench.summarize(records, [case0, case1])
    assert report["judgement_basis"] == "uncovered_seed_recovery"
    a1 = report["arms"]["a1_baseline"]
    a2 = report["arms"]["a2_no_signal"]
    a3 = report["arms"]["a3_current"]

    # A1：final == 原文 ⇒ 回收 0 / 下降 0 / 无回退（turn_limit 不是回退）
    assert a1["runs"] == 2
    assert a1["R_judge"] == 0.0 and a1["R_uncovered"] == 0.0 and a1["rollback_rate"] == 0.0
    assert a1["new_errors"] == 0 and a1["tokens_total"] == 30
    assert a1["elapsed_p50"] == pytest.approx(0.75) and a1["elapsed_p95"] == pytest.approx(0.975)
    assert a1["rounds_mean"] == 1.0
    # Task-4b：A1 无候选（零候选除零守卫：0.0 + 0）
    assert a1["candidates_recorded"] == 0 and a1["R_uncovered_last_candidate"] == 0.0

    # A2：no_improvement 回退原文 ⇒ 回退率 100%
    assert a2["runs"] == 2
    assert a2["R_judge"] == 0.0 and a2["R_uncovered"] == 0.0 and a2["rollback_rate"] == 1.0
    assert a2["new_errors"] == 0 and a2["tokens_total"] == 70
    assert a2["elapsed_p50"] == pytest.approx(0.5) and a2["elapsed_p95"] == pytest.approx(0.725)
    assert a2["rounds_mean"] == 3.0
    # Task-4b（W4 演示钉）：final 恒回退原文（R_uncovered = 0.0），但最后候选 = clean_text ⇒
    # 候选口径 1.0 ——「回退掩盖迭代产出」的数值化；两口径 MUST 独立（偷换即红）。
    assert a2["candidates_recorded"] == 2 and a2["R_uncovered_last_candidate"] == 1.0

    # A3：R_judge=1.0（裁判眼里全修好）但 R_uncovered < 1.0（一处 held-out 被写回）
    expected_uncovered = (places0 - probes0[0].expected_count + places1) / (places0 + places1)
    assert a3["runs"] == 2
    assert a3["R_judge"] == 1.0
    assert a3["R_uncovered"] == pytest.approx(expected_uncovered)
    assert a3["R_uncovered"] != a3["R_judge"]  # 口径不可互换（本用例的目的）
    assert a3["rollback_rate"] == 0.0 and a3["new_errors"] == 0
    assert a3["tokens_total"] == 110
    assert a3["elapsed_p50"] == pytest.approx(2.25) and a3["elapsed_p95"] == pytest.approx(2.925)
    assert a3["rounds_mean"] == 3.0
    # Task-4b：仅 case0 一条有候选（= clean_text）⇒ 池化于该记录记 1.0；与 final 口径（<1.0）独立
    assert a3["candidates_recorded"] == 1 and a3["R_uncovered_last_candidate"] == 1.0
    assert a3["R_uncovered_last_candidate"] != a3["R_uncovered"]


def test_summarize_pins_r_judge_mid_values_not_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """O1 补钉（Task 3 评审残余）：`R_judge` 是连续比值 `(v_0 − v_final) / v_0`，不是二值式
    「v_final 归零 ⇒ 1，否则 0」（旁证量也不许在口径上退化）。

    构造 v_0=3、v_final 分别 1 与 2 ⇒ `R_judge` = 2/3（单条）/ mean(2/3, 1/3) = 0.5（两条）：
    两个读数都落在非端点。单行变异自证：把 `declines.append((v0 - score_judge_violations(record))
    / v0 if v0 > 0 else 0.0)` 改成二值式 `1.0 if score_judge_violations(record) == 0 else 0.0`
    ⇒ 本用例必红（0.0 ≠ 2/3、0.0 ≠ 0.5）。
    计数**来源**用 stub（文本 ⇒ 条数映射）注入：本用例只钉算术；「v_final 从生产裁判 + 生产
    分流数出来」已由 `test_score_judge_violations_replays_production_counting` 真实链路钉住。
    """
    _require_nlp()  # detect_new_errors 仍走真实链路（本用例不对其结果断言）
    from delector.data.a1_seed_errors import SEED_CASES

    case = SEED_CASES[0]
    counts = {case.text: 3, "终稿甲": 1, "终稿乙": 2}
    monkeypatch.setattr(bench, "_counted_violations_of_text", lambda text: counts[text])
    monkeypatch.setattr(bench, "score_judge_violations", lambda record: counts[record.final_text])

    current = bench.Arm.A3_CURRENT
    single = bench.summarize([_record(current, case.id, "终稿甲")], [case])
    assert single["arms"]["a3_current"]["R_judge"] == pytest.approx(2 / 3)

    pair = bench.summarize([_record(current, case.id, "终稿甲"), _record(current, case.id, "终稿乙")], [case])
    assert pair["arms"]["a3_current"]["R_judge"] == pytest.approx(0.5)


def test_summarize_rollback_rate_requires_reverting_to_seed_text() -> None:
    """回退口径：`no_improvement` **且** final 回到原文才计（回退到中间候选不算 —— §9.5 精确口径）。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    case = SEED_CASES[0]
    records = [
        _record(bench.Arm.A3_CURRENT, case.id, case.text, rounds=3, reason="no_improvement"),
        _record(bench.Arm.A3_CURRENT, case.id, case.clean_text, rounds=3, reason="no_improvement"),
    ]
    report = bench.summarize(records, [case])
    assert report["arms"]["a3_current"]["rollback_rate"] == 0.5


def test_summarize_last_candidate_metrics_pool_only_candidate_records() -> None:
    """Task-4b：`R_uncovered_last_candidate` 仅池化「有候选」记录（Σ候选回收 / Σ有候选 probe 处数）；
    `candidates_recorded` = 有候选记录数；与 final 口径（`R_uncovered`）互相独立（偷换即红）。

    数字构造（synthetic；口径是纯字符串函数）：caseA 1 处 probe、caseB 2 处 probe；候选记录
    分别按候选回收 1/1、1/2、0/2 ⇒ 池化 2/5。本断言把分母口径钉到「有候选记录」：
    - 按记录等权 (1.0 + 0.5 + 0.0)/3 = 0.5 ≠ 2/5；
    - 把无候选记录也算进分母 (1+1+0)/(1+2+2+1) = 1/3 ≠ 2/5。

    O-4b-1 补钉（Task-4b 评审残余）：`last_candidate_text=""`（空串）是**合法候选** ——
    记录口径是「含该键即记录」（`_ChatRecorder` 侧已钉）。本断言把它纳入：
    `candidates_recorded` 含它、候选分母含其 probe 处数（2 处）。单行变异自证：把 summarize 里
    `if record.last_candidate_text is not None:` 改成**真值判断** `if record.last_candidate_text:`
    ⇒ 空串记录被静默丢弃 ⇒ 上面两条数量断言必红（candidates_recorded 3→2；池化 2/5→2/3）。
    """
    _require_nlp()
    from delector.data.a1_seed_errors import Injection

    probe_a = Injection(error_class="verb_kongruenz", kind="probe", wrong="AW", right="AR", expected_count=1)
    probe_b = Injection(error_class="artikel_genus", kind="probe", wrong="BW", right="BR", expected_count=2)
    case_a = _synthetic_case("pa", [probe_a])
    case_b = _synthetic_case("pb", [probe_b])

    records = [
        _record(bench.Arm.A3_CURRENT, "pa", "（无回收的终稿）", last_candidate_text="AR 修复形"),
        _record(bench.Arm.A3_CURRENT, "pb", "", last_candidate_text="BR 修复形"),
        _record(bench.Arm.A3_CURRENT, "pa", "AR 修复形"),  # 无候选记录：不进候选池化
        # O-4b-1：空串候选是**合法候选** —— MUST 进 candidates_recorded 与候选分母（pb 的 2 处 probe）。
        _record(bench.Arm.A3_CURRENT, "pb", "（空串候选局的终稿：不回收）", last_candidate_text=""),
    ]
    report = bench.summarize(records, [case_a, case_b])
    a3 = report["arms"]["a3_current"]

    assert a3["candidates_recorded"] == 3
    assert a3["R_uncovered_last_candidate"] == pytest.approx(2 / 5)
    # final 口径不受附带指标影响（判决面钉）：(0 + 0 + 1 + 0) / (1 + 2 + 1 + 2)
    assert a3["R_uncovered"] == pytest.approx(1 / 6)
    assert a3["R_uncovered_last_candidate"] != a3["R_uncovered"]  # 两口径不可互换

    # 零候选臂的除零守卫：A1 无记录 ⇒ 恒 0.0 + candidates_recorded=0（不得除零）
    a1 = report["arms"]["a1_baseline"]
    assert a1["candidates_recorded"] == 0 and a1["R_uncovered_last_candidate"] == 0.0


def test_dry_run_semantics_last_candidate_metrics() -> None:
    """Task-4b dry-run 语义自检（全 60 局实跑）：A1 无候选（工具轮耗尽）⇒ 0；A2/A3 20/20；
    A2 候选 1.0 而 final 0.0（回退掩盖迭代产出的演示数字）；A3 两者 ≈1.0（收敛不掩盖）。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    cases = list(SEED_CASES)
    records = bench.run_dry_run(cases)
    report = bench.summarize(records, cases)

    a1 = report["arms"]["a1_baseline"]
    assert a1["candidates_recorded"] == 0  # A1 唯一一轮被工具取证耗尽 ⇒ 永远收不到 corrected_text
    assert a1["R_uncovered_last_candidate"] == 0.0  # 零候选 ⇒ 除零守卫记 0.0

    a2 = report["arms"]["a2_no_signal"]
    assert a2["candidates_recorded"] == len(cases)  # 20/20：第 3 轮收尾回复给出 clean_text 候选
    assert a2["R_uncovered"] == 0.0  # final 恒回退原文（W4 的退化面）
    assert a2["R_uncovered_last_candidate"] == pytest.approx(1.0)  # 被回退掩盖的迭代产出

    a3 = report["arms"]["a3_current"]
    assert a3["candidates_recorded"] == len(cases)
    assert a3["R_uncovered"] == pytest.approx(1.0)
    assert a3["R_uncovered_last_candidate"] == pytest.approx(1.0)


# ── CLI（退出码 0/1/2 与输出面） ──────────────────────────────────────────────


def test_cli_exit_1_when_sample_set_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """样本集无效 ⇒ 退出码 1、不产出任何 JSON（错误只在 stderr）。"""
    from delector.data.a1_seed_errors import SEED_CASES

    broken = dataclasses.replace(SEED_CASES[0], injections=[])
    monkeypatch.setattr(bench, "load_seed_cases", lambda: [broken])

    rc = bench.main(["--dry-run", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "样本集无效" in captured.err
    assert captured.out == ""


def test_cli_exit_2_when_environment_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """环境不可用（模型/依赖）⇒ 退出码 2；与「样本集无效 = 1」语义不撞。"""
    monkeypatch.setattr(bench, "probe_environment", lambda *args, **kwargs: "德语模型不可用（stub 原因）")

    rc = bench.main(["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "[环境不可用]" in captured.err and "stub 原因" in captured.err
    assert captured.out == ""


def test_cli_exit_2_when_seed_loading_raises(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """W3 补钉（Task 2 评审欠覆盖）：种子集模块装载抛异常 ⇒ 退 2（环境归口），不崩、不是 1。

    单行变异靶点：把 main 里该 `except` 分支的 `return 2` 改成 `return 0` ⇒ 本用例必红。
    """

    def boom() -> list[Any]:
        raise ImportError("种子集模块不可用（stub 原因）")

    monkeypatch.setattr(bench, "load_seed_cases", boom)

    rc = bench.main(["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "[环境不可用]" in captured.err and "种子集模块装载失败" in captured.err and "stub 原因" in captured.err
    assert captured.out == ""


def test_probe_environment_maps_failures_to_reason() -> None:
    """probe_environment：可用 ⇒ None；模型缺失 / 加载抛错 ⇒ 原因文本（退出码 2 的单一归口）。"""
    assert bench.probe_environment(loader=lambda: object()) is None
    assert bench.probe_environment(loader=lambda: None) is not None

    def boom() -> Any:
        raise RuntimeError("德语模型加载失败（stub 原因）")

    reason = bench.probe_environment(loader=boom)
    assert reason is not None and "stub 原因" in reason


def test_probe_environment_passes_on_this_machine() -> None:
    """本机真实环境（有 de_core_news_sm）⇒ 探测必须通过（否则 dry-run 根本跑不动）。"""
    _require_nlp()
    assert bench.probe_environment() is None


def test_cli_without_mode_flag_exits_2_with_usage_copy(capsys: pytest.CaptureFixture[str]) -> None:
    """无模式旗标 ⇒ 2 + 文案「需 --dry-run 或 --real」（Task-5a：真跑已接线 ⇒ 不再有「未接线」文案）。"""
    rc = bench.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "需 --dry-run 或 --real" in captured.err
    assert captured.out == ""


def test_cli_dry_run_and_real_are_mutually_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    """`--dry-run` 与 `--real` 同给 ⇒ argparse 报错退 2（两种驱动源 MUST 不可共存）。"""
    with pytest.raises(SystemExit) as excinfo:
        bench.main(["--dry-run", "--real"])
    assert excinfo.value.code == 2
    assert "互斥" in capsys.readouterr().err


def test_cli_dry_run_json_outputs_pure_json_runrecord_list() -> None:
    """真实 CLI（子进程）：退出码 0、stdout **纯 JSON 列表**、逐篇三臂的行为与记录形状。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=str(_ROOT),
    )
    assert proc.returncode == 0, f"CLI 未按契约完成（rc={proc.returncode}）\nstderr={proc.stderr}"

    data = json.loads(proc.stdout)  # stdout 必须纯 JSON（import 期诊断行须已改道 stderr）
    assert isinstance(data, list)
    assert len(data) == len(SEED_CASES) * 3
    assert set(data[0]) == _RECORD_FIELDS
    # 逐篇轮转（设计稿 §3.2「交错执行」）：前 3 条 = 同一篇的三臂，臂序固定
    assert [record["case_id"] for record in data[:3]] == [SEED_CASES[0].id] * 3
    assert [record["arm"] for record in data[:3]] == ["a1_baseline", "a2_no_signal", "a3_current"]

    by_key = {(record["case_id"], record["arm"]): record for record in data}
    for case in SEED_CASES:
        a1 = by_key[(case.id, "a1_baseline")]
        a2 = by_key[(case.id, "a2_no_signal")]
        a3 = by_key[(case.id, "a3_current")]
        assert (a1["rounds"], a1["reason"], a1["converged"]) == (1, "turn_limit", False)
        assert (a2["rounds"], a2["reason"], a2["converged"]) == (3, "no_improvement", False)
        assert (a3["rounds"], a3["reason"], a3["converged"]) == (3, "ok", True)
        assert a1["final_text"] == case.text
        assert a2["final_text"] == case.text
        assert a3["final_text"] == case.clean_text
        # Task-4b：JSON records 的第十键（有意契约演进）—— A1 无候选；A2/A3 候选 = clean_text
        assert a1["last_candidate_text"] is None
        assert a2["last_candidate_text"] == case.clean_text
        assert a3["last_candidate_text"] == case.clean_text
        for record in (a1, a2, a3):
            assert record["model"] == bench.DRY_RUN_MODEL
            assert record["tokens_used"] > 0


def test_cli_cases_limits_run_to_first_n_seed_cases(capsys: pytest.CaptureFixture[str]) -> None:
    """`--cases N`：确定性取 SEED_CASES 前 N 篇（零 Key：--dry-run --json 全链路）。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    rc = bench.main(["--cases", "5", "--dry-run", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert len(data) == 5 * 3
    assert [record["case_id"] for record in data[:3]] == [SEED_CASES[0].id] * 3
    assert {record["case_id"] for record in data} == {case.id for case in SEED_CASES[:5]}
    assert set(data[0]) == _RECORD_FIELDS  # --json 形状契约不变（RunRecord 列表）


def test_cli_cases_invalid_values_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    """`--cases 0` / 负数 ⇒ argparse 报错退 2（在「真跑未接线」之前就拦下）。"""
    for bad in ("0", "-3"):
        with pytest.raises(SystemExit) as excinfo:
            bench.main(["--cases", bad, "--dry-run"])
        assert excinfo.value.code == 2
        assert "--cases 必须 ≥ 1" in capsys.readouterr().err


def test_cli_cases_non_integer_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """非整数 ⇒ argparse 自身报错退 2。"""
    with pytest.raises(SystemExit) as excinfo:
        bench.main(["--cases", "abc", "--dry-run"])
    assert excinfo.value.code == 2
    assert "invalid int value" in capsys.readouterr().err


def test_cli_cases_larger_than_sample_set_is_harmless(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N 大于样本数 ⇒ 切片语义（跑全部、不报错）—— 用两篇样本注入避免整集开销。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    monkeypatch.setattr(bench, "load_seed_cases", lambda: list(SEED_CASES[:2]))
    rc = bench.main(["--cases", "5", "--dry-run", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert len(data) == 2 * 3


def test_cli_cases_without_mode_flag_still_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """`--cases` 单独给（无模式旗标）仍退 2：模式必须显式（--dry-run 或 --real）。"""
    rc = bench.main(["--cases", "5"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "需 --dry-run 或 --real" in captured.err


def test_cli_text_report_prints_summary_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """文本模式带【综合记账】块（judgement_basis + 每臂九项）+ Task-4b 附带指标展示行
    （逐臂标注「附带指标 / 不进 P1/P2 判决」），数值出自 summarize。"""
    _require_nlp()
    case = _case()
    baseline, no_signal, current = bench.Arm.A1_BASELINE, bench.Arm.A2_NO_SIGNAL, bench.Arm.A3_CURRENT
    records = [
        _record(baseline, case.id, case.text, rounds=1, reason="turn_limit", tokens_used=1, elapsed_s=0.1),
        _record(
            no_signal,
            case.id,
            case.text,
            rounds=3,
            reason="no_improvement",
            tokens_used=2,
            elapsed_s=0.2,
            last_candidate_text=case.clean_text,
        ),
        _record(
            current,
            case.id,
            case.clean_text,
            rounds=3,
            reason="ok",
            converged=True,
            tokens_used=3,
            elapsed_s=0.3,
            last_candidate_text=case.clean_text,
        ),
    ]
    monkeypatch.setattr(bench, "run_dry_run", lambda cases: list(records))

    rc = bench.main(["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "judgement_basis=uncovered_seed_recovery" in captured.out
    a1_line = next(
        line for line in captured.out.splitlines() if line.startswith("[a1_baseline]") and "R_uncovered" in line
    )
    assert "R_uncovered=0.000" in a1_line and "rollback_rate=0.000" in a1_line
    a2_line = next(
        line for line in captured.out.splitlines() if line.startswith("[a2_no_signal]") and "R_uncovered" in line
    )
    assert "rollback_rate=1.000" in a2_line
    a3_line = next(
        line for line in captured.out.splitlines() if line.startswith("[a3_current]") and "R_uncovered" in line
    )
    assert "R_uncovered=1.000" in a3_line and "R_judge=1.000" in a3_line and "tokens_total=3" in a3_line

    # Task-4b：附带指标展示行（逐臂；标注「附带指标 / 不进 P1/P2 判决」；A2 = 候选 1.0 vs final 0.0 演示）
    a1_side = next(
        line
        for line in captured.out.splitlines()
        if line.startswith("[a1_baseline]") and "R_uncovered_last_candidate" in line
    )
    assert "R_uncovered_last_candidate=0.000" in a1_side and "candidates_recorded=0" in a1_side
    a2_side = next(
        line
        for line in captured.out.splitlines()
        if line.startswith("[a2_no_signal]") and "R_uncovered_last_candidate" in line
    )
    assert "R_uncovered_last_candidate=1.000" in a2_side and "candidates_recorded=1" in a2_side
    assert "附带指标" in a2_side and "不进 P1/P2 判决" in a2_side


# ── Task 4：--dry-run 不触发 rater（不发电） ─────────────────────────────────


def test_cli_dry_run_touches_no_network_and_never_reaches_the_rater(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task 4 契约 + Task-5a 增补：`--dry-run` 全链路**零网络**、不触发盲评 rater、Report 判决面不变。

        四道闸都实装（实测在本机不误伤全链路）：① socket 非回环 connect/connect_ex 与非本机
        DNS 查询 ⇒ 直接炸（回环放行是**刻意的**：asyncio 自管道走 socketpair 连回环，实测必须
        放行；真实出口由非回环闸 + `llm_client.chat` 闸把守）；② `llm_client.chat`（应用唯一
        出网口）⇒ 装成炸雷并断言**一次都没被调用**；③ Task-5a：`delector.server.load_env` ⇒
        装成「调用即 fail」并断言干跑全程零调用（运行期环境载入只许住 --real 分支）；④ 产物面：
        `--json` 输出不含 auxiliary/评级字样，且 gaming 源码**在 AST 层不引用 rater 的符号**、
        模块级 import 面不含任何仓库模块（真跑接线新增的 llm_client / delector.server 只住
        函数体内）、预热链不含 llm_client（文档字符串里提名字是允许的，故按 AST 判而非按子串扫）。
        """
    _require_nlp()
    import socket as socket_module

    import delector.services.llm_client as llm_client_module
    from delector.data.a1_seed_errors import SEED_CASES

    real_connect = socket_module.socket.connect
    real_connect_ex = socket_module.socket.connect_ex
    real_getaddrinfo = socket_module.getaddrinfo
    loopback = ("127.0.0.1", "::1", "localhost")

    def guarded_connect(sock: Any, address: Any, *args: Any) -> Any:
        if isinstance(address, tuple) and address and str(address[0]) in loopback:
            return real_connect(sock, address, *args)
        raise AssertionError(f"dry-run 触发了非回环连接：{address!r}")

    def guarded_connect_ex(sock: Any, address: Any, *args: Any) -> Any:
        if isinstance(address, tuple) and address and str(address[0]) in loopback:
            return real_connect_ex(sock, address, *args)
        raise AssertionError(f"dry-run 触发了非回环连接（connect_ex）：{address!r}")

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and host not in (*loopback, ""):
            raise AssertionError(f"dry-run 触发了非本机 DNS 查询：{host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    chat_calls: list[Any] = []

    async def forbidden_chat(*args: Any, **kwargs: Any) -> Any:
        chat_calls.append((args, kwargs))
        raise AssertionError("dry-run 触发了真实 llm_client.chat —— 必须走注入的 stub")

    monkeypatch.setattr(socket_module.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket_module.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket_module, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(llm_client_module, "chat", forbidden_chat)
    monkeypatch.setattr(bench, "load_seed_cases", lambda: [SEED_CASES[0]])

    # Task-5a 闸③：运行期环境载入（load_env）只许住 --real 分支 —— 干跑全程「调用即 fail」。
    env_stub = types.ModuleType("delector.server")
    setattr(env_stub, "load_env", lambda: pytest.fail("dry-run 触发了 load_env —— 载入点只许住 --real 分支"))
    monkeypatch.setitem(sys.modules, "delector.server", env_stub)

    rc = bench.main(["--dry-run", "--json"])
    captured = capsys.readouterr()
    assert rc == 0, f"带三重闸的 dry-run 仍应完成（rc={rc}）stderr={captured.err}"
    assert chat_calls == [], "dry-run 不得调用真实 chat（stub 是唯一驱动源）"

    data = json.loads(captured.out)
    assert len(data) == 3
    assert set(data[0]) == _RECORD_FIELDS
    assert "auxiliary" not in captured.out and "rate_pair" not in captured.out

    # AST 层 tripwire（Task-5a 更新）：rater 符号仍不得被引用；真跑接线新增的仓库 import
    # （llm_client / delector.server）**只许住函数体内** —— 模块级 import 面保持「纯 stdlib、
    # 零副作用」⇒「--dry-run 不可能触达真实出网口 / 不可能载入运行期环境」是**结构性**保证
    # （运行期的四道闸另见上方）。
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for needle in ("rate_pair", "insert_into_report"):
        assert needle not in referenced, f"gaming 源码不得引用盲评 rater 的符号：{needle!r}"
    top_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            top_level_imports.add(node.module or "")
    assert not any(name.startswith("delector") for name in top_level_imports), (
        f"gaming 源码的仓库 import MUST 全部住在函数体内（模块级 = 纯 stdlib）：{sorted(top_level_imports)}"
    )
    assert "delector.services.llm_client" not in bench._CHAIN_MODULES


# ── Task-5a：--real 真跑接线（全 stub、零 Key、零真网） ───────────────────────

#: 假 key / 假模型名 / 假 base_url —— **全部是 stub**，绝不触真凭据；反向扫描断言用的标记。
_FAKE_REAL_KEY = "sk-fake-5a-DO-NOT-LEAK-0e1f2a3b"
_FAKE_REAL_MODEL = "stub-model-5a"
_FAKE_REAL_BASE = "https://stub.invalid/v1"


def _stub_runtime_env(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """把 `delector.server` 换成 stub（**绝不 import 真模块**：真模块 import 期就执行
    `load_env()` + `create_app()`（建库 / 播种）—— 测试里 MUST NOT 触发）。返回 load_env 调用记录。"""
    calls: list[Any] = []
    stub = types.ModuleType("delector.server")
    setattr(stub, "load_env", lambda: calls.append("load_env"))
    monkeypatch.setitem(sys.modules, "delector.server", stub)
    return calls


def _install_real_stubs(
    monkeypatch: pytest.MonkeyPatch, *, key: str = _FAKE_REAL_KEY, reply_factory: Any = None
) -> tuple[list[Any], list[dict[str, Any]]]:
    """`--real` 的零 Key / 零真网 stub 面：load_env、llm_client 的 key / base_url / chat、
    生效模型名（`_effective_api_model` = harness 的非泄值判定面）。

    返回 `(load_env 调用记录, llm_client.chat 收到的 kwargs 记录)`。`reply_factory(n)` 决定
    第 n 次（1 起）chat 的回复；未给 ⇒ 装「调用即炸」的雷（该用例本不该触达真 chat）。
    """
    env_calls = _stub_runtime_env(monkeypatch)
    import delector.services.llm_client as llm_client_module

    monkeypatch.setattr(llm_client_module, "get_effective_api_key", lambda *a, **k: key)
    monkeypatch.setattr(llm_client_module, "get_effective_api_base_url", lambda *a, **k: _FAKE_REAL_BASE + "/")
    monkeypatch.setattr(bench, "_effective_api_model", lambda: _FAKE_REAL_MODEL)
    chat_calls: list[dict[str, Any]] = []

    async def stub_chat(**kwargs: Any) -> Any:
        chat_calls.append(kwargs)
        if reply_factory is None:
            raise AssertionError("本用例不应触达真 chat（llm_client.chat 必须零调用）")
        return reply_factory(len(chat_calls))

    monkeypatch.setattr(llm_client_module, "chat", stub_chat)
    return env_calls, chat_calls


def test_build_real_chat_is_production_shaped_and_key_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """真 chat 构造（生产同形）与非泄值判定面：`key_present`（bool；绝不回显 key）/ `model_name`；
    无 key ⇒ `RealRunUnavailable`。单行变异靶点：删 `build_real_chat` 的 `if not key` 守卫 ⇒ 必红。"""
    env_calls, _ = _install_real_stubs(monkeypatch)
    chat = bench.build_real_chat()
    assert isinstance(chat, bench.RealChat)
    assert chat.key_present is True  # 非泄值面：只给布尔
    assert chat.model_name == _FAKE_REAL_MODEL
    assert env_calls == []  # 构造本身不触 load_env（载入点住 main 的 --real 分支）

    import delector.services.llm_client as llm_client_module

    monkeypatch.setattr(llm_client_module, "get_effective_api_key", lambda *a, **k: "")
    with pytest.raises(bench.RealRunUnavailable):
        bench.build_real_chat()


def test_real_run_wires_production_shaped_chat_and_records(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T5a 主体：`--real` 全链路（全 stub、零 Key、零真网）。

    - `load_env` **恰调用一次**（唯一载入点、只在真跑分支）；
    - `llm_client.chat` 以**生产同形 kwargs** 被调（逐参对照 `routes.main._PolishReplyRecorder`：
      循环传入的 model 空串被忽略、以生效模型名出网；timeout / max_tokens / response_format
      原样透传、单次有界 = min(30.0s, 剩余 deadline)；api_key / base_url 构造期绑定、
      base_url 走 .rstrip("/")）；
    - 生效模型名进 `RunRecord.model`（`RealChat.model_name` 面）—— 不是 DRY_RUN_MODEL；
    - `--cases` 与 `--real` 同用照常（切片在装载后、校验前）：两篇种子 + `--cases 1` ⇒ 只跑第一篇；
    - 输出面与 dry-run 一致：`--json` = 十键 RunRecord 列表、逐篇三臂交错。
    """
    _require_nlp()
    import delector.services.llm_client as llm_client_module
    from delector.data.a1_seed_errors import SEED_CASES

    first, second = SEED_CASES[0], SEED_CASES[1]
    monkeypatch.setattr(bench, "load_seed_cases", lambda: [first, second])
    env_calls, chat_calls = _install_real_stubs(
        monkeypatch, reply_factory=lambda _n: {"corrected_text": first.clean_text, "notes_zh": []}
    )
    # 清掉 import 期诊断行（若本用例是全进程首个触发 spaCy / llm_client 装载的用例）：只清
    # 「main 之前」的噪声 —— main 自身的 stdout 契约（纯 JSON / 零输出）断言不受影响。
    capsys.readouterr()

    rc = bench.main(["--real", "--cases", "1", "--json"])
    captured = capsys.readouterr()
    assert rc == 0, f"stub 真跑应完成（rc={rc}）stderr={captured.err}"

    assert env_calls == ["load_env"]  # 恰一次（且确实发生在 --real 分支）
    assert len(chat_calls) == 3  # 恰三臂各一次（candidate-only 脚本：每臂 1 轮收到收尾候选）
    for call in chat_calls:
        assert set(call) == {
            "messages",
            "model",
            "timeout",
            "max_tokens",
            "response_format",
            "api_key",
            "base_url",
        }
        assert call["model"] == _FAKE_REAL_MODEL  # 循环的空串被忽略 ⇒ 生效模型名（生产同形）
        assert call["api_key"] == _FAKE_REAL_KEY  # key 真进了出网口（未丢失；输出面另钉零泄漏）
        assert call["base_url"] == _FAKE_REAL_BASE  # 生产 .rstrip("/") 口径
        assert call["response_format"] == llm_client_module.JSON_OBJECT
        assert 0.0 < call["timeout"] <= 30.0  # 有界：min(DEFAULT_PER_CALL_TIMEOUT_S, 剩余 deadline)
        assert 0 < call["max_tokens"] <= llm_client_module.DEFAULT_MAX_TOKENS
        assert call["messages"][0]["role"] == "system" and str(call["messages"][0]["content"]).strip()

    data = json.loads(captured.out)
    assert len(data) == 3  # --cases 1 生效（第二篇在装载后被切片拦下）
    assert [record["case_id"] for record in data] == [first.id] * 3
    assert [record["arm"] for record in data] == ["a1_baseline", "a2_no_signal", "a3_current"]
    assert set(data[0]) == _RECORD_FIELDS  # 十键契约（与 --dry-run 同形）
    assert {record["model"] for record in data} == {_FAKE_REAL_MODEL}  # 生效模型名进记录
    assert all(record["model"] != bench.DRY_RUN_MODEL for record in data)  # 未静默回退 dry 桩
    # 行为面（candidate-only 脚本）：A1/A2 固定违规 ⇒ 不降即停、回退原文；A3 生产分流见 v==0 ⇒ 收敛
    assert (data[0]["reason"], data[0]["converged"], data[0]["final_text"]) == (
        "no_improvement",
        False,
        first.text,
    )
    assert (data[2]["reason"], data[2]["converged"], data[2]["final_text"]) == ("ok", True, first.clean_text)
    assert all(record["last_candidate_text"] == first.clean_text for record in data)  # 透明记录面照常

    # 真跑前 stderr 的非泄值事实行：布尔 + 模型名齐备；key 本体绝不出现。
    assert "key 存在=True" in captured.err and _FAKE_REAL_MODEL in captured.err
    assert _FAKE_REAL_KEY not in captured.out and _FAKE_REAL_KEY not in captured.err


def test_real_run_without_key_exits_2_before_any_chat(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """无 Key ⇒ 前置退 2（人话原因 + `key 存在=False`）；**绝不**静默回退 dry 桩、先于任何 chat。

    单行变异靶点：删 `build_real_chat` 的 `if not key` 守卫 ⇒ 本用例必红（会继续走到 chat）。
    """
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    monkeypatch.setattr(bench, "load_seed_cases", lambda: [SEED_CASES[0]])
    env_calls, chat_calls = _install_real_stubs(monkeypatch, key="")
    # 清掉 import 期诊断行（若本用例是全进程首个触发 spaCy / llm_client 装载的用例）：只清
    # 「main 之前」的噪声 —— main 自身的 stdout 契约（纯 JSON / 零输出）断言不受影响。
    capsys.readouterr()

    rc = bench.main(["--real", "--json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""  # 零输出：不产出部分结果、也不回退 dry 桩的 JSON
    assert "key 存在=False" in captured.err and "API Key" in captured.err
    assert "Traceback" not in captured.err
    assert env_calls == ["load_env"]  # 载入仍发生 —— 正是它给出「无 key」的事实
    assert chat_calls == []  # 先于任何出网


def test_real_run_upstream_error_fails_loudly_without_partial_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """上游 `LLMError` ⇒ 显式失败：退 2 + stderr 人话原因；**零部分结果**（stdout 全空）。

    第 1 次 chat 成功、第 2 次抛 ⇒ 若实现有「静默部分结果」路径，stdout 会出现记录 —— 本断言即闸；
    同时钉「无重试」（chat 恰 2 次）与「异常面只透 detail、不透 raw」（raw 可能带凭据 ⇒ 假 key
    塞进 raw，断言其绝不外泄）。
    """
    _require_nlp()
    import delector.services.llm_client as llm_client_module
    from delector.data.a1_seed_errors import SEED_CASES

    case = SEED_CASES[0]

    def reply_factory(n: int) -> Any:
        if n == 1:
            return {"corrected_text": case.clean_text, "notes_zh": []}
        raise llm_client_module.LLMError(
            "AI 服务连接失败（stub 上游原因）", raw=f"stub raw 可能带凭据：{_FAKE_REAL_KEY}"
        )

    monkeypatch.setattr(bench, "load_seed_cases", lambda: [case])
    env_calls, chat_calls = _install_real_stubs(monkeypatch, reply_factory=reply_factory)
    # 清掉 import 期诊断行（若本用例是全进程首个触发 spaCy / llm_client 装载的用例）：只清
    # 「main 之前」的噪声 —— main 自身的 stdout 契约（纯 JSON / 零输出）断言不受影响。
    capsys.readouterr()

    rc = bench.main(["--real", "--json"])
    captured = capsys.readouterr()
    assert rc == 2  # 退码钉死：上游失败属「环境不可用」类（1 是样本集无效，不复用）
    assert captured.out == ""  # 绝不静默部分结果
    assert "[真跑失败]" in captured.err and "stub 上游原因" in captured.err
    assert "Traceback" not in captured.err
    assert env_calls == ["load_env"]
    # 第 1 次成功、第 2 次触发重试机制（最多 4 次尝试，即 1 原始 + 3 重试）⇒ 共 1 + 4 = 5 次，随后显式失败
    assert len(chat_calls) == 5
    assert _FAKE_REAL_KEY not in captured.err  # raw 不透出 ⇒ 凭据无外泄通道


def test_real_run_text_mode_reports_records_and_summary_like_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--real` 文本模式与 dry-run 同构：逐条全量记录 + 【综合记账】块；头行如实标注真跑模式
    （MUST NOT 复读 dry-run 的「零 Key」字样）。"""
    _require_nlp()
    from delector.data.a1_seed_errors import SEED_CASES

    case = SEED_CASES[0]
    monkeypatch.setattr(bench, "load_seed_cases", lambda: [case])
    env_calls, chat_calls = _install_real_stubs(
        monkeypatch, reply_factory=lambda _n: {"corrected_text": case.clean_text, "notes_zh": []}
    )
    # 清掉 import 期诊断行（若本用例是全进程首个触发 spaCy / llm_client 装载的用例）：只清
    # 「main 之前」的噪声 —— main 自身的 stdout 契约（纯 JSON / 零输出）断言不受影响。
    capsys.readouterr()

    rc = bench.main(["--real"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "【综合记账】judgement_basis=uncovered_seed_recovery" in captured.out
    a3_line = next(
        line for line in captured.out.splitlines() if line.startswith("[a3_current]") and "R_uncovered=" in line
    )
    assert "R_uncovered=1.000" in a3_line  # 收敛 ⇒ 回收率 1.0（真实链路算出来的，非 stub 数字）
    assert "--real" in captured.out and "零 Key" not in captured.out  # 头行如实标注，不复读干跑声明
    # 真链路确实被驱动（防「--real 静默回退 dry 桩」：load_env 恰一次 + 真 chat 被调过）
    assert env_calls == ["load_env"] and chat_calls


# ── 零 Key 红线（产物级 tripwire） ────────────────────────────────────────────


def test_harness_source_confines_key_and_env_loading_to_the_real_branch() -> None:
    """零 Key 红线的产物级钉子（Task-5a 起分两面；承 Task 2 的 tripwire 显式演进）。

    `--real` 已接线 ⇒ 源码允许出现 Key 载入调用，但 MUST 被夹住：
    1. 不含 `DEEPSEEK_API_KEY` 字样（绝不按环境变量名直读 key —— 一律走 llm_client 判定面）；
    2. `load_env` 的**调用点恰一处**（AST Call 计数 = 「唯一载入点」的产物级证据；
       运行期面另有 dry-run 用例的「调用即炸」stub 钉住「只住 --real 分支」）。
    """
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in source, "绝不按环境变量名直读 key（走 llm_client 的判定面）"
    tree = ast.parse(source)
    load_env_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load_env"
    ]
    assert len(load_env_calls) == 1, f"load_env 调用点必须恰一处（实际 {len(load_env_calls)}）"
