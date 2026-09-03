/**
 * wb_rtc_reconnect_probe.mjs —— 自动重连（去抖）与 HTTP 兜底降级
 *
 * Stage B M4（docs/plans/2026-09-03-lan-silent-sync-stage-b.md Task 5）：
 * WebRTC 断线要能自动重建，但不能无限重试；WebRTC 不可用（企业网禁 UDP/ICE、
 * 老浏览器）时必须退回 Stage A 的 HTTP 轮询，保证「至少可达」。
 *
 * 本探针跑两个 vm 场景：
 *   A. 有 RTCPeerConnection：模拟 connectionState 变 failed，断言会去抖重建；
 *      连续失败到上限后进入降级，且**不再**继续建连（不空转打服务端）。
 *   B. 无 RTCPeerConnection：autoSync() 返回 false、degraded() 为真，
 *      且 Stage A 的 HTTP 拉取照常发生（boot 的 pull 打到配对远端）。
 *
 * 实现若回退（断了不重连 / 无限重试 / 无 WebRTC 时连 HTTP 也停摆），本探针必红。
 *
 * 用法：
 *   node tools/wb_rtc_reconnect_probe.mjs            # 人类可读
 *   node tools/wb_rtc_reconnect_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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
for (const must of ["pushNow", "snapshot", "function pull", "function boot", "revokePair",
                    "rtcConnect", "rtcScheduleRetry", "autoSync", "rtcDegraded"]) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"（函数没写或切片切歪了）`);
}

const PAIR = { host: "192.168.1.103", key: "a1b2c3d4e5f60718293a4b5c6d7e8f90", ts: 1 };

const BASE_PRELUDE = `
var __reqs = [];
var __timers = [];
var __merged = null;
var S = { words: [], cards: {}, log: {}, wrong: {}, settings: {} };
function applyMerge(d, opts) { __merged = d; }
function renderReview() {}
function renderHeaderBadge() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { __timers.push(fn); return 0; }   // 探针手动推进，不去抖真实时间
function clearTimeout(id) {}
function setInterval(fn, ms) { return 0; }
function clearInterval(id) {}
var K = { pair: "wb.pair.v1" };
var __store = { "wb.pair.v1": ${JSON.stringify(JSON.stringify(PAIR))} };
var localStorage = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(__store, k) ? __store[k] : null; },
  setItem: function (k, v) { __store[k] = String(v); },
  removeItem: function (k) { delete __store[k]; }
};
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: String(url), method: o.method || "GET", headers: o.headers || {} });
  var u = String(url);
  if (/rtc\\/signal$/.test(u) && o.method === "POST") {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
  }
  if (/rtc\\/signal\\?/.test(u)) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ messages: [], now: 1 }); } });
  }
  if (/\\/api\\/wb\\/state$/.test(u) && (!o.method || o.method === "GET")) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ words: [], cards: {} }); } });
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
}
`;

const RTC_STUB = `
var __pcs = [];
function RTCPeerConnection(cfg) {
  var self = this;
  __pcs.push(this);
  this.connectionState = "new";
  this.localDescription = null;
  this.remoteDescription = null;
  this.onicecandidate = null;
  this.onconnectionstatechange = null;
  this.createDataChannel = function (name) {
    return { send: function () {}, close: function () {}, onopen: null, onmessage: null };
  };
  this.createOffer = function () { return Promise.resolve({ type: "offer", sdp: "v=0 mock" }); };
  this.createAnswer = function () { return Promise.resolve({ type: "answer", sdp: "v=0 mock" }); };
  this.setLocalDescription = function (d) { self.localDescription = d; return Promise.resolve(); };
  this.setRemoteDescription = function (d) { self.remoteDescription = d; return Promise.resolve(); };
  this.addIceCandidate = function (c) { return Promise.resolve(); };
  this.close = function () { self.connectionState = "closed"; };
}
`;

function makeCtx(withRTC) {
  const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
  vm.runInContext(BASE_PRELUDE + (withRTC ? RTC_STUB : "") + "\n" + SRC +
                  "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });
  return ctx;
}
const read = (ctx, expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));
async function flushTimers(ctx) {
  await vm.runInContext(`(async function () { var f; while ((f = __timers.shift())) { await f(); } })();`, ctx);
  for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));
}
async function simulateFailure(ctx) {
  vm.runInContext(`(function () {
    if (!__pcs.length) return;
    var pc = __pcs[__pcs.length - 1];
    pc.connectionState = "failed";
    if (pc.onconnectionstatechange) pc.onconnectionstatechange();
  })()`, ctx);
  for (let k = 0; k < 2; k++) await new Promise((r) => process.nextTick(r));
  await flushTimers(ctx);
}

// ══ 场景 A：有 WebRTC —— 断线要重建，到上限要降级且不再空转 ══════════════════
const ctxA = makeCtx(true);
vm.runInContext("__wbsync.init()", ctxA);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));

const started = await vm.runInContext("__wbsync.autoSync()", ctxA);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));
const pcsAfterStart = read(ctxA, "__pcs.length");
if (started !== true) fail("有 WebRTC 且有配对密钥时 autoSync() 应返回 true，实际 " + String(started));
if (pcsAfterStart !== 1) fail("autoSync() 没有建起 RTCPeerConnection（__pcs.length=" + pcsAfterStart + "）");

await simulateFailure(ctxA);
const pcsAfter1 = read(ctxA, "__pcs.length");
if (pcsAfter1 <= pcsAfterStart) {
  fail("连接变 failed 后没有自动重建（__pcs 仍 " + pcsAfter1 + " 个）—— 断线即永久失联");
}

// 连续失败到上限：应进入降级，且此后不再继续建连（不无限重试打服务端）
for (let n = 0; n < 8; n++) await simulateFailure(ctxA);
const degraded = read(ctxA, "__wbsync.rtc.degraded()");
if (degraded !== true) fail("连续失败到上限后没有进入降级（degraded()=" + String(degraded) + "）—— 会无限重试");
const pcsAtDegrade = read(ctxA, "__pcs.length");
await simulateFailure(ctxA);
const pcsAfterDegrade = read(ctxA, "__pcs.length");
if (pcsAfterDegrade !== pcsAtDegrade) {
  fail(`降级后仍在建连（${pcsAtDegrade} → ${pcsAfterDegrade}）—— 降级就该停下，交给 HTTP 兜底`);
}

// ══ 场景 B：无 WebRTC —— 必须降级，且 HTTP 轮询照常 ══════════════════════════
const ctxB = makeCtx(false);
vm.runInContext("__wbsync.init()", ctxB);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));

const startedB = await vm.runInContext("__wbsync.autoSync()", ctxB);
const degradedB = read(ctxB, "__wbsync.rtc.degraded()");
if (startedB !== false) fail("没有 WebRTC 时 autoSync() 应返回 false，实际 " + String(startedB));
if (degradedB !== true) fail("没有 WebRTC 时应直接降级到 HTTP 兜底（degraded()=" + String(degradedB) + "）");

const reqsB = read(ctxB, "__reqs");
const absState = "http://" + PAIR.host + "/api/wb/state";
const httpPulled = reqsB.some((r) => r.method === "GET" && r.url === absState);
if (!httpPulled) fail("降级后 Stage A 的 HTTP 拉取没有发生（" + JSON.stringify(reqsB.map((r) => r.method + " " + r.url)) +
  "）—— 没有 WebRTC 就彻底失联了");

const out = {
  ok: true,
  reconnectedAfterFailure: pcsAfter1 > pcsAfterStart,
  pcCountAfterStart: pcsAfterStart,
  pcCountAfterFailures: pcsAfter1,
  degradedAfterMaxFails: degraded,
  noReconnectAfterDegrade: pcsAfterDegrade === pcsAtDegrade,
  degradedWithoutWebRTC: degradedB,
  httpFallbackAlive: httpPulled,
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("场景A（有 WebRTC）：建连", out.pcCountAfterStart, "→ 断线重建至", out.pcCountAfterFailures,
    "→ 降级:", out.degradedAfterMaxFails, "| 降级后停手:", out.noReconnectAfterDegrade);
  console.log("场景B（无 WebRTC）：降级", out.degradedWithoutWebRTC, "| HTTP 兜底存活:", out.httpFallbackAlive);
  console.log("✅ PASS: 断线自动重建、失败到上限降级，且与 Stage A HTTP 轮询共存兜底");
}
