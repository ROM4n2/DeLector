/**
 * enc_known_lemmas_dedupe_probe.mjs —— fetchKnownLemmas 的 in-flight 去重行为探针
 *
 * 债（清债轮 B 债 3）：`fetchKnownLemmas()` 无模块级 promise、无缓存 ⇒ **无并发去重**。
 * 调用点只有 2 处：showView 的 `Promise.allSettled`、renderTextDetailAnnotated 的
 * `Promise.all([resolveDeck(), fetchKnownLemmas()])`，两处都不传 opts。
 * ⇒ 一次会话读 N 篇短文 = **N+1 次** `GET /api/cards/known-lemmas`（进场 1 + 每篇 1）；
 * 后端 `delector/routes/main.py:762 get_known_lemmas()` **无缓存**，每次都 SELECT。
 *
 * 本探针把 encounter.js **真源码**剥 import/export 后进 node:vm 真跑（不重抄实现），
 * 配一个「按 URL 精确 hold 队列 + 记录 signal」的桩 api()（桩法参照
 * tools/enc_open_race_probe.mjs），逐条断言去重语义：
 *   A1 并发去重：两次**并发**调用 ⇒ api("/api/cards/known-lemmas") 只被调 1 次，
 *      且两个调用方拿到**同一个数组实例**（真复用，不是各拉一次后碰巧相等）。
 *   A2 不做 TTL 缓存：两次**串行**调用（等第一次 settle 后再调）⇒ 调 2 次
 *      （防过度实现：TTL/永久缓存会让「刚背的词在 TTL 内不出现」，是 UX 回归）。
 *   A3 失败后可重试：in-flight 期间失败 ⇒ 失败后下一次调用**重新请求**并拿到数据
 *      （证明 finally 清空生效，不是把失败结果永久缓存）。
 *   A4 抢占不废掉共享请求：共享 promise 的请求**不带 signal**（本函数不接收 opts），
 *      且外部 AbortController.abort() 之后，两个调用方**仍都能拿到结果**。
 *   A5 返回形状逐字不变：Array.isArray 恒真；非数组 lemmas / 无信封 / 请求失败 ⇒ []。
 *
 * 用法：
 *   node tools/enc_known_lemmas_dedupe_probe.mjs            # 人类可读
 *   node tools/enc_known_lemmas_dedupe_probe.mjs --json     # {failures,total,cases:[…]}
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const KNOWN_URL = "/api/cards/known-lemmas";
const ENC_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "encounter.js"), "utf8");

/* 剥 import（跨行多行具名导入）/ export 前缀（与既有 encounter 探针同一套转换器）。 */
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

const LEMMAS = ["Haus", "Zug", "Fenster"];

/* ── 沙箱 ─────────────────────────────────────────────────────────────────── */
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
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] != null ? this.attrs[k] : null; },
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
 * 一次场景一个独立环境（模块级 _knownLemmasInFlight / 降级标志互不污染）。
 * net.held: url -> [{resolve, reject}]（按 URL 精确 hold；空数组 = 放行）
 * net.mode: 'ok' | 'nonarray' | 'noenvelope' | 'throw'
 */
function newEnv() {
  const doc = makeDocumentStub();
  const net = {
    held: new Map(),
    requests: [],   // {url, signal}
    mode: "ok",
  };

  function fixtureFor(u) {
    if (u !== KNOWN_URL) return {};
    if (net.mode === "nonarray") return { lemmas: "nope" };
    if (net.mode === "noenvelope") return null;
    return { lemmas: LEMMAS.slice() };
  }

  function api(url, opts = {}) {
    const u = String(url);
    const signal = opts && opts.signal ? opts.signal : null;
    net.requests.push({ url: u, signal });
    const q = net.held.get(u);
    if (q) {
      let resolve, reject;
      const p = new Promise((res, rej) => { resolve = res; reject = rej; });
      q.push({ resolve, reject });
      return p;
    }
    if (net.mode === "throw") return Promise.reject(new Error("Failed to fetch"));
    return Promise.resolve(fixtureFor(u));
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
    // ── 被剥离模块的桩 ──
    esc: (s) => String(s == null ? "" : s),
    notify() {},
    playGermanAudio() {},
    loadDeck: () => ({ words: [{ id: "l1", hw: "Haus" }], cards: { l1: { reps: 2 } } }),
    mergeServerDeck: (d) => d,
    addCardToDeck: () => ({ deck: {} }),
    buildKnownSet: () => new Set(["haus"]),
    mergeKnownLemmas: (a) => a,
    annotateWithDeck: () => ({ sentences: [], stats: { total_tokens: 1, known_tokens: 0, known_rate: 0 } }),
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

const flush = async (n = 20) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r));
};
const call = (ctx) => vm.runInContext("fetchKnownLemmas()", ctx);
const countKnown = (net) => net.requests.filter((r) => r.url === KNOWN_URL).length;
/**
 * 释放该 URL 上**所有**在飞请求（修复前可能有多个，修复后只有一个）。
 * 每个请求给**各自独立**的 lemmas 数组副本 ⇒ 靠引用相等就能分辨「复用了同一次请求」
 * 还是「各拉了一次、只是内容碰巧一样」（否则 A1-same-instance 恒真，失去判别力）。
 */
const releaseHeld = (net, url, factory = () => ({ lemmas: LEMMAS.slice() })) => {
  for (const entry of net.held.get(url) || []) entry.resolve(factory());
};
const rejectHeld = (net, url, err) => {
  for (const entry of net.held.get(url) || []) entry.reject(err);
};

/* ── 断言收集 ─────────────────────────────────────────────────────────────── */
const problems = [];
const cases = [];
const record = (name, ok, msg) => {
  cases.push({ name, ok });
  if (!ok) problems.push(`[${name}] ${msg}`);
};

/* ══ A1 两次并发调用 ⇒ 只打一次后端 ════════════════════════════════════════ */
{
  const { ctx, net } = newEnv();
  net.held.set(KNOWN_URL, []);
  const p1 = call(ctx);
  const p2 = call(ctx);
  await flush(2);
  const n = countKnown(net);
  if (n !== 1) {
    record("A1", false, `并发调用打了 ${n} 次 ${KNOWN_URL}（期望 1）—— 没有 in-flight 去重`);
  } else {
    record("A1", true, "");
  }
  const q = net.held.get(KNOWN_URL);
  if (q.length < 1) {
    record("A1-shared-request", false, "桩没有收到任何在飞请求，无法释放");
  } else {
    record("A1-shared-request", true, "");
  }
  releaseHeld(net, KNOWN_URL);
  await flush(10);
  const [r1, r2] = [await p1, await p2];
  const same = Array.isArray(r1) && r1 === r2;   // 同一实例 ⇒ 真的复用了同一次请求
  if (!same) {
    record("A1-same-instance", false, "两个调用方拿到的不是同一个数组实例（只是碰巧相等）");
  } else {
    record("A1-same-instance", true, "");
  }
  if (JSON.stringify(r1) !== JSON.stringify(LEMMAS)) {
    record("A1-payload", false, `复用结果内容不对：${JSON.stringify(r1)}`);
  } else {
    record("A1-payload", true, "");
  }
}

/* ══ A2 两次串行调用 ⇒ 仍打两次（证明没做成 TTL/永久缓存）══════════════════ */
{
  const { ctx, net } = newEnv();
  const r1 = await call(ctx);
  const r2 = await call(ctx);
  const n = countKnown(net);
  if (n !== 2) {
    record("A2", false, `串行调用只打了 ${n} 次（期望 2）—— 被做成了 TTL/永久缓存；` +
      `新背的词会在 TTL 内不出现（覆盖率与高亮滞后于用户刚做的动作）`);
  } else {
    record("A2", true, "");
  }
  if (JSON.stringify(r1) !== JSON.stringify(LEMMAS) || JSON.stringify(r2) !== JSON.stringify(LEMMAS)) {
    record("A2-payload", false, "串行两次的内容不对");
  } else {
    record("A2-payload", true, "");
  }
}

/* ══ A3 in-flight 期间失败 ⇒ 之后重新请求（finally 清空生效）════════════════ */
{
  const { ctx, net } = newEnv();
  net.held.set(KNOWN_URL, []);
  const pBad = call(ctx);
  await flush(2);
  rejectHeld(net, KNOWN_URL, new Error("Failed to fetch"));
  const first = await pBad;
  if (!Array.isArray(first) || first.length !== 0) {
    record("A3-first", false, `失败时没有退化为 []：${JSON.stringify(first)}`);
  } else {
    record("A3-first", true, "");
  }
  // 释放 hold（第二次请求放行）+ 恢复 ok 模式
  net.held.delete(KNOWN_URL);
  net.mode = "ok";
  const second = await call(ctx);
  const n = countKnown(net);
  if (n !== 2) {
    record("A3-retry", false, `失败后再调没有重新请求（共 ${n} 次，期望 2）—— ` +
      `失败结果被永久缓存了（finally 未清空 / catch 未清空）`);
  } else {
    record("A3-retry", true, "");
  }
  if (JSON.stringify(second) !== JSON.stringify(LEMMAS)) {
    record("A3-retry-payload", false, `重试没有拿到真实数据：${JSON.stringify(second)}`);
  } else {
    record("A3-retry-payload", true, "");
  }
}

/* ══ A4 抢占不废掉共享请求（无 signal + 外部 abort 后仍拿到结果）═══════════ */
{
  const { ctx, net } = newEnv();
  net.held.set(KNOWN_URL, []);
  const p1 = call(ctx);
  const p2 = call(ctx);
  await flush(2);
  const req = net.requests.filter((r) => r.url === KNOWN_URL)[0];
  if (req && req.signal) {
    record("A4-no-signal", false, "known-lemmas 请求带上了 signal —— 共享 promise 会被某个调用方的 " +
      "AbortController 连带 abort 掉（fetchKnownLemmas 不接收 opts，天然不该有 signal）");
  } else {
    record("A4-no-signal", true, "");
  }
  // 模拟「其中一个调用方被抢占」：外部 AbortController.abort()（= beginOpen 的旧 ctrl）
  const victim = new AbortController();
  victim.abort();
  releaseHeld(net, KNOWN_URL);
  await flush(10);
  const [r1, r2] = await Promise.all([p1, p2]);
  if (JSON.stringify(r1) === JSON.stringify(LEMMAS) && JSON.stringify(r2) === JSON.stringify(LEMMAS)) {
    record("A4", true, "");
  } else {
    record("A4", false, `抢占（abort）废掉了共享请求：p1=${JSON.stringify(r1)} p2=${JSON.stringify(r2)}`);
  }
}

/* ══ A5 返回形状逐字不变 ══════════════════════════════════════════════════ */
{
  const { ctx, net } = newEnv();
  const ok = await call(ctx);
  record("A5-array", Array.isArray(ok), "正常返回不是数组");
  record("A5-passthrough", JSON.stringify(ok) === JSON.stringify(LEMMAS), "正常返回的内容不是 res.lemmas 原样");

  const env2 = newEnv();
  env2.net.mode = "nonarray";
  const bad = await call(env2.ctx);
  record("A5-nonarray", Array.isArray(bad) && bad.length === 0, `lemmas 非数组时没有退化为 []：${JSON.stringify(bad)}`);

  const env3 = newEnv();
  env3.net.mode = "noenvelope";
  const none = await call(env3.ctx);
  record("A5-noenvelope", Array.isArray(none) && none.length === 0, `无信封时没有退化为 []：${JSON.stringify(none)}`);

  const env4 = newEnv();
  env4.net.mode = "throw";
  const failed = await call(env4.ctx);
  record("A5-throw", Array.isArray(failed) && failed.length === 0, `请求失败时没有退化为 []：${JSON.stringify(failed)}`);
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
    process.stderr.write(`fetchKnownLemmas in-flight 去重契约破坏：\n  - ${problems.join("\n  - ")}\n`);
    process.exit(1);
  }
  console.log(`✅ PASS: fetchKnownLemmas in-flight 去重（${total} 项，含「未做成 TTL 缓存」的反向断言）`);
}
