/**
 * motion_count_probe.mjs —— `countUp` 计数过程不出现负值
 *
 * 事故（2026-11-07 Android 真机实测）：`motion.js` 的 `countUp` 用
 * `Math.min(1, (now - start) / ms)` 只夹上界。rAF 回调的 `now` 可能略早于
 * 调度时取到的 `performance.now()`，`progress` 变负 → 三次缓动后仍为负 →
 * 台账「测验综合正答率」首帧闪过 `-2%`。
 *
 * 本探针把 `static/js/motion.js` **真源码**剥 export 后进 node:vm 真跑
 * （不重抄实现），用桩 `performance.now` / `requestAnimationFrame` /
 * `getComputedStyle` 驱动，断言：
 *   1 首帧时间戳早于 start 时，输出 MUST NOT 为负（落到 0）；
 *   2 全程采样窗口内每一帧 MUST NOT 为负；
 *   3 数值 MUST 单调不减（不发生回跳）；
 *   4 终值 MUST 精确等于目标值（不因夹取而欠/超）；
 *   5 reduce 下 MUST 直接落终态且不调度 rAF。
 *
 * 输出标准契约（`tests/probe_json_contract.py`）：精确 `{failures, total, cases}`。
 *
 * 用法：
 *   node tools/motion_count_probe.mjs            # 人类可读
 *   node tools/motion_count_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 * 契约被破坏时退出码 1、详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const MOTION_SRC = fs.readFileSync(path.join(ROOT, "static", "js", "motion.js"), "utf8");
const transformed = MOTION_SRC.replace(
  /^export\s+(?=(?:async\s+)?function\b|\blet\b|\bconst\b|\bvar\b|\bclass\b)/gm,
  "",
);

const cases = [];
const record = (name, ok, detail) => cases.push({ name, ok, detail });

/* ── 沙箱：只提供 countUp 走到的那条路径 ─────────────────────────────────── */
function makeSandbox({ reduced = false, token = "520ms" } = {}) {
  const raf = [];
  const sandbox = {
    window: { matchMedia: () => ({ matches: reduced }) },
    document: { documentElement: {} },
    getComputedStyle: () => ({ getPropertyValue: () => token }),
    performance: { now: () => 1000 },
    requestAnimationFrame: (cb) => {
      raf.push(cb);
      return raf.length;
    },
  };
  vm.runInNewContext(transformed, sandbox, { filename: "motion.js" });
  return { sandbox, raf };
}

/* ── 用例 1–4：正常路径，全程采样 ────────────────────────────────────────── */
{
  const { sandbox, raf } = makeSandbox();
  const el = { textContent: "0%" };
  const frames = [];
  let first = true;

  sandbox.countUp(el, 80, { duration: 520, format: (v) => `${Math.round(v)}%` });

  // rAF 时间戳可能早于 performance.now()（真机事故的触发条件）。
  let guard = 0;
  while (raf.length && guard++ < 500) {
    const cb = raf.shift();
    const t = first ? 1000 - 20 : Math.min(1000 + guard * 16, 1000 + 700);
    first = false;
    cb(t);
    frames.push(Number.parseFloat(el.textContent));
  }

  const negatives = frames.filter((v) => v < 0);
  record(
    "firstFrameNonNegative",
    frames.length > 0 && frames[0] >= 0,
    `首帧输出 ${frames[0]}%（期望 >= 0）`,
  );
  record(
    "allFramesNonNegative",
    negatives.length === 0,
    negatives.length ? `出现负值帧：${negatives.join(", ")}` : `采样 ${frames.length} 帧，无负值`,
  );
  const regressions = frames.filter((v, i) => i > 0 && v < frames[i - 1]);
  record(
    "monotonicNonDecreasing",
    regressions.length === 0,
    regressions.length ? `发生回跳：${regressions.join(", ")}` : `${frames.length} 帧单调不减`,
  );
  record("finalExact", frames.at(-1) === 80, `终值 ${frames.at(-1)}%（期望 80%）`);
}

/* ── 用例 5：reduce 下直接终态，不排 rAF ─────────────────────────────────── */
{
  const { sandbox, raf } = makeSandbox({ reduced: true });
  const el = { textContent: "0%" };
  sandbox.countUp(el, 80, { duration: 520, format: (v) => `${Math.round(v)}%` });
  record(
    "reduceSettlesWithoutRaf",
    el.textContent === "80%" && raf.length === 0,
    `文本 ${el.textContent} / rAF ${raf.length}（期望 80% / 0）`,
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
    "countUp 计数契约破坏：\n  - " + failures.map((c) => `${c.name}: ${c.detail}`).join("\n  - ") + "\n",
  );
  process.exit(1);
}
