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
    assert r["warning_count"] == 0
    assert r["problem_count"] == 0
    assert "cefr" in r
    assert r["version"] == "4.3.0"
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
    assert result["version"] == "4.3.0"
    assert result["error_count"] == 1
    assert result["warning_count"] == 0
    assert result["problem_count"] == 1
    assert len(result["sentences"]) == 2
    assert len(result["sentences"][0]["spans"]) == 1
    assert len(result["sentences"][1]["spans"]) == 0


def test_analyze_essay_pure_python_fallback():
    """nlp=None 降级模式：零误报，只给 CEFR 估分。"""
    text = "Ich lerne Deutsch. Das Buch ist interessant."
    result = analyze_essay_text(text, nlp=None)
    assert result["version"] == "4.3.0"
    assert result["error_count"] == 0
    assert result["warning_count"] == 0
    assert result["problem_count"] == 0
    assert len(result["sentences"]) == 0
    assert result["cefr"]["word_count"] > 0


def _hints(text, nlp):
    result = analyze_essay_text(text, nlp)
    return [hint for sent in result["sentences"] for hint in sent.get("hints", [])]


def test_prep_hint_fixed_case(nlp):
    hints = _hints("Ich fahre mit der Auto.", nlp)
    prep_hints = [h for h in hints if h["type"] == "prep_case"]
    assert any(h["label"] == "mit [Dat]" for h in prep_hints)


def test_prep_hint_two_way(nlp):
    hints = _hints("Ich gehe in der Stadt.", nlp)
    prep_hints = [h for h in hints if h["type"] == "prep_case"]
    assert any(h["label"] == "in [Dat/Akk]" for h in prep_hints)


def test_prep_hint_verb_collocation(nlp):
    hints = _hints("Er wartet auf dem Bus.", nlp)
    prep_hints = [h for h in hints if h["type"] == "prep_case"]
    assert any(h["label"] == "auf [Akk]" for h in prep_hints)


def test_np_hint_gender_case_label(nlp):
    hints = _hints("Ich fahre mit der Auto.", nlp)
    np_hints = [h for h in hints if h["type"] == "np_case"]
    assert any("Neut" in h["label"] for h in np_hints)


def test_hints_coexist_with_error_spans(nlp):
    result = analyze_essay_text("Ich fahre mit der Auto.", nlp)
    sent = result["sentences"][0]
    assert len(sent["spans"]) >= 1
    assert any(h["type"] == "prep_case" for h in sent["hints"])


def test_hints_key_present(nlp):
    result = analyze_essay_text("Ich sehe den Mann.", nlp)
    assert set(result.keys()) == {"version", "cefr", "error_count", "warning_count", "problem_count", "sentences"}
    for sent in result["sentences"]:
        assert "hints" in sent
        assert "warnings" in sent


def test_two_way_prep_emits_warning_not_span(nlp):
    result = analyze_essay_text("Ich gehe in der Stadt.", nlp)
    sent = result["sentences"][0]
    assert sent["spans"] == []
    assert len(sent["warnings"]) >= 1
    w = sent["warnings"][0]
    assert w["severity"] == "warning"
    assert w["error_type"] == "twoway"
    assert "注意" in w["label"] and "in" in w["label"]
    assert "Dat/Akk" in w["explanation_zh"]


def test_span_has_severity_error(nlp):
    result = analyze_essay_text("Ich sehe der Mann.", nlp)
    sent = result["sentences"][0]
    assert len(sent["spans"]) == 1
    assert sent["spans"][0]["severity"] == "error"


def test_warning_and_error_counts(nlp):
    text = "Ich gehe in der Stadt. Ich sehe der Mann."
    result = analyze_essay_text(text, nlp)
    assert result["error_count"] == 1
    assert result["warning_count"] == 1
    assert result["problem_count"] == 2
    assert len(result["sentences"]) == 2


def test_warning_positions_are_char_offsets(nlp):
    text = "Wir sitzen an dem Tisch."
    result = analyze_essay_text(text, nlp)
    sent = result["sentences"][0]
    assert len(sent["warnings"]) >= 1
    w = sent["warnings"][0]
    assert 0 <= w["start"] < w["end"] <= len(sent["text"])


# ── Task 5: 反例测试（零冠词 / 固定搭配 / 双向介词 / 缺失词典性别 / 合法组合） ──

def test_zero_article_nouns_not_flagged(nlp):
    """零冠词名词不应被误报（常见且通常正确）。"""
    for text in [
        "Wasser ist wichtig.",
        "Ich trinke Kaffee.",
        "Ich fahre mit Auto.",
        "Autos sind teuer.",
        "Menschen helfen Menschen.",
        "Bücher sind nützlich.",
    ]:
        assert _spans(text, nlp) == [], f"zero-article FP: {text} -> {_spans(text, nlp)}"


def test_fixed_collocation_correct_clean(nlp):
    """固定搭配正确格位不应误报。"""
    assert _spans("Ich warte auf den Bus.", nlp) == []
    assert _spans("Er leidet an einer Krankheit.", nlp) == []
    assert _spans("Ich freue mich auf das Wochenende.", nlp) == []


def test_fixed_collocation_error_flagged(nlp):
    """固定搭配错误格位应检出（praeposition）。"""
    spans = _spans("Ich warte auf dem Bus.", nlp)
    assert spans and spans[0]["error_type"] == "praeposition"
    assert "den Bus" in spans[0]["corrected_form"]
    spans2 = _spans("Er leidet an eine Krankheit.", nlp)
    assert spans2 and spans2[0]["error_type"] == "praeposition"


def test_two_way_prep_both_cases_clean(nlp):
    """双向介词 Dat/Akk 皆可：只给 warning，不报 error。"""
    for text in [
        "Ich gehe in die Stadt.",
        "Ich bin in der Stadt.",
        "Wir sitzen an dem Tisch.",
        "Wir gehen an den Tisch.",
        "Sie legt das Buch auf den Tisch.",
        "Das Buch liegt auf dem Tisch.",
    ]:
        result = analyze_essay_text(text, nlp)
        errs = [s for sent in result["sentences"] for s in sent["spans"]]
        warns = [w for sent in result["sentences"] for w in sent["warnings"]]
        assert errs == [], f"two-way FP error: {text} -> {errs}"
        assert warns, f"two-way missing warning: {text}"


def test_locative_stehen_auf_not_flagged(nlp):
    """位置动词 + 双向介词不应因‘stehen auf Akk(喜欢)’的习语搭配而误报位置 Dat。"""
    assert _spans("Die Vase steht auf dem Tisch.", nlp) == []
    assert _spans("Das Buch liegt auf dem Tisch.", nlp) == []


def test_genitive_attribute_not_flagged(nlp):
    """属格定语 des Mannes 不应被当作 Haus 的限定词误报。"""
    assert _spans("Das ist des Mannes Haus.", nlp) == []
    assert _spans("Das ist das Haus des Mannes.", nlp) == []


def test_missing_dict_gender_skip(nlp):
    """词典缺失的新词：无权威性别时不应强行用 spaCy 猜测性别误报正确句子。"""
    # Quantencomputer 不在 core_dict，spaCy 可能误判性别/数
    assert _spans("Ich sehe den Quantencomputer.", nlp) == []
    # 零冠词新词也不应误报
    assert _spans("Ich arbeite mit Quantencomputer.", nlp) == []
    assert _spans("Quantencomputer sind teuer.", nlp) == []


def test_legal_article_case_combos_clean(nlp):
    """合法冠词/格位组合不应误报。"""
    for text in [
        "Ich sehe den Mann.",
        "Ich gebe dem Mann das Buch.",
        "Ich gebe der Frau das Buch.",
        "Das ist der Mann.",
        "Mit meinem Auto fahre ich.",
        "Für meine Familie koche ich.",
        "Ich habe einen Hund.",
        "Ich habe eine Katze.",
        "Ich habe ein Haus.",
        "Wir haben keine Zeit.",
        "Trotz des Regens gehen wir spazieren.",
        "Wegen des Wetters bleibe ich zu Hause.",
    ]:
        assert _spans(text, nlp) == [], f"legal combo FP: {text} -> {_spans(text, nlp)}"


def test_nlp_none_various_no_error():
    """nlp=None 降级：任何输入零错误。"""
    for text in ["Wasser ist wichtig.", "Ich warte auf dem Bus.", "Das ist des Mannes Haus."]:
        r = analyze_essay_text(text, None)
        assert r["error_count"] == 0
        assert r["warning_count"] == 0
        assert r["sentences"] == []


def test_contraction_prep_not_flagged(nlp):
    """缩合介词 am/im/beim 不应误报。"""
    for text in ["Am Morgen trinke ich Kaffee.", "Im Haus ist es warm.", "Beim Arzt warte ich."]:
        assert _spans(text, nlp) == []

