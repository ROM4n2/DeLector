# -*- coding: utf-8 -*-
"""惰性迁移 single-flight 行为级回归锁（P1-8）。

背景：``GET /api/articles/{id}`` 的惰性迁移此前**无锁无重检**——8 并发打开同一篇
陈旧文章 ⇒ 8 次 spaCy 全量重算 + 8 次 UPDATE（墙钟 ~1.5s 但 8× CPU 与写放大）。
修法：per-article 的 ``{article_id: Lock}`` single-flight + **锁内重检 version**
（拿到锁后先再查一次，已被别的请求迁完 ⇒ 直接用，不重算）。

本文件钉行为证据（spy 数真实调用次数，不是数 SQL——并发下 UPDATE 次数还受
SQLite 锁调度影响，而 ``process_german_text`` 是成本主体，数它才稳）：
- 8 线程并发 GET 同一篇陈旧文章 ⇒ spaCy 计算恰好 1 次、8 个响应一致；
- 单线程旧文 ⇒ 正常迁移（语义不因加锁而坏）。
- 变异自证：摘掉 single-flight（回退无锁重检）⇒ 并发用例红（见 git diff/报告）。

隔离纪律：env 钉 tmp 双库 + 显式 create_app()（模块级 server.app 在 import 期已建）。
"""

import gc
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db_cleanup import remove_db_files  # noqa: E402

from delector import server  # noqa: E402
from delector.core.database import db_conn as real_db_conn  # noqa: E402
from delector.core.database import init_db  # noqa: E402
from delector.nlp_engine import processor  # noqa: E402

RAW_TEXT = "Der Hund läuft schnell durch den Park und spielt mit einem Ball."
CONCURRENCY = 8


@pytest.fixture
def db_paths(tmp_path) -> Iterator[str]:
    db = str(tmp_path / "singleflight.db")
    progress = str(tmp_path / "singleflight_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = db
    os.environ["PROGRESS_DB_PATH"] = progress
    yield db
    gc.collect()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    remove_db_files(db, progress)


def _insert_stale_article(db: str) -> int:
    with real_db_conn(db) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            ("Stale", RAW_TEXT, "{}"),
        )
        return int(cur.lastrowid or 0)


def _spy_spy_on_processor(monkeypatch: pytest.MonkeyPatch, sleep_s: float = 0.05) -> List[Dict[str, Any]]:
    """把 routes.main.process_german_text 换成带窗口的计数 spy（返回固定已迁移 payload）。"""
    from delector.routes import articles as routes_articles

    calls: List[Dict[str, Any]] = []

    def fake_process(text: str) -> Dict[str, Any]:
        calls.append({"text": text})
        time.sleep(sleep_s)  # 拉宽竞态窗口：无锁时 8 线程都会在首个 UPDATE 提交前进入计算
        return {
            "version": processor.PROCESSED_JSON_VERSION,
            "sentence_count": 1,
            "sentences": [{"id": 0, "text": text, "tokens": [], "topology": {}, "clause_tree": {}}],
            "stats": {"word_count": 10, "total_words": 10},
        }

    monkeypatch.setattr(routes_articles, "process_german_text", fake_process)
    return calls


def test_concurrent_gets_stale_article_compute_once(db_paths: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """8 并发 GET 同一篇陈旧文章 ⇒ process_german_text 恰好 1 次 + 8 响应一致。"""
    db = db_paths
    init_db(db)
    aid = _insert_stale_article(db)
    calls = _spy_spy_on_processor(monkeypatch)
    app = server.create_app()

    def hit(_: int) -> Dict[str, Any]:
        # 每线程独立 TestClient（app 共享）；同时起跑，落在同一个惰性迁移分支上
        client = TestClient(app, client=("127.0.0.1", 54321))
        resp = client.get(f"/api/articles/{aid}")
        assert resp.status_code == 200, resp.text
        return resp.json()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(hit, range(CONCURRENCY)))

    assert len(calls) == 1, (
        f"single-flight 失效：spaCy 计算被调用了 {len(calls)} 次（期望 1 次）——"
        "per-article 锁或锁内重检被摘？"
    )
    first = results[0]
    for i, body in enumerate(results[1:], start=1):
        assert body == first, f"响应 {i} 与首个响应不一致（并发迁移出了不同版本？）"
    assert first["stats"]["word_count"] == 10
    # 落库值 = 当前真相源版本（迁移确实写回了）
    with real_db_conn(db) as conn:
        row = conn.execute("SELECT processed_json FROM articles WHERE id = ?", (aid,)).fetchone()
    assert json.loads(row["processed_json"])["version"] == processor.PROCESSED_JSON_VERSION


def test_single_thread_stale_article_still_migrates(db_paths: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """单线程旧文 ⇒ 正常迁移（加锁不改变既有迁移语义）。"""
    db = db_paths
    init_db(db)
    aid = _insert_stale_article(db)
    calls = _spy_spy_on_processor(monkeypatch, sleep_s=0.0)
    client = TestClient(server.create_app(), client=("127.0.0.1", 54321))

    resp = client.get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    assert resp.json()["stats"]["word_count"] == 10
    assert len(calls) == 1
    # 二次 GET：已迁移 ⇒ 不再重算
    second = client.get(f"/api/articles/{aid}")
    assert second.status_code == 200
    assert len(calls) == 1, "已迁移文章二次 GET 不应再触发计算（惰性迁移判据被加锁改动破坏？）"
