#!/usr/bin/env python3
"""
DeLector - Cross-Platform Instant Launcher
Auto-detects port availability, LAN IP, and launches default browser.
"""
import os
import sys
import socket
import webbrowser
import threading
import time

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

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
    from server import app
    config = uvicorn.Config(app, host=host, port=port, reload=False, log_level="info")
    server = uvicorn.Server(config)
    try:
        # Disable signals in sub-threads (Android Chaquopy)
        if threading.current_thread() is not threading.main_thread():
            server.install_signal_handlers = lambda: None
    except Exception:
        server.install_signal_handlers = lambda: None
    server.run()

if __name__ == "__main__":
    main()
