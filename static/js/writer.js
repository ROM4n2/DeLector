/* DeLector - Writing Desk (Schreibwerkstatt) & Grammar Polish */
'use strict';

import { api, esc } from './core.js';
import { refreshCardCounters } from './reader.js';
import { Companion } from './companion.js';

let currentEssayId = null;
let currentAnalysis = null;
let selectedSpanRef = null;
let analyzeDebounceTimer = null;

let polishState = {
  original: '',
  corrected: '',
  hunks: [],
  notes_zh: [],
  error_count: 0
};

// ── Error Type Labels & Badges ──────────────────────────────────────────────
const ERROR_TYPE_LABELS = {
  artikel: '冠词 / 性数格一致',
  kasus: '介词支配格错误',
  praeposition: '固定介词搭配',
  andere: '语法与拼写规范'
};

function getErrorTypeLabel(type) {
  return ERROR_TYPE_LABELS[type] || '语法考点';
}

// ── Sidebar Tab Navigation ──────────────────────────────────────────────────
export function switchWriterPanelTab(tab) {
  const isDiag = tab === 'diag';
  const btnDiag = document.getElementById('wtab-btn-diag');
  const btnVersions = document.getElementById('wtab-btn-versions');
  const paneDiag = document.getElementById('wpane-diag');
  const paneVersions = document.getElementById('wpane-versions');

  if (btnDiag) btnDiag.classList.toggle('active', isDiag);
  if (btnVersions) btnVersions.classList.toggle('active', !isDiag);

  if (paneDiag) {
    paneDiag.classList.toggle('active', isDiag);
    paneDiag.classList.toggle('hidden', !isDiag);
  }
  if (paneVersions) {
    paneVersions.classList.toggle('active', !isDiag);
    paneVersions.classList.toggle('hidden', isDiag);
  }

  if (!isDiag) {
    loadEssayVersions();
  }
}

// ── Word & Sentence Stats Helper ────────────────────────────────────────────
function updateWriterStats(text) {
  const el = document.getElementById('writer-stats-counter');
  if (!el) return;
  const words = (text || '').trim().split(/\s+/).filter(w => /[a-zA-ZäöüßÄÖÜ]/.test(w));
  const sents = (text || '').split(/[.!?]+/).filter(s => s.trim().length > 0);
  el.textContent = `${words.length} 词 · ${sents.length} 句`;
}

// ── Essay Library Loading & Rendering ───────────────────────────────────────
export async function loadWriterEssays() {
  const listEl = document.getElementById('writer-essay-list');
  if (!listEl) return;

  try {
    const rows = await api('/api/essays');
    if (!rows || rows.length === 0) {
      listEl.innerHTML = '<div class="writer-empty-tip">暂无保存的作文草稿。在上方输入德语文本后点击「保存作文」即可收录。</div>';
      return;
    }

    listEl.innerHTML = rows.map(r => {
      const isCurrent = r.id === currentEssayId;
      const cefrBadge = r.cefr_level ? `<span class="cefr-badge badge-${r.cefr_level}">${r.cefr_level}</span>` : '';
      const dateStr = (r.updated_at || r.created_at || '').slice(0, 10);
      const errPill = r.error_count > 0
        ? `<span class="writer-essay-err-pill has-err">⚠️ ${r.error_count} 处待纠错</span>`
        : `<span class="writer-essay-err-pill no-err">✓ 表达流畅</span>`;

      return `
        <div class="writer-essay-item ${isCurrent ? 'active' : ''}" onclick="openWriterEssay(${r.id})">
          <div class="writer-essay-item-main">
            <div class="writer-essay-item-title">${esc(r.title || '未命名作文')}</div>
            <div class="writer-essay-item-meta">
              ${cefrBadge}
              ${errPill}
              <span class="writer-essay-date">${dateStr}</span>
            </div>
          </div>
          <div class="writer-essay-item-actions" onclick="event.stopPropagation()">
            <button class="btn btn-ghost btn-xs btn-del" onclick="deleteWriterEssay(${r.id}, event)" title="删除作文">🗑️</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('[Writer] Failed to load essays:', err);
    listEl.innerHTML = '<div class="writer-empty-tip">加载作文列表失败</div>';
  }
}

// ── Open Essay Draft ────────────────────────────────────────────────────────
export async function openWriterEssay(id) {
  try {
    const essay = await api(`/api/essays/${id}`);
    currentEssayId = essay.id;
    selectedSpanRef = null;

    const titleInput = document.getElementById('writer-title');
    const textArea = document.getElementById('writer-text');
    if (titleInput) titleInput.value = essay.title || '';
    if (textArea) textArea.value = essay.content || '';

    updateWriterStats(essay.content);

    let analysis = essay.analysis_json;
    if (typeof analysis === 'string') {
      try { analysis = JSON.parse(analysis); } catch (e) { analysis = null; }
    }

    if (analysis && analysis.sentences) {
      currentAnalysis = analysis;
      renderWriterReport(analysis);
    } else {
      analyzeWriterText(true);
    }

    // Reset error detail card
    resetErrorDetailView();
    loadWriterEssays();
    loadEssayVersions();
  } catch (err) {
    console.error('[Writer] Failed to open essay:', err);
    alert('打开作文失败：' + (err.message || err));
  }
}

// ── Clear / New Essay Draft ─────────────────────────────────────────────────
export function clearWriterForm() {
  currentEssayId = null;
  currentAnalysis = null;
  selectedSpanRef = null;

  const titleInput = document.getElementById('writer-title');
  const textArea = document.getElementById('writer-text');
  if (titleInput) titleInput.value = '';
  if (textArea) textArea.value = '';

  updateWriterStats('');

  const renderEl = document.getElementById('writer-render');
  if (renderEl) {
    renderEl.innerHTML = '<div class="writer-empty-tip">在上方输入德语文本后，系统将在此处以彩色波浪线下划线实时标出冠词、格位与介词错误。</div>';
  }

  const statusPill = document.getElementById('writer-render-status');
  if (statusPill) {
    statusPill.textContent = '等待输入';
    statusPill.className = 'writer-status-pill';
  }

  const cefrBox = document.getElementById('writer-cefr');
  if (cefrBox) {
    cefrBox.innerHTML = '<div class="writer-cefr-level">CEFR —</div><div class="writer-cefr-desc">输入德语作文以评估词汇难度与错误率</div>';
  }

  const versionListEl = document.getElementById('writer-version-list');
  if (versionListEl) {
    versionListEl.innerHTML = '<div class="writer-empty-tip">暂无版本记录（请先保存或打开作文）</div>';
  }

  resetErrorDetailView();
  loadWriterEssays();
}

// ── Reset Error Detail Box ──────────────────────────────────────────────────
function resetErrorDetailView() {
  const detailEl = document.getElementById('writer-err-detail');
  if (detailEl) {
    detailEl.innerHTML = `
      <div class="writer-err-placeholder">
        <div style="font-size:2rem;margin-bottom:0.5rem;">✍️</div>
        <div>点击左侧诊断视图中的<b>彩色波浪下划线</b>，查看错误成因与修正建议，并一键收录为 Anki 语法卡。</div>
      </div>
    `;
  }
}

// ── Realtime Text Analysis ──────────────────────────────────────────────────
export function analyzeWriterText(immediate = false) {
  const textInput = document.getElementById('writer-text');
  if (!textInput) return;
  const text = textInput.value;
  updateWriterStats(text);

  if (!text.trim()) {
    clearWriterForm();
    return;
  }

  if (analyzeDebounceTimer) {
    clearTimeout(analyzeDebounceTimer);
    analyzeDebounceTimer = null;
  }

  const performAnalysis = async () => {
    try {
      const a = await api('/api/writing/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });
      currentAnalysis = a;
      renderWriterReport(a);
    } catch (err) {
      console.error('[Writer] Analysis failed:', err);
    }
  };

  if (immediate) {
    performAnalysis();
  } else {
    analyzeDebounceTimer = setTimeout(performAnalysis, 350);
  }
}

// ── Render Analysis & Highlighted Text ──────────────────────────────────────
function renderWriterReport(a) {
  // Update status pill
  const statusPill = document.getElementById('writer-render-status');
  if (statusPill) {
    if (a.error_count === 0) {
      statusPill.textContent = '✓ 表达流畅 · 0 处待改';
      statusPill.className = 'writer-status-pill status-clean';
    } else {
      statusPill.textContent = `⚠️ 发现 ${a.error_count} 处语法疑点`;
      statusPill.className = 'writer-status-pill status-warn';
    }
  }

  // Update CEFR widget
  const cefrBox = document.getElementById('writer-cefr');
  if (cefrBox && a.cefr) {
    const lvl = a.cefr.recommended_level || 'A1';
    const wordCount = a.cefr.word_count || 0;
    cefrBox.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.35rem;">
        <span class="cefr-badge badge-${lvl}" style="font-size:0.9rem;padding:4px 10px;">${lvl} 估测</span>
        <span style="font-size:0.75rem;color:var(--pencil);font-family:var(--mono);">${wordCount} 词 · ${a.sentences.length} 句</span>
      </div>
      <div class="writer-cefr-desc">${esc(a.cefr.note_zh || '基于词汇频率与语法复杂度综合估测')}</div>
    `;
  }

  // Render Highlighted HTML
  const renderEl = document.getElementById('writer-render');
  if (!renderEl) return;

  if (!a.sentences || a.sentences.length === 0) {
    renderEl.innerHTML = '<div class="writer-empty-tip">未能识别到有效句子</div>';
    return;
  }

  const html = a.sentences.map((s, sentIdx) => {
    const sentHtml = buildSentenceHighlightedText(s.text, s.spans || [], sentIdx);
    return `
      <div class="writer-sent-block" data-sent-idx="${sentIdx}">
        <span class="writer-sent-num">${sentIdx + 1}</span>
        <span class="writer-sent-content">${sentHtml}</span>
      </div>
    `;
  }).join('');

  renderEl.innerHTML = html;
}

// ── Build Inline Spans with Wavy Underlines ─────────────────────────────────
function buildSentenceHighlightedText(text, spans, sentIdx) {
  if (!spans || spans.length === 0) {
    return esc(text);
  }

  const sorted = [...spans].sort((x, y) => x.start - y.start);
  let out = '';
  let pos = 0;

  sorted.forEach((sp, spanIdx) => {
    if (sp.start > pos) {
      out += esc(text.slice(pos, sp.start));
    }
    const isSelected = selectedSpanRef &&
      selectedSpanRef.sentence_id === sentIdx &&
      selectedSpanRef.span_index === spanIdx;

    out += `<mark class="writer-err-underline err-${sp.error_type} ${isSelected ? 'active-span' : ''}" ` +
      `data-sent="${sentIdx}" data-span="${spanIdx}" ` +
      `onclick="selectWriterSpan(${sentIdx}, ${spanIdx})" ` +
      `title="${esc(sp.explanation_zh)}">` +
      esc(text.slice(sp.start, sp.end)) +
      `</mark>`;
    pos = sp.end;
  });

  if (pos < text.length) {
    out += esc(text.slice(pos));
  }

  return out;
}

// ── Select Error Span to Display Details in Sidebar ─────────────────────────
export function selectWriterSpan(arg1, arg2) {
  if (!currentAnalysis || !currentAnalysis.sentences) return;

  let sentIdx = -1;
  let spanIdx = -1;

  if (typeof arg1 === 'number' && typeof arg2 === 'number') {
    // Check if passed directly as (sentIdx, spanIdx)
    if (currentAnalysis.sentences[arg1] &&
        currentAnalysis.sentences[arg1].spans &&
        currentAnalysis.sentences[arg1].spans[arg2]) {
      sentIdx = arg1;
      spanIdx = arg2;
    } else {
      // Fallback matching by character offsets (start, end)
      const start = arg1;
      const end = arg2;
      for (let sIdx = 0; sIdx < currentAnalysis.sentences.length; sIdx++) {
        const s = currentAnalysis.sentences[sIdx];
        for (let spIdx = 0; spIdx < (s.spans || []).length; spIdx++) {
          const sp = s.spans[spIdx];
          if (sp.start === start && sp.end === end) {
            sentIdx = sIdx;
            spanIdx = spIdx;
            break;
          }
        }
        if (sentIdx !== -1) break;
      }
    }
  }

  if (sentIdx === -1 || spanIdx === -1) return;

  const s = currentAnalysis.sentences[sentIdx];
  const sp = s.spans[spanIdx];
  selectedSpanRef = {
    essay_id: currentEssayId,
    sentence_id: sentIdx,
    span_index: spanIdx,
    span: sp,
    sentenceText: s.text
  };

  // Update active style on all marks
  document.querySelectorAll('.writer-err-underline').forEach(el => {
    const sAttr = parseInt(el.getAttribute('data-sent'), 10);
    const spAttr = parseInt(el.getAttribute('data-span'), 10);
    el.classList.toggle('active-span', sAttr === sentIdx && spAttr === spanIdx);
  });

  // Render detail in sidebar
  const detailEl = document.getElementById('writer-err-detail');
  if (!detailEl) return;

  detailEl.innerHTML = `
    <div class="writer-err-card err-card-${sp.error_type}">
      <div class="err-card-header">
        <span class="err-type-badge err-bg-${sp.error_type}">
          ${getErrorTypeLabel(sp.error_type)}
        </span>
      </div>
      <div class="err-explanation">
        ${esc(sp.explanation_zh)}
      </div>
      <div class="err-suggest-box">
        <span class="err-box-title">推荐修正形式：</span>
        <div class="correction-chip">${esc(sp.corrected_form)}</div>
      </div>
      <div class="err-context-box">
        <span class="err-box-title">完整原句语境：</span>
        <div class="err-context-text">${esc(s.text)}</div>
      </div>
      <div class="err-action-box">
        <button class="btn btn-accent btn-block" id="writer-save-card-btn" onclick="saveWriterErrorAsCard()">
          ＋ 一键存为 Anki 语法考点卡
        </button>
      </div>
    </div>
  `;
}

// ── Save Error as Anki Grammar Card ─────────────────────────────────────────
export async function saveWriterErrorAsCard() {
  if (!selectedSpanRef) return;

  const btn = document.getElementById('writer-save-card-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '保存中...';
  }

  try {
    // If the essay has not been saved yet, auto-create it first
    if (!currentEssayId) {
      const title = document.getElementById('writer-title')?.value.trim() || '未命名作文草稿';
      const content = document.getElementById('writer-text')?.value.trim() || selectedSpanRef.sentenceText;
      const essayRes = await api('/api/essays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content })
      });
      currentEssayId = essayRes.id;
      selectedSpanRef.essay_id = currentEssayId;
      loadWriterEssays();
    }

    await api('/api/writing/cards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        essay_id: currentEssayId,
        sentence_id: selectedSpanRef.sentence_id,
        span_index: selectedSpanRef.span_index
      })
    });

    if (btn) {
      btn.textContent = '✓ 已存为 Anki 语法卡';
      btn.classList.remove('btn-accent');
      btn.classList.add('btn-secondary');
    }

    refreshCardCounters();
    Companion.celebrate('card_grammar');
  } catch (err) {
    console.error('[Writer] Failed to save grammar card:', err);
    if (btn) {
      btn.disabled = false;
      btn.textContent = '重试存为语法卡';
    }
    alert('保存语法卡失败：' + (err.message || err));
  }
}

// ── Save / Update Essay ─────────────────────────────────────────────────────
export async function saveWriterEssay() {
  const titleInput = document.getElementById('writer-title');
  const textArea = document.getElementById('writer-text');
  const saveBtn = document.getElementById('writer-save-btn');

  const content = (textArea?.value || '').trim();
  if (!content) {
    alert('请输入德语作文内容后再保存。');
    return;
  }

  const title = (titleInput?.value || '').trim() || '未命名作文草稿';
  const origBtnText = saveBtn ? saveBtn.innerHTML : '';
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '💾 保存中...';
  }

  try {
    let res;
    if (currentEssayId) {
      res = await api(`/api/essays/${currentEssayId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content })
      });
    } else {
      res = await api('/api/essays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content })
      });
      currentEssayId = res.id;
    }

    currentAnalysis = res.analysis_json;
    renderWriterReport(res.analysis_json);
    loadWriterEssays();
    loadEssayVersions();

    if (saveBtn) {
      saveBtn.innerHTML = '✓ 已保存';
      setTimeout(() => {
        saveBtn.disabled = false;
        saveBtn.innerHTML = origBtnText;
      }, 1500);
    }
  } catch (err) {
    console.error('[Writer] Save essay failed:', err);
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = origBtnText;
    }
    alert('保存作文失败：' + (err.message || err));
  }
}

// ── Delete Essay Draft ──────────────────────────────────────────────────────
export async function deleteWriterEssay(id, evt) {
  if (evt) evt.stopPropagation();
  if (!confirm('确定要删除这篇作文草稿吗？')) return;

  try {
    await api(`/api/essays/${id}`, { method: 'DELETE' });
    if (currentEssayId === id) {
      clearWriterForm();
    } else {
      loadWriterEssays();
    }
  } catch (err) {
    console.error('[Writer] Delete essay failed:', err);
    alert('删除作文失败：' + (err.message || err));
  }
}

// ── Word-level LCS Diff Helper for Agent Review ─────────────────────────────
function renderWordDiff(oldSent, newSent) {
  if (!oldSent && !newSent) return { oldHtml: '', newHtml: '' };
  if (!oldSent) {
    return {
      oldHtml: '<div class="diff-empty">(无对应原句 / 新增内容)</div>',
      newHtml: `<div class="diff-sent diff-ins-block"><span class="diff-prefix">+</span>${esc(newSent)}</div>`
    };
  }
  if (!newSent) {
    return {
      oldHtml: `<div class="diff-sent diff-del-block"><span class="diff-prefix">-</span>${esc(oldSent)}</div>`,
      newHtml: '<div class="diff-empty">(建议删除此句)</div>'
    };
  }

  const w1 = oldSent.split(/(\s+|[.,!?;:„"“'«»()—–-])/).filter(Boolean);
  const w2 = newSent.split(/(\s+|[.,!?;:„"“'«»()—–-])/).filter(Boolean);
  const n = w1.length;
  const m = w2.length;

  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < m; j++) {
      if (w1[i] === w2[j]) {
        dp[i + 1][j + 1] = dp[i][j] + 1;
      } else {
        dp[i + 1][j + 1] = dp[i][j] > dp[i][j + 1] ? dp[i][j] : dp[i][j + 1];
      }
    }
  }

  let i = n;
  let j = m;
  const out1 = [];
  const out2 = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && w1[i - 1] === w2[j - 1]) {
      out1.push(esc(w1[i - 1]));
      out2.push(esc(w2[j - 1]));
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      out2.push(`<mark class="diff-token-ins">${esc(w2[j - 1])}</mark>`);
      j--;
    } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
      out1.push(`<mark class="diff-token-del">${esc(w1[i - 1])}</mark>`);
      i--;
    }
  }

  out1.reverse();
  out2.reverse();
  return {
    oldHtml: `<div class="diff-sent"><span class="diff-prefix">-</span>${out1.join('')}</div>`,
    newHtml: `<div class="diff-sent"><span class="diff-prefix">+</span>${out2.join('')}</div>`
  };
}

// ── AI Polish Review Modal & Diff Review State Machine ───────────────────────
export function openPolishOverlay() {
  const overlay = document.getElementById('polish-overlay');
  if (overlay) overlay.classList.remove('hidden');
}

export function closePolishOverlay() {
  const overlay = document.getElementById('polish-overlay');
  if (overlay) overlay.classList.add('hidden');
}

export function setPolishHunk(idx, isAccepted) {
  if (!polishState.hunks || !polishState.hunks[idx]) return;
  polishState.hunks[idx].accepted = isAccepted;
  renderPolishReview();
}

export function togglePolishHunk(idx) {
  if (!polishState.hunks || !polishState.hunks[idx]) return;
  polishState.hunks[idx].accepted = !polishState.hunks[idx].accepted;
  renderPolishReview();
}

export function acceptAllPolishHunks() {
  if (!polishState.hunks) return;
  polishState.hunks.forEach(h => { h.accepted = true; });
  renderPolishReview();
}

export function rejectAllPolishHunks() {
  if (!polishState.hunks) return;
  polishState.hunks.forEach(h => { h.accepted = false; });
  renderPolishReview();
}

export function renderPolishReview() {
  const total = polishState.hunks ? polishState.hunks.length : 0;
  const acceptedCount = polishState.hunks ? polishState.hunks.filter(h => h.accepted !== false).length : 0;

  const summaryEl = document.getElementById('polish-hunk-summary');
  if (summaryEl) {
    if (total === 0) {
      summaryEl.innerHTML = '<span>✓ 原文表达流畅，未检测到句式或语法需调整处。</span>';
    } else {
      summaryEl.innerHTML = `<span>共 <b>${total}</b> 处改动 · 已选定应用 <b>${acceptedCount}/${total}</b> 处</span>`;
    }
  }

  const diffListEl = document.getElementById('polish-diff-list');
  if (diffListEl) {
    if (total === 0) {
      diffListEl.innerHTML = '<div class="writer-empty-tip">未发现明显语法错误或句式改动。</div>';
    } else {
      diffListEl.innerHTML = polishState.hunks.map((hunk, idx) => {
        const isAccepted = hunk.accepted !== false;
        
        const oldSents = hunk.old || [];
        const newSents = hunk.new || [];
        const maxLen = Math.max(oldSents.length, newSents.length);
        let oldLinesHtml = '';
        let newLinesHtml = '';

        if (maxLen === 0) {
          oldLinesHtml = '<div class="diff-empty">(无内容)</div>';
          newLinesHtml = '<div class="diff-empty">(无内容)</div>';
        } else {
          for (let k = 0; k < maxLen; k++) {
            const oS = oldSents[k] || '';
            const nS = newSents[k] || '';
            const diffRes = renderWordDiff(oS, nS);
            oldLinesHtml += diffRes.oldHtml;
            newLinesHtml += diffRes.newHtml;
          }
        }

        const hunkTypeLabel = oldSents.length > 0 && newSents.length > 0
          ? '句式与用词润色'
          : (newSents.length > 0 ? '新增句子' : '删除冗余');

        return `
          <div class="diff-hunk ${isAccepted ? 'hunk-accepted' : 'hunk-rejected'}" data-hunk-idx="${idx}">
            <div class="diff-hunk-header">
              <div class="diff-hunk-title">
                <span class="diff-hunk-badge">#${idx + 1}</span>
                <span class="diff-hunk-label">${hunkTypeLabel}</span>
              </div>
              <div class="diff-decision-group">
                <button type="button" class="diff-decision-btn btn-choice-accept ${isAccepted ? 'active' : ''}" onclick="setPolishHunk(${idx}, true)" title="采纳 AI 润色建议">
                  ✓ 采纳润色
                </button>
                <button type="button" class="diff-decision-btn btn-choice-reject ${!isAccepted ? 'active' : ''}" onclick="setPolishHunk(${idx}, false)" title="保留原文字句">
                  ✕ 保留原句
                </button>
              </div>
            </div>
            <div class="diff-grid">
              <div class="diff-side diff-old ${!isAccepted ? 'side-chosen' : 'side-discarded'}" onclick="setPolishHunk(${idx}, false)" title="点击选择保留原句">
                <div class="diff-side-header">
                  <span class="diff-side-label label-old">原句 (Original)</span>
                  ${!isAccepted ? '<span class="diff-chosen-tag">✓ 保留此原句</span>' : ''}
                </div>
                <div class="diff-content">${oldLinesHtml}</div>
              </div>
              <div class="diff-side diff-new ${isAccepted ? 'side-chosen' : 'side-discarded'}" onclick="setPolishHunk(${idx}, true)" title="点击选择采纳 AI 润色">
                <div class="diff-side-header">
                  <span class="diff-side-label label-new">✨ AI 润色 (Korrektur)</span>
                  ${isAccepted ? '<span class="diff-chosen-tag accept-tag">✓ 采纳此润色</span>' : ''}
                </div>
                <div class="diff-content">${newLinesHtml}</div>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }
  }

  const notesEl = document.getElementById('polish-notes');
  if (notesEl) {
    if (polishState.notes_zh && polishState.notes_zh.length > 0) {
      notesEl.classList.remove('hidden');
      notesEl.innerHTML = `
        <div class="sidebar-section-title" style="margin-bottom:0.35rem;font-size:0.75rem;">💡 AI 润色解析与语法点评 (${polishState.notes_zh.length} 条)</div>
        <div class="writer-ai-notes-list">
          ${polishState.notes_zh.map(n => `<div class="writer-ai-note-item">• ${esc(n)}</div>`).join('')}
        </div>
      `;
    } else {
      notesEl.classList.add('hidden');
      notesEl.innerHTML = '';
    }
  }
}

// ── DeepSeek AI Polish Entire Essay with Sentence Diff Review ───────────────
export async function aiPolishEssay() {
  const textArea = document.getElementById('writer-text');
  const text = (textArea?.value || '').trim();

  if (!text) {
    alert('请先在上方输入德语作文文本。');
    return;
  }

  const aiBtn = document.getElementById('writer-ai-btn');
  const origBtnText = aiBtn ? aiBtn.innerHTML : '';
  if (aiBtn) {
    aiBtn.disabled = true;
    aiBtn.innerHTML = '✨ AI 润色中...';
  }

  try {
    // If no current essay, auto-create draft first
    if (!currentEssayId) {
      const title = document.getElementById('writer-title')?.value.trim() || '未命名作文草稿';
      const essayRes = await api('/api/essays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content: text })
      });
      currentEssayId = essayRes.id;
      loadWriterEssays();
    }

    const res = await api('/api/writing/ai-polish/diff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });

    if (res && res.result) {
      const { original, corrected, hunks, notes_zh, error_count } = res.result;
      polishState = {
        original: original || text,
        corrected: corrected || text,
        hunks: (hunks || []).map(h => ({ ...h, accepted: true })),
        notes_zh: notes_zh || [],
        error_count: error_count || 0
      };
      openPolishOverlay();
      renderPolishReview();
    }
  } catch (err) {
    console.error('[Writer] AI Polish Diff failed:', err);
    alert('AI 润色请求失败：' + (err.message || err));
  } finally {
    if (aiBtn) {
      aiBtn.disabled = false;
      aiBtn.innerHTML = origBtnText;
    }
  }
}

// ── Apply Selected AI Polish Hunks ──────────────────────────────────────────
export async function applyPolishChanges() {
  if (!polishState.hunks) return;
  const accepted_indices = polishState.hunks
    .map((h, idx) => (h.accepted !== false ? idx : -1))
    .filter(idx => idx !== -1);

  const applyBtn = document.getElementById('btn-apply-polish');
  const origText = applyBtn ? applyBtn.innerHTML : '';
  if (applyBtn) {
    applyBtn.disabled = true;
    applyBtn.innerHTML = '应用中...';
  }

  try {
    if (!currentEssayId) {
      const title = document.getElementById('writer-title')?.value.trim() || '未命名作文草稿';
      const content = polishState.original;
      const essayRes = await api('/api/essays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content })
      });
      currentEssayId = essayRes.id;
    }

    const res = await api('/api/writing/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        essay_id: currentEssayId,
        original_text: polishState.original,
        corrected_text: polishState.corrected,
        accepted_indices
      })
    });

    const textArea = document.getElementById('writer-text');
    if (textArea) textArea.value = res.content;
    updateWriterStats(res.content);

    currentAnalysis = res.analysis_json;
    renderWriterReport(res.analysis_json);

    closePolishOverlay();
    loadEssayVersions();
    loadWriterEssays();

    Companion.celebrate('card_grammar');
  } catch (err) {
    console.error('[Writer] Apply polish failed:', err);
    alert('应用润色更改失败：' + (err.message || err));
  } finally {
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.innerHTML = origText;
    }
  }
}

// ── Essay Version Snapshots Management ──────────────────────────────────────
export async function loadEssayVersions() {
  const listEl = document.getElementById('writer-version-list');
  if (!listEl) return;

  if (!currentEssayId) {
    listEl.innerHTML = '<div class="writer-empty-tip">请先打开或保存一篇作文以查看版本快照</div>';
    return;
  }

  try {
    const rows = await api(`/api/essays/${currentEssayId}/versions`);
    if (!rows || rows.length === 0) {
      listEl.innerHTML = '<div class="writer-empty-tip">暂无快照记录</div>';
      return;
    }

    listEl.innerHTML = rows.map(v => {
      const isCheckpoint = (v.message || '').startsWith('恢复到版本');
      const errPill = v.error_count > 0
        ? `<span class="writer-essay-err-pill has-err">⚠️ ${v.error_count} 处疑点</span>`
        : `<span class="writer-essay-err-pill no-err">✓ 0 错误</span>`;
      const timeStr = (v.created_at || '').replace('T', ' ').slice(0, 19);

      return `
        <div class="version-item ${isCheckpoint ? 'version-checkpoint' : ''}">
          <div class="version-header">
            <span class="version-id">#v${v.id}</span>
            ${errPill}
          </div>
          <div class="version-msg">${esc(v.message || '快照')}</div>
          <div class="version-meta">
            <span class="version-time">${timeStr}</span>
            <button class="btn btn-ghost btn-xs version-restore-btn" onclick="restoreEssayVersion(${v.id})" title="恢复至此快照">↩ 恢复</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('[Writer] Failed to load essay versions:', err);
    listEl.innerHTML = '<div class="writer-empty-tip">加载快照历史失败</div>';
  }
}

export async function saveEssayVersion() {
  if (!currentEssayId) {
    await saveWriterEssay();
    if (!currentEssayId) return;
  }

  const msgInput = document.getElementById('writer-version-msg');
  const msg = (msgInput?.value || '').trim();

  try {
    await api(`/api/essays/${currentEssayId}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg || '手动保存' })
    });
    if (msgInput) msgInput.value = '';
    loadEssayVersions();
  } catch (err) {
    console.error('[Writer] Save version failed:', err);
    alert('保存快照失败：' + (err.message || err));
  }
}

export async function restoreEssayVersion(versionId) {
  if (!currentEssayId) return;
  if (!confirm('确定要恢复到此版本快照吗？当前的未保存修改将自动保存为一个恢复前快照。')) return;

  try {
    const res = await api(`/api/essays/${currentEssayId}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: versionId })
    });

    const textArea = document.getElementById('writer-text');
    if (textArea) textArea.value = res.content;
    updateWriterStats(res.content);

    currentAnalysis = res.analysis_json;
    renderWriterReport(res.analysis_json);

    loadEssayVersions();
    loadWriterEssays();
  } catch (err) {
    console.error('[Writer] Restore version failed:', err);
    alert('恢复版本失败：' + (err.message || err));
  }
}
