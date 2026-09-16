/**
 * wb_rich_backfill_probe.mjs —— 背词工作台「A2/B1 富字段回填」动态探针
 * （fix/rich-fields-backfill · Task A）
 *
 * 背景（已确诊根因）：static/german/workbench.html 的 syncA2CardsFromServer /
 * syncB1CardsFromServer 曾是 **append-only**（只在 `!existingIds.has(wid)` 时 push，
 * 无 else 分支）→ 富字段上线前首次同步进去的存量词条恒为 `ex: []`，此后每次同步
 * 都被跳过，用户看到「A2 只有部分词有例句」。修复后为「只增 + 只补空字段」。
 *
 * 静态字符串断言只能证明「源码里有这行」，证明不了「手编例句真的没被覆盖」「二次
 * 同步真的 no-op」「FSRS 进度真的没被动」。本探针把 workbench.html 里的 **真实源码**
 * （CEFR_BY_PREFIX / cefrFromId / normalizeWord / 两个 sync 函数体）按花括号配对整段
 * 切出来，丢进 node:vm 沙箱真跑，只提供 S / fetch / save* 等最小桩。
 *
 * 硬约束（同 wb_tags_probe.mjs / wb_merge_probe.mjs）：探针里**不得重抄一份实现**。
 * 一切被测逻辑均来自 workbench.html 切片；本文件只提供桩与夹具。
 *
 * 用法：node tools/wb_rich_backfill_probe.mjs
 *   每个场景打印 PASS/FAIL；末尾汇总 FAIL 计数，>0 时设 process.exitCode = 1。
 *   node tools/wb_rich_backfill_probe.mjs --json
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
const HTML = path.join(ROOT, "static", "german", "workbench.html");
const JSON_MODE = process.argv.includes("--json");

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整声明/函数体（跳过字符串与注释）
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

function extractDecl(src, name) {
  const anchor = new RegExp(`^const\\s+${name}\\s*=`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到声明 const ${name}`);
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  const semi = src.indexOf(";", end);
  if (semi < 0 || semi > end + 8) throw new Error(`const ${name} 声明结尾找不到分号，切歪了`);
  return src.slice(m.index, semi + 1);
}

/** 抽取 `[async] function name(...) { ... }`（两种前缀都支持）。 */
function extractFn(src, name, isAsync) {
  const prefix = isAsync ? "async function" : "function";
  const anchor = new RegExp(`^${prefix}\\s+${name}\\s*\\(`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`workbench.html 里找不到函数 ${name}`);
  const parenOpen = src.indexOf("(", m.index);
  const parenClose = matchBracket(src, parenOpen);
  const braceOpen = src.indexOf("{", parenClose);
  const braceClose = matchBracket(src, braceOpen);
  return src.slice(m.index, braceClose + 1);
}

const html = fs.readFileSync(HTML, "utf8");
const PIECES = {
  CEFR_BY_PREFIX: extractDecl(html, "CEFR_BY_PREFIX"),
  cefrFromId: extractFn(html, "cefrFromId", false),
  normalizeWord: extractFn(html, "normalizeWord", false),
  syncA2CardsFromServer: extractFn(html, "syncA2CardsFromServer", true),
  syncB1CardsFromServer: extractFn(html, "syncB1CardsFromServer", true),
};
for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 40) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
}
/* 防死测：切片必须是真实现（回填分支确已存在），否则实现回退了探针照样绿 */
for (const fnName of ["syncA2CardsFromServer", "syncB1CardsFromServer"]) {
  if (!/\} else \{/.test(PIECES[fnName])) {
    throw new Error(`${fnName} 切片里没有「已存在则回填」else 分支，切歪或实现回退了`);
  }
  if (!/!cur\.ipa\s*&&\s*rw\.ipa/.test(PIECES[fnName])) {
    throw new Error(`${fnName} 切片里没有「只补空 ipa」逻辑，切歪或实现回退了`);
  }
}

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只提供被测代码依赖的最小桩
 * ------------------------------------------------------------------------ */
const PRELUDE = `
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: {} };
var wordFilters = { scope: "a2" };
var location = { protocol: "http:" };
var __saved = 0;
var __fetchPayload = null;
function saveWords() { __saved++; }
function renderWords() {}
function refilterReviewQueueForScope() {}
function renderHeaderBadge() {}
async function fetch(_url) {
  return { ok: true, json: async function () { return __fetchPayload; } };
}
`;

const ctx = vm.createContext({ console });
vm.runInContext(PRELUDE + "\n" + Object.values(PIECES).join("\n") + "\n", ctx, {
  filename: "workbench-rich-backfill-slices.js",
});

/* ---------------------------------------------------------------------------
 * 3. 夹具：A2 / B1 两套 profile（真实端点契约：A2 数组 / B1 {words} 信封）
 * ------------------------------------------------------------------------ */
const PROFILES = {
  A2: {
    fn: "syncA2CardsFromServer",
    scope: "a2",
    wrap: (arr) => arr,
    tags: ["a2"],
    cefr: "A2",
    id: "a2-haus",
    existing: (over) => Object.assign({
      id: "a2-haus", hw: "das Haus", pos: "n.", gloss: "房子", ipa: "",
      ex: [], letter: "H", page: 0, tags: ["a2"], cefr: "A2", custom: false, up: 0,
    }, over || {}),
    remote: (over) => Object.assign({
      id: "a2-haus", word: "das Haus", lemma: "Haus", pos: "n.", zh: "房子",
      ipa: "haʊs", de: "Das Haus ist groß.", example_zh: "房子很大。",
    }, over || {}),
    newRemote: (over) => Object.assign({
      id: "a2-neu", word: "das Neue", lemma: "Neue", pos: "n.", zh: "新东西",
      ipa: "ˈnɔʏə", de: "Das Neue ist gut.", example_zh: "新东西很好。",
    }, over || {}),
  },
  B1: {
    fn: "syncB1CardsFromServer",
    scope: "b1",
    wrap: (arr) => ({ words: arr }),
    tags: ["b1"],
    cefr: "B1",
    id: "b1-essen",
    existing: (over) => Object.assign({
      id: "b1-essen", hw: "das Essen", pos: "n.", gloss: "饭菜", ipa: "",
      ex: [], letter: "E", page: 0, tags: ["b1"], cefr: "B1", custom: false, up: 0,
      gender: null, plural: "",
    }, over || {}),
    remote: (over) => Object.assign({
      id: "b1-essen", hw: "das Essen", pos: "n.", zh: "饭菜", ipa: "ˈɛsn̩",
      de: "Das Essen ist warm.", example_zh: "饭菜是热的。", gender: "das", plural: "die Essen",
    }, over || {}),
    newRemote: (over) => Object.assign({
      id: "b1-neu", hw: "das Neue", pos: "n.", zh: "新东西", ipa: "ˈnɔʏə",
      de: "Das Neue ist gut.", example_zh: "新东西很好。", gender: "das", plural: "die Neue",
    }, over || {}),
  },
};

/* ---------------------------------------------------------------------------
 * 4. 驱动：把状态灌进沙箱、await 真实 sync 函数、读回结果
 * ------------------------------------------------------------------------ */
function setup({ scope, words, cards, log, wrong, payload }) {
  ctx.__state = {
    scope,
    words: JSON.parse(JSON.stringify(words || [])),
    cards: JSON.parse(JSON.stringify(cards || {})),
    log: JSON.parse(JSON.stringify(log || {})),
    wrong: JSON.parse(JSON.stringify(wrong || {})),
    payload: JSON.parse(JSON.stringify(payload)),
  };
  vm.runInContext(
    "S.words = __state.words; S.cards = __state.cards; S.log = __state.log; S.wrong = __state.wrong; " +
      "wordFilters.scope = __state.scope; __fetchPayload = __state.payload; __saved = 0;",
    ctx
  );
}
async function exec(fnName) {
  await vm.runInContext(`(function () { return ${fnName}(); })()`, ctx);
}
const wordsNow = () => JSON.parse(vm.runInContext("JSON.stringify(S.words)", ctx));
const progNow = () => JSON.parse(vm.runInContext("JSON.stringify({ cards: S.cards, log: S.log, wrong: S.wrong })", ctx));
const savedNow = () => vm.runInContext("__saved", ctx);
const resetSaved = () => vm.runInContext("__saved = 0;", ctx);
const find = (words, id) => words.find((w) => w.id === id);

/* ---------------------------------------------------------------------------
 * 5. 场景执行 + PASS/FAIL 汇总
 * ------------------------------------------------------------------------ */
/* 每个 check 都落一条 case 记录：JSON 模式据此汇总，人类模式据此打 PASS/FAIL。 */
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

/* profile × 6 场景（B1 额外一条 gender/plural 补齐），全部真实执行 sync 函数体。 */
for (const pname of ["A2", "B1"]) {
  const P = PROFILES[pname];

  /* #1 回填：存量词 ex:[] + 服务端 de 非空 → ex 被填成 [{de,zh}]，且 saveWords 落盘一次 */
  {
    const remote = P.remote();
    setup({ scope: P.scope, words: [P.existing({ ipa: "keep-ipa" })], payload: P.wrap([remote]) });
    await exec(P.fn);
    const cur = find(wordsNow(), P.id);
    check(
      `${pname} #1 回填空 ex`,
      Array.isArray(cur.ex) && cur.ex.length === 1 &&
        cur.ex[0].de === remote.de && cur.ex[0].zh === remote.example_zh,
      "ex=" + JSON.stringify(cur.ex)
    );
    check(`${pname} #1 changed → saveWords 恰好一次`, savedNow() === 1, "saveWords=" + savedNow());
  }

  /* #2 保护手编例句：存量词已有例句 → 服务端也有例句 → 逐字不变，且整体无变更 */
  {
    const manual = [{ de: "我手编的例句", zh: "手编中文" }];
    const word = P.existing({
      ex: manual.map((x) => ({ ...x })),
      ipa: "keep-ipa",
      gender: pname === "B1" ? "das" : undefined,
      plural: pname === "B1" ? "die Häuser" : undefined,
    });
    setup({ scope: P.scope, words: [word], payload: P.wrap([P.remote()]) });
    await exec(P.fn);
    const cur = find(wordsNow(), P.id);
    check(
      `${pname} #2 保护手编例句（不覆盖非空 ex）`,
      JSON.stringify(cur.ex) === JSON.stringify(manual),
      "ex=" + JSON.stringify(cur.ex)
    );
    check(`${pname} #2 全字段非空 → changed=false（不写盘）`, savedNow() === 0, "saveWords=" + savedNow());
  }

  /* #3 保护非空 ipa：存量 ipa 非空 → 服务端 ipa 不得覆盖 */
  {
    const word = P.existing({
      ipa: "MY-IPA",
      ex: [{ de: "既有例句", zh: "既有中文" }],
      gender: pname === "B1" ? "das" : undefined,
      plural: pname === "B1" ? "die Häuser" : undefined,
    });
    setup({ scope: P.scope, words: [word], payload: P.wrap([P.remote()]) });
    await exec(P.fn);
    const cur = find(wordsNow(), P.id);
    check(
      `${pname} #3 保护非空 ipa（不覆盖）`,
      cur.ipa === "MY-IPA" && JSON.stringify(cur.ex) === JSON.stringify([{ de: "既有例句", zh: "既有中文" }]),
      "ipa=" + cur.ipa + " ex=" + JSON.stringify(cur.ex)
    );
  }

  /* #4 FSRS 不动：回填前后 S.cards / S.log / S.wrong 深度相等 */
  {
    const id = P.id;
    const cards = { [id]: { reps: 5, due: 100, ef: 2.5 } };
    const log = { "2026-01-01": { rv: 3, good: 2 } };
    const wrong = { [id]: { n: 2 } };
    const before = JSON.stringify({ cards, log, wrong });
    setup({ scope: P.scope, words: [P.existing()], cards, log, wrong, payload: P.wrap([P.remote()]) });
    await exec(P.fn);
    const after = JSON.stringify(progNow());
    const cur = find(wordsNow(), id);
    check(`${pname} #4 FSRS 进度深度不变`, after === before, "after=" + after);
    check(`${pname} #4 回填确有发生（ex 已填）`, Array.isArray(cur.ex) && cur.ex.length === 1, "ex=" + JSON.stringify(cur.ex));
  }

  /* #5 幂等：同一批数据连跑两次，第二次 changed=false 且词表逐字节不变 */
  {
    const remote = P.remote();
    setup({ scope: P.scope, words: [P.existing()], payload: P.wrap([remote]) });
    await exec(P.fn);
    const firstSaved = savedNow();
    const afterFirst = JSON.stringify(wordsNow());
    resetSaved();
    await exec(P.fn);
    const secondSaved = savedNow();
    const afterSecond = JSON.stringify(wordsNow());
    check(
      `${pname} #5 幂等（首跑写盘 / 二跑 no-op / 词表逐字节不变）`,
      firstSaved === 1 && secondSaved === 0 && afterFirst === afterSecond,
      `firstSaved=${firstSaved} secondSaved=${secondSaved} stable=${afterFirst === afterSecond}`
    );
  }

  /* #6 新词仍加入（回归）：不存在的 id 仍走 push 分支，tags/cefr 正确 */
  {
    const remote = P.newRemote();
    setup({ scope: P.scope, words: [], payload: P.wrap([remote]) });
    await exec(P.fn);
    const cur = find(wordsNow(), remote.id);
    check(
      `${pname} #6 新词仍加入（push 分支回归）`,
      !!cur && JSON.stringify(cur.tags) === JSON.stringify(P.tags) && cur.cefr === P.cefr,
      cur ? JSON.stringify({ tags: cur.tags, cefr: cur.cefr }) : "null"
    );
  }

  /* #7（仅 B1）补齐空 gender/plural：服务端有值 → 只补空 */
  if (pname === "B1") {
    const remote = P.remote();
    const word = P.existing({ gender: null, plural: "", ipa: remote.ipa, ex: [{ de: "x", zh: "y" }] });
    setup({ scope: P.scope, words: [word], payload: P.wrap([remote]) });
    await exec(P.fn);
    const cur = find(wordsNow(), P.id);
    check(
      `${pname} #7 补齐空 gender/plural`,
      cur.gender === remote.gender && cur.plural === remote.plural,
      "gender=" + cur.gender + " plural=" + cur.plural
    );
  }
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
    console.log("ALL PASS：A2/B1 富字段回填行为自检通过");
  }
}
