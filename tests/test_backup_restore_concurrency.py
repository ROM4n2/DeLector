# -*- coding: utf-8 -*-
"""还原期间不得有其它请求进入事务间隙（2026-11-13 整体健康度审计 P1 #1）。

事故链（首版已用真实 SQLite 复现：`concurrent-user-write` 被整库回滚抹掉）：
restore 拆成 4 个独立事务，`_db_snapshot_guard` 的 yield 期间不持锁；任一步失败时
`snap.backup(live)` 整库覆盖活库，把事务间隙里其它请求的合法写入一并抹掉。

修法**不是**取消自动回滚——既有契约 `test_failed_restore_rolls_back_both_databases`
要求「主库已提交的清空也必须被回滚」，那是 2026-10-15 P0 修法，不得放宽。
而是让间隙里**不可能有别的请求**：`restore_write_barrier` 用同一把锁原子完成
「检查 Event + 登记在途计数」，置位 Event 挡新请求、等在途请求排空，并用
`RESTORE_OWNER_LOCK` 保证同时只有一次还原。

覆盖**所有** HTTP 方法：文章详情 GET 也会做 `processed_json` 惰性迁移并 UPDATE，
只拦写方法会留一条绕过路径（独立 reviewer MAJOR）。

判据是行为探针：真发 HTTP 请求、真置位屏障、真起线程、真 monkeypatch 接线，
不 mock 掉被守的对象、不用字符串在场断言。
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from delector.core.db import backup as db_backup
from delector.core.db.backup import RESTORE_IN_PROGRESS, restore_write_barrier
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


def test_get_request_is_also_denied_while_barrier_is_up() -> None:
    """GET 也会写库（文章详情惰性迁移），屏障 MUST 覆盖所有方法。"""
    client = _client()
    RESTORE_IN_PROGRESS.set()
    try:
        blocked = client.get("/api/articles/1")
    finally:
        RESTORE_IN_PROGRESS.clear()
    assert blocked.status_code == 503, (
        "只拦写方法留下了 GET 写库的绕过路径（独立 reviewer MAJOR）"
    )


def test_blocked_lan_write_still_carries_cors_header() -> None:
    """屏障的 503 在最内层 return，CORS 层仍须注入 ACAO，否则前端读不到 detail。"""
    client = _client()
    RESTORE_IN_PROGRESS.set()
    try:
        blocked = client.put(
            _WRITE_PATH,
            json={"payload": {}},
            headers={"Origin": "http://192.168.1.10:5173"},
        )
    finally:
        RESTORE_IN_PROGRESS.clear()
    assert blocked.status_code == 503
    assert blocked.headers.get("Access-Control-Allow-Origin") == "http://192.168.1.10:5173", (
        "503 没经过 CORS 层：局域网写请求读不到 detail / Retry-After，重试约定失效"
    )


def test_restore_barrier_waits_for_inflight_request_to_drain() -> None:
    """反向钉子：已在途（检查过 Event 之后）的请求排空前，restore 不得开始。"""
    assert db_backup.note_write_start() is True
    entered = threading.Event()

    def run_restore() -> None:
        with restore_write_barrier():
            entered.set()
            time.sleep(0.05)

    thread = threading.Thread(target=run_restore, daemon=True)
    thread.start()
    try:
        time.sleep(0.03)
        assert not entered.is_set(), "在途请求还没排空，restore 就已经开始了"
    finally:
        db_backup.note_write_end()

    assert entered.wait(timeout=2), "在途请求排空后 restore 应立即开始（屏障卡死）"
    thread.join(timeout=2)
    assert not thread.is_alive(), "restore 屏障未正常退出"


def test_second_concurrent_restore_is_rejected() -> None:
    """BLOCKER-2：同时只允许一次还原，否则先结束者 clear Event 会让后者裸露。"""
    with restore_write_barrier():
        with pytest.raises(RuntimeError, match="已有一次还原"):
            with restore_write_barrier():
                pass
    assert not RESTORE_IN_PROGRESS.is_set(), "owner 退出后 Event 未复位"


def test_note_write_start_is_rejected_while_barrier_is_up() -> None:
    """BLOCKER-1：检查 Event 与登记计数必须在同一把锁内完成。"""
    RESTORE_IN_PROGRESS.set()
    try:
        assert db_backup.note_write_start() is False, (
            "屏障置位时仍放行了新请求的登记：它会溜进 4 段事务间隙"
        )
    finally:
        RESTORE_IN_PROGRESS.clear()


def test_note_write_end_clamps_underflow() -> None:
    """多减一次不得让计数变负（否则每次还原都等满 5s 超时，全站还原永久失败）。"""
    db_backup.note_write_end()
    assert db_backup._ACTIVE_REQUESTS == 0, "在途计数被多减成负数，barrier 的 ==0 判据将永久不成立"


def test_middleware_registers_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """接线守卫：删掉 server middleware 的 start/end 调用必须立刻红。

    前三条探针都是手动置位 / 手动调 barrier，删掉接线仍会全绿；本用例用
    monkeypatch 计数，真发一次请求，钉住 middleware → 屏障的接线。
    """
    calls = {"start": 0, "end": 0}
    real_start = db_backup.note_write_start
    real_end = db_backup.note_write_end

    def counted_start() -> bool:
        calls["start"] += 1
        return real_start()

    def counted_end() -> None:
        calls["end"] += 1
        real_end()

    monkeypatch.setattr(db_backup, "note_write_start", counted_start)
    monkeypatch.setattr(db_backup, "note_write_end", counted_end)

    _client().get("/api/health")
    assert calls["start"] == 1, "middleware 没有登记在途请求（BLOCKER-1 的入口没了）"
    assert calls["end"] == 1, "middleware 没有在 finally 里出栈（计数会泄漏）"


def test_barrier_flag_is_always_cleared_even_on_failure() -> None:
    """屏障异常退出 MUST 复位，否则一次失败的还原会让全站接口永久 503。"""
    with pytest.raises(RuntimeError, match="injected restore failure"):
        with restore_write_barrier():
            raise RuntimeError("injected restore failure")
    assert not RESTORE_IN_PROGRESS.is_set(), "屏障未复位：还原失败后接口将永久不可用"
