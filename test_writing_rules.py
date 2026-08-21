# -*- coding: utf-8 -*-
"""Unit tests for writing_rules.py local rule engine."""
import pytest
import spacy
from writing_rules import analyze_essay_text, decline_determiner


@pytest.fixture(scope="module")
def nlp():
    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


def _spans(text, nlp):
    result = analyze_essay_text(text, nlp)
    return [span for sent in result["sentences"] for span in sent["spans"]]


def test_agreement_wrong_case(nlp):
    spans = _spans("Ich sehe der Mann.", nlp)
    assert spans, "Expected agreement error span"
    assert spans[0]["error_type"] == "artikel"
    assert "den Mann" in spans[0]["corrected_form"]


def test_agreement_correct_sentence_clean(nlp):
    assert _spans("Ich sehe den Mann.", nlp) == []


def test_prep_governed_case_dativ(nlp):
    spans = _spans("Ich fahre mit der Auto.", nlp)
    assert spans, "Expected preposition case error span"
    assert spans[0]["error_type"] == "kasus"
    assert "dem Auto" in spans[0]["corrected_form"]


def test_prep_one_case_correct_clean(nlp):
    assert _spans("Ich fahre mit dem Auto.", nlp) == []


def test_two_case_preposition_skipped(nlp):
    assert _spans("Ich gehe in der Stadt.", nlp) == []


def test_fixed_verb_prep_collocation(nlp):
    spans = _spans("Er wartet auf dem Bus.", nlp)
    assert spans, "Expected fixed preposition error span"
    assert spans[0]["error_type"] == "praeposition"
    assert "den Bus" in spans[0]["corrected_form"]
    assert "warten auf" in spans[0]["explanation_zh"]


def test_no_determiner_not_flagged(nlp):
    assert _spans("Ich fahre mit Auto.", nlp) == []


def test_no_spacy_returns_empty():
    r = analyze_essay_text("Ich sehe der Mann.", None)
    assert r["error_count"] == 0
    assert "cefr" in r
    assert r["version"] == "4.0.0"
    assert r["sentences"] == []


def test_decline_determiner_basic():
    assert decline_determiner("der", "Masc", "Sing", "Nom") == "der"
    assert decline_determiner("der", "Masc", "Sing", "Akk") == "den"
    assert decline_determiner("der", "Masc", "Sing", "Dat") == "dem"
    assert decline_determiner("der", "Masc", "Sing", "Gen") == "des"
    assert decline_determiner("der", "Fem", "Sing", "Nom") == "die"
    assert decline_determiner("der", "Neut", "Sing", "Dat") == "dem"
    assert decline_determiner("ein", "Masc", "Sing", "Akk") == "einen"
    assert decline_determiner("kein", "Neut", "Sing", "Dat") == "keinem"
    assert decline_determiner("invalid", "Masc", "Sing", "Nom") is None


def test_multi_sentence_analysis(nlp):
    text = "Ich sehe der Mann. Ich fahre mit dem Auto."
    result = analyze_essay_text(text, nlp)
    assert result["version"] == "4.0.0"
    assert result["error_count"] == 1
    assert len(result["sentences"]) == 2
    assert len(result["sentences"][0]["spans"]) == 1
    assert len(result["sentences"][1]["spans"]) == 0


def test_analyze_essay_pure_python_fallback():
    """nlp=None 降级模式：零误报，只给 CEFR 估分。"""
    text = "Ich lerne Deutsch. Das Buch ist interessant."
    result = analyze_essay_text(text, nlp=None)
    assert result["version"] == "4.0.0"
    assert result["error_count"] == 0
    assert len(result["sentences"]) == 0
    assert result["cefr"]["word_count"] > 0

