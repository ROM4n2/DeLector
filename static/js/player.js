/* DeLector - Shadow Reading Audio Player & TTS Engine */
'use strict';

import { state } from './core.js';

export async function playGermanAudio(text, rate = 0.88) {
  if (!text) return;
  const clean = text.trim();

  // 1. Try Android Native TTS Bridge first
  if (window.AndroidNativeTTS && typeof window.AndroidNativeTTS.speak === 'function') {
    try {
      const ok = window.AndroidNativeTTS.speak(clean, rate);
      if (ok) return;
    } catch (e) {
      console.warn('Native TTS failed, falling back:', e);
    }
  }

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
    await audio.play();
  } catch {
    if (!('speechSynthesis' in window)) {
      const statusEl = document.getElementById('player-status');
      if (statusEl) statusEl.textContent = '⚠ 语音引擎不可用';
      return;
    }
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

export const ShadowPlayer = {
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
    if (!state.currentArticle || !state.currentArticle.sentences || !state.currentArticle.sentences.length) return;
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
    if (!this.isPlaying || !state.currentArticle || !state.currentArticle.sentences) return;
    if (this.currentSentIdx >= state.currentArticle.sentences.length) {
      this.pause();
      this.currentSentIdx = 0;
      return;
    }

    const sent = state.currentArticle.sentences[this.currentSentIdx];
    if (!sent) return;

    this.highlightSentence(this.currentSentIdx);
    this.updateStatusText();

    if (this.audioEl) {
      this.audioEl.pause();
      this.audioEl.removeAttribute('src');
    }

    // Try Native TTS first on Android
    if (window.AndroidNativeTTS && typeof window.AndroidNativeTTS.speak === 'function') {
      try {
        const ok = window.AndroidNativeTTS.speak(sent.text.trim(), this.rate);
        if (ok) {
          const estDuration = Math.max(1500, sent.text.length * 70);
          setTimeout(() => {
            if (!this.isPlaying) return;
            this.handleSentenceFinished(estDuration);
          }, estDuration);
          return;
        }
      } catch (e) {
        console.warn('Native TTS speak error:', e);
      }
    }

    const ratePercent = Math.round((this.rate - 1.0) * 100);
    const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

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
      const pauseMs = Math.max(2000, Math.min(6000, duration * 1.1));
      this.showPauseCountdown(pauseMs);
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, pauseMs);
    } else {
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, 350);
    }
  },

  fallbackWebSpeech(sent) {
    // 原生 TTS 再试一次：必须检查返回值，false 就继续走 speechSynthesis，
    // 不能静默安排"句子结束"计时器（否则播放器无声空转）
    if (window.AndroidNativeTTS && typeof window.AndroidNativeTTS.speak === 'function') {
      try {
        const ok = window.AndroidNativeTTS.speak(sent.text.trim(), this.rate);
        if (ok) {
          const estDuration = Math.max(1500, sent.text.length * 75);
          setTimeout(() => {
            if (!this.isPlaying) return;
            this.handleSentenceFinished(estDuration);
          }, estDuration);
          return;
        }
      } catch (e) {
        console.warn('Native TTS speak error:', e);
      }
    }

    if (!('speechSynthesis' in window)) {
      this.pause();
      this.speakFailed(sent);
      return;
    }
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
        this.speakFailed(sent);
      }
    };

    this.utterance = utt;
    window.speechSynthesis.speak(utt);
  },

  speakFailed(sent) {
    // 三层 TTS（原生 / 服务器 / Web Speech）全失败：停下并给出可见提示，绝不静默推进。
    // 调用方应先 this.pause() 复位播放状态（isPlaying/按钮/高亮/计时器）。
    console.warn('[ShadowPlayer] 所有 TTS 引擎均不可用:', sent?.text);
    const el = document.getElementById('player-status');
    if (el) el.textContent = '⚠ 语音引擎不可用';
  },

  seekSentence(idx) {
    if (!state.currentArticle || !state.currentArticle.sentences) return;
    this.currentSentIdx = Math.max(0, Math.min(state.currentArticle.sentences.length - 1, idx));
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
    const sent = state.currentArticle?.sentences[idx];
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
    if (el && state.currentArticle && state.currentArticle.sentences) {
      el.textContent = `句 ${this.currentSentIdx + 1} / ${state.currentArticle.sentences.length}`;
    }
  },

  showPauseCountdown(ms) {
    const el = document.getElementById('player-status');
    if (el) el.textContent = `🎙️ 请跟读 (${Math.round(ms/1000)}s)…`;
  }
};
