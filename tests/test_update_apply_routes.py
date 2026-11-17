# -*- coding: utf-8 -*-
"""`/api/update/download|status|cancel|install` 路由（本机动作面）。

覆盖三件事：
1. 每条端点都必须挂本机闸（非回环来源 403）；
2. 下载只接受后端自己的解析结果，忙时 409，不在支持面的平台 400；
3. 安装只在 ``ready`` 且 Windows 安装版时拉起，失败不假装成功。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from delector import server
from delector.core import database
from delector.routes import update_apply


class FakeSession:
    """受控会话：只实现路由用到的四个方法，状态由用例指定。"""

    def __init__(
        self,
        snapshot: Optional[Dict[str, Any]] = None,
        *,
        begin_ok: bool = True,
        mark_ok: bool = True,
    ) -> None:
        self._snapshot = dict(snapshot or {"state": "downloading"})
        self.begin_ok = begin_ok
        self.mark_ok = mark_ok
        self.begun: List[Any] = []
        self.cancelled = 0
        self.marked = 0
        self.run_called = 0

    def begin(self, platform: str, channel: str, arch: str) -> bool:
        self.begun.append((platform, channel, arch))
        return self.begin_ok

    def run(self) -> Dict[str, Any]:
        self.run_called += 1
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)

    def cancel(self) -> Dict[str, Any]:
        self.cancelled += 1
        self._snapshot.update({"state": "failed", "error_reason": "cancelled"})
        return self.snapshot()

    def mark_installing(self) -> bool:
        self.marked += 1
        if not self.mark_ok:
            return False
        self._snapshot["state"] = "installing"
        return True


def _client(tmp_path: Path, *, host: str = "127.0.0.1") -> TestClient:
    os.environ["DATABASE_PATH"] = str(tmp_path / "update_apply.db")
    os.environ["PROGRESS_DB_PATH"] = str(tmp_path / "update_apply_progress.db")
    database.init_db(os.environ["DATABASE_PATH"])
    return TestClient(server.create_app(), client=(host, 54321))


@pytest.fixture
def client(tmp_path: Path) -> Any:
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    yield _client(tmp_path)
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _reset_session() -> Any:
    saved = update_apply._SESSION
    update_apply._SESSION = None
    yield
    update_apply._SESSION = saved


def test_download_rejects_non_loopback(tmp_path: Path) -> None:
    remote = _client(tmp_path, host="192.168.1.20")

    resp = remote.post("/api/update/download")

    assert resp.status_code == 403


def test_status_and_cancel_also_require_loopback(tmp_path: Path) -> None:
    remote = _client(tmp_path, host="192.168.1.20")

    assert remote.get("/api/update/download/status").status_code == 403
    assert remote.post("/api/update/download/cancel").status_code == 403
    assert remote.post("/api/update/install").status_code == 403


def test_download_starts_session_with_detected_target(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSession({"state": "downloading"})
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    monkeypatch.setattr(update_apply, "_host_target", lambda: ("windows", "installer", "x64"))
    started: List[Any] = []
    monkeypatch.setattr(update_apply, "_start_background", lambda target: started.append(target))

    resp = client.post("/api/update/download")

    assert resp.status_code == 200
    assert resp.json()["state"] == "downloading"
    assert fake.begun == [("windows", "installer", "x64")]
    assert started == [fake.run]


def test_download_busy_returns_409(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession({"state": "downloading"}, begin_ok=False)
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    monkeypatch.setattr(update_apply, "_host_target", lambda: ("linux", "portable", "x64"))

    resp = client.post("/api/update/download")

    assert resp.status_code == 409


def test_download_allows_android_with_arm64(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Android 复用 Python 下载器（安装交给 Java 桥），目标必须收敛为 arm64。"""
    fake = FakeSession({"state": "downloading"})
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    monkeypatch.setattr(update_apply, "is_android", lambda: True)
    monkeypatch.setattr(update_apply, "_start_background", lambda target: None)

    resp = client.post("/api/update/download")

    assert resp.status_code == 200
    assert fake.begun == [("android", "portable", "arm64")]


def test_download_rejects_macos(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_apply, "detect_platform", lambda **kwargs: "macos")

    resp = client.post("/api/update/download")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "unsupported"


def test_status_returns_snapshot(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession({"state": "verifying", "downloaded_bytes": 10})
    monkeypatch.setattr(update_apply, "_SESSION", fake)

    body = client.get("/api/update/download/status").json()

    assert body["state"] == "verifying"
    assert body["downloaded_bytes"] == 10


def test_cancel_delegates_to_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession({"state": "downloading"})
    monkeypatch.setattr(update_apply, "_SESSION", fake)

    body = client.post("/api/update/download/cancel").json()

    assert body["error_reason"] == "cancelled"
    assert fake.cancelled == 1


def test_install_requires_ready(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession({"state": "downloading"})
    monkeypatch.setattr(update_apply, "_SESSION", fake)

    resp = client.post("/api/update/install")

    assert resp.status_code == 409
    assert fake.marked == 0


def test_install_rejects_android(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Android 的安装由 Java 桥完成，本机端点必须明确拒绝而不是假装成功。"""
    fake = FakeSession({"state": "ready", "platform": "android", "channel": "portable"})
    monkeypatch.setattr(update_apply, "_SESSION", fake)

    resp = client.post("/api/update/install")

    assert resp.status_code == 400
    assert fake.marked == 0


def test_install_dispatches_windows_portable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "Portable.zip"
    archive.write_bytes(b"stub")
    fake = FakeSession(
        {
            "state": "ready",
            "platform": "windows",
            "channel": "portable",
            "version": "9.9.9",
            "asset_path": str(archive),
        }
    )
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    calls: List[Any] = []
    monkeypatch.setattr(update_apply, "_install_windows_portable", lambda path, version: calls.append((path, version)))
    monkeypatch.setattr(update_apply, "schedule_exit", lambda delay, function: None)

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert calls == [(archive, "9.9.9")]


def test_install_dispatches_linux(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "Linux.tar.gz"
    archive.write_bytes(b"stub")
    fake = FakeSession(
        {
            "state": "ready",
            "platform": "linux",
            "channel": "portable",
            "version": "9.9.9",
            "asset_path": str(archive),
        }
    )
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    calls: List[Any] = []
    monkeypatch.setattr(update_apply, "_install_linux", lambda path, version: calls.append((path, version)))
    monkeypatch.setattr(update_apply, "schedule_exit", lambda delay, function: None)

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert calls == [(archive, "9.9.9")]


def test_install_spawns_installer_and_schedules_exit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "Setup.exe"
    exe.write_bytes(b"stub")
    fake = FakeSession(
        {
            "state": "ready",
            "platform": "windows",
            "channel": "installer",
            "asset_path": str(exe),
        }
    )
    monkeypatch.setattr(update_apply, "_SESSION", fake)
    spawned: List[Path] = []
    scheduled: List[Any] = []

    def record_spawn(path: Path) -> None:
        spawned.append(path)

    def record_exit(delay: float, function: Any) -> None:
        scheduled.append((delay, function))

    monkeypatch.setattr(update_apply, "spawn_installer", record_spawn)
    monkeypatch.setattr(update_apply, "schedule_exit", record_exit)

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert resp.json()["state"] == "installing"
    assert spawned == [exe]
    assert len(scheduled) == 1
    assert fake.run_called == 0


def test_install_spawn_failure_is_500(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "Setup.exe"
    exe.write_bytes(b"stub")
    fake = FakeSession(
        {"state": "ready", "platform": "windows", "channel": "installer", "asset_path": str(exe)}
    )
    monkeypatch.setattr(update_apply, "_SESSION", fake)

    def boom(path: Path) -> None:
        raise OSError("denied")

    monkeypatch.setattr(update_apply, "spawn_installer", boom)

    resp = client.post("/api/update/install")

    assert resp.status_code == 500
