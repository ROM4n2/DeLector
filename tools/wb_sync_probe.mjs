/**
 * wb_sync_probe.mjs —— wbsync PUT body 与 /api/wb/state 契约对齐的动态探针
 *
 * 事故回归（2026-09-02）：pushNow() 发的是 `JSON.stringify(snapshot())` 裸快照，
 * 而服务端契约是 `{"payload": {...}}`（WbStateReq.payload，见 server.py）。
 * 于是 payload 取不到 → wb_state 永远存 {} → GET 永远空 → 跨设备进度永远合并不进来，
 * 用户看到的症状就是「工作台看不到词汇进度」。更阴险的是：那次 Task3 的「存在性
 * 测试」只断言了 wbsync 字符串在不在，契约断裂它一条都抓不到 —— 静态断言死测本尊。
 *
 * 本探针把 workbench.html 里的 **真实 wbsync 源码** 按括号配对切片进 node:vm 真跑，
 * 桩掉 fetch 抓它实际发出的请求体，断言 body 顶层必须是单键 payload 且五存储键齐全。
 * 探针里没有任何一份重抄的实现 —— 实现回退（body 退回裸快照）本探针必红。
 *
 * 用法：
 *   node tools/wb_sync_probe.mjs            # 人类可读
 *   node tools/wb_sync_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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

const html = readSources(SRC_FILES);

/* ---- 括号配对切片：const wbsync = (() => { ... })(); -------------------- */
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

const SRC = sliceDecl(html, "wbsync");
/* 切片护栏：必须是真实现（切歪或实现丢了关键逻辑直接非零退出） */
for (const must of ["pushNow", "snapshot", "X-WB-Key", '"payload"', "function stable"]) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"，切歪了或实现被删`);
}

/* ---- 沙箱：S + 合并/渲染桩 + 抓包 fetch -------------------------------- */
const SEED_ID = "probe-sync-1";
const PRELUDE = `
var __reqs = [];          // 抓到的全部 fetch 请求
var S = { words: [{ id: "${SEED_ID}", hw: "Haus", up: 3 }],
          cards: { "${SEED_ID}": { reps: 2, last: 111 } },
          log: {}, wrong: {}, settings: { dailyNew: 20 } };
function applyMerge(d) {}
function renderReview() {}
function renderHeaderBadge() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { return 0; }
function clearTimeout(id) {}
function setInterval(fn, ms) { return 0; }
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: url, method: o.method || "GET",
                headers: o.headers || {}, body: o.body || null });
  var isKey = /\\/key$/.test(url);
  return Promise.resolve({
    ok: true,
    json: function () { return Promise.resolve(isKey ? { key: "k".repeat(32) } : {}); }
  });
}
`;

const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
vm.runInContext(PRELUDE + "\n" + SRC + "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });

/* boot() 里有两个 await（拿 key → pull → server 空 → pushNow 种子推送），空转几拍等 Promise 链落定 */
vm.runInContext("__wbsync.init()", ctx);
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));

const reqs = JSON.parse(vm.runInContext("JSON.stringify(__reqs)", ctx));
const puts = reqs.filter((r) => r.method === "PUT");
if (!puts.length) fail("没有发出任何 PUT —— init 流程没走到种子推送，复现不了契约");

const put = puts[0];
let body;
try { body = JSON.parse(put.body); }
catch (e) { fail(`PUT body 不是合法 JSON：${String(e)}`); }

const topKeys = Object.keys(body);
const payload = body.payload;
const payloadKeys = payload && typeof payload === "object" ? Object.keys(payload).sort() : [];
const REQUIRED = ["cards", "log", "settings", "words", "wrong"];
const hasSeed = Array.isArray(payload?.words) && payload.words.some((w) => w && w.id === SEED_ID);

const problems = [];
if (JSON.stringify(topKeys) !== JSON.stringify(["payload"]))
  problems.push(`PUT body 顶层必须是单键 payload，实际顶层键 = ${JSON.stringify(topKeys)}`);
for (const k of REQUIRED)
  if (!payloadKeys.includes(k)) problems.push(`payload 缺存储键 ${k}，实际 = ${JSON.stringify(payloadKeys)}`);
if (!hasSeed) problems.push(`payload.words 没带上沙箱种子词 ${SEED_ID}（snapshot 没引用真 S）`);
if (!put.headers["X-WB-Key"]) problems.push("PUT 必须带 X-WB-Key 请求头");

if (problems.length) fail(`wbsync PUT body 契约破坏：\n  - ${problems.join("\n  - ")}`);

const out = {
  ok: true,
  requests: reqs.map((r) => ({
    method: r.method,
    url: r.url,
    hasKeyHeader: Boolean(r.headers["X-WB-Key"]),
  })),
  put: {
    topKeys,
    payloadKeys,
    payloadWords: payload.words.length,
    payloadHasSeed: hasSeed,
  },
};

if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("抓到的请求：");
  for (const r of out.requests) console.log(`  ${r.method} ${r.url}`);
  console.log("PUT body 顶层键：", out.put.topKeys);
  console.log("payload 存储键：", out.put.payloadKeys);
  console.log("payload.words：", out.put.payloadWords, "个（含种子", SEED_ID, ":", out.put.payloadHasSeed, "）");
  console.log("✅ PASS: PUT body 带 payload 包装，与服务端 WbStateReq 契约一致");
}
