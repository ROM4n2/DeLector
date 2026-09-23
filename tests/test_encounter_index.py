# -*- coding: utf-8 -*-
"""`GET /api/encounter/texts/index` 路由（遇见区 i+1 Task 3）。

契约面（delector/routes/encounter.py::api_list_text_index）：
- GET /api/encounter/texts/index → {"items":[{id,title,level,word_count,total_tokens,lemma_seq}]}
- total_tokens / lemma_seq 取自 pack_json.analysis（annotate 口径：剔除 is_space、保留标点），
  零 spaCy、零写库，供前端用自身背词 deck 在本机算覆盖率并排序。
- pack_json 为空 / 非法 JSON / 结构异常 → 该行两字段 None，但**仍返回**（前端降级展示，不丢行）。
- **绝不返回** content / pack_json / source 原文（字段集精确相等）。
- **不挂本机闸**：局域网内手机/平板要能读到词序列索引。

隔离纪律（对齐 test_encounter_routes.py）：env 钉 tmp_path throwaway 双 DB（encounter+progress），
绝不碰仓库根 delector.db；Windows 句柄释放：删文件前 gc.collect()。TestClient 默认
host("testclient") 命中 _require_localhost → 会拒；本端点用例打默认 client 应为 200，
这正是"未挂本机闸"的证据。
"""

import gc
import os

import pytest

# 先钉 env 再 import server（模块级 create_app 的 init_db 有副作用），对齐既有测试。
os.environ.setdefault("DATABASE_PATH", "test_encounter_index.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_index_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.data.encounter_seed_dict import PRESET_ENCOUNTER_PACKS  # noqa: E402
from delector.server import app  # noqa: E402

ENDPOINT = "/api/encounter/texts/index"
# 精确字段集：集合相等，任何多出的字段（content/pack_json/source）都会让断言变红。
_EXPECTED_KEYS = {"id", "title", "level", "word_count", "total_tokens", "lemma_seq"}


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB（encounter + progress）；yield 出 encounter 路径。"""
    _db = str(tmp_path / "encounter_index.db")
    _pdb = str(tmp_path / "encounter_index_progress.db")
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
    yield _db
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
def client():
    """默认 TestClient：host = 'testclient'，会被 _require_localhost 拒 —— 用来证"未挂本机闸"。"""
    return TestClient(app)


# ── ① 空库 ──────────────────────────────────────────────────────────────────


def test_index_empty_db_returns_empty_items(client):
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


# ── ② 真包：token 口径与包内 analysis 一致 ───────────────────────────────────


def test_index_real_pack_exposes_tokens_and_lemma_seq(client, clean_db):
    pack = PRESET_ENCOUNTER_PACKS[0]
    imported_id = database.import_encounter_pack(pack, db_path=clean_db)

    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1

    item = items[0]
    assert item["id"] == imported_id
    assert item["total_tokens"] == pack["analysis"]["tokens_total"]
    assert item["lemma_seq"] == pack["analysis"]["lemma_seq"]
    # annotate 口径自洽：词序列长度 == tokens_total
    assert len(item["lemma_seq"]) == item["total_tokens"]


# ── ③ 手工短文（无 pack_json）：降级 None 但不丢行 ────────────────────────────


def test_index_manual_text_degrades_to_none_but_still_returned(client, clean_db):
    manual_id = database.create_encounter_text(
        title="Handschrift",
        level="A2",
        source="manual",
        content="Ein kurzer Satz.",
        db_path=clean_db,
    )

    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
    items = resp.json()["items"]

    ids = [it["id"] for it in items]
    assert manual_id in ids, "手工短文必须出现在索引里（不能丢行）"
    row = next(it for it in items if it["id"] == manual_id)
    assert row["total_tokens"] is None
    assert row["lemma_seq"] is None


# ── ④ 坏 JSON：降级 None 且整体 200（不 500） ────────────────────────────────


def test_index_bad_pack_json_degrades_and_returns_200(client, clean_db):
    bad_id = database.create_encounter_text(
        title="Kaputt",
        level="A2",
        source="manual",
        content="egal",
        pack_json="{bad",
        db_path=clean_db,
    )

    resp = client.get(ENDPOINT)
    assert resp.status_code == 200, "坏 pack_json 绝不能把端点打成 500"
    items = resp.json()["items"]
    row = next(it for it in items if it["id"] == bad_id)
    assert row["total_tokens"] is None
    assert row["lemma_seq"] is None


# ── ⑤ 字段集精确相等（防泄 + 契约面） ────────────────────────────────────────


def test_index_item_field_set_is_exact(client, clean_db):
    database.import_encounter_pack(PRESET_ENCOUNTER_PACKS[0], db_path=clean_db)

    item = client.get(ENDPOINT).json()["items"][0]
    assert set(item.keys()) == _EXPECTED_KEYS


# ── ⑥ 鉴权语义：默认 TestClient 应 200（证未挂本机闸） ───────────────────────


def test_index_not_gated_by_localhost(client):
    """默认 host=testclient 不在回环白名单；端点仍应 200 —— 即未挂 _require_localhost。"""
    resp = client.get(ENDPOINT)
    assert resp.status_code == 200
