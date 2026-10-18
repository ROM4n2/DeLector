# -*- coding: utf-8 -*-
"""Task 1 验收测试：index_dom_probe.mjs 行为探针与结构断言。"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = ROOT / "tools" / "index_dom_probe.mjs"


def _run_probe(custom_html_path: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js 未安装，跳过 MJS 探针执行")
    assert node is not None

    cmd: list[str] = [node, str(PROBE_PATH), "--json"]
    if custom_html_path:
        cmd.extend(["--html", custom_html_path])
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))


def test_probe_script_exists():
    assert PROBE_PATH.exists(), f"探针脚本缺失: {PROBE_PATH}"


def test_index_dom_probe_clean_run():
    """生产环境 static/index.html 运行探针必须 exit 0，且包含全量契约节点。"""
    res = _run_probe()
    assert res.returncode == 0, f"探针报错: {res.stderr}\nSTDOUT: {res.stdout}"
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["errors"] == []

    # 验证 9 大视图已全量识别
    views = data["blocks"]["views"]
    expected_views = {
        "view-home",
        "view-encounter",
        "view-reader",
        "view-cards",
        "view-progress",
        "view-writer",
        "view-exam",
        "view-german",
        "view-search",
    }
    assert set(views.keys()) == expected_views

    # 验证 2 大 aside 抽屉
    asides = data["blocks"]["asides"]
    expected_asides = {"writer-panel", "drawer"}
    assert set(asides.keys()) == expected_asides

    # 验证 6 大模态覆盖层
    modals = data["blocks"]["modals"]
    expected_modals = {
        "modal-overlay",
        "settings-overlay",
        "polish-overlay",
        "version-preview-overlay",
        "quiz-overlay",
        "cloze-overlay",
    }
    assert set(modals.keys()) == expected_modals

    # 验证关键结构组件闭合
    assert data["blocks"]["nav_desktop"] is True
    assert data["blocks"]["nav_mobile"] is True
    assert data["blocks"]["companion"] is True
    assert data["blocks"]["topbar"] is True


def test_index_dom_probe_mutation_detects_broken_view(tmp_path):
    """变异测试：破坏任一 <main> 闭合标签，探针必须报错并返回 exit 1。"""
    html_src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    # 破坏 view-home 闭合
    assert "view-home" in html_src
    mutated = html_src.replace("</main>", "<!-- broken --><section>", 1)
    mutated_file = tmp_path / "mutated_index.html"
    mutated_file.write_text(mutated, encoding="utf-8")

    res = _run_probe(custom_html_path=str(mutated_file))
    assert res.returncode == 1
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert any("view-home" in err for err in data["errors"])
