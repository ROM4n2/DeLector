/* DeLector - 遇见区 (Encounter Zone) P0 Skeleton
 *
 * Task A4: curated short-text list + detail reader + local add-text form.
 * Views are routed by main.js show() (lazy show-style, no eager DOMContentLoaded
 * work). We only talk to the backend through the shared `api()` fetch wrapper in
 * ./core.js and escape all user-supplied strings with `esc()` before they enter
 * innerHTML — no raw interpolation of untrusted content.
 */
"use strict";

import { api, esc } from "./core.js";

// ── Internal routing state ──────────────────────────────────────────────────
// The view has two sub-states: the curated list (default) and the detail reader.
let _detailOpen = false;

function listEl() {
  return document.getElementById("encounter-text-list");
}
function readerEl() {
  return document.getElementById("encounter-reader");
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

export function renderTextDetail(text) {
  const rd = readerEl();
  if (!rd) return;
  const paragraphs = String(text.content || "")
    .split(/\n\s*\n/)
    .filter((p) => p.trim().length > 0);
  const body = paragraphs
    .map((p) => `<p>${esc(p.trim())}</p>`)
    .join("");
  rd.innerHTML = `
    <div class="encounter-reader-head">
      <button class="btn btn-ghost btn-sm" onclick="encounterBackToList()">← 返回列表</button>
      <h3>${esc(text.title)}</h3>
      <div class="encounter-reader-source">
        ${esc(text.level || "")} · ${esc(text.source || "来源未知")}
      </div>
    </div>
    <div class="encounter-body">${body}</div>
  `;
  rd.style.display = "block";
  const ls = listEl();
  if (ls) ls.style.display = "none";
  _detailOpen = true;
}

export async function openText(id) {
  try {
    const text = await fetchText(id);
    renderTextDetail(text);
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
