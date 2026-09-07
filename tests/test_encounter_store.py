# -*- coding: utf-8 -*-
"""encounter_texts 存储层（遇见区 i+1 Task A1）。

契约面（delector.core.database，纯 DB CRUD，无路由）：
- list_encounter_texts(level=None)  → ORDER BY id DESC 行列表，可选 level 过滤
- get_encounter_text(text_id)       → 单行 dict 或 None
- create_encounter_text(...)        → 新行自增 id
- import_encounter_pack(pack)       → 由 cardpack 落行（title/content/pack_json），幂等：
  同 pack_id 二次调用返回既有 id、不新增行；缺必需键抛 ValueError。

与 test_exam_trials.py / test_audit_hardening.py 同款纪律：store 函数都收
db_path，测试一律喂 **tmp_path 一次性 SQLite 文件**（含 progress 库），绝不触
及真实 delector.db / progress.db。Windows 句柄释放：删文件前 gc.collect()。
"""
import os
import gc
import json
import pytest

import delector.core.database as database  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 下的 throwaway DB（encounter + progress 双文件）。

    init_db(_DB) 内部会连带 init_progress_db()，故把 PROGRESS_DB_PATH 一起钉到
    tmp_path，避免 init_progress_db() 落到真实 progress.db。
    """
    _db = str(tmp_path / "encounter_test.db")
    _pdb = str(tmp_path / "encounter_test_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path 上
    yield {"db": _db, "pdb": _pdb}
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── (a) list 空库 ────────────────────────────────────────────────────────────

def test_list_empty(clean_db):
    rows = database.list_encounter_texts(db_path=clean_db["db"])
    assert rows == []


# ── (b) create → get 回读（列默认值）─────────────────────────────────────────

def test_create_then_get_returns_row(clean_db):
    tid = database.create_encounter_text(
        title="Hallo Berlin",
        level="A2",
        source="manual",
        content="Guten Tag!\n\nIch heiße Lukas.",
        db_path=clean_db["db"],
    )
    assert isinstance(tid, int) and tid > 0

    row = database.get_encounter_text(tid, db_path=clean_db["db"])
    assert row is not None
    assert row["id"] == tid
    assert row["title"] == "Hallo Berlin"
    assert row["level"] == "A2"
    assert row["source"] == "manual"
    assert row["content"] == "Guten Tag!\n\nIch heiße Lukas."
    # 未提供 pack_id / pack_json 时应为 NULL
    assert row["pack_id"] is None
    assert row["pack_json"] is None
    # created_at 由数据库填充，非空
    assert row["created_at"]


def test_get_missing_returns_none(clean_db):
    assert database.get_encounter_text(9999, db_path=clean_db["db"]) is None


# ── (c) level 过滤 ───────────────────────────────────────────────────────────

def test_list_level_filter(clean_db):
    database.create_encounter_text("t1", "A1", "", "c1", db_path=clean_db["db"])
    database.create_encounter_text("t2", "A2", "", "c2", db_path=clean_db["db"])
    database.create_encounter_text("t3", "A2", "", "c3", db_path=clean_db["db"])

    a2 = database.list_encounter_texts(level="A2", db_path=clean_db["db"])
    assert [r["title"] for r in a2] == ["t3", "t2"]  # newest first within filter
    a1 = database.list_encounter_texts(level="A1", db_path=clean_db["db"])
    assert [r["title"] for r in a1] == ["t1"]


# ── (d) list 排序 newest first ───────────────────────────────────────────────

def test_list_orders_newest_first(clean_db):
    ids = [
        database.create_encounter_text("first", "A1", "", "c", db_path=clean_db["db"]),
        database.create_encounter_text("second", "A2", "", "c", db_path=clean_db["db"]),
        database.create_encounter_text("third", "B1", "", "c", db_path=clean_db["db"]),
    ]
    rows = database.list_encounter_texts(db_path=clean_db["db"])
    # 后插的 id 更大 → 应排前面
    assert [r["id"] for r in rows] == sorted(ids, reverse=True)


# ── (e) import_encounter_pack 落行 ───────────────────────────────────────────

def test_import_pack_inserts_row(clean_db):
    pack = {
        "schema": "encounter-pack/v1",
        "pack_id": "job1-cardpack-0001",
        "source": {"kind": "curated"},
        "article": {
            "title": "Ein Tag im Park",
            "raw_text": "Es war einmal ein sonniger Tag.",
            "char_count": 32,
        },
        "analysis": {"tokens_total": 7, "known_rate": 0.2},
        "estimated_cefr": "B1",
    }
    tid = database.import_encounter_pack(pack, db_path=clean_db["db"])
    assert isinstance(tid, int) and tid > 0

    row = database.get_encounter_text(tid, db_path=clean_db["db"])
    assert row["title"] == "Ein Tag im Park"
    assert row["content"] == "Es war einmal ein sonniger Tag."
    assert row["pack_id"] == "job1-cardpack-0001"
    # 整包序列化存进 pack_json；反序列化后逐字段等价
    stored_pack = json.loads(row["pack_json"])
    assert stored_pack["schema"] == "encounter-pack/v1"
    assert stored_pack["pack_id"] == "job1-cardpack-0001"
    assert stored_pack["article"]["raw_text"] == "Es war einmal ein sonniger Tag."


# ── (f) import 幂等：同 pack_id 两次 → 同 id、仅一行 ────────────────────────

def test_import_pack_idempotent(clean_db):
    pack = {
        "schema": "encounter-pack/v1",
        "pack_id": "job1-cardpack-0002",
        "article": {"title": "Wetter", "raw_text": "Heute scheint die Sonne."},
        "estimated_cefr": "A2",
    }
    first = database.import_encounter_pack(pack, db_path=clean_db["db"])
    second = database.import_encounter_pack(pack, db_path=clean_db["db"])
    assert first == second
    assert first > 0

    all_rows = database.list_encounter_texts(db_path=clean_db["db"])
    matches = [r for r in all_rows if r["pack_id"] == "job1-cardpack-0002"]
    assert len(matches) == 1


# ── (g) import 缺必需键 → ValueError ─────────────────────────────────────────

def test_import_pack_missing_keys_raises_valueerror(clean_db):
    # 缺 schema
    with pytest.raises(ValueError):
        database.import_encounter_pack(
            {"pack_id": "x", "article": {"title": "t", "raw_text": "c"}},
            db_path=clean_db["db"],
        )
    # 缺 pack_id
    with pytest.raises(ValueError):
        database.import_encounter_pack(
            {"schema": "encounter-pack/v1", "article": {"title": "t", "raw_text": "c"}},
            db_path=clean_db["db"],
        )
    # 缺 article
    with pytest.raises(ValueError):
        database.import_encounter_pack(
            {"schema": "encounter-pack/v1", "pack_id": "y"},
            db_path=clean_db["db"],
        )
    # article 缺 title / raw_text
    with pytest.raises(ValueError):
        database.import_encounter_pack(
            {"schema": "encounter-pack/v1", "pack_id": "z", "article": {"title": "t"}},
            db_path=clean_db["db"],
        )
    # 非 dict
    with pytest.raises(ValueError):
        database.import_encounter_pack(["not", "a", "dict"], db_path=clean_db["db"])
