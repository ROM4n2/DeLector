"""ADR-0026 契约：正文段落必须是纯行内短语内容流。

W3C HTML5 解析规范规定 `<p>` 只能承载 Phrasing Content。一旦在 `<p>` 内部出现
块级元素（`<div>`），浏览器解析器会无条件自动闭合前置 `<p>`，导致整篇德语长文
被物理肢解为大量散落的单句短行。

本测试在静态层面锁死该缺陷类：
1. `reader.js` 的句子包装模板内严禁出现任何块级标签；
2. 句子级拓扑五场域不得再以行内 strip 的形式预埋进正文；
3. 拓扑分析必须收敛到右侧抽屉（`openSyntaxDrawerForSentence`）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
READER_JS = REPO_ROOT / "static" / "js" / "reader.js"

BLOCK_TAGS = (
    "div",
    "p",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "ul",
    "ol",
    "li",
    "table",
    "form",
    "fieldset",
    "figure",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
)


def _reader_source() -> str:
    return READER_JS.read_text(encoding="utf-8")


def _sent_wrapper_template() -> str:
    """抽出 `const sentWrapper = \\`...\\`;` 这段模板字符串的实体。"""
    source = _reader_source()
    match = re.search(
        r"const sentWrapper = `(?P<body>.*?)`;",
        source,
        re.DOTALL,
    )
    assert match is not None, "reader.js 中未找到 sentWrapper 模板（结构已变更，请同步本契约）"
    return match.group("body")


def _paragraph_assembly() -> str:
    """抽出所有推送进 paraElements 的段落模板（剥掉最外层段落标签本身）。"""
    source = _reader_source()
    pushes = re.findall(r"paraElements\.push\(\s*`(?P<body>.*?)`\s*\)", source, re.DOTALL)
    assert pushes, "reader.js 中未找到 paraElements.push 段落装配代码"
    body = "\n".join(pushes)
    return body.replace('<p class="reader-p">', "").replace("</p>", "")


def test_sent_wrapper_contains_no_block_level_tags() -> None:
    body = _sent_wrapper_template().lower()
    offenders = [tag for tag in BLOCK_TAGS if f"<{tag}" in body]
    assert offenders == [], (
        "句子包装模板内出现块级标签 "
        f"{offenders}；`<p class=\"reader-p\">` 内只允许 Phrasing Content，"
        "否则浏览器会强制闭合 <p> 把段落切成单句碎块（ADR-0026 决策 1A）。"
    )


def test_paragraph_assembly_is_pure_inline_stream() -> None:
    body = _paragraph_assembly().lower()
    offenders = [tag for tag in BLOCK_TAGS if f"<{tag}" in body]
    assert offenders == [], (
        f"段落装配模板内出现块级标签 {offenders}；段落内只应拼接行内句子单元。"
    )


def test_inline_topology_strip_is_removed() -> None:
    source = _reader_source()
    assert "sentence-topology-strip" not in source, (
        "正文仍预埋 sentence-topology-strip；五场域拓扑必须收敛到右侧抽屉（ADR-0026 决策 1A）。"
    )
    assert "sent-topology-" not in source, (
        "正文仍按句子生成 sent-topology-<id> 块节点；该节点是段落碎裂的物理根因。"
    )


def test_topology_entry_point_still_reachable() -> None:
    """移除行内 strip 后，句法分析入口必须仍然存在且指向抽屉。"""
    source = _reader_source()
    assert "export function openSyntaxDrawerForSentence(" in source, (
        "openSyntaxDrawerForSentence 丢失：移除行内 strip 后句法分析将无处可达。"
    )
    assert "renderDetailedFelderGrid(" in source, (
        "抽屉内必须继续渲染五场域明细网格，否则移除行内 strip 会丢失分级信息。"
    )


# ── 词阶视觉降噪与三档透视模式（ADR-0026 决策 2C） ──────────────────────────────

STYLE_CSS = REPO_ROOT / "static" / "style.css"
TOKENS_CSS = REPO_ROOT / "static" / "css" / "tokens.css"
READER_HTML = REPO_ROOT / "static" / "views" / "reader.html"
MAIN_JS = REPO_ROOT / "static" / "js" / "main.js"
INDEX_HTML = REPO_ROOT / "static" / "index.html"

CEFR_MODES = ("immersive", "exam", "heatmap")


def _rule_body(css: str, selector: str) -> str:
    """取出某个选择器对应的声明块（用于断言具体声明，而非整份文件的松散包含）。"""
    match = re.search(
        re.escape(selector) + r"\s*\{(?P<body>[^}]*)\}",
        css,
        re.DOTALL,
    )
    assert match is not None, f"style.css 中未找到选择器 {selector!r}"
    return match.group("body")


def test_baseline_tokens_define_no_background() -> None:
    """默认档（沉浸精读）下 A1/A2 不得铺任何底色。"""
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert "background: transparent" in _rule_body(css, ".tok.A1,\n.tok.A2"), (
        "A1/A2 默认必须是 transparent：基石词占正文 70%~80%，铺色即碎花布噪声。"
    )


def test_heatmap_mode_restores_full_color_scale() -> None:
    """全景热力档必须能把五档色阶完整恢复回来（信息不丢失）。"""
    css = STYLE_CSS.read_text(encoding="utf-8")
    for level in ("A1", "A2", "B1", "B2", "C1"):
        selector = f"#reader-content.cefr-mode-heatmap .tok.{level}"
        body = _rule_body(css, selector)
        assert f"var(--hl-{level})" in body, (
            f"全景热力档缺少 {level} 色阶恢复规则；分级信息被阉割。"
        )


def test_exam_mode_keeps_only_b2_and_c1() -> None:
    """考点聚焦档必须把 A1/A2/B1 归零，只留 B2 与 C1。"""
    css = STYLE_CSS.read_text(encoding="utf-8")
    zeroed = _rule_body(
        css,
        "#reader-content.cefr-mode-exam .tok.A1,\n"
        "#reader-content.cefr-mode-exam .tok.A2,\n"
        "#reader-content.cefr-mode-exam .tok.B1",
    )
    assert "background: transparent" in zeroed
    exam_b2 = _rule_body(css, "#reader-content.cefr-mode-exam .tok.B2")
    assert "--cefr-edge-exam" in exam_b2


def test_cefr_mode_tokens_exist_in_both_stylesheets() -> None:
    """tokens.css 是 token 正主，style.css 持有同值副本，两处必须同时定义。"""
    for path in (TOKENS_CSS, STYLE_CSS):
        css = path.read_text(encoding="utf-8")
        for token in ("--cefr-edge-weak", "--cefr-edge-exam"):
            assert token in css, f"{path.name} 缺少词阶透视 token {token}"


def test_reader_control_surface_exposes_three_modes() -> None:
    html = READER_HTML.read_text(encoding="utf-8")
    assert 'class="typo-pill cefr-mode-pill"' in html, "阅读器缺少词阶透视档位胶囊容器"
    for mode in CEFR_MODES:
        assert f'data-cefr-mode="{mode}"' in html, f"缺少 {mode} 档按钮"
        assert f"setCefrVisionMode('{mode}')" in html, f"{mode} 档未绑定 setCefrVisionMode"


def test_vision_mode_controller_is_wired_to_window() -> None:
    reader = _reader_source()
    assert "export function setCefrVisionMode(" in reader
    assert "export function applyCefrVisionMode(" in reader
    main = MAIN_JS.read_text(encoding="utf-8")
    assert "  setCefrVisionMode,\n" in main, (
        "setCefrVisionMode 未键入 main.js：模板内联 onclick 会打到 undefined 上。"
    )
    assert "applyCefrVisionMode();" in reader, (
        "renderReaderContent 必须应用一次词阶透视模式，否则首屏落回无 class 的裸样式。"
    )


def test_index_html_carries_vision_mode_markup() -> None:
    """index.html 是模板构建产物：不同步则用户实际加载的页面没有档位胶囊。"""
    index = INDEX_HTML.read_text(encoding="utf-8")
    assert 'class="typo-pill cefr-mode-pill"' in index, (
        "static/index.html 未包含词阶透视胶囊，需重跑 tools/build_index_html.py。"
    )
