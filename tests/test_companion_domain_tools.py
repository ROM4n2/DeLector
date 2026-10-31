# -*- coding: utf-8 -*-
"""Tests for companion domain-native tools: get_learner_profile and query_dictionary."""

import asyncio
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

from delector.tools.dictionary import query_dictionary
from delector.tools.dictionary import run as run_dictionary
from delector.tools.learner_profile import get_learner_profile
from delector.tools.learner_profile import run as run_learner_profile


@pytest.fixture
def mock_db_path(tmp_path):
    """Create a temporary SQLite database for learner profile tests."""
    db_file = tmp_path / "test_progress.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE vocab_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            word TEXT NOT NULL,
            lemma TEXT NOT NULL,
            pos TEXT,
            gender TEXT,
            plural TEXT,
            cefr_level TEXT,
            definition_zh TEXT NOT NULL,
            sentence_context TEXT NOT NULL,
            mastered INTEGER DEFAULT 0,
            mastered_at TIMESTAMP,
            correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            due_date TEXT,
            interval_days INTEGER DEFAULT 1,
            ease_factor REAL DEFAULT 2.5,
            repetition_count INTEGER DEFAULT 0,
            source TEXT DEFAULT 'user',
            stability REAL,
            fsrs_s REAL,
            fsrs_d REAL,
            fsrs_lapses INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()
    return str(db_file)


# ==============================================================================
# 1. get_learner_profile Tests
# ==============================================================================


def test_get_learner_profile_empty_db(mock_db_path, monkeypatch):
    """An empty database returns default values with status ok."""
    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res = get_learner_profile()
    assert res == {
        "status": "ok",
        "total_known_words": 0,
        "current_level_estimate": "A1",
        "fsrs_due_count": 0,
        "weakest_roots": [],
    }


def test_get_learner_profile_none_and_empty_payload(mock_db_path, monkeypatch):
    """Calling with None or empty payload works without errors."""
    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res_none = get_learner_profile(None)
    assert res_none["status"] == "ok"
    assert res_none["total_known_words"] == 0

    res_empty = get_learner_profile({})
    assert res_empty["status"] == "ok"


def test_get_learner_profile_no_vocab_table(tmp_path, monkeypatch):
    """Database without vocab_cards table gracefully returns defaults."""
    empty_db = tmp_path / "no_vocab.db"
    conn = sqlite3.connect(str(empty_db))
    conn.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(str(empty_db)),
    )
    res = get_learner_profile()
    assert res == {
        "status": "ok",
        "total_known_words": 0,
        "current_level_estimate": "A1",
        "fsrs_due_count": 0,
        "weakest_roots": [],
    }


def test_get_learner_profile_db_error_resilience(monkeypatch):
    """If get_progress_db raises an exception, return defaults safely."""
    def _raise():
        raise sqlite3.OperationalError("Database disk image is malformed")

    monkeypatch.setattr("delector.tools.learner_profile.get_progress_db", _raise)
    res = get_learner_profile()
    assert res == {
        "status": "ok",
        "total_known_words": 0,
        "current_level_estimate": "A1",
        "fsrs_due_count": 0,
        "weakest_roots": [],
    }


def test_get_learner_profile_known_words_and_levels(mock_db_path, monkeypatch):
    """Test known words calculation (mastered=1 or stability>=21.0) and level estimation."""
    conn = sqlite3.connect(mock_db_path)
    # Insert 10 mastered cards
    for i in range(10):
        conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, wrong_count)
            VALUES (?, ?, 'def', 'ctx', 1, 0)
            """,
            (f"w_m_{i}", f"l_m_{i}"),
        )
    # Insert 5 cards with stability >= 21.0 (mastered = 0)
    for i in range(5):
        conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, stability, wrong_count)
            VALUES (?, ?, 'def', 'ctx', 0, 25.5, 0)
            """,
            (f"w_s_{i}", f"l_s_{i}"),
        )
    # Insert 3 cards with fsrs_s >= 21.0 (mastered = 0)
    for i in range(3):
        conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, fsrs_s, wrong_count)
            VALUES (?, ?, 'def', 'ctx', 0, 22.0, 0)
            """,
            (f"w_f_{i}", f"l_f_{i}"),
        )
    # Insert unlearned cards (mastered = 0, stability < 21.0)
    for i in range(4):
        conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, stability, wrong_count)
            VALUES (?, ?, 'def', 'ctx', 0, 10.0, 0)
            """,
            (f"w_u_{i}", f"l_u_{i}"),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res = get_learner_profile()
    # 10 mastered + 5 with stability >= 21 + 3 with fsrs_s >= 21 = 18 total known
    assert res["total_known_words"] == 18
    assert res["current_level_estimate"] == "A1"


@pytest.mark.parametrize(
    ("known_count", "expected_level"),
    [
        (0, "A1"),
        (499, "A1"),
        (500, "A2"),
        (1199, "A2"),
        (1200, "B1"),
        (2499, "B1"),
        (2500, "B2"),
        (3500, "B2"),
    ],
)
def test_get_learner_profile_level_brackets(tmp_path, monkeypatch, known_count, expected_level):
    """Test CEFR level estimation brackets: A1 (<500), A2 (<1200), B1 (<2500), B2 (>=2500)."""
    db_file = tmp_path / f"test_level_{known_count}.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE vocab_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            lemma TEXT,
            definition_zh TEXT,
            sentence_context TEXT,
            mastered INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            due_date TEXT
        );
        """
    )
    # Efficiently insert known_count rows
    conn.executemany(
        """
        INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, wrong_count)
        VALUES (?, ?, 'd', 's', 1, 0)
        """,
        [(f"w{i}", f"l{i}") for i in range(known_count)],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(str(db_file)),
    )
    res = get_learner_profile()
    assert res["total_known_words"] == known_count
    assert res["current_level_estimate"] == expected_level


def test_get_learner_profile_fsrs_due_count(mock_db_path, monkeypatch):
    """Cards where due_date <= date('now') and mastered = 0 are counted in fsrs_due_count."""
    conn = sqlite3.connect(mock_db_path)
    # 2 due today/past, unmastered -> should be counted
    conn.execute(
        """
        INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, due_date)
        VALUES ('d1', 'd1', 'd', 'c', 0, '2020-01-01')
        """
    )
    conn.execute(
        """
        INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, due_date)
        VALUES ('d2', 'd2', 'd', 'c', 0, date('now'))
        """
    )
    # 1 due today, but mastered = 1 -> should NOT be counted
    conn.execute(
        """
        INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, due_date)
        VALUES ('d3', 'd3', 'd', 'c', 1, date('now'))
        """
    )
    # 1 due in the future -> should NOT be counted
    conn.execute(
        """
        INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, mastered, due_date)
        VALUES ('d4', 'd4', 'd', 'c', 0, '2099-12-31')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res = get_learner_profile()
    assert res["fsrs_due_count"] == 2


def test_get_learner_profile_weakest_roots(mock_db_path, monkeypatch):
    """Top 3-5 lemmas with highest wrong_count > 0 are returned in weakest_roots."""
    conn = sqlite3.connect(mock_db_path)
    lemmas_and_wrongs = [
        ("schreiben", 12),
        ("sprechen", 9),
        ("lesen", 7),
        ("hören", 5),
        ("sehen", 3),
        ("gehen", 1),
        ("kommen", 0),  # wrong_count == 0 must not be included
    ]
    for lemma, wrong in lemmas_and_wrongs:
        conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, wrong_count)
            VALUES (?, ?, 'def', 'ctx', ?)
            """,
            (lemma, lemma, wrong),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res = get_learner_profile()
    # Should contain top 5 lemmas descending
    assert res["weakest_roots"] == ["schreiben", "sprechen", "lesen", "hören", "sehen"]
    assert "gehen" not in res["weakest_roots"]
    assert "kommen" not in res["weakest_roots"]


def test_get_learner_profile_async_run(mock_db_path, monkeypatch):
    """Async run wrapper returns the profile dictionary."""
    monkeypatch.setattr(
        "delector.tools.learner_profile.get_progress_db",
        lambda *args, **kwargs: sqlite3.connect(mock_db_path),
    )
    res = asyncio.run(run_learner_profile({}))
    assert res["status"] == "ok"
    assert "total_known_words" in res


# ==============================================================================
# 2. query_dictionary Tests
# ==============================================================================


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"lemma": ""},
        {"lemma": "   "},
        {"lemma": None},
        {"other": "value"},
    ],
)
def test_query_dictionary_missing_or_empty_lemma(bad_payload):
    """Empty or missing lemma returns error status with message."""
    res = query_dictionary(bad_payload)
    assert res == {"status": "error", "message": "lemma is required"}


def test_query_dictionary_real_word_kommen():
    """Looking up 'kommen' returns definitions and preposition collocations."""
    res = query_dictionary({"lemma": "kommen"})
    assert res["status"] == "ok"
    assert res["lemma"] == "kommen"
    assert isinstance(res["definitions_zh"], list)
    assert len(res["definitions_zh"]) > 0
    assert any("来" in d for d in res["definitions_zh"])

    assert isinstance(res["collocations"], list)
    assert len(res["collocations"]) > 0
    # Ensure standard collocation structure is present
    first_col = res["collocations"][0]
    assert "praeposition" in first_col
    assert "kasus" in first_col
    assert "bedeutung_zh" in first_col


def test_query_dictionary_real_word_buch():
    """Looking up 'Buch' returns definitions and empty collocations."""
    res = query_dictionary({"lemma": "Buch"})
    assert res["status"] == "ok"
    assert res["lemma"] == "Buch"
    assert isinstance(res["definitions_zh"], list)
    assert len(res["definitions_zh"]) > 0
    assert any("书" in d for d in res["definitions_zh"])

    assert isinstance(res["collocations"], list)
    assert res["collocations"] == []


def test_query_dictionary_unknown_word():
    """An unknown word returns status ok with empty definitions and collocations."""
    res = query_dictionary({"lemma": "xyznotagermanword999"})
    assert res == {
        "status": "ok",
        "lemma": "xyznotagermanword999",
        "definitions_zh": [],
        "collocations": [],
    }


def test_query_dictionary_mocked_external_modules(monkeypatch):
    """When delector.core.linguistics and delector.core.prep_dict are present, they are queried."""
    fake_ling = types.ModuleType("delector.core.linguistics")
    setattr(fake_ling, "lookup_lemma", MagicMock(return_value={"definitions_zh": ["测试释义1", "测试释义2"]}))

    fake_prep = types.ModuleType("delector.core.prep_dict")
    setattr(
        fake_prep,
        "lookup_prep_collocations",
        MagicMock(
            return_value=[{"praeposition": "an", "kasus": "Dat", "bedeutung_zh": "在...旁", "beispiel": "an der Ecke"}]
        ),
    )

    monkeypatch.setitem(sys.modules, "delector.core.linguistics", fake_ling)
    monkeypatch.setitem(sys.modules, "delector.core.prep_dict", fake_prep)

    res = query_dictionary({"lemma": "testwort"})
    assert res["status"] == "ok"
    assert res["lemma"] == "testwort"
    assert res["definitions_zh"] == ["测试释义1", "测试释义2"]
    assert res["collocations"] == [
        {"praeposition": "an", "kasus": "Dat", "bedeutung_zh": "在...旁", "beispiel": "an der Ecke"}
    ]
    fake_ling.lookup_lemma.assert_called_once_with("testwort")
    fake_prep.lookup_prep_collocations.assert_called_once_with("testwort")


def test_query_dictionary_async_run():
    """Async run wrapper returns the query result."""
    res = asyncio.run(run_dictionary({"lemma": "Buch"}))
    assert res["status"] == "ok"
    assert res["lemma"] == "Buch"
    assert len(res["definitions_zh"]) > 0


def test_api_tools_route_query_dictionary_and_learner_profile():
    """Verify POST /api/tools/{tool_name} dispatches correctly for companion tools."""
    from fastapi.testclient import TestClient
    from delector.server import app

    client = TestClient(app, client=("127.0.0.1", 54321))
    res_dict = client.post("/api/tools/query_dictionary", json={"payload": {"lemma": "Buch"}})
    assert res_dict.status_code == 200, res_dict.text
    data = res_dict.json()
    assert data["status"] == "ok"
    assert data["lemma"] == "Buch"

    res_prof = client.post("/api/tools/get_learner_profile", json={"payload": {}})
    assert res_prof.status_code == 200, res_prof.text
    prof_data = res_prof.json()
    assert prof_data["status"] == "ok"
    assert "total_known_words" in prof_data
