# -*- coding: utf-8 -*-
"""伴学 Agent 上下文来源与页面隔离行为探针（第一阶段）。

探针 runner 在 `tests/test_companion_context_probe.mjs`：用 node:vm 的
SourceTextModule 把 `static/js/companion.js` / `cp-state.js` / `cp-drawer.js`
的**真源码**逐字节载入沙箱，驱动 harvestStudyContext / reset / renderContextBar，
覆盖：

  1. reader 实时选区优先，articleTitle/CEFR 来自当前文章；
  2. reader 无选区时可回退 reader-state；
  3. 非 reader 页面的实时选区不得带上一篇的 articleTitle/CEFR；
  4. 非 reader 页面无选区时即使 state 残留旧句子也必须为空；
  5. 切页 reset 清空 activeContext；
  6. 非 reader 无上下文时 context bar 显示当前页面，快捷问句隐藏；
  7. reader 绑定句子时快捷问句恢复可见（已发版正常路径不回退）；
  8. main.js show() 的 reset 接线存在。

node 缺失时整文件显式 skip（不静默假绿）。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tests" / "test_companion_context_probe.mjs"

pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：伴学上下文探针需要 node 直跑真源码 companion.js / cp-drawer.js",
)


def _run_probe():
    return subprocess.run(
        ["node", "--experimental-vm-modules", "--no-warnings", str(PROBE), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )


def test_companion_context_probe_scenarios_pinned():
    """全场景真实执行通过，且断言数不被掏空（防探针恒真化）。"""
    res = _run_probe()
    assert res.returncode == 0, (
        "伴学上下文探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out.get("ok") is True
    assert out.get("checks", 0) >= 220, f"探针断言数过低（{out.get('checks')}），疑被掏空恒真化"

    expected = {
        "reader-live-selection",
        "reader-state-fallback",
        "non-reader-live-selection",
        "non-reader-empty",
        "reset-on-switch",
        "drawer-context-gate",
        "reader-path-regression",
        "writer-draft-context",
        "writer-draft-gate",
        "writer-draft-live-refresh",
        "progress-partition",
        "main-wiring",
        "scope-key",
        "session-scope-reset",
        "entry-gate",
        "drawer-tab-gate",
        "avatar-disabled-css",
        "cp-api-session-header",
        "submit-stream-happy-path",
        "submit-stream-error-event",
        "submit-stream-reject",
        "submit-writer-latest-context",
        "submit-cards-latest-context",
        "submit-input-guards",
    }
    scenarios = out.get("scenarios") or {}
    assert expected <= set(scenarios), f"探针缺少关键场景：{sorted(expected - set(scenarios))}"
    for name in expected:
        assert scenarios[name] == "pass", f"场景 {name} 未通过：{scenarios[name]!r}"
