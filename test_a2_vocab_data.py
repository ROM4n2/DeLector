# -*- coding: utf-8 -*-
"""
DeLector - A2 词汇数据契约与规范化格式测试。
验证 A2 词库从 core_dict 提取、名词定冠词 (der/die/das) 拼装与首字母大写、动词/形容词小写保持。
"""
import pytest
from database import get_vocab_by_cefr, format_vocab_headword


def test_format_vocab_headword_helper():
    """测试 format_vocab_headword 工具函数的格式化契约。"""
    assert format_vocab_headword("abenteuer", "NOUN", "Neut") == "das Abenteuer"
    assert format_vocab_headword("abfahrt", "NOUN", "Fem") == "die Abfahrt"
    assert format_vocab_headword("abfall", "NOUN", "Masc") == "der Abfall"
    assert format_vocab_headword("abbiegen", "VERB", None) == "abbiegen"
    assert format_vocab_headword("aktuell", "ADJ", None) == "aktuell"
    assert format_vocab_headword("", "NOUN", "Masc") == ""


def test_get_vocab_by_cefr_a2_returns_974_words():
    """验证 get_vocab_by_cefr('A2') 完整返回 974 个词条。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    assert res["cefr"] == "A2"
    assert res["total"] == 974
    assert len(res["words"]) == 974

    word_map = {w["id"]: w for w in res["words"]}
    assert "a2-abenteuer" in word_map
    assert "a2-abfahrt" in word_map
    assert "a2-abbiegen" in word_map


def test_a2_noun_articles_and_capitalization():
    """验证 A2 名词均带有正确定冠词 (der/die/das) 且首字母大写。"""
    res = get_vocab_by_cefr(cefr="A2", scope="all")
    word_map = {w["id"]: w for w in res["words"]}

    assert word_map["a2-abenteuer"]["hw"] == "das Abenteuer"
    assert word_map["a2-abfahrt"]["hw"] == "die Abfahrt"
    assert word_map["a2-abfall"]["hw"] == "der Abfall"
    assert word_map["a2-apotheke"]["hw"] == "die Apotheke"
    assert word_map["a2-krankenhaus"]["hw"] == "das Krankenhaus"

    # 全量名词抽样检验
    nouns = [w for w in res["words"] if w.get("pos") in ("NOUN", "n.", "m.", "f.")]
    assert len(nouns) == 497
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

    assert word_map["a2-abbiegen"]["hw"] == "abbiegen"
    assert word_map["a2-aktuell"]["hw"] == "aktuell"

    for w in res["words"]:
        if w.get("pos") in ("VERB", "ADJ", "ADV", "PREP", "CONJ"):
            assert w["hw"][0].islower(), f"Non-noun {w['id']} '{w['hw']}' 词头不应大写"
