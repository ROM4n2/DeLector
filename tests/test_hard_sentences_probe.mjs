/**
 * test_hard_sentences_probe.mjs —— 长难句精读工坊前端行为探针（红线 11 契约钉死）
 *
 * 探针把 static/js/hard-sentences.js 的**真源码**逐字节喂进 node:vm 的
 * SourceTextModule 真跑（不是复制品）：ESM 的 import 由自定义 linker 解析，
 * 桩掉 ./core.js（api/esc/notify）唯一依赖，然后从模块命名空间驱动真实控制器
 * （enterHardSentences / revealTree / lookupWord / addCard / nextCard /
 * stopHardSentences / setHardSource / pickHardMaterial / setHardLevel），把后端
 * 契约逐字段钉死（对照 delector/routes/syntax_hard.py 与规格 §3）：
 *
 *   1. GET  /api/syntax/hard-sentences
 *      → {items:[{sentence, score, level, dimensions, path, source,
 *                 source_id, sentence_index}]}
 *      （source_id int、source 枚举、dimensions 子键
 *       clause_depth/clause_count/passive/subjunctive/verb_last/
 *       relative_clause/length 各含 value/score）
 *   2. GET  /api/syntax/hard-sentences/detail → analysis:{clause_tree, topology}
 *   3. POST /api/syntax/hard-sentence/trials body 七字段
 *      {source, source_id, sentence_index, level, score, revealed, duration_sec}
 *      → {trial_id}
 *   4. POST /api/cards/grammar 字段拼装（照 GrammarCardReq：
 *      article_id/sentence_context/grammar_name/cefr_level/explanation_zh/
 *      rule_formula/corrected_form/error_type）
 *
 * 行为路径：选源 → 卡片流 → 拆解揭示 → 查词（/api/lookup/vocab）→ 入盒 → 成绩汇总。
 *
 * 变异验证（探针非恒真证明）：内置 3 个变异用例，把契约字段/子键改错或删掉后
 * 重跑同一场景，探针必须捕获断裂（problems > 0）——若任何变异未被捕获，探针
 * 自身退出码 1（红），证明它钉得住契约而非「字符串在不在」式死测：
 *   变异 1：dimensions 的 clause_depth 子键改名 → 芯片「从句深度」应是红
 *   变异 2：detail 响应删掉 analysis.topology → 揭示后无拓扑
 *   变异 3：榜单 item 缺 path → 「近似分析」提示应消失（红）
 *
 * 用法（参照 tools/wb_sync_probe.mjs 双模式）：
 *   node --experimental-vm-modules --no-warnings tests/test_hard_sentences_probe.mjs
 *   node --experimental-vm-modules --no-warnings tests/test_hard_sentences_probe.mjs --json   # pytest 用
 * 契约被破坏或变异未被捕获时退出码 1、详情走 stderr。
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

/* ---- 真源码装载：逐字节读入，绝不重抄实现 ---------------------------------- */
const SRC = fs.readFileSync(path.join(ROOT, "static", "js", "hard-sentences.js"), "utf8");

/* 真源码护栏：关键实现片段必须逐字存在（文件被换/被删/切歪 → 直接红） */
const MUST = [
  'import { api, esc, notify } from "./core.js"',
  "/api/syntax/hard-sentences",
  "/api/syntax/hard-sentences/detail",
  "/api/syntax/hard-sentence/trials",
  "/api/cards/grammar",
  "/api/lookup/vocab",
  "export async function enterHardSentences",
  "export function stopHardSentences",
  "export async function revealTree",
  "export async function lookupWord",
  "export async function addCard",
  "export function nextCard",
  "duration_sec",
  "clause_tree",
  "topology",
  "clause_depth",
  "clause_count",
  "relative_clause",
  "article_id",
  "sentence_context",
  "grammar_name",
  "cefr_level",
  "explanation_zh",
  "rule_formula",
  "corrected_form",
  "error_type",
];
for (const m of MUST) {
  if (!SRC.includes(m)) fail(`hard-sentences.js 里缺 "${m}" —— 探针钉的不是真源码（文件被换/被删）`);
}

/* ---- 契约场景数据（后端响应形状，字段名逐字对齐 syntax_hard.py） ------------ */
const ITEMS = [
  {
    sentence: "Der Mann, der in die Schule geht, lernt fleißig Deutsch.",
    score: 68.5,
    level: "B2",
    dimensions: {
      clause_depth: { value: 2, score: 20 },
      clause_count: { value: 3, score: 15 },
      passive: { value: false, score: 0 },
      subjunctive: { value: false, score: 0 },
      verb_last: { value: true, score: 10 },
      relative_clause: { value: true, score: 12 },
      length: { value: 9, score: 11 },
    },
    path: "pure",
    source: "encounter",
    source_id: 7,
    sentence_index: 2,
  },
  {
    sentence: "Der Mann geht in die Schule.",
    score: 34,
    level: "A2",
    dimensions: {
      clause_depth: { value: 1, score: 5 },
      clause_count: { value: 1, score: 3 },
      passive: { value: false, score: 0 },
      subjunctive: { value: false, score: 0 },
      verb_last: { value: false, score: 0 },
      relative_clause: { value: false, score: 0 },
      length: { value: 7, score: 6 },
    },
    path: "spacy",
    source: "article",
    source_id: 3,
    sentence_index: 0,
  },
];

const CLAUSE_TREE = {
  type: "main",
  label: "主句",
  finite_verb: "lernt",
  text: "Der Mann … lernt",
  children: [
    { type: "relative", label: "关系从句", finite_verb: "geht", text: "der … geht", children: [] },
  ],
};

// 真实 API 形状（syntax_tree.analyze_sentence_topology / 纯 Python 降级输出）：
// field_texts 值为**字符串**，顶层 vorfeld/mittelfeld 为 token 数组。旧 fixture 用数组
// field_texts 与真实输出不符 → `Array.isArray(ft) ? ft.join(" ") : topo[key]` 走 join 分支，
// 掩盖了字符串 field_texts 时渲染成 "[object Object]" 的真机 bug（v5.7.2 报障）。
const TOPOLOGY = {
  vorfeld: [{ text: "Der", id: 0 }, { text: "Mann", id: 1 }],
  linke_klammer: [],
  mittelfeld: [{ text: "lernt", id: 2 }, { text: "fleißig", id: 3 }],
  rechte_klammer: [],
  nachfeld: [],
  field_texts: {
    vorfeld: "Der Mann",
    linke_klammer: "",
    mittelfeld: "lernt fleißig",
    rechte_klammer: "",
    nachfeld: "",
  },
  sentence_type: "Verbzweitsatz",
  bracket_structure: "VF / LK / MF / RK",
};

function buildRes(cfg) {
  // 变异 1：dimensions 子键 clause_depth → clause_dep（芯片该红）
  const dimKey = cfg.dimKey || "clause_depth";
  const mkDim = (dep) => ({
    [dimKey]: { value: dep, score: 20 },
    clause_count: { value: 3, score: 15 },
    passive: { value: false, score: 0 },
    subjunctive: { value: false, score: 0 },
    verb_last: { value: true, score: 10 },
    relative_clause: { value: true, score: 12 },
    length: { value: 9, score: 11 },
  });
  const mkItems = ITEMS.map((it) => ({ ...it, dimensions: mkDim(it.dimensions.clause_depth.value) }));
  // 变异 3：榜单 item 缺 path → 「近似分析」提示应消失
  const listItems = cfg.dropPath
    ? mkItems.map(({ path, ...rest }) => rest)
    : mkItems;

  // 变异 2：detail 响应删掉 analysis.topology → 揭示后无拓扑
  let analysis = { clause_tree: CLAUSE_TREE, topology: TOPOLOGY };
  if (cfg.noTopology) analysis = { clause_tree: CLAUSE_TREE };

  return {
    list: { items: listItems },
    detail: {
      sentence: listItems[0].sentence,
      score: listItems[0].score,
      level: listItems[0].level,
      dimensions: listItems[0].dimensions,
      path: listItems[0].path,
      analysis,
    },
    trials: { trial_id: 4242 },
    card: { id: 99 },
    lookup: {
      definition_zh: "男人；先生",
      pos: "Nomen",
      cefr_level: "A1",
      plural: "Männer",
    },
    articles: [
      { id: 3, title: "Goethe B2", level: "" },
    ],
    encounter: { texts: [{ id: 7, title: "Der Mann", level: "B2" }] },
  };
}

/* ---- vm 沙箱：Document/Window 桩 + 抓包 api 桩 + 依赖桩模块 ------------------ */
const STUB_CORE = `
"use strict";
export function esc(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
export function notify(message, opts) { globalThis.__probe.notifies.push(String(message)); }
export async function api(url, opts) {
  const o = {
    url: String(url),
    method: (opts && opts.method) || "GET",
    headers: (opts && opts.headers) || {},
    body: (opts && opts.body) || null,
  };
  globalThis.__probe.reqs.push(o);
  const u = o.url.split("?")[0];
  if (u === "/api/syntax/hard-sentences") return globalThis.__probe.res.list;
  if (u === "/api/syntax/hard-sentences/detail") return globalThis.__probe.res.detail;
  if (u === "/api/syntax/hard-sentence/trials") return globalThis.__probe.res.trials;
  if (u === "/api/cards/grammar") return globalThis.__probe.res.card;
  if (u === "/api/lookup/vocab") return globalThis.__probe.res.lookup;
  if (u === "/api/articles") return globalThis.__probe.res.articles;
  if (u === "/api/encounter/texts") return globalThis.__probe.res.encounter;
  throw new Error("探针 api 桩未覆盖 URL: " + url);
}
`;

// 运行一整轮场景（真源码 + 契约场景数据），返回 problems[] 与各契约域失败表。
// 契约被破坏时 problems 非空（不 exit，交由调用方判定：主跑红 / 变异跑证明敏感）。
async function runScenarios(cfg) {
  const failures = {};
  let checks = 0;
  const check = (cond, msg, domain) => {
    checks += 1;
    if (cond) return;
    (failures[domain] = failures[domain] || []).push(msg);
  };
  const DOMAINS = [
    "hard_list",
    "data_contract",
    "source_switch",
    "detail_analysis",
    "lookup",
    "cards_grammar",
    "trials_persist",
    "summary",
  ];

  // Document/Window 桩：getElementById 只认预注册表（与真 DOM 一致：未知 id 返回 undefined）
  const els = {};
  const makeEl = (id) => ({
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
    focus() {},
    appendChild() {},
  });
  for (const id of [
    "hs-source-bar",
    "hs-level-bar",
    "hs-material-bar",
    "hs-stage",
    "hs-summary",
    "hs-lookup-pop-zone",
    "hs-add-card-btn",
  ]) {
    els[id] = makeEl(id);
  }

  const store = {};
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
    setTimeout() {
      return 0;
    },
    clearTimeout() {},
    localStorage: {
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem(k, v) {
        store[k] = String(v);
      },
      removeItem(k) {
        delete store[k];
      },
    },
    document: {
      getElementById(id) {
        return els[id];
      },
      createElement() {
        return makeEl("style");
      },
      head: { appendChild() {} },
      documentElement: { appendChild() {} },
      querySelector() {
        return makeEl("sel");
      },
      addEventListener() {},
    },
    window: {},
  });
  context.__probe = {
    reqs: [],
    notifies: [],
    res: buildRes(cfg),
  };

  // 真源码逐字节进 vm（SourceTextModule，import 由 linker 解析为桩模块）
  const stubModule = async (src) => {
    const sm = new vm.SourceTextModule(src, { context });
    await sm.link(() => {
      throw new Error("桩模块不应再有 import");
    });
    await sm.evaluate();
    return sm;
  };
  const real = new vm.SourceTextModule(SRC, { context });
  await real.link(async (specifier) => {
    if (specifier === "./core.js") return stubModule(STUB_CORE);
    throw new Error("探针未提供依赖桩: " + specifier);
  });
  await real.evaluate();
  const L = real.namespace;

  const reqs = context.__probe.reqs;
  const notifies = context.__probe.notifies;
  const stage = () => els["hs-stage"].innerHTML;
  // 句子被逐词 <span> 拆开渲染，剥标签后再比对完整句（跨标签子串会漏）
  const stageText = () => els["hs-stage"].innerHTML.replace(/<[^>]+>/g, "");
  const summary = () => els["hs-summary"].innerHTML;
  const lookupZone = () => els["hs-lookup-pop-zone"].innerHTML;
  const addBtn = () => els["hs-add-card-btn"];

  /* ── 行为路径 ①：进入工坊 → 难度榜契约 GET /api/syntax/hard-sentences ── */
  await L.enterHardSentences();
  check(
    reqs.some((r) => r.url.split("?")[0] === "/api/syntax/hard-sentences"),
    "未请求 GET /api/syntax/hard-sentences",
    "hard_list",
  );
  // 榜单按难度降序渲染：idx0 是 encounter/B2 高难句（剥标签后比对完整句）
  check(stageText().includes(ITEMS[0].sentence), "难度榜未按降序渲染首句（encounter B2）", "hard_list");
  check(stage().includes("句 1 / 2"), "卡片流进度未按 items 长度渲染", "hard_list");

  /* ── 契约钉死点 1：列表项字段消费（source_id/sentence_index 数值化 + source 枚举 + dimensions 子键） ── */
  // source=all：源标签拼接「encounter#7 · 第3句」（Number(source_id)/Number(sentence_index)）
  check(
    stage().includes("encounter#7") && stage().includes("第3句"),
    "源标签未按 source/source_id/sentence_index 拼装（理性数化）",
    "data_contract",
  );
  // path==="pure" → 「轻量分析」提示（红线 1，v5.7.3 文案软化）
  check(stage().includes("轻量分析"), "path=pure 未渲染『轻量分析』提示（红线 1）", "data_contract");
  // dimensions 各子键消费：clause_depth/clause_count/length 带数值后缀，verb_last/relative_clause 布尔
  check(
    stage().includes("从句深度 2层") && stage().includes("从句数 3个") && stage().includes("句长 9词"),
    "dimensions 数值子键未渲染（clause_depth/clause_count/length）",
    "data_contract",
  );
  check(
    stage().includes("VL 句框") && stage().includes("关系从句"),
    "dimensions 布尔子键未渲染（verb_last/relative_clause）",
    "data_contract",
  );

  /* ── 行为路径 ②：拆解揭示 → GET detail → analysis.clause_tree + topology ── */
  await L.revealTree();
  const detailReq = reqs.find((r) => r.url.startsWith("/api/syntax/hard-sentences/detail"));
  check(Boolean(detailReq), "揭示未请求 GET /api/syntax/hard-sentences/detail", "detail_analysis");
  if (detailReq) {
    check(
      detailReq.url.includes("source=encounter") && detailReq.url.includes("source_id=7") &&
        detailReq.url.includes("sentence_index=2"),
      "detail 请求未带 source/source_id/sentence_index",
      "detail_analysis",
    );
  }
  check(stage().includes("✅ 句法结构已揭示"), "揭示后未渲染揭示态", "detail_analysis");
  check(stage().includes("主句") && stage().includes("关系从句"), "clause_tree 嵌套树未渲染", "detail_analysis");
  check(stage().includes(" ➤定式 lernt"), "clause_tree 节点未渲染定式动词 finite_verb", "detail_analysis");
  check(
    stage().includes("VF 前置场") && stage().includes("MF 中段") && stage().includes("框型"),
    "analysis.topology 未渲染（field_texts/框型）",
    "detail_analysis",
  );
  check(
    !stage().includes("[object Object]"),
    "topology 渲染出现 '[object Object]'（字符串 field_texts 被当 token 数组 toString，v5.7.2 真机报障）",
    "detail_analysis",
  );
  check(
    stage().includes("Der Mann") && stage().includes("lernt fleißig"),
    "topology 未渲染 field_texts 可读文案（应为字符串原文而非 token 数组）",
    "detail_analysis",
  );

  /* ── 行为路径 ③：逐词查词 → POST /api/lookup/vocab 轻量弹层 ── */
  await L.lookupWord(0);
  const lookupReq = reqs.find((r) => r.url === "/api/lookup/vocab");
  check(Boolean(lookupReq), "逐词未请求 POST /api/lookup/vocab", "lookup");
  check(lookupReq && lookupReq.method === "POST", "查词请求方法不是 POST", "lookup");
  if (lookupReq) {
    const body = JSON.parse(lookupReq.body);
    check(
      JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["sentence", "target_word"]),
      "查词 body 顶层字段必须恰为 {sentence, target_word}",
      "lookup",
    );
    check(body.target_word === "Der" && body.sentence === ITEMS[0].sentence, "查词 body 字段取值错误", "lookup");
  }
  check(
    lookupZone().includes("男人；先生") && lookupZone().includes("复数 Männer"),
    "查词 popup 未渲染 definition_zh/plural",
    "lookup",
  );

  /* ── 契约钉死点 4：入盒 POST /api/cards/grammar 字段拼装（照 GrammarCardReq） ── */
  await L.addCard();
  const cardReq = reqs.find((r) => r.url === "/api/cards/grammar");
  check(Boolean(cardReq), "未请求 POST /api/cards/grammar", "cards_grammar");
  check(cardReq && cardReq.method === "POST", "入盒请求方法不是 POST", "cards_grammar");
  if (cardReq) {
    const body = JSON.parse(cardReq.body);
    check(
      JSON.stringify(Object.keys(body).sort()) ===
        JSON.stringify([
          "article_id", "cefr_level", "corrected_form", "error_type",
          "explanation_zh", "grammar_name", "rule_formula", "sentence_context",
        ]),
      "入盒 body 字段必须恰为 GrammarCardReq 八字段",
      "cards_grammar",
    );
    check(body.article_id === null, "encounter 源 article_id 应为 null（非 article 不挂文章）", "cards_grammar");
    check(body.sentence_context === ITEMS[0].sentence, "sentence_context 未取当前句", "cards_grammar");
    check(body.grammar_name === "长难句精读", "grammar_name 固定值错误", "cards_grammar");
    check(body.cefr_level === "B2", "cefr_level 未透传 item.level", "cards_grammar");
    check(body.explanation_zh.includes("长难句精读（") && body.explanation_zh.includes("从句深度 2"), "explanation_zh 未按 dimensions 拼装", "cards_grammar");
    check(body.rule_formula.includes("69/100") && body.rule_formula.includes("encounter#7"), "rule_formula 未含难度分/源标识", "cards_grammar");
  }
  check(addBtn().textContent.includes("已加入复习盒"), "入盒成功后按钮未切『已加入复习盒』", "cards_grammar");
  check(addBtn().disabled === false, "入盒后按钮未释放 disabled", "cards_grammar");

  /* ── 契约钉死点 3：试练落盘 POST /api/syntax/hard-sentence/trials 七字段 ── */
  L.stopHardSentences(); // 离开：落盘当前句（item0，已揭示 → revealed=1）
  const trialReq = reqs.find((r) => r.url === "/api/syntax/hard-sentence/trials");
  check(Boolean(trialReq), "离开未 POST /api/syntax/hard-sentence/trials", "trials_persist");
  if (trialReq) {
    check(trialReq.method === "POST", "trials 请求方法不是 POST", "trials_persist");
    const body = JSON.parse(trialReq.body);
    check(
      JSON.stringify(Object.keys(body).sort()) ===
        JSON.stringify(["duration_sec", "level", "revealed", "score", "sentence_index", "source", "source_id"]),
      "trials body 字段必须恰为七字段 {source,source_id,sentence_index,level,score,revealed,duration_sec}",
      "trials_persist",
    );
    check(body.source === "encounter" && body.source_id === 7, "trials source/source_id 未透传", "trials_persist");
    check(body.sentence_index === 2 && body.level === "B2" && body.score === 68.5, "trials 句子标识字段未透传", "trials_persist");
    check(body.revealed === 1, "已揭示句子 trials.revealed 应为 1", "trials_persist");
    check(Number.isInteger(body.duration_sec) && body.duration_sec >= 1, "trials.duration_sec 必须为 ≥1 整数", "trials_persist");
  }

  /* ── 行为路径 ④：成绩汇总（推进到最后一句 → 会话末落盘 + 汇总渲染） ── */
  L.nextCard(); // idx → 1
  L.nextCard(); // idx=1 是末句 → 落盘 item1 + 提示已到末尾
  const trialReqs = reqs.filter((r) => r.url === "/api/syntax/hard-sentence/trials");
  check(trialReqs.length >= 2, "会话结束未对当前句落盘 trials", "trials_persist");
  check(notifies.some((n) => n.includes("已到末尾")), "推进到末尾未提示会话结束", "summary");
  check(summary().includes("句子 <b>2</b>") && summary().includes("已揭示 <b>1</b>"), "成绩汇总未按 items/revealedKeys 渲染", "summary");

  /* ── 行为路径 ⑤：选源（article 材料 → 选材料重拉榜单 → 回 all） ── */
  await L.setHardSource("article");
  check(
    reqs.some((r) => r.url === "/api/articles"),
    "选 article 未请求 GET /api/articles",
    "source_switch",
  );
  check(
    els["hs-material-bar"].innerHTML.includes("Goethe B2"),
    "article 源未渲染材料卡（/api/articles 标题）",
    "source_switch",
  );
  await L.pickHardMaterial(3);
  check(
    reqs.some((r) => r.url.startsWith("/api/syntax/hard-sentences") && r.url.includes("source_id=3")),
    "选材料后未按 source_id 重拉榜单",
    "source_switch",
  );
  check(stageText().includes("长难句 · 语料文章"), "选材料后未按 article 源渲染榜单头", "source_switch");
  await L.setHardSource("all");
  check(
    reqs.filter((r) => r.url.split("?")[0] === "/api/syntax/hard-sentences").length >= 3,
    "回 all 未重拉跨语料难度榜",
    "source_switch",
  );

  const domainProblems = DOMAINS.filter((d) => (failures[d] || []).length);
  return {
    problems: domainProblems.flatMap((d) => failures[d]),
    failures,
    checks,
    contracts: Object.fromEntries(DOMAINS.map((d) => [d, (failures[d] || []).length ? "fail" : "pass"])),
  };
}

/* ---- 变异验证：契约字段名改错，探针必须红（非恒真证明） --------------------- */
const MUTATIONS = [
  { name: "dimensions clause_depth 子键→clause_dep", cfg: { dimKey: "clause_dep" } },
  { name: "detail 响应删 analysis.topology", cfg: { noTopology: true } },
  { name: "榜单 item 缺 path", cfg: { dropPath: true } },
];

/* ---- 主流程：先主跑绿，再逐变异验证敏感 ------------------------------------ */
const base = await runScenarios({});
if (base.problems.length) {
  fail(
    `hard-sentences 契约钉死点被破坏（RED）：\n  - ${base.problems.join("\n  - ")}`,
  );
}

const mutations = [];
for (const { name, cfg } of MUTATIONS) {
  let r;
  try {
    r = await runScenarios(cfg);
  } catch (e) {
    r = { problems: [String(e)] };
  }
  if (!r.problems.length) {
    fail(
      `变异未捕获（探针恒真，死测！）：${name} 契约断裂重跑同一场景探针仍全绿 → 探针钉不住契约`,
    );
  }
  mutations.push({ name, caught: true, sample: r.problems[0] });
}

const out = {
  ok: true,
  file: "static/js/hard-sentences.js",
  contracts: base.contracts,
  probeChecks: base.checks,
  mutations,
};

if (JSON_MODE) {
  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
} else {
  console.log(`探针源：static/js/hard-sentences.js（逐字节进 vm，${SRC.length} 字符）`);
  console.log("契约域：");
  for (const [k, v] of Object.entries(base.contracts)) console.log(`  ${k}: ${v}`);
  console.log(`断言数：${base.checks}`);
  console.log("变异验证（契约断裂必须红）：");
  for (const m of mutations) console.log(`  ✅ ${m.name} → 已捕获（红）：「${m.sample}」`);
  console.log("✅ PASS: 四契约逐字段钉死，变异全部敏感，探针非恒真");
}