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

