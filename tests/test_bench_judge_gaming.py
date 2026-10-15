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
   stderr）；无 `--dry-run` 时未接线 ⇒ 2，**不打真网络**。
7. **零 Key 红线的产物级钉子**：骨架源码不出现任何 Key 载入路径（真跑在 Task 5/6
   才接线；届时本测试随接线显式更新 —— 它是 tripwire，不是永久禁令）。

反挂死纪律：无 sleep / 无线程；唯一的子进程调用带固定 timeout（≤120s，实测 CLI 全
干跑约 10s 量级）。
"""

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
    """ArmConfig / RunRecord 的字段契约（Task 3 直接消费 RunRecord 的这 9 个字段）。"""
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
    assert all(call["chat"] is stub_chat for call in captured)
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

    for record in (r1, r2, r3):
        assert record.tokens_used > 0
        assert record.elapsed_s >= 0.0
        assert record.model == bench.DRY_RUN_MODEL

    # 确定性（同输入同输出；elapsed_s 是墙钟观测值，不入断言）
    again = bench.run_arm(case, bench.Arm.A3_CURRENT, chat=bench.build_dry_run_chat(case))
    assert (again.final_text, again.rounds, again.reason, again.converged, again.tokens_used) == (
        r3.final_text,
        r3.rounds,
        r3.reason,
        r3.converged,
        r3.tokens_used,
    )


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


def test_cli_without_dry_run_is_not_wired_and_touches_no_network(capsys: pytest.CaptureFixture[str]) -> None:
    """Task 2 骨架不接线真跑：无 --dry-run ⇒ 2 + 人话提示，绝不触任何出网路径。"""
    rc = bench.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "真跑" in captured.err and "未接线" in captured.err
    assert captured.out == ""


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
        for record in (a1, a2, a3):
            assert record["model"] == bench.DRY_RUN_MODEL
            assert record["tokens_used"] > 0


# ── 零 Key 红线（产物级 tripwire） ────────────────────────────────────────────


def test_harness_source_has_no_key_loading_path() -> None:
    """骨架源码不得出现任何 Key 载入路径（真跑接线属 Task 5/6，届时显式更新本测试）。"""
    source = _SCRIPT.read_text(encoding="utf-8")
    for needle in ("load_env(", "get_effective_api_key", "DEEPSEEK_API_KEY"):
        assert needle not in source, f"骨架不得触 Key 载入路径：{needle!r}"
