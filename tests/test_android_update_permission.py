# -*- coding: utf-8 -*-
"""Android 应用内更新的权限面与桥接静态守卫（ADR-0034 D3 / M3）。

Java 运行时行为（PackageInstaller 会话、签名比对、OEM 额外确认）本机不可验证，
只能由真机确认；这里钉住「权限面最小化」与「路径/桥接不可悄悄扩大」这两类**可静态判定**
的边界，防止后续改动把静默安装或额外权限带进来。
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
MAIN_ACTIVITY = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
APK_INSTALLER = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "ApkInstaller.java"
RESULT_RECEIVER = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "InstallResultReceiver.java"

ANDROID = "{http://schemas.android.com/apk/res/android}"


def _permissions() -> List[str]:
    root = ET.parse(MANIFEST).getroot()
    return [node.get(ANDROID + "name") or "" for node in root.findall("uses-permission")]


def test_request_install_packages_declared_exactly_once() -> None:
    names = _permissions()

    assert names.count("android.permission.REQUEST_INSTALL_PACKAGES") == 1


def test_privileged_install_permission_is_not_declared() -> None:
    """`INSTALL_PACKAGES` 是 signature|privileged，第三方应用声明也拿不到，禁止出现在清单里。"""
    assert "android.permission.INSTALL_PACKAGES" not in _permissions()


def test_no_download_manager_or_foreground_service_permissions() -> None:
    names = set(_permissions())

    assert "android.permission.FOREGROUND_SERVICE" not in names
    assert "android.permission.DOWNLOAD_WITHOUT_NOTIFICATION" not in names


def test_install_receiver_is_private() -> None:
    root = ET.parse(MANIFEST).getroot()
    receivers = root.findall(".//receiver")

    assert len(receivers) == 1
    assert receivers[0].get(ANDROID + "name") == ".InstallResultReceiver"
    assert receivers[0].get(ANDROID + "exported") == "false"


def test_javascript_bridge_is_registered() -> None:
    source = MAIN_ACTIVITY.read_text(encoding="utf-8")

    assert '"DeLectorUpdate"' in source
    assert "ApkInstaller.install" in source


def test_installer_restricts_apk_to_private_updates_dir() -> None:
    source = APK_INSTALLER.read_text(encoding="utf-8")

    assert 'new File(activity.getFilesDir(), UPDATES_DIR)' in source
    assert "getCanonicalFile" in source
    assert "getPath().startsWith(prefix)" in source


def test_installer_never_calls_privileged_install_api() -> None:
    """静默安装的入口是隐藏/特权 API；第三方应用只有 PackageInstaller 会话这一条路。"""
    source = APK_INSTALLER.read_text(encoding="utf-8")

    assert "installPackage(" not in source
    assert "PackageInstaller" in source


def test_pending_user_action_is_propagated_to_system_ui() -> None:
    """不拉起系统确认 Activity，会话会永远悬着；两个端点都必须处理这个状态。"""
    installer = APK_INSTALLER.read_text(encoding="utf-8")
    receiver = RESULT_RECEIVER.read_text(encoding="utf-8")

    assert "PENDING_USER_ACTION" in installer
    assert "STATUS_PENDING_USER_ACTION" in receiver
    assert "EXTRA_INTENT" in receiver
