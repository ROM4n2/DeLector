# -*- coding: utf-8 -*-
"""``GET /api/articles`` 列表契约不变 + stats_json 迁移兼容回归锁（P1-6）。

钉住什么
--------
P1-6 改了列表的取数方式（``stats_json`` 投影列 + LIMIT），但**前端契约一个字段
都不能动**：``static/js/api-types.js::ArticleListItem`` = {id, title, created_at,
char_count, stats}，``reader.js`` 的 ``renderMiniBar(a.stats)`` 在消费它；路由契约
闸只查 URL，形状漂移闸查不到 ⇒ 本文件就是那个"形状闸"：

1. **形状不变**：列表每项恰含五个键、``stats`` 恒为 dict（含缺失/损坏 → {} 语义）；
2. **旧库迁移兼容**：老 schema（无 stats_json 列）的库跑 init_db 后——列补上、
   存量行一次性回填、列表对存量行返回的 stats 与旧实现口径一致；
3. **同步写**：新写入三条路径（ingest_article / seed_preset_articles / 惰性迁移
   单篇 GET）都落 stats_json；
4. **LIMIT**：默认 200、可参数化（首屏形状不变——main.js 不带参数调用不受影响）。

隔离纪律：对齐 test_get_endpoints_with_writes.py —— **每个测试**把 env 钉到
tmp_path throwaway 双库（首版漏钉 env，ingest 写进了 conftest 兜底测试库——本注释
就是防再犯的），显式 create_app()（模块级 server.app 在 import 期已用旧 env 建好，
不能用）；Windows 句柄释放：删文件前 gc.collect()。
"""

import gc
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db_cleanup import remove_db_files  # noqa: E402

from delector import server  # noqa: E402
from delector.core.database import db_conn as real_db_conn  # noqa: E402
from delector.core.database import ingest_article, init_db  # noqa: E402

RAW_TEXT = "Der Hund läuft schnell durch den Park."
LIST_KEYS = {"id", "title", "created_at", "char_count", "stats"}


@pytest.fixture
def db_paths(tmp_path) -> Iterator[Tuple[str, str]]:
    """把 DATABASE_PATH / PROGRESS_DB_PATH 钉进 tmp（测试结束后还原 + 删文件）。"""
    db = str(tmp_path / "contract.db")
    progress = str(tmp_path / "contract_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = db
    os.environ["PROGRESS_DB_PATH"] = progress
    yield db, progress
    gc.collect()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    remove_db_files(db, progress)


@pytest.fixture
def client(db_paths) -> Iterator[TestClient]:
    db, _progress = db_paths
    init_db(db)
    yield TestClient(server.create_app(), client=("127.0.0.1", 54321))


def _processed_json_with_stats(stats: Dict[str, Any]) -> str:
    return json.dumps({"version": "3.5.0", "sentence_count": 1, "sentences": [], "stats": stats}, ensure_ascii=False)


def _stats_shape_ok(items: List[Dict[str, Any]]) -> None:
    for item in items:
        assert set(item.keys()) == LIST_KEYS, f"列表项键集漂移：{set(item.keys())}"
        assert isinstance(item["stats"], dict), f"stats 必须是 dict，实际 {type(item['stats'])}"


# ── ① 形状不变（新库；create_app 会播种 4 篇预置文章，按 id 定位被测行） ──────
def test_list_response_shape_unchanged_new_db(client: TestClient, db_paths) -> None:
    db, _ = db_paths
    aid = ingest_article("Hund-Artikel", RAW_TEXT, db_path=db)
    resp = client.get("/api/articles")
    assert resp.status_code == 200
    items = resp.json()
    _stats_shape_ok(items)
    mine = [i for i in items if i["id"] == aid]
    assert len(mine) == 1, "ingest 的文章必须出现在列表里"
    item = mine[0]
    assert item["title"] == "Hund-Artikel"
    assert isinstance(item["char_count"], int) and item["char_count"] > 0
    assert item["stats"].get("word_count", 0) > 0, "新落库文章的 stats 不应为空（ingest 同步写被破坏）"
    # 预置文章也要有非空 stats（seed 同步写）
    for it in items:
        if it["id"] != aid:
            assert it["stats"], f"预置文章 {it['title']!r} 的 stats 为空（seed 同步写被破坏）"


# ── ② 旧库迁移兼容（无 stats_json 列的老 schema + 存量行） ────────────────────
def test_legacy_db_migration_backfills_and_keeps_stats_shape(db_paths) -> None:
    """老 schema 库跑 init_db ⇒ 列补上 + 一次性回填；列表 stats 与旧实现口径一致。

    旧口径（改前 list_articles）：pj 非 dict / 缺 stats / 解析失败 ⇒ {}；否则 stats 原样。
    不用 client fixture：那里的 init_db 会先建新 schema——这里必须先手搭老库再迁移。
    """
    db, _progress = db_paths
    legacy_rows = [
        # (title, processed_json, 旧实现应产出的 stats)
        ("valid", _processed_json_with_stats({"word_count": 6}), {"word_count": 6}),
        ("missing-stats", json.dumps({"version": "3.5.0"}), {}),
        ("not-dict", "not json at all", {}),
        ("empty", "{}", {}),
    ]
    conn = sqlite3.connect(db)
    try:
        # 老 schema：刻意不含 stats_json 列
        conn.execute(
            "CREATE TABLE articles (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
            "source_url TEXT, raw_text TEXT NOT NULL, processed_json TEXT NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        for title, pj, _stats in legacy_rows:
            conn.execute(
                "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
                (title, RAW_TEXT, pj),
            )
        conn.commit()
    finally:
        conn.close()

    init_db(db)  # 迁移：补列 + 一次性回填（articles 非空 ⇒ 不会播种预置文章）
    conn = sqlite3.connect(db)
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(articles)").fetchall()]
        assert "stats_json" in cols, "init_db 未给旧库补 stats_json 列"
        rows = {r[0]: r[1] for r in conn.execute("SELECT title, stats_json FROM articles").fetchall()}
    finally:
        conn.close()

    for title, _pj, expected_stats in legacy_rows:
        stored = rows[title]
        if expected_stats:
            assert stored is not None and json.loads(stored) == expected_stats, (
                f"存量行 {title} 回填结果与旧口径不符：{stored!r} vs {expected_stats!r}"
            )
        else:
            # 缺 stats / 非 dict / 空 JSON ⇒ 旧口径为 {}；回填落 NULL（COALESCE 兜底）
            # 或直接落 {} 都可接受，但列表必须给 {}。
            if stored is not None:
                assert json.loads(stored) == {}, f"存量行 {title} 回填应落空 stats：{stored!r}"

    app_client = TestClient(server.create_app(), client=("127.0.0.1", 54321))
    resp = app_client.get("/api/articles")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 4
    _stats_shape_ok(items)
    by_title = {i["title"]: i["stats"] for i in items}
    assert by_title["valid"] == {"word_count": 6}
    assert by_title["missing-stats"] == {}
    assert by_title["not-dict"] == {}
    assert by_title["empty"] == {}


# ── ③ 同步写三路径 ────────────────────────────────────────────────────────────
def test_lazy_migration_single_get_writes_stats_json(db_paths) -> None:
    """惰性迁移（单篇 GET）重算后必须同步回写 stats_json（否则该行永远走 blob 兜底）。"""
    db, progress = db_paths
    init_db(db)
    with real_db_conn(db) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            ("legacy", RAW_TEXT, "{}"),
        )
        aid = int(cur.lastrowid or 0)
    app_client = TestClient(server.create_app(), client=("127.0.0.1", 54321))
    resp = app_client.get(f"/api/articles/{aid}")
    assert resp.status_code == 200
    assert resp.json()["stats"].get("word_count", 0) > 0
    with real_db_conn(db) as conn:
        row = conn.execute("SELECT stats_json FROM articles WHERE id = ?", (aid,)).fetchone()
    assert row["stats_json"] is not None, "惰性迁移未同步写 stats_json"
    assert json.loads(row["stats_json"]).get("word_count", 0) > 0


def test_ingest_article_writes_stats_json(db_paths) -> None:
    db, _progress = db_paths
    init_db(db)
    aid = ingest_article("T", RAW_TEXT, db_path=db)
    with real_db_conn(db) as conn:
        row = conn.execute("SELECT stats_json FROM articles WHERE id = ?", (aid,)).fetchone()
    assert row["stats_json"] is not None and json.loads(row["stats_json"]), "ingest_article 未同步写 stats_json"


# ── ④ LIMIT：默认 200、可参数化 ───────────────────────────────────────────────
def test_list_limit_parameterized(client: TestClient, db_paths) -> None:
    db, _ = db_paths
    for i in range(5):
        ingest_article(f"A{i}", RAW_TEXT, db_path=db)
    full = client.get("/api/articles")
    assert len(full.json()) == 9  # 5 篇自灌 + 4 篇预置（create_app 播种）
    limited = client.get("/api/articles", params={"limit": 2})
    assert limited.status_code == 200
    items = limited.json()
    assert len(items) == 2, "limit 参数未生效"
    _stats_shape_ok(items)
    assert items[0]["title"] == "A4", "LIMIT 截断应保留最新（id DESC）语义"
