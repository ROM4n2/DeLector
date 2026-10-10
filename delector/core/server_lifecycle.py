# -*- coding: utf-8 -*-
"""uvicorn server 的可控生命周期：起、停、就绪探测（ADR-0020 §4 前置①、§6.4）。

为什么单独一个模块：`start.py` 与日后的桌面壳（`desktop.py`）需要**同一套**启停与
探针语义 —— 各写一套必然漂移，而漂移点恰好全落在「退出收尸」与「端口复用身份校验」
这两处静默失败的高发区。

`probe_identity` 与 `await_ready` 的语义差异（**必须分清，勿混用**）
----------------------------------------------------------------
- `probe_identity`：只回答「占着这个端口的是不是 DeLector」。它**接受任何 HTTP 状态码**，
  只要响应体带 DeLector 身份（``app == "delector"``）即返回 True —— **包括库坏时的 503**。
  理由：「进程是 DeLector、只是库暂时不可用」与「端口被别的软件占了」是两件事，
  调用方（`start.py` 的「已在运行 ⇒ 开浏览器」判定）必须能把它们区分开，否则会把
  自己那个降级的实例误报成「端口被其他程序占用」。
- `await_ready`：回答「DeLector **是否已经可以服务**」。它要求 **200 且身份对**，
  503（库坏）**不算**就绪 —— 否则会把「进程起来了但不可用」误判成「可以用了」。

一句话：`probe_identity` 判「是谁」，`await_ready` 判「能不能用」。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional, Tuple

import httpx
import uvicorn

__all__ = ["build_server", "serve_in_thread", "shutdown", "probe_identity", "await_ready"]

_logger = logging.getLogger("delector")

# 单次健康探测超时（秒）。对 spaCy 冷启动放宽：起服务的**首个**请求可能正好落在模型
# 加载里；总窗口由 await_ready 的 deadline_s 兜底（默认 30s）。
_PROBE_TIMEOUT_S = 3.0

# 就绪等待的退避：从 _BACKOFF_START_S 起翻倍，封顶 _BACKOFF_MAX_S。
_BACKOFF_START_S = 0.2
_BACKOFF_MAX_S = 2.0

# 身份校验锚点（与 delector/routes/main.py 的 /api/health 保持一致）。
_IDENTITY_FIELD = "app"
_IDENTITY_VALUE = "delector"


def build_server(host: str, port: int, app: Any) -> uvicorn.Server:
    """按给定绑定地址与 ASGI app 组装一个 `uvicorn.Server`（**只组装，不启动**）。"""
    config = uvicorn.Config(app, host=host, port=port, reload=False, log_level="info")
    return uvicorn.Server(config)


def serve_in_thread(server: uvicorn.Server) -> threading.Thread:
    """在**非 daemon** 线程里跑 `server.run()` 并返回该线程。

    非 daemon 是硬要求：daemon 线程会在解释器退出时被强杀，`join()` 收尸随之失去意义
    ——「退不干净」的成因之一正是它。调用方随后必须 `shutdown(server, thread)` 收尾。
    """
    thread = threading.Thread(target=server.run, name="delector-uvicorn", daemon=False)
    thread.start()
    return thread


def shutdown(server: uvicorn.Server, thread: threading.Thread, grace_s: float = 5.0) -> bool:
    """请求 server 退出并 join 线程；`grace_s` 内没停干净则**如实返回 False**。

    返回 False 表示线程仍活着（由调用方决定是否硬退出）—— 绝不假装成功：静默的
    「以为停了其实没停」正是下次启动盲判「端口被占用」的根因。
    """
    server.should_exit = True
    thread.join(grace_s)
    if thread.is_alive():
        _logger.warning("uvicorn server 在 %.1fs 宽限期内未退出（线程仍存活），交由调用方硬退出", grace_s)
        return False
    return True


def _fetch_health(port: int, host: str, timeout_s: float) -> Optional[Tuple[int, Any]]:
    """GET `/api/health`，返回 `(status_code, 解析后的 JSON)`；连不上 / 非 JSON 返回 None。"""
    try:
        response = httpx.get(f"http://{host}:{port}/api/health", timeout=timeout_s)
        return response.status_code, response.json()
    except Exception:
        # 连不上 / 超时 / 非 JSON：探针一律当「不是（可用的）DeLector」，不向上抛 ——
        # 探针是启动期的判定手段，不是异常传播通道。
        return None


def _has_identity(payload: Any) -> bool:
    """响应体是否带 DeLector 身份字段。非 dict（含 None）一律 False。"""
    return isinstance(payload, dict) and payload.get(_IDENTITY_FIELD) == _IDENTITY_VALUE


def probe_identity(port: int, timeout_s: float = 3.0, host: str = "127.0.0.1") -> bool:
    """探测端口上的服务是不是 DeLector（判「是谁」，**不看 HTTP 状态码**）。

    **与 `await_ready` 的差异（重要）**：本函数只要响应体带 DeLector 身份即返回 True，
    即便状态码是 503（库坏）—— 因为调用方（`start.py`）用它回答「这个端口是不是自己
    的实例还占着」。若把 503 判成 False，「DeLector 已在跑但库坏了」会被误报成
    「端口被其他程序占用」。
    """
    result = _fetch_health(port, host, timeout_s)
    if result is None:
        return False
    _status, payload = result
    return _has_identity(payload)


def _probe_ready(port: int, host: str) -> bool:
    """单次就绪探测：要求 **200 且身份对**（与 probe_identity 的差异见模块 docstring）。"""
    result = _fetch_health(port, host, _PROBE_TIMEOUT_S)
    if result is None:
        return False
    status, payload = result
    return status == 200 and _has_identity(payload)


def await_ready(port: int, deadline_s: float = 30.0, host: str = "127.0.0.1") -> bool:
    """在总截止时间内轮询，直到 DeLector **可服务**（200 且身份对）为止。

    **与 `probe_identity` 的差异（重要）**：本函数要求 **200 且身份对**，503（库坏）
    不算就绪 —— 它回答的是「能不能用」，不是「是不是 DeLector」。

    单次探测超时 3s、退避重试、总窗口默认 30s（对 spaCy 冷启动宽容）。窗口耗尽仍未
    就绪则**返回 False，绝不静默**：调用方（桌面壳 splash）据此显示失败，而不是对着
    一个起不来的服务空转。
    """
    deadline = time.monotonic() + deadline_s
    delay = _BACKOFF_START_S
    while time.monotonic() < deadline:
        if _probe_ready(port, host):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, _BACKOFF_MAX_S)
    _logger.warning("DeLector 在 %.1fs 就绪窗口内未返回 200+身份，判为未就绪", deadline_s)
    return False
