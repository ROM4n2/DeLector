/* DeLector - Goethe Cloze & C-Test Examination Engine */
'use strict';

import { state, esc, api, notify } from './core.js';
import { showUndoToast } from './cards.js';
import { Companion } from './companion.js';

export async function openClozeModal() {
  if (!state.currentArticle) {
    alert('请先在文库中选择并打开一篇文章！');
    return;
  }
  document.getElementById('cloze-overlay')?.classList.remove('hidden');
  const titleEl = document.getElementById('cloze-title');
  if (titleEl) titleEl.textContent = `《${state.currentArticle.title || '当前文章'}》· 完形实战`;
  switchClozeMode(state.currentClozeMode || 'grammar');
}

export function closeClozeModal() {
  document.getElementById('cloze-overlay')?.classList.add('hidden');
}

export async function switchClozeMode(mode) {
  state.currentClozeMode = mode;
  ['grammar', 'vocab', 'ctest'].forEach(m => {
    document.getElementById(`cloze-mode-btn-${m}`)?.classList.toggle('active', m === mode);
  });
  const bodyEl = document.getElementById('cloze-content');
  if (bodyEl) bodyEl.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--pencil);font-family:var(--mono);">⚡ 正在智能分析文章语法与词法，生成实战挖空题...</div>';
  document.getElementById('cloze-score-display')?.classList.add('hidden');

  try {
    state.currentClozeExercise = await api(`/api/articles/${state.currentArticle.id}/exercise/cloze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });
    renderClozeExercise(state.currentClozeExercise);
  } catch (e) {
    if (bodyEl) bodyEl.innerHTML = `<div style="color:var(--cherry);padding:2rem;">生成失败：${esc(e.message)}</div>`;
  }
}

export function renderClozeExercise(data) {
  const bodyEl = document.getElementById('cloze-content');
  if (!bodyEl) return;

  let text = data.masked_text || '';
  const parts = text.split(/(\[\[BLANK_\d+\]\])/g);
  let html = '';

  const itemMap = {};
  (data.items || []).forEach(it => {
    itemMap[it.index] = it;
  });

  parts.forEach(part => {
    const match = part.match(/^\[\[BLANK_(\d+)\]\]$/);
    if (match) {
      const idx = parseInt(match[1], 10);
      const item = itemMap[idx];
      if (item) {
        const ph = item.type === 'ctest' ? '...' : '____';
        html += `
          <span class="cloze-blank-wrap">
            <input type="text" class="cloze-input" data-index="${item.index}"
              data-type="${esc(item.type)}"
              data-first-letter="${esc(item.first_letter || '')}"
              placeholder="${ph}" autocomplete="off" autocorrect="off" autocapitalize="off"
              onkeydown="window.handleClozeKey(event, ${item.index})">
            <span class="cloze-hint-badge hidden" id="cloze-hint-${item.index}">${esc(item.hint || '')}</span>
          </span>
        `;
      }
    } else {
      html += esc(part).replace(/\n/g, '<br>');
    }
  });

  bodyEl.innerHTML = html;
  bodyEl.querySelector('.cloze-input')?.focus();
}

export function handleClozeKey(e, idx) {
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    const nextInput = document.querySelector(`.cloze-input[data-index="${idx + 1}"]`);
    if (nextInput) nextInput.focus();
    else submitClozeExercise();
  }
}

export function revealClozeHints() {
  if (!state.currentClozeExercise) return;
  let filledCount = 0;
  document.querySelectorAll('.cloze-input').forEach(input => {
    const firstLetter = input.getAttribute('data-first-letter') || '';
    const type = input.getAttribute('data-type');

    if (!input.value.trim()) {
      if (type !== 'ctest' && firstLetter) {
        input.value = firstLetter;
      }
      input.classList.add('has-hint');
      filledCount++;
    }

    const idx = input.getAttribute('data-index');
    const badge = document.getElementById(`cloze-hint-${idx}`);
    if (badge) badge.classList.remove('hidden');
  });

  showUndoToast(`💡 已为 ${filledCount} 个空白处填入首字母提示`);
}

export function resetClozeExercise() {
  if (!state.currentClozeExercise) return;
  renderClozeExercise(state.currentClozeExercise);
  document.getElementById('cloze-score-display')?.classList.add('hidden');
  showUndoToast('↺ 已重置作答，请重新填空');
}

export async function submitClozeExercise() {
  if (!state.currentClozeExercise || !state.currentArticle) return;
  const answers = {};
  document.querySelectorAll('.cloze-input').forEach(input => {
    const idx = input.getAttribute('data-index');
    answers[idx] = input.value.trim();
  });

  try {
    const evalRes = await api('/api/exercise/cloze/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article_id: state.currentArticle.id,
        mode: state.currentClozeMode,
        answers
      })
    });

    evalRes.results.forEach(res => {
      const input = document.querySelector(`.cloze-input[data-index="${res.index}"]`);
      if (input) {
        input.classList.remove('is-correct', 'is-wrong');
        input.classList.add(res.correct ? 'is-correct' : 'is-wrong');
        if (!res.correct) {
          let tag = input.parentElement.querySelector('.cloze-correction-tag');
          if (!tag) {
            tag = document.createElement('span');
            tag.className = 'cloze-correction-tag';
            input.parentElement.appendChild(tag);
          }
          tag.textContent = `正: ${res.expected}`;
        }
      }
    });

    const scoreDisp = document.getElementById('cloze-score-display');
    const scoreText = document.getElementById('cloze-score-text');
    const pctText = document.getElementById('cloze-pct-text');
    if (scoreDisp) scoreDisp.classList.remove('hidden');
    if (scoreText) scoreText.textContent = `${evalRes.score} / ${evalRes.total}`;
    if (pctText) pctText.textContent = `${evalRes.accuracy_pct}% 正确率`;

    if (evalRes.accuracy_pct >= 80) {
      showUndoToast(`🏆 太棒了！完形实战准确率达成 ${evalRes.accuracy_pct}%！`);
      Companion.celebrate('cloze_great', { pct: evalRes.accuracy_pct });
    }
  } catch (e) {
    notify(`提交判分失败: ${e.message}`, { kind: 'error' });
  }
}
