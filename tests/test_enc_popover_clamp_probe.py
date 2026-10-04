# -*- coding: utf-8 -*-
"""遇见区弹层垂直定位（夹取 + 向上翻转）探针接线（此前无 pytest wrapper ⇒ 永不入 CI）。

缺陷背景（子计划 3 Task 2）：词条弹层若只用 `Math.min(rect.bottom + 6, vh - h - 8)`
夹取，**空间不足时不会向上翻转**，弹层会被视口裁掉一截（用户看不到词义）。
探针覆盖 5 个场景：贴视口底部、空间不足向上翻转、上方够高不翻转（旧行为不回归）、
极矮视口留边、同帧只读一次 offsetHeight（No-Layout-Thrash）。

探针输出属 B 类：顶层键是**数字字符串** `"1"`~`"5"`（JS 对象数字键序列化所致），
它们就是场景名。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_popover_clamp_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_popover_clamp_probe_reports_no_failures() -> None:
    """探针自陈全绿，且 1~5 五个关键场景齐全（防「删场景换全绿」）。

    场景数守卫取 4：实测 5 个，留 1 个余量但 > 1。
    """
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    assert len(scenario_keys(out)) >= 4, (
        f"探针场景数异常偏少（{len(scenario_keys(out))}），可能场景被删：{sorted(scenario_keys(out))}"
    )
    # 场景名是数字字符串，必须逐字匹配（子串匹配会误判 "1" 被 "10" 命中）
    assert_scenarios_present(PROBE_NAME, out, ("1", "2", "3", "4", "5"))


def test_enc_popover_clamp_probe_samples_match_flip_behavior() -> None:
    """第二个用例：逐字钉死各场景文案的关键片段（防「输出形状变了但全绿」）。

    第 2 场景（向上翻转）是本探针的核心判据，单独强调：只做 `Math.min` 不翻转
    的实现会在这里红。
    """
    out = _run()

    assert "[8, vh-h-8]" in out["1"], f"场景 1 应钉住夹取区间 [8, vh-h-8]：{out['1']!r}"
    assert "翻转" in out["2"] and "Math.min" in out["2"], (
        f"场景 2 应钉住向上翻转（而非单纯 Math.min）：{out['2']!r}"
    )
    assert "不翻转" in out["3"] and "rect.bottom + 6" in out["3"], (
        f"场景 3 应钉住上方够高时不翻转的旧行为：{out['3']!r}"
    )
    assert "top >= 8" in out["4"], f"场景 4 应钉住极矮视口仍留 8px 边：{out['4']!r}"
    assert "offsetHeight" in out["5"] and "No-Layout-Thrash" in out["5"], (
        f"场景 5 应钉住同帧只读一次 offsetHeight：{out['5']!r}"
    )
