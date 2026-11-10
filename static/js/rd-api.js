/* DeLector - Reader Desk: 持久化访问层（L2）
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制；见
 * docs/plans/archive/2026-10-19-reader-api-layer-split.md Task 2）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage /
 *   getElementById / querySelector / innerHTML / addEventListener）；
 *   MUST NOT 弹用户提示（notify / alert / confirm）—— 失败怎么呈现是视图层的事；
 *   MUST NOT 用计时器（setTimeout / setInterval）。
 *   MUST NOT 声明顶层 let/var 可变模块状态。
 *   唯一允许的 import 仅限 ./core.js 的 api()。
 *
 * 每个端点函数 = 一个端点，返回 api() 的原样 Promise 结果，不做任何加工、不吞异常。
 * 错误轨保持逐字交给调用方（零静默失败），本层只负责「路径 + 方法 + 载荷」契约。
 * 另允许纯判定辅助函数（vocabSaveOutcome / vocabSaveNotice）：不加工响应体、
 * 不碰 DOM/提示/计时器；视图层据此决定文案与庆祝动画，避免 5 个存卡入口各写一份判定。
 */
'use strict';

import { api } from './core.js';

// ── 文章 CRUD ─────────────────────────────────────────────────────────────
export async function removeArticle(id) {
  return api('/api/articles/' + id, { method: 'DELETE' });
}

export async function fetchArticles(opts) {
  return api('/api/articles', opts);
}

export async function fetchArticle(id) {
  return api('/api/articles/' + id);
}

// ── 查词与语法分析 ─────────────────────────────────────────────────────────
export async function lookupVocab(payload) {
  return api('/api/lookup/vocab', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function lookupGrammar(payload) {
  return api('/api/lookup/grammar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

// ── 卡片保存 ───────────────────────────────────────────────────────────────
export async function saveVocabCard(payload) {
  return api('/api/cards/vocab', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

/** 把 POST /api/cards/vocab 的响应折成视图层可判定的结果（纯函数，不改响应体）。
 *
 *  字段缺失（后端仍是旧版，或离线壳/代理截断新字段）一律按「首次新增」处理：
 *  改动前的行为逐字保留，前端因而可以先于后端契约合入而不产生回归。
 */
export function vocabSaveOutcome(res) {
  const created = !(res && res.created === false);
  const skippedFields = (res && Array.isArray(res.skipped_fields)) ? res.skipped_fields : [];
  return { created, skippedFields };
}

/** 幂等命中时给用户的解释文案；首次新增返回空串（调用方据此决定是否提示）。 */
export function vocabSaveNotice(outcome) {
  if (!outcome || outcome.created) return '';
  return outcome.skippedFields && outcome.skippedFields.length
    ? '这个词已在词卡中，本次填写未覆盖原有释义'
    : '这个词已经在词卡里，未重复添加';
}

export async function saveGrammarCard(payload) {
  return api('/api/cards/grammar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function fetchCardCounts() {
  return api('/api/cards/counts');
}

/** 抽屉复习台账：按 lemma 取「代表卡」与卡数（只读，后端已做确定性去重）。
 *  lemma 走路径参数：网络层闸门要求 `api()` 路径可静态归一，query 串无法对账。 */
export async function fetchVocabLedger(lemma) {
  const key = encodeURIComponent(String(lemma || '').trim());
  if (!key) return { lemma: '', card_count: 0, card: null };
  return api(`/api/cards/vocab/ledger/${key}`);
}

// ── 笔记系统 ───────────────────────────────────────────────────────────────
export async function fetchArticleNotes(articleId) {
  return api(`/api/articles/${articleId}/notes`);
}

export async function saveArticleNote(articleId, payload) {
  return api(`/api/articles/${articleId}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function removeNote(noteId) {
  return api(`/api/notes/${noteId}`, { method: 'DELETE' });
}

export async function fetchNoteAssist(payload) {
  return api('/api/ai/note-assist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

// ── 句法雷达 ───────────────────────────────────────────────────────────────
export async function saveSyntaxStats(payload) {
  return api('/api/syntax/stats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function fetchSyntaxStats() {
  return api('/api/syntax/stats');
}
