/**
 * cards_quiz_choice_probe.mjs —— 卡盒测验 choice 模式「缺释义不渲染空白选项」行为探针
 *
 * 缺陷（2026-11-03 上批自审登记的「choice 选项不接待补充」）：renderCurrentQuizCard
 * 的 choice 分支曾用裸 `card.definition_zh` 当正确答案选项文本。HITL 提议链路允许
 * 缺 `definition_zh` 的卡入盒（提案、卡盒网格、卡背与复习卡面统一显示「待补充」，
 * 见 FEATURES.md「释义口径统一」），这样的卡进选择题时正确答案按钮渲染成**空白**，
 * 与 flashcard / dictation 两个分支（均走 formatCardDefinition）口径不一致。
 *
 * 本探针按括号配对把 static/js/cards.js 里**真实的** renderCurrentQuizCard 整段切出，
 * 连同 static/js/cd-state.js 的 cardState 容器与 formatCardDefinition 切片一起丢进
 * node:vm 沙箱真跑（状态与实现都来自真源码，探针内无手写替身），只桩 document /
 * esc / playGermanAudio，读回 quiz-choice-options 容器的**真 innerHTML** 再断言，
 * 并解析 onclick="submitChoice(idx, correctIdx)" 验证正确项索引映射。
 *
 * 硬约束（与 cards_workbench_no_review_probe.mjs 同款）：
 *   - 探针里 MUST NOT 重抄一份被测实现。被测逻辑一律来自 cards.js / cd-state.js
 *     真源码切片；本文件只提供 UI 桩与夹具数据。「待补充」等期望值是**断言常量**。
 *   - 切片护栏：切歪 / 回退直接退出码 1，不许静默假绿（项目红线 11）。
 *   - 输出契约：新增探针即标准（tests/probe_json_contract.py）⇒ 顶层**精确**
 *     {failures, total, cases}，不带 ok / samples 超集。
 *
 * 场景（真渲染，不是切片断言）：
 *   A 有释义卡 ⇒ 正确选项文本即原释义，onclick 的 correctIdx 精确落在该按钮上。
 *   B 缺释义卡（definition_zh 为 "" / 空白）⇒ 正确选项显示「待补充」，
 *     不再出现空白按钮；正确项索引映射仍精确。
 *   C 干扰项 ⇒ 排除空释义与同释义卡（旧过滤语义不回归），不足 3 个时选项收缩。
 *   D 切片护栏 ⇒ 渲染切片 MUST 调 formatCardDefinition（单一释义来源），
 *     MUST NOT 再以 `[card.definition_zh,` 起头构造选项数组（旧缺陷形态）。
 *
 * 用法：
 *   node tools/cards_quiz_choice_probe.mjs            # 人类可读（日志走 stderr）
 *   node tools/cards_quiz_choice_probe.mjs --json     # stdout 只输出 JSON
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
  process.stderr.write(
    "卡盒测验 choice「缺释义不渲染空白选项」契约破坏：\n  - " + problems.join("\n  - ") + "\n",
  );
  process.exit(1);
};

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽函数（跳过字符串与注释，口径同 cards_workbench_no_review_probe.mjs）
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号`);
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

/** 切 `export const x = {…}` 这类对象字面量声明：没有参数表，首个 `{` 就是字面量。 */
function sliceObjectDecl(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`源码里找不到声明 ${declNeedle}（实现回退或改名了）`);
  const brace = src.indexOf("{", at);
  if (brace < 0) throw new Error(`${declNeedle} 后找不到对象字面量开括号`);
  const end = matchBracket(src, brace);
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

/** 切 `function 名字(…) {…}`：先配对参数表，再要求下一个非空白字符是函数体 `{`。
 *  任一步失败一律 throw，由上层 catch 走 fail() 具名退出，不许静默返回短切片。 */
function sliceFunctionBody(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`源码里找不到声明 ${declNeedle}（实现回退或改名了）`);
  const paren = src.indexOf("(", at);
  if (paren < 0) throw new Error(`${declNeedle} 后找不到参数表开括号（函数体定位失败）`);
  const paramsEnd = matchBracket(src, paren);
  let j = paramsEnd + 1;
  while (j < src.length && /\s/.test(src[j])) j++;
  if (src[j] !== "{") {
    throw new Error(`${declNeedle} 参数表后不是函数体开括号（切到的是签名不是函数体）`);
  }
  const end = matchBracket(src, j);
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

const cardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "cards.js"), "utf8");
const cdStateJs = fs.readFileSync(path.join(ROOT, "static", "js", "cd-state.js"), "utf8");

let stateFn = "";
let definitionFn = "";
let renderFn = "";
try {
  stateFn = sliceObjectDecl(cdStateJs, "export const cardState = ");
  /* 缺释义降级「待补充」的正主：必须随切片进沙箱，不许手写桩。 */
  definitionFn = sliceFunctionBody(cdStateJs, "export function formatCardDefinition(");
  renderFn = sliceFunctionBody(cardsJs, "export function renderCurrentQuizCard(");
} catch (e) {
  fail([`源码切片失败：${e.message}`]);
}

const transformed = [stateFn, definitionFn, renderFn].filter(Boolean).join("\n\n");

/* 切片护栏：切歪 / 回退 ⇒ 直接红，不许假绿 */
const stripProblems = [];
if (!renderFn.includes("quiz-choice-options"))
  stripProblems.push("renderCurrentQuizCard 切片缺 quiz-choice-options（choice 分支被挪走或切片边界算错）");
if (!definitionFn.includes("待补充"))
  stripProblems.push("formatCardDefinition 切片缺「待补充」（缺释义降级口径被改走了）");
if (!/const cardState = \{/.test(transformed))
  stripProblems.push("切片缺 cd-state.js 的 cardState 容器（渲染切片会 ReferenceError）");
if (!/\bquiz\s*:\s*\{/.test(stateFn))
  stripProblems.push("cardState 切片缺 quiz 状态簇（容器被降级/改名，渲染切片会读到 undefined）");
if (/^[ \t]*import\b/m.test(transformed))
  stripProblems.push("切片里混入 import 行（切片边界算错了）");
if (stripProblems.length) fail(stripProblems);

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只桩 UI，被测逻辑全部来自上面的真源码切片
 * ------------------------------------------------------------------------ */
function buildCtx() {
  const els = new Map();
  const makeEl = (id) => {
    const el = {
      id,
      textContent: "",
      innerHTML: "",
      style: {},
      classList: { add() {}, remove() {} },
      querySelector() { return null; },
    };
    els.set(id, el);
    return el;
  };
  const sandbox = {
    console,
    document: {
      getElementById(id) {
        if (!els.has(id)) makeEl(id);
        return els.get(id);
      },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    isNaN, isFinite, parseInt, parseFloat,
    setTimeout() { return 0; },
    clearTimeout() {},
    // ↓ cards.js 的模块级环境（esc/playGermanAudio 为 import 项，桩之；其余未被
    //   choice 分支求值的标识符不桩 —— 误求值会当场 ReferenceError 暴露问题）。
    esc: (s) => String(s ?? ""),
    playGermanAudio() {},
    finishQuiz() { throw new Error("finishQuiz 不应在有效队列索引下被调用"); },
    /* cardState 的唯一来源是上面从 cd-state.js 切出的 stateFn（随 transformed 进沙箱）。
     * 这里 MUST NOT 再手写一份同形桩：两份真源并存时，一旦切片护栏被删，探针就会
     * 拿桩的形状判行为而悄悄变绿。 */
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(transformed, ctx, { filename: "cards.stripped.js" });
  return { ctx, els };
}

/** 真跑一次 renderCurrentQuizCard（choice 模式），返回 {html, els}。 */
function renderChoice(card, allVocab) {
  const { ctx, els } = buildCtx();
  vm.runInContext(
    "cardState.quiz.mode = 'choice'; cardState.quiz.index = 0;" +
    "cardState.quiz.correct = 0; cardState.quiz.wrong = 0;" +
    "cardState.quiz.queue = " + JSON.stringify([card]) + ";" +
    "cardState.quiz.allVocab = " + JSON.stringify(allVocab) + ";",
    ctx,
    { filename: "quiz-fixture.js" },
  );
  vm.runInContext("renderCurrentQuizCard()", ctx, { filename: "call-render.js" });
  return { html: els.get("quiz-choice-options").innerHTML, els };
}

/** 解析渲染出的选项按钮：[{idx, correctIdx, label}]（label 已剥序号 span）。 */
function parseOptions(html) {
  const out = [];
  const re = /<button class="quiz-choice-btn" onclick="submitChoice\((\d+), (\d+)\)">([\s\S]*?)<\/button>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const inner = m[3].replace(/<span[\s\S]*?<\/span>/, "").trim();
    out.push({ idx: Number(m[1]), correctIdx: Number(m[2]), label: inner });
  }
  return out;
}

/* ---------------------------------------------------------------------------
 * 3. 夹具与断言常量
 * ------------------------------------------------------------------------ */
/** 断言常量：缺释义统一降级文案（FEATURES.md「释义口径统一」，正主在 cd-state.js）。 */
const PENDING_LABEL = "待补充";

/** 基线卡：普通 reader 卡，释义齐全。 */
const DEFINED_CARD = {
  id: 42,
  word: "das Beispiel",
  pos: "Subst",
  definition_zh: "例子",
  cefr_level: "A2",
  mastered: 0,
};

/** 缺释义卡：HITL 提议允许入盒的形态（definition_zh 为空）。 */
const NO_DEF_CARD = { ...DEFINED_CARD, id: 43, word: "die Fassade", definition_zh: "" };

/** 词库：给 DEFINED_CARD 当题面时提供 3 个干扰项（含一张空释义卡，MUST 被排除）。 */
const VOCAB_FOR_DEFINED = [
  DEFINED_CARD,
  { id: 44, word: "der Mangel", definition_zh: "缺点" },
  { id: 45, word: "der Zuwachs", definition_zh: "增长" },
  { id: 46, word: "der Rahmen", definition_zh: "框架" },
  { id: 47, word: "die Lücke", definition_zh: "" },
];

const problems = [];
const cases = [];
const record = (name, ok, detail) => { cases.push({ name, ok }); if (!ok) problems.push(`${name}：${detail}`); };

/* ══ A 有释义卡：正确选项即原释义，onclick 索引映射精确 ═════════════════════ */
{
  const { html } = renderChoice(DEFINED_CARD, VOCAB_FOR_DEFINED);
  const opts = parseOptions(html);
  log(`[A] 选项数: ${opts.length}`);
  const correct = opts.find((o) => o.label === DEFINED_CARD.definition_zh);
  record(
    "A1-有释义卡正确选项即原释义",
    !!correct,
    `渲染结果里找不到文本为「${DEFINED_CARD.definition_zh}」的选项（正确答案未按原释义渲染）：${html.slice(0, 200)}`,
  );
  record(
    "A2-有释义卡正确索引映射精确",
    !!correct &&
      opts.every((o, i) => o.idx === i) &&
      opts.every((o) => o.correctIdx === correct.idx),
    `onclick 的 correctIdx 未统一落在原释义按钮上：${JSON.stringify(opts)}`,
  );
  record(
    "A3-有释义卡干扰项非空且不含空释义卡",
    opts.length === 4 && opts.every((o) => o.label !== "") && !opts.some((o) => o.label === PENDING_LABEL),
    `干扰项过滤语义变了（应排除空释义卡 die Lücke 且四选项齐全）：${JSON.stringify(opts)}`,
  );
}

/* ══ B 缺释义卡：正确选项走「待补充」，绝无空白按钮 ═════════════════════════ */
{
  const { html } = renderChoice(NO_DEF_CARD, VOCAB_FOR_DEFINED);
  const opts = parseOptions(html);
  const correct = opts.find((o) => o.label === PENDING_LABEL);
  record(
    "B1-缺释义卡正确选项显示待补充",
    !!correct,
    `缺释义卡的正确选项没有显示「${PENDING_LABEL}」：${html.slice(0, 200)}`,
  );
  record(
    "B2-缺释义卡无空白选项",
    opts.length >= 2 && opts.every((o) => o.label.trim() !== ""),
    `choice 选项里仍有空白按钮（缺陷本体）：${JSON.stringify(opts)}`,
  );
  record(
    "B3-缺释义卡正确索引映射精确",
    !!correct &&
      opts.every((o, i) => o.idx === i) &&
      opts.every((o) => o.correctIdx === correct.idx),
    `缺释义时 onclick 的 correctIdx 未统一落在「待补充」按钮上：${JSON.stringify(opts)}`,
  );
}

/* ══ C 空白释义同走待补充；干扰项不足时选项收缩且正确项仍在 ═════════════════ */
{
  const blank = { ...DEFINED_CARD, id: 48, word: "der Kompromiss", definition_zh: "  " };
  const { html } = renderChoice(blank, [blank, VOCAB_FOR_DEFINED[1], VOCAB_FOR_DEFINED[2]]);
  const opts = parseOptions(html);
  record(
    "C1-空白释义同走待补充",
    opts.some((o) => o.label === PENDING_LABEL),
    `definition_zh 为空白字符串时未走「${PENDING_LABEL}」降级：${JSON.stringify(opts)}`,
  );
  const pending = opts.find((p) => p.label === PENDING_LABEL);
  record(
    "C2-干扰项不足时选项收缩且正确项在",
    opts.length === 3 &&
      !!pending &&
      opts.every((o, i) => o.idx === i) &&
      opts.every((o) => o.correctIdx === pending.idx),
    `词库仅 2 个可用干扰项时选项数应为 3 且正确项映射仍成立：${JSON.stringify(opts)}`,
  );
}

/* ══ D 切片护栏：释义单一来源 + 旧缺陷形态绝迹 ══════════════════════════════ */
{
  record(
    "D1-渲染复用formatCardDefinition单一来源",
    renderFn.includes("formatCardDefinition("),
    "choice 分支体内没有调用 formatCardDefinition —— 释义降级口径又自造了一份",
  );
  record(
    "D2-选项数组不再以裸definition_zh起头",
    !/\[\s*card\.definition_zh\s*,/.test(renderFn),
    "choice 分支仍以 [card.definition_zh, …] 构造选项数组（旧缺陷形态复活）",
  );
}

if (problems.length) fail(problems);

const out = { failures: 0, total: cases.length, cases: cases.map((c) => ({ name: c.name, ok: true })) };
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log(`场景数: ${out.total}`);
  console.log("PROBE PASS: choice 模式缺释义卡正确选项显示「待补充」，无空白按钮；有释义卡与索引映射语义不变");
}
