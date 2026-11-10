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

function sliceFunction(src, name) {
  const start = src.indexOf("async function " + name + "(");
  if (start < 0) throw new Error("workbench.html 中找不到 async function " + name);
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

const failures = cases.filter((c) => !c.ok);
for (const c of failures) console.error(`[FAIL] ${c.name}: ${c.problem}`);
console.log(JSON.stringify({ failures: failures.length, total: cases.length, cases: cases.map((c) => ({ name: c.name, ok: c.ok })) }));
process.exit(failures.length === 0 ? 0 : 1);
