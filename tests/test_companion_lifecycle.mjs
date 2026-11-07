/**
 * test_companion_lifecycle.mjs —— 伴读桌宠 P3 状态机纯函数契约
 *
 * 只验证 static/js/companion-lifecycle.js：状态是条件的纯函数，
 * 优先级与「error 不清 waiting」是设计稿 §2.3 / §2.5 的硬要求。
 *
 * 用法：
 *   node --experimental-vm-modules --no-warnings tests/test_companion_lifecycle.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(process.env.DELECTOR_PROBE_ROOT || path.join(__dirname, ".."));
const SRC = fs.readFileSync(path.join(ROOT, "static/js/companion-lifecycle.js"), "utf8");

const context = vm.createContext({});
const module = new vm.SourceTextModule(SRC, {
  context,
  identifier: "companion-lifecycle.js"
});
await module.link(() => {});
await module.evaluate();
const { createLifecycleConditions, resolveLifecycleState, lifecycleTitle, isLifecycleState } =
  module.namespace;

const failures = [];
const check = (name, actual, expected) => {
  if (actual !== expected) {
    failures.push(`${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
};

const state = (overrides) => resolveLifecycleState(createLifecycleConditions(overrides));

// 基础态
check('默认 → idle', state(), 'idle');
check('turn → thinking', state({ turnInFlight: true }), 'thinking');
check('turn + tool → acting', state({ turnInFlight: true, toolActive: true }), 'acting');
check('proposal → waiting', state({ proposalPending: true }), 'waiting');
check('bubble → speaking', state({ bubbleVisible: true }), 'speaking');
check('sleeping 兜底', state({ sleeping: true }), 'sleeping');

// §2.5 抢占硬要求
check(
  'dragging 抢占 speaking',
  state({ dragging: true, bubbleVisible: true }),
  'dragging'
);
check(
  'dragging 抢占 error',
  state({ dragging: true, errorLatched: true }),
  'dragging'
);
check(
  'error 抢占 thinking',
  state({ errorLatched: true, turnInFlight: true }),
  'error'
);
check(
  'error 抢占 speaking',
  state({ errorLatched: true, bubbleVisible: true }),
  'error'
);
check(
  'error 高于 waiting 且不清 proposal',
  state({ errorLatched: true, proposalPending: true }),
  'error'
);
check(
  'error 解除后 waiting 自动恢复',
  state({ errorLatched: false, proposalPending: true }),
  'waiting'
);
check(
  'waiting 抢占 thinking',
  state({ proposalPending: true, turnInFlight: true }),
  'waiting'
);
check(
  '新一轮抢占 speaking',
  state({ bubbleVisible: true, turnInFlight: true }),
  'thinking'
);
check(
  'tool 优先级高于 turn',
  state({ turnInFlight: true, toolActive: true, proposalPending: false }),
  'acting'
);
check(
  'sleeping 不得盖过任何活动',
  state({ sleeping: true, bubbleVisible: true }),
  'speaking'
);

// 文案与合法性
check('thinking 文案', lifecycleTitle('thinking'), '伴读 · 思考中');
check('未知状态文案回落 idle', lifecycleTitle('typo'), '伴读 · 待机');
check('合法状态', isLifecycleState('error'), true);
check('拼写漂移', isLifecycleState('eror'), false);

if (failures.length) {
  process.stderr.write(`[companion-lifecycle] FAIL (${failures.length})\n`);
  failures.forEach((line) => process.stderr.write(`  - ${line}\n`));
  process.exit(1);
}

process.stdout.write("[companion-lifecycle] PASS: 20 条优先级/抢占/文案断言全部通过\n");
