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
    "satz_lab_network_failure_is_booting_not_raw_error",
    "satz_lab_http_error_keeps_status_detail",
    "satz_lab_undefined_error_treated_as_booting",
    "notify_server_ready_retries_pending_satz_lab",
    "notify_server_ready_ignores_idle_satz_lab",
    "mutation_satz_lab_network_failure_classification_removed_is_caught",
    "mutation_satz_lab_retry_hook_removed_from_notify_is_caught",
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
    # 删除全部 `try {`：T13 在同一函数里新增了退避等待的 try，只删旧锚点那一处
    # 已经不会让静态层变红（合并后实测），故按语义删光 try 关键字。
    broken = READER.replace("try {", "")
    assert broken != READER, "注入式变异应至少改动一处 try {"
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


# ── T13：阅读页状态机残留（行为探针：node 真跑 + 内建变异自证）─────────────
import json  # noqa: E402
import subprocess  # noqa: E402

from probe_runner import require_node  # noqa: E402

_T13_NODE_PROBE = r"""
const fs = await import('node:fs');
const vm = await import('node:vm');
const ROOT = process.cwd();
const READER = fs.readFileSync(ROOT + '/static/js/reader.js', 'utf8');
const STORE = fs.readFileSync(ROOT + '/static/js/article-store.js', 'utf8');
const cases = [];
const check = (name, ok, detail) => cases.push({ name, ok: !!ok, detail: ok ? '' : String(detail ?? '') });
const delays = JSON.parse(STORE.match(/const RETRY_DELAYS_MS = (\[[^\]]*\]);/)[1]);
const budget = Number(STORE.match(/const RETRY_BUDGET_MS = (\d+);/)[1]);

function strip(src) {
  const out = []; let inImport = false;
  for (const line of src.split('\n')) {
    if (!inImport && /^import\b/.test(line)) { inImport = !/;\s*$/.test(line); continue; }
    if (inImport) { if (/;\s*$/.test(line)) inImport = false; continue; }
    out.push(line);
  }
  return out.join('\n')
    .replace(/^export\s*\{[^}]*\};?/gm, '')
    .replace(/^export\s+/gm, '')
    .replace(/^['"]use strict['"];\s*$/gm, '');
}
function el(id) {
  const attrs = {};
  return {
    id, textContent: '', innerHTML: '', hidden: false, firstChild: null,
    style: { setProperty() {} },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, setAttribute(k, v) { attrs[k] = v; }, getAttribute(k) { return attrs[k]; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() {}, appendChild() {}, insertBefore() {}, remove() {},
    contains() { return false; }, getBoundingClientRect() { return { width: 0, height: 0 }; },
  };
}
function clock() {
  let now = 0, next = 0; const timers = new Map();
  return {
    now: () => now,
    setTimeout(fn, ms) { const id = ++next; timers.set(id, { at: now + ms, fn }); return id; },
    clearTimeout(id) { timers.delete(id); },
    pending: () => [...timers.keys()],
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, t]) => t.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); now = due[1].at; due[1].fn();
        await Promise.resolve(); await Promise.resolve();
      }
      now = Math.max(now, target); await Promise.resolve();
    },
  };
}
function sandbox(src) {
  const c = clock();
  const els = new Map();
  const doc = {
    getElementById(id) { if (!els.has(id)) els.set(id, el(id)); return els.get(id); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement: (tag) => el(tag), body: el('body'), documentElement: el('html'),
    addEventListener() {},
  };
  const listeners = {};
  const win = { show() {}, addEventListener(t, fn) { listeners[t] = fn; } };
  const ctx = {
    console: { warn() {}, log() {}, error() {} },
    Date: { now: () => c.now() }, setTimeout: c.setTimeout, clearTimeout: c.clearTimeout,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: doc, window: win, state: { currentArticle: null },
    esc: (s) => String(s ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;',
      '>': '&gt;', '"': '&quot;' })[ch]),
    jsAttr: (s) => JSON.stringify(String(s ?? '')), normalizeCefrPct: (p) => p || {},
    notify() {}, ShadowPlayer: { reset() {}, seekSentence() {} }, playGermanAudio() {},
    Companion: { celebrate() {} }, getActiveView: () => 'german',
    fetchArticle: () => Promise.reject(new Error('fetchArticle 未注入')),
    lookupVocab: () => Promise.resolve({}), lookupGrammar: () => Promise.resolve({}),
    saveVocabCard: () => Promise.resolve({}), saveGrammarCard: () => Promise.resolve({}),
    fetchCardCounts: () => Promise.resolve({ total: 0 }), fetchVocabLedger: () => Promise.resolve({}),
    fetchArticleNotes: () => Promise.resolve([]), saveArticleNote: () => Promise.resolve({}),
    removeNote: () => Promise.resolve({}), fetchNoteAssist: () => Promise.resolve({}),
    saveSyntaxStats: () => Promise.resolve({}), fetchSyntaxStats: () => Promise.resolve({}),
    vocabSaveOutcome: () => ({ created: true }), vocabSaveNotice: () => '',
    articleStore: { subscribe() {}, getState: () => ({ items: [] }), loadArticles() {},
      deleteArticle() {}, retryNow() {}, retryIfWaiting() {} },
    isRetryableError: (e) => !!e && (Number.isFinite(e.status) ? e.status >= 500 : e.name === 'TypeError'),
    RETRY_DELAYS_MS: delays, RETRY_BUDGET_MS: budget,
    CEFR_LEVELS: [], safeCefr: (s) => s || 'A1', safeTokens: (t) => t || [],
    renderMiniBar: () => '', renderFelderSpectrum: () => '', renderDetailedFelderGrid: () => '',
    renderClauseTreeNode: () => '', computeArticleSyntaxStats: () => ({}), renderRadarSvg: () => '',
  };
  vm.createContext(ctx);
  vm.runInContext(strip(src) + '\nglobalThis.__api = { openReader };', ctx, { filename: 'reader.js' });
  return { ctx, c, listeners, el: (id) => doc.getElementById(id) };
}
const flush = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
const ARTICLE = (id, extra = {}) => ({ id, title: 'Echter Titel ' + id, stats: {}, sentences: [], ...extra });
const err503 = () => Object.assign(new Error('nlp_loading'), { status: 503 });
const err404 = () => Object.assign(new Error('gone'), { status: 404 });

// ① 占位标题：404 不可重试 ⇒ _renderReaderError ⇒ finally
async function titleFailure(box, prev) {
  box.el('reader-title').textContent = prev;
  box.el('reader-content').innerHTML = '';
  box.ctx.fetchArticle = () => Promise.reject(err404());
  await box.ctx.__api.openReader(1);
  return { title: box.el('reader-title').textContent, html: box.el('reader-content').innerHTML };
}
{
  const r = await titleFailure(sandbox(READER), '⏳ 载入中…');
  check('P1-占位标题残留时失败态复原为空且错误正文保留',
    r.title === '' && r.html.includes('reader-state-error') && r.html.includes('这篇暂时打不开'),
    JSON.stringify(r));
  const n = await titleFailure(sandbox(READER), '上一篇真实标题');
  check('N1-上一篇真实标题仍被复原',
    n.title === '上一篇真实标题' && n.html.includes('reader-state-error'), JSON.stringify(n));
  const buggy = READER.replace(
    'const prevTitle = rawPrevTitle === READER_LOADING_TITLE ? "" : rawPrevTitle;',
    'const prevTitle = rawPrevTitle;');
  const mutated = buggy !== READER;
  const m = mutated ? await titleFailure(sandbox(buggy), '⏳ 载入中…') : null;
  check('M1-变异：去掉归一化后占位串被写回', mutated && !!m && m.title === '⏳ 载入中…',
    mutated ? JSON.stringify(m) : '变异锚点缺失（归一化修复不在源码里，探针失效）');
}

// ② 503 退避：假时钟 + 切换文章 / pagehide
async function backoff(box, { unload = false, switchArticle = false } = {}) {
  let calls = 0;
  box.ctx.fetchArticle = (id) => {
    calls += 1;
    return id === 2 ? Promise.resolve(ARTICLE(2)) : Promise.reject(err503());
  };
  void box.ctx.__api.openReader(1);
  await flush();
  const pendingAtBackoff = box.c.pending().length;
  const htmlAtBackoff = box.el('reader-content').innerHTML;
  if (unload && box.listeners.pagehide) box.listeners.pagehide();
  if (switchArticle) await box.ctx.__api.openReader(2);
  await flush();
  const pendingAfter = box.c.pending().length;
  await box.c.advance(delays[0] + 10);
  await flush();
  return { calls, pendingAtBackoff, pendingAfter, htmlAtBackoff,
           htmlFinal: box.el('reader-content').innerHTML };
}
{
  const sw = await backoff(sandbox(READER), { switchArticle: true });
  const un = await backoff(sandbox(READER), { unload: true });
  check('P2-切换与卸载均清除旧退避定时器且旧回调不复活',
    sw.pendingAfter === 0 && sw.calls === 2 && un.pendingAfter === 0 && un.calls === 1,
    JSON.stringify({ sw, un }));
  const n = await backoff(sandbox(READER));
  check('N2-未切换时退避照常触发且NLP提示保留',
    n.pendingAtBackoff === 1 && n.calls === 2 && n.htmlAtBackoff.includes('正在准备德语分词模型'),
    JSON.stringify(n));
  const buggy = READER.replace(
    'window.addEventListener("pagehide", _cancelReaderRetryTimer);', '');
  const mutated = buggy !== READER;
  const m = mutated ? await backoff(sandbox(buggy), { unload: true }) : null;
  check('M2-变异：去掉pagehide监听后旧回调复活',
    mutated && !!m && m.pendingAfter === 1 && m.calls === 2,
    mutated ? JSON.stringify(m) : '变异锚点缺失（pagehide 修复不在源码里，探针失效）');
}

// ③ processed_stale：真解析渲染后的 DOM 节点
async function renderArticle(box, extra) {
  let calls = 0;
  box.ctx.fetchArticle = () => { calls += 1; return Promise.resolve(ARTICLE(1, extra)); };
  await box.ctx.__api.openReader(1);
  await flush();
  return { html: box.el('reader-content').innerHTML, title: box.el('reader-title').textContent, calls };
}
const tipRe = /<div class="reader-state-tip" role="status">([^<]*)<\/div>/;
{
  const r = await renderArticle(sandbox(READER), { processed_stale: true, nlp_state: 'loading' });
  const m = r.html.match(tipRe);
  check('P3-processed_stale显示分词升级提示且不自动重拉',
    !!m && m[1].includes('分词正在升级') && r.calls === 1 && r.title === 'Echter Titel 1',
    JSON.stringify(r));
  const n = await renderArticle(sandbox(READER), {});
  check('N3-无processed_stale不显示提示', !tipRe.test(n.html) && n.calls === 1, JSON.stringify(n));
  const buggy = READER.replace('const staleTip = a.processed_stale',
    'const staleTip = false && a.processed_stale');
  const mutated = buggy !== READER;
  const m3 = mutated ? await renderArticle(sandbox(buggy), { processed_stale: true }) : null;
  check('M3-变异：去掉消费后提示消失', mutated && !!m3 && !tipRe.test(m3.html),
    mutated ? JSON.stringify(m3) : '变异锚点缺失（staleTip 修复不在源码里，探针失效）');
}
console.log(JSON.stringify({ cases, failures: cases.filter((c) => !c.ok).length }));
"""


def _run_t13_probe() -> dict:
    require_node()
    node = shutil.which("node")
    assert node is not None
    res = subprocess.run(
        [node, "--input-type=module", "-e", _T13_NODE_PROBE],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=120,
    )
    assert res.returncode == 0, f"node 探针自身失败（不是用例结论）：{res.stderr[-2000:]}"
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert isinstance(out.get("cases"), list), f"探针输出形状异常：{out!r}"
    return out


def _assert_t13_group(out: dict, names: tuple) -> None:
    cs = {c["name"]: c for c in out["cases"]}
    missing = [n for n in names if n not in cs]
    assert not missing, f"探针缺场景 {missing}；现有 {sorted(cs)}"
    bad = [f"{n}: {cs[n]['detail']}" for n in names if not cs[n]["ok"]]
    assert not bad, "T13 行为探针失败：\n" + "\n".join(bad)


def test_t13_placeholder_title_not_written_back() -> None:
    """① 阳性：残留占位串失败后不复写；阴性：真实标题仍复原；变异：去掉归一化 bug 复现。"""
    _assert_t13_group(_run_t13_probe(), (
        "P1-占位标题残留时失败态复原为空且错误正文保留",
        "N1-上一篇真实标题仍被复原",
        "M1-变异：去掉归一化后占位串被写回",
    ))


def test_t13_backoff_timer_cancelled_on_switch_and_unload() -> None:
    """② 阳性：切换/pagehide 清 timer；阴性：正常退避照常 + NLP 提示保留；变异：旧回调复活。"""
    _assert_t13_group(_run_t13_probe(), (
        "P2-切换与卸载均清除旧退避定时器且旧回调不复活",
        "N2-未切换时退避照常触发且NLP提示保留",
        "M2-变异：去掉pagehide监听后旧回调复活",
    ))


def test_t13_processed_stale_shows_visible_hint() -> None:
    """③ 阳性：可见提示且不自动重拉；阴性：无标记不显示；变异：提示消失。"""
    _assert_t13_group(_run_t13_probe(), (
        "P3-processed_stale显示分词升级提示且不自动重拉",
        "N3-无processed_stale不显示提示",
        "M3-变异：去掉消费后提示消失",
    ))
