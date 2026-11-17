# -*- coding: utf-8 -*-
"""应用内更新的"本机动作"端点：下载、进度、取消、安装（ADR-0034 / M2）。

为什么独立于 ``delector/routes/update.py``：
- 那边的结构守卫禁止出现版本号字面量与 ``_require_localhost``（只读端点）；
- 这里会写临时文件、拉起安装器、结束进程，MUST 全部挂本机闸。

端点只接受空请求体：资产 URL、大小、校验和都由后端自己解析（``/artifact`` 同源
逻辑），客户端传什么都不影响下载目标，避免 SSRF 与"客户端指定替换包"。
"""

import os
import platform as platform_module
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from delector.core import update_download
from delector.core.database import _require_localhost
from delector.core.update_apply import schedule_exit, spawn_installer
from delector.core.update_host import Channel, detect_arch, detect_platform, detect_windows_channel
from delector.core.update_linux import apply_switch, extract_payload, managed_root, plan_switch
from delector.core.update_portable import (
    build_apply_script,
    is_writable_root,
    powershell_command,
    prepare_payload,
)
from delector.core.update_session import UpdateSession
from delector.core.utils import is_android
from delector.routes.update import check_artifact

__all__ = ["api_update_cancel", "api_update_download", "api_update_install", "api_update_status", "router"]

router = APIRouter(prefix="/api/update", tags=["update"])

_SESSION_LOCK = threading.Lock()
_SESSION: Optional[UpdateSession] = None

# 安装器启动后等多久再退出应用：够 Inno 建起 Restart Manager 会话，又不至于让用户
# 盯着"正在安装"太久。真实安装时序需在 Windows 机器上验证（见计划 §8）。
_EXIT_DELAY_SECONDS = 1.5


def _download_dir() -> Path:
    """下载落盘目录：Android 用应用私有 files/updates，Windows 用 %TEMP%，其余 XDG cache。

    都不碰用户数据目录；Android 的落点是 Java 侧 PackageInstaller 能直接读取的私有路径。
    """
    if is_android():
        base = os.environ.get("DELECTOR_DATA_DIR") or str(Path.home())
        return Path(base) / "updates"
    if sys.platform.startswith("win"):
        base = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "DeLector-update"


def _install_dir() -> Path:
    """当前程序目录：冻结后是 exe 所在目录，开发态回落到仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _registry_key_exists(key: str) -> bool:
    """只读注册表键是否存在；非 Windows 平台一律 False。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            return True
    except OSError:
        return False


def _fetch_checksum(url: str) -> str:
    """取 ``.sha256`` 资产正文（小文件）；失败向上抛，由会话归为失败态。"""
    resp = httpx.get(url, timeout=10.0, headers={"User-Agent": "DeLector-Update"})
    resp.raise_for_status()
    return resp.text


def _build_session() -> UpdateSession:
    return UpdateSession(
        artifact_resolver=lambda platform, channel, arch: check_artifact(
            platform=platform, channel=channel, arch=arch
        ),
        checksum_fetcher=_fetch_checksum,
        downloader=lambda *args, **kwargs: update_download.download(
            *args, transport=update_download.httpx_transport, **kwargs
        ),
        target_dir=_download_dir(),
    )


def _get_session() -> UpdateSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = _build_session()
        return _SESSION


def _exit_app() -> None:
    """结束本进程：安装器需要独占程序目录。测试会替换它，绝不在测试里退出。"""
    os._exit(0)


def _start_background(target: Any) -> threading.Thread:
    """启动下载流水线线程；测试替换本函数即可同步观察，不必真起线程。"""
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


class _UnsupportedInstall(Exception):
    """该平台/形态没有可用的替换策略；路由转 400，不假装成功。"""


def _spawn_powershell(script: Path) -> None:
    """分离启动 helper 脚本：应用退出后仍由它完成目录交换。"""
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(powershell_command(script), shell=False, close_fds=True, creationflags=flags)


def _install_windows_portable(archive: Path, version: str) -> None:
    root = _install_dir()
    if not is_writable_root(root):
        raise _UnsupportedInstall("install_dir_not_writable")
    work = _download_dir()
    source = prepare_payload(archive, work / ("staging-" + version))
    backup = root.with_name(root.name + ".bak-" + version)
    script = work / "apply-portable.ps1"
    script.write_text(
        build_apply_script(
            pid=os.getpid(),
            source_dir=source,
            target_dir=root,
            restart_exe=root / "DeLector.exe",
            backup_dir=backup,
            log_path=work / "update-error.log",
        ),
        encoding="utf-8",
    )
    _spawn_powershell(script)


def _install_linux(archive: Path, version: str) -> None:
    plan = plan_switch(managed_root(), Path(sys.executable), version)
    if plan is None:
        # 非受管布局（用户解压到桌面）：拒绝自替换，回退 Release 页。
        raise _UnsupportedInstall("not_managed_layout")
    inner = extract_payload(archive, plan.version_dir)
    if inner != plan.version_dir:
        for child in list(inner.iterdir()):
            shutil.move(str(child), str(plan.version_dir / child.name))
        inner.rmdir()
    apply_switch(plan)
    subprocess.Popen([str(plan.link_path)], start_new_session=True, close_fds=True)


def _dispatch_install(snapshot: Dict[str, Any]) -> None:
    """按快照里的平台/形态分派；未知组合一律显式拒绝。"""
    asset = Path(str(snapshot.get("asset_path")))
    target = snapshot.get("platform")
    channel = snapshot.get("channel")

    if target == "windows" and channel == "installer":
        spawn_installer(asset)
        return

    version = snapshot.get("version")
    if not isinstance(version, str) or not version:
        raise _UnsupportedInstall("missing_version")
    if target == "windows" and channel == "portable":
        _install_windows_portable(asset, version)
        return
    if target == "linux":
        _install_linux(asset, version)
        return
    raise _UnsupportedInstall("unsupported_platform")


def _host_target() -> tuple[str, Channel, str]:
    """判定本机目标。macOS 不支持应用内更新（ADR-0034 D6）。

    Android **允许下载**（Python 下载器复用），但安装由 Java 桥完成，``/install``
    会明确拒绝；这样 APK 的下载与校验仍然走同一套可单测的 Python 逻辑。
    """
    target = detect_platform(android=is_android(), sys_platform=sys.platform)
    if target == "macos":
        raise HTTPException(status_code=400, detail="unsupported")
    if target == "android":
        return "android", "portable", "arm64"
    channel: Channel = "portable"
    if target == "windows":
        channel = detect_windows_channel(_install_dir(), _registry_key_exists)
    return target, channel, detect_arch(platform_module.machine())


@router.post("/download")
def api_update_download(request: Request) -> Dict[str, Any]:
    """开始下载（本机专用）。客户端不传 URL/哈希，目标由后端自行解析。"""
    _require_localhost(request)
    target, channel, arch = _host_target()
    session = _get_session()
    if not session.begin(target, channel, arch):
        raise HTTPException(status_code=409, detail="busy")
    _start_background(session.run)
    return session.snapshot()


@router.get("/download/status")
def api_update_status(request: Request) -> Dict[str, Any]:
    """下载会话快照（本机专用；含本地落盘路径，不对外暴露）。"""
    _require_localhost(request)
    return _get_session().snapshot()


@router.post("/download/cancel")
def api_update_cancel(request: Request) -> Dict[str, Any]:
    """取消下载并清理 ``.part``（本机专用）。"""
    _require_localhost(request)
    return _get_session().cancel()


@router.post("/install")
def api_update_install(request: Request) -> Dict[str, Any]:
    """按平台拉起安装/替换并安排退出（本机专用）。

    - Windows 安装版：Inno 静默安装；
    - Windows 便携版：解压到临时目录，由 helper 等退出后换目录；
    - Linux：解压到版本目录并原子切换符号链接；
    - Android：下载已完成，安装走 Java 桥，这里明确 400。
    """
    _require_localhost(request)
    session = _get_session()
    snapshot = session.snapshot()
    if snapshot["state"] != "ready":
        raise HTTPException(status_code=409, detail="not_ready")
    try:
        _dispatch_install(snapshot)
    except _UnsupportedInstall as exc:
        raise HTTPException(status_code=400, detail="unsupported") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="install_failed") from exc
    if not session.mark_installing():
        raise HTTPException(status_code=409, detail="not_ready")
    schedule_exit(_EXIT_DELAY_SECONDS, _exit_app)
    return session.snapshot()
