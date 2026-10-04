# -*- coding: utf-8 -*-
"""覆盖率行「降级标注」探针接线（tools/enc_coverage_degraded_probe.mjs）。

本文件此前**没有任何 pytest wrapper 引用** ⇒ 该探针永远不会进 CI（pytest 只发现
`tests/test_*.py`，`tools/*.mjs` 本身不是测试）。它是被 `tests/test_probe_wiring_guard.py`
的漏接线守卫抓出来的（守卫要求每个 `tools/*_probe.mjs` 都有 wrapper 引用）。

事故背景：`known-lemmas` 拉取失败时，覆盖率行原本会把异常**原样**吐给用户
（`undefined` / `TypeError` / `/api/...` 这类技术字面量），或者干脆什么都不显示。
修法是：失败时给出 `⚠` 降级标记 + `数据不完整` 文案，title 并列给出**两条**原因，
而**正常路径文案逐字不变**（不许给正常路径也挂降级标记）。

输出形状属 A 类，但比标准契约**少一个 `samples` 字段** —— 实测顶层恰好是
`{failures, total, cases}`，`total = 14`、`failures = 0`。因此第二个用例不去读
`samples`（读了必然 KeyError），改为逐字钉死 `cases` 的场景名全集。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_coverage_degraded_probe"

#: 实测 `cases` 的场景名全集（14 条）。这里刻意存成集合并做**相等**断言（而不只是
#: 「包含」）：本探针的验收点就是「正常路径逐字不变 + 降级路径是人话」这批具体判定，
#: 多一条少一条都意味着判定被增删，必须由人看过再改这份清单。
EXPECTED_CASES = frozenset(
    {
        "B1-render",
        "B1",
        "B1-title",
        "B5",
        "B2",
        "B2-human-copy",
        "B2-title",
        "B2-not-blank",
        "B3",
        "B3-human-copy",
        "B3-title",
        "B4-single-marker",
        "B4-human-copy",
        "B4-two-reasons",
    }
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_coverage_degraded_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 10（实测 14，留余量但防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 10, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) >= 10, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_enc_coverage_degraded_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景的存在性（防「删掉降级判定换全绿」）。

    覆盖四组验收点：B1 正常路径无降级标记 / B2 known-lemmas 失败才降级 /
    B3 语法侧失败同样降级 / B4 双源失败时 title 并列给出两条原因。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "B1-render",
            "B1",
            "B1-title",
            "B2",
            "B2-human-copy",
            "B2-not-blank",
            "B3",
            "B4-single-marker",
            "B4-two-reasons",
        ),
    )


def test_enc_coverage_degraded_probe_case_set_is_exact() -> None:
    """第二个用例：钉死 `cases` 的**场景名全集**（防「悄悄增删判定」）。

    本探针没有 `samples` 字段，故用「场景集合相等」替代「读 samples 口径」：
    少一条 = 某个降级判定被删（降级路径裸奔），多一条 = 有人加了未经复核的判定。
    两者都必须由人显式改 `EXPECTED_CASES` 才能通过。
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
