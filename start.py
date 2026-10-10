#!/usr/bin/env python3
"""
DeLector - Cross-Platform Instant Launcher
Auto-detects port availability, LAN IP, and launches default browser.
"""

import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import nullcontext

# 为什么必须在最顶部就把 stdout/stderr 重配成 utf-8（本仓既有写法，见 package_windows.py 顶部）：
# 下面那条启动横幅用 print() 打中文，而**被重定向到文件的 stdout 在 Windows 上默认按 locale/ANSI
# 编码打开**（CI runner 上是 cp1252，本机是 GBK）⇒ 打中文直接抛 UnicodeEncodeError ⇒ 进程退出 1。
# 而"输出被重定向 / 被日志采集 / 由服务或计划任务拉起"正是"当服务用"最常见的环境 —— 不加固等于
# 这些场景下根本起不来（`DeLector.exe --server-only` 启动即崩，实测原始报错 position 13-28 即标题行汉字）。
# 先判 `sys.stdout`/`sys.stderr` 是否为 None（--windowed 冻结后可能为 None）；errors="replace" 保证
# 即便重配失败也不会因一个字符崩掉整个进程。
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 数据落点必须在 `import server` **之前**定下来：`delector.core.database` 在被 import 的
# 那一瞬就按"当时的 env"算出 DATA_DIR，之后再设 DELECTOR_DATA_DIR 毫无作用 —— 于是数据
# 仍落在程序目录里，用户"解压新版覆盖旧目录 / 删掉旧目录"= 学习记录全空且零提示
# （ADR-0019 Q2-A / Q3-B）。真正的调用在 `main()` 开头的第一个语句处（见那里的注释）。
from delector.core.data_dir_bootstrap import bootstrap_data_dir


def _noop_signal_context(*_args, **_kwargs):
    """空 context manager：替代 uvicorn 的 capture_signals（Android 子线程禁信号用）。"""
    return nullcontext()


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_android() -> bool:
    """是否跑在 Chaquopy/Android 运行时里。"""
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ


def get_bind_host() -> str:
    """桌面端绑 0.0.0.0 是有意的特性（同 Wi-Fi 的手机/平板可访问）。

    Android 上只有应用内的 WebView 需要连本机，绑 0.0.0.0 等于把无鉴权的
    POST /api/settings（可改写 API Key 与 base_url）暴露给整个局域网。
    """
    return "127.0.0.1" if is_android() else "0.0.0.0"


def open_browser(port: int):
    time.sleep(1.2)
    # Support Android Termux termux-open-url fallback
    if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
        os.system(f"termux-open-url http://localhost:{port}")
    else:
        webbrowser.open(f"http://127.0.0.1:{port}")


def _address_lines(port: int, android: bool) -> list[str]:
    """横幅里的地址行（Android 只监听回环、桌面端还会给出局域网地址，故两者文案不同）。"""
    if android:
        return [f"  ● 仅本机监听: http://127.0.0.1:{port} (应用内 WebView)"]
    lines = [f"  ● 电脑本机访问: http://localhost:{port}"]
    ip = get_local_ip()
    if ip != "127.0.0.1":
        lines.append(f"  ● 手机/平板访问: http://{ip}:{port} (同一 Wi-Fi 局域网)")
    return lines


def print_banner(port: int, android: bool) -> None:
    """打印启动横幅（含中文）。

    为什么抽成独立函数：这是"重定向流下打中文会崩"那条缺陷的落点，抽出来后回归锁可在真子进程里
    直接调用它、精确复现"敌意流"（见 tests/test_start_banner_encoding.py），不必真起服务。
    """
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    for line in _address_lines(port, android):
        print(line)
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")


def main():
    port = 8000
    android = is_android()
    if is_port_in_use(port):
        # 不再盲复用：先分辨占用者是不是 DeLector 自己（ADR-0020 §6.4），否则会为
        # 一个无关程序打开页面。判定与动作封装在 _handle_existing_port（惰性 import）。
        _handle_existing_port(port, android)
        return

    # ⚠️ 必须在 `from delector.server import app` **之前**执行：那一行一跑，`database`
    # 已按仓库根把 DATA_DIR 落定，此时再设 DELECTOR_DATA_DIR 就晚了。
    # 放在端口占用早退**之后**是刻意的：已有实例在跑时不动它的库（Windows 上改名会被占用挡住）。
    bootstrap_data_dir(os.environ)

    host = get_bind_host()
    print_banner(port, android)

    if not android:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    from delector.core.server_lifecycle import build_server, serve_in_thread, shutdown
    from delector.server import app

    server = build_server(host, port, app)
    try:
        # 禁用信号处理：Android Chaquopy 在子线程里跑 server，而 signal.signal 只允许
        # 在 Python 主线程调用。注意 uvicorn 的 API 随版本迁移（0.52 起只有
        # capture_signals，install_signal_handlers 已不存在）——两代都覆盖，
        # 否则「防护」会静默失效成一条没人调用的实例属性（mypy 抓到这个失效）。
        if threading.current_thread() is not threading.main_thread():
            server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]  # 旧 uvicorn API
            server.capture_signals = _noop_signal_context  # type: ignore[method-assign]  # 新 uvicorn API
    except Exception:
        pass
    # 非 daemon 线程里跑 server，主线程 join 等待；Ctrl+C 时先收尸再退出 —— 这替代了
    # 原来裸 `server.run()` 的「无退出控制」，消除「壳退了服务还残留」的静默失败。
    thread = serve_in_thread(server)
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\n[提示] 收到停止信号，正在收尸...")
    # join 之后再收一次是**有意保留**的兜底：覆盖 KeyboardInterrupt 之外的退出路径。
    # `shutdown` 是幂等的（置 should_exit + join 一个已结束的线程都无副作用），重复调用安全
    # —— 勿当成"重复 shutdown 的 bug"删除。
    shutdown(server, thread)
    print("[提示] 服务已停止。")


def _handle_existing_port(port: int, android: bool) -> None:
    """端口已被占用时的处理：先分辨占用者是不是 DeLector 自己，再决定动作。

    - 是 DeLector（`probe_identity` 为真，含库坏时的 503）⇒ 保持既有行为：提示 + 打开
      浏览器指向已有实例，然后返回（不重复起服务）。
    - 不是 DeLector ⇒ 明确报错并退出，**绝不**为无关程序打开页面（ADR-0020 §6.4）。

    这里用**惰性 import** 而非文件顶部导入：本函数定义在 main() 之后，其 import 语句
    的行号才大于 main() 里 `bootstrap_data_dir(...)` 的调用行号 —— 否则会撞上
    tests/test_desktop_data_dir_bootstrap.py::test_start_py_bootstrap_precedes_every_delector_import
    （那条闸钉「bootstrap 必须早于任何 delector.* 导入」，以保 DATA_DIR 在被冻结前定好）。
    """
    from delector.core.server_lifecycle import probe_identity

    if probe_identity(port):
        print(f"[提示] DeLector 已在端口 {port} 运行，正在打开已有页面...")
        if not android:
            open_browser(port)
        return
    print(f"[错误] 端口 {port} 已被其他程序占用，无法启动 DeLector。")
    print("       请关闭占用该端口的程序，或结束残留的 DeLector 进程后重试。")
    sys.exit(1)


if __name__ == "__main__":
    main()
