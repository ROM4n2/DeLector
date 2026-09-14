/**
 * wb_merge_probe.mjs —— 背词工作台「合并导入 / id 别名迁移」动态探针（Task 8）
 *
 * 静态正则只能证明「代码长这样」，证明不了「二次导入是 no-op」「迁移是幂等的」。
 * 本探针把 static/german/workbench.html 里的 **真实源码**（normHw / applyMerge /
 * migrateSeedIdAliases / SEED_ID_ALIASES / SEED_WORDS / CORE_* 常量）按花括号配对
 * 整段切出来，丢进 node:vm 沙箱里真跑，再把结果打成 JSON 给 pytest 断言。
 *
 * 硬约束：探针里**不得重抄一份实现**。重抄的话实现回退了探针照样绿 —— 死测。
 * 所有被测逻辑一律来自 workbench.html 的切片，本文件只提供 S / save* / toast 等桩。
 *
 * 用法：node tools/wb_merge_probe.mjs --json
 *   --json 时 stdout 只有一个 JSON 对象，日志一律走 stderr，退出码 0。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const HTML = path.join(ROOT, "static", "german", "workbench.html");
const SOURCE_JSON = "D:/Ran/Goethe_A1/delector_custom_words.json";
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

/** 抽取一条顶层声明，如 `const SEED_ID_ALIASES = {...};`（含结尾分号）。 */
function extractDecl(src, name) {
  const anchor = new RegExp(`^const\\s+${name}\\s*=`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到声明 const ${name}`);
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  let tail = end + 1;
  while (tail < src.length && /[\s)\]]/.test(src[tail])) {
    if (src[tail] === ")" || src[tail] === "]") tail++; else break;
  }
  const semi = src.indexOf(";", end);
  return src.slice(m.index, (semi >= 0 && semi < end + 8 ? semi : end) + 1);
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

const html = fs.readFileSync(HTML, "utf8");
const PIECES = {
  CORE_WORD_SEED_IDS: extractDecl(html, "CORE_WORD_SEED_IDS"),
  CORE_CUSTOM_WORDS: extractDecl(html, "CORE_CUSTOM_WORDS"),
  SEED_WORDS: extractDecl(html, "SEED_WORDS"),
  SEED_ID_ALIASES: extractDecl(html, "SEED_ID_ALIASES"),
  migrateSeedIdAliases: extractFn(html, "migrateSeedIdAliases"),
  normHw: extractFn(html, "normHw"),
  applyMerge: extractFn(html, "applyMerge"),
  /* Task 4（ADR-0011）：词对象契约归一 + 存量迁移 */
  /* Task 5：normalizeWord 的 cefr 推导抽到 CEFR_BY_PREFIX + cefrFromId 公共 helper，
   * 沙箱必须一并带上（只加切片，护栏语义零漂移）。 */
  CEFR_BY_PREFIX: extractDecl(html, "CEFR_BY_PREFIX"),
  cefrFromId: extractFn(html, "cefrFromId"),
  normalizeWord: extractFn(html, "normalizeWord"),
  normalizeAllWords: extractFn(html, "normalizeAllWords"),
  migrateWordSchema: extractFn(html, "migrateWordSchema"),
  markSchemaMigrated: extractFn(html, "markSchemaMigrated"),
};
for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 40) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
  log(`[slice] ${k}: ${v.length} 字节`);
}
/* 防死测：切片必须是真实现，而不是碰巧匹配到的空壳 */
if (!/byHw/.test(PIECES.applyMerge)) throw new Error("applyMerge 切片里没有词头二级索引，切歪了");
if (!/cardWins/.test(PIECES.migrateSeedIdAliases)) throw new Error("migrateSeedIdAliases 切片切歪了");
if (!/cefr/.test(PIECES.normalizeWord)) throw new Error("normalizeWord 切片里没有 cefr 归一，切歪了");
if (!/SCHEMA_KEY/.test(PIECES.migrateWordSchema)) throw new Error("migrateWordSchema 切片里没有 wb.schema.v1 标记守卫，切歪了");

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只提供 workbench.html 里被测代码依赖的最小桩
 * ------------------------------------------------------------------------ */

const PRELUDE = `
var DEFAULT_SETTINGS = {};
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: {} };
var __toasts = [];
function toast(m) { __toasts.push(String(m)); }
var __saveWordsCalls = 0;
function saveWords() { __saveWordsCalls++; }
function saveCards() {}
function saveLog() {}
function saveWrong() {}
function saveSettings() {}
function applyTheme() {}
function renderHeaderBadge() {}
function showView() {}
function wordById(id) { return S.words.find(function (w) { return w.id === id; }) || null; }
/* Task 4 迁移桩：SCHEMA_KEY 常量 + localStorage 桩（键值存 __ls） */
var SCHEMA_KEY = "wb.schema.v1";
var __ls = {};
var localStorage = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(__ls, k) ? __ls[k] : null; },
  setItem: function (k, v) { __ls[k] = String(v); },
  removeItem: function (k) { delete __ls[k]; },
};
`;

const ctx = vm.createContext({ console });
vm.runInContext(
  PRELUDE + "\n" + Object.values(PIECES).join("\n") + "\n",
  ctx,
  { filename: "workbench-slices.js" }
);

const sb = (expr) => vm.runInContext(expr, ctx);
const call = (fn, ...args) => {
  ctx.__args = args;
  return vm.runInContext(`${fn}.apply(null, __args)`, ctx);
};
const setState = (state) => {
  ctx.__state = state;
  vm.runInContext(
    "S.words = __state.words; S.cards = __state.cards; S.log = __state.log; S.wrong = __state.wrong; __toasts.length = 0;",
    ctx
  );
};
const getState = () => vm.runInContext(
  "JSON.stringify({ words: S.words, cards: S.cards, log: S.log, wrong: S.wrong })",
  ctx
);

/** 复刻 loadAll() 的首装词表构造（用的是真实 SEED_WORDS / CORE_* 常量）。 */
function freshWords() {
  return JSON.parse(vm.runInContext(`JSON.stringify(
    SEED_WORDS.map(function (w) {
      return {
        id: w.id, hw: w.hw, pos: w.pos || "", gloss: w.gloss || "",
        ipa: w.ipa || "", ex: Array.isArray(w.ex) ? w.ex : [], letter: w.letter || "",
        page: w.page || 0, tags: CORE_WORD_SEED_IDS.has(w.id) ? ["core"] : [],
        custom: false, up: 0
      };
    }).concat(CORE_CUSTOM_WORDS.map(function (w) {
      return Object.assign({}, w, { tags: ["core"], custom: true, up: w.up || 0 });
    }))
  )`, ctx));
}

const normHw = (hw) => call("normHw", hw);
const wordsNow = () => JSON.parse(vm.runInContext("JSON.stringify(S.words)", ctx));
const cardsNow = () => JSON.parse(vm.runInContext("JSON.stringify(S.cards)", ctx));
const wrongNow = () => JSON.parse(vm.runInContext("JSON.stringify(S.wrong)", ctx));
const lastCounts = () => {
  const msgs = JSON.parse(vm.runInContext("JSON.stringify(__toasts)", ctx));
  const m = /新增\s*(\d+)\s*词、合并\s*(\d+)\s*词/.exec(msgs[msgs.length - 1] || "");
  if (!m) throw new Error("applyMerge 没吐出计数 toast：" + JSON.stringify(msgs));
  return { added: Number(m[1]), merged: Number(m[2]) };
};

/* ---------------------------------------------------------------------------
 * 3. 场景一：真实词库连导两次
 * ------------------------------------------------------------------------ */

function dupGroups(words) {
  const by = new Map();
  for (const w of words) {
    const k = normHw(w.hw);
    if (!k) continue;
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(w.id);
  }
  const dups = [];
  for (const [k, ids] of by) if (ids.length > 1) dups.push(k + " → " + ids.join(","));
  return dups;
}

const coreTagged = (words) => words.filter(w => Array.isArray(w.tags) && w.tags.includes("core")).length;

function runDoubleImport() {
  if (!fs.existsSync(SOURCE_JSON)) {
    return { skipped: true, reason: `${SOURCE_JSON} 不存在` };
  }
  const payload = JSON.parse(fs.readFileSync(SOURCE_JSON, "utf8"));
  const incoming = (payload.customWords || payload.words || []).length;

  setState({ words: freshWords(), cards: {}, log: {}, wrong: {} });
  const before = wordsNow();
  const beforeIds = before.map(w => w.id);
  const beforeCustom = before.map(w => !!w.custom);
  const coreTaggedBefore = coreTagged(before);

  call("applyMerge", JSON.parse(JSON.stringify(payload)));
  const first = lastCounts();
  const afterFirstWords = wordsNow();
  const dupFirst = dupGroups(afterFirstWords);

  call("applyMerge", JSON.parse(JSON.stringify(payload)));
  const afterSecondWords = wordsNow();
  const dupSecond = dupGroups(afterSecondWords);

  let idsChanged = 0, seedTurnedCustom = 0;
  for (let i = 0; i < beforeIds.length; i++) {
    if (afterSecondWords[i].id !== beforeIds[i]) idsChanged++;
    if (!beforeCustom[i] && afterSecondWords[i].custom) seedTurnedCustom++;
  }

  return {
    incoming,
    added: first.added,
    merged: first.merged,
    afterFirst: afterFirstWords.length,
    afterSecond: afterSecondWords.length,
    dupNormHwAfterFirst: dupFirst.length,
    dupNormHwAfterSecond: dupSecond.length,
    dupSamples: [...new Set([...dupFirst, ...dupSecond])].slice(0, 10),
    coreTaggedBefore,
    coreTaggedAfterSecond: coreTagged(afterSecondWords),
    idsChanged,
    seedTurnedCustom,
    secondImport: lastCounts(),
  };
}

/* ---------------------------------------------------------------------------
 * 4. 场景二：大小写敏感（sie/Sie、essen/Essen、leben/Leben）
 * ------------------------------------------------------------------------ */

function runCaseSensitivity() {
  const words = wordsNow(); // 沿用双次导入后的词表：真实世界的最终态
  const base = words.length ? words : freshWords();
  const pairs = {};
  for (const pair of ["sie|Sie", "essen|Essen", "leben|Leben"]) {
    const [lo, hi] = pair.split("|");
    pairs[pair] = base.filter(w => {
      const k = normHw(w.hw);
      return k === lo || k === hi;
    }).length;
  }
  return { normHwSie: normHw("Sie"), normHwsie: normHw("sie"), pairs };
}

/* ---------------------------------------------------------------------------
 * 5. 场景三：别名迁移的进度取舍 / 幂等 / 无孤儿
 * ------------------------------------------------------------------------ */

const ALIASES = JSON.parse(vm.runInContext("JSON.stringify(SEED_ID_ALIASES)", ctx));
const OLD_IDS = Object.keys(ALIASES);
const [OLD_A, OLD_B] = OLD_IDS;
const NEW_A = ALIASES[OLD_A], NEW_B = ALIASES[OLD_B];

function migrateWith({ words = [], cards = {}, log = {}, wrong = {} }) {
  setState({ words, cards, log, wrong });
  const changed = call("migrateSeedIdAliases");
  return { changed, cards: cardsNow(), wrong: wrongNow(), words: wordsNow() };
}

function runAliasMigration() {
  /* a) 目标位为空：整条搬过去 */
  const moved = migrateWith({ cards: { [OLD_A]: { reps: 5, due: 200 } } }).cards[NEW_A];

  /* b) 两边都有：留 reps 大的（旧的更大） */
  const higher = migrateWith({
    cards: { [OLD_A]: { reps: 7, due: 10 }, [NEW_A]: { reps: 3, due: 900 } },
  }).cards[NEW_A];

  /* c) 反向摆放：新的 reps 更大，必须留新的 */
  const higherRev = migrateWith({
    cards: { [OLD_A]: { reps: 2, due: 900 }, [NEW_A]: { reps: 9, due: 10 } },
  }).cards[NEW_A];

  /* d) reps 打平：留 due 更晚的（旧的 999） */
  const tie = migrateWith({
    cards: { [OLD_A]: { reps: 4, due: 999 }, [NEW_A]: { reps: 4, due: 100 } },
  }).cards[NEW_A];

  /* e) 错题本按 n 多者留 */
  const wrongKept = migrateWith({
    wrong: { [OLD_A]: { n: 4 }, [NEW_A]: { n: 1 } },
  }).wrong[NEW_A];

  /* f) 综合场景：真实词表 + 两条残留词条 + 新旧混杂进度，跑两次 */
  const words = freshWords();
  words.push({ id: OLD_A, hw: "残留词 A", pos: "", gloss: "", ipa: "", ex: [], letter: "", page: 0, tags: [], custom: false, up: 0 });
  words.push({ id: OLD_B, hw: "残留词 B", pos: "", gloss: "", ipa: "", ex: [], letter: "", page: 0, tags: [], custom: false, up: 0 });
  setState({
    words,
    cards: {
      "a1-0001": { reps: 1, due: 3 },
      [OLD_A]: { reps: 7, due: 10 },
      [NEW_A]: { reps: 3, due: 900 },
      [OLD_B]: { reps: 2, due: 5 },
    },
    log: { "2026-01-01": { rv: 3, good: 2 } },
    wrong: { [OLD_A]: { n: 4 }, [NEW_A]: { n: 1 }, [OLD_B]: { n: 2 } },
  });
  const firstRunChanged = call("migrateSeedIdAliases");
  const snapAfterFirst = getState();
  const secondRunChanged = call("migrateSeedIdAliases");
  const snapAfterSecond = getState();

  const finalCards = cardsNow();
  const finalWrong = wrongNow();
  const finalWords = wordsNow();
  const wordIds = new Set(finalWords.map(w => w.id));

  let oldKeysLeft = 0;
  for (const oldId of OLD_IDS) {
    if (Object.prototype.hasOwnProperty.call(finalCards, oldId)) oldKeysLeft++;
    if (Object.prototype.hasOwnProperty.call(finalWrong, oldId)) oldKeysLeft++;
  }
  const staleWordsLeft = finalWords.filter(w => OLD_IDS.includes(w.id)).length;
  const orphanCards = Object.keys(finalCards).filter(id => !wordIds.has(id)).length;

  return {
    aliases: ALIASES,
    movedWhenTargetEmpty: moved,
    keptHigherReps: higher.reps,
    keptHigherRepsReversed: higherRev.reps,
    keptLaterDueOnRepsTie: tie.due,
    wrongKeptHigherN: wrongKept.n,
    oldKeysLeft,
    staleWordsLeft,
    firstRunChanged,
    secondRunChanged,
    snapshotStable: snapAfterFirst === snapAfterSecond,
    orphanCards,
  };
}

/* ---------------------------------------------------------------------------
 * 6. 场景四：词对象契约归一 + 存量数据一次性迁移（Task 4 / ADR-0011 决策 2）
 * ------------------------------------------------------------------------ */

function runSchemaMigration() {
  /* 旧形状混存：A1 gloss/ex 富字段 + A2 zh/gender/plural 新契约 + reader card-*（缺 gender/plural/cefr） */
  const legacy = [
    { id: "a1-0001", hw: "Haus", pos: "n.", gloss: "房子", ipa: "haʊs", ex: [{ de: "Das Haus ist groß.", zh: "房子很大。" }], letter: "H", page: 1, tags: ["core"], custom: false, up: 0 },
    { id: "a2-abenteuer", hw: "das Abenteuer", pos: "n.", zh: "冒险", de: "", gender: "das", plural: "die Abenteuer", core: false, cefr: "A2", tags: ["a2"], custom: true, up: 1 },
    { id: "card-Testwort", hw: "Testwort", pos: "", gloss: "测试词", ipa: "", ex: [], letter: "T", page: 0, tags: ["reader"], custom: true, up: 2 },
  ];
  const idBefore = legacy.map(w => w.id);
  setState({
    words: JSON.parse(JSON.stringify(legacy)),
    cards: { "a1-0001": { reps: 3, due: 10 } },
    log: {},
    wrong: { "card-Testwort": { n: 2 } },
  });
  const keySet = (o) => Object.keys(o).sort().join("|");
  const cardsKeysBefore = keySet(cardsNow());
  const wrongKeysBefore = keySet(wrongNow());

  /* (d) 幂等：normalize 连跑两次 deep-equal */
  const once = vm.runInContext("JSON.stringify(S.words.map(normalizeWord))", ctx);
  const twice = vm.runInContext("JSON.stringify(S.words.map(normalizeWord).map(normalizeWord))", ctx);
  const normalizeIdempotent = once === twice;

  /* 一次性迁移（真实 migrateWordSchema）：全成功才 saveWords 落盘并写标记 */
  vm.runInContext("__saveWordsCalls = 0; __ls = {};", ctx);
  const firstRunChanged = call("migrateWordSchema");
  const markerAfterFirst = vm.runInContext("localStorage.getItem(SCHEMA_KEY)", ctx);
  const saveCallsAfterFirst = vm.runInContext("__saveWordsCalls", ctx);
  const migrated = wordsNow();
  vm.runInContext("__saveWordsCalls = 0;", ctx);
  const secondRunChanged = call("migrateWordSchema");
  const saveCallsAfterSecond = vm.runInContext("__saveWordsCalls", ctx);
  const migratedSecond = wordsNow();
  const cardsKeysAfter = keySet(cardsNow());
  const wrongKeysAfter = keySet(wrongNow());

  /* 失败路径：一条非法词（缺 id）→ 整体放弃，不落盘、不写标记 */
  setState({ words: [{ id: "a1-0002", hw: "Wohnung" }, { hw: "无 id 的坏词" }], cards: {}, log: {}, wrong: {} });
  vm.runInContext("__saveWordsCalls = 0; __ls = {};", ctx);
  const failRunChanged = call("migrateWordSchema");
  const failMarker = vm.runInContext("localStorage.getItem(SCHEMA_KEY)", ctx);
  const failSaveCalls = vm.runInContext("__saveWordsCalls", ctx);

  const byId = {};
  for (const w of migrated) byId[w.id] = w;
  const contractKeys = ["zh", "gloss", "gender", "plural", "cefr"];
  const contractMissing = migrated
    .filter(w => contractKeys.some(k => !Object.prototype.hasOwnProperty.call(w, k)))
    .map(w => w.id);

  return {
    /* (a) id 集合逐一不变 */
    idsUnchanged: JSON.stringify(idBefore) === JSON.stringify(migrated.map(w => w.id))
      && JSON.stringify(idBefore) === JSON.stringify(migratedSecond.map(w => w.id)),
    /* (b) 契约键齐全（reader 词补 null/"" 后也过） */
    contractMissingIds: contractMissing,
    a1ZhFromGloss: byId["a1-0001"].zh === "房子" && byId["a1-0001"].gloss === "房子",
    a2GlossFromZh: byId["a2-abenteuer"].gloss === "冒险" && byId["a2-abenteuer"].zh === "冒险",
    a1Cefr: byId["a1-0001"].cefr,
    a2Cefr: byId["a2-abenteuer"].cefr,
    readerCefrNull: byId["card-Testwort"].cefr === null,
    readerGenderNull: byId["card-Testwort"].gender === null,
    readerPluralEmpty: byId["card-Testwort"].plural === "",
    a1GenderNull: byId["a1-0001"].gender === null,
    a2GenderPreserved: byId["a2-abenteuer"].gender === "das" && byId["a2-abenteuer"].plural === "die Abenteuer",
    /* 不丢数据：A1 富字段原样保留（T4-N2 承接：custom/up 也在结构全拷贝保护面内） */
    a1RichFieldsPreserved: byId["a1-0001"].ipa === "haʊs"
      && Array.isArray(byId["a1-0001"].ex) && byId["a1-0001"].ex.length === 1
      && byId["a1-0001"].letter === "H" && byId["a1-0001"].page === 1
      && JSON.stringify(byId["a1-0001"].tags) === JSON.stringify(["core"])
      && byId["a1-0001"].custom === false
      && byId["a1-0001"].up === 0,
    /* (d) 幂等 */
    normalizeIdempotent,
    migrationStable: JSON.stringify(migrated) === JSON.stringify(migratedSecond),
    /* (c) cards/wrong 键集合不变 */
    cardsKeysUnchanged: cardsKeysBefore === cardsKeysAfter,
    wrongKeysUnchanged: wrongKeysBefore === wrongKeysAfter,
    /* 全成功才落盘 / 已标记跳过 / 失败不写半套 */
    firstRunChanged, markerAfterFirst: markerAfterFirst === "1", saveCallsAfterFirst,
    secondRunChanged, saveCallsAfterSecond,
    failRunChanged, failMarkerNull: failMarker === null, failSaveCalls,
  };
}

/* ------------------------------------------------------------------------ */

const doubleImport = runDoubleImport();
const caseSensitivity = runCaseSensitivity();
const aliasMigration = runAliasMigration();
const schemaMigration = runSchemaMigration();

const out = { doubleImport, caseSensitivity, aliasMigration, schemaMigration };
process.stdout.write(JSON.stringify(out, null, JSON_MODE ? 0 : 2));
if (!JSON_MODE) process.stdout.write("\n");
