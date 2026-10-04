/**
 * enc_known_same_source_probe.mjs —— 遇见区「列表 / 详情」已知词池同源行为探针
 *
 * 缺陷（2026-10-04 子计划 3 Task 3）：详情 `renderTextDetailAnnotated` 的 deck 走
 * `resolveDeck()`（本机 localStorage → 空则拉 `GET /api/wb/state` 镜像 → 合并），
 * 而列表 `showView` 走的是裸 `loadDeck(encStorage())`（**只**本机）。
 * ⇒ 女友清过站点数据 / 换浏览器 profile / 跨设备（桌面用过工作台）时：
 *      列表 knownSet 为空 ⇒ i+1 徽章「偏难 0%」；
 *      详情拉到镜像   ⇒ 覆盖行「已背词覆盖 82%」。
 *   同一功能两个真相。
 *
 * 已有 `tests/test_encounter_ui_probes.py` 两条用例是**源码字符串切片断言**，只钉住
 * 「两处都调了 mergeKnownLemmas」，**测不到 deck 来源不同**；本探针补上这个盲区。
 *
 * 本探针把 encounter.js **真源码**（剥 import/export 后进 node:vm 真跑，不重抄实现）
 * 与 deck-bridge.js **真源码**（零 import 纯模块，同样剥 export 后同上下文真跑）
 * 放在同一个 context 里 ⇒ `resolveDeck` / `loadDeck` / `mergeServerDeck` /
 * `buildKnownSet` / `mergeKnownLemmas` / `annotateWithDeck` 全部是**真实现**，
 * 探针只桩 `api()`、localStorage、DOM 与 enc-i1/enc-read 的纯函数。
 *
 * 断言：
 *   A  同源（本探针核心，修复前必红）：本机 deck 为**空** + `GET /api/wb/state`
 *      返回含 2 个已学词的 deck ⇒ **列表** knownSet（经真 rankEntries 调用点捕获）
 *      MUST 含这 2 个词。
 *   B  不回归：本机 deck **非空** ⇒ 列表 knownSet 仍含本机词，且**不**请求镜像
 *      （resolveDeck 的 empty 判据短路，离线/在线行为逐字不变）。
 *   C  离线不炸：`GET /api/wb/state` 抛错 ⇒ showView 仍正常渲染列表（不整体失败），
 *      且 resolveDeck 静默回退本机 deck（不抛、不是空壳）。
 *   D  两端同源（防将来又分叉）：showView 与 renderTextDetailAnnotated 调的是**同一个**
 *      deck 解析函数（对 resolveDeck 打计数桩），且两端产出的已知词池**逐字相等**。
 *   E  复用阶梯：encounter.js 内 `"/api/wb/state"` 字面量 MUST 只出现在 resolveDeck 一处
 *      （MUST NOT 新写第二份镜像兜底）。
 *
 * 用法：
 *   node tools/enc_known_same_source_probe.mjs            # 人类可读
 *   node tools/enc_known_same_source_probe.mjs --json     # stdout 只输出 JSON
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
const DECK_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "deck-bridge.js"), "utf8");

/* 剥 import（跨行多行具名导入）/ export 前缀。deck-bridge.js 零 import，只剥 export。 */
function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
}
const encCode = strip(ENC_SRC);
const deckCode = strip(DECK_SRC);
for (const [name, code] of [["encounter.js", encCode], ["deck-bridge.js", deckCode]]) {
  if (/^import\b/m.test(code)) fail(`${name} 剥离后仍有 import 行（探针转换器跟不上源码形态）`);
  if (/^\s*export\b/m.test(code)) fail(`${name} 剥离后仍有 export（探针转换器跟不上源码形态）`);
}

/* ── 夹具 ─────────────────────────────────────────────────────────────────────
 * deck 形状遵循 deck-bridge 的真契约：
 *   loadDeck  -> {words:[{id,hw}], cards:{[String(id)]:{reps}}}
 *   buildKnownSet 只收「word 存在 且 cards[id].reps > 0」的词，并剥冠词 + 小写。
 */
const LOCAL_WORDS = [{ id: "l1", hw: "Haus" }];
const LOCAL_CARDS = { l1: { reps: 2 } };

/** 工作台镜像：2 个已学词（其一带冠词，验归一口径）、1 个未学词（reps=0）。 */
const MIRROR_DECK = {
  words: [
    { id: "m1", hw: "die Abfahrt" },
    { id: "m2", hw: "Fenster" },
    { id: "m3", hw: "Zug" },
  ],
  cards: { m1: { reps: 3 }, m2: { reps: 1 }, m3: { reps: 0 } },
};
/** 镜像里「已学」的两个 ⇒ 归一后词面。 */
const MIRROR_LEARNED = ["abfahrt", "fenster"];

const TEXTS = [{ id: 1, title: "TITLE-A", level: "A2", source: "probe", word_count: 3 }];

/** 详情 annotate：两个镜像已学词 + 一个两侧都未学的词 ⇒ 可从 DOM 的 enc-known/enc-unk 反推详情词池。 */
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

function makeStorage(words, cards) {
  const data = new Map();
  if (words) data.set("wb.words.v1", JSON.stringify(words));
  if (cards) data.set("wb.cards.v1", JSON.stringify(cards));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem() {},
    removeItem() {},
  };
}

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

const DOM_IDS = [
  "encounter-text-list", "encounter-reader", "enc-coverage", "enc-i1-hint",
  "enc-popover", "enc-review", "enc-review-toggle", "enc-add-error",
  "encounter-add-form", "encounter-pull-panel", "encounter-pull-log", "encounter-pull-base",
];

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
 * 一次场景一个独立环境（模块级 _openSeq / _openCtrl / resolveDeck 计数互不污染）。
 * @param {{localWords?:any[], localCards?:object, wbState?: "mirror"|"throw"|"forbid"}} o
 */
function newEnv(o = {}) {
  const doc = makeDocumentStub();
  const net = { requests: [], wbState: o.wbState || "mirror" };
  const captured = { listKnownSets: [] };

  function api(url) {
    const u = String(url);
    net.requests.push(u);
    if (u === "/api/encounter/texts") return Promise.resolve({ texts: TEXTS.map((t) => ({ ...t })) });
    if (u === "/api/encounter/texts/index")
      return Promise.resolve({ items: [{ id: 1, total_tokens: 4, lemma_seq: ["Abfahrt", "Fenster", "Haus", "und"] }] });
    if (u === "/api/cards/known-lemmas") return Promise.resolve({ lemmas: [] });
    if (u === "/api/wb/state") {
      if (net.wbState === "throw") return Promise.reject(new Error("Failed to fetch"));
      if (net.wbState === "forbid") return Promise.reject(new Error("镜像端点不该被请求"));
      return Promise.resolve(JSON.parse(JSON.stringify(MIRROR_DECK)));
    }
    return Promise.reject(new Error(`桩 api 未覆盖的 URL：${u}`));
  }

  const sandbox = {
    console,
    document: doc,
    window: { localStorage: makeStorage(o.localWords, o.localCards), innerHeight: 800 },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    Promise, Set, Map, Symbol, parseInt, parseFloat, isNaN, undefined,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController,
    api,
    /* D 场景直接调 renderTextDetailAnnotated 的入参（不经 openText，隔离竞态守卫）。 */
    __probeText: { ...TEXTS[0], content: "Abfahrt Fenster Haus" },
    __probeAnnotate: ANNOTATE,
    // ── 被剥离模块的桩（core.js / player.js / enc-i1.js / enc-read.js / encounter-pull.js）──
    esc: (s) => String(s == null ? "" : s),
    notify() {},
    playGermanAudio() {},
    /* 观察点：列表 knownSet 就是真源码传给 rankEntries 的第一个实参 —— 不重抄计算。 */
    rankEntries: (knownSet, merged) => {
      captured.listKnownSets.push(Array.from(knownSet).map(String).sort());
      return (merged || []).map((m) => ({ entry: m, available: true, band: "i1", rate: 0.5, topPick: true }));
    },
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
  /* 先跑 deck-bridge 真源码（零 import 纯模块）→ encounter.js 里的 loadDeck /
   * mergeServerDeck / buildKnownSet / mergeKnownLemmas / annotateWithDeck /
   * addCardToDeck / DECK_KEYS 全部解析到真实现。 */
  vm.runInContext(deckCode, ctx, { filename: "deck-bridge.js" });
  vm.runInContext(encCode, ctx, { filename: "encounter.js" });
  /* 对 resolveDeck 打计数桩（模块内调用按全局名解析 ⇒ 换掉绑定即可观测）。
   * D 场景据此断言「两端走的是同一个 deck 解析函数」。 */
  vm.runInContext(
    "globalThis.__resolveDeckCalls = 0;" +
    "globalThis.__realResolveDeck = resolveDeck;" +
    "resolveDeck = function () {" +
    "  globalThis.__resolveDeckCalls++;" +
    "  return globalThis.__realResolveDeck.apply(null, arguments);" +
    "};",
    ctx,
    { filename: "resolveDeck-spy.js" }
  );
  return { ctx, doc, net, captured, sandbox };
}

const sb = (ctx, expr) => vm.runInContext(expr, ctx);
const listHtml = (doc) => String(doc.registry.get("encounter-text-list").innerHTML);
const readerHtml = (doc) => String(doc.registry.get("encounter-reader").innerHTML);
const resolveDeckCalls = (ctx) => Number(sb(ctx, "globalThis.__resolveDeckCalls"));

/** 从详情渲染出的 DOM 反推「详情端真正认为已学」的 lemma 集合（小写排序）。 */
function detailKnownLemmas(doc) {
  const html = readerHtml(doc);
  const out = [];
  const re = /class="enc-tok enc-known"[^>]*data-lemma="([^"]*)"/g;
  let m;
  while ((m = re.exec(html)) !== null) out.push(m[1].toLowerCase());
  return out.sort();
}

/**
 * 跑 showView 并把「整体抛错」转成可读断言。
 * ⚠ 不可直接 `await showView()`：一旦实现回退成「镜像失败即抛」，未捕获的 rejection
 * 会让 node 直接崩在栈上（退出码虽为 1，但看不到是哪条契约被破坏 ⇒ 不可诊断）。
 */
async function runShowView(ctx, label) {
  try {
    await sb(ctx, "showView()");
    return null;
  } catch (e) {
    return `${label} showView 整体抛错：${(e && e.message) || e} —— 列表渲染被 deck 解析连累了`;
  }
}

/**
 * 切出 `function <name>(...) { ... }` 整段（按大括号配对，跳过字符串/模板串）。
 * 传入的源码 MUST 已去注释（否则注释里的示例调用会被误判为真实调用点）。
 */
function sliceFunction(src, name) {
  const m = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(src);
  if (!m) return "";
  const open = src.indexOf("{", m.index);
  let depth = 0;
  let quote = null;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return src.slice(m.index, i + 1);
    }
  }
  return "";
}

const problems = [];
/** 只收非空问题（runShowView 成功时返回 null）。 */
const note = (m) => { if (m) problems.push(m); };

/* ══ A 同源核心：本机空 + 镜像有 2 个已学词 ⇒ 列表 knownSet MUST 含这 2 个 ══════ */
{
  const { ctx, doc, net, captured } = newEnv({ localWords: null, localCards: null });
  note(await runShowView(ctx, "[A]"));

  if (captured.listKnownSets.length !== 1) {
    problems.push(`[A] 夹具失配：rankEntries 被调 ${captured.listKnownSets.length} 次（期望 1），探针不可信`);
  }
  const known = captured.listKnownSets[0] || [];
  const missing = MIRROR_LEARNED.filter((w) => !known.includes(w));
  if (missing.length) {
    problems.push(
      `[A] 列表 knownSet 缺镜像已学词 ${JSON.stringify(missing)}（实际 ${JSON.stringify(known)}）—— ` +
      `列表的 deck 仍只读本机 localStorage，没走 resolveDeck 的镜像兜底 ⇒ 列表说「偏难 0%」而详情说「已覆盖 82%」`,
    );
  }
  if (known.includes("zug")) problems.push("[A] 列表把 reps=0 的未学词算成已学（buildKnownSet 真实现被绕开了？）");
  if (!net.requests.includes("/api/wb/state")) {
    problems.push("[A] showView 根本没请求 GET /api/wb/state —— 列表未复用 resolveDeck");
  }
  if (!listHtml(doc).includes("TITLE-A")) problems.push("[A] 夹具失配：列表未渲染");
}

/* ══ B 不回归：本机非空 ⇒ 用本机词，且不请求镜像 ═════════════════════════════ */
{
  const { ctx, doc, net, captured } = newEnv({ localWords: LOCAL_WORDS, localCards: LOCAL_CARDS });
  note(await runShowView(ctx, "[B]"));

  const known = captured.listKnownSets[0] || [];
  if (!known.includes("haus")) {
    problems.push(`[B] 列表 knownSet 丢了本机已学词 haus（实际 ${JSON.stringify(known)}）—— 改用 resolveDeck 造成回归`);
  }
  if (net.requests.includes("/api/wb/state")) {
    problems.push("[B] 本机 deck 非空时仍请求了 GET /api/wb/state —— resolveDeck 的 empty 短路失效，多烧一次往返");
  }
  if (!listHtml(doc).includes("TITLE-A")) problems.push("[B] 夹具失配：列表未渲染");
}

/* ══ C 离线不炸：镜像抛错 ⇒ 列表照常渲染 + resolveDeck 静默回退本机 ═══════════ */
{
  /* 本机「有词、无卡」⇒ resolveDeck 的 empty 判据（words 空 **或** cards 空）成立
   * ⇒ 必去拉镜像；镜像抛错后 MUST 静默回退本机 deck（MUST NOT 让整个列表渲染失败）。 */
  const { ctx, doc, net, captured } = newEnv({ localWords: LOCAL_WORDS, localCards: null, wbState: "throw" });
  note(await runShowView(ctx, "[C]"));

  if (!net.requests.includes("/api/wb/state")) {
    problems.push("[C] 夹具失配：本机无卡时未触发镜像拉取（empty 判据没生效），探针不可信");
  }
  if (!listHtml(doc).includes("TITLE-A")) {
    problems.push("[C] 镜像拉取抛错后整个列表渲染失败了（showView 抛/提前 return）—— 离线 MUST NOT 连累列表");
  }
  if (listHtml(doc).includes("加载遇见区列表失败")) {
    problems.push("[C] 列表上屏的是「加载遇见区列表失败」—— 镜像失败被当成了列表失败");
  }
  if (captured.listKnownSets.length !== 1) problems.push("[C] 夹具失配：rankEntries 未被调用");
  /* resolveDeck 自身：镜像失败 ⇒ 静默回退**本机 deck**（不抛、不是空壳） */
  let fellBack = null;
  try {
    fellBack = JSON.parse(
      await sb(
        ctx,
        "globalThis.__realResolveDeck().then(function (d) { return JSON.stringify({ words: d.words.length, cards: Object.keys(d.cards).length }); })",
      ),
    );
  } catch (e) {
    problems.push(`[C] 镜像失败后 resolveDeck 直接抛错（${(e && e.message) || e}）而不是静默回退本机 deck`);
  }
  if (fellBack && (fellBack.words !== LOCAL_WORDS.length || fellBack.cards !== 0)) {
    problems.push(`[C] 镜像失败后 resolveDeck 没有回退本机 deck（实际 ${JSON.stringify(fellBack)}，期望 words=${LOCAL_WORDS.length}, cards=0）`);
  }
}

/* ══ D 两端同源：同一个解析函数 + 逐字相等的词池 ═════════════════════════════ */
{
  const { ctx, doc, net, captured } = newEnv({ localWords: null, localCards: null });
  note(await runShowView(ctx, "[D]"));
  const afterList = resolveDeckCalls(ctx);
  if (afterList !== 1) {
    problems.push(`[D] showView 期间 resolveDeck 被调 ${afterList} 次（期望 1）—— 列表没走这个 deck 解析函数`);
  }
  try {
    await sb(ctx, "renderTextDetailAnnotated(__probeText, __probeAnnotate)");
  } catch (e) {
    problems.push(`[D] renderTextDetailAnnotated 抛错：${(e && e.message) || e}`);
  }
  const afterDetail = resolveDeckCalls(ctx);
  if (afterDetail !== 2) {
    problems.push(`[D] renderTextDetailAnnotated 期间 resolveDeck 累计 ${afterDetail} 次（期望 2）—— 详情没走同一个解析函数`);
  }
  if (!net.requests.includes("/api/wb/state")) problems.push("[D] 夹具失配：镜像端点未被请求");

  const listPool = captured.listKnownSets[0] || [];
  const detailPool = detailKnownLemmas(doc);
  if (JSON.stringify(listPool) !== JSON.stringify(detailPool)) {
    problems.push(
      `[D] 两端词池不相等：列表 ${JSON.stringify(listPool)} vs 详情 ${JSON.stringify(detailPool)} —— ` +
      `同一功能两个真相`,
    );
  }
  if (listPool.length !== MIRROR_LEARNED.length) {
    problems.push(`[D] 夹具失配：合并后的词池应为 ${JSON.stringify(MIRROR_LEARNED)}，实际 ${JSON.stringify(listPool)}`);
  }
}

/* ══ E 复用阶梯：**读**镜像的调用点 MUST 只有 resolveDeck 一处 ════════════════ */
{
  /* 只数 `api("/api/wb/state")`（GET 读镜像）这一形态的调用点。
   * ⚠ 不可退化成「全文子串 in」：encounter.js 另有一处 `/api/wb/state` 字面量
   *（encounter.js:1172 局域网配对的 **PUT 写**镜像目标，与 deck 解析无关），
   * 全文计数会恒 ≥ 2 而无判别力。 */
  const srcNoComment = ENC_SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/[^\n]*/g, "$1");
  const readCall = /api\(\s*["'`]\/api\/wb\/state["'`]\s*\)/g;
  const hits = srcNoComment.match(readCall) || [];
  if (hits.length !== 1) {
    problems.push(
      `[E] encounter.js 内读镜像调用点 api("/api/wb/state") 出现 ${hits.length} 次（期望 1）—— ` +
      `MUST 复用 resolveDeck，MUST NOT 新写第二份镜像兜底`,
    );
  }
  if (!/async\s+function\s+resolveDeck\s*\(/.test(ENC_SRC)) {
    problems.push("[E] encounter.js 不再有 resolveDeck —— 复用阶梯被拆掉了");
  }
  /* showView 体内 MUST NOT 出现裸 loadDeck( —— 列表只能经 resolveDeck 拿 deck。 */
  const showViewBody = sliceFunction(srcNoComment, "showView");
  if (/loadDeck\s*\(/.test(showViewBody)) {
    problems.push("[E] showView 体内仍有裸 loadDeck( 调用 —— 列表绕过了 resolveDeck（两端会再次分叉）");
  }
}

/* ── 裁决 ─────────────────────────────────────────────────────────────────── */
if (problems.length) {
  fail(`遇见区列表/详情 known 池同源契约破坏（子计划 3 Task 3）：\n  - ${problems.join("\n  - ")}`);
}

const out = {
  ok: true,
  A: "同源：本机空 + 镜像 2 词 ⇒ 列表 knownSet 含这 2 词",
  B: "不回归：本机非空 ⇒ 用本机词且不请求镜像",
  C: "离线：镜像抛错 ⇒ 列表照常渲染，resolveDeck 静默回退本机 deck",
  D: "两端同源：同一 resolveDeck + 词池逐字相等",
  E: "复用阶梯：读镜像调用点 api(\"/api/wb/state\") 仅 1 处 + showView 无裸 loadDeck(",
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  for (const k of ["A", "B", "C", "D", "E"]) console.log(`${k}: ${out[k]}`);
  console.log("✅ PASS: 遇见区列表与详情共用同一 deck 解析（本机 → 镜像兜底 → 合并）");
}
