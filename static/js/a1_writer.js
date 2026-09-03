/* DeLector - Goethe-Zertifikat A1 Schreiben Workshop Module */
'use strict';

import { api, esc, notify } from './core.js';
import { Companion } from './companion.js';

// ── Goethe A1 Schreiben Workshop Logic ───────────────────────────────────────

let a1WritingMode = 'essay';
let a1Teil1List = [];
let a1Teil2List = [];
let currentA1Teil1Idx = 0;
let currentA1Teil2Idx = 0;
let a1EmailDebounceTimer = null;

export function switchWriterMode(mode) {
  a1WritingMode = mode;

  ['essay', 'formular', 'email'].forEach((m) => {
    const btn = document.getElementById(
      `writer-mode-${m === 'essay' ? 'essay' : 'a1-' + m}`
    );
    if (btn) btn.classList.toggle('active', m === mode);
  });

  const freeLeft = document.getElementById('writer-free-left');
  const panel = document.getElementById('writer-panel');
  const formularView = document.getElementById('a1-formular-view');
  const emailView = document.getElementById('a1-email-view');

  if (freeLeft) freeLeft.classList.toggle('hidden', mode !== 'essay');
  if (panel) panel.classList.toggle('hidden', mode !== 'essay');
  if (formularView)
    formularView.classList.toggle('hidden', mode !== 'formular');
  if (emailView) emailView.classList.toggle('hidden', mode !== 'email');

  if (mode === 'formular') {
    if (!a1Teil1List.length) {
      loadA1WritingData().then(() => renderA1Formular());
    } else {
      renderA1Formular();
    }
  } else if (mode === 'email') {
    if (!a1Teil2List.length) {
      loadA1WritingData().then(() => renderA1Email());
    } else {
      renderA1Email();
    }
  }
}

export async function loadA1WritingData() {
  try {
    const [t1, t2] = await Promise.all([
      api('/api/a1/schreiben/teil1'),
      api('/api/a1/schreiben/teil2')
    ]);
    a1Teil1List = t1 || [];
    a1Teil2List = t2 || [];
    populateA1Selectors();
  } catch (err) {
    console.error('[Writer] Failed to load A1 writing data:', err);
  }
}

export function populateA1Selectors() {
  const sel1 = document.getElementById('a1-formular-select');
  if (sel1 && a1Teil1List.length) {
    sel1.innerHTML = a1Teil1List
      .map(
        (ex, i) => `
      <option value="${i}">Übung ${i + 1}: ${esc(ex.title)}</option>
    `
      )
      .join('');
  }

  const sel2 = document.getElementById('a1-email-select');
  if (sel2 && a1Teil2List.length) {
    sel2.innerHTML = a1Teil2List
      .map(
        (ex, i) => `
      <option value="${i}">Thema ${i + 1}: ${esc(ex.scenario)}</option>
    `
      )
      .join('');
  }
}

export function selectA1Formular(val) {
  currentA1Teil1Idx = parseInt(val, 10) || 0;
  renderA1Formular();
}

export function prevA1Formular() {
  if (!a1Teil1List.length) return;
  currentA1Teil1Idx =
    (currentA1Teil1Idx - 1 + a1Teil1List.length) % a1Teil1List.length;
  const sel = document.getElementById('a1-formular-select');
  if (sel) sel.value = currentA1Teil1Idx;
  renderA1Formular();
}

export function nextA1Formular() {
  if (!a1Teil1List.length) return;
  currentA1Teil1Idx = (currentA1Teil1Idx + 1) % a1Teil1List.length;
  const sel = document.getElementById('a1-formular-select');
  if (sel) sel.value = currentA1Teil1Idx;
  renderA1Formular();
}

export function randomA1Formular() {
  if (a1Teil1List.length <= 1) return;
  let nextIdx = Math.floor(Math.random() * a1Teil1List.length);
  if (nextIdx === currentA1Teil1Idx)
    nextIdx = (nextIdx + 1) % a1Teil1List.length;
  currentA1Teil1Idx = nextIdx;
  const sel = document.getElementById('a1-formular-select');
  if (sel) sel.value = currentA1Teil1Idx;
  renderA1Formular();
}

export function renderA1Formular() {
  if (!a1Teil1List.length) return;
  const ex = a1Teil1List[currentA1Teil1Idx % a1Teil1List.length];

  const titleEl = document.getElementById('a1-form-title');
  const scenarioEl = document.getElementById('a1-form-scenario');
  const passageEl = document.getElementById('a1-form-passage');
  const container = document.getElementById('a1-formular-container');
  const feedbackEl = document.getElementById('a1-formular-feedback');

  if (titleEl) titleEl.textContent = ex.title;
  if (scenarioEl) scenarioEl.textContent = ex.scenario;
  if (passageEl) passageEl.textContent = ex.passage;
  if (feedbackEl) {
    feedbackEl.classList.add('hidden');
    feedbackEl.innerHTML = '';
  }

  if (container) {
    let fieldsHtml = '';
    for (let i = 0; i < ex.fields.length; i++) {
      const fld = ex.fields[i];
      fieldsHtml += `
        <div class="a1-formular-field-row" id="row-${fld.key}">
          <label class="a1-formular-label" for="inp-${fld.key}">
            <b>${esc(fld.label)}</b>
          </label>
          <div class="a1-formular-input-wrap">
            <input type="text" id="inp-${fld.key}" class="a1-formular-input" placeholder="在此填入..." autocomplete="off" />
            <span class="a1-field-status-icon" id="icon-${fld.key}"></span>
          </div>
          <div class="a1-field-correction hidden" id="corr-${fld.key}"></div>
        </div>
      `;
    }
    container.innerHTML = fieldsHtml;
  }
}

export async function checkA1Formular() {
  if (!a1Teil1List.length) return;
  const ex = a1Teil1List[currentA1Teil1Idx % a1Teil1List.length];

  const answers = {};
  for (const fld of ex.fields) {
    const inp = document.getElementById(`inp-${fld.key}`);
    answers[fld.key] = inp ? inp.value.trim() : '';
  }

  try {
    const res = await api('/api/a1/schreiben/teil1/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exercise_id: ex.id,
        answers: answers
      })
    });

    // Render results
    for (const fld of ex.fields) {
      const row = document.getElementById(`row-${fld.key}`);
      const inp = document.getElementById(`inp-${fld.key}`);
      const icon = document.getElementById(`icon-${fld.key}`);
      const corr = document.getElementById(`corr-${fld.key}`);
      const chk = res.results[fld.key];

      if (chk && chk.correct) {
        if (row) {
          row.classList.remove('is-wrong');
          row.classList.add('is-correct');
        }
        if (inp) {
          inp.classList.remove('input-wrong');
          inp.classList.add('input-correct');
        }
        if (icon)
          icon.innerHTML =
            '<span style="color:#16a34a;font-weight:bold;">✓ 正确 (+1分)</span>';
        if (corr) corr.classList.add('hidden');
      } else {
        if (row) {
          row.classList.remove('is-correct');
          row.classList.add('is-wrong');
        }
        if (inp) {
          inp.classList.remove('input-correct');
          inp.classList.add('input-wrong');
        }
        if (icon)
          icon.innerHTML =
            '<span style="color:#dc2626;font-weight:bold;">✕ 错误 (0分)</span>';
        if (corr) {
          corr.classList.remove('hidden');
          corr.innerHTML = `
            <div style="color:#b91c1c;font-size:0.875rem;margin-top:0.25rem;">
              <b>标准答案:</b> ${esc(chk.expected)}
              ${fld.tip ? `<br><span style="color:var(--ink-mute);">${esc(fld.tip)}</span>` : ''}
            </div>
          `;
        }
      }
    }

    const feedbackEl = document.getElementById('a1-formular-feedback');
    if (feedbackEl) {
      feedbackEl.classList.remove('hidden');
      const scoreBadge =
        res.score === 5 ? '🎉 满分 5 / 5' : `📊 得分: ${res.score} / 5`;
      feedbackEl.innerHTML = `
        <div class="a1-score-card ${res.score >= 4 ? 'score-good' : 'score-need-work'}">
          <div style="font-size:1.25rem;font-weight:700;font-family:var(--serif-heading);">${scoreBadge}</div>
          <div style="font-size:0.875rem;margin-top:0.35rem;">
            ${res.score === 5 ? '太棒了！所有 5 个填空均完全符合歌德 A1 官方评分标准！' : '请核对标红的错误项与上方提示，总结大小写或日期格式规律。'}
          </div>
        </div>
      `;
    }

    if (res.score >= 4 && window.Companion) {
      window.Companion.celebrate('quiz_done', {
        pct: Math.round((res.score / 5) * 100)
      });
    }
  } catch (err) {
    console.error('[Writer] Check formular failed:', err);
    notify('判分失败：' + (err.message || err), { kind: 'error' });
  }
}

export function resetA1Formular() {
  renderA1Formular();
}

// ── Goethe A1 Teil 2: 30-Wort E-Mail Lab ──────────────────────────────────────

export function selectA1Email(val) {
  currentA1Teil2Idx = parseInt(val, 10) || 0;
  renderA1Email();
}

export function prevA1Email() {
  if (!a1Teil2List.length) return;
  currentA1Teil2Idx =
    (currentA1Teil2Idx - 1 + a1Teil2List.length) % a1Teil2List.length;
  const sel = document.getElementById('a1-email-select');
  if (sel) sel.value = currentA1Teil2Idx;
  renderA1Email();
}

export function nextA1Email() {
  if (!a1Teil2List.length) return;
  currentA1Teil2Idx = (currentA1Teil2Idx + 1) % a1Teil2List.length;
  const sel = document.getElementById('a1-email-select');
  if (sel) sel.value = currentA1Teil2Idx;
  renderA1Email();
}

export function randomA1Email() {
  if (a1Teil2List.length <= 1) return;
  let nextIdx = Math.floor(Math.random() * a1Teil2List.length);
  if (nextIdx === currentA1Teil2Idx)
    nextIdx = (nextIdx + 1) % a1Teil2List.length;
  currentA1Teil2Idx = nextIdx;
  const sel = document.getElementById('a1-email-select');
  if (sel) sel.value = currentA1Teil2Idx;
  renderA1Email();
}

export function renderA1Email() {
  if (!a1Teil2List.length) return;
  const ex = a1Teil2List[currentA1Teil2Idx % a1Teil2List.length];

  const promptEl = document.getElementById('a1-email-prompt');
  const leitpunkteEl = document.getElementById('a1-email-leitpunkte');
  const sampleBox = document.getElementById('a1-email-sample-box');
  const phrasesBox = document.getElementById('a1-email-phrases-box');

  if (promptEl) promptEl.textContent = ex.prompt;

  if (leitpunkteEl) {
    leitpunkteEl.innerHTML = ex.leitpunkte
      .map(
        (lp, idx) => `
      <div class="a1-leitpunkt-item" id="lp-chip-${idx}">
        <span class="lp-icon">⚪</span>
        <span class="lp-text">${esc(lp)}</span>
      </div>
    `
      )
      .join('');
  }

  if (sampleBox) {
    sampleBox.innerHTML = `
      <div class="a1-musterbrief-de">${esc(ex.sample_email).replace(/\n/g, '<br>')}</div>
      <div class="a1-musterbrief-zh" style="margin-top:0.5rem;font-size:0.85rem;color:var(--ink-mute);border-top:1px dashed var(--rule-light);padding-top:0.5rem;">
        ${esc(ex.sample_translation).replace(/\n/g, '<br>')}
      </div>
    `;
  }

  if (phrasesBox && ex.useful_phrases) {
    phrasesBox.innerHTML = ex.useful_phrases
      .map(
        (p) => `
      <div class="a1-phrase-chip">${esc(p)}</div>
    `
      )
      .join('');
  }

  onA1EmailInput();
}

export function onA1EmailInput() {
  const inputEl = document.getElementById('a1-email-input');
  if (!inputEl) return;
  const text = inputEl.value;

  const words = text
    .replace(/[,.!?]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length > 0);
  const wordCount = words.length;

  const countEl = document.getElementById('a1-email-word-count');
  const badgeEl = document.getElementById('a1-email-word-badge');
  if (countEl) countEl.textContent = `${wordCount} 词`;

  if (badgeEl) {
    if (wordCount === 0) {
      badgeEl.textContent = '建议 25~35 词';
      badgeEl.className = 'a1-diag-badge';
    } else if (wordCount < 20) {
      badgeEl.textContent = '偏短 (<20词)';
      badgeEl.className = 'a1-diag-badge badge-warn';
    } else if (wordCount <= 40) {
      badgeEl.textContent = '✓ 最佳区间 (25~35词)';
      badgeEl.className = 'a1-diag-badge badge-ok';
    } else {
      badgeEl.textContent = '偏长 (>40词)';
      badgeEl.className = 'a1-diag-badge badge-info';
    }
  }

  if (a1EmailDebounceTimer) clearTimeout(a1EmailDebounceTimer);
  a1EmailDebounceTimer = setTimeout(diagnoseA1Email, 500);
}

export async function diagnoseA1Email() {
  if (!a1Teil2List.length) return;
  const ex = a1Teil2List[currentA1Teil2Idx % a1Teil2List.length];
  const inputEl = document.getElementById('a1-email-input');
  const text = inputEl ? inputEl.value : '';

  if (!text.trim()) {
    const diagBox = document.getElementById('a1-email-diag-results');
    if (diagBox) diagBox.classList.add('hidden');
    return;
  }

  try {
    const res = await api('/api/a1/schreiben/teil2/diagnose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        leitpunkte: ex.leitpunkte
      })
    });

    const greetingStatus = document.getElementById('a1-email-greeting-status');
    if (greetingStatus) {
      if (res.greeting.valid) {
        greetingStatus.textContent =
          res.greeting.type === 'formal' ? '✓ 正式尊称' : '✓ 熟人便函';
        greetingStatus.className = 'a1-diag-badge badge-ok';
      } else {
        greetingStatus.textContent = '✕ 缺失称呼';
        greetingStatus.className = 'a1-diag-badge badge-err';
      }
    }

    const valedictionStatus = document.getElementById(
      'a1-email-valediction-status'
    );
    if (valedictionStatus) {
      if (res.has_valediction_comma_error) {
        valedictionStatus.textContent = '⚠ 勿加逗号';
        valedictionStatus.className = 'a1-diag-badge badge-warn';
      } else if (res.valediction.valid) {
        valedictionStatus.textContent = '✓ 规范结语';
        valedictionStatus.className = 'a1-diag-badge badge-ok';
      } else {
        valedictionStatus.textContent = '✕ 缺失结语';
        valedictionStatus.className = 'a1-diag-badge badge-err';
      }
    }

    // Update Leitpunkte checks
    if (res.leitpunkte_results) {
      res.leitpunkte_results.forEach((lp, idx) => {
        const chip = document.getElementById(`lp-chip-${idx}`);
        if (chip) {
          chip.classList.toggle('is-covered', lp.matched);
          const icon = chip.querySelector('.lp-icon');
          if (icon) icon.textContent = lp.matched ? '🟢' : '⚪';
        }
      });
    }

    const diagBox = document.getElementById('a1-email-diag-results');
    if (diagBox) {
      diagBox.classList.remove('hidden');
      if (!res.suggestions || !res.suggestions.length) {
        diagBox.innerHTML = `
          <div class="a1-diag-card diag-perfect">
            <b>🎉 格式完全合规！</b> 称呼、正文大小写、结语与词数均达到满分水准。
          </div>
        `;
      } else {
        let listHtml = res.suggestions
          .map(
            (s) => `
          <div class="a1-diag-item diag-${s.level || 'warning'}">
            <span>${s.level === 'error' ? '🚫' : '💡'}</span>
            <div>${esc(s.message)}</div>
          </div>
        `
          )
          .join('');
        diagBox.innerHTML = `<div class="a1-diag-list">${listHtml}</div>`;
      }
    }
  } catch (err) {
    console.error('[Writer] Diagnose email failed:', err);
  }
}

export function applyA1EmailTemplate() {
  if (!a1Teil2List.length) return;
  const ex = a1Teil2List[currentA1Teil2Idx % a1Teil2List.length];
  const inputEl = document.getElementById('a1-email-input');
  if (inputEl) {
    inputEl.value = ex.sample_email;
    onA1EmailInput();
  }
}

export function clearA1Email() {
  const inputEl = document.getElementById('a1-email-input');
  if (inputEl) {
    inputEl.value = '';
    onA1EmailInput();
  }
}

