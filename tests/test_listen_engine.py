"""
Tests for the dictation diagnosis engine (delector/services/listen.py).

规格：docs/specs/2026-09-13-listening-micro-training-design.md §3
七类归因各一例 + 标点剥离 / 空输入 / 分数计算，status 与 hint 均钉死。
"""

from delector.services.listen import diagnose_diktat, make_cloze


def test_diagnose_all_correct():
    """完全正确：全部 correct，hint 为空串，score=1。"""
    diag = diagnose_diktat("Ich gehe nach Hause", "Ich gehe nach Hause")
    assert diag.expected == "Ich gehe nach Hause"
    assert diag.actual == "Ich gehe nach Hause"
    assert [t.status for t in diag.tokens] == ["correct", "correct", "correct", "correct"]
    assert all(t.hint == "" for t in diag.tokens)
    assert diag.correct == 4
    assert diag.total == 4
    assert diag.score == 1.0


def test_diagnose_umlaut_variants():
    """变音：ü/u、ä/a、ö/o、ß/ss、é/e 五种映射，hint 给出具体变音对。"""
    cases = [
        ("Müde", "mude", "变音：ü→u"),
        ("Hände", "hande", "变音：ä→a"),
        ("hören", "horen", "变音：ö→o"),
        ("Fuß", "fuss", "变音：ß→ss"),
        ("Café", "cafe", "变音：é→e"),
    ]
    for exp, act, hint in cases:
        diag = diagnose_diktat(exp, act)
        assert diag.tokens[0].token == exp
        assert diag.tokens[0].status == "umlaut"
        assert diag.tokens[0].hint == hint
        assert diag.correct == 0
        assert diag.score == 0.0


def test_diagnose_umlaut_wins_over_case():
    """优先级：变音 > 大小写——「Müde」对「mude」同时含 M/m 大小写差，仍归为变音。"""
    diag = diagnose_diktat("Müde", "mude")
    assert diag.tokens[0].status == "umlaut"
    assert diag.tokens[0].hint == "变音：ü→u"


def test_umlaut_not_case_only_diff():
    """大小写守卫：纯大小写差但含变音字符的词归 case 而非 umlaut。"""
    diag = diagnose_diktat("Übung", "ÜBUNG")
    assert diag.tokens[0].status == "case"
    assert diag.tokens[0].hint == "大小写"
    diag2 = diagnose_diktat("Müde", "MÜDE")
    assert diag2.tokens[0].status == "case"
    assert diag2.tokens[0].hint == "大小写"


def test_short_function_words_not_inflected():
    """最短词长守卫：'es'→'e' 不再误判为词尾屈折，应归 missing/extra。"""
    diag = diagnose_diktat("Es regnet", "E regnet")
    statuses = [t.status for t in diag.tokens]
    assert "inflection" not in statuses
    assert any(t.token == "Es" and t.status == "missing" for t in diag.tokens)
    assert any(t.token == "E" and t.status == "extra" for t in diag.tokens)
    assert diag.correct == 1


def test_diagnose_case():
    """大小写：Der→der 归 case，hint「大小写」，同句其它词不受影响。"""
    diag = diagnose_diktat("Der Hund", "der Hund")
    assert [t.token for t in diag.tokens] == ["Der", "Hund"]
    assert diag.tokens[0].status == "case"
    assert diag.tokens[0].hint == "大小写"
    assert diag.tokens[1].status == "correct"
    assert diag.correct == 1
    assert diag.score == 0.5


def test_diagnose_inflection():
    """词尾屈折：gehen→gehe（-en→-e）、Hause→Haus（-e→∅）归 inflection。"""
    diag = diagnose_diktat("Wir gehen nach Hause", "Wir gehe nach Haus")
    assert [t.token for t in diag.tokens] == ["Wir", "gehen", "nach", "Hause"]
    assert [t.status for t in diag.tokens] == ["correct", "inflection", "correct", "inflection"]
    inflected = [t for t in diag.tokens if t.status == "inflection"]
    assert all(t.hint == "词尾" for t in inflected)
    assert diag.correct == 2
    assert diag.total == 4
    assert diag.score == 0.5


def test_diagnose_missing():
    """缺漏：期望词「gehe」输入中没有 → missing，hint「缺少」。"""
    diag = diagnose_diktat("Ich gehe nach Hause", "Ich nach Hause")
    assert [t.token for t in diag.tokens] == ["Ich", "gehe", "nach", "Hause"]
    assert [t.status for t in diag.tokens] == ["correct", "missing", "correct", "correct"]
    missing = next(t for t in diag.tokens if t.status == "missing")
    assert missing.hint == "缺少"
    assert diag.correct == 3
    assert diag.total == 4
    assert diag.score == 0.75


def test_diagnose_extra():
    """多余：输入词「schnell」期望中没有 → extra，hint「多余」。"""
    diag = diagnose_diktat("Ich gehe nach Hause", "Ich gehe schnell nach Hause")
    assert [t.token for t in diag.tokens] == ["Ich", "gehe", "schnell", "nach", "Hause"]
    assert [t.status for t in diag.tokens] == ["correct", "correct", "extra", "correct", "correct"]
    extra = next(t for t in diag.tokens if t.status == "extra")
    assert extra.hint == "多余"
    assert diag.correct == 4
    assert diag.total == 4
    assert diag.score == 1.0


def test_diagnose_scrambled_order():
    """顺序错乱：LCS 对齐为 missing + extra 组合归因，不误判为全错。"""
    diag = diagnose_diktat("Ich gehe nach Hause", "Ich nach Hause gehe")
    assert [t.token for t in diag.tokens] == ["Ich", "gehe", "nach", "Hause", "gehe"]
    assert [t.status for t in diag.tokens] == ["correct", "missing", "correct", "correct", "extra"]
    assert next(t for t in diag.tokens if t.status == "missing").hint == "缺少"
    assert next(t for t in diag.tokens if t.status == "extra").hint == "多余"
    assert diag.correct == 3
    assert diag.total == 4
    assert diag.score == 0.75


def test_punctuation_stripped_but_token_preserved():
    """首尾标点剥离后比对（大小写/变音规则同样适用），token 保留原始词形。"""
    diag = diagnose_diktat("Hallo, Welt!", "Hallo Welt")
    assert [t.token for t in diag.tokens] == ["Hallo,", "Welt!"]
    assert [t.status for t in diag.tokens] == ["correct", "correct"]
    assert diag.score == 1.0

    diag2 = diagnose_diktat("Gehen!", "geh")
    assert diag2.tokens[0].token == "Gehen!"
    assert diag2.tokens[0].status == "inflection"


def test_empty_inputs_score_zero():
    """空输入边界：双方为空 → 无 token、total=0、score=0；期望非空输入为空 → 全 missing。"""
    diag = diagnose_diktat("", "")
    assert diag.tokens == []
    assert diag.total == 0
    assert diag.correct == 0
    assert diag.score == 0.0

    diag2 = diagnose_diktat("Ich gehe", "")
    assert [t.status for t in diag2.tokens] == ["missing", "missing"]
    assert diag2.total == 2
    assert diag2.score == 0.0


def test_cloze_short_sentence_returns_none():
    """短句（<5 词）不挖空：3 词、4 词均返回 None。"""
    assert make_cloze("Ich gehe nach", "A1") is None
    assert make_cloze("Ich gehe nach Hause", "A1") is None


def test_cloze_blanks_noun():
    """名词句挖名词：非句首大写词 Hund 被挖，四字段钉死。"""
    item = make_cloze("Der Hund schläft heute gern", "A1")
    assert item is not None
    assert item.text_with_blanks == "Der ___ schläft heute gern"
    assert item.answer == "Hund"
    assert item.source == "Der Hund schläft heute gern"
    assert item.blank_index == 1


def test_cloze_blanks_verb():
    """动词句挖动词：无名词候选时挖 -e 结尾非功能词 gehe。"""
    item = make_cloze("Ich gehe morgen sehr früh", "A1")
    assert item is not None
    assert item.text_with_blanks == "Ich ___ morgen sehr früh"
    assert item.answer == "gehe"
    assert item.source == "Ich gehe morgen sehr früh"
    assert item.blank_index == 1


def test_cloze_skips_function_words():
    """功能词不被挖：und/ich 排除，挖名词 Anna。"""
    item = make_cloze("Ich und Anna spielen morgen hier", "A1")
    assert item is not None
    assert item.answer == "Anna"
    assert item.blank_index == 2
    assert item.text_with_blanks == "Ich und ___ spielen morgen hier"
    assert item.source == "Ich und Anna spielen morgen hier"


def test_cloze_no_candidate_returns_none():
    """全功能词/无候选（无大写非句首词、无动词特征词）→ None。"""
    assert make_cloze("Ich und du sind hier", "A1") is None
