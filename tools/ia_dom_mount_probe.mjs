/**
 * ia_dom_mount_probe.mjs —— ADR-0005 Task 2「A1 五模块迁入备考域」挂载契约探针
 *
 * 事故回归（2026-09-04）：Task 2 把 A1 写作/听力/阅读/口语/词表五个面板从
 * view-writer / view-cards 原子迁入 view-exam。本仓库两次前科（v4.7.0 空模块、
 * v4.8.2 悬空标识符）证明：DOM id 挪窝 + 渲染目标没跟上 = 页面照常渲染、
 * 内容静默渲进隐藏的旧容器，纯字符串存在断言（"id=xxx" in html）对
 * 「渲错了地方」全程绿。
 *
 * 本探针两层防线：
 *   1) DOM 结构断言：五组 a1 面板 id 必须出现在 view-exam 切片内；
 *      view-writer / view-cards 切片内不得再有这些 id（同 id 双现即事故）；
 *      每个被搬移的 id 全文件唯一。
 *   2) 行为断言（实现回退必红）：把 a1_cards.js 真源码剥 import/export 后进
 *      node:vm 真跑，桩假 document 抓每笔 innerHTML 写入与 classList 操作 ——
 *      setA1Mode('vocab') 必须把词卡写进 #exam-cards-container、显隐
 *      #exam-cards-view-toggle，绝不允许回流主站 #cards-container /
 *      .cards-view-toggle。渲染目标回退旧实现本探针必红。
 *
 * 用法：
 *   node tools/ia_dom_mount_probe.mjs            # 人类可读
 *   node tools/ia_dom_mount_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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

const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const html = read(path.join("static", "index.html"));
const mainJs = read(path.join("static", "js", "main.js"));
const cardsJs = read(path.join("static", "js", "cards.js"));
const writerJs = read(path.join("static", "js", "writer.js"));
const a1WriterJs = read(path.join("static", "js", "a1_writer.js"));
const a1CardsJs = read(path.join("static", "js", "a1_cards.js"));

const problems = [];

/* ---- 括号配对切片（仿 wb_sync_probe.mjs） ------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: ${openIdx} 不是开括号`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c; i++;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === q) break;
        i++;
      }
      i++; continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (OPEN[c]) { stack.push(c); i++; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对 @${i}`);
      stack.pop();
      if (!stack.length) return i;
      i++; continue;
    }
    i++;
  }
  throw new Error("找不到配对闭括号");
}

/** JS 块切片：锚点正则不得吞掉首个 `{`，切片= 锚点起、配对闭括号止。 */
function sliceBlock(src, anchorRe, label) {
  const m = anchorRe.exec(src);
  if (!m) { problems.push(`找不到 ${label}（锚点丢了或实现被删）`); return ""; }
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  return src.slice(m.index, end + 1);
}

/* ---- 第 1 层：HTML DOM 结构断言 ---------------------------------------- */
/* <main>/<section> 均不嵌套：切片 = 自带 id 的开标签到下一个同款闭标签。 */
function sliceView(id) {
  const at = html.indexOf(`id="${id}"`);
  if (at < 0) return null;
  const open = html.lastIndexOf("<main", at);
  const close = html.indexOf("</main>", at);
  return open < 0 || close < 0 ? null : html.slice(open, close + "</main>".length);
}

function sliceSection(id) {
  const at = html.indexOf(`id="${id}"`);
  if (at < 0) return null;
  const open = html.lastIndexOf("<section", at);
  const close = html.indexOf("</section>", at);
  return open < 0 || close < 0 ? null : html.slice(open, close + "</section>".length);
}

const examView = sliceView("view-exam");
const writerView = sliceView("view-writer");
const cardsView = sliceView("view-cards");
for (const [name, blk] of [["view-exam", examView], ["view-writer", writerView], ["view-cards", cardsView]]) {
  if (!blk) problems.push(`index.html 缺少 ${name}（切片失败）`);
}
if (examView && !examView.includes("PRÜFUNGSDOMÄNE")) problems.push("view-exam 切片切歪了（丢了 topbar 文案）");
if (writerView && !writerView.includes("ide-editor")) problems.push("view-writer 切片切歪了（丢了 ide-editor）");
if (cardsView && !cardsView.includes("cards-container")) problems.push("view-cards 切片切歪了（丢了 cards-container）");

const EXAM_SLICE_MUST = [
  "a1-formular-view",
  "a1-email-view",
  "exam-tab-formular",
  "exam-tab-email",
  "a1-toolbar",
  "a1-topic-pills",
  "a1-search-row",
  "a1-tab-vocab",
  "a1-tab-hoeren",
  "a1-tab-lesen",
  "a1-tab-teil2",
  "a1-tab-teil3",
  "exam-cards-container",
  "exam-cards-view-toggle",
  "exam-mode-btn-deck",
  "exam-mode-btn-grid",
  "a1-hoeren-container",
  "a1-lesen-container",
];
for (const id of EXAM_SLICE_MUST) {
  if (examView && !examView.includes(`id="${id}"`))
    problems.push(`id="${id}" 不在 view-exam 内 —— A1 面板没迁进备考域`);
}

const examWriting = sliceSection("exam-writing");
const examFamily = sliceSection("exam-cards-family");
if (!examWriting) problems.push('缺少 <section id="exam-writing">（写作模块面板容器）');
if (!examFamily) problems.push('缺少 <section id="exam-cards-family">（词表/听力/阅读/口语共享面板容器）');
for (const id of ["exam-tab-formular", "exam-tab-email", "a1-formular-view", "a1-email-view"]) {
  if (examWriting && !examWriting.includes(`id="${id}"`))
    problems.push(`id="${id}" 不在 exam-writing 面板内`);
}
for (const id of ["a1-toolbar", "exam-cards-container", "exam-cards-view-toggle", "a1-hoeren-container", "a1-lesen-container"]) {
  if (examFamily && !examFamily.includes(`id="${id}"`))
    problems.push(`id="${id}" 不在 exam-cards-family 面板内`);
}

const WRITER_SLICE_FORBID = [
  "a1-formular-view",
  "a1-email-view",
  "writer-mode-a1-formular",
  "writer-mode-a1-email",
  "a1-formular-select",
  "a1-email-input",
];
for (const id of WRITER_SLICE_FORBID) {
  if (writerView && writerView.includes(id))
    problems.push(`view-writer 仍残留 A1 写作痕迹：${id}（迁出必须删净）`);
}
if (writerView && !writerView.includes('id="writer-mode-essay"'))
  problems.push("view-writer 丢了 writer-mode-essay（回归纯 essay 工具要保留单按钮条）");

const CARDS_SLICE_FORBID = [
  "a1-toolbar",
  "a1-hoeren-container",
  "a1-lesen-container",
  "seg-a1",
  "a1-tab-vocab",
  "a1-topic-pills",
];
for (const id of CARDS_SLICE_FORBID) {
  if (cardsView && cardsView.includes(id))
    problems.push(`view-cards 仍残留 A1 痕迹：${id}（迁出必须删净）`);
}

/* id 唯一性铁律：每个被搬移的 id 全文件必须恰好 1 次（双现 = 挂载歧义） */
for (const id of [...EXAM_SLICE_MUST, "writer-mode-essay"]) {
  const n = html.split(`id="${id}"`).length - 1;
  if (n !== 1) problems.push(`id="${id}" 全文件出现 ${n} 次（必须恰好 1 次）`);
}
const GONE_FROM_HTML = ["seg-a1", "setCardSegment('a1')", "switchWriterMode('formular')", "switchWriterMode('email')"];
for (const frag of GONE_FROM_HTML) {
  if (html.includes(frag)) problems.push(`index.html 仍引用旧工具入口：${frag}`);
}

/* ---- 第 2 层：JS 挂载链静态断言 ----------------------------------------- */
const setSegmentBody = sliceBlock(cardsJs, /export\s+function\s+setCardSegment\b/, "cards.js setCardSegment");
if (setSegmentBody && /['"]a1['"]/.test(setSegmentBody))
  problems.push("cards.js setCardSegment 仍处理 'a1' 段（备考域已接管入口）");

const renderGridBody = sliceBlock(cardsJs, /export\s+function\s+renderCardsGrid\b/, "cards.js renderCardsGrid");
if (renderGridBody) {
  if (/cardSegment\s*===?\s*['"]a1['"]/.test(renderGridBody))
    problems.push("cards.js renderCardsGrid 仍保留 cardSegment === 'a1' 分流段");
  if (renderGridBody.includes("a1-toolbar"))
    problems.push("cards.js renderCardsGrid 仍操作 a1-toolbar（工具栏已归备考域）");
  if (renderGridBody.includes("A1Cards."))
    problems.push("cards.js renderCardsGrid 仍引用 A1Cards（分流删除后不得残留）");
}
if (!/export\s*\*\s*from\s*["']\.\/a1_cards\.js["']/.test(cardsJs))
  problems.push("cards.js 丢了 export * from './a1_cards.js'（main.js 经它转发的 A1 函数契约会断）");

if (!/export\s*\{[^}]*setExamWritingTab[^}]*\}\s*from\s*["']\.\/a1_writer\.js["']/s.test(writerJs))
  problems.push("writer.js 未具名 re-export setExamWritingTab（main.js 的 import 链会断）");

if (!/export\s+(async\s+)?function\s+setExamWritingTab\b/.test(a1WriterJs))
  problems.push("a1_writer.js 缺 export setExamWritingTab（exam 写作页签切换无宿主）");

const switchModeBody = sliceBlock(a1WriterJs, /export\s+function\s+switchWriterMode\b/, "a1_writer.js switchWriterMode");
if (switchModeBody && /\bformular\b|\bemail\b/i.test(switchModeBody))
  problems.push("a1_writer.js switchWriterMode 仍处理 formular/email（A1 写作已迁备考域）");

if (a1CardsJs.includes('querySelector(".cards-view-toggle")'))
  problems.push("a1_cards.js 仍查询主站 .cards-view-toggle（应改查 #exam-cards-view-toggle）");

const showBody = sliceBlock(mainJs, /export\s+function\s+show\(view\)/, "main.js show");
if (showBody) {
  if (showBody.includes('if (view !== "cards")'))
    problems.push('main.js show() 仍用 view !== "cards" 守卫停考计时器（备考域宿主已改 view-exam）');
  if (!showBody.includes('if (view !== "exam")'))
    problems.push('main.js show() 缺 if (view !== "exam") 守卫（离开备考域必须停听力/阅读考试计时器）');
  if (!/if \(view === "exam"\)/.test(showBody) || !showBody.includes("setExamModule"))
    problems.push('main.js show() 缺 view === "exam" 分支（进入备考域要点亮模块面板）');
}

const importWriterBlock = /import\s*\{([^}]*)\}\s*from\s*["']\.\/writer\.js["']/s.exec(mainJs);
if (importWriterBlock && !importWriterBlock[1].includes("setExamWritingTab"))
  problems.push("main.js 未从 ./writer.js import setExamWritingTab");

const exposerBody = sliceBlock(mainJs, /Object\.assign\(window,\s*/, "main.js window exposer");
for (const fn of ["setExamModule", "setExamWritingTab", "setA1CardViewMode"]) {
  if (exposerBody && !exposerBody.includes(fn))
    problems.push(`main.js exposer 缺 ${fn}（HTML onclick 挂不上 window，点击静默无操作）`);
}

/* ---- 第 3 层：node:vm 真跑 a1_cards.js（渲染目标行为级断言） ------------- */
let transformed = "";
let vmError = null;
if (!problems.length) {
  transformed = a1CardsJs
    .replace(/^import[^\n]*from[^\n]*;[^\S\n]*$/gm, "")
    .replace(/^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm, "");
  if (/^import\b/m.test(transformed)) problems.push("a1_cards.js 剥离后仍有 import 行（探针转换器跟不上源码形态）");
  if (/^\s*export\b/m.test(transformed)) problems.push("a1_cards.js 剥离后仍有 export（探针转换器跟不上源码形态）");
  for (const must of ["exam-cards-container", "exam-cards-view-toggle", "setA1CardViewMode", "function renderA1", "function renderA1PokerCard", "function renderA1GridView", "function setA1Mode"]) {
    if (!transformed.includes(must))
      problems.push(`a1_cards.js 剥离切片缺 "${must}"（实现回退或切歪）`);
  }
}

function makeEl(id) {
  const el = {
    id,
    innerHTML: "",
    textContent: "",
    disabled: false,
    style: {},
    classOps: [],
    _classes: new Set(),
    classList: {
      add(c) { el._classes.add(c); el.classOps.push(["add", c]); },
      remove(c) { el._classes.delete(c); el.classOps.push(["remove", c]); },
      toggle(c, force) {
        const on = force === undefined ? !el._classes.has(c) : Boolean(force);
        if (on) el.classList.add(c); else el.classList.remove(c);
        return on;
      },
      contains(c) { return el._classes.has(c); },
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  return el;
}

function makeDocumentStub() {
  const registry = new Map();
  const stub = {
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
  /* 预登记 DOM id：探针断言只认这些容器上的操作 */
  for (const id of [
    "exam-cards-container", "cards-container", "exam-cards-view-toggle",
    "a1-hoeren-container", "a1-lesen-container",
    "a1-topic-pills", "a1-search-row", "a1-toolbar",
    "exam-mode-btn-deck", "exam-mode-btn-grid",
    "a1-tab-vocab", "a1-tab-hoeren", "a1-tab-lesen", "a1-tab-teil2", "a1-tab-teil3",
    "a1-active-card",
  ]) stub.getElementById(id);
  return stub;
}

const SEED_WORD = {
  word: "Haus", lemma: "Haus", pos: "Subst", gender: "Neut", plural: "Häuser",
  definition_zh: "房子", example_de: "Das Haus ist groß.", example_zh: "房子很大。",
  topic: "",
};

/** 构造 vm 沙箱：桩 fetch 抓每笔请求 URL 进 __fetches（供懒加载场景断言）。 */
function buildCtx(doc) {
  const sandbox = {
    console,
    document: doc,
    JSON, Math, Object, Array, String, Number, RegExp, Promise, Set, parseInt, isNaN,
    setTimeout() { return 0; },
    clearTimeout() {},
    alert() {},
    // ↓ 以下为被剥离的模块导入桩（core/player/reader/companion/cards/a1_hoeren/a1_lesen）
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
    if (u.includes("/api/a1/vocab")) return [SEED_WORD];
    if (u.includes("/api/a1/topics")) return [];
    if (u.includes("/api/a1/sprechen/teil2")) return [];
    if (u.includes("/api/a1/sprechen/teil3")) return [];
    return {};
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext("var __fetches = [];", ctx, { filename: "probe-prelude.js" });
  return ctx;
}

const tick = () => new Promise((r) => process.nextTick(r));

const docStub = makeDocumentStub();
const ctx = buildCtx(docStub);
const mainCardsEl = docStub.registry.get("cards-container");
const examToggleEl = docStub.registry.get("exam-cards-view-toggle");

try {
  vm.runInContext(transformed, ctx, { filename: "a1_cards.stripped.js" });

  /* 种数据：loadA1Data 走桩 fetch 灌满缓存，后续 setA1Mode 同步渲染 */
  await vm.runInContext("loadA1Data()", ctx);
  await tick(); await tick();

  /* 场景 1：词表默认牌盒模式 —— 必须写进 exam-cards-container */
  vm.runInContext("setA1CardViewMode('deck'); setA1Mode('vocab');", ctx);
  const deckTarget = String(vm.runInContext("document.getElementById('exam-cards-container').innerHTML", ctx));
  if (!deckTarget.includes("deck-stage"))
    problems.push("setA1Mode('vocab') 后 exam-cards-container 没渲染出牌盒（deck-stage 缺失）");
  if (!deckTarget.includes("Haus"))
    problems.push("牌盒渲染没带上种子词 Haus（渲染目标指对了但数据没跟上）");
  if (mainCardsEl.innerHTML !== "")
    problems.push("renderA1 把词卡写进了主站 #cards-container（备考域渲染目标回退，回退必红场景）");
  if (!examToggleEl.classOps.some(([op, c]) => op === "remove" && c === "hidden"))
    problems.push("setA1Mode('vocab') 未给 #exam-cards-view-toggle 摘 hidden（备考域 toggle 显隐没接上）");

  /* 场景 2：目录模式 —— 同样必须写进 exam-cards-container */
  vm.runInContext("setA1CardViewMode('grid');", ctx);
  const gridTarget = String(vm.runInContext("document.getElementById('exam-cards-container').innerHTML", ctx));
  if (!gridTarget.includes("cards-grid"))
    problems.push("setA1CardViewMode('grid') 后 exam-cards-container 没渲染出目录网格");
  if (mainCardsEl.innerHTML !== "")
    problems.push("grid 模式下 renderA1 仍写主站 #cards-container");

  /* 场景 3：hoeren 模式 —— 备考域内听力容器显隐正常、词表容器让位 */
  vm.runInContext("setA1Mode('hoeren');", ctx);
  const hoerenEl = docStub.registry.get("a1-hoeren-container");
  const examCardsEl = docStub.registry.get("exam-cards-container");
  if (!hoerenEl.classOps.some(([op, c]) => op === "remove" && c === "hidden"))
    problems.push("setA1Mode('hoeren') 未摘掉 a1-hoeren-container 的 hidden");
  if (!examCardsEl.classOps.some(([op, c]) => op === "add" && c === "hidden"))
    problems.push("setA1Mode('hoeren') 未藏起 exam-cards-container");
  vm.runInContext("setA1Mode('vocab');", ctx);
  if (!hoerenEl._classes.has("hidden"))
    problems.push("切回 vocab 后 a1-hoeren-container 未重新隐藏");

  /* 场景 4（冷缓存懒加载，回退必红）：全新沙箱、从未 loadA1Data ——
     setA1Mode('vocab') 必须自己触发 loadA1Data（原 cards.js 'a1' 段的
     fetch 链路随分流段迁走，这个守卫只能由 a1_cards.js 自管）。实现回退
     （只渲染空态、不再拉数据）时 exam-cards-container 里就是空态页而没有
     种子词，本场景必红。 */
  const doc2 = makeDocumentStub();
  const ctx2 = buildCtx(doc2);
  vm.runInContext(transformed, ctx2, { filename: "a1_cards.stripped.js#2" });
  vm.runInContext("setA1CardViewMode('deck'); setA1Mode('vocab');", ctx2);
  await tick(); await tick(); await tick();
  const fetches2 = JSON.parse(vm.runInContext("JSON.stringify(__fetches)", ctx2));
  const coldTarget = String(vm.runInContext("document.getElementById('exam-cards-container').innerHTML", ctx2));
  if (!fetches2.some((u) => u.includes("/api/a1/vocab")))
    problems.push("冷缓存 setA1Mode('vocab') 未触发 /api/a1/vocab 拉取（题库懒加载守卫丢失）");
  if (!coldTarget.includes("deck-stage") || !coldTarget.includes("Haus"))
    problems.push("冷缓存拉取完成后 exam-cards-container 未重渲染出牌盒（懒加载→渲染链断）");
} catch (e) {
  vmError = e;
  problems.push(`a1_cards.js vm 真跑抛错：${e && e.stack ? e.stack.split("\n").slice(0, 3).join(" | ") : e}`);
}

/* ---- 裁决 ---------------------------------------------------------------- */
if (problems.length) {
  fail(`A1 备考域挂载契约破坏（ADR-0005 Task 2）：\n  - ${problems.join("\n  - ")}`);
}

const out = {
  ok: true,
  exam: {
    panelsInExamView: EXAM_SLICE_MUST.length,
    writingPanelIds: ["exam-tab-formular", "exam-tab-email", "a1-formular-view", "a1-email-view"],
    familyPanelIds: ["a1-toolbar", "exam-cards-container", "exam-cards-view-toggle", "a1-hoeren-container", "a1-lesen-container"],
  },
  dynamic: {
    vocabDeckTarget: "exam-cards-container",
    vocabGridTarget: "exam-cards-container",
    mainCardsContainerUntouched: mainCardsEl.innerHTML === "",
    hoerenContainerWired: true,
    coldCacheLazyLoad: true,
    vmError: vmError ? String(vmError) : null,
  },
};

if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("写作面板 id：", out.exam.writingPanelIds.join(", "));
  console.log("卡盒族面板 id：", out.exam.familyPanelIds.join(", "));
  console.log("vm 渲染目标：vocab deck/grid → exam-cards-container；主站 cards-container 未被触碰：", out.dynamic.mainCardsContainerUntouched);
  console.log("冷缓存懒加载：setA1Mode 自管 fetch+重渲染（场景 4 绿）");
  console.log("✅ PASS: A1 五模块已在 view-exam 挂载，旧工具视图已删净，渲染目标指向备考域容器");
}
