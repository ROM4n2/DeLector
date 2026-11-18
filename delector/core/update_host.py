# -*- coding: utf-8 -*-
"""平台 / 安装形态判定（纯函数，零副作用）。

为什么单独成模块：更新链路里最容易写错的一步是"这台机器该拿哪个包"。Chaquopy 下
Android 的 ``sys.platform`` 是 ``linux``，只看 ``sys.platform`` 会把 Android 误判成
Linux 并去下 tar.gz。因此平台判定 MUST 先问 ``is_android()`` 的调用方，再回落
``sys.platform``；本模块把这套优先级钉在一个可单测的纯函数里。
"""

from pathlib import Path
from typing import Callable, Literal

__all__ = [
    "Arch",
    "Channel",
    "Platform",
    "UNINSTALL_KEY",
    "detect_arch",
    "detect_platform",
    "detect_windows_channel",
]

Platform = Literal["windows", "linux", "macos", "android"]
Channel = Literal["installer", "portable"]
Arch = Literal["x64", "arm64"]

# Inno Setup 的 AppId（installer/DeLector.iss:35）+ `_is1` 后缀 = per-user 卸载键。
# 安装形态判定用它而不是"目录里有没有 exe"：便携版同样有 exe。
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{6F4A2C1E-9B3D-4E7A-8C55-1D2E3F4A5B6C}_is1"
)


def detect_platform(*, android: bool, sys_platform: str) -> Platform:
    """Android 优先于 ``sys_platform``（Chaquopy 下后者是 ``linux``）。"""
    if android:
        return "android"
    if sys_platform.startswith("win"):
        return "windows"
    if sys_platform == "darwin":
        return "macos"
    return "linux"


def detect_arch(machine: str) -> Arch:
    """把 ``platform.machine()`` 收敛到两种实际产物；未知一律按 x64。"""
    normalized = (machine or "").strip().lower()
    if normalized in ("arm64", "aarch64"):
        return "arm64"
    return "x64"


def detect_windows_channel(install_dir: Path, uninstall_key_exists: Callable[[str], bool]) -> Channel:
    """判定 Windows 安装形态：安装版（有卸载器/卸载键）还是便携版。

    ``uninstall_key_exists`` 注入而非直接读注册表：读注册表是平台副作用，单测里
    用假函数即可覆盖四种组合，不必起 Windows 注册表。
    """
    if (install_dir / "unins000.exe").is_file():
        return "installer"
    if uninstall_key_exists(UNINSTALL_KEY):
        return "installer"
    return "portable"
