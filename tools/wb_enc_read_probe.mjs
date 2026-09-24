/**
 * wb_enc_read_probe.mjs —— 遇见区「已读状态」纯函数行为探针
 * （遇见区已读状态 · Task 1）
 *
 * 为什么需要它（项目红线 11）：跨边界契约（幂等不写盘 / 坏 JSON 降级不抛 /
 * 取首个未读 / 纯度）只有**真跑真实源码**才算数——字符串存在式断言是死测。
 * 本探针读 static/js/enc-read.js 的**真实源码**，按既有切法（见
 * tools/wb_enc_i1_probe.mjs 的「不重抄实现、把真源码注入 node:vm 沙箱」纪律）
 * 去掉冗余的 ESM `export` 关键字后注入 node:vm 沙箱执行，注入桩 storage，
 * 逐场景钉死契约。
 *
 * 硬约束：探针内**不得重抄一份实现**；一切被测逻辑均来自 enc-read.js 真实源码切片。
 *
 * 用法：
 *   node tools/wb_enc_read_probe.mjs            # 每场景打印 PASS/FAIL；有失败则退出码 1
 *   node tools/wb_enc_read_probe.mjs --json     # stdout 只输出单个 JSON
 *     {"failures": <int>, "total": <int>, "cases": [{"name","ok","detail"}]}
 *   有失败时退出码仍为 1（CI / pytest 双保险）。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SRC_PATH = path.join(ROOT, "static", "js", "enc-read.js");
const JSON_MODE = process.argv.includes("--json");

/** 与模块 READ_KEY 必须逐字一致的存储键（探针侧单点，用于 seed / 快照断言）。 */
const STORAGE_KEY = "delector_encounter_read_v1";

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
  if (!/export\s+const\s+READ_KEY\s*=/.test(code)) {
    throw new Error("缺少 export const READ_KEY（契约缺失）");
  }
  for (const fn of ["loadRead", "markRead", "isRead", "unmarkRead", "pickUnread"]) {
    if (!new RegExp("export\\s+function\\s+" + fn + "\\s*\\(").test(code)) {
      throw new Error("缺少 export function " + fn + "（契约缺失）");
    }
  }
  if (/\bimport\b/.test(code)) throw new Error("enc-read.js 不得含 import（零依赖纪律）");
  // 去 ESM export 关键字后即可作为 classic Script 注入 vm（共享内部 helper 一并保留）。
  const sandboxSource = raw.replace(/^export\s+/gm, "");
  ctx = vm.createContext({});
  vm.runInContext(sandboxSource, ctx, { filename: "enc-read.sandbox.js" });
} catch (err) {
  loadError = err && err.message ? err.message : String(err);
}

/* ---------------------------------------------------------------------------
 * 3. 桩 storage（内部 Map；可统计 setItem 调用次数与最终字符串快照）
 * ------------------------------------------------------------------------ */
/** 正常桩：形状 {getItem,setItem,removeItem}；另暴露 seed/raw/setCount 供断言。 */
function makeStorage() {
  const map = new Map();
  let setCount = 0;
  let removeCount = 0;
  const stub = {
    getItem: function (k) {
      return map.has(k) ? map.get(k) : null;
    },
    setItem: function (k, v) {
      setCount++;
      map.set(k, String(v));
    },
    removeItem: function (k) {
      removeCount++;
      map.delete(k);
    },
  };
  return {
    storage: stub,
    raw: function () {
      return map.has(STORAGE_KEY) ? map.get(STORAGE_KEY) : null;
    },
    has: function (k) {
      return map.has(k);
    },
    seed: function (v) {
      map.set(STORAGE_KEY, v);
    },
    setCount: function () {
      return setCount;
    },
    removeCount: function () {
      return removeCount;
    },
  };
}

/** 写盘必抛桩：模拟 setItem 抛异常（如 QuotaExceededError）。 */
function makeThrowingStorage() {
  const map = new Map();
  return {
    getItem: function (k) {
      return map.has(k) ? map.get(k) : null;
    },
    setItem: function () {
      throw new Error("QuotaExceededError");
    },
    removeItem: function (k) {
      map.delete(k);
    },
  };
}

/* ---------------------------------------------------------------------------
 * 4. 场景
 * ------------------------------------------------------------------------ */
const SCENARIO_NAMES = [
  "S1 空态（无键 / 坏 JSON / 非对象）",
  "S2 幂等（已读不写盘）",
  "S3 多篇（时间戳）",
  "S4 isRead",
  "S5 unmarkRead",
  "S6 pickUnread",
  "S7 写盘失败",
  "S8 schema 版本号（v 写侧不漂移 / 读侧透传）",
];

function ev(expression) {
  return vm.runInContext(expression, ctx);
}
/** 把「模块不抛」变成可断言的结果：ok=false 即抛出（契约违约）。 */
function attempt(fn) {
  try {
    return { ok: true, value: fn() };
  } catch (e) {
    return { ok: false, error: e && e.message ? e.message : String(e) };
  }
}
function callLoad(handle) {
  ctx.__s = handle.storage;
  return ev("loadRead(__s)");
}
function callMark(handle, id, nowMs) {
  ctx.__s = handle.storage;
  ctx.__id = id;
  ctx.__now = nowMs;
  return ev("markRead(__s, __id, __now)");
}
function callIsRead(state, id) {
  ctx.__st = state;
  ctx.__id = id;
  return ev("isRead(__st, __id)");
}
function callUnmark(handle, id) {
  ctx.__s = handle.storage;
  ctx.__id = id;
  return ev("unmarkRead(__s, __id)");
}
function callPick(ranked, state) {
  ctx.__ranked = ranked;
  ctx.__st = state;
  return ev("pickUnread(__ranked, __st)");
}
/** 构造读态 {v:1, read:{[String(id)]:1}}（仅用于 isRead/pickUnread 的注入）。 */
function stateWith(ids) {
  const read = {};
  for (const id of ids) read[String(id)] = 1;
  return { v: 1, read: read };
}
/** 读态是否为空（{v:1, read:{}}）。 */
function isEmptyState(s) {
  return !!s && s.v === 1 && s.read && typeof s.read === "object" && Object.keys(s.read).length === 0;
}

function runScenarios() {
  /* ---- S1 空态：无键 / 坏 JSON / 非对象 一律降级 {v:1,read:{}} 且不抛 ---- */
  const h1a = makeStorage();
  const r1a = attempt(function () {
    return callLoad(h1a);
  });
  check(
    "S1 空态 无键 → loadRead 返回 {v:1,read:{}} 且不抛",
    r1a.ok && isEmptyState(r1a.value),
    r1a.ok ? JSON.stringify(r1a.value) : "THREW: " + r1a.error
  );

  const h1b = makeStorage();
  h1b.seed("{bad");
  const r1b = attempt(function () {
    return callLoad(h1b);
  });
  check(
    "S1 空态 坏 JSON('{bad') → 降级空态且不抛",
    r1b.ok && isEmptyState(r1b.value),
    r1b.ok ? JSON.stringify(r1b.value) : "THREW: " + r1b.error
  );

  const h1c = makeStorage();
  h1c.seed("[1,2]");
  const r1c = attempt(function () {
    return callLoad(h1c);
  });
  check(
    "S1 空态 非对象('[1,2]') → 降级空态且不抛",
    r1c.ok && isEmptyState(r1c.value),
    r1c.ok ? JSON.stringify(r1c.value) : "THREW: " + r1c.error
  );

  const r1d = attempt(function () {
    ctx.__s = null;
    return ev("loadRead(__s)");
  });
  check(
    "S1 空态 storage=null → 降级空态且不抛",
    r1d.ok && isEmptyState(r1d.value),
    r1d.ok ? JSON.stringify(r1d.value) : "THREW: " + r1d.error
  );

  /* ---- S2 幂等：已读 → false 且不写盘（逐字节不变 + setItem 计数不变） ---- */
  const h2 = makeStorage();
  const r2first = attempt(function () {
    return callMark(h2, "7", 1000);
  });
  check(
    "S2 幂等 首次 markRead('7',1000) → true 且存储含 7",
    r2first.ok && r2first.value === true && h2.has(STORAGE_KEY) && /"7":1000/.test(String(h2.raw())),
    r2first.ok ? "value=" + r2first.value + " raw=" + h2.raw() : "THREW: " + r2first.error
  );
  const snapBefore = h2.raw();
  const countBefore = h2.setCount();
  const r2second = attempt(function () {
    return callMark(h2, "7", 2000);
  });
  check(
    "S2 幂等 再次 markRead('7',2000) → false",
    r2second.ok && r2second.value === false,
    r2second.ok ? "value=" + r2second.value : "THREW: " + r2second.error
  );
  check(
    "S2 幂等 已读不写盘：存储字符串逐字节不变",
    h2.raw() === snapBefore,
    "before=" + snapBefore + " after=" + h2.raw()
  );
  check(
    "S2 幂等 已读不写盘：setItem 调用次数未增加",
    h2.setCount() === countBefore,
    "before=" + countBefore + " after=" + h2.setCount()
  );

  /* ---- S3 多篇：连续标记 1/2/3，read 含 3 键且时间戳与注入 nowMs 一致 ---- */
  const h3 = makeStorage();
  callMark(h3, "1", 1000);
  callMark(h3, "2", 2000);
  callMark(h3, "3", 3000);
  const st3 = attempt(function () {
    return callLoad(h3);
  });
  const read3 = st3.ok ? st3.value.read : null;
  check(
    "S3 多篇 read 含 3 键",
    !!read3 && Object.keys(read3).length === 3 && "1" in read3 && "2" in read3 && "3" in read3,
    read3 ? JSON.stringify(read3) : "THREW: " + st3.error
  );
  check(
    "S3 多篇 各时间戳与注入 nowMs 一致（1000/2000/3000）",
    !!read3 && read3["1"] === 1000 && read3["2"] === 2000 && read3["3"] === 3000,
    read3 ? JSON.stringify(read3) : "THREW: " + st3.error
  );

  /* ---- S4 isRead：命中 true / 未命中 false / id=null false / 空 state false ---- */
  const h4 = makeStorage();
  callMark(h4, "7", 1000);
  const st4 = callLoad(h4);
  check("S4 isRead 命中 true", callIsRead(st4, "7") === true, "got " + callIsRead(st4, "7"));
  check("S4 isRead 未命中 false", callIsRead(st4, "999") === false, "got " + callIsRead(st4, "999"));
  check("S4 isRead id=null → false", callIsRead(st4, null) === false, "got " + callIsRead(st4, null));
  check("S4 isRead 空 state → false", callIsRead({}, "7") === false, "got " + callIsRead({}, "7"));
  check("S4 isRead state=null → false", callIsRead(null, "7") === false, "got " + callIsRead(null, "7"));

  /* ---- S5 unmarkRead：删已存在 true 且键消失；删不存在 false 且不写盘 ---- */
  const h5 = makeStorage();
  callMark(h5, "1", 1000);
  const r5del = attempt(function () {
    return callUnmark(h5, "1");
  });
  const st5 = callLoad(h5);
  check(
    "S5 unmarkRead 删已存在 → true",
    r5del.ok && r5del.value === true,
    r5del.ok ? "value=" + r5del.value : "THREW: " + r5del.error
  );
  check(
    "S5 unmarkRead 删已存在 → 键消失",
    !("1" in st5.read),
    JSON.stringify(st5.read)
  );
  const snap5 = h5.raw();
  const count5 = h5.setCount();
  const r5miss = attempt(function () {
    return callUnmark(h5, "999");
  });
  check(
    "S5 unmarkRead 删不存在 → false",
    r5miss.ok && r5miss.value === false,
    r5miss.ok ? "value=" + r5miss.value : "THREW: " + r5miss.error
  );
  check(
    "S5 unmarkRead 删不存在 → 不写盘（存储字符串逐字节不变）",
    h5.raw() === snap5 && h5.setCount() === count5,
    "rawBefore=" + snap5 + " rawAfter=" + h5.raw() + " setCount=" + h5.setCount()
  );

  /* ---- S6 pickUnread：首个未读 / 跳过已读 / 全已读 null / 非数组 null / 纯度 ---- */
  const ranked6 = [{ id: "a" }, { id: "b" }, { id: "c" }];
  const p1 = attempt(function () {
    return callPick(ranked6, stateWith([]));
  });
  check(
    "S6 pickUnread 全未读 → 首条（id=a）",
    p1.ok && p1.value === ranked6[0] && p1.value.id === "a",
    p1.ok ? "id=" + (p1.value && p1.value.id) : "THREW: " + p1.error
  );
  check(
    "S6 pickUnread 首条已读 → 第二条（id=b）",
    callPick(ranked6, stateWith(["a"])).id === "b",
    "id=" + callPick(ranked6, stateWith(["a"])).id
  );
  check(
    "S6 pickUnread 连续跳过多个已读 → id=c",
    callPick(ranked6, stateWith(["a", "b"])).id === "c",
    "id=" + callPick(ranked6, stateWith(["a", "b"])).id
  );
  check(
    "S6 pickUnread 全已读 → null",
    callPick(ranked6, stateWith(["a", "b", "c"])) === null,
    "got " + JSON.stringify(callPick(ranked6, stateWith(["a", "b", "c"])))
  );
  check("S6 pickUnread ranked 非数组 → null", callPick(null, stateWith([])) === null, "got " + callPick(null, stateWith([])));
  check("S6 pickUnread ranked 空数组 → null", callPick([], stateWith([])) === null, "got " + callPick([], stateWith([])));

  const before6 = JSON.stringify(ranked6);
  callPick(ranked6, stateWith(["a"]));
  const after6 = JSON.stringify(ranked6);
  check(
    "S6 纯度 pickUnread 不改入参数组及其元素（深比较相等）",
    before6 === after6 && ranked6.length === 3,
    "before=" + before6 + " after=" + after6
  );

  /* ---- S7 写盘失败：setItem 抛异常 / storage=null / storage 非对象 → false 且不抛 ---- */
  const ht = makeThrowingStorage();
  const r7a = attempt(function () {
    ctx.__s = ht;
    return ev("markRead(__s, '9', 1)");
  });
  check(
    "S7 写盘失败 setItem 抛异常 → false 且不抛",
    r7a.ok && r7a.value === false,
    r7a.ok ? "value=" + r7a.value : "THREW: " + r7a.error
  );
  const r7b = attempt(function () {
    ctx.__s = null;
    return ev("markRead(__s, '9', 1)");
  });
  check(
    "S7 写盘失败 storage=null → false 且不抛",
    r7b.ok && r7b.value === false,
    r7b.ok ? "value=" + r7b.value : "THREW: " + r7b.error
  );
  const r7c = attempt(function () {
    ctx.__s = 42;
    return ev("markRead(__s, '9', 1)");
  });
  check(
    "S7 写盘失败 storage 非对象 → false 且不抛",
    r7c.ok && r7c.value === false,
    r7c.ok ? "value=" + r7c.value : "THREW: " + r7c.error
  );

  /* ---- S8 schema 版本号：写侧落盘 v=1 不漂移；读侧透传盘上真实 v（非硬编码 SCHEMA_V） ---- */
  const h8a = makeStorage();
  callMark(h8a, "1", 1000);
  const raw8 = String(h8a.raw());
  let parsed8 = null;
  try {
    parsed8 = JSON.parse(raw8);
  } catch (e) {
    parsed8 = null;
  }
  check(
    'S8 schema 写侧 markRead 后盘上顶层含 "v":1 且 read 形状正确（防 _persist 漂移 / 漏写）',
    /"v"\s*:\s*1\b/.test(raw8) &&
      !!parsed8 &&
      parsed8.v === 1 &&
      !!parsed8.read &&
      typeof parsed8.read === "object" &&
      !Array.isArray(parsed8.read),
    "raw=" + raw8
  );

  const h8b = makeStorage();
  h8b.seed('{"v":2,"read":{}}');
  const st8 = attempt(function () {
    return callLoad(h8b);
  });
  check(
    "S8 schema 读侧 盘上 v=2 → loadRead 透传 v===2（非硬编码 SCHEMA_V）",
    st8.ok && st8.value.v === 2 && !!st8.value.read && typeof st8.value.read === "object",
    st8.ok ? "v=" + st8.value.v + " read=" + JSON.stringify(st8.value.read) : "THREW: " + st8.error
  );

  /* ---- 源码契约防死测：切到的必须是真实现 ---- */
  check(
    "源码契约 READ_KEY === delector_encounter_read_v1（备份导出/还原契约）",
    ev("READ_KEY") === STORAGE_KEY,
    "got " + ev("READ_KEY")
  );
  check("源码契约 READ_KEY MUST NOT 为 enc. 前缀", !/^enc\./.test(String(ev("READ_KEY"))), "got " + ev("READ_KEY"));
  check(
    "源码契约 幂等判据用 Object.prototype.hasOwnProperty.call（防真值判断）",
    /Object\.prototype\.hasOwnProperty\.call\(/.test(code),
    ""
  );
  check("源码契约 键一律 String(...) 归一", /String\(/.test(code), "");
}

if (loadError) {
  for (const name of SCENARIO_NAMES) check(name, false, "源码未加载：" + loadError);
} else {
  runScenarios();
}

/* ---------------------------------------------------------------------------
 * 5. 输出
 * ------------------------------------------------------------------------ */
if (JSON_MODE) {
  process.stdout.write(JSON.stringify({ failures: failures, total: cases.length, cases: cases }));
} else {
  console.log("");
  if (failures > 0) console.log("FAIL 汇总：" + failures + " 个断言未通过");
  else console.log("ALL PASS：遇见区已读状态 幂等写盘 / 取首个未读 行为自检通过");
}
process.exitCode = failures > 0 ? 1 : 0;
