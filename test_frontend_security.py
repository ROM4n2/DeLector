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
HOEREN = (ROOT / "static" / "js" / "a1_hoeren.js").read_text(encoding="utf-8")
LESEN = (ROOT / "static" / "js" / "a1_lesen.js").read_text(encoding="utf-8")


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
    assert "deleteArticle(${Number(a.id)}, ${jsAttr(a.title)})" in READER
    assert "inspectSubWord(${jsAttr(k.word)}" in READER
    assert "saveClauseAsGrammarCard(${jsAttr(clauseLabel)}" in READER


def test_main_js_feed_ingest_quotes_are_entity_safe():
    # encodeURIComponent 不转义 '（保留字符 !'()*-._~），必须再套 jsAttr
    assert ("window.ingestFeedItem(${jsAttr(encodeURIComponent(it.link))}, "
            "${jsAttr(encodeURIComponent(it.title))}, this)") in MAIN
    assert "window.selectFeedSource(${jsAttr(s.id)})" in MAIN


def test_a1_hoeren_js_uses_jsattr_for_dynamic_values():
    assert "'${esc(v.word)}'" not in HOEREN
    assert "'${esc(v.meaning)}'" not in HOEREN
    assert "saveVocabChip(${jsAttr(v.word)}, ${jsAttr(v.meaning)}, this)" in HOEREN
    assert "jumpToQuestion(${jsAttr(q.id)})" in HOEREN
    assert "selectOption(${jsAttr(q.id)}, ${jsAttr(opt.key)})" in HOEREN
    assert "playSingleAudio(${jsAttr(q.id)})" in HOEREN


def test_a1_lesen_js_uses_jsattr_for_dynamic_values():
    assert "jumpToQuestion(${jsAttr(q.id)})" in LESEN
    assert "selectOption(${jsAttr(q.id)}," in LESEN
    assert "'${q.id}'" not in LESEN


def test_reader_js_xss_sinks_are_neutralised():
    """reader.js 内嵌模板的 XSS sink 全部经 Number() / safeCefr / esc() 消毒。

    正向锚点锁住修复后的模板形式；反向锚点锁住危险的原始插值形式。
    替换 esc/Number 为 passthrough → 反向锚点复现 → 测试红。
    替换回归（git revert static/js/reader.js 的修改）→ 正向锚点消失 → 测试红。
    """
    # renderMiniBar: recommended_level 白名单收敛 + est_reading_minutes Number 强制
    assert "safeCefr(stats.recommended_level)" in READER
    assert "Number(stats.est_reading_minutes)" in READER
    # 反向：旧的 raw interpolation 不能存在
    assert 'stats.recommended_level || "A1"' not in READER

    # loadArticles: a.id → Number, created_at → esc
    assert "openReader(${Number(a.id)})" in READER
    assert "deleteArticle(${Number(a.id)}" in READER
    assert "${esc(a.created_at)}" in READER

    # token span: t.id → Number, sent.id → Number
    assert 'id="tok-${Number(t.id)}"' in READER
    assert 'onclick="inspect(${Number(t.id)},${Number(sent.id)})"' in READER

    # sent wrapper: sent.id → Number
    assert 'data-sent-id="${Number(sent.id)}"' in READER
    assert "toggleSentenceTopology(${Number(sent.id)})" in READER
    assert 'id="sent-topology-${Number(sent.id)}"' in READER

    # heatbar: cnt → Number
    assert "Number(counts[lvl])" in READER

    # renderFelderSpectrum: sentId → Number
    assert "openSyntaxDrawerForSentence(${Number(sentId)})" in READER

    # clause tree: typeCls strip + tokenIds sanitized + sentId → Number
    assert '.replace(/[^a-z0-9_-]/g, "")' in READER
    assert ".map(Number).filter(Number.isFinite)" in READER
    assert "saveClauseAsGrammarCard(${jsAttr(clauseLabel)}, ${jsAttr(clauseFormula)}, ${jsAttr(clauseText)}, ${Number(sentId)})" in READER

    # renderReaderHeatbar badge: safeCefr
    assert 'safeCefr(stats.recommended_level)' in READER
