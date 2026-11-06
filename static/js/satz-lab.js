"use strict";

// 首屏「句子解剖台」：页面不内嵌任何分析结果，每次都调用本地引擎实时返回。
// 三条示例句都用以下命令验证过能产出 UI 所需的拓扑五场域 + clause_tree：
//   .venv\Scripts\python.exe -c "from delector.nlp_engine.syntax_tree import analyze_syntax_tree as a; import json; print(json.dumps(a('Die Lehrerin gibt dem Schüler das Buch.'), ensure_ascii=False))"
// 若引擎行为变化，先重跑该命令，再决定是否调整示例句；不得手写引擎产生不出来的展示数据。

import { api, esc } from "./core.js";

const SAMPLES = [
  { label: "双宾语 · 格位", text: "Die Lehrerin gibt dem Schüler das Buch." },
  { label: "被动语态 · 框型", text: "Das Buch wurde von dem Lehrer empfohlen." },
  { label: "原因从句 · 树", text: "Weil es heute regnet, bleiben wir zu Hause." },
];

const FIELDS = [
  { key: "vorfeld", label: "VF 前场", cls: "vf" },
  { key: "linke_klammer", label: "LK 左框", cls: "lk" },
  { key: "mittelfeld", label: "MF 中场", cls: "mf" },
  { key: "rechte_klammer", label: "RK 右框", cls: "rk" },
  { key: "nachfeld", label: "NF 后场", cls: "nf" },
];

const CASE_ZH = { Nom: "主格", Akk: "宾格", Dat: "与格", Gen: "属格" };
const CASE_POS = new Set(["NOUN", "PRON", "PROPN"]);

const labState = { active: 0, busy: false };
const cache = new Map();

export function initSatzLab() {
  const samplesEl = document.getElementById("satz-lab-samples");
  const outputEl = document.getElementById("satz-lab-output");
  if (!samplesEl || !outputEl) return;

  samplesEl.innerHTML = SAMPLES.map(
    (s, i) =>
      `<button type="button" class="satz-lab-chip${i === labState.active ? " is-active" : ""}" data-sample="${i}" aria-pressed="${i === labState.active}">${esc(s.label)}</button>`,
  ).join("");

  samplesEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-sample]");
    if (btn) runSatzLab(Number(btn.dataset.sample));
  });
  outputEl.addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) runSatzLab(labState.active);
  });

  runSatzLab(0);
}

export async function runSatzLab(index = labState.active) {
  const outputEl = document.getElementById("satz-lab-output");
  if (!outputEl || labState.busy) return;

  const safeIndex = Number.isInteger(index) && SAMPLES[index] ? index : 0;
  labState.active = safeIndex;
  syncChips();

  if (cache.has(safeIndex)) {
    outputEl.innerHTML = renderAnalysis(cache.get(safeIndex));
    bindTreeHighlight(outputEl);
    return;
  }

  const sample = SAMPLES[safeIndex];
  labState.busy = true;
  outputEl.innerHTML = `<div class="satz-lab-loading">本地引擎解析中…<br><span class="satz-lab-loading-sentence">${esc(sample.text)}</span></div>`;
  try {
    const data = await api("/api/syntax/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: sample.text }),
    });
    cache.set(safeIndex, data);
    outputEl.innerHTML = renderAnalysis(data);
    bindTreeHighlight(outputEl);
  } catch (err) {
    outputEl.innerHTML = `<div class="satz-lab-error">本地引擎暂不可用：${esc(err.message || String(err))} <button type="button" class="satz-lab-retry" data-retry>重试</button></div>`;
  } finally {
    labState.busy = false;
  }
}

function syncChips() {
  document.querySelectorAll("#satz-lab-samples [data-sample]").forEach((btn) => {
    const on = Number(btn.dataset.sample) === labState.active;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
}

function renderAnalysis(data) {
  const sent = data && Array.isArray(data.sentences) ? data.sentences[0] : null;
  if (!sent || !sent.topology) {
    return `<div class="satz-lab-error">引擎没有返回可展示的句法结果。</div>`;
  }

  const tokens = collectTokens(sent.topology);
  const meta = [
    sent.topology.sentence_type || "",
    sent.topology.bracket_structure || "",
    "本地 spaCy · 实时",
  ].filter(Boolean);
  const hasCase = tokens.some((t) => caseLabel(t));

  return `
    <div class="satz-lab-meta">${meta.map((m) => `<span class="satz-lab-meta-tag">${esc(m)}</span>`).join("")}</div>
    <div class="satz-lab-sentence">${renderSentence(tokens)}</div>
    <div class="felder-spectrum-bar satz-fields">${renderFields(sent.topology)}</div>
    ${hasCase ? `<div class="satz-case-note">名词/代词上标 = 格位（Nom 主格 · Akk 宾格 · Dat 与格 · Gen 属格）</div>` : ""}
    <div class="satz-tree" aria-label="从句树">${renderTree(sent.clause_tree)}</div>
  `;
}

function collectTokens(topology) {
  const seen = new Set();
  const out = [];
  for (const field of FIELDS) {
    for (const token of topology[field.key] || []) {
      if (!token || typeof token !== "object" || seen.has(token.id)) continue;
      seen.add(token.id);
      out.push(token);
    }
  }
  return out.sort((a, b) => Number(a.id) - Number(b.id));
}

function caseLabel(token) {
  if (!token || !token.case || !CASE_POS.has(token.pos)) return "";
  return CASE_ZH[token.case] || "";
}

function renderSentence(tokens) {
  let html = "";
  tokens.forEach((token, i) => {
    const prev = tokens[i - 1];
    let space = "";
    if (i > 0) {
      const prevOpens = prev && /^[„(«]$/.test(prev.text || "");
      const opensHere = token.is_punct && /^[„(«]$/.test(token.text || "");
      if ((!token.is_punct && !prevOpens) || opensHere) space = " ";
    }
    const label = caseLabel(token);
    const attrs = [
      `class="satz-tok${label ? " has-case" : ""}"`,
      `data-tok-id="${Number(token.id)}"`,
      label ? `data-case="${label}"` : "",
      label ? `title="${esc(token.text)} · ${label}"` : "",
    ]
      .filter(Boolean)
      .join(" ");
    html += `${space}<span ${attrs}>${esc(token.text)}</span>`;
  });
  return html;
}

function renderFields(topology) {
  return FIELDS.map((field) => {
    const tokens = topology[field.key] || [];
    const text = tokens.length
      ? tokens.map((t) => (t && typeof t === "object" ? t.text : t)).join(" ")
      : "—";
    return `<div class="feld-pill feld-${field.cls}${tokens.length ? "" : " is-empty"}"><span class="feld-tag">${field.label}</span><span class="feld-val">${esc(text)}</span></div>`;
  }).join("");
}

function renderTree(node, depth = 0) {
  if (!node) return "";
  const tags = [];
  if (node.connector) {
    tags.push(`<span class="clause-pill-tag tag-conn">连词 ${esc(node.connector)}</span>`);
  }
  if (node.finite_verb) {
    tags.push(`<span class="clause-pill-tag tag-verb">变位 ${esc(node.finite_verb)}</span>`);
  }
  const ids = JSON.stringify(Array.isArray(node.token_ids) ? node.token_ids : []);
  const children = (node.children || []).map((child) => renderTree(child, depth + 1)).join("");
  return `<div class="clause-tree-node depth-${Math.min(depth, 3)}">
    <div class="clause-node-box" data-ids='${ids}' role="button" tabindex="0" title="点击高亮该从句覆盖的词">
      <div class="clause-node-top">
        <span class="clause-type-name">${esc(node.label || node.type || "Satz")}</span>
        <span class="clause-node-tags">${tags.join("")}</span>
      </div>
      <div class="clause-formula"><code>${esc(node.formula || "")}</code></div>
      <div class="clause-quote-text">„${esc(node.text || "")}“</div>
    </div>
    ${children}
  </div>`;
}

function bindTreeHighlight(root) {
  root.querySelectorAll(".clause-node-box").forEach((box) => {
    const activate = () => {
      let ids = [];
      try {
        ids = JSON.parse(box.dataset.ids || "[]");
      } catch {
        ids = [];
      }
      highlightTokens(ids);
    };
    box.addEventListener("click", activate);
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
  });
}

function highlightTokens(ids) {
  const set = new Set((ids || []).map(Number));
  document.querySelectorAll("#satz-lab-output .satz-tok").forEach((el) => {
    el.classList.toggle("clause-highlight", set.has(Number(el.dataset.tokId)));
  });
}
