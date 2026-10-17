# 本文件含「正常模式需要、--follow-imports=skip 下 unused」的动态面 type: ignore
# （BaseRoute 静态无 endpoint/path、运行时必为 APIRoute 的动态访问）——门禁用
# `mypy --follow-imports=skip tests` 跑，skip 下 fastapi 降 Any 使这些 ignore 变
# unused，故文件级豁免 unused-ignore（其它错误码仍全查）。
# mypy: disable-error-code="unused-ignore"
import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import re
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

# 夹具与打包 helper 自 tests/server_helpers.py 上收（C6 Task 3）。夹具用 `as 同名` 显式再导出
# 写法：pyflakes 据此不判「导入未用」（夹具由 pytest 按名解析，静态看不见使用）。
from server_helpers import ROOT, _calls_named, _insert_vocab_card, _package_windows_build_windows_fn
from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client
from server_helpers import test_db_path as test_db_path
from starlette.responses import StreamingResponse

# 模块对象本身：几条测试要断言 server 里的私有常量/函数（`_is_blocked_addr`、
# 钉住的 IPv6 段），故 import 模块对象而非仅具名导入。
# 不再需要"先设好 DATABASE_PATH 再 import"：库 env 由根 conftest 的 setdefault 兜底，
# 并由各模块 autouse fixture（本文件：clean_db，C6 Task 3 起自 server_helpers 导入）在
# 用例前后钉定；本模块不再在模块级赋值
# （契约 C1，见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1）。
from delector import server
from delector.core.database import db_conn, db_progress_conn
from delector.routes.main import AIPolishReq, _polish_event_stream, api_writing_ai_polish
from delector.server import (
    SYSTEM_GRAMMAR_PROMPT,
    app,
    clean_html_to_article,
    get_cefr_level,
    init_db,
    is_safe_public_url,
    process_german_text,
    set_setting,
)
from delector.services import polish_loop


@pytest.fixture
def test_progress_path():
    return "test_progress.db"


def test_cefr_lookup():
    assert get_cefr_level("gehen") == "A1"
    assert get_cefr_level("beeinträchtigen") in ("B2", "C1")


def test_grammar_cards_migration_adds_columns():
    import sqlite3

    conn = sqlite3.connect("test_delector.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(grammar_cards)")}
    assert "corrected_form" in cols and "error_type" in cols, f"缺列: {cols}"


def test_essays_table_created():
    import sqlite3

    conn = sqlite3.connect("test_delector.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(essays)")}
    assert {"id", "title", "content", "analysis_json", "cefr_level", "error_count", "created_at"} <= cols


def test_writing_analyze_endpoint(client):
    res = client.post("/api/writing/analyze", json={"text": "Ich sehe der Mann."})
    assert res.status_code == 200
    a = res.json()
    assert "sentences" in a and len(a["sentences"]) > 0 and a["sentences"][0]["spans"]


def test_essays_crud_flow(client):
    r = client.post("/api/essays", json={"title": "Mein Essay", "content": "Ich fahre mit der Auto."})
    assert r.status_code == 200
    eid = r.json()["id"]
    assert r.json()["error_count"] >= 1
    assert len(client.get("/api/essays").json()) >= 1
    g = client.get(f"/api/essays/{eid}").json()
    assert g["analysis_json"]
    u = client.put(f"/api/essays/{eid}", json={"content": "Ich fahre mit dem Auto."})
    assert u.status_code == 200
    assert u.json()["error_count"] == 0
    assert client.delete(f"/api/essays/{eid}").status_code == 200


def test_writing_card_sugar_endpoint(client):
    r = client.post("/api/essays", json={"title": "T", "content": "Ich sehe der Mann."})
    assert r.status_code == 200
    eid = r.json()["id"]
    a = r.json()["analysis_json"]
    span = a["sentences"][0]["spans"][0]
    res = client.post("/api/writing/cards", json={"essay_id": eid, "sentence_id": 0, "span_index": 0})
    assert res.status_code == 200
    cards_data = client.get("/api/cards").json()
    g_cards = cards_data.get("grammar_cards", [])
    assert g_cards and g_cards[0].get("corrected_form") == span["corrected_form"]
    assert g_cards[0].get("error_type") == span["error_type"]


def test_ai_polish_no_key_stub(client, monkeypatch):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["result"]["error_count"] == 0
    assert data["result"]["corrected_text"] == "Hallo."


def test_ai_polish_diff_no_key_stub(client, monkeypatch):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish/diff", json={"text": "Ich habe ein Hund. Er ist gut."})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    result = data["result"]
    assert result["original"] == "Ich habe ein Hund. Er ist gut."
    assert result["corrected"] == "Ich habe ein Hund. Er ist gut."
    assert result["hunks"] == []
    assert result["error_count"] == 0
    assert "DeepSeek API Key" in result["notes_zh"][0]


def test_ai_polish_diff_mocked(client, monkeypatch):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "test-api-key")

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "corrected_text": "Ich habe einen Hund. Er ist gut. Ich liebe ihn.",
                            "notes_zh": [
                                "ein -> einen: Akkusativ maskulin",
                                "Ich liebe ihn: Ergänzung zur Vollständigkeit",
                            ],
                            "error_count": 2,
                        }
                    )
                }
            }
        ]
    }

    class _MockResponse:
        def json(self):
            return mock_response_payload

    class _MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return _MockResponse()

    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", _MockAsyncClient)

    orig_text = "Ich habe ein Hund. Er ist gut."
    res = client.post("/api/writing/ai-polish/diff", json={"text": orig_text})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    result = data["result"]
    assert result["original"] == orig_text
    assert result["corrected"] == "Ich habe einen Hund. Er ist gut. Ich liebe ihn."
    assert result["error_count"] == 2
    assert len(result["notes_zh"]) == 2

    hunks = result["hunks"]
    assert len(hunks) == 2
    assert hunks[0]["old"] == ["Ich habe ein Hund."]
    assert hunks[0]["new"] == ["Ich habe einen Hund."]
    assert hunks[0]["accepted"] is True

    assert hunks[1]["old"] == []
    assert hunks[1]["new"] == ["Ich liebe ihn."]
    assert hunks[1]["accepted"] is True


def test_essay_versions_table_and_seed_migration(client, test_db_path):
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(essay_versions)")}
    assert {"id", "essay_id", "content", "analysis_json", "message", "created_at"} <= cols

    indices = [r[1] for r in conn.execute("PRAGMA index_list(essay_versions)")]
    assert "idx_essay_versions_essay_id" in indices

    # Seed migration test: insert an essay without versions, then re-run init_db
    conn.execute(
        "INSERT INTO essays (title, content, analysis_json, cefr_level, error_count) VALUES (?, ?, ?, ?, ?)",
        ("Old Essay", "Ich habe ein Hund.", '{"error_count": 1}', "A2", 1),
    )
    conn.commit()
    old_essay_id = conn.execute("SELECT id FROM essays WHERE title = 'Old Essay'").fetchone()[0]
    conn.close()

    # Re-run init_db
    init_db(test_db_path)

    conn = sqlite3.connect(test_db_path)
    versions = conn.execute(
        "SELECT essay_id, message FROM essay_versions WHERE essay_id = ?", (old_essay_id,)
    ).fetchall()
    assert len(versions) == 1
    assert versions[0][1] == "初始快照"

    # Running init_db again is idempotent (no duplicate seed)
    init_db(test_db_path)
    versions_after = conn.execute(
        "SELECT essay_id, message FROM essay_versions WHERE essay_id = ?", (old_essay_id,)
    ).fetchall()
    assert len(versions_after) == 1
    conn.close()


def test_essay_versions_crud_and_restore(client):
    # 1. Create essay
    r = client.post("/api/essays", json={"title": "Version Essay", "content": "Ich sehe der Mann."})
    assert r.status_code == 200
    eid = r.json()["id"]

    # 2. List versions initially empty
    v_list = client.get(f"/api/essays/{eid}/versions").json()
    assert isinstance(v_list, list)

    # 3. Manual save version 1
    s1 = client.post(f"/api/essays/{eid}/versions", json={"message": "v1手动保存"})
    assert s1.status_code == 200
    v1_id = s1.json()["version_id"]
    assert s1.json()["message"] == "v1手动保存"
    assert "created_at" in s1.json()

    # Save with default message
    s_def = client.post(f"/api/essays/{eid}/versions", json={})
    assert s_def.status_code == 200
    assert s_def.json()["message"] == "手动保存"

    # 4. List versions (ordered by id DESC)
    v_list = client.get(f"/api/essays/{eid}/versions").json()
    assert len(v_list) >= 2
    assert v_list[0]["id"] == s_def.json()["version_id"]
    assert v_list[1]["id"] == v1_id
    assert "error_count" in v_list[0]

    # 5. Non-existent essay 404
    assert client.get("/api/essays/99999/versions").status_code == 404
    assert client.post("/api/essays/99999/versions", json={"message": "test"}).status_code == 404
    assert client.post("/api/essays/99999/restore", json={"version_id": 1}).status_code == 404

    # 6. Non-existent version 404
    assert client.post(f"/api/essays/{eid}/restore", json={"version_id": 99999}).status_code == 404

    # 7. Update essay content to content B
    client.put(f"/api/essays/{eid}", json={"content": "Ich sehe den Mann. Er ist nett."})

    # 8. Restore to version 1 (which had "Ich sehe der Mann.")
    # Content differs, so a checkpoint version is created before restoring
    res_restore = client.post(f"/api/essays/{eid}/restore", json={"version_id": v1_id})
    assert res_restore.status_code == 200
    restore_data = res_restore.json()
    assert restore_data["content"] == "Ich sehe der Mann."
    assert restore_data["checkpoint_version_id"] is not None

    # Check versions list: should contain checkpoint "恢复到版本 {v1_id} 之前"
    v_list2 = client.get(f"/api/essays/{eid}/versions").json()
    assert any(f"恢复到版本 {v1_id} 之前" in v["message"] for v in v_list2)

    # 9. Restore again when identical: checkpoint is skipped (None)
    res_restore_again = client.post(f"/api/essays/{eid}/restore", json={"version_id": v1_id})
    assert res_restore_again.status_code == 200
    assert res_restore_again.json()["checkpoint_version_id"] is None
    assert res_restore_again.json()["content"] == "Ich sehe der Mann."


def test_essay_version_preview_read_only(client):
    r = client.post("/api/essays", json={"title": "Preview Essay", "content": "Ich gehe in das Kino."})
    eid = r.json()["id"]

    s1 = client.post(f"/api/essays/{eid}/versions", json={"message": "v1 preview test"})
    v1_id = s1.json()["version_id"]

    # 404 guards
    assert client.get(f"/api/essays/99999/versions/{v1_id}").status_code == 404
    assert client.get(f"/api/essays/{eid}/versions/99999").status_code == 404

    # Preview version
    pv = client.get(f"/api/essays/{eid}/versions/{v1_id}")
    assert pv.status_code == 200
    data = pv.json()
    assert data["id"] == v1_id
    assert data["essay_id"] == eid
    assert data["message"] == "v1 preview test"
    assert data["content"] == "Ich gehe in das Kino."
    assert "analysis_json" in data
    assert "error_count" in data

    # Verify read-only: version count unchanged, essay content unchanged
    v_list = client.get(f"/api/essays/{eid}/versions").json()
    assert len(v_list) == 1
    essay_data = client.get(f"/api/essays/{eid}").json()
    assert essay_data["content"] == "Ich gehe in das Kino."


def test_essay_version_delete(client):
    r = client.post("/api/essays", json={"title": "Delete Version Essay", "content": "Das ist ein Haus."})
    eid = r.json()["id"]

    s1 = client.post(f"/api/essays/{eid}/versions", json={"message": "v1 to delete"})
    v1_id = s1.json()["version_id"]
    s2 = client.post(f"/api/essays/{eid}/versions", json={"message": "v2 to keep"})
    v2_id = s2.json()["version_id"]

    # 404 guards
    assert client.delete(f"/api/essays/99999/versions/{v1_id}").status_code == 404
    assert client.delete(f"/api/essays/{eid}/versions/99999").status_code == 404

    # Delete v1
    del_r = client.delete(f"/api/essays/{eid}/versions/{v1_id}")
    assert del_r.status_code == 200
    assert del_r.json() == {"status": "ok", "deleted_version_id": v1_id}

    # Verify v1 is gone from list, v2 remains
    v_list = client.get(f"/api/essays/{eid}/versions").json()
    v_ids = [v["id"] for v in v_list]
    assert v1_id not in v_ids
    assert v2_id in v_ids

    # Repeated delete gives 404
    assert client.delete(f"/api/essays/{eid}/versions/{v1_id}").status_code == 404

    # Essay content untouched
    essay_data = client.get(f"/api/essays/{eid}").json()
    assert essay_data["content"] == "Das ist ein Haus."


def test_writing_apply_partial_and_full_accept(client):
    orig = "Ich habe ein Hund. Er ist gut."
    corr = "Ich habe einen Hund. Er ist gut. Ich liebe ihn."
    # 1. Create essay
    r = client.post("/api/essays", json={"title": "Diff Apply Essay", "content": orig})
    assert r.status_code == 200
    eid = r.json()["id"]

    # 2. Out of bounds index returns 400
    r_oob = client.post(
        "/api/writing/apply",
        json={"essay_id": eid, "original_text": orig, "corrected_text": corr, "accepted_indices": [-1]},
    )
    assert r_oob.status_code == 400

    r_oob2 = client.post(
        "/api/writing/apply",
        json={"essay_id": eid, "original_text": orig, "corrected_text": corr, "accepted_indices": [99]},
    )
    assert r_oob2.status_code == 400

    # 3. Non-existent essay returns 404
    r_404 = client.post(
        "/api/writing/apply",
        json={"essay_id": 99999, "original_text": orig, "corrected_text": corr, "accepted_indices": [0]},
    )
    assert r_404.status_code == 404

    # 4. Partial accept (accept hunk 0 out of 2)
    # Hunk 0: "Ich habe ein Hund." -> "Ich habe einen Hund."
    # Hunk 1: "" -> "Ich liebe ihn." (rejected)
    r_apply = client.post(
        "/api/writing/apply",
        json={"essay_id": eid, "original_text": orig, "corrected_text": corr, "accepted_indices": [0]},
    )
    assert r_apply.status_code == 200
    apply_data = r_apply.json()
    assert apply_data["content"] == "Ich habe einen Hund. Er ist gut."
    assert apply_data["version_id"] is not None
    assert "error_count" in apply_data

    # Check essay was updated in DB
    essay_get = client.get(f"/api/essays/{eid}").json()
    assert essay_get["content"] == "Ich habe einen Hund. Er ist gut."

    # Check auto-created version
    v_list = client.get(f"/api/essays/{eid}/versions").json()
    assert len(v_list) == 1
    assert v_list[0]["message"] == "AI 润色 · 接受 1/2 处"

    # 5. Full reject (accepted_indices = [])
    # Content remains unchanged, version_id is None, no new version added
    r_reject = client.post(
        "/api/writing/apply",
        json={
            "essay_id": eid,
            "original_text": "Ich habe einen Hund. Er ist gut.",
            "corrected_text": corr,
            "accepted_indices": [],
        },
    )
    assert r_reject.status_code == 200
    reject_data = r_reject.json()
    assert reject_data["content"] == "Ich habe einen Hund. Er ist gut."
    assert reject_data["version_id"] is None

    # Version count should still be 1
    v_list_after = client.get(f"/api/essays/{eid}/versions").json()
    assert len(v_list_after) == 1


def test_delete_essay_cascades_versions(client, test_db_path):
    import sqlite3

    r = client.post("/api/essays", json={"title": "Cascade Essay", "content": "Ich trinke Kaffee."})
    assert r.status_code == 200
    eid = r.json()["id"]

    # Save 2 versions
    client.post(f"/api/essays/{eid}/versions", json={"message": "v1"})
    client.post(f"/api/essays/{eid}/versions", json={"message": "v2"})

    conn = sqlite3.connect(test_db_path)
    count = conn.execute("SELECT COUNT(*) FROM essay_versions WHERE essay_id = ?", (eid,)).fetchone()[0]
    assert count == 2
    conn.close()

    # Delete essay
    del_r = client.delete(f"/api/essays/{eid}")
    assert del_r.status_code == 200

    conn = sqlite3.connect(test_db_path)
    count_after = conn.execute("SELECT COUNT(*) FROM essay_versions WHERE essay_id = ?", (eid,)).fetchone()[0]
    assert count_after == 0
    conn.close()


def test_seed_preset_articles_with_a1(client, test_db_path):
    init_db(test_db_path)

    with db_conn(test_db_path) as conn:
        rows = conn.execute("SELECT title, raw_text FROM articles").fetchall()
        assert len(rows) >= 4
        titles = [r["title"] for r in rows]
        assert any("A1" in t for t in titles)
        assert any("A2" in t for t in titles)
        assert any("B1" in t for t in titles)


def test_a1_grammar_prompt_coverage():
    assert "A1" in SYSTEM_GRAMMAR_PROMPT
    assert "变位" in SYSTEM_GRAMMAR_PROMPT or "格" in SYSTEM_GRAMMAR_PROMPT


def test_cefr_text_difficulty_stats(client):
    # 1. Direct process_german_text check
    a1_text = "Hallo! Ich heiße Lukas. Ich lerne Deutsch und trinke Kaffee."
    res_a1 = process_german_text(a1_text)
    assert "stats" in res_a1
    assert res_a1["stats"]["word_count"] > 0
    assert res_a1["stats"]["recommended_level"] == "A1"
    assert res_a1["stats"]["cefr_percentages"]["A1"] > 60.0
    assert res_a1["stats"]["est_reading_minutes"] >= 1

    # 2. List articles API returns stats
    res = client.get("/api/articles")
    assert res.status_code == 200
    articles = res.json()
    assert len(articles) > 0
    assert "stats" in articles[0]
    assert "cefr_percentages" in articles[0]["stats"]


def test_full_api_flow(client):
    # 1. Ingest text
    text = "Nachdem er die Prüfung bestanden hatte, fuhr er nach Berlin."
    res = client.post("/api/articles/ingest", json={"title": "Test Goethe", "raw_text": text})
    assert res.status_code == 200
    art_id = res.json()["article_id"]

    # 2. Get article with tokens
    res = client.get(f"/api/articles/{art_id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["sentences"]) > 0
    words = [t["text"] for t in data["sentences"][0]["tokens"]]
    assert "Prüfung" in words

    # 3. Add vocab card
    v_res = client.post(
        "/api/cards/vocab",
        json={
            "article_id": art_id,
            "word": "Prüfung",
            "lemma": "Prüfung",
            "pos": "NOUN",
            "gender": "Fem",
            "cefr_level": "A2",
            "definition_zh": "考试",
            "sentence_context": text,
        },
    )
    assert v_res.status_code == 200

    # 4. Add grammar card
    g_res = client.post(
        "/api/cards/grammar",
        json={
            "article_id": art_id,
            "sentence_context": text,
            "grammar_name": "Plusquamperfekt mit nachdem",
            "cefr_level": "B1",
            "explanation_zh": "过去完成时表示过去发生之前的动作",
            "rule_formula": "nachdem + Partizip II + hatte/war",
        },
    )
    assert g_res.status_code == 200

    # 5. Export APKG
    apkg_res = client.get("/api/cards/export/apkg")
    assert apkg_res.status_code == 200
    assert len(apkg_res.content) > 1000


def test_is_safe_public_url_filters_private_ips(monkeypatch):
    # 这几条走字面 IP，不碰 DNS。
    assert is_safe_public_url("http://127.0.0.1:8000/api") is False
    assert is_safe_public_url("http://localhost:3000") is False
    assert is_safe_public_url("http://192.168.1.1/admin") is False
    assert is_safe_public_url("http://10.0.0.5/") is False
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("ftp://example.com/file") is False

    # 放行那条必须钉住解析结果：真去问 DNS 的话，本机开着 Teredo 隧道时
    # tagesschau.de 会解析出 2001::/32 里的地址，同一份代码时红时绿。
    import socket as _socket

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("23.55.108.51", 443)),
        ],
    )
    assert is_safe_public_url("https://www.tagesschau.de/inland/test") is True


def test_clean_html_to_article():
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Klimawandel in den Alpen – DER SPIEGEL</title></head>
    <body>
      <nav><a href="/">Home</a></nav>
      <script>console.log("ad");</script>
      <p>Die Temperaturen in den Alpen steigen doppelt so schnell wie im globalen Durchschnitt.</p>
      <p>Forscher warnen vor gravierenden Folgen für das Ökosystem und den Tourismus der Region.</p>
      <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    title, body = clean_html_to_article(mock_html)
    assert "Klimawandel in den Alpen" in title
    assert "DER SPIEGEL" not in title
    assert "Temperaturen in den Alpen" in body
    assert "Copyright" not in body


def test_url_ingest_endpoint_with_mock(client, monkeypatch):
    from unittest.mock import AsyncMock

    mock_html = (
        "<html><head><title>Hallo Berlin</title></head><body>"
        "<p>Ich lebe seit zwei Jahren in Berlin und lerne jeden Tag Deutsch.</p></body></html>"
    )
    monkeypatch.setattr("delector.routes.main.fetch_remote_html", AsyncMock(return_value=mock_html))
    # 端点自己也过一次 SSRF 闸（server.py:858），而 fetch 被 mock 掉不代表闸被 mock 掉。
    # 不钉住这里就等于让这条测试依赖真实 DNS：本机开着 Teredo 时 dw.com 会带出
    # 2001::/32 的地址，闸门拒绝，测试变成时红时绿；CI 的 Linux runner 无 Teredo 一直绿。
    monkeypatch.setattr("delector.routes.main.is_safe_public_url", lambda u: True)

    res = client.post("/api/articles/ingest-url", json={"url": "https://www.dw.com/de/hallo-berlin/a-123"})
    assert res.status_code == 200
    data = res.json()
    assert data["article_id"] > 0
    assert "stats" in data


def test_backup_export_and_restore_roundtrip(client):
    # 1. Export current backup
    res = client.get("/api/backup/export")
    assert res.status_code == 200
    data = res.json()
    assert "version" in data
    assert "articles" in data
    assert "vocab_cards" in data
    assert "grammar_cards" in data

    # 2. Modify or add custom entry
    custom_backup = {
        "version": 1,
        "articles": [
            {
                "id": 999,
                "title": "Backup Test Article",
                "raw_text": "Ein Test für Backup.",
                "processed_json": "{}",
                "source_url": "https://example.com/backup",
                "created_at": "2026-08-18 12:00:00",
            }
        ],
        "vocab_cards": [
            {
                "id": 999,
                "article_id": 999,
                "word": "Test",
                "lemma": "Test",
                "pos": "NOUN",
                "gender": "Masc",
                "cefr_level": "A1",
                "definition_zh": "测试",
                "sentence_context": "Ein Test.",
                "plural": "Tests",
                "created_at": "2026-08-18 12:00:00",
            }
        ],
        "grammar_cards": [
            {
                "id": 999,
                "article_id": 999,
                "sentence_context": "Ein Test.",
                "grammar_name": "Nomen",
                "cefr_level": "A1",
                "explanation_zh": "名词",
                "rule_formula": "Pattern",
                "examples_zh": "例子",
                "created_at": "2026-08-18 12:00:00",
            }
        ],
    }

    # 3. Restore custom backup
    res_restore = client.post("/api/backup/restore", json=custom_backup)
    assert res_restore.status_code == 200

    # 4. Verify roundtrip integrity
    res_verify = client.get("/api/articles/999")
    assert res_verify.status_code == 200
    assert res_verify.json()["title"] == "Backup Test Article"


def test_backup_restore_covers_encounter_texts(client):
    """vault-team 评审 ②：备份/还原必须覆盖遇见区短文表（encounter_texts）——
    缺失时"看着还原成功"，换机后遇见区却全空。

    变异探针：造一篇 → 导出（含 encounter_texts）→ 把目标库该表删空（模拟
    还原前数据丢失）→ 全量 restore → 遇见区文本必须回来。
    """
    import sqlite3

    # 1) 造一篇（走本机闸 POST /api/encounter/texts）。
    r = client.post(
        "/api/encounter/texts",
        json={
            "title": "Mein erstes U-Bahn-Abenteuer",
            "level": "A2",
            "source": "手工",
            "content": "Ich fahre zum ersten Mal mit der U-Bahn.",
        },
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # 2) 导出应含 encounter_texts 且带着这篇。
    res = client.get("/api/backup/export")
    assert res.status_code == 200
    data = res.json()
    assert "encounter_texts" in data
    assert any(x.get("id") == tid for x in data["encounter_texts"])

    # 3) 目标库删光该表行（模拟还原前数据丢失/被清）。
    conn = sqlite3.connect("test_delector.db")
    conn.execute("DELETE FROM encounter_texts")
    conn.commit()
    conn.close()
    assert client.get("/api/encounter/texts").json()["texts"] == []

    # 4) 全量还原 → 遇见区文本回来。
    rr = client.post("/api/backup/restore", json=data)
    assert rr.status_code == 200, rr.text
    titles = [t["title"] for t in client.get("/api/encounter/texts").json()["texts"]]
    assert any("U-Bahn" in t for t in titles), f"还原后遇见区应恢复短文，实际: {titles}"


def test_audio_tts_endpoint_with_mock(client, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    fake_mp3 = tmp_path / "fake_de.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00mock_audio_data")

    monkeypatch.setattr("delector.routes.main.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))

    res = client.post("/api/audio/tts", json={"text": "Hallo Berlin!", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert len(res.content) > 10


def test_tts_falls_back_to_stdlib_mini_client_when_edge_tts_missing(client, monkeypatch, tmp_path):
    """安卓 APK 没有 edge_tts wheel → generate_edge_tts_audio 走 edge_tts_mini 客户端。

    模拟 Chaquopy 环境：import edge_tts 抛 ImportError，edge_tts_mini.synthesize 返回假 MP3。
    """
    import asyncio
    import sys
    import types

    from delector.routes import main as routes_main

    # 1. 堵死 edge_tts 导入（模拟安卓）：sys.modules[name]=None 时 import 抛 ImportError
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    # 2. 用假模块顶替 services.tts，synthesize 返回假 MP3
    fake_mini = types.ModuleType("delector.services.tts")
    fake_mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x00mock_edge_mini_audio"
    fake_mini.synthesize = lambda text, voice, rate: fake_mp3  # type: ignore[attr-defined]  # 构造假模块顶替 sys.modules，刻意在 ModuleType 上动态挂属性
    # routes/main.py 的 generate_edge_tts_audio 延迟导入写的是
    # `from delector.services import tts as edge_tts_mini`，找的是
    # sys.modules["delector.services.tts"] —— 顶替该键生效。
    monkeypatch.setitem(sys.modules, "delector.services.tts", fake_mini)
    # 双保险：前面若已有测试触发过真 tts 的延迟导入，包对象上会缓存
    # 真模块属性，`from delector.services import tts` 命中包属性而不查 sys.modules。
    # 顶替包属性，消除「单独跑绿、整批红」的顺序依赖。
    import delector.services

    monkeypatch.setattr(delector.services, "tts", fake_mini, raising=False)

    # 3. 独立缓存目录，避免污染
    cache_dir = tmp_path / "mini_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(routes_main, "AUDIO_CACHE_DIR", str(cache_dir))

    path = asyncio.run(routes_main.generate_edge_tts_audio("Wie geht es dir?", "de-DE-KatjaNeural", "+0%"))
    with open(path, "rb") as f:
        assert f.read() == fake_mp3


def test_reading_notes_crud_and_export(client):
    # 1. Ingest article
    res_art = client.post(
        "/api/articles/ingest", json={"title": "Notizen Test", "raw_text": "Berlin ist wunderbar und groß."}
    )
    art_id = res_art.json()["article_id"]

    # 2. Create reading note
    res_note = client.post(
        f"/api/articles/{art_id}/notes",
        json={
            "sentence_id": 1,
            "selected_text": "wunderbar",
            "color": "yellow",
            "note_content": "形容词：精彩的、极好的",
        },
    )
    assert res_note.status_code == 200
    note_id = res_note.json()["id"]

    # 3. List notes
    res_list = client.get(f"/api/articles/{art_id}/notes")
    assert res_list.status_code == 200
    notes = res_list.json()
    assert len(notes) == 1
    assert notes[0]["selected_text"] == "wunderbar"

    # 4. Export study guide markdown
    res_guide = client.get(f"/api/articles/{art_id}/export-guide")
    assert res_guide.status_code == 200
    assert "Notizen Test" in res_guide.text
    assert "wunderbar" in res_guide.text
    assert "形容词：精彩的、极好的" in res_guide.text

    # 5. Delete note
    res_del = client.delete(f"/api/notes/{note_id}")
    assert res_del.status_code == 200
    res_list2 = client.get(f"/api/articles/{art_id}/notes")
    assert len(res_list2.json()) == 0


def test_audio_cache_stats_and_clear(client, monkeypatch, tmp_path):
    # Mock AUDIO_CACHE_DIR to temporary directory
    cache_dir = tmp_path / "audio_cache"
    cache_dir.mkdir()
    (cache_dir / "sample1.mp3").write_bytes(b"x" * 1024 * 50)  # 50 KB
    (cache_dir / "sample2.mp3").write_bytes(b"x" * 1024 * 50)  # 50 KB

    monkeypatch.setattr("delector.routes.main.AUDIO_CACHE_DIR", str(cache_dir))

    # 1. Get cache stats
    res_stats = client.get("/api/audio/cache")
    assert res_stats.status_code == 200
    data = res_stats.json()
    assert data["file_count"] == 2
    assert data["total_size_bytes"] == 1024 * 100

    # 2. Clear cache
    res_clear = client.post("/api/audio/cache/clear")
    assert res_clear.status_code == 200
    assert res_clear.json()["cleared_count"] == 2

    # 3. Verify empty
    res_stats2 = client.get("/api/audio/cache")
    assert res_stats2.json()["file_count"] == 0


def test_audio_cache_clear_reports_removal_failures(client, monkeypatch, tmp_path):
    """删除失败的条目不得被静默吞掉：响应必须报出失败计数与文件名。

    旧实现 `except Exception: pass` 会让「文件被别的进程锁住」这类失败在响应里
    完全隐形——用户看到 cleared_count=1，却不知道还有一个 50KB 的条目删不掉。
    """
    cache_dir = tmp_path / "audio_cache"
    cache_dir.mkdir()
    (cache_dir / "ok.mp3").write_bytes(b"x" * 1024 * 50)
    (cache_dir / "locked.mp3").write_bytes(b"x" * 1024 * 50)
    monkeypatch.setattr("delector.routes.main.AUDIO_CACHE_DIR", str(cache_dir))

    real_remove = os.remove

    def flaky_remove(path):
        if os.path.basename(path) == "locked.mp3":
            raise PermissionError("locked by another process")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)

    res = client.post("/api/audio/cache/clear")
    assert res.status_code == 200
    data = res.json()
    assert data["cleared_count"] == 1
    assert data["failed_count"] == 1
    assert data["failed_files"] == ["locked.mp3"]
    # 删不掉的条目必须真的留在盘上（不能是「删了却报失败」）
    assert (cache_dir / "locked.mp3").exists()
    assert not (cache_dir / "ok.mp3").exists()


def test_audio_cache_clear_freed_mb_is_true_delta(client, monkeypatch, tmp_path):
    """freed_mb 必须是「清理前 − 清理后」的真实差值，而不是清理前的静态总量。

    构造一个删不掉的 1MB 文件：真实只释放 1.0MB，而旧实现会报清理前总量 2.0MB。
    差值口径下必须是 1.0——这同时证明失败路径的占用没被虚报成已释放。
    """
    cache_dir = tmp_path / "audio_cache"
    cache_dir.mkdir()
    (cache_dir / "gone.mp3").write_bytes(b"x" * 1024 * 1024)  # 1 MB，将成功删除
    (cache_dir / "locked.mp3").write_bytes(b"x" * 1024 * 1024)  # 1 MB，删除失败
    monkeypatch.setattr("delector.routes.main.AUDIO_CACHE_DIR", str(cache_dir))

    real_remove = os.remove

    def flaky_remove(path):
        if os.path.basename(path) == "locked.mp3":
            raise PermissionError("locked by another process")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)

    before = client.get("/api/audio/cache").json()["total_size_mb"]
    res = client.post("/api/audio/cache/clear")
    assert res.status_code == 200
    after = client.get("/api/audio/cache").json()["total_size_mb"]

    assert before == 2.0 and after == 1.0
    assert res.json()["freed_mb"] == round(before - after, 2) == 1.0


# ── C8 Task5: encounter 出站抓取大小闸 + 诚实状态码 ────────────────────────────


class _FakeShelfStream:
    """`httpx.stream(...)` 的替身：可注字节分片、可注 Content-Length、可注状态码。"""

    def __init__(self, chunks, status_code=200, headers=None):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}

    def iter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mock_shelf_stream(monkeypatch, resp):
    from delector.routes import encounter as encounter_routes

    monkeypatch.setattr(encounter_routes.httpx, "stream", lambda *a, **k: resp)


def test_encounter_pull_pack_rejects_oversized_response_with_content_length(client, monkeypatch):
    """超 2MB 的货架响应必须被拒（Content-Length 已点破的情况）。"""
    from delector.core.security import MAX_HTML_BYTES

    big = b"x" * (MAX_HTML_BYTES + 1)
    _mock_shelf_stream(
        monkeypatch, _FakeShelfStream([big], headers={"content-length": str(len(big))})
    )

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://127.0.0.1:8000", "pack_id": ""},
    )
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "体积超限" in detail
    assert "2MB" in detail


def test_encounter_pull_pack_rejects_oversized_stream_without_content_length(client, monkeypatch):
    """无 Content-Length 的超大流同样必须被拒：上限在**读取过程中**累计生效。"""
    from delector.core.security import MAX_HTML_BYTES

    chunk = b"x" * (512 * 1024)
    chunks = [chunk] * (MAX_HTML_BYTES // len(chunk) + 2)  # 3MB，远超 2MB
    _mock_shelf_stream(monkeypatch, _FakeShelfStream(chunks))  # headers 为空 ⇒ 无 content-length

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://127.0.0.1:8000", "pack_id": ""},
    )
    assert res.status_code == 502
    assert "体积超限" in res.json()["detail"]


def test_encounter_pull_pack_surfaces_real_404_status_code(client, monkeypatch):
    """404（资源不存在）必须与「连不上电脑端」区分开：真实状态码进原因。"""
    from delector.routes import encounter as encounter_routes

    _mock_shelf_stream(monkeypatch, _FakeShelfStream([b"{}"], status_code=404))

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://127.0.0.1:8000", "pack_id": "nope"},
    )
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "404" in detail
    # 不得再糊成 WiFi/防火墙提示（那会把「卡包不存在」误导成「网络不通」）
    assert detail != encounter_routes._PULL_FAIL_HINT


def test_encounter_pull_pack_surfaces_real_5xx_status_code(client, monkeypatch):
    """5xx 与 404 文案必须不同：同族错误不能糊成同一句话。"""
    _mock_shelf_stream(monkeypatch, _FakeShelfStream([b"{}"], status_code=503))

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://127.0.0.1:8000", "pack_id": "nope"},
    )
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "503" in detail
    assert "404" not in detail


def test_encounter_pull_pack_accepts_small_response(client, monkeypatch):
    """正常小响应照旧被接受（大小闸不得误伤正常拉取）。"""
    body = json.dumps({"packs": [{"pack_id": "p1", "title": "Test"}]}).encode("utf-8")
    _mock_shelf_stream(
        monkeypatch, _FakeShelfStream([body], headers={"content-length": str(len(body))})
    )

    res = client.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://127.0.0.1:8000", "pack_id": ""},
    )
    assert res.status_code == 200
    assert res.json() == {"packs": [{"pack_id": "p1", "title": "Test"}]}


def test_core_dict_and_offline_vocab_lookup(client):
    """Test offline Goethe core vocabulary lookup and CEFR tagging."""
    from delector.data.core_dict import get_core_cefr_level, lookup_core_vocab

    # Direct core_dict module tests
    hit = lookup_core_vocab("Herausforderung")
    assert hit is not None
    assert hit["cefr_level"] == "B1"
    assert hit["gender"] == "Fem"
    assert "挑战" in hit["definition_zh"]

    lvl = get_core_cefr_level("klimawandel")
    assert lvl == "B1"

    # API endpoint test with local dict hit (no network API key required)
    res = client.post(
        "/api/lookup/vocab",
        json={"sentence": "Der Klimawandel ist eine große Herausforderung.", "target_word": "Herausforderung"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "local_dict"
    assert "挑战" in data["definition_zh"]
    assert data["gender"] == "Fem"
    assert data["cefr_level"] == "B1"


def test_static_esm_modules_served(client):
    """Test all static ES Modules are served properly by FastAPI."""
    for mod in ["main.js", "core.js", "player.js", "reader.js", "cards.js", "folio.js", "cloze.js"]:
        res = client.get(f"/js/{mod}")
        assert res.status_code == 200
        assert "javascript" in res.headers.get("content-type", "")


def test_feed_sources_endpoint(client):
    """Test GET /api/feed/sources returns preset German learning & news feeds."""
    res = client.get("/api/feed/sources")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data
    assert len(data["sources"]) >= 4
    ids = [s["id"] for s in data["sources"]]
    assert "dw_deutsch" in ids
    assert "tagesschau_news" in ids


def test_feed_items_parsing_and_endpoint(client, monkeypatch):
    """Test RSS XML fetching and parsing via /api/feed/items."""
    sample_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Tagesschau</title>
        <link>https://www.tagesschau.de</link>
        <item>
          <title>Klimaschutz in Deutschland</title>
          <link>https://www.tagesschau.de/inland/klima-100.html</link>
          <description>&lt;p&gt;Deutschland will bis 2045 klimaneutral werden.&lt;/p&gt;</description>
          <pubDate>Wed, 19 Aug 2026 08:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""

    from delector.routes import main as routes_main

    async def mock_fetch(url):
        return sample_rss_xml

    monkeypatch.setattr(routes_main, "fetch_remote_html", mock_fetch)
    monkeypatch.setattr(routes_main, "is_safe_public_url", lambda u: True)

    res = client.get("/api/feed/items?url=https://www.tagesschau.de/xml/rss2/")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    item = data["items"][0]
    assert item["title"] == "Klimaschutz in Deutschland"
    assert "Deutschland will bis 2045" in item["summary"]
    assert item["link"] == "https://www.tagesschau.de/inland/klima-100.html"


def test_feed_items_rdf_parsing(client, monkeypatch):
    """Test RDF XML parsing (used by DW and others)."""
    sample_rdf = """<?xml version="1.0" encoding="UTF-8"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
      <item>
        <title>Neues Gesetz im Bundestag verabschiedet</title>
        <link>https://www.dw.com/de/bundestag-gesetz/a-999</link>
        <description>Der Bundestag hat heute das neue Gesetz beschlossen.</description>
        <dc:date xmlns:dc="http://purl.org/dc/elements/1.1/">2026-08-19T08:00:00Z</dc:date>
      </item>
    </rdf:RDF>"""

    from delector.routes import main as routes_main

    async def mock_fetch_rdf(url):
        return sample_rdf

    monkeypatch.setattr(routes_main, "fetch_remote_html", mock_fetch_rdf)
    monkeypatch.setattr(routes_main, "is_safe_public_url", lambda u: True)

    res = client.get("/api/feed/items?url=https://rss.dw.com/rdf/rss-de-all")

    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["items"][0]["title"] == "Neues Gesetz im Bundestag verabschiedet"
    assert "Bundestag" in data["items"][0]["summary"]


def test_syntax_analyze_endpoint(client):
    res = client.post(
        "/api/syntax/analyze", json={"text": "Weil das Wetter heute schön ist, geht Maria im Park spazieren."}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == "3.5.0"
    assert data["sentence_count"] == 1
    s0 = data["sentences"][0]
    assert "topology" in s0
    assert "clause_tree" in s0
    assert "vorfeld" in s0["topology"]
    assert "linke_klammer" in s0["topology"]
    assert s0["topology"]["field_texts"]["linke_klammer"] == "geht"


def test_process_german_text_includes_topology_and_clause_tree():
    processed = process_german_text("Er hat das Buch gelesen. Wenn er Zeit hat, kommt er vorbei.")
    assert processed["version"] == "3.5.0"
    assert len(processed["sentences"]) == 2

    s0 = processed["sentences"][0]
    assert "topology" in s0
    assert "clause_tree" in s0
    assert s0["topology"]["field_texts"]["vorfeld"] == "Er"
    assert s0["topology"]["field_texts"]["linke_klammer"] == "hat"


def test_app_settings_get_and_post(client):
    # 1. Initial settings
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "has_api_key" in data
    assert "api_base_url" in data
    assert "tts_voice" in data

    # 2. Update settings
    up_res = client.post(
        "/api/settings",
        json={
            "api_key": "sk-test-mock-key-1234567890",
            "api_base_url": "https://api.custom.com/v1",
            "api_model": "custom-gpt4",
            "tts_voice": "de-DE-ConradNeural",
            "tts_rate": "+15%",
        },
    )
    assert up_res.status_code == 200
    assert up_res.json()["success"] is True

    # 3. Verify settings updated and masked
    res2 = client.get("/api/settings")
    data2 = res2.json()
    assert data2["has_api_key"] is True
    assert data2["api_key_masked"].startswith("sk-t")
    assert data2["api_base_url"] == "https://api.custom.com/v1"
    assert data2["api_model"] == "custom-gpt4"
    assert data2["tts_voice"] == "de-DE-ConradNeural"
    assert data2["tts_rate"] == "+15%"


def test_settings_test_key_without_key(client, monkeypatch):
    # 密闭性：本机 .env 若配了真实 DEEPSEEK_API_KEY，会被 load_env() 灌进
    # app_settings，端点于是拿到真 key 去打真实 DeepSeek（既烧 token，又让
    # 「无 key 应失败」的断言从红翻绿）。这里强制 effective key 为空。
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "error" in data


# ── 查词链修复测试（lemma-first / EXT 接线 / 诚实 source）────────────────────


def test_lookup_lemma_first(client, monkeypatch):
    """前端带 lemma → 直接命中核心词库，不触发 AI。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht", "lemma": "gehen"})
    data = r.json()
    assert data["source"] == "local_dict"
    assert "去" in data["definition_zh"]


def test_lookup_lemma_absent_present_irregular(client, monkeypatch):
    """无 lemma 时 geht 靠现在时反查 → stammformen + 三态表释义回填。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht"})
    data = r.json()
    assert data.get("stammformen", {}).get("infinitiv") == "gehen"
    assert data["definition_zh"]
    assert data["source"] == "linguistics"


def test_lookup_plural_haeuser(client, monkeypatch):
    """变元音复数 Häuser + lemma Haus → 核心词库命中。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post(
        "/api/lookup/vocab", json={"sentence": "Die Häuser sind alt.", "target_word": "Häuser", "lemma": "Haus"}
    )
    data = r.json()
    assert data["source"] == "local_dict"
    assert "房屋" in data["definition_zh"]


def test_lookup_linguistics_ext_tier(client, monkeypatch):
    """主链查不到时落 EXT（LINGUISTICS_VOCAB_EXT 接线）。

    探针词从旧的 ``klima`` 换为 ``tunnel``：官方词表接入主干后 ``klima`` 已是
    core_dict 命中词（source=local_dict），不再能证明 EXT 回退层；``tunnel`` 只在
    LINGUISTICS_VOCAB_EXT、不在任何主干分片里，仍能钉住这条回退链。
    """
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Tunnel.", "target_word": "tunnel"})
    data = r.json()
    assert data["source"] == "linguistics_ext"
    assert "隧道" in data["definition_zh"]


def test_lookup_no_hit_honest_none(client, monkeypatch):
    """未知词 + 无 key → source=none 空释义（不再是 AI 已预填谎言）。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Xyzzy.", "target_word": "zzzznonsense"})
    data = r.json()
    assert data["source"] == "none"
    assert not data["definition_zh"]


def test_lookup_ai_error_backfill_linguistics(client, monkeypatch):
    """key 假 + httpx 崩 → ai_exception；强动词变位词回填三态表释义。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "sk-bogus")

    class _BoomClient:
        def post(self, *a, **k):
            raise RuntimeError("simulated network down")

    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", lambda *a, **k: _BoomClient())
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht"})
    data = r.json()
    assert data["source"] == "linguistics"
    assert data["definition_zh"]


# ── 安全加固回归：SSRF 多地址校验 / 重定向逐跳预校验 / TTS 长度闸 ─────────────


def test_is_safe_public_url_rejects_when_any_resolved_ip_is_private(monkeypatch):
    """域名解析出的每一条地址都必须过闸。

    只查第一条 A 记录的旧写法（gethostbyname）会放过「公网 A 记录掩护下的
    内网 A/AAAA 记录」组合。monkeypatch 同时钉住新旧两条解析路径：
    旧实现查 gethostbyname 拿到公网 IP 会误判通过，本测试对它是红的。
    """
    import socket as _socket

    public_ip, private_v6 = "93.184.216.34", "fd00::1"

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (public_ip, port or 0)),
            (_socket.AF_INET6, _socket.SOCK_STREAM, 17, "", (private_v6, port or 0)),
        ]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_socket, "gethostbyname", lambda host: public_ip)

    assert is_safe_public_url("https://mixed-dns.example/") is False


def test_is_safe_public_url_accepts_all_public_resolution(monkeypatch):
    """全部地址都是公网时照常放行，不能因为加了校验而误杀正常站点。"""
    import socket as _socket

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0)),
            (_socket.AF_INET6, _socket.SOCK_STREAM, 17, "", ("2606:2800:220:1:248:1893:25c8:1946", port or 0)),
        ]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    assert is_safe_public_url("https://all-public.example/") is True


# ── IPv6 过渡格式：判定必须落在「内嵌的目的 IPv4」上，而不是外层包装 ────────────


def _pin_resolution(monkeypatch, addr: str):
    """把 getaddrinfo 钉成只返回 addr 一条，避免测试依赖真实 DNS。"""
    import socket as _socket

    family = _socket.AF_INET6 if ":" in addr else _socket.AF_INET
    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (family, _socket.SOCK_STREAM, 6, "", (addr, 443, 0, 0)),
        ],
    )


@pytest.mark.parametrize(
    "addr, note",
    [
        ("2002:c0a8:0101::1", "6to4 内嵌 192.168.1.1"),
        ("2002:7f00:0001::1", "6to4 内嵌 127.0.0.1"),
        ("2002:a9fe:a9fe::1", "6to4 内嵌 169.254.169.254 云元数据"),
        ("2001:0:0:0:0:0:3f57:fefe", "Teredo client 内嵌 192.168.1.1"),
        ("2001:0:c0a8:101:0:0:4746:748", "Teredo server 内嵌 192.168.1.1"),
        ("::ffff:127.0.0.1", "IPv4-mapped 回环"),
        ("::ffff:10.0.0.5", "IPv4-mapped 内网"),
    ],
)
def test_is_safe_public_url_rejects_ipv4_smuggled_in_ipv6(monkeypatch, addr, note):
    """内网 IPv4 套进 IPv6 过渡格式后必须照样被拦。

    这是真能打进内网的 SSRF 通道，不是理论风险：6to4 的 `2002:c0a8:0101::1`
    外层 `is_global` 为真、六个旗标一个不沾，旧写法（只看外层 `is_private` 等）
    对它一路放行，而内核会把包路由到 192.168.1.1。
    """
    _pin_resolution(monkeypatch, addr)
    assert is_safe_public_url("https://smuggle.example/") is False, note


@pytest.mark.parametrize(
    "addr, note",
    [
        ("2001::b92d:7b9", "Teredo client 70.210.248.70 公网、server 段全零"),
        ("2002:8080:8080::1", "6to4 内嵌 128.128.128.128 公网"),
        ("::ffff:8.8.8.8", "IPv4-mapped 公网"),
    ],
)
def test_is_safe_public_url_accepts_public_target_behind_ipv6_transition(monkeypatch, addr, note):
    """过渡格式包着公网地址时必须放行——修误放不能顺手把误拒留下。

    `2001::/32`(Teredo) 落在 ipaddress 的私有段清单 `2001::/23` 里、
    `::ffff:0:0/96` 被判 `is_reserved`，只看外层旗标会把它们全拒掉：
    本机 `www.dw.com` 曾解析出 `2001::b92d:7b9`，于是 URL 导入对**所有**站点
    全废。CI 的 Linux runner 没有 Teredo，这个方向在 CI 上永远看不见。
    """
    _pin_resolution(monkeypatch, addr)
    assert is_safe_public_url("https://transition.example/") is True, note


_IPV6_SPECIAL_ADDRS = (
    "2001:db8::1",  # documentation（在 2001::/23 之外）
    "2001:2::1",  # benchmarking
    "2001:3::1",  # AMT
    "2001:4:112::1",  # AS112-v6
    "2001:10::1",  # ORCHID（已弃用）
    "2001:20::1",  # ORCHIDv2 —— 3.11.16 上从 ipaddress 的表里掉了出来
    "2001:30::1",  # Drone Remote ID
    "100::1",  # discard-only
    "5f00::1",  # SRv6 SID
    "64:ff9b:1::1",  # 本地用 IPv4/IPv6 转换
)


def test_is_safe_public_url_still_rejects_non_teredo_2001_ranges(monkeypatch):
    """`2001::/23` 里除 Teredo 之外的保留段不能被顺手放开。

    修法是「只对 Teredo/6to4/IPv4-mapped 解包」，不是「把 2001:: 整段当公网」。
    """
    for addr in _IPV6_SPECIAL_ADDRS:
        _pin_resolution(monkeypatch, addr)
        assert is_safe_public_url("https://reserved.example/") is False, addr


def test_ipv6_special_ranges_are_pinned_in_our_own_code():
    """这些段必须由**我们自己的常量**兜住，不能只靠 `ipaddress` 的私有段表。

    那张表会随 Python 补丁版本变：3.11.8 里有一条粗粒度的 `2001::/23`，把整个
    IETF Protocol Assignments 块兜住；3.11.16 换成细粒度条目后 `2001:20::/28`
    (ORCHIDv2) 掉了出来，闸门就此放行。同一份代码、同一个 3.11 大版本，
    判定结果相反 —— 本机绿而 CI 红，v4.4.8 首次发布就是这么挂的。
    """
    import ipaddress as _ip

    from delector import server as _srv

    for addr in _IPV6_SPECIAL_ADDRS:
        obj = _ip.ip_address(addr)
        assert obj in _srv._IETF_PROTOCOL_ASSIGNMENTS or any(obj in net for net in _srv._IPV6_DENY_PREFIXES), (
            f"{addr} 只靠 ipaddress 的表兜着，换个 Python 补丁版本就会漏"
        )


class _FlaglessIPv6(ipaddress.IPv6Address):
    """把 stdlib 的所有旗标压成假的 IPv6 地址替身。

    要单独验证「我们自己钉的段」在起作用，就必须把 `ipaddress` 那张表的贡献
    摘干净：真地址在 3.11.8 上会被粗粒度的 `2001::/23` 条目兜住，把
    `_is_blocked_addr` 里我们的范围检查整段删掉，本机照样全绿 —— v4.4.8
    第一次发版就是这么被放过去的。

    为什么不改 stdlib 那张表来模拟 CI 的 Python：3.11.8 的 `is_private` 上还挂着
    `functools.lru_cache`，只要**任何**更早的测试算过同一个地址，结果就被永久缓存，
    之后改表毫无作用 —— 测试会随执行顺序时红时绿。替身不碰 CPython 内部，
    换 Python 版本也不会漂。
    """

    is_private = False
    is_loopback = False
    is_link_local = False
    is_reserved = False
    is_multicast = False
    is_unspecified = False


def test_is_blocked_addr_relies_on_our_own_pinned_ranges():
    """旗标全假时仍要拒 —— 拒绝理由只能来自我们钉的段，不能来自 stdlib。"""
    for addr in _IPV6_SPECIAL_ADDRS:
        assert server._is_blocked_addr(_FlaglessIPv6(addr)) is True, addr

    # 反向：替身不是「什么都拒」。公网地址、以及 Teredo 包着的公网 IPv4
    # （已在 `_resolve_ssrf_targets` 里解包成 70.210.248.70）都必须放行。
    for addr in ("2a03:2880:f11b:83:face:b00c:0:25de", "2606:4700::1111", "2001::b92d:7b9"):
        assert server._is_blocked_addr(_FlaglessIPv6(addr)) is False, addr


def test_url_ingest_gate_is_pinned_not_dns_dependent():
    """端点测试不许依赖真实 DNS——本机 IPv6 状态一变就时红时绿。

    `test_url_ingest_endpoint_with_mock` 只 mock 了 `fetch_remote_html`，
    但端点自己还会调一次 `is_safe_public_url`（server.py:858），闸门没被钉住。
    """
    import inspect

    src = inspect.getsource(test_url_ingest_endpoint_with_mock)
    assert "delector.routes.main.is_safe_public_url" in src, "端点测试必须钉住 SSRF 闸，不能真去问 DNS"


def test_fetch_remote_html_never_requests_blocked_redirect_target(monkeypatch):
    """重定向目标必须在请求发出**之前**过 SSRF 闸。

    follow_redirects=True 的旧写法先打请求、后校验最终 URL——重定向到内网时
    内网服务已经收到 GET（盲 SSRF），哪怕响应随后被丢弃。
    """
    import asyncio
    import ipaddress as _ipaddress
    import socket as _socket

    from fastapi import HTTPException

    import delector.core.security as security

    requested = []

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        host = host.strip("[]")
        try:
            _ipaddress.ip_address(host)  # 字面量 IP 原样返回，让内网判定照常生效
        except ValueError:
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (host, port or 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    def fake_gethostbyname(host):
        # 字面量内网 IP 原样返回，旧实现的最终校验才能识别它；
        # 其余域名一律解析成公网 IP——否则 .example 真实解析失败会在
        # 请求发出前就被拒，测试对旧实现假绿。
        return host if host.startswith("169.254") else "93.184.216.34"

    monkeypatch.setattr(_socket, "gethostbyname", fake_gethostbyname)

    class FakeResp:
        def __init__(self, status_code, headers=None, text="", url=""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self.url = url

        @property
        def is_redirect(self):
            return self.status_code in (301, 302, 303, 307, 308)

    class FakeClient:
        """按构造参数忠实模拟 httpx 的跟随语义：follow_redirects=True（旧实现）
        在 get() 内部自动追跳每一跳；False 时原样返回 3xx，由服务端逐跳驱动。"""

        def __init__(self, *args, follow_redirects=False, **kwargs):
            self.follow_redirects = follow_redirects

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            url = str(url)
            while True:
                requested.append(url)
                if url == "https://public-start.example/article":
                    if self.follow_redirects:
                        url = "http://169.254.169.254/latest/meta-data/"
                        continue
                    return FakeResp(302, {"location": "http://169.254.169.254/latest/meta-data/"}, url=url)
                if url.startswith("http://169.254.169.254"):
                    # 内网目标照常「应答」——旧实现下这个请求已经发生（盲 SSRF）
                    return FakeResp(200, {}, "fake-internal-body", url=url)
                return FakeResp(200, {}, "<html>ok</html>", url=url)

    monkeypatch.setattr(security.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://public-start.example/article"))
    assert exc_info.value.status_code == 400
    assert all("169.254" not in u for u in requested), f"盲 SSRF 发生了: {requested}"


def test_fetch_remote_html_still_follows_public_redirects(monkeypatch):
    """公网站点之间的正常重定向链不受影响——加固不能误杀正常抓取。"""
    import asyncio
    import socket as _socket

    import delector.core.security as security

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_socket, "gethostbyname", lambda host: "93.184.216.34")

    requested = []

    class FakeResp:
        def __init__(self, status_code, headers=None, text="", url=""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self.url = url

        @property
        def is_redirect(self):
            return self.status_code in (301, 302, 303, 307, 308)

    class FakeClient:
        """与被拒测试同一套跟随语义：True 时桩内追跳（旧行为），False 时裸 3xx。"""

        def __init__(self, *args, follow_redirects=False, **kwargs):
            self.follow_redirects = follow_redirects

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            url = str(url)
            while True:
                requested.append(url)
                if url == "https://short.example/x":
                    if self.follow_redirects:
                        url = "https://short.example/final"
                        continue
                    return FakeResp(302, {"location": "/final"}, url=url)
                return FakeResp(200, {}, "<html>ok</html>", url=url)

    monkeypatch.setattr(security.httpx, "AsyncClient", FakeClient)

    body = asyncio.run(security.fetch_remote_html("https://short.example/x"))
    assert body == "<html>ok</html>"
    assert len(requested) == 2


def test_fetch_remote_html_network_error_returns_502(monkeypatch):
    """P1-3: 出网抓取遇到 DNS/连接失败/httpx.HTTPError 时，必须返回 502 并携带明确人话说明。"""
    import asyncio
    import socket as _socket

    import httpx
    from fastapi import HTTPException

    import delector.core.security as security

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda *a, **kw: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    class ErrorClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("Connection refused by peer")

        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("Connection refused by peer")

    monkeypatch.setattr(security.httpx, "AsyncClient", ErrorClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://example.com/unreachable"))
    assert exc_info.value.status_code == 502
    assert "连接失败" in exc_info.value.detail or "ConnectError" in exc_info.value.detail


def test_fetch_remote_html_total_timeout_returns_502(monkeypatch):
    """P1-3: 出网抓取总耗时超出截止时间时，必须掐断并返回 502。"""
    import asyncio
    import socket as _socket

    from fastapi import HTTPException

    import delector.core.security as security

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda *a, **kw: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    class SlowClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            await asyncio.sleep(0.5)
            return None

        def stream(self, *args, **kwargs):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _slow_stream():
                await asyncio.sleep(0.5)
                yield None

            return _slow_stream()

    monkeypatch.setattr(security.httpx, "AsyncClient", SlowClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://example.com/slow", total_timeout=0.05))
    assert exc_info.value.status_code == 502
    assert "超时" in exc_info.value.detail


def test_tts_rejects_oversized_text(client):
    """朗读接口有长度上限：局域网可达的端点不该被超大文本打满合成与磁盘缓存。"""
    res = client.post("/api/audio/tts", json={"text": "A" * 1001})
    assert res.status_code == 400


# ── v4.4 Task1: Settings localhost-only security boundary (failing before Task2) ──


def test_settings_post_rejects_non_loopback_client(lan_client):
    """非本机不得修改敏感设置：POST /api/settings 来自局域网必须 403。"""
    res = lan_client.post("/api/settings", json={"api_key": "sk-should-be-rejected"})
    assert res.status_code == 403


def test_settings_test_key_rejects_non_loopback_client(lan_client):
    """非本机不得测试连通性：POST /api/settings/test-key 来自局域网必须 403。"""
    res = lan_client.post("/api/settings/test-key", json={"api_key": "sk-any"})
    assert res.status_code == 403


def test_settings_post_lan_does_not_mutate_sensitive_settings(lan_client, test_db_path):
    """被 403 时数据库中的敏感设置必须保持不变。"""
    import sqlite3

    set_setting("DEEPSEEK_API_KEY", "sk-original-keep", db_path=test_db_path)
    set_setting("API_BASE_URL", "https://original.example/v1", db_path=test_db_path)

    res = lan_client.post(
        "/api/settings",
        json={
            "api_key": "sk-hacked-rejected",
            "api_base_url": "https://evil.example/v1",
        },
    )
    assert res.status_code == 403

    conn = sqlite3.connect(test_db_path)
    rows = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM app_settings").fetchall()}
    conn.close()
    assert rows.get("DEEPSEEK_API_KEY") == "sk-original-keep"
    assert rows.get("API_BASE_URL") == "https://original.example/v1"


def test_settings_test_key_lan_does_not_leak_or_mutate(lan_client, test_db_path):
    """test-key 被 403 时也不得改库或泄露信息。"""
    import sqlite3

    set_setting("DEEPSEEK_API_KEY", "sk-keep-intact", db_path=test_db_path)
    res = lan_client.post("/api/settings/test-key", json={"api_key": "sk-evil"})
    assert res.status_code == 403
    conn = sqlite3.connect(test_db_path)
    val = conn.execute("SELECT value FROM app_settings WHERE key='DEEPSEEK_API_KEY'").fetchone()
    conn.close()
    assert val and val[0] == "sk-keep-intact"


def test_settings_post_succeeds_on_loopback(client):
    """回环来源的合法设置更新仍返回成功；已有 /api/settings 行为保持不变。"""
    res = client.post(
        "/api/settings",
        json={
            "api_key": "sk-loopback-ok-1234567890",
            "api_base_url": "https://api.loopback.example/v1",
            "tts_voice": "de-DE-ConradNeural",
        },
    )
    assert res.status_code == 200
    assert res.json().get("success") is True

    # verify persisted and masked correctly
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["has_api_key"] is True
    assert data["api_base_url"] == "https://api.loopback.example/v1"
    assert data["tts_voice"] == "de-DE-ConradNeural"


def test_settings_test_key_succeeds_on_loopback(client, monkeypatch):
    """回环来源的 test-key 不应被 403 拦截（空 key 时返回 success=False 而非 403）。"""
    # 同上：切断本机 .env 真 key，避免真实外呼（密闭性 + 不烧 token）。
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    # 未被来源闸拦截：返回 200 且 success 为 False（提示输入 key），而非 403
    assert res.status_code == 200
    assert res.json().get("success") is False


# GET /api/settings 回环来源的字段集合口径锚（C8 Task6）：非回环来源恰好少
# `api_key_masked` 一项，其余逐字一致——否则桌面端会静默失去配置面板。
_SETTINGS_LOOPBACK_KEYS = {
    "has_api_key",
    "api_key_masked",
    "api_base_url",
    "api_model",
    "tts_voice",
    "tts_rate",
    "nlp_engine",
    "nlp_engine_detail",
}


def test_settings_get_loopback_origin_keeps_api_key_masked_field():
    """回环来源（127.0.0.1）的字段集合 MUST 与今日逐字一致。"""
    loopback = TestClient(app, client=("127.0.0.1", 54321))
    res = loopback.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == _SETTINGS_LOOPBACK_KEYS
    assert "api_key_masked" in data


def test_settings_get_non_loopback_origin_omits_api_key_masked_field():
    """非回环来源（192.168.1.50）不得读到 api key（哪怕已掩码）。

    注意这是**按来源收敛字段**，不是整门拦截：局域网手机端仍要能读 base_url /
    model / tts_* 来渲染设置面板（前端 static/js/main.js:632-634），
    故 MUST NOT 加 `_require_localhost`（那会让手机端直接吃 403）。
    """
    lan = TestClient(app, client=("192.168.1.50", 54322))
    res = lan.get("/api/settings")
    assert res.status_code == 200, "LAN 来源必须仍能读该端点（不得整门 403）"
    data = res.json()
    assert "api_key_masked" not in data
    assert set(data.keys()) == _SETTINGS_LOOPBACK_KEYS - {"api_key_masked"}
    # 只收敛这一项：其余字段照旧
    assert "has_api_key" in data
    assert "api_base_url" in data
    assert "api_model" in data
    assert "tts_voice" in data


# ── v4.4 Task6: Backup source, Android spaCy loading, AI failure paths ─────────

# --- 6.3 AI 402 / timeout / non-JSON (server returns 502, not 200) ---


def _make_402_client():
    class _R:
        status_code = 402
        text = '{"error":{"code":"insufficient_balance"}}'

        def json(self):
            return {"error": "Insufficient Balance"}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


def _make_timeout_client():
    import httpx as _httpx

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            raise _httpx.TimeoutException("simulated timeout")

    return _C


def _make_non_json_client():
    class _R:
        status_code = 200
        text = "not json"

        def json(self):
            raise ValueError("not json")

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


def _make_non_json_content_client():
    """HTTP 200 但 choices[0].message.content 不是 JSON。"""

    class _R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "THIS IS NOT JSON"}}]}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return _R()

    return _C


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_note_assist_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-test-402-timeout")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/ai/note-assist", json={"sentence": "Guten Tag.", "selected_text": "Guten Tag"})
    assert res.status_code == 502, f"AI 失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    # 不得泄露 API Key
    assert "sk-test-402-timeout" not in res.text


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_ai_polish_diff_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-test-polish")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish/diff", json={"text": "Ich habe ein Hund."})
    assert res.status_code == 502, f"AI 润色失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    assert "sk-test-polish" not in res.text


@pytest.mark.parametrize(
    "factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client]
)
def test_ai_polish_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-test-polish2")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 502
    assert "sk-test-polish2" not in res.text


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client])
def test_grammar_lookup_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-grammar")
    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", factory())
    res = client.post("/api/lookup/grammar", json={"sentence": "Ich gehe.", "target_phrase": "gehe"})
    assert res.status_code == 502
    assert "sk-grammar" not in res.text


def test_ai_no_key_stub_still_succeeds(client, monkeypatch):
    """无 key 时仍返回 200 stub（与网络失败的 502 区分）。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/ai/note-assist", json={"sentence": "Hallo.", "selected_text": "Hallo"})
    assert res.status_code == 200
    assert res.json().get("_stub") is True
    res2 = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


# ── GET /api/audio/tts ───────────────────────────────────────────────────────


def test_get_audio_tts_returns_mp3(client):
    """GET 版 TTS 端点：供 workbench <audio src> 直接用，无需 fetch + blob。"""
    r = client.get("/api/audio/tts", params={"text": "hallo"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert len(r.content) > 0
    assert 'filename="speech.mp3"' in r.headers.get("content-disposition", "")


def test_get_audio_tts_rejects_empty_text(client):
    r = client.get("/api/audio/tts", params={"text": ""})
    assert r.status_code == 400


def test_get_audio_tts_rejects_overlong_text(client):
    r = client.get("/api/audio/tts", params={"text": "x" * 1001})
    assert r.status_code == 400


def test_get_audio_tts_rejects_malformed_rate(client):
    r = client.get("/api/audio/tts", params={"text": "hallo", "rate": "banana"})
    assert r.status_code == 400


# ── Task 1 Hardening & Regression Test Suite ──────────────────────────────────


def test_task1_restore_req_includes_a1_records(client):
    """RestoreReq 正确支持 a1_hoeren_records 与 a1_lesen_records 还原。"""
    payload = {
        "version": 2,
        "a1_hoeren_records": [
            {
                "id": 101,
                "set_id": 1,
                "score_raw": 14,
                "score_official": 23.3,
                "total_questions": 15,
                "duration_seconds": 580,
                "answers_json": '{"q1": "A"}',
                "wrong_questions_json": "[]",
                "created_at": "2026-09-01T12:00:00",
            }
        ],
        "a1_lesen_records": [
            {
                "id": 201,
                "set_id": 2,
                "score_raw": 13,
                "score_official": 21.7,
                "total_questions": 15,
                "duration_seconds": 650,
                "answers_json": '{"q1": "B"}',
                "wrong_questions_json": "[]",
                "created_at": "2026-09-01T12:00:00",
            }
        ],
    }
    res = client.post("/api/backup/restore", json=payload)
    assert res.status_code == 200

    with db_progress_conn() as pconn:
        h = pconn.execute("SELECT * FROM a1_hoeren_records WHERE id = 101").fetchone()
        lr = pconn.execute("SELECT * FROM a1_lesen_records WHERE id = 201").fetchone()
    assert h is not None and h["score_raw"] == 14
    assert lr is not None and lr["score_raw"] == 13


def test_task1_review_card_computes_elapsed_days(client):
    """review_card_sm2 从 due_date 计算真实的 elapsed_days。"""
    from datetime import datetime, timedelta

    ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, pos, cefr_level, definition_zh, sentence_context,
                interval_days, ease_factor, repetition_count, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            ("TestWord", "TestWord", "NOUN", "A1", "测试词义", "Context sentence", 3, 2.5, 2, ten_days_ago),
        )
        card_id = cur.lastrowid

    # 逾期 10 天复习，elapsed_days 应 > interval_days (3)
    res = client.post(f"/api/cards/vocab/{card_id}/review", json={"grade": 3})
    assert res.status_code == 200
    data = res.json()
    assert data["interval_days"] > 3


def test_task1_tts_fallback_chain_on_mini_failure(monkeypatch):
    """当 edge_tts 缺失且 edge_tts_mini 抛异常时，平滑降级到备选引擎。"""
    import asyncio
    import sys

    from delector.routes import main as routes_main

    # 模拟 edge_tts 缺失
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    # 模拟 edge_tts_mini（services.tts）失败
    class FakeMini:
        @staticmethod
        def synthesize(*args, **kwargs):
            raise RuntimeError("Mini TTS simulated error")

    monkeypatch.setitem(sys.modules, "delector.services.tts", FakeMini)

    # 模拟有道兜底响应
    class MockHttpxResp:
        status_code = 200
        content = b"ID3" + b"\x00" * 300  # 合法音频 mock 数据

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, *args, **kwargs):
            return MockHttpxResp()

    monkeypatch.setattr(routes_main.httpx, "AsyncClient", MockAsyncClient)

    audio_file = asyncio.run(routes_main.generate_edge_tts_audio("Guten Morgen", voice="de-DE-KatjaNeural"))
    assert os.path.exists(audio_file)
    assert os.path.getsize(audio_file) > 200


def test_task1_localhost_protection_on_destructive_endpoints(client, lan_client):
    """验证 delete_article, delete_card, clear_audio_cache, delete_essay, delete_essay_version 的局域网拦截。"""
    # 1. 局域网访问一律 403
    assert lan_client.delete("/api/articles/999").status_code == 403
    assert lan_client.delete("/api/cards/vocab/999").status_code == 403
    assert lan_client.post("/api/audio/cache/clear").status_code == 403
    assert lan_client.delete("/api/essays/999").status_code == 403
    assert lan_client.delete("/api/essays/999/versions/999").status_code == 403

    # 2. 本机访问正常通过拦截（业务 404 或 200）
    assert client.delete("/api/articles/999").status_code == 404
    assert client.delete("/api/cards/vocab/999").status_code == 404
    assert client.post("/api/audio/cache/clear").status_code == 200
    assert client.delete("/api/essays/999").status_code == 404
    assert client.delete("/api/essays/999/versions/999").status_code == 404


def test_task1_get_article_corrupted_json(client):
    """get_article 面对损坏的 processed_json 能够平滑重新分析，不产生 500。"""
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO articles (title, raw_text, processed_json)
            VALUES (?, ?, ?)
        """,
            ("Corrupted Test", "Das ist ein Test.", "{invalid json broken syntax"),
        )
        art_id = cur.lastrowid

    res = client.get(f"/api/articles/{art_id}")
    assert res.status_code == 200
    data = res.json()
    assert "stats" in data
    assert data["sentence_count"] >= 1


def test_task1_create_writing_card_bounds_check(client):
    """save_writing_card 对越界的 sentence_id / span_index 进行防御性校验，返回 400 而非 500。"""
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO essays (title, content, analysis_json, cefr_level, error_count, sentence_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            ("Essay", "Content", json.dumps({"sentences": [{"text": "Hallo", "spans": []}]}), "A1", 0, 1),
        )
        essay_id = cur.lastrowid

    # 越界 sentence_id
    res1 = client.post("/api/writing/cards", json={"essay_id": essay_id, "sentence_id": 99, "span_index": 0})
    assert res1.status_code == 400

    # 越界 span_index
    res2 = client.post("/api/writing/cards", json={"essay_id": essay_id, "sentence_id": 0, "span_index": 99})
    assert res2.status_code == 400


def test_task1_is_safe_public_url_port_validation(monkeypatch):
    """is_safe_public_url 仅允许白名单端口 (80, 443, 8080, 8443, None)。"""
    import socket as _socket

    monkeypatch.setattr(
        _socket, "getaddrinfo", lambda host, port: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    )

    # 允许的端口
    assert is_safe_public_url("https://example.com") is True
    assert is_safe_public_url("http://example.com:80") is True
    assert is_safe_public_url("https://example.com:443") is True
    assert is_safe_public_url("http://example.com:8080/rss") is True
    assert is_safe_public_url("https://example.com:8443/feed") is True

    # 危险端口必须拒绝
    assert is_safe_public_url("http://example.com:22") is False
    assert is_safe_public_url("http://example.com:25") is False
    assert is_safe_public_url("http://example.com:3306") is False
    assert is_safe_public_url("http://example.com:6379") is False
    assert is_safe_public_url("http://example.com:27017") is False


def test_task1_fetch_remote_html_max_bytes_limit(monkeypatch):
    """fetch_remote_html 拦截 Content-Length > 2MB 或流式传输体积超过 2MB 的响应。"""
    import asyncio
    import socket as _socket

    from fastapi import HTTPException

    from delector.routes import main as routes_main

    monkeypatch.setattr(
        _socket, "getaddrinfo", lambda host, port: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    )

    class BigContentLengthResp:
        status_code = 200
        headers = {"content-length": str(3 * 1024 * 1024)}  # 3MB
        is_redirect = False

        async def aiter_bytes(self):
            yield b"small"

    class BigStreamResp:
        status_code = 200
        headers = {}
        is_redirect = False

        async def aiter_bytes(self):
            # 产生超过 2MB 的 chunk
            for _ in range(5):
                yield b"A" * (600 * 1024)

    class StreamMockClient:
        def __init__(self, mode="header"):
            self.mode = mode

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        # 刻意的类体内局部导入：装饰器只被本 mock 类的 stream 用到
        from contextlib import asynccontextmanager  # type: ignore[misc]

        @asynccontextmanager
        async def stream(self, method, url, headers=None):
            if self.mode == "header":
                yield BigContentLengthResp()
            else:
                yield BigStreamResp()

    # 1. 响应头 Content-Length 超过 2MB
    monkeypatch.setattr(routes_main.httpx, "AsyncClient", lambda *args, **kwargs: StreamMockClient("header"))
    with pytest.raises(HTTPException) as exc1:
        asyncio.run(routes_main.fetch_remote_html("https://example.com/big-header"))
    assert exc1.value.status_code == 400
    assert "体积超限" in exc1.value.detail

    # 2. 实际传输流数据超过 2MB
    monkeypatch.setattr(routes_main.httpx, "AsyncClient", lambda *args, **kwargs: StreamMockClient("stream"))
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(routes_main.fetch_remote_html("https://example.com/big-stream"))
    assert exc2.value.status_code == 400
    assert "体积超限" in exc2.value.detail


def test_task1_a1_anki_export_has_attachment_headers(client):
    """A1 Anki 导出接口携带符合规范的 _attachment_headers (含 no-store 与 UTF-8 编码文件名)。"""
    res = client.get("/api/a1/export/anki")
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert 'filename="Goethe_A1_Wortliste.apkg"' in cd
    assert "no-store" in res.headers.get("cache-control", "")


def test_task1_sync_router_thread_safety(client):
    """WebRTC 同步路由器具备 _sync_lock 保护，能正常存取。"""
    from delector.routes import sync as routes_sync

    assert hasattr(routes_sync, "_sync_lock")

    key = client.get("/api/wb/state/key").json()["key"]
    store_res = client.post(
        "/api/wb/sync/store",
        json={"sdp": {"type": "offer", "sdp": "v=0..."}, "role": "offer"},
        headers={"X-WB-Key": key},
    )
    assert store_res.status_code == 200
    code = store_res.json()["code"]

    fetch_res = client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key})
    assert fetch_res.status_code == 200
    assert fetch_res.json()["role"] == "offer"


def test_task1_corpus_dict_registered_in_all_packaging_targets():
    """corpus_dict 完整注册在 package_windows.py, CI workflow 以及 DeLector.spec 中。"""
    root = ROOT
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert "--hidden-import=delector.data.corpus_dict" in pkg
    assert "--hidden-import=delector.data.core_dict" in pkg

    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert wf.count("--hidden-import=delector.data.corpus_dict") == 2, "Linux & macOS 两个构建都要"

    # DeLector.spec 是本地 PyInstaller 产物：.gitignore 的 `*.spec` 把它排除，且 CI 里
    # pytest 跑在 package_windows.py / PyInstaller 之前，干净 checkout 下必然不存在。
    # 用显式 skip 而非静默 if，避免 CI 输出里看起来"通过了"其实一条都没断言。
    spec_path = os.path.join(root, "DeLector.spec")
    if not os.path.exists(spec_path):
        pytest.skip("DeLector.spec 未生成（本地构建产物，非 canonical）——跳过 spec 断言")
    spec = open(spec_path, encoding="utf-8").read()
    assert "'delector.data.corpus_dict'" in spec
    assert "'delector.routes.corpus'" in spec


def test_all_backend_modules_registered_in_all_packaging_targets():
    """所有路由与核心词典模块必须完整注册在 package_windows.py、CI workflow 以及 Android 拷贝清单中。

    防范 regression：
    - v4.8.1：routes_corpus.py 遗漏导致 Android APK 崩溃
    - v5.2.0：routes_rtc.py, routes_exam.py, exam_catalog.py 遗漏导致 Chaquopy 启动报
      ModuleNotFoundError: No module named 'routes_rtc'
    """
    root = ROOT
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()

    # Phase 1 Task 2：8 个纯数据词典已收进 delector.data/ 子包
    # T5：encounter_seed_dict 为第 9 个纯数据模块（被 database.py 延迟导入），
    # 逐条钉死进打包面，否则打包后运行期 ModuleNotFoundError 而本地全绿。
    data_dict_modules = {
        "core_dict",
        "core_dict_ext",
        "prep_dict",
        "a1_dict",
        "a1_writing_dict",
        "a1_hoeren_dict",
        "a1_lesen_dict",
        "corpus_dict",
        "encounter_seed_dict",
        # ADR-0011 Task 1：A1 工作台词库单一真相（被 database.py 延迟导入），
        # 漏登记 = 打包后 ModuleNotFoundError 而本地 pytest 全绿。
        "a1_workbench_dict",
        # R8 交付 1：本分支新增两片，均住 delector/data/，与其它数据模块同口径
        # （前缀 delector.data.）逐条钉进打包面 —— 漏登记 = 打包后 ModuleNotFoundError
        # 而本地 pytest 全绿。official_vocab=官方歌德词表分片；lexicon_merge=字段级
        # 合并共享纯函数（被 delector.core.lexicon 与 core_dict 共用）。
        "official_vocab",
        "lexicon_merge",
        # Phase 2 · S1：富字段 side-car 分片 official_vocab_rich（ipa/例句），
        # 同口径逐条钉进打包面 —— 漏登记 = 打包后 ModuleNotFoundError 而本地全绿。
        "official_vocab_rich",
        "a1_fragments",
        "a1_sidecar",
        # Task 4（rektion）：a1_verb_case 被 services/writing.py 静态导入 —— 漏登记 = 打包后 ModuleNotFoundError。
        "a1_verb_case",
    }
    # Phase 1 Task 4：8 个 routes_*.py 收进 delector.routes/ 子包，`routes_` 前缀由
    # 包路径取代（delector.routes_a1 → delector.routes.a1）。漏改打包清单 =
    # 打包后 ModuleNotFoundError，而本地 pytest 全绿，只能靠这条断言挡住。
    route_modules = {
        "a1",
        "a2",
        "a1_hoeren",
        "a1_lesen",
        "corpus",
        "sync",
        "rtc",
        "exam",
        "listen",
        "syntax_hard",
        "main",
        "tools",
    }
    # Phase 1 Task 5：4 个服务模块收进 delector.services/ 子包（edge_tts_mini →
    # services.tts，monkeypatch 契约同步迁到 delector.services.tts，不再有顶层 shim）
    # Task 3：listen 服务（听写诊断/填空引擎）与路由同步进打包面。
    # Task 3（长难句）：syntax_score 服务（句子难度评分）与 syntax_hard 路由同步进打包面。
    # Task 3（LLM 收口）：llm_client 服务（唯一出网口）与路由同步进打包面 —— 本批次新增，
    # 集合是硬编码的，不登记 ⇒ 这条守卫对新模块永久失明（本地全绿、打包后 ModuleNotFoundError）。
    # Task 4（循环内核）：polish_loop 服务（验证驱动 agent 循环内核）与路由同步进打包面 —— 本批次新增，
    # 集合是硬编码的，不登记 ⇒ 这条守卫对新模块永久失明（本地全绿、打包后 ModuleNotFoundError）。
    # Task 5（工具白名单）：polish_tools 服务（任务级白名单 + 前置钩子，同进程直调）同步进打包面 ——
    # 同上：集合硬编码，不登记 ⇒ 守卫对它永久失明。
    service_modules = {
        "writing",
        "essay_diff",
        "exam_catalog",
        "tts",
        "listen",
        "syntax_score",
        "llm_client",
        "polish_loop",
        "polish_tools",
    }
    top_level_modules: set[str] = set()
    required_modules = sorted(data_dict_modules | route_modules | service_modules | top_level_modules)

    def _mod_prefix(mod: str) -> str:
        if mod in data_dict_modules:
            return "delector.data."
        if mod in route_modules:
            return "delector.routes."
        if mod in service_modules:
            return "delector.services."
        return "delector."

    for mod in required_modules:
        hidden = f"--hidden-import={_mod_prefix(mod)}{mod}"
        # 1. Windows PyInstaller
        assert hidden in pkg, f"{mod} 未在 package_windows.py 的 --hidden-import 中注册"
        # 2. Linux & macOS CI PyInstaller
        assert wf.count(hidden) >= 2, (
            f"{mod} 未在 build-release.yml Linux/macOS 的 --hidden-import 中完整注册 (count={wf.count(hidden)})"
        )
    # 3. Android Chaquopy：Phase 2 后整目录拷入。再逐个 cp 扁平 .py 会漏模块 ——
    #    v5.3.0 实际漏过 routes_a2.py（server.py:233 静态 import 它），整目录拷贝修掉它。
    assert "cp -r start.py" in wf, "Android 应单独拷贝入口 start.py"
    assert "cp -r delector" in wf, "Android 应整目录拷入 delector/（覆盖全部 26 个业务模块）"

    critical_apk_needles = [
        "delector/server.py",
        "de_core_news_sm",
        "delector/routes/corpus.py",
        "delector/routes/a1_hoeren.py",
        "delector/routes/a1_lesen.py",
        "delector/routes/rtc.py",
        "delector/routes/exam.py",
        "delector/routes/listen.py",
        "delector/routes/syntax_hard.py",
        "delector/services/listen.py",
        "delector/services/syntax_score.py",
        "delector/services/exam_catalog.py",
        # Task 4（循环内核）：polish_loop 服务进 APP_NEEDLES 验包探针 —— 与
        # services/listen|syntax_score|exam_catalog 同口径（Android 由 `cp -r delector`
        # 整目录拷入覆盖，这里钉住「产物里真有」这一环）。
        "delector/services/polish_loop.py",
        # Task 5（工具白名单）：polish_tools 服务同口径进 APP_NEEDLES 验包探针。
        "delector/services/polish_tools.py",
        "delector/routes/a2.py",
    ]
    for needle in critical_apk_needles:
        assert f'"{needle}"' in wf, f"{needle} 未在 build-release.yml 的 APP_NEEDLES 验包探针中"

    spec_path = os.path.join(root, "DeLector.spec")
    if os.path.exists(spec_path):
        spec = open(spec_path, encoding="utf-8").read()
        for mod in required_modules:
            assert f"'{_mod_prefix(mod)}{mod}'" in spec, f"{mod} 未在 DeLector.spec 的 hiddenimports 中注册"


def test_preset_processed_data_registered_in_all_packaging_targets():
    """子计划 2A：预置文章预生成数据文件必须在**三个**打包位点显式纳入，且产物验收闸有断言。

    为什么不能只靠 `--hidden-import`：那只收 `.py` —— `delector/data/preset_processed.json`
    是数据文件，MUST 用 `--add-data` 显式纳入；否则产物里没有它，运行时会**静默降级**成纯
    Python 口径（「列表 A2 → 点进去 A1」跳变复发），而本地 pytest 全绿（同 v4.8.1 / v5.2.0
    的漏模块事故同款失效面）。

    Android 端（DEV-RULES §2.4 第③端）由 `build-release.yml` 的 `cp -r delector` 整目录拷贝覆盖
    ——`preset_processed.json` 就在 `delector/` 目录下，随整目录进 APK，故**无需**单独声明。
    """
    root = ROOT
    needle = "delector/data/preset_processed.json"

    # 断言的是「PyInstaller 命令里真有一行 --add-data 引用了这个数据文件」，而非只是常量定义在场
    # —— 否则删掉 add-data 那行、只留常量，纯子串断言仍会绿（本守卫会被绕过）。
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert any("--add-data" in line and "PRESET_PROCESSED_DATA_REL" in line for line in pkg.splitlines()), (
        "package_windows.py 未在 PyInstaller 命令里用 --add-data 纳入预生成数据文件（Windows 位点）："
        "漏收 ⇒ 产物静默降级为纯 Python 口径，本地全绿"
    )
    assert needle in pkg, "package_windows.py 缺少预生成数据文件的相对路径常量 PRESET_PROCESSED_DATA_REL"

    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert wf.count(needle) == 2, (
        f"build-release.yml 应在 Linux / macOS 两个 PyInstaller 位点各纳入一次 (count={wf.count(needle)})"
    )
    # Android 覆盖：整目录拷贝（与四端打包同步守卫同款依据）。
    assert "cp -r delector" in wf, "Android 端需整目录拷入 delector/ 才能带上该数据文件"

    verify = open(os.path.join(root, "tools", "verify_windows_portable.py"), encoding="utf-8").read()
    assert needle in verify, "verify_windows_portable.py 缺少对预生成数据文件的**真产物**断言"
    assert "missing_data_files" in verify, (
        "verify_windows_portable.py 必须真扫产物、缺数据文件即 FAIL（这是「只在真产物上才能发现」的闸）"
    )


def _workflow_job_segment(workflow: str, job: str) -> str:
    """截取 workflow 中某个 job 的文本段（从 `  <job>:` 头到下一个 `  <name>:` 头）。

    为什么按 job 头切片而非只 `wf.count(...)`：只数出现次数不钉"落在哪个 job" —— 把安装整体
    挪到 Linux job 里，count 仍是 1、断言照样绿。切片后即可断言"Windows 段含、Linux/macOS 段不含"。
    job 头缩进恰好 2 空格（其 body 至少 4 空格），故 `^  name:` 只会命中 job 边界。
    """
    header = re.compile(rf"^  {re.escape(job)}:\s*$", re.M).search(workflow)
    assert header is not None, f"build-release.yml 缺 job {job!r}"
    boundary = re.compile(r"^  [A-Za-z0-9_-]+:\s*$", re.M).search(workflow, header.end())
    return workflow[header.start() : boundary.start() if boundary else len(workflow)]


def test_windows_portable_entry_is_desktop_shell_and_isolates_desktop_deps():
    """Windows 便携包入口改为桌面壳 `desktop.py`，且桌面依赖只在 Windows 位点安装。

    为什么入口要换成 desktop.py：Task 4 的 pywebview 桌面壳（窗口 + 托盘）才是"双击 exe"
    该有的形态；旧的 `start.py` 只起服务 + 开浏览器，不是桌面应用。

    为什么桌面依赖**不并** requirements.txt：`import webview` 在缺 GTK/WebKit 的 Linux 上
    直接抛异常 —— 一旦进公共依赖面，CI 在 Linux 装依赖 / 收集测试就会炸，而这与桌面壳
    的正确性无关。故桌面依赖独占 `requirements-desktop.txt`，且**只允许** Windows 位点安装。

    为什么不但数次数（见 `_workflow_job_segment`）：`wf.count(...) == 1` 不钉"落在哪个 job"，
    把安装整体挪到 Linux job 仍绿。故额外钉 job 边界：build-windows 段必须含、build-linux /
    build-macos 段必须不含。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()
    wf = open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()

    assert "desktop.py" in pkg, "Windows 便携包入口必须是桌面壳 desktop.py"
    assert '"start.py"' not in pkg, "入口已改为 desktop.py，不得残留旧的 start.py 入口"

    # count==1 钉"只装一次"；job 边界钉"装对了 job"（二者缺一都能被绕过）。
    assert wf.count("requirements-desktop.txt") == 1, (
        "requirements-desktop.txt 只允许在 Windows 位点安装一次"
        "（Linux/macOS 装了会因缺 GTK/WebKit 崩，且与桌面壳正确性无关）"
    )
    assert "pip install -r requirements-desktop.txt" in _workflow_job_segment(wf, "build-windows"), (
        "build-windows 位点缺桌面依赖安装步骤"
    )
    for job in ("build-linux", "build-macos"):
        assert "requirements-desktop.txt" not in _workflow_job_segment(wf, job), (
            f"{job} 不得安装桌面依赖：Linux/macOS 缺 GTK/WebKit，装了必崩且与桌面壳无关"
        )

    # 依赖隔离反向钉：requirements.txt 必须零桌面依赖（防被顺手合并）。
    # pillow 同为桌面独占（pystray 生成托盘图标用），一并纳入黑名单。
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    for dep in ("pywebview", "pystray", "pythonnet", "pillow"):
        assert dep not in req, f"{dep} 不得进 requirements.txt：会污染 Linux/Android 依赖面"


def test_windows_portable_declares_webview2_freeze_items():
    """打包冻结项：按 pywebview 官方 PyInstaller 建议收集 webview 包 + Windows 平台后端。

    漏收 ⇒ `webview.platforms.winforms` / `edgechromium` 在冻结后 import 失败，exe 起得来
    却拉不起窗口（白屏 / 直接崩），而本地 pytest 全绿。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    for needle in (
        "--collect-all=webview",
        "--hidden-import=webview.platforms.edgechromium",
        "--hidden-import=webview.platforms.winforms",
        "--hidden-import=pystray._win32",
    ):
        assert needle in pkg, f"{needle} 未在 package_windows.py 的冻结项中"


def test_windows_portable_builds_windowed_with_brand_icon():
    """Windows 便携包必须 `--windowed` + `--icon=assets/DeLector.ico`，且**不得**再 `--console`。

    黑框根因：服务是同进程非 daemon 线程（没有子进程），`--console` 让每次双击都多弹一个
    控制台窗口 —— 用户以为"多开了 PowerShell"。stdout/stderr 已由 ensure_streams 收口到
    launch.log（提交 3217161），控制台不再承担"看服务日志与 IP"的职责；无控制台下的失败
    改走原生弹窗 / 托盘提示，故 `--console` 必须退役为 `--windowed`。`--icon` 缺省时 exe
    用 PyInstaller 默认图标，与 DeLector 品牌不一致，故显式挂 assets/DeLector.ico。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "--windowed" in pkg, "Windows 打包必须 --windowed：双击 DeLector.exe 不应再弹出控制台黑框"
    assert "--console" not in pkg, (
        "不得再出现 --console：stdout/stderr 已由 ensure_streams 收口到 launch.log，"
        "留着 --console 等于每次双击多弹一个黑框（服务是同进程线程，没有子进程需要它）"
    )

    icon_lines = [ln for ln in pkg.splitlines() if "--icon=" in ln]
    assert icon_lines, "打包命令缺 --icon=：exe 会用 PyInstaller 默认图标而非 assets/DeLector.ico"
    for ln in icon_lines:
        assert "DeLector.ico" in ln and "assets" in ln, (
            f"--icon= 必须指向 assets/DeLector.ico，实际：{ln.strip()}"
        )
        assert "root_dir" in ln, (
            f"图标路径必须与 --add-data 同口径经 root_dir 构造（打包机目录不定），实际：{ln.strip()}"
        )


def test_windows_portable_declares_webview2_payload_verification():
    """Windows 便携包必须**构建后自检** WebView2 运行时 DLL，且缺了就**硬失败**。

    为什么这是"最能防事故"的一条：pywebview 走系统 Edge WebView2，一旦打包漏收
    WebView2Loader.dll / Microsoft.Web.WebView2*.dll，exe 能起、窗口却**白屏**（无报错弹窗）
    —— 与 v4.8.1（routes_corpus 漏） / v5.2.0（routes_rtc/exam 漏）同款的"本地全绿、
    打包后静默失败"。故断言：① 自检函数存在；② 所需 DLL 清单完整登记（删一项即白屏）；
    ③ 缺失走**非零退出**（不是打印警告）；④ 文案点名"白屏"，让后人看懂为何不能删。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "verify_webview2_payload" in pkg, "缺构建后自检函数：漏收 WebView2 DLL 会白屏而无人发现"
    assert "assert_webview2_payload" in pkg, "缺「缺失即失败」的执行入口（自检与失败处置分离更好测）"

    for needle in ("WebView2Loader.dll", "Microsoft.Web.WebView2"):
        assert needle in pkg, f"WebView2 DLL 清单缺 {needle!r}：漏了它 exe 就白屏"

    assert "白屏" in pkg, "失败文案必须点明后果（白屏），否则后人会把自检当噪音删掉"


def test_verify_webview2_payload_reports_missing_dlls_recursively(tmp_path):
    """行为级：递归 + 大小写不敏感地查 WebView2 DLL；缺谁就精确点名谁。

    产物里 DLL 落在 `_internal/webview/lib/` 之类的**子目录**，只扫顶层会漏判 ⇒ 白屏放行。
    """
    import package_windows

    nested = tmp_path / "_internal" / "webview" / "lib"
    nested.mkdir(parents=True)
    (nested / "webview2loader.dll").write_bytes(b"")  # 小写：大小写不敏感
    (nested / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"")
    assert package_windows.verify_webview2_payload(str(tmp_path)) == [], "齐全时不得误报缺失"

    (nested / "Microsoft.Web.WebView2.Core.dll").unlink()
    missing = package_windows.verify_webview2_payload(str(tmp_path))
    assert missing == ["Microsoft.Web.WebView2"], f"缺失清单必须精确点名，实际 {missing}"


def test_assert_webview2_payload_hard_fails_when_dll_missing(tmp_path):
    """缺 DLL ⇒ **非零退出**（`SystemExit`），绝不能只打印警告就放行。

    这是本任务的核心守卫：自检**必须真的会让构建失败**，否则白屏包照样发布。
    """
    import package_windows

    with pytest.raises(SystemExit) as excinfo:
        package_windows.assert_webview2_payload(str(tmp_path))

    assert excinfo.value.code != 0, "缺 WebView2 DLL 时必须非零退出（构建失败）"


def test_assert_webview2_payload_passes_when_dlls_present(tmp_path):
    """齐全 ⇒ 不抛、正常返回（否则每次正常构建都会被自己的自检拒掉）。"""
    import package_windows

    (tmp_path / "WebView2Loader.dll").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"")

    package_windows.assert_webview2_payload(str(tmp_path))  # 不抛即通过


def test_verify_webview2_payload_requires_a_dll_suffix(tmp_path):
    """同名 `.xml`/`.pdb` 不得冒充 DLL：只收集到 `Microsoft.Web.WebView2.Core.xml` 时仍判缺失。

    为什么必须锚定 `.dll`：产物常伴同名 `.xml`/`.pdb`，只做子串匹配会被同伴文件名命中 ⇒ 真漏收
    DLL 却**假绿**，白屏包照样发布。
    """
    import package_windows

    (tmp_path / "WebView2Loader.dll").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.xml").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.pdb").write_bytes(b"")

    missing = package_windows.verify_webview2_payload(str(tmp_path))

    assert missing == ["Microsoft.Web.WebView2"], f"只有同名 .xml/.pdb 时仍须判缺失，实际 {missing}"


def test_build_windows_actually_invokes_webview2_payload_check():
    """`assert_webview2_payload(...)` 的调用点 MUST 落在 `build_windows()` 函数体内。

    为什么用 AST 钉调用点而非只查函数名出现在源码里：现有守卫只断言"函数名 / DLL 名 / '白屏'
    字样在源码中"，把 `build_windows()` 里那行调用删掉，闸就**失效**而全套测试仍绿。AST 把
    "定义存在"提升为"真的在构建路径上被调用"，删调用即红（本轮已做变异自证）。
    """
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "assert_webview2_payload"), (
        "build_windows() 内必须真调用 assert_webview2_payload()：否则验包闸形同虚设（删调用全套仍绿）"
    )


def test_windows_portable_readme_matches_desktop_entry():
    """产物《说明_README.txt》必须与入口一致：双击=桌面窗口、手机访问=`--server-only`。

    防"入口改了、文案没跟"的文档漂移：否则用户会照着 README 找一个已不存在的"默认浏览器"启动方式。
    """
    import package_windows

    readme = package_windows.release_readme("v9.9.9")

    assert "桌面窗口" in readme, "README 必须点明双击 DeLector.exe 打开的是桌面窗口"
    assert "--server-only" in readme, "README 必须告诉用户手机/平板访问要走 --server-only"
    assert "默认浏览器" not in readme, "入口已改为桌面窗口，README 不得再写'默认浏览器'"


def test_readme_generation_is_wired_into_build_windows():
    """`build_windows()` 必须把 `release_readme(...)` 的文本写进产物 README（防守卫与被写文本脱钩）。"""
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "release_readme"), (
        "build_windows() 必须调用 release_readme() 生成产物文案，否则守卫测的不是真正的产物内容"
    )


# ---------------------------------------------------------------------------
# GET /api/cards/counts：只数个数的轻量端点（2026-10-03 Task 2）
# ---------------------------------------------------------------------------


def _insert_grammar_card(**over: object) -> int:
    """直插一行 grammar_cards（照 `test_due_cards_grammar_branch_untouched` 的手法）。

    最小必填列：sentence_context / grammar_name / cefr_level / explanation_zh。
    """
    row: Dict[str, Any] = {
        "sentence_context": "Er geht nach Hause.",
        "grammar_name": "Akkusativ",
        "cefr_level": "A1",
        "explanation_zh": "第四格带冠词的定语从句",
    }
    row.update(over)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO grammar_cards "
            "(sentence_context, grammar_name, cefr_level, explanation_zh, mastered, due_date) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (
                row["sentence_context"],
                row["grammar_name"],
                row["cefr_level"],
                row["explanation_zh"],
                row.get("mastered", 0),
            ),
        )
        return int(cur.lastrowid or 0)


def test_card_counts_empty_db_returns_zero_not_null(client):
    """① 空库 ⇒ 五个字段全为 ``0``；**尤其 mastered 必须是 ``0`` 而不是 ``null``**。

    ``SUM(mastered = 1)`` 在空表上返回 ``NULL``（不是 ``0``）⇒ 若端点不写 ``or 0``，
    本用例必红。``null`` 会顺着 ``${n} 张卡`` 的模板串渲染成字面量 ``null张卡``。

    修复前本请求 404（端点不存在）⇒ 端点一旦落地，此用例即钉住「诚实留 0」。
    """
    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    data = res.json()
    for key in ("vocab_total", "vocab_mastered", "grammar_total", "grammar_mastered", "total"):
        assert key in data, f"计数端点缺字段 {key}：前端角标会渲染出 undefined"
        assert data[key] == 0, f"空库时 {key} MUST 为 0，实际 {data[key]!r}（null 会渲染成字面量 null）"


def test_card_counts_reports_per_table_totals_and_mastered(client):
    """② 2 张 vocab（1 张 ``mastered=1``）+ 1 张 grammar（``mastered=0``）⇒ 逐字段断言。

    非空基线：若端点返回全 0（假绿），本用例会红；``total`` 另钉「两表之和」。
    """
    _insert_vocab_card(word="Haus", lemma="haus", mastered=0)
    _insert_vocab_card(word="Baum", lemma="baum", mastered=1)
    _insert_grammar_card(grammar_name="Akkusativ", mastered=0)

    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    data = res.json()
    assert data["vocab_total"] == 2, f"vocab_total 应为 2，实际 {data['vocab_total']!r}"
    assert data["vocab_mastered"] == 1, f"vocab_mastered 应为 1，实际 {data['vocab_mastered']!r}"
    assert data["grammar_total"] == 1, f"grammar_total 应为 1，实际 {data['grammar_total']!r}"
    assert data["grammar_mastered"] == 0, f"grammar_mastered 应为 0，实际 {data['grammar_mastered']!r}"
    assert data["total"] == 3, f"total 应为两表之和 3，实际 {data['total']!r}"


def test_card_counts_does_not_run_fsrs_next_intervals(client, monkeypatch):
    """③ 计数端点 **MUST NOT** 做逐卡 FSRS 递推（端点存在的全部理由）。

    ``GET /api/cards`` 对每张卡跑 ``get_fsrs_next_intervals``；计数端点只要两个整数，
    递推纯属浪费。把模块属性换成抛异常的桩后仍 MUST 200。

    端点改成 ``SELECT *`` 再取 ``len`` ⇒ 桩被调用 ⇒ 本用例必红。
    """
    from delector.routes import main as routes_main

    def _boom(*args: object, **kwargs: object):
        raise AssertionError("计数端点调用了 get_fsrs_next_intervals：它只数个数，不该逐卡递推 FSRS")

    monkeypatch.setattr(routes_main, "get_fsrs_next_intervals", _boom)
    _insert_vocab_card(word="Haus", lemma="haus", mastered=1)

    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    assert res.json()["vocab_total"] == 1


# ── AI 润色循环（Task 6）：返回契约 / 适用性闸门 / 流式进度 / 断连取消 ───────────
_ESSAY_TEXT = "Ich habe ein Hund. Er ist gut."
# 书信体夹具：正文首词小写已对，但结语后带逗号 ⇒ 恰好 1 条 error（裁判有话可说）。
_LETTER_TEXT = "Liebe Maria,\nich lade dich ein.\nViele Grüße,\nAnna"


class _ScriptedChat:
    """`llm_client.chat` 的脚本桩：逐轮按顺序回复（脚本用完后重复最后一条）。"""

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        self.script = script
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        return self.script[idx] if idx < len(self.script) else self.script[-1]

    def contents(self) -> List[str]:
        """所有轮次里出现过的消息正文（用于断言「证据被回喂给了模型」）。"""
        out: List[str] = []
        for call in self.calls:
            for msg in call.get("messages", []):
                content = msg.get("content")
                if isinstance(content, str):
                    out.append(content)
        return out


def _stub_api_key(monkeypatch: Any) -> None:
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-stub")


def _parse_sse(raw: str) -> List[Dict[str, Any]]:
    """把 SSE 文本解析成事件列表（帧以空行分隔，只认 `data:` 行）。"""
    events: List[Dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        lines = [ln for ln in frame.split("\n") if ln.startswith("data:")]
        if not lines:
            continue
        events.append(json.loads(lines[0][len("data:") :].strip()))
    return events


def test_ai_polish_response_carries_convergence_contract(client, monkeypatch):
    """只增不改：两个端点的 `result` 新增 converged / unconverged_reason，既有字段不动。"""
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"], "error_count": 1}]
    )
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["corrected_text"] == "Ich habe einen Hund. Er ist gut."
    assert result["notes_zh"] == ["ein → einen"]
    # error_count 今天仍是**模型报的数**（既有断言 test_ai_polish_diff_mocked 的口径），
    # 换成裁判口径会静默破坏既有契约。
    assert result["error_count"] == 1
    assert result["converged"] is True
    assert result["unconverged_reason"] is None

    diff = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT}).json()["result"]
    assert diff["original"] == _ESSAY_TEXT
    assert diff["corrected"] == "Ich habe einen Hund. Er ist gut."
    assert diff["hunks"], "diff 端点仍要给出逐句 hunk（既有逐 hunk 采纳 UI 依赖它）"
    assert diff["converged"] is True
    assert diff["unconverged_reason"] is None


def test_ai_polish_no_key_reports_endpoint_level_reason(client, monkeypatch):
    """无 Key ⇒ 循环**根本没跑** ⇒ 端点层原因码 `no_api_key`（不进 REASONS）。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["corrected_text"] == "Hallo."
    assert "DeepSeek API Key" in result["notes_zh"][0]
    assert result["error_count"] == 0
    assert result["converged"] is False
    assert result["unconverged_reason"] == "no_api_key"
    assert "no_api_key" not in polish_loop.REASONS, (
        "no_api_key 是端点层原因码（循环没跑），混进 REASONS 会让「原因码 = 循环出口」这条契约失真"
    )


def test_ai_polish_non_letter_grammar_error_is_counted_by_the_loop(client, monkeypatch):
    """★ Task 7 闸门收窄（**三态死绿守卫的改写其一**）：非书信体 + 语法错 ⇒ 语法违规**真被计数**。

    场景：桩模型改了措辞但**不修**冠词错（`ein Hund` 原样保留）⇒ v_0 == v_1 == 1 ⇒
    `no_improvement`（语法违规进了 v 才会发生）。

    判别力（变异自证②）：把闸门改回"非书信体一律零违规" ⇒ v_0 == v_1 == 0 ⇒ 首轮即收敛
    ⇒ 本用例 MUST 红 —— 旧闸门下的行为就是"零违规"，本用例的存在即"真被计数"与它的对比。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe ein Hund. Er ist sehr lieb.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["converged"] is False, "非书信体的语法违规 MUST 被计数（否则修不动也会被判收敛）"
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")
    assert result["judge_degraded"] is False


def test_ai_polish_non_letter_unfixable_falls_back_to_original(client, monkeypatch):
    """★ 产品语义钉子（**三态死绿守卫的改写其二**；ADR §10.3 的落点，MUST 有断言）：
    非书信体语法错**修不动** ⇒ 回退**原文**（**不是**"首轮即接受"）。

    这是闸门收窄后的**明知而接受**的行为（2026-10-15 用户拍板；同款登记在
    `violations_for` 与 `_make_judge` 的 docstring）：循环按 Task 4 钉死的
    `no_improvement` 语义走 argmin ⇒ 原文；用户拿到的人话是前端
    `POLISH_REASON_COPY.no_improvement`（"AI 改了几轮仍没能减少硬性错误，已保留更接近原文的一版。"）。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe ein Hund. Er ist sehr lieb.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["corrected_text"] == _ESSAY_TEXT, "修不动 ⇒ 按循环语义回退原文（不是首轮即接受）"
    assert result["converged"] is False
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")


def test_ai_polish_letter_text_still_judged_by_a1_rules(client, monkeypatch):
    """反向对照：书信体**不受**闸门豁免 ⇒ 改不动就照旧回退原文并给 no_improvement。

    少了这条，「闸门一律返回 []」也能让上一条变绿 —— 那等于把裁判整个关掉。
    """
    _stub_api_key(monkeypatch)
    # 改了用词但没修结语逗号 ⇒ v_1 == v_0 == 1 ⇒ 不降即停
    chat = _ScriptedChat([{"corrected_text": "Liebe Maria,\nich lade dich herzlich ein.\nViele Grüße,\nAnna"}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    result = client.post("/api/writing/ai-polish", json={"text": _LETTER_TEXT}).json()["result"]

    assert result["corrected_text"] == _LETTER_TEXT, "书信体改不动 ⇒ 回退原文（闸门必须对它失效）"
    assert result["converged"] is False
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable")


# ── Task 1/2 评审 RED#1 闭环：端点级接线回归 + 引擎降级诚实性 ──────────────────
# 书信体 + 冠词格错（"ein Hund" → "einen Hund"）的文本夹具。
# 用**书信体**而非非书信体：RED#1 只要求"证明接缝是活的"，书信体已足够 ——
# 且能把本用例与 Task 7（HITL）的闸门收窄彻底解耦（非书信体的语法计数属 Task 7，此处不碰）。
# 该文本无任何**格式/字数族 error**（称呼语合法、正文首词小写、结语无逗号）
# ⇒ 不接 nlp 时 v_0 == 0（这是本用例能判死"没接线"的前提）。
_GRAMMAR_LETTER_TEXT = "Liebe Maria,\nich habe ein Hund.\nViele Grüße\nAnna"


def _real_nlp_or_skip() -> Any:
    """加载真模型（沿用 `tests/test_writing_rules.py` 的 nlp fixture 惯例）；缺失 ⇒ skip。"""
    import spacy

    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


def test_ai_polish_endpoint_counts_grammar_violations_on_letter_text(client, monkeypatch):
    """★ 评审 RED#1 闭环点：端点级接线回归 —— 生产链路 MUST 把语法裁判真的送进循环。

    用**书信体 + 冠词格错**文本（书信体 ⇒ 闸门不豁免 ⇒ 语法违规照常计数）：
    桩模型**不修**该冠词错 ⇒ v_0 == v_1 == 1 ⇒ `no_improvement`（断言形态①：语法违规真被计数）。
    若端点**不注入** `judge=`（退回内核默认裁判，不带 nlp）⇒ 语法违规静默消失，而该书信体文本
    又无格式 error ⇒ v_0 == v_1 == 0 ⇒ **首轮即收敛** ⇒ 本用例 MUST 红（这就是 dead-green 的判别力）。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    # 桩模型只改结尾措辞、**不修**冠词错 ⇒ 裁判应判「改不动」
    chat = _ScriptedChat(
        [{"corrected_text": "Liebe Maria,\nich habe ein Hund und freue mich.\nViele Grüße\nAnna", "notes_zh": ["x"]}]
    )
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)

    result = client.post("/api/writing/ai-polish", json={"text": _GRAMMAR_LETTER_TEXT}).json()["result"]

    assert result["converged"] is False, "带冠词格错的书信体文本不该被判为已收敛"
    assert result["unconverged_reason"] in ("no_improvement", "judge_unreliable"), (
        "语法违规 MUST 被计数（否则端点没把语法裁判送进循环 = dead-green）"
    )
    assert result["judge_degraded"] is False, "引擎可用 ⇒ judge_degraded 必须为 False"


def test_ai_polish_endpoint_reports_degraded_when_no_nlp(client, monkeypatch):
    """引擎不可用 ⇒ 循环**照常收敛**（运行期 fail-open），但 `judge_degraded` MUST 如实为 True。

    红线 1：不得让「没检查」看起来像「检查通过」⇒ 声明层 fail-closed 靠这个布尔透出。
    """
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    result = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT}).json()["result"]

    assert result["judge_degraded"] is True
    # 降级不阻止收敛（fail-open）：非书信体 + 无语法裁判 ⇒ 首轮即接受
    assert result["converged"] is True


def test_ai_polish_endpoint_surfaces_advisories_without_blocking_convergence(client, monkeypatch):
    """★ Task 6 HITL 收尾（B 维 advisory 可见性）：`judge_advisories` MUST 到达响应体，
    且 advisory **不阻断收敛** —— 判定与「去掉该句」逐字段相同。

    判别力（变异自证①）：把 advisory 的 level 改成 error ⇒ 它翻进 error 计数 ⇒
    v_0 == v_1 == 1 ⇒ no_improvement ⇒ 本用例的 `converged is True` 与
    `unconverged_reason is None` 断言 MUST 红。
    """
    nlp = _real_nlp_or_skip()
    _stub_api_key(monkeypatch)
    text_with = "Gestern gehe ich zur Schule."
    text_without = "Ich gehe zur Schule."

    # 桩模型「不修任何东西」：候选 = 原文 ⇒ 本用例只观察判定不受 advisory 影响。
    chat_with = _ScriptedChat([{"corrected_text": text_with, "notes_zh": []}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat_with)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: nlp)
    res_with = client.post("/api/writing/ai-polish", json={"text": text_with}).json()["result"]

    chat_without = _ScriptedChat([{"corrected_text": text_without, "notes_zh": []}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat_without)
    res_without = client.post("/api/writing/ai-polish", json={"text": text_without}).json()["result"]

    assert res_with["judge_advisories"], "B 维 advisory MUST 到达响应体（否则 warning 是 no-op）"
    assert all(isinstance(a, str) for a in res_with["judge_advisories"])
    assert any("过去" in a for a in res_with["judge_advisories"]), (
        f"advisory 文案应解释时间锚与时态冲突: {res_with['judge_advisories']}"
    )
    assert res_without["judge_advisories"] == [], "对照组不得有 advisory（防断言恒真）"
    assert res_with["converged"] is True and res_with["unconverged_reason"] is None
    assert res_with["judge_degraded"] is False
    # 「与去掉该句逐字相同」：advisory 不得进 error 计数、不得改变停止策略。
    assert (res_with["error_count"], res_with["converged"], res_with["unconverged_reason"]) == (
        res_without["error_count"],
        res_without["converged"],
        res_without["unconverged_reason"],
    ), "advisory 影响了判定（警告被当成错误计数？）"


def test_ai_polish_response_carries_judge_advisories_contract(client, monkeypatch):
    """响应契约（只增不改）：无 Key 路径也要带 `judge_advisories: []`（前端消费不炸）。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "")

    result = client.post("/api/writing/ai-polish", json={"text": "Hallo."}).json()["result"]

    assert result["judge_advisories"] == []
    assert result["judge_degraded"] is True


# ── Task 7：文本族感知的提示词参数化（立论冲突解法 b；业务知识住产品层）──────────


def test_pick_system_prompt_letter_vs_prose():
    """提示词选择：书信体 ⇒ 既有 A1 提示词**逐字**；散文 ⇒ 不含称呼语/结语指令。

    为什么散文版必须去书信指令（评审黄卡 #2）：内核里逐字 A1 书信指令对非书信体会
    **诱导模型加一个称呼语**，而格式族规则此时已被闸门关掉 ⇒ 污染无守卫。
    """
    from delector.routes.main import POLISH_PROSE_SYSTEM_PROMPT, pick_system_prompt

    letter_prompt = pick_system_prompt("letter")
    prose_prompt = pick_system_prompt("prose")

    assert letter_prompt == polish_loop.POLISH_LOOP_SYSTEM_PROMPT, "书信体 MUST 用既有 A1 提示词（逐字）"
    assert prose_prompt == POLISH_PROSE_SYSTEM_PROMPT, "散文体 MUST 用散文向提示词（产品层常量）"
    assert prose_prompt != letter_prompt
    assert "称呼语" not in prose_prompt and "结语" not in prose_prompt, "散文提示词不得含称呼语/结语指令"
    assert "逐句润色" in prose_prompt and "保持句子的结构与出现顺序" in prose_prompt, "diff 关键约束 MUST 保留"
    assert "corrected_text" in prose_prompt, "JSON 契约 MUST 保留（循环按它解析）"


def test_run_polish_passes_text_family_aware_system_prompt(monkeypatch):
    """装配点：`_run_polish` MUST 按文本族把系统提示词**真的送进循环**（否则参数化是死代码）。

    判别力（变异自证③）：`pick_system_prompt` 恒返回 A1 提示词 ⇒ 本用例第一条断言（散文
    提示词）MUST 红。
    """
    from delector.routes.main import POLISH_PROSE_SYSTEM_PROMPT, _run_polish

    captured: List[Dict[str, Any]] = []

    async def _fake_loop(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return polish_loop.LoopResult(text=kwargs["text"], converged=True, reason="ok", rounds=0, violations=[])

    monkeypatch.setattr("delector.services.polish_loop.run_polish_loop", _fake_loop)
    monkeypatch.setattr("delector.routes.main.get_effective_api_base_url", lambda: "http://stub")
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    essay = "Ich habe ein Hund. Er ist gut."
    letter = "Liebe Maria,\nich lade dich ein.\nViele Grüße\nAnna"
    asyncio.run(_run_polish(essay, "sk-stub"))
    asyncio.run(_run_polish(letter, "sk-stub"))

    assert captured[0]["system_prompt"] == POLISH_PROSE_SYSTEM_PROMPT, (
        "非书信体 ⇒ 散文提示词 MUST 真送进循环（参数化不许是死代码）"
    )
    assert captured[1]["system_prompt"] == polish_loop.POLISH_LOOP_SYSTEM_PROMPT, "书信体 ⇒ 既有 A1 提示词"


def test_writer_js_surfaces_degraded_hint_and_advisories_without_toast():
    """前端生产者（评审黄卡的闭环）：`judge_degraded` / `judge_advisories` MUST 被
    writer.js 消费，且走 **overlay notes 区的非阻断呈现**（Global Constraints 明说
    "不是 error toast"）。

    与 `test_frontend_polish_reason_copy_covers_every_reason_code` 同为源码级守卫：
    后端加了字段而前端不渲染 ⇒ 字段等于没加（这正是评审黄卡点名的"无生产者"）。

    no-key 抑制（评审黄卡 Y3 的闭环）：no-key 路径**循环根本没跑**（`_no_key_outcome`
    什么都没检查）⇒ 降级提示里"本次仅做格式/字数检查"不实 ⇒ `unconverged_reason ==
    "no_api_key"` 时 MUST 抑制该提示（no-key 已有自己的 toast / notes 文案，抑制不丢信息）。
    """
    src = open(os.path.join(ROOT, "static", "js", "writer.js"), encoding="utf-8").read()
    assert "judge_advisories" in src, "writer.js MUST 消费 judge_advisories（advisory 可见性）"
    assert "judge_degraded" in src, "writer.js MUST 消费 judge_degraded（降级可见性）"

    render_block = src[src.index("export function renderPolishReview") : src.index("// ── AI 润色：未收敛原因码")]
    assert "polishState.judge_advisories" in render_block, "advisory MUST 在 renderPolishReview 里逐条呈现"
    assert "polishState.judge_degraded" in render_block, "降级提示 MUST 在 renderPolishReview 里呈现"
    assert "语法检查未启用" in render_block, "降级提示 MUST 是一句可见的人话（非阻断，不是 toast）"
    assert (
        "polishState.judge_degraded && polishState.unconverged_reason !== 'no_api_key'" in render_block
    ), "no-key 路径循环根本没跑 ⇒ 提示 MUST 受 unconverged_reason 守卫（否则'仅做格式/字数检查'不实）"

    # 生产侧（抑制条件的输入）：响应装配 MUST 把 unconverged_reason 存进 polishState
    assign = src[src.index("const { original, corrected, hunks, notes_zh"):]
    assert "unconverged_reason" in assign[: assign.index("};")], (
        "polishState MUST 携带 unconverged_reason（no-key 抑制分支的输入）"
    )


def test_get_loaded_nlp_is_read_only(monkeypatch):
    """`get_loaded_nlp()` 只读已加载模型：未解析/加载失败 ⇒ None，且**绝不触发加载**。"""
    from delector.nlp_engine import processor

    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)
    calls = {"n": 0}

    def _spy(name: str) -> Any:
        calls["n"] += 1
        raise RuntimeError("不应被调用")

    monkeypatch.setattr(processor, "_load_spacy_model", _spy)

    assert processor.get_loaded_nlp() is None
    assert calls["n"] == 0, "get_loaded_nlp 不得触发任何加载"

    sentinel = object()
    monkeypatch.setattr(processor, "_nlp_resolved", True)
    monkeypatch.setattr(processor, "_nlp_model", sentinel)
    assert processor.get_loaded_nlp() is sentinel


def test_try_load_nlp_no_download_loads_locally(monkeypatch):
    """本地能加载 ⇒ 写入既有缓存（`_nlp_model` / `_nlp_resolved=True`）并返回模型。"""
    from delector.nlp_engine import processor

    sentinel = object()
    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)
    monkeypatch.setattr(processor, "_load_spacy_model", lambda name: (sentinel, f"{name}(stub)"))

    assert processor.try_load_nlp_no_download() is sentinel
    assert processor.get_loaded_nlp() is sentinel


def test_try_load_nlp_no_download_never_downloads(monkeypatch):
    """★ 变异守卫：本地加载全失败 ⇒ MUST 返回 None，且**绝不**触发 `spacy.cli.download`。

    把 `try_load_nlp_no_download` 改成会走 download 的版本 ⇒ 本地加载既已失败，爆炸桩
    `spacy.cli.download` 会被命中 ⇒ 本用例红线。
    """
    from spacy import cli as spacy_cli

    from delector.nlp_engine import processor

    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_nlp_model", None)

    def _boom(name: str) -> Any:
        raise RuntimeError("no local model")

    monkeypatch.setattr(processor, "_load_spacy_model", _boom)

    def _bomb(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("try_load_nlp_no_download 绝不能触发 spacy.cli.download（出网 + pip）")

    monkeypatch.setattr(spacy_cli, "download", _bomb)

    assert processor.try_load_nlp_no_download() is None, "本地失败 ⇒ 诚实返回 None（不抛、不下载）"
    assert processor.get_loaded_nlp() is None, "失败 ⇒ 不写任何全局"


def test_ai_polish_runs_tool_hooks_on_the_real_path(client, monkeypatch, caplog):
    """前置钩子链 MUST 在**真链路**上被跑过（不是只在单测里）：审计留痕 + 证据回喂。"""
    import logging

    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [
            {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}},
            {"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"]},
        ]
    )
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    with caplog.at_level(logging.INFO):
        res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})

    assert res.status_code == 200
    audited = [r.getMessage() for r in caplog.records if "writing_check" in r.getMessage()]
    assert audited, f"审计钩子没在真链路上留下痕迹（logs={[r.getMessage()[:80] for r in caplog.records]}）"
    assert any(c.startswith("[工具结果:writing_check]") for c in chat.contents()), (
        "工具结果必须作为证据回喂给模型（证明 dispatch 走的是白名单真身）"
    )


def test_ai_polish_stream_emits_progress_then_full_result(client, monkeypatch):
    """`stream=true` ⇒ SSE：逐轮进度事件 + 收尾 `done` + 最后一条完整 result。

    TestClient 的传输层会把**整个响应**缓冲完再返回（starlette 1.6 的
    `_TestClientTransport.handle_request` 一次性跑完 ASGI app），故这里断言的是
    「帧序列正确」，不是「帧是增量到达的」——增量与断连由下一条用例直接驱动生成器覆盖。
    """
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat(
        [
            {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}},
            {"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["ein → einen"], "error_count": 1},
        ]
    )
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})

    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    events = _parse_sse(res.text)
    assert events, f"SSE 帧为空：{res.text[:200]!r}"
    assert events[-1]["event"] == "result", f"最后一条必须是完整 result：{events[-1]}"
    done = [e for e in events if e.get("event") == "done"]
    assert done and done[-1]["converged"] is True and done[-1]["reason"] == "ok"
    progress = [e for e in events if e.get("event") == "tool"]
    assert progress, "取证的那一轮必须吐进度事件"
    assert progress[0]["max_turns"] == polish_loop.MAX_TURNS_DEFAULT, "max_turns 必须由服务端给出（前端不许硬编码）"
    assert progress[0]["round"] >= 1
    payload = events[-1]["result"]
    assert payload["corrected"] == "Ich habe einen Hund. Er ist gut."
    assert payload["hunks"]
    assert payload["converged"] is True
    assert payload["unconverged_reason"] is None


def test_ai_polish_feedback_and_prose_routing(client: Any, monkeypatch: Any) -> None:
    """Task 4: 端到端路由接入与分流透传。

    散文体裁（prose）在多轮润色中：
    1. 发生违规时，SSE 流中吐出 event == "judge_feedback" 事件；
    2. 反馈内容严格遵循 text_type="prose" 过滤，绝不包含 a1_ 书信格式规则（如 a1_greeting_missing）；
    3. 模型依据反馈修正后，最终成功收敛 (converged=True, reason="ok")。
    """
    _stub_api_key(monkeypatch)

    chat = _ScriptedChat(
        [
            {"corrected_text": "Ich gehe nach Schule.", "notes_zh": ["in -> nach"]},
            {"corrected_text": "Ich gehe in die Schule.", "notes_zh": ["nach -> in die"]},
        ]
    )
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    def _fake_make_judge(leitpunkte: Any, nlp: Any) -> Any:
        def _judge(text: str) -> Dict[str, Any]:
            if "nach Schule" in text:
                return {
                    "word_count": 5,
                    "greeting": {"valid": True},  # 候选含格式特征，由 text_type="prose" 守门过滤
                    "violations": [
                        {"rule": "a1_greeting_missing", "level": "error", "message": "书信缺少称呼语"},
                        {"rule": "grammar_error", "level": "error", "message": "语法错误"},
                    ],
                }
            elif "in Schule" in text:
                # 原文基线：维持 prev_v >= 2，使首轮违规数不恶化并触发反馈机制
                return {
                    "word_count": 5,
                    "greeting": {"valid": False},
                    "violations": [
                        {"rule": "grammar_error", "level": "error", "message": "语法错误"},
                        {"rule": "spelling_mistake", "level": "error", "message": "拼写错误"},
                    ],
                }
            return {"word_count": 5, "greeting": {"valid": False}, "violations": []}

        return _judge

    monkeypatch.setattr("delector.routes.main._make_judge", _fake_make_judge)

    res = client.post("/api/writing/ai-polish", json={"text": "Ich gehe in Schule.", "stream": True})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse(res.text)
    assert events, f"SSE 帧为空：{res.text[:200]!r}"

    # a) In SSE stream, an event with event == "judge_feedback" is emitted.
    fb_events = [e for e in events if e.get("event") == "judge_feedback"]
    assert fb_events, f"SSE 流中必须包含 judge_feedback 事件，实际事件: {[e.get('event') for e in events]}"

    # b) The feedback content does NOT contain a1_ letter format rules (e.g. a1_greeting_missing).
    feedback = fb_events[0]["feedback"]
    assert "grammar_error" in feedback
    assert "a1_greeting_missing" not in feedback
    assert "a1_" not in feedback, f"散文体裁反馈中严禁包含 a1_ 规则：{feedback}"

    # c) Final result converges or completes successfully.
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events and done_events[-1]["converged"] is True and done_events[-1]["reason"] == "ok"
    assert events[-1]["event"] == "result"
    assert events[-1]["result"]["corrected_text"] == "Ich gehe in die Schule."
    assert events[-1]["result"]["converged"] is True


def test_ai_polish_stream_defaults_off_and_keeps_json(client, monkeypatch):
    """`stream` 默认关：不传就是既有 JSON 行为（既有测试逐字不变的前提）。"""
    _stub_api_key(monkeypatch)
    chat = _ScriptedChat([{"corrected_text": "Ich habe einen Hund. Er ist gut.", "notes_zh": ["x"]}])
    monkeypatch.setattr("delector.routes.main.llm_client.chat", chat)

    res = client.post("/api/writing/ai-polish", json={"text": _ESSAY_TEXT})

    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["result"]["corrected_text"] == "Ich habe einen Hund. Er ist gut."


def test_ai_polish_stream_cancels_loop_when_client_disconnects(monkeypatch):
    """客户端中途断开 ⇒ 服务端循环任务被 `cancel()`（不泄漏、不继续烧配额）。

    为什么不用 TestClient：它的传输层把整个响应缓冲完才返回（实测见上一条用例注释），
    `request.is_disconnected()` 在响应生成期间恒为 False（httpx 的 receive() 要等
    response_complete）⇒ 「中途断开」在 TestClient 下**物理上无法复现**。
    故这里直接驱动端点的流式生成器，配一个「第 2 轮 chat 卡住时才报已断开」的 Request 桩；
    其余链路（chat 桩、白名单、钩子、循环）全是真的。
    """
    gate = asyncio.Event()
    entered_second_call = asyncio.Event()
    state = {"calls": 0, "cancelled": False}

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            return {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}}
        entered_second_call.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return {"corrected_text": _ESSAY_TEXT}

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.routes.main.llm_client.chat", _chat)

    class _DisconnectedRequest:
        """仅提供端点用到的两个面：`client.host`（本机闸）与 `is_disconnected()`。"""

        client = type("Client", (), {"host": "127.0.0.1"})

        async def is_disconnected(self) -> bool:
            return entered_second_call.is_set()

    async def _drive() -> Dict[str, Any]:
        resp = await api_writing_ai_polish(AIPolishReq(text=_ESSAY_TEXT, stream=True), _DisconnectedRequest())

        async def _drain() -> str:
            raw = ""
            async for chunk in resp.body_iterator:
                raw += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            return raw

        # 上限 5s：取消逻辑被抽掉时生成器会永远轮询 ⇒ 宁可**红**也不要挂住整轮门禁。
        raw = await asyncio.wait_for(_drain(), timeout=5.0)
        # 快照必须在**事件循环关掉之前**取：asyncio.run() 收尾会顺手 cancel 掉所有
        # 未完成任务，那时再读 cancelled 恒为真 ⇒ 断言会变成假绿。
        return {
            "events": _parse_sse(raw),
            "cancelled": state["cancelled"],
            "calls": state["calls"],
        }

    snap = asyncio.run(_drive())

    assert snap["cancelled"] is True, "断开后服务端循环 MUST 被取消（否则继续烧配额）"
    assert snap["calls"] < polish_loop.MAX_TURNS_DEFAULT, (
        f"取消后不该继续跑满轮次：calls={snap['calls']} / max={polish_loop.MAX_TURNS_DEFAULT}"
    )
    assert all(e.get("event") != "result" for e in snap["events"]), "已断开就不该再产出完整 result"


def test_ai_polish_stream_cancels_loop_when_starlette_listener_preempts(monkeypatch):
    """starlette 的 `listen_for_disconnect` **抢先**取消生成器 ⇒ finally 同步收尸掐断在途 chat。

    与上一条用例的分工（为什么必须单开这条）：
    - 上一条直接迭代 `resp.body_iterator`，**绕开了** `StreamingResponse.__call__`
      ⇒ `listen_for_disconnect` 根本不参与，「监听器抢先 cancel 生成器」这条路
      物理上测不到；
    - 这里直接驱动 `StreamingResponse.__call__`：uvicorn 的 HTTP 协议栈（h11 /
      httptools impl，实测源码 `spec_version='2.3'`）⇒ starlette 1.6 的 `__call__`
      走 task-group 分支（`spec_version < (2, 4)`）：`stream_response` 与
      `listen_for_disconnect` **同时**跑。断连从监听器那条路进来：receive 第 2 次
      被调用 ⇒ 返回 `http.disconnect` ⇒ 监听器 break ⇒
      `task_group.cancel_scope.cancel()` ⇒ `stream_response` 里的生成器在 await 点
      被投递 `CancelledError` ⇒ 生成器的 `finally` 必须**同步** `task.cancel()`
      把在途 chat 掐断；
    - 生成器的 request 桩 `is_disconnected()` 恒 False：堵死「轮询自报断开」那条路，
      确保取消只能来自监听器 —— 把 `finally` 里的 `task.cancel()` 抽掉，本用例必红
      （变异自证）。
    """
    gate = asyncio.Event()
    entered_second_call = asyncio.Event()
    cancelled_seen = asyncio.Event()
    state = {"calls": 0, "cancelled": False}

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            return {"tool_call": {"name": "writing_check", "payload": {"text": _ESSAY_TEXT, "leitpunkte": []}}}
        entered_second_call.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            cancelled_seen.set()
            raise
        return {"corrected_text": _ESSAY_TEXT}

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.routes.main.llm_client.chat", _chat)

    class _NeverDisconnectedRequest:
        """生成器只用得到 `is_disconnected()`：恒 False ⇒ 取消只能来自 starlette 监听器。"""

        async def is_disconnected(self) -> bool:
            return False

    async def _drive() -> Dict[str, Any]:
        resp = StreamingResponse(
            _polish_event_stream(request=_NeverDisconnectedRequest(), text=_ESSAY_TEXT, with_diff=False),
            media_type="text/event-stream",
        )
        receive_calls = {"n": 0}

        async def receive() -> Dict[str, Any]:
            receive_calls["n"] += 1
            if receive_calls["n"] == 1:
                # 首条非断连消息：监听器只在拿到 http.disconnect 时才 break
                return {"type": "http.request", "body": b"", "more_body": False}
            # 第 2 次被调用才报断开 —— 但先等循环真的跑起来（第 2 次 chat 已卡在途），
            # 把取消钉在「流已开头、在途 chat 进行中」这个真实窗口，避开生成器还没
            # 起步的竞态窗口（那时取消可能整段跳过生成器体，finally 无从谈起）。
            await entered_second_call.wait()
            return {"type": "http.disconnect"}

        sent: List[Dict[str, Any]] = []

        async def send(message: Dict[str, Any]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/writing/ai-polish",
            "raw_path": b"/api/writing/ai-polish",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 51234),
            "server": ("127.0.0.1", 8000),
        }

        # 取消沿 task group 回传：resp(...) 可能原样抛出 CancelledError（starlette 用
        # create_collapsing_task_group 折叠单异常组），压掉即可 —— 断言看的是收尸效果。
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(resp(scope, receive, send), timeout=10.0)

        # finally 只同步 cancel、不 await：给事件循环节拍让取消真正传导到在途 chat。
        # 上限 5s：finally 的 cancel 被抽掉时在途 chat 会永远卡住 ⇒ 宁可红也不挂死门禁。
        try:
            await asyncio.wait_for(cancelled_seen.wait(), timeout=5.0)
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True

        bodies = b"".join(m.get("body", b"") for m in sent if m.get("type") == "http.response.body")
        return {
            "started": bool(sent) and sent[0].get("type") == "http.response.start",
            "receive_calls": receive_calls["n"],
            "frames": _parse_sse(bodies.decode("utf-8")),
            "cancelled": state["cancelled"],
            "calls": state["calls"],
            "timed_out": timed_out,
        }

    snap = asyncio.run(_drive())

    assert snap["started"], "stream_response 必须真跑过（证明驱动的是 StreamingResponse.__call__ 而非裸生成器）"
    assert snap["receive_calls"] >= 2, f"监听器必须真参与（receive 被调用次数={snap['receive_calls']}）"
    assert not snap["timed_out"], "finally 必须收尸：在途 chat 5s 内没收到 CancelledError（cancel 被抽掉？）"
    assert snap["cancelled"] is True, "finally MUST 同步 task.cancel()（否则在途 chat 裸跑烧配额）"
    assert snap["calls"] < polish_loop.MAX_TURNS_DEFAULT, (
        f"取消后不该继续跑满轮次：calls={snap['calls']} / max={polish_loop.MAX_TURNS_DEFAULT}"
    )
    assert all(e.get("event") != "result" for e in snap["frames"]), "已断开就不该再产出完整 result"


def test_ai_polish_stream_error_frame_carries_llm_detail(client, monkeypatch):
    """接缝③：流已开头 ⇒ 上游 LLMError MUST 以 **error 帧**抵达用户（`e.detail` 人话）。

    事实链：`_run_polish` 捕获 `llm_client.LLMError` 后 `raise HTTPException(502, detail=e.detail)`
    ⇒ 流层原本写的 `except llm_client.LLMError` **永不命中** ⇒ error 帧永不发出 ⇒ 用户只拿到
    前端那句通用「润色流结束但没有返回结果」。修法选 **(b) 流层捕获 `HTTPException`**：
    `_run_polish` 的契约对两种调用方保持同一形状（失败 ⇒ HTTPException(502)），流已经开了头
    改不了状态码，只能在流内用 error 帧把人话送出去；前端 `writer.js` 也早已按
    `ev.event === 'error'` / `ev.detail` 消费。
    """
    from delector.services import llm_client

    _stub_api_key(monkeypatch)
    # 裁判引擎 deliberately 置为不可用：本条只关心「错误怎么抵达用户」，
    # 让 chat 第一轮就抛，别把时间花在加载真 spaCy 模型上。
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    async def _chat(**kwargs: Any) -> Dict[str, Any]:
        raise llm_client.LLMError("DeepSeek 服务暂时不可用 (503)")

    monkeypatch.setattr("delector.routes.main.llm_client.chat", _chat)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})

    assert res.status_code == 200
    events = _parse_sse(res.text)
    errors = [e for e in events if e.get("event") == "error"]
    assert errors, f"上游失败 MUST 以 error 帧抵达用户，实际帧：{events}"
    assert "DeepSeek 服务暂时不可用 (503)" in errors[0]["detail"], f"error 帧 MUST 带 e.detail 人话：{errors[0]}"
    assert all(e.get("event") != "result" for e in events), "失败路径不该再产出 result 帧"


def test_ai_polish_records_and_uses_real_usage_tokens(client: Any, monkeypatch: Any) -> None:
    """生产端点 Usage 权威透出与精确计量接入。

    断言：
    - _PolishReplyRecorder 初始化 self.usage = None；
    - _PolishReplyRecorder.__call__ 透传 include_usage=True 给 llm_client.chat；
    - _PolishReplyRecorder 捕获 recorder.usage == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}；
    - 在 SSE 流中，tokens_used 消费恰好 50 tokens（来自 usage.completion_tokens），而非字符估算。
    """
    from delector.routes import main as routes_main

    _stub_api_key(monkeypatch)
    monkeypatch.setattr("delector.nlp_engine.processor.get_loaded_nlp", lambda: None)
    monkeypatch.setattr("delector.nlp_engine.processor.try_load_nlp_no_download", lambda: None)

    # 1. 验证单元层面 recorder 初始态与 _capture 行为
    unit_recorder = routes_main._PolishReplyRecorder("test-key", "https://api.deepseek.com")
    assert unit_recorder.usage is None

    chat_calls: List[Dict[str, Any]] = []

    async def mock_chat(**kwargs: Any) -> Dict[str, Any]:
        chat_calls.append(kwargs)
        payload: Dict[str, Any] = {
            "corrected_text": "Ich habe einen Hund. Er ist gut.",
            "notes_zh": ["ein → einen"],
            "error_count": 0,
        }
        if kwargs.get("include_usage"):
            payload["usage"] = {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        return payload

    monkeypatch.setattr("delector.routes.main.llm_client.chat", mock_chat)

    captured_recorders: List[Any] = []
    original_recorder_cls = routes_main._PolishReplyRecorder

    class _SpyRecorder(original_recorder_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            captured_recorders.append(self)

    monkeypatch.setattr("delector.routes.main._PolishReplyRecorder", _SpyRecorder)

    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT, "stream": True})
    assert res.status_code == 200

    # a) _PolishReplyRecorder 捕获 recorder.usage
    assert len(captured_recorders) == 1
    recorder = captured_recorders[0]
    expected_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    assert recorder.usage == expected_usage

    # 透传断言：llm_client.chat 必须收到 include_usage=True
    assert len(chat_calls) >= 1
    assert chat_calls[0].get("include_usage") is True

    # b) SSE stream 中 tokens_used 恰好消费 50 tokens
    events = _parse_sse(res.text)
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, f"缺少 done 事件帧：{events}"
    assert done_events[0]["tokens_used"] == 50, (
        f"tokens_used 期望为精确 usage (50)，实际为 {done_events[0]['tokens_used']}"
    )


def test_frontend_polish_reason_copy_covers_every_reason_code():
    """writer.js 的中文文案 MUST 覆盖 `polish_loop.REASONS` 全部成员 + 端点层 no_api_key。

    将来往 REASONS 里加码而忘了配文案 ⇒ 这里立刻红（前端否则只能弹一句空话）。
    """
    src = open(os.path.join(ROOT, "static", "js", "writer.js"), encoding="utf-8").read()
    block = re.search(r"const POLISH_REASON_COPY\s*=\s*\{(.*?)\n\};", src, re.S)
    assert block, "writer.js 里找不到 POLISH_REASON_COPY 映射表"
    keys = set(re.findall(r"^\s*([a-z_]+)\s*:", block.group(1), re.M))
    expected = set(polish_loop.REASONS) | {"no_api_key"}
    assert keys == expected, (
        f"文案表与原因码集合不一致：缺 {sorted(expected - keys)}，多 {sorted(keys - expected)}"
    )


def test_frontend_polish_progress_takes_max_turns_from_server():
    """进度文案的轮次分母 MUST 取自服务端事件的 `max_turns`，不许前端写死 3。"""
    src = open(os.path.join(ROOT, "static", "js", "writer.js"), encoding="utf-8").read()
    body = src[src.index("export async function aiPolishEssay") : src.index("export async function applyPolishChanges")]
    assert "AbortController" in body, "取消必须有 AbortController（或等价机制）"
    assert "max_turns" in body, "轮次分母必须来自服务端事件"
    assert "/3 轮" not in body, "不许把轮次上界硬编码成 3（内核改 MAX_TURNS_DEFAULT 这里就撒谎）"


# ── C8 Batch C：TTS 三连（有界退避 / 拆分超时 / SSL 回退可观测）─────────────────
#
# 三条口径（delector/services/tts.py）：
#  (a) 只对连接/传输层与 5xx 重试，每次重试前有**有界退避**；协议/解析错误 MUST NOT 重试；
#  (b) 连接超时与读取超时是两个独立值：连接 < 30s（死主机不得再挂满 30s）、读取 >= 30s；
#  (c) Android/Chaquopy 的 SSL 不校验回退 MUST 保留、但 MUST NOT 静默
#      （该分支本机无法真实触发：测试用替身强制走它，只断言「不再静默」这一可验证面）。

_TTS_TURN_END_FRAME = (0x1, b"Path:turn.end\r\n\r\n")
_TTS_AUDIO_HEADERS = b"Path:audio\r\nContent-Type:audio/mpeg\r\n\r\n"
_TTS_AUDIO_FRAME = (0x2, len(_TTS_AUDIO_HEADERS).to_bytes(2, "big") + _TTS_AUDIO_HEADERS + b"MP3DATA")
_TTS_OK_FRAMES = [_TTS_AUDIO_FRAME, _TTS_TURN_END_FRAME]


class _FakeMiniWS:
    """`delector.services.tts._WebSocket` 的测试替身：不发网络，按帧序列回放。

    只实现 synthesize 实际用到的四个方法；帧格式与真协议一致（见 tts.py 的 recv_frame）。
    """

    def __init__(self, host: str = "speech.platform.bing.com", *args: Any, **kwargs: Any) -> None:
        self.host = host
        self.frames = list(_TTS_OK_FRAMES)
        self.closed = False

    def handshake(self, path: str, host: str) -> None:
        self.path = path

    def send_text(self, payload: str) -> None:
        pass

    def recv_frame(self) -> Any:
        return self.frames.pop(0)

    def close(self) -> None:
        self.closed = True


def test_tts_retries_transport_error_with_bounded_backoff(monkeypatch):
    """(a) 连接层失败（可重试）⇒ 第二次尝试前有一次**有界**退避 sleep，且最终合成成功。"""
    from delector.services import tts

    sleeps: List[float] = []
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))
    attempts: List[int] = []

    class _Flaky(_FakeMiniWS):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("connection refused")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(tts, "_WebSocket", _Flaky)
    assert tts.synthesize("Hallo") == b"MP3DATA"
    assert len(attempts) == 2, "可重试失败必须重试一次（首次 + 重试）"
    assert sleeps, "重试前必须有退避 sleep —— 无 sleep 的立即重试正是本次修的缺陷"
    assert sum(sleeps) <= 2.0, f"退避总时长必须有界且远低于调用方 60s 预算: {sleeps}"


def test_tts_protocol_error_is_not_retried(monkeypatch):
    """(a) 协议层结果（服务端零音频帧、直接 turn.end）重试不改变结果 ⇒ MUST NOT 重试。"""
    from delector.services import tts

    sleeps: List[float] = []
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))
    attempts: List[int] = []

    class _NoAudio(_FakeMiniWS):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            super().__init__(*args, **kwargs)
            self.frames = [_TTS_TURN_END_FRAME]

    monkeypatch.setattr(tts, "_WebSocket", _NoAudio)
    with pytest.raises(RuntimeError, match="no audio"):
        tts.synthesize("Hallo")
    assert len(attempts) == 1, "协议/解析错误被重试了（重试不改变结果，纯烧调用方预算）"
    assert sleeps == [], "协议错误不得进入退避重试路径"


def test_tts_handshake_5xx_retries_4xx_does_not(monkeypatch):
    """(a) 5xx 握手拒绝可重试；4xx（非 403 时钟校准）是协议拒绝，原样抛出、不重试。"""
    from delector.services import tts

    sleeps: List[float] = []
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))
    attempts: List[int] = []

    class _Five(_FakeMiniWS):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            super().__init__(*args, **kwargs)

        def handshake(self, path: str, host: str) -> None:
            if len(attempts) == 1:
                raise tts._HandshakeError(b"HTTP/1.1 503 Service Unavailable", {})
            super().handshake(path, host)

    monkeypatch.setattr(tts, "_WebSocket", _Five)
    assert tts.synthesize("Hallo") == b"MP3DATA"
    assert len(attempts) == 2, "5xx 握手拒绝必须重试一次"
    assert len(sleeps) == 1, "5xx 重试前也要走有界退避"

    attempts.clear()
    sleeps.clear()

    class _Four(_FakeMiniWS):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append(1)
            super().__init__(*args, **kwargs)

        def handshake(self, path: str, host: str) -> None:
            raise tts._HandshakeError(b"HTTP/1.1 401 Unauthorized", {})

    monkeypatch.setattr(tts, "_WebSocket", _Four)
    with pytest.raises(tts._HandshakeError):
        tts.synthesize("Hallo")
    assert len(attempts) == 1, "4xx 协议拒绝不得重试"
    assert sleeps == [], "4xx 协议拒绝不得 sleep"


def test_tts_websocket_splits_connect_and_read_timeouts(monkeypatch, recwarn):
    """(b) 连接/读取超时是两个独立值：连接 < 30s（修「死主机挂 30s」）、读取 >= 30s（不劣化慢网）。"""
    from delector.services import tts

    recorded: Dict[str, float] = {}

    class _Sock:
        def settimeout(self, value: float) -> None:
            recorded["read_timeout"] = value

    class _Ctx:
        def wrap_socket(self, sock: Any, server_hostname: Any = None) -> Any:
            return sock

    def _create_connection(address: Any, timeout: float = 0.0) -> _Sock:
        recorded["connect_timeout"] = timeout
        return _Sock()

    monkeypatch.setattr(tts.socket, "create_connection", _create_connection)
    monkeypatch.setattr(tts.ssl, "create_default_context", lambda *args, **kwargs: _Ctx())

    tts._WebSocket("example.invalid")

    assert recorded["connect_timeout"] < 30.0, "连接超时必须严格短于 30s（死主机不得再挂满 30s）"
    assert recorded["read_timeout"] >= 30.0, "读取超时不得短于 30s（慢网络不是新回归）"
    assert recorded["connect_timeout"] != recorded["read_timeout"], "连接/读取超时必须是两个独立值"
    # 桌面路径仍走 create_default_context（证书校验不动）：不得出现 SSL 降级告警
    assert not [w for w in recwarn.list if "证书" in str(w.message)], "桌面路径不该走降级分支"


def test_tts_ssl_fallback_stays_but_is_no_longer_silent(monkeypatch, caplog):
    """(c) 默认 CA 不可用 ⇒ 仍回退到不校验上下文（Android/Chaquopy 路径），但必须告警 + 记日志。

    ⚠️ 该分支本机无法真实触发（无 Chaquopy / 证书缺失环境）：这里用替身强制走它，只断言
    「不再静默」这一可在本机验证的面；回退本身 MUST NOT 被删除（见 tts.py 处的注释）。
    """
    from delector.services import tts

    class _Sock:
        def settimeout(self, value: float) -> None:
            pass

    class _Ctx:
        def wrap_socket(self, sock: Any, server_hostname: Any = None) -> Any:
            return sock

    def _no_default_context(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no CA store on this platform")

    monkeypatch.setattr(tts.socket, "create_connection", lambda address, timeout=None: _Sock())
    monkeypatch.setattr(tts.ssl, "create_default_context", _no_default_context)
    monkeypatch.setattr(tts.ssl, "_create_unverified_context", lambda *args, **kwargs: _Ctx())

    with caplog.at_level(logging.WARNING, logger="delector.services.tts"), pytest.warns(
        RuntimeWarning, match="证书"
    ):
        tts._WebSocket("example.invalid")

    assert any("证书" in record.getMessage() for record in caplog.records), "SSL 降级路径没有日志（静默降级）"


# ── C8 Batch C：设置面板 LAN 渲染回归（api_key_masked 仅回环来源返回）───────────


def test_settings_panel_guards_absent_api_key_masked_static():
    """(i) main.js 设置面板必须按存在性守卫 api_key_masked 再做插值。

    背景：GET /api/settings 对非回环来源收敛掉 `api_key_masked`（C8 Task6），
    裸插值会让局域网客户端的设置面板渲染字面 'undefined'。
    """
    src = open(os.path.join(ROOT, "static", "js", "main.js"), encoding="utf-8").read()
    start = src.index("export async function openSettingsModal()")
    end = src.index("export function closeSettingsModal()")
    lines = src[start:end].splitlines()

    hits = [i for i, ln in enumerate(lines) if "${s.api_key_masked}" in ln]
    assert hits, "设置面板不再插值 api_key_masked —— 回环渲染路径被误删"
    for i in hits:
        window = "\n".join(lines[max(0, i - 2) : i + 1])
        assert re.search(r"s\.api_key_masked\s*\?", window), (
            f"api_key_masked 未被存在性判断守卫（LAN 来源将渲染字面 'undefined'）: {lines[i].strip()}"
        )
    assert "局域网不显示" in "\n".join(lines), "缺少 LAN 来源的诚实回退文案（既不造掩码也不显示 undefined）"


def test_settings_panel_loopback_rendering_path_kept_verbatim():
    """(ii) 回环来源（响应仍带 api_key_masked）的渲染路径 MUST 逐字保留。"""
    src = open(os.path.join(ROOT, "static", "js", "main.js"), encoding="utf-8").read()
    assert "`✓ 当前已配置 Key: ${s.api_key_masked}（留空保存表示不修改）`" in src, (
        "回环渲染文案被改动/删除（桌面端会静默改文案）"
    )
    assert "if (s.has_api_key)" in src, "key 存在性信号（has_api_key）必须仍是渲染分支条件"


def test_api_types_settings_typedef_marks_api_key_masked_loopback_only():
    """api-types.js 的 Settings typedef 必须记录 api_key_masked 为仅回环来源返回。"""
    js = open(os.path.join(ROOT, "static", "js", "api-types.js"), encoding="utf-8").read()
    block = re.search(r"/\*\*(?:(?!\*/).)*GET /api/settings(?:(?!\*/).)*\*/", js, re.S)
    assert block, "api-types.js 缺少 GET /api/settings 的 typedef 注释块"
    text = block.group(0)
    assert "[api_key_masked]" in text, "api_key_masked 未标为可选（LAN 来源响应中不含该字段）"
    assert "回环" in text or "loopback" in text.lower(), "typedef 未记录 api_key_masked 仅回环来源返回"
