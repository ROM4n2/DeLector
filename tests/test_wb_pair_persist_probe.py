# -*- coding: utf-8 -*-
"""持久配对凭证探针接线（tools/wb_pair_persist_probe.mjs，此前无 pytest wrapper ⇒ 永不入 CI）。

事故背景（Stage B M2）：配对凭证要长期有效，前提是「随时能一键作废」。探针把
workbench.html 里真实的 wbsync 源码切进 node:vm（桩 localStorage / fetch），断言：
  1) `pair.set(host,key)` 真把 {host,key} 落进 localStorage（不只是内存里有效）；
  2) `pair.revoke()` 会 POST /api/wb/state/key 让服务端重新生成密钥；
  3) revoke 后本地配对状态被清除（pairInfo() 为 null 且 removeItem 被调用）；
  4) revoke 后本机 pushNow 用**新 key** 推送 —— 主机不能被自己作废的 key 卡死。

探针输出属 C 类（扁平结论字段）。⚠ `persistedPair.ts` / `restoredPairOnBoot.ts`
来自被测实现的 `Date.now()`，**是墙钟时间、逐次不同** ⇒ 本文件 MUST NOT 断言它的
取值（否则每跑一次就随机红），只断言同一次运行内两者相等。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

PROBE_NAME = "wb_pair_persist_probe"


def _run() -> dict[str, Any]:
    require_node()
    return run_json_probe(PROBE_NAME)


def test_wb_pair_persist_probe_reports_no_failures() -> None:
    """探针自陈全绿，且被测维度齐全（防「删维度换全绿」）。

    场景数守卫取 5：实测顶层 6 个被测维度（persistedPair / restoredPairOnBoot /
    revokePosted / pairClearedAfterRevoke / pushedWithNewKey / requests），
    留 1 个余量但 > 1。
    """
    out = _run()
    assert_probe_clean(PROBE_NAME, out)

    assert len(scenario_keys(out)) >= 5, (
        f"探针被测维度异常偏少（{len(scenario_keys(out))}），可能维度被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(
        PROBE_NAME,
        out,
        (
            "persistedPair",
            "restoredPairOnBoot",
            "revokePosted",
            "pairClearedAfterRevoke",
            "pushedWithNewKey",
            "requests",
        ),
    )


def test_wb_pair_persist_probe_samples_match_revoke_contract() -> None:
    """第二个用例：钉死 revoke 契约的**具体口径**（防「输出形状变了但全绿」）。

    钉 host/key 的**夹具常量**（探针源码里 PAIR 是硬编码的，不是运行期变量），
    但 MUST NOT 钉 `ts`（墙钟时间，逐次不同）。同时钉住三个布尔结论逐字为 True，
    以及请求序列的 method/url 形状。
    """
    out = _run()

    persisted = out["persistedPair"]
    assert persisted["host"] == "192.168.1.103", f"落盘配对 host 不符：{persisted!r}"
    assert persisted["key"] == "a1b2c3d4e5f60718293a4b5c6d7e8f90", f"落盘配对 key 不符：{persisted!r}"
    assert isinstance(persisted["ts"], int), f"落盘配对应带整数 ts：{persisted!r}"

    restored = out["restoredPairOnBoot"]
    assert restored["host"] == persisted["host"] and restored["key"] == persisted["key"], (
        f"boot 恢复的配对与落盘的不一致：{restored!r} vs {persisted!r}"
    )
    # ts 来自 Date.now()，只断言"被写进去了"，不钉取值
    assert isinstance(restored["ts"], int), f"boot 恢复配对应带整数 ts：{restored!r}"

    for field in ("revokePosted", "pairClearedAfterRevoke", "pushedWithNewKey"):
        assert out[field] is True, f"{field} 应为 True（旧 key 会永不过期 / 本机被自己卡死）：{out[field]!r}"

    urls = [(r["method"], r["url"]) for r in out["requests"]]
    assert ("POST", "/api/wb/state/key") in urls, f"缺少 revoke 的 POST /api/wb/state/key：{urls!r}"
    assert ("PUT", "/api/wb/state") in urls, f"撤销后缺少换新 key 的 PUT /api/wb/state：{urls!r}"
