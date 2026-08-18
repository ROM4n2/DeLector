/* DeLector – frontend logic */
'use strict';

let currentArticle = null;
let selectedToken   = null;
let selectedSent    = null;
let grammarData     = null;

// ── German Audio TTS ─────────────────────────────────────────────────────────
// ── German Audio TTS (Edge Neural TTS + Fallback) ────────────────────────────
async function playGermanAudio(text, rate = 0.88) {
  if (!text) return;
  const clean = text.trim();
  const voice = ShadowPlayer.voice || localStorage.getItem('delector_voice') || 'de-DE-KatjaNeural';
  const ratePercent = Math.round((rate - 1.0) * 100);
  const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

  try {
    const resp = await fetch('/api/audio/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean, voice: voice, rate: rateStr })
    });
    if (!resp.ok) throw new Error('Neural TTS error');
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    audio.play();
  } catch {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(clean);
    utt.lang = 'de-DE';
    utt.rate = rate;
    const voices = window.speechSynthesis.getVoices();
    const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('German') || v.name.includes('Hedda') || v.name.includes('Stefan')));
    if (deVoice) utt.voice = deVoice;
    window.speechSynthesis.speak(utt);
  }
}

// ── View router ──────────────────────────────────────────────────────────────
function show(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  closeDrawer();
  clearCefrFocus();

  const player = document.getElementById('shadow-player');
  if (player) {
    player.classList.toggle('hidden', view !== 'reader');
    if (view !== 'reader') ShadowPlayer.pause();
  }

  if (view === 'home')  loadArticles();
  if (view === 'cards') loadCards();
}

// ── Shadow Reading Audio Engine (Edge Neural TTS + Fallback) ────────────────
const ShadowPlayer = {
  isPlaying: false,
  currentSentIdx: 0,
  mode: 'shadow', // 'continuous' | 'shadow' | 'loop'
  rate: 0.88,
  voice: localStorage.getItem('delector_voice') || 'de-DE-KatjaNeural',
  audioEl: null,
  pauseTimer: null,
  utterance: null,
  isIntentionalCancel: false,

  init() {
    this.audioEl = new Audio();
    const savedVoice = localStorage.getItem('delector_voice') || 'de-DE-KatjaNeural';
    this.setVoice(savedVoice);
    if ('speechSynthesis' in window) {
      window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
      };
    }
  },

  reset() {
    this.pause();
    this.currentSentIdx = 0;
    this.clearSentenceHighlight();
    this.updateStatusText();
  },

  setVoice(voice) {
    this.voice = voice;
    localStorage.setItem('delector_voice', voice);
    const isKatja = voice.includes('Katja');
    const isConrad = voice.includes('Conrad');
    const btnKatja = document.getElementById('voice-btn-katja');
    const btnConrad = document.getElementById('voice-btn-conrad');
    if (btnKatja) btnKatja.classList.toggle('active', isKatja);
    if (btnConrad) btnConrad.classList.toggle('active', isConrad);
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
      if (this.audioEl) { this.audioEl.pause(); }
      this.speakCurrentSentence();
    }
  },

  play() {
    if (!currentArticle || !currentArticle.sentences || !currentArticle.sentences.length) return;
    this.isPlaying = true;
    this.updatePlayBtn(true);
    this.speakCurrentSentence();
  },

  pause() {
    this.isPlaying = false;
    if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
    if (this.audioEl) {
      this.audioEl.pause();
    }
    if ('speechSynthesis' in window) {
      this.isIntentionalCancel = true;
      window.speechSynthesis.cancel();
      this.isIntentionalCancel = false;
    }
    this.updatePlayBtn(false);
    this.clearSentenceHighlight();
  },

  toggle() {
    if (this.isPlaying) this.pause();
    else this.play();
  },

  speakCurrentSentence() {
    if (!this.isPlaying || !currentArticle || !currentArticle.sentences) return;
    if (this.currentSentIdx >= currentArticle.sentences.length) {
      this.pause();
      this.currentSentIdx = 0;
      return;
    }

    const sent = currentArticle.sentences[this.currentSentIdx];
    if (!sent) return;

    this.highlightSentence(this.currentSentIdx);
    this.updateStatusText();

    if (this.audioEl) {
      this.audioEl.pause();
      this.audioEl.removeAttribute('src');
    }

    // Convert speed rate float (e.g. 0.88) to edge-tts rate format (e.g. "-12%")
    const ratePercent = Math.round((this.rate - 1.0) * 100);
    const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

    // 优先调用后端 Edge Neural TTS 神经高保真音频
    fetch('/api/audio/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: sent.text, voice: this.voice, rate: rateStr })
    }).then(resp => {
      if (!resp.ok) throw new Error('Neural TTS error');
      return resp.blob();
    }).then(blob => {
      if (!this.isPlaying) return;
      const audioUrl = URL.createObjectURL(blob);
      this.audioEl.src = audioUrl;
      const startTime = Date.now();

      this.audioEl.onended = () => {
        URL.revokeObjectURL(audioUrl);
        if (!this.isPlaying) return;
        const duration = Date.now() - startTime;
        this.handleSentenceFinished(duration);
      };

      this.audioEl.onerror = () => {
        this.fallbackWebSpeech(sent);
      };

      this.audioEl.play().catch(() => this.fallbackWebSpeech(sent));
    }).catch(() => {
      this.fallbackWebSpeech(sent);
    });
  },

  handleSentenceFinished(duration) {
    if (this.mode === 'loop') {
      this.pauseTimer = setTimeout(() => this.speakCurrentSentence(), 700);
    } else if (this.mode === 'shadow') {
      // 影子跟读模式：停顿相当于句长的 1.1 倍（至少 2 秒，最多 6 秒）供大声跟读复述
      const pauseMs = Math.max(2000, Math.min(6000, duration * 1.1));
      this.showPauseCountdown(pauseMs);
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, pauseMs);
    } else {
      // 连续播放模式
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, 350);
    }
  },

  fallbackWebSpeech(sent) {
    if (!('speechSynthesis' in window)) return;
    this.isIntentionalCancel = true;
    window.speechSynthesis.cancel();
    this.isIntentionalCancel = false;

    const utt = new SpeechSynthesisUtterance(sent.text.trim());
    utt.lang = 'de-DE';
    utt.rate = this.rate;

    const voices = window.speechSynthesis.getVoices();
    const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('German') || v.name.includes('Hedda') || v.name.includes('Stefan')));
    if (deVoice) utt.voice = deVoice;

    const startTime = Date.now();

    utt.onend = () => {
      if (!this.isPlaying) return;
      const duration = Date.now() - startTime;
      this.handleSentenceFinished(duration);
    };

    utt.onerror = (e) => {
      if (e.error !== 'interrupted' && e.error !== 'canceled' && !this.isIntentionalCancel) {
        this.pause();
      }
    };

    this.utterance = utt;
    window.speechSynthesis.speak(utt);
  },

  seekSentence(idx) {
    if (!currentArticle || !currentArticle.sentences) return;
    this.currentSentIdx = Math.max(0, Math.min(currentArticle.sentences.length - 1, idx));
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
      this.speakCurrentSentence();
    } else {
      this.highlightSentence(this.currentSentIdx);
      this.updateStatusText();
    }
  },

  next() { this.seekSentence(this.currentSentIdx + 1); },
  prev() { this.seekSentence(this.currentSentIdx - 1); },
  replay() { this.seekSentence(this.currentSentIdx); },

  setMode(mode) {
    this.mode = mode;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
      this.speakCurrentSentence();
    }
  },

  setSpeed(rate) {
    this.rate = rate;
    document.querySelectorAll('.speed-step-btn').forEach(b => {
      b.classList.toggle('active', parseFloat(b.dataset.speed) === rate);
    });
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
      this.speakCurrentSentence();
    }
  },

  highlightSentence(idx) {
    document.querySelectorAll('.tok').forEach(el => el.classList.remove('reading-active'));
    const sent = currentArticle?.sentences[idx];
    if (!sent || !sent.tokens || !sent.tokens.length) return;
    sent.tokens.forEach(t => {
      const el = document.getElementById('tok-' + t.id);
      if (el) el.classList.add('reading-active');
    });
    const firstTok = document.getElementById('tok-' + sent.tokens[0].id);
    if (firstTok) firstTok.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },

  clearSentenceHighlight() {
    document.querySelectorAll('.tok.reading-active').forEach(el => el.classList.remove('reading-active'));
  },

  updatePlayBtn(playing) {
    const btn = document.getElementById('player-play-btn');
    if (btn) btn.innerHTML = playing ? '⏸' : '▶';
  },

  updateStatusText() {
    const el = document.getElementById('player-status');
    if (el && currentArticle && currentArticle.sentences) {
      el.textContent = `句 ${this.currentSentIdx + 1} / ${currentArticle.sentences.length}`;
    }
  },

  showPauseCountdown(ms) {
    const el = document.getElementById('player-status');
    if (el) el.textContent = `🎙️ 请跟读 (${Math.round(ms/1000)}s)…`;
  }
};

// ── Reader Typography Controller ─────────────────────────────────────────────
let readerFontMode = localStorage.getItem('delector_font_mode') || 'sans';
let readerFontSize = parseInt(localStorage.getItem('delector_font_size'), 10) || 18;

function applyTypography() {
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

function setFontMode(mode) {
  readerFontMode = mode;
  localStorage.setItem('delector_font_mode', mode);
  applyTypography();
}

function adjustFontSize(delta) {
  readerFontSize = Math.max(14, Math.min(24, readerFontSize + delta));
  localStorage.setItem('delector_font_size', readerFontSize);
  applyTypography();
}

let currentFocusedLevel = null;

function toggleCefrFocus(level) {
  if (currentFocusedLevel === level) {
    clearCefrFocus();
    return;
  }
  
  currentFocusedLevel = level;
  document.body.classList.add('focus-mode');
  
  // Highlight heatbar segment
  document.querySelectorAll('.heatbar-seg').forEach(el => {
    el.classList.toggle('focused', el.classList.contains(level));
  });

  // Focus tokens of this level
  document.querySelectorAll('.tok').forEach(el => {
    const matches = el.classList.contains(level);
    el.classList.toggle('focus-active', matches);
  });
}

function clearCefrFocus() {
  currentFocusedLevel = null;
  document.body.classList.remove('focus-mode');
  document.querySelectorAll('.heatbar-seg').forEach(el => el.classList.remove('focused'));
  document.querySelectorAll('.tok').forEach(el => el.classList.remove('focus-active'));
}

function renderMiniBar(stats) {
  if (!stats || !stats.cefr_percentages) return '';
  const p = stats.cefr_percentages;
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl => 
    (p[lvl] && p[lvl] > 0) ? `<div class="mini-seg ${lvl}" style="width:${p[lvl]}%" title="${lvl}: ${p[lvl]}%"></div>` : ''
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

// ── Articles ─────────────────────────────────────────────────────────────────
async function loadArticles() {
  const el = document.getElementById('article-list');
  el.innerHTML = '<div class="empty-state">加载中…</div>';
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
}

function renderReaderHeatbar(stats) {
  if (!stats || !stats.cefr_percentages) return;
  const p = stats.cefr_percentages;
  const counts = stats.cefr_counts || {};
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl => {
    if (!p[lvl] || p[lvl] <= 0) return '';
    const cnt = counts[lvl] || 0;
    return `<div class="heatbar-seg ${lvl}" style="width:${p[lvl]}%" onclick="toggleCefrFocus('${lvl}')" title="点击聚焦 ${lvl} 级别生词 (${cnt} 词)">${lvl} ${p[lvl]}%</div>`;
  }).join('');

  document.getElementById('reader-heatbar').innerHTML = segs;
  document.getElementById('heatbar-time').textContent = `预计精读 ${stats.est_reading_minutes || 1} 分钟 · 共 ${stats.word_count || 0} 词`;
  
  const rec = stats.recommended_level || 'A1';
  const badge = document.getElementById('reader-meta-badge');
  if (badge) {
    badge.textContent = `${rec} 建议`;
    badge.className = `mini-level-badge mini-level-${rec.startsWith('B2') ? 'B2' : rec}`;
  }
}

async function openReader(id) {
  currentArticle = await api('/api/articles/' + id);
  document.getElementById('reader-title').textContent = currentArticle.title;
  renderReaderHeatbar(currentArticle.stats);
  const content = document.getElementById('reader-content');
  
  // Format tokens into continuous paragraphs, preventing sentence-by-sentence fragmentation & overflow
  let paraTokens = [];
  currentArticle.sentences.forEach(sent => {
    const sentTokens = sent.tokens.map(t => {
      if (t.is_space) {
        if (t.text.includes('\n\n')) return '__PARA__';
        if (t.text.includes('\n')) return '<br>';
        return ' ';
      }
      if (t.is_punct) return `<span class="punct">${esc(t.text)}</span>`;
      const lvl = t.cefr_level || 'A1';
      return `<span id="tok-${t.id}" class="tok ${lvl}" onclick="inspect(${t.id},${sent.id})">${esc(t.text)}</span>`;
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
  show('reader');
}

// ── Token inspection ─────────────────────────────────────────────────────────
function inspect(tokenId, sentId) {
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
  const el = document.getElementById('tok-' + tokenId);
  if (el) el.classList.add('sel');

  const sent  = currentArticle.sentences.find(s => s.id === sentId);
  const token = sent.tokens.find(t => t.id === tokenId);
  selectedToken = token;
  selectedSent  = sent;
  grammarData   = null;

  const sentIdx = currentArticle.sentences.findIndex(s => s.id === sentId);
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

  document.getElementById('d-meta').innerHTML =
    `原型: <strong>${esc(token.lemma)}</strong> · 词性: ${esc(token.pos)} ${genderHtml}` +
    (token.case ? ` · ${esc(token.case)}` : '');
  document.getElementById('d-def').value = '';
  document.getElementById('d-def-status').textContent = 'AI 解析中…';
  document.getElementById('d-sent').textContent = sent.text;
  document.getElementById('save-vocab-btn').textContent = '+ 加入 Anki 词汇卡';
  document.getElementById('grammar-result').classList.add('hidden');
  openDrawer('vocab');

  // Async AI quick definition lookup
  api('/api/lookup/vocab', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ sentence: sent.text, target_word: token.text })
  }).then(res => {
    if (res && res.definition_zh && selectedToken?.text === token.text) {
      if (!document.getElementById('d-def').value) {
        document.getElementById('d-def').value = res.definition_zh;
      }
      document.getElementById('d-def-status').textContent = '✓ AI 已预填';
      if (res.plural) selectedToken.plural = res.plural;
    } else {
      document.getElementById('d-def-status').textContent = '';
    }
  }).catch(() => {
    document.getElementById('d-def-status').textContent = '';
  });
}

// ── Drawer & Tabs ────────────────────────────────────────────────────────────
let currentDrawerTab = 'vocab';

function switchDrawerTab(tab) {
  currentDrawerTab = tab;
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

function openDrawer(preferredTab = null) {
  document.getElementById('drawer').classList.add('open');
  document.body.classList.add('drawer-open');
  if (preferredTab) switchDrawerTab(preferredTab);
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.body.classList.remove('drawer-open');
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
}

// ── Grammar AI ───────────────────────────────────────────────────────────────
async function analyzeGrammar() {
  const btn = document.getElementById('analyze-btn');
  btn.textContent = '分析中…';
  btn.disabled = true;
  try {
    grammarData = await api('/api/lookup/grammar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ sentence: selectedSent.text, target_phrase: selectedToken.text })
    });
    const lvl = grammarData.cefr_level || 'B1';
    document.getElementById('g-name').textContent    = grammarData.grammar_name;
    document.getElementById('g-formula').textContent = grammarData.rule_formula || '';
    document.getElementById('g-formula').classList.toggle('hidden', !grammarData.rule_formula);
    document.getElementById('g-exp').textContent     = grammarData.explanation_zh;
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

// ── Save ─────────────────────────────────────────────────────────────────────
async function saveVocab() {
  if (!selectedToken || !currentArticle) return;
  const def = document.getElementById('d-def').value.trim() || selectedToken.lemma || selectedToken.text;
  await api('/api/cards/vocab', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: currentArticle.id,
      word: selectedToken.text, lemma: selectedToken.lemma,
      pos: selectedToken.pos,   gender: selectedToken.gender,
      cefr_level: selectedToken.cefr_level || 'A1',
      definition_zh: def, sentence_context: selectedSent.text,
      plural: selectedToken.plural || ''
    })
  });
  document.getElementById('save-vocab-btn').textContent = '✓ 已保存';
  refreshCount();
}

async function saveGrammar() {
  if (!grammarData) return;
  await api('/api/cards/grammar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: currentArticle.id,
      sentence_context: selectedSent.text,
      grammar_name: grammarData.grammar_name,
      cefr_level: grammarData.cefr_level || 'B1',
      explanation_zh: grammarData.explanation_zh,
      rule_formula: grammarData.rule_formula
    })
  });
  document.getElementById('save-grammar-btn').textContent = '✓ 已加入语法卡';
  refreshCount();
}

// ── Cards view ────────────────────────────────────────────────────────────────
async function loadCards() {
  updateAudioCacheInfo();
  const { vocab_cards: vc, grammar_cards: gc } = await api('/api/cards');
  document.getElementById('cards-container').innerHTML = `
    <div class="section-label" style="margin-bottom:0.875rem;">
      <span class="section-title">词汇卡 · VOCABULARY (${vc.length})</span>
    </div>
    <div class="card-grid">${vc.map(c => `
      <div class="memo-card">
        <div class="memo-card-head">
          <span class="memo-word">${esc(c.word)}</span>
          <span class="cefr-badge badge-${c.cefr_level}">${c.cefr_level}</span>
        </div>
        <div class="memo-def">${esc(c.definition_zh)}</div>
        <div class="memo-meta">${esc(c.lemma)} · ${esc(c.pos)}${c.gender ? ' · ' + esc(c.gender) : ''}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
      </div>`).join('')}</div>

    <div class="section-label" style="margin-bottom:0.875rem;">
      <span class="section-title">歌德语法考点卡 · GRAMMAR (${gc.length})</span>
    </div>
    ${gc.map(c => `
      <div class="grammar-memo-card">
        <div class="grammar-memo-head">
          <span class="grammar-memo-name">${esc(c.grammar_name)}</span>
          <span class="cefr-badge badge-${c.cefr_level}">Goethe ${c.cefr_level}</span>
        </div>
        ${c.rule_formula ? `<div class="grammar-memo-formula">${esc(c.rule_formula)}</div>` : ''}
        <div class="grammar-memo-exp">${esc(c.explanation_zh)}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
      </div>`).join('')}
  `;
}

async function updateAudioCacheInfo() {
  try {
    const info = await api('/api/audio/cache');
    const span = document.getElementById('cache-size-span');
    if (span) span.textContent = `${info.total_size_mb || 0} MB`;
  } catch {
    // ignore
  }
}

async function clearAudioCache() {
  try {
    const info = await api('/api/audio/cache');
    if (!info.file_count) {
      alert('当前本地语音缓存已是空的（0 MB）。');
      return;
    }
    if (!confirm(`确定清理本地 ${info.file_count} 个语音缓存文件（共 ${info.total_size_mb} MB）吗？\n清理后再次播放将自动按需重新生成。`)) {
      return;
    }
    const res = await api('/api/audio/cache/clear', { method: 'POST' });
    alert(`✓ 已清理 ${res.cleared_count || 0} 个缓存音频，释放 ${res.freed_mb || 0} MB 磁盘空间！`);
    updateAudioCacheInfo();
  } catch {
    alert('清理语音缓存失败');
  }
}

// ── Database Backup & Restore ────────────────────────────────────────────────
async function downloadBackupJson() {
  try {
    const data = await api('/api/backup/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `delector_backup_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('导出备份失败');
  }
}

function uploadBackupJson(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async function(evt) {
    try {
      const payload = JSON.parse(evt.target.result);
      await api('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      alert('备份还原成功！');
      loadCards();
      refreshCount();
    } catch {
      alert('备份文件格式不正确或还原失败');
    }
  };
  reader.readAsText(file);
  e.target.value = '';
}

// ── Import modal ──────────────────────────────────────────────────────────────
let currentImportTab = 'text';

function switchImportTab(tab) {
  currentImportTab = tab;
  document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(`tab-btn-${tab}`)?.classList.add('active');
  document.getElementById(`import-tab-${tab}`)?.classList.add('active');
}

function openModal()  {
  document.getElementById('modal-overlay').classList.add('open');
  switchImportTab('text');
}
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

async function submitActiveImport() {
  if (currentImportTab === 'text') {
    await submitImport();
  } else if (currentImportTab === 'url') {
    const url = document.getElementById('imp-url-input').value.trim();
    const title = document.getElementById('imp-url-title').value.trim();
    if (!url) { alert('请输入有效的德语网页链接'); return; }
    const btn = document.getElementById('import-btn');
    btn.textContent = '抓取解析中…'; btn.disabled = true;
    try {
      const data = await api('/api/articles/ingest-url', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url, title })
      });
      closeModal();
      document.getElementById('imp-url-input').value = '';
      document.getElementById('imp-url-title').value = '';
      openReader(data.article_id);
    } catch (e) {
      alert('抓取失败，请检查网址是否为公开德语网页，或直接复制文本导入');
    } finally {
      btn.textContent = '开始阅读'; btn.disabled = false;
    }
  } else if (currentImportTab === 'file') {
    const text = document.getElementById('imp-text').value.trim();
    if (text) {
      await submitImport();
    } else {
      document.getElementById('file-input').click();
    }
  }
}

function handleFileSelect(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  readFileContent(file);
  e.target.value = '';
}

function readFileContent(file) {
  const reader = new FileReader();
  reader.onload = function(evt) {
    const text = evt.target.result;
    const title = file.name.replace(/\.[^/.]+$/, "");
    document.getElementById('imp-title').value = title;
    document.getElementById('imp-text').value = text;
    switchImportTab('text');
  };
  reader.readAsText(file, "UTF-8");
}

function setupDropzone() {
  const dz = document.getElementById('dropzone');
  if (!dz) return;
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evtName => {
    dz.addEventListener(evtName, (e) => { e.preventDefault(); e.stopPropagation(); });
  });
  dz.addEventListener('dragover', () => dz.classList.add('dragover'));
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', (e) => {
    dz.classList.remove('dragover');
    const file = e.dataTransfer?.files?.[0];
    if (file) readFileContent(file);
  });
}

async function submitImport() {
  const text  = document.getElementById('imp-text').value.trim();
  const title = document.getElementById('imp-title').value.trim() || '未命名文稿';
  if (!text) { alert('请输入德语文本'); return; }
  const btn = document.getElementById('import-btn');
  btn.textContent = '处理中…'; btn.disabled = true;
  try {
    const data = await api('/api/articles/ingest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title, raw_text: text })
    });
    closeModal();
    document.getElementById('imp-text').value  = '';
    document.getElementById('imp-title').value = '';
    openReader(data.article_id);
  } catch { alert('导入失败'); }
  finally { btn.textContent = '开始阅读'; btn.disabled = false; }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
async function refreshCount() {
  const { vocab_cards: vc, grammar_cards: gc } = await api('/api/cards');
  document.getElementById('card-count').textContent = vc.length + gc.length;
}

// ── Reading Notes & Selection Tooltip ────────────────────────────────────────
let currentArticleNotes = [];
let activeSelectedRangeText = '';
let activeSelectedSentId = null;
let activeEditingNoteId = null;

async function loadArticleNotes(articleId) {
  try {
    currentArticleNotes = await api(`/api/articles/${articleId}/notes`);
    renderArticleNotes();
  } catch (e) {
    console.error('Failed to load notes', e);
  }
}

function renderArticleNotes() {
  document.querySelectorAll('.tok').forEach(el => {
    el.classList.remove('user-hl-yellow', 'user-hl-green', 'user-hl-pink');
  });
  document.querySelectorAll('.margin-note-badge').forEach(el => el.remove());

  if (!currentArticleNotes || !currentArticleNotes.length) return;

  currentArticleNotes.forEach(note => {
    const phrase = note.selected_text?.trim();
    if (phrase) {
      document.querySelectorAll('.tok').forEach(tokEl => {
        if (phrase.includes(tokEl.textContent.trim()) || tokEl.textContent.trim() === phrase) {
          tokEl.classList.add(`user-hl-${note.color || 'yellow'}`);
        }
      });
    }

    if (note.note_content && note.sentence_id) {
      const sent = currentArticle?.sentences?.find(s => s.id === note.sentence_id);
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

function setupSelectionTooltip() {
  const content = document.getElementById('reader-content');
  const tooltip = document.getElementById('selection-tooltip');
  if (!content || !tooltip) return;

  content.addEventListener('mouseup', () => {
    setTimeout(() => {
      const sel = window.getSelection();
      const text = sel ? sel.toString().trim() : '';
      if (text.length > 0 && content.contains(sel.anchorNode)) {
        activeSelectedRangeText = text;
        const range = sel.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        let node = sel.anchorNode;
        while (node && node !== content) {
          if (node.id && node.id.startsWith('tok-')) {
            const tokId = parseInt(node.id.replace('tok-', ''), 10);
            const foundSent = currentArticle?.sentences?.find(s => s.tokens.some(t => t.id === tokId));
            if (foundSent) activeSelectedSentId = foundSent.id;
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

async function applyHighlight(color) {
  if (!activeSelectedRangeText || !currentArticle) return;
  const tooltip = document.getElementById('selection-tooltip');
  tooltip.classList.add('hidden');

  await api(`/api/articles/${currentArticle.id}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sentence_id: activeSelectedSentId || 1,
      selected_text: activeSelectedRangeText,
      color: color,
      note_content: ''
    })
  });

  await loadArticleNotes(currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

function openNoteDrawerFromSelection() {
  if (!activeSelectedRangeText || !currentArticle) return;
  const tooltip = document.getElementById('selection-tooltip');
  tooltip.classList.add('hidden');

  activeEditingNoteId = null;
  document.getElementById('note-badge-status').textContent = '随笔草稿';
  document.getElementById('note-quote').textContent = `"${activeSelectedRangeText}"`;
  document.getElementById('note-text-input').value = '';
  document.getElementById('save-note-btn').textContent = '✓ 保存便签';
  document.getElementById('del-note-btn').classList.add('hidden');
  
  openDrawer('note');
}

function openNoteDrawerForExisting(noteId) {
  const note = currentArticleNotes.find(n => n.id === noteId);
  if (!note) return;

  activeEditingNoteId = note.id;
  activeSelectedRangeText = note.selected_text;
  activeSelectedSentId = note.sentence_id;

  document.getElementById('note-badge-status').textContent = '已保存便签';
  document.getElementById('note-quote').textContent = `"${note.selected_text}"`;
  document.getElementById('note-text-input').value = note.note_content || '';
  document.getElementById('save-note-btn').textContent = '✓ 更新便签';
  document.getElementById('del-note-btn').classList.remove('hidden');

  openDrawer('note');
}

async function aiNoteAssist() {
  if (!activeSelectedRangeText || !currentArticle) return;
  const btn = document.getElementById('note-ai-btn');
  btn.textContent = '✨ 解析中…';
  btn.disabled = true;

  const sent = currentArticle.sentences?.find(s => s.id === activeSelectedSentId);
  const sentText = sent ? sent.text : activeSelectedRangeText;

  try {
    const res = await api('/api/ai/note-assist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence: sentText, selected_text: activeSelectedRangeText })
    });
    
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

async function saveCurrentNote() {
  if (!activeSelectedRangeText || !currentArticle) return;
  const noteText = document.getElementById('note-text-input').value.trim();

  if (activeEditingNoteId) {
    await api(`/api/notes/${activeEditingNoteId}`, { method: 'DELETE' });
  }

  await api(`/api/articles/${currentArticle.id}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sentence_id: activeSelectedSentId || 1,
      selected_text: activeSelectedRangeText,
      color: 'yellow',
      note_content: noteText
    })
  });

  document.getElementById('save-note-btn').textContent = '✓ 已保存';
  await loadArticleNotes(currentArticle.id);
  window.getSelection()?.removeAllRanges();
}

async function deleteCurrentNote() {
  if (!activeEditingNoteId || !currentArticle) return;
  if (!confirm('确定删除此条随笔便签吗？')) return;
  await api(`/api/notes/${activeEditingNoteId}`, { method: 'DELETE' });
  closeDrawer();
  await loadArticleNotes(currentArticle.id);
}

function playSelectedAudio() {
  if (!activeSelectedRangeText) return;
  playGermanAudio(activeSelectedRangeText);
  document.getElementById('selection-tooltip').classList.add('hidden');
}

function downloadStudyGuide() {
  if (!currentArticle) return;
  window.location.href = `/api/articles/${currentArticle.id}/export-guide`;
}

// ── Global Keyboard Shortcuts ────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  const isEditing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  const isModalOpen = document.getElementById('modal-overlay')?.classList.contains('open');

  if (e.key === 'Escape') {
    clearCefrFocus();
    closeDrawer();
    closeModal();
    return;
  }

  if (isEditing || isModalOpen) return;

  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const drawer = document.getElementById('drawer');
    if (drawer.classList.contains('open')) {
      e.preventDefault();
      saveVocab();
      return;
    }
  }

  // Audio Playback Shortcuts
  if (e.code === 'Space') {
    const isReader = document.getElementById('view-reader')?.classList.contains('active');
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.toggle();
      return;
    }
  } else if (e.key === 'ArrowRight') {
    const isReader = document.getElementById('view-reader')?.classList.contains('active');
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.next();
      return;
    }
  } else if (e.key === 'ArrowLeft') {
    const isReader = document.getElementById('view-reader')?.classList.contains('active');
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.prev();
      return;
    }
  } else if (e.key === 'r' || e.key === 'R') {
    const isReader = document.getElementById('view-reader')?.classList.contains('active');
    if (isReader) {
      e.preventDefault();
      ShadowPlayer.replay();
      return;
    }
  }

  if (e.key === 'j' || e.key === 'k') {
    const tokens = Array.from(document.querySelectorAll('.tok'));
    if (!tokens.length) return;
    const curIndex = tokens.findIndex(el => el.classList.contains('sel'));
    let nextIndex = 0;
    if (e.key === 'j') {
      nextIndex = curIndex < tokens.length - 1 ? curIndex + 1 : 0;
    } else {
      nextIndex = curIndex > 0 ? curIndex - 1 : tokens.length - 1;
    }
    tokens[nextIndex]?.click();
    tokens[nextIndex]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadArticles();
refreshCount();
applyTypography();
setupDropzone();
setupSelectionTooltip();
ShadowPlayer.init();
