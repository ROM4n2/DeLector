# 全站视觉换皮调研：现状审计、范围与分期

> 日期：2026-11-08　|　性质：**只读调研**（未改 `static/`、未改 `android/`、未改 `docs/adr/`、未改任何代码）
> 基线：`origin/master` `af18632`（含 #290 静态资源指纹）
> 上游：[外部 UI 设计参考库](2026-11-06-external-ui-design-reference-library.md)、[动效与生动力调研](2026-11-07-motion-vitality-research.md)、[考试布局重构调研](2026-11-07-exam-layout-redesign-research.md)、ADR-0029、ADR-0030
> 证据标记：`[S]` 静态代码审计（本机脚本统计，可复现）｜`[T]` token 数值推导（WCAG 对比度计算）｜`[A]` 运行时实测｜`[U]` 未验证

---

## 0. 结论先行

1. **换皮的真实成本不在 token，在 token 之外。** `style.css` 规则体内仍有 **582 处 hex、118 种 rgba**；颜色类声明中 **33.4%（748/2239）直接写字面量**，不走 `var()` `[S]`。只改 `tokens.css` 与 `:root` 只能覆盖约三分之二的颜色面。
2. **同一套设计系统存在三层实现漂移**：`tokens.css` 73 个变量；`style.css` 有 **3 个 `:root` 块、87 个变量**（多 14 个本地变量，值与 tokens 无冲突）；`workbench.css` 另立 **17 个局部变量**，其中 `--good-soft/--hard-soft/--again-soft` 是硬编码浅色 `[S]`。
3. **主应用与工作台是两种视觉方言**：主应用是「1.5px 墨线 + 硬投影 + 直角」，工作台是「12px 圆角 + 软阴影 + 160/169 处 `var()`」`[S]`。iframe 不继承父文档 `:root`，主题变量必须显式注入，不能靠父页覆盖。
4. **现有无障碍有既存欠账，换色会放大它**：`--coral` 于 `--paper` 上 **2.82:1**、白字于 coral **2.99:1**、`--mustard` 于纸面 **1.72:1**、`--muted` **3.49:1** `[T]`。当前靠「大字号/粗体/冗余编码」成立，新配色若沿用同等明度会直接踩 WCAG。
5. **结构风险高于视觉风险**：**131 个选择器重复定义（多出 162 次）**、**186 处 `!important`**、155 个 `@media`，且 **没有任何视觉回归测试**。一次性重排 `style.css` 的失败模式是静默错位，不是编译错误。
6. **模板层也有盲区**：`index.html` 有 **117 个内联 `style` 属性**、`workbench.html` **116 个**、抽屉 35 个，这些不走 token `[S]`；另有 **79 处 JS 颜色字面量**（companion 21、listen-lab 14、folio 11 最多）。
7. **换皮应分四步走，不建议一次性全站重排**：① 先建视觉基线（截图矩阵 + computed-style 快照 + 字面量预算闸）；② 只换 token 验证管线；③ 按组件族（按钮/导航/卡片/抽屉/播放器）逐个换；④ 最后收口 workbench iframe、A1/考试/伴读。布局重排应单独立项。
8. **本轮未做运行时取证**：Edge headless 截图命令未产出文件（环境问题），`[A]` 级证据留到 Phase 0 的截图基建里补；本报告的量化结论均可由仓库内静态文件复现。

---

## 1. 范围盘点

### 1.1 全站形态

| 面 | 入口 | 体量 | 备注 |
| --- | --- | --- | --- |
| 主应用 9 个视图 | `static/index.html`（由 `index.skeleton.html` + 片段装配） | 147,103 B | home / encounter / reader / cards / progress / writer / exam / german / search |
| 主样式 | `static/style.css` | **13,492 行** | 3 个 `:root`、1,589 个去重选择器 |
| 共享 token | `static/css/tokens.css` | 73 个变量 | **仅 workbench 加载**；主应用靠 `style.css :root` 镜像（ADR-0030 §2.1） |
| 工作台 iframe | `static/german/workbench.html` | 150,890 B | 独立文档，加载 `fonts.css` + `tokens.css` + `workbench.css` |
| 工作台样式 | `static/css/workbench.css` | 378 行 | 44 处 hex、13 处 rgba、169 处 `var()`；圆角 12px |
| 字体 | `static/css/fonts.css` | 21 个 `@font-face` | 全部本地 woff2；外部 `googleapis` 只出现在注释（离线要求） |
| 浮层 | `static/modals/*.html` 8 个 + 抽屉 + 玩家/提示条 | 约 5.9 万 B | 设置、导入、润色、测验、完形、版本预览等 |
| 伴读组件 | `static/layout/companion.html` + `companion*.js` / `cp-*.js` | 6,242 B HTML + 约 17 万 B JS | P1–P4 刚落地，视觉与位置契约都较新 |

### 1.2 各视图的样式比重（按选择器命中数）`[S]`

| 组件族 | 命中数 | 组件族 | 命中数 |
| --- | ---: | --- | ---: |
| `.companion` | 172 | `.deck` | 64 |
| `.a1-` | 146 | `.quiz` | 58 |
| `.enc`（生词/遇词） | 116 | `.drawer` | 57 |
| `.writer` | 106 | `.card` | 55 |
| `.folio` | 35 | `.tok`（正文词元） | 32 |
| `.satz-` | 31 | `.exam` | 26 |
| `.nav` | 23 | `.cloze` | 22 |
| `.reader` | 15 | `.shadow-player` | 8 |

单段最大的样式块：Shadow Reading 1,004 行、Sticky Note Drawer 650 行、Inlay Hints 621 行、Morphology 547 行、Quiz 490 行、A1 Schreiben 445 行、Reader Workspace 428 行、移动端优化 421 行、A1 Hören 421 行 `[S]`。

> 判断：**「阅读器 + 抽屉 + 播放器」三块就占约 2,100 行**，是全站换皮的主战场；A1/考试/工作台是第二战场。

---

## 2. 量化审计

### 2.1 颜色：token 覆盖不到三成

| 指标 | 数值 | 口径 |
| --- | ---: | --- |
| 规则体内 hex 字面量 | **582 处 / 145 种** | 已排除 `:root` 块 |
| 规则体内 rgba 字面量 | **118 种** | 同上 |
| 颜色类声明总数 | 2,239 | color/background/border/shadow/fill/stroke |
| 走 `var()` 的颜色声明 | 1,382（61.7%） | |
| 直接写字面量 | **748（33.4%）** | 其余为 `inherit/transparent/none` |
| 最高频字面量 | `#1a1a1a` 78、`#fff` 58、`#ed6f5c` 19、`#ffffff` 17、`#15140f` 17、`#b44322` 14、`#2980b9` 13 | 前 7 名里 4 个是 token 值的「影子副本」 |

含义：`#1a1a1a`、`#ed6f5c`、`#15140f`、`#faf8f5` 等本质是 `--ink/--coral/--ink/--paper` 的手抄值。**换色时这些副本不会跟随，会形成新旧两套墨色并存**。

### 2.2 Token 漂移

| 文件 | `:root` 块 | 变量数 | 与 `tokens.css` 差异 |
| --- | ---: | ---: | --- |
| `static/css/tokens.css` | 1 | 73 | 基准 |
| `static/style.css` | **3** | 87 | 多 14 个本地变量（`--font-*`、`--drawer-*`、`--reader-fs`、`--writer-vvh` 等），同值无冲突 |
| `static/css/workbench.css` | 1 | 17 | 前 15 个映射到 tokens（带硬编码 fallback），`--good-soft/--hard-soft/--again-soft` 为独立浅色 |

`[S]` 审计提醒：只按 `:root` 抓 `var()` 会误报 8 个「未定义变量」，实际它们都在局部作用域（`--reader-content-width`、`--cards-empty-tone`、`--enc-*`）或由 JS 写入（`--bubble-arrow-x/y`，`companion.js:1382/1385`）。换皮审计必须按「作用域 + JS setProperty」两级查，不能只扫全局。

### 2.3 排印与字面量

| 指标 | 数值 |
| --- | ---: |
| 非 `var()` 的 `font-family` 声明 | **311 处** |
| `!important` | **186 处** |
| `@media` | 155 个 |
| `@keyframes` / `infinite` | 16 / **7（与 ADR-0030 白名单一致）** |
| `grid-template-columns` | 43 处 |

换字体族的成本不在 `tokens.css` 的 5 行，而在 311 处直接写死字体栈的声明；其中 `--enc-display/--enc-body/--enc-mono` 是另一套局部字体栈（`style.css:11542-11544`），与全局 token 不同源。

### 2.4 内联样式与 JS 颜色（换皮盲区）

| 文件 | 内联 `style` 属性 | 颜色字面量 |
| --- | ---: | ---: |
| `static/index.html`（装配产物） | **117** | 19 |
| `static/german/workbench.html` | **116** | 10 |
| `static/modals/drawer.html` | 35 | 0 |
| `static/modals/quiz_overlay.html` | 20 | 0 |
| `static/views/writer.html` | 16 | 0 |
| `static/views/progress.html` | 11 | 10 |
| 其余模板合计 | 36 | 8 |

| JS 文件 | 颜色字面量 |
| --- | ---: |
| `companion.js` | 21 |
| `listen-lab.js` | 14 |
| `folio.js` | 11 |
| `hard-sentences.js` | 10 |
| `cp-drawer.js` / `rd-syntax.js` | 6 / 6 |
| `main.js` | 5 |
| `a1_writer.js` / `cp-drawer-proposals.js` | 3 / 3 |
| **合计** | **79** |

> `index.html` 是装配产物：改模板后必须跑 `python tools/build_index_html.py`，否则 `check_index_html_sync.py` 红。换皮涉及模板时必须走这条链。

### 2.5 对比度（WCAG 2.2）`[T]`

| 组合 | 对比度 | 判定 |
| --- | ---: | --- |
| `--ink #15140f` / `--paper #faf8f5` | 17.40:1 | 优 |
| `--pencil #5c554b` / paper | 6.94:1 | 正文可用 |
| `--moss #3b6e3f` / paper | 5.68:1 | 可用 |
| `--cherry #b03030` / paper | 5.98:1 | 可用 |
| 白字 / `--accent #c14a2b` | 4.90:1 | 正文勉强，小字要复核 |
| `--muted #8c8477` / paper | **3.49:1** | 仅大字/辅助态可用 |
| `--ink-faint #8b8676` / paper | **3.43:1** | 同上 |
| 白字 / `--coral #ed6f5c` | **2.99:1** | 不达 4.5:1 |
| `--coral` / paper | **2.82:1** | 不作为正文色 |
| `--mustard #e9b94a` / paper | **1.72:1** | 纯装饰/底色 |

含义：现行视觉是靠「字号落差 + 粗体 + 等宽小字 + 冗余编码」撑起来的，不是靠颜色对比。换皮若把强调色提亮或降低明度，会同时改变「看起来更现代」和「读不清」两件事，必须用对比度闸兜底。

---

## 3. 结构与工程风险

| # | 风险 | 证据 | 影响 | 缓解 |
| --- | --- | --- | --- | --- |
| R1 | 无视觉回归测试 | 仓库无截图/computed-style 基线 | 换皮回归只能靠肉眼，静默错位 | Phase 0 建 3 断点 × 9 视图截图矩阵 + 关键控件 computed-style JSON |
| R2 | 重复选择器与顺序依赖 | 131 个选择器重复、162 次额外定义；如 `.shadow-player` 3 次、`#view-progress` 3 次、顶栏两组 | 换皮若就地改旧规则，可能被后面的旧规则覆盖 | 只在文件末尾追加独立分区（与近期 PR 一致），不重排旧段 |
| R3 | `!important` 186 处 | `[S]` | 新规则需要更高优先级，易升级成 `!important` 军备竞赛 | 新增规则避开被 `!important` 锁死的属性；先列清单再改 |
| R4 | 主应用 / workbench 双文档 | 两个 `<link>` 集合不同；iframe 不继承父 `:root` | 只改主应用→工作台仍是旧皮肤 | 主题变量写入两边；或 iframe 注入共享主题类 |
| R5 | 模板 → 产物装配 | `index.skeleton.html` + includes + `build_index_html.py` | 手改 `index.html` 会被门禁判红 | 换皮改片段，统一重建 |
| R6 | 缓存与 Android 重解包 | `sw.js` `CACHE_NAME = delector-static-v5.21.1`；Android `static.version` + `BuildConfig.VERSION_CODE` | 用户可能看到新旧 CSS 混用 | 发版时 bump `CACHE_NAME` 与 versionCode；换皮 PR 明确「需发版才可见」 |
| R7 | PWA 主题色三处硬编码 | `head.html` `theme-color #faf8f5`、`manifest.json` `theme_color/background_color #faf8f5`、图标 SVG 内 `#1a1714` | 新纸色下状态栏/启动底色不匹配 | 新纸色落定后同步三处，加静态守卫 |
| R8 | 无暗色主题架构 | `prefers-color-scheme` 0 处、`data-theme` 0 处 | 若换皮含暗色，等于新增一套主题系统 | 先决定是否纳入；纳入则必须有第二套 token 与对比度闸 |
| R9 | ADR-0029 / 0030 约束 | 7 处 `infinite` 白名单；reduce 必须落终态；字形不得是唯一语义载体 | 换皮加动效/图标容易违规 | 换皮默认零新增循环动画；图标走 inline SVG + 可访问名 |
| R10 | 设计文档含历史稿 | `docs/design-system.md` 明确 §2/§3/§6.1/§7/§8.1 为历史稿，仓内无实现 | 按文档换皮会做出不存在的组件 | 以 `tokens.css` + `style.css` 现值为唯一真值，换皮后同步 §4/§5 |

---

## 4. 三条路线

### 路线 A：Token-only 换肤（低风险，建议先做）

- **范围**：`tokens.css` + `style.css :root`（2 份镜像）+ 高频影子字面量（`#1a1a1a`/`#ed6f5c`/`#15140f`/`#faf8f5` 等）替换为 `var()`。
- **能改**：纸色、墨色、强调色、CEFR 高亮、便签色、阴影、缓动。
- **不能改**：圆角、间距、字号阶梯、组件形态、布局。
- **成本**：改动集中，冲突面小；需 1 次全站目检 + 对比度闸。
- **风险**：中低。最大风险是字面量未清干净导致新旧混色。
- **适合**：验证「换皮管线」（截图基线、缓存、Android 重解包）是否成立。

### 路线 B：Token + 组件层（中风险，推荐作为主工程）

- **在 A 之上**：新增间距/圆角/边框宽度/字号阶梯 token，按组件族重绘：按钮、顶栏/底栏、卡片、抽屉、播放器、设置/导入模态。
- **能改**：视觉语言（例如直角↔小圆角、硬投影↔细边线）、信息密度、控件反馈。
- **不能改**：页面信息架构、视图布局、交互流程。
- **成本**：按组件族分 5–6 个 PR，每个都能独立目检；`style.css` 末尾追加分区。
- **风险**：中。重复选择器与 `!important` 是主要变量；需要按族回归。
- **适合**：真正的「换皮」，且能与现有并发纪律（2 个 worktree 上限）兼容。

### 路线 C：全站视觉重塑（高风险，不建议本季度）

- **在 B 之上**：改布局、改信息架构、改组件边界（如台账/考试/工作台重排）。
- **成本**：需要设计稿 + 视图级验收 + 移动端断点重做 + 工作台同步。
- **风险**：高。无视觉回归测试、Android/iOS 无真机覆盖、`style.css` 合并冲突面大。
- **前置**：Phase 0 基线 + 至少 5 份真实用户反馈（与 PROJECT_OVERVIEW 的宣传门槛一致）。

---

## 5. 建议分期

| 阶段 | 内容 | 产出 | 验收 |
| --- | --- | --- | --- |
| **P0 基线** | 截图矩阵（1440/1024/393 × 9 视图 + 工作台 + 5 浮层）、关键控件 computed-style 快照、对比度脚本、字面量预算闸 | `_artifacts/`（不入库）+ `tools/check_visual_tokens.py` | 换皮前后 diff 可读；闸门能判红 |
| **P1 Token** | 两处 `:root` 同步、影子字面量收敛、CEFR/便签/阴影重定值 | 1 个 PR | 全站目检 + 对比度全绿 + 7 处 `infinite` 不变 |
| **P2 组件族** | 按钮 → 导航 → 卡片/牌盒 → 抽屉 → 播放器 → 模态 | 5–6 个 PR | 每族截图 + 移动端 393 宽 |
| **P3 边界收口** | workbench iframe 主题注入、A1/考试/伴读、PWA 三处主题色 | 2 个 PR | 工作台与主应用同肤；manifest/theme-color 一致 |
| **P4 文档与发布** | `design-system.md` §4/§5 同步、CHANGELOG、缓存 bump | 发版 PR | 静态文档门禁 + Android 重解包验证 |

排序理由：先把「怎么证明没坏」建起来（P0），再动最小变量面（P1），然后按用户高频路径铺开（P2），最后处理跨文档与跨端（P3/P4）。

---

## 6. 待用户拍板的三件事

1. **换皮目标**：只换「材质与色彩」（路线 A/B），还是同时改「形态与密度」（路线 C）？
2. **是否纳入暗色主题**：当前零基础。纳入等于新增一套 token + 对比度闸 + 双主题截图矩阵，工作量约等于再做一个 P1–P2。
3. **是否先建视觉回归基建**：若不建，P2 的每个组件 PR 都只能靠人工目检；建议至少接受 P0 的前置投入。

---

## 7. 未验证 / 边界

- **本轮无 `[A]` 级运行时数据**：Edge headless 截图未产出文件（命令退出 0 但目录为空），未继续排查；建议 P0 用 Playwright/Edge 正常路径重做。
- **未覆盖**：iOS Safari、Android 真机色彩管理、系统级暗色、真实屏幕阅读器、低端机渲染性能（与 `PROJECT_OVERVIEW` 开放待办第 2、6 条一致）。
- **未做**：任何代码、样式、模板、Android 资产改动；本文件是唯一新增产物。
- **与既有决策的关系**：[下一批路线图](../plans/2026-11-07-next-batch-roadmap.md) §5 曾把「全站视觉批改」列为不做，理由是收益低、与既有设计冲突、无法验证。本调研**不推翻该结论**，只把「无法验证」这一条转成可执行的 P0 前置；是否启动换皮仍取决于第 6 节的三项拍板。

---

## 8. 横向调研：同类产品与官方设计系统

> 口径：只记录能落到「做法 + 数字 + 代价」的样本，不做产品收藏。每个样本给三行判断：
> **值得抄**（能直接变成 token / 规则）｜**慎抄**（视觉上成立，但拖慢我们的阅读或操作节奏）｜**移动端不可用**（在 393px 或触摸场景直接失效）。
> 标注 `[官方]` 为厂商文档原文，`[第三方]` 为实测/测评，`[T]` 为本次推导。

### 8.1 语言学习与阅读类

#### LingQ —— 「可调阅读器 + 词状态」

- **解决的问题**：把真实长文变成可点击、可追踪的生词阅读器。
- **值得抄**：阅读器给「字号 +/-」与「行距倍率」两个独立调节，行距可细调到 `0.80x`（用户社区普遍推荐值）`[第三方]`；词状态用 5 级（新词/学习中 1–4/已知）驱动高亮，让「读得懂多少」一眼可见。
- **慎抄**：5 级状态几乎全靠颜色区分（多种蓝 + 黄），色弱用户无法分辨；我们已有 CEFR 五色，换皮必须补「下划线/边标/形状」第二编码，否则是把同类缺陷复制一遍。
- **移动端**：可用，但设置项多、层级深，手机上要三次点击才能改行距；我们的抽屉设置应把「字号/行距」放在第一层。

#### Readlang —— 「点词即译，译完即卡」

- **解决的问题**：跨网站阅读时，把「查词」压缩成一次点击，并自动沉淀为复习卡。
- **值得抄**：译文以**行内气泡**贴着原词出现，不打断段落流；查过的词自动进入卡片队列——「阅读动作即采集动作」，与我们「精读 → 生词 → 卡片」的链路同构。
- **慎抄**：气泡覆盖原文，德语长词 + 中文释义会把一行撑成两行，连续查词时版面跳动明显；移动端点击热区与「选词/翻页」手势冲突。
- **移动端**：浏览器可用；Web Reader 扩展仅桌面。结论：**交互可抄，气泡形态在 393px 要改成底部条**。

#### Beelinguapp —— 「并排双语 + 母语音频」

- **解决的问题**：用平行文本降低理解门槛，同时用母语朗读建立语音—文字映射。
- **值得抄**：两种语言**逐句对齐**，音频按句高亮；对齐单位是「句」不是「段」，滚动时不会错位。
- **慎抄**：真正的左右并排在手机上不可行：393px 减去 32px 边距后两栏各约 180px，按 16px 字号每行仅 11–12 个字符，德语复合词必然断行 `[T]`。手机端必须退化为「上下堆叠 + 当前句同步」，这也是它自己的实际做法。
- **移动端**：可用（堆叠模式）；**并排模式在移动端不可用**。

#### Duolingo —— 「展示字体与正文字体分工」

- **解决的问题**：让品牌人格与长文可读性同时成立。
- **值得抄（官方数字）** `[官方]`：标题字 Feather Bold 行高 **100–110%**、字距 **-20**、**不得小于 30px**、标题不超过 10 个词；正文 DIN Next Rounded 行高 **140%**、字距 **0**、**不得小于 14px**；无品牌字体时用 Nunito 替代。这套「展示字体只做短标题、正文字体保 140% 行高」的分工可以直接映射到我们的 `--serif-display` / `--serif-body`。
- **慎抄**：圆润字体 + 高饱和绿 + 角色插画是「游戏化人格」，放进歌德/德福备考会削弱可信度；它的动效与庆祝反馈密度也不适合长文阅读。
- **移动端**：优秀（大字、大按钮、单手可达），但那是「练习流」而非「阅读流」的移动端，不可整体照搬。

#### Language Reactor —— 「双语字幕 + 模糊降噪」

- **解决的问题**：看视频时同时看到母语与目标语字幕，并可按词查义。
- **值得抄**：字幕分「主/辅」两层，辅层可整体**模糊**，需要时再聚焦；这比「一直显示两行」更少干扰，可借到阅读器的「译文默认淡出、悬停/点按显形」。
- **慎抄**：双层字幕 + 逐词悬浮是视频时间轴产物；搬到静态文本会变成「每句两个版本」的视觉噪音。
- **移动端**：**不可用**——Chrome/Edge 桌面扩展，无手机版；这提醒我们：桌面才成立的交互不要作为主链路。

**本组判断**：值得抄的是「字号/行距独立可调」「句级对齐」「展示/正文分工」；慎抄的是「颜色承载语义」「并排双语」「双层字幕」；移动端明确不可用的是「真并排」与「扩展型双语层」。

### 8.2 写作与知识管理类

#### iA Writer —— 「克制的编辑体」

- **解决的问题**：让写作界面消失，只留下文本。
- **值得抄**：字体家族按用途拆成 Quattro（正文）/ Duo（等宽对照）/ Mono（代码），并提供 Focus Mode 淡化非当前段落；这是一种「用排版而不是用边框」做层级的方法。
- **慎抄**：极简到隐藏控件，新用户找不到字号/主题入口；我们的读者需要「字号、行距、译文」常在可见处，不能学到「全部收进菜单」。
- **移动端**：可用，但 Focus Mode 在小屏上收益有限，且隐藏式控件在触摸端更难发现。

#### 私有笔记库 —— 「CSS 变量即主题 API」

- **解决的问题**：让用户与主题作者在不改源码的情况下重绘整个应用。
- **值得抄（官方数字）** `[官方]`：编辑区 `--font-text-size: 16px`；正文 `--line-height-normal: 1.5`，紧凑处 `1.3`；UI 字号固定为 `12 / 13 / 15 / 20px`。这套「正文 16px + 1.5 行高 + UI 12–15px」的分离，正是我们 `--reader-fs: 1.125rem`（18px）与全局 16px 可以对齐的参照。
- **慎抄**：主题生态靠社区 CSS 覆盖，对比度与焦点态无人统一；我们若开放太多变量，会重演「每套主题一套对比度」的问题。
- **移动端**：可用；但插件面板在手机上经常溢出，说明「桌面密度直接缩放」不可行。

#### Notion —— 「默认/小字号 + 全宽」

- **解决的问题**：同一份文档兼顾「阅读」与「数据库/看板」。
- **值得抄（官方）** `[官方]`：只给「默认 / 小字号」两档，加一个「全宽」开关，不做 5 档字号——减少选择成本。
- **慎抄**：全宽在 1440px 下会让正文行宽超过 120 字符，长文阅读明显疲劳；我们的阅读器 `--reader-content-width: min(760px, …)` 已经在做限宽，不能为了「看起来更满」取消。
- **移动端**：可用，但块级手柄、悬浮菜单占掉大量纵向空间，阅读时 chrome 过重。

#### Ulysses —— 「行标记与固定滚动」

- **解决的问题**：长文写作时保持「当前行」在视线内。
- **值得抄（官方）** `[官方]`：提供「行标记（当前行浅灰底）」与「固定滚动（当前行锁定在屏幕上/中/下）」两个独立开关，而不是一个笼统的「打字机模式」。
- **慎抄**：固定滚动会锁死阅读位置，复习/回看场景反而碍事；我们只在写作视图考虑，不进入阅读器。
- **移动端**：iPad/iPhone 可用，但行标记 + 固定滚动在小屏上压缩可视行数。

**本组判断**：值得抄的是「正文 16px/1.5、UI 12–15px 的分离」「两档字号 + 限宽」「行标记」；慎抄的是「隐藏控件」「全宽正文」「固定滚动」；移动端不可用的是「桌面密度直接缩放」。

### 8.3 大厂官方设计系统

#### Material Design 3

- **解决的问题**：跨设备、跨品牌的语义化颜色与排版系统。
- **值得抄** `[官方]`：
  - 字号：15 个基础样式 + 15 个强调样式；以 **Major Second（1.125）**、基准 **14px** 构建；`displayLarge 57/64`、`displayMedium 45/52`、`displaySmall 36/44`、`headlineLarge 32/40`；`bodyLarge 16/24`、`labelSmall 11/16`。
  - 动效：标准 **300ms**、强调 **500ms**、进场减速 **400ms**、退场加速 **200ms**；桌面端建议 **150–200ms**。
  - 暗色：不用纯黑，基准 surface 为 `#121212`（M2）/ `#1C1B1F`（M3 baseline）；用 surface container 的 5 级强调替代阴影堆叠。
- **慎抄**：15×2 个样式对 9 个视图是过剩；M3 Expressive 的弹性动效 350–500ms 适合展示型界面，放在精读工具里会「慢半拍」。
- **移动端**：原生优秀；Web 端要自己实现重排与语言行高（官方特别提醒中日韩行高需 +7%），不能只拷 token 表。

#### Apple Human Interface Guidelines

- **解决的问题**：系统级可读性、动态字体与无障碍基线。
- **值得抄** `[官方]`：iOS 正文 **17pt**、Large Title **34pt**、最小可用 **11pt**；Dynamic Type 允许用户整体放大；对比度**不低于 4.5:1**，自定义前景/背景在小字上**争取 7:1**；暗色模式用语义色自动映射，并提供「增强对比度」「减弱动态效果」开关。
- **慎抄**：pt/sp 与 Web px 不是一一对应；Dynamic Type 的「整页重排」对固定高度组件是灾难，我们若引入必须同时改掉固定高度。
- **移动端**：这是移动端基线本身；但它的「系统字体 + 语义色」依赖平台，Web 只能借原则不能借实现。

#### Fluent 2（Microsoft）

- **解决的问题**：桌面生产力软件的高密度排版与跨平台字体。
- **值得抄** `[官方]`：Web 字阶 `caption2 10/14`、`caption1 12/16`、`body1 14/20`、`subtitle2 16/22`、`subtitle1 20/26`、`title3 24/32`、`title2 28/36`、`title1 32/40`、`largeTitle 40/52`、`display 68/92`；正文对比度 **≥4.5:1**，大字（>18.5px 粗体或 >24px 常规）**≥3:1**；以 4px 为网格。
- **慎抄**：`caption2 10px` 低于我们任何可读辅助字的底线；Fluent 的「企业工具感」来自高密度与中性灰，不适合纸面阅读。
- **移动端**：可用（iOS/Android 各有独立字阶），但那是「工具」而非「阅读」的移动端。

#### Carbon（IBM）

- **解决的问题**：复杂企业产品在「生产密度」与「表达性排版」之间的切换。
- **值得抄** `[官方]`：两套字阶——productive 基准 **14px**、expressive 基准 **16px**；间距刻度 `2 / 4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 / 64 / 80 / 96 / 160px`，服从 2x Grid。
- **慎抄**：productive 的 14px 基准对德语长文偏小；我们的阅读器已用 18px，不应为了「统一 14px」降回去。间距刻度可以借，字阶不要整套借。
- **移动端**：可用，但企业表格/表单的密度在手机上需要重排，不能直接套。

#### Primer（GitHub）

- **解决的问题**：高信息密度、长文文档、开发者审美。
- **值得抄** `[官方]`：字号用 rem 以支持浏览器缩放；行高用无单位值并对齐 4px 网格；**行宽建议 ≤80 字符**；强调优先用字重/层级，**不把颜色当主要强调手段**；字体栈走系统字体以保证性能。
- **慎抄**：开发者灰阶 + 代码块审美放在语言学习产品里会显得冷；其「≤80 字符」在 18px 德语下约等于 **680–720px** 容器，比我们现在的 760px 更紧。
- **移动端**：可用，但代码/表格场景与我们的阅读场景不同。

### 8.4 横切结论：哪些能直接变成规则

| 结论 | 来源 | 落成什么 |
| --- | --- | --- |
| 正文 ≥16px、行高 1.5–1.7；辅助字 ≥12px，不用 10px | 私有笔记库、Apple、Fluent、Carbon | `--fs-body` 16px、`--lh-body` 1.6；辅助字号下限 12px |
| 行宽 ≤80 字符（德语 18px ≈ 680–720px） | Primer、通行排版经验 | 阅读器限宽从 760px 收到约 700px（P2 验证） |
| 展示字体与正文字体分工，展示字不小于 30px | Duolingo | `--serif-display` 只用于标题；正文用 `--serif-body` |
| 间距用 4px/8px 刻度 | Carbon、Fluent | 新增 `--space-1..8`（4/8/12/16/24/32/40/48） |
| 语义不只靠颜色 | Polaris、Apple | CEFR 五色必须加下沿/形状第二编码 |
| 暗色不用纯黑，语义色映射，正文 4.5:1、小字争取 7:1 | M3、Apple | 若做暗色，先建 `--surface-*` 语义层 |
| 动效 150–300ms 为主，退场快于进场 | M3、M1 | 现有 100/180/360ms 已在区间内，不新增 500ms 常驻 |
| 主题靠 CSS 变量，但变量要收敛 | 私有笔记库 | 只开放语义 token，不开放组件内部变量 |

### 8.5 收束：回到我们自己的三件事

#### ① 只换材质，还是连形态密度一起换？

**建议：材质先行，形态只动三个高价值点，不做布局重排。**

- **换材质**：纸色/墨色/强调色、阴影、圆角、字体分工、间距刻度。理由：这些是 token 能覆盖的 61.7%，且不改信息架构。
- **只动三个密度点**：
  1. 阅读器行宽 `760px → 约 700px`（对应 ≤80 字符），并把行高显式化为 1.6；
  2. 抽屉/设置的第一层间距统一到 4/8/12/16/24 刻度，减少「18px、22px」这类散值；
  3. 触摸目标统一 ≥44px（Apple/Fluent 基线），现有 `.companion` 与 `.nav` 已有 44px 约束，扩展到按钮族。
- **不动**：视图布局、信息架构、卡片网格列数、工作台分栏。理由：这些没有视觉回归测试兜底，属于路线 C。

#### ② 暗色要不要进这一轮？

**建议：不进本轮，但本轮把 token 改成「语义层 + 值层」两层，给暗色留插槽。**

- 依据：我们当前 `prefers-color-scheme` 与 `data-theme` 均为 0，等于零基础；M3/Apple 都要求暗色单独做对比度（4.5:1，小字争取 7:1）且不用纯黑，工作量约等于再做一次 P1–P2。
- 折中：本轮只交付 light；把 `--paper/--ink/--coral` 映射到 `--surface/--text/--accent` 语义别名，下一轮加 `[data-theme="dark"]` 时只换值不改组件。
- 若产品强烈需要夜间阅读，可先做「阅读器局部暗色」实验（只覆盖 `.reader` 容器），但必须单独做对比度与截图验收，不混进全站换皮。

#### ③ P0 视觉回归基建怎么建？

**建议：先建「截图矩阵 + 关键控件 computed-style + 三条闸」，不追求像素级全站快照。**

- **截图矩阵**：12 个面（9 视图 + 工作台 + 抽屉 + 伴读）× 3 个宽度（1440 / 1024 / 393）= **36 张/轮**；首轮只拍 default 态，稳定后再加 focus-visible 与 reduced-motion 两态（×3 = 108 张）。
- **computed-style 快照**：12 个关键控件（主按钮、次按钮、输入、卡片、导航项、抽屉项、播放器、词元、CEFR 标记、便签、Toast、伴读）各取 20 个属性（font-size/line-height/color/background/border/radius/shadow/padding/margin/transition-duration 等），存 JSON 做 diff。
- **三条闸**：
  1. **字面量预算**：规则体 hex 数不得超过基线 **582**，rgba 不得超过 **118**；新增必须走 token。
  2. **对比度**：对 `tokens.css` 与 `style.css :root` 的成对颜色跑 4.5:1 / 3:1（大字）检查，失败即红。
  3. **动效**：`infinite` 必须仍为 **7**；`prefers-reduced-motion` 下位置/透明度变化必须等于终态。
- **落地形态**：先做本地脚本（`tools/` 下，不接 CI），跑一轮约 3–6 分钟；等矩阵稳定后再接 CI，避免早期截图噪声把流水线拖红。
- **基线存放**：截图与 JSON 放 `_artifacts/visual-baseline/<commit>/`，不入库；只把「期望值/manifest」入库，防止仓库膨胀。

> 本章的判断可以一句话收束：**换材质是低风险高收益，换形态密度只做阅读相关的三个点，暗色延后，先把「怎么证明没坏」建起来再动第二刀。**

---

## 9. 结构拆分与解耦评估（CSS / JS）

> 本节只读评估，不改代码。结论按三档给：**能做**（现在就可以动）｜**有条件能做**（前置条件明确）｜**现在别做**（触发条件写清）。

### 9.1 现状约束（先钉死不可假设的部分）

- `static/index.html` 只加载 `/style.css`（[head.html:17](../../static/layout/head.html#L17)）；工作台 iframe 独立加载 `fonts.css + tokens.css + workbench.css`（[workbench.html:12-14](../../static/german/workbench.html#L12-L14)）。**不能假设可以随便改成多 `<link>`**。
- 多个测试直接读 `static/style.css` 并断言选择器/声明存在（如 [test_exam_domain.py:142-157](../../tests/test_exam_domain.py#L142-L157)、[test_audit_hardening.py:385-386](../../tests/test_audit_hardening.py#L385-L386)）。**拆分后必须仍产出这个路径的文件**，否则门禁全红。
- `index.html` 已经是「片段 + `build_index_html.py` + `check_index_html_sync.py`」模式；CSS 拆分可以复用同一套「源文件 + 构建 + 同步闸」先例，不需要发明新流程。
- JS 已经是 ES Module：`main.js` 是唯一入口 `<script type="module">`，其余 45 个文件靠 `import` 组装；且已有 [check_frontend_layers.py](../../tools/check_frontend_layers.py) 强制分层、import 白名单、反「假解耦」规则。

### 9.2 CSS 拆分的三条路

| 方案 | 做法 | 代价 | 渐进性 | 出问题怎么退 | 判断 |
| --- | --- | --- | --- | --- | --- |
| **A. 构建期拼接 + `@layer` 定序** | 源码切成 `src/css/*.css`，`build_css.py` 按 manifest 顺序拼接并生成 `static/style.css`；构建器在每段外包 `@layer` | 新增构建脚本与同步闸；生成物必须入库；改样式要改源文件 | 最好：先做「零差异拆分」，再加 layer，再逐段迁移 | 生成物一直提交在仓里，`git revert` 即回滚；构建坏了也能手工改生成物救急 | **能做**（分两阶段，先不加 layer） |
| **B. 单文件内用 `@layer` 分层** | 不拆文件，把现有 13,492 行整体包进 `@layer legacy {}`，新代码进后续 layer | 文件仍是 13.5k 行；一次包裹等于全站级联重排；一个括号错误整层失效 | 差：只能一次性切换，无法按组件渐进 | 需要整段回退，且没有中间态 | **有条件能做**（必须先有 P0 基线） |
| **C. 按页面/组件切文件，多 `<link>` 交付** | `reader.css`、`cards.css`… 各自 `<link>` | 违反当前「只加载 style.css」；请求数、缓存键、Android 重扫都变复杂；跨文件顺序隐式 | 中：可以一个个加，但顺序错了很难查 | 删 `<link>` 即可，但级联顺序已变 | **现在别做**（交付形态不改；只拆源码、仍合并成单文件） |

**`@layer` 的两个硬坑（决定 A/B 能不能成）**：

1. **未分层的普通声明优先级最高**。只要还有一条规则在 layer 外，它就会压过所有 layer 内的新规则。所以要么全站都进 layer，要么新代码别指望 layer 帮它赢。
2. **`!important` 的层序是反的**：普通声明「后面的 layer 赢」，`!important` 变成「前面的 layer 赢」，且层内 `!important` 优先于层外 `!important`。现有 **186 处 `!important`** 意味着：把 legacy 包进 `@layer legacy` 后，新规则若想覆盖它们，必须也写 `!important` 且放在**更早**的 layer——这与直觉相反，是换皮时最容易踩的静默回归。

**顺序建议**：`@layer reset, tokens, base, layout, components, overrides;`。先声明顺序再写规则；`@layer` 语句必须出现在所有普通规则之前（`@charset`/`@import` 除外）。

### 9.3 CSS 的现实拆法（可执行）

1. **阶段 1：零差异拆分。** 按现有 section 边界切成 8 段左右（tokens 镜像、base、layout/nav、reader、cards/deck、writer/exam/A1、drawer/player/companion、responsive/overrides），`build_css.py` 按原顺序拼接，**输出与当前 `style.css` 字节级一致**（sha256 相等）。这一步不改任何声明，视觉风险为零，可以在 P0 之前做。
2. **阶段 2：加 layer，但内容不变。** 仍用同一批分片，构建时包 layer；跑 P0 截图矩阵，要求 diff 为 0。任何非零 diff 都说明有未分层规则或 `!important` 反序，修完再进下一步。
3. **阶段 3：按组件族迁移。** 每次只把一段从 `legacy` 挪进 `components`，配套截图；不顺手去重、不顺手删 `!important`。
4. **永远不做**：为了让文件变短而合并 131 个重复选择器、批量删 186 处 `!important`。这些需要「生效声明来源」级别的分析，不是正则能证明的；在没有基线时做，等于盲改级联。

### 9.4 JS 侧：真缝与假缝

**现状量化**：46 个 JS 文件、约 1.05 MB；`core.js` 被 22 个文件导入，`companion.js` 10 个，`player.js` 9 个；`main.js` 出度 19。

**真缝（切了会减少耦合）**：

- `cp-state.js` 是真正的纯状态层：不碰 DOM、不发网络、不用计时器（文件头契约 + 机械闸）。同类还有 `motion.js`、`wr-format.js`、`rd-syntax.js`、`companion-obstacles.js`。把 `writer.js`/`cards.js`/`companion.js` 里的纯计算继续往这些 L1/L2 模块搬，是低风险、可测试的。
- `CompanionDrawer` 有**两个写者**：`main.js` 在 window 上拼了一个 facade，`cp-drawer.js` 又 `Object.assign(window.CompanionDrawer || {}, CompanionDrawer)` 合并进去（[cp-drawer.js:1473](../../static/js/cp-drawer.js#L1473)）。这是真实的顺序依赖，应改成「cp-drawer 导出唯一对象，main 只导入并挂一次」。
- 自定义事件很少，只有 `companion:settle-end`（有生产/消费）与 `companion:statechange`（**没有监听者，是死事件**）。事件总线不是问题，**不要为了“解耦”再造一个**。

**假缝（切了只多一层转发）**：

- 把 `main.js` 结尾的 `Object.assign(window, { ... })` 搬到新文件 `window-bridge.js`——193 个名字只是换了个地方挂，耦合没变。
- 按文件大小把 `cp-drawer.js`（1,475 行）再切成 `cp-drawer-render.js` / `cp-drawer-events.js`，但两边仍共享 `#drawer`、`#companion-input`、`#d-tab-companion` 等 DOM id——只是把「一个文件里的隐式契约」变成「两个文件之间的隐式契约」。
- 把 `companion.js` 的 DOM 读写和状态更新分开，但状态仍从 `window.state` 取——分层是假的。

**真正的耦合量级**：

| 耦合点 | 规模 | 说明 |
| --- | ---: | --- |
| `Object.assign(window, {...})` | **193 个名字** | [main.js:1197](../../static/js/main.js#L1197) 起，导航/卡片/写作/播放器/伴读全在这一个出口 |
| 静态 HTML 内联事件 | **526 处 / 102 个不同入口** | 前三名 `show` 42、`ShadowPlayer` 34、`setExamModule` 14 |
| 跨文件共享 DOM id | 至少 8 组 | `#drawer`（3 文件）、`#companion`、`#ide-editor`、`#companion-input`、`#drawer-companion-section`、`#d-tab-companion`、`#view-progress`、`#a1-*-container` |
| 指向不存在的全局 | 6 处 | `window.showUndoToast` 被 `if` 守卫 6 次，全仓没有定义 → 静默空操作 |

**结论**：JS 的模块化不是「要不要做」，而是「已经做了一半」。下一步不是继续切文件，而是**缩窗口桥**：把 526 处内联事件按视图迁到 `data-action` + 每视图一个委托监听，再按批次删 `window` 名字。先做前三名（`show`、`ShadowPlayer`、`setExamModule`，合计 90 处），风险最低、收益最大。

### 9.5 没有视觉基线时拆结构，风险有多大？

| 动作 | 无基线风险 | 理由 |
| --- | --- | --- |
| 零差异 CSS 拆分（字节一致） | **接近零** | 输出不变，可用 sha256 证明；风险只剩「有人手改生成物」 |
| 单文件包 `@layer` / 调整顺序 | **高** | 186 处 `!important` 与未分层规则会静默换序；没有截图看不出来 |
| 合并重复选择器 / 删 `!important` | **很高** | 131 个重复选择器就是 131 处顺序依赖，删哪条要看生效声明来源 |
| 纯逻辑 JS 迁移（L1/L2，无 DOM） | **低** | 有分层闸 + pytest 覆盖；输出可单测 |
| DOM 归属重切（抽屉/伴读） | **中高** | 跨文件共享 id，行为回归只能靠点击与截图 |

**先后顺序**：

1. **先做零差异拆分**（可先于 P0；用 sha256 闸兜底）；
2. **再做 P0 视觉基线**；
3. **然后才允许 `@layer` / 顺序调整 / 组件迁移**；
4. JS 侧纯逻辑迁移可与 P0 并行；DOM 重切必须等 P0。

### 9.6 判断与触发条件

- **能做（现在）**：CSS 零差异拆分 + `build_css.py` + `check_css_sync.py`；JS 纯逻辑继续迁入 L1/L2；`CompanionDrawer` 单写者化；删除死事件与 `showUndoToast` 死守卫。
- **有条件能做**：`@layer` 定序（前置：P0 截图矩阵 + 36 张 diff 为 0）；组件族迁移（前置：该族有 3 个断点截图）；内联事件迁移（前置：该视图有截图覆盖 + 点击路径测试）。
- **现在别做**：多 `<link>` 交付、批量去重、批量删 `!important`、按文件大小切 JS、新建事件总线。
- **「现在别做」的触发条件**（满足任一再启动）：
  1. `style.css` 单周出现 ≥2 次合并冲突，或一次换皮 PR 在同一区段改动 >500 行；
  2. P0 矩阵已稳定跑通 2 轮，且目标组件在 1440/1024/393 三档均有基线；
  3. 出现明确的组件所有权需求（两人同时改同一文件的不同组件）。

### 9.7 下一步具体动作

1. 新增 `tools/build_css.py` 与 `tools/check_css_sync.py`，先放**单个源文件**跑通「源 → `static/style.css` → sha256 相等」，不拆内容。
2. 按 8 个 section 边界拆到 `src/css/`，构建输出仍写 `static/style.css`；跑全量 pytest（它们读生成物）与 6 个静态门禁。
3. 起 P0 截图 / computed-style 基线（与 §8.5③ 同一套），之后才加 `@layer`。
4. JS 按批次缩桥：`show` → `ShadowPlayer` → `setExamModule` → `switchDrawerTab`/`setA1Mode`；每批只改一个视图，配一次点击回归。
5. 修两个已确认的耦合缺陷：`CompanionDrawer` 双写者、`showUndoToast` 死守卫（或改用已有 `notify()`）。

> 一句话：**结构拆分可以先于视觉基线，但只能做「输出字节不变」的那一半；任何会改变级联结果的动作，都必须排在 P0 之后。**

---

## 10. 参考来源

- [Material 3 – Type scale & tokens](https://m3.material.io/styles/typography/type-scale-tokens)（2026-11-08 读取）
- [Material 3 – Easing and duration](https://m3.material.io/styles/motion/easing-and-duration)；[Motion specs](https://m3.material.io/styles/motion/overview/specs)
- [Material 2 – Dark theme](https://m2.material.io/design/color/dark-theme.html)；[M3 – Color roles](https://m3.material.io/styles/color/roles)
- [Android Developers – Material 3 in Compose（字号表）](https://developer.android.google.cn/develop/ui/compose/designsystems/material3?hl=zh-cn)
- [Apple HIG – Typography](https://developer.apple.com/design/human-interface-guidelines/typography)；[Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- [Fluent 2 – Typography](https://fluent2.microsoft.design/typography)
- [Carbon – Type sets](https://carbondesignsystem.com/elements/typography/type-sets/)；[Spacing](https://carbondesignsystem.com/elements/spacing/overview/)
- [Primer – Typography](https://primer.style/foundations/typography)
- [Polaris – Typography](https://polaris-react.shopify.com/design/typography)；[Typography tokens](https://polaris-react.shopify.com/design/typography/typography-tokens)
- [Duolingo Brand Guidelines – Typography](https://design.duolingo.com/identity/typography)
- [私有笔记库 – Typography CSS variables](https://docs.私有笔记库.md/Reference/CSS+variables/Foundations/Typography)
- [Notion Help – Customize and style your content](https://www.notion.com/en-gb/help/customize-and-style-your-content)
- [Ulysses – Customize the Editor](https://help.ulysses.app/dive-into-editing/editor-customization-guide)
- [LingQ Settings Guide（第三方）](https://lingtuitive.com/blog/ultimate-lingq-settings)
- [Readlang 官网](https://readlang.com/)；[Beelinguapp 官网](https://beelinguapp.com/link/download)
- [Language Reactor 平台限制（第三方）](https://refold.la/learning-libraries?item=84002-language-reactor&type=tool)
