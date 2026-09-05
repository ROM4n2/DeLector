/* DeLector - Goethe-Zertifikat A1 Wortliste & Sprechen Module */
"use strict";

import { state, api, esc, jsAttr } from "./core.js";
import { playGermanAudio } from "./player.js";
import { refreshCardCounters } from "./reader.js";
import { Companion } from "./companion.js";
import { getCachedVocabLemmas } from "./cards.js";
import { initA1Hoeren, stopHoerenExam } from "./a1_hoeren.js";
import { initA1Lesen, stopLesenExam } from "./a1_lesen.js";

// ── Goethe A1 Wortliste & Sprechen State ─────────────────────────────────────
export let a1Mode = "vocab"; // 'vocab' | 'teil2' | 'teil3' | 'hoeren' | 'lesen'
export let a1CurrentTopic = "";
export let a1SearchQuery = "";
export let a1TopicsCache = null;
export let a1VocabCache = [];
export let a1Teil2Cache = [];
export let a1Teil3Cache = [];
export let a1CardIndex = 0;
export let a1CardFlipped = false;
export let _a1SavedLemmas = new Set();
export let _examVocabLevel = "A1";
export let _a2VocabCache = null;
let _a2VocabLoadingPromise = null;

export async function setExamVocabLevel(level) {
  _examVocabLevel = (level || "A1").toUpperCase();
  a1CardIndex = 0;
  a1CardFlipped = false;
  if (_examVocabLevel === "A2") {
    if (!_a2VocabCache) {
      if (!_a2VocabLoadingPromise) {
        _a2VocabLoadingPromise = api("/api/a2/vocab")
          .then((res) => {
            _a2VocabCache = res || [];
            _a2VocabLoadingPromise = null;
            return _a2VocabCache;
          })
          .catch((e) => {
            console.error("Failed to load A2 vocab", e);
            _a2VocabCache = [];
            _a2VocabLoadingPromise = null;
            return [];
          });
      }
      await _a2VocabLoadingPromise;
    }
    renderA1TopicPills();
    renderA1();
  } else {
    renderA1TopicPills();
    renderA1();
  }
}

export function getA1Mode() {
  return a1Mode;
}
export function isA1DataLoaded() {
  return !!(a1VocabCache.length && a1TopicsCache);
}

// ── Goethe-Zertifikat A1 Wortliste & Sprechen Lab ────────────────────────────
// ADR-0005 Task 2：A1 词表/口语面板宿主已迁到 view-exam，渲染目标统一为
// 备考域容器 #exam-cards-container（主站 #cards-container 只归复习卡盒）。
const a1CardsHost = () => document.getElementById("exam-cards-container");

// 牌盒/目录视图模式。主站 cards.js 的同款状态对 A1 不再生效（两个视图
// 各自独立），本模块自管一份，toggle 按钮也在备考域容器内
// （#exam-cards-view-toggle 里的 exam-mode-btn-*）。cards.js 的
// getCardViewMode 桩仍在（探针 vm 注入 & 潜在旧调用兜底），但本模块
// 的判定只看自己的 a1ViewMode。
let a1ViewMode = "deck";

export function setA1CardViewMode(mode) {
  a1ViewMode = mode;
  document
    .getElementById("exam-mode-btn-deck")
    ?.classList.toggle("active", mode === "deck");
  document
    .getElementById("exam-mode-btn-grid")
    ?.classList.toggle("active", mode === "grid");
  renderA1();
}

export async function loadA1Data() {
  try {
    const [topics, vocab, teil2, teil3] = await Promise.all([
      api("/api/a1/topics"),
      api("/api/a1/vocab"),
      api("/api/a1/sprechen/teil2"),
      api("/api/a1/sprechen/teil3"),
    ]);
    a1TopicsCache = topics || [];
    a1VocabCache = vocab || [];
    a1Teil2Cache = teil2 || [];
    a1Teil3Cache = teil3 || [];

    _a1SavedLemmas = getCachedVocabLemmas();

    renderA1TopicPills();
  } catch (e) {
    console.error("Failed to load A1 data", e);
  }
}

export function renderA1TopicPills() {
  const container = document.getElementById("a1-topic-pills");
  if (!container) return;

  if (_examVocabLevel === "A2") {
    const totalCount = _a2VocabCache ? _a2VocabCache.length : 974;
    container.innerHTML = `
      <button class="a1-pill active" onclick="filterA1Topic('')">
        🌟 全部 A2 考纲词汇 <span class="a1-pill-count">${totalCount}</span>
      </button>
    `;
    return;
  }

  if (!a1TopicsCache) return;

  const totalCount = a1VocabCache.length || 702;
  let html = `
    <button class="a1-pill ${a1CurrentTopic === "" ? "active" : ""}" onclick="filterA1Topic('')">
      🌟 全部主题 <span class="a1-pill-count">${totalCount}</span>
    </button>
  `;

  for (const t of a1TopicsCache) {
    const isActive = a1CurrentTopic === t.key ? "active" : "";
    html += `
      <button class="a1-pill ${isActive}" onclick="filterA1Topic(${jsAttr(t.key)})" title="${esc(t.keywords)}">
        ${esc(t.label)} <span class="a1-pill-count">${t.count}</span>
      </button>
    `;
  }
  container.innerHTML = html;
}

export function setA1Mode(mode) {
  stopHoerenExam();
  stopLesenExam();
  a1Mode = mode;
  a1CardIndex = 0;
  a1CardFlipped = false;

  ["vocab", "teil2", "teil3", "hoeren", "lesen"].forEach((m) => {
    const btn = document.getElementById(`a1-tab-${m}`);
    if (btn) btn.classList.toggle("active", m === mode);
  });

  const searchRow = document.getElementById("a1-search-row");
  const pillsRow = document.getElementById("a1-topic-pills");
  const viewToggle = document.getElementById("exam-cards-view-toggle");
  const cardsContainer = a1CardsHost();
  const hoerenContainer = document.getElementById("a1-hoeren-container");
  const lesenContainer = document.getElementById("a1-lesen-container");

  if (mode === "hoeren") {
    searchRow?.classList.add("hidden");
    pillsRow?.classList.add("hidden");
    viewToggle?.classList.add("hidden");
    cardsContainer?.classList.add("hidden");
    lesenContainer?.classList.add("hidden");
    hoerenContainer?.classList.remove("hidden");
    initA1Hoeren();
    return;
  }

  if (mode === "lesen") {
    searchRow?.classList.add("hidden");
    pillsRow?.classList.add("hidden");
    viewToggle?.classList.add("hidden");
    cardsContainer?.classList.add("hidden");
    hoerenContainer?.classList.add("hidden");
    lesenContainer?.classList.remove("hidden");
    initA1Lesen();
    return;
  }

  // Vocab / Sprechen modes
  hoerenContainer?.classList.add("hidden");
  lesenContainer?.classList.add("hidden");
  cardsContainer?.classList.remove("hidden");

  if (mode === "vocab") {
    searchRow?.classList.remove("hidden");
    pillsRow?.classList.remove("hidden");
    viewToggle?.classList.remove("hidden");
  } else if (mode === "teil2") {
    searchRow?.classList.add("hidden");
    pillsRow?.classList.remove("hidden");
    viewToggle?.classList.add("hidden");
  } else {
    searchRow?.classList.add("hidden");
    pillsRow?.classList.add("hidden");
    viewToggle?.classList.add("hidden");
  }

  // 题库懒加载：原 cards.js 'a1' 段的「未加载先 fetch 再渲染」链路随分流段
  // 一起迁走。备考域入口 setExamModule → setA1Mode，这里补上同语义守卫，
  // 否则首次进入 vocab/口语会拿空缓存渲染成「未找到考纲词汇」空态。
  if (mode === "vocab" && _examVocabLevel === "A2") {
    if (!_a2VocabCache) {
      setExamVocabLevel("A2").catch(() => {});
      return;
    }
    renderA1TopicPills();
    renderA1();
    return;
  }

  if (!isA1DataLoaded()) {
    loadA1Data()
      .then(() => {
        // 守卫：等待期间用户可能已切到 hoeren/lesen（它们不走本渲染路径）。
        if (a1Mode === "vocab" || a1Mode === "teil2" || a1Mode === "teil3")
          renderA1();
      })
      .catch(() => {});
    return;
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
  a1SearchQuery = (q || "").trim().toLowerCase();
  a1CardIndex = 0;
  a1CardFlipped = false;
  renderA1();
}

export function flipA1Card() {
  a1CardFlipped = !a1CardFlipped;
  const card = document.getElementById("a1-active-card");
  if (card) {
    card.classList.toggle("is-flipped", a1CardFlipped);
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

export function getA1CurrentList() {
  if (a1Mode === "vocab") {
    if (_examVocabLevel === "A2") {
      let list = _a2VocabCache || [];
      if (a1SearchQuery) {
        list = list.filter(
          (w) =>
            (w.word || "").toLowerCase().includes(a1SearchQuery) ||
            (w.lemma || "").toLowerCase().includes(a1SearchQuery) ||
            (w.definition_zh || "").toLowerCase().includes(a1SearchQuery),
        );
      }
      return list;
    }
    let list = a1VocabCache || [];
    if (a1CurrentTopic) list = list.filter((w) => w.topic === a1CurrentTopic);
    if (a1SearchQuery) {
      list = list.filter(
        (w) =>
          (w.word || "").toLowerCase().includes(a1SearchQuery) ||
          (w.lemma || "").toLowerCase().includes(a1SearchQuery) ||
          (w.definition_zh || "").toLowerCase().includes(a1SearchQuery),
      );
    }
    return list;
  } else if (a1Mode === "teil2") {
    let list = a1Teil2Cache || [];
    if (a1CurrentTopic)
      list = list.filter((c) => c.topic_id === a1CurrentTopic);
    return list;
  } else {
    return a1Teil3Cache || [];
  }
}

export function renderA1() {
  const container = a1CardsHost();
  if (!container) return;

  if (a1Mode === "vocab") {
    if (a1ViewMode === "deck") {
      renderA1PokerCard();
    } else {
      renderA1GridView();
    }
  } else if (a1Mode === "teil2") {
    renderA1Teil2Deck();
  } else {
    renderA1Teil3Deck();
  }
}

export function renderA1PokerCard() {
  const container = a1CardsHost();
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) {
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">🔍</div>
        <div style="font-family:var(--serif-heading);font-size:1.25rem;color:var(--ink);">未找到匹配的 ${_examVocabLevel || "A1"} 考纲词汇</div>
        <p style="color:var(--ink-mute);font-size:0.875rem;margin-top:0.5rem;">尝试清空搜索框或切换主题分类</p>
      </div>
    `;
    return;
  }

  const cur = list[a1CardIndex % list.length];
  const total = list.length;
  const isSaved = _a1SavedLemmas.has(
    (cur.lemma || cur.word || "").toLowerCase(),
  );

  let genderCls = "gender-other";
  let genderTag = "";
  if (cur.gender === "Masc") {
    genderCls = "a1-card-gender-m";
    genderTag = '<span class="gender-pill der">der · 阳性</span>';
  } else if (cur.gender === "Fem") {
    genderCls = "a1-card-gender-f";
    genderTag = '<span class="gender-pill die">die · 阴性</span>';
  } else if (cur.gender === "Neut") {
    genderCls = "a1-card-gender-n";
    genderTag = '<span class="gender-pill das">das · 中性</span>';
  } else if (cur.gender === "Plur") {
    genderCls = "a1-card-gender-f";
    genderTag = '<span class="gender-pill die">die · 复数</span>';
  }

  container.innerHTML = `
    <div class="deck-stage" id="deck-stage">
      <div class="deck-meta-bar">
        <span>🌟 歌德 ${_examVocabLevel || "A1"} 官方考纲词卡 · POKER FLIP</span>
        <span class="deck-counter-badge">WORT ${a1CardIndex + 1} / ${total}</span>
      </div>

      <div class="deck-stack-wrap">
        ${total > 2 ? '<div class="deck-card-layer deck-card-layer-3"></div>' : ""}
        ${total > 1 ? '<div class="deck-card-layer deck-card-layer-2"></div>' : ""}

        <div class="deck-active-card ${genderCls} ${a1CardFlipped ? "is-flipped" : ""}" id="a1-active-card">
          <!-- 正面 FRONT -->
          <div class="deck-card-face card-front" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div>
                <div class="deck-word-title">${esc(cur.word)}</div>
                <div class="deck-meta-lemma">
                  ${esc(cur.lemma)} · ${esc(cur.pos || "WORT")} ${cur.plural ? "· Pl: " + esc(cur.plural) : ""}
                </div>
              </div>
              <div class="card-top-actions">
                <button class="speaker-btn" style="font-size:1.125rem;" onclick="event.stopPropagation();playGermanAudio(${jsAttr(cur.word)})" title="朗读德语">🔊</button>
                <span class="cefr-badge badge-${_examVocabLevel || "A1"}">Goethe ${_examVocabLevel || "A1"}</span>
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
              <button class="btn ${isSaved ? "btn-ghost saved" : "btn-accent"} btn-xs"
                      onclick="saveA1WordToDeck(${jsAttr(cur.lemma)}, ${jsAttr(cur.word)}, ${jsAttr(cur.pos || "")}, ${jsAttr(cur.gender || "")}, ${jsAttr(cur.plural || "")}, ${jsAttr(cur.definition_zh || "")}, ${jsAttr(cur.example_de || "")}, ${jsAttr(cur.example_zh || "")}, this)">
                ${isSaved ? "✓ 已在复习盒" : "+ 加入 FSRS 盒"}
              </button>
            </div>
          </div>

          <!-- 背面 BACK -->
          <div class="deck-card-face card-back" onclick="flipA1Card()">
            <div class="deck-card-head">
              <div class="deck-back-lemma">${esc(cur.word)}</div>
              <div class="card-top-actions">
                <button class="speaker-btn" style="font-size:1.125rem;" onclick="event.stopPropagation();playGermanAudio(${jsAttr(cur.example_de)})" title="朗读官方例句">🔊</button>
                <span class="cefr-badge badge-${_examVocabLevel || "A1"}">Goethe ${_examVocabLevel || "A1"}</span>
              </div>
            </div>

            <div class="deck-back-body">
              <div class="deck-def-block">
                <div class="deck-def-label">CHINESISCHE BEDEUTUNG · 中文释义</div>
                <div class="deck-def-text">${esc(cur.definition_zh)}</div>
              </div>

              <div class="deck-example-block" style="margin-top:0.75rem;">
                <div class="deck-def-label">GOETHE ${_examVocabLevel || "A1"} STANDARD-BEISPIEL · 官方考纲例句</div>
                <div class="deck-example-de" style="font-size:0.95rem;font-weight:500;color:var(--ink);">${esc(cur.example_de)}</div>
                <div class="deck-example-zh" style="font-size:0.85rem;color:var(--ink-mute);margin-top:0.25rem;">${esc(cur.example_zh)}</div>
              </div>
            </div>

            <div class="deck-card-foot" style="justify-content:space-between;" onclick="event.stopPropagation()">
              <button class="btn btn-ghost btn-xs" onclick="flipA1Card()">↩ 返回正面</button>
              <button class="btn ${isSaved ? "btn-ghost saved" : "btn-accent"} btn-xs"
                      onclick="saveA1WordToDeck(${jsAttr(cur.lemma)}, ${jsAttr(cur.word)}, ${jsAttr(cur.pos || "")}, ${jsAttr(cur.gender || "")}, ${jsAttr(cur.plural || "")}, ${jsAttr(cur.definition_zh || "")}, ${jsAttr(cur.example_de || "")}, ${jsAttr(cur.example_zh || "")}, this)">
                ${isSaved ? "✓ 已在复习盒" : "+ 加入 FSRS 盒"}
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

export function renderA1GridView() {
  const container = a1CardsHost();
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) {
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;background:var(--paper-card);border:1.5px dashed var(--rule);margin-top:1rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">🔍</div>
        <div style="font-family:var(--serif-heading);font-size:1.25rem;color:var(--ink);">未找到匹配的 ${_examVocabLevel || "A1"} 考纲词汇</div>
      </div>
    `;
    return;
  }

  let cardsHtml = "";
  for (const w of list) {
    const isSaved = _a1SavedLemmas.has((w.lemma || w.word || "").toLowerCase());
    let genderStrip = "";
    if (w.gender === "Masc") genderStrip = "gender-masc-strip";
    else if (w.gender === "Fem") genderStrip = "gender-fem-strip";
    else if (w.gender === "Neut") genderStrip = "gender-neut-strip";

    cardsHtml += `
      <div class="card-item card-vocab a1-grid-card ${genderStrip}">
        <div class="card-head">
          <div class="card-title">${esc(w.word)}</div>
          <div class="card-meta">
            <button class="speaker-btn" onclick="playGermanAudio(${jsAttr(w.word)})" title="朗读">🔊</button>
            <span class="cefr-badge badge-${_examVocabLevel || "A1"}">${_examVocabLevel || "A1"}</span>
          </div>
        </div>
        <div class="card-lemma-row">${esc(w.lemma)} · ${esc(w.pos || "")} ${w.plural ? "· Pl: " + esc(w.plural) : ""}</div>
        <div class="card-def">${esc(w.definition_zh)}</div>
        <div class="card-context" style="margin-top:0.5rem;font-size:0.85rem;">
          <div style="color:var(--ink);">${esc(w.example_de)}</div>
          <div style="color:var(--ink-mute);font-size:0.775rem;">${esc(w.example_zh)}</div>
        </div>
        <div class="card-actions" style="margin-top:0.75rem;justify-content:flex-end;">
          <button class="btn ${isSaved ? "btn-ghost saved" : "btn-accent"} btn-xs"
                  onclick="saveA1WordToDeck(${jsAttr(w.lemma)}, ${jsAttr(w.word)}, ${jsAttr(w.pos || "")}, ${jsAttr(w.gender || "")}, ${jsAttr(w.plural || "")}, ${jsAttr(w.definition_zh || "")}, ${jsAttr(w.example_de || "")}, ${jsAttr(w.example_zh || "")}, this)">
            ${isSaved ? "✓ 已在复习盒" : "+ 加入 FSRS 盒"}
          </button>
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="cards-grid-summary" style="margin: 0.75rem 0; font-size:0.875rem; color:var(--ink-mute);">
      共筛选出 <b>${list.length}</b> 个歌德 ${_examVocabLevel || "A1"} 官方考纲词汇
    </div>
    <div class="cards-grid">${cardsHtml}</div>
  `;
}

export function renderA1Teil2Deck() {
  const container = a1CardsHost();
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) return;

  const cur = list[a1CardIndex % list.length];
  const total = list.length;

  let promptsHtml = "";
  for (const p of cur.prompts || []) {
    promptsHtml += `
      <div class="a1-prompt-box">
        <div class="a1-prompt-badge ${p.type === "W-Frage" ? "badge-w" : "badge-jn"}">${esc(p.type)}</div>
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
        <div class="deck-active-card a1-sprechen-card ${a1CardFlipped ? "is-flipped" : ""}" id="a1-active-card">
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

export function renderA1Teil3Deck() {
  const container = a1CardsHost();
  if (!container) return;

  const list = getA1CurrentList();
  if (!list.length) return;

  const cur = list[a1CardIndex % list.length];
  const total = list.length;

  let reqsHtml = "";
  for (const r of cur.requests || []) {
    reqsHtml += `
      <div class="a1-prompt-box">
        <div class="a1-prompt-badge badge-w">${esc(r.style || "Bitte")}</div>
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
        <div class="deck-active-card a1-sprechen-card ${a1CardFlipped ? "is-flipped" : ""}" id="a1-active-card">
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

export async function saveA1WordToDeck(
  lemma,
  word,
  pos,
  gender,
  plural,
  defn,
  exampleDe,
  exampleZh,
  btn,
) {
  if (btn) btn.disabled = true;
  try {
    await api("/api/cards/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: null,
        word: word || lemma,
        lemma: lemma,
        pos: pos || "WORT",
        gender: gender || "",
        plural: plural || "",
        cefr_level: _examVocabLevel || "A1",
        definition_zh: defn || "",
        sentence_context: exampleDe || "",
      }),
    });
    _a1SavedLemmas.add((lemma || word).toLowerCase());
    if (btn) {
      btn.textContent = "✓ 已在复习盒";
      btn.classList.add("saved");
    }
    refreshCardCounters();
    Companion.celebrate("card_vocab");
  } catch (e) {
    if (btn) btn.disabled = false;
    alert("保存词汇卡失败");
  }
}

export const saveA1VocabCard = saveA1WordToDeck;
export const playA1Audio = playGermanAudio;
