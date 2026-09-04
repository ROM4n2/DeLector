# -*- coding: utf-8 -*-
"""背词工作台与主站共享设计 Token 测试。"""
import os
import re

ROOT = os.path.dirname(__file__)
TOKENS_CSS_PATH = os.path.join(ROOT, "static", "css", "tokens.css")
STYLE_CSS_PATH = os.path.join(ROOT, "static", "style.css")
WORKBENCH_HTML_PATH = os.path.join(ROOT, "static", "german", "workbench.html")


def test_tokens_css_exists_and_contains_core_tokens():
    assert os.path.exists(TOKENS_CSS_PATH), "static/css/tokens.css 必须存在"
    content = open(TOKENS_CSS_PATH, encoding="utf-8").read()

    # 1. 纸张与表面 (Surfaces)
    for token in ("--paper", "--paper-card", "--paper-warm", "--paper-tint"):
        assert token in content, f"tokens.css 缺少纸面变量 {token}"
    assert "#faf8f5" in content.lower(), "--paper 应为 #FAF8F5"

    # 2. 墨水与线条 (Ink & Rule)
    for token in ("--ink", "--pencil", "--muted", "--rule", "--border"):
        assert token in content, f"tokens.css 缺少墨水与规则线变量 {token}"
    assert "#15140f" in content.lower(), "--ink 应为 #15140F"
    assert "#d8d0c2" in content.lower(), "--rule 应为 #D8D0C2"

    # 3. 认知反馈色系 (Cognitive & Accent Colors)
    for token in ("--accent", "--moss", "--mustard", "--cherry"):
        assert token in content, f"tokens.css 缺少记忆反馈/重点色变量 {token}"
    assert "#c14a2b" in content.lower(), "--accent 应为陶土赤红 #C14A2B"
    assert "#3b6e3f" in content.lower(), "--moss (Good) 应为苔藓绿 #3B6E3F"
    assert "#b03030" in content.lower(), "--cherry (Again) 应为樱桃红 #B03030"

    # 4. 字体排印 (Typography)
    for token in ("--serif", "--sans", "--mono"):
        assert token in content, f"tokens.css 缺少字体族变量 {token}"


def test_style_css_imports_tokens_css():
    assert os.path.exists(STYLE_CSS_PATH)
    content = open(STYLE_CSS_PATH, encoding="utf-8").read()
    assert re.search(r'@import\s+(?:url\()?["\'](?:css/)?tokens\.css["\']\)?', content), \
        "static/style.css 必须引入 tokens.css"


def test_workbench_html_imports_tokens_and_maps_editorial_vars():
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()

    # 1. 检查 tokens.css 引入
    assert '<link rel="stylesheet" href="../css/tokens.css">' in content or \
           re.search(r'<link\s+rel=["\']stylesheet["\']\s+href=["\']\.\./css/tokens\.css["\']', content), \
           "workbench.html 必须在 head 中引入 ../css/tokens.css"

    # 2. 检查 :root 映射
    root_match = re.search(r':root\s*\{([^}]+)\}', content)
    assert root_match, "workbench.html 必须包含 :root 样式声明"
    root_block = root_match.group(1)

    assert "--bg: var(--paper" in root_block or "--bg:var(--paper" in root_block, "--bg 应映射到 var(--paper"
    assert "--text: var(--ink" in root_block or "--text:var(--ink" in root_block, "--text 应映射到 var(--ink"
    assert "--line: var(--rule" in root_block or "--line:var(--rule" in root_block, "--line 应映射到 var(--rule"
    assert "--accent: var(--accent" in root_block or "--accent:var(--accent" in root_block, "--accent 应映射到 var(--accent"
    assert "--good: var(--moss" in root_block or "--good:var(--moss" in root_block, "--good 应映射到 var(--moss"
    assert "--again: var(--cherry" in root_block or "--again:var(--cherry" in root_block, "--again 应映射到 var(--cherry"


def test_workbench_scope_selector_modes():
    """#scopeSeg 必须覆盖 data-scope="core"、"all" 与 "reader" 三档。"""
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()
    assert 'id="scopeSeg"' in content, "workbench.html 必须包含 #scopeSeg"
    seg = content.split('id="scopeSeg"')[1].split("</div>")[0]
    assert 'data-scope="core"' in seg, '#scopeSeg 必须包含 data-scope="core"'
    assert 'data-scope="all"' in seg, '#scopeSeg 必须包含 data-scope="all"'
    assert 'data-scope="reader"' in seg, '#scopeSeg 必须包含 data-scope="reader"'


def test_workbench_editorial_typography_contract():
    """验证 workbench.html 遵循全局字体体系与 960px 画布排版规范。"""
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()

    # 1. body 必须使用 var(--sans, ...)
    body_match = re.search(r'(?<![,\w])body\s*\{([^}]+)\}', content)
    assert body_match, "workbench.html 必须包含 body 样式声明"
    body_css = body_match.group(1)
    assert re.search(r'font-family\s*:\s*var\(--sans', body_css), \
        "body 必须使用 var(--sans, ...)"

    # 2. font-family 声明中不得硬编码 "Microsoft YaHei" 或 "Segoe UI"
    assert not re.search(r'font-family\s*:\s*[^;}]*(?:Microsoft YaHei|Segoe UI)', content, re.IGNORECASE), \
        "workbench.html 不得在 font-family 声明中硬编码 'Microsoft YaHei' 或 'Segoe UI'"

    # 3. .wrap 画布排版：max-width 应为 960px（或 var(--wrap-max, 960px)），而非旧的 1060px
    wrap_match = re.search(r'\.wrap\s*\{([^}]+)\}', content)
    assert wrap_match, "workbench.html 必须包含 .wrap 样式规则"
    wrap_css = wrap_match.group(1)
    assert "1060px" not in wrap_css, ".wrap 不应再使用旧的 max-width: 1060px"
    assert re.search(r'max-width\s*:\s*(?:var\(--wrap-max,\s*960px\)|960px)', wrap_css), \
        ".wrap 必须使用 max-width: 960px 或 var(--wrap-max, 960px)"


def test_workbench_editorial_navigation_contract():
    """验证 workbench.html 的出版物风格轻量化导航与顶栏重塑契约。"""
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()

    # 1. header.top h1 必须使用衬线字体 var(--serif, ...)
    h1_match = re.search(r'header\.top\s+h1\s*\{([^}]+)\}', content)
    assert h1_match, "必须包含 header.top h1 样式声明"
    h1_css = h1_match.group(1)
    assert re.search(r'font-family\s*:\s*var\(--serif', h1_css), \
        "header.top h1 必须使用 var(--serif, ...)"

    # 2. nav.tabs 不得使用旧版厚重卡片容器样式（border-radius:var(--radius) 或 box-shadow:var(--shadow)）
    tabs_match = re.search(r'(?<![.\w])nav\.tabs\s*\{([^}]+)\}', content)
    assert tabs_match, "必须包含 nav.tabs 样式声明"
    tabs_css = tabs_match.group(1)
    assert "border-radius:var(--radius)" not in tabs_css and "border-radius: var(--radius)" not in tabs_css, \
        "nav.tabs 不得使用厚重卡片圆角 border-radius:var(--radius)"
    assert "box-shadow:var(--shadow)" not in tabs_css and "box-shadow: var(--shadow)" not in tabs_css, \
        "nav.tabs 不得使用厚重投影 box-shadow:var(--shadow)"

    # 3. nav.tabs button.active 必须使用下划线 border-bottom 与 var(--accent)，且不可使用实心背景 background:var(--accent)
    active_match = re.search(r'nav\.tabs\s+button\.active\s*\{([^}]+)\}', content)
    assert active_match, "必须包含 nav.tabs button.active 样式声明"
    active_css = active_match.group(1)
    assert re.search(r'border-bottom\s*:\s*2px\s+solid\s+var\(--accent\)', active_css) or \
           ("border-bottom" in active_css and "var(--accent)" in active_css), \
        "nav.tabs button.active 必须使用 border-bottom: 2px solid var(--accent)"
    assert "background:var(--accent)" not in active_css and "background: var(--accent)" not in active_css, \
        "nav.tabs button.active 不得使用实心背景 background:var(--accent)"


def test_workbench_zettelkasten_card_and_stamp_buttons_contract():
    """验证 Zettelkasten 实体学术卡片箱与矿物植物印章式评分座契约。"""
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()

    # 1. .face background 必须使用 var(--panel)
    face_match = re.search(r'(?<![.\w])\.face\s*\{([^}]+)\}', content)
    assert face_match, "workbench.html 必须包含 .face 样式规则"
    face_css = face_match.group(1)
    assert "background:var(--panel)" in face_css or "background: var(--panel)" in face_css or \
           re.search(r'background\s*:\s*var\(--panel', face_css), \
        ".face 必须使用 background: var(--panel)"

    # 2. .face .hw 必须使用 var(--serif
    hw_match = re.search(r'\.face\s+\.hw\s*\{([^}]+)\}', content)
    assert hw_match, "workbench.html 必须包含 .face .hw 样式规则"
    hw_css = hw_match.group(1)
    assert re.search(r'font-family\s*:\s*var\(--serif', hw_css), \
        ".face .hw 必须使用 var(--serif, ...)"

    # 3. .rate-btn 基础与状态样式断言：消除实心大白字 color: #fff
    rate_match = re.search(r'(?<![.\w])\.rate-btn\s*\{([^}]+)\}', content)
    assert rate_match, "workbench.html 必须包含 .rate-btn 基础样式规则"
    rate_css = rate_match.group(1)
    assert "color:#fff" not in rate_css and "color: #fff" not in rate_css and "color:#ffffff" not in rate_css.lower(), \
        ".rate-btn 基础样式不得使用实心白字 color: #fff"

    # 4. .rate-btn[data-g="3"] 必须使用 var(--good-soft 且不得包含 color: #fff
    btn3_match = re.search(r'\.rate-btn\[data-g=["\']3["\']\]\s*\{([^}]+)\}', content)
    assert btn3_match, "workbench.html 必须包含 .rate-btn[data-g='3'] 样式规则"
    btn3_css = btn3_match.group(1)
    assert "var(--good-soft" in btn3_css, ".rate-btn[data-g='3'] 必须使用 var(--good-soft"
    assert "color:#fff" not in btn3_css and "color: #fff" not in btn3_css, \
        ".rate-btn[data-g='3'] 不得使用实心白字 color: #fff"

    # 5. .rate-btn[data-g="1"] 必须使用 var(--again-soft 且不得包含 color: #fff
    btn1_match = re.search(r'\.rate-btn\[data-g=["\']1["\']\]\s*\{([^}]+)\}', content)
    assert btn1_match, "workbench.html 必须包含 .rate-btn[data-g='1'] 样式规则"
    btn1_css = btn1_match.group(1)
    assert "var(--again-soft" in btn1_css, ".rate-btn[data-g='1'] 必须使用 var(--again-soft"
    assert "color:#fff" not in btn1_css and "color: #fff" not in btn1_css, \
        ".rate-btn[data-g='1'] 不得使用实心白字 color: #fff"


def test_workbench_editorial_secondary_views_contract():
    """验证自测题与词库辅助视图 Editorial 风格细化契约。"""
    assert os.path.exists(WORKBENCH_HTML_PATH), "static/german/workbench.html 必须存在"
    content = open(WORKBENCH_HTML_PATH, encoding="utf-8").read()

    # 1. 断言 .qword, .spell-input, .kpi .v, table.wtab .hw 使用 var(--serif 而非 raw Georgia,serif
    for selector_re in (
        r'\.qword\s*\{([^}]+)\}',
        r'\.spell-input\s*\{([^}]+)\}',
        r'\.kpi\s+\.v\s*\{([^}]+)\}',
        r'table\.wtab\s+\.hw\s*\{([^}]+)\}',
    ):
        m = re.search(selector_re, content)
        assert m, f"找不到选择器样式：{selector_re}"
        rule_css = m.group(1)
        assert "Georgia,serif" not in rule_css, f"{selector_re} 不得硬编码 Georgia,serif"
        assert "var(--serif" in rule_css, f"{selector_re} 必须使用 var(--serif, ...)"

    # 2. 断言 table.wtab .ipa 使用 var(--mono
    ipa_m = re.search(r'table\.wtab\s+\.ipa\s*\{([^}]+)\}', content)
    assert ipa_m, "找不到 table.wtab .ipa 样式规则"
    ipa_css = ipa_m.group(1)
    assert "var(--mono" in ipa_css, "table.wtab .ipa 必须使用 var(--mono, ...)"

    # 3. 断言 .qopt 具有 8px 圆角
    qopt_m = re.search(r'(?<![.\w])\.qopt\s*\{([^}]+)\}', content)
    assert qopt_m, "找不到 .qopt 基础样式规则"
    qopt_css = qopt_m.group(1)
    assert re.search(r'border-radius\s*:\s*8px', qopt_css), ".qopt 必须包含 border-radius: 8px"
