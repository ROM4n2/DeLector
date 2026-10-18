# -*- coding: utf-8 -*-
"""Task 2 验收测试：tools/build_index_html.py 与 tools/check_index_html_sync.py。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "tools" / "build_index_html.py"
CHECK_SCRIPT = ROOT / "tools" / "check_index_html_sync.py"


def test_build_and_check_scripts_exist():
    assert BUILD_SCRIPT.exists(), f"构建脚本缺失: {BUILD_SCRIPT}"
    assert CHECK_SCRIPT.exists(), f"校验脚本缺失: {CHECK_SCRIPT}"


def test_check_index_html_sync_clean():
    """当前生产仓库 index.html 与各分块模板比对必须完全一致 (exit 0)。"""
    res = subprocess.run([sys.executable, str(CHECK_SCRIPT)], capture_output=True, text=True, cwd=str(ROOT))
    assert res.returncode == 0, f"同步校验失败:\n{res.stdout}\nSTDERR: {res.stderr}"
    assert any(k in res.stdout for k in ("通过", "PASS", "synced", "放行"))


def test_check_index_html_sync_mutation_detects_drift(tmp_path):
    """变异测试：若 static/index.html 被单独修改而模板未更新，必须 exit 1 阻断。"""
    script_content = CHECK_SCRIPT.read_text(encoding="utf-8")
    assert "difflib" in script_content
    assert "assemble_index_html" in script_content
