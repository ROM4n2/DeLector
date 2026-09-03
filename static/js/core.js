/* DeLector - Core Utilities, API Client & Shared State */
'use strict';

// ── Global Reactive State ───────────────────────────────────────────────────
export const state = {
  currentArticle: null,
  selectedToken: null,
  selectedSent: null,
  grammarData: null,
  allCards: [],
  currentCardFilter: 'all',
  currentDeckIndex: 0,
  deckCards: [],
  isFlipped: false,
  currentFolioPage: 0,
  currentClozeExercise: null,
  currentClozeMode: 'grammar',
  activeSelectedRangeText: '',
  activeSelectedSentId: null,
  activeEditingNoteId: null,
  currentFocusedLevel: null
};

// ── Utility Functions ────────────────────────────────────────────────────────
export function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Escape a value destined for a JS string literal *inside* an HTML attribute
// (onclick="f(${jsAttr(v)})"). esc() alone is NOT enough there: attribute
// parsing decodes &#39; back into a live quote BEFORE the JS engine parses,
// so crafted values can break out of the string. JSON.stringify escapes
// quotes, backslashes, newlines and control chars; esc() then keeps the
// surrounding HTML attribute from terminating early. Both layers required.
export function jsAttr(v) {
  return esc(JSON.stringify(v == null ? '' : String(v)));
}

// Largest-remainder method integer normalization for CEFR distribution
export function normalizeCefrPct(rawPct) {
  if (!rawPct) return {};
  const levels = ['A1', 'A2', 'B1', 'B2', 'C1'];
  const active = levels.filter(l => rawPct[l] > 0);
  if (!active.length) return rawPct;

  const floored = {};
  const remainders = {};
  let total = 0;
  active.forEach(l => {
    floored[l] = Math.floor(rawPct[l]);
    remainders[l] = rawPct[l] - floored[l];
    total += floored[l];
  });

  let leftover = 100 - total;
  active
    .slice()
    .sort((a, b) => remainders[b] - remainders[a])
    .forEach(l => {
      if (leftover > 0) { floored[l]++; leftover--; }
    });

  const out = {};
  levels.forEach(l => { out[l] = floored[l] || 0; });
  return out;
}

// ── Hosted Toasts (非阻断通知带) ──────────────────────────────────────────────
// 读/渲染/AI 等路径的错误只应 toast，不阻断式 alert()。
let _notifyTimer = null;

export function notify(message, { kind = 'info', ttl = 2600, sticky = false } = {}) {
  let el = document.getElementById('wb-notify');
  if (!el) {
    el = document.createElement('div');
    el.id = 'wb-notify';
    el.className = 'wb-notify';
    el.setAttribute('role', 'status');
    (document.body || document.documentElement).appendChild(el);
  }
  el.textContent = message;
  el.dataset.kind = kind;
  el.classList.add('show');
  if (_notifyTimer) clearTimeout(_notifyTimer);
  if (!sticky) _notifyTimer = setTimeout(() => el.classList.remove('show'), ttl);
}

// ── API Fetch Wrapper ────────────────────────────────────────────────────────
export const DEFAULT_TIMEOUT_MS = 25000;

export async function api(url, opts = {}) {
  // 默认 25s 超时；调用方可 opts.timeout 覆盖。与外部 signal 合并：任一先触发即中止。
  const { timeout = DEFAULT_TIMEOUT_MS, signal, ...rest } = opts;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  const onUserAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onUserAbort, { once: true });
  }
  try {
    const res = await fetch(url, { ...rest, signal: controller.signal });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(errData.detail || `HTTP Error ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    const e = timedOut ? new Error(`请求超时（${Math.round(timeout / 1000)}s），请检查网络`) : err;
    console.error(`[API Error] ${url}:`, e);
    throw e;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onUserAbort);
  }
}
