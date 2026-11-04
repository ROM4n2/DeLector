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
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tests" / "test_companion_context_probe.mjs"

# 由 node:vm 真源码探针的 beginScenario/endScenario 插桩实测得到；总数下界由各项求和。
EXPECTED_SCENARIO_CHECKS = {
    "reader-live-selection": 4,
    "reader-state-fallback": 2,
    "non-reader-live-selection": 4,
    "non-reader-empty": 3,
    "reset-on-switch": 6,
    "drawer-context-gate": 7,
    "reader-path-regression": 5,
    "writer-draft-context": 8,
    "writer-draft-gate": 7,
    "progress-partition": 11,
    "writer-draft-live-refresh": 6,
    "card-current-context": 5,
    "card-partition": 6,
    "card-empty-degrade": 6,
    "definition-fallback-ui": 8,
    "proposal-batch-actions": 7,
    "proposal-failure-paths": 6,
    "session-global-groups": 8,
    "session-cross-scope-reset": 5,
    "proposal-sentence-fields": 2,
    "proposal-multi-action": 8,
    "writer-revision-apply": 7,
    "main-wiring": 4,
    "scope-key": 2,
    "session-scope-reset": 3,
    "entry-gate": 8,
    "drawer-tab-gate": 1,
    "avatar-disabled-css": 3,
    "german-entry-lock": 2,
    "user-reenable": 1,
    "cp-api-session-header": 8,
    "submit-stream-happy-path": 70,
    "submit-stream-error-event": 13,
    "submit-stream-reject": 12,
    "submit-stream-resume": 11,
    "submit-stream-resume-existing-scope": 6,
    "submit-stream-resume-stale": 6,
    "submit-stream-turn-ownership": 12,
    "submit-stream-recover-after-unsaved": 7,
    "submit-writer-latest-context": 15,
    "submit-cards-latest-context": 15,
    "submit-input-guards": 5,
}
MIN_TOTAL_CHECKS = sum(EXPECTED_SCENARIO_CHECKS.values())

pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：伴学上下文探针需要 node 直跑真源码 companion.js / cp-drawer.js",
)


def _run_probe(probe=PROBE):
    env = os.environ.copy()
    env["DELECTOR_PROBE_ROOT"] = str(ROOT)
    return subprocess.run(
        ["node", "--experimental-vm-modules", "--no-warnings", str(probe), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
    )


def _assert_probe_output(out):
    assert out.get("ok") is True
    scenarios = out.get("scenarios")
    scenario_checks = out.get("scenarioChecks")
    assert isinstance(scenarios, dict), "探针缺少场景状态映射"
    assert isinstance(scenario_checks, dict), "探针缺少 scenarioChecks 场景级真实计数"

    expected_names = set(EXPECTED_SCENARIO_CHECKS)
    assert set(scenarios) == expected_names, (
        f"探针场景状态键不一致：缺少={sorted(expected_names - set(scenarios))}，"
        f"新增={sorted(set(scenarios) - expected_names)}"
    )
    assert set(scenario_checks) == expected_names, (
        f"探针场景计数键不一致：缺少={sorted(expected_names - set(scenario_checks))}，"
        f"新增={sorted(set(scenario_checks) - expected_names)}"
    )

    for name, minimum in EXPECTED_SCENARIO_CHECKS.items():
        assert scenarios[name] == "pass", f"场景 {name} 未通过：{scenarios[name]!r}"
        actual = scenario_checks[name]
        assert isinstance(actual, int), f"场景 {name} checks 不是整数：{actual!r}"
        assert actual >= minimum, f"场景 {name} 断言数过低（{actual} < {minimum}），疑被删除或掏空"

    total = out.get("checks")
    assert isinstance(total, int), f"探针总 checks 不是整数：{total!r}"
    assert total >= MIN_TOTAL_CHECKS, f"探针总断言数过低（{total} < {MIN_TOTAL_CHECKS}），疑被掏空"
    assert total == sum(scenario_checks.values()), "总 checks 与逐场景插桩计数之和不一致"


def _read_successful_probe(res):
    assert res.returncode == 0, (
        "伴学上下文探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    return json.loads(res.stdout)


def test_companion_context_probe_scenarios_pinned():
    """全场景真实执行通过，逐场景与总断言数均不得被掏空。"""
    _assert_probe_output(_read_successful_probe(_run_probe()))


def test_companion_context_probe_rejects_deleted_scenario_body(tmp_path):
    """完整删除一个场景本体后，探针可运行，但该场景必因低于自身下界而红。"""
    name = "main-wiring"
    source = PROBE.read_text(encoding="utf-8")
    start = source.index(f'  beginScenario("{name}");')
    body_start = source.index("\n", start) + 1
    end = source.index("  endScenario();", body_start)
    assert source[body_start:end].count("check(") == EXPECTED_SCENARIO_CHECKS[name]
    mutant = tmp_path / "deleted-scenario-body.mjs"
    mutant.write_text(source[:body_start] + source[end:], encoding="utf-8")

    out = _read_successful_probe(_run_probe(mutant))
    assert out["scenarioChecks"][name] == 0
    with pytest.raises(AssertionError, match=rf"{name}.*断言数过低"):
        _assert_probe_output(out)


def test_companion_context_probe_rejects_deleted_begin_marker(tmp_path):
    """删除 begin 标记后不得抛异常冒充 RED，而应因场景键缺失被契约断言拒绝。"""
    name = "reader-live-selection"
    source = PROBE.read_text(encoding="utf-8")
    marker = f'  beginScenario("{name}");\n'
    assert source.count(marker) == 1
    mutant = tmp_path / "deleted-begin-marker.mjs"
    mutant.write_text(source.replace(marker, "", 1), encoding="utf-8")

    out = _read_successful_probe(_run_probe(mutant))
    assert name not in out["scenarioChecks"]
    with pytest.raises(AssertionError, match="场景状态键不一致"):
        _assert_probe_output(out)
