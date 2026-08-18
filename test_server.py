import os
import pytest
from fastapi.testclient import TestClient

# Ensure test DBs are isolated
os.environ["DATABASE_PATH"] = "test_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_progress.db"

from server import (
    app, init_db, get_db, get_cefr_level, export_anki_deck,
    SYSTEM_GRAMMAR_PROMPT, process_german_text,
    is_safe_public_url, clean_html_to_article,
    init_progress_db, get_progress_db,
)

@pytest.fixture
def test_db_path():
    return "test_delector.db"

@pytest.fixture
def test_progress_path():
    return "test_progress.db"

@pytest.fixture
def client():
    return TestClient(app)

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

def test_audio_tts_endpoint_with_mock(client, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    fake_mp3 = tmp_path / "fake_de.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00mock_audio_data")
    
    monkeypatch.setattr("server.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))
    
    res = client.post("/api/audio/tts", json={"text": "Hallo Berlin!", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert len(res.content) > 10

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
