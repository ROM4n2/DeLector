# -*- coding: utf-8 -*-
"""带断点、可取消、带校验的更新包下载器（零全局状态）。

设计边界：
- **传输可注入**（``transport``）：单测用假流模拟 206 续传 / 200 忽略 Range /
  中途截断，绝不真联网；真实实现是 ``httpx_transport``。
- **下载与校验分离**：``download`` 只负责把字节落到 ``.part``，``finalize`` 负责
  sha256 比对与原子改名。校验失败不得留下可被误用的正式文件。
- **本地文件名固定**：只取资产名的 basename，不信任 ``Content-Disposition``，也不让
  URL 决定落盘路径。
"""

import hashlib
import hmac
import os
import shutil
import threading
from abc import abstractmethod
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Protocol

import httpx

__all__ = [
    "ChecksumMismatchError",
    "DownloadCancelled",
    "DownloadError",
    "NoSpaceError",
    "NotFoundError",
    "RateLimitedError",
    "SizeMismatchError",
    "download",
    "finalize",
    "has_space",
    "httpx_transport",
    "parse_sha256_asset",
    "sha256_file",
    "verify_sha256",
]

_CHUNK_SIZE = 1 << 20
# 预检留 64MB 余量：解压/临时文件与文件系统块开销，避免"刚好装得下"然后写失败。
_SPACE_MARGIN = 64 * 1024 * 1024


class DownloadError(Exception):
    """下载失败基类；``reason`` 直接映射到会话快照的 ``error_reason``。"""

    reason = "network"


class NoSpaceError(DownloadError):
    reason = "no_space"


class RateLimitedError(DownloadError):
    reason = "rate_limited"


class NotFoundError(DownloadError):
    reason = "not_found"


class SizeMismatchError(DownloadError):
    reason = "size_mismatch"


class ChecksumMismatchError(DownloadError):
    reason = "checksum_mismatch"


class DownloadCancelled(DownloadError):
    reason = "cancelled"


class DownloadStream(Protocol):
    """一次 HTTP 响应的最小面：状态码 + 分块字节 + 关闭。"""

    status_code: int

    @abstractmethod
    def iter_chunks(self) -> Iterable[bytes]:
        ...

    @abstractmethod
    def close(self) -> None:
        ...


class Transport(Protocol):
    @abstractmethod
    def __call__(self, url: str, headers: Dict[str, str]) -> DownloadStream:
        ...


class _HttpxStream:
    """把 ``httpx`` 的流式响应包成本模块的 ``DownloadStream``。"""

    def __init__(self, url: str, headers: Dict[str, str]) -> None:
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        self._context = self._client.stream("GET", url, headers=headers)
        self._response = self._context.__enter__()
        self.status_code = self._response.status_code
        self._closed = False

    def iter_chunks(self) -> Iterable[bytes]:
        return self._response.iter_bytes(_CHUNK_SIZE)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._context.__exit__(None, None, None)
        finally:
            self._client.close()


def httpx_transport(url: str, headers: Dict[str, str]) -> DownloadStream:
    """真实传输：唯一的出网点。单测不调用它。"""
    return _HttpxStream(url, headers)


def parse_sha256_asset(text: str, expected_name: str) -> Optional[str]:
    """解析 CI 生成的 ``.sha256`` 文本，返回期望资产的 64 位小写 hex。

    兼容 ``sha256sum`` 的 ``hex  name`` 与 ``hex *name`` 两种形态；纯 hex 行也接受。
    名字存在但与期望资产不符时返回 None —— 宁可报 ``checksum_missing``，不拿别的
    文件的哈希去校验本文件。
    """
    entries: list[tuple[str, Optional[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        digest = parts[0].lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            continue
        name: Optional[str] = None
        if len(parts) == 2:
            name = parts[1].strip()
            if name.startswith("*"):
                name = name[1:]
        entries.append((digest, name))

    for digest, name in entries:
        if name == expected_name:
            return digest
    named = [entry for entry in entries if entry[1] is not None]
    if not named and len(entries) == 1:
        return entries[0][0]
    return None


def sha256_file(path: Path) -> str:
    """分块算哈希（1MB），不把整个安装包读进内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected_hex: str) -> bool:
    """常量时间比较，避免把哈希比对写成可测的时序侧信道。"""
    return hmac.compare_digest(sha256_file(path), expected_hex.strip().lower())


def has_space(dest_dir: Path, needed_bytes: int) -> bool:
    """空间预检；目录不存在时先按父目录估算（下载前会 mkdir）。"""
    probe = dest_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return True  # 拿不到配额就不拦，后续写失败会转成 write_failed
    return usage.free >= needed_bytes + _SPACE_MARGIN


def _local_name(asset_name: str) -> str:
    """只接受纯文件名：带目录的资产名直接拒绝，防止落盘路径被资产名带跑。"""
    name = Path(asset_name).name
    if not name or name in (".", "..") or name != asset_name:
        raise DownloadError(f"非法资产名: {asset_name!r}")
    return name


def download(
    asset_url: str,
    asset_name: str,
    expected_size: int,
    dest_dir: Path,
    *,
    transport: Transport,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """下载到 ``<name>.part`` 并返回该路径；不负责哈希，交给 ``finalize``。

    续传规则：已有 ``.part`` 就带 ``Range``；服务端返回 200（忽略 Range）则丢弃旧
    字节从头写。字节数必须与 ``expected_size`` **严格相等**，多写少写都算失败。
    """
    local = _local_name(asset_name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / (local + ".part")

    start = part.stat().st_size if part.is_file() else 0
    if start > expected_size:
        part.unlink()
        start = 0
    if expected_size > 0 and start == expected_size:
        # 上次已写满但没来得及 finalize（进程被杀等）：不必再发 Range（服务端会回 416）。
        return part

    if not has_space(dest_dir, max(expected_size - start, 0)):
        raise NoSpaceError("磁盘剩余空间不足")

    headers: Dict[str, str] = {"Range": f"bytes={start}-"} if start > 0 else {}
    try:
        stream = transport(asset_url, headers)
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError("network") from exc
    written = start
    try:
        status = int(stream.status_code)
        if status in (401, 403, 429):
            raise RateLimitedError("rate_limited")
        if status == 404:
            raise NotFoundError("not_found")
        if status not in (200, 206):
            raise DownloadError("network")
        if status == 200:
            start = 0  # 服务端忽略了 Range：不能把 200 的完整响应追加到旧片段后面
            written = 0

        mode = "ab" if start > 0 else "wb"
        with part.open(mode) as handle:
            for chunk in stream.iter_chunks():
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("用户取消")
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if on_progress is not None:
                    on_progress(min(written, expected_size), expected_size)
                if written > expected_size:
                    raise SizeMismatchError("下载字节数超过预期")
    finally:
        try:
            stream.close()
        except Exception:  # silent-ok: 关闭失败不得覆盖真正的下载错误
            pass

    if written != expected_size:
        raise SizeMismatchError(f"下载字节数不符: {written} != {expected_size}")
    return part


def finalize(part: Path, expected_sha256: str, final_path: Path) -> Path:
    """校验 sha256 后原子改名；校验失败删掉 ``.part`` 并拒绝留下正式文件。"""
    if not verify_sha256(part, expected_sha256):
        part.unlink(missing_ok=True)
        raise ChecksumMismatchError("安装包 sha256 与 Release 校验和不符")
    os.replace(part, final_path)
    return final_path
