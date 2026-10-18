/* DeLector - Writing Desk: 持久化访问层（L2）
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制；见
 * docs/plans/2026-10-19-writer-js-modularization.md Task 3）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage /
 *   getElementById / querySelector / innerHTML / addEventListener）；
 *   MUST NOT 弹用户提示（notify / alert / confirm）—— 失败怎么呈现是**视图层**的事，
 *   MUST NOT 用计时器（setTimeout / setInterval）。唯一允许的 import 是 ./core.js 的 api()。
 *
 * 每个函数 = 一个端点，**返回 api() 的原样结果**，不做任何加工、不吞异常。
 * 这样调用方的 catch / notify 错误轨保持逐字不变（零静默失败），本层只负责
 * 「路径 + 方法 + 载荷」这一件事。
 *
 * 流式 SSE（readPolishStream）与带进度回调的编排**刻意留**在 writer.js —— 它们要
 * 在流中改按钮文案，属视图编排面。
 */
'use strict';

import { api } from './core.js';

// ── 写作分析 ──────────────────────────────────────────────────────────────
export async function analyzeWritingRemote(text) {
  return api('/api/writing/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  });
}

// ── 作文草稿 CRUD ─────────────────────────────────────────────────────────
export async function fetchWriterEssays() {
  return api('/api/essays');
}

export async function fetchWriterEssay(id) {
  return api(`/api/essays/${id}`);
}

export async function createWriterEssay(title, content) {
  return api('/api/essays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content })
  });
}

export async function updateWriterEssay(id, title, content) {
  return api(`/api/essays/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content })
  });
}

export async function removeWriterEssay(id) {
  return api(`/api/essays/${id}`, { method: 'DELETE' });
}

// ── 语法卡 / AI 润色 ──────────────────────────────────────────────────────
export async function saveWritingGrammarCard(essayId, sentenceId, spanIndex) {
  return api('/api/writing/cards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      essay_id: essayId,
      sentence_id: sentenceId,
      span_index: spanIndex
    })
  });
}

export async function fetchWritingPolishDiff(text) {
  return api('/api/writing/ai-polish/diff', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  });
}

export async function applyWritingPolish(essayId, originalText, correctedText, acceptedIndices) {
  return api('/api/writing/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      essay_id: essayId,
      original_text: originalText,
      corrected_text: correctedText,
      accepted_indices: acceptedIndices
    })
  });
}

// ── 版本快照 ──────────────────────────────────────────────────────────────
export async function fetchEssayVersions(essayId) {
  return api(`/api/essays/${essayId}/versions`);
}

export async function createEssayVersion(essayId, message) {
  return api(`/api/essays/${essayId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
}

export async function fetchEssayVersion(essayId, versionId) {
  return api(`/api/essays/${essayId}/versions/${versionId}`);
}

export async function removeEssayVersion(essayId, versionId) {
  return api(`/api/essays/${essayId}/versions/${versionId}`, { method: 'DELETE' });
}

// 命名后缀 `Remote` 的由来：视图层 writer.js 已有一个同名编排函数
// `restoreEssayVersion(versionId)`（带 confirm + 编辑器回填，且经 window 暴露给
// onclick）。本层是它底下的那次请求，故按既有 `analyzeWritingRemote` 的先例加后缀，
// 避免同名重复声明（ES 会直接 SyntaxError，整张模块图一起挂）。
export async function restoreEssayVersionRemote(essayId, versionId) {
  return api(`/api/essays/${essayId}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version_id: versionId })
  });
}
