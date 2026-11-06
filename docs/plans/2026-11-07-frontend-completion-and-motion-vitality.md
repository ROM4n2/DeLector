# 前端「补全 / 生动力」实施计划（加法批次）

- **状态**：In Progress —— 四项决策已拍板；M1 已实施并开 PR，T2–T8 逐项推进；T9 拆下一批
- **日期**：2026-11-07
- **上游**：[ADR-0029](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)、[动效调研与模板](../reviews/2026-11-07-motion-vitality-research.md)、`../reviews/2026-11-07-motion-templates.css`、`../reviews/2026-11-07-motion-templates.js`
- **前置批次**：第四批 B 类 390 处装饰字形清零（PR #255，扫描 0 残留）
- **性质**：加法（补全 + 生动力），但**先做一步减法**（循环动画收口，见 §1 D1）

---

## Goal

在已完成「字形清零」的界面上，用**排版层级**和**一次性动效**补回原本由字形承担的注意力锚点，让界面「不空、不死」，同时不打断精读与写作的编辑节奏。

一句话判据：**删掉字形后，界面靠层级、状态冗余和一次性的反馈仍然能「说话」；任何持续抢占注意力的动画都算失败。**

## Tech Stack

- 原生 CSS（`static/style.css`、`static/css/workbench.css`、`static/css/tokens.css`）
- 原生 ES Module（`static/js/*.js`），无第三方运行时依赖
- 既有构建：`tools/build_index_html.py`、`tools/check_index_html_sync.py`
- 测试：pytest 静态源码探针 + Node 探针 + 现有前端守卫

## Spec Reference

| 文档 | 用途 |
| --- | --- |
| `docs/adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md` | 不变量 I1、动效边界、失败信号 §6 |
| `docs/reviews/2026-11-07-motion-vitality-research.md` | 外部实测值、可抄手法 §4、循环判定 §8、反例 §7 |
| `docs/reviews/2026-11-07-motion-templates.css` / `.js` | 可直接落地的模板（stagger / countUp / fade） |
| `docs/design-system.md` + `static/css/tokens.css` | 现有 token 与视觉语言 |
| `docs/reviews/2026-11-06-external-ui-design-reference-library.md` | 更早一版外部参考 |

## Global Constraints（全批次硬约束）

1. **I1**：任何字形都不得是意义的唯一载体；本批不新增任何 emoji/符号字形，也不允许用动画让某个字形变成唯一状态提示。
2. **动效预算**：只允许 `opacity`、颜色、`box-shadow`、`border-color`、`transform: translateY(≤4px)`、`scale(0.95–1.0)`。禁止 `width/height/top/left/margin` 动画（会触发布局）。
3. **时长**：一次性动效 ≤260ms；数字计数 520ms 是唯一例外；按压 100–150ms；hover 80–180ms。
4. **循环白名单**：只允许「正在发生的事」（光标、加载、在线）与「角色身份」（眨眼、待机）两类；其余循环一律删除或改一次性（见 §1 D1）。
5. **reduce 守卫**：每个新增/保留的动画与过渡都必须有 `prefers-reduced-motion: reduce` 降级；reduce 下直接落到终态。
6. **阅读面零位移**：`writer` 编辑器正文、`reader` 正文词元、考试题干/选项文本不得有入场、位移、缩放、呼吸。
7. **不引入依赖、不扩 sprite**：图标集维持 16 个；若任务需要第 17 个图标，进停止门。
8. **可回滚**：每个任务一个独立 commit；不得删除或放宽现有测试断言来换取绿灯。
9. **同一文件单归属**：`static/style.css`、`static/index.html`、`tokens.css` 只归主代理；子代理按文件分片。

---

## 1. 先回答冲突点（本计划的关键决策）

### D1：13 处 `infinite` 怎么处置？放本批还是单独一批？

**结论：单独一个前置小批 M1（减法），先于加法合并。** 理由：

1. 减法与加法混在同一 PR，无法单独回滚：若入场动效造成打扰，回滚会把「停止呼吸」的修复一起带走。
2. `tokenPulse` 直接作用在正文词元上，是本批所有新动效的前提预算——它不先停，任何入场/高亮都会叠加成「页面一直在动」。
3. M1 可以独立验收（grep + reduce 模拟），成本低、风险低，适合作为加法批次的前置门。

13 处逐条判定（位置以当前 `static/style.css` / `static/css/workbench.css` 为准）：

| # | 动画 | 位置 | 用途 | 处置 | 批次 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `tokenPulse` 0.7s | `style.css:1412`，`.tok.focus-active` | 聚焦词元呼吸 | **删除动画**；保留 `scale(1.06)` + 2px ink ring 静态标记 | M1 |
| 2 | `pulse-linked` 1.8s | `style.css:6937`，`.tok.linked-separable` | 可分动词关联 | **降级**：静态 2px 蓝边 + 一次性 260ms 高亮 | M1 |
| 3 | `pulse-clause` 1.6s | `style.css:7305`，`.tok.clause-highlight` | 从句高亮 | **降级**：同上，静态 2px 橙边 | M1 |
| 4 | `pulse` 2.4s | `style.css:231`，`.topbar-inner .pulse` | 顶栏状态点 | **合并**到统一 `.status-dot`：仅「在线/实时」时循环，其余静态 | M1 |
| 5 | `pulseDot` 2.2s | `style.css:4630`，`.folio-pulse` | 状态圆点 | 与 #4 合并，保留一处定义 | M1 |
| 6 | `thoughtInkPulse` 1.2s | `style.css:11651` | 思考中指示 | **改静态三点**；加载语义由文案承担 | M1 |
| 7 | `typingCursorBlink` 0.8s | `style.css:11754` | 打字光标 | **保留**（语义），补 reduce | M1 |
| 8 | `charBlink` 4.2s | `style.css:7908` | 角色眨眼 | **保留**（角色身份），补 reduce | M1 |
| 9-10 | `companionIdle` 4s ×2 | `style.css:7415`、`style.css:7673` | 伴读待机 | **保留**（唯一常驻角色动效），补 reduce | M1 |
| 11-12 | `marqueeLeft/Right` 42/48s | `style.css:4973/4977` | 空态滚动 | **保留**（已有 reduce，且只在空态） | — |
| 13 | `pulse` 1s | `workbench.css:324`，`.audio-btn.busy` | 音频忙碌 | **保留**（加载语义），补 reduce | M1 |

M1 结束后：`tokenPulse` / `pulse-linked` / `pulse-clause` / `thoughtInkPulse` / `pulseDot` 五个 keyframes 名消失；`infinite` 从 13 处降到 **7 处**，且 7 处全部在白名单内。

### D2：`tokenPulse` 与阅读节奏

删除动画，保留**静态**可辨识标记：`.tok.focus-active` 继续用 `scale(1.06)` + 2px `--ink` 外环 + 加粗；`body.focus-mode .tok` 的 0.22s opacity/transform 过渡保留（这是切换，不是循环）。

验收：`grep -n "tokenPulse" static/` 无结果；`.tok` 相关规则中无 `animation:`；reduce 下聚焦仍有静态环。

### D3：「补全」用图形还是排版？

**用排版与状态冗余，不加图标。** 字形清零后若某处「看起来缺东西」，优先用：左竖线 + mono eyebrow + serif 标题 + 状态文字 + 颜色冗余。sprite 维持 16 个；需要新图形即进停止门。

---

## 2. 任务切分与顺序

| 任务 | 阶段 | 依赖 | 改动面 | 为什么这个顺序 |
| --- | --- | --- | --- | --- |
| **M1 / T1** | 减法前置 | 无 | `style.css`、`workbench.css` | 先腾出动效预算，后续加法才有上限 |
| **T2** | 基建 | T1 | `tokens.css`、`style.css`、`static/js/motion.js` | 统一时长/位移/降级，避免每个任务各写一套 |
| **T3** | 功能面 | T2 | `style.css` 的 hover 规则 | 低风险、高频、可立即验收 |
| **T4** | 功能面 | T2 | `style.css`、`layout/nav_desktop.html`、`layout/nav_mobile.html` | 复用考试模块已验证的 `scaleY` 色条 |
| **T5** | 内容面 | T2 | `static/js/search.js`、`static/js/cards.js`、`style.css` | 一次性入场，限定 3–6 项；最后接内容面 |
| **T6** | 数据面 | T2 | `static/views/progress.html`、`static/js/main.js` 或 progress 模块 | 数字计数最容易过度，放在入场之后单独验收 |
| **T7** | 浮层 | T2 | `style.css` `.enc-popover` | 只统一 token，不引入关闭定时器 |
| **T8** | 控件 | T2 | `style.css` 按钮/复选框 | 按压反馈，范围最小 |
| **T9** | 静态补全 | T3–T8 | `style.css`、`views/cards.html`、nav/cards/reader 三面 | 排印与状态冗余是最大视觉面，放最后单独拍板 |

顺序原则：**先减法 → 再基建 → 先功能面后内容面 → 最大视觉面最后。** 任一任务未过验收，不进入下一个。

---

## 3. 逐项改动面与验收判据

> 每条验收后面标注它对应 I1 / ADR-0029 的哪一条，便于逐条核对。

### T1（M1）循环动画收口

**改动面**
- `static/style.css`：`:224-232`（`.topbar-inner .pulse`）、`:1403-1424`（`.tok.focus-active` / `tokenPulse`）、`:4624-4642`（`.folio-pulse` / `pulseDot`）、`:6928-6955`（`.linked-separable` / `pulse-linked`）、`:7296-7324`（`.clause-highlight` / `pulse-clause`）、`:7411-7418` 与 `:7673`（`companionIdle`）、`:7896-7910`（`charBlink`）、`:11645-11660`（`thoughtInkPulse`）、`:11748-11760`（`typingCursorBlink`）
- `static/css/workbench.css`：`:324`（`.audio-btn.busy`）
- 不改 JS 里添加 class 的逻辑（`linked-separable` / `clause-highlight` 仍然切换，只是外观变静态）

**验收**
- [ ] `grep -rn "tokenPulse\|pulse-linked\|pulse-clause\|thoughtInkPulse\|pulseDot" static/` 为 0。
- [ ] `grep -rn "infinite" static/` 只剩 7 处，且逐条落在白名单（光标 / 眨眼 / 待机 ×2 / marquee ×2 / 音频忙碌）。（ADR §8）
- [ ] `.tok`、`.tok.focus-active` 无 `animation`；聚焦仍有 `scale(1.06)` + 2px 环。（约束 6）
- [ ] `prefers-reduced-motion: reduce` 覆盖全部 7 处白名单动画。（约束 5）
- [ ] 手动：打开阅读页聚焦词元 10s，画面无持续缩放/发光；打开可分动词高亮，无呼吸。
- [ ] `python -m pytest tests/test_frontend_guards.py tests/test_grammatik_radar.py -q` 全绿。

### T2 动效基建（token + 工具函数 + 全局降级）

**改动面**
- `static/css/tokens.css` 新增（不迁移旧值）：
  - `--motion-enter: 180ms`
  - `--motion-enter-shift: 4px`
  - `--motion-press: 100ms`
  - `--motion-count: 520ms`
  - `--motion-stagger-step: 40ms`
- `static/style.css` 新增通用类与 keyframes：
  - `@keyframes dl-fade-up { from { opacity:0; transform:translateY(var(--motion-enter-shift)); } }`
  - `.dl-enter { animation: dl-fade-up var(--motion-enter) var(--ease-editorial) both; }`
  - `.dl-stagger > * { animation-delay: calc(var(--stagger-index, 0) * var(--motion-stagger-step)); }`
  - `.dl-count { font-variant-numeric: tabular-nums; }`
  - 全局 reduce 块：`animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important;`
- 新增 `static/js/motion.js`：只导出 `prefersReducedMotion()`、`stagger(root, {step=40, cap=6})`、`countUp(el, to, {duration=520, format})`。**不移植 `revealOnce`**（首屏内容不需要滚动触发，YAGNI）。

**验收**
- [ ] 新 token 只在 `tokens.css` 定义，其他文件引用变量，不出现裸 `180ms/40ms/520ms`（M1 白名单动画除外）。
- [ ] reduce 块生效：模拟 reduce 后，`getAnimations()` 中不存在 `dl-fade-up` 的运行实例。
- [ ] `motion.js` 无第三方 import；`node --check` 通过；被引用一次以上才允许保留（未使用即删）。
- [ ] `python -m pytest tests/test_frontend_module_graph.py tests/test_frontend_guards.py -q` 全绿。

### T3 hover 收敛（只改色/阴影）

**改动面**
- `static/style.css`：
  - `.exam-module-card:hover`：去掉 `transform: translateX(2px)`，改为 `border-color` / `box-shadow` / `background`。
  - `.stat-badge`（`:4840-4857`）：保留 `translateY(-2px)`（ADR 允许的单卡上浮），时长对齐 `--dur-fast`，并包进 `@media (hover: hover)`。
  - 搜索分组、卡片列表行：只加 `background-color` / `border-color` 过渡。
- 不改 `.exam-module-card::before` 的选中色条（T4 复用）。

**验收**
- [ ] `grep -n ":hover" static/style.css` 的规则块中，带 `transform` 的只剩 `.stat-badge` 与已记录的例外（每条例外写注释）。
- [ ] 所有 hover 过渡落在 80–180ms，无 `translate` 造成相邻行位移。（研究 §4 手法 2）
- [ ] 触屏模拟（`pointer: coarse`）下无依赖 hover 才能看见的信息。（I1：hover 不得是唯一载体）

### T4 选中态左侧色条

**改动面**
- `static/style.css`：为 `.nav-tab.active`、`.mobile-nav-item.active` 增加 `::before` 色条，复制 `.exam-module-card::before`（`:3753-3768`）的 `scaleY(0→1)`、`transform-origin: top`、`transition: transform 260ms var(--ease-editorial)`。
- `static/layout/nav_desktop.html` / `nav_mobile.html`：仅在现有 `active` 类不变的前提下补 `aria-current="page"`（若已有则跳过）。

**验收**
- [ ] active 同时有：2px 色条 + 字重/颜色变化 + `aria-current`，三者冗余，不是只靠颜色。（I1）
- [ ] 色条用 `transform`，不改变布局盒；切换 tab 不产生 1px 抖动。
- [ ] reduce 下色条直接出现/消失，无过渡。
- [ ] `python -m pytest tests/test_index_dom_probe.py tests/test_frontend_guards.py -q` 全绿。

### T5 一次性入场 + 列表 stagger

**改动面**
- `static/style.css`：`.dl-enter` / `.dl-stagger` 通用类（T2 已建）。
- `static/js/search.js`：每组结果首次渲染后对容器加 `.dl-enter`，对 ≤6 个子项设 `--stagger-index`；**重渲染不重播**。
- `static/js/cards.js`：卡片网格首次进入加 stagger；追加/翻页不加。
- 考试模块网格 `#exam-module-grid`（`views/exam.html` 容器）：首次渲染 7 项，按 6 项封顶（第 7 项与第 6 项同延迟）。

**验收**
- [ ] 单次入场 ≤6 项、间隔 40ms、单卡 180ms；第 7 项不再累加延迟。（研究 §4 手法 5）
- [ ] 只在首次渲染触发；滚动追加、搜索 re-render、翻页均不重播。
- [ ] 正文、表格行、搜索结果文本本身不做逐条入场。
- [ ] reduce 下无动画、直接显示终态。
- [ ] 手动：搜索结果从输入到出现无「最后一项等半秒」的迟滞。

### T6 数字首现计数

**改动面**
- `static/views/progress.html` 的 6 个 `.stat-ring`：`#stat-streak`、`#stat-mastered-vocab`、`#stat-mastered-grammar`、`#stat-articles`、`#stat-accuracy`（带 `%`）、`#stat-minutes`。
- 调用 `countUp()` 时同时设 `aria-label` 为最终值；**不加 `aria-live`**。
- 计数只在统计页首次进入时播放；切换 tab 回来不重播。

**验收**
- [ ] 每项 520ms、easeOutCubic、无回弹；`#stat-accuracy` 保留 `%` 与整数格式。
- [ ] 元素带 `.dl-count`（`tabular-nums`），起止宽度不抖。
- [ ] `aria-label` 为最终值，屏幕阅读器不会逐帧朗读。（I1 + 研究 §5 注意）
- [ ] reduce 下直接显示最终值。
- [ ] 手动：连续切两次统计页，第二次无计数动画。

### T7 浮层过渡统一

**改动面**
- `static/style.css`：`.enc-popover`（`:11180-11198`）已有 180ms 入场，改为引用 `--motion-enter` / `--ease-editorial`；reduce 已覆盖。
- **不新增关闭动画**：`.enc-popover.open { display:block }` 保持即时关闭，避免引入 `setTimeout` / `animationend` 的竞态。

**验收**
- [ ] 入场时长来自 token，不新增第二套 keyframes。
- [ ] 关闭仍即时；无 JS 定时器。
- [ ] reduce 下 `animation: none`，浮层直接出现。
- [ ] `python -m pytest tests/test_encounter_ui_probes.py -q` 全绿。

### T8 按压反馈

**改动面**
- `static/style.css`：`.btn:active`、`.icon-btn:active`、`.deck-card:active`（若存在）加 `transform: scale(0.98)`、`transition: transform var(--motion-press) ease`；包在 `@media (hover: hover)` 或仅 `:active`。
- 正文链接、`.tok`、考试选项文字**不加**。

**验收**
- [ ] 按压只作用在可点控件，`scale` 0.95–0.98，100–150ms。
- [ ] 不改变布局盒（`display:inline-block` 已有则不动）。
- [ ] reduce 下无缩放。
- [ ] 手动：按钮长按不出现「陷下去不复位」。

### T9 静态补全（排版与状态冗余）

> 这是最大视觉面，**独立验收、独立拍板**；未点头不得开工。

**改动面**
- 卡片三态状态芯片（`static/js/cards.js` 渲染 + `static/style.css`）：文字 + 颜色 + 3px 左竖线；不改现有中文标题。（ADR §13.1 的 Deferred Gap）
- focus 可见性：只对 T3–T8 触及的控件补 `:focus-visible` 2px `--ink` 环 + 2px offset；不做全站清理。
- 排印节奏：只改 nav / cards / reader 三个面（ADR §3.5），使用现有 token；section 间距 40–64px、正文 1.6、长读 1.9、行宽 45–90 字符。
- 不改 `static/views/` 之外的布局，不做全站 token 迁移。

**验收**
- [ ] 卡片三态在灰阶/色盲模拟下仍可区分（文字 + 线 + 颜色三通道）。（I1）
- [ ] 三个面之外的文件 0 改动；截图对比未被要求修改的页面差异 ≤5%。（ADR §6.2）
- [ ] 无新增 `px` 硬编码间距；新值全部来自 `tokens.css`。
- [ ] `python -m pytest tests/test_frontend_guards.py tests/test_german_workbench.py tests/test_cards_state_split.py -q` 全绿。

---

## 4. 停止门（出现任一，停下来问，不自行判断）

1. **需要第 17 个图标**，或需要改 `static/icons/*` 才能完成某个任务。
2. **需要给正文（reader `.tok`、writer 编辑器、考试题干/选项）加任何动画或位移**——即使只有 4px。
3. **需要新的 `infinite`**，或白名单外动画无法降级为一次性。
4. **reduce 降级无法在不改 JS 结构的前提下实现**（例如需要重构渲染时序）。
5. **某任务需要修改 3 个以上视图的布局**，或视觉差异预计 >5%。
6. **需要放宽/删除现有测试断言**，或需要 `skip` 才能绿灯。
7. **调研数值与当前代码漂移 >20%**（例如 `infinite` 数量、`@keyframes` 数量、行号对不上且无法按选择器定位）。
8. **某页面的同时运行动画 >6 个**，或出现掉帧/布局抖动的主观反馈。
9. **实现需要引入第三方库/字体/图片资源**，或新增网络请求。
10. **T9 的任何一条需要动 `static/style.css` 之外的全局 token 迁移**。

---

## 5. 明确不做什么（反例清单）

| 不做 | 原因 |
| --- | --- |
| 大面积渐变 / 光晕 / 渐变文字 | 与纸张 + 墨线气质冲突，降低低对比文本可读性 |
| 弹跳 / 回弹 / overshoot easing | 文本场景显得不稳，与「克制」冲突 |
| 视差滚动、滚动劫持 | 晕动风险，破坏原生滚动与键盘导航 |
| 任何循环装饰动画 | 阅读时持续抢占注意力；ADR-0029 已明确 |
| 整页/视图入场过渡 | 高频导航每次多等 200–400ms；`main.js` 的 `display` 硬切是对的 |
| 正文 3D 翻转 | 90° 处文字发虚，长文本不可读 |
| 骨架 shimmer 循环 | 与「不做循环」冲突；静态块足够 |
| 每位数都滚的实时计数器 | 无法扫读，`aria-live` 会刷屏 |
| 给搜索结果逐条 700ms 入场 | 营销节奏，不是阅读节奏；上限 6 项 × 40ms |
| 全站 token 迁移 / 全站 focus 环清理 | 无视觉回归测试，回归风险高于收益 |
| 关闭动画 + JS 定时器 | 竞态与额外状态，收益低 |

---

## 6. 验收执行方式（全批统一）

1. **静态闸门**
   - `python tools/build_index_html.py`，再 `python tools/check_index_html_sync.py`。
   - `grep -rn "infinite" static/` 对照白名单（M1 后应为 7 处）。
   - `grep -rn "@keyframes" static/` 计数，新增 keyframes 必须在本计划的清单内。
2. **测试闸门**
   - 每个任务：受影响 pytest + Node 探针全绿。
   - 全批收尾：受影响测试全量跑一遍，记录 passed / skipped；新增守卫只增不减。
3. **reduce 闸门**
   - 浏览器模拟 `prefers-reduced-motion: reduce`，逐任务检查：动画实例为 0 或时长 `.01ms`；所有终态可见。
4. **人工闸门（5 个场景）**
   - 阅读页聚焦词元 10s：无循环、无位移。
   - 搜索一次：结果出现 ≤180ms，无逐条迟到。
   - 统计页首次进入：6 个数字 520ms 内到位，第二次进入不动。
   - 写作页输入 30s：正文与光标外无其它动画。
   - 考试切模块：色条 260ms，题干文字不移动。
5. **回滚点**：M1、T2、T3–T4、T5–T6、T7–T8、T9 各自独立 commit；任一验收失败只回滚该 commit。

---

## 7. 偏差表（执行期填写，不静默改写）

| # | 计划 | 实际 | 理由 |
| --- | --- | --- | --- |
| 1 | M1 `pulse-linked` / `pulse-clause` 降级为「静态 2px 边 + 一次性 260ms 高亮」 | 只保留静态 2px 边，不做一次性高亮 | 停止门 #2：不给正文 `.tok` 新增任何动画；静态环 + 背景/字重已足以区分 |
| 2 | M1 `thoughtInkPulse` 改「静态三点」 | 保留原单个静态 `.thought-pulse-dot` | DOM 里本就只有一个点；加载语义由「Eule 正在推演句子结构...」文案承担，不新增节点 |

---

## 8. 需要用户先拍板的事项

| # | 事项 | 选项 | 建议 |
| --- | --- | --- | --- |
| 1 | M1（13 处循环收口）是否接受作为**独立前置 PR** | A. 独立 PR 先合 / B. 并入加法批次 | **A**：可单独回滚、可先验收阅读面 |
| 2 | T9 是否本批就做 | A. 本批做 / B. 拆下一批 | **B**：T9 视觉面最大，等 T1–T8 跑一轮真实使用后再定 |
| 3 | 数字计数是否接受「只播一次」 | A. 接受 / B. 每次进入都播 | **A**：避免烦躁 |
| 4 | 统计页 6 个数字是否全部计数，还是只计 2 个主指标 | A. 全部 / B. 只计 streak + vocab | **A**：数量可控，且都已 `tabular-nums` |

> 以上四项确认后，才进入 M1 开工；M1 合并并验收后，再按 T2 → T8 顺序推进。
