/**
 * cards_workbench_no_review_probe.mjs —— 卡盒里「工作台词不给复习按钮」行为探针
 *
 * 白复习事故：统一池（core/vocab_pool.py）把工作台背过的词投影进 vocab_cards，
 * 但只写 fsrs_s / fsrs_d / fsrs_lapses，**不写** repetition_count / due_date。
 * 卡盒 DSR 复习（review_card_sm2）也**不写** fsrs_*。
 * ⇒ 用户在卡盒点「1 重来 / 2 困难 / 3 良好 / 4 简单」：DSR 四列被写了，
 *   但卡面因 fsrs_s 优先仍显示「📚 工作台 · s=25」（屏幕上什么都没变），
 *   而工作台那侧的 FSRS 也没动 —— 复习了，等于没复习。
 *
 * 本探针按括号配对把 static/js/cards.js 里**真实的**
 * isWorkbenchSourced / cardStatsTag / renderDeckStage 三个函数整段切出来，
 * 丢进 node:vm 沙箱真跑（不重抄实现），只桩 document / esc / jsAttr，
 * 读回 renderDeckStage 写进容器的**真 innerHTML** 再断言。
 *
 * 硬约束（与 cards_wb_source_probe.mjs / enc_known_same_source_probe.mjs 同款）：
 *   - 探针里 MUST NOT 重抄一份被测实现。被测逻辑一律来自 cards.js 真源码切片；
 *     本文件只提供 UI 桩与夹具数据。文案 / href 的「期望值」是**断言常量**。
 *   - 切片护栏：切歪 / 回退直接退出码 1，不许静默假绿（项目红线 11）。
 *
 * 场景（真渲染，不是切片断言）：
 *   A 工作台词（fsrs_s=25）⇒ 渲染结果 MUST NOT 含 submitCardReview（消除白复习），
 *     MUST 仍含 mastered 按钮（用户亲手设的标记永不隐藏），MUST 含「去工作台」链接。
 *   B 普通 reader 卡（fsrs_s=null）⇒ 四个 DSR 复习按钮**逐个仍在**（旧语义不回归）。
 *   C 边界带（fsrs_s = 0 / "" / "abc" / NaN / 负数）⇒ 仍给四个按钮，
 *     判据放宽成 `>= 0` 或反向 MUST 立刻变红。
 *   D 工作台词 + 用户手动「已掌握」⇒ mastered 徽记与按钮仍在，复习按钮仍不渲染。
 *   E 单一判据：isWorkbenchSourced 与 cardStatsTag 的判据表达式**逐字一致**，
 *     且二者在整条边界输入带上**行为等价**（标签说工作台 ⇔ 按钮被收走）。
 *   F 复用阶梯：renderDeckStage 体内 MUST NOT 出现第二份 fsrs_s 阈值
 *     （MUST 调 isWorkbenchSourced，MUST NOT 自造判据）。
 *   G 路由非自造：「去工作台」的 href MUST 沿用 index.html 里既有的工作台路由。
 *
 * 用法：
 *   node tools/cards_workbench_no_review_probe.mjs            # 人类可读（日志走 stderr）
 *   node tools/cards_workbench_no_review_probe.mjs --json     # stdout 只输出 JSON
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
    "卡盒「工作台词不给复习按钮」契约破坏（子计划 5 Task 1）：\n  - " + problems.join("\n  - ") + "\n",
  );
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
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

const cardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "cards.js"), "utf8");
const indexHtml = fs.readFileSync(path.join(ROOT, "static", "index.html"), "utf8");

/** 去掉块注释、行注释与 HTML 注释（判据逐字比对 MUST NOT 被注释里的示例干扰；
 *  HTML 注释 MUST 一并剥 —— cards.js 的卡面模板串里带 HTML 注释，它随 innerHTML
 *  一起进 DOM，剥掉才是「只看代码」的判据）。 */
function stripComments(src) {
  return src
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`\\])\/\/[^\n]*/g, "$1");
}

let predicateFn = "";
let statsFn = "";
let renderFn = "";
try {
  statsFn = sliceFunction(cardsJs, "function cardStatsTag(");
  renderFn = sliceFunction(cardsJs, "export function renderDeckStage(");
} catch (e) {
  fail([`源码切片失败：${e.message}`]);
}
/* isWorkbenchSourced 缺失**不**提前退出：让它缺席，A/B/C/D 场景仍能真跑并报出
 * 行为层的红（否则修复前只看到「找不到声明」一句，诊断价值为零）。 */
let predicateMissing = false;
try {
  predicateFn = sliceFunction(cardsJs, "function isWorkbenchSourced(");
} catch {
  predicateMissing = true;
}
const transformed = [predicateFn, statsFn, renderFn].filter(Boolean).join("\n\n");

/* 切片护栏：切歪 / 回退 ⇒ 直接红，不许假绿 */
const stripProblems = [];
if (!transformed.includes('class="card-stats-tag"'))
  stripProblems.push("切片缺 card-stats-tag（卡面 meta 行被挪走或实现回退）");
if (!transformed.includes("correct_count"))
  stripProblems.push("切片缺 correct_count（非工作台词的旧文案路径被删了？逐字不变契约破了）");
if (!transformed.includes("submitCardReview"))
  stripProblems.push("切片缺 submitCardReview（四个 DSR 复习按钮被整段删了？普通卡仍需它）");
/* ⚠ 极性 MUST 是「命中即坏」：`^\s*` 里的 \s 含换行，MUST NOT 用 ! 反转后当守卫
 * （反转会把「没混进 import」判成坏，等于护栏恒红）。 */
if (/^[ \t]*import\b/m.test(transformed))
  stripProblems.push("切片里混入 import 行（切片边界算错了）");
if (!/\bmastered\b/.test(renderFn))
  stripProblems.push("renderDeckStage 切片缺 mastered（mastered 徽记/按钮被吞了？）");
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
    attachDeckSwipeListener() {},
    state: {},
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext("var deckIndex = 0; var deckFlipped = false;", ctx, {
    filename: "cards-workbench-no-review-prelude.js",
  });
  vm.runInContext(transformed, ctx, { filename: "cards.stripped.js" });
  return { ctx, container };
}

/** 真跑一次 renderDeckStage，返回写进容器的**真 innerHTML**。 */
function render(card) {
  const { ctx, container } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  vm.runInContext("renderDeckStage([__card], [])", ctx, { filename: "call-render.js" });
  return container.innerHTML;
}

/** 直接问真判据函数（不经渲染），供 E 场景做同源比对。判据缺失时返回 undefined。 */
function askPredicate(card) {
  if (predicateMissing) return undefined;
  const { ctx } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  return vm.runInContext("isWorkbenchSourced(__card)", ctx);
}

/** 直接问真 cardStatsTag（不经渲染），供 E 场景做同源比对。 */
function askTag(card) {
  const { ctx } = buildCtx();
  vm.runInContext("var __card = " + JSON.stringify(card) + ";", ctx, { filename: "card-fixture.js" });
  return vm.runInContext("cardStatsTag(__card)", ctx);
}

/**
 * 抠出「替代 DSR 按钮的那一块」——工作台词时卡面本该没有 sm2 按钮，
 * 剩下一句人话 + 去工作台跳转。A5/A6 就在这块上断言（MUST NOT 拿整页
 * innerHTML 当判据：整页里本来就有 card-stats-tag 那行 legitimately 带 s=…）。
 * 抠不到 ⇒ 返回整页（好让 A6 报出「连提示块都没有」而不是空串假绿）。
 */
function hintBlock(html) {
  const m = /<div class="deck-workbench-hint">[\s\S]*?<\/div>/.exec(html);
  return m ? m[0] : html;
}

/* ---------------------------------------------------------------------------
 * 3. 夹具与断言常量
 * ------------------------------------------------------------------------ */
/** 基线卡：普通 reader 卡，DSR 侧有真实进度，due_date 已排程。 */
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

/** 工作台词：用户在背词工作台背过（fsrs_s=25），卡盒 DSR 侧从未复习。 */
const WORKBENCH_CARD = {
  ...READER_CARD,
  fsrs_s: 25,
  correct_count: 0,
  wrong_count: 0,
  repetition_count: 0,
  due_date: null,
};

/** 断言常量：四个 DSR 复习按钮的 grade 调用形态（非实现重抄，是产品契约）。 */
const GRADE_CALLS = [1, 2, 3, 4].map((g) => `submitCardReview('vocab', 42, ${g})`);

/** 断言常量：既有工作台路由（index.html 的 iframe src 逐字复用，MUST NOT 自造）。 */
const WORKBENCH_ROUTE = "/german/workbench.html";

const problems = [];
const cases = [];
const record = (name, ok, detail) => { cases.push({ name, ok, detail }); if (!ok) problems.push(`${name}：${detail}`); };

/* ══ A 工作台词：不给复习按钮，保留 mastered 按钮 + 去工作台跳转 ══════════════ */
{
  const html = render(WORKBENCH_CARD);
  log(`[A] 工作台词渲染长度: ${html.length}`);

  record(
    "A1-工作台词不渲染DSR复习按钮",
    !html.includes("submitCardReview"),
    `工作台词卡面仍渲染 submitCardReview（DSR 四列被写、fsrs_s 不动 = 白复习）：${html.match(/submitCardReview[^\n]{0,40}/g)}`,
  );
  record(
    "A2-工作台词保留mastered按钮",
    /class="card-master-btn/.test(html),
    "工作台词卡面把 mastered 按钮一起吞了 —— 用户亲手设的标记永不隐藏",
  );
  record(
    "A3-工作台词保留工作台徽记",
    /card-stats-tag[^>]*>[^<]*工作台/.test(html),
    `工作台词卡面丢了「📚 工作台」徽记：${(/card-stats-tag[^>]*>([^<]*)/.exec(html) || [])[1]}`,
  );
  record(
    "A4-工作台词有去工作台链接",
    html.includes(`href="${WORKBENCH_ROUTE}"`),
    `工作台词卡面没有指向既有工作台路由（${WORKBENCH_ROUTE}）的跳转：${html.match(/<a [^>]*>/g)}`,
  );
  record(
    "A5-去工作台提示是人话",
    /工作台/.test(hintBlock(html)) && /复习/.test(hintBlock(html)),
    `「去工作台」位置的提示没写成用户看得懂的话（应含「工作台」+「复习」）：${JSON.stringify(hintBlock(html))}`,
  );
  record(
    "A6-提示不泄漏技术字段名",
    !/fsrs_s|repetition_count|correct_count|fsrs/i.test(hintBlock(html)),
    `替代按钮那块渲染出了技术字段名（fsrs_s / repetition_count / correct_count）：${JSON.stringify(hintBlock(html))}`,
  );
}

/* ══ B 不回归：普通 reader 卡的四个复习按钮逐个仍在 ═══════════════════════ */
{
  const html = render(READER_CARD);
  log(`[B] 普通卡 submitCardReview 出现次数: ${(html.match(/submitCardReview/g) || []).length}`);
  const missing = GRADE_CALLS.filter((c) => !html.includes(c));
  record(
    "B1-普通卡四个复习按钮齐全",
    missing.length === 0,
    `普通 reader 卡丢了 DSR 复习按钮 ${JSON.stringify(missing)}（submitCardReview MUST NOT 被删）`,
  );
  record(
    "B2-普通卡无去工作台链接",
    !html.includes(WORKBENCH_ROUTE),
    "普通 reader 卡也被塞了「去工作台」跳转（非工作台词的旧语义 MUST 逐字不变）",
  );
  record(
    "B3-普通卡保留mastered按钮",
    /class="card-master-btn/.test(html),
    "普通卡把 mastered 按钮吞了",
  );
}

/* ══ C 边界带：判据放宽 / 反向 MUST 立刻变红 ═════════════════════════════ */
for (const [label, value] of [
  ["0", 0],
  ["空串", ""],
  ["字符串0", "0"],
  ["脏值abc", "abc"],
  ["NaN", Number.NaN],
  ["负数", -1],
]) {
  const html = render({ ...READER_CARD, fsrs_s: value });
  const missing = GRADE_CALLS.filter((c) => !html.includes(c));
  record(
    `C-fsrs_s=${label}仍给四个复习按钮`,
    missing.length === 0 && !html.includes(WORKBENCH_ROUTE),
    `fsrs_s=${label} 被误判成工作台来源，四个 DSR 复习按钮被收走 ${JSON.stringify(missing)} —— 判据 MUST 是 > 0，不是 >= 0 / 非空`,
  );
}

/* ══ D 工作台词 + 用户手动已掌握：徽记与按钮永不隐藏 ═════════════════════ */
{
  const html = render({ ...WORKBENCH_CARD, mastered: 1 });
  record(
    "D1-已掌握工作台词仍无复习按钮",
    !html.includes("submitCardReview"),
    "已掌握的工作台词又开始给 DSR 复习按钮了（白复习没消除）",
  );
  record(
    "D2-已掌握工作台词保留mastered徽记",
    /card-stats-tag[^>]*>[^<]*已掌握/.test(html),
    `已掌握工作台词的「🛡️ 已掌握」徽记被吞了：${(/card-stats-tag[^>]*>([^<]*)/.exec(html) || [])[1]}`,
  );
  record(
    "D3-已掌握工作台词保留mastered按钮",
    /class="card-master-btn/.test(html),
    "已掌握工作台词把 mastered 按钮吞了（用户无法再点回待复习）",
  );
  record(
    "D4-已掌握工作台词仍有去工作台链接",
    html.includes(`href="${WORKBENCH_ROUTE}"`),
    "已掌握工作台词丢了「去工作台」跳转",
  );
}

/* ══ E 单一判据：表达式逐字一致 + 整条边界带上行为等价 ═══════════════════ */
if (predicateMissing) {
  record(
    "E0-存在工作台来源判据函数",
    false,
    "cards.js 里没有 isWorkbenchSourced(card) —— 卡面没有可复用的工作台来源判据（只能去复制第二份阈值）",
  );
} else {
  const norm = (fnSrc) => {
    const line = stripComments(fnSrc)
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l.includes("isFinite"));
    if (!line) return null;
    /* 归一：剥 `if (` / `return ` 前缀与 `)` `;` `{` 尾巴，只留判据表达式本体。
     * 目的是让 `if (EXPR) {`（cardStatsTag）与 `return EXPR;`（isWorkbenchSourced）
     * 两种句式比对的是**同一条判据**，而不是连标点都比。 */
    return line
      .replace(/^if\s*\(/, "")
      .replace(/^return\s+/, "")
      .replace(/[)\s;{]+$/, "")
      .replace(/\s+/g, " ");
  };
  const a = norm(predicateFn);
  const b = norm(statsFn);
  if (a === null || b === null) {
    problems.push(`E-判据表达式定位失败：isWorkbenchSourced=${JSON.stringify(a)} cardStatsTag=${JSON.stringify(b)}`);
  } else if (a !== b) {
    problems.push(
      `E-判据表达式两份拷贝已漂移：isWorkbenchSourced=${JSON.stringify(a)} vs cardStatsTag=${JSON.stringify(b)} —— ` +
      `同一语义两个真相（标签与按钮会不一致）`,
    );
  }
  record("E1-判据表达式逐字同源", a !== null && b !== null && a === b, `两份判据不一致：${JSON.stringify(a)} vs ${JSON.stringify(b)}`);

  /* 行为等价：判据说「工作台」⇔ 标签说「工作台」。判据漂移必在带内露馅。 */
  const band = [
    null, undefined, 0, "0", "", " ", 25, "25.0", 0.0001, -1, Number.NaN, "abc", 1e-9, 25.5, 3,
  ];
  const diverged = band.filter((v) => {
    const card = { ...READER_CARD, fsrs_s: v };
    return askPredicate(card) !== /工作台/.test(askTag(card));
  });
  record(
    "E2-判据与标签整带行为等价",
    diverged.length === 0,
    `以下 fsrs_s 取值上「是否工作台来源」与「标签是否说工作台」判定分叉：${JSON.stringify(diverged)} —— ` +
    `按钮会与标签对不上（用户看到 📚 工作台 却仍能点 DSR 复习，或反之）`,
  );
  record(
    "E3-工作台侧判据为真",
    askPredicate({ ...READER_CARD, fsrs_s: 25 }) === true,
    "fsrs_s=25 的工作台词没有被 isWorkbenchSourced 判成工作台来源",
  );
  record(
    "E4-普通卡侧判据为假",
    askPredicate({ ...READER_CARD, fsrs_s: null }) === false,
    "fsrs_s=null 的普通卡被误判成工作台来源",
  );
}

/* ══ F 复用阶梯：renderDeckStage MUST NOT 自造第二份阈值 ═════════════════ */
{
  const renderBody = stripComments(renderFn);
  if (/fsrs_s/.test(renderBody)) {
    problems.push("F-renderDeckStage 体内出现 fsrs_s —— 卡面自造了第二份工作台来源判据（应调 isWorkbenchSourced）");
  }
  if (!/isWorkbenchSourced\s*\(/.test(renderBody)) {
    problems.push("F-renderDeckStage 体内没有调 isWorkbenchSourced —— 判据被绕开或改名了");
  }
  record("F1-渲染复用单一判据", /isWorkbenchSourced\s*\(/.test(renderBody) && !/fsrs_s/.test(renderBody),
    "renderDeckStage 没有复用 isWorkbenchSourced（自造了第二份阈值）");
}

/* ══ G 路由非自造：href 沿用 index.html 里既有的工作台路由 ═══════════════ */
{
  if (!indexHtml.includes(WORKBENCH_ROUTE)) {
    problems.push(`G-夹具失配：index.html 里已找不到既有工作台路由 ${WORKBENCH_ROUTE}，探针不可信`);
  }
  const hrefs = (render(WORKBENCH_CARD).match(/href="([^"]*)"/g) || []);
  const invented = hrefs.filter((h) => !h.includes(WORKBENCH_ROUTE));
  record(
    "G1-跳转未自造路由",
    hrefs.length === 1 && invented.length === 0,
    `工作台词卡面上的 href 集合异常 ${JSON.stringify(hrefs)}（MUST 只有既有工作台路由一条）`,
  );
}

if (problems.length) fail(problems);

const out = {
  ok: true,
  failures: 0,
  total: cases.length,
  cases: cases.map((c) => ({ name: c.name, ok: true })),
  samples: {
    workbenchHasReviewButtons: render(WORKBENCH_CARD).includes("submitCardReview"),
    readerHasReviewButtons: GRADE_CALLS.every((c) => render(READER_CARD).includes(c)),
    workbenchRoute: WORKBENCH_ROUTE,
  },
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log(`场景数: ${out.total}`);
  console.log(`工作台词含 DSR 复习按钮: ${out.samples.workbenchHasReviewButtons}（期望 false）`);
  console.log(`普通卡含 DSR 复习按钮: ${out.samples.readerHasReviewButtons}（期望 true）`);
  console.log(`去工作台路由（既有）: ${out.samples.workbenchRoute}`);
  console.log("PROBE PASS: 工作台词在卡盒不渲染 DSR 复习按钮，保留 mastered 按钮 + 去工作台跳转；普通卡四个按钮逐字未变");
}
