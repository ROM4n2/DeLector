---
title: "ADR-0025: 伴学 Agent 视口上下文注入、跨 Span 选区空格对齐与正文零侵入悬浮胶囊"
created: 2026-10-31
updated: 2026-10-31
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/frontend-architecture
  - topic/agent-development
  - topic/nlp-ux
status: accepted
audience:
  - architect
deciders: 用户
supersedes: none
related: [01-Rules/AGENT-CONTEXT-STANDARDS.md, 08-Projects/DeLector/DELECTOR-DEV-RULES.md]
verified: 2026-10-31
description: "DeLector 伴学 Agent 视口上下文强注入、分词阅读器跨 span 选区空格还原算法（restoreSentenceSpaces）与正文零侵入选区悬浮胶囊架构决策。"
---

# ADR-0025：伴学 Agent 视口上下文注入、跨 Span 选区空格对齐与正文零侵入悬浮胶囊

## Status
已接受（2026-10-31）。源于 DeLector 德语伴学 Agent 交互与空格断链排障复盘。

## Context
在 DeLector 精读 Web 工作台中，伴学导学 Agent 与学员交互面临三大核心矛盾：
1. **Agent 虚假失忆与文本 Token 坍缩**：正文由分词器将每个词元渲染为 `<span class="tok">` 且无文本空白节点。跨 span 划词时，`window.getSelection().toString()` 仅拼接各 span 的 `textContent`，导致文本丢失空格（如 `SiekönnendenArtikelleidernichtmehraufrufen`）。下游大模型 Tokenizer 判定为无意义乱码，反向向学员输出：“对话中未给出具体句子，缺少上下文”。
2. **正文蜂窝状视觉污染**：此前为方便触发句法与伴学，在每个句子末尾硬编码内联徽章 `[🌳 句法][🦉 伴学]`，破坏了德语分词韵律与动词闭合框（Rechte Klammer），正文呈碎片化“蜂窝状”，背离沉浸式学术印刷体验。
3. **移动端触控选区困境**：移动端触屏长按拖选难句成本极高，容易误触。

## Decision

### 1. 跨 Span 选区空格对齐还原算法 (`restoreSentenceSpaces`)
在前端选区提取出口层，禁止直接向后端传递裸 `window.getSelection().toString()`。必须利用底层句子权威文本 `sent.text` 进行双指针空间空格重构：
- 若选中文本已含空格则直接返回；
- 若选区在去除空白后与全句一致，直接返回清洗后的全句；
- 若为局部短语，在 `fullSentenceText` 中双指针滑动比对，跳过空格字符逐字匹配，精确截取包含原生空格的原始文本切片。

```javascript
export function restoreSentenceSpaces(selectedText, fullSentenceText) {
  if (!selectedText || !fullSentenceText) return selectedText;
  if (selectedText.includes(" ")) return selectedText;

  const sClean = selectedText.replace(/\s+/g, "");
  const fClean = fullSentenceText.replace(/\s+/g, "");

  if (sClean === fClean || sClean === fClean.replace(/[.?!;:]+$/, "")) {
    return fullSentenceText.trim();
  }

  let fIdx = 0;
  while (fIdx < fullSentenceText.length) {
    if (fullSentenceText[fIdx] === sClean[0]) {
      let tempF = fIdx;
      let tempS = 0;
      while (tempF < fullSentenceText.length && tempS < sClean.length) {
        if (/\s/.test(fullSentenceText[tempF])) {
          tempF++;
          continue;
        }
        if (fullSentenceText[tempF] === sClean[tempS]) {
          tempF++;
          tempS++;
        } else {
          break;
        }
      }
      if (tempS === sClean.length) {
        return fullSentenceText.slice(fIdx, tempF);
      }
    }
    fIdx++;
  }
  return selectedText;
}
```

### 2. 视口语境强注入与反问熔断机制
在后端 Agent 核心循环中，将视口研读难句注入为最高优先级的系统事实块，并施加**严禁反问指令**：
- 注入当前视口难句、所属文章与目标 CEFR 难度级别；
- 明确指示：*“当学员询问‘这个句子’、‘拓扑结构’或生词时，均默认针对【当前视口研读难句】直接深入分析，切勿向学员反问或索要句子！”*

### 3. 正文零侵入悬浮胶囊 (Floating Capsule) 与抽屉步进器
- **正文纯净回归**：彻底剥离正文内联常驻按钮；
- **选区悬浮胶囊**：划词选中后，在选区正上方动态浮现精致高斯模糊工具条（`[🌳 句法]`、`[🦉 问伴学]`、`[📝 随笔]`、`[🔊 朗读]`），点击即直达对应抽屉 Tab 并自动关闭胶囊；
- **抽屉内置步进器**：伴学抽屉顶部语境条提供 `[ ◀ 上一句 ] [ 句 N/M ] [ 下一句 ▶ ]`，移动端读者单手轻触即可逐句浏览问诊；
- **动态弹跳操作项**：依赖句子的快捷问诊 Chip（从句拓扑、核心生词）在无句子时默认收拢，锁定难句后通过 `@keyframes chipBouncePop` 动画优雅弹出。

## Consequences
- **正面收益**：彻底解决跨 span 划词无空格导致的 Agent 误诊问题；正文排版恢复沉浸式学术杂志美感；移动端交互大幅提效。
- **守卫与测试**：
  - 4 道前端与伴学契约检查门禁 100% 通过；
  - 后端专项单测 `pytest tests/test_companion_*.py` 16 passed；
  - 通用规范沉淀至 [[01-Rules/AGENT-CONTEXT-STANDARDS#4.1 分词选区文本与视口语境对齐范式 (Study Viewport Context Hygiene) (MUST)]]。
