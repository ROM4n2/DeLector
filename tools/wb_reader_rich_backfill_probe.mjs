/**
 * wb_reader_rich_backfill_probe.mjs —— 背词工作台「精读生词（reader 档）富字段回填」动态探针
 * （fix/reader-vocab-rich-backfill）
 *
 * 背景（已确诊根因）：static/german/workbench.html 的 syncReaderCardsFromServer 曾
 * 是 **append-only**（只在 `!existingIds.has(wid)` 时 push，无 else 分支）→ 富字段
 * 上线前首次同步进去的存量生词恒为 `ipa: ""` / `ex: []`，此后每次同步都被跳过 ——
 * 生词卡永远裸（无例句无音标），与 A1/A2/B1 三档信息量不对齐。修复后升级为
 * 「只增 + 只补空字段」。
 *
 * 静态字符串断言只能证明「源码里有这行」，证明不了「手编例句真的没被覆盖」「原句
 * 优先时官方中文真的没被塞进去」「二次同步真的 no-op」「FSRS 进度真的没被动」。本
 * 探针把 workbench.html 里的 **真实源码**（syncReaderCardsFromServer 函数体）按花
 * 括号配对整段切出来，丢进 node:vm 沙箱真跑，只提供 S / fetch / save* 等最小桩。
 *
 * 硬约束（同 wb_rich_backfill_probe.mjs）：探针里**不得重抄一份实现**。一切被测
 * 逻辑均来自 workbench.html 切片；本文件只提供桩与夹具。
 *
 * 用法：node tools/wb_reader_rich_backfill_probe.mjs
 *   每个场景打印 PASS/FAIL；末尾汇总 FAIL 计数，>0 时设 process.exitCode = 1。
 *   node tools/wb_reader_rich_backfill_probe.mjs --json
 *   --json 时 stdout 只输出单个 JSON 对象
 *   {"fail": <int>, "total": <int>, "cases": [{"name", "ok", "detail"}]}（供 pytest
 *   行为级断言消费），人类可读输出静默，退出码恒为 0（由断言侧判 fail == 0）。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
/* ---- 探针读取口（C7 Task 2）：可多文件来源 ------------------------------
 * 现在只有 `workbench.html` 一个源文件，故 `readSources(SRC_FILES)` 与改造前的
 * `fs.readFileSync(HTML, "utf8")` 逐字节等价（单文件时 join 不插入任何字节）。
 * workbench.html 拆成模块后只需改 `WB_SRC_ROOT` 与 `SRC_FILES`，切片语义不动。 */
const SRC_ROOT = process.env.WB_SRC_ROOT ?? "static/german";
const SRC_FILES = ["workbench.html"];

function readSources(names) {
  const parts = names.map((name) => {
    const dir = path.isAbsolute(SRC_ROOT) ? SRC_ROOT : path.join(ROOT, SRC_ROOT);
    const file = path.isAbsolute(name) ? name : path.join(dir, name);
    if (!fs.existsSync(file)) {
      process.stderr.write(`探针源文件不存在：${file}（声明搬迁后请同步 WB_SRC_ROOT / SRC_FILES）\n`);
      process.exit(3);
    }
    const text = fs.readFileSync(file, "utf8");
    if (!text.length) {
      process.stderr.write(`探针源文件为空：${file}\n`);
      process.exit(3);
    }
    return text;
  });
  return parts.join("\n");
}

const JSON_MODE = process.argv.includes("--json");

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整函数体（跳过字符串与注释）
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号（${src[openIdx]}）`);
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

/** 找不到声明就此**非零退出**，并打印所查声明名（No-Silent-Skip：返回空串会让
 *  下游 `in` 断言静默假绿）。退出码 3 = 读取口失败，与「契约被破坏」的 1 区分开。 */
function dieMissingDecl(name) {
  process.stderr.write(
    `探针源 ${SRC_FILES.join(", ")}（根目录 ${SRC_ROOT}）里找不到声明 ${name}\n`
  );
  process.exit(3);
}

/** 统一切片入口：按名字定位 `const/let/var NAME =` 或 `[async] function NAME(`，
 *  用括号配平取到声明体结尾（变量声明含结尾分号）；值为标量（不含括号）时读到语句分号。
 *  语义与改造前各探针自抄的 extractDecl / extractDeclAny / extractDeclAny（标量口径）/
 *  extractFn / sliceBlock / 内联 anchor 六种口径逐字一致（改前已实测：132 个顶层函数与
 *  52 个顶层声明逐条比对，零差异）。 */
function sliceDecl(src, name) {
  const decl = new RegExp(`^(?:const|let|var)\\s+${name}\\s*=`, "m").exec(src);
  const m = decl || new RegExp(`^(?:async\\s+)?function\\s+${name}\\s*\\(`, "m").exec(src);
  if (!m) dieMissingDecl(`const/let/var/function ${name}`);
  if (!decl) {
    /* 函数声明：m[0] 以 `(` 结尾 ⇒ 参数表先括号配对，再取函数体花括号 */
    const parenClose = matchBracket(src, m.index + m[0].length - 1);
    const braceOpen = src.indexOf("{", parenClose);
    if (braceOpen < 0) {
      process.stderr.write(`函数 ${name} 的参数表之后找不到函数体花括号，切歪了\n`);
      process.exit(3);
    }
    return src.slice(m.index, matchBracket(src, braceOpen) + 1);
  }
  const after = m.index + m[0].length;
  let i = after;
  while (i < src.length && /\s/.test(src[i])) i++;
  if (!OPEN[src[i]]) {
    /* 标量声明（`const SCHEMA_KEY = "wb.schema.v1";`）：值不含括号，读到语句分号。
     * 前提：标量值内不得含 ASCII `;`（13 个探针的目标声明实测均无，含
     * `CORE_WORD_SEED_IDS = new Set([...])`）—— 若违反，切片会在此截断 ⇒ 以语法错 /
     * 退出码 3 报出，不会静默通过。 */
    const tail = src.indexOf(";", after);
    if (tail < 0) {
      process.stderr.write(`声明 ${name} 结尾找不到分号，切歪了\n`);
      process.exit(3);
    }
    return src.slice(m.index, tail + 1);
  }
  const end = matchBracket(src, i);
  const semi = src.indexOf(";", end);
  if (semi < 0 || semi > end + 8) {
    process.stderr.write(`声明 ${name} 结尾找不到分号，切歪了（end=${end} semi=${semi}）\n`);
    process.exit(3);
  }
  return src.slice(m.index, semi + 1);
}

const html = readSources(SRC_FILES);
const READER_SYNC = sliceDecl(html, "syncReaderCardsFromServer");
if (!READER_SYNC || READER_SYNC.length < 40) {
  throw new Error(`syncReaderCardsFromServer 切片长度异常（${READER_SYNC && READER_SYNC.length}），锚点可能失配`);
}
/* 防死测：切片必须是真实现（只补空回填分支确已存在），否则实现回退了探针照样绿 */
if (!/\} else \{/.test(READER_SYNC)) {
  throw new Error("syncReaderCardsFromServer 切片里没有「已存在则回填」else 分支，切歪或实现回退了");
}
for (const re of [/\!cur\.ipa\s*&&\s*rw\.ipa/, /\!cur\.gender\s*&&\s*rw\.gender/, /\!cur\.plural\s*&&\s*rw\.plural/]) {
  if (!re.test(READER_SYNC)) {
    throw new Error(`syncReaderCardsFromServer 切片缺少「只补空」守卫 ${re}，切歪或实现回退了`);
  }
}
/* 反向守卫（运行时再钉一次源码形态）：回填只动词表，不得触碰 FSRS 进度 */
for (const forbidden of ["S.cards", "S.log", "S.wrong"]) {
  if (READER_SYNC.includes(forbidden)) {
    throw new Error(`syncReaderCardsFromServer 切片出现 ${forbidden}：回填禁止触碰 FSRS 复习进度`);
  }
}

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只提供被测代码依赖的最小桩
 * ------------------------------------------------------------------------ */
const PRELUDE = `
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: {} };
var wordFilters = { scope: "reader" };
var location = { protocol: "http:" };
var __saved = 0;
var __savedCards = 0;
var __fetchPayload = null;
function saveWords() { __saved++; }
function saveCards() { __savedCards++; }
function renderWords() {}
function refilterReviewQueueForScope() {}
function renderHeaderBadge() {}
async function fetch(_url) {
  return { ok: true, json: async function () { return __fetchPayload; } };
}
`;

const ctx = vm.createContext({ console });
vm.runInContext(PRELUDE + "\n" + READER_SYNC + "\n", ctx, {
  filename: "workbench-reader-rich-backfill-slices.js",
});

/* ---------------------------------------------------------------------------
 * 3. 夹具：reader 档真实端点契约（/api/cards/vocab?scope=reader → {words:[12 字段]}）
 * ------------------------------------------------------------------------ */
const ID = "card-7";

/** 存量生词（reader sync 落库形态：ipa:"" / ex:[] = 富字段上线前的裸卡）。 */
function existing(over) {
  return Object.assign({
    id: ID, hw: "Zustand", pos: "n.", gloss: "状态", zh: "状态", ipa: "",
    ex: [], letter: "Z", page: 0, tags: ["reader"], custom: true, up: 0,
    gender: null, plural: "",
  }, over || {});
}

/** 服务端 reader 行（12 字段契约）。 */
function remote(over) {
  return Object.assign({
    id: ID, hw: "Zustand", pos: "n.", gender: "Masc", plural: "-..e",
    de: "Als wir in die Wohnung eingezogen sind, war sie in sehr schlechtem Zustand.",
    zh: "状态", ipa: "deːɐ tsˈʊstant", example_zh: "我们搬进来时，这套房子状况很差。",
    core: false, cefr: "A1", letter: "Z",
  }, over || {});
}

/* ---------------------------------------------------------------------------
 * 4. 驱动：把状态灌进沙箱、await 真实 sync 函数、读回结果
 * ------------------------------------------------------------------------ */
function setup({ words, cards, log, wrong, payload }) {
  ctx.__state = {
    words: JSON.parse(JSON.stringify(words || [])),
    cards: JSON.parse(JSON.stringify(cards || {})),
    log: JSON.parse(JSON.stringify(log || {})),
    wrong: JSON.parse(JSON.stringify(wrong || {})),
    payload: JSON.parse(JSON.stringify(payload)),
  };
  vm.runInContext(
    "S.words = __state.words; S.cards = __state.cards; S.log = __state.log; S.wrong = __state.wrong; " +
      "wordFilters.scope = 'reader'; __fetchPayload = __state.payload; __saved = 0; __savedCards = 0;",
    ctx
  );
}
async function exec() {
  await vm.runInContext("(function () { return syncReaderCardsFromServer(); })()", ctx);
}
const wordsNow = () => JSON.parse(vm.runInContext("JSON.stringify(S.words)", ctx));
const progNow = () => JSON.parse(vm.runInContext("JSON.stringify({ cards: S.cards, log: S.log, wrong: S.wrong })", ctx));
const savedNow = () => vm.runInContext("__saved", ctx);
const cardsSavedNow = () => vm.runInContext("__savedCards", ctx);
const resetSaved = () => vm.runInContext("__saved = 0;", ctx);
const find = (words, id) => words.find((w) => w.id === id);

/* ---------------------------------------------------------------------------
 * 5. 场景执行 + PASS/FAIL 汇总
 * ------------------------------------------------------------------------ */
const cases = [];
let failCount = 0;
function check(name, cond, detail) {
  const ok = !!cond;
  cases.push({ name, ok, detail: detail == null ? "" : String(detail) });
  if (!ok) failCount++;
  if (!JSON_MODE) {
    console.log(ok ? `PASS  ${name}` : `FAIL  ${name}${detail ? "  —  " + detail : ""}`);
  }
}

/* #1 回填空 ipa：存量生词 ipa:"" + 服务端有 ipa → 被补上（且写盘一次） */
{
  const rw = remote();
  setup({ words: [existing()], payload: { words: [rw] } });
  await exec();
  const cur = find(wordsNow(), ID);
  check("reader #1 回填空 ipa", cur.ipa === rw.ipa, "ipa=" + JSON.stringify(cur.ipa));
  check("reader #1 changed → saveWords 恰好一次", savedNow() === 1, "saveWords=" + savedNow());
}

/* #2 回填空 ex：存量生词 ex:[] + 服务端有 de → ex 被填成 [{de,zh}] */
{
  const rw = remote();
  setup({ words: [existing({ ipa: rw.ipa })], payload: { words: [rw] } });
  await exec();
  const cur = find(wordsNow(), ID);
  check(
    "reader #2 回填空 ex",
    Array.isArray(cur.ex) && cur.ex.length === 1 && cur.ex[0].de === rw.de && cur.ex[0].zh === rw.example_zh,
    "ex=" + JSON.stringify(cur.ex)
  );
}

/* #3 原句优先：服务端 de 是生词所在原句 → example_zh 为空，ex 的 zh 不得被塞入官方中文；
 *    同批另一条走「无原句」路径（de = 官方例句 + example_zh 非空）→ zh 正常带上。 */
{
  const SENTENCE = "Der Zustand der Wohnung war schlecht.";
  const ctxRow = remote({ id: ID, de: SENTENCE, example_zh: "" });
  const offRow = remote({
    id: "card-8", hw: "Haus", de: "In welchem Haus wohnst du?", example_zh: "你住在哪栋房子里？",
  });
  const offExisting = Object.assign(existing({ id: "card-8", hw: "Haus" }), { ipa: "" });
  setup({ words: [existing(), offExisting], payload: { words: [ctxRow, offRow] } });
  await exec();
  const words = wordsNow();
  const withCtx = find(words, ID);
  const withOfficial = find(words, "card-8");
  check(
    "reader #3 原句优先（ex.de = 原句 且 zh 不塞官方中文）",
    Array.isArray(withCtx.ex) && withCtx.ex.length === 1 &&
      withCtx.ex[0].de === SENTENCE && withCtx.ex[0].zh === "",
    "ex=" + JSON.stringify(withCtx.ex)
  );
  check(
    "reader #3 无原句时官方例句中文正常带上（对照）",
    Array.isArray(withOfficial.ex) && withOfficial.ex.length === 1 &&
      withOfficial.ex[0].de === offRow.de && withOfficial.ex[0].zh === offRow.example_zh,
    "ex=" + JSON.stringify(withOfficial.ex)
  );
}

/* #4 保护非空：已有 ipa / 手编 ex / 手编 gender / plural → 逐字不变，且整体无变更 */
{
  const manual = [{ de: "我手编的例句", zh: "手编中文" }];
  const word = existing({
    ipa: "MY-IPA",
    ex: manual.map((x) => ({ ...x })),
    gender: "Fem",
    plural: "MY-PLURAL",
  });
  const before = JSON.stringify({ ipa: word.ipa, ex: word.ex, gender: word.gender, plural: word.plural });
  setup({ words: [word], payload: { words: [remote()] } });
  await exec();
  const cur = find(wordsNow(), ID);
  const after = JSON.stringify({ ipa: cur.ipa, ex: cur.ex, gender: cur.gender, plural: cur.plural });
  check("reader #4 保护非空 ipa / 手编 ex / gender / plural（不覆盖）", after === before, "after=" + after);
  check("reader #4 全字段非空 → changed=false（不写盘）", savedNow() === 0, "saveWords=" + savedNow());
}

/* #5 FSRS 不动：回填前后 S.cards / S.log / S.wrong 深度相等，且 cards 写盘次数为 0 */
{
  const cards = { [ID]: { reps: 5, due: 100, ef: 2.5 } };
  const log = { "2026-01-01": { rv: 3, good: 2 } };
  const wrong = { [ID]: { n: 2 } };
  const before = JSON.stringify({ cards, log, wrong });
  setup({ words: [existing()], cards, log, wrong, payload: { words: [remote()] } });
  await exec();
  const after = JSON.stringify(progNow());
  const cur = find(wordsNow(), ID);
  check("reader #5 FSRS 进度深度不变", after === before, "after=" + after);
  check("reader #5 cards 写盘次数为 0", cardsSavedNow() === 0, "saveCards=" + cardsSavedNow());
  check("reader #5 回填确有发生（ipa 已补）", cur.ipa === remote().ipa, "ipa=" + JSON.stringify(cur.ipa));
}

/* #6 幂等：同一批数据连跑两次，第二次 changed === false（不写盘、词表逐字节不变） */
{
  const rw = remote();
  setup({ words: [existing()], payload: { words: [rw] } });
  await exec();
  const firstSaved = savedNow();
  const afterFirst = JSON.stringify(wordsNow());
  resetSaved();
  await exec();
  const secondSaved = savedNow();
  const afterSecond = JSON.stringify(wordsNow());
  check(
    "reader #6 幂等（首跑写盘 / 二跑 changed=false no-op / 词表逐字节不变）",
    firstSaved === 1 && secondSaved === 0 && afterFirst === afterSecond,
    `firstSaved=${firstSaved} secondSaved=${secondSaved} stable=${afterFirst === afterSecond}`
  );
}

/* #7 新词仍加入（回归）：不存在的 id 走 push 分支，tags 为 ["reader"] */
{
  const rw = remote({ id: "card-99", hw: "Wohnung" });
  setup({ words: [], payload: { words: [rw] } });
  await exec();
  const cur = find(wordsNow(), "card-99");
  check(
    "reader #7 新词仍加入（push 分支回归，tags=[\"reader\"]）",
    !!cur && JSON.stringify(cur.tags) === JSON.stringify(["reader"]),
    cur ? JSON.stringify({ tags: cur.tags, hw: cur.hw, letter: cur.letter }) : "null"
  );
}

/* #8 只补空 gender / plural：服务端有值 → 补上；非空则不动 */
{
  const rw = remote();
  setup({ words: [existing({ gender: null, plural: "", ipa: rw.ipa, ex: [{ de: "x", zh: "y" }] })], payload: { words: [rw] } });
  await exec();
  const cur = find(wordsNow(), ID);
  check(
    "reader #8 补齐空 gender / plural",
    cur.gender === rw.gender && cur.plural === rw.plural,
    "gender=" + cur.gender + " plural=" + cur.plural
  );
}

if (JSON_MODE) {
  /* 单个 JSON 到 stdout，供 pytest 解析；退出码恒为 0，由断言侧判 fail == 0。 */
  process.stdout.write(JSON.stringify({ fail: failCount, total: cases.length, cases }));
} else {
  console.log("");
  if (failCount > 0) {
    console.log(`FAIL 汇总：${failCount} 个场景未通过`);
    process.exitCode = 1;
  } else {
    console.log("ALL PASS：reader 精读生词富字段回填行为自检通过");
  }
}
