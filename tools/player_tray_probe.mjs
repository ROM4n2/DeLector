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
 * 用法：
 *   node tools/player_tray_probe.mjs            # 人类可读
 *   node tools/player_tray_probe.mjs --json     # stdout 只输出 JSON
 * 任一断言失败退出码 1。
 */
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const STATIC = path.join(ROOT, "static");
const JSON_MODE = process.argv.includes("--json");
const EDGE =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
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

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail });
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
<body>
<div hidden>${sprite}</div>
<main id="view-reader" class="active">
  <p>Der Mann liest jeden Morgen die Zeitung.</p>
</main>
${trayHtml}
<script type="module">
import { ShadowPlayer, playGermanAudio } from "/js/player.js";
window.ShadowPlayer = ShadowPlayer;
window.playGermanAudio = playGermanAudio;
ShadowPlayer.init();
document.getElementById("shadow-player").classList.remove("hidden");
window.__playerReady = true;
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

function launchEdge(userDataDir) {
  const child = spawn(
    EDGE,
    [
      "--headless=new",
      "--remote-debugging-port=0",
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "--hide-scrollbars",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  const wsUrl = new Promise((resolve, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(new Error("Edge 未输出 DevTools 地址")), 20000);
    child.stderr.on("data", (chunk) => {
      buf += chunk.toString();
      const m = buf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
    });
    child.on("exit", (code) => reject(new Error(`Edge 提前退出（${code}）`)));
  });
  return { child, wsUrl };
}

async function waitForPageTarget(port) {
  for (let i = 0; i < 100; i++) {
    try {
      const resp = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await resp.json();
      const page = list.find((t) => t.type === "page");
      if (page) return page;
    } catch {
      /* 端口尚未就绪 */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("等不到 Edge page target");
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    };
  }

  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  async eval(expression) {
    const r = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description || "Runtime.evaluate 异常");
    }
    return r.result.value;
  }
}

async function main() {
  const trayHtml = extractTrayHtml();
  const server = await startServer(trayHtml);
  const port = server.address().port;
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "delector-tray-probe-"));
  const { child, wsUrl } = launchEdge(userDataDir);
  let cdp;
  try {
    const browserWs = await wsUrl;
    const browserPort = Number(new URL(browserWs).port);
    const page = await waitForPageTarget(browserPort);
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.onopen = resolve;
      ws.onerror = reject;
    });
    cdp = new Cdp(ws);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 360,
      height: 800,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await cdp.send("Page.navigate", { url: `http://127.0.0.1:${port}/harness.html` });

    let ready = false;
    for (let i = 0; i < 100; i++) {
      try {
        ready = await cdp.eval("window.__playerReady === true");
      } catch {
        ready = false;
      }
      if (ready) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!ready) {
      const errors = cdp.events
        .filter((e) => e.method === "Runtime.exceptionThrown")
        .map((e) => e.params.exceptionDetails?.exception?.description);
      throw new Error(`harness 未就绪；页面异常：${errors.join(" | ") || "无"}`);
    }
    await new Promise((r) => setTimeout(r, 250));

    // 0) 刷新后从 localStorage 恢复音色：折叠标签与菜单选中态必须同时恢复
    await cdp.eval(
      "localStorage.setItem('delector_voice','de-DE-ConradNeural'); location.reload(); true",
    );
    ready = false;
    for (let i = 0; i < 100; i++) {
      try {
        ready = await cdp.eval("window.__playerReady === true");
      } catch {
        ready = false;
      }
      if (ready) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!ready) throw new Error("reload 后 harness 未就绪");
    const restored = await cdp.eval(`(async () => {
      window.ShadowPlayer.toggleVoiceMenu();
      await new Promise((r) => setTimeout(r, 50));
      const label = document.getElementById('voice-current-label').textContent.trim();
      const checked = [...document.querySelectorAll('#voice-menu [aria-checked="true"]')]
        .map((r) => r.dataset.voice);
      window.ShadowPlayer.closeVoiceMenu();
      return { label, checked };
    })()`);
    check(
      "voice:restores-from-storage",
      restored.label === "男声 · Conrad" &&
        restored.checked.length === 1 &&
        restored.checked[0] === "de-DE-ConradNeural",
      restored,
    );

    // 1) 4 个音色可达 + aria-checked 唯一 + 每行 ≥44px
    await cdp.eval("window.ShadowPlayer.setVoice('de-DE-KatjaNeural')");
    await cdp.eval("window.ShadowPlayer.toggleVoiceMenu()");
    const voice = await cdp.eval(`(() => {
      const radios = [...document.querySelectorAll('#voice-menu [role="radio"]')];
      return {
        count: radios.length,
        checked: radios.filter((r) => r.getAttribute('aria-checked') === 'true').length,
        labels: radios.map((r) => r.querySelector('.vo-name')?.textContent.trim() + '/' +
          r.querySelector('.vo-meta')?.textContent.trim()),
        heights: radios.map((r) => Math.round(r.getBoundingClientRect().height)),
        menuOpen: !document.getElementById('voice-menu').classList.contains('hidden'),
      };
    })()`);
    check("voice:4-reachable", voice.count === 4, voice.labels);
    check("voice:aria-checked-unique", voice.checked === 1, `checked=${voice.checked}`);
    check("voice:rows>=44px", voice.heights.every((h) => h >= 44), voice.heights);
    check("voice:menu-opens", voice.menuOpen, voice.menuOpen);

    // 2) 折叠态回显当前音色；切到 Killian 后必须同步
    const collapsed = await cdp.eval(`(() => {
      window.ShadowPlayer.setVoice('de-DE-KillianNeural');
      const label = document.getElementById('voice-current-label').textContent.trim();
      const checked = [...document.querySelectorAll('#voice-menu [aria-checked="true"]')]
        .map((r) => r.dataset.voice);
      const expanded = document.getElementById('voice-current-btn').getAttribute('aria-expanded');
      return { label, checked, expanded };
    })()`);
    check(
      "voice:collapsed-label",
      collapsed.label === "男声 · Killian",
      collapsed.label,
    );
    check(
      "voice:selection-syncs",
      collapsed.checked.length === 1 && collapsed.checked[0] === "de-DE-KillianNeural",
      collapsed.checked,
    );
    check("voice:menu-closed-after-pick", collapsed.expanded === "false", collapsed.expanded);

    // 3) 倍速显示值与 data-speed 一致
    const speeds = await cdp.eval(`(() => {
      return [...document.querySelectorAll('.speed-step-btn')].map((b) => {
        const r = b.getBoundingClientRect();
        return {
          data: parseFloat(b.dataset.speed),
          text: b.textContent.trim(),
          shown: parseFloat(b.textContent.trim()),
          w: Math.round(r.width),
          h: Math.round(r.height),
        };
      });
    })()`);
    const speedMismatch = speeds.filter((s) => s.data !== s.shown);
    check(
      "speed:label-matches-data-speed",
      speeds.length === 4 && speedMismatch.length === 0,
      speedMismatch.length ? speedMismatch : speeds.map((s) => `${s.text}=${s.data}`),
    );

    // 4a) 音色不生效时必须可见提示（走真实 Android 原生桥分支）
    const notice = await cdp.eval(`(async () => {
      window.AndroidNativeTTS = { speak: () => true };
      await window.playGermanAudio('Hallo');
      const note = document.getElementById('player-voice-note');
      const r = note.getBoundingClientRect();
      return {
        hidden: note.classList.contains('hidden'),
        text: note.textContent.trim(),
        w: Math.round(r.width),
        h: Math.round(r.height),
      };
    })()`);
    check(
      "voice:unavailable-notice-visible",
      !notice.hidden && notice.h > 0 && notice.text.includes("当前音色不可用"),
      notice,
    );

    // 4b) 状态行不是 0×0，且能承载「语音引擎不可用」
    const status = await cdp.eval(`(() => {
      window.ShadowPlayer.speakFailed({ text: 'x' });
      const line = document.getElementById('player-status');
      const text = document.getElementById('player-status-text');
      const lr = line.getBoundingClientRect();
      const tr = text.getBoundingClientRect();
      return {
        lineW: Math.round(lr.width),
        lineH: Math.round(lr.height),
        textW: Math.round(tr.width),
        textH: Math.round(tr.height),
        content: text.textContent.trim(),
        error: text.classList.contains('is-error'),
      };
    })()`);
    check(
      "status:visible-and-reads-engine-failure",
      status.lineW > 0 && status.lineH > 0 && status.content === "语音引擎不可用" && status.error,
      status,
    );

    // 5) 360×800 布局：无横向溢出；传输与倍速同排
    const layout = await cdp.eval(`(() => {
      const tray = document.getElementById('shadow-player');
      const rect = (el) => {
        const r = el.getBoundingClientRect();
        return { top: +r.top.toFixed(1), bottom: +r.bottom.toFixed(1), left: +r.left.toFixed(1), right: +r.right.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) };
      };
      const controls = [...tray.querySelectorAll('.player-btn, .voice-current-btn, .mode-btn, .speed-step-btn')]
        .map((el) => ({ cls: el.className, text: el.textContent.trim(), ...rect(el) }));
      const left = document.querySelector('.player-left').getBoundingClientRect();
      const speed = document.querySelector('.speed-pill').getBoundingClientRect();
      const voice = document.querySelector('.voice-pill').getBoundingClientRect();
      const modes = document.querySelector('.player-mode-group').getBoundingClientRect();
      return {
        innerWidth,
        innerHeight,
        docScrollW: document.documentElement.scrollWidth,
        tray: { ...rect(tray), scrollW: tray.scrollWidth, clientW: tray.clientWidth, padding: getComputedStyle(tray).padding },
        controls,
        overflow: controls.filter((c) => c.right > innerWidth + 0.5 || c.left < -0.5),
        transportSpeedSameRow: Math.abs((left.top + left.bottom) / 2 - (speed.top + speed.bottom) / 2) <= 1.5,
        voiceModeSameRow: Math.abs((voice.top + voice.bottom) / 2 - (modes.top + modes.bottom) / 2) <= 1.5,
      };
    })()`);
    check(
      "layout:360-no-horizontal-overflow",
      layout.innerWidth === 360 &&
        layout.docScrollW <= 360 &&
        layout.tray.scrollW <= layout.tray.clientW + 1 &&
        layout.overflow.length === 0,
      {
        docScrollW: layout.docScrollW,
        tray: layout.tray,
        overflow: layout.overflow,
      },
    );
    check("layout:transport-and-speed-same-row", layout.transportSpeedSameRow, {
      transportSpeedSameRow: layout.transportSpeedSameRow,
    });
    check("layout:voice-and-modes-same-row", layout.voiceModeSameRow, {
      voiceModeSameRow: layout.voiceModeSameRow,
    });

    // 证据截图
    const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    fs.writeFileSync(path.join(SHOT_DIR, "tray-360x800.png"), Buffer.from(shot.data, "base64"));

    ws.close();
  } finally {
    try {
      cdp?.ws.close();
    } catch {
      /* ignore */
    }
    child.kill();
    server.close();
    // Edge 进程可能还持有 user-data-dir 句柄：清理失败不掩盖探针结论。
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }

  const failures = checks.filter((c) => !c.ok);
  const payload = { failures: failures.length, total: checks.length, cases: checks };
  if (JSON_MODE) {
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
  } else {
    for (const c of checks) {
      const flag = c.ok ? "PASS" : "FAIL";
      process.stdout.write(`[${flag}] ${c.name}${c.ok ? "" : " :: " + JSON.stringify(c.detail)}\n`);
    }
    process.stdout.write(
      `\n${checks.length - failures.length}/${checks.length} passed；截图 _artifacts/2026-11-07-player-tray-shots/tray-360x800.png\n`,
    );
  }
  process.exit(failures.length ? 1 : 0);
}

main().catch((err) => {
  process.stderr.write(`[probe] ${err.stack || err.message}\n`);
  process.exit(1);
});
