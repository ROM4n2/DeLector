# -*- coding: utf-8 -*-
"""player_tray_probe.mjs 的 pytest wrapper（托盘 B 方案行为契约）。

探针本体在真实 Chromium 里跑（页面自检 + --dump-dom），钉住四条用户可见事实：
4 个音色可达且 aria-checked 唯一、折叠态回显当前音色、倍速显示与 data-speed
一致、音色不可用时提示可见；另含 360×800 无横向溢出。

本文件只做三件事：跑探针、断言成功路径、钉住关键场景名。判定口径与
`tests/test_probe_json_contract.py` 一致：探针 `--json` 必须输出精确
`{failures, total, cases}` 且退出码 0。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = ROOT / "tools" / "player_tray_probe.mjs"

REQUIRED_CASES: frozenset[str] = frozenset(
    {
        "voice:restores-from-storage",
        "voice:4-reachable",
        "voice:aria-checked-unique",
        "voice:collapsed-label",
        "voice:selection-syncs",
        "speed:label-matches-data-speed",
        "voice:unavailable-notice-visible",
        "status:visible-and-reads-engine-failure",
        "layout:360-no-horizontal-overflow",
        "layout:transport-and-speed-same-row",
    }
)

_WINDOWS_BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
_POSIX_BROWSERS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
)


def _has_browser() -> bool:
    """与探针的浏览器发现口径保持一致：环境变量优先，其次常见路径 / PATH。"""
    import os

    explicit = (
        os.environ.get("PLAYER_TRAY_BROWSER")
        or os.environ.get("CHROME_PATH")
        or os.environ.get("EDGE_PATH")
    )
    if explicit:
        return Path(explicit).is_file()
    if any(Path(p).is_file() for p in _WINDOWS_BROWSERS):
        return True
    return any(shutil.which(cmd) for cmd in _POSIX_BROWSERS)


def test_probe_script_exists() -> None:
    assert PROBE_PATH.exists(), f"探针脚本缺失: {PROBE_PATH}"


def test_player_tray_probe_clean_run() -> None:
    """探针在干净环境必须 exit 0，且关键场景全部通过。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js 未安装，跳过 MJS 探针执行")
    assert node is not None
    if not _has_browser():
        pytest.skip("未安装 Chromium/Edge/Chrome，跳过浏览器行为探针")

    res = subprocess.run(
        [node, str(PROBE_PATH), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        timeout=180,
    )
    assert res.returncode == 0, (
        f"探针退出码 {res.returncode}：\n"
        f"stdout(前 1000 字):\n{res.stdout[:1000]}\n"
        f"stderr(前 1000 字):\n{res.stderr[:1000]}"
    )

    data = json.loads(res.stdout)
    assert set(data) == {"failures", "total", "cases"}, f"非标准契约顶层键: {sorted(data)}"
    assert data["total"] >= len(REQUIRED_CASES), f"场景数骤降: {data['total']}"
    assert data["failures"] == 0, (
        "托盘契约失败：\n"
        + "\n".join(
            f"  - {c['name']} :: {json.dumps(c.get('detail'), ensure_ascii=False)}"
            for c in data["cases"]
            if not c["ok"]
        )
    )

    case_names = {c["name"] for c in data["cases"]}
    missing = sorted(REQUIRED_CASES - case_names)
    assert not missing, f"关键场景缺失（探针可能在空转）：{missing}"
