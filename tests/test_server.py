# 本文件含「正常模式需要、--follow-imports=skip 下 unused」的动态面 type: ignore
# （BaseRoute 静态无 endpoint/path、运行时必为 APIRoute 的动态访问）——门禁用
# `mypy --follow-imports=skip tests` 跑，skip 下 fastapi 降 Any 使这些 ignore 变
# unused，故文件级豁免 unused-ignore（其它错误码仍全查）。
# mypy: disable-error-code="unused-ignore"
import json
import logging
import os
import re
from typing import Any, Dict, List

import pytest

# 夹具与打包 helper 自 tests/server_helpers.py 上收（C6 Task 3）。夹具用 `as 同名` 显式再导出
# 写法：pyflakes 据此不判「导入未用」（夹具由 pytest 按名解析，静态看不见使用）。
from server_helpers import ROOT
from server_helpers import clean_db as clean_db
from server_helpers import test_db_path as test_db_path

# 不再需要"先设好 DATABASE_PATH 再 import"：库 env 由根 conftest 的 setdefault 兜底，
# 并由各模块 autouse fixture（本文件：clean_db，C6 Task 3 起自 server_helpers 导入）在
# 用例前后钉定；本模块不再在模块级赋值
# （契约 C1，见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1）。
from delector.core.database import db_conn
from delector.server import (
    SYSTEM_GRAMMAR_PROMPT,
    clean_html_to_article,
    get_cefr_level,
    init_db,
    is_safe_public_url,
    process_german_text,
)


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

    monkeypatch.setattr("delector.routes.audio.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))

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

    from delector.routes import audio as routes_audio

    # 1. 堵死 edge_tts 导入（模拟安卓）：sys.modules[name]=None 时 import 抛 ImportError
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    # 2. 用假模块顶替 services.tts，synthesize 返回假 MP3
    fake_mini = types.ModuleType("delector.services.tts")
    fake_mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x00mock_edge_mini_audio"
    fake_mini.synthesize = lambda text, voice, rate: fake_mp3  # type: ignore[attr-defined]  # 构造假模块顶替 sys.modules，刻意在 ModuleType 上动态挂属性
    # routes/audio.py 的 generate_edge_tts_audio 延迟导入写的是
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
    monkeypatch.setattr(routes_audio, "AUDIO_CACHE_DIR", str(cache_dir))

    path = asyncio.run(routes_audio.generate_edge_tts_audio("Wie geht es dir?", "de-DE-KatjaNeural", "+0%"))
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

    monkeypatch.setattr("delector.routes.audio.AUDIO_CACHE_DIR", str(cache_dir))

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
    monkeypatch.setattr("delector.routes.audio.AUDIO_CACHE_DIR", str(cache_dir))

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
    monkeypatch.setattr("delector.routes.audio.AUDIO_CACHE_DIR", str(cache_dir))

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
    monkeypatch.setattr("delector.routes.settings.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "error" in data


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
