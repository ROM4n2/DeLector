# -*- coding: utf-8 -*-
"""T8：运行时三处静默降级的行为探针（审计报告 P2 #7 + #8）。

三条都触发真实代码路径并检查结果，不做源码字符串存在断言。
"""

import errno
import os
from pathlib import Path

import pytest


def test_explicit_env_is_not_overwritten_by_stale_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """磁盘残留 .env 只能补缺，不能覆写显式注入的 env。"""
    import delector.server as server

    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=FROM_STALE_DOTENV\n"
        "DELECTOR_DATA_DIR=FROM_STALE_DOTENV\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "INJECTED_EXPLICIT")
    monkeypatch.setenv("DELECTOR_DATA_DIR", "INJECTED_EXPLICIT")

    server.load_env()  # 真跑启动期环境载入：dotenv + 手写兜底两条路径

    assert os.environ["DEEPSEEK_API_KEY"] == "INJECTED_EXPLICIT"
    assert os.environ["DELECTOR_DATA_DIR"] == "INJECTED_EXPLICIT"


def test_write_failure_leaves_no_partial_json_and_detail_has_no_path(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注入 ENOSPC 到 fsync：半截文件必须清掉，500 detail 只回错误类别。"""
    import delector.routes.backup as backup_routes

    export_dir = tmp_path / "Downloads"
    export_dir.mkdir()
    monkeypatch.setattr(backup_routes, "_export_download_dir", lambda: (export_dir, False))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)

    def _fsync_boom(_fd: int) -> None:
        # filename 带绝对路径：旧实现 f"写入失败：{exc}" 会把它整段回给前端。
        raise OSError(errno.ENOSPC, "no space left on device", str(export_dir / "wb.json"))

    monkeypatch.setattr(backup_routes.os, "fsync", _fsync_boom)

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"type": "wb-sync", "version": 1}},
    )

    assert resp.status_code == 500, resp.text
    detail = resp.json()["detail"]
    assert "写入失败" in detail  # 既有 500 契约不放松
    assert str(export_dir) not in detail, "绝对路径泄露给前端"
    assert "wb.json" not in detail, "连文件名都不应带"
    assert list(export_dir.iterdir()) == [], "半截 JSON 残留"


def test_lock_degradation_emits_visible_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """锁原语不可用 + once 已静默 ⇒ 仍返回降级句柄，但 MUST 留一条可见告警。"""
    from delector.core import instance_lock

    paths = instance_lock.LockPaths(
        lock=str(tmp_path / "instance.lock"),
        meta=str(tmp_path / "instance.json"),
    )
    record = instance_lock.LockRecord(
        pid=os.getpid(),
        version="t8",
        port=8000,
        data_dir=str(tmp_path),
        acquired_at="",
    )
    monkeypatch.setattr(instance_lock, "_acquire_os_lock", lambda fd: None)
    monkeypatch.setattr(instance_lock, "_PRIMITIVE_MISSING_WARNED", True)

    handle = instance_lock.try_acquire(paths, record)

    assert isinstance(handle, instance_lock.LockHandle)
    assert handle.is_degraded is True  # 锁是加固层：不抛、不拒启
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "不是真互斥" in err


def test_dotenv_path_must_not_override_explicit_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """钉住 dotenv 本身那条路径：注入假模块，使守卫不依赖本机是否装了 dotenv。

    本机未装 python-dotenv 时，`load_env()` 走 except + 手写兜底，
    `override=False` 的改动无人守 —— 单改回 `override=True` 仍能绿。
    这里显式注入模块并模拟「override=True 会覆写显式 env」的真实语义。
    """
    import sys
    import types

    import delector.server as server

    seen: list[dict] = []

    def fake_load_dotenv(**kwargs) -> None:
        seen.append(kwargs)
        if kwargs.get("override", False):
            os.environ["DEEPSEEK_API_KEY"] = "FROM_STALE_DOTENV"

    monkeypatch.setitem(
        sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=fake_load_dotenv)
    )
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=FROM_STALE_DOTENV\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "INJECTED_EXPLICIT")

    server.load_env()

    assert seen and seen[0].get("override") is False, (
        "dotenv 被允许覆写显式注入的 env（override 不是 False）"
    )
    assert os.environ["DEEPSEEK_API_KEY"] == "INJECTED_EXPLICIT"
