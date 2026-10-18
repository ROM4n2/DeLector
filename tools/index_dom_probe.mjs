/**
 * index_dom_probe.mjs —— static/index.html DOM 结构与闭合边界断言探针
 *
 * 遵循 C7「探针先行」纪律：在切分 static/index.html 前，精确锁定：
 *   1) 9 大业务视图 (<main id="view-...">...</main>)
 *   2) 2 大侧边抽屉 (<aside id="...">...</aside>)
 *   3) 6 大交互浮层/Modal (<div id="...-overlay" class="...overlay...">...</div>)
 *   4) 骨架组件 (topbar, nav_desktop, nav_mobile, companion)
 *
 * 用法：
 *   node tools/index_dom_probe.mjs            # 人类可读终端格式
 *   node tools/index_dom_probe.mjs --json     # 纯 JSON 格式输出（供测试/CI 消费）
 *   node tools/index_dom_probe.mjs --html <path> # 指定测试目标文件
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

let targetHtmlRel = path.join("static", "index.html");
const htmlArgIdx = process.argv.indexOf("--html");
if (htmlArgIdx >= 0 && process.argv[htmlArgIdx + 1]) {
  targetHtmlRel = process.argv[htmlArgIdx + 1];
}

const targetPath = path.isAbsolute(targetHtmlRel)
  ? targetHtmlRel
  : path.join(ROOT, targetHtmlRel);

if (!fs.existsSync(targetPath)) {
  const errPayload = { ok: false, errors: [`目标文件不存在: ${targetPath}`] };
  if (JSON_MODE) {
    console.log(JSON.stringify(errPayload, null, 2));
  } else {
    console.error(errPayload.errors[0]);
  }
  process.exit(1);
}

const html = fs.readFileSync(targetPath, "utf8");
const errors = [];
const blocks = {
  views: {},
  asides: {},
  modals: {},
  topbar: false,
  nav_desktop: false,
  nav_mobile: false,
  companion: false,
};

// ── 1. 检验 9 大视图切片与配对闭合 ──────────────────────────────────────────
const EXPECTED_VIEWS = [
  "view-home",
  "view-encounter",
  "view-reader",
  "view-cards",
  "view-progress",
  "view-writer",
  "view-exam",
  "view-german",
  "view-search",
];

for (const id of EXPECTED_VIEWS) {
  const openMarker = `id="${id}"`;
  const at = html.indexOf(openMarker);
  if (at < 0) {
    errors.push(`缺少视图容器: #${id}`);
    continue;
  }
  const tagOpen = html.lastIndexOf("<main", at);
  if (tagOpen < 0) {
    errors.push(`视图 #${id} 未使用 <main> 标签定义`);
    continue;
  }
  const tagClose = html.indexOf("</main>", at);
  if (tagClose < 0) {
    errors.push(`视图 #${id} 缺失闭合标签 </main>`);
    continue;
  }
  // 确保没有嵌套另一个 <main
  const nextOpen = html.indexOf("<main", at);
  if (nextOpen > 0 && nextOpen < tagClose) {
    errors.push(`视图 #${id} 的闭合边界被后续 <main 嵌套破坏`);
    continue;
  }
  blocks.views[id] = {
    start: tagOpen,
    end: tagClose + "</main>".length,
    length: tagClose + "</main>".length - tagOpen,
  };
}

// ── 2. 检验 2 大侧边抽屉 ──────────────────────────────────────────────────
const EXPECTED_ASIDES = ["writer-panel", "drawer"];
for (const id of EXPECTED_ASIDES) {
  const openMarker = `id="${id}"`;
  const at = html.indexOf(openMarker);
  if (at < 0) {
    errors.push(`缺少抽屉容器: #${id}`);
    continue;
  }
  const tagOpen = html.lastIndexOf("<aside", at);
  if (tagOpen < 0) {
    errors.push(`抽屉 #${id} 未使用 <aside> 标签定义`);
    continue;
  }
  const tagClose = html.indexOf("</aside>", at);
  if (tagClose < 0) {
    errors.push(`抽屉 #${id} 缺失闭合标签 </aside>`);
    continue;
  }
  blocks.asides[id] = {
    start: tagOpen,
    end: tagClose + "</aside>".length,
    length: tagClose + "</aside>".length - tagOpen,
  };
}

// ── 3. 检验 6 大模态覆盖层 ────────────────────────────────────────────────
const EXPECTED_MODALS = [
  "modal-overlay",
  "settings-overlay",
  "polish-overlay",
  "version-preview-overlay",
  "quiz-overlay",
  "cloze-overlay",
];

for (const id of EXPECTED_MODALS) {
  const openMarker = `id="${id}"`;
  const at = html.indexOf(openMarker);
  if (at < 0) {
    errors.push(`缺少模态遮罩/浮层: #${id}`);
    continue;
  }
  const tagOpen = html.lastIndexOf("<div", at);
  if (tagOpen < 0) {
    errors.push(`模态浮层 #${id} 未使用 <div> 标签定义`);
    continue;
  }
  blocks.modals[id] = true;
}

// ── 4. 检验基础布局骨架 ──────────────────────────────────────────────────
if (html.includes('<div class="top-ticker topbar">') && html.includes('id="topbar-system"')) {
  blocks.topbar = true;
} else {
  errors.push("缺少或未完整闭合顶部栏: <div class=\"top-ticker topbar\">");
}

if (html.includes('<nav id="nav">') && html.includes("</nav>")) {
  blocks.nav_desktop = true;
} else {
  errors.push("缺少或未完整闭合桌面侧边导航: <nav id=\"nav\">");
}

if (html.includes('<nav id="mobile-bottom-nav"') && html.includes("</nav>")) {
  blocks.nav_mobile = true;
} else {
  errors.push("缺少或未完整闭合移动底栏导航: <nav id=\"mobile-bottom-nav\">");
}

if (html.includes('id="companion"') && html.includes('id="companion-panel"')) {
  blocks.companion = true;
} else {
  errors.push("缺少小伴侣挂载节点: #companion / #companion-panel");
}

// ── 5. 输出判定结论 ───────────────────────────────────────────────────────
const ok = errors.length === 0;
const payload = {
  ok,
  target: path.relative(ROOT, targetPath),
  errors,
  blocks,
};

if (JSON_MODE) {
  console.log(JSON.stringify(payload, null, 2));
} else {
  if (ok) {
    console.log(`[PASS] ${payload.target}: DOM 结构验证通过 (9 视图 / 2 抽屉 / 6 模态 / 骨架完整)`);
  } else {
    console.error(`[FAIL] ${payload.target}: 发现 ${errors.length} 处 DOM 结构错误:`);
    for (const err of errors) {
      console.error(`  - ${err}`);
    }
  }
}

process.exit(ok ? 0 : 1);
