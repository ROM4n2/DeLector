# -*- coding: utf-8 -*-
"""覆盖率行「降级标注」的并发串味探针接线（tools/enc_degraded_concurrency_probe.mjs）。

本文件此前**没有任何 pytest wrapper 引用** ⇒ 该探针永远不会进 CI（pytest 只发现
`tests/test_*.py`，`tools/*.mjs` 本身不是测试）。它是被 `tests/test_probe_wiring_guard.py`
的漏接线守卫当场抓出来的（2026-10-05 清债轮 Task 3 落地后守卫立刻红：
`assert not ['enc_degraded_concurrency_probe']`）。

事故背景：降级状态原本是**模块级全局**（`_knownDegraded` / `_deckDegraded`），而快照点
在详情渲染路径上。`showView` 的 `resolveDeck()` 与详情的 `resolveDeck()` 并发、且以相反
结果交错结束时，详情会被**别人那次调用**的失败污名化：自己明明拿到了成功的镜像 deck，
覆盖率行却显示「数据不完整」—— 把成功谎报成失败。修法是降级状态与**本次调用**绑定。

输出形状属 A 类，且比标准契约**少一个 `samples` 字段** —— 实测顶层恰好是
`{failures, total, cases}`，`total = 21`、`failures = 0`。因此第二个用例不去读
`samples`（读了必然 KeyError），改为逐字钉死 `cases` 的场景名全集。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    probe_path,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_degraded_concurrency_probe"
PROBE = probe_path(PROBE_NAME)

#: 实测 `cases` 的场景名全集（21 条）。这里刻意存成集合并做**相等**断言（而不只是
#: 「包含」）：本探针的验收点就是「串味不误标（S1）+ 自己那次的降级不丢（S2/S3）+
#: 时序对照与无并发基线（S4/S5）」这批具体判定，多一条少一条都意味着判定被增删，
#: 必须由人看过再改这份清单。
EXPECTED_CASES = frozenset(
    {
        "S1-夹具-列表在飞",
        "S1-夹具-详情在飞",
        "S1-详情deck真成功",
        "S1-覆盖行已渲染",
        "S1",
        "S1-title",
        "S2-夹具-详情在飞",
        "S2",
        "S2-title",
        "S2-人话",
        "S3-夹具-详情在飞",
        "S3-详情deck成功",
        "S3",
        "S3-title",
        "S3-人话",
        "S4-快照时未标记",
        "S4-详情deck成功",
        "S4",
        "S5-详情deck成功",
        "S5",
        "S5-覆盖行",
    }
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_degraded_concurrency_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 15（实测 21，留余量但防「删场景换全绿」）。"""
    assert PROBE.exists(), f"缺少 tools/{PROBE_NAME}.mjs 动态探针（文件缺失，无法接线）"

    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 15, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) >= 15, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_enc_degraded_concurrency_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景的存在性（防「删掉串味判定换全绿」）。

    `S1` 是本探针的**核心价值**：详情自己两路都成功、并发的列表那次失败落在快照之前
    ⇒ 覆盖率行 MUST 不含降级标记。删掉 `S1` 就等于把本次修的并发串味 bug **变成无守卫**，
    故它与它的两条前置校验（详情 deck 真成功 / 覆盖行已渲染）一起被逐字钉住。
    同时钉住 S2/S3（自己那次的降级 MUST 不丢，防「只读到别人那次」的反向退化）与
    S4/S5（时序对照 + 无并发基线，防探针恒红或恒绿）。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "S1-详情deck真成功",
            "S1-覆盖行已渲染",
            "S1",
            "S1-title",
            "S2",
            "S2-title",
            "S2-人话",
            "S3",
            "S3-title",
            "S3-人话",
            "S4",
            "S5",
            "S5-覆盖行",
        ),
    )


def test_enc_degraded_concurrency_probe_case_set_is_exact() -> None:
    """第二个用例：钉死 `cases` 的**场景名全集**（防「悄悄增删判定」）。

    本探针没有 `samples` 字段，故用「场景集合相等」替代「读 samples 口径」：
    少一条 = 某个判定被删（串味路径裸奔 / 降级路径裸奔），多一条 = 有人加了未经复核的
    判定。两者都必须由人显式改 `EXPECTED_CASES` 才能通过。
    """
    out = _run()
    keys = scenario_keys(out)

    assert keys == EXPECTED_CASES, (
        f"场景集合与实测基线不符：\n"
        f"  多出：{sorted(keys - EXPECTED_CASES)}\n"
        f"  缺失：{sorted(EXPECTED_CASES - keys)}"
    )
    # total 与 cases 长度必须自洽，否则「场景数下界」守卫会被 total 字段单独抬高而失效
    assert out["total"] == len(keys), (
        f"total({out['total']}) 与 cases 实际条数({len(keys)}) 不符"
    )
