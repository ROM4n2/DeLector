# DeLector 去 Emoji 与「呼吸感」重构调研

- **状态**：调研稿，供评审；本轮不改任何前端代码 / README / CSS / JS。
- **日期**：2026-11-06
- **调研范围**：`README.md` + `static/**/*.{html,js,css}`（含生成产物 `static/index.html` 与源片段）
- **证据标记约定**：
  - `[实测]` 本轮在本仓库扫描/统计得到，给出 `文件:行号` 或统计口径；
  - `[来源]` 有外部链接支撑，链接见附录 B；
  - `[推断]` 基于实测与来源的判断，未做用户实验；
  - `[未验证]` 本轮无法证实，已列入第 10 节。
- **配套原型**：`docs/research/2026-11-06-emoji-vs-typography-prototype.html`（独立静态页，未接入构建链）。

---

## 0. 结论先行

1. **问题集中在「装饰层」，不在「内容层」。** `[实测]` 全仓 551 个 emoji 簇中，523 个出现在用户可见文案里；其中 **382 个（73%）与紧邻的中文文案完全同义**（如 `📖 精读`、`📊 学习统计`），删掉不损失任何信息。README 的正文含具体版本号、ADR 链接与实测数字，内容质量是健康的；让它显「AI」的是 **10/12 个二级标题带 emoji + 9/12 个标题带英文括注** 这种模板化装饰。
2. **不建议用「图标库替换 emoji」一刀切。** `[实测]` 真正「emoji 是唯一信息载体」的只有 83 个（16%），且大多数是带 `title` 的按钮；其中约 60 个可以靠**纯文字 + 排版**解决，只有约 20 个值得画 SVG。真正需要插画的只有 **4 个伴学角色 + 5 处空状态**。
3. **「呼吸感」缺的不是留白，是系统。** `[实测]` `static/style.css` 里有 **11 种 line-height、8 种 letter-spacing、5 种非 8pt 网格的 gap 值、78 处 11px、24 处 10px**；`static/css/tokens.css` 只有颜色与 4 个动效时长，**没有间距阶梯与字号阶梯**。先把 4/8pt 间距与 6 级字阶立起来，比再加 24px padding 有效得多。
4. **彻底取缔 emoji 可行，而且仓库里已有样板。** `[实测]` `static/views/home.html` 的首屏（eyebrow 小圆点 + 等宽大写 + 衬线大标题 + 单个斜体强调词 + 两条文字 CTA）以及 `static/layout/nav_desktop.html`（德文标签 + 中文标签，无 emoji）已经是「无 emoji 但不死板」的现成范式。重构应把它推广，而不是另发明一套视觉语言。
5. **优先级**：P0 先做「零设计依赖」的删除（382 个冗余 + README 装饰 + 26 个注释内 emoji），预计移除 70% 以上的 emoji 且不改任何布局；P1 处理 83 个 icon-only 与状态标记；P2 才做角色 SVG、间距/字阶系统与动效。先 P0 就能显著降低「AI 味」，且风险最低。

---

## 1. 现状清点

### 1.1 扫描口径

- `[实测]` 判定规则：按 Unicode 码位范围识别 emoji（`U+1F000–U+1FAFF`、`U+2600–U+26FF`、`U+2700–U+27BF`、`U+2B00–U+2BFF`、区域指示符、变体选择符 `U+FE0F`），并把 `→ ✓ ✕ ✗ ✦ ●` 等**非彩色排版符号**单独计数，避免把「箭头」误报成 emoji。
- `[实测]` 区分「可见」与「注释」：HTML 注释、JS 行注释/块注释、CSS 注释不计入可见量。
- `[实测]` `static/index.html` 由 `tools/build_index_html.py` 从 `static/index.skeleton.html` 的 `@include` 片段组装，是**构建产物**；它的 emoji 与 `layout/`、`views/`、`modals/` 源片段重复。**不要把它和源片段相加**。
- `[实测]` 复现方式见附录 A。分类采用启发式，误差约 ±5%；已发现 `⭐`（U+2B50）2 例被归入排版符号，未影响结论。

### 1.2 总量

| 范围 | 可见 emoji | 注释内 emoji | 行数 | 密度（个/100 行） | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| `README.md` | 24 | 0 | 226 | **10.6** | 10/12 个标题带 emoji |
| `static/index.html`（生成物） | 143 | 2 | 3326 | 4.3 | 与下方源片段重复，仅供核对 |
| `static` 源片段（不含 `index.html`） | **356** | 26 | — | — | 真正需要修改的源 |
| **去重合计（README + static 源）** | **380** | **26** | — | — | 本文后续以 380 为准 |
| 非彩色排版符号（✓/✕/✗/✦ 等） | 147 | — | — | — | `✓` 87、`✕` 35、`✗` 10、`✦` 10 |

`[实测]` 可见 emoji 共 **523** 个（含生成物），去重后 **380** 个；**86 个不同 emoji** 被重复使用 **6.4 次/个**。Top 频次：

| 次数 | emoji | 主要语义 | 典型位置 |
| ---: | --- | --- | --- |
| 42 | `🔊` | 播放/朗读 | 卡片、阅读器、抽屉、写作 |
| 40 | `⚠️` | 警告/疑点 | `static/js/writer.js:405`、`:438`、`:549` |
| 24 | `✍️` | 写作/检查 | `static/views/writer.html:76`、`:84`、`:192` |
| 19 | `📖` | 阅读/词汇 | `static/views/exam.html:14`、`:16`、`:70` |
| 18 | `⚡` | 快速/本地/强度 | `static/js/reader.js:446-448`、`static/modals/drawer.html:384` |
| 17 | `🎯` | 练习/目标 | `static/views/exam.html:93`、`:141` |
| 16 | `📝` | 写作/便签 | `static/views/exam.html:12`、`static/modals/drawer.html:32` |
| 15 | `🔍` | 搜索/诊断 | `static/views/exam.html:269`、`static/js/a1_cards.js:382` |
| 15 | `✨` | AI/润色 | `static/js/writer.js:715`、`:1212` |
| 14 | `📚` | 工作台/词库 | `static/js/cards.js:220`、`static/views/writer.html:130` |

### 1.3 按用途分类

`[实测]` 523 个可见 emoji 的用途分布（启发式归类，含代表行号）：

| 类别 | 数量 | 占比 | 代表位置 |
| --- | ---: | ---: | --- |
| A 导航图标 | 11 | 2.1% | `static/layout/nav_mobile.html:7,15,23,31,39,47,55,63`；`static/layout/nav_desktop.html:39,48,55` |
| B 输入占位符 | 2 | 0.4% | `static/views/exam.html:269`（`placeholder="🔍 搜索 A1 单词…"`） |
| C 图标按钮（带 tooltip） | 22 | 4.2% | `static/german/workbench.html:59`（`🔊` 播放）；`static/js/a1_cards.js:492`（`🔀 翻转`） |
| D tooltip | 2 | 0.4% | `static/views/cards.html:40`（`title="⚠ 用备份文件…"`） |
| E 状态/结果标记 | 64 | 12.2% | `static/js/writer.js:405`（`⚠️ 发现 N 处语法疑点`）；`static/js/cards.js:133`（`🎉`/`🛡️`/`🎴` 三态） |
| F 运行时提示/toast | 32 | 6.1% | `static/js/cloze.js:113`；`static/js/companion.js:612`；`static/js/writer.js:974` |
| G 按钮/选项文案 | 49 | 9.4% | `static/views/exam.html:59`（`🎲 随机练习`）；`static/views/writer.html:33-60` |
| H 标题/分区 | 18 | 3.4% | `static/views/writer.html:178,189,202,239`；`static/views/exam.html:70,305,326` |
| I 角色/图标位 | 26 | 5.0% | `static/layout/companion.html:17,33,41,49,57`；`static/index.html:2434-2444` |
| J 列表符号（`❖`） | 6 | 1.1% | `static/modals/import_modal.html:28,35,42` |
| K 装饰/语气/未归类前缀 | **291** | **55.6%** | `README.md:32`（`## 🚀 快速启动 (Quick Start)`）、`:51`、`:57`；前端大量 `<span>📖 精选</span>` 形态 |
| **合计** | **523** | 100% | — |

`[实测]` K 类中 README 占 22 个、前端占 269 个。对前端 K 类人工抽样 40 条，其中 34 条是「emoji + 中文短标签」的句首装饰（可直删），其余为模板字符串拼接。

### 1.4 信息承载分级（决定替换策略）

| 级别 | 判定 | 数量 | 占比 | 处理方式 |
| --- | --- | ---: | ---: | --- |
| 纯冗余 | emoji 后紧跟同义中文（如 `📖 精读`） | **382** | 73.0% | 直接删，零设计成本 |
| 唯一载体 | 图标位/纯图标按钮，删后无文字（如 `🔊`、`🗑️`） | **83** | 15.9% | 替换：文字、SVG 或 CSS 图形 |
| 其他 | 英文文案、模板拼接、动态三态等 | 58 | 11.1% | 按语义逐项处理 |

`[实测]` 附加特征：

- **72 个（占可见量的 13.8%）带 `U+FE0F` 变体选择符**（`⚠️`、`✍️`、`⚙️`、`🗑️`、`👁️`、`🎙️`、`🛡️`），渲染取决于平台是否按 emoji presentation 处理；
- **2 个国旗**：`static/js/a1_hoeren.js` 中的 `🇩🇪` / `🇨🇳`；
- **0 个 `aria-label` / `aria-hidden`**：所有 emoji 都作为普通文本节点暴露给读屏器；
- **25 行 `title="…emoji…"`**：原生 tooltip 与读屏名称里都带 emoji。

### 1.5 同屏密度（最容易「一眼 AI」的位置）

| 场景 | 同屏 emoji 数 | 位置 | 问题 |
| --- | ---: | --- | --- |
| 移动端底栏 | 8 | `static/layout/nav_mobile.html:7-63` | 8 个 emoji 并排，色板/笔画/基线各不相同 |
| 考试模块宫格 | 7 | `static/views/exam.html:12-18` | 7 个模块只有 6 个不同图标：`📖` 同时指「阅读」「词汇」，`🎧` 同时指「听力」「听力微训」 |
| 伴学抽屉底部 | 9 | `static/modals/drawer.html:384-399` | 3 个思考强度 + 6 个快捷指令挤在同一区域；`⚡`（彩色）与 `⚖`（文本默认，常呈单色）并排 |
| 写作侧栏 | 6 | `static/views/writer.html:178,189,202,222,239,269` | 6 个分区标题全部 emoji 前缀 |
| 角色选择 | 4 | `static/layout/companion.html:33-57` | `🦉 🐱 🦊 🤖` 四种画风/复杂度完全不同的 glyph |
| README 目录 | 10 | `README.md` 10 个 H2 | 10/12 个标题带 emoji，GitHub 侧边目录变成彩色符号条 |

### 1.6 注释里的 emoji（评审者视角）

`[实测]` 26 个 emoji 在源片段注释中（`static/js/cards.js:173,206,207,511,982`、`static/js/writer.js:319,604` 等）。它们对用户不可见，但**对 Review 的面试官/维护者可见**，是「AI 生成痕迹」最廉价、最无争议的清理项。

---

## 2. 可读性与跨平台损害

### 2.1 emoji 与现有字号体系冲突

`[实测]` `static/style.css` 的 font-size 分布：**11px × 78、12px × 63、10px × 24、13px × 33、14px × 29**。emoji 恰好大量出现在 11–14px 的标签里（`.sidebar-section-title`、`.a1-card-label`）。

`[来源]` Google Design 明确说明：Unicode 只定义码位，**每个平台用自己的字体绘制**（Apple Color Emoji / Segoe UI Emoji / Noto Color Emoji），风格与细节由各家决定。`[推断]` 在 11px 下，彩色 emoji 的细节（表情、纸张纹理、扬声器线条）基本糊成一团，且因字体度量不同，视觉高度与中文字重不匹配。

`[实测]` `static/style.css` 中 `.mob-icon { font-size: 1.125rem; line-height: 1; }`，旁边 `.mob-label` 是 `0.6875rem`（11px）等宽字体。`[推断]` `line-height: 1` + 平台 emoji 字体的不同 ascent/descent，会在 Windows 上产生上下裁切或基线偏移；这是「行高跳动」的直接来源（未在真机逐像素验证，见第 10 节）。

### 2.2 调色板失控

`[实测]` 86 个不同 emoji 天然携带 86 套颜色，而项目设计系统是 5 色 editorial 调色板（`static/css/tokens.css`）。`[推断]` 这导致：

- emoji 成为屏幕上饱和度最高的元素，抢走正文与 CEFR 色标的注意力；
- 无法响应主题色/暗色模式（emoji 不受 `currentColor` 控制）；
- 同一功能的图标在不同页面颜色不同（`📖` 是蓝色书、`📚` 是三本不同色的书）。

### 2.3 跨平台字形不一致

`[来源]` Windows 的 Segoe UI Emoji **不包含国旗图形**，会显示两位国家代码（微软社区答复亦确认）。

`[实测]` `static/js/a1_hoeren.js` 使用 `🇩🇪` / `🇨🇳`。`[推断]` 在项目的主力桌面平台 Windows 上，用户看到的是 `DE 听力原文` / `CN 原文对照`，而不是德国/中国国旗——一个德语学习 App 的语言标识在主力平台上「坏掉」，这是最具体的可读性损害。

`[实测]` 72 个 emoji 带 `U+FE0F`。`[来源]` Unicode 的 emoji presentation 规则允许同一码位以文本或彩色形态呈现；`[实测]` `drawer.html:384-386` 的 `⚡ / ⚖ / 🧠` 三个并排按钮里，`⚖` 默认是文本形态，另外两个是彩色形态，同一组控件内风格不统一。

### 2.4 语义碰撞：它已经不是一个图标系统

`[实测]` `static/views/exam.html:12-18` 的 7 个模块，图标与语义的映射是：

| 模块 | emoji | 冲突 |
| --- | --- | --- |
| 写作 | `📝` | 与「便签」(`drawer.html:32`) 同图标 |
| 听力 | `🎧` | 与「听力微训」(`exam.html:305`) 同图标 |
| 阅读 | `📖` | 与「词汇」(`exam.html:16`) 同图标 |
| 口语 | `💬` | 与「说句话」(`companion.html:127`) 同图标 |
| 词汇 | `📖` | 同上 |
| 听力微训 | `🎧` | 同上 |
| 长难句 | `✍️` | 与「写作」(`writer.html:76`) 同图标 |

`[推断]` 图标系统的第一原则是「同义同形、异义异形」；emoji 只有 86 个可用字符且语义宽泛，导致 **7 个模块只有 6 个不同图标、2 组语义碰撞**。这不是选得不好，是 emoji 作为图标系统的能力上限。

### 2.5 无障碍

`[实测]` 0 个 `aria-hidden`、0 个 `aria-label`。emoji 作为文本节点会被读屏器按名称播报（如「扬声器」「警告标志」），夹在中文句子里形成噪声。

`[来源]` W3C 技术 H86 专门给出 emoji 的文本替代方案；MDN 的 `img` role 文档也指出 emoji 对读屏用户「可能没有文本表示，或替代文本与上下文不符」。`[来源]` CHI 2020 论文《Emoji Accessibility for Visually Impaired People》记录了视障用户的实际困难：**尺寸太小难以辨认、颜色难以区分**。

`[推断]` 当前实现里，`🔊` 这类纯图标按钮的读屏名称来自 `title`（如「播放发音（快捷键 P）」），尚可；但正文里的 `⚠️ 发现 3 处语法疑点` 会先读「警告标志」再读中文，信息重复且打断节奏。

### 2.6 视觉重量无法统一

`[来源]` 图标字体/emoji 的笔画、圆角、内部细节由字体厂商决定；SVG 可以统一到 1.5px 描边、方头端点、`currentColor`。`[推断]` 项目当前是「1.5px 硬边框 + 2px 硬阴影」的 editorial 风格，而 emoji 是彩色 3D/扁平混合体，两者在视觉重量上天然冲突——这是「看起来像 AI 拼装」的底层原因之一。

---

## 3. 「AI 味」的成因

### 3.1 README 实测指标

`[实测]` `README.md`：226 行、14,364 字符、12 个标题、22 个项目符号、44 行表格、90 对粗体、98 个行内代码、56 个间隔号 `·`、6 个破折号、**2 个感叹号**。

| 指标 | 实测 | 判读 |
| --- | ---: | --- |
| 二级标题带 emoji | 10 / 12（83%） | **高**：模板化装饰的最强信号 |
| 标题带英文括注 | 9 / 12（75%） | **高**：`## 中文 (English)` 全篇同一模板 |
| 粗体密度 | 90 对 / 226 行 = 0.40/行 | **高**：「每句都重要」= 没有重点 |
| 表格行占比 | 44 / 226 = 19% | 中高：信息被切成大量等宽格子 |
| 间隔号 `·` | 56 | 中：badge 化标点，视觉噪声 |
| 感叹号 | 2 | **低**：不是问题 |
| 破折号 | 6 | 低：不是问题 |
| 段落长度 | 中位数 94.5 字符，标准差 283.5，最长 1257 | **不是「均匀」**：是一段 1257 字符的墙 + 大量短列表 |
| 营销形容词 | 一键 5、完整 5、核心 4、全面 2、智能 2、沉浸 2 | 中低：多数仍挂在具体功能上 |

### 3.2 六项成因逐项判定

| 成因 | 在本 README 的严重度 | 证据 |
| --- | --- | --- |
| emoji 滥用 | **严重** | 24 个 emoji；10/12 个 H2；7 个 blockquote callout；4 个平台表格单元 |
| 句式模板化 | **严重（标题层）** | 9/12 个 H2 是 `中文 (English)`；每个 feature bullet 都是「粗体标签 + 冒号 + 说明」 |
| 过度并列清单 | 中高 | 22 个 bullet + 44 行表格；功能段 6 条并列 |
| 感叹号 | 低 | 全文 2 个 |
| 空洞形容词 | 中低 | `一键`×5、`完整`×5，但多与具体动作绑定 |
| 均匀段落长度 | 低 | 段落长度方差很大，但存在单段 1257 字符的「墙」 |

### 3.3 外部依据

- `[来源]` 维基百科 WikiProject AI Cleanup 的访谈（IEEE Spectrum，2026-10）指出：AI 文本的痕迹已从「显眼套话」转向**结构特征**——偏爱三段式（rule of three）、消极平行结构（「不是 X，而是 Y」）、以及成体系的模板化排版；单条不足以定罪，累积起来才有意义。本 README 的「不是又一个…不用…」（`:10`）与 9/12 个同构标题正属于这一类。
- `[来源]` Microsoft Writing Style Guide：**大多数文本沟通中不要使用 emoji**；仅在短消息、只读一次的场合谨慎使用。README 是「会被反复阅读的文本」，正落在其「不要用」区间。
- `[来源]` 真实开源项目对照：本轮实际抓取了 `astral-sh/uv` 与 `BurntSushi/ripgrep` 的 GitHub 首页（2026-11-06）。两者的 H2/H3 **全部无 emoji**，靠 badge、代码块、短段落、明确链接组织信息；uv 的 README 甚至把「Highlights」写成 11 条纯文字 bullet。这说明「专业感」不依赖 emoji，反而依赖**信息密度与可扫描性**。
- `[来源]` W3C H86 与 MDN 的 `img` role 文档：emoji 需要显式的文本替代，否则读屏语义不可控。

### 3.4 判断

`[推断]` 这份 README 的「AI 味」约 **70% 来自格式模板、30% 来自措辞**，**内容层是健康的**。因此修复策略应是「去装饰 + 打破对称」，而不是重写内容：

1. 删除所有标题/表格/callout 的 emoji；
2. 把 9/12 个 `中文 (English)` 标题改成「只有需要给英文读者时」才保留括注，其余用纯中文；
3. 把 90 对粗体压到每节 ≤3 处；
4. 把 44 行表格压缩为 2–3 张真正需要对照的表；
5. 用 GitHub Alerts（`> [!NOTE]` / `> [!WARNING]`）替代「emoji + blockquote」。

`[来源]` GitHub 官方 changelog 确认 Alerts 是原生 Markdown 扩展，会由 GitHub 自己渲染图标与配色——既保留「提示」的视觉层级，又不把 emoji 写进正文，也不会被复制到其他渲染器时变成裸符号。

---

## 4. Emoji 替代方案对比

`[实测]` 当前静态资源：`static/js` 约 979KB、`static/style.css` 约 252KB、`static/` 全量约 2.5MB；已有字体全部是拉丁子集 woff2，**没有自带 emoji 字体**（所以 emoji 必然走系统字体）。`[实测]` 没有 CSP（全仓未搜到 `Content-Security-Policy`），inline SVG 不受限。`[实测]` `tools/sync_android_sources.py` 整棵 `static/` 复制到 Android assets；`static/sw.js` 为运行时缓存、无 precache 清单——新增静态 SVG 不需要改打包配置或 SW。

| 方案 | 体积 / 请求 | 可维护性 | 无障碍 | 构建链兼容 | 主题/颜色 | 适用位置 |
| --- | --- | --- | --- | --- | --- | --- |
| **纯排版**（文字、编号、线条、字号字重） | 0 字节 / 0 请求 | 最高：改文案即可 | 最好：本身就是文本 | 无影响 | 完全受 `currentColor` 控制 | 导航、分区标题、按钮、状态、列表符号（覆盖 70%+） |
| **Inline SVG** | 每个 0.3–1.5KB；20 个约 8–12KB 原始、3–4KB gzip `[推断]` | 中：SVG 混在模板里，需约定 `viewBox`/描边 | 好：`aria-hidden="true"` 或 `role="img"`+`<title>` | 好：片段内联，`build_index_html.py` 原样组装；无 CSP | 好：`fill/stroke: currentColor` | 图标按钮、状态图标、空状态 |
| **SVG sprite**（`<symbol>`+`<use>`） | 1 个文件 8–15KB，可缓存 | 中：集中管理，但改一个要动 sprite | 好：同 inline SVG | 好：文件放 `static/`，Android 整树复制；SW 运行时缓存 | 好 | 图标数量 >20 时 |
| **图标字体** | 1 个 woff2 15–40KB | 低：改图标要重新生成字体 | **差**：PUA 字符会被读屏念出乱码，必须手工隐藏 | 中：多一个 `@font-face` 与加载态 | 中：单色，受 `color` 控制 | 不推荐 |
| **CSS mask** | 每个图标 1 个 SVG 请求（或复用 sprite） | 中：CSS 里写 URL，图标不可内联改色 | 取决于宿主元素的 `aria-label` | 好：静态文件 | 好：`background-color` 即颜色 | 需要「图标随主题变色」且不想塞 DOM 时 |
| **Emoji（现状）** | 0 字节 | 最高（直接打字） | **差**：0 个 aria，读屏噪声 | 无 | **差**：不受控 | 不建议继续用于 UI/README |

### 4.1 选型结论（按位置）

`[推断]` 不存在「一个最佳方案」，应按位置选：

- **导航 / 分区标题 / 按钮 / 列表符号 / 状态文案** → 纯排版。项目已有衬线、无衬线、等宽三套字体与 editorial 分隔线，足够建立层级，成本为 0。
- **纯图标按钮（播放、删除、翻转、随机）** → inline SVG，统一 24×24 `viewBox`、1.5px 描边、`currentColor`；按钮必须有 `aria-label`。
- **空状态（5 处）** → 1 套 48–64px 的线性 SVG 或「大字 + 细线」排版空状态，二选一，不要混用。
- **伴学角色（4 个）** → SVG 角色（仓库已有 `docs/svg-character-spec.md` 与 SVG 上传能力），这是唯一值得投入插画预算的地方。
- **图标字体** → 不采用；无障碍与加载态都劣于 SVG。

---

## 5. 「生动活泼 + 呼吸感」的量化规范草案

### 5.1 现状诊断（为什么现在「闷」）

`[实测]` `static/style.css`：

| 维度 | 实测 | 问题 |
| --- | --- | --- |
| font-size | 11px×78、12px×63、10px×24、13px×33、14px×29… | 主体是 10–12px 的「小字海洋」，阅读正文只有少数几处 18px |
| line-height | 11 种值（1 / 1.2 / 1.3 / 1.35 / 1.4 / 1.45 / 1.5 / 1.55 / 1.6 / 1.7 / 1.95 / 2） | 没有节奏，行与行关系不可预期 |
| gap | 8px×43、6.4px×23、12px×22、5.6px×21、16px×16、4px×15… | 5.6 / 6.4 / 4.8 这类值不在任何网格上 |
| letter-spacing | 8 种值 | 等宽标签的字距没有统一规则 |
| border-radius | 2 / 3 / 4 / 6 / 8 / 10 / 12 / 50% / 999 | 与「硬边框 + 硬阴影」的 editorial 语言冲突 |
| 间距 token | `tokens.css` 中 **0 个** | 全靠局部硬编码 |
| 字号 token | `tokens.css` 中 **0 个** | 同上 |

`[来源]` Material 3 的 spacing 系统以 8dp 为基本单位（space100 = 8dp）；`[来源]` GEL 也采用 4px 基准、多数步进落在 8 的倍数。`[推断]` 当前 5.6/6.4/4.8 这类值无法形成可感知的节奏，是「看起来挤、又说不出哪里挤」的根因。

### 5.2 间距系统（建议新增到 `tokens.css`）

```css
/* 4px 基准，8pt 节奏；组件内部 ≤12，组件间 16–24，区块间 48–64 */
--sp-1: 4px;   --sp-2: 8px;   --sp-3: 12px;  --sp-4: 16px;
--sp-5: 24px;  --sp-6: 32px;  --sp-7: 48px;  --sp-8: 64px;  --sp-9: 96px;
```

| 用途 | 目标值 | 现状（示例） | 为什么 |
| --- | ---: | --- | --- |
| 图标与文字 | 8px | 6px / 0.35rem 混杂 | 8px 是可感知的最小「分离」 |
| 标签内边距 | 4px 10px | 1px 6px、2px 8px | 触感与点击面积 |
| 卡片内边距 | 20px（移动 16px） | 12px | 内容不再贴边，产生「呼吸」 |
| 卡片间距 | 16px（移动 12px） | 8px / 12px | 组件间距离 ≥ 组件内距离的 1.5 倍 |
| 区块间距 | 48px（移动 32px） | 24px / 32px | 与卡片间距形成 2–3 倍差 |
| 页面上下留白 | 64–96px | 40px 左右 | 首屏不顶天立地 |
| 页面左右 gutter | 32px（移动 20px） | 20px / 24px | 阅读列不贴边 |

`[来源]` NN/g 的 proximity 原则：元素越近越被视为同组；「组内间距 < 组间间距」是产生层级的最低成本手段。`[推断]` 把「区块间距 ≥ 3× 段落间距」作为硬规则，比逐页调 padding 更稳定。

### 5.3 字号与行高阶梯

```css
--fs-2xs: 11px;  /* 仅等宽元数据/大写 eyebrow */
--fs-xs:  12px;  /* UI 标签下限 */
--fs-sm:  13px;
--fs-md:  16px;  /* 正文默认 */
--fs-lg:  19px;  /* 精读正文 */
--fs-xl:  26px;  /* 小节标题 */
--fs-2xl: 34px;
--fs-3xl: 44px;
--fs-display: clamp(44px, 5.2vw, 78px); /* 沿用现有 hero */

--lh-display: 1.02;
--lh-heading: 1.15;
--lh-tight:   1.3;
--lh-ui:      1.45;
--lh-body:    1.6;
--lh-read:    1.9;
```

| 角色 | 字号 / 行高 | 现状 | 说明 |
| --- | --- | --- | --- |
| Hero 标题 | 44–78px / 1.02 | 已有 | 保持现有 display 级 |
| 区块标题 | 26px / 1.15 | 混用 1.2–1.35 | 层级靠字号，不靠加粗 |
| 卡片标题 | 19px / 1.3 | 1.1–1.2 偏紧 | 中文需要更大行高 |
| 正文 | 16px / 1.6 | 15px / 1.5 左右 | 正文不低于 16px |
| 精读正文 | 19px / 1.9 | 18px / 1.95 | 保持衬线长文节奏 |
| UI 标签 | 12px / 1.45 | 11px / 1 | 11px 只留给等宽大写 |
| 元数据 | 11px / 1.4 | 11px / 1–1.2 | 允许，但必须等宽大写 + 字距 0.08em |

`[来源]` Butterick's Practical Typography：屏幕正文字号不应低于 15–16px；行距为字号的 120–145%。`[来源]` WCAG 1.4.8 要求段内行距至少 1.5 倍、段间距至少为行距的 1.5 倍。`[推断]` 项目精读正文 1.95 已高于要求，问题是 UI 层 10–12px 过多，导致「正文舒服、界面局促」的割裂感。

### 5.4 行宽与留白比例

| 项 | 目标 | 依据 |
| --- | --- | --- |
| 德文精读行宽 | **60–68 字符**（约 640–700px @19px） | `[来源]` Butterick：45–90 字符；德文长词偏多，取下限更稳 |
| 中文正文行宽 | **32–38 字**（约 36em） | `[来源]` WCAG 1.4.8：CJK 不超过 40 字符 |
| 桌面内容列占视口 | 55–65% | `[推断]` 两侧留白 ≥ 18% 才有「页面」而非「面板」感 |
| 段落间距 | 1em（16–19px） | `[来源]` WCAG 1.4.8 段间距 ≥ 1.5× 行距的等效实践 |
| 区块上下留白 | 48–64px | 见 5.2 |
| 卡片留白 : 卡片间距 | ≥ 1 : 1.5 | `[来源]` NN/g proximity |

### 5.5 层级信号：一个元素只允许一种「分离手段」

`[实测]` 当前 badge/pill 常见「背景 + 边框 + 阴影 + 圆角」四件套同时出现（如 `.stat-badge` 类）。`[推断]` 这会让界面持续处于「高频噪声」状态。

建议规则：

1. **组内分隔**用 1px `--line-soft`；
2. **区块分隔**用 1.5–2px ink 线（沿用现有 `border-bottom: 1.5px solid var(--ink)`）；
3. **可点击卡片**用 2px 硬阴影 + hover 位移 1px，不再额外加背景色；
4. **状态**用 3px 左竖线 + 文字，不再同时加圆角胶囊 + 背景 + 阴影；
5. 圆角收敛为 `0 / 2px / 4px / 999px(pill)` 四档，删除 6/8/10/12 的中间值（除非是角色插画容器）。

### 5.6 动效（沿用现有 token，补齐节奏）

`[实测]` `tokens.css` 已有：`--dur-fast: 180ms`、`--dur-mid: 360ms`、`--dur-slow: 900ms`、`--ease-editorial`。

| 场景 | 时长 | 缓动 | 备注 |
| --- | ---: | --- | --- |
| hover / focus | 120ms | ease-out | 只改 `transform`/`opacity`/`border-color` |
| 按钮按下 | 80ms | linear | `translateY(1px)`，与硬阴影配合 |
| 开关 / chip 选中 | 180ms | `--ease-editorial` | 现有 fast |
| 抽屉 / 面板 | 320ms | `cubic-bezier(0.22,1,0.36,1)` | 进入略慢、退出 200ms |
| 首屏入场 | 500–700ms | 同上 | 列表 stagger 40ms，最多 5 项 |
| 伴学角色呼吸 | 3.2s，`ease-in-out`，无限循环 | — | 唯一允许的常驻动效 |

`[来源]` Material 3：emphasized 500ms（进出屏幕）、emphasized decelerate 400ms（进入）、emphasized accelerate 200ms（退出）、standard 300ms。`[来源]` WCAG 2.3.3 要求对交互触发的动效提供关闭方式。`[推断]` 项目已有 `--dur-slow: 900ms` 与 editorial 缓动，不需要推翻，只需**规定每种交互只能用哪一档**，并补 `prefers-reduced-motion: reduce` 的全局降级。

### 5.7 状态反馈：三通道，不靠颜色单打独斗

`[来源]` WCAG 1.4.1 要求不能只靠颜色传达信息。建议每个状态同时具备：

1. **文字**：`正确` / `错误` / `注意` / `待复习` / `已掌握`；
2. **颜色**：moss / cherry / mustard（现有 token）；
3. **形状或位置**：3px 左竖线，或下划线，或 2px 边框。

`[实测]` 现状 `static/js/cards.js:133` 用 `🎉`/`🛡️`/`🎴` 三种 emoji 表示三种卡片状态——用户必须先学会 emoji 的含义。改为文字徽记后，信息 self-evident，且可被读屏器正确朗读。

### 5.8 「克制」与「活泼」的平衡

**去掉 emoji 之后，界面靠什么保持不死板？** 答案不是「多加留白」这一件事，而是四个可量化的对比：

| 手段 | 具体做法 | 成本 |
| --- | --- | --- |
| 字体对比 | 衬线斜体（强调词） × 等宽大写（eyebrow/元数据） × 无衬线正文；同一屏最多 3 种角色 | 0（字体已存在） |
| 节奏对比 | 大留白区块（96px）+ 紧凑数据行（8px）；一张一弛 | 0（改间距 token） |
| 触感 | 2px 硬阴影、按下位移 1px、翻牌 3D、下划线从左展开 | 0（已有） |
| 局部插画 | 4 个伴学角色 + 5 处空状态，统一 1.5px 线稿 | 约 20–30KB SVG，一次性设计成本 |

**每屏只允许一个「高音量」元素**：要么一个 >34px 的 display 标题，要么一个彩色插画，要么一个强调色块；其余全部安静。`[推断]` 这比「每屏放 5 个 emoji」更能产生「活泼但不吵」的感觉。

**已有正例**：`static/views/home.html` 首屏没有 emoji，靠「小圆点 + `DAS LANGE SATZ` 等宽 eyebrow + 衬线大标题 + 一个斜体强调词 + `→`/`+` 两个排版符号」完成生动性。`static/layout/nav_desktop.html` 用「德文标签 + 中文标签」替代图标，也是可复用的范式。

---

## 6. 替换决策表

> 「代价」列只计**实现成本**，不含设计审美判断；「零」表示改文案/删字符即可。

| 位置 | 现在用什么 | 换成什么 | 为什么 | 代价 |
| --- | --- | --- | --- | --- |
| README 10 个 H2 | `## 🚀 快速启动 (Quick Start)` 等 | 纯文字标题；仅在面向英文贡献者时保留英文括注 | 标题 emoji 是 Reviewer 第一眼看到的「AI 模板」；9/12 同构标题强化机器感 | 零（纯删除/改写） |
| README 7 个 blockquote callout | `> 📖 …`、`> 🚀 …` | `> [!NOTE]` / `> [!WARNING]` 等 GitHub Alerts | 语义化、GitHub 原生渲染、复制到别处不会变裸符号 | 零（改 Markdown 语法） |
| README 平台表格 4 个单元 | `🪟 Windows`、`📱 Android` | `Windows` / `Android` / `macOS` / `Linux` 纯文字 | 文字已足够；国旗/平台 emoji 在 Windows 上还可能显示为代码 | 零 |
| 移动端底栏 8 个 | `📖 📊 🎧 ✍️ …` | 方案 A：等宽大写德文缩写（`LESEN`/`HÖREN`/`SCHREIBEN`）；方案 B：20px inline SVG 线稿 + 12px 中文标签 | 8 个 emoji 色板/笔画不可统一；底栏是「AI App」感最强的位置 | 方案 A 零；方案 B 约 8 个 SVG，1–2 天 |
| 桌面导航 3 个 | `🔍 检索`、`🧩 拆句`、`⚙️ 设置` | 直接删 emoji，保留文字（与同文件其他纯文字 tab 一致） | 同文件已有 9 个无 emoji tab，删掉即统一 | 零 |
| 考试模块宫格 7 个 | `📝 🎧 📖 💬 📖 🎧 ✍️` | `01–07` 等宽编号 + 中文名 + 一行德文副标题 | 7 个模块只有 6 个图标且语义碰撞；编号天然唯一、可排序 | 零（纯排版） |
| 按钮文案 49 个 | `🎲 随机练习`、`💾 保存作文` | 删 emoji，保留动词；危险操作改用颜色/位置区分 | 按钮文字已表达动作；emoji 只是语气 | 零 |
| 纯图标按钮 22 个 | `🔊`、`🗑️`、`🔀`、`▶` | 16/20px inline SVG，`aria-label`，`currentColor` | 唯一需要「图形」的地方；SVG 可统一描边并继承主题色 | 约 20 个图标，2–3 天 |
| 状态标记 64 个 | `⚠️ 发现 3 处疑点`、`🎉/🛡️/🎴` | 文字徽记（`注意`/`正确`/`错误`/`待复习`/`已掌握`）+ 3px 左竖线 + 颜色 | 现在用户要先学 emoji 语义；文字 + 形状 + 颜色三通道更稳 | 低（改模板与少量 CSS） |
| toast 32 个 | `❌ 仅支持 .svg`、`🔊 已开启` | 删 emoji；用 toast variant（success/error/info）+ 左侧 3px 色条 | toast 已有颜色与位置，emoji 重复表达 | 零或极低 |
| 分区标题 18 个 | `📊 语言水平与质量估测` | 纯文字 + 上方 1.5px ink 线或等宽编号 | 标题层级应由字号/线构成，不由 emoji 构成 | 零 |
| 列表符号 6 个 | `❖ 粘贴长文` | CSS `::marker`（4px 方块/短横）或 `—` | `❖` 是装饰性 glyph，且与 editorial 线语言不一致 | 极低（CSS） |
| 输入占位符 2 个 | `placeholder="🔍 搜索…"` | `搜索 A1 单词 / 释义 / 例句…` | 输入框本身已有搜索语义；占位符越短越易读 | 零 |
| 伴学角色 4 个 | `🦉 🐱 🦊 🤖` | inline SVG 角色（沿用 `docs/svg-character-spec.md`） | 这是唯一值得插画投入的地方；角色是产品人格，不是图标 | 4 个 SVG，约 8–12KB，2–4 天 |
| 空状态 5 处 | `✍️`/`🔍` 2–2.5rem 大字 | 统一空状态组件：48–64px 线稿 + 一句说明 + 一个主按钮 | 大号 emoji 是最显眼的「AI App」视觉；空状态是品牌露出位 | 5 个 SVG 或 1 套排版空状态，1–2 天 |
| 注释内 26 个 | `// 🎴 FRONT FACE` | 删除 emoji | 不影响用户，但影响 Reviewer 对代码专业度的判断 | 零 |
| 运行时 LLM 输出 | 未知（系统提示词未禁止） | 在 `COMPANION_AGENT_SYSTEM_PROMPT` 增加「不要使用 emoji」；前端可加兜底过滤 | 静态清理后，模型仍可能在回复里输出 emoji，破坏一致性 | 极低（一行提示词 + 可选过滤） |

`[未验证]` 最后一行：本轮只读了提示词（`delector/services/companion_agent.py:58-82`），没有实际调用模型统计输出中的 emoji 比例。

---

## 7. 实施路径（可直接开工）

### P0：零设计依赖清理（建议先做，1–2 天）

1. 删除 **382 个纯冗余 emoji**（`emoji + 中文` 形态），只改文案；
2. 删除 README 全部装饰 emoji，改 GitHub Alerts；
3. 删除 26 个注释内 emoji；
4. 删除 `❖` 列表符号，改 CSS `::marker`；
5. 删除 2 个输入占位符 emoji；
6. 桌面导航 3 个 emoji 直接删（同文件已有无 emoji 范式）。

**验收**：

- 扫描脚本输出 `visible = 141`（523 − 382，理论值；允许 ±5 的分类误差）；
- `README.md` emoji 计数 = 0；
- 不改任何布局/间距/组件结构，视觉 diff 只应出现「emoji 消失」；
- 不新增文件、不改 `build_index_html.py`。

**风险**：`📖` 这类「emoji 在句首、中文在句尾」的模板字符串需要逐条看，避免把「emoji 是唯一分隔符」的地方删成两段粘连。建议按 `file:line` 清单逐条过，而不是全局正则替换。

### P1：图标位与状态语义（3–5 天）

1. 为 22 个纯图标按钮建立 20 个 inline SVG（24×24 viewBox、1.5px stroke、`currentColor`），补 `aria-label`；
2. 64 个状态标记改为「文字 + 颜色 + 3px 左竖线」；
3. toast 改为 variant 样式，删除 emoji；
4. 移动端底栏先做**方案 A（德文缩写纯排版）**，成本最低；若评审认为不够活泼，再升级到 SVG 方案 B。

**验收**：

- 图标按钮有 `aria-label`，键盘可聚焦；
- 状态不只靠颜色（灰度截图仍可区分）；
- 移动端底栏在 320px 宽度下 8 项不换行、不截断。

### P2：系统与「呼吸感」（1–2 周）

1. 写入 5.2/5.3 的间距与字号 token；
2. 按 5.5 收敛层级信号与圆角；
3. 按 5.6 统一动效档位，补 `prefers-reduced-motion`；
4. 实现 4 个伴学角色 SVG + 5 处统一空状态；
5. 精读页行宽校准到 60–68 字符。

**验收**：

- 全站不再出现 5.6/6.4/4.8 这类非网格间距（可用 CSS lint/正则检查）；
- 10px 字号降为 0 或仅剩等宽装饰；
- Lighthouse/axe 无「emoji 无语义」类告警；
- 灰度截图下层级仍成立。

### 建议的推进顺序

`P0 → P1 的移动端底栏 → P2 的间距/字阶 → P1 的 SVG 图标 → P2 的角色与空状态`。

理由：P0 收益/成本比最高；底栏是「AI 感」最集中的位置，先做一个可视样板给评审；间距/字阶是后续所有视觉工作的地基；SVG 图标与角色可以并行，但不应阻塞地基。

---

## 8. 证据分级总表

| 结论 | 等级 | 依据 |
| --- | --- | --- |
| 523 个可见 emoji、380 个去重后源片段 emoji、86 个不同 emoji | 已实测 | 附录 A 脚本 |
| 382 个（73%）emoji 与中文同义冗余 | 已实测 | 1.4 节 |
| README 10/12 H2 带 emoji、9/12 带英文括注、2 个感叹号 | 已实测 | 3.1 节 |
| 11px×78、12px×63、11 种 line-height、8 种 letter-spacing | 已实测 | 5.1 节 |
| `tokens.css` 无间距/字号 token | 已实测 | `static/css/tokens.css` 全文 |
| 7 个考试模块只有 6 个不同图标，2 组语义碰撞 | 已实测 | 2.4 节 |
| Windows 不渲染国旗 emoji | 有来源支撑 | 微软社区答复（附录 B） |
| emoji 尺寸过小会损害视障用户识别 | 有来源支撑 | CHI 2020 论文 |
| 8pt/4px 间距节奏能提升一致性与可预期性 | 有来源支撑 | Material 3 Spacing、GEL |
| 45–90 字符行宽、120–145% 行距 | 有来源支撑 | Butterick |
| AI 文本的结构性痕迹（三段式、消极平行） | 有来源支撑 | IEEE Spectrum / WikiProject AI Cleanup |
| 「emoji 在 11px 下糊成一团」 | 我的推断 | 基于字号分布 + 字体渲染来源 |
| 「每屏一个高音量元素」能兼顾活泼与克制 | 我的推断 | 设计判断，未做用户测试 |
| 20 个 SVG 约 3–4KB gzip | 我的推断 | 按单图标 0.3–1.5KB 估算 |
| 运行期 LLM 是否输出 emoji | 未验证 | 只读了提示词，未调用模型 |
| `line-height:1` 是否导致 Windows 裁切 | 未验证 | 未在真机逐像素验证 |
| 去掉 emoji 后用户是否真的觉得「更专业」 | 未验证 | 无用户实验 |

---

## 9. 这次调研没能回答的问题

1. **用户感知**：没有做 A/B 或访谈，无法证明「去 emoji 后用户觉得更专业/更愿意留存」。本报告的「AI 味」判断基于设计规范、开源对照与评审视角，不是用户实验结论。
2. **Android WebView 的实际渲染**：没有在真机/模拟器上截取 `🇩🇪`、`⚠️`、`🗑️` 的实际字形与基线。跨平台结论中，Windows 国旗有来源支撑，Android 的具体表现属于推断。
3. **暗色模式**：没有验证 SVG 图标与现有暗色主题的对比度；`currentColor` 方案理论上可行，但未逐图标检查。
4. **动态生成的 emoji**：伴学 Agent、AI 润色、后端返回的 Markdown 是否含 emoji，未统计。需要在 P0 后用真实调用采样。
5. **emoji 与屏幕阅读器的实际播报**：没有用 NVDA/VoiceOver 实测中文语境下的播报序列；W3C/CHI 的结论是通用性的，具体到本项目的噪声程度未量化。
6. **设计成本**：4 个角色 + 5 个空状态的插画工时没有评估，只给了体积估算。
7. **「呼吸感」的阈值**：96px 区块间距、60–68 字符行宽是规范建议值，未在 DeLector 的真实内容（长德语复合词、大量表格）上做视觉校准；需要在 P2 用真实页面微调。
8. **GitHub Alerts 的降级**：在非 GitHub 渲染器（如某些 IDE Markdown 预览）中，`> [!NOTE]` 会退化为普通 blockquote；这是可接受的降级，但未逐一验证。

---

## 附录 A：扫描口径与复现

`[实测]` 脚本对 `README.md` 与 `static/**/*.{html,js,css}` 逐字符扫描，核心逻辑：

```python
EMOJI_RANGES = [
    (0x1F000, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF),
    (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF),
    (0x203C, 0x203C), (0x2049, 0x2049), (0x2139, 0x2139),
    (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
    (0xFE0F, 0xFE0F), (0x200D, 0x200D),
]
# 相邻 emoji 码位合并为一个簇；FE0F/200D 不单独计数
# HTML/JS/CSS 注释按行内上下文排除
# index.html 单独统计，不与源片段相加
```

- 统计日期：2026-11-06；仓库 HEAD：`b632859`（本轮工作树存在其他会话的未跟踪文件，未改动）。
- 分类为启发式（按行内上下文与选择器关键词），误差约 ±5%；`⭐` 2 例被归入排版符号。
- 复现时建议把脚本放在仓库外（如临时目录），避免污染工作树。

## 附录 B：外部来源

**无障碍与 emoji**

- W3C WAI, *H86: Providing text alternatives for emojis, emoticons, ASCII art, and leetspeak*：<https://w3c.github.io/wcag/techniques/html/H86>
- MDN, *ARIA: img role*（含 emoji 示例）：<https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/img_role>
- W3C Design System, *SVG icons*（`aria-hidden="true" focusable="false"` 模式）：<https://design-system.w3.org/styles/svg-icons.html>
- Tigwell, Gorman, Menzies, *Emoji Accessibility for Visually Impaired People* (CHI 2020)：<https://eprints.bournemouth.ac.uk/33854/1/tigwell-gorman-menzies-CHI2020.pdf>
- W3C, *Understanding SC 2.5.8: Target Size (Minimum)*：<https://w3c.github.io/wcag/understanding/target-size-minimum>
- W3C, *Understanding SC 2.3.3: Animation from Interactions*：<https://www.w3.org/WAI/WCAG21/Understanding/animation-from-interactions.html>

**排版与节奏**

- Butterick's Practical Typography, *Line length*：<https://practicaltypography.com/line-length.html>
- Butterick's Practical Typography, *Line spacing*：<https://practicaltypography.com/line-spacing.html>
- W3C, *Understanding SC 1.4.8: Visual Presentation*：<https://w3c.github.io/wcag/understanding/visual-presentation>
- Material Design 3, *Spacing*（8dp 基准，space100 = 8dp）：<https://m3.material.io/styles/spacing>
- Material Design 3, *Easing and duration*：<https://m3.material.io/styles/motion/easing-and-duration>
- NN/g, *Proximity Principle in Visual Design*：<https://www.nngroup.com/articles/gestalt-proximity>
- MDN, *text-wrap*（`balance` / `pretty`）：<https://developer.mozilla.org/en-US/docs/Web/CSS/text-wrap>

**emoji 跨平台与「AI 味」**

- Google Design, *Emoji Evolution: From Fun to Global Language*（各平台各自渲染）：<https://design.google/library/the-evolution-of-emoji>
- Microsoft Q&A, *Windows 10: Font "Segoe UI Emoji" does not support country flag emojis*：<https://learn.microsoft.com/de-de/answers/questions/3782465/windows-10-font-segoe-ui-emoji-does-not-support-co>
- Microsoft Writing Style Guide, *emoticons, emoji*：<https://learn.microsoft.com/zh-cn/style-guide/a-z-word-list-term-collections/e/emoticons-emoji>
- IEEE Spectrum, *Inside Wikipedia's Cleanup of AI-Generated Content*：<https://spectrum.ieee.org/wikipedia-wikiproject-ai-writing-cleanup>
- GitHub Changelog, *New Markdown extension: Alerts*：<https://github.blog/changelog/2023-12-14-new-markdown-extension-alerts-provide-distinctive-styling-for-significant-content/>
- 真实开源对照（本轮抓取，H2/H3 均无 emoji）：<https://github.com/astral-sh/uv>、<https://github.com/BurntSushi/ripgrep>

**图标方案**

- CSS-Tricks, *Icon Fonts vs SVG*（图标字体局限）：<https://css-tricks.com/icon-fonts-vs-svg/>
- icojoy, *Why SVG Icons Have Overtaken Icon Fonts*（PUA 与读屏问题）：<https://icojoy.com/blog/svg-icons-overtake-icon-fonts-2026/>

## 附录 C：配套原型

`docs/research/2026-11-06-emoji-vs-typography-prototype.html` 是一个**独立静态页**，不参与 `tools/build_index_html.py` 的组装，不被 `static/index.html` 引用，也不进入 Android 包。它用三列并排展示：

1. **现状**：emoji 版底栏、考试宫格、状态行、toast、空状态；
2. **仅删 emoji**：同一结构，只删除装饰；
3. **排版增强**：应用本报告 5.2–5.6 的间距/字阶/动效/状态三通道，并用可切换的 8pt 网格辅助线说明「呼吸感从哪来」。

原型只用于评审沟通，不作为实现代码。

---

_本报告只做调研，未修改任何前端代码、README、CSS/JS、构建脚本或 Android/后端文件。_
