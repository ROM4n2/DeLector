# -*- coding: utf-8 -*-
"""卡盒「工作台词不给复习按钮」探针接线（既有漏接，2026-10-05 清债轮 C 组补上）。

白复习事故：统一池（core/vocab_pool.py）把工作台背过的词投影进 vocab_cards，但只写
fsrs_s / fsrs_d / fsrs_lapses，**不写** repetition_count / due_date。卡盒 DSR 复习
（review_card_sm2）也**不写** fsrs_*。⇒ 用户在卡盒点「1 重来 / 2 困难 / 3 良好 / 4 简单」：
DSR 四列被写了，但卡面因 fsrs_s 优先仍显示「📚 工作台 · s=25」（屏幕上什么都没变），
而工作台那侧的 FSRS 也没动 —— 复习了，等于没复习。

为何本组单独补它：它是 `tools/` 下**唯一**用标准契约
`{failures, total, cases:[{name,ok}], samples}` 的漏接探针（total=28），
且此前**完全没有** pytest wrapper 引用 ⇒ 该 P0 回归守卫从未进过 CI。
补接线前先核实（2026-10-05）：`grep -rF cards_workbench_no_review_probe.mjs tests/`
零命中，与本组另外 7 个漏接探针同批发现。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "cards_workbench_no_review_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_cards_workbench_no_review_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 20（实测 28，留足余量但防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 20, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) >= 20, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_cards_workbench_no_review_probe_key_scenarios_present() -> None:
    """逐字钉死七条关键场景的存在性（各字母段落的锚点，防「删一整段换全绿」）。

    A 白复习消除 / B 旧语义不回归 / C 判据边界（>= 0 放宽会在这里露馅）/
    D 手动已掌握叠加 / E 单一判据同源 / F 复用阶梯（不自造第二份阈值）/
    H 样式契约（只吐 class 不定义样式 → 裸 <a> 蓝下划线）。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "A1-工作台词不渲染DSR复习按钮",
            "A2-工作台词保留mastered按钮",
            "B1-普通卡四个复习按钮齐全",
            "B2-普通卡无去工作台链接",
            "C-fsrs_s=0仍给四个复习按钮",
            "D1-已掌握工作台词仍无复习按钮",
            "E1-判据表达式逐字同源",
            "E2-判据与标签整带行为等价",
            "F1-渲染复用单一判据",
            "H1-工作台提示块三类已定义样式",
        ),
    )


def test_cards_workbench_no_review_probe_samples_match_no_review_contract() -> None:
    """第二个用例：钉死 samples 的**具体口径**（防「输出形状变了但全绿」）。

    三条互为反证：工作台词 MUST NOT 有 DSR 复习按钮（白复习的根因）、
    普通 reader 卡 MUST 仍有（否则是「把所有按钮都删了」式的假修复）、
    跳转 href MUST 复用 index.html 里既有的工作台路由（不许自造路由）。
    """
    out = _run()
    samples: dict[str, Any] = out["samples"]

    assert samples["workbenchHasReviewButtons"] is False, (
        "工作台词（fsrs_s>0）卡面又渲染了 submitCardReview：白复习事故复发"
    )
    assert samples["readerHasReviewButtons"] is True, (
        "普通 reader 卡（fsrs_s=null）四个 DSR 复习按钮不见了："
        "把按钮对工作台词也一起删掉不等于修复"
    )
    assert samples["workbenchRoute"] == "/german/workbench.html", (
        f"去工作台路由被自造/改动：{samples['workbenchRoute']!r}（应沿用 index.html 既有路由）"
    )
