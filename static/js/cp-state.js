/* DeLector - Companion State Container (L1 Pure Layer)
 *
 * 伴学智能体状态容器（依据 docs/specs/2026-10-31-companion-study-agent-design.md §3.2）
 * 集中收口抽屉展开态、消息流状态、活跃工具及 Proposal 提议队列。
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制）：
 *   MUST NOT 触碰 DOM；MUST NOT 发网络请求；MUST NOT 弹用户提示；
 *   MUST NOT 用计时器；MUST NOT 有顶层 `let`/`var`；import 白名单为**空**。
 */
'use strict';

export const companionState = {
  // 抽屉可见性
  isOpen: false,

  // 当前标签页: 'chat' (对话) | 'proposals' (提议卡片) | 'context' (学情)
  activeTab: 'chat',

  // 对话历史记录: [{ role: 'user'|'assistant'|'system', content: string, thought?: string }]
  messages: [],

  // 是否有在途的 Agent 请求
  inFlight: false,

  // 流式阶段: null | 'thinking' | 'tool' | 'streaming' | 'done' | 'error'
  streamStage: null,

  // 当前调用的工具信息: { tool: string, label: string, summary: string }
  activeTool: null,

  // 待处理或已处理的提议列表: [{ id, action, title, payload, status: 'pending'|'accepted'|'discarded' }]
  proposals: [],

  // 视口收获的上下文: { selectedText, articleTitle, cefrLevel }
  activeContext: {
    selectedText: '',
    articleTitle: '',
    cefrLevel: 'B1'
  }
};

/** 重置会话与暂存流状态 */
export function resetCompanionSession() {
  companionState.messages = [];
  companionState.inFlight = false;
  companionState.streamStage = null;
  companionState.activeTool = null;
  companionState.proposals = [];
}

/** 更新当前阅读上下文 */
export function setCompanionContext(selectedText, articleTitle, cefrLevel) {
  companionState.activeContext.selectedText = selectedText || '';
  companionState.activeContext.articleTitle = articleTitle || '';
  companionState.activeContext.cefrLevel = cefrLevel || 'B1';
}
