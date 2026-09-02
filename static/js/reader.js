/* DeLector - Reader View, Token Inspector & Sticky Notes */
"use strict";

import { state, esc, jsAttr, api, normalizeCefrPct } from "./core.js";
import { ShadowPlayer, playGermanAudio } from "./player.js";
import { Companion } from "./companion.js";

// ── XSS Sink-Side Defences ────────────────────────────────────────────────────
// crafted backup (/api/backup/restore 直灌 processed_json) 让 stats / tokens /
// clause_tree 可携带任意字符串；以下模板全部经 innerHTML 落 DOM。
// 数值位：模板期 Number() 收敛为 number literal（NaN 也安全——不会引号或尖括号），
// 比 jsAttr 更好：jsAttr 会把 number 变 string "5"，破坏 inspect() 里的 === 查找。
// CEFR 档位：白名单收敛（CSS class / 文本都由此拼出）。
// token_ids 数组：先收敛为纯数字 JSON（无双引号），再拼 onclick。
const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1"];
const safeCefr = (v) => (CEFR_LEVELS.includes(v) ? v : "A1");
const safeTokens = (ids) =>
  JSON.stringify((ids || []).map(Number).filter(Number.isFinite));

let currentArticleNotes = [];
let readerFontMode = localStorage.getItem("delector_font_mode") || "sans";
let readerFontSize =
  parseInt(localStorage.getItem("delector_font_size"), 10) || 18;

// ── Typography ───────────────────────────────────────────────────────────────
export function applyTypography() {
  const content = document.getElementById("reader-content");
  if (content) {
    if (readerFontMode === "serif") {
      content.classList.add("font-serif");
    } else {
      content.classList.remove("font-serif");
    }
    content.style.setProperty("--reader-fs", `${readerFontSize / 16}rem`);
  }

  const btnSans = document.getElementById("btn-font-sans");
  const btnSerif = document.getElementById("btn-font-serif");
  if (btnSans && btnSerif) {
    btnSans.classList.toggle("active", readerFontMode === "sans");
    btnSerif.classList.toggle("active", readerFontMode === "serif");
  }
}

export function setFontMode(mode) {
  readerFontMode = mode;
  localStorage.setItem("delector_font_mode", mode);
  applyTypography();
}

export function adjustFontSize(delta) {
  readerFontSize = Math.max(14, Math.min(24, readerFontSize + delta));
  localStorage.setItem("delector_font_size", readerFontSize);
  applyTypography();
}

// ── CEFR Focus Mode ─────────────────────────────────────────────────────────
export function toggleCefrFocus(level) {
  if (state.currentFocusedLevel === level) {
    clearCefrFocus();
    return;
  }

  state.currentFocusedLevel = level;
  document.body.classList.add("focus-mode");

  document.querySelectorAll(".heatbar-seg").forEach((el) => {
    el.classList.toggle("focused", el.classList.contains(level));
  });

  document.querySelectorAll(".tok").forEach((el) => {
    const matches = el.classList.contains(level);
    el.classList.toggle("focus-active", matches);
  });
}

export function clearCefrFocus() {
  state.currentFocusedLevel = null;
  document.body.classList.remove("focus-mode");
  document
    .querySelectorAll(".heatbar-seg")
    .forEach((el) => el.classList.remove("focused"));
  document
    .querySelectorAll(".tok")
    .forEach((el) => el.classList.remove("focus-active"));
}

// ── Heatbars ─────────────────────────────────────────────────────────────────
export function renderMiniBar(stats) {
  if (!stats || !stats.cefr_percentages) return "";
  const p = normalizeCefrPct(stats.cefr_percentages);
  const segs = ["A1", "A2", "B1", "B2", "C1"]
    .map((lvl) =>
      p[lvl] > 0
        ? `<div class="mini-seg ${lvl}" style="width:${p[lvl]}%" title="${lvl}: ${p[lvl]}%"></div>`
        : "",
    )
    .join("");

  const rec = safeCefr(stats.recommended_level);
  const recClass = rec.startsWith("B2") ? "mini-level-B2" : `mini-level-${rec}`;

  return `
    <div class="mini-bar-wrap">
      <span class="mini-level-badge ${recClass}">${rec} 推荐</span>
      <div class="mini-cefr-bar">${segs}</div>
      <span style="font-size:0.6875rem;color:var(--pencil);font-family:var(--mono);">约 ${Number(stats.est_reading_minutes) || 1} 分钟</span>
    </div>
  `;
}

export function renderReaderHeatbar(stats) {
  if (!stats || !stats.cefr_percentages) return;
  const p = normalizeCefrPct(stats.cefr_percentages);
  const counts = stats.cefr_counts || {};
  const segs = ["A1", "A2", "B1", "B2", "C1"]
    .map((lvl) => {
      if (!p[lvl] || p[lvl] <= 0) return "";
      const cnt = Number(counts[lvl]) || 0;
      return `<div class="heatbar-seg ${lvl}" style="width:${p[lvl]}%" onclick="toggleCefrFocus('${lvl}')" title="点击聚焦 ${lvl} 级别生词 (${cnt} 词)">${lvl} ${p[lvl]}%</div>`;
    })
    .join("");

  const heatEl = document.getElementById("reader-heatbar");
  if (heatEl) heatEl.innerHTML = segs;
  const timeEl = document.getElementById("heatbar-time");
  if (timeEl)
    timeEl.textContent = `预计精读 ${stats.est_reading_minutes || 1} 分钟 · 共 ${stats.word_count || 0} 词`;

  const rec = safeCefr(stats.recommended_level);
  const badge = document.getElementById("reader-meta-badge");
  if (badge) {
    badge.textContent = `${rec} 建议`;
    badge.className = `mini-level-badge mini-level-${rec.startsWith("B2") ? "B2" : rec}`;
  }
}

// ── Articles ─────────────────────────────────────────────────────────────────
export async function deleteArticle(id, title) {
  const name = title || "该文章";
  if (!confirm(`确定要删除《${name}》及其所有阅读笔记吗？此操作无法撤销。`)) {
    return;
  }
  try {
    await api("/api/articles/" + id, { method: "DELETE" });
    await loadArticles();
  } catch (err) {
    alert("删除文章失败: " + (err.message || err));
  }
}

export async function loadArticles() {
  const el = document.getElementById("article-list");
  if (!el) return;
  el.innerHTML = '<div class="empty-state">加载中…</div>';
  try {
    const data = await api("/api/articles");
    if (!data.length) {
      el.innerHTML =
        '<div class="empty-state">暂无文稿，点击上方按钮导入德语文章</div>';
      return;
    }
    el.innerHTML = data
      .map(
        (a) => `
      <div class="article-row" onclick="openReader(${Number(a.id)})">
        <div>
          <div class="article-row-title">${esc(a.title)}</div>
          <div class="article-row-meta">${esc(a.created_at)} · ${a.char_count} 字符</div>
          ${renderMiniBar(a.stats)}
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;flex-shrink:0;">
          <button class="article-row-del" onclick="event.stopPropagation(); deleteArticle(${Number(a.id)}, ${jsAttr(a.title)})" title="删除文章">🗑</button>
          <span class="article-row-arrow">→</span>
        </div>
      </div>`,
      )
      .join("");
  } catch (err) {
    el.innerHTML = '<div class="empty-state">文章列表加载失败</div>';
  }
}

export async function openReader(id) {
  state.currentArticle = await api("/api/articles/" + id);
  document.getElementById("reader-title").textContent =
    state.currentArticle.title;
  renderReaderHeatbar(state.currentArticle.stats);
  const content = document.getElementById("reader-content");

  let paraElements = [];
  let currentSentences = [];

  state.currentArticle.sentences.forEach((sent) => {
    let hasParaBreak = false;
    const sentTokens = sent.tokens
      .map((t) => {
        if (t.is_space) {
          if (t.text.includes("\n\n")) {
            hasParaBreak = true;
            return "";
          }
          if (t.text.includes("\n")) return "<br>";
          return " ";
        }
        if (t.is_punct) return `<span class="punct">${esc(t.text)}</span>`;
        const lvl = t.cefr_level || "A1";
        let sepPartnerId = null;
        if (t.separable) {
          sepPartnerId =
            "sep_prefix_id" in t.separable
              ? t.separable.sep_prefix_id
              : t.separable.sep_verb_id;
        }
        const sepAttr =
          sepPartnerId !== null && sepPartnerId !== undefined
            ? ` data-sep-partner="tok-${Number(sepPartnerId)}"`
            : "";
        const sepClass = t.separable ? " is-separable" : "";
        return `<span id="tok-${Number(t.id)}" class="tok ${lvl}${sepClass}"${sepAttr} onclick="inspect(${Number(t.id)},${Number(sent.id)})">${esc(t.text)}</span>`;
      })
      .join("");

    const topoHtml = renderFelderSpectrum(sent.topology, sent.id);
    const sentWrapper = `
      <span class="reader-sent-unit" id="sent-unit-${Number(sent.id)}" data-sent-id="${Number(sent.id)}">
        <span class="sent-text-wrap">${sentTokens}</span>
        <button class="sent-syntax-btn" onclick="event.stopPropagation(); toggleSentenceTopology(${Number(sent.id)})" title="展开德语拓扑五场域与从句树 (Satzbau)">🌳 句法</button>
      </span>
      <div id="sent-topology-${Number(sent.id)}" class="sentence-topology-strip hidden">${topoHtml}</div>
    `;

    currentSentences.push(sentWrapper);
    if (hasParaBreak) {
      paraElements.push(
        `<p class="reader-p">${currentSentences.join(" ")}</p>`,
      );
      currentSentences = [];
    }
  });

  if (currentSentences.length > 0) {
    paraElements.push(`<p class="reader-p">${currentSentences.join(" ")}</p>`);
  }

  content.innerHTML = paraElements.join("");

  ShadowPlayer.reset();
  applyTypography();
  await loadArticleNotes(id);

  // Setup separable verb hover linking
  content.querySelectorAll(".tok.is-separable").forEach((tokEl) => {
    const partnerId = tokEl.getAttribute("data-sep-partner");
    if (!partnerId) return;
    tokEl.addEventListener("mouseenter", () => {
      document.getElementById(partnerId)?.classList.add("linked-separable");
    });
    tokEl.addEventListener("mouseleave", () => {
      const isSel =
        tokEl.classList.contains("sel") ||
        document.querySelector(".tok.sel")?.getAttribute("data-sep-partner") ===
          tokEl.id;
      if (!isSel) {
        document
          .getElementById(partnerId)
          ?.classList.remove("linked-separable");
      }
    });
  });

  // Dispatch view change
  if (window.show) window.show("reader");
}

// ── Token Inspection ────────────────────────────────────────────────────────
export function inspect(tokenId, sentId) {
  document
    .querySelectorAll(".tok.sel")
    .forEach((el) => el.classList.remove("sel"));
  document
    .querySelectorAll(".tok.linked-separable")
    .forEach((el) => el.classList.remove("linked-separable"));

  const el = document.getElementById("tok-" + tokenId);
  if (el) el.classList.add("sel");

  const sent = state.currentArticle.sentences.find((s) => s.id === sentId);
  const token = sent.tokens.find((t) => t.id === tokenId);
  state.selectedToken = token;
  state.selectedSent = sent;
  state.grammarData = null;

  // Highlight separable partner and self if linked
  if (token.separable) {
    el?.classList.add("linked-separable");
    const partnerId =
      "sep_prefix_id" in token.separable
        ? token.separable.sep_prefix_id
        : token.separable.sep_verb_id;
    if (partnerId !== undefined && partnerId !== null) {
      document
        .getElementById("tok-" + partnerId)
        ?.classList.add("linked-separable");
    }
  }

  const sentIdx = state.currentArticle.sentences.findIndex(
    (s) => s.id === sentId,
  );
  if (sentIdx >= 0) {
    ShadowPlayer.seekSentence(sentIdx);
  }

  const lvl = token.cefr_level || "A1";
  document.getElementById("d-word").textContent = token.text;
  document.getElementById("d-cefr").textContent = "CEFR " + lvl;
  document.getElementById("d-cefr").className = "cefr-badge badge-" + lvl;

  let genderHtml = "";
  if (token.gender === "Masc")
    genderHtml = '<span class="gender-tag gender-der">der 阳性</span>';
  else if (token.gender === "Fem")
    genderHtml = '<span class="gender-tag gender-die">die 阴性</span>';
  else if (token.gender === "Neut")
    genderHtml = '<span class="gender-tag gender-das">das 中性</span>';

  let separableHtml = "";
  if (token.separable && token.separable.sep_lemma) {
    separableHtml = ` · 🔗 可分原形: <strong style="color:var(--accent);">${esc(token.separable.sep_lemma)}</strong>`;
  }

  document.getElementById("d-meta").innerHTML =
    `原型: <strong>${esc(token.lemma)}</strong> · 词性: ${esc(token.pos)} ${genderHtml}${separableHtml}` +
    (token.case ? ` · ${esc(token.case)}` : "");

  // Clear previous dynamic morphology sections
  const oldSep = document.getElementById("d-separable-box");
  if (oldSep) oldSep.remove();
  const oldStamm = document.getElementById("d-stammformen-box");
  if (oldStamm) oldStamm.remove();
  const oldKomposita = document.getElementById("d-komposita-box");
  if (oldKomposita) oldKomposita.remove();
  const oldPraep = document.getElementById("d-praep-box");
  if (oldPraep) oldPraep.remove();

  // Render Separable Banner if applicable
  if (token.separable && token.separable.sep_lemma) {
    const metaEl = document.getElementById("d-meta");
    const sepDiv = document.createElement("div");
    sepDiv.id = "d-separable-box";
    sepDiv.className = "separable-banner";
    sepDiv.innerHTML = `
      <span class="sep-tag">🔗 框形可分动词 (Satzklammer)</span>
      <span class="sep-formula">合成原形: <strong>${esc(token.separable.sep_lemma)}</strong></span>
    `;
    metaEl.parentNode.insertBefore(sepDiv, metaEl.nextSibling);
  }

  document.getElementById("d-def").value = "";
  document.getElementById("d-def-status").textContent = "词库查询中…";
  document.getElementById("d-sent").textContent = sent.text;
  document.getElementById("save-vocab-btn").textContent = "+ 加入 Anki 词汇卡";
  document.getElementById("grammar-result").classList.add("hidden");
  openDrawer("vocab");

  api("/api/lookup/vocab", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // 带上 spaCy 词元：查词链按 lemma 优先，geht→gehen / Häuser→Haus 才能命中
    body: JSON.stringify({
      sentence: sent.text,
      target_word: token.text,
      lemma: token.lemma || token.text,
    }),
  })
    .then((res) => {
      if (res && state.selectedToken?.text === token.text) {
        // 诚实显示释义来源：空释义不再谎称 "AI 已预填"
        const SRC_LABEL = {
          local_dict: "⚡ 歌德核心词库 (0ms)",
          linguistics_ext: "⚡ 本地词库 · 形态学",
          linguistics: "⚡ 本地词库 · 形态学",
          ai: "AI 在线释义",
          ai_error: "⚠ AI 接口异常，暂无释义",
          ai_exception: "⚠ AI 接口异常，暂无释义",
          none: "暂无离线释义",
        };
        const dDefEl = document.getElementById("d-def");
        if (res.definition_zh && !dDefEl.value) {
          dDefEl.value = res.definition_zh;
        }
        const statusEl = document.getElementById("d-def-status");
        statusEl.textContent =
          SRC_LABEL[res.source] ||
          (res.definition_zh ? "本地词库" : "暂无离线释义");
        if (!res.definition_zh) {
          dDefEl.placeholder = "该词暂无释义，可手动填写笔记…";
        }
        if (res.plural) state.selectedToken.plural = res.plural;
        if (res.gender && !genderHtml) {
          const gTag =
            res.gender === "Masc"
              ? '<span class="gender-tag gender-der">der 阳性</span>'
              : res.gender === "Fem"
                ? '<span class="gender-tag gender-die">die 阴性</span>'
                : '<span class="gender-tag gender-das">das 中性</span>';
          document.getElementById("d-meta").innerHTML += ` ${gTag}`;
        }

        // Render Stammformen if irregular verb
        if (res.stammformen) {
          state.selectedToken.stammformen = res.stammformen;
          const sf = res.stammformen;
          const metaEl = document.getElementById("d-meta");
          const stammDiv = document.createElement("div");
          stammDiv.id = "d-stammformen-box";
          stammDiv.className = "stammformen-banner";
          stammDiv.innerHTML = `
          <span class="stamm-tag">⚡ 强变化三态</span>
          <span class="stamm-formula"><strong>${esc(sf.infinitiv)}</strong> — ${esc(sf.praeteritum)} — <em>${esc(sf.hilfsverb)}</em> <strong>${esc(sf.partizip2)}</strong></span>
        `;
          metaEl.parentNode.insertBefore(stammDiv, metaEl.nextSibling);
        }

        // Render Komposita if compound noun
        if (res.komposita && res.komposita.length >= 2) {
          const metaEl =
            document.getElementById("d-stammformen-box") ||
            document.getElementById("d-meta");
          const kompDiv = document.createElement("div");
          kompDiv.id = "d-komposita-box";
          kompDiv.className = "komposita-banner";
          kompDiv.innerHTML = `
          <div class="komposita-title">🧩 复合词结构拆解:</div>
          <div class="komposita-pills-row">
            ${res.komposita
              .map(
                (k) => `
              <span class="komposita-pill" title="点击查看子词" onclick="window.inspectSubWord(${jsAttr(k.word)}, ${jsAttr(k.def_zh || "")}, ${jsAttr(k.gender || "")})">
                <span class="k-word">${esc(k.word)}</span>
                ${k.gender ? `<span class="k-gender">${esc(k.gender)}</span>` : ""}
                <span class="k-def">${esc(k.def_zh || "")}</span>
              </span>
            `,
              )
              .join('<span class="komposita-plus">+</span>')}
          </div>
        `;
          metaEl.parentNode.insertBefore(kompDiv, metaEl.nextSibling);
        }

        // Render Präpositionen-Kollokationen（固定介词搭配 + 支配的格）
        if (res.praepositionen && res.praepositionen.length) {
          // 存进 state：每条后面的「+」按钮按下标取数据，避免把例句里的引号
          // 拼进 onclick 属性（komposita 那种传参方式碰上 "…" 就会拼坏）。
          state.selectedToken.praepositionen = res.praepositionen;
          const anchor =
            document.getElementById("d-komposita-box") ||
            document.getElementById("d-stammformen-box") ||
            document.getElementById("d-meta");
          const praepDiv = document.createElement("div");
          praepDiv.id = "d-praep-box";
          praepDiv.className = "praep-banner";
          praepDiv.innerHTML = `
          <div class="praep-title">🧭 固定介词搭配 (Präposition + Kasus):</div>
          ${res.praepositionen
            .map(
              (p, i) => `
            <div class="praep-row">
              <span class="praep-prep">${esc(p.praeposition)}</span>
              <span class="praep-kasus">+ ${esc(p.kasus)}</span>
              <span class="praep-def">${esc(p.bedeutung_zh)}</span>
              <span class="praep-example">${esc(p.beispiel)}</span>
              <button class="praep-save" title="把这一条存成词汇卡"
                      onclick="window.savePrepCollocation(${i}, this)">+</button>
            </div>
          `,
            )
            .join("")}
        `;
          anchor.parentNode.insertBefore(praepDiv, anchor.nextSibling);
        }
      } else {
        document.getElementById("d-def-status").textContent = "";
      }
    })
    .catch(() => {
      document.getElementById("d-def-status").textContent = "";
    });
}

export function inspectSubWord(word, defZh, gender) {
  document.getElementById("d-def").value =
    `${word} (${gender ? gender + ", " : ""}${defZh})`;
  document.getElementById("d-def-status").textContent = "🧩 已选用复合子词释义";
}

// ── Drawer & Tabs ────────────────────────────────────────────────────────────
export function switchDrawerTab(tab) {
  const tabVocab = document.getElementById("d-tab-vocab");
  const tabSyntax = document.getElementById("d-tab-syntax");
  const tabNote = document.getElementById("d-tab-note");
  const tabAll = document.getElementById("d-tab-all");
  if (tabVocab) tabVocab.classList.toggle("active", tab === "vocab");
  if (tabSyntax) tabSyntax.classList.toggle("active", tab === "syntax");
  if (tabNote) tabNote.classList.toggle("active", tab === "note");
  if (tabAll) tabAll.classList.toggle("active", tab === "all");

  const vocabWrap = document.getElementById("drawer-vocab-wrap");
  const syntaxSec = document.getElementById("drawer-syntax-section");
  const noteSec = document.getElementById("drawer-note-section");

  if (vocabWrap)
    vocabWrap.classList.toggle("hidden", tab !== "vocab" && tab !== "all");
  if (syntaxSec)
    syntaxSec.classList.toggle("hidden", tab !== "syntax" && tab !== "all");
  if (noteSec)
    noteSec.classList.toggle("hidden", tab !== "note" && tab !== "all");

  const bodyEl = document.querySelector(".drawer-body");
  if (bodyEl) bodyEl.scrollTop = 0;

  if (tab === "note" && noteSec) {
    document.getElementById("note-text-input")?.focus();
  }
}

export function openDrawer(preferredTab = null) {
  document.getElementById("drawer")?.classList.add("open");
  document.body.classList.add("drawer-open");
  if (preferredTab) switchDrawerTab(preferredTab);
}

export function closeDrawer() {
  document.getElementById("drawer")?.classList.remove("open");
  document.body.classList.remove("drawer-open");
  document
    .querySelectorAll(".tok.sel")
    .forEach((el) => el.classList.remove("sel"));
}

// ── Grammar AI ───────────────────────────────────────────────────────────────
export async function analyzeGrammar() {
  const btn = document.getElementById("analyze-btn");
  btn.textContent = "分析中…";
  btn.disabled = true;
  try {
    state.grammarData = await api("/api/lookup/grammar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sentence: state.selectedSent.text,
        target_phrase: state.selectedToken.text,
      }),
    });
    const lvl = state.grammarData.cefr_level || "B1";
    document.getElementById("g-name").textContent =
      state.grammarData.grammar_name;
    document.getElementById("g-formula").textContent =
      state.grammarData.rule_formula || "";
    document
      .getElementById("g-formula")
      .classList.toggle("hidden", !state.grammarData.rule_formula);
    document.getElementById("g-exp").textContent =
      state.grammarData.explanation_zh;
    document.getElementById("g-badge").textContent = "Goethe " + lvl;
    document.getElementById("g-badge").className =
      "cefr-badge grammar-cefr-badge badge-" + lvl;
    document.getElementById("grammar-result").classList.remove("hidden");
  } catch {
    alert("语法解析失败，请检查 API Key");
  } finally {
    btn.textContent = "AI 深度剖析";
    btn.disabled = false;
  }
}

export async function saveVocab() {
  if (!state.selectedToken || !state.currentArticle) return;
  const btn = document.getElementById("save-vocab-btn");
  const originalText = btn ? btn.textContent : "+ 加入 Anki 词汇卡";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "保存中…";
  }
  const def =
    document.getElementById("d-def")?.value.trim() ||
    state.selectedToken.lemma ||
    state.selectedToken.text;
  try {
    await api("/api/cards/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: state.currentArticle.id,
        word: state.selectedToken.text,
        lemma: state.selectedToken.lemma,
        pos: state.selectedToken.pos,
        gender: state.selectedToken.gender,
        cefr_level: state.selectedToken.cefr_level || "A1",
        definition_zh: def,
        sentence_context: state.selectedSent ? state.selectedSent.text : "",
        plural: state.selectedToken.plural || "",
      }),
    });
    if (btn) {
      btn.textContent = "✓ 已保存";
      btn.disabled = false;
    }
    refreshCardCounters();
    Companion.celebrate("card_vocab");
  } catch (e) {
    if (btn) {
      btn.textContent = originalText;
      btn.disabled = false;
    }
    alert(`保存生词卡失败: ${e.message}`);
  }
}

/** 把抽屉里某一条介词搭配单独存成词汇卡。
 *
 * 为什么每条一个按钮：抽屉的 #save-vocab-btn 存的是「被点击的那个词」，
 * 而 bestehen 有 auf/aus/in 三条意思完全不同的搭配，用户得能只存想背的那条。
 * 不做「一键全存」——灌进不想背的条目会污染 FSRS 队列，而队列的价值
 * 恰恰建立在每张卡都是用户主动选的。
 *
 * 复用 vocab 卡而不新增 card_type：VocabCardReq 的字段刚好够用，
 * FSRS 排程与 Anki 导出立刻可用，零 schema 改动。
 */
export async function savePrepCollocation(index, btn) {
  const rows = state.selectedToken && state.selectedToken.praepositionen;
  if (!rows || !rows[index] || !state.currentArticle) return;
  const p = rows[index];
  const lemma = state.selectedToken.lemma || state.selectedToken.text;
  // 中文义里的「(sich)」是反身标记（数据集的键不带 sich，为了匹配 spaCy lemma），
  // 存卡时把它还原到词头，卡面才是德语里真正的形态：sich freuen auf
  const reflexive = p.bedeutung_zh.includes("(sich)");
  const head = `${reflexive ? "sich " : ""}${lemma} ${p.praeposition}`;
  const def = `${p.bedeutung_zh.replace("(sich)", "").trim()} (+${p.kasus})`;
  if (btn) btn.disabled = true;
  try {
    await api("/api/cards/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: state.currentArticle.id,
        word: head,
        lemma: lemma,
        pos: state.selectedToken.pos,
        cefr_level: state.selectedToken.cefr_level || "B1",
        definition_zh: def,
        sentence_context: p.beispiel,
      }),
    });
    if (btn) btn.textContent = "✓";
    refreshCardCounters();
    Companion.celebrate("card_vocab");
  } catch {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "+";
    }
    alert("保存搭配卡失败");
  }
}

export async function saveGrammar() {
  if (!state.grammarData || !state.currentArticle) return;
  const btn = document.getElementById("save-grammar-btn");
  const originalText = btn ? btn.textContent : "+ 加入 Anki 语法卡";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "保存中…";
  }
  try {
    await api("/api/cards/grammar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: state.currentArticle.id,
        sentence_context: state.selectedSent ? state.selectedSent.text : "",
        grammar_name: state.grammarData.grammar_name,
        cefr_level: state.grammarData.cefr_level || "B1",
        explanation_zh: state.grammarData.explanation_zh,
        rule_formula: state.grammarData.rule_formula,
      }),
    });
    if (btn) {
      btn.textContent = "✓ 已加入语法卡";
      btn.disabled = false;
    }
    refreshCardCounters();
    Companion.celebrate("card_grammar");
  } catch (e) {
    if (btn) {
      btn.textContent = originalText;
      btn.disabled = false;
    }
    alert(`保存语法卡失败: ${e.message}`);
  }
}

export async function refreshCardCounters() {
  try {
    const data = await api("/api/cards");
    const vLen = (data.vocab_cards || []).length;
    const gLen = (data.grammar_cards || []).length;
    const total = vLen + gLen;
    const badge = document.getElementById("card-count");
    const mobBadge = document.getElementById("mob-card-count");
    if (badge) badge.textContent = total;
    if (mobBadge) mobBadge.textContent = total;
  } catch (e) {}
}

// ── Notes & Selections ───────────────────────────────────────────────────────
export async function loadArticleNotes(articleId) {
  try {
    currentArticleNotes = await api(`/api/articles/${articleId}/notes`);
  } catch {
    currentArticleNotes = [];
  }

  document.querySelectorAll(".margin-note-badge").forEach((el) => el.remove());

  currentArticleNotes.forEach((note) => {
    if (note.note_content && note.sentence_id) {
      const sent = state.currentArticle?.sentences?.find(
        (s) => s.id === note.sentence_id,
      );
      if (sent && sent.tokens?.length) {
        const lastTok = sent.tokens[sent.tokens.length - 1];
        const lastTokEl = document.getElementById("tok-" + lastTok.id);
        if (
          lastTokEl &&
          !lastTokEl.parentNode.querySelector(`[data-note-id="${note.id}"]`)
        ) {
          const badge = document.createElement("span");
          badge.className = "margin-note-badge";
          badge.dataset.noteId = note.id;
          badge.innerHTML = `📌 随笔`;
          badge.title = note.note_content;
          badge.onclick = (e) => {
            e.stopPropagation();
            openNoteDrawerForExisting(note.id);
          };
          lastTokEl.insertAdjacentElement("afterend", badge);
        }
      }
    }
  });
}

export function setupSelectionTooltip() {
  const content = document.getElementById("reader-content");
  const tooltip = document.getElementById("selection-tooltip");
  if (!content || !tooltip) return;

  content.addEventListener("mouseup", () => {
    setTimeout(() => {
      const sel = window.getSelection();
      const text = sel ? sel.toString().trim() : "";
      if (text.length > 0 && content.contains(sel.anchorNode)) {
        state.activeSelectedRangeText = text;
        const range = sel.getRangeAt(0);
        const rect = range.getBoundingClientRect();

        let node = sel.anchorNode;
        while (node && node !== content) {
          if (node.id && node.id.startsWith("tok-")) {
            const tokId = parseInt(node.id.replace("tok-", ""), 10);
            const foundSent = state.currentArticle?.sentences?.find((s) =>
              s.tokens.some((t) => t.id === tokId),
            );
            if (foundSent) state.activeSelectedSentId = foundSent.id;
            break;
          }
          node = node.parentNode;
        }

        tooltip.style.left = `${rect.left + rect.width / 2}px`;
        tooltip.style.top = `${rect.top - 8}px`;
        tooltip.classList.remove("hidden");
      } else {
        tooltip.classList.add("hidden");
      }
    }, 50);
  });

  document.addEventListener("mousedown", (e) => {
    if (!tooltip.contains(e.target) && !content.contains(e.target)) {
      tooltip.classList.add("hidden");
    }
  });
}

export async function applyHighlight(color) {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const tooltip = document.getElementById("selection-tooltip");
  if (tooltip) tooltip.classList.add("hidden");

  await api(`/api/articles/${state.currentArticle.id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sentence_id: state.activeSelectedSentId || 1,
      selected_text: state.activeSelectedRangeText,
      color: color,
      note_content: "",
    }),
  });

  await loadArticleNotes(state.currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

export function openNoteDrawerFromSelection() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const tooltip = document.getElementById("selection-tooltip");
  if (tooltip) tooltip.classList.add("hidden");

  state.activeEditingNoteId = null;
  document.getElementById("note-badge-status").textContent = "随笔草稿";
  document.getElementById("note-quote").textContent =
    `"${state.activeSelectedRangeText}"`;
  document.getElementById("note-text-input").value = "";
  document.getElementById("save-note-btn").textContent = "✓ 保存便签";
  document.getElementById("del-note-btn").classList.add("hidden");

  openDrawer("note");
}

export function openNoteDrawerForExisting(noteId) {
  const note = currentArticleNotes.find((n) => n.id === noteId);
  if (!note) return;

  state.activeEditingNoteId = note.id;
  state.activeSelectedRangeText = note.selected_text;
  state.activeSelectedSentId = note.sentence_id;

  document.getElementById("note-badge-status").textContent = "已保存便签";
  document.getElementById("note-quote").textContent = `"${note.selected_text}"`;
  document.getElementById("note-text-input").value = note.note_content || "";
  document.getElementById("save-note-btn").textContent = "✓ 更新便签";
  document.getElementById("del-note-btn").classList.remove("hidden");

  openDrawer("note");
}

export async function aiNoteAssist() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const btn = document.getElementById("note-ai-btn");
  btn.textContent = "✨ 解析中…";
  btn.disabled = true;

  const sent = state.currentArticle.sentences?.find(
    (s) => s.id === state.activeSelectedSentId,
  );
  const sentText = sent ? sent.text : state.activeSelectedRangeText;

  try {
    const res = await api("/api/ai/note-assist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sentence: sentText,
        selected_text: state.activeSelectedRangeText,
      }),
    });

    if (res._stub) {
      const statusEl =
        document.getElementById("d-def-status") ||
        document.getElementById("note-ai-status");
      if (statusEl)
        statusEl.textContent = "⚠ 未配置 DEEPSEEK_API_KEY，AI 解析不可用";
      return;
    }

    let summary = res.summary_zh || "";
    if (res.key_points && res.key_points.length) {
      summary += "\n• " + res.key_points.join("\n• ");
    }
    document.getElementById("note-text-input").value = summary;
  } catch {
    alert("AI 速记解析失败，请检查网络配置");
  } finally {
    btn.textContent = "✨ AI 速记辅助";
    btn.disabled = false;
  }
}

export async function saveCurrentNote() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const noteText = document.getElementById("note-text-input").value.trim();

  if (state.activeEditingNoteId) {
    await api(`/api/notes/${state.activeEditingNoteId}`, { method: "DELETE" });
  }

  await api(`/api/articles/${state.currentArticle.id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sentence_id: state.activeSelectedSentId || 1,
      selected_text: state.activeSelectedRangeText,
      color: "yellow",
      note_content: noteText,
    }),
  });

  document.getElementById("save-note-btn").textContent = "✓ 已保存";
  await loadArticleNotes(state.currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

export async function deleteCurrentNote() {
  if (!state.activeEditingNoteId || !state.currentArticle) return;
  if (!confirm("确定删除此条随笔便签吗？")) return;
  await api(`/api/notes/${state.activeEditingNoteId}`, { method: "DELETE" });
  closeDrawer();
  await loadArticleNotes(state.currentArticle.id);
}

export function playSelectedAudio() {
  if (!state.activeSelectedRangeText) return;
  playGermanAudio(state.activeSelectedRangeText);
  document.getElementById("selection-tooltip")?.classList.add("hidden");
}

export function downloadStudyGuide() {
  if (!state.currentArticle) return;
  window.location.href = `/api/articles/${state.currentArticle.id}/export-guide`;
}

// ── Satzbau & Felder-Modell Engine ──────────────────────────────────────────

export function renderFelderSpectrum(topology, sentId) {
  if (!topology)
    return '<span style="font-size:0.75rem;color:var(--pencil);">五场域拓扑解析中...</span>';
  const fields = [
    { key: "vorfeld", label: "前场 VF", cls: "vf", desc: "Vorfeld" },
    {
      key: "linke_klammer",
      label: "左框 LK",
      cls: "lk",
      desc: "Linke Klammer",
    },
    { key: "mittelfeld", label: "中场 MF", cls: "mf", desc: "Mittelfeld" },
    {
      key: "rechte_klammer",
      label: "右框 RK",
      cls: "rk",
      desc: "Rechte Klammer",
    },
    { key: "nachfeld", label: "后场 NF", cls: "nf", desc: "Nachfeld" },
  ];

  const boxes = fields
    .map((f) => {
      const toks = topology[f.key] || [];
      const text =
        toks.map((t) => (t && t.text !== undefined ? t.text : t)).join(" ") ||
        "—";
      const isEmp = toks.length === 0;
      return `
      <div class="feld-pill feld-${f.cls}${isEmp ? " is-empty" : ""}" title="${f.desc}">
        <span class="feld-tag">${f.label}</span>
        <span class="feld-val">${esc(text)}</span>
      </div>
    `;
    })
    .join("");

  return `
    <div class="felder-spectrum-bar">
      ${boxes}
    </div>
    <div class="felder-bar-actions">
      <button class="btn-open-ast-action" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sentId)})">在工作台展开从句拓扑树 AST ➔</button>
    </div>
  `;
}

export function renderDetailedFelderGrid(topology) {
  if (!topology) return '<div class="empty-state">暂无拓扑场域数据</div>';
  const fields = [
    {
      key: "vorfeld",
      name: "前场 (Vorfeld)",
      desc: "主语 / 状语 / 前置从句",
      cls: "vf",
    },
    {
      key: "linke_klammer",
      name: "左框 (Linke Klammer)",
      desc: "主句变位动词 / 从句引导连词",
      cls: "lk",
    },
    {
      key: "mittelfeld",
      name: "中场 (Mittelfeld)",
      desc: "核心论元 / 宾语 / 副词状语",
      cls: "mf",
    },
    {
      key: "rechte_klammer",
      name: "右框 (Rechte Klammer)",
      desc: "未变位动词 / 分词 / 前缀 / 从句谓语",
      cls: "rk",
    },
    {
      key: "nachfeld",
      name: "后场 (Nachfeld)",
      desc: "后置从句 / 比较短语 / 补充成分",
      cls: "nf",
    },
  ];

  return fields
    .map((f) => {
      const toks = topology[f.key] || [];
      const text =
        toks.map((t) => (t && t.text !== undefined ? t.text : t)).join(" ") ||
        "（空）";
      const isEmp = toks.length === 0;
      return `
      <div class="feld-card feld-card-${f.cls}${isEmp ? " is-empty-card" : ""}">
        <div class="feld-card-header">
          <span class="feld-card-title">${f.name}</span>
          <span class="feld-card-desc">${f.desc}</span>
        </div>
        <div class="feld-card-content">${esc(text)}</div>
      </div>
    `;
    })
    .join("");
}

export function renderClauseTreeNode(node, depth = 0, sentId) {
  if (!node)
    return '<div class="syntax-empty" style="color:var(--pencil);font-size:0.8125rem;">暂无从句分层</div>';

  const typeCls = String(node.type || "hauptsatz").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const formulaHtml = node.formula
    ? `<div class="clause-formula"><code>${esc(node.formula)}</code></div>`
    : "";
  const connectorHtml = node.connector
    ? `<span class="clause-pill-tag tag-conn">引导: <strong>${esc(node.connector)}</strong></span>`
    : "";
  const verbHtml = node.finite_verb
    ? `<span class="clause-pill-tag tag-verb">动词: <strong>${esc(node.finite_verb)}</strong></span>`
    : "";
  const tokenIds = (node.token_ids || []).map(Number).filter(Number.isFinite);
  const tokenIdsJson = JSON.stringify(tokenIds);

  const childHtml =
    node.children && node.children.length > 0
      ? `<div class="clause-children-tree">${node.children.map((c) => renderClauseTreeNode(c, depth + 1, sentId)).join("")}</div>`
      : "";

  const clauseLabel = node.label || node.type || "句法节点";
  const clauseFormula = node.formula || "";
  const clauseText = node.text || "";

  return `
    <div class="clause-tree-node depth-${depth} type-${typeCls}">
      <div class="clause-node-box" onclick="highlightClauseTokens(${tokenIdsJson})">
        <div class="clause-node-top">
          <span class="clause-type-name">${esc(node.label || node.type)}</span>
          <div style="display:flex;gap:0.35rem;flex-wrap:wrap;">
            ${connectorHtml}
            ${verbHtml}
          </div>
        </div>
        ${formulaHtml}
        <div class="clause-quote-text">„${esc(node.text || "")}“</div>
        <div class="clause-node-footer">
          <button class="btn-clause-pill" onclick="event.stopPropagation(); highlightClauseTokens(${tokenIdsJson})">🔍 聚焦高亮</button>
          <button class="btn-clause-pill btn-save-anki" onclick="event.stopPropagation(); saveClauseAsGrammarCard(${jsAttr(clauseLabel)}, ${jsAttr(clauseFormula)}, ${jsAttr(clauseText)}, ${Number(sentId)})">+ 加入语法卡</button>
        </div>
      </div>
      ${childHtml}
    </div>
  `;
}

export function toggleSentenceTopology(sentId) {
  const el = document.getElementById(`sent-topology-${sentId}`);
  if (!el) return;
  const isHidden = el.classList.contains("hidden");
  document
    .querySelectorAll(".sentence-topology-strip")
    .forEach((s) => s.classList.add("hidden"));
  if (isHidden) {
    el.classList.remove("hidden");
  }
}

export function openSyntaxDrawerForSentence(sentId) {
  const sent = state.currentArticle?.sentences?.find((s) => s.id === sentId);
  if (!sent) return;
  state.selectedSent = sent;

  const quoteEl = document.getElementById("syntax-sent-quote");
  if (quoteEl) quoteEl.textContent = sent.text;

  const typeBadge = document.getElementById("syntax-sent-type-badge");
  const tree = sent.clause_tree || {};
  if (typeBadge) {
    typeBadge.textContent = tree.label || "V2 主句";
  }

  const felderGrid = document.getElementById("syntax-felder-grid");
  if (felderGrid) {
    felderGrid.innerHTML = renderDetailedFelderGrid(sent.topology);
  }

  const treeContainer = document.getElementById("syntax-tree-container");
  if (treeContainer) {
    treeContainer.innerHTML = renderClauseTreeNode(sent.clause_tree, 0, sentId);
  }

  openDrawer("syntax");
}

export function highlightClauseTokens(tokenIds) {
  document
    .querySelectorAll(".tok.clause-highlight")
    .forEach((el) => el.classList.remove("clause-highlight"));
  if (!tokenIds || !tokenIds.length) return;
  tokenIds.forEach((id) => {
    const el = document.getElementById("tok-" + id);
    if (el) el.classList.add("clause-highlight");
  });
}

export async function saveClauseAsGrammarCard(
  label,
  formula,
  textSnippet,
  sentId,
) {
  const sent = state.currentArticle?.sentences?.find((s) => s.id === sentId);
  if (!sent || !state.currentArticle) return;
  try {
    await api("/api/cards/grammar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: state.currentArticle.id,
        sentence_context: sent.text,
        grammar_name: label || "德语从句句法",
        cefr_level: "B1",
        explanation_zh: `【${label}】\n句式公式：${formula || "德语经典拓扑结构"}\n例句分析：${textSnippet}`,
        rule_formula: formula || "Satzbau",
      }),
    });
    refreshCardCounters();
    alert(`✓ 已将「${label}」沉淀至 Anki 语法卡盒！`);
  } catch (err) {
    alert("保存语法卡失败");
  }
}

if (typeof window !== "undefined") {
  window.deleteArticle = deleteArticle;
}
