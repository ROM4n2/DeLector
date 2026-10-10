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

# ── 托盘菜单（打开 / 检查更新 / 退出）；action 键供实现映射到处理函数 ──────────
TRAY_MENU_SPEC: Tuple[Tuple[str, str], ...] = (
    ("打开", "open"),
    ("检查更新", "check_update"),
    ("退出", "quit"),
)


# ── 日志：落数据目录 + 显式文件句柄（--windowed 下 sys.stdout 可能为 None）────
def resolve_log_path(env: Mapping[str, str]) -> str:
    """日志落点 = Task 1 的数据目录 + `launch.log`（与库、备份同处一地，覆盖安装不丢）。"""
    return os.path.join(resolve_data_dir(env), LOG_FILE_NAME)


def open_log_streams(log_path: str) -> Tuple[TextIO, TextIO]:
    """打开 stdout/stderr 的追加流。

    `--windowed` 形态下 `sys.stdout` / `sys.stderr` 可能为 `None`（无控制台），故**必须显式开
    文件句柄**，不能依赖 `print` 到默认流。
    """
    out = open(log_path, "a", encoding="utf-8", buffering=1)
    err = open(log_path, "a", encoding="utf-8", buffering=1)
    return out, err


def _append_log(log_path: str, message: str) -> None:
    """追加一行带时间戳的日志。**绝不抛**：日志写不进去不能让调用方跟着崩。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        # 日志不可写是"最没得治"的环境问题；此处只静默放弃（调用方可能正在崩溃处理中）。
        pass


def _redirect_std_streams(log_path: str) -> None:
    """把 stdout/stderr 重定向到 `launch.log`。失败只降级、不阻止启动（看不到日志好过起不来）。"""
    try:
        out, err = open_log_streams(log_path)
    except OSError:
        return
    sys.stdout = out
    sys.stderr = err


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


def _run_desktop_inner(port: int, log_path: str) -> int:
    """桌面壳主体：检测运行时 → 定数据落点 → 起服务 → 起窗口；**任何**路径都先收尸。"""
    if not ensure_webview2_runtime():
        _append_log(log_path, "未检测到 WebView2 运行时：提示安装并退出。")
        _message_box("缺少 WebView2 运行时", webview2_missing_message())
        return 2

    # ⚠️ 必须在 `from delector.server import app` **之前**：那一行一跑，`database` 已按仓库根把
    # DATA_DIR 落定，之后再设 DELECTOR_DATA_DIR 就晚了（与 start.py 同款接线）。
    bootstrap_data_dir(os.environ)

    from delector.server import app

    server = build_server(BIND_HOST, port, app)
    thread = serve_in_thread(server)
    try:
        return _show_window(server, thread, port, log_path)
    finally:
        # 关窗 / 异常 / Ctrl+C 全部经此收尸（与托盘「退出」同一路径），绝不留残留服务。
        coordinated_shutdown(server, thread, log_path)


def run_desktop(port: int = DEFAULT_PORT) -> int:
    """启动桌面壳：返回**进程退出码**。

    **所有**退出路径（关窗 / 托盘退出 / 异常 / Ctrl+C）都会先 `shutdown(server, thread)`：
    干净退出返回 0；就绪超时返回 1；缺 WebView2 返回 2；收尸超时则经 `coordinated_shutdown`
    硬退出（`os._exit(1)`），不留残留进程。
    """
    log_path = resolve_log_path(os.environ)
    _redirect_std_streams(log_path)
    try:
        return _run_desktop_inner(port, log_path)
    except KeyboardInterrupt:
        _append_log(log_path, "收到 Ctrl+C：退出（服务已收尸）。")
        return 0
    except Exception:
        write_crash("DeLector 启动失败", traceback.format_exc(), log_path)
        return 1


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """解析命令行：`--port` 与 `--server-only`（`--help` 由 argparse 处理）。"""
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
    return parser.parse_args(argv)


def run_server_only() -> int:
    """`--server-only`：委托 `start.main()` 的**既有行为**（无窗口、绑 0.0.0.0、开浏览器）。

    为什么复用而不是另写一套：这条路径要精确保留便携版原来的启动语义（含端口占用时的
    身份校验、LAN 访问、`bootstrap_data_dir` 顺序），复用是唯一能保证"不漂移"的做法。
    """
    import start

    start.main()
    return 0


def dispatch(server_only: bool, port: int) -> int:
    """入口分派（可测的纯接线）：`--server-only` ⇒ 既有服务；否则 ⇒ 桌面窗口。

    ⚠️ `--server-only` **复用** `start.main()`（固定端口，见 `run_server_only` 的理由）：该路径
    不接受 `--port`。用户若在此组合下显式给了非默认端口，必须**显式告知**它不生效 —— 静默丢弃会被
    误读成"端口没换成功"，正是本任务要消除的一类静默失败（不动 `start.main()` 签名是为了不引入
    port-identity / LAN 面回归）。
    """
    if not server_only:
        return run_desktop(port)
    # 守卫式压平（最大缩进 2 层）：下面这条警告是"不静默"的落点，理由见上方 docstring。
    if port != DEFAULT_PORT:
        print(
            f"[警告] --server-only 复用既有服务，固定端口 {DEFAULT_PORT}："
            f"你传入的 --port {port} 不会生效。",
            file=sys.stderr,
        )
    return run_server_only()


if __name__ == "__main__":
    _args = _parse_args(sys.argv[1:])
    raise SystemExit(dispatch(_args.server_only, _args.port))
