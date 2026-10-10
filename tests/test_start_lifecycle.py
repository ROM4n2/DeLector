# -*- coding: utf-8 -*-
"""Task 3（RED 先写）：uvicorn 生命周期可控化 + 端口复用身份校验。

钉住两类静默失败（ADR-0020 §4 前置① / §6.4）：
  * **退不干净**：server 线程必须非 daemon 且可 join；shutdown 超时必须如实返回 False。
  * **盲复用**：probe_identity 必须校验响应带 DeLector 身份，而不是「端口能连上就算」。

纪律：
  * 不钉绝对毫秒阈值（只钉关系与状态），避免慢机器/杀软导致的 flaky。
  * 真起 uvicorn（最小 FastAPI app）+ 动态空闲端口，绝不碰生产 8000。
"""

import socket
import threading
import time
from typing import Any, List, Tuple

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

import start
from delector.core.server_lifecycle import (
    await_ready,
    build_server,
    probe_identity,
    serve_in_thread,
    shutdown,
)

_HOST = "127.0.0.1"


# ── 测试脚手架：真起服务 / 探端口 ──────────────────────────────────────────────
def _free_port() -> int:
    """向系统要一个空闲端口（bind 0 再读回），避免并发测试互撞。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _port_connectable(port: int, timeout_s: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex((_HOST, port)) == 0


def _delector_ok_app() -> FastAPI:
    """真 DeLector 身份 + 库可用：/api/health 回 200 且带 app=delector。"""
    app = FastAPI()

    @app.get("/api/health")
    def health() -> Any:
        return {"status": "ok", "database": "ok", "app": "delector", "version": "test"}

    return app


def _delector_db_broken_app() -> FastAPI:
    """身份对但库坏：503 且仍带 app=delector（用来区分「是 DeLector」与「已就绪」）。"""
    app = FastAPI()

    @app.get("/api/health")
    def health() -> Any:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "detail": "本地数据库暂时不可用", "app": "delector"},
        )

    return app


def _impostor_json_app() -> FastAPI:
    """别的软件占着端口：能连上、也回 JSON，但没有 DeLector 身份字段。"""
    app = FastAPI()

    @app.get("/api/health")
    def health() -> Any:
        return {"status": "ok"}

    return app


def _impostor_plaintext_app() -> FastAPI:
    """非 JSON 响应：探针不得崩，应判为非 DeLector。"""
    app = FastAPI()

    @app.get("/api/health")
    def health() -> Any:
        return PlainTextResponse("hello from some other program")

    return app


def _launch_server(app: Any) -> Tuple[uvicorn.Server, threading.Thread, int]:
    """真起一个 uvicorn server（最小 app），等它就绪后返回 (server, thread, port)。"""
    port = _free_port()
    server = build_server(_HOST, port, app)
    thread = serve_in_thread(server)
    deadline = time.monotonic() + 20.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "测试前置：uvicorn 未能在窗口内启动"
    return server, thread, port


@pytest.fixture
def start_server():
    """返回一个 `launch(app)`；用例结束时统一收尸（含断言失败的路径）。"""
    started: List[Tuple[uvicorn.Server, threading.Thread]] = []

    def launch(app: Any) -> Tuple[uvicorn.Server, threading.Thread, int]:
        server, thread, port = _launch_server(app)
        started.append((server, thread))
        return server, thread, port

    yield launch

    for server, thread in started:
        shutdown(server, thread, grace_s=10.0)


# ── 生命周期：起服务 → shutdown → 线程结束 + 端口释放 ──────────────────────────
def test_serve_and_shutdown_are_controllable(start_server):
    server, thread, port = start_server(_delector_ok_app())

    assert thread.daemon is False, "server 线程必须非 daemon，否则 join 无意义（进程退出时被强杀）"
    assert thread.is_alive(), "起服务后线程应在运行"
    assert _port_connectable(port), "前置：服务确实在监听端口"

    ok = shutdown(server, thread, grace_s=10.0)

    assert ok is True, "正常退出应返回 True"
    assert thread.is_alive() is False, "shutdown 后线程必须已结束（这正是「退出收尸」要的）"
    assert _port_connectable(port) is False, "shutdown 后端口必须释放，否则下次启动会盲判被占用"


def test_shutdown_returns_false_when_thread_ignores_exit():
    """超时兜底：线程不响应退出请求时必须如实返回 False，绝不假装成功。"""

    class _StuckServer:
        should_exit = False

    blocker = threading.Event()
    thread = threading.Thread(target=blocker.wait, daemon=False)
    thread.start()
    try:
        ok = shutdown(_StuckServer(), thread, grace_s=0.2)
        assert thread.is_alive(), "前置：线程确实还活着（否则这条用例证明不了超时路径）"
        assert ok is False, "线程未在宽限期内结束 ⇒ shutdown 必须返回 False，不得假装成功"
    finally:
        blocker.set()
        thread.join(5.0)


# ── 身份校验：不能只探「端口能连上」 ──────────────────────────────────────────
def test_probe_identity_rejects_foreign_json_service(start_server):
    server, thread, port = start_server(_impostor_json_app())
    assert _port_connectable(port), "前置：假服务确实占用了端口（旧的 is_port_in_use 会误判可复用）"
    assert probe_identity(port, timeout_s=3.0) is False, (
        "端口被非 DeLector 程序占用（无身份字段）时必须 False，否则会静默打开无关页面"
    )


def test_probe_identity_false_on_non_json_service(start_server):
    server, thread, port = start_server(_impostor_plaintext_app())
    assert probe_identity(port, timeout_s=3.0) is False, "非 JSON 响应不得让探针崩，应判为非 DeLector"


def test_probe_identity_true_for_delector_with_broken_db(start_server):
    server, thread, port = start_server(_delector_db_broken_app())
    assert probe_identity(port, timeout_s=3.0) is True, (
        "503 但带 DeLector 身份 ⇒ probe_identity 视为「是 DeLector」（用于「已在运行」判定）"
    )
    assert await_ready(port, deadline_s=2.0) is False, (
        "await_ready 要求 200 且身份对 ⇒ 库坏时必须 False，不得静默判成就绪"
    )


def test_await_ready_true_for_healthy_delector(start_server):
    server, thread, port = start_server(_delector_ok_app())
    assert await_ready(port, deadline_s=15.0) is True, "健康 DeLector 必须被判为就绪"


def test_await_ready_false_when_nothing_on_port():
    port = _free_port()
    assert await_ready(port, deadline_s=1.0) is False, "端口无服务时必须返回 False（非静默）"


# ── start.main：端口被占时不再盲复用 ──────────────────────────────────────────
def test_main_exits_when_port_held_by_foreign_program(monkeypatch, capsys):
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr("delector.core.server_lifecycle.probe_identity", lambda *_a, **_k: False)
    monkeypatch.setattr(start, "open_browser", lambda _port: pytest.fail("不得为无关程序打开页面"))

    with pytest.raises(SystemExit):
        start.main()

    out = capsys.readouterr().out
    assert "8000" in out, f"报错必须点名端口，实际输出：{out!r}"
    # 否定断言：被**无关程序**占用时不得吐出「复用」语义文案（如「已在运行」）。只钉
    # "含 8000" 太弱 —— 误把陌生端口当成"已在运行"的文案照样过，恰好是本任务要消灭的盲复用。
    assert "已在" not in out, (
        f"无关程序占用端口时不得输出「复用/已在运行」文案，否则'陌生端口'被误报成'自己的实例'：{out!r}"
    )


def test_main_reuses_existing_delector_without_exiting(monkeypatch):
    opened: List[int] = []
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr("delector.core.server_lifecycle.probe_identity", lambda *_a, **_k: True)
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: opened.append(port))

    start.main()  # 识别为 DeLector：不得抛 SystemExit、不得起第二个服务

    assert opened == [8000], "识别为 DeLector 时应保持既有行为：打开浏览器指向已有服务"


def test_main_stops_server_on_keyboard_interrupt(monkeypatch):
    """main() 收到 Ctrl+C（KeyboardInterrupt）时 MUST 调 shutdown 收尸，而不是把线程晾着。

    这条把「退出收尸」从「起得来」推进到「停得下」：命中 join() 被中断的分支。
    用打桩替掉 server_lifecycle 的四个入口 + 假 `delector.server`，避免真拉服务与
    真拉 spaCy；断言的是**接线**（Ctrl+C ⇒ 调 shutdown 且收的是本次的 server）。
    """
    import sys
    import types

    from delector.core import server_lifecycle

    fake_server = types.SimpleNamespace(should_exit=False)

    class _InterruptOnJoin:
        daemon = False

        def join(self, *_args: Any, **_kwargs: Any) -> None:
            raise KeyboardInterrupt

        def is_alive(self) -> bool:
            return False

    recorded: List[Any] = []

    def _record_shutdown(server: Any, thread: Any, grace_s: float = 5.0) -> bool:
        recorded.append((server, thread, grace_s))
        return True

    monkeypatch.setattr(start, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(start, "is_android", lambda: True)  # 走回环、且不起浏览器线程
    monkeypatch.setattr(start, "bootstrap_data_dir", lambda *_a, **_k: "")
    monkeypatch.setattr(server_lifecycle, "build_server", lambda host, port, app: fake_server)
    monkeypatch.setattr(server_lifecycle, "serve_in_thread", lambda server: _InterruptOnJoin())
    monkeypatch.setattr(server_lifecycle, "shutdown", _record_shutdown)
    monkeypatch.setitem(sys.modules, "delector.server", types.SimpleNamespace(app=object()))

    start.main()  # 不得把 KeyboardInterrupt 冒出来（否则进程会以栈退出）

    assert recorded, "Ctrl+C 时必须调用 shutdown 收尸，否则服务线程会残留"
    assert recorded[0][0] is fake_server, "shutdown 收的必须是本次起的 server"


def test_main_covers_both_uvicorn_signal_apis_in_non_main_thread(monkeypatch):
    """非主线程启服务时（Android/Chaquopy），MUST 同时覆盖两代 uvicorn 信号 API。

    为什么两代都要覆盖：`signal.signal` 只允许在 Python **主线程**调用，故在子线程里跑 server
    必须把「安装信号处理器」整条关掉；而 uvicorn 的 API 随版本迁移（0.52 起只剩 `capture_signals`，
    旧的 `install_signal_handlers` 已不存在）。只覆盖其中一代 ⇒ 另一代照常调 `signal.signal`
    ⇒ 子线程里抛「signal only works in main thread」，把服务直接带崩。

    用替身 server 断言「两代入口都被装上」：这既钉住语义，也钉住「`setattr` 按名赋值」的写法
    （改回点属性访问会被 mypy 的 skip 口径判 unused-ignore，见 ci.yml 门禁）。
    """
    import sys
    import types

    from delector.core import server_lifecycle

    fake_server = types.SimpleNamespace(should_exit=False)

    class _AlreadyFinishedThread:
        """替身线程：join 立即返回、is_alive 恒 False（本用例只关心信号接线）。"""

        daemon = False

        def join(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(start, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(start, "is_android", lambda: True)  # 走回环、且不起浏览器线程
    monkeypatch.setattr(start, "bootstrap_data_dir", lambda *_a, **_k: "")
    monkeypatch.setattr(server_lifecycle, "build_server", lambda host, port, app: fake_server)
    monkeypatch.setattr(server_lifecycle, "serve_in_thread", lambda server: _AlreadyFinishedThread())
    monkeypatch.setattr(server_lifecycle, "shutdown", lambda *_a, **_k: True)
    monkeypatch.setitem(sys.modules, "delector.server", types.SimpleNamespace(app=object()))

    errors: List[Exception] = []

    def _run_main() -> None:
        try:
            start.main()
        except Exception as exc:  # 子线程里的异常需搬回主线程断言，否则会被静默吞掉
            errors.append(exc)

    # 必须在**非主线程**里跑 main()：信号禁用的分支只在子线程生效（这正是 Android 的处境）。
    worker = threading.Thread(target=_run_main, name="start-main-under-test")
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive(), "main() 在子线程里未在窗口内返回"
    assert not errors, f"main() 在子线程里抛异常：{errors!r}"

    # 旧代 API：装上的是空 no-op（可调用且返回 None）。
    assert hasattr(fake_server, "install_signal_handlers"), (
        "旧 uvicorn API install_signal_handlers 未被覆盖：老版本 uvicorn 会照常调 signal.signal，"
        "在子线程里直接崩"
    )
    assert fake_server.install_signal_handlers() is None, "旧代信号入口必须是空 no-op"
    # 新代 API：装上的正是模块级的空 context manager（供 capture_signals 使用）。
    assert fake_server.capture_signals is start._noop_signal_context, (
        "新 uvicorn API capture_signals 未被覆盖成 _noop_signal_context：新版 uvicorn 会照常调 "
        "signal.signal，在子线程里直接崩"
    )
