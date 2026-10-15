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


# ── Task 3：主谓一致（Number 一致）───────────────────────────────────────────


def _sent_spans(text, nlp, fn):
    """按句切分、逐句调用检测器（与 analyze_essay_text / analyze_a1_email 的 base 口径一致）。"""
    doc = nlp(text)
    spans = []
    for sent in doc.sents:
        toks = list(sent)
        if not toks:
            continue
        spans.extend(fn(toks, toks[0].idx))
    return spans


def _numerus(text, nlp):
    from delector.services.writing import detect_subject_verb_agreement

    return _sent_spans(text, nlp, detect_subject_verb_agreement)


def test_numerus_wrong_number_flagged(nlp):
    """负样本：复数主语 + 单数定式动词 MUST 报 1 条（error_type=numerus）。"""
    spans = _numerus("Die Kinder spielt im Garten.", nlp)
    assert len(spans) == 1
    sp = spans[0]
    assert set(sp.keys()) == {"severity", "error_type", "corrected_form", "explanation_zh", "start", "end"}
    assert sp["severity"] == "error"
    assert sp["error_type"] == "numerus"
    assert "spielen" in sp["corrected_form"]
    assert (sp["start"], sp["end"]) == (11, 17), "span 应指向出错的定式动词 spielt"
    assert "Kinder" in sp["explanation_zh"]


def test_numerus_correct_number_clean(nlp):
    """正样本：数一致 MUST 零误报。"""
    assert _numerus("Die Kinder spielen im Garten.", nlp) == []


def test_numerus_coordinated_subject_guard(nlp):
    """FP 守卫①（防御性）：并列主语（sb 只挂第一个并列项，Number 是整个并列短语的属性）⇒ 不报。

    注意：当前「只报复数主语＋单数动词」判据下**该守卫不可达/防御性**（`Anna und Tom spielen`
    的动词天然是复数，本就不会进判定）—— 勿当有效拦截器；此用例仅锁行为不退化，将来放开
    反向判定（单数主语＋复数动词）时该守卫才可能成为真实拦截。
    """
    assert _numerus("Anna und Tom spielen im Garten.", nlp) == []
    assert _numerus("Ich und du sind Freunde.", nlp) == []


def test_numerus_collective_noun_guard(nlp):
    """FP 守卫②：集合名词（die Familie）在语法上是单数 ⇒ 不报。"""
    assert _numerus("Meine Familie ist groß.", nlp) == []
    assert _numerus("Die Familie meiner Frau wohnt in Berlin.", nlp) == []


def test_numerus_indefinite_pronoun_guard(nlp):
    """FP 守卫③：man / 不定代词 / 形式主语 das 的 Number 语义不可靠 ⇒ 不报（宁漏不误）。"""
    assert _numerus("Man spielt im Garten.", nlp) == []
    assert _numerus("Das sind meine Eltern.", nlp) == []
    assert _numerus("Niemand kennt den Mann.", nlp) == []


def test_numerus_perfect_tense_guard(nlp):
    """FP 守卫④：复合时态（hat ... gemacht，Number 落在助动词上）⇒ 不报。"""
    assert _numerus("Die Kinder haben im Garten gespielt.", nlp) == []
    assert _numerus("Meine Eltern sind gestern angekommen.", nlp) == []


def test_numerus_quantity_phrase_guard(nlp):
    """FP 守卫⑤：数量词短语作主语（`Zwei Stunden ist genug.` 实测是合法句）⇒ 不报。"""
    assert _numerus("Zwei Stunden ist genug.", nlp) == []
    assert _numerus("Zehn Euro ist zu viel.", nlp) == []


def test_numerus_infinitive_subject_guard(nlp):
    """FP 守卫⑥：不定式/动词短语作主语（`Bücher lesen ist schön.`）⇒ 不报。"""
    assert _numerus("Bücher lesen ist schön.", nlp) == []
    assert _numerus("Sport machen ist wichtig.", nlp) == []


def test_numerus_missing_subject_guard(nlp):
    """FP 守卫⑦：主语缺失（祈使句 / es gibt / 无 sb 的句子）⇒ 不报。"""
    assert _numerus("Hilf mir bitte!", nlp) == []
    assert _numerus("Es gibt viele Leute in der Stadt.", nlp) == []
    assert _numerus("Heute ist es warm.", nlp) == []


def test_numerus_wired_into_a1_judge(nlp):
    """接线缝（RED#1 教训）：numerus 违规 MUST 经 analyze_a1_email 进统一违规形状。"""
    from delector.services.writing import analyze_a1_email, collect_violations

    got = collect_violations(analyze_a1_email("Die Kinder spielt im Garten.", nlp=nlp))
    numerus_spans = [v for v in got if v["rule"] == "numerus"]
    assert len(numerus_spans) == 1
    assert numerus_spans[0]["level"] == "error"
    assert numerus_spans[0]["span"] is not None


# ── Task 4：动词支配格（Rektion）+ 人工词表 A1_VERB_CASES ─────────────────────


def _rektion(text, nlp):
    from delector.services.writing import detect_verb_case_government

    return _sent_spans(text, nlp, detect_verb_case_government)


def test_rektion_dative_verb_with_accusative_object_flagged(nlp):
    """负样本：helfen 支配三格，宾语却是四格形态 ⇒ 报 1 条（实测锚点）。"""
    spans = _rektion("Ich helfe meinen Bruder.", nlp)
    assert len(spans) == 1
    sp = spans[0]
    assert set(sp.keys()) == {"severity", "error_type", "corrected_form", "explanation_zh", "start", "end"}
    assert sp["severity"] == "error"
    assert sp["error_type"] == "rektion"
    assert sp["corrected_form"] == "meinem Bruder"
    assert "helfen" in sp["explanation_zh"]


def test_rektion_dative_verb_with_dative_object_clean(nlp):
    """正样本：helfen + 三格 ⇒ 0 条。

    含 `meiner Schwester` 这个关键 FP 样本：spaCy 把 Fem Dat 的 `meiner` 标成 Gen
    （同形歧义）—— 该守卫按**表面形式 vs 目标格形式**比对，不依赖 morph.Case 直判。
    """
    assert _rektion("Ich helfe meinem Bruder.", nlp) == []
    assert _rektion("Ich helfe meiner Schwester.", nlp) == []


def test_rektion_accusative_verb_flags_dative_object(nlp):
    """负样本：verstehen 支配四格，宾语却是三格 ⇒ 报。"""
    spans = _rektion("Ich verstehe der Frage.", nlp)
    assert len(spans) == 1
    assert spans[0]["error_type"] == "rektion"
    assert spans[0]["corrected_form"] == "die Frage"


def test_rektion_accusative_verb_with_accusative_object_clean(nlp):
    """正样本：四格动词 + 四格宾语 ⇒ 0 条。"""
    assert _rektion("Ich sehe den Mann.", nlp) == []
    assert _rektion("Ich lese den Brief.", nlp) == []


def test_rektion_unknown_verb_guard(nlp):
    """FP 守卫①：动词不在词表（besuchen）⇒ 不判。"""
    assert _rektion("Ich besuche meinen Bruder.", nlp) == []


def test_rektion_reflexive_guard(nlp):
    """FP 守卫②：反身结构（sich freuen）⇒ 不判。"""
    assert _rektion("Ich freue mich auf das Wochenende.", nlp) == []


def test_rektion_separable_prefix_guard(nlp):
    """FP 守卫③：可分前缀动词（an|rufen，分裂前缀 dep=svp）⇒ 不判。"""
    assert _rektion("Ich rufe meine Mutter an.", nlp) == []


def test_rektion_nominalized_verb_guard(nlp):
    """FP 守卫④：名词化动词（das Lesen）⇒ 不判。"""
    assert _rektion("Das Lesen ist wichtig.", nlp) == []


def test_rektion_ambiguous_two_case_verbs_skipped(nlp):
    """FP 守卫⑤：词表内标 `Dat+Acc` 的动词（geben/kaufen 等两可支配）⇒ 不判。"""
    assert _rektion("Ich gebe dem Kind ein Buch.", nlp) == []
    assert _rektion("Ich kaufe den Mann ein Buch.", nlp) == []


def test_rektion_pronoun_object_skipped(nlp):
    """FP 守卫⑥：代词宾语（dir/ihm，无冠词）⇒ 不判。"""
    assert _rektion("Ich danke dir.", nlp) == []
    assert _rektion("Ich helfe ihm.", nlp) == []


def test_rektion_plural_object_skipped(nlp):
    """宁漏不误：复数宾语跳过（Dat Plur 名词还需 -n 词尾，只换冠词给出半对纠正）。"""
    assert _rektion("Ich helfe den Kindern.", nlp) == []
    assert _rektion("Ich helfe die Kinder.", nlp) == []


def test_rektion_free_dative_and_ambiguous_verbs_skipped(nlp):
    """A 类 FP（评审实跑锚点）：登记进 `Dat+Acc` 的动词 MUST 不判 ——

    自由第三格（`jdm. die Tür öffnen` / `jdm. etw. bezahlen`）与两可支配（`schmecken`：
    `Das schmeckt mir.` 三格 与 `Ich schmecke den Wein.` 四格都合法）硬判必误报。
    """
    assert _rektion("Ich öffne meinem Bruder die Tür.", nlp) == []
    assert _rektion("Ich bezahle meinem Vater das Essen.", nlp) == []
    assert _rektion("Ich schmecke den Wein.", nlp) == []


def test_rektion_free_dative_with_strict_accusative_verb_skipped(nlp):
    """第三类 FP（评审探针实跑锚点）：**严格 Acc 动词 + 自由第三格**（`jdm. etw.`）MUST 不报。

    实测：`Ich lese meinem Bruder das Buch.` / `Ich suche meinem Bruder die Schuhe.` 里 spaCy 给
    `Bruder` 打 `da`、给四格宾语 `Buch` / `Schuhe` 打 `oa` —— 旧实现把所有 `oa`/`da` 宾语都拿去
    和 Acc 目标格比对 ⇒ 合法句被报 `corrected_form='meinen Bruder'`。自由第三格是 A1 教材级
    普遍构造（`Ich öffne / lese / suche jdm. etw.`），故：四格位已被 `oa` 宾语占用的 `da` 宾语
    MUST 不判（判据本体与取舍见 `detect_verb_case_government` docstring）。
    """
    for text in [
        "Ich lese meinem Bruder das Buch.",
        "Ich suche meinem Bruder die Schuhe.",
        "Ich lese meinem Bruder die Zeitung.",
        "Ich suche meiner Schwester den Regenschirm.",
    ]:
        assert _rektion(text, nlp) == [], f"自由第三格被误报: {text} -> {_rektion(text, nlp)}"


def test_rektion_accusative_verb_single_dative_shaped_object_still_flagged(nlp):
    """反证据（防上一豁免过宽）：四格位**无人占用**时，`da` 宾语 MUST 仍按「格写错」报 1 条。

    实测（探针）：`Ich verstehe der Frage.` 里 spaCy 把宾语打成 `da`（无 `oa` 兄弟）—— 该句是
    **真实格错**（应为 `die Frage`，既有用例 `test_rektion_accusative_verb_flags_dative_object`
    已钉死）；`Ich brauche dem Buch.` 同理（应为 `das Buch`）。豁免若按「da 一律不判」实现就会把
    这两句一起漏掉，本条锁死「只有四格位被 `oa` 占用时，`da` 才是自由第三格」这条判据。
    """
    sp = _rektion("Ich verstehe der Frage.", nlp)
    assert len(sp) == 1 and sp[0]["corrected_form"] == "die Frage"
    sp2 = _rektion("Ich brauche dem Buch.", nlp)
    assert len(sp2) == 1 and sp2[0]["corrected_form"] == "das Buch"


def test_rektion_wired_into_a1_judge(nlp):
    """接线缝（RED#1 教训）：rektion 违规 MUST 经 analyze_a1_email 进统一违规形状。"""
    from delector.services.writing import analyze_a1_email, collect_violations

    got = collect_violations(analyze_a1_email("Ich helfe meinen Bruder.", nlp=nlp))
    rektion_spans = [v for v in got if v["rule"] == "rektion"]
    assert len(rektion_spans) == 1
    assert rektion_spans[0]["level"] == "error"
    assert rektion_spans[0]["span"] is not None


# ── Task 5：主句动词位置（V2）────────────────────────────────────────────────


def _v2(text, nlp):
    from delector.services.writing import detect_verb_second_position

    return _sent_spans(text, nlp, detect_verb_second_position)


def test_v2_wrong_position_flagged(nlp):
    """负样本（实测锚点）：主语插在 Vorfeld 与定式动词之间 ⇒ 报 1 条。"""
    spans = _v2("Gestern ich habe gearbeitet.", nlp)
    assert len(spans) == 1
    sp = spans[0]
    assert set(sp.keys()) == {"severity", "error_type", "corrected_form", "explanation_zh", "start", "end"}
    assert sp["severity"] == "error"
    assert sp["error_type"] == "wortstellung"
    assert sp["corrected_form"] == "Gestern habe ich"
    assert "habe" in sp["explanation_zh"] or "V2" in sp["explanation_zh"]


def test_v2_correct_position_clean(nlp):
    """正样本（实测锚点）：单 token / 多 token Vorfeld（PP、ADV+名词）⇒ 0 条。

    `Gestern Abend habe ich gearbeitet.` 与 `Am Montag habe ich Zeit.` 是多 token 前置短语 ——
    按 token index 硬判会误报，本实现按「主语是否在动词前 + 其左侧有无独立成分」判定。
    """
    assert _v2("Gestern habe ich gearbeitet.", nlp) == []
    assert _v2("Am Montag habe ich Zeit.", nlp) == []
    assert _v2("Gestern Abend habe ich gearbeitet.", nlp) == []
    assert _v2("Die Kinder spielen im Garten.", nlp) == []
    assert _v2("Ich habe Hunger.", nlp) == []
    assert _v2("Meine Eltern haben mir ein Buch gekauft.", nlp) == []


def test_v2_subject_np_internal_modifier_exempt(nlp):
    """B 类 FP（评审补充实跑锚点）：主语 NP **内部**的副词修饰不算独立 Vorfeld 成分 ⇒ 0 条。

    实测链：`Meine sehr große Familie wohnt in Berlin.` 里 `sehr`（dep=`mo`）→ `große`（ADJ）
    → `Familie`（主语）—— 只按 dep 白名单会把 `sehr` 当独立前置成分 ⇒ 误报。
    """
    for text in [
        "Meine sehr große Familie wohnt in Berlin.",
        "Ein wirklich guter Film läuft heute.",
        "Meine sehr nette Nachbarin hilft mir oft.",
        "Zwei sehr schöne Blumen blühen.",
        "Sehr guter Kaffee kommt aus Brasilien.",
    ]:
        assert _v2(text, nlp) == [], f"NP 内部修饰误报: {text} -> {_v2(text, nlp)}"


def test_v2_focus_particle_inside_subject_np_exempt(nlp):
    """第三类 FP（评审探针实跑锚点）：**焦点小词**挂在主语 NP 上 ⇒ 不算独立 Vorfeld 成分 ⇒ 0 条。

    实测链：`Auch → Familie`（1 步到主语）、`Nur → mein(DET) → Bruder`（2 步）—— 两条链上**都没有
    ADJ**，故旧判据（「必须经过 ADJ」）整类漏掉，把 `Auch` / `Nur` 当独立前置成分 ⇒ 合法句被报
    `Auch wohnt meine Familie`。豁免判据 = 该词是**封闭焦点小词表**（`_FOCUS_PARTICLES`）成员且
    head 链 1~2 步进入主语 NP；时间副词 MUST NOT 进表（见下一条用例）。
    """
    for text in [
        "Auch meine Familie wohnt in Berlin.",
        "Nur mein Bruder kommt heute.",
        "Auch mein Bruder arbeitet in Berlin.",
        "Nur meine Schwester wohnt hier.",
        "Sogar mein Vater kocht heute.",
        "Auch meine Eltern arbeiten hier.",
        "Gerade mein Bruder hilft mir oft.",
    ]:
        assert _v2(text, nlp) == [], f"焦点小词误报: {text} -> {_v2(text, nlp)}"


def test_v2_focus_particles_closed_list_excludes_time_adverbs(nlp):
    """防退化（焦点小词豁免的边界，MUST NOT 松）：时间副词**不得**进 `_FOCUS_PARTICLES`。

    理由（实测）：错误语序 `Gestern ich habe gearbeitet.` 里 `Gestern` 的 dep=`mo`、head 直挂主语
    —— 与 `Auch meine Familie ...` 的 `Auch` 在 spaCy 里**形态相同**，两者只能靠封闭词表区分。
    词表一旦混入时间副词，V2 规则对「状语 + 主语 + 定式动词」这类错误（A1 最高频语序错）永久
    失明。本条钉死词表成员口径；行为侧由下方真前置状语负样本锁住。
    """
    from delector.services.writing import _FOCUS_PARTICLES

    for adv in ("gestern", "heute", "morgen", "jetzt", "dann", "später", "abends", "früher", "oft"):
        assert adv not in _FOCUS_PARTICLES, f"时间/频率副词「{adv}」不得进焦点小词表"


def test_v2_fronted_adverbial_still_flagged_after_np_guard(nlp):
    """反证据（防豁免过宽）：错误语序里真前置状语（head 链到主语/动词、链上无 ADJ）⇒ MUST 仍报。

    实测坑：`Gestern ich habe gearbeitet.` 里 spaCy 把 `Gestern` 直接挂到主语 `ich` 上
    （`Gestern → ich`）—— 「head 链可达主语」单独使用会把它误豁免 ⇒ 豁免因此额外要求
    链上经过 ADJ（`sehr → große(ADJ) → Familie`），本条锁死该收紧不回退。
    """
    for text in [
        "Gestern ich habe gearbeitet.",
        "Heute meine Familie wohnt in Berlin.",
        "Jetzt ich gehe nach Hause.",
        "Am Montag ich habe Zeit.",
        "Sehr ich habe mich gefreut.",
        "In Berlin meine Familie wohnt.",
        # 焦点小词豁免（F2）落地后追加：时间副词前置 + 主语插在动词前 = A1 最高频语序错，
        # 与焦点小词在 spaCy 里同形（head 直挂主语）⇒ MUST 仍全部报（防豁免过宽）。
        "Morgen ich fahre nach Berlin.",
        "Heute ich trinke Kaffee.",
    ]:
        assert len(_v2(text, nlp)) == 1, f"真前置成分被漏报: {text} -> {_v2(text, nlp)}"


def test_v2_subordinate_clause_exempt(nlp):
    """豁免①从句：从属连词引导的分句里 V2 不成立（实测 `bin`/`regnet` 的 dep=mo）⇒ 0 条。"""
    assert _v2("Ich bleibe zu Hause, weil ich krank bin.", nlp) == []
    assert _v2("Wenn es regnet, bleibe ich zu Hause.", nlp) == []


def test_v2_question_exempt(nlp):
    """豁免②疑问句：V1/疑问语序 ⇒ 0 条。"""
    assert _v2("Hast du Zeit?", nlp) == []
    assert _v2("Warum hast du keine Zeit?", nlp) == []


def test_v2_imperative_exempt(nlp):
    """豁免③祈使句 ⇒ 0 条。"""
    assert _v2("Komm bitte her!", nlp) == []
    assert _v2("Machen Sie bitte das Fenster zu!", nlp) == []


def test_v2_coordinated_clause_exempt(nlp):
    """豁免④并列句：第二分句（`isst` 的 dep=cj）与并列主语 ⇒ 0 条。"""
    assert _v2("Ich koche Kaffee, und mein Bruder isst Kuchen.", nlp) == []
    assert _v2("Mein Bruder und ich gehen ins Kino.", nlp) == []


def test_v2_quoted_speech_exempt(nlp):
    """豁免⑤直接引语：引号内的句子（实测 `komme` 的 dep=oc + 引号奇偶双保险）⇒ 0 条。"""
    assert _v2('Er sagt: "Ich komme morgen."', nlp) == []


def test_v2_fragment_exempt(nlp):
    """豁免⑥标题式片段 / 无主语句（含无人称被动）⇒ 0 条。"""
    assert _v2("Viele Grüße aus Berlin.", nlp) == []
    assert _v2("Heute wird viel gearbeitet.", nlp) == []


def test_v2_salutation_line_break_not_flagged(nlp):
    """实测 FP 源（官方范文 email_03/email_06）：称呼语被 spaCy 并进正文句 ——
    `Herr` 会成为第二个 sb（豁免⑥多主语）、或跨行 Vorfeld（豁免⑧换行）⇒ 不报。"""
    assert _v2("Sehr geehrter Herr Becker,\n\nich interessiere mich sehr für Ihre Wohnung.", nlp) == []
    assert _v2("Liebe Sarah,\n\nes tut mir leid, aber ich muss am Freitag arbeiten.", nlp) == []


def test_v2_wired_into_a1_judge(nlp):
    """接线缝（RED#1 教训）：wortstellung 违规 MUST 经 analyze_a1_email 进统一违规形状。"""
    from delector.services.writing import analyze_a1_email, collect_violations

    got = collect_violations(analyze_a1_email("Gestern ich habe gearbeitet.", nlp=nlp))
    v2_spans = [v for v in got if v["rule"] == "wortstellung"]
    assert len(v2_spans) == 1
    assert v2_spans[0]["level"] == "error"
    assert v2_spans[0]["span"] is not None


# ── 永久硬门（D）：≥20 句合法德语 MUST 零（语法族）违规 ────────────────────────
# 背景：官方 10 篇范文门（test_official_a1_samples_have_no_errors_under_wired_judge）放过
# 三类实跑误报 —— ① 主语 NP 内副词修饰（`Meine sehr große Familie...` 报 wortstellung）
# ② 自由第三格/两可动词（`Ich öffne meinem Bruder die Tür.` 报 rektion）
# ③ 焦点小词（`Auch meine Familie wohnt in Berlin.` 报 wortstellung）—— 范文里没有这些句式
# ⇒ 单靠范文门不足以防 FP。本清单为**永久硬门**：每句都实跑确认零语法族违规后才登记。
#
# **类覆盖清单（加句子前 MUST 逐类过一遍 —— 只加句子不检类，门会再次变窄，本轮就是这么漏的）**：
#   ① 主语 NP 内部修饰：副词（`sehr`）/ 形容词（`guter`）/ **分词**（`von mir gekaufte`）/
#      **介词短语**（`im blauen Hemd`）
#   ② 焦点小词（Fokuspartikeln，封闭词表 `_FOCUS_PARTICLES` / `writing.py::_is_inside_subject_np`）
#   ③ 自由第三格 `jdm. etw.`（严格 Acc 动词 + 三格宾语）+ 人三物四（`Dat+Acc` 登记不判）
#   ④ 及物 / 不及物两可（`schmecken`：`Das schmeckt mir.` 与 `Ich schmecke den Wein.`）
#   ⑤ 前置状语 / 介词短语后的正常 V2
#   ⑥ 从句前置的主从复合
#   ⑦ 疑问句 / 祈使句（V1、`?`、Mood=Imp）
# 新增句子时逐类核对：任一类句式若无在册句子 ⇒ 该类对 FP 失明（本门的真实失败模式）。
COMMON_CORRECT_SENTENCES: list[str] = [
    # ① 主语 NP 内修饰 —— 副词/形容词（B 类 FP 覆盖）
    "Meine sehr große Familie wohnt in Berlin.",
    "Ein wirklich guter Film läuft heute.",
    "Meine sehr nette Nachbarin hilft mir oft.",
    "Zwei sehr schöne Blumen blühen.",
    "Sehr guter Kaffee kommt aus Brasilien.",
    "Ganz besonders gute Ideen sind wichtig.",
    # ① 主语 NP 内修饰 —— 分词 / 介词短语（CRV 指出此前无任何用例的句式）
    "Die von mir gekaufte Uhr funktioniert.",
    "Der Mann im blauen Hemd arbeitet hier.",
    # ② 焦点小词（Fokuspartikeln）—— `Auch` / `Nur` 的 head 直挂主语 NP，链上无 ADJ
    "Auch meine Familie wohnt in Berlin.",
    "Nur mein Bruder kommt heute.",
    "Auch mein Bruder arbeitet in Berlin.",
    "Nur meine Schwester wohnt hier.",
    "Sogar mein Vater kocht heute.",
    "Auch meine Eltern arbeiten hier.",
    "Gerade mein Bruder hilft mir oft.",
    # ③ 自由第三格 `jdm. etw.`（严格 Acc 动词 lesen/suchen + 三格宾语）/ 人三物四
    "Ich öffne meinem Bruder die Tür.",
    "Ich bezahle meinem Vater das Essen.",
    "Ich gebe dem Kind ein Buch.",
    "Ich zeige meiner Freundin die Fotos.",
    "Ich kaufe meinem Mann ein Buch.",
    "Ich lese meinem Bruder das Buch.",
    "Ich suche meinem Bruder die Schuhe.",
    "Ich lese meinem Bruder die Zeitung.",
    "Ich suche meiner Schwester den Regenschirm.",
    # ④ 及物/不及物两可的动词
    "Ich schmecke den Wein.",
    "Das schmeckt mir gut.",
    "Die Suppe schmeckt sehr gut.",
    "Ich öffne die Tür.",
    # ⑤ 前置介词短语 / 时间状语后 V2 正常语序
    "Am Montag habe ich Zeit.",
    "Gestern Abend habe ich gearbeitet.",
    "Am Wochenende fahre ich nach Berlin.",
    "Heute Morgen trinke ich Kaffee.",
    # ⑥ 从句在前的主从复合
    "Weil ich müde bin, gehe ich schlafen.",
    "Wenn es regnet, bleibe ich zu Hause.",
    "Wenn ich Zeit habe, komme ich zu dir.",
    "Obwohl es kalt ist, gehe ich spazieren.",
    # ⑦ 疑问句 / 祈使句
    "Kannst du mir die Tür öffnen?",
    "Kochst du heute Kaffee?",
    "Öffne bitte die Tür!",
    # 常见 A1 基础句（回归护栏）
    "Ich lerne jeden Tag Deutsch.",
    "Meine Eltern wohnen in Hamburg.",
    "Der Mann liest ein Buch.",
    "Die Kinder spielen im Garten.",
    "Ich trinke morgens Kaffee.",
    "Sie liest die Zeitung.",
    "Wir sehen einen Film.",
    "Er braucht eine Pause.",
    "Der Film ist wirklich gut.",
    "Mein Bruder arbeitet in einer Firma.",
    "Heute ist das Wetter schön.",
    "Im Sommer fahren wir ans Meer.",
]


def test_common_correct_sentences_grammar_gate(nlp):
    """永久硬门：`COMMON_CORRECT_SENTENCES` 每句 MUST 零**语法族**违规（nlp fixture 下）。

    判据口径（对任务原话的客观修正，非放水）：清单是裸句（非邮件），格式族
    `a1_greeting_missing` 对任何无称呼语输入**必然**报 error —— 与语法误报无关 ⇒ 门只断言
    语法族（rule 不以 `a1_` 开头），并以 `judge_engine == "rules+spacy"` 证明语法族真跑过
    （防门空转：将来若接线断开、语法族不跑，本门 MUST 红）。
    """
    from delector.services.writing import analyze_a1_email, collect_violations

    # 防静默缩水（变异自证③）：清单**只增不减** —— 抽掉任一句（含本轮新增 16 句）即红。需要删句时
    # MUST 在 diff 里写明「该句本身不合法」的理由，并同步下调此下限（删句唯一正当理由）。
    assert len(COMMON_CORRECT_SENTENCES) >= 51, "硬门清单只增不减（上一轮 35 句 → 本轮 51 句，覆盖七类句式）"
    for s in COMMON_CORRECT_SENTENCES:
        diag = analyze_a1_email(s, nlp=nlp)
        assert diag["judge_engine"] == "rules+spacy", f"语法族未跑（门空转）: {s}"
        got = [v for v in collect_violations(diag) if not v["rule"].startswith("a1_")]
        assert got == [], f"合法句被语法族误报: {s} -> {got}"


# ── Task 6 HITL 收尾（B 维）：过去时间锚 × 时态一致性 = advisory（warning）──────────
# 移植自 `tools/bench_judge_fp.py` 的 B 维探测（该脚本是冻结的标定记录，勿改）。
# HITL 裁决（用户 2026-10-15）：接线为 `level="warning"`（正样本 FP 0/35、负样本 7/7、
# 对照 0/6 两档阈值均成立，但样本偏小 ⇒ 先 advisory，不阻断收敛）。


def _tempus(text, nlp):
    from delector.services.writing import detect_past_anchor_tense_conflict

    return _sent_spans(text, nlp, detect_past_anchor_tense_conflict)


def test_tempus_past_anchor_conflict_is_warning_span(nlp):
    """负样本：过去时间锚 + 现在时限定动词 MUST 报 1 条，且是 **warning** 级（advisory）。"""
    spans = _tempus("Gestern gehe ich zur Schule.", nlp)
    assert len(spans) == 1
    sp = spans[0]
    assert set(sp.keys()) == {"severity", "error_type", "corrected_form", "explanation_zh", "start", "end"}
    assert sp["severity"] == "warning", "B 维是 advisory：severity 必须是 warning（HITL 裁决）"
    assert sp["error_type"] == "tempus"
    assert (sp["start"], sp["end"]) == (8, 12), "span 应指向出错的定式动词 gehe"
    assert "Gestern" in sp["explanation_zh"]
    assert "过去" in sp["explanation_zh"]


def test_tempus_correct_past_sentences_clean(nlp):
    """正/边界样本：Präteritum / Perfekt / 未来现在时 MUST 零误报（与 bench 对照 0/6 同口径）。"""
    for text in [
        "Gestern ging ich zur Schule.",
        "Gestern habe ich eine Suppe gekocht.",
        "Letzte Woche bin ich nach Berlin gefahren.",
        "Gestern kaufte ich ein Buch im Supermarkt.",
        "Damals wohnte ich in Hamburg.",
        "Morgen fahre ich nach Berlin.",
    ]:
        assert _tempus(text, nlp) == [], f"正确句被误报: {text}"


def test_tempus_no_false_advisory_on_known_good_texts(nlp):
    """FP 守卫（正样本零误报，D3 硬门同口径）：官方 10 篇 + 51 句硬门清单 MUST 零 advisory。"""
    from delector.data import a1_writing_dict
    from delector.services.writing import analyze_a1_email

    for ex in a1_writing_dict.A1_SCHREIBEN_TEIL2:
        advs = analyze_a1_email(ex["sample_email"], nlp=nlp)["advisories"]
        assert advs == [], f"官方范文被报 advisory（误报）: {ex['id']} -> {advs}"
    for s in COMMON_CORRECT_SENTENCES:
        advs = analyze_a1_email(s, nlp=nlp)["advisories"]
        assert advs == [], f"合法句被报 advisory（误报）: {s} -> {advs}"


def test_tempus_advisory_wired_but_not_counted_as_error(nlp):
    """接线缝：advisory 进并列键 `advisories`（统一形状、level=warning），**不进 error 计数**。

    判别力（变异自证①）：把 tempus 的 severity 改成 error ⇒ 路由翻进 `violations` ⇒
    `collect_violations` 非空 ⇒ 本用例 `== []` 断言 MUST 红。
    """
    from delector.services.writing import analyze_a1_email, collect_violations

    letter = "Liebe Maria,\ngestern gehe ich zur Schule.\nViele Grüße\nAnna"
    diag = analyze_a1_email(letter, nlp=nlp)
    assert diag["judge_engine"] == "rules+spacy"
    tempus = [a for a in diag["advisories"] if a["rule"] == "tempus"]
    assert len(tempus) == 1
    assert tempus[0]["level"] == "warning"
    assert set(tempus[0].keys()) == {"rule", "level", "message", "span"}
    assert tempus[0]["span"] == (21, 25), "advisory 的 span 与 detect_* 同口径（指向 gehe）"
    assert collect_violations(diag) == [], "advisory 不得进 error 计数（否则阻断收敛）"
    assert all(v["rule"] != "tempus" for v in diag["violations"]), "advisory 只住 advisories 键"
