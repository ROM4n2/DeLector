# -*- coding: utf-8 -*-
"""平台 / 安装形态判定（`delector/core/update_host.py`）。"""

from pathlib import Path

import pytest

from delector.core.update_host import (
    UNINSTALL_KEY,
    detect_arch,
    detect_platform,
    detect_windows_channel,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ISS = REPO_ROOT / "installer" / "DeLector.iss"


@pytest.mark.parametrize(
    "android,sys_platform,expected",
    [
        (True, "linux", "android"),      # Chaquopy：sys.platform 是 linux，必须被 android 覆盖
        (False, "win32", "windows"),
        (False, "linux", "linux"),
        (False, "darwin", "macos"),
    ],
)
def test_detect_platform(android: bool, sys_platform: str, expected: str) -> None:
    assert detect_platform(android=android, sys_platform=sys_platform) == expected


@pytest.mark.parametrize(
    "machine,expected",
    [("AMD64", "x64"), ("x86_64", "x64"), ("arm64", "arm64"), ("aarch64", "arm64"), ("", "x64")],
)
def test_detect_arch(machine: str, expected: str) -> None:
    assert detect_arch(machine) == expected


def test_uninstaller_file_means_installer(tmp_path: Path) -> None:
    (tmp_path / "unins000.exe").write_bytes(b"")

    assert detect_windows_channel(tmp_path, lambda key: False) == "installer"


def test_uninstall_registry_key_means_installer(tmp_path: Path) -> None:
    assert detect_windows_channel(tmp_path, lambda key: key == UNINSTALL_KEY) == "installer"


def test_no_marker_means_portable(tmp_path: Path) -> None:
    assert detect_windows_channel(tmp_path, lambda key: False) == "portable"


def test_uninstall_key_stays_in_sync_with_inno_app_id() -> None:
    """安装形态判定的键必须与 Inno 的 AppId 同源；改 .iss 未同步这里会静默误判。"""
    iss = ISS.read_text(encoding="utf-8")
    app_id = "6F4A2C1E-9B3D-4E7A-8C55-1D2E3F4A5B6C"

    assert app_id in iss
    assert app_id in UNINSTALL_KEY
    assert UNINSTALL_KEY.endswith("_is1")
