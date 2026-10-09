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


def main():
    port = 8000
    android = is_android()
    if is_port_in_use(port):
        print(f"[提示] 端口 {port} 正在运行中或已被占用，正在尝试连接已有服务...")
        if not android:
            open_browser(port)
        return

    # ⚠️ 必须在 `import uvicorn` / `from delector.server import app` **之前**执行：那两行一跑，
    # `database` 已按仓库根把 DATA_DIR 落定，此时再设 DELECTOR_DATA_DIR 就晚了。
    # 放在端口占用早退**之后**是刻意的：已有实例在跑时不动它的库（Windows 上改名会被占用挡住）。
    bootstrap_data_dir(os.environ)

    host = get_bind_host()
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    if android:
        print(f"  ● 仅本机监听: http://127.0.0.1:{port} (应用内 WebView)")
    else:
        print(f"  ● 电脑本机访问: http://localhost:{port}")
        ip = get_local_ip()
        if ip != "127.0.0.1":
            print(f"  ● 手机/平板访问: http://{ip}:{port} (同一 Wi-Fi 局域网)")
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")

    if not android:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    import uvicorn

    from delector.server import app

    config = uvicorn.Config(app, host=host, port=port, reload=False, log_level="info")
    server = uvicorn.Server(config)
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
    server.run()


if __name__ == "__main__":
    main()
