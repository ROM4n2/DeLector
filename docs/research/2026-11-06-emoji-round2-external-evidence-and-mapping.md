# DeLector 前端去 Emoji 第二轮：外部证据与逐项映射

> 日期：2026-11-06　|　性质：决策前调研（不改代码）　|　上游：[第一轮调研](2026-11-06-emoji-and-ai-tone-frontend-research.md)
> 本轮目标：用**真实产品与真实代码**回答「下一步到底该改哪一处」，而不是复述设计原则。
> 证据标记：`[A]` 一手抓取/实测（含 URL 或 file:line）｜`[B]` 官方规范/设计系统｜`[C]` 社区材料｜`[U]` 未验证

---

## 0. 结论先行

1. **6 个同类产品里，5 个落地页正文零 emoji。** Duolingo、Babbel、LingQ、Readlang、Migaku 均为 0；只有 Language Reactor 在营销文案里堆了 30+ 个 emoji。DeLector 目前的写法更像 Language Reactor，而不是它想对标的「学术工具」。[A]
2. **它们的「活泼」没有一个是靠 emoji 实现的。** Duolingo 靠角色插画与游戏化，Babbel 靠摄影 + 3 个专用 SVG 图标，LingQ/Readlang 靠产品截图，Migaku 靠可交互 demo。共同点是：**信息密度低、每屏只讲一件事、CTA 重复但文案极短**。[A]
3. **6 个工程型开源 README 的标题 emoji 数为 0/6。** uv、ripgrep、Zed、bat、tldraw、Supabase 全部零标题 emoji；5/6 全篇零 emoji。它们靠「代码块 + 可验证数字 + 反方观点」建立可信度，ripgrep 甚至专门写了一节 `Why shouldn't I use ripgrep?`。[A]
4. **上一轮有两处数字需要更正**：`aria-label` 不是 0（源片段 11 处，只是没有一处用在 emoji 上）；README 不是「10/12 标题带 emoji」，而是 **10/10 个二级标题全带 emoji**。口径差异见 §1.4。[A]
5. **最该先改的不是「删 emoji」，是三处会直接误导用户的语义碰撞**：7 个考试模块只有 6 个不同图标、`🇩🇪/🇨🇳` 在 Windows 上退化为 `DE/CN`、状态用单个 emoji 承担全部语义。[A]

---

## 1. 同类产品实测

### 1.1 方法与边界

- 抓取时间：2026-11-06，均为未登录的公开落地页（WebFetch → 可读文本）。[A]
- **只统计产品自身文案**，用户评论里的 emoji 不计入（Migaku 的 testimonial 有 🙏🔥，属用户生成内容）。
- **不能观察到的**：登录后的应用内界面、实际留白数值、动效曲线。这些标 `[U]`，不写成结论。原因见 §6。

### 1.2 逐项实测

| 产品 | 落地页 emoji | 图标/插画载体 | 「活泼」来源 | 证据 |
|---|---|---|---|---|
| Duolingo（中文站） | **0** | 6 张插画/截图；无图标字体 | 绿色猫头鹰吉祥物、游戏化措辞（「闯关升级」「大赚经验」）、短句 CTA | [duolingo.com](https://www.duolingo.com/) [A] |
| Babbel | **0** | **3 个独立 SVG 文件**：`Medal.svg`、`Lightbulb.svg`、`Users.svg` | 大幅摄影 + 每节 1 个标题 + 1 段 2 句文案；证据用「92%」「25m」这类数字 | [babbel.com](https://www.babbel.com/) [A] |
| LingQ | **0** | 6 张 `.webp` 场景插画 | 同一句 CTA「开始免费试用！」重复 6 次；每节一句话 | [lingq.com](https://www.lingq.com/) [A] |
| Readlang | **0** | 产品截图 + 平台图标 | 首屏直接给可点击的西班牙语样张；定价表信息密度高但没有装饰符 | [readlang.com](https://readlang.com/) [A] |
| Language Reactor | **≈30**（含重复的 `➜`/`🎧`） | emoji 直接充当功能图标（`📑Books`、`🧠What to Learn`、`🎴Export to Anki`） | emoji + 感叹号 + 口语化标题（「Language Superpowers」） | [languagereactor.com](https://www.languagereactor.com/) [A] |
| Migaku | **0**（正文） | 扩展真实 UI 截图 + 可交互 demo | 把产品界面本身当插图；用「What the heck is Migaku?」这种自嘲式标题 | [migaku.com](https://www.migaku.com/) [A] |
| Anki | 仅取到导航（页面 500） | 纯文字导航：Docs / Forums / AnkiWeb / Add-Ons / Shared Decks | 无 | [apps.ankiweb.net](https://apps.ankiweb.net/) [A，受限] |

### 1.3 观察（可证伪的陈述）

- **Babbel 的图标是「一个用途一个文件」**：`Medal.svg` 只用于「Learn Fast」，`Lightbulb.svg` 只用于「Proven Results」，`Users.svg` 只用于「Language Experts」。这正是 DeLector `exam.html` 缺的东西——那里 7 个模块共用了 6 个 emoji。[A]
- **Duolingo / LingQ / Readlang 的每节结构都是「1 标题 + ≤2 句正文 + 1 图/1 CTA」**。DeLector README 的段落最长 1257 字符（第一轮实测），是它们的 5–10 倍。[A]
- **Language Reactor 证明了「emoji 多」不等于「AI 味」**：它是一个真实运营多年、200 万用户的产品。但它面向的是消费级语言爱好者，标题是「Language Superpowers」。DeLector 面向备考读者，同一套语气会直接冲突。[A + 推断]

### 1.4 与上一轮的数字口径更正

| 指标 | 上一轮 | 本轮复算 | 差异原因 |
|---|---|---|---|
| README 二级标题带 emoji | 10/12（83%） | **10/10（100%）** | 上一轮把 H1 与 H3 计入分母；实际 `##` 共 10 个，全部带 emoji |
| `static/` 源片段 `aria-label` | 0 | **11**（不含生成物 `index.html`） | 上一轮只扫了 emoji 邻近行；全量扫描可查到 11 处，但**没有一处作用于 emoji/图标** |
| `aria-hidden` / `sr-only` | 未单独报 | **0 / 0** | 与上一轮结论一致 |
| `title=` 属性 | 25 | **154**（源片段） | 上一轮只统计了 emoji 所在行 |

> 结论不变的部分：`382 / 523 = 73%` 可删、`83` 个信息载体、`72` 个 `U+FE0F`。变的是「无障碍完全为零」这句话——准确说法是「**有 11 处 aria-label，但零处服务于字形符号；aria-hidden 与 sr-only 才是真的零**」。

---

## 2. 工程型开源 README 实测

### 2.1 量化对照

用 GitHub API 直接取 `README.md` 原文，脚本统计（复现见附录）。

| 项目 | 行数 | 标题数 | 标题带 emoji | 全篇 emoji | 表格行 | 粗体对 | 感叹号 |
|---|---:|---:|---:|---:|---:|---:|---:|
| uv | 326 | 22 | **0** | **0** | 2 | 0 | 3 |
| ripgrep | 541 | 15 | **0** | **0** | 36 | 38 | 7 |
| Zed | 48 | 6 | **0** | **0** | 0 | 1 | 3 |
| bat | 947 | 85 | **0** | **0** | 16 | 7 | 14 |
| tldraw | 139 | 12 | **0** | **0** | 0 | 14 | 0 |
| Supabase | 288 | 7 | **0** | **4**（⚡💚） | 0 | 1 | 17 |
| **DeLector** | **226** | **11** | **10** | **22** | **44** | **90** | **2** |

> DeLector 的 emoji 密度是这 6 个项目的 5 倍以上；粗体密度（90 对 / 226 行）是 uv 的「无穷倍」、ripgrep 的 3.4 倍。**「每段都在用力」是比 emoji 更准的 AI 味代理指标。**

### 2.2 段落级观察

**ripgrep：用「反方观点」建立可信度。** README 同时有 `Why should I use ripgrep?` 与 `Why shouldn't I use ripgrep?`，后者明确写「如果你需要 POSIX 通用工具，用 grep」。[A]

> 对应 DeLector：[README.md:105](file:///d:/Code/DeLector/README.md#L105) 的「工程取舍」已经做对了方向（每条带出处、带数字），但缺一节「**什么场景不该用 DeLector**」。这比删 22 个 emoji 更能提升面试官信任。

**uv：标题即目录，正文即链接。** `## Highlights` 下 9 条 bullet，每条一个能力 + 一个链接，全篇零粗体。[A]

> 对应 DeLector：[README.md:94](file:///d:/Code/DeLector/README.md#L94) 的「核心特性」6 条 bullet 全用 `**加粗**：` 开头，视觉重量均匀，读者无法判断哪条最重要。

**Zed：README 只有 48 行。** 安装、开发、贡献、许可各两三行，其余全部外链 docs。[A]

> 对应 DeLector：226 行里 [README.md:55-73](file:///d:/Code/DeLector/README.md#L55-L73) 的多平台下载表把 macOS/Linux/Android 的细节全铺在首页。可下沉到 `docs/agents/ops.md`（已存在该文件，见 [README.md:50](file:///d:/Code/DeLector/README.md#L50)）。

**bat / tldraw：用截图承担「活泼」。** bat 每个特性配一张终端截图；tldraw 用深浅色双 hero 图。[A]

> 对应 DeLector：[README.md:20-23](file:///d:/Code/DeLector/README.md#L20-L23) 已有两张产品截图，方向正确；但它们在 8 个徽章之后才出现，首屏视觉重心被徽章占满。

---

## 3. 图标系统与无障碍基线

### 3.1 真实项目的取舍证据

| 项目 | 做法 | 可引用的原话/事实 | 对 DeLector 的含义 |
|---|---|---|---|
| Babbel | 独立 SVG 文件，一图一义 | 页面直接加载 `Medal.svg` / `Lightbulb.svg` / `Users.svg` [A] | 图标要能被单独替换、单独计数；emoji 做不到 |
| GitHub Primer | Octicons：手工维护的 SVG 图标集，按 Symbols/Objects/Developer 分类 | 「A scalable set of icons handcrafted by GitHub」[B] [链接](https://primer.style/octicons/) | 图标需要命名体系；DeLector 的 📖 同时表示「阅读」和「词表」就是命名缺失 |
| GOV.UK Design System | **大多数情况不用图标**；用了必须配可见文字标签；**一个图标不得表示两件事** | 「Avoid using icons in most cases… Do not use a single icon to represent more than one thing.」[B] [链接](https://design-system.service.gov.uk/styles/images/) | 直接命中 `exam.html` 的 6/7 碰撞 |
| W3C WAI | 装饰性图像用空 `alt` 或 CSS 背景；不要留空 `alt` 属性 | 「a null (empty) alt text should be provided (`alt=""`)」[B] [链接](https://www.w3.org/WAI/tutorials/images/decorative/) | 装饰性 glyph 应移出可访问性树，而不是让屏幕阅读器读「书」 |
| MDN | `aria-hidden="true"` 用于隐藏纯装饰图标；不得用于可聚焦元素 | 「Purely decorative content, such as icons or images」[B] [链接](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-hidden) | DeLector 目前 `aria-hidden` 为 0，所有装饰 emoji 都会进入可访问性树 |

### 3.2 最低限度可执行清单（只列 6 条，不写规范大全）

1. **装饰性 emoji 一律删；若因视觉需要保留图形，改为 CSS 背景或 `aria-hidden="true"` 的 SVG。** 判据：旁边已有文字。
2. **图标按钮必须有可访问名**：`<button aria-label="关闭">` + 可见「×」时，给「×」加 `aria-hidden="true"`，避免读出「times」。
3. **一个图标只表示一件事。** 做不到就删图标、改用编号或纯文字（GOV.UK）。
4. **纯文字标签优先于 `title=`  tooltip。** `title` 在触屏与键盘上不可靠，且不能替代 `aria-label`。
5. **状态不能只靠颜色或只靠字形。** 至少「文字 + 颜色」两通道；DeLector 现有 `✅/❌` 是单通道。
6. **不要用国旗表示语言。** Windows 的 Segoe UI Emoji 不渲染区域指示符，会退化为 `DE`/`CN`。[第一轮已引微软社区来源]

> 这 6 条覆盖了 DeLector 当前 0 处 `aria-hidden` 与 83 个信息载体里需要保留的部分；不需要引入 axe-core 或全量无障碍审计。

---

## 4. 对 DeLector 的逐项映射

> 每条都写清「改哪、改完会怎样」。`适用性` 列区分「直接照做 / 部分适用 / 不适用」。

| # | 外部结论 | DeLector 位置 | 具体改动 | 改了会怎样 | 适用性 |
|---|---|---|---|---|---|
| 1 | 一图一义（GOV.UK/Babbel） | [exam.html:12-18](file:///d:/Code/DeLector/static/views/exam.html#L12-L18)：7 个模块用 📝🎧📖💬📖🎧✍️，📖 与 🎧 各重复一次 | 删 emoji，改 `01`–`07` 编号 + 中文 + 德文副标题（原型 C 列已画） | 7 个模块可被逐一点名；消除「📖 到底是阅读还是词表」的歧义 | 直接照做 |
| 2 | 图标 + 可见文字（GOV.UK） | [nav_mobile.html:7,15,23,31,39,47,55,63](file:///d:/Code/DeLector/static/layout/nav_mobile.html#L7) 8 个 tab 全部「emoji + 中文」 | emoji 是冗余的，直接删；保留文字，用 2px 下划线表示 active | 底栏从「儿童 App」变「工具」；可读性不降（文字本来就在） | 直接照做 |
| 3 | 单字形不足以承载状态 | [cards.js:133](file:///d:/Code/DeLector/static/js/cards.js#L133) 三态 `🎉/🛡️/🎴` 无文字 | 改为文字徽章 + 颜色 + 3px 左竖线（原型 C 列） | 色盲用户与截图场景仍可辨；状态可被搜索/朗读 | 直接照做 |
| 4 | 装饰性 glyph 应移出可访问性树 | [writer.js:405](file:///d:/Code/DeLector/static/js/writer.js#L405) `⚠️ 发现 N 处语法疑点` | 删 ⚠️，保留句子；用琥珀色左竖线 + 「疑点」标签 | 屏幕阅读器不再读「warning sign」；视觉层级由颜色承担 | 直接照做 |
| 5 | 国旗非跨平台可靠 | [a1_hoeren.js:508-509](file:///d:/Code/DeLector/static/js/a1_hoeren.js#L508-L509) `🇩🇪 听力原文` / `🇨🇳 原文对照` | 改为等宽大写 `DE` / `ZH` 文本标签 | Windows 主力平台不再显示成 `DE`/`CN` 方块；三端一致 | 直接照做（修 bug） |
| 6 | 大字号 emoji 是最强的 AI 视觉信号 | [cards.js:1176](file:///d:/Code/DeLector/static/js/cards.js#L1176) 2.5rem 📡/🧭；[writer.js:815](file:///d:/Code/DeLector/static/js/writer.js#L815) 2rem ✍️；[a1_cards.js:382](file:///d:/Code/DeLector/static/js/a1_cards.js#L382)、[:508](file:///d:/Code/DeLector/static/js/a1_cards.js#L508) 2.5rem 🔍 | 换成排版空状态：细线 + 衬线标题 + 一句德文/中文说明 + 一个文本按钮 | 空状态仍有「设计感」，且不再像随手贴的 emoji | 直接照做 |
| 7 | 导航文字化（Duolingo/Babbel） | [nav_desktop.html](file:///d:/Code/DeLector/static/layout/nav_desktop.html) 已有 3 个 emoji、其余纯文字 | 把仅剩的 🔍/🧩/⚙️ 也删掉，与其余 tab 一致 | 桌面导航已经是正确样板，改造成本最低 | 直接照做 |
| 8 | 角色是品牌资产，不是装饰 | [companion.html:17,33,41,49,57](file:///d:/Code/DeLector/static/layout/companion.html#L17) 🦉🐱🦊🤖 | 走 `docs/svg-character-spec.md` 换成 SVG 角色；这是唯一建议保留「图形角色」的地方 | 保留产品记忆点；但需要设计投入（4 个角色 × 3 表情） | 部分适用，需拍板 |
| 9 | README 标题零 emoji（6/6） | [README.md:32,55,75,94,117,133,166,190,210,224](file:///d:/Code/DeLector/README.md#L32) 10/10 个 H2 带 emoji | 删 emoji；保留「中文 (Deutsch)」中真正是术语的部分，去掉英文括注 | 首屏从「营销页」变「技术文档」；目录仍可读 | 直接照做 |
| 10 | 粗体密度应反映重要性 | [README.md:94-103](file:///d:/Code/DeLector/README.md#L94-L103) 6 条特性全部 `**加粗**：` | 只给每条的第一个名词加粗，或全不加粗，改由列表顺序表达优先级 | 读者能看出哪条是核心；降低「每句都在喊」的观感 | 直接照做 |
| 11 | 「不该用」章节建立信任（ripgrep） | [README.md:105](file:///d:/Code/DeLector/README.md#L105)「工程取舍」 | 增一节「什么场景不该用 DeLector」（如：只想背单词、不需要句法分析） | 面试官看到边界感；比任何形容词都可信 | 直接照做 |
| 12 | 首屏视觉重心 | [README.md:3-14](file:///d:/Code/DeLector/README.md#L3-L14) 8 个徽章在标题之前 | 徽章下移到「技术栈」附近；首屏只留标题 + 一句话 + 两张截图 | 首屏先回答「这是什么」，而不是「CI 过了吗」 | 直接照做 |
| 13 | 功能性图标在熟练用户场景仍有效（GOV.UK 自身让步） | `static/` 全站 | 不搞「全站零图标」；保留 ≤12 个功能图标并全部配文字 | 避免把「去 emoji」做成「去视觉」 | 部分适用 |

---

## 5. 明确「不适用」的结论

| 外部做法 | 为什么不适用于 DeLector |
|---|---|
| Duolingo 的游戏化（连胜、经验值、等级） | 用户目标是歌德/德福考试，且产品定位是「学术级精读工作台」；游戏化会与 `Academic Modern Editorial` 视觉语言冲突。只借用「角色插画」这一项。 |
| Babbel 的大幅人物摄影 | DeLector 是文本密集型工具，摄影会增加体积、拉低信息密度，且无法说明功能。 |
| Language Reactor 的 emoji 营销体 | 它面向消费级语言爱好者，标题是「Language Superpowers」；DeLector 的用户是备考读者与面试官。**这是反例，不是范本。** |
| GOV.UK「大多数情况不用图标」 | GOV.UK 自己留了例外：「case working systems, where users are familiar with the interface and return to it frequently」。DeLector 正是高频回访的 case-working 工具，所以**不能全删功能图标**。 |
| Material 8dp 网格全站硬套 | 桌面端高密度表格（台账、词表）需要 4px 级微调；8dp 适用于触控目标，不适用于所有内边距。 |
| 「所有 emoji 都换成 SVG」 | 73% 是冗余装饰，换成 SVG 只是把噪声换成更贵的噪声。先删，再补。 |

---

## 6. 本轮没能回答的问题

1. **登录后的应用内界面**：Duolingo/Babbel/LingQ 的练习界面需要账号，本轮只看到落地页。它们的「应用内是否用 emoji 做状态标记」我没有证据。`[U]`
2. **真实留白数值**：本机没有可用的 Chrome/Edge 调试实例（`chrome-devtools` 报找不到 Chrome），无法读取商业站的 computed padding/line-height。本轮关于「留白大」的判断来自页面结构（每节 1 标题 + ≤2 句），不是像素测量。`[U]`
3. **图标方案的体积实测**：没有把 83 个 SVG 真正内联进项目称重；报告里的 0.3–1.5KB/个是行业常见区间，不是本项目实测。`[U]`
4. **屏幕阅读器实际朗读**：没有跑 NVDA/VoiceOver 实录；对 emoji 朗读的结论依赖 W3C/MDN 与第一轮引用的 CHI 2020 论文。`[U]`
5. **`title=` 154 处的逐条用途**：只做了总数统计，没有区分「表单提示」「图标说明」「JS 拼装」。`[U]`
6. **Android WebView 对 inline SVG 的渲染差异**：构建链会整树复制 `static/`（[sync_android_sources.py:84,117](file:///d:/Code/DeLector/tools/sync_android_sources.py#L84)），但未在真机验证 SVG 的 `currentColor` 继承。`[U]`

---

## 附录 A：复现方式

- README 统计：GitHub Contents API 取原文 → Python 正则统计标题/emoji/表格/粗体/感叹号。脚本：`%TEMP%\readme_analyze.py`
- DeLector 统计：遍历 `static/`（排除生成物 `index.html`）→ 统计每文件 emoji、密度最高行、`aria-*`/`title=`。脚本：`%TEMP%\delector_check2.py`
- 产品页：WebFetch 抓取落地页文本；emoji 计数排除 `➜`（U+279C，排版符号）。

## 附录 B：外部来源

| # | 来源 | 层级 | 用途 |
|---|---|---|---|
| 1 | https://www.duolingo.com/ | A | 零 emoji、插画驱动 |
| 2 | https://www.babbel.com/ | A | 零 emoji、3 个 SVG 图标 |
| 3 | https://www.lingq.com/ | A | 零 emoji、webp 插画 |
| 4 | https://readlang.com/ | A | 零 emoji、产品截图 |
| 5 | https://www.languagereactor.com/ | A | 30+ emoji 反例 |
| 6 | https://www.migaku.com/ | A | 零 emoji、可交互 demo |
| 7 | https://apps.ankiweb.net/ | A（受限） | 纯文字导航 |
| 8 | https://github.com/astral-sh/uv | A | README 零 emoji、0 粗体 |
| 9 | https://github.com/BurntSushi/ripgrep | A | 「Why shouldn't I use」章节 |
| 10 | https://github.com/zed-industries/zed | A | 48 行极简 README |
| 11 | https://github.com/sharkdp/bat | A | 截图承担活泼 |
| 12 | https://github.com/tldraw/tldraw | A | 12 个短 H2、零 emoji |
| 13 | https://github.com/supabase/supabase | A | 唯一 4 个 emoji 的反例 |
| 14 | https://design-system.service.gov.uk/styles/images/ | B | 一图一义、图标配文字 |
| 15 | https://www.w3.org/WAI/tutorials/images/decorative/ | B | 装饰图空 alt |
| 16 | https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-hidden | B | 装饰图标 aria-hidden |
| 17 | https://primer.style/octicons/ | B | 命名化 SVG 图标集 |
