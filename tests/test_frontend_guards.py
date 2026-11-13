# -*- coding: utf-8 -*-
r"""P0-3 / P0-4 前端守卫：openReader 失败可见化 + 评分按钮重入闸。

⚠️ **这是结构守卫（文本结构断言），弱于行为测试**
------------------------------------------------
本仓**没有** JS 测试基建（无 jsdom / 无 JS test runner），本文件只能断言
"正确的代码形状存在"（try/catch、notify 调用、disabled、重入闸），
**不能**证明这些代码在真实浏览器里的运行时行为。真实验收靠 HITL
（人在环手动验收：真实点击 / 真实超时场景）。若未来引入 JS 测试基建，
本文件应升级为行为级测试后退役。

钉住什么
--------
- P0-3：`reader.js:openReader` 全程静默失败（无 try/catch、无加载态，
  首次打开恰逢 spaCy 惰性迁移 25s 超时 ⇒ 页面停在列表零提示）
  ⇒ openReader 体内必须含 try / catch / notify / "载入中"占位 / finally；
  `static/js/core.js` 必须有浏览器侧全局兜底
  （unhandledrejection + window.onerror → notify，带节流）。
- P0-4：`cards.js:submitCardReview` 无重入闸 + 评分按钮无 disabled
  ⇒ 连点会 FSRS 双推进 + 跳两张卡（学习数据写脏且不可回滚）
  ⇒ 函数体内必须含 `_reviewInFlight` 重入闸、按钮 disabled、finally 恢复。
- P2 首屏惰性：`index.html` 的 workbench iframe 曾带静态 `src`（383KB 的
  workbench.html 首屏即加载并启动内部轮询，即使从不进背词工作台）
  ⇒ iframe 必须只带 `data-src`、**不含**静态 `src=`；`main.js` 在 `show('german')`
  时按视图幂等赋值。

**变异自证**：把 openReader 的 try/catch 删掉 / 把 submitCardReview 的
disabled 与重入闸删掉 / 把 workbench iframe 的静态 `src=` 加回去 ⇒ 对应用例立即转红。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
READER = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

# 与 index.html / main.js 同源的惰性工作台路由（漂移即两侧一起改）。
_WORKBENCH_ROUTE = "/german/workbench.html"


def _extract_function(source: str, signature: str) -> str:
    """按函数签名截取函数体（从签名行到下一个顶层 `export` 或文件尾）。

    够用的文本级近似：JS 函数体行首缩进恒为 0（本仓格式化纪律），
    顶层 export 声明即可作为边界。
    """
    start = source.find(signature)
    assert start != -1, f"找不到函数签名 {signature!r}（前提变了，需重写守卫）"
    next_export = source.find("\nexport ", start + len(signature))
    end = next_export if next_export != -1 else len(source)
    return source[start:end]


# ── P0-3：openReader 失败可见化 ───────────────────────────────────────────────
def test_open_reader_body_has_try_catch_and_notify():
    body = _extract_function(READER, "export async function openReader(")

    assert "try {" in body, "openReader 必须包 try（曾全程静默失败，页面停在列表零提示）"
    assert "catch (" in body, "openReader 必须捕获失败"
    # 失败可见的两条合法通路：旧路径走 notify 弹通知；2026-11-10 起详情改用正文区
    # 常驻错误态（带「重试」按钮），比会消失的 toast 更不容易劝退用户。
    assert "notify(" in body or "_renderReaderError(" in body, (
        "失败必须可见：notify 通知或正文区错误态（不许只 console.error）"
    )
    assert "finally" in body, "加载态必须在 finally 里恢复（不许卡死在占位文案）"


def test_open_reader_shows_loading_placeholder_in_title():
    body = _extract_function(READER, "export async function openReader(")

    assert "载入中" in body, "进入时必须在 reader-title 置加载占位（25s 超时也要有反馈）"


# ── P0-3：浏览器侧全局兜底（去重/节流，别弹成一串） ────────────────────────────
def test_core_has_global_error_fallback_with_throttle():
    assert 'unhandledrejection' in CORE and 'addEventListener' in CORE, (
        "core.js 必须挂 unhandledrejection 全局兜底（static/ 内此前为零）"
    )
    assert "window.onerror" in CORE, "core.js 必须挂 window.onerror 全局兜底"
    assert "notify(" in CORE, "全局兜底必须统一走 notify"
    assert "Date.now()" in CORE, "全局兜底必须节流（同错连发不得弹成一串）"


# ── P0-4：评分请求防重入（FSRS 双推进 + 跳两张卡） ────────────────────────────
def test_submit_card_review_has_reentry_gate_and_disabled_buttons():
    # 飞行标志已搬进 cardState.deck.reviewInFlight（cd-state.js 簇 2）。断言形状逐字不动，
    # 只换标识符：本条抓的是「入口有闸 + 成对置位/复位 + disabled + finally」四件事。
    body = _extract_function(CARDS, "export async function submitCardReview(")

    assert "if (cardState.deck.reviewInFlight) return" in body, (
        "函数入口必须有重入闸：连点期间的新请求直接丢弃"
    )
    assert "cardState.deck.reviewInFlight = true" in body and "cardState.deck.reviewInFlight = false" in body, (
        "飞行标志必须成对置位/复位"
    )
    assert "disabled = true" in body, "请求飞行期间评分按钮必须 disabled（照 writer.js 既有模式）"
    assert "finally" in body, "按钮恢复必须放 finally（失败路径也不许把按钮锁死）"


# ── 评分按钮的 onclick 与重入闸共存（按钮本体仍可点，由函数内部挡） ────────────
def test_rating_bar_buttons_still_rendered_with_submit_handler():
    assert "submitCardReview(" in CARDS, "评分按钮必须仍接线 submitCardReview（守卫不得误删接线）"


# ── P2 首屏惰性：workbench iframe 不得静态挂载（data-src + 按视图赋值）────────────
def _german_view_block() -> str:
    """截取 index.html 里 `#view-german` 的 `<main>` 块（与 test_german_workbench 同切法）。"""
    return INDEX.split('id="view-german"')[1].split("</main>")[0]


def test_workbench_iframe_is_lazy_no_static_src():
    """首屏不得静态挂载 workbench iframe：必须用 `data-src`，且**没有**裸 `src=` 属性。

    ⚠️ **结构守卫（文本结构断言），弱于行为测试**：本仓无 JS 测试基建，它只能证明
    "正确的代码形状存在"，**不能**证明真实浏览器里首屏真的不再加载该 iframe。真实验收
    靠 HITL（真实启动一次、看 network 面板 / `launch.log` 首屏口径）。
    """
    block = _german_view_block()
    assert f'data-src="{_WORKBENCH_ROUTE}"' in block, "workbench iframe 必须用 data-src 惰性路由"
    # data-src= 里含子串 `src=`，故用负向后顾 `(?<![-\w])` 排除 `-src=` / 标识符前缀，
    # 只匹配真正的 `src=` 属性；否则守卫会被 data-src 形态骗过。
    assert re.search(r"(?<![-\w])src\s*=", block) is None, (
        "workbench iframe 不得带静态 src=（会让 383KB 的 workbench.html 首屏即加载、并启动其内部轮询）"
    )


def test_main_js_wires_lazy_workbench_on_german_view():
    """main.js 必须在进入 german 视图时按视图幂等赋 src（结构守卫，弱于行为测试）。"""
    helper = _extract_function(MAIN, "function ensureGermanWorkbench(")
    assert 'getElementById("german-workbench-frame")' in helper, "未按 id 取到 workbench iframe"
    assert 'getAttribute("data-src")' in helper, "未从 data-src 读取惰性路由"
    assert 'setAttribute("src"' in helper, "未把惰性路由赋给 src"
    assert 'getAttribute("src")' in helper, "缺少幂等守卫（重设 src 会整页重载、丢工作台状态）"

    show_body = _extract_function(MAIN, "export function show(")
    assert "ensureGermanWorkbench()" in show_body, "show('german') 未接线 ensureGermanWorkbench()"


# ── ADR-0029 I1：关闭键的可访问名（字形 ✕ 不得是意义的唯一载体）────────────────
def test_modal_close_buttons_have_accessible_name():
    """`static/modals/*.html` 里每个 `class="drawer-close"` 按钮必须有可用名。

    ADR-0029 不变量 I1：任何字形都不得是意义的唯一载体；可访问名只能来自
    可见文字 / `aria-label` / `aria-labelledby`，`title` 不计入。

    ⚠️ **结构守卫（文本结构断言），弱于行为测试**：本仓无 JS 测试基建，它只能
    证明 "aria-label 属性存在"，**不能**证明真实浏览器里读屏真的念得出名字。
    真实验收靠 HITL（读屏 / 无障碍树抽查）。
    """
    # 开标签属性可跨行，用 re.DOTALL；`[^>]*` 保证不吞掉下一个标签。
    open_tag_re = re.compile(
        r'<button\b[^>]*\bclass\s*=\s*"[^"]*\bdrawer-close\b[^"]*"[^>]*>',
        re.DOTALL,
    )

    hits: list[tuple[str, str]] = []
    for path in sorted((ROOT / "static" / "modals").glob("*.html")):
        source = path.read_text(encoding="utf-8")
        hits.extend((path.name, m.group(0)) for m in open_tag_re.finditer(source))

    missing = [
        (name, tag)
        for name, tag in hits
        if not re.search(r"\baria-label\s*=", tag)
        and not re.search(r"\baria-labelledby\s*=", tag)
    ]
    assert not missing, "关闭键缺可访问名（title / ✕ 字形不计入）：\n" + "\n".join(
        f"{name}: {tag}" for name, tag in missing
    )

    # 防正则静默失效：当前实际 6 个（drawer / import / polish / settings /
    # version_preview + cloze_overlay），匹配数骤降说明守卫已被改瞎。
    assert len(hits) >= 6, f"只匹配到 {len(hits)} 个 drawer-close 按钮，正则疑似失效"


# ── v5.23.2 事故守卫：状态模板里引用了已删除的变量 ────────────────────────────
# 事故：_readerStateHtml 删掉 `const bar = ...` 后，模板里仍留着 `${bar}`。模块能
# 解析（不是重复导出那种解析期错误），但**一进阅读页就** `ReferenceError: bar is
# not defined` —— 点文章毫无反应，只有全局兜底弹一条提示。node --check 与模块图
# 守卫都只查语法/绑定，看不见这条渲染路径。这里只核对这一个模板函数：`${名字}`
# 形式的纯标识符必须在本函数内声明过。
def test_reader_state_template_uses_only_declared_vars():
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
import shutil  # noqa: E402
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
