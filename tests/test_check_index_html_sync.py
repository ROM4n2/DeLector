# -*- coding: utf-8 -*-
"""Task 2 验收测试：tools/build_index_html.py 与 tools/check_index_html_sync.py。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "tools" / "build_index_html.py"
CHECK_SCRIPT = ROOT / "tools" / "check_index_html_sync.py"


def _run(script: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    """统一以 UTF-8 读侧运行脚本（locale 无关，理由见 test_check_index_html_sync_clean）。"""
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )


def test_build_and_check_scripts_exist():
    assert BUILD_SCRIPT.exists(), f"构建脚本缺失: {BUILD_SCRIPT}"
    assert CHECK_SCRIPT.exists(), f"校验脚本缺失: {CHECK_SCRIPT}"


def test_check_index_html_sync_clean():
    """当前生产仓库 index.html 与各分块模板比对必须完全一致 (exit 0)。"""
    # encoding 必须显式：默认按 locale 解码（GitHub Windows runner = cp1252），而子进程写的是
    # UTF-8 中文 ⇒ 解码崩在 subprocess 读线程内，returncode 仍为 0 但 res.stdout 变成 None。
    res = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, f"同步校验失败:\n{res.stdout}\nSTDERR: {res.stderr}"
    assert any(k in res.stdout for k in ("通过", "PASS", "synced", "放行"))


def test_build_index_html_check_clean():
    """`build_index_html.py --check` 必须与同步门禁同结论（当前仓态 exit 0）。

    回归锚点：读侧曾用 `read_text()`，universal newlines 把磁盘 CRLF 吃成 LF ⇒ 恒假红，
    与 `check_index_html_sync.py` 的 PASS 自相矛盾。
    """
    res = _run(BUILD_SCRIPT, "--check")
    assert res.returncode == 0, f"build --check 假红:\n{res.stdout}\nSTDERR: {res.stderr}"
    assert "校验通过" in res.stdout


def test_build_index_html_check_mutation_detects_drift(tmp_path):
    """变异自证：`--check` 不是恒绿 —— 目标被改一行必须 exit 1。"""
    target = tmp_path / "index.html"
    res_build = _run(BUILD_SCRIPT, "--output", str(target))
    assert res_build.returncode == 0, f"装配副本失败:\n{res_build.stderr}"
    assert _run(BUILD_SCRIPT, "--check", "--output", str(target)).returncode == 0

    target.write_bytes((target.read_bytes().decode("utf-8") + "\r\n<!-- drift -->\r\n").encode("utf-8"))
    res_drift = _run(BUILD_SCRIPT, "--check", "--output", str(target))
    assert res_drift.returncode == 1, "漂移未被 --check 检出 ⇒ 门禁形同虚设"


def test_check_index_html_sync_mutation_detects_drift(tmp_path):
    """变异测试：若 static/index.html 被单独修改而模板未更新，必须 exit 1 阻断。"""
    script_content = CHECK_SCRIPT.read_text(encoding="utf-8")
    assert "difflib" in script_content
    assert "assemble_index_html" in script_content
