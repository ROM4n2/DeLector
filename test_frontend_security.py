"""前端 XSS 注入面契约测试。

背景（为什么 esc 不够）：esc() 把 ' 转成 &#39;，但浏览器解析 HTML 属性时会
先把实体还原成原始字符、再交给 JS 引擎执行 —— 单引号在 JS 字符串里「复活」，
精心构造的值即可越狱执行任意代码（卡片词、文章标题都是可注入数据：桌面端
绑 0.0.0.0，POST /api/cards 无鉴权；ingest-url 的标题来自任意外部网页）。

jsAttr(v) = esc(JSON.stringify(v))：JSON 层处理引号/反斜杠/换行/控制字符，
esc 层防止属性本身提前终止，两层缺一不可。
"""

from pathlib import Path

ROOT = Path(__file__).parent
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")
READER = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
MAIN = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")


def test_core_exports_jsattr_helper():
    assert "export function jsAttr(" in CORE


def test_cards_js_no_esc_inside_js_string_literals():
    assert "'${esc(card.word)}'" not in CARDS
    assert "'${esc(c.word)}'" not in CARDS
    assert "'${esc(c.grammar_name)}'" not in CARDS
    assert "'${esc(isVocab ? card.word : card.grammar_name)}'" not in CARDS
    assert CARDS.count("${jsAttr(") >= 5


def test_reader_js_no_esc_inside_js_string_literals():
    assert "'${esc(a.title)}'" not in READER
    assert "'${esc(k.word)}'" not in READER
    # 朴素反斜杠转义可被 \'; 序列绕过（\\' 解析为字面反斜杠 + 存活引号），必须移除
    assert ".replace(/'/g" not in READER
    assert "deleteArticle(${a.id}, ${jsAttr(a.title)})" in READER
    assert "inspectSubWord(${jsAttr(k.word)}" in READER
    assert "saveClauseAsGrammarCard(${jsAttr(clauseLabel)}" in READER


def test_main_js_feed_ingest_quotes_are_entity_safe():
    # encodeURIComponent 不转义 '（保留字符 !'()*-._~），必须再套 jsAttr
    assert ("window.ingestFeedItem(${jsAttr(encodeURIComponent(it.link))}, "
            "${jsAttr(encodeURIComponent(it.title))}, this)") in MAIN
