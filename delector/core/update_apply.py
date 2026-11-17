# -*- coding: utf-8 -*-
"""Windows 安装版的"拉起安装器"原语（纯命令构造 + 可注入进程启动）。

为什么应用不能自己覆盖自己：运行中的 ``DeLector.exe`` 与已加载 DLL 被 Windows 文件
锁占用。这里把"交给 Inno 安装器"的动作压到最小：构造静默安装命令、以分离进程启动、
然后由应用延迟退出，让安装器拿到文件锁。
"""

import subprocess
import threading
from pathlib import Path
from typing import Callable, List

__all__ = ["installer_command", "schedule_exit", "spawn_installer"]

# 与 CI 已验证过的静默参数同口径（build-release.yml:185）。额外 ``/CLOSEAPPLICATIONS``
# 让安装器通过 Restart Manager 关闭仍持有文件的进程，避免"装到一半被占用"。
_INSTALLER_ARGS = [
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
]


def installer_command(exe: Path) -> List[str]:
    """安装器命令行；``shell=False`` 由调用方保证，参数里不拼接任何用户输入。"""
    return [str(exe), *_INSTALLER_ARGS]


def spawn_installer(exe: Path, *, popen: Callable[..., object] = subprocess.Popen) -> object:
    """以分离进程启动安装器并立即返回。

    分离进程组的目的：应用退出时不把安装器一起带走（否则安装会被中断）。
    """
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return popen(installer_command(exe), shell=False, close_fds=True, creationflags=flags)


def schedule_exit(
    delay_s: float,
    exit_fn: Callable[[], None],
    *,
    timer_factory: Callable[..., threading.Timer] = threading.Timer,
) -> threading.Timer:
    """延迟退出：给安装器一点时间拿到文件句柄，再结束本进程。"""
    timer = timer_factory(delay_s, exit_fn)
    timer.daemon = True
    timer.start()
    return timer
