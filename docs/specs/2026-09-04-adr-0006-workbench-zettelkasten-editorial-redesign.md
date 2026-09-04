---
title: "ADR-0006: 背词工作台实体学术卡片箱 (Zettelkasten) 与心流优先重塑"
created: 2026-09-04
updated: 2026-09-04
type: project
tags:
  - project/delector
  - topic/adr
  - topic/architecture
  - topic/frontend
  - topic/design-system
  - topic/workbench
status: accepted
audience: both
---

# ADR-0006: 背词工作台实体学术卡片箱 (Zettelkasten) 与心流优先重塑

## 1. Context and Problem Statement

在路线 B（ADR-0005 §4.5）实施完成后，背词工作台已成功抽离并引入了 `static/css/tokens.css` 共享 Token，且打通了 CEFR 考纲词库契约与离线降级。

然而在**真实视觉与交互质感**层面，背词工作台依然存在严重的产品体验断层：
1. **视觉骨骼陈旧且割裂**：虽然底色映射到了 `--paper`，但布局骨架仍是早期 2018 年 Bootstrap / 后台管理工具的粗笨形态——高饱和度的纯红纯绿大色块评分按钮、粗重的通栏矩形粘性 Tab 栏、突兀的圆形翻页大箭头以及宋体、微软雅黑与 Georgia 混乱混用的字体栈，与主站 **Academic Modern Editorial & Continuous Exhibition**（学术期刊与实体纸张质感）存在强烈的“粗糙玩具感”。
2. **注意力焦点分散**：背词是典型的高心流认知活动。当前翻转卡片周围充斥着大面积高对比度外围控件（厚重顶栏、高饱和分段器、通栏底色），喧宾夺主，极大加剧了长时间背词的眼部与认知疲劳。
3. **技术守卫的高敏感性**：`workbench.html` 受到 `tools/wb_queue_probe.mjs` 中 13 处代码切片（包含 `pad2`, `buildReviewQueue`, `refilterReviewQueueForScope`, `renormalizeQueueTail` 等）以及 `test_german_workbench.py` 79 项静态契约测试的严密监控。任何视觉重构必须**在零破坏代码切片与状态机的前提下实施**。

---

## 2. Decision Drivers

- **视觉同源与实体隐喻 (MUST)**：工作台必须彻底消除“低幼管理后台”感，重构为具象的实体**学术卡片箱 (Zettelkasten Index Card)**，与 DeLector 主站的温润纸墨期刊风完全同源共生。
- **心流优先与外围克制 (MUST)**：除单词卡片本身外，所有周边控制（导航、分段器、进度条、翻页箭头）必须“退入背景”，最大程度降低视线干扰。
- **高频操作温润化 (MUST)**：重构「不认识 / 模糊 / 认识」评分区，告别粗暴的大面积纯色荧光块，采用雅致的植物矿物墨水印章与等宽快捷键角标。
- **切片护栏与工程隔离红线 (RFC 2119 MUST)**：
  - 严禁破坏 `tools/wb_queue_probe.mjs` 监控的 13 处 JS 切片；
  - 维持 `workbench.html` 独立单文件与 iframe 物理沙箱隔离；
  - 保证全量 565 项 pytest 与 10/10 动态探针 100% 全绿。

---

## 3. Considered Options & Socratic Decisions

### Q1: 核心卡片隐喻与视觉形态
- **Option A (Accepted ➡️): 实体学术卡片箱 (The Zettelkasten Archive Index Card)**
  - **纸面质感**：纯白卡片 `#ffffff` 叠放于 `#faf8f5` 暖纸画布，配合 1px 装订细线 `--rule` 与精致纸边缘投影 `--shadow-card`。
  - **排版分层**：词头采用 `Playfair Display / Instrument Serif` 衬线标题排印；音标、词性与例句统一规范使用 `Inter / IBM Plex Mono`，层级分明。
  - **印章式评分座**：重塑为柔和暖白底 + 矿物墨色微边框（苔藓绿 `--moss`、芥末黄 `--mustard`、深樱桃红 `--cherry`），辅以 `[1] [2] [3]` 键盘操作角标，温润耐看。
  - **翻页控制弱化**：箭头弱化为与卡片边缘呼应的轻质悬浮微交互，不再突兀。
- Option B: 现代生产力流线风格 (Linear / Raycast Dark Minimalism)
  - 采用极简冷灰冷黑高对比度发光块。违背了 DeLector 的人文德语学术内核，予以否决。

### Q2: 视线聚焦与外围控件节制
- **Option A (Accepted ➡️): 心流优先架构 (Focus-First / Quiet Navigation)**
  - **轻量出版物导航**：废弃粗大的实色 Tab 胶囊，改为优雅的底边细线划动导航（Subtle Underline Tabs），激活项以陶土赤红细线与深炭墨水标定。
  - **顶栏紧凑化**：分段器与徽标精细化，降低高度，突出标题层级。
  - **极简进度刻度**：进度条收缩为 3px 极细刻度线，安静反馈进度。
- Option B: 全功能展台面板 (Dense Multi-Tool Studio)
  - 维持原有大块面积，仅替换文字颜色。无法解决视觉粗笨的核心痛点，予以否决。

---

## 4. Decision Outcome & Implementation Architecture

### 4.1 视觉层演进规范
1. **全局字体彻底统一**：
   - 移除 `body` 上的 `"Microsoft YaHei"` 硬编码，改用 `var(--sans)`。
   - 移除各处的 `Georgia` 硬编码，统一使用 `var(--serif)`。
   - 移除各处的 `Consolas` 硬编码，统一使用 `var(--mono)`。
2. **卡片结构与质感升级**：
   - 卡片增加内边距与留白呼吸感，去除生硬阴影，引入实体纸张边线与微投影。
   - 词头 `.hw` 增加 letter-spacing 与字重调优。
   - 例句区德语与中文释义对齐期刊印刷排版。
3. **评分底座重构**：
   - `.rate-btn` 从粗暴的 `background: var(--good)` 实色，改为高阶轻质墨水风：
     - 背景使用各状态对应的 soft 色相（`var(--good-soft)`, `var(--hard-soft)`, `var(--again-soft)`）；
     - 文字与边框使用饱满的深色 Token（`var(--moss)`, `var(--mustard)`, `var(--cherry)`）；
     - 悬浮时产生轻量级微升动效；
     - 增加清晰的等宽快捷键提示 `[1]`, `[2]`, `[3]`。
4. **导航与分段控件轻量化**：
   - `nav.tabs` 移除厚重大边框与强阴影，采用无边框清爽排列 + 底部活动滑块线。
   - `#scopeSeg` 调整为微小装订夹（Paperclip）风格的小型分段器。

### 4.2 技术守卫不变量 (Engineering Invariants)
- **切片保全**：所有改动严格限于 `<style>` 及纯展示型 DOM 结构（如 class 装饰），绝不改动任何被测函数的签名、参数及内部实现。
- **DOM ID 保全**：`#scopeSeg`, `#tabs`, `#cardFlip`, `#cardHw`, `#cardIpa`, `#cardPos`, `#cardGloss`, `#cardEx`, `#revBoard`, `#revEmpty`, `#dueBadge` 等全部保留，确保 JS 行为与既有 DOM 查询 100% 稳定。

---

## 5. Consequences & Status

- **Status**: **Accepted**
- **Pros**:
  - 背词工作台与 DeLector 主站视觉体验彻底弥合，达到出版物级美学品质；
  - 极大降低背词心流干扰，告别粗糙色块导致的眼部疲劳；
  - 保持 10/10 Node.js 动态探针与 13 项切片护栏 100% 稳固。
- **Cons**:
  - CSS 重构需要细致调整各视口下的内边距与媒体查询适配，确保移动端同样精致。