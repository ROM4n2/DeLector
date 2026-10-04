# -*- coding: utf-8 -*-
"""fetchKnownLemmas「in-flight 去重」探针接线（tools/enc_known_lemmas_dedupe_probe.mjs）。

本文件此前**没有任何 pytest wrapper 引用** ⇒ 该探针永远不会进 CI（pytest 只发现
`tests/test_*.py`，`tools/*.mjs` 本身不是测试）。它是被 `tests/test_probe_wiring_guard.py`
的漏接线守卫抓出来的（守卫要求每个 `tools/*_probe.mjs` 都有 wrapper 引用）。

事故背景：`fetchKnownLemmas()` 过去无模块级 promise、无缓存 ⇒ **无并发去重**。而它的
调用点有两处（showView 的 `Promise.allSettled`、renderTextDetailAnnotated 的
`Promise.all([resolveDeck(), fetchKnownLemmas()])`），都不传 opts ⇒ 一次会话读 N 篇短文
= **N+1 次** `GET /api/cards/known-lemmas`（进场 1 + 每篇 1），后端每次都真 SELECT。

═══ 输出形状（2026-10-05 实测，非推断）═══
`node tools/enc_known_lemmas_dedupe_probe.mjs` 退出码 0，逐行打印 16 条 `PASS <名>`；
`--json` 的顶层键**恰好**是 `{failures, total, cases}`，实测 `total = 16`、
`failures = 0`，`cases[i]` 的键**恰好**是 `{name, ok}`。

即：属 A 类契约，但**既没有 `samples`、也没有顶层 `ok`** —— 与
`enc_coverage_degraded` 同一形状。故第二个用例**不去读 `samples`**（读了必然 KeyError），
改为逐字钉死 `cases` 的场景名全集 + 每条的 `ok` 值。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "enc_known_lemmas_dedupe_probe"

#: 实测 `cases` 的场景名全集（16 条）。刻意存成集合并做**相等**断言（而不只是「包含」）：
#: 本探针的验收点就是「并发去重 + 不做 TTL 缓存 + 失败可重试 + 抢占不废共享请求」这批
#: 具体判定，多一条少一条都意味着判定被增删，必须由人看过再改这份清单。
EXPECTED_CASES = frozenset(
    {
        # A1 并发去重：两次并发只打一次后端，且两个调用方拿到**同一个数组实例**
        "A1",
        "A1-shared-request",
        "A1-same-instance",
        "A1-payload",
        # A2 **反向断言**：两次**串行**调用仍打两次（证明没做成 TTL/永久缓存）
        "A2",
        "A2-payload",
        # A3 in-flight 期间失败 ⇒ 之后重新请求（finally 清空生效）
        "A3-first",
        "A3-retry",
        "A3-retry-payload",
        # A4 抢占不废掉共享请求：请求不带 signal，外部 abort 后仍都拿到结果
        "A4-no-signal",
        "A4",
        # A5 返回形状逐字不变：非数组 / 无信封 / 请求失败 ⇒ []
        "A5-array",
        "A5-passthrough",
        "A5-nonarray",
        "A5-noenvelope",
        "A5-throw",
    }
)


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_enc_known_lemmas_dedupe_probe_reports_no_failures() -> None:
    """探针自陈全绿，且场景数 ≥ 12（实测 16，留余量但防「删场景换全绿」）。"""
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    total = out["total"]
    assert total >= 12, f"探针场景数异常偏少（{total}），可能场景被删"
    assert len(scenario_keys(out)) >= 12, (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {total}）"
    )


def test_enc_known_lemmas_dedupe_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景的存在性（防「删掉核心判定换全绿」）。

    覆盖四组验收点：A1 并发只打一次 + 同一数组实例（A2-payload 另钉不做 TTL 缓存的反向
    断言）/ A3 失败后可重试 / A4 共享请求不带 signal 且抢占不废掉它 / A5 三种坏形状退化为 []。
    """
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "A1",
            "A1-same-instance",
            "A2",
            "A2-payload",
            "A3-retry",
            "A4-no-signal",
            "A4",
            "A5-nonarray",
            "A5-noenvelope",
            "A5-throw",
        ),
    )


def test_enc_known_lemmas_dedupe_probe_case_set_is_exact() -> None:
    """第二个用例：钉死 `cases` 的**场景名全集 + 每条的 ok 值**（防「形状变了但全绿」）。

    本探针没有 `samples` 字段，故用「场景集合相等 + 逐条 ok」替代「读 samples 口径」：
      - 少一条 = 某个判定被删（并发去重或失败可重试裸奔）；多一条 = 有人加了未经复核的判定；
      - 每条 `ok` 必须逐字为 `True` —— 只钉名字集合的话，有人把 `record(name, ok, msg)`
        改成无条件 `record(name, true, "")` 就能在集合不变的前提下全绿。

    特别强调 A2：它是一条**反向断言**（串行调用必须打 2 次），本探针的核心价值就在于
    挡住「顺手加个 TTL 缓存」的过度实现 —— 那样会让刚背的词在 TTL 内不出现，是 UX 回归。
    故 A2 及其 payload 单独再断一次 `ok is True`。
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

    # 逐条钉 ok 值：case 对象的键恰好是 {name, ok}
    by_name = {str(c["name"]): c for c in out["cases"] if isinstance(c, dict) and "name" in c}
    not_ok = sorted(n for n, c in by_name.items() if c.get("ok") is not True)
    assert not not_ok, (
        f"这些场景的 ok 不是 True（failures 字段与逐条判定不自洽，输出形状可能已变）：{not_ok}"
    )

    # 「未做成 TTL 缓存」的反向断言：本探针最核心的一条，单独钉
    assert by_name["A2"].get("ok") is True, (
        "A2（两次串行调用 MUST 仍打 2 次后端）判定为失败 —— "
        "说明有人给 fetchKnownLemmas 加了 TTL/永久缓存：刚背的词会在 TTL 内不出现，"
        "覆盖率与高亮滞后于用户刚做的动作，是 UX 回归。"
    )
