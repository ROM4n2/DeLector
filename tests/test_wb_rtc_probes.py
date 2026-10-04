# -*- coding: utf-8 -*-
"""WebRTC 建连 + 自动重连两个探针接线（此前均无 pytest wrapper ⇒ 永不入 CI）。

Stage B M4/M5 背景：`wbsync.rtc` 经配对远端中继建 WebRTC，DataChannel 收发信封并
静默合并（wb_rtc_connect_probe.mjs）；WebRTC 断线要能自动重建但不能无限重试，
WebRTC 不可用（企业网禁 UDP/ICE、老浏览器）时必须退回 Stage A 的 HTTP 轮询
保证「至少可达」（wb_rtc_reconnect_probe.mjs）。

两个探针输出均属 C 类（扁平结论字段，无 cases）。每个探针两个独立用例，
可单独 `pytest tests/test_wb_rtc_probes.py::test_xxx` 跑。
"""

from typing import Any

from probe_runner import (
    assert_probe_clean,
    assert_scenarios_present,
    require_node,
    run_json_probe,
    scenario_keys,
)

CONNECT_PROBE = "wb_rtc_connect_probe"
RECONNECT_PROBE = "wb_rtc_reconnect_probe"


def _run(name: str) -> dict[str, Any]:
    require_node()
    return run_json_probe(name)


# ── wb_rtc_connect_probe：建连 / 握手 / 快照 / 静默合并 ──────────────────────────

def test_wb_rtc_connect_probe_reports_no_failures() -> None:
    """建连探针自陈全绿，且被测维度齐全（防「删维度换全绿」）。

    场景数守卫取 7：实测顶层 9 个被测维度，留 2 个余量但 > 1。
    """
    out = _run(CONNECT_PROBE)
    assert_probe_clean(CONNECT_PROBE, out)

    assert len(scenario_keys(out)) >= 7, (
        f"建连探针维度异常偏少（{len(scenario_keys(out))}），可能维度被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(
        CONNECT_PROBE,
        out,
        (
            "connected",
            "channelCreated",
            "offerPostUrl",
            "offerHasPairKey",
            "answerApplied",
            "candidateApplied",
            "snapshotSentOnOpen",
            "mergedCardIds",
            "mergeSilent",
        ),
    )


def test_wb_rtc_connect_probe_samples_match_handshake_contract() -> None:
    """建连探针第二个用例：钉死握手契约的具体口径。

    钉 offer 必须发往**配对远端中继**且带 `X-WB-Key`（否则连的是随机 peer），
    answer / candidate 都必须被应用，且合并走静默模式。
    """
    out = _run(CONNECT_PROBE)

    assert out["connected"] is True, "WebRTC 未连通"
    assert out["channelCreated"] is True, "DataChannel 未创建"

    assert out["offerPostUrl"] == "http://192.168.1.103/api/wb/rtc/signal", (
        f"offer 发往的 URL 不符（应是配对远端中继）：{out['offerPostUrl']!r}"
    )
    assert out["offerHasPairKey"] is True, "offer 未带 X-WB-Key：会连到非配对 peer"

    assert out["answerApplied"] is True, "对端 answer 未被应用"
    assert out["candidateApplied"] is True, "ICE candidate 未被应用"
    assert out["snapshotSentOnOpen"] is True, "channel open 后未发送快照：手机端拿不到历史"

    assert out["mergedCardIds"] == ["cx"], f"applyMerge 收到的卡片 id 不符：{out['mergedCardIds']!r}"
    assert out["mergeSilent"] is True, "DataChannel 合并非静默：后台同步会弹窗/切视图"


# ── wb_rtc_reconnect_probe：去抖重连 + 降级 + HTTP 兜底 ─────────────────────────

def test_wb_rtc_reconnect_probe_reports_no_failures() -> None:
    """重连探针自陈全绿，且被测维度齐全（防「删维度换全绿」）。

    场景数守卫取 6：实测顶层 7 个被测维度，留 1 个余量但 > 1。
    """
    out = _run(RECONNECT_PROBE)
    assert_probe_clean(RECONNECT_PROBE, out)

    assert len(scenario_keys(out)) >= 6, (
        f"重连探针维度异常偏少（{len(scenario_keys(out))}），可能维度被删：{sorted(scenario_keys(out))}"
    )
    assert_scenarios_present(
        RECONNECT_PROBE,
        out,
        (
            "reconnectedAfterFailure",
            "pcCountAfterStart",
            "pcCountAfterFailures",
            "degradedAfterMaxFails",
            "noReconnectAfterDegrade",
            "degradedWithoutWebRTC",
            "httpFallbackAlive",
        ),
    )


def test_wb_rtc_reconnect_probe_samples_match_debounce_and_fallback() -> None:
    """重连探针第二个用例：钉死「去抖重建一次 → 到上限降级 → 降级后停手」的口径。

    `pcCountAfterStart=1 / pcCountAfterFailures=2` 是「去抖重建恰好一次」的
    硬证据：断一次只应多建 1 个 peer，失败到上限则进入降级且**不再**空转建连。
    """
    out = _run(RECONNECT_PROBE)

    assert out["pcCountAfterStart"] == 1, f"初始应只建 1 个 peer：{out['pcCountAfterStart']!r}"
    assert out["pcCountAfterFailures"] == 2, (
        f"断线后应去抖重建**恰好一次**（1→2），实测 {out['pcCountAfterFailures']!r}"
        f"（>2 说明无限重试/空转打服务端，=1 说明断了不重连）"
    )
    assert out["reconnectedAfterFailure"] is True, "断线未触发自动重建"

    assert out["degradedAfterMaxFails"] is True, "连续失败到上限后未降级到 HTTP"
    assert out["noReconnectAfterDegrade"] is True, "降级后仍在继续建连：空转打服务端"

    assert out["degradedWithoutWebRTC"] is True, "无 RTCPeerConnection 时未直接降级"
    assert out["httpFallbackAlive"] is True, "降级后 Stage A 的 HTTP 拉取没发生：彻底失联"
