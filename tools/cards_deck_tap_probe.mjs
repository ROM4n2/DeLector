/**
 * cards_deck_tap_probe.mjs —— 扑克牌「tap 翻面 / drag 切卡」行为探针
 *
 * 真机事故（2026-11-07 Android）：卡片页 → 扑克牌模式，点卡片本体永远翻不了面，
 * 一点就滑到下一张。根因不是阈值太小，而是旧 `attachDeckSwipeListener` 只在
 * `touchmove` 里给 `currentX` 赋值；干净 tap 没有 touchmove ⇒ `currentX` 停在
 * 初始 `0`，`touchend` 算出的 `diff = 0 - startX` 恒为大幅负数 ⇒ 每次点击都被
 * 当成「左滑」`stepDeck(1)`，随后重渲染把 click 目标端掉，翻面永远轮不到。
 *
 * 本探针按括号配对把 `static/js/cards.js` 里**真实的** attachDeckSwipeListener
 * 整段切出来（含函数内的阈值常量），配 `static/js/cd-state.js` 的真实 cardState
 * 容器切片进 node:vm 真跑；`toggleDeckFlip` / `stepDeck` 只做调用计数桩，
 * 手势判定逻辑零重抄。断言：
 *   1 干净 tap（无 move，历史事故）MUST 翻面且 MUST NOT 切卡；
 *   2 阈值内 tap（< 10px）MUST 翻面；
 *   3 左/右 drag（> 70px）MUST 切卡且 MUST NOT 翻面；
 *   4 10–70px 模糊区 MUST 回弹（不翻面、不切卡）；
 *   5 卡面按钮等带 onclick 的目标 MUST 被忽略；
 *   6 纵向滚动 MUST 不翻面、不切卡；
 *   7 pointercancel MUST 回弹且无动作；
 *   8 背面 tap MUST 不翻面（背面留给评分按钮）。
 *
 * 输出标准契约（`tests/probe_json_contract.py`）：精确 `{failures, total, cases}`。
 *
 * 用法：
 *   node tools/cards_deck_tap_probe.mjs            # 人类可读
 *   node tools/cards_deck_tap_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");
const log = (...a) => { if (!JSON_MODE) console.error(...a); };

const fail = (problems) => {
  process.stderr.write("扑克牌手势契约破坏：\n  - " + problems.join("\n  - ") + "\n");
  process.exit(1);
};

/* ---------------------------------------------------------------------------
 * 1. 源码切片（口径同 cards_wb_source_probe.mjs / wb_queue_probe.mjs）
 * ------------------------------------------------------------------------ */
const OPEN = { "(": ")", "[": "]", "{": "}" };
const CLOSE = { ")": "(", "]": "[", "}": "{" };

function matchBracket(src, openIdx) {
  if (!OPEN[src[openIdx]]) throw new Error(`matchBracket: 位置 ${openIdx} 不是开括号`);
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
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i < 0) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i); if (i < 0) break; i += 2; continue; }
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

function sliceObjectDecl(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`源码里找不到声明 ${declNeedle}（实现回退或改名了）`);
  const brace = src.indexOf("{", at);
  if (brace < 0) throw new Error(`${declNeedle} 后找不到对象字面量开括号`);
  const end = matchBracket(src, brace);
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

function sliceFunctionBody(src, declNeedle) {
  const at = src.indexOf(declNeedle);
  if (at < 0) throw new Error(`源码里找不到声明 ${declNeedle}（实现回退或改名了）`);
  const paren = src.indexOf("(", at);
  if (paren < 0) throw new Error(`${declNeedle} 后找不到参数表开括号（函数体定位失败）`);
  const paramsEnd = matchBracket(src, paren);
  let j = paramsEnd + 1;
  while (j < src.length && /\s/.test(src[j])) j++;
  if (src[j] !== "{") {
    throw new Error(`${declNeedle} 的参数表后不是函数体开括号（函数体定位失败）`);
  }
  const end = matchBracket(src, j);
  return src.slice(at, end + 1).replace(/^export\s+/, "");
}

const cardsJs = fs.readFileSync(path.join(ROOT, "static", "js", "cards.js"), "utf8");
const cdStateJs = fs.readFileSync(path.join(ROOT, "static", "js", "cd-state.js"), "utf8");

let stateFn = "";
let swipeFn = "";
try {
  stateFn = sliceObjectDecl(cdStateJs, "export const cardState = ");
  swipeFn = sliceFunctionBody(cardsJs, "function attachDeckSwipeListener(");
} catch (e) {
  fail([`源码切片失败：${e.message}`]);
}

const transformed = stateFn + "\n\n" + swipeFn + "\n;globalThis.__deckState = cardState;";

/* 切片护栏：切歪 / 回退 / 又挂回 touch 监听 ⇒ 直接红，不许假绿 */
const stripProblems = [];
if (!swipeFn.includes("pointerdown")) stripProblems.push("切片缺 pointerdown（手势实现回退了？）");
if (!swipeFn.includes("pointerup")) stripProblems.push("切片缺 pointerup（手势实现回退了？）");
if (!swipeFn.includes("TAP_SLOP_PX") || !swipeFn.includes("SWIPE_COMMIT_PX"))
  stripProblems.push("切片缺阈值常量（tap/drag 判定被删或改名）");
if (swipeFn.includes("touchstart"))
  stripProblems.push("切片仍含 touchstart（新旧监听并存会双重处理，MUST 只保留 Pointer Events）");
if (!/currentX\s*=\s*e\.clientX/.test(swipeFn))
  stripProblems.push("切片缺 pointerdown 里的 currentX 初始化（历史 tap 事故的根因）");
if (!/const cardState = \{/.test(transformed))
  stripProblems.push("切片缺 cd-state.js 的 cardState 容器");
if (stripProblems.length) fail(stripProblems);

/* ---------------------------------------------------------------------------
 * 2. 沙箱：只桩 UI 与动作出口，手势判定全部来自真源码
 * ------------------------------------------------------------------------ */
const handlers = {};
const cardEl = {
  style: {},
  addEventListener(type, fn) { handlers[type] = fn; },
  setPointerCapture() {},
};
let flips = 0;
let steps = [];

const sandbox = {
  console,
  document: { getElementById: (id) => (id === "deck-active-card" ? cardEl : null) },
  toggleDeckFlip: () => { flips += 1; },
  stepDeck: (dir) => { steps.push(dir); },
};
try {
  vm.runInNewContext(transformed, sandbox, { filename: "cards.deck.stripped.js" });
  sandbox.attachDeckSwipeListener();
} catch (e) {
  fail([`沙箱执行失败：${e.message}`]);
}

const CARD_TARGET = { closest: () => null };
const BUTTON_TARGET = { closest: () => ({ tagName: "BUTTON" }) };
const ev = (x, y = 0, target = CARD_TARGET) => ({
  pointerId: 1,
  pointerType: "touch",
  button: 0,
  clientX: x,
  clientY: y,
  target,
});

function reset(flipped = false) {
  flips = 0;
  steps = [];
  cardEl.style.transform = "";
  sandbox.__deckState.deck.flipped = flipped;
}

/** 跑一次手势：down → 可选 move → up / cancel。返回动作与最终 transform。 */
function gesture({ downX = 200, downY = 0, moveX = null, moveY = 0, target = CARD_TARGET, cancel = false, flipped = false } = {}) {
  reset(flipped);
  handlers.pointerdown(ev(downX, downY, target));
  if (moveX !== null) handlers.pointermove(ev(moveX, moveY, target));
  if (cancel) {
    handlers.pointercancel(ev(moveX ?? downX, moveY, target));
  } else {
    handlers.pointerup(ev(moveX ?? downX, moveY, target));
  }
  return { flips, steps: [...steps], transform: cardEl.style.transform };
}

/* ---------------------------------------------------------------------------
 * 3. 场景
 * ------------------------------------------------------------------------ */
const cases = [];
const record = (name, ok, detail) => cases.push({ name, ok, detail });

/* 场景 1：干净 tap（无 move）—— 历史事故的精确复现 */
{
  const r = gesture({ downX: 200 });
  log(`[1] tap(no move): flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "tapWithoutMoveFlips",
    r.flips === 1 && r.steps.length === 0,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 1 / []）`,
  );
}

/* 场景 2：阈值内 tap（7px，小于 10px slop） */
{
  const r = gesture({ downX: 200, moveX: 207, downY: 40, moveY: 41 });
  log(`[2] tap(7px): flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "tapWithinSlopFlips",
    r.flips === 1 && r.steps.length === 0,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 1 / []）`,
  );
}

/* 场景 3：左滑越过 70px ⇒ 下一张，且不翻面 */
{
  const r = gesture({ downX: 300, moveX: 220 });
  log(`[3] drag left 80px: flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "dragLeftStepsNext",
    r.flips === 0 && r.steps.length === 1 && r.steps[0] === 1,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 0 / [1]）`,
  );
}

/* 场景 4：右滑越过 70px ⇒ 上一张，且不翻面 */
{
  const r = gesture({ downX: 100, moveX: 180 });
  log(`[4] drag right 80px: flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "dragRightStepsPrev",
    r.flips === 0 && r.steps.length === 1 && r.steps[0] === -1,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 0 / [-1]）`,
  );
}

/* 场景 5：10–70px 模糊区 ⇒ 回弹，不翻面也不切卡 */
{
  const r = gesture({ downX: 200, moveX: 170 });
  log(`[5] drag 30px: flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}`);
  record(
    "ambiguousDragSnapsBack",
    r.flips === 0 && r.steps.length === 0 && r.transform === "",
    `flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}（期望 0 / [] / ""）`,
  );
}

/* 场景 6：卡面按钮 / 带 onclick 的控件不参与翻面 */
{
  const r = gesture({ downX: 200, target: BUTTON_TARGET });
  log(`[6] tap on [onclick]: flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "interactiveTargetIgnored",
    r.flips === 0 && r.steps.length === 0,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 0 / []）`,
  );
}

/* 场景 7：纵向滚动意图 ⇒ 不翻面、不切卡 */
{
  const r = gesture({ downX: 200, downY: 100, moveX: 205, moveY: 180 });
  log(`[7] vertical scroll: flips=${r.flips} steps=${JSON.stringify(r.steps)}`);
  record(
    "verticalScrollDoesNotFlip",
    r.flips === 0 && r.steps.length === 0,
    `flips=${r.flips} steps=${JSON.stringify(r.steps)}（期望 0 / []）`,
  );
}

/* 场景 8：pointercancel ⇒ 回弹且无动作 */
{
  const r = gesture({ downX: 300, moveX: 200, cancel: true });
  log(`[8] pointercancel: flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}`);
  record(
    "pointerCancelDoesNothing",
    r.flips === 0 && r.steps.length === 0 && r.transform === "",
    `flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}（期望 0 / [] / ""）`,
  );
}

/* 场景 9：背面 tap 不翻面（背面留给评分按钮） */
{
  const r = gesture({ downX: 200, flipped: true });
  log(`[9] tap on back: flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}`);
  record(
    "flippedTapDoesNothing",
    r.flips === 0 && r.steps.length === 0 && r.transform === "rotateY(180deg)",
    `flips=${r.flips} steps=${JSON.stringify(r.steps)} transform=${JSON.stringify(r.transform)}（期望 0 / [] / rotateY(180deg)）`,
  );
}

const failures = cases.filter((c) => !c.ok);
const out = { failures: failures.length, total: cases.length, cases };

if (JSON_MODE) {
  process.stdout.write(JSON.stringify(out) + "\n");
} else {
  for (const c of cases) console.log(`${c.ok ? "PASS" : "FAIL"} ${c.name} — ${c.detail}`);
}
if (failures.length) {
  process.stderr.write(
    "扑克牌手势契约破坏：\n  - " + failures.map((c) => `${c.name}: ${c.detail}`).join("\n  - ") + "\n",
  );
  process.exit(1);
}
