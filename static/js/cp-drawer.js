/* DeLector - Companion Drawer UI Component
 *
 * 依据: docs/specs/2026-10-31-companion-study-agent-design.md §3.1-§3.4
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 构建 (createElement / textContent / appendChild)，彻底杜绝 XSS 隐患。
 * 包含纯 DOM 结构化 Markdown 渲染器（支持标题、代码块、列表、引用、加粗、行内代码）。
 */
'use strict';

import { companionState, setCompanionContext } from './cp-state.js';
import { streamCompanionChat, executeProposal } from './cp-api.js';

let drawerEl = null;
let contextBarEl = null;
let bodyEl = null;
let inputEl = null;
let sendBtnEl = null;
let abortController = null;

/** 解析单行文本的行内样式 (bold, italic, code, del) 并构建纯 DOM 节点 */
function appendInlineFormattedText(targetEl, text) {
  if (!text) return;
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|~~[^~]+~~)/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      const strong = document.createElement('strong');
      strong.textContent = part.slice(2, -2);
      targetEl.appendChild(strong);
    } else if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      const code = document.createElement('code');
      code.textContent = part.slice(1, -1);
      targetEl.appendChild(code);
    } else if (part.startsWith('*') && part.endsWith('*') && part.length >= 2) {
      const em = document.createElement('em');
      em.textContent = part.slice(1, -1);
      targetEl.appendChild(em);
    } else if (part.startsWith('~~') && part.endsWith('~~') && part.length >= 4) {
      const del = document.createElement('del');
      del.textContent = part.slice(2, -2);
      targetEl.appendChild(del);
    } else {
      targetEl.appendChild(document.createTextNode(part));
    }
  }
}

/**
 * 纯 DOM 构建的安全 Markdown 渲染器 (Zero-innerHTML 铁律，彻底杜绝 XSS 注入)
 * 支持标题、围栏代码块、无序/有序列表、引用块、行内加粗/代码
 */
export function renderSafeMarkdownToElement(container, markdown) {
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }
  if (!markdown) return;

  const lines = markdown.split('\n');
  let currentList = null;
  let currentListType = null;
  let inCodeBlock = false;
  let codeBuffer = [];
  let codeLang = '';

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // 1. 代码块围栏 (```)
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        if (codeLang) code.className = 'language-' + codeLang;
        code.textContent = codeBuffer.join('\n');
        pre.appendChild(code);
        container.appendChild(pre);
        inCodeBlock = false;
        codeBuffer = [];
        codeLang = '';
      } else {
        if (currentList) {
          container.appendChild(currentList);
          currentList = null;
          currentListType = null;
        }
        inCodeBlock = true;
        codeLang = trimmed.slice(3).trim();
        codeBuffer = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(rawLine);
      continue;
    }

    // 2. 空行 -> 关闭当前列表
    if (!trimmed) {
      if (currentList) {
        container.appendChild(currentList);
        currentList = null;
        currentListType = null;
      }
      continue;
    }

    // 3. 标题 (#, ##, ###, ####)
    const headerMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headerMatch) {
      if (currentList) {
        container.appendChild(currentList);
        currentList = null;
        currentListType = null;
      }
      const level = headerMatch[1].length;
      const tag = level <= 2 ? 'h4' : level === 3 ? 'h5' : 'h6';
      const headingEl = document.createElement(tag);
      appendInlineFormattedText(headingEl, headerMatch[2]);
      container.appendChild(headingEl);
      continue;
    }

    // 4. 引用块 (> ...)
    if (trimmed.startsWith('>')) {
      if (currentList) {
        container.appendChild(currentList);
        currentList = null;
        currentListType = null;
      }
      const bq = document.createElement('blockquote');
      appendInlineFormattedText(bq, trimmed.slice(1).trim());
      container.appendChild(bq);
      continue;
    }

    // 5. 无序列表 (- ... 或 * ...)
    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      if (!currentList || currentListType !== 'ul') {
        if (currentList) container.appendChild(currentList);
        currentList = document.createElement('ul');
        currentListType = 'ul';
      }
      const li = document.createElement('li');
      appendInlineFormattedText(li, ulMatch[1]);
      currentList.appendChild(li);
      continue;
    }

    // 6. 有序列表 (1. ... 或 2. ...)
    const olMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
    if (olMatch) {
      if (!currentList || currentListType !== 'ol') {
        if (currentList) container.appendChild(currentList);
        currentList = document.createElement('ol');
        currentListType = 'ol';
      }
      const li = document.createElement('li');
      appendInlineFormattedText(li, olMatch[2]);
      currentList.appendChild(li);
      continue;
    }

    // 7. 普通段落
    if (currentList) {
      container.appendChild(currentList);
      currentList = null;
      currentListType = null;
    }

    const p = document.createElement('p');
    appendInlineFormattedText(p, trimmed);
    container.appendChild(p);
  }

  // 收尾
  if (currentList) {
    container.appendChild(currentList);
  }
  if (inCodeBlock && codeBuffer.length > 0) {
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = codeBuffer.join('\n');
    pre.appendChild(code);
    container.appendChild(pre);
  }
}

/** 刷新抽屉顶部视口研读语境条 */
function renderContextBar() {
  if (!contextBarEl) return;
  while (contextBarEl.firstChild) {
    contextBarEl.removeChild(contextBarEl.firstChild);
  }

  const text = companionState.activeContext.selectedText;
  if (text) {
    contextBarEl.style.display = 'flex';
    const icon = document.createElement('span');
    icon.textContent = '📌';
    const textSpan = document.createElement('span');
    textSpan.className = 'companion-context-text';
    textSpan.textContent = '已绑定难句: „' + text + '“';

    const clearBtn = document.createElement('button');
    clearBtn.className = 'companion-context-clear';
    clearBtn.title = '解除难句绑定';
    clearBtn.textContent = '✕';
    clearBtn.addEventListener('click', () => {
      setCompanionContext('', companionState.activeContext.articleTitle, companionState.activeContext.cefrLevel);
      renderContextBar();
    });

    contextBarEl.appendChild(icon);
    contextBarEl.appendChild(textSpan);
    contextBarEl.appendChild(clearBtn);
  } else {
    contextBarEl.style.display = 'flex';
    const hint = document.createElement('span');
    hint.className = 'companion-context-hint';
    hint.textContent = '💡 提示：在文章中划词或点击句子，即可让 Eule 针对性问诊。';

    const grabBtn = document.createElement('button');
    grabBtn.className = 'companion-context-grab-btn';
    grabBtn.textContent = '🎯 抓取当前句';
    grabBtn.addEventListener('click', () => {
      syncCurrentContext();
    });

    contextBarEl.appendChild(hint);
    contextBarEl.appendChild(grabBtn);
  }
}

/** 同步当前阅读器选区或活动难句 */
export function syncCurrentContext() {
  if (window.Companion && window.Companion.harvestStudyContext) {
    const ctx = window.Companion.harvestStudyContext();
    if (ctx.selectedText) {
      setCompanionContext(ctx.selectedText, ctx.articleTitle, ctx.cefrLevel);
      renderContextBar();
      if (bodyEl) {
        const hintDiv = document.createElement('div');
        hintDiv.className = 'companion-message assistant';
        hintDiv.style.borderLeft = '3px solid var(--coral, #b44322)';
        const lbl = document.createElement('div');
        lbl.textContent = '✓ 已同步视口难句：';
        const q = document.createElement('em');
        q.textContent = '„' + ctx.selectedText + '“';
        hintDiv.appendChild(lbl);
        hintDiv.appendChild(q);
        bodyEl.appendChild(hintDiv);
        bodyEl.scrollTop = bodyEl.scrollHeight;
      }
      return;
    }
  }
  alert('未检测到当前选中文本。请在文章中用鼠标划词选中，或点击句子后重试。');
}

/** 初始化抽屉 DOM 挂载 */
export function initCompanionDrawer() {
  if (drawerEl) return drawerEl;

  drawerEl = document.createElement('aside');
  drawerEl.id = 'companion-drawer';
  drawerEl.className = 'companion-drawer';
  drawerEl.setAttribute('aria-label', 'DeLector 伴学助手抽屉');

  // Header
  const headerEl = document.createElement('div');
  headerEl.className = 'companion-drawer-header';

  const titleEl = document.createElement('div');
  titleEl.className = 'companion-drawer-title';
  const iconSpan = document.createElement('span');
  iconSpan.textContent = '🦉';
  const textSpan = document.createElement('span');
  textSpan.textContent = 'Eule · 德语伴学导学伙伴';
  titleEl.appendChild(iconSpan);
  titleEl.appendChild(textSpan);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'companion-drawer-close';
  closeBtn.id = 'companion-drawer-close';
  closeBtn.title = '收起抽屉';
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', closeCompanionDrawer);

  headerEl.appendChild(titleEl);
  headerEl.appendChild(closeBtn);

  // Context Bar (视口语境提示条)
  contextBarEl = document.createElement('div');
  contextBarEl.className = 'companion-context-bar';
  contextBarEl.id = 'companion-context-bar';

  // Body
  bodyEl = document.createElement('div');
  bodyEl.className = 'companion-drawer-body';
  bodyEl.id = 'companion-drawer-body';

  const welcomeMsg = document.createElement('div');
  welcomeMsg.className = 'companion-message assistant';
  const welcomeText = document.createElement('div');
  welcomeText.textContent =
    'Hallo! 我是你的研读伙伴 Eule。选中德语难句点击我，我可以为你深入剖析拓扑结构、语用褒贬或批量制作闪卡。';
  welcomeMsg.appendChild(welcomeText);
  bodyEl.appendChild(welcomeMsg);

  // Footer
  const footerEl = document.createElement('div');
  footerEl.className = 'companion-drawer-footer';

  const quickActionsEl = document.createElement('div');
  quickActionsEl.className = 'companion-quick-actions';
  quickActionsEl.id = 'companion-quick-actions';

  const actions = [
    { act: 'sync', label: '🎯 抓取当前句', prompt: null },
    { act: 'syntax', label: '从句拓扑问诊', prompt: '请帮我分析选中文本的主从句拓扑结构与核心动词位置。' },
    { act: 'vocab', label: '提取核心生词', prompt: '请帮我提取选中文本中的核心 B1/B2 动词与动介搭配，并提议制成生词卡。' },
    { act: 'pragmatics', label: '深挖语用褒贬', prompt: '这个句子在德语母语者的语用习惯中具有怎样的情感色彩与正式度？' }
  ];

  for (const a of actions) {
    const btn = document.createElement('button');
    btn.className = 'companion-quick-chip';
    btn.textContent = a.label;
    if (a.act === 'sync') {
      btn.addEventListener('click', () => syncCurrentContext());
    } else {
      btn.addEventListener('click', () => submitPrompt(a.prompt));
    }
    quickActionsEl.appendChild(btn);
  }

  const inputRowEl = document.createElement('div');
  inputRowEl.className = 'companion-input-row';

  inputEl = document.createElement('input');
  inputEl.type = 'text';
  inputEl.className = 'companion-input';
  inputEl.id = 'companion-input';
  inputEl.placeholder = '输入德语学习疑问或指令...';
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleSend();
  });

  sendBtnEl = document.createElement('button');
  sendBtnEl.className = 'companion-send-btn';
  sendBtnEl.id = 'companion-send-btn';
  sendBtnEl.textContent = '发送';
  sendBtnEl.addEventListener('click', handleSend);

  inputRowEl.appendChild(inputEl);
  inputRowEl.appendChild(sendBtnEl);

  footerEl.appendChild(quickActionsEl);
  footerEl.appendChild(inputRowEl);

  drawerEl.appendChild(headerEl);
  drawerEl.appendChild(contextBarEl);
  drawerEl.appendChild(bodyEl);
  drawerEl.appendChild(footerEl);

  document.body.appendChild(drawerEl);
  renderContextBar();
  return drawerEl;
}

export function openCompanionDrawer(contextPayload) {
  if (!drawerEl) initCompanionDrawer();
  if (contextPayload) {
    setCompanionContext(
      contextPayload.selectedText,
      contextPayload.articleTitle,
      contextPayload.cefrLevel
    );
  }
  companionState.isOpen = true;
  drawerEl.classList.add('is-open');
  renderContextBar();

  if (contextPayload && contextPayload.selectedText) {
    const hintDiv = document.createElement('div');
    hintDiv.className = 'companion-message assistant';
    hintDiv.style.borderLeft = '3px solid var(--coral, #b44322)';

    const label = document.createElement('div');
    label.textContent = '已绑定视口难句：';
    const quote = document.createElement('em');
    quote.textContent = '„' + contextPayload.selectedText + '“';

    hintDiv.appendChild(label);
    hintDiv.appendChild(quote);
    bodyEl.appendChild(hintDiv);
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }
}

export function closeCompanionDrawer() {
  if (!drawerEl) return;
  companionState.isOpen = false;
  drawerEl.classList.remove('is-open');
}

export function toggleCompanionDrawer(contextPayload) {
  if (companionState.isOpen) {
    closeCompanionDrawer();
  } else {
    openCompanionDrawer(contextPayload);
  }
}

function handleSend() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  submitPrompt(text);
}

function submitPrompt(userText) {
  if (companionState.inFlight) return;
  if (!bodyEl) initCompanionDrawer();

  // 1. 渲染用户消息
  const userMsgEl = document.createElement('div');
  userMsgEl.className = 'companion-message user';
  userMsgEl.textContent = userText;
  bodyEl.appendChild(userMsgEl);

  companionState.messages.push({ role: 'user', content: userText });

  // 2. 准备助手气泡
  const asstMsgEl = document.createElement('div');
  asstMsgEl.className = 'companion-message assistant';

  const thoughtEl = document.createElement('div');
  thoughtEl.className = 'companion-thought';
  thoughtEl.style.display = 'none';

  const toolContainerEl = document.createElement('div');
  toolContainerEl.className = 'companion-tool-container';
  toolContainerEl.style.display = 'none';
  toolContainerEl.style.marginBottom = '0.4rem';

  const textBodyEl = document.createElement('div');
  textBodyEl.className = 'companion-text-body';
  textBodyEl.textContent = '...';

  const proposalsContainerEl = document.createElement('div');
  proposalsContainerEl.className = 'companion-proposals-container';

  asstMsgEl.appendChild(thoughtEl);
  asstMsgEl.appendChild(toolContainerEl);
  asstMsgEl.appendChild(textBodyEl);
  asstMsgEl.appendChild(proposalsContainerEl);

  bodyEl.appendChild(asstMsgEl);
  bodyEl.scrollTop = bodyEl.scrollHeight;

  companionState.inFlight = true;
  if (sendBtnEl) sendBtnEl.disabled = true;

  abortController = new AbortController();
  let fullStreamText = '';

  const activeContext = companionState.activeContext.selectedText
    ? {
        selected_text: companionState.activeContext.selectedText,
        article_title: companionState.activeContext.articleTitle,
        cefr_level: companionState.activeContext.cefrLevel
      }
    : null;

  streamCompanionChat({
    messages: companionState.messages,
    context: activeContext,
    signal: abortController.signal,
    onEvent: (event, data) => {
      if (event === 'thought') {
        thoughtEl.style.display = 'block';
        thoughtEl.textContent = data.text || '';
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
            c.textContent = '✓ ' + data.tool + ' 完成: ' + (data.summary || '');
          }
        }
      } else if (event === 'delta') {
        fullStreamText = data.text || '';
        renderSafeMarkdownToElement(textBodyEl, fullStreamText);
      } else if (event === 'proposal') {
        renderProposalCard(proposalsContainerEl, data.proposal);
      } else if (event === 'done') {
        companionState.inFlight = false;
        if (sendBtnEl) sendBtnEl.disabled = false;
        renderSafeMarkdownToElement(textBodyEl, fullStreamText);
        companionState.messages.push({ role: 'assistant', content: fullStreamText });
      } else if (event === 'error') {
        companionState.inFlight = false;
        if (sendBtnEl) sendBtnEl.disabled = false;
        textBodyEl.textContent = '[异常: ' + (data.message_zh || '处理失败') + ']';
        textBodyEl.style.color = 'var(--coral, #b44322)';
      }
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  }).catch((err) => {
    companionState.inFlight = false;
    if (sendBtnEl) sendBtnEl.disabled = false;
    textBodyEl.textContent = '[连接失败: ' + err.message + ']';
    textBodyEl.style.color = 'var(--coral, #b44322)';
  });
}

function renderProposalCard(container, proposal) {
  if (!container || !proposal) return;

  const cardEl = document.createElement('div');
  cardEl.className = 'companion-proposal-card';

  const titleEl = document.createElement('div');
  titleEl.className = 'companion-proposal-title';
  titleEl.textContent = '📝 提议：' + (proposal.title || '生成卡片');
  cardEl.appendChild(titleEl);

  const contentEl = document.createElement('div');
  contentEl.className = 'companion-proposal-content';

  const cards = (proposal.payload && proposal.payload.cards) || [];
  for (const c of cards) {
    const itemEl = document.createElement('div');
    itemEl.style.fontSize = '0.85rem';
    itemEl.style.padding = '0.25rem 0';
    itemEl.style.borderBottom = '1px dashed var(--rule, #dcd6cd)';

    const boldWord = document.createElement('strong');
    boldWord.textContent = c.word || '';
    itemEl.appendChild(boldWord);
    itemEl.appendChild(document.createTextNode(': ' + (c.reading || '')));

    if (c.context_sentence) {
      const sentEl = document.createElement('div');
      sentEl.style.fontSize = '0.78rem';
      sentEl.style.color = 'var(--pencil, #666)';
      sentEl.textContent = '„' + c.context_sentence + '“';
      itemEl.appendChild(sentEl);
    }
    contentEl.appendChild(itemEl);
  }
  cardEl.appendChild(contentEl);

  const actionsEl = document.createElement('div');
  actionsEl.className = 'companion-proposal-actions';

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'companion-btn-confirm';
  confirmBtn.textContent = '确认添加入库';

  const discardBtn = document.createElement('button');
  discardBtn.className = 'companion-btn-discard';
  discardBtn.textContent = '放弃';

  confirmBtn.addEventListener('click', async () => {
    confirmBtn.disabled = true;
    confirmBtn.textContent = '正在入库...';
    try {
      const res = await executeProposal(proposal.id, proposal.action, proposal.payload);
      confirmBtn.style.display = 'none';
      discardBtn.style.display = 'none';
      const statusDiv = document.createElement('div');
      statusDiv.style.color = 'var(--ink, #1a1a1a)';
      statusDiv.style.fontWeight = 'bold';
      statusDiv.style.marginTop = '0.4rem';
      statusDiv.textContent = '✓ 已成功添加 ' + (res.created_count || cards.length) + ' 张生词卡至复习流';
      cardEl.appendChild(statusDiv);
    } catch (err) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = '重试';
      alert('入库失败: ' + err.message);
    }
  });

  discardBtn.addEventListener('click', () => {
    cardEl.style.opacity = '0.5';
    cardEl.style.pointerEvents = 'none';
    discardBtn.textContent = '已放弃';
    confirmBtn.style.display = 'none';
  });

  actionsEl.appendChild(confirmBtn);
  actionsEl.appendChild(discardBtn);
  cardEl.appendChild(actionsEl);

  container.appendChild(cardEl);
}
