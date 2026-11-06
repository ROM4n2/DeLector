/* DeLector - Companion Drawer UI Component
 *
 * 依据: 方案 A 深度统一设计
 * 将伴学导学作为主抽屉 (#drawer) 的第 5 个专属 Tab 深度集成。
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 构建 (createElement / textContent / appendChild)，彻底杜绝 XSS 隐患。
 * 模块化拆分结构：
 * - cp-drawer-markdown.js: 纯 DOM 结构化 Markdown 渲染器。
 * - cp-drawer-capsule.js: 萌宠浮动胶囊拖拽/点击交互控制器。
 * - cp-drawer-proposals.js: 生词与语法卡片入库提议交互卡片。
 */
'use strict';

import { companionState, setCompanionContext, resetCompanionContextForView } from './cp-state.js';
import { getActiveView, getCompanionScopeKey } from './companion.js';
import {
  streamCompanionChat,
  executeProposal,
  rejectProposal,
  fetchCompanionSessions,
  createCompanionSession,
  fetchCompanionHistory,
  fetchCompanionProposals,
  fetchAppSettings,
  updateReasoningEffort
} from './cp-api.js';
import { renderSafeMarkdownToElement } from './cp-drawer-markdown.js';
import { initFloatingCapsule } from './cp-drawer-capsule.js';
import { renderProposalCard, renderProposalList } from './cp-drawer-proposals.js';

// Re-export modular components for caller backwards compatibility
export { renderSafeMarkdownToElement } from './cp-drawer-markdown.js';
export { initFloatingCapsule } from './cp-drawer-capsule.js';
export { renderProposalCard, renderProposalList } from './cp-drawer-proposals.js';

let drawerEl = null;
let contextBarEl = null;
let bodyEl = null;
let inputEl = null;
let sendBtnEl = null;
let abortController = null;
let activeTurnGeneration = 0;
let currentReasoningEffort = 'medium';
let sessionSelectEl = null;
let persistedHistorySessionId = null;
let persistedHistoryCount = 0;

function setPersistedHistoryCount(sessionId, count) {
  if (!sessionId) return;
  persistedHistorySessionId = sessionId;
  persistedHistoryCount = count;
}

function getPersistedHistoryCount(sessionId) {
  if (!sessionId) return 0;
  // 状态被重置或切换到未跟踪会话时，以当前已加载历史为基线；
  // 同一 session 的乐观 user 不计入，只有 done/成功恢复才推进该计数。
  if (persistedHistorySessionId !== sessionId || companionState.messages.length < persistedHistoryCount) {
    setPersistedHistoryCount(sessionId, companionState.messages.length);
  }
  return persistedHistoryCount;
}

export async function refreshSessionSelect() {
  sessionSelectEl = document.getElementById('companion-session-select');
  if (!sessionSelectEl) return;
  try {
    // 全局历史入口：一次拉全量会话，再按 scope 分组；当前 scope 仍排在最前。
    // 后端 /api/companion/sessions 不带 scope_key 时本来就返回全部 scope，旧 scoped 端点不变。
    const res = await fetchCompanionSessions();
    if (res && res.sessions) {
      companionState.sessions = res.sessions;
      renderSessionOptions();
    }
  } catch (err) {
    console.warn('[CompanionDrawer] Failed to fetch sessions:', err);
  }
}

function renderSessionOptions() {
  if (!sessionSelectEl) sessionSelectEl = document.getElementById('companion-session-select');
  if (!sessionSelectEl) return;

  while (sessionSelectEl.firstChild) {
    sessionSelectEl.removeChild(sessionSelectEl.firstChild);
  }

  const defaultOpt = document.createElement('option');
  defaultOpt.value = '';
  defaultOpt.textContent = '＋ 新建会话';
  sessionSelectEl.appendChild(defaultOpt);

  const currentScope = getCompanionScopeKey();
  const sessions = companionState.sessions || [];
  const current = sessions.filter((s) => (s.scope_key || '') === currentScope);
  const others = sessions.filter((s) => (s.scope_key || '') !== currentScope).slice(0, 8);

  const addOption = (parent, s, withScope) => {
    const opt = document.createElement('option');
    opt.value = s.id;
    const scopeSuffix = withScope ? ` · ${s.scope_key || 'view:global'}` : '';
    opt.textContent = `${s.title}${scopeSuffix} (${new Date(s.created_at).toLocaleDateString()})`;
    if (s.id === companionState.currentSessionId) {
      opt.selected = true;
    }
    parent.appendChild(opt);
  };

  if (current.length > 0) {
    const group = document.createElement('optgroup');
    group.label = '当前页面';
    for (const s of current) addOption(group, s, false);
    sessionSelectEl.appendChild(group);
  }
  if (others.length > 0) {
    const group = document.createElement('optgroup');
    group.label = '其它会话（跨页面）';
    for (const s of others) addOption(group, s, true);
    sessionSelectEl.appendChild(group);
  }
}

export async function newSession(articleId) {
  try {
    const view = getActiveView();
    const currentArticleId = view === 'reader' && window.state?.currentArticle
      ? window.state.currentArticle.id
      : null;
    const aid = articleId || currentArticleId || null;
    const scopeKey = getCompanionScopeKey();
    const res = await createCompanionSession(
      aid,
      '伴学研读 ' + new Date().toLocaleTimeString(),
      scopeKey
    );
    if (res && res.session) {
      companionState.currentSessionId = res.session.id;
      companionState.messages = [];
      companionState.proposals = [];
      await refreshSessionSelect();
      clearMessageArea();
      renderWelcomeMessage();
    }
  } catch (err) {
    console.error('[CompanionDrawer] Failed to create session:', err);
  }
}

export async function switchSession(sessionId) {
  if (!sessionId) {
    await newSession();
    return;
  }
  companionState.currentSessionId = sessionId;
  clearMessageArea();
  try {
    const histRes = await fetchCompanionHistory(sessionId);
    const messages = (histRes && histRes.messages) || [];
    companionState.messages = messages.map(m => ({
      role: m.role,
      content: m.content,
      thought: m.thought
    }));

    const propRes = await fetchCompanionProposals(sessionId);
    const proposals = (propRes && propRes.proposals) || [];
    companionState.proposals = proposals;

    renderHistoricalMessages(messages, proposals);

    // 跨 scope 恢复：历史照读，但当前页面上下文必须重置并显式告知，
    // 绝不把其它文章/页面的句子静默当成当前上下文。
    const selected = (companionState.sessions || []).find((s) => s.id === sessionId);
    const selectedScope = selected && selected.scope_key;
    if (selectedScope && selectedScope !== getCompanionScopeKey()) {
      resetCompanionContextForView(getActiveView());
      renderContextBar();
      if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
      if (bodyEl) {
        const notice = document.createElement('div');
        notice.className = 'companion-message assistant companion-scope-notice';
        notice.textContent = `已切换到「${selectedScope}」的历史会话；当前页面上下文未绑定，不会沿用其它页面的句子。`;
        bodyEl.appendChild(notice);
      }
    }
  } catch (err) {
    console.error('[CompanionDrawer] Failed to switch session:', err);
  }
}

function clearMessageArea() {
  if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
  if (bodyEl) {
    while (bodyEl.firstChild) {
      bodyEl.removeChild(bodyEl.firstChild);
    }
  }
}

function renderWelcomeMessage() {
  if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
  if (!bodyEl) return;
  const msgEl = document.createElement('div');
  msgEl.className = 'companion-message assistant';
  const textEl = document.createElement('div');
  textEl.className = 'companion-text-body';
  textEl.textContent = 'Hallo! 我是你的研读伙伴 Eule。选中德语难句点击我，我可以为你深入剖析拓扑结构、语用褒贬或批量制作闪卡。';
  msgEl.appendChild(textEl);
  bodyEl.appendChild(msgEl);
}

function renderHistoricalMessages(messages, proposals) {
  if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
  if (!bodyEl) return;

  if (messages.length === 0) {
    renderWelcomeMessage();
    return;
  }

  for (const msg of messages) {
    const msgEl = document.createElement('div');
    msgEl.className = `companion-message ${msg.role}`;
    const textEl = document.createElement('div');
    if (msg.role === 'assistant') {
      renderSafeMarkdownToElement(textEl, msg.content || '');
    } else {
      textEl.textContent = msg.content || '';
    }
    msgEl.appendChild(textEl);
    bodyEl.appendChild(msgEl);
  }

  if (proposals.length > 0) {
    const propContainer = document.createElement('div');
    propContainer.className = 'companion-proposals-history';
    renderProposalList(propContainer, proposals, async (proposal, action) => {
      return await handleProposalAction(proposal, action);
    });
    bodyEl.appendChild(propContainer);
  }
  bodyEl.scrollTop = bodyEl.scrollHeight;
}

/**
 * 设置思维链推演深度 (low / medium / high)
 * @param {string} effort
 * @returns {string}
 */
export function setReasoningEffort(effort) {
  currentReasoningEffort = effort || 'medium';
  if (companionState) {
    companionState.reasoningEffort = currentReasoningEffort;
  }
  // 1. 同步 UI 思考强度胶囊 active 状态
  const pills = document.querySelectorAll('.thinking-pill');
  pills.forEach((p) => {
    p.classList.toggle('active', p.dataset.effort === currentReasoningEffort);
  });
  // 2. 同步设置弹窗中的下拉框
  const select = document.getElementById('set-reasoning-effort');
  if (select && select.value !== currentReasoningEffort) {
    select.value = currentReasoningEffort;
  }
  // 3. 异步持久化到后端设置
  updateReasoningEffort(currentReasoningEffort).catch((err) => {
    console.warn('[CompanionDrawer] Failed to persist reasoning effort:', err);
  });
  return currentReasoningEffort;
}

const COMPANION_VIEW_LABELS = {
  reader: '阅读器',
  home: '文库',
  cards: '卡盒',
  progress: '学情',
  writer: '写作台',
  exam: '备考',
  search: '检索',
  encounter: '遇见区',
  german: '德语工作台'
};

/** 动态同步底部快捷操作选项卡显示状态（阅读器按选区，写作台按草稿） */
function updateQuickActionChips(hasText, view, hasDraft) {
  const readerContext = Boolean(hasText) && view === 'reader';
  const writerContext = Boolean(hasDraft) && view === 'writer';
  const chips = document.querySelectorAll('.companion-quick-chip.context-required');
  chips.forEach((c) => {
    c.classList.toggle('is-visible', readerContext);
  });
  const writerChips = document.querySelectorAll('.companion-quick-chip.writer-draft-required');
  writerChips.forEach((c) => {
    c.classList.toggle('is-visible', writerContext);
  });
  const progressContext = view === 'progress';
  const progressChips = document.querySelectorAll('.companion-quick-chip.progress-required');
  progressChips.forEach((c) => {
    c.classList.toggle('is-visible', progressContext);
  });
  const cardsContext = view === 'cards';
  const cardsChips = document.querySelectorAll('.companion-quick-chip.card-proposal-required');
  cardsChips.forEach((c) => {
    c.classList.toggle('is-visible', cardsContext);
  });
}

/** HITL 提议动作：确认写库并刷新卡盒；拒绝只流转状态、绝不写卡。 */
async function handleProposalAction(proposal, action) {
  if (!proposal || !proposal.id) {
    throw new Error('提议缺少有效 ID');
  }
  if (action === 'reject' || action === 'discard') {
    return await rejectProposal(proposal.id);
  }
  if (proposal.action === 'apply_writing_revision') {
    const writerState = typeof window.getWriterRevisionState === 'function'
      ? window.getWriterRevisionState()
      : null;
    const original = String(proposal.payload && proposal.payload.original_text || '').trim();
    if (!writerState || !writerState.essay_id || !writerState.content) {
      throw new Error('请先保存作文，再应用修订');
    }
    if (!original || writerState.content.split(original).length !== 2) {
      throw new Error('原句在当前草稿中不存在或不唯一');
    }
    const res = await executeProposal(proposal.id, proposal.action, {
      ...proposal.payload,
      essay_id: writerState.essay_id
    });
    if (res && res.content && typeof window.applyCompanionRevision === 'function') {
      window.applyCompanionRevision(res.content);
    }
    return res;
  }
  const res = await executeProposal(proposal.id, proposal.action, proposal.payload);
  if (String(proposal.action || '').startsWith('create_vocab_card') && res && Number(res.created_count) > 0 && typeof window.loadCards === 'function') {
    window.loadCards();
  }
  return res;
}

/** 刷新抽屉顶部视口研读语境条与手机端句子步进器 */
export function renderContextBar() {
  if (!contextBarEl) {
    contextBarEl = document.getElementById('companion-context-bar');
  }
  if (!contextBarEl) return;

  while (contextBarEl.firstChild) {
    contextBarEl.removeChild(contextBarEl.firstChild);
  }

  const text = companionState.activeContext.selectedText;
  const draft = companionState.activeContext.draftText;
  const cardContext = companionState.activeContext.cardContext;
  const view = companionState.activeContext.view || getActiveView();
  const viewLabel = COMPANION_VIEW_LABELS[view] || '当前页面';
  const sents = window.state?.currentArticle?.sentences || [];

  if (text) {
    contextBarEl.style.display = 'flex';
    const icon = document.createElement('span');
    icon.textContent = '📌';
    const textSpan = document.createElement('span');
    textSpan.className = 'companion-context-text';
    textSpan.textContent = (view === 'reader' ? '已绑定难句: „' : '已绑定文本: „') + text + '“';

    const clearBtn = document.createElement('button');
    clearBtn.className = 'companion-context-clear';
    clearBtn.title = '解除难句绑定';
    clearBtn.textContent = '✕';
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      setCompanionContext(
        '',
        companionState.activeContext.articleTitle,
        companionState.activeContext.cefrLevel,
        view,
        'none',
        companionState.activeContext.draftText
      );
      renderContextBar();
    });

    contextBarEl.appendChild(icon);
    contextBarEl.appendChild(textSpan);

    // 手机端/精读模式：直接提供上下句无缝步进导航 (◀ 句 3/18 ▶)
    // 句子步进只属于阅读器；其它页面的 live-selection 不得借用上一篇的句子列表。
    if (view === 'reader' && sents.length > 0) {
      let currentIdx = sents.findIndex(
        (s) => s.text === text || s.id === window.state?.activeSelectedSentId
      );
      if (currentIdx === -1 && text) {
        currentIdx = sents.findIndex((s) => s.text.replace(/\s+/g, '') === text.replace(/\s+/g, ''));
      }

      const navWrap = document.createElement('div');
      navWrap.className = 'companion-sent-nav';

      const prevBtn = document.createElement('button');
      prevBtn.className = 'companion-nav-btn';
      prevBtn.title = '上一句 (手机快捷点选)';
      prevBtn.setAttribute('aria-label', '上一句');
      prevBtn.innerHTML = '<svg class="ui-ico" aria-hidden="true" focusable="false"><use href="#ui-ico-chevron-left"></use></svg>';
      prevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetIdx = currentIdx > 0 ? currentIdx - 1 : sents.length - 1;
        const targetSent = sents[targetIdx];
        if (targetSent) {
          if (window.state) {
            window.state.activeSelectedSentId = targetSent.id;
            window.state.activeSelectedRangeText = targetSent.text;
          }
          setCompanionContext(
            targetSent.text,
            window.state?.currentArticle?.title,
            window.state?.currentArticle?.cefr_level,
            'reader',
            'reader-state',
            companionState.activeContext.draftText
          );
          renderContextBar();
        }
      });

      const indicator = document.createElement('span');
      indicator.className = 'companion-nav-indicator';
      indicator.textContent = (currentIdx >= 0 ? (currentIdx + 1) : '-') + '/' + sents.length;

      const nextBtn = document.createElement('button');
      nextBtn.className = 'companion-nav-btn';
      nextBtn.title = '下一句 (手机快捷点选)';
      nextBtn.setAttribute('aria-label', '下一句');
      nextBtn.innerHTML = '<svg class="ui-ico" aria-hidden="true" focusable="false"><use href="#ui-ico-chevron-right"></use></svg>';
      nextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetIdx = (currentIdx >= 0 && currentIdx < sents.length - 1) ? currentIdx + 1 : 0;
        const targetSent = sents[targetIdx];
        if (targetSent) {
          if (window.state) {
            window.state.activeSelectedSentId = targetSent.id;
            window.state.activeSelectedRangeText = targetSent.text;
          }
          setCompanionContext(
            targetSent.text,
            window.state?.currentArticle?.title,
            window.state?.currentArticle?.cefr_level,
            'reader',
            'reader-state',
            companionState.activeContext.draftText
          );
          renderContextBar();
        }
      });

      navWrap.appendChild(prevBtn);
      navWrap.appendChild(indicator);
      navWrap.appendChild(nextBtn);
      contextBarEl.appendChild(navWrap);
    }

    contextBarEl.appendChild(clearBtn);
  } else if (view === 'writer' && draft) {
    contextBarEl.style.display = 'flex';
    const icon = document.createElement('span');
    icon.textContent = '✍️';
    const textSpan = document.createElement('span');
    textSpan.className = 'companion-context-text';
    textSpan.textContent = '已绑定当前草稿（' + draft.length + ' 字符）';
    contextBarEl.appendChild(icon);
    contextBarEl.appendChild(textSpan);
  } else if (view === 'cards' && cardContext) {
    contextBarEl.style.display = 'flex';
    const icon = document.createElement('span');
    icon.textContent = '🃏';
    const textSpan = document.createElement('span');
    textSpan.className = 'companion-context-text';
    textSpan.textContent = '已绑定当前卡盒词条';
    contextBarEl.appendChild(icon);
    contextBarEl.appendChild(textSpan);
  } else {
    contextBarEl.style.display = 'flex';
    const hint = document.createElement('span');
    hint.className = 'companion-context-hint';
    if (view === 'reader') {
      hint.textContent = '📄 阅读器 · 未绑定句子：划选正文或点击 🦉伴学，即可让 Eule 针对性问诊。';
    } else if (view === 'writer') {
      hint.textContent =
        '📝 写作台 · 尚未检测到草稿：先在编辑器输入正文，再点「✍️ 检查草稿」。';
    } else {
      hint.textContent =
        '📄 ' + viewLabel + ' · 未绑定句子：本页仅支持自由问答，阅读器专属问诊请在阅读页使用。';
    }

    contextBarEl.appendChild(hint);

    // “抓取当前句”只在阅读器有意义；其它页面没有可抓取的视口句子。
    if (view === 'reader') {
      const grabBtn = document.createElement('button');
      grabBtn.className = 'companion-context-grab-btn';
      grabBtn.textContent = '🎯 抓取当前句';
      grabBtn.addEventListener('click', () => {
        syncCurrentContext();
      });
      contextBarEl.appendChild(grabBtn);
    }
  }

  updateQuickActionChips(Boolean(text), view, Boolean(draft));
}

/** 写作台输入时静默刷新草稿上下文（不追加聊天消息）。 */
export function refreshWriterDraftContext() {
  if (getActiveView() !== 'writer') return;
  if (!window.Companion || typeof window.Companion.harvestStudyContext !== 'function') return;
  const ctx = window.Companion.harvestStudyContext();
  setCompanionContext(
    ctx.selectedText,
    ctx.articleTitle,
    ctx.cefrLevel,
    ctx.view,
    ctx.contextSource,
    ctx.draftText,
    ctx.cardContext
  );
  renderContextBar();
}

/** 卡盒当前词条：发送/打开前刷新，供 propose_vocab_cards 使用。 */
export function refreshCardBoxContext() {
  if (getActiveView() !== 'cards') return;
  if (!window.Companion || typeof window.Companion.harvestStudyContext !== 'function') return;
  const ctx = window.Companion.harvestStudyContext();
  setCompanionContext(
    ctx.selectedText,
    ctx.articleTitle,
    ctx.cefrLevel,
    ctx.view,
    ctx.contextSource,
    ctx.draftText,
    ctx.cardContext
  );
  renderContextBar();
}

/** 卡盒页专属：基于当前卡面词条批量提议生词卡（HITL）。 */
export function sendCardProposal() {
  if (getActiveView() !== 'cards') return;
  refreshCardBoxContext();
  if (!companionState.activeContext.cardContext) {
    alert('当前卡盒没有可用词条。请切换到卡面视图并确保当前分区有卡片后再试。');
    return;
  }
  submitPrompt(
    '请基于【当前卡盒词条】提议 3~5 个相关的 B1/B2 德语生词卡（propose_vocab_cards），' +
      '每张卡必须含 definition_zh 中文释义与例句（reading 仅用于读音/音标，不得充当释义）；' +
      '所有卡片都必须等我确认后才能入库。'
  );
}

/** 写作台专属：为选中原句生成逐条可确认/拒绝的修订提议。 */
export function sendWriterRevisionProposal() {
  if (getActiveView() !== 'writer') return;
  refreshWriterDraftContext();
  const original = String(companionState.activeContext.selectedText || '').trim();
  const writerState = typeof window.getWriterRevisionState === 'function'
    ? window.getWriterRevisionState()
    : null;
  if (!original) {
    alert('请先在编辑器中选中需要修订的完整句子。');
    return;
  }
  if (!writerState || !writerState.essay_id) {
    alert('请先保存作文，再生成修订提议。');
    return;
  }
  if (writerState.content.split(original).length !== 2) {
    alert('选中原句必须恰好出现在当前草稿中一次。');
    return;
  }
  submitPrompt(
    '请调用 propose_writing_revision，为以下选中原句生成一条待确认修订提议。' +
      'original_text 必须逐字保留原句，revised_text 给出完整改写，不得直接修改作文：\n\n' + original
  );
}

/** 进度页专属：学习负荷 / 复习压力画像。 */
export function sendProgressProfile() {
  if (getActiveView() !== 'progress') return;
  submitPrompt(
    '请调用 get_learner_profile 工具，总结我的学习负荷、复习压力、已掌握词量与当前水平估计，并给出可执行的调整建议。'
  );
}

/** 进度页专属：对输入框中的德语文本做 CEFR 词汇等级分布。 */
export function sendProgressVocabStats() {
  if (getActiveView() !== 'progress') return;
  const input = document.getElementById('companion-input');
  const text = (input && input.value ? input.value : '').trim();
  if (!text) {
    alert('请先在输入框粘贴需要统计的德语文本，再点击「词汇等级」。');
    input?.focus();
    return;
  }
  input.value = '';
  submitPrompt(
    '请调用 vocab_stats 工具统计以下德语文本的 CEFR 词汇等级分布，并解释已知/未知词比例：\n\n' + text
  );
}

/** 进度页专属：生成可确认写入的周学习目标。 */
export function sendProgressWeeklyGoal() {
  if (getActiveView() !== 'progress') return;
  submitPrompt(
    '请先调用 get_learner_profile 了解我的学习负荷，再调用 propose_weekly_goal 生成一个具体、可执行、可衡量的本周学习目标；必须等我确认后才能写入。'
  );
}

/** 同步当前阅读器选区或活动难句 */
export function syncCurrentContext() {
  if (window.Companion && window.Companion.harvestStudyContext) {
    const ctx = window.Companion.harvestStudyContext();
    if (ctx.selectedText || ctx.draftText) {
      setCompanionContext(
        ctx.selectedText,
        ctx.articleTitle,
        ctx.cefrLevel,
        ctx.view,
        ctx.contextSource,
        ctx.draftText,
        ctx.cardContext
      );
      renderContextBar();
      if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
      if (bodyEl) {
        const hintDiv = document.createElement('div');
        hintDiv.className = 'companion-message assistant';
        hintDiv.style.borderLeft = '3px solid var(--coral, #b44322)';
        const lbl = document.createElement('div');
        if (ctx.view === 'writer' && !ctx.selectedText) {
          lbl.textContent = '✓ 已同步写作台草稿：';
        } else {
          lbl.textContent = ctx.view === 'reader' ? '✓ 已同步视口难句：' : '✓ 已同步当前页面文本：';
        }
        const q = document.createElement('em');
        q.textContent = ctx.selectedText
          ? '„' + ctx.selectedText + '“'
          : '（' + ctx.draftText.length + ' 字符）';
        hintDiv.appendChild(lbl);
        hintDiv.appendChild(q);
        bodyEl.appendChild(hintDiv);
        bodyEl.scrollTop = bodyEl.scrollHeight;
      }
      return;
    }
  }
  const view = getActiveView();
  if (view === 'writer') {
    alert('写作台尚未检测到草稿。请先在编辑器输入正文，再使用「✍️ 检查草稿」。');
    return;
  }
  alert(
    view === 'reader'
      ? '未检测到当前选中文本。请在文章中点击句旁的 [🦉 伴学]，或点击单词后重试。'
      : '当前页面未检测到选中文本；阅读器专属问诊请在阅读页使用。'
  );
}

/** 初始化抽屉 DOM 挂载（挂载到主抽屉 #drawer 的 companion-section） */
export function initCompanionDrawer() {
  const container = document.getElementById('drawer-companion-section');
  drawerEl = document.getElementById('drawer');
  contextBarEl = document.getElementById('companion-context-bar');
  bodyEl = document.getElementById('companion-drawer-body');
  inputEl = document.getElementById('companion-input');
  sendBtnEl = document.getElementById('companion-send-btn');

  if (inputEl && !inputEl._companionBound) {
    inputEl._companionBound = true;
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleSend();
    });
  }
  if (sendBtnEl && !sendBtnEl._companionBound) {
    sendBtnEl._companionBound = true;
    sendBtnEl.addEventListener('click', handleSend);
  }

  // 初始化全局伴学浮动胶囊拖拽/点击行为
  initFloatingCapsule();

  renderContextBar();
  refreshSessionSelect();

  // 恢复持久化保存的思考强度配置
  fetchAppSettings().then((res) => {
    if (res && res.reasoning_effort) {
      setReasoningEffort(res.reasoning_effort);
    }
  }).catch(() => {});

  return container;
}

export function openCompanionDrawer(contextPayload) {
  // 统一入口准入：german 工作台禁止打开伴学抽屉。
  if (getActiveView() === 'german') return;
  initCompanionDrawer();
  const view = (contextPayload && contextPayload.view) || getActiveView();
  if (contextPayload) {
    const contextSource =
      contextPayload.contextSource ||
      (contextPayload.selectedText
        ? view === 'reader'
          ? 'reader-state'
          : 'live-selection'
        : 'none');
    setCompanionContext(
      contextPayload.selectedText,
      contextPayload.articleTitle,
      contextPayload.cefrLevel,
      view,
      contextSource,
      contextPayload.draftText,
      contextPayload.cardContext
    );
  } else {
    // 无显式上下文时也必须清掉旧值，避免抽屉页签复用上一篇的阅读器上下文。
    setCompanionContext('', '', '', view, 'none', '', '');
  }
  companionState.isOpen = true;

  if (typeof window.openDrawer === 'function') {
    window.openDrawer('companion');
  } else {
    document.getElementById('drawer')?.classList.add('open');
    document.body.classList.add('drawer-open');
    if (typeof window.switchDrawerTab === 'function') {
      window.switchDrawerTab('companion');
    }
  }
  renderContextBar();

  if (contextPayload && (contextPayload.selectedText || contextPayload.draftText)) {
    if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
    if (bodyEl) {
      const hintDiv = document.createElement('div');
      hintDiv.className = 'companion-message assistant';
      hintDiv.style.borderLeft = '3px solid var(--coral, #b44322)';

      const label = document.createElement('div');
      label.textContent = view === 'reader' ? '已绑定视口难句：' : '已绑定当前页面文本：';
      const quote = document.createElement('em');
      quote.textContent = contextPayload.selectedText
        ? '„' + contextPayload.selectedText + '“'
        : '（' + contextPayload.draftText.length + ' 字符草稿）';

      hintDiv.appendChild(label);
      hintDiv.appendChild(quote);
      bodyEl.appendChild(hintDiv);
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  }
}

export function closeCompanionDrawer() {
  companionState.isOpen = false;
  if (typeof window.closeDrawer === 'function') {
    window.closeDrawer();
  } else {
    document.getElementById('drawer')?.classList.remove('open');
    document.body.classList.remove('drawer-open');
  }
}

export function toggleCompanionDrawer(contextPayload) {
  const drawer = document.getElementById('drawer');
  const isCompanionOpen =
    drawer?.classList.contains('open') &&
    document.getElementById('d-tab-companion')?.classList.contains('active');

  if (isCompanionOpen) {
    closeCompanionDrawer();
  } else {
    openCompanionDrawer(contextPayload);
  }
}

export function handleSend() {
  if (!inputEl) inputEl = document.getElementById('companion-input');
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  submitPrompt(text);
}

function createCompanionTurnController({
  thoughtCtrl,
  toolContainerEl,
  textBodyEl,
  proposalsContainerEl,
  typewriter
}) {
  let fullStreamText = '';
  let completed = false;

  return {
    handleEvent(event, data, turnGeneration, sessionId, persistedCount) {
      if (event === 'thought') {
        thoughtCtrl.setRealThought(data.text || '');
      } else if (event === 'tool_start') {
        toolContainerEl.style.display = 'block';
        const chip = document.createElement('span');
        chip.className = 'companion-tool-chip';
        chip.dataset.tool = data.tool || '';
        chip.textContent = data.label || ('正在调用 ' + data.tool + '...');
        toolContainerEl.appendChild(chip);
      } else if (event === 'tool_end') {
        const chips = toolContainerEl.querySelectorAll('.companion-tool-chip');
        for (const c of chips) {
          if (c.dataset.tool === data.tool) {
            const isError = Boolean(data.result && (data.result.status === 'error' || data.result.error_code));
            if (isError) {
              c.classList.add('companion-tool-chip--error');
              c.style.borderColor = 'var(--coral, #b44322)';
              c.style.color = 'var(--coral, #b44322)';
              c.textContent = '✗ ' + data.tool + ' 异常: ' + (data.summary || (data.result && data.result.message) || '失败');
            } else {
              c.textContent = '✓ ' + data.tool + ' 完成: ' + (data.summary || '已获取语言学上下文');
            }
          }
        }
      } else if (event === 'delta') {
        thoughtCtrl.finish();
        const chunk = data.text || '';
        fullStreamText += chunk;
        typewriter.append(chunk);
      } else if (event === 'proposal') {
        renderProposalCard(proposalsContainerEl, data.proposal, handleProposalAction);
      } else if (event === 'done') {
        completed = true;
        thoughtCtrl.finish();
        const ownsTurn = turnGeneration === activeTurnGeneration;
        if (ownsTurn) {
          setPersistedHistoryCount(sessionId, persistedCount + 2);
          companionState.inFlight = false;
          if (sendBtnEl) sendBtnEl.disabled = false;
        }
        typewriter.flush();
        if (fullStreamText) {
          renderSafeMarkdownToElement(textBodyEl, fullStreamText);
        }
        if (ownsTurn) {
          companionState.messages.push({ role: 'assistant', content: fullStreamText });
        }
      } else if (event === 'error') {
        typewriter.cancel();
        thoughtCtrl.fail('研读中断');
        if (turnGeneration === activeTurnGeneration) {
          companionState.inFlight = false;
          if (sendBtnEl) sendBtnEl.disabled = false;
        }
        textBodyEl.textContent = '[异常: ' + (data.message_zh || '处理失败') + ']';
        textBodyEl.style.color = 'var(--coral, #b44322)';
      }
      bodyEl.scrollTop = bodyEl.scrollHeight;
    },

    async handleStreamError(err, sessionId, userText, minimumRecoveredMessages, turnGeneration) {
      if (completed || turnGeneration !== activeTurnGeneration) return;
      typewriter.cancel();
      thoughtCtrl.fail('连接中断');

      let recoveredMessages = null;
      if (sessionId) {
        // 取消响应与后端 finally 落库可能相差一个网络来回；顺序短重试，不重发模型请求。
        for (let attempt = 0; attempt < 3 && !recoveredMessages; attempt += 1) {
          try {
            const histRes = await fetchCompanionHistory(sessionId);
            const messages = (histRes && histRes.messages) || [];
            const userMsg = messages[messages.length - 2];
            const assistantMsg = messages[messages.length - 1];
            if (
              messages.length >= minimumRecoveredMessages &&
              userMsg?.role === 'user' &&
              userMsg.content === userText &&
              assistantMsg?.role === 'assistant' &&
              assistantMsg.content
            ) {
              recoveredMessages = messages;
            }
          } catch (recoveryErr) {
            console.warn('[CompanionDrawer] Failed to recover interrupted turn:', recoveryErr);
            break;
          }
        }
      }

      if (
        recoveredMessages &&
        companionState.currentSessionId === sessionId &&
        turnGeneration === activeTurnGeneration
      ) {
        setPersistedHistoryCount(sessionId, recoveredMessages.length);
        companionState.messages = recoveredMessages.map((m) => ({
          role: m.role,
          content: m.content,
          thought: m.thought
        }));
        const assistantMsg = recoveredMessages[recoveredMessages.length - 1];
        renderSafeMarkdownToElement(textBodyEl, assistantMsg.content);
        const notice = document.createElement('div');
        notice.className = 'companion-resume-notice';
        notice.textContent = '连接中断，已恢复断点前的回答。';
        textBodyEl.appendChild(notice);
        return;
      }

      if (completed || turnGeneration !== activeTurnGeneration) return;
      textBodyEl.textContent = '[连接失败: ' + err.message + ']';
      textBodyEl.style.color = 'var(--coral, #b44322)';
    },

    cleanup(turnGeneration) {
      thoughtCtrl.cleanup();
      if (turnGeneration === activeTurnGeneration) {
        companionState.inFlight = false;
        if (sendBtnEl) sendBtnEl.disabled = false;
      }
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  };
}

export function submitPrompt(userText) {
  if (companionState.inFlight) return;
  if (!userText || !userText.trim()) return;

  const activeView = getActiveView();

  // 写作台：发送前刷新草稿上下文，保证“先打开抽屉、后输入正文”也能拿到最新草稿。
  if (activeView === 'writer' && window.Companion?.harvestStudyContext) {
    const latest = window.Companion.harvestStudyContext();
    setCompanionContext(
      latest.selectedText,
      latest.articleTitle,
      latest.cefrLevel,
      latest.view,
      latest.contextSource,
      latest.draftText,
      latest.cardContext
    );
  }

  // 卡盒：发送前刷新当前卡面词条，避免用户先开抽屉、后翻卡导致上下文过期。
  if (activeView === 'cards' && window.Companion?.harvestStudyContext) {
    const latest = window.Companion.harvestStudyContext();
    setCompanionContext(
      latest.selectedText,
      latest.articleTitle,
      latest.cefrLevel,
      latest.view,
      latest.contextSource,
      latest.draftText,
      latest.cardContext
    );
  }

  // 守卫：写作检查在无草稿时显式降级，不让模型凭空编造检查结果。
  if (
    activeView === 'writer' &&
    !companionState.activeContext.draftText &&
    /草稿|writing_check|写作检查|检查.*写作/.test(userText)
  ) {
    alert('写作台尚未检测到草稿。请先在编辑器输入正文，再执行写作检查。');
    return;
  }

  // 守卫：针对需要句子的快捷提问，若无句子则先尝试自动同步视口句子
  if (
    !companionState.activeContext.selectedText &&
    (userText.includes('选中文本') || userText.includes('这个句子') || userText.includes('拓扑结构'))
  ) {
    syncCurrentContext();
    if (!companionState.activeContext.selectedText) {
      alert('请先在文章中划选或点击单词绑定德语难句，再执行针对性问诊！');
      return;
    }
  }

  if (!bodyEl) initCompanionDrawer();
  if (!bodyEl) return;

  let persistedCountAtStart = getPersistedHistoryCount(companionState.currentSessionId);

  // 1. 渲染用户消息
  const userMsgEl = document.createElement('div');
  userMsgEl.className = 'companion-message user';
  userMsgEl.textContent = userText;
  bodyEl.appendChild(userMsgEl);

  companionState.messages.push({ role: 'user', content: userText });

  // 2. 准备助手气泡
  const asstMsgEl = document.createElement('div');
  asstMsgEl.className = 'companion-message assistant';

  const thoughtCtrl = createThoughtAccordion();

  const toolContainerEl = document.createElement('div');
  toolContainerEl.className = 'companion-tool-container';
  toolContainerEl.style.display = 'none';
  toolContainerEl.style.marginBottom = '0.4rem';

  const textBodyEl = document.createElement('div');
  textBodyEl.className = 'companion-text-body';
  textBodyEl.textContent = '...';

  const proposalsContainerEl = document.createElement('div');
  proposalsContainerEl.className = 'companion-proposals-container';

  asstMsgEl.appendChild(thoughtCtrl.boxEl);
  asstMsgEl.appendChild(toolContainerEl);
  asstMsgEl.appendChild(textBodyEl);
  asstMsgEl.appendChild(proposalsContainerEl);

  bodyEl.appendChild(asstMsgEl);
  bodyEl.scrollTop = bodyEl.scrollHeight;

  const turnGeneration = ++activeTurnGeneration;
  let minimumRecoveredMessages = persistedCountAtStart + 2;
  companionState.inFlight = true;
  if (!sendBtnEl) sendBtnEl = document.getElementById('companion-send-btn');
  if (sendBtnEl) sendBtnEl.disabled = true;

  abortController = new AbortController();

  const activeContext = companionState.activeContext.selectedText
    ? {
        selected_text: companionState.activeContext.selectedText,
        article_title: companionState.activeContext.articleTitle,
        cefr_level: companionState.activeContext.cefrLevel
      }
    : null;

  const typewriter = new AdaptiveTypewriter(textBodyEl, {
    onProgress: () => {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    },
    onComplete: () => {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  });
  const turnController = createCompanionTurnController({
    thoughtCtrl,
    toolContainerEl,
    textBodyEl,
    proposalsContainerEl,
    typewriter
  });

  let streamSessionId = companionState.currentSessionId;
  streamCompanionChat({
    session_id: streamSessionId,
    reasoning_effort: currentReasoningEffort,
    messages: companionState.messages,
    context: activeContext,
    view: companionState.activeContext.view,
    context_source: companionState.activeContext.contextSource,
    draft_text: companionState.activeContext.draftText,
    card_context: companionState.activeContext.cardContext,
    scope_key: getCompanionScopeKey(),
    signal: abortController.signal,
    onSessionId: (sessionId, historyLength) => {
      if (sessionId) {
        streamSessionId = sessionId;
        if (turnGeneration === activeTurnGeneration && Number.isInteger(historyLength) && historyLength >= 0) {
          persistedCountAtStart = historyLength;
          minimumRecoveredMessages = historyLength + 2;
          setPersistedHistoryCount(sessionId, historyLength);
        }
        if (turnGeneration === activeTurnGeneration && companionState.currentSessionId !== sessionId) {
          companionState.currentSessionId = sessionId;
          refreshSessionSelect().catch(() => {});
        }
      }
    },
    onEvent: (event, data) => turnController.handleEvent(
      event,
      data,
      turnGeneration,
      streamSessionId,
      persistedCountAtStart
    )
  }).catch((err) => {
    return turnController.handleStreamError(
      err,
      streamSessionId,
      userText,
      minimumRecoveredMessages,
      turnGeneration
    );
  }).finally(() => {
    turnController.cleanup(turnGeneration);
  });
}

/**
 * 客户端自适应弹性打字机平滑队列 (2B -> 架构平滑演进至 C)
 * 具备动态弹性调速：字数多则平滑自适应加速，字数少则自然书写，附带微光墨水光标
 */
export class AdaptiveTypewriter {
  constructor(container, options = {}) {
    this.container = container;
    this.onProgress = options.onProgress || null;
    this.onComplete = options.onComplete || null;
    this.targetText = '';
    this.renderedLength = 0;
    this.animId = null;
    this.isTyping = false;

    this.cursorEl = document.createElement('span');
    this.cursorEl.className = 'companion-typing-cursor';
  }

  enqueue(text) {
    if (!text) return;
    this.targetText = text;
    if (!this.isTyping) {
      this.isTyping = true;
      this.tick();
    }
  }

  append(chunk) {
    if (!chunk) return;
    this.targetText += chunk;
    if (!this.isTyping) {
      this.isTyping = true;
      this.tick();
    }
  }

  tick() {
    const remaining = this.targetText.length - this.renderedLength;
    if (remaining <= 0) {
      this.flush();
      return;
    }

    let step = 3;
    if (remaining > 1000) {
      step = 36;
    } else if (remaining > 500) {
      step = 22;
    } else if (remaining > 200) {
      step = 12;
    } else if (remaining > 60) {
      step = 6;
    } else {
      step = 2;
    }

    this.renderedLength = Math.min(this.targetText.length, this.renderedLength + step);
    const currentSlice = this.targetText.slice(0, this.renderedLength);

    renderSafeMarkdownToElement(this.container, currentSlice);

    if (this.renderedLength < this.targetText.length) {
      this.container.appendChild(this.cursorEl);
    }

    if (this.onProgress) {
      this.onProgress(this.renderedLength, this.targetText.length);
    }

    this.animId = requestAnimationFrame(() => this.tick());
  }

  flush() {
    if (this.animId) {
      cancelAnimationFrame(this.animId);
      this.animId = null;
    }
    if (this.targetText) {
      this.renderedLength = this.targetText.length;
      renderSafeMarkdownToElement(this.container, this.targetText);
    }
    if (this.cursorEl.parentNode) {
      this.cursorEl.remove();
    }
    this.isTyping = false;
    if (this.onComplete) {
      this.onComplete();
    }
  }

  cancel() {
    if (this.animId) {
      cancelAnimationFrame(this.animId);
      this.animId = null;
    }
    this.isTyping = false;
    if (this.cursorEl.parentNode) {
      this.cursorEl.remove();
    }
  }
}

export function createThoughtAccordion() {
  const boxEl = document.createElement('div');
  boxEl.className = 'companion-thought-box is-thinking is-expanded';

  // 1. Header (Clickable toggle)
  const headerEl = document.createElement('div');
  headerEl.className = 'companion-thought-header';
  headerEl.title = '点击展开/折叠推演思维链';

  const leftWrap = document.createElement('div');
  leftWrap.className = 'thought-header-left';

  const iconEl = document.createElement('span');
  iconEl.className = 'thought-badge-icon';

  const dotEl = document.createElement('span');
  dotEl.className = 'thought-pulse-dot';
  iconEl.appendChild(dotEl);

  const titleEl = document.createElement('span');
  titleEl.className = 'thought-title';
  titleEl.textContent = 'Eule 正在推演句子结构...';

  leftWrap.appendChild(iconEl);
  leftWrap.appendChild(titleEl);

  const rightWrap = document.createElement('div');
  rightWrap.className = 'thought-header-right';

  const timerEl = document.createElement('span');
  timerEl.className = 'thought-timer';
  timerEl.textContent = '0.0s';

  const arrowEl = document.createElement('span');
  arrowEl.className = 'thought-toggle-arrow';
  arrowEl.textContent = '▾';

  rightWrap.appendChild(timerEl);
  rightWrap.appendChild(arrowEl);

  headerEl.appendChild(leftWrap);
  headerEl.appendChild(rightWrap);

  // 2. Body
  const thoughtBodyEl = document.createElement('div');
  thoughtBodyEl.className = 'companion-thought-body';

  const stepsListEl = document.createElement('div');
  stepsListEl.className = 'thought-steps-list';

  const stepTexts = [
    '① 校验视口上下文与德语原句边界',
    '② 检索五场域 (Felderstruktur) 拓扑规则',
    '③ 校验动词框架 (Verbalklammer) 与从句层级',
    '④ 提炼核心生词卡与学情建议'
  ];

  const stepEls = stepTexts.map((txt, idx) => {
    const s = document.createElement('div');
    s.className = 'thought-step' + (idx === 0 ? ' is-active' : '');
    s.textContent = txt;
    stepsListEl.appendChild(s);
    return s;
  });

  const realContentEl = document.createElement('div');
  realContentEl.className = 'thought-real-content';
  realContentEl.style.display = 'none';

  thoughtBodyEl.appendChild(stepsListEl);
  thoughtBodyEl.appendChild(realContentEl);

  boxEl.appendChild(headerEl);
  boxEl.appendChild(thoughtBodyEl);

  headerEl.addEventListener('click', () => {
    boxEl.classList.toggle('is-expanded');
  });

  const t0 = performance.now();
  let finished = false;
  let realThoughtBuffer = '';
  const timerId = setInterval(() => {
    if (finished || realThoughtBuffer) return;
    const elapsedSec = (performance.now() - t0) / 1000;
    timerEl.textContent = `${elapsedSec.toFixed(1)}s`;

    if (elapsedSec >= 1.2 && stepEls[0].classList.contains('is-active')) {
      stepEls[0].className = 'thought-step is-done';
      stepEls[0].textContent = '✓ 视口研读难句与上下文已锁定';
      stepEls[1].className = 'thought-step is-active';
    }
    if (elapsedSec >= 2.8 && stepEls[1].classList.contains('is-active')) {
      stepEls[1].className = 'thought-step is-done';
      stepEls[1].textContent = '✓ 拓扑五场域映射分析完成';
      stepEls[2].className = 'thought-step is-active';
    }
    if (elapsedSec >= 4.8 && stepEls[2].classList.contains('is-active')) {
      stepEls[2].className = 'thought-step is-done';
      stepEls[2].textContent = '✓ 动词框架与从句层级定式检验';
      stepEls[3].className = 'thought-step is-active';
    }
  }, 500);

  return {
    boxEl,
    setRealThought: (chunk) => {
      if (!chunk) return;
      if (!realThoughtBuffer) {
        stepsListEl.style.display = 'none';
      }
      realThoughtBuffer += chunk;
      realContentEl.style.display = 'block';
      realContentEl.textContent = realThoughtBuffer;
      stepEls.forEach((el) => {
        el.className = 'thought-step is-done';
      });
    },
    finish: () => {
      if (finished) return;
      finished = true;
      clearInterval(timerId);
      const totalSec = ((performance.now() - t0) / 1000).toFixed(1);
      boxEl.classList.remove('is-thinking');
      boxEl.classList.add('is-completed');
      boxEl.classList.remove('is-expanded');

      if (dotEl.parentNode) dotEl.remove();
      iconEl.textContent = '✓';
      titleEl.textContent = `深度推演完成 (${totalSec} 秒)`;
      timerEl.textContent = '';
      if (realThoughtBuffer) {
        stepsListEl.style.display = 'none';
      }
      stepEls.forEach((el) => {
        el.className = 'thought-step is-done';
      });
    },
    fail: (msg) => {
      if (finished) return;
      finished = true;
      clearInterval(timerId);
      boxEl.classList.remove('is-thinking');
      boxEl.classList.add('is-error');
      if (dotEl.parentNode) dotEl.remove();
      iconEl.textContent = '!';
      titleEl.textContent = msg || '研读中断';
    },
    cleanup: () => {
      clearInterval(timerId);
    }
  };
}

export const CompanionDrawer = {
  setReasoningEffort,
  init: initCompanionDrawer,
  toggle: toggleCompanionDrawer,
  open: openCompanionDrawer,
  close: closeCompanionDrawer,
  handleSend,
  sendPrompt: (prompt) => submitPrompt(prompt),
  submitPrompt,
  syncContext: syncCurrentContext,
  syncCurrentContext,
  refreshWriterDraftContext,
  refreshCardBoxContext,
  sendCardProposal,
  sendWriterRevisionProposal,
  sendProgressProfile,
  sendProgressVocabStats,
  sendProgressWeeklyGoal,
  renderContextBar,
  renderProposalCard,
  renderProposalList,
  renderSafeMarkdownToElement,
  initFloatingCapsule,
  newSession,
  switchSession,
  refreshSessionSelect,
};

if (typeof window !== 'undefined') {
  window.CompanionDrawer = Object.assign(window.CompanionDrawer || {}, CompanionDrawer);
}
