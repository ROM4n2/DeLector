# -*- coding: utf-8 -*-
"""工作台导出必须「先落盘、后报成功」的机械闸。

缺陷背景（2026-11-11）：桌面壳 WebView2 默认 `ALLOW_DOWNLOADS=False`，
`on_download_starting` 会静默取消下载（无异常、无回调），而旧前端在 `download()`
之后无条件 `toast("已导出…")` ⇒ 磁盘无文件、界面照样报成功。

本文件钉两层：
1. `POST /api/wb/backup/save` 真的写盘，并把真实路径与字节数回给前端；
2. `tools/wb_export_probe.mjs` 切真源码跑五种场景，断言 toast 只认 `res.ok`。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from probe_runner import assert_probe_clean, run_json_probe, scenario_keys


@pytest.fixture
def export_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把落盘目录指到 tmp，并确保不触发 Android 分支。"""
    import delector.routes.backup as backup_routes

    target = tmp_path / "Downloads"
    target.mkdir()
    monkeypatch.setattr(backup_routes, "_export_download_dir", lambda: (target, False))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    return target


def test_save_endpoint_writes_file_and_reports_real_path(client, export_dir: Path) -> None:
    payload = {"type": "wb-sync", "version": 1, "cards": {"der": {"word": "der"}}}
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb-sync-2026-11-11.json", "payload": payload},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    target = Path(body["path"])
    assert target.is_absolute()
    assert target.parent == export_dir
    raw = target.read_bytes()
    assert body["bytes"] == len(raw) > 0
    assert json.loads(raw.decode("utf-8")) == payload


def test_save_endpoint_never_overwrites_existing_export(client, export_dir: Path) -> None:
    req = {"filename": "wb.json", "payload": {"n": 1}}
    first = client.post("/api/wb/backup/save", json=req).json()
    second = client.post("/api/wb/backup/save", json=req).json()

    assert Path(first["path"]).name == "wb.json"
    assert Path(second["path"]).name == "wb-2.json"
    assert Path(first["path"]).is_file() and Path(second["path"]).is_file()


def test_save_endpoint_strips_path_traversal(client, export_dir: Path) -> None:
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "../../evil.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    target = Path(resp.json()["path"])
    assert target.parent == export_dir
    assert target.name == "evil.json"
    assert not (export_dir.parent / "evil.json").exists()


def test_save_endpoint_reports_failure_instead_of_fake_success(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import delector.routes.backup as backup_routes

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(backup_routes, "_export_download_dir", lambda: (blocker, False))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 500
    assert "写入失败" in resp.json()["detail"]


def test_export_dir_is_created_when_missing(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载目录不存在时自动创建，文件必须落在新目录里。"""
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    downloads = tmp_path / "Downloads"
    assert not downloads.exists()

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert downloads.is_dir()
    assert Path(body["path"]).parent == downloads
    assert Path(body["path"]).is_file()
    assert "fallback_dir" not in body


def test_export_dir_falls_back_to_home_when_creation_fails(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载目录建不出来时退回主目录，且返回体必须能辨识这个降级。"""
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    (tmp_path / "Downloads").write_text("not a directory", encoding="utf-8")

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback_dir"] is True
    assert "用户主目录" in body["warning"]
    target = Path(body["path"])
    assert target.parent == tmp_path
    assert target.name == "wb.json"
    assert target.is_file()


def test_android_keeps_system_download_channel(client, export_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes, "is_android", lambda: True)
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 501
    assert list(export_dir.iterdir()) == []


def test_export_toast_is_bound_to_probe_verified_result() -> None:
    """动态探针：成功/失败/回退三条路径的 toast 都由真实结果驱动。"""
    out = run_json_probe("wb_export_probe")
    assert_probe_clean("wb_export_probe", out)
    assert out["total"] >= 5
    assert {
        "save_ok",
        "save_ok_fallback_dir",
        "save_500",
        "save_no_path",
        "fallback_501",
        "save_network_throw",
    } <= scenario_keys(out)
