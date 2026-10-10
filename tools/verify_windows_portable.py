#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Windows 便携产物验收闸：完整性 + **真启一次**（ADR-0021 替代投资#1）。

为什么要有这个脚本
==================
`build-release.yml` 此前对产物**零验证**：pytest → package_windows.py → 压缩 → 上传，
**从不真跑一次产物**。用户真实踩过的坑正落在这段盲区里：

- 双击 exe **没窗口 / 进程不退出**（P0，根因是 GUI 时序死锁）；
- **跑错构建**（工作区停在陈旧 master，产物命名误导，用户以为拿到新包其实是旧包）；
- 产物缺 `WebView2Loader.dll` ⇒ 解压白屏（打包脚本已加验包闸，但**从没在真产物上跑过**）。

三面镜评审里两个席位独立得出同一结论：**"在 CI 真启一次产物"是唯一能在作者双击之前
抓住这类问题的闸**。本脚本就是那道闸：可本地跑、可 CI 跑，**只用标准库**。

它验什么（两层）
================
(a) **完整性**：产物目录定位 / `.build-info.json` 四键齐全 + commit 抗陈旧 / 无 `.env` /
    必需 WebView2 DLL / `_internal/webview` 与 `_internal/pythonnet` 存在。
(b) **真启一次**（本闸核心）：以 ``DeLector.exe --server-only`` 起子进程，轮询
    ``http://127.0.0.1:8000/api/health`` 直到 **200 且 ``status=="ok"`` 且 ``app=="delector"``**
    （**身份校验**，不是"端口能连上"）；再终止它，断言**进程消失 + 端口释放 + 无孤儿**。

⚠️ 覆盖边界（**必读：别误以为它覆盖了窗口形态**）
================================================
CI runner 无桌面会话，GUI 路径（pywebview / pystray）在无头环境**不能作为阻塞判据**，
故本闸**只用 ``--server-only``**：它验的是"真产物里的服务能否起来并干净退出"。
**窗口形态（双击出不出窗口 / 进程退不退）不在本闸覆盖范围内** —— 那由本机人工双击 +
``scratch/`` 复现脚本覆盖。把这条写在这里，是为了不让后人误以为"CI 绿了 ⇒ 双击没问题"。

为什么独立实现、不 import 打包脚本
==================================
`package_windows.py` 里有 `verify_webview2_payload` / `assert_no_env_in_payload` /
`current_commit_short_sha`，判据口径可复用；但本脚本**刻意不 import 它**：

1. 验收脚本要能对**冻结产物 / 干净 CI runner**独立跑，而 import 构建脚本会顺带拉入
   `delector.core.version` 等构建侧依赖，把"验收"与"构建"耦合成一体；
2. 更关键的纪律 —— 验收闸**不能与构建闸共用同一份代码**：否则构建脚本里那个检查若本身
   有 bug（例如只扫顶层目录），"验收"会跟着一起错判，等于没验。这里**独立复刻判据**
   （锚定 `.dll` 后缀、递归扫描等），让两道闸互为独立证据。

终止策略为什么这样选（**实测口径**，见 `terminate_process` 与 `DEFAULT_TERMINATE_MODE`）
=====================================================================================
本机实测两种口径（``--terminate-mode``）：`terminate`（TerminateProcess，硬杀）与
`graceful`（CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT，期望走 uvicorn 优雅退出）。
真实产物上两种口径**都拿不到 exit 0**：`graceful` → ``3221225786``（= ``0xC000013A``，系统级
STATUS_CONTROL_C_EXIT，即被控制台控制事件杀死、并没有走成优雅路径），`terminate` → ``1``；
两者的退出耗时都是 0.0s、端口都在 2.0s 内释放、都无孤儿。
（2026-10-10 真产物 `dist/DeLector-v5.16.0-Windows-x64-Portable` 两次复测原始值：
 ``--terminate-mode terminate`` → exit_code=1；``--terminate-mode graceful`` → exit_code=3221225786。
 两次均脚本退出码 0 / 进程退出耗时 0.0s / 端口 8000 于 2.0s 内释放 / 无孤儿 —— 与上表一致，
 故默认仍取 terminate。）

据此**两点定夺**：
1. 本闸**不断言 exit code** —— 断它等于把闸绑死在一个与"是否干净退出"无关的系统细节上；
   只断言真正在乎的**实际保证**：**进程结束 + 端口释放 + 无孤儿**。
2. 默认取**确定性更高**的 ``terminate``：``graceful`` 依赖"父子共享控制台"，CI / 重定向下
   CTRL_BREAK 可能静默不达、要等满 ``PROCESS_END_TIMEOUT_S`` 才升级硬杀，反而更慢更飘。


GBK 自保
========
Windows 控制台是 GBK，本脚本的 print 含中文 ⇒ 必须把 stdout/stderr 重配成 utf-8，
否则抛 ``UnicodeEncodeError``。**不依赖环境变量**（CI 的 PYTHONIOENCODING 也可能没传到）。

用法
====
::

    export PYTHONIOENCODING=utf-8
    python tools/verify_windows_portable.py --artifact dist/DeLector-v5.16.0-Windows-x64-Portable
    python tools/verify_windows_portable.py --expect-commit 2625ee3   # CI：与 GITHUB_SHA 短 sha 对齐
    python tools/verify_windows_portable.py --terminate-mode terminate # 终止策略实测对比用

退出码：0 = 全部通过；非零 = 任一步失败（并在输出里给明"哪一步 / 期望什么 / 实际什么"）。
"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple

# ── 产物完整性判据 ────────────────────────────────────────────────────────────
BUILD_INFO_FILENAME = ".build-info.json"
REQUIRED_BUILD_INFO_KEYS: Tuple[str, ...] = ("commit", "built_at", "app_version", "entry")

# WebView2 运行时 DLL：漏收 ⇒ 解压白屏。判据与 package_windows.py 同口径（**锚定 .dll
# 后缀**，防同名 .xml/.pdb 假绿），但独立实现（见模块 docstring 的取舍说明）。
REQUIRED_DLL_NEEDLES: Tuple[str, ...] = ("WebView2Loader.dll", "Microsoft.Web.WebView2")
# 桌面壳的两大运行时目录：缺 webview ⇒ 无桌面窗口；缺 pythonnet ⇒ WebView2 后端(clr)不可用。
REQUIRED_INTERNAL_DIRS: Tuple[str, ...] = ("webview", "pythonnet")

ENV_FILE_SUFFIX = ".env"
ARTIFACT_GLOB = "DeLector-*-Windows-x64-Portable"

# git 短 sha 的官方最短长度：commit 前缀比对时的可信下限（更短的前缀会撞出巧合误判）。
MIN_COMMIT_LEN = 7

# ── 真启 / 健康探针参数 ───────────────────────────────────────────────────────
EXE_NAME = "DeLector.exe"
SERVER_ONLY_FLAG = "--server-only"

# `--server-only` 复用 start.py：该路径固定绑 8000（不接受 --port），故此处端口是真相源。
SERVER_PORT = 8000
HEALTH_URL = f"http://127.0.0.1:{SERVER_PORT}/api/health"

# 身份锚点：与 delector/routes/main.py 的 /api/health 契约一致（app 字段）。
IDENTITY_FIELD = "app"
IDENTITY_VALUE = "delector"
READY_STATUS = "ok"

HEALTH_DEADLINE_S = 120.0  # 起服总截止：ADR-0018 §7.3 记 health_200 ≈ 2.6s，留足冷机余量
HEALTH_PROBE_TIMEOUT_S = 3.0  # 单次探测超时
BACKOFF_START_S = 0.2
BACKOFF_MAX_S = 2.0
BACKOFF_MAX_FACTOR = 2.0

PROCESS_END_TIMEOUT_S = 10.0  # 终止后进程须在此内结束
PORT_RELEASE_TIMEOUT_S = 10.0  # 端口须在此内释放
PORT_POLL_INTERVAL_S = 0.1
KILL_TIMEOUT_S = 15.0

# 轮询三态：交由 `wait_until_ready` 的 while 条件判断，避免在循环体内再套 if（保持浅缩进）。
_PROBE_READY = "ready"
_PROBE_PENDING = "pending"
_PROBE_DEAD = "dead"

# 终止策略默认值：本机实测（2026-10-10，真实产物 dist/DeLector-v5.16.0-…）两种口径都是
#   graceful（CTRL_BREAK_EVENT）→ exit_code=0xC000013A、退出 0.0s、端口 2.0s 释放、无孤儿
#   terminate（TerminateProcess）→ exit_code=1、退出 0.0s、端口 2.0s 释放、无孤儿
# 两者都**拿不到 exit 0**，且 graceful 依赖"父子共享控制台"（CI/重定向下 CTRL_BREAK 可能
# 静默不达、要等满 PROCESS_END_TIMEOUT_S 才升级硬杀）。故取**确定性更高、无环境依赖**的
# terminate 作默认；graceful 保留为 --terminate-mode 供对比 / 需要优雅信号时手工指定。
DEFAULT_TERMINATE_MODE = "terminate"

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Windows 专有符号：Linux 上也要能 import（单测 / mypy 在 ubuntu 跑），故 getattr 兜底。
_CREATE_NEW_PROCESS_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_CTRL_BREAK_EVENT: Optional[int] = getattr(signal, "CTRL_BREAK_EVENT", None)
# SIGKILL 在 Windows 上不存在（typeshed win32 无此常量）⇒ getattr 兜底，避免撞 mypy attr-defined。
_SIGKILL: int = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 15))


class VerifyError(Exception):
    """验收失败的可读原因（哪一步 / 期望什么 / 实际什么）。"""


class StopResult(NamedTuple):
    """终止结果：进程是否结束、耗时、退出码、是否升级为硬杀。"""

    ended: bool
    elapsed_s: float
    exit_code: Optional[int]
    escalated: bool


# ── 输出（人读报告 + GBK 自保）───────────────────────────────────────────────
class Report:
    """逐条记 PASS/FAIL/SKIP 并**即时打印**（CI 日志可实时看进度）；最后以退出码表达结果。"""

    def __init__(self) -> None:
        self.failed = False

    def ok(self, label: str, detail: str = "") -> None:
        _emit("PASS", label, detail)

    def skip(self, label: str, detail: str = "") -> None:
        _emit("SKIP", label, detail)

    def fail(self, label: str, detail: str = "") -> None:
        self.failed = True
        _emit("FAIL", label, detail)


def _emit(status: str, label: str, detail: str) -> None:
    suffix = f"：{detail}" if detail else ""
    print(f"[{status}] {label}{suffix}", flush=True)


def _reconfigure_streams() -> None:
    """把 stdout/stderr 重配成 utf-8，避免 GBK 控制台抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        _reconfigure_one(stream)


def _reconfigure_one(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        pass


# ── (a) 完整性：定位产物 + 逐项判据（纯逻辑，可单测）─────────────────────────
def locate_artifact(dist_dir: Path, override: str = "") -> Path:
    """定位 Windows 产物目录：override 优先；否则在 dist_dir 下 glob 唯一候选。

    多候选 / 无候选都抛 VerifyError（**不猜**）：猜错产物目录 = 验收了错的东西，
    比直接失败更危险（与"跑错包"同类）。
    """
    if override:
        path = Path(override)
        if not path.is_dir():
            raise VerifyError(f"指定的产物目录不存在：{path}")
        return path
    matches = sorted(p for p in dist_dir.glob(ARTIFACT_GLOB) if p.is_dir())
    if not matches:
        raise VerifyError(f"在 {dist_dir} 下找不到产物目录（期望匹配 {ARTIFACT_GLOB}）")
    if len(matches) > 1:
        raise VerifyError(f"找到多个产物目录，需用 --artifact 明确指定：{[str(p) for p in matches]}")
    return matches[0]


def read_build_info(artifact: Path) -> Dict[str, Any]:
    """读产物根的 `.build-info.json`；缺失 / 非 JSON 对象一律抛 VerifyError。"""
    path = artifact / BUILD_INFO_FILENAME
    if not path.is_file():
        raise VerifyError(f"缺少构建指纹 {BUILD_INFO_FILENAME}（期望文件 {path}）")
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerifyError(f"{BUILD_INFO_FILENAME} 不是合法 JSON：{exc!r}") from exc
    if not isinstance(data, dict):
        raise VerifyError(f"{BUILD_INFO_FILENAME} 顶层不是 JSON 对象（实际 {type(data).__name__}）")
    return data


def missing_build_info_keys(info: Mapping[str, Any]) -> List[str]:
    """返回缺失或为空的指纹键（空 = 四键齐全且非空）。"""
    return [key for key in REQUIRED_BUILD_INFO_KEYS if not info.get(key)]


def commit_mismatch(actual_commit: str, expect_commit: str) -> Optional[str]:
    """commit 指纹是否与期望**不一致**：一致 / 未传期望返回 None，否则返回中文说明。

    比较口径：两者都是 git sha 前缀 ⇒ 相等，或较短者长度 ≥ MIN_COMMIT_LEN 且是较长者的
    前缀，都算一致。这样 CI 无论传短 sha（`git rev-parse --short HEAD`，与打包脚本同源）
    还是完整 `GITHUB_SHA` 都能对上；而 <7 位的巧合前缀（如 "abc" vs "abcd"）仍判不一致。
    这正是"工作区停在旧 master、产物命名误导"那次的防复发闸。
    """
    expected = expect_commit.strip().lower()
    if not expected:
        return None
    actual = actual_commit.strip().lower()
    if actual == expected:
        return None
    shorter, longer = sorted((actual, expected), key=len)
    if len(shorter) >= MIN_COMMIT_LEN and longer.startswith(shorter):
        return None
    return (
        f"产物 commit={actual or '<空>'} 与期望 {expected} 不一致："
        "产物可能是**陈旧构建**或跑错了包（抗陈旧闸，防「以为拿到新包其实是旧包」复发）"
    )


def find_env_files(artifact: Path) -> List[str]:
    """递归找 `.env` / `*.env`（返回相对产物根的路径，空 = 通过）。

    匹配 `endswith(".env")` 同时覆盖裸 `.env` 与 `prod.env` 这类变体；大小写不敏感
    （Windows 文件名大小写不固定）。
    """
    hits = [
        str(p.relative_to(artifact))
        for p in artifact.rglob("*")
        if p.is_file() and p.name.lower().endswith(ENV_FILE_SUFFIX)
    ]
    return sorted(hits)


def missing_dlls(artifact: Path) -> List[str]:
    """返回缺失的必需 DLL needle（空 = 通过）。**锚定 `.dll` 后缀**防同名 .xml/.pdb 假绿。"""
    names = [p.name.lower() for p in artifact.rglob("*") if p.is_file()]
    return [
        needle
        for needle in REQUIRED_DLL_NEEDLES
        if not any(name.endswith(".dll") and needle.lower() in name for name in names)
    ]


def missing_internal_dirs(artifact: Path) -> List[str]:
    """返回缺失的 `_internal/<name>` 目录名（空 = 通过）。"""
    internal = artifact / "_internal"
    return [name for name in REQUIRED_INTERNAL_DIRS if not (internal / name).is_dir()]


def health_is_ready(status_code: int, payload: Any) -> bool:
    """健康响应是否算"就绪"：**200 且 status=="ok" 且 app=="delector"**。

    身份校验（app）是硬要求，不是"端口能连上"：端口上可能是别的程序，也可能是旧进程
    —— 只判"能连上"会把它们全放行。身份不对（`app != "delector"`）必须判否。
    """
    if status_code != 200 or not isinstance(payload, dict):
        return False
    return payload.get(IDENTITY_FIELD) == IDENTITY_VALUE and payload.get("status") == READY_STATUS


# ── (b) 真启：启动 / 轮询 / 终止 / 端口 / 孤儿 ────────────────────────────────
def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """端口上是否仍有监听者（与 start.py 的 is_port_in_use 同口径：connect 得通即占用）。

    为什么用 connect 而非 bind：这正是**应用自己的判据**（start.py 用它决定"已在运行"），
    "退不干净"对用户的实际后果就是它误判成占用。bind 会被 TIME_WAIT 干扰出假阳性。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def launch_server_only(exe: Path, log_path: Path, env: Mapping[str, str], mode: str) -> "subprocess.Popen[bytes]":
    """以 `DeLector.exe --server-only` 起子进程，stdout/stderr 落 log_path。

    ⚠️ 只用 `--server-only`：CI runner 无桌面会话，GUI 路径不可作为阻塞判据（见模块 docstring）。
    `mode=="graceful"` 时带 CREATE_NEW_PROCESS_GROUP，子进程才能收到 CTRL_BREAK。
    """
    child_env = dict(os.environ)
    child_env.update(env)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUNBUFFERED"] = "1"
    with open(log_path, "wb") as handle:
        return subprocess.Popen(
            [str(exe), SERVER_ONLY_FLAG],
            cwd=str(exe.parent),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=child_env,
            creationflags=_creation_flags(mode),
        )


def _creation_flags(mode: str) -> int:
    """graceful 模式需要 CREATE_NEW_PROCESS_GROUP 才能给子进程发 CTRL_BREAK；否则为 0。"""
    return _CREATE_NEW_PROCESS_GROUP if mode == "graceful" else 0


def _probe_once() -> bool:
    """单次健康探测：200 且身份对。连不上 / 非 JSON / 503（HTTPError）一律当"还没就绪"。"""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=HEALTH_PROBE_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return health_is_ready(int(response.status), payload)
    except (urllib.error.URLError, OSError, ValueError):
        # HTTPError 是 URLError 子类（503 = 库不可用，属"还没就绪"）；JSONDecodeError 是
        # ValueError 子类；socket.timeout 是 OSError 子类。三类都被这里覆盖。
        return False


def _poll_once(proc: "subprocess.Popen[bytes]") -> str:
    """一次轮询，返回三态：ready=就绪；dead=进程已退（起不来）；pending=继续等。"""
    if proc.poll() is not None:
        return _PROBE_DEAD
    if _probe_once():
        return _PROBE_READY
    return _PROBE_PENDING


def _sleep_briefly(backoff: float, deadline: float) -> float:
    """睡一小段（不越过截止），返回下一次退避值。"""
    remaining = deadline - time.monotonic()
    time.sleep(min(backoff, max(remaining, 0.0)))
    return min(backoff * BACKOFF_MAX_FACTOR, BACKOFF_MAX_S)


def wait_until_ready(proc: "subprocess.Popen[bytes]", deadline_s: float = HEALTH_DEADLINE_S) -> Optional[float]:
    """轮询 /api/health 直到就绪；返回自起算所需秒数；超时 / 进程早退返回 None。"""
    start = time.monotonic()
    deadline = start + deadline_s
    backoff = BACKOFF_START_S
    state = _PROBE_PENDING
    while state == _PROBE_PENDING and time.monotonic() < deadline:
        state = _poll_once(proc)
        backoff = _sleep_briefly(backoff, deadline)
    return time.monotonic() - start if state == _PROBE_READY else None


def terminate_process(proc: "subprocess.Popen[bytes]", mode: str) -> StopResult:
    """按 mode 请求终止并要求进程结束，超时则升级为硬杀。

    终止策略（实测对比见模块 docstring 与 `--terminate-mode`）：
      - graceful：向 CREATE_NEW_PROCESS_GROUP 子进程发 CTRL_BREAK_EVENT，期望走 uvicorn 优雅
        退出；本机实测 Windows 上会带出系统级 STATUS_CONTROL_C_EXIT (0xC000013A)。
      - terminate：TerminateProcess（硬杀），exit code 恒为 1。
    两种口径都**无法稳定拿到 exit 0** ⇒ 本闸不断言 exit code，只断言"进程结束"这一实际保证。
    """
    start = time.monotonic()
    _request_stop(proc, mode)
    if _await_exit(proc, PROCESS_END_TIMEOUT_S):
        return StopResult(True, time.monotonic() - start, proc.returncode, False)
    proc.kill()
    ended = _await_exit(proc, PROCESS_END_TIMEOUT_S)
    return StopResult(ended, time.monotonic() - start, proc.returncode, True)


def _request_stop(proc: "subprocess.Popen[bytes]", mode: str) -> None:
    """发一次终止请求：优先优雅信号，发不出去（非 Windows / 进程已退）则退回硬杀。"""
    if mode == "graceful" and _CTRL_BREAK_EVENT is not None:
        try:
            proc.send_signal(_CTRL_BREAK_EVENT)
            return
        except (OSError, ValueError):
            pass
    proc.terminate()


def _await_exit(proc: "subprocess.Popen[bytes]", timeout_s: float) -> bool:
    try:
        proc.wait(timeout=timeout_s)
        return True
    except subprocess.TimeoutExpired:
        return False


def wait_port_release(port: int, timeout_s: float = PORT_RELEASE_TIMEOUT_S) -> float:
    """轮询直到端口不再被占用；返回释放耗时秒数；超时抛 VerifyError。"""
    start = time.monotonic()
    deadline = start + timeout_s
    while port_in_use(port) and time.monotonic() < deadline:
        time.sleep(PORT_POLL_INTERVAL_S)
    if port_in_use(port):
        raise VerifyError(
            f"端口 {port} 在 {timeout_s:.0f}s 内未释放：产物「退不干净」的实证"
            "（进程虽结束，监听却还在 —— 下次启动会误判「已在运行」）"
        )
    return time.monotonic() - start


def descendant_pids(root_pid: int, parent_of: Optional[Mapping[int, int]] = None) -> List[int]:
    """root_pid 的全部后代 PID（升序）。

    parent_of=None 时走平台探测（Windows 用 CIM）；测试可注入 parent_of 表，与平台无关地
    钉住寻树逻辑。非 Windows 探测返回空（本闸的启动段本就只在 Windows 有意义）。
    """
    if parent_of is None:
        parent_of = _windows_parent_map() if os.name == "nt" else {}
    found: set[int] = set()
    frontier: List[int] = [root_pid]
    while frontier:
        current = frontier.pop()
        children = [pid for pid, ppid in parent_of.items() if ppid == current and pid not in found]
        found.update(children)
        frontier.extend(children)
    return sorted(found)


def _windows_parent_map() -> Dict[int, int]:
    """用 PowerShell + CIM 取全表 (pid -> ppid)；失败返回空表（不阻断验收）。

    为什么不用 psutil：本脚本 MUST 只用标准库。PowerShell 是 windows-latest 既有组件，
    比已弃用的 wmic 稳。
    """
    script = "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_parent_map(proc.stdout)


def parse_parent_map(text: str) -> Dict[int, int]:
    """解析 `pid ppid` 行；非两列数字的整行跳过（对 PowerShell 的杂项输出免疫）。"""
    rows = (line.split() for line in text.splitlines())
    numeric = (cols for cols in rows if len(cols) == 2 and cols[0].isdigit() and cols[1].isdigit())
    return {int(cols[0]): int(cols[1]) for cols in numeric}


def kill_pids(pids: List[int]) -> None:
    """强杀一批 PID（含其子树）；**绝不抛**（清孤儿是尽力而为，失败由断言暴露）。"""
    for pid in pids:
        _kill_pid(pid)


def _kill_pid(pid: int) -> None:
    try:
        _kill_pid_impl(pid)
    except (OSError, subprocess.SubprocessError):
        pass


def _kill_pid_impl(pid: int) -> None:
    if os.name == "nt":
        # taskkill /T 连带子树：孤儿可能还有自己的子进程，只杀一层会留尾。
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, timeout=KILL_TIMEOUT_S)
        return
    os.kill(pid, _SIGKILL)


# ── 各步的编排（打印 + 汇总）─────────────────────────────────────────────────
def _check_build_info(report: Report, artifact: Path, expect_commit: str) -> None:
    try:
        info = read_build_info(artifact)
    except VerifyError as exc:
        report.fail("构建指纹 .build-info.json", str(exc))
        return
    missing = missing_build_info_keys(info)
    if missing:
        report.fail("构建指纹四键齐全", f"缺少键 {missing}（期望 {list(REQUIRED_BUILD_INFO_KEYS)}）")
    else:
        report.ok("构建指纹四键齐全", f"app_version={info['app_version']} commit={info['commit']}")
    problem = commit_mismatch(str(info.get("commit", "")), expect_commit)
    if problem:
        report.fail("commit 抗陈旧一致性", problem)
    elif not expect_commit.strip():
        report.skip("commit 抗陈旧一致性", "未传 --expect-commit（本地默认跳过；CI 会传入 GITHUB_SHA 短 sha）")
    else:
        report.ok("commit 抗陈旧一致性", f"与期望 {expect_commit} 一致")


def _check_integrity(report: Report, artifact: Path, expect_commit: str) -> None:
    _check_build_info(report, artifact, expect_commit)
    leaked = find_env_files(artifact)
    if leaked:
        report.fail("产物无 .env", f"发现 {leaked} —— 会把 API Key 一起发出去")
    else:
        report.ok("产物无 .env")
    missing_dll = missing_dlls(artifact)
    if missing_dll:
        report.fail("WebView2 运行时 DLL 齐全", f"缺少 {missing_dll} —— 解压后双击会白屏")
    else:
        report.ok("WebView2 运行时 DLL 齐全")
    missing_dir = missing_internal_dirs(artifact)
    if missing_dir:
        report.fail("_internal 关键目录存在", f"缺少 {missing_dir}（期望 _internal/{{webview,pythonnet}}）")
    else:
        report.ok("_internal 关键目录存在", "webview / pythonnet")


def _child_env(data_dir: Path) -> Dict[str, str]:
    """产物子进程的环境：把数据目录钉进临时目录。

    ⚠️ MUST 设 `DELECTOR_DATA_DIR`（data_dir_bootstrap 模块 docstring 的硬纪律）：不设时它按
    平台默认落点（Windows 是 %LOCALAPPDATA%\\DeLector）执行，并可能**迁移** exe 旁的旧库 ——
    既有"把真实库搬走"的污染面，又会给容器留脏。钉进临时目录后，真启产物对它**零副作用**
    （这才是"验收"，不是"顺手用一遍"）。
    """
    return {
        "DELECTOR_DATA_DIR": str(data_dir),
        "DATABASE_PATH": str(data_dir / "verify.db"),
        "PROGRESS_DB_PATH": str(data_dir / "verify_progress.db"),
    }


def _tail(path: Path, limit: int = 2000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"(读日志失败：{exc})"


def _check_orphans(report: Report, root_pid: int) -> None:
    """断言无孤儿后代；有则清掉并复验（"若产生子进程，一并清掉并断言已清"）。"""
    orphans = descendant_pids(root_pid)
    if not orphans:
        report.ok("无孤儿进程")
        return
    kill_pids(orphans)
    remaining = descendant_pids(root_pid)
    if remaining:
        report.fail("无孤儿进程", f"清理后仍有存活后代 {remaining}")
    else:
        report.ok("无孤儿进程", f"发现并已清掉后代 {orphans}")


def _check_termination(report: Report, proc: "subprocess.Popen[bytes]", mode: str) -> None:
    result = terminate_process(proc, mode)
    mode_note = "（已升级硬杀）" if result.escalated else ""
    if result.ended:
        report.ok("终止进程", f"退出耗时 {result.elapsed_s:.1f}s，exit_code={result.exit_code}{mode_note}")
    else:
        report.fail("终止进程", f"进程在 {PROCESS_END_TIMEOUT_S:.0f}s 内未结束{mode_note}")
    try:
        release_s = wait_port_release(SERVER_PORT)
        report.ok("端口释放", f"{SERVER_PORT} 于 {release_s:.1f}s 内释放")
    except VerifyError as exc:
        report.fail("端口释放", str(exc))
    _check_orphans(report, proc.pid)


def _abort_launch(proc: "subprocess.Popen[bytes]", mode: str) -> None:
    """起服失败时的收尾：确保不留残进程与孤儿。"""
    terminate_process(proc, mode)
    kill_pids(descendant_pids(proc.pid))


def _check_launch(report: Report, artifact: Path, mode: str) -> None:
    exe = artifact / EXE_NAME
    if not exe.is_file():
        report.fail("真启找得到可执行文件", f"缺少 {exe}")
        return
    if port_in_use(SERVER_PORT):
        report.fail("起服前端口空闲", f"端口 {SERVER_PORT} 已被占用 —— 无法判定产物是否真能起服务")
        return
    tmp_dir = Path(tempfile.mkdtemp(prefix="delector_verify_"))
    log_path = tmp_dir / "server.log"
    try:
        proc = launch_server_only(exe, log_path, _child_env(tmp_dir), mode)
        ready_s = wait_until_ready(proc)
        if ready_s is None:
            detail = (
                f"产物在 {HEALTH_DEADLINE_S:.0f}s 内未就绪（期望 /api/health 200 且 app=='delector'）；"
                f"进程退出码={proc.poll()}。服务日志尾部：\n{_tail(log_path)}"
            )
            report.fail("真启 --server-only 至就绪", detail)
            _abort_launch(proc, mode)
            return
        report.ok("真启 --server-only 至就绪", f"起服耗时 {ready_s:.1f}s（对照 ADR-0018 代理口径 2.6s）")
        _check_termination(report, proc, mode)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _finish(report: Report) -> int:
    print("=" * 60)
    if report.failed:
        print("验收结论：FAIL —— 产物不合格，**禁止**进入压缩 / 上传（坏产物绝不能进 zip/artifact）。")
        return 1
    print("验收结论：PASS —— 产物通过完整性 + 真启验收（窗口形态不在本闸覆盖；见脚本 docstring）。")
    return 0


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeLector Windows 便携产物验收闸（完整性 + 真启一次）")
    parser.add_argument("--artifact", default="", help="产物目录；缺省用 dist 下唯一的 Windows 便携产物")
    parser.add_argument("--expect-commit", default="", help="期望的 commit 短 sha（CI 传 GITHUB_SHA）；不传则跳过该项")
    parser.add_argument(
        "--terminate-mode",
        choices=("graceful", "terminate"),
        default=DEFAULT_TERMINATE_MODE,
        help="终止策略：graceful=CTRL_BREAK_EVENT；terminate=TerminateProcess（实测对比用）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    _reconfigure_streams()
    args = _parse_args(argv)
    report = Report()
    try:
        artifact = locate_artifact(_REPO_ROOT / "dist", args.artifact)
    except VerifyError as exc:
        report.fail("定位产物目录", str(exc))
        return _finish(report)
    report.ok("定位产物目录", str(artifact))
    _check_integrity(report, artifact, args.expect_commit)
    # 完整性不过就不真启：一个已知坏的产物（缺 DLL / 夹带 .env）不该被跑起来，更不该进包。
    if report.failed:
        return _finish(report)
    _check_launch(report, artifact, args.terminate_mode)
    return _finish(report)


if __name__ == "__main__":
    raise SystemExit(main())
