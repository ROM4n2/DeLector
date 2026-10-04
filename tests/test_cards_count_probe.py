# -*- coding: utf-8 -*-
"""卡片角标计数探针接线（tools/cards_count_probe.mjs，此前无 pytest wrapper ⇒ 永不入 CI）。

事故背景（子计划 1 Task 1）：`refreshCardCounters` 过去为了显示一个数字去请求
`GET /api/cards`（SELECT * 全表 + 逐卡 get_fsrs_next_intervals 递推），且挂在 7 个
「每次存卡后」的调用点上 ⇒ 存 N 张卡是 O(N²) 的写路径放大。改为 `GET /api/cards/counts`。

探针输出形状属 C 类（扁平结论字段，无 `cases`）：顶层键是被测维度，取值 `ok:true`
**只在该探针 problems 为空、退出码 0 时才存在**（见 tests/probe_runner.py 模块 docstring）。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "cards_count_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_cards_count_probe_reports_no_failures() -> None:
    """探针自陈全绿，且被测维度齐全（防「删维度换全绿」）。

    场景数守卫取 6：实测 `counts` 下 9 个被测维度（endpoint / requestedPaths /
    legacyEndpointNotUsed / badgesFromTotalOnly / badgesBothWritten /
    onlyTotalConsumed / failureSilent / missingTotalFallback / arityPreserved），
    留出余量但 > 1，删掉一半维度仍会红。
    """
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    assert len(scenario_keys(out["counts"])) >= 6, (
        f"探针被测维度异常偏少（{len(scenario_keys(out['counts']))}），可能维度被删：{sorted(out['counts'])}"
    )
    # 关键维度逐字钉死：删掉任何一条都是契约倒退（而非"简化"）
    assert_scenarios_present(
        PROBE_NAME,
        out["counts"],
        (
            "endpoint",
            "requestedPaths",
            "legacyEndpointNotUsed",
            "badgesFromTotalOnly",
            "badgesBothWritten",
            "onlyTotalConsumed",
            "failureSilent",
            "missingTotalFallback",
            "arityPreserved",
        ),
    )


def test_cards_count_probe_samples_match_endpoint_contract() -> None:
    """第二个用例：钉死 samples 的**具体口径**，防「输出形状变了但全绿」。

    这里钉三条与后端契约直接耦合的值：
      - endpoint 必须是 `/api/cards/counts`，且 `requestedPaths` 里**不得**出现
        `/api/cards`（打全量端点就是 O(N²) 事故复发）；
      - `badgesFromTotalOnly` 两个角标**都**是 7（只消费 total 一项就够）；
      - `failureSilent` / `missingTotalFallback` 都保持 42（失败静默保留旧值，
        而不是把 "undefined"/"null" 写进角标）。
    """
    out = _run()
    counts = out["counts"]

    assert counts["endpoint"] == "/api/cards/counts", (
        f"角标端点被改回 {counts['endpoint']!r}：打全量 /api/cards 会退回 O(N²) 写路径放大"
    )
    assert counts["requestedPaths"] == ["/api/cards/counts"], (
        f"实际请求路径异常：{counts['requestedPaths']!r}（期望恰好一次 /api/cards/counts）"
    )
    assert counts["legacyEndpointNotUsed"] is True, (
        "旧全量端点 /api/cards 又被请求了：O(N²) 写路径放大事故复发"
    )

    assert counts["badgesFromTotalOnly"] == {"card-count": 7, "mob-card-count": 7}, (
        f"只给 total 时两个角标未同步更新：{counts['badgesFromTotalOnly']!r}"
    )
    assert counts["badgesBothWritten"] is True, "card-count 与 mob-card-count 未同时写入"

    for field in ("failureSilent", "missingTotalFallback"):
        assert counts[field] == {"card-count": 42, "mob-card-count": 42}, (
            f"{field} 未静默保留旧值 42（会被清 0 或写入 undefined）：{counts[field]!r}"
        )
