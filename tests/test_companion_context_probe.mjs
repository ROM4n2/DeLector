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
const CP_PROPOSALS_SRC = read("static/js/cp-drawer-proposals.js");
const CD_STATE_SRC = read("static/js/cd-state.js");
const CARDS_SRC = read("static/js/cards.js");
const MAIN_SRC = read("static/js/main.js");
const READER_SRC = read("static/js/reader.js");
const WRITER_SRC = read("static/js/writer.js");
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
  "progress-required",
  "sendProgressProfile",
  "sendProgressVocabStats",
  "refreshWriterDraftContext",
  "card-proposal-required",
  "sendCardProposal",
  "card_context",
  "contextSource = 'card-current'",
  "is-german-view",
];
for (const m of MUST) {
  const srcs = [COMPANION_SRC, CP_STATE_SRC, CP_DRAWER_SRC, CP_API_SRC, MAIN_SRC, READER_SRC, WRITER_SRC];
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
    dataset: {},
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
    focus() {},
    get firstChild() {
      return el.children.length ? el.children[0] : null;
    },
  };
  return el;
}

const registry = new Map();
for (const v of VIEWS) registry.set("view-" + v, makeEl("view-" + v));
registry.set("companion-context-bar", makeEl("companion-context-bar"));
registry.set("companion-session-select", makeEl("companion-session-select"));
registry.set("companion-drawer-body", makeEl("companion-drawer-body"));
const writerEditor = makeEl("ide-editor");
registry.set("ide-editor", writerEditor);
const companionInput = makeEl("companion-input");
registry.set("companion-input", companionInput);
const chips = [makeEl("chip-1"), makeEl("chip-2"), makeEl("chip-3")];
const writerChips = [makeEl("writer-chip")];
const progressChips = [makeEl("progress-chip-1"), makeEl("progress-chip-2")];
const cardChips = [makeEl("card-chip")];

const contextBar = registry.get("companion-context-bar");
const documentStub = {
  getElementById(id) {
    return registry.get(id);
  },
  querySelectorAll(selector) {
    if (selector.includes(".companion-quick-chip.writer-draft-required")) return writerChips;
    if (selector.includes(".companion-quick-chip.progress-required")) return progressChips;
    if (selector.includes(".companion-quick-chip.card-proposal-required")) return cardChips;
    if (selector.includes(".companion-quick-chip.context-required")) return chips;
    return [];
  },
  querySelector() {
    return null;
  },
  createElement(tag) {
    return makeEl(tag);
  },
  createTextNode(text) {
    return { nodeValue: String(text), textContent: String(text) };
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
context.__probe = { alerts: [], companionToggle: [], openDrawerCalls: [], apiCalls: [], sessionFetchCalls: [], sessionsFixture: [] };

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
  const cdState = await instantiate(CD_STATE_SRC, {}, "cd-state.js");
  const companion = await instantiate(
    COMPANION_SRC,
    { "./player.js": async () => stubPlayer, "./cd-state.js": async () => cdState },
    "companion.js"
  );
  const cpState = await instantiate(CP_STATE_SRC, {}, "cp-state.js");

  const stubApi = await instantiate(
    [
      "export async function streamCompanionChat() {}",
      "export async function executeProposal() {}",
      "export async function rejectProposal() {}",
      "export async function fetchCompanionSessions(scopeKey) { globalThis.__probe.sessionFetchCalls.push(scopeKey || null); return { sessions: globalThis.__probe.sessionsFixture || [] }; }",
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
  const realProposals = await instantiate(CP_PROPOSALS_SRC, {}, "cp-drawer-proposals-real.js");
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
  context.window.Companion = C;
  const { cardState } = cdState.namespace;
  const {
    companionState,
    setCompanionContext,
    resetCompanionContextForView,
    resetCompanionSessionScope,
  } = cpState.namespace;
  const {
    renderContextBar,
    openCompanionDrawer,
    refreshWriterDraftContext,
    sendProgressVocabStats,
    sendCardProposal,
    refreshSessionSelect,
    switchSession,
  } = cpDrawer.namespace;

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

  /* G3. 进度页：能力分区、无数据降级、写作草稿静默刷新 */
  setView("progress");
  setSelection("");
  setState({});
  ctx = C.harvestStudyContext();
  check(ctx.view === "progress", "G3 进度页 view 未识别");
  check(ctx.selectedText === "" && ctx.draftText === "", "G3 进度页不应硬塞文本上下文");
  check(ctx.contextSource === "none", "G3 进度页来源应保持 none");

  setCompanionContext("", "", "", "progress", "none", "");
  renderContextBar();
  for (const chip of progressChips) {
    check(chip.classList.contains("is-visible"), "G3 进度页专属入口未显示");
  }
  for (const chip of chips) {
    check(!chip.classList.contains("is-visible"), "G3 进度页仍显示阅读器快捷问句");
  }
  for (const chip of writerChips) {
    check(!chip.classList.contains("is-visible"), "G3 进度页仍显示写作检查入口");
  }

  setView("cards");
  setCompanionContext("", "", "", "cards", "none", "");
  renderContextBar();
  for (const chip of progressChips) {
    check(!chip.classList.contains("is-visible"), "G3 非进度页仍显示进度专属入口");
  }

  setView("writer");
  writerEditor.textContent = DRAFT;
  refreshWriterDraftContext();
  check(companionState.activeContext.draftText === DRAFT, "G3 写作输入未刷新草稿上下文");
  for (const chip of writerChips) {
    check(chip.classList.contains("is-visible"), "G3 写作输入后检查入口未刷新");
  }
  check(
    WRITER_SRC.includes("refreshWriterDraftContext"),
    "G3 writer.js 未接线草稿输入刷新"
  );
  check(
    CP_DRAWER_SRC.includes("get_learner_profile"),
    "G3 学习负荷入口未指向 get_learner_profile"
  );
  check(
    CP_DRAWER_SRC.includes("vocab_stats"),
    "G3 词汇等级入口未指向 vocab_stats"
  );
  setView("progress");
  companionInput.value = "";
  context.__probe.alerts.length = 0;
  sendProgressVocabStats();
  check(
    context.__probe.alerts.some((m) => m.includes("请先在输入框粘贴")),
    "G3 词汇等级无文本时未降级提示"
  );

  /* G4. 卡盒页：当前卡面词条 → cardContext，卡盒专属入口分区，无词条降级 */
  setView("cards");
  setSelection("");
  setState({});
  cardState.catalog.viewMode = "deck";
  cardState.catalog.segment = "due";
  cardState.catalog.dueCards.due_vocab = [
    {
      id: 7,
      word: "die Eule",
      lemma: "Eule",
      definition_zh: "猫头鹰",
      pos: "noun",
      gender: "feminine",
      cefr_level: "B1",
      sentence_context: "Die Eule schläft am Tag.",
    },
  ];
  cardState.catalog.dueCards.due_grammar = [];
  cardState.deck.index = 0;

  ctx = C.harvestStudyContext();
  check(ctx.view === "cards", "G4 卡盒页 view 未识别");
  check(ctx.contextSource === "card-current", "G4 卡盒词条来源未标为 card-current");
  check(ctx.cardContext.includes("die Eule"), "G4 未采集到当前卡面词条");
  check(ctx.cardContext.includes("猫头鹰"), "G4 卡盒词条释义丢失");
  check(ctx.selectedText === "" && ctx.draftText === "", "G4 卡盒词条污染了 selectedText/draftText");

  setCompanionContext("", "", "", "cards", "card-current", "", ctx.cardContext);
  renderContextBar();
  const cardBar = contextBar.children.find((c) => c.className === "companion-context-text");
  check(
    Boolean(cardBar && cardBar.textContent.includes("已绑定当前卡盒词条")),
    "G4 卡盒 context bar 未显示"
  );
  for (const chip of cardChips) {
    check(chip.classList.contains("is-visible"), "G4 卡盒关联生词提议入口未显示");
  }
  for (const chip of chips) {
    check(!chip.classList.contains("is-visible"), "G4 卡盒页仍显示阅读器快捷问句");
  }
  for (const chip of writerChips) {
    check(!chip.classList.contains("is-visible"), "G4 卡盒页仍显示写作检查入口");
  }

  /* G4-b. grid 视图无当前卡面 → 不回退成旧词条 */
  cardState.catalog.viewMode = "grid";
  ctx = C.harvestStudyContext();
  check(ctx.cardContext === "", "G4 grid 视图不应采集卡盒词条");
  check(ctx.contextSource === "none", "G4 grid 视图来源应保持 none");
  cardState.catalog.viewMode = "deck";

  /* G4-c. 无可用词条：入口仍可点，但必须显式降级提示，不静默无响应 */
  cardState.catalog.dueCards.due_vocab = [];
  cardState.deck.index = 0;
  context.__probe.alerts.length = 0;
  sendCardProposal();
  check(
    context.__probe.alerts.some((m) => m.includes("当前卡盒没有可用词条")),
    "G4 无可用词条时未降级提示"
  );
  check(CP_DRAWER_SRC.includes("propose_vocab_cards"), "G4 卡盒入口未指向 propose_vocab_cards");
  check(
    CP_PROPOSALS_SRC.includes("definition_zh") && CP_PROPOSALS_SRC.includes("待补充"),
    "G4 提案卡片未按 definition_zh 渲染释义或缺少「待补充」降级"
  );
  check(
    CP_DRAWER_SRC.includes("definition_zh 中文释义"),
    "G4 卡盒提议指令未要求模型给出 definition_zh 中文释义"
  );

  /* G5. 缺释义统一展示 + 批量确认/全部拒绝 */
  const { formatCardDefinition } = cdState.namespace;
  check(formatCardDefinition({ definition_zh: "" }) === "待补充", "G5 空释义未显示待补充");
  check(formatCardDefinition({ definition_zh: "  " }) === "待补充", "G5 空白释义未显示待补充");
  check(formatCardDefinition({}) === "待补充", "G5 缺字段未显示待补充");
  check(formatCardDefinition({ definition_zh: " 狗 " }) === "狗", "G5 正常释义被误改");
  const { selectSegmentLists, buildDeckFromLists } = cdState.namespace;
  const sharedDeck = buildDeckFromLists([{ id: 1 }], [{ id: 2 }]);
  check(
    sharedDeck.length === 2 && sharedDeck[0]._type === "vocab" && sharedDeck[1]._type === "grammar",
    "G5 公共卡组构成顺序或 _type 漂移"
  );
  const masteredLists = selectSegmentLists({
    segment: "mastered",
    cards: { vocab_cards: [{ id: 1, mastered: 1 }, { id: 2, mastered: 0 }], grammar_cards: [] },
    dueCards: {},
  });
  check(
    masteredLists.vList.length === 1 && masteredLists.vList[0].id === 1,
    "G5 mastered 分段取卡逻辑错误"
  );
  check(
    (CARDS_SRC.match(/formatCardDefinition\(/g) || []).length >= 4,
    "G5 卡盒网格/卡背/复习卡面未统一使用 formatCardDefinition"
  );

  const { renderProposalList, renderProposalCard } = realProposals.namespace;
  const singleHost = makeEl("single-host");
  renderProposalCard(
    singleHost,
    {
      id: "p-single",
      title: "T",
      payload: { cards: [{ word: "der Witwer", reading: "[ˈvɪtvɐ]" }] },
      status: "pending",
    },
    async () => {}
  );
  const singleContent = singleHost.children[0].children.find(
    (c) => c.className === "companion-proposal-content"
  );
  const singleText = singleContent.children[0].children
    .map((n) => n.textContent || n.nodeValue || "")
    .join("");
  check(singleText.includes("待补充"), "G5 提案卡片缺释义未显示待补充");

  const host = makeEl("batch-host");
  const proposals = [
    { id: "p1", action: "create_vocab_cards", title: "A", payload: { cards: [] }, status: "pending" },
    { id: "p2", action: "create_vocab_cards", title: "B", payload: { cards: [] }, status: "pending" },
  ];
  const calls = [];
  renderProposalList(host, proposals, async (p, action) => {
    calls.push(p.id + ":" + action);
  });
  const bar = host.children.find((c) => c.className === "companion-proposal-batch-bar");
  check(Boolean(bar), "G5 多条 pending 提议未出现批量操作条");
  await bar.children[1].listeners.click();
  check(calls.join(",") === "p1:reject,p2:reject", "G5 全部拒绝未逐条走 onAction");
  check(proposals.every((p) => p.status === "rejected"), "G5 全部拒绝后状态未置 rejected");
  check(
    !host.children.some((c) => c.className === "companion-proposal-batch-bar"),
    "G5 全部拒绝后批量条未消失"
  );

  const confirmHost = makeEl("confirm-host");
  const proposals2 = [
    { id: "p3", action: "create_vocab_cards", title: "C", payload: { cards: [] }, status: "pending" },
    { id: "p4", action: "create_vocab_cards", title: "D", payload: { cards: [] }, status: "pending" },
  ];
  const confirmCalls = [];
  renderProposalList(confirmHost, proposals2, async (p, action) => {
    confirmCalls.push(p.id + ":" + action);
  });
  const bar2 = confirmHost.children.find((c) => c.className === "companion-proposal-batch-bar");
  await bar2.children[0].listeners.click();
  check(confirmCalls.join(",") === "p3:confirm,p4:confirm", "G5 全部确认未逐条走 onAction");
  check(proposals2.every((p) => p.status === "accepted"), "G5 全部确认后状态未置 accepted");

  const oneHost = makeEl("one-host");
  renderProposalList(
    oneHost,
    [{ id: "p5", title: "E", payload: { cards: [] }, status: "pending" }],
    async () => {}
  );
  check(
    !oneHost.children.some((c) => c.className === "companion-proposal-batch-bar"),
    "G5 单条 pending 不应出现批量条"
  );

  /* G6. 失败路径：空/畸形提议不可确认，正常提议不受影响 */
  const emptyHost = makeEl("empty-host");
  renderProposalCard(
    emptyHost,
    { id: "p-empty", action: "create_vocab_cards", title: "空", payload: { cards: [] }, status: "pending" },
    async () => {}
  );
  const emptyActions = emptyHost.children[0].children.find(
    (c) => c.className === "companion-proposal-actions"
  );
  check(emptyActions.children[0].disabled === true, "G6 空提议确认按钮未禁用");
  check(
    emptyActions.children[0].textContent.includes("无可入库词条"),
    "G6 空提议未给出可见原因"
  );
  check(emptyActions.children[1].disabled === false, "G6 空提议仍应允许放弃");

  const badHost = makeEl("bad-host");
  renderProposalCard(
    badHost,
    { id: "p-bad", action: "create_vocab_cards", title: "坏", payload: {}, status: "pending" },
    async () => {}
  );
  const badActions = badHost.children[0].children.find(
    (c) => c.className === "companion-proposal-actions"
  );
  check(badActions.children[0].disabled === true, "G6 畸形 payload 确认按钮未禁用");

  const okHost = makeEl("ok-host");
  renderProposalCard(
    okHost,
    {
      id: "p-ok",
      action: "create_vocab_cards",
      title: "好",
      payload: { cards: [{ word: "der Hund", definition_zh: "狗" }] },
      status: "pending",
    },
    async () => {}
  );
  const okActions = okHost.children[0].children.find(
    (c) => c.className === "companion-proposal-actions"
  );
  check(okActions.children[0].disabled === false, "G6 正常提议确认按钮被误禁用");
  check(
    okActions.children[0].textContent === "确认添加入库",
    "G6 正常提议确认按钮文案被误改"
  );

  /* G7. 全局历史分组 + 跨 scope 上下文重置 */
  setView("cards");
  context.__probe.sessionsFixture = [
    { id: "ses_cards", title: "卡盒会话", scope_key: "view:cards", created_at: "2026-11-01" },
    { id: "ses_article", title: "阅读会话", scope_key: "article:3", created_at: "2026-11-02" },
  ];
  context.__probe.sessionFetchCalls.length = 0;
  await refreshSessionSelect();
  const selectEl = registry.get("companion-session-select");
  check(
    context.__probe.sessionFetchCalls.at(-1) === null,
    "G7 全局历史未走全量查询（仍按 scope 过滤）"
  );
  const groups = selectEl.children.filter((c) => typeof c.label === "string" && c.label);
  check(groups.length === 2, "G7 未按 scope 分成两组");
  check(groups[0] && groups[0].label === "当前页面", "G7 第一组不是当前页面");
  check(
    groups[0] && groups[0].children[0] && groups[0].children[0].value === "ses_cards",
    "G7 当前 scope 会话未排在当前页面组"
  );
  check(groups[1] && groups[1].label.includes("其它会话"), "G7 缺少其它会话组");
  check(
    groups[1] && groups[1].children[0] && groups[1].children[0].value === "ses_article",
    "G7 其它 scope 会话未进入其它会话组"
  );
  check(
    groups[1] && groups[1].children[0] && groups[1].children[0].textContent.includes("article:3"),
    "G7 其它会话未标注来源 scope"
  );
  check(selectEl.children[0].textContent === "＋ 新建会话", "G7 新建会话入口被挤走");

  setCompanionContext("Alter Satz.", "Der Spiegel", "C1", "cards", "reader-state");
  await switchSession("ses_article");
  check(companionState.currentSessionId === "ses_article", "G7 跨 scope 未切到目标会话");
  check(companionState.activeContext.selectedText === "", "G7 跨 scope 未清空旧句子");
  check(companionState.activeContext.contextSource === "none", "G7 跨 scope 未归一 contextSource");
  check(
    registry
      .get("companion-drawer-body")
      .children.some((c) => String(c.className).includes("companion-scope-notice")),
    "G7 跨 scope 未给出显式提示"
  );

  setCompanionContext("Karte Satz", "", "", "cards", "live-selection");
  await switchSession("ses_cards");
  check(
    companionState.activeContext.selectedText === "Karte Satz",
    "G7 同 scope 切换不应清空当前上下文"
  );

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

  /* L. german 工作台入口彻底禁点；用户手动收起伴读必须可点回 */
  const germanAvatar = STYLE_SRC.match(
    /\.companion\.is-disabled\.is-german-view\s+\.companion-avatar\s*\{[^}]*\}/
  );
  check(
    Boolean(germanAvatar && germanAvatar[0].includes("pointer-events: none")),
    "L german 工作台头像未禁点"
  );
  const userDisabledAvatar = STYLE_SRC.match(/\.companion\.is-disabled\s+\.companion-avatar\s*\{[^}]*\}/);
  check(
    Boolean(userDisabledAvatar && !userDisabledAvatar[0].includes("pointer-events: none")),
    "L 用户关闭伴读后头像仍被禁点，无法点回"
  );
  check(
    MAIN_SRC.includes('classList.toggle("is-german-view", view === "german")'),
    "L main.js 未按 view 精确挂 is-german-view"
  );

  // 行为层：german 下 onClick 直接早退，不允许借“重新启用”绕过禁用。
  setView("german");
  C.enabled = false;
  context.__probe.companionToggle.length = 0;
  C.onClick({});
  check(C.enabled === false, "L german 下点击竟然重新启用了伴读");
  check(context.__probe.companionToggle.length === 0, "L german 下点击仍唤起了抽屉");

  // 行为层：用户主动关闭后，在非 german 页面点击浮标应重新启用伴读。
  setView("cards");
  C.enabled = false;
  C.onClick({});
  check(C.enabled === true, "L 用户关闭伴读后点击浮标未能重新启用");
  C.enabled = true;

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
      "writer-draft-live-refresh": "pass",
      "progress-partition": "pass",
      "card-current-context": "pass",
      "card-partition": "pass",
      "card-empty-degrade": "pass",
      "definition-fallback-ui": "pass",
      "proposal-batch-actions": "pass",
      "proposal-failure-paths": "pass",
      "session-global-groups": "pass",
      "session-cross-scope-reset": "pass",
      "main-wiring": "pass",
      "scope-key": "pass",
      "session-scope-reset": "pass",
      "entry-gate": "pass",
      "drawer-tab-gate": "pass",
      "avatar-disabled-css": "pass",
      "german-entry-lock": "pass",
      "user-reenable": "pass",
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
