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
//   download_all_reject → download() 整体 reject：必须由 exportAndReport 兜成 error 终态
//   click_reject        → click 链（参数构造）抛出：必须由 .catch 兜成 error 终态
//
// --json 输出契约（新增探针 MUST 标准三键）：{failures, total, cases:[{name, ok}]}

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HTML = fs.readFileSync(path.join(ROOT, "static/german/workbench.html"), "utf8");

function sliceFunction(src, name) {
  const m = new RegExp("(?:async\\s+)?function\\s+" + name + "\\s*\\(").exec(src);
  if (!m) throw new Error("workbench.html 中找不到 function " + name);
  const start = m.index;
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") {
      depth -= 1;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error("函数未闭合：" + name);
}

const downloadSrc = sliceFunction(HTML, "download");
const failureSrc = sliceFunction(HTML, "reportExportFailure");
const reportSrc = sliceFunction(HTML, "exportAndReport");
const clickStart = HTML.indexOf('$("btnExportFull").addEventListener("click"');
const clickEnd = HTML.indexOf('$("fileImport").addEventListener("change"');
if (clickStart < 0 || clickEnd < 0 || clickEnd <= clickStart) {
  throw new Error("workbench.html 中找不到两个导出按钮的 click 监听块");
}
const clickSrc = HTML.slice(clickStart, clickEnd);

function runScenario(name, fetchImpl, check, { tweak, trigger } = {}) {
  const toasts = [];
  const handlers = {};
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
    handlers,
    $: (id) => ({
      textContent: "", dataset: {}, classList: { add: () => {}, remove: () => {} },
      addEventListener: (evt, fn) => { if (evt === "click") handlers[id] = fn; }
    }),
    toast: (msg, kind) => toasts.push({ msg, kind: kind || "info" })
  };
  if (tweak) tweak(sandbox);
  vm.createContext(sandbox);
  vm.runInContext(`${downloadSrc}\n${failureSrc}\n${reportSrc}\n${clickSrc}\n`
    + `this.__run = exportAndReport;`, sandbox);
  const kick = trigger
    ? Promise.resolve().then(() => {
        const h = handlers["btnExportFull"];
        if (!h) throw new Error("未注册 btnExportFull 的 click 监听");
        h();
      })
    : sandbox.__run("同步文件", "wb-sync-2026-11-11.json", { type: "wb-sync", cards: {} });
  return Promise.resolve(kick)
    .then(() => {
      return new Promise((r) => setTimeout(r, 0)).then(() => {
        const problem = check({ toasts, location: sandbox.location, handlers });
      return { name, ok: !problem, problem };
      });
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

cases.push(
  await runScenario(
    "download_all_reject",
    async () => { throw new Error("save 通道不可用"); },
    ({ toasts }) => {
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}：${JSON.stringify(toasts)}`;
      const t = toasts[0];
      if (t.msg.includes("已导出")) return "download 整体 reject 却报成功：" + t.msg;
      if (!t.msg.startsWith("⚠ 导出失败：")) return "download 整体 reject 未给失败终态：" + t.msg;
      if (t.kind !== "error") return "失败 toast 未走 error kind：" + t.kind;
      return null;
    },
    { tweak: (sandbox) => {
        // save / prepare 的异常都被 download 内部吞掉，让 blob 兜底也抛 ⇒ 整体 reject
        sandbox.Blob = class { constructor() { throw new Error("blob 兜底失败"); } };
      } }
  )
);

cases.push(
  await runScenario(
    "click_reject",
    async () => jsonResponse({ ok: true, path: "x", bytes: 1 }),
    ({ toasts, handlers }) => {
      if (!handlers["btnExportFull"] || !handlers["btnExportSync"]) return "两个 click 监听未全部注册";
      if (toasts.length !== 1) return `期望 1 次 toast，实际 ${toasts.length}：${JSON.stringify(toasts)}`;
      const t = toasts[0];
      if (!t.msg.startsWith("⚠ 导出失败：")) return "click 链抛出未给失败终态：" + t.msg;
      if (t.kind !== "error") return "click 失败 toast 未走 error kind：" + t.kind;
      return null;
    },
    { trigger: true }
  )
);

const failures = cases.filter((c) => !c.ok);
for (const c of failures) console.error(`[FAIL] ${c.name}: ${c.problem}`);
console.log(JSON.stringify({ failures: failures.length, total: cases.length, cases: cases.map((c) => ({ name: c.name, ok: c.ok })) }));
process.exit(failures.length === 0 ? 0 : 1);
