# -*- coding: utf-8 -*-
"""Windows 安装拉起原语（`delector/core/update_apply.py`）：只断言命令与进程参数。"""

from pathlib import Path
from typing import Any, List, Tuple

from delector.core.update_apply import installer_command, schedule_exit, spawn_installer


def test_installer_command_is_exact() -> None:
    exe = Path("C:/tmp/Setup.exe")

    assert installer_command(exe) == [
        str(exe),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
    ]


def test_spawn_installer_uses_no_shell_and_separate_process_group() -> None:
    calls: List[Tuple[List[str], dict]] = []

    def popen(args: List[str], **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "proc"

    result = spawn_installer(Path("Setup.exe"), popen=popen)

    assert result == "proc"
    args, kwargs = calls[0]
    assert args[0] == "Setup.exe"
    assert kwargs["shell"] is False
    assert isinstance(kwargs["creationflags"], int)


def test_schedule_exit_marks_daemon_and_starts() -> None:
    class FakeTimer:
        def __init__(self, delay: float, function: Any) -> None:
            self.delay = delay
            self.function = function
            self.daemon = False
            self.started = False

        def start(self) -> None:
            self.started = True

    timer = schedule_exit(1.5, lambda: None, timer_factory=FakeTimer)

    assert timer.delay == 1.5
    assert timer.daemon is True
    assert timer.started is True
