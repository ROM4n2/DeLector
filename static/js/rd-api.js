/* DeLector - Reader Desk: 持久化访问层（L2）
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制；见
 * docs/plans/2026-10-19-reader-api-layer-split.md Task 2）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage /
 *   getElementById / querySelector / innerHTML / addEventListener）；
 *   MUST NOT 弹用户提示（notify / alert / confirm）—— 失败怎么呈现是视图层的事；
 *   MUST NOT 用计时器（setTimeout / setInterval）。
 *   MUST NOT 声明顶层 let/var 可变模块状态。
 *   唯一允许的 import 仅限 ./core.js 的 api()。
 *
 * 每个函数 = 一个端点，返回 api() 的原样 Promise 结果，不做任何加工、不吞异常。
 * 错误轨保持逐字交给调用方（零静默失败），本层只负责「路径 + 方法 + 载荷」契约。
 */
'use strict';

import { api } from './core.js';

// ── 文章 CRUD ─────────────────────────────────────────────────────────────
export async function removeArticle(id) {
  return api('/api/articles/' + id, { method: 'DELETE' });
}

export async function fetchArticles() {
  return api('/api/articles');
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
