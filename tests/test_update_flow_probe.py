# -*- coding: utf-8 -*-
"""应用内更新面板纯展示逻辑（`static/js/update-flow.js`）的行为探针接线。

被测真相在 `tools/update_flow_probe.mjs`：data URL 导入真实源码，零重抄实现。
"""

from probe_runner import assert_probe_clean, assert_scenarios_present, require_node, run_json_probe

PROBE = "update_flow_probe"

SCENARIOS = (
    "percent_edges",
    "download_view",
    "verifying_view",
    "ready_view",
    "failed_humanized",
    "unknown_reason_fallback",
    "idle_view",
)


def test_update_flow_probe_is_clean() -> None:
    require_node()
    out = run_json_probe(PROBE)

    assert_probe_clean(PROBE, out)
    assert_scenarios_present(PROBE, out, SCENARIOS)
