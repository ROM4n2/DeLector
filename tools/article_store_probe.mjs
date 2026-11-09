/**
 * article_store_probe.mjs —— 文章列表「先 store 后缓存」行为探针
 *
 * 被测逻辑**不重抄**：把 static/js/article-store.js 与 article-seed.js 真源码
 * 剥掉 import/export 后放进 node:vm 沙箱，提供 localStorage / fetchArticles /
 * removeArticle 桩。断言 ADR-0032 阶段一 + 阶段二的硬契约：
 *
 *   A. 首装无缓存：loadArticles() 在 fetch resolve 之前就通知内置快照（4 行）；
 *   B. 成功 GET 才写缓存；缓存与接口同为 5 键；
 *   C. 有缓存：fetch 未返回时首帧就是缓存行，且 builtin=false；
 *   D. fetch 失败：保留旧数据；不可重试错误直接进 error，可重试错误进后台退避；
 *   E. 写操作不走缓存：删除成功后先失效快照，再由成功 GET 重建；
 *   F. 契约守卫：缺键/坏项被 normalize 丢弃；
 *   R. 就绪重试：ECONNREFUSED → 后端起来 → 自动接管；预算耗尽 → error + 可重试；
 *      4xx 不重试；退避时序用假时钟断言（无真实 sleep）。
 *
 * 用法：
 *   node tools/article_store_probe.mjs            # 人类可读
 *   node tools/article_store_probe.mjs --json     # stdout 只输出 JSON（pytest 用）
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const JSON_MODE = process.argv.includes("--json");
const read = (name) => fs.readFileSync(path.join(ROOT, "static", "js", name), "utf8");

const cases = [];
function check(name, ok, detail = "") {
  cases.push({ name, ok: !!ok, detail: ok ? "" : String(detail) });
}

function makeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
  };
}

const ITEM = (id, title = `文章 ${id}`) => ({
  id,
  title,
  created_at: "2026-11-09 12:00",
  char_count: 100 + id,
  stats: { recommended_level: "A2" },
});

// 浏览器里「连接被拒」表现为 TypeError: Failed to fetch（无 status）。
const networkError = () => new TypeError("Failed to fetch");

const flushMicrotasks = () => new Promise((resolve) => setImmediate(resolve));

// 假时钟：退避时序可断言，测试不依赖真实 sleep。
function makeClock() {
  let current = 0;
  let nextId = 0;
  const timers = new Map();
  return {
    now: () => current,
    setTimer(fn, ms) {
      const id = ++nextId;
      timers.set(id, { at: current + ms, fn });
      return id;
    },
    clearTimer(id) {
      timers.delete(id);
    },
    pending() {
      return [...timers.values()].map((t) => t.at - current).sort((a, b) => a - b);
    },
    async advance(ms) {
      const target = current + ms;
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, t]) => t.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        current = due[1].at;
        due[1].fn();
        await flushMicrotasks();
      }
      if (target > current) current = target;
      await flushMicrotasks();
    },
    async runAll(limit = 50) {
      for (let i = 0; i < limit && timers.size; i += 1) {
        const [id, timer] = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
        timers.delete(id);
        current = timer.at;
        timer.fn();
        await flushMicrotasks();
      }
      // 让最后一次 attempt 的 reject 落地
      await flushMicrotasks();
    },
  };
}

function loadSandbox() {
  const context = {
    console,
    Date,
    JSON,
    Set,
    Map,
    Math,
    Promise,
    Array,
    Number,
    String,
    Object,
    setTimeout,
    clearTimeout,
    localStorage: makeStorage(),
    fetchArticles: () => Promise.reject(new Error("fetchArticles 未注入")),
    removeArticle: () => Promise.reject(new Error("removeArticle 未注入")),
  };
  vm.createContext(context);

  const seedSrc = read("article-seed.js")
    .replace(/^export\s+/gm, "")
    .replace(/^'use strict';\s*$/m, "");
  vm.runInContext(seedSrc, context, { filename: "article-seed.js" });
  vm.runInContext("globalThis.ARTICLE_SEED_SNAPSHOT = ARTICLE_SEED_SNAPSHOT;", context);

  const storeSrc = read("article-store.js")
    .replace(/^import[^\n]*\n/gm, "")
    .replace(/^export\s*\{[^}]*\};?\s*$/gm, "")
    .replace(/^export\s+/gm, "")
    .replace(/^'use strict';\s*$/m, "");
  vm.runInContext(
    storeSrc +
      "\nglobalThis.__store = { createArticleStore, isArticleListItem, normalizeArticleList, isRetryableError, CACHE_KEY, RETRY_DELAYS_MS, RETRY_BUDGET_MS };\n",
    context,
    { filename: "article-store.js" },
  );
  return context;
}

function readCache(ctx) {
  const raw = ctx.localStorage.getItem(ctx.__store.CACHE_KEY);
  return raw ? JSON.parse(raw) : null;
}

async function scenarioFirstInstall() {
  const ctx = loadSandbox();
  let resolveFetch = null;
  let calls = 0;
  ctx.fetchArticles = () => {
    calls += 1;
    return new Promise((resolve) => {
      resolveFetch = resolve;
    });
  };

  const store = ctx.__store.createArticleStore();
  const seen = [];
  store.subscribe((state) => seen.push({ len: state.items.length, status: state.status, builtin: state.builtin }));

  const pending = store.loadArticles();
  const first = store.getState();
  check("A1-首装首帧来自内置快照", first.items.length === 4 && first.builtin === true && first.status === "stale", JSON.stringify(first));
  check("A2-fetch 未返回就通知了首帧", calls === 1 && seen.some((s) => s.len === 4 && s.builtin), JSON.stringify(seen));
  check("A3-内置快照 5 键与列表契约同形", first.items.every((a) => ctx.__store.normalizeArticleList([a]).length === 1), "seed item keys");

  resolveFetch([ITEM(101), ITEM(102)]);
  await pending;
  const ready = store.getState();
  check("A4-成功后 ready 且替换内置快照", ready.status === "ready" && ready.items.length === 2 && ready.builtin === false, JSON.stringify(ready));
  const cached = readCache(ctx);
  check("A5-成功 GET 才写缓存", cached && Array.isArray(cached.items) && cached.items.length === 2, JSON.stringify(cached));
}

async function scenarioCachedFirst() {
  const ctx = loadSandbox();
  ctx.localStorage.setItem(ctx.__store.CACHE_KEY, JSON.stringify({ savedAt: 1, items: [ITEM(7, "缓存文章")] }));
  let resolveFetch = null;
  ctx.fetchArticles = () =>
    new Promise((resolve) => {
      resolveFetch = resolve;
    });

  const store = ctx.__store.createArticleStore();
  const pending = store.loadArticles();
  const first = store.getState();
  check(
    "B1-有缓存时首帧是缓存行",
    first.items.length === 1 && first.items[0].id === 7 && first.fromCache === true && first.builtin === false,
    JSON.stringify(first),
  );

  resolveFetch([ITEM(8, "真实文章")]);
  await pending;
  check("B2-真实数据静默替换缓存", store.getState().status === "ready" && store.getState().items[0].id === 8, JSON.stringify(store.getState()));
}

async function scenarioFailureKeepsOldData() {
  const ctx = loadSandbox();
  ctx.localStorage.setItem(ctx.__store.CACHE_KEY, JSON.stringify({ savedAt: 1, items: [ITEM(9, "旧文章")] }));
  ctx.fetchArticles = () => Promise.reject(new Error("boom"));

  const store = ctx.__store.createArticleStore();
  await store.loadArticles();
  const state = store.getState();
  check(
    "C1-不可重试失败保留旧数据并进 error",
    state.items.length === 1 && state.items[0].id === 9 &&
      state.status === "error" && state.error === "boom" &&
      state.retrying === false && state.retryable === false,
    JSON.stringify(state),
  );
}

async function scenarioAutoResumeAfterRefusal() {
  const ctx = loadSandbox();
  const clock = makeClock();
  let calls = 0;
  ctx.fetchArticles = () => {
    calls += 1;
    return calls === 1 ? Promise.reject(networkError()) : Promise.resolve([ITEM(42, "后端就绪后的文章")]);
  };

  const store = ctx.__store.createArticleStore({
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    now: clock.now,
  });
  const pending = store.loadArticles();
  await flushMicrotasks();

  const during = store.getState();
  check(
    "R1-连接被拒时首帧仍是快照并进入重试中",
    during.items.length === 4 && during.builtin === true && during.status === "stale" &&
      during.retrying === true && during.retryable === true,
    JSON.stringify(during),
  );
  check(
    "R2-首次失败后按 200ms 退避",
    JSON.stringify(clock.pending()) === JSON.stringify([200]),
    JSON.stringify(clock.pending()),
  );

  await clock.advance(200);
  const ready = store.getState();
  check(
    "R3-后端起来后自动接管（不刷新不切页）",
    calls === 2 && ready.status === "ready" && ready.items.length === 1 &&
      ready.items[0].id === 42 && ready.retrying === false && ready.builtin === false,
    JSON.stringify(ready),
  );
  await pending;
}

async function scenarioRetryBudgetExhausted() {
  const ctx = loadSandbox();
  const clock = makeClock();
  let calls = 0;
  let backendUp = false;
  ctx.fetchArticles = () => {
    calls += 1;
    return backendUp
      ? Promise.resolve([ITEM(77, "手动重试成功")])
      : Promise.reject(networkError());
  };

  const store = ctx.__store.createArticleStore({
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    now: clock.now,
  });
  const pending = store.loadArticles();
  await flushMicrotasks();

  const delays = [];
  let guard = 0;
  while (clock.pending().length && guard < 20) {
    delays.push(clock.pending()[0]);
    await clock.advance(clock.pending()[0]);
    guard += 1;
  }
  await pending;

  const state = store.getState();
  check(
    "R4-预算耗尽进 error 且首帧仍在",
    state.items.length === 4 && state.builtin === true && state.status === "error" &&
      state.retrying === false && state.retryable === true,
    JSON.stringify(state),
  );
  check(
    "R5-退避时序为 200/400/800/1600/3200",
    JSON.stringify(delays) === JSON.stringify([200, 400, 800, 1600, 3200]),
    JSON.stringify(delays),
  );
  check(
    "R6-穷尽后停止轮询（共 6 次请求）",
    calls === 6 && clock.pending().length === 0,
    `calls=${calls} pending=${JSON.stringify(clock.pending())}`,
  );

  // 可见重试入口：用户点「重试」后立刻重新走一轮，成功即接管。
  backendUp = true;
  const retry = store.retryNow();
  await flushMicrotasks();
  const after = store.getState();
  check(
    "R7-retryNow 立即恢复为 ready",
    calls === 7 && after.status === "ready" &&
      after.items.length === 1 && after.items[0].id === 77 && after.retryable === false,
    JSON.stringify(after),
  );
  await retry;
}

async function scenarioNonRetryable4xx() {
  const ctx = loadSandbox();
  const clock = makeClock();
  let calls = 0;
  ctx.fetchArticles = () => {
    calls += 1;
    return Promise.reject(Object.assign(new Error("文章不存在"), { status: 404 }));
  };

  const store = ctx.__store.createArticleStore({
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    now: clock.now,
  });
  await store.loadArticles();
  const state = store.getState();
  check(
    "R8-4xx 不重试直接进 error",
    calls === 1 && state.status === "error" && state.retrying === false &&
      state.retryable === false && state.error === "文章不存在" && clock.pending().length === 0,
    `calls=${calls} ${JSON.stringify(state)}`,
  );
}

function scenarioRetryClassifier() {
  const ctx = loadSandbox();
  const classify = ctx.__store.isRetryableError;
  const cases = [
    [networkError(), true],
    [Object.assign(new Error("超时"), { code: "TIMEOUT" }), true],
    [Object.assign(new Error("坏网关"), { status: 502 }), true],
    [Object.assign(new Error("不可用"), { status: 503 }), true],
    [Object.assign(new Error("未找到"), { status: 404 }), false],
    [Object.assign(new Error("参数错误"), { status: 422 }), false],
    [new Error("boom"), false],
  ];
  const actual = cases.map(([err]) => classify(err));
  check(
    "R9-分类器：拒绝/超时/5xx 可重试，4xx/未知不重试",
    JSON.stringify(actual) === JSON.stringify(cases.map(([, expected]) => expected)),
    JSON.stringify(actual),
  );
  check(
    "R10-默认预算与退避常量符合约定",
    ctx.__store.RETRY_BUDGET_MS >= 10000 && ctx.__store.RETRY_BUDGET_MS <= 15000 &&
      JSON.stringify(ctx.__store.RETRY_DELAYS_MS) === JSON.stringify([200, 400, 800, 1600, 3200]),
    `${ctx.__store.RETRY_BUDGET_MS} ${JSON.stringify(ctx.__store.RETRY_DELAYS_MS)}`,
  );
}

async function scenarioWriteBypassesCache() {
  const ctx = loadSandbox();
  ctx.localStorage.setItem(ctx.__store.CACHE_KEY, JSON.stringify({ savedAt: 1, items: [ITEM(1), ITEM(2)] }));
  const removed = [];
  ctx.removeArticle = async (id) => {
    removed.push(id);
  };
  let resolveFetch = null;
  ctx.fetchArticles = () =>
    new Promise((resolve) => {
      resolveFetch = resolve;
    });

  const store = ctx.__store.createArticleStore();
  const boot = store.loadArticles();
  resolveFetch([ITEM(1), ITEM(2)]);
  await boot;

  const deleting = store.deleteArticle(1);
  await new Promise((resolve) => setTimeout(resolve, 0));
  check("D1-删除走写接口而非缓存", removed.length === 1 && removed[0] === 1, JSON.stringify(removed));
  check("D2-删除后先失效缓存", readCache(ctx) === null, JSON.stringify(readCache(ctx)));

  resolveFetch([ITEM(2)]);
  await deleting;
  const state = store.getState();
  check("D3-成功 GET 后缓存重建为剩余项", state.items.length === 1 && state.items[0].id === 2 && readCache(ctx).items.length === 1, JSON.stringify(state));
}

function scenarioContractGuard() {
  const ctx = loadSandbox();
  const bad = [{ id: 1, title: "缺键" }, { id: "2", title: "坏 id", created_at: "", char_count: 0, stats: {} }, ITEM(3)];
  const normalized = ctx.__store.normalizeArticleList(bad);
  check("E1-缺键/坏 id 被丢弃", normalized.length === 1 && normalized[0].id === 3, JSON.stringify(normalized));
}

(async () => {
  await scenarioFirstInstall();
  await scenarioCachedFirst();
  await scenarioFailureKeepsOldData();
  await scenarioAutoResumeAfterRefusal();
  await scenarioRetryBudgetExhausted();
  await scenarioNonRetryable4xx();
  scenarioRetryClassifier();
  await scenarioWriteBypassesCache();
  scenarioContractGuard();

  const failures = cases.filter((c) => !c.ok).map((c) => c.name + (c.detail ? `: ${c.detail}` : ""));
  const out = { failures: failures.length, total: cases.length, cases };
  if (JSON_MODE) {
    process.stdout.write(JSON.stringify(out));
  } else {
    console.log(`article-store probe: ${cases.length - failures.length}/${cases.length} 通过`);
  }
  if (failures.length) {
    process.stderr.write("文章列表 store/缓存契约破坏：\n  - " + failures.join("\n  - ") + "\n");
    process.exit(1);
  }
})();
