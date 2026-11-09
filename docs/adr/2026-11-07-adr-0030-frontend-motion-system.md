# ADR-0030：前端动效系统——5 个 token、三件套类与 reduce 降级

- **状态**：Accepted（2026-11-07）
- **日期**：2026-11-07
- **决策者**：DeLector 维护者 + 用户（计划 §8 四项拍板后执行）
- **关联**：ADR-0029（不变量 I1、动效边界、失败信号 §6）、[动效调研](../research/2026-11-07-motion-vitality-research.md)、[实施计划](../plans/archive/2026-11-07-frontend-completion-and-motion-vitality.md)
- **性质**：**新增**，不取代 ADR-0029。ADR-0029 §3.5 只把「动效 token」列为一个待新增类别，未定义系统、降级策略与验收口径；本 ADR 补上这一层。

---

## 1. 背景

ADR-0029 完成字形清零后，界面需要新的注意力锚点。调研（`docs/research/2026-11-07-motion-vitality-research.md`）给出三条约束：

1. 阅读面接近零动效也能成立（Obsidian Help 正文无位移，NN/g 文章页仅 4 个元素、150ms）。
2. 功能面 hover 预算应花在颜色/阴影上，不花在位移上（GitHub 抽样 80 条 hover，仅 2 条带 `transform`）。
3. 实测 `static/` 有 22 个 `@keyframes`、**13 处 `infinite`**（此前估计 4 处），其中 3 个直接作用在阅读正文上。

若每个任务各写一套时长/位移/降级，会出现数值漂移与漏降级。因此需要一层最小的动效基建，只统一「一次性入场 / 错峰 / 数字计数 / 按压」四件事。

---

## 2. 决策

### 2.1 五个 token（唯一数值源）

在 `static/css/tokens.css` 定义，并在 `static/style.css :root` **镜像一份**：

| token | 值 | 用途 |
|---|---|---|
| `--motion-enter` | `180ms` | 一次性入场时长 |
| `--motion-enter-shift` | `4px` | 入场位移（仅 translateY） |
| `--motion-press` | `100ms` | 按压反馈时长 |
| `--motion-count` | `520ms` | 数字首现计数（唯一超过 260ms 的例外） |
| `--motion-stagger-step` | `40ms` | 列表错峰步长 |

**必须双份镜像**：主应用 `static/index.html` 只加载 `style.css`；`tokens.css` 仅 workbench 加载。单点定义会让 `.dl-enter` 在主应用拿不到时长。两套 token 在本仓本就互为镜像。

### 2.2 三个 CSS 原语

```css
@keyframes dl-fade-up {
  from { opacity: 0; transform: translateY(var(--motion-enter-shift)); }
}
.dl-enter { animation: dl-fade-up var(--motion-enter) var(--ease-editorial) both; }
.dl-stagger > * { animation-delay: calc(var(--stagger-index, 0) * var(--motion-stagger-step)); }
.dl-count { font-variant-numeric: tabular-nums; }
```

- `.dl-enter` 只负责单次淡入上移；`.dl-stagger` 只设延迟，动画必须落在子元素上。
- `.dl-count` **不承担动画**，只统一数字等宽，避免计数时宽度抖动。
- 错峰序号 `--stagger-index` 封顶在 `cap - 1`（默认 6），第 7 项起不再累加延迟。

### 2.3 四个运行时函数（`static/js/motion.js`）

| 函数 | 职责 |
|---|---|
| `prefersReducedMotion()` | 读 `matchMedia("(prefers-reduced-motion: reduce)")` |
| `stagger(root, {step, cap})` | 分配 `--stagger-index`；reduce 下清序号并返回 0 |
| `enterOnce(root, {cap})` | 挂类 → 播放 → **动画结束后自动摘类与序号** |
| `countUp(el, to, {duration, format})` | 一次性递增；reduce 或 token 缺失时直接落终态 |

约束：

- JS 不复制数值，毫秒值从 `getComputedStyle(document.documentElement)` 读 token。
- 无第三方 import，不引入 `revealOnce`（首屏内容不做滚动触发，YAGNI）。
- `enterOnce` 必须摘类：`.view` 靠 `display:none/block` 切换，`display` 变化会让 CSS 动画从头重播；不摘类等于每次切回视图都重播。

### 2.4 一次性语义

- 入场、单卡网格、搜索结果分组、考试模块网格：**只在首次渲染触发**；重渲染、翻页、换关键词、切回视图均不重播。
- 数字计数：由 `#view-progress` 的 `dataset.countPlayed` 一次性门控；每项同时设 `aria-label` 为最终值，不加 `aria-live`。
- 浮层 `.enc-popover` 只统一入口时长，不新增关闭动画（避免 `setTimeout` / `animationend` 竞态）。

### 2.5 动效预算（硬约束）

- 允许：`opacity`、颜色、`box-shadow`、`border-color`、`transform: translateY(≤4px)`、`scale(0.95–1.0)`。
- 禁止：`width / height / top / left / margin` 动画（触发布局）。
- 时长：一次性 ≤260ms；按压 100–150ms；hover 80–180ms；计数 520ms 为唯一例外。
- 阅读面零位移：`reader` 正文词元、`writer` 编辑器正文、考试题干/选项不得有入场、位移、缩放、呼吸。

### 2.6 循环白名单（7 处，全部有 reduce 降级）

| 动画 | 位置 | 语义 |
|---|---|---|
| `typingCursorBlink` | `style.css` | 打字光标（正在发生的事） |
| `charBlink` | `style.css` | 角色眨眼（角色身份） |
| `companionIdle` ×2 | `style.css` | 伴读待机（唯一常驻角色动效） |
| `marqueeLeft` / `marqueeRight` | `style.css` | 空态滚动（已有 reduce） |
| `pulse` | `workbench.css` | 音频忙碌（加载语义） |

白名单外的循环一律删除或改一次性。M1 删除了 `tokenPulse` / `pulse-linked` / `pulse-clause` / `thoughtInkPulse` / `pulseDot` 五个 keyframes。

### 2.7 降级策略

1. 全局兜底：`prefers-reduced-motion: reduce` 下所有动画/过渡压到 `0.01ms`，`animation-iteration-count: 1`，`scroll-behavior: auto`。
2. 显式终态：`.dl-enter` / `.dl-stagger > *` 设 `animation: none`，避免 `.01ms` 的「完成态动画」仍出现在 `getAnimations()`。
3. 按压：`.btn:active { transform: none }`。
4. JS：`prefersReducedMotion()` 为真时不出入场、不计数，直接落终态，且不留类（用户会话中途关掉 reduce 也不会突然补播）。

---

## 3. 被否决的选项

| 选项 | 否决理由 |
|---|---|
| 每个任务自定义时长/位移 | 数值漂移，且容易漏掉 reduce 分支 |
| 用 `transition` 做入场 | 需要先改初始态再改终态，时序难控；`animation ... both` 更简单 |
| 给正文/表格行/搜索结果文本逐条入场 | 阅读节奏被打断，触停止门 #2 |
| 滚动触发的 `revealOnce` | 首屏内容不需要滚动触发，YAGNI |
| 计数每次进入都播 | 烦躁；只播一次并保持 `aria-label` 终值 |
| 为关闭浮层加退场动画 | 引入定时器/事件竞态，收益低 |
| 保留装饰性循环动画 | 阅读时持续抢占注意力，违反 ADR-0029 |

---

## 4. 后果与失败信号

**正面**：动效数值只有一个来源；每个新增动画都有现成的 reduce 分支；阅读面保持静态；22 个 keyframes 的循环从 13 处收敛到 7 处白名单。

**负面 / 已知边界**：

- token 必须在 `tokens.css` 与 `style.css :root` 各写一份，存在漂移风险；由静态检查与探针兜底。
- `enterOnce` 的摘类依赖 `setTimeout`；若视图在动画期间被销毁，定时器仍会执行，但只操作已脱离文档的节点，无可见副作用。

**失败信号（出现任一即应重开本 ADR）**：

1. 任一动画在 reduce 下仍有位移或持续播放。
2. 阅读面出现新增动画或位移（含 4px）。
3. 同一页面同时运行动画 >6 个，或出现掉帧/布局抖动。
4. 新增第 8 处 `infinite`，且不在白名单内。
5. 新动效需要 `width / height / top / left / margin` 才能实现。

---

## 5. 落地记录

| 项 | PR | merge commit | 落地事实 |
|---|---|---|---|
| M1 循环收口 | #257 | `e840467` | 13 处 `infinite` → 7 处白名单；删除/降级 5 个 keyframes |
| T2 基建 | #258 | `3a2e957` | 5 token 双份镜像；`motion.js`；三件套类；全局 reduce 块 |
| T5 入场 | #261 | `8217dfd` | `enterOnce`；搜索分组、卡片网格、考试模块网格首次入场；cap 6 |
| T6 计数 | #262 | `97f4ac3` | 6 个统计数字 520ms 一次性计数；`aria-label` 终值 |
| T7 浮层 | #263 | `4821bf3` | `.enc-popover` 入口时长 token 化；无关闭动画 |
| T8 按压 | #264 | `61be846` | `.btn:active` `scale(.98)` / `--motion-press`；reduce 下不缩放 |

验证方法见 [`docs/agents/motion-verification.md`](../agents/motion-verification.md)。

---

## 6. 参考

- [ADR-0029：前端去 Emoji 与编辑节奏重构](2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)
- [动效与生动力调研](../research/2026-11-07-motion-vitality-research.md)
- [前端补全与生动力实施计划](../plans/2026-11-07-frontend-completion-and-motion-vitality.md)
- WCAG 2.2 §2.3.3 Animation from Interactions；MDN `prefers-reduced-motion`
