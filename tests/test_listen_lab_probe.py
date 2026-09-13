# -*- coding: utf-8 -*-
"""Task 5 前端行为探针驱动（红线 11）：node 直跑 tests/test_listen_lab_probe.mjs。

探针用 node:vm 的 SourceTextModule 把 static/js/listen-lab.js **真源码**逐字节
加载进沙箱，由自定义 linker 桩掉 ./core.js（api/esc/notify）与 ./player.js
（playGermanAudio），从模块命名空间驱动真实控制器（enterListenLab /
selectListenMaterial / setListenMode / listenSubmitDictation / listenNext /
listenSkip / listenRestart / listenSubmitCloze），把四条前后端契约逐字段钉死：

  1. GET  /api/listen/materials            → {items:[{source_type,source_id,title,level}]}
  2. GET  /api/listen/materials/{st}/{id}  → {sentences:[str]}（播放队列）
  3. POST /api/listen/diagnose body {expected,actual}
     → {tokens:[{token,status,hint}], correct, total, score}（六色反馈，status 六值枚举）
  4. POST /api/listen/trials  body {mode,source_type,source_id,level,total,correct,duration_sec}
     → {trial_id}（成绩落盘）

并内置 3 个变异用例（diagnose status→stat / materials 缺 title / sentences 非数组）
证明探针非恒真：契约字段名改错重跑同一场景，探针必须红，否则探针自身退出码 1。

运行（仓库根）：$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_listen_lab_probe.py -v
node 缺失时整文件显式 skip（显式理由），既不让 CI 因缺 node 变红，也不静默假绿。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tests" / "test_listen_lab_probe.mjs"

pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：前端行为探针需要 node 直跑真源码 listen-lab.js",
)


def _run_probe():
    """node --experimental-vm-modules 直跑探针（vm.SourceTextModule 需要该 flag）。"""
    res = subprocess.run(
        ["node", "--experimental-vm-modules", "--no-warnings", str(PROBE), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return res


def test_listen_lab_probe_contract_pinned():
    """四契约域 + 行为路径全绿，断言数不被掏空（防探针恒真化）。"""
    res = _run_probe()
    assert res.returncode == 0, (
        "listen-lab 行为探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out.get("ok") is True
    # 四契约域必须显式 pass（materials / detail_queue / diagnose_six_status / trials_persist）
    for name in ("materials", "detail_queue", "diagnose_six_status", "trials_persist"):
        assert out["contracts"].get(name) == "pass", f"契约域 {name} 未通过：{out['contracts']}"
    # 断言数下限：探针被悄悄砍断言（恒真化）时这里红
    assert out["probeChecks"] >= 20, f"探针断言数过低（{out['probeChecks']}），疑被掏空恒真化"


def test_listen_lab_probe_mutations_caught():
    """变异验证（红线 11）：契约字段名改错，探针必须捕获（红），证明非恒真。"""
    res = _run_probe()
    assert res.returncode == 0, (
        "listen-lab 行为探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out["mutations"], "探针没有内置任何变异用例（恒真风险）"
    for m in out["mutations"]:
        assert m["caught"] is True, (
            f"变异 {m['name']} 未被探针捕获 → 探针恒真（死测）：{m.get('sample')}"
        )
