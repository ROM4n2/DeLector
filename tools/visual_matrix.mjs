#!/usr/bin/env node
/*
 * DeLector P0 截图矩阵 + computed-style 导出（零 npm 依赖，直连 CDP）。
 *
 * 由 tools/visual_matrix.py 一键调用；也可对已启动的服务单独运行：
 *   node tools/visual_matrix.mjs --url http://127.0.0.1:8765 --out _artifacts/matrix
 *
 * 设计取舍：
 * - 每个场景都重新导航，避免上一场景的 drawer/modal/选区残留。
 * - 截图前等待有限动画结束，并把 `iterations === Infinity` 的循环动画暂停在 0ms，
 *   让 marquee/光标类无限动画不制造逐帧差异。
 * - 任何场景/控件缺失都记为失败并以非 0 退出，不静默 skip。
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DEFAULT_WIDTHS = [393, 360, 1280];
const MOBILE_HEIGHT = 844;
const DESKTOP_HEIGHT = 900;
const PROPERTIES = [
  "display",
  "width",
  "height",
  "color",
  "background-color",
  "border-top-color",
  "border-top-width",
  "border-radius",
  "font-family",
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
  "padding-top",
  "padding-left",
  "box-shadow",
  "opacity",
  "transform",
  "transition-duration",
  "animation-name",
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parseArgs(argv) {
  const args = { widths: DEFAULT_WIDTHS, only: null, out: null, computedStyleOut: null, url: null };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (flag === "--url") args.url = value;
    else if (flag === "--out") args.out = value;
    else if (flag === "--computed-style-out") args.computedStyleOut = value;
    else if (flag === "--widths") args.widths = value.split(",").map((item) => Number(item.trim())).filter(Boolean);
    else if (flag === "--only") args.only = value.split(",").map((item) => item.trim()).filter(Boolean);
    else continue;
    i += 1;
  }
  if (!args.url || !args.out || !args.computedStyleOut) {
    throw new Error("必须提供 --url / --out / --computed-style-out");
  }
  return args;
}

function findChrome() {
  const candidates = [];
  if (process.env.DELECTOR_CHROME) candidates.push(process.env.DELECTOR_CHROME);
  const playwrightRoot = process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, "ms-playwright")
    : null;
  if (playwrightRoot && fs.existsSync(playwrightRoot)) {
    for (const entry of fs.readdirSync(playwrightRoot).sort().reverse()) {
      if (entry.startsWith("chromium-")) {
        candidates.push(path.join(playwrightRoot, entry, "chrome-win64", "chrome.exe"));
      }
      if (entry.startsWith("chromium_headless_shell-")) {
        candidates.push(
          path.join(playwrightRoot, entry, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        );
      }
    }
  }
  candidates.push(
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  );
  const found = candidates.find((candidate) => candidate && fs.existsSync(candidate));
  if (!found) {
    throw new Error("找不到 Chromium/Chrome；请设置 DELECTOR_CHROME 指向可执行文件");
  }
  return found;
}

async function startChrome() {
  const executable = findChrome();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "delector-visual-"));
  const port = 9300 + Math.floor(Math.random() * 500);
  const child = spawn(
    executable,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      "--force-device-scale-factor=1",
      `--user-data-dir=${profile}`,
      `--remote-debugging-port=${port}`,
      "about:blank",
    ],
    { stdio: "ignore", windowsHide: true },
  );

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page) return { child, port, profile, wsUrl: page.webSocketDebuggerUrl };
    } catch {
      /* 浏览器还没起好，继续等 */
    }
    await sleep(200);
  }
  child.kill();
  throw new Error("Chromium 在 20s 内没有暴露 CDP 页面");
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.seq = 0;
    this.pending = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
      }
    };
  }

  async send(method, params = {}) {
    await this.ready;
    const id = ++this.seq;
    const response = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.ws.send(JSON.stringify({ id, method, params }));
    return response;
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      const description =
        result.exceptionDetails.exception?.description || JSON.stringify(result.exceptionDetails);
      throw new Error(description);
    }
    return result.result?.value;
  }

  close() {
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }
}

const SCENARIOS = [
  {
    key: "home",
    label: "首页 / 文稿库",
    prep: `(async () => { window.show("home"); return true; })()`,
    ready: `document.querySelector(".article-row")`,
  },
  {
    key: "reader",
    label: "阅读器（预置文章）",
    prep: `(async () => {
      const articles = await (await fetch("/api/articles")).json();
      if (!articles.length) throw new Error("没有可打开的文章");
      window.show("reader");
      await window.openReader(articles[0].id);
      return true;
    })()`,
    ready: `document.querySelector(".tok")`,
  },
  {
    key: "reader-select",
    label: "阅读器选中词元（基线控件专用）",
    matrix: false,
    prep: `(async () => {
      const articles = await (await fetch("/api/articles")).json();
      if (!articles.length) throw new Error("没有可打开的文章");
      window.show("reader");
      await window.openReader(articles[0].id);
      const token = document.querySelector(".tok.A1") || document.querySelector(".tok");
      if (!token) throw new Error("阅读器没有渲染词元");
      const sent = token.closest(".reader-sent-unit");
      window.inspect(Number(token.id.replace("tok-", "")), Number(sent?.dataset.sentId || 0));
      return true;
    })()`,
    ready: `document.querySelector(".tok.sel")`,
  },
  {
    key: "drawer",
    label: "词卡 / 生词抽屉",
    prep: `(async () => {
      const articles = await (await fetch("/api/articles")).json();
      if (!articles.length) throw new Error("没有可打开的文章");
      window.show("reader");
      await window.openReader(articles[0].id);
      const token = document.querySelector(".tok.A1") || document.querySelector(".tok");
      if (!token) throw new Error("阅读器没有渲染词元");
      const sent = token.closest(".reader-sent-unit");
      window.inspect(Number(token.id.replace("tok-", "")), Number(sent?.dataset.sentId || 0));
      window.openDrawer("vocab");
      return true;
    })()`,
    ready: `document.querySelector("#drawer.open")`,
  },
  {
    key: "cards",
    label: "卡盒（闪卡牌堆）",
    prep: `(async () => {
      window.show("cards");
      await window.loadCards();
      window.setCardViewMode("deck");
      return true;
    })()`,
    ready: `document.querySelector(".deck-active-card")`,
  },
  {
    key: "exam",
    label: "备考总览",
    prep: `(async () => { window.show("exam"); return true; })()`,
    ready: `document.querySelector(".exam-module-card.active")`,
  },
  {
    key: "progress",
    label: "学习进度",
    prep: `(async () => { window.show("progress"); await window.loadProgress(); return true; })()`,
    ready: `document.querySelector(".stat-ring")`,
  },
  {
    key: "writer",
    label: "写作诊断",
    prep: `(async () => { window.show("writer"); return true; })()`,
    ready: `document.querySelector("#ide-editor")`,
  },
  {
    key: "german",
    label: "德语背词工作台",
    prep: `(async () => { window.show("german"); return true; })()`,
    ready: `(() => {
      const frame = document.getElementById("german-workbench-frame");
      return !!(frame && frame.contentDocument && frame.contentDocument.querySelector("#view-review"));
    })()`,
    timeout: 20000,
  },
  {
    key: "search",
    label: "全文检索",
    prep: `(async () => {
      window.show("search");
      const input = document.getElementById("search-input");
      input.value = "der";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`,
    ready: `document.querySelector("#view-search.active")`,
    delay: 1200,
  },
  {
    key: "encounter",
    label: "遇见区 / 分级短篇",
    prep: `(async () => { window.show("encounter"); return true; })()`,
    ready: `document.querySelector("#view-encounter.active")`,
  },
  {
    key: "settings",
    label: "设置弹窗",
    prep: `(async () => { await window.openSettingsModal(); return true; })()`,
    ready: `document.querySelector("#settings-overlay.open")`,
  },
  {
    key: "quiz",
    label: "测验浮层",
    prep: `(async () => {
      window.show("cards");
      await window.loadCards();
      window.openQuizOverlay();
      return true;
    })()`,
    ready: `document.querySelector(".quiz-mode-card")`,
  },
];

const CONTROLS = [
  { key: "nav-tab-active", label: "顶部导航（选中态）", selector: ".nav-tab.active", scenario: "home", width: 1280 },
  { key: "mobile-nav-active", label: "底部导航（选中态）", selector: ".mobile-nav-btn.active", scenario: "home", width: 393 },
  { key: "article-row", label: "文稿列表行", selector: ".article-row", scenario: "home", width: 1280 },
  { key: "btn-primary", label: "主按钮 btn-dark", selector: "#view-cards .btn.btn-dark", scenario: "cards", width: 1280 },
  { key: "btn-ghost", label: "次按钮 btn-ghost", selector: "#view-cards .btn.btn-ghost", scenario: "cards", width: 1280 },
  { key: "btn-accent", label: "强调按钮 btn-accent", selector: ".btn.btn-accent", scenario: "encounter", width: 1280 },
  { key: "tok-A1", label: "阅读器 A1 词元", selector: ".tok.A1", scenario: "reader", width: 1280 },
  { key: "tok-selected", label: "阅读器选中词元", selector: ".tok.sel", scenario: "reader-select", width: 1280 },
  { key: "deck-active-card", label: "闪卡牌堆顶卡", selector: ".deck-active-card", scenario: "cards", width: 1280 },
  { key: "exam-module-active", label: "备考模块（选中态）", selector: ".exam-module-card.active", scenario: "exam", width: 1280 },
  { key: "stat-ring-coral", label: "进度统计环（coral）", selector: ".stat-ring.coral", scenario: "progress", width: 1280 },
  { key: "settings-input", label: "设置输入框", selector: "#set-base-url", scenario: "settings", width: 1280 },
];

function viewportFor(width) {
  return { width, height: width < 600 ? MOBILE_HEIGHT : DESKTOP_HEIGHT, deviceScaleFactor: 1, mobile: width < 600 };
}

async function navigate(cdp, url) {
  await cdp.send("Page.navigate", { url });
  await waitFor(cdp, `document.readyState === "complete"`, 15000);
  await waitFor(cdp, `!!window.show && !!document.getElementById("view-home")`, 15000);
}

async function waitFor(cdp, expression, timeout = 12000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      if (await cdp.evaluate(`!!(${expression})`)) return;
    } catch {
      /* 页面切换中可能短暂异常 */
    }
    await sleep(150);
  }
  throw new Error(`等待超时：${expression}`);
}

async function settle(cdp) {
  await cdp.evaluate(`(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await new Promise((resolve) => setTimeout(resolve, 700));
    for (const animation of document.getAnimations()) {
      const timing = animation.effect && animation.effect.getTiming ? animation.effect.getTiming() : null;
      if (timing && timing.iterations === Infinity) {
        try { animation.pause(); animation.currentTime = 0; } catch {}
      }
    }
    return true;
  })()`);
}

async function runScenario(cdp, url, scenario, width, outDir, shotIndex) {
  const started = Date.now();
  await cdp.send("Emulation.setDeviceMetricsOverride", viewportFor(width));
  await navigate(cdp, url);
  await cdp.evaluate(scenario.prep);
  if (scenario.ready) await waitFor(cdp, scenario.ready, scenario.timeout || 12000);
  if (scenario.delay) await sleep(scenario.delay);
  await settle(cdp);
  const { data } = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const filename = `${String(shotIndex).padStart(2, "0")}-${scenario.key}-${width}.png`;
  fs.writeFileSync(path.join(outDir, filename), Buffer.from(data, "base64"));
  return { scenario: scenario.key, label: scenario.label, width, file: filename, ms: Date.now() - started };
}

async function captureControls(cdp, url, outDir) {
  const groups = new Map();
  for (const control of CONTROLS) {
    const groupKey = `${control.scenario}@${control.width}`;
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(control);
  }
  const controls = {};
  for (const [, group] of groups) {
    const { scenario: scenarioKey, width } = group[0];
    const scenario = SCENARIOS.find((item) => item.key === scenarioKey);
    if (!scenario) throw new Error(`控件引用了未知场景：${scenarioKey}`);
    await cdp.send("Emulation.setDeviceMetricsOverride", viewportFor(width));
    await navigate(cdp, url);
    await cdp.evaluate(scenario.prep);
    if (scenario.ready) await waitFor(cdp, scenario.ready, scenario.timeout || 12000);
    if (scenario.delay) await sleep(scenario.delay);
    await settle(cdp);
    for (const control of group) {
      const properties = await cdp.evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(control.selector)});
        if (!element) return null;
        const style = getComputedStyle(element);
        return Object.fromEntries(${JSON.stringify(PROPERTIES)}.map((prop) => [prop, style.getPropertyValue(prop).trim()]));
      })()`);
      controls[control.key] = {
        label: control.label,
        selector: control.selector,
        scenario: control.scenario,
        width: control.width,
        properties,
        error: properties ? null : `未找到控件：${control.selector}`,
      };
    }
  }
  return {
    schema: 1,
    capturedAt: new Date().toISOString(),
    url,
    controls,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  fs.mkdirSync(args.out, { recursive: true });
  fs.mkdirSync(path.dirname(args.computedStyleOut), { recursive: true });

  const started = Date.now();
  const { child, profile, wsUrl } = await startChrome();
  const cdp = new CDP(wsUrl);
  const screenshots = [];
  const failures = [];
  let index = 0;

  try {
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    const scenarios = SCENARIOS.filter((scenario) => scenario.matrix !== false);
    const selected = args.only ? scenarios.filter((scenario) => args.only.includes(scenario.key)) : scenarios;
    if (args.only && selected.length !== args.only.length) {
      const known = new Set(scenarios.map((item) => item.key));
      const unknown = args.only.filter((key) => !known.has(key));
      throw new Error(`--only 含未知场景：${unknown.join(", ")}`);
    }

    for (const width of args.widths) {
      for (const scenario of selected) {
        index += 1;
        try {
          const result = await runScenario(cdp, args.url, scenario, width, args.out, index);
          screenshots.push(result);
          console.log(`[OK] ${result.file} (${result.ms}ms)`);
        } catch (error) {
          failures.push({ scenario: scenario.key, width, error: String(error.message || error) });
          console.log(`[FAIL] ${scenario.key} @ ${width}px: ${error.message || error}`);
        }
      }
    }

    const computed = await captureControls(cdp, args.url, args.out);
    fs.writeFileSync(args.computedStyleOut, `${JSON.stringify(computed, null, 2)}\n`, "utf-8");
    const missingControls = Object.entries(computed.controls)
      .filter(([, value]) => value.error)
      .map(([key, value]) => ({ key, error: value.error }));

    const summary = {
      startedAt: new Date(started).toISOString(),
      durationMs: Date.now() - started,
      widths: args.widths,
      screenshotCount: screenshots.length,
      expectedScreenshotCount: selected.length * args.widths.length,
      screenshots,
      failures,
      computedStylePath: args.computedStyleOut,
      missingControls,
    };
    fs.writeFileSync(path.join(args.out, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf-8");
    console.log(
      `\n矩阵完成：${summary.screenshotCount}/${summary.expectedScreenshotCount} 张，` +
        `${(summary.durationMs / 1000).toFixed(1)}s；失败 ${failures.length}，控件缺失 ${missingControls.length}`,
    );
    if (failures.length || missingControls.length) process.exitCode = 1;
  } finally {
    cdp.close();
    child.kill();
    await sleep(300);
    fs.rmSync(profile, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
