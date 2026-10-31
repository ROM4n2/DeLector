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

  const response = await fetch('/api/companion/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify({ messages, context }),
    signal: signal
  });

  if (!response.ok) {
    throw new Error('HTTP ' + response.status + ': 伴学智能体服务不可用');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    let currentEvent = 'delta';
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

  // 尾包处理：流结束时若 buffer 还有剩余行
  if (buffer.trim()) {
    const lines = buffer.split('\n');
    let currentEvent = 'delta';
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
}
