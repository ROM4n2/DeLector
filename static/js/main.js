/* DeLector - Application Main Entry & Router */
"use strict";

import { state, api, esc, jsAttr } from "./core.js";
import { ShadowPlayer, playGermanAudio } from "./player.js";
import { Companion } from "./companion.js";
import {
  loadArticles,
  deleteArticle,
  openReader,
  inspect,
  toggleCefrFocus,
  clearCefrFocus,
  switchDrawerTab,
  openDrawer,
  closeDrawer,
  analyzeGrammar,
  saveVocab,
  saveGrammar,
  applyTypography,
  setFontMode,
  adjustFontSize,
  setupSelectionTooltip,
  applyHighlight,
  openNoteDrawerFromSelection,
  openNoteDrawerForExisting,
  aiNoteAssist,
  saveCurrentNote,
  deleteCurrentNote,
  playSelectedAudio,
  downloadStudyGuide,
  refreshCardCounters,
  inspectSubWord,
  savePrepCollocation,
  renderFelderSpectrum,
  renderDetailedFelderGrid,
  renderClauseTreeNode,
  toggleSentenceTopology,
  openSyntaxDrawerForSentence,
  highlightClauseTokens,
  saveClauseAsGrammarCard,
} from "./reader.js";

import {
  setCardSegment,
  setCardViewMode,
  loadCards,
  toggleDeckFlip,
  stepDeck,
  submitCardReview,
  deleteCard,
  toggleMaster,
  openQuizOverlay,
  closeQuizOverlay,
  startQuiz,
  flipFlashcard,
  submitFlashcard,
  checkDictation,
  advanceQuiz,
  submitChoice,
  clearAudioCache,
  downloadBackupJson,
  uploadBackupJson,
  filterPrepCase,
  searchPrepCollocations,
  savePrepCardFromMatrix,
  retryPrepMatrix,
  setA1Mode,
  filterA1Topic,
  searchA1Vocab,
  flipA1Card,
  stepA1Card,
  randomA1Card,
  saveA1VocabCard,
  saveA1WordToDeck,
  renderA1PokerCard,
  playA1Audio,
} from "./cards.js";
import {
  switchFolioPage,
  prevFolioPage,
  nextFolioPage,
  scrollToFolioSection,
  renderMarquees,
  loadProgress,
} from "./folio.js";
import {
  openClozeModal,
  closeClozeModal,
  switchClozeMode,
  renderClozeExercise,
  handleClozeKey,
  revealClozeHints,
  resetClozeExercise,
  submitClozeExercise,
} from "./cloze.js";
import {
  loadWriterEssays,
  analyzeWriterText,
  selectWriterSpan,
  saveWriterErrorAsCard,
  aiPolishEssay,
  saveWriterEssay,
  openWriterEssay,
  deleteWriterEssay,
  clearWriterForm,
  switchWriterPanelTab,
  openPolishOverlay,
  closePolishOverlay,
  setPolishHunk,
  togglePolishHunk,
  acceptAllPolishHunks,
  rejectAllPolishHunks,
  applyPolishChanges,
  saveEssayVersion,
  restoreEssayVersion,
  loadEssayVersions,
  previewEssayVersion,
  closeVersionPreview,
  deleteEssayVersion,
  jumpToSentence,
  fixSelectedSpan,
  clearEditorText,
  setupEditorListeners,
  toggleInlayHints,
  openWriterProblem,
  renderProblemsPanel,
  toggleWriterMobilePanel,
  closeWriterMobilePanel,
  switchWriterMode,
  selectA1Formular,
  prevA1Formular,
  nextA1Formular,
  randomA1Formular,
  checkA1Formular,
  resetA1Formular,
  selectA1Email,
  prevA1Email,
  nextA1Email,
  randomA1Email,
  onA1EmailInput,
  diagnoseA1Email,
  applyA1EmailTemplate,
  clearA1Email,
} from "./writer.js";
import * as A1Hoeren from "./a1_hoeren.js";
import * as A1Lesen from "./a1_lesen.js";

// ── View Router ─────────────────────────────────────────────────────────────
export function show(view) {
  if (view === "articles") view = "home";
  document
    .querySelectorAll(".view")
    .forEach((el) => el.classList.remove("active"));
  const targetView = document.getElementById("view-" + view);
  if (targetView) targetView.classList.add("active");

  // Top nav tabs
  document
    .querySelectorAll(".nav-tab")
    .forEach((el) => el.classList.remove("active"));
  const activeNavBtn = document.getElementById("nav-btn-" + view);
  if (activeNavBtn) activeNavBtn.classList.add("active");

  // Mobile bottom nav
  document
    .querySelectorAll(".mobile-nav-btn")
    .forEach((el) => el.classList.remove("active"));
  const activeMobBtn = document.getElementById("mob-btn-" + view);
  if (activeMobBtn) activeMobBtn.classList.add("active");

  const bottomNav = document.getElementById("mobile-bottom-nav");
  if (bottomNav) {
    bottomNav.classList.toggle("hidden", view === "reader");
  }

  // German workbench 用 iframe 全屏，伴读宠物会盖住底部按钮（尤其 Android）
  const compEl = document.getElementById("companion");
  if (compEl) {
    if (view === "german") {
      compEl.classList.add("is-disabled");
    } else if (Companion.enabled) {
      compEl.classList.remove("is-disabled");
    }
  }

  closeDrawer();
  clearCefrFocus();
  // 切视图时清掉 writer 的 mobile sheet：否则 v4.4.5 起的 .writer-panel-lock
  // 与 scrim 仍挂着，从 reader 走硬件返回键到 home 时会落在一个半透明、滚不
  // 动的屏幕上（writer.js:closeWriterMobilePanel 内部负责 scrim + body lock + panel class 三个清理）。
  // typeof 守卫：函数来自 ./writer.js 的具名 export，走 main.js:114-116 注入；
  // 模块加载失败时不挂、不影响其它视图切换。
  if (typeof closeWriterMobilePanel === "function") closeWriterMobilePanel();

  if (view !== "cards") {
    if (typeof A1Hoeren?.stopHoerenExam === "function")
      A1Hoeren.stopHoerenExam();
    if (typeof A1Lesen?.stopLesenExam === "function") A1Lesen.stopLesenExam();
  }

  const player = document.getElementById("shadow-player");
  if (player) {
    player.classList.toggle("hidden", view !== "reader");
    if (view !== "reader") ShadowPlayer.pause();
  }

  if (view === "home") loadArticles();
  if (view === "cards") loadCards();
  if (view === "progress") loadProgress();
  if (view === "writer") {
    loadWriterEssays();
    setupEditorListeners();
  }
}

// ── Import Modal ─────────────────────────────────────────────────────────────
let currentImportTab = "text";
let cachedFeedSources = [];
let activeFeedId = null;

export function switchImportTab(tab) {
  currentImportTab = tab;
  document
    .querySelectorAll(".modal-tab, .import-tab")
    .forEach((b) => b.classList.remove("active"));
  document
    .querySelectorAll(".tab-content")
    .forEach((c) => c.classList.remove("active"));
  document.getElementById(`tab-btn-${tab}`)?.classList.add("active");
  document.getElementById(`import-tab-${tab}`)?.classList.add("active");

  const impBtn = document.getElementById("import-btn");
  if (impBtn) {
    impBtn.style.display = tab === "feed" ? "none" : "inline-flex";
  }

  if (tab === "feed" && !cachedFeedSources.length) {
    loadFeedSources();
  }
}

export async function loadFeedSources() {
  const bar =
    document.getElementById("feed-sources-bar") ||
    document.getElementById("feed-sources-list");
  if (!bar) return;
  try {
    const res = await api("/api/feed/sources");
    cachedFeedSources = res.sources || [];
    if (!cachedFeedSources.length) {
      bar.innerHTML =
        '<span style="color:var(--pencil);font-size:0.75rem;">暂无可用的德语订阅源</span>';
      return;
    }

    bar.innerHTML = cachedFeedSources
      .map(
        (s, idx) => `
      <button class="feed-source-pill ${s.id === (activeFeedId || cachedFeedSources[0].id) ? "active" : ""}"
        data-id="${esc(s.id)}"
        onclick="window.selectFeedSource(${jsAttr(s.id)})">
        <span class="feed-source-idx">${String(idx + 1).padStart(2, "0")}.</span>
        <span class="feed-source-name">${esc(s.name)}</span>
        <span class="feed-lvl-tag">${esc(s.level)}</span>
      </button>
    `,
      )
      .join("");

    const initial =
      cachedFeedSources.find((s) => s.id === activeFeedId) ||
      cachedFeedSources[0];
    if (initial) {
      activeFeedId = initial.id;
      loadFeedItems(initial.url);
    }
  } catch (e) {
    console.error("Failed to load feed sources:", e);
    bar.innerHTML = `<span style="color:var(--cherry);font-size:0.75rem;">无法加载订阅源: ${e.message || "网络或服务异常"}（请重启 start.bat）</span>`;
  }
}

export function selectFeedSource(feedId) {
  activeFeedId = feedId;
  document.querySelectorAll(".feed-source-pill").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-id") === feedId);
  });
  const target = cachedFeedSources.find((s) => s.id === feedId);
  if (target) {
    loadFeedItems(target.url);
  }
}

export async function loadFeedItems(url) {
  const container =
    document.getElementById("feed-items-container") ||
    document.getElementById("feed-items-list");
  if (!container) return;
  container.innerHTML =
    '<div style="text-align:center;padding:2.5rem;color:var(--pencil);font-family:var(--mono);font-size:0.8125rem;">⏳ 正在抓取最新外刊列表…</div>';

  try {
    const res = await api(`/api/feed/items?url=${encodeURIComponent(url)}`);
    const items = res.items || [];
    if (!items.length) {
      container.innerHTML =
        '<div style="text-align:center;padding:2rem;color:var(--pencil);font-size:0.8125rem;">该订阅源暂无可解析文章。</div>';
      return;
    }

    const currentSource = cachedFeedSources.find((s) => s.id === activeFeedId);
    const sourceName = currentSource ? currentSource.name : "RSS";

    container.innerHTML = items
      .map(
        (it, idx) => `
      <div class="feed-item-card">
        <div class="feed-item-header">
          <div class="feed-item-index">[ Nº ${String(idx + 1).padStart(2, "0")} ]</div>
          <div class="feed-item-date">${it.pub_date ? it.pub_date.slice(0, 16) : ""}</div>
        </div>
        <div class="feed-item-title">${esc(it.title)}</div>
        ${it.summary ? `<div class="feed-item-summary">${esc(it.summary)}</div>` : ""}
        <div class="feed-item-footer">
          <span class="feed-item-origin">QUELLE: ${esc(it.source || sourceName)}</span>
          <button class="btn-feed-ingest" onclick="window.ingestFeedItem(${jsAttr(encodeURIComponent(it.link))}, ${jsAttr(encodeURIComponent(it.title))}, this)">
            📥 导入精读
          </button>
        </div>
      </div>
    `,
      )
      .join("");
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:2rem;color:var(--cherry);font-size:0.8125rem;">抓取失败：${e.message}</div>`;
  }
}

export async function ingestFeedItem(encodedUrl, encodedTitle, btn) {
  const url = decodeURIComponent(encodedUrl);
  const title = decodeURIComponent(encodedTitle);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "抓取解析中…";
  }

  try {
    const data = await api("/api/articles/ingest-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, title }),
    });
    closeModal();
    openReader(data.article_id);
  } catch (e) {
    alert(`导入外刊失败: ${e.message}`);
    if (btn) {
      btn.disabled = false;
      btn.textContent = "📥 导入精读";
    }
  }
}

export function openModal() {
  const el =
    document.getElementById("modal-overlay") ||
    document.getElementById("import-overlay");
  if (!el) return;
  el.classList.remove("hidden");
  el.classList.add("open");
  switchImportTab(currentImportTab || "text");
}

export function closeModal() {
  const el =
    document.getElementById("modal-overlay") ||
    document.getElementById("import-overlay");
  if (!el) return;
  el.classList.add("hidden");
  el.classList.remove("open");
}

// ── Settings Modal ─────────────────────────────────────────────────────────
export async function openSettingsModal() {
  const overlay = document.getElementById("settings-overlay");
  if (!overlay) return;
  overlay.classList.remove("hidden");
  overlay.classList.add("open");

  const statusEl = document.getElementById("set-key-status");
  const feedbackEl = document.getElementById("test-key-feedback");
  if (feedbackEl) feedbackEl.textContent = "";

  try {
    const s = await api("/api/settings");
    document.getElementById("set-base-url").value =
      s.api_base_url || "https://api.deepseek.com";
    document.getElementById("set-model-name").value =
      s.api_model || "deepseek-v4-flash";
    if (s.tts_voice)
      document.getElementById("set-tts-voice").value = s.tts_voice;
    if (s.tts_rate) document.getElementById("set-tts-rate").value = s.tts_rate;

    if (s.has_api_key) {
      statusEl.textContent = `✓ 当前已配置 Key: ${s.api_key_masked}（留空保存表示不修改）`;
      statusEl.style.color = "#16a34a";
    } else {
      statusEl.textContent = "⚠️ 当前未配置 API Key（AI 深度语法剖析需配置）";
      statusEl.style.color = "#ca8a04";
    }
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

export function closeSettingsModal() {
  const overlay = document.getElementById("settings-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  overlay.classList.remove("open");
}

export function toggleKeyVisibility() {
  const input = document.getElementById("set-api-key");
  const btn = document.getElementById("btn-toggle-key-vis");
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    if (btn) btn.textContent = "🔒";
  } else {
    input.type = "password";
    if (btn) btn.textContent = "👁️";
  }
}

export async function testApiKeyConnection() {
  const btn = document.getElementById("btn-test-key");
  const feedback = document.getElementById("test-key-feedback");
  const key = document.getElementById("set-api-key").value.trim();
  const baseUrl = document.getElementById("set-base-url").value.trim();
  const model = document.getElementById("set-model-name").value.trim();

  btn.textContent = "⏳ 测试中…";
  btn.disabled = true;
  feedback.textContent = "";
  feedback.style.color = "var(--pencil)";

  try {
    const res = await api("/api/settings/test-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: key,
        api_base_url: baseUrl,
        api_model: model,
      }),
    });
    if (res.success) {
      feedback.textContent = `✓ ${res.message}`;
      feedback.style.color = "#16a34a";
    } else {
      feedback.textContent = `✕ ${res.error}`;
      feedback.style.color = "#dc2626";
    }
  } catch (err) {
    feedback.textContent = `✕ 请求异常: ${err.message}`;
    feedback.style.color = "#dc2626";
  } finally {
    btn.textContent = "⚡ 测试连通性";
    btn.disabled = false;
  }
}

export async function saveAppSettings() {
  const btn = document.getElementById("btn-save-settings");
  const key = document.getElementById("set-api-key").value.trim();
  const baseUrl = document.getElementById("set-base-url").value.trim();
  const model = document.getElementById("set-model-name").value.trim();
  const voice = document.getElementById("set-tts-voice").value;
  const rate = document.getElementById("set-tts-rate").value;

  btn.textContent = "保存中…";
  btn.disabled = true;

  try {
    const body = {
      api_base_url: baseUrl,
      api_model: model,
      tts_voice: voice,
      tts_rate: rate,
    };
    if (key) body.api_key = key;

    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (voice && window.ShadowPlayer) {
      ShadowPlayer.setVoice(voice);
    }

    alert("✓ 偏好与 API 设置已成功保存并即刻生效！");
    closeSettingsModal();
  } catch (err) {
    alert("保存设置失败: " + err.message);
  } finally {
    btn.textContent = "✓ 保存并生效";
    btn.disabled = false;
  }
}

export async function submitActiveImport() {
  if (currentImportTab === "text") {
    await submitImport();
  } else if (currentImportTab === "url") {
    const urlInput =
      document.getElementById("imp-url-input") ||
      document.getElementById("import-url-input");
    const titleInput =
      document.getElementById("imp-url-title") ||
      document.getElementById("import-url-title");
    const url = urlInput ? urlInput.value.trim() : "";
    const title = titleInput ? titleInput.value.trim() : "";
    if (!url) {
      alert("请输入有效的德语网页链接");
      return;
    }
    const btn = document.getElementById("import-btn");
    btn.textContent = "抓取解析中…";
    btn.disabled = true;
    try {
      const data = await api("/api/articles/ingest-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, title }),
      });
      closeModal();
      if (urlInput) urlInput.value = "";
      if (titleInput) titleInput.value = "";
      openReader(data.article_id);
    } catch (e) {
      alert("抓取失败，请检查网址是否为公开德语网页，或直接复制文本导入");
    } finally {
      btn.textContent = "开始阅读";
      btn.disabled = false;
    }
  } else if (currentImportTab === "file") {
    const textInput =
      document.getElementById("imp-text") ||
      document.getElementById("import-text-input");
    const text = textInput ? textInput.value.trim() : "";
    if (text) {
      await submitImport();
    } else {
      document.getElementById("file-input")?.click();
    }
  }
}

export function handleFileSelect(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  readFileContent(file);
  e.target.value = "";
}

function readFileContent(file) {
  const reader = new FileReader();
  reader.onload = function (evt) {
    const text = evt.target.result;
    const title = file.name.replace(/\.[^/.]+$/, "");
    const titleEl =
      document.getElementById("imp-title") ||
      document.getElementById("import-title-input");
    const textEl =
      document.getElementById("imp-text") ||
      document.getElementById("import-text-input");
    if (titleEl) titleEl.value = title;
    if (textEl) textEl.value = text;
    switchImportTab("text");
  };
  reader.readAsText(file, "UTF-8");
}

export function setupDropzone() {
  const dz = document.getElementById("dropzone");
  if (!dz) return;
  ["dragenter", "dragover", "dragleave", "drop"].forEach((evtName) => {
    dz.addEventListener(evtName, (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
  });
  dz.addEventListener("dragover", () => dz.classList.add("dragover"));
  dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
  dz.addEventListener("drop", (e) => {
    dz.classList.remove("dragover");
    const file = e.dataTransfer?.files?.[0];
    if (file) readFileContent(file);
  });
}

export async function submitImport() {
  const textEl =
    document.getElementById("imp-text") ||
    document.getElementById("import-text-input");
  const titleEl =
    document.getElementById("imp-title") ||
    document.getElementById("import-title-input");
  const text = textEl ? textEl.value.trim() : "";
  const title = (titleEl && titleEl.value.trim()) || "未命名文稿";
  if (!text) {
    alert("请输入德语文本");
    return;
  }
  const btn = document.getElementById("import-btn");
  btn.textContent = "处理中…";
  btn.disabled = true;
  try {
    const data = await api("/api/articles/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, raw_text: text }),
    });
    closeModal();
    document.getElementById("imp-text").value = "";
    document.getElementById("imp-title").value = "";
    openReader(data.article_id);
  } catch {
    alert("导入失败");
  } finally {
    btn.textContent = "开始阅读";
    btn.disabled = false;
  }
}

// ── Global Hotkeys ───────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  const isEditing = ["INPUT", "TEXTAREA"].includes(
    document.activeElement?.tagName,
  );
  const isModalOpen = document
    .getElementById("modal-overlay")
    ?.classList.contains("open");

  if (e.key === "Escape") {
    clearCefrFocus();
    closeDrawer();
    closeModal();
    return;
  }

  if (isEditing || isModalOpen) return;

  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    const drawer = document.getElementById("drawer");
    if (drawer?.classList.contains("open")) {
      e.preventDefault();
      saveVocab();
      return;
    }
  }

  const isReader = document
    .getElementById("view-reader")
    ?.classList.contains("active");
  const isCards = document
    .getElementById("view-cards")
    ?.classList.contains("active");
  const isProgress = document
    .getElementById("view-progress")
    ?.classList.contains("active");

  if (e.code === "Space") {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.toggle();
    } else if (isCards) {
      e.preventDefault();
      toggleDeckFlip();
    }
  } else if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.next();
    } else if (isCards) {
      stepDeck(1);
    } else if (isProgress) {
      nextFolioPage();
    }
  } else if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.prev();
    } else if (isCards) {
      stepDeck(-1);
    } else if (isProgress) {
      prevFolioPage();
    }
  } else if (e.key === "r" || e.key === "R") {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.replay();
    }
  }

  if (isReader && (e.key === "j" || e.key === "k")) {
    const tokens = Array.from(document.querySelectorAll(".tok"));
    if (!tokens.length) return;
    const curIndex = tokens.findIndex((el) => el.classList.contains("sel"));
    let nextIndex = 0;
    if (e.key === "j") {
      nextIndex = curIndex < tokens.length - 1 ? curIndex + 1 : 0;
    } else {
      nextIndex = curIndex > 0 ? curIndex - 1 : tokens.length - 1;
    }
    tokens[nextIndex]?.click();
    tokens[nextIndex]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

// ── Mount All Interactive Handlers to Window for HTML Compatibility ─────────
Object.assign(window, {
  // Navigation & Core
  show,
  openModal,
  closeModal,
  openSettingsModal,
  closeSettingsModal,
  toggleKeyVisibility,
  testApiKeyConnection,
  saveAppSettings,
  switchImportTab,
  submitActiveImport,
  handleFileSelect,
  submitImport,
  selectFeedSource,
  loadFeedItems,
  ingestFeedItem,

  // Reader & Token Inspector
  openReader,
  deleteArticle,
  inspect,
  toggleCefrFocus,
  clearCefrFocus,
  switchDrawerTab,
  openDrawer,
  closeDrawer,
  analyzeGrammar,
  saveVocab,
  saveGrammar,
  saveVocabCard: saveVocab,
  saveGrammarCard: saveGrammar,
  playGermanAudio,
  setFontMode,
  adjustFontSize,
  applyHighlight,
  openNoteDrawerFromSelection,
  openNoteDrawerForExisting,
  aiNoteAssist,
  saveCurrentNote,
  deleteCurrentNote,
  playSelectedAudio,
  downloadStudyGuide,
  inspectSubWord,
  savePrepCollocation,
  renderFelderSpectrum,
  renderDetailedFelderGrid,
  renderClauseTreeNode,
  toggleSentenceTopology,
  openSyntaxDrawerForSentence,
  highlightClauseTokens,
  saveClauseAsGrammarCard,

  // Cards & Deck
  setCardSegment,
  setCardViewMode,
  loadCards,
  toggleDeckFlip,
  stepDeck,
  submitCardReview,
  deleteCard,
  toggleMaster,
  openQuizOverlay,
  closeQuizOverlay,
  startQuiz,
  flipFlashcard,
  submitFlashcard,
  checkDictation,
  advanceQuiz,
  selectChoiceOption: submitChoice,
  clearAudioCache,
  downloadBackupJson,
  uploadBackupJson,

  // Präpositionen-Matrix（卡盒第四段的行内 onclick / oninput）
  filterPrepCase,
  searchPrepCollocations,
  savePrepCardFromMatrix,
  retryPrepMatrix,

  // Goethe A1 Wortliste & Sprechen
  setA1Mode,
  filterA1Topic,
  searchA1Vocab,
  flipA1Card,
  stepA1Card,
  randomA1Card,
  saveA1VocabCard,
  saveA1WordToDeck,
  renderA1PokerCard,
  playA1Audio,

  // Atelier Landing Page Folio
  switchFolioPage,
  prevFolioPage,
  nextFolioPage,
  scrollToFolioSection,
  renderMarquees,
  loadProgress,

  // Cloze
  openClozeModal,
  closeClozeModal,
  switchClozeMode,
  revealClozeHints,
  resetClozeExercise,
  submitClozeExercise,
  handleClozeKey,

  // Writer & Schreibwerkstatt
  loadWriterEssays,
  analyzeWriterText,
  selectWriterSpan,
  saveWriterErrorAsCard,
  aiPolishEssay,
  saveWriterEssay,
  openWriterEssay,
  deleteWriterEssay,
  clearWriterForm,
  switchWriterPanelTab,
  openPolishOverlay,
  closePolishOverlay,
  setPolishHunk,
  togglePolishHunk,
  acceptAllPolishHunks,
  rejectAllPolishHunks,
  applyPolishChanges,
  saveEssayVersion,
  restoreEssayVersion,
  loadEssayVersions,
  previewEssayVersion,
  closeVersionPreview,
  deleteEssayVersion,
  jumpToSentence,
  fixSelectedSpan,
  clearEditorText,
  toggleInlayHints,
  openWriterProblem,
  renderProblemsPanel,
  toggleWriterMobilePanel,
  closeWriterMobilePanel,
  switchWriterMode,
  selectA1Formular,
  prevA1Formular,
  nextA1Formular,
  randomA1Formular,
  checkA1Formular,
  resetA1Formular,
  selectA1Email,
  prevA1Email,
  nextA1Email,
  randomA1Email,
  onA1EmailInput,
  diagnoseA1Email,
  applyA1EmailTemplate,
  clearA1Email,

  // Player
  ShadowPlayer,

  // Companion Mascot System
  Companion,

  // Goethe A1 Exam Engines
  A1Hoeren,
  A1Lesen,
});

// ── PWA Service Worker Registration ──────────────────────────────────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

// ── Application Initialization ───────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadArticles();
  refreshCardCounters();
  applyTypography();
  setupDropzone();
  setupSelectionTooltip();
  setupEditorListeners();
  ShadowPlayer.init();
  Companion.init();
});
