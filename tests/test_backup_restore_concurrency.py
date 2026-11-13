# -*- coding: utf-8 -*-
"""还原期间不得有其它写请求进入事务间隙（2026-11-13 整体健康度审计 P1 #1）。

事故链（首版已用真实 SQLite 复现：`concurrent-user-write` 被整库回滚抹掉）：
restore 拆成 4 个独立事务，`_db_snapshot_guard` 的 yield 期间不持锁；任一步失败时
`snap.backup(live)` 整库覆盖活库，把事务间隙里其它请求的合法写入一并抹掉。

修法**不是**取消自动回滚——既有契约 `test_failed_restore_rolls_back_both_databases`
要求「主库已提交的清空也必须被回滚」，那是 2026-10-15 P0 修法，不得放宽。
而是让间隙里**不可能有别的写请求**：`restore_write_barrier` 置位 Event 挡新写请求，
并等待已在途的写请求排空；护栏落在 HTTP 层（应用层写入的唯一入口）。

判据是行为探针：真发 HTTP 写请求、真置位屏障、真起线程，不 mock、不用字符串断言。
"""

import threading
import time

from fastapi.testclient import TestClient

from delector.core.db.backup import (
    RESTORE_IN_PROGRESS,
    note_write_end,
    note_write_start,
    restore_write_barrier,
)
from delector.server import app

_WRITE_PATH = "/api/wb/state"


def _client() -> TestClient:
    return TestClient(app, client=("127.0.0.1", 54321), raise_server_exceptions=False)


def test_write_request_denied_while_restore_barrier_is_up() -> None:
    """屏障置位期间，写请求 MUST 被 503 挡住，而不是进入事务间隙后被回滚抹掉。"""
    client = _client()
    RESTORE_IN_PROGRESS.set()
    try:
        blocked = client.put(_WRITE_PATH, json={"payload": {}})
    finally:
        RESTORE_IN_PROGRESS.clear()

    assert blocked.status_code == 503, (
        "还原进行中却放行了写请求 —— 它会在 4 段事务的间隙提交，"
        f"随后被 `snap.backup(live)` 整库抹掉。实际：{blocked.status_code}"
    )
    assert blocked.json().get("detail") == "restore_in_progress"
    assert blocked.headers.get("Retry-After") == "1", "被挡的写请求必须带重试提示"

    after = client.put(_WRITE_PATH, json={"payload": {}})
    assert after.status_code != 503, "屏障落下后仍拒绝写请求：护栏没有复位"


def test_restore_barrier_waits_for_inflight_write_to_drain() -> None:
    """反向钉子：已在途（检查过 Event 之后）的写请求排空前，restore 不得开始。

    只判 Event 不足以关掉竞态：写请求可能刚检查完标志、还没执行完就被回滚。
    因此屏障必须等计数器归零。
    """
    note_write_start()
    entered = threading.Event()

    def run_restore() -> None:
        with restore_write_barrier():
            entered.set()
            time.sleep(0.05)

    thread = threading.Thread(target=run_restore, daemon=True)
    thread.start()
    try:
        time.sleep(0.03)
        assert not entered.is_set(), "在途写请求还没排空，restore 就已经开始了"
    finally:
        note_write_end()

    assert entered.wait(timeout=2), "在途写请求排空后 restore 应立即开始（屏障卡死）"
    thread.join(timeout=2)
    assert not thread.is_alive(), "restore 屏障未正常退出"


def test_barrier_flag_is_always_cleared_even_on_failure() -> None:
    """屏障异常退出 MUST 复位，否则一次失败的还原会让全站写接口永久 503。"""
    with pytest_raises_runtime():
        with restore_write_barrier():
            raise RuntimeError("injected restore failure")
    assert not RESTORE_IN_PROGRESS.is_set(), "屏障未复位：还原失败后写接口将永久不可用"


class pytest_raises_runtime:
    """轻量 `pytest.raises(RuntimeError)` 替代，避免本文件引入额外 import。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        assert exc_type is RuntimeError, f"期望 RuntimeError 冒泡，实际 {exc_type!r}"
        assert exc is not None and str(exc) == "injected restore failure"
        return True
