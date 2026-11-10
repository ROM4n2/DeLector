/**
 * vocab_save_feedback_probe.mjs —— 「存卡响应 → 用户可见反馈」跨边界行为探针
 *
 * 背景（2026-11-10 P2）：`POST /api/cards/vocab` 幂等命中既有卡时，后端返回
 * `created:false` 与 `skipped_fields`；在此之前 5 个前端入口一律显示「已保存」并
 * 播放庆祝动画，用户手填的释义被「只补空」静默丢弃却回报成功。
 *
 * 硬约束：探针里**不得重抄一份实现**。被测逻辑一律来自 `static/js/` 真源码
 * （剥 import/export 后进 node:vm），本文件只提供 DOM / 网络 / 伴侣桩。
 * 5 个入口共用从 rd-api.js 真源码取出的 `vocabSaveOutcome` / `vocabSaveNotice`，
 * 避免「手写桩 + 真源码切片」两个真相源。
 *
 * `--json` 输出**精确标准三键** `{failures, total, cases}`（新增探针即标准，
 * 见 tests/test_probe_json_contract.py；多一个键都会被判红）。`cases[]` 带
 * 实测 detail，供 wrapper 钉住具体口径；契约破坏时退出码 1、详情写 stderr。
 *
 * 用法：
 *   node tools/vocab_save_feedback_probe.mjs            # 人类可读
 *   node tools/vocab_save_feedback_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

const problems = [];
const cases = [];

function check(name, ok, detail) {
  cases.push({ name, ok: !!ok, detail: String(detail || "") });
  if (!ok) problems.push(`${name}: ${detail}`);
}

/* 与 cards_count_probe.mjs / wb_cards_vocab_unwrap_probe.mjs 同口径的剥离器。 */
function strip(src) {
  return src
    .replace(/^import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];?[ \t]*$/gm, "")
    .replace(/^import[^\n]*from[^\n]*;[^\S\n]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "")
    .replace(/^export\s*\{[\s\S]*?\};?[ \t]*$/gm, "");
}

function makeEl(id) {
  return {
    id,
    innerHTML: "", textContent: "", value: "", disabled: false,
    dataset: {}, style: { setProperty() {}, pointerEvents: "" },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() {}, removeEventListener() {}, appendChild() {},
  };
}

function makeDocument() {
  const registry = new Map();
  return {
    registry,
    getElementById(id) {
      if (!registry.has(id)) registry.set(id, makeEl(id));
      return registry.get(id);
    },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() {}, createElement(tag) { return makeEl(`__${tag}`); },
    body: { appendChild() {}, classList: { add() {}, remove() {}, toggle() {} } },
  };
}

/* 未知 import 绑定的兜底：视图模块顶层可能声明/引用一堆与本探针无关的东西。
   只作环境，不提供任何被测逻辑；未知绑定一律 undefined，若真被调用会显式炸红。 */
function buildCtx(file, response, pureFns, extra = {}) {
  const src = strip(fs.readFileSync(path.join(ROOT, "static", "js", file), "utf8"));
  const calls = { celebrate: [], notify: [], alert: [], savedCalls: [] };
  const doc = makeDocument();
  const token = {
    text: "Haus", lemma: "Haus", pos: "NOUN", gender: "Neut", plural: "-..er",
    cefr_level: "A1",
    praepositionen: [{
      bedeutung_zh: "依赖于 (+Akk)", praeposition: "auf", kasus: "Akk",
      beispiel: "Das Haus besteht auf Qualität.",
    }],
  };
  const base = {
    console: JSON_MODE ? { log() {}, error() {}, warn() {} } : console,
    document: doc,
    window: {},
    localStorage: {
      _m: new Map(),
      getItem(k) { return this._m.has(String(k)) ? this._m.get(String(k)) : null; },
      setItem(k, v) { this._m.set(String(k), String(v)); },
      removeItem(k) { this._m.delete(String(k)); },
    },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Promise, Set, Map,
    Symbol, Date, Error, parseInt, parseFloat, isNaN, isFinite,
    encodeURIComponent, decodeURIComponent,
    setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {},
    alert(m) { calls.alert.push(String(m)); },
    notify(m) { calls.notify.push(String(m)); },
    Companion: new Proxy({}, {
      get: (_t, key) => (...args) => { if (key === "celebrate") calls.celebrate.push(args[0]); },
    }),
    api: async () => response,
    saveVocabCard: async () => response,
    savePrepSaved: async () => ({}),
    fetchVocabLedger: async () => ({ lemma: "", card_count: 0, card: null }),
    renderVocabLedger() {}, clearVocabLedger() {}, refreshCardCounters() {},
    fetchCardCounts: async () => ({ total: 0 }),
    esc: (s) => String(s ?? ""), jsAttr: (v) => JSON.stringify(v ?? ""),
    normalizeCefrPct: (v) => v,
    state: { selectedToken: token, currentArticle: { id: 1 }, selectedSent: { text: "Das Haus ist alt." } },
    cardState: { prep: { cache: null }, savedKeys: new Set() },
    articleStore: {},
    ...pureFns,
    ...extra,
  };
  const sandbox = new Proxy(base, {
    has: () => true,
    get: (t, k) => (k in t ? t[k] : undefined),
  });
  const ctx = vm.createContext(sandbox);
  try {
    vm.runInContext(src, ctx, { filename: `${file}#stripped` });
  } catch (e) {
    throw new Error(`${file} 真源码切片在沙箱中加载失败（桩或剥离器跟不上源码形态）：${e && e.message}`);
  }
  return { ctx, calls, doc };
}

/* ── ① 纯函数：全部从 rd-api.js 真源码取 ───────────────────────────────── */
const apiCtx = buildCtx("rd-api.js", {}, {});
const vocabSaveOutcome = vm.runInContext("vocabSaveOutcome", apiCtx.ctx);
const vocabSaveNotice = vm.runInContext("vocabSaveNotice", apiCtx.ctx);
if (typeof vocabSaveOutcome !== "function" || typeof vocabSaveNotice !== "function") {
  console.error("rd-api.js 缺少 vocabSaveOutcome / vocabSaveNotice 纯函数");
  process.exit(1);
}
const pureFns = { vocabSaveOutcome, vocabSaveNotice };

const oCreated = vocabSaveOutcome({ created: true, skipped_fields: [] });
check("outcome_created_true", oCreated.created === true && oCreated.skippedFields.length === 0,
  `首次新增判定错误：${JSON.stringify(oCreated)}`);
const oLegacy = vocabSaveOutcome({ status: "ok", id: 1, word: "Haus", plural: "" });
check("outcome_missing_fields_is_backward_compatible", oLegacy.created === true && oLegacy.skippedFields.length === 0,
  `后端旧响应/字段截断必须按首次新增兜底：${JSON.stringify(oLegacy)}`);
check("outcome_null_response_is_backward_compatible", vocabSaveOutcome(null).created === true,
  "null 响应不得把成功路径判成幂等命中");
const oDup = vocabSaveOutcome({ created: false, skipped_fields: ["definition_zh", "sentence_context"] });
check("outcome_duplicate_with_skipped_fields", oDup.created === false && oDup.skippedFields.length === 2,
  `幂等命中/跳过字段判定错误：${JSON.stringify(oDup)}`);
const oDirty = vocabSaveOutcome({ created: false, skipped_fields: "not-an-array" });
check("outcome_dirty_skipped_fields_is_safe", oDirty.created === false && oDirty.skippedFields.length === 0,
  "脏 skipped_fields 必须降级为空数组，不能把字符串当列表渲染");
check("notice_created_is_empty", vocabSaveNotice(oCreated) === "", "首次新增不得弹提示");
check("notice_skipped_explains_no_overwrite", vocabSaveNotice(oDup).includes("未覆盖"),
  `跳过字段时必须解释「未覆盖原有释义」：${vocabSaveNotice(oDup)}`);
check("notice_plain_duplicate_explains_no_insert", vocabSaveNotice(oDirty).includes("未重复添加"),
  `普通幂等命中必须说明未新增：${vocabSaveNotice(oDirty)}`);

/* ── ② 视图层：5 个入口都从真源码跑，断言「庆祝动画 / 按钮文案 / 提示」 ─── */
async function runReader(response) {
  const { ctx, calls, doc } = buildCtx("reader.js", response, pureFns);
  await vm.runInContext("saveVocab()", ctx, { filename: "reader.js#saveVocab" });
  return { calls, btn: doc.getElementById("save-vocab-btn") };
}

const createdRes = { status: "ok", id: 1, word: "Haus", plural: "", created: true, skipped_fields: [] };
const dupRes = { status: "ok", id: 1, word: "Haus", plural: "", created: false, skipped_fields: ["definition_zh"] };

let r = await runReader(createdRes);
check("reader_saveVocab_created_celebrates", r.calls.celebrate.length === 1 && r.calls.notify.length === 0,
  `首次新增应庆祝且零提示：${JSON.stringify(r.calls)}`);
check("reader_saveVocab_created_button", r.btn.textContent === "已保存", `按钮文案应为「已保存」，实际 ${r.btn.textContent}`);
r = await runReader(dupRes);
check("reader_saveVocab_duplicate_no_celebration", r.calls.celebrate.length === 0,
  "幂等命中不得播放庆祝动画（会把什么都没发生渲染成一次成功）");
check("reader_saveVocab_duplicate_button", r.btn.textContent === "已在词卡中",
  `幂等命中按钮应说明已在词卡中，实际 ${r.btn.textContent}`);
check("reader_saveVocab_duplicate_explains_skipped", r.calls.notify.some((m) => m.includes("未覆盖")),
  `手填释义被跳过必须给人类可读提示：${JSON.stringify(r.calls.notify)}`);
r = await runReader({ status: "ok", id: 1, word: "Haus", plural: "" });
check("reader_saveVocab_legacy_response_unchanged",
  r.calls.celebrate.length === 1 && r.calls.notify.length === 0 && r.btn.textContent === "已保存",
  "后端字段缺失时行为必须与改动前逐字一致");

{
  const { ctx, calls } = buildCtx("reader.js", dupRes, pureFns, {
    saveVocabCard: async () => { throw new Error("network down"); },
  });
  try { await vm.runInContext("saveVocab()", ctx); } catch { /* 函数内部 catch 掉 */ }
  check("reader_saveVocab_failure_still_alerts", calls.alert.length === 1 && calls.celebrate.length === 0,
    `失败路径必须保留 alert 且不庆祝：${JSON.stringify(calls)}`);
}

{
  const { ctx, calls, doc } = buildCtx("reader.js", dupRes, pureFns);
  const btn = makeEl("prep-btn");
  vm.runInContext("var __probeBtn = null;", ctx);
  ctx.__probeBtn = btn;
  await vm.runInContext("savePrepCollocation(0, __probeBtn)", ctx);
  check("reader_prep_collocation_duplicate_no_celebration", calls.celebrate.length === 0,
    "抽屉搭配卡幂等命中不得庆祝");
  check("reader_prep_collocation_duplicate_button", btn.textContent === "已在词卡中",
    `抽屉搭配卡按钮文案错误：${btn.textContent}`);
  void doc;
}

async function runEntry(file, invoke, response) {
  const { ctx, calls } = buildCtx(file, response, pureFns, {});
  await vm.runInContext(invoke, ctx, { filename: `${file}#entry` });
  return calls;
}

const matrixBtn = `({ dataset: { word: 'bestehen', praep: 'auf', kasus: 'Akk', refl: '0', zh: '依赖于', cefr: 'B1', beispiel: 'bestehen auf Qualität' }, disabled: false, textContent: '', classList: { add(){}, remove(){} } })`;
let c = await runEntry("cards.js", `savePrepCardFromMatrix(${matrixBtn})`, dupRes);
check("cards_matrix_duplicate_no_celebration", c.celebrate.length === 0 && c.notify.length === 1,
  `介词矩阵入口必须给出解释且不庆祝：${JSON.stringify(c)}`);
c = await runEntry("cards.js", `savePrepCardFromMatrix(${matrixBtn})`, createdRes);
check("cards_matrix_created_celebrates", c.celebrate.length === 1 && c.notify.length === 0,
  `介词矩阵首次新增仍应庆祝：${JSON.stringify(c)}`);

const a1Args = "'Haus', 'Haus', 'NOUN', 'Neut', '', '房子', 'Das Haus ist alt.', '', '', null";
c = await runEntry("a1_cards.js", `saveA1WordToDeck(${a1Args})`, dupRes);
check("a1_cards_duplicate_no_celebration", c.celebrate.length === 0 && c.notify.length === 1,
  `A1 词卡入口必须给出解释且不庆祝：${JSON.stringify(c)}`);
c = await runEntry("a1_cards.js", `saveA1WordToDeck(${a1Args})`, createdRes);
check("a1_cards_created_celebrates", c.celebrate.length === 1 && c.notify.length === 0,
  `A1 词卡首次新增仍应庆祝：${JSON.stringify(c)}`);

const chipEl = `({ style: {}, innerHTML: '', classList: { add(){}, remove(){} } })`;
c = await runEntry("a1_hoeren.js", `saveVocabChip('die Wohnung', '公寓', ${chipEl})`, dupRes);
check("a1_hoeren_duplicate_no_celebration", c.celebrate.length === 0 && c.notify.length === 1,
  `听力芯片入口必须给出解释且不庆祝：${JSON.stringify(c)}`);
c = await runEntry("a1_hoeren.js", `saveVocabChip('die Wohnung', '公寓', ${chipEl})`, createdRes);
check("a1_hoeren_created_celebrates", c.celebrate.length === 1 && c.notify.length === 0,
  `听力芯片首次新增仍应庆祝：${JSON.stringify(c)}`);

const out = {
  failures: problems.length,
  total: cases.length,
  cases,
};
if (problems.length) {
  process.stderr.write("存卡反馈契约破坏：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
}
log(`[vocab-save-feedback] ${cases.length} 场景全绿`);
console.log(JSON.stringify(out));
