# -*- coding: utf-8 -*-
"""`/api/encounter/*` 路由（遇见区 i+1 Task A2）。

契约面（delector/routes/encounter.py，全部端点走默认 env DB 路径）：
- GET  /api/encounter/texts[?level=]      → {"texts":[{id,title,level,source,word_count,created_at}]}
- GET  /api/encounter/texts/{text_id}      → 单篇含 content/pack_json；缺失 404
- POST /api/encounter/texts  (localhost)   → 手工加文本 → 201 {id,title,level}
- POST /api/encounter/import-pack (localhost) → encounter-pack/v1 整包落库 → {id, imported}
- validate_pack(pack) 纯函数：schema/pack_id/article{title,raw_text} 必需

隔离纪律（对齐 test_server.py / test_encounter_store.py）：路由内部走
get_db_path()（每次读 os.environ，不是 import 冻结）。autouse fixture 把
DATABASE_PATH/PROGRESS_DB_PATH 钉到 tmp_path throwaway 文件并 init_db；Windows
句柄释放：删文件前 gc.collect()。TestClient 本机闸：client=("127.0.0.1",..) 放行，
默认 host("testclient") 命中 _require_localhost → 403。
"""
import gc
import json
import os

import pytest

# 先钉 env 再 import server（模块级 create_app 的 init_db 有副作用）
os.environ.setdefault("DATABASE_PATH", "test_encounter_routes.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_routes_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.routes import encounter as encounter_mod  # noqa: E402
from delector.server import app  # noqa: E402

CARD_PACK_SCHEMA = "encounter-pack/v1"


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB（encounter + progress）。"""
    _db = str(tmp_path / "encounter_routes.db")
    _pdb = str(tmp_path / "encounter_routes_progress.db")
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
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    yield
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


@pytest.fixture
def local_client():
    """显式本机来源：命中 _require_localhost 放行分支。"""
    return TestClient(app, client=("127.0.0.1", 54321))


@pytest.fixture
def lan_client():
    """默认 host 是 'testclient'，不在回环白名单 → 命中 _require_localhost 拒绝。"""
    return TestClient(app)


def _fixture_pack(pack_id="t1", cefr="a2"):
    """合法的 encounter-pack/v1 夹具；estimated_cefr 默认小写以测归一化。"""
    return {
        "schema": CARD_PACK_SCHEMA,
        "pack_id": pack_id,
        "source": {"kind": "job1"},
        "article": {
            "title": "Ein Tag im Park",
            "raw_text": "Es war einmal ein sonniger Tag im Park.",
            "char_count": 41,
        },
        "analysis": {"tokens_total": 8, "known_rate": 0.25},
        "glosses": [],
        "estimated_cefr": cefr,
    }


# ── 注册守卫：encounter 路由真的挂进 app ─────────────────────────────────────

def test_encounter_module_has_router_and_registered(local_client):
    """encounter 模块定义 APIRouter 且端点可达（register 守卫在 test_server 钉全量）。"""
    assert isinstance(encounter_mod.router, __import__("fastapi").APIRouter)
    resp = local_client.get("/api/encounter/texts")
    assert resp.status_code == 200
    assert resp.json() == {"texts": []}


# ── validate_pack 纯函数 ────────────────────────────────────────────────────

def test_validate_pack_accepts_valid_pack():
    encounter_mod.validate_pack(_fixture_pack())


@pytest.mark.parametrize("mutator", [
    lambda p: p.update(schema="wrong"),
    lambda p: p.update(schema=""),
    lambda p: p.pop("schema", None),
])
def test_validate_pack_rejects_bad_schema(mutator):
    p = _fixture_pack()
    mutator(p)
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p)


def test_validate_pack_rejects_missing_or_blank_pack_id():
    p = _fixture_pack()
    p.pop("pack_id")
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p)
    p2 = _fixture_pack(pack_id="   ")
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p2)


def test_validate_pack_rejects_non_dict():
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(["not", "dict"])


def test_validate_pack_rejects_missing_or_bad_article():
    p = _fixture_pack()
    p.pop("article")
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p)
    p2 = _fixture_pack()
    p2["article"] = "not a dict"
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p2)


@pytest.mark.parametrize("field", ["title", "raw_text"])
def test_validate_pack_rejects_blank_article_fields(field):
    p = _fixture_pack()
    p["article"][field] = ""
    with pytest.raises(ValueError):
        encounter_mod.validate_pack(p)


# ── GET 列表 / 详情 / 404 ──────────────────────────────────────────────────

def test_get_list_empty(local_client):
    resp = local_client.get("/api/encounter/texts")
    assert resp.status_code == 200
    assert resp.json() == {"texts": []}


def test_get_list_shows_created_row_with_word_count(local_client):
    created = local_client.post(
        "/api/encounter/texts",
        json={"title": "Hallo", "level": "A2", "source": "manual",
              "content": "Guten Tag\n\nIch heiße Lukas."},
    )
    assert created.status_code == 201
    created_id = created.json()["id"]

    resp = local_client.get("/api/encounter/texts")
    body = resp.json()
    assert len(body["texts"]) == 1
    row = body["texts"][0]
    assert row["id"] == created_id
    assert row["title"] == "Hallo"
    assert row["level"] == "A2"
    assert row["source"] == "manual"
    assert row["word_count"] == 5  # 空白分词：Guten/Tag/Ich/heiße/Lukas.
    assert row["created_at"]


def test_get_list_filter_by_level(local_client):
    local_client.post("/api/encounter/texts", json={"title": "a", "level": "A1", "content": "x y"})
    local_client.post("/api/encounter/texts", json={"title": "b", "level": "A2", "content": "x y"})
    a2 = local_client.get("/api/encounter/texts?level=A2").json()["texts"]
    assert [r["title"] for r in a2] == ["b"]
    a1 = local_client.get("/api/encounter/texts?level=A1").json()["texts"]
    assert [r["title"] for r in a1] == ["a"]


def test_get_detail_returns_full_row(local_client):
    created = local_client.post(
        "/api/encounter/texts",
        json={"title": "Detail", "level": "A2", "source": "s", "content": "Erster Absatz."},
    ).json()
    resp = local_client.get(f"/api/encounter/texts/{created['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == created["id"]
    assert data["title"] == "Detail"
    assert data["level"] == "A2"
    assert data["source"] == "s"
    assert data["content"] == "Erster Absatz."
    assert "pack_json" in data


def test_get_detail_missing_returns_404(local_client):
    resp = local_client.get("/api/encounter/texts/9999")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ── POST 手工加文本 ────────────────────────────────────────────────────────

def test_post_create_level_normalized_upper(local_client):
    resp = local_client.post(
        "/api/encounter/texts",
        json={"title": "Norm", "level": "a2", "content": "ein zwei drei"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["level"] == "A2"
    # 详情回读确认落库即归一化值
    detail = local_client.get(f"/api/encounter/texts/{data['id']}").json()
    assert detail["level"] == "A2"


def test_post_create_invalid_level_400(local_client):
    resp = local_client.post(
        "/api/encounter/texts",
        json={"title": "x", "level": "C2", "content": "abc"},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


@pytest.mark.parametrize("payload", [
    {"title": "", "level": "A2", "content": "abc"},          # title 空
    {"title": "x", "level": "A2", "content": ""},            # content 空
])
def test_post_create_blank_fields_rejected(local_client, payload):
    resp = local_client.post("/api/encounter/texts", json=payload)
    # min_length=1 → Pydantic 422（缺/空标量 string 校验失败）
    assert resp.status_code in (400, 422)


def test_post_create_localhost_gate_denies_lan(lan_client):
    resp = lan_client.post(
        "/api/encounter/texts",
        json={"title": "x", "level": "A2", "content": "abc"},
    )
    assert resp.status_code == 403


# ── import-pack ────────────────────────────────────────────────────────────

def test_import_pack_happy_path_normalizes_level(local_client):
    resp = local_client.post("/api/encounter/import-pack", json={"pack": _fixture_pack()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["imported"] is True

    texts = local_client.get("/api/encounter/texts").json()["texts"]
    assert len(texts) == 1
    assert texts[0]["title"] == "Ein Tag im Park"
    assert texts[0]["level"] == "A2"  # 小写 "a2" 归一化大写

    detail = local_client.get(f"/api/encounter/texts/{data['id']}").json()
    stored = json.loads(detail["pack_json"])
    assert stored["schema"] == CARD_PACK_SCHEMA
    assert stored["pack_id"] == "t1"
    assert stored["article"]["raw_text"] == "Es war einmal ein sonniger Tag im Park."


def test_import_pack_bad_level_400(local_client):
    resp = local_client.post(
        "/api/encounter/import-pack",
        json={"pack": _fixture_pack(cefr="C2")},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_import_pack_invalid_schema_400(local_client):
    p = _fixture_pack()
    p["schema"] = "encounter-pack/OLD"
    resp = local_client.post("/api/encounter/import-pack", json={"pack": p})
    assert resp.status_code == 400


def test_import_pack_missing_keys_400(local_client):
    p = _fixture_pack()
    p.pop("article")
    resp = local_client.post("/api/encounter/import-pack", json={"pack": p})
    assert resp.status_code == 400


def test_import_pack_idempotent_same_id_single_row(local_client):
    first = local_client.post("/api/encounter/import-pack", json={"pack": _fixture_pack("dup")}).json()
    second = local_client.post("/api/encounter/import-pack", json={"pack": _fixture_pack("dup")}).json()
    assert first["id"] == second["id"]
    texts = local_client.get("/api/encounter/texts").json()["texts"]
    assert len(texts) == 1


def test_import_pack_localhost_gate_denies_lan(lan_client):
    resp = lan_client.post("/api/encounter/import-pack", json={"pack": _fixture_pack()})
    assert resp.status_code == 403
