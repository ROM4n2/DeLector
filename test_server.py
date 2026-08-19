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

