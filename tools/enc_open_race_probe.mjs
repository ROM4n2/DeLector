/**
 * enc_open_race_probe.mjs —— 遇见区 openText 重入竞态行为探针
 *
 * 事故（2026-10-04 子计划 3 Task 1）：annotate 端点「P0 直跑、禁缓存」（spaCy 每次真跑），
 * renderTextDetailAnnotated 内还有 await Promise.all([resolveDeck(), fetchKnownLemmas()])
 * ⇒ 单次 openText 最坏 3 次 RTT + 1 次全量标注，窗口是**秒级**。此窗口内：
 *   ① renderReaderShell 整体覆写 rd.innerHTML，晚到的响应必定覆盖先到的；
 *   ② markRead 幂等写盘且不判断「是不是用户最后点的那个」⇒ 两篇都被记已读，
 *      晚到那篇被 pickUnread 永久剔出 i+1 推荐；
 *   ③ catch 分支同样整体覆写 rd.innerHTML ⇒ A 的失败提示能盖掉 B 的成功正文。
 *
 * 本探针把 encounter.js **真源码**剥 import/export 后进 node:vm 真跑（不重抄实现），
 * 配一个「可控 resolve 时序 + 记录 signal」的桩 api()，逐条断言竞态语义：
 *   A  后点者胜：B 先到并上屏，A 的晚到响应不得覆写、不得 markRead(A)，只 markRead(B)；
 *   A2 catch 不越权：A 的请求在 B 上屏之后失败，其失败提示不得盖掉 B 的正文；
 *   B  覆写前守卫生效：A 已在 renderTextDetailAnnotated 内部 await 处被抢占、B 先上屏，
 *      A 恢复后不得覆写 DOM（这是「第二道守卫在覆写点之前」的唯一有效位置）；
 *   C  取消旧 in-flight：第二次 openText 必须 abort 第一次的 ctrl.signal；
 *   D  跨调用：showView 复用同一 seq ⇒ 上一次调用的晚到列表响应不得覆写。
 *
 * 用法：
 *   node tools/enc_open_race_probe.mjs            # 人类可读
 *   node tools/enc_open_race_probe.mjs --json     # stdout 只输出 JSON
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
const CORE_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "core.js"), "utf8");

/* 剥 import（encounter.js 的 import 块是跨行的多行具名导入）/ export 前缀。 */
function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
}
const transformed = strip(ENC_SRC);
if (/^import\b/m.test(transformed)) fail("encounter.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
if (/^\s*export\b/m.test(transformed)) fail("encounter.js 剥离后仍有 export（探针转换器跟不上源码形态）");

/* ── 夹具 ─────────────────────────────────────────────────────────────────── */
const TEXTS = [
  { id: 2, title: "TITLE-B", level: "A2", source: "probe", word_count: 3, content: "b b b" },
  { id: 1, title: "TITLE-A", level: "A2", source: "probe", word_count: 3, content: "a a a" },
];

function annotateOf(id) {
  return {
    sentences: [
      {
        idx: 0,
        tokens: [
          { text: `w${id}`, lemma: `w${id}`, pos: "NOUN", known: false },
          { text: "x", lemma: "x", pos: "NOUN", known: true },
        ],
      },
    ],
  };
}

function fixtureFor(u) {
  if (/\/api\/encounter\/texts\/\d+\/annotate$/.test(u)) {
    const id = Number(u.match(/\/texts\/(\d+)\/annotate$/)[1]);
    return annotateOf(id);
  }
  // fetchIndex / fetchTexts 都要 { items } / { texts } 信封（源码里是 (res && res.items) || []）。
  if (/\/api\/encounter\/texts\/index$/.test(u)) {
    return { items: TEXTS.map((t) => ({ id: t.id, total_tokens: 3, lemma_seq: [1, 2, 3] })) };
  }
  if (/\/api\/encounter\/texts$/.test(u)) return { texts: TEXTS.map((t) => ({ ...t })) };
  if (/\/api\/encounter\/texts\/\d+$/.test(u)) {
    const id = Number(u.match(/\/texts\/(\d+)$/)[1]);
    return { ...TEXTS.find((t) => t.id === id) };
  }
  if (/\/api\/cards\/known-lemmas$/.test(u)) return { lemmas: ["x"] };
  if (/\/api\/wb\/state$/.test(u)) return {};
  throw new Error(`桩 api 未覆盖的 URL：${u}`);
}

/* ── 沙箱 ─────────────────────────────────────────────────────────────────── */
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
 * 一次探针场景的独立环境（模块级 _openSeq/_openCtrl 状态互不污染）。
 * net.abortMode: 'ignore' = 桩忽略 abort（模拟「响应已算出、abort 来不及」），
 *                'reject'  = 桩真按 signal 拒绝（模拟浏览器真实行为）。
 */
function newEnv() {
  const doc = makeDocumentStub();
  const net = {
    held: new Map(),   // url -> [{resolve, reject}]
    requests: [],      // {url, signal}
    abortMode: "ignore",
  };

  function api(url, opts = {}) {
    const u = String(url);
    const signal = opts && opts.signal ? opts.signal : null;
    net.requests.push({ url: u, signal });
    const value = fixtureFor(u);

    const q = net.held.get(u);
    if (q) {
      let resolve, reject;
      const p = new Promise((res, rej) => { resolve = res; reject = rej; });
      const entry = { resolve, reject };
      q.push(entry);
      if (signal) {
        const onAbort = () => {
          if (net.abortMode === "reject") {
            const idx = q.indexOf(entry);
            if (idx >= 0) q.splice(idx, 1);
            const err = new Error("The operation was aborted.");
            err.name = "AbortError";
            reject(err);
          }
        };
        if (signal.aborted) onAbort();
        else signal.addEventListener("abort", onAbort, { once: true });
      }
      return p;
    }
    if (signal && signal.aborted) {
      const err = new Error("The operation was aborted.");
      err.name = "AbortError";
      return Promise.reject(err);
    }
    return Promise.resolve(value);
  }

  const marked = [];   // markRead 调用记录（id 序列）
  const storage = { getItem: () => null, setItem() {}, removeItem() {} };

  const sandbox = {
    console,
    document: doc,
    window: { localStorage: storage },
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
    loadDeck: () => ({ words: [{ word: "x", lemma: "x", pos: "NOUN" }], cards: { x: { lemma: "x" } } }),
    mergeServerDeck: (d) => d,
    addCardToDeck: () => ({ deck: {} }),
    buildKnownSet: () => new Set(["x"]),
    mergeKnownLemmas: (a) => a,
    annotateWithDeck: (deck, annotate) => ({
      sentences: annotate.sentences,
      stats: { total_tokens: 3, known_tokens: 1, known_rate: 1 / 3 },
    }),
    DECK_KEYS: { words: "wb.words.v1", cards: "wb.cards.v1" },
    rankEntries: (knownSet, merged) =>
      merged.map((m) => ({ entry: m, available: true, band: "i1", rate: 0.5, topPick: true })),
    hasCoverage: () => true,
    loadRead: () => ({}),
    isRead: () => false,
    pickUnread: (ranked) => (ranked && ranked.length ? ranked[0] : null),
    markRead: (st, id, ts) => { marked.push({ id, ts }); },
    PULL_ENDPOINT: "/api/encounter/pull-pack",
    normalizeDesktopBase: (s) => s,
    readDesktopBase: () => "",
    writeDesktopBase() {},
    mapPackRows: () => [],
    pullPackRequest: () => ({}),
  };

  const ctx = vm.createContext(sandbox);
  return { ctx, doc, net, marked, sandbox };
}

const flush = async (n = 20) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r));
};

const readerHtml = (doc) => String(doc.registry.get("encounter-reader").innerHTML);
const listHtml = (doc) => String(doc.registry.get("encounter-text-list").innerHTML);

const problems = [];

/* ══ 场景 A：后点者胜（桩忽略 abort ⇒ 走 seq 守卫，不走 catch） ═════════════ */
{
  const { ctx, doc, net, marked } = newEnv();
  vm.runInContext(transformed, ctx, { filename: "encounter.js#A" });
  net.abortMode = "ignore";
  net.held.set("/api/encounter/texts/1", []);
  net.held.set("/api/encounter/texts/1/annotate", []);

  vm.runInContext("openText(1)", ctx);          // A 慢
  await flush(2);
  vm.runInContext("openText(2)", ctx);          // B 快
  await flush(2);

  // B 的两个请求未被 hold ⇒ 立即 resolve；等它上屏
  await flush(20);
  if (!readerHtml(doc).includes("TITLE-B")) {
    problems.push("[A] B 未上屏（reader 正文没有 TITLE-B）—— 桩/时序失配，探针本身不可信");
  }

  // A 晚到
  net.held.get("/api/encounter/texts/1")[0].resolve(fixtureFor("/api/encounter/texts/1"));
  net.held.get("/api/encounter/texts/1/annotate")[0].resolve(fixtureFor("/api/encounter/texts/1/annotate"));
  await flush(20);

  if (readerHtml(doc).includes("TITLE-A"))
    problems.push("[A] 晚到的 A 覆写了正文（reader 变成 TITLE-A）—— 读到后点的那篇、被先点的那篇覆盖");
  if (marked.some((m) => m.id === 1))
    problems.push("[A] 晚到的 A 被 markRead —— 两篇都被记已读，A 被 pickUnread 永久剔出 i+1 推荐");
  if (!marked.some((m) => m.id === 2))
    problems.push("[A] B 未被 markRead（真正上屏的那篇必须记已读）");
}

/* ══ 场景 A2：A 的请求在 B 上屏之后失败 ⇒ 其失败提示不得盖掉 B ══════════════ */
{
  const { ctx, doc, net, marked } = newEnv();
  vm.runInContext(transformed, ctx, { filename: "encounter.js#A2" });
  net.abortMode = "ignore";
  net.held.set("/api/encounter/texts/1", []);
  net.held.set("/api/encounter/texts/1/annotate", []);

  vm.runInContext("openText(1)", ctx);
  await flush(2);
  vm.runInContext("openText(2)", ctx);
  await flush(20);
  if (!readerHtml(doc).includes("TITLE-B"))
    problems.push("[A2] 夹具失配：B 未成功上屏");

  // A 此时才失败（网络错误 / 被 abort 都归到这里）⇒ catch 写「打开短篇失败」。
  net.held.get("/api/encounter/texts/1")[0].reject(new Error("Failed to fetch"));
  net.held.get("/api/encounter/texts/1/annotate")[0].reject(new Error("Failed to fetch"));
  await flush(20);

  if (readerHtml(doc).includes("打开短篇失败"))
    problems.push("[A2] A 的失败提示覆写了 B 的正文（catch 分支缺 seq 守卫）");
  if (!readerHtml(doc).includes("TITLE-B"))
    problems.push("[A2] B 的正文被从屏上挤掉了");
  if (marked.some((m) => m.id === 1))
    problems.push("[A2] 失败的 A 仍被 markRead");
  if (!marked.some((m) => m.id === 2))
    problems.push("[A2] B 未被 markRead");
}

/* ══ 场景 B：A 已在 renderTextDetailAnnotated 内部 await 处被抢占 ════════════ */
{
  const { ctx, doc, net, marked } = newEnv();
  vm.runInContext(transformed, ctx, { filename: "encounter.js#B" });
  net.abortMode = "ignore";
  net.held.set("/api/encounter/texts/1", []);
  net.held.set("/api/encounter/texts/1/annotate", []);
  net.held.set("/api/cards/known-lemmas", []);
  net.held.set("/api/encounter/texts/2", []);
  net.held.set("/api/encounter/texts/2/annotate", []);

  // A：两个 fetch 放行 → A 进入 renderTextDetailAnnotated，卡在内部 fetchKnownLemmas
  vm.runInContext("openText(1)", ctx);
  await flush(2);
  net.held.get("/api/encounter/texts/1")[0].resolve(fixtureFor("/api/encounter/texts/1"));
  net.held.get("/api/encounter/texts/1/annotate")[0].resolve(fixtureFor("/api/encounter/texts/1/annotate"));
  await flush(10);
  if (readerHtml(doc).includes("TITLE-A"))
    problems.push("[B] 夹具失配：A 在 B 之前就上屏了（known-lemmas 未被 hold 住）");
  if (net.held.get("/api/cards/known-lemmas").length !== 1)
    problems.push("[B] 夹具失配：A 未停在 renderTextDetailAnnotated 内部 await");

  // B：完整跑完并上屏（它的 known-lemmas 是队列第 2 个）
  vm.runInContext("openText(2)", ctx);
  await flush(4);
  net.held.get("/api/encounter/texts/2")[0].resolve(fixtureFor("/api/encounter/texts/2"));
  net.held.get("/api/encounter/texts/2/annotate")[0].resolve(fixtureFor("/api/encounter/texts/2/annotate"));
  await flush(4);
  net.held.get("/api/cards/known-lemmas")[1].resolve(fixtureFor("/api/cards/known-lemmas"));
  await flush(20);
  if (!readerHtml(doc).includes("TITLE-B"))
    problems.push("[B] 夹具失配：B 未成功上屏");

  // A 恢复：它的 known-lemmas 现在才 resolve
  net.held.get("/api/cards/known-lemmas")[0].resolve(fixtureFor("/api/cards/known-lemmas"));
  await flush(20);

  if (readerHtml(doc).includes("TITLE-A"))
    problems.push("[B] A 在 render 内部 await 处被抢占后仍覆写了正文 —— 覆写点之前缺 seq 守卫");
  if (marked.some((m) => m.id === 1))
    problems.push("[B] 被抢占的 A 仍被 markRead");
  if (!marked.some((m) => m.id === 2))
    problems.push("[B] B 未被 markRead");
}

/* ══ 场景 C：第二次 openText 必须 abort 第一次的 ctrl.signal ════════════════ */
{
  const { ctx, doc, net } = newEnv();
  vm.runInContext(transformed, ctx, { filename: "encounter.js#C" });
  net.abortMode = "ignore";
  net.held.set("/api/encounter/texts/1", []);
  net.held.set("/api/encounter/texts/1/annotate", []);

  vm.runInContext("openText(1)", ctx);
  await flush(2);
  vm.runInContext("openText(2)", ctx);
  await flush(4);

  const sigs = net.requests.filter((r) => /\/texts\/1(\/annotate)?$/.test(r.url)).map((r) => r.signal);
  if (sigs.length < 2)
    problems.push(`[C] fetchText/fetchAnnotate 没有收到 signal（只记录到 ${sigs.length} 次）—— signal 未透传`);
  else {
    if (!sigs[0])
      problems.push("[C] fetchText(1) 未透传 ctrl.signal（AbortController 没有接到 api）");
    if (sigs.some((s) => !s))
      problems.push("[C] 存在未带 signal 的请求（signal 透传不完整）");
    if (sigs[0] && !sigs[0].aborted)
      problems.push("[C] 第二次 openText 未 abort 第一次的 ctrl.signal（旧 in-flight 仍在烧 spaCy）");
  }
}

/* ══ 场景 D：showView 复用同一 seq ⇒ 跨调用晚到响应不得覆写 ════════════════ */
{
  const { ctx, doc, net, marked } = newEnv();
  vm.runInContext(transformed, ctx, { filename: "encounter.js#D" });
  net.abortMode = "ignore";
  net.held.set("/api/encounter/texts", []);        // 列表（showView 用）
  net.held.set("/api/encounter/texts/index", []);  // 索引（showView 用）

  vm.runInContext("showView()", ctx);              // 慢：列表 + 索引都 hold 住
  await flush(2);

  vm.runInContext("openText(2)", ctx);             // 用户在等待中点了卡片
  await flush(20);
  if (!readerHtml(doc).includes("TITLE-B"))
    problems.push("[D] 夹具失配：openText(2) 未上屏");
  if (listHtml(doc) !== "")
    problems.push("[D] 夹具失配：openText 之前列表已有内容");

  // showView 的晚到响应现在才到
  net.held.get("/api/encounter/texts")[0].resolve(fixtureFor("/api/encounter/texts"));
  net.held.get("/api/encounter/texts/index")[0].resolve(fixtureFor("/api/encounter/texts/index"));
  await flush(20);

  if (listHtml(doc).includes("encounter-card"))
    problems.push("[D] 上一次 showView 的晚到列表响应覆写了 DOM（showView 未复用同一 seq 守卫）");
  if (String(doc.registry.get("encounter-text-list").style.display) !== "none")
    problems.push("[D] 晚到的 showView 把列表重新显示出来，盖掉了正在读的详情");
  if (!readerHtml(doc).includes("TITLE-B"))
    problems.push("[D] 晚到的 showView 影响了详情正文");
  if (!marked.some((m) => m.id === 2))
    problems.push("[D] 夹具失配：openText(2) 未 markRead");
}

/* ── 结构守卫：core.js 的 signal 契约没被改掉（桩依赖它） ─────────────────── */
if (!/signal\s*:\s*controller\.signal/.test(CORE_SRC))
  problems.push("core.js api() 的 signal 契约变了（探针桩按此契约建模）");

/* ── 裁决 ────────────────────────────────────────────────────────────────── */
if (problems.length) {
  fail(`openText 重入竞态契约破坏（子计划 3 Task 1）：\n  - ${problems.join("\n  - ")}`);
}

const out = {
  ok: true,
  A: "后点者胜：A 的晚到响应不覆写、只 markRead(B)",
  A2: "A 的请求在 B 上屏后失败：失败提示不覆写 B",
  B: "render 内部 await 处被抢占：A 不覆写",
  C: "第二次 openText abort 第一次的 ctrl.signal",
  D: "showView 复用同一 seq，跨调用晚到响应不覆写",
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  for (const k of ["A", "A2", "B", "C", "D"]) console.log(`${k}: ${out[k]}`);
  console.log("✅ PASS: openText 重入守卫 + 旧 in-flight 取消 + 跨调用 seq 全部生效");
}
