/* DeLector - Reader View, Token Inspector & Sticky Notes */
'use strict';

import { state, esc, api, normalizeCefrPct } from './core.js';
import { ShadowPlayer, playGermanAudio } from './player.js';

let currentArticleNotes = [];
let readerFontMode = localStorage.getItem('delector_font_mode') || 'sans';
let readerFontSize = parseInt(localStorage.getItem('delector_font_size'), 10) || 18;

// ── Typography ───────────────────────────────────────────────────────────────
export function applyTypography() {
  const content = document.getElementById('reader-content');
  if (content) {
    if (readerFontMode === 'serif') {
      content.classList.add('font-serif');
    } else {
      content.classList.remove('font-serif');
    }
    content.style.setProperty('--reader-fs', `${readerFontSize / 16}rem`);
  }

  const btnSans = document.getElementById('btn-font-sans');
  const btnSerif = document.getElementById('btn-font-serif');
  if (btnSans && btnSerif) {
    btnSans.classList.toggle('active', readerFontMode === 'sans');
    btnSerif.classList.toggle('active', readerFontMode === 'serif');
  }
}

export function setFontMode(mode) {
  readerFontMode = mode;
  localStorage.setItem('delector_font_mode', mode);
  applyTypography();
}

export function adjustFontSize(delta) {
  readerFontSize = Math.max(14, Math.min(24, readerFontSize + delta));
  localStorage.setItem('delector_font_size', readerFontSize);
  applyTypography();
}

// ── CEFR Focus Mode ─────────────────────────────────────────────────────────
export function toggleCefrFocus(level) {
  if (state.currentFocusedLevel === level) {
    clearCefrFocus();
    return;
  }
  
  state.currentFocusedLevel = level;
  document.body.classList.add('focus-mode');
  
  document.querySelectorAll('.heatbar-seg').forEach(el => {
    el.classList.toggle('focused', el.classList.contains(level));
  });

  document.querySelectorAll('.tok').forEach(el => {
    const matches = el.classList.contains(level);
    el.classList.toggle('focus-active', matches);
  });
}

export function clearCefrFocus() {
  state.currentFocusedLevel = null;
  document.body.classList.remove('focus-mode');
  document.querySelectorAll('.heatbar-seg').forEach(el => el.classList.remove('focused'));
  document.querySelectorAll('.tok').forEach(el => el.classList.remove('focus-active'));
}

// ── Heatbars ─────────────────────────────────────────────────────────────────
export function renderMiniBar(stats) {
  if (!stats || !stats.cefr_percentages) return '';
  const p = normalizeCefrPct(stats.cefr_percentages);
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl =>
    (p[lvl] > 0) ? `<div class="mini-seg ${lvl}" style="width:${p[lvl]}%" title="${lvl}: ${p[lvl]}%"></div>` : ''
  ).join('');

  const rec = stats.recommended_level || 'A1';
  const recClass = rec.startsWith('B2') ? 'mini-level-B2' : `mini-level-${rec}`;

  return `
    <div class="mini-bar-wrap">
      <span class="mini-level-badge ${recClass}">${rec} 推荐</span>
      <div class="mini-cefr-bar">${segs}</div>
      <span style="font-size:0.6875rem;color:var(--pencil);font-family:var(--mono);">约 ${stats.est_reading_minutes || 1} 分钟</span>
    </div>
  `;
}

export function renderReaderHeatbar(stats) {
  if (!stats || !stats.cefr_percentages) return;
  const p = normalizeCefrPct(stats.cefr_percentages);
  const counts = stats.cefr_counts || {};
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl => {
    if (!p[lvl] || p[lvl] <= 0) return '';
    const cnt = counts[lvl] || 0;
    return `<div class="heatbar-seg ${lvl}" style="width:${p[lvl]}%" onclick="toggleCefrFocus('${lvl}')" title="点击聚焦 ${lvl} 级别生词 (${cnt} 词)">${lvl} ${p[lvl]}%</div>`;
  }).join('');

  const heatEl = document.getElementById('reader-heatbar');
  if (heatEl) heatEl.innerHTML = segs;
  const timeEl = document.getElementById('heatbar-time');
  if (timeEl) timeEl.textContent = `预计精读 ${stats.est_reading_minutes || 1} 分钟 · 共 ${stats.word_count || 0} 词`;

  const rec = stats.recommended_level || 'A1';
  const badge = document.getElementById('reader-meta-badge');
  if (badge) {
    badge.textContent = `${rec} 建议`;
    badge.className = `mini-level-badge mini-level-${rec.startsWith('B2') ? 'B2' : rec}`;
  }
}

// ── Articles ─────────────────────────────────────────────────────────────────
export async function loadArticles() {
  const el = document.getElementById('article-list');
  if (!el) return;
  el.innerHTML = '<div class="empty-state">加载中…</div>';
  try {
    const data = await api('/api/articles');
    if (!data.length) {
      el.innerHTML = '<div class="empty-state">暂无文稿，点击上方按钮导入德语文章</div>';
      return;
    }
    el.innerHTML = data.map(a => `
      <div class="article-row" onclick="openReader(${a.id})">
        <div>
          <div class="article-row-title">${esc(a.title)}</div>
          <div class="article-row-meta">${a.created_at} · ${a.char_count} 字符</div>
          ${renderMiniBar(a.stats)}
        </div>
        <span class="article-row-arrow">→</span>
      </div>`).join('');
  } catch (err) {
    el.innerHTML = '<div class="empty-state">文章列表加载失败</div>';
  }
}

export async function openReader(id) {
  state.currentArticle = await api('/api/articles/' + id);
  document.getElementById('reader-title').textContent = state.currentArticle.title;
  renderReaderHeatbar(state.currentArticle.stats);
  const content = document.getElementById('reader-content');
  
  let paraTokens = [];
  state.currentArticle.sentences.forEach(sent => {
    const sentTokens = sent.tokens.map(t => {
      if (t.is_space) {
        if (t.text.includes('\n\n')) return '__PARA__';
        if (t.text.includes('\n')) return '<br>';
        return ' ';
      }
      if (t.is_punct) return `<span class="punct">${esc(t.text)}</span>`;
      const lvl = t.cefr_level || 'A1';
      const sepAttr = t.separable ? ` data-sep-partner="tok-${t.separable.sep_prefix_id || t.separable.sep_verb_id}"` : '';
      const sepClass = t.separable ? ' is-separable' : '';
      return `<span id="tok-${t.id}" class="tok ${lvl}${sepClass}"${sepAttr} onclick="inspect(${t.id},${sent.id})">${esc(t.text)}</span>`;
    }).join('');

    paraTokens.push(sentTokens);
  });

  const fullText = paraTokens.join(' ');
  const splitParas = fullText.split('__PARA__').map(p => p.trim()).filter(Boolean);
  
  if (splitParas.length > 0) {
    content.innerHTML = splitParas.map(p => `<p class="reader-p">${p}</p>`).join('');
  } else {
    content.innerHTML = `<p class="reader-p">${fullText}</p>`;
  }

  ShadowPlayer.reset();
  applyTypography();
  await loadArticleNotes(id);
  
  // Dispatch view change
  if (window.show) window.show('reader');
}

// ── Token Inspection ────────────────────────────────────────────────────────
export function inspect(tokenId, sentId) {
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
  document.querySelectorAll('.tok.linked-separable').forEach(el => el.classList.remove('linked-separable'));

  const el = document.getElementById('tok-' + tokenId);
  if (el) el.classList.add('sel');

  const sent  = state.currentArticle.sentences.find(s => s.id === sentId);
  const token = sent.tokens.find(t => t.id === tokenId);
  state.selectedToken = token;
  state.selectedSent  = sent;
  state.grammarData   = null;

  // Highlight separable partner if linked
  if (token.separable) {
    const partnerId = token.separable.sep_prefix_id || token.separable.sep_verb_id;
    if (partnerId) {
      document.getElementById('tok-' + partnerId)?.classList.add('linked-separable');
    }
  }

  const sentIdx = state.currentArticle.sentences.findIndex(s => s.id === sentId);
  if (sentIdx >= 0) {
    ShadowPlayer.seekSentence(sentIdx);
  }

  const lvl = token.cefr_level || 'A1';
  document.getElementById('d-word').textContent = token.text;
  document.getElementById('d-cefr').textContent = 'CEFR ' + lvl;
  document.getElementById('d-cefr').className = 'cefr-badge badge-' + lvl;

  let genderHtml = '';
  if (token.gender === 'Masc') genderHtml = '<span class="gender-tag gender-der">der 阳性</span>';
  else if (token.gender === 'Fem') genderHtml = '<span class="gender-tag gender-die">die 阴性</span>';
  else if (token.gender === 'Neut') genderHtml = '<span class="gender-tag gender-das">das 中性</span>';

  let separableHtml = '';
  if (token.separable && token.separable.sep_lemma) {
    separableHtml = ` · 🔗 可分原形: <strong style="color:var(--accent);">${esc(token.separable.sep_lemma)}</strong>`;
  }

  document.getElementById('d-meta').innerHTML =
    `原型: <strong>${esc(token.lemma)}</strong> · 词性: ${esc(token.pos)} ${genderHtml}${separableHtml}` +
    (token.case ? ` · ${esc(token.case)}` : '');
  
  // Clear previous dynamic morphology sections
  const oldStamm = document.getElementById('d-stammformen-box');
  if (oldStamm) oldStamm.remove();
  const oldKomposita = document.getElementById('d-komposita-box');
  if (oldKomposita) oldKomposita.remove();

  document.getElementById('d-def').value = '';
  document.getElementById('d-def-status').textContent = '词库查询中…';
  document.getElementById('d-sent').textContent = sent.text;
  document.getElementById('save-vocab-btn').textContent = '+ 加入 Anki 词汇卡';
  document.getElementById('grammar-result').classList.add('hidden');
  openDrawer('vocab');

  api('/api/lookup/vocab', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ sentence: sent.text, target_word: token.text })
  }).then(res => {
    if (res && state.selectedToken?.text === token.text) {
      if (res.definition_zh && !document.getElementById('d-def').value) {
        document.getElementById('d-def').value = res.definition_zh;
      }
      document.getElementById('d-def-status').textContent = res.source === 'local_dict' ? '⚡ 歌德核心词库 (0ms)' : '✓ AI 已预填';
      if (res.plural) state.selectedToken.plural = res.plural;
      if (res.gender && !genderHtml) {
        const gTag = res.gender === 'Masc' ? '<span class="gender-tag gender-der">der 阳性</span>' :
                     res.gender === 'Fem' ? '<span class="gender-tag gender-die">die 阴性</span>' :
                     '<span class="gender-tag gender-das">das 中性</span>';
        document.getElementById('d-meta').innerHTML += ` ${gTag}`;
      }

      // Render Stammformen if irregular verb
      if (res.stammformen) {
        state.selectedToken.stammformen = res.stammformen;
        const sf = res.stammformen;
        const metaEl = document.getElementById('d-meta');
        const stammDiv = document.createElement('div');
        stammDiv.id = 'd-stammformen-box';
        stammDiv.className = 'stammformen-banner';
        stammDiv.innerHTML = `
          <span class="stamm-tag">⚡ 强变化三态</span>
          <span class="stamm-formula"><strong>${esc(sf.infinitiv)}</strong> — ${esc(sf.praeteritum)} — <em>${esc(sf.hilfsverb)}</em> <strong>${esc(sf.partizip2)}</strong></span>
        `;
        metaEl.parentNode.insertBefore(stammDiv, metaEl.nextSibling);
      }

      // Render Komposita if compound noun
      if (res.komposita && res.komposita.length >= 2) {
        const metaEl = document.getElementById('d-stammformen-box') || document.getElementById('d-meta');
        const kompDiv = document.createElement('div');
        kompDiv.id = 'd-komposita-box';
        kompDiv.className = 'komposita-banner';
        kompDiv.innerHTML = `
          <div class="komposita-title">🧩 复合词结构拆解:</div>
          <div class="komposita-pills-row">
            ${res.komposita.map(k => `
              <span class="komposita-pill" title="点击查看子词" onclick="window.inspectSubWord('${esc(k.word)}', '${esc(k.def_zh||'')}', '${esc(k.gender||'')}')">
                <span class="k-word">${esc(k.word)}</span>
                ${k.gender ? `<span class="k-gender">${esc(k.gender)}</span>` : ''}
                <span class="k-def">${esc(k.def_zh || '')}</span>
              </span>
            `).join('<span class="komposita-plus">+</span>')}
          </div>
        `;
        metaEl.parentNode.insertBefore(kompDiv, metaEl.nextSibling);
      }
    } else {
      document.getElementById('d-def-status').textContent = '';
    }
  }).catch(() => {
    document.getElementById('d-def-status').textContent = '';
  });
}

export function inspectSubWord(word, defZh, gender) {
  document.getElementById('d-def').value = `${word} (${gender ? gender + ', ' : ''}${defZh})`;
  document.getElementById('d-def-status').textContent = '🧩 已选用复合子词释义';
}


// ── Drawer & Tabs ────────────────────────────────────────────────────────────
export function switchDrawerTab(tab) {
  const tabVocab = document.getElementById('d-tab-vocab');
  const tabNote  = document.getElementById('d-tab-note');
  const tabAll   = document.getElementById('d-tab-all');
  if (tabVocab) tabVocab.classList.toggle('active', tab === 'vocab');
  if (tabNote)  tabNote.classList.toggle('active', tab === 'note');
  if (tabAll)   tabAll.classList.toggle('active', tab === 'all');

  const vocabWrap = document.getElementById('drawer-vocab-wrap');
  const noteSec   = document.getElementById('drawer-note-section');

  if (vocabWrap) vocabWrap.classList.toggle('hidden', tab === 'note');
  if (noteSec)   noteSec.classList.toggle('hidden', tab === 'vocab');

  const bodyEl = document.querySelector('.drawer-body');
  if (bodyEl) bodyEl.scrollTop = 0;

  if (tab === 'note' && noteSec) {
    document.getElementById('note-text-input')?.focus();
  }
}

export function openDrawer(preferredTab = null) {
  document.getElementById('drawer')?.classList.add('open');
  document.body.classList.add('drawer-open');
  if (preferredTab) switchDrawerTab(preferredTab);
}

export function closeDrawer() {
  document.getElementById('drawer')?.classList.remove('open');
  document.body.classList.remove('drawer-open');
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
}

// ── Grammar AI ───────────────────────────────────────────────────────────────
export async function analyzeGrammar() {
  const btn = document.getElementById('analyze-btn');
  btn.textContent = '分析中…';
  btn.disabled = true;
  try {
    state.grammarData = await api('/api/lookup/grammar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ sentence: state.selectedSent.text, target_phrase: state.selectedToken.text })
    });
    const lvl = state.grammarData.cefr_level || 'B1';
    document.getElementById('g-name').textContent    = state.grammarData.grammar_name;
    document.getElementById('g-formula').textContent = state.grammarData.rule_formula || '';
    document.getElementById('g-formula').classList.toggle('hidden', !state.grammarData.rule_formula);
    document.getElementById('g-exp').textContent     = state.grammarData.explanation_zh;
    document.getElementById('g-badge').textContent   = 'Goethe ' + lvl;
    document.getElementById('g-badge').className     = 'cefr-badge grammar-cefr-badge badge-' + lvl;
    document.getElementById('grammar-result').classList.remove('hidden');
  } catch {
    alert('语法解析失败，请检查 API Key');
  } finally {
    btn.textContent = 'AI 深度剖析';
    btn.disabled = false;
  }
}

export async function saveVocab() {
  if (!state.selectedToken || !state.currentArticle) return;
  const def = document.getElementById('d-def').value.trim() || state.selectedToken.lemma || state.selectedToken.text;
  await api('/api/cards/vocab', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: state.currentArticle.id,
      word: state.selectedToken.text, lemma: state.selectedToken.lemma,
      pos: state.selectedToken.pos,   gender: state.selectedToken.gender,
      cefr_level: state.selectedToken.cefr_level || 'A1',
      definition_zh: def, sentence_context: state.selectedSent.text,
      plural: state.selectedToken.plural || ''
    })
  });
  document.getElementById('save-vocab-btn').textContent = '✓ 已保存';
  refreshCardCounters();
}

export async function saveGrammar() {
  if (!state.grammarData || !state.currentArticle) return;
  await api('/api/cards/grammar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: state.currentArticle.id,
      sentence_context: state.selectedSent.text,
      grammar_name: state.grammarData.grammar_name,
      cefr_level: state.grammarData.cefr_level || 'B1',
      explanation_zh: state.grammarData.explanation_zh,
      rule_formula: state.grammarData.rule_formula
    })
  });
  document.getElementById('save-grammar-btn').textContent = '✓ 已加入语法卡';
  refreshCardCounters();
}

export async function refreshCardCounters() {
  try {
    const data = await api('/api/cards');
    const vLen = (data.vocab_cards || []).length;
    const gLen = (data.grammar_cards || []).length;
    const total = vLen + gLen;
    const badge = document.getElementById('card-count');
    const mobBadge = document.getElementById('mob-card-count');
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

  document.querySelectorAll('.margin-note-badge').forEach(el => el.remove());

  currentArticleNotes.forEach(note => {
    if (note.note_content && note.sentence_id) {
      const sent = state.currentArticle?.sentences?.find(s => s.id === note.sentence_id);
      if (sent && sent.tokens?.length) {
        const lastTok = sent.tokens[sent.tokens.length - 1];
        const lastTokEl = document.getElementById('tok-' + lastTok.id);
        if (lastTokEl && !lastTokEl.parentNode.querySelector(`[data-note-id="${note.id}"]`)) {
          const badge = document.createElement('span');
          badge.className = 'margin-note-badge';
          badge.dataset.noteId = note.id;
          badge.innerHTML = `📌 随笔`;
          badge.title = note.note_content;
          badge.onclick = (e) => {
            e.stopPropagation();
            openNoteDrawerForExisting(note.id);
          };
          lastTokEl.insertAdjacentElement('afterend', badge);
        }
      }
    }
  });
}

export function setupSelectionTooltip() {
  const content = document.getElementById('reader-content');
  const tooltip = document.getElementById('selection-tooltip');
  if (!content || !tooltip) return;

  content.addEventListener('mouseup', () => {
    setTimeout(() => {
      const sel = window.getSelection();
      const text = sel ? sel.toString().trim() : '';
      if (text.length > 0 && content.contains(sel.anchorNode)) {
        state.activeSelectedRangeText = text;
        const range = sel.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        let node = sel.anchorNode;
        while (node && node !== content) {
          if (node.id && node.id.startsWith('tok-')) {
            const tokId = parseInt(node.id.replace('tok-', ''), 10);
            const foundSent = state.currentArticle?.sentences?.find(s => s.tokens.some(t => t.id === tokId));
            if (foundSent) state.activeSelectedSentId = foundSent.id;
            break;
          }
          node = node.parentNode;
        }

        tooltip.style.left = `${rect.left + rect.width / 2}px`;
        tooltip.style.top = `${rect.top - 8}px`;
        tooltip.classList.remove('hidden');
      } else {
        tooltip.classList.add('hidden');
      }
    }, 50);
  });

  document.addEventListener('mousedown', (e) => {
    if (!tooltip.contains(e.target) && !content.contains(e.target)) {
      tooltip.classList.add('hidden');
    }
  });
}

export async function applyHighlight(color) {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const tooltip = document.getElementById('selection-tooltip');
  if (tooltip) tooltip.classList.add('hidden');

  await api(`/api/articles/${state.currentArticle.id}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sentence_id: state.activeSelectedSentId || 1,
      selected_text: state.activeSelectedRangeText,
      color: color,
      note_content: ''
    })
  });

  await loadArticleNotes(state.currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

export function openNoteDrawerFromSelection() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const tooltip = document.getElementById('selection-tooltip');
  if (tooltip) tooltip.classList.add('hidden');

  state.activeEditingNoteId = null;
  document.getElementById('note-badge-status').textContent = '随笔草稿';
  document.getElementById('note-quote').textContent = `"${state.activeSelectedRangeText}"`;
  document.getElementById('note-text-input').value = '';
  document.getElementById('save-note-btn').textContent = '✓ 保存便签';
  document.getElementById('del-note-btn').classList.add('hidden');
  
  openDrawer('note');
}

export function openNoteDrawerForExisting(noteId) {
  const note = currentArticleNotes.find(n => n.id === noteId);
  if (!note) return;

  state.activeEditingNoteId = note.id;
  state.activeSelectedRangeText = note.selected_text;
  state.activeSelectedSentId = note.sentence_id;

  document.getElementById('note-badge-status').textContent = '已保存便签';
  document.getElementById('note-quote').textContent = `"${note.selected_text}"`;
  document.getElementById('note-text-input').value = note.note_content || '';
  document.getElementById('save-note-btn').textContent = '✓ 更新便签';
  document.getElementById('del-note-btn').classList.remove('hidden');

  openDrawer('note');
}

export async function aiNoteAssist() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const btn = document.getElementById('note-ai-btn');
  btn.textContent = '✨ 解析中…';
  btn.disabled = true;

  const sent = state.currentArticle.sentences?.find(s => s.id === state.activeSelectedSentId);
  const sentText = sent ? sent.text : state.activeSelectedRangeText;

  try {
    const res = await api('/api/ai/note-assist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence: sentText, selected_text: state.activeSelectedRangeText })
    });

    if (res._stub) {
      const statusEl = document.getElementById('d-def-status') || document.getElementById('note-ai-status');
      if (statusEl) statusEl.textContent = '⚠ 未配置 DEEPSEEK_API_KEY，AI 解析不可用';
      return;
    }

    let summary = res.summary_zh || '';
    if (res.key_points && res.key_points.length) {
      summary += '\n• ' + res.key_points.join('\n• ');
    }
    document.getElementById('note-text-input').value = summary;
  } catch {
    alert('AI 速记解析失败，请检查网络配置');
  } finally {
    btn.textContent = '✨ AI 速记辅助';
    btn.disabled = false;
  }
}

export async function saveCurrentNote() {
  if (!state.activeSelectedRangeText || !state.currentArticle) return;
  const noteText = document.getElementById('note-text-input').value.trim();

  if (state.activeEditingNoteId) {
    await api(`/api/notes/${state.activeEditingNoteId}`, { method: 'DELETE' });
  }

  await api(`/api/articles/${state.currentArticle.id}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sentence_id: state.activeSelectedSentId || 1,
      selected_text: state.activeSelectedRangeText,
      color: 'yellow',
      note_content: noteText
    })
  });

  document.getElementById('save-note-btn').textContent = '✓ 已保存';
  await loadArticleNotes(state.currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

export async function deleteCurrentNote() {
  if (!state.activeEditingNoteId || !state.currentArticle) return;
  if (!confirm('确定删除此条随笔便签吗？')) return;
  await api(`/api/notes/${state.activeEditingNoteId}`, { method: 'DELETE' });
  closeDrawer();
  await loadArticleNotes(state.currentArticle.id);
}

export function playSelectedAudio() {
  if (!state.activeSelectedRangeText) return;
  playGermanAudio(state.activeSelectedRangeText);
  document.getElementById('selection-tooltip')?.classList.add('hidden');
}

export function downloadStudyGuide() {
  if (!state.currentArticle) return;
  window.location.href = `/api/articles/${state.currentArticle.id}/export-guide`;
}
