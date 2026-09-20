/**
 * wb_search_probe.mjs —— 全文检索视图（Suche）行为级自检探针
 * （feature/vocab-search · Task 5 · ADR-0014）
 *
 * 背景：static/js/search.js（Task 4 产物）把 /api/search 的四组结果渲染进
 * #search-group-{vocab,example,colloc,corpus}；展示字段一律先经 core.js 的 esc()
 * 或「先 esc 后包 <mark>」的 _highlight()（红线 11 / spec §3.4）。静态正则只能证明
 * 「源码里写着 esc(」，证明不了「含 <script> 的字段真的没有注入 innerHTML」。
 *
 * 本探针从**真实源文件**按括号配对整段切出实现（core.js 的 esc；search.js 的
 * _GROUP_ORDER / _s / el / _setStatus / _clearGroups / _renderEmpty / _highlight /
 * 四个条目渲染器 / _itemHtml / renderSearchGroups），丢进 node:vm 真跑；只提供
 * 最小 DOM 桩（记录 innerHTML 写值）与合成响应夹具。
 *
 * 硬约束（同 wb_rich_backfill_probe.mjs / wb_a1_bootstrap_probe.mjs）：探针里
 * **不得重抄一份被测实现**；一切被测逻辑均来自源文件切片。
 *
 * 扫描器说明：core.js 的 esc 含正则字面量 /"/g 与 /'/g，朴素括号配对会把正则里的
 * 引号误当字符串起始而切歪，故本探针的 matchBracket 增加了**正则字面量识别**
 * （依据前一个有意义字符判定 `/` 是除号还是正则起始）。
 *
 * 用法：
 *   node tools/wb_search_probe.mjs [--json] [--fixture <resp.json>]
 *   --json 时 stdout 仅输出单个 JSON 对象
 *     {"fail": <int>, "total": <int>, "cases": [{"name","ok","detail"}]}
 *   （供 pytest 行为级断言消费），人类可读输出静默、由断言侧判 fail == 0；
 *   人类模式每个场景打印 PASS/FAIL，末尾汇总并据 fail 设 process.exitCode。
 *   --fixture 可选：传入 {q,scope,total,groups} 形状的响应 JSON 覆盖内置合成夹具；
 *   缺值/不可读时打印用法并 exit 0。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SEARCH_JS = path.join(ROOT, "static", "js", "search.js");
const CORE_JS = path.join(ROOT, "static", "js", "core.js");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

/* ---------------------------------------------------------------------------
 * 0. 参数：--json / 可选 --fixture <path>
 * ------------------------------------------------------------------------ */
function usage(msg) {
  if (msg) log(`参数错误：${msg}`);
  log("用法：node tools/wb_search_probe.mjs [--json] [--fixture <resp.json>]");
  log("");
  log("  --json               仅输出单个 JSON 结果对象到 stdout（供 pytest 消费）");
  log("  --fixture <path>     可选：{q,scope,total,groups} 形状的响应 JSON，覆盖内置合成夹具");
  log("   （缺 --fixture 时使用内置合成响应；无参数 / 参数误用时打印本用法并 exit 0）");
}
function argValue(flag) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
}
const hasFixtureFlag = process.argv.includes("--fixture");
const FIXTURE = argValue("--fixture");
if (hasFixtureFlag && !FIXTURE) {
  usage("--fixture 需要跟一个文件路径");
  process.exit(0);
}
const extras = process.argv.slice(2).filter((a) => a !== "--json" && a !== "--fixture" && a !== FIXTURE);
if (extras.length) {
  usage(`未知参数：${extras.join(" ")}`);
  process.exit(0);
}

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整声明/函数体（跳过字符串、注释与正则字面量）
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

/** `/` 是否可能是正则起始：前一个有意义字符不是标识符字符、数字、`)`、`]`、引号。 */
function regexAllowed(prev) {
  if (prev == null) return true;
  return !/[A-Za-z0-9_$)\]"'`]/.test(prev);
}

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号（${src[openIdx]}）`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  let prev = src[openIdx]; // 上一个有意义字符：用于判定 `/` 是除号还是正则起始
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { prev = c; i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      i++;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === quote) break;
        i++;
      }
      i++;
      prev = quote;
      continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (c === "/" && regexAllowed(prev)) {
      // 正则字面量：消费到未转义的收尾 `/`（跳过字符类 [...]），再吃掉 flags。
      i++;
      let inClass = false;
      while (i < src.length) {
        const d = src[i];
        if (d === "\\") { i += 2; continue; }
        if (d === "[") { inClass = true; i++; continue; }
        if (d === "]") { inClass = false; i++; continue; }
        if (d === "/" && !inClass) break;
        if (d === "\n") break; // 未闭合（防御）：退化为普通字符继续
        i++;
      }
      i++;
      while (i < src.length && /[a-z]/.test(src[i])) i++;
      prev = "x";
      continue;
    }
    if (OPEN[c]) { stack.push(c); i++; prev = c; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i++;
      prev = c;
      continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  throw new Error(`matchBracket: 从 ${openIdx} 起找不到配对闭括号`);
}

/** 抽取 `[export] const|let|var NAME = <括号字面量>;`（值为对象/数组）。 */
function extractDecl(src, name) {
  const anchor = new RegExp(`^(?:export\\s+)?(?:const|let|var)\\s+${name}\\s*=`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`源文件里找不到声明 ${name}`);
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  const semi = src.indexOf(";", end);
  if (semi < 0 || semi > end + 8) throw new Error(`声明 ${name} 结尾找不到分号，切歪了`);
  return src.slice(m.index, semi + 1).replace(/^export\s+/, "");
}

/** 抽取 `[export] [async] function NAME(...) { ... }`。 */
function extractFn(src, name) {
  const anchor = new RegExp(`^(?:export\\s+)?(?:async\\s+)?function\\s+${name}\\s*\\(`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`源文件里找不到函数 ${name}`);
  const parenOpen = src.indexOf("(", m.index);
  const parenClose = matchBracket(src, parenOpen);
  const braceOpen = src.indexOf("{", parenClose);
  const braceClose = matchBracket(src, braceOpen);
  return src.slice(m.index, braceClose + 1).replace(/^export\s+/, "");
}

const searchSrc = fs.readFileSync(SEARCH_JS, "utf8");
const coreSrc = fs.readFileSync(CORE_JS, "utf8");

const PIECES = {
  esc: extractFn(coreSrc, "esc"), // ← 来自 core.js（真实转义实现）
  _GROUP_ORDER: extractDecl(searchSrc, "_GROUP_ORDER"),
  _s: extractDecl(searchSrc, "_s"),
  el: extractFn(searchSrc, "el"),
  _setStatus: extractFn(searchSrc, "_setStatus"),
  _clearGroups: extractFn(searchSrc, "_clearGroups"),
  _renderEmpty: extractFn(searchSrc, "_renderEmpty"),
  _highlight: extractFn(searchSrc, "_highlight"),
  _vocabHtml: extractFn(searchSrc, "_vocabHtml"),
  _exampleHtml: extractFn(searchSrc, "_exampleHtml"),
  _collocHtml: extractFn(searchSrc, "_collocHtml"),
  _corpusHtml: extractFn(searchSrc, "_corpusHtml"),
  _itemHtml: extractFn(searchSrc, "_itemHtml"),
  renderSearchGroups: extractFn(searchSrc, "renderSearchGroups"),
};
for (const [k, v] of Object.entries(PIECES)) {
  if (!v || v.length < 20) throw new Error(`切片 ${k} 长度异常（${v && v.length}），锚点可能失配`);
}

/* 防死测：切片必须是真实现，否则实现回退了探针照样绿。 */
if (!/replace\(\/&\/g/.test(PIECES.esc) || !/replace\(\/</.test(PIECES.esc)) {
  throw new Error("esc 切片里没有 &/< 替换，切歪或实现回退了");
}
if (!/esc\(text/.test(PIECES._highlight) || !/esc\(needle/.test(PIECES._highlight) || !/<mark>/.test(PIECES._highlight)) {
  throw new Error("_highlight 切片里没有 esc(text)/esc(needle)/<mark>，切歪或实现回退了");
}
if (PIECES._highlight.indexOf("esc(text") > PIECES._highlight.indexOf("<mark>")) {
  throw new Error("_highlight 里 <mark> 出现在 esc(text) 之前（顺序颠倒 = XSS 隐患）");
}
const KINDS = ["vocab", "example", "colloc", "corpus"];
for (const kind of KINDS) {
  if (!PIECES._GROUP_ORDER.includes(`"${kind}"`)) throw new Error(`_GROUP_ORDER 切片缺少分组 ${kind}`);
}
const RENDERERS = ["_vocabHtml", "_exampleHtml", "_collocHtml", "_corpusHtml"];
for (const fn of RENDERERS) {
  if (!PIECES[fn].includes("_highlight(")) throw new Error(`${fn} 切片未经过 _highlight() 转义路径`);
  // 四个条目渲染器必须都被 _itemHtml 分派（corpus 走 return 兜底，故按调用而非字面量判定）。
  if (!PIECES._itemHtml.includes(`${fn}(`)) throw new Error(`_itemHtml 切片未分派 ${fn}`);
}
if (!PIECES.renderSearchGroups.includes("_itemHtml(") || !PIECES.renderSearchGroups.includes("_renderEmpty(")) {
  throw new Error("renderSearchGroups 切片缺少 _itemHtml/_renderEmpty，切歪或实现回退了");
}
log(`[slice] ${Object.keys(PIECES).join(", ")}`);

/* ---------------------------------------------------------------------------
 * 2. 最小 DOM 桩：记录 innerHTML / textContent 写值与 classList 状态
 * ------------------------------------------------------------------------ */
const els = new Map();
function makeEl(id) {
  const el = {
    id,
    innerHTML: "",
    textContent: "",
    dataset: {},
    _classes: new Set(),
    classList: {
      add(c) { el._classes.add(c); },
      remove(c) { el._classes.delete(c); },
      toggle(c, on) {
        if (on === undefined) { el._classes.has(c) ? el._classes.delete(c) : el._classes.add(c); }
        else if (on) el._classes.add(c);
        else el._classes.delete(c);
      },
      contains(c) { return el._classes.has(c); },
    },
  };
  return el;
}
const domEl = (id) => {
  if (!els.has(id)) els.set(id, makeEl(id));
  return els.get(id);
};
const documentStub = {
  getElementById: (id) => domEl(id),
  createElement: (tag) => makeEl(tag),
  querySelectorAll: () => [],
  head: { appendChild() {} },
  documentElement: { appendChild() {} },
  body: { appendChild() {} },
};

/* ---------------------------------------------------------------------------
 * 3. 沙箱：注入被测源码切片 + DOM 桩，真跑
 * ------------------------------------------------------------------------ */
const vmConsole = { log() {}, warn() {}, error() {}, info() {} };
const ctx = vm.createContext({ console: JSON_MODE ? vmConsole : console, document: documentStub });
vm.runInContext(Object.values(PIECES).join("\n") + "\n", ctx, { filename: "search-slices.js" });

function runRender(resp) {
  ctx.__resp = resp;
  vm.runInContext("renderSearchGroups(__resp)", ctx);
}

/* ---------------------------------------------------------------------------
 * 4. 夹具：内置合成响应（四组各一条，字段刻意含 <script>/<>& 考验转义）
 * ------------------------------------------------------------------------ */
function syntheticResponse() {
  return {
    q: "haus",
    scope: "all",
    total: 4,
    // 每组截断前命中数（Task 6）；与各组实际条数相等 → 无「仅显示前」噪音。
    groups_total: { vocab: 1, example: 1, colloc: 1, corpus: 1 },
    // truncated 仅表示语料 hard cap 未扫完（真异常）；本夹具未触发。
    truncated: false,
    groups: {
      vocab: [
        {
          hw: "Haus<script>alert(1)</script>",
          lemma: "haus",
          pos: "n.",
          cefr: "A1",
          fields: { hw: "Haus", def_zh: "房子<x>" },
          payload: { cefr: "A1", pos: "n.", gender: "das", plural: "die Häuser" },
        },
      ],
      example: [
        {
          lemma: "haus",
          hw: "haus",
          fields: { example_de: "Das Haus ist groß.", example_zh: "房子很大<>" },
          payload: { ipa: "haʊs" },
        },
      ],
      colloc: [
        {
          lemma: "achten",
          hw: "achten",
          fields: { prep: "auf", case: "Akk", colloc_zh: "注意<>&", example_de: "Achte auf <das Haus>." },
          payload: { prep: "auf", case: "Akk" },
        },
      ],
      corpus: [
        {
          pos: "article",
          cefr: "",
          fields: { title: "Titel<s>", text: "..." },
          payload: {
            source: "article",
            ref_id: 7,
            title: "Artikel über das Haus<s>",
            level: "",
            snippet: "…das Haus…<script>x</script>",
          },
        },
      ],
    },
  };
}

let RESPONSE = syntheticResponse();
if (FIXTURE) {
  try {
    const parsed = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
    if (!parsed || typeof parsed !== "object" || !parsed.groups) {
      throw new Error("fixture 形状应为 {q,scope,total,groups}");
    }
    RESPONSE = parsed;
    log(`[fixture] ${FIXTURE}`);
  } catch (e) {
    usage(`无法读取/解析 --fixture：${FIXTURE}（${e && e.message ? e.message : e}）`);
    process.exit(0);
  }
}

/* ---------------------------------------------------------------------------
 * 5. 场景执行 + PASS/FAIL 汇总
 * ------------------------------------------------------------------------ */
const cases = [];
let failCount = 0;
function check(name, cond, detail) {
  const ok = !!cond;
  cases.push({ name, ok, detail: detail == null ? "" : String(detail) });
  if (!ok) failCount++;
  if (!JSON_MODE) console.log(ok ? `PASS  ${name}` : `FAIL  ${name}${detail ? "  —  " + detail : ""}`);
}

/* 场景 1：高亮转义安全（XSS）—— 含 <script> 的原文/查询串都不得留下可执行标签。 */
{
  const out = vm.runInContext("_highlight('<script>alert(1)</script>', '<script>')", ctx);
  check(
    "xss_highlight_escape",
    typeof out === "string" && !/<script/i.test(out) && out.includes("&lt;script&gt;") && out.includes("<mark>"),
    "out=" + out
  );
  check(
    "xss_highlight_escape: 命中处被 <mark> 包裹",
    typeof out === "string" && out.includes("<mark>&lt;script&gt;</mark>"),
    "out=" + out
  );
}

/* 场景 2：四组渲染 —— 合成响应四组各 1 条 → 四容器都被渲染、字段经 esc()。 */
{
  runRender(RESPONSE);
  const htmls = {};
  let allRendered = true;
  let allVisible = true;
  for (const kind of KINDS) {
    const body = domEl("search-group-" + kind);
    const sec = domEl("search-group-sec-" + kind);
    htmls[kind] = body.innerHTML;
    if (!htmls[kind] || !htmls[kind].includes("search-item")) allRendered = false;
    if (sec.classList.contains("hidden")) allVisible = false;
  }
  check(
    "four_groups_render",
    allRendered && allVisible,
    KINDS.map((k) => `${k}=${htmls[k].length}字符`).join(" ")
  );
  const rawScript = KINDS.filter((k) => /<script/i.test(htmls[k]));
  check(
    "four_groups_render: 字段经 esc() 转义",
    rawScript.length === 0,
    rawScript.length ? `未转义分组：${rawScript.join(",")}` : "四组均无未转义 <script>"
  );
}

/* 场景 3：空态 —— total=0/四组空 → 走空态分支（不抛错、不出结果行）。 */
{
  let threw = null;
  try {
    runRender({
      q: "zzzz",
      scope: "all",
      total: 0,
      truncated: false,
      groups: { vocab: [], example: [], colloc: [], corpus: [] },
    });
  } catch (e) {
    threw = e;
  }
  const anyRow = KINDS.some((k) => (domEl("search-group-" + k).innerHTML || "").includes("search-item"));
  const allHidden = KINDS.every((k) => domEl("search-group-sec-" + k).classList.contains("hidden"));
  const emptyNode = domEl("search-empty");
  check(
    "empty_state",
    !threw && !anyRow && allHidden && emptyNode.innerHTML.includes("未找到"),
    threw
      ? `抛错：${threw && threw.message}`
      : `anyRow=${anyRow} allHidden=${allHidden} empty=${JSON.stringify(emptyNode.innerHTML.slice(0, 60))}`
  );
}

/* 场景 4（Task 6）：截断语义拆分 —— limit 每组限量走**信息性**组尾提示「仅显示前 N 条」，
 * 语料 hard cap 未扫完走**警告**「⚠ 部分语料未扫描完」；旧「结果已截断」文案必须消失。 */
{
  const resp = syntheticResponse();
  resp.groups_total.vocab = 30; // 实际显示 1 条、截断前 30 条 → 信息性提示
  resp.truncated = true; // 语料 hard cap 未扫完 → 警告
  let threw = null;
  try {
    runRender(resp);
  } catch (e) {
    threw = e;
  }
  const vocabHtml = domEl("search-group-vocab").innerHTML;
  const exampleHtml = domEl("search-group-example").innerHTML;
  const statusHtml = domEl("search-status").innerHTML;
  check(
    "truncation_notices",
    !threw &&
      vocabHtml.includes("仅显示前 1 条") &&
      vocabHtml.includes("命中 30") &&
      statusHtml.includes("部分语料未扫描完") &&
      !statusHtml.includes("结果已截断"),
    threw
      ? `抛错：${threw && threw.message}`
      : `vocab尾=${JSON.stringify(vocabHtml.slice(-90))} status=${JSON.stringify(statusHtml)}`
  );
  // 未截断组（groups_total==条数）不得出现「仅显示前」噪音。
  check(
    "truncation_notices: 未截断组无噪音",
    !exampleHtml.includes("仅显示前"),
    "example尾=" + JSON.stringify(exampleHtml.slice(-60))
  );
}

/* ---------------------------------------------------------------------------
 * 6. 汇总
 * ------------------------------------------------------------------------ */
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ fail: failCount, total: cases.length, cases }));
} else {
  console.log("");
  if (failCount > 0) {
    console.log(`FAIL 汇总：${failCount} 个场景未通过`);
    process.exitCode = 1;
  } else {
    console.log(`ALL PASS：检索视图（高亮转义 / 四组渲染 / 空态，共 ${cases.length} 项断言）自检通过`);
  }
}
