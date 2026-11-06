# 前端「补全 / 生动力」调研：外部实测与可抄模板

> 日期：2026-11-07　|　性质：外部调研 + 模板（不改 `static/`）　|　上游：[外部 UI 设计参考库](2026-11-06-external-ui-design-reference-library.md)、ADR-0029
> 目标：把「不用 emoji 也让界面有生气」的加法那一半，落成可复现的实测值与可直接抄的代码。
> 证据标记：`[A]` 本机实测（computed style / CSSOM / 截图）｜`[B]` 官方文档｜`[C]` 第三方｜`[U]` 未验证

---

## 0. 结论先行

1. **10 个页面实测完成，9 个可用 A 级数据。** Medium 被 Cloudflare 拦（只拿到 33 个元素与加载环），按预案改用 NN/g 文章；Duolingo 首页 8/8 样式表跨域不可读，降为 `[A 受限]`，补测了 `duolingo.com/approach`。
2. **阅读面的动效不是「少」，是「只做一次、只做 opacity / 底色」。** Obsidian Help 126 个元素有 transition，其中 37 个只过渡 `opacity`，正文本身没有位移；NN/g 文章页只有 4 个元素、150ms；Things 3 只有 5 个元素、100–200ms。**阅读界面接近零动效也能成立。**
3. **功能面把 hover 预算花在颜色上，不花在位移上。** GitHub 326 条 hover 规则，抽样 80 条里只有 2 条带 `transform`，73 条只改颜色/阴影/边框；Stripe Docs 22 条 hover 全部不含 `transform`；GitHub 主时长 80ms。
4. **营销面的「生动」= stagger + 长时长。** Raycast 438 个 transition 元素，185 个 400ms、177 个 300ms；扩展卡以 **80ms 递增、单卡 700ms** 入场（第 7 张延迟 580ms）。Linear changelog 234 个 transition 元素、54 个 keyframes。这套节奏不能搬进阅读器。
5. **只有 3 件事值得抄进 DeLector**：hover 只改色/阴影（80–180ms）、选中态 2px 色条 `scaleY`（260ms）、数字首现一次性计数（400–600ms）。其余（700ms stagger、3D 按钮唇边、渐变光晕）列为反例。
6. **22 个 `@keyframes` 里实际有 13 处 `infinite`，不是 4 处。** 其中 `tokenPulse`（0.7s 呼吸）、`pulse-linked`、`pulse-clause` 直接作用在阅读正文上，与 ADR-0029「不做循环动画」冲突最严重；判定见 §8。

---

## 1. 方法与证据

### 1.1 采集方式

- 浏览器：本机 Edge `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，`--headless=new`，CDP 端口 9337。
- 视口：1440×900，`deviceScaleFactor=1`，`mobile=false`。
- 每个页面：`Page.navigate` → 等 3.5s → 滚到 600px 触发视口动画 → 回顶 → 采集 → 截图。
- 复现命令：

```powershell
node C:\Users\Haoyu\AppData\Local\Temp\del_motion\measure.mjs d:\Code\DeLector\_artifacts\2026-11-07-motion-shots

# 只补测某几个页面（结果按 id 合并进 motion.json）
$env:ONLY='linear-changelog,nng-article'
node C:\Users\Haoyu\AppData\Local\Temp\del_motion\measure.mjs d:\Code\DeLector\_artifacts\2026-11-07-motion-shots
```

> 脚本是临时文件，不入库。原始数据与截图在仓库内 `_artifacts/2026-11-07-motion-shots/`（12 张 JPG + `motion.json`，共 13 个文件、1,213,531 字节），属未跟踪证据目录，**不提交 git**。

### 1.2 采集字段

| 字段 | 取法 | 用途 |
|---|---|---|
| `transitionElements` | 遍历 `body *`，`transitionDuration > 0` | 有多少元素参与动效 |
| `durations` / `easings` | `getComputedStyle` 的 transition 值聚合 | 时长档位与曲线分布 |
| `keyframes` | 同源 `document.styleSheets` 里的 `CSSKeyframesRule` | 有哪些动画、帧值 |
| `hoverRules` | 选择器含 `:hover/:focus/:active` 且声明含 transition/transform/opacity | hover 到底改了什么 |
| `delaySamples` | `transition-delay` / `animation-delay` > 0 | 还原 stagger 间隔 |
| `running` | `document.getAnimations()` | 循环动画与首屏动画 |
| `reducedMotion` | `Emulation.setEmulatedMedia` 模拟 `prefers-reduced-motion: reduce` 后复查 | 降级是否存在 |

### 1.3 证据边界

- 跨域样式表无法读取 `cssRules`（Obsidian、NN/g、Duolingo 首页均有），所以「hover 规则数」在这些页面偏低甚至为 0；computed transition 仍然有效。
- **hover 没有被真实触发**：结论来自「CSS 规则 + computed style」，不是鼠标事件后的差值。凡是需要区分「hover 前后」的数值，都标为推断。
- JS 内联动画（Web Animations API）只通过 `getAnimations()` 抓到正在运行的部分，静态写在 JS 里的时长可能漏采。
- Medium 为 `[U]`，其 `medium.jpg` 是 Cloudflare 验证页，不能作为视觉证据。

---

## 2. 实测总表

| 页面 | 类别 | 元素 | 有 transition | 主时长 | 主 easing | keyframes | hover 规则（抽样） | reduce 后仍在动 | 证据 |
|---|---|---:|---:|---|---|---:|---|---:|---|
| Readlang | 阅读 | 412 | 10 | 0.3s ×10 | ease ×9 | 11 | 22（1 带 transform） | 0 | A |
| Obsidian Help | 阅读 | 571 | 126 | 0.14s ×96 / 0.1s ×29 | ease-in-out ×126 | 0 | 0（跨域） | 2（`node-inserted`，0s） | A |
| NN/g 文章 | 阅读（替代 Medium） | 698 | 4 | 0.15s ×4 | ease-out ×4 | 0 | 0（跨域） | 0 | A |
| Things 3 | 阅读基线 | 465 | 5 | 0.1s ×4 / 0.2s ×1 | ease-out ×5 | 0 | 49（4 带 transform） | 0 | A |
| GitHub 仓库 | 功能 | 2824 | 31 | 0.08s ×22 / 0.2s ×5 | `cubic-bezier(.65,0,.35,1)` ×19 | 43 | 326（抽样 80：2 transform） | 0 | A |
| Linear changelog | 功能 | 3351 | 234 | 0.2s ×70 / 0.1s ×53 / 0.25s ×48 | ease ×189 / `cubic-bezier(.25,.46,.45,.94)` ×45 | 54 | 73（16 transform） | 0 | A |
| Stripe Docs | 功能 | 756 | 48 | 0.2s ×15 / 0.3s ×15 / 0.1s ×10 | ease-in-out ×27 / `cubic-bezier(0,0,.4,1)` ×10 | 0 | 22（0 transform） | 0 | A |
| Raycast 首页 | 营销 | 1749 | 438 | 0.4s ×185 / 0.3s ×177 | `cubic-bezier(.23,1,.32,1)` ×185 | 58 | 80（33 transform） | 20 | A |
| Vercel 首页 | 营销 | 1055 | 158 | 0.1s ×79 / 0.15s ×51 | `cubic-bezier(.4,0,.2,1)` ×137 | 73 | 48（1 transform） | 9（`animation-name:none`，误报） | A |
| Duolingo 首页 | 营销 | 598 | 3 | 0.2/0.3/0.5s 各 1 | ease ×2 | 0 | 0（8/8 跨域） | 0 | A 受限 |
| Duolingo Approach | 营销 | 206 | 10 | 0.2s ×10 | ease ×10 | 9 | 5（3 transform） | 0 | A |
| Medium | 阅读 | 33 | 0 | — | — | — | — | 4（`lds-ring`） | U |

---

## 3. 逐类发现

### 3.1 应用内阅读面：动效预算几乎为零，且只碰「外壳」

**Obsidian Help（571 元素 / 126 transition）** `[A]`

- 126 个元素全部 `ease-in-out`；96 个 140ms、29 个 100ms。
- 过渡属性以 `opacity` 为主（37 个采样），`transform` 只有 3 个，`background/box-shadow/border` 各 1。
- **0 个 keyframes**，正文区域没有任何入场动画。
- 页面没有 `prefers-reduced-motion` 查询；模拟 reduce 后仍有 2 个元素挂着 `node-inserted`（但时长为 0s，实际是 Vue 的挂载钩子，不是可见动画）。

> 可抄的点：**把动效限制在侧栏、按钮、行背景；正文不动。** 140ms 是阅读类的高频档。

**Readlang（412 元素 / 10 transition）** `[A]`

- 10 个 transition 全是 0.3s：9 个 `ease`、1 个 `ease-out`。
- 划词/查词的 hover 实现是 **下沿内阴影 + 1px 下边框**，而不是位移：
  - `box-shadow: rgba(67,176,138,.5) 0 -4px 0 inset`
  - `border-bottom: 1px solid rgba(67,176,138,.5)`
  - 已翻译词改为 `background-color: rgba(42,185,123,.3)`
- 11 个 keyframes 主要是营销区的兔子吉祥物（`rabbitExcerpt*`）与一个 `spin`，阅读正文 0 个。

> 可抄的点：**行内元素的「选中」用底色/内阴影，不用 transform。** 这条直接适用于 DeLector 的 `.tok`。

**NN/g 文章（698 元素 / 4 transition）** `[A]`

- 4 个元素、150ms、`ease-out`，0 个 keyframes，0 个 `infinite`。
- 这是本次最接近「学术阅读页」的样本：**动效预算可以是 4 个元素。**

**Things 3（465 元素 / 5 transition）** `[A]`

- 4 个 100ms + 1 个 200ms，全部 `ease-out`，0 个 keyframes。
- 动效全部绑在控件上：checkbox `:active { transform: scale(0.95) }`，输入框 focus 用 2px `box-shadow` 环，按钮 `:active` 只改底色。
- 有 `prefers-reduced-motion` 查询。

> 可抄的点：**按压反馈 100ms、`scale(0.95–0.98)`，只作用在可点控件上。** 阅读类产品里这是「有生气」与「不打扰」的分界。

### 3.2 应用内功能面：hover 花在颜色上，动效花在状态切换上

**GitHub 仓库页（2824 元素 / 31 transition / 43 keyframes）** `[A]`

- 主时长 **80ms ×22**；200ms ×5；400ms ×2（toast / 进度条）。
- 主曲线 `cubic-bezier(0.65, 0, 0.35, 1)`（对称 ease-in-out）×19。
- 326 条 hover 规则；抽样前 80 条中 **73 条只改 `background-color / border-color / color / fill / box-shadow`，只有 2 条带 `transform`**。
- 43 个 keyframes 里能看到 `shimmer`（遮罩位移）与 `skeleton-loading`（骨架块平移）；toast 用 400ms。

> 可抄的点：**80ms + 对称曲线 + 只改颜色**，是密集界面的安全区。骨架屏用「块位移/遮罩」，不是整页 spinner。

**Linear changelog（3351 元素 / 234 transition / 54 keyframes）** `[A]`

- 时长四档：200ms ×70、100ms ×53、250ms ×48、120ms ×39、160ms ×24。
- 曲线：`ease` ×189，`cubic-bezier(0.25,0.46,0.45,0.94)`（easeOutQuad）×45。
- 73 条 hover 规则里 16 条带 `transform`，主要是 `:active { scale(0.98/0.97) }`。
- 入场 keyframes 是 `fadeIn` / `scaleIn`（从 0.98 起，不是 0）。

> 可抄的点：**入场从 0.98 开始，不要从 0.9；位移 4px 级，不要 20px。**

**Stripe Docs（756 元素 / 48 transition / 0 keyframes）** `[A]`

- 时长：200ms ×15、300ms ×15、100ms ×10、150ms ×8。
- 曲线：`ease-in-out` ×27、`cubic-bezier(0,0,0.4,1)`（decelerate）×10。
- 22 条 hover 规则 **0 条 transform**，全部是 `box-shadow / color / background-color`。
- **0 个 keyframes**：文档页完全没有入场动画。

> 可抄的点：**状态用阴影和底色表达，不用位移。** 这是「功能面」最稳的样式。

### 3.3 营销页：stagger 与长时长，正是不能搬进阅读器的部分

**Raycast 首页（1749 元素 / 438 transition / 58 keyframes）** `[A]`

- 185 个 400ms、177 个 300ms；主曲线 `cubic-bezier(0.23, 1, 0.32, 1)`（easeOutQuint）。
- 扩展卡入场：**7 张卡 delay 0.10 / 0.18 / 0.26 / 0.34 / 0.42 / 0.50 / 0.58s，间隔 80ms，单卡 700ms**，曲线 `cubic-bezier(0.215,0.61,0.355,1)`。
- hover：卡片只改 `background + border-color`，箭头 `translate(3px)`，logo `scale(1.05)`，链接 `:active scale(0.98)`。
- 模拟 reduce 后仍有 20 个元素挂着入场动画（`fade-in-up` / `slideIn`），**说明它的降级不完整**。

> 结论：Raycast 的 stagger 是「营销节奏」，不是「阅读节奏」。可抄的是它的 **80ms 间隔上限**与 **hover 只改色**，不是 700ms 时长。

**Vercel 首页（1055 元素 / 158 transition / 73 keyframes）** `[A]`

- 79 个 100ms、51 个 150ms；主曲线 `cubic-bezier(0.4, 0, 0.2, 1)`（Material 标准）。
- keyframes 里有 `fade-slide-in`（-8px）、`flip-front/flip-back`（`rotateY`），以及渐变/光晕类动画。
- 48 条 hover 里只有 1 条 `transform`，44 条只改颜色/阴影。

> 结论：**微交互快（100–150ms）是它对的地方**；渐变光晕与 73 个 keyframes 是反例。

**Duolingo（首页 598 元素 / `[A 受限]`；Approach 206 元素 / `[A]`）**

- 首页 8/8 样式表跨域，只能读到 3 个 transition。能读到的头部是 **0.3s / 0.4s 两档，其中 0.4s 用 `cubic-bezier(0.22, 1, 0.36, 1)`** —— 与 DeLector 的 `--ease-editorial` 完全相同。
- Approach 页按钮是典型的「3D 唇边」：`:active` 时 `translateY(2px)` / `translateY(4px)`，同时把 `::before` 的 `box-shadow` 设为 `none`，制造「按下去」的深度。
- 页面只有 10 个 transition（0.2s ease）与 9 个 keyframes。

> 结论：**曲线可以借，糖果色 + 4px 按压深度不要借。** ADR-0029 的 `cubic-bezier(.22,1,.36,1)` 在外部得到了一次独立验证，但这不代表要复制游戏化。

**Medium** `[U]`

- 33 个元素、`lds-ring` 加载环，是 Cloudflare 验证页；无有效数据。替代样本为 NN/g 文章。

---

## 4. 可落地手法清单

| # | 手法 | 外部证据 | 适用场景 | 实现要点 | 误用后果 |
|---:|---|---|---|---|---|
| 1 | 一次性入场（opacity + 4px） | Linear `fadeIn/scaleIn`；Vercel `fade-slide-in -8px` | 视图切换后的首屏卡片、结果列表 | `animation ... both`，只播一次；位移 ≤4px；180–240ms | 每次重渲染都播 → 界面「抖」；位移 20px → 像营销页 |
| 2 | hover 只改色/阴影 | GitHub 73/80；Stripe 22/22；Vercel 44/48 | 密集列表、导航、表格行 | `background-color / border-color / box-shadow`，80–180ms | 用 `translate` 改布局 → 相邻行位移；触屏无 hover → 功能不可达 |
| 3 | hover 上浮 2px | DeLector `.stat-badge` 已有；Raycast `scale(1.05)` | 单张卡片、模块入口 | `translateY(-2px)` + `--shadow-card`；包在 `@media (hover:hover)` | 列表里逐行上浮 → 视觉噪声；触屏误触 |
| 4 | 选中态左侧色条 | DeLector `style.css:3753` 已有；Raycast 左侧条 | 块级列表项、导航 | `::before` + `scaleY(0→1)`，`transform-origin: top`，260ms | 用在行内元素上（`.tok`）→ 色条没有高度，消失 |
| 5 | 列表 stagger | Raycast 80ms ×7 | 3–6 项的卡片/结果 | 40ms 间隔、最多 6 项、`animation-delay` 用 CSS 变量 | 超过 6 项 → 最后一项等 0.5s；滚动追加 → 反复播 |
| 6 | 静态骨架 + 一次淡出 | GitHub `shimmer` / `skeleton-loading` | 查词、搜索结果、卡片预取（>300ms 空白） | 静态块与最终尺寸一致；内容 `opacity` 180ms 淡入 | 循环 shimmer → 违反「不做循环」；尺寸不一致 → 淡入时跳动 |
| 7 | 数字首现计数 | 无外部样本（本次 10 页均未采到） | 统计页首次进入 | rAF + easeOutCubic，400–600ms，`tabular-nums` | 每次进页面都滚 → 烦；无等宽 → 宽度抖；`aria-live` → 每帧朗读 |
| 8 | 焦点调暗 | DeLector `body.focus-mode .tok` 已有 | 精读、专注模式 | `opacity: .28`，220ms，只调非焦点项 | 调暗后对比度不足；同时加位移 → 阅读节奏被打断 |
| 9 | 按压 `scale(0.95–0.98)` | Things 3 `scale(.95)`；Raycast `scale(.98)` | 按钮、checkbox、卡片 | 100–150ms，只在 `:active`；不改变布局盒 | 用在正文链接上 → 文字缩放发虚 |

---

## 5. 代码模板

完整文件：

- [motion-templates.css](file:///d:/Code/DeLector/docs/reviews/2026-11-07-motion-templates.css)
- [motion-templates.js](file:///d:/Code/DeLector/docs/reviews/2026-11-07-motion-templates.js)

只挂现有 token（`--accent` / `--moss` / `--pencil` / `--paper-*` / `--shadow-*` / `--dur-fast` / `--dur-mid` / `--ease-editorial`）。唯一字面量是 `260ms`（ADR-0029 选中色条，与 `style.css:3763` 一致）。

### 5.1 hover 上浮

```css
.dl-lift {
  transition:
    transform var(--dur-fast) var(--ease-editorial),
    box-shadow var(--dur-fast) var(--ease-editorial),
    border-color var(--dur-fast) var(--ease-editorial);
}
@media (hover: hover) and (pointer: fine) {
  .dl-lift:hover { transform: translateY(-2px); box-shadow: var(--shadow-card); }
}
.dl-lift:active { transform: translateY(0); box-shadow: var(--shadow-sm); }
```

- **什么时候用**：单张卡片、统计徽章、模块入口。
- **什么时候别用**：正文词元、表格行、移动端长列表；触屏没有 hover。

### 5.2 选中态色条

```css
.dl-selectable { position: relative; }
.dl-selectable::before {
  content: ""; position: absolute; left: -1rem; top: 0; bottom: 0;
  width: 2px; background: var(--accent);
  transform: scaleY(0); transform-origin: top;
  transition: transform 260ms var(--ease-editorial);
}
.dl-selectable.is-selected::before { transform: scaleY(1); }
```

- **什么时候用**：`exam-module-card`、导航项、任何有高度的块级列表项。
- **什么时候别用**：行内元素（`.tok`、`<a>`、`<span>`）；行内盒没有可用高度，色条不可见。

### 5.3 卡片翻面

```css
.dl-flip { perspective: 1000px; }
.dl-flip-inner {
  position: relative; transform-style: preserve-3d;
  transition: transform var(--dur-mid) var(--ease-editorial);
}
.dl-flip.is-flipped .dl-flip-inner { transform: rotateY(180deg); }
.dl-flip-face { backface-visibility: hidden; }
.dl-flip-back { position: absolute; inset: 0; transform: rotateY(180deg); overflow: auto; }
```

- **什么时候用**：闪卡、正反面术语、答案揭示。
- **什么时候别用**：正文、设置页、长文本；90° 处文字会发虚。系统开启「减少动态」时降级为两面淡入淡出。

### 5.4 列表逐项 stagger

```css
.dl-stagger > * {
  animation: dl-rise var(--dur-fast) var(--ease-editorial) both;
  animation-delay: calc(var(--stagger-index, 0) * var(--stagger-step, 40ms));
}
@keyframes dl-rise {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.dl-stagger > :nth-child(1) { --stagger-index: 0; }
/* … 2–6；n+7 全部按第 6 档 */
```

- **什么时候用**：一次渲染 3–6 张卡片/结果。
- **什么时候别用**：滚动中追加、分页加载、超过 6 项、正文列表。

### 5.5 骨架屏 → 内容淡入

```css
.dl-skeleton { background: var(--paper-tint); border-radius: 2px; }
.dl-skeleton.is-loaded { opacity: 0; transition: opacity var(--dur-fast) var(--ease-editorial); }
.dl-content-enter { animation: dl-fade var(--dur-fast) var(--ease-editorial) both; }
```

- **什么时候用**：已知会有 >300ms 空白的区域（查词、搜索结果、卡片预取）。
- **什么时候别用**：<150ms 的本地请求（会闪）、正文首屏；骨架尺寸必须与最终内容一致。

### 5.6 数字计数

```js
export function countUp(el, to, { duration = 520, format } = {}) {
  const fmt = format || ((n) => String(Math.round(n)));
  if (prefersReducedMotion()) { el.textContent = fmt(to); return () => {}; }
  // rAF + easeOutCubic（1 - (1-p)^3），不回落、不回弹
}
```

- **什么时候用**：统计页首次进入、结果总数首次出现。
- **什么时候别用**：实时数字、金额、表格单元格；不要加 `aria-live`。

---

## 6. 对照 DeLector 现状的映射

### 6.1 适合直接套的

| 视图 | 目标元素 | 模板 | 现状 | 建议 |
|---|---|---|---|---|
| 考试 | `.exam-module-card` | 选中色条 | 已实现 `scaleY` 260ms（[style.css:3753-3768](file:///d:/Code/DeLector/static/style.css#L3753-L3768)） | **保持**，作为全站样板；hover 从 `translateX(2px)` 统一为 `translateY(-2px)` 或保持不位移 |
| 统计 | `.stat-badge`、`#stat-streak`、`#stat-mastered-vocab` 等 | hover 上浮 + 数字计数 | hover 已有 150ms 上浮（[style.css:4848-4857](file:///d:/Code/DeLector/static/style.css#L4848-L4857)）；数字无动画 | hover 对齐 `--dur-fast`；数字首次进入用 `countUp(…, 520)`，`tabular-nums` |
| 搜索 | `#search-group-vocab` 等 `.search-group-body` | stagger + 骨架 | 结果直接插入，无过渡 | 每组 ≤6 项用 stagger 40ms；请求 >300ms 时先出静态骨架 |
| 卡片 | `.flip-inner`（workbench） | 卡片翻面 | 已有 500ms 3D 翻转 | 保持；确保 `prefers-reduced-motion` 下降级为淡入 |
| 导航 | 桌面/移动 tab | 选中色条 | 已有 active 样式，无过渡 | 只加 260ms 色条；**不要**给整个视图切换加入场 |

### 6.2 现在硬切换、值得加过渡的

| 位置 | 现状 | 建议 |
|---|---|---|
| 查词浮层 `.enc-pop` | 直接插入/移除 | 180ms `opacity + translateY(4px)`，关闭 120ms |
| 悬停释义/搭配面板 | `display` 切换 | 先改成 `visibility + opacity`，避免 `display` 无法过渡 |
| 搜索结果出现 | 一次性 `innerHTML` | 只对组容器做一次 180ms 淡入；不要逐条 700ms |
| 卡片状态徽章 | 颜色硬切 | 颜色 120ms 过渡 + 文字不变（状态不能只靠颜色） |

### 6.3 一动就会破坏编辑节奏的

| 位置 | 原因 |
|---|---|
| `writer` 正文与编辑器 | 任何入场/位移都会打断输入；只保留保存状态的色点 |
| `reader` 正文词元 | 正处在精读节奏里；只允许底色/内阴影 120ms，不允许位移、缩放、循环呼吸 |
| 考试题干与选项文本 | 文本移动会让眼睛重新定位；只允许选项容器 hover 改色 |
| 视图整体切换 | `main.js:213` 的 `display` 硬切是对的；整页淡入会拖慢每次导航 |

---

## 7. 不做什么

| 做法 | 为什么不做 | 外部反例 |
|---|---|---|
| 大面积渐变 / 光晕 | 与纸张+墨线的编辑气质冲突；低对比文本上会降低可读性 | Vercel 首页（73 个 keyframes、渐变层） |
| 弹跳 / 回弹 easing（overshoot） | 会让「克制」变成「活泼」；文本场景显得不稳 | Duolingo 糖果按钮 |
| 循环动画 | 阅读时持续抢占注意力；ADR-0029 已明确不做 | Raycast 入场循环、DeLector 现有 13 处 `infinite` |
| 视差滚动 | 滚动与阅读进度耦合，晕动风险高；移动端性能差 | 营销页常见，本次样本中 Linear/Raycast 均有滚动触发 |
| 滚动劫持（scroll-jacking） | 破坏浏览器原生滚动与键盘导航 | 无 |
| 正文 3D 翻转 | 90° 处文字发虚，长文本不可读 | Vercel 的 `flip-front/back` 只用于卡片，不用于正文 |
| 整页视图过渡 | 每次导航多等 200–400ms，阅读产品的高频切换会被拖慢 | GitHub / Stripe 都不做整页过渡 |
| 每位数都滚的实时计数器 | 数字一直动，无法扫读；`aria-live` 会刷屏 | 无 |
| 骨架 shimmer 循环 | 与「不做循环」冲突；静态块已足够 | GitHub 的 shimmer 只用于短时加载 |

---

## 8. 22 个 `@keyframes` 的循环动画判定

`static/style.css` 19 个 + `static/css/workbench.css` 3 个 = **22 个**。其中 **13 处**声明了 `infinite`（style.css 12 处 + workbench 1 处），不是先前估计的 4 处。

| 动画 | 位置 | 用途 | 判定 |
|---|---|---|---|
| `pulse` 2.4s | [style.css:231](file:///d:/Code/DeLector/static/style.css#L231) | 顶栏 6px 圆点 | **降级**：只有编码「在线/实时」时才保留；否则改静态 |
| `tokenPulse` 0.7s alternate | [style.css:1412](file:///d:/Code/DeLector/static/style.css#L1412) | 聚焦词元呼吸 | **删除**：直接作用在正文，0.7s 太快，最伤阅读 |
| `pulseDot` 2.2s | [style.css:4630](file:///d:/Code/DeLector/static/style.css#L4630) | 状态圆点 | **合并**：与 `pulse` 保留一处即可 |
| `marqueeLeft/Right` 42/48s | [style.css:4973-4977](file:///d:/Code/DeLector/static/style.css#L4973-L4977) | 空态滚动 | **保留**：已有 `prefers-reduced-motion` 降级，且只在空态 |
| `pulse-linked` 1.8s | [style.css:6937](file:///d:/Code/DeLector/static/style.css#L6937) | 可分动词关联高亮 | **降级**：改静态 2px 边框 + 一次性 260ms 高亮 |
| `pulse-clause` 1.6s | [style.css:7305](file:///d:/Code/DeLector/static/style.css#L7305) | 从句高亮 | **降级**：同上 |
| `charBlink` 4.2s | [style.css:7908](file:///d:/Code/DeLector/static/style.css#L7908) | 角色眨眼 | **保留**：角色身份，低频（4.2s） |
| `companionIdle` 4s | [style.css:7415](file:///d:/Code/DeLector/static/style.css#L7415) | 伴读待机 | **保留**：唯一允许常驻的角色动效；需尊重 reduce |
| `thoughtInkPulse` 1.2s | [style.css:11651](file:///d:/Code/DeLector/static/style.css#L11651) | 思考中指示 | **保留**：加载语义；但可改为静态三点 |
| `typingCursorBlink` 0.8s | [style.css:11754](file:///d:/Code/DeLector/static/style.css#L11754) | 打字光标 | **保留**：光标闪烁是语义，不是装饰 |
| `pulse` 1s（workbench） | workbench.css:324 | 音频忙碌 | **保留**：加载态；或改静态 |

> 总原则：**循环动画只允许两种身份——「正在发生的事」（加载/光标/在线）与「角色身份」（眨眼/待机）。** 其余全部改为一次性或静态。

---

## 9. 没法验证的结论

1. **Medium** 被 Cloudflare 拦，无法测量；NN/g 是替代样本，不是 Medium 本身。`[U]`
2. **Duolingo 应用内界面**（登录后的 XP、连胜、关卡）不可访问；只能测营销页。`[U]`
3. **hover 前后差值**未真实触发，所有 hover 结论来自 CSS 规则 + computed style。`[A，推断]`
4. **JS 内联动画**只抓到运行中的部分，未做运行时代码注入，可能漏采。`[U]`
5. **跨域样式表**（Obsidian、NN/g、Duolingo 首页）的 hover 规则读不到，规则数为 0 不代表没有。`[A，受限]`
6. **Vercel 的 reduce 后 9 个元素**是探针误报（`animation-name: none`），没有据此下结论。`[A，已排除]`
7. **Raycast 的 reduce 降级不完整**（20 个元素仍挂入场动画）是基于 `getAnimations()` 的一次采样，未做完整交互路径验证。`[A，单次]`
8. **计数动画**在 10 个样本里都没有采到；模板的 400–600ms 来自阅读类动效档位与工程经验，不是实测值。`[U]`
9. **触屏行为**未测：所有页面都在桌面视口渲染，没有验证 `pointer: coarse`。`[U]`
10. **性能**未测：没有做 Performance trace，无法给出「掉帧/重绘」结论。`[U]`

---

## 10. 证据索引

- 原始数据：`_artifacts/2026-11-07-motion-shots/motion.json`
- 截图：`_artifacts/2026-11-07-motion-shots/*.jpg`（12 张；`medium.jpg` 为 Cloudflare 验证页，仅作失败证据）
- 采集脚本：`C:\Users\Haoyu\AppData\Local\Temp\del_motion\measure.mjs`（临时，不入库）
- 主要页面：
  - https://readlang.com/
  - https://help.obsidian.md/
  - https://www.nngroup.com/articles/animation-usability/
  - https://culturedcode.com/things/
  - https://github.com/ROM4n2/DeLector
  - https://linear.app/changelog
  - https://docs.stripe.com/payments
  - https://www.raycast.com/
  - https://vercel.com/
  - https://www.duolingo.com/approach
