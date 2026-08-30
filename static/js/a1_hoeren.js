/* DeLector - Goethe-Zertifikat A1 Hörverstehen (Listening) Studio */
"use strict";

import { api, esc } from "./core.js";
import { playGermanAudio } from "./player.js";

export let hoerenSets = [];
export let currentSetId = 1;
export let currentSetData = null;
export let userAnswers = {};
export let currentQuestionIndex = 0;
export let examPhase = "idle"; // 'idle' | 'reading' | 'beep' | 'playing' | 'pause' | 'answering' | 'graded'
export let countdownSec = 0;
let _examTimer = null;
let _examStartTime = 0;
let _lastGradedResult = null;
let _audioElement = null;

export async function initA1Hoeren() {
  const container = document.getElementById("a1-hoeren-container");
  if (!container) return;

  try {
    const res = await api("/api/a1/hoeren/sets");
    hoerenSets = res?.sets || [];
    renderHoerenHeader();
    if (hoerenSets.length > 0) {
      await selectHoerenSet(hoerenSets[0].set_id);
    }
  } catch (e) {
    console.error("Failed to load A1 Hoeren sets", e);
    container.innerHTML = `<div class="p-4 text-pencil">⚠️ 无法加载听力题库: ${esc(e.message)}</div>`;
  }
}

export function renderHoerenHeader() {
  const container = document.getElementById("a1-hoeren-container");
  if (!container) return;

  let setsHtml = hoerenSets
    .map(
      (s) => `
    <button class="folio-anchor-pill ${s.set_id === currentSetId ? "active" : ""}"
            onclick="A1Hoeren.selectHoerenSet(${s.set_id})">
      ${esc(s.title_zh || s.title_de)}
    </button>
  `,
    )
    .join("");

  container.innerHTML = `
    <div class="a1-hoeren-header">
      <div class="a1-hoeren-title-bar">
        <div class="a1-hoeren-title">
          <span class="pulse"></span>
          <span>🎧 Goethe-Zertifikat A1 · 听力考场工坊 (Hörverstehen · 15题 / 25分)</span>
        </div>
        <div class="a1-hoeren-status-badge" id="hoeren-status-badge">
          考场准备就绪
        </div>
      </div>
      <div class="a1-hoeren-set-pills">
        ${setsHtml}
      </div>
    </div>
    <div id="a1-hoeren-exam-stage" class="a1-hoeren-exam-stage">
      <!-- 试卷与答题区 -->
    </div>
  `;
}

export async function selectHoerenSet(setId) {
  currentSetId = setId;
  examPhase = "idle";
  userAnswers = {};
  currentQuestionIndex = 0;
  _lastGradedResult = null;
  if (_examTimer) {
    clearInterval(_examTimer);
    _examTimer = null;
  }

  renderHoerenHeader();

  const stage = document.getElementById("a1-hoeren-exam-stage");
  if (!stage) return;

  stage.innerHTML = '<div class="p-6 text-pencil">正在载入试卷内容...</div>';

  try {
    currentSetData = await api(`/api/a1/hoeren/set/${setId}`);
    renderHoerenQuestions();
  } catch (e) {
    console.error("Failed to load set", e);
    stage.innerHTML = `<div class="p-6 text-red">⚠️ 试卷载入失败: ${esc(e.message)}</div>`;
  }
}

function getAllQuestions() {
  if (!currentSetData || !currentSetData.parts) return [];
  const p1 = currentSetData.parts.teil_1 || [];
  const p2 = currentSetData.parts.teil_2 || [];
  const p3 = currentSetData.parts.teil_3 || [];
  return [...p1, ...p2, ...p3];
}

export function renderHoerenQuestions() {
  const stage = document.getElementById("a1-hoeren-exam-stage");
  if (!stage || !currentSetData) return;

  const allQ = getAllQuestions();
  if (allQ.length === 0) {
    stage.innerHTML = '<div class="p-6 text-pencil">该试卷暂无题目。</div>';
    return;
  }

  // 渲染总览大盘与考场控制栏
  stage.innerHTML = `
    <div class="a1-hoeren-layout">
      <!-- 左侧：题目答题卡与播放控制 -->
      <div class="a1-hoeren-main-panel">
        <div class="a1-hoeren-toolbar">
          <div class="a1-hoeren-timer-block">
            <span class="a1-hoeren-timer-label">考试阶段:</span>
            <span id="hoeren-phase-label" class="a1-hoeren-phase-tag">待开始</span>
            <span id="hoeren-countdown" class="a1-hoeren-countdown">--:--</span>
          </div>
          <div class="a1-hoeren-action-group">
            <button id="btn-hoeren-start" class="btn btn-dark" onclick="A1Hoeren.startHoerenExam()">
              ▶ 开始模拟考 (全真流程)
            </button>
            <button id="btn-hoeren-submit" class="btn btn-accent" onclick="A1Hoeren.submitHoerenExam()">
              ✓ 提交交卷 (评分)
            </button>
          </div>
        </div>

        <div id="a1-hoeren-cards-container" class="a1-hoeren-cards-container">
          ${renderAllQuestionCards(allQ)}
        </div>
      </div>

      <!-- 右侧：答题卡与考情导航 -->
      <div class="a1-hoeren-sidebar">
        <div class="a1-hoeren-side-card">
          <div class="a1-side-header">
            <span>📋 答题卡 (Antwortbogen)</span>
            <span id="hoeren-answered-ratio">0/15</span>
          </div>
          <div class="a1-hoeren-grid-matrix">
            ${allQ
              .map(
                (q, idx) => `
              <button id="hoeren-nav-btn-${q.id}" class="hoeren-matrix-cell"
                      onclick="A1Hoeren.jumpToQuestion('${q.id}')">
                ${idx + 1}
              </button>
            `,
              )
              .join("")}
          </div>
          <div class="a1-side-rules">
            <div class="a1-rule-item"><strong>Teil 1 (1-6):</strong> 短对话 · 播放 2 遍</div>
            <div class="a1-rule-item"><strong>Teil 2 (7-10):</strong> 广播 · 播放 1 遍 (R/F)</div>
            <div class="a1-rule-item"><strong>Teil 3 (11-15):</strong> 留言 · 播放 2 遍</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderAllQuestionCards(allQ) {
  let html = "";
  let currentTeil = 0;

  allQ.forEach((q, idx) => {
    if (q.teil !== currentTeil) {
      currentTeil = q.teil;
      let teilDesc = "";
      if (currentTeil === 1)
        teilDesc = "Teil 1: 日常短对话（每段播放 2 遍 · 三选一 A/B/C）";
      else if (currentTeil === 2)
        teilDesc = "Teil 2: 公共广播（每段仅播放 1 遍 · 判断正误 R/F）";
      else if (currentTeil === 3)
        teilDesc = "Teil 3: 电话留言与答录机（每段播放 2 遍 · 三选一 A/B/C）";

      html += `<div class="a1-hoeren-teil-divider">
        <span class="a1-hoeren-teil-badge">TEIL ${currentTeil}</span>
        <span class="a1-hoeren-teil-text">${teilDesc}</span>
      </div>`;
    }

    const isAnswered = !!userAnswers[q.id];
    const optionsHtml = (q.options || [])
      .map((opt) => {
        const isSelected = userAnswers[q.id] === opt.key;
        return `
        <label class="a1-option-label ${isSelected ? "selected" : ""}"
               onclick="A1Hoeren.selectOption('${q.id}', '${opt.key}')">
          <input type="radio" name="opt_${q.id}" value="${opt.key}" ${isSelected ? "checked" : ""} />
          <span class="a1-opt-key">${opt.key}</span>
          <span class="a1-opt-text">${esc(opt.text)}</span>
        </label>
      `;
      })
      .join("");

    html += `
      <div class="a1-hoeren-q-card" id="q-card-${q.id}" data-qid="${q.id}">
        <div class="a1-q-header">
          <span class="a1-q-num">Frage ${idx + 1}</span>
          <span class="a1-q-repeat">🔁 播放 ${q.repeat_count} 遍</span>
          <button class="btn btn-ghost btn-xs audio-play-btn" onclick="A1Hoeren.playSingleAudio('${q.id}')" title="单独朗读本题听力">
            🔊 听力试听
          </button>
        </div>
        <div class="a1-q-prompt-zh">${esc(q.prompt_zh)}</div>
        <div class="a1-q-de">${esc(q.question_de)}</div>
        <div class="a1-q-options">
          ${optionsHtml}
        </div>
        <div id="q-analysis-${q.id}" class="a1-q-analysis hidden"></div>
      </div>
    `;
  });

  return html;
}

export function selectOption(qid, key) {
  userAnswers[qid] = key;

  // 更新卡片 UI
  const card = document.getElementById(`q-card-${qid}`);
  if (card) {
    card.querySelectorAll(".a1-option-label").forEach((lbl) => {
      const inp = lbl.querySelector("input");
      if (inp && inp.value === key) {
        lbl.classList.add("selected");
        inp.checked = true;
      } else {
        lbl.classList.remove("selected");
      }
    });
  }

  // 更新答题卡矩阵
  const matrixBtn = document.getElementById(`hoeren-nav-btn-${qid}`);
  if (matrixBtn) {
    matrixBtn.classList.add("answered");
  }

  // 更新已答比例
  const allQ = getAllQuestions();
  const answeredCount = Object.keys(userAnswers).length;
  const ratioSpan = document.getElementById("hoeren-answered-ratio");
  if (ratioSpan) {
    ratioSpan.innerText = `${answeredCount}/${allQ.length}`;
  }
}

export function jumpToQuestion(qid) {
  const card = document.getElementById(`q-card-${qid}`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("card-highlight");
    setTimeout(() => card.classList.remove("card-highlight"), 1200);
  }
}

export function playSingleAudio(qid) {
  const allQ = getAllQuestions();
  const q = allQ.find((item) => item.id === qid);
  if (!q || !q.audio_text_de) return;
  playGermanAudio(q.audio_text_de);
}

// ── Exam Simulation Engine ──────────────────────────────────────────────────

export async function startHoerenExam() {
  if (examPhase !== "idle" && examPhase !== "graded") {
    if (!confirm("考试正在进行中，是否重新开始？")) return;
  }

  examPhase = "reading";
  currentQuestionIndex = 0;
  _examStartTime = Date.now();

  const startBtn = document.getElementById("btn-hoeren-start");
  if (startBtn) {
    startBtn.innerText = "⏸ 考场进行中...";
    startBtn.disabled = true;
  }

  runExamQuestionStep(0);
}

async function runExamQuestionStep(qIndex) {
  const allQ = getAllQuestions();
  if (qIndex >= allQ.length) {
    finishExamCountdown();
    return;
  }

  currentQuestionIndex = qIndex;
  const q = allQ[qIndex];

  jumpToQuestion(q.id);

  // 1. 读题时间 (5s)
  setPhaseInfo("读题时间 (Lesen)", 5);
  await waitSeconds(5);

  // 2. 第一遍朗读
  setPhaseInfo(`第 1 遍播放 (${q.repeat_count === 1 ? "仅1遍" : "共2遍"})`, 0);
  await playAudioPromise(q.audio_text_de);

  // 3. 若为重复 2 遍题型，停顿 4 秒后放第二遍
  if (q.repeat_count === 2) {
    setPhaseInfo("思考停顿...", 4);
    await waitSeconds(4);

    setPhaseInfo("第 2 遍播放", 0);
    await playAudioPromise(q.audio_text_de);
  }

  // 4. 答题停顿时间 (8s)
  setPhaseInfo("请作答 (Antworten)", 8);
  await waitSeconds(8);

  // 进入下一题
  runExamQuestionStep(qIndex + 1);
}

function setPhaseInfo(label, sec) {
  const phaseTag = document.getElementById("hoeren-phase-label");
  const countdown = document.getElementById("hoeren-countdown");
  const statusBadge = document.getElementById("hoeren-status-badge");

  if (phaseTag) phaseTag.innerText = label;
  if (statusBadge)
    statusBadge.innerText = `Frage ${currentQuestionIndex + 1}/15 · ${label}`;

  countdownSec = sec;
  if (_examTimer) clearInterval(_examTimer);

  if (sec > 0) {
    if (countdown) countdown.innerText = `${sec}s`;
    _examTimer = setInterval(() => {
      countdownSec--;
      if (countdownSec <= 0) {
        clearInterval(_examTimer);
        _examTimer = null;
        if (countdown) countdown.innerText = "0s";
      } else {
        if (countdown) countdown.innerText = `${countdownSec}s`;
      }
    }, 1000);
  } else {
    if (countdown) countdown.innerText = "🔊 播放中";
  }
}

function waitSeconds(sec) {
  return new Promise((resolve) => setTimeout(resolve, sec * 1000));
}

function playAudioPromise(text) {
  return new Promise((resolve) => {
    try {
      playGermanAudio(text);
      // 根据字数估算朗读时长 (德语大约每秒 3.2 个音节或 2.2 个词)
      const words = text.split(/\s+/).length;
      const estimatedSec = Math.max(3, Math.ceil(words / 2.2) + 2);
      setTimeout(resolve, estimatedSec * 1000);
    } catch (e) {
      console.warn("Audio play failed, fallback next", e);
      setTimeout(resolve, 3000);
    }
  });
}

function finishExamCountdown() {
  examPhase = "finished";
  setPhaseInfo("考试录音播放完毕，请核对答题卡并交卷", 0);
  const startBtn = document.getElementById("btn-hoeren-start");
  if (startBtn) {
    startBtn.innerText = "✓ 录音完毕";
    startBtn.disabled = false;
  }
}

// ── Submission & Grading Review ─────────────────────────────────────────────

export async function submitHoerenExam() {
  const allQ = getAllQuestions();
  const answeredCount = Object.keys(userAnswers).length;

  if (answeredCount < allQ.length) {
    if (
      !confirm(
        `还有 ${allQ.length - answeredCount} 道题未作答，确定现在交卷并评分吗？`,
      )
    ) {
      return;
    }
  }

  const duration = Math.max(
    1,
    Math.round((Date.now() - _examStartTime) / 1000),
  );

  try {
    const payload = {
      set_id: currentSetId,
      duration_seconds: duration,
      answers: userAnswers,
    };

    const graded = await api("/api/a1/hoeren/grade", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    _lastGradedResult = graded;
    renderGradedResults(graded);
  } catch (e) {
    alert("提交判分失败: " + e.message);
  }
}

function renderGradedResults(graded) {
  examPhase = "graded";
  const stage = document.getElementById("a1-hoeren-exam-stage");
  if (!stage) return;

  const scoreOfficial = graded.score_official;
  const rating = graded.rating;
  let ratingClass = "rating-fail";
  if (scoreOfficial >= 20.0) ratingClass = "rating-excellent";
  else if (scoreOfficial >= 17.5) ratingClass = "rating-good";
  else if (scoreOfficial >= 12.5) ratingClass = "rating-pass";

  // 滚动到顶部展示成绩卡
  window.scrollTo({ top: 0, behavior: "smooth" });

  // 在每个问题卡片下方展开原文解析
  (graded.details || []).forEach((d) => {
    const card = document.getElementById(`q-card-${d.id}`);
    const analysisBox = document.getElementById(`q-analysis-${d.id}`);
    const navBtn = document.getElementById(`hoeren-nav-btn-${d.id}`);

    if (navBtn) {
      navBtn.classList.remove("answered");
      navBtn.classList.add(d.is_correct ? "correct" : "wrong");
    }

    if (card) {
      card.classList.add(d.is_correct ? "card-correct" : "card-wrong");
    }

    if (analysisBox) {
      analysisBox.classList.remove("hidden");
      const vocabChips = (d.key_vocabulary || [])
        .map(
          (v) => `
        <span class="a1-vocab-chip" onclick="A1Hoeren.saveVocabChip('${esc(v.word)}', '${esc(v.meaning)}')">
          <strong>${esc(v.word)}</strong> ${v.plural ? `(${esc(v.plural)})` : ""}: ${esc(v.meaning)} ➕
        </span>
      `,
        )
        .join("");

      analysisBox.innerHTML = `
        <div class="analysis-status-line">
          <span class="${d.is_correct ? "text-green" : "text-red"}">
            ${d.is_correct ? "✅ 正确" : `❌ 错误 (您的选择: ${esc(d.user_answer || "未选")})`}
          </span>
          <span class="correct-ans-tag">官方答案: <strong>${esc(d.correct_answer)}</strong></span>
        </div>
        <div class="analysis-transcript-block">
          <div class="transcript-de"><strong>🇩🇪 听力原文:</strong> ${esc(d.transcript_de)}</div>
          <div class="transcript-zh"><strong>🇨🇳 原文对照:</strong> ${esc(d.transcript_zh)}</div>
        </div>
        <div class="analysis-explanation">
          <strong>💡 考点深度解析:</strong> ${esc(d.explanation_zh)}
        </div>
        ${vocabChips ? `<div class="analysis-vocab-row"><strong>📌 考点高频生词:</strong> ${vocabChips}</div>` : ""}
      `;
    }
  });

  // 插入顶部成绩总评 Banner
  const toolbar = document.querySelector(".a1-hoeren-toolbar");
  if (toolbar) {
    toolbar.insertAdjacentHTML(
      "beforebegin",
      `
      <div class="a1-hoeren-score-banner ${ratingClass}">
        <div class="score-banner-left">
          <div class="score-number">${scoreOfficial}<span class="score-total"> / 25.0</span></div>
          <div class="score-meta">答对 ${graded.score_raw} / ${graded.total_questions} 题 · 评定: <strong>${rating}</strong></div>
        </div>
        <div class="score-banner-right">
          <button class="btn btn-dark btn-sm" onclick="A1Hoeren.selectHoerenSet(${currentSetId})">
            🔄 重测本卷
          </button>
        </div>
      </div>
    `,
    );
  }
}

export function saveVocabChip(word, meaning) {
  // 快速添加词汇到背词卡
  api("/api/cards/vocab", {
    method: "POST",
    body: JSON.stringify({
      word: word,
      lemma: word.replace(/^(der|die|das)\s+/i, ""),
      pos: "NOUN",
      definition_zh: meaning,
      sentence_context: `Goethe A1 听力高频考点词: ${word} (${meaning})`,
    }),
  })
    .then(() => {
      alert(`✅ 已成功将「${word}」收录进复习卡盒！`);
    })
    .catch((e) => {
      alert(`收录失败: ${e.message}`);
    });
}

// 挂载全局对象供 HTML onclick 唤起
window.A1Hoeren = {
  initA1Hoeren,
  selectHoerenSet,
  renderHoerenQuestions,
  selectOption,
  jumpToQuestion,
  playSingleAudio,
  startHoerenExam,
  submitHoerenExam,
  saveVocabChip,
};
