# -*- coding: utf-8 -*-
"""遇见区 openText 重入竞态探针接线（此前无 pytest wrapper ⇒ 永不入 CI）。

缺陷背景（子计划 3 Task 1）：`openText` 是 async 渲染，用户连点两篇文章时，
先发的请求可能后到并覆写后点的那篇 ⇒ 「我点的是 B，看到的却是 A」。
探针覆盖：后点者胜、A 在 B 上屏后失败不覆写、render 内部 await 处被抢占、
第二次 openText abort 第一次的 ctrl.signal、showView 复用同一 seq。

探针输出属 B 类：顶层键 `A`/`A2`/`B`/`C`/`D` **就是场景名**（注意 `A2` 是独立场景）。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_open_race_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_open_race_probe_reports_no_failures() -> None:
    """探针自陈全绿，且 A/A2/B/C/D 五个关键场景齐全（防「删场景换全绿」）。

    场景数守卫取 4：实测 5 个（含 A2），留 1 个余量但 > 1。
    """
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    assert len(scenario_keys(out)) >= 4, (
        f"探针场景数异常偏少（{len(scenario_keys(out))}），可能场景被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(PROBE_NAME, out, ("A", "A2", "B", "C", "D"))


def test_enc_open_race_probe_samples_match_seq_guard() -> None:
    """第二个用例：逐字钉死各场景文案的关键片段（防「输出形状变了但全绿」）。

    特别把 `A2`（A 的请求在 B 上屏后失败）单列出来：它钉的是「失败提示也不覆写」，
    是一条独立的失败路径回归，不是 A 的重复。
    """
    out = _run()

    assert "后点者胜" in out["A"] and "markRead(B)" in out["A"], (
        f"A 场景文案缺后点者胜判据：{out['A']!r}"
    )
    assert "失败" in out["A2"] and "不覆写" in out["A2"], (
        f"A2 场景文案缺失败不覆写判据：{out['A2']!r}"
    )
    assert "抢占" in out["B"] and "不覆写" in out["B"], f"B 场景文案缺 await 抢占判据：{out['B']!r}"
    assert "abort" in out["C"] and "ctrl.signal" in out["C"], (
        f"C 场景文案缺 signal abort 判据：{out['C']!r}"
    )
    assert "seq" in out["D"] and "跨调用" in out["D"], f"D 场景文案缺跨调用 seq 判据：{out['D']!r}"
