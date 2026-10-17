# -*- coding: utf-8 -*-
"""C9 Task 2 的行为证明：豁免理由里做出的承诺，MUST 是代码真能做到的事。

覆盖两条「理由与代码不符」在改成**代码**一侧之后的可测面（Y1 / Y5），以及 Y6
「有意的不对称」被钉住后的回归面：

- Y1 `prune_audio_cache`（delector/core/db/content.py）：删除失败按轮汇总落 warning。
  原 `except Exception: pass` 的理由只覆盖「单文件瞬时占用」；系统性失败（ACL / 持久锁）
  会让目录**持续**超出 max_files 且零痕迹 —— 计数 + warning 把那种情形变成可观测。
- Y5 `_is_retryable`（delector/services/tts.py）：`ssl.SSLCertVerificationError` 是确定性
  失败 ⇒ 不重试（省一次 TLS 握手 + 0.5s 退避）；`OSError(ENETUNREACH / EHOSTUNREACH)` 是
  传输层可达性抖动 ⇒ 重试一次（此前因它不是 `ConnectionError` 子类而落进「不重试」）。
- Y6 错误信封：`_HandshakeError` 原样上抛、其余失败包 `RuntimeError` —— 有意为之
  （理由写在 `_HandshakeError` 的 docstring 里），本文件把该契约钉住，防止下次被「顺手统一」。

变异自证（去掉被判据覆盖的逻辑 ⇒ 本文件转红 ⇒ 复原）：见提交信息。
"""

from __future__ import annotations

import errno
import logging
import os
import ssl
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

# 循 database.py 的循环导入纪律：直接 import content 会爆环
# （database.py 在定义完连接访问器后才 re-export content），故走包外层入口。
import delector.core.database as content_db
from delector.services import tts

# ── 公共小件 ────────────────────────────────────────────────────────────


class _Collect(logging.Handler):
    """挂到 `delector` logger 上收记录：不依赖 root logger 的传播设置。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_cache(tmp_path: Path, count: int) -> List[Path]:
    """建 count 个缓存文件，mtime 递增 ⇒ 旧/新可判，裁剪顺序确定。"""
    paths: List[Path] = []
    for i in range(count):
        p = tmp_path / f"a{i:03d}.mp3"
        p.write_bytes(b"x" * 16)
        os.utime(p, (1_600_000_000 + i, 1_600_000_000 + i))
        paths.append(p)
    return paths


_AUDIO_HEADERS = b"Path:audio\r\nContent-Type:audio/mpeg\r\n\r\n"
_OK_FRAMES: List[Tuple[int, bytes]] = [
    (0x2, len(_AUDIO_HEADERS).to_bytes(2, "big") + _AUDIO_HEADERS + b"MP3DATA"),
    (0x1, b"Path:turn.end\r\n\r\n"),
]


class _FakeWS:
    """`tts._WebSocket` 的最小替身：不发网络，按帧序列回放（帧式样与真协议一致）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.frames = list(_OK_FRAMES)

    def handshake(self, path: str, host: str) -> None:
        return None

    def send_text(self, payload: str) -> None:
        return None

    def recv_frame(self) -> Tuple[int, bytes]:
        return self.frames.pop(0)

    def close(self) -> None:
        return None


# ── Y1：裁剪失败必须留痕 ─────────────────────────────────────────────────


def test_prune_audio_cache_warns_when_deletes_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """删不掉的（占用 / ACL）文件必须留痕，且被占用文件必须原样留下。

    原实现 `except Exception: pass`：单文件瞬时占用下轮自愈，但**系统性**失败
    （权限 / 持久锁）会让缓存静默超出 max_files —— 那种情形下这条 warning 是唯一的观测点。
    """
    files = _make_cache(tmp_path, 50)
    blocked = {files[0], files[1]}  # 最旧的两个 ⇒ 必在本轮删除选择集内
    real_remove = os.remove

    def fake_remove(path: str) -> None:
        if Path(path) in blocked:
            raise PermissionError(13, "file is locked by another process", str(path))
        real_remove(path)

    monkeypatch.setattr(os, "remove", fake_remove)

    handler = _Collect()
    lg = logging.getLogger("delector")
    lg.addHandler(handler)
    previous_level = lg.level
    lg.setLevel(logging.WARNING)
    try:
        content_db.prune_audio_cache(max_files=45, cache_dir=str(tmp_path))
    finally:
        lg.removeHandler(handler)
        lg.setLevel(previous_level)

    messages = [r.getMessage() for r in handler.records if r.levelno >= logging.WARNING]
    assert messages, "删除失败时一条 warning 都没有 ⇒ 失败被静默吞掉（这正是 Y1）"
    assert any("删除失败" in m and "2" in m for m in messages), f"失败计数未落进 warning: {messages}"

    for p in blocked:
        assert p.exists(), "删不掉的文件不该凭空消失（本函数只做尽力清理）"
    # 选择集 = 50 - 45 + 30 = 35 个最旧文件；其中 2 个失败 ⇒ 33 个被删，剩 17 个。
    assert len(list(tmp_path.iterdir())) == 17, "成功部分必须照常删除（本函数不是全有或全无）"


# ── Y5：重试分类的两个边缘 ──────────────────────────────────────────────


def test_ssl_cert_verification_error_is_not_retryable() -> None:
    """证书类失败是**确定性**的：重试收益恒为 0，只多付一次 TLS 握手 + 0.5s 退避。"""
    error = ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer certificate")
    assert isinstance(error, ssl.SSLError), "前提：它仍 ⊂ SSLError（故判定顺序必须先排除它）"
    assert tts._is_retryable(error) is False


def test_unreachable_errnos_are_retryable() -> None:
    """ENETUNREACH / EHOSTUNREACH 是传输层可达性抖动：重启连接有真实成功概率。"""
    for code in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        error = OSError(code, "simulated unreachable")
        assert not isinstance(error, ConnectionError), "前提：PEP 3151 不给这两个 errno 专有子类（故此前漏判）"
        assert tts._is_retryable(error) is True, f"errno={code} 未计入可重试"


def test_synthesize_retries_network_unreachable_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：第一次 ENETUNREACH、第二次成功 ⇒ 必须发生第二次尝试 + 一次有界退避。"""
    attempts: List[int] = []
    sleeps: List[float] = []
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))

    class _Flaky:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError(errno.ENETUNREACH, "network is unreachable")
            self._inner = _FakeWS()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    monkeypatch.setattr(tts, "_WebSocket", _Flaky)
    assert tts.synthesize("Hallo") == b"MP3DATA"
    assert len(attempts) == 2, "传输层不可达必须重试一次（首次 + 一次重试）"
    assert sleeps == [0.5], f"重试前必须有且仅有一次 0.5s 有界退避: {sleeps}"


def test_synthesize_does_not_retry_cert_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：证书校验失败 ⇒ 只有一次尝试、零退避，且走 RuntimeError 信封。"""
    attempts: List[int] = []
    sleeps: List[float] = []
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))

    class _CertBroken:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            raise ssl.SSLCertVerificationError(1, "certificate verify failed")

    monkeypatch.setattr(tts, "_WebSocket", _CertBroken)
    with pytest.raises(RuntimeError, match="edge_tts_mini synthesis failed"):
        tts.synthesize("Hallo")
    assert len(attempts) == 1, "确定性失败不得重试（原判据把它当 SSLError 重试了一次）"
    assert sleeps == [], "不重试就不得进入退避路径"


# ── Y6：错误信封的有意不对称 ────────────────────────────────────────────


def test_handshake_rejection_propagates_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_HandshakeError` 原样上抛（不套 RuntimeError）：调用方要按 status_code 分流。

    见 `_HandshakeError` docstring 的「有意不对称」三条理由。此行以下断言与
    tests/test_server.py 的 `pytest.raises(tts._HandshakeError)` 同口径 —— 两处都改才算改契约。
    """
    framed: Dict[str, int] = {"attempts": 0}

    class _Rejected:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            framed["attempts"] += 1

        def handshake(self, path: str, host: str) -> None:
            raise tts._HandshakeError(b"HTTP/1.1 401 Unauthorized", {})

        def close(self) -> None:
            return None

    monkeypatch.setattr(tts, "_WebSocket", _Rejected)
    with pytest.raises(tts._HandshakeError) as excinfo:
        tts.synthesize("Hallo")
    assert excinfo.value.status_code == 401
    assert framed["attempts"] == 1