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
import sys
import threading
import time
from typing import Any, Dict, List, Tuple

import pytest

os.environ.setdefault("DATABASE_PATH", "test_syntax_hard_api.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_syntax_hard_api_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.routes import encounter as encounter_mod  # noqa: E402
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


def test_spacy_status_endpoint(client):
    """spaCy 加载诊断端点（v5.7.4）：返回 {path, error}，只读契约。"""
    res = client.get("/api/syntax/spacy-status")
    assert res.status_code == 200
    data = res.json()
    assert set(data) == {"path", "error"}
    assert data["path"] in ("spacy", "pure")
    assert isinstance(data["error"], str)


def test_spacy_status_reports_live_error_on_pure_path(client, monkeypatch):
    """回归：spaCy 走 pure 时 error 必须是 get_spacy_nlp() 记录的实时异常，
    而非空串（v5.7.5 真机确诊：route 按值 import _spacy_load_error 导致永远为空）。"""
    from delector.nlp_engine import syntax_tree

    monkeypatch.setattr(syntax_hard, "get_spacy_nlp", lambda: None)
    syntax_tree._spacy_load_error = "md: OSError: [E050] Can't find model 'de_core_news_md'"
    try:
        res = client.get("/api/syntax/spacy-status")
        data = res.json()
        assert data["path"] == "pure"
        assert data["error"] == syntax_tree._spacy_load_error
        assert data["error"]  # 非空——前端不再兜底显示"未捕获到加载异常"
    finally:
        syntax_tree._spacy_load_error = ""


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


# ── 排名缓存容量 + 懒读正文（2026-09-28 swarm 审计 P2 / 性能）────────────────


def test_rank_cache_bounded_eviction():
    """_RANK_CACHE 有容量上限：超限淘汰最早过期项，长期运行不无界增长。"""
    syntax_hard._RANK_CACHE.clear()
    limit = syntax_hard._RANK_CACHE_MAX_ENTRIES
    for i in range(limit):
        syntax_hard._put_rank_cache(f"m:{i}", 1000.0 + i, [])
    assert len(syntax_hard._RANK_CACHE) == limit

    syntax_hard._put_rank_cache("m:new", 10_000_000.0, [])
    assert len(syntax_hard._RANK_CACHE) == limit, "超限后应淘汰到上限"
    assert "m:0" not in syntax_hard._RANK_CACHE, "最早过期项应被淘汰"
    assert "m:new" in syntax_hard._RANK_CACHE
    syntax_hard._RANK_CACHE.clear()


def test_list_article_ids_returns_only_ids():
    """_list_article_ids 只取 id（不 materialize 全文）：避免每请求全量读正文。"""
    aid = _seed_article()
    ids = syntax_hard._list_article_ids()
    assert aid in ids
    assert all(isinstance(i, int) for i in ids), "应只返回 id（int），而非含 raw_text 的行 dict"


def test_single_material_cache_hit_skips_text_fetch(client, monkeypatch):
    """单材料热请求（缓存命中）不得再读材料正文——正文仅在缓存缺失时读。"""
    aid = _seed_article()
    client.get("/api/syntax/hard-sentences", params={"source": "article", "source_id": aid})

    calls = {"n": 0}
    orig = syntax_hard._material_text

    def _counted(source: str, source_id: int) -> str:
        calls["n"] += 1
        return orig(source, source_id)

    monkeypatch.setattr(syntax_hard, "_material_text", _counted)
    client.get("/api/syntax/hard-sentences", params={"source": "article", "source_id": aid})
    assert calls["n"] == 0, "缓存命中时不应再读材料正文"


# ── _RANK_CACHE 并发安全 + source=all 聚合层缓存（2026-10-03 Task 1）────────


def _agg_item(source: str, source_id: int, score: float) -> Dict[str, Any]:
    """聚合路径用的最小 item（字段对齐真实 _rank_source 输出，过滤/排序会读 score/level）。"""
    return {
        "sentence": f"Satz {source_id}",
        "score": score,
        "level": "B1",
        "dimensions": {},
        "path": "pure",
        "source": source,
        "source_id": source_id,
        "sentence_index": 0,
    }


@pytest.fixture
def agg_probe(monkeypatch):
    """把 source=all 的逐材料来源换成 300 个假 id（越过 256 上限），并统计 _rank_source 调用数。

    300 = 200 article + 100 encounter：修复前逐材料逐条写缓存，第 257 条起最早写的那批
    expires 最小 ⇒ 被 min() 淘汰 ⇒ 第二轮整榜从第 1 条就全 miss（命中率悬崖）。

    假 _rank_source MUST 像真身一样**逐条 _put_rank_cache**（expires 逐条递增），
    否则测的就不是真实缺陷：用例③要断言「sweep 后逐材料条目被清空」，
    若假身不写缓存，该断言就是空的。
    """
    calls = {"n": 0}

    def _fake_rank_source(source: str, source_id: int) -> List[Dict[str, Any]]:
        calls["n"] += 1
        items = [_agg_item(source, source_id, 50.0 + (source_id % 7))]
        # 模拟真身：now 每材料各取一次 ⇒ expires 逐条递增（悬崖的成因之一）
        syntax_hard._put_rank_cache(
            f"{source}:{source_id}", time.monotonic() + syntax_hard._CACHE_TTL_SEC, items
        )
        return items

    monkeypatch.setattr(syntax_hard, "_rank_source", _fake_rank_source)
    monkeypatch.setattr(syntax_hard, "_list_article_ids", lambda: list(range(1, 201)))
    monkeypatch.setattr(syntax_hard, "_list_encounter_ids", lambda: list(range(1, 101)))
    return calls


def test_rank_cache_aggregate_hit_on_second_sweep(client, agg_probe):
    """300 篇材料时第二轮 source=all 必须整榜命中：_rank_source 调用次数为 0。

    修复前：无聚合层 ⇒ 第二轮又逐材料调 300 次（悬崖：命中率 0%）。
    """
    syntax_hard._RANK_CACHE.clear()
    first = client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    assert first.status_code == 200
    assert first.json()["items"], "第一轮应产出整榜"
    after_first = agg_probe["n"]
    assert after_first == 300, f"第一轮应逐材料算 300 次，实际 {after_first}"

    second = client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    assert second.status_code == 200
    assert agg_probe["n"] - after_first == 0, (
        f"第二轮应整榜命中（聚合层缓存），实际又调了 {agg_probe['n'] - after_first} 次 _rank_source —— "
        "命中悬崖：逐材料条目被容量淘汰打穿"
    )
    assert second.json()["items"] == first.json()["items"], "整榜命中时两次结果应一致"


def test_rank_cache_concurrent_writes_are_safe():
    """16 线程 hammer _put_rank_cache：不得抛 RuntimeError（dictionary changed size）。

    修复前 min() 迭代期间另一线程写入 ⇒ RuntimeError ⇒ 被 source=all 的
    except Exception: continue 吞掉 ⇒ 该材料静默从难度榜消失（结果错，非仅性能）。

    为什么显式收紧 sys.setswitchinterval：竞态窗口只有 min() 迭代 256 个 key 的
    那一瞬（微秒级），而 CPython 默认 5ms 的 GIL 时间片几乎不会正好落在里面
    （本机实测默认片下 10 轮 0 复现）。收紧时间片 = 提高抢占密度，让竞态**确定性**
    可复现，而不是"偶发所以测不了"（[Instinct: No-Silent-Drop]）。加了锁之后
    无论时间片多小都不应有异常，故本用例对时间片取值不敏感、不会变脆。
    """
    syntax_hard._RANK_CACHE.clear()
    n_threads, n_iters = 16, 200
    barrier = threading.Barrier(n_threads)
    errors: List[BaseException] = []
    err_lock = threading.Lock()

    def _worker(tid: int) -> None:
        try:
            barrier.wait(timeout=30)  # 真并发：16 线程同一时刻起跑，否则测的是串行假通过
            for i in range(n_iters):
                syntax_hard._put_rank_cache(f"t{tid}:{i}", 1000.0 + tid * n_iters + i, [])
        except BaseException as exc:  # noqa: BLE001 —— 测试要看见任何竞态异常
            with err_lock:
                errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # 放大抢占密度：让 min() 迭代窗口真能被撞上
    try:
        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            assert not t.is_alive(), "并发 worker 线程未在 60s 内结束（Barrier 死锁？）"
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, f"并发写缓存出现 {len(errors)} 个异常，样例：{[repr(e) for e in errors[:3]]}"
    assert len(syntax_hard._RANK_CACHE) <= syntax_hard._RANK_CACHE_MAX_ENTRIES, (
        f"缓存条目 {len(syntax_hard._RANK_CACHE)} 应受上限 {syntax_hard._RANK_CACHE_MAX_ENTRIES} 约束"
    )
    syntax_hard._RANK_CACHE.clear()


def test_rank_cache_sweep_leaves_no_per_material_entry(client, agg_probe):
    """聚合路径跑完后 _RANK_CACHE 只剩聚合 key：逐材料条目被清空（留着只会被 min() 误伤）。"""
    syntax_hard._RANK_CACHE.clear()
    client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    keys = sorted(syntax_hard._RANK_CACHE)
    assert len(keys) == 1, f"聚合路径后应只剩 1 条聚合 key，实际 {len(keys)} 条：{keys[:5]}"
    assert keys[0] == syntax_hard._ALL_RANK_CACHE_KEY


def test_rank_cache_aggregate_preserves_per_material_isolation(client, monkeypatch):
    """聚合层 MUST 保留逐材料异常隔离：单个材料炸只丢它自己，整榜仍 200 且含其它材料。"""
    syntax_hard._RANK_CACHE.clear()
    calls: List[Tuple[str, int]] = []

    def _flaky_rank_source(source: str, source_id: int) -> List[Dict[str, Any]]:
        calls.append((source, source_id))
        if source_id == 2:
            raise RuntimeError("模拟单材料分析炸掉")
        return [_agg_item(source, source_id, 50.0)]

    monkeypatch.setattr(syntax_hard, "_rank_source", _flaky_rank_source)
    monkeypatch.setattr(syntax_hard, "_list_article_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(syntax_hard, "_list_encounter_ids", lambda: [])

    res = client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    assert res.status_code == 200, "单材料异常不得炸整榜"
    ids = sorted(it["source_id"] for it in res.json()["items"])
    assert ids == [1, 3], f"只应丢 source_id=2，实际 {ids}"
    assert ("article", 2) in calls, "炸掉的材料应被真实调用过（异常来自 _rank_source 而非被跳过）"
    syntax_hard._RANK_CACHE.clear()


# ── 聚合 key 的失效入口（2026-10-03 Task 1 收尾）───────────────────────────────
# 缺陷：source=all 的聚合 key（TTL 300s）引入后**没有任何失效入口**。
# 基线行为：新材料 ⇒ 新 key ⇒ 下次 source=all 立即可见；删除的材料下次 sweep 自然消失。
# 引入聚合层后：新入库文章在聚合 key 命中期间最长 300 秒不出现在难度榜；已删材料滞留 300 秒。
# 这与 Task 1 修的「材料静默从难度榜消失」是同一类缺陷（结果错，不是性能问题），
# 只是被 TTL 兜底且自愈、且零测试覆盖 —— 故本组用例钉死失效入口。


@pytest.fixture
def mutable_ids(monkeypatch):
    """可控的假 id 列表（可变）+ _rank_source 调用记录；(art, enc, calls) 三元组。

    不用 agg_probe：它的 id 列表是写死的 range()，本组用例要在两次 sweep **之间**
    增删 id 来模拟"新材料入库 / 材料被删"。

    假 _rank_source **不写**逐材料缓存：聚合路径收尾的 _drop_rank_cache_except 已把
    逐材料条目清空 ⇒ 本组用例的断言只取决于聚合 key 在不在，与逐材料条目无关。
    """
    art: List[int] = [1, 2]
    enc: List[int] = []
    calls: List[Tuple[str, int]] = []

    def _fake_rank_source(source: str, source_id: int) -> List[Dict[str, Any]]:
        calls.append((source, source_id))
        return [_agg_item(source, source_id, 50.0)]

    monkeypatch.setattr(syntax_hard, "_rank_source", _fake_rank_source)
    monkeypatch.setattr(syntax_hard, "_list_article_ids", lambda: list(art))
    monkeypatch.setattr(syntax_hard, "_list_encounter_ids", lambda: list(enc))
    return art, enc, calls


def _sweep_all(client):
    """跑一次 source=all 聚合路径（返回 items 的 source_id 升序列表）。"""
    res = client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    assert res.status_code == 200
    return sorted(it["source_id"] for it in res.json()["items"])


def _enc_ids_in_all(client):
    """source=all 里属于 encounter 的**去重** source_id 集合。

    两处坑：init_db 预置 4 篇示例文章（article 与 encounter 的 id 各自从 1 起，会撞号），
    以及聚合榜是逐句条目（同 id 出现多次）⇒ 必须按 source 字段筛 + 去重。
    """
    res = client.get("/api/syntax/hard-sentences", params={"source": "all", "limit": 100})
    assert res.status_code == 200
    return {it["source_id"] for it in res.json()["items"] if it["source"] == "encounter"}


def test_invalidate_rank_cache_makes_new_material_visible(client, mutable_ids):
    """失效后新材料**立即**出现在难度榜：入库 → invalidate → 下一轮 source=all 必须重聚合。

    修复前（无失效入口）：聚合 key 在 TTL 300s 内一直命中旧整榜 ⇒ 新材料最长 300 秒
    不出现在难度榜——与 Task 1 修的「材料静默从难度榜消失」同类，只是被 TTL 兜底自愈。
    """
    art, _enc, calls = mutable_ids
    syntax_hard._RANK_CACHE.clear()
    assert _sweep_all(client) == [1, 2]
    assert ("article", 1) in calls and ("article", 2) in calls, "第一轮应逐材料聚合"

    # 新材料入库（id 列表增长）。聚合 key 仍在 TTL 内 ⇒ 未失效时下面这次直接命中旧榜。
    art.append(3)
    calls.clear()
    assert _sweep_all(client) == [1, 2], "前置条件：TTL 内未失效 ⇒ 命中旧聚合榜"
    assert calls == [], "前置条件：命中聚合 key 时不应再逐材料调 _rank_source"

    syntax_hard.invalidate_rank_cache()
    calls.clear()
    ids = _sweep_all(client)
    assert ("article", 3) in calls, (
        "失效后必须重新聚合：新材料 id=3 未被 _rank_source 调用 ⇒ 它仍不在难度榜里"
        "（新材料静默缺席，最长 300s）"
    )
    assert ids == [1, 2, 3], f"整榜应含新旧全部材料，实际 {ids}"
    syntax_hard._RANK_CACHE.clear()


def test_invalidate_rank_cache_drops_deleted_material(client, mutable_ids):
    """失效后已删材料**立即**从难度榜消失（删除同理，不再滞留 300s）。"""
    art, _enc, calls = mutable_ids
    syntax_hard._RANK_CACHE.clear()
    assert _sweep_all(client) == [1, 2]

    art.remove(2)  # 材料被删（库里已无此 id）
    calls.clear()
    assert _sweep_all(client) == [1, 2], "前置条件：TTL 内未失效 ⇒ 旧榜仍含已删材料"

    syntax_hard.invalidate_rank_cache()
    calls.clear()
    ids = _sweep_all(client)
    assert ("article", 2) not in calls, "已删材料不得再被聚合（库里已无此 id）"
    assert ids == [1], f"已删材料应立即从难度榜消失，实际 {ids}"
    syntax_hard._RANK_CACHE.clear()


def test_invalidate_rank_cache_keeps_per_material_entries():
    """失效**只**清聚合 key：逐材料条目保留（最小动作取舍，见 invalidate_rank_cache docstring）。

    依据：聚合层已整榜覆盖逐材料条目（sweep 收尾还会 _drop_rank_cache_except 清掉它们）
    ⇒ 连带清逐材料条目会白丢单材料路径（source=article&source_id=）的热缓存，
    那条路径与本次写入/删除无关。聚合 key 失效后重聚合本就会重新写它们。
    """
    syntax_hard._RANK_CACHE.clear()
    expires = time.monotonic() + syntax_hard._CACHE_TTL_SEC
    syntax_hard._put_rank_cache("article:7", expires, [_agg_item("article", 7, 50.0)])
    syntax_hard._put_rank_cache(syntax_hard._ALL_RANK_CACHE_KEY, expires, [_agg_item("article", 7, 50.0)])

    syntax_hard.invalidate_rank_cache()

    assert syntax_hard._ALL_RANK_CACHE_KEY not in syntax_hard._RANK_CACHE, "聚合 key 应被清掉"
    assert "article:7" in syntax_hard._RANK_CACHE, (
        "逐材料条目应保留：单材料路径的热缓存与本次聚合失效无关，连带清纯属浪费"
    )
    syntax_hard._RANK_CACHE.clear()


def test_invalidate_rank_cache_is_idempotent_and_lock_safe():
    """失效入口幂等（重复调用不抛）+ 并发下不产生 RuntimeError（dictionary changed size）。

    幂等：key 不存在时 pop 不得抛——写入点与删除点都可能连续触发（同一批材料多次操作）。
    锁安全：失效 MUST 在 _RANK_CACHE_LOCK 内做。无锁时 pop 与并发 _put_rank_cache 的
    min() 迭代撞上 ⇒ RuntimeError ⇒ 被 source=all 的 except Exception: continue 吞掉
    ⇒ 材料静默从难度榜消失（与 _RANK_CACHE_LOCK 注释同一类竞态）。

    并发窗口：pop 必须是**真改动 size**（key 存在）才会撞上 min() 的迭代 ⇒ 一半 worker
    持续重写聚合 key 保证它存在，另一半 worker 填满过 256 触发 min() 大迭代。
    显式收紧 sys.setswitchinterval 提高抢占密度（finally 还原），手法同
    test_rank_cache_concurrent_writes_are_safe。
    """
    syntax_hard._RANK_CACHE.clear()
    syntax_hard.invalidate_rank_cache()  # 空缓存上调用：不得抛
    syntax_hard.invalidate_rank_cache()  # 幂等：重复调用不得抛
    expires = time.monotonic() + syntax_hard._CACHE_TTL_SEC
    syntax_hard._put_rank_cache(syntax_hard._ALL_RANK_CACHE_KEY, expires, [])
    syntax_hard.invalidate_rank_cache()
    assert syntax_hard._ALL_RANK_CACHE_KEY not in syntax_hard._RANK_CACHE, "聚合 key 应被清掉"

    n_threads, n_iters = 15, 200
    barrier = threading.Barrier(n_threads)
    errors: List[BaseException] = []
    err_lock = threading.Lock()

    def _worker(tid: int) -> None:
        try:
            barrier.wait(timeout=30)  # 真并发：15 线程同一时刻起跑，否则测的是串行假通过
            for i in range(n_iters):
                role = tid % 3
                if role == 0:
                    syntax_hard.invalidate_rank_cache()  # 被测方：无锁则与 min() 迭代相撞
                elif role == 1:
                    # 保证聚合 key 一直存在 ⇒ invalidate 的 pop 是真改动 size
                    syntax_hard._put_rank_cache(syntax_hard._ALL_RANK_CACHE_KEY, expires, [])
                else:
                    syntax_hard._put_rank_cache(f"t{tid}:{i}", 1000.0 + tid * n_iters + i, [])
        except BaseException as exc:  # noqa: BLE001 —— 测试要看见任何竞态异常
            with err_lock:
                errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # 放大抢占密度：让 min() 迭代窗口真能被撞上
    try:
        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            assert not t.is_alive(), "并发 worker 线程未在 60s 内结束（Barrier 死锁？）"
    finally:
        sys.setswitchinterval(old_interval)  # MUST 还原：时间片是进程全局态，会污染后续用例

    assert sys.getswitchinterval() == old_interval, "时间片未还原（会污染后续用例的时序假设）"
    assert not errors, f"并发失效缓存出现 {len(errors)} 个异常，样例：{[repr(e) for e in errors[:3]]}"
    syntax_hard._RANK_CACHE.clear()


def test_create_encounter_text_endpoint_invalidates_rank_cache(client):
    """POST /api/encounter/texts 成功后**立即**失效聚合榜缓存（走真实端点，非直接调 db 层）。

    这条钉的是 encounter 侧的写入点：`api_create_text` 必须在 create_encounter_text 事务
    提交**之后**调一次 invalidate_rank_cache()。测试用真实 HTTP 端点而不是直接调
    database.create_encounter_text，正是为了覆盖"路由层调了失效入口"这一环——若只在
    存储层加失效，本用例会红。

    聚合 key TTL 是 300s：第一轮 sweep 把它写满后，第二轮必然命中旧榜 ⇒ 新短文 id
    不在其中；只有写入点真的失效了，重聚合才会带上新 id。
    """
    syntax_hard._RANK_CACHE.clear()
    seed_id = _seed_encounter()  # 前置材料：先把聚合 key 填上
    # init_db 会预置 4 篇示例文章 ⇒ source=all 里混有 article id，故只取 encounter 项比较；
    # 且 sweep 是**逐句**返回（同 id 多次出现）⇒ 还要去重。
    assert _enc_ids_in_all(client) == {seed_id}, "前置条件：第一轮 encounter 应只有 seed 一篇"

    # 真实端点新建短文（挂本机闸，client 已是 127.0.0.1）。事务在路由内提交后失效聚合榜。
    res = client.post(
        "/api/encounter/texts",
        json={
            "title": "Im Café",
            "level": "A2",
            "source": "test",
            "content": "Der Kaffee ist heiß. Ich trinke ihn langsam. Danach gehe ich nach Hause.",
        },
    )
    assert res.status_code == 201, f"新建短文应 201，实际 {res.status_code}：{res.text}"
    new_id = res.json()["id"]

    ids = _enc_ids_in_all(client)
    assert new_id in ids, (
        f"新建短文 id={new_id} 未出现在难度榜，实际 {sorted(ids)}：写入点未失效聚合缓存"
        f"（新短文静默缺席，最长 300s）"
    )
    assert seed_id in ids, f"既有短文 id={seed_id} 不应被误清，实际 {sorted(ids)}"
    syntax_hard._RANK_CACHE.clear()


# ── 整包导入侧的两个写入点（Task 1 最后一个缺口）──────────────────────────────
# 缺口：_list_encounter_ids 查的是**全表** encounter_texts，而 import_encounter_pack
# 落库的预置短文同样进难度榜 ⇒ import-pack / pull-pack 两处路由若不失效聚合 key，
# 整包导入的短文会静默缺席难度榜最长 300s。
# 造 pack 依据：encounter.py:87-98 validate_pack（schema / pack_id / article.title /
# article.raw_text 四项必需，中文报错），等级归一在路由层（encounter.py:271-272
# estimated_cefr → A1/A2/B1 白名单，缺省 A2）。pack_json 的 analysis 段不参与
# 难度榜（只喂 texts/index 覆盖率），故此处不带，与 tests/test_encounter_pull.py:68
# 的 _fixture_pack 保持同一最小形状。

_PACK_RAW_TEXT = (
    "Guten Morgen! Ich heiße Ben und wohne in Köln. "
    "Obwohl es gestern stark geregnet hat, bin ich trotzdem spazieren gegangen."
)


def _pack_fixture(pack_id: str) -> Dict[str, Any]:
    """合法的 encounter-pack/v1 最小包（validate_pack 四项必需键齐备）。"""
    return {
        "schema": encounter_mod.CARD_PACK_SCHEMA,
        "pack_id": pack_id,
        "source": {"kind": "job1"},
        "article": {"title": "Ein Tag im Park", "raw_text": _PACK_RAW_TEXT},
        "estimated_cefr": "A2",
    }


def test_import_pack_endpoint_invalidates_rank_cache(client):
    """POST /api/encounter/import-pack 成功后**立即**失效聚合榜缓存（走真实端点）。

    与 test_create_encounter_text_endpoint_invalidates_rank_cache 同理：整包导入是
    encounter 侧的另一条写入路径，若只在存储层加失效或干脆漏加，本用例会红。
    """
    syntax_hard._RANK_CACHE.clear()
    seed_id = _seed_encounter()  # 前置材料：先把聚合 key 写满
    assert _enc_ids_in_all(client) == {seed_id}, "前置条件：第一轮 encounter 应只有 seed 一篇"

    res = client.post("/api/encounter/import-pack", json={"pack": _pack_fixture("t1-import-pack")})
    assert res.status_code == 200, f"整包导入应 200，实际 {res.status_code}：{res.text}"
    new_id = res.json()["id"]

    ids = _enc_ids_in_all(client)
    assert new_id in ids, (
        f"导入包短文 id={new_id} 未出现在难度榜，实际 {sorted(ids)}："
        f"import-pack 写入点未失效聚合缓存（整包导入的短文静默缺席，最长 300s）"
    )
    assert seed_id in ids, f"既有短文 id={seed_id} 不应被误清，实际 {sorted(ids)}"
    syntax_hard._RANK_CACHE.clear()


def test_pull_pack_endpoint_invalidates_rank_cache(client, monkeypatch):
    """POST /api/encounter/pull-pack 成功后**立即**失效聚合榜缓存（走真实端点）。

    pull-pack 是手机端入站的第三条 encounter 写入路径（import_encounter_pack 同一个
    存储层函数），故 MUST 与 import-pack 同等失效。出站 httpx.get 转调本用例的假货架，
    保持真实路由代码路径被执行（手法对齐 tests/test_encounter_pull.py:136-154）。
    """
    syntax_hard._RANK_CACHE.clear()
    seed_id = _seed_encounter()
    assert _enc_ids_in_all(client) == {seed_id}, "前置条件：第一轮 encounter 应只有 seed 一篇"

    shelf_pack = _pack_fixture("t1-pull-pack")

    class _Resp:  # 最小出站响应替身：_shelf_get 只读 status_code / json()
        status_code = 200

        def json(self) -> Dict[str, Any]:
            return shelf_pack

    monkeypatch.setattr(
        encounter_mod.httpx,
        "get",
        lambda url, *a, **kw: _Resp(),
    )

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://192.168.1.5:8000", "pack_id": "t1-pull-pack"},
    )
    assert res.status_code == 200, f"出站拉取应 200，实际 {res.status_code}：{res.text}"
    new_id = res.json()["id"]

    ids = _enc_ids_in_all(client)
    assert new_id in ids, (
        f"拉取包短文 id={new_id} 未出现在难度榜，实际 {sorted(ids)}："
        f"pull-pack 写入点未失效聚合缓存（拉取导入的短文静默缺席，最长 300s）"
    )
    assert seed_id in ids, f"既有短文 id={seed_id} 不应被误清，实际 {sorted(ids)}"
    syntax_hard._RANK_CACHE.clear()

