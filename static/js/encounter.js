/* DeLector - 遇见区 (Encounter Zone) P0 Skeleton
 *
 * Task A4: curated short-text list + detail reader + local add-text form.
 * Task A5: 已背词 deck 桥 —— 打开短篇时拉 A3 annotate，按本机背词工作台 deck
 *          判定 known，渲染逐 token 高亮 + 覆盖统计（#enc-coverage）。
 * Views are routed by main.js show() (lazy show-style, no eager DOMContentLoaded
 * work). We only talk to the backend through the shared `api()` fetch wrapper in
 * ./core.js and escape all user-supplied strings with `esc()` before they enter
 * innerHTML — no raw interpolation of untrusted content.
 */
"use strict";

import { api, esc } from "./core.js";
import {
  loadDeck,
  mergeServerDeck,
  buildKnownSet,
  annotateWithDeck,
} from "./deck-bridge.js";

// ── Internal routing state ──────────────────────────────────────────────────
// The view has two sub-states: the curated list (default) and the detail reader.
let _detailOpen = false;

function listEl() {
  return document.getElementById("encounter-text-list");
}
function readerEl() {
  return document.getElementById("encounter-reader");
}
function coverageEl() {
  return document.getElementById("enc-coverage");
}

// A5：若 token 以标点/闭引/闭括号开头，前一个 token 后不要补空格（贴在一起）。
// 开头的专用正则：常见的句读、闭引号、闭括号。
const LEADING_PUNCT_RE = /^[\s]*[.,!?;:)\]}"'»›„„…—-]/;

function hideCoverage() {
  const el = coverageEl();
  if (el) el.style.display = "none";
}

function setCoverage(html) {
  const el = coverageEl();
  if (!el) return;
  el.innerHTML = html;
  el.style.display = "";
}

// A5：解析本机 deck；本机为空时尝试用 GET /api/wb/state 镜像兜底并合并。
async function resolveDeck() {
  const storage =
    typeof window !== "undefined" && window.localStorage
      ? window.localStorage
      : null;
  let deck = loadDeck(storage);
  const empty =
    !Array.isArray(deck.words) ||
    deck.words.length === 0 ||
    !deck.cards ||
    Object.keys(deck.cards).length === 0;
  if (empty) {
    let server = null;
    try {
      server = await api("/api/wb/state");
    } catch (e) {
      /* 镜像拉取失败静默：回退到本机（即便本机空）。 */
    }
    if (
      server &&
      (Array.isArray(server.words) || (server.cards && typeof server.cards === "object"))
    ) {
      deck = mergeServerDeck(deck, server);
    }
  }
  return deck;
}

// 纯文本段落回退渲染（A4 保持）：无 annotate / 无已背词时用，绝不清覆盖行。
function buildPlainParagraphs(text) {
  const paragraphs = String(text.content || "")
    .split(/\n\s*\n/)
    .filter((p) => p.trim().length > 0);
  return paragraphs.map((p) => `<p>${esc(p.trim())}</p>`).join("");
}

// A5：把注解句子渲染成"每 token 一个 span"的流动正文，join 用单空格但
// 标点/闭引前不加前置空格、句首 token 无前置空格；句子间补一个空格。
function buildAnnotatedBody(annotate) {
  return (annotate.sentences || [])
    .map((s) => {
      const toks = s.tokens || [];
      let html = "";
      for (let i = 0; i < toks.length; i++) {
        const tok = toks[i];
        const text = String(tok == null || tok.text == null ? "" : tok.text);
        const lemma = String(tok == null || tok.lemma == null ? "" : tok.lemma);
        if (i > 0 && !LEADING_PUNCT_RE.test(text)) html += " ";
        const cls = tok && tok.known ? "enc-tok enc-known" : "enc-tok";
        html += `<span class="${cls}" data-lemma="${esc(lemma)}">${esc(text)}</span>`;
      }
      return html;
    })
    .filter((h) => h.length > 0)
    .join(" ");
}

// ── Fetch list ──────────────────────────────────────────────────────────────
export async function fetchTexts() {
  const res = await api("/api/encounter/texts");
  return (res && res.texts) || [];
}

// ── Render list ─────────────────────────────────────────────────────────────
export function renderTextList(texts) {
  const el = listEl();
  if (!el) return;
  if (!texts.length) {
    el.innerHTML =
      '<div class="encounter-empty">遇见区暂无短篇 —— 点右上「＋ 加文本」添加一篇。</div>';
    return;
  }
  el.innerHTML = texts
    .map(
      (t) => `
      <div class="encounter-card" onclick="encounterOpenText(${Number(t.id)})" role="button" tabindex="0">
        <span class="encounter-badge ${esc(t.level)}">${esc(t.level)}</span>
        <span class="encounter-card-title">${esc(t.title)}</span>
        <span class="encounter-card-meta">
          ${typeof t.word_count === "number" ? `${t.word_count} 词 · ` : ""}
          ${esc(t.created_at || "")} · ${esc(t.source || "—")}
        </span>
      </div>
    `,
    )
    .join("");
}

export async function showView() {
  // 默认回到列表态；若已在详情态则刷新当前详情标题/正文不改动（进入入口卡首次为列表）。
  _detailOpen = false;
  hideCoverage();
  const rd = readerEl();
  if (rd) rd.style.display = "none";
  const ls = listEl();
  if (ls) ls.style.display = "";
  const addForm = document.getElementById("encounter-add-form");
  if (addForm) addForm.classList.remove("open");
  try {
    const texts = await fetchTexts();
    renderTextList(texts);
  } catch (e) {
    const el = listEl();
    if (el) {
      el.innerHTML = `<div class="encounter-empty">加载遇见区列表失败：${esc(
        e.message || "未知错误",
      )}</div>`;
    }
  }
}

// ── Detail ──────────────────────────────────────────────────────────────────
export async function fetchText(id) {
  return api(`/api/encounter/texts/${Number(id)}`);
}

// A5：拉逐词注解（annotate 端点）。
export async function fetchAnnotate(id) {
  return api(`/api/encounter/texts/${Number(id)}/annotate`);
}

// 通用"头部 + 正文容器"渲染，返回正文容器（id = enc-reader-body），
// 供纯段落回退与逐 token 高亮两种模式共用。
function renderReaderShell(text, bodyHtml) {
  const rd = readerEl();
  if (!rd) return null;
  rd.innerHTML = `
    <div class="encounter-reader-head">
      <button class="btn btn-ghost btn-sm" onclick="encounterBackToList()">← 返回列表</button>
      <h3>${esc(text.title)}</h3>
      <div class="encounter-reader-source">
        ${esc(text.level || "")} · ${esc(text.source || "来源未知")}
      </div>
    </div>
    <div class="encounter-body" id="enc-reader-body">${bodyHtml}</div>
  `;
  rd.style.display = "block";
  const ls = listEl();
  if (ls) ls.style.display = "none";
  _detailOpen = true;
  return rd;
}

// A4 纯段落回退：无 annotate 数据或已背词集合为空时展示（保留原有正文排版）。
export function renderTextDetail(text) {
  renderReaderShell(text, buildPlainParagraphs(text));
}

// A5：有已背词时，把 annotate 逐 token 高亮 + 覆盖统计行一起渲染。
// deck 为空（本机+server 镜像都无已背词）时回退纯段落并给提示。
export async function renderTextDetailAnnotated(text, annotate) {
  const rd = readerEl();
  if (!rd) return;
  const deck = await resolveDeck();
  const knownSet = buildKnownSet(deck);

  if (!annotate || !annotate.sentences || !annotate.sentences.length) {
    renderTextDetail(text);
    return;
  }

  if (knownSet.size === 0) {
    // 本机 + server 镜像都没有任何已背词 → 纯段落 + 引导提示，不做高亮。
    renderTextDetail(text);
    setCoverage(`<div>本地暂无已背词记录（去背词工作台学几词后回来看高亮）。</div>`);
    return;
  }

  const { sentences, stats } = annotateWithDeck(deck, annotate);
  renderReaderShell(text, `<div class="encounter-flow">${buildAnnotatedBody({ sentences })}</div>`);
  renderCoverage(stats);
}

function renderCoverage(stats) {
  if (!stats) return;
  const total = Number(stats.total_tokens) || 0;
  const known = Number(stats.known_tokens) || 0;
  const rateNum = Number(stats.known_rate) || 0;
  const pct = Math.round(rateNum * 100);
  setCoverage(`已背词覆盖 ${known}/${total} 词位（${pct}%）`);
}

export async function openText(id) {
  try {
    // 拉详情 + 注解（并行）。annotate 失败（如无该文本）会让 Promise.all 整段失败，
    // 落到 catch 提示 —— 文本内容与注解必须同时到齐才能渲染 token 流。
    const [text, annotate] = await Promise.all([
      fetchText(id),
      fetchAnnotate(id),
    ]);
    await renderTextDetailAnnotated(text, annotate);
  } catch (e) {
    const rd = readerEl();
    if (rd) {
      rd.style.display = "block";
      rd.innerHTML = `<div class="encounter-empty">打开短篇失败：${esc(
        e.message || "未知错误",
      )}</div>`;
    }
  }
}

export function backToList() {
  _detailOpen = false;
  hideCoverage();
  const rd = readerEl();
  if (rd) rd.style.display = "none";
  const ls = listEl();
  if (ls) {
    ls.style.display = "";
    fetchTexts().then(renderTextList).catch(() => {});
  }
}

// ── 「＋ 加文本」 local form ─────────────────────────────────────────────────
export function toggleAddForm() {
  const form = document.getElementById("encounter-add-form");
  if (!form) return;
  form.classList.toggle("open");
  const err = document.getElementById("enc-add-error");
  if (err) err.classList.remove("show");
}

export function cancelAdd() {
  const form = document.getElementById("encounter-add-form");
  if (!form) return;
  form.classList.remove("open");
  const err = document.getElementById("enc-add-error");
  if (err) err.classList.remove("show");
  ["enc-f-title", "enc-f-level", "enc-f-source", "enc-f-content"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

export async function submitAddText() {
  const err = document.getElementById("enc-add-error");
  const titleEl = document.getElementById("enc-f-title");
  const levelEl = document.getElementById("enc-f-level");
  const sourceEl = document.getElementById("enc-f-source");
  const contentEl = document.getElementById("enc-f-content");
  if (!err) return;

  const title = (titleEl ? titleEl.value : "").trim();
  const level = (levelEl ? levelEl.value : "A2").toUpperCase();
  const source = (sourceEl ? sourceEl.value : "").trim();
  const content = contentEl ? contentEl.value : "";

  if (!title || !content.trim()) {
    err.textContent = "标题与正文均为必填项。";
    err.classList.add("show");
    return;
  }

  try {
    await api("/api/encounter/texts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, level, source, content }),
    });
    // 成功：清表单、收起、刷新列表（无论当前在列表还是详情态都回列表）。
    err.classList.remove("show");
    if (titleEl) titleEl.value = "";
    if (sourceEl) sourceEl.value = "";
    if (contentEl) contentEl.value = "";
    cancelAdd();
    backToList();
  } catch (e) {
    err.textContent = `添加失败：${e.message || "未知错误"}`;
    err.classList.add("show");
  }
}
