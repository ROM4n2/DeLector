# -*- coding: utf-8 -*-
"""Windows 便携版 helper 脚本生成与解压（`delector/core/update_portable.py`）。"""

import zipfile
from pathlib import Path

import pytest

from delector.core.update_portable import (
    build_apply_script,
    is_writable_root,
    powershell_command,
    prepare_payload,
)


def _zip_with(tmp_path: Path, *, inner: str = "DeLector-vX-Windows-x64-Portable") -> Path:
    archive = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(f"{inner}/DeLector.exe", b"stub")
        handle.writestr(f"{inner}/_internal/base.dll", b"stub")
    return archive


def test_prepare_payload_finds_executable_root(tmp_path: Path) -> None:
    staging = tmp_path / "staging"

    root = prepare_payload(_zip_with(tmp_path), staging)

    assert (root / "DeLector.exe").is_file()
    assert (root / "_internal" / "base.dll").is_file()


def test_prepare_payload_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.exe", b"x")

    with pytest.raises(ValueError):
        prepare_payload(archive, tmp_path / "staging")


def test_prepare_payload_requires_executable(tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("readme.txt", b"x")

    with pytest.raises(ValueError):
        prepare_payload(archive, tmp_path / "staging")


def test_is_writable_root(tmp_path: Path) -> None:
    assert is_writable_root(tmp_path) is True
    assert not (tmp_path / ".delector-write-probe").exists()


def test_apply_script_quotes_every_path_and_waits_for_pid(tmp_path: Path) -> None:
    tricky = tmp_path / "O'Brien's app"
    script = build_apply_script(
        pid=4321,
        source_dir=tricky / "source",
        target_dir=tricky / "target",
        restart_exe=tricky / "target" / "DeLector.exe",
        backup_dir=tricky / "backup",
        log_path=tricky / "error.log",
    )

    # 单引号必须双写，否则路径里的 ' 会把脚本提前截断
    assert "O''Brien''s app" in script
    assert "Wait-Process -Id 4321" in script
    assert "Move-Item" in script and "Copy-Item" in script and "Start-Process" in script
    assert "exit 1" in script  # 失败要有非零退出码
    assert script.count("$target = '") == 1


def test_powershell_command_is_non_interactive(tmp_path: Path) -> None:
    command = powershell_command(tmp_path / "apply.ps1")

    assert command[:5] == ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    assert command[-1].endswith("apply.ps1")
