"""workbench iframe 视觉闸门的定向测试（纯静态，不启动浏览器）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import workbench_gates  # noqa: E402


def test_repo_workbench_gates_pass() -> None:
    report = workbench_gates.evaluate()
    assert report["ok"], json.dumps(report["gates"], ensure_ascii=False, indent=2)


def test_literal_budgets_are_pinned_to_measured_values() -> None:
    """上限钉在实测值上：改进后必须同步下调，不允许留余量让字面量回涨。"""
    gates = {gate["name"]: gate for gate in workbench_gates.evaluate()["gates"]}
    hex_gate = gates["hex literals outside token blocks"]
    rgba_gate = gates["unique rgba literals outside token blocks"]
    assert hex_gate["actual"] == workbench_gates.WB_HEX_BUDGET
    assert rgba_gate["actual"] == workbench_gates.WB_RGBA_BUDGET


def test_token_blocks_are_exempt_from_literal_budget() -> None:
    css = ':root{--ink:#112233}[data-theme="dark"]{--ink:#ddeeff}.a{color:#123456}'
    assert workbench_gates.count_hex([css]) == 1


def test_html_inline_style_literals_are_counted() -> None:
    html = '<div style="color:#aabbcc"><p style="font-size:12px">ok</p></div>'
    assert workbench_gates.count_hex([], html) == 1


def test_rgba_counts_unique_values_outside_token_blocks() -> None:
    css = (
        ':root{--shadow:rgba(0,0,0,.3)}'
        ".a{background:rgba(0,0,0,.5)}"
        ".b{background:rgba(0, 0, 0, 0.5)}"
        ".c{background:rgba(1,2,3,.2)}"
    )
    assert workbench_gates.unique_rgba([css]) == {"rgba(0,0,0,.5)", "rgba(1,2,3,.2)"}


def test_dark_contrast_resolves_from_dark_tokens() -> None:
    """暗色必须按 workbench 自己的 [data-theme] 重绑解析，不能复用亮色值。"""
    light = {item["id"]: item for item in workbench_gates.evaluate_contrast(dark=False)}
    dark = {item["id"]: item for item in workbench_gates.evaluate_contrast(dark=True)}
    assert light["light:on-accent-on-accent"]["resolved"]["foreground"] == "#fff"
    assert dark["dark:on-accent-on-accent"]["resolved"]["foreground"] == "#241512"
    assert dark["dark:on-accent-on-accent"]["ratio"] >= 4.5
    # 暗色的 --muted / --pencil / --ink-faint 曾有未重绑或过暗的欠账
    for pair_id in ("dark:muted-on-warm", "dark:pencil-on-paper", "dark:ink-faint-on-paper"):
        assert dark[pair_id]["ok"], (pair_id, dark[pair_id])


def test_undefined_reference_detection() -> None:
    defined = {"--ink", "--paper"}
    text = ".a{color:var(--ink)}.b{color:var(--fg)}.c{background:var(--ghost, #fff)}"
    assert workbench_gates.undefined_in(text, defined) == ["--fg", "--ghost"]


def test_self_reference_detection() -> None:
    css = (
        ":root{--accent:var(--accent,#c14a2b);--ok:var(--ink);}"
        ".a{--line:var(--line)}"
    )
    assert workbench_gates.self_references_in(css) == ["--accent", "--line"]


def test_self_reference_is_not_matched_by_other_tokens() -> None:
    css = ":root{--accent:var(--coral);--ink:var(--ink-soft);}"
    assert workbench_gates.self_references_in(css) == []


def test_reference_detection_ignores_comments() -> None:
    css = "/* var(--dead) --x: var(--x); */ .a{color:var(--ink)}"
    assert workbench_gates.undefined_in(css, {"--ink"}) == []
    assert workbench_gates.self_references_in(css) == []


def test_repo_has_no_undefined_or_self_reference_debt() -> None:
    assert workbench_gates.find_undefined_references() == []
    assert workbench_gates.find_self_references() == []


@pytest.mark.parametrize("dark", [False, True])
def test_every_contrast_pair_resolves_real_colors(dark: bool) -> None:
    """token 解析不出颜色时 ratio 会被算成 0 —— 那会把配置错误伪装成对比度问题。"""
    for item in workbench_gates.evaluate_contrast(dark=dark):
        assert item["resolved"]["foreground"], item
        assert item["resolved"]["background"], item
