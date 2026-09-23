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

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
ENCOUNTER_JS = (ROOT / "static" / "js" / "encounter.js").read_text(encoding="utf-8")


def _slice_function(src, name):
    """切出 `function <name>(...) { ... }` 整段（含签名，按大括号配对收尾）。

    用于把断言钉到某个具体函数体，替代「全文子串 in」这类恒真 / 无判别力弱断言
    —— 同一记号（如 Math.round(）往往在别的函数里也出现，全文匹配根本钉不住目标。
    """
    start = src.index(f"function {name}")
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"未找到 function {name} 的闭合大括号")


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


# ── Task 5（i+1 就近选材）：不点开任何一篇即可按本机已背词覆盖率分组 + 标 i+1 ────
# 契约：遇见区列表按已背词覆盖率分区间排序并标出「正好读」；索引端点失败时**逐字**
# 退回既有列表行为（零破坏）。探针风格沿用本文件：读文件 + 子串/结构断言。


def _view_encounter_markup():
    """返回 <main id="view-encounter" ...>...</main> 的整段文本。"""
    start = INDEX.index('id="view-encounter"')
    start = INDEX.rindex("<main", 0, start)
    end = INDEX.index("</main>", start)
    return INDEX[start:end]


def test_encounter_view_has_i1_hint_before_list():
    """① view-encounter 段内必须有 i+1 提示条容器，且位于 #encounter-text-list 之前。"""
    view = _view_encounter_markup()
    assert 'id="enc-i1-hint"' in view
    assert "enc-i1-hint" in view
    hint_at = view.index('id="enc-i1-hint"')
    list_at = view.index('id="encounter-text-list"')
    assert hint_at < list_at, "i+1 提示条容器必须渲染在列表之前"


def test_encounter_js_imports_i1_and_deck_bridge():
    """② encounter.js 必须 import ./enc-i1.js（选材纯函数）与 ./deck-bridge.js（deck 桥）。"""
    assert "./enc-i1.js" in ENCOUNTER_JS
    assert "./deck-bridge.js" in ENCOUNTER_JS


def test_encounter_js_renders_three_band_badges_escaped():
    """③ 渲染路径含三态徽章 class，且展示字段经 esc()（XSS 安全）。"""
    assert "enc-i1-badge" in ENCOUNTER_JS
    for cls in ("enc-i1-i1", "enc-i1-easy", "enc-i1-hard"):
        assert cls in ENCOUNTER_JS, f"缺少三态徽章 class {cls}"
    # 三态文案单点定义（渲染层不散落各区间字面量）
    assert "正好读" in ENCOUNTER_JS
    assert "偏简单" in ENCOUNTER_JS
    assert "偏难" in ENCOUNTER_JS
    # 徽章模板行必须经 esc() 转义（去掉 esc( → 本断言必红）
    badge_lines = [ln for ln in ENCOUNTER_JS.splitlines() if "enc-i1-badge" in ln]
    assert badge_lines, "未找到 enc-i1-badge 徽章渲染"
    assert any("esc(" in ln for ln in badge_lines), "徽章展示字段必须经 esc()"
    # pct 取整 + 百分号必须落在 i1BadgeHtml 函数体内（全文 "Math.round(" 是恒真弱断言：
    # renderCoverage 内亦有，无判别力）。去掉 Math.round(Number(...)) 或 % → 本断言必红。
    badge_body = _slice_function(ENCOUNTER_JS, "i1BadgeHtml")
    assert "enc-i1-badge" in badge_body, "i1BadgeHtml 必须渲染 enc-i1-badge 徽章"
    assert "Math.round(Number(" in badge_body, (
        "i1BadgeHtml 的 pct 必须经 Math.round(Number(rate) * 100) 取整为整数百分比"
    )
    assert "%" in badge_body, "i1BadgeHtml 必须输出百分比（含 %）"


def test_encounter_js_degrades_when_index_endpoint_fails():
    """④ 降级路径：Promise.allSettled 并行拉取；索引失败仍按既有顺序渲染列表。"""
    assert "Promise.allSettled" in ENCOUNTER_JS
    assert "fetchIndex" in ENCOUNTER_JS
    # renderTextList 的 ranked 形参必须可为空（带默认值 → 省略即退回既有行为）。
    assert re.search(
        r"function\s+renderTextList\s*\(\s*texts\s*,\s*ranked\s*=", ENCOUNTER_JS
    ), "renderTextList 的 ranked 形参必须可为空（带默认值）"
    # 降级调用点：索引失败时以「单参」调用（不传 ranked）。
    assert re.search(
        r"renderTextList\s*\(\s*texts\s*\)", ENCOUNTER_JS
    ), "索引失败降级路径必须以 renderTextList(texts) 单参调用"
