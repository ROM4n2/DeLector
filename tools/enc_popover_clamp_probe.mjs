/**
 * enc_popover_clamp_probe.mjs —— 遇见区弹层垂直视口夹取 / 向上翻转行为探针
 *
 * 事故（2026-10-04 子计划 3 Task 2）：手机竖屏（约 640px 可视高）读短文滚到
 * **每屏最后一行**点该行 `.enc-unk`，此时 rect.bottom ≈ 596，而弹层高 150-200px；
 * 弹层是 position:fixed 且无 max-height/overflow ⇒ 100% 落在屏幕外 ⇒ 用户看不到
 * 任何反馈，像是点击无效。这是 .enc-unk **唯一的**交互入口，每屏可复现。
 *
 * 本探针把 encounter.js **真源码**剥 import/export 后进 node:vm 真跑（不重抄实现），
 * 直接调 `openPopoverNear(rect, ...)`，用桩 `window.innerHeight` / `pop.offsetHeight`
 * / `pop.offsetWidth` 驱动，逐条断言定位契约：
 *   1 核心：贴视口底部点击 ⇒ 写入的 style.top 必须**完整落在视口内**（8 <= top <= vh-h-8）；
 *   2 翻转：top 必须**小于 rect.bottom**（证明是向上翻转，不是单纯 Math.min 夹取）；
 *   3 上方空间足够时不翻转：视口上半部点击 ⇒ 仍是 rect.bottom + 6（旧行为不回归）；
 *   4 极矮视口（vh < h + 16）⇒ top >= 8，贴屏顶也留边，不能为负；
 *   5 同帧只读一次 offsetHeight（No-Layout-Thrash：读一次、算一次、写一次）。
 *
 * 用法：
 *   node tools/enc_popover_clamp_probe.mjs            # 人类可读
 *   node tools/enc_popover_clamp_probe.mjs --json     # stdout 只输出 JSON
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const fail = (msg) => {
  process.stderr.write(msg + "\n");
  process.exit(1);
};

const ENC_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "encounter.js"), "utf8");

/* 剥 import（encounter.js 的 import 块是跨行的多行具名导入）/ export 前缀。 */
function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
}
const transformed = strip(ENC_SRC);
if (/^import\b/m.test(transformed)) fail("encounter.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
if (/^\s*export\b/m.test(transformed)) fail("encounter.js 剥离后仍有 export（探针转换器跟不上源码形态）");

/* ── 沙箱：只需要 openPopoverNear 走到的那条路径 ───────────────────────────── */
const DOM_IDS = [
  "encounter-text-list", "encounter-reader", "enc-coverage", "enc-i1-hint",
  "enc-popover", "enc-review", "enc-review-toggle", "enc-add-error",
  "encounter-add-form", "encounter-pull-panel", "encounter-pull-log", "encounter-pull-base",
];

function makeEl(id, counters) {
  const el = {
    id,
    innerHTML: "",
    textContent: "",
    disabled: false,
    style: {},
    dataset: {},
    _classes: new Set(),
    classList: {
      add(c) { el._classes.add(c); },
      remove(c) { el._classes.delete(c); },
      toggle(c, f) { const on = f === undefined ? !el._classes.has(c) : Boolean(f); if (on) el.classList.add(c); else el.classList.remove(c); return on; },
      contains(c) { return el._classes.has(c); },
    },
    attrs: {},
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return el.attrs[k] != null ? el.attrs[k] : null; },
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    remove() {},
    contains() { return false; },
    closest() { return null; },
    // 弹层内部子查询：返回一个能吞下 classList/textContent 的哑元（lookupGloss 会写）。
    querySelector() { return makeEl(`${id}__child`, counters); },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }; },
    /* offsetWidth/Height 是 getter：计数读取次数（No-Layout-Thrash 守卫）。 */
    _offsetWidth: 240,
    _offsetHeight: 0,
    get offsetWidth() { counters.widthReads++; return this._offsetWidth; },
    get offsetHeight() { counters.heightReads++; return this._offsetHeight; },
  };
  return el;
}

function newEnv({ innerWidth = 390, innerHeight = 640, offsetWidth = 240, offsetHeight = 180 } = {}) {
  const counters = { widthReads: 0, heightReads: 0 };
  const registry = new Map();
  for (const id of DOM_IDS) registry.set(id, makeEl(id, counters));

  const document = {
    getElementById(id) {
      if (!registry.has(id)) registry.set(id, makeEl(id, counters));
      return registry.get(id);
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
    createElement(tag) { return makeEl(`__created__${tag}`, counters); },
    body: { appendChild() {} },
    documentElement: { appendChild() {} },
  };

  const storage = { getItem: () => null, setItem() {}, removeItem() {} };
  const sandbox = {
    console,
    document,
    window: { localStorage: storage, innerWidth, innerHeight },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    Promise, Set, Map, Symbol, parseInt, parseFloat, isNaN, undefined,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController,
    api: () => Promise.resolve({}),          // 词典查询：探针只关心定位，不关心 gloss
    esc: (s) => String(s == null ? "" : s),
    notify() {},
    playGermanAudio() {},
    loadDeck: () => ({ words: [], cards: {} }),
    mergeServerDeck: (d) => d,
    addCardToDeck: () => ({ deck: {} }),
    buildKnownSet: () => new Set(),
    mergeKnownLemmas: (a) => a,
    annotateWithDeck: (deck, annotate) => ({ sentences: annotate.sentences, stats: {} }),
    DECK_KEYS: { words: "wb.words.v1", cards: "wb.cards.v1" },
    rankEntries: () => [],
    hasCoverage: () => true,
    loadRead: () => ({}),
    isRead: () => false,
    pickUnread: () => null,
    markRead() {},
    PULL_ENDPOINT: "/api/encounter/pull-pack",
    normalizeDesktopBase: (s) => s,
    readDesktopBase: () => "",
    writeDesktopBase() {},
    mapPackRows: () => [],
    pullPackRequest: () => ({}),
  };

  const ctx = vm.createContext(sandbox);
  vm.runInContext(transformed, ctx, { filename: "encounter.js" });

  const pop = registry.get("enc-popover");
  pop._offsetWidth = offsetWidth;
  pop._offsetHeight = offsetHeight;

  /** 在真源码上跑一次 openPopoverNear，返回 { top, left, rect, height }。 */
  function open(rect) {
    counters.heightReads = 0;
    counters.widthReads = 0;
    vm.runInContext(
      `openPopoverNear(${JSON.stringify(rect)}, "lemma", "Wort", "NOUN", 0)`,
      ctx,
    );
    const rawTop = String(pop.style.top);
    const rawLeft = String(pop.style.left);
    const m = /(-?[\d.]+)px/.exec(rawTop);
    if (!m) fail(`openPopoverNear 没写 style.top（读到 ${JSON.stringify(rawTop)}）—— 探针失配`);
    return {
      top: Number(m[1]),
      left: /(-?[\d.]+)px/.exec(rawLeft) ? Number(/(-?[\d.]+)px/.exec(rawLeft)[1]) : NaN,
      rect,
      height: offsetHeight,
      heightReads: counters.heightReads,
    };
  }

  return { open, ctx, registry };
}

const rectOf = (top, bottom, left = 24) => ({
  top, bottom, left, right: left + 80, width: 80, height: bottom - top,
});

const problems = [];

/* ══ 1 核心：点每屏最后一行（贴视口底部）⇒ 弹层必须完整落在视口内 ═══════════ */
{
  const { open } = newEnv({ innerHeight: 640, offsetHeight: 180 });
  const rect = rectOf(580, 596);              // 手机竖屏滚到底：rect.bottom ≈ 596
  const r = open(rect);
  const lo = 8;
  const hi = 640 - 180 - 8;                   // 452
  if (!(r.top >= lo && r.top <= hi))
    problems.push(
      `[1] 贴视口底部点击时弹层越界：style.top=${r.top}px，rect.bottom=${rect.bottom}，` +
      `但弹层必须落在 [${lo}, ${hi}]（vh=640, h=180）—— 整块弹层落在屏幕外，用户零反馈`,
    );
}

/* ══ 2 翻转：空间不足时必须向上翻转，而不是只 Math.min 贴住底边 ══════════════
 * 这里的几何是**唯一**能区分「翻转」与「纯夹取」的窄带：vh - popH - EDGE 落在
 * (rect.bottom, rect.bottom + GAP) 之间 —— 纯 Math.min 夹出来的 top 会 ≥ rect.bottom，
 * 即弹层还压在刚点的词上（只夹不翻，用户的点击被自己选的弹层遮住）。
 * 同时断言弹层**整块**位于词上方（top + popH <= rect.top），证明是真翻转不是挪了 1px。
 */
{
  const { open } = newEnv({ innerHeight: 800, offsetHeight: 210 });
  const rect = rectOf(560, 580);              // 800 - 210 - 8 = 582 > 580，落在窄带里
  const r = open(rect);
  if (!(r.top < rect.bottom))
    problems.push(
      `[2] top=${r.top}px 不小于 rect.bottom=${rect.bottom}px —— 只是被 Math.min 夹住，` +
      `没有向上翻转；弹层仍压在用户刚点的词上`,
    );
  if (!(r.top + r.height <= rect.top))
    problems.push(
      `[2] 翻转不彻底：top=${r.top}px + h=${r.height}px = ${r.top + r.height}px > rect.top=` +
      `${rect.top}px —— 弹层没有整块落到点词上方`,
    );
}

/* ══ 3 上方空间足够时不翻转（旧的 rect.bottom + 6 行为不得回归） ════════════ */
{
  const { open } = newEnv({ innerHeight: 640, offsetHeight: 180 });
  const rect = rectOf(100, 116);              // 视口上半部
  const r = open(rect);
  const want = rect.bottom + 6;               // 116 + 6 = 122
  if (r.top !== want)
    problems.push(
      `[3] 上方空间足够却翻转/夹取了：style.top=${r.top}px，应保持旧行为 ${want}px ` +
      `(= rect.bottom + 6)—— 定位回归`,
    );
}

/* ══ 4 极矮视口（vh < h + 16）⇒ 贴屏顶也要留 8px 边，不能为负 ═══════════════ */
{
  const { open } = newEnv({ innerHeight: 150, offsetHeight: 180 });
  const rect = rectOf(580, 596);
  const r = open(rect);
  if (!(r.top >= 8))
    problems.push(
      `[4] 极矮视口下 top=${r.top}px < 8 —— 翻转后没再夹上边界，弹层顶部会被切掉 ` +
      `(vh=150 < h+16=196，此时 vh-h-8 为负)`,
    );
}

/* ══ 5 No-Layout-Thrash：同一帧内 offsetHeight 只读一次 ══════════════════════ */
{
  const { open } = newEnv({ innerHeight: 640, offsetHeight: 180 });
  const r = open(rectOf(580, 596));
  if (r.heightReads !== 1)
    problems.push(
      `[5] 同一帧读了 ${r.heightReads} 次 pop.offsetHeight —— 必须读一次、算一次、写一次 ` +
      `(反复读会触发同帧多次强制重排)`,
    );
}

/* ── 裁决 ────────────────────────────────────────────────────────────────── */
if (problems.length) {
  fail(`遇见区弹层垂直定位契约破坏（子计划 3 Task 2）：\n  - ${problems.join("\n  - ")}`);
}

const out = {
  ok: true,
  1: "贴视口底部：style.top 落在 [8, vh-h-8]，弹层完整可见",
  2: "空间不足时向上翻转（top < rect.bottom），不是单纯 Math.min",
  3: "上方空间足够时不翻转，仍是 rect.bottom + 6（旧行为不回归）",
  4: "极矮视口（vh < h+16）时 top >= 8，贴屏顶也留边",
  5: "同帧只读一次 offsetHeight（No-Layout-Thrash）",
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  for (const k of ["1", "2", "3", "4", "5"]) console.log(`${k}: ${out[k]}`);
  console.log("✅ PASS: 弹层垂直夹取 + 向上翻转 + 极矮视口留边全部生效");
}