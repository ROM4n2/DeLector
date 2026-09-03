/**
 * wb_phone_pull_silent_probe.mjs —— 手机后台轮询 pull 必须静默（不弹「合并导入完成」）
 *
 * 2026-09-03 跟进事故：上一轮让手机能拉到镜像后，用户背词时每 5s 轮询都弹
 * 「合并导入完成」通知、还把视图踢到 review，很烦。根因：wbsync.pull() 发现本机与
 * 桌面镜像有差异就调 applyMerge，而 applyMerge 末尾无条件 toast + showView("review")。
 * 后台轮询是镜像同步，不是「导入完成」，不该有阻断式弹窗（也违背前端规范
 * FRONTEND-DESIGN-PATTERNS：阻断式弹窗应改走字通知带）。
 *
 * 本探针把 **真 wbsync + 真 applyMerge + 真 normHw** 切进 node:vm 真跑，桩 toast/showView
 * 记录调用次数，模拟手机（/key=403）且本机进度与镜像持续不同（手机有 c9、镜像有 c1）。
 *   - 后台 pull 触发 toast / 切视图 → 探针 exit 1（bug）
 *   - 后台 pull 静默、但显式 applyMerge 仍弹 → exit 0（修复后）
 *
 * 用法：
 *   node tools/wb_phone_pull_silent_probe.mjs            # 人类可读
 *   node tools/wb_phone_pull_silent_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * bug 存在时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");
const fail = (m) => { process.stderr.write(m + "\n"); process.exit(1); };
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
      while (i < src.length) { if (src[i] === "\\") { i += 2; continue; } if (src[i] === q) break; i++; }
      i++; continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (OPEN[c]) { stack.push(c); i++; continue; }
    if (CLOSE[c]) { if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对 @${i}`); stack.pop(); if (!stack.length) return i; i++; continue; }
    i++;
  }
  throw new Error("找不到配对闭括号");
}
function sliceBlock(src, re) {
  const m = re.exec(src);
  if (!m) fail("找不到 " + re);
  let i = m.index + m[0].length;
  while (i < src.length && !OPEN[src[i]]) i++;
  const end = matchBracket(src, i);
  const semi = src.indexOf(";", end);
  return src.slice(m.index, (semi >= 0 && semi < end + 8 ? semi : end) + 1);
}

const wbsyncSrc = sliceBlock(html, /^const\s+wbsync\s*=/m);
const applyMergeSrc = sliceBlock(html, /function applyMerge\(/);
const normHwSrc = sliceBlock(html, /function normHw\(/);
if (!applyMergeSrc.includes('toast("合并导入完成')) fail("applyMerge 切片里缺 toast 调用，切歪了");
for (const must of ["pushNow", "snapshot", "X-WB-Key", "function stable", "function pull", "function boot"]) {
  if (!wbsyncSrc.includes(must)) fail(`wbsync 切片里缺 "${must}"，切歪了`);
}

/* 手机本地：背过 c9（比镜像新），与镜像 c1 持续不同 → 每次 pull 都 diff */
const MIRROR = {
  words: [{ id: "w1", hw: "Haus", up: 3 }],
  cards: { c1: { reps: 5, last: 999 } },
  log: { "2026-09-03": { rv: 3 } },
  wrong: {},
  settings: {},
};

const PRELUDE = `
globalThis.__toasts = [];
globalThis.__views = [];
var __reqs = [];
var S = { words: [], cards: { c9: { reps: 2, last: 500 } }, log: {}, wrong: {}, settings: { dailyNew: 20 } };
function toast(m) { globalThis.__toasts.push(m); }
function showView(v) { globalThis.__views.push(v); }
function renderReview() {}
function renderHeaderBadge() {}
function applyTheme() {}
function saveWords() {} function saveCards() {} function saveLog() {} function saveWrong() {} function saveSettings() {}
var document = { addEventListener: function () {}, hidden: false };
var window = { addEventListener: function () {} };
function setTimeout(fn, ms) { return 0; }
function clearTimeout(id) {}
function setInterval(fn, ms) { return 0; }
function fetch(url, opts) {
  var o = opts || {};
  __reqs.push({ url: url, method: o.method || "GET", headers: o.headers || {}, body: o.body || null });
  if (/\\/key$/.test(url)) {
    return Promise.resolve({ ok: false, status: 403, json: function () { return Promise.resolve({}); } });
  }
  if (/\\/api\\/wb\\/state$/.test(url) && (!o.method || o.method === "GET")) {
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve(${JSON.stringify(MIRROR)}); } });
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ ok: true }); } });
}
`;

const ctx = vm.createContext({ console, Promise, JSON, Object, Array, Math, Date, String, RegExp, Error });
vm.runInContext(PRELUDE + "\n" + normHwSrc + "\n" + applyMergeSrc + "\n" + wbsyncSrc + "\n;globalThis.__wbsync = wbsync;", ctx, { filename: "wbsync-slice.js" });

/* 后台 pull：boot 的首次 pull + 手动再拉两次，模拟每 5s 轮询 */
vm.runInContext("__wbsync.init()", ctx);
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));
vm.runInContext("__wbsync.pull()", ctx);
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));
vm.runInContext("__wbsync.pull()", ctx);
await new Promise((r) => process.nextTick(r));
await new Promise((r) => process.nextTick(r));

const pullToasts = vm.runInContext("__toasts.length", ctx);
const pullViews = vm.runInContext("__views.length", ctx);

/* 显式 applyMerge（WebRTC / 文件导入）仍应弹通知 */
vm.runInContext("applyMerge({ type:'wb-sync', cards:{x1:{reps:1}}, log:{}, wrong:{}, settings:{} })", ctx);
const explicitToasts = vm.runInContext("__toasts.length", ctx);

if (pullToasts > 0) fail(`后台 pull 弹了 ${pullToasts} 次『合并导入完成』通知（还切了 ${pullViews} 次视图）—— 每 5s 轮询都会弹，很烦人`);
if (explicitToasts === 0) fail("显式合并导入（WebRTC/文件）也应给反馈，但没弹通知——改过头了");

const out = { ok: true, pullToastCount: pullToasts, pullViewSwitches: pullViews, explicitToastTotal: explicitToasts };
if (JSON_MODE) process.stdout.write(JSON.stringify(out, null, 2) + "\n");
else {
  console.log("后台 pull 通知次数：", pullToasts, "，切视图次数：", pullViews);
  console.log("显式合并导入通知次数：", explicitToasts);
  console.log("✅ PASS: 后台 pull 静默合并（无通知、不切视图），但显式导入仍弹通知");
}
