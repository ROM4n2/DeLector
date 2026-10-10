# -*- coding: utf-8 -*-
"""从桌面壳 `desktop.py` 的 `launch.log` 算出**真实首屏**（端到端）耗时。

为什么需要这个脚本
------------------
桌面侧此前只有 `health_200`（进程起 → `/api/health` 200 = **服务就绪**）这个**代理口径**；
"首屏可用"（页面真的渲染出来）从未测过 —— 代理口径 ≠ 首屏可用，二者不可相减
（ADR-0018 §8 `Unknown 8` / ADR-0020 §6 `Unknown 2` 记的就是这个缺口）。

`desktop.py` 现在在日志里落三枚**可独立解析**的阶段标记（各带 `_append_log` 的时间戳）：
  - `开始启动（进程级计时起点）`  —— 进程级计时起点（日志里最早的标记）；
  - `服务已就绪`                  —— uvicorn 已可服务（≈ `health_200` 的口径）；
  - `真实 UI 已加载（首屏可用）`  —— pywebview 的 `loaded` 事件（页面渲染完成）⇒ **真实首屏**。
本脚本把三点连成一张小表，给出三段耗时：起点→服务就绪、服务就绪→首屏、起点→首屏（端到端首屏）。

口径与边界
----------
- 时间戳精度 = `_append_log` 的 `%H:%M:%S`（**秒**级）；差值以秒为单位。刻意不为计时去改
  `_append_log` 的时间戳格式（避免动既有 8 段阶段日志的口径）。
- 日志是**追加**写：多次启动会留下多个 `开始启动` 标记 ⇒ 取**最后一次**启动为计时起点，
  只统计其后的 `服务已就绪` / `真实 UI 已加载`。
- 旧日志（本脚本之前产生）**没有** `loaded` 行 ⇒ 如实报"该日志不含首屏事件"，
  **绝不**拿 `health_200` 冒充首屏、也不静默给 0（退出码非零）。

退出码
------
0 = 成功算出三行；
3 = 日志存在且可解析，但**不含首屏事件**（缺 `loaded` 行，多为旧日志）；
4 = 找不到 / 读不了日志文件；
5 = 日志存在但**格式异常**（无带时间戳行 / 找不到计时起点 / 首屏前无服务就绪行）。

用法
----
::

    export PYTHONIOENCODING=utf-8
    python tools/first_screen_from_log.py
    python tools/first_screen_from_log.py --log "D:\\tmp\\launch.log"
"""

import argparse
import os
import re
import sys
from datetime import datetime
from typing import List, Mapping, NamedTuple, Optional, Sequence

LOG_FILE_NAME = "launch.log"
APP_DIR_NAME = "DeLector"

# 与 desktop.py 写入的日志消息**逐字对齐**的标记（各取稳定子串；两边漂移由 tests 钉住）：
# desktop.py 写入时句尾带「。」，这里只取核心短语 ⇒ 子串匹配对尾标点不敏感。
START_MARKER = "开始启动（进程级计时起点）"
READY_MARKER = "服务已就绪"
SCREEN_MARKER = "真实 UI 已加载（首屏可用）"

EXIT_OK = 0
EXIT_NO_FIRST_SCREEN = 3
EXIT_LOG_NOT_FOUND = 4
EXIT_BAD_FORMAT = 5

# `_append_log` 的行格式：`[YYYY-MM-DD HH:MM:SS] 消息`（时间戳秒级；容忍可选的 `.毫秒` 尾巴）。
_LINE_RE = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*(?P<msg>.*)$")


class _MarkedLine(NamedTuple):
    when: datetime
    message: str


def default_log_path(env: Mapping[str, str]) -> str:
    """默认落点 = `%LOCALAPPDATA%\\DeLector\\launch.log`（与 `desktop.resolve_log_path` 同源）。

    本脚本**只用标准库**（tools/ 在 `mypy --strict` 范围，且不应拖入 delector），故不 import
    生产的 `resolve_data_dir`，而按同一规则自行推导；两条规则的漂移由 tests 钉住（都落到
    `DeLector/launch.log`）。
    """
    local = env.get("LOCALAPPDATA", "")
    base = local if local else os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME, LOG_FILE_NAME)


def _parse_line(raw: str) -> Optional[_MarkedLine]:
    """解析一行 `[时间戳] 消息`；不符格式（含坏行）返回 None —— 坏行跳过，不崩。"""
    match = _LINE_RE.match(raw.rstrip("\r\n"))
    if match is None:
        return None
    try:
        when = datetime.strptime(match.group("ts")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return _MarkedLine(when, match.group("msg"))


def _marked_lines(text: str) -> List[_MarkedLine]:
    """把整份日志解析成带时间戳的行（坏行被丢弃，不抛）。"""
    parsed: List[_MarkedLine] = []
    for raw in text.splitlines():
        line = _parse_line(raw)
        if line is not None:
            parsed.append(line)
    return parsed


def _last_index(lines: List[_MarkedLine], marker: str) -> Optional[int]:
    """`marker` 最后一次出现的下标（日志追加写 ⇒ 取最近一次启动）。"""
    for index in range(len(lines) - 1, -1, -1):
        if marker in lines[index].message:
            return index
    return None


def _first_index_after(lines: List[_MarkedLine], marker: str, after: int) -> Optional[int]:
    """`after` 之后首次出现 `marker` 的下标；找不到返回 None。"""
    for index in range(after + 1, len(lines)):
        if marker in lines[index].message:
            return index
    return None


def _fmt_seconds(seconds: float) -> str:
    """以秒为单位、去掉多余尾零（如 `3s` / `2.5s`）。"""
    return f"{seconds:g}s"


def _fmt_stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _read_text(log_path: str) -> str:
    """读日志全文（UTF-8、坏字节替换）；IO 失败原样抛出，由调用方转成人话。"""
    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def run(log_path: str) -> int:
    """解析 `log_path` 并打印首屏小表；返回进程退出码（见模块 docstring）。"""
    if not os.path.isfile(log_path):
        print(f"找不到日志文件：{log_path}", file=sys.stderr)
        print(r"（用 --log PATH 指定；桌面壳默认落点：%LOCALAPPDATA%\DeLector\launch.log）", file=sys.stderr)
        return EXIT_LOG_NOT_FOUND
    try:
        text = _read_text(log_path)
    except OSError as exc:
        print(f"读取日志失败：{log_path}（{exc}）", file=sys.stderr)
        return EXIT_LOG_NOT_FOUND

    lines = _marked_lines(text)
    if not lines:
        print(f"日志格式异常：{log_path} 里没有可解析的 '[YYYY-MM-DD HH:MM:SS] 消息' 行。", file=sys.stderr)
        return EXIT_BAD_FORMAT

    start_index = _last_index(lines, START_MARKER)
    if start_index is None:
        print(f"日志格式异常：{log_path} 里找不到计时起点行「{START_MARKER}」。", file=sys.stderr)
        print("（该行由 desktop.py 在启动最早处写入；被截断的旧日志可能没有。）", file=sys.stderr)
        return EXIT_BAD_FORMAT

    screen_index = _first_index_after(lines, SCREEN_MARKER, start_index)
    if screen_index is None:
        print(f"该日志不含首屏事件：在计时起点之后找不到「{SCREEN_MARKER}」行（多为旧日志）。", file=sys.stderr)
        print("（不得用 health_200『服务就绪』冒充首屏；请用带 loaded 事件的新版本重跑。）", file=sys.stderr)
        return EXIT_NO_FIRST_SCREEN

    ready_index = _first_index_after(lines, READY_MARKER, start_index)
    if ready_index is None or ready_index > screen_index:
        print(f"日志格式异常：{log_path} 里首屏事件之前找不到服务就绪行「{READY_MARKER}」。", file=sys.stderr)
        return EXIT_BAD_FORMAT

    start, ready, screen = lines[start_index], lines[ready_index], lines[screen_index]
    print("=== 首屏耗时（来自 launch.log）===")
    print(f"日志文件: {log_path}")
    print(f"计时起点: {_fmt_stamp(start.when)}")
    print(f"服务就绪: {_fmt_stamp(ready.when)}")
    print(f"首屏已加载: {_fmt_stamp(screen.when)}")
    print(f"起点 → 服务就绪: {_fmt_seconds((ready.when - start.when).total_seconds())}")
    print(f"服务就绪 → 首屏已加载: {_fmt_seconds((screen.when - ready.when).total_seconds())}")
    print(f"起点 → 首屏已加载（端到端首屏）: {_fmt_seconds((screen.when - start.when).total_seconds())}")
    return EXIT_OK


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 desktop 壳的 launch.log 算出真实首屏（端到端）耗时。")
    parser.add_argument(
        "--log",
        default="",
        help=r"launch.log 路径（默认 %LOCALAPPDATA%\DeLector\launch.log）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    log_path = str(args.log) if args.log else default_log_path(os.environ)
    return run(log_path)


if __name__ == "__main__":
    raise SystemExit(main())
