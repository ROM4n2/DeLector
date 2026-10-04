# -*- coding: utf-8 -*-
"""卡片目录/网格「角标复用 cardStatsTag」探针接线（tools/cards_catalog_tag_probe.mjs）。

本文件此前**没有任何 pytest wrapper 引用** ⇒ 该探针永远不会进 CI（pytest 只发现
`tests/test_*.py`，`tools/*.mjs` 本身不是测试）。它是被 `tests/test_probe_wiring_guard.py`
的漏接线守卫抓出来的（守卫要求每个 `tools/*_probe.mjs` 都有 wrapper 引用）。

事故背景：词汇目录/网格过去**硬编码** `correct_count` 之类的统计位，工作台词
（`fsrs_s` 有值的投影卡）在目录里谎报「0 正 / 0 误」——卡面显示「📚 工作台 · s=25.0」，
目录却写着零正零误。修法是让目录网格复用卡片面那个 `cardStatsTag` 切片，并保证
**正常路径文案逐字不变**（普通卡 / 语法卡的「⏳ 到期: … · N 正 / M 误」不许被改写）。

输出形状属 A 类（标准契约 `{failures, total, cases:[{name, ok}], samples}`），
实测 `total = 10`、`failures = 0`。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "cards_catalog_tag_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_cards_catalog_tag_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 7（实测 10，留余量但防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 7, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) >= 7, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_cards_catalog_tag_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景的存在性（各字母段落的锚点，防「删一整段换全绿」）。

    A 工作台词目录不再谎报零正零误 / A2 与 cardStatsTag 同源 /
    B 普通卡统计位逐字不变 / B2 due_date 不丢 / C 无残留硬编码 + 复用切片 /
    D 语法卡同样成立 / E cardStatsTag 自身零改动。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "A1-工作台词目录网格不谎报零正零误",
            "A2-工作台词目录网格与cardStatsTag同源",
            "B1-普通卡仍显正误统计",
            "B2-换用后due_date信息不丢",
            "B3-普通卡统计位逐字等于cardStatsTag",
            "C1-目录网格无残留硬编码correct_count",
            "C2-目录网格复用cardStatsTag",
            "D1-语法卡仍显正误统计",
            "D2-语法卡统计位等于cardStatsTag",
            "E1-cardStatsTag零改动",
        ),
    )


def test_cards_catalog_tag_probe_samples_match_tag_contract() -> None:
    """第二个用例：逐字断言 samples 的**用户可见文案**（防「形状变了但全绿」）。

    钉三条直接面向用户的角标文案，任何一条被改写都是契约变更而不是重构：
      - 工作台词卡必须显示「📚 工作台 · s=25.0」（这是它与非工作台词卡的区分标记，
        目录里也必须能一眼看出这是工作台投影卡，而不是伪装成普通卡显示零正零误）；
      - 普通 reader 卡与语法卡必须**逐字**保留「⏳ 到期: <日期> · N 正 / M 误」格式
        （事故修复只应作用于工作台词分支，改写正常路径文案就是回归）；
      - `cardStatsTagSha256` 是被复用切片的指纹，必须存在且是 64 位小写十六进制
        （指纹缺失 = 「复用」这件事其实没被验证；此处只断言形状而不钉死具体摘要值，
        因为切片**合法**变更时摘要本就会变，而那属于 E1 场景的判定职责）。
    """
    out = _run()
    samples: dict[str, Any] = out["samples"]

    assert samples["vocabWorkbench"] == "📚 工作台 · s=25.0", (
        f"工作台词卡的目录角标文案被改写：{samples['vocabWorkbench']!r}"
        "（它必须与卡面的工作台标记一致，而不是显示成普通卡的零正零误）"
    )
    assert samples["vocabReader"] == "⏳ 到期: 2026-10-05 · 7 正 / 2 误", (
        f"普通 reader 卡的目录角标文案被改写：{samples['vocabReader']!r}"
        "（正常路径文案必须逐字不变）"
    )
    assert samples["grammarReader"] == "⏳ 到期: 2026-10-06 · 5 正 / 1 误", (
        f"语法卡的目录角标文案被改写：{samples['grammarReader']!r}"
        "（正常路径文案必须逐字不变）"
    )

    sha = samples["cardStatsTagSha256"]
    assert isinstance(sha, str) and len(sha) == 64 and all(
        c in "0123456789abcdef" for c in sha
    ), f"cardStatsTag 切片指纹形状异常：{sha!r}（期望 64 位小写十六进制）"
