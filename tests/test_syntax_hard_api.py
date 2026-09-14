# -*- coding: utf-8 -*-
"""`/api/syntax/*` 路由（长难句精读工坊 Task 3）。

契约面（delector/routes/syntax_hard.py）：
- GET  /api/syntax/hard-sentences?source=&source_id=&level=&min_score=&limit=
      → {"items":[{sentence, score, level, dimensions, path, source, source_id, sentence_index}]}
      source ∈ article/encounter/all（默认 all）；level/min_score 过滤；limit 默认 50 上限 100
- GET  /api/syntax/hard-sentences/detail?source=&source_id=&sentence_index=
      → {sentence, score, level, dimensions, path, analysis{clause_tree, topology}}；越界/缺失 404
- POST /api/syntax/hard-sentence/trials body 七字段 → {"trial_id"}
- GET  /api/syntax/hard-sentence/trials?limit=50 → {"items":[...]}（created_at 倒序，limit 上限 100）

隔离纪律（对齐 test_listen_api.py）：路由内部走 get_db_path()（每次读 os.environ，
非 import 冻结）。env 用 setdefault（delector/server.py:352 模块级单例 app 在收集期
首次 import 即 create_app，直接赋值会把它抢成自己的名字）；autouse fixture 把
DATABASE_PATH/PROGRESS_DB_PATH 切到 tmp_path throwaway 文件并 init_db，同时清空
进程内存排名缓存（键=source+id）；清理只清表不删库。TestClient 本机闸：
client=("127.0.0.1",..) 放行，默认 host("testclient") 命中 _require_localhost → 403。
"""

import os

import pytest

os.environ.setdefault("DATABASE_PATH", "test_syntax_hard_api.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_syntax_hard_api_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.routes import syntax_hard  # noqa: E402
from delector.server import app  # noqa: E402
from delector.services.syntax_score import SentenceScore  # noqa: E402

_ARTICLE_TEXT = (
    "Guten Morgen! Ich heiße Anna. Ich komme aus Berlin und lerne Deutsch. "
    "Obwohl es gestern geregnet hat, bin ich trotzdem spazieren gegangen."
)


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB + 清空进程内存排名缓存；只清表不删库。"""
    _db = str(tmp_path / "syntax_api.db")
    _pdb = str(tmp_path / "syntax_api_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    syntax_hard._RANK_CACHE.clear()  # 跨用例不共享排名缓存（键=source+id）
    yield
    # 只清表不删库：模块级单例 app 与共享进程都依赖这些 env 指向的库文件仍在
    try:
        conn = database.get_db(_db)
        try:
            conn.execute("DELETE FROM hard_sentence_trials")
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


def _seed_article() -> int:
    """插入一篇 article（正文含多句）。"""
    return database.ingest_article(title="Test Artikel", text=_ARTICLE_TEXT)


def _fake_scored(entries):
    """构造 rank_sentences 的假返回：[(sentence, score, level), ...] → 列表[SentenceScore]。"""
    return [
        SentenceScore(score=score, level=level, dimensions={}, path="pure", sentence=sentence)
        for sentence, score, level in entries
    ]


# ── hard-sentences 列表（真实计算） ────────────────────────────────────


def test_hard_sentences_article_shape_and_order(client):
    """article 源：字段契约逐字、难度降序、source/source_id/sentence_index 正确。"""
    aid = _seed_article()
    res = client.get("/api/syntax/hard-sentences", params={"source": "article", "source_id": aid})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items, "文章至少一句"
    for it in items:
        assert set(it) == {
            "sentence",
            "score",
            "level",
            "dimensions",
            "path",
            "source",
            "source_id",
            "sentence_index",
        }
        assert it["source"] == "article"
        assert it["source_id"] == aid
        assert isinstance(it["sentence_index"], int)
        assert isinstance(it["score"], (int, float))
        assert it["level"] in ("A1", "A2", "B1", "B2")
        assert it["path"] in ("spacy", "pure")
    scores = [it["score"] for it in items]
    assert scores == sorted(scores, reverse=True)  # 难度降序
    # sentence_index 对齐原文切句：第 0 句应为首句
    assert any(it["sentence_index"] == 0 and it["sentence"] == "Guten Morgen!" for it in items)


def test_hard_sentences_encounter_shape(client):
    """encounter 源：复用 get_encounter_text 的 content 字段，字段契约与 article 一致。"""
    tid = _seed_encounter()
    res = client.get("/api/syntax/hard-sentences", params={"source": "encounter", "source_id": tid})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items
    for it in items:
        assert set(it) == {
            "sentence",
            "score",
            "level",
            "dimensions",
            "path",
            "source",
            "source_id",
            "sentence_index",
        }
        assert it["source"] == "encounter"
        assert it["source_id"] == tid


def test_hard_sentences_all_aggregates_both_sources(client):
    """source=all：聚合 article + encounter 两类材料，难度降序。"""
    aid = _seed_article()
    tid = _seed_encounter()
    res = client.get("/api/syntax/hard-sentences", params={"source": "all"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert {it["source"] for it in items} == {"article", "encounter"}
    assert {it["source_id"] for it in items} >= {aid, tid}
    scores = [it["score"] for it in items]
    assert scores == sorted(scores, reverse=True)


def test_hard_sentences_default_source_is_all(client):
    """source 缺省默认 all（不传 source 也出结果）。"""
    _seed_article()
    res = client.get("/api/syntax/hard-sentences")
    assert res.status_code == 200
    assert res.json()["items"]


def test_hard_sentences_missing_material_404(client):
    """材料不存在 / 来源非法 → 404 人话。"""
    r1 = client.get("/api/syntax/hard-sentences", params={"source": "article", "source_id": 99999})
    assert r1.status_code == 404
    r2 = client.get("/api/syntax/hard-sentences", params={"source": "encounter", "source_id": 99999})
    assert r2.status_code == 404
    r3 = client.get("/api/syntax/hard-sentences", params={"source": "unknown", "source_id": 1})
    assert r3.status_code == 404


# ── hard-sentences 过滤与护栏（monkeypatch rank_sentences 钉死逻辑） ────


def test_hard_sentences_level_filter(client, monkeypatch):
    """level 过滤：只保留匹配 CEFR 级别的句子。"""
    tid = _seed_encounter()
    fake = _fake_scored(
        [
            ("Erstens.", 80.0, "B2"),
            ("Zweitens.", 30.0, "A2"),
            ("Drittens.", 10.0, "A1"),
        ]
    )
    monkeypatch.setattr(syntax_hard, "rank_sentences", lambda text: list(fake))
    res = client.get(
        "/api/syntax/hard-sentences", params={"source": "encounter", "source_id": tid, "level": "A2"}
    )
    items = res.json()["items"]
    assert [it["level"] for it in items] == ["A2"]
    assert [it["sentence"] for it in items] == ["Zweitens."]


def test_hard_sentences_min_score_filter(client, monkeypatch):
    """min_score 过滤：只保留 score >= min_score 的句子。"""
    tid = _seed_encounter()
    fake = _fake_scored(
        [
            ("Erstens.", 80.0, "B2"),
            ("Zweitens.", 30.0, "A2"),
            ("Drittens.", 10.0, "A1"),
        ]
    )
    monkeypatch.setattr(syntax_hard, "rank_sentences", lambda text: list(fake))
    res = client.get(
        "/api/syntax/hard-sentences",
        params={"source": "encounter", "source_id": tid, "min_score": 40},
    )
    items = res.json()["items"]
    assert [it["sentence"] for it in items] == ["Erstens."]
    assert all(it["score"] >= 40 for it in items)


def test_hard_sentences_limit_and_cap(client, monkeypatch):
    """limit 生效且上限 100（请求超大 limit 被钳制）。"""
    tid = _seed_encounter()
    fake = _fake_scored([(f"S{i}.", float(100 - i), "B2") for i in range(120)])
    monkeypatch.setattr(syntax_hard, "rank_sentences", lambda text: list(fake))
    res = client.get(
        "/api/syntax/hard-sentences", params={"source": "encounter", "source_id": tid, "limit": 10}
    )
    assert len(res.json()["items"]) == 10
    res2 = client.get(
        "/api/syntax/hard-sentences", params={"source": "encounter", "source_id": tid, "limit": 500}
    )
    assert len(res2.json()["items"]) == 100  # 上限钳制


# ── detail 单句完整分析 ────────────────────────────────────────────────


def test_hard_sentences_detail_shape(client):
    """detail：单句完整分析（analysis 含 clause_tree/topology）供前端揭示渲染。"""
    aid = _seed_article()
    res = client.get(
        "/api/syntax/hard-sentences/detail",
        params={"source": "article", "source_id": aid, "sentence_index": 0},
    )
    assert res.status_code == 200
    data = res.json()
    assert set(data) == {"sentence", "score", "level", "dimensions", "path", "analysis"}
    assert data["sentence"] == "Guten Morgen!"
    assert isinstance(data["score"], (int, float))
    assert data["level"] in ("A1", "A2", "B1", "B2")
    assert data["path"] in ("spacy", "pure")
    assert isinstance(data["analysis"], dict)
    assert "clause_tree" in data["analysis"]
    assert "topology" in data["analysis"]


def test_hard_sentences_detail_404(client):
    """detail 越界 / 材料不存在 / 来源非法 → 404 人话。"""
    aid = _seed_article()
    r1 = client.get(
        "/api/syntax/hard-sentences/detail",
        params={"source": "article", "source_id": aid, "sentence_index": 999},
    )
    assert r1.status_code == 404
    r2 = client.get(
        "/api/syntax/hard-sentences/detail",
        params={"source": "article", "source_id": 99999, "sentence_index": 0},
    )
    assert r2.status_code == 404
    r3 = client.get(
        "/api/syntax/hard-sentences/detail",
        params={"source": "unknown", "source_id": 1, "sentence_index": 0},
    )
    assert r3.status_code == 404


def test_hard_sentences_detail_analysis_error_404(client, monkeypatch):
    """红线 1 纪律：单句分析抛异常（Android spaCy/数据差异）→ 404 人话而非 500。

    回归：v5.7.0 真机报「长难句清单加载失败 Internal Server Error」——detail 端点
    无容错（rank_sentences 有逐句 try/except 而 detail 没有），某句 analyze_syntax_tree
    抛 → 500。此测试钉死失败降级 404。
    """
    aid = _seed_article()

    def _boom(text):
        raise RuntimeError("spaCy 分析崩")

    monkeypatch.setattr(syntax_hard, "analyze_syntax_tree", _boom)
    res = client.get(
        "/api/syntax/hard-sentences/detail",
        params={"source": "article", "source_id": aid, "sentence_index": 0},
    )
    assert res.status_code == 404
    assert "无法分析" in res.json()["detail"]


def test_rank_source_split_error_returns_empty(client, monkeypatch):
    """切句异常（极端文本/环境差异）→ 单材料空榜 200，不炸调用方。"""
    tid = _seed_encounter()

    def _boom(text):
        raise RuntimeError("切句崩")

    monkeypatch.setattr(syntax_hard, "split_sentences_pure_python", _boom)
    res = client.get(
        "/api/syntax/hard-sentences",
        params={"source": "encounter", "source_id": tid},
    )
    assert res.status_code == 200
    assert res.json()["items"] == []


def test_hard_sentences_all_resilient_to_bad_material(client, monkeypatch):
    """source=all 逐材料隔离：坏材料（SQL/切句异常）只丢自身，其余材料仍上榜。"""
    _seed_encounter()
    fake = _fake_scored([("Einzig guter Satz.", 60.0, "B1")])
    monkeypatch.setattr(syntax_hard, "rank_sentences", lambda text: list(fake))

    def _boom():
        raise RuntimeError("文章表崩")

    monkeypatch.setattr(syntax_hard, "_list_article_ids", _boom)
    res = client.get("/api/syntax/hard-sentences", params={"source": "all"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items, "坏材料不应炸掉全榜"
    assert all(it["source"] == "encounter" for it in items)


# ── trials 落盘与回读（不挂闸） ────────────────────────────────────────


def test_trials_post_get_roundtrip(client):
    """POST trials 落盘返回 trial_id；GET trials 回读字段逐字一致。"""
    res = client.post(
        "/api/syntax/hard-sentence/trials",
        json={
            "source": "article",
            "source_id": 1,
            "sentence_index": 2,
            "level": "B2",
            "score": 72.5,
            "revealed": 1,
            "duration_sec": 90,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"trial_id"}
    assert isinstance(body["trial_id"], int)
    res2 = client.get("/api/syntax/hard-sentence/trials")
    assert res2.status_code == 200
    items = res2.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["id"] == body["trial_id"]
    assert row["source"] == "article"
    assert row["source_id"] == 1
    assert row["sentence_index"] == 2
    assert row["level"] == "B2"
    assert row["score"] == pytest.approx(72.5)
    assert row["revealed"] == 1
    assert row["duration_sec"] == 90
    assert row["created_at"]


def test_trials_ordered_desc_and_limit(client):
    """GET trials 按 created_at 倒序，limit 生效且上限 100。"""
    for i in range(3):
        client.post(
            "/api/syntax/hard-sentence/trials",
            json={
                "source": "encounter",
                "source_id": 1,
                "sentence_index": i,
                "level": "A2",
                "score": 50.0,
                "revealed": 0,
                "duration_sec": 10,
            },
        )
    res = client.get("/api/syntax/hard-sentence/trials", params={"limit": 2})
    items = res.json()["items"]
    assert len(items) == 2
    ids = [it["id"] for it in items]
    assert ids == sorted(ids, reverse=True), "created_at 倒序（同秒以 id 倒序打平）"
    res2 = client.get("/api/syntax/hard-sentence/trials", params={"limit": 500})
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 3  # 上限钳制不报错


def test_trials_rejects_invalid_body(client):
    """trials body 缺字段 → Pydantic 422。"""
    res = client.post("/api/syntax/hard-sentence/trials", json={"source": "article"})
    assert res.status_code == 422
