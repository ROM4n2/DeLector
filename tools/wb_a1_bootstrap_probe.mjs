/**
 * wb_a1_bootstrap_probe.mjs —— A1 首装「服务端 12 字段 → 前端词对象」行为级自检探针
 * （fix/rich-fields-backfill · Task B-S2 · ADR-0014 §6-S2）
 *
 * 背景：A1 首装改走服务端 API（GET /api/cards/vocab?cefr=A1&scope=all），首装结果写
 * localStorage 即缓存；服务未起/失败回退内联种子。a1WordFromApi() 把服务端 12 字段行
 * 映射为前端词对象，口径**必须与旧内联建表（a1WordsFromInline()）逐字段等价**。
 *
 * 硬约束（同 wb_tags_probe.mjs / wb_rich_backfill_probe.mjs）：探针里**不得重抄一份被测
 * 实现**。a1WordFromApi / a1WordsFromInline / normalizeWord / cefrFromId / CEFR_BY_PREFIX /
 * CORE_WORD_SEED_IDS 全部从 static/german/workbench.html 按括号配对整段切出，丢进 node:vm
 * 真跑；本文件只提供夹具与断言。
 *
 * 场景 C（Task B-S3 裁决版）：内联降级为离线 fallback —— 服务端可用时 a1WordsFromInline
 * 调用 0 次、fetch 拒绝时恰好 1 次（704 条），计数器桩证明内联不是主路径数据源。
 *
 * 真数据：通过 --fixture <path> 接收由 pytest 用 Python 产出的 JSON：
 *   {"rows": [...12 字段服务端行...], "inline": {"seed": [...], "custom": [...]}}
 *   rows   = delector.core.database.get_vocab_by_cefr("A1", scope="all")["words"]
 *   inline = delector.data.a1_workbench_dict.A1_WORKBENCH_SEED / A1_WORKBENCH_CUSTOM
 *   （fixture 不提交进仓库，由 pytest 写到 tmp_path）
 *
 * 用法：
 *   node tools/wb_a1_bootstrap_probe.mjs --fixture <fixture.json> [--json]
 *   --json 时 stdout 只有一个 JSON 对象 {"fail": <int>, "total": <int>, "cases": [...]}，
 *   日志走 stderr；人类模式每个场景打印 PASS/FAIL。无 --fixture 时打印用法提示、退出码 0。
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
 * 0. 参数：--fixture <path>
 * ------------------------------------------------------------------------ */
function argValue(flag) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
}
const FIXTURE = argValue("--fixture");
if (!FIXTURE) {
  log("用法：node tools/wb_a1_bootstrap_probe.mjs --fixture <fixture.json> [--json]");
  log("");
  log("  --fixture <path>  由 pytest 用 Python 产出的 JSON：");
  log('    {"rows": [...12 字段服务端行...], "inline": {"seed": [...], "custom": [...]}}');
  log("    rows   = get_vocab_by_cefr(\"A1\", scope=\"all\")[\"words\"]");
  log("    inline = a1_workbench_dict.A1_WORKBENCH_SEED / A1_WORKBENCH_CUSTOM");
  log("  --json            仅输出单个 JSON 结果对象到 stdout");
  process.exit(0);
}

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整声明/函数体（跳过字符串与注释）
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

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

function extractFn(src, name) {
  // 允许 async 前缀：bootstrapA1Words 是 `async function ...`（括号配对与签名无关）。
  const anchor = new RegExp(`^(?:async\\s+)?function\\s+${name}\\s*\\(`, "m");
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
  CEFR_BY_PREFIX: extractDecl(html, "CEFR_BY_PREFIX"),
  cefrFromId: extractFn(html, "cefrFromId"),
  normalizeWord: extractFn(html, "normalizeWord"),
  a1WordFromApi: extractFn(html, "a1WordFromApi"),
  a1WordsFromInline: extractFn(html, "a1WordsFromInline"),
  CORE_WORD_SEED_IDS: extractDecl(html, "CORE_WORD_SEED_IDS"),
};
for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 30) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
}
/* 防死测：切片必须是真实现，否则实现回退了探针照样绿 */
if (!/normalizeWord\(/.test(PIECES.a1WordFromApi)) {
  throw new Error("a1WordFromApi 切片里没有 normalizeWord(...)，切歪或实现回退了");
}
if (!/SEED_WORDS\.map\(/.test(PIECES.a1WordsFromInline) || !/CORE_CUSTOM_WORDS/.test(PIECES.a1WordsFromInline)) {
  throw new Error("a1WordsFromInline 切片里没有 SEED_WORDS.map / CORE_CUSTOM_WORDS，切歪或实现回退了");
}
if (!/cefrFromId\(/.test(PIECES.normalizeWord)) {
  throw new Error("normalizeWord 切片里没有 cefrFromId(...)，切歪或实现回退了");
}
log(`[slice] ${Object.keys(PIECES).join(", ")}`);

/* ---------------------------------------------------------------------------
 * 2. 夹具
 * ------------------------------------------------------------------------ */
let fixture;
try {
  fixture = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
} catch (e) {
  process.stderr.write(`无法读取/解析 --fixture：${FIXTURE}（${e && e.message ? e.message : e}）\n`);
  process.exit(2);
}
const ROWS = Array.isArray(fixture.rows) ? fixture.rows : [];
const INLINE = (fixture.inline && typeof fixture.inline === "object") ? fixture.inline : {};
const SEED = Array.isArray(INLINE.seed) ? INLINE.seed : [];
const CUSTOM = Array.isArray(INLINE.custom) ? INLINE.custom : [];
if (!ROWS.length || !SEED.length || !CUSTOM.length) {
  process.stderr.write("fixture 形状异常：rows / inline.seed / inline.custom 必须都是非空数组\n");
  process.exit(2);
}
log(`[fixture] rows=${ROWS.length} inline.seed=${SEED.length} inline.custom=${CUSTOM.length}`);

/* ---------------------------------------------------------------------------
 * 3. 沙箱：注入被测源码切片 + 夹具常量
 * ------------------------------------------------------------------------ */
const PRELUDE = `var SEED_WORDS = ${JSON.stringify(SEED)};
var CORE_CUSTOM_WORDS = ${JSON.stringify(CUSTOM)};
var __rows = ${JSON.stringify(ROWS)};
`;
const ctx = vm.createContext({ console });
vm.runInContext(
  PRELUDE + "\n" + Object.values(PIECES).join("\n") + "\n",
  ctx,
  { filename: "workbench-a1-bootstrap-slices.js" }
);
const sb = (expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));

/* ---------------------------------------------------------------------------
 * 4. 场景执行
 * ------------------------------------------------------------------------ */
const cases = [];
let failCount = 0;
function check(name, cond, detail, extra) {
  const ok = !!cond;
  const entry = { name, ok, detail: detail == null ? "" : String(detail) };
  /* extra：结构化字段（如内联调用次数），让 pytest 能按字段名断言而不必解析 detail 文本 */
  if (extra && typeof extra === "object") Object.assign(entry, extra);
  cases.push(entry);
  if (!ok) failCount++;
  if (!JSON_MODE) console.log(ok ? `PASS  ${name}` : `FAIL  ${name}${detail ? "  —  " + detail : ""}`);
}

const inlineWords = sb(`a1WordsFromInline()`);
const apiWords = sb(`__rows.map(a1WordFromApi)`);

/* 场景 1：逐字段等价（id 集合与顺序一致；除 page 外逐字段相等；ex 比首条 de/zh） */
{
  const EQ_FIELDS = ["id", "hw", "pos", "gloss", "ipa", "letter", "cefr", "custom", "gender", "plural", "up", "zh"];
  const sameIdOrder = inlineWords.length === apiWords.length
    && inlineWords.every((w, i) => w.id === apiWords[i].id);
  let matched = 0;
  let firstDiff = null;
  const n = Math.min(inlineWords.length, apiWords.length);
  for (let i = 0; i < n; i++) {
    const a = inlineWords[i];
    const b = apiWords[i];
    let ok = true;
    for (const f of EQ_FIELDS) {
      if (JSON.stringify(a[f]) !== JSON.stringify(b[f])) { ok = false; if (!firstDiff) firstDiff = `${b.id}.${f}: inline=${JSON.stringify(a[f])} api=${JSON.stringify(b[f])}`; break; }
    }
    if (ok && JSON.stringify(a.tags) !== JSON.stringify(b.tags)) { ok = false; if (!firstDiff) firstDiff = `${b.id}.tags`; }
    if (ok) {
      const a0 = (Array.isArray(a.ex) && a.ex[0]) || {};
      const b0 = (Array.isArray(b.ex) && b.ex[0]) || {};
      if (JSON.stringify({ de: a0.de, zh: a0.zh }) !== JSON.stringify({ de: b0.de, zh: b0.zh })) { ok = false; if (!firstDiff) firstDiff = `${b.id}.ex[0]`; }
    }
    if (ok && b.page !== 0) { ok = false; if (!firstDiff) firstDiff = `${b.id}.page=${b.page}`; }
    if (ok) matched++;
  }
  check(
    "1 逐字段等价",
    sameIdOrder && inlineWords.length === apiWords.length && matched === inlineWords.length,
    `inline=${inlineWords.length} api=${apiWords.length} matched=${matched}` + (firstDiff ? ` firstDiff=${firstDiff}` : "")
  );
}

/* 场景 2：服务端行 12 字段齐全（防契约漂移） */
{
  const CONTRACT = ["id", "hw", "pos", "gender", "plural", "de", "zh", "ipa", "example_zh", "core", "cefr", "letter"];
  const missing = [];
  for (const r of ROWS) {
    const miss = CONTRACT.filter((k) => !(k in r));
    if (miss.length) missing.push(`${r && r.id}:[${miss.join(",")}]`);
  }
  check("2 契约 12 字段齐全", missing.length === 0, missing.length ? `缺失：${missing.slice(0, 5).join(" ")}` : `${ROWS.length} 行均含 12 字段`);
}

/* 场景 3：letter 取 seed 原值（不派生）—— a1-0462 öffnen：seed O，letterOf 派生为 Ö */
{
  const row = apiWords.find((w) => w.id === "a1-0462");
  const hwFirst = row ? String(row.hw || "?").charAt(0).toUpperCase() : "";
  check(
    "3 letter 不派生（a1-0462 === 'O'）",
    !!row && row.letter === "O" && row.letter !== hwFirst,
    row ? `letter=${JSON.stringify(row.letter)} hw首字母派生=${JSON.stringify(hwFirst)}` : "找不到 a1-0462"
  );
}

/* 场景 4：custom / tags 口径 */
{
  const coreIds = new Set(sb(`Array.from(CORE_WORD_SEED_IDS)`));
  const customRows = ROWS.filter((r) => String(r.id || "").startsWith("core-"));
  const customOk = customRows.length > 0 && customRows.every((r) => {
    const w = apiWords.find((x) => x.id === r.id);
    return w && w.custom === true && (w.tags || []).includes("core") && (w.tags || []).includes("a1");
  });
  const seedRows = ROWS.filter((r) => String(r.id || "").startsWith("a1-"));
  let seedOk = 0;
  let seedFirstBad = null;
  for (const r of seedRows) {
    const expected = coreIds.has(r.id) ? ["a1", "core"] : ["a1"];
    const w = apiWords.find((x) => x.id === r.id);
    if (w && JSON.stringify(w.tags) === JSON.stringify(expected)) seedOk++;
    else if (!seedFirstBad) seedFirstBad = `${r.id}: expected=${JSON.stringify(expected)} api=${JSON.stringify(w && w.tags)}`;
  }
  check(
    "4 custom/tags 口径",
    customOk && seedOk === seedRows.length && coreIds.size === 213,
    `core-*=${customRows.length}（含 core&custom） seed匹配=${seedOk}/${seedRows.length} CORE_WORD_SEED_IDS=${coreIds.size}` + (seedFirstBad ? ` firstBad=${seedFirstBad}` : "")
  );
}

/* 场景 5：page 恒 0 / ex 形状为 [{de,zh}] 或 [] */
{
  let ok = 0;
  let firstBad = null;
  for (const w of apiWords) {
    const ex = w.ex;
    const exOk = Array.isArray(ex) && ex.length <= 1
      && ex.every((p) => p && typeof p.de === "string" && typeof p.zh === "string");
    if (w.page === 0 && exOk) ok++;
    else if (!firstBad) firstBad = `${w.id}: page=${w.page} ex=${JSON.stringify(ex)}`;
  }
  check("5 page 恒 0 / ex 形状", ok === apiWords.length, `${ok}/${apiWords.length}` + (firstBad ? ` firstBad=${firstBad}` : ""));
}

/* ---------------------------------------------------------------------------
 * 4b. 验收修复场景（红牌① / 黄牌② / 黄牌③）
 *
 * 静态正则只能证明「代码长这样」，证明不了「挂起期真的不落盘空表」「inline 设备真的会
 * 重试且合并不覆盖非空」。这里把 workbench.html 里的**真实启动序切片**（sync / hydrate）
 * 与 **bootstrapA1Words / saveWords / migrateSeedIdAliases / backfillCoreWords /
 * mergeA1ServerWords** 等真实函数切片丢进 node:vm 真跑，localStorage 用可观测桩
 * （记录每次 setItem 的键与 words payload），fetch 用可控 stub（永挂 / 返回真实 rows）。
 * ------------------------------------------------------------------------ */
/** const/let/var 声明切片：值为括号字面量（对象/数组/Set）走括号配对；为标量（字符串 /
 *  布尔）则读到语句分号。extractDecl 只支持前者，故本函数补上后者。
 *  var 声明用于把 SEED_WORDS 从 fixture 注入后覆盖同一脚本作用域时的可选场景。 */
function extractDeclAny(src, name) {
  const anchor = new RegExp(`^(?:const|let|var)\\s+${name}\\s*=`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到声明 ${name}`);
  let i = m.index + m[0].length;
  while (i < src.length && /\s/.test(src[i])) i++;
  if (OPEN[src[i]]) {
    const end = matchBracket(src, i);
    const semi = src.indexOf(";", end);
    if (semi < 0 || semi > end + 8) throw new Error(`const ${name} 声明结尾找不到分号，切歪了`);
    return src.slice(m.index, semi + 1);
  }
  const semi = src.indexOf(";", m.index + m[0].length);
  if (semi < 0) throw new Error(`const ${name} 声明结尾找不到分号，切歪了`);
  return src.slice(m.index, semi + 1);
}

const P2 = {
  K: extractDeclAny(html, "K"),
  DEFAULT_SETTINGS: extractDeclAny(html, "DEFAULT_SETTINGS"),
  S: extractDeclAny(html, "S"),
  SCHEMA_KEY: extractDeclAny(html, "SCHEMA_KEY"),
  A1_SRC_KEY: extractDeclAny(html, "A1_SRC_KEY"),
  SEED_ID_ALIASES: extractDeclAny(html, "SEED_ID_ALIASES"),
  CORE_WORD_SEED_IDS: PIECES.CORE_WORD_SEED_IDS,
  CEFR_BY_PREFIX: PIECES.CEFR_BY_PREFIX,
  OTHER_LEVEL_SCOPES: extractDeclAny(html, "OTHER_LEVEL_SCOPES"),
  SCOPE_PREDICATES: extractDeclAny(html, "SCOPE_PREDICATES"),
  A1_BOOT_PENDING: extractDeclAny(html, "A1_BOOT_PENDING"),
  cefrFromId: PIECES.cefrFromId,
  cefrOf: extractFn(html, "cefrOf"),
  isInScope: extractFn(html, "isInScope"),
  normalizeWord: PIECES.normalizeWord,
  a1WordFromApi: PIECES.a1WordFromApi,
  a1WordsFromInline: PIECES.a1WordsFromInline,
  mergeA1ServerWords: extractFn(html, "mergeA1ServerWords"),
  markSchemaMigrated: extractFn(html, "markSchemaMigrated"),
  migrateSeedIdAliases: extractFn(html, "migrateSeedIdAliases"),
  backfillCoreWords: extractFn(html, "backfillCoreWords"),
  saveWords: extractFn(html, "saveWords"),
  saveCards: extractFn(html, "saveCards"),
  saveLog: extractFn(html, "saveLog"),
  saveWrong: extractFn(html, "saveWrong"),
  bootstrapA1Words: extractFn(html, "bootstrapA1Words"),
};
for (const [k, v] of Object.entries(P2)) {
  if (!v || v.length < 8) throw new Error(`切片 P2.${k} 长度异常（${v && v.length}），锚点可能失配`);
}
/* 防死测：切片必须是真实现，否则实现回退了探针照样绿 */
if (!/A1_SRC_KEY/.test(P2.bootstrapA1Words) || !/mergeA1ServerWords\(/.test(P2.bootstrapA1Words)) {
  throw new Error("bootstrapA1Words 切片里没有 A1_SRC_KEY / mergeA1ServerWords，切歪或实现回退了");
}
if (!/A1_BOOT_PENDING && S\.words\.length === 0/.test(P2.saveWords)) {
  throw new Error("saveWords 切片里没有「挂起 + 空表」兜底闸，切歪或实现回退了");
}

const STARTUP_SEG = html.split("loadAll();")[1].split("(async () => {")[0];
const HYDRATE_SEG = html.split("(async () => {")[1].split("if (updated) {")[1].split("console.log")[0];
for (const [name, seg] of [["同步启动段", STARTUP_SEG], ["hydrate 重载段", HYDRATE_SEG]]) {
  if (!/migrateSeedIdAliases\(\)/.test(seg) || !/backfillCoreWords\(\)/.test(seg)) {
    throw new Error(`${name} 切片里找不到 migrateSeedIdAliases / backfillCoreWords，锚点漂移`);
  }
}

/** 造一个全新沙箱：真实切片 + 可观测 localStorage 桩 + 可控 fetch。 */
function makeRuntime(fetchMode) {
  const store = new Map();
  const rec = { wordsWrites: [], saveCalls: [], writes: {}, fetchCalls: 0, toasts: [], inlineCalls: 0 };
  /* vm 内 console 一律走 stderr：--json 模式下 stdout 只能是那一个 JSON 对象，
   * bootstrapA1Words 的 console.log 绝不能污染 stdout。 */
  const vmConsole = {
    log: (...a) => console.error(...a),
    warn: (...a) => console.error(...a),
    error: (...a) => console.error(...a),
    info: (...a) => console.error(...a),
  };
  const sandbox = {
    console: vmConsole,
    location: { protocol: "http:" },
    __rec: rec,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => {
        store.set(k, String(v));
        rec.writes[k] = (rec.writes[k] || 0) + 1;
        if (k === "wb.words.v1") {
          try { rec.wordsWrites.push(JSON.parse(String(v))); } catch (e) { rec.wordsWrites.push(null); }
        }
      },
      removeItem: (k) => { store.delete(k); },
    },
    fetch: () => {
      rec.fetchCalls++;
      if (fetchMode === "server") return Promise.resolve({ ok: true, status: 200, json: async () => ({ words: ROWS }) });
      // down：服务不可用（连接被拒）—— bootstrap 的 try/catch 应吃掉并回退内联
      if (fetchMode === "down") return Promise.reject(new Error("ECONNREFUSED：本地服务未起"));
      return new Promise(() => {});   // 默认永挂：模拟首装挂在 await fetch
    },
    idbPut: () => {},
    wbsync: { push: () => {} },
    toast: (m) => rec.toasts.push(String(m)),
    renderWords: () => {},
    refilterReviewQueueForScope: () => {},
    renderHeaderBadge: () => {},
    renderReview: () => {},
    renderSettings: () => {},
    applyTheme: () => {},
    fsrsSelfTest: () => {},
    syncScopeControls: () => {},
    loadAll: () => {},   // idbHydrate 分支里 re-loadAll 用；场景 A 手工预置 S 状态，故置空
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(
    `var SEED_WORDS = ${JSON.stringify(SEED)};\nvar CORE_CUSTOM_WORDS = ${JSON.stringify(CUSTOM)};\n` +
      Object.values(P2).join("\n") + "\n" +
      "var __realSaveWords = saveWords;\n" +
      "saveWords = function () { __rec.saveCalls.push(JSON.parse(JSON.stringify(S.words))); return __realSaveWords.apply(this, arguments); };\n" +
      /* 内联兜底调用计数器：只 +1 并转发给真切片，不重抄实现 —— 用于证明
       * 「服务端可用时 a1WordsFromInline 一次都没被调用」。 */
      "var __realInline = a1WordsFromInline;\n" +
      "a1WordsFromInline = function () { __rec.inlineCalls++; return __realInline.apply(this, arguments); };\n",
    context,
    { filename: "workbench-a1-runtime-slices.js" }
  );
  return { context, rec };
}
const sb2 = (context, expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, context));

/* 场景 A：挂起期不落盘空表 / 半表 —— 真跑启动序切片，localStorage 桩记录 words payload。
 * 预置：K.words 缺失（未写）、cards 含别名 id a1-0544、S.words = []、A1_BOOT_PENDING = true，
 * 与 http 首装「挂在 await fetch」时的状态等价（fetch 永挂）。 */
{
  const runs = [];
  for (const [label, seg, filename] of [
    ["同步启动段", STARTUP_SEG, "startup-sync.js"],
    ["hydrate 重载段", HYDRATE_SEG, "startup-hydrate.js"],
  ]) {
    const { context, rec } = makeRuntime();
    vm.runInContext(
      'S.words = []; A1_BOOT_PENDING = true; S.cards = { "a1-0544": { reps: 3, due: 1000 } }; S.log = {}; S.wrong = {};',
      context
    );
    vm.runInContext(seg, context, { filename });
    runs.push({ label, rec });
  }
  const payloads = [];
  let cardsSaved = 0, logSaved = 0, wrongSaved = 0;
  for (const { rec } of runs) {
    payloads.push(...rec.saveCalls, ...rec.wordsWrites);   // saveCalls=落盘意图（闸前），wordsWrites=真实写入（闸后）
    cardsSaved += rec.writes["wb.cards.v1"] || 0;
    logSaved += rec.writes["wb.log.v1"] || 0;
    wrongSaved += rec.writes["wb.wrong.v1"] || 0;
  }
  const bad = payloads.filter(
    (p) => !(Array.isArray(p) && p.length > 0 && p.some((w) => String((w && w.id) || "").startsWith("a1-")))
  );
  const emptyCount = payloads.filter((p) => Array.isArray(p) && p.length === 0).length;
  const halfCount = payloads.filter(
    (p) => Array.isArray(p) && p.length > 0 && p.every((w) => String((w && w.id) || "").startsWith("core-"))
  ).length;
  check(
    "A 挂起期不落盘空表",
    bad.length === 0 && cardsSaved >= 2 && logSaved >= 2 && wrongSaved >= 2,
    `落盘 words 尝试=${payloads.length} 空表=${emptyCount} 半表=${halfCount} ` +
      `saveCards=${cardsSaved} saveLog=${logSaved} saveWrong=${wrongSaved}`
  );
}

/* 场景 A2：saveWords 统一兜底闸挡住「挂起 + 空表」直接落盘 */
{
  const { context, rec } = makeRuntime();
  vm.runInContext("S.words = []; A1_BOOT_PENDING = true;", context);
  vm.runInContext("saveWords();", context);
  const wrote = rec.writes["wb.words.v1"] || 0;
  check("A2 兜底闸挡住挂起空表", wrote === 0, `wb.words.v1 写入次数=${wrote}`);
}

/* 场景 B：inline 标记设备下次启动会重试（真跑 bootstrapA1Words 切片）——
 * 来源标记 = inline + 词表非空 + fetch 返回真实 rows：断言触发判定为真、合并不覆盖非空
 * （手编 ex/hw/ipa/letter 逐字保留）、补空字段、追加缺失 id、成功后标记升级为 server、
 * 绝不触碰 cards/log/wrong。 */
{
  const { context, rec } = makeRuntime("server");
  const target = ROWS.find((r) => String(r.id || "").startsWith("a1-") && r.ipa && r.letter) || ROWS[0];
  const other = ROWS.find((r) => r.id !== target.id && String(r.id || "").startsWith("a1-")) || ROWS[1];
  const existing = [
    { id: target.id, hw: "(HANDHW)", pos: "", gloss: "手编", zh: "手编", ipa: "",
      ex: [{ de: "HAND EX", zh: "手编例句" }], letter: "", page: 0, tags: ["a1", "core"], custom: false,
      up: 0, cefr: "A1", gender: null, plural: "" },
    { id: other.id, hw: "(KEEPHW)", pos: "", gloss: "手编2", zh: "手编2", ipa: "(KEEPIPA)",
      ex: [{ de: "KEEPEX", zh: "保留" }], letter: "(KEEP)", page: 0, tags: ["a1"], custom: false,
      up: 0, cefr: "A1", gender: null, plural: "" },
  ];
  vm.runInContext(
    `S.words = ${JSON.stringify(existing)};\n` +
      "A1_BOOT_PENDING = false;\n" +
      `S.cards = { "${target.id}": { reps: 5, due: 2000 } }; S.log = {}; S.wrong = {};\n` +
      'localStorage.setItem("wb.words.v1", JSON.stringify(S.words));\n' +
      'localStorage.setItem("wb.a1.src.v1", "inline");\n' +
      'localStorage.setItem("wb.schema.v1", "1");\n',
    context
  );
  await vm.runInContext("bootstrapA1Words()", context);
  const out = sb2(
    context,
    `{ fetchCalls: __rec.fetchCalls, marker: localStorage.getItem("wb.a1.src.v1"), len: S.words.length,
       w0: S.words.find(w => w.id === ${JSON.stringify(target.id)}),
       w2: S.words.find(w => w.id === ${JSON.stringify(other.id)}),
       cards: S.cards, cardsWrites: __rec.writes["wb.cards.v1"] || 0 }`
  );
  const ex0Ok = out.w0 && JSON.stringify(out.w0.ex) === JSON.stringify([{ de: "HAND EX", zh: "手编例句" }]);
  const w2Ok = !!out.w2 && out.w2.hw === "(KEEPHW)" && out.w2.ipa === "(KEEPIPA)" && out.w2.letter === "(KEEP)"
    && JSON.stringify(out.w2.ex) === JSON.stringify([{ de: "KEEPEX", zh: "保留" }]);
  const cardsOk = JSON.stringify(out.cards) === JSON.stringify({ [target.id]: { reps: 5, due: 2000 } })
    && out.cardsWrites === 0;
  check(
    "B inline 标记设备下次启动重试",
    out.fetchCalls >= 1 && out.marker === "server" && out.len === ROWS.length
      && !!out.w0 && out.w0.hw === "(HANDHW)" && ex0Ok && out.w0.ipa === target.ipa && out.w0.letter === target.letter
      && w2Ok && cardsOk,
    `fetch=${out.fetchCalls} marker=${out.marker} len=${out.len}/${ROWS.length} ` +
      `w0.hw=${out.w0 && out.w0.hw} w0.ex=${JSON.stringify(out.w0 && out.w0.ex)} ` +
      `w0.ipa=${out.w0 && out.w0.ipa}(期望${target.ipa}) w0.letter=${out.w0 && out.w0.letter}(期望${target.letter}) ` +
      `w2=${out.w2 && out.w2.hw}/${out.w2 && out.w2.ipa}/${out.w2 && out.w2.letter} cardsWrites=${out.cardsWrites}`
  );
}

/* 场景 C：内联仅作离线兜底（ADR-0014 §6-S3 裁决版）—— 真跑 bootstrapA1Words 源码切片，
 * 同一段实现跑两种情形对比：
 *   (a) fetch 成功             → 词表来自服务端（a1-0001 与服务端行一致），a1WordsFromInline 调用 **0** 次；
 *   (b) fetch 拒绝（服务不可用）→ 词表来自内联（a1WordsFromInline 调用 **1** 次），条数 704。
 * 调用次数由沙箱计数器桩给出（包住真切片：只 +1 并转发，探针里没有重抄实现）。
 * 场景价值：静态正则只能证明「代码长这样」，证明不了「服务端可用时那 682+22 条一次都没被用过」——
 * 裁决保留内联的前提就是它**只**在 file:// 直开 / 服务不可用这两条路上出场。 */
{
  const PROBE_ID = "a1-0001";
  const probeRow = ROWS.find((r) => r.id === PROBE_ID) || null;
  const runs = {};
  for (const mode of ["server", "down"]) {
    const { context } = makeRuntime(mode);
    vm.runInContext(
      "S.words = []; A1_BOOT_PENDING = true; S.cards = {}; S.log = {}; S.wrong = {};",
      context
    );
    await vm.runInContext("bootstrapA1Words()", context);
    runs[mode] = sb2(
      context,
      `{ inlineCalls: __rec.inlineCalls, fetchCalls: __rec.fetchCalls, len: S.words.length,
         marker: localStorage.getItem("wb.a1.src.v1"), toasts: __rec.toasts,
         probe: (S.words.find(function (w) { return w.id === ${JSON.stringify(PROBE_ID)}; }) || null) }`
    );
  }
  const a = runs.server;
  const b = runs.down;
  const hwFromServer = !!a.probe && !!probeRow && a.probe.hw === probeRow.hw;
  check(
    "C1 内联仅作离线兜底：服务端可用时内联零调用",
    a.inlineCalls === 0 && a.fetchCalls === 1 && a.len === ROWS.length && hwFromServer
      && a.marker === "server" && a.toasts.length === 0,
    `inlineCalls=${a.inlineCalls} fetchCalls=${a.fetchCalls} len=${a.len}/${ROWS.length} ` +
      `${PROBE_ID}.hw=${a.probe && a.probe.hw}（服务端行=${probeRow && probeRow.hw}） ` +
      `marker=${a.marker} toasts=${a.toasts.length}`,
    { inlineCalls: a.inlineCalls, len: a.len, marker: a.marker, hw: (a.probe && a.probe.hw) || null }
  );
  check(
    "C2 内联仅作离线兜底：服务不可用时兜底一次",
    b.inlineCalls === 1 && b.fetchCalls === 1 && b.len === SEED.length + CUSTOM.length && b.len === 704
      && b.marker === "inline" && b.toasts.length === 1,
    `inlineCalls=${b.inlineCalls} fetchCalls=${b.fetchCalls} len=${b.len}/${SEED.length + CUSTOM.length} ` +
      `marker=${b.marker} toasts=${b.toasts.length}`,
    { inlineCalls: b.inlineCalls, len: b.len, marker: b.marker }
  );
}

/* ---------------------------------------------------------------------------
 * 5. 汇总
 * ------------------------------------------------------------------------ */
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ fail: failCount, total: cases.length, cases }));
} else {
  console.log("");
  if (failCount > 0) {
    console.log(`FAIL 汇总：${failCount} 个场景未通过`);
    process.exitCode = 1;
  } else {
    console.log(`ALL PASS：A1 首装映射（服务端 ${ROWS.length} 条 vs 内联 ${SEED.length + CUSTOM.length} 条）自检通过`);
  }
}
