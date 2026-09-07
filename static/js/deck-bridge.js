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

/* ======================================================================
 * A6 进卡纯函数（Node 可测性硬约束同上：零 import / 不碰浏览器全局）。
 *
 * 只操作 deck 对象 {words, cards} —— localStorage 写回 / PUT /api/wb/state
 * 镜像同步由调用方（encounter.js 页面侧）完成，这里保持纯净。
 *
 * ⚠ 语义真相（与背词工作台 static/german/workbench.html 对齐，RED-1）：
 *   工作台真实队列语义是——一个词处于「新/待排」iff **cards 里没有它的条目**
 *   （!S.cards[w.id]，workbench ~2122 newIds 池 & ~2310 手动 new）；due 词要求
 *   reps>0（~2114）；工作台自己的「置为 new」就是 delete S.cards[id]（~2938）；
 *   真卡存的是数值毫秒 due（~2043）。若进卡时写一张 reps:0 / due=ISO 的 starter 卡，
 *   会让该词对两个池都不可见 → 永不排期 → 核心承诺被破坏。
 *
 *   因此 A6 进卡 = **只写词（word），绝不写卡（card）**：让新增自定义词天然满足
 *   !S.cards[w.id]「新词」语义，进入工作台可见词表、可被复习。
 *
 *   自定义词 add 形状（btnWordSave, ~line 3246）：
 *     { id:"u-"+now.toString(36), hw, pos, gloss, ipa, ex, letter,
 *       page:0, tags:[...], custom:true, up:now }   // up = 真实毫秒
 *   FSRS 卡（fsrsReview, ~line 2023/2043）：{s,d,due,last,reps,lapses}
 *   —— 卡仅由工作台自己写/删，A6 不做卡。
 *
 * 说明：
 *   - id 前缀 'u-' + genId 与 workbench 一致（'u-' + Date.now().toString(36)），
 *     跨页同源自定义词按 id/hw 去重不打架。
 *   - genId 参数可传函数（默认 Date.now().toString(36)）也可直接传字符串后缀，
 *     便于测试确定性注入；nowMs 显式注入 up（真实毫秒，默认 Date.now()），
 *     绝不靠解析 id 后缀还原 up。
 * ==================================================================== */

/** 内部：解析 genId（函数→调用取串 / 字符串→直接用 / 缺省→fallbackMs 的 base36）。 */
function _genIdSuffix(genId, fallbackMs) {
  if (typeof genId === "function") {
    const v = genId();
    return v == null ? fallbackMs.toString(36) : String(v);
  }
  if (genId != null) return String(genId);
  return fallbackMs.toString(36);
}

/** 内部：词表分段首字母（与 workbench letterOf 口径一致：剥括号+剥冠词/小品词）。 */
function _letterOf(hw) {
  const s = String(hw || "")
    .replace(/\([^)]*\)/g, " ")
    .replace(
      /^(der|die|das|ein|eine|einen|dem|den|sich|zu|an|auf|aus|bei|ein|für|mit|nach|von|vor|zu)\s+/i,
      "",
    )
    .trim();
  const ch = s.charAt(0) || "";
  return ch.toUpperCase();
}

/**
 * makeWordObject(lemma, gloss, pos, genId, nowMs) -> 自定义 word 对象
 * 字段与 workbench 自定义词逐项对齐（含 custom:true）。lemma 即 hw。
 * up 直接取 nowMs（真实毫秒；缺省 Date.now()）——**绝不**从 id 后缀解析。
 */
export function makeWordObject(lemma, gloss, pos, genId, nowMs) {
  const now = nowMs != null && !Number.isNaN(Number(nowMs)) ? Number(nowMs) : Date.now();
  const suffix = _genIdSuffix(genId, now);
  const hw = String(lemma == null ? "" : lemma);
  return {
    id: "u-" + suffix,
    hw: hw,
    pos: String(pos == null ? "" : pos),
    gloss: String(gloss == null ? "" : gloss),
    ipa: "",
    ex: [],
    letter: _letterOf(hw),
    page: 0,
    tags: [],
    custom: true,
    up: now,
  };
}

/**
 * addCardToDeck(deck, lemma, {gloss,pos,genId,nowMs}) -> {deck, added, reason}
 *
 * 语义（word-only，绝不写卡——对齐工作台 !S.cards[w.id]「新词」真值）：
 *   added=true  reason='added'     词不存在 → 只追加 1 个自定义 word，**不建 card**
 *   added=false reason='exists'    词已在 deck.words（尚无 learned 卡）→ 不重复
 *   added=false reason='learned'   词已在 deck.words 且 cards[id].reps>0 → 不动
 *
 * cards 永不新增键；返回时 cards 保持原 deck.cards 原样（坏 deck 按空 {} 兜底）。
 * 幂等：同一 lemma（hw 忽略大小写）二次调用绝不重复追加。坏/残缺 deck 安全降级为空。
 */
export function addCardToDeck(deck, lemma, opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const words = Array.isArray(deck && deck.words) ? deck.words.slice() : [];
  const cards =
    deck && deck.cards && typeof deck.cards === "object" && !Array.isArray(deck.cards)
      ? deck.cards
      : {};
  const hw = String(lemma == null ? "" : lemma);
  const lower = hw.toLowerCase();

  for (const w of words) {
    if (!w || w.hw == null) continue;
    if (String(w.hw).toLowerCase() === lower) {
      const card = cards[String(w.id)];
      const reason = card && typeof card === "object" && Number(card.reps) > 0
        ? "learned"
        : "exists";
      return { deck: { words: words, cards: cards }, added: false, reason: reason };
    }
  }

  const nowMs = o.nowMs != null && !Number.isNaN(Number(o.nowMs)) ? Number(o.nowMs) : Date.now();
  const word = makeWordObject(hw, o.gloss, o.pos, o.genId, nowMs);
  words.push(word);
  // 只写词、不建卡：让 !S.cards[w.id]「新词」语义保持（RED-1 修复）。

  return { deck: { words: words, cards: cards }, added: true, reason: "added" };
}
