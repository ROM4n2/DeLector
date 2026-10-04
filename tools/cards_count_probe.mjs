/**
 * cards_count_probe.mjs —— 卡片角标计数「打计数端点而非拉全量」行为探针
 *
 * 性能事故回归（子计划 1 / Task 1）：refreshCardCounters 过去为了显示一个数字而请求
 * GET /api/cards —— 那条路径是 SELECT * 全表 + 逐卡 get_fsrs_next_intervals 递推
 * （O(N) 行物化 + O(N) 次递推），且它挂在 7 个「每次存卡后」的调用点上
 * ⇒ 存 N 张卡是 O(N²) 的写路径放大。改为 GET /api/cards/counts（每表 1 次聚合）。
 *
 * 硬约束：探针里**不得重抄一份实现**。被测逻辑一律来自 static/js/reader.js 真源码
 * （剥 import/export 后进 node:vm），本文件只提供 document/api 桩。
 *
 * 三条断言：
 *   A. 路径：被请求的 path 是 /api/cards/counts，且**不是** /api/cards。
 *   B. 取值：桩返回 {total: 7} ⇒ card-count 与 mob-card-count **都**变成 7。
 *   C. 失败静默：桩抛错 ⇒ 角标**保持原值 42 不被清 0**。
 *   D. 字段不静默丢弃：返回体缺 total（代理截断）⇒ MUST 走 catch 兜底，
 *      MUST NOT 把 "undefined"/"null" 写进角标。
 *
 * 冻结契约（断言护栏，防修复面过宽）：
 *   E. refreshCardCounters 的签名/导出形态不变（仍是零参 async 函数）。
 *   F. 只消费 total —— vocab_total/grammar_total/vocab_mastered/grammar_mastered
 *      当前无消费方，本任务 MUST NOT 把它们拼进角标。
 *
 * 用法：
 *   node tools/cards_count_probe.mjs            # 人类可读
 *   node tools/cards_count_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

const fail = (problems) => {
  process.stderr.write("卡片角标计数契约破坏（子计划 1 Task 1）：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
};

const readerJs = fs.readFileSync(path.join(ROOT, "static", "js", "reader.js"), "utf8");

/* 剥 import/export（同 wb_cards_vocab_unwrap_probe.mjs 的转换器口径） */
const transformed = readerJs
  .replace(/^import[^\n]*from[^\n]*;[^\S\n]*$/gm, "")
  .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
const stripProblems = [];
if (/^import\b/m.test(transformed)) stripProblems.push("reader.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
if (/^\s*export\b/m.test(transformed)) stripProblems.push("reader.js 剥离后仍有 export（探针转换器跟不上源码形态）");
for (const must of ["async function refreshCardCounters", 'getElementById("card-count")', 'getElementById("mob-card-count")']) {
  if (!transformed.includes(must)) stripProblems.push(`reader.js 剥离切片缺 "${must}"（实现回退或切歪）`);
}
if (stripProblems.length) fail(stripProblems);

/* ---- 服务端真实返回体形状（GET /api/cards/counts 的产出） ---- */
const COUNTS_BODY = {
  vocab_total: 12,
  vocab_mastered: 3,
  grammar_total: 4,
  grammar_mastered: 1,
  total: 16,
};
/* 场景 B 只喂 total（断言 F：另 4 字段无消费方，角标必须只等于 total） */
const TOTAL_ONLY_BODY = { total: 7 };

const BADGE_IDS = ["card-count", "mob-card-count"];
const PRESET = 42; /* 场景 C/D 的角标旧值 */

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", disabled: false, style: { setProperty() {} },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}

/** document 桩：预置两个角标到 PRESET，其余 getElementById 按需造。 */
function makeDocumentStub(prefillBadges) {
  const registry = new Map();
  if (prefillBadges) for (const id of BADGE_IDS) registry.set(id, makeEl(id));
  return {
    registry,
    getElementById(id) {
      if (!registry.has(id)) registry.set(id, makeEl(id));
      return registry.get(id);
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    createElement(tag) { return makeEl(`__created__${tag}`); },
    body: { appendChild() {}, classList: { add() {}, remove() {}, toggle() {} } },
  };
}

/**
 * 构造沙箱。handler(url) 决定桩 api 的行为：返回对象 = 成功，抛错 = 失败。
 * 每笔请求进 __fetches 供断言 A 用。
 */
function buildCtx(handler) {
  const sandbox = {
    console: JSON_MODE ? { log() {}, error() {}, warn() {} } : console,
    document: makeDocumentStub(true),
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Promise, Set, Map,
    parseInt, parseFloat, isNaN, isFinite,
    setTimeout() { return 0; },
    clearTimeout() {},
    alert() {},
    // ↓ 被剥离的模块导入桩（core / player / companion）
    state: {},
    esc: (s) => String(s ?? ""),
    jsAttr: (v) => JSON.stringify(v == null ? "" : v),
    normalizeCefrPct: (v) => v,
    notify() {},
    ShadowPlayer: class {},
    playGermanAudio() {},
    Companion: { celebrate() {} },
    localStorage: {
      _m: new Map(),
      getItem(k) { return this._m.has(String(k)) ? this._m.get(String(k)) : null; },
      setItem(k, v) { this._m.set(String(k), String(v)); },
      removeItem(k) { this._m.delete(String(k)); },
    },
  };
  sandbox.api = async (url) => {
    sandbox.__fetches.push(String(url));
    return handler(String(url));
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext("var __fetches = [];", ctx, { filename: "counts-prelude.js" });
  return ctx;
}

/** 跑一次 refreshCardCounters，返回 {fetches, badges}。 */
async function run(handler, prefillBadges = true) {
  const ctx = buildCtx(handler);
  for (const id of BADGE_IDS) {
    if (prefillBadges) ctx.document.getElementById(id).textContent = PRESET;
    else ctx.document.getElementById(id).textContent = "";
  }
  vm.runInContext(transformed, ctx, { filename: "reader.stripped.js" });
  const err = vm.runInContext(
    "(async () => { try { await refreshCardCounters(); return null; } catch (e) { return String(e && e.message || e); } })()",
    ctx
  );
  const rejection = await err;
  const fetches = JSON.parse(vm.runInContext("JSON.stringify(__fetches)", ctx));
  const badges = {};
  for (const id of BADGE_IDS) badges[id] = ctx.document.getElementById(id).textContent;
  return { fetches, badges, rejection };
}

const tick = () => new Promise((r) => process.nextTick(r));

const problems = [];
const results = {};

/* ═══ 断言 A + B：请求 /api/cards/counts 并把 total 写进两个角标 ═══ */
const a = await run((url) => {
  /* 计数端点给真实全量返回体；旧全量端点也给一份，故意让「误打 /api/cards」红得清楚 */
  if (url.includes("/api/cards/counts")) return COUNTS_BODY;
  return { vocab_cards: new Array(12).fill({ id: 1 }), grammar_cards: new Array(4).fill({ id: 2 }) };
});
await tick();
log(`[A/B] fetch: ${a.fetches.join(" | ")}`);
log(`[A/B] badges: ${JSON.stringify(a.badges)}`);
results.requestedPaths = a.fetches;
results.badges = a.badges;

if (a.rejection !== null)
  problems.push(`refreshCardCounters 在计数端点正常返回时抛出未捕获异常：${a.rejection}（MUST 静默成功）`);
if (!a.fetches.includes("/api/cards/counts"))
  problems.push(`refreshCardCounters 未请求 /api/cards/counts，实际请求 ${JSON.stringify(a.fetches)}（角标必须走计数端点，不得再拉全量卡片）`);
if (a.fetches.some((u) => u.trim() === "/api/cards"))
  problems.push(`refreshCardCounters 仍请求 GET /api/cards（${JSON.stringify(a.fetches)}）—— 为拿一个 length 拉全表 + 逐卡 FSRS 递推，存卡写路径放大为 O(N²)`);

/* ═══ 断言 B'（取值）：桩只给 {total: 7} ⇒ 两个角标都必须是 7 ═══ */
const b = await run(() => TOTAL_ONLY_BODY);
await tick();
log(`[B'] fetch: ${b.fetches.join(" | ")}`);
log(`[B'] badges: ${JSON.stringify(b.badges)}`);
results.totalOnly = { paths: b.fetches, badges: b.badges };
for (const id of BADGE_IDS) {
  if (b.badges[id] !== "7" && b.badges[id] !== 7)
    problems.push(`角标 ${id} 未显示 total=7，实际 ${JSON.stringify(b.badges[id])}（角标必须取 data.total）`);
}

/* ═══ 断言 C（失败静默）：桩抛错 ⇒ 角标保持 42，MUST NOT 被清 0 ═══ */
const c = await run(() => { throw new Error("stub network down"); });
await tick();
log(`[C] fetch: ${c.fetches.join(" | ")}`);
log(`[C] badges: ${JSON.stringify(c.badges)}`);
results.failureSilent = { paths: c.fetches, badges: c.badges };
for (const id of BADGE_IDS) {
  const v = c.badges[id];
  if (v === 0 || v === "0")
    problems.push(`角标 ${id} 在计数请求失败时被写成 0（实际 ${JSON.stringify(v)}）—— catch MUST 静默保留旧值，MUST NOT 把已知计数抹成 0`);
  else if (v !== PRESET && v !== PRESET.toString())
    problems.push(`角标 ${id} 在计数请求失败后未保持旧值 ${PRESET}，实际 ${JSON.stringify(v)}（失败静默 = 保留旧值）`);
}
if (c.rejection !== null)
  problems.push(`refreshCardCounters 在计数请求失败时把错误抛出了函数外：${c.rejection}（catch MUST 保持静默）`);

/* ═══ 断言 D（字段不静默丢弃）：返回体缺 total ⇒ 走 catch 兜底，MUST NOT 显示 undefined ═══ */
const d = await run(() => ({ vocab_total: 12, grammar_total: 4 }));
await tick();
log(`[D] fetch: ${d.fetches.join(" | ")}`);
log(`[D] badges: ${JSON.stringify(d.badges)}`);
results.missingTotal = { paths: d.fetches, badges: d.badges };
for (const id of BADGE_IDS) {
  const v = d.badges[id];
  if (v === undefined || v === "undefined" || v === null || v === "null" || v === "" || v === 0 || v === "0")
    problems.push(`返回体缺 total 时角标 ${id} 被写成 ${JSON.stringify(v)} —— MUST 走 catch 兜底保留旧值 ${PRESET}，MUST NOT 显示 undefined/0`);
  else if (v !== PRESET && v !== PRESET.toString())
    problems.push(`返回体缺 total 时角标 ${id} 未回退保留旧值 ${PRESET}，实际 ${JSON.stringify(v)}`);
}

/* ═══ 断言 E（签名/导出冻结）：仍是零参 async 函数 ═══ */
const sigCtx = buildCtx(() => ({}));
vm.runInContext(transformed, sigCtx, { filename: "reader.stripped.js#arity" });
const sig = vm.runInContext("String(refreshCardCounters.length)", sigCtx);
log(`[E] arity: ${sig}`);
results.arity = Number(sig);
if (sig !== "0")
  problems.push(`refreshCardCounters 的参数个数变成 ${sig}（签名 MUST NOT 变——7 个调用点跨 5 个模块全部零改动）`);

/* ═══ 断言 F（只用 total）：全量返回体下角标必须是 16，不得拼 12+4=16 之外的任何组合 ═══ */
const f = await run(() => COUNTS_BODY);
await tick();
log(`[F] badges: ${JSON.stringify(f.badges)}`);
results.onlyTotal = { paths: f.fetches, badges: f.badges };
for (const id of BADGE_IDS) {
  const v = f.badges[id];
  /* 合法取值：total(16) / vocab_total(12) / grammar_total(4) / 12+4=16。
   * 本任务 MUST 只用 total；vocab_total / grammar_total 当前无消费方。 */
  if (v !== "16" && v !== 16)
    problems.push(`全量返回体下角标 ${id} 显示 ${JSON.stringify(v)}，应为 total=16（只消费 total，不拼另 4 字段）`);
}

if (problems.length) fail(problems);

const out = {
  ok: true,
  counts: {
    endpoint: "/api/cards/counts",
    requestedPaths: results.requestedPaths,
    legacyEndpointNotUsed: !results.requestedPaths.some((u) => u.trim() === "/api/cards"),
    badgesFromTotalOnly: results.totalOnly.badges,
    badgesBothWritten: BADGE_IDS.every((id) => String(results.badges[id]) === "16"),
    onlyTotalConsumed: results.onlyTotal.badges,
    failureSilent: results.failureSilent.badges,
    missingTotalFallback: results.missingTotal.badges,
    arityPreserved: results.arity === 0,
    noUndefinedOnMissingTotal: BADGE_IDS.every((id) => String(results.missingTotal.badges[id]) === String(PRESET)),
  },
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("角标请求路径:", JSON.stringify(out.counts.requestedPaths));
  console.log("旧全量端点未使用:", out.counts.legacyEndpointNotUsed);
  console.log("只给 total 时角标:", JSON.stringify(out.counts.badgesFromTotalOnly));
  console.log("两角标均写入:", out.counts.badgesBothWritten);
  console.log("只消费 total:", JSON.stringify(out.counts.onlyTotalConsumed));
  console.log("失败静默(保留旧值 42):", JSON.stringify(out.counts.failureSilent));
  console.log("缺 total 时兜底:", JSON.stringify(out.counts.missingTotalFallback));
  console.log("零参签名保持:", out.counts.arityPreserved);
  console.log("✅ PASS: 角标走 /api/cards/counts 取 total，两角标同步，失败/缺字段静默保留旧值");
}