/**
 * wb_pair_push_probe.mjs —— wbsync 配对远端模式：push/pull 必须走绝对远端地址 + 配对 key
 *
 * Stage A（2026-09-03，docs/plans/2026-09-03-lan-silent-sync-stage-a.md Task 3）：
 * 手机 APP 的页面 origin 是它自己的 127.0.0.1:8000，配对后 wbsync 必须把同步打到
 * http://<配对 host>/api/wb/state（而非相对路径 /api/wb/state，那会打到自己本地 server）。
 * 本探针把 workbench.html 里**真实 wbsync 源码**切进 node:vm，桩 localStorage 预置配对记录
 * {host,key}，断言：
 *   1) 配对后不请求本机 /api/wb/state/key（不再需要）；
 *   2) boot 的 pull 走绝对远端地址 GET；
 *   3) pushNow 的 PUT 走绝对远端地址且带 X-WB-Key = 配对 key；
 *   4) 拉到的远端进度确实送进 applyMerge。
 * 实现若回退到相对 ENDPOINT（配对形同虚设 / 只读 / 打到自己），本探针必红。
 *
 * 用法：
 *   node tools/wb_pair_push_probe.mjs            # 人类可读
 *   node tools/wb_pair_push_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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

const HTML = path.join(ROOT, "static", "german", "workbench.html");
const html = fs.readFileSync(HTML, "utf8");

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

const anchor = /^const\s+wbsync\s*=/m.exec(html);
if (!anchor) fail("workbench.html 里找不到 const wbsync 声明");
let i = anchor.index + anchor[0].length;
while (i < html.length && !OPEN[html[i]]) i++;
const end = matchBracket(html, i);
const semi = html.indexOf(";", end);
const SRC = html.slice(anchor.index, (semi >= 0 && semi < end + 8 ? semi : end) + 1);
for (const must of ["pushNow", "snapshot", "X-WB-Key", "function stable", "function pull", "function boot",
                    "remoteEndpoint", "setPair", "loadPair"]) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"，切歪了`);
}

const PAIR = { host: "192.168.1.103", key: "a1b2c3d4e5f60718293a4b5c6d7e8f90", ts: 1 };
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
var K = { pair: "wb.pair.v1" };   // wbsync 切片外部的 K（slice 只含 IIFE，须补桩）
var localStorage = {
  getItem: function (k) { return k === "wb.pair.v1" ? ${JSON.stringify(JSON.stringify(PAIR))} : null; },
  setItem: function () {}, removeItem: function () {}
};
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: String(url), method: o.method || "GET", headers: o.headers || {}, body: o.body || null });
  if (String(url).indexOf("/api/wb/state") >= 0 && (!o.method || o.method === "GET")) {
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
vm.runInContext("__wbsync.pushNow()", ctx);
await new Promise((r) => process.nextTick(r));

const reqs = JSON.parse(vm.runInContext("JSON.stringify(__reqs)", ctx));
const merged = vm.runInContext("__merged", ctx);
const absState = "http://" + PAIR.host + "/api/wb/state";

const askedLocalKey = reqs.some((r) => /\/api\/wb\/state\/key$/.test(r.url));
if (askedLocalKey) fail("配对后仍在请求本机 /api/wb/state/key —— 配对密钥没有生效");

const gotRemotePull = reqs.some((r) => r.method === "GET" && r.url === absState);
if (!gotRemotePull) fail("配对后 boot 没有向远端绝对地址 GET /api/wb/state 拉镜像：" +
  JSON.stringify(reqs.map((r) => r.method + " " + r.url)));

const put = reqs.find((r) => r.method === "PUT" && r.url === absState);
if (!put) fail("配对后 pushNow 没有向远端绝对地址 PUT（打到了相对地址或没推送）：" +
  JSON.stringify(reqs.map((r) => r.method + " " + r.url)));
if (put.headers["X-WB-Key"] !== PAIR.key) {
  fail("PUT 的 X-WB-Key 不等于配对 key：" + String(put.headers["X-WB-Key"]));
}
if (!merged || !merged.cards || !merged.cards.c1) {
  fail("远端拉到的进度没有送进 applyMerge：" + JSON.stringify(merged));
}

const out = {
  ok: true,
  askedLocalKey,
  gotRemotePull,
  putUrl: put.url,
  putHasPairKey: put.headers["X-WB-Key"] === PAIR.key,
  mergedCardIds: Object.keys(merged.cards || {}),
  requests: reqs.map((r) => ({ method: r.method, url: r.url })),
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("wbsync 发出的请求：");
  for (const r of out.requests) console.log(`  ${r.method} ${r.url}`);
  console.log("PUT 配对 key 匹配：", out.putHasPairKey);
  console.log("applyMerge 收到的卡片：", out.mergedCardIds);
  console.log("✅ PASS: 配对后 wbsync 对远端绝对地址静默双向同步（GET 拉取 + PUT 带配对 key 推送）");
}
