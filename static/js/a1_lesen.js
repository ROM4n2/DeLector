/* DeLector - Goethe-Zertifikat A1 Lesen (Reading) Studio */
"use strict";

import { api, esc, jsAttr } from "./core.js";

export let lesenSets = [];
export let currentSetId = 1;
export let currentSetData = null;
export let userAnswers = {};
let _examStartTime = 0;
let _examTimer = null;
let _timerRemainingSec = 25 * 60; // 25 minutes standard

export async function initA1Lesen() {
  const container = document.getElementById("a1-lesen-container");
  if (!container) return;

  try {
    const res = await api("/api/a1/lesen/sets");
    lesenSets = res?.sets || [];
    renderLesenHeader();
    if (lesenSets.length > 0) {
      await selectLesenSet(lesenSets[0].set_id);
    }
  } catch (e) {
    console.error("Failed to load A1 Lesen sets", e);
    container.innerHTML = `<div class="p-4 text-pencil">⚠️ 无法加载阅读题库: ${esc(e.message)}</div>`;
  }
}

export function renderLesenHeader() {
  const container = document.getElementById("a1-lesen-container");
  if (!container) return;

  let setsHtml = lesenSets
    .map(
      (s) => `
    <button class="folio-anchor-pill ${s.set_id === currentSetId ? "active" : ""}"
            onclick="A1Lesen.selectLesenSet(${s.set_id})">
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
          <span>📖 Goethe-Zertifikat A1 · 生活阅读实战工坊 (Lesen · 15题 / 25分 / 限时25分钟)</span>
        </div>
        <div class="a1-hoeren-status-badge" id="lesen-timer-badge">
          ⏱️ 剩余 25:00
        </div>
      </div>
      <div class="a1-hoeren-set-pills">
        ${setsHtml}
      </div>
    </div>
    <div id="a1-lesen-exam-stage" class="a1-hoeren-exam-stage">
      <!-- 试卷与答题区 -->
    </div>
  `;
}

export function stopLesenExam() {
  if (_examTimer) {
    clearInterval(_examTimer);
    _examTimer = null;
  }
}

export async function selectLesenSet(setId) {
  stopLesenExam();
  currentSetId = setId;
  userAnswers = {};
  _examStartTime = Date.now();
  _timerRemainingSec = 25 * 60;

  renderLesenHeader();
  startLesenTimer();

  const stage = document.getElementById("a1-lesen-exam-stage");
  if (!stage) return;

  stage.innerHTML = '<div class="p-6 text-pencil">正在载入阅读试卷...</div>';

  try {
    const data = await api(`/api/a1/lesen/set/${setId}`);
    if (setId !== currentSetId) return;
    currentSetData = data;
    renderLesenQuestions();
  } catch (e) {
    if (setId !== currentSetId) return;
    console.error("Failed to load lesen set", e);
    stage.innerHTML = `<div class="p-6 text-red">⚠️ 试卷载入失败: ${esc(e.message)}</div>`;
  }
}

function startLesenTimer() {
  if (_examTimer) clearInterval(_examTimer);   // 防双击/重开试卷叠计时器
  const badge = document.getElementById("lesen-timer-badge");
  _examTimer = setInterval(() => {
    _timerRemainingSec--;
    if (_timerRemainingSec <= 0) {
      clearInterval(_examTimer);
      _examTimer = null;
      if (badge) badge.innerText = "⏱️ 时间到！请交卷";
    } else {
      const min = Math.floor(_timerRemainingSec / 60);
      const sec = _timerRemainingSec % 60;
      if (badge) {
        badge.innerText = `⏱️ 剩余 ${min.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
      }
    }
  }, 1000);
}

function getAllQuestions() {
  if (!currentSetData || !currentSetData.parts) return [];
  const p1 = currentSetData.parts.teil_1 || [];
  const p2 = currentSetData.parts.teil_2 || [];
  const p3 = currentSetData.parts.teil_3 || [];
  return [...p1, ...p2, ...p3];
}

export function renderLesenQuestions() {
  const stage = document.getElementById("a1-lesen-exam-stage");
  if (!stage || !currentSetData) return;

  const allQ = getAllQuestions();
  if (allQ.length === 0) {
    stage.innerHTML = '<div class="p-6 text-pencil">该试卷暂无题目。</div>';
    return;
  }

  stage.innerHTML = `
    <div class="a1-hoeren-layout">
      <!-- 左侧：题目区 -->
      <div class="a1-hoeren-main-panel">
        <div class="a1-hoeren-toolbar">
          <div class="a1-hoeren-timer-block">
            <span class="a1-hoeren-timer-label">阅读模式:</span>
            <span class="a1-hoeren-phase-tag">生活实用阅读</span>
            <span style="font-size:0.8rem; color:var(--pencil);">划词可即时查看语法释义</span>
          </div>
          <div class="a1-hoeren-action-group">
            <button id="btn-lesen-submit" class="btn btn-accent" onclick="A1Lesen.submitLesenExam()">
              ✓ 提交阅读答卷 (评分)
            </button>
          </div>
        </div>

        <div id="a1-lesen-cards-container" class="a1-hoeren-cards-container">
          ${renderAllLesenCards(currentSetData.parts)}
        </div>
      </div>

      <!-- 右侧：答题卡 -->
      <div class="a1-hoeren-sidebar">
        <div class="a1-hoeren-side-card">
          <div class="a1-side-header">
            <span>📋 阅读答题卡</span>
            <span id="lesen-answered-ratio">0/15</span>
          </div>
          <div class="a1-hoeren-grid-matrix">
            ${allQ
              .map(
                (q, idx) => `
              <button id="lesen-nav-btn-${q.id}" class="hoeren-matrix-cell"
                      onclick="A1Lesen.jumpToQuestion(${jsAttr(q.id)})">
                ${idx + 1}
              </button>
            `,
              )
              .join("")}
          </div>
          <div class="a1-side-rules">
            <div class="a1-rule-item"><strong>Teil 1 (1-5):</strong> 生活便条/邮件 · 判断 R/F</div>
            <div class="a1-rule-item"><strong>Teil 2 (6-10):</strong> 需求与网页广告 · 二选一 A/B</div>
            <div class="a1-rule-item"><strong>Teil 3 (11-15):</strong> 公共标牌告示 · 判断 R/F</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderAllLesenCards(parts) {
  let html = "";
  let qNum = 1;

  // ── Teil 1 ──────────────────────────────────────────────────────────────
  const p1 = parts.teil_1 || [];
  if (p1.length > 0) {
    html += `
      <div class="a1-hoeren-teil-divider">
        <span class="a1-hoeren-teil-badge">TEIL 1</span>
        <span class="a1-hoeren-teil-text">阅读简短便条与邮件 · 判断下列陈述是正确 (Richtig) 还是错误 (Falsch)</span>
      </div>
    `;

    p1.forEach((q) => {
      const isR = userAnswers[q.id] === "R";
      const isF = userAnswers[q.id] === "F";
      html += `
        <div class="a1-hoeren-q-card" id="q-card-${q.id}">
          <div class="a1-q-header">
            <span class="a1-q-num">Frage ${qNum++}</span>
            <span class="a1-q-repeat">✉️ 便条/邮件阅读</span>
          </div>
          <div class="a1-lesen-passage-box">
            ${esc(q.reading_text_de)}
          </div>
          <div class="a1-lesen-statement">
            <strong>陈述:</strong> ${esc(q.statement_de)} <span class="text-pencil">(${esc(q.statement_zh)})</span>
          </div>
          <div class="a1-q-options">
            <label class="a1-option-label ${isR ? "selected" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("R")})">
              <input type="radio" name="opt_${q.id}" value="R" ${isR ? "checked" : ""} />
              <span class="a1-opt-key">R</span>
              <span class="a1-opt-text">Richtig (正确)</span>
            </label>
            <label class="a1-option-label ${isF ? "selected" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("F")})">
              <input type="radio" name="opt_${q.id}" value="F" ${isF ? "checked" : ""} />
              <span class="a1-opt-key">F</span>
              <span class="a1-opt-text">Falsch (错误)</span>
            </label>
          </div>
          <div id="q-analysis-${q.id}" class="a1-q-analysis hidden"></div>
        </div>
      `;
    });
  }

  // ── Teil 2 ──────────────────────────────────────────────────────────────
  const p2 = parts.teil_2 || [];
  if (p2.length > 0) {
    html += `
      <div class="a1-hoeren-teil-divider">
        <span class="a1-hoeren-teil-badge">TEIL 2</span>
        <span class="a1-hoeren-teil-text">根据用户具体生活需求 · 从两个德语网页广告中挑选合适的一个 (A 或 B)</span>
      </div>
    `;

    p2.forEach((q) => {
      const isA = userAnswers[q.id] === "A";
      const isB = userAnswers[q.id] === "B";
      html += `
        <div class="a1-hoeren-q-card" id="q-card-${q.id}">
          <div class="a1-q-header">
            <span class="a1-q-num">Frage ${qNum++}</span>
            <span class="a1-q-repeat">🌐 网页对比选择</span>
          </div>
          <div class="a1-lesen-need-box">
            <strong>🎯 用户需求:</strong> ${esc(q.user_need_zh)}
          </div>
          <div class="a1-lesen-dual-web">
            <div class="a1-web-card ${isA ? "selected-web" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("A")})">
              <div class="web-card-header">
                <span class="web-tag">网站 A</span>
                <span class="web-url">${esc(q.ad_a.title)}</span>
              </div>
              <div class="web-card-body">${esc(q.ad_a.text_de)}</div>
              <button class="btn btn-sm ${isA ? "btn-accent" : "btn-ghost"} web-select-btn">选择网站 A</button>
            </div>
            <div class="a1-web-card ${isB ? "selected-web" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("B")})">
              <div class="web-card-header">
                <span class="web-tag">网站 B</span>
                <span class="web-url">${esc(q.ad_b.title)}</span>
              </div>
              <div class="web-card-body">${esc(q.ad_b.text_de)}</div>
              <button class="btn btn-sm ${isB ? "btn-accent" : "btn-ghost"} web-select-btn">选择网站 B</button>
            </div>
          </div>
          <div id="q-analysis-${q.id}" class="a1-q-analysis hidden"></div>
        </div>
      `;
    });
  }

  // ── Teil 3 ──────────────────────────────────────────────────────────────
  const p3 = parts.teil_3 || [];
  if (p3.length > 0) {
    html += `
      <div class="a1-hoeren-teil-divider">
        <span class="a1-hoeren-teil-badge">TEIL 3</span>
        <span class="a1-hoeren-teil-text">阅读公共场所的真实标牌与告示 · 判断下列陈述是正确还是错误</span>
      </div>
    `;

    p3.forEach((q) => {
      const isR = userAnswers[q.id] === "R";
      const isF = userAnswers[q.id] === "F";
      html += `
        <div class="a1-hoeren-q-card" id="q-card-${q.id}">
          <div class="a1-q-header">
            <span class="a1-q-num">Frage ${qNum++}</span>
            <span class="a1-q-repeat">🪧 公共标牌告示</span>
          </div>
          <div class="a1-lesen-sign-box">
            <span class="sign-pin">📌 SCHILD / AUSHANG</span>
            <div class="sign-content">${esc(q.sign_text_de)}</div>
          </div>
          <div class="a1-lesen-statement">
            <strong>陈述:</strong> ${esc(q.statement_de)} <span class="text-pencil">(${esc(q.statement_zh)})</span>
          </div>
          <div class="a1-q-options">
            <label class="a1-option-label ${isR ? "selected" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("R")})">
              <input type="radio" name="opt_${q.id}" value="R" ${isR ? "checked" : ""} />
              <span class="a1-opt-key">R</span>
              <span class="a1-opt-text">Richtig (正确)</span>
            </label>
            <label class="a1-option-label ${isF ? "selected" : ""}" onclick="A1Lesen.selectOption(${jsAttr(q.id)}, ${jsAttr("F")})">
              <input type="radio" name="opt_${q.id}" value="F" ${isF ? "checked" : ""} />
              <span class="a1-opt-key">F</span>
              <span class="a1-opt-text">Falsch (错误)</span>
            </label>
          </div>
          <div id="q-analysis-${q.id}" class="a1-q-analysis hidden"></div>
        </div>
      `;
    });
  }

  return html;
}

export function selectOption(qid, key) {
  userAnswers[qid] = key;

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

    // 网页卡片高亮
    card.querySelectorAll(".a1-web-card").forEach((wCard, idx) => {
      const targetKey = idx === 0 ? "A" : "B";
      if (targetKey === key) {
        wCard.classList.add("selected-web");
        const btn = wCard.querySelector(".web-select-btn");
        if (btn) {
          btn.className = "btn btn-sm btn-accent web-select-btn";
        }
      } else {
        wCard.classList.remove("selected-web");
        const btn = wCard.querySelector(".web-select-btn");
        if (btn) {
          btn.className = "btn btn-sm btn-ghost web-select-btn";
        }
      }
    });
  }

  const matrixBtn = document.getElementById(`lesen-nav-btn-${qid}`);
  if (matrixBtn) {
    matrixBtn.classList.add("answered");
  }

  const allQ = getAllQuestions();
  const answeredCount = Object.keys(userAnswers).length;
  const ratioSpan = document.getElementById("lesen-answered-ratio");
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

export async function submitLesenExam() {
  const allQ = getAllQuestions();
  const answeredCount = Object.keys(userAnswers).length;

  if (answeredCount < allQ.length) {
    if (
      !confirm(
        `还有 ${allQ.length - answeredCount} 道题未作答，确定现在交卷评分吗？`,
      )
    ) {
      return;
    }
  }

  if (_examTimer) {
    clearInterval(_examTimer);
    _examTimer = null;
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

    const graded = await api("/api/a1/lesen/grade", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    renderLesenGradedResults(graded);
  } catch (e) {
    alert("提交阅读判分失败: " + e.message);
  }
}

function renderLesenGradedResults(graded) {
  const scoreOfficial = graded.score_official;
  const rating = graded.rating;
  let ratingClass = "rating-fail";
  if (scoreOfficial >= 20.0) ratingClass = "rating-excellent";
  else if (scoreOfficial >= 17.5) ratingClass = "rating-good";
  else if (scoreOfficial >= 12.5) ratingClass = "rating-pass";

  window.scrollTo({ top: 0, behavior: "smooth" });

  (graded.details || []).forEach((d) => {
    const card = document.getElementById(`q-card-${d.id}`);
    const analysisBox = document.getElementById(`q-analysis-${d.id}`);
    const navBtn = document.getElementById(`lesen-nav-btn-${d.id}`);

    if (navBtn) {
      navBtn.classList.remove("answered");
      navBtn.classList.add(d.is_correct ? "correct" : "wrong");
    }

    if (card) {
      card.classList.add(d.is_correct ? "card-correct" : "card-wrong");
    }

    if (analysisBox) {
      analysisBox.classList.remove("hidden");
      analysisBox.innerHTML = `
        <div class="analysis-status-line">
          <span class="${d.is_correct ? "text-green" : "text-red"}">
            ${d.is_correct ? "✅ 正确" : `❌ 错误 (您的选择: ${esc(d.user_answer || "未选")})`}
          </span>
          <span class="correct-ans-tag">官方正确答案: <strong>${esc(d.correct_answer)}</strong></span>
        </div>
        <div class="analysis-explanation">
          <strong>💡 考点线索剖析:</strong> ${esc(d.explanation_zh)}
        </div>
      `;
    }
  });

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
          <button class="btn btn-dark btn-sm" onclick="A1Lesen.selectLesenSet(${currentSetId})">
            🔄 重测本卷
          </button>
        </div>
      </div>
    `,
    );
  }
}

window.A1Lesen = {
  initA1Lesen,
  selectLesenSet,
  renderLesenQuestions,
  selectOption,
  jumpToQuestion,
  stopLesenExam,
  submitLesenExam,
};
