/**
 * enc_coverage_degraded_probe.mjs —— 覆盖率行的「降级来源」标注行为探针
 *
 * 债（清债轮 B 债 4）：唯一覆盖率行（renderCoverage）只有三个数字
 * （`已背词覆盖 12/312 词位（4%）`），**无来源、无降级标记**。而两路来源都在前端
 * **静默降级**：
 *   ① `resolveDeck()`  —— 本机 localStorage，空则拉 `GET /api/wb/state`，**catch 是空实现**；
 *   ② `fetchKnownLemmas()` —— catch 返回 `[]`。
 * ⇒ 离线 / 清过站点数据 / 镜像拉取失败时，覆盖率**静默变低**成「已背词覆盖 0/312（0%）」，
 *    用户**无法分辨**是「真没背」还是「拉取失败」。
 *
 * 已核实的事实（不凭印象）：`stats.total_tokens`（分母 total）由
 * deck-bridge.annotateWithDeck 从 **annotate 端点返回的 token 流**数出，**与 resolveDeck 无关**；
 * `known_tokens`（分子）= `buildKnownSet(deck) ∪ extraKnownLemmas` ⇒ **两路降级都只压低分子、
 * 不动分母**。所以「数据不完整」是对分子失真的准确描述。
 *
 * 本探针把 encounter.js **真源码**剥 import/export 后进 node:vm 真跑（不重抄实现），
 * 直接调 `renderTextDetailAnnotated(text, annotate)`，用桩 api() / localStorage / DOM 驱动，
 * 逐条断言（只标覆盖率行，不动列表徽章 —— 徽章只有百分比、无分母，误导性弱）：
 *   B1 正常时**不含**任何降级标记（行内无 ⚠、无「数据不完整」、title 为空）；
 *   B2 fetchKnownLemmas 失败 ⇒ 含降级标记，且行内 + title **都不含技术字段名**
 *      （fsrs_s / lemmas / known-lemmas / /api/… / HTTP 状态码 / 英文异常名）；
 *   B3 resolveDeck 降级（本机 deck 空 + GET /api/wb/state 抛错）⇒ 含降级标记；
 *   B4 两路都降级 ⇒ 标记**只叠一份**（⚠ 与「数据不完整」各出现一次），title 给出两条原因；
 *   B5 正常路径文案**逐字未变**：仍等于去重/标注之前的字面量
 *      `已背词覆盖 12/312 词位（4%）`（防顺带改文案）。
 *
 * 用法：
 *   node tools/enc_coverage_degraded_probe.mjs            # 人类可读
 *   node tools/enc_coverage_degraded_probe.mjs --json     # {failures,total,cases:[…]}
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const ENC_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "encounter.js"), "utf8");

function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
}
const transformed = strip(ENC_SRC);
if (/^import\b/m.test(transformed)) fail("encounter.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
if (/^\s*export\b/m.test(transformed)) fail("encounter.js 剥离后仍有 export（探针转换器跟不上源码形态）");

function fail(msg) {
  if (JSON_MODE) process.stdout.write(JSON.stringify({ ok: false, error: msg }) + "\n");
  else process.stderr.write(msg + "\n");
  process.exit(1);
}

const KNOWN_URL = "/api/cards/known-lemmas";
const WB_URL = "/api/wb/state";

/** 去重/标注之前的覆盖率行字面量 —— B5 逐字比对用。 */
const NORMAL_COPY = "已背词覆盖 12/312 词位（4%）";
const STATS = { total_tokens: 312, known_tokens: 12, known_rate: 12 / 312 };

const ANNOTATE = {
  sentences: [
    {
      idx: 0,
      tokens: [
        { text: "Haus", lemma: "Haus", pos: "NOUN", known: false },
        { text: "Zug", lemma: "Zug", pos: "NOUN", known: false },
      ],
    },
  ],
};

const DOM_IDS = [
  "encounter-text-list", "encounter-reader", "enc-coverage", "enc-i1-hint",
  "enc-popover", "enc-review", "enc-review-toggle", "enc-add-error",
  "encounter-add-form", "encounter-pull-panel", "encounter-pull-log", "encounter-pull-base",
];

function makeEl(id) {
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
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }; },
  };
  return el;
}

function makeDocumentStub() {
  const registry = new Map();
  for (const id of DOM_IDS) registry.set(id, makeEl(id));
  return {
    registry,
    getElementById(id) {
      if (!registry.has(id)) registry.set(id, makeEl(id));
      return registry.get(id);
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
    createElement(tag) { return makeEl(`__created__${tag}`); },
    body: { appendChild() {} },
    documentElement: { appendChild() {} },
  };
}

/**
 * @param {{knownFail?:boolean, deckEmpty?:boolean, wbFail?:boolean}} o
 *   knownFail  : GET /api/cards/known-lemmas 抛错（→ fetchKnownLemmas 降级）
 *   deckEmpty  : 本机 deck 为空（→ resolveDeck 必去拉镜像，制造降级的前提）
 *   wbFail     : GET /api/wb/state 抛错（→ resolveDeck 降级）
 */
function newEnv(o = {}) {
  const doc = makeDocumentStub();
  const net = { requests: [] };

  function api(url) {
    const u = String(url);
    net.requests.push(u);
    if (u === KNOWN_URL) {
      if (o.knownFail) return Promise.reject(new Error("Failed to fetch"));
      return Promise.resolve({ lemmas: ["Haus"] });
    }
    if (u === WB_URL) {
      if (o.wbFail) return Promise.reject(new Error("Failed to fetch"));
      return Promise.resolve({ words: [], cards: {} });
    }
    return Promise.reject(new Error(`桩 api 未覆盖的 URL：${u}`));
  }

  const storage = { getItem: () => null, setItem() {}, removeItem() {} };
  const sandbox = {
    console,
    document: doc,
    window: { localStorage: storage, innerHeight: 800 },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    Promise, Set, Map, Symbol, parseInt, parseFloat, isNaN, undefined,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController,
    api,
    __probeText: { id: 1, title: "T", level: "A2", source: "probe", content: "Haus Zug" },
    __probeAnnotate: ANNOTATE,
    // ── 被剥离模块的桩 ──
    esc: (s) => String(s == null ? "" : s),
    notify() {},
    playGermanAudio() {},
    loadDeck: () =>
      o.deckEmpty
        ? { words: [], cards: {} }
        : { words: [{ id: "l1", hw: "Haus" }], cards: { l1: { reps: 2 } } },
    mergeServerDeck: (d) => d,
    addCardToDeck: () => ({ deck: {} }),
    buildKnownSet: () => new Set(["haus"]),
    mergeKnownLemmas: (a) => a,
    // stats 由真 annotateWithDeck 形态给出（探针桩，探针只关心覆盖率行文案）
    annotateWithDeck: () => ({ sentences: ANNOTATE.sentences, stats: Object.assign({}, STATS) }),
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
  return { ctx, doc, net };
}

/** 跑一次详情渲染，回读覆盖率行的 innerHTML + title。 */
async function renderCoverageOf(env) {
  try {
    await vm.runInContext("renderTextDetailAnnotated(__probeText, __probeAnnotate)", env.ctx);
  } catch (e) {
    return { error: (e && e.message) || String(e) };
  }
  const el = env.doc.registry.get("enc-coverage");
  return { html: String(el.innerHTML), title: String(el.getAttribute("title") || "") };
}

const countOf = (s, sub) => s.split(sub).length - 1;
const MARK = "⚠";
const MARK_TEXT = "数据不完整";
/** 禁止出现在用户可见文案里的技术字面量（债 4 的头号验收点：MUST 是人话）。 */
const FORBIDDEN = [
  "fsrs_s", "fsrs", "lemmas", "lemma", "known-lemmas", "known_lemmas",
  "/api/", "wb/state", "cards/", "http://", "https://",
  "Failed to fetch", "TypeError", "undefined", "null", "NaN", "HTTP",
  "500", "502", "503", "504", "400", "404",
];

const problems = [];
const cases = [];
const record = (name, ok, msg) => {
  cases.push({ name, ok });
  if (!ok) problems.push(`[${name}] ${msg}`);
};

/* ══ B1 正常路径：不含降级标记 ════════════════════════════════════════════ */
const normal = await renderCoverageOf(newEnv());
record("B1-render", !normal.error && normal.html !== "",
  normal.error
    ? `renderTextDetailAnnotated 抛错：${normal.error}`
    : "覆盖率行为空（setCoverage 未写入 #enc-coverage）");
if (!normal.error) {
  const clean = !normal.html.includes(MARK) && !normal.html.includes(MARK_TEXT);
  record("B1", clean, `正常路径出现了降级标记：${JSON.stringify(normal.html)}`);
  record("B1-title", !normal.title, `正常路径不该有 title：${JSON.stringify(normal.title)}`);
}

/* ══ B5 正常路径文案逐字未变 ══════════════════════════════════════════════ */
if (!normal.error) {
  record("B5", normal.html === NORMAL_COPY,
    `正常路径文案被改动：实际 ${JSON.stringify(normal.html)}，期望 ${JSON.stringify(NORMAL_COPY)}`);
}

/* ══ B2 fetchKnownLemmas 失败 ⇒ 有标记、无技术字段名 ══════════════════════ */
const knownFail = await renderCoverageOf(newEnv({ knownFail: true }));
if (knownFail.error) {
  record("B2", false, `known-lemmas 失败时 renderTextDetailAnnotated 抛错：${knownFail.error}`);
} else {
  const marked = knownFail.html.includes(MARK) && knownFail.html.includes(MARK_TEXT);
  record("B2", marked,
    `known-lemmas 失败却没有降级标记：${JSON.stringify(knownFail.html)} / title=${JSON.stringify(knownFail.title)}`);
  const bad = FORBIDDEN.filter((f) => knownFail.html.includes(f) || knownFail.title.includes(f));
  record("B2-human-copy", bad.length === 0,
    `降级文案里出现技术字面量 ${JSON.stringify(bad)}：html=${JSON.stringify(knownFail.html)} title=${JSON.stringify(knownFail.title)}`);
  record("B2-title", knownFail.title.trim().length > 0,
    "降级时 title 为空（用户看不到原因）—— MUST NOT 留空白");
  record("B2-not-blank", !/\s{2,}/.test(knownFail.html.trim()),
    `降级行里有连续空白：${JSON.stringify(knownFail.html)}`);
}

/* ══ B3 resolveDeck 降级（本机空 + 镜像抛错）⇒ 有标记 ═════════════════════ */
const deckFail = await renderCoverageOf(newEnv({ deckEmpty: true, wbFail: true }));
if (deckFail.error) {
  record("B3", false, `镜像失败时 renderTextDetailAnnotated 抛错：${deckFail.error}`);
} else {
  const marked = deckFail.html.includes(MARK) && deckFail.html.includes(MARK_TEXT);
  record("B3", marked,
    `resolveDeck 降级却没有降级标记：${JSON.stringify(deckFail.html)} / title=${JSON.stringify(deckFail.title)}`);
  const bad = FORBIDDEN.filter((f) => deckFail.html.includes(f) || deckFail.title.includes(f));
  record("B3-human-copy", bad.length === 0,
    `降级文案里出现技术字面量 ${JSON.stringify(bad)}：html=${JSON.stringify(deckFail.html)} title=${JSON.stringify(deckFail.title)}`);
  record("B3-title", deckFail.title.trim().length > 0, "降级时 title 为空（用户看不到原因）");
}

/* ══ B4 两路都降级 ⇒ 标记只叠一份，title 给两条原因 ═══════════════════════ */
const both = await renderCoverageOf(newEnv({ knownFail: true, deckEmpty: true, wbFail: true }));
if (both.error) {
  record("B4", false, `两路都降级时抛错：${both.error}`);
} else {
  const m1 = countOf(both.html, MARK);
  const m2 = countOf(both.html, MARK_TEXT);
  record("B4-single-marker", m1 === 1 && m2 === 1,
    `两路降级时标记叠了多份：⚠ x${m1}、${MARK_TEXT} x${m2} —— ${JSON.stringify(both.html)}`);
  const bad = FORBIDDEN.filter((f) => both.html.includes(f) || both.title.includes(f));
  record("B4-human-copy", bad.length === 0,
    `降级文案里出现技术字面量 ${JSON.stringify(bad)}：html=${JSON.stringify(both.html)} title=${JSON.stringify(both.title)}`);
  record("B4-two-reasons", both.title.includes("；"),
    `title 没有并列给出两条原因：${JSON.stringify(both.title)}`);
}

/* ── 裁决 ─────────────────────────────────────────────────────────────────── */
const total = cases.length;
const failures = problems.length;
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ failures, total, cases }, null, 2) + "\n");
  if (failures) process.exit(1);
} else {
  for (const c of cases) console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}`);
  if (failures) {
    process.stderr.write(`覆盖率行降级标注契约破坏：\n  - ${problems.join("\n  - ")}\n`);
    process.exit(1);
  }
  console.log(`✅ PASS: 覆盖率行降级标注（${total} 项，正常路径文案逐字不变）`);
}
