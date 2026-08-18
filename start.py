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

def open_browser(port: int):
    time.sleep(1.2)
    # Support Android Termux termux-open-url fallback
    if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
        os.system(f"termux-open-url http://localhost:{port}")
    else:
        webbrowser.open(f"http://127.0.0.1:{port}")

def main():
    port = 8000
    if is_port_in_use(port):
        print(f"[提示] 端口 {port} 正在运行中或已被占用，正在尝试连接已有服务...")
        open_browser(port)
        return

    ip = get_local_ip()
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    print(f"  ● 电脑本机访问: http://localhost:{port}")
    if ip != "127.0.0.1":
        print(f"  ● 手机/平板访问: http://{ip}:{port} (同一 Wi-Fi 局域网)")
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
