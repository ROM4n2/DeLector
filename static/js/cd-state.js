/* DeLector - Cards State Container (L1 Pure Layer)
 *
 * cards.js 的 15 个模块级可变状态收口于此（计划 docs/plans/2026-10-20-cards-state-container.md
 * Task 2；设计稿 docs/specs/2026-10-20-cards-state-view-decoupling-design.md §6.1）。
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制，`LAYER_SPEC["cd-state.js"]`）：
 *   MUST NOT 触碰 DOM；MUST NOT 发网络请求；MUST NOT 弹用户提示；
 *   MUST NOT 用计时器；MUST NOT 有顶层 `let`/`var`；import 白名单为**空**
 *   （容器不依赖任何东西，才谈得上「谁都能读、写入面是一份清单」）。
 *
 * 两条硬约束（改动前请先读，都是实测出来的，不是风格偏好）：
 *   1) 初值 MUST 逐字取自 cards.js 原文 —— 设计稿初稿曾把 segment/viewMode 写成
 *      'vocab'/'grid'（实际是 "due"/"deck"），那会静默改变首屏行为。
 *   2) `stepDeckState` MUST NOT 夹取。`stepDeck` 今天没有 clamp，边界靠按钮
 *      `disabled` 挡 + `renderDeckStage` 的渲染期纠正（`renderDeckStage` 那行
 *      纠正保持内联，不搬进来 —— 它依赖传入的 deck.length）。
 *
 * 只有 enterSegment / stepDeckState 两个访问器：只有它们的写序列编码了真实不变量
 * （切段复位卡组、移卡复位翻面）。其余状态走直接字段访问，不再加十几个 getter。
 */
'use strict';

export const cardState = {
  // 簇 1 卡册浏览 —— 初值逐字取自 cards.js:29-34
  catalog: {
    segment: "due", // cards.js:29  'due' | 'pending' | 'mastered' | 'prep'
    viewMode: "deck", // cards.js:30  'deck' | 'grid'
    cards: { vocab_cards: [], grammar_cards: [] }, // cards.js:33  cachedCards
    dueCards: { due_vocab: [], due_grammar: [], due_count: 0 }, // cards.js:34  cachedDueCards
  },
  // 簇 2 翻牌卡组 —— 初值取自 cards.js:31-32,35,429
  deck: { index: 0, flipped: false, lastFlipTime: 0, reviewInFlight: false },
  // 簇 3 测验 —— 初值取自 cards.js:659-667（对象就地可变，与现状一致：8 个读者共享同一引用）
  quiz: { mode: "flashcard", queue: [], index: 0, correct: 0, wrong: 0, isFlipped: false, allVocab: [] },
  // 簇 4 介词矩阵 —— 初值取自 cards.js:1102-1106
  // `loading` 是**正在飞的那次请求**（并发点击共用，不重复发），不是布尔；初值 null。
  prep: { cache: null, loading: null, caseFilter: "", searchQuery: "", searchTimer: null },
  // 簇 5 瞬时 UI —— cards.js:35
  toast: { undoTimer: null },
};

/** 切段：必须同时复位卡位与翻面（`setCardSegment` 的三写不变量收口于此）。 */
export function enterSegment(segment) {
  cardState.catalog.segment = segment;
  cardState.deck.index = 0;
  cardState.deck.flipped = false;
}

/** 移动卡位：**逐字复刻** `stepDeck` 的两写，不含任何夹取（见文件头第 2 条）。 */
export function stepDeckState(delta) {
  cardState.deck.index += delta;
  cardState.deck.flipped = false;
}
