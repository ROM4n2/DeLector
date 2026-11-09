/* DeLector - 应用数据入口（L2 持久化访问层）
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage）；
 *   MUST NOT 弹用户提示（notify / alert / confirm）；
 *   MUST NOT 用计时器（setTimeout / setInterval）；
 *   MUST NOT 声明顶层 let/var 可变模块状态。
 *   唯一允许的 import 仅限 ./core.js 的 api()。
 *
 * 唯一职责 = 「路径 + 方法 + 载荷」契约。返回 api() 的原样 Promise 结果，
 * 不做加工、不吞异常。视图层不得再直接 import api() 或拼 /api/ 路径。
 */
'use strict';

import { api } from './core.js';

// ── 首页：备考目录 / 订阅源 / 导入 ───────────────────────────────────────────
export async function fetchExamCatalog() {
  return api('/api/exams/catalog');
}

export async function fetchFeedSources() {
  return api('/api/feed/sources');
}

export async function fetchFeedItems(url) {
  const params = new URLSearchParams({ url: String(url || '') });
  return api('/api/feed/items?' + params.toString());
}

export async function ingestArticleUrl(payload) {
  return api('/api/articles/ingest-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function ingestArticle(payload) {
  return api('/api/articles/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ── 设置 ───────────────────────────────────────────────────────────────────
export async function fetchSettings() {
  return api('/api/settings');
}

export async function saveSettings(payload) {
  return api('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function testApiKey(payload) {
  return api('/api/settings/test-key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ── 卡片 / 复习 ────────────────────────────────────────────────────────────
export async function fetchCards() {
  return api('/api/cards');
}

export async function fetchDueCards() {
  return api('/api/cards/due');
}

export async function reviewCard(type, id, payload) {
  return api(`/api/cards/${type}/${id}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function removeCard(type, id) {
  return api(`/api/cards/${type}/${id}`, { method: 'DELETE' });
}

export async function masterCard(type, id, payload) {
  return api(`/api/cards/${type}/${id}/master`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function recordQuiz(payload) {
  return api('/api/quiz/record', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ── 音频缓存 ───────────────────────────────────────────────────────────────
export async function fetchAudioCache() {
  return api('/api/audio/cache');
}

export async function purgeAudioCache() {
  return api('/api/audio/cache/clear', { method: 'POST' });
}

// ── 备份 ───────────────────────────────────────────────────────────────────
export async function prepareBackup(payload) {
  return api('/api/backup/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function restoreBackup(payload) {
  return api('/api/backup/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ── 备考工作台 ─────────────────────────────────────────────────────────────
export async function fetchPrepMatrix() {
  return api('/api/prep/matrix');
}

export async function fetchPrepSaved() {
  return api('/api/prep/saved');
}

export async function savePrepSaved(payload) {
  return api('/api/prep/saved', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
