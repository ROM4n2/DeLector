/**
 * frontend_guards_probe.mjs —— P0-3 / P0-4 前端守卫 行为探针（T10）
 *
 * 被测实现不重抄：按红线 13「锚点 + 括号配平」从真源码切出函数/声明，
 * 放进 node:vm 真跑；沙箱只提供环境桩（document / notify / fetch 驱动面），
 * 不放任何手写实现与真源码切片并存的「两个真相源」。
 *
 * 静态/切片层任一失败 ⇒ 记 probe_bootstrap 失败并直接退出，不进 vm。
 * --json 标准 A 类契约：{failures, total, cases:[{name, ok}]}；失败 exit 1。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8").replace(/\r\n/g, "\n");
const cases = [];
const check = (name, ok, detail = "") =>
  cases.push({ name, ok: !!ok, detail: ok ? "" : String(detail) });

/* ── 红线 13：锚点 + 括号配平（口径同 tools/cards_catalog_tag_probe.mjs）── */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx, label) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket(${label}): 位置 ${openIdx} 不是开括号`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c; i += 1;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === q) break;
        i += 1;
      }
      i += 1; continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (OPEN[c]) { stack.push(c); i += 1; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c])
        throw new Error(`matchBracket(${label}): 括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i += 1; continue;
    }
    i += 1;
  }
  throw new Error(`matchBracket(${label}): 从 ${openIdx} 起找不到配对闭括号（MUST NOT 返回短切片）`);
}

function sliceFunctionBody(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`找不到声明 ${declNeedle}（实现回退或改名）`);
  const paren = src.indexOf("(", at);
  if (paren < 0) throw new Error(`${declNeedle} 后找不到参数表 '('`);
  const paramsEnd = matchBracket(src, paren, declNeedle + " 参数表");
  let j = paramsEnd + 1;
  while (j < src.length && /\s/.test(src[j])) j += 1;
  if (src[j] !== "{")
    throw new Error(
      `${declNeedle}: 参数表 ')' 后下一个非空白字符不是函数体 '{'` +
      `（实际 ${JSON.stringify(src[j] ?? "<EOF>")}）：MUST NOT 返回短切片（红线 13）`
    );
  const end = matchBracket(src, j, declNeedle + " 函数体");
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

function sliceObjectDecl(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`找不到对象声明 ${declNeedle}`);
  const open = src.indexOf("{", at);
  if (open < 0) throw new Error(`${declNeedle} 后找不到 '{'`);
  const end = matchBracket(src, open, declNeedle);
  return src.slice(at, end + 1).replace(/^export\s+/, "") + ";";
}

function sliceBlock(src, marker, label) {
  const at = src.indexOf(marker);
  if (at < 0) throw new Error(`找不到块锚点 ${marker}`);
  const open = src.indexOf("{", at);
  if (open < 0) throw new Error(`${label}: 锚点后找不到 '{'`);
  return src.slice(at, matchBracket(src, open, label) + 1);
}

function takeLine(src, re, label) {
  const m = src.match(re);
  if (!m) throw new Error(`找不到真源码声明 ${label}（不许手写桩顶替）`);
  return m[0];
}

function replaceOnce(src, needle, replacement, label) {
  const count = src.split(needle).length - 1;
  if (count !== 1) throw new Error(`${label}: 注入式变异锚点应恰好 1 处，实际 ${count}`);
  return src.replace(needle, replacement);
}

function newSandbox(extra) {
  const ctx = Object.assign({
    console: { warn() {}, error() {}, log() {} },
    JSON, Math, Promise, Array, Object, Number, String, Boolean, Set, Map, Error,
    setTimeout: (fn) => { fn(); return 0; },
    clearTimeout() {},
  }, extra);
  vm.createContext(ctx);
  return ctx;
}

/* ── 真源码切片（bootstrap 失败即红，且不再进 vm）── */
let readerJs, cardsJs, coreJs, mainJs, cdStateJs, indexHtml;
let openReaderFn, submitFn, reportFn, guardBlock, ensureFn, cardStateDecl;
try {
  readerJs = read("static/js/reader.js");
  cardsJs = read("static/js/cards.js");
  coreJs = read("static/js/core.js");
  mainJs = read("static/js/main.js");
  cdStateJs = read("static/js/cd-state.js");
  indexHtml = read("static/index.html");

  openReaderFn = sliceFunctionBody(readerJs, "export async function openReader(");
  submitFn = sliceFunctionBody(cardsJs, "export async function submitCardReview(");
  reportFn = sliceFunctionBody(coreJs, "function _reportGlobalError(");
  guardBlock = sliceBlock(
    coreJs, "if (typeof window !== 'undefined' && !window.__delectorGlobalGuards)", "全局兜底注册块"
  );
  ensureFn = sliceFunctionBody(mainJs, "function ensureGermanWorkbench(");
  cardStateDecl = sliceObjectDecl(cdStateJs, "export const cardState = ");

  // 切片护栏：切歪/退化成签名即红，不许静默假绿
  if (!openReaderFn.includes("finally") || !openReaderFn.includes("_renderReaderError("))
    throw new Error("openReader 切片缺 finally / 错误态（切到签名了？）");
  if (!submitFn.includes("reviewInFlight = false"))
    throw new Error("submitCardReview 切片缺 finally 复位（切短了？）");
  if (!cardStateDecl.includes("reviewInFlight"))
    throw new Error("cd-state.js 的 cardState 真声明切片不含 reviewInFlight（切歪了？）");
} catch (e) {
  check("probe_bootstrap", false, "源码切片/锚点失败：" + e.message);
}

const readerStatePrefix = () => [
  takeLine(readerJs, /^let _readerOpenToken\s*=.*$/m, "_readerOpenToken"),
  takeLine(readerJs, /^const READER_LOADING_HINT\s*=.*$/m, "READER_LOADING_HINT"),
  takeLine(readerJs, /^const READER_NLP_LOADING_HINT\s*=.*$/m, "READER_NLP_LOADING_HINT"),
].join("\n");

/* ── A：openReader 加载占位 + 失败可见 ─── */
async function scenarioOpenReader() {
  async function run(slice) {
    const state = { loading: [], errors: [], notify: [] };
    const titleEl = { textContent: "上一篇标题" };
    const ctx = newSandbox({
      document: { getElementById: (id) => (id === "reader-title" ? titleEl : null) },
      _renderReaderLoading: (h) => state.loading.push(h),
      _renderReaderError: (msg, canRetry) => state.errors.push({ msg, canRetry }),
      _humanizeReaderError: (err) => String(err && err.message),
      _isNlpLoadingError: () => false,
      isRetryableError: () => false,
      RETRY_DELAYS_MS: [],
      RETRY_BUDGET_MS: 0,
      _openReaderBody: async () => { throw new Error("boom"); },
      notify: (msg) => state.notify.push(msg),
      Date: class extends Date { static now() { return 1000; } },
    });
    vm.runInContext(
      readerStatePrefix() + "\n" + slice + "\nglobalThis.__run = openReader;", ctx
    );
    const p = ctx.__run(1);
    const titleAtEntry = titleEl.textContent;
    await p;
    return { state, titleEl, titleAtEntry };
  }

  const r = await run(openReaderFn);
  check("open_reader_shows_loading_placeholder",
    r.titleAtEntry === "⏳ 载入中…" && r.state.loading.length >= 1,
    `titleAtEntry=${r.titleAtEntry} loading=${r.state.loading.length}`);
  check("open_reader_failure_renders_visible_error_and_restores_title",
    (r.state.errors.length === 1 || r.state.notify.length >= 1) &&
      r.titleEl.textContent === "上一篇标题",
    `errors=${r.state.errors.length} notify=${r.state.notify.length} title=${r.titleEl.textContent}`);

  const noPlaceholder = replaceOnce(
    openReaderFn, 'if (titleEl) titleEl.textContent = "⏳ 载入中…";',
    "if (titleEl) { /* 占位被删 */ }", "openReader 加载占位"
  );
  const m1 = await run(noPlaceholder);
  check("mutation_open_reader_placeholder_removed_is_caught",
    m1.titleAtEntry !== "⏳ 载入中…", "删掉占位后判据仍认为有占位 ⇒ 死测");

  const errorBlock =
    "          _renderReaderError(_humanizeReaderError(err), canRetry, () => {\n" +
    "            void openReader(id);\n" +
    "          });";
  const noError = replaceOnce(openReaderFn, errorBlock, "          /* 错误态被删 */", "openReader 错误态");
  const m2 = await run(noError);
  check("mutation_open_reader_error_state_removed_is_caught",
    m2.state.errors.length === 0 && m2.state.notify.length === 0,
    "删掉错误态后判据仍看到提示 ⇒ 死测");
}

/* ── B：submitCardReview 重入闸 + disabled ─── */
async function scenarioSubmitReview() {
  async function run(slice) {
    const buttons = Array.from({ length: 4 }, () => ({ disabled: false }));
    let reviewCalls = 0;
    let release;
    const pending = new Promise((res) => { release = res; });
    const ctx = newSandbox({
      document: { querySelectorAll: () => buttons },
      navigator: {},
      reviewCard: () => { reviewCalls += 1; return pending; },
      showUndoToast() {}, stepDeck() {}, refreshDueCount() {},
      Companion: { celebrate() {} }, notify() {},
    });
    vm.runInContext(
      cardStateDecl + "\n" + slice +
        "\nglobalThis.__submit = submitCardReview; globalThis.__state = cardState;", ctx
    );
    const p1 = ctx.__submit("vocab", 1, 3);
    const p2 = ctx.__submit("vocab", 1, 3); // 连点
    const snap = {
      reviewCalls,
      allDisabled: buttons.every((b) => b.disabled === true),
      inFlight: ctx.__state.deck.reviewInFlight,
    };
    release();
    await Promise.all([p1, p2]);
    return { snap, buttons, ctx };
  }

  const r = await run(submitFn);
  check("submit_review_reentry_gate_blocks_double_post", r.snap.reviewCalls === 1,
    `连点发出 ${r.snap.reviewCalls} 次请求`);
  check("submit_review_buttons_disabled_during_flight_and_restored",
    r.snap.allDisabled && r.snap.inFlight === true &&
      r.buttons.every((b) => b.disabled === false) &&
      r.ctx.__state.deck.reviewInFlight === false,
    `snap=${JSON.stringify(r.snap)}`);

  const noGate = replaceOnce(
    submitFn, "if (cardState.deck.reviewInFlight) return;", "", "submitCardReview 重入闸"
  );
  const m = await run(noGate);
  check("mutation_submit_review_gate_removed_is_caught", m.snap.reviewCalls === 2,
    "删掉重入闸后判据仍看到单请求 ⇒ 死测");
}

/* ── C：core.js 全局兜底注册 + 节流 ─── */
function scenarioGlobalGuard() {
  function run(sliceReport, sliceReg) {
    let now = 1000;
    const notifyCalls = [];
    const listeners = {};
    const win = {
      addEventListener: (t, fn) => { (listeners[t] ||= []).push(fn); },
      onerror: null,
    };
    const ctx = newSandbox({
      window: win,
      notify: (msg) => notifyCalls.push(msg),
      Date: class extends Date { static now() { return now; } },
    });
    vm.runInContext(
      [takeLine(coreJs, /^let _lastGlobalError\s*=.*$/m, "_lastGlobalError"),
       sliceReport, sliceReg].join("\n"), ctx
    );
    return { ctx, notifyCalls, listeners, setNow: (v) => { now = v; } };
  }
  const r = run(reportFn, guardBlock);
  check("global_guard_registers_both_listeners",
    (r.listeners["unhandledrejection"] || []).length === 1 &&
      typeof r.ctx.window.onerror === "function", "全局兜底监听器未挂全");
  const fire = (msg) => r.listeners["unhandledrejection"][0]({ reason: { message: msg } });
  fire("boom"); fire("boom");
  r.setNow(5000); fire("boom");
  check("global_guard_throttles_duplicate_errors", r.notifyCalls.length === 2,
    `同错连发/节流过期后的 notify 次数异常：${r.notifyCalls.length}`);

  const noThrottle = replaceOnce(
    reportFn,
    "if (message === _lastGlobalError.message && now - _lastGlobalError.at < 3000) return;",
    "", "全局兜底节流"
  );
  const m = run(noThrottle, guardBlock);
  const fire2 = (msg) => m.listeners["unhandledrejection"][0]({ reason: { message: msg } });
  fire2("boom"); fire2("boom");
  check("mutation_global_guard_throttle_removed_is_caught", m.notifyCalls.length === 2,
    "删掉节流后判据仍看到 1 次 notify ⇒ 死测");
}

/* ── D：iframe 首屏惰性 + ensureGermanWorkbench 幂等 ─── */
function iframeHasNoStaticSrc(tag) {
  const attrs = {};
  for (const a of tag.matchAll(/([-\w]+)\s*=\s*"([^"]*)"/g)) attrs[a[1]] = a[2];
  return !("src" in attrs) && attrs["data-src"] === "/german/workbench.html";
}

function scenarioWorkbenchIframe() {
  const m = indexHtml.match(/<iframe\b[^>]*\bid="german-workbench-frame"[^>]*>/i);
  if (!m) {
    check("workbench_iframe_has_no_static_src", false, "index.html 找不到 workbench iframe 标签");
    return;
  }
  check("workbench_iframe_has_no_static_src", iframeHasNoStaticSrc(m[0]), m[0]);

  const attrs = {};
  for (const a of m[0].matchAll(/([-\w]+)\s*=\s*"([^"]*)"/g)) attrs[a[1]] = a[2];
  const frame = {
    attrs: { ...attrs }, setCalls: [],
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = String(v); this.setCalls.push(k); },
  };
  const ctx = newSandbox({ document: { getElementById: () => frame } });
  vm.runInContext(ensureFn + "\nglobalThis.__ensure = ensureGermanWorkbench;", ctx);
  ctx.__ensure(); ctx.__ensure();
  check("ensure_workbench_is_lazy_and_idempotent",
    frame.getAttribute("src") === "/german/workbench.html" && frame.setCalls.length === 1,
    `src=${frame.getAttribute("src")} setCalls=${frame.setCalls.length}`);

  const mutatedTag = m[0].replace(/<iframe\b/, '<iframe src="/german/workbench.html"');
  check("mutation_iframe_static_src_added_is_caught", !iframeHasNoStaticSrc(mutatedTag),
    "静态 src 回潮后判据仍看不见 ⇒ 死测");
}

/* ── E：切片自证（红线 13 两型静默失效）── */
function scenarioSliceBalance() {
  const destructured = "async function f({a}={}) { return a; }\n";
  let sliced = "";
  try { sliced = sliceFunctionBody(destructured, "async function f("); }
  catch (e) { check("slice_destructured_params_not_short", false, e.message); return; }
  check("slice_destructured_params_not_short",
    sliced.includes("return a;") && sliced.trimEnd().endsWith("}"),
    `解构参数切片退化：${JSON.stringify(sliced)}`);
  let threw = false;
  try { sliceFunctionBody("async function g() 42;", "async function g("); }
  catch (e) { threw = /不是|MUST/.test(e.message); }
  check("slice_rejects_non_brace_after_paren", threw, "')' 后非 '{' 未具名报错");
}

async function main() {
  if (cases.some((c) => !c.ok)) return; // 静态/切片层已红 ⇒ MUST NOT 跑 node:vm
  await scenarioOpenReader();
  await scenarioSubmitReview();
  scenarioGlobalGuard();
  scenarioWorkbenchIframe();
  scenarioSliceBalance();
}
await main();

const failures = cases.filter((c) => !c.ok);
for (const c of failures) console.error(`[FAIL] ${c.name}: ${c.detail}`);
console.log(JSON.stringify({
  failures: failures.length, total: cases.length,
  cases: cases.map((c) => ({ name: c.name, ok: c.ok })),
}));
process.exit(failures.length ? 1 : 0);
