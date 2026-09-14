/**
 * test_listen_lab_probe.mjs —— 听力微训工坊前端行为探针（红线 11 契约钉死）
 *
 * 探针把 static/js/listen-lab.js 的**真源码**逐字节喂进 node:vm 的
 * SourceTextModule 真跑（不是复制品）：ESM 的 import 由自定义 linker 解析，
 * 桩掉 ./core.js（api/esc/notify）与 ./player.js（playGermanAudio）两个依赖，
 * 然后从模块命名空间驱动真实控制器（enterListenLab / selectListenMaterial /
 * setListenMode / listenSubmitDictation / listenNext / listenSkip / listenRestart /
 * listenSubmitCloze），把后端四契约逐字段钉死：
 *
 *   1. GET  /api/listen/materials            → {items:[{source_type,source_id,title,level}]}
 *   2. GET  /api/listen/materials/{st}/{id}  → {sentences:[str]}（建播放队列）
 *   3. POST /api/listen/diagnose body {expected,actual}
 *           → {tokens:[{token,status,hint}], correct, total, score}（六色反馈渲染）
 *   4. POST /api/listen/trials  body {mode,source_type,source_id,level,total,correct,duration_sec}
 *           → {trial_id}（成绩落盘路径）
 *
 * 行为路径：模式切换（L/D/C）→ 材料选择 → 播放队列推进 → 听写提交渲染 → 成绩汇总。
 *
 * 变异验证（探针非恒真证明）：内置 3 个变异用例，把契约字段名改错重跑同一场景，
 * 探针必须捕获断裂（problems > 0）——若任何变异未被捕获，探针自身退出码 1（红），
 * 证明它钉得住契约而非「字符串在不在」式死测：
 *   变异 1：diagnose 响应 status → stat
 *   变异 2：materials items 缺 title
 *   变异 3：material 详情 sentences 非数组
 *
 * 用法（参照 tools/wb_sync_probe.mjs 双模式）：
 *   node --experimental-vm-modules --no-warnings tests/test_listen_lab_probe.mjs
 *   node --experimental-vm-modules --no-warnings tests/test_listen_lab_probe.mjs --json   # pytest 用
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
const SRC = fs.readFileSync(path.join(ROOT, "static", "js", "listen-lab.js"), "utf8");

/* 真源码护栏：关键实现片段必须逐字存在（文件被换/被删/切歪 → 直接红） */
const MUST = [
  'import { api, esc, notify } from "./core.js"',
  'import { playGermanAudio } from "./player.js"',
  "/api/listen/materials",
  "/api/listen/diagnose",
  "/api/listen/trials",
  "export async function enterListenLab",
  "export async function selectListenMaterial",
  "export function setListenMode",
  "export async function listenSubmitDictation",
  "export function listenSubmitCloze",
  "export function listenRestart",
  "statCorrect",
  "statTotal",
  "duration_sec",
  "st-correct",
  "st-umlaut",
  "st-case",
  "st-inflection",
  "st-missing",
  "st-extra",
];
for (const m of MUST) {
  if (!SRC.includes(m)) fail(`listen-lab.js 里缺 "${m}" —— 探针钉的不是真源码（文件被换/被删）`);
}

/* ---- 契约场景数据（后端响应形状，字段名逐字对齐 delector/routes/listen.py）-- */
const SENTENCES = [
  "Der Mann geht in die Schule.",
  "Er lernt fleißig Deutsch.",
  "Die Kinder spielen im Garten.",
];

// 六值枚举全覆盖：correct/umlaut/case/inflection/missing/extra
const DIAG_TOKENS = [
  { token: "Der", status: "correct", hint: "完全正确" },
  { token: "man", status: "case", hint: "大小写" },
  { token: "geht", status: "correct", hint: "完全正确" },
  { token: "in", status: "correct", hint: "完全正确" },
  { token: "die", status: "extra", hint: "多余" },
  { token: "Schule", status: "umlaut", hint: "变音：ü→u" },
  { token: "Haus", status: "inflection", hint: "词尾" },
  { token: "str", status: "missing", hint: "缺少" },
];

function buildRes(cfg) {
  // cfg.statusKey：变异 1 —— diagnose 响应把 status 改名；缺省为 status
  const statusKey = cfg.statusKey || "status";
  const mkTokens = (arr) => arr.map((t) => ({ token: t.token, hint: t.hint, [statusKey]: t.status }));
  const items = [
    { source_type: "hoeren", source_id: 1, title: "Goethe A1", level: "A1" },
    { source_type: "encounter", source_id: 7, title: "Der Mann", level: "A2" },
  ];
  return {
    materials: {
      // 变异 2：materials items 缺 title
      items: cfg.dropTitle ? items.map(({ title, ...rest }) => rest) : items,
    },
    detail: cfg.badSentences
      ? // 变异 3：material 详情 sentences 非数组
        { source_type: "encounter", source_id: 7, title: "Der Mann", level: "A2", sentences: "nope" }
      : { source_type: "encounter", source_id: 7, title: "Der Mann", level: "A2", sentences: SENTENCES.slice() },
    diagResp1: {
      expected: SENTENCES[0],
      actual: "x",
      tokens: mkTokens(DIAG_TOKENS),
      correct: 3,
      total: 8,
      score: 0.375,
    },
    diagResp2: {
      expected: SENTENCES[2],
      actual: "x",
      tokens: mkTokens([
        { token: "Kinder", status: "correct", hint: "" },
        { token: "spielen", status: "correct", hint: "" },
      ]),
      correct: 2,
      total: 2,
      score: 1.0,
    },
    trials: { trial_id: 4242 },
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
  if (u === "/api/listen/materials") return globalThis.__probe.res.materials;
  if (u.indexOf("/api/listen/materials/") === 0) return globalThis.__probe.res.detail;
  if (u === "/api/listen/diagnose") {
    const i = (globalThis.__probe.diagCount = (globalThis.__probe.diagCount || 0) + 1);
    return i === 1 ? globalThis.__probe.res.diagResp1 : globalThis.__probe.res.diagResp2;
  }
  if (u === "/api/listen/trials") return globalThis.__probe.res.trials;
  throw new Error("探针 api 桩未覆盖 URL: " + url);
}
`;

const STUB_PLAYER = `
"use strict";
export async function playGermanAudio(text, rate) {
  globalThis.__probe.tts.push({ text: String(text), rate: rate });
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
    "materials",
    "detail_queue",
    "mode_switch",
    "diagnose_six_status",
    "trials_persist",
    "cloze_mode",
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
    "listen-stage",
    "listen-level-bar",
    "listen-material-bar",
    "listen-mode-bar",
    "listen-player-bar",
    "listen-score-card",
    "listen-status",
    "listen-dict-input",
    "listen-cloze-input",
  ]) {
    els[id] = makeEl(id);
  }

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
    setTimeout() {
      return 0;
    }, // 桩计时器：不真的推进（场景用 listenNext 显式驱动）
    clearTimeout() {},
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
    window: {
      // 有 speechSynthesis → _ttsUsable() 为真 → 走 playGermanAudio 桩
      speechSynthesis: { cancel() {}, getVoices() { return []; }, speak() {} },
    },
  });
  context.__probe = {
    reqs: [],
    tts: [],
    notifies: [],
    diagCount: 0,
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
    if (specifier === "./player.js") return stubModule(STUB_PLAYER);
    throw new Error("探针未提供依赖桩: " + specifier);
  });
  await real.evaluate();
  const L = real.namespace;

  const reqs = context.__probe.reqs;
  const tts = context.__probe.tts;
  const stage = () => els["listen-stage"].innerHTML;

  /* ── 行为路径 ①：进入工坊 → 材料清单契约 GET /api/listen/materials ── */
  await L.enterListenLab();
  check(
    reqs.some((r) => r.url === "/api/listen/materials"),
    "未请求 GET /api/listen/materials",
    "materials",
  );
  const matBar = els["listen-material-bar"].innerHTML;
  check(matBar.includes("Goethe A1"), "材料清单未渲染 title（hoeren）", "materials");
  check(matBar.includes("Der Mann"), "材料清单未渲染 title（encounter）", "materials");
  check(matBar.includes("A1") && matBar.includes("A2"), "材料清单未渲染 level", "materials");
  check(matBar.includes("hoeren") && matBar.includes("encounter"), "材料清单未渲染 source_type", "materials");

  /* ── 行为路径 ②：材料选择 → 播放队列推进（sentences:[str] 驱动） ── */
  await L.selectListenMaterial("encounter", 7);
  check(
    reqs.some((r) => r.url === "/api/listen/materials/encounter/7"),
    "未请求材料详情 GET /api/listen/materials/encounter/7",
    "detail_queue",
  );
  check(stage().includes("Der Mann geht in die Schule."), "播放队列未按 sentences[0] 渲染句子", "detail_queue");
  check(stage().includes("句 1 / 3"), "播放队列进度未按 sentences 长度渲染", "detail_queue");

  L.listenPlayToggle();
  check(tts.length === 1 && tts[0].text === SENTENCES[0], "播放队列推进未调用 playGermanAudio(sentences[0])", "detail_queue");
  check(tts[0] && tts[0].rate === 1.0, "playGermanAudio 未带默认语速 1.0", "detail_queue");
  check(els["listen-status"].textContent.includes("句 1 / 3"), "播放状态行未更新（队列推进）", "detail_queue");

  /* ── 行为路径 ③：模式切换 L→D（模式条三态 + 听写 UI） ── */
  const modeBar = els["listen-mode-bar"].innerHTML;
  check(
    modeBar.includes("🎧 精听/跟读") && modeBar.includes("✍️ 听写") && modeBar.includes("⬚ 填空"),
    "模式条未渲染 L/D/C 三态",
    "mode_switch",
  );
  L.setListenMode("D");
  check(stage().includes('id="listen-dict-input"'), "D 模式未渲染听写输入框", "mode_switch");
  check(stage().includes("🔒 原文已隐藏"), "D 模式未隐藏原文（听写语义）", "mode_switch");

  /* ── 行为路径 ④：听写提交 → 六色逐字反馈（POST /api/listen/diagnose） ── */
  els["listen-dict-input"].value = "Der man geht in die Schule.";
  await L.listenSubmitDictation();
  const diagReq = reqs.find((r) => r.url === "/api/listen/diagnose");
  check(Boolean(diagReq), "听写提交未请求 POST /api/listen/diagnose", "diagnose_six_status");
  check(diagReq && diagReq.method === "POST", "diagnose 请求方法不是 POST", "diagnose_six_status");
  if (diagReq) {
    const body = JSON.parse(diagReq.body);
    check(
      JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["actual", "expected"]),
      "diagnose body 顶层字段必须恰为 {expected, actual}",
      "diagnose_six_status",
    );
    check(body.expected === SENTENCES[0], "diagnose body.expected 未取当前句", "diagnose_six_status");
    check(body.actual === "Der man geht in die Schule.", "diagnose body.actual 未取输入框值", "diagnose_six_status");
  }
  const fbHtml = stage();
  for (const [st, cls] of [
    ["correct", "st-correct"],
    ["umlaut", "st-umlaut"],
    ["case", "st-case"],
    ["inflection", "st-inflection"],
    ["missing", "st-missing"],
    ["extra", "st-extra"],
  ]) {
    check(fbHtml.includes(cls), `六色反馈缺 ${st} 的样式类 ${cls}`, "diagnose_six_status");
  }
  check(fbHtml.includes('title="变音：ü→u"'), "反馈未渲染 hint（title 属性）", "diagnose_six_status");
  check(fbHtml.includes("✓ 3 / 8 词"), "反馈统计未按 correct/total 渲染", "diagnose_six_status");

  /* ── 行为路径 ⑤：跳过不计分 → 成绩累加 → 会话结束落盘 POST /api/listen/trials ── */
  L.listenNext(); // idx 1
  L.listenSkip(); // 跳过 s1：不计成绩
  check(stage().includes("↷"), "跳过句未渲染 ↷ 标记", "trials_persist");
  els["listen-dict-input"].value = "Die Kinder spielen im Garten.";
  await L.listenSubmitDictation(); // idx 2：correct 2 / total 2
  L.listenNext(); // idx 3 ≥ len → _finishSession

  const trialReq = reqs.find((r) => r.url === "/api/listen/trials");
  check(Boolean(trialReq), "会话结束未 POST /api/listen/trials", "trials_persist");
  if (trialReq) {
    const body = JSON.parse(trialReq.body);
    check(
      JSON.stringify(Object.keys(body).sort()) ===
        JSON.stringify(["correct", "duration_sec", "level", "mode", "source_id", "source_type", "total"]),
      "trials body 字段必须恰为七字段 {mode,source_type,source_id,level,total,correct,duration_sec}",
      "trials_persist",
    );
    check(body.mode === "dictation", "D 模式 trials.mode 应为 dictation", "trials_persist");
    check(
      body.source_type === "encounter" && body.source_id === 7 && body.level === "A2",
      "trials 材料标识字段（source_type/source_id/level）未透传",
      "trials_persist",
    );
    check(
      body.total === 10 && body.correct === 5,
      "trials 成绩未按 correct/total 累加（3+2 / 8+2，跳过不计分）",
      "trials_persist",
    );
    check(Number.isInteger(body.duration_sec) && body.duration_sec >= 1, "trials.duration_sec 必须为 ≥1 整数", "trials_persist");
  }
  const scoreCard = els["listen-score-card"].innerHTML;
  check(scoreCard.includes("正确 <b>5</b>") && scoreCard.includes("总计 <b>10</b>"), "成绩卡未渲染 statCorrect/statTotal", "trials_persist");
  check(scoreCard.includes("50%"), "成绩卡百分比未按 correct/total 计算", "trials_persist");

  /* ── 行为路径 ⑥：C 模式（重开 → 填空 → 错答 → 结束落盘 mode=cloze） ── */
  L.listenRestart();
  L.setListenMode("C");
  check(stage().includes('id="listen-cloze-input"'), "C 模式未渲染填空输入框", "cloze_mode");
  check(stage().includes("listen-blank"), "C 模式未按挖空渲染 ___ 占位", "cloze_mode");
  els["listen-cloze-input"].value = "Mann"; // s0 正确答案
  L.listenSubmitCloze();
  L.listenNext(); // s1 仅 4 词 → 无可挖词
  check(stage().includes("本句无可挖词"), "短句无可挖词路径未渲染提示", "cloze_mode");
  L.listenNext(); // s2
  els["listen-cloze-input"].value = "Kind"; // 错答（答案 Kinder）
  L.listenSubmitCloze();
  check(stage().includes("✗ 答案：Kinder"), "C 模式错答未渲染答案揭示", "cloze_mode");
  L.listenNext(); // finish
  const trialReqC = reqs.filter((r) => r.url === "/api/listen/trials").pop();
  check(Boolean(trialReqC), "C 模式会话结束未 POST /api/listen/trials", "cloze_mode");
  if (trialReqC) {
    const body = JSON.parse(trialReqC.body);
    check(body.mode === "cloze", "C 模式 trials.mode 应为 cloze", "cloze_mode");
    check(body.total === 2 && body.correct === 1, "C 模式成绩未按句对错累加", "cloze_mode");
  }

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
  { name: "diagnose 响应 status→stat", cfg: { statusKey: "stat" } },
  { name: "materials items 缺 title", cfg: { dropTitle: true } },
  { name: "material 详情 sentences 非数组", cfg: { badSentences: true } },
];

/* ---- 主流程：先主跑绿，再逐变异验证敏感 ------------------------------------ */
const base = await runScenarios({});
if (base.problems.length) {
  fail(
    `listen-lab 契约钉死点被破坏（RED）：\n  - ${base.problems.join("\n  - ")}`,
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
  file: "static/js/listen-lab.js",
  contracts: base.contracts,
  probeChecks: base.checks,
  mutations,
};

if (JSON_MODE) {
  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
} else {
  console.log(`探针源：static/js/listen-lab.js（逐字节进 vm，${SRC.length} 字符）`);
  console.log("契约域：");
  for (const [k, v] of Object.entries(base.contracts)) console.log(`  ${k}: ${v}`);
  console.log(`断言数：${base.checks}`);
  console.log("变异验证（契约断裂必须红）：");
  for (const m of mutations) console.log(`  ✅ ${m.name} → 已捕获（红）：「${m.sample}」`);
  console.log("✅ PASS: 四契约逐字段钉死，变异全部敏感，探针非恒真");
}
