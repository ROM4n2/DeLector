# -*- coding: utf-8 -*-
"""应用内更新会话状态机（同步流水线，线程由路由层负责）。

为什么状态机是同步的：下载进度、校验、失败原因都要能被单测确定性地断言。
把 ``threading.Thread`` 留在路由层，「开始 → 下载 → 校验 → 就绪」这段就退化成
一条可顺序观察的纯流水线；测试不需要 sleep，也不会出现"偶发绿"。

状态：``idle → downloading → verifying → ready → installing``；任一失败 → ``failed``。
同一时刻只允许一个活动会话（``begin`` 返回 False 表示忙）。
"""

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from delector.core.update_download import DownloadError, finalize, parse_sha256_asset

__all__ = ["UpdateSession"]

_ACTIVE_STATES = frozenset({"downloading", "verifying"})
_SNAPSHOT_KEYS = (
    "state",
    "platform",
    "channel",
    "arch",
    "version",
    "downloaded_bytes",
    "total_bytes",
    "asset_path",
    "error_reason",
)


class _Abort(Exception):
    """流水线内部的显式失败（带 ``error_reason``）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UpdateSession:
    """一次应用内更新的完整生命周期。

    - ``artifact_resolver(platform, channel, arch)``：返回 ``/api/update/artifact`` 同款字典
    - ``checksum_fetcher(url)``：返回 ``.sha256`` 文本
    - ``downloader``：``delector.core.update_download.download`` 的可注入替身
    - ``on_change``：每次状态迁移时收到快照副本（测试用它断言迁移序列）
    """

    def __init__(
        self,
        *,
        artifact_resolver: Callable[[str, str, str], Dict[str, Any]],
        checksum_fetcher: Callable[[str], str],
        downloader: Callable[..., Path],
        target_dir: Path,
        on_change: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._artifact_resolver = artifact_resolver
        self._checksum_fetcher = checksum_fetcher
        self._downloader = downloader
        self._target_dir = target_dir
        self._on_change = on_change
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._state = "idle"
        self._platform = ""
        self._channel = ""
        self._arch = ""
        self._version: Optional[str] = None
        self._downloaded = 0
        self._total = 0
        self._asset_path: Optional[str] = None
        self._asset_name: Optional[str] = None
        self._error: Optional[str] = None

    # ── 对外 ──────────────────────────────────────────────────────────────
    def begin(self, platform: str, channel: str, arch: str) -> bool:
        """占用会话；已有活动会话时返回 False（路由层转 409 busy）。"""
        with self._lock:
            if self._state in _ACTIVE_STATES or self._state == "installing":
                return False
            self._cancel.clear()
            self._state = "downloading"
            self._platform = platform
            self._channel = channel
            self._arch = arch
            self._version = None
            self._downloaded = 0
            self._total = 0
            self._asset_path = None
            self._asset_name = None
            self._error = None
            snapshot = self._snapshot_locked()
        self._emit(snapshot)
        return True

    def run(self) -> Dict[str, Any]:
        """执行整条流水线；必须紧跟一次成功的 ``begin``。"""
        try:
            self._pipeline()
        except _Abort as exc:
            self._fail(exc.reason)
        except DownloadError as exc:
            self._fail(exc.reason)
        except Exception:  # 写盘/权限/未知：不把异常抛给后台线程
            self._fail("write_failed")
        return self.snapshot()

    def cancel(self) -> Dict[str, Any]:
        """请求取消；只对 ``downloading / verifying`` 生效。"""
        with self._lock:
            if self._state not in _ACTIVE_STATES:
                return self._snapshot_locked()
            self._cancel.set()
            self._state = "failed"
            self._error = "cancelled"
            snapshot = self._snapshot_locked()
        self._discard_part()
        self._emit(snapshot)
        return snapshot

    def mark_installing(self) -> bool:
        """就绪 → 安装中；状态不符返回 False（路由层转 409）。"""
        with self._lock:
            if self._state != "ready":
                return False
            self._state = "installing"
            snapshot = self._snapshot_locked()
        self._emit(snapshot)
        return True

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    # ── 内部 ──────────────────────────────────────────────────────────────
    def _pipeline(self) -> None:
        try:
            meta = self._artifact_resolver(self._platform, self._channel, self._arch)
        except Exception as exc:
            raise _Abort("network") from exc
        if meta.get("error_reason"):
            raise _Abort(str(meta["error_reason"]))

        asset_name = meta.get("asset_name")
        asset_url = meta.get("asset_url")
        checksum_url = meta.get("checksum_url")
        size = meta.get("asset_size")
        if not isinstance(asset_name, str) or not isinstance(asset_url, str):
            raise _Abort("asset_missing")
        if not isinstance(checksum_url, str):
            raise _Abort("checksum_missing")
        if not isinstance(size, int) or size <= 0:
            raise _Abort("asset_missing")

        with self._lock:
            self._version = meta.get("version")
            self._asset_name = asset_name
            self._total = size
            snapshot = self._snapshot_locked()
        self._emit(snapshot)

        part = self._downloader(
            asset_url,
            asset_name,
            size,
            self._target_dir,
            cancel_event=self._cancel,
            on_progress=self._progress,
        )
        if self._cancel.is_set():
            raise _Abort("cancelled")

        with self._lock:
            self._state = "verifying"
            snapshot = self._snapshot_locked()
        self._emit(snapshot)

        try:
            checksum_text = self._checksum_fetcher(checksum_url)
        except Exception as exc:
            raise _Abort("network") from exc
        expected = parse_sha256_asset(checksum_text, asset_name)
        if expected is None:
            raise _Abort("checksum_missing")

        final = finalize(part, expected, self._target_dir / asset_name)
        if self._cancel.is_set():
            final.unlink(missing_ok=True)
            raise _Abort("cancelled")

        with self._lock:
            self._state = "ready"
            self._asset_path = str(final)
            self._downloaded = size
            snapshot = self._snapshot_locked()
        self._emit(snapshot)

    def _progress(self, downloaded: int, total: int) -> None:
        with self._lock:
            self._downloaded = downloaded
            self._total = total

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._state == "failed" and self._error == "cancelled":
                return  # 已被 cancel() 收口，不覆盖成别的失败原因
            self._state = "failed"
            self._error = reason
            snapshot = self._snapshot_locked()
        if reason == "cancelled":
            self._discard_part()
        self._emit(snapshot)

    def _discard_part(self) -> None:
        with self._lock:
            name = self._asset_name
        if not name:
            return
        # 下载线程可能仍持有句柄；Windows 下删除会抛 PermissionError。删不掉不是新失败，
        # 下一轮 download 会按既有 .part 续传或按大小规则丢弃，故这里只吞掉 OSError。
        try:
            (self._target_dir / (name + ".part")).unlink(missing_ok=True)
        except OSError:  # silent-ok: 句柄被下载线程占用时删不掉，下一轮按 .part 续传
            pass

    def _snapshot_locked(self) -> Dict[str, Any]:
        values = {
            "state": self._state,
            "platform": self._platform,
            "channel": self._channel,
            "arch": self._arch,
            "version": self._version,
            "downloaded_bytes": self._downloaded,
            "total_bytes": self._total,
            "asset_path": self._asset_path,
            "error_reason": self._error,
        }
        assert tuple(values) == _SNAPSHOT_KEYS
        return values

    def _emit(self, snapshot: Dict[str, Any]) -> None:
        if self._on_change is not None:
            self._on_change(dict(snapshot))
