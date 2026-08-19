# DeLector 设计系统规范 (Design System Specification v3.0)
> **版本**：v3.0 · 2026-08  
> **视觉流派**：Gutenberg Broadsheet + Bauhaus Stationery + Atelier Zero Modern Editorial (德式经典社论、包豪斯手账工作台与现代极简杂志落地页)  
> **核心定位**：专为德语欧标（CEFR A1–C1）长文精读、歌德/德福证书备考与语言知识内化打造的极简高密度学术研读与数据展台工作台。

---

## 目录
1. [设计演进谱系与去 AI 同质化哲学 (Design Evolution & De-AI Philosophy)](#1-设计演进谱系与去-ai-同质化哲学)
2. [Artifact 1–4 设计演进与流派解构 (Cross-Artifact Anatomy)](#2-artifact-14-设计演进与流派解构)
3. [Artifact 4 (Atelier Zero) 现代社论设计范式深度剖析](#3-artifact-4-atelier-zero-现代社论设计范式深度剖析)
4. [视觉 Token 全量体系 (The Complete Design Tokens v3.0)](#4-视觉-token-全量体系)
5. [字体排印阶梯与版式节奏 (Typography Stack & Rhythm)](#5-字体排印阶梯与版式节奏)
6. [DeLector「台账（Folio）」全新重塑方案 (Folio Ledger Transformation)](#6-delector台账folio全新重塑方案)
7. [特色学术与语言学组件蓝图 (Domain-Specific UI Components)](#7-特色学术与语言学组件蓝图)
8. [交互动效、无障碍与移动端触控规范 (Motion, A11y & Touch Guidelines)](#8-交互动效无障碍与移动端触控规范)
9. [反同质化守则与设计防线 (Anti-Cliché Guardrails)](#9-反同质化守则与设计防线)

---

## 1. 设计演进谱系与去 AI 同质化哲学

在 AI 辅助生成界面的当下，多数产品极易陷入“大圆角黑色毛玻璃、泛滥的彩色弥散发光渐变、千篇一律的 Bento 紧凑卡片、无序的悬浮药丸按钮”等模板化陷阱。

DeLector 设计系统历经四个阶段的演进与提炼，确立了以**“真实物理纸张、德式印刷墨线、严谨数据台账与社论杂志排版节奏”**为核心的高级审美体系。

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DELECTOR 视觉演进与流派谱系                                     │
├───────────────────┬───────────────────┬───────────────────────┬────────────────────────────────┤
│   Artifact 1.0    │   Artifact 2.0    │     Artifact 3.0      │          Artifact 4.0          │
│   (Level App)     │    (Zentou AI)    │       (Mutuals)       │         (Atelier Zero)         │
├───────────────────┼───────────────────┼───────────────────────┼────────────────────────────────┤
│ 拟物移动设备展台   │ 包豪斯工程方格手账 │ 经典古腾堡社论大报刊   │ 现代极简杂志落地页 / 展台流     │
│ 柔和马卡龙任务卡   │ 和纸胶带、大头针  │ 细黑墨线、单色等宽走字 │ 0.78:1.22 不对称排版、纸张微噪点│
│ 阶段光环、手感卡片 │ 手写字体批注与注疏 │ 双栏固定导轨、数据台账 │ 实体环形指标、双向滚动全球走字带│
└───────────────────┴───────────────────┴───────────────────────┴────────────────────────────────┘
                                                │
                                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                       DeLector v3.0 统一流派：Academic Modern Editorial                       │
│    温润羊皮纸基底 + 1.5px 印刷墨线 + 等宽元数据走字 + 环形指标徽章 + 现代杂志卡片画册展台        │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### v3.0 核心设计原则
1. **真实物理基底（Substantive Paper & Physical Grain）**：
   杜绝生硬纯黑或千篇一律的冷白。使用含有微细纤维/噪点微质感（SVG Fractal Noise Overlay）的温润纸张色（`--paper: #FAF8F5 / #EFE7D2`），让长文阅读如沉浸于欧洲古典图书。
2. **严谨印刷墨线（German Print Linework）**：
   用清晰、笃定的硬质线条（`1.5px solid var(--ink)` 与 `1px solid var(--rule)`）建立视觉网格体系，彻底告别模糊无边界的阴影溢出。
3. **数据走字与元数据对齐（Editorial Ticker & Metadata Density）**：
   将所有状态、统计与环境信息转化为严密的等宽打字机元数据带（`IBM Plex Mono` / `JetBrains Mono`），提供学术级的秩序感。
4. **不对称多栏与空间呼吸（Asymmetric Grids & Breathing Rhythm）**：
   跳出死板的居中对称，通过黄金比例分割（0.78fr : 1.22fr）、超大号衬线标题与精巧段落文字的张力对比，呈现出顶级杂志的版式节奏。

---

## 2. Artifact 1–4 设计演进与流派解构

| 维度 | Artifact 1 (`artifact.html`) | Artifact 2 (`artifact2.html`) | Artifact 3 (`artifact3.html`) | Artifact 4 (`artifact4.html`) |
| :--- | :--- | :--- | :--- | :--- |
| **主题定位** | Level - 每日习惯养成移动端展台 | Zentou AI - 概念设计手账蓝图 | Mutuals - 关系网络社论台账 | Open Design / Atelier Zero - 现代开源设计落地页 |
| **视觉流派** | 现代移动卡片 + 拟物暗色展台 | 包豪斯工坊 + 纸质手账批注 | 古腾堡报刊 (Gutenberg Broadsheet) | 现代高端社论杂志 (Atelier Editorial) |
| **主纸张基底** | 纯白 `#ffffff` 嵌入暗夜舞台 `#0e0d0c` | 暖米黄方格纸 `#fbf6ec` + 点阵 | 经典牛皮纸色 `#f4ede0` + 面板纯色 | 重磅温润纸色 `#efe7d2` + SVG 噪点层 |
| **墨水与线条** | 浅灰分割线 `#ebe6dd` | 铅笔灰 `#4d473d` + 2px/3px 实线 | 纯黑墨水 `#1f1c14` + 1px 实线 | 德国铸字墨黑 `#15140f` + 0.16 透明度墨线 |
| **强调色彩** | 琥珀橙 `#e98425` + 珊瑚橘 `#ff6b3d` | 朱砂红 `#d8482b` + 高亮黄 `#f9d27c` | 哥德朱砂红 `#c14a2b` + 森林绿 `#406b3a` | 朱砂珊瑚红 `--coral: #ed6f5c` + 芥末黄 `#e9b94a` |
| **字体组合** | Instrument Serif + Inter + IBM Plex Mono | DM Serif Display + Patrick Hand + Mono | DM Serif Display/Text + IBM Plex Mono | Playfair Display + Inter Tight + JetBrains Mono |
| **标志性组件** | 3D 拟真手机框、柔和马卡龙胶囊 | 和纸胶带、打孔夹、手写便签、回形针 | 顶栏 Ticker、左侧边栏导轨、台账明细表 | 双侧边文字轨道、环形指标圆环、双向走字带、倾斜展台 |
| **给 DeLector 的贡献** | 卡片翻折质感、CEFR 马卡龙高亮阶梯 | 词法抽屉便签、语法打字机卡片、手写心得 | 顶栏元数据 Ticker、单色台账结构、词汇列表 | 落地页 Hero 不对称排版、环形数据徽章、现代杂志式台账 |

---

## 3. Artifact 4 (Atelier Zero) 现代社论设计范式深度剖析

`artifact4.html` 是现代社论落地页与交互展台的集大成者。其核心创新点与技术实现可提炼为以下 6 大维度：

### 3.1 Hero 架构与宏观排版张力
1. **0.78fr : 1.22fr 不对称网格**：
   打破传统落地页左文右图居中等分的呆板布局，采用左侧紧凑排版（文案、操作、环形数据）与右侧舒展画册（超高纵深插画、四角校准线）的不对称对撞。
2. **混合排印大标题（Display Headline）**：
   ```html
   <h1 class="display">Designing <em>intelligence</em> with skills, <em>taste,</em> and <em>code</em><span class="dot">.</span></h1>
   ```
   - 基础字形采用 `Inter Tight 800`，超粗几何无衬线展现现代力量感；
   - 核心关键词穿插 `Playfair Display 500 Italic`（斜体衬线），赋予古典社论优雅韵味；
   - 句末点缀朱砂珊瑚红实心圆点（`--coral dot`），形成强烈的视觉定焦。
3. **顶栏极细元数据带与脉冲灯（Top Metadata Strip with Live Pulse）**：
   ```html
   <div class="topbar-inner">
     <span><b>OD / 2026</b> · Vol. 01 / Issue Nº 26</span>
     <span class="mid"><span>Filed under <b class="coral">Design · Intelligence</b></span></span>
     <span class="right"><span class="pulse"></span>Live · v0.3.0</span>
   </div>
   ```
   高度仅 `36px`，全大写等宽字体，通过 `letter-spacing: 0.18em` 形成精密仪器仪表盘式的专业感。

### 3.2 拟物印刷质感与微物理细节
1. **全景纸张纤维噪点层（SVG Fractal Noise Overlay）**：
   ```css
   body::before {
     content: '';
     position: fixed;
     inset: 0;
     pointer-events: none;
     z-index: 1;
     background-image:
       radial-gradient(circle at 12% 18%, rgba(106, 92, 56, 0.07) 0, transparent 28%),
       radial-gradient(circle at 88% 72%, rgba(106, 92, 56, 0.06) 0, transparent 32%),
       url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.18 0 0 0 0 0.16 0 0 0 0 0.12 0 0 0 0.06 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
     mix-blend-mode: multiply;
     opacity: 0.92;
   }
   ```
   这种极轻微的正片叠底噪点让整个屏幕从冰冷的数字发光像素转化为“透气、温润、可触摸”的重磅书籍纸面。
2. **四角定位标尺与图版元数据（Plate Corner Marks & Annotations）**：
   在 Hero 图片与展台卡片四角，使用 `corner tl/tr/bl/br` 绘制 L 形细黑线，并在四角打上打字机元数据：`[FIG. 01 / OD-26]`、`[Plate Nº 08]`、`[SHA · a1b2c3d]`、`[52.5200° N · 13.4050° E]`。
3. **固定双侧边垂直轨道（Fixed Side Rails）**：
   屏幕最左侧与最右侧固定 `36px` 极细垂直边界，通过 `writing-mode: vertical-rl` 放置微型版权与流派定义文字，强化报刊版面的装订边框感。

### 3.3 数据徽章与交互组件体系
1. **环形指标徽章（Ring Stat Badge）**：
   ```html
   <div class="stat">
     <span class="ring solid">31</span>
     <span class="stat-label"><b>skills</b>shippable</span>
   </div>
   <div class="stat">
     <span class="ring dashed coral">12</span>
     <span class="stat-label"><b>CLIs</b>BYO agent</span>
   </div>
   ```
   `34px x 34px` 正圆，支持虚线（`dashed`）、实线（`solid`）与朱红强调态，配合双行上下结构的文本标签，是高密度紧凑数据的最佳表现形式。
2. **双向跑马灯走字带（Wire / Dual Counter-Marquee）**：
   上下双行以相反方向（`52s` 与 `64s`）缓慢匀速滚动的社论简讯，悬浮自动暂停，用 `linear-gradient` 左右边缘做柔和羽化遮罩（`mask-image`）。
3. **物理微倾斜卡片（Tilted Exhibition Cards）**：
   在 Selected Work 展台中，卡片分别设置 `transform: rotate(-1.2deg)` 与 `rotate(2.4deg)`，悬浮时平滑抬升，打破传统 UI 的网格死板感，呈现真实桌面随意散落的书籍画册美感。
4. **超大步进数字流程卡（Method Step Cards）**：
   使用 `78px` 超大号衬线斜体数字（`01`, `02`, `03`）直接压在卡片顶部分割线上，后接带有转折箭头的加粗无衬线标题与说明图。

---

## 4. 视觉 Token 全量体系

```css
:root {
  /* ──────── 1. 纸张与表面材质 (Paper Surfaces) ──────── */
  --paper:          #FAF8F5;   /* 主纸张背景，温润米白色 (Atelier Warm Paper: #EFE7D2) */
  --paper-card:     #FFFFFF;   /* 纯白阅读纸张与展台卡片底色 (--bone: #F7F1DE) */
  --paper-tint:     #F2ECE1;   /* 次级衬底、工具条底槽、台账表头 (--paper-warm: #ECE4CF) */
  --paper-deep:     #E8E0D2;   /* 强调背景、按压凹陷底色 (--paper-dark: #DDD2B6) */
  --paper-dark-box: #15140F;   /* 极夜黑展台容器（用于高对比度卡片块） */

  /* ──────── 2. 印刷墨水与灰阶 (Ink & Pencil Gradients) ──────── */
  --ink:            #15140F;   /* 德国铸字墨黑，主文字与主边框（1.5px 实线） */
  --ink-soft:       #2A2620;   /* 柔墨黑，大段精读正文 */
  --ink-mute:       #5A5448;   /* 铅笔暖灰，副标题、辅助说明文字 */
  --ink-faint:      #8B8676;   /* 极淡灰元数据、占位符、标尺定位文字 */

  /* ──────── 3. 分割线与网格标线 (Linework & Rules) ──────── */
  --line:           rgba(21, 20, 15, 0.16); /* 核心分割线（1px solid） */
  --line-soft:      rgba(21, 20, 15, 0.08); /* 辅助虚线与二级分割线 */
  --line-faint:     rgba(21, 20, 15, 0.05); /* 侧边轨道与极微弱边界线 */
  --rule:           #D8D0C2;                /* 实体网格实线 */
  --rule-dashed:    #C8BFA9;                /* 打字机卡片虚线 */

  /* ──────── 4. 经典学术强调色 (Editorial Accents) ──────── */
  --coral:          #ED6F5C;   /* 珊瑚朱砂红：主焦点、操作按钮、重点考点 (Goethe Accent: #C14A2B) */
  --coral-soft:     #F08E7C;   /* 柔珊瑚红：悬浮态与微高亮 */
  --mustard:        #E9B94A;   /* 暖芥末黄/琥珀色：发音磁带进度、复习高亮 (Amber: #D9771C) */
  --olive:          #6E7448;   /* 冷杉绿/橄榄绿：掌握测试、良性指标、语法正解 (Moss: #3B6E3F) */
  --ink-blue:       #2A528A;   /* 钢笔墨水蓝：原型词法指向、外链、词性标记 */

  /* ──────── 5. 欧标马卡龙标记色阶 (CEFR Harmonized Highlighters) ──────── */
  --hl-A1:          #E3EFFB;   --hl-A1-ink: #1D548C; /* A1 入门 (淡天蓝) */
  --hl-A2:          #D6ECCF;   --hl-A2-ink: #20662A; /* A2 基础 (鼠尾草绿) */
  --hl-B1:          #FDE9BD;   --hl-B1-ink: #825C00; /* B1 核心 (晨光暖黄) */
  --hl-B2:          #FDE0D7;   --hl-B2-ink: #91261B; /* B2 高级 (浅桃珊瑚) */
  --hl-C1:          #EFE2FA;   --hl-C1-ink: #522485; /* C1 精通 (淡薰衣草紫) */

  /* ──────── 6. 物理投影与阴影 (Tactile Shadows) ──────── */
  --shadow-sm:      0 2px 4px rgba(21, 20, 15, 0.06);
  --shadow-card:    0 14px 28px -12px rgba(21, 20, 15, 0.12);
  --shadow-exhibit: 0 30px 60px -30px rgba(21, 20, 15, 0.18);
  --shadow-hard:    3px 3px 0 rgba(21, 20, 15, 0.15); /* 实体硬印章投影 */

  /* ──────── 7. 缓动与动画时间 (Motion & Transitions) ──────── */
  --ease-editorial: cubic-bezier(0.22, 1, 0.36, 1); /* 顶级杂志回弹曲线 */
  --dur-fast:       180ms;
  --dur-mid:        360ms;
  --dur-slow:       900ms;
}
```

---

## 5. 字体排印阶梯与版式节奏

```css
:root {
  /* 1. 经典大号展示字体 (用于品牌、Hero大标、文章名、词头展示) */
  --serif-display: 'Playfair Display', 'Instrument Serif', 'DM Serif Display', Georgia, serif;

  /* 2. 学术阅读长文字体 (德语图书级衬线体，抗视觉疲劳) */
  --serif-body:    'DM Serif Text', 'Iowan Old Style', Georgia, serif;

  /* 3. 几何与功能无衬线字体 (标题强化、按钮、导航、卡片结构) */
  --sans-tight:    'Inter Tight', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --sans:          'Inter', -apple-system, system-ui, sans-serif;

  /* 4. 打字机与数据台账字体 (所有数据指标、CEFR 标签、公式、走字栏) */
  --mono:          'JetBrains Mono', 'IBM Plex Mono', 'SF Mono', Consolas, monospace;

  /* 5. 手写心得与注疏 (随笔心得、草稿、旁白提示) */
  --hand:          'Caveat', 'Patrick Hand', cursive;
}
```

### 现代社论排印阶梯规格表
| 排版角色 | 字体 Stack | 尺寸 / 行高 | 字重与样式 | 适用场景与规则 |
| :--- | :--- | :--- | :--- | :--- |
| **Hero Display** | `--sans-tight` + `--serif-display` | `clamp(44px, 5.2vw, 78px) / 1.0` | `800 Bold + 500 Italic` | 首页落地展示大标，关键词斜体穿插 |
| **Section Title**| `--sans-tight` | `clamp(32px, 3.8vw, 54px) / 1.05` | `800 ExtraBold` | 模块主标题，字距 `-0.024em` |
| **Article Title**| `--serif-display` | `2.25rem / 1.15` | `700 Normal` | 精读阅读器大标题 |
| **Reader Body**  | `--serif-body` | `1.25rem / 1.95` | `400 Normal` | 德语精读长文正文，字距 `+0.01em` |
| **Card Header**  | `--sans-tight` | `1.375rem / 1.1` | `700 Bold` | 展台卡片标题，字距 `-0.014em` |
| **Data Ring**    | `--mono` 或 `--sans-tight` | `1.25rem / 1.0` | `700 Bold` | 环形指标内部数值 |
| **Data Ticker**  | `--mono` | `0.6875rem / 1.0` | `500 Uppercase` | 顶栏与走字带元数据（字距 `+0.18em`） |
| **Field Note**   | `--hand` | `1.125rem / 1.3` | `700 Normal` | 拟物便签心得手写体、边白批注 |

---

## 6. DeLector「台账（Folio）」全新重塑方案

### 6.1 现有三折页痛点诊断
目前 DeLector 的「台账」采用 3 折页横向滑轨设计（`#folio-track` 宽度 300%，页宽 33.333%）：
* **痛点 1**：在 1024px 以下不同设备尺寸上，滑轨 transform 计算容易产生 1-2px 的亚像素错位，导致右侧内容边缘露出或截断。
* **痛点 2**：用户在「总览」「掌握度」「错题」三页之间需要频繁点击切换，割裂了完整的学习数据心流。
* **痛点 3**：卡片排版较为平面化，未能体现类似 `artifact4.html` 的高级杂志展台排版张力。

### 6.2 全新形态：现代杂志连续展台 (Continuous Exhibition Folio)
借鉴 `artifact4.html` 的多栏不对称网格、环形指标徽章、高对比度黑白展台卡片与打字机折线图，将台账重构为**纵向流式编排、支持快速分段导航的现代学术展台**：

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [🇩🇪 DELECTOR FOLIO // AKADEMISCHES STUDIENBUCH]             [ 2026-08 ] · [ LIVE SYNCED ● ]          │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ § I. 核心研读指标看板 (6-Metric Stat Plate)                                                              │
│                                                                                                        │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐   │
│   │  ( 14 ) 连续  │ │ ( 428 ) 掌握 │ │  ( 36 ) 掌握 │ │  ( 18 ) 精读 │ │ ( 94% ) 准确 │ │( 820m )研读│   │
│   │   TAGE STREAK│ │   VOKABELN   │ │   GRAMMATIK  │ │   ARTIKEL    │ │  QUIZ ACC.   │ │ GESAMTZEIT│   │
│   └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └─────────────┘   │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ § II. 欧标掌握度阶梯与 30 天墨线留存走势 (Mastery Matrix & 30-Day Retention Trendline)                   │
│                                                                                                        │
│  [ 欧标能力阶梯分布 CEFR Matrix ]              [ 30 天研读留存墨线走势 30-Day Trend ]                     │
│  A1 ───────── [████████████████████] 100% (142词)  │                                                   │
│  A2 ───────── [███████████████     ]  78% (180词)  │        /\      /\   /\                            │
│  B1 ───────── [██████████          ]  52%  (86词)  │  __/\_/  \/\__/  \_/  \___ (日均 45 分钟)         │
│  B2 ───────── [████                ]  24%  (18词)  │  [01] ─────────────── [15] ─────────────── [30]   │
│  C1 ───────── [█                   ]   6%   (2词)  │  ↳ 峰值: 110 MIN · 稳定度: 92%                    │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ § III. 错题攻坚集与学术成就印章展台 (Error Ledger & Academic Seals Showcase)                             │
│                                                                                                        │
│  [ 易错词汇双栏攻坚清单 Top Errors ]           [ 歌德备考学术印章展台 Sealed Milestones ]                │
│  · vergeblich    徒劳的、无结果的   [ 4误/1正 ]  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  · verhandeln    谈判、协商         [ 3误/2正 ]  │  │ [SIEGEL 01] ★ │  │ [SIEGEL 02] ✦ │  │ [SIEGEL 03] ○ │  │
│  · beitragen     贡献、有助于       [ 3误/1正 ]  │  │ 词汇破百大师   │  │ 句法从句学者   │  │ 德福满分冲刺 │  │
│  · ankommen auf  取决于 (介词配价)  [ 2误/0正 ]  │  │ ✓ 已加盖钢印   │  │ ✓ 已加盖钢印   │  │ 待达成 (72%)  │  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 台账模块重构代码实现规范

#### 1. 环形指标六宫格 (The 6-Metric Stat Plate)
```html
<div class="folio-stats-grid">
  <!-- 连续天数 -->
  <div class="stat-badge">
    <div class="stat-ring solid coral" id="stat-streak">14</div>
    <div class="stat-text">
      <b>Tage Streak</b>
      <span>连续研读天数</span>
    </div>
  </div>
  <!-- 掌握词汇 -->
  <div class="stat-badge">
    <div class="stat-ring solid" id="stat-mastered-vocab">428</div>
    <div class="stat-text">
      <b>Vokabeln</b>
      <span>已掌握词汇</span>
    </div>
  </div>
  <!-- 掌握语法 -->
  <div class="stat-badge">
    <div class="stat-ring dashed" id="stat-mastered-grammar">36</div>
    <div class="stat-text">
      <b>Grammatik</b>
      <span>掌握语法考点</span>
    </div>
  </div>
  <!-- 精读篇数 -->
  <div class="stat-badge">
    <div class="stat-ring solid" id="stat-articles">18</div>
    <div class="stat-text">
      <b>Artikel</b>
      <span>精读解析文章</span>
    </div>
  </div>
  <!-- 测验准确率 -->
  <div class="stat-badge">
    <div class="stat-ring dashed coral" id="stat-accuracy">94%</div>
    <div class="stat-text">
      <b>Genauigkeit</b>
      <span>测验平均正答率</span>
    </div>
  </div>
  <!-- 研读时长 -->
  <div class="stat-badge">
    <div class="stat-ring solid" id="stat-minutes">820</div>
    <div class="stat-text">
      <b>Minuten</b>
      <span>累计专注时长</span>
    </div>
  </div>
</div>
```

```css
.folio-stats-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
  padding: 24px 0;
  border-bottom: 1px solid var(--line);
}
@media (max-width: 1024px) {
  .folio-stats-grid { grid-template-columns: repeat(3, 1fr); gap: 14px; }
}
@media (max-width: 560px) {
  .folio-stats-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
.stat-badge {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--paper-card);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
}
.stat-ring {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1.5px solid var(--ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}
.stat-ring.dashed { border-style: dashed; }
.stat-ring.coral { border-color: var(--coral); color: var(--coral); }
.stat-text {
  font-family: var(--sans);
  font-size: 11px;
  line-height: 1.25;
  color: var(--ink-mute);
  letter-spacing: 0.02em;
}
.stat-text b {
  display: block;
  font-size: 13px;
  color: var(--ink);
  font-weight: 700;
  text-transform: uppercase;
}
```

---

## 7. 特色学术与语言学组件蓝图

### 7.1 拓扑五场域可视化展台 (Topological Field Visualizer)
德语五场域（VF 前场、LK 左句框、MF 中场、RK 右句框、NF 后场）是德语语法的核心骨架。

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ SATZTOPOLOGIE // TOPOLOGISCHES FELDMODELL (TOPOLOGICAL SYNTAX CARD)                                   │
├───────────────┬───────────────┬───────────────────────────────┬───────────────┬────────────────────────┤
│  VORFELD (VF) │ LINKE KLAMMER │         MITTELFELD (MF)       │ RECHTE KLAMMER│     NACHFELD (NF)      │
│     前场      │   左句框 (LK)  │             中场              │   右句框 (RK)  │          后场          │
├───────────────┼───────────────┼───────────────────────────────┼───────────────┼────────────────────────┤
│ [ Gestern ]   │ [ hat ]       │ der fleißige Student das Buch │ [ gelesen ],  │ [ weil er Zeit hatte. ]│
│  ADV / 时间状语│  AUX / 助动词  │     SUBJ + AKK.OBJ / 主宾语   │  PART.II / 动词│    NEBENSATZ / 原因从句 │
└───────────────┴───────────────┴───────────────────────────────┴───────────────┴────────────────────────┘
```

```css
.syntax-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr 2fr 1.2fr 1.6fr;
  border: 1.5px solid var(--ink);
  background: var(--paper-card);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--shadow-hard);
}
.syntax-field {
  padding: 14px 12px;
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
}
.syntax-field:last-child { border-right: none; }
.syntax-field-head {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-faint);
  border-bottom: 1px dashed var(--line);
  padding-bottom: 6px;
  margin-bottom: 10px;
}
.syntax-field-token {
  font-family: var(--serif-display);
  font-size: 17px;
  color: var(--ink);
  margin-bottom: 4px;
}
.syntax-field-meta {
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--coral);
}
```

### 7.2 复古录音磁带发音控制台 (Cassette Deck Audio Console)
内嵌于精读阅读器底部，取代漂浮黑色胶囊。

```html
<div class="cassette-deck">
  <!-- 磁带走带窗口 -->
  <div class="cassette-window">
    <div class="cassette-spool left spinning"></div>
    <div class="cassette-tape-ribbon">
      <div class="tape-counter">04:28 // SATZ 03/12</div>
      <div class="tape-title">DIE TRANSFORMATION DER ARBEITSWELT</div>
    </div>
    <div class="cassette-spool right spinning"></div>
  </div>

  <!-- 机械按键区 -->
  <div class="cassette-controls">
    <button class="mech-btn" title="上句 [K]">⏮</button>
    <button class="mech-btn play-btn" title="播放/暂停 [Space]">▶</button>
    <button class="mech-btn" title="下句 [J]">⏭</button>
    <button class="mech-btn" title="循环单句 [R]">🔁</button>
    
    <!-- 音色与语速 -->
    <div class="cassette-toggles">
      <div class="toggle-slot">
        <span class="active">👩 Katja</span>
        <span>👨 Conrad</span>
      </div>
      <div class="toggle-slot">
        <span>0.8x</span>
        <span class="active">1.0x</span>
        <span>1.2x</span>
      </div>
    </div>
  </div>
</div>
```

```css
.cassette-deck {
  background: var(--paper-deep);
  border: 1.5px solid var(--ink);
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: var(--shadow-hard);
  margin-top: 24px;
}
.cassette-window {
  background: var(--ink);
  color: var(--paper);
  border-radius: 8px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid rgba(255,255,255,0.1);
  margin-bottom: 14px;
}
.cassette-spool {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px dashed var(--mustard);
}
.cassette-tape-ribbon {
  flex: 1;
  text-align: center;
  font-family: var(--mono);
}
.tape-counter { font-size: 11px; color: var(--mustard); letter-spacing: 0.12em; }
.tape-title { font-size: 12px; color: #fff; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cassette-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.mech-btn {
  padding: 8px 14px;
  background: var(--paper-card);
  border: 1.5px solid var(--ink);
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 2px 2px 0 var(--ink);
  transition: transform 80ms ease, box-shadow 80ms ease;
}
.mech-btn:active {
  transform: translate(2px, 2px);
  box-shadow: 0 0 0 var(--ink);
}
.mech-btn.play-btn {
  background: var(--coral);
  color: #fff;
  border-color: var(--ink);
}
```

---

## 8. 交互动效、无障碍与移动端触控规范

### 8.1 优雅进场动效 (`[data-reveal]` Protocol)
使用 `artifact4.html` 标准的 `IntersectionObserver` 进场驱动：
```css
[data-reveal] {
  opacity: 0;
  translate: 0 28px;
  transition:
    opacity 900ms var(--ease-editorial) var(--reveal-delay, 0ms),
    translate 900ms var(--ease-editorial) var(--reveal-delay, 0ms),
    scale 900ms var(--ease-editorial) var(--reveal-delay, 0ms);
  will-change: opacity, translate, scale;
}
[data-reveal='scale'] { translate: 0 0; scale: 0.96; }
[data-reveal][data-revealed='true'] {
  opacity: 1;
  translate: 0 0;
  scale: 1;
}

/* 阶梯延迟 */
.folio-stats-grid > .stat-badge:nth-child(1) { --reveal-delay: 0ms; }
.folio-stats-grid > .stat-badge:nth-child(2) { --reveal-delay: 60ms; }
.folio-stats-grid > .stat-badge:nth-child(3) { --reveal-delay: 120ms; }
.folio-stats-grid > .stat-badge:nth-child(4) { --reveal-delay: 180ms; }
.folio-stats-grid > .stat-badge:nth-child(5) { --reveal-delay: 240ms; }
.folio-stats-grid > .stat-badge:nth-child(6) { --reveal-delay: 300ms; }
```

### 8.2 减动效用户保护 (Prefers-Reduced-Motion)
```css
@media (prefers-reduced-motion: reduce) {
  [data-reveal] {
    opacity: 1 !important;
    translate: 0 0 !important;
    scale: 1 !important;
    transition: none !important;
  }
  .marquee-track { animation: none !important; }
}
```

### 8.3 移动端与触控增强 (Touch Targets & Dock Threshold)
1. **44px × 44px 黄金触控区**：所有移动端按键、查词高亮词块、发音控制按钮点击区域不得小于 `44px`。
2. **1024px 宽幅底部常驻导航 Dock**：
   在屏幕宽度 `<= 1024px` 时，顶部导航栏自动收起，切换为底部拇指操作的极简 Dock，包含 `[ 📖 精读 | 🎴 卡片 | 📊 台账 | ✍️ 完形 ]` 四大核心入口。

---

## 9. 反同质化守则与设计防线 (Anti-Cliché Guardrails)

| ❌ 严厉禁止的 AI 同质化模板 | ✅ DeLector v3.0 规范替代方案 |
| :--- | :--- |
| **滥用深色毛玻璃大圆角胶囊** (`rounded-full backdrop-blur-xl bg-black/60`) | **重磅物理纸张底色 + 1.5px 印刷墨线边框** (`border: 1.5px solid var(--ink); background: var(--paper-card);`) |
| **泛滥的彩虹流光渐变文字** (`bg-gradient-to-r from-purple-400 to-pink-600 text-transparent`) | **纯正德国铸字墨黑，核心词辅以斜体衬线或朱砂红强调** (`font-family: var(--serif-display); font-style: italic; color: var(--coral);`) |
| **满屏霓虹外发光** (`glow ring-4 ring-indigo-500/50`) | **实体硬质物理硬投影** (`box-shadow: 3px 3px 0 rgba(21, 20, 15, 0.15);`) |
| **无序堆叠的随意 Bento Box** | **严谨的社论台账结构（Ledger List）与多栏不对称黄金分割展台** |
| **阻断式弹窗与花哨 Alert** | **顶部等宽数据走字通知带与和纸便签内嵌分析抽屉** |

---

*本规范由 DeLector 前端架构与 UI/UX 委员会统一制定并维护，作为全站组件迭代与视觉重塑的单一真实数据源 (Single Source of Truth)。*
