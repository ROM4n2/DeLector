/**
 * wb_pair_persist_probe.mjs —— 持久配对凭证：set 持久化 / revoke 撤销后旧 key 失效
 *
 * Stage B M2（docs/plans/2026-09-03-lan-silent-sync-stage-b.md Task 2）：
 * 配对凭证要长期有效，前提是「随时能一键作废」。本探针把 workbench.html 里**真实的
 * wbsync 源码**切进 node:vm，桩 localStorage / fetch，断言：
 *   1) pair.set(host,key) 真的把 {host,key} 落进 localStorage（不只是内存里有效）；
 *   2) pair.revoke() 会 POST /api/wb/state/key 让服务端重新生成密钥；
 *   3) revoke 后本地配对状态被清除（pairInfo() 为 null 且 removeItem 被调用）；
 *   4) revoke 后本机 pushNow 用**新 key** 推送 —— 主机不能被自己作废的 key 卡死。
 *
 * 任何一条被回退（revoke 不请求服务端 / 不落盘 / 不换 key），本探针必红。
 *
 * 用法：
 *   node tools/wb_pair_persist_probe.mjs            # 人类可读
 *   node tools/wb_pair_persist_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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
                    "remoteEndpoint", "setPair", "loadPair", "clearPair", "revokePair"]) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"（函数没写或切片切歪了）`);
}

const PAIR = { host: "192.168.1.103", key: "a1b2c3d4e5f60718293a4b5c6d7e8f90", ts: 1 };
const NEW_KEY = "fffedcba9876543210fffedcba9876543";
const MIRROR = {
  words: [{ id: "w1", hw: "Haus", up: 3 }],
  cards: { c1: { reps: 5, last: 999 } },
  log: {}, wrong: {}, settings: { dailyNew: 20 },
};

const PRELUDE = `
var __reqs = [];
var __ops = [];                       // localStorage 写/删操作流水
var __merged = null;
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: { dailyNew: 20 } };
function applyMerge(d) { __merged = d; }
function renderReview() {}
function renderHeaderBadge() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { return 0; }
function clearTimeout(id) {}
function setInterval(fn, ms) { return 0; }
var K = { pair: "wb.pair.v1" };
var __store = {};
var localStorage = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(__store, k) ? __store[k] : null; },
  setItem: function (k, v) { __ops.push(["set", k, String(v)]); __store[k] = String(v); },
  removeItem: function (k) { __ops.push(["remove", k]); delete __store[k]; }
};
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: String(url), method: o.method || "GET", headers: o.headers || {}, body: o.body || null });
  var u = String(url);
  if (/\\/api\\/wb\\/state\\/key$/.test(u) && o.method === "POST") {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ key: ${JSON.stringify(NEW_KEY)} }); } });
  }
  if (/\\/api\\/wb\\/state\\/key$/.test(u)) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ key: ${JSON.stringify(PAIR.key)} }); } });
  }
  if (/\\/api\\/wb\\/state$/.test(u) && (!o.method || o.method === "GET")) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve(${JSON.stringify(MIRROR)}); } });
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
}
`;

const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
vm.runInContext(PRELUDE + "\n" + SRC + "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });

const read = (expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));

// ── 1) set 必须落盘（不只是内存里有效） ──────────────────────────────────────
vm.runInContext(`__wbsync.pair.set(${JSON.stringify(PAIR.host)}, ${JSON.stringify(PAIR.key)})`, ctx);
const setOps = read("__ops").filter((o) => o[0] === "set" && o[1] === "wb.pair.v1");
if (!setOps.length) fail("pair.set 没有把配写进 localStorage —— 刷新页面配对就丢了，持久凭证无从谈起");
let persisted = null;
try { persisted = JSON.parse(setOps[setOps.length - 1][2]); } catch (e) { persisted = null; }
if (!persisted || persisted.host !== PAIR.host || persisted.key !== PAIR.key) {
  fail("落盘的配对内容不含 host/key：" + JSON.stringify(persisted));
}

// ── 2) 先 init（boot 会读到刚落盘的配对），再撤销 ──────────────────────────
vm.runInContext("__wbsync.init()", ctx);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));
const infoBefore = read("__wbsync.pairInfo()");
if (!infoBefore || infoBefore.host !== PAIR.host) {
  fail("boot 没有从 localStorage 恢复出持久配对：" + JSON.stringify(infoBefore));
}

const revoked = await vm.runInContext("__wbsync.pair.revoke()", ctx);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));

const reqs = read("__reqs");
const ops = read("__ops");

// ── 3) revoke 必须真的请求服务端重新生成密钥 ────────────────────────────────
const revokePost = reqs.some((r) => r.method === "POST" && /\/api\/wb\/state\/key$/.test(r.url));
if (!revokePost) fail("pair.revoke 没有 POST /api/wb/state/key —— 服务端不重新生成，旧 key 永不过期");

// ── 4) revoke 后本地配对状态清除 ────────────────────────────────────────────
const infoAfter = read("__wbsync.pairInfo()");
if (infoAfter !== null) fail("revoke 后 pairInfo() 仍返回配对信息：" + JSON.stringify(infoAfter));
const removed = ops.some((o) => o[0] === "remove" && o[1] === "wb.pair.v1");
if (!removed) fail("revoke 没有清掉 localStorage 里的 wb.pair.v1 —— 页面刷新又会拿旧凭证");

// ── 5) 撤销后本机仍要能用新 key 推送（不能被自己作废的 key 卡死） ──────────
if (revoked !== NEW_KEY) fail("revoke 没有返回/采用服务端下发的新 key：" + String(revoked));
vm.runInContext("__wbsync.pushNow()", ctx);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));
const reqs2 = read("__reqs");
const put = reqs2.filter((r) => r.method === "PUT" && /\/api\/wb\/state$/.test(r.url)).pop();
if (!put) fail("撤销后 pushNow 没有推送：" + JSON.stringify(reqs2.map((r) => r.method + " " + r.url)));
if (put.headers["X-WB-Key"] !== NEW_KEY) {
  fail("撤销后推送仍用旧 key（" + String(put.headers["X-WB-Key"]) + "）—— 自己把自己作废了");
}

const out = {
  ok: true,
  persistedPair: persisted,
  restoredPairOnBoot: infoBefore,
  revokePosted: revokePost,
  pairClearedAfterRevoke: infoAfter === null && removed,
  pushedWithNewKey: put.headers["X-WB-Key"] === NEW_KEY,
  requests: reqs2.map((r) => ({ method: r.method, url: r.url })),
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("落盘配对：", JSON.stringify(out.persistedPair));
  console.log("boot 恢复配对：", JSON.stringify(out.restoredPairOnBoot));
  console.log("revoke 请求服务端重生成：", out.revokePosted);
  console.log("revoke 后清除本地配对：", out.pairClearedAfterRevoke);
  console.log("wbsync 发出的请求：");
  for (const r of out.requests) console.log(`  ${r.method} ${r.url}`);
  console.log("✅ PASS: 配对凭证可持久保存，且能被一键撤销（旧 key 失效、本机换用新 key 继续同步）");
}
