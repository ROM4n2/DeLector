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

// ── API Fetch Wrapper ────────────────────────────────────────────────────────
export async function api(url, opts = {}) {
  try {
    const res = await fetch(url, opts);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(errData.detail || `HTTP Error ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`[API Error] ${url}:`, err);
    throw err;
  }
}
