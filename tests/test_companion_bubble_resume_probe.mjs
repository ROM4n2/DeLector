/**
 * test_companion_bubble_resume_probe.mjs —— 桌宠气泡「模态挂起过期不得复活」行为探针
 *
 * 事故背景（P2 复审）：
 *   写作页移动端 sheet 展开属于模态，`repositionBubble()` 会把气泡收起并记下
 *   `bubbleSuspendedByModal`。旧实现关闭模态时**无条件** `remove('hidden')` ——
 *   如果 sheet 开着超过气泡自然 TTL（6.5s），被挂起的过期气泡会在关闭瞬间复活，
 *   用户关掉抽屉看到一个早就该消失的旧气泡。
 *
 * 探针把 `static/js/companion.js` 的**真源码**逐字节喂进 node:vm 的
 * SourceTextModule 真跑（不是复制品）：ESM import 由自定义 linker 桩掉
 * ./player.js / ./cd-state.js，真实加载 ./companion-obstacles.js，再用假时钟
 * 驱动 `Companion.say()` 与 `Companion.repositionBubble()` 的模态分支。
 *
 * 钉死的契约：
 *   1. say() 后气泡可见；
 *   2. 模态打开 → 气泡收起；
 *   3. 模态在 TTL 内关闭 → 气泡恢复可见（正常路径不回退）；
 *   4. 模态开超过 TTL 再关闭 → 气泡**保持隐藏**（本缺陷的回归钉）；
 *   5. 过期丢弃后重复 reposition 也不得复活；
 *   6. 之后再 say() 仍能正常显示新气泡（修法不误伤正常播报）。
 *
 * 用法：
 *   node --experimental-vm-modules --no-warnings tests/test_companion_bubble_resume_probe.mjs
 *   node --experimental-vm-modules --no-warnings tests/test_companion_bubble_resume_probe.mjs --json
 * 契约破坏时退出码 1，详情走 stderr。
 *
 * 环境变量：
 *   DELECTOR_PROBE_ROOT     仓库根目录（默认本文件上一级）
 *   DELECTOR_COMPANION_SRC  覆盖 companion.js 路径（pytest wrapper 做变异验证用）
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(process.env.DELECTOR_PROBE_ROOT || path.join(__dirname, ".."));
const JSON_MODE = process.argv.includes("--json");
// 依赖桩集中在 tests/companion_probe_deps.mjs：companion.js 新增 import 只改那一处。
const { companionDependencySources } = await import(
  pathToFileURL(path.join(ROOT, "tests", "companion_probe_deps.mjs")).href
);
const DEP_SOURCES = companionDependencySources(ROOT);

const COMPANION_SRC = fs.readFileSync(
  process.env.DELECTOR_COMPANION_SRC || path.join(ROOT, "static", "js", "companion.js"),
  "utf8"
);

/* ---- 最小 DOM 桩 --------------------------------------------------------- */
function makeClassList(initial = []) {
  const classes = new Set(initial);
  return {
    add(c) {
      classes.add(c);
    },
    remove(c) {
      classes.delete(c);
    },
    contains(c) {
      return classes.has(c);
    },
    toggle(c, force) {
      if (force === undefined) {
        if (classes.has(c)) classes.delete(c);
        else classes.add(c);
      } else if (force) {
        classes.add(c);
      } else {
        classes.delete(c);
      }
    }
  };
}

/**
 * 每个场景一套全新模块实例：companion.js 的 bubbleSuspendedByModal /
 * bubbleExpiresAt 是模块级状态，复用会串味。
 */
async function boot() {
  const state = { now: 0, modalOpen: false, timers: new Map(), nextTimerId: 0 };

  const bubble = {
    style: {},
    offsetWidth: 0,
    offsetHeight: 0,
    classList: makeClassList(["hidden"]),
    querySelector() {
      return null;
    }
  };
  // 零尺寸胶囊：resume 分支之后 repositionBubble 会在此提前返回，
  // 探针只验证「显不显示」这一个契约，不复制几何求解实现。
  const capsule = {
    style: {},
    offsetWidth: 0,
    offsetHeight: 0,
    classList: makeClassList(),
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name]
        : null;
    },
    dispatchEvent() {
      return true;
    },
    getBoundingClientRect() {
      return { left: 0, top: 0, width: 0, height: 0 };
    }
  };

  const elements = new Map([
    ["companion-bubble", bubble],
    ["companion", capsule],
    ["companion-de", { textContent: "" }],
    ["companion-zh", { textContent: "" }]
  ]);

  const documentStub = {
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector(selector) {
      return selector === ".writer-sidebar.mobile-panel-open" && state.modalOpen ? {} : null;
    },
    querySelectorAll() {
      return [];
    }
  };

  class FakeDate extends Date {
    static now() {
      return state.now;
    }
  }

  const context = vm.createContext({
    console,
    Date: FakeDate,
    CustomEvent: class {
      constructor(type, init) {
        this.type = type;
        this.detail = init && init.detail;
      }
    },
    setTimeout(fn, delay = 0) {
      const id = ++state.nextTimerId;
      state.timers.set(id, { fn, due: state.now + delay });
      return id;
    },
    clearTimeout(id) {
      state.timers.delete(id);
    },
    document: documentStub,
    window: {},
    navigator: { vibrate() {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    performance: { now: () => state.now },
    requestAnimationFrame(fn) {
      fn();
      return 1;
    },
    cancelAnimationFrame() {}
  });

  const companion = new vm.SourceTextModule(COMPANION_SRC, { context, identifier: "companion.js" });

  const deps = {};
  for (const [specifier, source] of Object.entries(DEP_SOURCES)) {
    deps[specifier] = new vm.SourceTextModule(source, { context, identifier: specifier });
  }
  await companion.link((specifier) => {
    if (deps[specifier]) return deps[specifier];
    throw new Error("探针未提供依赖桩: " + specifier);
  });
  await companion.evaluate();

  const Companion = companion.namespace.Companion;

  const advance = (ms) => {
    state.now += ms;
    for (;;) {
      const due = [...state.timers.entries()]
        .filter(([, timer]) => timer.due <= state.now)
        .sort((a, b) => a[1].due - b[1].due)[0];
      if (!due) break;
      state.timers.delete(due[0]);
      due[1].fn();
    }
  };

  return {
    Companion,
    state,
    advance,
    setModal(open) {
      state.modalOpen = open;
    },
    say() {
      Companion.say({ de: "Das ist ein Test.", zh: "这是一条测试气泡。" });
    },
    isHidden() {
      return bubble.classList.contains("hidden");
    }
  };
}

/* ---- 场景 ---------------------------------------------------------------- */
const cases = [];
function check(name, ok, detail) {
  cases.push({ name, ok: Boolean(ok), detail: detail || "" });
}

async function scenarioVisibleAfterSay() {
  const h = await boot();
  h.say();
  check("visible-after-say", !h.isHidden(), "say() 后气泡应可见");
}

async function scenarioModalOpenHides() {
  const h = await boot();
  h.say();
  h.setModal(true);
  h.Companion.repositionBubble();
  check("modal-open-hides", h.isHidden(), "模态打开时气泡应收起让位");
}

async function scenarioResumeWithinTtl() {
  const h = await boot();
  h.say(); // now=0，TTL 到 6500
  h.advance(1000);
  h.setModal(true);
  h.Companion.repositionBubble();
  h.advance(2000); // now=3000，仍在 TTL 内
  h.setModal(false);
  h.Companion.repositionBubble();
  check("resume-within-ttl-shows", !h.isHidden(), "TTL 内关闭模态，气泡应恢复可见");
}

async function scenarioResumeAfterLongModal() {
  const h = await boot();
  h.say(); // now=0
  h.advance(500); // now=500，模态打开
  h.setModal(true);
  h.Companion.repositionBubble();
  h.advance(7000); // now=7500：模态已开 7s > 6.5s，自然过期定时器已触发
  h.setModal(false);
  h.Companion.repositionBubble();
  check(
    "resume-after-long-modal-stays-hidden",
    h.isHidden(),
    "模态开超过 TTL 后关闭，过期气泡不得复活"
  );

  // 过期丢弃是终态：再来几次 reposition 也不得复活
  h.Companion.repositionBubble();
  h.Companion.repositionBubble();
  check(
    "expired-bubble-stays-dead-on-repeat",
    h.isHidden(),
    "过期气泡被丢弃后重复 reposition 不得复活"
  );

  // 修法不误伤正常播报：新 say() 仍应显示新气泡
  h.say();
  const shownAgain = !h.isHidden();
  h.advance(6500);
  check("say-again-after-expiry-shows", shownAgain, "过期后新的 say() 应正常显示气泡");
  check("new-bubble-expires-on-own-ttl", h.isHidden(), "新气泡仍按自己的 TTL 正常收起");
}

/* ---- 运行 ---------------------------------------------------------------- */
for (const scenario of [
  scenarioVisibleAfterSay,
  scenarioModalOpenHides,
  scenarioResumeWithinTtl,
  scenarioResumeAfterLongModal
]) {
  await scenario();
}

const failures = cases.filter((c) => !c.ok);
const out = { ok: failures.length === 0, failures: failures.length, total: cases.length, cases };

if (JSON_MODE) {
  console.log(JSON.stringify(out));
} else {
  for (const c of cases) {
    console.log(`${c.ok ? "PASS" : "FAIL"} ${c.name}${c.detail ? " — " + c.detail : ""}`);
  }
  console.log(`\n${cases.length - failures.length}/${cases.length} checks passed`);
}

if (failures.length) {
  process.stderr.write(
    "气泡模态挂起过期契约被破坏：\n" +
      failures.map((f) => `  - ${f.name}: ${f.detail}`).join("\n") +
      "\n"
  );
  process.exit(1);
}
