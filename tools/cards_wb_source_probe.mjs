/**
 * cards_wb_source_probe.mjs —— ADR-0016 审计 P0 Task 5「卡面区分工作台来源」行为探针
 *
 * 说谎事故：统一池把工作台背过的词投影进 vocab_cards（core/vocab_pool.py 只写
 * fsrs_s / fsrs_d / fsrs_lapses，**不写** due_date / correct_count / wrong_count）。
 * cards.js 正面页脚的 meta 行原为
 *     `${card.mastered ? "🛡️ 已掌握" : card.due_date ? "⏳ 到期: …" : "⏳ 待复习"} ·
 *      ${card.correct_count || 0} 正 / ${card.wrong_count || 0} 误`
 * ⇒ 对一条 fsrs_s=25（用户在背词工作台背了 5 次）的工作台词，卡面显示
 *   「⏳ 待复习 · 0 正 / 0 误」—— 正/误是**卡盒 DSR 侧**统计，对工作台词恒为 0（说谎）。
 *
 * 本探针按括号配对把 static/js/cards.js 里**真实的** cardStatsTag + renderDeckStage
 * 两个函数整段切出来，丢进 node:vm 沙箱真跑，只桩 document / esc / jsAttr，
 * 读回 renderDeckStage 写进容器的那份**真 innerHTML**，再从里面正则抠出
 * <span class="card-stats-tag"> 的真实文案做断言。
 *
 * 硬约束（与 wb_queue_probe.mjs / wb_cards_vocab_unwrap_probe.mjs 同款）：
 *   - 探针里**不得重抄一份被测实现**。被测逻辑一律来自 cards.js 真源码切片；
 *     本文件只提供 UI 桩与夹具数据。文案的「期望值」是**断言常量**，不是实现。
 *   - 切片护栏：切片必须同时含 `card-stats-tag` 与 `correct_count` 两个标志性
 *     token，且必须**不含** re-export / import 行 —— 切歪直接退出码 1，
 *     不许静默假绿（项目红线 11：字符串存在式断言是死测）。
 *
 * 场景（真渲染，不是切片断言）：
 *   1. 工作台词（fsrs_s=25）⇒ 显示工作台 FSRS 状态，且**不再**出现「正 / … 误」。
 *   2. 工作台词 + 用户手动「已掌握」⇒ **徽记合并**：「🛡️ 已掌握 · 📚 工作台 · s=…」。
 *      用户的 mastered 是亲手设的标记，**永不隐藏**（隐藏它等于用新的不实换旧的不实）。
 *   3. 非工作台词（fsrs_s=null）⇒ meta 行与旧实现**逐字相同**（回退必红）。
 *   4. 非工作台词（fsrs_s=0）⇒ 同上。
 *   5. SQLite REAL 以字符串下发（fsrs_s="25.0"）⇒ 仍判工作台。
 *   6. 脏值（fsrs_s="abc" / NaN）⇒ 退回非工作台路径（不炸、不误判）。
 *   7. 零暗示：工作台文案 MUST NOT 含「次」「复习」「repetition」等把 s 读成
 *      DSR 复习次数的字眼，也 MUST NOT 复现 correct/wrong 两列的数字。
 *
 * 用法：
 *   node tools/cards_wb_source_probe.mjs            # 人类可读（日志走 stderr）
 *   node tools/cards_wb_source_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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
  process.stderr.write("卡面「工作台来源」契约破坏（ADR-0016 审计 P0 Task 5）：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
};

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽函数（跳过字符串与注释，口径同 wb_queue_probe.mjs）
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
  // 剥掉 `export ` 前缀：node:vm 的 Script 不是 ES module，带 export 会 SyntaxError
  // （口径同 wb_cards_vocab_unwrap_probe.mjs 的转换器）。
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

const cardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "cards.js"), "utf8");
let predicateFn = "";
let statsFn = "";
let renderFn = "";
try {
  /* renderDeckStage 自子计划 5 Task 1 起会调 isWorkbenchSourced（决定工作台词
   * 收不收 DSR 复习按钮），该函数 MUST 一并进沙箱，否则本探针的卡面渲染会撞
   * ReferenceError。这是**补齐切片**（渲染路径多了一个依赖），不改动任何断言。 */
  predicateFn = sliceFunction(cardsJs, "function isWorkbenchSourced(");
  statsFn = sliceFunction(cardsJs, "function cardStatsTag(");
  renderFn = sliceFunction(cardsJs, "export function renderDeckStage(");
} catch (e) {
  fail([`源码切片失败：${e.message}`]);
}
const transformed = predicateFn + "\n\n" + statsFn + "\n\n" + renderFn;

/* 切片护栏：切歪 / 回退 ⇒ 直接红，不许假绿 */
const stripProblems = [];
if (!transformed.includes('class="card-stats-tag"'))
  stripProblems.push("切片缺 card-stats-tag（卡面 meta 行被挪走或实现回退）");
if (!transformed.includes("correct_count"))
  stripProblems.push("切片缺 correct_count（非工作台词的旧文案路径被删了？逐字不变契约破了）");
if (/^\s*import\b/m.test(transformed))
  stripProblems.push("切片里混入 import 行（切片边界算错了）");
if (/\brepetition_count\b/.test(statsFn))
  stripProblems.push("cardStatsTag 里引用了 repetition_count（工作台 s 与 DSR 复习次数语义不同，MUST NOT 混用）");
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
    JSON, Math, Object, Array, String, Number, RegExp, isNaN, isFinite,
    setTimeout() { return 0; },
    clearTimeout() {},
    // ↓ cards.js 的模块级环境
    esc: (s) => String(s ?? ""),
    jsAttr: (v) => JSON.stringify(v == null ? "" : v),
    attachDeckSwipeListener() {},
    state: {},
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext("var deckIndex = 0; var deckFlipped = false;", ctx, { filename: "cards-wb-source-prelude.js" });
  vm.runInContext(transformed, ctx, { filename: "cards.stripped.js" });
  return { ctx, container };
}

/** 真跑一次 renderDeckStage，返回正面页脚 meta 行的**真实文案**。 */
function render(card) {
  const { ctx, container } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  vm.runInContext("renderDeckStage([__card], [])", ctx, { filename: "call-render.js" });
  const html = container.innerHTML;
  const m = /<span class="card-stats-tag">([\s\S]*?)<\/span>/.exec(html);
  if (!m) throw new Error("渲染结果里抠不到 card-stats-tag（卡面结构变了？）");
  return m[1];
}

/* ---------------------------------------------------------------------------
 * 3. 场景
 * ------------------------------------------------------------------------ */
const problems = [];
const cases = [];
const record = (name, ok, detail) => { cases.push({ name, ok, detail }); if (!ok) problems.push(`${name}：${detail}`); };

/* 基线卡（非工作台来源的普通 reader 卡）：DSR 侧有真实进度，due_date 已排程 */
const READER_CARD = {
  id: 42,
  word: "das Beispiel",
  lemma: "beispiel",
  pos: "Subst",
  gender: "das",
  definition_zh: "例子",
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

/* 旧实现的 meta 行文案（**断言常量**，非实现重抄）—— 场景 3/4 拿它做逐字比对 */
const LEGACY_READER_TAG = "⏳ 到期: 2026-10-05 · 7 正 / 2 误";

/* --- 场景 1：工作台词（fsrs_s=25）必须说工作台的实话 --- */
{
  const tag = render({ ...READER_CARD, fsrs_s: 25, correct_count: 0, wrong_count: 0 });
  log(`[1] 工作台词 meta: ${tag}`);
  record(
    "1-工作台词显示工作台FSRS状态",
    /工作台/.test(tag) && /s=25\.0/.test(tag),
    `fsrs_s=25 的卡面 meta 未显示工作台 FSRS 状态，实际渲染为：${JSON.stringify(tag)}`,
  );
  record(
    "1-工作台词不复现DSR正误",
    !/正\s*\//.test(tag) && !/误/.test(tag),
    `工作台词仍显示了卡盒 DSR 的「N 正 / N 误」（对工作台词恒为 0 = 对用户说谎）：${JSON.stringify(tag)}`,
  );
}

/* --- 场景 2：工作台词 + 用户手动「已掌握」⇒ 徽记合并（mastered 永不隐藏） --- */
{
  const tag = render({ ...READER_CARD, mastered: 1, fsrs_s: 12.34, correct_count: 0, wrong_count: 0 });
  log(`[2] 工作台词(已掌握) meta: ${tag}`);
  // 期望文案是**断言常量**（裁决后的产品口径），不是被测实现的重抄。
  const WANT = "🛡️ 已掌握 · 📚 工作台 · s=12.3";
  record(
    "2-已掌握工作台词合并徽记",
    tag === WANT,
    `mastered=1 且 fsrs_s>0 的工作台词 meta 异常：工作台分支吞掉了用户亲手设的「🛡️ 已掌握」徽记。got=${JSON.stringify(tag)} want=${JSON.stringify(WANT)}`,
  );
  record(
    "2-已掌握工作台词仍不复现DSR正误",
    !/正\s*\//.test(tag) && !/误/.test(tag),
    `已掌握工作台词仍显示了卡盒 DSR 的「N 正 / N 误」（对工作台词恒为 0 = 对用户说谎）：${JSON.stringify(tag)}`,
  );
  record(
    "2-已掌握工作台词零取反（不得出现 repetition_count）",
    !/repetition/.test(tag) && !/\b次\b/.test(tag),
    `已掌握工作台词 meta 含把 s 读成 DSR 复习次数的字眼：${JSON.stringify(tag)}`,
  );
}

/* --- 场景 3：非工作台词（fsrs_s=null）逐字不变 --- */
{
  const tag = render({ ...READER_CARD });
  log(`[3] 非工作台词(fsrs_s=null) meta: ${tag}`);
  record(
    "3-非工作台词null逐字不变",
    tag === LEGACY_READER_TAG,
    `fsrs_s=null 的普通卡 meta 被改动：got=${JSON.stringify(tag)} want=${JSON.stringify(LEGACY_READER_TAG)}`,
  );
}

/* --- 场景 4：非工作台词（fsrs_s=0）逐字不变 --- */
{
  const tag = render({ ...READER_CARD, fsrs_s: 0 });
  log(`[4] 非工作台词(fsrs_s=0) meta: ${tag}`);
  record(
    "4-非工作台词零值逐字不变",
    tag === LEGACY_READER_TAG,
    `fsrs_s=0 的普通卡 meta 被改动：got=${JSON.stringify(tag)} want=${JSON.stringify(LEGACY_READER_TAG)}`,
  );
}

/* --- 场景 5：SQLite REAL 以字符串下发时仍判工作台 --- */
{
  const tag = render({ ...READER_CARD, fsrs_s: "25.0" });
  log(`[5] fsrs_s 为字符串 "25.0" 的 meta: ${tag}`);
  record(
    "5-字符串数值仍判工作台",
    /工作台/.test(tag) && /s=25\.0/.test(tag),
    `fsrs_s="25.0"（SQLite REAL 可能以字符串下发）未判为工作台来源：${JSON.stringify(tag)}`,
  );
}

/* --- 场景 6：脏值退回非工作台，不炸不误判 --- */
for (const [name, dirty] of [["abc", "abc"], ["NaN", Number.NaN]]) {
  const tag = render({ ...READER_CARD, fsrs_s: dirty });
  log(`[6] 脏值 fsrs_s=${name} 的 meta: ${tag}`);
  record(
    `6-脏值${name}退回非工作台`,
    tag === LEGACY_READER_TAG,
    `fsrs_s=${name} 的卡 meta 异常（应退回非工作台旧文案）：got=${JSON.stringify(tag)} want=${JSON.stringify(LEGACY_READER_TAG)}`,
  );
}

/* --- 场景 7：零暗示 —— s ≠ repetition_count --- */
{
  const tag = render({ ...READER_CARD, fsrs_s: 25, repetition_count: 9, correct_count: 3, wrong_count: 1 });
  log(`[7] 零暗示检查 meta: ${tag}`);
  const forbidden = ["次", "复习", "repetition", "轮", "遍", "掌握度"];
  const hit = forbidden.filter((w) => tag.includes(w));
  record(
    "7-不暗示s等价DSR复习次数",
    hit.length === 0,
    `工作台 meta 含会把 s 读成 DSR 复习次数的字眼 ${JSON.stringify(hit)}：${JSON.stringify(tag)}`,
  );
  record(
    "7-不复现DSR正误数字",
    !/\b9\b/.test(tag) && !/\b3\b/.test(tag) && !/\b1\b/.test(tag.replace("s=25.0", "")),
    `工作台 meta 复现了卡盒 DSR 侧的 repetition_count / correct_count 数字：${JSON.stringify(tag)}`,
  );
}

if (problems.length) fail(problems);

const out = {
  ok: true,
  failures: 0,
  total: cases.length,
  cases: cases.map((c) => ({ name: c.name, ok: true })),
  samples: {
    workbench: render({ ...READER_CARD, fsrs_s: 25 }),
    readerUnchanged: render({ ...READER_CARD }),
  },
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("工作台词 meta:", out.samples.workbench);
  console.log("非工作台词 meta（逐字未变）:", out.samples.readerUnchanged);
  console.log(`场景数: ${out.total}`);
  console.log("✅ PASS: 卡面按 fsrs_s 区分来源 —— 工作台词显示工作台 FSRS 状态且不再谎报「0 正 / 0 误」，非工作台词逐字不变");
}
