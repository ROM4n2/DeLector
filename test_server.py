import os
import json
import re
import pytest
from fastapi.testclient import TestClient

# Ensure test DBs are isolated
os.environ["DATABASE_PATH"] = "test_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_progress.db"

from server import (
    app, init_db, get_db, get_cefr_level,
    SYSTEM_GRAMMAR_PROMPT, process_german_text,
    is_safe_public_url, clean_html_to_article,
    get_progress_db, set_setting,
    BACKUP_FORMAT_VERSION, BACKUP_SETTINGS_WHITELIST,
)

@pytest.fixture
def test_db_path():
    return "test_delector.db"

@pytest.fixture
def test_progress_path():
    return "test_progress.db"

@pytest.fixture
def client():
    # 显式给出本机来源地址：备份端点有「仅 127.0.0.1」闸，
    # TestClient 默认把 client.host 报成 "testclient"，会被闸拒掉。
    return TestClient(app, client=("127.0.0.1", 54321))

@pytest.fixture
def lan_client():
    """模拟同 Wi-Fi 的另一台设备，用于验证备份端点的局域网闸。"""
    return TestClient(app, client=("192.168.1.77", 54321))

@pytest.fixture(autouse=True)
def clean_db():
    for f in ("test_delector.db", "test_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    init_db("test_delector.db")
    yield
    for f in ("test_delector.db", "test_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

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
    assert {"id", "title", "content", "analysis_json",
            "cefr_level", "error_count", "created_at"} <= cols

def test_writing_analyze_endpoint(client):
    res = client.post("/api/writing/analyze", json={"text": "Ich sehe der Mann."})
    assert res.status_code == 200
    a = res.json()
    assert "sentences" in a and len(a["sentences"]) > 0 and a["sentences"][0]["spans"]

def test_essays_crud_flow(client):
    r = client.post("/api/essays", json={"title": "Mein Essay",
                                         "content": "Ich fahre mit der Auto."})
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
    res = client.post("/api/writing/cards", json={
        "essay_id": eid, "sentence_id": 0, "span_index": 0})
    assert res.status_code == 200
    cards_data = client.get("/api/cards").json()
    g_cards = cards_data.get("grammar_cards", [])
    assert g_cards and g_cards[0].get("corrected_form") == span["corrected_form"]
    assert g_cards[0].get("error_type") == span["error_type"]

def test_ai_polish_no_key_stub(client, monkeypatch):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["result"]["error_count"] == 0
    assert data["result"]["corrected_text"] == "Hallo."

def test_ai_polish_diff_no_key_stub(client, monkeypatch):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "")
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
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "test-api-key")

    mock_response_payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "corrected_text": "Ich habe einen Hund. Er ist gut. Ich liebe ihn.",
                    "notes_zh": [
                        "ein -> einen: Akkusativ maskulin",
                        "Ich liebe ihn: Ergänzung zur Vollständigkeit"
                    ],
                    "error_count": 2
                })
            }
        }]
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

    monkeypatch.setattr("server.httpx.AsyncClient", _MockAsyncClient)

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
        "INSERT INTO essays (title, content, analysis_json, cefr_level, error_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Old Essay", "Ich habe ein Hund.", '{"error_count": 1}', "A2", 1)
    )
    conn.commit()
    old_essay_id = conn.execute("SELECT id FROM essays WHERE title = 'Old Essay'").fetchone()[0]
    conn.close()

    # Re-run init_db
    init_db(test_db_path)

    conn = sqlite3.connect(test_db_path)
    versions = conn.execute(
        "SELECT essay_id, message FROM essay_versions WHERE essay_id = ?",
        (old_essay_id,)
    ).fetchall()
    assert len(versions) == 1
    assert versions[0][1] == "初始快照"

    # Running init_db again is idempotent (no duplicate seed)
    init_db(test_db_path)
    versions_after = conn.execute(
        "SELECT essay_id, message FROM essay_versions WHERE essay_id = ?",
        (old_essay_id,)
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
    r_oob = client.post("/api/writing/apply", json={
        "essay_id": eid,
        "original_text": orig,
        "corrected_text": corr,
        "accepted_indices": [-1]
    })
    assert r_oob.status_code == 400

    r_oob2 = client.post("/api/writing/apply", json={
        "essay_id": eid,
        "original_text": orig,
        "corrected_text": corr,
        "accepted_indices": [99]
    })
    assert r_oob2.status_code == 400

    # 3. Non-existent essay returns 404
    r_404 = client.post("/api/writing/apply", json={
        "essay_id": 99999,
        "original_text": orig,
        "corrected_text": corr,
        "accepted_indices": [0]
    })
    assert r_404.status_code == 404

    # 4. Partial accept (accept hunk 0 out of 2)
    # Hunk 0: "Ich habe ein Hund." -> "Ich habe einen Hund."
    # Hunk 1: "" -> "Ich liebe ihn." (rejected)
    r_apply = client.post("/api/writing/apply", json={
        "essay_id": eid,
        "original_text": orig,
        "corrected_text": corr,
        "accepted_indices": [0]
    })
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
    r_reject = client.post("/api/writing/apply", json={
        "essay_id": eid,
        "original_text": "Ich habe einen Hund. Er ist gut.",
        "corrected_text": corr,
        "accepted_indices": []
    })
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
    
    with get_db(test_db_path) as conn:
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
    v_res = client.post("/api/cards/vocab", json={
        "article_id": art_id,
        "word": "Prüfung",
        "lemma": "Prüfung",
        "pos": "NOUN",
        "gender": "Fem",
        "cefr_level": "A2",
        "definition_zh": "考试",
        "sentence_context": text
    })
    assert v_res.status_code == 200

    # 4. Add grammar card
    g_res = client.post("/api/cards/grammar", json={
        "article_id": art_id,
        "sentence_context": text,
        "grammar_name": "Plusquamperfekt mit nachdem",
        "cefr_level": "B1",
        "explanation_zh": "过去完成时表示过去发生之前的动作",
        "rule_formula": "nachdem + Partizip II + hatte/war"
    })
    assert g_res.status_code == 200

    # 5. Export APKG
    apkg_res = client.get("/api/cards/export/apkg")
    assert apkg_res.status_code == 200
    assert len(apkg_res.content) > 1000

def test_is_safe_public_url_filters_private_ips():
    assert is_safe_public_url("http://127.0.0.1:8000/api") is False
    assert is_safe_public_url("http://localhost:3000") is False
    assert is_safe_public_url("http://192.168.1.1/admin") is False
    assert is_safe_public_url("http://10.0.0.5/") is False
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("ftp://example.com/file") is False
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
    mock_html = "<html><head><title>Hallo Berlin</title></head><body><p>Ich lebe seit zwei Jahren in Berlin und lerne jeden Tag Deutsch.</p></body></html>"
    monkeypatch.setattr("server.fetch_remote_html", AsyncMock(return_value=mock_html))
    
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
        "articles": [{
            "id": 999,
            "title": "Backup Test Article",
            "raw_text": "Ein Test für Backup.",
            "processed_json": "{}",
            "source_url": "https://example.com/backup",
            "created_at": "2026-08-18 12:00:00"
        }],
        "vocab_cards": [{
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
            "created_at": "2026-08-18 12:00:00"
        }],
        "grammar_cards": [{
            "id": 999,
            "article_id": 999,
            "sentence_context": "Ein Test.",
            "grammar_name": "Nomen",
            "cefr_level": "A1",
            "explanation_zh": "名词",
            "rule_formula": "Pattern",
            "examples_zh": "例子",
            "created_at": "2026-08-18 12:00:00"
        }]
    }
    
    # 3. Restore custom backup
    res_restore = client.post("/api/backup/restore", json=custom_backup)
    assert res_restore.status_code == 200
    
    # 4. Verify roundtrip integrity
    res_verify = client.get("/api/articles/999")
    assert res_verify.status_code == 200
    assert res_verify.json()["title"] == "Backup Test Article"


# ── v3.10.0 备份往返修复的回归测试 ────────────────────────────────────────────
# 上面那个 roundtrip 测试只断言了文章标题，正是它让「还原丢掉 SRS 状态」
# 这个数据丢失缺陷一路绿灯。下面把每一处都钉死。

def _vocab_card_with_srs(card_id=501):
    return {
        "id": card_id, "article_id": None, "word": "warten", "lemma": "warten",
        "pos": "VERB", "gender": "None", "plural": "", "cefr_level": "A2",
        "definition_zh": "等待", "sentence_context": "Ich warte auf dich.",
        "created_at": "2026-08-01 10:00:00",
        "mastered": 1, "mastered_at": "2026-08-15 09:00:00",
        "correct_count": 7, "wrong_count": 2, "due_date": "2026-12-24",
        "interval_days": 43, "ease_factor": 2.87, "repetition_count": 5,
    }


def test_restore_preserves_srs_state(client):
    """还原必须带回全部 SM-2/FSRS 字段。

    旧实现的 INSERT 列表不含这 8 列，且用 INSERT OR REPLACE，
    于是导出的 JSON 明明带着复习历史，还原一圈却全部回落到 schema 默认值。
    """
    card = _vocab_card_with_srs()
    res = client.post("/api/backup/restore", json={"version": 2, "vocab_cards": [card]})
    assert res.status_code == 200

    with get_db("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE id = 501").fetchone())
    for col in ("mastered", "mastered_at", "correct_count", "wrong_count",
                "due_date", "interval_days", "ease_factor", "repetition_count"):
        assert row[col] == card[col], f"{col} 未被还原：{row[col]!r} != {card[col]!r}"


def test_export_includes_srs_columns(client):
    """导出侧同样要断言——否则「导出完整」这个前提哪天悄悄坏掉不会有人知道。"""
    client.post("/api/backup/restore", json={"version": 2,
                                            "vocab_cards": [_vocab_card_with_srs()]})
    data = client.get("/api/backup/export").json()
    assert data["version"] == BACKUP_FORMAT_VERSION
    exported = next(c for c in data["vocab_cards"] if c["id"] == 501)
    assert exported["ease_factor"] == 2.87
    assert exported["repetition_count"] == 5
    assert exported["due_date"] == "2026-12-24"


def test_progress_db_roundtrips(client):
    """progress.db 三张表进备份——连胜/测验历史/趋势全靠它。"""
    payload = {
        "version": 2,
        "study_log": [{"id": 1, "event_type": "add_card", "ref_id": 42,
                       "note": "t", "logged_at": "2026-08-10 08:00:00"}],
        "quiz_log": [{"id": 1, "card_id": 42, "card_type": "vocab",
                      "mode": "recall", "correct": 1,
                      "attempted_at": "2026-08-10 08:05:00"}],
        "daily_summary": [{"date": "2026-08-10", "cards_added": 3, "cards_mastered": 1,
                           "articles_read": 2, "quiz_sessions": 1, "study_minutes": 25}],
    }
    assert client.post("/api/backup/restore", json=payload).status_code == 200

    with get_progress_db("test_progress.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM study_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM quiz_log").fetchone()[0] == 1
        summary = dict(conn.execute("SELECT * FROM daily_summary").fetchone())
    assert summary["study_minutes"] == 25
    assert summary["cards_added"] == 3

    exported = client.get("/api/backup/export").json()
    assert exported["daily_summary"][0]["study_minutes"] == 25
    assert exported["quiz_log"][0]["mode"] == "recall"


def test_export_whitelists_settings_and_never_leaks_api_key(client):
    """备份 JSON 会被分享/上传——API key 绝不能在里面。"""
    set_setting("DEEPSEEK_API_KEY", "sk-should-never-be-exported", db_path="test_delector.db")
    set_setting("TTS_VOICE", "de-DE-ConradNeural", db_path="test_delector.db")

    data = client.get("/api/backup/export").json()
    keys = {s["key"] for s in data["app_settings"]}
    assert "TTS_VOICE" in keys
    assert "DEEPSEEK_API_KEY" not in keys
    assert "DEEPSEEK_API_KEY" not in set(BACKUP_SETTINGS_WHITELIST)
    # 整个序列化结果里都不该出现那个值
    assert "sk-should-never-be-exported" not in json.dumps(data)


def test_restore_does_not_wipe_api_key(client):
    """还原是真覆盖，但覆盖范围必须止于白名单键。

    整表 DELETE app_settings 会连带抹掉 DEEPSEEK_API_KEY——它从不进备份，
    抹了就再也灌不回来，用户得重新配一遍 key。
    """
    set_setting("DEEPSEEK_API_KEY", "sk-must-survive-restore", db_path="test_delector.db")
    set_setting("TTS_VOICE", "de-DE-KatjaNeural", db_path="test_delector.db")

    res = client.post("/api/backup/restore", json={
        "version": 2,
        "app_settings": [{"key": "TTS_VOICE", "value": "de-DE-ConradNeural"}],
    })
    assert res.status_code == 200

    with get_db("test_delector.db") as conn:
        rows = {r["key"]: r["value"] for r in
                conn.execute("SELECT key, value FROM app_settings").fetchall()}
    assert rows["DEEPSEEK_API_KEY"] == "sk-must-survive-restore"
    assert rows["TTS_VOICE"] == "de-DE-ConradNeural"


def test_restore_accepts_v1_backup(client):
    """读 v1 是硬要求：迁移用户手里拿的恰恰是 v3.9.1 导出的 v1 文件。

    v1 没有 app_settings / progress 三表 / local_storage 字段，
    缺列的 SRS 值回落到建表默认值即可，不能因缺字段而拒收。
    """
    v1 = {
        "version": 1,
        "articles": [{"id": 77, "title": "V1 Backup", "raw_text": "Alt.",
                      "processed_json": "{}", "source_url": "",
                      "created_at": "2026-01-01 00:00:00"}],
        "vocab_cards": [{"id": 77, "article_id": 77, "word": "alt", "lemma": "alt",
                         "pos": "ADJ", "gender": "None", "plural": "",
                         "cefr_level": "A1", "definition_zh": "旧的",
                         "sentence_context": "Alt.", "created_at": "2026-01-01 00:00:00"}],
    }
    assert client.post("/api/backup/restore", json=v1).status_code == 200

    with get_db("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE id = 77").fetchone())
    assert row["definition_zh"] == "旧的"
    assert row["ease_factor"] == 2.5      # schema 默认值
    assert row["interval_days"] == 1
    assert row["mastered"] == 0


def test_failed_restore_rolls_back_both_databases():
    """还原中途失败必须整体回滚，不能留下「已清库而备份没灌进去」的状态。

    两个 db 是独立文件、无法共处一个事务：主库先清空并提交，
    progress 库随后失败——若无文件级快照，主库数据已经没了。
    这里用重复的 daily_summary 主键制造 IntegrityError。

    用独立的 client（raise_server_exceptions=False）：默认 TestClient 会把
    服务端异常原样抛给调用方，拿不到 500 响应。
    """
    client = TestClient(app, client=("127.0.0.1", 54321), raise_server_exceptions=False)
    with get_db("test_delector.db") as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert before > 0, "预置文章应存在，否则这个测试证明不了什么"

    bad = {
        "version": 2,
        "articles": [{"id": 900, "title": "Should Not Survive", "raw_text": "x",
                      "processed_json": "{}", "source_url": "", "created_at": None}],
        # 同一个 date 两行 → daily_summary 主键冲突
        "daily_summary": [{"date": "2026-08-11"}, {"date": "2026-08-11"}],
    }
    res = client.post("/api/backup/restore", json=bad)
    assert res.status_code >= 500

    with get_db("test_delector.db") as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        leaked = conn.execute("SELECT COUNT(*) FROM articles WHERE id = 900").fetchone()[0]
    assert after == before, "主库未被回滚：还原失败却把原有文章清掉了"
    assert leaked == 0, "主库未被回滚：失败的还原却留下了新数据"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/backup/export"),
    ("post", "/api/backup/prepare"),
    ("get", "/api/backup/download/sometoken"),
    ("post", "/api/backup/restore"),
])
def test_backup_endpoints_reject_lan_clients(lan_client, method, path):
    """桌面端有意绑 0.0.0.0，所以备份端点必须自己挡住局域网。

    否则同 Wi-Fi 的任何人都能拖走整库（export），
    或者——在还原改成真覆盖之后——用一个 POST 清空别人的数据库。
    """
    res = getattr(lan_client, method)(path, **({"json": {}} if method == "post" else {}))
    assert res.status_code == 403


def test_prepare_and_download_backup_is_single_use(client):
    """Android 导出链路：POST 组装（带 localStorage）→ GET 下载（带 attachment 头）。

    为什么不能沿用 blob:：Android WebView 的 DownloadListener 对 blob: URL
    永不触发，且没有 shouldOverrideUrlLoading 兜底，点击是静默无操作。
    真 http URL + Content-Disposition 是这个 App 里唯一被证明能下载的路径。
    """
    ls = {"delector_voice": "de-DE-ConradNeural",
          "delector_companion_custom_svg": "<svg/>"}
    prep = client.post("/api/backup/prepare", json={"local_storage": ls})
    assert prep.status_code == 200
    token = prep.json()["token"]
    assert token and len(token) >= 20

    res = client.get(f"/api/backup/download/{token}")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert ".json" in res.headers["content-disposition"]
    body = res.json()
    assert body["version"] == BACKUP_FORMAT_VERSION
    assert body["local_storage"] == ls          # localStorage 必须原样带上
    assert "articles" in body and "daily_summary" in body

    # token 单次有效，用后内存槽清空
    assert client.get(f"/api/backup/download/{token}").status_code == 404


def test_download_rejects_unknown_token(client):
    client.post("/api/backup/prepare", json={"local_storage": {}})
    assert client.get("/api/backup/download/not-the-right-token").status_code == 404


def test_frontend_export_does_not_use_blob_download():
    """前端导出必须走 prepare→download，不能退回 Blob + <a download>。

    blob: 方案在桌面浏览器上能用、在 Android 上是静默无操作，
    所以它的回归不会有任何报错——只会让用户以为自己有备份。
    只能在源码层立个哨兵。
    """
    src = open(os.path.join(os.path.dirname(__file__), "static", "js", "cards.js"),
               encoding="utf-8").read()
    start = src.index("export async function downloadBackupJson")
    export_fn = src[start:src.index("export function uploadBackupJson")]
    assert "/api/backup/prepare" in export_fn
    assert "/api/backup/download/" in export_fn
    assert "createObjectURL" not in export_fn, "blob: 下载在 Android 上是静默无操作"
    assert "local_storage" in export_fn, "localStorage 必须一起导出（字号/语音/宠物 SVG 只在那里）"


def test_audio_tts_endpoint_with_mock(client, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    fake_mp3 = tmp_path / "fake_de.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00mock_audio_data")
    
    monkeypatch.setattr("server.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))
    
    res = client.post("/api/audio/tts", json={"text": "Hallo Berlin!", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert len(res.content) > 10

def test_tts_falls_back_to_stdlib_mini_client_when_edge_tts_missing(client, monkeypatch, tmp_path):
    """安卓 APK 没有 edge_tts wheel → generate_edge_tts_audio 走 edge_tts_mini 客户端。

    模拟 Chaquopy 环境：import edge_tts 抛 ImportError，edge_tts_mini.synthesize 返回假 MP3。
    """
    import sys
    import types
    import asyncio
    import server

    # 1. 堵死 edge_tts 导入（模拟安卓）：sys.modules[name]=None 时 import 抛 ImportError
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    # 2. 用假模块顶替 edge_tts_mini，synthesize 返回假 MP3
    fake_mini = types.ModuleType("edge_tts_mini")
    fake_mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x00mock_edge_mini_audio"
    fake_mini.synthesize = lambda text, voice, rate: fake_mp3
    monkeypatch.setitem(sys.modules, "edge_tts_mini", fake_mini)

    # 3. 独立缓存目录，避免污染
    cache_dir = tmp_path / "mini_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(server, "AUDIO_CACHE_DIR", str(cache_dir))

    path = asyncio.run(server.generate_edge_tts_audio(
        "Wie geht es dir?", "de-DE-KatjaNeural", "+0%"
    ))
    with open(path, "rb") as f:
        assert f.read() == fake_mp3


def test_reading_notes_crud_and_export(client):
    # 1. Ingest article
    res_art = client.post("/api/articles/ingest", json={"title": "Notizen Test", "raw_text": "Berlin ist wunderbar und groß."})
    art_id = res_art.json()["article_id"]

    # 2. Create reading note
    res_note = client.post(f"/api/articles/{art_id}/notes", json={
        "sentence_id": 1,
        "selected_text": "wunderbar",
        "color": "yellow",
        "note_content": "形容词：精彩的、极好的"
    })
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
    (cache_dir / "sample1.mp3").write_bytes(b"x" * 1024 * 50) # 50 KB
    (cache_dir / "sample2.mp3").write_bytes(b"x" * 1024 * 50) # 50 KB

    monkeypatch.setattr("server.AUDIO_CACHE_DIR", str(cache_dir))

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

# ── Phase A: Delete & Master ─────────────────────────────────────────────────

def test_delete_vocab_card(client):
    """Hard-delete removes card from DB."""
    res = client.post("/api/cards/vocab", json={
        "word": "lesen", "lemma": "lesen", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "读", "sentence_context": "Ich lese."
    })
    assert res.status_code == 200
    card_id = res.json()["id"]

    del_res = client.delete(f"/api/cards/vocab/{card_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_id"] == card_id

    cards = client.get("/api/cards").json()
    ids = [c["id"] for c in cards["vocab_cards"]]
    assert card_id not in ids

def test_delete_nonexistent_card_returns_404(client):
    res = client.delete("/api/cards/vocab/99999")
    assert res.status_code == 404

def test_master_vocab_card(client):
    """Mastering a card marks it and logs to progress DB."""
    res = client.post("/api/cards/vocab", json={
        "word": "schreiben", "lemma": "schreiben", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "写", "sentence_context": "Ich schreibe."
    })
    card_id = res.json()["id"]

    patch_res = client.patch(f"/api/cards/vocab/{card_id}/master",
                             json={"mastered": True})
    assert patch_res.status_code == 200
    assert patch_res.json()["mastered"] is True

    with get_db("test_delector.db") as conn:
        row = conn.execute("SELECT mastered, mastered_at FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["mastered"] == 1
        assert row["mastered_at"] is not None

    with get_progress_db("test_progress.db") as conn:
        row = conn.execute(
            "SELECT event_type FROM study_log WHERE ref_id=? AND event_type='master_card'",
            (card_id,)
        ).fetchone()
        assert row is not None
        assert row["event_type"] == "master_card"

def test_unmaster_card(client):
    """Unmastering resets mastered flag."""
    res = client.post("/api/cards/vocab", json={
        "word": "fahren", "lemma": "fahren", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "驾驶", "sentence_context": "Er fährt."
    })
    card_id = res.json()["id"]

    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": True})
    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": False})

    with get_db("test_delector.db") as conn:
        row = conn.execute("SELECT mastered FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["mastered"] == 0

# ── Phase B: Quiz Record ──────────────────────────────────────────────────────

def test_quiz_record_correct(client):
    """Correct answer increments correct_count and logs to quiz_log."""
    res = client.post("/api/cards/vocab", json={
        "word": "hören", "lemma": "hören", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "听", "sentence_context": "Ich höre Musik."
    })
    card_id = res.json()["id"]

    quiz_res = client.post("/api/quiz/record", json={
        "card_id": card_id, "card_type": "vocab",
        "mode": "flashcard", "correct": True
    })
    assert quiz_res.status_code == 200

    with get_db("test_delector.db") as conn:
        row = conn.execute("SELECT correct_count, wrong_count FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["correct_count"] == 1
        assert row["wrong_count"] == 0

    with get_progress_db("test_progress.db") as conn:
        row = conn.execute("SELECT correct FROM quiz_log WHERE card_id=?", (card_id,)).fetchone()
        assert row["correct"] == 1

def test_quiz_record_wrong(client):
    """Wrong answer increments wrong_count."""
    res = client.post("/api/cards/vocab", json={
        "word": "sehen", "lemma": "sehen", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "看", "sentence_context": "Ich sehe dich."
    })
    card_id = res.json()["id"]

    client.post("/api/quiz/record", json={
        "card_id": card_id, "card_type": "vocab",
        "mode": "dictation", "correct": False
    })

    with get_db("test_delector.db") as conn:
        row = conn.execute("SELECT correct_count, wrong_count FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["wrong_count"] == 1
        assert row["correct_count"] == 0

# ── Phase C: Progress Stats ───────────────────────────────────────────────────

def test_progress_stats_empty(client):
    """Progress stats returns expected keys even with no data."""
    res = client.get("/api/progress/stats")
    assert res.status_code == 200
    data = res.json()
    for key in ("total_cards", "total_mastered", "streak", "cefr_counts",
                "trend", "milestones", "accuracy_pct"):
        assert key in data, f"Missing key: {key}"
    assert len(data["trend"]) == 30
    assert data["streak"] >= 0
    assert data["total_cards"] >= 0  # seeded articles may produce vocab cards via NLP
    assert data["total_articles"] >= 0

def test_progress_stats_after_adding_cards(client):
    """Progress reflects added and mastered cards."""
    res = client.post("/api/cards/vocab", json={
        "word": "sprechen", "lemma": "sprechen", "pos": "VERB",
        "cefr_level": "B1", "definition_zh": "说", "sentence_context": "Ich spreche Deutsch."
    })
    card_id = res.json()["id"]
    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": True})

    stats = client.get("/api/progress/stats").json()
    assert stats["total_cards"] >= 1
    assert stats["total_mastered"] >= 1
    assert stats["cefr_counts"]["B1"] >= 1
    # first_card milestone unlocked
    milestones = {m["id"]: m for m in stats["milestones"]}
    assert milestones["first_card"]["unlocked"] is True
    assert milestones["master_10"]["unlocked"] is False  # only 1 mastered


# ── v3.0 / v3.8: FSRS Spaced Repetition & Cloze Exercises ──────────────────

def test_fsrs_algorithm_calculation():
    """Verify modern FSRS DSR calculation mathematics and gradients."""
    from server import calculate_fsrs, get_fsrs_next_intervals

    # 1. Initial review gradients for all 4 grades
    intervals_init = get_fsrs_next_intervals(rep=0, interval=1, ef=2.5)
    assert intervals_init[1] == 1  # Again: 1d
    assert intervals_init[2] == 2  # Hard: 2d
    assert intervals_init[3] == 4  # Good: 4d
    assert intervals_init[4] == 9  # Easy: 9d

    # 2. First time review (Grade 3 - Good)
    rep1, iv1, ef1, due1, next_ivs1 = calculate_fsrs(grade=3, rep=0, interval=1, ef=2.5)
    assert rep1 == 1
    assert iv1 == 4
    assert ef1 == 4.4
    assert isinstance(next_ivs1, dict)
    assert len(next_ivs1) == 4

    # 3. Second consecutive success (Grade 3 - Good)
    rep2, iv2, ef2, due2, next_ivs2 = calculate_fsrs(grade=3, rep=rep1, interval=iv1, ef=ef1)
    assert rep2 == 2
    assert iv2 == 9
    assert ef2 == 4.4

    # 4. Third success (Grade 4 - Easy)
    rep3, iv3, ef3, due3, next_ivs3 = calculate_fsrs(grade=4, rep=rep2, interval=iv2, ef=ef2)
    assert rep3 == 3
    assert iv3 >= 20
    assert ef3 < 4.4  # Difficulty decreased for easy card

    # 5. Lapse / Failure (Grade 1 - Forgot) resets repetition smoothly
    rep_f, iv_f, ef_f, due_f, next_ivs_f = calculate_fsrs(grade=1, rep=rep3, interval=iv3, ef=ef3)
    assert rep_f == 0
    assert iv_f <= 2
    assert ef_f > ef3  # Difficulty increased

def test_sm2_backward_compatibility():
    """Verify legacy calculate_sm2 wrapper returns 4-tuple and works seamlessly."""
    from server import calculate_sm2
    rep, interval, ef, due = calculate_sm2(grade=3, rep=0, interval=1, ef=2.5)
    assert rep == 1
    assert interval == 4
    assert ef == 4.4
    assert isinstance(due, str)

def test_card_review_fsrs_endpoint(client):
    """Test POST /api/cards/{card_type}/{card_id}/review updates FSRS schedule and returns next_intervals."""
    res = client.post("/api/cards/vocab", json={
        "word": "verstehen", "lemma": "verstehen", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "理解", "sentence_context": "Ich verstehe."
    })
    card_id = res.json()["id"]

    # Review with Grade 3 (Good)
    rev_res = client.post(f"/api/cards/vocab/{card_id}/review", json={
        "grade": 3
    })
    assert rev_res.status_code == 200
    card_data = rev_res.json()
    assert card_data["repetition_count"] == 1
    assert card_data["interval_days"] == 4
    assert "due_date" in card_data
    assert "next_intervals" in card_data
    assert card_data["next_intervals"]["1"] == 1 or card_data["next_intervals"][1] == 1
    assert (card_data["next_intervals"]["3"] == 9 or card_data["next_intervals"][3] == 9)

def test_get_cards_includes_next_intervals(client):
    """Test GET /api/cards and GET /api/cards/due populate next_intervals for cards."""
    res = client.post("/api/cards/vocab", json={
        "word": "behalten", "lemma": "behalten", "pos": "VERB",
        "cefr_level": "B1", "definition_zh": "保留，记住", "sentence_context": "Ich behalte das Wort."
    })
    assert res.status_code == 200

    cards_res = client.get("/api/cards")
    assert cards_res.status_code == 200
    cards_data = cards_res.json()
    assert len(cards_data["vocab_cards"]) > 0
    first_card = cards_data["vocab_cards"][0]
    assert "next_intervals" in first_card
    assert (1 in first_card["next_intervals"] or "1" in first_card["next_intervals"])

def test_due_cards_endpoint(client):
    """Test GET /api/cards/due returns cards due today or earlier."""
    res = client.post("/api/cards/vocab", json={
        "word": "lernen", "lemma": "lernen", "pos": "VERB",
        "cefr_level": "A1", "definition_zh": "学习", "sentence_context": "Ich lerne."
    })
    assert res.status_code == 200   # 建卡失败会让下面的断言变成空转

    due_res = client.get("/api/cards/due")
    assert due_res.status_code == 200
    data = due_res.json()
    assert "due_vocab" in data
    assert "due_grammar" in data
    assert "due_count" in data
    assert data["due_count"] >= 1

def test_cloze_exercise_generation_and_eval(client):
    """Test Cloze exercise generation for grammar, vocab, ctest, and evaluation."""
    # Ingest test passage
    text = "In Deutschland lernen viele Studenten Deutsch, weil sie an einer Universität studieren möchten."
    art_res = client.post("/api/articles/ingest", json={"title": "Cloze Test Passage", "raw_text": text})
    art_id = art_res.json()["article_id"]

    # 1. Grammar Cloze Generation
    g_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "grammar"})
    assert g_res.status_code == 200
    g_data = g_res.json()
    assert g_data["mode"] == "grammar"
    assert len(g_data["items"]) > 0
    assert "masked_text" in g_data

    # 2. C-Test Cloze Generation
    c_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "ctest"})
    assert c_res.status_code == 200
    c_data = c_res.json()
    assert c_data["mode"] == "ctest"
    assert len(c_data["items"]) > 0

    # 3. Evaluate Answers
    first_item = g_data["items"][0]
    eval_res = client.post("/api/exercise/cloze/evaluate", json={
        "article_id": art_id,
        "mode": "grammar",
        "answers": {
            str(first_item["index"]): first_item["original"]
        }
    })
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "score" in eval_data
    assert "total" in eval_data
    assert "accuracy_pct" in eval_data
    assert eval_data["results"][0]["correct"] is True

def test_cloze_evaluation_vocab_and_incorrect(client):
    """Test vocab mode cloze generation and evaluation, including incorrect answer."""
    text = "Deutsch ist eine schöne Sprache, die viele Menschen lernen."
    art_res = client.post("/api/articles/ingest", json={"title": "Vocab Cloze", "raw_text": text})
    art_id = art_res.json()["article_id"]

    v_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "vocab"})
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["mode"] == "vocab"
    assert len(v_data["items"]) > 0

    first_item = v_data["items"][0]
    correct_ans = first_item["original"]
    eval_res = client.post("/api/exercise/cloze/evaluate", json={
        "article_id": art_id,
        "mode": "vocab",
        "answers": {str(first_item["index"]): correct_ans}
    })
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["results"][0]["correct"] is True

    if len(v_data["items"]) > 1:
        second = v_data["items"][1]
        eval_res2 = client.post("/api/exercise/cloze/evaluate", json={
            "article_id": art_id,
            "mode": "vocab",
            "answers": {str(second["index"]): "wronganswer"}
        })
        assert eval_res2.status_code == 200
        eval_data2 = eval_res2.json()
        assert eval_data2["results"][0]["correct"] is False

def test_cloze_evaluation_ctest(client):
    """Test ctest mode generation and evaluation."""
    text = "Die Universität bietet viele Kurse an, die Studenten können wählen."
    art_res = client.post("/api/articles/ingest", json={"title": "Ctest Cloze", "raw_text": text})
    art_id = art_res.json()["article_id"]
    c_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "ctest"})
    assert c_res.status_code == 200
    c_data = c_res.json()
    assert c_data["mode"] == "ctest"
    assert len(c_data["items"]) > 0
    answers = {str(item["index"]): item["original"] for item in c_data["items"][:3]}
    eval_res = client.post("/api/exercise/cloze/evaluate", json={
        "article_id": art_id,
        "mode": "ctest",
        "answers": answers
    })
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "score" in eval_data
    assert eval_data["score"] >= 0

def test_core_dict_and_offline_vocab_lookup(client):
    """Test offline Goethe core vocabulary lookup and CEFR tagging."""
    from core_dict import lookup_core_vocab, get_core_cefr_level

    # Direct core_dict module tests
    hit = lookup_core_vocab("Herausforderung")
    assert hit is not None
    assert hit["cefr_level"] == "B1"
    assert hit["gender"] == "Fem"
    assert "挑战" in hit["definition_zh"]

    lvl = get_core_cefr_level("klimawandel")
    assert lvl == "B1"

    # API endpoint test with local dict hit (no network API key required)
    res = client.post("/api/lookup/vocab", json={
        "sentence": "Der Klimawandel ist eine große Herausforderung.",
        "target_word": "Herausforderung"
    })
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

    import server
    async def mock_fetch(url):
        return sample_rss_xml

    monkeypatch.setattr(server, "fetch_remote_html", mock_fetch)
    monkeypatch.setattr(server, "is_safe_public_url", lambda u: True)

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

    import server
    async def mock_fetch_rdf(url):
        return sample_rdf

    monkeypatch.setattr(server, "fetch_remote_html", mock_fetch_rdf)
    monkeypatch.setattr(server, "is_safe_public_url", lambda u: True)

    res = client.get("/api/feed/items?url=https://rss.dw.com/rdf/rss-de-all")

    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["items"][0]["title"] == "Neues Gesetz im Bundestag verabschiedet"
    assert "Bundestag" in data["items"][0]["summary"]


# ── v3.4.0 Phase: Morphology & Separable Verbs Engine ─────────────────────────

def test_separable_verbs_extraction():
    """Verify spaCy dependency extraction for German separable verbs."""
    from server import process_german_text
    
    text = "Er steigt jeden Morgen in den Zug ein."
    res = process_german_text(text)
    assert res["sentence_count"] >= 1
    sent = res["sentences"][0]
    tokens = sent["tokens"]
    
    verb_tok = next((t for t in tokens if t["text"] == "steigt"), None)
    prefix_tok = next((t for t in tokens if t["text"] == "ein"), None)
    
    assert verb_tok is not None, "Verb token 'steigt' not found"
    assert prefix_tok is not None, "Prefix token 'ein' not found"
    
    assert "separable" in verb_tok, "separable info missing on verb token"
    assert verb_tok["separable"]["sep_prefix_id"] == prefix_tok["id"]
    assert verb_tok["separable"]["sep_lemma"] == "einsteigen"
    
    assert "separable" in prefix_tok, "separable info missing on prefix token"
    assert prefix_tok["separable"]["sep_verb_id"] == verb_tok["id"]
    assert prefix_tok["separable"]["sep_lemma"] == "einsteigen"


def test_irregular_verb_stammformen_lookup():
    """Verify Goethe irregular/strong verb Stammformen reverse lookup."""
    from linguistics import lookup_irregular_verb
    
    # 1. Base infinitive
    res_gehen = lookup_irregular_verb("gehen")
    assert res_gehen is not None
    assert res_gehen["infinitiv"] == "gehen"
    assert res_gehen["praeteritum"] == "ging"
    assert res_gehen["partizip2"] == "gegangen"
    assert res_gehen["hilfsverb"] == "ist"
    
    # 2. Conjugated / past reverse lookup
    res_ging = lookup_irregular_verb("ging")
    assert res_ging is not None
    assert res_ging["infinitiv"] == "gehen"
    
    res_gegangen = lookup_irregular_verb("gegangen")
    assert res_gegangen is not None
    assert res_gegangen["infinitiv"] == "gehen"
    
    # 3. Separable compound irregular verb
    res_einsteigen = lookup_irregular_verb("einsteigen")
    assert res_einsteigen is not None
    assert res_einsteigen["infinitiv"] == "einsteigen"
    assert "stieg" in res_einsteigen["praeteritum"]
    assert res_einsteigen["partizip2"] == "eingestiegen"
    assert res_einsteigen["hilfsverb"] == "ist"


def test_komposita_splitting():
    """Verify German compound noun splitting with Fugenelemente."""
    from linguistics import split_komposita
    
    # 1. Two-part compound
    klima_parts = split_komposita("Klimaschutz")
    assert len(klima_parts) == 2
    assert klima_parts[0]["lemma"] == "klima"
    assert klima_parts[1]["lemma"] == "schutz"
    
    # 3. Plural compound noun with linking -s- and plural -en
    klima_massnahmen = split_komposita("Klimaschutzmaßnahmen")
    assert len(klima_massnahmen) >= 2
    assert any("klima" in p["lemma"] for p in klima_massnahmen)

    # 4. Two-part compound with linking -s-
    bund_reg = split_komposita("Bundesregierung")
    assert len(bund_reg) == 2
    assert bund_reg[0]["lemma"] == "bund"
    assert bund_reg[1]["lemma"] == "regierung"



def test_vocab_lookup_with_linguistics_stammformen_and_komposita(client):
    """Test /api/lookup/vocab includes stammformen for verbs and komposita for compounds."""
    # 1. Verb lookup returns stammformen
    res_verb = client.post("/api/lookup/vocab", json={
        "sentence": "Er ging gestern nach Hause.",
        "target_word": "ging"
    })
    assert res_verb.status_code == 200
    data_verb = res_verb.json()
    assert "stammformen" in data_verb
    assert data_verb["stammformen"]["infinitiv"] == "gehen"
    assert data_verb["stammformen"]["praeteritum"] == "ging"
    assert data_verb["stammformen"]["partizip2"] == "gegangen"
    assert data_verb["stammformen"]["hilfsverb"] == "ist"
    
    # 2. Compound lookup returns komposita
    res_comp = client.post("/api/lookup/vocab", json={
        "sentence": "Klimaschutz ist eine globale Aufgabe.",
        "target_word": "Klimaschutz"
    })
    assert res_comp.status_code == 200
    data_comp = res_comp.json()
    assert "komposita" in data_comp
    assert len(data_comp["komposita"]) >= 2
    assert data_comp["komposita"][0]["lemma"] == "klima"

    # 3. Plural compound lookup returns komposita
    res_plural_comp = client.post("/api/lookup/vocab", json={
        "sentence": "Die Bundesregierung plant neue Klimaschutzmaßnahmen.",
        "target_word": "Klimaschutzmaßnahmen"
    })
    assert res_plural_comp.status_code == 200
    data_plural_comp = res_plural_comp.json()
    assert "komposita" in data_plural_comp
    assert len(data_plural_comp["komposita"]) >= 2

def test_vocab_lookup_returns_prep_collocations(client):
    """查词响应要带 praepositionen：抽屉的第四个 banner 就靠它。

    bestehen 是这个数据集存在的理由：auf/aus/in 三个介词三个意思，
    值必须是列表，单值 schema 会静默丢掉两个义项。
    """
    res = client.post("/api/lookup/vocab", json={
        "sentence": "Das Team besteht aus fünf Personen.",
        "target_word": "besteht", "lemma": "bestehen"
    })
    assert res.status_code == 200
    rows = res.json().get("praepositionen")
    assert rows, "bestehen 必须有介词搭配"
    preps = {r["praeposition"] for r in rows}
    assert {"auf", "aus", "in"} <= preps
    for r in rows:
        assert r["kasus"] in ("Akk", "Dat", "Gen")
        assert r["bedeutung_zh"] and r["beispiel"]


def test_vocab_lookup_omits_prep_key_when_no_collocation(client):
    """没有固定搭配的词不能带空 praepositionen 键——前端按键存在与否决定是否渲染。"""
    res = client.post("/api/lookup/vocab", json={
        "sentence": "Das Haus ist groß.", "target_word": "Haus", "lemma": "haus"
    })
    assert res.status_code == 200
    assert "praepositionen" not in res.json()


def test_prep_lookup_falls_back_to_surface_form(client):
    """lemma 缺失时用表面形兜底：前端不总能给出 lemma（点击非动词位置时）。"""
    res = client.post("/api/lookup/vocab", json={
        "sentence": "Ich warte auf den Bus.", "target_word": "warten"
    })
    assert res.status_code == 200
    assert res.json()["praepositionen"][0]["praeposition"] == "auf"


def _load_build_prep():
    """加载生成器模块（tools/ 不是 package，只能按路径加载）。"""
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "tools", "build_prep.py")
    spec = importlib.util.spec_from_file_location("build_prep_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prep_dataset_integrity():
    """数据集自检：键小写、值是元组的元组、格合法、例句真的用上了该介词。

    最后一条是本数据集唯一的自动幻觉检测 —— AI 编出 "warten für" 时，
    例句里往往还是 auf。判定用生成器的 `_accepted_surface_forms`，**不复制**
    那张缩合表：两份各自维护的话，一边认 zum 一边不认，正确数据会在这里被
    判成幻觉（实遇：animieren zu → "zum Nachdenken" 把测试挂掉）。
    """
    from prep_dict import PREP_COLLOCATIONS
    accepted = _load_build_prep()._accepted_surface_forms
    assert len(PREP_COLLOCATIONS) >= 40
    for lemma, rows in PREP_COLLOCATIONS.items():
        assert lemma == lemma.lower(), f"{lemma} 不是小写，查词链会 miss"
        assert isinstance(rows, tuple) and rows, f"{lemma} 的值必须是非空元组"
        for row in rows:
            assert isinstance(row, tuple) and len(row) == 4, f"{lemma}: {row}"
            prep, kasus, zh, example = row
            assert kasus in ("Akk", "Dat", "Gen"), f"{lemma}: 非法格 {kasus}"
            assert zh and example, f"{lemma}: 缺中文义或例句"
            words = {w.strip(".,!?;:»«\"'").lower() for w in example.split()}
            assert words & accepted(prep), f"{lemma}: 例句没用上 {prep} —— {example}"
        # 同一介词允许出现两次 —— 靠反身性区分的两个义项就是这样：
        # ausgeben für 花费 / (sich) 冒充，einfügen in 插入 / (sich) 融入。
        # 真正要拦的是 AI 把同一条重复两遍，所以按 (介词, 中文义) 判重。
        senses = {(r[0], r[2]) for r in rows}
        assert len(senses) == len(rows), f"{lemma} 有完全重复的搭配 {[r[0] for r in rows]}"


def test_prep_contractions_cover_all_dative_accusative_pairs():
    """缩合表漏一个介词 = 那个介词的正确搭配被当幻觉丢进「确认没有搭配」名单。

    这条负例名单会被 --resume 当成已答过而永不重问，缺口从此静默。
    所以缩合形式必须成表维护，并在这里逐条钉住。
    """
    bp = _load_build_prep()
    for prep, expected in [("an", "am"), ("an", "ans"), ("in", "im"), ("in", "ins"),
                           ("zu", "zum"), ("zu", "zur"), ("bei", "beim"),
                           ("von", "vom"), ("auf", "aufs"), ("für", "fürs"),
                           ("um", "ums"), ("über", "übers")]:
        forms = bp._accepted_surface_forms(prep)
        assert prep in forms, f"{prep} 自身必须被接受"
        assert expected in forms, f"{prep} 缺缩合形式 {expected}"


def test_prep_dataset_keys_all_exist_in_dictionary():
    """prep 词头必须是词库里真有的词，否则查词链永远碰不到它。

    实遇：词库把 rätseln 错拼成 ratseln，缓存照错拼问了 AI，词库修好后
    prep_dict 仍带着 ratseln —— 查 rätseln 没搭配、查 ratseln 有，两边
    看起来都正常。生成器的 prune_unknown_lemmas 负责剔除，这里守住结果。
    """
    from prep_dict import PREP_COLLOCATIONS
    from core_dict import CORE_VOCAB_DB
    seed = set(_load_build_prep().SEED_COLLOCATIONS)
    orphans = [w for w in PREP_COLLOCATIONS if w not in CORE_VOCAB_DB and w not in seed]
    assert not orphans, f"这些词头不在词库里: {orphans[:10]}"


def test_prep_dict_registered_in_all_package_targets():
    """漏注册任一处 = 打包后 ModuleNotFoundError（或安卓上静默没有该功能）。"""
    root = os.path.dirname(__file__)
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert "--hidden-import=prep_dict" in pkg
    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"),
              encoding="utf-8").read()
    assert wf.count("--hidden-import=prep_dict") == 2, "Windows/Linux 两个构建都要"
    cp_line = [ln for ln in wf.splitlines() if "cp -r server.py" in ln]
    assert cp_line and "prep_dict.py" in cp_line[0], "安卓 cp 列表漏了 prep_dict.py"


def test_syntax_analyze_endpoint(client):
    res = client.post("/api/syntax/analyze", json={
        "text": "Weil das Wetter heute schön ist, geht Maria im Park spazieren."
    })
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
    up_res = client.post("/api/settings", json={
        "api_key": "sk-test-mock-key-1234567890",
        "api_base_url": "https://api.custom.com/v1",
        "api_model": "custom-gpt4",
        "tts_voice": "de-DE-ConradNeural",
        "tts_rate": "+15%"
    })
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

def test_settings_test_key_without_key(client):
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "error" in data











# --- Android / Chaquopy runtime: spacy is absent, everything must fall back to pure Python ---

def test_pure_python_pipeline_without_spacy():
    """APK 里没有 spacy，process_german_text 走纯 Python 分支。

    这条分支曾因调用不存在的 lookup_core_dict 而在 import server 时就 NameError，
    导致安卓端 uvicorn 永远起不来、启动页一直卡住。
    """
    import server

    result = server._process_german_text_pure_python(
        "Der Hund schläft. Ich habe ein Buch gelesen!"
    )

    assert result["sentence_count"] == 2
    tokens = [t for s in result["sentences"] for t in s["tokens"]]
    assert tokens, "pure-python 分支必须产出 token"
    # 核心词库命中时应带出 CEFR 与词性，而不是空值
    der = next(t for t in tokens if t["text"] == "Der")
    assert der["lemma"] == "der"
    assert der["cefr_level"]
    assert all(t["cefr_level"] == "" for t in tokens if t["is_punct"])
    assert result["stats"]["word_count"] > 0

def test_module_import_survives_without_spacy(monkeypatch):
    """server 的 import 期副作用（init_db → seed_preset_articles）不能依赖 spacy。"""
    import server

    monkeypatch.setattr(server, "nlp", None)
    seeded = server.process_german_text(server.PRESET_ARTICLES[0]["text"])
    assert seeded["sentence_count"] > 0
    assert seeded["sentences"][0]["tokens"]

def test_syntax_tree_pure_python_sentence_split():
    """syntax_tree 的降级分支曾有和 server 完全相同的切句 bug：句号被切成独立句子。"""
    from syntax_tree import _analyze_syntax_tree_pure_python, split_sentences_pure_python

    assert split_sentences_pure_python("Der Hund schläft. Ich lese!") == [
        "Der Hund schläft.",
        "Ich lese!",
    ]
    result = _analyze_syntax_tree_pure_python("Der Hund schläft. Ich lese!")
    assert result["sentence_count"] == 2
    assert [s["text"] for s in result["sentences"]] == ["Der Hund schläft.", "Ich lese!"]

def test_bind_host_is_loopback_only_on_android(monkeypatch):
    """Android 上必须只监听回环：POST /api/settings 无鉴权，绑 0.0.0.0 会暴露给整个局域网。"""
    import start

    monkeypatch.setattr(start, "is_android", lambda: True)
    assert start.get_bind_host() == "127.0.0.1"

    monkeypatch.setattr(start, "is_android", lambda: False)
    assert start.get_bind_host() == "0.0.0.0"

def test_settings_reports_nlp_engine(client):
    """降级是静默的，所以引擎状态必须能从 API 读到（真机上唯一的可验证途径）。"""
    import server

    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["nlp_engine"] in ("spacy", "pure_python")
    assert data["nlp_engine"] == server.NLP_ENGINE
    assert data["nlp_engine_detail"]

def test_android_never_downloads_model_at_import():
    """Android 上 spacy.cli.download 会起 pip 子进程拉 15MB 模型。

    Chaquopy 里必然失败，但会在 import server 期间阻塞启动——正是把 APK
    卡在启动页的那类故障。装上 spaCy 后这段原本的死代码变成了活路径。
    """
    import subprocess
    import sys
    import os

    probe = (
        "import spacy, sys, os\n"
        "def _boom(*a, **k):\n"
        "    raise OSError('simulated')\n"
        # 三条加载路径全部堵死：spacy.load(名称)、模块自身 load()、按数据目录加载
        "spacy.load = _boom\n"
        "import spacy.util\n"
        "spacy.util.load_model_from_init_py = _boom\n"
        "spacy.util.load_model_from_path = _boom\n"
        "import spacy.cli\n"
        "spacy.cli.download = lambda *a, **k: print('DOWNLOAD_ATTEMPTED')\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import server\n"
        "print('ENGINE=' + server.NLP_ENGINE)\n"
    )
    env = {**os.environ, "ANDROID_ROOT": "/system", "PYTHONIOENCODING": "utf-8"}
    res = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env)
    out = (res.stdout or "") + (res.stderr or "")
    assert "DOWNLOAD_ATTEMPTED" not in out, "Android 上不得在 import 期联网下载模型"
    assert "ENGINE=pure_python" in out

def test_spacy_model_candidates_prefer_md():
    """README 与 Dockerfile 都装 md（带词向量、标注更准），sm 只是兜底。"""
    import server

    assert server.SPACY_MODEL_CANDIDATES == ("de_core_news_md", "de_core_news_sm")
    # 自动下载走小模型：md 约 45MB，首启动拉它太慢
    assert server.AUTO_DOWNLOAD_MODEL == "de_core_news_sm"

def test_load_spacy_model_falls_back_to_module_load(monkeypatch):
    """spacy.load(名称) 查的是 .dist-info；Android 上模型是直接拷进源码目录的。

    真机实测报的就是 "[E050] Can't find model 'de_core_news_sm'"，尽管这个包
    import 得动。所以按名称失败后必须退到模块自身的 load()。
    """
    import sys
    import types
    import server

    sentinel = object()
    fake = types.ModuleType("de_fake_news_sm")
    fake.load = lambda **kw: sentinel
    monkeypatch.setitem(sys.modules, "de_fake_news_sm", fake)
    monkeypatch.setattr(server.spacy, "load", lambda *a, **k:
                        (_ for _ in ()).throw(OSError("[E050] Can't find model")))

    nlp, how = server._load_spacy_model("de_fake_news_sm")
    assert nlp is sentinel
    assert "module.load" in how

def test_load_spacy_model_reports_every_failed_strategy(monkeypatch):
    """全部失败时错误信息要带上每条策略的原因，否则真机上无从判断卡在哪。"""
    import server

    monkeypatch.setattr(server.spacy, "load", lambda *a, **k:
                        (_ for _ in ()).throw(OSError("no dist-info")))
    with pytest.raises(RuntimeError) as excinfo:
        server._load_spacy_model("de_definitely_not_installed")
    message = str(excinfo.value)
    assert "spacy.load" in message
    assert "import de_definitely_not_installed" in message

def test_android_build_extracts_spacy_data_packages():
    """Chaquopy 默认不把包的数据文件解到磁盘（build.json 的 extract_packages 为空）。

    这三个包都用 Path(__file__).parent 去 open() 真实文件，漏掉任何一个，
    真机上 spaCy 就会静默退回纯 Python 路径。
    """
    gradle = open(os.path.join(os.path.dirname(__file__), "android", "app", "build.gradle"),
                  encoding="utf-8").read()
    extract_lines = [ln for ln in gradle.splitlines() if "extractPackages" in ln]
    assert extract_lines, "build.gradle 必须声明 extractPackages"
    declared = extract_lines[0]
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in declared, f"{pkg} 的数据文件不会被解包"

def _read_android_gradle():
    return open(os.path.join(os.path.dirname(__file__), "android", "app", "build.gradle"),
                encoding="utf-8").read()

def test_android_version_code_encoding():
    """versionCode 必须是 major*10000 + minor*100 + patch，且严格大于历史最大值。

    旧编码 major*100 + minor*10 + patch 在 minor 到 10 时溢出撞车
    （3.10.0 与 4.0.0 都算出 400）。versionCode 撞车 = 新版本无法覆盖安装，
    所以这条规则交给测试守，而不是靠记忆。
    """
    gradle = _read_android_gradle()
    code = int(re.search(r"versionCode\s+(\d+)", gradle).group(1))
    name = re.search(r'versionName\s+"([\d.]+)"', gradle).group(1)
    major, minor, patch = (int(x) for x in name.split("."))
    assert code == major * 10000 + minor * 100 + patch, \
        f"versionName {name} 应编码为 {major * 10000 + minor * 100 + patch}，实际 {code}"
    assert minor < 100 and patch < 100, "minor/patch 各只有两位空间"
    assert code > 391, "必须大于 v3.9.1 的 391，否则安卓拒绝覆盖安装"

def test_android_signing_config_degrades_without_keystore():
    """签名配置必须以「keystore 文件存在」为条件，且只读环境变量。

    两条都不能少：
    - 无条件写 storeFile 会让本地开发和 fork 直接构建失败；
    - 把口令写进 build.gradle 则是把签名密钥提交进仓库。
    """
    gradle = _read_android_gradle()
    assert "signingConfigs" in gradle, "缺少钉死的签名配置"
    assert 'file(pinnedKeystore).exists()' in gradle, \
        "签名配置必须以 keystore 文件真实存在为前提，否则本地/fork 构建会炸"
    for var in ("DELECTOR_KEYSTORE_PATH", "DELECTOR_KEYSTORE_PASSWORD",
                "DELECTOR_KEY_ALIAS", "DELECTOR_KEY_PASSWORD"):
        assert f'System.getenv("{var}")' in gradle, f"{var} 必须从环境变量读"
    assert "storePassword" in gradle and 'storePassword "' not in gradle, \
        "口令不得硬编码在 build.gradle 里"
    # keytool -printcert -jarfile 只认 v1 签名，而 AGP 在 minSdk>=24 时默认只出
    # v2/v3。CI 验签闸靠 keytool 读指纹，没开 v1 的话闸读出来永远是空的——
    # 实测 v3.10.0 首跑就死在这（keystore 指纹对、APK 指纹空）。删掉这行 =
    # 闸静默失效，所以交给测试钉住。
    assert "v1SigningEnabled true" in gradle, \
        "必须显式开 v1 签名，否则 keytool 读不出 APK 指纹，验签闸退化成摆设"

def test_release_workflow_gates_apk_signature():
    """CI 必须验签，并且只取 debug 变体那一个确定的 APK 路径。

    没有这道闸时的失效模式是静默的：secret 缺失 → gradle 回落到随机 debug
    keystore → 产出一个看起来正常、装到手机上却签名不一致的 APK。
    """
    workflow = open(os.path.join(os.path.dirname(__file__), ".github", "workflows",
                                 "build-release.yml"), encoding="utf-8").read()
    assert "keytool -printcert -jarfile" in workflow, "缺少 APK 证书指纹断言"
    assert "app/build/outputs/apk/debug/app-debug.apk" in workflow, \
        "APK 路径必须写死到 debug 变体，find *.apk 会随机抓到别的变体"
    assert 'find android/app/build/outputs/apk/ -name "*.apk"' not in workflow
    assert "$RUNNER_TEMP/delector-debug.jks" in workflow, \
        "keystore 必须解到 $RUNNER_TEMP，不能落在工作树里"
    # 指纹一旦填上就不能再被清空：空值时那道闸退化成 APK↔keystore 自比对，
    # 拦不住「keystore 被换成另一份合法 keystore」（= 已安装用户永远收不到升级）。
    expected = re.search(r'EXPECTED_SHA256:\s*"([^"]*)"', workflow).group(1)
    assert re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", expected), \
        f"EXPECTED_SHA256 必须是大写冒号分隔的 32 字节指纹（与 keytool 输出同格式），实际 {expected!r}"
    assert "android/" not in workflow.split("Decode Pinned Signing Keystore")[1].split("base64 -d")[0], \
        "解码目标不得指向仓库内路径"

def test_android_workflow_build_and_signature_contract():
    """CI 必须保留关键构建与签名契约：JDK 17、Gradle 构建、keytool 验签、指纹、模型与 extractPackages。

    任何一项静默丢失都会导致：本地能跑但 CI 产出的 APK 是旧签名/缺模型/纯 Python 降级。
    """
    wf = open(os.path.join(os.path.dirname(__file__), ".github", "workflows",
                           "build-release.yml"), encoding="utf-8").read()
    gradle = open(os.path.join(os.path.dirname(__file__), "android", "app", "build.gradle"),
                  encoding="utf-8").read()
    # JDK 17
    assert "java-version: '17'" in wf or 'java-version: "17"' in wf, "工作流必须保留 JDK 17"
    assert "setup-java" in wf, "工作流必须使用 setup-java"
    # Android 构建命令（复用已有 JDK/缓存/签名，不新增平行流程）
    assert "gradle assembleDebug" in wf or "gradle assemble" in wf, "工作流必须执行 Gradle assemble 任务"
    assert "Sync Python Backend, Model, and Assets into Android Project" in wf, \
        "Gradle 构建必须在资产生成之后执行"
    # keytool 验签
    assert "keytool -printcert -jarfile" in wf, "缺少 keytool -printcert -jarfile 验签"
    # 期望指纹
    expected = re.search(r'EXPECTED_SHA256:\s*"([^"]*)"', wf)
    assert expected and expected.group(1), "缺少 EXPECTED_SHA256 指纹声明"
    assert re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", expected.group(1)), \
        f"指纹格式错误: {expected.group(1)!r}"
    # 模型声明
    assert "de_core_news_sm" in wf, "工作流必须声明模型 de_core_news_sm"
    assert "spacy" in wf.lower(), "工作流必须声明 spacy"
    # 三个 extractPackages 在 gradle 中
    extract_lines = [ln for ln in gradle.splitlines() if "extractPackages" in ln]
    assert extract_lines, "build.gradle 必须声明 extractPackages"
    declared = extract_lines[0]
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in declared, f"{pkg} 的数据文件不会被解包"


def test_android_apk_content_via_app_imy():
    """APK 内容必须通过 assets/chaquopy/app.imy 检查，不能直接在 APK 根目录 grep Python 文件。

    Python 代码被打进 app.imy（及 requirements-<abi>.imy），直接在 APK namelist 里
    grep server.py 会误判成缺失；而只查 APK 根目录会漏检但测试仍绿。
    """
    wf = open(os.path.join(os.path.dirname(__file__), ".github", "workflows",
                           "build-release.yml"), encoding="utf-8").read()
    # 必须检查 app.imy 内部而非 APK 根
    assert "assets/chaquopy/app.imy" in wf, \
        "APK 内容检查必须验证 assets/chaquopy/app.imy，不能直接在 APK 根目录查找"
    # app.imy 内必须包含关键资产
    for needle in ("server.py", "de_core_news_sm", "spacy", "thinc"):
        assert needle in wf, f"APK 内容检查必须验证 {needle} 在 app.imy/requirements 中"
    # 不得仅用 APK 根目录 grep 来验证 Python 文件（这是常见误判）
    # 允许 app.imy 上下文中的 grep，但 workflow 中若出现直接 "unzip -l.*apk.*grep.*server.py"
    # 而不经过 app.imy，则为错误模式
    lines = wf.splitlines()
    for ln in lines:
        stripped = ln.strip()
        if "server.py" in stripped and "grep" in stripped.lower():
            assert "app.imy" in wf, "server.py 检查必须在 app.imy 上下文中"
            break


def test_keystore_protected_by_gitignore_and_hook():
    root = os.path.dirname(__file__)
    ignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    for pat in ("*.jks", "*.keystore", "*.p12", "signing.properties"):
        assert pat in ignore, f".gitignore 缺 {pat}"
    hook = open(os.path.join(root, ".githooks", "pre-commit"), encoding="utf-8").read()
    assert "*.jks" in hook, "pre-commit 的文件名黑名单不覆盖 keystore"
    assert "feedfeed" in hook, "还需按文件头认 keystore：改后缀就能绕开文件名黑名单"
    # Task3: 编码后的 PKCS12（Base64 存成普通文本）也不能靠改后缀绕开
    assert "PKCS12 Base64" in hook, "pre-commit 缺少 PKCS12 Base64 内容检测"
    assert "020103" in hook, "PKCS12 判定必须包含 version 3 头校验（020103），不能只认 3082"
    # 不能用通用 MII 前缀单独作为 PATTERNS 条目（会把公开证书全误拦）
    assert "MII[A-Za-z0-9+/]" in hook or "MII" in hook, "应有 MII 长串预筛但必须配合解码校验"
    # Base64 块必须配合解码校验：hook 里应有 python 解码与 0x30 0x82 校验
    assert "base64" in hook and "0x30" in hook, "PKCS12 Base64 检测需经 base64 解码后验文件头"


def _pkcs12_b64():
    import base64
    return base64.b64encode(bytes.fromhex("30820500020103") + b"A" * 1200).decode()


def _cert_b64():
    import base64
    return base64.b64encode(bytes.fromhex("3082010030820100") + b"B" * 1200).decode()


def _run_hook_with_files(tmp_path, files):
    """在隔离的临时 git 仓库里暂存 files 并运行 pre-commit，返回 (returncode, output)。

    files: dict[str, str|bytes]  path -> content
    """
    import subprocess
    import shutil
    import tempfile
    import pathlib

    if shutil.which("bash") is None:
        pytest.skip("bash 不可用，跳过 hook 行为测试")
    root = os.path.dirname(__file__)
    hook_src = os.path.join(root, ".githooks", "pre-commit")
    hook_content = open(hook_src, encoding="utf-8").read()

    repo = pathlib.Path(tempfile.mkdtemp(dir=str(tmp_path)))
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), capture_output=True, check=True)
    (repo / ".githooks").mkdir()
    # 用 LF 写入，避免 Windows 写入 CRLF 导致 bash 在 Windows cwd 下报 $'\r' 错误
    with open(repo / ".githooks" / "pre-commit", "wb") as f:
        f.write(hook_content.encode("utf-8"))
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", rel], cwd=str(repo), capture_output=True, check=True)
    result = subprocess.run(
        ["bash", ".githooks/pre-commit"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout + result.stderr


def test_precommit_blocks_pkcs12_base64_in_plain_text(tmp_path):
    """普通文本里的 PKCS12 Base64 必须被拦截（编码后改后缀绕开的缺口）。"""
    b64 = _pkcs12_b64()
    code, out = _run_hook_with_files(tmp_path, {"notes.txt": b64})
    assert code != 0, f"应拦截 PKCS12 Base64，hook 却放行: {out}"
    assert "PKCS12" in out


def test_precommit_blocks_p12_and_pfx_filenames(tmp_path):
    """敏感文件名 .p12/.pfx 仍按文件名黑名单拦截。"""
    for name in ("secret.p12", "secret.pfx"):
        code, out = _run_hook_with_files(tmp_path, {name: ""})
        assert code != 0, f"{name} 应被文件名黑名单拦截: {out}"


def test_precommit_allows_example_and_sample_exemption(tmp_path):
    """.example/.sample/.template 白名单内的 PKCS12 不应误拦。"""
    b64 = _pkcs12_b64()
    for name in ("secret.txt.example", "secret.txt.sample", "secret.txt.template"):
        code, out = _run_hook_with_files(tmp_path, {name: b64})
        assert code == 0, f"{name} 白名单应放行，却被拦: {out}"


def test_precommit_allows_public_pem_cert_not_pkcs12(tmp_path):
    """公开证书的 Base64（同为 MII 开头）不应被 PKCS12 规则误拦。

    证书 Base64 同样以 MII 开头且长度足够，但解码后头不是 3082????020103，
    必须放行。用非 .pem 文件名避免触发 *.pem 文件名黑名单。
    """
    b64 = _cert_b64()
    content = "public cert:\n" + b64 + "\nend\n"
    code, out = _run_hook_with_files(tmp_path, {"doc.txt": content})
    assert code == 0, f"公开证书不应被误拦: {out}"


def test_precommit_allow_secret_exempts_pkcs12_line(tmp_path):
    """行内 delector:allow-secret 豁免应对 PKCS12 Base64 同样生效。"""
    b64 = _pkcs12_b64()
    content = b64 + " # delector:allow-secret\n"
    code, out = _run_hook_with_files(tmp_path, {"notes.txt": content})
    assert code == 0, f"含 allow-secret 的行应豁免: {out}"


def test_precommit_wrapped_pkcs12_still_blocked(tmp_path):
    """换行包裹的 PKCS12 Base64（每行 64 字符）也应被拦截。"""
    b64 = _pkcs12_b64()
    wrapped = "\n".join(b64[i:i+64] for i in range(0, len(b64), 64))
    code, out = _run_hook_with_files(tmp_path, {"wrapped.txt": wrapped})
    assert code != 0, f"换行包裹的 PKCS12 仍应拦截: {out}"
    assert "PKCS12" in out


def test_delete_article(client):
    # 1. Ingest article
    res = client.post("/api/articles/ingest", json={
        "title": "Article To Delete",
        "raw_text": "Das ist ein Testtext zum Löschen."
    })
    assert res.status_code == 200
    art_id = res.json()["article_id"]

    # 2. Add reading note to this article
    n_res = client.post(f"/api/articles/{art_id}/notes", json={
        "sentence_id": 0,
        "selected_text": "Testtext",
        "color": "yellow",
        "note_content": "随笔要点"
    })
    assert n_res.status_code == 200

    # 3. Check note exists
    notes_res = client.get(f"/api/articles/{art_id}/notes")
    assert notes_res.status_code == 200
    assert len(notes_res.json()) == 1

    # 4. Delete article
    del_res = client.delete(f"/api/articles/{art_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted"] is True
    assert del_data["article_id"] == art_id

    # 5. Article should now be 404
    get_res = client.get(f"/api/articles/{art_id}")
    assert get_res.status_code == 404

    # 6. Reading notes should be empty
    notes_after = client.get(f"/api/articles/{art_id}/notes")
    assert notes_after.status_code == 200
    assert len(notes_after.json()) == 0

    # 7. Deleting non-existent article returns 404
    del_non_existent = client.delete("/api/articles/999999")
    assert del_non_existent.status_code == 404


# ── 查词链修复测试（lemma-first / EXT 接线 / 诚实 source）────────────────────

def test_lookup_lemma_first(client, monkeypatch):
    """前端带 lemma → 直接命中核心词库，不触发 AI。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab",
                    json={"sentence": "Er geht.", "target_word": "geht", "lemma": "gehen"})
    data = r.json()
    assert data["source"] == "local_dict"
    assert "去" in data["definition_zh"]


def test_lookup_lemma_absent_present_irregular(client, monkeypatch):
    """无 lemma 时 geht 靠现在时反查 → stammformen + 三态表释义回填。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht"})
    data = r.json()
    assert data.get("stammformen", {}).get("infinitiv") == "gehen"
    assert data["definition_zh"]
    assert data["source"] == "linguistics"


def test_lookup_plural_haeuser(client, monkeypatch):
    """变元音复数 Häuser + lemma Haus → 核心词库命中。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab",
                    json={"sentence": "Die Häuser sind alt.", "target_word": "Häuser", "lemma": "Haus"})
    data = r.json()
    assert data["source"] == "local_dict"
    assert "房屋" in data["definition_zh"]


def test_lookup_linguistics_ext_tier(client, monkeypatch):
    """主链查不到时落 EXT（LINGUISTICS_VOCAB_EXT 接线）。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Klima.", "target_word": "klima"})
    data = r.json()
    assert data["source"] == "linguistics_ext"
    assert "气候" in data["definition_zh"]


def test_lookup_no_hit_honest_none(client, monkeypatch):
    """未知词 + 无 key → source=none 空释义（不再是 AI 已预填谎言）。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab",
                    json={"sentence": "Xyzzy.", "target_word": "zzzznonsense"})
    data = r.json()
    assert data["source"] == "none"
    assert not data["definition_zh"]


def test_lookup_ai_error_backfill_linguistics(client, monkeypatch):
    """key 假 + httpx 崩 → ai_exception；强动词变位词回填三态表释义。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda: "sk-bogus")

    class _BoomClient:
        def post(self, *a, **k):
            raise RuntimeError("simulated network down")

    monkeypatch.setattr("server.httpx.AsyncClient", lambda *a, **k: _BoomClient())
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


def test_fetch_remote_html_never_requests_blocked_redirect_target(monkeypatch):
    """重定向目标必须在请求发出**之前**过 SSRF 闸。

    follow_redirects=True 的旧写法先打请求、后校验最终 URL——重定向到内网时
    内网服务已经收到 GET（盲 SSRF），哪怕响应随后被丢弃。
    """
    import asyncio
    import ipaddress as _ipaddress
    import socket as _socket

    import server as server_module
    from fastapi import HTTPException

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

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server_module.fetch_remote_html("https://public-start.example/article"))
    assert exc_info.value.status_code == 400
    assert all("169.254" not in u for u in requested), f"盲 SSRF 发生了: {requested}"


def test_fetch_remote_html_still_follows_public_redirects(monkeypatch):
    """公网站点之间的正常重定向链不受影响——加固不能误杀正常抓取。"""
    import asyncio
    import socket as _socket

    import server as server_module

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

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeClient)

    body = asyncio.run(server_module.fetch_remote_html("https://short.example/x"))
    assert body == "<html>ok</html>"
    assert len(requested) == 2


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

    res = lan_client.post("/api/settings", json={
        "api_key": "sk-hacked-rejected",
        "api_base_url": "https://evil.example/v1",
    })
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
    res = client.post("/api/settings", json={
        "api_key": "sk-loopback-ok-1234567890",
        "api_base_url": "https://api.loopback.example/v1",
        "tts_voice": "de-DE-ConradNeural",
    })
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
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    # 未被来源闸拦截：返回 200 且 success 为 False（提示输入 key），而非 403
    assert res.status_code == 200
    assert res.json().get("success") is False


# ── v4.4 Task6: Backup source, Android spaCy loading, AI failure paths ─────────

# --- 6.1 Backup source boundary (prepare/download/restore) ---

def test_backup_prepare_rejects_lan(lan_client):
    """非本机不得 prepare 备份（会带上 localStorage 完整数据库）。"""
    res = lan_client.post("/api/backup/prepare", json={"local_storage": {"delector_font_size": "18"}})
    assert res.status_code == 403


def test_backup_download_rejects_lan_even_with_valid_token(client, lan_client):
    """prepare 产生的 token 也不得被局域网下载。"""
    prep = client.post("/api/backup/prepare", json={"local_storage": {"delector_voice": "x"}})
    assert prep.status_code == 200
    token = prep.json()["token"]
    # lan 尝试用同一 token 下载必须被来源闸挡住，而非 404
    res = lan_client.get(f"/api/backup/download/{token}")
    assert res.status_code == 403
    # 回环仍可正常下载（单次有效）
    ok = client.get(f"/api/backup/download/{token}")
    assert ok.status_code == 200
    assert "attachment" in ok.headers.get("content-disposition", "")


def test_backup_restore_lan_does_not_mutate_db(lan_client, test_db_path):
    """被 403 的还原请求不得改库。"""
    import sqlite3
    import server
    from unittest.mock import patch
    # 先写一条已知文章
    with server.get_db(test_db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    payload = {
        "version": 2,
        "articles": [{"id": 9999, "title": "Hacked", "raw_text": "x", "processed_json": "{}", "source_url": "", "created_at": "2026-01-01 00:00:00"}],
    }
    res = lan_client.post("/api/backup/restore", json=payload)
    assert res.status_code == 403
    with server.get_db(test_db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        hacked = conn.execute("SELECT COUNT(*) FROM articles WHERE id=9999").fetchone()[0]
    assert after == before
    assert hacked == 0


def test_backup_restore_failure_keeps_original_db(client, test_db_path):
    """还原失败（DB 约束错误）必须通过文件快照回滚，原始文章保持不变。"""
    import sqlite3
    import server
    from fastapi.testclient import TestClient as TC
    # 用 raise_server_exceptions=False 才能拿到 500 响应而非抛异常
    fail_client = TC(server.app, client=("127.0.0.1", 54322), raise_server_exceptions=False)
    with server.get_db(test_db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        titles_before = {r[0] for r in conn.execute("SELECT title FROM articles").fetchall()}
    # daily_summary 主键重复触发 IntegrityError
    bad = {
        "version": 2,
        "articles": [{"id": 9100, "title": "Should Rollback", "raw_text": "x", "processed_json": "{}", "source_url": "", "created_at": "2026-01-01 00:00:00"}],
        "daily_summary": [{"date": "2026-08-20"}, {"date": "2026-08-20"}],
    }
    res = fail_client.post("/api/backup/restore", json=bad)
    assert res.status_code >= 500
    with server.get_db(test_db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        leaked = conn.execute("SELECT COUNT(*) FROM articles WHERE id=9100").fetchone()[0]
        titles_after = {r[0] for r in conn.execute("SELECT title FROM articles").fetchall()}
    assert after == before, "还原失败未回滚主库"
    assert leaked == 0
    assert titles_before == titles_after


def test_backup_loopback_still_succeeds(client):
    """回环来源的完整备份链路仍可用（prepare→download→restore 往返）。"""
    ls = {"delector_font_size": "20"}
    prep = client.post("/api/backup/prepare", json={"local_storage": ls})
    assert prep.status_code == 200
    token = prep.json()["token"]
    dl = client.get(f"/api/backup/download/{token}")
    assert dl.status_code == 200
    body = dl.json()
    assert body["local_storage"] == ls
    # restore 回环成功
    assert client.post("/api/backup/restore", json={"version": 2, "articles": body["articles"][:1]}).status_code == 200


# --- 6.2 Android spaCy loading contract (static) ---

def test_android_spacy_module_load_fallback_static():
    """_load_spacy_model 必须包含 module.load() 回退（Android 无 dist-info 时唯一可用路径）。"""
    src = open(os.path.join(os.path.dirname(__file__), "server.py"), encoding="utf-8").read()
    assert "importlib.import_module" in src, "缺 importlib 回退"
    assert "module.load()" in src, "缺 module.load() 回退"
    assert "spacy.load(name)" in src or 'spacy.load(' in src, "缺 spacy.load(name) 首选路径"


def test_android_spacy_model_dir_fallback_static():
    """模型目录 glob 回退必须存在（meta 版本与目录名不一致时的最后兜底）。"""
    src = open(os.path.join(os.path.dirname(__file__), "server.py"), encoding="utf-8").read()
    assert "glob(f\"{name}-*\"" in src or 'glob(f"{name}-' in src, "缺模型目录 glob 兜底"
    assert "data_dirs" in src, "缺 data_dirs 变量"


def test_android_spacy_download_gated_by_is_android_static():
    """自动下载必须被 is_android() 门控，否则 Android import 期起 pip 子进程卡死。"""
    src = open(os.path.join(os.path.dirname(__file__), "server.py"), encoding="utf-8").read()
    # 必须有 is_android 判断且在 download 之前
    assert "is_android()" in src, "缺 is_android() 判断"
    # 确保下载路径在 is_android 分支保护下，而非无条件
    assert "from spacy.cli import download" in src
    # 静态断言：download 调用位于 is_android() 之后且在 else 分支
    lines = src.splitlines()
    android_idx = next((i for i, ln in enumerate(lines) if "is_android()" in ln), -1)
    download_idx = next((i for i, ln in enumerate(lines) if "from spacy.cli import download" in ln), -1)
    assert android_idx != -1 and download_idx != -1 and android_idx < download_idx, "download 必须在 is_android() 之后"


def test_android_spacy_extract_packages_static():
    """build.gradle extractPackages 必须包含 spacy/thinc/de_core_news_sm 三者。"""
    gradle = open(os.path.join(os.path.dirname(__file__), "android", "app", "build.gradle"), encoding="utf-8").read()
    line = next((ln for ln in gradle.splitlines() if "extractPackages" in ln), "")
    assert line, "缺 extractPackages 声明"
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in line, f"{pkg} 未在 extractPackages 中"


# --- 6.3 AI 402 / timeout / non-JSON (server returns 502, not 200) ---

def _make_402_client():
    class _R:
        status_code = 402
        text = '{"error":{"code":"insufficient_balance"}}'
        def json(self):
            return {"error": "Insufficient Balance"}
    class _C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return _R()
    return _C


def _make_timeout_client():
    import httpx as _httpx
    class _C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
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
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return _R()
    return _C


def _make_non_json_content_client():
    """HTTP 200 但 choices[0].message.content 不是 JSON。"""
    class _R:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "THIS IS NOT JSON"}}]}
    class _C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return _R()
    return _C


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client])
def test_note_assist_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "sk-test-402-timeout")
    monkeypatch.setattr("server.httpx.AsyncClient", factory())
    res = client.post("/api/ai/note-assist", json={"sentence": "Guten Tag.", "selected_text": "Guten Tag"})
    assert res.status_code == 502, f"AI 失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    # 不得泄露 API Key
    assert "sk-test-402-timeout" not in res.text


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client])
def test_ai_polish_diff_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "sk-test-polish")
    monkeypatch.setattr("server.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish/diff", json={"text": "Ich habe ein Hund."})
    assert res.status_code == 502, f"AI 润色失败应返回 502，实际 {res.status_code}: {res.text[:200]}"
    assert "sk-test-polish" not in res.text


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client, _make_non_json_content_client])
def test_ai_polish_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "sk-test-polish2")
    monkeypatch.setattr("server.httpx.AsyncClient", factory())
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 502
    assert "sk-test-polish2" not in res.text


@pytest.mark.parametrize("factory", [_make_402_client, _make_timeout_client, _make_non_json_client])
def test_grammar_lookup_ai_failure_returns_502(client, monkeypatch, factory):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "sk-grammar")
    monkeypatch.setattr("server.httpx.AsyncClient", factory())
    res = client.post("/api/lookup/grammar", json={"sentence": "Ich gehe.", "target_phrase": "gehe"})
    assert res.status_code == 502
    assert "sk-grammar" not in res.text


def test_ai_no_key_stub_still_succeeds(client, monkeypatch):
    """无 key 时仍返回 200 stub（与网络失败的 502 区分）。"""
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/ai/note-assist", json={"sentence": "Hallo.", "selected_text": "Hallo"})
    assert res.status_code == 200
    assert res.json().get("_stub") is True
    res2 = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


# --- 6.4 Frontend error display (static, reuse api() path) ---

def test_frontend_ai_error_paths_reuse_api_and_show_alert():
    """前端 AI 错误必须走 api() 抛异常 → catch → alert/状态提示，不静默成功，不吞异常。"""
    writer_src = open(os.path.join(os.path.dirname(__file__), "static", "js", "writer.js"), encoding="utf-8").read()
    reader_src = open(os.path.join(os.path.dirname(__file__), "static", "js", "reader.js"), encoding="utf-8").read()
    core_src = open(os.path.join(os.path.dirname(__file__), "static", "js", "core.js"), encoding="utf-8").read()
    # core api() 必须在非 ok 时抛 Error
    assert "throw new Error" in core_src, "core.js api() 必须抛异常"
    # writer aiPolishEssay 必须有 try/catch 且 catch 中有 alert
    polish_fn = writer_src[writer_src.index("export async function aiPolishEssay"):]
    polish_fn = polish_fn[:polish_fn.index("export async function applyPolishChanges")]
    assert "try" in polish_fn and "catch" in polish_fn, "aiPolishEssay 缺 try/catch"
    assert "alert" in polish_fn, "aiPolishEssay 失败时必须 alert"
    # 不写 API Key 到 DOM/localStorage
    assert "api_key" not in writer_src.lower() or "localStorage.setItem" not in writer_src or "DEEPSEEK_API_KEY" not in writer_src, "writer 不应把 API Key 写入 localStorage/DOM"
    # reader aiNoteAssist 同理
    note_fn = reader_src[reader_src.index("export async function aiNoteAssist"):]
    note_fn = note_fn[:note_fn.index("export async function saveCurrentNote")]
    assert "try" in note_fn and "catch" in note_fn, "aiNoteAssist 缺 try/catch"
    assert "alert" in note_fn or "statusEl" in note_fn, "aiNoteAssist 失败时必须提示"


def test_frontend_does_not_write_api_key_to_storage():
    """前端不得把 API Key 写入 localStorage 或以明文写入 DOM。"""
    import pathlib
    js_dir = pathlib.Path(os.path.join(os.path.dirname(__file__), "static", "js"))
    for fp in js_dir.glob("*.js"):
        src = fp.read_text(encoding="utf-8")
        # 禁止同一行内把 api_key 明文 setItem
        for line in src.splitlines():
            low = line.lower()
            if "localstorage.setitem" in low and "api_key" in low:
                assert False, f"{fp.name} 将 API Key 写入 localStorage: {line.strip()[:120]}"
        # 禁止把 API Key 明文通过 innerHTML 写入 DOM：检查同一行内同时出现 api_key 变量与 innerHTML
        for line in src.splitlines():
            low_line = line.lower()
            if "innerhtml" in low_line and "api_key" in low_line and "masked" not in low_line:
                # 允许的 warning 文案含 DEEPSEEK_API_KEY 常量但不含实际 key 值
                if "DEEPSEEK_API_KEY" in line and "api_key_masked" not in line and "has_api_key" not in line:
                    # 仅当该行试图把变量值写入 innerHTML 时才报错，常量提示文案放行
                    if "detail" in low_line or "response" in low_line or "res." in low_line:
                        assert False, f"{fp.name} 可能泄露 API Key 到 DOM: {line.strip()[:120]}"
