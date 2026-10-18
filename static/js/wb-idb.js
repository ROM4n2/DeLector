/**
 * wb-idb.js —— 存储层 + IndexedDB 迁移/自动备份（C7 Task 5 · 块 2：seed-persist）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （三段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) `loadAll()`；
 *   2) `saveWords()`，连同其上方「落盘闸 + 缓存写入」那段说明；
 *   3) F2 分节 banner 与 IndexedDB 全套：IDB_NAME / IDB_VER / IDB_STORES / _idb /
 *      _idbReady / _idbFailed 六个状态，idbOpen / idbPut / idbGet / idbSnapshot /
 *      idbListSnapshots / idbRestoreSnapshot / idbDeleteSnapshot / idbHydrate 八个函数。
 * 搬动前后唯一新增的字节是本段说明性文件头（三段片段之间只加了分隔空行）。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js  →  wb-idb.js  →  wb-tts.js  →  主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证（计划 Fog of War
 * Unknown 2），必须保留整体回退成内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在 wb-tts.js 之前：两者互不依赖（IDB 层不碰 _tts*，TTS 层不碰 IDB_*），
 * 故顺序只按「启动期依赖方向」定 —— 主内联脚本第一句就是 loadAll()，而 loadAll /
 * idbHydrate 的实现住在本文件；wb-tts.js 的 playWord 只在用户点击时被调用。
 * 读加载序即读依赖方向，不留「谁先谁后都行」的模糊地带。
 *
 * 跨文件依赖（全部在**运行期**解析；它们都是主内联脚本的顶层声明，同处全局词法环境）：
 *   S / K / DEFAULT_SETTINGS / A1_BOOT_PENDING / normalizeAllWords / migrateWordSchema /
 *   wbsync / localStorage / indexedDB / Date
 * => 这些函数只能在主内联脚本解析完成之后被调用（启动序 / UI / 定时器）。
 *    任何「在加载期调用 loadAll / idbOpen」的写法都会撞上 TDZ，不要加。
 * => 反向也成立：主内联脚本仍可在运行期读写本文件的顶层 let（_idb / _idbReady /
 *    _idbFailed 落在同一全局词法环境，不挂 window）。
 *
 * 严格模式：搬出前这些代码位于主内联脚本的 "use strict" 之下，本文件不带该指令
 * （与 wb-tts.js / wb-seed-data.js 一致）。已逐条核对：本片段不依赖严格/宽松模式的任何
 * 差异（无未声明变量赋值、无裸 this、无 arguments.callee、无重复形参、无八进制字面量）。
 */

function loadAll() {
  try { S.words = JSON.parse(localStorage.getItem(K.words) || "null") || null; } catch (e) { S.words = null; }
  A1_BOOT_PENDING = false;
  if (!Array.isArray(S.words)) {
    // 首装：不再当场建表 —— 由 bootstrapA1Words() 优先拉服务端 A1 视图（失败回退内联）。
    // 此处仅置空表 + 挂起标记，等异步结果再覆盖；期间 UI 显示「正在加载 A1 词库…」。
    S.words = [];
    A1_BOOT_PENDING = true;
  } else {
    // Task 4：localStorage 存量词对象读出后、进 S.words 被消费前逐条在内存归一
    // （无论是否已标记——远端镜像可能把旧形状词拉回来）。任一条失败 → 整体放弃，S.words 保留原样。
    const normalized = normalizeAllWords(S.words);
    if (normalized) S.words = normalized;
  }
  const load = (key, fallback) => {
    try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v == null ? fallback : v; }
    catch (e) { return fallback; }
  };
  S.cards = load(K.cards, {});
  S.log = load(K.log, {});
  S.wrong = load(K.wrong, {});
  S.settings = Object.assign({}, DEFAULT_SETTINGS, load(K.set, {}));
  /* 首装挂起时 S.words 为空：migrateWordSchema() 会把空表落盘并写 schema 标记，
   * 造成「关页 → 下次读回 [] → 不再进首装分支」的永久空表。故挂起时跳过，
   * 由 bootstrapA1Words() 在词表就绪后再调用。存量词表分支（非挂起）照旧。 */
  if (!A1_BOOT_PENDING) migrateWordSchema();
}

/* 落盘闸 + 缓存写入（ADR-0014 §6-S2 验收修复红牌①）：首装挂起期词表为空时绝不写
 * wb.words.v1，防任何新增调用点把 [] 写进缓存造成「关页 → 下次读回 [] → 不再进首装」
 * 的永久空表。首装成功路径在 bootstrapA1Words() 里已先置 A1_BOOT_PENDING=false 再
 * saveWords()，故此闸只挡「空表 + 挂起」这一种组合，绝不误挡首装成功路径。 */
function saveWords() { if (A1_BOOT_PENDING && S.words.length === 0) return; localStorage.setItem(K.words, JSON.stringify(S.words)); idbPut("words", S.words); wbsync.push(); }

/* ======================================================================
 * F2 · IndexedDB 迁移 + 自动备份（双写期：localStorage + IDB 并行写）
 *  - 突破 5MB 限制支持万词库
 *  - 每日首次启动自动 snapshot，保留最近 7 条
 *  - 设置页加「历史版本」面板，预览/恢复/删除
 *  - IDB 不可用时静默降级到 localStorage（不影响功能）
 * ==================================================================== */
const IDB_NAME = "wb";
const IDB_VER = 1;
const IDB_STORES = ["words", "cards", "log", "wrong", "settings", "snapshots"];
let _idb = null;       // IDBDatabase 实例
let _idbReady = false;
let _idbFailed = false;

function idbOpen() {
  return new Promise((resolve) => {
    if (_idbReady && _idb) return resolve(_idb);
    if (_idbFailed) return resolve(null);
    if (typeof indexedDB === "undefined") { _idbFailed = true; return resolve(null); }
    try {
      const req = indexedDB.open(IDB_NAME, IDB_VER);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        for (const s of IDB_STORES) {
          if (!db.objectStoreNames.contains(s)) {
            db.createObjectStore(s, s === "snapshots" ? { keyPath: "ts", autoIncrement: true } : { keyPath: "key" });
          }
        }
      };
      req.onsuccess = (e) => { _idb = e.target.result; _idbReady = true; resolve(_idb); };
      req.onerror = () => { _idbFailed = true; resolve(null); };
    } catch (e) { _idbFailed = true; resolve(null); }
  });
}

async function idbPut(store, value) {
  // 单条记录：用 key="main" 存（words/cards/log/wrong/settings 都是单对象）
  const db = await idbOpen();
  if (!db) return;
  try {
    return new Promise((resolve) => {
      const tx = db.transaction(store, "readwrite");
      tx.objectStore(store).put({ key: "main", value });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  } catch (e) { /* 静默 */ }
}

async function idbGet(store) {
  const db = await idbOpen();
  if (!db) return null;
  try {
    return new Promise((resolve) => {
      const tx = db.transaction(store, "readonly");
      const req = tx.objectStore(store).get("main");
      req.onsuccess = () => resolve(req.result ? req.result.value : null);
      req.onerror = () => resolve(null);
    });
  } catch (e) { return null; }
}

async function idbSnapshot() {
  const db = await idbOpen();
  if (!db) return null;
  const snap = {
    ts: Date.now(),
    words: S.words,
    cards: S.cards,
    log: S.log,
    wrong: S.wrong,
    settings: S.settings,
  };
  try {
    return new Promise((resolve) => {
      const tx = db.transaction("snapshots", "readwrite");
      tx.objectStore("snapshots").add(snap);
      tx.oncomplete = async () => {
        // 清理超过 7 条的旧快照
        const all = await idbListSnapshots();
        if (all && all.length > 7) {
          const tx2 = db.transaction("snapshots", "readwrite");
          for (let i = 0; i < all.length - 7; i++) {
            tx2.objectStore("snapshots").delete(all[i].ts);
          }
        }
        resolve(snap.ts);
      };
      tx.onerror = () => resolve(null);
    });
  } catch (e) { return null; }
}

async function idbListSnapshots() {
  const db = await idbOpen();
  if (!db) return [];
  try {
    return new Promise((resolve) => {
      const tx = db.transaction("snapshots", "readonly");
      const req = tx.objectStore("snapshots").getAll();
      req.onsuccess = () => resolve((req.result || []).sort((a, b) => b.ts - a.ts));
      req.onerror = () => resolve([]);
    });
  } catch (e) { return []; }
}

async function idbRestoreSnapshot(ts) {
  const db = await idbOpen();
  if (!db) return null;
  try {
    return new Promise((resolve) => {
      const tx = db.transaction("snapshots", "readonly");
      const req = tx.objectStore("snapshots").get(ts);
      req.onsuccess = async () => {
        const snap = req.result;
        if (!snap) return resolve(null);
        // 双写恢复到 localStorage + IDB（不直接覆盖 S，避免运行时状态紊乱；刷新后从 localStorage 读）
        localStorage.setItem(K.words, JSON.stringify(snap.words || []));
        localStorage.setItem(K.cards, JSON.stringify(snap.cards || {}));
        localStorage.setItem(K.log, JSON.stringify(snap.log || {}));
        localStorage.setItem(K.wrong, JSON.stringify(snap.wrong || {}));
        localStorage.setItem(K.set, JSON.stringify(snap.settings || {}));
        resolve(snap);
      };
      req.onerror = () => resolve(null);
    });
  } catch (e) { return null; }
}

async function idbDeleteSnapshot(ts) {
  const db = await idbOpen();
  if (!db) return false;
  try {
    return new Promise((resolve) => {
      const tx = db.transaction("snapshots", "readwrite");
      tx.objectStore("snapshots").delete(ts);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  } catch (e) { return false; }
}

/** 启动时从 IDB 覆盖 localStorage 数据（如果 IDB 更新） */
async function idbHydrate() {
  const db = await idbOpen();
  if (!db) return false;
  let updated = false;
  for (const store of ["words", "cards", "log", "wrong", "settings"]) {
    const v = await idbGet(store);
    if (v != null) {
      const lsKey = store === "words" ? K.words : store === "cards" ? K.cards : store === "log" ? K.log : store === "wrong" ? K.wrong : K.set;
      const lsVal = localStorage.getItem(lsKey);
      const idbVal = JSON.stringify(v);
      if (lsVal !== idbVal) {
        localStorage.setItem(lsKey, idbVal);
        updated = true;
      }
    }
  }
  return updated;
}
