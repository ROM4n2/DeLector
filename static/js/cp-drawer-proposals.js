/* DeLector - Companion Drawer Proposal Cards Component
 *
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 构建 (createElement / textContent / appendChild)。
 * 支持结构化生词/语法卡片提议渲染、状态徽标 (pending / accepted / rejected) 以及异步操作回调。
 */
'use strict';

/**
 * 渲染单个提议交互卡片
 * @param {HTMLElement} container - 挂载卡片的父容器
 * @param {Object} proposal - 提议数据对象 { id, title, action, payload, status }
 * @param {Function} [onAction] - 操作回调函数 (proposal, action) => Promise<any> | void
 * @returns {HTMLElement|null}
 */
export function renderProposalCard(container, proposal, onAction) {
  if (!container || !proposal) return null;

  const cardEl = document.createElement('div');
  cardEl.className = 'companion-proposal-card';
  if (proposal.id) {
    cardEl.dataset.proposalId = String(proposal.id);
  }

  // 1. 标题
  const titleEl = document.createElement('div');
  titleEl.className = 'companion-proposal-title';
  titleEl.textContent = '📝 提议：' + (proposal.title || '生成卡片');
  cardEl.appendChild(titleEl);

  // 2. 提议内容详情
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

  // 3. 操作区与状态徽标
  const actionsEl = document.createElement('div');
  actionsEl.className = 'companion-proposal-actions';
  actionsEl.style.display = 'flex';
  actionsEl.style.alignItems = 'center';
  actionsEl.style.gap = '0.5rem';
  actionsEl.style.marginTop = '0.5rem';

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'companion-btn-confirm';
  confirmBtn.textContent = '确认添加入库';

  const rejectBtn = document.createElement('button');
  rejectBtn.className = 'companion-btn-discard';
  rejectBtn.textContent = '放弃';

  const badgeEl = document.createElement('span');
  badgeEl.className = 'companion-proposal-badge';
  badgeEl.style.display = 'none';

  actionsEl.appendChild(confirmBtn);
  actionsEl.appendChild(rejectBtn);
  actionsEl.appendChild(badgeEl);
  cardEl.appendChild(actionsEl);

  // 4. 状态同步逻辑
  function applyStatus(status) {
    if (status === 'accepted') {
      confirmBtn.disabled = true;
      confirmBtn.style.display = '';
      rejectBtn.style.display = 'none';
      badgeEl.className = 'companion-proposal-badge companion-proposal-badge--accepted';
      badgeEl.style.display = 'inline-flex';
      badgeEl.style.alignItems = 'center';
      badgeEl.style.color = 'var(--moss, #2e6b3e)';
      badgeEl.style.fontWeight = 'bold';
      badgeEl.textContent = '✓ 已收录';
      cardEl.classList.add('is-accepted');
      cardEl.classList.remove('is-rejected');
      cardEl.style.opacity = '1';
    } else if (status === 'rejected' || status === 'discarded') {
      confirmBtn.style.display = 'none';
      rejectBtn.style.display = 'none';
      badgeEl.className = 'companion-proposal-badge companion-proposal-badge--rejected';
      badgeEl.style.display = 'inline-flex';
      badgeEl.style.alignItems = 'center';
      badgeEl.style.color = 'var(--pencil, #888888)';
      badgeEl.textContent = '已忽略';
      cardEl.classList.add('is-rejected');
      cardEl.classList.remove('is-accepted');
      cardEl.style.opacity = '0.6';
    } else {
      // pending
      confirmBtn.disabled = false;
      confirmBtn.style.display = '';
      confirmBtn.textContent = '确认添加入库';
      rejectBtn.disabled = false;
      rejectBtn.style.display = '';
      rejectBtn.textContent = '放弃';
      badgeEl.style.display = 'none';
      cardEl.classList.remove('is-accepted', 'is-rejected');
      cardEl.style.opacity = '1';
    }
  }

  // 初始状态判定
  applyStatus(proposal.status || 'pending');

  // 5. 事件绑定
  confirmBtn.addEventListener('click', async () => {
    confirmBtn.disabled = true;
    const oldText = confirmBtn.textContent;
    confirmBtn.textContent = '正在入库...';
    try {
      if (typeof onAction === 'function') {
        await onAction(proposal, 'confirm');
      }
      proposal.status = 'accepted';
      applyStatus('accepted');
    } catch (err) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = oldText || '确认添加入库';
      console.error('Proposal execution failed:', err);
      alert('入库失败: ' + (err.message || '未知错误'));
    }
  });

  rejectBtn.addEventListener('click', async () => {
    try {
      if (typeof onAction === 'function') {
        await onAction(proposal, 'reject');
      }
      proposal.status = 'rejected';
      applyStatus('rejected');
    } catch (err) {
      console.error('Proposal rejection failed:', err);
    }
  });

  container.appendChild(cardEl);
  return cardEl;
}

/**
 * 批量渲染提议列表
 * @param {HTMLElement} container - 挂载列表的父容器
 * @param {Array<Object>} proposals - 提议数组
 * @param {Function} [onAction] - 操作回调函数 (proposal, action) => Promise<any> | void
 */
export function renderProposalList(container, proposals, onAction) {
  if (!container) return;
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }
  if (!Array.isArray(proposals) || proposals.length === 0) return;

  for (const proposal of proposals) {
    renderProposalCard(container, proposal, onAction);
  }
}
