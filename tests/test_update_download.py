# -*- coding: utf-8 -*-
"""更新包下载器（`delector/core/update_download.py`）：零真实网络。

所有传输都用 `FakeTransport` 表达：状态码、响应分块、Range 头都由用例决定。
"""

import hashlib
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pytest

from delector.core import update_download
from delector.core.update_download import (
    ChecksumMismatchError,
    DownloadCancelled,
    DownloadError,
    NoSpaceError,
    SizeMismatchError,
    download,
    finalize,
    parse_sha256_asset,
    verify_sha256,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeStream:
    def __init__(self, status_code: int, chunks: Iterable[bytes]) -> None:
        self.status_code = status_code
        self._chunks = list(chunks)
        self.closed = False

    def iter_chunks(self) -> Iterable[bytes]:
        return iter(self._chunks)

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    """按调用记录 head/头，返回预设流；可让不同调用返回不同状态。"""

    def __init__(self, responses: List[Tuple[int, List[bytes]]]) -> None:
        self.calls: List[Tuple[str, Dict[str, str]]] = []
        self._responses = list(responses)

    def __call__(self, url: str, headers: Dict[str, str]) -> FakeStream:
        self.calls.append((url, dict(headers)))
        status, chunks = self._responses.pop(0)
        return FakeStream(status, chunks)


def _part(dest: Path, name: str = "pkg.bin") -> Path:
    return dest / (name + ".part")


# ==========================================================================
# 1. 基本落盘 / 续传 / 200 忽略 Range
# ==========================================================================
def test_download_writes_part_only(tmp_path: Path) -> None:
    payload = b"abcdef"
    transport = FakeTransport([(200, [payload])])

    part = download(
        "https://example.test/pkg.bin",
        "pkg.bin",
        len(payload),
        tmp_path,
        transport=transport,
    )

    assert part == _part(tmp_path)
    assert part.read_bytes() == payload
    assert not (tmp_path / "pkg.bin").exists()
    assert transport.calls[0][1] == {}  # 首次无 Range


def test_resume_sends_range_and_appends(tmp_path: Path) -> None:
    _part(tmp_path).write_bytes(b"abc")
    transport = FakeTransport([(206, [b"def"])])
    progress: List[Tuple[int, int]] = []

    part = download(
        "https://example.test/pkg.bin",
        "pkg.bin",
        6,
        tmp_path,
        transport=transport,
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert transport.calls[0][1] == {"Range": "bytes=3-"}
    assert part.read_bytes() == b"abcdef"
    assert progress[-1] == (6, 6)


def test_200_ignores_range_and_restarts_from_zero(tmp_path: Path) -> None:
    """服务端忽略 Range 时必须丢弃旧片段，不能拼成 ab + abc。"""
    _part(tmp_path).write_bytes(b"ab")
    transport = FakeTransport([(200, [b"abc"])])

    part = download("https://example.test/pkg.bin", "pkg.bin", 3, tmp_path, transport=transport)

    assert part.read_bytes() == b"abc"


def test_oversized_part_is_truncated_before_request(tmp_path: Path) -> None:
    _part(tmp_path).write_bytes(b"0123456789")
    transport = FakeTransport([(200, [b"abc"])])

    part = download("https://example.test/pkg.bin", "pkg.bin", 3, tmp_path, transport=transport)

    assert transport.calls[0][1] == {}
    assert part.read_bytes() == b"abc"


# ==========================================================================
# 2. 失败路径
# ==========================================================================
def test_short_body_keeps_part_for_resume(tmp_path: Path) -> None:
    transport = FakeTransport([(200, [b"ab"])])

    with pytest.raises(SizeMismatchError) as excinfo:
        download("https://example.test/pkg.bin", "pkg.bin", 5, tmp_path, transport=transport)

    assert excinfo.value.reason == "size_mismatch"
    assert _part(tmp_path).read_bytes() == b"ab"  # 保留，允许下次续传


def test_oversized_body_is_rejected(tmp_path: Path) -> None:
    transport = FakeTransport([(200, [b"abcd"])])

    with pytest.raises(SizeMismatchError):
        download("https://example.test/pkg.bin", "pkg.bin", 2, tmp_path, transport=transport)


def test_cancel_raises_cancelled(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    transport = FakeTransport([(200, [b"abc"])])

    with pytest.raises(DownloadCancelled) as excinfo:
        download(
            "https://example.test/pkg.bin",
            "pkg.bin",
            3,
            tmp_path,
            transport=transport,
            cancel_event=cancel,
        )

    assert excinfo.value.reason == "cancelled"


def test_no_space_is_reported_before_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_download, "has_space", lambda dest, needed: False)
    transport = FakeTransport([])

    with pytest.raises(NoSpaceError) as excinfo:
        download("https://example.test/pkg.bin", "pkg.bin", 3, tmp_path, transport=transport)

    assert excinfo.value.reason == "no_space"
    assert transport.calls == []


@pytest.mark.parametrize(
    "status,reason",
    [(403, "rate_limited"), (429, "rate_limited"), (404, "not_found"), (500, "network")],
)
def test_status_mapping(status: int, reason: str, tmp_path: Path) -> None:
    transport = FakeTransport([(status, [])])

    with pytest.raises(DownloadError) as excinfo:
        download("https://example.test/pkg.bin", "pkg.bin", 3, tmp_path, transport=transport)

    assert excinfo.value.reason == reason


def test_path_like_asset_name_is_rejected(tmp_path: Path) -> None:
    transport = FakeTransport([])

    with pytest.raises(DownloadError):
        download("https://example.test/pkg.bin", "../evil.bin", 3, tmp_path, transport=transport)


def test_stream_is_closed_even_on_failure(tmp_path: Path) -> None:
    stream = FakeStream(200, [b"a"])

    def transport(url: str, headers: Dict[str, str]) -> FakeStream:
        return stream

    with pytest.raises(SizeMismatchError):
        download("https://example.test/pkg.bin", "pkg.bin", 2, tmp_path, transport=transport)

    assert stream.closed is True


# ==========================================================================
# 3. 校验和解析 / 文件哈希 / 原子收尾
# ==========================================================================
_HASH = "a" * 64


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"{_HASH}  pkg.bin\n", _HASH),
        (f"{_HASH} *pkg.bin\n", _HASH),
        (f"{_HASH}\n", _HASH),
        (f"{'b' * 64}  other.bin\n", None),
        (f"{'b' * 64}  other.bin\n{_HASH}  pkg.bin\n", _HASH),
        ("not-a-hash  pkg.bin\n", None),
        ("", None),
    ],
)
def test_parse_sha256_asset(text: str, expected: Optional[str]) -> None:
    assert parse_sha256_asset(text, "pkg.bin") == expected


def test_verify_and_finalize(tmp_path: Path) -> None:
    payload = b"payload"
    part = _part(tmp_path)
    part.write_bytes(payload)

    assert verify_sha256(part, _sha(payload).upper()) is True

    final = finalize(part, _sha(payload), tmp_path / "pkg.bin")

    assert final.read_bytes() == payload
    assert not part.exists()


def test_finalize_rejects_checksum_mismatch_and_removes_part(tmp_path: Path) -> None:
    part = _part(tmp_path)
    part.write_bytes(b"tampered")

    with pytest.raises(ChecksumMismatchError) as excinfo:
        finalize(part, "b" * 64, tmp_path / "pkg.bin")

    assert excinfo.value.reason == "checksum_mismatch"
    assert not part.exists()
    assert not (tmp_path / "pkg.bin").exists()
