/* DeLector - Companion Drawer Safe Markdown Renderer
 *
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 构建 (createElement / textContent / appendChild)，彻底杜绝 XSS 隐患。
 * 支持标题 (#, ##, ###, ...)、Markdown 表格、围栏代码块 (```)、无序/有序列表、
 * 引用块 (>)、以及行内样式 (加粗 **word**、斜体 *word*、行内代码 `code`、删除线 ~~word~~)。
 */
'use strict';

/** 检测 Markdown 表格分隔行 (|---|---| 或 |:---|:---:|---:|) */
export function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-+:?\s*\|)+\s*(:?-+:?\s*)?$/.test(line);
}

/** 分割 Markdown 表格行单元格 */
export function splitTableRow(line) {
  const cells = line.trim().split('|');
  if (line.trim().startsWith('|')) cells.shift();
  if (line.trim().endsWith('|')) cells.pop();
  return cells.map((c) => c.trim());
}

/** 解析表格对齐方式 */
export function parseAlignments(sepLine) {
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
export function appendInlineFormattedText(targetEl, text) {
  if (!text || !targetEl) return;
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
 * @param {HTMLElement} container - 渲染目标的父容器节点
 * @param {string} markdownText - 待解析并渲染的 Markdown 源码
 */
export function renderSafeMarkdownToElement(container, markdownText) {
  if (!container) return;
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }
  if (!markdownText) return;

  const lines = String(markdownText).split('\n');
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

    // 4. 标题 (#, ##, ###, ####, #####, ######)
    const headerMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
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

    // 6. 无序列表 (- ... 或 * ... 或 + ...)
    const ulMatch = trimmed.match(/^[-*+]\s+(.+)$/);
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
