/* DeLector - 听力微训工坊 (Listening Micro-Training Lab)
 *
 * 三模式控制器：L 精听/影子跟读 · D 听写诊断 · C 听力填空。
 * 挂载于备考域 view-exam（index.html #exam-listen 容器），main.js
 * `import * as ListenLab` 命名空间接线（参照 A1Hoeren 先例）。
 *
 * 后端契约（delector/routes/listen.py，字段名逐字一致 —— 红线 11）：
 *   GET  /api/listen/materials[?level=]                    → {items:[{source_type,source_id,title,level}]}
 *   GET  /api/listen/materials/{source_type}/{source_id}   → {source_type,source_id,title,level,sentences:[str]}
 *   POST /api/listen/diagnose  body {expected,actual}      → {tokens:[{token,status,hint}],correct,total,score}
 *   POST /api/listen/trials    body {mode,source_type,source_id,level,total,correct,duration_sec}
 *
 * 播放队列自管（不重构 reader 的 ShadowPlayer）：逐句 playGermanAudio +
 * 估算时长推进（text.length*70ms，对齐 ShadowPlayer Native TTS 路径）；
 * 会话令牌 _q.token 使陈旧计时/TTS 响应失效；三层 TTS 全不可用时停止并
 * 显示「⚠ 语音引擎不可用」，不静默空转（对齐 ShadowPlayer.speakFailed）。
 *
 * Mode C 前端本地挖空：按后端 make_cloze 同策略镜像（分词 + 名词/动词
 * 启发式 + 功能词停用表），___ 占位 + 大小写/变音容差校验。
 */
"use strict";

import { api, esc, notify } from "./core.js";
import { playGermanAudio } from "./player.js";

/* ── 会话状态（单会话单队列） ─────────────────────────────────────────────── */
const _q = {
  mode: "L",             // 'L' | 'D' | 'C'
  level: "all",          // 'all' | 'A1' | 'A2'
  materials: [],         // 当前等级材料清单
  materialsLoaded: false,
  material: null,        // 当前材料 {source_type, source_id, title, level}
  sentences: [],         // 句子数组
  idx: 0,                // 当前句索引
  flow: "shadow",        // 'shadow' | 'continuous'（仅 L 模式生效）
  speed: 1.0,
  playing: false,
  token: 0,              // 会话令牌：陈旧计时/响应失效
  timer: null,
  done: [],              // 每句 {answered, diag|ok|skipped}
  statCorrect: 0,
  statTotal: 0,
  startedAt: 0,
  finished: false,
};

/* ── Mode C 挖空镜像（对齐后端 make_cloze 策略） ──────────────────────────── */
const _PUNCT_CHARS = ".,!?;:„“”\"'«»()[]{}—–-…·";
const _UMLAUT_REPL = { ü: "u", ä: "a", ö: "o", é: "e", ß: "ss" };
// 功能词停用表（镜像 delector/services/listen.py 的 _FUNCTION_WORDS）
const _FUNCTION_WORDS = new Set([
  "der", "die", "das", "dem", "den", "des",
  "ein", "eine", "einen", "einem", "einer", "eines",
  "ich", "du", "er", "sie", "es", "wir", "ihr", "man",
  "mein", "dein", "sein", "mich", "dich", "mir", "dir", "uns", "euch",
  "ist", "sind", "war", "waren", "bin", "bist", "hat", "haben", "hast",
  "und", "oder", "aber", "wie", "was", "wann", "wo", "wer", "wen", "wem",
  "als", "dass", "denn",
  "zu", "zum", "zur", "mit", "auf", "an", "im", "in", "aus", "bei", "nach",
  "von", "vom", "für", "über", "um", "nicht", "ja", "nein", "so", "da",
  "hier", "sehr", "auch", "noch", "schon",
]);

// 逐字诊断六类 → 胶囊文案（对齐 ListenDiagnosis 的 TokenStatus）
const _STATUS_META = {
  correct: { label: "正确", cls: "st-correct" },
  umlaut: { label: "变音", cls: "st-umlaut" },
  case: { label: "大小写", cls: "st-case" },
  inflection: { label: "词尾", cls: "st-inflection" },
  missing: { label: "缺少", cls: "st-missing" },
  extra: { label: "多余", cls: "st-extra" },
};

/* ── 工具函数 ─────────────────────────────────────────────────────────────── */

function el(id) {
  return document.getElementById(id);
}

// 剥离首尾标点（双端扫描，避免正则转义字符类）
function _stripPunct(w) {
  let i = 0;
  let j = w.length - 1;
  while (i <= j && _PUNCT_CHARS.includes(w[i])) i += 1;
  while (j >= i && _PUNCT_CHARS.includes(w[j])) j -= 1;
  return w.slice(i, j + 1);
}

// 估算播放时长（对齐 ShadowPlayer 的 text.length * 70）
function _estDuration(text) {
  return Math.max(1500, String(text).length * 70);
}

// 三层 TTS 兜底预检：原生桥或 Web Speech 任一可用即可出声（server TTS 失败会
// 内部 fallback 到 Web Speech；两者皆无 = 全链路不可用，需停止并提示）。
function _ttsUsable() {
  if (window.AndroidNativeTTS && typeof window.AndroidNativeTTS.speak === "function") {
    return true;
  }
  return "speechSynthesis" in window;
}

// 变音归一（大小写 + ü→u / ä→a / ö→o / é→e / ß→ss）——填空校验容差用
function _normForCompare(s) {
  let out = "";
  for (const ch of String(s).toLowerCase()) out += _UMLAUT_REPL[ch] || ch;
  return out;
}

// 填空校验：大小写容差（lower 相等）或变音替换后相等
function _clozeMatch(input, answer) {
  const a = String(input || "").trim();
  const b = String(answer || "").trim();
  if (!a || !b) return false;
  if (a.toLowerCase() === b.toLowerCase()) return true;
  return _normForCompare(a) === _normForCompare(b);
}

// 前端本地挖空（镜像后端 make_cloze：<5 词不挖、名词优先、动词次之、每次 1 空）
function _makeCloze(sentence) {
  const words = String(sentence || "").trim().split(/\s+/);
  if (words.length < 5) return null;
  const cores = words.map(_stripPunct);
  let pick = null;
  // 名词候选：非句首、首字符大写（含变音大写）、非功能词
  for (let i = 1; i < words.length; i += 1) {
    const c = cores[i];
    if (c && /^[A-ZÄÖÜ]/.test(c) && !_FUNCTION_WORDS.has(c.toLowerCase())) {
      pick = i;
      break;
    }
  }
  // 动词候选：词长 ≥3、常见词尾 -en/-n/-e、非功能词
  if (pick == null) {
    for (let i = 0; i < words.length; i += 1) {
      const low = cores[i].toLowerCase();
      if (low.length >= 3 && /(en|n|e)$/.test(low) && !_FUNCTION_WORDS.has(low)) {
        pick = i;
        break;
      }
    }
  }
  if (pick == null) return null;
  const blanks = words.map((w, i) => (i === pick ? "___" : w));
  return {
    text_with_blanks: blanks.join(" "),
    answer: cores[pick],
    source: sentence,
    blank_index: pick,
  };
}

function _clozeTextHtml(item) {
  return esc(item.text_with_blanks).replace(/___/g, '<span class="listen-blank">___</span>');
}

function _capHtml(t) {
  const meta = _STATUS_META[t.status] || { label: t.status, cls: "st-extra" };
  const hint = t.hint || meta.label;
  return `<span class="listen-cap ${meta.cls}" title="${esc(hint)}">${esc(t.token)}<em>${meta.label}</em></span>`;
}

/* ── 样式注入（Academic Modern Editorial token · 暖纸墨线风） ─────────────── */
let _styleInjected = false;
function _ensureStyle() {
  if (_styleInjected || el("listen-lab-style")) return;
  _styleInjected = true;
  const style = document.createElement("style");
  style.id = "listen-lab-style";
  style.textContent = `
#exam-listen { --listen-bg: var(--paper-warm); }
.listen-lab-topbar { display:flex; align-items:center; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; margin-bottom:0.75rem; }
.listen-stage { margin-top:0.25rem; }
.listen-subhead { font-size:0.75rem; color:var(--pencil); font-family:var(--mono); margin-top:0.25rem; letter-spacing:0.02em; }
.listen-bar { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin:0.35rem 0; }
.listen-bar-label { font-size:0.6875rem; font-family:var(--mono); color:var(--ink-faint); text-transform:uppercase; letter-spacing:0.08em; margin-right:0.25rem; white-space:nowrap; }
.listen-pill { min-height:44px; padding:0.5rem 0.9rem; border:1.5px solid var(--ink); border-radius:999px; background:var(--paper-card); color:var(--ink); font-family:var(--mono); font-size:0.75rem; cursor:pointer; }
.listen-pill.active { background:var(--ink); color:var(--paper); }
.listen-material-card { display:flex; align-items:center; gap:0.5rem; min-height:44px; padding:0.45rem 0.8rem; border:1.5px solid var(--rule); border-radius:8px; background:var(--paper-card); font-size:0.8125rem; cursor:pointer; text-align:left; max-width:100%; }
.listen-material-card.active { border-color:var(--coral); background:var(--paper-warm); box-shadow:var(--shadow-sm); }
.listen-badge { font-family:var(--mono); font-size:0.6875rem; font-weight:700; padding:0.15rem 0.4rem; border-radius:4px; background:var(--paper-deep); color:var(--ink); }
.listen-badge.A2 { background:var(--hl-A2); color:var(--hl-A2-ink); }
.listen-mat-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.listen-mat-src { font-size:0.6875rem; color:var(--ink-faint); font-family:var(--mono); white-space:nowrap; }
.listen-empty { font-size:0.8125rem; color:var(--pencil); padding:0.5rem 0; }
.listen-player-group { display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap; }
.listen-btn { min-height:44px; padding:0.5rem 0.85rem; border:1.5px solid var(--ink); border-radius:6px; background:var(--paper-card); color:var(--ink); font-family:var(--mono); font-size:0.75rem; cursor:pointer; }
.listen-btn-dark { background:var(--ink); color:var(--paper); }
.listen-btn-main { background:var(--coral); border-color:var(--coral); color:#fff; }
.listen-player-status { margin-left:auto; font-size:0.75rem; font-family:var(--mono); color:var(--pencil); white-space:nowrap; }
.listen-player-status.warn { color:var(--cherry); font-weight:700; }
.listen-stage-head { display:flex; align-items:baseline; justify-content:space-between; gap:0.5rem; margin:0.75rem 0 0.5rem; flex-wrap:wrap; }
.listen-progress { font-family:var(--mono); font-size:0.75rem; color:var(--pencil); }
.listen-sent-list { display:flex; flex-direction:column; gap:0.4rem; }
.listen-sent { display:flex; align-items:center; gap:0.6rem; min-height:44px; padding:0.5rem 0.75rem; border:1px solid var(--rule-light); border-left:3px solid transparent; border-radius:6px; background:var(--paper-card); font-size:0.875rem; cursor:pointer; }
.listen-sent.active { border-left-color:var(--coral); background:var(--paper-warm); }
.listen-sent-idx { font-family:var(--mono); font-size:0.6875rem; color:var(--ink-faint); }
.listen-sent-text { flex:1; }
.listen-hidden { color:var(--ink-faint); font-family:var(--mono); font-size:0.75rem; }
.listen-mark { font-family:var(--mono); font-weight:700; }
.listen-mark.ok { color:var(--moss); }
.listen-mark.no { color:var(--cherry); }
.listen-mark.skip { color:var(--ink-faint); }
.listen-dict-card { border:1.5px solid var(--ink); border-radius:8px; background:var(--paper-card); padding:1rem; margin:0.5rem 0; box-shadow:var(--shadow-sm); }
.listen-hidden-tip { font-size:0.8125rem; color:var(--pencil); margin-bottom:0.75rem; }
.listen-input-row { display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
.listen-input { flex:1; min-width:220px; min-height:44px; padding:0.5rem 0.75rem; border:1.5px solid var(--rule); border-radius:6px; background:var(--paper); color:var(--ink); font-size:0.9375rem; font-family:var(--sans); }
.listen-cloze-text { font-size:1.0625rem; line-height:1.7; margin-bottom:0.75rem; color:var(--ink); }
.listen-blank { display:inline-block; min-width:3.5rem; border-bottom:2px solid var(--coral); color:var(--coral); font-weight:700; text-align:center; }
.listen-feedback { margin-top:0.75rem; border-top:1px dashed var(--rule); padding-top:0.75rem; display:flex; flex-direction:column; gap:0.6rem; align-items:flex-start; }
.listen-cap-row { display:flex; flex-wrap:wrap; gap:0.35rem; }
.listen-cap { display:inline-flex; align-items:center; gap:0.3rem; padding:0.25rem 0.5rem; border-radius:999px; border:1.5px solid; font-size:0.8125rem; font-family:var(--mono); }
.listen-cap em { font-style:normal; font-size:0.625rem; font-family:var(--mono); opacity:0.85; }
.listen-cap.st-correct { border-color:var(--moss); background:#e9f2ea; color:#2c5a31; }
.listen-cap.st-umlaut { border-color:#4a6fa5; background:#eaf0f9; color:#34568c; }
.listen-cap.st-case { border-color:var(--mustard); background:#fbf3dc; color:#7a5d00; }
.listen-cap.st-inflection { border-color:var(--amber); background:#fbeedd; color:#9a5200; }
.listen-cap.st-missing { border-color:var(--cherry); background:#fbeae7; color:#8f2424; }
.listen-cap.st-extra { border-color:var(--pencil); background:#f0eeea; color:#4a443c; }
.listen-fb-stat { font-family:var(--mono); font-size:0.75rem; color:var(--pencil); }
.listen-score-card { margin-top:1rem; border:1.5px solid var(--ink); border-radius:8px; background:var(--paper-warm); padding:1.25rem; box-shadow:3px 4px 0 rgba(26,23,20,0.12); }
.listen-score-head { font-family:var(--serif-heading); font-size:1.125rem; font-weight:700; margin-bottom:0.6rem; }
.listen-score-row { display:flex; gap:0.6rem; align-items:baseline; font-size:0.9375rem; margin-bottom:0.9rem; flex-wrap:wrap; }
.listen-score-actions { display:flex; gap:0.5rem; flex-wrap:wrap; }
`;
  (document.head || document.documentElement).appendChild(style);
}

/* ── 播放队列（自管，会话令牌防陈旧响应） ─────────────────────────────────── */

function _clearTimer() {
  if (_q.timer) {
    clearTimeout(_q.timer);
    _q.timer = null;
  }
}

function _stop() {
  _clearTimer();
  _q.token += 1;
  _q.playing = false;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function _setStatus(text, warn) {
  const s = el("listen-status");
  if (s) {
    s.textContent = text;
    s.classList.toggle("warn", !!warn);
  }
}

function _seekTo(i) {
  _clearTimer();
  _q.token += 1;
  _q.playing = false;
  _q.idx = Math.max(0, Math.min(_q.sentences.length - 1, i));
}

// 播放当前句：估算时长推进；L 模式自动连播（跟读停顿/连读），D/C 播完停住等输入
function _playCurrent() {
  const sent = _q.sentences[_q.idx];
  if (!sent || _q.finished) return;
  _clearTimer();
  _q.token += 1;
  _q.playing = true;
  const myTok = _q.token;
  // 先渲染再写状态：_renderPlayerBar 会重建 #listen-status，顺序颠倒提示会被清空
  _renderAll();
  _setStatus(`▶ 句 ${_q.idx + 1} / ${_q.sentences.length} · ${_q.speed}x`);

  if (!_ttsUsable()) {
    // 三层 TTS 全不可用：停止并给出可见提示，绝不静默空转
    _stop();
    _renderAll();
    _setStatus("⚠ 语音引擎不可用", true);
    return;
  }
  playGermanAudio(sent, _q.speed);
  const dur = _estDuration(sent);
  _q.timer = setTimeout(() => {
    if (myTok !== _q.token) return; // 陈旧计时：会话已切走
    _q.playing = false;
    if (_q.mode === "L") {
      // 跟读停顿：max(2000, min(6000, dur*1.1))；连读：350ms
      const pause = _q.flow === "shadow" ? Math.max(2000, Math.min(6000, dur * 1.1)) : 350;
      _q.timer = setTimeout(() => {
        if (myTok !== _q.token) return;
        _advanceTo(_q.idx + 1);
      }, pause);
      _renderAll();
    } else {
      _renderAll();
      _focusInput();
    }
  }, dur);
}

function _focusInput() {
  const id = _q.mode === "D" ? "listen-dict-input" : "listen-cloze-input";
  const input = el(id);
  if (input) input.focus();
}

// 跳到指定句：L 模式自动连播，D/C 停在目标句等输入
function _advanceTo(i) {
  _clearTimer();
  _q.token += 1;
  _q.playing = false;
  if (i >= _q.sentences.length) {
    _finishSession();
    return;
  }
  _q.idx = Math.max(0, i);
  _renderAll();
  if (_q.mode === "L") _playCurrent();
}

function _startSession(data) {
  _stop();
  _q.material = {
    source_type: data.source_type,
    source_id: data.source_id,
    title: data.title,
    level: data.level,
  };
  _q.sentences = Array.isArray(data.sentences) ? data.sentences.slice() : [];
  _q.idx = 0;
  _q.done = _q.sentences.map(() => ({}));
  _q.statCorrect = 0;
  _q.statTotal = 0;
  _q.finished = false;
  _q.startedAt = Date.now();
  _renderAll();
}

function _finishSession() {
  _clearTimer();
  _q.token += 1;
  _q.playing = false;
  _q.finished = true;
  const durationSec = Math.max(1, Math.round((Date.now() - _q.startedAt) / 1000));
  _renderAll();
  // 成绩落盘：失败静默降级（本地成绩照常展示），不阻断会话
  if (_q.mode === "D" || _q.mode === "C") {
    api("/api/listen/trials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: _q.mode === "D" ? "dictation" : "cloze",
        source_type: _q.material.source_type,
        source_id: _q.material.source_id,
        level: _q.material.level,
        total: _q.statTotal,
        correct: _q.statCorrect,
        duration_sec: durationSec,
      }),
    }).catch(() => { /* 静默降级：不阻断，成绩已在本地展示 */ });
  }
}

/* ── 渲染 ─────────────────────────────────────────────────────────────────── */

function _renderLevelBar() {
  const bar = el("listen-level-bar");
  if (!bar) return;
  bar.innerHTML =
    `<span class="listen-bar-label">等级</span>` +
    [
      ["all", "全部"],
      ["A1", "A1"],
      ["A2", "A2"],
    ]
      .map(
        ([v, label]) =>
          `<button class="listen-pill${_q.level === v ? " active" : ""}" onclick="ListenLab.setListenLevel('${v}')">${label}</button>`,
      )
      .join("");
}

function _renderMaterialBar() {
  const bar = el("listen-material-bar");
  if (!bar) return;
  if (!_q.materialsLoaded) {
    bar.innerHTML = `<span class="listen-empty">⏳ 正在加载材料…</span>`;
    return;
  }
  if (!_q.materials.length) {
    bar.innerHTML = `<span class="listen-empty">当前等级暂无材料 —— 可在遇见区添加分级短文（A1/A2）</span>`;
    return;
  }
  bar.innerHTML =
    `<span class="listen-bar-label">材料</span>` +
    _q.materials
      .map((m) => {
        const active =
          _q.material &&
          _q.material.source_type === m.source_type &&
          _q.material.source_id === m.source_id;
        return `<button class="listen-material-card${active ? " active" : ""}" onclick="ListenLab.selectListenMaterial('${m.source_type}', ${Number(m.source_id)})">
          <span class="listen-badge ${esc(m.level)}">${esc(m.level)}</span>
          <span class="listen-mat-title">${esc(m.title)}</span>
          <span class="listen-mat-src">${m.source_type === "hoeren" ? "🎧 听力句库" : "📖 分级短文"}</span>
        </button>`;
      })
      .join("");
}

function _renderModeBar() {
  const bar = el("listen-mode-bar");
  if (!bar) return;
  if (!_q.material) {
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML =
    `<span class="listen-bar-label">模式</span>` +
    [
      ["L", "🎧 精听/跟读"],
      ["D", "✍️ 听写"],
      ["C", "⬚ 填空"],
    ]
      .map(
        ([v, label]) =>
          `<button class="listen-pill${_q.mode === v ? " active" : ""}" onclick="ListenLab.setListenMode('${v}')">${label}</button>`,
      )
      .join("");
}

function _renderPlayerBar() {
  const bar = el("listen-player-bar");
  if (!bar) return;
  if (!_q.material) {
    bar.innerHTML = "";
    return;
  }
  const playLabel = _q.playing ? "⏸ 暂停" : "▶ 播放";
  const speeds = [0.75, 0.9, 1.0, 1.1, 1.25];
  const flowHtml =
    _q.mode === "L"
      ? `<span class="listen-bar-label">节奏</span>` +
        `<button class="listen-pill${_q.flow === "shadow" ? " active" : ""}" onclick="ListenLab.listenSetFlow('shadow')" title="播放后留跟读停顿">🎙️ 跟读</button>` +
        `<button class="listen-pill${_q.flow === "continuous" ? " active" : ""}" onclick="ListenLab.listenSetFlow('continuous')" title="句子连续朗读">▶ 连读</button>`
      : "";
  bar.innerHTML =
    `<div class="listen-player-group">` +
    `<button class="listen-btn listen-btn-main" onclick="ListenLab.listenPlayToggle()">${playLabel}</button>` +
    `<button class="listen-btn" onclick="ListenLab.listenPrev()" title="上一句">⏮</button>` +
    `<button class="listen-btn" onclick="ListenLab.listenNext()" title="下一句">⏭</button>` +
    `<button class="listen-btn" onclick="ListenLab.listenReplay()" title="重听当前句">🔁</button>` +
    `</div>` +
    `<div class="listen-player-group"><span class="listen-bar-label">语速</span>` +
    speeds
      .map(
        (s) =>
          `<button class="listen-pill${_q.speed === s ? " active" : ""}" onclick="ListenLab.listenSetSpeed(${s})">${s}x</button>`,
      )
      .join("") +
    `</div>` +
    flowHtml +
    `<div class="listen-player-status" id="listen-status"></div>`;
}

// 句子列表：L 显示原文；D 隐藏原文（答过才揭示）；C 显示挖空文本
function _sentListHtml() {
  return _q.sentences
    .map((s, i) => {
      const d = _q.done[i] || {};
      let mark = "";
      if (d.answered) {
        if (_q.mode === "D") {
          const diag = d.diag;
          const ok = diag && diag.correct === diag.total;
          mark = `<span class="listen-mark ${ok ? "ok" : "no"}">${ok ? "✓" : "✗"}</span>`;
        } else if (_q.mode === "C") {
          mark = `<span class="listen-mark ${d.ok ? "ok" : "no"}">${d.ok ? "✓" : "✗"}</span>`;
        }
      } else if (d.skipped) {
        mark = `<span class="listen-mark skip">↷</span>`;
      }
      let textHtml;
      if (_q.mode === "D") {
        textHtml = d.answered
          ? esc(s)
          : `<span class="listen-hidden">🔒 第 ${i + 1} 句 · 原文已隐藏（点击重听）</span>`;
      } else if (_q.mode === "C") {
        const item = _makeCloze(s);
        textHtml = item ? _clozeTextHtml(item) : esc(s);
      } else {
        textHtml = esc(s);
      }
      const active = i === _q.idx ? " active" : "";
      return `<div class="listen-sent${active}" onclick="ListenLab.listenJump(${i})" role="button" tabindex="0">
        <span class="listen-sent-idx">${String(i + 1).padStart(2, "0")}</span>
        <span class="listen-sent-text">${textHtml}</span>${mark}
      </div>`;
    })
    .join("");
}

function _dictationHtml() {
  const i = _q.idx;
  const sent = _q.sentences[i];
  if (!sent) return "";
  const d = _q.done[i] || {};
  const feedback = d.answered && d.diag
    ? `<div class="listen-feedback">
        <div class="listen-cap-row">${(d.diag.tokens || []).map(_capHtml).join("")}</div>
        <div class="listen-fb-stat">✓ ${d.diag.correct} / ${d.diag.total} 词</div>
        <button class="listen-btn" onclick="ListenLab.listenNext()">下一句 ▶</button>
      </div>`
    : "";
  return `
    <div class="listen-stage-head">
      <span class="listen-bar-label">听写 · 隐藏文本（先播放，再复述输入）</span>
      <span class="listen-progress">句 ${i + 1} / ${_q.sentences.length}</span>
    </div>
    <div class="listen-dict-card">
      <div class="listen-hidden-tip">🔒 原文已隐藏 —— 点「▶ 播放」听写，再在下方输入复现的句子</div>
      <div class="listen-input-row">
        <input id="listen-dict-input" class="listen-input" type="text" placeholder="输入你听到的德语句子…" autocomplete="off" autocorrect="off" onkeydown="if (event.key === 'Enter') ListenLab.listenSubmitDictation();" />
        <button class="listen-btn listen-btn-dark" onclick="ListenLab.listenSubmitDictation()">✓ 提交判分</button>
        <button class="listen-btn" onclick="ListenLab.listenSkip()">跳过</button>
      </div>
      ${feedback}
    </div>
    <div class="listen-sent-list">${_sentListHtml()}</div>
  `;
}

function _clozeHtml() {
  const i = _q.idx;
  const sent = _q.sentences[i];
  if (!sent) return "";
  const item = _makeCloze(sent);
  const d = _q.done[i] || {};
  if (!item) {
    return `
      <div class="listen-stage-head">
        <span class="listen-bar-label">填空 · 本句无可挖词</span>
        <span class="listen-progress">句 ${i + 1} / ${_q.sentences.length}</span>
      </div>
      <div class="listen-dict-card">
        <div class="listen-hidden-tip">本句过短或全为功能词，无法挖空 —— 点击下一句继续</div>
        <div class="listen-input-row">
          <button class="listen-btn listen-btn-dark" onclick="ListenLab.listenNext()">下一句 ▶</button>
        </div>
      </div>
      <div class="listen-sent-list">${_sentListHtml()}</div>
    `;
  }
  const feedback = d.answered
    ? `<div class="listen-feedback">
        <div class="listen-cap-row">${d.ok
            ? `<span class="listen-cap st-correct">✓ ${esc(item.answer)}</span>`
            : `<span class="listen-cap st-missing">✗ 答案：${esc(item.answer)}</span>`}</div>
        <div class="listen-fb-stat">${d.ok ? "回答正确" : "回答有误，看答案后点下一句"}</div>
        <button class="listen-btn" onclick="ListenLab.listenNext()">下一句 ▶</button>
      </div>`
    : "";
  return `
    <div class="listen-stage-head">
      <span class="listen-bar-label">填空 · 先听后填</span>
      <span class="listen-progress">句 ${i + 1} / ${_q.sentences.length}</span>
    </div>
    <div class="listen-dict-card">
      <div class="listen-cloze-text">${_clozeTextHtml(item)}</div>
      <div class="listen-input-row">
        <input id="listen-cloze-input" class="listen-input" type="text" placeholder="填入 ___ 处的单词…" autocomplete="off" autocorrect="off" onkeydown="if (event.key === 'Enter') ListenLab.listenSubmitCloze();" />
        <button class="listen-btn listen-btn-dark" onclick="ListenLab.listenSubmitCloze()">✓ 校验</button>
        <button class="listen-btn" onclick="ListenLab.listenSkip()">跳过</button>
      </div>
      ${feedback}
    </div>
    <div class="listen-sent-list">${_sentListHtml()}</div>
  `;
}

function _renderStage() {
  const stage = el("listen-stage");
  if (!stage) return;
  if (!_q.material || _q.finished) {
    stage.innerHTML = "";
    return;
  }
  if (_q.mode === "L") {
    stage.innerHTML = `
      <div class="listen-stage-head">
        <span class="listen-bar-label">${esc(_q.material.title)} · ${esc(_q.material.level)} · ${_q.sentences.length} 句</span>
        <span class="listen-progress">句 ${_q.idx + 1} / ${_q.sentences.length}</span>
      </div>
      <div class="listen-sent-list">${_sentListHtml()}</div>
    `;
  } else if (_q.mode === "D") {
    stage.innerHTML = _dictationHtml();
  } else if (_q.mode === "C") {
    stage.innerHTML = _clozeHtml();
  }
}

function _renderScoreCard() {
  const card = el("listen-score-card");
  if (!card) return;
  if (!_q.material || !_q.finished) {
    card.innerHTML = "";
    return;
  }
  if (_q.mode === "L") {
    card.innerHTML = `
      <div class="listen-score-card">
        <div class="listen-score-head">🏁 精听完成</div>
        <div class="listen-score-row">🎉 已完整听完 ${_q.sentences.length} 句（${esc(_q.material.title)}）</div>
        <div class="listen-score-actions">
          <button class="listen-btn" onclick="ListenLab.listenRestart()">↺ 再练一次</button>
          <button class="listen-btn listen-btn-dark" onclick="ListenLab.listenExit()">⟲ 换材料</button>
        </div>
      </div>
    `;
    return;
  }
  const pct = _q.statTotal ? Math.round((_q.statCorrect / _q.statTotal) * 100) : 0;
  card.innerHTML = `
    <div class="listen-score-card">
      <div class="listen-score-head">🏁 本会话成绩 · ${_q.mode === "D" ? "听写" : "填空"}</div>
      <div class="listen-score-row">
        <span>正确 <b>${_q.statCorrect}</b></span><span>/</span><span>总计 <b>${_q.statTotal}</b></span><span>·</span><span>${pct}%</span>
      </div>
      <div class="listen-score-actions">
        <button class="listen-btn" onclick="ListenLab.listenRestart()">↺ 再练一次</button>
        <button class="listen-btn listen-btn-dark" onclick="ListenLab.listenExit()">⟲ 换材料</button>
      </div>
    </div>
  `;
}

function _renderAll() {
  _renderLevelBar();
  _renderMaterialBar();
  _renderModeBar();
  _renderPlayerBar();
  _renderStage();
  _renderScoreCard();
}

/* ── 材料拉取 ─────────────────────────────────────────────────────────────── */

async function _loadMaterials() {
  const levelParam = _q.level === "all" ? "" : `?level=${encodeURIComponent(_q.level)}`;
  try {
    const res = await api(`/api/listen/materials${levelParam}`);
    _q.materials = (res && res.items) || [];
  } catch (e) {
    _q.materials = [];
    notify(`材料清单加载失败：${e.message || "未知错误"}`, { kind: "error" });
  }
  _q.materialsLoaded = true;
}

/* ── 对外导出（main.js `import * as ListenLab` + window 命名空间挂载） ─────── */

// 进入备考域听力微训：幂等初始化（样式/材料缓存/会话现场恢复）
export async function enterListenLab() {
  _ensureStyle();
  if (!el("listen-stage")) return;
  if (!_q.materialsLoaded) await _loadMaterials();
  _renderAll();
}

// 离开备考域：停止播放队列（幂等）
export function stopListenLab() {
  _stop();
}

// 等级过滤：重置材料缓存并回到材料选择态
export async function setListenLevel(level) {
  _q.level = level;
  _q.materialsLoaded = false;
  _stop();
  _q.material = null;
  _q.finished = false;
  await _loadMaterials();
  _renderAll();
}

// 选择材料：拉详情切句，开始新会话
export async function selectListenMaterial(sourceType, sourceId) {
  if (!sourceType || sourceId == null) return;
  try {
    const data = await api(`/api/listen/materials/${encodeURIComponent(sourceType)}/${Number(sourceId)}`);
    if (!data || !Array.isArray(data.sentences) || !data.sentences.length) {
      notify("该材料没有可用句子，请换一个", { kind: "error" });
      return;
    }
    _startSession(data);
  } catch (e) {
    notify(`材料不可用：${e.message || "未知错误"}`, { kind: "error" });
  }
}

// 三模式切换：重置本材料会话（新模式 = 新会话）
export function setListenMode(mode) {
  if (mode !== "L" && mode !== "D" && mode !== "C") return;
  if (!_q.material || _q.finished) return;
  _stop();
  _q.mode = mode;
  _q.idx = 0;
  _q.done = _q.sentences.map(() => ({}));
  _q.statCorrect = 0;
  _q.statTotal = 0;
  _q.finished = false;
  _q.startedAt = Date.now();
  _renderAll();
}

export function listenPlayToggle() {
  if (!_q.material || _q.finished) return;
  if (_q.playing) {
    _stop();
    _renderAll();
  } else {
    _playCurrent();
  }
}

export function listenNext() {
  if (!_q.material || _q.finished) return;
  _advanceTo(_q.idx + 1);
}

export function listenPrev() {
  if (!_q.material || _q.finished) return;
  _advanceTo(_q.idx - 1);
}

export function listenReplay() {
  if (!_q.material || _q.finished) return;
  _playCurrent();
}

export function listenJump(i) {
  if (!_q.material || _q.finished) return;
  _seekTo(i);
  _playCurrent();
}

export function listenSetSpeed(rate) {
  _q.speed = rate;
  if (_q.playing) _playCurrent(); // 变速后重播当前句
  _renderAll();
}

export function listenSetFlow(flow) {
  if (flow !== "shadow" && flow !== "continuous") return;
  _q.flow = flow;
  _renderAll();
}

export function listenSkip() {
  if (!_q.material || _q.finished) return;
  const d = _q.done[_q.idx] || {};
  if (!d.answered) _q.done[_q.idx] = { skipped: true }; // 跳过不计成绩
  _advanceTo(_q.idx + 1);
}

// D 模式提交：POST /api/listen/diagnose → 逐字六色反馈，成绩按 correct/total 累加
export async function listenSubmitDictation() {
  const input = el("listen-dict-input");
  const sent = _q.sentences[_q.idx];
  if (!input || !sent || _q.finished) return;
  const actual = input.value.trim();
  if (!actual) {
    notify("请先输入听写内容（或点跳过）", { kind: "info" });
    return;
  }
  // 全非德语字符 → 提示重听，不进 diagnose
  if (!/[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]/.test(actual)) {
    notify("输入中缺少德语字符，请重听后再试", { kind: "info" });
    return;
  }
  const btn = document.querySelector('#listen-stage .listen-btn-dark');
  if (btn) btn.disabled = true;
  try {
    const diag = await api("/api/listen/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected: sent, actual }),
    });
    _q.done[_q.idx] = { answered: true, diag };
    _q.statTotal += Number(diag.total) || 0;
    _q.statCorrect += Number(diag.correct) || 0;
    _renderAll();
  } catch (e) {
    notify(`听写诊断失败：${e.message || "未知错误"}`, { kind: "error" });
  } finally {
    if (btn) btn.disabled = false;
  }
}

// C 模式提交：本地挖空校验（大小写/变音容差），成绩按句对错累加
export function listenSubmitCloze() {
  const input = el("listen-cloze-input");
  const sent = _q.sentences[_q.idx];
  if (!input || !sent || _q.finished) return;
  const item = _makeCloze(sent);
  if (!item) return; // 渲染层已处理无可挖词句
  const actual = input.value.trim();
  if (!actual) {
    notify("请先输入填空单词（或点跳过）", { kind: "info" });
    return;
  }
  const ok = _clozeMatch(actual, item.answer);
  _q.done[_q.idx] = { answered: true, ok, item, actual };
  _q.statTotal += 1;
  if (ok) _q.statCorrect += 1;
  _renderAll();
}

// 重开本材料会话
export function listenRestart() {
  if (!_q.material || !_q.sentences.length) return;
  _startSession({
    source_type: _q.material.source_type,
    source_id: _q.material.source_id,
    title: _q.material.title,
    level: _q.material.level,
    sentences: _q.sentences,
  });
}

// 退出会话：回到材料选择态
export function listenExit() {
  _stop();
  _q.material = null;
  _q.finished = false;
  _renderAll();
}
