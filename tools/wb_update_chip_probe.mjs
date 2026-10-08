/**
 * wb_update_chip_probe.mjs —— 顶栏版本更新 chip 行为级自检探针
 * （feature · Task 5 · 探针驱动的单一 TDD 对）
 *
 * 背景：static/js/update.js 的 initUpdateCheck 是顶栏更新 chip 的**唯一驱动源**。
 * 静态正则只能证明「源码里写着 esc( / has_update」，证明不了本功能最容易回归的那条
 * 红线——「无新版 / 拿不准(null) / 请求失败」时，真的一动 DOM 都不动。顶栏那句
 * "System · vX.Y.Z" 是用户判断「前端资源刷没刷新」的自证指标，一旦被更新状态污染，
 * 就会重演 v4.4.5「修好的链路看起来像没生效」的旧事故。
 *
 * 本探针从**真实源文件**按括号配对整段切出实现（core.js 的 esc；update.js 的
 * initUpdateCheck），丢进 node:vm 真跑；只提供最小 DOM 桩与合成响应夹具，并注入
 * 假 fetch / 同步 setTimeout，以确定性复现四种响应路径（有新版 / 已最新 / 拿不准 /
 * 抛异常），外加 XSS 与手动检查入口场景。
 *
 * 硬约束（同 wb_search_probe.mjs）：探针里**不得重抄一份被测实现**；
 * 一切被测逻辑均来自源文件切片。
 *
 * fixture 形状：键集 MUST 等于端点的 7 键契约（delector/routes/update.py），
 * 由 fixture_shape_matches_contract 场景显式比对——形状不符会恒绿漏检
 * （vault: POST-MORTEM-V5.7.3-FIXTURE-SHAPE-MISMATCH）。
 *
 * 用法：
 *   node tools/wb_update_chip_probe.mjs --json
 *   --json 时 stdout 仅输出**标准契约**（精确三键，供 pytest 消费）：
 *     {"failures": <int>, "total": <int>, "cases": [{"name": <str>, "ok": <bool>}]}
 *   人类模式打印 PASS/FAIL 摘要并据 failures 设 process.exitCode。
 *   --json 模式始终退出码 0（裁决交给消费方读 failures）。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const UPDATE_JS = path.join(ROOT, "static", "js", "update.js");
const CORE_JS = path.join(ROOT, "static", "js", "core.js");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

/* 端点契约：恰 7 键（delector/routes/update.py 的 _build_success/_build_failure）。 */
const ENDPOINT_KEYS = [
  "current", "latest", "has_update", "page_url", "checked_at", "cached", "error_reason",
];

/* ---------------------------------------------------------------------------
 * 1. 源码切片：按括号配对抽取完整函数体（跳过字符串、注释与正则字面量）
 *    esc 含正则字面量 /"/g 与 /'/g，朴素括号配对会把正则里的引号误当字符串起始，
 *    故 matchBracket 需识别正则字面量（依据前一个有意义字符判定 `/` 是除号还是正则）。
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function regexAllowed(prev) {
  if (prev == null) return true;
  return !/[A-Za-z0-9_$)\]"'`]/.test(prev);
}

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号（${src[openIdx]}）`);
  const stack = [src[openIdx]];
  let i = openIdx + 1;
  let prev = src[openIdx];
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") { prev = c; i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      i++;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === quote) break;
        i++;
      }
      i++;
      prev = quote;
      continue;
    }
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
    if (c === "/" && regexAllowed(prev)) {
      i++;
      let inClass = false;
      while (i < src.length) {
        const d = src[i];
        if (d === "\\") { i += 2; continue; }
        if (d === "[") { inClass = true; i++; continue; }
        if (d === "]") { inClass = false; i++; continue; }
        if (d === "/" && !inClass) break;
        if (d === "\n") break; // 未闭合（防御）：退化为普通字符继续
        i++;
      }
      i++;
      while (i < src.length && /[a-z]/.test(src[i])) i++;
      prev = "x";
      continue;
    }
    if (OPEN[c]) { stack.push(c); i++; prev = c; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i++;
      prev = c;
      continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  throw new Error(`matchBracket: 从 ${openIdx} 起找不到配对闭括号`);
}

/** 抽取 `[export] [async] function NAME(...) { ... }`（去掉 export 前缀）。 */
function extractFn(src, name) {
  const anchor = new RegExp(`^(?:export\\s+)?(?:async\\s+)?function\\s+${name}\\s*\\(`, "m");
  const m = anchor.exec(src);
  if (!m) throw new Error(`源文件里找不到函数 ${name}`);
  const parenOpen = src.indexOf("(", m.index);
  const parenClose = matchBracket(src, parenOpen);
  const braceOpen = src.indexOf("{", parenClose);
  const braceClose = matchBracket(src, braceOpen);
  return src.slice(m.index, braceClose + 1).replace(/^export\s+/, "");
}

/* 切片失败（例如 update.js 尚未创建）不抛到顶层：改为吐一条失败 case 的标准 JSON，
 * 这样 contract 探针在 RED 阶段仍能判"形状合规"，而行为裁决由 wrapper 的
 * failures==0 兜住——RED 因此是**干净的断言失败**，不是进程崩溃。 */
let SLICES = null;
let sliceError = null;
try {
  const coreSrc = fs.readFileSync(CORE_JS, "utf8");
  const updateSrc = fs.readFileSync(UPDATE_JS, "utf8");
  const esc = extractFn(coreSrc, "esc");
  const initUpdateCheck = extractFn(updateSrc, "initUpdateCheck");
  // 防死测：切片必须是真实现，否则实现回退了探针照样绿。
  if (!esc || esc.length < 20 || !/replace\(\/&\/g/.test(esc) || !/replace\(\/</.test(esc)) {
    throw new Error("esc 切片异常（缺 &/< 替换）：切歪或实现回退了");
  }
  if (!initUpdateCheck || initUpdateCheck.length < 100 || !/has_update/.test(initUpdateCheck)) {
    throw new Error("initUpdateCheck 切片异常（缺 has_update 判定）：切歪或实现回退了");
  }
  SLICES = { esc, initUpdateCheck };
  log(`[slice] esc(${esc.length}) initUpdateCheck(${initUpdateCheck.length})`);
} catch (e) {
  sliceError = e;
}

/* ---------------------------------------------------------------------------
 * 2. 最小 DOM 桩：记录 innerHTML / textContent / hidden 写值与事件处理器
 * ------------------------------------------------------------------------ */
function makeEl(id) {
  const el = {
    id,
    innerHTML: "",
    textContent: "",
    hidden: false,
    dataset: {},
    attributes: {},
    _handlers: {},
    addEventListener(type, fn) { (el._handlers[type] = el._handlers[type] || []).push(fn); },
    removeEventListener(type, fn) {
      const arr = el._handlers[type] || [];
      const idx = arr.indexOf(fn);
      if (idx >= 0) arr.splice(idx, 1);
    },
    dispatch(type) { (el._handlers[type] || []).slice().forEach((fn) => fn()); },
    setAttribute(k, v) { el.attributes[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(el.attributes, k) ? el.attributes[k] : null; },
  };
  return el;
}

const vmConsole = { log() {}, warn() {}, error() {}, info() {} };

/** 组装一个干净沙箱：DOM 桩 + 计时器队列 + 切片源码，返回驱动句柄。 */
function makeSandbox(fetchImpl) {
  const els = new Map();
  const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
  const chip = getEl("update-chip");
  chip.hidden = true; // 与 index.html 的 hidden 属性一致（无新版时零可见变化）
  const trigger = getEl("topbar-system");
  // 按 index.html 真实结构补桩：<span class="right" id="topbar-system">…System · vX.Y.Z</span>。
  // 这句「System · vX.Y.Z」是「前端资源刷没刷新」的唯一肉眼自证指标（v4.4.5 漏 bump 出过事故），
  // 运行期快照要拿它做前后比对，故桩内必须有真实初值，绝不能是空串（空串会让污染仅表现为
  // 「从空变有」的弱信号，且与真实顶栏状态不符）。
  trigger.textContent = "System · v5.16.0";

  const timers = [];
  const setTimeoutFn = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };

  const documentStub = {
    getElementById: getEl,
    createElement: (tag) => makeEl(tag),
    querySelectorAll: () => [],
  };
  const ctx = vm.createContext({ console: vmConsole, document: documentStub });
  vm.runInContext(SLICES.esc + "\n" + SLICES.initUpdateCheck + "\n", ctx, { filename: "update-slices.js" });

  return {
    ctx,
    chip,
    trigger,
    start() {
      ctx.__opts = { fetchImpl, setTimeoutFn, delayMs: 0 };
      vm.runInContext("initUpdateCheck(__opts)", ctx);
    },
    fireTimers() { timers.splice(0).forEach((t) => t.fn()); },
    click() { trigger.dispatch("click"); },
  };
}

/* ---------------------------------------------------------------------------
 * 3. 夹具与断言工具
 * ------------------------------------------------------------------------ */
const okResp = (data) => ({ ok: true, status: 200, json: () => Promise.resolve(data) });

function newerResponse() {
  return {
    current: "5.16.0",
    latest: "5.17.0",
    has_update: true,
    page_url: "https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0",
    checked_at: 1767225600,
    cached: false,
    error_reason: null,
  };
}
function upToDateResponse() {
  return {
    current: "5.16.0",
    latest: "5.16.0",
    has_update: false,
    page_url: null,
    checked_at: 1767225600,
    cached: true,
    error_reason: null,
  };
}
function failedResponse() {
  return {
    current: "5.16.0",
    latest: null,
    has_update: null,
    page_url: null,
    checked_at: 1767225600,
    cached: false,
    error_reason: "network",
  };
}

const sameKeySet = (obj, keys) => {
  const a = Object.keys(obj).sort().join(",");
  const b = keys.slice().sort().join(",");
  return a === b;
};
/** 从 innerHTML 里取某属性值（chip 用 innerHTML 构建 <a>，故断言锚在属性上）。 */
function attr(html, name) {
  const m = new RegExp(name + '="([^"]*)"').exec(html);
  return m ? m[1] : null;
}
/** 「可见变化」快照：silent 场景断言它前后一字不差。
 *
 * 除 #update-chip 的 hidden/innerHTML/textContent 外，MUST 同时记录 #topbar-system 的
 * textContent。顶栏那句「System · vX.Y.Z」是「前端资源刷没刷新」的唯一肉眼自证指标，
 * 更新状态只由本模块的 chip 承载，一旦在**运行期**污染它，就会重演 v4.4.5「修好的链路
 * 看起来像没生效」的事故。
 *
 * 为何非纳入不可：wrapper 的 test_topbar_version_self_attest_string_intact 只对
 * static/index.html 做**源码静态断言**，拦得住「有人把 chip 插进版本号与其 </span> 之间」，
 * 却拦不住「update.js 在运行期往 #topbar-system 追加/改写文本」——那种污染下，若只看
 * chip 快照，静默场景仍会全绿而红线已被打破却无人报警。故本快照是该红线的**运行期**守卫，
 * 所有 silent 路径（以及「有新版」路径，见 chip_shown_when_newer）都必须逐字比对 sys 字段。
 */
const snap = (chip, system) => ({
  h: chip.hidden,
  html: chip.innerHTML,
  text: chip.textContent,
  sys: system ? system.textContent : null,
});
const snapKey = (s) => JSON.stringify(s);

const flush = () => new Promise((resolve) => setImmediate(resolve));

/** 自动路径：建沙箱 → 触发一次性延迟检查 → 冲刷微任务，返回句柄与事前快照。 */
async function autoRun(fetchImpl) {
  const sb = makeSandbox(fetchImpl);
  const before = snap(sb.chip, sb.trigger);
  sb.start();
  sb.fireTimers();
  await flush();
  return { sb, before };
}

/* ---------------------------------------------------------------------------
 * 4. 场景断言与汇总
 * ------------------------------------------------------------------------ */
const cases = [];
let failCount = 0;
function check(name, ok, detail) {
  const passed = !!ok;
  cases.push({ name, ok: passed, detail: detail == null ? "" : String(detail) });
  if (!passed) failCount++;
  log(passed ? `PASS  ${name}` : `FAIL  ${name}${detail ? "  —  " + detail : ""}`);
}

const unhandled = [];
process.on("unhandledRejection", (r) => { unhandled.push(r); });

if (sliceError) {
  check("slices_available", false, "切不出被测实现：" + (sliceError && sliceError.message));
} else {
  /* 场景 0：fixture 形状 == 端点 7 键契约（形状不符 ⇒ 恒绿漏检）。 */
  check(
    "fixture_shape_matches_contract",
    sameKeySet(newerResponse(), ENDPOINT_KEYS) &&
      sameKeySet(upToDateResponse(), ENDPOINT_KEYS) &&
      sameKeySet(failedResponse(), ENDPOINT_KEYS),
    "fixture 键集：" + Object.keys(newerResponse()).sort().join(","),
  );

  /* 场景 1：落后 → chip 可见、文案含版本、href === page_url、target/rel 齐全；
   * 且顶栏自证串（#topbar-system）同样不得被污染——即便「有新版」，更新状态也只由 chip
   * 承载，绝不改写 System · vX.Y.Z（否则 v4.4.5 的「刷新自证」红线被运行期打破）。 */
  {
    const data = newerResponse();
    const { sb, before } = await autoRun(() => Promise.resolve(okResp(data)));
    const html = sb.chip.innerHTML;
    check(
      "chip_shown_when_newer",
      sb.chip.hidden === false &&
        before.sys === sb.trigger.textContent &&
        html.indexOf("v5.17.0") !== -1 &&
        attr(html, "href") === data.page_url &&
        html.indexOf('target="_blank"') !== -1 &&
        html.indexOf('rel="noopener noreferrer"') !== -1,
      "hidden=" + sb.chip.hidden + " sys=" + sb.trigger.textContent +
        " href=" + attr(html, "href") + " html=" + html,
    );
  }

  /* 场景 2：已最新 → 零可见变化（chip 隐藏且不写任何文本；顶栏自证串亦逐字不动）。 */
  {
    const { sb, before } = await autoRun(() => Promise.resolve(okResp(upToDateResponse())));
    check(
      "silent_when_up_to_date",
      snapKey(snap(sb.chip, sb.trigger)) === snapKey(before),
      "before=" + snapKey(before) + " after=" + snapKey(snap(sb.chip, sb.trigger)),
    );
  }

  /* 场景 3：拿不准（has_update=null + error_reason=network）→ 零可见变化，不报错不成 toast；
   * 顶栏自证串亦逐字不动。 */
  {
    const { sb, before } = await autoRun(() => Promise.resolve(okResp(failedResponse())));
    check(
      "silent_when_check_failed",
      snapKey(snap(sb.chip, sb.trigger)) === snapKey(before),
      "before=" + snapKey(before) + " after=" + snapKey(snap(sb.chip, sb.trigger)),
    );
  }

  /* 场景 4：fetch 抛异常 → 零可见变化（同理，不是"没崩"；顶栏自证串亦逐字不动）。 */
  {
    const { sb, before } = await autoRun(() => { throw new Error("fetch failed"); });
    check(
      "silent_when_fetch_throws",
      snapKey(snap(sb.chip, sb.trigger)) === snapKey(before),
      "before=" + snapKey(before) + " after=" + snapKey(snap(sb.chip, sb.trigger)),
    );
  }

  /* 场景 5：非 2xx（HTTP 403）→ 零可见变化；顶栏自证串亦逐字不动。 */
  {
    const { sb, before } = await autoRun(() => Promise.resolve({ ok: false, status: 403, json: () => Promise.resolve({}) }));
    check(
      "silent_when_non_2xx",
      snapKey(snap(sb.chip, sb.trigger)) === snapKey(before),
      "before=" + snapKey(before) + " after=" + snapKey(snap(sb.chip, sb.trigger)),
    );
  }

  /* 场景 6：XSS —— latest 含可执行标签时，输出里不得留下可执行标签。 */
  {
    const data = newerResponse();
    data.latest = '<img src=x onerror="alert(1)">';
    const { sb } = await autoRun(() => Promise.resolve(okResp(data)));
    const html = sb.chip.innerHTML;
    check(
      "xss_latest_escaped",
      html.indexOf("&lt;img") !== -1 && !/<img/i.test(html) && !/<script/i.test(html),
      "html=" + html,
    );
  }

  /* 场景 7：XSS —— page_url 含引号越狱企图时，href 属性不得被撑破。 */
  {
    const data = newerResponse();
    data.page_url = 'https://evil.example/x" onmouseover="alert(1)';
    const { sb } = await autoRun(() => Promise.resolve(okResp(data)));
    const html = sb.chip.innerHTML;
    check(
      "xss_page_url_escaped",
      html.indexOf("&quot;") !== -1 && html.indexOf('onmouseover="') === -1,
      "html=" + html,
    );
  }

  /* 场景 8：手动检查「已最新」→ 先短暂显示，再被 ~3s 计时器清空。 */
  {
    const sb = makeSandbox(() => Promise.resolve(okResp(upToDateResponse())));
    sb.start();
    sb.fireTimers();
    await flush(); // 自动：静默
    sb.click();
    await flush(); // 手动：显示「已是最新」
    const shown = sb.chip.hidden === false && sb.chip.innerHTML.indexOf("已是最新") !== -1;
    sb.fireTimers();
    await flush(); // ~3s 后清空
    const cleared = sb.chip.hidden === true && sb.chip.innerHTML === "";
    check("manual_click_shows_latest", shown && cleared, "shown=" + shown + " cleared=" + cleared);
  }

  /* 场景 9：手动检查失败 → 短暂显示**人话**，禁止直出 HTTP 403 / fetch failed / TypeError。 */
  {
    const sb = makeSandbox(() => Promise.resolve(okResp(failedResponse())));
    sb.start();
    sb.fireTimers();
    await flush();
    sb.click();
    await flush();
    const shownHtml = sb.chip.innerHTML;
    const shown = sb.chip.hidden === false;
    sb.fireTimers();
    await flush();
    const cleared = sb.chip.hidden === true && sb.chip.innerHTML === "";
    const human = shownHtml.indexOf("连不上 GitHub") !== -1;
    const noRaw = !/HTTP \d|fetch failed|TypeError/.test(shownHtml);
    check("manual_click_humanizes_error", shown && human && noRaw && cleared, "shownHtml=" + shownHtml);
  }

  /* 兜底：任何路径都不得产生未处理的 promise 拒绝。 */
  await flush();
  await flush();
  check("no_unhandled_rejection", unhandled.length === 0, "unhandled=" + unhandled.length);
}

/* ---------------------------------------------------------------------------
 * 5. 输出
 * ------------------------------------------------------------------------ */
if (JSON_MODE) {
  process.stdout.write(
    JSON.stringify({
      failures: failCount,
      total: cases.length,
      cases: cases.map((c) => ({ name: c.name, ok: c.ok })),
    }),
  );
} else {
  console.log("");
  if (failCount > 0) {
    console.log(`FAIL 汇总：${failCount} 个场景未通过`);
    process.exitCode = 1;
  } else {
    console.log(`ALL PASS：顶栏更新 chip（4 响应路径 + 零变化红线 + XSS + 手动检查，共 ${cases.length} 项断言）自检通过`);
  }
}
