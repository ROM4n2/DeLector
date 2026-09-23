/**
 * wb_enc_i1_probe.mjs —— 遇见区 i+1 就近选材纯函数行为探针
 * （2026-09-23 遇见区 i+1 补齐 · Phase B · Task 4）
 *
 * 为什么需要它（项目红线 11）：跨边界契约（区间阈值 / 覆盖率分母口径 / 排序与纯度 /
 * topPick）只有**真跑真实源码**才算数——字符串存在式断言是死测。本探针读
 * static/js/enc-i1.js 的**真实源码**，按既有切法（见 tools/wb_rich_backfill_probe.mjs
 * 的「不重抄实现、把真源码注入 node:vm 沙箱」纪律）去掉冗余的 ESM `export` 关键字后
 * 注入 node:vm 沙箱执行，注入桩 knownSet，逐场景钉死契约。
 *
 * 硬约束：探针内**不得重抄一份实现**；一切被测逻辑均来自 enc-i1.js 真实源码切片。
 *
 * 用法：
 *   node tools/wb_enc_i1_probe.mjs            # 每场景打印 PASS/FAIL；有失败则退出码 1
 *   node tools/wb_enc_i1_probe.mjs --json     # stdout 只输出单个 JSON
 *     {"failures": <int>, "total": <int>, "cases": [{"name","ok","detail"}]}
 *   有失败时退出码仍为 1（CI / pytest 双保险）。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SRC_PATH = path.join(ROOT, "static", "js", "enc-i1.js");
const JSON_MODE = process.argv.includes("--json");

/* ---------------------------------------------------------------------------
 * 1. 结果收集
 * ------------------------------------------------------------------------ */
const cases = [];
let failures = 0;
function check(name, ok, detail) {
  const good = !!ok;
  cases.push({ name: name, ok: good, detail: detail == null ? "" : String(detail) });
  if (!good) failures++;
  if (!JSON_MODE) {
    console.log(good ? "PASS  " + name : "FAIL  " + name + (detail ? "  —  " + detail : ""));
  }
}

/* 删注释（保留字符串字面量），用于「源码契约」防死测断言，避免注释误命中。 */
function stripComments(src) {
  let out = "";
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (c === "/" && n === "*") {
      const j = src.indexOf("*/", i + 2);
      i = j < 0 ? src.length : j + 2;
      continue;
    }
    if (c === "/" && n === "/") {
      const j = src.indexOf("\n", i + 2);
      i = j < 0 ? src.length : j;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      out += c;
      i++;
      while (i < src.length) {
        out += src[i];
        if (src[i] === "\\") {
          out += src[i + 1] || "";
          i += 2;
          continue;
        }
        if (src[i] === q) {
          i++;
          break;
        }
        i++;
      }
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

/* ---------------------------------------------------------------------------
 * 2. 读取并加载真实源码（去 ESM `export ` 后注入沙箱）
 * ------------------------------------------------------------------------ */
let loadError = null;
let code = "";
let ctx = null;
try {
  if (!fs.existsSync(SRC_PATH)) throw new Error("源码不存在：" + SRC_PATH);
  const raw = fs.readFileSync(SRC_PATH, "utf8");
  if (!raw || raw.length < 200) throw new Error("源码过短，疑似空文件");
  code = stripComments(raw);
  // 契约存在性：真实源码必须仍导出全部 6 个符号（防「切歪 / 传空实现」）。
  if (!/export\s+const\s+I1_BANDS\s*=/.test(code)) {
    throw new Error("缺少 export const I1_BANDS（契约缺失）");
  }
  for (const fn of ["bandOf", "coverageOf", "rankEntries", "topPick", "hasCoverage"]) {
    if (!new RegExp("export\\s+function\\s+" + fn + "\\s*\\(").test(code)) {
      throw new Error("缺少 export function " + fn + "（契约缺失）");
    }
  }
  if (/\bimport\b/.test(code)) throw new Error("enc-i1.js 不得含 import（零依赖纪律）");
  // 去 ESM export 关键字后即可作为 classic Script 注入 vm（共享内部 helper 一并保留）。
  const sandboxSource = raw.replace(/^export\s+/gm, "");
  ctx = vm.createContext({});
  vm.runInContext(sandboxSource, ctx, { filename: "enc-i1.sandbox.js" });
} catch (err) {
  loadError = err && err.message ? err.message : String(err);
}

/* ---------------------------------------------------------------------------
 * 3. 场景
 * ------------------------------------------------------------------------ */
const SCENARIO_NAMES = [
  "S1 区间边界 bandOf",
  "S2 区间边界 coverageOf → band",
  "S3 排序：分组 + rate 降序 + 同分 id 升序",
  "S4 available=false 排最后",
  "S5 topPick",
  "S6 纯度（不改入参）",
  "S7 hasCoverage",
  "S8 分母语义（total_tokens 而非 lemma_seq.length）",
  "S9 available 判据（坏输入降级不抛）",
];

const K = "k";
const U = "u";
/** 构造长度 len、前 knownN 个为已知词 K、其余为 U 的 lemma_seq。 */
function buildSeq(knownN, len) {
  const a = [];
  for (let i = 0; i < len; i++) a.push(i < knownN ? K : U);
  return a;
}

function ev(expression) {
  return vm.runInContext(expression, ctx);
}
function covWith(knownArr, entry) {
  ctx.__knownArr = knownArr;
  ctx.__entry = entry;
  return ev("coverageOf(new Set(__knownArr), __entry)");
}
function rankWith(knownArr, entries) {
  ctx.__knownArr = knownArr;
  ctx.__entries = entries;
  return ev("rankEntries(new Set(__knownArr), __entries)");
}

function runScenarios() {
  /* ---- S1 区间边界：逐条钉死 bandOf ---- */
  const bf = ev("bandOf");
  check("S1 区间边界 bandOf(0.84) === hard", bf(0.84) === "hard", "got " + bf(0.84));
  check("S1 区间边界 bandOf(0.85) === i1", bf(0.85) === "i1", "got " + bf(0.85));
  check("S1 区间边界 bandOf(0.96) === i1", bf(0.96) === "i1", "got " + bf(0.96));
  check("S1 区间边界 bandOf(0.97) === easy", bf(0.97) === "easy", "got " + bf(0.97));
  check(
    "S1 I1_BANDS 常量单点定义（0.85 / 0.97 / ±Infinity）",
    ev("I1_BANDS.i1[0]") === 0.85 &&
      ev("I1_BANDS.i1[1]") === 0.97 &&
      ev("I1_BANDS.easy[0]") === 0.97 &&
      ev("I1_BANDS.easy[1] === Infinity") === true &&
      ev("I1_BANDS.hard[1]") === 0.85 &&
      ev("I1_BANDS.hard[0] === -Infinity") === true,
    JSON.stringify({
      i1: [ev("I1_BANDS.i1[0]"), ev("I1_BANDS.i1[1]")],
      easy0: ev("I1_BANDS.easy[0]"),
      hard1: ev("I1_BANDS.hard[1]"),
    })
  );

  /* ---- S2 coverageOf 由 rate 派生的 band 与边界一致 ---- */
  for (const [known, expBand] of [[84, "hard"], [85, "i1"], [96, "i1"], [97, "easy"]]) {
    const cov = covWith([K], { id: 1, total_tokens: 100, lemma_seq: buildSeq(known, 100) });
    check(
      "S2 区间边界 coverageOf rate=" + known / 100 + " → band " + expBand,
      cov.available === true &&
        cov.knownTokens === known &&
        cov.totalTokens === 100 &&
        cov.rate === known / 100 &&
        cov.band === expBand,
      JSON.stringify({ knownTokens: cov.knownTokens, totalTokens: cov.totalTokens, rate: cov.rate, band: cov.band })
    );
  }

  /* ---- S3 排序分组 + 组内 rate 降序 + 同分 id 升序 ---- */
  const entries3 = [
    { id: 10, total_tokens: 100, lemma_seq: buildSeq(90, 100) }, // i1  rate .90
    { id: 2, total_tokens: 100, lemma_seq: buildSeq(90, 100) }, // i1  rate .90（与 10 同分）
    { id: 7, total_tokens: 100, lemma_seq: buildSeq(95, 100) }, // i1  rate .95
    { id: 5, total_tokens: 100, lemma_seq: buildSeq(99, 100) }, // easy rate .99
    { id: 1, total_tokens: 100, lemma_seq: buildSeq(50, 100) }, // hard rate .50
  ];
  const ranked3 = rankWith([K], entries3);
  const ids3 = Array.from(ranked3, (r) => r.id);
  const bands3 = Array.from(ranked3, (r) => r.band);
  check(
    "S3 排序：i1(rate 降序/id 升序) → easy → hard，id 顺序 [7,2,10,5,1]",
    JSON.stringify(ids3) === JSON.stringify([7, 2, 10, 5, 1]),
    "ids=" + JSON.stringify(ids3)
  );
  check(
    "S3 分组顺序 band = [i1,i1,i1,easy,hard]（i1 组在 easy 前、hard 后）",
    JSON.stringify(bands3) === JSON.stringify(["i1", "i1", "i1", "easy", "hard"]),
    "bands=" + JSON.stringify(bands3)
  );
  const i1Rates3 = ranked3.filter((r) => r.band === "i1").map((r) => r.rate);
  check(
    "S3 i1 组内 rate 降序",
    i1Rates3.length === 3 && i1Rates3.every((v, i) => i === 0 || i1Rates3[i - 1] >= v),
    JSON.stringify(i1Rates3)
  );
  check(
    "S3 同分按 id 升序（id 2 在 id 10 之前）",
    ids3.indexOf(2) >= 0 && ids3.indexOf(10) >= 0 && ids3.indexOf(2) < ids3.indexOf(10),
    JSON.stringify(ids3)
  );

  /* ---- S4 available=false 一律排最后，其内部保持入参相对顺序 ---- */
  const entries4 = [
    { id: 1, total_tokens: 100, lemma_seq: buildSeq(90, 100) }, // i1
    { id: 2, total_tokens: 100, lemma_seq: null }, // unavailable（lemma_seq 非数组）
    { id: 3, total_tokens: 0, lemma_seq: buildSeq(0, 10) }, // unavailable（total_tokens 非正）
    { id: 4, total_tokens: 100, lemma_seq: buildSeq(99, 100) }, // easy
    { id: 5 }, // unavailable（无字段）
    { id: 6, total_tokens: null, lemma_seq: buildSeq(90, 100) }, // unavailable（total_tokens=null：索引端点对未分析行的真实形态）
  ];
  const ranked4 = rankWith([K], entries4);
  const ids4 = Array.from(ranked4, (r) => r.id);
  check(
    "S4 available=false 排最后且内部保持入参相对顺序 → [1,4,2,3,5,6]",
    JSON.stringify(ids4) === JSON.stringify([1, 4, 2, 3, 5, 6]),
    "ids=" + JSON.stringify(ids4)
  );
  check(
    "S4 available=false 条目 band===null 且 rate===0",
    ranked4.filter((r) => !r.available).length === 4 &&
      ranked4.filter((r) => !r.available).every((r) => r.band === null && r.rate === 0),
    JSON.stringify(Array.from(ranked4, (r) => ({ id: r.id, available: r.available, band: r.band })))
  );
  check(
    "S4 total_tokens=null（未分析行真实形态）降级且排最后（ranked 末位 id===6）",
    ranked4.length === 6 &&
      ranked4[ranked4.length - 1].id === 6 &&
      ranked4[ranked4.length - 1].available === false,
    JSON.stringify(ids4)
  );

  /* ---- S5 topPick ---- */
  const tp = ev("topPick");
  const first = tp(ranked3);
  check("S5 topPick 有 i1 → 返回首条（id 7）", first !== null && first.id === 7, "id=" + (first && first.id));
  check(
    "S5 topPick 只有 easy/hard → null",
    tp([{ band: "easy" }, { band: "hard" }]) === null,
    "got " + JSON.stringify(tp([{ band: "easy" }, { band: "hard" }]))
  );
  check("S5 topPick 空数组 → null", tp([]) === null, "got " + tp([]));
  check("S5 topPick 非数组 → null", tp(null) === null, "got " + tp(null));

  /* ---- S6 纯度：返回新数组，且入参数组与其元素未被改动 ---- */
  const entries6 = [
    { id: 3, total_tokens: 100, lemma_seq: buildSeq(99, 100) },
    { id: 1, total_tokens: 100, lemma_seq: buildSeq(90, 100) },
    { id: 2, total_tokens: 100, lemma_seq: null },
  ];
  const before6 = JSON.stringify(entries6);
  const ranked6 = rankWith([K], entries6);
  const after6 = JSON.stringify(entries6);
  check("S6 纯度：rankEntries 返回新数组（非入参引用）", ranked6 !== entries6, "same=" + (ranked6 === entries6));
  check(
    "S6 纯度：rankEntries 不改入参数组与元素（调用前快照深比较）",
    before6 === after6,
    "before=" + before6 + " after=" + after6
  );
  check("S6 纯度：rankEntries 不丢条目（长度不变）", ranked6.length === entries6.length, "len=" + ranked6.length);
  check(
    "S6 纯度：入参未被就地排序（仍为原序 3,1,2）",
    entries6.map((e) => e.id).join(",") === "3,1,2",
    entries6.map((e) => e.id).join(",")
  );

  /* ---- S7 hasCoverage ---- */
  const hc = ev("hasCoverage");
  check("S7 hasCoverage 空 Set → false", hc(new Set()) === false, "got " + hc(new Set()));
  check("S7 hasCoverage 非空 Set → true", hc(new Set(["a"])) === true, "got " + hc(new Set(["a"])));

  /* ---- S8 分母语义：rate 用 total_tokens，不是 lemma_seq.length ---- */
  const cov8 = covWith([K], { id: 1, total_tokens: 200, lemma_seq: buildSeq(85, 100) });
  check(
    "S8 分母用 total_tokens（85/200=0.425，band hard）而非 lemma_seq.length（85/100=0.85）",
    cov8.knownTokens === 85 && cov8.totalTokens === 200 && cov8.rate === 0.425 && cov8.band === "hard",
    JSON.stringify({ knownTokens: cov8.knownTokens, totalTokens: cov8.totalTokens, rate: cov8.rate, band: cov8.band })
  );
  check("S8 rate 不等于 0.85（用 lemma_seq.length 才会变 0.85）", cov8.rate !== 0.85, "rate=" + cov8.rate);

  /* ---- S9 available 判据：坏输入降级不抛 ---- */
  const covNull = covWith([K], null);
  check(
    "S9 entry=null → 降级 {available:false,knownTokens:0,totalTokens:0,rate:0,band:null}",
    covNull.available === false &&
      covNull.knownTokens === 0 &&
      covNull.totalTokens === 0 &&
      covNull.rate === 0 &&
      covNull.band === null,
    JSON.stringify(covNull)
  );
  check("S9 entry 非对象（number）→ available=false", covWith([K], 42).available === false, "");
  check(
    "S9 total_tokens=0 → available=false",
    covWith([K], { total_tokens: 0, lemma_seq: buildSeq(1, 1) }).available === false,
    ""
  );
  check(
    "S9 total_tokens 负数 → available=false",
    covWith([K], { total_tokens: -5, lemma_seq: buildSeq(1, 1) }).available === false,
    ""
  );
  check(
    "S9 total_tokens 缺失 → available=false",
    covWith([K], { lemma_seq: buildSeq(1, 1) }).available === false,
    ""
  );
  const covTotalNull = covWith([K], { id: 9, total_tokens: null, lemma_seq: buildSeq(1, 1) });
  check(
    "S9 total_tokens=null（索引端点未分析行的真实形态）→ 降级 {available:false,band:null,rate:0,totalTokens:0}",
    covTotalNull.available === false &&
      covTotalNull.band === null &&
      covTotalNull.rate === 0 &&
      covTotalNull.totalTokens === 0 &&
      covTotalNull.knownTokens === 0,
    JSON.stringify(covTotalNull)
  );
  check(
    "S9 total_tokens 为字符串 → available=false",
    covWith([K], { total_tokens: "100", lemma_seq: buildSeq(1, 1) }).available === false,
    ""
  );
  check(
    "S9 lemma_seq 非数组 → available=false",
    covWith([K], { total_tokens: 100, lemma_seq: "x" }).available === false,
    ""
  );

  /* ---- 源码契约防死测：切到的必须是真实现 ---- */
  check("源码契约：分母为 entry.total_tokens（防死测）", /entry\.total_tokens/.test(code), "");
  check(
    "源码契约：命中判定 knownSet.has(String(...).toLowerCase())",
    /knownSet\.has\(\s*String\([^)]*\)\.toLowerCase\(\)\s*\)/.test(code),
    ""
  );
}

if (loadError) {
  for (const name of SCENARIO_NAMES) check(name, false, "源码未加载：" + loadError);
} else {
  runScenarios();
}

/* ---------------------------------------------------------------------------
 * 4. 输出
 * ------------------------------------------------------------------------ */
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ failures: failures, total: cases.length, cases: cases }));
} else {
  console.log("");
  if (failures > 0) console.log("FAIL 汇总：" + failures + " 个断言未通过");
  else console.log("ALL PASS：enc-i1 覆盖率 / 分区间 / 排序 / 推荐 行为自检通过");
}
process.exitCode = failures > 0 ? 1 : 0;
