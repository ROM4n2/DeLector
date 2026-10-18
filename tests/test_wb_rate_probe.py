# -*- coding: utf-8 -*-
"""背词工作台 doRate 评分行为动态探针接线（tools/wb_rate_probe.mjs）。

背景：
  `static/js/wb-rate.js` 的 `doRate(g)` 承担复习卡片的核心回写链路：
  - 评分分支累加（good / hard / again 计数）；
  - 错题登记（again 分支调用 addWrong(id, "rv-again")）；
  - 新词/复习词区分（logToday.nw 累加）；
  - 翻面/越界保护。
  本文件为 `tools/wb_rate_probe.mjs` 的 pytest wrapper，保证该动态行为探针进入 CI 流水线。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "wb_rate_probe"

EXPECTED_SCENARIOS = (
    "good-grade-3-new-card",
    "hard-grade-2-reviewed-card",
    "again-grade-1-records-wrong",
    "unflipped-guard-ignores-rating",
    "queue-end-guard-ignores-rating",
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_wb_rate_probe_reports_no_failures() -> None:
    """探针自陈全绿（failures == 0），且五组核心行为场景齐全。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)
    assert len(scenario_keys(out)) >= 5, (
        f"探针场景数异常偏少（{len(scenario_keys(out))}），可能场景被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(PROBE_NAME, out, EXPECTED_SCENARIOS)


def test_wb_rate_probe_cases_detail_passed() -> None:
    """逐个场景断言 ok 状态为 True。"""
    out = _run()
    cases = out.get("cases", [])
    assert isinstance(cases, list) and len(cases) >= 5
    for c in cases:
        assert isinstance(c, dict)
        assert c.get("ok") is True, f"场景 {c.get('name')} 未通过"
