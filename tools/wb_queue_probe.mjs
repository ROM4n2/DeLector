/**
 * wb_queue_probe.mjs —— 背词工作台「设置即时生效 / 范围切换」行为级动态探针（ADR-0002 Task 6）
 *
 * 静态正则只能证明「代码长这样」：能证明 renormalizeQueueTail() 存在、revIdx 不被赋值，
 * 证明不了「dailyNew 15→30 之后尾部真的从 10 个新词变成 25 个」。
 * 本探针把 static/german/workbench.html 里的 **真实源码**（SEED_WORDS / CORE_* 常量、
 * inScopeWord / logToday / buildReviewQueue / refilterReviewQueueForScope /
 * renormalizeQueueTail / extraNewWords / renderReview / renderWords 过滤谓词）
 * 按括号配对整段切出来，丢进 node:vm 沙箱真跑，再把结果打成 JSON 给 pytest 断言。
 *
 * 硬约束（与 tools/wb_merge_probe.mjs 同款）：
 *   - 探针里**不得重抄一份被测实现**。重抄的话实现回退了探针照样绿 —— 死测。
 *     本文件只提供 $ / document / toast / showCard / renderHeaderBadge 等纯 UI 桩
 *     与 __setup / __snapshot 等**夹具**代码；一切被测逻辑均来自 workbench.html 切片。
 *   - 切片护栏：切出来的东西必须带标志性 token（renormalizeQueueTail 必须含
 *     manualExtraIds；refilterReviewQueueForScope 必须**不含** renormalizeQueueTail）。
 *     切歪直接抛错退出码非 0，不许静默假绿。
 *
 * 用法：node tools/wb_queue_probe.mjs [--json]
 *   --json 时 stdout 只有一个 JSON 对象，日志一律走 stderr，退出码 0。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const HTML = path.join(ROOT, "static", "german", "workbench.html");
const JSON_MODE = process.argv.includes("--json");

const log = (...a) => { if (!JSON_MODE) console.error(...a); };

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整声明/函数体（跳过字符串与注释）
 * ------------------------------------------------------------------------ */

const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

/** 从 openIdx（必须是一个开括号）扫到配对的闭括号，返回闭括号下标。
 *  扫描时跳过 '..' / ".." / `..` 字符串与 // 、 /* 注释，避免被词条正文里的括号带偏。 */
function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号（${src[openIdx]}）`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      i++;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === quote) break;
        i++;
      }
      i++;
      continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (OPEN[c]) { stack.push(c); i++; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i++;
      continue;
    }
    i++;
  }
  throw new Error(`matchBracket: 从 ${openIdx} 起找不到配对闭括号`);
}

/** 抽取一条顶层的 `const NAME = <{...}|[...]|new X(...)>;` 声明（含结尾分号）。 */
function extractDecl(src, name) {
  const anchor = new RegExp(`^const\\s+${name}\\s*=`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到声明 const ${name}`);
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  const semi = src.indexOf(";", end);
  if (semi < 0 || semi > end + 8) throw new Error(`const ${name} 声明结尾找不到分号，切歪了`);
  return src.slice(m.index, semi + 1);
}

/** 抽取一个完整函数声明 `function name(...) { ... }`。 */
function extractFn(src, name) {
  const anchor = new RegExp(`^function\\s+${name}\\s*\\(`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到函数 ${name}`);
  const parenOpen = src.indexOf("(", m.index);
  const parenClose = matchBracket(src, parenOpen);
  const braceOpen = src.indexOf("{", parenClose);
  const braceClose = matchBracket(src, braceOpen);
  return src.slice(m.index, braceClose + 1);
}

/** 抽取一整行顶层语句（给 `const pad2 = (n) => ...;` 这类单行箭头声明用，
 *  extractDecl 的括号配对会停在参数表 `(n)` 上，对箭头声明不适用）。 */
function extractLine(src, re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到 ${what}`);
  const line = m[0].trim();
  if (!line.endsWith(";")) throw new Error(`${what} 不是完整单行语句：${line.slice(0, 60)}`);
  return line;
}

const html = fs.readFileSync(HTML, "utf8");

/* renderWords 里那条过滤谓词：`S.words.filter( w => { ... } )` 的实参整段。
 * 它是 Task 3「搜索旁路 scope」的唯一落点，必须切真源码而不是重写一份判定。 */
function extractWordsPredicate(src) {
  const body = extractFn(src, "renderWords");
  const at = body.indexOf("S.words.filter(");
  if (at < 0) throw new Error("renderWords 里找不到 S.words.filter(，过滤链被挪走了");
  const paren = body.indexOf("(", at + "S.words.filter".length - 1);
  const pred = body.slice(paren, matchBracket(body, paren) + 1).slice(1, -1).trim();
  if (!pred.startsWith("w =>")) throw new Error(`切出来的不是 renderWords 的过滤谓词：${pred.slice(0, 60)}`);
  return pred;
}

/** renderWords 里的 `const q = wordFilters.q.toLowerCase();` —— 谓词闭包依赖它。 */
function extractWordsQLine(src) {
  const body = extractFn(src, "renderWords");
  const m = /^\s*const q = .*;$/m.exec(body);
  if (!m) throw new Error("renderWords 里找不到 const q = ... 行");
  const line = m[0].trim();
  if (!/wordFilters\.q/.test(line)) throw new Error(`const q 行不读 wordFilters.q，切歪了：${line}`);
  return line;
}

const WORDS_PREDICATE = extractWordsPredicate(html);
const WORDS_Q_LINE = extractWordsQLine(html);

const PIECES = {
  /* 通用 helper（一律切真源码：wordState 的分档直接决定 wordFilters.state 那几条过滤，
   * 写个桩就等于把被测逻辑换掉了） */
  pad2: extractLine(html, /^const pad2 = .*$/m, "pad2"),
  todayStr: extractFn(html, "todayStr"),
  endToday: extractFn(html, "endToday"),
  fmtMD: extractFn(html, "fmtMD"),
  shuffle: extractFn(html, "shuffle"),
  /* 词表常量 */
  CORE_WORD_SEED_IDS: extractDecl(html, "CORE_WORD_SEED_IDS"),
  CORE_CUSTOM_WORDS: extractDecl(html, "CORE_CUSTOM_WORDS"),
  SEED_WORDS: extractDecl(html, "SEED_WORDS"),
  /* 状态 + scope 判定 */
  wordFilters: extractDecl(html, "wordFilters"),
  wordById: extractFn(html, "wordById"),
  inScopeWord: extractFn(html, "inScopeWord"),
  logToday: extractFn(html, "logToday"),
  wordState: extractFn(html, "wordState"),
  /* 被测队列逻辑 */
  buildReviewQueue: extractFn(html, "buildReviewQueue"),
  injectWrongWords: extractFn(html, "injectWrongWords"),
  refilterReviewQueueForScope: extractFn(html, "refilterReviewQueueForScope"),
  manualExtraIds: extractDecl(html, "manualExtraIds"),
  renormalizeQueueTail: extractFn(html, "renormalizeQueueTail"),
  extraNewWords: extractFn(html, "extraNewWords"),
  queueInfoText: extractFn(html, "queueInfoText"),
  renderReview: extractFn(html, "renderReview"),
  renderWordsPredicate: WORDS_PREDICATE,
};

/* ---------------------------------------------------------------------------
 * 2. 切片护栏：切歪直接抛，不许在一个残缺实现上得出「行为正确」的结论
 * ------------------------------------------------------------------------ */

const GUARDS = [
  ["renormalizeQueueTail 必须含手动追加豁免 manualExtraIds",
    () => /manualExtraIds/.test(PIECES.renormalizeQueueTail)],
  ["renormalizeQueueTail 必须读 S.settings.dailyNew 配额",
    () => /S\.settings\.dailyNew/.test(PIECES.renormalizeQueueTail)],
  ["renormalizeQueueTail 不得调 buildReviewQueue（会重置 revIdx）",
    () => !/buildReviewQueue/.test(PIECES.renormalizeQueueTail)],
  ["refilterReviewQueueForScope 不得含 renormalizeQueueTail（ADR 3.6 切范围不补齐）",
    () => !/renormalizeQueueTail/.test(PIECES.refilterReviewQueueForScope)],
  ["refilterReviewQueueForScope 必须做 inScopeWord 过滤",
    () => /inScopeWord/.test(PIECES.refilterReviewQueueForScope)],
  ["buildReviewQueue 必须重置 revIdx（scope 场景 6 靠它区分「重建 vs 尾部手术」）",
    () => /revIdx\s*=\s*0/.test(PIECES.buildReviewQueue)],
  ["renderReview 必须带「本轮刷完就重建」那道门",
    () => /revIdx >= revQueue\.length/.test(PIECES.renderReview)
       && /buildReviewQueue\(\)/.test(PIECES.renderReview)],
  ["renderReview 切片不得越界吞掉 showCard",
    () => !/function showCard/.test(PIECES.renderReview)],
  ["extraNewWords 必须登记豁免 id",
    () => /manualExtraIds\.add/.test(PIECES.extraNewWords)],
  ["renderWords 谓词必须含 scope 过滤与搜索前提",
    () => /wordFilters\.scope/.test(WORDS_PREDICATE) && /!q/.test(WORDS_PREDICATE)],
  ["renderWords 谓词必须含 wordState 分档（切少了就等于换掉了被测逻辑）",
    () => /wordState\(/.test(WORDS_PREDICATE)],
  ["inScopeWord 必须以 wordFilters.scope 为唯一 truth source",
    () => /wordFilters\.scope/.test(PIECES.inScopeWord)],
  ["SEED_WORDS 切片长度异常",
    () => PIECES.SEED_WORDS.length > 100000],
];

for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 25) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
  log(`[slice] ${k}: ${v.length} 字节`);
}
for (const [why, ok] of GUARDS) {
  if (!ok()) throw new Error(`切片护栏失败：${why}`);
}
log(`[guard] ${GUARDS.length} 条切片护栏通过`);

/* ---------------------------------------------------------------------------
 * 3. 沙箱：纯 UI 桩 + 夹具。被测逻辑一行都不在这里。
 * ------------------------------------------------------------------------ */

const PRELUDE = `
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: { retention: 0.9, dailyNew: 15, newOrder: "seed" } };
var revQueue = [], revIdx = 0, ratedCount = 0, flipped = false, queueDay = null, curView = "review";
var __toasts = [];
var __els = {};
function $(id) {
  if (!__els[id]) __els[id] = {
    id: id, style: {}, dataset: {}, disabled: false, checked: false,
    textContent: "", innerHTML: "", value: "",
    classList: { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } },
    querySelectorAll: function () { return []; },
    addEventListener: function () {},
    closest: function () { return null; }
  };
  return __els[id];
}
var document = { createElement: function () { return $("__tmp" + Math.random()); }, querySelectorAll: function () { return []; } };
function toast(m) { __toasts.push(String(m)); }
function saveWords() {} function saveCards() {} function saveLog() {}
function saveWrong() {} function saveSettings() {}
/* 纯展示，不动队列状态：showCard 只读 revQueue[revIdx] 往 DOM 上刷字，
 * renderHeaderBadge 只算徽标文案。桩掉它们不会改变任何被测行为。 */
function showCard() {}
function renderHeaderBadge() {}
function renderWords() {}
function playWord() { return Promise.resolve({ ok: true }); }
`;

/* buildReviewQueue 调用计数器：场景 6 要分辨「尾部手术」和「整队重建」，
 * 光看 revIdx 归零推不出是谁干的。这里只包一层计数，转手调真实现。 */
const INSTRUMENT = `
var __buildCalls = 0;
const __realBuildReviewQueue = buildReviewQueue;
buildReviewQueue = function () { __buildCalls++; return __realBuildReviewQueue.apply(null, arguments); };
`;

/* 夹具：构造 S.words / S.cards / 今日日志 / 队列初态，以及取快照。
 * 这里没有任何被测逻辑 —— 队列一律由真实 buildReviewQueue() 生成。 */
const FIXTURE = `
function __freshWords() {
  return SEED_WORDS.map(function (w) {
    return {
      id: w.id, hw: w.hw, pos: w.pos || "", gloss: w.gloss || "",
      ipa: w.ipa || "", ex: Array.isArray(w.ex) ? w.ex : [], letter: w.letter || "",
      page: w.page || 0, tags: CORE_WORD_SEED_IDS.has(w.id) ? ["core"] : [],
      custom: false, up: 0
    };
  }).concat(CORE_CUSTOM_WORDS.map(function (w) {
    return Object.assign({}, w, { tags: ["core"], custom: true, up: w.up || 0 });
  }));
}
/** 到期卡取词表**末尾**若干词：newOrder="seed" 时新词池从表头取，两端不打架。 */
function __setup(cfg) {
  S.words = __freshWords();
  S.cards = {}; S.log = {}; S.wrong = {};
  S.settings = { retention: 0.9, dailyNew: cfg.dailyNew, newOrder: cfg.newOrder };
  var now = Date.now();
  for (var i = 0; i < cfg.dueCount; i++) {
    var w = S.words[S.words.length - 1 - i];
    S.cards[w.id] = { reps: 3, s: 4.2, d: 5.1, due: now - (i + 1) * 3600000, last: now - 86400000 };
  }
  logToday().nw = cfg.todayNw;
  wordFilters.q = ""; wordFilters.letter = ""; wordFilters.tag = "";
  wordFilters.diff = ""; wordFilters.state = ""; wordFilters.scope = cfg.scope;
  curView = cfg.curView;
  manualExtraIds.clear();
  revQueue = []; revIdx = 0; ratedCount = 0; queueDay = null; __toasts.length = 0;
  buildReviewQueue();
  queueDay = todayStr();
  revIdx = cfg.revIdx === "finished" ? revQueue.length : cfg.revIdx;
  ratedCount = revIdx;
  __buildCalls = 0;
  return __snapshot();
}
function __isNew(id) { return !S.cards[id]; }
function __tail() { return revQueue.slice(revIdx + 1); }
function __snapshot() {
  var tail = __tail();
  return {
    queueLen: revQueue.length,
    revIdx: revIdx,
    ratedCount: ratedCount,
    queueDay: queueDay,
    buildCalls: __buildCalls,
    head: JSON.stringify(revQueue.slice(0, revIdx + 1)),
    queue: JSON.stringify(revQueue),
    tailNew: tail.filter(__isNew).length,
    tailDue: tail.filter(function (id) { return !!S.cards[id]; }).length,
    tailNewIds: tail.filter(__isNew),
    tailNonCore: tail.filter(function (id) { return !inScopeWord(wordById(id)); }).length,
    newInQueue: revQueue.filter(__isNew).length,
    nonCoreInQueue: revQueue.filter(function (id) { return !inScopeWord(wordById(id)); }).length,
    pinnedInQueue: revQueue.filter(function (id) { return manualExtraIds.has(id); }).length,
    normalNewInTail: tail.filter(function (id) { return __isNew(id) && !manualExtraIds.has(id); }).length,
    quota: Math.max(0, S.settings.dailyNew - (logToday().nw || 0))
  };
}
function __setDailyNew(v) { S.settings.dailyNew = v; renormalizeQueueTail(); return __snapshot(); }
function __switchScope(next) { wordFilters.scope = next; refilterReviewQueueForScope(); return __snapshot(); }
/** 把队列里每张卡推进成「今天刚评过」的**结果状态**：reps > 0、due 推到 3 天后。
 *  这是 doRate() 的产物而不是它的实现 —— FSRS 排程不在本探针的被测面内，
 *  这里只需要一个真实可达的完成态：新词配额已被 today.nw 吃光（由 __setup 的
 *  todayNw 负责）、到期卡不再到期。队列本身仍由真实 buildReviewQueue() 生成。 */
function __markQueueRated() {
  var now = Date.now();
  revQueue.forEach(function (id) {
    S.cards[id] = { reps: 4, s: 5, d: 5, due: now + 3 * 86400000, last: now };
  });
  revIdx = revQueue.length;
  ratedCount = revIdx;
  __buildCalls = 0;
  return __snapshot();
}
function __makeWordsPredicate() {
  ${WORDS_Q_LINE}
  return (${WORDS_PREDICATE});
}
`;

const ctx = vm.createContext({ console });
vm.runInContext(
  [PRELUDE, ...Object.values(PIECES).filter(s => s !== WORDS_PREDICATE), INSTRUMENT, FIXTURE].join("\n"),
  ctx,
  { filename: "workbench-slices.js" }
);

const sb = (expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));
const run = (stmt) => vm.runInContext(stmt, ctx);

/** 首个不同下标，用于幂等失败时报「哪儿变了」而不是干巴巴一个 false。 */
function firstDiff(a, b) {
  if (a === b) return null;
  const x = JSON.parse(a), y = JSON.parse(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if (x[i] !== y[i]) return { at: i, before: x[i] ?? null, after: y[i] ?? null, lenBefore: x.length, lenAfter: y.length };
  }
  return { at: -1, lenBefore: x.length, lenAfter: y.length };
}

const isPrefix = (short, long) => short.every((id, i) => long[i] === id);

/* ---------------------------------------------------------------------------
 * 场景 1：liveDailyNew —— 队列未刷完时改 dailyNew，尾部即时重算、已评部分不动
 * ------------------------------------------------------------------------ */

function runLiveDailyNew() {
  const initial = sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 5, dueCount: 8, scope: "all", curView: "review", revIdx: 6 })`);
  const raised = sb(`__setDailyNew(30)`);
  const lowered = sb(`__setDailyNew(10)`);
  const floored = sb(`__setDailyNew(3)`);   // 3 < today.nw=5 → 配额被 max(0, …) 兜到 0

  const phases = { initial, raised, lowered, floored };
  const expect = { initial: 15, raised: 30, lowered: 10, floored: 3 };
  const out = { todayNw: 5, quotaFormula: "max(0, dailyNew - today.nw)" };
  for (const [k, snap] of Object.entries(phases)) {
    out[k] = {
      dailyNew: expect[k],
      tailNew: snap.tailNew,
      expectTailNew: Math.max(0, expect[k] - 5),
      tailDue: snap.tailDue,
      queueLen: snap.queueLen,
    };
  }
  return Object.assign(out, {
    revIdx: initial.revIdx,
    dueInTailBefore: initial.tailDue,
    dueKeptInTail: floored.tailDue,
    headStableBytes: [raised, lowered, floored].every(s => s.head === initial.head),
    revIdxStable: [raised, lowered, floored].every(s => s.revIdx === initial.revIdx),
    ratedCountStable: [raised, lowered, floored].every(s => s.ratedCount === initial.ratedCount),
    queueDayStable: [raised, lowered, floored].every(s => s.queueDay === initial.queueDay),
    buildCallsTotal: floored.buildCalls,
    loweredIsPrefixOfRaised: isPrefix(lowered.tailNewIds, raised.tailNewIds),
    headBytes: initial.head.length,
  });
}

/* ---------------------------------------------------------------------------
 * 场景 2：extraExempt —— 手动追加的超配额词不被裁
 * ------------------------------------------------------------------------ */

function runExtraExempt() {
  const before = sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 5, dueCount: 8, scope: "all", curView: "review", revIdx: 6 })`);
  run(`extraNewWords()`);
  const afterExtra = sb(`__snapshot()`);
  const registered = sb(`Array.from(manualExtraIds)`);
  const after = sb(`__setDailyNew(3)`);   // 配额压到 0：常规新词该被裁光，豁免的一个都不能少
  const survived = sb(`Array.from(manualExtraIds).filter(function (id) { return revQueue.indexOf(id) >= 0; }).length`);
  return {
    /* 追加与登记分开报：只登记不追加、只追加不登记是两种不同的坏法 */
    extraAppended: afterExtra.queueLen - before.queueLen,
    extraRegistered: registered.length,
    dailyNewAfter: 3,
    quotaAfter: after.quota,
    queueLenBefore: before.queueLen,
    queueLenAfterExtra: afterExtra.queueLen,
    queueLenAfter: after.queueLen,
    pinnedSurvived: survived,
    pinnedInQueue: after.pinnedInQueue,
    normalNewAfter: after.normalNewInTail,
    headStableBytes: after.head === before.head,
    toast: sb(`__toasts[__toasts.length - 1] || ""`),
  };
}

/* ---------------------------------------------------------------------------
 * 场景 3：scopeNoTopUp —— 切 core 只过滤不补齐（ADR 3.6 刻意的不对称）
 * ------------------------------------------------------------------------ */

function runScopeNoTopUp() {
  const before = sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 0, dueCount: 8, scope: "all", curView: "review", revIdx: 3 })`);
  const after = sb(`__switchScope("core")`);
  return {
    quota: before.quota,
    tailNewBefore: before.tailNew,
    tailNewAfter: after.tailNew,
    nonCoreNewFilteredOut: before.tailNew - after.tailNew,
    nonCoreLeftInTail: after.tailNonCore,
    queueLenBefore: before.queueLen,
    queueLenAfter: after.queueLen,
    revIdxStable: after.revIdx === before.revIdx,
    rebuilt: after.buildCalls > 0,
    toppedUpToQuota: after.tailNew >= before.quota,
  };
}

/* ---------------------------------------------------------------------------
 * 场景 4：searchBypass —— core 模式下搜索旁路 scope（Task 3 的行为面）
 * ------------------------------------------------------------------------ */

function runSearchBypass() {
  sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 0, dueCount: 0, scope: "core", curView: "words", revIdx: 0 })`);
  /* 探针词必须是**真实非核心**词：计划文档举例的 Absender(a1-0007) 其实在
   * CORE_WORD_SEED_IDS 里，拿它做探针这条场景会恒真。故从真实词表里现挑。 */
  const probe = sb(`(function () {
    var w = S.words.find(function (x) {
      return !(x.tags || []).includes("core") && x.hw.length >= 8 && x.hw.indexOf(" ") < 0;
    });
    if (!w) throw new Error("词表里找不到可用的非核心探针词");
    return { id: w.id, hw: w.hw, core: (w.tags || []).includes("core") };
  })()`);

  run(`wordFilters.q = ${JSON.stringify(probe.hw.toLowerCase())};`);
  const withSearch = sb(`(function () {
    var pred = __makeWordsPredicate();
    var hits = S.words.filter(pred);
    return {
      hits: hits.length,
      nonCore: hits.filter(function (w) { return !(w.tags || []).includes("core"); }).length,
      probeHit: hits.some(function (w) { return w.id === ${JSON.stringify(probe.id)}; })
    };
  })()`);

  run(`wordFilters.q = "";`);
  const withoutSearch = sb(`(function () {
    var pred = __makeWordsPredicate();
    var hits = S.words.filter(pred);
    return {
      hits: hits.length,
      nonCore: hits.filter(function (w) { return !(w.tags || []).includes("core"); }).length,
      probeHit: hits.some(function (w) { return w.id === ${JSON.stringify(probe.id)}; })
    };
  })()`);

  run(`wordFilters.scope = "all"; wordFilters.q = ${JSON.stringify(probe.hw.toLowerCase())};`);
  const allMode = sb(`S.words.filter(__makeWordsPredicate()).length`);

  return {
    probeWord: probe,
    hitsWithSearch: withSearch.hits,
    nonCoreHitsWithSearch: withSearch.nonCore,
    probeWordHitWithSearch: withSearch.probeHit,
    hitsWithoutSearch: withoutSearch.hits,
    nonCoreHitsWithoutSearch: withoutSearch.nonCore,
    probeWordHitWithoutSearch: withoutSearch.probeHit,
    hitsWithSearchAllMode: allMode,
  };
}

/* ---------------------------------------------------------------------------
 * 场景 5：idempotency —— 连调两次 renormalizeQueueTail() 队列逐字节不变
 * ------------------------------------------------------------------------ */

function runIdempotency() {
  const out = {};
  for (const mode of ["seed", "shuffle"]) {
    sb(`__setup({ dailyNew: 15, newOrder: "${mode}", todayNw: 5, dueCount: 8, scope: "all", curView: "review", revIdx: 6 })`);
    const first = sb(`__setDailyNew(30)`);          // 走补词分支（会摸 pool / shuffle）
    const second = sb(`(renormalizeQueueTail(), __snapshot())`);
    out[mode] = {
      stable: first.queue === second.queue,
      diff: firstDiff(first.queue, second.queue),
      queueLen: second.queueLen,
      tailNew: second.tailNew,
    };
  }
  return out;
}

/* ---------------------------------------------------------------------------
 * 场景 6：finishedStateScopeSwitch —— 今日刷完后切模式（Task 1 复核新发现）
 *
 * refilterReviewQueueForScope() 结尾的 `if (curView === "review") renderReview();`
 * 在 Task 1 之前是死代码（#wScope 在词库视图，curView 永远不是 "review"）。
 * 顶栏控件让它第一次活了，而 renderReview() 的门是
 * `if (queueDay !== today || revIdx >= revQueue.length) buildReviewQueue()`。
 *
 * 本场景出两组数据，**读法完全不同**，别混用：
 *   - scene()               合成完成态（见其函数头注释）：只守与裁决无关的不变式；
 *   - runReachableFinished() 真实可达完成态：**这组才是线上行为**，裁决照它做。
 * 裁决结论（docs/plans/workbench-scope-control-and-live-settings.md · Task 6）：
 * 重建确实发生，但产出空队列 → 完成屏，不补齐、不弹卡、不抹 ratedCount，无害。
 * ------------------------------------------------------------------------ */

/** 合成完成态：`revIdx = "finished"` 只是把 revIdx / ratedCount 直接写成队列长度，
 *  **从没调过 doRate**。这个 fixture 真实不可达，两处自相矛盾：
 *    1. todayNw: 0 与 ratedCount: 23 互斥 —— 真评掉那 15 张新词，today.nw 必然是 15；
 *    2. 8 张到期卡的 due 还停在过去，重建时又被当到期卡捡回来。
 *  所以它报出的 `revIdx 23→0 / tailNew 0→15 / toppedUpToQuota: true`
 *  **不代表线上行为**，不可被引用为「完成态切模式会补满配额」的证据。
 *  保留它的唯一意义：守住与裁决无关的不变式（非 review 视图不重建、
 *  尾部不残留非核心词、ratedCount 不被抹、重建与否自洽）。
 *  真实可达的那组见 runReachableFinished()。 */
function runFinishedStateScopeSwitch() {
  const scene = (curView) => {
    const before = sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 0, dueCount: 8, scope: "all", curView: "${curView}", revIdx: "finished" })`);
    const after = sb(`__switchScope("core")`);
    const pick = (s) => ({
      revIdx: s.revIdx, queueLen: s.queueLen, tailNew: s.tailNew,
      newInQueue: s.newInQueue, nonCoreInQueue: s.nonCoreInQueue,
      tailNonCore: s.tailNonCore,
      ratedCount: s.ratedCount, queueDay: s.queueDay,
    });
    return {
      curView,
      synthetic: true,
      quota: before.quota,
      before: pick(before),
      after: pick(after),
      rebuilt: after.buildCalls > 0,
      buildCalls: after.buildCalls,
      toppedUpToQuota: after.newInQueue >= before.quota,
    };
  };
  const review = scene("review");
  const control = scene("words");
  return Object.assign(review, {
    controlNonReviewView: control,
    reachableFinished: runReachableFinished(),
  });
}

/** 真实可达的完成态：新词配额被评满（today.nw = dailyNew = 15）、
 *  到期卡全部评过（due 推到未来），revIdx / ratedCount 与之自洽。
 *  这组数字才是线上行为 —— 重建产出**空队列**，renderReview() 落回完成屏。 */
function runReachableFinished() {
  sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 15, dueCount: 8, scope: "all", curView: "review", revIdx: "finished" })`);
  const before = sb(`__markQueueRated()`);
  const after = sb(`__switchScope("core")`);
  return {
    synthetic: false,
    /* 切模式那一刻的新词配额 = max(0, dailyNew - today.nw)，此处已耗尽为 0 */
    quota: before.quota,
    before: { revIdx: before.revIdx, queueLen: before.queueLen, ratedCount: before.ratedCount },
    after: {
      revIdx: after.revIdx, queueLen: after.queueLen, ratedCount: after.ratedCount,
      newInQueue: after.newInQueue, tailNonCore: after.tailNonCore,
    },
    rebuilt: after.buildCalls > 0,
    buildCalls: after.buildCalls,
    /* 空队列 ⇒ renderReview() 的 `revIdx >= revQueue.length` 分支 ⇒ 完成屏 */
    landsOnFinishedScreen: after.revIdx >= after.queueLen,
  };
}

/* ---------------------------------------------------------------------------
 * 场景 7：rebuildClearsExemptions —— 整队重建清空手动追加豁免集
 *
 * manualExtraIds 只增不减，而 revQueue 会被 buildReviewQueue() 整队重建。
 * 可达后果：标签页跨夜不关，昨天手动追加、今天仍未学的词若又被排进新队列，
 * 就会被当 pinned，逃过 dailyNew 调低时的裁剪。
 * 本场景走**真实路径**触发重建（queueDay 拨回昨天 → renderReview() 的 rollover 门），
 * 不直接调 buildReviewQueue()。
 * ------------------------------------------------------------------------ */

function runRebuildClearsExemptions() {
  const before = sb(`__setup({ dailyNew: 15, newOrder: "seed", todayNw: 0, dueCount: 8, scope: "all", curView: "review", revIdx: 3 })`);
  run(`extraNewWords()`);
  const afterExtra = sb(`__snapshot()`);
  const registeredIds = sb(`Array.from(manualExtraIds)`);

  /* dailyNew 调到 40：让重建后的新词池覆盖那 20 个手动追加词 —— 否则它们压根
   * 不在新队列里，"漏裁"这个后果就无从发生，断言也就恒真了。 */
  const rebuilt = sb(`(function () {
    S.settings.dailyNew = 40;
    queueDay = "1999-01-01";
    renderReview();
    return __snapshot();
  })()`);
  const exemptAfterRebuild = sb(`manualExtraIds.size`);
  const staleExemptInQueue = sb(
    `${JSON.stringify(registeredIds)}.filter(function (id) { return revQueue.indexOf(id) >= 0; }).length`
  );

  /* 配额压到 0：豁免集若有残留，那些 id 会以 pinned 身份活过裁剪。 */
  const trimmed = sb(`__setDailyNew(0)`);

  return {
    queueLenBeforeExtra: before.queueLen,
    extraAppended: afterExtra.queueLen - before.queueLen,
    registeredBeforeRebuild: registeredIds.length,
    rebuilt: rebuilt.buildCalls > 0,
    buildCalls: rebuilt.buildCalls,
    revIdxAfterRebuild: rebuilt.revIdx,
    queueLenAfterRebuild: rebuilt.queueLen,
    /* > 0 才说明「漏裁」这条路径真的可达（否则下面 newInQueueAfterTrim 恒 0） */
    staleExemptInQueue,
    exemptAfterRebuild,
    quotaAfterTrim: trimmed.quota,
    pinnedInQueueAfterTrim: trimmed.pinnedInQueue,
    newInQueueAfterTrim: trimmed.newInQueue,
    queueLenAfterTrim: trimmed.queueLen,
  };
}

/* ------------------------------------------------------------------------ */

const out = {
  slices: Object.fromEntries(Object.entries(PIECES).map(([k, v]) => [k, v.length])),
  guards: GUARDS.length,
  fixture: {
    seedWords: sb(`SEED_WORDS.length`),
    coreCustomWords: sb(`CORE_CUSTOM_WORDS.length`),
    coreSeedIds: sb(`CORE_WORD_SEED_IDS.size`),
    words: sb(`__freshWords().length`),
  },
  liveDailyNew: runLiveDailyNew(),
  extraExempt: runExtraExempt(),
  scopeNoTopUp: runScopeNoTopUp(),
  searchBypass: runSearchBypass(),
  idempotency: runIdempotency(),
  finishedStateScopeSwitch: runFinishedStateScopeSwitch(),
  rebuildClearsExemptions: runRebuildClearsExemptions(),
};

process.stdout.write(JSON.stringify(out, null, JSON_MODE ? 0 : 2));
if (!JSON_MODE) process.stdout.write("\n");
