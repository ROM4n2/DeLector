# -*- coding: utf-8 -*-
"""存卡反馈跨边界行为探针接线（tools/vocab_save_feedback_probe.mjs）。

背景（2026-11-10 P2）：`POST /api/cards/vocab` 幂等命中既有卡时返回
`created:false` / `skipped_fields`，此前 5 个前端入口一律「已保存」+ 庆祝动画，
用户手填的释义被「只补空」静默丢弃却回报成功。

探针把 `rd-api.js`（纯判定函数）与 `reader.js` / `cards.js` / `a1_cards.js` /
`a1_hoeren.js`（5 个存卡入口）的**真源码**切进 node:vm 沙箱真跑，桩只提供
DOM/网络/伴侣环境；断言按钮文案、庆祝动画次数、以及提示文案，不是字符串存在断言。
`--json` 输出精确标准三键 `{failures, total, cases}`（新增探针即标准），
`cases[].detail` 带实测值供本文件钉住具体口径。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "vocab_save_feedback_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_vocab_save_feedback_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 20（实测 23，防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 20, f"探针场景数异常偏少（{total}），可能整段被测入口被删：{sorted(scenario_keys(out))}"
    assert len(scenario_keys(out)) >= 20, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_vocab_save_feedback_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景：后端旧响应兼容、幂等命中不庆祝、跳过字段有解释、5 入口全覆盖。"""
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "outcome_missing_fields_is_backward_compatible",
            "outcome_duplicate_with_skipped_fields",
            "notice_skipped_explains_no_overwrite",
            "reader_saveVocab_duplicate_no_celebration",
            "reader_saveVocab_duplicate_explains_skipped",
            "reader_saveVocab_legacy_response_unchanged",
            "reader_prep_collocation_duplicate_no_celebration",
            "cards_matrix_duplicate_no_celebration",
            "a1_cards_duplicate_no_celebration",
            "a1_hoeren_duplicate_no_celebration",
            "cards_matrix_created_celebrates",
            "a1_cards_created_celebrates",
            "a1_hoeren_created_celebrates",
        ),
    )


def test_vocab_save_feedback_probe_details_match_contract() -> None:
    """钉死具体口径：跳过字段的提示必须解释「未覆盖」，不是笼统的「已保存」。"""
    out = _run()
    by_name = {str(c["name"]): c for c in out["cases"]}

    duplicate = by_name["outcome_duplicate_with_skipped_fields"]
    assert duplicate["ok"] is True
    assert "definition_zh" in duplicate["detail"], (
        f"幂等命中的跳过字段没被实测值记录：{duplicate['detail']!r}"
    )
    assert "未覆盖" in by_name["notice_skipped_explains_no_overwrite"]["detail"], (
        "提示文案没解释「未覆盖原有释义」"
    )
    assert "未覆盖" in by_name["reader_saveVocab_duplicate_explains_skipped"]["detail"], (
        "阅读器主路径没把跳过字段解释给用户"
    )
