# -*- coding: utf-8 -*-
"""更新会话状态机（`delector/core/update_session.py`）：同步流水线，零线程、零网络。"""

import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from delector.core.update_download import ChecksumMismatchError, DownloadCancelled
from delector.core.update_session import UpdateSession

PAYLOAD = b"abc"
NAME = "pkg.bin"
VERSION = "9.9.9"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _meta(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "version": VERSION,
        "asset_name": NAME,
        "asset_url": "https://example.test/pkg.bin",
        "asset_size": len(PAYLOAD),
        "checksum_url": "https://example.test/pkg.bin.sha256",
        "error_reason": None,
    }
    base.update(over)
    return base


def _downloader(payload: bytes = PAYLOAD) -> Callable[..., Path]:
    def run(asset_url: str, asset_name: str, size: int, dest: Path, **kwargs: Any) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        part = dest / (asset_name + ".part")
        part.write_bytes(payload)
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            on_progress(len(payload), size)
        return part

    return run


def _session(
    tmp_path: Path,
    *,
    meta: Optional[Dict[str, Any]] = None,
    payload: bytes = PAYLOAD,
    checksum: Optional[str] = None,
    downloader: Optional[Callable[..., Path]] = None,
    on_change: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> UpdateSession:
    meta_value = _meta() if meta is None else meta
    text = checksum if checksum is not None else f"{SHA}  {meta_value.get('asset_name', NAME)}\n"
    return UpdateSession(
        artifact_resolver=lambda platform, channel, arch: dict(meta_value),
        checksum_fetcher=lambda url: text,
        downloader=downloader or _downloader(payload),
        target_dir=tmp_path,
        on_change=on_change,
    )


def test_happy_path_reaches_ready(tmp_path: Path) -> None:
    states: List[str] = []
    session = _session(tmp_path, on_change=lambda snap: states.append(snap["state"]))

    assert session.begin("windows", "installer", "x64") is True
    result = session.run()

    assert result["state"] == "ready"
    assert result["version"] == VERSION
    assert result["downloaded_bytes"] == len(PAYLOAD)
    assert result["total_bytes"] == len(PAYLOAD)
    assert Path(str(result["asset_path"])).read_bytes() == PAYLOAD
    assert "verifying" in states
    assert states[-1] == "ready"
    assert not (tmp_path / (NAME + ".part")).exists()


def test_snapshot_has_exact_keys(tmp_path: Path) -> None:
    session = _session(tmp_path)

    session.begin("windows", "installer", "x64")
    snapshot = session.snapshot()

    assert set(snapshot) == {
        "state",
        "platform",
        "channel",
        "arch",
        "version",
        "downloaded_bytes",
        "total_bytes",
        "asset_path",
        "error_reason",
    }
    assert snapshot["state"] == "downloading"
    assert snapshot["error_reason"] is None


def test_second_begin_is_rejected_as_busy(tmp_path: Path) -> None:
    session = _session(tmp_path)
    assert session.begin("windows", "installer", "x64") is True

    assert session.begin("windows", "portable", "x64") is False
    assert session.snapshot()["channel"] == "installer"  # 原会话未被覆盖


def test_artifact_failure_is_surfaced(tmp_path: Path) -> None:
    session = _session(tmp_path, meta=_meta(error_reason="asset_missing", asset_url=None))

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "asset_missing"


def test_zero_size_asset_is_rejected(tmp_path: Path) -> None:
    session = _session(tmp_path, meta=_meta(asset_size=0))

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "asset_missing"


def test_download_cancelled_cleans_part(tmp_path: Path) -> None:
    def downloader(asset_url: str, asset_name: str, size: int, dest: Path, **kwargs: Any) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        part = dest / (asset_name + ".part")
        part.write_bytes(b"ab")
        raise DownloadCancelled("用户取消")

    session = _session(tmp_path, downloader=downloader)

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "cancelled"
    assert not (tmp_path / (NAME + ".part")).exists()


def test_checksum_mismatch_fails_without_ready_file(tmp_path: Path) -> None:
    session = _session(tmp_path, checksum=f"{'b' * 64}  {NAME}\n")

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "checksum_mismatch"
    assert result["asset_path"] is None
    assert not (tmp_path / NAME).exists()
    assert not (tmp_path / (NAME + ".part")).exists()


def test_unparseable_checksum_asset_is_checksum_missing(tmp_path: Path) -> None:
    session = _session(tmp_path, checksum="garbage\n")

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "checksum_missing"


def test_mark_installing_requires_ready(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin("windows", "installer", "x64")

    assert session.mark_installing() is False  # downloading 不是 ready


def test_mark_installing_transitions_ready_to_installing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin("windows", "installer", "x64")
    session.run()

    assert session.mark_installing() is True
    assert session.snapshot()["state"] == "installing"
    assert session.mark_installing() is False


def test_cancel_from_downloading_marks_failed_cancelled(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin("windows", "installer", "x64")

    result = session.cancel()

    assert result["state"] == "failed"
    assert result["error_reason"] == "cancelled"


def test_cancel_after_ready_is_noop(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.begin("windows", "installer", "x64")
    session.run()

    result = session.cancel()

    assert result["state"] == "ready"


def test_download_error_reason_is_preserved(tmp_path: Path) -> None:
    def downloader(asset_url: str, asset_name: str, size: int, dest: Path, **kwargs: Any) -> Path:
        raise ChecksumMismatchError("boom")

    session = _session(tmp_path, downloader=downloader)

    session.begin("windows", "installer", "x64")
    result = session.run()

    assert result["state"] == "failed"
    assert result["error_reason"] == "checksum_mismatch"
