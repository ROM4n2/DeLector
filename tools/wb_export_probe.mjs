// 工作台导出行为探针：钉住「没有真实落盘证据就不许报成功」。
//
// 背景（2026-11-11 缺陷）：桌面壳 WebView2 默认 ALLOW_DOWNLOADS=False，
// `on_download_starting` 会静默取消下载；旧前端 `download()` 之后无条件
// `toast("已导出…")`，于是磁盘上没有文件而界面照样报成功。
//
// 本探针从 workbench.html 切出 `download()` 与 `exportAndReport()` 的真实源码，
// 在 node:vm 里用假 fetch 真跑，逐个场景断言 toast：
//   save_ok            → 报「已导出」并带真实路径/字节数
//   save_ok_fallback_dir → 落盘成功但下载目录降级：必须显式说「已存到用户主目录」
//   save_500           → 只报失败（⚠ + error 形态），不得出现「已导出」
//   save_no_path       → 200 但缺 path ⇒ 仍算失败，不得报成功
//   fallback_501       → Android/旧通道：只报「已请求下载」，不承诺落盘
//   save_network_throw → 退回下载通道，同样不承诺落盘
//
// --json 输出契约（新增探针 MUST 标准三键）：{failures, total, cases:[{name, ok}]}

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HTML = fs.readFileSync(path.join(ROOT, "static/german/workbench.html"), "utf8");

/* 红线 13：锚点 + 括号配平。旧实现 `src.indexOf("{", start)` 拿参数表里解构的
 * `{` 当函数体、且简单数花括号不跳字符串/注释/模板 ⇒ 切出无体短切片，判据恒真。
 * 口径与 tools/cards_catalog_tag_probe.mjs 的 matchBracket 一致。 */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx, label) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket(${label}): 位置 ${openIdx} 不是开括号`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c; i += 1;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === q) break;
        i += 1;
      }
      i += 1; continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (OPEN[c]) { stack.push(c); i += 1; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c])
        throw new Error(`matchBracket(${label}): 括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i += 1; continue;
    }
    i += 1;
  }
  throw new Error(`matchBracket(${label}): 从 ${openIdx} 起找不到配对闭括号（MUST NOT 返回短切片）`);
}

function sliceFunction(src, name) {
  const anchor = "async function " + name + "(";
  const start = src.indexOf(anchor);
  if (start < 0) throw new Error(`workbench.html 中找不到 ${anchor}（红线 13 锚点失败）`);
  const paren = start + anchor.length - 1; // '(' 的下标
  const paramsEnd = matchBracket(src, paren, name + " 参数表");
  let j = paramsEnd + 1;
  while (j < src.length && /\s/.test(src[j])) j += 1;
  if (src[j] !== "{") {
    throw new Error(
      `sliceFunction(${name}): 参数表 ')' 之后下一个非空白字符不是函数体 '{'` +
      `（实际 ${JSON.stringify(src[j] ?? "<EOF>")}）；MUST NOT 返回短切片（红线 13）`
    );
  }
  const end = matchBracket(src, j, name + " 函数体");
  return src.slice(start, end + 1);
}

const downloadSrc = sliceFunction(HTML, "download");
const reportSrc = sliceFunction(HTML, "exportAndReport");

function runScenario(name, fetchImpl, check) {
  const toasts = [];
  const sandbox = {
    console,
    location: { protocol: "http:", href: "" },
    fetch: fetchImpl,
    Blob: class { constructor(parts) { this.parts = parts; } },
    URL: { createObjectURL: () => "blob:stub", revokeObjectURL: () => {} },
    document: {
      body: { appendChild: () => {} },
      createElement: () => ({ href: "", download: "", click: () => {}, remove: () => {} })
    },
    setTimeout: () => 0,
    clearTimeout: () => {},
    $: () => ({ textContent: "", dataset: {}, classList: { add: () => {}, remove: () => {} } }),
    toast: (msg, kind) => toasts.push({ msg, kind: kind || "info" })
  };
  vm.createContext(sandbox);
  vm.runInContext(`${downloadSrc}\n${reportSrc}\nthis.__run = exportAndReport;`, sandbox);
  return sandbox
    .__run("同步文件", "wb-sync-2026-11-11.json", { type: "wb-sync", cards: {} })
    .then(() => {
      const problem = check({ toasts, location: sandbox.location });
      return { name, ok: !problem, problem };
    })
    .catch((err) => ({ name, ok: false, problem: "场景抛异常：" + err.stack }));
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const cases = [];

cases.push(
  await runScenario(
    "save_ok",
    async () => jsonResponse({ ok: true, path: "C:\\Users\\u\\Downloads\\wb-sync-2026-11-11.json", bytes: 42 }),
    ({ toasts }) => {
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}：${JSON.stringify(toasts)}`;
      const t = toasts[0];
      if (!t.msg.includes("已导出")) return "成功路径未报「已导出」：" + t.msg;
      if (!t.msg.includes("wb-sync-2026-11-11.json")) return "成功路径未带真实路径：" + t.msg;
      if (!t.msg.includes("42")) return "成功路径未带字节数：" + t.msg;
      return null;
    }
  )
);

cases.push(
  await runScenario(
    "save_ok_fallback_dir",
    async () => jsonResponse({
      ok: true,
      path: "C:\\Users\\u\\wb-sync-2026-11-11.json",
      bytes: 42,
      fallback_dir: true,
      warning: "下载目录不可用，已保存到用户主目录"
    }),
    ({ toasts }) => {
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}：${JSON.stringify(toasts)}`;
      const t = toasts[0];
      if (!t.msg.includes("已导出")) return "降级写盘未报「已导出」：" + t.msg;
      if (!t.msg.includes("用户主目录")) return "下载目录降级却未说明真实位置：" + t.msg;
      if (!t.msg.includes("wb-sync-2026-11-11.json")) return "降级写盘未带真实路径：" + t.msg;
      return null;
    }
  )
);

cases.push(
  await runScenario(
    "save_500",
    async () => jsonResponse({ detail: "写入失败：磁盘只读" }, 500),
    ({ toasts }) => {
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}`;
      const t = toasts[0];
      if (t.msg.includes("已导出")) return "写盘失败却报成功：" + t.msg;
      if (!t.msg.startsWith("⚠ 导出失败：")) return "失败 toast 缺 ⚠ 前缀：" + t.msg;
      if (!t.msg.includes("磁盘只读")) return "失败 toast 未带原因：" + t.msg;
      if (t.kind !== "error") return "失败 toast 未标 error 形态：" + t.kind;
      return null;
    }
  )
);

cases.push(
  await runScenario(
    "save_no_path",
    async () => jsonResponse({ ok: true }),
    ({ toasts }) => {
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}`;
      if (toasts[0].msg.includes("已导出")) return "200 但无落盘路径却报成功：" + toasts[0].msg;
      if (toasts[0].kind !== "error") return "缺路径未按失败处理";
      return null;
    }
  )
);

cases.push(
  await runScenario(
    "fallback_501",
    async (url) => {
      if (String(url).includes("/api/wb/backup/save")) return jsonResponse({ detail: "Android 使用系统下载通道" }, 501);
      return jsonResponse({ token: "tok-1" });
    },
    ({ toasts, location }) => {
      if (location.href !== "/api/wb/backup/download/tok-1") return "未走旧下载通道：" + location.href;
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}`;
      if (toasts[0].msg.includes("已导出")) return "回退通道未验证落盘却报成功：" + toasts[0].msg;
      if (!toasts[0].msg.includes("已请求下载")) return "回退提示不明确：" + toasts[0].msg;
      return null;
    }
  )
);

cases.push(
  await runScenario(
    "save_network_throw",
    async (url) => {
      if (String(url).includes("/api/wb/backup/save")) throw new Error("network down");
      return jsonResponse({ token: "tok-2" });
    },
    ({ toasts, location }) => {
      if (location.href !== "/api/wb/backup/download/tok-2") return "网络异常后未回退下载通道：" + location.href;
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}`;
      if (toasts[0].msg.includes("已导出")) return "网络异常却报成功：" + toasts[0].msg;
      return null;
    }
  )
);

/* ── sliceFunction 自证（T10）：阳性 / 阴性 / 变异自证 ──────────────────────
 * 把保护物（配平）换回旧实现 ⇒ 下面三条场景立即转红 ⇒ 探针 exit 1 ⇒ wrapper 红。 */
function sliceSelfTest() {
  const out = [];
  const add = (name, ok, detail) =>
    out.push({ name, ok: !!ok, problem: ok ? null : String(detail) });

  add("slice_real_download_has_full_body",
    downloadSrc.includes("return { ok: true") && downloadSrc.trimEnd().endsWith("}"),
    "download 真源码切片不含函数体（短切片 / 锚点失败）");
  add("slice_real_report_has_full_body",
    reportSrc.includes('toast("⚠ 导出失败："') && reportSrc.trimEnd().endsWith("}"),
    "exportAndReport 真源码切片不含函数体");

  const trap = [
    "async function trap() {",
    '  const s = "}";',
    "  // } 行注释里的花括号",
    "  /* } 块注释里的花括号 */",
    "  const t = `}`;",
    "  const tail = 1;",
    "}",
  ].join("\n");
  let trapped = "";
  try { trapped = sliceFunction(trap, "trap"); } catch (e) { add("slice_skips_strings_comments_templates", false, e.message); }
  if (trapped) add("slice_skips_strings_comments_templates",
    trapped.includes("const tail = 1;") && trapped.trimEnd().endsWith("}"),
    "字符串/注释/模板里的 `}` 让切片提前收尾（旧数花括号实现）");

  const destructured = "async function f({a}={}) { return a; }\n";
  let dsrc = "";
  try { dsrc = sliceFunction(destructured, "f"); } catch (e) { add("slice_destructured_params_full_body", false, e.message); }
  if (dsrc) add("slice_destructured_params_full_body",
    dsrc.includes("return a;") && dsrc.trimEnd().endsWith("}") && dsrc.length > destructured.indexOf("{") + 1,
    "解构参数 f({a}={}) 停在参数花括号上（旧 indexOf('{') 实现）");

  let threw = false;
  try { sliceFunction("async function g() 42;", "g"); } catch (e) { threw = /参数表|短切片/.test(e.message); }
  add("slice_rejects_non_brace_after_paren", threw,
    "')' 后非 '{' 时未具名报错（返回了短切片？）");
  return out;
}

cases.push(...sliceSelfTest());

const failures = cases.filter((c) => !c.ok);
for (const c of failures) console.error(`[FAIL] ${c.name}: ${c.problem}`);
console.log(JSON.stringify({ failures: failures.length, total: cases.length, cases: cases.map((c) => ({ name: c.name, ok: c.ok })) }));
process.exit(failures.length === 0 ? 0 : 1);
