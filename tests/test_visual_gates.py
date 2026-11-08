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
    assert before + 1 <= visual_gates.HEX_BUDGET  # 一处的余量正是给这种小改动

    exhausted = css + "".join(f"\n.probe-{i} {{ color: #12345{i % 10}; }}\n" for i in range(3))
    assert visual_gates.count_hex_outside_root(exhausted) > visual_gates.HEX_BUDGET


def test_root_tokens_are_exempt_from_hex_budget() -> None:
    """换主题色应改 :root token，而不是新增规则体字面量。"""
    css = ":root { --ink: #112233; } .card { color: var(--ink); }"
    assert visual_gates.count_hex_outside_root(css) == 0
    assert visual_gates.count_hex_outside_root(":root{--ink:#112233}.card{color:#112233}") == 1


def test_rgba_gate_counts_unique_values() -> None:
    css = ".a{color:rgba(0,0,0,.5)}.b{color:rgba(0, 0, 0, 0.5)}.c{color:rgba(1,2,3,.2)}"
    assert visual_gates.unique_rgba_values(css) == {"rgba(0,0,0,.5)", "rgba(1,2,3,.2)"}


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
