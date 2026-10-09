# -*- coding: utf-8 -*-
"""分层剖析汇总脚本的可执行输出门禁。"""

import os
import re
import subprocess
import sys
from pathlib import Path

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


def test_targets_are_explicit_assumptions(bench_out: str) -> None:
    for key in TARGET_KEYS:
        assert _number(bench_out, key) > 0.0
    source = _value(bench_out, "target_source")
    for phrase in ("本基准的假设值", "未经用户确认", "条件②", "完全依赖", "结论会变"):
        assert phrase in source, f"target_source 缺少 `{phrase}`：{source}"


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


def test_targets_are_marked_unconfirmed_and_headroom_is_printed(bench_out: str) -> None:
    """目标值必须与余量**绑定出现**：拆开搬运的余量数字会被当成已确认事实。"""
    assert _value(bench_out, "target_status") == "unconfirmed"
    for scenario in ("cold_start", "long_read_cold", "cards_list", "warm_read"):
        assert _number(bench_out, f"headroom_to_2x_target_{scenario}", "x") > 0.0, bench_out
    note = _value(bench_out, "headroom_note")
    assert "2×目标" in note and "target_status" in note, note


def test_scenario_scope_is_declared_as_proxy(bench_out: str) -> None:
    """四场景是**代理口径**，不声明就会被下游当端到端 p95 写进 ADR。"""
    note = _value(bench_out, "scenario_scope_note")
    assert "代理" in note, note
    assert "端到端" in note, note
