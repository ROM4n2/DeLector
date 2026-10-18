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
    """生产环境 static/index.html 运行探针必须 exit 0，且输出标准三键契约。"""
    res = _run_probe()
    assert res.returncode == 0, f"探针报错: {res.stderr}\nSTDOUT: {res.stdout}"
    data = json.loads(res.stdout)
    assert data["failures"] == 0
    assert data["total"] == 21
    case_names = {c["name"] for c in data["cases"]}

    # 验证 9 大视图已全量识别
    expected_views = {
        "view:view-home",
        "view:view-encounter",
        "view:view-reader",
        "view:view-cards",
        "view:view-progress",
        "view:view-writer",
        "view:view-exam",
        "view:view-german",
        "view:view-search",
    }
    assert expected_views.issubset(case_names)

    # 验证 2 大 aside 抽屉
    expected_asides = {"aside:writer-panel", "aside:drawer"}
    assert expected_asides.issubset(case_names)

    # 验证 6 大模态覆盖层
    expected_modals = {
        "modal:modal-overlay",
        "modal:settings-overlay",
        "modal:polish-overlay",
        "modal:version-preview-overlay",
        "modal:quiz-overlay",
        "modal:cloze-overlay",
    }
    assert expected_modals.issubset(case_names)

    # 验证关键结构组件闭合
    assert "layout:nav_desktop" in case_names
    assert "layout:nav_mobile" in case_names
    assert "layout:companion" in case_names
    assert "layout:topbar" in case_names


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
    assert data["failures"] > 0
    failed_names = [c["name"] for c in data["cases"] if not c["ok"]]
    assert any("view-home" in name for name in failed_names)
