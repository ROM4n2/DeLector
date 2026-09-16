/**
 * wb_tags_probe.mjs —— 词条「等级标签 a1 补齐 + reader 谓词收窄」行为级自检探针
 *
 * 背景（用户需求）：词条 tags 里 A2/B1 有等级标签（a2/b1），但 A1 只有 core（核心语义）
 * 没有 a1（等级语义），于是「全部标签」下拉筛不出「A1 全量」。
 * 约定：a1/a2/b1 = 等级标签；core = 核心词标记；reader = 精读生词来源。
 *
 * 本探针把 static/german/workbench.html 里的 **真实源码**（CORE_WORD_SEED_IDS /
 * CORE_CUSTOM_WORDS 常量、CEFR_BY_PREFIX + cefrFromId + cefrOf、SCOPE_PREDICATES +
 * isInScope、backfillCoreWords）按括号配对整段切出来，丢进 node:vm 真跑，
 * 用一份「存量老形状」词表验证四类词的行为。不做整文件模糊匹配。
 *
 * 硬约束（同 wb_queue_probe.mjs / wb_merge_probe.mjs）：探针里**不得重抄一份被测实现**。
 * 一切被测逻辑均来自 workbench.html 切片；本文件只提供 S / save* 等桩与夹具。
 *
 * 用法：node tools/wb_tags_probe.mjs [--json]
 *   --json 时 stdout 只有一个 JSON 对象，日志走 stderr，退出码 0；断言失败退出码 1。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const HTML = path.join(ROOT, "static", "german", "workbench.html");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

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

function extractFn(src, name) {
  const anchor = new RegExp(`^function\\s+${name}\\s*\\(`, "m");
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
  CORE_WORD_SEED_IDS: extractDecl(html, "CORE_WORD_SEED_IDS"),
  CORE_CUSTOM_WORDS: extractDecl(html, "CORE_CUSTOM_WORDS"),
  CEFR_BY_PREFIX: extractDecl(html, "CEFR_BY_PREFIX"),
  cefrFromId: extractFn(html, "cefrFromId"),
  cefrOf: extractFn(html, "cefrOf"),
  OTHER_LEVEL_SCOPES: extractDecl(html, "OTHER_LEVEL_SCOPES"),
  SCOPE_PREDICATES: extractDecl(html, "SCOPE_PREDICATES"),
  isInScope: extractFn(html, "isInScope"),
  backfillCoreWords: extractFn(html, "backfillCoreWords"),
};
for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 25) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
  log(`[slice] ${k}: ${v.length} 字节`);
}
/* 防死测：切片必须是真实现 */
if (!/cefrOf/.test(PIECES.backfillCoreWords) || !/isInScope/.test(PIECES.backfillCoreWords)) {
  throw new Error("backfillCoreWords 切片里没有 cefrOf / isInScope 的 a1 补齐逻辑，切歪了");
}
if (!/includes\("core"\)/.test(PIECES.SCOPE_PREDICATES)) {
  throw new Error("SCOPE_PREDICATES 切片里没有 core 谓词，切歪了");
}

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只提供被测代码依赖的最小桩
 * ------------------------------------------------------------------------ */
const PRELUDE = `
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: {} };
function saveWords() {}
function saveCards() {}
function saveLog() {}
function saveWrong() {}
function saveSettings() {}
`;

const ctx = vm.createContext({ console });
vm.runInContext(PRELUDE + "\n" + Object.values(PIECES).join("\n") + "\n", ctx, {
  filename: "workbench-tag-slices.js",
});

const run = (stmt) => vm.runInContext(stmt, ctx);
const sb = (expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));

/* 夹具：用真实常量构造「存量老形状」词表 + 各类型探针词。
 * 老形状 = A1 种子词只有 core 标签（无 a1，模拟改造前落盘的数据）。 */
const FIXTURE = `
function __buildFixture() {
  var coreId = Array.from(CORE_WORD_SEED_IDS)[0];   // 真实 A1 核心种子 id
  var coreSet = CORE_WORD_SEED_IDS;
  var custom = CORE_CUSTOM_WORDS.map(function (w) {
    return Object.assign({}, w);                     // 真实 22 条 core-* 补缺词（tags:["core"], custom:true）
  });
  var words = [
    { id: coreId, hw: "核心词", tags: ["core"] },          // A1 核心词（老形状：只有 core）
    { id: "a1-9001", hw: "普通A1词", tags: [] },           // A1 非核心（老形状：空 tags）
    { id: "a2-haus", hw: "das Haus", tags: ["a2"], cefr: "A2" },   // A2：不得被补 a1
    { id: "b1-essen", hw: "das Essen", tags: ["b1"], cefr: "B1" }, // B1：不得被补 a1
    { id: "card-Testwort", hw: "Testwort", tags: ["reader"], custom: true, cefr: null } // 精读生词
  ].concat(custom);
  return { words: words, coreId: coreId, customCount: custom.length, coreSetSize: coreSet.size };
}
`;

vm.runInContext(FIXTURE, ctx);

/* ---------------------------------------------------------------------------
 * 3. 场景：跑真实 backfillCoreWords，检查四类词行为
 * ------------------------------------------------------------------------ */
const meta = sb(`__buildFixture()`);
run(`S.words = __buildFixture().words;`);

const tagOf = (id) => sb(`(S.words.find(function (w) { return w.id === ${JSON.stringify(id)}; }) || {}).tags || []`);
const isReader = (id) => sb(`isInScope(S.words.find(function (w) { return w.id === ${JSON.stringify(id)}; }) || {}, "reader")`);
const isCore = (id) => sb(`isInScope(S.words.find(function (w) { return w.id === ${JSON.stringify(id)}; }) || {}, "core")`);
const inAll = (id) => sb(`isInScope(S.words.find(function (w) { return w.id === ${JSON.stringify(id)}; }) || {}, "all")`);
const cefrOfId = (id) => sb(`cefrOf(S.words.find(function (w) { return w.id === ${JSON.stringify(id)}; }) || {})`);

const coreId = meta.coreId;
const customIds = new Array(meta.customCount).fill(0).map((_, i) => `core-${String(i + 1).padStart(3, "0")}`);

/* 首跑：真实 backfillCoreWords —— 捕获返回值，此刻词表从「老形状」被幂等补齐。 */
const changedFirst = sb(`(function () { return backfillCoreWords(); })()`);

/* 快照四类词结果 */
const result = {
  fixture: { coreId: coreId, customCount: meta.customCount, totalWords: sb(`S.words.length`) },
  a1NonCore: { id: "a1-9001", tags: tagOf("a1-9001"), cefr: cefrOfId("a1-9001") },
  a1Core: { id: coreId, tags: tagOf(coreId), cefr: cefrOfId(coreId) },
  coreCustom: { ids: customIds, allHaveA1: customIds.every((id) => tagOf(id).includes("a1")),
                allHaveCore: customIds.every((id) => tagOf(id).includes("core")),
                anyReader: customIds.filter((id) => isReader(id)).length },
  readerWord: { id: "card-Testwort", tags: tagOf("card-Testwort"), isReader: isReader("card-Testwort") },
  a2Word: { id: "a2-haus", tags: tagOf("a2-haus"), hasA1: tagOf("a2-haus").includes("a1") },
  b1Word: { id: "b1-essen", tags: tagOf("b1-essen"), hasA1: tagOf("b1-essen").includes("a1") },
  readerScopeHasCoreCustom: customIds.filter((id) => isReader(id)).length,
  allScopeHasCoreCustom: customIds.every((id) => inAll(id)),
  allScopeExcludesReader: !inAll("card-Testwort"),
  coreScopeOnCoreCustom: isCore("core-001"),
  changedFirst: changedFirst,
  /* 幂等：再跑一次返回 false，且词表逐字节不变 */
  idempotent: (function () {
    const before = sb(`S.words`);
    const changed = sb(`(function () { return backfillCoreWords(); })()`);
    const after = sb(`S.words`);
    return { changedSecond: changed, stable: JSON.stringify(before) === JSON.stringify(after) };
  })(),
};

/* ---------------------------------------------------------------------------
 * 4. 断言
 * ------------------------------------------------------------------------ */
const problems = [];
const must = (cond, msg) => { if (!cond) problems.push(msg); };

/* 类别 1：A1 非核心 → 含 a1、不含 core */
must(result.a1NonCore.tags.includes("a1"), "A1 非核心词补 a1 失败：tags=" + JSON.stringify(result.a1NonCore.tags));
must(!result.a1NonCore.tags.includes("core"), "A1 非核心词不应含 core：tags=" + JSON.stringify(result.a1NonCore.tags));
/* 类别 2：A1 核心 → 含 a1 且含 core */
must(result.a1Core.tags.includes("a1") && result.a1Core.tags.includes("core"),
  "A1 核心词必须同时含 a1 与 core：tags=" + JSON.stringify(result.a1Core.tags));
/* 类别 3：22 条 custom → 含 a1 与 core，且不再命中 reader */
must(result.coreCustom.allHaveA1, "存在未补 a1 的 core-* 补缺词");
must(result.coreCustom.allHaveCore, "存在未含 core 的 core-* 补缺词");
must(result.coreCustom.anyReader === 0, "有 " + result.coreCustom.anyReader + " 条 core-* 补缺词仍被 reader 谓词命中（收窄失败）");
/* 类别 4：精读生词 → 仍命中 reader，且不被补 a1 */
must(result.readerWord.isReader, "精读生词 card-* 未命中 reader 谓词");
must(!result.readerWord.tags.includes("a1"), "精读生词不应被补 a1：tags=" + JSON.stringify(result.readerWord.tags));
/* 旁证：A2/B1 不被补 a1；all 档不含精读生词；core 档含 core-* */
must(!result.a2Word.hasA1, "A2 词不应被补 a1");
must(!result.b1Word.hasA1, "B1 词不应被补 a1");
must(result.allScopeExcludesReader, "all 档（A1 全量）不应混入精读生词");
must(result.allScopeHasCoreCustom, "all 档应包含 core-* 补缺词");
must(result.coreScopeOnCoreCustom, "core 档应包含 core-* 补缺词");
/* 幂等与 changed 契约 */
must(result.changedFirst === true, "首次 backfill 应返回 true（确有变更）");
must(result.idempotent.changedSecond === false, "二次 backfill 应返回 false（幂等）");
must(result.idempotent.stable, "二次 backfill 后词表发生了变化（非幂等）");

const out = { ok: problems.length === 0, probes: result, problems };

if (problems.length) {
  process.stderr.write("词条等级标签 / reader 谓词行为自检失败：\n  - " + problems.join("\n  - ") + "\n");
  if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
  process.exit(1);
}

if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  log("✅ PASS: A1 等级标签补齐 + reader 谓词收窄行为自检通过");
  log("  A1 非核心 tags:", result.a1NonCore.tags.join(","));
  log("  A1 核心 tags:", result.a1Core.tags.join(","));
  log("  core-* 补缺词:", result.fixture.customCount, "条，含 a1&core，reader 命中", result.coreCustom.anyReader, "条");
  log("  精读生词 reader 命中:", result.readerWord.isReader);
}
