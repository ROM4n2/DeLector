/* DeLector - German Companion Mascot System (Eule & Friends) */
'use strict';

import { ShadowPlayer, playGermanAudio } from './player.js';
import { cardState, selectSegmentLists, buildDeckFromLists } from './cd-state.js';
import {
  getCompanionViewport,
  getAvoidPadding,
  collectNoParkRects,
  intersectsAny
} from './companion-obstacles.js';
import {
  createLifecycleConditions,
  resolveLifecycleState,
  lifecycleTitle
} from './companion-lifecycle.js';

// P3 状态机定时器：看门狗只证明「在途却完全没有字节」，error 驻留避免永久红点。
const TURN_WATCHDOG_MS = 120000;
const ERROR_DWELL_MS = 30000;

// ── SVG Character Templates (Standardized classes & dynamic CSS vars) ───────
export const CHARACTERS = {
  owl: {
    id: 'owl',
    name: 'Eule',
    title: '歌德猫头鹰',
    primary: '#6b4f8f',
    accent: '#e8953a',
    svg: `
      <svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="owl-belly-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="var(--c-accent)" stop-opacity="0.25"/>
            <stop offset="100%" stop-color="var(--c-accent)" stop-opacity="0.05"/>
          </radialGradient>
        </defs>
        <!-- Owl Body & Wings -->
        <g class="char-body">
          <!-- Ear Tufts -->
          <polygon points="26,30 18,12 38,24" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          <polygon points="74,30 82,12 62,24" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          
          <!-- Main Torso -->
          <ellipse cx="50" cy="56" rx="34" ry="36" fill="var(--c-primary)" stroke="#222" stroke-width="2.5"/>
          
          <!-- Belly Feathers -->
          <ellipse cx="50" cy="62" rx="22" ry="24" fill="#faf8f5" stroke="#222" stroke-width="1.5"/>
          <path d="M 42,54 Q 50,60 58,54 M 40,64 Q 50,70 60,64 M 44,74 Q 50,78 56,74" fill="none" stroke="var(--c-accent)" stroke-width="2" stroke-linecap="round"/>
          
          <!-- Wings -->
          <path d="M 18,46 C 14,58 20,74 28,78 C 24,70 22,58 26,48 Z" fill="var(--c-primary)" stroke="#222" stroke-width="2" filter="brightness(0.9)"/>
          <path d="M 82,46 C 86,58 80,74 72,78 C 76,70 78,58 74,48 Z" fill="var(--c-primary)" stroke="#222" stroke-width="2" filter="brightness(0.9)"/>
          
          <!-- Feet -->
          <ellipse cx="40" cy="91" rx="5" ry="3.5" fill="var(--c-accent)" stroke="#222" stroke-width="1.5"/>
          <ellipse cx="60" cy="91" rx="5" ry="3.5" fill="var(--c-accent)" stroke="#222" stroke-width="1.5"/>
        </g>
        
        <!-- Big Owl Eyes (Animated blink) -->
        <g class="char-eyes-wrap">
          <!-- Left Eye Frame -->
          <circle cx="37" cy="40" r="14" fill="#fff" stroke="#222" stroke-width="2"/>
          <g class="char-eye" style="transform-origin: 37px 40px;">
            <circle cx="37" cy="40" r="8" fill="#222"/>
            <circle cx="39.5" cy="37.5" r="3" fill="#fff"/>
            <circle cx="35" cy="42" r="1.2" fill="#fff"/>
          </g>
          <!-- Spectacles Bridge -->
          <path d="M 48,40 Q 50,38 52,40" fill="none" stroke="var(--c-accent)" stroke-width="2.5" stroke-linecap="round"/>
          <!-- Right Eye Frame -->
          <circle cx="63" cy="40" r="14" fill="#fff" stroke="#222" stroke-width="2"/>
          <g class="char-eye" style="transform-origin: 63px 40px;">
            <circle cx="63" cy="40" r="8" fill="#222"/>
            <circle cx="65.5" cy="37.5" r="3" fill="#fff"/>
            <circle cx="61" cy="42" r="1.2" fill="#fff"/>
          </g>
        </g>
        
        <!-- Beak -->
        <polygon points="50,44 44,52 56,52" fill="var(--c-accent)" stroke="#222" stroke-width="1.8" stroke-linejoin="round"/>
      </svg>
    `
  },
  cat: {
    id: 'cat',
    name: 'Katze',
    title: '学者猫',
    primary: '#4f8f6b',
    accent: '#f0e6d0',
    svg: `
      <svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <g class="char-body">
          <!-- Cat Ears -->
          <polygon points="25,32 20,10 42,22" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          <polygon points="26,29 23,15 38,23" fill="var(--c-accent)"/>
          <polygon points="75,32 80,10 58,22" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          <polygon points="74,29 77,15 62,23" fill="var(--c-accent)"/>
          
          <!-- Head & Body -->
          <ellipse cx="50" cy="58" rx="34" ry="34" fill="var(--c-primary)" stroke="#222" stroke-width="2.5"/>
          <ellipse cx="50" cy="65" rx="20" ry="22" fill="#faf8f5" stroke="#222" stroke-width="1.5"/>
          
          <!-- Scholar Bowtie -->
          <polygon points="44,72 50,75 44,78" fill="var(--c-accent)" stroke="#222" stroke-width="1.5"/>
          <polygon points="56,72 50,75 56,78" fill="var(--c-accent)" stroke="#222" stroke-width="1.5"/>
          <circle cx="50" cy="75" r="2.5" fill="#d9663f" stroke="#222" stroke-width="1"/>
          
          <!-- Whiskers -->
          <line x1="22" y1="52" x2="34" y2="54" stroke="#222" stroke-width="1.5" stroke-linecap="round"/>
          <line x1="20" y1="58" x2="33" y2="58" stroke="#222" stroke-width="1.5" stroke-linecap="round"/>
          <line x1="78" y1="52" x2="66" y2="54" stroke="#222" stroke-width="1.5" stroke-linecap="round"/>
          <line x1="80" y1="58" x2="67" y2="58" stroke="#222" stroke-width="1.5" stroke-linecap="round"/>
          
          <!-- Paws -->
          <ellipse cx="38" cy="89" rx="6" ry="4" fill="#faf8f5" stroke="#222" stroke-width="1.5"/>
          <ellipse cx="62" cy="89" rx="6" ry="4" fill="#faf8f5" stroke="#222" stroke-width="1.5"/>
        </g>
        
        <!-- Eyes -->
        <g class="char-eyes-wrap">
          <circle cx="36" cy="44" r="11" fill="#fff" stroke="#222" stroke-width="2"/>
          <g class="char-eye" style="transform-origin: 36px 44px;">
            <ellipse cx="36" cy="44" rx="7" ry="8.5" fill="#222"/>
            <circle cx="38" cy="41" r="2.5" fill="#fff"/>
          </g>
          <circle cx="64" cy="44" r="11" fill="#fff" stroke="#222" stroke-width="2"/>
          <g class="char-eye" style="transform-origin: 64px 44px;">
            <ellipse cx="64" cy="44" rx="7" ry="8.5" fill="#222"/>
            <circle cx="66" cy="41" r="2.5" fill="#fff"/>
          </g>
        </g>
        
        <!-- Nose & Mouth -->
        <polygon points="50,52 47,49 53,49" fill="#d9663f"/>
        <path d="M 47,53 Q 50,56 53,53" fill="none" stroke="#222" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    `
  },
  fox: {
    id: 'fox',
    name: 'Fuchs',
    title: '灵动狐',
    primary: '#d9663f',
    accent: '#f4ede2',
    svg: `
      <svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <g class="char-body">
          <!-- Fox Ears -->
          <polygon points="22,34 16,8 42,20" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          <polygon points="23,30 19,14 36,22" fill="#222"/>
          <polygon points="78,34 84,8 58,20" fill="var(--c-primary)" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
          <polygon points="77,30 81,14 64,22" fill="#222"/>
          
          <!-- Head/Body -->
          <ellipse cx="50" cy="56" rx="34" ry="34" fill="var(--c-primary)" stroke="#222" stroke-width="2.5"/>
          
          <!-- White Cheeks & Chest -->
          <path d="M 18,54 C 20,70 34,84 50,86 C 66,84 80,70 82,54 C 70,60 58,52 50,60 C 42,52 30,60 18,54 Z" fill="var(--c-accent)" stroke="#222" stroke-width="1.8"/>
          
          <!-- Paws -->
          <ellipse cx="38" cy="89" rx="5.5" ry="3.5" fill="#222"/>
          <ellipse cx="62" cy="89" rx="5.5" ry="3.5" fill="#222"/>
        </g>
        
        <!-- Eyes -->
        <g class="char-eyes-wrap">
          <g class="char-eye" style="transform-origin: 36px 42px;">
            <ellipse cx="36" cy="42" rx="6.5" ry="8" fill="#222"/>
            <circle cx="38" cy="39.5" r="2.5" fill="#fff"/>
          </g>
          <g class="char-eye" style="transform-origin: 64px 42px;">
            <ellipse cx="64" cy="42" rx="6.5" ry="8" fill="#222"/>
            <circle cx="66" cy="39.5" r="2.5" fill="#fff"/>
          </g>
        </g>
        
        <!-- Snout Nose -->
        <polygon points="50,61 45,56 55,56" fill="#222" stroke="#222" stroke-width="1" stroke-linejoin="round"/>
      </svg>
    `
  },
  robot: {
    id: 'robot',
    name: 'Roboter',
    title: '包豪斯机甲',
    primary: '#4a6fa5',
    accent: '#9bd1f0',
    svg: `
      <svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <g class="char-body">
          <!-- Antenna -->
          <line x1="50" y1="12" x2="50" y2="24" stroke="#222" stroke-width="2.5"/>
          <circle cx="50" cy="10" r="5" fill="var(--c-accent)" stroke="#222" stroke-width="2"/>
          
          <!-- Head / Body Box (Bauhaus Rounded Box) -->
          <rect x="20" y="24" width="60" height="52" rx="10" ry="10" fill="var(--c-primary)" stroke="#222" stroke-width="2.5"/>
          
          <!-- Ear Bolts -->
          <rect x="14" y="44" width="6" height="12" rx="2" fill="#222"/>
          <rect x="80" y="44" width="6" height="12" rx="2" fill="#222"/>
          
          <!-- Chest Plate / Screen -->
          <rect x="28" y="32" width="44" height="24" rx="6" ry="6" fill="#1c2430" stroke="#222" stroke-width="1.8"/>
          
          <!-- Speaker Mouth / Meter -->
          <line x1="34" y1="64" x2="66" y2="64" stroke="#222" stroke-width="2" stroke-linecap="round"/>
          <circle cx="38" cy="64" r="1.5" fill="var(--c-accent)"/>
          <circle cx="46" cy="64" r="1.5" fill="var(--c-accent)"/>
          <circle cx="54" cy="64" r="1.5" fill="var(--c-accent)"/>
          <circle cx="62" cy="64" r="1.5" fill="var(--c-accent)"/>
          
          <!-- Legs -->
          <rect x="34" y="76" width="10" height="12" rx="3" fill="#222"/>
          <rect x="56" y="76" width="10" height="12" rx="3" fill="#222"/>
        </g>
        
        <!-- Glowing Eyes -->
        <g class="char-eyes-wrap">
          <g class="char-eye" style="transform-origin: 39px 44px;">
            <circle cx="39" cy="44" r="6" fill="var(--c-accent)"/>
            <circle cx="40" cy="43" r="2" fill="#fff"/>
          </g>
          <g class="char-eye" style="transform-origin: 61px 44px;">
            <circle cx="61" cy="44" r="6" fill="var(--c-accent)"/>
            <circle cx="62" cy="43" r="2" fill="#fff"/>
          </g>
        </g>
      </svg>
    `
  }
};

// ── Authentic German A1–B1 Phrases Library ──────────────────────────────────
export const PHRASES = {
  greeting: [
    { de: "Hallo! Schön, dich zu sehen!", zh: "你好！很高兴见到你！" },
    { de: "Guten Tag! Bereit zum Deutschlernen?", zh: "日安！准备好学德语了吗？" },
    { de: "Willkommen zurück am Lesepult!", zh: "欢迎回到德语研读台！" }
  ],
  card_vocab: [
    { de: "Super! Ein neues Wort gelernt!", zh: "太棒了！又学到一个新单词！" },
    { de: "Ausgezeichnet! Dein Wortschatz wächst!", zh: "优秀！你的词汇量又增长了！" },
    { de: "Wort für Wort zum Erfolg!", zh: "一词一句，渐入佳境！" }
  ],
  card_grammar: [
    { de: "Klasse! Eine neue Grammatikregel gemeistert!", zh: "太棒了！掌握了一条新语法考点！" },
    { de: "Sehr gut! Die deutsche Struktur wird klarer!", zh: "很好！德语句法结构越来越清晰了！" },
    { de: "Wunderbar! Grammatik ist das Fundament!", zh: "极好！语法是语言的基石！" }
  ],
  review_good: [
    { de: "Perfekt erinnert! Weiter so!", zh: "完美回忆！继续保持！" },
    { de: "Genau richtig! Das Langzeitgedächtnis arbeitet!", zh: "完全正确！长期记忆正在生效！" },
    { de: "Toll gemacht! Schritt für Schritt voran!", zh: "做得好！一步一个脚印稳步向前！" }
  ],
  review_hard: [
    { de: "Kein Problem! Wiederholung festigt das Wissen!", zh: "没关系！重复是强化记忆的关键！" },
    { de: "Bleib dran! Aller Anfang ist schwer.", zh: "坚持住！万事开头难，熟能生巧。" },
    { de: "Übung macht den Meister!", zh: "熟能生巧，多复习几次就记住了！" }
  ],
  cloze_great: [
    { de: "Stark! {pct}% Trefferquote!", zh: "真厉害！完形命中率达成 {pct}%！" },
    { de: "Großartig! Du beherrschst den Text!", zh: "太出色了！你已经完全吃透了文本！" },
    { de: "Glänzende Leistung im Lückentext!", zh: "完形填空实战表现极其亮眼！" }
  ],
  quiz_done: [
    { de: "Test abgeschlossen! {pct}% richtig!", zh: "测验完成！正确率 {pct}%！" },
    { de: "Gute Arbeit bei der Wiederholung!", zh: "专项复习测验完成得非常出色！" },
    { de: "Fleiß zahlt sich aus!", zh: "天道酬勤，每一分努力都有回报！" }
  ],
  streak: [
    { de: "Schon {n} Tage in Folge! Fantastisch!", zh: "已经连续打卡 {n} 天！太不可思议了！" },
    { de: "{n} Tage Ausdauer! Du bist ein Vorbild!", zh: "连续 {n} 天的毅力！你是学习的榜样！" }
  ],
  idle: [
    { de: "Lass uns etwas Schönes lesen!", zh: "我们一起读篇优美的德语文章吧！" },
    { de: "Bereit für den nächsten Textabschnitt?", zh: "准备好开启下一段德语阅读了吗？" },
    { de: "Kleine Schritte führen zum großen Ziel!", zh: "跬步千里，持续阅读带来认知跃迁！" },
    { de: "Ich begleite dich beim Lernen!", zh: "我会一直在这里陪伴你的德语之旅！" }
  ]
};

// ── 当前视图识别（Agent 上下文来源隔离的唯一判据） ──────────────────────────
const ACTIVE_VIEW_IDS = ['reader', 'home', 'cards', 'progress', 'writer', 'exam', 'search', 'encounter', 'german'];

/** 返回当前激活的 view（无激活视图时返回空串）。 */
export function getActiveView() {
  if (typeof document === 'undefined' || typeof document.getElementById !== 'function') return '';
  for (const view of ACTIVE_VIEW_IDS) {
    const el = document.getElementById('view-' + view);
    if (el && el.classList && el.classList.contains('active')) return view;
  }
  return '';
}

/** 返回当前页面/文章的会话 scope key：article:<id> 或 view:<name>。 */
export function getCompanionScopeKey() {
  const view = getActiveView();
  const articleId = window.state && window.state.currentArticle
    ? window.state.currentArticle.id
    : null;
  if (view === 'reader' && articleId !== null && articleId !== undefined && articleId !== '') {
    return 'article:' + articleId;
  }
  return 'view:' + (view || 'global');
}

/** 读取卡盒当前卡面词条（仅 deck 视图；grid 无选中态，返回空）。 */
function readCardBoxContext() {
  const catalog = cardState && cardState.catalog;
  if (!catalog || catalog.viewMode !== 'deck') return '';
  const { vList, gList } = selectSegmentLists(catalog);
  const deck = buildDeckFromLists(vList, gList);
  const idx = cardState.deck && Number.isFinite(cardState.deck.index) ? cardState.deck.index : 0;
  const card = deck[idx];
  if (!card) return '';
  const segment = catalog.segment || 'due';
  const lines = ['【当前卡盒词条】', `分段: ${segment}`];
  if (card._type === 'vocab') {
    if (card.word) lines.push(`词: ${card.word}`);
    if (card.lemma) lines.push(`词元: ${card.lemma}`);
    if (card.definition_zh) lines.push(`释义: ${card.definition_zh}`);
    if (card.cefr_level || card.pos || card.gender) {
      lines.push(`词性/等级: ${[card.pos, card.gender, card.cefr_level].filter(Boolean).join(' · ')}`);
    }
  } else if (card.grammar_name) {
    lines.push(`语法考点: ${card.grammar_name}`);
    if (card.explanation_zh) lines.push(`说明: ${card.explanation_zh}`);
    if (card.cefr_level) lines.push(`等级: ${card.cefr_level}`);
  }
  if (card.sentence_context) lines.push(`例句: ${card.sentence_context}`);
  return lines.join('\n');
}

/** 读取写作台当前草稿（与 writer.js 的 editorText 同口径：TreeWalker 只取文本节点）。 */
function readWriterDraftText() {
  const el = document.getElementById('ide-editor');
  if (!el) return '';
  if (typeof document.createTreeWalker === 'function' && typeof NodeFilter !== 'undefined') {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    let text = '';
    let node;
    while ((node = walker.nextNode())) {
      text += node.nodeValue;
    }
    return text.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
  }
  return (el.textContent || '').replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
}

// ── SVG Sanitizer & Custom Character Processing ────────────────────────────
export function sanitizeSvg(rawSvg) {
  if (typeof rawSvg !== 'string' || !rawSvg.trim()) {
    throw new Error('SVG 内容为空');
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(rawSvg.trim(), 'image/svg+xml');

  const parserError = doc.querySelector('parsererror');
  if (parserError) {
    throw new Error('SVG XML 解析失败: ' + (parserError.textContent?.slice(0, 100) || '格式错误'));
  }

  const svgEl = doc.querySelector('svg');
  if (!svgEl) {
    throw new Error('未找到有效的 <svg> 根节点');
  }

  const ALLOWED_TAGS = new Set([
    'svg', 'g', 'circle', 'rect', 'path', 'ellipse', 'line',
    'polygon', 'polyline', 'text', 'tspan', 'defs',
    'lineargradient', 'radialgradient', 'stop', 'clippath', 'mask'
  ]);

  // Recursively sanitize all descendant elements
  const allElements = Array.from(svgEl.querySelectorAll('*'));
  for (const el of allElements) {
    const tag = el.tagName.toLowerCase();
    if (!ALLOWED_TAGS.has(tag)) {
      el.remove();
      continue;
    }

    // Sanitize attributes
    const attrs = Array.from(el.attributes);
    for (const attr of attrs) {
      const name = attr.name.toLowerCase();
      const val = attr.value.trim().toLowerCase();

      // Block any event handlers (onclick, onload, onerror, etc.)
      if (name.startsWith('on')) {
        el.removeAttribute(attr.name);
        continue;
      }

      // Block dangerous protocol schemes or script injections
      if (val.includes('javascript:') || val.includes('vbscript:') || val.includes('data:text/html') || val.includes('expression(')) {
        el.removeAttribute(attr.name);
        continue;
      }

      // href / xlink:href only permitted if pointing to local SVG IDs (e.g. #gradientId)
      if (name === 'href' || name === 'xlink:href') {
        if (!attr.value.trim().startsWith('#')) {
          el.removeAttribute(attr.name);
          continue;
        }
      }

      // Style attribute check
      if (name === 'style') {
        if (/url\s*\(|expression|javascript|@import|-moz-binding/i.test(attr.value)) {
          el.removeAttribute(attr.name);
        }
      }
    }
  }

  // Sanitize root svg attributes
  const rootAttrs = Array.from(svgEl.attributes);
  for (const attr of rootAttrs) {
    const name = attr.name.toLowerCase();
    const val = attr.value.trim().toLowerCase();
    if (name.startsWith('on') || val.includes('javascript:') || val.includes('vbscript:') || val.includes('data:text/html') || val.includes('expression(')) {
      svgEl.removeAttribute(attr.name);
    }
  }

  // Ensure companion-svg class on root
  const currentClass = svgEl.getAttribute('class') || '';
  if (!currentClass.includes('companion-svg')) {
    svgEl.setAttribute('class', (currentClass + ' companion-svg').trim());
  }

  // Ensure viewBox
  if (!svgEl.getAttribute('viewBox')) {
    const w = parseFloat(svgEl.getAttribute('width')) || 100;
    const h = parseFloat(svgEl.getAttribute('height')) || 100;
    svgEl.setAttribute('viewBox', `0 0 ${w} ${h}`);
  }

  return svgEl.outerHTML;
}

// ── 气泡定位几何辅助 ────────────────────────────────────────────────────────
function clamp(value, min, max) {
  if (max < min) return min;
  return Math.min(Math.max(value, min), max);
}

/** 视觉视口；复用 companion-obstacles 的统一实现（含 --writer-keyboard-inset 兜底） */
function getVisualViewport() {
  return getCompanionViewport();
}

/** 把 computed transform-origin 解析成元素局部 px 坐标 */
function parseTransformOrigin(value, width, height) {
  const parts = String(value || '').trim().split(/\s+/);
  const resolve = (token, axisSize) => {
    if (!token || token === 'center') return axisSize / 2;
    if (token === 'left' || token === 'top') return 0;
    if (token === 'right' || token === 'bottom') return axisSize;
    const num = parseFloat(token);
    if (!Number.isFinite(num)) return axisSize / 2;
    return token.endsWith('%') ? (num / 100) * axisSize : num;
  };
  return {
    x: resolve(parts[0], width),
    y: resolve(parts[1] || parts[0], height)
  };
}

// ── Companion Mascot Singleton Controller ────────────────────────────────────
/** 模态（写作页移动端 sheet）打开期间临时收起的气泡，关闭后自动恢复 */
let bubbleSuspendedByModal = false;
/** 气泡自然收起的绝对时间戳；挂起期间计时不暂停，恢复前必须复核是否已过期 */
let bubbleExpiresAt = 0;
const BUBBLE_TTL_MS = 6500;

export const Companion = {
  charId: 'owl',
  name: '',
  color: '',
  soundEnabled: true,
  enabled: true,
  panelOpen: false,
  bubbleTimer: null,
  lastSpeechAt: 0,
  lastPhraseKey: '',

  // P3 生机状态：条件驱动，data-state 单源派生，不散落 class。
  _conditions: createLifecycleConditions(),
  _state: 'idle',
  _proposalCount: 0,
  _turnWatchdog: null,
  _errorDwell: null,
  _errorReason: '',
  _bubbleSuppressedBy: '',
  _dragReleasePending: false,
  _bubbleResolvePending: false,
  _lifecycleBound: false,

  get state() {
    return this._state;
  },

  get conditions() {
    return { ...this._conditions };
  },

  _applyLifecycleState(reason) {
    const next = resolveLifecycleState(this._conditions);
    const prev = this._state;
    this._state = next;

    const compEl = document.getElementById('companion');
    if (compEl) {
      compEl.setAttribute('data-state', next);
    }
    const charEl = document.getElementById('companion-char');
    if (charEl) {
      charEl.title = lifecycleTitle(next);
    }
    const avatarEl = document.getElementById('companion-avatar');
    if (avatarEl) {
      avatarEl.setAttribute('aria-label', '伴读角色设置与对话 · ' + lifecycleTitle(next).replace('伴读 · ', ''));
    }

    // 姿态只有两个来源：data-state 与情绪类；离开 idle/speaking 时摘掉情绪类。
    if (next !== 'idle' && next !== 'speaking') {
      this._clearEmotionClasses();
    }

    if (prev !== next && compEl) {
      compEl.dispatchEvent(new CustomEvent('companion:statechange', {
        bubbles: true,
        detail: { from: prev, to: next, reason: reason || '' }
      }));
    }
  },

  _clearEmotionClasses() {
    document.querySelectorAll('.companion-char, .mascot-stage-char').forEach((el) => {
      el.classList.remove('is-happy', 'is-wiggle', 'is-sad');
    });
  },

  _setCondition(name, value) {
    if (!Object.prototype.hasOwnProperty.call(this._conditions, name)) return;
    if (this._conditions[name] === value) return;
    this._conditions[name] = value;
    this._applyLifecycleState(name);
  },

  _clearTurnWatchdog() {
    if (this._turnWatchdog) {
      clearTimeout(this._turnWatchdog);
      this._turnWatchdog = null;
    }
  },

  _armTurnWatchdog() {
    this._clearTurnWatchdog();
    if (!this._conditions.turnInFlight) return;
    this._turnWatchdog = setTimeout(() => {
      this._turnWatchdog = null;
      if (this._conditions.turnInFlight) {
        this.raiseError('watchdog');
      }
    }, TURN_WATCHDOG_MS);
  },

  _armErrorDwell() {
    if (this._errorDwell) clearTimeout(this._errorDwell);
    this._errorDwell = setTimeout(() => {
      this._errorDwell = null;
      this.clearError();
    }, ERROR_DWELL_MS);
  },

  /** 新一轮开始：清掉上一轮的错误与待确认阻塞语义（proposal 卡片本身不删）。 */
  beginTurn() {
    this._conditions.turnInFlight = true;
    this._conditions.toolActive = false;
    this._conditions.errorLatched = false;
    this._errorReason = '';
    if (this._errorDwell) {
      clearTimeout(this._errorDwell);
      this._errorDwell = null;
    }
    this._proposalCount = 0;
    this._conditions.proposalPending = false;
    this._applyLifecycleState('turn-start');
    this._armTurnWatchdog();
  },

  /** 任意 SSE 字节都证明连接还活着：看门狗重置；watchdog 型 error 自动解除。 */
  touchTurn() {
    if (this._conditions.errorLatched && this._errorReason === 'watchdog') {
      this._conditions.errorLatched = false;
      this._errorReason = '';
      this._applyLifecycleState('watchdog-recovered');
    }
    this._armTurnWatchdog();
  },

  setToolActive(active) {
    this._setCondition('toolActive', Boolean(active));
  },

  endTurn() {
    this._conditions.turnInFlight = false;
    this._conditions.toolActive = false;
    this._clearTurnWatchdog();
    this._applyLifecycleState('turn-end');
  },

  noteProposal() {
    this._proposalCount += 1;
    this._conditions.proposalPending = true;
    this._applyLifecycleState('proposal');
  },

  resolveProposal() {
    this._proposalCount = Math.max(0, this._proposalCount - 1);
    this._conditions.proposalPending = this._proposalCount > 0;
    this._applyLifecycleState('proposal-resolved');
  },

  raiseError(reason) {
    this._conditions.turnInFlight = false;
    this._conditions.toolActive = false;
    this._conditions.errorLatched = true;
    this._errorReason = reason || 'stream';
    this._clearTurnWatchdog();
    this._applyLifecycleState('error:' + this._errorReason);
    this._armErrorDwell();
  },

  clearError() {
    if (!this._conditions.errorLatched) return;
    this._conditions.errorLatched = false;
    this._errorReason = '';
    if (this._errorDwell) {
      clearTimeout(this._errorDwell);
      this._errorDwell = null;
    }
    this._applyLifecycleState('error-clear');
  },

  setDragging(active) {
    const next = Boolean(active);
    if (next) {
      this._dragReleasePending = false;
      this._setCondition('dragging', true);
      if (this._conditions.bubbleVisible) {
        this._bubbleSuppressedBy = 'drag';
        const bubble = document.getElementById('companion-bubble');
        if (bubble) bubble.classList.add('hidden');
        this._conditions.bubbleVisible = false;
      }
      return;
    }
    // 松手不等于落点已定：P2 的 settleIfNeeded() 在同一 pointerup 里随后执行，
    // 可能带着 260ms 的 is-settling 滑动。dragging 要持续到 settle 结束，
    // 否则气泡会对着旧锚点求解。微任务等到本轮事件回调结束再判断。
    this._dragReleasePending = true;
    queueMicrotask(() => this._releaseDragIfSettled());
  },

  _releaseDragIfSettled() {
    if (!this._dragReleasePending) return;
    if (this._isSettling()) return; // 等 companion:settle-end
    this._finishDragRelease();
  },

  _finishDragRelease() {
    if (!this._dragReleasePending) return false;
    this._dragReleasePending = false;
    this._setCondition('dragging', false);
    this.schedulePanelFit();
    return this._resumeBubbleIfPending();
  },

  _onSettleEnd() {
    // 让位结束后桌宠可能换了位置，设置面板跟着重新落位。
    this.schedulePanelFit();
    const shouldResolve = this._bubbleResolvePending;
    this._bubbleResolvePending = false;
    const solvedByRelease = this._finishDragRelease();
    if (!shouldResolve || solvedByRelease) return;

    // 展示请求在 settle 期间被挂起时的补显：未过期、且未被拖拽/聚焦抑制才出现。
    const bubble = document.getElementById('companion-bubble');
    if (
      bubble &&
      bubble.classList.contains('hidden') &&
      !this._conditions.dragging &&
      !this._isEditableFocused() &&
      bubbleExpiresAt > Date.now()
    ) {
      bubble.classList.remove('hidden');
      this._setCondition('bubbleVisible', true);
    }
    this.repositionBubble();
  },

  _isSettling() {
    const cap = document.getElementById('companion');
    return Boolean(cap && cap.classList.contains('is-settling'));
  },

  _resumeBubbleIfPending() {
    if (this._bubbleSuppressedBy !== 'drag') return false;
    if (this._isEditableFocused()) {
      this._bubbleSuppressedBy = '';
      return false;
    }
    if (!bubbleExpiresAt || Date.now() >= bubbleExpiresAt) {
      this._bubbleSuppressedBy = '';
      return false;
    }
    const bubble = document.getElementById('companion-bubble');
    if (!bubble) {
      this._bubbleSuppressedBy = '';
      return false;
    }
    bubble.classList.remove('hidden');
    this._bubbleSuppressedBy = '';
    this.repositionBubble();
    this._setCondition('bubbleVisible', true);
    return true;
  },

  _isEditableTarget(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.isContentEditable) return true;
    const tag = String(el.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    return Boolean(el.closest && el.closest('[contenteditable="true"], [contenteditable=""]'));
  },

  _isEditableFocused() {
    return this._isEditableTarget(document.activeElement);
  },

  _suppressBubbleForFocus() {
    this._bubbleSuppressedBy = 'focus';
    if (this.bubbleTimer) {
      clearTimeout(this.bubbleTimer);
      this.bubbleTimer = null;
    }
    bubbleExpiresAt = 0;
    const bubble = document.getElementById('companion-bubble');
    if (bubble) bubble.classList.add('hidden');
    this._conditions.bubbleVisible = false;
    this._applyLifecycleState('bubble-focus');
  },

  _onLifecycleVisibilityChange() {
    const compEl = document.getElementById('companion');
    if (!compEl) return;
    const hidden = document.visibilityState === 'hidden';
    compEl.setAttribute('data-paused', hidden ? 'true' : 'false');
  },

  _bindLifecycleListeners() {
    if (this._lifecycleBound) return;
    this._lifecycleBound = true;

    document.addEventListener('focusin', (event) => {
      if (this._isEditableTarget(event.target)) {
        this._suppressBubbleForFocus();
      }
    });

    document.addEventListener('visibilitychange', () => {
      this._onLifecycleVisibilityChange();
    });

    // P2 在 is-settling 摘除时派发；松弛拖拽释放与气泡求解都排在这一刻之后。
    document.addEventListener('companion:settle-end', () => {
      this._onSettleEnd();
    });

    this._onLifecycleVisibilityChange();
  },

  sanitizeSvg,

  init() {
    // P3：先建立可观测的初始状态，再渲染角色；监听器只绑一次。
    this._bindLifecycleListeners();
    this._applyLifecycleState('init');

    // 0. Restore custom character SVG from localStorage if present
    const savedCustomSvg = localStorage.getItem('delector_companion_custom_svg');
    if (savedCustomSvg) {
      try {
        const cleanSvg = sanitizeSvg(savedCustomSvg);
        this.registerCharacter('custom', {
          name: '自定义',
          title: '自定义伴读',
          primary: '#15140f',
          accent: '#ed6f5c',
          svg: cleanSvg
        });
      } catch (e) {
        console.warn('[Companion] Failed to restore custom SVG:', e);
        localStorage.removeItem('delector_companion_custom_svg');
      }
    }

    // 1. Read persistent settings
    this.charId = localStorage.getItem('delector_companion_char') || 'owl';
    if (!CHARACTERS[this.charId]) this.charId = 'owl';
    this.name = localStorage.getItem('delector_companion_name') || '';
    this.color = localStorage.getItem('delector_companion_color') || '';
    this.soundEnabled = localStorage.getItem('delector_companion_sound') !== 'off';
    this.enabled = localStorage.getItem('delector_companion_enabled') !== 'off';
    // P4：自由移动默认关闭；关闭时桌宠固定在默认角落，拖拽不启动。
    this.freeMove = localStorage.getItem('delector_companion_roam') === 'on';

    // 2. Render initial mascot elements
    this.renderAll();
    this.syncStudio();

    // 3. Daily Greeting Check
    const today = new Date().toISOString().slice(0, 10);
    const lastVisit = localStorage.getItem('delector_visit_date');
    if (lastVisit !== today) {
      localStorage.setItem('delector_visit_date', today);
      setTimeout(() => {
        this.celebrate('greeting');
      }, 1200);
    }
  },

  registerCharacter(id, def) {
    if (!id || !def || !def.svg) return;
    CHARACTERS[id] = {
      id,
      name: def.name || id,
      title: def.title || def.name || id,
      primary: def.primary || '#15140f',
      accent: def.accent || '#ed6f5c',
      svg: def.svg
    };
    if (id === 'custom') {
      const studioCustomBtn = document.getElementById('studio-btn-custom');
      if (studioCustomBtn) studioCustomBtn.style.display = '';
      const panelCustomBtn = document.getElementById('panel-btn-custom');
      if (panelCustomBtn) panelCustomBtn.style.display = '';
    }
    this.renderAll();
    this.syncStudio();
  },

  async handleSvgUpload(file) {
    if (!file) return;

    // 1. Validate file extension / mime type
    const isSvgExt = file.name && file.name.toLowerCase().endsWith('.svg');
    const isSvgMime = file.type === 'image/svg+xml' || file.type === '' || file.type === 'text/xml';
    if (!isSvgExt && !isSvgMime) {
      if (window.showUndoToast) window.showUndoToast('仅支持上传 .svg 格式矢量图形文件');
      return;
    }

    // 2. Validate file size <= 64KB
    const MAX_SIZE = 64 * 1024;
    if (file.size > MAX_SIZE) {
      if (window.showUndoToast) window.showUndoToast('SVG 文件大小不能超过 64KB');
      return;
    }

    try {
      const rawText = await file.text();
      const cleanSvg = sanitizeSvg(rawText);

      // 3. Register custom character
      this.registerCharacter('custom', {
        name: '自定义',
        title: '自定义伴读',
        primary: '#15140f',
        accent: '#ed6f5c',
        svg: cleanSvg
      });

      // 4. Save to localStorage and switch
      localStorage.setItem('delector_companion_custom_svg', cleanSvg);
      this.setCharacter('custom');

      if (window.showUndoToast) {
        window.showUndoToast('自定义伴读角色已导入并生效');
      }
      this.triggerEmotion('happy');
      this.say({
        de: "Hallo! Ich bin dein individueller Begleiter!",
        zh: "你好！我是你的专属自定义伴读角色！"
      });
    } catch (err) {
      console.error('[Companion] SVG Upload error:', err);
      if (window.showUndoToast) {
        window.showUndoToast('SVG 解析失败: ' + (err.message || '格式损坏'));
      }
    }
  },

  triggerUpload(source = 'studio') {
    const inputId = source === 'panel' ? 'panel-svg-input' : 'studio-svg-input';
    const input = document.getElementById(inputId) || document.getElementById('studio-svg-input');
    if (input) input.click();
  },

  onFileSelected(event) {
    const file = event?.target?.files?.[0];
    if (file) {
      this.handleSvgUpload(file);
    }
    if (event?.target) {
      event.target.value = '';
    }
  },

  getCurrentCharDef() {
    return CHARACTERS[this.charId] || CHARACTERS.owl;
  },

  setCharacter(charId) {
    if (!CHARACTERS[charId]) return;
    this.charId = charId;
    localStorage.setItem('delector_companion_char', charId);
    this.renderAll();
    this.syncStudio();
    this.triggerEmotion('happy');
  },

  setName(name) {
    this.name = (name || '').trim().slice(0, 12);
    localStorage.setItem('delector_companion_name', this.name);
    this.syncStudio();
  },

  setColor(color) {
    this.color = color || '';
    localStorage.setItem('delector_companion_color', this.color);
    this.renderAll();
    this.syncStudio();
  },

  toggleSound() {
    this.soundEnabled = !this.soundEnabled;
    localStorage.setItem('delector_companion_sound', this.soundEnabled ? 'on' : 'off');
    this.syncStudio();
    if (window.showUndoToast) {
      window.showUndoToast(this.soundEnabled ? '伴读发声已开启' : '伴读发声已静音');
    }
  },

  toggleEnabled() {
    this.enabled = !this.enabled;
    localStorage.setItem('delector_companion_enabled', this.enabled ? 'on' : 'off');
    const compEl = document.getElementById('companion');
    if (compEl) {
      compEl.classList.toggle('is-disabled', !this.enabled);
    }
    this.syncStudio();
  },

  // P4：自由移动开关。位置记忆在胶囊控制器内完成（按布局尺寸换算并持久化）。
  setFreeMove(enabled) {
    this.freeMove = Boolean(enabled);
    localStorage.setItem('delector_companion_roam', this.freeMove ? 'on' : 'off');
    const compEl = document.getElementById('companion');
    const controller = compEl && compEl._floatingCapsuleController;
    if (controller && typeof controller.setFreeMove === 'function') {
      controller.setFreeMove(this.freeMove);
    } else if (compEl) {
      compEl.classList.toggle('is-free-move', this.freeMove);
      compEl.setAttribute('data-free-move', this.freeMove ? 'on' : 'off');
    }
    this.syncPanel();
    // 关闭时桌宠靠 CSS 过渡回角落，等过渡结束再量面板；开启是直接落位，用 rAF。
    this.schedulePanelFit(this.freeMove ? 0 : 360);
    if (window.showUndoToast) {
      window.showUndoToast(
        this.freeMove
          ? '自由移动已开启：可拖到任意位置，落点仍会避开主要操作控件'
          : '自由移动已关闭：伴读回到默认角落，位置已记住'
      );
    }
  },

  saveStudioSettings() {
    const nameInput = document.getElementById('studio-mascot-name');
    if (nameInput) this.setName(nameInput.value);
    if (window.showUndoToast) {
      window.showUndoToast('伴读研习工坊设置已保存生效');
    }
    this.triggerEmotion('happy');
    this.say({ de: "Danke! Ich bin bereit!", zh: "谢谢！我已经准备好了！" });
  },

  _suppressClickUntil: 0,

  _suppressClick(ms) {
    this._suppressClickUntil = Date.now() + (ms || 350);
  },

  onClick(evt) {
    // 统一入口准入：german 工作台（iframe 全屏）真正禁用伴学入口。
    if (getActiveView() === 'german') {
      return;
    }
    if (this._suppressClickUntil && Date.now() < this._suppressClickUntil) {
      return;
    }
    // P3：点击角色 = 用户已看到错误，立即解除 error 驻留。
    this.clearError();
    if (navigator.vibrate) navigator.vibrate(15);
    if (!this.enabled) {
      this.toggleEnabled();
      return;
    }
    // Shift 或 Alt 辅助键唤起外观选角面板
    if (evt && (evt.shiftKey || evt.altKey)) {
      this.togglePanel();
      return;
    }
    // 默认点击唤起德语伴学抽屉
    if (window.CompanionDrawer) {
      const ctx = this.harvestStudyContext();
      window.CompanionDrawer.toggle(ctx);
      return;
    }
    this.togglePanel();
  },

  togglePanel() {
    this.panelOpen = !this.panelOpen;
    const cap = document.getElementById('companion');
    const panel = document.getElementById('companion-panel');
    if (cap) {
      cap.classList.remove('panel-below', 'panel-align-left');
    }
    if (panel) {
      panel.classList.toggle('hidden', !this.panelOpen);
    }
    if (this.panelOpen) {
      this.syncPanel();
      if (panel) {
        requestAnimationFrame(() => this.fitPanelInViewport());
      }
    }
  },

  /** 让设置面板跟随桌宠但不越出视觉视口：优先原位置（上方/右对齐），放不下再翻面。 */
  fitPanelInViewport() {
    const cap = document.getElementById('companion');
    const panel = document.getElementById('companion-panel');
    if (!cap || !panel || panel.classList.contains('hidden')) return;
    const vp = getVisualViewport();
    const margin = 8;

    // 每次都从默认方位重新量，避免桌宠换位置后沿用上一次的翻面结果。
    cap.classList.remove('panel-below', 'panel-align-left');
    let rect = panel.getBoundingClientRect();
    if (rect.top < vp.top + margin) {
      cap.classList.add('panel-below');
      rect = panel.getBoundingClientRect();
    }
    if (rect.bottom > vp.top + vp.height - margin) {
      cap.classList.remove('panel-below');
      rect = panel.getBoundingClientRect();
      // 上下都放不下时优先保留能完整放下的一侧。
      if (rect.top < vp.top + margin && panel.offsetHeight <= vp.height - margin * 2) {
        cap.classList.add('panel-below');
        rect = panel.getBoundingClientRect();
      }
    }

    if (rect.left < vp.left + margin) {
      cap.classList.add('panel-align-left');
    }
  },

  schedulePanelFit(delay = 0) {
    if (!this.panelOpen) return;
    if (delay > 0) {
      setTimeout(() => this.fitPanelInViewport(), delay);
    } else {
      requestAnimationFrame(() => this.fitPanelInViewport());
    }
  },

  harvestStudyContext() {
    const view = getActiveView();
    let selectedText = '';
    let contextSource = 'none';

    // 1. 实时 DOM 选区：所有页面唯一允许的即时来源
    if (window.getSelection) {
      const sel = window.getSelection().toString().trim();
      if (sel && sel.length > 0 && sel.length < 500) {
        selectedText = sel;
        contextSource = 'live-selection';
      }
    }

    // 2. 只有阅读器允许读取阅读器状态（其它页面 MUST NOT 复用上一篇的残留）
    let articleTitle = '';
    let cefrLevel = '';
    if (view === 'reader') {
      if (!selectedText && window.state && window.state.activeSelectedRangeText) {
        selectedText = window.state.activeSelectedRangeText.trim();
        contextSource = 'reader-state';
      }
      if (!selectedText && window.state && window.state.activeSelectedSentId && window.state.currentArticle?.sentences) {
        const sent = window.state.currentArticle.sentences.find(s => s.id === window.state.activeSelectedSentId);
        if (sent && sent.text) {
          selectedText = sent.text.trim();
          contextSource = 'reader-state';
        }
      }
      // 3. 若选中文本因 span 紧贴缺失空格，且能定位到当前句，自动恢复德语词间空格
      if (selectedText && !selectedText.includes(' ') && window.state && window.state.activeSelectedSentId && window.state.currentArticle?.sentences) {
        const sent = window.state.currentArticle.sentences.find(s => s.id === window.state.activeSelectedSentId);
        if (sent && sent.text) {
          if (typeof window.restoreSentenceSpaces === 'function') {
            selectedText = window.restoreSentenceSpaces(selectedText, sent.text);
          } else if (sent.text.replace(/\s+/g, '') === selectedText.replace(/\s+/g, '')) {
            selectedText = sent.text.trim();
          }
        }
      }
      if (window.state && window.state.currentArticle && window.state.currentArticle.title) {
        articleTitle = window.state.currentArticle.title;
      } else {
        const titleEl = document.querySelector('.article-title, #reader-article-title, .reader-header-title');
        if (titleEl) {
          articleTitle = titleEl.textContent.trim();
        }
      }
      cefrLevel = (window.state && window.state.currentArticle && window.state.currentArticle.cefr_level) || 'B1';
    }

    // 4. 写作台草稿：与 reader 的 selected_text 分离，用 draftText 单独承载。
    let draftText = '';
    if (view === 'writer') {
      draftText = readWriterDraftText();
      if (draftText && contextSource === 'none') {
        contextSource = 'writer-draft';
      }
    }

    // 5. 卡盒当前词条：与 selected_text / draftText 分离，用 cardContext 单独承载。
    let cardContext = '';
    if (view === 'cards') {
      cardContext = readCardBoxContext();
      if (cardContext && contextSource === 'none') {
        contextSource = 'card-current';
      }
    }

    return {
      selectedText,
      articleTitle,
      cefrLevel,
      view,
      contextSource,
      draftText,
      cardContext
    };
  },

  onSay() {
    if (navigator.vibrate) navigator.vibrate(15);
    this.triggerEmotion('happy');
    const items = PHRASES.idle;
    const pick = items[Math.floor(Math.random() * items.length)];
    this.say(pick);
  },

  celebrate(key, data = {}) {
    const list = PHRASES[key];
    if (!list || !list.length) return;

    // Pick random phrase
    let pick = list[Math.floor(Math.random() * list.length)];
    let de = pick.de;
    let zh = pick.zh;

    if (data.pct !== undefined) {
      de = de.replace('{pct}', data.pct);
      zh = zh.replace('{pct}', data.pct);
    }
    if (data.n !== undefined) {
      de = de.replace('{n}', data.n);
      zh = zh.replace('{n}', data.n);
    }

    // Trigger emotion based on category
    if (key === 'card_vocab' || key === 'card_grammar' || key === 'review_good' || key === 'cloze_great' || key === 'quiz_done') {
      this.triggerEmotion('happy');
    } else if (key === 'review_hard') {
      this.triggerEmotion('wiggle');
    } else if (key === 'streak') {
      this.triggerEmotion('happy');
    }

    this.say({ de, zh });
  },

  /**
   * 气泡四侧求解：优先 top → bottom → left → right，放不下翻面，
   * 跨轴夹取进视口，高度按 45vh 封顶后内部滚动，箭头跟随角色中心。
   *
   * 气泡是 .companion（可能带 scale(0.88)）的绝对定位子元素，
   * 因此先在「视觉视口坐标」里求解，再用 transform-origin + 缩放系数
   * 反算回容器局部坐标，避免移动端缩放把气泡推出屏幕。
   */
  repositionBubble() {
    const bubble = document.getElementById('companion-bubble');
    const capsule = document.getElementById('companion');
    if (!bubble || !capsule) return;

    // 写作页移动端 sheet 展开时属于模态：气泡先收起（让位），关闭后由一次
    // repositionBubble 自动恢复，不靠抬高 z-index 去盖住 sheet。
    // 模态判断排在 settle 挂起之前：开合 sheet 时气泡必须立刻让位，不能等 260ms 滑动。
    const modalOpen = Boolean(document.querySelector('.writer-sidebar.mobile-panel-open'));
    if (modalOpen) {
      if (!bubble.classList.contains('hidden')) {
        bubble.classList.add('hidden');
        bubbleSuspendedByModal = true;
      }
      return;
    }
    if (bubbleSuspendedByModal) {
      bubbleSuspendedByModal = false;
      // 挂起期间计时不暂停：模态开着超过气泡 TTL 时，关闭瞬间不得让过期气泡"复活"。
      if (bubbleExpiresAt > Date.now()) {
        bubble.classList.remove('hidden');
      } else {
        bubble.classList.add('hidden');
        bubbleExpiresAt = 0;
        if (this.bubbleTimer) {
          clearTimeout(this.bubbleTimer);
          this.bubbleTimer = null;
        }
      }
    }

    // P3：settle 滑动期间锚点在动，求解只会得到过期位置；挂起到 settle-end 再算。
    // 拖拽释放与自动让位走同一条节奏，不区分来源。
    if (this._isSettling()) {
      if (!bubble.classList.contains('hidden')) this._bubbleResolvePending = true;
      return;
    }
    if (bubble.classList.contains('hidden')) return;

    // 1. 清空上一轮的内联约束，回到自然尺寸再测量
    const body = bubble.querySelector('.companion-bubble-body');
    const bodyEl = body || bubble;
    bubble.style.maxWidth = '';
    bodyEl.style.maxHeight = '';
    bodyEl.style.overflowY = '';
    bubble.style.pointerEvents = '';
    bubble.style.left = '';
    bubble.style.top = '';
    bubble.style.right = '';
    bubble.style.bottom = '';

    const capRect = capsule.getBoundingClientRect();
    if (!capRect.width || !capRect.height) return;

    const capWidth = capsule.offsetWidth || 60;
    const capHeight = capsule.offsetHeight || 60;
    const scale = capRect.width / capWidth || 1;

    const capCs = window.getComputedStyle(capsule);
    const capLeft = parseFloat(capCs.left);
    const capTop = parseFloat(capCs.top);
    let anchorLeft = Number.isFinite(capLeft) ? capLeft : capRect.left;
    let anchorTop = Number.isFinite(capTop) ? capTop : capRect.top;
    const origin = parseTransformOrigin(capCs.transformOrigin, capWidth, capHeight);

    // 用 offsetWidth/offsetHeight 量布局尺寸：它们不受 transform 影响，
    // 避免 pop-anim 缩放过程中把气泡量小、误判为“放得下”后裁掉正文。
    const natural = {
      width: (bubble.offsetWidth || 0) * scale,
      height: (bubble.offsetHeight || 0) * scale
    };
    const vp = getVisualViewport();

    const MARGIN = 8;   // 视口安全边距
    const GAP = 12;     // 角色与气泡间距
    const MAX_W = Math.max(120, vp.width - MARGIN * 2);
    const MAX_H = Math.min(vp.height * 0.45, vp.height - MARGIN * 2);

    let bw = Math.min(natural.width, MAX_W);
    let bh = Math.min(natural.height, MAX_H);

    let ax = capRect.left;
    let ay = capRect.top;
    const aw = capRect.width;
    const ah = capRect.height;

    // 2. 四侧主轴可用空间
    const space = {
      top: ay - GAP - (vp.top + MARGIN),
      bottom: (vp.top + vp.height - MARGIN) - (ay + ah + GAP),
      left: ax - GAP - (vp.left + MARGIN),
      right: (vp.left + vp.width - MARGIN) - (ax + aw + GAP)
    };

    const fits = side =>
      space[side] >= (side === 'top' || side === 'bottom' ? bh : bw);

    // 2.5 禁停区：投影出每个方向的气泡矩形，优先选「放得下且不压控件」的一侧。
    //     避让完全基于当前可见 DOM 矩形，不做坐标硬编码。
    const obstacles = collectNoParkRects(vp, getAvoidPadding());
    const rectForSide = (s) => {
      const vertical = s === 'top' || s === 'bottom';
      const left = vertical ? ax + aw / 2 - bw / 2 : (s === 'left' ? ax - GAP - bw : ax + aw + GAP);
      const top = vertical ? (s === 'top' ? ay - GAP - bh : ay + ah + GAP) : ay + ah / 2 - bh / 2;
      return { left, top, width: bw, height: bh };
    };
    const hitsNoPark = (s) => intersectsAny(rectForSide(s), obstacles);

    // 3. 优先方向 → 翻面；再避开禁停区；都不行时选可用空间最大的一侧，压到该空间内部滚动
    const order = ['top', 'bottom', 'left', 'right'];
    let side = order.find((s) => fits(s) && !hitsNoPark(s));
    if (!side) side = order.find(fits);
    if (!side) side = order.reduce(
      (best, s) => (space[s] > space[best] ? s : best),
      order[0]
    );

    const isVertical = side === 'top' || side === 'bottom';
    const mainSpace = Math.max(48, space[side]);

    // 4. 宽度封顶：只在真的超宽时写 max-width，避免把气泡钉死在自然宽度上
    //    （钉死会因 max-content → max-width 的重新换行把高度悄悄顶高）
    const widthCap = isVertical
      ? MAX_W
      : Math.max(96, Math.min(MAX_W, mainSpace));
    if (natural.width > widthCap + 0.5) {
      bubble.style.maxWidth = (widthCap / scale) + 'px';
    }

    // 宽度变化会改变换行与高度，先重新量一次布局尺寸
    bw = (bubble.offsetWidth || 0) * scale;
    bh = (bubble.offsetHeight || 0) * scale;

    // 5. 高度封顶：只有超出 45vh（或侧面可用空间）时才启用内层滚动
    const heightCap = isVertical ? Math.min(MAX_H, mainSpace) : MAX_H;
    if (bh > heightCap + 0.5) {
      // 气泡的 padding / 描边会占掉高度，封顶值扣掉这部分后交给内层滚动
      const chromeH = Math.max(0, bubble.offsetHeight - bodyEl.offsetHeight);
      bodyEl.style.maxHeight = Math.max(24, heightCap / scale - chromeH) + 'px';
      bodyEl.style.overflowY = 'auto';
      bh = (bubble.offsetHeight || 0) * scale;
    }

    const overflow = bodyEl.scrollHeight > bodyEl.clientHeight + 1 ||
      bubble.scrollWidth > bubble.clientWidth + 1;
    if (overflow) {
      bubble.style.pointerEvents = 'auto';
    }

    // 5.5 联合让位：上下都放不干净时（常见于写作页贴着 dock），把胶囊沿最近安全位
    //     挪到「某一侧能完整放下气泡」的位置，而不是让气泡压在控件/编辑区上。
    const bubbleRectAt = (anchor, s) => {
      const bx = anchor.left + aw / 2 - bw / 2;
      const by = s === 'top' ? anchor.top - GAP - bh : anchor.top + ah + GAP;
      return {
        left: clamp(bx, vp.left + MARGIN, vp.left + vp.width - MARGIN - bw),
        top: clamp(by, vp.top + MARGIN, vp.top + vp.height - MARGIN - bh),
        width: bw,
        height: bh
      };
    };
    const cleanAt = (anchor, s) => !intersectsAny(bubbleRectAt(anchor, s), obstacles);

    if (isVertical && !cleanAt({ left: ax, top: ay }, side)) {
      const current = { left: ax, top: ay };
      // 候选锚点 = 当前位 + 视口角 + 每个禁停区四边（障碍已含 8/12px 外扩），
      // 再按离当前位置的距离排序，取第一个「胶囊不压、气泡也不压」的锚点。
      const xs = [ax, vp.left + MARGIN, vp.right - MARGIN - aw];
      const ys = [ay, vp.top + MARGIN, vp.bottom - MARGIN - ah];
      obstacles.forEach((o) => {
        xs.push(o.left - aw, o.right);
        ys.push(o.top - ah, o.bottom);
      });

      const uniq = (list) => [...new Set(list.map((v) => Math.round(v * 10) / 10))];
      const anchors = [];
      uniq(xs).forEach((x0) => {
        uniq(ys).forEach((y0) => {
          const left = clamp(x0, vp.left + MARGIN, Math.max(vp.left + MARGIN, vp.right - MARGIN - aw));
          const top = clamp(y0, vp.top + MARGIN, Math.max(vp.top + MARGIN, vp.bottom - MARGIN - ah));
          if (anchors.some((a) => Math.abs(a.left - left) < 1 && Math.abs(a.top - top) < 1)) return;
          if (intersectsAny({ left, top, width: aw, height: ah }, obstacles)) return;
          anchors.push({ left, top });
        });
      });
      anchors.sort(
        (a, b) =>
          (a.left - current.left) ** 2 + (a.top - current.top) ** 2 -
          ((b.left - current.left) ** 2 + (b.top - current.top) ** 2)
      );

      const controller = capsule._floatingCapsuleController;
      for (const a of anchors) {
        if (Math.abs(a.left - current.left) < 1 && Math.abs(a.top - current.top) < 1) continue;
        const nextSide = ['top', 'bottom'].find((s) => cleanAt(a, s));
        if (!nextSide) continue;
        if (controller && typeof controller.moveToVisual === 'function') {
          controller.moveToVisual(a);
          ax = a.left;
          ay = a.top;
          anchorLeft = a.left - origin.x * (1 - scale);
          anchorTop = a.top - origin.y * (1 - scale);
          side = nextSide;
        }
        break;
      }
    }

    // 6. 视觉视口坐标下的落点
    let x;
    let y;
    if (isVertical) {
      x = ax + aw / 2 - bw / 2;
      y = side === 'top' ? ay - GAP - bh : ay + ah + GAP;
      x = clamp(x, vp.left + MARGIN, vp.left + vp.width - MARGIN - bw);
      y = clamp(y, vp.top + MARGIN, vp.top + vp.height - MARGIN - bh);
    } else {
      y = ay + ah / 2 - bh / 2;
      x = side === 'left' ? ax - GAP - bw : ax + aw + GAP;
      y = clamp(y, vp.top + MARGIN, vp.top + vp.height - MARGIN - bh);
      x = clamp(x, vp.left + MARGIN, vp.left + vp.width - MARGIN - bw);
    }

    // 7. 视觉坐标 → 容器局部坐标（视觉 = 布局原点 + origin + scale*(局部 - origin)）
    bubble.style.left = (origin.x + (x - anchorLeft - origin.x) / scale) + 'px';
    bubble.style.top = (origin.y + (y - anchorTop - origin.y) / scale) + 'px';
    bubble.style.right = 'auto';
    bubble.style.bottom = 'auto';
    bubble.dataset.side = side;

    // 8. 箭头跟随角色中心（百分比，随气泡宽高自适应）
    if (isVertical) {
      const pct = clamp(((ax + aw / 2 - x) / bw) * 100, 6, 94);
      bubble.style.setProperty('--bubble-arrow-x', pct + '%');
    } else {
      const pct = clamp(((ay + ah / 2 - y) / bh) * 100, 6, 94);
      bubble.style.setProperty('--bubble-arrow-y', pct + '%');
    }
  },

  say(entry) {
    if (!entry || !entry.de) return;
    const charDef = this.getCurrentCharDef();
    const displayName = this.name || charDef.name;

    const prefixDe = `${displayName}: ${entry.de}`;
    const rawDe = entry.de;
    const zh = entry.zh || '';

    // 1. Render Floating Bubble
    const bubble = document.getElementById('companion-bubble');
    const deEl = document.getElementById('companion-de');
    const zhEl = document.getElementById('companion-zh');

    if (bubble && deEl && zhEl) {
      deEl.textContent = prefixDe;
      zhEl.textContent = zh;

      // P3：拖拽 / 编辑态聚焦 / 落点滑动期间气泡不出现；条件解除后若未过期再补显。
      // 过期时间统一走 P2 的模块级 bubbleExpiresAt，repositionBubble 的模态守卫依赖它。
      const suppressedByDrag = this._conditions.dragging;
      const suppressedByFocus = this._isEditableFocused();
      const suppressedBySettle = this._isSettling();
      if (!suppressedByDrag && !suppressedByFocus && !suppressedBySettle) {
        bubble.classList.remove('hidden');
        this.repositionBubble();
        bubble.classList.remove('pop-anim');
        void bubble.offsetWidth; // trigger reflow
        bubble.classList.add('pop-anim');
      } else {
        bubble.classList.add('hidden');
        if (suppressedByDrag) this._bubbleSuppressedBy = 'drag';
        else if (suppressedByFocus) this._bubbleSuppressedBy = 'focus';
        // 展示请求挂起：settle-end 时由 _onSettleEnd 补显并求解，避免先落在默认位置再跳。
        if (suppressedBySettle) this._bubbleResolvePending = true;
      }

      if (suppressedByFocus) {
        bubbleExpiresAt = 0;
      } else {
        bubbleExpiresAt = Date.now() + BUBBLE_TTL_MS;
        if (this.bubbleTimer) clearTimeout(this.bubbleTimer);
        this.bubbleTimer = setTimeout(() => {
          this.bubbleTimer = null;
          bubbleExpiresAt = 0;
          bubble.classList.add('hidden');
          this._setCondition('bubbleVisible', false);
        }, BUBBLE_TTL_MS);
      }

      this._setCondition(
        'bubbleVisible',
        !suppressedByDrag && !suppressedByFocus && !suppressedBySettle
      );
    }

    // 2. Render Folio Stage Bubble if visible
    const stageBubble = document.getElementById('mascot-stage-bubble');
    const stageDe = document.getElementById('mascot-stage-de');
    const stageZh = document.getElementById('mascot-stage-zh');
    if (stageBubble && stageDe && stageZh) {
      stageDe.textContent = prefixDe;
      stageZh.textContent = zh;
      stageBubble.classList.remove('pop-anim');
      void stageBubble.offsetWidth;
      stageBubble.classList.add('pop-anim');
    }

    // 3. Audio Voice with 8s cooldown & ShadowPlayer non-conflict check
    if (this.soundEnabled && !ShadowPlayer.isPlaying) {
      const now = Date.now();
      if (now - this.lastSpeechAt >= 8000) {
        this.lastSpeechAt = now;
        playGermanAudio(rawDe, 0.9);
      }
    }
  },

  triggerEmotion(emotion) {
    // P3：情绪只允许覆盖 idle / speaking；其他状态里情绪会掩盖真实姿态。
    if (this._state !== 'idle' && this._state !== 'speaking') return;
    if (this._conditions.dragging) return;

    const chars = document.querySelectorAll('.companion-char, .mascot-stage-char');
    const cls = emotion === 'happy' ? 'is-happy' : emotion === 'wiggle' ? 'is-wiggle' : 'is-sad';

    chars.forEach(el => {
      el.classList.remove('is-happy', 'is-wiggle', 'is-sad');
      void el.offsetWidth;
      el.classList.add(cls);
      setTimeout(() => el.classList.remove(cls), 1200);
    });
  },

  renderAll() {
    const charDef = this.getCurrentCharDef();
    const primaryColor = this.color || charDef.primary;
    const accentColor = charDef.accent;

    const styleVars = `--c-primary:${primaryColor}; --c-accent:${accentColor};`;

    // 1. Floating Widget Character SVG
    const floatCharEl = document.getElementById('companion-char');
    if (floatCharEl) {
      floatCharEl.setAttribute('style', styleVars);
      floatCharEl.innerHTML = charDef.svg;
    }

    // Floating Avatar Icon
    const avatarIcon = document.getElementById('companion-avatar-icon');
    if (avatarIcon) {
      avatarIcon.innerHTML = charDef.svg;
    }

    // 2. Folio Stage Character SVG
    const stageCharEl = document.getElementById('mascot-stage-char');
    if (stageCharEl) {
      stageCharEl.setAttribute('style', styleVars);
      stageCharEl.innerHTML = charDef.svg;
    }

    // Disabled state
    const compEl = document.getElementById('companion');
    if (compEl) {
      compEl.classList.toggle('is-disabled', !this.enabled);
    }
  },

  syncStudio() {
    const charDef = this.getCurrentCharDef();

    // 0. Update custom button visibility
    const hasCustom = !!CHARACTERS.custom;
    const studioCustomBtn = document.getElementById('studio-btn-custom');
    if (studioCustomBtn) {
      studioCustomBtn.style.display = hasCustom ? '' : 'none';
    }

    // 1. Char Selector Active state
    document.querySelectorAll('.mascot-choice-btn').forEach(btn => {
      const char = btn.getAttribute('data-char');
      if (char) {
        const isActive = char === this.charId;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-pressed', String(isActive));
      }
    });

    // 2. Input values
    const nameInput = document.getElementById('studio-mascot-name');
    if (nameInput && document.activeElement !== nameInput) {
      nameInput.value = this.name;
    }

    // 3. Sound toggle UI
    const soundIcon = document.getElementById('studio-sound-icon');
    const soundLabel = document.getElementById('studio-sound-label');
    const soundBtn = document.getElementById('studio-sound-btn');
    if (soundIcon) {
      const useEl = soundIcon.querySelector('use');
      if (useEl) useEl.setAttribute('href', this.soundEnabled ? '#ui-ico-volume-2' : '#ui-ico-volume-x');
      else soundIcon.textContent = this.soundEnabled ? '音量开' : '静音';
    }
    if (soundLabel) soundLabel.textContent = this.soundEnabled ? '发声已开启' : '发声已静音';
    if (soundBtn) soundBtn.setAttribute('aria-pressed', String(this.soundEnabled));

    // 4. Status Tag
    const tag = document.getElementById('mascot-status-tag');
    if (tag) {
      tag.textContent = this.enabled ? `${charDef.name.toUpperCase()} · AKTIV` : 'INAKTIV';
    }

    this.syncPanel();
  },

  syncPanel() {
    // 0. Update panel custom button visibility
    const hasCustom = !!CHARACTERS.custom;
    const panelCustomBtn = document.getElementById('panel-btn-custom');
    if (panelCustomBtn) {
      panelCustomBtn.style.display = hasCustom ? '' : 'none';
    }

    // 1. Sync mini floating panel buttons
    document.querySelectorAll('.panel-char-btn').forEach(btn => {
      const char = btn.getAttribute('data-char');
      if (char) {
        const isActive = char === this.charId;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-pressed', String(isActive));
        // 面板按钮没有可见文字，形象必须用 SVG 承载，不能以单个 emoji 作为唯一标签。
        const def = CHARACTERS[char];
        if (def && def.svg && btn.innerHTML !== def.svg) {
          btn.innerHTML = def.svg;
        }
      }
    });

    const panelName = document.getElementById('panel-name');
    if (panelName && document.activeElement !== panelName) {
      panelName.value = this.name;
    }

    const soundBtn = document.getElementById('panel-sound');
    if (soundBtn) {
      const soundIcon = document.getElementById('panel-sound-icon');
      if (soundIcon) {
        const useEl = soundIcon.querySelector('use');
        if (useEl) {
          useEl.setAttribute('href', this.soundEnabled ? '#ui-ico-volume-2' : '#ui-ico-volume-x');
        }
      }
      soundBtn.setAttribute('aria-pressed', String(this.soundEnabled));
    }

    // P4：自由移动开关（原生 checkbox，checked 即状态；文字同步，不靠颜色表达）
    const freeMoveInput = document.getElementById('drawer-free-move');
    if (freeMoveInput) {
      freeMoveInput.checked = Boolean(this.freeMove);
    }
    const freeMoveState = document.getElementById('drawer-free-move-state');
    if (freeMoveState) {
      freeMoveState.textContent = this.freeMove ? '已开启' : '已关闭';
    }
  }
};
