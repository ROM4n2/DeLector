# -*- coding: utf-8 -*-
"""
Contract and regression tests for Goethe-Zertifikat A1 Wortliste & Sprechen Lab.
"""
import io
import zipfile
from fastapi.testclient import TestClient
from server import app
import a1_dict

client = TestClient(app, client=("127.0.0.1", 54321))


def test_a1_dict_dataset_structure():
    """验证 A1 考纲词库与口语题库数据完整性与结构规范。"""
    # 1. 15 大生活主题
    assert len(a1_dict.A1_TOPICS) == 15
    for key, label, kw in a1_dict.A1_TOPICS:
        assert key and label and kw

    # 2. 650+ 官方考纲词
    assert len(a1_dict.GOETHE_A1_VOCAB) >= 600
    for lemma, entry in a1_dict.GOETHE_A1_VOCAB.items():
        assert "word" in entry and "definition_zh" in entry
        assert "topic" in entry and entry["topic"]
        assert "pos" in entry
        assert "example_de" in entry and "example_zh" in entry
        if entry["pos"] == "NOUN":
            assert entry["gender"] in ("Masc", "Fem", "Neut", "Plur", None)

    # 3. 口语 Teil 2 主题抽词卡 (30+)
    assert len(a1_dict.A1_SPRECHEN_TEIL2) >= 30
    for card in a1_dict.A1_SPRECHEN_TEIL2:
        assert card.get("topic_id")
        assert card.get("keyword")
        assert len(card.get("prompts", [])) >= 1
        for p in card["prompts"]:
            assert p.get("q") and p.get("a") and p.get("type") in ("W-Frage", "Ja/Nein-Frage")

    # 4. 口语 Teil 3 情景图标请求卡 (20+)
    assert len(a1_dict.A1_SPRECHEN_TEIL3) >= 20
    for card in a1_dict.A1_SPRECHEN_TEIL3:
        assert card.get("icon")
        assert card.get("keyword")
        assert card.get("situation")
        assert len(card.get("requests", [])) >= 1
        for r in card["requests"]:
            assert r.get("utterance") and r.get("response")


def test_a1_topics_endpoint():
    """GET /api/a1/topics 返回 15 大主题及对应词汇统计。"""
    res = client.get("/api/a1/topics")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 15
    first = data[0]
    assert "key" in first and "label" in first and "count" in first
    assert first["count"] > 0


def test_a1_vocab_endpoint_filtering():
    """GET /api/a1/vocab 支持全量查询、主题过滤与关键字模糊搜索。"""
    # 1. 全量
    res_all = client.get("/api/a1/vocab")
    assert res_all.status_code == 200
    all_words = res_all.json()
    assert len(all_words) >= 600

    # 2. 按主题过滤 (food)
    res_food = client.get("/api/a1/vocab?topic=food")
    assert res_food.status_code == 200
    food_words = res_food.json()
    assert len(food_words) > 0
    assert all(w["topic"] == "food" for w in food_words)

    # 3. 按关键字搜索
    res_search = client.get("/api/a1/vocab?q=Wasser")
    assert res_search.status_code == 200
    search_words = res_search.json()
    assert any("Wasser" in w["word"] or "wasser" in w["lemma"] for w in search_words)


def test_a1_sprechen_teil2_endpoint():
    """GET /api/a1/sprechen/teil2 返回 Teil 2 问答卡，并支持按主题过滤。"""
    res = client.get("/api/a1/sprechen/teil2")
    assert res.status_code == 200
    cards = res.json()
    assert len(cards) >= 30

    res_topic = client.get("/api/a1/sprechen/teil2?topic=personal")
    assert res_topic.status_code == 200
    topic_cards = res_topic.json()
    assert len(topic_cards) > 0
    assert all(c["topic_id"] == "personal" for c in topic_cards)


def test_a1_sprechen_teil3_endpoint():
    """GET /api/a1/sprechen/teil3 返回 Teil 3 考场情景与物品请求卡。"""
    res = client.get("/api/a1/sprechen/teil3")
    assert res.status_code == 200
    cards = res.json()
    assert len(cards) >= 20
    first = cards[0]
    assert "icon" in first and "situation" in first and "requests" in first


def test_a1_anki_export_endpoint():
    """GET /api/a1/export/anki 导出合法 apkg 牌组二进制包。"""
    res = client.get("/api/a1/export/anki")
    assert res.status_code == 200
    assert "application/octet-stream" in res.headers.get("content-type", "")
    assert len(res.content) > 1000
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert "collection.anki2" in zf.namelist() or "collection.anki21" in zf.namelist()


def test_a1_frontend_html_structure():
    """验证 static/index.html 中 A1 考纲速通分段与工具栏 DOM 结构。"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="seg-a1"' in html
    assert 'id="a1-toolbar"' in html
    assert 'id="a1-topic-pills"' in html
    assert 'id="a1-tab-vocab"' in html
    assert 'id="a1-tab-teil2"' in html
    assert 'id="a1-tab-teil3"' in html


def test_a1_frontend_js_bindings():
    """验证 cards.js 和 main.js 中 A1 核心交互函数导出。"""
    with open("static/js/cards.js", "r", encoding="utf-8") as f:
        cards_js = f.read()

    assert "setA1Mode" in cards_js
    assert "filterA1Topic" in cards_js
    assert "saveA1WordToDeck" in cards_js
    assert "renderA1PokerCard" in cards_js

    with open("static/js/main.js", "r", encoding="utf-8") as f:
        main_js = f.read()

    assert "setA1Mode" in main_js
    assert "filterA1Topic" in main_js
    assert "saveA1WordToDeck" in main_js
    assert "Object.assign(window" in main_js


def test_a1_css_styling_and_tokens():
    """验证 static/style.css 中 A1 专用组件、性属色彩与考场抽卡样式。"""
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".a1-toolbar" in css
    assert ".a1-pill" in css
    assert ".a1-card-gender-m" in css
    assert ".a1-card-gender-f" in css
    assert ".a1-card-gender-n" in css
    assert ".a1-sprechen-card" in css
