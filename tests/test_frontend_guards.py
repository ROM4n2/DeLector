# -*- coding: utf-8 -*-
r"""P0-3 / P0-4 前端守卫：openReader 失败可见化 + 评分重入闸 + 首屏惰性（T10）。

两层判据：
  * 静态层：按红线 13「锚点 + 括号配平」切真源码后的结构判据（含越界切片自证）。
    静态层已红 ⇒ MUST NOT 再跑 node:vm（test_static_layer_red_short_circuits_before_node_vm）。
  * 行为层：tools/frontend_guards_probe.mjs 切真源码进 node:vm 真跑；判据是运行时事实
    （加载占位 / 错误态 / 节流 / 只发一次 POST / 按钮 disabled / iframe 幂等），
    不再是字符串存在断言。沙箱只放真源码切片 + 环境桩，不放手写实现（红线 13）。
"""

import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from _pytest.outcomes import Exit, Skipped
from probe_runner import assert_probe_clean, assert_scenarios_present, run_json_probe, scenario_keys

ROOT = Path(__file__).resolve().parent.parent
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
READER = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

_WORKBENCH_ROUTE = "/german/workbench.html"
PROBE_NAME = "frontend_guards_probe"
_PAIRS = {"(": ")", "{": "}", "[": "]"}


def _iter_brackets(source: str, start: int = 0):
    """产出 (下标, 括号字符)，只取代码态；跳过字符串/注释/模板，模板插值计入配平。

    与 tests/wb_source.py::_iter_braces 同口径，额外 yield 圆/方括号以便配平参数表。
    已知限制（同 wb_source）：不识别正则字面量里的未转义括号。
    """
    modes = ["code"]
    interp_depths: list[int] = []
    depth = 0
    i, n = start, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        mode = modes[-1]
        if mode == "code":
            if ch == "/" and nxt == "/":
                modes.append("line")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                modes.append("block")
                i += 2
                continue
            if ch in ("'", '"'):
                modes.append("str" + ch)
                i += 1
                continue
            if ch == "`":
                modes.append("tpl")
                i += 1
                continue
            if ch in _PAIRS:
                yield i, ch
                depth += 1
                i += 1
                continue
            if ch in ")}]":
                yield i, ch
                depth -= 1
                if interp_depths and depth == interp_depths[-1]:
                    interp_depths.pop()
                    modes.pop()
                i += 1
                continue
            i += 1
            continue
        if mode == "line":
            if ch == "\n":
                modes.pop()
            i += 1
            continue
        if mode == "block":
            if ch == "*" and nxt == "/":
                modes.pop()
                i += 2
                continue
            i += 1
            continue
        if mode == "tpl":
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                modes.pop()
                i += 1
                continue
            if ch == "$" and nxt == "{":
                interp_depths.append(depth)
                yield i + 1, "{"
                depth += 1
                modes.append("code")
                i += 2
                continue
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == mode[-1]:
            modes.pop()
        i += 1


def _matching_close(source: str, open_idx: int, label: str) -> int:
    """从 open_idx（必须是开括号）配平到配对闭括号；任一步失败具名报错，不返回短切片。"""
    opener = source[open_idx]
    assert opener in _PAIRS, f"{label}: 下标 {open_idx} 不是开括号（红线 13 锚点失败）"
    stack = [opener]
    for idx, ch in _iter_brackets(source, open_idx):
        if idx == open_idx:
            continue
        if ch in _PAIRS:
            stack.append(ch)
        else:
            expected = _PAIRS[stack[-1]]
            assert ch == expected, f"{label}: 下标 {idx} 括号不配对（期望 {expected}，得到 {ch}）"
            stack.pop()
            if not stack:
                return idx
    raise AssertionError(f"{label}: 从下标 {open_idx} 起找不到配对闭括号（MUST NOT 返回短切片）")


def _extract_function(source: str, signature: str) -> str:
    """红线 13：配平参数表到 `)`，要求下一个非空白字符是函数体 `{`，再配平到 `}`。

    旧实现从签名切到下一个 `\\nexport ` ⇒ 把约 200 行邻函数（`_openReaderBody` 等）切进
    body，字符串断言因此恒真。解构参数 `f({a}={})` 不会让切片停在参数的花括号上。
    """
    start = source.find(signature)
    assert start != -1, f"找不到函数签名 {signature!r}（前提变了，需重写守卫）"
    paren = source.find("(", start + len(signature) - 1)
    assert paren != -1, f"{signature!r} 之后找不到参数表 '('（红线 13 锚点失败）"
    close_paren = _matching_close(source, paren, signature)
    j = close_paren + 1
    while j < len(source) and source[j].isspace():
        j += 1
    assert j < len(source) and source[j] == "{", (
        f"{signature!r} 的参数表 `)` 之后下一个非空白字符不是函数体 '{{'"
        f"（实际 {source[j:j + 24]!r}）：MUST NOT 返回签名/短切片（红线 13）"
    )
    end = _matching_close(source, j, signature)
    return source[start : end + 1]


# ── 静态层：纯函数，可用构造源码喂阴性 / 变异自证 ───────────────────────────
def _open_reader_violations(body: str) -> list[str]:
    p = []
    if "try {" not in body:
        p.append("openReader 缺 try（曾全程静默失败）")
    if "catch (" not in body:
        p.append("openReader 缺 catch")
    if "notify(" not in body and "_renderReaderError(" not in body:
        p.append("失败不可见（既无 notify 也无正文错误态）")
    if "finally" not in body:
        p.append("加载态未在 finally 复原")
    if "载入中" not in body:
        p.append("缺加载占位标题")
    return p


def _submit_review_violations(body: str) -> list[str]:
    p = []
    if "if (cardState.deck.reviewInFlight) return" not in body:
        p.append("入口缺重入闸")
    if "cardState.deck.reviewInFlight = true" not in body or "cardState.deck.reviewInFlight = false" not in body:
        p.append("飞行标志未成对置位/复位")
    if "disabled = true" not in body:
        p.append("飞行期间评分按钮未 disabled")
    if "finally" not in body:
        p.append("按钮恢复未放 finally")
    return p


def _core_guard_violations(core: str) -> list[str]:
    p = []
    if "unhandledrejection" not in core or "addEventListener" not in core:
        p.append("core.js 缺 unhandledrejection 全局兜底")
    if "window.onerror" not in core:
        p.append("core.js 缺 window.onerror 兜底")
    if "notify(" not in core:
        p.append("全局兜底未走 notify")
    if "Date.now()" not in core:
        p.append("全局兜底缺节流")
    return p


def _german_view_block() -> str:
    return INDEX.split('id="view-german"')[1].split("</main>")[0]


def _iframe_violations(block: str) -> list[str]:
    p = []
    if f'data-src="{_WORKBENCH_ROUTE}"' not in block:
        p.append("workbench iframe 缺 data-src 惰性路由")
    if re.search(r"(?<![-\w])src\s*=", block) is not None:
        p.append("workbench iframe 带静态 src=（首屏即加载 383KB）")
    return p


def _main_wiring_violations(main: str) -> list[str]:
    p = []
    helper = _extract_function(main, "function ensureGermanWorkbench(")
    for needle in (
        'getElementById("german-workbench-frame")',
        'getAttribute("data-src")',
        'setAttribute("src"',
        'getAttribute("src")',
    ):
        if needle not in helper:
            p.append(f"ensureGermanWorkbench 缺 {needle}")
    if "ensureGermanWorkbench()" not in _extract_function(main, "export function show("):
        p.append("show('german') 未接线 ensureGermanWorkbench()")
    return p


def _static_layer_violations() -> list[str]:
    return (
        _open_reader_violations(_extract_function(READER, "export async function openReader("))
        + _submit_review_violations(_extract_function(CARDS, "export async function submitCardReview("))
        + _core_guard_violations(CORE)
        + _iframe_violations(_german_view_block())
        + _main_wiring_violations(MAIN)
    )


def _assert_static_layer_clean() -> None:
    problems = _static_layer_violations()
    assert not problems, "前端守卫静态层已红（MUST NOT 再跑 node:vm）：\n" + "\n".join(problems)


def _run_probe() -> dict:
    if not shutil.which("node"):
        if os.environ.get("CI"):
            pytest.exit(
                "CI 环境缺少必需的 node 运行时；前端守卫行为探针不能以 skip 静默跳过",
                returncode=1,
            )
        pytest.skip("未安装 node：本守卫需要 node 真跑行为探针")
    return run_json_probe(PROBE_NAME)


def _guarded_probe_run() -> dict:
    _assert_static_layer_clean()  # 静态层已红 ⇒ 下一行不执行（不跑 node:vm）
    return _run_probe()


_PROBE_SCENARIOS = (
    "open_reader_shows_loading_placeholder",
    "open_reader_failure_renders_visible_error_and_restores_title",
    "submit_review_reentry_gate_blocks_double_post",
    "submit_review_buttons_disabled_during_flight_and_restored",
    "global_guard_registers_both_listeners",
    "global_guard_throttles_duplicate_errors",
    "workbench_iframe_has_no_static_src",
    "ensure_workbench_is_lazy_and_idempotent",
    "slice_destructured_params_not_short",
    "slice_rejects_non_brace_after_paren",
    "mutation_open_reader_placeholder_removed_is_caught",
    "mutation_open_reader_error_state_removed_is_caught",
    "mutation_submit_review_gate_removed_is_caught",
    "mutation_global_guard_throttle_removed_is_caught",
    "mutation_iframe_static_src_added_is_caught",
)


# ── 阳性 ────────────────────────────────────────────────────────────────────
def test_static_layer_clean_on_real_sources():
    _assert_static_layer_clean()


def test_frontend_guards_probe_reports_no_failures():
    out = _guarded_probe_run()
    assert_probe_clean(PROBE_NAME, out)
    assert out["total"] >= 15, f"探针场景数异常偏少（{out['total']}）"
    assert len(scenario_keys(out)) == out["total"]


def test_frontend_guards_probe_key_scenarios_present():
    out = _guarded_probe_run()
    assert_scenarios_present(PROBE_NAME, out, _PROBE_SCENARIOS)


def test_missing_node_is_fatal_in_ci(monkeypatch):
    """阴性：CI 缺 node ⇒ pytest.exit(returncode=1)，不是静默 skip。"""
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(Exit) as exc:
        _run_probe()
    assert exc.value.returncode == 1


def test_missing_node_skips_only_locally(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(Skipped):
        _run_probe()


# ── 阴性：删掉保护物 ⇒ 守卫必红 ─────────────────────────────────────────────
def test_open_reader_violations_catch_removed_protection():
    assert _open_reader_violations("export async function openReader(id) { return; }"), (
        "try/catch/notify/finally/占位被删光后判据仍全绿 ⇒ 死测"
    )


def test_submit_review_violations_catch_removed_protection():
    assert _submit_review_violations(
        "export async function submitCardReview(t,i,g) { await reviewCard(t,i,{}); }"
    ), "重入闸/disabled/finally 被删光后判据仍全绿 ⇒ 死测"


def test_iframe_violations_catch_static_src_readded():
    bad = '<iframe id="german-workbench-frame" src="/german/workbench.html" data-src="/german/workbench.html"></iframe>'
    assert _iframe_violations(bad), "静态 src 回潮后判据仍全绿 ⇒ 死测"


def test_rating_bar_buttons_still_rendered_with_submit_handler():
    """调用点 MUST 在：定义处那个 `submitCardReview(` 会让裸子串断言恒真（旧死测）。"""
    occurrences = list(re.finditer(r"\bsubmitCardReview\s*\(", CARDS))
    assert len(occurrences) >= 2, (
        "cards.js 里除函数定义外没有 submitCardReview( 调用点（评分按钮接线被删）；"
        "旧判据只查子串，定义本身就能让它恒绿"
    )


# ── 变异自证 ────────────────────────────────────────────────────────────────
def test_static_layer_red_short_circuits_before_node_vm(monkeypatch):
    """静态层红 ⇒ MUST NOT 调 _run_probe（即不跑 node:vm）。"""
    broken = READER.replace(
        "  try {\n    for (let attempt = 1; ; attempt += 1) {",
        "  for (let attempt = 1; ; attempt += 1) {",
    )
    assert broken != READER, "注入式变异锚点应恰好命中 1 处"
    monkeypatch.setattr(sys.modules[__name__], "READER", broken)
    monkeypatch.setattr(
        sys.modules[__name__], "_run_probe",
        lambda: pytest.fail("静态层已红却仍跑了 node:vm"),
    )
    with pytest.raises(AssertionError, match="静态层已红"):
        _guarded_probe_run()


def test_extract_function_balances_to_closing_brace():
    """阳性：真源码切到配对 `}`，不再把约 200 行邻函数切进 body。"""
    body = _extract_function(READER, "export async function openReader(")
    assert body.rstrip().endswith("}")
    assert "async function _openReaderBody(" not in body, "越界切片（旧实现死测根因）"
    assert "try {" in body and "finally" in body


def test_extract_function_does_not_bleed_into_neighbour():
    """阴性：旧 `\\nexport ` 边界会把邻函数切进来。"""
    src = "function f() { return 1; }\nfunction g() { return 2; }\n"
    assert "return 2" not in _extract_function(src, "function f(")


def test_extract_function_handles_destructured_params_and_fails_loud():
    """变异自证：`f({a}={})` 不短切；`)` 后非 `{` 具名报错；字符串/注释里的 `}` 不误配平。"""
    src = "function f({a}={}) { return a; }\nfunction g() { return 2; }\n"
    body = _extract_function(src, "function f(")
    assert "return a;" in body and "return 2" not in body
    with pytest.raises(AssertionError, match="不是函数体"):
        _extract_function("function h() 42;", "function h(")
    trap = 'function t() { const s = "}"; /* } */ const tail = 1; }\n'
    assert "const tail = 1;" in _extract_function(trap, "function t(")


# ── 其余既有契约（改用修好的 _extract_function）─────────────────────────────
def test_modal_close_buttons_have_accessible_name():
    """ADR-0029 I1：每个 drawer-close 按钮必须有可访问名（title / ✕ 字形不计入）。"""
    open_tag_re = re.compile(
        r'<button\b[^>]*\bclass\s*=\s*"[^"]*\bdrawer-close\b[^"]*"[^>]*>', re.DOTALL
    )
    hits: list[tuple[str, str]] = []
    for path in sorted((ROOT / "static" / "modals").glob("*.html")):
        source = path.read_text(encoding="utf-8")
        hits.extend((path.name, m.group(0)) for m in open_tag_re.finditer(source))
    missing = [
        (name, tag) for name, tag in hits
        if not re.search(r"\baria-label\s*=", tag) and not re.search(r"\baria-labelledby\s*=", tag)
    ]
    assert not missing, "关闭键缺可访问名（title / ✕ 字形不计入）：\n" + "\n".join(
        f"{name}: {tag}" for name, tag in missing
    )
    assert len(hits) >= 6, f"只匹配到 {len(hits)} 个 drawer-close 按钮，正则疑似失效"


def test_reader_state_template_uses_only_declared_vars():
    """v5.23.2：`${名字}` 纯标识符必须在本函数内声明过（运行时 ReferenceError）。"""
    body = _extract_function(READER, "function _readerStateHtml(")
    declared = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", body))
    declared |= set(re.findall(r"function\s+\w+\s*\(([^)]*)\)", body))
    declared |= {"kind", "title", "hint", "opts", "options"}
    used = set(re.findall(r"\$\{\s*([A-Za-z_$][\w$]*)\s*\}", body))
    missing = sorted(used - declared)
    assert not missing, (
        "reader 状态模板引用了未声明的变量（运行时 ReferenceError，阅读页打不开）："
        + ", ".join(missing)
    )
