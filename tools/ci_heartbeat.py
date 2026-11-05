# -*- coding: utf-8 -*-
"""CI 步骤心跳包装器（纯旁路）。

背景：2026-11-04 run 41833602180 的 Windows Portable Smoke 卡在 Verify 步 30 分钟被
取消，且该 job 日志 GitHub 未保留（API 404），根因至今未定位。步骤级 timeout 能把
"静默卡死 30 分钟"变成"快速失败"，但**被取消的 job 日志可能整份丢失**——周期心跳是
唯一还能留在日志里的相位证据。

纪律（本工具 MUST 遵守）：
- **纯旁路**：只观察、不干预。子进程退出码原样返回；不设超时、不 try/except 吞掉
  子进程失败、不改任何成败判定。
- **心跳自身不能成为失败源**：心跳线程里任何异常（含写日志失败）都被就地吞掉并
  静默停止；线程起不来也照常跑子进程。
- **不新增依赖**：只用标准库（subprocess / threading / argparse / time / datetime）。
- 阶段切换（开始/结束）各打一条；运行中每 ``--interval`` 秒打一条。

用法::

    python tools/ci_heartbeat.py --stage build -- python package_windows.py
"""

import argparse
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import List, Optional, Sequence

DEFAULT_INTERVAL_SEC = 60.0


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行子命令并旁路心跳；返回子进程的退出码（不做任何改写）。"""
    parser = argparse.ArgumentParser(
        description="Run a CI command with a pure-sideband periodic heartbeat (no timeout, no exit-code rewrite).",
    )
    parser.add_argument("--stage", required=True, help="阶段名（写进每条心跳，例如 build / verify）")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help=f"心跳间隔秒数（默认 {DEFAULT_INTERVAL_SEC:g}）",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="`--` 之后是要执行的命令")
    args = parser.parse_args(argv)

    command = _strip_separator(list(args.command))
    if not command:
        parser.error("缺少要执行的命令：用法 `-- <command> [args...]`")

    start = time.monotonic()
    _emit(f"[heartbeat] {_now_hms()} stage={args.stage} started (elapsed 0s)")

    try:
        proc = subprocess.Popen(command)  # 继承 stdout/stderr，子进程输出照常进步骤日志
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

    rc = proc.wait()
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
