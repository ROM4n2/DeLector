# -*- coding: utf-8 -*-
"""CI 步骤心跳包装器（默认纯旁路；可选硬截止）。

背景（2026-11-04 run 41833602180 attempt 1）：Windows Portable Smoke 的 Verify 步从
12:59:38 起挂住，job 级 30 分钟超时在 13:31:36 终止，job 结论记为 ``cancelled``，
且该 job 日志 GitHub 未保留（API 404）。**该次运行的 Verify 步没有步骤级
``timeout-minutes``**（commit 05d5c3f 的 ci.yml 可核）；10 分钟上限是事后
commit 5248611（2026-11-04 22:48 +0800）才加的——所以那一轮不是“上限未生效”，
而是“上限未写”。更麻烦的是：job 级超时给出的 ``cancelled`` 与「被后续 push
顶掉（concurrency.cancel-in-progress）」在结论上完全同形，无法区分真卡死。

因此本工具增加**可选**的 ``--deadline-seconds``：到点由包装器杀掉整棵子进程树，
并以 **124** 退出。这样“真卡死”变成可识别的 ``failure``（步骤非零退出），与
“被顶掉的 cancelled”在结论上分开。

纪律（本工具 MUST 遵守）
------------------------
- **默认纯旁路**：不传 ``--deadline-seconds`` 时只观察、不干预。子进程退出码原样
  返回；不 try/except 吞掉子进程失败、不改任何成败判定。
- **截止是判据，不是静默重试**：仅在显式传入截止时启用；到点打印 ``::error::``、
  杀整棵进程树（Windows ``taskkill /T /F``；POSIX 新会话 + ``killpg``），返回 124。
- **心跳自身不能成为失败源**：心跳线程里任何异常（含写日志失败）都被就地吞掉并
  静默停止；线程起不来也照常跑子进程。
- **不新增依赖**：只用标准库（subprocess / threading / argparse / time / datetime）。
- 阶段切换（开始/结束）各打一条；运行中每 ``--interval`` 秒打一条。

用法::

    python tools/ci_heartbeat.py --stage build -- python package_windows.py
    python tools/ci_heartbeat.py --stage verify --deadline-seconds 480 \
        -- python tools/verify_windows_portable.py --expect-commit <sha>
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import List, Optional, Sequence

DEFAULT_INTERVAL_SEC = 60.0

#: 到点杀进程树后等待其退出的上限（秒）；超时也照常以 124 返回，包装器自身 MUST 退出。
KILL_GRACE_SECONDS = 10.0

#: 截止触发的退出码（与 GNU timeout 一致），与子进程自身的退出码区分。
DEADLINE_EXIT_CODE = 124


def _now_hms() -> str:
    """当前时间 HH:MM:SS（runner 本地时区；GitHub runner 为 UTC）。"""
    return datetime.now().strftime("%H:%M:%S")


def _emit(line: str) -> None:
    """写一行心跳日志；**任何异常都不得外抛**（写日志失败不应让 job 红）。"""
    try:
        print(line, flush=True)
    except Exception:  # silent-ok: 心跳是纯旁路，写日志失败不影响子进程退出码与步骤成败
        pass


def _heartbeat_loop(stage: str, interval: float, start: float, stop: threading.Event) -> None:
    """后台线程：每 ``interval`` 秒打印一条 "still running"。

    ``stop.wait(interval)`` 在收到 stop 时立即返回 ⇒ 子进程结束到线程退出的延迟
    约为 0，不会把心跳延迟算进步骤耗时。线程内所有异常就地吞掉。
    """
    try:
        while not stop.wait(interval):
            elapsed = int(time.monotonic() - start)
            _emit(f"[heartbeat] {_now_hms()} {stage} still running (elapsed {elapsed}s, stage={stage})")
    except Exception:  # silent-ok: 心跳线程是纯旁路，任何异常只停心跳、不改子进程结果
        return


def _strip_separator(command: List[str]) -> List[str]:
    """去掉 argparse.REMAINDER 捕获到的首个 ``--``。"""
    if command and command[0] == "--":
        return command[1:]
    return command


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """杀掉子进程及其整棵进程树；失败只记录，不抛异常。"""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=KILL_GRACE_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            _emit(f"::warning::ci_heartbeat taskkill 失败：{type(exc).__name__}: {exc}")
    else:
        # os.killpg / getpgid / SIGKILL 是 POSIX 专有符号；用 getattr 取，避免在
        # Windows（本地 mypy 也要过）上被类型检查判成缺失属性。
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        sigkill = getattr(signal, "SIGKILL", None)
        if killpg is None or getpgid is None or sigkill is None:
            _emit("::warning::ci_heartbeat 当前平台缺少 killpg/getpgid/SIGKILL，退化为单进程 kill")
        else:
            try:
                killpg(getpgid(proc.pid), sigkill)
            except (ProcessLookupError, OSError) as exc:
                _emit(f"::warning::ci_heartbeat killpg 失败：{type(exc).__name__}: {exc}")
    try:
        proc.kill()
    except OSError:
        # 进程树已被 taskkill/killpg 收掉时 kill 可能报错；此处只做兜底。
        pass


def _wait_with_deadline(proc: subprocess.Popen[bytes], deadline_seconds: float) -> int:
    """等待子进程；超过硬截止则杀树并以 124 返回。"""
    deadline = time.monotonic() + deadline_seconds
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _emit(
                f"::error::ci_heartbeat deadline exceeded ({deadline_seconds:g}s); "
                f"killing process tree pid={proc.pid}"
            )
            _kill_process_tree(proc)
            try:
                proc.wait(timeout=KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _emit("::error::ci_heartbeat process tree still alive after kill; exiting 124")
            return DEADLINE_EXIT_CODE
        time.sleep(min(1.0, remaining))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行子命令并旁路心跳；默认原样返回子进程退出码，传截止时到点返回 124。"""
    parser = argparse.ArgumentParser(
        description=(
            "Run a CI command with a pure-sideband heartbeat. "
            "Without --deadline-seconds the exit code is passed through unchanged."
        ),
    )
    parser.add_argument("--stage", required=True, help="阶段名（写进每条心跳，例如 build / verify）")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help=f"心跳间隔秒数（默认 {DEFAULT_INTERVAL_SEC:g}）",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=None,
        help=(
            "可选硬截止（秒）：到点杀掉整棵子进程树并以 124 退出，"
            "使卡死变成可识别的 failure 而不是 job 级 cancelled。不传则纯旁路。"
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="`--` 之后是要执行的命令")
    args = parser.parse_args(argv)

    if args.deadline_seconds is not None and args.deadline_seconds <= 0:
        parser.error("--deadline-seconds 必须为正数")

    command = _strip_separator(list(args.command))
    if not command:
        parser.error("缺少要执行的命令：用法 `-- <command> [args...]`")

    start = time.monotonic()
    _emit(f"[heartbeat] {_now_hms()} stage={args.stage} started (elapsed 0s)")

    try:
        if args.deadline_seconds is not None and os.name != "nt":
            # 独立会话，截止时才能用 killpg 收掉整棵进程树。
            proc = subprocess.Popen(command, start_new_session=True)
        else:
            proc = subprocess.Popen(command)  # 继承 stdout/stderr，输出照常进步骤日志
    except OSError as exc:
        _emit(f"::error::ci_heartbeat 无法启动命令 {command!r}: {type(exc).__name__}: {exc}")
        return 127

    stop = threading.Event()
    thread: Optional[threading.Thread] = None
    try:
        thread = threading.Thread(
            target=_heartbeat_loop,
            args=(args.stage, args.interval, start, stop),
            name=f"ci-heartbeat-{args.stage}",
            daemon=True,
        )
        thread.start()
    except Exception:
        # 心跳线程起不来也必须继续跑子进程（旁路不是前置条件）。
        thread = None

    if args.deadline_seconds is None:
        rc = proc.wait()
    else:
        rc = _wait_with_deadline(proc, args.deadline_seconds)
    stop.set()
    if thread is not None:
        try:
            thread.join(timeout=1.0)
        except Exception:  # silent-ok: 心跳是纯旁路，join 失败不影响子进程退出码与步骤成败
            pass

    elapsed = int(time.monotonic() - start)
    _emit(f"[heartbeat] {_now_hms()} stage={args.stage} finished (elapsed {elapsed}s, rc={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
