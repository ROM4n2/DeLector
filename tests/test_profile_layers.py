# -*- coding: utf-8 -*-
"""分层剖析汇总脚本的可执行输出门禁。"""

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_profile_layers.py"
UPSTREAM_SCRIPTS = (
    "bench_cards_endpoint.py",
    "bench_spacy_unit.py",
    "bench_long_read.py",
    "bench_cold_start.py",
)
TARGET_KEYS = (
    "target_cold_start_s",
    "target_long_read_cold_s",
    "target_cards_list_s",
    "target_warm_read_s",
)
SCENARIO_KEYS = (
    "scenario_cards_list_s",
    "scenario_long_read_cold_s",
    "scenario_warm_read_s",
    "startup_s",
)


def _load_script_module() -> ModuleType:
    """按路径加载 tools/bench_profile_layers.py（tools/ 不是 package，只能按路径加载）。

    路由补丁的四种输入组合现实中只会落一个分支，故必须直接调用 `_verdict` 逐一断言
    —— 靠实跑输出只能覆盖到当前机器恰好命中的那一条。
    """
    spec = importlib.util.spec_from_file_location("bench_profile_layers_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 一个"全部未超 2×目标"的基线 p95（秒）；逐个 override 制造"仅某场景超标"的输入。
_UNDER_P95: dict[str, float] = {
    "cards_list": 0.05,
    "long_read_cold": 0.05,
    "warm_read": 0.00002,
    "cold_start": 0.05,
}
_OVER = 99.0  # 远超任一 2×目标 ⇒ 该场景必判"超标"


def _p95_mapping(**overrides: float) -> dict[str, float]:
    mapping = dict(_UNDER_P95)
    mapping.update(overrides)
    return mapping


def _run_bench() -> str:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        check=False,
    )
    assert proc.returncode == 0, (
        f"分层基准退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


@pytest.fixture(scope="module")
def bench_out() -> str:
    return _run_bench()


def _value(out: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}=(.+)$", out, re.MULTILINE)
    assert match is not None, f"输出缺少 `{key}=...`\n{out}"
    return match.group(1)


def _number(out: str, key: str, suffix: str = "") -> float:
    raw = _value(out, key)
    match = re.fullmatch(rf"([0-9]+(?:\.[0-9]+)?){re.escape(suffix)}", raw)
    assert match is not None, f"`{key}` 不可解析：{raw}"
    return float(match.group(1))


def test_script_exists_and_reuses_all_upstream_benchmarks() -> None:
    assert SCRIPT.is_file(), f"缺少分层汇总脚本：{SCRIPT}"
    src = SCRIPT.read_text(encoding="utf-8")
    for name in UPSTREAM_SCRIPTS:
        assert name in src, f"未复用前置基准 `{name}`"
    assert "subprocess.run" in src


def test_new_files_have_no_type_check_suppressions() -> None:
    for path in (SCRIPT, Path(__file__)):
        src = path.read_text(encoding="utf-8")
        assert re.search(r"type:\s*ignore|#\s*noqa|mypy:\s*disable-error-code", src) is None


def test_all_upstream_benchmarks_ran(bench_out: str) -> None:
    for name in ("cards_endpoint", "spacy_unit", "long_read", "cold_start"):
        assert _value(bench_out, f"source_bench_{name}") == "ok", bench_out


def test_required_layer_rows_are_parseable(bench_out: str) -> None:
    python_pct = _number(bench_out, "python_cpu_pct", "%")
    sql_pct = _number(bench_out, "sql_pct", "%")
    cards_pct = _number(bench_out, "scenario_cards_python_pct", "%")
    longread_pct = _number(bench_out, "scenario_longread_python_pct", "%")
    assert python_pct > 0.0
    assert 0.0 < sql_pct <= 100.0
    assert cards_pct > 0.0
    assert longread_pct > 0.0
    weighting = _value(bench_out, "python_cpu_weighting")
    assert "segment_D_ms" in weighting and "cold_ms" in weighting
    assert "跨口径" in _value(bench_out, "scenario_longread_python_note")


def test_four_scenario_timings_and_startup_are_positive(bench_out: str) -> None:
    for key in SCENARIO_KEYS:
        assert _number(bench_out, key) > 0.0
    # 原先这里断言 `startup_s == scenario_cold_start_s` —— 那是**恒真断言**：两行由同一个
    # 变量、同一精度打印出来，任何实现（含打桩成 0）都会绿。换成有信息量的跨场景关系：
    # 卡盒 20k（一次全表 SQL + 2 万行物化 + FSRS 递推）必然远慢于热读（一次 dict 命中），
    # 量级差在 10³ 以上 ⇒ 这条关系只在"某一侧根本没测到"时才会翻，不是能跑就绿。
    cards_list_s = _number(bench_out, "scenario_cards_list_s")
    warm_read_s = _number(bench_out, "scenario_warm_read_s")
    assert cards_list_s > warm_read_s * 100, (
        f"卡盒列表 {cards_list_s}s 未比热读 {warm_read_s}s 高两个数量级："
        f"其中一侧测的已不是它自称的东西\n{bench_out}"
    )


def test_unmeasured_layers_are_explicit_and_explained(bench_out: str) -> None:
    assert _value(bench_out, "network_pct") == "unmeasured"
    note = _value(bench_out, "network_note")
    assert "外部" in note
    assert "不发" in note
    # 逐路径事实（Task 5b 修正）：旧文案称"为避免真发需 key/付费请求"是**错的** ——
    # 只有 AI 需 key，TTS/RSS 免 key。理由写错会原样搬进 ADR，故把三条路径的真实
    # 依赖钉成断言，并禁止那条错误措辞复活。
    assert "DEEPSEEK_API_KEY" in note, f"network_note 必须逐路径写明 AI 需 key：{note}"
    assert "PRESET_FEEDS" in note, f"network_note 必须写明 RSS 是公开预设源：{note}"
    assert "免 key" in note, f"network_note 必须区分 TTS/RSS 免 key：{note}"
    assert "贡献为 0" in note, f"network_note 必须写明网络层对本次四场景的贡献：{note}"
    assert "付费" not in note, f"network_note 仍在沿用「需 key/付费」的错误理由：{note}"
    assert _value(bench_out, "frontend_pct") == "unmeasured"
    assert "浏览器自动化" in _value(bench_out, "frontend_note")
    assert _value(bench_out, "android") == "unmeasured"
    assert "Android" in _value(bench_out, "android_note")
    rss = _value(bench_out, "rss_mb")
    if rss == "unmeasured":
        assert "Windows" in _value(bench_out, "rss_note")
    else:
        assert float(rss) > 0.0
        assert "resource" in _value(bench_out, "rss_note")


def test_targets_are_explicit_confirmed_value_judgements(bench_out: str) -> None:
    """目标值来源已从"未确认假设"改为"用户拍板 + 价值判断"，且联动警示必须保留。"""
    for key in TARGET_KEYS:
        assert _number(bench_out, key) > 0.0
    source = _value(bench_out, "target_source")
    for phrase in ("用户拍板", "价值判断", "体验预算", "无客观对错", "条件②", "完全依赖", "结论"):
        assert phrase in source, f"target_source 缺少 `{phrase}`：{source}"
    assert "未经用户确认" not in source, f"target_source 仍在宣称未确认：{source}"


def test_p95_is_measured_per_scenario_and_sample_size_is_declared(bench_out: str) -> None:
    """Task 5b：四场景 p95 必须真有数字（不再是 unmeasured），且**样本量必须申报**。

    为什么必须钉样本量：n 决定 p95 能支撑什么强度的结论（n=5 的 p95≈最大值、
    系统性低估尾部），不报 n 的 p95 数字会被下游当成"已确证"直接写进 ADR。
    """
    for scenario in ("cold_start", "long_read_cold", "cards_list", "warm_read"):
        assert _number(bench_out, f"scenario_{scenario}_p95_s") > 0.0, bench_out
    assert int(_value(bench_out, "p95_n")) >= 5, bench_out
    note = _value(bench_out, "p95_note")
    for phrase in ("样本", "同一批", "低估", "20"):
        assert phrase in note, f"p95_note 缺少 `{phrase}`：{note}"


def test_verdict_separates_both_conditions_and_and_result(bench_out: str) -> None:
    verdict = _value(bench_out, "verdict")
    condition_one = re.search(r"条件①=(成立|不成立|无法判定)", verdict)
    condition_two = re.search(r"条件②=(成立|不成立|仅可否证|无法判定)", verdict)
    and_result = re.search(r"AND结果=(成立|不成立|无法判定)", verdict)
    assert condition_one is not None, verdict
    assert condition_two is not None, verdict
    assert and_result is not None, verdict
    assert "p95" in verdict
    two = condition_two.group(1)
    if condition_one.group(1) == "不成立":
        assert and_result.group(1) == "不成立" and "建议O0" in verdict
    elif two == "成立":
        assert and_result.group(1) == "成立", verdict
    elif two == "不成立":
        # 强结论只在样本量足够时才允许出现（见 p95_note 的统计口径）
        assert int(_value(bench_out, "p95_n")) >= 20, f"n<20 不许写条件②=不成立：{verdict}"
        assert and_result.group(1) == "不成立" and "建议O0" in verdict
    else:  # 仅可否证 / 无法判定
        assert and_result.group(1) == "无法判定"
        assert "不足以判定" in verdict and "缺" in verdict
        if two == "仅可否证":
            assert int(_value(bench_out, "p95_n")) < 20, f"n≥20 时不该停留在仅可否证：{verdict}"


def test_targets_are_confirmed_and_headroom_is_printed(bench_out: str) -> None:
    """目标值已拍板（confirmed），但仍须与余量**绑定出现**：余量数字仍随目标值联动。"""
    assert _value(bench_out, "target_status") == "confirmed"
    status_note = _value(bench_out, "target_status_note")
    assert "confirmed" in status_note and "未确认" not in status_note, status_note
    for scenario in ("cold_start", "long_read_cold", "cards_list", "warm_read"):
        assert _number(bench_out, f"headroom_to_2x_target_{scenario}", "x") > 0.0, bench_out
    note = _value(bench_out, "headroom_note")
    assert "2×目标" in note and "target_status" in note, note


def test_scenario_scope_is_declared_as_proxy(bench_out: str) -> None:
    """四场景是**代理口径**，不声明就会被下游当端到端 p95 写进 ADR。"""
    note = _value(bench_out, "scenario_scope_note")
    assert "代理" in note, note
    assert "端到端" in note, note


def test_condition_two_uses_exactly_three_scenarios_and_warm_read_is_sentinel(bench_out: str) -> None:
    """门禁：条件②判定集**恰 3 场景**，warm_read 只作缓存哨兵、被排除在判定集之外。

    为什么必须钉死：warm_read 是 µs 级 dict 命中，与目标差 4 个数量级 —— 一旦被悄悄加回
    判定集，它会永远"不超标"从而稀释门；漏掉某个判定场景则会让条件②口径在无人察觉下改变。
    """
    scenarios = _value(bench_out, "condition_two_scenarios")
    members = scenarios.split(",")
    assert members == ["cards_list", "long_read_cold", "cold_start"], scenarios
    assert len(members) == 3, scenarios
    assert "warm_read" not in members, scenarios
    assert _value(bench_out, "warm_read_role") == "sentinel"
    assert "不参与条件②" in _value(bench_out, "warm_read_sentinel_note")
    # 哨兵仍必须被测量并输出（移出判定集 ≠ 不再测量）
    assert _number(bench_out, "scenario_warm_read_p95_s") > 0.0, bench_out


def test_warm_read_over_target_does_not_trigger_condition_two() -> None:
    """哨兵不得参与门：把 warm_read 拉到远超目标，条件②仍不得判"成立"。"""
    module = _load_script_module()
    condition_two = getattr(module, "_condition_two")
    # warm_read 巨大、判定集三场景全部未超 ⇒ 条件②只能是"不成立"（n=20）而非"成立"。
    text, _detail, over = condition_two(_p95_mapping(warm_read=_OVER), 20)
    assert text != "成立", text
    assert over == (), over
    assert "warm_read" not in _detail or "超门限" not in _detail, _detail


@pytest.mark.parametrize(
    ("overrides", "required", "forbidden"),
    [
        # 仅 cold_start 超标 ⇒ O0 杠杆（spaCy 惰性加载）+ 明说 O2 修不了它
        (
            {"cold_start": _OVER},
            ("建议O0杠杆", "spaCy", "修不了它", "初始化/IO", "O2"),
            ("建议O2评估",),
        ),
        # 仅 cards_list 超标 ⇒ O2 评估（热点下沉）
        ({"cards_list": _OVER}, ("建议O2评估", "热点下沉"), ("建议O0杠杆",)),
        # 仅 long_read_cold 超标 ⇒ O2 评估（热点下沉）
        ({"long_read_cold": _OVER}, ("建议O2评估", "热点下沉"), ("建议O0杠杆",)),
        # 同时超标 ⇒ 先做 O0 压冷启动，再评估 O2
        ({"cold_start": _OVER, "cards_list": _OVER}, ("先", "O0", "O2"), ()),
    ],
)
def test_verdict_routes_remediation_by_over_limit_scenario(
    overrides: dict[str, float],
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    """门与修法不得错配：条件②成立时必须**按超标场景**给出对应修法方向。

    现实实跑只会落一个分支，故这里对四种输入组合直接调用 `_verdict` 逐一断言。
    """
    module = _load_script_module()
    verdict_text = getattr(module, "_verdict")(85.9, _p95_mapping(**overrides), 20)
    assert "条件②=成立" in verdict_text, verdict_text
    for phrase in required:
        assert phrase in verdict_text, f"缺少 `{phrase}`：{verdict_text}"
    for phrase in forbidden:
        assert phrase not in verdict_text, f"不该出现 `{phrase}`：{verdict_text}"


def test_scenario_partition_gate_is_invoked_at_import() -> None:
    """④ 启动期分区门禁的**调用点**必须存在 —— 否则门禁被静默拆除。

    现况：`bench_profile_layers.py` 定义了 `_validate_scenario_partition()` 并在模块层调用
    （`_validate_scenario_partition()` 那一行），但**没有任何测试**钉住这行调用 ⇒ 删掉调用
    而保留函数与正确常量时，其余测试全绿：门禁被静默拆除，warm_read 就能悄悄回到条件②判定集
    而无人察觉。故这里两路钉死：
    ① AST 断言**模块层真的调用了它**（只保留定义不够）；
    ② 直接调用函数，断言之错的分区会 raise（函数确实在执法，不是空壳）。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    module_level_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_validate_scenario_partition"
    ]
    assert module_level_calls, (
        "bench_profile_layers.py 模块层不再调用 `_validate_scenario_partition()`："
        "启动期分区门禁被拆除（warm_read 可悄悄回到条件②判定集而无人察觉）"
    )
    # ② 函数确实在执法：合法分区不抛；把判定集改成含 warm_read 必须 raise。
    module = _load_script_module()
    validate = getattr(module, "_validate_scenario_partition")
    validate()  # 合法分区：不抛
    # 用 setattr 而非直接属性赋值：`module` 是 `ModuleType`，直接赋值会被 mypy 判 attr-defined，
    # 而本轮禁用类型检查豁免，故走 setattr。
    setattr(module, "CONDITION_TWO_SCENARIOS", ("cards_list", "long_read_cold", "warm_read"))
    with pytest.raises(AssertionError):
        validate()


def test_route_for_empty_over_limit_is_explicit() -> None:
    """⑥ `_route_for_over_limit(())` 空集必须**显式处理**，不得落进「建议O2评估」。

    现况：空集只因 `_verdict` 只在 `over` 非空（条件②成立）时调用它而**不可达**；一旦未来
    有人直接调用，会落到兜底的「建议O2评估（热点下沉）」——把"没有超标场景"误读成"卡盒/长文
    超标"，把修法方向带偏。故显式 raise，让误用立刻暴露，而不是给一个假的修法建议。
    """
    module = _load_script_module()
    route = getattr(module, "_route_for_over_limit")
    with pytest.raises(ValueError):
        route(())
