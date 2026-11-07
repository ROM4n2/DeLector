# -*- coding: utf-8 -*-
"""桌宠气泡「模态挂起过期不得复活」探针接线（tests/test_companion_bubble_resume_probe.mjs）。

事故背景（P2 复审）：写作页移动端 sheet 是模态，展开时 `repositionBubble()` 把气泡
收起并记下挂起标记。旧实现关闭模态时**无条件** `remove('hidden')` —— sheet 开超过
气泡自然 TTL（6.5s）时，被挂起的过期气泡会在关闭瞬间复活。

探针把 `static/js/companion.js` 真源码喂进 node:vm 的 SourceTextModule 真跑，
用假时钟驱动 say() / repositionBubble() 的模态分支；场景名即契约名。
本接线额外做**变异验证**：把恢复前的过期判断改成恒真，探针必须当场变红，
证明它不是「字符串在不在」式死测。

node 缺失时整文件显式 skip（不静默假绿）。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tests" / "test_companion_bubble_resume_probe.mjs"
COMPANION = ROOT / "static" / "js" / "companion.js"

# 探针实测场景计数；总数下界由各项求和，防「删场景换全绿」。
EXPECTED_CASE_CHECKS = {
    "visible-after-say": 1,
    "modal-open-hides": 1,
    "resume-within-ttl-shows": 1,
    "resume-after-long-modal-stays-hidden": 1,
    "expired-bubble-stays-dead-on-repeat": 1,
    "say-again-after-expiry-shows": 1,
    "new-bubble-expires-on-own-ttl": 1,
}
MIN_TOTAL_CHECKS = sum(EXPECTED_CASE_CHECKS.values())

GUARD_ANCHOR = "if (bubbleExpiresAt > Date.now()) {"

pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：气泡挂起过期探针需要 node --experimental-vm-modules 直跑真源码",
)


def _run_probe(extra_env=None):
    env = os.environ.copy()
    env["DELECTOR_PROBE_ROOT"] = str(ROOT)
    env.update(extra_env or {})
    return subprocess.run(
        ["node", "--experimental-vm-modules", "--no-warnings", str(PROBE), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
    )


def _parse(res):
    assert res.returncode == 0, (
        "气泡挂起过期探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out.get("ok") is True, f"探针未自陈通过：{out!r}"
    assert out.get("failures") == 0, f"探针有失败场景：{out!r}"
    return out


def test_bubble_resume_probe_scenarios_pinned():
    """全场景真实执行通过，场景名与断言数均不得被掏空。"""
    out = _parse(_run_probe())

    case_names = [c["name"] for c in out["cases"]]
    assert set(case_names) == set(EXPECTED_CASE_CHECKS), (
        f"探针场景键不一致：缺少={sorted(set(EXPECTED_CASE_CHECKS) - set(case_names))}，"
        f"新增={sorted(set(case_names) - set(EXPECTED_CASE_CHECKS))}"
    )
    assert all(c["ok"] is True for c in out["cases"]), f"存在失败场景：{out['cases']!r}"
    assert out["total"] >= MIN_TOTAL_CHECKS, (
        f"探针总断言数过低（{out['total']} < {MIN_TOTAL_CHECKS}），疑被删场景或掏空"
    )


def test_bubble_resume_probe_catches_unconditional_resume(tmp_path):
    """变异验证：恢复前的过期判断改成恒真，探针必须红在「过期不得复活」场景。"""
    source = COMPANION.read_text(encoding="utf-8")
    assert source.count(GUARD_ANCHOR) == 1, (
        f"companion.js 缺少唯一的过期判断锚点 {GUARD_ANCHOR!r}：探针变异验证已失效"
    )

    mutant = tmp_path / "companion-unconditional-resume.js"
    mutant.write_text(source.replace(GUARD_ANCHOR, "if (true) {"), encoding="utf-8")

    res = _run_probe({"DELECTOR_COMPANION_SRC": str(mutant)})
    assert res.returncode != 0, "恒真恢复的变异未被探针捕获：探针可能已退化为死测"
    out = json.loads(res.stdout)
    assert out["ok"] is False
    failed = {c["name"] for c in out["cases"] if not c["ok"]}
    assert "resume-after-long-modal-stays-hidden" in failed, (
        f"变异未被关键场景捕获，实际失败场景：{sorted(failed)}"
    )
