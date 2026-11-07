/* DeLector - Shadow Reading Audio Player & TTS Engine */
"use strict";

import { state } from "./core.js";

const DEFAULT_VOICE = "de-DE-KatjaNeural";

// 音色身份固定为「性别 · 姓名」：不依赖颜色或字形，读屏与视觉同一套文字。
const VOICE_META = {
  "de-DE-KatjaNeural": { name: "Katja", gender: "女声", style: "德国之声推荐" },
  "de-DE-ConradNeural": { name: "Conrad", gender: "男声", style: "严谨沉稳" },
  "de-DE-AmalaNeural": { name: "Amala", gender: "女声", style: "自然清晰" },
  "de-DE-KillianNeural": { name: "Killian", gender: "男声", style: "浑厚母语" },
};

function voiceMeta(voice) {
  return VOICE_META[voice] || VOICE_META[DEFAULT_VOICE];
}

function setStatusText(text, isError = false) {
  const el = document.getElementById("player-status-text");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

// 音色降级提示：只在音色确实没生效时出现，绝不假装选中音色在生效。
function setVoiceNotice(visible) {
  const note = document.getElementById("player-voice-note");
  if (note) note.classList.toggle("hidden", !visible);
}

// 服务器用响应头回报「voice 是否真的进了合成器」：
// 1 = edge_tts 按所选音色合成；0 = 降级到不含 voice 的公共 URL。
function applyVoiceHonoredHeader(resp) {
  const flag = resp.headers.get("X-TTS-Voice-Honored");
  if (flag === "0") setVoiceNotice(true);
  else if (flag === "1") setVoiceNotice(false);
}

export async function playGermanAudio(text, rate = 0.8) {
  if (!text) return;
  const clean = text.trim();

  // 1. Try Android Native TTS Bridge first
  if (
    window.AndroidNativeTTS &&
    typeof window.AndroidNativeTTS.speak === "function"
  ) {
    try {
      const ok = window.AndroidNativeTTS.speak(clean, rate);
      if (ok) {
        setVoiceNotice(true); // 原生桥不接收 voice，系统语音不是所选音色
        return;
      }
    } catch (e) {
      console.warn("Native TTS failed, falling back:", e);
    }
  }

  const voice =
    ShadowPlayer.voice ||
    localStorage.getItem("delector_voice") ||
    DEFAULT_VOICE;
  const ratePercent = Math.round((rate - 1.0) * 100);
  const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

  try {
    const resp = await fetch("/api/audio/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean, voice: voice, rate: rateStr }),
    });
    if (!resp.ok) throw new Error("Neural TTS error");
    applyVoiceHonoredHeader(resp);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    const revokeUrl = () => URL.revokeObjectURL(url);
    audio.onended = revokeUrl;
    audio.onerror = revokeUrl; // 失败/解码错误同样撤销，防泄漏
    await audio.play().catch((err) => {
      revokeUrl();
      throw err;
    });
  } catch {
    if (!("speechSynthesis" in window)) {
      setStatusText("语音引擎不可用", true);
      return;
    }
    setVoiceNotice(true); // 兜底走系统语音，所选音色不生效
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(clean);
    utt.lang = "de-DE";
    utt.rate = rate;
    const voices = window.speechSynthesis.getVoices();
    const deVoice = voices.find(
      (v) =>
        v.lang.startsWith("de") &&
        (v.name.includes("Natural") ||
          v.name.includes("Google") ||
          v.name.includes("German") ||
          v.name.includes("Hedda") ||
          v.name.includes("Stefan")),
    );
    if (deVoice) utt.voice = deVoice;
    window.speechSynthesis.speak(utt);
  }
}

export const ShadowPlayer = {
  isPlaying: false,
  currentSentIdx: 0,
  mode: "shadow", // 'continuous' | 'shadow' | 'loop'
  rate: 0.8,
  voice: localStorage.getItem("delector_voice") || DEFAULT_VOICE,
  audioEl: null,
  pauseTimer: null,
  utterance: null,
  isIntentionalCancel: false,
  _curUrl: null, // 当前 blob object URL：切句/暂停/兜底出口统一撤销，不只等 onended
  _reqToken: 0, // 播放请求令牌：陈旧慢响应不得覆盖新句

  init() {
    this.audioEl = new Audio();
    const savedVoice =
      localStorage.getItem("delector_voice") || DEFAULT_VOICE;
    this.setVoice(savedVoice);
    if ("speechSynthesis" in window) {
      window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
      };
    }
    // Android 原生桥只接收 text/rate，voice 永远不生效：从一开始就如实告知。
    if (
      window.AndroidNativeTTS &&
      typeof window.AndroidNativeTTS.speak === "function"
    ) {
      setVoiceNotice(true);
    }
    document.addEventListener("click", (e) => {
      const pill = document.querySelector(".voice-pill");
      if (pill && !pill.contains(e.target)) this.closeVoiceMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeVoiceMenu();
    });
  },

  reset() {
    this.pause();
    this.currentSentIdx = 0;
    this.clearSentenceHighlight();
    this.updateStatusText();
  },

  setVoice(voice) {
    const next = VOICE_META[voice] ? voice : DEFAULT_VOICE;
    this.voice = next;
    localStorage.setItem("delector_voice", next);

    const meta = voiceMeta(next);
    const label = document.getElementById("voice-current-label");
    if (label) label.textContent = `${meta.gender} · ${meta.name}`;

    document.querySelectorAll(".voice-option").forEach((btn) => {
      const active = btn.dataset.voice === next;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-checked", active ? "true" : "false");
    });
    this.closeVoiceMenu();

    if (this.isPlaying) {
      if (this.pauseTimer) {
        clearTimeout(this.pauseTimer);
        this.pauseTimer = null;
      }
      if (this.audioEl) {
        this.audioEl.pause();
      }
      this.speakCurrentSentence();
    }
  },

  toggleVoiceMenu() {
    const menu = document.getElementById("voice-menu");
    const btn = document.getElementById("voice-current-btn");
    if (!menu || !btn) return;
    const open = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const active = menu.querySelector(".voice-option.active");
      if (active) active.focus();
    }
  },

  closeVoiceMenu() {
    const menu = document.getElementById("voice-menu");
    const btn = document.getElementById("voice-current-btn");
    if (!menu || !btn) return;
    menu.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
  },

  play() {
    if (
      !state.currentArticle ||
      !state.currentArticle.sentences ||
      !state.currentArticle.sentences.length
    )
      return;
    this.isPlaying = true;
    this.updatePlayBtn(true);
    this.speakCurrentSentence();
  },

  pause() {
    this.isPlaying = false;
    this._reqToken++; // 使在途 TTS 响应全部失效
    if (this.pauseTimer) {
      clearTimeout(this.pauseTimer);
      this.pauseTimer = null;
    }
    if (this.audioEl) {
      this.audioEl.pause();
    }
    this._revokeCurrent();
    if ("speechSynthesis" in window) {
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

  _revokeCurrent() {
    if (this._curUrl) {
      URL.revokeObjectURL(this._curUrl);
      this._curUrl = null;
    }
  },

  speakCurrentSentence() {
    if (
      !this.isPlaying ||
      !state.currentArticle ||
      !state.currentArticle.sentences
    )
      return;
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
      this._revokeCurrent(); // 切句前释放上一句 blob
      this.audioEl.removeAttribute("src");
    }

    // Try Native TTS first on Android
    if (
      window.AndroidNativeTTS &&
      typeof window.AndroidNativeTTS.speak === "function"
    ) {
      try {
        const ok = window.AndroidNativeTTS.speak(sent.text.trim(), this.rate);
        if (ok) {
          setVoiceNotice(true); // 原生桥无 voice 参数：当前音色并未生效
          const estDuration = Math.max(1500, sent.text.length * 70);
          setTimeout(() => {
            if (!this.isPlaying) return;
            this.handleSentenceFinished(estDuration);
          }, estDuration);
          return;
        }
      } catch (e) {
        console.warn("Native TTS speak error:", e);
      }
    }

    const ratePercent = Math.round((this.rate - 1.0) * 100);
    const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

    const myToken = ++this._reqToken;
    fetch("/api/audio/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: sent.text,
        voice: this.voice,
        rate: rateStr,
      }),
    })
      .then((resp) => {
        if (!resp.ok) throw new Error("Neural TTS error");
        applyVoiceHonoredHeader(resp); // 服务器明确回报所选音色是否生效
        return resp.blob();
      })
      .then((blob) => {
        if (this._reqToken !== myToken || !this.isPlaying) return; // 陈旧响应丢弃
        const audioUrl = URL.createObjectURL(blob);
        this._revokeCurrent(); // 上一句 blob 此刻仍未播完也释放
        this._curUrl = audioUrl;
        this.audioEl.src = audioUrl;
        const startTime = Date.now();

        this.audioEl.onended = () => {
          this._revokeCurrent();
          if (!this.isPlaying) return;
          const duration = Date.now() - startTime;
          this.handleSentenceFinished(duration);
        };

        this.audioEl.onerror = () => {
          this._revokeCurrent();
          this.fallbackWebSpeech(sent);
        };

        this.audioEl.play().catch(() => {
          this._revokeCurrent();
          this.fallbackWebSpeech(sent);
        });
      })
      .catch(() => {
        this._revokeCurrent();
        this.fallbackWebSpeech(sent);
      });
  },

  handleSentenceFinished(duration) {
    if (this.mode === "loop") {
      this.pauseTimer = setTimeout(() => this.speakCurrentSentence(), 700);
    } else if (this.mode === "shadow") {
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
    if (
      window.AndroidNativeTTS &&
      typeof window.AndroidNativeTTS.speak === "function"
    ) {
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
        console.warn("Native TTS speak error:", e);
      }
    }

    if (!("speechSynthesis" in window)) {
      this.pause();
      this.speakFailed(sent);
      return;
    }
    setVoiceNotice(true); // Web Speech 只能挑系统语言，不是所选 neural 音色
    this.isIntentionalCancel = true;
    window.speechSynthesis.cancel();
    this.isIntentionalCancel = false;

    const utt = new SpeechSynthesisUtterance(sent.text.trim());
    utt.lang = "de-DE";
    utt.rate = this.rate;

    const voices = window.speechSynthesis.getVoices();
    const deVoice = voices.find(
      (v) =>
        v.lang.startsWith("de") &&
        (v.name.includes("Natural") ||
          v.name.includes("Google") ||
          v.name.includes("German") ||
          v.name.includes("Hedda") ||
          v.name.includes("Stefan")),
    );
    if (deVoice) utt.voice = deVoice;

    const startTime = Date.now();

    utt.onend = () => {
      if (!this.isPlaying) return;
      const duration = Date.now() - startTime;
      this.handleSentenceFinished(duration);
    };

    utt.onerror = (e) => {
      if (
        e.error !== "interrupted" &&
        e.error !== "canceled" &&
        !this.isIntentionalCancel
      ) {
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
    console.warn("[ShadowPlayer] 所有 TTS 引擎均不可用:", sent?.text);
    setStatusText("语音引擎不可用", true);
  },

  seekSentence(idx) {
    if (!state.currentArticle || !state.currentArticle.sentences) return;
    this.currentSentIdx = Math.max(
      0,
      Math.min(state.currentArticle.sentences.length - 1, idx),
    );
    const targetSent = state.currentArticle.sentences[this.currentSentIdx];
    if (targetSent && window.renderSyntaxViewForSentence) {
      window.renderSyntaxViewForSentence(targetSent.id);
    }
    if (this.isPlaying) {
      if (this.pauseTimer) {
        clearTimeout(this.pauseTimer);
        this.pauseTimer = null;
      }
      this.speakCurrentSentence();
    } else {
      this.highlightSentence(this.currentSentIdx);
      this.updateStatusText();
    }
  },

  next() {
    this.seekSentence(this.currentSentIdx + 1);
  },
  prev() {
    this.seekSentence(this.currentSentIdx - 1);
  },
  replay() {
    this.seekSentence(this.currentSentIdx);
  },

  setMode(mode) {
    this.mode = mode;
    document
      .querySelectorAll(".mode-btn")
      .forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    if (this.isPlaying) {
      if (this.pauseTimer) {
        clearTimeout(this.pauseTimer);
        this.pauseTimer = null;
      }
      this.speakCurrentSentence();
    }
  },

  setSpeed(rate) {
    this.rate = rate;
    document.querySelectorAll(".speed-step-btn").forEach((b) => {
      b.classList.toggle("active", parseFloat(b.dataset.speed) === rate);
    });
    if (this.isPlaying) {
      if (this.pauseTimer) {
        clearTimeout(this.pauseTimer);
        this.pauseTimer = null;
      }
      this.speakCurrentSentence();
    }
  },

  highlightSentence(idx) {
    document
      .querySelectorAll(".tok")
      .forEach((el) => el.classList.remove("reading-active"));
    const sent = state.currentArticle?.sentences[idx];
    if (!sent || !sent.tokens || !sent.tokens.length) return;
    sent.tokens.forEach((t) => {
      const el = document.getElementById("tok-" + t.id);
      if (el) el.classList.add("reading-active");
    });
    const firstTok = document.getElementById("tok-" + sent.tokens[0].id);
    if (firstTok)
      firstTok.scrollIntoView({ behavior: "smooth", block: "center" });
  },

  clearSentenceHighlight() {
    document
      .querySelectorAll(".tok.reading-active")
      .forEach((el) => el.classList.remove("reading-active"));
  },

  updatePlayBtn(playing) {
    const btn = document.getElementById("player-play-btn");
    if (btn) btn.innerHTML = playing
      ? '<svg class="ui-ico" aria-hidden="true" focusable="false"><use href="#ui-ico-pause"></use></svg>'
      : '<svg class="ui-ico" aria-hidden="true" focusable="false"><use href="#ui-ico-play"></use></svg>';
  },

  updateStatusText() {
    if (state.currentArticle && state.currentArticle.sentences) {
      setStatusText(
        `句 ${this.currentSentIdx + 1} / ${state.currentArticle.sentences.length}`,
      );
    }
  },

  showPauseCountdown(ms) {
    setStatusText(`请跟读 (${Math.round(ms / 1000)}s)…`);
  },
};
