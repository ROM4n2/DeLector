# DeLector 设计规范 (Design System Specification)
> **版本**：v1.0 · 2026-08  
> **流派**：Modern Editorial + Notebook Sticky-Notes Hybrid (现代杂志刊物与手帐便签融合风格)  
> **核心定位**：专为德语欧标（CEFR A2-C1）长文研读与歌德证书备考打造的沉浸式工作台。

---

## 1. 设计哲学 (Design Philosophy)

1. **学术刊物的长文呼吸感 (Editorial Serenity)**：
   - 德语长文阅读需要极高可读性。正文采用书籍级衬线体与大行高（`1.95`），杜绝视觉拥挤与廉价感。
2. **手写备考笔记的人情味 (Notebook & Craft Flair)**：
   - 考点解析与制卡流程借鉴真实的便签（Sticky Note）、胶带（Tape）、印章（Pin/Stamp）与马克笔荧光涂抹（Marker Highlighter），营造“自己的复习错题本”沉浸感。
3. **语义驱动的色标体系 (Semantic Color Coding)**：
   - CEFR 难度（A2/B1/B2/C1）采用温和清新的柔和马卡龙色阶，既一目了然，又不破坏整体阅读流畅度。

---

## 2. 字体体系 (Typography Trio)

| 角色 | 字体名称 | 典型字阶 / 粗细 | 应用场景 |
| :--- | :--- | :--- | :--- |
| **Display / 杂志大标题** | `Instrument Serif` | `2.75rem` / `700 Italic` | 首页 Hero 标题、文稿行标题、抽屉大字、卡片正面德语词 |
| **Reading / 德语正文** | `DM Serif Display` | `1.25rem` / `line-height: 1.95` | 文章阅读器长文段落 |
| **Interface / 界面与正文** | `Inter` | `0.8125rem`–`0.9375rem` / `500-600` | 按钮、输入框、常规解释、列表说明 |
| **Technical / 代码与元数据** | `IBM Plex Mono` | `0.65rem`–`0.75rem` / `600 Uppercase` | CEFR 徽标、词性/原型、语法公式、日期/字符统计、图章 |
| **Handwritten / 手写批注** | `Patrick Hand` | `1.125rem`–`1.25rem` / `400` | 空状态引导、手帐注疏提示 |

---

## 3. 色彩与材质 Token (Color & Surface Tokens)

### 3.1 基础环境色 (Base Surfaces & Ink)
```css
--paper:       #FAF8F5;   /* 主纸张背景，带细微温润米白色调 */
--paper-tint:  #F3EDE4;   /* 二级衬底、图例条背景 */
--stage:       #181512;   /* 深炭黑底色（用于深色按钮与高对比元素） */
--ink:         #1A1714;   /* 印刷墨黑，全站主文字与主边框色 */
--pencil:      #5E564C;   /* 铅笔灰，用于次要元数据与辅助说明 */
--rule:        #DDD7CD;   /* 浅线边框与账簿分割线 */
--grid-dot:    rgba(26, 23, 20, 0.06); /* 点阵网格材质 (22px x 22px) */
```

### 3.2 强调色 (Accents)
```css
--accent:      #D8482B;   /* 熟褐朱红（Cinnabar），主操作、焦点强调、图章虚线 */
--amber:       #E98425;   /* 琥珀暖橙，用于微高亮与渐变 */
--tape:        rgba(43, 38, 32, 0.14); /* 磨砂半透明胶带纸材质 */
```

### 3.3 欧标马克笔色阶 (CEFR Pastel Marker Palette)
```css
/* A2 - 进阶表达 */
--hl-A2:       #D2EECB;   /* 柔和鼠尾草绿 */
--hl-A2-ink:   #1F6B27;

/* B1 - 核心中级 */
--hl-B1:       #FFE9BF;   /* 阳光暖黄 */
--hl-B1-ink:   #8A6400;

/* B2 - 高级考点 */
--hl-B2:       #FFE1D9;   /* 珊瑚浅桃粉 */
--hl-B2-ink:   #9A2418;

/* C1 - 精通论述 */
--hl-C1:       #F3E6FF;   /* 优雅薰衣草紫 */
--hl-C1-ink:   #53248A;
```

### 3.4 手帐便签色彩 (Sticky Notes Palette)
```css
--note-yellow: #FEF9D9;   /* 经典暖黄便签（抽屉主背景、词汇卡） */
--note-pink:   #FFEAE4;   /* 桃粉便签（语法考点卡、偶数复习卡） */
--note-blue:   #E4F0FF;   /* 天蓝便签（三倍数复习卡） */
```

---

## 4. 核心组件与布局规范 (Component Guidelines)

### 4.1 导航栏 (Navigation)
- **品牌标**：`DeLector.` 斜体衬线，句末带朱红强调点。
- **徽标图章**：倾斜 `-1.5deg` 的 `1.5px dashed` 胶囊框，全大写等宽字体。
- **底纹与边框**：`2px solid var(--ink)` 扎实底线，配合 `backdrop-filter: blur(10px)`。

### 4.2 首页与文稿列表 (Home & Ruled Rows)
- **Hero 区**：圆点胶囊徽标（`● CEFR IMMERSIVE WORKSPACE`）引领大标题。
- **文稿行**：账簿式水平行（Ruled Rows），悬浮时向右微移 `+6px`，标题变朱红色，右侧指示箭头平滑位移。

### 4.3 沉浸阅读工作台 (Reader Workspace)
- **阅读纸张卡**：白底纸面卡片，`2px solid var(--ink)` 边框，右下方带有硬质投影 `5px 6px 0 -1px rgba(26,23,20,0.12)`。
- **词汇分词（Tokenized Text）**：
  - 未标注生词：纯文本无背景；
  - CEFR 生词：带有对应马卡龙底色（`padding: 1px 2px; border-radius: 2px`）；
  - 选中词（Active Token）：反色墨黑（`background: var(--ink); color: #FEF9EE`）并带有墨黑外轮廓光圈。

### 4.4 胶带便签抽屉 (Sticky Note Slide-over Drawer)
- **顶部胶带**：居中跨接的半透明磨砂胶带（`tape-top`），带有虚线边缘与轻微倾斜（`-1deg`）。
- **词汇分析卡**：白底便签卡，大号斜体词头配 `IBM Plex Mono` 词性/变格元数据。
- **语法剖析卡**：桃粉色独立便签，语法句型公式（Rule Formula）使用虚线等宽代码块展示。
- **原句回溯**：虚线透明底框，用斜体衬线字体呈现完整德语语境。

### 4.5 复习卡片库 (Cards Library)
- **网格排列**：自然交替黄/粉/蓝三色便签。
- **手作微倾角**：偶数卡片旋转 `+0.4deg`，奇数卡片旋转 `-0.5deg`，鼠标悬浮时回正并向上浮动 `-2px`。

---

## 5. 交互与动效原则 (Interaction & Motion)

1. **抽屉滑入**：
   - 贝塞尔曲线：`transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1)`
2. **按钮点击反馈**：
   - 统一采用物理投影按压感（`transform: translateY(-1px)` 悬浮，`translateY(1px)` 按下）。
3. **触控与无障碍友好**：
   - 移动端/平板触控热区保持在 `≥ 36px - 44px`。
