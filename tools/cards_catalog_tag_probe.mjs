/**
 * cards_catalog_tag_probe.mjs —— 卡盒「目录/网格视图」按来源说真话 行为探针
 *
 * 说谎事故：统一池（core/vocab_pool.py）把工作台背过的词投影进 vocab_cards，
 * 但只写 fsrs_s / fsrs_d / fsrs_lapses，**不写** correct_count / wrong_count。
 * 卡面（renderDeckStage）自 PR #98 起已改用 cardStatsTag(card)，对工作台词显示
 * 「📚 工作台 · s=25」；而**目录/网格视图**（renderCatalogGrid）仍硬编码旧文案
 *     `${c.correct_count || 0} 正 / ${c.wrong_count || 0} 误`
 * ⇒ 同一条词在卡面说「工作台」，在目录里说「0 正 / 0 误」——**同一张卡两套说法**，
 *   且目录那套对工作台词恒为 0（用户在背词工作台背了 5 次）。
 *
 * 讽刺点：class 名叫 `card-stats-tag`，但内容与 cardStatsTag 毫无关系。
 * 既有探针（tools/cards_wb_source_probe.mjs）的切片护栏只检查 renderDeckStage 切片
 * ⇒ 目录视图此前**不受任何守卫**，可以静默回退。
 *
 * 本探针按括号配对把 static/js/cards.js 里**真实的**
 * isWorkbenchSourced / cardStatsTag / renderCatalogGrid 三个函数整段切出来，丢进 node:vm 沙箱真跑
 * （MUST NOT 重抄一份被测实现），只桩 document / esc / jsAttr，读回
 * renderCatalogGrid 写进容器的那份**真 innerHTML**，从里面正则抠出
 * <span class="card-stats-tag"> 的真实文案做断言。
 *
 * 场景：
 *   A1 工作台词（fsrs_s=25）⇒ 目录词汇卡的 meta 行 MUST NOT 含「0 正 / 0 误」
 *   A2 工作台词 ⇒ 含「📚 工作台」（判据与 cardStatsTag 同源：问真函数要答案）
 *   A3 普通 reader 卡（fsrs_s=null）⇒ 仍含「N 正 / N 误」**且仍含「到期:」**
 *      —— 证明换用 cardStatsTag 没把原目录视图的 ` · 到期: X` 后缀信息丢掉
 *      （cardStatsTag 非工作台分支自带 due_date，见 A6 的基线切片）
 *   A4 目录视图源码切片里 MUST NOT 残留 correct_count（防「只换了一半」）
 *   A5 语法考点卡网格非工作台路径不回归（仍给正/误统计）
 *   A6 cardStatsTag MUST 复用 isWorkbenchSourced，且二者在整条边界带行为符合来源契约
 *
 * 用法：
 *   node tools/cards_catalog_tag_probe.mjs            # 人类可读（日志走 stderr）
 *   node tools/cards_catalog_tag_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

const fail = (problems) => {
  process.stderr.write("卡盒「目录视图按来源说真话」契约破坏（清债轮 A 组 债1）：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
};

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽函数（跳过字符串与注释，口径同 cards_wb_source_probe.mjs）
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

/** 按 `function 名字(` 定位函数体，切出从 `function` 到配对 `}` 的整段。 */
function sliceFunction(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`cards.js 里找不到声明 ${declNeedle}（实现回退或改名了）`);
  const brace = src.indexOf("{", at);
  if (brace < 0) throw new Error(`${declNeedle} 后找不到函数体开括号`);
  const end = matchBracket(src, brace);
  // 剥掉 `export ` 前缀：node:vm 的 Script 不是 ES module，带 export 会 SyntaxError。
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

/** 行尾归一：避免源码诊断随 checkout 的 CRLF / LF 风格漂移。 */
const lf = (s) => s.replace(/\r\n/g, "\n");

const cardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "cards.js"), "utf8");

let predicateFn = "";
let statsFn = "";
let gridFn = "";
try {
  predicateFn = sliceFunction(cardsJs, "function isWorkbenchSourced(");
  statsFn = sliceFunction(cardsJs, "function cardStatsTag(");
  gridFn = sliceFunction(cardsJs, "export function renderCatalogGrid(");
} catch (e) {
  fail([`源码切片失败：${e.message}`]);
}
const transformed = predicateFn + "\n\n" + statsFn + "\n\n" + gridFn;

/* 切片护栏：切歪 / 回退 ⇒ 直接红，不许静默假绿（项目红线 11） */
const stripProblems = [];
if (!/\bfunction\s+isWorkbenchSourced\s*\(/.test(transformed))
  stripProblems.push("执行切片缺 isWorkbenchSourced（cardStatsTag 的唯一来源判据未注入沙箱）");
if (!/class="card-stats-tag"/.test(gridFn))
  stripProblems.push("renderCatalogGrid 切片缺 card-stats-tag（目录网格的统计位被挪走或实现回退）");
/* cardStatsTag 返回**纯文本**，类名由调用方的 <span> 提供 ⇒ 它的切片锚点是
 * correct_count（非工作台分支的旧文案本体），不是 class 名。 */
if (!/correct_count/.test(statsFn))
  stripProblems.push("cardStatsTag 切片缺 correct_count（非工作台分支的旧文案被删了？逐字不变契约破了）");
if (/^[ \t]*import\b/m.test(transformed))
  stripProblems.push("切片里混入 import 行（切片边界算错了）");
if (stripProblems.length) fail(stripProblems);

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只桩 UI，被测逻辑全部来自上面的真源码切片
 * ------------------------------------------------------------------------ */
function buildCtx() {
  const container = { innerHTML: "" };
  const sandbox = {
    console,
    document: {
      getElementById(id) {
        if (id === "cards-container") return container;
        return null;
      },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    JSON, Math, Object, Array, String, Number, Boolean, RegExp, Date, Error,
    isNaN, isFinite, parseInt, parseFloat,
    setTimeout() { return 0; },
    clearTimeout() {},
    // ↓ cards.js 的模块级环境
    esc: (s) => String(s ?? ""),
    jsAttr: (v) => JSON.stringify(v == null ? "" : v),
    state: {},
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(transformed, ctx, { filename: "cards-catalog-tag.stripped.js" });
  return { ctx, container };
}

/**
 * 真跑一次 renderCatalogGrid，返回目录里所有 card-stats-tag 的**真实文案**。
 * vocabTags = 词汇卡网格的（vList 顺序），grammarTags = 语法考点卡网格的。
 */
function renderGrid(vList, gList = []) {
  const { ctx, container } = buildCtx();
  vm.runInContext(
    "renderCatalogGrid(" + JSON.stringify(vList) + ", " + JSON.stringify(gList) + ")",
    ctx,
    { filename: "call-render-grid.js" },
  );
  const found = [...container.innerHTML.matchAll(/<span class="card-stats-tag">([\s\S]*?)<\/span>/g)].map((m) => m[1]);
  // 词汇卡网格在前、语法网格在后（renderCatalogGrid 的模板里就是这个先后）。
  return { vocabTags: found.slice(0, vList.length), grammarTags: found.slice(vList.length) };
}

/** 直接问真 cardStatsTag（不经渲染），供 A2/A6 做同源比对。 */
function askTag(card) {
  const { ctx } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  return vm.runInContext("cardStatsTag(__card)", ctx);
}

/** 直接问真 isWorkbenchSourced，供 A6 在整条边界带核对来源契约。 */
function askPredicate(card) {
  const { ctx } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  return vm.runInContext("isWorkbenchSourced(__card)", ctx);
}

/* ---------------------------------------------------------------------------
 * 3. 夹具与断言常量（**期望值是断言常量**，MUST NOT 是被测实现的重抄）
 * ------------------------------------------------------------------------ */

/** 基线卡：普通 reader 卡，DSR 侧有真实进度，due_date 已排程。 */
const READER_VOCAB = {
  id: 42,
  word: "das Beispiel",
  lemma: "beispiel",
  pos: "Subst",
  gender: "das",
  definition_zh: "例子",
  sentence_context: "Das ist ein gutes Beispiel.",
  cefr_level: "A2",
  mastered: 0,
  due_date: "2026-10-05",
  interval_days: 3,
  ease_factor: 2.5,
  repetition_count: 4,
  correct_count: 7,
  wrong_count: 2,
  fsrs_s: null,
};

/** 工作台词：用户在背词工作台背过（fsrs_s=25），卡盒 DSR 侧从未复习 ⇒ 正/误恒为 0。 */
const WORKBENCH_VOCAB = {
  ...READER_VOCAB,
  fsrs_s: 25,
  correct_count: 0,
  wrong_count: 0,
  repetition_count: 0,
  due_date: null,
};

/** 基线语法考点卡：歌德语法卡，表结构（database.py 的 grammar_cards）**无 fsrs_* 列**。 */
const READER_GRAMMAR = {
  id: 7,
  grammar_name: "Akkusativ",
  sentence_context: "Ich sehe den Mann.",
  cefr_level: "B1",
  explanation_zh: "第四格",
  mastered: 0,
  due_date: "2026-10-06",
  correct_count: 5,
  wrong_count: 1,
};

/** 断言常量：旧实现（非工作台普通卡）在目录词汇网格里的文案 —— A3/A5 的「不回归」基准。
 *  注意末尾没有「 · 到期: …」：换用 cardStatsTag 后 due_date 由它自己渲染在前缀位。 */
const LEGACY_READER_TAG = "⏳ 到期: 2026-10-05 · 7 正 / 2 误";
const LEGACY_GRAMMAR_TAG = "⏳ 到期: 2026-10-06 · 5 正 / 1 误";

/** 工作台来源边界契约：期望值是测试数据，不复制被测实现的阈值表达式。 */
const SOURCE_BOUNDARY_CASES = [
  ["null", null, false],
  ["undefined", undefined, false],
  ["0", 0, false],
  ['"0"', "0", false],
  ['""', "", false],
  ['" "', " ", false],
  ["25", 25, true],
  ['"25.0"', "25.0", true],
  ["0.0001", 0.0001, true],
  ["-1", -1, false],
  ["NaN", Number.NaN, false],
  ['"abc"', "abc", false],
  ["1e-9", 1e-9, true],
  ["25.5", 25.5, true],
  ["3", 3, true],
];

const problems = [];
const cases = [];
const record = (name, ok, detail) => { cases.push({ name, ok, detail }); if (!ok) problems.push(`${name}：${detail}`); };

/* ══ A 词汇卡网格：工作台词 MUST NOT 再说「0 正 / 0 误」 ═══════════════════ */
{
  const { vocabTags } = renderGrid([WORKBENCH_VOCAB]);
  const tag = vocabTags[0] ?? "";
  log(`[A1] 词汇网格（工作台词）: ${JSON.stringify(tag)}`);

  record(
    "A1-工作台词目录网格不谎报零正零误",
    !/0\s*正\s*\/\s*0\s*误/.test(tag),
    `工作台词（fsrs_s=25，用户在工作台背过）在目录网格里仍显示「0 正 / 0 误」——` +
    `correct_count/wrong_count 是卡盒 DSR 侧语义，对工作台词恒为 0：${JSON.stringify(tag)}`,
  );
  record(
    "A2-工作台词目录网格与cardStatsTag同源",
    /工作台/.test(tag) && tag === askTag(WORKBENCH_VOCAB),
    `词汇卡网格的统计文案与真 cardStatsTag 对不上（目录视图必须复用同一判据与文案）：` +
    `grid=${JSON.stringify(tag)} cardStatsTag=${JSON.stringify(askTag(WORKBENCH_VOCAB))}`,
  );
}

/* ══ B 普通 reader 卡不回归：正/误仍在，due_date 信息不丢 ═════════════════ */
{
  const { vocabTags } = renderGrid([READER_VOCAB]);
  const tag = vocabTags[0] ?? "";
  log(`[B] 词汇网格（普通 reader 卡）: ${JSON.stringify(tag)}`);

  record(
    "B1-普通卡仍显正误统计",
    /7\s*正\s*\/\s*2\s*误/.test(tag),
    `普通 reader 卡的「N 正 / N 误」丢了（cardStatsTag 非工作台分支 MUST 逐字保留该统计）：${JSON.stringify(tag)}`,
  );
  record(
    "B2-换用后due_date信息不丢",
    /到期:\s*2026-10-05/.test(tag),
    `换用 cardStatsTag 后 due_date 信息丢了（cardStatsTag 非工作台分支自带「⏳ 到期: …」前缀，` +
    `原目录视图那段 `+"` · 到期: ${c.due_date}`"+` 后缀因此是冗余的）：${JSON.stringify(tag)}`,
  );
  record(
    "B3-普通卡统计位逐字等于cardStatsTag",
    tag === LEGACY_READER_TAG && tag === askTag(READER_VOCAB),
    `普通 reader 卡的统计文案被改动：grid=${JSON.stringify(tag)} ` +
    `want=${JSON.stringify(LEGACY_READER_TAG)} cardStatsTag=${JSON.stringify(askTag(READER_VOCAB))}`,
  );
}

/* ══ C 目录网格源码里 MUST NOT 残留硬编码 correct_count（防「只换了一半」） ══ */
{
  const gridBody = lf(gridFn);
  record(
    "C1-目录网格无残留硬编码correct_count",
    !/correct_count/.test(gridBody),
    `renderCatalogGrid 切片里仍直接引用 correct_count —— 只换了一半（另一处仍硬编码旧文案）：` +
    `${gridBody.split("\n").filter((l) => /correct_count/.test(l)).join(" ⏎ ")}`,
  );
  record(
    "C2-目录网格复用cardStatsTag",
    /cardStatsTag\s*\(/.test(gridBody),
    "renderCatalogGrid 切片里没有调 cardStatsTag —— 目录视图自造了第二份文案分支（应复用卡面同一来源）",
  );
}

/* ══ D 语法考点卡网格：非工作台路径不回归 ═══════════════════════════════ */
{
  const { grammarTags } = renderGrid([READER_VOCAB], [READER_GRAMMAR]);
  const tag = grammarTags[0] ?? "";
  log(`[D] 语法网格: ${JSON.stringify(tag)}`);

  record(
    "D1-语法卡仍显正误统计",
    /5\s*正\s*\/\s*1\s*误/.test(tag),
    `语法考点卡的「N 正 / N 误」丢了（旧语义 MUST 不回归）：${JSON.stringify(tag)}`,
  );
  record(
    "D2-语法卡统计位等于cardStatsTag",
    tag === LEGACY_GRAMMAR_TAG && tag === askTag(READER_GRAMMAR),
    `语法考点卡的统计文案异常：grid=${JSON.stringify(tag)} ` +
    `want=${JSON.stringify(LEGACY_GRAMMAR_TAG)} cardStatsTag=${JSON.stringify(askTag(READER_GRAMMAR))}`,
  );
}

/* ══ E cardStatsTag 复用唯一来源判据，且整条边界带行为符合契约 ══════════ */
{
  const statsBody = lf(statsFn);
  const reusesPredicate = /isWorkbenchSourced\s*\(/.test(statsBody);
  const duplicatesFiniteCheck = /Number\s*\.\s*isFinite\s*\(/.test(statsBody);
  const duplicatesThreshold = /\bwbS\s*>\s*0\b/.test(statsBody);
  const diverged = SOURCE_BOUNDARY_CASES.filter(([, value, expected]) => {
    const card = { ...READER_VOCAB, fsrs_s: value };
    const predicateResult = askPredicate(card);
    const tagResult = /工作台/.test(askTag(card));
    return predicateResult !== expected || tagResult !== expected || predicateResult !== tagResult;
  }).map(([label]) => label);
  record(
    // 场景键为既有 pytest wrapper 的兼容接口；通过条件已由“零改动哈希”改为下方行为契约。
    "E1-cardStatsTag零改动",
    reusesPredicate && !duplicatesFiniteCheck && !duplicatesThreshold && diverged.length === 0,
    `cardStatsTag 必须只调用 isWorkbenchSourced，且判据/标签须在边界带符合来源契约：` +
    `reuses=${reusesPredicate} Number.isFinite=${duplicatesFiniteCheck} wbS>0=${duplicatesThreshold} ` +
    `diverged=${JSON.stringify(diverged)}`,
  );
}

if (problems.length) fail(problems);

const out = {
  ok: true,
  failures: 0,
  total: cases.length,
  cases: cases.map((c) => ({ name: c.name, ok: true })),
  samples: {
    vocabWorkbench: renderGrid([WORKBENCH_VOCAB]).vocabTags[0],
    vocabReader: renderGrid([READER_VOCAB]).vocabTags[0],
    grammarReader: renderGrid([READER_VOCAB], [READER_GRAMMAR]).grammarTags[0],
    cardStatsTagSha256: crypto.createHash("sha256").update(lf(statsFn), "utf8").digest("hex"),
  },
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("词汇网格（工作台词）:", out.samples.vocabWorkbench);
  console.log("词汇网格（普通卡）:", out.samples.vocabReader);
  console.log("语法网格（普通卡）:", out.samples.grammarReader);
  console.log(`cardStatsTag 切片 SHA-256（观察项，不参与门禁）: ${out.samples.cardStatsTagSha256}`);
  console.log(`场景数: ${out.total}`);
  console.log("✅ PASS: 目录/网格视图复用 cardStatsTag —— 工作台词不再谎报「0 正 / 0 误」，普通卡与语法卡的正误统计及 due_date 逐字未变");
}
