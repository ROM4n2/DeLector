/* DeLector - Cards Management, 3D Poker Deck & Quiz Engine */
"use strict";

import { state, esc, jsAttr, api } from "./core.js";
import { playGermanAudio } from "./player.js";
import { Companion } from "./companion.js";
import { refreshCardCounters } from "./reader.js";

let cardSegment = "due"; // 'due' | 'pending' | 'mastered' | 'prep'
let cardViewMode = "deck"; // 'deck' | 'grid'
let deckIndex = 0;
let deckFlipped = false;
let cachedCards = { vocab_cards: [], grammar_cards: [] };
let cachedDueCards = { due_vocab: [], due_grammar: [], due_count: 0 };
let undoToastTimer = null;
let _lastFlipTime = 0;

// ── Goethe A1 Wortliste & Sprechen State ──
let a1Mode = 'vocab'; // 'vocab' | 'teil2' | 'teil3'
let a1CurrentTopic = '';
let a1SearchQuery = '';
let a1TopicsCache = null;
let a1VocabCache = [];
let a1Teil2Cache = [];
let a1Teil3Cache = [];
let a1CardIndex = 0;
let a1CardFlipped = false;
let _a1SavedLemmas = new Set();

export function setCardSegment(seg) {
  cardSegment = seg;
  deckIndex = 0;
  deckFlipped = false;
  ['due', 'pending', 'mastered', 'prep', 'a1'].forEach(s => {
    const btn = document.getElementById('seg-' + s);
    if (btn) btn.classList.toggle('active', s === seg);
  });
  renderCardsGrid();
}

export function setCardViewMode(mode) {
  cardViewMode = mode;
  document
    .getElementById("mode-btn-deck")
    ?.classList.toggle("active", mode === "deck");
  document
    .getElementById("mode-btn-grid")
    ?.classList.toggle("active", mode === "grid");
  renderCardsGrid();
}

export async function loadCards() {
  updateAudioCacheInfo();
  try {
    const [allCards, dueCards] = await Promise.all([
      api("/api/cards"),
      api("/api/cards/due"),
    ]);
    cachedCards = allCards;
    cachedDueCards = dueCards;
  } catch (e) {
    cachedCards = { vocab_cards: [], grammar_cards: [] };
    cachedDueCards = { due_vocab: [], due_grammar: [], due_count: 0 };
  }

  const vAll = cachedCards.vocab_cards || [];
  const gAll = cachedCards.grammar_cards || [];
  const totalPending =
    vAll.filter((c) => !c.mastered).length +
    gAll.filter((c) => !c.mastered).length;
  const totalMastered =
    vAll.filter((c) => c.mastered).length +
    gAll.filter((c) => c.mastered).length;

  const sd = document.getElementById("seg-due-count");
  const sp = document.getElementById("seg-pending-count");
  const sm = document.getElementById("seg-mastered-count");
  if (sd) sd.textContent = cachedDueCards.due_count || 0;
  if (sp) sp.textContent = totalPending;
  if (sm) sm.textContent = totalMastered;

  renderCardsGrid();
}

export async function refreshDueCount() {
  try {
    cachedDueCards = await api("/api/cards/due");
    const sd = document.getElementById("seg-due-count");
    if (sd) sd.textContent = cachedDueCards.due_count || 0;
  } catch (e) {}
}

export function renderCardsGrid() {
  if (cardSegment === 'a1') {
    document.getElementById('prep-filter-bar')?.classList.add('hidden');
    document.getElementById('a1-toolbar')?.classList.remove('hidden');
    if (a1Mode === 'vocab') {
      document.querySelector('.cards-view-toggle')?.classList.remove('hidden');
    } else {
      document.querySelector('.cards-view-toggle')?.classList.add('hidden');
    }
    if (!a1VocabCache.length || !a1TopicsCache) {
      loadA1Data().then(renderA1);
    } else {
      renderA1();
    }
    return;
  }
  document.getElementById('a1-toolbar')?.classList.add('hidden');

  // 介词矩阵段跟其余三段的数据源完全无关（不是 cachedCards 的过滤视图），
  // 所以在算 vList/gList 之前就分流，免得白跑一遍过滤。
  if (cardSegment === "prep") {
    document.getElementById("prep-filter-bar")?.classList.remove("hidden");
    // 牌盒/目录切换在这一段没有意义：两个模式渲染同一个矩阵，
    // 点了只是白付一次 691 行重排。
    document.querySelector(".cards-view-toggle")?.classList.add("hidden");
    if (_prepMatrixCache) renderPrepMatrix();
    else loadPrepMatrix().then(renderPrepMatrix);
    return;
  }
  document.getElementById("prep-filter-bar")?.classList.add("hidden");
  document.querySelector(".cards-view-toggle")?.classList.remove("hidden");

  let vList = [];
  let gList = [];

  if (cardSegment === "due") {
    vList = cachedDueCards.due_vocab || [];
    gList = cachedDueCards.due_grammar || [];
  } else if (cardSegment === "mastered") {
    vList = (cachedCards.vocab_cards || []).filter((c) => !!c.mastered);
    gList = (cachedCards.grammar_cards || []).filter((c) => !!c.mastered);
  } else {
    vList = (cachedCards.vocab_cards || []).filter((c) => !c.mastered);
    gList = (cachedCards.grammar_cards || []).filter((c) => !c.mastered);
  }

  const container = document.getElementById("cards-container");
  if (!container) return;

  if (vList.length === 0 && gList.length === 0) {
    const emptyIcon =
      cardSegment === "due" ? "🎉" : cardSegment === "mastered" ? "🛡️" : "🎴";
    const emptyTitle =
      cardSegment === "due"
        ? "今日复习任务已全部达成！"
        : cardSegment === "mastered"
          ? "尚无已掌握归档卡片"
          : "待复习卡片库空空如也";
    const emptyDesc =
      cardSegment === "due"
        ? "太棒了！艾宾浩斯记忆排程显示今日暂无到期卡片。您可以切换至「待复习全量」主动温故或进入文库精读新文章。"
        : "在阅读器中点击生词或语法考点，即可一键收录。";

    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;box-shadow:2px 2px 0 var(--ink);">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">${emptyIcon}</div>
        <div style="font-family:var(--serif-heading);font-size:1.375rem;color:var(--ink);margin-bottom:0.35rem;">
          ${emptyTitle}
        </div>
        <p style="font-size:0.8125rem;color:var(--pencil);max-width:440px;margin:0 auto;line-height:1.6;">
          ${emptyDesc}
        </p>
      </div>
    `;
    return;
  }

  if (cardViewMode === "deck") {
    renderDeckStage(vList, gList);
  } else {
    renderCatalogGrid(vList, gList);
  }
}

export function renderDeckStage(vList, gList) {
  const container = document.getElementById("cards-container");
  if (!container) return;

  const deck = [
    ...vList.map((c) => ({ ...c, _type: "vocab" })),
    ...gList.map((c) => ({ ...c, _type: "grammar" })),
  ];

  if (deckIndex >= deck.length) deckIndex = Math.max(0, deck.length - 1);
  const card = deck[deckIndex];
  const total = deck.length;
  const isVocab = card._type === "vocab";

  const ef = card.ease_factor || 2.5;
  const iv = card.interval_days || 1;
  const rep = card.repetition_count || 0;

  let nextAgain = 1;
  let nextHard = 2;
  let nextGood = 4;
  let nextEasy = 9;

  if (card.next_intervals && typeof card.next_intervals === "object") {
    nextAgain = card.next_intervals[1] ?? card.next_intervals["1"] ?? 1;
    nextHard = card.next_intervals[2] ?? card.next_intervals["2"] ?? 2;
    nextGood = card.next_intervals[3] ?? card.next_intervals["3"] ?? 4;
    nextEasy = card.next_intervals[4] ?? card.next_intervals["4"] ?? 9;
  } else if (rep === 0) {
    nextAgain = 1;
    nextHard = 2;
    nextGood = 4;
    nextEasy = 9;
  } else {
    // Client-side FSRS fallback estimate
    const d = Math.min(10.0, Math.max(1.0, ef));
    const s = Math.max(0.1, iv);
    nextAgain = Math.max(
      1,
      Math.round(Math.min(s, 0.6 * Math.pow(d, -0.3) * Math.pow(s + 1, 0.4))),
    );
    nextHard = Math.max(
      1,
      Math.round(s * (1 + 0.6 * (11 - d) * Math.pow(s, -0.2) * 0.25)),
    );
    nextGood = Math.max(
      1,
      Math.round(s * (1 + 1.0 * (11 - d) * Math.pow(s, -0.2) * 0.25)),
    );
    nextEasy = Math.max(
      1,
      Math.round(s * (1 + 1.4 * (11 - d) * Math.pow(s, -0.2) * 0.25)),
    );
  }

  container.innerHTML = `
    <div class="deck-stage" id="deck-stage">
      <div class="deck-meta-bar">
        <span>🎴 3D 扑克翻牌盒 · POKER FLIP STACK</span>
        <span class="deck-counter-badge">KARTE ${deckIndex + 1} / ${total}</span>
      </div>

      <div class="deck-stack-wrap" id="deck-stack-wrap">
        ${total > 2 ? '<div class="deck-card-layer deck-card-layer-3"></div>' : ""}
        ${total > 1 ? '<div class="deck-card-layer deck-card-layer-2"></div>' : ""}

        <!-- 3D Flipping Card Container -->
        <div class="deck-active-card ${deckFlipped ? "is-flipped" : ""}" id="deck-active-card">

          <!-- 🎴 FRONT FACE (正面) -->
          <div class="deck-card-face card-front" onclick="toggleDeckFlip(event)">
            <div class="deck-card-head">
              <div>
                <div class="deck-word-title">${isVocab ? esc(card.word) : esc(card.grammar_name)}</div>
                <div class="deck-meta-lemma">
                  ${isVocab ? `${esc(card.lemma || card.word)} · ${esc(card.pos || "WORT")}${card.gender ? " · " + esc(card.gender) : ""}` : "Goethe Grammatik"}
                </div>
              </div>
              <div class="card-top-actions">
                ${isVocab ? `<button class="speaker-btn" style="font-size:1.125rem;" onclick="event.stopPropagation();playGermanAudio(${jsAttr(card.word)})" title="朗读单词">🔊</button>` : ""}
                <span class="cefr-badge badge-${card.cefr_level || "A1"}">${card.cefr_level || "A1"}</span>
                <button class="card-del-btn" onclick="event.stopPropagation();deleteCard(${jsAttr(card._type)}, ${card.id}, ${jsAttr(isVocab ? card.word : card.grammar_name)})" title="删除此卡片">✕</button>
              </div>
            </div>

            <!-- Front Center Watermark / Prompt -->
            <div class="deck-front-center">
              <div class="deck-seal-stamp">KARTEIKARTE · ${card.cefr_level || "A1"}</div>
              <div class="deck-flip-guide">
                <div class="deck-flip-icon">🔀</div>
                <div class="deck-flip-prompt">点击卡片 或 按空格 (Space) 3D 翻转背面</div>
              </div>
            </div>

            <!-- Front Footer -->
            <div class="deck-card-footer" onclick="event.stopPropagation()">
              <span class="card-stats-tag">${card.mastered ? "🛡️ 已掌握" : card.due_date ? `⏳ 到期: ${card.due_date}` : "⏳ 待复习"} · ${card.correct_count || 0} 正 / ${card.wrong_count || 0} 误</span>
              <button class="card-master-btn ${card.mastered ? "mastered-active" : ""}" onclick="toggleMaster('${card._type}', ${card.id}, ${!!card.mastered})">
                ${card.mastered ? "↺ 重返待复习" : "✓ 斩 (已掌握)"}
              </button>
            </div>
          </div>

          <!-- 🎴 BACK FACE (背面 180° 旋转) -->
          <div class="deck-card-face card-back">
            <div class="deck-card-head">
              <div>
                <span class="deck-back-lemma">${isVocab ? esc(card.word) : esc(card.grammar_name)}</span>
                <span class="deck-back-tag">RÜCKSEITE · 释义</span>
              </div>
              <div class="card-top-actions">
                <span class="cefr-badge badge-${card.cefr_level || "A1"}">${card.cefr_level || "A1"}</span>
                <span class="deck-flip-back-btn" onclick="toggleDeckFlip(event)" title="翻回正面">↶ 翻回</span>
              </div>
            </div>

            <!-- Back Center Body -->
            <div class="deck-back-body">
              <div class="deck-def-text">${esc(isVocab ? card.definition_zh : card.explanation_zh)}</div>
              ${!isVocab && card.rule_formula ? `<div class="grammar-memo-formula" style="margin-bottom:0.875rem;">${esc(card.rule_formula)}</div>` : ""}
              ${card.sentence_context ? `<div class="deck-sent-quote">${esc(card.sentence_context)}</div>` : ""}
            </div>

            <!-- SuperMemo SM-2 Rating Bar on Back -->
            <div class="deck-sm2-rating-bar" onclick="event.stopPropagation()">
              <button class="sm2-btn sm2-btn-again" onclick="event.stopPropagation();submitCardReview('${card._type}', ${card.id}, 1)" title="完全忘记，重置为 1 天">
                <span>1 重来</span>
                <span class="sm2-int-tag">${nextAgain}天</span>
              </button>
              <button class="sm2-btn sm2-btn-hard" onclick="event.stopPropagation();submitCardReview('${card._type}', ${card.id}, 2)" title="勉强想起，短间隔复习">
                <span>2 困难</span>
                <span class="sm2-int-tag">${nextHard}天</span>
              </button>
              <button class="sm2-btn sm2-btn-good" onclick="event.stopPropagation();submitCardReview('${card._type}', ${card.id}, 3)" title="正常回忆，按艾宾浩斯递增">
                <span>3 良好</span>
                <span class="sm2-int-tag">${nextGood}天</span>
              </button>
              <button class="sm2-btn sm2-btn-easy" onclick="event.stopPropagation();submitCardReview('${card._type}', ${card.id}, 4)" title="熟练掌握，大幅增加间隔">
                <span>4 简单</span>
                <span class="sm2-int-tag">${nextEasy}天</span>
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- Navigation Stepper Bar -->
      <div class="deck-nav-controls">
        <button class="deck-btn-nav" id="deck-btn-prev" onclick="stepDeck(-1)" ${deckIndex === 0 ? "disabled" : ""}>
          ‹ 上一张 (A)
        </button>
        <button class="btn btn-dark" id="deck-btn-flip-ctrl" style="font-size:0.75rem;padding:0.45rem 1.25rem;" onclick="toggleDeckFlip(event)">
          ${deckFlipped ? "↶ 翻回正面 (Space)" : "🔀 翻至背面 (Space)"}
        </button>
        <button class="deck-btn-nav" id="deck-btn-next" onclick="stepDeck(1)" ${deckIndex >= total - 1 ? "disabled" : ""}>
          下一张 (D) ›
        </button>
      </div>
    </div>
  `;

  attachDeckSwipeListener();
}

export async function submitCardReview(type, id, grade) {
  try {
    if (navigator.vibrate) {
      navigator.vibrate(grade >= 3 ? [15, 30, 20] : 30);
    }
    await api(`/api/cards/${type}/${id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grade, card_type: type }),
    });
    showUndoToast(`✓ 已记录记忆评分 (FSRS 排程已更新)`);
    stepDeck(1);
    refreshDueCount();
    Companion.celebrate(grade >= 3 ? "review_good" : "review_hard");
  } catch (e) {
    console.error("Failed to submit review:", e);
  }
}

export function toggleDeckFlip(e) {
  if (e) e.stopPropagation();
  const now = Date.now();
  if (now - _lastFlipTime < 200) return; // 防 Android 双击事件抖动
  _lastFlipTime = now;
  if (navigator.vibrate) navigator.vibrate(15);
  deckFlipped = !deckFlipped;
  const cardEl = document.getElementById("deck-active-card");
  if (cardEl) {
    cardEl.classList.toggle("is-flipped", deckFlipped);
  }
  const flipBtn = document.getElementById("deck-btn-flip-ctrl");
  if (flipBtn) {
    flipBtn.textContent = deckFlipped
      ? "↶ 翻回正面 (Space)"
      : "🔀 翻至背面 (Space)";
  }
}

export function stepDeck(direction) {
  const cardEl = document.getElementById("deck-active-card");
  if (cardEl) {
    cardEl.classList.add(
      direction > 0 ? "is-swiping-left" : "is-swiping-right",
    );
  }
  setTimeout(() => {
    deckIndex += direction;
    deckFlipped = false;
    renderCardsGrid();
  }, 160);
}

function attachDeckSwipeListener() {
  const cardEl = document.getElementById("deck-active-card");
  if (!cardEl) return;

  let startX = 0;
  let currentX = 0;
  let isDragging = false;

  const onTouchStart = (e) => {
    startX = e.type.includes("touch") ? e.touches[0].clientX : e.clientX;
    isDragging = true;
  };

  const onTouchMove = (e) => {
    if (!isDragging) return;
    if (deckFlipped) return; // 背面有评分按钮，不处理滑动
    currentX = e.type.includes("touch") ? e.touches[0].clientX : e.clientX;
    const diff = currentX - startX;
    cardEl.style.transform = `translateX(${diff}px) rotate(${diff * 0.05}deg) ${deckFlipped ? "rotateY(180deg)" : ""}`;
  };

  const onTouchEnd = () => {
    if (!isDragging) return;
    isDragging = false;
    if (deckFlipped) return; // 背面不触发翻页
    const diff = currentX - startX;
    if (diff < -70) {
      stepDeck(1);
    } else if (diff > 70) {
      stepDeck(-1);
    } else {
      cardEl.style.transform = deckFlipped ? "rotateY(180deg)" : "";
    }
  };

  cardEl.addEventListener("touchstart", onTouchStart, { passive: true });
  cardEl.addEventListener("touchmove", onTouchMove, { passive: true });
  cardEl.addEventListener("touchend", onTouchEnd);
}

export function renderCatalogGrid(vList, gList) {
  const container = document.getElementById("cards-container");
  if (!container) return;

  container.innerHTML = `
    <div class="section-label" style="margin-bottom:0.875rem;">
      <span class="section-title">词汇卡 · VOCABULARY (${vList.length})</span>
    </div>
    <div class="card-grid">${vList
      .map(
        (c) => `
      <div class="memo-card ${c.mastered ? "is-mastered" : ""}" id="v-card-${c.id}">
        <div class="memo-card-head">
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <span class="memo-word">${esc(c.word)}</span>
            <button class="speaker-btn" onclick="playGermanAudio(${jsAttr(c.word)})" title="朗读单词">🔊</button>
          </div>
          <div class="card-top-actions">
            <span class="cefr-badge badge-${c.cefr_level || "A1"}">${c.cefr_level || "A1"}</span>
            <button class="card-del-btn" onclick="deleteCard('vocab', ${c.id}, ${jsAttr(c.word)})" title="删除此卡片">✕</button>
          </div>
        </div>
        <div class="memo-def">${esc(c.definition_zh)}</div>
        <div class="memo-meta">${esc(c.lemma)} · ${esc(c.pos || "WORT")}${c.gender ? " · " + esc(c.gender) : ""}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
        <div class="card-footer-actions">
          <span class="card-stats-tag">${c.correct_count || 0} 正 / ${c.wrong_count || 0} 误${c.due_date ? ` · 到期: ${c.due_date}` : ""}</span>
          <button class="card-master-btn ${c.mastered ? "mastered-active" : ""}" onclick="toggleMaster('vocab', ${c.id}, ${!!c.mastered})">
            ${c.mastered ? "↺ 重返待复习" : "✓ 斩 (已掌握)"}
          </button>
        </div>
      </div>`,
      )
      .join("")}</div>

    <div class="section-label" style="margin-top:2rem;margin-bottom:0.875rem;">
      <span class="section-title">歌德语法考点卡 · GRAMMAR (${gList.length})</span>
    </div>
    ${gList
      .map(
        (c) => `
      <div class="grammar-memo-card ${c.mastered ? "is-mastered" : ""}" id="g-card-${c.id}">
        <div class="grammar-memo-head">
          <span class="grammar-memo-name">${esc(c.grammar_name)}</span>
          <div class="card-top-actions">
            <span class="cefr-badge badge-${c.cefr_level || "A1"}">Goethe ${c.cefr_level || "A1"}</span>
            <button class="card-del-btn" onclick="deleteCard('grammar', ${c.id}, ${jsAttr(c.grammar_name)})" title="删除此考点卡">✕</button>
          </div>
        </div>
        ${c.rule_formula ? `<div class="grammar-memo-formula">${esc(c.rule_formula)}</div>` : ""}
        <div class="grammar-memo-exp">${esc(c.explanation_zh)}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
        <div class="card-footer-actions">
          <span class="card-stats-tag">${c.correct_count || 0} 正 / ${c.wrong_count || 0} 误</span>
          <button class="card-master-btn ${c.mastered ? "mastered-active" : ""}" onclick="toggleMaster('grammar', ${c.id}, ${!!c.mastered})">
            ${c.mastered ? "↺ 重返待复习" : "✓ 斩 (已掌握)"}
          </button>
        </div>
      </div>`,
      )
      .join("")}
  `;
}

export async function deleteCard(type, id, name) {
  try {
    await api(`/api/cards/${type}/${id}`, { method: "DELETE" });
    showUndoToast(`已删除卡片「${name}」`);
    loadCards();
  } catch (e) {
    alert("删除卡片失败: " + e.message);
  }
}

export async function toggleMaster(type, id, currentMastered) {
  try {
    await api(`/api/cards/${type}/${id}/master`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mastered: !currentMastered }),
    });
    loadCards();
  } catch (e) {
    alert("更新卡片状态失败: " + e.message);
  }
}

export function showUndoToast(msg) {
  let toast = document.getElementById("undo-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "undo-toast";
    toast.className = "undo-toast";
    document.body.appendChild(toast);
  }
  if (undoToastTimer) clearTimeout(undoToastTimer);

  toast.innerHTML = `<span>${msg}</span>`;
  toast.classList.remove("hidden");

  undoToastTimer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 3500);
}

// ── Quiz Engine ──────────────────────────────────────────────────────────────
let quizState = {
  mode: "flashcard",
  queue: [],
  index: 0,
  correct: 0,
  wrong: 0,
  isFlipped: false,
  allVocab: [],
};

export function openQuizOverlay() {
  const overlay = document.getElementById("quiz-overlay");
  if (!overlay) return;
  overlay.classList.remove("hidden");
  document.getElementById("quiz-step-mode")?.classList.remove("hidden");
  document.getElementById("quiz-step-run")?.classList.add("hidden");
  document.getElementById("quiz-step-done")?.classList.add("hidden");
}

export function closeQuizOverlay() {
  const overlay = document.getElementById("quiz-overlay");
  if (overlay) overlay.classList.add("hidden");
  loadCards();
}

export async function startQuiz(mode) {
  quizState.mode = mode;
  quizState.correct = 0;
  quizState.wrong = 0;
  quizState.index = 0;
  quizState.isFlipped = false;

  const data = await api("/api/cards");
  const vocab = data.vocab_cards || [];
  quizState.allVocab = vocab;

  if (vocab.length === 0) {
    alert("卡片库中暂无词汇卡，请先在文章阅读中收集词汇！");
    closeQuizOverlay();
    return;
  }

  const pending = vocab.filter((c) => !c.mastered);
  const pool = pending.length > 0 ? pending : vocab;
  pool.sort((a, b) => {
    const wA = (a.wrong_count || 0) * 2 - (a.correct_count || 0);
    const wB = (b.wrong_count || 0) * 2 - (b.correct_count || 0);
    return wB - wA;
  });

  quizState.queue = pool.slice(0, 15);

  document.getElementById("quiz-step-mode")?.classList.add("hidden");
  document.getElementById("quiz-step-done")?.classList.add("hidden");
  document.getElementById("quiz-step-run")?.classList.remove("hidden");

  renderCurrentQuizCard();
}

export function renderCurrentQuizCard() {
  const { queue, index, mode, correct, wrong } = quizState;
  if (index >= queue.length) {
    finishQuiz();
    return;
  }

  const card = queue[index];
  const total = queue.length;

  const posEl = document.getElementById("quiz-pos");
  const totEl = document.getElementById("quiz-total");
  const corEl = document.getElementById("quiz-score-correct");
  const wrgEl = document.getElementById("quiz-score-wrong");
  const progFill = document.getElementById("quiz-progress-fill");

  if (posEl) posEl.textContent = index + 1;
  if (totEl) totEl.textContent = total;
  if (corEl) corEl.textContent = correct;
  if (wrgEl) wrgEl.textContent = wrong;
  if (progFill) progFill.style.width = `${Math.round((index / total) * 100)}%`;

  document.getElementById("quiz-flashcard-wrap")?.classList.add("hidden");
  document.getElementById("quiz-dictation-wrap")?.classList.add("hidden");
  document.getElementById("quiz-choice-wrap")?.classList.add("hidden");

  if (mode === "flashcard") {
    const wrap = document.getElementById("quiz-flashcard-wrap");
    wrap?.classList.remove("hidden");
    quizState.isFlipped = false;

    const front = wrap.querySelector(".quiz-card-front");
    const back = wrap.querySelector(".quiz-card-back");
    const actions = document.getElementById("quiz-fc-actions");
    if (front) front.classList.remove("hidden");
    if (back) back.classList.add("hidden");
    if (actions) actions.classList.add("hidden");

    const wEl = document.getElementById("quiz-fc-word");
    const bEl = document.getElementById("quiz-fc-cefr");
    const dEl = document.getElementById("quiz-fc-def");
    const sEl = document.getElementById("quiz-fc-sent");

    if (wEl) wEl.textContent = card.word;
    if (bEl)
      bEl.textContent = `${card.cefr_level || "A1"} · ${card.pos || "WORT"}`;
    if (dEl) dEl.textContent = card.definition_zh;
    if (sEl) sEl.textContent = card.sentence_context || "";

    playGermanAudio(card.word);
  } else if (mode === "dictation") {
    const wrap = document.getElementById("quiz-dictation-wrap");
    wrap?.classList.remove("hidden");

    const defEl = document.getElementById("quiz-dict-def");
    const hintEl = document.getElementById("quiz-dict-sent-hint");
    const inputEl = document.getElementById("quiz-dict-input");
    const fbEl = document.getElementById("quiz-dict-feedback");
    const nextBtn = document.getElementById("quiz-dict-next");

    if (defEl) defEl.textContent = card.definition_zh;
    if (hintEl) {
      const masked = (card.sentence_context || "").replace(
        new RegExp(card.word, "gi"),
        "______",
      );
      hintEl.textContent = masked;
    }
    if (inputEl) {
      inputEl.value = "";
      inputEl.disabled = false;
      setTimeout(() => inputEl.focus(), 50);
    }
    if (fbEl) {
      fbEl.className = "quiz-dict-feedback hidden";
      fbEl.textContent = "";
    }
    if (nextBtn) nextBtn.classList.add("hidden");
  } else if (mode === "choice") {
    const wrap = document.getElementById("quiz-choice-wrap");
    wrap?.classList.remove("hidden");

    const wEl = document.getElementById("quiz-choice-word");
    const bEl = document.getElementById("quiz-choice-cefr");
    const optContainer = document.getElementById("quiz-choice-options");

    if (wEl) wEl.textContent = card.word;
    if (bEl)
      bEl.textContent = `${card.cefr_level || "A1"} · ${card.pos || "WORT"}`;

    const otherDefs = quizState.allVocab
      .filter(
        (c) =>
          c.id !== card.id &&
          c.definition_zh &&
          c.definition_zh !== card.definition_zh,
      )
      .map((c) => c.definition_zh);

    otherDefs.sort(() => Math.random() - 0.5);
    const options = [card.definition_zh, ...otherDefs.slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    if (optContainer) {
      optContainer.innerHTML = options
        .map(
          (opt, idx) => `
        <button class="quiz-choice-btn" onclick="submitChoice(${idx}, ${options.indexOf(card.definition_zh)})">
          <span style="font-family:var(--mono);margin-right:0.5rem;color:var(--pencil);">${String.fromCharCode(65 + idx)}.</span>
          ${esc(opt)}
        </button>
      `,
        )
        .join("");
    }

    playGermanAudio(card.word);
  }
}

export function flipFlashcard() {
  if (quizState.isFlipped) return;
  quizState.isFlipped = true;
  const wrap = document.getElementById("quiz-flashcard-wrap");
  if (!wrap) return;
  wrap.querySelector(".quiz-card-front")?.classList.add("hidden");
  wrap.querySelector(".quiz-card-back")?.classList.remove("hidden");
  document.getElementById("quiz-fc-actions")?.classList.remove("hidden");
}

export async function submitFlashcard(isCorrect) {
  const card = quizState.queue[quizState.index];
  if (isCorrect) quizState.correct++;
  else quizState.wrong++;

  api("/api/quiz/record", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      card_id: card.id,
      card_type: "vocab",
      mode: "flashcard",
      correct: isCorrect,
    }),
  }).catch(() => {});

  quizState.index++;
  renderCurrentQuizCard();
}

export function checkDictation() {
  const card = quizState.queue[quizState.index];
  const inputEl = document.getElementById("quiz-dict-input");
  const fbEl = document.getElementById("quiz-dict-feedback");
  const nextBtn = document.getElementById("quiz-dict-next");
  if (!inputEl || !fbEl) return;

  const val = inputEl.value.trim();
  if (!val) return;

  inputEl.disabled = true;
  const isMatch = val.toLowerCase() === card.word.trim().toLowerCase();

  if (isMatch) {
    quizState.correct++;
    fbEl.className = "quiz-dict-feedback correct";
    fbEl.innerHTML = `✓ 拼写正确！<b>${esc(card.word)}</b>`;
    playGermanAudio(card.word);
  } else {
    quizState.wrong++;
    fbEl.className = "quiz-dict-feedback wrong";
    fbEl.innerHTML = `✗ 正确拼写为：<b>${esc(card.word)}</b> (你的回答：${esc(val)})`;
  }
  fbEl.classList.remove("hidden");
  if (nextBtn) nextBtn.classList.remove("hidden");

  api("/api/quiz/record", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      card_id: card.id,
      card_type: "vocab",
      mode: "dictation",
      correct: isMatch,
    }),
  }).catch(() => {});
}

export function advanceQuiz() {
  quizState.index++;
  renderCurrentQuizCard();
}

export function submitChoice(chosenIdx, correctIdx) {
  const btns = document.querySelectorAll(".quiz-choice-btn");
  btns.forEach((b) => (b.disabled = true));

  const card = quizState.queue[quizState.index];
  const isCorrect = chosenIdx === correctIdx;

  if (btns[correctIdx]) btns[correctIdx].classList.add("is-correct");
  if (!isCorrect && btns[chosenIdx]) btns[chosenIdx].classList.add("is-wrong");

  if (isCorrect) quizState.correct++;
  else quizState.wrong++;

  api("/api/quiz/record", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      card_id: card.id,
      card_type: "vocab",
      mode: "choice",
      correct: isCorrect,
    }),
  }).catch(() => {});

  setTimeout(() => {
    quizState.index++;
    renderCurrentQuizCard();
  }, 1000);
}

export function finishQuiz() {
  document.getElementById("quiz-step-run")?.classList.add("hidden");
  const donePanel = document.getElementById("quiz-step-done");
  if (donePanel) donePanel.classList.remove("hidden");

  const total = quizState.correct + quizState.wrong;
  const pct = total > 0 ? Math.round((quizState.correct / total) * 100) : 0;

  const dCor = document.getElementById("done-correct");
  const dWrg = document.getElementById("done-wrong");
  const dAcc = document.getElementById("done-accuracy");
  const dEnc = document.getElementById("done-encourage");

  if (dCor) dCor.textContent = quizState.correct;
  if (dWrg) dWrg.textContent = quizState.wrong;
  if (dAcc) dAcc.textContent = `${pct}% 准确率`;

  const mottos = [
    "Übung macht den Meister. (熟能生巧)",
    "Aller Anfang ist schwer, aber du machst Fortschritte! (万事开头难，但你正在进步！)",
    "Wer rastet, der rostet. Bleib dran! (流水不腐，继续保持！)",
    "Schritt für Schritt kommt man ans Ziel. (一步一个脚印，终将抵达终点。)",
  ];
  if (dEnc)
    dEnc.textContent = mottos[Math.floor(Math.random() * mottos.length)];
  Companion.celebrate("quiz_done", { pct });
}

export async function updateAudioCacheInfo() {
  try {
    const info = await api("/api/audio/cache");
    const span = document.getElementById("cache-size-span");
    if (span) span.textContent = `${info.total_size_mb || 0} MB`;
  } catch {}
}

export async function clearAudioCache() {
  try {
    const info = await api("/api/audio/cache");
    if (!info.file_count) {
      alert("当前本地语音缓存已是空的（0 MB）。");
      return;
    }
    if (
      !confirm(
        `确定清理本地 ${info.file_count} 个语音缓存文件（共 ${info.total_size_mb} MB）吗？\n清理后再次播放将自动按需重新生成。`,
      )
    ) {
      return;
    }
    const res = await api("/api/audio/cache/clear", { method: "POST" });
    alert(
      `✓ 已清理 ${res.cleared_count || 0} 个缓存音频，释放 ${res.freed_mb || 0} MB 磁盘空间！`,
    );
    updateAudioCacheInfo();
  } catch {
    alert("清理语音缓存失败");
  }
}

// 备份要带上 localStorage：字号、语音偏好、用户手绘上传的宠物 SVG 只存在这里，
// 而卸载 App 会连同数据库一起清空它。用前缀扫描而不是显式白名单——
// 白名单会让将来新增的偏好项静默漏出备份。
const BACKUP_LS_PREFIX = "delector_";
const BACKUP_LS_WORKBENCH_PREFIX = "wb.";
// 瞬态标记：既不导出也不清除，否则还原后会重复弹一次连胜庆祝。
const BACKUP_LS_TRANSIENT = new Set(["delector_streak_celebrated"]);

function backupLocalStorageKeys() {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k) continue;
    if (k.startsWith(BACKUP_LS_PREFIX) && !BACKUP_LS_TRANSIENT.has(k))
      keys.push(k);
    if (k.startsWith(BACKUP_LS_WORKBENCH_PREFIX)) keys.push(k);
  }
  return keys;
}

export async function downloadBackupJson() {
  try {
    // 两步走：POST 交出 localStorage 换一个一次性 token，再导航到 GET 下载。
    // 不能用 Blob + <a download>：Android WebView 的 DownloadListener 对 blob:
    // URL 永不触发，点击是静默无操作——连 catch 都进不去，用户以为导出成功了。
    const local_storage = {};
    backupLocalStorageKeys().forEach((k) => {
      local_storage[k] = localStorage.getItem(k);
    });
    const { token } = await api("/api/backup/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ local_storage }),
    });
    if (!token) throw new Error("备份服务未返回下载凭证");
    window.location.href = `/api/backup/download/${token}`;
  } catch (e) {
    alert("导出备份失败");
  }
}

export function uploadBackupJson(e) {
  const file = e.target.files?.[0];
  e.target.value = ""; // 先清空，否则重选同一个文件不会再触发 change
  if (!file) return;
  if (
    !confirm(
      "还原会清空当前全部文章、生词卡、语法卡、笔记与学习统计，用备份文件的内容整体替换。\n\n此操作不可撤销。确定继续吗？",
    )
  )
    return;
  const reader = new FileReader();
  reader.onload = async function (evt) {
    try {
      const payload = JSON.parse(evt.target.result);
      await api("/api/backup/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      // localStorage 也用真覆盖语义，和数据库侧保持一致：先清掉现有 delector_*
      // 再按备份重写。混用两套语义会造出「数据库回到备份时刻、界面偏好却是
      // 两个时刻的混合」这种没人能复现的状态。
      backupLocalStorageKeys().forEach((k) => {
        // workbench 进度是**累加**的，不是权威覆盖：用户可能在本设备上练了
        // 新的 wb.* 状态，然后才想起还原一份更早的 DeLector 备份。删除备份里
        // 没有的 wb.* 键会把这台设备上较新的学习进度静默抹掉，所以只清 delector_。
        if (k.startsWith(BACKUP_LS_PREFIX)) localStorage.removeItem(k);
      });
      Object.entries(payload.local_storage || {}).forEach(([k, v]) => {
        if (v === null) return;
        const isDelector =
          k.startsWith(BACKUP_LS_PREFIX) && !BACKUP_LS_TRANSIENT.has(k);
        const isWorkbench = k.startsWith(BACKUP_LS_WORKBENCH_PREFIX);
        if (isDelector || isWorkbench) localStorage.setItem(k, v);
      });
      alert("备份还原成功！页面即将重新加载以应用还原后的设置。");
      window.location.reload();
    } catch {
      alert("备份文件格式不正确或还原失败");
    }
  };
  reader.readAsText(file);
}

// ── Präpositionen-Matrix（卡盒第四段）─────────────────────────────────────────
// 整个 552 词 / 691 条的矩阵一次拉完（约 100 KB JSON），之后过滤与搜索全在本地。
// 为什么不做服务端分页/搜索：数据是静态词库，进程内已缓存，往返一次省下的带宽
// 换不回每次敲键都打一趟网络的手感。
let _prepMatrixCache = null; // {groups: [...]} —— 懒加载一次，会话内存活
let _prepLoading = null; // 正在飞的那次请求（并发点击共用，不重复发）
let _prepCaseFilter = ""; // '' | 'Dat' | 'Akk' | 'Gen'
let _prepSearchQuery = "";
let _prepSearchTimer = null;
// 本次会话已入卡的 lemma|praep|kasus。按钮的 disabled 状态活不过一次重渲染
// （过滤、搜索、切回本段都会整块重建 innerHTML），只靠它就等于「敲一下键
// 就能把已存的行变回可点」，于是同一条搭配能无声地重复入卡 ——
// /api/cards/vocab 是裸 INSERT，word 上也没有 UNIQUE，重复不会被拦。
const _prepSavedKeys = new Set();

function _prepKey(lemma, praep, kasus) {
  return `${lemma}|${praep}|${kasus}`;
}

export async function loadPrepMatrix() {
  if (_prepMatrixCache) return _prepMatrixCache;
  if (_prepLoading) return _prepLoading; // 并发进入只发一次
  _prepLoading = (async () => {
    try {
      const data = await api("/api/prep/matrix");
      _prepMatrixCache = data;
      // 从服务端加载已入卡状态，替代空 Set
      try {
        const savedData = await api("/api/prep/saved");
        if (savedData && Array.isArray(savedData.keys)) {
          _prepSavedKeys.clear();
          savedData.keys.forEach((k) => _prepSavedKeys.add(k));
        }
      } catch {
        /* 首次访问无数据，忽略 */
      }
      const total = (data.groups || []).reduce((s, g) => s + g.total, 0);
      const badge = document.getElementById("seg-prep-count");
      if (badge) badge.textContent = total;
      return data;
    } catch {
      // 失败**不**落缓存：缓存一个空结构会把一次网络抖动变成整个会话的
      // 「词库尚未生成」，只有刷新页面才能恢复，而 APK 里 WebView 就是唯一
      // 客户端，恢复路径等于重启 App。重试风暴由 _prepLoading 挡住。
      return null;
    } finally {
      _prepLoading = null;
    }
  })();
  return _prepLoading;
}

export function filterPrepCase(kasus) {
  _prepCaseFilter = kasus;
  // 按 data-kasus 而不是按下标认高亮：下标写法在有人调整 HTML 里 pill 顺序时
  // 会静默高亮错的那颗，而这种错没有测试能抓到。
  document
    .querySelectorAll("#prep-filter-bar .folio-anchor-pill")
    .forEach((p) => {
      p.classList.toggle("active", (p.dataset.kasus || "") === kasus);
    });
  renderPrepMatrix();
}

export function searchPrepCollocations(q) {
  // 去抖 150ms：每次击键都要把命中集整块 innerHTML 重写一遍，而单字母查询
  // 才是常态（'e' 命中 639 / 691 行）。桌面上一次约 45ms，安卓 WebView 单线程
  // 慢 4–8 倍 → 每键 200–400ms 同步主线程工作，打一个长词就是九连击。
  clearTimeout(_prepSearchTimer);
  _prepSearchTimer = setTimeout(() => {
    _prepSearchQuery = q.trim().toLowerCase();
    renderPrepMatrix();
  }, 150);
}

function renderPrepMatrix() {
  // 段守卫：loadPrepMatrix().then(renderPrepMatrix) 没有取消机制，用户在 93KB
  // 响应落地前切走的话，691 行会渲进「今日到期」的容器里，而过滤栏已经隐藏，
  // 连筛都筛不掉。
  if (cardSegment !== "prep") return;
  const container = document.getElementById("cards-container");
  if (!container) return;
  const groups = (_prepMatrixCache && _prepMatrixCache.groups) || [];
  const q = _prepSearchQuery;

  const matched = groups
    .map((g) => {
      const cases = {};
      let total = 0;
      Object.entries(g.cases).forEach(([kasus, entries]) => {
        if (_prepCaseFilter && kasus !== _prepCaseFilter) return;
        // 子串匹配即可覆盖 552 词规模：搜 freuen 命中 freuen auf，
        // 搜 "sich freuen" 也命中（反身前缀在这里现拼），不必上德语分词。
        // 两侧都转小写：当前词库全是小写动词/形容词，可一旦将来进了名词搭配
        // （Angst vor），大写首字母会让搜索静默查不到——误杀比漏检更难发现。
        const hits = q
          ? entries.filter((e) => prepSearchKey(e).includes(q))
          : entries;
        if (!hits.length) return; // 空桶不建键，否则 header 会挂一个没有行的格徽标
        cases[kasus] = hits;
        total += hits.length;
      });
      return { ...g, cases, total };
    })
    .filter((g) => g.total > 0);

  if (!matched.length) {
    // 三种空态要说三句不同的话：拉取失败说网络（别把传输故障说成词库缺失，
    // 那会让人去查数据集）、有过滤条件说没命中、都没有才是词库真空。
    const failed = !_prepMatrixCache;
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">${failed ? "📡" : "🧭"}</div>
        <div style="font-family:var(--serif-heading);font-size:1.375rem;color:var(--ink);">
          ${failed ? "介词矩阵加载失败" : q || _prepCaseFilter ? "没有命中的搭配" : "介词搭配库尚未生成"}
        </div>
        ${
          failed
            ? `<button class="btn btn-ghost btn-sm" style="margin-top:1rem;"
                            onclick="window.retryPrepMatrix()">重试</button>`
            : ""
        }
      </div>`;
    return;
  }

  container.innerHTML = matched
    .map(
      (g) => `
    <section class="prep-group">
      <header class="prep-group-head">
        <span class="prep-group-name">${esc(g.praeposition)}</span>
        <span class="prep-group-total">${g.total} 条</span>
        ${Object.keys(g.cases)
          .map((k) => `<span class="prep-case-badge">${esc(k)}</span>`)
          .join("")}
      </header>
      ${Object.entries(g.cases)
        .map(([kasus, entries]) =>
          entries
            .map((e) => {
              const saved = _prepSavedKeys.has(
                _prepKey(e.lemma, g.praeposition, kasus),
              );
              return `
        <div class="prep-row">
          <span class="prep-row-head">
            ${e.reflexive ? '<i class="prep-refl">sich </i>' : ""}${esc(e.lemma)}<em class="prep-kasus">+${esc(kasus)}</em>
          </span>
          <span class="prep-row-def">${esc(prepPlainDef(e))} <span class="prep-cefr">${esc(e.cefr || "")}</span></span>
          <span class="prep-row-actions">
            <blockquote class="prep-example">${esc(e.beispiel)}</blockquote>
            <button class="btn btn-ghost btn-xs prep-save-btn${saved ? " saved" : ""}"
                    onclick="window.savePrepCardFromMatrix(this)"${saved ? " disabled" : ""}
                    data-word="${esc(e.lemma)}" data-praep="${esc(g.praeposition)}"
                    data-kasus="${esc(kasus)}" data-refl="${e.reflexive ? 1 : 0}"
                    data-zh="${esc(prepPlainDef(e))}" data-cefr="${esc(e.cefr || "")}"
                    data-beispiel="${esc(e.beispiel)}">${saved ? "✓ 已存" : "+ 卡"}</button>
          </span>
        </div>`;
            })
            .join(""),
        )
        .join("")}
    </section>`,
    )
    .join("");
}

/** 搜索用的归一化词头：反身条目连 "sich " 一起进 haystack，这样中德两种
 *  查法（freuen / sich freuen）都命中。 */
function prepSearchKey(e) {
  return `${e.reflexive ? "sich " : ""}${e.lemma}`.toLowerCase();
}

/** 去掉中文义里的 (sich) 反身标记。矩阵已经把 sich 显式渲染在词头上了，
 *  再让释义尾巴上挂一个 (sich) 是重复噪音（抽屉里没有词头前缀，所以保留）。 */
function prepPlainDef(e) {
  return (e.bedeutung_zh || "").replace("(sich)", "").trim();
}

export async function savePrepCardFromMatrix(btn) {
  const lemma = btn.dataset.word,
    praep = btn.dataset.praep,
    kasus = btn.dataset.kasus;
  const refl = btn.dataset.refl === "1";
  const zh = btn.dataset.zh,
    cefr = btn.dataset.cefr,
    beispiel = btn.dataset.beispiel;
  // 与 reader.js savePrepCollocation 相同的 payload 构造。重复而非抽象：
  // reader 的构造依赖 state.selectedToken 上下文，矩阵的依赖 dataset，
  // 强行统一要发明第三个适配层。
  // 卡面是搭配本身（sich freuen auf），格只进释义后缀 (+Akk)——
  // 把格拼进卡面会得到 "freuen Akk" 这种德语里不存在的形态。
  const head = `${refl ? "sich " : ""}${lemma} ${praep}`;
  const def = `${zh} (+${kasus})`;
  btn.disabled = true;
  try {
    await api("/api/cards/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // article_id 为空：矩阵是脱离文章的词库视图，没有来源文章可挂。
        // pos 只能留空：prep_dict.py 没有词性列，所以同一条搭配从抽屉入卡
        // 显示 "freuen · VERB"、从矩阵入卡显示 "freuen · WORT"（cards.js:189
        // 的 `card.pos || 'WORT'` 兜底）。已知的外观差异，不值得为它现造词性。
        article_id: null,
        word: head,
        lemma: lemma,
        pos: "",
        gender: "",
        cefr_level: cefr || "B1",
        definition_zh: def,
        sentence_context: beispiel || "",
      }),
    });
    _prepSavedKeys.add(_prepKey(lemma, praep, kasus));
    // 异步写入服务端，不阻塞 UI
    api("/api/prep/saved", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lemma, praep, kasus }),
    }).catch(() => {});
    btn.textContent = "✓ 已存";
    btn.classList.add("saved");
    refreshCardCounters();
    Companion.celebrate("card_vocab");
  } catch {
    btn.disabled = false;
    alert("保存搭配卡失败");
  }
}

/** 空态里那颗「重试」按钮：清掉失败态重新拉一次。 */
export async function retryPrepMatrix() {
  await loadPrepMatrix();
  renderPrepMatrix();
}

// ── Goethe-Zertifikat A1 Wortliste & Sprechen Lab ────────────────────────────

export async function loadA1Data() {
  try {
    const [topics, vocab, teil2, teil3] = await Promise.all([
      api('/api/a1/topics'),
      api('/api/a1/vocab'),
      api('/api/a1/sprechen/teil2'),
      api('/api/a1/sprechen/teil3'),
    ]);
    a1TopicsCache = topics || [];
    a1VocabCache = vocab || [];
    a1Teil2Cache = teil2 || [];
    a1Teil3Cache = teil3 || [];

    _a1SavedLemmas = new Set(
      (cachedCards.vocab_cards || []).map(c => (c.lemma || c.word || '').toLowerCase())
    );

    renderA1TopicPills();
  } catch (e) {
    console.error('Failed to load A1 data', e);
  }
}

export function renderA1TopicPills() {
  const container = document.getElementById('a1-topic-pills');
  if (!container || !a1TopicsCache) return;

  const totalCount = a1VocabCache.length || 702;
  let html = `
    <button class="a1-pill ${a1CurrentTopic === '' ? 'active' : ''}" onclick="filterA1Topic('')">
      🌟 全部主题 <span class="a1-pill-count">${totalCount}</span>
    </button>
  `;

  for (const t of a1TopicsCache) {
    const isActive = a1CurrentTopic === t.key ? 'active' : '';
    html += `
      <button class="a1-pill ${isActive}" onclick="filterA1Topic(${jsAttr(t.key)})" title="${esc(t.keywords)}">
        ${esc(t.label)} <span class="a1-pill-count">${t.count}</span>
      </button>
    `;
  }
  container.innerHTML = html;
}

export function setA1Mode(mode) {
  a1Mode = mode;
  a1CardIndex = 0;
  a1CardFlipped = false;

  ['vocab', 'teil2', 'teil3'].forEach(m => {
    const btn = document.getElementById(`a1-tab-${m}`);
    if (btn) btn.classList.toggle('active', m === mode);
  });

  const searchRow = document.getElementById('a1-search-row');
  const pillsRow = document.getElementById('a1-topic-pills');
  const viewToggle = document.querySelector('.cards-view-toggle');

  if (mode === 'vocab') {
    searchRow?.classList.remove('hidden');
    pillsRow?.classList.remove('hidden');
    viewToggle?.classList.remove('hidden');
  } else if (mode === 'teil2') {
    searchRow?.classList.add('hidden');
    pillsRow?.classList.remove('hidden');
    viewToggle?.classList.add('hidden');
  } else {
    searchRow?.classList.add('hidden');
    pillsRow?.classList.add('hidden');
    viewToggle?.classList.add('hidden');
  }

  renderA1();
}

export function filterA1Topic(topicKey) {
  a1CurrentTopic = topicKey;
  a1CardIndex = 0;
  a1CardFlipped = false;
  renderA1TopicPills();
  renderA1();
}

export function searchA1Vocab(q) {
  a1SearchQuery = (q || '').trim().toLowerCase();
  a1CardIndex = 0;
  a1CardFlipped = false;
  renderA1();
}

export function flipA1Card() {
  a1CardFlipped = !a1CardFlipped;
  const card = document.getElementById('a1-active-card');
  if (card) {
    card.classList.toggle('is-flipped', a1CardFlipped);
  }
}

export function stepA1Card(delta) {
  let list = getA1CurrentList();
  if (!list.length) return;
  a1CardIndex = (a1CardIndex + delta + list.length) % list.length;
  a1CardFlipped = false;
  renderA1();
}

export function randomA1Card() {
  let list = getA1CurrentList();
  if (list.length <= 1) return;
  let nextIdx = Math.floor(Math.random() * list.length);
  if (nextIdx === a1CardIndex) nextIdx = (nextIdx + 1) % list.length;
  a1CardIndex = nextIdx;
  a1CardFlipped = false;
  renderA1();
}

function getA1CurrentList() {
  if (a1Mode === 'vocab') {
    let list = a1VocabCache || [];
    if (a1CurrentTopic) list = list.filter(w => w.topic === a1CurrentTopic);
    if (a1SearchQuery) {
      list = list.filter(w =>
        (w.word || '').toLowerCase().includes(a1SearchQuery) ||
        (w.lemma || '').toLowerCase().includes(a1SearchQuery) ||
        (w.definition_zh || '').toLowerCase().includes(a1SearchQuery)
      );
    }
    return list;
  } else if (a1Mode === 'teil2') {
    let list = a1Teil2Cache || [];
    if (a1CurrentTopic) list = list.filter(c => c.topic_id === a1CurrentTopic);
    return list;
  } else {
    return a1Teil3Cache || [];
  }
}

export function renderA1() {
  const container = document.getElementById('cards-container');
  if (!container) return;

  if (a1Mode === 'vocab') {
    if (cardViewMode === 'deck') {
      renderA1PokerCard();
    } else {
      renderA1GridView();
    }
  } else if (a1Mode === 'teil2') {
    renderA1Teil2Deck();
  } else {
    renderA1Teil3Deck();
  }
}

export function renderA1PokerCard() {
  const container = document.getElementById('cards-container');
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) {
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">🔍</div>
        <div style="font-family:var(--serif-heading);font-size:1.25rem;color:var(--ink);">未找到匹配的 A1 考纲词汇</div>
        <p style="color:var(--ink-mute);font-size:0.875rem;margin-top:0.5rem;">尝试清空搜索框或切换主题分类</p>
      </div>
    `;
    return;
  }

  const cur = list[a1CardIndex % list.length];
  const total = list.length;
  const isSaved = _a1SavedLemmas.has((cur.lemma || cur.word || '').toLowerCase());

  let genderCls = 'gender-other';
  let genderTag = '';
  if (cur.gender === 'Masc') {
    genderCls = 'a1-card-gender-m';
    genderTag = '<span class="gender-pill der">der · 阳性</span>';
  } else if (cur.gender === 'Fem') {
    genderCls = 'a1-card-gender-f';
    genderTag = '<span class="gender-pill die">die · 阴性</span>';
  } else if (cur.gender === 'Neut') {
    genderCls = 'a1-card-gender-n';
    genderTag = '<span class="gender-pill das">das · 中性</span>';
  } else if (cur.gender === 'Plur') {
    genderCls = 'a1-card-gender-f';
    genderTag = '<span class="gender-pill die">die · 复数</span>';
  }

  container.innerHTML = `
    <div class="deck-stage" id="deck-stage">
      <div class="deck-meta-bar">
        <span>🌟 歌德 A1 官方考纲词卡 · POKER FLIP</span>
        <span class="deck-counter-badge">WORT ${a1CardIndex + 1} / ${total}</span>
      </div>

      <div class="deck-stack-wrap">
        ${total > 2 ? '<div class="deck-card-layer deck-card-layer-3"></div>' : ''}
        ${total > 1 ? '<div class="deck-card-layer deck-card-layer-2"></div>' : ''}

        <div class="deck-active-card ${genderCls} ${a1CardFlipped ? 'is-flipped' : ''}" id="a1-active-card">
          <!-- 正面 FRONT -->
          <div class="deck-card-face card-front" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div>
                <div class="deck-word-title">${esc(cur.word)}</div>
                <div class="deck-meta-lemma">
                  ${esc(cur.lemma)} · ${esc(cur.pos || 'WORT')} ${cur.plural ? '· Pl: ' + esc(cur.plural) : ''}
                </div>
              </div>
              <div class="card-top-actions">
                <button class="speaker-btn" style="font-size:1.125rem;" onclick="event.stopPropagation();playGermanAudio(${jsAttr(cur.word)})" title="朗读德语">🔊</button>
                <span class="cefr-badge badge-A1">Goethe A1</span>
              </div>
            </div>

            <div class="deck-front-center">
              <div style="margin-bottom:0.75rem;">${genderTag}</div>
              <div class="deck-flip-guide">
                <div class="deck-flip-icon">🔀</div>
                <div class="deck-flip-prompt">点击卡片 或 按空格 3D 翻转查看释义与考纲例句</div>
              </div>
            </div>

            <div class="deck-card-foot" style="justify-content:flex-end;" onclick="event.stopPropagation()">
              <button class="btn ${isSaved ? 'btn-ghost saved' : 'btn-accent'} btn-xs"
                      onclick="saveA1WordToDeck(${jsAttr(cur.lemma)}, ${jsAttr(cur.word)}, ${jsAttr(cur.pos || '')}, ${jsAttr(cur.gender || '')}, ${jsAttr(cur.plural || '')}, ${jsAttr(cur.definition_zh || '')}, ${jsAttr(cur.example_de || '')}, ${jsAttr(cur.example_zh || '')}, this)">
                ${isSaved ? '✓ 已在复习盒' : '+ 加入 FSRS 盒'}
              </button>
            </div>
          </div>

          <!-- 背面 BACK -->
          <div class="deck-card-face card-back" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="deck-back-lemma">${esc(cur.word)}</div>
              <div class="card-top-actions">
                <button class="speaker-btn" style="font-size:1.125rem;" onclick="event.stopPropagation();playGermanAudio(${jsAttr(cur.example_de)})" title="朗读官方例句">🔊</button>
                <span class="cefr-badge badge-A1">Goethe A1</span>
              </div>
            </div>

            <div class="deck-back-body">
              <div class="deck-def-block">
                <div class="deck-def-label">CHINESISCHE BEDEUTUNG · 中文释义</div>
                <div class="deck-def-text">${esc(cur.definition_zh)}</div>
              </div>

              <div class="deck-example-block" style="margin-top:0.75rem;">
                <div class="deck-def-label">GOETHE A1 STANDARD-BEISPIEL · 官方考纲例句</div>
                <div class="deck-example-de" style="font-size:0.95rem;font-weight:500;color:var(--ink);">${esc(cur.example_de)}</div>
                <div class="deck-example-zh" style="font-size:0.85rem;color:var(--ink-mute);margin-top:0.25rem;">${esc(cur.example_zh)}</div>
              </div>
            </div>

            <div class="deck-card-foot" style="justify-content:space-between;" onclick="event.stopPropagation()">
              <button class="btn btn-ghost btn-xs" onclick="flipA1Card()">↩ 返回正面</button>
              <button class="btn ${isSaved ? 'btn-ghost saved' : 'btn-accent'} btn-xs"
                      onclick="saveA1WordToDeck(${jsAttr(cur.lemma)}, ${jsAttr(cur.word)}, ${jsAttr(cur.pos || '')}, ${jsAttr(cur.gender || '')}, ${jsAttr(cur.plural || '')}, ${jsAttr(cur.definition_zh || '')}, ${jsAttr(cur.example_de || '')}, ${jsAttr(cur.example_zh || '')}, this)">
                ${isSaved ? '✓ 已在复习盒' : '+ 加入 FSRS 盒'}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="deck-controls-bottom">
        <button class="deck-nav-btn" onclick="stepA1Card(-1)" title="上一张 (← / A)">◀ 上一张</button>
        <button class="deck-nav-btn deck-btn-flip" onclick="flipA1Card()" title="翻转卡片 (Space)">🔀 翻转</button>
        <button class="deck-nav-btn" onclick="randomA1Card()" title="随机抽词">🎲 随机</button>
        <button class="deck-nav-btn" onclick="stepA1Card(1)" title="下一张 (→ / D)">下一张 ▶</button>
      </div>
    </div>
  `;
}

function renderA1GridView() {
  const container = document.getElementById('cards-container');
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) {
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">🔍</div>
        <div style="font-family:var(--serif-heading);font-size:1.25rem;color:var(--ink);">未找到匹配的 A1 考纲词汇</div>
      </div>
    `;
    return;
  }

  let cardsHtml = '';
  for (const w of list) {
    const isSaved = _a1SavedLemmas.has((w.lemma || w.word || '').toLowerCase());
    let genderStrip = '';
    if (w.gender === 'Masc') genderStrip = 'gender-masc-strip';
    else if (w.gender === 'Fem') genderStrip = 'gender-fem-strip';
    else if (w.gender === 'Neut') genderStrip = 'gender-neut-strip';

    cardsHtml += `
      <div class="card-item card-vocab a1-grid-card ${genderStrip}">
        <div class="card-head">
          <div class="card-title">${esc(w.word)}</div>
          <div class="card-meta">
            <button class="speaker-btn" onclick="playGermanAudio(${jsAttr(w.word)})" title="朗读">🔊</button>
            <span class="cefr-badge badge-A1">A1</span>
          </div>
        </div>
        <div class="card-lemma-row">${esc(w.lemma)} · ${esc(w.pos || '')} ${w.plural ? '· Pl: ' + esc(w.plural) : ''}</div>
        <div class="card-def">${esc(w.definition_zh)}</div>
        <div class="card-context" style="margin-top:0.5rem;font-size:0.85rem;">
          <div style="color:var(--ink);">${esc(w.example_de)}</div>
          <div style="color:var(--ink-mute);font-size:0.775rem;">${esc(w.example_zh)}</div>
        </div>
        <div class="card-actions" style="margin-top:0.75rem;justify-content:flex-end;">
          <button class="btn ${isSaved ? 'btn-ghost saved' : 'btn-accent'} btn-xs"
                  onclick="saveA1WordToDeck(${jsAttr(w.lemma)}, ${jsAttr(w.word)}, ${jsAttr(w.pos || '')}, ${jsAttr(w.gender || '')}, ${jsAttr(w.plural || '')}, ${jsAttr(w.definition_zh || '')}, ${jsAttr(w.example_de || '')}, ${jsAttr(w.example_zh || '')}, this)">
            ${isSaved ? '✓ 已在复习盒' : '+ 加入 FSRS 盒'}
          </button>
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="cards-grid-summary" style="margin: 0.75rem 0; font-size:0.875rem; color:var(--ink-mute);">
      共筛选出 <b>${list.length}</b> 个歌德 A1 官方考纲词汇
    </div>
    <div class="cards-grid">${cardsHtml}</div>
  `;
}

function renderA1Teil2Deck() {
  const container = document.getElementById('cards-container');
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) return;

  const cur = list[a1CardIndex % list.length];
  const total = list.length;

  let promptsHtml = '';
  for (const p of (cur.prompts || [])) {
    promptsHtml += `
      <div class="a1-prompt-box">
        <div class="a1-prompt-badge ${p.type === 'W-Frage' ? 'badge-w' : 'badge-jn'}">${esc(p.type)}</div>
        <div class="a1-prompt-q">
          <button class="speaker-btn" onclick="event.stopPropagation();playGermanAudio(${jsAttr(p.q)})" title="朗读提问">🔊</button>
          <b>问：</b>${esc(p.q)}
        </div>
        <div class="a1-prompt-a">
          <button class="speaker-btn" onclick="event.stopPropagation();playGermanAudio(${jsAttr(p.a)})" title="朗读回答">🔊</button>
          <b>答：</b>${esc(p.a)}
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="deck-stage" id="deck-stage">
      <div class="deck-meta-bar">
        <span>💬 歌德 A1 口语 Teil 2 · 主题抽词对练卡</span>
        <span class="deck-counter-badge">THEMA-KARTE ${a1CardIndex + 1} / ${total}</span>
      </div>

      <div class="deck-stack-wrap">
        <div class="deck-active-card a1-sprechen-card ${a1CardFlipped ? 'is-flipped' : ''}" id="a1-active-card">
          <!-- 正面 FRONT (考场抽题卡) -->
          <div class="deck-card-face card-front" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="a1-thema-title">Thema: ${esc(cur.topic_id.toUpperCase())}</div>
              <span class="cefr-badge badge-A1">Teil 2</span>
            </div>

            <div class="deck-front-center">
              <div class="a1-exam-keyword-badge">${esc(cur.keyword)}</div>
              <div class="a1-exam-task-prompt">
                考场任务：根据主题 <b>${esc(cur.topic_id)}</b> 与关键词 <b>${esc(cur.keyword)}</b> 向考官/搭档提问并应答。
              </div>
              <div class="deck-flip-guide" style="margin-top:1.5rem;">
                <div class="deck-flip-icon">🔀</div>
                <div class="deck-flip-prompt">先在心中构思提问，点击卡片翻转核对标准 W-Frage / Ja-Nein 问答</div>
              </div>
            </div>
          </div>

          <!-- 背面 BACK (标准问答参考) -->
          <div class="deck-card-face card-back" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="deck-back-lemma">关键词: ${esc(cur.keyword)} · 标准问答</div>
              <span class="cefr-badge badge-A1">Goethe Muster</span>
            </div>

            <div class="deck-back-body" style="padding:1rem 0;">
              ${promptsHtml}
            </div>

            <div class="deck-card-foot" style="justify-content:space-between;" onclick="event.stopPropagation()">
              <button class="btn btn-ghost btn-xs" onclick="flipA1Card()">↩ 返回题目</button>
            </div>
          </div>
        </div>
      </div>

      <div class="deck-controls-bottom">
        <button class="deck-nav-btn" onclick="stepA1Card(-1)">◀ 上一张</button>
        <button class="deck-nav-btn deck-btn-flip" onclick="flipA1Card()">🔀 翻转</button>
        <button class="deck-nav-btn" onclick="randomA1Card()">🎲 随机抽题</button>
        <button class="deck-nav-btn" onclick="stepA1Card(1)">下一张 ▶</button>
      </div>
    </div>
  `;
}

function renderA1Teil3Deck() {
  const container = document.getElementById('cards-container');
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) return;

  const cur = list[a1CardIndex % list.length];
  const total = list.length;

  let reqsHtml = '';
  for (const r of (cur.requests || [])) {
    reqsHtml += `
      <div class="a1-prompt-box">
        <div class="a1-prompt-badge badge-w">${esc(r.style || 'Bitte')}</div>
        <div class="a1-prompt-q">
          <button class="speaker-btn" onclick="event.stopPropagation();playGermanAudio(${jsAttr(r.utterance)})" title="朗读请求">🔊</button>
          <b>提出请求：</b>${esc(r.utterance)}
        </div>
        <div class="a1-prompt-a">
          <button class="speaker-btn" onclick="event.stopPropagation();playGermanAudio(${jsAttr(r.response)})" title="朗读回应">🔊</button>
          <b>礼貌应答：</b>${esc(r.response)}
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="deck-stage" id="deck-stage">
      <div class="deck-meta-bar">
        <span>🙋 歌德 A1 口语 Teil 3 · 考场情景与物品请求卡</span>
        <span class="deck-counter-badge">SITUATION ${a1CardIndex + 1} / ${total}</span>
      </div>

      <div class="deck-stack-wrap">
        <div class="deck-active-card a1-sprechen-card ${a1CardFlipped ? 'is-flipped' : ''}" id="a1-active-card">
          <!-- 正面 FRONT (物品图标与情景) -->
          <div class="deck-card-face card-front" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="a1-thema-title">情景物品：${esc(cur.keyword)}</div>
              <span class="cefr-badge badge-A1">Teil 3</span>
            </div>

            <div class="deck-front-center">
              <div class="a1-situation-icon">${cur.icon}</div>
              <div class="a1-situation-desc">${esc(cur.situation)}</div>
              <div class="deck-flip-guide" style="margin-top:1.5rem;">
                <div class="deck-flip-icon">🔀</div>
                <div class="deck-flip-prompt">用祈使句 (Imperativ mit Sie) 或礼貌句 (Können Sie bitte...) 提出请求</div>
              </div>
            </div>
          </div>

          <!-- 背面 BACK (满分请求与应答) -->
          <div class="deck-card-face card-back" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="deck-back-lemma">${cur.icon} ${esc(cur.keyword)} · 满分请求与应答</div>
              <span class="cefr-badge badge-A1">Goethe Muster</span>
            </div>

            <div class="deck-back-body" style="padding:1rem 0;">
              ${reqsHtml}
            </div>

            <div class="deck-card-foot" style="justify-content:space-between;" onclick="event.stopPropagation()">
              <button class="btn btn-ghost btn-xs" onclick="flipA1Card()">↩ 返回情景</button>
            </div>
          </div>
        </div>
      </div>

      <div class="deck-controls-bottom">
        <button class="deck-nav-btn" onclick="stepA1Card(-1)">◀ 上一张</button>
        <button class="deck-nav-btn deck-btn-flip" onclick="flipA1Card()">🔀 翻转</button>
        <button class="deck-nav-btn" onclick="randomA1Card()">🎲 随机情景</button>
        <button class="deck-nav-btn" onclick="stepA1Card(1)">下一张 ▶</button>
      </div>
    </div>
  `;
}

export async function saveA1WordToDeck(lemma, word, pos, gender, plural, defn, exampleDe, exampleZh, btn) {
  if (btn) btn.disabled = true;
  try {
    await api('/api/cards/vocab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article_id: null,
        word: word || lemma,
        lemma: lemma,
        pos: pos || 'WORT',
        gender: gender || '',
        plural: plural || '',
        cefr_level: 'A1',
        definition_zh: defn || '',
        sentence_context: exampleDe || '',
      }),
    });
    _a1SavedLemmas.add((lemma || word).toLowerCase());
    if (btn) {
      btn.textContent = '✓ 已在复习盒';
      btn.classList.add('saved');
    }
    refreshCardCounters();
    Companion.celebrate('card_vocab');
  } catch (e) {
    if (btn) btn.disabled = false;
    alert('保存词汇卡失败');
  }
}

export const saveA1VocabCard = saveA1WordToDeck;
export const playA1Audio = playGermanAudio;

