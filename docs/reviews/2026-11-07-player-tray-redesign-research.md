# 底部音频托盘重构调研（2026-11-07）

> 只读调研 + 外部实测。**未改 `static/` 下任何文件**，未跑 pytest，未碰 ADR 与计划文件。
> 证据截图：`_artifacts/2026-11-07-player-tray-shots/`（未跟踪，不入 git）。
> 证据分级：`[A]` 本机实测 · `[A 受限]` 实测但只有部分控件 · `[B]` 官方文档 · `[U]` 未验证。

---

## 0. 判据修正：第四批把 `player_and_tooltip.html:52/60` 的 👩/👨 判错了

### 0.1 事实

第四批去字形把这处判为「相邻已有文字、安全删除」。删除后，`static/modals/player_and_tooltip.html:46-61` 只剩：

```html
<button id="voice-btn-katja" class="voice-btn active" title="清脆自然女声 (Katja)">
  <span class="vb-lbl">Katja</span>
</button>
```

问题出在 [style.css:3419-3431](file:///d:/Code/DeLector/static/style.css#L3419-L3431)：

```css
/* 声音按钮手机上只留图标（省出 ~130px 让位给模式按钮） */
.voice-btn { min-width: 44px; height: 40px; padding: 0; font-size: 0; }
.voice-btn .vb-ico { font-size: 1.1rem; line-height: 1; }
.voice-btn .vb-lbl { display: none; }
```

即：**「相邻的文字」在源码里存在，但在 ≤768px 的断点上被 CSS 关掉了**。手机端唯一可见的载体就是 `.vb-ico` 里的 emoji；emoji 一删，按钮退化成 44×40 的纯色块。实测（430px，见 §1.2）：两个按钮 `font-size: 0px`、`.vb-lbl` 的 `display: none`，渲染结果就是一个黑块 + 一个米块，与用户截图完全一致（[current-tray-430.png](../../_artifacts/2026-11-07-player-tray-shots/current-tray-430.png)）。

补充：`title` 属性里的「清脆自然女声 (Katja)」在触屏上不可达（无 hover），不构成兜底。

### 0.2 判据补强（写给后续所有去字形批次）

原判据只问了一个问题：「这个字形旁边有没有文字」。至少要问三个：

1. **断点问**：文字在**每一个会渲染该控件的断点/容器宽度**下都可见吗？（本例：桌面可见、手机 `display:none`。检查方式是读该元素及其祖先在 `@media` 里的覆盖，而不是读 HTML 相邻节点。）
2. **状态问**：这个字形是不是某类**状态或身份的唯一可辨载体**？如果它的语义是「当前是谁 / 现在是哪一档」，删掉就必须同时补一个**可读文字**的等价物，否则不是去装饰，是删功能。
3. **可达问**：如果兜底信息只存在于 `title`、`aria-label`、hover tooltip 或长按菜单里，那么它在触屏上等于不存在——不能算「已有文字」。

可机械化的两条检查（建议进静态门禁，不在本轮实施）：

- 任何 `button` 命中 `font-size: 0` 且其子树内既无 `<svg>` 图标也无 `<img>` 时告警；本例中即使有 `<svg>` 也应告警，因为图标是 `.vb-ico` 删除后的空壳。
- `display: none` 的节点若承载 `aria-live` 文案或状态文案（见 §1.3 第 3 条），单独列为「移动端不可见文案」清单。

ADR-0029 §16.2.4 已记下这次反转；本文补的是**证据链与断点维度**，不改 ADR。

---

## 1. 现状取证

### 1.1 控件清单（`player_and_tooltip.html:26-121` + 实测）

测量方式：用同结构 DOM + 真实 `static/style.css` 建离线 harness，Edge headless 在 430×932 / 393×852 / 360×780 / 820×900 下读取 `getBoundingClientRect` 与 `getComputedStyle`。图标用空 `<svg>` 占位，几何量不受影响。

| 控件 | DOM | 430px 实测 | 393px | 360px | 桌面 820px |
| --- | --- | --- | --- | --- | --- |
| 上一句 / 下一句 | `.player-btn` | 40×40 | 40×40 | 40×40 | 28×28 |
| 播放/暂停 | `.player-btn-main` | 40×40 | 40×40 | 40×40 | 30×30 |
| 重播当前句 | `.player-btn` | 40×40 | 40×40 | 40×40 | 28×28 |
| 句序状态 | `#player-status` | **0×0（display:none）** | 0×0 | 0×0 | 70×13 |
| 音色 Katja | `.voice-btn` | **44×40，font-size 0，标签 display:none** | 同 | 同 | 49×**19** |
| 音色 Conrad | `.voice-btn` | 44×40，同上 | 同 | 同 | 54×**19** |
| 跟读 / 连读 / 单句 | `.mode-btn` | 41/41/40 × 40 | 同 | 同 | 37/37/36 × **19** |
| 语速 0.6/0.8/1.0/1.2 | `.speed-step-btn` | 100×40 ×4 | 100×40 | 83×40 | 35×**19** |
| 托盘本体 | `.shadow-player` | 430×**152**（视口 932 → 16.3%） | 393×152（17.8%） | 360×152 | 820×48 |

补充事实：

- 语速按钮的**标签与实际值不符**：[player_and_tooltip.html:99-105](file:///d:/Code/DeLector/static/modals/player_and_tooltip.html#L99-L105) 是 `data-speed="0.88"` 却显示 `0.8x`。
- 移动端允许横向滚动为空：430 下 `scrollWidth=426`、`clientWidth=426`，没有溢出；问题是**空白**不是溢出。
- 播放器三行布局来自 [style.css:3392-3453](file:///d:/Code/DeLector/static/style.css#L3392-L3453)；同一文件 3073 处还有一个 `@media (max-width:768px)` 的旧版覆盖，两处重复，后续重构时应合并。

### 1.2 430px 下的实际占位

```
430 × 932 视口，托盘 y=780，高 152px
┌──────────────────────────────────────────────────────┐
│  ① 40×40      40×40      40×40      40×40            │  y=790
│  ◀           ▶          ▶          ↻                 │  （句序 0×0，隐藏）
│  x=14       x=135      x=255      x=376              │
├──────────────────────────────────────────────────────┤
│  ② [■■][■■]                  [跟读][连读][单句]       │  y=836
│     90×42                    x=292..415  125×40       │
│     x=15..104                ← 空 188px →             │
├──────────────────────────────────────────────────────┤
│  ③ [ 0.6x ][ 0.8x ][ 1.0x ][ 1.2x ]                  │  y=882
│     100     100     100     100    = 402×42           │
└──────────────────────────────────────────────────────┘
```

`■■` = 两个 44×40 的纯色块（黑=active，米=inactive），内部无任何可见字符。

### 1.3 六个结构性问题

1. **音色身份在移动端完全丢失**（§0）。桌面还有 9.6px 的 `Katja`/`Conrad`，手机上是零字符。
2. **第二行有 188px 死区**（430 下占整行 43%）。`.player-right` 用 `justify-content: space-between` 只有两个子组，音色组靠左、模式组靠右，中间全空；360 下死区仍有 118px。
3. **`#player-status` 被隐藏，但它承载三类文案**——句序（`updateStatusText`）、跟读倒计时（`showPauseCountdown`）、以及两处「语音引擎不可用」（[player.js:49-51](file:///d:/Code/DeLector/static/js/player.js#L49-L51)、[player.js:352-358](file:///d:/Code/DeLector/static/js/player.js#L352-L358)）。手机用户既看不到进度，也**看不到 TTS 全链路失败的报错**，属于静默失败。
4. **音色状态机是 2 选 1，但数据源是 4 选 1**。设置里可选 4 个（Katja/Conrad/Amala/Killian，[settings_modal.html:214-227](file:///d:/Code/DeLector/static/modals/settings_modal.html#L214-L227)），托盘只有 2 个按钮；`setVoice` 只判断 Katja/Conrad（[player.js:104-112](file:///d:/Code/DeLector/static/js/player.js#L104-L112)）。用户在设置里选 Amala 后，托盘两个按钮**都不 active**，画面比删 emoji 之前更糟。
5. **触达尺寸不达标**。手机 40px 高（低于 44 的增强档），桌面 19px 高（低于 WCAG 2.5.8 的 24px 最低档）；音色按钮桌面 49×19。
6. **拇指区错位**。最靠近屏幕底边的是第三行「倍速」，而最高频的播放/上一句/下一句在 100px 之上的第一行；`#view-reader` 为此预留了 `padding-bottom: 12rem`（192px）。

### 1.4 谁在拇指区、谁挤在同一行

- 拇指热区（屏幕底部 ~0–60px）：整行倍速（4×100×40）；播放区实际落在 100–140px 高度带。
- 同一行挤压：第二行同时放「音色（2）+ 模式（3）」五组可点目标，左侧却留空 188px；第一行四个 40px 方块按 `space-between` 摊到 430 全宽，相邻键起点间隔 121px、实际空档 81px，远超必要，等于把可点目标推到左右边缘。
- 桌面端更极端：全部控件塞进 48px 单行，高度 19px，语速四键间距 0，误触风险高。

---

## 2. 外部参考实测

### 2.1 方法（可复现）

Edge headless + CDP：桌面 `1440×900` 取 `getBoundingClientRect` / `getComputedStyle` / 可访问名，随后 `Emulation.setDeviceMetricsOverride` 到 `393×852` 截图。连接到 `/json/list` 的 page target（不是 `/json/version`）。命令见 §7。

### 2.2 实测表

| 产品 | 音色/音轨切换形态 | 控件实测尺寸 | 身份载体 | 选中态表达 | 结论分级 |
| --- | --- | --- | --- | --- | --- |
| **YouTube**（桌面播放器） | 齿轮 → 设置菜单；行内「播放速度 正常」带当前值，音轨项仅在多音轨视频出现 | 菜单行 273×**48**，字号 11px；`aria-label=设置` | 文字（菜单项 + 行内当前值） | 菜单项 `aria-checked` | [A 受限]（该视频单音轨；倍速子菜单点击后被程序关闭，未取到选项尺寸） |
| **Apple Podcasts**（播客单集页） | 无音色/音轨切换；只有倍速 `1×` 与传输键 | 倍速 32×32；主播放 176×36；单集播放 68×28；剩余时间 42×16 | 封面 + 单集标题 | 倍速按钮文字直接变成 `1.5×` | [A] |
| **ElevenLabs Voice Library** | 画廊：圆形头像 + 悬停播放；可访问名即 `Play {Name} - {UseCase} preview` | 圆形卡 109 / 145 / 202px（随断点）；实测按钮内无 `<img>`（头像是 SVG/背景） | **姓名 + 用途**（可访问名里同时给出，如 `Nassim - Corporate Narrator`） | 画廊无选中态（浏览面，不是选择器） | [A] |
| **Microsoft Speech Studio · Voice Gallery** | 声音卡片网格，每卡含试听键 | 卡 343×208；试听键 28×29 | **姓名 + 性别 + 语言 + 风格描述**（原文：「晓晓 女 中文(普通话，简体) 21 样式 活泼、温暖的声音… 温暖 聊天 +3」） | 无选中态 | [A] |
| **Spotify**（embed 播放器） | 无音色切换；单播放键 | 播放 48×48；更多 24×24；剩余 42×16 | 封面 | 播放↔暂停图标互换 | [A] |
| **DWDS**（德语词典） | 词条发音 | 发音链接 **16×16** | 喇叭图标 + 可访问名「Aussprache als Audio abspielen」 | 无 | [A] |
| **Babbel**（营销页） | 只有显示语言选择，无音频控件 | 语言选择 179×48 | — | — | [A 受限] |
| **Audible** | 页面按 IP 跳到 `audible.co.jp`，无试听控件 | 0 个音频控件 | — | — | [U] |
| **Duolingo** | `duolingo.com/approach` → `about.duolingo.com` | 0 个音频控件 | — | — | [U] |
| **Readlang** | 落地页无 TTS 控件（TTS 需进阅读器选中文本） | 0 个音频控件 | — | — | [U] |
| **Spotify 完整 Web 播放器** | 登录墙；15 个跨域样式表不可读，0 个控件 | — | — | — | [U] |
| **LEO 词典** | Cloudflare 挑战页 | — | — | — | [U] |

### 2.3 可用于本项目的五条结论

1. **没有一家把「两个音色」并排做成色块放在传输栏里。** 多声音的形态只有三种：菜单（YouTube）、画廊（ElevenLabs / Speech Studio）、根本不提供（播放器）。
2. **身份一律文字优先**：姓名 + 性别/语种/风格，头像与色块只是辅助。Speech Studio 把「女 / 中文(普通话，简体)」直接写进卡片，是和我们场景最接近的写法（同一套 Azure/Edge 音色体系）。
3. **当前值回显在折叠态**：YouTube 的设置行写「播放速度 正常」，不展开也知道当前档位。托盘按钮也该这样写「女声 · Katja」。
4. **传输键是最大目标，倍速是独立小目标**：Spotify 播放 48×48、Apple 主播放 176×36；倍速在 Apple 只有 32×32 但独立成键。没有产品把倍速四档铺成四个同宽大键——我们现在是 4×100px，占了整行。
5. **选中态不靠颜色单独承担**：菜单用 `aria-checked` + 勾选图形；播放器用图标互换。我们的 `.active` 是黑白反转，视觉上够强，但缺 `aria-pressed`，读屏用户拿不到状态。

---

## 3. 方案

### 方案 A｜文字化双音色段（保守）

```
┌────────────────────────────────────────────────────┐
│ 句 3 / 8 · 跟读中，请朗读…                    20px  │
├────────────────────────────────────────────────────┤
│ [◀][▶][▶][↻]                            44px       │
├────────────────────────────────────────────────────┤
│ [ 女声 · Katja ][ 男声 · Conrad ]  [跟读|连读|单句] │ 44px
├────────────────────────────────────────────────────┤
│ [0.6x][0.8x][1.0x][1.2x]                44px       │
└────────────────────────────────────────────────────┘
音色按钮：两行文字（主：女声/男声 11px；次：Katja 9px），每键 ≥88×44
```

- 仍是三行控制 + 一行状态，高度约 150px（与现状持平，但不再有死区、不再有空块）。
- 优点：改动面最小，一次点击切音色；360px 下 2×88 + 3×44 + 间距 = 320，可放下。
- 缺点：**只能覆盖 2/4 个音色**，`Amala`/`Killian` 仍然无处安放；要补「更多」入口就变成「选择器 + 导航」两套动作。

### 方案 B｜当前音色按钮 + 4 音色面板（推荐）

```
┌────────────────────────────────────────────────────┐
│ 句 3 / 8 · 跟读中，请朗读…                    20px  │  ← 恢复被隐藏的状态
├────────────────────────────────────────────────────┤
│ [ 女声 · Katja  ▾ ]          [跟读][连读][单句]    │ 44px
├────────────────────────────────────────────────────┤
│ [◀][▶][▶][↻]        [0.6][0.8][1.0][1.2]          │ 44px
└────────────────────────────────────────────────────┘
                          点 [女声 · Katja ▾] 后向上弹出：
              ┌──────────────────────────────┐
              │ ✓ 女声 · Katja    清脆自然   │ 44px
              │ ○ 男声 · Conrad   沉稳磁性   │ 44px
              │ ○ 女声 · Amala    自然清晰   │ 44px
              │ ○ 男声 · Killian  浑厚母语   │ 44px
              └──────────────────────────────┘
                 role=radiogroup / role=radio / aria-checked
```

- 2 行控制 + 1 行状态，总高约 **136px**（8+20+6+44+6+44+8，省 16px），且把倒计时和报错重新露出来。
- 音色按钮是**折叠态回显**（YouTube 模式），展开后 4 个音色一屏列全，与设置页数据源一致，彻底消除「2 选 1 状态机 vs 4 选 1 数据源」。
- 模式三键保持一键直达，不塞进菜单。
- 倍速与传输同排：430 下 4×44 + 4×44 + 8 = 360 ≤ 402；360 下传输 40 宽、倍速 40 宽 = 320 ≤ 332，**不溢出但只余 4px**（需 `@media (max-width:380px)` 收窄并做 360 回归）。
- 代价：切音色从 1 次点击变 2 次；需要处理面板焦点、Esc、点击外部关闭，以及 `setVoice` 正在播放时会重读当前句（[player.js:113-122](file:///d:/Code/DeLector/static/js/player.js#L113-L122)）——面板先关再重读，避免动画/重读叠加。

### 方案 C｜音色迁出托盘（放进伴读抽屉）

```
托盘： [◀][▶][▶][↻]      0.8x ▾        句 3/8
抽屉： 词典 | 句法 | 随笔 | 声音
```

- 优点：托盘最干净，传输键可回到拇指区正中。
- 缺点：音色从「一眼可见」变成两级菜单；与现有抽屉 IA 冲突（抽屉是内容面板，不是设置面板）；需要新增 tab、迁移状态、改 `swipe` 手势，成本最高。**不推荐**。

### 推荐：方案 B

理由按权重排序：

1. **一次解决根因**：音色身份重新由**可读文字**承担（满足 I1），并且覆盖 4 个音色，不再是「删了 emoji 补个文字」的单点补丁。
2. **与设置页单一数据源**：`delector_voice` 一个 key，托盘与设置都读它，`Amala/Killian` 不再出现「两个都不 active」。
3. **顺手修掉三个既有缺陷**：恢复 `#player-status`（倒计时/报错可见）、去掉 188px 死区、把传输键放回底部。
4. **触达与窄屏可量化通过**：所有目标 ≥44×44（360px 下倍速/传输 40 宽 × 44 高，横向 320px，余量 12px）。
5. **外部证据支持**：YouTube 的「当前值回显 + 菜单」、Speech Studio 的「姓名 + 性别」、Apple 的「独立小倍速键」三种做法可以同时落进这个结构。

不选 A 的唯一原因是 4 音色无法自洽；不选 C 是因为把高频设置埋进内容抽屉，收益不抵成本。

### 推荐方案的约束核对

| 约束 | 方案 B 的处理 |
| --- | --- |
| 触屏 44px | 所有行高 44；传输键 44×44（≤380px 时 40×44）；模式键 44×44；音色按钮 118×44；面板每行 44 |
| 窄屏 360px | 行 1：118 + 3×44 + 8 = 258 ≤ 332；行 2：4×40 + 4×40 + 8 = 328 ≤ 332。**余量仅 4px**，必须做 360 截图回归 |
| `prefers-reduced-motion` | 面板只做 `opacity + translateY(4px)`，`var(--dur-fast) var(--ease-editorial)`；`reduce` 下直接显示，无位移。不使用弹跳/循环 |
| I1（不只靠颜色/字形） | 按钮与面板均为文字；active 态是文字 + 反转底色 + `aria-checked`/`aria-pressed` 三重表达 |
| 更新中的既有状态 | `setVoice` 会重读当前句：切换后先关面板、再重读；连续点选需取消上一段音频（复用现有 `pauseTimer`/`audioEl.pause()` 路径） |
| 桌面 19px 问题 | 同一套结构在 ≥769px 收起为单行，但控件高度提到 28–32px，至少满足 24px 最低档 |

---

## 4. 命名与数据事实

### 4.1 `Katja` / `Conrad` 是什么

**不是应用自造的名字，是微软 Edge/Azure Neural TTS 的音色标识符**，且是硬编码的完整 voice id：

| 位置 | 事实 |
| --- | --- |
| [player_and_tooltip.html:49/57](file:///d:/Code/DeLector/static/modals/player_and_tooltip.html#L49-L57) | `setVoice('de-DE-KatjaNeural')` / `'de-DE-ConradNeural'` 写死在 `onclick` |
| 设置页 [:214-227](file:///d:/Code/DeLector/static/modals/settings_modal.html#L214-L227) | 下拉四项：Katja / Conrad / Amala / Killian，值均为 `de-DE-*Neural` |
| 后端 [audio.py:98-105](file:///d:/Code/DeLector/delector/routes/audio.py#L98-L105) | `_TTS_VOICE_WHITELIST` 恰好这四个 id，其它 voice 返回 400 |
| 后端默认 [audio.py:29](file:///d:/Code/DeLector/delector/routes/audio.py#L29) | `voice = "de-DE-KatjaNeural"` |
| 产品文案 [FEATURES.md:141](file:///d:/Code/DeLector/FEATURES.md#L141) | 「女声 `KatjaNeural` / 男声 `ConradNeural`」——项目自己已经用「女声/男声」做解释 |

`de-DE-KatjaNeural` 的命名规则是 `语言-地区-名字Neural`，属于微软语音库；名字是**音色名**，不是角色人设。因此对用户展示时，名字只能当副标题，主标题应是学习者真正用来区分的维度。

### 4.2 给用户看什么名字

沿用设置页已有的措辞（不改文案源）：

| 值 | 托盘/面板主标题 | 副标题（沿用设置页） |
| --- | --- | --- |
| `de-DE-KatjaNeural` | 女声 · Katja | 德国之声推荐 / 清脆自然 |
| `de-DE-ConradNeural` | 男声 · Conrad | 严谨沉稳 / 沉稳磁性 |
| `de-DE-AmalaNeural` | 女声 · Amala | 自然清晰 |
| `de-DE-KillianNeural` | 男声 · Killian | 浑厚母语 |

理由：`Katja` 单独出现对不熟悉 TTS 的人无意义（这正是 §0 事故的语义层原因）；「女声/男声」是可立刻区分的功能维度，名字是稳定标识。两者都写，同时满足可辨与可记。**不做人设化命名**（如「安娜老师」），那会引入一套需要额外解释的世界观，且与设置页脱节。

### 4.3 一个必须写进方案的事实：音色选择在两条链路上无效

- **Android 原生 TTS**：`window.AndroidNativeTTS.speak(text, rate)` 只有两个参数（[player.js:16](file:///d:/Code/DeLector/static/js/player.js#L16)、[:200](file:///d:/Code/DeLector/static/js/player.js#L200)、[:290](file:///d:/Code/DeLector/static/js/player.js#L290)），**没有 voice 参数**。Android WebView 内切音色不会改变声音。
- **服务端降级链路**：`generate_edge_tts_audio` 的 `except` 分支改用有道/百度/Google 的 URL 模板（[audio.py:56-92](file:///d:/Code/DeLector/delector/routes/audio.py#L56-L92)），这些 URL 不含 voice；`edge_tts` 缺失时（Chaquopy 打包）音色同样无效。
- **Web Speech 兜底**：`speechSynthesis` 分支自己挑 de-DE 的第一个 voice（[player.js:54-68](file:///d:/Code/DeLector/static/js/player.js#L54-L68)），与托盘选择无关。

结论：托盘音色控件只在「服务端 edge_tts 可用」时真实生效。重构时不能只把它做得更显眼，否则是在**放大一个会说谎的控件**。最低要求：当当前引擎不支持 voice 时，面板里显式标注「当前设备使用系统语音，音色选择暂不生效」，而不是假装切换成功。是否要修引擎不在本轮范围，记为待决策项。

---

## 5. 不做的清单

| 看起来合理 | 为什么不做 |
| --- | --- |
| 把语速四档塞进音色下拉 | 两个动作共用一个菜单：改语速从 1 击变 2 击，且菜单打开时无法边听边调；Apple/YouTube 都把倍速与音轨分开 |
| 用两个色块/两个图标承载音色 | §0 的复现路径；I1 要求可读文字 |
| 继续用 `font-size: 0` 隐藏移动端标签 | 本次事故的直接机制；即使有 `title`/`aria-label` 也不能替代可见文字 |
| 给当前音色加呼吸灯/循环闪烁表示选中 | ADR-0029 禁循环动效；会与「播放中」状态抢注意力 |
| 四个音色平铺在托盘 | 4×88 = 352px，加模式组必然溢出 360 |
| 把「跟读/连读/单句」收进菜单 | 影子跟读时最常切换的就是模式，必须一键 |
| hover 才显示音色名 | 触屏无 hover；这正是 `title` 兜底失效的原因 |
| 在托盘再加一个「播放」入口 | 与既有 `ShadowPlayer` 单例冲突，会出现双声/双计时器 |
| 面板里做搜索、分组、滚动 | 4 项固定，加检索只会让小面板变成半成品页面 |
| 为音色新开 localStorage key | 现用 `delector_voice`，设置页与托盘必须共用一个源 |
| 改 `Katja` → 「安娜」之类的角色名 | 与设置页、后端白名单、FEATURES 文案脱节，且需要额外解释成本 |

---

## 6. 证据与复现

### 6.1 复现命令

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  --headless=new --remote-debugging-port=9341 `
  --user-data-dir="$env:TEMP\del_tray_profile" --window-size=1440,900 about:blank
# 连接 http://127.0.0.1:9341/json/list → 取 type=page 的 webSocketDebuggerUrl
# Page.navigate → Runtime.evaluate("(SNAPSHOT)()") → Emulation.setDeviceMetricsOverride(393x852, dsr=2) → Page.captureScreenshot
```

要点（上轮已踩过，沿用）：

- 必须连 **page target**；`/json/version` 的 browser WS 不能 `Page.navigate`。
- `Runtime.evaluate` 传 `(${SNAPSHOT})()`；传裸箭头函数会得到 `{}`。
- 解析 `transitionTimingFunction` 时用正则提 `cubic-bezier(...)`，按逗号 `split` 会截断。
- 跨域样式表读 `cssRules` 抛 `SecurityError`，记录条数后跳过，computed style 仍可用。

### 6.2 截图索引（`_artifacts/2026-11-07-player-tray-shots/`，19 个文件 / 1,590,630 B）

| 文件 | 内容 |
| --- | --- |
| `current-tray-430.png` | 用户报告的现状（黑块 + 米块，无文字） |
| `tray-harness-430/393/360/820.jpg` | 现状托盘在四个宽度下的实测渲染 |
| `elevenlabs-desktop.jpg` / `elevenlabs-cards*.jpg` | 声音画廊：头像 + 姓名 + 用途标签 |
| `speech-studio-desktop/393.jpg` | Azure 音色卡：姓名 + 性别 + 语言 + 风格 |
| `apple-podcasts-desktop/393.jpg` | 独立倍速键 32×32 + 主播放 176×36 |
| `youtube-menu-desktop/393.jpg` | 播放器设置菜单：行内回显「播放速度 正常」 |
| `spotify-embed-desktop.jpg` | 48×48 播放键，无倍速/音色 |
| `dwds-desktop.jpg` | 词典 16×16 发音链接 |
| `babbel-desktop.jpg` | 营销页只有语言选择 |
| `audible-jp-redirect.jpg` / `duolingo-about-redirect.jpg` | `[U]` 证据：地理跳转 / 站点重定向 |

---

## 7. 待决策（交给实施批次）

1. 引擎降级时音色控件是「禁用 + 说明」还是「隐藏」——涉及 `player.js` 的引擎探测，需产品拍板（§4.3）。
2. 0.8x 按钮的真实值是 0.88（`-12%`）：改标签为 0.9x，还是把值改成 0.8（`-20%`）？两者都会影响已习惯「0.8x=0.88」的老用户，建议随托盘重构一并统一样本。
3. 桌面端是否同步换成 B 结构（单行 28–32px 高），还是仅移动端重构、桌面保留现状。
