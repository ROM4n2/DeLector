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

# 就绪窗口给足：首启 health_200 ≈ 2.6s，其中 spaCy 模型加载 ≈ 1.47s（ADR-0018 §7.3）⇒ 冷启动
# 首次建档更慢。取 60s 兜底，宁慢勿"静默判未就绪"。
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

# ── splash 分阶段文案（启动反馈：ADR-0020 §4 前置②）──────────────────────────
SPLASH_LOADING_MODEL = "正在加载德语模型…"
SPLASH_STARTING_SERVER = "正在启动服务…"
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


def _set_splash_stage(window: Any, stage: str) -> None:
    """把 splash 阶段文案推进一格（失败不影响主流程）。"""
    try:
        window.evaluate_js(f"document.getElementById('stage').textContent = {stage!r}")
    except Exception:
        pass


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


def _show_window(server: Any, thread: threading.Thread, port: int, log_path: str) -> int:
    """建 splash → 等就绪（分阶段反馈）→ 切真实 UI → 进主线程事件循环。"""
    import webview  # 惰性：GUI 依赖不得进模块顶层（CI 无 GUI 时 import desktop 不能炸）

    coordinator = QuitCoordinator()
    splash = webview.create_window(
        "DeLector",
        html=_splash_html(SPLASH_LOADING_MODEL),
        width=430,
        height=270,
        frameless=True,
        on_top=True,
    )
    if splash is None:
        # pywebview 理论上不返回 None；真出现说明环境异常，必须**可见地**失败而非崩在下一行
        # （此处收窄也让 mypy 通过，无需 type: ignore）。
        _append_log(log_path, "webview.create_window 返回 None：无法创建桌面窗口。")
        _message_box("DeLector 启动失败", "无法创建桌面窗口，详情见 launch.log。")
        return 1
    splash.events.closed += lambda: coordinator.request_quit()  # 关窗 = 请求退出（与托盘同一路径）
    _start_tray(splash, coordinator, log_path)

    _set_splash_stage(splash, SPLASH_STARTING_SERVER)
    if not await_ready(port, deadline_s=READY_DEADLINE_S):
        # 就绪失败必须**可见**：弹窗 + 日志，绝不静默卡在 splash。
        _append_log(log_path, "服务在就绪窗口内未就绪：提示用户并退出。")
        _message_box("DeLector 启动超时", f"本地服务在 {READY_DEADLINE_S:.0f}s 内未就绪，详情见 launch.log。")
        coordinator.request_quit()
        return 1
    _set_splash_stage(splash, SPLASH_READY)
    splash.load_url(f"http://127.0.0.1:{port}")

    webview.start()  # 阻塞**主线程**，直到窗口关闭（GUI 事件循环必须占主线程）
    return 0


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
