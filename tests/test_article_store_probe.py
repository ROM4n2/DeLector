# -*- coding: utf-8 -*-
"""文章列表 store / 缓存优先行为探针接线（ADR-0032 阶段一 + 阶段二）。

探针 `tools/article_store_probe.mjs` 把 `static/js/article-store.js` 与
`article-seed.js` 真源码放进 node:vm 沙箱，用 localStorage / fetchArticles /
removeArticle 桩验证：
  - 首装无缓存时首帧来自内置快照，且在 fetch 返回前就已通知；
  - 只有成功的列表 GET 才写缓存；
  - 有缓存时首帧是缓存行，真实数据到达后静默替换；
  - 请求失败保留旧数据（stale + error）；
  - 删除等写操作先失效缓存，再由成功 GET 重建。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "article_store_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_article_store_probe_reports_no_failures() -> None:
    out = _run()
    assert_probe_clean(PROBE_NAME, out)
    assert out["total"] >= 10, f"探针场景数异常偏少（{out['total']}），可能场景被删"
    assert len(scenario_keys(out)) == out["total"], (
        f"cases 里的场景数与 total 不符（{len(scenario_keys(out))} vs {out['total']}）"
    )


def test_article_store_probe_key_scenarios_present() -> None:
    """逐字钉死关键场景，防「删一整段换全绿」。"""
    out = _run()
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "A1-首装首帧来自内置快照",
            "A2-fetch 未返回就通知了首帧",
            "A4-成功后 ready 且替换内置快照",
            "A5-成功 GET 才写缓存",
            "B1-有缓存时首帧是缓存行",
            "B2-真实数据静默替换缓存",
            "C1-失败保留旧数据并标记 stale+error",
            "D2-删除后先失效缓存",
            "D3-成功 GET 后缓存重建为剩余项",
            "E1-缺键/坏 id 被丢弃",
        ),
    )
