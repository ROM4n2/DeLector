/* DeLector - 文章列表薄 store（阶段二 + 阶段一）
 *
 * 唯一缓存读写点：localStorage 快照只由「成功的文章列表 GET」写入。
 * UI 只从这里取数、只订阅变化；渲染函数不直接碰网络/缓存。
 *
 * 状态机：
 *   idle → stale（先渲染缓存/内置快照）→ ready（真实数据替换）
 *                                       ↘ stale + retrying（后端未就绪，后台退避重试中）
 *                                       ↘ error + retryable（预算耗尽 / 不可重试，等用户点重试）
 * status=stale 表示「屏上是旧数据」，视图必须给出形状/图标痕迹（I1）。
 *
 * 重试只覆盖「后端未就绪」类失败（连接被拒、502/503、超时）；4xx 业务错误与
 * 明确接口错误不重试，直接进 error。首帧仍由快照同步渲染，重试全部在后台。
 */
'use strict';

import { ARTICLE_SEED_SNAPSHOT } from './article-seed.js';
import { fetchArticles, removeArticle } from './rd-api.js';

const CACHE_KEY = 'delector.articles.snapshot.v1';
const ARTICLE_LIST_KEYS = ['id', 'title', 'created_at', 'char_count', 'stats'];

// 「后端未就绪」重试：仅覆盖可恢复失败，总预算内有限次退避，不无限轮询。
// 导出给 reader.js 的「文章详情」加载复用 —— 详情与列表走同一套就绪判定与退避策略，
// 不在阅读器里再写第二份 isRetryableError（红线：同一条策略只允许一处实现）。
export const RETRY_DELAYS_MS = [200, 400, 800, 1600, 3200];
export const RETRY_BUDGET_MS = 12000;
export const ATTEMPT_TIMEOUT_MS = 6000;

export function isRetryableError(err) {
  if (!err) return false;
  if (err.code === 'TIMEOUT' || err.name === 'TypeError') return true;
  if (Number.isFinite(err.status)) return err.status >= 500;
  const message = String(err.message || err);
  return /Failed to fetch|NetworkError|Load failed|ECONNREFUSED|请求超时/i.test(message);
}

function isArticleListItem(item) {
  if (!item || typeof item !== 'object') return false;
  if (!Number.isFinite(item.id)) return false;
  return ARTICLE_LIST_KEYS.every((key) => key in item);
}

function normalizeArticleList(items) {
  return Array.isArray(items) ? items.filter(isArticleListItem) : [];
}

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const items = normalizeArticleList(parsed && parsed.items);
    return items.length ? items : null;
  } catch (_) {
    // 存储不可用 / 内容损坏：静默退化为内置快照，首帧不受影响。
    return null;
  }
}

function writeCache(items) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), items }));
  } catch (_) {
    // 配额满 / 隐私模式：缓存降级为「本次内存有效」，不影响真实数据渲染。
  }
}

function invalidateCache() {
  try {
    localStorage.removeItem(CACHE_KEY);
  } catch (_) {
    // 同上：缓存失效不是错误路径。
  }
}

function hydrateSnapshot() {
  const cached = readCache();
  if (cached) {
    return { items: cached, builtin: false };
  }
  return { items: ARTICLE_SEED_SNAPSHOT.slice(), builtin: true };
}

function createArticleStore(options) {
  const opts = options || {};
  // 依赖可注入：测试用假时钟驱动退避，无需真实 sleep。
  const fetchList = typeof opts.fetchArticles === 'function' ? opts.fetchArticles : fetchArticles;
  const removeRemote = typeof opts.removeArticle === 'function' ? opts.removeArticle : removeArticle;
  const schedule = typeof opts.setTimer === 'function'
    ? opts.setTimer
    : (fn, ms) => setTimeout(fn, ms);
  const unschedule = typeof opts.clearTimer === 'function'
    ? opts.clearTimer
    : (id) => clearTimeout(id);
  const clock = typeof opts.now === 'function' ? opts.now : () => Date.now();
  const retryDelays = Array.isArray(opts.retryDelays) ? opts.retryDelays.slice() : RETRY_DELAYS_MS;
  const retryBudgetMs = Number.isFinite(opts.retryBudgetMs) ? opts.retryBudgetMs : RETRY_BUDGET_MS;
  const attemptTimeoutMs = Number.isFinite(opts.attemptTimeoutMs)
    ? opts.attemptTimeoutMs
    : ATTEMPT_TIMEOUT_MS;
  const retryableError = typeof opts.isRetryable === 'function' ? opts.isRetryable : isRetryableError;

  let state = {
    items: [],
    status: 'idle',
    fromCache: false,
    builtin: false,
    error: null,
    empty: false,
    updatedAt: 0,
    retrying: false,
    retryable: false,
    attempts: 0,
  };
  let cycle = null;
  let loadSeq = 0;
  const listeners = new Set();

  function getState() {
    return state;
  }

  function subscribe(fn) {
    if (typeof fn !== 'function') return () => {};
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function setState(patch) {
    state = { ...state, ...patch };
    for (const fn of Array.from(listeners)) {
      try {
        fn(state);
      } catch (_) {
        // 单个订阅者渲染失败不得阻断其它订阅者。
      }
    }
  }

  function seedFirstFrame() {
    if (state.items.length) return;
    const snapshot = hydrateSnapshot();
    setState({
      items: snapshot.items,
      status: 'stale',
      fromCache: true,
      builtin: snapshot.builtin,
      error: null,
      empty: false,
    });
  }

  function finishCycle(current) {
    if (current.settled) return;
    current.settled = true;
    if (current.timer) {
      unschedule(current.timer);
      current.timer = null;
    }
    if (cycle === current) cycle = null;
    current.resolve(state.items);
  }

  async function runAttempt(current) {
    let items;
    try {
      items = normalizeArticleList(await fetchList({ timeout: attemptTimeoutMs }));
    } catch (err) {
      handleAttemptFailure(current, err);
      return;
    }
    // 删除等写操作 / 手动重试会开启新序号；旧响应不得把已删除的行写回来。
    if (current.seq !== loadSeq) return finishCycle(current);
    writeCache(items);
    setState({
      items,
      status: 'ready',
      fromCache: false,
      builtin: false,
      error: null,
      empty: items.length === 0,
      updatedAt: clock(),
      retrying: false,
      retryable: false,
      attempts: current.attempts,
    });
    finishCycle(current);
  }

  function handleAttemptFailure(current, err) {
    if (current.seq !== loadSeq) return finishCycle(current);
    const message = (err && err.message) || String(err);
    const canRetry = retryableError(err);
    const delay = retryDelays[current.attempts - 1];
    const elapsed = clock() - current.startedAt;
    const withinBudget =
      canRetry && Number.isFinite(delay) && elapsed + delay <= retryBudgetMs;

    if (!withinBudget) {
      // 不可重试 or 次数/预算到顶：停在这里，等用户点「重试」。
      setState({
        status: 'error',
        error: message,
        retrying: false,
        retryable: canRetry,
        attempts: current.attempts,
      });
      finishCycle(current);
      return;
    }

    setState({
      status: state.items.length ? 'stale' : 'error',
      error: message,
      retrying: true,
      retryable: true,
      attempts: current.attempts,
    });
    current.timer = schedule(() => {
      current.timer = null;
      if (current.seq !== loadSeq || current.settled) return;
      current.attempts += 1;
      runAttempt(current);
    }, delay);
  }

  function loadArticles(options) {
    const force = !!(options && options.force);
    if (cycle && !force) return cycle.promise;
    if (cycle) finishCycle(cycle);
    seedFirstFrame();
    if (state.items.length) {
      setState({ status: 'stale', fromCache: true, error: null, retrying: false, retryable: false, attempts: 0 });
    }

    const seq = ++loadSeq;
    let resolve;
    const promise = new Promise((done) => {
      resolve = done;
    });
    const current = {
      seq,
      promise,
      resolve,
      settled: false,
      timer: null,
      attempts: 1,
      startedAt: clock(),
    };
    cycle = current;
    runAttempt(current);
    return promise;
  }

  // 用户可见的重试入口：取消当前退避，立刻重新走一轮完整预算。
  function retryNow() {
    return loadArticles({ force: true });
  }

  // 后端就绪信号（宿主探活成功）：**只打断正在等待的退避计时器**，提前发起下一次尝试。
  // 不新建 cycle、不改退避序列、不动已在途的请求与已就绪的状态，因此不构成第二套重试机制。
  function retryIfWaiting() {
    const current = cycle;
    if (!current || current.timer == null) return false;
    unschedule(current.timer);
    current.timer = null;
    if (current.seq !== loadSeq || current.settled) return false;
    current.attempts += 1;
    runAttempt(current);
    return true;
  }

  async function deleteArticle(id) {
    // 写操作不走缓存：删除成功后先失效快照，再由成功 GET 重建。
    await removeRemote(id);
    invalidateCache();
    setState({ items: state.items.filter((item) => Number(item.id) !== Number(id)), error: null });
    await loadArticles({ force: true });
  }

  return { getState, subscribe, loadArticles, deleteArticle, retryNow, retryIfWaiting };
}

export const articleStore = createArticleStore();
export {
  createArticleStore,
  isArticleListItem,
  normalizeArticleList,
  isRetryableError,
  ARTICLE_LIST_KEYS,
  CACHE_KEY,
  RETRY_DELAYS_MS,
  RETRY_BUDGET_MS,
};
