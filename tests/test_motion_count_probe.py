# -*- coding: utf-8 -*-
"""`countUp` 计数过程不出现负值的探针接线（tools/motion_count_probe.mjs）。

事故（2026-11-07 Android 真机）：`motion.js` 的 `countUp` 只夹了 progress 上界，
rAF 时间戳早于 `performance.now()` 时 progress 变负，台账「测验综合正答率」
首帧闪过 `-2%`。探针跑 `static/js/motion.js` 真源码，驱动首帧负时间戳，
钉死「全程无负值 / 单调不减 / 终值精确 / reduce 不排 rAF」。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "motion_count_probe"

_CASES = (
    "firstFrameNonNegative",
    "allFramesNonNegative",
    "monotonicNonDecreasing",
    "finalExact",
    "reduceSettlesWithoutRaf",
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_motion_count_probe_reports_no_failures() -> None:
    """探针自陈全绿，且 5 个关键场景都在（防删场景换全绿）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)
    assert len(scenario_keys(out)) == len(_CASES), (
        f"探针场景数异常（{sorted(scenario_keys(out))}），可能场景被删"
    )
    assert_scenarios_present(PROBE_NAME, out, _CASES)


def test_motion_count_probe_pins_first_frame_and_final_value() -> None:
    """第二个用例：逐条钉死事故复现点，防「全绿但判据被放松」。"""
    out = _run()
    by_name = {str(c["name"]): c for c in out["cases"]}

    first = by_name["firstFrameNonNegative"]
    assert first["ok"] is True, f"首帧仍出现负值：{first['detail']}"
    assert "0%" in first["detail"], f"首帧未落到 0：{first['detail']}"

    negatives = by_name["allFramesNonNegative"]
    assert negatives["ok"] is True, f"计数过程仍有负值帧：{negatives['detail']}"

    final = by_name["finalExact"]
    assert final["ok"] is True, f"终值不精确：{final['detail']}"
