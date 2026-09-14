/* DeLector - 长难句精读工坊 (Hard-Sentence Reading Lab)
 *
 * 句子卡片流控制器：跨语料难度榜 → 逐句卡（难度分 + CEFR 标签 + 复杂度维度
 * chips）→ 尝试拆解（默认隐藏句法树）→ 揭示句法树（clause_tree 嵌套渲染）+
 * 逐词释义（复用 /api/lookup/vocab 查词链）→ 可选「加入复习盒」（复用
 * /api/cards/grammar 语义）。会话结束 POST /api/syntax/hard-sentence/trials。
 *
 * 挂载于备考域 view-exam（index.html #exam-hard-sentences 容器），main.js
 * `import * as HardSentences` 命名空间接线（参照 ListenLab 先例）。
 *
 * 后端契约（delector/routes/syntax_hard.py，字段名逐字一致 —— 红线 11）：
 *   GET  /api/syntax/hard-sentences[?source=&source_id=&level=&min_score=&limit=]
 *                            → {items:[{sentence, score, level, dimensions,
 *                                       path, source, source_id, sentence_index}]}
 *   GET  /api/syntax/hard-sentences/detail?source=&source_id=&sentence_index=
 *                            → {sentence, score, level, dimensions, path, analysis}
 *   POST /api/syntax/hard-sentence/trials  body {source, source_id, sentence_index,
 *                                                level, score, revealed, duration_sec}
 *   POST /api/cards/grammar（复习盒复用，无新端点——照 reader.saveGrammar 卡字段）
 *
 * 红线 1：响应带 path，pure 路径显示「近似分析」提示，评分仅参考。
 * 重复入盒幂等：localStorage 记忆（键 = source:source_id:sentence_index），
 * 已入盒显示「已加入」，不与后端判定耦合。
 * 试练落盘失败静默降级（本地状态照常展示，不阻断卡片流）。
 */
"use strict";

import { api, esc, notify } from "./core.js";

/* ── 会话状态（单会话单队列） ─────────────────────────────────────────────── */
const _q = {
  source: "all",        // 'all' | 'article' | 'encounter'
  sourceId: null,       // source!=all 时选中的材料 id
  level: "all",         // 'all' | 'A1' | 'A2' | 'B1' | 'B2'
  materials: [],        // source!=all 时的材料清单（源/短文）
  materialsLoaded: false,
  items: [],            // 当前难度榜 {sentence, score, level, dimensions, path, source, source_id, sentence_index}
  itemsLoaded: false,
  idx: 0,               // 当前句索引
  detail: null,         // 当前句揭示出的完整分析 {analysis:{clause_tree, topology}}
  revealed: false,      // 本句是否揭示过
  revealedKeys: new Set(), // 本会话内揭示过的句子键
  spacyError: "",       // spaCy 加载诊断（/api/syntax/spacy-status，v5.7.4）
  startedAt: 0,
};

const _SAVED_PREFIX = "hardsent:saved:";

// CEFR 标签 → 胶囊配色
const _LEVEL_META = {
  A1: { cls: "hs-lv-a1" },
  A2: { cls: "hs-lv-a2" },
  B1: { cls: "hs-lv-b1" },
  B2: { cls: "hs-lv-b2" },
};

// dimensions 键 → 中文 chip 文案（值真值才渲染；length/深度/计数带数值）
const _DIM_META = [
  { key: "clause_depth", plain: "从句深度", numeric: true, suffix: "层" },
  { key: "clause_count", plain: "从句数", numeric: true, suffix: "个" },
  { key: "passive", plain: "被动" },
  { key: "subjunctive", plain: "虚拟式" },
  { key: "verb_last", plain: "VL 句框" },
  { key: "relative_clause", plain: "关系从句" },
  { key: "length", plain: "句长", numeric: true, suffix: "词" },
];

/* ── 工具函数 ─────────────────────────────────────────────────────────────── */

function el(id) {
  return document.getElementById(id);
}

function _sentenceKey(item) {
  return `${item.source || ""}:${item.source_id ?? ""}:${item.sentence_index ?? ""}`;
}

function _isSaved(item) {
  try {
    return !!localStorage.getItem(_SAVED_PREFIX + _sentenceKey(item));
  } catch (_e) {
    return false;
  }
}

function _markSaved(item) {
  try {
    localStorage.setItem(_SAVED_PREFIX + _sentenceKey(item), "1");
  } catch (_e) {
    /* localStorage 不可用：静默跳过（记忆降级，不阻断入盒） */
  }
}

// 会话已进行秒数（trial duration_sec 用）
function _elapsedSec() {
  return _q.startedAt ? Math.max(1, Math.round((Date.now() - _q.startedAt) / 1000)) : 0;
}

// 句子的复杂度维度 chips HTML
function _dimChipsHtml(dimensions) {
  if (!dimensions || typeof dimensions !== "object") return "";
  const chips = [];
  for (const meta of _DIM_META) {
    const d = dimensions[meta.key];
    if (d == null) continue;
    const v = d.value;
    if (meta.numeric) {
      if (Number(v) > 0) {
        chips.push(
          `<span class="hs-chip">${esc(meta.plain)} ${esc(String(v))}${esc(meta.suffix)}</span>`,
        );
      }
    } else if (v) {
      chips.push(`<span class="hs-chip">${esc(meta.plain)}</span>`);
    }
  }
  return chips.join("");
}

// 难度分 → 刻度中文描述
function _scoreLabel(score) {
  if (score >= 70) return "高难";
  if (score >= 45) return "中难";
  if (score >= 25) return "入门";
  return "基础";
}

// 空格分词：返回原词序列（保标点），供逐词可点渲染
function _tokenize(sentence) {
  return String(sentence || "").split(/\s+/).filter(Boolean);
}

/* ── 样式注入（Academic Modern Editorial token · 暖纸墨线风） ─────────────── */
let _styleInjected = false;
function _ensureStyle() {
  if (_styleInjected || el("hard-sentences-style")) return;
  _styleInjected = true;
  const style = document.createElement("style");
  style.id = "hard-sentences-style";
  style.textContent = `
#exam-hard-sentences { --hs-bg: var(--paper-warm); }
.hs-topbar { display:flex; align-items:center; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; margin-bottom:0.75rem; }
.hs-subhead { font-size:0.75rem; color:var(--pencil); font-family:var(--mono); margin-top:0.25rem; letter-spacing:0.02em; }
.hs-bar { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin:0.35rem 0; }
.hs-bar-label { font-size:0.6875rem; font-family:var(--mono); color:var(--ink-faint); text-transform:uppercase; letter-spacing:0.08em; margin-right:0.25rem; white-space:nowrap; }
.hs-pill { min-height:44px; padding:0.5rem 0.9rem; border:1.5px solid var(--ink); border-radius:999px; background:var(--paper-card); color:var(--ink); font-family:var(--mono); font-size:0.75rem; cursor:pointer; }
.hs-pill.active { background:var(--ink); color:var(--paper); }
.hs-select { min-height:44px; padding:0.45rem 0.6rem; border:1.5px solid var(--rule); border-radius:6px; background:var(--paper-card); color:var(--ink); font-family:var(--mono); font-size:0.75rem; cursor:pointer; }
.hs-material-card { display:flex; align-items:center; gap:0.5rem; min-height:44px; padding:0.55rem 0.85rem; border:1.5px solid var(--rule); border-radius:8px; background:var(--paper-card); font-size:0.9375rem; cursor:pointer; text-align:left; max-width:100%; }
.hs-material-card.active { border-color:var(--coral); background:var(--paper-warm); box-shadow:var(--shadow-sm); }
.hs-mat-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; }
.hs-empty { font-size:0.8125rem; color:var(--pencil); padding:0.5rem 0; }
.hs-btn { min-height:44px; padding:0.5rem 0.85rem; border:1.5px solid var(--ink); border-radius:6px; background:var(--paper-card); color:var(--ink); font-family:var(--mono); font-size:0.75rem; cursor:pointer; }
.hs-btn-dark { background:var(--ink); color:var(--paper); }
.hs-btn-main { background:var(--coral); border-color:var(--coral); color:#fff; }
.hs-btn:disabled { opacity:0.5; cursor:not-allowed; }
.hs-stage-head { display:flex; align-items:baseline; justify-content:space-between; gap:0.5rem; margin:0.75rem 0 0.5rem; flex-wrap:wrap; }
.hs-progress { font-family:var(--mono); font-size:0.75rem; color:var(--pencil); white-space:nowrap; }
.hs-card { border:1.5px solid var(--ink); border-radius:10px; background:var(--paper-card); padding:1.3rem 1.4rem; box-shadow:3px 4px 0 rgba(26,23,20,0.1); }
.hs-card-meta { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.6rem; }
.hs-score { font-family:var(--mono); font-weight:700; font-size:0.8125rem; }
.hs-score b { font-size:1.05rem; }
.hs-lv { font-family:var(--mono); font-weight:700; font-size:0.6875rem; padding:0.15rem 0.5rem; border-radius:999px; border:1.5px solid; }
.hs-lv-a1 { border-color:var(--moss); background:#e9f2ea; color:#2c5a31; }
.hs-lv-a2 { border-color:var(--mustard); background:#fbf3dc; color:#7a5d00; }
.hs-lv-b1 { border-color:var(--amber); background:#fbeedd; color:#9a5200; }
.hs-lv-b2 { border-color:var(--cherry); background:#fbeae7; color:#8f2424; }
.hs-src-tag { font-family:var(--mono); font-size:0.6875rem; color:var(--ink-faint); }
.hs-sentence { font-size:1.125rem; line-height:1.85; color:var(--ink); margin:0.6rem 0 0.8rem; }
.hs-word { cursor:pointer; border-bottom:1px dotted var(--pencil); padding:0 1px; }
.hs-word:hover { background:var(--hl-A2); border-bottom-color:var(--ink); }
.hs-chips { display:flex; flex-wrap:wrap; gap:0.35rem; margin-bottom:0.75rem; }
.hs-chip { display:inline-flex; align-items:center; padding:0.3rem 0.6rem; border-radius:999px; border:1.5px solid var(--rule); font-size:0.75rem; font-family:var(--mono); color:var(--pencil); background:var(--paper); }
.hs-path-note { font-size:0.75rem; font-family:var(--mono); color:var(--amber); margin-bottom:0.6rem; }
.hs-diag { color:var(--ink-faint); font-size:0.6875rem; }
.hs-actions { display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
.hs-reveal-zone { margin-top:0.9rem; }
.hs-reveal-tip { font-size:0.8125rem; color:var(--pencil); margin-bottom:0.6rem; }
.hs-tree { margin-top:0.6rem; font-size:0.9375rem; line-height:1.8; }
.hs-tree-node { margin-bottom:0.45rem; padding-left:0.85rem; border-left:2px solid var(--rule); }
.hs-tree-node .hs-tn-label { font-weight:700; color:var(--ink); }
.hs-tree-node .hs-tn-type { font-family:var(--mono); font-size:0.75rem; color:var(--coral); }
.hs-tree-node .hs-tn-verb { font-family:var(--mono); font-size:0.8125rem; color:var(--cherry); }
.hs-tree-node .hs-tn-text { color:var(--pencil); }
.hs-topo { margin-top:0.7rem; padding-top:0.7rem; border-top:1px dashed var(--rule); font-size:0.9375rem; line-height:1.85; }
.hs-topo .hs-topo-k { font-family:var(--mono); font-size:0.75rem; color:var(--ink-faint); text-transform:uppercase; letter-spacing:0.05em; }
.hs-topo .hs-topo-v { font-family:var(--mono); color:var(--ink); font-weight:600; }
.hs-added-note { font-family:var(--mono); font-size:0.75rem; color:var(--moss); font-weight:700; }
.hs-lookup-pop { margin-top:0.7rem; border:1.5px solid var(--ink); border-radius:8px; background:var(--paper-warm); padding:0.7rem 0.8rem; font-size:0.8125rem; box-shadow:var(--shadow-sm); }
.hs-lookup-word { font-family:var(--mono); font-weight:700; }
.hs-lookup-def { margin-left:0.4rem; }
.hs-lookup-meta { font-family:var(--mono); font-size:0.6875rem; color:var(--ink-faint); margin-left:0.4rem; }
.hs-summary { margin-top:1rem; border:1.5px solid var(--ink); border-radius:8px; background:var(--paper-warm); padding:1.25rem; box-shadow:3px 4px 0 rgba(26,23,20,0.12); }
.hs-summary-head { font-family:var(--serif-heading); font-size:1.125rem; font-weight:700; margin-bottom:0.6rem; }
.hs-summary-row { display:flex; gap:0.6rem; align-items:baseline; font-size:0.9375rem; margin-bottom:0.9rem; flex-wrap:wrap; }
.hs-summary-actions { display:flex; gap:0.5rem; flex-wrap:wrap; }
`;
  (document.head || document.documentElement).appendChild(style);
}

/* ── 渲染 ─────────────────────────────────────────────────────────────────── */

function _renderSourceBar() {
  const bar = el("hs-source-bar");
  if (!bar) return;
  bar.innerHTML =
    `<span class="hs-bar-label">材料源</span>` +
    [
      ["all", "全部"],
      ["article", "语料文章"],
      ["encounter", "遇见区短文"],
    ]
      .map(
        ([v, label]) =>
          `<button class="hs-pill${_q.source === v ? " active" : ""}" onclick="HardSentences.setHardSource('${v}')">${label}</button>`,
      )
      .join("");
}

function _renderLevelBar() {
  const bar = el("hs-level-bar");
  if (!bar) return;
  bar.innerHTML =
    `<span class="hs-bar-label">级别</span>` +
    `<select class="hs-select" id="hs-level-select" onchange="HardSentences.setHardLevel(this.value)" aria-label="难度级别过滤">` +
    [
      ["all", "全部"],
      ["A1", "A1（入门）"],
      ["A2", "A2（基础）"],
      ["B1", "B1（进阶）"],
      ["B2", "B2（高难）"],
    ]
      .map(
        ([v, label]) =>
          `<option value="${v}"${_q.level === v ? " selected" : ""}>${label}</option>`,
      )
      .join("") +
    `</select>`;
}

function _renderMaterialBar() {
  const bar = el("hs-material-bar");
  if (!bar) return;
  if (_q.source === "all") {
    bar.innerHTML = "";
    return;
  }
  if (!_q.materialsLoaded) {
    bar.innerHTML = `<span class="hs-empty">⏳ 正在加载材料…</span>`;
    return;
  }
  if (!_q.materials.length) {
    bar.innerHTML = `<span class="hs-empty">当前材料源暂无内容 —— 请切换材料源</span>`;
    return;
  }
  bar.innerHTML =
    `<span class="hs-bar-label">材料</span>` +
    _q.materials
      .map((m) => {
        const active = _q.sourceId != null && _q.sourceId === m.id;
        const lvCls = "hs-lv-" + String(m.level || "A1").toLowerCase();
        return `<button class="hs-material-card${active ? " active" : ""}" onclick="HardSentences.pickHardMaterial(${Number(m.id)})">
          ${_q.source === "article" ? "" : `<span class="hs-lv ${lvCls}">${esc(m.level || "")}</span>`}
          <span class="hs-mat-title">${esc(m.title || `材料 #${m.id}`)}</span>
        </button>`;
      })
      .join("");
}

function _flushTrial(item) {
  if (!item) return;
  const revealed = _q.revealedKeys.has(_sentenceKey(item)) ? 1 : 0;
  api("/api/syntax/hard-sentence/trials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: item.source,
      source_id: Number(item.source_id) ?? 0,
      sentence_index: Number(item.sentence_index) ?? 0,
      level: item.level || "",
      score: Number(item.score) ?? 0,
      revealed,
      duration_sec: _elapsedSec(),
    }),
  }).catch(() => {
    /* 静默降级：试练落盘失败不阻断卡片流（红线 11） */
  });
}

// 揭示句法树：GET detail → 渲染 clause_tree 嵌套 + topology
async function _reveal(item) {
  if (!item) return;
  _q.detail = null;
  try {
    const params = new URLSearchParams({
      source: item.source || "",
      source_id: String(Number(item.source_id) ?? 0),
      sentence_index: String(Number(item.sentence_index) ?? 0),
    });
    const data = await api(`/api/syntax/hard-sentences/detail?${params.toString()}`);
    _q.detail = data || {};
  } catch (e) {
    notify(`句法分析不可用：${e.message || "未知错误"}`, { kind: "error" });
    _q.detail = {};
  }
  _q.revealed = true;
  _q.revealedKeys.add(_sentenceKey(item));
  _renderStage();
}

function _treeNodeHtml(node, depth) {
  if (!node || typeof node !== "object") return "";
  const type = node.type || "";
  const label = node.label || type;
  const fin = node.finite_verb ? `<span class="hs-tn-verb"> ➤定式 ${esc(node.finite_verb)}</span>` : "";
  const text = node.text ? `<span class="hs-tn-text"> ｜ ${esc(node.text)}</span>` : "";
  const children = Array.isArray(node.children) && node.children.length
    ? node.children
        .map((c) => _treeNodeHtml(c, depth + 1))
        .join("")
    : "";
  return `<div class="hs-tree-node" style="margin-left:${depth * 0.9}rem">
    <span class="hs-tn-type">${esc(type)}</span>
    <span class="hs-tn-label">${esc(label)}</span>${fin}${text}
    ${children ? `<div class="hs-tree-children">${children}</div>` : ""}
  </div>`;
}

function _topologyHtml(analysis) {
  const topo = analysis && analysis.topology;
  if (!topo || typeof topo !== "object") return "";
  const lines = [];
  // 五场域 VF/LK/MF/RK/NF（field_texts 已含可读文案）
  const fieldOrder = [
    ["vorfeld", "VF 前置场"],
    ["linke_klammer", "LK 左框"],
    ["mittelfeld", "MF 中段"],
    ["rechte_klammer", "RK 右框"],
    ["nachfeld", "NF 后置"],
  ];
  for (const [key, zh] of fieldOrder) {
    const ft = topo.field_texts && topo.field_texts[key];
    // field_texts 值为**字符串**（spaCy 与纯 Python 双路径的真实形状）；缺失时
    // 才退化到顶层 token 数组。旧实现 `Array.isArray(ft) ? ft.join(" ") : topo[key]`
    // 对字符串 field_texts 恒走 else → vals=原始 token 数组 → String(数组) 渲染成
    // "[object Object],[object Object]"（真机报障，探针 fixture 形状错误漏检）。
    let vals = null;
    if (typeof ft === "string" && ft.trim()) {
      vals = ft;
    } else if (Array.isArray(ft)) {
      vals = ft.join(" ");
    } else if (Array.isArray(topo[key])) {
      vals = topo[key].join(" ");
    } else if (topo[key] != null) {
      vals = topo[key];
    }
    if (vals && String(vals).trim()) {
      lines.push(`<span class="hs-topo-k">${zh}</span> <span class="hs-topo-v">${esc(String(vals))}</span>`);
    }
  }
  if (topo.sentence_type) lines.push(`<span class="hs-topo-k">框型</span> <span class="hs-topo-v">${esc(topo.sentence_type)}</span>`);
  if (topo.bracket_structure) lines.push(`<span class="hs-topo-k">结构</span> <span class="hs-topo-v">${esc(topo.bracket_structure)}</span>`);
  if (!lines.length) return "";
  return `<div class="hs-topo">${lines.join(" · ")}</div>`;
}

// 逐词可点渲染：点击查词（POST /api/lookup/vocab 轻量弹层）
function _sentenceHtml(item) {
  const words = _tokenize(item.sentence);
  return words
    .map((w, i) => `<span class="hs-word" onclick="HardSentences.lookupWord(${i})" role="button" tabindex="0">${esc(w)}</span>`)
    .join(" ");
}

function _renderStage() {
  const stage = el("hs-stage");
  const summary = el("hs-summary");
  if (!stage) return;
  const item = _q.items[_q.idx];
  if (!item) {
    stage.innerHTML = "";
    if (summary) summary.innerHTML = "";
    return;
  }
  const meta = _LEVEL_META[item.level] || {};
  const a1a2Note = item.level === "A1" || item.level === "A2";
  const saved = _isSaved(item);
  const revealedZone = _q.revealed
    ? _renderRevealedZone(item)
    : `<div class="hs-reveal-zone">
        <div class="hs-reveal-tip">🔍 先试着自己找主句 —— 想好了再点揭示，核对自己的拆解。</div>
        <button class="hs-btn hs-btn-main" onclick="HardSentences.revealTree()">🔍 揭示句法树</button>
        ${a1a2Note ? `<span class="hs-src-tag">A1/A2：精读脚手架，难度画像仅供参考</span>` : ""}
      </div>`;

  stage.innerHTML = `
    <div class="hs-stage-head">
      <span class="hs-bar-label">长难句 · ${esc(_q.source === "all" ? "全语料难度榜" : (_q.source === "article" ? "语料文章" : "遇见区短文"))}</span>
      <span class="hs-progress">句 ${_q.idx + 1} / ${_q.items.length}</span>
    </div>
    <div class="hs-card">
      <div class="hs-card-meta">
        <span class="hs-lv ${meta.cls}">${esc(item.level || "-")}</span>
        <span class="hs-score">难度<b>${Math.round(Number(item.score) || 0)}</b>/100 · ${esc(_scoreLabel(item.score))}</span>
        ${_q.source === "all" ? `<span class="hs-src-tag">${esc(item.source)}#${esc(String(item.source_id))} · 第${Number(item.sentence_index) + 1}句</span>` : ""}
      </div>
      ${item.path === "pure" ? `<div class="hs-path-note">✦ 轻量分析：难度画像为粗估，排序供参考，不必当真${_q.spacyError ? ` <span class="hs-diag" title="NLP 引擎降级原因">诊断：${esc(_q.spacyError)}</span>` : ""}</div>` : ""}
      <div class="hs-sentence">${_sentenceHtml(item)}</div>
      <div class="hs-chips">${_dimChipsHtml(item.dimensions)}</div>
      ${revealedZone}
      <div id="hs-lookup-pop-zone"></div>
      <div class="hs-actions" style="${_q.revealed ? "" : "margin-top:0.9rem;"}">
        <button class="hs-btn hs-btn-dark" onclick="HardSentences.addCard()" id="hs-add-card-btn">${saved ? "✔ 已加入复习盒" : "➕ 加入复习盒"}</button>
        <button class="hs-btn" onclick="HardSentences.prevCard()" title="上一句">⏮ 上一句</button>
        <button class="hs-btn hs-btn-main" onclick="HardSentences.nextCard()">下一句 ▶</button>
      </div>
    </div>
  `;
}

function _renderRevealedZone(item) {
  const analysis = _q.detail && _q.detail.analysis;
  const tree = analysis && analysis.clause_tree;
  let treeHtml = "";
  if (tree && typeof tree === "object") {
    treeHtml = `<div class="hs-tree"><span class="hs-bar-label">子句树</span>${_treeNodeHtml(tree, 0)}</div>`;
  }
  return `
    <div class="hs-reveal-zone">
      <div class="hs-reveal-tip">✅ 句法结构已揭示 —— 对照你的拆解。</div>
      ${treeHtml}
      ${_topologyHtml(analysis)}
    </div>
  `;
}

function _renderSummary() {
  const summary = el("hs-summary");
  if (!summary) return;
  if (!_q.items.length) {
    summary.innerHTML = "";
    return;
  }
  summary.innerHTML = `
    <div class="hs-summary">
      <div class="hs-summary-head">🏁 本会话</div>
      <div class="hs-summary-row">
        <span>句子 <b>${_q.items.length}</b></span>
        <span>·</span>
        <span>已揭示 <b>${_q.revealedKeys.size}</b></span>
        <span>·</span>
        <span>当前句难度 <b>${Math.round(Number(_q.items[_q.idx].score) || 0)}/100</b></span>
      </div>
      <div class="hs-summary-actions">
        <button class="hs-btn" onclick="HardSentences.restart()">↺ 重新加载</button>
        <button class="hs-btn hs-btn-dark" onclick="HardSentences.exit()">⟲ 换材料</button>
      </div>
    </div>
  `;
}

function _renderAll() {
  _renderSourceBar();
  _renderLevelBar();
  _renderMaterialBar();
  _renderStage();
  _renderSummary();
}

/* ── 材料 / 句子拉取 ─────────────────────────────────────────────────────── */

function _queryParams() {
  const p = new URLSearchParams();
  p.set("source", _q.source);
  if (_q.source !== "all" && _q.sourceId != null) p.set("source_id", String(Number(_q.sourceId)));
  if (_q.level !== "all") p.set("level", _q.level);
  p.set("limit", "50");
  return p;
}

async function _loadItems() {
  _q.itemsLoaded = false;
  _q.items = [];
  _q.idx = 0;
  _q.detail = null;
  _q.revealed = false;
  try {
    const res = await api(`/api/syntax/hard-sentences?${_queryParams().toString()}`);
    _q.items = (res && res.items) || [];
  } catch (e) {
    _q.items = [];
    notify(`长难句清单加载失败：${e.message || "未知错误"}`, { kind: "error" });
  }
  _q.itemsLoaded = true;
  if (!_q.startedAt) _q.startedAt = Date.now();
  _renderAll();
  if (!_q.items.length) {
    const stage = el("hs-stage");
    if (stage) stage.innerHTML = `<div class="hs-empty">没有符合当前条件的句子 —— 可在级别/材料源上放宽筛选</div>`;
  }
}

async function _loadMaterials() {
  _q.materialsLoaded = false;
  _q.materials = [];
  _q.sourceId = null;
  try {
    if (_q.source === "article") {
      const data = await api("/api/articles");
      _q.materials = Array.isArray(data) ? data.map((a) => ({ id: a.id, title: a.title, level: "" })) : [];
    } else if (_q.source === "encounter") {
      const data = await api("/api/encounter/texts");
      const texts = (data && data.texts) || [];
      _q.materials = texts.map((t) => ({ id: t.id, title: t.title, level: t.level || "" }));
    }
  } catch (e) {
    _q.materials = [];
    notify(`材料清单加载失败：${e.message || "未知错误"}`, { kind: "error" });
  }
  _q.materialsLoaded = true;
  _renderAll();
}

/* ── 对外导出（main.js `import * as HardSentences` + window 命名空间挂载） ── */

// 进入备考域长难句工坊：幂等初始化（样式 + 拉到默认全部难度榜）
export async function enterHardSentences() {
  _ensureStyle();
  if (!el("hs-stage")) return;
  // 先等诊断就绪再渲染：_loadSpacyDiag 非 await 时 _renderAll 抢先执行，
  // _q.spacyError 还是空串 → 诊断小字永不出现（v5.7.4 真机确认）。
  await _loadSpacyDiag();
  if (!_q.itemsLoaded) await _loadItems();
  _renderAll();
}

// 拉 spaCy 加载诊断（只读；失败静默，不阻断工坊）
async function _loadSpacyDiag() {
  try {
    const data = await api("/api/syntax/spacy-status");
    _q.spacyError =
      data && data.path === "pure"
        ? data.error || "未捕获到加载异常（需进一步排查）"
        : "";
  } catch (_e) {
    _q.spacyError = "";
  }
}

// 离开备考域：落盘当前句试练（幂等；本句已揭示则记 1）
export function stopHardSentences() {
  if (_q.items[_q.idx]) _flushTrial(_q.items[_q.idx]);
}

// 材料源切换：重置材料/句子清单
export async function setHardSource(source) {
  if (!["all", "article", "encounter"].includes(source)) return;
  _q.source = source;
  _q.sourceId = null;
  _q.itemsLoaded = false;
  _q.items = [];
  _q.idx = 0;
  _q.detail = null;
  _q.revealed = false;
  if (source === "all") {
    await _loadItems();
  } else {
    await _loadMaterials();
    _renderAll();
  }
}

// 级别过滤：重置并重拉
export async function setHardLevel(level) {
  if (!["all", "A1", "A2", "B1", "B2"].includes(level)) return;
  _q.level = level;
  await _loadItems();
}

// 选材料：拉该材料长难句榜单
export async function pickHardMaterial(id) {
  if (id == null) return;
  _q.sourceId = Number(id);
  await _loadItems();
}

export async function revealTree() {
  const item = _q.items[_q.idx];
  if (!item || _q.revealed) return;
  await _reveal(item);
}

// 逐词查词：POST /api/lookup/vocab 轻量弹层
export async function lookupWord(idx) {
  const item = _q.items[_q.idx];
  if (!item) return;
  const words = _tokenize(item.sentence);
  const word = words[idx];
  if (!word) return;
  const zone = el("hs-lookup-pop-zone");
  if (zone) zone.innerHTML = `<div class="hs-lookup-pop"><span class="hs-lookup-word">${esc(word)}</span><span class="hs-lookup-def">查询中…</span></div>`;
  try {
    const data = await api("/api/lookup/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentence: item.sentence, target_word: word }),
    });
    const def = (data && data.definition_zh) || "（未找到释义）";
    const pos = data && data.pos ? `<span class="hs-lookup-meta">${esc(data.pos)}</span>` : "";
    const lv = data && data.cefr_level ? `<span class="hs-lookup-meta">${esc(data.cefr_level)}</span>` : "";
    const plural = data && data.plural ? `<span class="hs-lookup-meta">复数 ${esc(data.plural)}</span>` : "";
    if (zone) zone.innerHTML = `<div class="hs-lookup-pop"><span class="hs-lookup-word">${esc(word)}</span><span class="hs-lookup-def">${esc(def)}</span>${pos}${lv}${plural}</div>`;
  } catch (e) {
    if (zone) zone.innerHTML = `<div class="hs-lookup-pop"><span class="hs-lookup-word">${esc(word)}</span><span class="hs-lookup-def">查词失败：${esc(e.message || "未知错误")}</span></div>`;
  }
}

// 加入复习盒：复用 /api/cards/grammar 语义（照 reader.saveGrammar 卡字段）
export async function addCard() {
  const item = _q.items[_q.idx];
  if (!item) return;
  if (_isSaved(item)) {
    notify("该句已加入复习盒", { kind: "info" });
    return;
  }
  const btn = el("hs-add-card-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "保存中…";
  }
  const dimParts = _DIM_META
    .map((meta) => {
      const d = item.dimensions && item.dimensions[meta.key];
      if (!d) return null;
      if (meta.numeric) return d.value > 0 ? `${meta.plain} ${d.value}` : null;
      return d.value ? meta.plain : null;
    })
    .filter(Boolean);
  const explanation = dimParts.length
    ? `长难句精读（${dimParts.join(" · ")}）`
    : `长难句精读（难度 ${Math.round(Number(item.score) || 0)}/100）`;
  try {
    await api("/api/cards/grammar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_id: item.source === "article" ? Number(item.source_id) : null,
        sentence_context: item.sentence,
        grammar_name: "长难句精读",
        cefr_level: item.level || "B1",
        explanation_zh: explanation,
        rule_formula: `难度 ${Math.round(Number(item.score) || 0)}/100 · 源 ${item.source}#${String(item.source_id)}`,
        corrected_form: "",
        error_type: "",
      }),
    });
    _markSaved(item);
    if (btn) btn.textContent = "✔ 已加入复习盒";
    notify("已加入复习盒", { kind: "success" });
  } catch (e) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "➕ 加入复习盒";
    }
    notify(`加入复习盒失败：${e.message || "未知错误"}`, { kind: "error" });
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function nextCard() {
  if (!_q.items.length) return;
  if (_q.idx < _q.items.length - 1) {
    _q.idx += 1;
    _q.detail = null;
    _q.revealed = false;
    _renderAll();
  } else {
    // 到末尾：落盘最后一句试练，提示会话结束
    _flushTrial(_q.items[_q.idx]);
    notify("已到末尾 —— 本会话句子已浏览完", { kind: "info" });
  }
}

export function prevCard() {
  if (!_q.items.length) return;
  if (_q.idx > 0) {
    _q.idx -= 1;
    _q.detail = null;
    _q.revealed = false;
    _renderAll();
  }
}

export async function restart() {
  return _loadItems();
}

export async function exit() {
  if (!_q.items.length) return;
  _flushTrial(_q.items[_q.idx]);
  // 回到源选择空态（保留材料源胶囊，清空榜单）
  _q.items = [];
  _q.itemsLoaded = false;
  _q.idx = 0;
  _q.detail = null;
  _q.revealed = false;
  _q.source = "all";
  _q.sourceId = null;
  _q.level = "all";
  _q.startedAt = 0;
  await _loadItems();
}