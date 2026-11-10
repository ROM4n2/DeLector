# -*- coding: utf-8 -*-
"""早期静态层（ADR-0033 B2）的最小机械闸：MIME、/api 503、端口可交接。"""

import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from delector.core import early_static


def _serve(directory: Path):
    server = early_static.start("127.0.0.1", 0, str(directory))
    assert server is not None
    return server


def _get(port: int, path: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def test_serves_index_and_module_js_with_correct_mime(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>DeLector</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("export const x = 1;", encoding="utf-8")
    (tmp_path / "style.css").write_text(":root{--x:1}", encoding="utf-8")
    server = _serve(tmp_path)
    try:
        status, ctype, body = _get(server.port, "/")
        assert status == 200 and "text/html" in ctype and b"DeLector" in body
        status, ctype, _ = _get(server.port, "/app.js")
        # Windows 注册表常把 .js 映射成 text/plain，module script 会拒绝执行
        assert status == 200 and ctype.startswith("text/javascript")
        status, ctype, _ = _get(server.port, "/style.css")
        assert status == 200 and ctype.startswith("text/css")
    finally:
        server.stop()


def test_api_is_503_while_backend_is_not_ready(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    server = _serve(tmp_path)
    try:
        status, ctype, body = _get(server.port, "/api/articles")
        assert status == 503
        assert "application/json" in ctype
        assert b"starting" in body
    finally:
        server.stop()


def test_stop_frees_the_port_for_the_backend(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    server = _serve(tmp_path)
    port = server.port
    server.stop()
    # uvicorn 要接管同一端口：静态层的监听 socket 必须真的释放
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


def test_hand_off_socket_is_still_listening_and_reused_by_uvicorn(tmp_path: Path):
    """闸：交接必须交出**仍处于 listen 状态**的 socket，且 uvicorn 能直接复用。

    这是「静态层停止 → uvicorn 重新 bind」空窗（交接期请求被拒 ⇒ 页面 boot 中断）的机械防线：
    一旦有人把 `hand_off()` 改回先 close 再 bind，这里会失败。
    """
    import time

    import uvicorn

    from delector.core.server_lifecycle import serve_in_thread, shutdown

    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    server = _serve(tmp_path)
    port = server.port
    sock = server.hand_off()
    assert sock is not None
    assert sock.getsockname()[1] == port
    assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1

    async def app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]}
        )
        await send({"type": "http.response.body", "body": b'{"app":"delector"}'})

    uv = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    thread = serve_in_thread(uv, [sock])
    body = b""
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                    body = resp.read()
                break
            except Exception:
                time.sleep(0.05)
        assert b'"delector"' in body
    finally:
        shutdown(uv, thread)
        sock.close()


def test_resolve_static_dir_prefers_explicit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    assert early_static.resolve_static_dir() == str(tmp_path)
