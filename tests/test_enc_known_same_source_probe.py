# -*- coding: utf-8 -*-
"""遇见区「列表/详情」已知词池同源探针接线（此前无 pytest wrapper ⇒ 永不入 CI）。

缺陷背景（子计划 3 Task 3，2026-10-04）：详情 `renderTextDetailAnnotated` 的 deck 走
`resolveDeck()`（本机 localStorage → 空则拉 `GET /api/wb/state` 镜像 → 合并），
而列表 `showView` 走裸 `loadDeck(encStorage())`（**只**本机）。
⇒ 女友清过站点数据 / 换浏览器 profile / 跨设备时，同一功能出现两个真相：
列表 knownSet 为空显示「i+1 徽章 偏难 0%」，详情却显示「已背词覆盖 82%」。

探针输出属 B 类：顶层键 `A`~`E` **就是场景名**，值是该场景的自陈文案。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_known_same_source_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_known_same_source_probe_reports_no_failures() -> None:
    """探针自陈全绿，且 A~E 五个关键场景齐全（防「删场景换全绿」）。

    场景数守卫取 4：实测 5 个（A~E），留 1 个余量但 > 1。
    """
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    assert len(scenario_keys(out)) >= 4, (
        f"探针场景数异常偏少（{len(scenario_keys(out))}），可能场景被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(PROBE_NAME, out, ("A", "B", "C", "D", "E"))


def test_enc_known_same_source_probe_samples_match_deck_resolution() -> None:
    """第二个用例：逐字钉死各场景文案的关键片段（防「输出形状变了但全绿」）。

    文案由探针在裁决通过后构造，若探针换了措辞或漏了判据，这里会红。
    """
    out = _run()

    assert "同源" in out["A"] and "knownSet" in out["A"], f"A 场景文案缺同源判据：{out['A']!r}"
    assert "不回归" in out["B"] and "本机" in out["B"], f"B 场景文案缺本机优先判据：{out['B']!r}"
    assert "离线" in out["C"] and "静默" in out["C"], f"C 场景文案缺静默回退判据：{out['C']!r}"
    assert out["D"].startswith("两端同源"), f"D 场景应是两端同源：{out['D']!r}"
    assert "复用阶梯" in out["E"] and "/api/wb/state" in out["E"], (
        f"E 场景文案缺复用阶梯判据：{out['E']!r}"
    )
