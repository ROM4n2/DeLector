# ADR-0026: 沉浸式学术精读排版重塑与 CEFR 词阶分级视觉降噪

- **状态**：ACCEPTED
- **日期**：2026-11-01
- **决策者**：席皓宇 (Haoyu Xi), Hermes Agent
- **关联 ADR**：
  - [[0007-reader-syntax-ghost-pill-explicit-trigger]] (前序：正文句法胶囊隐式触发)
  - [[0006-workbench-zettelkasten-editorial-redesign]] (学术出版物设计规范)
  - [[0025-companion-agent-native-tool-calling-and-streaming]] (伴学抽屉与分析流)

---

## 1. 背景与问题陈述 (Context and Problem Statement)

DeLector 定位为德语学术精读与歌德/德福备考工作台。在 `v5.20.1` 的真实阅读界面使用中，暴露出破坏阅读沉浸感的两项严重视觉与排版缺陷：

1. **段落物理碎裂（HTML5 标准违背）**：
   - `reader.js` 在渲染段落时，在 `<p class="reader-p">` 内部为每个句子强行拼接了用于行内拓扑展开的 `<div class="sentence-topology-strip hidden">`；
   - 依据 W3C HTML5 解析标准，`<p>` 属于行内短语内容（Phrasing Content）容器。当浏览器解析器在 `<p>` 内部遇到块级 `<div>` 时，会**强制自动闭合前置 `<p>` 标签**；
   - 导致整篇德文长文被浏览器物理肢解为大量散落的单句短行，自然排版段落流被彻底破坏。

2. **全量色块过载（五彩斑斓碎花布效应）**：
   - `style.css` 对 `A1 / A2 / B1 / B2 / C1` 全部赋予了显性彩色实心底色（蓝、绿、黄、橙、紫）；
   - 德语中高频的 A1/A2 基础词汇（冠词、代词、基础介词等）占据文章 70%~80% 的字数。全词无差别上色导致背景噪声喧宾夺主，丧失了难度预警的信噪比，造成强烈视觉疲劳。

3. **行内按钮侵入阅读流**：
   - 句子末尾内联的 `🌳 句法` 按钮直接打断了连贯的长难句认读节奏。

---

## 2. 决策驱动力 (Decision Drivers)

- **神圣文本流（Sacred Editorial Text Flow）**：阅读器必须呈现出版级德语期刊排版质感，段落完整连贯，具备正确的缩进与行间呼吸感。
- **高信噪比难度透视**：消除 80% 无效背景色块，让读者的注意力集中在文本语义本身；真正的高阶难词（C1）与考点结构在需要时自然浮现。
- **零破坏向下兼容**：保留既有 CEFR 标注、可分离动词配对、句子分段和单句划词查词的所有底层元数据契约。

---

## 3. 备选方案权衡 (Considered Options)

### 3.1 段落解耦架构
- **方案 1A（拓扑条彻底移出正文流，收敛至侧边抽屉或浮层）[CHOSEN]**：
  正文 `<p>` 仅保留纯粹的 `<span class="reader-sent-unit">` 行内结构。拓扑五场域分析统一收敛在右侧助手面板或交互抽屉中，正文彻底免除 `<div>` 侵入。
- **方案 1B（行内伪元素挂载，按需动态插拔）[DISCARDED]**：
  在段落后按需动态插入块容器。仍会引起段落局部重排与几何形变，增加 DOM 状态机复杂度。

### 3.2 词阶视觉降噪策略
- **方案 2A（视觉基线清零法）**：A1/A2 彻底透明底色，B1/B2 弱化，C1 保留点缀。
- **方案 2B（多档视力透视开关）**：沉浸 / 考点 / 全景三档手动切换。
- **方案 2C（方案 2A + 方案 2B 组合演进）[CHOSEN]**：
  默认采用基线清零法则（A1/A2 纯净底色），同时在阅读控制区提供透视档位切换，兼顾日常沉浸精读与考前地毯式词汇排查。

---

## 4. 决策定案 (Decision Outcome)

选择 **方案 1A + 方案 2C**。

### 核心规范定义

1. **正文 DOM 纯净化契约 (`reader.js`)**：
   - 彻底移除 `<p class="reader-p">` 内所有 `<div class="sentence-topology-strip">` 预埋节点；
   - 保持 `<p class="reader-p">` 内纯行内短语元素契约：`<span class="reader-sent-unit">` 包含 `<span class="sent-text-wrap">` 及纯文本；
   - 德语拓扑五场域的查看直接联动右侧分析抽屉（`#drawer-syntax-section`），不再于正文行间做破坏性几何展开。

2. **设计系统词阶视觉 Token 重塑 (`tokens.css` / `style.css`)**：
   - **A1 / A2（基石词）**：`background: transparent`，文本颜色使用经典正文字色，彻底移除底色干扰；
   - **B1 / B2（进阶词）**：`background: transparent`，下沿辅以极细低对比度弱底纹（0.08 alpha），非悬浮状态近乎无感；
   - **C1（考纲核心难词）**：赋予轻柔学术点缀色（`var(--hl-C1)` 柔和淡紫底色或经典珊瑚印章色下划线），形成清晰的精读注意力焦点；
   - **高亮与交互**：鼠标悬停、划词选中（`.tok.sel`）与可分离动词配对（`.separable-prefix`）依然具备即时高对比度交互反馈。

3. **阅读器视力透视三档模式**：
   - `reader-mode-immersive`（默认）：沉浸精读模式，基线清零，正文连贯如印刷期刊；
   - `reader-mode-exam`：考点聚焦模式，仅高亮 B2/C1 及考纲固定搭配；
   - `reader-mode-heatmap`：全量热力模式，保留历史全量 CEFR 彩色图谱，供快速扫读统计。

---

## 5. 预期结果与验证指标 (Consequences & Verification)

- **正面收益**：
  - 彻底根除段落被拆成单句断行的 HTML5 解析异常，恢复德语学术期刊排版；
  - 消除 80% 无谓的五彩底色块，信噪比显著提升，长文阅读心流得以保持；
  - DOM 节点数量减少约 30%（移除了全篇所有预埋的 `sentence-topology-strip`），降低移动端与低配设备渲染负担。
- **工程验证指标**：
  - W3C DOM 校验：`<p>` 内部无任何 Flow Content（`<div>`）节点；
  - 门禁回归：`tests/test_frontend_layers.py`、`tests/test_frontend_security.py` 及全量测试 100% 保持绿色。
