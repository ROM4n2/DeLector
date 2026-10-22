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

import contextlib
import errno
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import IO, Callable, List, Optional, Tuple, cast

import pytest

from delector.core import instance_lock
from delector.core.instance_lock import (
    UNKNOWN_RECORD,
    LockHandle,
    LockPaths,
    LockRecord,
    read_record,
    try_acquire,
    write_record,
)


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


# ── 跨进程锁原语 ──
#
# 为什么用「两次独立 os.open」而不是 fork：
# Windows 没有 fork，且 msvcrt.locking / fcntl.flock 的互斥性都绑定在**内核句柄**上，
# 同进程内两次独立 open 得到的正是两个句柄 —— 覆盖的失败面与真子进程相同（Task 3 再验真进程）。
# 若只对同一个 fd 重复调用，锁永远「成功」，这两个用例会退化成永不失败的空断言。


def _record(tmp_path: Path, port: int = 8000) -> LockRecord:
    return LockRecord(
        pid=os.getpid(),
        version="5.19.0",
        port=port,
        data_dir=str(tmp_path),
        acquired_at="2026-10-21T12:00:00+08:00",
    )


def test_second_acquire_returns_holder_record(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    record = _record(tmp_path)

    first = try_acquire(paths, record)
    assert isinstance(first, LockHandle), f"首次取锁必须拿到 LockHandle，实际是 {type(first).__name__}"
    assert first.record.pid == os.getpid()
    assert first.record.version == "5.19.0"

    second = try_acquire(paths, record)
    assert isinstance(second, LockRecord), f"锁被持有时必须返回对方的 LockRecord，实际是 {type(second).__name__}"
    assert second == first.record

    first.release()


def test_release_is_idempotent_and_allows_reacquire(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    record = _record(tmp_path)

    first = try_acquire(paths, record)
    assert isinstance(first, LockHandle)
    first.release()
    first.release()  # 幂等：退出路径可能被调用两次（finally + 上下文管理器）

    again = try_acquire(paths, record)
    assert isinstance(again, LockHandle), "release() 之后必须能重新取到锁"
    again.release()


def test_held_lock_with_missing_meta_returns_unknown_record(tmp_path: Path) -> None:
    """锁被持有但 meta 被删（升级残留 / 手工清理）是合法中间态：必须降级成版本未知，不抛异常。"""
    paths = _paths(tmp_path)
    record = _record(tmp_path)

    handle = try_acquire(paths, record)
    assert isinstance(handle, LockHandle)
    try:
        os.unlink(paths.meta)
        second = try_acquire(paths, record)
    finally:
        handle.release()

    assert isinstance(second, LockRecord), f"meta 缺失时必须返回 unknown 记录，实际是 {type(second).__name__}"
    assert second == UNKNOWN_RECORD
    assert second.pid == 0


def test_write_record_does_not_void_the_lock(tmp_path: Path) -> None:
    """回归哨兵：回写 meta 若误写到 paths.lock（os.replace），锁会指向旧 inode 而静默失效。"""
    paths = _paths(tmp_path)
    handle = try_acquire(paths, _record(tmp_path, port=8000))
    assert isinstance(handle, LockHandle)

    updated = replace(handle.record, port=8002)
    write_record(handle, updated)

    second = try_acquire(paths, updated)
    try:
        assert isinstance(second, LockRecord), "回写 meta 之后锁必须仍然有效（否则单实例静默失效）"
        assert second == updated
    finally:
        handle.release()


# ── 降级响亮度 / errno 归属 / seek(0) / 回写失败不穿出 ──
#
# 为什么这四条必须存在
# -------------------
# `except OSError: return False` 把「原语坏了」读成「别人持有锁」：NFS/SMB 上 `flock` 返 `ENOLCK`
# 时既不降级也不打 WARNING，用户只会看到「已有实例在运行」。同理 `write_record` 未包 try 会在
# Windows 并发读时把 `WinError 32` 抛穿 `try_acquire` 并留下悬空锁 fd。下面四个失败面各钉一条。
#
# 平台分支交代：两条原语**都在本机跑**（`msvcrt` 分支与 `fcntl` 分支都走假模块，不靠 skipif），
# 只有「seek(0) 的作用」这一条本质是 Windows 语义（POSIX 锁的是整个 inode、与 fd offset 无关），
# 故只写 Windows 分支并在用例内显式说明。

#: (原语模块名, 该模块的加锁函数)。本机 `_acquire_os_lock` 实际分派到的那条排在首位 ——
#: 必须**真跑**，不许被 `pytest.mark.skipif` 静默跳掉。
_PRIMITIVES: List[Tuple[str, Callable[[int], Optional[bool]]]] = [
    ("msvcrt", instance_lock._acquire_windows_lock),
    ("fcntl", instance_lock._acquire_posix_lock),
]
_HOST_PRIMITIVE_NAME = "msvcrt" if sys.platform == "win32" else "fcntl"
_PRIMITIVES_UNDER_TEST: List[Tuple[str, Callable[[int], Optional[bool]]]] = sorted(
    _PRIMITIVES, key=lambda item: item[0] != _HOST_PRIMITIVE_NAME
)


def _fake_primitive_module(name: str, exc: OSError) -> SimpleNamespace:
    """假原语模块：名为 `name` 的模块里，唯一的加锁函数直接抛 `exc`（另带调用方会读的常量）。"""

    def _raise(*_args: object) -> None:
        raise exc

    if name == "msvcrt":
        return SimpleNamespace(locking=_raise, LK_NBLCK=2)
    return SimpleNamespace(flock=_raise, LOCK_EX=2, LOCK_NB=4)


def test_missing_primitive_warns_exactly_once_and_never_fails_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """降级必须响亮但只喊一次：`_PRIMITIVE_MISSING_WARNED` 此前完全没有回归保护。"""
    paths = _paths(tmp_path)
    record = _record(tmp_path)
    monkeypatch.setattr(instance_lock, "_load_primitive", lambda name: None)
    monkeypatch.setattr(instance_lock, "_PRIMITIVE_MISSING_WARNED", False)

    with caplog.at_level(logging.WARNING, logger="delector"):
        first = try_acquire(paths, record)
        second = try_acquire(paths, record)

    assert isinstance(first, LockHandle), "原语缺失只能降级成句柄，不能抛也不能返回对方记录"
    assert first._fd == -1
    assert isinstance(second, LockHandle), "第二次同样降级成句柄"
    assert second._fd == -1

    warnings = [item for item in caplog.records if item.levelno == logging.WARNING]
    if len(warnings) != 1:
        raise AssertionError(f"降级 WARNING 应恰好 1 条，实际 {len(warnings)} 条：{[i.getMessage() for i in warnings]}")
    # WARNING 必须点明「不是真互斥」，否则读日志的人会以为单实例仍成立。
    assert "本次不是真互斥" in warnings[0].getMessage()


@pytest.mark.parametrize(
    "module_name, acquire",
    _PRIMITIVES_UNDER_TEST,
    ids=[name for name, _ in _PRIMITIVES_UNDER_TEST],
)
def test_non_held_errno_degrades_but_held_errno_is_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    module_name: str,
    acquire: Callable[[int], Optional[bool]],
) -> None:
    """`ENOLCK`（NFS/SMB 无锁支持）不是「被持有」，必须降级成 `None` 并留 WARNING；`EACCES` 才是。"""
    fd = os.open(tmp_path / "instance.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        monkeypatch.setattr(
            instance_lock,
            "_load_primitive",
            lambda name: _fake_primitive_module(module_name, OSError(errno.ENOLCK, "no locks available")),
        )
        with caplog.at_level(logging.WARNING, logger="delector"):
            assert acquire(fd) is None, "ENOLCK 是原语不可用，必须降级成 None 而不是『被持有』"
        assert any("本次不是真互斥" in item.getMessage() for item in caplog.records), (
            "非持有类 errno 必须留下 WARNING；静默归成『被持有』就是把故障藏起来"
        )

        caplog.clear()
        monkeypatch.setattr(
            instance_lock,
            "_load_primitive",
            lambda name: _fake_primitive_module(module_name, OSError(errno.EACCES, "resource busy")),
        )
        with caplog.at_level(logging.WARNING, logger="delector"):
            assert acquire(fd) is False, "EACCES/EAGAIN 才是『别人持有』，且不应产生降级 WARNING"
        assert caplog.records == [], "『被持有』是正常判定结果，不该刷降级日志"
    finally:
        os.close(fd)


def test_windows_lock_pulls_fd_offset_back_to_zero(tmp_path: Path) -> None:
    """删掉 `os.lseek(fd, 0, SEEK_SET)` 时本用例转红：那时 B 会锁到 byte 5，与 A 的 byte 0 不冲突。

    POSIX 的 `flock` 锁的是整个 inode、与 fd offset 无关，等价断言在那边恒真（假模块也证明不了
    offset 无关性），故只写 Windows 分支；在非 win32 主机上运行时显式跳过并说明原因。
    """
    if sys.platform != "win32":
        pytest.skip("msvcrt 区间锁语义专属：POSIX flock 锁整个 inode，offset 断言在那边恒真")

    lock_path = tmp_path / "instance.lock"
    fd_a = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fd_b = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        assert instance_lock._acquire_windows_lock(fd_a) is True
        os.lseek(fd_b, 5, os.SEEK_SET)
        # 实现必须把 offset 拉回 0，否则 B 会锁在 byte 5、与 A 的区间不冲突，从而误判为成功。
        assert instance_lock._acquire_windows_lock(fd_b) is False
    finally:
        os.close(fd_b)
        os.close(fd_a)


def test_write_record_failure_does_not_escape_try_acquire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """回写失败只影响「别人看到谁」，不影响互斥：不得抛，也不得丢掉已持有的锁。"""
    paths = _paths(tmp_path)
    record = _record(tmp_path)

    def _boom(handle: object, new_record: LockRecord) -> None:
        raise OSError(errno.EIO, "模拟回写失败")

    monkeypatch.setattr(instance_lock, "write_record", _boom)

    with caplog.at_level(logging.WARNING, logger="delector"):
        handle = try_acquire(paths, record)

    assert isinstance(handle, LockHandle), "回写失败不得把异常穿出 try_acquire（会留下悬空锁 fd）"
    assert handle._fd >= 0, "锁已经拿到，句柄必须带着真 fd"
    assert any("本次不是真互斥" in item.getMessage() for item in caplog.records), "回写失败必须留痕"

    try:
        second = try_acquire(paths, record)
    finally:
        handle.release()

    assert isinstance(second, LockRecord), "第一次拿到的锁必须仍然有效（第二次应撞上持有者而不是重新上锁）"


def test_acquire_creates_parent_dir_of_both_lock_and_meta(tmp_path: Path) -> None:
    """锁与 meta 分处两个目录时两个父目录都要建：只建 meta 父目录 ⇒ `os.open` 抛 ENOENT ⇒ 降级。

    现有用例的 `LockPaths` 全部由 `_paths()` 造（同目录），把这条修复退回只建 meta 父目录时
    28 条仍全绿 —— 故这里显式拆成 `a/` 与 `b/` 两个待建目录。
    """
    paths = LockPaths(
        lock=str(tmp_path / "a" / "instance.lock"),
        meta=str(tmp_path / "b" / "instance.json"),
    )

    handle = try_acquire(paths, _record(tmp_path))
    assert isinstance(handle, LockHandle), f"不同目录也必须取到句柄，实际是 {type(handle).__name__}"
    try:
        assert handle._fd >= 0, "不同目录也必须拿到真锁（降级至 _fd == -1 说明 lock 的父目录没建）"
    finally:
        handle.release()


def test_non_held_errno_does_not_consume_missing_primitive_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`ENOLCK` 是「原语存在但加锁被拒」，不是「原语缺失」：不得冒充，也不得吃掉那次唯一告警。

    `_PRIMITIVE_MISSING_WARNED` 被误置真时，同进程后续**真·原语缺失**会零 warning（二阶静默），
    故这里用例开始先显式归零，不依赖执行顺序。
    """
    paths = _paths(tmp_path)
    monkeypatch.setattr(instance_lock, "_PRIMITIVE_MISSING_WARNED", False)
    monkeypatch.setattr(
        instance_lock,
        "_load_primitive",
        lambda name: _fake_primitive_module(_HOST_PRIMITIVE_NAME, OSError(errno.ENOLCK, "no locks available")),
    )

    with caplog.at_level(logging.WARNING, logger="delector"):
        handle = try_acquire(paths, _record(tmp_path))

    assert isinstance(handle, LockHandle), "加锁被拒只能降级成句柄，不能抛也不能返回对方记录"
    assert handle._fd == -1
    messages = [item.getMessage() for item in caplog.records]
    assert any("本次不是真互斥" in message for message in messages), "加锁被拒必须留一条含真实 errno 的 WARNING"
    assert not any("无可用的文件锁原语" in message for message in messages), (
        "ENOLCK 不是原语缺失：再喊一条『无可用的文件锁原语』既是假陈述，也会让后续真缺失静默"
    )
    assert instance_lock._PRIMITIVE_MISSING_WARNED is False, "加锁被拒不得置『原语缺失已告警』旗标"


def test_unserializable_record_releases_fd_and_allows_reacquire(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """记录不可序列化（`TypeError`）时：不抛、响亮降级，且锁 fd 必须真被收尸（否则本次进程再也取不到锁）。"""
    paths = _paths(tmp_path)
    bad = LockRecord(
        pid=1,
        version=cast(str, object()),
        port=8000,
        data_dir=str(tmp_path),
        acquired_at="2026-10-21T12:00:00+08:00",
    )

    with caplog.at_level(logging.WARNING, logger="delector"):
        degraded = try_acquire(paths, bad)

    assert isinstance(degraded, LockHandle), "序列化失败不得把异常穿出 try_acquire（模块承诺启动期不抛）"
    assert degraded._fd == -1, "已释放锁的句柄必须是降级句柄"
    assert any("本次不是真互斥" in item.getMessage() for item in caplog.records), "显式点名必须留痕"

    again = try_acquire(paths, _record(tmp_path))
    assert isinstance(again, LockHandle), "锁必须真的被释放：后续取锁应成功，而不是撞上自己悬空的 fd"
    again.release()


# ── 跨进程（真 spawn）──
#
# 为什么必须另开这一节
# -------------------
# 上面所有用例都跑在**一个进程**里：互斥性只经「同进程两次 `os.open` 得到两个内核句柄」间接验证，
# 这盖不住两件只有真进程才能验的事：
#   ① 锁在**另一个 OS 进程**手里时，本进程必须被真的挡住（不是句柄不同，而是内核拒绝）；
#   ② 子进程被 `terminate()` 后，锁必须**随进程退出自愈** —— 本模块刻意不做 pid 探活，
#      唯一依赖就是「OS 释放已死进程的锁」，这条承诺此前一条测试都没钉。
# Windows 没有 fork，`python -c` + spawn 是唯一可移植路径，正好也是产品真实形态
# （`start.py` 在用户双击时就是这么跑起来的）。
#
# 反脆弱约定（都踩过）：
#   - 等待子进程的 `HELD` 用**队列 + 硬上界**，不用裸 sleep 轮询；
#   - `finally` 必收尸：`terminate()` → `wait(10)` → `kill()` 兜底 → `wait(10)`，绝不留下裸 sleep 的子进程；
#   - 任何断言失败都把子进程 stdout/stderr 原文塞进消息：否则「子进程其实没拿到锁」会被读成父进程的 bug。

#: 子进程等锁期间在 `HELD` 之后保持持有的时长：远大于父进程全部动作，靠 `terminate()` 结束（不是靠它自己退出）。
_CHILD_HOLD_SECONDS = 30
#: 等 `HELD` 的上界。子进程 import 本仓库代码约 0.3s，10s 是「本机不可能慢成这样」的余量。
_HELD_TIMEOUT = 10.0
#: 收尸上界：`terminate()` 之后的 `wait()` 与 `kill()` 兜底的 `wait()` 都用它。
_TERMINATE_TIMEOUT = 10.0
#: 队列 EOF 哨兵：泵线程读到流结束就投它，让「子进程提前死了」立刻变成可诊断失败而不是干等 10s。
_CHILD_EOF = ""

_CHILD_SCRIPT = r'''
import os
import sys
import time

from delector.core.instance_lock import LockHandle, LockPaths, LockRecord, try_acquire

base = sys.argv[1]
paths = LockPaths(
    lock=os.path.join(base, "instance.lock"),
    meta=os.path.join(base, "instance.json"),
)
record = LockRecord(
    pid=os.getpid(),
    version="5.19.0",
    port=8000,
    data_dir=base,
    acquired_at="2026-10-21T12:00:00+08:00",
)
handle = try_acquire(paths, record)
if not isinstance(handle, LockHandle):
    # 子进程自己没拿到锁：父进程后面「被挡住」就可能是假的，必须显式失败并把身份打到 stderr。
    sys.stderr.write("CHILD_NOT_HOLDER %r\n" % (handle,))
    sys.stderr.flush()
    raise SystemExit(3)
print("HELD %d" % os.getpid(), flush=True)
time.sleep(@@HOLD_SECONDS@@)
handle.release()
'''.replace("@@HOLD_SECONDS@@", str(_CHILD_HOLD_SECONDS))


def _pump_lines(stream: "IO[str]", sink: "queue.Queue[str]") -> None:
    """后台泵：把子进程 stdout 逐行投进队列，流结束投 EOF 哨兵。

    为什么不用 `communicate(timeout=...)`：它要等**进程退出**才返回，而子进程故意持有 30s，
    必然先超时；而裸 `readline()` 在子进程卡死时会永久阻塞。队列 + 上界是唯一两头都咬住的做法。
    """
    try:
        for line in stream:
            sink.put(line)
    finally:
        sink.put(_CHILD_EOF)


@dataclass
class _ChildProcess:
    """真子进程句柄：等待带上界，收尸幂等（`finally` 之后仍可再调 `stop()`）。"""

    proc: "subprocess.Popen[str]"
    lines: "queue.Queue[str]"
    pump: "threading.Thread"
    captured: List[str] = field(default_factory=list)

    def await_held(self, timeout: float = _HELD_TIMEOUT) -> int:
        """等到 `HELD <pid>`，返回子进程 pid；超时或子进程早退都抛带 stdout/stderr 原文的断言。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(self.describe(f"子进程 {timeout:.0f}s 内未打印 HELD"))
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(self.describe(f"子进程 {timeout:.0f}s 内未打印 HELD")) from None
            if line == _CHILD_EOF:
                raise AssertionError(self.describe("子进程未打印 HELD 就退出了"))
            self.captured.append(line)
            if line.startswith("HELD "):
                return int(line.split()[1])

    def stop(self) -> None:
        """terminate → wait → kill 兜底。幂等：进程已退出时只剩 `join`。"""
        if self.proc.poll() is None:
            # `poll()` 判活与 `terminate()` 之间存在窗口：子进程可能刚好在此间退出，
            # Windows 上 `terminate()` 会抛 OSError/PermissionError。若在 `finally` 里抛出，
            # 会顶掉真正的 AssertionError（「子进程未打印 HELD」），故这里的收尸异常一律吞掉。
            with contextlib.suppress(OSError):
                self.proc.terminate()
        try:
            self.proc.wait(timeout=_TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=_TERMINATE_TIMEOUT)
        self.pump.join(timeout=_TERMINATE_TIMEOUT)
        if self.pump.is_alive():
            # join 超时不能静默丢弃：否则后续排空队列可能少行，describe() 消息残缺却不说。
            self.captured.append("<pump 未在窗口内结束，输出可能不完整>")

    def collect_output(self) -> Tuple[str, str]:
        """收尸并返回子进程 stdout/stderr 原文（`stop()` 之后 stderr 已到 EOF，读不会阻塞）。"""
        self.stop()
        while True:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            if line != _CHILD_EOF:
                self.captured.append(line)
        stderr_text = ""
        if self.proc.stderr is not None:
            stderr_text = self.proc.stderr.read() or ""
        return "".join(self.captured), stderr_text

    def describe(self, reason: str) -> str:
        """把失败原因和子进程原文拼成一条消息，并顺手收尸（断言失败也不留僵尸）。"""
        stdout_text, stderr_text = self.collect_output()
        return f"{reason}\n--- child stdout ---\n{stdout_text}\n--- child stderr ---\n{stderr_text}"


def _spawn_child(tmp_path: Path) -> _ChildProcess:
    """起真子进程跑内联脚本；`cwd` + `PYTHONPATH` 双写，保证它 import 到**本仓库**的代码。"""
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root)] + ([inherited] if inherited else []))
    # 子进程只 print ASCII，但显式钉住编码，免得继承到奇怪 locale 时 print 抛 UnicodeError。
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, str(tmp_path)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    lines: "queue.Queue[str]" = queue.Queue()
    if proc.stdout is None:  # stdout=PIPE 保证不为 None；显式收窄给类型检查器看
        raise AssertionError("stdout=PIPE 却拿到 None")
    pump = threading.Thread(target=_pump_lines, args=(proc.stdout, lines), daemon=True)
    pump.start()
    return _ChildProcess(proc=proc, lines=lines, pump=pump)


def test_subprocess_holder_blocks_parent_and_os_release_heals(tmp_path: Path) -> None:
    """真子进程持有锁 ⇒ 父进程被挡住且读到子进程身份；子进程被杀 ⇒ 父进程立刻能取锁。

    变异自证（计划 Task 3 Step 2）：把 `_acquire_os_lock` 改成直接 `return True`（跳过 OS 锁）后，
    本用例必然转红 —— 那时父进程也能「取到」锁，`blocked` 会是 `LockHandle` 而不是子进程的记录。
    """
    paths = _paths(tmp_path)
    child = _spawn_child(tmp_path)
    try:
        child_pid = child.await_held()

        blocked = try_acquire(paths, _record(tmp_path, port=8002))
        if isinstance(blocked, LockHandle):
            blocked.release()
            raise AssertionError(
                child.describe("子进程持有锁时父进程必须被挡住（返回 LockRecord），实际又拿到了锁句柄")
            )
        assert blocked.pid == child_pid, child.describe(
            f"返回的持有者 pid 必须是子进程 pid {child_pid}，实际 {blocked.pid}"
        )
        # 记录必须来自子进程**回写**的 meta（父进程的候选记录是 port=8002），否则 pid 巧合也对不上语义。
        assert blocked.port == 8000, child.describe("持有者记录必须来自子进程回写的 meta（port=8000）")

        child.stop()

        healed = try_acquire(paths, _record(tmp_path, port=8000))
        if not isinstance(healed, LockHandle):
            raise AssertionError(
                child.describe(f"子进程退出后父进程必须能取锁，实际拿到 {type(healed).__name__}")
            )
        try:
            # 反向自证：降级句柄（`_fd == -1`）同样是 `LockHandle`，单靠 `isinstance` 无法区分
            # 「真拿到锁」与「降级放过」。故用另一条 record 再抢一次：真锁必须挡住本进程自己，
            # 且返回的持有者 pid 必须是本进程 —— 这才能证明 `healed` 是真锁而非降级句柄。
            contender = try_acquire(paths, _record(tmp_path, port=8003))
            if isinstance(contender, LockHandle):
                contender.release()
                raise AssertionError(
                    child.describe("healed 必须是真的锁：第二条 record 竟也取到锁句柄（说明 healed 只是降级放过）")
                )
            assert contender.pid == os.getpid(), child.describe(
                f"持锁者应为本进程 pid {os.getpid()}，实际 {contender.pid}"
            )
        finally:
            healed.release()
    finally:
        child.stop()
