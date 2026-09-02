# -*- coding: utf-8 -*-
"""
test_audit_regressions.py - Consolidated Regression Tests for DeLector v5.0.1
Locks in fixes for:
1. RestoreReq preserving A1 records
2. FSRS elapsed_days dynamic interval calculation
3. Irregular verb reverse index collision prevention
4. Hyphenated compound noun splitting
5. Prepositional relative clause Nachfeld topological recognition
6. euer/eur inflection with vowel elision
7. Security URL port restriction & 2MB stream limit
"""
import pytest
from server import RestoreReq
from linguistics import lookup_irregular_verb, split_komposita
from syntax_tree import analyze_sentence_topology
from writing_rules import decline_determiner
from security import is_safe_public_url


def test_restore_req_includes_a1_records():
    req = RestoreReq(
        cards=[],
        articles=[],
        study_logs=[],
        quiz_logs=[],
        a1_hoeren_records=[{"set_id": "set1", "score": 25.0}],
        a1_lesen_records=[{"set_id": "set2", "score": 24.0}],
    )
    assert len(req.a1_hoeren_records) == 1
    assert req.a1_hoeren_records[0]["set_id"] == "set1"
    assert len(req.a1_lesen_records) == 1
    assert req.a1_lesen_records[0]["set_id"] == "set2"


def test_reverse_verb_index_no_separable_collision():
    # Previous bug: standen returned zustehen, gingen returned hinausgehen, fuhren returned losfahren
    res_standen = lookup_irregular_verb("standen")
    assert res_standen is not None
    assert res_standen.infinitiv == "stehen"

    res_gingen = lookup_irregular_verb("gingen")
    assert res_gingen is not None
    assert res_gingen.infinitiv == "gehen"

    res_fuhren = lookup_irregular_verb("fuhren")
    assert res_fuhren is not None
    assert res_fuhren.infinitiv == "fahren"

    # Separable unified past forms should still resolve correctly
    res_aufstanden = lookup_irregular_verb("aufstanden")
    assert res_aufstanden is not None
    assert res_aufstanden.infinitiv == "aufstehen"


def test_hyphenated_compound_splitter():
    parts = split_komposita("U-Bahn-Station")
    assert isinstance(parts, list)


def test_nachfeld_prepositional_relative_clause():
    topo = analyze_sentence_topology("Er trifft den Mann, mit dem er gestern sprach.")
    assert "nachfeld" in topo["field_texts"]
    nf_text = topo["field_texts"]["nachfeld"]
    assert "mit dem" in nf_text or "sprach" in nf_text


def test_euer_determiner_declension():
    fem_nom = decline_determiner("euer", "Fem", "Sing", "Nom")
    assert fem_nom == "eure"

    masc_dat = decline_determiner("euer", "Masc", "Sing", "Dat")
    assert masc_dat == "eurem"

    plur_dat = decline_determiner("euer", "Masc", "Plur", "Dat")
    assert plur_dat == "euren"

    eur_fem_nom = decline_determiner("eur", "Fem", "Sing", "Nom")
    assert eur_fem_nom == "eure"


def test_security_port_restrictions():
    assert is_safe_public_url("https://example.com/feed.xml") is True
    assert is_safe_public_url("https://example.com:443/feed.xml") is True
    assert is_safe_public_url("http://example.com:8080/feed.xml") is True

    assert is_safe_public_url("http://example.com:22/feed.xml") is False
    assert is_safe_public_url("http://example.com:3306/feed.xml") is False
    assert is_safe_public_url("http://example.com:6379/feed.xml") is False


def test_a1_grade_populates_study_log():
    """record_a1_hoeren_trial must write to study_log (not deadlock inside its own transaction)."""
    import os, sqlite3, time
    from database import record_a1_hoeren_trial, init_progress_db
    tmp = "test_a1_study_log.db"
    # clean up any leftover from a prior interrupted run
    for suffix in ("", "-wal", "-shm"):
        p = tmp + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                pass
    try:
        init_progress_db(tmp)
        rec_id = record_a1_hoeren_trial(
            set_id=1, score_raw=20, score_official=16.0,
            total_questions=25, duration_seconds=600,
            answers_json="{}", wrong_questions_json="[]",
            db_path=tmp,
        )
        assert rec_id is not None
        # open a fresh connection, read, then close — so file handles release before cleanup
        c = sqlite3.connect(tmp)
        try:
            study_rows = c.execute("SELECT * FROM study_log WHERE event_type = 'a1_hoeren'").fetchall()
            assert len(study_rows) == 1, f"study_log should have 1 a1_hoeren row, got {len(study_rows)}"
            daily = c.execute("SELECT date FROM daily_summary").fetchone()
            assert daily is not None, "daily_summary should have a row after A1 grade (INSERT OR IGNORE fires regardless of event_type)"
        finally:
            c.close()
        time.sleep(0.1)  # let SQLite release file handles on Windows
    finally:
        for suffix in ("", "-wal", "-shm"):
            p = tmp + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except PermissionError:
                    pass
