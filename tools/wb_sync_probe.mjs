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

const HTML = path.join(ROOT, "static", "german", "workbench.html");
const html = fs.readFileSync(HTML, "utf8");

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

const anchor = /^const\s+wbsync\s*=/m.exec(html);
if (!anchor) fail("workbench.html 里找不到 const wbsync 声明");
let i = anchor.index + anchor[0].length;
while (i < html.length && !OPEN[html[i]]) i++;
const end = matchBracket(html, i);
const semi = html.indexOf(";", end);
const SRC = html.slice(anchor.index, (semi >= 0 && semi < end + 8 ? semi : end) + 1);
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
