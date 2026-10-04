/**
 * enc_degraded_concurrency_probe.mjs —— 覆盖率行「降级标注」的并发串味行为探针
 *
 * 缺陷（2026-10-05 清债轮 Task 3）：降级状态（`_knownDegraded` / `_deckDegraded`）是
 * **模块级全局**，而快照点（`renderTextDetailAnnotated` 里 `degradedSources()`）在
 * **详情渲染路径**上。当 `showView` 的 `resolveDeck()` 与详情的 `resolveDeck()`
 * 并发、且以**相反结果交错结束**时：
 *
 *   ① 用户进场 ⇒ showView 走 `resolveDeck()`，镜像请求 `GET /api/wb/state` **在飞**；
 *   ② 用户点了旧 DOM 上的卡片 ⇒ `openText` 又进**自己的** `resolveDeck()`，
 *      详情这次**成功**拿到镜像 deck（本地空 + 镜像有词 ⇒ 覆盖率本该正常）；
 *   ③ 详情还在等另一路 `fetchKnownLemmas()`，此刻①的镜像请求**失败**了 ⇒
 *      模块级 `_deckDegraded = true` 被**别人那次调用**写下；
 *   ④ 详情的两路都到齐 ⇒ 快照 `degradedSources()` 读到**③写下的 true** ⇒
 *      「详情拿到了自己的成功 deck，却显示『deck 降级』」—— 把成功谎报成失败。
 *
 * 本探针把 encounter.js + deck-bridge.js **真源码**剥 import/export 后进 node:vm 真跑
 * （不重抄实现），用**可手工控制的 deferred 请求桩**把上面的交错时序**精确摆出来**：
 * 第 1 次 `GET /api/wb/state` / `GET /api/cards/known-lemmas` 给列表，第 2 次给详情
 * （showView 先起 ⇒ 顺序确定），由探针决定谁先落地。
 *
 * 断言（S1 是本探针核心，修复前必红）：
 *   S1 串味：详情自己的 deck + known **都成功**，但并发的**列表**那次 resolveDeck 失败
 *      且失败落在详情快照**之前** ⇒ 覆盖率行 MUST **不含**降级标记。
 *      （前置校验：详情 DOM 里确有镜像已学词 ⇒ 证明详情那次 deck 真的成功了，
 *        不是「探针把两路都弄失败了」的假红。）
 *   S2 自身 deck 降级不丢：详情**自己**那次 resolveDeck 失败（并发的列表那次成功）
 *      ⇒ MUST 有标记 + title 有人话原因（防「只读到别人那次」）。
 *   S3 自身 known 降级不丢：详情**自己**那次 known-lemmas 失败 ⇒ MUST 有标记。
 *   S4 时序对照：同样的两个参与者，但列表的失败落在详情快照**之后**
 *      ⇒ 两版都应无标记（证明 S1 的红真由「交错顺序」造成，不是探针恒红）。
 *   S5 无并发基线：只有详情一路，两路都成功 ⇒ 无标记（回归护栏）。
 *   所有降级文案 MUST 是人话（禁 fsrs / lemmas / known-lemmas / /api/… / 状态码）。
 *
 * 用法：
 *   node tools/enc_degraded_concurrency_probe.mjs            # 人类可读
 *   node tools/enc_degraded_concurrency_probe.mjs --json     # {failures,total,cases:[…]}
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
const DECK_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "deck-bridge.js"), "utf8");

function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
}
const encCode = strip(ENC_SRC);
const deckCode = strip(DECK_SRC);
for (const [name, code] of [["encounter.js", encCode], ["deck-bridge.js", deckCode]]) {
  if (/^import\b/m.test(code)) {
    process.stderr.write(`${name} 剥离后仍有 import 行（探针转换器跟不上源码形态）\n`);
    process.exit(1);
  }
  if (/^\s*export\b/m.test(code)) {
    process.stderr.write(`${name} 剥离后仍有 export（探针转换器跟不上源码形态）\n`);
    process.exit(1);
  }
}

/* ── 夹具 ─────────────────────────────────────────────────────────────────────
 * 本机 deck **空**（⇒ resolveDeck 必去拉镜像，制造「两路各自有独立结果」的前提）。
 * 镜像带 2 个已学词 + 1 个未学词（reps=0）⇒ 可从详情 DOM 的 enc-known 反推详情词池。
 */
const MIRROR_DECK = {
  words: [
    { id: "m1", hw: "die Abfahrt" },
    { id: "m2", hw: "Fenster" },
    { id: "m3", hw: "Zug" },
  ],
  cards: { m1: { reps: 3 }, m2: { reps: 1 }, m3: { reps: 0 } },
};
/** 镜像里「已学」的两个 ⇒ 归一后词面（详情 deck 成功时 MUST 出现在 enc-known 里）。 */
const MIRROR_LEARNED = ["abfahrt", "fenster"];

const TEXTS = [{ id: 1, title: "TITLE-A", level: "A2", source: "probe", word_count: 3 }];
const ANNOTATE = {
  sentences: [
    {
      idx: 0,
      tokens: [
        { text: "Abfahrt", lemma: "Abfahrt", pos: "NOUN", known: false },
        { text: "Fenster", lemma: "Fenster", pos: "NOUN", known: false },
        { text: "Haus", lemma: "Haus", pos: "NOUN", known: false },
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

/** 手工控制的请求：探针决定它何时落地 / 何时炸。 */
function hold() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
/** 立刻成功（给定的值）的请求。 */
function give(value) {
  return { promise: Promise.resolve(value) };
}
const clone = (v) => JSON.parse(JSON.stringify(v));

function newEnv() {
  const doc = makeDocumentStub();
  /* wbQueue[i] / knownQueue[i] = 第 i+1 次该端点的请求；未配置 ⇒ 默认成功。
   * showView 先起 ⇒ 第 1 次归列表、第 2 次归详情（顺序由 waitFor 钉住）。 */
  const net = { requests: [], wbCalls: 0, knownCalls: 0, wbQueue: [], knownQueue: [] };

  function api(url) {
    const u = String(url);
    net.requests.push(u);
    if (u === "/api/encounter/texts") return Promise.resolve({ texts: TEXTS.map((t) => ({ ...t })) });
    if (u === "/api/encounter/texts/index")
      return Promise.resolve({ items: [{ id: 1, total_tokens: 4, lemma_seq: ["Abfahrt", "Fenster", "Haus", "und"] }] });
    if (u === "/api/cards/known-lemmas") {
      const slot = net.knownQueue[net.knownCalls];
      net.knownCalls++;
      return slot ? slot.promise : Promise.resolve({ lemmas: [] });
    }
    if (u === "/api/wb/state") {
      const slot = net.wbQueue[net.wbCalls];
      net.wbCalls++;
      return slot ? slot.promise : Promise.resolve(clone(MIRROR_DECK));
    }
    return Promise.reject(new Error(`桩 api 未覆盖的 URL：${u}`));
  }

  const sandbox = {
    console,
    document: doc,
    window: { localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, innerHeight: 800 },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    Promise, Set, Map, Symbol, parseInt, parseFloat, isNaN, undefined,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController,
    api,
    __probeText: { ...TEXTS[0], content: "Abfahrt Fenster Haus" },
    __probeAnnotate: ANNOTATE,
    // ── 被剥离模块的桩 ──
    esc: (s) => String(s == null ? "" : s),
    notify() {},
    playGermanAudio() {},
    rankEntries: (knownSet, merged) =>
      (merged || []).map((m) => ({ entry: m, available: true, band: "i1", rate: 0.5, topPick: true })),
    hasCoverage: () => true,
    loadRead: () => ({}),
    isRead: () => false,
    pickUnread: (ranked) => (ranked && ranked.length ? ranked[0] : null),
    markRead() {},
    PULL_ENDPOINT: "/api/encounter/pull-pack",
    normalizeDesktopBase: (s) => s,
    readDesktopBase: () => "",
    writeDesktopBase() {},
    mapPackRows: () => [],
    pullPackRequest: () => ({}),
  };

  const ctx = vm.createContext(sandbox);
  vm.runInContext(deckCode, ctx, { filename: "deck-bridge.js" });
  vm.runInContext(encCode, ctx, { filename: "encounter.js" });
  return { ctx, doc, net };
}

const sb = (ctx, expr) => vm.runInContext(expr, ctx);

/** 让 vm 里已经排好队的微任务/续体跑完（setImmediate 是宏任务 ⇒ 微任务先排空）。 */
const settle = async (rounds = 8) => {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setImmediate(r));
};

async function waitFor(cond, rounds = 60) {
  for (let i = 0; i < rounds; i++) {
    if (cond()) return true;
    await new Promise((r) => setImmediate(r));
  }
  return false;
}

/** 详情 DOM 里「真正被标成已学」的 lemma（小写排序）—— 详情 deck 成功与否的直接证据。 */
function detailKnownLemmas(doc) {
  const html = String(doc.registry.get("encounter-reader").innerHTML);
  const out = [];
  const re = /class="enc-tok enc-known"[^>]*data-lemma="([^"]*)"/g;
  let m;
  while ((m = re.exec(html)) !== null) out.push(m[1].toLowerCase());
  return out.sort();
}

function coverageOf(doc) {
  const el = doc.registry.get("enc-coverage");
  return { html: String(el.innerHTML), title: String(el.getAttribute("title") || "") };
}

const MARK = "⚠";
const MARK_TEXT = "数据不完整";
/** 禁止出现在用户可见文案里的技术字面量（MUST 是人话）。 */
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
const humanCopyViolations = (cov) =>
  FORBIDDEN.filter((f) => cov.html.includes(f) || cov.title.includes(f));

/* ══ S1 串味（核心，修复前必红）══════════════════════════════════════════════
 * 列表的镜像请求**晚于**详情 deck 成功、但**早于**详情快照失败 ⇒ 详情被别人的
 * 失败污名化：「拿到自己的成功 deck，却显示 deck 降级」。 */
{
  const { ctx, doc, net } = newEnv();
  const listWb = hold();                        // ① 列表那次镜像：在飞
  net.wbQueue[0] = listWb;
  net.wbQueue[1] = give(clone(MIRROR_DECK));    // ② 详情那次镜像：成功
  net.knownQueue[0] = give({ lemmas: [] });     // 列表的 known：成功（让 showView 走到 resolveDeck）
  const detailKnown = hold();                   // ③ 详情的 known：在飞（详情卡在这条上）
  net.knownQueue[1] = detailKnown;

  /* main.js 是 fire-and-forget 调 showView 的（不 await）⇒ 这里也必须不 await。 */
  const listP = sb(ctx, "showView()");
  const listFlying = await waitFor(() => net.wbCalls === 1);
  record("S1-夹具-列表在飞", listFlying,
    `列表没进自己的 resolveDeck（/api/wb/state 调用 ${net.wbCalls} 次，期望 1）—— 探针时序失控，结论不可信`);

  const detailP = sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  const bothFlying = await waitFor(() => net.wbCalls === 2 && net.knownCalls === 2);
  record("S1-夹具-详情在飞", bothFlying,
    `详情的两路没同时起到（wb=${net.wbCalls}, known=${net.knownCalls}，期望各 2）—— 探针时序失控`);

  /* ④ 列表的镜像失败 —— 落在详情快照**之前**。 */
  listWb.reject(new Error("Failed to fetch"));
  await settle();
  /* ⑤ 详情的 known 落地 ⇒ 详情的 Promise.all 解析 ⇒ 快照。 */
  detailKnown.resolve({ lemmas: [] });
  await settle();
  await Promise.allSettled([listP, detailP]);
  await settle();

  const pool = detailKnownLemmas(doc);
  record("S1-详情deck真成功", JSON.stringify(pool) === JSON.stringify(MIRROR_LEARNED),
    `详情那次 deck 没拿到镜像已学词（实际 ${JSON.stringify(pool)}，期望 ${JSON.stringify(MIRROR_LEARNED)}）` +
    ` —— 若详情自己就是失败的，本场景就没有串味可言，结论不可信`);

  const cov = coverageOf(doc);
  record("S1-覆盖行已渲染", cov.html.includes("已背词覆盖"),
    `覆盖率行没渲染出来：${JSON.stringify(cov.html)}`);
  record("S1", !cov.html.includes(MARK) && !cov.html.includes(MARK_TEXT),
    `详情自己的 deck + known 都成功，却被标了「${MARK_TEXT}」（并发串味：别人的失败写进了模块级状态）` +
    ` —— html=${JSON.stringify(cov.html)} title=${JSON.stringify(cov.title)}`);
  record("S1-title", !cov.title,
    `详情自己的两路都成功，却给了降级原因 title：${JSON.stringify(cov.title)}`);
}

/* ══ S2 自身 deck 降级 MUST 不丢（并发的列表那次是成功的）══════════════════ */
{
  const { ctx, doc, net } = newEnv();
  net.wbQueue[0] = give(clone(MIRROR_DECK));    // 列表那次：成功
  const detailWb = hold();                      // 详情那次：在飞 → 后失败
  net.wbQueue[1] = detailWb;
  net.knownQueue[0] = give({ lemmas: [] });
  net.knownQueue[1] = give({ lemmas: [] });

  const listP = sb(ctx, "showView()");
  await waitFor(() => net.wbCalls === 2);
  const detailP = sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  const flying = await waitFor(() => net.knownCalls === 2);
  record("S2-夹具-详情在飞", flying, `详情的 known 未起到（known=${net.knownCalls}）—— 探针时序失控`);

  detailWb.reject(new Error("Failed to fetch"));
  await settle();
  await Promise.allSettled([listP, detailP]);
  await settle();

  const cov = coverageOf(doc);
  record("S2", cov.html.includes(MARK) && cov.html.includes(MARK_TEXT),
    `详情**自己**那次 deck 失败，却没有降级标记（把状态绑错了调用 / 恒 false）` +
    ` —— html=${JSON.stringify(cov.html)}`);
  record("S2-title", cov.title.trim().length > 0, `降级时 title 为空（用户看不到原因）：${JSON.stringify(cov.title)}`);
  const bad = humanCopyViolations(cov);
  record("S2-人话", bad.length === 0,
    `降级文案里出现技术字面量 ${JSON.stringify(bad)}：html=${JSON.stringify(cov.html)} title=${JSON.stringify(cov.title)}`);
}

/* ══ S3 自身 known 降级 MUST 不丢 ══════════════════════════════════════════ */
{
  const { ctx, doc, net } = newEnv();
  net.wbQueue[0] = give(clone(MIRROR_DECK));
  net.wbQueue[1] = give(clone(MIRROR_DECK));
  net.knownQueue[0] = give({ lemmas: [] });     // 列表的 known：成功
  const detailKnown = hold();                   // 详情的 known：在飞 → 后失败
  net.knownQueue[1] = detailKnown;

  const listP = sb(ctx, "showView()");
  await waitFor(() => net.wbCalls === 2);
  const detailP = sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  const flying = await waitFor(() => net.knownCalls === 2);
  record("S3-夹具-详情在飞", flying, `详情的 known 未起到（known=${net.knownCalls}）—— 探针时序失控`);

  detailKnown.reject(new Error("Failed to fetch"));
  await settle();
  await Promise.allSettled([listP, detailP]);
  await settle();

  const pool = detailKnownLemmas(doc);
  record("S3-详情deck成功", JSON.stringify(pool) === JSON.stringify(MIRROR_LEARNED),
    `详情 deck 应成功（实际 ${JSON.stringify(pool)}）—— 夹具失配，S3 判据不可信`);
  const cov = coverageOf(doc);
  record("S3", cov.html.includes(MARK) && cov.html.includes(MARK_TEXT),
    `详情**自己**那次 known-lemmas 失败，却没有降级标记 —— html=${JSON.stringify(cov.html)}`);
  record("S3-title", cov.title.trim().length > 0, `降级时 title 为空：${JSON.stringify(cov.title)}`);
  const bad = humanCopyViolations(cov);
  record("S3-人话", bad.length === 0,
    `降级文案里出现技术字面量 ${JSON.stringify(bad)}：html=${JSON.stringify(cov.html)} title=${JSON.stringify(cov.title)}`);
}

/* ══ S4 时序对照：同样的两个参与者，列表失败落在详情快照**之后** ⇒ 都不标 ══ */
{
  const { ctx, doc, net } = newEnv();
  const listWb = hold();
  net.wbQueue[0] = listWb;
  net.wbQueue[1] = give(clone(MIRROR_DECK));
  net.knownQueue[0] = give({ lemmas: [] });
  const detailKnown = hold();
  net.knownQueue[1] = detailKnown;

  const listP = sb(ctx, "showView()");
  await waitFor(() => net.wbCalls === 1);
  const detailP = sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  await waitFor(() => net.wbCalls === 2 && net.knownCalls === 2);

  /* 与 S1 **唯一的区别**：先让详情落地（快照先发生），列表的失败后到。 */
  detailKnown.resolve({ lemmas: [] });
  await settle();
  await Promise.allSettled([detailP]);
  const snapshot = coverageOf(doc);
  record("S4-快照时未标记", !snapshot.html.includes(MARK),
    `快照时就有降级标记（列表还没失败呢）：${JSON.stringify(snapshot.html)} —— S1 的红可能是别的原因`);
  listWb.reject(new Error("Failed to fetch"));
  await settle();
  await Promise.allSettled([listP]);
  await settle();

  const pool = detailKnownLemmas(doc);
  record("S4-详情deck成功", JSON.stringify(pool) === JSON.stringify(MIRROR_LEARNED),
    `详情词池应为 ${JSON.stringify(MIRROR_LEARNED)}，实际 ${JSON.stringify(pool)}`);
  const cov = coverageOf(doc);
  record("S4", !cov.html.includes(MARK) && !cov.html.includes(MARK_TEXT),
    `列表失败落在快照之后，详情却被补标了降级：${JSON.stringify(cov.html)}`);
}

/* ══ S5 无并发基线：只有详情一路，两路都成功 ⇒ 无标记 ═════════════════════ */
{
  const { ctx, doc, net } = newEnv();
  net.wbQueue[0] = give(clone(MIRROR_DECK));
  net.knownQueue[0] = give({ lemmas: [] });
  try {
    await sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  } catch (e) {
    record("S5", false, `renderTextDetailAnnotated 抛错：${(e && e.message) || e}`);
  }
  await settle();
  const pool = detailKnownLemmas(doc);
  record("S5-详情deck成功", JSON.stringify(pool) === JSON.stringify(MIRROR_LEARNED),
    `详情词池应为 ${JSON.stringify(MIRROR_LEARNED)}，实际 ${JSON.stringify(pool)}`);
  const cov = coverageOf(doc);
  record("S5", !cov.html.includes(MARK) && !cov.html.includes(MARK_TEXT),
    `无并发且两路都成功，却标了降级：${JSON.stringify(cov.html)}`);
  record("S5-覆盖行", cov.html.includes("已背词覆盖"), `覆盖率行文案变了：${JSON.stringify(cov.html)}`);
  void net;
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
    process.stderr.write(`覆盖率降级标注的并发串味契约破坏：\n  - ${problems.join("\n  - ")}\n`);
    process.exit(1);
  }
  console.log(`✅ PASS: 降级状态与本次调用绑定（${total} 项，S1 串味场景不再误标）`);
}
