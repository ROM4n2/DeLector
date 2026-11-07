# -*- coding: utf-8 -*-
"""扑克牌 tap/drag 手势探针接线（tools/cards_deck_tap_probe.mjs）。

真机事故（2026-11-07 Android）：旧 `attachDeckSwipeListener` 只在 touchmove 里
给 `currentX` 赋值，干净 tap 没有 touchmove ⇒ `currentX` 停在 0 ⇒
`diff = -startX` 恒为大幅负数 ⇒ 每次点击都被当成左滑跳下一张，翻面永远轮不到。

探针切 `static/js/cards.js` 真源码进 node:vm，钉死：
- 干净 tap / 阈值内 tap 翻面且不切卡；
- 越过阈值的左右 drag 切卡且不翻面；
- 模糊区、纵向滚动、pointercancel、背面 tap 均无动作。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "cards_deck_tap_probe"

_CASES = (
    "tapWithoutMoveFlips",
    "tapWithinSlopFlips",
    "dragLeftStepsNext",
    "dragRightStepsPrev",
    "ambiguousDragSnapsBack",
    "interactiveTargetIgnored",
    "verticalScrollDoesNotFlip",
    "pointerCancelDoesNothing",
    "flippedTapDoesNothing",
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_cards_deck_tap_probe_reports_no_failures() -> None:
    """探针自陈全绿，且 9 个场景都在（防删场景换全绿）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)
    assert len(scenario_keys(out)) == len(_CASES), (
        f"探针场景数异常（{sorted(scenario_keys(out))}），可能场景被删"
    )
    assert_scenarios_present(PROBE_NAME, out, _CASES)


def test_cards_deck_tap_probe_pins_tap_and_drag_exclusivity() -> None:
    """第二条：tap 只翻面、drag 只切卡，两者互斥。"""
    out = _run()
    by_name = {str(c["name"]): c for c in out["cases"]}

    tap = by_name["tapWithoutMoveFlips"]
    assert tap["ok"] is True, f"干净 tap 仍不翻面：{tap['detail']}"

    left = by_name["dragLeftStepsNext"]
    assert left["ok"] is True, f"左滑仍不切卡：{left['detail']}"

    right = by_name["dragRightStepsPrev"]
    assert right["ok"] is True, f"右滑仍不切卡：{right['detail']}"
