/* DeLector - Application Main Entry & Router */
'use strict';

import { state, api } from './core.js';
import { ShadowPlayer, playGermanAudio } from './player.js';
import {
  loadArticles,
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
  refreshCardCounters
} from './reader.js';
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
  uploadBackupJson
} from './cards.js';
import {
  switchFolioPage,
  prevFolioPage,
  nextFolioPage,
  loadProgress
} from './folio.js';
import {
  openClozeModal,
  closeClozeModal,
  switchClozeMode,
  renderClozeExercise,
  handleClozeKey,
  revealClozeHints,
  resetClozeExercise,
  submitClozeExercise
} from './cloze.js';

// ── View Router ─────────────────────────────────────────────────────────────
export function show(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  const targetView = document.getElementById('view-' + view);
  if (targetView) targetView.classList.add('active');

  // Top nav tabs
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  const activeNavBtn = document.getElementById('nav-btn-' + view);
  if (activeNavBtn) activeNavBtn.classList.add('active');

  // Mobile bottom nav
  document.querySelectorAll('.mobile-nav-btn').forEach(el => el.classList.remove('active'));
  const activeMobBtn = document.getElementById('mob-btn-' + view);
  if (activeMobBtn) activeMobBtn.classList.add('active');

  closeDrawer();
  clearCefrFocus();

  const player = document.getElementById('shadow-player');
  if (player) {
    player.classList.toggle('hidden', view !== 'reader');
    if (view !== 'reader') ShadowPlayer.pause();
  }

  if (view === 'home')     loadArticles();
  if (view === 'cards')    loadCards();
  if (view === 'progress') loadProgress();
}

// ── Import Modal ─────────────────────────────────────────────────────────────
let currentImportTab = 'text';
let cachedFeedSources = [];
let activeFeedId = null;

export function switchImportTab(tab) {
  currentImportTab = tab;
  document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(`tab-btn-${tab}`)?.classList.add('active');
  document.getElementById(`import-tab-${tab}`)?.classList.add('active');

  const impBtn = document.getElementById('import-btn');
  if (impBtn) {
    impBtn.style.display = tab === 'feed' ? 'none' : 'inline-flex';
  }

  if (tab === 'feed' && !cachedFeedSources.length) {
    loadFeedSources();
  }
}

export async function loadFeedSources() {
  const bar = document.getElementById('feed-sources-bar');
  if (!bar) return;
  try {
    const res = await api('/api/feed/sources');
    cachedFeedSources = res.sources || [];
    if (!cachedFeedSources.length) return;

    bar.innerHTML = cachedFeedSources.map(s => `
      <button class="feed-source-pill ${s.id === (activeFeedId || cachedFeedSources[0].id) ? 'active' : ''}"
        data-id="${s.id}"
        onclick="window.selectFeedSource('${s.id}')">
        <span>${s.name}</span>
        <span class="feed-lvl-tag">${s.level}</span>
      </button>
    `).join('');

    const initial = cachedFeedSources.find(s => s.id === activeFeedId) || cachedFeedSources[0];
    if (initial) {
      activeFeedId = initial.id;
      loadFeedItems(initial.url);
    }
  } catch (e) {
    bar.innerHTML = '<span style="color:var(--pencil);font-size:0.75rem;">无法加载订阅源</span>';
  }
}

export function selectFeedSource(feedId) {
  activeFeedId = feedId;
  document.querySelectorAll('.feed-source-pill').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-id') === feedId);
  });
  const target = cachedFeedSources.find(s => s.id === feedId);
  if (target) {
    loadFeedItems(target.url);
  }
}


export async function loadFeedItems(url) {
  const container = document.getElementById('feed-items-container');
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;padding:2.5rem;color:var(--pencil);font-family:var(--mono);font-size:0.8125rem;">⏳ 正在抓取最新外刊列表…</div>';

  try {
    const res = await api(`/api/feed/items?url=${encodeURIComponent(url)}`);
    const items = res.items || [];
    if (!items.length) {
      container.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--pencil);font-size:0.8125rem;">该订阅源暂无可解析文章。</div>';
      return;
    }

    container.innerHTML = items.map(it => `
      <div class="feed-item-card">
        <div class="feed-item-header">
          <div class="feed-item-title">${it.title}</div>
          <div class="feed-item-date">${it.pub_date ? it.pub_date.slice(0, 16) : ''}</div>
        </div>
        ${it.summary ? `<div class="feed-item-summary">${it.summary}</div>` : ''}
        <div class="feed-item-footer">
          <button class="btn-feed-ingest" onclick="window.ingestFeedItem('${encodeURIComponent(it.link)}', '${encodeURIComponent(it.title)}', this)">
            📥 导入精读
          </button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:2rem;color:var(--cherry);font-size:0.8125rem;">抓取失败：${e.message}</div>`;
  }
}

export async function ingestFeedItem(encodedUrl, encodedTitle, btn) {
  const url = decodeURIComponent(encodedUrl);
  const title = decodeURIComponent(encodedTitle);
  if (btn) {
    btn.disabled = true;
    btn.textContent = '抓取解析中…';
  }

  try {
    const data = await api('/api/articles/ingest-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title })
    });
    closeModal();
    openReader(data.article_id);
  } catch (e) {
    alert(`导入外刊失败: ${e.message}`);
    if (btn) {
      btn.disabled = false;
      btn.textContent = '📥 导入精读';
    }
  }
}


export function openModal() {
  document.getElementById('modal-overlay')?.classList.add('open');
  switchImportTab('text');
}

export function closeModal() {
  document.getElementById('modal-overlay')?.classList.remove('open');
}

export async function submitActiveImport() {
  if (currentImportTab === 'text') {
    await submitImport();
  } else if (currentImportTab === 'url') {
    const url = document.getElementById('imp-url-input').value.trim();
    const title = document.getElementById('imp-url-title').value.trim();
    if (!url) { alert('请输入有效的德语网页链接'); return; }
    const btn = document.getElementById('import-btn');
    btn.textContent = '抓取解析中…'; btn.disabled = true;
    try {
      const data = await api('/api/articles/ingest-url', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url, title })
      });
      closeModal();
      document.getElementById('imp-url-input').value = '';
      document.getElementById('imp-url-title').value = '';
      openReader(data.article_id);
    } catch (e) {
      alert('抓取失败，请检查网址是否为公开德语网页，或直接复制文本导入');
    } finally {
      btn.textContent = '开始阅读'; btn.disabled = false;
    }
  } else if (currentImportTab === 'file') {
    const text = document.getElementById('imp-text').value.trim();
    if (text) {
      await submitImport();
    } else {
      document.getElementById('file-input')?.click();
    }
  }
}

export function handleFileSelect(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  readFileContent(file);
  e.target.value = '';
}

function readFileContent(file) {
  const reader = new FileReader();
  reader.onload = function(evt) {
    const text = evt.target.result;
    const title = file.name.replace(/\.[^/.]+$/, "");
    document.getElementById('imp-title').value = title;
    document.getElementById('imp-text').value = text;
    switchImportTab('text');
  };
  reader.readAsText(file, "UTF-8");
}

export function setupDropzone() {
  const dz = document.getElementById('dropzone');
  if (!dz) return;
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evtName => {
    dz.addEventListener(evtName, (e) => { e.preventDefault(); e.stopPropagation(); });
  });
  dz.addEventListener('dragover', () => dz.classList.add('dragover'));
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', (e) => {
    dz.classList.remove('dragover');
    const file = e.dataTransfer?.files?.[0];
    if (file) readFileContent(file);
  });
}

export async function submitImport() {
  const text  = document.getElementById('imp-text').value.trim();
  const title = document.getElementById('imp-title').value.trim() || '未命名文稿';
  if (!text) { alert('请输入德语文本'); return; }
  const btn = document.getElementById('import-btn');
  btn.textContent = '处理中…'; btn.disabled = true;
  try {
    const data = await api('/api/articles/ingest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title, raw_text: text })
    });
    closeModal();
    document.getElementById('imp-text').value  = '';
    document.getElementById('imp-title').value = '';
    openReader(data.article_id);
  } catch {
    alert('导入失败');
  } finally {
    btn.textContent = '开始阅读';
    btn.disabled = false;
  }
}

// ── Global Hotkeys ───────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  const isEditing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  const isModalOpen = document.getElementById('modal-overlay')?.classList.contains('open');

  if (e.key === 'Escape') {
    clearCefrFocus();
    closeDrawer();
    closeModal();
    return;
  }

  if (isEditing || isModalOpen) return;

  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const drawer = document.getElementById('drawer');
    if (drawer?.classList.contains('open')) {
      e.preventDefault();
      saveVocab();
      return;
    }
  }

  const isReader = document.getElementById('view-reader')?.classList.contains('active');
  const isCards = document.getElementById('view-cards')?.classList.contains('active');
  const isProgress = document.getElementById('view-progress')?.classList.contains('active');

  if (e.code === 'Space') {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.toggle();
    } else if (isCards) {
      e.preventDefault();
      toggleDeckFlip();
    }
  } else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.next();
    } else if (isCards) {
      stepDeck(1);
    } else if (isProgress) {
      nextFolioPage();
    }
  } else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.prev();
    } else if (isCards) {
      stepDeck(-1);
    } else if (isProgress) {
      prevFolioPage();
    }
  } else if (e.key === 'r' || e.key === 'R') {
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.replay();
    }
  }

  if (isReader && (e.key === 'j' || e.key === 'k')) {
    const tokens = Array.from(document.querySelectorAll('.tok'));
    if (!tokens.length) return;
    const curIndex = tokens.findIndex(el => el.classList.contains('sel'));
    let nextIndex = 0;
    if (e.key === 'j') {
      nextIndex = curIndex < tokens.length - 1 ? curIndex + 1 : 0;
    } else {
      nextIndex = curIndex > 0 ? curIndex - 1 : tokens.length - 1;
    }
    tokens[nextIndex]?.click();
    tokens[nextIndex]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
});

// ── Mount All Interactive Handlers to Window for HTML Compatibility ─────────
Object.assign(window, {
  // Navigation & Core
  show,
  openModal,
  closeModal,
  switchImportTab,
  submitActiveImport,
  handleFileSelect,
  submitImport,
  selectFeedSource,
  loadFeedItems,
  ingestFeedItem,

  // Reader & Token Inspector
  openReader,
  inspect,
  toggleCefrFocus,
  clearCefrFocus,
  switchDrawerTab,
  openDrawer,
  closeDrawer,
  analyzeGrammar,
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

  // Leporello Folio
  switchFolioPage,
  prevFolioPage,
  nextFolioPage,
  loadProgress,

  // Cloze
  openClozeModal,
  closeClozeModal,
  switchClozeMode,
  revealClozeHints,
  resetClozeExercise,
  submitClozeExercise,
  handleClozeKey,

  // Player
  ShadowPlayer
});

// ── PWA Service Worker Registration ──────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// ── Application Initialization ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadArticles();
  refreshCardCounters();
  applyTypography();
  setupDropzone();
  setupSelectionTooltip();
  ShadowPlayer.init();
});
