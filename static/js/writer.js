/* DeLector - Writing Desk (Schreibwerkstatt) & Grammar Polish */
'use strict';

import { api, esc } from './core.js';
import { refreshCardCounters } from './reader.js';
import { Companion } from './companion.js';
import * as A1Writer from './a1_writer.js';
export {
  switchWriterMode,
  loadA1WritingData,
  populateA1Selectors,
  selectA1Formular,
  prevA1Formular,
  nextA1Formular,
  randomA1Formular,
  renderA1Formular,
  checkA1Formular,
  resetA1Formular,
  selectA1Email,
  prevA1Email,
  nextA1Email,
  randomA1Email,
  renderA1Email,
  onA1EmailInput,
  diagnoseA1Email,
  applyA1EmailTemplate,
  clearA1Email,
} from './a1_writer.js';
export * from './a1_writer.js';

let currentEssayId = null;
let currentAnalysis = null;
let selectedSpanRef = null;
let analyzeDebounceTimer = null;
let isComposing = false;
let inlayEnabled = !/Android/i.test(navigator.userAgent);

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

export function getErrorTypeLabel(type) {
  return ERROR_TYPE_LABELS[type] || '语法考点';
}

// ── Sidebar Tab Navigation (v4.2.0) ─────────────────────────────────────────
const WRITER_TABS = ['diag', 'problems', 'versions'];

export function switchWriterPanelTab(tab) {
  WRITER_TABS.forEach(t => {
    const btn = document.getElementById(`wtab-btn-${t}`);
    const pane = document.getElementById(`wpane-${t}`);
    const isActive = t === tab;
    if (btn) btn.classList.toggle('active', isActive);
    if (pane) {
      pane.classList.toggle('active', isActive);
      pane.classList.toggle('hidden', !isActive);
    }
  });

  if (tab === 'versions') {
    loadEssayVersions();
  } else if (tab === 'problems' && currentAnalysis) {
    renderProblemsPanel(currentAnalysis);
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

// ── Text & Editor Helpers (v4.0.0 IDE Inline Editor) ─────────────────────────
export function editorText() {
  const el = document.getElementById('ide-editor');
  if (!el) return '';
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
  let text = '';
  let node;
  while ((node = walker.nextNode())) {
    text += node.nodeValue;
  }
  return text.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
}

export function setEditorText(text) {
  const el = document.getElementById('ide-editor');
  if (!el) return;
  el.textContent = text;
  updateWriterStats(text);
}

export function clearEditorText() {
  const el = document.getElementById('ide-editor');
  if (el) el.innerHTML = '';
  clearWriterForm();
}

// ── Caret Offset Capture & Restoration (TreeWalker) ─────────────────────────
function captureCaret(rootEl) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (!rootEl.contains(range.startContainer)) return null;

  let offset = 0;
  const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null, false);
  let node;
  while ((node = walker.nextNode())) {
    if (node === range.startContainer) {
      offset += range.startOffset;
      break;
    }
    offset += node.nodeValue.length;
  }
  return offset;
}

function restoreCaret(rootEl, offset) {
  if (offset === null || offset === undefined) return;
  const sel = window.getSelection();
  if (!sel) return;

  const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null, false);
  let currentOffset = 0;
  let targetNode = null;
  let targetOffset = 0;
  let lastNode = null;
  let node;

  while ((node = walker.nextNode())) {
    lastNode = node;
    const len = node.nodeValue.length;
    if (currentOffset + len >= offset) {
      targetNode = node;
      targetOffset = Math.max(0, offset - currentOffset);
      break;
    }
    currentOffset += len;
  }

  if (!targetNode && lastNode) {
    targetNode = lastNode;
    targetOffset = lastNode.nodeValue.length;
  }

  if (targetNode) {
    try {
      const range = document.createRange();
      range.setStart(targetNode, Math.min(targetOffset, targetNode.nodeValue.length));
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (e) {
      // Safe fallback
    }
  }
}

// ── Build Inline Spans with Wavy Underlines & Inline Inlay Hints (v4.1.1) ────
export function buildSentenceHighlightedText(text, spans = [], hints = [], sentIdx, options = {}) {
  const { clickable = true, useNativeTitle = false } = options;

  // Map hints by end position
  const hintsByPos = {};
  if (hints && hints.length > 0) {
    hints.forEach((h) => {
      const pos = h.end;
      if (!hintsByPos[pos]) hintsByPos[pos] = [];
      hintsByPos[pos].push(h);
    });
  }

  function renderHintsAt(pos) {
    const list = hintsByPos[pos];
    if (!list || list.length === 0) return '';
    return list.map((h) => {
      const label = h.label.includes('[') ? h.label.slice(h.label.indexOf('[')) : h.label;
      const hintClass = h.type === 'prep_case' ? 'inlay-prep' : 'inlay-np';
      return `<span class="inlay-hint ${hintClass}" contenteditable="false" data-hint="${esc(label)}" title="${esc(h.label)}"></span>`;
    }).join('');
  }

  if (!spans || spans.length === 0) {
    let out = '';
    let pos = 0;
    const hintPositions = Object.keys(hintsByPos).map(Number).sort((a, b) => a - b);
    hintPositions.forEach((p) => {
      if (p > pos) {
        out += esc(text.slice(pos, p));
      }
      out += renderHintsAt(p);
      pos = p;
    });
    if (pos < text.length) {
      out += esc(text.slice(pos));
    }
    return out;
  }

  const sorted = [...spans].sort((x, y) => x.start - y.start);
  let out = '';
  let pos = 0;

  sorted.forEach((sp, spanIdx) => {
    while (pos < sp.start) {
      const candidates = Object.keys(hintsByPos).map(Number).filter(p => p > pos && p <= sp.start);
      if (candidates.length > 0) {
        const nextHint = Math.min(...candidates);
        out += esc(text.slice(pos, nextHint)) + renderHintsAt(nextHint);
        pos = nextHint;
      } else {
        out += esc(text.slice(pos, sp.start));
        pos = sp.start;
      }
    }

    const isSelected = selectedSpanRef &&
      selectedSpanRef.sentence_id === sentIdx &&
      selectedSpanRef.span_index === spanIdx;

    const titleAttr = useNativeTitle ? `title="${esc(sp.explanation_zh)}"` : '';
    const clickAttr = clickable ? `onclick="selectWriterSpan(${sentIdx}, ${spanIdx}, event)"` : '';

    out += `<mark class="writer-err-underline err-${sp.error_type} ${isSelected ? 'active-span' : ''}" ` +
      `data-sent="${sentIdx}" data-span="${spanIdx}" ${clickAttr} ${titleAttr}>`;

    let spanPos = sp.start;
    while (spanPos < sp.end) {
      const candidates = Object.keys(hintsByPos).map(Number).filter(p => p > spanPos && p < sp.end);
      if (candidates.length > 0) {
        const nextHint = Math.min(...candidates);
        out += esc(text.slice(spanPos, nextHint)) + renderHintsAt(nextHint);
        spanPos = nextHint;
      } else {
        out += esc(text.slice(spanPos, sp.end));
        spanPos = sp.end;
      }
    }

    out += `</mark>`;
    out += renderHintsAt(sp.end);
    pos = sp.end;
  });

  while (pos < text.length) {
    const candidates = Object.keys(hintsByPos).map(Number).filter(p => p > pos && p <= text.length);
    if (candidates.length > 0) {
      const nextHint = Math.min(...candidates);
      out += esc(text.slice(pos, nextHint)) + renderHintsAt(nextHint);
      pos = nextHint;
    } else {
      out += esc(text.slice(pos));
      pos = text.length;
    }
  }

  return out;
}

// ── Inlay Hints Toggle (v4.1.1) ────────────────────────────────────────────
export function toggleInlayHints() {
  inlayEnabled = !inlayEnabled;
  const btn = document.getElementById('writer-inlay-toggle');
  if (btn) {
    btn.textContent = inlayEnabled ? '💡 格提示 ON' : '💡 格提示 OFF';
    btn.classList.toggle('btn-ghost', inlayEnabled);
    btn.classList.toggle('btn-secondary', !inlayEnabled);
  }
  const editor = document.getElementById('ide-editor');
  if (editor) {
    editor.classList.toggle('hide-inlays', !inlayEnabled);
  }
}

// 移动端面板首次打开时才自动切到「问题清单」——trigger 文案是「📋 问题与历史」，
// 首屏应兑现这个承诺。之后不再覆盖 tab：用户手动切到 versions，或 openWriterProblem
// 切到 diag 去展示错误详情（v4.4.5 B2），关闭再打开都应保留那个状态。
let writerMobilePanelDidAutoSwitch = false;

export function toggleWriterMobilePanel() {
  const panel = document.getElementById('writer-panel');
  const sheet = document.getElementById('writer-mobile-panel-sheet');
  if (!panel || !sheet) return;

  // trigger 按钮常驻可见，面板已开时再点应该收起 (v4.4.5)
  if (panel.classList.contains('mobile-panel-open')) {
    closeWriterMobilePanel();
    return;
  }

  panel.classList.add('mobile-panel-open');
  sheet.classList.add('open');
  document.body.classList.add('writer-panel-lock');

  if (!writerMobilePanelDidAutoSwitch && currentAnalysis) {
    switchWriterPanelTab('problems');
    writerMobilePanelDidAutoSwitch = true;
  }
}

export function closeWriterMobilePanel() {
  const panel = document.getElementById('writer-panel');
  const sheet = document.getElementById('writer-mobile-panel-sheet');
  if (panel) panel.classList.remove('mobile-panel-open');
  if (sheet) sheet.classList.remove('open');
  document.body.classList.remove('writer-panel-lock');
}

// ── Render Editor Content & Retain Caret ────────────────────────────────────
export function renderEditor(text, a, caretOffset) {
  const editor = document.getElementById('ide-editor');
  if (!editor) return;

  const scrollY = editor.scrollTop;

  if (!text || !text.trim()) {
    editor.innerHTML = '';
    updateAnalysisPanels({ cefr: null, error_count: 0, sentences: [] });
    return;
  }

  if (!a || !a.sentences || a.sentences.length === 0) {
    editor.textContent = text;
    if (caretOffset !== null && caretOffset !== undefined) {
      restoreCaret(editor, caretOffset);
    }
    editor.scrollTop = scrollY;
    updateAnalysisPanels(a || { cefr: null, error_count: 0, sentences: [] });
    return;
  }

  let html = '';
  a.sentences.forEach((s, sentIdx) => {
    const sentHtml = buildSentenceHighlightedText(s.text, s.spans || [], s.hints || [], sentIdx, {
      clickable: true,
      useNativeTitle: false
    });
    html += `<span class="ide-sent-block" data-sent-idx="${sentIdx}">${sentHtml}</span> `;
  });

  editor.innerHTML = html;
  editor.classList.toggle('hide-inlays', !inlayEnabled);

  if (caretOffset !== null && caretOffset !== undefined) {
    restoreCaret(editor, caretOffset);
  }
  editor.scrollTop = scrollY;
  updateAnalysisPanels(a);
}

// ── Update Sidebar Analysis Panels & Sentence Navigation ────────────────────
export function updateAnalysisPanels(a) {
  // 1. Status Pill
  const statusPill = document.getElementById('writer-render-status');
  if (statusPill) {
    const errCount = a?.error_count || 0;
    if (errCount === 0) {
      statusPill.textContent = '✓ 表达流畅 · 0 处待改';
      statusPill.className = 'writer-status-pill status-clean';
    } else {
      statusPill.textContent = `⚠️ 发现 ${errCount} 处语法疑点`;
      statusPill.className = 'writer-status-pill status-warn';
    }
  }

  // 2. CEFR Widget
  const cefrBox = document.getElementById('writer-cefr');
  if (cefrBox) {
    if (a?.cefr) {
      const lvl = a.cefr.recommended_level || 'A1';
      const wordCount = a.cefr.word_count || 0;
      const sentCount = a.sentences ? a.sentences.length : 0;
      cefrBox.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.35rem;">
          <span class="cefr-badge badge-${lvl}" style="font-size:0.9rem;padding:4px 10px;">${lvl} 估测</span>
          <span style="font-size:0.75rem;color:var(--pencil);font-family:var(--mono);">${wordCount} 词 · ${sentCount} 句</span>
        </div>
        <div class="writer-cefr-desc">${esc(a.cefr.note_zh || '基于词汇频率与语法复杂度综合估测')}</div>
      `;
    } else {
      cefrBox.innerHTML = '<div class="writer-cefr-level">CEFR —</div><div class="writer-cefr-desc">输入德语作文以评估词汇难度与错误率</div>';
    }
  }

  // 3. Sentence Navigation List
  const navEl = document.getElementById('writer-sent-nav');
  if (navEl) {
    if (!a?.sentences || a.sentences.length === 0) {
      navEl.innerHTML = '<div class="writer-empty-tip" style="padding:0.5rem 0;">输入文本后生成句子索引</div>';
    } else {
      navEl.innerHTML = a.sentences.map((s, idx) => {
        const errCount = (s.spans || []).length;
        const badge = errCount > 0
          ? `<span class="writer-nav-badge has-err">⚠️ ${errCount} 处疑点</span>`
          : `<span class="writer-nav-badge clean">✓ 正常</span>`;
        const previewText = s.text.length > 28 ? s.text.slice(0, 28) + '...' : s.text;
        return `
          <div class="writer-nav-item" onclick="jumpToSentence(${idx})">
            <span class="writer-nav-idx">${idx + 1}</span>
            <span class="writer-nav-snippet" title="${esc(s.text)}">${esc(previewText)}</span>
            ${badge}
          </div>
        `;
      }).join('');
    }
  }

  // 4. Problems List Panel (v4.2.0)
  renderProblemsPanel(a);
}

// ── Render Problems Panel (v4.2.0) ─────────────────────────────────────────
export function renderProblemsPanel(a) {
  const listEl = document.getElementById('writer-problem-list');
  const statEl = document.getElementById('writer-problems-stat');
  const badgeEl = document.getElementById('wtab-problems-badge');
  if (!listEl) return;

  const errors = [];
  const warnings = [];

  const sentences = a?.sentences || [];
  sentences.forEach((s, sentIdx) => {
    (s.spans || []).forEach((sp, spanIdx) => {
      errors.push({
        severity: 'error',
        error_type: sp.error_type,
        label: getErrorTypeLabel(sp.error_type),
        explanation_zh: sp.explanation_zh,
        corrected_form: sp.corrected_form,
        sentence_idx: sentIdx,
        span_idx: spanIdx,
        sentence_text: s.text,
        start: sp.start,
        end: sp.end
      });
    });

    (s.warnings || []).forEach((w, warnIdx) => {
      warnings.push({
        severity: 'warning',
        error_type: w.error_type || 'twoway',
        label: w.label || '注意：双格介词',
        explanation_zh: w.explanation_zh,
        sentence_idx: sentIdx,
        warning_idx: warnIdx,
        sentence_text: s.text,
        start: w.start,
        end: w.end
      });
    });
  });

  const totalCount = errors.length + warnings.length;

  if (badgeEl) {
    if (totalCount > 0) {
      badgeEl.textContent = totalCount;
      badgeEl.classList.remove('hidden');
    } else {
      badgeEl.classList.add('hidden');
    }
  }

  if (statEl) {
    if (totalCount === 0) {
      statEl.textContent = '0 处问题';
    } else {
      statEl.textContent = `${errors.length} 错误 · ${warnings.length} 提醒`;
    }
  }

  if (totalCount === 0) {
    listEl.innerHTML = '<div class="writer-empty-tip">✓ 未发现语法疑点或搭配提醒</div>';
    return;
  }

  let html = '';

  if (errors.length > 0) {
    html += `
      <div class="writer-problem-group-header">
        <span>❌ 语法疑点 (${errors.length})</span>
        <span>点击跳转 & 修正</span>
      </div>
    `;
    errors.forEach(p => {
      html += `
        <div class="writer-problem-row" onclick="openWriterProblem(${p.sentence_idx}, 'error', ${p.span_idx})">
          <div class="writer-problem-header">
            <span class="writer-problem-badge sev-error">${esc(p.label)}</span>
            <span class="writer-problem-pos">第 ${p.sentence_idx + 1} 句</span>
          </div>
          <div class="writer-problem-expl">${esc(p.explanation_zh)}</div>
          ${p.corrected_form ? `<div class="writer-problem-suggest">推荐修正：<b>${esc(p.corrected_form)}</b></div>` : ''}
          ${p.sentence_text ? `<div class="writer-problem-preview">${esc(p.sentence_text)}</div>` : ''}
        </div>
      `;
    });
  }

  if (warnings.length > 0) {
    html += `
      <div class="writer-problem-group-header">
        <span>⚠️ 介词搭配提醒 (${warnings.length})</span>
        <span>请按动作方向核对</span>
      </div>
    `;
    warnings.forEach(p => {
      html += `
        <div class="writer-problem-row" onclick="openWriterProblem(${p.sentence_idx}, 'warning', ${p.warning_idx})">
          <div class="writer-problem-header">
            <span class="writer-problem-badge sev-warning">${esc(p.label)}</span>
            <span class="writer-problem-pos">第 ${p.sentence_idx + 1} 句</span>
          </div>
          <div class="writer-problem-expl">${esc(p.explanation_zh)}</div>
          ${p.sentence_text ? `<div class="writer-problem-preview">${esc(p.sentence_text)}</div>` : ''}
        </div>
      `;
    });
  }

  listEl.innerHTML = html;
}

// ── Open Problem from Problems Panel (v4.2.0) ──────────────────────────────
export function openWriterProblem(sentenceIdx, kind, idx) {
  jumpToSentence(sentenceIdx);
  if (kind === 'error') {
    // 错误详情卡 #writer-err-detail 在 diag pane 内，必须先切 tab，
    // 否则 selectWriterSpan 把内容写进 display:none 的面板，用户看不到反馈 (v4.4.5)
    switchWriterPanelTab('diag');
    selectWriterSpan(sentenceIdx, idx, null);
  }
  // warning 分支不切 tab：没有详情可渲染，切过去只会露出上一次点击留下的
  // 陈旧错误卡（resetErrorDetailView 只在换文/应用修改时跑）。
  // 留在问题清单，用户重新拉起面板时还在原来那份列表上 (v4.4.5)
}

// ── Jump to Sentence Block & Flash ──────────────────────────────────────────
export function jumpToSentence(sentIdx) {
  const block = document.querySelector(`.ide-sent-block[data-sent-idx="${sentIdx}"]`);
  if (block) {
    block.scrollIntoView({ behavior: 'smooth', block: 'center' });
    block.classList.remove('ide-sent-flash');
    void block.offsetWidth; // Trigger reflow
    block.classList.add('ide-sent-flash');
    setTimeout(() => block.classList.remove('ide-sent-flash'), 1200);
  }
  // 跳转结果（编辑器滚动 + 闪烁）发生在 bottom sheet 背后，
  // 不收起面板等于什么都没发生。桌面端调用只是移除几个不存在的 class，无副作用 (v4.4.5)
  closeWriterMobilePanel();
}

// ── Realtime Text Analysis (Debounced) ──────────────────────────────────────
export function analyzeWriterText(immediate = false) {
  if (isComposing) return;
  const text = editorText();
  updateWriterStats(text);

  if (!text.trim()) {
    clearWriterForm();
    return;
  }

  const editor = document.getElementById('ide-editor');
  const caretOffset = editor ? captureCaret(editor) : null;

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
      renderEditor(text, a, caretOffset);
    } catch (err) {
      console.error('[Writer] Analysis failed:', err);
    }
  };

  if (immediate) {
    performAnalysis();
  } else {
    analyzeDebounceTimer = setTimeout(performAnalysis, 400);
  }
}

// ── Select Error Span to Display Details in Sidebar ─────────────────────────
export function selectWriterSpan(arg1, arg2, evt) {
  if (evt) evt.stopPropagation();
  if (!currentAnalysis || !currentAnalysis.sentences) return;

  let sentIdx = -1;
  let spanIdx = -1;

  if (typeof arg1 === 'number' && typeof arg2 === 'number') {
    if (currentAnalysis.sentences[arg1] &&
        currentAnalysis.sentences[arg1].spans &&
        currentAnalysis.sentences[arg1].spans[arg2]) {
      sentIdx = arg1;
      spanIdx = arg2;
    } else {
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

  // Update active style on marks
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
      <div class="err-action-box" style="display:flex;flex-direction:column;gap:0.5rem;">
        <button class="btn btn-dark btn-block" id="writer-fix-span-btn" onclick="fixSelectedSpan()">
          ✨ 一键应用修正 (${esc(sp.corrected_form)})
        </button>
        <button class="btn btn-secondary btn-block" id="writer-save-card-btn" onclick="saveWriterErrorAsCard()">
          ＋ 存为 Anki 语法考点卡
        </button>
      </div>
    </div>
  `;
}

// ── One-Click Correction in Inline IDE Editor (v4.0.0) ──────────────────────
export function fixSelectedSpan() {
  if (!selectedSpanRef || !currentAnalysis || !currentAnalysis.sentences) return;

  const { sentence_id, span } = selectedSpanRef;
  const s = currentAnalysis.sentences[sentence_id];
  if (!s || !span) return;

  // Replace error segment in the sentence text
  const before = s.text.slice(0, span.start);
  const after = s.text.slice(span.end);
  const fixedSent = before + span.corrected_form + after;

  // Reassemble full text
  const newSentences = currentAnalysis.sentences.map((sent, idx) => {
    return idx === sentence_id ? fixedSent : sent.text;
  });
  const newFullText = newSentences.join(' ');

  setEditorText(newFullText);
  selectedSpanRef = null;
  const tooltip = document.getElementById('ide-error-tooltip');
  if (tooltip) {
    tooltip.classList.add('hidden');
    tooltip.dataset.locked = 'false';
  }
  resetErrorDetailView();
  analyzeWriterText(true);
}

// ── Setup Editor Event Listeners & Hover Tooltip ────────────────────────────
export function setupEditorListeners() {
  const editor = document.getElementById('ide-editor');
  if (!editor || editor.__listenersAttached) return;
  editor.__listenersAttached = true;

  editor.addEventListener('compositionstart', () => { isComposing = true; });
  editor.addEventListener('compositionend', () => {
    isComposing = false;
    analyzeWriterText();
  });

  const tooltip = document.getElementById('ide-error-tooltip');
  const showTooltip = (mark, locked = false) => {
    if (!mark || !tooltip || !currentAnalysis) return;
    const sentIdx = parseInt(mark.getAttribute('data-sent'), 10);
    const spanIdx = parseInt(mark.getAttribute('data-span'), 10);
    const s = currentAnalysis.sentences?.[sentIdx];
    const sp = s?.spans?.[spanIdx];
    if (!sp) return;

    tooltip.innerHTML = `
      <div class="tooltip-header">
        <span class="err-type-badge err-bg-${sp.error_type}">${getErrorTypeLabel(sp.error_type)}</span>
      </div>
      <div class="tooltip-body">${esc(sp.explanation_zh)}</div>
      <div class="tooltip-suggest">推荐修正：<b>${esc(sp.corrected_form)}</b></div>
      ${sp.corrected_form ? '<button class="btn btn-dark btn-xs tooltip-fix-btn" onclick="fixSelectedSpan()">应用修正</button>' : ''}
    `;
    const rect = mark.getBoundingClientRect();
    tooltip.style.top = `${rect.bottom + window.scrollY + 6}px`;
    tooltip.style.left = `${Math.max(10, Math.min(window.innerWidth - 270, rect.left + window.scrollX))}px`;
    tooltip.dataset.locked = locked ? 'true' : 'false';
    tooltip.classList.remove('hidden');
  };

  editor.addEventListener('mouseover', (e) => {
    const mark = e.target.closest('.writer-err-underline');
    showTooltip(mark);
  });

  editor.addEventListener('click', (e) => {
    const mark = e.target.closest('.writer-err-underline');
    if (mark) showTooltip(mark, true);
  });

  editor.addEventListener('mouseout', (e) => {
    const mark = e.target.closest('.writer-err-underline');
    if (mark && tooltip && tooltip.dataset.locked !== 'true') {
      tooltip.classList.add('hidden');
    }
  });
}

// ── Reset Error Detail Box ──────────────────────────────────────────────────
function resetErrorDetailView() {
  const detailEl = document.getElementById('writer-err-detail');
  if (detailEl) {
    detailEl.innerHTML = `
      <div class="writer-err-placeholder">
        <div style="font-size:2rem;margin-bottom:0.5rem;">✍️</div>
        <div>点击编辑器中的<b>彩色波浪下划线</b>，查看错误成因与修正建议，并支持一键替换与存卡。</div>
      </div>
    `;
  }
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
    if (titleInput) titleInput.value = essay.title || '';
    setEditorText(essay.content || '');

    let analysis = essay.analysis_json;
    if (typeof analysis === 'string') {
      try { analysis = JSON.parse(analysis); } catch (e) { analysis = null; }
    }

    if (analysis && analysis.sentences) {
      currentAnalysis = analysis;
      renderEditor(essay.content || '', analysis);
    } else {
      analyzeWriterText(true);
    }

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
  if (titleInput) titleInput.value = '';
  const editor = document.getElementById('ide-editor');
  if (editor) editor.innerHTML = '';

  updateWriterStats('');
  updateAnalysisPanels({ cefr: null, error_count: 0, sentences: [] });

  const versionListEl = document.getElementById('writer-version-list');
  if (versionListEl) {
    versionListEl.innerHTML = '<div class="writer-empty-tip">暂无版本记录（请先保存或打开作文）</div>';
  }

  resetErrorDetailView();
  loadWriterEssays();
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
    if (!currentEssayId) {
      const title = document.getElementById('writer-title')?.value.trim() || '未命名作文草稿';
      const content = editorText() || selectedSpanRef.sentenceText;
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
  const saveBtn = document.getElementById('writer-save-btn');

  const content = editorText();
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
    const finalContent = res.content || content;
    renderEditor(finalContent, res.analysis_json);
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
  const text = editorText();

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

    setEditorText(res.content);
    currentAnalysis = res.analysis_json;
    renderEditor(res.content, res.analysis_json);

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

// ── Essay Version Snapshots Management (v4.0.0) ─────────────────────────────
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
        <div class="version-item ${isCheckpoint ? 'version-checkpoint' : ''}" onclick="previewEssayVersion(${v.id})" title="点击预览此快照内容">
          <div class="version-header">
            <span class="version-id">#v${v.id}</span>
            ${errPill}
          </div>
          <div class="version-msg">${esc(v.message || '快照')}</div>
          <div class="version-meta">
            <span class="version-time">${timeStr}</span>
            <div class="version-actions" onclick="event.stopPropagation()">
              <button class="btn btn-ghost btn-xs version-restore-btn" onclick="restoreEssayVersion(${v.id})" title="恢复至此快照">↩ 恢复</button>
              <button class="btn btn-ghost btn-xs btn-del" onclick="deleteEssayVersion(${v.id})" title="删除此快照">🗑️</button>
            </div>
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

export async function previewEssayVersion(versionId) {
  if (!currentEssayId) return;
  try {
    const v = await api(`/api/essays/${currentEssayId}/versions/${versionId}`);
    const overlay = document.getElementById('version-preview-overlay');
    if (!overlay) return;

    const badgeEl = document.getElementById('version-preview-badge');
    const titleEl = document.getElementById('version-preview-title');
    const timeEl = document.getElementById('version-preview-time');
    const statusEl = document.getElementById('version-preview-status');
    const contentEl = document.getElementById('version-preview-content');
    const restoreBtn = document.getElementById('version-preview-restore-btn');

    if (badgeEl) badgeEl.textContent = `#v${v.id}`;
    if (titleEl) titleEl.textContent = v.message || '快照预览';
    if (timeEl) timeEl.textContent = (v.created_at || '').replace('T', ' ').slice(0, 19);

    if (statusEl) {
      if (v.error_count > 0) {
        statusEl.textContent = `⚠️ 记录了 ${v.error_count} 处语法疑点`;
        statusEl.className = 'writer-status-pill status-warn';
      } else {
        statusEl.textContent = '✓ 表达流畅 · 0 错误';
        statusEl.className = 'writer-status-pill status-clean';
      }
    }

    if (contentEl) {
      const a = v.analysis_json;
      if (a && a.sentences && a.sentences.length > 0) {
        contentEl.innerHTML = a.sentences.map((s, sIdx) => {
          const sentHtml = buildSentenceHighlightedText(s.text, s.spans || [], s.hints || [], sIdx, {
            clickable: false,
            useNativeTitle: true
          });
          return `<span class="ide-sent-block">${sentHtml}</span> `;
        }).join('');
      } else {
        contentEl.textContent = v.content || '(空白快照)';
      }
    }

    if (restoreBtn) {
      restoreBtn.onclick = () => {
        closeVersionPreview();
        restoreEssayVersion(versionId);
      };
    }

    overlay.classList.remove('hidden');
  } catch (err) {
    console.error('[Writer] Preview version failed:', err);
    alert('查看版本快照失败：' + (err.message || err));
  }
}

export function closeVersionPreview() {
  const overlay = document.getElementById('version-preview-overlay');
  if (overlay) overlay.classList.add('hidden');
}

export async function deleteEssayVersion(versionId) {
  if (!currentEssayId) return;
  if (!confirm(`确定要删除版本快照 #v${versionId} 吗？当前作文内容不受影响。`)) return;

  try {
    await api(`/api/essays/${currentEssayId}/versions/${versionId}`, {
      method: 'DELETE'
    });
    loadEssayVersions();
  } catch (err) {
    console.error('[Writer] Delete version failed:', err);
    alert('删除版本快照失败：' + (err.message || err));
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

    setEditorText(res.content);
    currentAnalysis = res.analysis_json;
    renderEditor(res.content, res.analysis_json);

    loadEssayVersions();
    loadWriterEssays();
  } catch (err) {
    console.error('[Writer] Restore version failed:', err);
    alert('恢复版本失败：' + (err.message || err));
  }
}

