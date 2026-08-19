/* DeLector - Continuous Exhibition Folio (Atelier Landing Page Learning Progress Ledger) */
'use strict';

import { esc, api } from './core.js';
import { Companion } from './companion.js';

let currentFolioIndex = 0;
const FOLIO_SECTIONS = [
  'folio-sec-metrics',
  'folio-sec-spectrum',
  'folio-sec-errors',
  'folio-sec-milestones'
];

const GERMAN_MOTTOS = [
  { de: "Es ist noch kein Meister vom Himmel gefallen.", zh: "没有人生来就是大师，精进源于日复一日的沉淀。", author: "Deutsches Sprichwort" },
  { de: "Wer fremde Sprachen nicht kennt, weiß nichts von seiner eigenen.", zh: "不谙异国语言者，亦不知自身母语之妙。", author: "Johann Wolfgang von Goethe" },
  { de: "Die Grenzen meiner Sprache bedeuten die Grenzen meiner Welt.", zh: "我的语言之界限，即是我的世界之界限。", author: "Ludwig Wittgenstein" },
  { de: "Man lernt nie aus.", zh: "活到老，学到老；精读即是不断拓展认知边界。", author: "Deutsches Sprichwort" },
  { de: "Ohne Fleiß kein Preis.", zh: "不劳则无获；日积跬步，终至千里。", author: "Deutsches Sprichwort" },
  { de: "Ein Buch ist wie ein Garten, den man in der Tasche trägt.", zh: "一本书如同一座随身携带的私家花园。", author: "Arabisches Sprichwort auf Deutsch" }
];

export function updateFolioActiveTab(idx) {
  currentFolioIndex = Math.max(0, Math.min(FOLIO_SECTIONS.length - 1, idx));
  for (let i = 0; i < FOLIO_SECTIONS.length; i++) {
    const tab = document.getElementById(`folio-tab-${i}`);
    if (tab) {
      tab.classList.toggle('active', i === currentFolioIndex);
    }
  }
}

export function scrollToFolioSection(secId, tabIdx) {
  if (typeof tabIdx === 'number') {
    updateFolioActiveTab(tabIdx);
  } else {
    const idx = FOLIO_SECTIONS.indexOf(secId);
    if (idx !== -1) updateFolioActiveTab(idx);
  }

  const targetEl = document.getElementById(secId);
  if (targetEl) {
    const nav = document.getElementById('nav');
    const navHeight = nav ? nav.offsetHeight : 64;
    const rect = targetEl.getBoundingClientRect();
    const targetY = window.pageYOffset + rect.top - navHeight - 16;
    window.scrollTo({
      top: Math.max(0, targetY),
      behavior: 'smooth'
    });
  }
}

export function switchFolioPage(idx) {
  const targetIdx = Math.max(0, Math.min(FOLIO_SECTIONS.length - 1, idx));
  scrollToFolioSection(FOLIO_SECTIONS[targetIdx], targetIdx);
}

export function prevFolioPage() {
  if (currentFolioIndex > 0) {
    switchFolioPage(currentFolioIndex - 1);
  }
}

export function nextFolioPage() {
  if (currentFolioIndex < FOLIO_SECTIONS.length - 1) {
    switchFolioPage(currentFolioIndex + 1);
  }
}

export function renderMarquees(stats = {}) {
  const topTrack = document.getElementById('marquee-row-top');
  const bottomTrack = document.getElementById('marquee-row-bottom');

  if (topTrack) {
    // Upper row: Classic German quotes & literary mottoes
    const quoteItems = [
      { de: "Es ist noch kein Meister vom Himmel gefallen.", zh: "没有人生来就是大师", author: "Deutsches Sprichwort" },
      { de: "Die Grenzen meiner Sprache bedeuten die Grenzen meiner Welt.", zh: "我的语言之界限即我的世界之界限", author: "Ludwig Wittgenstein" },
      { de: "Wer fremde Sprachen nicht kennt, weiß nichts von seiner eigenen.", zh: "不谙外语者亦不知母语之妙", author: "Johann Wolfgang von Goethe" },
      { de: "Ein Buch ist wie ein Garten, den man in der Tasche trägt.", zh: "随身携带的私家花园", author: "Arabisches Sprichwort" },
      { de: "Man lernt nie aus.", zh: "活到老学到老，拓展认知边界", author: "Deutsches Sprichwort" },
      { de: "Aller Anfang ist schwer.", zh: "万事开头难，坚持即胜利", author: "Deutsches Sprichwort" },
      { de: "Ohne Fleiß kein Preis.", zh: "不劳无获，日积跬步终至千里", author: "Deutsches Sprichwort" }
    ];

    const quoteHtml = quoteItems.map(q => `
      <div class="marquee-item marquee-quote">
        <span class="marquee-dot">✦</span>
        <span class="marquee-text-de">“${esc(q.de)}”</span>
        <span class="marquee-text-zh">${esc(q.zh)}</span>
        <span class="marquee-tag">[${esc(q.author)}]</span>
      </div>
    `).join('');

    // Duplicate twice for seamless -50% translateX loop
    topTrack.innerHTML = quoteHtml + quoteHtml;
  }

  if (bottomTrack) {
    // Lower row: Live metrics and stats battle report
    const streak = stats.streak || 0;
    const vocab = stats.mastered_vocab || 0;
    const grammar = stats.mastered_grammar || 0;
    const articles = stats.total_articles || 0;
    const accuracy = stats.accuracy_pct || 0;
    const minutes = stats.total_study_minutes || 0;
    const totalCards = stats.total_cards || 0;

    const statItems = [
      { icon: '🔥', label: 'STREAK', val: `${streak} TAGE`, desc: '连续研读' },
      { icon: '📖', label: 'VOKABELN', val: `${vocab} WÖRTER`, desc: '已掌握词汇' },
      { icon: '🌳', label: 'GRAMMATIK', val: `${grammar} REGELN`, desc: '核心语法考点' },
      { icon: '📑', label: 'ARTIKEL', val: `${articles} TEXTE`, desc: '精读篇数' },
      { icon: '🎯', label: 'GENAUIGKEIT', val: `${accuracy}%`, desc: '测验正答率' },
      { icon: '⏱', label: 'ZEIT', val: `${minutes} MIN`, desc: '专注学时' },
      { icon: '🗂', label: 'KARTEN', val: `${totalCards} GESAMT`, desc: '卡片总库' }
    ];

    const statHtml = statItems.map(s => `
      <div class="marquee-item marquee-stat">
        <span class="marquee-dot coral">●</span>
        <span class="marquee-stat-label">${s.label}</span>
        <span class="marquee-stat-val">${s.val}</span>
        <span class="marquee-stat-desc">${s.desc}</span>
      </div>
    `).join('');

    // Duplicate twice for seamless -50% translateX loop
    bottomTrack.innerHTML = statHtml + statHtml;
  }
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

  // Render initial marquee even before async stats arrive
  renderMarquees();

  try {
    const stats = await api('/api/progress/stats');

    // Render marquees with loaded real-time stats
    renderMarquees(stats);

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
    if (stAccuracy) stAccuracy.textContent = `${stats.accuracy_pct || 0}%`;
    if (stMinutes) stMinutes.textContent = stats.total_study_minutes || 0;

    // Sync Companion Mascot Studio & check streak milestone
    Companion.syncStudio();
    const streak = stats.streak || 0;
    const lastStreak = parseInt(localStorage.getItem('delector_streak_celebrated') || '0', 10);
    if (streak >= 3 && streak > lastStreak) {
      localStorage.setItem('delector_streak_celebrated', streak.toString());
      setTimeout(() => {
        Companion.celebrate('streak', { n: streak });
      }, 800);
    }

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
        const colors = {
          A1: 'var(--hl-A1, #E3EFFB)',
          A2: 'var(--hl-A2, #D6ECCF)',
          B1: 'var(--hl-B1, #FDE9BD)',
          B2: 'var(--hl-B2, #FDE0D7)',
          C1: 'var(--hl-C1, #EFE2FA)'
        };
        heatbar.innerHTML = levels.map(lvl => {
          const count = cefrCounts[lvl] || 0;
          if (count === 0) return '';
          const pct = Math.round((count / totalCards) * 100);
          return `
            <div class="heat-seg" style="flex:${count};background:${colors[lvl]};" title="${lvl}: ${count} 张 (${pct}%)">
              <span class="heat-seg-label" style="color:var(--ink);">${lvl} ${pct}%</span>
            </div>
          `;
        }).join('');
      }
    }

    const cefrLadder = document.getElementById('progress-cefr-ladder');
    if (cefrLadder) {
      const levels = [
        { code: 'A1', name: '入门级 (Elementar A1)', color: 'var(--hl-A1)', ink: 'var(--hl-A1-ink)' },
        { code: 'A2', name: '基础级 (Grundstufe A2)', color: 'var(--hl-A2)', ink: 'var(--hl-A2-ink)' },
        { code: 'B1', name: '进阶级 (Mittelstufe B1)', color: 'var(--hl-B1)', ink: 'var(--hl-B1-ink)' },
        { code: 'B2', name: '高阶级 (Oberstufe B2)', color: 'var(--hl-B2)', ink: 'var(--hl-B2-ink)' },
        { code: 'C1', name: '精通级 (Fortgeschritten C1)', color: 'var(--hl-C1)', ink: 'var(--hl-C1-ink)' }
      ];

      cefrLadder.innerHTML = levels.map(l => {
        const count = cefrCounts[l.code] || 0;
        const pct = totalCards > 0 ? Math.round((count / totalCards) * 100) : 0;
        return `
          <div class="cefr-ladder-row">
            <span class="cefr-ladder-badge" style="background:${l.color};color:${l.ink};">${l.code}</span>
            <div class="cefr-ladder-info">
              <div class="cefr-ladder-header">
                <span class="cefr-ladder-name">${l.name}</span>
                <span class="cefr-ladder-count"><b>${count}</b> 张 · ${pct}%</span>
              </div>
              <div class="cefr-ladder-track">
                <div class="cefr-ladder-fill" style="width:${pct}%;background:${l.ink};"></div>
              </div>
            </div>
          </div>
        `;
      }).join('');
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
              ${m.unlocked ? '✓ 已加盖钢印' : '○ 待达成'}
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
        errorsList.innerHTML = topErrors.map(e => `
          <div class="dossier-error-row">
            <span class="error-col-word">${esc(e.word)}</span>
            <span class="error-col-def">${esc(e.definition_zh)}</span>
            <span class="error-col-stat">${e.wrong_count} 误 / ${e.correct_count} 正</span>
          </div>
        `).join('');
      } else {
        errorsList.innerHTML = `
          <div class="dossier-empty-state">
            <span>✓ 暂无重点易错词汇记录（Keine Fehlerschwerpunkte）</span>
          </div>
        `;
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
  const padX = 16;
  const padY = 14;

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
        <stop offset="0%" stop-color="var(--coral, #ED6F5C)" stop-opacity="0.22" />
        <stop offset="100%" stop-color="var(--coral, #ED6F5C)" stop-opacity="0.0" />
      </linearGradient>
    </defs>
    <line x1="${padX}" y1="${h - padY}" x2="${w - padX}" y2="${h - padY}" stroke="var(--rule, #D8D0C2)" stroke-width="1" />
    <line x1="${padX}" y1="${h / 2}" x2="${w - padX}" y2="${h / 2}" stroke="var(--line-soft, rgba(21,20,15,0.08))" stroke-width="1" stroke-dasharray="3,3" />
    <path d="${areaPathStr}" fill="url(#chartGrad)" />
    <polyline fill="none" stroke="var(--coral, #ED6F5C)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${polylineStr}" />
    ${points.filter(p => p.val > 0).map(p => `
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="var(--ink, #15140F)" stroke="#fff" stroke-width="2">
        <title>${p.date}: +${p.val} 张卡片 (Hinzugefügt / Gemeistert)</title>
      </circle>
    `).join('')}
  `;

  const axisStart = document.getElementById('chart-axis-start');
  if (axisStart && trend.length > 0) {
    axisStart.textContent = `● ${trend[0].date} (START)`;
  }
}

// Global exports on window
if (typeof window !== 'undefined') {
  window.switchFolioPage = switchFolioPage;
  window.prevFolioPage = prevFolioPage;
  window.nextFolioPage = nextFolioPage;
  window.scrollToFolioSection = scrollToFolioSection;
  window.loadProgress = loadProgress;
  window.renderTrendChart = renderTrendChart;
  window.renderMarquees = renderMarquees;
}

