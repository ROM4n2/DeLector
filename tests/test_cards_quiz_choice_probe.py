# -*- coding: utf-8 -*-
"""卡盒测验 choice「缺释义不渲染空白选项」探针接线（2026-11-03）。

缺陷：renderCurrentQuizCard 的 choice 分支曾用裸 ``card.definition_zh`` 当正确
答案选项文本。HITL 提议链路允许缺释义的卡入盒（提案、卡盒网格、卡背与复习卡面
统一显示「待补充」），这样的卡进选择题时正确答案按钮渲染成**空白**，与同函数里
flashcard / dictation 两个分支（均走 formatCardDefinition）口径不一致。
上批（2026-11-03 02:34 自审）登记为「choice 选项不接待补充」，本批修复并加探针。

探针形态：切片 cards.js 的 renderCurrentQuizCard + cd-state.js 的 cardState /
formatCardDefinition 真源码进 node:vm 沙箱真跑（同 cards_workbench_no_review_probe
的支架），读回 quiz-choice-options 的真 innerHTML，解析 onclick 的
selectChoiceOption(idx, correctIdx) 验证正确项索引映射。
变异实证（2026-11-03）：revert cards.js 修复后探针 exit 1，B1/B2/C1/C2/D2 具名红
——守卫对缺陷本体有判别力，不是恒绿。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "cards_quiz_choice_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_cards_quiz_choice_probe_reports_no_failures() -> None:
    """探针自陈全绿，场景数符合预期（防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 10, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) == total, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_cards_quiz_choice_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景的存在性（防「删一整段换全绿」）。

    A 有释义卡语义不回归 / B 缺释义卡走「待补充」且无空白按钮（缺陷本体）/
    C 空白释义与小词库收缩 / D 切片护栏（单一释义来源 + 旧缺陷形态绝迹）。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "A1-有释义卡正确选项即原释义",
            "A2-有释义卡正确索引映射精确",
            "A3-有释义卡干扰项非空且不含空释义卡",
            "B1-缺释义卡正确选项显示待补充",
            "B2-缺释义卡无空白选项",
            "B3-缺释义卡正确索引映射精确",
            "C1-空白释义同走待补充",
            "C2-干扰项不足时选项收缩且正确项在",
            "D1-渲染复用formatCardDefinition单一来源",
            "D2-选项数组不再以裸definition_zh起头",
        ),
    )
