/**
 * player_tray_probe.mjs —— 底部音频托盘（B 方案）行为探针
 *
 * 钉住四条用户可见事实：
 *   1) 4 个音色都可达，且 role=radio 的 aria-checked 恒唯一；
 *   2) 折叠态按钮回显当前音色的「性别 · 姓名」；
 *   3) 每个倍速按钮的显示值与 data-speed 一致；
 *   4) 音色真正不生效时，「当前音色不可用，使用系统语音」可见，
 *      且状态行（句序/倒计时/引擎不可用）不是 0×0。
 * 另加 360×800 布局验收：托盘与所有控件不得横向溢出，传输键与倍速同排。
 *
 * 实现说明（为什么不用 CDP）：
 *   CI 跑在 ubuntu（Node 20），本机是 Windows。硬编码 msedge.exe 会在 CI 变
 *   ENOENT；而 Node 20 没有全局 WebSocket，CDP 还得多带一个实验 flag。这里改成
 *   「页面自检 + `--dump-dom`」：harness 在浏览器里跑完全部交互，把标准三键
 *   JSON 写进 <body data-probe>，Node 只负责起静态服务、拉起任意 Chromium 并
 *   解析 DOM。跨平台、零依赖、跨 Node 版本。
 *
 * 用法：
 *   node tools/player_tray_probe.mjs            # 人类可读 + 截图证据
 *   node tools/player_tray_probe.mjs --json     # stdout 只输出 JSON
 * 任一断言失败退出码 1。
 */
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const STATIC = path.join(ROOT, "static");
const JSON_MODE = process.argv.includes("--json");
const SHOT_DIR = path.join(ROOT, "_artifacts", "2026-11-07-player-tray-shots");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

/** 按平台找浏览器：环境变量优先，其次常见安装路径 / PATH。 */
function findBrowser() {
  const explicit = process.env.PLAYER_TRAY_BROWSER || process.env.CHROME_PATH || process.env.EDGE_PATH;
  if (explicit) {
    if (fs.existsSync(explicit)) return explicit;
    throw new Error(`PLAYER_TRAY_BROWSER/CHROME_PATH 指向的浏览器不存在：${explicit}`);
  }

  const absolute = {
    win32: [
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ],
    darwin: [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    linux: [],
  }[process.platform] || [];

  for (const file of absolute) {
    if (fs.existsSync(file)) return file;
  }

  const onPath = process.platform === "win32"
    ? ["msedge.exe", "chrome.exe", "chromium.exe"]
    : [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
      ];
  for (const cmd of onPath) {
    const probe = process.platform === "win32" ? "where" : "which";
    const res = spawnSync(probe, [cmd], { encoding: "utf8" });
    const hit = res.status === 0 ? res.stdout.split(/\r?\n/).map((s) => s.trim()).find(Boolean) : null;
    if (hit && fs.existsSync(hit)) return hit;
  }

  throw new Error(
    "找不到 Chromium/Edge/Chrome。安装任一浏览器，或用 PLAYER_TRAY_BROWSER 指定可执行文件路径。",
  );
}

/** 从分块模板里取出 #shadow-player 整块（按 div 深度配对）。 */
function extractTrayHtml() {
  const src = fs.readFileSync(
    path.join(STATIC, "modals", "player_and_tooltip.html"),
    "utf8",
  );
  const start = src.indexOf('<div id="shadow-player"');
  if (start < 0) throw new Error("player_and_tooltip.html 里找不到 #shadow-player");
  const tagRe = /<div\b|<\/div>/g;
  tagRe.lastIndex = start;
  let depth = 0;
  let m;
  while ((m = tagRe.exec(src))) {
    depth += m[0] === "</div>" ? -1 : 1;
    if (depth === 0) return src.slice(start, m.index + m[0].length);
  }
  throw new Error("#shadow-player 的 </div> 未闭合");
}

function harnessHtml(trayHtml) {
  // 图标 symbol 由 index.html 内联；探针页从独立 sprite 注入，保证截图里按钮不是空白。
  const sprite = fs.readFileSync(path.join(STATIC, "icons", "lucide-sprite.svg"), "utf8");
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>player tray probe</title>
<link rel="stylesheet" href="/css/tokens.css" />
<link rel="stylesheet" href="/style.css" />
<style>body{margin:0;background:var(--paper);}#view-reader{max-width:760px;}</style>
</head>
<body data-probe-started="0">
<div hidden>${sprite}</div>
<main id="view-reader" class="active">
  <p>Der Mann liest jeden Morgen die Zeitung.</p>
</main>
${trayHtml}
<script>
try { localStorage.setItem("delector_voice", "de-DE-ConradNeural"); } catch (e) {}
document.body.setAttribute("data-probe-started", "1");
</script>
<script type="module">
import { ShadowPlayer, playGermanAudio } from "/js/player.js";

const checks = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail });
const tick = (ms) => new Promise((r) => setTimeout(r, ms || 60));
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const rect = (el) => {
  const r = el.getBoundingClientRect();
  return {
    top: +r.top.toFixed(1),
    bottom: +r.bottom.toFixed(1),
    left: +r.left.toFixed(1),
    right: +r.right.toFixed(1),
    w: +r.width.toFixed(1),
    h: +r.height.toFixed(1),
  };
};

async function run() {
  window.ShadowPlayer = ShadowPlayer;
  ShadowPlayer.init();
  document.getElementById("shadow-player").classList.remove("hidden");
  await tick(120);

  // 0) 初始化时从 localStorage 恢复音色：折叠标签与菜单选中态必须同时恢复
  ShadowPlayer.toggleVoiceMenu();
  await tick();
  const restored = {
    label: $("#voice-current-label").textContent.trim(),
    checked: $$("#voice-menu [aria-checked='true']").map((r) => r.dataset.voice),
  };
  ShadowPlayer.closeVoiceMenu();
  check(
    "voice:restores-from-storage",
    restored.label === "男声 · Conrad" &&
      restored.checked.length === 1 &&
      restored.checked[0] === "de-DE-ConradNeural",
    restored,
  );

  // 1) 4 个音色可达 + aria-checked 唯一 + 每行 >=44px
  ShadowPlayer.setVoice("de-DE-KatjaNeural");
  ShadowPlayer.toggleVoiceMenu();
  await tick();
  const voice = {
    count: $$("#voice-menu [role='radio']").length,
    checked: $$("#voice-menu [role='radio'][aria-checked='true']").length,
    labels: $$("#voice-menu [role='radio']").map(
      (r) => (r.querySelector(".vo-name")?.textContent.trim() || "") + "/" +
        (r.querySelector(".vo-meta")?.textContent.trim() || ""),
    ),
    heights: $$("#voice-menu [role='radio']").map((r) => Math.round(r.getBoundingClientRect().height)),
    menuOpen: !$("#voice-menu").classList.contains("hidden"),
  };
  check("voice:4-reachable", voice.count === 4, voice.labels);
  check("voice:aria-checked-unique", voice.checked === 1, "checked=" + voice.checked);
  check("voice:rows>=44px", voice.heights.every((h) => h >= 44), voice.heights);
  check("voice:menu-opens", voice.menuOpen, voice.menuOpen);

  // 2) 折叠态回显当前音色；切到 Killian 后必须同步
  ShadowPlayer.setVoice("de-DE-KillianNeural");
  const collapsed = {
    label: $("#voice-current-label").textContent.trim(),
    checked: $$("#voice-menu [aria-checked='true']").map((r) => r.dataset.voice),
    expanded: $("#voice-current-btn").getAttribute("aria-expanded"),
    menuHidden: $("#voice-menu").classList.contains("hidden"),
  };
  check("voice:collapsed-label", collapsed.label === "男声 · Killian", collapsed.label);
  check(
    "voice:selection-syncs",
    collapsed.checked.length === 1 && collapsed.checked[0] === "de-DE-KillianNeural",
    collapsed.checked,
  );
  check("voice:menu-closed-after-pick", collapsed.expanded === "false" && collapsed.menuHidden, collapsed);

  // 3) 倍速显示值与 data-speed 一致
  const speeds = $$(".speed-step-btn").map((b) => ({
    data: parseFloat(b.dataset.speed),
    text: b.textContent.trim(),
    shown: parseFloat(b.textContent.trim()),
    w: Math.round(b.getBoundingClientRect().width),
    h: Math.round(b.getBoundingClientRect().height),
  }));
  const speedMismatch = speeds.filter((s) => s.data !== s.shown);
  check(
    "speed:label-matches-data-speed",
    speeds.length === 4 && speedMismatch.length === 0,
    speedMismatch.length ? speedMismatch : speeds.map((s) => s.text + "=" + s.data),
  );

  // 4a) 音色不生效时必须可见提示（走真实 Android 原生桥分支）
  window.AndroidNativeTTS = { speak: () => true };
  await playGermanAudio("Hallo");
  const note = $("#player-voice-note");
  const noteRect = rect(note);
  check(
    "voice:unavailable-notice-visible",
    !note.classList.contains("hidden") &&
      noteRect.h > 0 &&
      note.textContent.trim().includes("当前音色不可用"),
    {
      hidden: note.classList.contains("hidden"),
      text: note.textContent.trim(),
      w: noteRect.w,
      h: noteRect.h,
    },
  );

  // 4b) 状态行不是 0×0，且能承载「语音引擎不可用」
  ShadowPlayer.speakFailed({ text: "x" });
  const line = $("#player-status");
  const lineText = $("#player-status-text");
  const lineRect = rect(line);
  const textRect = rect(lineText);
  check(
    "status:visible-and-reads-engine-failure",
    lineRect.w > 0 &&
      lineRect.h > 0 &&
      lineText.textContent.trim() === "语音引擎不可用" &&
      lineText.classList.contains("is-error"),
    {
      lineW: lineRect.w,
      lineH: lineRect.h,
      textW: textRect.w,
      textH: textRect.h,
      content: lineText.textContent.trim(),
      error: lineText.classList.contains("is-error"),
    },
  );

  // 5) 360×800 布局：无横向溢出；传输与倍速同排；音色与模式同排
  const tray = $("#shadow-player");
  const controls = $$(".player-btn, .voice-current-btn, .mode-btn, .speed-step-btn")
    .map((el) => ({ cls: el.className, text: el.textContent.trim(), ...rect(el) }));
  const leftRect = rect($(".player-left"));
  const speedRect = rect($(".speed-pill"));
  const voiceRect = rect($(".voice-pill"));
  const modesRect = rect($(".player-mode-group"));
  const layout = {
    innerWidth,
    innerHeight,
    docScrollW: document.documentElement.scrollWidth,
    tray: {
      ...rect(tray),
      scrollW: tray.scrollWidth,
      clientW: tray.clientWidth,
      padding: getComputedStyle(tray).padding,
    },
    overflow: controls.filter((c) => c.right > innerWidth + 0.5 || c.left < -0.5),
    transportSpeedSameRow:
      Math.abs((leftRect.top + leftRect.bottom) / 2 - (speedRect.top + speedRect.bottom) / 2) <= 1.5,
    voiceModeSameRow:
      Math.abs((voiceRect.top + voiceRect.bottom) / 2 - (modesRect.top + modesRect.bottom) / 2) <= 1.5,
  };
  check(
    "layout:360-no-horizontal-overflow",
    layout.innerWidth === 360 &&
      layout.docScrollW <= 360 &&
      layout.tray.scrollW <= layout.tray.clientW + 1 &&
      layout.overflow.length === 0,
    { docScrollW: layout.docScrollW, tray: layout.tray, overflow: layout.overflow },
  );
  check("layout:transport-and-speed-same-row", layout.transportSpeedSameRow, {
    transportSpeedSameRow: layout.transportSpeedSameRow,
  });
  check("layout:voice-and-modes-same-row", layout.voiceModeSameRow, {
    voiceModeSameRow: layout.voiceModeSameRow,
  });

  const failures = checks.filter((c) => !c.ok).length;
  const payload = { failures, total: checks.length, cases: checks };
  document.body.setAttribute("data-probe", encodeURIComponent(JSON.stringify(payload)));
}

run().catch((err) => {
  document.body.setAttribute(
    "data-probe-error",
    encodeURIComponent(String((err && err.stack) || err)),
  );
});
</script>
</body>
</html>`;
}

/**
 * 外层舞台：Windows headless 会把窗口宽度钳到 ~496px，`--window-size=360` 拿不到
 * 360px 视口。改用 360×800 的 iframe 承载 harness，内层媒体查询 / 布局都以 iframe
 * 视口为准；外层只负责把结果属性搬上来，供 `--dump-dom` 读取。
 */
function stageHtml() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>player tray probe stage</title>
<style>html,body{margin:0;padding:0;background:#fff}iframe{display:block;width:360px;height:800px;border:0}</style>
</head>
<body data-stage="1">
<iframe id="stage" src="/harness.html" width="360" height="800" scrolling="no"></iframe>
<script>
var stage = document.getElementById("stage");
var timer = setInterval(function () {
  var body = null;
  try { body = stage.contentDocument && stage.contentDocument.body; } catch (e) { body = null; }
  if (!body) return;
  var err = body.getAttribute("data-probe-error");
  var ok = body.getAttribute("data-probe");
  if (err) {
    document.body.setAttribute("data-probe-error", err);
    clearInterval(timer);
  } else if (ok) {
    document.body.setAttribute("data-probe", ok);
    clearInterval(timer);
  }
}, 50);
</script>
</body>
</html>`;
}

function startServer(trayHtml) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/harness.html") {
      res.writeHead(200, { "Content-Type": MIME[".html"] });
      res.end(harnessHtml(trayHtml));
      return;
    }
    if (url.pathname === "/stage.html") {
      res.writeHead(200, { "Content-Type": MIME[".html"] });
      res.end(stageHtml());
      return;
    }
    const rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    const file = path.resolve(STATIC, rel);
    if (!file.startsWith(STATIC + path.sep) || !fs.existsSync(file)) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function runBrowser(browser, url, extraArgs) {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "delector-tray-probe-"));
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${userDataDir}`,
    "--window-size=420,880",
    "--virtual-time-budget=6000",
    "--dump-dom",
    ...extraArgs,
    url,
  ];
  if (process.platform === "linux") args.unshift("--no-sandbox", "--disable-dev-shm-usage");

  // 必须异步 spawn：spawnSync 会阻塞事件循环，本地静态服务无法响应浏览器请求。
  return new Promise((resolve) => {
    const child = spawn(browser, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (status) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        fs.rmSync(userDataDir, { recursive: true, force: true });
      } catch {
        /* 浏览器可能仍持有目录句柄：清理失败不掩盖探针结论 */
      }
      resolve({ status, stdout, stderr });
    };
    const timer = setTimeout(() => {
      child.kill();
      stderr += "\n[probe] 浏览器 120s 未退出，已强制结束";
      finish(-1);
    }, 120000);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (err) => {
      stderr += String(err);
      finish(-1);
    });
    child.on("close", (code) => finish(code));
  });
}

function readProbePayload(dom) {
  const started = /data-stage="1"/.test(dom);
  if (!started) throw new Error("stage 页面没有解析（data-stage 未置位）");
  const errMatch = dom.match(/data-probe-error="([^"]*)"/);
  if (errMatch) throw new Error("harness 自检异常：" + decodeURIComponent(errMatch[1]));
  const match = dom.match(/data-probe="([^"]+)"/);
  if (!match) throw new Error("harness 没有产出 data-probe 结果（自检可能未跑完）");
  return JSON.parse(decodeURIComponent(match[1]));
}

async function main() {
  const browser = findBrowser();
  const trayHtml = extractTrayHtml();
  const server = await startServer(trayHtml);
  const url = `http://127.0.0.1:${server.address().port}/stage.html`;
  let result;
  try {
    const first = await runBrowser(browser, url, []);
    if (first.status !== 0) {
      throw new Error(
        `浏览器退出码 ${first.status}\nstderr(前 800 字):\n${(first.stderr || "").slice(0, 800)}`,
      );
    }
    result = readProbePayload(first.stdout || "");

    // 人类可读模式顺手留一张 360×800 证据截图；CI 的 --json 模式不写文件。
    if (!JSON_MODE) {
      fs.mkdirSync(SHOT_DIR, { recursive: true });
      await runBrowser(browser, url, [
        `--screenshot=${path.join(SHOT_DIR, "tray-360x800.png")}`,
        "--virtual-time-budget=2000",
      ]);
    }
  } finally {
    server.close();
  }

  const failures = result.cases.filter((c) => !c.ok);
  if (JSON_MODE) {
    process.stdout.write(
      JSON.stringify({ failures: failures.length, total: result.total, cases: result.cases }, null, 2) + "\n",
    );
  } else {
    for (const c of result.cases) {
      const flag = c.ok ? "PASS" : "FAIL";
      process.stdout.write(`[${flag}] ${c.name}${c.ok ? "" : " :: " + JSON.stringify(c.detail)}\n`);
    }
    process.stdout.write(
      `\n${result.total - failures.length}/${result.total} passed；截图 _artifacts/2026-11-07-player-tray-shots/tray-360x800.png\n`,
    );
  }
  process.exit(failures.length ? 1 : 0);
}

main().catch((err) => {
  process.stderr.write(`[probe] ${err.stack || err.message}\n`);
  process.exit(1);
});
