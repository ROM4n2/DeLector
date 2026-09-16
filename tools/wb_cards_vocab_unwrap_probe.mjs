/**
 * wb_cards_vocab_unwrap_probe.mjs —— ADR-0011 Task 6 备考域取数「信封解包」行为探针
 *
 * 事故回归（CRV R1，2026-09-15）：/api/cards/vocab?cefr=B1&scope=all 返回信封
 * {cefr, scope, total, words:[...]}，a1_cards.js 的 loadExamVocab 若不做
 * `res.words` 解包（Array.isArray(res) ? res : [] 对信封恒得 []），B1 备考域
 * 页签永远空表，且空数组写进 _examVocabCaches 永久缓存 —— 纯字符串断言对此
 * 全程绿（红线 11），必须 node:vm 真跑。
 *
 * 硬约束：探针里**不得重抄一份实现**。被测逻辑一律来自 static/js/a1_cards.js
 * 真源码（剥 import/export 后进 node:vm），本文件只提供 document/api 桩。
 *
 * 场景：
 *   A. B1 信封解包（回退必红）：喂真实信封 JSON 形状，断言词项进入
 *      _examVocabCaches["B1"] 且逐字段经 mapCardsVocabItem 映射（含 topic/core），
 *      并断言 S5 富字段 example_zh 非空透传（信封携带 ipa/example_zh，A2 形态映射
 *      消费 example_zh；ipa 由 A2 原始路径在场景 B 断言）。
 *   B. A2 数组端点不回退：/api/a2/vocab 原生返回数组（含 ipa 富字段），必须原样
 *      入缓存不被误改，且 ipa 逐字透传。
 *
 * 用法：
 *   node tools/wb_cards_vocab_unwrap_probe.mjs            # 人类可读
 *   node tools/wb_cards_vocab_unwrap_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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
  process.stderr.write("备考域取数信封解包契约破坏（ADR-0011 Task 6 R1）：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
};

const a1CardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "a1_cards.js"), "utf8");

/* 剥 import/export（同 ia_dom_mount_probe.mjs 的转换器口径） */
const transformed = a1CardsJs
  .replace(/^import[^\n]*from[^\n]*;[^\S\n]*$/gm, "")
  .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
const stripProblems = [];
if (/^import\b/m.test(transformed)) stripProblems.push("a1_cards.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
if (/^\s*export\b/m.test(transformed)) stripProblems.push("a1_cards.js 剥离后仍有 export（探针转换器跟不上源码形态）");
for (const must of ["_examVocabCaches", "mapCardsVocabItem", "async function loadExamVocab", "async function setExamVocabLevel"]) {
  if (!transformed.includes(must)) stripProblems.push(`a1_cards.js 剥离切片缺 "${must}"（实现回退或切歪）`);
}
if (stripProblems.length) fail(stripProblems);

/* ---- 真实信封 JSON 形状（GET /api/cards/vocab?cefr=B1&scope=all 的服务端产出） ---- */
const ENVELOPE = {
  cefr: "B1",
  scope: "all",
  total: 2,
  words: [
    {
      id: "b1-beispiel", hw: "das Beispiel", pos: "Subst", gender: "Neut",
      plural: "die Beispiele", de: "Das ist ein gutes Beispiel.", zh: "例子",
      ipa: "das ˈbaɪʃpiːl", example_zh: "这是一个好例子。",
      core: true, cefr: "B1",
    },
    {
      id: "b1-entwickeln", hw: "entwickeln", pos: "V", gender: "",
      plural: "", de: "Die Stadt entwickelt sich schnell.", zh: "发展",
      ipa: "ɛntˈvɪkl̩n", example_zh: "这座城市发展得很快。",
      core: false, cefr: "B1",
    },
  ],
};

/* A2 数组端点桩的 ipa 样本（S5 富字段）：/api/a2/vocab 现下发 ipa，原样入缓存须逐字透传。 */
const A2_ARRAY_IPA = "das ˈaːbn̩tɔɪ̯ɐ";

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", disabled: false, style: {},
    classList: {
      add() {}, remove() {}, toggle() {}, contains() { return false; },
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}

function makeDocumentStub() {
  const registry = new Map();
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
    body: { appendChild() {} },
  };
}

/** 构造沙箱：桩 api 按 url 分发（抓每笔请求进 __fetches 供断言）。 */
function buildCtx(routes) {
  const sandbox = {
    console,
    document: makeDocumentStub(),
    JSON, Math, Object, Array, String, Number, RegExp, Promise, Set, parseInt, isNaN,
    setTimeout() { return 0; },
    clearTimeout() {},
    alert() {},
    // ↓ 被剥离的模块导入桩（core/player/reader/companion/cards/a1_hoeren/a1_lesen）
    esc: (s) => String(s ?? ""),
    jsAttr: (v) => JSON.stringify(v == null ? "" : v),
    state: {},
    playGermanAudio() {},
    refreshCardCounters() {},
    Companion: { celebrate() {} },
    getCardViewMode: () => "deck",
    getCachedVocabLemmas: () => new Set(),
    initA1Hoeren() {},
    initA1Lesen() {},
    stopHoerenExam() {},
    stopLesenExam() {},
  };
  sandbox.api = async (url) => {
    sandbox.__fetches.push(String(url));
    const u = String(url);
    for (const [needle, payload] of routes) {
      if (u.includes(needle)) return typeof structuredClone === "function" ? structuredClone(payload) : JSON.parse(JSON.stringify(payload));
    }
    return {};
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext("var __fetches = [];", ctx, { filename: "unwrap-prelude.js" });
  return ctx;
}

const tick = () => new Promise((r) => process.nextTick(r));

async function runScenarioA() {
  const ctx = buildCtx([["/api/cards/vocab?cefr=B1&scope=all&sources=official", ENVELOPE]]);
  vm.runInContext(transformed, ctx, { filename: "a1_cards.stripped.js#b1" });
  await vm.runInContext('setExamVocabLevel("B1")', ctx);
  await tick(); await tick();

  const fetches = JSON.parse(vm.runInContext("JSON.stringify(__fetches)", ctx));
  const cache = JSON.parse(vm.runInContext('JSON.stringify(_examVocabCaches["B1"] ?? null)', ctx));
  return { fetches, cache };
}

async function runScenarioB() {
  const A2_ARRAY = [
    { id: "a2-abenteuer", word: "das Abenteuer", hw: "das Abenteuer", lemma: "abenteuer", pos: "Subst", gender: "das", plural: "die Abenteuer", definition_zh: "冒险", zh: "冒险", example_de: "", de: "", ipa: A2_ARRAY_IPA, example_zh: "", topic: "general", core: true, cefr: "A2" },
  ];
  const ctx = buildCtx([["/api/a2/vocab", A2_ARRAY]]);
  vm.runInContext(transformed, ctx, { filename: "a1_cards.stripped.js#a2" });
  await vm.runInContext('setExamVocabLevel("A2")', ctx);
  await tick(); await tick();
  const cache = JSON.parse(vm.runInContext('JSON.stringify(_examVocabCaches["A2"] ?? null)', ctx));
  return { cache };
}

const problems = [];

/* 场景 A：B1 信封必须解包（当前实现回退时 cache === []，此处必红） */
const a = await runScenarioA();
log(`[A] fetch: ${a.fetches.join(" | ")}`);
log(`[A] cache["B1"]: ${JSON.stringify(a.cache)}`);
if (!a.fetches.includes("/api/cards/vocab?cefr=B1&scope=all&sources=official"))
  problems.push("setExamVocabLevel('B1') 未请求 /api/cards/vocab?cefr=B1&scope=all&sources=official");
if (!Array.isArray(a.cache))
  problems.push("_examVocabCaches['B1'] 不是数组（缓存契约破坏）");
if (a.cache.length !== ENVELOPE.words.length)
  problems.push(`信封未解包：_examVocabCaches['B1'] 长度 ${a.cache.length}，应为 ${ENVELOPE.words.length}（loadExamVocab 对信封 res.words 不解包时恒为 0）`);
const byId = {};
for (const w of a.cache || []) byId[w.id] = w;
const expectA = {
  "b1-beispiel": { word: "das Beispiel", hw: "das Beispiel", lemma: "beispiel", pos: "Subst", gender: "Neut", plural: "die Beispiele", definition_zh: "例子", zh: "例子", example_de: "Das ist ein gutes Beispiel.", de: "Das ist ein gutes Beispiel.", example_zh: "这是一个好例子。", cefr: "B1", topic: "general", core: true },
  /* core 硬编码 true（同 a2.py:37 的 A2 形态，Y1 同构化要求）：源数据 core:false
   * 的词条也必须归一为 true，若实现改回透传源值，本行断言红。 */
  "b1-entwickeln": { word: "entwickeln", hw: "entwickeln", lemma: "entwickeln", pos: "V", gender: "", plural: "", definition_zh: "发展", zh: "发展", example_de: "Die Stadt entwickelt sich schnell.", de: "Die Stadt entwickelt sich schnell.", example_zh: "这座城市发展得很快。", cefr: "B1", topic: "general", core: true },
};
let mappedAll = Object.keys(expectA).length > 0;
for (const [id, fields] of Object.entries(expectA)) {
  const got = byId[id];
  if (!got) { mappedAll = false; problems.push(`缓存缺词项 ${id}（信封解包后必须逐条入缓存）`); continue; }
  for (const [k, v] of Object.entries(fields)) {
    if (got[k] !== v) { mappedAll = false; problems.push(`词项 ${id} 字段 ${k} 映射错误：got=${JSON.stringify(got[k])} want=${JSON.stringify(v)}（mapCardsVocabItem 未映射/映射错）`); }
  }
}
if (a.cache && a.cache.some((w) => "total" in w || "scope" in w))
  problems.push("信封元数据（total/scope）泄漏进缓存词项（把信封本身当词项）");

/* 场景 B：A2 数组端点原样入缓存（防修复面过宽误伤既有路径） */
const b = await runScenarioB();
log(`[B] cache["A2"]: ${JSON.stringify(b.cache)}`);
const a2Unchanged = Array.isArray(b.cache) && b.cache.length === 1
  && b.cache[0].id === "a2-abenteuer" && b.cache[0].word === "das Abenteuer"
  && b.cache[0].topic === "general" && b.cache[0].core === true;
if (!a2Unchanged) problems.push("A2 数组端点 /api/a2/vocab 取数路径被误改（应原样入缓存）");
/* S5 富字段接线：A2 数组端点原样入缓存时 ipa 必须逐字透传（不被任何映射层吞掉）。 */
const a2IpaPassthrough =
  Array.isArray(b.cache) && b.cache.length === 1
  && b.cache[0].ipa === A2_ARRAY_IPA;
if (!a2IpaPassthrough)
  problems.push(`A2 数组端点 ipa 未原样透传：got=${JSON.stringify(b.cache && b.cache[0] && b.cache[0].ipa)} want=${JSON.stringify(A2_ARRAY_IPA)}（S5 富字段接线）`);

if (problems.length) fail(problems);

/* S5 富字段接线证据：B1 映射后 example_zh 必须逐字等于信封源值（非空透传）。 */
const b1ExampleZhPassthrough = (a.cache || []).every((w) => {
  const src = ENVELOPE.words.find((e) => e.id === w.id);
  return !!src && w.example_zh === src.example_zh && !!w.example_zh;
});

const out = {
  ok: true,
  unwrap: {
    requestedUrl: "/api/cards/vocab?cefr=B1&scope=all&sources=official",
    cacheFilled: Array.isArray(a.cache) && a.cache.length === ENVELOPE.words.length,
    itemCount: a.cache.length,
    mappedByMapCardsVocabItem: mappedAll,
    sampleItem: a.cache[0],
    a2ArraySourceUnchanged: a2Unchanged,
    b1ExampleZhPassthrough,
    a2IpaPassthrough,
    envelope: { cefr: ENVELOPE.cefr, scope: ENVELOPE.scope, total: ENVELOPE.total, words: ENVELOPE.words.length },
  },
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("信封输入:", JSON.stringify(out.unwrap.envelope));
  console.log("缓存词项输出:", JSON.stringify(out.unwrap.sampleItem));
  console.log("A2 数组端点不回退:", out.unwrap.a2ArraySourceUnchanged);
  console.log("B1 example_zh 非空透传:", out.unwrap.b1ExampleZhPassthrough);
  console.log("A2 ipa 原样透传:", out.unwrap.a2IpaPassthrough);
  console.log("✅ PASS: /api/cards 信封已解包进 _examVocabCaches，字段经 mapCardsVocabItem 映射，A2 数组路径不受影响");
}
