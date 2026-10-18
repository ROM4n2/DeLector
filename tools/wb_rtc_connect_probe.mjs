/**
 * wb_rtc_connect_probe.mjs —— 前端 WebRTC 建连与 DataChannel 收发契约
 *
 * Stage B M3（docs/plans/archive/2026-09-03-lan-silent-sync-stage-b.md Task 4）：
 * 本环境跑不了真 P2P，所以用**桩 RTCPeerConnection** 把建连/收发的行为钉住。探针把
 * workbench.html 里真实的 wbsync 源码切进 node:vm，断言：
 *   1) rtc.connect() 建 DataChannel 并 createOffer；
 *   2) offer 经配对远端的中继端点 POST 出去，且带 X-WB-Key = 配对 key；
 *   3) 中继里对端的 answer 会被 setRemoteDescription 收下；
 *   4) DataChannel open 后立刻把 snapshot 发过去（信封形如 {payload:{...}}）；
 *   5) 收到对端信封后走 applyMerge(payload, {silent:true}) —— 静默合并、不弹窗。
 *
 * 实现若回退（不建连 / 打到相对地址 / 不鉴权 / 收到信封不合并或弹窗），本探针必红。
 *
 * 用法：
 *   node tools/wb_rtc_connect_probe.mjs            # 人类可读
 *   node tools/wb_rtc_connect_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
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
for (const must of ["pushNow", "snapshot", "X-WB-Key", "function stable", "function pull",
                    "function boot", "remoteEndpoint", "revokePair",
                    "rtcConnect", "rtcSendEnvelope", "rtc"] ) {
  if (!SRC.includes(must)) fail(`wbsync 切片里缺 "${must}"（函数没写或切片切歪了）`);
}

const PAIR = { host: "192.168.1.103", key: "a1b2c3d4e5f60718293a4b5c6d7e8f90", ts: 1 };
// 对端（B）经中继回的信令：answer + 一个 ICE candidate
const PEER_MESSAGES = [
  { sender: "B", type: "answer", payload: { type: "answer", sdp: "v=0 mock-answer" }, ts: 10 },
  { sender: "B", type: "candidate", payload: { candidate: "candidate:1 1 udp 1 10.0.0.2 5000 typ host" }, ts: 11 },
];
// 对端发来的进度信封（与 HTTP PUT 同一个信封形状 {payload:{...}}）
const PEER_SNAPSHOT = { words: [{ id: "w9", hw: "Buch", up: 2 }], cards: { cx: { reps: 7, last: 5 } },
                        log: {}, wrong: {}, settings: { dailyNew: 20 } };

const PRELUDE = `
var __reqs = [];
var __rtcLog = [];
var __chan = null;          // 探针持有 DataChannel 桩，便于主动触发 onopen/onmessage
var __merged = null;
var __mergeOpts = null;
var S = { words: [{ id: "local1", hw: "Haus", up: 1 }], cards: { cl: { reps: 2, last: 1 } },
          log: {}, wrong: {}, settings: { dailyNew: 20 } };
function applyMerge(d, opts) { __merged = d; __mergeOpts = opts || null; }
function renderReview() {}
function renderHeaderBadge() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { return 0; }
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
  __reqs.push({ url: String(url), method: o.method || "GET", headers: o.headers || {}, body: o.body || null });
  var u = String(url);
  if (/rtc\\/signal$/.test(u) && o.method === "POST") {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
  }
  if (/rtc\\/signal\\?/.test(u)) {
    return Promise.resolve({ ok: true, json: function () {
      return Promise.resolve({ messages: ${JSON.stringify(PEER_MESSAGES)}, now: 12 });
    } });
  }
  if (/\\/api\\/wb\\/state$/.test(u) && (!o.method || o.method === "GET")) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } });
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
}
function RTCPeerConnection(cfg) {
  var self = this;
  this.localDescription = null;
  this.remoteDescription = null;
  this.onicecandidate = null;
  this.createDataChannel = function (name) {
    __rtcLog.push(["createDataChannel", name]);
    __chan = { send: function (s) { __rtcLog.push(["send", s]); }, close: function () {},
               onopen: null, onmessage: null };
    return __chan;
  };
  this.createOffer = function () {
    __rtcLog.push(["createOffer"]);
    return Promise.resolve({ type: "offer", sdp: "v=0 mock-offer" });
  };
  this.createAnswer = function () {
    __rtcLog.push(["createAnswer"]);
    return Promise.resolve({ type: "answer", sdp: "v=0 mock-answer" });
  };
  this.setLocalDescription = function (d) {
    __rtcLog.push(["setLocalDescription", d && d.type]);
    self.localDescription = d;
    return Promise.resolve();
  };
  this.setRemoteDescription = function (d) {
    __rtcLog.push(["setRemoteDescription", d && d.type, d && d.sdp]);
    self.remoteDescription = d;
    return Promise.resolve();
  };
  this.addIceCandidate = function (c) {
    __rtcLog.push(["addIceCandidate", JSON.stringify(c)]);
    return Promise.resolve();
  };
  this.close = function () { __rtcLog.push(["close"]); };
}
`;

const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
vm.runInContext(PRELUDE + "\n" + SRC + "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });

const read = (expr) => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, ctx));

// ── init：boot 会从 localStorage 恢复持久配对，_key 随之就绪 ─────────────────
vm.runInContext("__wbsync.init()", ctx);
for (let k = 0; k < 4; k++) await new Promise((r) => process.nextTick(r));

// ── 1) 建连：建 DataChannel + createOffer ────────────────────────────────────
const connected = await vm.runInContext("__wbsync.rtc.connect()", ctx);
for (let k = 0; k < 6; k++) await new Promise((r) => process.nextTick(r));

const rtcLog = read("__rtcLog");
if (connected !== true) fail("rtc.connect() 返回 " + String(connected) + "（有配对密钥时应能发起建连）");
if (!rtcLog.some((e) => e[0] === "createDataChannel")) fail("没有建 DataChannel：" + JSON.stringify(rtcLog));
if (!rtcLog.some((e) => e[0] === "createOffer")) fail("发起端没有 createOffer：" + JSON.stringify(rtcLog));

// ── 2) offer 必须经「配对远端」的中继端点发出，且带配对 key ──────────────────
const reqs = read("__reqs");
const relay = "http://" + PAIR.host + "/api/wb/rtc/signal";
const offerPost = reqs.find((r) => r.method === "POST" && r.url === relay);
if (!offerPost) fail("offer 没发往配对远端的中继端点 " + relay + "（打到相对地址=打到自己）：" +
  JSON.stringify(reqs.map((r) => r.method + " " + r.url)));
if (offerPost.headers["X-WB-Key"] !== PAIR.key) {
  fail("信令没带配对 key：" + String(offerPost.headers["X-WB-Key"]));
}
let offerBody = null;
try { offerBody = JSON.parse(offerPost.body); } catch (e) { offerBody = null; }
if (!offerBody || offerBody.type !== "offer" || !offerBody.payload || !offerBody.payload.sdp) {
  fail("offer 请求体不合契约（应含 client/type/payload.sdp）：" + String(offerPost.body));
}

// ── 3) 中继里对端的 answer 要被收下 ──────────────────────────────────────────
const setRemote = rtcLog.filter((e) => e[0] === "setRemoteDescription");
if (!setRemote.some((e) => e[1] === "answer")) {
  fail("没有用对端的 answer 调 setRemoteDescription：" + JSON.stringify(rtcLog));
}
const gotCandidate = rtcLog.some((e) => e[0] === "addIceCandidate");
if (!gotCandidate) fail("对端的 ICE candidate 没有喂给 addIceCandidate：" + JSON.stringify(rtcLog));

// ── 4) DataChannel open 后要主动把本机快照发过去 ────────────────────────────
vm.runInContext("if (__chan && __chan.onopen) __chan.onopen()", ctx);
const sends = read("__rtcLog").filter((e) => e[0] === "send");
if (!sends.length) fail("DataChannel open 后没有发送本机快照");
let sent = null;
try { sent = JSON.parse(sends[sends.length - 1][1]); } catch (e) { sent = null; }
if (!sent || !sent.payload || !sent.payload.words) {
  fail("发出的信封不是 {payload:{...}} 形状（应与 HTTP PUT 同构）：" + String(sends[sends.length - 1][1]));
}

// ── 5) 收到对端信封 → 静默合并（不弹窗、不切视图） ──────────────────────────
vm.runInContext(`if (__chan && __chan.onmessage) __chan.onmessage({ data: JSON.stringify(${JSON.stringify({ payload: PEER_SNAPSHOT })}) })`, ctx);
const merged = read("__merged");
const mergeOpts = read("__mergeOpts");
if (!merged || !merged.cards || !merged.cards.cx) {
  fail("收到对端信封没有送进 applyMerge：" + JSON.stringify(merged));
}
if (merged.payload) fail("applyMerge 收到的是未解包的信封（应传 payload 内层）：" + JSON.stringify(merged));
if (!mergeOpts || mergeOpts.silent !== true) {
  fail("DataChannel 合并没有走静默模式（后台同步弹窗/切视图会很烦）：" + JSON.stringify(mergeOpts));
}

const out = {
  ok: true,
  connected,
  channelCreated: rtcLog.some((e) => e[0] === "createDataChannel"),
  offerPostUrl: offerPost.url,
  offerHasPairKey: offerPost.headers["X-WB-Key"] === PAIR.key,
  answerApplied: setRemote.some((e) => e[1] === "answer"),
  candidateApplied: gotCandidate,
  snapshotSentOnOpen: !!sent,
  mergedCardIds: Object.keys(merged.cards || {}),
  mergeSilent: !!(mergeOpts && mergeOpts.silent === true),
};
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("建连动作：", JSON.stringify(rtcLog.map((e) => e[0])));
  console.log("offer 发往：", out.offerPostUrl, "（带配对 key：" + out.offerHasPairKey + "）");
  console.log("对端 answer 已应用：", out.answerApplied, "| candidate 已应用：", out.candidateApplied);
  console.log("open 后发送快照：", out.snapshotSentOnOpen);
  console.log("applyMerge 收到的卡片：", out.mergedCardIds, "| 静默：", out.mergeSilent);
  console.log("✅ PASS: wbsync.rtc 经配对远端中继建连，DataChannel 收发信封并静默合并");
}
