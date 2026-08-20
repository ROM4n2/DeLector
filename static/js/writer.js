/* DeLector - Writing Desk (Schreibwerkstatt) & Grammar Polish */
'use strict';

import { api, esc } from './core.js';
import { refreshCardCounters } from './reader.js';
import { Companion } from './companion.js';

let currentEssayId = null;
let currentAnalysis = null;
let selectedSpanRef = null;
let analyzeDebounceTimer = null;

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

// ── DeepSeek AI Polish Entire Essay ─────────────────────────────────────────
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
    const res = await api('/api/writing/ai-polish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });

    if (res && res.result) {
      const { corrected_text, notes_zh } = res.result;

      if (corrected_text && corrected_text !== text) {
        textArea.value = corrected_text;
        updateWriterStats(corrected_text);
        analyzeWriterText(true);
      }

      const detailEl = document.getElementById('writer-err-detail');
      if (detailEl && notes_zh && notes_zh.length > 0) {
        detailEl.innerHTML = `
          <div class="writer-ai-notes-card">
            <div class="sidebar-section-title">✨ DeepSeek AI 润色建议与点评</div>
            <div class="writer-ai-notes-list">
              ${notes_zh.map(n => `<div class="writer-ai-note-item">💡 ${esc(n)}</div>`).join('')}
            </div>
            ${corrected_text && corrected_text !== text ? '<div class="writer-ai-note-tip">✓ 已将润色后的德文更新至编辑框并重新分析。</div>' : ''}
          </div>
        `;
      }
    }
  } catch (err) {
    console.error('[Writer] AI Polish failed:', err);
    alert('AI 润色请求失败：' + (err.message || err));
  } finally {
    if (aiBtn) {
      aiBtn.disabled = false;
      aiBtn.innerHTML = origBtnText;
    }
  }
}
