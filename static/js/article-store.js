/* DeLector - 文章列表薄 store（阶段二 + 阶段一）
 *
 * 唯一缓存读写点：localStorage 快照只由「成功的文章列表 GET」写入。
 * UI 只从这里取数、只订阅变化；渲染函数不直接碰网络/缓存。
 *
 * 状态机：
 *   idle → stale（先渲染缓存/内置快照）→ ready（真实数据替换）
 *                                       ↘ error（无数据时）/ stale + error（有旧数据时）
 * status=stale 表示「屏上是旧数据」，视图必须给出形状/图标痕迹（I1）。
 */
'use strict';

import { ARTICLE_SEED_SNAPSHOT } from './article-seed.js';
import { fetchArticles, removeArticle } from './rd-api.js';

const CACHE_KEY = 'delector.articles.snapshot.v1';
const ARTICLE_LIST_KEYS = ['id', 'title', 'created_at', 'char_count', 'stats'];

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

function createArticleStore() {
  let state = {
    items: [],
    status: 'idle',
    fromCache: false,
    builtin: false,
    error: null,
    empty: false,
    updatedAt: 0,
  };
  let inflight = null;
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

  function loadArticles(options) {
    const force = !!(options && options.force);
    if (inflight && !force) return inflight;
    seedFirstFrame();
    if (state.items.length) {
      setState({ status: 'stale', fromCache: true });
    }

    const seq = ++loadSeq;
    const request = (async () => {
      try {
        const items = normalizeArticleList(await fetchArticles());
        // 删除等写操作会开启新序号；旧响应不得把已删除的行写回来。
        if (seq !== loadSeq) return state.items;
        writeCache(items);
        setState({
          items,
          status: 'ready',
          fromCache: false,
          builtin: false,
          error: null,
          empty: items.length === 0,
          updatedAt: Date.now(),
        });
        return items;
      } catch (err) {
        if (seq !== loadSeq) return state.items;
        const message = (err && err.message) || String(err);
        if (state.items.length) {
          setState({ status: 'stale', error: message });
        } else {
          setState({ status: 'error', error: message, empty: false });
        }
        return state.items;
      }
    })();
    inflight = request;
    const clearInflight = () => {
      if (inflight === request) inflight = null;
    };
    request.then(clearInflight, clearInflight);

    return request;
  }

  async function deleteArticle(id) {
    // 写操作不走缓存：删除成功后先失效快照，再由成功 GET 重建。
    await removeArticle(id);
    invalidateCache();
    setState({ items: state.items.filter((item) => Number(item.id) !== Number(id)), error: null });
    await loadArticles({ force: true });
  }

  return { getState, subscribe, loadArticles, deleteArticle };
}

export const articleStore = createArticleStore();
export { createArticleStore, isArticleListItem, normalizeArticleList, ARTICLE_LIST_KEYS, CACHE_KEY };
