# -*- coding: utf-8 -*-
"""tests/db_cleanup.py::remove_db_files 的 TDD 单测（先 RED 后 GREEN）。

背景：17 个 ``clean_db`` fixture 曾把删库失败 ``except OSError: pass`` 静默吞掉——
Windows 上句柄未 close 时 ``os.remove`` 抛 ``PermissionError``（OSError 子类），
吞掉它 = 残留行跨用例污染（假红/假绿）。本文件钉住新契约：gc + 有限次重试后
仍删不掉 ⇒ 抛出**点名根因与修法**的异常（消息含 "close" 与 "db_conn"）。

用例 ③ 是核心 RED：打开连接**故意不 close**（本地变量持有引用、期间不释放，
helper 内部的 gc.collect() 清不掉可达对象）→ 调 helper ⇒ 必须抛。
修复前（静默 pass 行为）此用例必红。

用例 ③④ 依赖 Windows 句柄语义（POSIX 允许 unlink 已打开的文件，句柄锁不可
观测），非 Windows 显式跳过并给理由，保证 ubuntu CI 不假红也不假绿。
"""

import os
import sqlite3
import sys
import threading
import time

import pytest
from db_cleanup import remove_db_files

_WIN32_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="POSIX 允许 unlink 已打开的文件，『句柄未 close 删不掉』仅 Windows 可观测",
)


def _make_db_trio(base: str) -> None:
    """造出主库 + ``-wal`` + ``-shm`` 三件套（内容无所谓，存在即可）。"""
    for suffix in ("", "-wal", "-shm"):
        with open(base + suffix, "wb") as fh:
            fh.write(b"x")


def test_removes_all_three_files(tmp_path):
    """① 三件套正常删除：造三个文件 → 调用 → 全消失。"""
    base = str(tmp_path / "trio.db")
    _make_db_trio(base)
    remove_db_files(base)
    for suffix in ("", "-wal", "-shm"):
        assert not os.path.exists(base + suffix), f"{base + suffix} 应被删除"


def test_idempotent_when_files_absent(tmp_path):
    """② 文件不存在 ⇒ 幂等不抛；部分存在（只有主库）同样不抛且清干净。"""
    remove_db_files(str(tmp_path / "never_existed.db"))
    base = str(tmp_path / "partial.db")
    with open(base, "wb") as fh:
        fh.write(b"x")
    remove_db_files(base)
    for suffix in ("", "-wal", "-shm"):
        assert not os.path.exists(base + suffix), f"{base + suffix} 应被删除"


@_WIN32_ONLY
def test_unclosed_connection_fails_loudly(tmp_path):
    """③ 核心 RED：连接不 close（引用可达，GC 清不掉）⇒ helper 必须抛并点名根因。"""
    base = str(tmp_path / "leaked.db")
    conn = sqlite3.connect(base)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.execute("INSERT INTO t VALUES ('残留行')")
    conn.commit()
    # 故意不 close：conn 由局部变量持有（可达，helper 的 gc.collect() 断不了它），
    # Windows 上文件句柄未释放，os.remove 必抛 PermissionError。
    try:
        with pytest.raises(OSError) as excinfo:
            remove_db_files(base)
    finally:
        conn.close()  # 本测试自己不留泄漏
    msg = str(excinfo.value)
    assert "close" in msg, f"异常消息必须点名『句柄未 close』根因，实际：{msg!r}"
    assert "db_conn" in msg, f"异常消息必须点名修法 db_conn/db_progress_conn，实际：{msg!r}"


def test_os_remove_failure_fails_loudly(tmp_path, monkeypatch):
    """⑤ 平台无关的 fail-loudly 契约守卫：os.remove 恒抛 ⇒ helper 必须抛并点名根因。

    这是用例 ③④ 在非 Windows 平台的替身：③④ 依赖 Windows 句柄语义
    （POSIX unlink 已打开文件不报错），在 ubuntu CI 上被 skip ⇒ fail-loudly
    契约零守卫。本用例不依赖任何平台行为——直接把 ``os.remove`` 换成恒抛
    ``OSError(13, "permission denied")`` 的桩，钉住两件事：
    (1) 最终失败必须**抛**（而非静默 ``except OSError: pass``）；
    (2) 异常消息必须**同时包含** "close"（根因提示）与 "db_conn"（修法提示）。
    本用例在 CI（含 ubuntu）上必须执行，**不得**加 skipif；若有人把 helper
    的最终 raise 改回静默吞掉，本用例必红（判别力来源）。

    patch 目标选全局 ``os.remove``：helper 是 ``import os`` 后调 ``os.remove``，
    而 ``db_cleanup.os`` 与全局 ``os`` 是同一个模块对象，两种写法效果等价；
    选 ``os.remove`` 是 monkeypatch 的标准写法，用例结束自动恢复。
    """
    base = str(tmp_path / "stubbed.db")
    with open(base, "wb") as fh:  # 目标文件必须真实存在，否则 helper 幂等跳过
        fh.write(b"x")

    def always_denied(path, *args, **kwargs):
        raise OSError(13, "permission denied")

    monkeypatch.setattr(os, "remove", always_denied)
    with pytest.raises(OSError) as excinfo:
        remove_db_files(base)
    monkeypatch.undo()  # 让下方断言失败时错误信息本身可读（桩不再干扰其他工具）
    msg = str(excinfo.value)
    assert "close" in msg, f"异常消息必须点名『句柄未 close』根因，实际：{msg!r}"
    assert "db_conn" in msg, f"异常消息必须点名修法 db_conn/db_progress_conn，实际：{msg!r}"


@_WIN32_ONLY
def test_retry_succeeds_after_lock_released(tmp_path):
    """④ 重试路径：锁先在（前 1~2 次尝试必失败），线程释放后重试成功 ⇒ 不抛。

    时序假设：持锁线程打开连接后 0.15s 才 close；helper 的删尝试点 ≈ 0 / 0.1 /
    0.2 / 0.3s（首删 + 3 次重试，每次失败后 gc + sleep 0.1s）→ 至少 0.2s 一点
    落在 close 之后，余量 ≥ 50ms。**非恒真**：若线程永不 close，helper 最终
    抛 ⇒ 本用例红。
    """
    base = str(tmp_path / "retry.db")
    sqlite3.connect(base).close()  # 先把文件造出来
    opened = threading.Event()
    holder: dict = {}

    def hold_lock_briefly() -> None:
        c = sqlite3.connect(base)
        c.execute("SELECT 1")
        holder["conn"] = c  # 持引用，防 GC 提前释放句柄
        opened.set()
        time.sleep(0.15)  # 覆盖 helper 的前 1–2 次尝试窗口
        c.close()

    worker = threading.Thread(target=hold_lock_briefly)
    worker.start()
    assert opened.wait(timeout=5), "持锁线程未按时打开连接"
    remove_db_files(base)  # 前 1~2 次失败，重试成功 ⇒ 不抛
    for suffix in ("", "-wal", "-shm"):
        assert not os.path.exists(base + suffix), f"{base + suffix} 应被删除"
    worker.join(timeout=5)
