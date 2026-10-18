/**
 * wb_phone_pull_probe.mjs —— 手机（远端 IP）经 wbsync 服务端镜像能否自动拉到进度
 *
 * 2026-09-03 事故回归：wbsync.boot() 必须先取到 GET /api/wb/state/key，而该端点被
 * _require_localhost 限制；手机是远端 IP → 永远 403 → 旧实现里 _enabled=false，
 * 连 pull()（GET /api/wb/state，服务端本就开放给局域网、无需 key）都不触发 →
 * 手机永远看不到背词进度。这与 server.py:1419「手机/平板拉取不需 key」矛盾。
 *
 * 本探针把 workbench.html 里的 **真实 wbsync 源码** 按括号配对切片进 node:vm 真跑，
 * 桩 fetch 模拟「手机」（/key 返回 403），断言其仍会 GET 镜像且 applyMerge 收到 cards
 * 进度。探针里没有任何重抄实现；实现回退（pull 又被 key 卡住）本探针必红。
 *
 * 用法：
 *   node tools/wb_phone_pull_probe.mjs            # 人类可读
 *   node tools/wb_phone_pull_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * 契约破坏时退出码 1、详情走 stderr。
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
for (const must of ["pushNow", "snapshot", "X-WB-Key", "function stable", "function pull", "function boot"]) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"，切歪了`);
}

/* 桌面推上去的全量镜像，带背词进度（cards.c1 已复习 reps:5） */
const MIRROR = {
  words: [{ id: "w1", hw: "Haus", up: 3 }],
  cards: { c1: { reps: 5, last: 999 } },
  log: { "2026-09-03": { rv: 3 } },
  wrong: {},
  settings: { dailyNew: 20 },
};

const PRELUDE = `
var __reqs = [];
var __merged = null;
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: { dailyNew: 20 } };
function applyMerge(d) { __merged = d; }           // 记录是否被调用、收到什么
function renderReview() {}
function renderHeaderBadge() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { return 0; }
function clearTimeout(id) {}
function setInterval(fn, ms) { return 0; }
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: url, method: o.method || "GET", headers: o.headers || {}, body: o.body || null });
  if (/\\/key$/.test(url)) {                          // 手机是远端 IP → key 端点 403
    return Promise.resolve({ ok: false, status: 403, json: function () { return Promise.resolve({}); } });
  }
  if (/\\/api\\/wb\\/state$/.test(url) && (!o.method || o.method === "GET")) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve(${JSON.stringify(MIRROR)}); } });
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
}
`;

const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
vm.runInContext(PRELUDE + "\n" + SRC + "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });
vm.runInContext("__wbsync.init()", ctx);
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));

const reqs = JSON.parse(vm.runInContext("JSON.stringify(__reqs)", ctx));
const merged = vm.runInContext("__merged", ctx);
const gotPull = reqs.some((r) => r.method === "GET" && /\/api\/wb\/state$/.test(r.url));
if (!gotPull) fail("手机（key=403）没有去拉 /api/wb/state 镜像 → 进度永远进不来（bug 复现）");
if (!merged || !merged.cards || !merged.cards.c1) fail("虽然拉了镜像，但 applyMerge 没收到 cards 进度：" + JSON.stringify(merged));

const out = {
  ok: true,
  gotPull,
  requests: reqs.map((r) => ({ method: r.method, url: r.url, hasKeyHeader: Boolean(r.headers["X-WB-Key"]) })),
  mergedCardIds: Object.keys(merged.cards || {}),
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("手机发出的请求：");
  for (const r of out.requests) console.log(`  ${r.method} ${r.url}`);
  console.log("applyMerge 收到的卡片进度 id：", out.mergedCardIds);
  console.log("✅ PASS: 手机虽拿不到 key，仍成功拉取并合并了服务端镜像进度");
}
