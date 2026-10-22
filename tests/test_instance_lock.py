# -*- coding: utf-8 -*-
r"""`instance_lock` 的记录/路径/元数据读写契约（Task 1）。

为什么单独钉 `for_platform`
--------------------------
锁路径必须是**全局唯一**（ADR-0019 §6.4），与数据目录无关。若这里跟着 `resolve_data_dir`
走，便携版与安装版就会各锁各的 —— 两个窗口、两个库，正是单实例要消灭的状态面。
故用显式 env 字典分别模拟 Windows / POSIX，断言**完整字面落点**，而不是依赖跑测试的
主机平台（CI 与本机平台不同，跟着平台走的断言会在另一边静默失效）。

为什么钉「读损坏 ⇒ None」而不是抛
--------------------------------
`instance.json` 是**元数据**、不是锁本体：锁被持有但 meta 半截/缺失是合法中间态（spec §3.1）。
此时读方必须降级成「版本未知」，绝不能把 JSON 解析异常抛到启动主链上。每个字段单独变异
一次（其余字段保持合法），否则某条 `isinstance` 守卫被删掉时，别的守卫会替它兜底，
测试照样全绿 —— 这正是「测试没咬住」的形态。

为什么钉「回写不碰 instance.lock」
---------------------------------
POSIX 的 `flock` 锁的是 inode：若 `os.replace` 的目标写成 `paths.lock`，锁会指向已 unlink
的旧 inode，**单实例静默失效**。故这里同时钉锁文件的内容与 inode 不被回写改变。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Tuple, cast

import pytest

from delector.core.instance_lock import LockPaths, LockRecord, read_record, write_record


def _paths(tmp_path: Path) -> LockPaths:
    """临时目录下的锁路径；不调用 `for_platform`，避免用例互相依赖。"""
    return LockPaths(
        lock=str(tmp_path / "instance.lock"),
        meta=str(tmp_path / "instance.json"),
    )


def _handle(paths: LockPaths) -> object:
    """Task 1 只约定 `handle.paths`；用最小替身，不提前引入 Task 2 的 `LockHandle`。"""
    return SimpleNamespace(paths=paths)


def _as_slash(path: str) -> str:
    """断言字面落点前统一成 `/`：两种分隔符都替换，断言才与跑测主机平台无关。"""
    return path.replace("\\", "/")


_VALID_META: dict[str, object] = {
    "pid": 4321,
    "version": "5.19.0",
    "port": 8002,
    "data_dir": r"D:\学习资料\DeLector",
    "acquired_at": "2026-10-21T12:00:00+08:00",
}


def _meta_with(field: str, value: object) -> dict[str, object]:
    """复制一份合法记录、只改一个字段：保证失败能归因到那一条守卫。"""
    meta = dict(_VALID_META)
    meta[field] = value
    return meta


def _json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


# 每条 (case_id, 文件原文)；原文为 None 表示文件不存在。
_CORRUPT_CASES: List[Tuple[str, Optional[str]]] = [
    ("missing", None),
    ("not-json", "{not json"),
    ("non-dict-list", _json_text([1, 2])),
    ("non-dict-string", _json_text("hello")),
    ("non-dict-null", "null"),
    ("pid-wrong-type", _json_text(_meta_with("pid", "x"))),
    ("version-wrong-type", _json_text(_meta_with("version", 519))),
    ("port-wrong-type", _json_text(_meta_with("port", "8000"))),
    ("data-dir-wrong-type", _json_text(_meta_with("data_dir", None))),
    ("acquired-at-wrong-type", _json_text(_meta_with("acquired_at", ["x"]))),
    ("pid-bool", _json_text(_meta_with("pid", True))),
    ("port-bool", _json_text(_meta_with("port", False))),
    # 缺字段必须显式钉：`data.get()` 返回 None 与「字段类型错」是两条不同的失败面。
    ("missing-fields-only-pid", _json_text({"pid": 1})),
    (
        "missing-field-acquired-at",
        _json_text({"pid": 1, "version": "5.19.0", "port": 8000, "data_dir": "D:/x"}),
    ),
]


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    record = LockRecord(
        pid=4321,
        version="5.19.0",
        port=8002,
        data_dir=r"D:\学习资料\DeLector",
        acquired_at="2026-10-21T12:00:00+08:00",
    )

    write_record(_handle(paths), record)

    assert read_record(paths) == record


@pytest.mark.parametrize("case_id, meta_text", _CORRUPT_CASES, ids=[case for case, _ in _CORRUPT_CASES])
def test_read_record_returns_none_for_missing_and_corrupt(
    tmp_path: Path, case_id: str, meta_text: Optional[str]
) -> None:
    paths = _paths(tmp_path)
    if meta_text is not None:
        Path(paths.meta).write_text(meta_text, encoding="utf-8")

    assert read_record(paths) is None, f"case={case_id}"


def test_for_platform_windows_and_posix() -> None:
    win = LockPaths.for_platform({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"})
    posix = LockPaths.for_platform({"HOME": "/home/x", "XDG_DATA_HOME": "/home/x/.local/share"})

    assert _as_slash(win.lock) == "C:/Users/x/AppData/Local/DeLector/instance.lock"
    assert _as_slash(win.meta) == "C:/Users/x/AppData/Local/DeLector/instance.json"
    assert _as_slash(posix.lock) == "/home/x/.local/share/DeLector/instance.lock"
    assert _as_slash(posix.meta) == "/home/x/.local/share/DeLector/instance.json"

    assert win.lock != win.meta
    assert posix.lock != posix.meta


def test_write_record_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = Path(paths.lock)
    lock_path.write_bytes(b"sentinel")
    before = lock_path.stat()
    record = LockRecord(
        pid=1,
        version="5.19.0",
        port=8000,
        data_dir=str(tmp_path / "数据"),
        acquired_at="2026-10-21T12:00:00+08:00",
    )

    write_record(_handle(paths), record)

    assert lock_path.read_bytes() == b"sentinel"
    if before.st_ino != 0:  # Windows 某些文件系统不提供稳定 inode，此时只靠内容钉住
        assert lock_path.stat().st_ino == before.st_ino
    assert sorted(os.listdir(tmp_path)) == ["instance.json", "instance.lock"]
    payload = json.loads(Path(paths.meta).read_text(encoding="utf-8"))
    assert payload["pid"] == record.pid
    assert payload["data_dir"] == record.data_dir


def test_write_record_cleans_temp_on_non_oserror_failure(tmp_path: Path) -> None:
    """清理必须挂在 `finally`：`json.dump` 抛 TypeError 时同样不能留半截 `.tmp`。"""
    paths = _paths(tmp_path)
    record = LockRecord(
        pid=1,
        version=cast(str, object()),
        port=8000,
        data_dir=str(tmp_path),
        acquired_at="2026-10-21T12:00:00+08:00",
    )

    with pytest.raises(TypeError):
        write_record(_handle(paths), record)

    leftovers = [name for name in os.listdir(tmp_path) if name.endswith(".tmp")]
    assert leftovers == []


def test_read_record_accepts_bom_prefixed_meta(tmp_path: Path) -> None:
    """Windows 编辑器可能给 JSON 加 BOM；带 BOM 的元数据仍必须读成完整记录，而不是版本未知。"""
    paths = _paths(tmp_path)
    payload = b"\xef\xbb\xbf" + json.dumps(_VALID_META, ensure_ascii=False).encode("utf-8")
    Path(paths.meta).write_bytes(payload)

    assert read_record(paths) == LockRecord(
        pid=4321,
        version="5.19.0",
        port=8002,
        data_dir=r"D:\学习资料\DeLector",
        acquired_at="2026-10-21T12:00:00+08:00",
    )
