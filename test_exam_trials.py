# -*- coding: utf-8 -*-
"""exam_trials 泛化成绩表 + 幂等迁移 + 备份接线（ADR-0005 Task 4）。

契约面：
- database.record_exam_trial / get_exam_history 泛化读写（level, module 维度）。
- 旧 record_a1_*_trial / get_a1_*_history 改内部透传：签名与返回结构逐字段
  等价，且行同时落进 exam_trials(level='A1', module=…)。
- migrate_a1_records_to_exam_trials()：行数对账防重入，幂等可重跑。
- 备份链：_PROGRESS_TABLES 带 exam_trials → export 键齐 → RestoreReq 接
  exam_trials 字段 → restore 真覆盖灌表。

与 test_audit_hardening.py 同款纪律：模块顶层先钉隔离 env 再 import
server（顶层 init_db() 副作用），clean_db autouse 前后双钉 env +
gc.collect() 后删库（Windows 句柄释放纪律）。
"""
import json
import os
import gc
import pytest

os.environ["DATABASE_PATH"] = "test_exam_trials_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_exam_trials_progress.db"

from fastapi.testclient import TestClient  # noqa: E402

from server import app, init_db, get_progress_db  # noqa: E402
import database  # noqa: E402

_DB = "test_exam_trials_delector.db"
_PDB = "test_exam_trials_progress.db"
_DB_FILES = (_DB, _PDB)

_HOEREN_FIELDS = {
    "set_id": 3, "score_raw": 18, "score_official": 20.5,
    "total_questions": 25, "duration_seconds": 640,
    "answers_json": '{"a1_h_01_t1_q01": "B"}',
    "wrong_questions_json": '[{"qid": "a1_h_01_t1_q02"}]',
}


@pytest.fixture
def client():
    # 显式 127.0.0.1：restore 端点有 _require_localhost 闸。
    return TestClient(app, client=("127.0.0.1", 54321))


@pytest.fixture(autouse=True)
def clean_db():
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _DB
    os.environ["PROGRESS_DB_PATH"] = _PDB
    gc.collect()
    for f in _DB_FILES:
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    init_db(_DB)  # 内部连带 init_progress_db() + 迁移调用
    yield
    gc.collect()
    for f in _DB_FILES:
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


# ── RED 1：泛化写读回（字段逐个对，无 level/module 冗余字段） ────────────────

def test_record_exam_trial_roundtrip_fields():
    rid = database.record_exam_trial(
        "A1", "hoeren", db_path=_PDB, **_HOEREN_FIELDS)
    assert isinstance(rid, int) and rid > 0

    hist = database.get_exam_history("A1", "hoeren", db_path=_PDB)
    assert len(hist) == 1
    row = hist[0]
    # 与旧 get_a1_*_history 逐字段等价：SELECT * 的全列，不加冗余
    assert set(row.keys()) == {
        "id", "set_id", "score_raw", "score_official", "total_questions",
        "duration_seconds", "answers_json", "wrong_questions_json", "created_at",
    }
    for k, v in _HOEREN_FIELDS.items():
        assert row[k] == v, f"{k}: {row[k]!r} != {v!r}"
    assert row["created_at"] is not None

    # level/module 维度隔离：lesen 视角看不见 hoeren 的行
    assert database.get_exam_history("A1", "lesen", db_path=_PDB) == []
    assert database.get_exam_history("A2", "hoeren", db_path=_PDB) == []

    # limit 语义与旧函数一致（ORDER BY id DESC LIMIT ?）
    for i in range(3):
        database.record_exam_trial(
            "A1", "lesen", set_id=i + 1, score_raw=10 + i, score_official=8.0 + i,
            total_questions=25, duration_seconds=300,
            answers_json="{}", wrong_questions_json="[]", db_path=_PDB)
    lesen = database.get_exam_history("A1", "lesen", limit=2, db_path=_PDB)
    assert [r["set_id"] for r in lesen] == [3, 2]


# ── RED 2：旧函数透传——签名/返回结构不变 + 行落进泛化表 ─────────────────────

def test_legacy_a1_hoeren_trial_passes_through(db_path=_PDB):
    rid = database.record_a1_hoeren_trial(
        _HOEREN_FIELDS["set_id"], _HOEREN_FIELDS["score_raw"],
        _HOEREN_FIELDS["score_official"], _HOEREN_FIELDS["total_questions"],
        _HOEREN_FIELDS["duration_seconds"], _HOEREN_FIELDS["answers_json"],
        _HOEREN_FIELDS["wrong_questions_json"], db_path=_PDB)
    assert isinstance(rid, int) and rid > 0

    hist = database.get_a1_hoeren_history(limit=50, db_path=_PDB)
    assert len(hist) == 1
    row = hist[0]
    assert set(row.keys()) == {
        "id", "set_id", "score_raw", "score_official", "total_questions",
        "duration_seconds", "answers_json", "wrong_questions_json", "created_at",
    }
    for k, v in _HOEREN_FIELDS.items():
        assert row[k] == v

    # 同一行必须同时出现在 exam_trials(level='A1', module='hoeren')
    with database.db_progress_conn(_PDB) as conn:
        g = conn.execute(
            "SELECT COUNT(*) FROM exam_trials WHERE level='A1' AND module='hoeren'"
        ).fetchone()[0]
    assert g == 1


def test_legacy_a1_lesen_trial_passes_through():
    rid = database.record_a1_lesen_trial(
        2, 15, 19.0, 25, 700, '{"q": "R"}', "[]", db_path=_PDB)
    assert isinstance(rid, int) and rid > 0
    hist = database.get_a1_lesen_history(db_path=_PDB)
    assert len(hist) == 1
    assert hist[0]["score_official"] == 19.0
    with database.db_progress_conn(_PDB) as conn:
        g = conn.execute(
            "SELECT COUNT(*) FROM exam_trials WHERE level='A1' AND module='lesen'"
        ).fetchone()[0]
    assert g == 1


# ── RED 3：幂等迁移——行数对账 + created_at 原值拷贝 + 可重跑 ─────────────────

def _seed_legacy_rows():
    with database.db_progress_conn(_PDB) as conn:
        conn.executemany(
            """INSERT INTO a1_hoeren_records
               (set_id, score_raw, score_official, total_questions,
                duration_seconds, answers_json, wrong_questions_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (1, 20, 22.0, 25, 600, "{}", "[]", "2026-08-01 10:00:00"),
                (2, 15, 18.5, 25, 610, "{}", "[]", "2026-08-02 11:30:00"),
            ])
        conn.execute(
            """INSERT INTO a1_lesen_records
               (set_id, score_raw, score_official, total_questions,
                duration_seconds, answers_json, wrong_questions_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, 22, 24.0, 25, 700, "{}", "[]", "2026-08-03 09:15:00"))


def test_migrate_a1_records_idempotent():
    _seed_legacy_rows()
    report = database.migrate_a1_records_to_exam_trials(db_path=_PDB)
    assert report == {
        "hoeren": {"migrated": 2, "skipped": False},
        "lesen": {"migrated": 1, "skipped": False},
    }

    with database.db_progress_conn(_PDB) as conn:
        rows = conn.execute(
            "SELECT level, module, set_id, score_raw, score_official,"
            " total_questions, duration_seconds, answers_json,"
            " wrong_questions_json, created_at FROM exam_trials"
            " ORDER BY level, module, set_id").fetchall()
        g = conn.execute("SELECT COUNT(*) FROM exam_trials").fetchone()[0]
    assert g == 3
    by_key = {(r["level"], r["module"], r["set_id"]): dict(r) for r in rows}
    h1 = by_key[("A1", "hoeren", 1)]
    assert h1["score_raw"] == 20 and h1["score_official"] == 22.0
    assert h1["created_at"] == "2026-08-01 10:00:00"  # created_at 原值拷贝
    l1 = by_key[("A1", "lesen", 1)]
    assert l1["score_raw"] == 22 and l1["created_at"] == "2026-08-03 09:15:00"

    # 第二次跑：行数对账即跳过，零新增
    report2 = database.migrate_a1_records_to_exam_trials(db_path=_PDB)
    assert report2 == {
        "hoeren": {"migrated": 0, "skipped": True},
        "lesen": {"migrated": 0, "skipped": True},
    }
    with database.db_progress_conn(_PDB) as conn:
        g2 = conn.execute("SELECT COUNT(*) FROM exam_trials").fetchone()[0]
    assert g2 == 3, "重复迁移不得翻倍"


def test_migrate_on_empty_legacy_tables_skips():
    # 空旧表：0 >= 0 行数对账即跳过，不写任何行
    report = database.migrate_a1_records_to_exam_trials(db_path=_PDB)
    assert report == {
        "hoeren": {"migrated": 0, "skipped": True},
        "lesen": {"migrated": 0, "skipped": True},
    }


def test_migrate_after_new_grade_does_not_duplicate():
    """迁移完成后 + 透传新成绩 + 重启（再跑 migrate）→ 旧行不得重插二次。

    回归：migrate 之前用 ==（general_count == legacy_count）做对账，但透传
    模式后旧表冻结、exam_trials 随新成绩单调增，一旦「迁移后又做了一次成绩」，
    general = legacy+1 ≠ legacy 会被误判为未迁移，把旧表整行再插一遍导致重复
    （已复现：6→count 3→migrate2 迁 2 行→count 5）。
    """
    _seed_legacy_rows()  # hoeren 2 行 + lesen 1 行
    database.migrate_a1_records_to_exam_trials(db_path=_PDB)

    # 透传写一条**新**成绩：旧表冻结、只写 exam_trials(level='A1', module='hoeren')
    database.record_a1_hoeren_trial(
        _HOEREN_FIELDS["set_id"], _HOEREN_FIELDS["score_raw"],
        _HOEREN_FIELDS["score_official"], _HOEREN_FIELDS["total_questions"],
        _HOEREN_FIELDS["duration_seconds"], _HOEREN_FIELDS["answers_json"],
        _HOEREN_FIELDS["wrong_questions_json"], db_path=_PDB)

    # 模拟重启再跑迁移：此时 general=3（2 迁移 + 1 新）> legacy=2，必须 skip
    report = database.migrate_a1_records_to_exam_trials(db_path=_PDB)
    assert report == {
        "hoeren": {"migrated": 0, "skipped": True},
        "lesen": {"migrated": 0, "skipped": True},
    }
    with database.db_progress_conn(_PDB) as conn:
        g = conn.execute("SELECT COUNT(*) FROM exam_trials").fetchone()[0]
    assert g == 4, "迁移后新成绩 + 重启不得让旧行重插（重复数据）"


# ── RED 4：备份接线——export 键齐 + RestoreReq + restore 灌表 ────────────────

def test_backup_payload_contains_exam_trials():
    database.record_exam_trial(
        "A1", "hoeren", db_path=_PDB, **_HOEREN_FIELDS)
    from database import build_backup_payload
    payload = build_backup_payload()
    assert "exam_trials" in payload
    assert len(payload["exam_trials"]) == 1
    assert payload["exam_trials"][0]["level"] == "A1"
    assert payload["exam_trials"][0]["module"] == "hoeren"
    assert payload["exam_trials"][0]["score_raw"] == _HOEREN_FIELDS["score_raw"]


def test_restore_exam_trials_roundtrip(client):
    from server import RestoreReq
    assert "exam_trials" in RestoreReq.model_fields

    row = dict(_HOEREN_FIELDS)
    row.update({"id": 7, "level": "A1", "module": "hoeren",
                "created_at": "2026-08-04 12:00:00"})
    payload = {"version": 2, "exam_trials": [row]}
    res = client.post("/api/backup/restore", json=payload)
    assert res.status_code == 200

    with get_progress_db(_PDB) as conn:
        got = dict(conn.execute(
            "SELECT * FROM exam_trials WHERE id = 7").fetchone())
    for k, v in row.items():
        assert got[k] == v, f"{k}: {got[k]!r} != {v!r}"


def test_restore_v51_backup_keeps_a1_history_visible(client):
    """v5.1 备份里 A1 成绩只存在旧表：还原后透传读路径必须能看到。

    读路径已切到泛化表（exam_trials），而 v5.1 备份没有 exam_trials 键——
    若 restore 不补一次幂等迁移，历史会「看着还原成功却读不出来」。
    """
    payload = {
        "version": 2,
        "a1_hoeren_records": [{
            "id": 101, "set_id": 1, "score_raw": 14, "score_official": 23.3,
            "total_questions": 15, "duration_seconds": 580,
            "answers_json": "{\"q1\": \"A\"}", "wrong_questions_json": "[]",
            "created_at": "2026-09-01T12:00:00",
        }],
    }
    res = client.post("/api/backup/restore", json=payload)
    assert res.status_code == 200

    hist = database.get_a1_hoeren_history(db_path=_PDB)
    assert len(hist) == 1
    assert hist[0]["score_raw"] == 14
    # 行数对账不翻倍：再跑 restore 一圈（迁移幂等）历史仍只有 1 条
    client.post("/api/backup/restore", json=payload)
    assert len(database.get_a1_hoeren_history(db_path=_PDB)) == 1


# ── RED 5：routes 透传端到端（grade 落库 + history 读回） ────────────────────

def test_hoeren_routes_end_to_end(client):
    grade = client.post("/api/a1/hoeren/grade", json={
        "set_id": 1, "duration_seconds": 600,
        "answers": {"a1_h_01_t1_q01": "B"},
    })
    assert grade.status_code == 200
    assert "score_official" in grade.json()

    hist = client.get("/api/a1/hoeren/history")
    assert hist.status_code == 200
    entries = hist.json()["history"]
    assert len(entries) == 1
    assert entries[0]["set_id"] == 1
    assert set(entries[0].keys()) == {
        "id", "set_id", "score_raw", "score_official", "total_questions",
        "duration_seconds", "answers_json", "wrong_questions_json", "created_at",
    }

    # 端到端：这条记录同时落在泛化表
    with database.db_progress_conn(_PDB) as conn:
        g = conn.execute(
            "SELECT COUNT(*) FROM exam_trials WHERE level='A1' AND module='hoeren'"
        ).fetchone()[0]
    assert g == 1


def test_lesen_routes_end_to_end(client):
    grade = client.post("/api/a1/lesen/grade", json={
        "set_id": 1, "duration_seconds": 750,
        "answers": {"a1_l_01_t1_q01": "R"},
    })
    assert grade.status_code == 200
    hist = client.get("/api/a1/lesen/history")
    assert hist.status_code == 200
    assert len(hist.json()["history"]) == 1
    with database.db_progress_conn(_PDB) as conn:
        g = conn.execute(
            "SELECT COUNT(*) FROM exam_trials WHERE level='A1' AND module='lesen'"
        ).fetchone()[0]
    assert g == 1
