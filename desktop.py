#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""DeLector Windows 桌面壳：pywebview 窗口 + pystray 托盘 + 统一退出收尸（ADR-0020 §4）。

设计要点
--------
- **Python 仍是 HTTP 主体**（不违反 ADR-0018）：本壳只换前端宿主，服务仍是本进程里的 uvicorn。
- **三线程模型（互不阻塞）**：pywebview **占主线程**（GUI 事件循环必须在主线程）；server 走
  `serve_in_thread`（**非 daemon**）；托盘（pystray）放**独立线程**。
- **四条必须一起做的前置**（缺一即静默失败）：① 退出收尸；② 启动反馈（splash 分阶段）；
  ③ WebView2 运行时检测；④ 日志（`launch.log`）与失败弹窗。
- **双窗口（方案 A）**：splash 是无边框置顶小窗（启动反馈）；真实 UI 住在**另一个普通可缩放
  窗口**（有标题栏、可最大化/还原/拖边、不置顶，初始隐藏），就绪后亮主窗口并销毁 splash。
  二者需求相反（置顶/无边框 vs 可缩放/有标题栏），共用一个窗口会把真实 UI 关进无标题栏小窗
  —— 即"没法放大、没法改尺寸"的成因。
- **真实首屏口径（关掉 ADR-0018 §8 `Unknown 8` 的代理口径缺口）**：日志在**进程最早处**记
  「开始启动（进程级计时起点）」，并在主窗口 `load_url` 之后按 pywebview 的 **`loaded` 事件**
  （页面渲染完成）记「真实 UI 已加载（首屏可用）」—— 这才是"首屏"的**真口径**；此前的
  `health_200`（服务就绪）只是**代理口径**，不可冒充首屏。解析见 `tools/first_screen_from_log.py`。
- **可安全 import**：模块顶层**不**导入 webview / pystray、不启动任何东西；重活只在
  `run_desktop()` 与 `if __name__ == "__main__":` 内发生（CI 缺 GTK/WebKit 时 import 不会炸）。

为什么日志落数据目录（而非程序目录）
----------------------------------
打包成 `--windowed` 后 stdout 不可见；日志若落程序目录，用户"覆盖安装新版 / 删旧目录"就把它
一起清掉。故复用 Task 1 的 `resolve_data_dir`，让日志与库、备份同处一地。

为什么所有退出路径都要过 `coordinated_shutdown`
--------------------------------------------
"壳退了服务还残留"会让下次启动盲判"端口被占用"、甚至"以为升级了其实还是旧进程在服务" —— 这是
比"没有桌面窗口"严重得多的静默失败。故关窗 / 托盘退出 / 异常 / Ctrl+C **四条路径**统一先
`shutdown(server, thread)`；超时（返回 False）则硬退出，绝不留残留。
"""

import argparse
import os
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Mapping, Optional, TextIO, Tuple

from delector.core.data_dir_bootstrap import bootstrap_data_dir, resolve_data_dir
from delector.core.server_lifecycle import await_ready, build_server, serve_in_thread, shutdown

LOG_FILE_NAME = "launch.log"

# 局域网地址文件：`--windowed` 打包后没有控制台，start.py 的横幅（唯一带 LAN 地址的输出）
# 没人看得见 ⇒ 在数据目录落一份 `http://<LAN_IP>:<port>`（每次启动覆盖；能双击打开、能复制、
# 随时再看）。托盘「显示局域网地址」读它；`--server-only` 与桌面态 LAN 可用时都写。
LAN_ADDRESS_FILE_NAME = "lan-address.txt"

# 日志轮转上限：桌面端长期运行会持续追加（uvicorn 每请求一行 access，见 server_lifecycle
# 的 log_level="info"），无上限的追加早晚吃满磁盘。启动时若 launch.log 超过此值就滚动为
# `launch.log.1`（只保留一份旧的），保证它有界。**不改日志行格式**——
# `tools/first_screen_from_log.py` 依赖 `[时间戳] 消息` 解析，格式一变该工具即失效。
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_SUFFIX = ".1"

# 桌面端绑 0.0.0.0 是**有意保留**的特性（与 start.py 一致）：同 Wi-Fi 的手机/平板可访问工作台。
BIND_HOST = "0.0.0.0"

# 就绪窗口给足：spaCy 模型已改**惰性加载**（ADR-0018 §7.6 O0 杠杆）——启动期不再 spacy.load，
# 故 ADR-0018 §7.3 记的「首启 health_200 ≈ 2.6s、其中模型加载 ≈ 1.47s」是惰性化**之前**的口径，
# 现已不再成立（模型加载被推迟到**首次真正需要 NLP 的请求**）。但首次建档 / 首次打开文章仍会触发
# 一次模型加载（有机器依赖，慢盘上可达数秒）⇒ 取 60s 兜底，宁慢勿"静默判未就绪"。
READY_DEADLINE_S = 60.0

# 默认端口：桌面窗口路径用它；`--server-only` 复用 `start.main()` 时**固定**用它
# —— 该路径不接受 `--port`（见 dispatch 的显式警告），此常量是其真实端口的单一真相。
DEFAULT_PORT = 8000

# ── AppUserModelID（Win32 任务栏身份）────────────────────────────────────────
# PyInstaller `--windowed` 的进程默认继承宿主 exe 的身份 ⇒ 任务栏按钮被归到 "Python" 分组、
# 固定到任务栏后也认不出是 DeLector。`SetCurrentProcessExplicitAppUserModelID` 必须在**建窗
# 之前**调用（任务栏按钮在首个窗口出现时定身份，晚设不生效）；仅 win32、**绝不抛**、失败落
# `launch.log`（范式同 `_allocate_debug_console`）。
APP_USER_MODEL_ID = "ROM4n2.DeLector"

# ── WebView2 运行时检测（锚点取自本机实测注册表）────────────────────────────
# 实测：HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID} 的 pv=154.0.4258.62。
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_PV_VALUE = "pv"
WEBVIEW2_REG_SUBPATH = "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + WEBVIEW2_GUID

# 三处都要查：64/32 位视图落点不同，HKCU 覆盖"用户级安装"。顺序即遍历顺序（测试钉住成员与顺序）。
WEBVIEW2_BRANCHES: Tuple[str, ...] = ("HKLM_WOW6432", "HKLM", "HKCU")

# WebView2 Evergreen 运行时官方下载（Microsoft 短链 fwlink）—— 缺失时给用户的可点击入口。
WEBVIEW2_DOWNLOAD_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

# Release 页：托盘「检查更新」直接打开它（与 /api/update/check 的 page_url 同源语义）。
RELEASE_PAGE_URL = "https://github.com/ROM4n2/DeLector/releases"

# ── 窗口几何：splash 是刻意的小窗启动反馈；主窗口必须是**普通可缩放窗口** ─────────
# 为什么拆成两个窗口（方案 A）：splash 需要无边框 + 置顶才有"启动反馈"的观感，而真实 UI 必须有
# 标题栏（最大化/还原/拖边）且不得永远置顶。二者需求相反，同一个窗口无法兼得 —— 旧实现复用同一个
# splash 窗口 load_url，把真实 UI 关进无标题栏小窗（本次缺陷：没法放大、没法改尺寸）。
SPLASH_WIDTH = 430
SPLASH_HEIGHT = 270
MAIN_WINDOW_TITLE = "DeLector"
MAIN_WINDOW_WIDTH = 1280
MAIN_WINDOW_HEIGHT = 820
MAIN_WINDOW_MIN_SIZE: Tuple[int, int] = (900, 600)

# ── splash 分阶段文案（启动反馈：ADR-0020 §4 前置②）──────────────────────────
# 为什么不再写「正在加载德语模型」：spaCy 模型已改**惰性加载**（ADR-0018 §7.6 O0 杠杆）——
# 启动期不再 spacy.load（preload 也不做），模型推迟到**首次真正需要 NLP 的请求**（首次打开
# 文章时经惰性迁移加载）。故启动阶段文案据实改成「启动服务 / 等待就绪」，不让 UI 说谎。
SPLASH_LOADING_MODEL = "正在启动服务…"
SPLASH_STARTING_SERVER = "正在等待服务就绪…"
SPLASH_READY = "就绪"

# ── 托盘菜单（打开 / 显示局域网地址 / 检查更新 / 退出）；action 键供实现映射到处理函数 ──
TRAY_MENU_SPEC: Tuple[Tuple[str, str], ...] = (
    ("打开", "open"),
    ("显示局域网地址", "show_lan_address"),
    ("检查更新", "check_update"),
    ("退出", "quit"),
)


# ── 日志：落数据目录 + 显式文件句柄（--windowed 下 sys.stdout 可能为 None）────
def resolve_log_path(env: Mapping[str, str]) -> str:
    """日志落点 = Task 1 的数据目录 + `launch.log`（与库、备份同处一地，覆盖安装不丢）。"""
    return os.path.join(resolve_data_dir(env), LOG_FILE_NAME)


def resolve_lan_address_path(env: Mapping[str, str]) -> str:
    """局域网地址文件落点 = 数据目录 + `lan-address.txt`（与 launch.log、库同处一地，覆盖安装不丢）。"""
    return os.path.join(resolve_data_dir(env), LAN_ADDRESS_FILE_NAME)


def open_log_streams(log_path: str) -> Tuple[TextIO, TextIO]:
    """打开 stdout/stderr 的追加流。

    `--windowed` 形态下 `sys.stdout` / `sys.stderr` 可能为 `None`（无控制台），故**必须显式开
    文件句柄**，不能依赖 `print` 到默认流。
    """
    out = open(log_path, "a", encoding="utf-8", buffering=1)
    err = open(log_path, "a", encoding="utf-8", buffering=1)
    return out, err


def rotate_log_if_needed(log_path: str, max_bytes: int = LOG_MAX_BYTES) -> bool:
    """启动时滚动过大日志：超 `max_bytes` 就把 `launch.log` 移为 `launch.log.1`（覆盖旧备份）。

    为什么在**启动时**做（而非运行期定时器）：运行期滚动要与两个永不关闭的追加句柄
    （`open_log_streams` 的 stdout/stderr 句柄）协调，竞态复杂；每次启动都是一条干净边界，
    此处滚动最简单、无竞态。只保留**一份**旧的：滚动后新 `launch.log` 从空开始。
    返回 True 表示真的滚动了（供调用方/测试观测）；轮转失败**不阻断启动**（维护动作，
    写不进好过起不来），但**不静默吞**：把原因落 `_append_log`。
    """
    try:
        if not os.path.isfile(log_path) or os.path.getsize(log_path) <= max_bytes:
            return False
        os.replace(log_path, log_path + LOG_BACKUP_SUFFIX)
        return True
    except OSError as exc:
        _append_log(log_path, f"启动时日志大小检查/轮转失败（不阻断启动）：{exc!r}")
        return False


def _append_log(log_path: str, message: str) -> None:
    """追加一行带时间戳的日志。**绝不抛**：日志写不进去不能让调用方跟着崩。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        # 日志不可写是"最没得治"的环境问题；此处只静默放弃（调用方可能正在崩溃处理中）。
        pass


def _detect_lan_address(port: int) -> Optional[str]:
    """探测局域网地址 `http://<LAN_IP>:<port>`；探不到 LAN IP（离线/仅回环）返回 None。

    复用 `start.get_local_ip`（惰性 import）：桌面端与 `--server-only` 对"有没有 LAN"必须
    同一判法，另写一套 socket 探测迟早漂移。判据与 start.py 横幅一致：回环 = 没有 LAN。
    """
    import start

    ip = start.get_local_ip()
    if ip == "127.0.0.1":
        return None
    return f"http://{ip}:{port}"


def _remove_stale_lan_address(env: Mapping[str, str], log_path: str) -> None:
    """删除上一轮残留的 `lan-address.txt`（本次没探测到 LAN）。**绝不抛**。

    黄牌背景：探不到 LAN 时只"不写"不够 —— 上一轮的文件还在，托盘「显示局域网地址」会读出
    **上一轮**的 IP 给用户（拿着过期地址连手机然后失败，比没有文件更糟）。删掉它，托盘就走
    "可读失败"路径（明说本次没有地址）。删除失败（被杀软锁等）不阻断启动，仅留痕。
    """
    path = resolve_lan_address_path(env)
    try:
        if os.path.isfile(path):
            os.remove(path)
            _append_log(log_path, f"已删除上一轮残留的 {LAN_ADDRESS_FILE_NAME}（本次未探测到局域网 IP）。")
    except OSError as exc:
        _append_log(log_path, f"删除残留 {LAN_ADDRESS_FILE_NAME} 失败（不阻断启动）：{exc!r}")


def write_lan_address(port: int, env: Mapping[str, str], log_path: str) -> Optional[str]:
    """把局域网地址写进数据目录的 `lan-address.txt`（每次启动覆盖）。返回写入的地址。

    为什么需要它：`--windowed` 打包后 stdout 不可见，start.py 的横幅没了 ⇒ 落一份文件
    （双击可看、可复制、随时再看），托盘「显示局域网地址」也读它。两条硬约束：
    - **没有 LAN 就不写**：回环地址不是"局域网地址"，写进去只会让用户拿它连手机然后失败；
      且必须**清掉上一轮残留**（否则托盘读出过期 IP，见 `_remove_stale_lan_address`）；
    - **写失败不得阻断启动**：地址是便利功能，"起不来"比"没有地址"严重得多 —— 失败落
      `_append_log` 留痕后返回 None。
    """
    address = _detect_lan_address(port)
    if address is None:
        _append_log(log_path, f"未探测到局域网 IP（端口 {port}）：本次不写 {LAN_ADDRESS_FILE_NAME}。")
        _remove_stale_lan_address(env, log_path)
        return None
    path = resolve_lan_address_path(env)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(address + "\n")
    except OSError as exc:
        _append_log(log_path, f"写 {LAN_ADDRESS_FILE_NAME} 失败（不阻断启动）：{exc!r}")
        return None
    _append_log(log_path, f"局域网地址已写入 {path}：{address}")
    return address


def _win_ms_since_create() -> float:
    """Windows：自**进程创建**到此刻的毫秒数（`GetProcessTimes` + `GetSystemTimeAsFileTime`）。

    两个时刻都是 OS 给的 FILETIME（100ns 单位、自 1601-01-01 起）⇒ 直接相减，与时区/夏令时无关。
    失败**会抛**（由 `_ms_since_process_create` 统一兜成 None）：这里只负责"问一次系统"，错误
    处理只该在一个地方，免得两处口径漂移。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    ok = kernel32.GetProcessTimes(
        kernel32.GetCurrentProcess(),
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    )
    if not ok:
        raise OSError("GetProcessTimes 返回失败")
    now = wintypes.FILETIME()
    kernel32.GetSystemTimeAsFileTime(ctypes.byref(now))
    delta = ((now.dwHighDateTime << 32) | now.dwLowDateTime) - (
        (created.dwHighDateTime << 32) | created.dwLowDateTime
    )
    return delta / 10000.0  # 100ns 单位 ⇒ 毫秒


def _ms_since_process_create() -> Optional[float]:
    """自**进程创建**到此刻的毫秒数；取不到返回 None，**绝不抛**。

    为什么必须问 OS 要"进程创建时刻"、而不能用 `time.time()` 减一个模块级常量：解释器启动、
    本模块的模块级 import、以及打包形态下 PyInstaller 的 bootstrap 全在本文件第一条语句**之前**
    —— 自己记的起点只能量到那之后，恰恰漏掉要测的那段。
    非 Windows 直接返回 None（CI 是 ubuntu，`ctypes.windll` 在那儿根本不存在）。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        return _win_ms_since_create()
    except Exception:
        # 取不到就报"取不到"（调用方写 `?`）：绝不让一个仪表把启动搞崩。
        return None


def _log_prestart_elapsed(log_path: str) -> None:
    """落一行「自进程创建」的毫秒数（取不到写 `?`）。

    **另起一行**、不改既有锚行：`tools/first_screen_from_log.py` 用子串匹配锚行（起点/就绪/首屏），
    把机器相关数字塞进锚行会让既有断言变脆。
    """
    elapsed = _ms_since_process_create()
    shown = "?" if elapsed is None else f"{elapsed:.0f}"
    _append_log(log_path, f"进程已运行 {shown} ms（自进程创建；此前为未测段）")


def _bind_missing_streams_to_devnull() -> None:
    """日志/控制台都不可用时的最后兜底：只补缺失流，且**绝不抛**。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        try:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", buffering=1))
        except Exception:
            # 连 devnull 都打不开时已无可用的留痕介质；仍不得让收口本身阻断启动。
            pass


def _allocate_debug_console() -> None:
    """Windows debug 模式按需挂回控制台；非 Windows 或任意失败都直接返回。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.AllocConsole()
    except Exception:
        return

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        try:
            setattr(sys, name, open("CONOUT$", "w", encoding="utf-8", buffering=1))
        except Exception:
            # AllocConsole 成功但设备流打开失败时，交给 ensure_streams 的 devnull 兜底。
            pass


def _set_app_user_model_id(log_path: str) -> None:
    """Windows：给进程设显式 AppUserModelID；非 Windows 或任意失败都直接返回（**绝不抛**）。

    为什么需要它：`--windowed` 打包后进程默认继承宿主 exe 身份，任务栏按钮会被归到 "Python"
    分组、固定到任务栏后也认不出是 DeLector。显式设置后任务栏/固定快捷方式才与品牌一致。
    时机：进程早期、**建窗之前** —— 任务栏按钮在首个窗口出现时定身份，晚设不生效。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        _append_log(log_path, f"AppUserModelID 已设置：{APP_USER_MODEL_ID}")
    except Exception as exc:
        _append_log(log_path, f"设置 AppUserModelID 失败（不阻断启动）：{exc!r}")


def ensure_streams(log_path: str, debug_console: bool = False) -> None:
    """确保 stdout/stderr 可写，供桌面与跨平台入口共同调用。

    默认只收口 `None` 流：将其绑定到既有 `launch.log` 追加流，不覆盖真实终端或 pytest 捕获流。
    `debug_console=True` 时不写日志；Windows 上按需 `AllocConsole()`，失败或非 Windows 则退到
    devnull。整个收口链路**绝不抛**，避免日志设施反过来阻断进程启动。
    """
    try:
        if debug_console:
            if sys.stdout is None or sys.stderr is None:
                _allocate_debug_console()
            _bind_missing_streams_to_devnull()
            return

        missing_out = sys.stdout is None
        missing_err = sys.stderr is None
        if not missing_out and not missing_err:
            return

        parent = os.path.dirname(os.path.abspath(log_path))
        os.makedirs(parent, exist_ok=True)
        out, err = open_log_streams(log_path)
        if missing_out:
            sys.stdout = out
        else:
            out.close()
        if missing_err:
            sys.stderr = err
        else:
            err.close()
    except Exception as exc:
        # 先复用既有日志惯例留痕；路径本身不可写时再静默降级，二者都不得外抛。
        try:
            _append_log(log_path, f"标准流收口失败，退到静默流：{exc!r}")
        except Exception:
            pass
        _bind_missing_streams_to_devnull()


def _redirect_std_streams(log_path: str, debug_console: bool = False) -> None:
    """兼容既有启动接线：仅收口缺失的 stdout/stderr，失败不阻止启动。"""
    ensure_streams(log_path, debug_console)


def _message_box(title: str, detail: str) -> None:
    """原生弹窗（崩溃 / 缺失运行时 / 就绪失败都用它）。非 Windows 退化为 stderr。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, detail, title, 0x10)  # 0x10 = MB_ICONERROR
    except Exception:
        # 非 Windows / ctypes 不可用：退化成 stderr（无头场景至少留痕，绝不静默吞掉）。
        print(f"[{title}] {detail}", file=sys.stderr)


def write_crash(title: str, detail: str, log_path: str) -> None:
    """写 traceback 到 `launch.log` + 弹窗。**绝不抛**（崩溃处理里的二次异常会掩盖原始错误）。"""
    _append_log(log_path, f"{title}\n{detail}")
    _message_box(title, detail)


# ── ① WebView2 运行时检测：注册表三处 + pv 值 ────────────────────────────────
def _branch_to_hive_view(winreg: Any, branch: str) -> Tuple[Any, int]:
    """把分支名映射成 `(hive, 视图 flag)`；未知分支返回 `(None, 0)`。"""
    mapping = {
        "HKLM_WOW6432": (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        "HKLM": (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        "HKCU": (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_64KEY),
    }
    return mapping.get(branch, (None, 0))


def _read_registry_pv(branch: str) -> Optional[str]:
    """读某分支下 WebView2 客户端项的 `pv`；非 Windows / 不可读返回 None（**不抛**）。"""
    try:
        import winreg
    except ImportError:
        return None  # 非 Windows：检测退化为"缺失"，由上层给出安装引导
    hive, view = _branch_to_hive_view(winreg, branch)
    if hive is None:
        return None
    try:
        key = winreg.OpenKey(hive, WEBVIEW2_REG_SUBPATH, 0, winreg.KEY_READ | view)
    except OSError:
        return None
    try:
        value, _kind = winreg.QueryValueEx(key, WEBVIEW2_PV_VALUE)
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)
    return value if isinstance(value, str) else None


def _detect_webview2_pv(read_pv: Callable[[str], Optional[str]]) -> Optional[str]:
    """按序遍历三处分支，返回**首个**非空 `pv`；都没有返回 None（命中即短路）。"""
    for branch in WEBVIEW2_BRANCHES:
        pv = read_pv(branch)
        if isinstance(pv, str) and pv.strip():
            return pv
    return None


def ensure_webview2_runtime(read_pv: Optional[Callable[[str], Optional[str]]] = None) -> bool:
    """WebView2 运行时是否可用（按注册表 `pv` 判定）。

    `read_pv` 是**依赖注入缝**：默认读真实注册表；测试注入替身以钉住三分支逻辑（零依赖、跨平台）。
    """
    reader = _read_registry_pv if read_pv is None else read_pv
    return _detect_webview2_pv(reader) is not None


def webview2_missing_message() -> str:
    """缺失运行时的提示文案：**必须给出安装入口**，否则"解压即用"被打破（ADR-0020 §4 前置③）。"""
    return (
        "DeLector 需要「Microsoft Edge WebView2 运行时」才能显示桌面窗口。\n"
        f"请安装后重试：{WEBVIEW2_DOWNLOAD_URL}\n"
        "（Windows 11 通常已内置；Windows 10 若缺失可安装 Evergreen 运行时。）"
    )


# ── 统一退出：关窗 / 托盘退出 / 异常 / Ctrl+C 共用同一收尸路径 ────────────────
class QuitCoordinator:
    """统一退出触发器：关窗与托盘「退出」都调 `request_quit()` ⇒ 同一收尸路径，且**幂等**。

    幂等是必需的：关窗会触发一次、托盘「退出」也可能触发一次；两条路径都到齐时只允许收尸一次，
    否则会二次硬退出 / 二次销毁窗口，导致崩溃或卡死。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = False

    def request_quit(self) -> bool:
        """请求退出。返回 True 表示本次请求生效（首次）；重复请求返回 False（被忽略）。"""
        with self._lock:
            # 守卫式压平：把「首次?」记下再无条件置位，避免 with→if→return 的三层嵌套。
            first = not self._requested
            self._requested = True
            return first

    @property
    def requested(self) -> bool:
        return self._requested


def coordinated_shutdown(
    server: Any,
    thread: threading.Thread,
    log_path: str,
    exit_fn: Callable[[int], None] = os._exit,
) -> bool:
    """**唯一**收尸入口：先 `shutdown(server, thread)`；超时（返回 False）⇒ 硬退出。

    返回 True = 干净退出；返回 False = 宽限期内没停干净、进程已（或将被）硬退出。**所有**退出
    路径都必须经过这里，杜绝"壳退了服务还残留"。
    """
    if shutdown(server, thread):
        _append_log(log_path, "服务已干净退出。")
        return True
    _append_log(log_path, "服务在宽限期内未退出：硬退出进程，避免残留。")
    exit_fn(1)
    return False


# ── ② 启动反馈：splash 分阶段 → 就绪后切真实 UI ───────────────────────────────
def _splash_html(stage: str) -> str:
    """splash 的极简 HTML：深色底 + 当前阶段文案（就绪前用户唯一能看到的反馈）。"""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>DeLector</title></head>"
        "<body style=\"margin:0;font-family:'Segoe UI',sans-serif;background:#0f1115;color:#e8e8ea;"
        "display:flex;align-items:center;justify-content:center;height:100vh\">"
        "<div style='text-align:center'>"
        "<div style='font-size:24px;font-weight:600;letter-spacing:2px'>DeLector</div>"
        f"<div id='stage' style='margin-top:12px;color:#b9b9c0'>{stage}</div>"
        "</div></body></html>"
    )


def _set_splash_stage(window: Any, stage: str, log_path: str) -> None:
    """把 splash 阶段文案推进一格。

    **不再静默吞异常**（P0 事故帮凶）：`evaluate_js` 会 marshal 到 GUI 线程执行，而该线程要等
    `webview.start()` 才跑 —— 时序错了它不报错而是**永久等待**；旧实现的 `except Exception: pass`
    把这件事彻底抹掉，事故排查时零线索。现在失败一律 `_append_log`（写清哪一步、什么异常）。
    """
    try:
        window.evaluate_js(f"document.getElementById('stage').textContent = {stage!r}")
    except Exception as exc:
        _append_log(log_path, f"splash 阶段更新失败（stage={stage}）：{exc!r}")


# ── 托盘（pystray 放独立线程，不阻塞主线程 GUI 事件循环）────────────────────
def _tray_image(image_module: Any, draw_module: Any) -> Any:
    """一张最简托盘图标（深底 + 暖色方块），避免依赖外部图标文件。"""
    img = image_module.new("RGB", (64, 64), (28, 28, 32))
    draw = draw_module.Draw(img)
    draw.rectangle((12, 12, 52, 52), fill=(212, 168, 83))
    return img


def _tray_open(window: Any) -> None:
    try:
        window.show()
    except Exception:
        pass


def _tray_check_update(_window: Any) -> None:
    """托盘「检查更新」：打开 Release 页（用户当场看到是否有新版）。"""
    try:
        import webbrowser

        webbrowser.open(RELEASE_PAGE_URL)
    except Exception:
        pass


def _read_lan_address() -> str:
    """读数据目录里的 `lan-address.txt`；读不到 / 内容为空返回空串（调用方给可读失败提示）。

    except 必须捕 `(OSError, UnicodeDecodeError)`：坏文件（非 UTF-8 字节）抛的是
    UnicodeDecodeError（⊂ ValueError，**不是** OSError）—— 只捕 OSError 会让它穿过本函数
    逃进 pystray 托盘回调 ⇒ 托盘线程静默死亡。扩捕后坏文件与缺失同走"可读失败"路径。
    """
    try:
        with open(resolve_lan_address_path(os.environ), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _tray_show_lan_address(_window: Any) -> None:
    """托盘「显示局域网地址」：弹原生窗显示地址（可 Ctrl+C 复制）；拿不到时给**可读**失败提示。

    不许静默：用户点了一项却什么都没发生，比没有这项更糟。失败同时弹窗 + 落 launch.log。
    """
    address = _read_lan_address()
    if not address:
        _append_log(
            resolve_log_path(os.environ), "托盘「显示局域网地址」未读到地址：lan-address.txt 缺失或为空。"
        )
        _message_box(
            "无法显示局域网地址",
            "未找到局域网地址（数据目录里的 lan-address.txt 缺失或为空）。\n"
            "可能原因：启动时未探测到局域网 IP（电脑未联网）。\n"
            "请确认电脑已联网后重启 DeLector，详情见 launch.log。",
        )
        return
    _message_box(
        "局域网地址",
        f"手机/平板（同一 Wi-Fi）可用浏览器打开：\n{address}\n\n"
        f"地址也已写入数据目录的 {LAN_ADDRESS_FILE_NAME}，可随时复制。",
    )


def _tray_quit(window: Any, coordinator: QuitCoordinator) -> None:
    """托盘「退出」：与关窗走**同一**收尸路径（先标记 coordinator，再销毁窗口）。"""
    if coordinator.request_quit():
        try:
            window.destroy()
        except Exception:
            pass


def _tray_handler_map(window: Any, coordinator: QuitCoordinator) -> Dict[str, Callable[[], None]]:
    """动作键 → 处理函数的**唯一**真相（键名与 `TRAY_MENU_SPEC` 的 action 对齐）。"""
    return {
        "open": lambda: _tray_open(window),
        "show_lan_address": lambda: _tray_show_lan_address(window),
        "check_update": lambda: _tray_check_update(window),
        "quit": lambda: _tray_quit(window, coordinator),
    }


def assert_keys_cover_spec(spec: Tuple[Tuple[str, str], ...], handlers: Mapping[str, Any]) -> None:
    """断言 `spec` 的动作键集合与 `handlers` 键集合**恒等**（缺一或多一都算漂移）。

    为什么是"恒等"而非"覆盖"：多出来的 handler 是死代码（无人调用），漏掉的 spec 动作键会
    在菜单组装时 KeyError。两者都要报，才能保证两个独立声明始终同步。
    """
    spec_keys = [action for _label, action in spec]
    if set(spec_keys) != set(handlers):
        raise ValueError(f"托盘菜单 spec 与 handlers 键不一致：spec={spec_keys} handlers={list(handlers)}")


def build_tray_handlers(
    spec: Tuple[Tuple[str, str], ...], window: Any, coordinator: QuitCoordinator
) -> Dict[str, Callable[[], None]]:
    """由 spec 校验并构造处理函数表（纯函数，**不依赖 pystray 真跑**）。

    原实现把 handlers 硬编码在托盘线程内，`TRAY_MENU_SPEC` 的动作键一旦漂移，`handlers[action]`
    会 KeyError 让**托盘线程静默死亡**（用户只看到托盘没了、零线索）。抽成纯函数后，键一致性
    可在 import/测试期即被钉死；运行期漂移也会在此显式报错而非无声 KeyError。
    """
    handlers = _tray_handler_map(window, coordinator)
    assert_keys_cover_spec(spec, handlers)
    return handlers


def _run_tray(window: Any, coordinator: QuitCoordinator, log_path: str) -> None:
    """托盘线程主体：组装菜单并从 `TRAY_MENU_SPEC` 映射处理函数。GUI 依赖在此惰性导入。"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as exc:
        _append_log(log_path, f"托盘不可用（{exc}）：功能降级为仅窗口。")
        return

    # 组装也放进 try：spec→handlers 漂移会在此显式报错并被**记入日志**，不再静默杀死线程。
    try:
        handlers = build_tray_handlers(TRAY_MENU_SPEC, window, coordinator)
        menu = pystray.Menu(*[pystray.MenuItem(label, handlers[action]) for label, action in TRAY_MENU_SPEC])
        icon = pystray.Icon("DeLector", _tray_image(Image, ImageDraw), "DeLector", menu)
        icon.run()
    except Exception as exc:
        _append_log(log_path, f"托盘线程异常退出（{exc}）。")


def _start_tray(window: Any, coordinator: QuitCoordinator, log_path: str) -> None:
    """在**独立线程**里跑托盘（daemon：随主进程退出而结束，不阻塞收尾）。"""
    threading.Thread(
        target=_run_tray,
        args=(window, coordinator, log_path),
        name="delector-tray",
        daemon=True,
    ).start()


def _destroy_window(window: Any, log_path: str) -> None:
    """销毁窗口，让阻塞中的 `webview.start()` 得以返回。

    失败路径**必须真正结束进程**：不能只弹窗然后把一个空 splash 永远挂着（那正是本次事故的形态）。
    销毁失败也要留痕，否则又回到"窗口不出、零线索"。

    对已被销毁的窗口重复调用是**安全**的（pywebview 在实例已消失时静默返回）。
    """
    try:
        window.destroy()
    except Exception as exc:
        _append_log(log_path, f"销毁窗口失败：{exc!r}")


def _abort_windows(splash: Any, main: Any, coordinator: QuitCoordinator, log_path: str) -> None:
    """就绪失败 / 异常时的收尾：标记退出并销毁**两个**窗口。

    为什么两个都要销毁：pywebview 的 GUI 循环在**最后一个**窗口关闭时才退出（winforms 平台在
    `BrowserView.instances` 清空时调 `Application.Exit`）。只销毁 splash 而隐藏的主窗口仍存活 ⇒
    `start()` 永不返回 ⇒ 进程挂着不退（与 P0 同形的静默挂起）。
    """
    coordinator.request_quit()
    _destroy_window(splash, log_path)
    _destroy_window(main, log_path)


def _on_main_closed(splash: Any, coordinator: QuitCoordinator, log_path: str) -> None:
    """主窗口关闭 = 用户显式退出：标记统一收尸触发器，并把仍在的 splash 一并销毁。

    为什么必须销毁 splash：GUI 循环在最后一个窗口关闭时才退出；若主窗口先关而 splash 仍在（就绪后
    销毁与关窗之间的竞态边界），循环永不返回。对已销毁的 splash 重复销毁是安全的（见 `_destroy_window`）。
    """
    coordinator.request_quit()
    _destroy_window(splash, log_path)


def _after_start(
    splash: Any,
    main: Any,
    coordinator: QuitCoordinator,
    port: int,
    log_path: str,
    result: List[int],
) -> None:
    """GUI 事件循环**启动后**（由 `webview.start(func, args)` 在独立线程调度）要做的后台工作。

    为什么这段必须搬到这里（P0 死锁根因）：pywebview 会把 `evaluate_js` / `load_url` marshal 到
    GUI 线程执行，而 GUI 事件循环由 `webview.start()` 才启动 —— 在 start **之前**调它们会永久等待
    （`scratch/repro_splash_deadlock.py` 三模式实测），窗口永不出现、进程永不退出。放进 `func` 后
    循环已在跑，evaluate_js / load_url 都安全。

    就绪后**切到主窗口**（方案 A 的双窗口）：先 `main.show()` 亮出普通可缩放窗口，再
    `main.load_url(...)` 加载真实 UI，最后 `splash.destroy()` 收掉启动反馈。顺序不可颠倒：
    销毁 splash 前主窗口必须已在（否则瞬间零窗口 ⇒ GUI 循环提前退出）。

    **首屏真口径**：`load_url` 之前注册 pywebview 的 `loaded` 事件（页面渲染完成），命中时记
    「真实 UI 已加载（首屏可用）」。注册放在这里（循环已起）既满足 P0（循环启动前碰窗口/事件会
    永久阻塞），又因 `load_url` 会 `events.loaded.clear()` 而必须早于它注册。

    `result` 是回传给主线程 `_show_window` 的退出码容器：失败时置 1 并**销毁两个窗口**，让
    `webview.start()` 得以返回（否则进程会挂着一个空 splash 永不退出）。
    """
    try:
        _set_splash_stage(splash, SPLASH_STARTING_SERVER, log_path)
        _append_log(log_path, "等待服务就绪…")
        if not await_ready(port, deadline_s=READY_DEADLINE_S):
            # 就绪失败必须**可见**：日志 + 弹窗 + 真正结束进程（不留空 splash）。
            _append_log(log_path, "服务在就绪窗口内未就绪：提示用户并退出。")
            _message_box("DeLector 启动超时", f"本地服务在 {READY_DEADLINE_S:.0f}s 内未就绪，详情见 launch.log。")
            result[0] = 1
            _abort_windows(splash, main, coordinator, log_path)
            return
        _append_log(log_path, "服务已就绪。")
        _set_splash_stage(splash, SPLASH_READY, log_path)
        _append_log(log_path, f"切换到主窗口（真实 UI）：http://127.0.0.1:{port}")
        main.show()  # 先亮主窗口：此刻起至少有一个窗口在，销毁 splash 不会触发 GUI 循环退出
        # 首屏**真口径**：用 pywebview 的 `loaded` 事件（页面渲染完成 = 首屏可用）。注册必须在
        # `load_url` **之前**——`load_url` 内部会 `events.loaded.clear()`，注册晚了就收不到。
        # 此处已在 `webview.start()` 调度的事件循环**之内**（P0 约束：循环启动前碰窗口/事件会被
        # marshal 到未运行的线程 ⇒ 永久阻塞，故不得挪到 start 之前）；`health_200` 只是"服务就绪"
        # 的代理口径，不能冒充首屏。已过 `await_ready` ⇒ 主窗口初始 splash-html 的 loaded 早已触发，
        # 此处注册只捕获后续 `load_url` 的真实 UI 渲染完成。
        main.events.loaded += lambda: _append_log(log_path, "真实 UI 已加载（首屏可用）。")
        main.load_url(f"http://127.0.0.1:{port}")  # 再把真实 UI 载入主窗口（非 splash）
        _destroy_window(splash, log_path)  # 最后收掉 splash（实例非空 ⇒ 不触发 Application.Exit）
        _append_log(log_path, "已切换到主窗口，splash 已关闭。")
    except Exception as exc:
        # 后台线程里的异常若不接住，线程会**静默死亡**（又回到"窗口不出、零线索"）；必须留痕并收尾。
        _append_log(log_path, f"就绪/切 UI 阶段异常：{exc!r}")
        result[0] = 1
        _abort_windows(splash, main, coordinator, log_path)


def _show_window(server: Any, thread: threading.Thread, port: int, log_path: str) -> int:
    """建 splash + 主窗口 → 起托盘 → 进主线程事件循环；就绪等待与切 UI 交给 `_after_start`。

    两个窗口（方案 A）：splash 无边框置顶小窗（启动反馈）；主窗口是**普通可缩放窗口**（有标题栏、
    可最大化/还原/拖边、不置顶、初始隐藏）。就绪后由 `_after_start` 亮主窗口并销毁 splash。

    时序是本次 P0 死锁的核心：先 `create_window`，再 **`webview.start(_after_start, ...)` 把事件循环
    跑起来**，最后让 `_after_start` 在循环内做 `_set_splash_stage` / `await_ready` / `show` / `load_url`。
    """
    import webview  # 惰性：GUI 依赖不得进模块顶层（CI 无 GUI 时 import desktop 不能炸）

    coordinator = QuitCoordinator()
    splash = webview.create_window(
        MAIN_WINDOW_TITLE,
        html=_splash_html(SPLASH_LOADING_MODEL),
        width=SPLASH_WIDTH,
        height=SPLASH_HEIGHT,
        frameless=True,
        on_top=True,
    )
    if splash is None:
        # pywebview 理论上不返回 None；真出现说明环境异常，必须**可见地**失败而非崩在下一行
        # （此处收窄也让 mypy 通过，无需 type: ignore）。
        _append_log(log_path, "webview.create_window 返回 None：无法创建桌面窗口。")
        _message_box("DeLector 启动失败", "无法创建桌面窗口，详情见 launch.log。")
        return 1
    _append_log(log_path, "已创建 splash 窗口。")

    main = webview.create_window(
        MAIN_WINDOW_TITLE,
        html=_splash_html(SPLASH_READY),
        width=MAIN_WINDOW_WIDTH,
        height=MAIN_WINDOW_HEIGHT,
        min_size=MAIN_WINDOW_MIN_SIZE,
        frameless=False,  # 有标题栏 ⇒ 有最大化/还原按钮、可拖边（缺陷修复要点）
        on_top=False,  # 不得永远置顶（置顶是 splash 的刻意行为，不是 UI 该有的）
        hidden=True,  # 就绪前不显示（否则用户会看到空窗）
    )
    if main is None:
        # 同 splash 分支：原生窗口要到 `webview.start()` 才建，此处直接返回即可（进程随 run_desktop
        # 返回退出，无残留窗口）。**不得**在此调 destroy —— 任何窗口操作都必须在 start 之后（P0 约束）。
        _append_log(log_path, "webview.create_window 返回 None（主窗口）：无法创建桌面窗口。")
        _message_box("DeLector 启动失败", "无法创建桌面窗口，详情见 launch.log。")
        return 1
    _append_log(log_path, "已创建主窗口（普通可缩放窗口，就绪后显示）。")

    # 退出语义重钉：主窗口关闭 = 用户显式退出 ⇒ 接统一收尸触发器；若 splash 仍在则一并销毁
    # （否则 GUI 循环在最后一个窗口关闭前不会返回）。splash 无法被用户关闭（无边框无控件，仅程序销毁），
    # 故不为它接线 closed —— 那只会让"退出标记"被程序性销毁误触发。
    main.events.closed += lambda: _on_main_closed(splash, coordinator, log_path)
    _start_tray(main, coordinator, log_path)
    _append_log(log_path, "托盘线程已启动。")

    result: List[int] = [0]  # 由 _after_start（后台线程）写回：失败=1，成功保持 0
    _append_log(log_path, "进入 GUI 事件循环（webview.start）。")
    webview.start(_after_start, (splash, main, coordinator, port, log_path, result))  # 阻塞直到所有窗口关闭
    _append_log(log_path, "GUI 事件循环已退出（窗口已关闭）。")
    return result[0]


def _check_port_or_fail(port: int, log_path: str) -> bool:
    """桌面建服**之前**的端口/身份校验（P0-1：防旧实例冒充新构建）。

    缺陷背景：此前直接 `build_server` + `serve_in_thread`，没有任何校验。uvicorn
    绑定失败走 `sys.exit` ⇒ 被 `threading.excepthook` 静默忽略 ⇒ server 线程真死；
    而 `await_ready` 对**旧实例**照样返回 200+身份 ⇒ 照常亮主窗口 ⇒ 用户以为升级了，
    实际是旧进程在服务。三分支：
    - 端口空闲 ⇒ True，正常继续；
    - 被占且身份是 DeLector ⇒ 弹窗 + 日志 + False（拒绝启动）。**刻意不做**"连过去"
      的窗口复用——那会把复杂度带回 P0 时序雷区，拒绝启动是诚实且最简单的处理；
    - 被占但不是 DeLector ⇒ 弹窗 + 日志 + False。
    所有失败路径必须**弹窗 + 日志**（调用方据此非零退出），不许只写日志。
    """
    # 惰性 import：复用 start.py 的既有判定与 server_lifecycle 的既有身份探测，
    # 不另写一套（两处判法一旦漂移，桌面端与 `--server-only` 就会对同一端口给出不同结论）。
    import start
    from delector.core.server_lifecycle import probe_identity

    if not start.is_port_in_use(port):
        return True
    if probe_identity(port):
        _append_log(
            log_path, f"端口 {port} 已有 DeLector 在运行：拒绝启动（防旧实例冒充新构建）。"
        )
        _message_box(
            "DeLector 已在运行",
            f"已有 DeLector 在运行（端口 {port}）。若要使用新版本，请先退出旧实例。",
        )
        return False
    _append_log(log_path, f"端口 {port} 被其他程序占用：拒绝启动。")
    _message_box(
        "端口被占用",
        f"端口 {port} 被其他程序占用，DeLector 无法启动。请关闭占用该端口的程序后重试。",
    )
    return False


def _run_desktop_inner(port: int, log_path: str) -> int:
    """桌面壳主体：端口/身份校验 → 检测运行时 → 定数据落点 → 起服务 → 起窗口；**任何**路径都先收尸。"""
    # P0-1：建服**最早处**先校验端口/身份（要早、要响、要简单）。
    # 校验失败 ⇒ 已弹窗 + 已落日志 ⇒ 退出码 3（2 已被"缺 WebView2"占用）。
    if not _check_port_or_fail(port, log_path):
        return 3
    _append_log(log_path, "端口与身份校验通过。")

    if not ensure_webview2_runtime():
        _append_log(log_path, "未检测到 WebView2 运行时：提示安装并退出。")
        _message_box("缺少 WebView2 运行时", webview2_missing_message())
        return 2
    _append_log(log_path, "WebView2 运行时检测通过。")

    # ⚠️ 必须在 `from delector.server import app` **之前**：那一行一跑，`database` 已按仓库根把
    # DATA_DIR 落定，之后再设 DELECTOR_DATA_DIR 就晚了（与 start.py 同款接线）。
    bootstrap_data_dir(os.environ)
    _append_log(log_path, "数据目录落点已定（bootstrap_data_dir 已返回，不代表迁移已落稳）。")
    # 桌面态 LAN 可用时同样落一份地址（托盘「显示局域网地址」读它；--windowed 无控制台）。
    # 放在 bootstrap 之后：env 里的数据目录落点已定，文件与库、launch.log 同处一地。
    write_lan_address(port, os.environ, log_path)

    from delector.server import app
    _append_log(log_path, "服务端模块已导入（delector.server）。")

    server = build_server(BIND_HOST, port, app)
    _append_log(log_path, "HTTP 服务已装配（build_server 完成）。")
    thread = serve_in_thread(server)
    _append_log(log_path, "本地服务线程已启动（等在就绪窗口内命中）。")
    try:
        return _show_window(server, thread, port, log_path)
    finally:
        # 关窗 / 异常 / Ctrl+C 全部经此收尸（与托盘「退出」同一路径），绝不留残留服务。
        coordinated_shutdown(server, thread, log_path)


def run_desktop(port: int = DEFAULT_PORT, debug_console: bool = False) -> int:
    """启动桌面壳：返回**进程退出码**。

    **所有**退出路径（关窗 / 托盘退出 / 异常 / Ctrl+C）都会先 `shutdown(server, thread)`：
    干净退出返回 0；就绪超时返回 1；缺 WebView2 返回 2；端口被占（DeLector 或其他程序）
    返回 3（建服前的端口/身份校验，见 `_check_port_or_fail`）；收尸超时则经
    `coordinated_shutdown` 硬退出（`os._exit(1)`），不留残留进程。
    """
    log_path = resolve_log_path(os.environ)
    # 先滚动过大日志（若有）再重定向/追加 —— 必须在 `_redirect_std_streams` 打开两个追加句柄
    # **之前**（Windows 上对已打开文件 `os.replace` 会失败）；只保守一份旧档，不改行格式。
    rotate_log_if_needed(log_path)
    _redirect_std_streams(log_path, debug_console)
    # 进程级计时起点：让 launch.log 能**独立**算出"端到端"耗时（起点 → 服务就绪 / 起点 → 首屏）。
    # 放在**最早处**（日志流一就绪）——晚于此处就漏掉"服务启动前"的进程开销，端到端就少算一截。
    _append_log(log_path, "开始启动（进程级计时起点）。")
    # 紧接着补一行"自进程创建"的毫秒数：起点之前的解释器启动 / 本模块模块级 import / 打包
    # bootstrap 都在本行之前发生，只有问 OS 要进程创建时刻才测得到（见 `_ms_since_process_create`）。
    _log_prestart_elapsed(log_path)
    # AppUserModelID 必须在**建窗之前**设置（任务栏按钮在首个窗口出现时定身份，晚设不生效）；
    # 仅 win32、绝不抛、失败落 launch.log（范式同 _allocate_debug_console）。
    _set_app_user_model_id(log_path)
    try:
        return _run_desktop_inner(port, log_path)
    except KeyboardInterrupt:
        _append_log(log_path, "收到 Ctrl+C：退出（服务已收尸）。")
        return 0
    except Exception:
        write_crash("DeLector 启动失败", traceback.format_exc(), log_path)
        return 1


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """解析命令行：端口、仅服务模式与调试控制台（`--help` 由 argparse 处理）。"""
    parser = argparse.ArgumentParser(
        prog="desktop.py",
        description="DeLector Windows 桌面壳（pywebview 窗口 + pystray 托盘，ADR-0020）。",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"本地服务端口（默认 {DEFAULT_PORT}）")
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="仅启动本地服务（无桌面窗口），保留同 Wi-Fi 手机/平板可访问的既有工作流",
    )
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="调试时挂回控制台，不把缺失的标准流收口到 launch.log",
    )
    return parser.parse_args(argv)


def run_server_only(debug_console: bool = False) -> int:
    """`--server-only`：委托 `start.main()` 的**既有行为**（无窗口、绑 0.0.0.0、开浏览器）。

    为什么复用而不是另写一套：这条路径要精确保留便携版原来的启动语义（含端口占用时的
    身份校验、LAN 访问、`bootstrap_data_dir` 顺序），复用是唯一能保证"不漂移"的做法。
    """
    import start

    if debug_console:
        start.main(debug_console=True)
    else:
        start.main()
    return 0


def dispatch(server_only: bool, port: int, debug_console: bool = False) -> int:
    """入口分派（可测的纯接线）：`--server-only` ⇒ 既有服务；否则 ⇒ 桌面窗口。

    ⚠️ `--server-only` **复用** `start.main()`（固定端口，见 `run_server_only` 的理由）：该路径
    不接受 `--port`。用户若在此组合下显式给了非默认端口，必须**显式告知**它不生效 —— 静默丢弃会被
    误读成"端口没换成功"，正是本任务要消除的一类静默失败（不动 `start.main()` 签名是为了不引入
    port-identity / LAN 面回归）。
    """
    if not server_only:
        if debug_console:
            return run_desktop(port, debug_console=True)
        return run_desktop(port)

    # server-only 的警告发生在 start.main() 之前，故本入口必须先自行收口标准流。
    log_path = resolve_log_path(os.environ)
    rotate_log_if_needed(log_path)
    ensure_streams(log_path, debug_console)
    # 守卫式压平（最大缩进 2 层）：下面这条警告是"不静默"的落点，理由见上方 docstring。
    if port != DEFAULT_PORT:
        print(
            f"[警告] --server-only 复用既有服务，固定端口 {DEFAULT_PORT}："
            f"你传入的 --port {port} 不会生效。",
            file=sys.stderr,
        )
    # 地址出口：无控制台（--windowed）时用户唯一能拿到 `http://<LAN_IP>:<port>` 的地方。
    # 端口用 DEFAULT_PORT —— 该路径固定 8000，`--port` 不生效（见上方警告）。
    write_lan_address(DEFAULT_PORT, os.environ, log_path)
    if debug_console:
        return run_server_only(debug_console=True)
    return run_server_only()


if __name__ == "__main__":
    _args = _parse_args(sys.argv[1:])
    raise SystemExit(dispatch(_args.server_only, _args.port, _args.debug_console))
