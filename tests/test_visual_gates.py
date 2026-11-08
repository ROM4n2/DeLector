"""P0 视觉闸门与 computed-style 比对的定向测试（不启动浏览器）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import visual_baseline  # noqa: E402
import visual_gates  # noqa: E402


def _style() -> str:
    return visual_gates.STYLE_CSS.read_text(encoding="utf-8")


def test_repo_visual_gates_pass() -> None:
    report = visual_gates.evaluate()
    assert report["ok"], json.dumps(report["gates"], ensure_ascii=False, indent=2)


def test_hex_gate_detects_extra_literals() -> None:
    css = _style()
    before = visual_gates.count_hex_outside_root(css)
    assert before <= visual_gates.HEX_BUDGET

    mutating = css + "\n.visual-gate-probe { color: #123456; }\n"
    assert visual_gates.count_hex_outside_root(mutating) == before + 1
    assert before + 1 <= visual_gates.HEX_BUDGET  # 未触硬顶的单点新增仍允许，接近上限时另有告警

    probes = visual_gates.HEX_BUDGET - before + 1
    exhausted = css + "".join(f"\n.probe-{i} {{ color: #{i:06x}; }}\n" for i in range(probes))
    assert visual_gates.count_hex_outside_root(exhausted) > visual_gates.HEX_BUDGET


def test_root_tokens_are_exempt_from_hex_budget() -> None:
    """换主题色应改 :root token，而不是新增规则体字面量。"""
    css = ":root { --ink: #112233; } .card { color: var(--ink); }"
    assert visual_gates.count_hex_outside_root(css) == 0
    assert visual_gates.count_hex_outside_root(":root{--ink:#112233}.card{color:#112233}") == 1


def test_rgba_gate_counts_unique_values() -> None:
    css = ".a{color:rgba(0,0,0,.5)}.b{color:rgba(0, 0, 0, 0.5)}.c{color:rgba(1,2,3,.2)}"
    assert visual_gates.unique_rgba_values(css) == {"rgba(0,0,0,.5)", "rgba(1,2,3,.2)"}


def test_literal_caps_are_hard_ceilings_with_headroom() -> None:
    """新上限是硬顶而非目标值：实测必须仍低于逼近阈值，且不触发告警。"""
    report = {gate["name"]: gate for gate in visual_gates.evaluate()["gates"]}
    for name, budget in (
        ("hex literals outside :root", visual_gates.HEX_BUDGET),
        ("unique rgba literals", visual_gates.RGBA_BUDGET),
    ):
        gate = report[name]
        assert gate["ok"], gate
        assert gate["actual"] <= budget * visual_gates.NEAR_LIMIT_RATIO, gate
        assert gate["warning"] == "", gate


def test_literal_near_limit_warning_mentions_token() -> None:
    assert visual_gates.literal_gate_warning(581, 700) == ""
    assert visual_gates.literal_gate_warning(629, 700) == ""
    message = visual_gates.literal_gate_warning(630, 700)
    assert "90%" in message
    assert "新增字面量应优先改成 token" in message
    # 告警只提示，不改判 ok
    gate = visual_gates.GateResult(name="probe", ok=True, actual=630, budget=700, warning=message)
    assert gate.ok


def test_infinite_gate_ignores_comments() -> None:
    css = "/* animation: spin 1s infinite; */ .a { animation: spin 1s infinite; }"
    assert visual_gates._INFINITE_RE.findall(visual_gates.strip_comments(css)) == ["infinite"]


def test_contrast_math_known_values() -> None:
    assert visual_gates.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.01)


def test_contrast_gate_detects_root_color_regression() -> None:
    css = _style()
    report = visual_gates.evaluate_contrast(css)
    assert all(item["ok"] for item in report if not item["advisory"])

    regressed = re.sub(r"(--ink\s*:\s*)#[0-9a-fA-F]{3,8}", r"\g<1>#e8e2d8", css, count=1)
    assert regressed != css
    changed = {item["id"]: item for item in visual_gates.evaluate_contrast(regressed)}
    assert changed["ink-on-paper"]["ratio"] < 4.5
    assert not changed["ink-on-paper"]["ok"]


def test_p1_contrast_debts_are_gated_and_cleared() -> None:
    """P1 的 5 组欠账必须已移入闸门（非 advisory）且实测达标。"""
    report = {item["id"]: item for item in visual_gates.evaluate_contrast(_style())}
    expected = {
        "muted-on-paper": 4.5,
        "ink-faint-on-paper": 4.5,
        "coral-on-paper": 4.5,
        "white-on-coral": 4.5,
        "mustard-ink-on-paper": 4.5,
    }
    for pair_id, threshold in expected.items():
        item = report[pair_id]
        assert not item["advisory"], pair_id
        assert item["ratio"] >= threshold, (pair_id, item["ratio"])


def test_mustard_gate_rejects_text_usage() -> None:
    css = (
        ":root{--mustard:#e9b94a}"
        ".ok{border-left:1px solid var(--mustard)}"
        ".bad{color:var(--mustard)}"
        ".ink{color:var(--mustard-ink)}"
    )
    violations = visual_gates.find_mustard_text_usage(css)
    assert violations == ["color: var(--mustard)"]


def test_token_mirrors_agree_for_p1_pairs() -> None:
    """style.css 的 :root 与 workbench 用的 tokens.css 必须给同一组值。"""
    style_tokens = visual_gates.parse_root_tokens(_style())
    core = (REPO_ROOT / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    core_tokens = visual_gates.parse_root_tokens(core)
    for name in (
        "--paper",
        "--coral",
        "--mustard",
        "--mustard-ink",
        "--muted",
        "--ink-faint",
    ):
        assert visual_gates.resolve_token(name, style_tokens) == visual_gates.resolve_token(
            name, core_tokens
        ), name


def test_workbench_hard_token_is_text_safe() -> None:
    """workbench iframe 不继承父 :root，--hard 必须自己解析到文字安全色。"""
    core = (REPO_ROOT / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    workbench = (REPO_ROOT / "static" / "css" / "workbench.css").read_text(encoding="utf-8")
    tokens = visual_gates.parse_root_tokens(core)
    tokens.update(visual_gates.parse_root_tokens(workbench))
    hard = visual_gates.resolve_token("--hard", tokens)
    soft = visual_gates.resolve_token("--hard-soft", tokens)
    assert hard == "#825c00"
    hard_rgb = visual_gates._parse_color(hard)
    soft_rgb = visual_gates._parse_color(soft)
    assert hard_rgb is not None and soft_rgb is not None
    assert visual_gates.contrast_ratio(hard_rgb, soft_rgb) >= 4.5


def test_baseline_compare_reports_property_transition(tmp_path: Path) -> None:
    baseline = {
        "controls": {
            "btn-primary": {
                "label": "主按钮 btn-dark",
                "selector": ".btn.btn-dark",
                "properties": {"background-color": "rgb(21, 20, 15)"},
            }
        }
    }
    current = {
        "controls": {
            "btn-primary": {
                "label": "主按钮 btn-dark",
                "selector": ".btn.btn-dark",
                "properties": {"background-color": "rgb(193, 74, 43)"},
            }
        }
    }
    diffs, missing, added = visual_baseline.compare(baseline, current)
    assert not missing and not added
    assert diffs == [
        "btn-primary（主按钮 btn-dark / .btn.btn-dark）.background-color: "
        "'rgb(21, 20, 15)' -> 'rgb(193, 74, 43)'"
    ]

    baseline_path = tmp_path / "baseline.json"
    visual_baseline.update(baseline_path, current)
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == current
