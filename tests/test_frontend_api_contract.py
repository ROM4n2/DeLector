# -*- coding: utf-8 -*-
"""`tools/check_frontend_api_contract.py` 纯逻辑单元测试（ADR-0021 替代投资#3）。

范围（只测**不 import delector.server** 的纯函数）
------------------------------------------------
URL 表达式归一化（模板插值 / `+` 拼接 / 紧贴的查询尾）、分类排除（外部 URL / 静态资源 /
非 API）、路由参数占位匹配、以及「未注册端点 ⇒ find_unknown 非空」的判定核心。

为什么单测**不** import 真实 app：路由表由 CI 的**阻塞步**直接跑
`python tools/check_frontend_api_contract.py` 校验（那里 import 了 delector.server，需
spaCy 环境）；此处只钉与路由表无关的纯函数，保持秒级、可移植、确定性。

断言纪律（防恒真 / 防假绿）
--------------------------
每条断言都能被「改坏实现」打红（见末尾 MUTATION 表）。特别地，直接以**当前仓库**的
真实写法做回归：listen-lab.js 的 `` `/api/listen/materials${levelParam}` `` 曾因插值被
误当成路径段而假报未知端点 —— 这条真实回归被钉死为一条用例。
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNDER_TEST = _REPO_ROOT / "tools" / "check_frontend_api_contract.py"


def _load_under_test() -> Any:
    """按路径加载被守卫脚本（`tools/` 不是 package，不能直接 import）。

    MUST 先注册进 sys.modules：被加载模块用了 `@dataclass`，而 dataclasses 内部经
    `sys.modules[cls.__module__]` 解析类型注解 —— 未注册会让 `cls.__module__` 查不到
    ⇒ AttributeError: 'NoneType' object has no attribute '__dict__'。
    """
    name = "frontend_api_contract_under_test"
    spec = importlib.util.spec_from_file_location(name, _UNDER_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fc = _load_under_test()


# ── URL 表达式归一化 ─────────────────────────────────────────────────────────
def test_template_interpolation_becomes_placeholder() -> None:
    """模板字面量插值 ⇒ 路径段占位 `{}`。"""
    assert fc.normalize_url_expr("`/api/a1/lesen/set/${setId}`") == "/api/a1/lesen/set/{}"


def test_template_multiple_interpolations() -> None:
    """多个插值各自折叠为独立路径段。"""
    assert fc.normalize_url_expr("`/api/cards/${type}/${id}/review`") == "/api/cards/{}/{}/review"


def test_concat_string_plus_variable() -> None:
    """`"/api/articles/" + id` ⇒ `/api/articles/{}`（变量段在路径段位置折叠）。"""
    assert fc.normalize_url_expr('"/api/articles/" + id') == "/api/articles/{}"


def test_glued_interpolation_is_query_tail_not_segment() -> None:
    """**真实回归**（listen-lab.js）：紧贴路径的插值是查询尾，不当路径段。

    `levelParam` 是 `""` 或 `"?level=…"` 的查询串构造器，粘在 `/api/listen/materials` 后；
    若折叠为 `{}` 会得到 `/api/listen/materials{}` 而假报未知端点。
    """
    assert fc.normalize_url_expr("`/api/listen/materials${levelParam}`") == "/api/listen/materials"


def test_pure_variable_is_dynamic() -> None:
    """纯变量首参无字面量可求值 ⇒ None（记为动态，不判失败）。"""
    assert fc.normalize_url_expr("src") is None
    assert fc.normalize_url_expr("PULL_ENDPOINT") is None


def test_top_level_ternary_is_dynamic() -> None:
    """顶层三元（跨主机切换）无法静态求值 ⇒ None（硬判会假阳性）。"""
    expr = 'pair ? "http://" + pair.host + "/api/wb/state" : "/api/wb/state"'
    assert fc.normalize_url_expr(expr) is None


# ── 分类与排除 ───────────────────────────────────────────────────────────────
def test_classify_query_string_stripped() -> None:
    """查询串在匹配前剥离。"""
    kind, path = fc.classify_url("/api/cards/vocab?cefr=B1&scope=all&sources=official")
    assert kind == fc.KIND_CHECKABLE
    assert path == "/api/cards/vocab"


def test_classify_external_absolute_url_excluded() -> None:
    """外部绝对 URL（含协议相对 `//`）不是本机路由。"""
    for url in ("https://example.com/api/x", "http://host/api/x", "//cdn/api/x", "data:text/plain,x"):
        kind, path = fc.classify_url(url)
        assert kind == fc.KIND_EXTERNAL, url
        assert path is None


def test_classify_external_scheme_concat() -> None:
    """`"http://" + host + "/api/wb/state"` 归一化后带 scheme ⇒ 外部，排除。"""
    kind, _ = fc.classify_url("http://{}/api/wb/state")
    assert kind == fc.KIND_EXTERNAL


def test_classify_static_resource_excluded() -> None:
    """静态资源（/static/… 或资源扩展名）不是 API。"""
    for url in ("/static/js/app.js", "/static/app.css", "/favicon.ico", "/img/logo.png"):
        kind, path = fc.classify_url(url)
        assert kind == fc.KIND_STATIC, url
        assert path is None


def test_classify_non_api_rooted_path() -> None:
    """非 /api/ 的根路径不是 API 路由（如 openapi 文档）。"""
    kind, path = fc.classify_url("/openapi.json")
    assert kind == fc.KIND_NON_API
    assert path is None


def test_classify_api_root_is_checkable() -> None:
    """`/api/…` 才是可判定面。"""
    kind, path = fc.classify_url("/api/articles")
    assert kind == fc.KIND_CHECKABLE
    assert path == "/api/articles"


# ── 路由参数占位与匹配 ───────────────────────────────────────────────────────
def test_route_param_converter_normalized() -> None:
    """`{text_id:int}` 这类 FastAPI 转换器占位一并归一为 `{}`。"""
    assert fc.normalize_route_pattern("/api/encounter/texts/{text_id:int}") == "/api/encounter/texts/{}"
    assert fc.normalize_route_pattern("/api/articles/{article_id}") == "/api/articles/{}"


def test_paths_match_with_param_placeholder() -> None:
    """前端 `{}` 占位与路由参数占位互配。"""
    assert fc.paths_match("/api/articles/{}", "/api/articles/{article_id}")
    assert fc.paths_match("/api/cards/{}/{}/review", "/api/cards/{card_type}/{card_id}/review")
    assert fc.paths_match("/api/encounter/texts/{}", "/api/encounter/texts/{text_id:int}")


def test_paths_match_rejects_segment_count_and_literal_mismatch() -> None:
    """段数不同 / 字面量不同 => 不匹配（防恒真）。"""
    assert not fc.paths_match("/api/cards", "/api/cards/due")
    assert not fc.paths_match("/api/cards/counts", "/api/cards/due")
    assert not fc.paths_match("/api/articles/{}", "/api/articles/{}/notes")


# ── 站点扫描（识别真实写法）──────────────────────────────────────────────────
def test_scan_detects_real_call_forms() -> None:
    """识别实测存在的写法：api / fetch / doFetch / location.href / xhr.open。"""
    source = (
        'const a = await api("/api/articles");\n'
        'const b = await fetch("/api/cards/due");\n'
        'const c = await doFetch("/api/update/check");\n'
        'window.location.href = `/api/backup/download/${token}`;\n'
        'xhr.open("GET", "/api/settings");\n'
    )
    calls = fc.scan_source(source, "fixture.js")
    callees = {c.callee for c in calls}
    assert {"api", "fetch", "doFetch", "location.href", ".open"} <= callees
    urls = {c.url for c in calls}
    assert "/api/articles" in urls
    assert "/api/cards/due" in urls
    assert "/api/update/check" in urls
    assert "/api/backup/download/{}" in urls
    assert "/api/settings" in urls


def test_scan_ignores_empty_call_in_comment() -> None:
    """注释里的 `fetch()/api()` 空实参站点被丢弃（降噪，不产生动态站点）。"""
    source = "// 拼进 fetch()/api() 直连桌面\n"
    assert fc.scan_source(source, "fixture.js") == []


def test_scan_records_dynamic_site() -> None:
    """动态首参记为 kind=dynamic（INFO，不判失败）。"""
    calls = fc.scan_source('api(PULL_ENDPOINT, { method: "POST" });\n', "fixture.js")
    assert len(calls) == 1
    assert calls[0].kind == fc.KIND_DYNAMIC
    assert calls[0].url is None


# ── 判定核心：未知端点必须被判失败 ───────────────────────────────────────────
_PATTERNS = ["/api/articles", "/api/articles/{}", "/api/cards/due", "/api/settings"]


def test_find_unknown_flags_missing_endpoint() -> None:
    """**变异自证核心**：调了未注册端点 ⇒ find_unknown 非空（⇒ 工具非零退出）。"""
    source = 'const r = await api("/api/definitely/not/registered");\n'
    calls = fc.scan_source(source, "fixture.js")
    unknown = fc.find_unknown(calls, _PATTERNS)
    assert len(unknown) == 1, "未知端点未被判失败：路由契约闸失效"
    assert unknown[0][0].url == "/api/definitely/not/registered"
    assert unknown[0][1], "失败信息缺最近似路由（无法定位）"


def test_find_unknown_passes_known_endpoint() -> None:
    """已注册端点 ⇒ 不判失败（防恒真：不能什么都不匹配都算失败）。"""
    source = 'api("/api/articles");\napi(`/api/articles/${id}`);\napi("/api/cards/due");\n'
    calls = fc.scan_source(source, "fixture.js")
    assert fc.find_unknown(calls, _PATTERNS) == []


def test_find_unknown_ignores_dynamic_and_excluded() -> None:
    """动态/外部/静态/非 API 站点都不进入判定面。"""
    source = (
        "api(SOME_VAR);\n"
        'fetch("https://example.com/api/x");\n'
        'api("/static/js/app.js");\n'
        'api("/openapi.json");\n'
    )
    calls = fc.scan_source(source, "fixture.js")
    assert fc.find_unknown(calls, _PATTERNS) == []


# ── MUTATION 对照表（改坏实现哪一处 ⇒ 哪条用例转红）────────────────────────────
# 1. normalize_url_expr 去掉顶层三元短路（`?` 检查）    ⇒ test_top_level_ternary_is_dynamic
# 2. _collapse 把紧贴插值也折叠为 `{}`（去掉截断分支）  ⇒ test_glued_interpolation_is_query_tail_not_segment
# 3. classify_url 不剥离查询串                          ⇒ test_classify_query_string_stripped
# 4. classify_url 去掉外部 URL 判定                      ⇒ test_classify_external_* （两条）
# 5. classify_url 去掉静态资源判定                       ⇒ test_classify_static_resource_excluded
# 6. paths_match 恒真（return True）                    ⇒ test_paths_match_rejects_segment_count_and_literal_mismatch
# 7. find_unknown 恒返回 []（吞掉失败）                 ⇒ test_find_unknown_flags_missing_endpoint
# 8. _iter_sites 不认识 doFetch/location.href/.open      ⇒ test_scan_detects_real_call_forms
