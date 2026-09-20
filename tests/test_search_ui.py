# -*- coding: utf-8 -*-
"""全文检索前端（Task 4）静态结构与安全守卫。

覆盖 spec 2026-09-20 §2/§3.4/§4 的前端契约：

- ``static/index.html``：``<main id="view-search" class="view">`` 壳 + 顶栏检索入口 +
  四组结果容器 + 空态 + 五值范围分段控件；
- ``static/js/search.js``：``/api/search`` 调用、300ms 防抖、四组渲染、命中高亮
  **先 esc() 再包 <mark>**（XSS 守卫）、空态、语料空 snippet 降级、端点缺失降级；
- ``static/js/main.js``：import 检索模块 + 注册视图路由 + 命名空间挂载。

风格照 ``tests/test_writer_mobile.py``：读文件做静态切片/结构断言，不起服务、不跑 JS。
"""

import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent


def _text(rel: str) -> str:
    """读仓库内文件；缺失返回空串（RED 阶段 search.js 尚未创建时给干净的断言失败，
    而非模块导入期 FileNotFoundError 的收集错误）。"""
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


INDEX = _text("static/index.html")
MAIN_JS = _text("static/js/main.js")
SEARCH = _text("static/js/search.js")

_SEARCH_PATH = ROOT / "static" / "js" / "search.js"


def _js_fn(src: str, signature: str) -> str:
    """取 ``src`` 中某函数的函数体（签名之后到第一个顶格 ``}`` 之前）。

    顶格 ``}`` 是函数结束：函数内部的块都在缩进层，不会误配到 ``\n}``。
    """
    assert signature in src, f"search.js 找不到函数签名：{signature!r}"
    body = src.split(signature, 1)[1]
    end = body.find("\n}")
    return body if end == -1 else body[:end]


def _main_tag(idx: str, view_id: str) -> Optional[str]:
    m = re.search(rf'<main\b[^>]*\bid="{re.escape(view_id)}"[^>]*>', idx)
    return m.group(0) if m else None


# ── index.html：视图壳 / 导航 / 分组容器 / 范围控件 ───────────────────────────


def test_view_search_shell_exists_with_view_class():
    tag = _main_tag(INDEX, "view-search")
    assert tag, 'index.html 必须有 <main id="view-search"> 壳'
    assert "view" in tag.split("class=")[1], 'view-search 的 class 必须含 "view"（show() 按 .view 点亮）'


def test_top_nav_has_search_entry():
    assert 'id="nav-btn-search"' in INDEX, "顶栏缺少 nav-btn-search 入口"
    m = re.search(r'<button\b[^>]*id="nav-btn-search"[^>]*>', INDEX)
    assert m, "nav-btn-search 必须是 <button>"
    assert "show('search')" in m.group(0), "nav-btn-search 的 onclick 必须含 show('search')"


def test_mobile_dock_has_search_entry():
    """<=1024px 时 #nav .nav-links 被 display:none（由底部 dock 替代），
    dock 里必须有 mob-btn-search，否则本功能在手机/Android 上不可达。
    show(view) 按 mob-btn-<view> 惯例点亮，无需改 JS。"""
    m = re.search(r'<button\b[^>]*id="mob-btn-search"[^>]*>', INDEX)
    assert m, "移动 dock 缺少 mob-btn-search 入口（<=1024px 时 nav-links 隐藏 → 检索不可达）"
    assert "show('search')" in m.group(0), "mob-btn-search 的 onclick 必须含 show('search')"


def test_search_view_has_input_and_four_group_containers():
    assert 'id="search-input"' in INDEX, "缺少检索输入框 #search-input"
    for kind in ("vocab", "example", "colloc", "corpus"):
        assert f'id="search-group-{kind}"' in INDEX, f"缺少分组结果容器 #search-group-{kind}"
    assert 'id="search-empty"' in INDEX, "缺少空态容器 #search-empty"
    assert 'id="search-status"' in INDEX, "缺少状态条容器 #search-status"


def test_scope_control_has_all_five_values():
    assert 'id="search-scope-bar"' in INDEX, "缺少范围分段控件 #search-scope-bar"
    for scope in ("all", "vocab", "example", "colloc", "corpus"):
        assert f'data-scope="{scope}"' in INDEX, f"分段控件缺少 data-scope={scope!r}"


# ── search.js：存在性 + 端点 + 防抖 + 渲染 + 降级 ─────────────────────────────


def test_search_module_exists():
    assert _SEARCH_PATH.exists(), "static/js/search.js 必须存在"


def test_search_calls_api_endpoint_with_scope_and_limit():
    assert "/api/search" in SEARCH, "search.js 必须请求 /api/search"
    # 绑到**请求构造点**（URLSearchParams），而非裸子串：丢掉 limit 传参、
    # 改 _LIMIT 常量名/取值、或对 scope 换形状，任一都会让断言变红。
    assert "URLSearchParams({" in SEARCH, "search.js 必须用 URLSearchParams 构造查询串"
    assert "scope: _s.scope" in SEARCH, "查询串必须以 scope: _s.scope 请求（绑构造）"
    assert "limit: String(_LIMIT)" in SEARCH, "查询串必须以 limit: String(_LIMIT) 请求（绑构造）"
    assert "_LIMIT = 20" in SEARCH, "单组上限常量 _LIMIT 必须为 20（spec §3.3 默认值）"


def test_search_uses_300ms_debounce():
    assert "debounce" in SEARCH, "search.js 必须实现防抖逻辑"
    assert "_DEBOUNCE_MS = 300" in SEARCH, "防抖时长必须为 300ms（spec §2）"


def test_search_renders_four_groups_and_exports():
    assert "export function initSearch" in SEARCH, "search.js 必须导出 initSearch"
    assert "export function renderSearchGroups" in SEARCH, "search.js 必须导出 renderSearchGroups"
    for kind in ("vocab", "example", "colloc", "corpus"):
        assert f'"{kind}"' in SEARCH, f"search.js 未处理分组 {kind!r}"
    assert "_GROUP_ORDER" in SEARCH, "四组渲染应走固定序常量表"


def test_search_has_empty_state_and_truncated_notice():
    assert "search-empty" in SEARCH, "search.js 必须能填空态"
    assert "未找到" in SEARCH or "至少 2 个字符" in SEARCH, "search.js 缺少空态文案"
    assert "truncated" in SEARCH and "结果已截断" in SEARCH, "search.js 必须提示 truncated"


def test_search_degrades_without_local_service():
    assert "catch" in SEARCH, "search.js 必须有 try/catch 兜底（端点缺失/file:// 直开）"
    assert "检索不可用" in SEARCH or "需本地服务" in SEARCH, "端点缺失时必须提示降级文案（不白屏）"


def test_corpus_snippet_empty_falls_back_to_title_only():
    assert "snippet" in SEARCH, "search.js 必须消费 corpus payload.snippet"
    assert "仅标题匹配" in SEARCH, "snippet 为空（title-only 命中）时必须给「仅标题匹配」提示"


def test_search_reuses_existing_audio_and_deck_entries():
    assert "playGermanAudio" in SEARCH, "🔊 发音必须复用 player.js 的 playGermanAudio"
    assert "saveA1WordToDeck" in SEARCH, "「+ 加入 FSRS 盒」必须复用既有进卡函数（勿自造写库逻辑）"
    assert "openReader" in SEARCH, "语料跳转文章必须复用 reader.js 的 openReader"


# ── XSS 守卫：高亮必须先 esc() 再包 <mark> ────────────────────────────────────


def test_highlight_escapes_before_wrapping_mark():
    body = _js_fn(SEARCH, "function _highlight(")
    # 关键：必须对**原文参数 text** 走 esc()（而非仅对 needle），否则查询/字段含
    # <script> 时原样进 innerHTML 注入。断言 "esc(text" 使「删掉这层转义」直接变红。
    assert "esc(text" in body, "高亮函数必须先对原文 esc(text)（否则含 <script> 会注入）"
    assert "<mark>" in body, "高亮必须用 <mark> 包裹命中"
    assert body.index("esc(text") < body.index("<mark>"), "esc(text) 必须发生在 <mark> 包裹之前"


def test_highlight_is_used_across_all_renderers():
    # 逐渲染器切片断言（四个渲染器各自必须调用 _highlight）：任一渲染器去掉
    # _highlight() 调用即变红。旧的全局 SEARCH.count("_highlight(") >= 5
    # 阈值过宽（实际 11），删掉两个渲染器的高亮仍绿，故弃用。
    for fn in ("_vocabHtml(", "_exampleHtml(", "_collocHtml(", "_corpusHtml("):
        body = _js_fn(SEARCH, "function " + fn)
        assert "_highlight(" in body, f"渲染器 {fn} 必须经过 _highlight() 转义路径"


# ── main.js：import + 视图注册 + 命名空间挂载 ──────────────────────────────────


def test_main_imports_search_module():
    assert "./search.js" in MAIN_JS, "main.js 必须 import ./search.js"


def test_main_registers_search_view_route():
    show_body = MAIN_JS.split("export function show(")[1].split("\nexport ")[0]
    assert 'view === "search"' in show_body, "show() 必须路由 search 视图"
    assert "Search.initSearch" in show_body, "进入 search 视图必须调 Search.initSearch()"


def test_main_mounts_search_namespace_on_window():
    assert "Object.assign(window, {" in MAIN_JS, "main.js 必须在 window 上挂载模块命名空间"
    block = MAIN_JS.split("Object.assign(window, {", 1)[1]
    assert re.search(r"\bSearch\b", block), "window 挂载块必须含 Search 命名空间（供 inline onclick 调用）"


# ── 行为级动态探针 tools/wb_search_probe.mjs（Task 5） ─────────────────────────
#
# 上面的静态断言只能证明「源码里写着 esc( / <mark> / 四个分组」。探针把 core.js 的
# esc 与 search.js 的 _highlight / 四个渲染器 / renderSearchGroups 按括号配对**真实
# 切片**丢进 node:vm 真跑（探针里没有一份重抄的实现）：
#   ① 高亮转义安全（含 <script> 的字段不注入 innerHTML）；② 四组渲染；③ 空态。
# 这里驱动它、断言 fail==0 且三个关键场景名都在（防场景被删仍全绿）。

_PROBE_SCENARIOS = ("xss_highlight_escape", "four_groups_render", "empty_state")


def _run_search_probe() -> dict:
    """跑 tools/wb_search_probe.mjs --json，返回解析后的 dict（含 fail/total/cases）。"""
    import json
    import shutil
    import subprocess

    import pytest

    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    probe = ROOT / "tools" / "wb_search_probe.mjs"
    assert probe.exists(), "缺少 tools/wb_search_probe.mjs 动态探针"
    res = subprocess.run(
        ["node", str(probe), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, "探针执行失败：\n%s\n%s" % (res.stdout, res.stderr)
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(
            "探针 --json 输出不是合法 JSON：%s\nstdout 片段：%r\nstderr 片段：%r"
            % (e, res.stdout[:400], res.stderr[:400])
        )


def test_search_ui_behaves_under_node():
    """动态探针：真实 esc/_highlight/渲染器在 node:vm 里跑三个行为场景。"""
    out = _run_search_probe()
    assert out["fail"] == 0, "探针有失败场景：%s" % [c for c in out["cases"] if not c["ok"]]
    assert out["total"] >= 3, "探针场景数必须 ≥3，实际 %s" % out["total"]
    names = {c["name"] for c in out["cases"]}
    for key in _PROBE_SCENARIOS:
        assert key in names, "关键场景 %r 缺失（被删仍全绿风险）；实际场景：%s" % (key, sorted(names))
