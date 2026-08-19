/* DeLector - Leporello Folio (3-Fold Learning Progress Ledger) */
'use strict';

import { esc, api } from './core.js';

let currentFolioPage = 0;

const GERMAN_MOTTOS = [
  { de: "Es ist noch kein Meister vom Himmel gefallen.", zh: "没有人生来就是大师，精进源于日复一日的沉淀。", author: "Deutsches Sprichwort" },
  { de: "Wer fremde Sprachen nicht kennt, weiß nichts von seiner eigenen.", zh: "不谙异国语言者，亦不知自身母语之妙。", author: "Johann Wolfgang von Goethe" },
  { de: "Die Grenzen meiner Sprache bedeuten die Grenzen meiner Welt.", zh: "我的语言之界限，即是我的世界之界限。", author: "Ludwig Wittgenstein" },
  { de: "Man lernt nie aus.", zh: "活到老，学到老；精读即是不断拓展认知边界。", author: "Deutsches Sprichwort" },
  { de: "Ohne Fleiß kein Preis.", zh: "不劳则无获；日积跬步，终至千里。", author: "Deutsches Sprichwort" },
  { de: "Ein Buch ist wie ein Garten, den man in der Tasche trägt.", zh: "一本书如同一座随身携带的私家花园。", author: "Arabisches Sprichwort auf Deutsch" }
];

export function switchFolioPage(idx) {
  currentFolioPage = Math.max(0, Math.min(2, idx));
  const track = document.getElementById('folio-track');
  if (track) {
    track.style.transform = `translateX(-${currentFolioPage * 33.33333}%)`;
  }
  for (let i = 0; i < 3; i++) {
    const tab = document.getElementById(`folio-tab-${i}`);
    if (tab) tab.classList.toggle('active', i === currentFolioPage);
  }
}

export function prevFolioPage() {
  if (currentFolioPage > 0) switchFolioPage(currentFolioPage - 1);
}

export function nextFolioPage() {
  if (currentFolioPage < 2) switchFolioPage(currentFolioPage + 1);
}

export async function loadProgress() {
  const dayIndex = Math.floor(Date.now() / (1000 * 60 * 60 * 24)) % GERMAN_MOTTOS.length;
  const motto = GERMAN_MOTTOS[dayIndex];
  const mottoEl = document.getElementById('progress-motto');
  if (mottoEl) {
    mottoEl.innerHTML = `
      <div class="dossier-motto-quote">“${esc(motto.de)}”</div>
      <div class="dossier-motto-zh">${esc(motto.zh)}</div>
      <div class="dossier-motto-author">— ${esc(motto.author)}</div>
    `;
  }

  try {
    const stats = await api('/api/progress/stats');

    const tStreak = document.getElementById('ticker-streak');
    const tTime = document.getElementById('ticker-time');
    if (tStreak) tStreak.textContent = `${stats.streak || 0} TAGE`;
    if (tTime) tTime.textContent = `${stats.total_study_minutes || 0} MIN`;

    const stStreak = document.getElementById('stat-streak');
    const stVocab = document.getElementById('stat-mastered-vocab');
    const stGrammar = document.getElementById('stat-mastered-grammar');
    const stArticles = document.getElementById('stat-articles');
    const stAccuracy = document.getElementById('stat-accuracy');
    const stMinutes = document.getElementById('stat-minutes');

    if (stStreak) stStreak.textContent = stats.streak || 0;
    if (stVocab) stVocab.textContent = stats.mastered_vocab || 0;
    if (stGrammar) stGrammar.textContent = stats.mastered_grammar || 0;
    if (stArticles) stArticles.textContent = stats.total_articles || 0;
    if (stAccuracy) stAccuracy.textContent = stats.accuracy_pct || 0;
    if (stMinutes) stMinutes.textContent = stats.total_study_minutes || 0;

    const cefrCounts = stats.cefr_counts || {};
    const totalCards = stats.total_cards || 0;
    const tcEl = document.getElementById('progress-total-cards');
    if (tcEl) tcEl.textContent = `GESAMT: ${totalCards} KARTEN`;

    const heatbar = document.getElementById('progress-cefr-bar');
    if (heatbar) {
      if (totalCards === 0) {
        heatbar.innerHTML = '<div class="heat-seg" style="flex:1;background:var(--paper-deep);text-align:center;color:var(--pencil);font-size:0.6875rem;padding:0.35rem;">暂无卡片数据 (Keine Kartendaten)</div>';
      } else {
        const levels = ['A1', 'A2', 'B1', 'B2', 'C1'];
        const colors = { A1: 'var(--cefr-a1)', A2: 'var(--cefr-a2)', B1: 'var(--cefr-b1)', B2: 'var(--cefr-b2)', C1: 'var(--cefr-c1)' };
        heatbar.innerHTML = levels.map(lvl => {
          const count = cefrCounts[lvl] || 0;
          if (count === 0) return '';
          const pct = Math.round((count / totalCards) * 100);
          return `
            <div class="heat-seg" style="flex:${count};background:${colors[lvl]};" title="${lvl}: ${count} 张 (${pct}%)">
              <span class="heat-seg-label">${lvl} ${pct}%</span>
            </div>
          `;
        }).join('');
      }
    }

    renderTrendChart(stats.trend || []);

    const milestonesEl = document.getElementById('progress-milestones');
    if (milestonesEl) {
      const ms = stats.milestones || [];
      milestonesEl.innerHTML = ms.map((m, idx) => `
        <div class="dossier-stamp ${m.unlocked ? 'unlocked' : ''}">
          <div class="stamp-header">
            <span class="stamp-seal-tag">[ SIEGEL ${String(idx + 1).padStart(2, '0')} ]</span>
            <span class="stamp-icon">${m.icon}</span>
          </div>
          <div>
            <div class="stamp-title">${esc(m.title)}</div>
            <div class="stamp-desc">${esc(m.desc)}</div>
          </div>
          <div class="stamp-status-line">
            <span>STATUS</span>
            <span class="${m.unlocked ? 'stamp-status-unlocked' : 'stamp-status-locked'}">
              ${m.unlocked ? '✓ FREIGESCHALTET' : '○ OFFEN'}
            </span>
          </div>
        </div>
      `).join('');
    }

    const errorsWrap = document.getElementById('progress-errors-wrap');
    const errorsList = document.getElementById('progress-errors-list');
    const topErrors = stats.top_errors || [];
    if (errorsWrap && errorsList) {
      if (topErrors.length > 0) {
        errorsWrap.classList.remove('hidden');
        errorsList.innerHTML = topErrors.map(e => `
          <div class="dossier-error-row">
            <span class="error-col-word">${esc(e.word)}</span>
            <span class="error-col-def">${esc(e.definition_zh)}</span>
            <span class="error-col-stat">${e.wrong_count} 误 / ${e.correct_count} 正</span>
          </div>
        `).join('');
      } else {
        errorsWrap.classList.add('hidden');
      }
    }
  } catch (e) {
    console.error('Failed to load progress stats:', e);
  }
}

export function renderTrendChart(trend) {
  const svg = document.getElementById('progress-chart-svg');
  if (!svg) return;

  const w = 760;
  const h = 100;
  const padX = 14;
  const padY = 12;

  const maxVal = Math.max(...trend.map(d => (d.cards_added || 0) + (d.cards_mastered || 0)), 4);
  const step = (w - padX * 2) / (trend.length - 1 || 1);

  const points = trend.map((d, i) => {
    const val = (d.cards_added || 0) + (d.cards_mastered || 0);
    const x = padX + i * step;
    const y = h - padY - ((val / maxVal) * (h - padY * 2));
    return { x, y, val, date: d.date };
  });

  const polylineStr = points.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const areaPathStr = `M ${points[0].x.toFixed(1)} ${h - padY} ` +
    points.map(p => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ') +
    ` L ${points[points.length - 1].x.toFixed(1)} ${h - padY} Z`;

  svg.innerHTML = `
    <defs>
      <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.18" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0" />
      </linearGradient>
    </defs>
    <line x1="${padX}" y1="${h - padY}" x2="${w - padX}" y2="${h - padY}" stroke="var(--rule)" stroke-width="1" />
    <line x1="${padX}" y1="${h/2}" x2="${w - padX}" y2="${h/2}" stroke="var(--rule-light)" stroke-width="1" stroke-dasharray="3,3" />
    <path d="${areaPathStr}" fill="url(#chartGrad)" />
    <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="square" points="${polylineStr}" />
    ${points.filter(p => p.val > 0).map(p => `
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="var(--ink)" stroke="#fff" stroke-width="2">
        <title>${p.date}: +${p.val} 张卡片 (Hinzugefügt / Gemeistert)</title>
      </circle>
    `).join('')}
  `;

  const axisStart = document.getElementById('chart-axis-start');
  if (axisStart && trend.length > 0) {
    axisStart.textContent = `● ${trend[0].date} (START)`;
  }
}
