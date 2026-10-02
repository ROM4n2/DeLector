# ADR-0007: 精读句法拓扑行内幽灵微胶囊主动触发与心流保护架构

- **状态**: Accepted
- **日期**: 2026-09-05
- **作者**: Lead Socratic Inquisitor & Fullstack Architect
- **领域**: Reader UX / Syntax Analysis / Interaction Architecture

---

## 1. 背景与问题定义 (Context & Problem Statement)

在路线 C（Grammatik-Radar）的最初实现中，为了降低读者查阅句法信息的步数，引入了「光标停留句子 600ms 自动防抖触发右侧句法抽屉」的机制。
但在真实阅读与精读场景中暴露出了严重的可用性缺陷：
1. **心流被动打断 (Cognitive & Flow Disruption)**：读者的光标在行间移动、阅读跟读时，只要无意停顿 600ms，屏幕右侧即猛然划出大面板并切换焦点，造成明显的界面闪烁与干扰。
2. **生词查词抽屉被强行冲刷 (Drawer State Thrashing)**：读者刚点击一个生词正在右侧查看释义与搭配，鼠标悬停在另一句时句法抽屉被强行激活，冲掉正在学习的单词卡片。
3. **句法剖析属于高负荷按需工具 (On-Demand Deep Dive)**：拓扑五场域、从句树与复杂度雷达是深度认知辅助工具，应当在读者遇到看不懂的长难句时由读者**明确主动发起 (Explicit User Intent)**。

---

## 2. 决策驱动因素 (Decision Drivers)

- **心流优先 (Focus-First / Zero-Friction Reading)**：阅读界面必须安静，普通阅读时正文排版不得有粗笨固定的杂乱按钮。
- **意图明确 (Explicit Intent vs Accidental Trigger)**：只有在用户明确点击时才触发大面积抽屉展开与语料复杂度雷达的异步统计。
- **状态隔离 (No Drawer State Thrashing)**：绝不在用户阅读或查词时静默覆盖当前抽屉状态。
- **Academic Modern Editorial 审美规范**：微型胶囊按钮平时隐形（幽灵状态），鼠标进入句子单元才轻巧淡入，保持德式印刷的纯净质感。

---

## 3. 备选方案考量 (Considered Options)

- **Option 1: 保持 600ms Hover 自动触发**：
  - *缺点*：心流侵入严重，鼠标游走带来状态混乱与不必要请求，被否决。
- **Option 2: 划选/选中弹出悬浮工具栏 (Selection Floating Menu)**：
  - *缺点*：划选句子对单句完整句法分析路径过长，且存在复杂的绝对定位与移动端触摸冲突。
- **Option 3: 行内幽灵微胶囊按钮 (Quiet Ghost Pill on Hover) [选中方案]**：
  - *优点*：平时 `opacity: 0`，正文阅读 0 干扰；光标移入句子 `.reader-sent-unit` 时平滑过渡到微弱透明度；点击 `🌳 句法` 才显式打开抽屉；彻底消除全局定时器与意外弹窗。

---

## 4. 架构决策 (Decision Outcome)

决定采用 **行内幽灵微胶囊按钮（Option A） + 显式点击打开右侧主抽屉（Option 1）**：

1. **DOM 结构规范**：
   在 `static/js/reader.js` 的 `sentWrapper` 模板中，在句子内容末尾保留幽灵胶囊按钮：
   ```html
   <button class="sent-syntax-btn" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sent.id)})" title="展开德语拓扑五场域、从句树与句法雷达">🌳 句法</button>
   ```
2. **CSS 幽灵交互规范**：
   在 `static/style.css` 中：
   - 默认态：`.sent-syntax-btn` 设为 `opacity: 0; pointer-events: none;`，不占据视觉焦点，不干扰文本连续排版。
   - 悬停态：`.reader-sent-unit:hover .sent-syntax-btn` 优雅渐变 `opacity: 0.65; pointer-events: auto;`。
   - 激活/悬浮态：`.sent-syntax-btn:hover` 高亮 `opacity: 1; background: var(--paper-warm); border-color: var(--accent); color: var(--accent);`。
3. **彻底移除悬停定时器**：
   完全废除 `_syntaxHoverTimer` 及 `mouseenter/mouseleave` 自动打开抽屉的监听器，杜绝后台游离计时器与非预期请求。

---

## 5. 影响与后效 (Consequences)

### 正面效益
- 阅读心流 100% 保持纯粹，文章排版干净整洁。
- 只有读者真正需要探索长难句结构时主动点击，抽屉才展开，符合真实学习场景。
- 彻底避免冲掉生词查词抽屉，状态流清晰稳定。
- 代码精简，移除防抖定时器，降低前端状态机复杂度。

### 负面效益 / 缓解措施
- 触发句法需要多一次明确点击操作（这正是用户所期望的主动交互而非负担）。