# DeLector 设计系统规范 (Design System Specification v2.0)
> **版本**：v2.0 · 2026-08  
> **视觉流派**：Gutenberg Broadsheet + Bauhaus Stationery (德式经典社论报刊与包豪斯手账工作台)  
> **核心定位**：专为德语欧标（CEFR A1–C1）长文精读、歌德证书备考与知识内化打造的极简高密度学术研读工作台。

---

## 1. 设计演进与去 AI 同质化哲学 (Design Evolution & De-AI Philosophy)

随着功能迭代（神经网络语音切换、多模式跟读、随笔批注、导出与全库备份），界面曾逐渐出现“按钮碎片化堆砌、胶囊药丸泛滥、深色玻璃拟态与纸质手账割裂”等典型 AI 同质化弊病。

**v2.0 确立四大设计铁律（去除 AI 模板痕迹）：**

1. **统一材质基底，杜绝割裂的暗黑毛玻璃**：
   - 彻底摒弃浮于表面的暗黑渐变毛玻璃胶囊（如旧版 `#shadow-player`）。
   - 全站统一回归 **“温润纸张（Paper）+ 印刷墨线（Ink 1.5px）+ 和纸胶带（Washi Tape）”** 的真实手作质感，所有浮层与工具条均生长于统一的物理桌面上。
2. **社论台账化结构（Broadsheet Ledger）**：
   - 借鉴 `artifact3.html` 的报刊台账结构，用极简细实线（`1px solid var(--rule)`）与单色元数据对齐替代毫无意义的圆角卡片嵌套。
3. **顶栏数据走字带（Editorial Ticker Ribbon）**：
   - 整合零散的状态标签，统一收纳进等宽字体数据带：`[ LEVEL: B1 ]  [ WORDS: 428 ]  [ EST: 4 MIN ]`。
4. **功能聚拢与减法**：
   - 合并同类操作，减少独立悬浮按钮。一个工具条只做一件事，用物理按压感（Ink Press）替代花哨的流光发光动效。

---

## 2. 视觉 Token 系统 (Design Tokens)

### 2.1 基础环境与纸张色 (Surfaces & Ink)
```css
:root {
  /* 基础纸张与墨水 */
  --paper:          #FAF8F5;   /* 主纸张背景，温润米白色 */
  --paper-card:     #FFFFFF;   /* 正式卡片与阅读纸张纯白底色 */
  --paper-tint:     #F2ECE1;   /* 次级衬底、工具条底槽、台账表头 */
  --paper-deep:     #E8E0D2;   /* 强调背景、按压凹陷底色 */
  
  --ink:            #1A1714;   /* 德国铸字墨黑，主文字与主边框（1.5px） */
  --pencil:         #5C554B;   /* 铅笔暖灰，副标题与说明文字 */
  --muted:          #8C8477;   /* 淡灰元数据与占位符 */
  --rule:           #D8D0C2;   /* 台账网格线与浅色分割线 */
  --rule-light:     #EBE5DA;   /* 极细微衬线 */
  
  /* 物理材质 */
  --grid-dot:       rgba(26, 23, 20, 0.05); /* 20px x 20px 纸张点阵网格 */
  --tape:           rgba(43, 38, 32, 0.12); /* 磨砂半透明和纸胶带 */
  --tape-border:    rgba(26, 23, 20, 0.18);
}
```

### 2.2 经典学术强调色 (Editorial Accents)
```css
:root {
  --accent:         #C14A2B;   /* 哥德朱砂红（Cinnabar）：主焦点、操作按键、重要考点 */
  --accent-hover:   #A83B1F;
  --amber:          #D9771C;   /* 暖琥珀黄：音频播放进度、随笔提示、复习高亮 */
  --moss:           #3B6E3F;   /* 经典冷杉绿：通过测试、已掌握考点、良性指标 */
  --ink-blue:       #2A528A;   /* 钢笔墨水蓝：原型指向、外链、词性标记 */
}
```

### 2.3 欧标马卡龙标记色阶 (CEFR Harmonized Highlighters)
> 降低饱和度，模拟真实浅色荧光笔在书籍上的柔和浸润感，消除视觉刺眼感。

```css
:root {
  /* A1 - 入门认知 (淡天蓝) */
  --hl-A1:          #E3EFFB;
  --hl-A1-ink:      #1D548C;

  /* A2 - 基础进阶 (柔鼠尾草绿) */
  --hl-A2:          #D6ECCF;
  --hl-A2-ink:      #20662A;

  /* B1 - 核心中级 (晨光暖黄) */
  --hl-B1:          #FDE9BD;
  --hl-B1-ink:      #825C00;

  /* B2 - 高级应用 (珊瑚浅桃粉) */
  --hl-B2:          #FDE0D7;
  --hl-B2-ink:      #91261B;

  /* C1 - 精通论述 (浅薰衣草紫) */
  --hl-C1:          #EFE2FA;
  --hl-C1-ink:      #522485;
}
```

### 2.4 手账拟物便签色彩 (Tactile Sticky Note Tints)
```css
:root {
  --note-yellow:    #FFFBE6;   /* 暖黄便签：默认词汇分析卡与个人随笔 */
  --note-pink:      #FFF0ED;   /* 桃粉便签：歌德语法深度剖析 */
  --note-green:     #EDF7EC;   /* 浅绿便签：例句搭配与习惯表达 */
}
```

---

## 3. 字体体系与层级阶梯 (Typography Stack)

```css
:root {
  /* 1. 经典杂志标题 (用于品牌 Logo、文章大标题、词头展现) */
  --serif-display: 'Instrument Serif', 'DM Serif Display', Georgia, serif;
  
  /* 2. 学术阅读长文 (德国图书级衬线体，阅读不疲劳) */
  --serif-body:    'DM Serif Text', 'Iowan Old Style', Georgia, serif;
  
  /* 3. 界面功能与通用正文 */
  --sans:          'Inter', -apple-system, system-ui, sans-serif;
  
  /* 4. 数据台账与元数据 (所有数据指标、CEFR 徽标、公式、走字栏) */
  --mono:          'IBM Plex Mono', 'SF Mono', Consolas, monospace;
  
  /* 5. 手写心得与注疏 (随笔心得、草稿、旁白提示) */
  --hand:          'Caveat', 'Patrick Hand', cursive;
}
```

### 排版阶梯规格表
| 角色 | 字体 | 尺寸 / 行高 | 字重与样式 | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| **Brand Logo** | `--serif-display` | `1.75rem / 1.0` | `800 Italic` | 顶栏 `DeLector.` 标，末尾朱红点 |
| **Article Title** | `--serif-display` | `2.25rem / 1.15` | `700 Normal` | 阅读器与文章列表标题 |
| **Reader Body** | `--serif-body` | `1.25rem / 1.95` | `400 Normal` | 德语精读长文（字距 `+0.01em`） |
| **Data Ticker** | `--mono` | `0.75rem / 1.0` | `500 Uppercase` | 顶栏元数据走字带（字距 `+0.12em`） |
| **UI Control** | `--sans` | `0.8125rem / 1.2`| `600 Normal` | 按钮、输入框、选项卡标签 |
| **Margin Note** | `--hand` | `1.125rem / 1.3` | `700 Normal` | 拟物便签心得手写体、边白批注 |

---

## 4. 核心组件重构规范 (Component Blueprint)

### 4.1 顶部数据走字带 (The Editorial Ticker Bar)
* **位置**：页面最顶端，贯穿全屏。
* **样式**：高度 `36px`，`background: var(--paper-tint); border-bottom: 1px solid var(--ink);`。
* **内容编排**：
  ```
  [ 🇩🇪 DELECTOR // 01 LEKTÜRE ]  ───  [ CEFR LEVEL: B1 ]  ·  [ 482 WÖRTER ]  ·  [ ⏱️ 5 MIN ]  ───  [ SYSTEM STATUS: READY ]
  ```

### 4.2 统一学术阅读器面板 (Reader Workspace)
* **纸张主体**：居中最大宽度 `820px`，纯白卡片底，`border: 1.5px solid var(--ink)`，右下带有硬质物理投影（`4px 4px 0 rgba(26,23,20,0.1)`）。
* **段落编排**：段间距 `1.75rem`，首行段落首字下沉或带段落标记（`§ 1`, `§ 2`）。
* **分词与划线**：
  - 普通生词：轻浅底色高亮（`var(--hl-B1)`），圆角 `2px`；
  - 当前朗读句（Karaoke Glow）：整句下方带有 `2px solid var(--amber)` 琥珀色下划线，背景微泛黄，不遮挡文字；
  - 选中词（Active Token）：反相墨黑底白字（`background: var(--ink); color: #FFF`），带 `1px solid var(--ink)` 外框。

### 4.3 桌面录音机式音频中控 (The Editorial Audio Console)
* **设计原则**：告别飘在半空的黑色浮动胶囊，将其打造成**内嵌在阅读器底部的磁带机控制台（Cassette Audio Deck）**。
* **布局规范**：
  - 底色：`var(--paper-deep)`，四周包裹 `1.5px solid var(--ink)`；
  - 左侧：机械式方形按键（`⏮` 上句、`▶` 播放/暂停、`⏭` 下句、`🔁` 重听），实心物理按压反馈；
  - 中间：音色切换切换器（`[ 👩 Katja ] [ 👨 Conrad ]`），纸质物理凹陷槽；
  - 右侧：语速步进与模式选择（`0.8x / 1.0x / 1.2x` 与 `跟读 / 连读 / 单句`）。

### 4.4 和纸便签分析抽屉 (Sticky Note Workspace)
* **顶部特征**：双色和纸胶带封头（`tape-top`），轻微手作倾斜（`-1deg`）。
* **便签选项卡**：顶部嵌入式三段切换 `[ 📖 词汇考点 | 📝 随笔便签 | ✦ 全部 ]`，切换即平滑滚动或就地过滤。
* **考点公式区**：采用等宽虚线打字机方框（`border: 1px dashed var(--ink); background: #FAF6ED;`）。

---

## 5. 德语学习数据可视化与考点台账规范 (Data Ledger & Metrics Specification)
> **借鉴 `artifact3.html` 的严谨报刊台账结构**，为后续学习分析与复习概览模块提供标准。

### 5.1 学习台账总体架构 (Dashboard Ledger Layout)
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 🇩🇪 DELECTOR ANALYTICS // MEIN FORTSCHRITT                          [ 2026-08 ]  │
├────────────────────────────────┬────────────────────────────────────────────────┤
│ 1. 欧标掌握度阶梯 (CEFR Matrix) │ 2. 核心考点突破雷达 (Grammar Scorecard)         │
│  A1 [████████████████] 100%    │  · Akkusativ/Dativ 介词配价      [ 92% 掌握 ]   │
│  A2 [████████████    ]  78%    │  · Passiv 被动态与情态动词      [ 64% 需强化 ] │
│  B1 [████████        ]  52%    │  · Nebensatz 连词从句从属句式   [ 81% 掌握 ]   │
│  B2 [████            ]  24%    │  · Konjunktiv II 虚拟式假设表达 [ 35% 待学习 ] │
│  C1 [█               ]   6%    │                                                │
├────────────────────────────────┴────────────────────────────────────────────────┤
│ 3. 近期精读台账 (Recent Reading Ledger)                                         │
│  DATUM      TITEL                                      STUFE    WÖRTER   STATUS │
│  2026-08-18 Die Transformation der Arbeitswelt         [ B2 ]   482 W    ✓ 完成  │
│  2026-08-17 Klimaschutz im Alltag: Was jeder tun kann  [ B1 ]   365 W    ✓ 完成  │
│  2026-08-16 Eine Reise nach München                    [ A2 ]   280 W    ✓ 完成  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 数据图表设计规则
1. **进度计量槽（Gauge Meter）**：
   - 杜绝炫彩渐变与霓虹发光；
   - 采用报刊式实心墨黑分格槽（`height: 8px; border: 1px solid var(--ink); background: var(--paper-deep);`，填充块使用 `var(--ink)` 或 `var(--accent)`）。
2. **状态指标印章（Status Stamps）**：
   - 完成/通过：`[ ✓ BEHERRSCHT ]` 绿色细线印章；
   - 待复习：`[ ⚠️ WIEDERHOLEN ]` 琥珀色虚线印章；
   - 重点难点：`[ ★ SCHWERPUNKT ]` 朱红色实线方印。
3. **数据字体规范**：
   - 所有百分比、计数、日期、耗时一律采用 `IBM Plex Mono`，字距微调 `letter-spacing: 0.05em`。

---

## 6. 反模式与防 AI 同质化守则 (Anti-Cliché Guardrails)

| 禁忌 AI 模板模式 | DeLector 规范替代方案 |
| :--- | :--- |
| ❌ 泛滥的深色毛玻璃大圆角胶囊 (`rounded-full backdrop-blur-xl`) | ✅ 扎实的物理纸张卡片与 1.5px 墨线边框 (`border: 1.5px solid var(--ink)`) |
| ❌ 渐变色字、彩虹文字 (`text-gradient`) | ✅ 纯黑印刷墨字，局部辅以手写体或朱砂红点缀 |
| ❌ 满屏发光外描边 (`glow ring-2 ring-purple-500`) | ✅ 物理硬投影（`box-shadow: 3px 3px 0 rgba(26,23,20,0.1)`) |
| ❌ 无序堆砌的 Bento Box 随意插图标 | ✅ 严谨的社论台账（Ledger List）与结构化考点折叠卡 |
| ❌ 随意弹出的阻断式 Alert | ✅ 嵌入式内联状态文字与顶栏走字信息通知 |
