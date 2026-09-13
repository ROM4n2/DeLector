/* DeLector - 遇见区 (Encounter Zone) P0 Skeleton
 *
 * Task A4: curated short-text list + detail reader + local add-text form.
 * Task A5: 已背词 deck 桥 —— 打开短篇时拉 A3 annotate，按本机背词工作台 deck
 *          判定 known，渲染逐 token 高亮 + 覆盖统计（#enc-coverage）。
 * Task A6: 点词弹层（释义）/ 一键进卡（写 deck + wb 镜像同步）/ 读完会话小复习。
 * Views are routed by main.js show() (lazy show-style, no eager DOMContentLoaded
 * work). We only talk to the backend through the shared `api()` fetch wrapper in
 * ./core.js and escape all user-supplied strings with `esc()` before they enter
 * innerHTML — no raw interpolation of untrusted content.
 */
"use strict";

import { api, esc, notify } from "./core.js";
import { playGermanAudio } from "./player.js";
import {
  loadDeck,
  mergeServerDeck,
  annotateWithDeck,
  addCardToDeck,
  DECK_KEYS,
} from "./deck-bridge.js";
import {
  PULL_ENDPOINT,
  normalizeDesktopBase,
  readDesktopBase,
  writeDesktopBase,
  mapPackRows,
  pullPackRequest,
} from "./encounter-pull.js";

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

// ── A6 交互状态 ─────────────────────────────────────────────────────────────
let _popoverBound = false;   // 全局点击/键盘代理只绑一次
let _sentTexts = [];         // 每句还原文本（按 data-si 索引，供 /api/lookup/vocab 用）
let _sessionAdded = [];      // 本次 openText 会话已加入的词 {hw, gloss, pos}
let _sessionSyncOk = true;   // 本会话 wb 镜像同步是否全部成功（失败要在复习区记录）
let _pending = null;         // 弹层当前词 {lemma, surface, pos, gloss, sentence, known}

function popoverEl() {
  return document.getElementById("enc-popover");
}
function reviewEl() {
  return document.getElementById("enc-review");
}
function reviewToggleEl() {
  return document.getElementById("enc-review-toggle");
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

// A6：是否为可点「生词候选」token（与 deck-bridge 的 isLemmaCandidate 口径一致）：
// 真正的单词（pos 非标点/符号、含字母），且当前判定未学（known=false）。
function isTapCandidate(tok) {
  if (!tok) return false;
  const text = String(tok.text == null ? "" : tok.text);
  const pos = String(tok.pos || "").toUpperCase();
  if (["PUNCT", "SYM", "SPACE"].some((p) => pos.startsWith(p))) return false;
  if (!/[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]/.test(text)) return false;
  return !tok.known;
}

// A6：单句 token 流 → 表面文本（供 /api/lookup/vocab 的 sentence 参数用，
// 标点/闭引前不补空格，与渲染空隙规则一致）。
function sentenceSurface(tokens) {
  let s = "";
  const arr = Array.isArray(tokens) ? tokens : [];
  for (let i = 0; i < arr.length; i++) {
    const t = arr[i];
    const text = String(t == null || t.text == null ? "" : t.text);
    if (i > 0 && !LEADING_PUNCT_RE.test(text)) s += " ";
    s += text;
  }
  return s;
}

// A5：把注解句子渲染成"每 token 一个 span"的流动正文，join 用单空格但
// 标点/闭引前不加前置空格、句首 token 无前置空格；句子间补一个空格。
// A6：未知生词 span 加 .enc-unk + data-*（si/lemma/text/pos），供点击事件
//     委托打开释义弹层；并把每句还原文本写入 _sentTexts[s.idx]（lookup 用）。
function buildAnnotatedBody(annotate) {
  return (annotate.sentences || [])
    .map((s) => {
      const toks = s.tokens || [];
      const si = s && s.idx != null ? s.idx : 0;
      _sentTexts[si] = sentenceSurface(toks);
      let html = "";
      for (let i = 0; i < toks.length; i++) {
        const tok = toks[i];
        const text = String(tok == null || tok.text == null ? "" : tok.text);
        const lemma = String(tok == null || tok.lemma == null ? "" : tok.lemma);
        const pos = String(tok == null || tok.pos == null ? "" : tok.pos);
        if (i > 0 && !LEADING_PUNCT_RE.test(text)) html += " ";
        let cls = "enc-tok";
        if (tok && tok.known) cls += " enc-known";
        else if (isTapCandidate(tok)) cls += " enc-unk";
        html += `<span class="${cls}" data-si="${si}" data-lemma="${esc(
          lemma,
        )}" data-text="${esc(text)}" data-pos="${esc(pos)}" role="button" tabindex="-1">${esc(
          text,
        )}</span>`;
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
    // ⑦ 修复：POST /texts 是 _require_localhost 本机闸，手机/局域网端点击只会 403。
    // 空态文案不再把手机用户往死路引导，注明「添加仅限运行服务的电脑本机」。
    el.innerHTML =
      '<div class="encounter-empty">遇见区暂无短篇 —— 可在电脑本机点右上「＋ 加文本」添加（手机/平板端只能阅读与背词）。</div>';
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
  resetSessionReview();
  closePopover();
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
// A6：即使本机/镜像都没有已背词（knownSet 空），也照常渲染 token 流 ——
//     此时每个词都算「未学」，都带 .enc-unk 可点 → 走 A6 一键进卡。
export async function renderTextDetailAnnotated(text, annotate) {
  const rd = readerEl();
  if (!rd) return;
  const deck = await resolveDeck();

  if (!annotate || !annotate.sentences || !annotate.sentences.length) {
    renderTextDetail(text);
    return;
  }

  const { sentences, stats } = annotateWithDeck(deck, annotate);
  renderReaderShell(
    text,
    `<div class="encounter-flow">${buildAnnotatedBody({ sentences })}</div>`,
  );
  renderCoverage(stats);
  showReviewToggleIfNeeded();
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
    // 打开一篇新文本 = 新的阅读会话：小复习列表重置（A6）。
    resetSessionReview();
    ensurePopoverBound();
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
  resetSessionReview();
  closePopover();
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
    // ⑦ 修复：POST /texts 仅在电脑本机放行（_require_localhost）；手机/局域网端
    // 点添加会得到 403「该接口仅允许本机访问」。把死路翻译成人话，别让用户以为坏了。
    const msg = (e && e.message) || "";
    err.textContent = msg.indexOf("仅允许本机") >= 0
      ? "新增短篇仅限运行本服务的电脑本机操作（手机/平板端只能阅读与背词）"
      : `添加失败：${msg || "未知错误"}`;
    err.classList.add("show");
  }
}

/* ======================================================================
 * 从电脑导入（WiFi 内容分发）：「遇见区」拉取桌面货架卡包
 *
 * 架构（ADR-0004 拉取免 key / Plan 全局约束）：Android 实例绑回环，桌面绑
 * 0.0.0.0 天然是货架。手机前端**只**调本机 /api/encounter/pull-pack（同源零跨域），
 * 由手机服务端出站 GET 桌面货架（出站不受监听绑定限制）。前端**绝不**把
 * desktop_base 拼进 fetch()/api() 直连桌面 —— 那是跨域且违背架构（红线）。
 *
 * 流程：入口 → 轻量面板（地址输入，localStorage 记忆）→ 连接电脑 → 列表 →
 * 某包「导入」→ 刷新遇见区列表 → 关闭面板。地址归一/记忆/数据映射的纯逻辑在
 * ./encounter-pull.js（Node 可测）。
 * ==================================================================== */

function pullPanelEl() {
  return document.getElementById("encounter-pull-panel");
}
function pullListEl() {
  return document.getElementById("encounter-pull-list");
}
function pullErrorEl() {
  return document.getElementById("enc-pull-error");
}

/** 本机 localStorage（不可用时 null，记忆读写降级为 no-op）。 */
function encStorage() {
  return typeof window !== "undefined" && window.localStorage
    ? window.localStorage
    : null;
}

/** 面板内小错误行：显示人话错误（后端 detail 或前端校验提示）。 */
function showPullError(msg) {
  const err = pullErrorEl();
  if (!err) return;
  err.textContent = msg || "";
  err.classList.add("show");
}

function clearPullError() {
  const err = pullErrorEl();
  if (!err) return;
  err.classList.remove("show");
  err.textContent = "";
}

/** 打开/关闭「从电脑导入」面板；打开时回填记忆地址。 */
export function togglePullPanel() {
  const panel = pullPanelEl();
  if (!panel) return;
  const opening = !panel.classList.contains("open");
  panel.classList.toggle("open", opening);
  if (opening) {
    clearPullError();
    const input = document.getElementById("enc-pull-base");
    if (input && !input.value) input.value = readDesktopBase(encStorage());
    const list = pullListEl();
    if (list) list.innerHTML = "";
  }
}

export function cancelPull() {
  const panel = pullPanelEl();
  if (panel) panel.classList.remove("open");
  clearPullError();
  const list = pullListEl();
  if (list) list.innerHTML = "";
}

/**
 * 「连接电脑」：把归一后的地址交给本机服务端代理拉取货架清单（本机同源调用）。
 * 成功后渲染包列表；失败把人话 detail 直接提示（后端已中文人话化）。
 */
export async function connectDesktop() {
  const input = document.getElementById("enc-pull-base");
  const btn = document.getElementById("enc-pull-connect");
  const list = pullListEl();
  if (!list) return;
  clearPullError();

  let base;
  try {
    base = normalizeDesktopBase(input ? input.value : "");
  } catch (e) {
    showPullError(e.message || "地址格式不正确");
    return;
  }
  // 记忆归一后的地址，下次自动回填。
  writeDesktopBase(encStorage(), base);

  if (btn) btn.disabled = true;
  list.innerHTML = '<div class="encounter-empty">正在连接电脑…</div>';
  try {
    // ✅ 只调本机相对路径；desktop_base 作为 body 字段交由服务端出站（零跨域）。
    const res = await api(PULL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pullPackRequest(base, null)),
    });
    renderPullPacks(mapPackRows(res && res.packs), base);
  } catch (e) {
    list.innerHTML = "";
    showPullError((e && e.message) || "连接失败");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** 渲染货架包列表（标题 + 等级 + 词数 + 「导入」）；空货架给人话提示。 */
function renderPullPacks(rows, base) {
  const list = pullListEl();
  if (!list) return;
  if (!rows.length) {
    list.innerHTML =
      '<div class="encounter-empty">电脑上还没有可导入的卡包。</div>';
    return;
  }
  list.innerHTML = rows
    .map(
      (r) => `
      <div class="encounter-card enc-pull-row">
        <span class="encounter-badge ${esc(r.level)}">${esc(r.level)}</span>
        <span class="encounter-card-title">${esc(r.title)}</span>
        <span class="encounter-card-meta">${r.word_count} 词</span>
        <button class="btn btn-dark btn-sm enc-pull-import" data-pack-id="${esc(
          r.pack_id,
        )}" data-pack-title="${esc(r.title)}">导入</button>
      </div>
    `,
    )
    .join("");
  list.setAttribute("data-desktop-base", base);
}

/**
 * 导入某包：POST 本机 pull-pack（带 pack_id）→ 幂等落库 → notify + 刷新列表 +
 * 关面板。按钮在请求中禁用防重复点击。
 */
async function importPack(packId, packTitle, btn) {
  const base = (pullListEl() && pullListEl().getAttribute("data-desktop-base")) || "";
  if (!base) {
    showPullError("请先连接电脑");
    return;
  }
  clearPullError();
  const originalText = btn ? btn.textContent : "导入";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "导入中…";
  }
  try {
    await api(PULL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pullPackRequest(base, packId)),
    });
    notify(`已导入：${packTitle}`, { kind: "success" });
    cancelPull();
    await refreshList();
  } catch (e) {
    showPullError((e && e.message) || "导入失败");
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

/** 刷新遇见区列表（复用 fetchTexts/renderTextList；失败静默）。 */
async function refreshList() {
  try {
    renderTextList(await fetchTexts());
  } catch (e) {
    /* 刷新失败不打断：面板已关，用户可手动重进遇见区。 */
  }
}

/** 全局点击代理：面板内「连接/导入」按钮（面板打开时绑一次）。 */
let _pullBound = false;
function ensurePullBound() {
  if (_pullBound) return;
  _pullBound = true;
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (t.closest && t.closest("#enc-pull-connect")) {
      ev.preventDefault();
      connectDesktop();
      return;
    }
    const imp = t.closest ? t.closest(".enc-pull-import") : null;
    if (imp) {
      ev.preventDefault();
      importPack(
        imp.getAttribute("data-pack-id") || "",
        imp.getAttribute("data-pack-title") || "",
        imp,
      );
    }
  });
}

// showView() 进场时保证面板交互已绑（面板 DOM 常驻 index.html）。
ensurePullBound();

/* ======================================================================
 * A6：点词释义弹层 → 一键进卡 → 读完会话小复习
 *
 * 纯 deck 写操作（word/card 对象形状、幂等、learned/exists 判定）都在
 * deck-bridge.js（Node 可测）。本文件只做页面侧编排：
 *   - 点击未知词 → #enc-popover 弹层（复用既有 /api/lookup/vocab 查释义）
 *   - 「加入卡片」→ addCardToDeck + 写回 localStorage(wb.words.v1/cards.v1)
 *      + 触发 PUT /api/wb/state 镜像同步（沿用 workbench 的 payload/key 契约）
 *   - 读完小复习 #enc-review：会话刚加入词翻转 + 🔊 发音（playGermanAudio）
 * ==================================================================== */

function hideReviewUI() {
  const rv = reviewEl();
  if (rv) {
    rv.style.display = "none";
    rv.innerHTML = "";
  }
  const tg = reviewToggleEl();
  if (tg) tg.style.display = "none";
}

function resetSessionReview() {
  _sessionAdded = [];
  _sessionSyncOk = true;
  hideReviewUI();
}

function closePopover() {
  const pop = popoverEl();
  if (pop) pop.classList.remove("open");
  _pending = null;
}

// 复习开关：有会话词时可见；点它把收起的 #enc-review 重新打开/收起。
function showReviewToggleIfNeeded() {
  const tg = reviewToggleEl();
  if (tg) {
    tg.style.display = _sessionAdded.length ? "" : "none";
    tg.textContent = _sessionAdded.length ? `小复习（${_sessionAdded.length}）` : "小复习";
  }
}

function toggleReviewOpen() {
  const rv = reviewEl();
  if (!rv) return;
  const tg = reviewToggleEl();
  const open = rv.style.display !== "none";
  if (open) {
    rv.style.display = "none";
    if (tg) tg.textContent = `小复习（${_sessionAdded.length}）`;
  } else {
    rv.style.display = "";
    if (tg) tg.textContent = "收起小复习";
  }
}

function playSessionWord(hw) {
  if (hw) playGermanAudio(hw);
}

// 渲染小复习列表：行 = word(hw) 正面 / gloss 反面；整行点击翻转；
// 🔊 播放该词发音。gloss 一律 esc，XSS 安全。
function renderSessionReview() {
  const rv = reviewEl();
  if (!rv) return;
  if (!_sessionAdded.length) {
    hideReviewUI();
    return;
  }
  showReviewToggleIfNeeded();
  const rows = _sessionAdded
    .map(
      (w) => `
      <div class="enc-rev-row" data-hw="${esc(w.hw || "")}" data-gloss="${esc(w.gloss || "")}">
        <span class="enc-rev-front">${esc(w.hw)}</span>
        <span class="enc-rev-gloss">${esc(w.gloss || "")}</span>
        <button class="enc-rev-speak" data-enc-speak="${esc(w.hw)}" title="发音">🔊</button>
      </div>
    `,
    )
    .join("");
  rv.innerHTML = `
    <div class="enc-review-head">
      <h4>本篇新词小复习</h4>
      <button class="enc-review-collapse" data-enc-toggle-review>收起</button>
    </div>
    <div class="enc-review-list">${rows}</div>
    ${_sessionSyncOk ? "" : '<div class="enc-review-note">⚠ 服务端镜像同步失败，词卡已安全保存在本机。</div>'}
  `;
  rv.style.display = "";
  const tg = reviewToggleEl();
  if (tg) tg.style.display = "none";
}

// 翻转某复习行 front/back：行自带 data-hw/data-gloss（从 _sessionAdded 渲染时
// 写入，天然 XSS-safe），正点翻到反面看释义，再点翻回词形。
function flipReviewRow(row) {
  const front = row.querySelector(".enc-rev-front");
  const gloss = row.querySelector(".enc-rev-gloss");
  if (!front || !gloss) return;
  const hw = row.getAttribute("data-hw") || "";
  const glossText = row.getAttribute("data-gloss") || "";
  const showingFront = row.getAttribute("data-flipped") !== "1";
  if (showingFront) {
    row.setAttribute("data-flipped", "1");
    front.textContent = glossText || "未收录";
    gloss.textContent = "正面";
  } else {
    row.removeAttribute("data-flipped");
    front.textContent = hw;
    gloss.textContent = glossText || "未收录";
  }
}

// 打开弹层并定位到点词附近；随即用既有词典端点取 gloss（未收录则留空仍可进卡）。
function openPopoverNear(rect, lemma, surface, pos, si) {
  const pop = popoverEl();
  if (!pop) return;
  const sentence = _sentTexts[si] || surface || "";
  _pending = { lemma, surface, pos, sentence, gloss: "", known: false };
  pop.innerHTML = `
    <div class="enc-pop-head">
      <strong>${esc(surface)}</strong>
      ${pos ? `<span class="enc-pop-pos">${esc(pos)}</span>` : ""}
      <button class="enc-pop-close" data-enc-close aria-label="关闭">×</button>
    </div>
    <div class="enc-pop-gloss enc-pop-loading">查词中…</div>
    <button class="btn btn-accent enc-pop-add" disabled>加入卡片</button>
    <div class="enc-pop-status" data-enc-status></div>
  `;
  pop.classList.add("open");
  // fixed 定位到点词下方（视口坐标，getBoundingClientRect 已给出），避免滚出视野。
  const vw = window.innerWidth;
  const left = Math.min(Math.max(8, Math.round(rect.left)), vw - pop.offsetWidth - 8);
  const top = Math.round(rect.bottom + 6);
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
  lookupGloss(_pending);
}

async function lookupGloss(pending) {
  const pop = popoverEl();
  if (!pop || !pending) return;
  const glossEl = pop.querySelector(".enc-pop-gloss");
  const addBtn = pop.querySelector(".enc-pop-add");
  try {
    const res = await api("/api/lookup/vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // 与 reader.js 一致：sentence + target_word + lemma（spaCy 词元，geht→gehen 可命中）
      body: JSON.stringify({
        sentence: pending.sentence,
        target_word: pending.surface,
        lemma: pending.lemma,
      }),
    });
    const def = res && res.definition_zh ? String(res.definition_zh).trim() : "";
    if (def) {
      pending.gloss = def;
      glossEl.classList.remove("enc-pop-loading");
      glossEl.textContent = def;
    } else {
      // 词典未收录：仍鼓励进卡，gloss 留空待背词台补。
      glossEl.classList.remove("enc-pop-loading");
      glossEl.classList.add("enc-pop-none");
      glossEl.textContent = "未收录（仍可加入卡片，释义留空待补）";
    }
  } catch (e) {
    glossEl.classList.remove("enc-pop-loading");
    glossEl.classList.add("enc-pop-none");
    glossEl.textContent = "未收录（词典查询失败，仍可加入卡片）";
  }
  if (addBtn) addBtn.disabled = false;
}

/* ======================================================================
 * ① 修复：进卡「双写」本地持久层 —— localStorage + IndexedDB（vault-team 评审 ①）。
 *
 * 背景：workbench（背词工作台）自 F2 起已把万词库持久化到 IndexedDB（db "wb"，
 * store words/cards/log/wrong/settings/snapshots，单条 key "main"），启动时经
 * idbHydrate 把 IDB 覆盖回 localStorage。本页（encounter）之前进卡只写
 * localStorage——若该 origin 的 localStorage 先被清空/换机恢复，或先跑 workbench
 * 的 idbHydrate（IDB 旧字符串 ≠ localStorage 新串时整键覆盖），新词就丢了。
 *
 * 契约（与 static/german/workbench.html F2 逐字段一致，改须同步）：
 *   库名/版本/store 名/snapshots keyPath 完全一致；words store 单条
 *   {key:"main", value:<word 数组>}。
 *
 * IDB 不可用（私隐模式/低版本）时静默降级为 localStorage-only（返回 false），
 * 绝不抛异常 —— 本页所有写路径都已保证 localStorage 先行成功。
 * ==================================================================== */
const ENC_IDB_STORES = ["words", "cards", "log", "wrong", "settings", "snapshots"];
let _encIdb = null;        // IDBDatabase 实例
let _encIdbReady = false;
let _encIdbFailed = false;

function encIdbOpen() {
  return new Promise((resolve) => {
    if (_encIdbReady && _encIdb) return resolve(_encIdb);
    if (_encIdbFailed) return resolve(null);
    if (typeof indexedDB === "undefined") { _encIdbFailed = true; return resolve(null); }
    try {
      const req = indexedDB.open("wb", 1);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        for (const s of ENC_IDB_STORES) {
          if (!db.objectStoreNames.contains(s)) {
            db.createObjectStore(
              s,
              s === "snapshots" ? { keyPath: "ts", autoIncrement: true } : { keyPath: "key" },
            );
          }
        }
      };
      req.onsuccess = (e) => { _encIdb = e.target.result; _encIdbReady = true; resolve(_encIdb); };
      req.onerror = () => { _encIdbFailed = true; resolve(null); };
    } catch (e) { _encIdbFailed = true; resolve(null); }
  });
}

/** 把整份 words 数组写入 IDB words store（key "main"）。失败静默返回 false。 */
async function encIdbWriteWords(words) {
  const db = await encIdbOpen();
  if (!db) return false;
  try {
    return await new Promise((resolve) => {
      const tx = db.transaction("words", "readwrite");
      tx.objectStore("words").put({ key: "main", value: words });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  } catch (e) { return false; }
}

// 读 wb.pair.v1（配对远端 {host,key}）—— 与 workbench 的 loadPair 同键。
function readWbPair(storage) {
  try {
    const raw = storage && storage.getItem ? storage.getItem("wb.pair.v1") : null;
    if (raw) {
      const p = JSON.parse(raw);
      if (p && p.host && p.key) return { host: p.host, key: p.key };
    }
  } catch (e) {
    /* 解析坏/无 localStorage：按未配对 */
  }
  return null;
}

// best-effort 镜像同步（复用 workbench 的 PUT /api/wb/state + X-WB-Key 契约）：
//   - 端点/密钥：已配对(wb.pair.v1)走 http://<host>/api/wb/state + pair.key；
//     否则本机 /api/wb/state，key 从 GET /api/wb/state/key（127.0.0.1 闸）取一次。
//   - body 沿用 {"payload": {...}}（WbStateReq）；payload 尽量保留 server 镜像里
//     settings/log/wrong，仅用本页拥有权威的 words/cards 覆盖 —— 避免弄丢他设备状态。
//   - ⚠ 跨设备已知局限（YELLOW-2，P0 单设备可接受）：本页 words/cards 是 last-write-wins
//     覆盖远端镜像；Object.assign 保留 server 的 settings/log/wrong 不被冲掉。多设备
//     并发编辑会丢更新（丢字），暂不做双向合并——留待未来 two-way merge。
//   失败静默返回 false（词卡已安全落本机，不阻断阅读）。这是跨页镜像的等价实现，
//   非逐字节复用 workbench wbsync（不同页面、不同 module 边界）。
async function mirrorPushWb(storage, deck) {
  try {
    const pair = readWbPair(storage);
    const endpoint = pair ? "http://" + pair.host + "/api/wb/state" : "/api/wb/state";
    let key = pair ? pair.key : null;
    if (!key) {
      const keyRes = await api("/api/wb/state/key");
      key = keyRes && keyRes.key ? keyRes.key : null;
    }
    if (!key) return false; // 拿不到 key（远端 / 未配对 / 未启动 server）→ 仅本机
    // 保留 server 镜像中非 words/cards 的键（settings/log/wrong 等），防 clobber。
    let snapshot = { words: deck.words, cards: deck.cards };
    try {
      const current = await api(endpoint); // GET server 镜像（局域网无需 key）
      if (current && typeof current === "object" && !Array.isArray(current)) {
        snapshot = Object.assign({}, current, snapshot);
      }
    } catch (e) {
      /* server 空 / 不可达：只用本页 snapshot */
    }
    await api(endpoint, {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-WB-Key": key },
      body: JSON.stringify({ payload: snapshot }),
    });
    return true;
  } catch (e) {
    _sessionSyncOk = false;
    return false;
  }
}

// 一键进卡：读本机 deck → addCardToDeck → 写回 wb.words.v1（只写词、不写卡）→
// 触发镜像同步 → 记入会话小复习。added=false（exists/learned）给用户原因。
// RED-1：进卡只加词（word），**绝不写卡** —— 让工作台 !S.cards[w.id]「新词」语义成立。
async function handleAddCard() {
  const p = _pending;
  const pop = popoverEl();
  if (!p || !pop) return;
  const addBtn = pop.querySelector(".enc-pop-add");
  const statusEl = pop.querySelector("[data-enc-status]");
  if (addBtn) addBtn.disabled = true;
  const storage =
    typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  try {
    const deck = loadDeck(storage);
    const res = addCardToDeck(deck, p.lemma, {
      gloss: p.gloss,
      pos: p.pos,
      nowMs: Date.now(),
    });
    if (res.added) {
      try {
        // 只写 words 回 wb.words.v1；cards 不加任何键，让新词保持「未排新词」。
        storage.setItem(DECK_KEYS.words, JSON.stringify(res.deck.words));
      } catch (e) {
        /* 存储满/隐私模式：进卡失败提示，不静默吞 */
        if (statusEl) {
          statusEl.textContent = "加入失败：本地存储不可用";
          statusEl.classList.add("err");
          if (addBtn) addBtn.disabled = false;
        }
        return;
      }
      // ① 修复：双写 IndexedDB（与 workbench F2 同库同 key "main"）——手机/离线
      // 场景下 localStorage 清空或 idbHydrate 覆盖后新词仍可从 IDB 找回。
      // IDB 失败只静默降级（localStorage 已成功），绝不影响下面的镜像同步与反馈。
      await encIdbWriteWords(res.deck.words);
      // 写 deck 成功即触发镜像同步（best-effort，成败不影响本地落卡）。
      await mirrorPushWb(storage, res.deck);
      _sessionAdded.push({ hw: p.lemma, gloss: p.gloss, pos: p.pos, surface: p.surface });
      renderSessionReview();
      if (statusEl) {
        statusEl.textContent = "已加入背词库";
        statusEl.classList.add("ok");
      }
      if (addBtn) addBtn.textContent = "已加入";
    } else {
      const reasonText =
        res.reason === "learned" ? "该词已学习，无需再加入" : "该词已在背词库中";
      if (statusEl) {
        statusEl.textContent = reasonText;
        statusEl.classList.add("ok");
      }
      if (addBtn) addBtn.disabled = true;
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = `加入失败：${e.message || "未知错误"}`;
      statusEl.classList.add("err");
    }
    if (addBtn) addBtn.disabled = false;
  }
}

// 点词事件入口：从被点的 token span 取 lemma/text/pos/si，打开弹层。
function openPopoverFromToken(el) {
  const lemma = el.getAttribute("data-lemma") || "";
  const text = el.getAttribute("data-text") || lemma;
  const pos = el.getAttribute("data-pos") || "";
  const siRaw = el.getAttribute("data-si");
  const si = siRaw != null && siRaw !== "" ? Number(siRaw) : 0;
  if (!lemma) return;
  const rect = el.getBoundingClientRect();
  openPopoverNear(rect, lemma, text, pos, si);
}

// 全局点击/键盘代理：只绑一次（_popoverBound）。各 A6 交互元素都走这里，
// 不新增 window hook（避免动 main.js 的 exposer 与模块图）。
function ensurePopoverBound() {
  if (_popoverBound) return;
  _popoverBound = true;

  document.addEventListener("click", (ev) => {
    const target = ev.target;
    // 关闭按钮
    if (target.closest && target.closest("[data-enc-close]")) {
      ev.preventDefault();
      closePopover();
      return;
    }
    // 「加入卡片」
    if (target.closest && target.closest(".enc-pop-add")) {
      ev.preventDefault();
      handleAddCard();
      return;
    }
    // 复习列表收起/重开按钮（面板头）→ 折叠面板，露出小复习开关
    if (target.closest && target.closest("[data-enc-toggle-review]")) {
      ev.preventDefault();
      const rv = reviewEl();
      if (rv) rv.style.display = "none";
      const tg = reviewToggleEl();
      if (tg) tg.textContent = `小复习（${_sessionAdded.length}）`;
      return;
    }
    // 小复习开关按钮 → 重开面板
    if (target.closest && target.closest("#enc-review-toggle")) {
      ev.preventDefault();
      toggleReviewOpen();
      return;
    }
    // 🔊 发音
    if (target.closest && target.closest("[data-enc-speak]")) {
      ev.preventDefault();
      const hw = target.closest("[data-enc-speak]").getAttribute("data-enc-speak");
      playSessionWord(hw);
      return;
    }
    // 复习行整行翻转（但不响应 🔊 子按钮，上面已拦）
    const revRow = target.closest ? target.closest(".enc-rev-row") : null;
    if (revRow) {
      flipReviewRow(revRow);
      return;
    }
    // 点未知生词 span → 打开弹层
    const tok = target.closest ? target.closest(".enc-unk") : null;
    if (tok) {
      ev.preventDefault();
      openPopoverFromToken(tok);
      return;
    }
    // 点弹层以外 → 收起
    const pop = popoverEl();
    if (pop && pop.classList.contains("open") && !pop.contains(target)) {
      closePopover();
    }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closePopover();
  });
}
