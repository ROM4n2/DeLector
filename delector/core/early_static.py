# -*- coding: utf-8 -*-
"""桌面壳的「先起静态、后交后端」最小静态层（ADR-0033 B2）。

为什么需要它：桌面主窗口的页面与静态资源原本由同一个 uvicorn 进程提供，而 uvicorn 在本机
冷启要 ~5.5s 才开始 accept（实测）；WebView2 在 ~3.4s 就能承载文档。只把 `load_url` 提前会
撞上连接拒绝页（白屏），拿不到任何首帧收益。本模块用 stdlib 在**同一端口、同一 origin** 先
把 `static/` 服务起来，页面立刻可绘制；随后 `desktop.py` 关掉它、让 uvicorn 接管同一端口，
`/api/*` 在交接窗口内返回 503，由 ADR-0032 的退避重试自然兜住。

边界：
- 只服务 GET/HEAD 的静态文件；`/api/*` 一律 503（不代理、不缓存、不碰业务）。
- 存储/origin 不变（仍是 `http://127.0.0.1:<port>`），`localStorage` 与 ADR-0032 快照不迁移。
- 交接用 `hand_off()`：停 accept 但**保持监听 socket**，交给 uvicorn 复用（`server.run(sockets=...)`）。
  `stop()` 只用于放弃交接（找不到后端 / 启动失败）；关 socket 再重新 bind 会留下 ECONNREFUSED
  空窗，交接期内的子资源请求会因此失败（实测早加载样本复现过）。

本模块刻意**只依赖 stdlib**：它必须在 `import delector.server`（1.1s+）之前就能工作。
"""

from __future__ import annotations

import json
import os
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, BinaryIO, Optional
from urllib.parse import unquote, urlsplit

__all__ = ["EarlyStaticServer", "resolve_static_dir", "start"]

#: 早期静态层只认这些扩展名的 MIME（Windows 注册表会把 .js 映射成 text/plain，module script
#: 会因此拒绝执行 —— 必须显式覆盖，不能信 `mimetypes` 的机器相关结果）。
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".txt": "text/plain; charset=utf-8",
}


def resolve_static_dir(data_dir: Optional[str] = None) -> Optional[str]:
    """找出静态资源目录；顺序与 `delector.server.STATIC_DIR` 对齐，但**不 import server**。

    候选：`STATIC_DIR` 环境变量 → `<数据目录>/static` → 仓库/安装目录 `static` → 当前目录
    `static`。找不到返回 None（调用方退回「等就绪」旧路径，不硬失败）。
    """
    explicit = os.environ.get("STATIC_DIR")
    if explicit and os.path.isdir(explicit):
        return explicit
    if data_dir is None:
        data_dir = os.environ.get("DELECTOR_DATA_DIR") or ""
    candidates = []
    if data_dir:
        candidates.append(os.path.join(data_dir, "static"))
    # 本文件在 delector/core/ 下 ⇒ 上两级即仓库根（打包后同样是程序目录旁的 static/）
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static"))
    candidates.append(os.path.join(os.getcwd(), "static"))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return None


class _Handler(SimpleHTTPRequestHandler):
    """静态白名单 + `/api/*` 503。禁止目录列表，禁止路径穿越（基类 translate_path 已处理）。"""

    server_version = "DeLectorEarlyStatic/1.0"

    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    # 显式 MIME：扩展名表优先，未知扩展回退基类（仍可能是机器相关，但首屏资源已全部覆盖）
    def guess_type(self, path: str) -> str:  # type: ignore[override]
        ext = os.path.splitext(path)[1].lower()
        if ext in _MIME:
            return _MIME[ext]
        return super().guess_type(path)

    def _is_api(self) -> bool:
        return unquote(urlsplit(self.path).path).startswith("/api/")

    def _service_unavailable(self) -> None:
        body = json.dumps({"app": "delector", "detail": "starting"}, ensure_ascii=False).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib 命名)
        if self._is_api():
            self._service_unavailable()
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._is_api():
            self._service_unavailable()
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802
        self._service_unavailable()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def list_directory(self, path: str) -> Optional[BinaryIO]:  # type: ignore[override]
        # 不暴露目录列表：目录请求只允许落到 index.html（基类会优先找 index）
        self.send_error(404, "Not Found")
        return None

    def log_message(self, fmt: str, *args: Any) -> None:
        # 早期静态层不写访问日志（uvicorn 接管后才有正式日志），避免污染 launch.log
        return


class EarlyStaticServer:
    """线程内运行的最小静态服务；交接给 uvicorn 用 `hand_off()`，放弃交接用 `stop()`。"""

    def __init__(self, httpd: ThreadingHTTPServer):
        self._httpd = httpd
        # 0.1s 轮询：`shutdown()` 最多等一个轮询周期，交接越短，页面请求越少落在空档里。
        self._thread = threading.Thread(
            target=lambda: httpd.serve_forever(poll_interval=0.1),
            name="delector-early-static",
            daemon=True,
        )
        self.port = int(httpd.server_address[1])

    def start(self) -> "EarlyStaticServer":
        self._thread.start()
        return self

    def hand_off(self) -> Optional[socket.socket]:
        """停掉 accept 循环但**不关闭**监听 socket，返回它交给 uvicorn 复用。

        为什么不能 `stop()` 后让 uvicorn 重新 bind：`stop()` 关 socket 到 uvicorn 完成
        bind 之间有 ~1s 空窗，此时页面新发起的子资源/API 连接会被内核直接拒绝
        （ECONNREFUSED），module script 加载失败 ⇒ 页面 boot 中断、真实行永不出现。
        保持 socket 监听则 backlog 里的连接由 uvicorn 接手，不存在拒绝窗口。

        已 accepted 的连接仍由本层 daemon 线程服务完（只读静态文件，无副作用）。
        线程未能在宽限内退出时退回 `stop()` 并返回 None（调用方走「重新 bind」旧路径）。
        """
        try:
            self._httpd.shutdown()
        # silent-ok: 已关闭的 server 重复 shutdown 抛异常等价于「已停止」，交接继续
        except Exception:
            pass
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            self.stop()
            return None
        sock = self._httpd.socket
        # 从 server 上摘下 socket（置 None），`server_close()` 才不会把它关掉。
        self._httpd.socket = None  # type: ignore[assignment]
        self._httpd.server_close()
        return sock

    def stop(self) -> None:
        try:
            self._httpd.shutdown()
        finally:
            self._httpd.server_close()
        self._thread.join(timeout=5)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_close(self) -> None:
        # `hand_off()` 会把监听 socket 摘下（置 None）交给 uvicorn；此时不能再关它。
        if self.socket is None:
            return
        super().server_close()


def start(host: str, port: int, static_dir: Optional[str] = None) -> Optional[EarlyStaticServer]:
    """起静态层；找不到静态目录或绑定失败返回 None（调用方退回等就绪路径）。"""
    directory = static_dir or resolve_static_dir()
    if not directory:
        return None
    try:
        httpd = _Server((host, port), lambda *a, **kw: _Handler(*a, directory=directory, **kw))
        return EarlyStaticServer(httpd).start()
    except OSError:
        return None
