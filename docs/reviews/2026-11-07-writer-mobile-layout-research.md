# 写作页移动端布局：调研、根因与落地（2026-11-07）

> 范围：`#view-writer` 在 ≤860px 视口下的滚动链、底部面板/页签可达性、软键盘让位、标题占位裁切。
> 本轮**不包含**桌宠遮挡修复与 agent 操作条实现（另派），但布局给它们留了位置。
> 证据目录：`_artifacts/2026-11-07-writer-shots/`（不入 git）。改前列数据来自 `facts.json` / `facts_keyboard.json`，改后来自 `verify.json` / `verify_keyboard.json` / `verify_focus.json`。
> 复测脚本：`_artifacts/2026-11-07-writer-shots/cdp_verify_layout.py`、`cdp_verify_keyboard.py`、`cdp_verify_focus.py`（headless Edge + CDP，非产品代码）。

---

## 0. 结论摘要

| 问题 | 根因 | 处置 | 改后实测 |
| --- | --- | --- | --- |
| 底部三个页签只露一条、看不见也点不到 | 桌面基规则 `top: 4.5rem` 与移动端 `bottom: 0` + `height` 同时生效，`position: fixed` 过约束 → `bottom` 被忽略；sheet 停在 `top:72px`，恰好在 852 视口底部露出 39.8px 条带；`z-index:1100` 还盖住 dock（z 1000） | 补 `top: auto`，回到 `bottom:0 + translateY(100%)` 的完整离屏；页头提供常驻「问题与历史」入口 | 闭包 sheet `y=852`，可见 **0px**；展开后三个页签 `y=218.5–256.3`，`elementFromPoint` 命中自身 |
| 嵌套滚动「看不见也点不到」 | `.view { overflow-x: hidden }` 把 `overflow-y: visible` 计算成 `auto`，`#view-writer` 变成永不滚动的隐式滚动容器 | 移动端改 `overflow-x: clip; overflow-y: visible`（`clip` 不创建滚动容器） | 滚动容器只剩 `html`；`#view-writer` `scrollHeight == clientHeight` |
| 键盘弹出压死编辑区 | 全站按 `vh` 算高度；只监听 `window.resize`，adjustPan/iOS 下拿不到键盘高度 | 新增 `--writer-vvh` / `--writer-keyboard-inset`，由 `visualViewport` 写入；展开 sheet 用 `bottom: inset` 抬升 | 430px 可视高下聚焦编辑器：`scrollY=361`，编辑框 `165.4–325.4`、工具栏 `337.4–372.4`，dock 从 `372` 起 |
| 标题占位被右侧裁掉 | 单行 `<input>` 的 placeholder **不参与换行**；示例文本宽 495.2px，输入框 `clientWidth` 仅 319/286px | 改成 `textarea rows=1` + JS 自适应高度；Enter 仍然失焦不换行 | `scrollHeight=74px`（两行 × 29px + padding），占位完整 |
| `100vh` 陷阱 | 基规则与移动端都按整屏 `100vh` 定高，键盘态必然溢出 | 默认值 `100dvh`，JS 可用时覆盖为实时 `visualViewport.height` | 393×430 下 `--writer-vvh: 430px`；visualViewport-only 场景 `inset: 422px` |

---

## 1. 取证方法

- 浏览器：headless Edge（`--headless=new`）+ CDP（`Emulation.setDeviceMetricsOverride`，`mobile=true`，DPR=1）。
- 视口：393×852、360×800；键盘态用两种方式分别覆盖：
  - **adjustResize 型**（Android 默认）：直接把布局视口压到 430px；
  - **adjustPan / iOS 型**：布局仍 852，用只改 `visualViewport.height=430` 的桩对象 + 派发 `resize`，验证 `--writer-keyboard-inset` 分支。
- 判定指标：`getBoundingClientRect()`、`scrollHeight/clientHeight`、`getComputedStyle().overflowY`、`document.elementFromPoint()`。
- 外部产品：同机 headless Edge 393×852 / 393×430 截图；有登录墙、Cloudflare、无 Web 客户端的按证据等级标注（见 §5）。

---

## 2. 改前实测（origin/master）

### 2.1 393×852

| 块 | 几何 |
| --- | --- |
| 文档 | `scrollHeight 1212` vs 视口 852 → 溢出 **360px** |
| ticker + 顶部导航 | 36 + 52 = 88px |
| `.writer-header-bar` | 高 **238px**（含 eyebrow、标题、两行按钮） |
| 模式切换条 | 49.4px |
| 编辑卡 | 420px（标题 44 + 编辑框 240 + 工具栏 35 + 内外边距） |
| 工具栏 | `y 839–874`，已在视口外 |
| `#writer-panel`（闭包） | `top:72px`、`height:647.5`、`bottom:719.5`；`transform: translateY(647.5px)` |
| 三个页签 | `y 732.5–772.3`，**可见 39.8px**（被裁的条带） |
| 底部 dock | `y 794`、`h 58`、`z 1000`；sheet `z 1100` 整片压住 |

### 2.2 键盘态 393×430

- sheet `height 326.8`、`top 398.8`；
- 编辑区 `y 587`，**完全在可视区外**；
- 工具栏 `y ≥ 700`，不可达。

### 2.3 滚动链

| 元素 | `overflow` | 是否真滚动 |
| --- | --- | --- |
| `html` | `auto` | 是（唯一） |
| `body` | `auto` | 否 |
| `#view-writer` | `overflow-x: hidden` → 计算 `overflow-y: auto` | **否**（隐式容器、`scrollHeight == clientHeight`） |

### 2.4 占位裁切量化

- 占位文本：`作文标题（如：Mein Urlaub in Berlin / B1 备考书信）...`，按标题字体实测宽 **495.2px**；
- 输入框 `clientWidth`：393 视口 **319px**、360 视口 **286px**；
- `<input>` 单行 + `white-space` 默认 `pre` → 文本只能横向溢出，右侧被裁。
- 改用 textarea 后 `white-space: pre-wrap`，同字体下两行高 74px，占位完整（见 `new-393x852-top.png`）。

---

## 3. 根因明细（含 CSS 证据）

### 3.1 `position: fixed` 过约束（P0）

`.writer-sidebar` 桌面基规则同时给了 `top: 4.5rem`；移动端只覆盖 `bottom: 0` 与 `height`。
按 CSS 2.1 §10.6.4，`top`、`bottom`、`height` 三者中 `bottom` 会被**静默忽略**：

```css
/* 改前（移动端） */
.writer-sidebar {
  position: fixed;
  top: 4.5rem;      /* 基规则没被覆盖 */
  bottom: 0;        /* 被忽略 */
  height: 647.5px;  /* 由 76vh 算出 */
  transform: translateY(100%);
}
```

结果：`top=72` 生效，`translateY(647.5)` 后元素顶边 = 719.5，底边 = 1367，视口 852 → 底部露出 39.8px 页签条；同时 z 1100 盖住 dock。

**修法**：`top: auto`，让 `bottom:0` 参与计算；并用 `translateY(100%)` 保证闭包完全离屏。

### 3.2 `overflow-x: hidden` 派生嵌套滚动

`.view { overflow-x: hidden }`；按 CSS Overflow 3，若一轴为 `hidden` 而另一轴为 `visible`，后者计算为 `auto`。
于是 `#view-writer` 成了滚动容器，但它自身高度随内容增长，永远不产生滚动 → 用户滚的是 `html`，而任何 `scrollIntoView`/`overflow` 判断都可能在错误的容器上算。

**修法**：移动端 `overflow-x: clip`（不创建滚动容器）+ `overflow-y: visible`，只保留 `html` 一条滚动链。

### 3.3 `100vh` 与键盘

`100vh` 是**布局视口**高度，不随软键盘变化：

- adjustResize：`window.innerHeight` 变矮，`100vh` 不变（部分 WebView 会锁在初始值）→ 固定高元素被顶出；
- adjustPan / iOS：布局视口完全不变，只有 `visualViewport` 变矮 → `resize` 也可能不触发。

**修法**：`--writer-vvh` 默认 `100dvh`，JS 可用时写实时 px；sheet 用 `min(calc(var(--writer-vvh) * 0.76), 680px)`。
`--writer-keyboard-inset = layoutHeight − visualViewport.height − visualViewport.offsetTop`；展开态 `bottom: inset`，adjustResize 下 inset=0 不产生副作用。

### 3.4 单行 input 的 placeholder 不可换行

`::placeholder` 继承输入框的 `white-space`；`<input>` 只能是单行，宽度又由容器决定 → 唯一出路是换控件，而不是 `ellipsis`。

### 3.5 安全区与底部固定栏

闭包 sheet 的底部内边距 `calc(0.75rem + 58px + env(safe-area-inset-bottom, 0px))`，保证滚到底时最后一个控件不被 dock / home indicator 吃掉。实测计算值 70px（安全区为 0 的环境）。

---

## 4. 改后实测

### 4.1 两种视口（闭包 → 展开）

| 指标 | 393×852 | 360×800 |
| --- | --- | --- |
| 文档 `scrollHeight` | 1007（+155） | 1007（+207） |
| 页头 `.writer-header-bar` | 171.1px（y 104–275.1） | 171.1px |
| 标题 textarea | y 440.4，h 74，两行 | y 440.4，h 74，两行 |
| 编辑框 | y 526.4，h 160，完整可见 | y 526.4，h 160，完整可见 |
| 工具栏 | y 698.4–733.4 | y 698.4–733.4 |
| 闭包 sheet | y 852，可见 0px | y 800，可见 0px |
| 展开 sheet | y 204.5–852，h 647.5 | y 192–800，h 608 |
| 展开后页签 | y 218.5–256.3，三个都 `hitSelf` | y 206–243.8，三个都 `hitSelf` |
| 滚动容器 | 仅 `html`；`#view-writer` 不再滚动 | 仅 `html` |

页签逐个点击验证（`switchWriterPanelTab`）：诊断分析 / 问题清单 / 版本快照的 `paneVisible=true`、`active=true`、`insideViewport=true`、`elementFromPoint` 命中按钮本身。

### 4.2 键盘态

| 场景 | 结果 |
| --- | --- |
| adjustResize 393×430，聚焦编辑器 | `scrollY 361`；标题 `y≈79`、编辑框 `165.4–325.4`、工具栏 `337.4–372.4`；dock 从 372 起（工具条仅 0.4px 亚像素贴边） |
| adjustResize 360×430 | 同上（数值一致） |
| 展开 sheet（430 高） | `y 103.2–430`，h 326.8；页签 `y 117.2–155`，三个都 `hitSelf`；三个 pane 切换正常 |
| visualViewport-only（布局 852 / 可视 430） | `--writer-vvh: 430px`、`--writer-keyboard-inset: 422px`；展开 sheet `bottom: 422px` → 矩形 `y 103.2–430`，完整落在键盘上方 |
| 遮罩点击 | `mobile-panel-open` 与 `body.writer-panel-lock` 都正确移除 |

### 4.3 与既有守卫的兼容

`tests/test_writer_mobile.py` 钉住的是「`bottom: 0` + `translateY(100%)` + `height: min(...)` + `max-height: none` + `overflow-y: auto` + `padding-bottom` 含 58px + toggle 函数体含 `writerMobilePanelDidAutoSwitch` + 所有 `var(--*)` 有声明」。
本次没有改这些契约，只补 `top: auto` 与两个新变量声明 → `32 passed`；`build_index_html` + `check_index_html_sync` PASS。

---

## 5. 外部参考（移动端写作界面怎么排）

> 证据等级：**[M]** 本次 DOM 实测；**[S]** 本次 393/430 截图判读；**[R]** 公开资料/产品长期行为，未在本机复测；**[U]** 本次无法验证（登录墙/Cloudflare/无 Web 客户端）。

| 产品 | 面板形态 | 抽屉/面板高度与拖拽 | 键盘弹出处理 | 正文可视高度 | 专注模式 | 等级 |
| --- | --- | --- | --- | --- | --- | --- |
| LanguageTool（语法检查） | 编辑区全宽 + 结果内联；底部固定操作条（Example Text / Clipboard） | 无抽屉；底部条固定 ~110px | 430 高下底部条随布局一起收缩，编辑区仍在上半屏 | 393×852 下编辑区约 480px 高 | 无 | [S] `ext-languagetool-393x852.png` / `-393x430.png` |
| DeepL Write | 上下两段：输入框 + 「修改建议」结果卡；结果常驻下方，不是抽屉 | 无抽屉；输入卡约 170px 高 | 未做专门让位（结果区在下方，键盘遮挡由页面滚动解决） | 结果区首屏约 250px | 无 | [S] `ext-deepl-write-*.png` |
| Ginger（语法检查） | 单列：textarea 200px + 两个动作按钮 + 结果区在下 | 无 | 键盘态 430 高时 `textarea` 仍 200px，页面整体可滚 | 编辑框固定 200px | 无 | [M] `external.json` |
| Scribens | 紧凑工具栏 + 单列编辑区，结果替换内容区 | 无 | 页面滚动 | 约 300px | 无 | [S] `ext-scribens-*.png` |
| Dillinger（Markdown） | 侧栏 drawer（文件/导出），正文单栏 | 抽屉盖住左侧约 80% 宽，点遮罩关闭 | 页面滚动 | 约 600px | 无 | [S] `ext-dillinger-*.png` |
| Obsidian 移动端 | 编辑区全屏 + 右侧栏/底部工具条；命令面板是底部 sheet | 半屏 sheet，可下拉关闭 | 编辑器自身滚动，工具栏贴键盘上沿 | 约 500px | 有（隐藏 UI） | [S] `ext-obsidian-*.png`；细节 [R] |
| iA Writer | 纯文本全屏，键盘上方一条格式/统计条 | 无面板 | 键盘上沿工具条，正文自动让位 | 约 380px（键盘态） | 有（专注模式） | [S] `ext-iawriter-393x852.png`；[R] |
| Ulysses | 编辑器全屏 + 底部/侧边 inspector；建议面板是覆盖层 | 覆盖式面板，非拖拽 | 键盘态收窄正文，工具栏贴键盘 | 约 400px | 有 | [S] `ext-ulysses-393x852.png`；[R] |
| Notion / Google Docs 移动端 | 编辑区全屏；评论/建议是底部 sheet 或独立页 | 半屏 sheet，可拖到全屏 | 键盘态正文收缩，工具栏贴键盘 | 未能实测 | 无 | [U]（登录墙；`ext-notion-*`、`ext-gdocs-*` 截图不可用） |
| Bear | 编辑器全屏 + 底部格式条；标签/信息面板 | 底部 sheet | 工具栏贴键盘上沿 | 未能实测 | 有 | [U]（无 Web 客户端；`ext-bear-393x852.png` 为落地页） |

**共性结论**（去除未验证项后）：

1. **编辑区永远占主位**，诊断/建议不长期挤占正文；要么内联（LanguageTool、DeepL Write），要么收进可关闭的面板（Obsidian、Ulysses）。
2. **键盘态让位是硬要求**：要么把工具条贴到键盘上沿（iA Writer、Obsidian），要么整体滚动到焦点（Scribens、Ginger）。
3. 需要「全篇诊断」的产品（LanguageTool / DeepL Write）都把结果放在**输入之后**，而不是固定在视口底部与编辑区抢高度。
4. 没有产品会把「诊断面板」以 40px 条带常驻在底部——这正是本次要消除的反模式。

---

## 6. 方案对比与选择

> 数字均为 393 宽、852/800 高；键盘态按 430 可视高估算（正文可视高度 = 键盘上沿 − 编辑卡起始 y）。

### 方案 A：编辑优先 + 底部抽屉（**已采用**）

- 正文占满；诊断 / 问题 / 版本收进底部 sheet，半屏（`min(76% vvh, 680px)`）；点「问题与历史」或页签打开。
- 393×852：正文可视 **526.4 → 733.4**（编辑框 + 工具栏约 207px），标题 + 工具栏同屏；进入诊断 **1 步**（点按钮）。
- 360×800：同上，编辑框 160px 完整；文档仅溢出 207px（草稿库）。
- 键盘态 430：聚焦后编辑框 160px + 工具栏 35px 全部在 dock 之上，可视正文 **约 160px**；进入诊断仍需 1 步（按钮固定在页头，滚动后需先回顶或点 dock？——按钮在页头，键盘态需要上滚一次）。
- 与设计语言：复用既有 `--paper / --ink / 4px 硬阴影 / 180ms ease`，无新控件形态；不引入手势库，**冲突最小**。
- 360px 下可写：是（编辑框 286×160）。

### 方案 B：分栏切换（写作 / 诊断互斥 tab）

- 两个 tab 各占满；写作时正文可达约 500px（852 下），诊断时无正文。
- 进入诊断 **1 步**（tab），但**丢失上下文**：看诊断时看不到原文，无法对照下划线位置。
- 360px 下可写：是；但与「选中文本→就地操作」的后续 agent 方向冲突（切走后选区丢失），且现有页签语义要重做。
- 动效上要新增整页转场，和当前「无边框、就地」语言不一致。

### 方案 C：编辑 + 底部固定摘要条

- 只显示「N 处问题 / CEFR 等级」，点开才展开完整面板。
- 正文可视高度比 A 少 **约 44px**（常驻条 + 安全区），进入诊断 **2 步**（点摘要 → 点页签）。
- 360px 下可写：是；但它把「常驻底栏」重新引回来，和本次要消除的「底部条带」形态接近，且摘要条会与 dock 叠加。

### 推荐

**A**。理由是：进入诊断只需 1 步、正文高度损失可控、诊断与原文可同屏对照（半透明遮罩 + 可滚面板）、无需新交互模型，且为后续 agent 浮动操作条留出了正文上方的空间。B 的上下文丢失与 C 的底栏叠加都和现有设计语言/后续 agent 方向冲突。

---

## 7. 为桌宠 agent 预留（只出设计）

### 7.1 交互落点：选区浮动条，不挂桌宠

```
选中文本
  └─ 选区上方/下方 12px：浮动操作条（改写 / 解释 / 存卡）  ← 就地，跟随选区
       └─ 点「改写」：条内切换为建议卡（原句 / 建议 / 接受 / 忽略）
            └─ 接受后：只替换选区，不整段重排
```

- **落点**：`#ide-editor` 内、选区 rect 的 `top − 44px`（不够则下方 `bottom + 8px`），水平夹在视口内。
- **不放进抽屉**：抽屉是「全篇视角」，会遮住原文；选区内联操作需要原文对照。
- **不做成独立浮层盖住输入区**：浮动条只在有选区时出现，无选区即销毁。

### 7.2 为什么不能让桌宠悬在输入区上

| 风险 | 具体表现 |
| --- | --- |
| 遮挡 | 桌宠 63×63，按当前坐标 `x 324–387 / y 721–784`，正好压住编辑卡右下角与工具栏；本轮实测编辑框与桌宠纵向重叠为 0 只是因为它现在停在下边缘，滚动/键盘变化后必然重叠 |
| 误触 | 桌宠是常驻可点元素，与「清空」「格提示」按钮同一区域；点击穿透策略不可控 |
| 键盘后位置失控 | 桌宠按 `bottom` 定位；adjustResize 后布局视口 430，`bottom: 0` 会把它抬到键盘正上方，恰好盖住正在编辑的行；adjustPan 下它又留在原处，可能落到键盘后面 |
| 焦点抢占 | 桌宠若带 `tabindex`/可聚焦，会打断 contenteditable 的输入法组合态 |

**结论**：桌宠只在**非编辑态**（写作页未聚焦编辑器、或面板收起且无选区）出现在右下角；编辑态必须让位（淡出或移到页头），agent 能力走选区浮动条。

### 7.3 需要预留的状态位（只命名，不实现）

| 状态 | 建议归属 | 命名 |
| --- | --- | --- |
| 无选区 | 编辑器 | `data-agent-state="idle"` |
| 有选区 | 编辑器 | `data-agent-state="selected"`，选区 rect 写入 `--agent-anchor-x/y` |
| 思考中 | 浮动条 | `data-agent-state="thinking"`（条内 spinner，禁用按钮） |
| 建议待确认 | 浮动条 | `data-agent-state="proposed"`，带 `data-agent-action="accept|reject"` |
| 错误 | 浮动条 | `data-agent-state="error"`（内联文案 + 重试） |
| 桌宠让位 | `#companion` | `body.writer-editing`（由编辑器 focus/blur 切换） |

接口位置建议：`static/js/writer.js` 内新增 `initWriterAgentSelection()`（本轮不建）；DOM 锚点 `#writer-agent-bar` 挂在 `#view-writer` 末尾，`position: fixed`、`z-index: 1090`（低于 sheet 1100、高于 dock 1000）。样式 token 全部复用现有变量，不新增颜色。

---

## 8. 验收与证据

| 项 | 证据 |
| --- | --- |
| 闭包无条带 | `new-393x852-top.png`、`new-360x800-top.png`；`verify.json` 中 sheet `y=852/800`、`visiblePx=0` |
| 页签可达 | `new-393x852-panel-open.png`、`new-360x800-panel-open.png`、`new-393x430-panel-open-focus.png`；三个 tab `hitSelf=true` |
| 键盘让位 | `new-393x430-focus-scrolled.png`、`new-360x430-focus-scrolled.png`、`new-393x852-vv-only-open.png` |
| 占位完整 | `new-393x852-top.png` 中两行完整；`titleInput.scrollHeight=74` |
| 单一滚动链 | `verify.json` → `scrollables` 仅 `html`（关闭态） |
| 自动测试 | `pytest tests/test_writer_mobile.py` → `32 passed` |
| 生成物一致 | `build_index_html.py` + `check_index_html_sync.py` → PASS |

### 8.1 模拟器装机实测（emulator-5554，411×866 CSS / dpr 2.625）

| 项 | 结果 |
| --- | --- |
| 标题 | `#writer-title` 已是 `TEXTAREA`，高 74px（两行），右边距 374 < 411，末尾「...」完整 |
| 闭包 | `transform: translateY(658.155px)`，面板顶边 = 866 = 视口底；页签 `rect.top 879 > 866`，完全离屏 |
| 抽屉展开 | `rect 208→866`；三页签 `221–264`；「问题清单 / 版本快照 / 诊断分析」依次切换、高亮正常 |
| 键盘 | 真实软键盘弹出后 `visualViewport = 554`、`--writer-vvh: 554px`、`inset 0`；编辑区 `211–371`、工具栏 `383–417`、dock `496–554`，工具栏未被压住 |
| 遮罩 | 点击 (540,300) 后 `mobile-panel-open` 移除、transform 回 658px、scrim 淡出 |

> 装机陷阱（**必看**）：APK 版本号不变时，`files/static.version` 会走「只补缺失文件」快路径，旧 `index.html` 留在设备上；同时旧 Service Worker（`delector-static-v5.21.1`）还会缓存旧 CSS。验证前必须先确认 DOM 里 `#writer-title` 是 `TEXTAREA`、CSS 里含 `top: auto`，否则测的是旧资源。


---

## 9. 未覆盖与风险

1. **真机键盘形态**：模拟器（411×866，API 37，软键盘后可视 554px）已实测通过；折叠屏、分屏、第三方输入法（含候选词条）仍未覆盖。
2. **安全区实际值**：模拟器 `env(safe-area-inset-bottom)=0`；刘海/home indicator 机型需在真机确认 `padding-bottom` 生效。
3. **桌宠遮挡**：本轮未动 `#companion`，它仍可能压住工具栏右下角；按 §7 的让位规则另派实现。
4. **横向 320px**：未纳入（低于项目现有最小支持宽度）；若支持，标题会折三行，`maxHeight 96px` 会触发内部滚动。
5. **页签入口只有一个**：闭包态完全依赖页头「问题与历史」。若后续把它收进溢出菜单，需要同时提供底部常驻入口。

---

## 10. 附录：移动端 WebView 布局检查清单（初稿）

> 用法：改任何「有固定定位 + 输入框 + 底部面板」的移动端页面时逐条勾。每条给出**判据**和**验收方法**，不写散文。

### A. 视口单位与键盘

- [ ] **禁止用 `100vh` 定容器高度**。默认写 `100dvh`；需要实时值写 `var(--app-vvh, 100dvh)`。
  - 判据：键盘弹出前后 `getComputedStyle(el).height` 必须变化（adjustResize）。
- [ ] **同时监听 `visualViewport.resize` 和 `scroll`**，不要只监听 `window.resize`。
  - 判据：adjustPan 形态下 `visualViewport.height` 变、`innerHeight` 不变，变量仍要更新。
- [ ] **键盘遮挡量公式**：`inset = layoutHeight − visualViewport.height − visualViewport.offsetTop`，不得为负。
- [ ] **底部固定元素**：展开态 `bottom: var(--keyboard-inset, 0px)`；adjustResize 下 inset=0 不应产生位移。

### B. 安全区

- [ ] 底部固定栏/抽屉必须有 `padding-bottom: calc(<内容间距> + <栏高> + env(safe-area-inset-bottom, 0px))`。
  - 判据：`getComputedStyle(sheet).paddingBottom` ≥ 内容间距 + 栏高。
- [ ] `viewport-fit=cover` 已开启，否则 `env()` 恒为 0。
- [ ] 安全区只加在**滚动内容末端**，不要加在 `position: fixed` 的 `height` 上（会导致高度跳变）。

### C. 固定定位几何

- [ ] `position: fixed` 若同时写了 `top` / `bottom` / `height`，逐项确认谁被忽略（浏览器按 over-constrained 规则静默丢弃 `bottom`）。
  - 判据：改完打印 `getComputedStyle(el)` 的 `top/bottom/height` 三者，`top + height == bottom` 才自洽。
- [ ] 移动端覆盖桌面基规则时，显式写 `top: auto`（或 `bottom: auto`），不要只覆盖一半。
- [ ] 抽屉「隐藏」用 `transform: translateY(100%)` 或 `visibility: hidden`，**不要**用「只露一条」的 peek。
  - 判据：闭包时 `rect.top >= innerHeight` 或 `rect.bottom <= 0`，可见像素 = 0。

### D. 滚动链

- [ ] 全页只允许**一个**滚动容器（通常是 `html`）。
  - 判据：遍历 `body *`，`overflow-y` 为 `auto|scroll` 且 `scrollHeight > clientHeight` 的元素，除抽屉内部外应为 0。
- [ ] `overflow-x: hidden` 会把另一轴 `visible` 计算成 `auto`；需要裁切但不滚动时用 `overflow-x: clip`。
- [ ] 面板内部允许滚动时，给它 `overscroll-behavior: contain`，避免滚动穿透到页面。
- [ ] 打开面板时给 `body` 加 `overflow: hidden`（并记录原值），关闭时恢复；否则背景会跟着滚。

### E. 输入与占位文字

- [ ] 单行 `<input>` 的 placeholder **不会换行**；长示例文案必须换 `textarea` 或缩短文案，不要用 `text-overflow: ellipsis` 掩盖。
  - 判据：`canvas.measureText(placeholder).width <= input.clientWidth`，否则换控件。
- [ ] 自适应高度 textarea：`height:auto → scrollHeight`，并设 `max-height` 与 `overflow-y:auto` 上限。
- [ ] 键盘聚焦后，用 `scrollIntoView({block:'nearest'})` + `scroll-margin-bottom`（含底部栏 + 工具栏高度）让位；延迟 ≥ 300ms 等键盘动画结束。
- [ ] `contenteditable` 的 `data-placeholder` 方案（`::before`）要单独检查换行与高度。

### F. 悬浮元素（桌宠 / 浮层）遮挡判据

- [ ] 悬浮元素与「输入框、工具栏、页签」的矩形交集必须为 **0**：
  `overlapW = max(0, min(a.right,b.right) − max(a.left,b.left))`，同理 `overlapH`。
- [ ] `elementFromPoint(控件中心)` 必须命中控件自身（或其后代），不得命中浮层。
- [ ] 编辑态（编辑器 `focus`）悬浮元素必须让位：`body.writer-editing` 时 `opacity: 0; pointer-events: none`。
- [ ] 悬浮元素不得设置 `tabindex` 或可聚焦，避免打断输入法组合态。
- [ ] 键盘态下悬浮元素若按 `bottom` 定位，必须和抽屉一样接 `--keyboard-inset`，否则会跳到键盘正上方。

### G. 验收脚本最小集

```text
1. 393×852 / 360×800 / 393×430 / 360×430 四档截图
2. 闭包态：面板可见像素 = 0；唯一滚动容器 = html
3. 展开态：目标页签/按钮 elementFromPoint 命中自身
4. 键盘态：聚焦后编辑框完整在可视区，工具栏不被 dock 覆盖
5. 占位文案：measureText 宽度 ≤ 容器宽度（或已换行）
6. 安全区：computed padding-bottom 含 58px + env()
7. 控制台无报错；`build_index_html` + `check_index_html_sync` 通过
```

### H. Android WebView 静态资源缓存（装机验证必查）

- [ ] **装完先验「跑的是不是新包」**：`adb shell pm path` 的 base.apk 大小与本地 APK 一致；`assets/static/index.html` 的 md5 与构建产物一致。
- [ ] 版本号未变时，`files/static.version` 相同会走「只补缺失文件」快路径 → 旧 `index.html` 留存。验证前清 `files/static` + 版本标记，或改版本号。
- [ ] Service Worker（如 `delector-static-v5.21.1`）会缓存旧 CSS/JS；验证前注销旧 SW 或提升 cache 名。
- [ ] **DOM/样式反证**：改版验证至少断言一个结构性变化（例：`#writer-title` 的 `tagName === 'TEXTAREA'`）和一个样式变化（例：sheet 计算样式含 `top: auto` / `translateY(100%)`），否则截图再像也不能证明新代码生效。
- [ ] `adb install -r` 遇到 `INSTALL_FAILED_VERSION_DOWNGRADE` 时用 `-r -d`，**不要 uninstall**（会丢用户数据）。
