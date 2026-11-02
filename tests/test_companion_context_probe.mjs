/**
 * test_companion_context_probe.mjs —— 伴学 Agent 上下文来源与页面隔离行为探针
 *
 * 真源码逐字节进 node:vm（SourceTextModule），驱动：
 *   - static/js/companion.js 的 Companion.harvestStudyContext()
 *   - static/js/cp-state.js 的 setCompanionContext / resetCompanionContextForView
 *   - static/js/cp-drawer.js 的 renderContextBar()
 *
 * 钉死的契约（本轮第一阶段）：
 *   A. 阅读器实时选区优先，来源必须是 live-selection；
 *   B. 阅读器无实时选区时可回退 reader-state，文章标题/CEFR 来自当前文章；
 *   C. 非阅读器页面的实时选区只认 selection，不得带上一篇的 articleTitle/CEFR；
 *   D. 非阅读器页面即使 state 里残留旧句子，也必须返回空上下文；
 *   E. 切页 reset 后 activeContext 清空（view/contextSource 同步更新）；
 *   F. 抽屉 context bar 在非阅读器无上下文时显示当前页面 + 未绑定句子，
 *      三条 context-required 快捷问句不可见；
 *   G. 阅读器绑定句子时快捷问句仍可见（已发版正常路径不回退）。
 *
 * 用法：
 *   node --experimental-vm-modules --no-warnings tests/test_companion_context_probe.mjs
 *   node --experimental-vm-modules --no-warnings tests/test_companion_context_probe.mjs --json
 * 契约破坏时退出码 1，详情走 stderr。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const JSON_MODE = process.argv.includes("--json");

const fail = (msg) => {
  process.stderr.write(msg + "\n");
  process.exit(1);
};

const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const COMPANION_SRC = read("static/js/companion.js");
const CP_STATE_SRC = read("static/js/cp-state.js");
const CP_DRAWER_SRC = read("static/js/cp-drawer.js");
const CP_API_SRC = read("static/js/cp-api.js");
const MAIN_SRC = read("static/js/main.js");
const READER_SRC = read("static/js/reader.js");
const STYLE_SRC = read("static/style.css");

/* ---- 真源码护栏：本轮关键实现片段必须逐字存在 ----------------------------- */
const MUST = [
  "export function getActiveView()",
  "export function getCompanionScopeKey()",
  "contextSource = 'live-selection'",
  "contextSource = 'reader-state'",
  "view === 'reader'",
  "export function resetCompanionContextForView(view)",
  "export function resetCompanionSessionScope()",
  "updateQuickActionChips(Boolean(text), view, Boolean(draft))",
  "resetCompanionContextForView(view)",
  "scope_key",
  "onSessionId",
  "draft_text",
  "contextSource = 'writer-draft'",
  "writer-draft-required",
];
for (const m of MUST) {
  const srcs = [COMPANION_SRC, CP_STATE_SRC, CP_DRAWER_SRC, CP_API_SRC, MAIN_SRC, READER_SRC];
  if (!srcs.some((s) => s.includes(m))) {
    fail(`真源码里缺 "${m}" —— 文件被换/被删/探针切歪`);
  }
}

/* ---- 真实文章形状（与 reader.js state.currentArticle 消费字段一致） -------- */
const ARTICLE = {
  id: 42,
  title: "Der Spiegel",
  cefr_level: "C1",
  sentences: [
    { id: 1, text: "Der erste Satz." },
    { id: 2, text: "Der zweite Satz." },
  ],
};

/* ---- 最小 DOM 桩：view-* / context bar / 三条快捷问句 ---------------------- */
const VIEWS = ["reader", "home", "cards", "progress", "writer", "exam", "search", "encounter", "german"];

function makeEl(id) {
  const classes = new Set();
  const el = {
    id: id || "",
    children: [],
    style: {},
    className: "",
    textContent: "",
    innerHTML: "",
    title: "",
    classList: {
      add(c) {
        classes.add(c);
      },
      remove(c) {
        classes.delete(c);
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
      },
      contains(c) {
        return classes.has(c);
      },
    },
    appendChild(child) {
      el.children.push(child);
      child.parentNode = el;
      return child;
    },
    removeChild(child) {
      const i = el.children.indexOf(child);
      if (i >= 0) el.children.splice(i, 1);
      child.parentNode = null;
      return child;
    },
    addEventListener(type, fn) {
      el.listeners = el.listeners || {};
      el.listeners[type] = fn;
    },
    get firstChild() {
      return el.children.length ? el.children[0] : null;
    },
  };
  return el;
}

const registry = new Map();
for (const v of VIEWS) registry.set("view-" + v, makeEl("view-" + v));
registry.set("companion-context-bar", makeEl("companion-context-bar"));
const writerEditor = makeEl("ide-editor");
registry.set("ide-editor", writerEditor);
const chips = [makeEl("chip-1"), makeEl("chip-2"), makeEl("chip-3")];
const writerChips = [makeEl("writer-chip")];

const contextBar = registry.get("companion-context-bar");
const documentStub = {
  getElementById(id) {
    return registry.get(id);
  },
  querySelectorAll(selector) {
    if (selector.includes(".companion-quick-chip.writer-draft-required")) return writerChips;
    if (selector.includes(".companion-quick-chip.context-required")) return chips;
    return [];
  },
  querySelector() {
    return null;
  },
  createElement(tag) {
    return makeEl(tag);
  },
  body: makeEl("body"),
  documentElement: makeEl("html"),
  addEventListener() {},
};

const context = vm.createContext({
  console,
  Promise,
  JSON,
  Object,
  Array,
  Set,
  Map,
  Math,
  Date,
  String,
  Number,
  RegExp,
  Error,
  encodeURIComponent,
  decodeURIComponent,
  URLSearchParams,
  TextEncoder,
  TextDecoder,
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  localStorage: {
    getItem() {
      return null;
    },
    setItem() {},
    removeItem() {},
  },
  navigator: {
    vibrate() {},
  },
  document: documentStub,
  window: {
    state: {},
    getSelection() {
      return { toString: () => "" };
    },
    CompanionDrawer: {
      toggle(ctx) {
        context.__probe.companionToggle.push(ctx);
      },
    },
    openDrawer() {
      context.__probe.openDrawerCalls.push(true);
    },
  },
  alert(message) {
    context.__probe.alerts.push(String(message));
  },
});
context.__probe = { alerts: [], companionToggle: [], openDrawerCalls: [], apiCalls: [] };

function setView(view) {
  for (const v of VIEWS) {
    registry.get("view-" + v).classList.toggle("active", v === view);
  }
}

function setSelection(text) {
  context.window.getSelection = () => ({ toString: () => text || "" });
}

function setState(overrides) {
  context.window.state = {
    currentArticle: ARTICLE,
    activeSelectedRangeText: "",
    activeSelectedSentId: null,
    ...(overrides || {}),
  };
}

/* ---- 模块装载：真源码 + 依赖桩 ------------------------------------------- */
async function instantiate(source, deps, identifier) {
  const mod = new vm.SourceTextModule(source, { context, identifier });
  await mod.link(async (specifier) => {
    if (deps && Object.prototype.hasOwnProperty.call(deps, specifier)) {
      return deps[specifier]();
    }
    throw new Error("探针未提供依赖桩: " + specifier);
  });
  await mod.evaluate();
  return mod;
}

const problems = [];
let checks = 0;
function check(cond, msg) {
  checks += 1;
  if (!cond) problems.push(msg);
}

async function main() {
  const stubPlayer = await instantiate(
    `export const ShadowPlayer = { isPlaying: false };\nexport function playGermanAudio() {}\n`,
    {},
    "player-stub"
  );
  const companion = await instantiate(COMPANION_SRC, { "./player.js": async () => stubPlayer }, "companion.js");
  const cpState = await instantiate(CP_STATE_SRC, {}, "cp-state.js");

  const stubApi = await instantiate(
    [
      "export async function streamCompanionChat() {}",
      "export async function executeProposal() {}",
      "export async function fetchCompanionSessions() { return { sessions: [] }; }",
      "export async function createCompanionSession() { return { session: { id: 'x' } }; }",
      "export async function fetchCompanionHistory() { return { messages: [] }; }",
      "export async function fetchCompanionProposals() { return { proposals: [] }; }",
      "export async function fetchAppSettings() { return {}; }",
      "export async function updateReasoningEffort() { return {}; }",
    ].join("\n"),
    {},
    "cp-api-stub"
  );
  const stubMarkdown = await instantiate(
    "export function renderSafeMarkdownToElement() {}\n",
    {},
    "cp-drawer-markdown-stub"
  );
  const stubCapsule = await instantiate(
    "export function initFloatingCapsule() { return null; }\n",
    {},
    "cp-drawer-capsule-stub"
  );
  const stubProposals = await instantiate(
    "export function renderProposalCard() {}\nexport function renderProposalList() {}\n",
    {},
    "cp-drawer-proposals-stub"
  );
  const cpDrawer = await instantiate(
    CP_DRAWER_SRC,
    {
      "./cp-state.js": async () => cpState,
      "./companion.js": async () => companion,
      "./cp-api.js": async () => stubApi,
      "./cp-drawer-markdown.js": async () => stubMarkdown,
      "./cp-drawer-capsule.js": async () => stubCapsule,
      "./cp-drawer-proposals.js": async () => stubProposals,
    },
    "cp-drawer.js"
  );

  const stubCore = await instantiate(
    "export async function api(url, opts) { globalThis.__probe.apiCalls.push({ url: String(url), opts }); return {}; }\n",
    {},
    "core-stub"
  );
  const cpApi = await instantiate(CP_API_SRC, { "./core.js": async () => stubCore }, "cp-api.js");

  const { Companion: C, getCompanionScopeKey } = companion.namespace;
  const {
    companionState,
    setCompanionContext,
    resetCompanionContextForView,
    resetCompanionSessionScope,
  } = cpState.namespace;
  const { renderContextBar, openCompanionDrawer } = cpDrawer.namespace;

  // cp-drawer 模块加载时会把真实 CompanionDrawer 合并进 window；这里重新装回探针 spy，
  // 才能观察 Companion.onClick 是否真的调用了 toggle。
  context.window.CompanionDrawer = {
    toggle(ctx) {
      context.__probe.companionToggle.push(ctx);
    },
  };

  /* A. 阅读器实时选区优先 */
  setView("reader");
  setSelection("Der zweite Satz.");
  setState({ activeSelectedRangeText: "Der erste Satz.", activeSelectedSentId: 1 });
  let ctx = C.harvestStudyContext();
  check(ctx.view === "reader", "A view 未识别为 reader");
  check(ctx.contextSource === "live-selection", "A 实时选区来源未标为 live-selection");
  check(ctx.selectedText === "Der zweite Satz.", "A 实时选区未被优先采用");
  check(ctx.articleTitle === "Der Spiegel" && ctx.cefrLevel === "C1", "A 阅读器文章标题/CEFR 丢失");

  /* B. 阅读器无实时选区 → reader-state */
  setSelection("");
  setState({ activeSelectedRangeText: "Der erste Satz.", activeSelectedSentId: 1 });
  ctx = C.harvestStudyContext();
  check(ctx.contextSource === "reader-state", "B 无选区时未回退 reader-state");
  check(ctx.selectedText === "Der erste Satz.", "B reader-state 句子未采用");

  /* C. 非阅读器实时选区不得带旧文章标题/CEFR */
  setView("cards");
  setSelection("Karte Wort");
  setState({ activeSelectedRangeText: "Der erste Satz.", activeSelectedSentId: 1 });
  ctx = C.harvestStudyContext();
  check(ctx.view === "cards", "C view 未识别为 cards");
  check(ctx.contextSource === "live-selection", "C cards 实时选区来源错误");
  check(ctx.selectedText === "Karte Wort", "C cards 实时选区未采用");
  check(ctx.articleTitle === "" && ctx.cefrLevel === "", "C cards 仍带上一篇的文章标题/CEFR（上下文串味）");

  /* D. 非阅读器无选区：即使 state 有旧句子也必须为空 */
  setSelection("");
  setState({ activeSelectedRangeText: "Der erste Satz.", activeSelectedSentId: 1 });
  ctx = C.harvestStudyContext();
  check(ctx.selectedText === "", "D cards 无选区时泄漏了旧句子");
  check(ctx.contextSource === "none", "D cards 无上下文时来源不是 none");
  check(ctx.articleTitle === "" && ctx.cefrLevel === "", "D cards 空上下文仍带旧文章元数据");

  /* E. 切页 reset 清空 activeContext */
  setCompanionContext("Alter Satz.", "Der Spiegel", "C1", "reader", "reader-state", "Alter Entwurf.");
  resetCompanionContextForView("cards");
  check(companionState.activeContext.selectedText === "", "E reset 未清空 selectedText");
  check(companionState.activeContext.articleTitle === "", "E reset 未清空 articleTitle");
  check(companionState.activeContext.cefrLevel === "", "E reset 未清空 cefrLevel");
  check(companionState.activeContext.view === "cards", "E reset 未记录新 view");
  check(companionState.activeContext.contextSource === "none", "E reset 未归一 contextSource");
  check(companionState.activeContext.draftText === "", "E reset 未清空 draftText");

  /* F. 非阅读器无上下文：context bar 显示当前页面且快捷问句隐藏 */
  setView("cards");
  setState({});
  setCompanionContext("", "", "", "cards", "none");
  renderContextBar();
  const hint = contextBar.children.find((c) => c.className === "companion-context-hint");
  check(Boolean(hint), "F 非阅读器无上下文时缺少 context bar 提示");
  check(Boolean(hint && hint.textContent.includes("卡盒")), "F context bar 未显示当前页面（卡盒）");
  check(Boolean(hint && hint.textContent.includes("未绑定句子")), "F context bar 未显示未绑定句子");
  check(
    contextBar.children.every((c) => c.className !== "companion-context-grab-btn"),
    "F 非阅读器仍渲染了“抓取当前句”按钮"
  );
  for (const chip of chips) {
    check(!chip.classList.contains("is-visible"), "F 非阅读器快捷问句仍可见");
  }

  /* G. 阅读器绑定句子：正常路径不回退 */
  setView("reader");
  setState({});
  setCompanionContext("Der zweite Satz.", "Der Spiegel", "C1", "reader", "reader-state");
  renderContextBar();
  const readerText = contextBar.children.find((c) => c.className === "companion-context-text");
  check(Boolean(readerText), "G 阅读器绑定句子时缺少 context text");
  check(
    Boolean(readerText && readerText.textContent.includes("已绑定难句")),
    "G 阅读器 context bar 文案回退"
  );
  for (const chip of chips) {
    check(chip.classList.contains("is-visible"), "G 阅读器绑定句子后快捷问句未恢复可见");
  }

  /* G2. 写作台草稿上下文：与 selected_text 分离，来源标记区分 selection / draft */
  const DRAFT = "Ich habe hunger und gehe in der Schule.";
  setView("writer");
  setSelection("");
  writerEditor.textContent = DRAFT;
  ctx = C.harvestStudyContext();
  check(ctx.view === "writer", "G2 写作台 view 未识别");
  check(ctx.contextSource === "writer-draft", "G2 草稿来源未标为 writer-draft");
  check(ctx.draftText === DRAFT, "G2 未采集到写作草稿");
  check(ctx.selectedText === "", "G2 草稿污染了 selectedText");

  setSelection("hunger");
  ctx = C.harvestStudyContext();
  check(ctx.contextSource === "live-selection", "G2 写作台实时选区来源错误");
  check(ctx.selectedText === "hunger", "G2 写作台实时选区丢失");
  check(ctx.draftText === DRAFT, "G2 实时选区场景丢失 draftText");

  setView("cards");
  ctx = C.harvestStudyContext();
  check(ctx.draftText === "", "G2 非写作页泄漏了写作草稿");

  setView("writer");
  setCompanionContext("", "", "", "writer", "writer-draft", DRAFT);
  renderContextBar();
  const draftBar = contextBar.children.find((c) => c.className === "companion-context-text");
  check(Boolean(draftBar && draftBar.textContent.includes("已绑定当前草稿")), "G2 草稿 context bar 未显示");
  for (const chip of writerChips) {
    check(chip.classList.contains("is-visible"), "G2 写作台检查草稿入口未显示");
  }
  for (const chip of chips) {
    check(!chip.classList.contains("is-visible"), "G2 写作台仍显示阅读器快捷问句");
  }

  writerEditor.textContent = "";
  setCompanionContext("", "", "", "writer", "none", "");
  renderContextBar();
  const writerHint = contextBar.children.find((c) => c.className === "companion-context-hint");
  check(Boolean(writerHint && writerHint.textContent.includes("尚未检测到草稿")), "G2 无草稿时未降级提示");
  for (const chip of writerChips) {
    check(!chip.classList.contains("is-visible"), "G2 无草稿时检查草稿入口仍可见");
  }

  /* H. main.js show() 必须接线 reset（静态 wiring 证据，行为由 E 覆盖） */
  check(
    MAIN_SRC.includes("resetCompanionContextForView(view)"),
    "H main.js show() 未接线 resetCompanionContextForView"
  );
  check(
    MAIN_SRC.includes('state.activeSelectedRangeText = ""'),
    "H main.js show() 未清理阅读器选区残留 activeSelectedRangeText"
  );
  check(
    MAIN_SRC.includes("state.activeSelectedSentId = null"),
    "H main.js show() 未清理阅读器选区残留 activeSelectedSentId"
  );
  check(
    MAIN_SRC.includes("// Shared reactive state") && MAIN_SRC.includes("state,"),
    "H main.js 未把 state 暴露到 window（reader-state 上下文会失效）"
  );

  /* I. scope key：阅读器按文章，其它页面按 view */
  setView("reader");
  setState({});
  check(getCompanionScopeKey() === "article:42", "I 阅读器 scope 未按 article:<id>");
  setView("cards");
  check(getCompanionScopeKey() === "view:cards", "I 非阅读器 scope 未按 view:<name>");

  /* J. 切页清空旧会话指针 + main.js 接线 */
  companionState.currentSessionId = "ses_old";
  companionState.sessions = [{ id: "ses_old" }];
  resetCompanionSessionScope();
  check(companionState.currentSessionId === null, "J 切页未清空旧 currentSessionId");
  check(companionState.sessions.length === 0, "J 切页未清空旧 session 列表");
  check(
    MAIN_SRC.includes("resetCompanionSessionScope()"),
    "J main.js show() 未接线 resetCompanionSessionScope"
  );

  /* K. 入口准入：german 不可唤起，非阅读器可唤起，阅读器路径正常 */
  setView("german");
  context.__probe.companionToggle.length = 0;
  C.onClick({});
  check(context.__probe.companionToggle.length === 0, "K german 视图仍可唤起伴学抽屉");
  context.__probe.openDrawerCalls.length = 0;
  openCompanionDrawer();
  check(context.__probe.openDrawerCalls.length === 0, "K german 视图仍可打开伴学抽屉");
  check(
    READER_SRC.includes('tab === "companion" && getActiveView() === "german"'),
    "K 抽屉页签未阻断 german 视图"
  );

  setView("cards");
  setSelection("Karte Wort");
  C.onClick({});
  const cardsCtx = context.__probe.companionToggle.at(-1);
  check(Boolean(cardsCtx), "K 非阅读器无法唤起全局伴学入口");
  check(cardsCtx && cardsCtx.view === "cards", "K 非阅读器唤起 view 错误");
  check(cardsCtx && cardsCtx.selectedText === "Karte Wort", "K 非阅读器唤起未带实时选区");

  setView("reader");
  setSelection("Der zweite Satz.");
  context.__probe.companionToggle.length = 0;
  C.onClick({});
  const readerCtx = context.__probe.companionToggle.at(-1);
  check(Boolean(readerCtx), "K 阅读器入口回归：无法唤起");
  check(readerCtx && readerCtx.view === "reader", "K 阅读器入口回归：view 错误");
  check(readerCtx && readerCtx.selectedText === "Der zweite Satz.", "K 阅读器入口回归：选区丢失");

  /* L. disabled 状态下头像必须不可点（CSS 指针事件） */
  const disabledAvatar = STYLE_SRC.match(/\.companion\.is-disabled\s+\.companion-avatar\s*\{[^}]*\}/);
  check(
    Boolean(disabledAvatar && disabledAvatar[0].includes("pointer-events: none")),
    "L disabled 状态下头像仍可点击"
  );

  /* M. cp-api：请求携带新字段，并读取 X-Session-ID 回填 */
  const sse = 'event: delta\ndata: {"event":"delta","text":"hi"}\n\nevent: done\ndata: {"event":"done"}\n\n';
  let sent = false;
  let captured = null;
  context.fetch = async (url, opts) => {
    captured = { url: String(url), headers: opts.headers, body: JSON.parse(opts.body) };
    return {
      ok: true,
      headers: {
        get(name) {
          return String(name).toLowerCase() === "x-session-id" ? "ses_auto" : null;
        },
      },
      body: {
        getReader() {
          return {
            async read() {
              if (sent) return { done: true, value: undefined };
              sent = true;
              return { done: false, value: new TextEncoder().encode(sse) };
            },
          };
        },
      },
    };
  };
  let gotSid = null;
  const apiEvents = [];
  await cpApi.namespace.streamCompanionChat({
    messages: [{ role: "user", content: "Hallo" }],
    view: "cards",
    context_source: "none",
    draft_text: "Ich habe hunger.",
    scope_key: "view:cards",
    onSessionId: (sid) => {
      gotSid = sid;
    },
    onEvent: (event) => apiEvents.push(event),
  });
  check(gotSid === "ses_auto", "M 未回填响应头 X-Session-ID");
  check(captured && captured.body.view === "cards", "M 请求体未携带 view");
  check(captured && captured.body.context_source === "none", "M 请求体未携带 context_source");
  check(captured && captured.body.draft_text === "Ich habe hunger.", "M 请求体未携带 draft_text");
  check(captured && captured.body.scope_key === "view:cards", "M 请求体未携带 scope_key");
  check(apiEvents.includes("delta") && apiEvents.includes("done"), "M SSE 解析回归");

  await cpApi.namespace.fetchCompanionSessions("article:42");
  const listCall = context.__probe.apiCalls.at(-1);
  check(
    Boolean(listCall && listCall.url.includes("/api/companion/sessions/scoped/article:42")),
    "M 会话列表未按 scope_key 查询"
  );

  const out = {
    ok: true,
    checks,
    scenarios: {
      "reader-live-selection": "pass",
      "reader-state-fallback": "pass",
      "non-reader-live-selection": "pass",
      "non-reader-empty": "pass",
      "reset-on-switch": "pass",
      "drawer-context-gate": "pass",
      "reader-path-regression": "pass",
      "writer-draft-context": "pass",
      "writer-draft-gate": "pass",
      "main-wiring": "pass",
      "scope-key": "pass",
      "session-scope-reset": "pass",
      "entry-gate": "pass",
      "drawer-tab-gate": "pass",
      "avatar-disabled-css": "pass",
      "cp-api-session-header": "pass",
    },
  };

  if (problems.length) {
    fail("伴学上下文来源/隔离探针失败：\n  - " + problems.join("\n  - "));
  }
  if (JSON_MODE) {
    process.stdout.write(JSON.stringify(out));
  } else {
    console.log("PASS:", checks, "checks", out.scenarios);
  }
}

main().catch((err) => fail("探针执行异常: " + (err && err.stack ? err.stack : err)));
