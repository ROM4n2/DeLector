# -*- coding: utf-8 -*-
"""
DeLector - A2 词汇数据契约与规范化格式测试。
验证 A2 词库从 core_dict 提取、名词定冠词 (der/die/das) 拼装与首字母大写、动词/形容词小写保持。
"""

from delector.core.database import format_vocab_headword, get_vocab_by_cefr
from delector.data.core_dict import CORE_VOCAB_DB

# A2 条数从权威数据源动态推导：官方词表接入后 A2/B1 分布随数据变更
# （abenteuer/abfahrt/abbiegen 等按官方 cefr 改档），硬编码魔数会静默漂移。
A2_TOTAL = sum(1 for val in CORE_VOCAB_DB.values() if val[0].upper() == "A2")
A2_NOUN_TOTAL = sum(
    1 for val in CORE_VOCAB_DB.values() if val[0].upper() == "A2" and val[1] == "NOUN"
)


def test_format_vocab_headword_helper():
    """测试 format_vocab_headword 工具函数的格式化契约。"""
    assert format_vocab_headword("abenteuer", "NOUN", "Neut") == "das Abenteuer"
    assert format_vocab_headword("abfahrt", "NOUN", "Fem") == "die Abfahrt"
    assert format_vocab_headword("abfall", "NOUN", "Masc") == "der Abfall"
    assert format_vocab_headword("abbiegen", "VERB", None) == "abbiegen"
    assert format_vocab_headword("aktuell", "ADJ", None) == "aktuell"
    assert format_vocab_headword("", "NOUN", "Masc") == ""


def test_get_vocab_by_cefr_a2_returns_all_a2_words():
    """验证 get_vocab_by_cefr('A2') 完整返回全部 A2 词条（条数动态对齐数据真值）。

    条数期望从权威数据源（core_dict 中 CEFR=A2 的条目数）动态推导，不硬编码：
    官方词表接入后 A2 分布随数据变更（abenteuer/abfahrt/abbiegen 已按官方 cefr
    改档 B1/A1/B1，不再是 A2）。
    """
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    assert res["cefr"] == "A2"
    assert res["total"] == A2_TOTAL
    assert len(res["words"]) == A2_TOTAL

    word_map = {w["id"]: w for w in res["words"]}
    assert "a2-apotheke" in word_map
    assert "a2-krankenhaus" in word_map
    assert "a2-besuch" in word_map


def test_a2_noun_articles_and_capitalization():
    """验证 A2 名词均带有正确定冠词 (der/die/das) 且首字母大写。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}

    assert word_map["a2-besuch"]["hw"] == "der Besuch"
    assert word_map["a2-ampel"]["hw"] == "die Ampel"
    assert word_map["a2-apotheke"]["hw"] == "die Apotheke"
    assert word_map["a2-krankenhaus"]["hw"] == "das Krankenhaus"
    assert word_map["a2-eis"]["hw"] == "das Eis"

    # 全量名词抽样检验（条数动态对齐数据真值，不硬编码）
    nouns = [w for w in res["words"] if w.get("pos") in ("NOUN", "n.", "m.", "f.")]
    assert len(nouns) == A2_NOUN_TOTAL
    for w in nouns:
        gender = w.get("gender")
        hw = w.get("hw", "")
        if gender == "Masc":
            assert hw.startswith("der "), f"Masc noun {w['id']} hw '{hw}' 缺少 'der ' 前缀"
            assert hw[4].isupper(), f"Masc noun {w['id']} '{hw}' 词首未大写"
        elif gender == "Fem":
            assert hw.startswith("die "), f"Fem noun {w['id']} hw '{hw}' 缺少 'die ' 前缀"
            assert hw[4].isupper(), f"Fem noun {w['id']} '{hw}' 词首未大写"
        elif gender == "Neut":
            assert hw.startswith("das "), f"Neut noun {w['id']} hw '{hw}' 缺少 'das ' 前缀"
            assert hw[4].isupper(), f"Neut noun {w['id']} '{hw}' 词首未大写"


def test_a2_verbs_and_adjectives_stay_lowercase():
    """验证动词、形容词、副词词头保持小写。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}

    assert word_map["a2-anmelden"]["hw"] == "anmelden"
    assert word_map["a2-aktuell"]["hw"] == "aktuell"

    for w in res["words"]:
        if w.get("pos") in ("VERB", "ADJ", "ADV", "PREP", "CONJ"):
            assert w["hw"][0].islower(), f"Non-noun {w['id']} '{w['hw']}' 词头不应大写"
