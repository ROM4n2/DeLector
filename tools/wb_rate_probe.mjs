/**
 * wb_rate_probe.mjs —— 背词工作台 doRate 评分与错词记录行为级动态探针（C7 遗留收口）
 *
 * 为什么需要本探针：
 *   `static/js/wb-rate.js` 的 `doRate(g)` 承担复习卡片的核心回写链路：
 *   - FSRS 评分计算与卡片写盘（fsrsReview / saveCards）；
 *   - 今日学习日志累加（logToday: rv++, nw++, good++/hard++/again++）；
 *   - 错词登记（g===1 时调 addWrong(id, "rv-again")）；
 *   - 翻面/队列边界拦截（!flipped 或 revIdx >= revQueue.length 拦截退出）。
 *   C7 期间只为它提供了「必须住在 wb-rate.js」的静态所有权钉子，
 *   任何评分分支改错（如 good 改成 hard、漏调 addWrong）静态正则完全无法察觉。
 *
 * 探针实现规范（同 wb_queue_probe.mjs / enc_coverage_degraded_probe.mjs）：
 *   - 严禁探针内重抄一份 doRate 实现；必须真实从 `static/js/wb-rate.js` 切出函数体；
 *   - 切片带关键 token 护栏，切歪直接退出码 3；
 *   - 丢入 node:vm 沙箱，在假状态下实跑五组真实行为场景；
 *   - 输出标准三键契约：`{ failures, total, cases: [{name, ok}] }`。
 *
 * 用法：
 *   node tools/wb_rate_probe.mjs            # 人类可读终端输出
 *   node tools/wb_rate_probe.mjs --json     # stdout 只输出标准 JSON（pytest 用）
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const SRC_ROOT = process.env.WB_SRC_ROOT ?? "static";
const SRC_FILES = ["js/wb-rate.js"];

function readSources(names) {
  const parts = names.map((name) => {
    const dir = path.isAbsolute(SRC_ROOT) ? SRC_ROOT : path.join(ROOT, SRC_ROOT);
    const file = path.isAbsolute(name) ? name : path.join(dir, name);
    if (!fs.existsSync(file)) {
      process.stderr.write(`探针源文件不存在：${file}\n`);
      process.exit(3);
    }
    const text = fs.readFileSync(file, "utf8");
    if (!text.length) {
      process.stderr.write(`探针源文件为空：${file}\n`);
      process.exit(3);
    }
    return text;
  });
  return parts.join("\n");
}

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
      const quote = c;
      i++;
      while (i < src.length) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === quote) break;
        i++;
      }
      i++;
      continue;
    }
    if (c === "/" && src[i + 1] === "/") {
      i = src.indexOf("\n", i);
      if (i < 0) break;
      continue;
    }
    if (c === "/" && src[i + 1] === "*") {
      i = src.indexOf("*/", i);
      if (i < 0) break;
      i += 2;
      continue;
    }
    if (OPEN[c]) { stack.push(c); i++; continue; }
    if (CLOSE[c]) {
      if (stack[stack.length - 1] !== CLOSE[c]) throw new Error(`括号不配对于下标 ${i}`);
      stack.pop();
      if (!stack.length) return i;
      i++;
      continue;
    }
    i++;
  }
  throw new Error(`matchBracket: 从 ${openIdx} 起找不到配对闭括号`);
}

function sliceFunction(src, name) {
  const re = new RegExp(`^(?:async\\s+)?function\\s+${name}\\s*\\(`, "m");
  const m = re.exec(src);
  if (!m) {
    process.stderr.write(`在源码中未找到函数 ${name}\n`);
    process.exit(3);
  }
  const parenClose = matchBracket(src, m.index + m[0].length - 1);
  const braceOpen = src.indexOf("{", parenClose);
  if (braceOpen < 0) {
    process.stderr.write(`函数 ${name} 找不到函数体花括号\n`);
    process.exit(3);
  }
  return src.slice(m.index, matchBracket(src, braceOpen) + 1);
}

const rawSource = readSources(SRC_FILES);
const doRateSrc = sliceFunction(rawSource, "doRate");

// 切片护栏：必须包含关键分支 token，防止切歪或切空
const REQUIRED_TOKENS = [
  "t.good++",
  "t.hard++",
  "t.again++",
  'addWrong(id, "rv-again")',
  "fsrsReview",
  "saveCards()",
  "saveLog()",
  "renderReview()",
];
for (const tok of REQUIRED_TOKENS) {
  if (!doRateSrc.includes(tok)) {
    process.stderr.write(`doRate 切片缺少标志 token: ${tok}\n`);
    process.exit(3);
  }
}

const cases = [];
const problems = [];
function record(name, ok, detail) {
  cases.push({ name, ok });
  if (!ok) problems.push(`${name}: ${detail}`);
}

function runScenario(fn) {
  let revQueue = ["word-a", "word-b"];
  let revIdx = 0;
  let flipped = true;
  let ratedCount = 0;
  let queueDay = "2026-10-18";

  const S = {
    cards: {},
    settings: { retention: 0.9 },
  };

  let savedCardsCount = 0;
  function saveCards() { savedCardsCount++; }

  let savedLogCount = 0;
  function saveLog() { savedLogCount++; }

  let renderedHeaderBadgeCount = 0;
  function renderHeaderBadge() { renderedHeaderBadgeCount++; }

  let renderedReviewCount = 0;
  function renderReview() { renderedReviewCount++; }

  const fsrsCalls = [];
  function fsrsReview(card, g, now, ret) {
    fsrsCalls.push({ card, g, now, ret });
    return {
      id: card ? card.id : "mock-card",
      reps: (card && card.reps ? card.reps : 0) + 1,
      grade: g,
    };
  }

  const wrongCalls = [];
  function addWrong(id, tag) {
    wrongCalls.push({ id, tag });
  }

  const todayLog = { rv: 0, nw: 0, good: 0, hard: 0, again: 0 };
  function logToday() { return todayLog; }

  const sandbox = {
    console,
    Date,
    get revQueue() { return revQueue; },
    set revQueue(v) { revQueue = v; },
    get revIdx() { return revIdx; },
    set revIdx(v) { revIdx = v; },
    get flipped() { return flipped; },
    set flipped(v) { flipped = v; },
    get ratedCount() { return ratedCount; },
    set ratedCount(v) { ratedCount = v; },
    get queueDay() { return queueDay; },
    set queueDay(v) { queueDay = v; },
    S,
    fsrsReview,
    saveCards,
    logToday,
    addWrong,
    saveLog,
    renderHeaderBadge,
    renderReview,
  };

  const context = vm.createContext(sandbox);
  vm.runInContext(doRateSrc, context);

  fn({
    setQueue(q) { revQueue = q; },
    setIdx(i) { revIdx = i; },
    setFlipped(f) { flipped = f; },
    setCards(c) { S.cards = c; },
    doRate(g) { vm.runInContext(`doRate(${g})`, context); },
    getState() {
      return {
        revQueue,
        revIdx,
        flipped,
        ratedCount,
        todayLog,
        wrongCalls,
        fsrsCalls,
        savedCardsCount,
        savedLogCount,
        renderedHeaderBadgeCount,
        renderedReviewCount,
        cards: S.cards,
      };
    },
  });
}

/* ══ 1. 评分 3（Good / 良好）══ */
runScenario(({ doRate, getState }) => {
  doRate(3);
  const st = getState();
  const ok = (
    st.todayLog.good === 1 &&
    st.todayLog.hard === 0 &&
    st.todayLog.again === 0 &&
    st.todayLog.rv === 1 &&
    st.todayLog.nw === 1 &&
    st.wrongCalls.length === 0 &&
    st.ratedCount === 1 &&
    st.revIdx === 1 &&
    st.fsrsCalls.length === 1 &&
    st.fsrsCalls[0].g === 3 &&
    st.savedCardsCount === 1 &&
    st.savedLogCount === 1 &&
    st.renderedHeaderBadgeCount === 1 &&
    st.renderedReviewCount === 1
  );
  record("good-grade-3-new-card", ok, `good=3 评分行为异常: ${JSON.stringify(st.todayLog)}`);
});

/* ══ 2. 评分 2（Hard / 困难）：已学卡片复习 ══ */
runScenario(({ setCards, doRate, getState }) => {
  setCards({ "word-a": { id: "word-a", reps: 3 } });
  doRate(2);
  const st = getState();
  const ok = (
    st.todayLog.hard === 1 &&
    st.todayLog.good === 0 &&
    st.todayLog.again === 0 &&
    st.todayLog.rv === 1 &&
    st.todayLog.nw === 0 &&
    st.wrongCalls.length === 0 &&
    st.ratedCount === 1 &&
    st.revIdx === 1 &&
    st.fsrsCalls.length === 1 &&
    st.fsrsCalls[0].g === 2 &&
    st.savedCardsCount === 1
  );
  record("hard-grade-2-reviewed-card", ok, `hard=2 评分行为异常: ${JSON.stringify(st.todayLog)}`);
});

/* ══ 3. 评分 1（Again / 重来）：必须登记错词 ══ */
runScenario(({ setCards, doRate, getState }) => {
  setCards({ "word-a": { id: "word-a", reps: 1 } });
  doRate(1);
  const st = getState();
  const ok = (
    st.todayLog.again === 1 &&
    st.todayLog.good === 0 &&
    st.todayLog.hard === 0 &&
    st.todayLog.rv === 1 &&
    st.todayLog.nw === 0 &&
    st.wrongCalls.length === 1 &&
    st.wrongCalls[0].id === "word-a" &&
    st.wrongCalls[0].tag === "rv-again" &&
    st.ratedCount === 1 &&
    st.revIdx === 1 &&
    st.fsrsCalls.length === 1 &&
    st.fsrsCalls[0].g === 1 &&
    st.savedCardsCount === 1
  );
  record("again-grade-1-records-wrong", ok, `again=1 错题记录行为异常: wrong=${JSON.stringify(st.wrongCalls)}`);
});

/* ══ 4. 边界拦截：未翻面点击评分被忽略 ══ */
runScenario(({ setFlipped, doRate, getState }) => {
  setFlipped(false);
  doRate(3);
  const st = getState();
  const ok = (
    st.revIdx === 0 &&
    st.ratedCount === 0 &&
    st.todayLog.rv === 0 &&
    st.todayLog.good === 0 &&
    st.fsrsCalls.length === 0 &&
    st.savedCardsCount === 0
  );
  record("unflipped-guard-ignores-rating", ok, `未翻面时 doRate 应早退忽略，实际: idx=${st.revIdx}`);
});

/* ══ 5. 边界拦截：队列越界评分被忽略 ══ */
runScenario(({ setIdx, setQueue, doRate, getState }) => {
  setQueue(["word-a"]);
  setIdx(1);
  doRate(3);
  const st = getState();
  const ok = (
    st.revIdx === 1 &&
    st.ratedCount === 0 &&
    st.todayLog.rv === 0 &&
    st.fsrsCalls.length === 0
  );
  record("queue-end-guard-ignores-rating", ok, `队列用尽时 doRate 应早退忽略，实际: idx=${st.revIdx}`);
});

/* ── 裁决输出 ─────────────────────────────────────────────────────────── */
const total = cases.length;
const failures = problems.length;
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ failures, total, cases }, null, 2) + "\n");
  if (failures) process.exit(1);
} else {
  for (const c of cases) {
    console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}`);
  }
  if (failures) {
    process.stderr.write(`wb_rate_probe 契约破坏:\n  - ${problems.join("\n  - ")}\n`);
    process.exit(1);
  }
  console.log(`✅ PASS: wb-rate.js doRate 评分行为探针（${total} 项全通过）`);
}
