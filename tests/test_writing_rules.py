# -*- coding: utf-8 -*-
"""Unit tests for writing_rules.py local rule engine."""

import pytest
import spacy

from delector.services.writing import analyze_essay_text, decline_determiner


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


def test_decline_determiner_euer_and_eur():
    """euer / eur 物主代词屈折与元音省略（eure, eurem, euren, eures, eurer）。"""
    assert decline_determiner("euer", "Masc", "Sing", "Nom") == "euer"
    assert decline_determiner("euer", "Masc", "Sing", "Akk") == "euren"
    assert decline_determiner("euer", "Masc", "Sing", "Dat") == "eurem"
    assert decline_determiner("euer", "Fem", "Sing", "Nom") == "eure"
    assert decline_determiner("euer", "Fem", "Sing", "Dat") == "eurer"
    assert decline_determiner("euer", "Neut", "Sing", "Nom") == "euer"
    assert decline_determiner("euer", "Neut", "Sing", "Akk") == "euer"
    assert decline_determiner("euer", "Neut", "Sing", "Dat") == "eurem"
    assert decline_determiner("euer", "Neut", "Sing", "Gen") == "eures"
    assert decline_determiner("euer", "Masc", "Plur", "Nom") == "eure"
    assert decline_determiner("euer", "Masc", "Plur", "Dat") == "euren"

    # eur lemma
    assert decline_determiner("eur", "Fem", "Sing", "Akk") == "eure"
    assert decline_determiner("eur", "Masc", "Sing", "Dat") == "eurem"


def test_prep_entlang_positional_case(nlp):
    """entlang 介词/后置词按位置支配不同格：前置=属格 (Genitiv)，后置=宾格 (Akkusativ)。"""
    # 1. 前置正确（属格）
    assert _spans("Er geht entlang des Weges.", nlp) == []
    # 2. 前置错误（与与格混淆）
    spans_pre_err = _spans("Er geht entlang dem Weg.", nlp)
    assert any(s["error_type"] == "kasus" and "des" in s["corrected_form"] for s in spans_pre_err)

    # 3. 后置正确（宾格）
    assert _spans("Er geht den Weg entlang.", nlp) == []
    # 4. 后置错误（与格 dem Weg entlang 报错应为 den Weg）
    spans_post_err = _spans("Er geht dem Weg entlang.", nlp)
    assert any("den" in s["corrected_form"] for s in spans_post_err)


def test_analyze_a1_email_capitalized_noun_exemption_and_expanded_valedictions():
    """A1 邮件诊断：正文首词大写名词/专有名词免检，并扩充常用结语表。"""
    from delector.services.writing import analyze_a1_email

    # 1. 专有名词/名词（Montag, Berlin）在称呼语逗号后允许大写
    text1 = "Liebe Maria,\nMontag habe ich Zeit für Deutschkurs.\nViele Grüße\nHans"
    diag1 = analyze_a1_email(text1)
    rule_names1 = [s["rule"] for s in diag1["suggestions"]]
    assert "a1_greeting_body_lowercase" not in rule_names1

    text2 = "Lieber Tom,\nBerlin ist eine wunderbare Stadt.\nBis bald\nAnna"
    diag2 = analyze_a1_email(text2)
    rule_names2 = [s["rule"] for s in diag2["suggestions"]]
    assert "a1_greeting_body_lowercase" not in rule_names2
    assert "a1_valediction_missing" not in rule_names2

    # 2. 普通动词/代词大写依然报错
    text3 = "Liebe Maria,\nIch komme morgen.\nAlles Gute\nHans"
    diag3 = analyze_a1_email(text3)
    rule_names3 = [s["rule"] for s in diag3["suggestions"]]
    assert "a1_greeting_body_lowercase" in rule_names3

    # 3. 扩充的结语都能被识别（auf wiedersehen, schöne grüße, alles gute, alles liebe, herzlichen dank）
    for v in ["Auf Wiedersehen", "Schöne Grüße", "Alles Gute", "Alles Liebe", "Herzlichen Dank"]:
        email = f"Hallo Peter,\nich lade dich ein.\n{v}\nMax"
        diag = analyze_a1_email(email)
        rules = [s["rule"] for s in diag["suggestions"]]
        assert "a1_valediction_missing" not in rules, f"{v} 应被识别为有效结语"


# ── Task 1/2：统一违规形状 + 引擎降级标记 + 接线既有语法算力 ──────────────────
# 统一违规形状：{"rule": str, "level": "error"|"warning", "message": str, "span": tuple|None}


def test_collect_violations_unified_shape_and_error_only():
    """`collect_violations` 只保留 `level=="error"` 并给出统一形状（warning 不阻止收敛）。"""
    from delector.services.writing import collect_violations

    analysis = {
        "violations": [
            {"rule": "a1_greeting_missing", "level": "error", "message": "缺称呼语", "span": None},
            {"rule": "a1_word_count", "level": "warning", "message": "字数偏短", "span": None},
            {"rule": "artikel", "level": "error", "message": "应为 einen", "span": (4, 13)},
        ]
    }
    out = collect_violations(analysis)
    assert [v["rule"] for v in out] == ["a1_greeting_missing", "artikel"], "warning 不得入违规"
    assert set(out[0].keys()) == {"rule", "level", "message", "span"}
    assert out[1]["span"] == (4, 13)


def test_collect_violations_legacy_suggestions_fallback_error_only():
    """无新键 `violations` ⇒ 回退 legacy `suggestions`，且同样只取 `level=="error"`。"""

    from delector.services.writing import collect_violations

    analysis = {
        "suggestions": [
            {"rule": "a1_greeting_missing", "level": "error", "message": "缺称呼语"},
            {"rule": "a1_word_count", "level": "warning", "message": "字数偏短"},
        ]
    }
    out = collect_violations(analysis)
    assert [v["rule"] for v in out] == ["a1_greeting_missing"]
    assert out[0]["span"] is None


def test_collect_violations_prefers_new_key_over_legacy():
    """新键 `violations` 存在时**优先**新键（legacy 不再被读）。"""
    from delector.services.writing import collect_violations

    analysis = {
        "violations": [{"rule": "kasus", "level": "error", "message": "m", "span": (0, 3)}],
        "suggestions": [{"rule": "a1_greeting_missing", "level": "error", "message": "legacy"}],
    }
    assert [v["rule"] for v in collect_violations(analysis)] == ["kasus"]


def test_collect_violations_empty_analysis():
    from delector.services.writing import collect_violations

    assert collect_violations({}) == []
    assert collect_violations({"violations": []}) == []


def test_analyze_a1_email_judge_engine_rules_only_without_nlp():
    """无 nlp ⇒ 只跑格式族，`judge_engine="rules_only"`（语法族不产违规）。"""
    from delector.services.writing import analyze_a1_email

    diag = analyze_a1_email("Liebe Maria,\nich lade dich ein.\nViele Grüße,\nAnna")
    assert diag["judge_engine"] == "rules_only"
    assert all(v["rule"].startswith("a1_") for v in diag["violations"]), "无 nlp 时不应产语法违规"


def test_analyze_a1_email_judge_engine_rules_plus_spacy(nlp):
    """nlp 可用且语法族跑过检测器 ⇒ `judge_engine="rules+spacy"`，语法违规并入 `violations`。"""
    from delector.services.writing import analyze_a1_email

    diag = analyze_a1_email("Ich habe ein Hund.", nlp=nlp)
    assert diag["judge_engine"] == "rules+spacy"
    gram = [v for v in diag["violations"] if v["rule"] == "artikel"]
    assert len(gram) == 1
    assert gram[0]["level"] == "error"
    assert gram[0]["span"] == (9, 17)
    assert "einen" in gram[0]["message"]


def test_analyze_a1_email_existing_keys_unchanged(nlp):
    """只增不改：既有的 `suggestions` / `greeting` / `valediction` 等内容逐字不动。"""
    from delector.services.writing import analyze_a1_email

    text = "Liebe Maria,\nich lade dich ein.\nViele Grüße,\nAnna"
    diag = analyze_a1_email(text)
    assert [(s["rule"], s["level"]) for s in diag["suggestions"]] == [
        ("a1_word_count", "warning"),
        ("a1_valediction_comma", "error"),
    ]
    assert set(diag["suggestions"][0].keys()) == {"rule", "level", "message"}
    assert diag["greeting"]["valid"] is True and diag["greeting"]["has_comma"] is True
    assert diag["valediction"]["valid"] is True
    assert diag["word_count"] == 9 and diag["word_count_status"] == "too_short"
    # 并列新键：格式族进入统一形状（无 nlp ⇒ 只格式族；键集与建议一致地多一个 span）
    assert [v["rule"] for v in diag["violations"]] == ["a1_word_count", "a1_valediction_comma"]
    assert all(set(v.keys()) == {"rule", "level", "message", "span"} for v in diag["violations"])


def test_analyze_a1_email_wires_grammar_and_preposition(nlp):
    """负样本接线：冠词-名词一致 / 介词支配格 各报 1 条（经统一抽取器可见）。"""
    from delector.services.writing import analyze_a1_email, collect_violations

    letter_bad_artikel = "Liebe Maria,\nich habe ein Hund.\nViele Grüße\nAnna"
    v1 = collect_violations(analyze_a1_email(letter_bad_artikel, nlp=nlp))
    assert [v["rule"] for v in v1] == ["artikel"] and v1[0]["level"] == "error"

    letter_bad_kasus = "Liebe Maria,\nich fahre mit den Bus.\nViele Grüße\nAnna"
    v2 = collect_violations(analyze_a1_email(letter_bad_kasus, nlp=nlp))
    assert [v["rule"] for v in v2] == ["kasus"] and v2[0]["level"] == "error"


def test_official_a1_samples_have_no_errors_under_wired_judge(nlp):
    """硬门（D3）：官方 10 篇范文在接线后的裁判下 MUST 零**error** 级违规。

    连官方范文都报错 ⇒ 规则过严 ⇒ `v` 恒 > 0 ⇒ 循环永不收敛。故这是每加一条规则都要过的门。
    """
    from delector.data import a1_writing_dict
    from delector.services.writing import analyze_a1_email, collect_violations

    samples = a1_writing_dict.A1_SCHREIBEN_TEIL2
    assert len(samples) >= 10
    for ex in samples:
        diag = analyze_a1_email(ex["sample_email"], nlp=nlp)
        got = collect_violations(diag)
        assert got == [], f"官方范文被报违规（规则过严）: {ex['id']} -> {got}"
        assert diag["judge_engine"] == "rules+spacy"
