# -*- coding: utf-8 -*-
"""验收测试：tools/build_css.py 与 tools/check_css_sync.py 的零差异拼接契约。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "tools" / "build_css.py"
CHECK_SCRIPT = ROOT / "tools" / "check_css_sync.py"

sys.path.insert(0, str(ROOT / "tools"))

from build_css import SOURCE_FILES, assemble_css  # noqa: E402


def _run(script: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    """统一以 UTF-8 读侧运行脚本（locale 无关，理由同 test_check_index_html_sync）。"""
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


def test_check_css_sync_clean():
    """当前仓态：src/css 分片拼接物与 static/style.css 必须逐字节一致 (exit 0)。"""
    res = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, f"同步校验失败:\n{res.stdout}\nSTDERR: {res.stderr}"
    assert "PASS" in res.stdout and "sha256=" in res.stdout


def test_build_css_check_clean():
    """`build_css.py --check` 必须与同步门禁同结论（当前仓态 exit 0）。"""
    res = _run(BUILD_SCRIPT, "--check")
    assert res.returncode == 0, f"build --check 假红:\n{res.stdout}\nSTDERR: {res.stderr}"
    assert "校验通过" in res.stdout and "sha256=" in res.stdout


def test_check_css_sync_mutation_detects_drift(tmp_path):
    """同步闸本身也必须可红：产物多一个字节时 check_css_sync.py 必须 exit 1。"""
    target = tmp_path / "style.css"
    assert _run(BUILD_SCRIPT, "--output", str(target)).returncode == 0
    assert _run(CHECK_SCRIPT, "--output", str(target)).returncode == 0

    target.write_bytes(target.read_bytes().replace(b"}", b"} ", 1))
    res = _run(CHECK_SCRIPT, "--output", str(target))
    assert res.returncode == 1, "同步闸对字节漂移未判红 ⇒ 门禁形同虚设"
    assert "FAIL" in res.stderr and "产物 sha256=" in res.stderr


def test_build_css_check_mutation_detects_drift(tmp_path):
    """变异自证：`--check` 不是恒绿 —— 目标被改一个字节必须 exit 1。"""
    target = tmp_path / "style.css"
    res_build = _run(BUILD_SCRIPT, "--output", str(target))
    assert res_build.returncode == 0, f"拼接副本失败:\n{res_build.stderr}"
    assert _run(BUILD_SCRIPT, "--check", "--output", str(target)).returncode == 0

    target.write_bytes(target.read_bytes() + b"\r\n/* drift */\r\n")
    assert _run(BUILD_SCRIPT, "--check", "--output", str(target)).returncode == 1, (
        "漂移未被 --check 检出 ⇒ 门禁形同虚设"
    )


def test_assemble_rejects_unlisted_source(tmp_path):
    """目录里出现未登记分片必须失败，防止新分片永远不参与构建。"""
    for name in SOURCE_FILES:
        (tmp_path / name).write_bytes(b"/* ok */\r\n")
    (tmp_path / "99-orphan.css").write_bytes(b"/* orphan */\r\n")

    try:
        assemble_css(tmp_path)
    except ValueError as exc:
        assert "未登记" in str(exc)
    else:
        raise AssertionError("未登记分片未被拒绝")


def test_assemble_rejects_missing_source(tmp_path):
    """已登记分片缺失必须失败，禁止静默跳过。"""
    for name in SOURCE_FILES[:-1]:
        (tmp_path / name).write_bytes(b"/* ok */\r\n")

    try:
        assemble_css(tmp_path)
    except ValueError as exc:
        assert "缺少" in str(exc)
    else:
        raise AssertionError("缺失分片未被拒绝")
