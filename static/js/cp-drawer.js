/* DeLector - Companion Drawer UI Component
 *
 * 依据: 方案 A 深度统一设计
 * 将伴学导学作为主抽屉 (#drawer) 的第 5 个专属 Tab 深度集成。
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 构建 (createElement / textContent / appendChild)，彻底杜绝 XSS 隐患。
 * 包含纯 DOM 结构化 Markdown 渲染器（支持标题、表格、代码块、列表、引用、加粗、行内代码）。
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

/** 检测 Markdown 表格分隔行 (|---|---| 或 |:---|:---:|---:|) */
function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-+:?\s*\|)+\s*(:?-+:?\s*)?$/.test(line);
}

/** 分割 Markdown 表格行单元格 */
function splitTableRow(line) {
  let cells = line.trim().split('|');
  if (line.trim().startsWith('|')) cells.shift();
  if (line.trim().endsWith('|')) cells.pop();
  return cells.map((c) => c.trim());
}

/** 解析表格对齐方式 */
function parseAlignments(sepLine) {
  const cells = splitTableRow(sepLine);
  return cells.map((c) => {
    const left = c.startsWith(':');
    const right = c.endsWith(':');
    if (left && right) return 'center';
    if (right) return 'right';
    return 'left';
  });
}

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
 * 支持标题、表格、围栏代码块、无序/有序列表、引用块、行内加粗/代码
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

    // 3. Markdown 表格 (| 场 | 功能 | 典型内容 | + |---|---|---|)
    if (rawLine.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      if (currentList) {
        container.appendChild(currentList);
        currentList = null;
        currentListType = null;
      }
      const headerCells = splitTableRow(rawLine);
      const aligns = parseAlignments(lines[i + 1]);
      i++; // 跳过分隔行

      const table = document.createElement('table');
      const thead = document.createElement('thead');
      const headerTr = document.createElement('tr');

      for (let c = 0; c < headerCells.length; c++) {
        const th = document.createElement('th');
        if (aligns[c]) th.style.textAlign = aligns[c];
        appendInlineFormattedText(th, headerCells[c]);
        headerTr.appendChild(th);
      }
      thead.appendChild(headerTr);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      while (i + 1 < lines.length && lines[i + 1].trim().includes('|')) {
        i++;
        const rowCells = splitTableRow(lines[i]);
        const tr = document.createElement('tr');
        for (let c = 0; c < headerCells.length; c++) {
          const td = document.createElement('td');
          if (aligns[c]) td.style.textAlign = aligns[c];
          appendInlineFormattedText(td, rowCells[c] || '');
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      container.appendChild(table);
      continue;
    }

    // 4. 标题 (#, ##, ###, ####)
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

    // 5. 引用块 (> ...)
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

    // 6. 无序列表 (- ... 或 * ...)
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

    // 7. 有序列表 (1. ... 或 2. ...)
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

    // 8. 普通段落
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

/** 动态同步底部快捷操作选项卡显示状态（有句子时弹跳出，无句子时收起） */
function updateQuickActionChips(hasText) {
  const chips = document.querySelectorAll('.companion-quick-chip.context-required');
  chips.forEach((c) => {
    c.classList.toggle('is-visible', hasText);
  });
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
  const sents = window.state?.currentArticle?.sentences || [];

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
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      setCompanionContext('', companionState.activeContext.articleTitle, companionState.activeContext.cefrLevel);
      renderContextBar();
    });

    contextBarEl.appendChild(icon);
    contextBarEl.appendChild(textSpan);

    // 手机端/精读模式：直接提供上下句无缝步进导航 (◀ 句 3/18 ▶)
    if (sents.length > 0) {
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
      prevBtn.textContent = '◀';
      prevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetIdx = currentIdx > 0 ? currentIdx - 1 : sents.length - 1;
        const targetSent = sents[targetIdx];
        if (targetSent) {
          if (window.state) {
            window.state.activeSelectedSentId = targetSent.id;
            window.state.activeSelectedRangeText = targetSent.text;
          }
          setCompanionContext(targetSent.text, window.state?.currentArticle?.title, window.state?.currentArticle?.cefr_level);
          renderContextBar();
        }
      });

      const indicator = document.createElement('span');
      indicator.className = 'companion-nav-indicator';
      indicator.textContent = (currentIdx >= 0 ? (currentIdx + 1) : '-') + '/' + sents.length;

      const nextBtn = document.createElement('button');
      nextBtn.className = 'companion-nav-btn';
      nextBtn.title = '下一句 (手机快捷点选)';
      nextBtn.textContent = '▶';
      nextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetIdx = (currentIdx >= 0 && currentIdx < sents.length - 1) ? currentIdx + 1 : 0;
        const targetSent = sents[targetIdx];
        if (targetSent) {
          if (window.state) {
            window.state.activeSelectedSentId = targetSent.id;
            window.state.activeSelectedRangeText = targetSent.text;
          }
          setCompanionContext(targetSent.text, window.state?.currentArticle?.title, window.state?.currentArticle?.cefr_level);
          renderContextBar();
        }
      });

      navWrap.appendChild(prevBtn);
      navWrap.appendChild(indicator);
      navWrap.appendChild(nextBtn);
      contextBarEl.appendChild(navWrap);
    }

    contextBarEl.appendChild(clearBtn);
  } else {
    contextBarEl.style.display = 'flex';
    const hint = document.createElement('span');
    hint.className = 'companion-context-hint';
    hint.textContent = '💡 提示：点击正文中 🦉伴学 或词汇，即可让 Eule 针对性问诊。';

    const grabBtn = document.createElement('button');
    grabBtn.className = 'companion-context-grab-btn';
    grabBtn.textContent = '🎯 抓取当前句';
    grabBtn.addEventListener('click', () => {
      syncCurrentContext();
    });

    contextBarEl.appendChild(hint);
    contextBarEl.appendChild(grabBtn);
  }

  updateQuickActionChips(Boolean(text));
}

/** 同步当前阅读器选区或活动难句 */
export function syncCurrentContext() {
  if (window.Companion && window.Companion.harvestStudyContext) {
    const ctx = window.Companion.harvestStudyContext();
    if (ctx.selectedText) {
      setCompanionContext(ctx.selectedText, ctx.articleTitle, ctx.cefrLevel);
      renderContextBar();
      if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
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
  alert('未检测到当前选中文本。请在文章中点击句旁的 [🦉 伴学]，或点击单词后重试。');
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

  renderContextBar();
  return container;
}

export function openCompanionDrawer(contextPayload) {
  initCompanionDrawer();
  if (contextPayload) {
    setCompanionContext(
      contextPayload.selectedText,
      contextPayload.articleTitle,
      contextPayload.cefrLevel
    );
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

  if (contextPayload && contextPayload.selectedText) {
    if (!bodyEl) bodyEl = document.getElementById('companion-drawer-body');
    if (bodyEl) {
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

export function submitPrompt(userText) {
  if (companionState.inFlight) return;
  if (!userText || !userText.trim()) return;

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

  companionState.inFlight = true;
  if (!sendBtnEl) sendBtnEl = document.getElementById('companion-send-btn');
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

  const typewriter = new AdaptiveTypewriter(textBodyEl, {
    onProgress: () => {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    },
    onComplete: () => {
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  });

  streamCompanionChat({
    messages: companionState.messages,
    context: activeContext,
    signal: abortController.signal,
    onEvent: (event, data) => {
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
        renderProposalCard(proposalsContainerEl, data.proposal);
      } else if (event === 'done') {
        thoughtCtrl.finish();
        companionState.inFlight = false;
        if (sendBtnEl) sendBtnEl.disabled = false;
        typewriter.flush();
        if (fullStreamText) {
          renderSafeMarkdownToElement(textBodyEl, fullStreamText);
        }
        companionState.messages.push({ role: 'assistant', content: fullStreamText });
      } else if (event === 'error') {
        typewriter.cancel();
        thoughtCtrl.fail('研读中断');
        companionState.inFlight = false;
        if (sendBtnEl) sendBtnEl.disabled = false;
        textBodyEl.textContent = '[异常: ' + (data.message_zh || '处理失败') + ']';
        textBodyEl.style.color = 'var(--coral, #b44322)';
      }
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  }).catch((err) => {
    typewriter.cancel();
    thoughtCtrl.fail('连接中断');
    textBodyEl.textContent = '[连接失败: ' + err.message + ']';
    textBodyEl.style.color = 'var(--coral, #b44322)';
  }).finally(() => {
    thoughtCtrl.cleanup();
    companionState.inFlight = false;
    if (sendBtnEl) sendBtnEl.disabled = false;
    bodyEl.scrollTop = bodyEl.scrollHeight;
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

function createThoughtAccordion() {
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
      boxEl.classList.remove('is-expanded'); // Auto-collapse to focus on answer

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
