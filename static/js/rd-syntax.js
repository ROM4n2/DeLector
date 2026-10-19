/* DeLector - Reader Syntax, Radar & Topology Renderers (L1 Pure Layer)
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制；见
 * docs/plans/2026-10-19-reader-js-layer-split.md Task 2）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage /
 *   getElementById / querySelector / innerHTML / addEventListener 等）；
 *   MUST NOT 发网络请求（fetch / api / XMLHttpRequest 等）；
 *   MUST NOT 弹用户提示（notify / alert / confirm 等）；
 *   MUST NOT 用计时器（setTimeout / setInterval 等）；
 *   MUST NOT 有顶层 `let`/`var`（无可变模块状态）。
 *   允许的 import 仅限 ./core.js 的 esc, jsAttr, normalizeCefrPct。
 */
'use strict';

import { esc, jsAttr, normalizeCefrPct } from './core.js';

export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1"];
export const safeCefr = (v) => (CEFR_LEVELS.includes(v) ? v : "A1");
export const safeTokens = (ids) =>
  JSON.stringify((ids || []).map(Number).filter(Number.isFinite));

export function renderMiniBar(stats) {
  if (!stats || !stats.cefr_percentages) return "";
  const p = normalizeCefrPct(stats.cefr_percentages);
  const segs = ["A1", "A2", "B1", "B2", "C1"]
    .map((lvl) =>
      p[lvl] > 0
        ? `<div class="mini-seg ${lvl}" style="width:${p[lvl]}%" title="${lvl}: ${p[lvl]}%"></div>`
        : "",
    )
    .join("");

  const rec = safeCefr(stats.recommended_level);
  const recClass = rec.startsWith("B2") ? "mini-level-B2" : `mini-level-${rec}`;

  return `
    <div class="mini-bar-wrap">
      <span class="mini-level-badge ${recClass}">${rec} 推荐</span>
      <div class="mini-cefr-bar">${segs}</div>
      <span style="font-size:0.6875rem;color:var(--pencil);font-family:var(--mono);">约 ${Number(stats.est_reading_minutes) || 1} 分钟</span>
    </div>
  `;
}

export function renderFelderSpectrum(topology, sentId) {
  if (!topology)
    return '<span style="font-size:0.75rem;color:var(--pencil);">五场域拓扑解析中...</span>';
  const fields = [
    { key: "vorfeld", label: "前场 VF", cls: "vf", desc: "Vorfeld" },
    {
      key: "linke_klammer",
      label: "左框 LK",
      cls: "lk",
      desc: "Linke Klammer",
    },
    { key: "mittelfeld", label: "中场 MF", cls: "mf", desc: "Mittelfeld" },
    {
      key: "rechte_klammer",
      label: "右框 RK",
      cls: "rk",
      desc: "Rechte Klammer",
    },
    { key: "nachfeld", label: "后场 NF", cls: "nf", desc: "Nachfeld" },
  ];

  const boxes = fields
    .map((f) => {
      const toks = topology[f.key] || [];
      const text =
        toks.map((t) => (t && t.text !== undefined ? t.text : t)).join(" ") ||
        "—";
      const isEmp = toks.length === 0;
      return `
      <div class="feld-pill feld-${f.cls}${isEmp ? " is-empty" : ""}" title="${f.desc}">
        <span class="feld-tag">${f.label}</span>
        <span class="feld-val">${esc(text)}</span>
      </div>
    `;
    })
    .join("");

  return `
    <div class="felder-spectrum-bar">
      ${boxes}
    </div>
    <div class="felder-bar-actions">
      <button class="btn-open-ast-action" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sentId)})">在工作台展开从句拓扑树 AST ➔</button>
    </div>
  `;
}

export function renderDetailedFelderGrid(topology) {
  if (!topology) return '<div class="empty-state">暂无拓扑场域数据</div>';
  const fields = [
    {
      key: "vorfeld",
      name: "前场 (Vorfeld)",
      desc: "主语 / 状语 / 前置从句",
      cls: "vf",
    },
    {
      key: "linke_klammer",
      name: "左框 (Linke Klammer)",
      desc: "主句变位动词 / 从句引导连词",
      cls: "lk",
    },
    {
      key: "mittelfeld",
      name: "中场 (Mittelfeld)",
      desc: "核心论元 / 宾语 / 副词状语",
      cls: "mf",
    },
    {
      key: "rechte_klammer",
      name: "右框 (Rechte Klammer)",
      desc: "未变位动词 / 分词 / 前缀 / 从句谓语",
      cls: "rk",
    },
    {
      key: "nachfeld",
      name: "后场 (Nachfeld)",
      desc: "后置从句 / 比较短语 / 补充成分",
      cls: "nf",
    },
  ];

  return fields
    .map((f) => {
      const toks = topology[f.key] || [];
      const text =
        toks.map((t) => (t && t.text !== undefined ? t.text : t)).join(" ") ||
        "（空）";
      const isEmp = toks.length === 0;
      return `
      <div class="feld-card feld-card-${f.cls}${isEmp ? " is-empty-card" : ""}">
        <div class="feld-card-header">
          <span class="feld-card-title">${f.name}</span>
          <span class="feld-card-desc">${f.desc}</span>
        </div>
        <div class="feld-card-content">${esc(text)}</div>
      </div>
    `;
    })
    .join("");
}

export function renderClauseTreeNode(node, depth = 0, sentId) {
  if (!node)
    return '<div class="syntax-empty" style="color:var(--pencil);font-size:0.8125rem;">暂无从句分层</div>';

  const typeCls = String(node.type || "hauptsatz").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const formulaHtml = node.formula
    ? `<div class="clause-formula"><code>${esc(node.formula)}</code></div>`
    : "";
  const connectorHtml = node.connector
    ? `<span class="clause-pill-tag tag-conn">引导: <strong>${esc(node.connector)}</strong></span>`
    : "";
  const verbHtml = node.finite_verb
    ? `<span class="clause-pill-tag tag-verb">动词: <strong>${esc(node.finite_verb)}</strong></span>`
    : "";
  const tokenIds = (node.token_ids || []).map(Number).filter(Number.isFinite);
  const tokenIdsJson = JSON.stringify(tokenIds);

  const childHtml =
    node.children && node.children.length > 0
      ? `<div class="clause-children-tree">${node.children.map((c) => renderClauseTreeNode(c, depth + 1, sentId)).join("")}</div>`
      : "";

  const clauseLabel = node.label || node.type || "句法节点";
  const clauseFormula = node.formula || "";
  const clauseText = node.text || "";

  return `
    <div class="clause-tree-node depth-${depth} type-${typeCls}">
      <div class="clause-node-box" onclick="highlightClauseTokens(${tokenIdsJson})">
        <div class="clause-node-top">
          <span class="clause-type-name">${esc(node.label || node.type)}</span>
          <div style="display:flex;gap:0.35rem;flex-wrap:wrap;">
            ${connectorHtml}
            ${verbHtml}
          </div>
        </div>
        ${formulaHtml}
        <div class="clause-quote-text">„${esc(node.text || "")}“</div>
        <div class="clause-node-footer">
          <button class="btn-clause-pill" onclick="event.stopPropagation(); highlightClauseTokens(${tokenIdsJson})">🔍 聚焦高亮</button>
          <button class="btn-clause-pill btn-save-anki" onclick="event.stopPropagation(); saveClauseAsGrammarCard(${jsAttr(clauseLabel)}, ${jsAttr(clauseFormula)}, ${jsAttr(clauseText)}, ${Number(sentId)})">+ 加入语法卡</button>
        </div>
      </div>
      ${childHtml}
    </div>
  `;
}

export function computeArticleSyntaxStats(sentences) {
  if (!Array.isArray(sentences) || sentences.length === 0) {
    return {
      sent_count: 0,
      avg_clause_depth: 0.0,
      passive_rate: 0.0,
      konjunktiv_rate: 0.0,
      vl_rate: 0.0,
    };
  }
  let totalDepth = 0;
  let passiveCount = 0;
  let konjCount = 0;
  let vlCount = 0;

  function getTreeDepth(node) {
    if (!node) return 0;
    if (!node.children || node.children.length === 0) return 1;
    let maxChild = 0;
    for (const child of node.children) {
      const d = getTreeDepth(child);
      if (d > maxChild) maxChild = d;
    }
    return 1 + maxChild;
  }

  function checkTreeFeatures(node) {
    let hasPassive = !!(node?.features?.is_passive);
    let hasKonj = !!(node?.features?.is_subjunctive);
    if (node?.children) {
      for (const child of node.children) {
        const sub = checkTreeFeatures(child);
        if (sub.hasPassive) hasPassive = true;
        if (sub.hasKonj) hasKonj = true;
      }
    }
    return { hasPassive, hasKonj };
  }

  const total = sentences.length;
  for (const sent of sentences) {
    if (sent.clause_tree) {
      totalDepth += getTreeDepth(sent.clause_tree);
      const feats = checkTreeFeatures(sent.clause_tree);
      if (feats.hasPassive) passiveCount++;
      if (feats.hasKonj) konjCount++;
    } else {
      totalDepth += 1;
    }
    if (sent.topology?.sentence_type === "VL") {
      vlCount++;
    }
  }

  return {
    sent_count: total,
    avg_clause_depth: Number((totalDepth / total).toFixed(2)),
    passive_rate: Number((passiveCount / total).toFixed(4)),
    konjunktiv_rate: Number((konjCount / total).toFixed(4)),
    vl_rate: Number((vlCount / total).toFixed(4)),
  };
}

export function renderRadarSvg(current, historical) {
  const cur = current || {};
  const hist = historical || null;

  const cx = 110;
  const cy = 110;
  const radius = 75;
  const labelRadius = 92;

  // 4 dimensions:
  // 1. 嵌套深度: normalize min 1.0, max 4.0 -> clamp [0, 1]
  // 2. 被动率: max 0.5 -> clamp [0, 1]
  // 3. Konj.II率: max 0.5 -> clamp [0, 1]
  // 4. VL句式: max 0.6 -> clamp [0, 1]
  const clamp01 = (v) => Math.max(0, Math.min(1, Number(v) || 0));

  const normDepth = (d) => clamp01(((Number(d) || 1.0) - 1.0) / 3.0);
  const normPassive = (p) => clamp01((Number(p) || 0) / 0.5);
  const normKonj = (k) => clamp01((Number(k) || 0) / 0.5);
  const normVl = (v) => clamp01((Number(v) || 0) / 0.6);

  // Angles: North, East, South, West: -PI/2, 0, PI/2, PI
  const angles = [-Math.PI / 2, 0, Math.PI / 2, Math.PI];

  // Grid lines: 3 concentric circles or polygons at r = 25, 50, 75
  const gridRadii = [25, 50, 75];
  let gridSvg = "";
  for (const r of gridRadii) {
    const gridPoints = angles.map((ang) => {
      const x = cx + r * Math.cos(ang);
      const y = cy + r * Math.sin(ang);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    gridSvg += `<polygon points="${gridPoints}" fill="none" stroke="var(--line-soft, #d8d0c2)" stroke-width="1" stroke-dasharray="2,2"/>`;
  }

  // 4 radial axis lines from center to outer web
  let axisSvg = "";
  for (const ang of angles) {
    const x2 = cx + radius * Math.cos(ang);
    const y2 = cy + radius * Math.sin(ang);
    axisSvg += `<line class="radar-axis" x1="${cx}" y1="${cy}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="var(--line, rgba(21,20,15,0.16))" stroke-width="1"/>`;
  }

  // 4 labels placed outside axes at r = 92
  const labels = [
    { text: `深度 (${(cur.avg_clause_depth || 0).toFixed(1)})`, anchor: "middle", baseline: "baseline" },
    { text: `被动 (${Math.round((cur.passive_rate || 0) * 100)}%)`, anchor: "start", baseline: "middle" },
    { text: `Konj (${Math.round((cur.konjunktiv_rate || 0) * 100)}%)`, anchor: "middle", baseline: "hanging" },
    { text: `VL (${Math.round((cur.vl_rate || 0) * 100)}%)`, anchor: "end", baseline: "middle" },
  ];

  let labelSvg = "";
  for (let i = 0; i < angles.length; i++) {
    const ang = angles[i];
    const lx = cx + labelRadius * Math.cos(ang);
    const ly = cy + labelRadius * Math.sin(ang);
    const item = labels[i];
    labelSvg += `<text class="radar-label" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${item.anchor}" dominant-baseline="${item.baseline}">${esc(item.text)}</text>`;
  }

  // Helper to compute points from data
  function computePoints(data) {
    const vals = [
      normDepth(data.avg_clause_depth),
      normPassive(data.passive_rate),
      normKonj(data.konjunktiv_rate),
      normVl(data.vl_rate),
    ];
    return vals.map((norm, i) => {
      const r = norm * radius;
      const x = cx + r * Math.cos(angles[i]);
      const y = cy + r * Math.sin(angles[i]);
      return { x, y };
    });
  }

  // Historical polygon
  let histSvg = "";
  if (hist && (hist.total_articles || 0) > 0) {
    const histPts = computePoints(hist);
    const histPtsStr = histPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    histSvg = `<polygon points="${histPtsStr}" stroke="var(--muted, #8c8477)" stroke-dasharray="3,3" fill="none" stroke-width="1.5"/>`;
  }

  // Current polygon and vertices
  const curPts = computePoints(cur);
  const curPtsStr = curPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const curPoly = `<polygon points="${curPtsStr}" stroke="var(--accent, #c14a2b)" stroke-width="2" fill="var(--accent, #c14a2b)" fill-opacity="0.25"/>`;

  let curVertices = "";
  for (const pt of curPts) {
    curVertices += `<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="3" fill="var(--accent, #c14a2b)"/>`;
  }

  return `${gridSvg}${axisSvg}${histSvg}${curPoly}${curVertices}${labelSvg}`;
}

