import os
import pytest
from fastapi.testclient import TestClient

# Ensure test DB
os.environ["DATABASE_PATH"] = "test_delector.db"
from server import app, init_db, get_db, get_cefr_level, export_anki_deck, SYSTEM_GRAMMAR_PROMPT, process_german_text, is_safe_public_url, clean_html_to_article

@pytest.fixture
def test_db_path():
    return "test_delector.db"

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    if os.path.exists("test_delector.db"):
        try:
            os.remove("test_delector.db")
        except OSError:
            pass
    init_db("test_delector.db")
    yield
    if os.path.exists("test_delector.db"):
        try:
            os.remove("test_delector.db")
        except OSError:
            pass

def test_cefr_lookup():
    assert get_cefr_level("gehen") == "A1"
    assert get_cefr_level("beeinträchtigen") in ("B2", "C1")

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
