# -*- coding: utf-8 -*-
"""
Contract and regression tests for Goethe-Zertifikat A1 Wortliste & Sprechen Lab.
"""
import io
import os
import pytest
import re
import zipfile
os.environ.setdefault("DATABASE_PATH", "test_delector_goethe_a1.db")
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
    """验证 static/index.html 中 A1 考纲速通分段与工具栏 DOM 结构。

    ADR-0005 Task 2 起备考域接管 A1 入口：seg-a1 分段按钮删除
    （替代入口 = view-exam 的 exam-card-vocab），工具栏 id 不变、
    原样迁入 view-exam。
    """
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="exam-card-vocab"' in html  # A1 考纲入口现在在备考域
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
    assert ".deck-controls-bottom" in css
    assert ".deck-nav-btn" in css


def _all_css_blocks(css, selector):
    """Yield (position, declaration_block) for every occurrence of an exact selector."""
    blocks = []
    idx = 0
    while True:
        idx = css.find(selector + " {", idx)
        if idx == -1:
            idx = css.find(selector + "{", idx)
        if idx == -1:
            break
        start = css.find("{", idx) + 1
        depth, i = 1, start
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        blocks.append((idx, css[start : i - 1]))
        idx = i
    return blocks


def test_cards_seg_bar_is_scrollable_on_narrow_screens():
    """卡片分段栏在窄屏（安卓）必须自身横向滚动，而不是被 .view 裁掉。

    v4.7.1 报告：5 个段按钮合计约 527px，超出 360px 视口后被移动端守卫
    `.view { overflow-x: hidden }` 裁切，最后的「歌德 A1 速通」tab 永远不可见
    （只显示到 Präpositionen）。

    修法只落在移动端媒体块（那里才有 .view 的 overflow-x:hidden）：该块里的
    `.cards-seg-bar` 加 `overflow-x: auto` + `max-width: 100%` 让超出部分可滑动
    到达，`.cards-seg-btn` 加 `flex-shrink: 0` 保持自然宽度。

    ⚠️ 不能把滚动规则加在基础（非 media）`.cards-seg-bar` 上：桌面内容列约 712px
    比 seg-bar 自然宽 741px 窄，基础规则加 overflow 会把桌面「歌德 A1」右缘裁掉
    （1280/1600px 实测回归）。所以本测试同时断言：存在滚动块（移动端修复生效）
    且基础块没有 overflow-x（桌面保持自然宽度）。
    """
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    seg_bar_blocks = _all_css_blocks(css, ".cards-seg-bar")
    assert seg_bar_blocks, ".cards-seg-bar 规则块不存在"
    base_block = seg_bar_blocks[0][1]
    scroll_blocks = [
        block for pos, block in seg_bar_blocks
        if re.search(r"overflow-x\s*:\s*auto", block) and "max-width: 100%" in block
    ]
    assert scroll_blocks, (
        "移动端媒体块里的 .cards-seg-bar 必须 overflow-x:auto + max-width:100%，"
        "否则超出视口的段标签被 .view 裁掉，「歌德 A1」不可达"
    )
    assert not re.search(r"overflow-x\s*:\s*(auto|scroll)", base_block), (
        "基础 .cards-seg-bar 规则块不能有 overflow-x（桌面内容列比 seg-bar 窄，"
        "加了会把桌面 A1 tab 右缘裁掉）"
    )

    seg_btn_blocks = _all_css_blocks(css, ".cards-seg-btn")
    assert any(
        re.search(r"flex-shrink\s*:\s*0", block) for _, block in seg_btn_blocks
    ), ".cards-seg-btn 必须 flex-shrink:0，段标签不压缩换行，由滚动接管"


@pytest.fixture(autouse=True, scope="module")
def _m5_isolated_db_teardown():
    """M5-1: 模块结束时回收句柄并删除隔离临时库，防残留串入下次运行。"""
    yield
    import gc, os as _os
    gc.collect()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        try:
            _os.remove("test_delector_goethe_a1.db" + _suffix)
        except OSError:
            pass
