# -*- coding: utf-8 -*-
"""存量 ``processed_json`` 版本升级的行为级回归锁。

覆盖三条硬约束（对应 PR 验收口径）：
1. **按需重算**：旧版本行只在 GET 时重算，当前版本行不重算；
2. **不损坏既有内容**：重算失败 / 非 UTF-8 / 损坏 JSON 时保留旧结果，``raw_text`` 永不被改写，
   写库中途异常整体回滚（不留「备份写了、正文没更新」的半成品）；
3. **可回退 + 幂等**：覆盖前快照进 ``processed_json_backup``，``--restore`` 逐字写回；
   重跑时已迁移行跳过，结果逐字一致。

边界数据形态刻意写死 ``OLD_VERSION = "3.5.0"``（历史落库形态，不跟随当前常量漂移）。
"""

import gc
import json
import os
import sys
from typing import Any, Dict, Iterator, List, Optional

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
from delector.routes import articles as routes_articles  # noqa: E402
from tools import recompute_processed  # noqa: E402

OLD_VERSION = "3.5.0"
CURRENT = processor.PROCESSED_JSON_VERSION
RAW_TEXT = "Die Lehrerin gibt den Schülern die Bücher."


@pytest.fixture
def db_paths(tmp_path) -> Iterator[str]:
    db = str(tmp_path / "migration.db")
    progress = str(tmp_path / "migration_progress.db")
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


def _old_payload(version: str = OLD_VERSION, stats: Optional[Dict[str, Any]] = None) -> str:
    return json.dumps(
        {
            "version": version,
            "sentence_count": 1,
            "sentences": [
                {
                    "id": 0,
                    "text": RAW_TEXT,
                    "tokens": [{"id": 0, "text": "Die", "pos": "ADV", "case": ""}],
                    "topology": {"mittelfeld": ["Die"]},
                    "clause_tree": {"id": "root", "type": "hauptsatz"},
                }
            ],
            "stats": stats if stats is not None else {"word_count": 1, "cefr_percentages": {}},
        },
        ensure_ascii=False,
    )


def _new_payload(text: str) -> Dict[str, Any]:
    return {
        "version": CURRENT,
        "sentence_count": 1,
        "sentences": [
            {
                "id": 0,
                "text": text,
                "tokens": [{"id": 0, "text": "Die", "pos": "DET", "case": "Nom"}],
                "topology": {"vorfeld": ["Die"], "mittelfeld": []},
                "clause_tree": {"id": "root", "type": "hauptsatz"},
            }
        ],
        "stats": {"word_count": len(text), "cefr_percentages": {}},
    }


def _insert(
    db: str,
    raw_text: Any,
    processed_json: str,
    stats_json: Optional[str] = "auto",
) -> int:
    if stats_json == "auto":
        stats_json = json.dumps({"word_count": 1})
    with real_db_conn(db) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json, stats_json) VALUES (?, ?, ?, ?)",
            ("Boundary", raw_text, processed_json, stats_json),
        )
        return int(cur.lastrowid or 0)


def _row(db: str, article_id: int) -> Dict[str, Any]:
    with real_db_conn(db) as conn:
        return dict(conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone())


def _backup_rows(db: str) -> List[Dict[str, Any]]:
    with real_db_conn(db) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM processed_json_backup ORDER BY article_id")]


def _client() -> TestClient:
    return TestClient(server.create_app(), client=("127.0.0.1", 54321))


def _counting_processor(calls: List[str], *, fail_on: Optional[str] = None):
    def fake(text: str) -> Dict[str, Any]:
        calls.append(text)
        if fail_on is not None and text == fail_on:
            raise RuntimeError("synthetic parser failure")
        return _new_payload(text)

    return fake


# ── 1. 按需重算 + 备份 + 原文不变 ────────────────────────────────────────────────
def test_old_version_triggers_recompute_backs_up_and_keeps_raw_text(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_paths
    init_db(db)
    old = _old_payload()
    aid = _insert(db, RAW_TEXT, old)
    calls: List[str] = []
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor(calls))

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == CURRENT
    assert body["stats"]["word_count"] == len(RAW_TEXT)
    assert len(calls) == 1

    stored = _row(db, aid)
    assert json.loads(stored["processed_json"])["version"] == CURRENT
    assert stored["raw_text"] == RAW_TEXT, "raw_text 被改写了（绝对不允许）"
    backups = _backup_rows(db)
    assert len(backups) == 1
    assert backups[0]["article_id"] == aid
    assert backups[0]["processed_json"] == old, "备份必须是覆盖前的逐字内容"
    assert backups[0]["processed_version"] == OLD_VERSION


def test_current_version_does_not_recompute(db_paths: str, monkeypatch: pytest.MonkeyPatch) -> None:
    db = db_paths
    init_db(db)
    aid = _insert(db, RAW_TEXT, _old_payload(CURRENT))
    calls: List[str] = []
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor(calls))

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    assert calls == [], "当前版本行不得重算"
    assert _backup_rows(db) == []


def test_second_get_is_idempotent(db_paths: str, monkeypatch: pytest.MonkeyPatch) -> None:
    db = db_paths
    init_db(db)
    aid = _insert(db, RAW_TEXT, _old_payload())
    calls: List[str] = []
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor(calls))
    client = _client()

    first = client.get(f"/api/articles/{aid}")
    after_first = _row(db, aid)
    second = client.get(f"/api/articles/{aid}")

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1, "第二次 GET 不应再重算"
    assert _row(db, aid)["processed_json"] == after_first["processed_json"]
    assert len(_backup_rows(db)) == 1


# ── 2. 失败 / 边界：旧结果保留、正文不动、无半成品 ──────────────────────────────
@pytest.mark.parametrize(
    "raw_text",
    [
        "",
        "x" * 100_000,  # ingest 上限量级
        "Grüße aus Köln – äöü ß",  # 合法但含非 ASCII
    ],
)
def test_boundary_text_shapes_migrate_without_crash(
    db_paths: str, monkeypatch: pytest.MonkeyPatch, raw_text: str
) -> None:
    db = db_paths
    init_db(db)
    aid = _insert(db, raw_text, _old_payload())
    calls: List[str] = []
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor(calls))

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200, resp.text
    assert calls == [raw_text], "正文必须以原样（含空串/超长）送入重算，不得截断"
    assert _row(db, aid)["raw_text"] == raw_text


def test_broken_json_is_treated_as_stale_and_backed_up(db_paths: str, monkeypatch: pytest.MonkeyPatch) -> None:
    db = db_paths
    init_db(db)
    broken = '{"version": "3.5.0", "sentences": ['
    aid = _insert(db, RAW_TEXT, broken, None)
    calls: List[str] = []
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor(calls))

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == CURRENT
    backups = _backup_rows(db)
    assert len(backups) == 1 and backups[0]["processed_json"] == broken
    assert _row(db, aid)["raw_text"] == RAW_TEXT


def test_non_utf8_blob_raw_text_does_not_crash_and_keeps_old_row(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_paths
    init_db(db)
    blob = b"Gr\xfc\xdfe aus K\xf6ln"  # latin-1：不是合法 UTF-8
    old = _old_payload()
    aid = _insert(db, blob, old)
    calls: List[str] = []

    def fake(text: str) -> Dict[str, Any]:
        calls.append(text)
        raise RuntimeError("synthetic parser failure on lossy-decoded text")

    monkeypatch.setattr(routes_articles, "process_german_text", fake)

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["processed_upgrade_failed"] is True
    assert body["stats"]["word_count"] == 1, "失败时必须回落到旧结果"
    assert calls and "\ufffd" in calls[0], "BLOB 应只在内存里有损解码后交给解析器"
    stored = _row(db, aid)
    assert stored["processed_json"] == old
    assert isinstance(stored["raw_text"], bytes) and stored["raw_text"] == blob, "BLOB 正文不得被改写"
    assert _backup_rows(db) == []


def test_non_utf8_blob_processed_json_does_not_crash(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """processed_json 被存成 BLOB（非 UTF-8）时：内存容错解码，不 500；备份保留原始字节。"""
    db = db_paths
    init_db(db)
    broken = b'{"version": "3.5.0", "\xff": ['
    aid = _insert(db, RAW_TEXT, broken, None)
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor([]))

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == CURRENT
    assert _row(db, aid)["raw_text"] == RAW_TEXT
    backups = _backup_rows(db)
    assert len(backups) == 1 and backups[0]["processed_json"] == broken


def test_parser_failure_keeps_old_result_and_is_visible(
    db_paths: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    db = db_paths
    init_db(db)
    old = _old_payload()
    aid = _insert(db, RAW_TEXT, old)
    monkeypatch.setattr(
        routes_articles, "process_german_text", _counting_processor([], fail_on=RAW_TEXT)
    )

    with caplog.at_level("WARNING"):
        resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == OLD_VERSION
    assert body["processed_upgrade_failed"] is True
    assert any("重算失败" in rec.message for rec in caplog.records)
    assert _row(db, aid)["processed_json"] == old
    assert _backup_rows(db) == []


def test_partial_write_failure_rolls_back_backup(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """备份已写入、UPDATE 前抛错 ⇒ 整个事务回滚，不得留半成品。"""
    db = db_paths
    init_db(db)
    old = _old_payload()
    aid = _insert(db, RAW_TEXT, old)
    monkeypatch.setattr(routes_articles, "process_german_text", _counting_processor([]))

    def exploding_write(conn, article_id, old_processed_json, old_stats_json, payload):
        conn.execute(
            "INSERT INTO processed_json_backup (article_id, processed_version, processed_json, stats_json) "
            "VALUES (?, ?, ?, ?)",
            (article_id, OLD_VERSION, old_processed_json, old_stats_json),
        )
        raise RuntimeError("synthetic failure after backup insert")

    monkeypatch.setattr(routes_articles, "write_migrated", exploding_write)

    resp = _client().get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    assert resp.json()["processed_upgrade_failed"] is True
    assert _row(db, aid)["processed_json"] == old
    assert _backup_rows(db) == [], "回滚后不得留下备份半成品"


# ── 3. 维护 CLI：分批 / 单篇失败不中断 / 幂等 / 回退 ─────────────────────────────
def _seed_cli_articles(db: str) -> List[int]:
    init_db(db)
    # init_db 会播种预置文章（新库 count==0）；这里只关心自己造的 4 篇，清掉以免计数漂移。
    with real_db_conn(db) as conn:
        conn.execute("DELETE FROM articles")
    return [
        _insert(db, "ok-1", _old_payload()),
        _insert(db, "FAIL", _old_payload()),
        _insert(db, "ok-3", _old_payload()),
        _insert(db, "ok-4", _old_payload()),
    ]


def test_cli_continues_after_single_failure_and_is_resumable(db_paths: str) -> None:
    db = db_paths
    ids = _seed_cli_articles(db)
    calls: List[str] = []
    process = _counting_processor(calls, fail_on="FAIL")

    first = recompute_processed.run_migration(db, batch_size=2, process=process, out=lambda _m: None)

    assert first == {"scanned": 4, "stale": 4, "migrated": 3, "skipped": 0, "failed": 1}
    assert json.loads(_row(db, ids[1])["processed_json"])["version"] == OLD_VERSION
    for aid in (ids[0], ids[2], ids[3]):
        assert json.loads(_row(db, aid)["processed_json"])["version"] == CURRENT
    assert _row(db, ids[1])["raw_text"] == "FAIL"

    # 重跑：已迁移的 3 篇跳过，失败那篇继续尝试（不重复成功篇）
    calls.clear()
    second = recompute_processed.run_migration(db, batch_size=2, process=process, out=lambda _m: None)

    assert second == {"scanned": 4, "stale": 1, "migrated": 0, "skipped": 3, "failed": 1}
    assert calls == ["FAIL"]


def test_cli_success_is_idempotent_and_batches(db_paths: str) -> None:
    db = db_paths
    ids = _seed_cli_articles(db)
    calls: List[str] = []
    process = _counting_processor(calls)

    first = recompute_processed.run_migration(db, batch_size=3, process=process, out=lambda _m: None)
    snapshot = {aid: _row(db, aid)["processed_json"] for aid in ids}
    calls.clear()
    second = recompute_processed.run_migration(db, batch_size=1, process=process, out=lambda _m: None)

    assert first["migrated"] == 4 and first["failed"] == 0
    assert second["migrated"] == 0 and second["skipped"] == 4 and calls == []
    assert {aid: _row(db, aid)["processed_json"] for aid in ids} == snapshot, "重跑结果必须逐字一致"


def test_cli_limit_and_dry_run_do_not_write(db_paths: str) -> None:
    db = db_paths
    ids = _seed_cli_articles(db)
    before = {aid: _row(db, aid)["processed_json"] for aid in ids}
    calls: List[str] = []
    process = _counting_processor(calls)

    dry = recompute_processed.run_migration(
        db, batch_size=10, dry_run=True, process=process, out=lambda _m: None
    )
    assert dry["stale"] == 4 and dry["migrated"] == 0 and calls == []
    assert {aid: _row(db, aid)["processed_json"] for aid in ids} == before

    limited = recompute_processed.run_migration(
        db, batch_size=10, limit=2, process=process, out=lambda _m: None
    )
    assert limited["stale"] == 2 and limited["migrated"] == 2
    assert sum(
        1 for aid in ids if json.loads(_row(db, aid)["processed_json"])["version"] == CURRENT
    ) == 2


def test_cli_restore_returns_exact_old_payload(db_paths: str) -> None:
    db = db_paths
    init_db(db)
    old = _old_payload(stats={"word_count": 7})
    old_stats = json.dumps({"word_count": 7})
    aid = _insert(db, RAW_TEXT, old, old_stats)
    process = _counting_processor([])
    recompute_processed.run_migration(db, process=process, out=lambda _m: None)
    assert json.loads(_row(db, aid)["processed_json"])["version"] == CURRENT

    result = recompute_processed.run_restore(db, out=lambda _m: None)

    assert result == {"restored": 1, "missing": 0}
    stored = _row(db, aid)
    assert stored["processed_json"] == old, "回退必须逐字写回"
    assert stored["stats_json"] == old_stats
    assert stored["raw_text"] == RAW_TEXT
    assert _backup_rows(db) == [], "回退成功后删除该篇备份（可再次迁移时重建）"

    again = recompute_processed.run_restore(db, out=lambda _m: None)
    assert again == {"restored": 0, "missing": 0}


def test_cli_restore_single_article(db_paths: str) -> None:
    db = db_paths
    init_db(db)
    first, second = _insert(db, "a", _old_payload()), _insert(db, "b", _old_payload())
    recompute_processed.run_migration(db, process=_counting_processor([]), out=lambda _m: None)

    result = recompute_processed.run_restore(db, article_id=second, out=lambda _m: None)

    assert result == {"restored": 1, "missing": 0}
    assert json.loads(_row(db, first)["processed_json"])["version"] == CURRENT
    assert json.loads(_row(db, second)["processed_json"])["version"] == OLD_VERSION


def test_backup_table_created_by_init_db_on_existing_database(db_paths: str) -> None:
    db = db_paths
    init_db(db)
    init_db(db)  # 幂等：第二次启动不得因表已存在而失败
    with real_db_conn(db) as conn:
        names = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "processed_json_backup" in names
