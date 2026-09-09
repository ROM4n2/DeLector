# -*- coding: utf-8 -*-
"""遇见区 (view-encounter) SPA 骨架字符串探针。

P0 前端骨架由三块组成：
  1. index.html 新增 <main id="view-encounter" class="view">（列表 + 详情 + 加文本表单）；
  2. 德语文库 (view-home) 内加一张入口卡，携带「遇见区 i+1 短文」标记，点击 show('encounter')；
  3. main.js import './encounter.js' 并接入 show() 路由 —— 满足
     test_frontend_module_graph.py 的可达性要求。

Task A4 只做骨架，不引第三方库、不动 Python 路由 / workbench.html。此测试与
test_german_workbench.py 互不切片（它只 slice workbench.html），因此仅加
「遇见区」入口与结构断言，不碰任何 async-IIFE 定位记号。
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
ENCOUNTER_JS = (ROOT / "static" / "js" / "encounter.js").read_text(encoding="utf-8")


def _view_home_markup():
    """返回 <main id="view-home" ...>...</main> 的整段文本。"""
    start = INDEX.index('id="view-home"')
    # 从该 id 回溯到该 <main> 标签开头
    start = INDEX.rindex("<main", 0, start)
    end = INDEX.index("</main>", start)
    return INDEX[start:end]


def test_index_has_encounter_view_section():
    """index.html 必须含 <main id="view-encounter" class="view"> 结构。"""
    assert 'id="view-encounter"' in INDEX
    assert "view-encounter" in INDEX
    # 骨架结构：列表容器 + 详情容器 + 「＋ 加文本」表单入口
    assert 'id="encounter-text-list"' in INDEX
    assert "encounter-reader" in INDEX


def test_index_encounter_view_has_add_form_entry():
    """view-encounter 必须带一个「＋ 加文本」入口（内联表单开关/表单容器）。"""
    # 探针：加文本按钮文案 + 表单容器 id（主 DOM 中全局存在即可）
    assert "＋ 加文本" in INDEX or "+ 加文本" in INDEX
    assert 'id="encounter-add-form"' in INDEX or "encounter-add-form" in INDEX


def test_index_home_view_has_encounter_entry():
    """德语文库 (view-home) 内必须有进入遇见区的入口卡。"""
    home = _view_home_markup()
    assert "遇见区" in home
    assert "i+1 短文" in home
    # 入口必须真正触发 show('encounter')
    assert "show('encounter')" in home
    # 该入口标记确实落在 view-home 之内，而非顶层 nav（nav 不带遇见区入口）
    assert 'id="view-home"' in home


def test_main_js_imports_encounter_module():
    """main.js 必须 import './encounter.js'（模块图可达性契约）。"""
    assert "./encounter.js" in MAIN_JS
    assert "encounter.js" in MAIN_JS


def test_main_js_show_router_activates_encounter():
    """show() 路由遇到 'encounter' 必须触发列表渲染（惰性 show 式，不做 eager 初始化）。"""
    assert "view-encounter" in MAIN_JS or '=== "encounter"' in MAIN_JS or "view === 'encounter'" in MAIN_JS


def test_encounter_js_exports_view_hooks():
    """encounter.js 提供列表/详情渲染入口（字符串探针级的最小可达性）。"""
    assert "showView" in ENCOUNTER_JS
    assert "fetchTexts" in ENCOUNTER_JS
    assert "renderTextList" in ENCOUNTER_JS


def test_encounter_js_reuses_core_api_helper():
    """encounter.js 复用 core.js 的 api/esc 帮手，而非自行 reimplement fetch。"""
    assert "./core.js" in ENCOUNTER_JS
    assert "api(" in ENCOUNTER_JS
    assert "esc(" in ENCOUNTER_JS
