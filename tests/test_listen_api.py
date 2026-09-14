# -*- coding: utf-8 -*-
"""`/api/listen/*` 路由（听力微训工坊 Task 3）。

契约面（delector/routes/listen.py）：
- GET  /api/listen/materials[?level=]                          → {"items":[{source_type,source_id,title,level}]}
- GET  /api/listen/materials/{source_type}/{source_id}         → {source_type,source_id,title,level,
                                                                    sentences:[str]}；缺失 404
- POST /api/listen/diagnose  body {expected,actual}            → ListenDiagnosis（tokens 六类 status）
- POST /api/listen/trials    body 七字段                       → {"trial_id"}
- GET  /api/listen/trials?limit=50                             → {"items":[...]}（created_at 倒序，limit 上限 100）

隔离纪律（对齐 test_encounter_routes.py）：路由内部走 get_db_path()（每次读
os.environ，不是 import 冻结）。env 用 setdefault（`delector/server.py:352` 模块级
单例 app 在收集期首次 import 即 create_app，直接赋值会把它抢成自己的名字）；
autouse fixture 把 DATABASE_PATH/PROGRESS_DB_PATH 切到 tmp_path throwaway 文件并
init_db；清理只清表不删库。TestClient 本机闸：client=("127.0.0.1",..) 放行，
默认 host("testclient") 命中 _require_localhost → 403。
"""

import os

import pytest

os.environ.setdefault("DATABASE_PATH", "test_listen_api.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_listen_api_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.server import app  # noqa: E402

VALID_STATUSES = {"correct", "umlaut", "case", "inflection", "missing", "extra"}


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB；清理只清表不删库。"""
    _db = str(tmp_path / "listen_api.db")
    _pdb = str(tmp_path / "listen_api_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    yield
    # 只清表不删库：模块级单例 app 与共享进程都依赖这些 env 指向的库文件仍在
    try:
        conn = database.get_db(_db)
        try:
            conn.execute("DELETE FROM listen_trials")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client():
    """显式本机来源：命中 _require_localhost 放行分支。"""
    return TestClient(app, client=("127.0.0.1", 54321))


def _seed_encounter(level: str = "A2", title: str = "Ein Tag im Park") -> int:
    """插入一篇 encounter 短文（content 含多句，供切句断言）。"""
    content = "Guten Morgen! Ich heiße Anna. Ich komme aus Berlin und lerne Deutsch."
    return database.create_encounter_text(title=title, level=level, source="test", content=content)


# ── materials 聚合 ─────────────────────────────────────────────────────


def test_materials_aggregates_encounter_and_hoeren(client):
    """materials 聚合 encounter 短文 + hoeren 音频句库，字段契约钉死。"""
    tid = _seed_encounter(level="A2", title="Park")
    tid2 = _seed_encounter(level="A1", title="Hallo")
    res = client.get("/api/listen/materials")
    assert res.status_code == 200
    items = res.json()["items"]
    assert {it["source_type"] for it in items} == {"encounter", "hoeren"}
    enc = [it for it in items if it["source_type"] == "encounter"]
    assert {it["source_id"] for it in enc} == {tid, tid2}
    assert {it["title"] for it in enc} == {"Park", "Hallo"}
    hoeren = [it for it in items if it["source_type"] == "hoeren"]
    assert {it["source_id"] for it in hoeren} == {1, 2, 3, 4, 5}
    assert all(it["level"] == "A1" for it in hoeren)
    assert all(it["title"] for it in hoeren)
    for it in items:
        assert set(it) == {"source_type", "source_id", "title", "level"}


def test_materials_level_filter(client):
    """level 过滤：为空返回全部；A2 只含 encounter；A1 含 encounter A1 + 全部 hoeren。"""
    _seed_encounter(level="A2")
    _seed_encounter(level="A1")
    res = client.get("/api/listen/materials", params={"level": "A2"})
    items = res.json()["items"]
    assert items, "A2 过滤不应为空"
    assert all(it["level"] == "A2" for it in items)
    assert all(it["source_type"] == "encounter" for it in items), "hoeren 全为 A1，A2 过滤应排除"
    res2 = client.get("/api/listen/materials", params={"level": "A1"})
    items2 = res2.json()["items"]
    assert any(it["source_type"] == "hoeren" for it in items2)
    assert all(it["level"] == "A1" for it in items2)


# ── materials 详情（切句） ─────────────────────────────────────────────


def test_materials_detail_encounter_sentences(client):
    """encounter 详情：content 用 split_sentences_pure_python 切句返回字符串列表。"""
    tid = _seed_encounter(level="A1", title="Begrüßung")
    res = client.get(f"/api/listen/materials/encounter/{tid}")
    assert res.status_code == 200
    data = res.json()
    assert data["source_type"] == "encounter"
    assert data["source_id"] == tid
    assert data["title"] == "Begrüßung"
    assert data["level"] == "A1"
    assert isinstance(data["sentences"], list)
    assert len(data["sentences"]) > 1
    assert all(isinstance(s, str) and s for s in data["sentences"])


def test_materials_detail_hoeren_sentences(client):
    """hoeren 详情：句子从题面 audio_text_de 切句而来，非空字符串列表。"""
    res = client.get("/api/listen/materials/hoeren/1")
    assert res.status_code == 200
    data = res.json()
    assert data["source_type"] == "hoeren"
    assert data["source_id"] == 1
    assert data["title"]
    assert data["level"] == "A1"
    assert len(data["sentences"]) > 1
    assert all(isinstance(s, str) and s for s in data["sentences"])


def test_materials_detail_missing_404(client):
    """材料不存在或类型未知 → 404 人话。"""
    r1 = client.get("/api/listen/materials/encounter/99999")
    assert r1.status_code == 404
    r2 = client.get("/api/listen/materials/hoeren/999")
    assert r2.status_code == 404
    r3 = client.get("/api/listen/materials/unknown/1")
    assert r3.status_code == 404


# ── diagnose ───────────────────────────────────────────────────────────


def test_diagnose_endpoint_shape(client):
    """diagnose 本地诊断：返回 ListenDiagnosis 形状，tokens.status 六类之一。"""
    res = client.post(
        "/api/listen/diagnose",
        json={"expected": "Ich gehe nach Hause", "actual": "Ich gehe nach Haus"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["expected"] == "Ich gehe nach Hause"
    assert data["actual"] == "Ich gehe nach Haus"
    assert isinstance(data["correct"], int)
    assert isinstance(data["total"], int)
    assert isinstance(data["score"], float)
    assert data["total"] == 4
    assert any(t["status"] == "inflection" for t in data["tokens"])
    for t in data["tokens"]:
        assert set(t) == {"token", "status", "hint"}
        assert t["status"] in VALID_STATUSES
        assert isinstance(t["hint"], str)


# ── trials 落盘与回读 ──────────────────────────────────────────────────


def test_trials_post_get_roundtrip(client):
    """POST /trials 落盘返回 trial_id；GET /trials 回读字段一致，score=correct/total。"""
    res = client.post(
        "/api/listen/trials",
        json={
            "mode": "diktat",
            "source_type": "encounter",
            "source_id": 3,
            "level": "A2",
            "total": 8,
            "correct": 6,
            "duration_sec": 120,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"trial_id"}
    assert isinstance(body["trial_id"], int)
    res2 = client.get("/api/listen/trials")
    assert res2.status_code == 200
    items = res2.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["id"] == body["trial_id"]
    assert row["mode"] == "diktat"
    assert row["source_type"] == "encounter"
    assert row["source_id"] == 3
    assert row["level"] == "A2"
    assert row["total"] == 8
    assert row["correct"] == 6
    assert row["score"] == pytest.approx(0.75)
    assert row["duration_sec"] == 120
    assert row["created_at"]


def test_trials_ordered_desc_and_limit(client):
    """GET /trials 按 created_at 倒序，limit 生效且上限 100。"""
    for correct in (1, 2, 3):
        client.post(
            "/api/listen/trials",
            json={
                "mode": "diktat",
                "source_type": "encounter",
                "source_id": 1,
                "level": "A1",
                "total": 3,
                "correct": correct,
                "duration_sec": 10,
            },
        )
    res = client.get("/api/listen/trials", params={"limit": 2})
    items = res.json()["items"]
    assert len(items) == 2
    ids = [it["id"] for it in items]
    assert ids == sorted(ids, reverse=True), "created_at 倒序（同秒以 id 倒序打平）"
    # limit 上限 100：请求超大 limit 也应被钳制（此处只验不报错）
    res2 = client.get("/api/listen/trials", params={"limit": 500})
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 3


def test_trials_rejects_invalid_body(client):
    """trials body 缺字段 → Pydantic 422。"""
    res = client.post("/api/listen/trials", json={"mode": "diktat"})
    assert res.status_code == 422
