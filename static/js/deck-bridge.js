/* DeLector - 已背词 deck 桥（遇见区 A5，纯逻辑 ES module）
 *
 * 本模块把 A3 annotate 的 per-token lemma 流按「本机背词工作台 deck」判定 known，
 * 并给出覆盖统计，供 encounter.js 渲染已背词高亮。
 *
 * Node 可测性硬约束（Plan Task A5）：
 *   - **零 import**：纯逻辑、无任何依赖，浏览器（ESM）与 Node（临时拷成 .mjs 直读）
 *     两处都能跑，无需 package.json 的 "type":"module"。
 *   - **模块顶层不碰浏览器全局**：localStorage/document/window 一律不出现；
 *     storage 由调用方注入（浏览器传 window.localStorage，Node 测桩传 getItem 对象）。
 *   - 幂等 / 不抛异常：坏 JSON、缺键、假 storage 一律返回空 deck。
 *
 * Deck 权威 = 背词工作台 localStorage `wb.words.v1`（word 数组，元素含 id/hw/…）
 *   + `wb.cards.v1`（按 String(word.id) 键控的对象，元素含 reps/…）。
 *   「已学习(learned)」= 存在 word 且 cards[String(word.id)].reps > 0。
 *   （workbench 的"手动稳固"也会置 reps≥1，reps>0 已覆盖，无需单独处理 manual 标记。）
 *   known(lemma) = lower(lemma) ∈ { lower(hw) : word 且 cards[id].reps>0 }。
 *
 * 暴露的纯函数（全部可被 Node 测）：
 *   loadDeck(storage)            -> {words, cards}
 *   mergeServerDeck(deck, payload) -> deck（本地为准，server-only 词/卡补进）
 *   buildKnownSet(deck)          -> Set<lower hw>（仅 learned）
 *   isKnown(knownSet, lemma)     -> bool
 *   annotateWithDeck(deck, annotateResp) -> {sentences, stats}
 */
"use strict";

// 背词工作台的两把权威存储键（与 static/german/workbench.html 的 K 常量一致）。
export const DECK_KEYS = {
  words: "wb.words.v1",
  cards: "wb.cards.v1",
};

// 标点/符号 POS 前缀（spaCy 德语常见 PUNCT / SYM / SPACE）。
const PUNCT_POS_PREFIX = ["PUNCT", "SYM", "SPACE"];

/** 安全 JSON.parse：null / 空串 / 坏 JSON 一律返回 null，不抛。 */
function safeParse(raw) {
  if (raw == null) return null;
  try {
    const v = JSON.parse(raw);
    return v;
  } catch (e) {
    return null;
  }
}

/** 该 token 是否算"生词候选"（进 unknown_top）：须是真正的单词，而非标点/数字/符号。 */
function isLemmaCandidate(tok) {
  if (!tok || tok.text == null || tok.lemma == null) return false;
  const text = String(tok.text);
  const pos = String(tok.pos || "").toUpperCase();
  // pos 明确是标点/符号/空白 → 排除
  if (PUNCT_POS_PREFIX.some((p) => pos.startsWith(p))) return false;
  // text 不含任何字母（如数字、孤立符号、非字母 Unicode）→ 视为标点类，排除
  // 覆盖拉丁扩展（ä/ö/ü/ß）、拉丁扩展附加等常见德语字素。
  if (!/[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]/.test(text)) return false;
  return true;
}

/**
 * loadDeck(storage) -> {words:[], cards:{}}
 * storage: 带 getItem 的对象（浏览器传 localStorage；Node 测桩传 getItem 返回 null）。
 * 缺键 / 坏 JSON / 假 storage 一律安全回退为空，不抛异常。
 */
export function loadDeck(storage) {
  if (!storage || typeof storage.getItem !== "function") {
    return { words: [], cards: {} };
  }
  const words = safeParse(storage.getItem(DECK_KEYS.words));
  const cards = safeParse(storage.getItem(DECK_KEYS.cards));
  return {
    words: Array.isArray(words) ? words : [],
    cards:
      cards && typeof cards === "object" && !Array.isArray(cards) ? cards : {},
  };
}

/**
 * mergeServerDeck(deck, wbStatePayload) -> deck
 * wbStatePayload = GET /api/wb/state 的镜像（{words, cards}，同 workbench 快照形状）。
 * 本地为准：本地已存在的 word.id / card key 冲突保留本地；server-only 的词与卡补进。
 */
export function mergeServerDeck(deck, payload) {
  const base =
    deck && typeof deck === "object" ? deck : { words: [], cards: {} };
  const words = Array.isArray(base.words) ? base.words.slice() : [];
  const cards =
    base.cards && typeof base.cards === "object" && !Array.isArray(base.cards)
      ? Object.assign({}, base.cards)
      : {};

  const haveWordId = {};
  for (const w of words) {
    if (w && w.id != null) haveWordId[String(w.id)] = true;
  }
  const serverWords =
    payload && Array.isArray(payload.words) ? payload.words : [];
  for (const w of serverWords) {
    if (w && w.id != null && !haveWordId[String(w.id)]) {
      words.push(w);
      haveWordId[String(w.id)] = true;
    }
  }

  const serverCards =
    payload && payload.cards && typeof payload.cards === "object"
      ? payload.cards
      : {};
  for (const key of Object.keys(serverCards)) {
    if (!Object.prototype.hasOwnProperty.call(cards, key)) {
      cards[key] = serverCards[key];
    }
  }

  return { words, cards };
}

/**
 * buildKnownSet(deck) -> Set<lower hw>
 * 仅收录"已学习"词（word 存在且 cards[String(id)].reps>0），hw 归一为小写。
 */
export function buildKnownSet(deck) {
  const known = new Set();
  if (!deck || typeof deck !== "object") return known;
  const words = Array.isArray(deck.words) ? deck.words : [];
  const cards =
    deck.cards && typeof deck.cards === "object" ? deck.cards : {};
  for (const w of words) {
    if (!w || w.id == null || w.hw == null) continue;
    const card = cards[String(w.id)];
    if (card && typeof card === "object" && Number(card.reps) > 0) {
      known.add(String(w.hw).toLowerCase());
    }
  }
  return known;
}

/** isKnown(knownSet, lemma) -> bool：lemma 小写后是否命中已知集。 */
export function isKnown(knownSet, lemma) {
  if (!knownSet || lemma == null) return false;
  return knownSet.has(String(lemma).toLowerCase());
}

/**
 * annotateWithDeck(deck, annotateResp) -> {
 *   sentences: [{idx, tokens:[{text,lemma,pos,known}]}],
 *   stats: {total_tokens, known_tokens, known_rate, unknown_top:[{lemma,count}]}
 * }
 *
 * - 每个 token 加 known 布尔（纯 isKnown，标点也保留、记 known=false，进 total）。
 * - stats.known_rate = known/total 四舍五入 2 位；total==0 时 rate=0。
 * - unknown_top = 未知 token 中"生词候选"lemma 按频次降序（同频按首现先后）取前 10；
 *   标点（pos 属 PUNCT/SYM 或 text 全非字母）不入候选、也不计入。
 */
export function annotateWithDeck(deck, annotateResp) {
  const knownSet = buildKnownSet(deck);
  const srcSentences =
    annotateResp && Array.isArray(annotateResp.sentences)
      ? annotateResp.sentences
      : [];

  const annotated = srcSentences.map((s) => ({
    idx: s && s.idx != null ? s.idx : 0,
    tokens: (Array.isArray(s && s.tokens) ? s.tokens : []).map((tok) =>
      Object.assign({}, tok, {
        known: isKnown(knownSet, tok ? tok.lemma : null),
      }),
    ),
  }));

  let totalTokens = 0;
  let knownTokens = 0;
  const counts = new Map(); // lemma(lower) -> count
  const firstSeen = new Map(); // lemma(lower) -> 首个 token 流下标
  let streamPos = 0;

  for (const s of annotated) {
    for (const tok of s.tokens) {
      totalTokens++;
      if (tok.known) knownTokens++;
      if (!tok.known && isLemmaCandidate(tok)) {
        const key = String(tok.lemma).toLowerCase();
        if (!counts.has(key)) {
          counts.set(key, 0);
          firstSeen.set(key, streamPos);
        }
        counts.set(key, counts.get(key) + 1);
      }
      streamPos++;
    }
  }

  const unknownTop = Array.from(counts.entries())
    .map(([lemma, count]) => ({ lemma, count }))
    .sort(
      (a, b) =>
        b.count - a.count || firstSeen.get(a.lemma) - firstSeen.get(b.lemma),
    )
    .slice(0, 10);

  const knownRate =
    totalTokens === 0 ? 0 : Math.round((knownTokens / totalTokens) * 100) / 100;

  return {
    sentences: annotated,
    stats: {
      total_tokens: totalTokens,
      known_tokens: knownTokens,
      known_rate: knownRate,
      unknown_top: unknownTop,
    },
  };
}
