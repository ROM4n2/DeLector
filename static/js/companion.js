/* DeLector - German Companion Mascot System (Eule & Friends) */
'use strict';

import { ShadowPlayer, playGermanAudio } from './player.js';

// ── SVG Character Templates (Standardized classes & dynamic CSS vars) ───────
export const CHARACTERS = {
  owl: {
    id: 'owl',
    name: 'Eule',
    emoji: '🦉',
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
    emoji: '🐱',
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
    emoji: '🦊',
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
    emoji: '🤖',
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

// ── Companion Mascot Singleton Controller ────────────────────────────────────
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

  init() {
    // 1. Read persistent settings
    this.charId = localStorage.getItem('delector_companion_char') || 'owl';
    if (!CHARACTERS[this.charId]) this.charId = 'owl';
    this.name = localStorage.getItem('delector_companion_name') || '';
    this.color = localStorage.getItem('delector_companion_color') || '';
    this.soundEnabled = localStorage.getItem('delector_companion_sound') !== 'off';
    this.enabled = localStorage.getItem('delector_companion_enabled') !== 'off';

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
      emoji: def.emoji || '✨',
      title: def.title || def.name || id,
      primary: def.primary || '#6b4f8f',
      accent: def.accent || '#e8953a',
      svg: def.svg
    };
    this.renderAll();
    this.syncStudio();
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
      window.showUndoToast(this.soundEnabled ? '🔊 伴读发声已开启' : '🔇 伴读发声已静音');
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

  saveStudioSettings() {
    const nameInput = document.getElementById('studio-mascot-name');
    if (nameInput) this.setName(nameInput.value);
    if (window.showUndoToast) {
      window.showUndoToast('✓ 伴读研习工坊设置已保存生效');
    }
    this.triggerEmotion('happy');
    this.say({ de: "Danke! Ich bin bereit!", zh: "谢谢！我已经准备好了！" });
  },

  onClick() {
    if (navigator.vibrate) navigator.vibrate(15);
    if (!this.enabled) {
      this.toggleEnabled();
      return;
    }
    this.panelOpen = !this.panelOpen;
    const panel = document.getElementById('companion-panel');
    if (panel) {
      panel.classList.toggle('hidden', !this.panelOpen);
    }
    if (this.panelOpen) {
      this.syncPanel();
    }
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
      bubble.classList.remove('hidden');
      bubble.classList.remove('pop-anim');
      void bubble.offsetWidth; // trigger reflow
      bubble.classList.add('pop-anim');

      if (this.bubbleTimer) clearTimeout(this.bubbleTimer);
      this.bubbleTimer = setTimeout(() => {
        bubble.classList.add('hidden');
      }, 6500);
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
      avatarIcon.textContent = charDef.emoji;
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

    // 1. Char Selector Active state
    document.querySelectorAll('.mascot-choice-btn').forEach(btn => {
      const char = btn.getAttribute('data-char');
      btn.classList.toggle('active', char === this.charId);
    });

    // 2. Input values
    const nameInput = document.getElementById('studio-mascot-name');
    if (nameInput && document.activeElement !== nameInput) {
      nameInput.value = this.name;
    }

    // 3. Sound toggle UI
    const soundIcon = document.getElementById('studio-sound-icon');
    const soundLabel = document.getElementById('studio-sound-label');
    if (soundIcon) soundIcon.textContent = this.soundEnabled ? '🔊' : '🔇';
    if (soundLabel) soundLabel.textContent = this.soundEnabled ? '发声已开启' : '发声已静音';

    // 4. Status Tag
    const tag = document.getElementById('mascot-status-tag');
    if (tag) {
      tag.textContent = this.enabled ? `${charDef.name.toUpperCase()} · AKTIV` : 'INAKTIV';
    }

    this.syncPanel();
  },

  syncPanel() {
    // Sync mini floating panel
    document.querySelectorAll('.panel-char-btn').forEach(btn => {
      const char = btn.getAttribute('data-char');
      btn.classList.toggle('active', char === this.charId);
    });

    const panelName = document.getElementById('panel-name');
    if (panelName && document.activeElement !== panelName) {
      panelName.value = this.name;
    }

    const soundBtn = document.getElementById('panel-sound');
    if (soundBtn) {
      soundBtn.textContent = this.soundEnabled ? '🔊' : '🔇';
    }
  }
};
