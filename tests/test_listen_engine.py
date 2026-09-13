"""
Tests for the dictation diagnosis engine (delector/services/listen.py).

规格：docs/specs/2026-09-13-listening-micro-training-design.md §3
七类归因各一例 + 标点剥离 / 空输入 / 分数计算，status 与 hint 均钉死。
"""

from delector.services.listen import diagnose_diktat


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
