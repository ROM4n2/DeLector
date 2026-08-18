import os
import pytest
from fastapi.testclient import TestClient

# Ensure test DB
os.environ["DATABASE_PATH"] = "test_delector.db"
from server import app, init_db, get_db, get_cefr_level, export_anki_deck

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
