# docs/research/ 专项技术调研索引

> 本目录是 **DeLector 项目的可复用技术调研与设计探索资产库**。
> 区别于 `docs/reviews/` 的一次性审计与评测报告，本目录沉淀的是**长期有效、可跨模块与后续版本复用的工程经验、外部基准对标与设计实测数据**。

---

## 目录分层与速查总览

| 调研领域 | 核心议题与沉淀资产 | 覆盖文件 |
|---|---|---|
| **一、前端排版与去字形工程** | 消除字形歧义、建立克制排版阶梯、实测主流 App 间距比与字阶 | `*-emoji-*.md` · `*-reference-library.md` |
| **二、交互动效与伴读生机** | 动效分层、7 处无限循环白名单、桌宠生机状态机与避让机制 | `*-motion-*.md` · `*-companion-bubble-*.md` · `*-master-slash-*.md` |
| **三、界面重构与布局探索** | 移动端 393px 触控断点适配、设置页 IA 分段、备考单列目录 | `*-exam-*.md` · `*-player-tray-*.md` · `*-settings-ia-*.md` · `*-writer-mobile-*.md` |
| **四、视觉换皮与设计系统** | 全仓 CSS 现状量化、横向对标 M3/HIG/Fluent2、复习状态设计 | `*-full-site-visual-reskin-research.md` · `*-wordcard-review-state-research.md` |
| **五、随附研究原型与代码模板** | 不接入构建链的独立静态对比原型、动效辅助函数脚手架 | `*.html` · `*.css` · `*.js` |
| **六、启动性能与本地服务架构** | 冷启动指标口径、WebView 预热、sidecar 就绪握手、Web 首屏指标在本地 HTTP 场景的可迁移性 | `*-first-screen-startup-*.md` |

---

## 一、 前端排版与去字形工程（Typography & De-Emoji）

- [2026-11-06 前端去 Emoji 与 AI 语调调研](2026-11-06-emoji-and-ai-tone-frontend-research.md)
  - **核心价值**：扫描全站 551 处 Emoji，诊断 AI 辅助工具的语调疲劳度与屏幕阅读器（AT）误读机制；确立「字形不得是意义唯一载体」硬准则，催生 [ADR-0029](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)。
- [2026-11-06 去 Emoji 第二轮外部证据与映射表](2026-11-06-emoji-round2-external-evidence-and-mapping.md)
  - **核心价值**：梳理 WCAG 2.1 与 AT 实际朗读证据，建立 50+ 个核心控件从字形向语义文字、ARIA 标签和 Lucide 线性图标的精确替换映射表。
- [2026-11-06 外部 UI 设计实测参考库](2026-11-06-external-ui-design-reference-library.md)
  - **核心价值**：对标 Raycast、Linear、Obsidian、Duolingo 等 14 款顶级产品的实测数值。量化提炼：
    - 间距比：功能面 1.0–1.5，阅读面 2.5–3.0，落地页 4.0；
    - 字阶比：正文至标题 2.0–3.0；
    - 微动效区间：80–160ms，避免多余 300ms+ 拖沓。

---

## 二、 交互动效与伴读生机（Motion & Companion Vitality）

- [2026-11-07 伴读桌宠：气泡自适配、遮挡冲突、生机状态机与自由移动调研](2026-11-07-companion-bubble-and-vitality-research.md)
  - **核心价值**：针对悬浮宠物的注意力争夺与遮挡，设计 5 级状态机（idle → acting → waiting → sleeping → error）与动态滑动避让算法（P2/P3/P4 前置）。
- [2026-11-07 动效与生动力调研 (加法批次)](2026-11-07-motion-vitality-research.md)
  - **核心价值**：确立动效分层标准，盘点全站收敛出**唯一 7 处允许无限循环的白名单**（打字游标、伴读呼吸等）；制定全局 `prefers-reduced-motion` 零残留降级规范（催生 [ADR-0030](../adr/2026-11-07-adr-0030-frontend-motion-system.md)）。
- [2026-11-07 卡盒「斩」中档触控反馈调研](2026-11-07-master-slash-feedback-research.md)
  - **核心价值**：调研背词熟练度操作的心流，设计「100ms 按压 + 180ms 朱印印章 + 520ms 等宽滚动计数」中档反馈链路，拒绝过度打断式弹窗。

---

## 三、 界面重构与布局探索（Layout Redesign & Mobile Breakpoints）

- [2026-11-07 备考页单列目录与排版改造调研](2026-11-07-exam-layout-redesign-research.md)
  - **核心价值**：废除多列卡片网格，重构为 820px 单列目录、2px 珊瑚底线与等宽元数据计数；实测窄屏 393px/360px 压缩页头至 190px 保证首屏全显。
- [2026-11-07 播放器托盘与移动端断点字形调研](2026-11-07-player-tray-redesign-research.md)
  - **核心价值**：排查 ≤768px 断点下朗读音色按钮因 `font-size: 0` 导致文字坍缩的 bug；沉淀字形审查「三问口径」（断点问、状态问、可达问）。
- [2026-11-07 设置页 IA 分段控件与思考强度调研](2026-11-07-settings-ia-and-reasoning-control-research.md)
  - **核心价值**：将传统的生硬下拉菜单重塑为 iOS 风格三档分段控件（关闭/标准/深读），打通 UI 档位与大模型后端 `reasoning_effort` 映射。
- [2026-11-07 移动端写作台布局与 Agent 槽位调研](2026-11-07-writer-mobile-layout-research.md)
  - **核心价值**：解决 393px 移动视口下工具栏按钮 44px 点击区域重叠问题（行距 6→8px）；为智能体操作条（润色、语法、选区）预留无冲突的弹性槽位。

---

## 四、 视觉换皮与设计系统（Visual Reskin & Design System）

- [2026-11-08 全站视觉换皮调研与结构解耦评估](2026-11-08-full-site-visual-reskin-research.md)
  - **核心价值**：全面量化全站 CSS 现状（字面量 33.4%、无暗色基础），深度对标 M3 / HIG / Fluent 2；规划 P0 视觉回归基建、P1 纯 Token 治理、P2 组件族换肤路线。
- [2026-11-08 词卡抽屉「复习状态」UI 立项调研](2026-11-08-wordcard-review-state-research.md)
  - **核心价值**：横向对标 Anki / Mochi / Duolingo 等 10 个产品，提出方案 B 单行等宽复习台账方案（读侧 SQL 单条逆运算去重，不改写端、不加状态）。

---

## 五、 随附研究原型与代码模板（Prototypes & Assets）

- [2026-11-06 去 Emoji vs 排版层级对比原型](2026-11-06-emoji-vs-typography-prototype.html)
  - 独立静态 HTML 页面，并排展示「原版彩色 Emoji」、「纯删 Emoji」与「克制编辑排版」效果。
- `2026-11-07-motion-templates.css` / `2026-11-07-motion-templates.js`
  - 原型期验证通过的动效 CSS 类（fade-up / enter / stagger）与 JavaScript 错峰控制辅助函数。

---

## 六、 启动性能与本地服务架构（Startup Performance & Local-Service Architecture）

- [2026-11-09 首屏启动业界实践调研](2026-11-09-first-screen-startup-industry-research.md)
  - **核心价值**：按「Android 原生 → 混合外壳 → Web 首屏 → 可迁移性」四层核对一手来源（Android 启动指标 / Splash / `startUpWebView`、Electron / Tauri / VS Code、NN/g、web-vitals / Lighthouse / MDN）。给出 4.0s 端到端的分段归因：**2.3s 是「壳等 Python sidecar」，不是 Web 首屏**；可并行余量仅约 0.55s 轮询对齐 + WebView 预热，1.2s 重依赖 import 是进程内结构性成本。结论：业界顺序是「先削串行，再诚实遮盖」，本项目缺口集中在 TTFD 口径缺失、splash 撤场看定时器而非首帧、`androidx.webkit` 1.10.0 缺 `startUpWebView`。未核实项见文末 §7（含 web.dev 原文抓取失败、预热收益无官方数字、实测未复跑）。
- [2026-11-09 AndroidX WebView 异步启动（`startUpWebView`）可行性调研](2026-11-09-androidx-webview-startup-research.md)
  - **核心价值**：下载 `webkit-1.16.0.aar` 读元数据实证 **`minCompileSdk=33` / `minAGP=7.2.0` / `minSdk=24`**，推翻「必须升 compileSdk 36 + AGP 8.9 + Gradle 8.11」的假设——本项目（34 / 8.4.2 / 8.6 / 24）已满足，升级只需一行依赖。同时给出 AGP↔API 36 的官方门槛、Chaquopy 15.0.1 仅支持 AGP ≤8.5（若要升 AGP 必须换 16.1）的官方版本表，以及 `startUpWebView` 的调用时机、`shouldRunUiThreadStartUpTasks(false)` 分片、失败降级与审计 API；未证实项单独列清单。
- [2026-11-09 `startUpWebView` 预初始化 Chromium 的负结果存档](2026-11-09-android-webview-prestartup-negative-result.md)
  - **核心价值**：把「并行 WebView 初始化抵消 #320 的 +738ms」这一假设实测证伪。两轮各 7 次 TTFD（x86_64 模拟器）：基线 4095 / 3938ms，`startUpWebView` 版 4067 / 4005ms，通过线 3966ms 未达、放弃线 4166ms 未破——付出 APK +0.08%、dex 方法数 +1,292（+2.18%）的成本，换来 0 收益。归因：Python 启动与 Chromium 初始化抢同一份 CPU，且 #319 之后 TTFD 下界已不在 WebView 上。附带结论：#320 的 +19% 回退在同一构建下被吸收（≈4005ms vs 4704ms），但「挪创建位置」本身无价值；实现留档于 `archive/negative-webview-prestartup`。
