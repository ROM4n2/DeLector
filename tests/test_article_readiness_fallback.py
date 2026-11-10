# -*- coding: utf-8 -*-
"""文章详情「分词未就绪」快退的行为锁（2026-11-10 真机点验）。

真机现象：服务 listening 后立刻可进入阅读页，但详情首次 GET 会触发
``processed_json`` 惰性迁移，同步等 spaCy 模型加载（Android 上数十秒）；前端 fetch
超时后把「还没准备好」渲染成「加载失败」。

修法：模型仍 ``loading`` 时**不在请求里等** ——
- 有旧 ``sentences``：先返回旧结果，并打 ``processed_stale`` / ``nlp_state``；
- 没有可用旧结果：回 ``503 nlp_loading`` + ``Retry-After``，让前端显示「正在准备分词」
  并按退避重试。

本文件钉住这三条路径（就绪时不得误伤原有惰性迁移）。
"""

import gc
import json
import os
import sys
from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db_cleanup import remove_db_files  # noqa: E402

from delector import server  # noqa: E402
from delector.core.database import db_conn as real_db_conn  # noqa: E402
from delector.core.database import init_db  # noqa: E402
from delector.routes import articles as articles_route  # noqa: E402

RAW_TEXT = "Der Hund läuft schnell durch den Park und spielt mit einem Ball."


@pytest.fixture
def db_paths(tmp_path) -> Iterator[str]:
    db = str(tmp_path / "readiness.db")
    progress = str(tmp_path / "readiness_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = db
    os.environ["PROGRESS_DB_PATH"] = progress
    yield db
    gc.collect()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    remove_db_files(db, progress)


def _insert_article(db: str, processed_json: str) -> int:
    init_db(db)
    with real_db_conn(db) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            ("Readiness", RAW_TEXT, processed_json),
        )
        return int(cur.lastrowid or 0)


def _readiness(state: str) -> Dict[str, Any]:
    return {
        "state": state,
        "loaded": state == "ready",
        "model": "de_core_news_sm",
        "prewarm_started": True,
        "error": "",
    }


def test_detail_returns_503_when_nlp_loading_without_usable_payload(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型未就绪且没有可用旧结果 ⇒ 503 + Retry-After（可重试信号，不是 500）。"""
    aid = _insert_article(db_paths, "{}")
    monkeypatch.setattr(articles_route, "get_nlp_readiness", lambda: _readiness("loading"))
    client = TestClient(server.create_app(), client=("127.0.0.1", 54321))

    res = client.get(f"/api/articles/{aid}")

    assert res.status_code == 503, f"未就绪应回 503，实际 {res.status_code}：{res.text[:200]}"
    assert res.json()["detail"] == "nlp_loading", f"503 应带可判定的 detail，实际 {res.text[:200]}"
    assert res.headers.get("retry-after") == "2", "503 必须给 Retry-After，前端才能退避重试"


def test_detail_returns_stale_payload_when_nlp_loading_with_old_sentences(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型未就绪但有旧 sentences ⇒ 先给旧结果 + 打标，绝不把用户挡在错误页。"""
    old_payload = json.dumps(
        {
            "version": "1.0.0",
            "stats": {"word_count": 2, "cefr_counts": {"A1": 2}},
            "sentences": [{"id": 1, "tokens": []}],
        }
    )
    aid = _insert_article(db_paths, old_payload)
    monkeypatch.setattr(articles_route, "get_nlp_readiness", lambda: _readiness("loading"))
    client = TestClient(server.create_app(), client=("127.0.0.1", 54321))

    res = client.get(f"/api/articles/{aid}")

    assert res.status_code == 200, f"有旧结果时应先返回 200，实际 {res.status_code}：{res.text[:200]}"
    body = res.json()
    assert body["processed_stale"] is True, "旧结果必须显式打标，前端才能提示「分词正在升级」"
    assert body["nlp_state"] == "loading", f"应回传 nlp_state=loading，实际 {body.get('nlp_state')!r}"
    assert body["sentences"] == [{"id": 1, "tokens": []}], "旧 sentences 必须原样返回"
    assert "processed_json" not in body, "响应不得回传原始序列化列（与既有去重契约一致）"


def test_detail_still_migrates_when_nlp_ready(
    db_paths: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型就绪时快退不得触发：仍走原惰性迁移路径（不能把正常路径堵死）。"""
    aid = _insert_article(db_paths, "{}")
    monkeypatch.setattr(articles_route, "get_nlp_readiness", lambda: _readiness("ready"))
    migrated: Dict[str, Any] = {
        "version": "test",
        "stats": {"word_count": 9},
        "sentences": [{"id": 7, "tokens": []}],
    }
    monkeypatch.setattr(articles_route, "process_german_text", lambda _text: dict(migrated))
    client = TestClient(server.create_app(), client=("127.0.0.1", 54321))

    res = client.get(f"/api/articles/{aid}")

    assert res.status_code == 200, f"就绪时应正常迁移并返回 200，实际 {res.status_code}：{res.text[:200]}"
    body = res.json()
    assert body["stats"]["word_count"] == 9, f"迁移结果应回传，实际 {body.get('stats')!r}"
    assert not body.get("processed_stale"), "正常迁移路径不得带 processed_stale 标记"
