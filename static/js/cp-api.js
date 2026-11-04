/* DeLector - Companion API Client (L2 Persistent Access Layer)
 *
 * 依据: docs/specs/2026-10-31-companion-study-agent-design.md §3.3
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制）：
 *   MUST NOT 触碰 DOM；MUST NOT 弹用户提示；MUST NOT 用计时器；
 *   MUST NOT 声明顶层 let/var 可变模块状态；
 *   唯一允许的 import 仅限 ./core.js 的 api。
 */
'use strict';

import { api } from './core.js';

export async function fetchCompanionContext() {
  return api('/api/companion/context');
}

export async function executeProposal(proposalId, action, payload) {
  return api('/api/companion/proposal/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      proposal_id: proposalId,
      action: action,
      payload: payload
    })
  });
}

export async function rejectProposal(proposalId) {
  return api('/api/companion/proposal/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposal_id: proposalId })
  });
}

export async function fetchAppSettings() {
  return api('/api/settings');
}

export async function updateReasoningEffort(effort) {
  return api('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reasoning_effort: effort })
  });
}

export async function fetchCompanionSessions(scopeKey) {
  if (scopeKey) {
    return api(`/api/companion/sessions/scoped/${scopeKey}`);
  }
  return api('/api/companion/sessions');
}

export async function createCompanionSession(articleId, title, scopeKey) {
  return api('/api/companion/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      article_id: articleId || null,
      title: title || '新伴学会话',
      scope_key: scopeKey || null
    })
  });
}

export async function fetchCompanionHistory(sessionId) {
  return api(`/api/companion/sessions/${sessionId}/messages`);
}

export async function fetchCompanionProposals(sessionId) {
  return api(`/api/companion/sessions/${sessionId}/proposals`);
}

/**
 * 消费伴学流式会话端点，解析强类型 SSE 事件
 * @param {Object} options
 * @param {Array} options.messages - 历史消息数组
 * @param {Object} [options.context] - 视口上下文
 * @param {Function} options.onEvent - (eventType, data) => void
 * @param {AbortSignal} [options.signal] - 用于主动取消的信号
 */
export async function streamCompanionChat(options) {
  const messages = options.messages || [];
  const context = options.context || null;
  const onEvent = options.onEvent || (() => {});
  const signal = options.signal || null;

  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream'
  };
  if (options.reasoning_effort) {
    headers['X-Reasoning-Effort'] = options.reasoning_effort;
  }
  if (options.session_id) {
    headers['X-Session-ID'] = options.session_id;
  }

  const reqBody = { messages, context };
  if (options.session_id) {
    reqBody.session_id = options.session_id;
  }
  if (options.reasoning_effort) {
    reqBody.reasoning_effort = options.reasoning_effort;
  }
  if (options.view) {
    reqBody.view = options.view;
  }
  if (options.context_source) {
    reqBody.context_source = options.context_source;
  }
  if (options.draft_text) {
    reqBody.draft_text = options.draft_text;
  }
  if (options.card_context) {
    reqBody.card_context = options.card_context;
  }
  if (options.scope_key) {
    reqBody.scope_key = options.scope_key;
  }

  const response = await fetch('/api/companion/chat', {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(reqBody),
    signal: signal
  });

  if (!response.ok) {
    throw new Error('HTTP ' + response.status + ': 伴学智能体服务不可用');
  }

  // 首次由后端自动建会话时，用响应头回填前端 currentSessionId。
  const responseSessionId = response.headers && response.headers.get
    ? response.headers.get('X-Session-ID')
    : null;
  const rawHistoryLength = response.headers && response.headers.get
    ? response.headers.get('X-History-Length')
    : null;
  const parsedHistoryLength = Number.parseInt(rawHistoryLength, 10);
  const responseHistoryLength = Number.isFinite(parsedHistoryLength) && parsedHistoryLength >= 0
    ? parsedHistoryLength
    : null;
  if (responseSessionId && typeof options.onSessionId === 'function') {
    options.onSessionId(responseSessionId, responseHistoryLength);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let currentEvent = 'delta';

  function parseLines(lines) {
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        continue;
      }
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        const rawJson = line.slice(5).trim();
        try {
          const parsed = JSON.parse(rawJson);
          const eventType = (parsed && parsed.event) || currentEvent;
          onEvent(eventType, parsed);
        } catch (_) {
          // 容错忽略非 JSON 帧
        }
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    parseLines(lines);
  }

  // 尾包处理：流结束时若 buffer 还有剩余行
  if (buffer.trim()) {
    parseLines(buffer.split('\n'));
  }
}
