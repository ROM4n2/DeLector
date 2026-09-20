/* DeLector - 全文检索视图 (Suche)
 *
 * 跨域检索控制器：词条 / 例句 / 搭配 / 语料 四组结果。
 * 挂载于主站 view-search（index.html #view-search），main.js `import * as Search`
 * 命名空间接线（参照 HardSentences / ListenLab 先例）。
 *
 * 后端契约（delector/routes/search.py，字段名逐字一致 —— 红线 11）：
 *   GET /api/search?q=&scope=&limit=
 *     → {q, scope, total, groups:{vocab,example,colloc,corpus}, groups_total, truncated}
 *   - groups_total[k]：第 k 组在 limit 截断前的命中条数（截断语义拆分，Task 6）。
 *     组被 limit 截断（groups_total[k] > groups[k].length）时在组尾追加信息提示。
 *   - truncated：**仅**表示「语料 hard cap 未扫完」这一真异常（limit 限量不计入）。
 *   - groups.vocab[]   : {hw, lemma, pos, cefr, fields:{hw,def_zh}, payload:{cefr,pos,gender,plural}}
 *   - groups.example[] : {lemma, hw, fields:{example_de,example_zh}, payload:{ipa}}
 *   - groups.colloc[]  : {lemma, fields:{prep,case,colloc_zh,example_de}, payload:{prep,case}}
 *   - groups.corpus[]  : {pos:source, cefr:level, payload:{source,ref_id,title,level,snippet}}
 *
 * 硬纪律（spec §3.4/§4）：
 *   - 所有展示字段一律经 esc()（或经先 esc 后包 <mark> 的 _highlight）；绝不 innerHTML
 *     直插未转义数据 —— 查询串含 `<script>` 时不得注入（XSS 守卫）。
 *   - 输入 ≥2 字符触发、300ms 防抖；范围分段控件状态**不持久化**（与工作台同纪律）。
 *   - 复用既有入口：🔊 playGermanAudio · 「+ 加入 FSRS 盒」saveA1WordToDeck ·
 *     语料跳转 openReader(article) / openText(encounter)。
 *   - file:// 直开或端点缺失（fetch 失败/非 JSON）→ try/catch 降级为「检索不可用」，
 *     不影响其它功能（详情见 _runSearch）。
 */
"use strict";

import { api, esc, notify } from "./core.js";
import { playGermanAudio } from "./player.js";
import { saveA1WordToDeck } from "./a1_cards.js";
import { openReader } from "./reader.js";
import { openText } from "./encounter.js";

/* ── 常量 ─────────────────────────────────────────────────────────────────── */

// 范围分段控件五值（与 routes/search.py::_VALID_SCOPES 白名单逐字一致；非法值后端 400）。
const _SCOPES = ["all", "vocab", "example", "colloc", "corpus"];

// 四组固定序 = spec §3.2 的 kind 序（DOM 分组容器的静态序同此；组标题在 index.html）。
const _GROUP_ORDER = ["vocab", "example", "colloc", "corpus"];

const _DEBOUNCE_MS = 300; // 输入防抖（spec §2）
const _MIN_Q = 2; // ≥2 字符才检索（与后端 fold(q) 长度守卫一致）
const _LIMIT = 20; // 单组上限（spec §3.3 默认值）

/* ── 会话状态（不持久化） ─────────────────────────────────────────────────── */
const _s = {
  q: "",
  scope: "all",
  seq: 0, // 请求序号：丢弃过期响应（输入快速变化时的竞态）
  // 最近一次响应按 kind 分组的结果，供 🔊/进卡/跳转按 (kind,index) 回查（不塞进 onclick）
  results: { vocab: [], example: [], colloc: [], corpus: [] },
  styled: false,
  bound: false,
};

/* ── 工具 ─────────────────────────────────────────────────────────────────── */

function el(id) {
  return document.getElementById(id);
}

/* ── 样式注入（Academic Modern Editorial token · 复用既有设计系统，不另起一套） ── */
function _ensureStyle() {
  if (_s.styled || el("search-view-style")) return;
  _s.styled = true;
  const style = document.createElement("style");
  style.id = "search-view-style";
  style.textContent = `
#view-search { background: var(--paper-warm); }
.search-panel { max-width: 60rem; margin: 0 auto; }
.search-bar { margin-bottom: 0.75rem; }
.search-input { width:100%; min-height:46px; padding:0.6rem 0.9rem; border:1.5px solid var(--ink); border-radius:8px; background:var(--paper-card); color:var(--ink); font-size:1rem; font-family:var(--serif-body, var(--mono)); }
.search-input:focus { outline:none; box-shadow:0 0 0 3px var(--hl-A2); }
.search-scope-bar { display:flex; flex-wrap:wrap; gap:0.4rem; margin-bottom:0.75rem; }
.search-scope-btn.active { background:var(--ink); color:var(--paper); border-color:var(--ink); }
.search-status { font-family:var(--mono); font-size:0.75rem; color:var(--pencil); min-height:1.2em; margin-bottom:0.75rem; }
.search-group { margin-bottom:1.4rem; }
.search-group.hidden { display:none; }
.search-group-head { font-family:var(--serif-heading); font-size:1rem; font-weight:700; color:var(--ink); border-bottom:1.5px solid var(--ink); padding-bottom:0.25rem; margin-bottom:0.6rem; }
.search-item { border:1.5px solid var(--rule); border-radius:8px; background:var(--paper-card); padding:0.6rem 0.8rem; margin-bottom:0.5rem; }
.search-item-head { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; }
.search-hw { font-weight:700; font-size:1.0625rem; color:var(--ink); }
.search-pos, .search-cefr, .search-corpus-tag { font-family:var(--mono); font-size:0.6875rem; color:var(--pencil); border:1px solid var(--rule); border-radius:999px; padding:0.1rem 0.45rem; }
.search-def { color:var(--ink); margin-top:0.3rem; }
.search-ex-de { color:var(--ink); margin-top:0.3rem; }
.search-ex-zh { color:var(--pencil); font-size:0.875rem; margin-top:0.15rem; }
.search-colloc-head { font-weight:700; color:var(--coral); }
.search-title { font-weight:600; color:var(--ink); }
.search-snippet { color:var(--pencil); font-size:0.875rem; margin-top:0.35rem; line-height:1.6; }
.search-snippet-empty { font-style:italic; color:var(--ink-faint); }
.search-item-corpus { cursor:pointer; }
.search-item-corpus:hover { border-color:var(--coral); box-shadow:var(--shadow-sm); }
.search-item mark { background:var(--hl-A2); color:inherit; padding:0 0.1rem; border-radius:2px; }
.search-empty { text-align:center; padding:2rem 1rem; color:var(--pencil); font-size:0.9375rem; }
.search-group-more { font-family:var(--mono); font-size:0.75rem; color:var(--pencil); padding:0.25rem 0.1rem 0; }
`;
  (document.head || document.documentElement).appendChild(style);
}

/* ── 命中高亮：先 esc() 再包 <mark>（XSS 守卫 —— 顺序不可颠倒） ────────────────
 * 原文与查询串都先 esc()，再在**已转义串**上做大小写不敏感的子串定位；切片索引
 * 在同一个已转义串上计算，故两串无论是否含 & < > 都保持对齐。查询串含
 * `<script>` 时 esc 后成为 `&lt;script&gt;`，包进 <mark> 也只是纯文本。 */
function _highlight(text, q) {
  const safe = esc(text == null ? "" : String(text));
  const needle = String(q == null ? "" : q).trim();
  if (!needle) return safe;
  const safeNeedle = esc(needle);
  if (!safeNeedle) return safe;
  const hay = safe.toLowerCase();
  const target = safeNeedle.toLowerCase();
  let out = "";
  let from = 0;
  let idx = hay.indexOf(target, from);
  while (idx !== -1) {
    out += safe.slice(from, idx) + "<mark>" + safe.slice(idx, idx + safeNeedle.length) + "</mark>";
    from = idx + safeNeedle.length;
    idx = hay.indexOf(target, from);
  }
  return out + safe.slice(from);
}

/* ── 防抖 ─────────────────────────────────────────────────────────────────── */
function _debounce(fn, ms) {
  let timer = null;
  return function debounced(...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(this, args);
    }, ms);
  };
}

const _debouncedRun = _debounce(() => _runSearch(), _DEBOUNCE_MS);

/* ── 状态条 / 空态 ────────────────────────────────────────────────────────── */

function _setStatus(text) {
  const s = el("search-status");
  if (s) s.innerHTML = esc(text);
}

function _clearGroups() {
  for (const kind of _GROUP_ORDER) {
    const sec = el("search-group-sec-" + kind);
    if (sec) sec.classList.add("hidden");
    const body = el("search-group-" + kind);
    if (body) body.innerHTML = "";
  }
}

function _renderEmpty(message) {
  _clearGroups();
  const empty = el("search-empty");
  if (empty) empty.innerHTML = `<div class="search-empty-text">${esc(message)}</div>`;
}

/* ── 各组条目渲染 ─────────────────────────────────────────────────────────── */

function _vocabHtml(item, index, q) {
  const payload = item.payload || {};
  const fields = item.fields || {};
  const hw = item.hw || item.lemma || "";
  const pos = item.pos || payload.pos || "";
  const cefr = item.cefr || payload.cefr || "";
  const defZh = fields.def_zh || "";
  return `<div class="search-item search-item-vocab">
    <div class="search-item-head">
      <span class="search-hw">${_highlight(hw, q)}</span>
      ${pos ? `<span class="search-pos">${esc(pos)}</span>` : ""}
      ${cefr ? `<span class="search-cefr">${esc(cefr)}</span>` : ""}
      <button class="btn btn-ghost btn-xs search-audio-btn" onclick="Search.playResult('vocab', ${index})" title="朗读词头">🔊</button>
      <button class="btn btn-ghost btn-xs search-add-btn" onclick="Search.addVocab(${index}, this)">+ 加入 FSRS 盒</button>
    </div>
    ${defZh ? `<div class="search-def">${_highlight(defZh, q)}</div>` : ""}
  </div>`;
}

function _exampleHtml(item, index, q) {
  const fields = item.fields || {};
  const de = fields.example_de || "";
  const zh = fields.example_zh || "";
  if (!de && !zh) return "";
  return `<div class="search-item search-item-example">
    <div class="search-item-head">
      <span class="search-pos">${_highlight(item.lemma || "", q)}</span>
      <button class="btn btn-ghost btn-xs search-audio-btn" onclick="Search.playResult('example', ${index})" title="朗读德文例句">🔊</button>
    </div>
    ${de ? `<div class="search-ex-de">${_highlight(de, q)}</div>` : ""}
    ${zh ? `<div class="search-ex-zh">${_highlight(zh, q)}</div>` : ""}
  </div>`;
}

function _collocHtml(item, index, q) {
  const fields = item.fields || {};
  const lemma = item.lemma || item.hw || "";
  const head = [lemma, fields.prep || "", fields.case || ""].filter(Boolean).join(" ");
  const zh = fields.colloc_zh || "";
  const ex = fields.example_de || "";
  return `<div class="search-item search-item-colloc">
    <div class="search-item-head">
      <span class="search-colloc-head">${_highlight(head, q)}</span>
      <button class="btn btn-ghost btn-xs search-audio-btn" onclick="Search.playResult('colloc', ${index})" title="朗读搭配例句">🔊</button>
    </div>
    ${zh ? `<div class="search-def">${_highlight(zh, q)}</div>` : ""}
    ${ex ? `<div class="search-ex-de">${_highlight(ex, q)}</div>` : ""}
  </div>`;
}

function _corpusHtml(item, index, q) {
  const payload = item.payload || {};
  const fields = item.fields || {};
  const title = payload.title || fields.title || "";
  const snippet = payload.snippet || "";
  const tag = payload.source === "encounter" ? "遇见区短文" : "语料文章";
  // snippet 为空 = title-only 命中（T2 CRV Y8：正文无该串，仅标题命中）→ 不渲染空片段，
  // 显式提示「仅标题匹配」而不是留一块空白（用户会以为坏了）。
  const body = snippet
    ? `<div class="search-snippet">${_highlight(snippet, q)}</div>`
    : `<div class="search-snippet search-snippet-empty">仅标题匹配（正文无命中片段）</div>`;
  return `<div class="search-item search-item-corpus" onclick="Search.openCorpusResult(${index})" role="button" tabindex="0">
    <div class="search-item-head">
      <span class="search-corpus-tag">${esc(tag)}</span>
      <span class="search-title">${_highlight(title, q)}</span>
    </div>
    ${body}
  </div>`;
}

function _itemHtml(kind, item, index, q) {
  if (kind === "vocab") return _vocabHtml(item, index, q);
  if (kind === "example") return _exampleHtml(item, index, q);
  if (kind === "colloc") return _collocHtml(item, index, q);
  return _corpusHtml(item, index, q);
}

/* ── 渲染四组（对外导出，供 main.js / 探针调用） ───────────────────────────── */

export function renderSearchGroups(resp) {
  const data = resp || {};
  const groups = data.groups || {};
  const groupsTotal = data.groups_total || {};
  const q = data.q || _s.q;
  const scope = data.scope || _s.scope;
  const total = Number(data.total) || 0;

  _s.results = { vocab: [], example: [], colloc: [], corpus: [] };
  let shown = 0;
  let rendered = false;

  for (const kind of _GROUP_ORDER) {
    const items = Array.isArray(groups[kind]) ? groups[kind] : [];
    _s.results[kind] = items;
    shown += items.length;
    const sec = el("search-group-sec-" + kind);
    const body = el("search-group-" + kind);
    if (!body) continue;
    if (!items.length) {
      if (sec) sec.classList.add("hidden");
      body.innerHTML = "";
      continue;
    }
    rendered = true;
    if (sec) sec.classList.remove("hidden");
    let html = items.map((it, i) => _itemHtml(kind, it, i, q)).join("");
    // limit 每组限量是**正常**现象（几乎总发生）→ 组尾给**信息性**提示，而非全局警告。
    // 仅当该组截断前命中数 > 当前展示条数时出现；展示值仍走 esc()。
    const groupTotal = Number(groupsTotal[kind]) || 0;
    if (groupTotal > items.length) {
      html += `<div class="search-group-more">仅显示前 ${esc(items.length)} 条（命中 ${esc(groupTotal)}）</div>`;
    }
    body.innerHTML = html;
  }

  if (!rendered) {
    _renderEmpty(`未找到与「${q}」匹配的结果（范围：${scope}）`);
    _setStatus("");
    return;
  }

  const empty = el("search-empty");
  if (empty) empty.innerHTML = "";
  const parts = [`共 ${total} 条命中`];
  if (shown !== total) parts.push(`当前展示 ${shown} 条`);
  // truncated 仅表示「语料 hard cap 未扫完」这一真异常（limit 限量走组尾信息提示）。
  if (data.truncated) parts.push("⚠ 部分语料未扫描完");
  _setStatus(parts.join(" · "));
}

/* ── 检索请求 ─────────────────────────────────────────────────────────────── */

async function _runSearch() {
  const q = _s.q;
  if (q.trim().length < _MIN_Q) {
    _renderEmpty("输入至少 2 个字符开始检索（词条 / 例句 / 搭配 / 语料）");
    _setStatus("");
    return;
  }
  const seq = ++_s.seq;
  _setStatus("⏳ 检索中…");
  try {
    const params = new URLSearchParams({ q, scope: _s.scope, limit: String(_LIMIT) });
    const resp = await api(`/api/search?${params.toString()}`);
    if (seq !== _s.seq) return; // 已有更新请求发出，丢弃本次过期响应
    renderSearchGroups(resp);
  } catch (e) {
    if (seq !== _s.seq) return;
    // 端点缺失（旧前端 + 新后端错位）/ file:// 直开 / 网络异常：降级提示，不白屏、不抛。
    _renderEmpty("检索不可用：需本地服务（请通过本地服务打开，而非 file:// 直开）");
    _setStatus("");
    console.debug("[Search] /api/search 不可用:", e);
  }
}

/* ── 范围切换（状态不持久化） ─────────────────────────────────────────────── */

export function setSearchScope(scope) {
  if (!_SCOPES.includes(scope)) return;
  _s.scope = scope;
  document.querySelectorAll("#search-scope-bar .search-scope-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.scope === scope);
  });
  if (_s.q.trim().length >= _MIN_Q) _runSearch();
}

/* ── 行内动作：发音 / 进卡 / 语料跳转 ─────────────────────────────────────── */

export function playResult(kind, index) {
  const item = (_s.results[kind] || [])[index];
  if (!item) return;
  const fields = item.fields || {};
  const payload = item.payload || {};
  let text = "";
  if (kind === "vocab") text = item.hw || item.lemma || "";
  else if (kind === "example") text = fields.example_de || "";
  else if (kind === "colloc") text = fields.example_de || item.lemma || "";
  else text = payload.title || "";
  if (!text) return;
  playGermanAudio(text).catch(() => notify("语音引擎不可用", { kind: "error" }));
}

export async function addVocab(index, btn) {
  const item = (_s.results.vocab || [])[index];
  if (!item) return;
  const payload = item.payload || {};
  const fields = item.fields || {};
  const lemma = item.lemma || item.hw || "";
  const hw = item.hw || lemma;
  // 复用既有进卡入口（a1_cards.js 的 saveA1WordToDeck → POST /api/cards/vocab）：
  // 不在此自造写库逻辑，payload 形状完全由该函数持有。
  await saveA1WordToDeck(
    lemma,
    hw,
    item.pos || payload.pos || "WORT",
    payload.gender || "",
    payload.plural || "",
    fields.def_zh || "",
    "",
    "",
    btn,
  );
}

export function openCorpusResult(index) {
  const item = (_s.results.corpus || [])[index];
  if (!item) return;
  const payload = item.payload || {};
  const refId = Number(payload.ref_id);
  if (!refId) return;
  if (payload.source === "encounter") {
    // 遇见区短文：先切视图（show 同时点亮导航），再打开详情。
    if (window.show) window.show("encounter");
    openText(refId);
  } else {
    // 语料文章：openReader 内部会 window.show('reader') 并渲染。
    openReader(refId);
  }
}

/* ── 视图初始化（幂等；main.js show('search') 调用） ──────────────────────── */

export function initSearch() {
  _ensureStyle();
  const input = el("search-input");
  if (input && !_s.bound) {
    _s.bound = true;
    input.addEventListener("input", () => {
      _s.q = input.value || "";
      _debouncedRun();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") _runSearch();
    });
  }
  if (input) _s.q = input.value || ""; // 输入框状态仅镜像 DOM，不持久化
  if (_s.q.trim().length < _MIN_Q) {
    _renderEmpty("输入至少 2 个字符开始检索（词条 / 例句 / 搭配 / 语料）");
    _setStatus("");
  }
}
