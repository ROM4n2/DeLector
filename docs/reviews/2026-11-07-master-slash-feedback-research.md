# 「斩」反馈动效与背词流程借鉴调研

> 日期：2026-11-07　|　性质：只读调研，不改 `static/`、不开 PR　|　上游：ADR-0030
> 目标：回答「斩」现在到底发生了什么、该补哪一档动效、背词流程是否值得借鉴。
> 证据标记：`[S]` 本仓源码静态核对（file:line）｜`[B]` 官方文档｜`[C]` 第三方｜`[U]` 未验证

---

## 0. 结论先行

1. **推荐「中档 · 落印」**：按下 100ms 压感 + 卡面 180ms「已掌握」朱印 + 计数器 520ms 递增（触觉可选）。不加音效，不加常驻循环，不引入新时长 token；印章出现后由现有重渲染替换卡片。
2. **不建议「重档 · 斩击退场」首发**：斜切墨线 + 卡片飞出 + 音效会越过 ADR-0030 的位移预算（`translateY ≤ 4px`、`scale 0.95–1.0`、一次性 `≤ 260ms`），需要 ADR 例外、`VIBRATE` 权限、音效开关三件事一起做；收益主要是「爽」，不是「清楚」。
3. **背词流程不要搬「斩」的动效**：工作台 `doRate` 的价值是每张卡 3–8 秒的节奏，逐卡庆祝会拖慢。值得抄的是 **撤销**、**统一触觉**、**可关闭反馈**，不是印章。
4. **关键现状**：`斩` 目前**没有任何主动视觉、听觉、触觉反馈**；唯一变化是 PATCH + 2 个 GET 之后的整卡 `innerHTML` 替换。按钮的绿色 `mastered-active` 状态在 due/pending 段根本来不及被看到就被重渲染掉了。`[S]`
5. **关键风险**：`navigator.vibrate` 在 Android WebView 的引擎层支持，但 Chrome 官方文档要求宿主 APK 声明 `android.permission.VIBRATE`；本仓 `AndroidManifest.xml` 没有该权限，因此现有 `vibrate(15/30)` **预期是静默 no-op**，需真机验证。`[S][B][U]`

---

## 1. 现状：`斩` 到底做了什么

### 1.1 代码路径

| 层 | 位置 | 事实 |
| --- | --- | --- |
| 入口 | [cards.js:340-342](file:///d:/Code/DeLector/static/js/cards.js#L340-L342)（牌盒）、`:647-649`（词汇网格）、`:674-676`（语法网格） | 同一个 `card-master-btn`，文案 `斩 (已掌握)` / `↺ 重返待复习` |
| handler | [cards.js:700-711](file:///d:/Code/DeLector/static/js/cards.js#L700-L711) `toggleMaster(type,id,currentMastered)` | 直接 `PATCH /api/cards/{type}/{id}/master`，无乐观更新 |
| 成功 | [cards.js:70-101](file:///d:/Code/DeLector/static/js/cards.js#L70-L101) `loadCards()` | `Promise.all([GET /api/cards, GET /api/cards/due])` → 刷新三个 segment 计数 → `renderCardsGrid()` |
| 渲染 | [cards.js:111-182](file:///d:/Code/DeLector/static/js/cards.js#L111-L182) → `renderDeckStage()` | 整段 `container.innerHTML = ...` 替换；索引保留、翻面状态保留 |
| 失败 | [cards.js:708-710](file:///d:/Code/DeLector/static/js/cards.js#L708-L710) | `alert("更新卡片状态失败: ...")` |

### 1.2 按下之后现在到底发生什么

- **没有 `:active` 规则**。`.card-master-btn` 只有 hover 样式，按下瞬间没有视觉。`[S]`
- **没有离场编排**。没有 `setTimeout`、没有 keyframe、没有 class 切换。`[S]`
- **没有音效**。仓库 `static/` 下没有 mp3/wav/ogg/m4a，也没有 `AudioContext`。`[S]`
- **没有触感**。同一文件的评分（`cards.js:432-434`）和翻面（`:458`）都调了 `navigator.vibrate`，`toggleMaster` 没有。`[S]`
- **没有 toast / undo**。`showUndoToast` 名为 undo，实际是通用 toast（评分 `cards.js:440`、删除 `:693`、导入等都用它），没有撤销动作；`斩` 连 toast 都没有。`[S]`
- **有计数变化，但是瞬变**。三个 segment 计数通过 `textContent` 直接赋值，不是 `countUp`。`[S]`
- **卡片直接换**。在 due/pending 段，被斩的卡从列表消失；如果这是最后一张，直接切空态（`cards.js:136-175`）；否则同索引换成下一张。用户看不到按钮变绿 `mastered-active` 的那一刻。`[S]`

结论：**不是纯位移，也不是位移 + 缩放；是零动效的整卡替换。**

### 1.3 感知时序

| 时刻 | 发生什么 | 用户感知 |
| --- | --- | --- |
| `t0` pointerdown | 无 `:active`、无 ripple | 手指下没有反馈 |
| `t0` click | 发起 PATCH | 仍无反馈 |
| `t0 + RTT1` | PATCH 返回 → `loadCards()` | 仍无反馈 |
| `t0 + RTT1 + RTT2` | 2 个 GET 返回 → 计数瞬变 → `innerHTML` | 卡片「瞬移」成下一张 / 空态 |
| 之后 | 无入场动画 | 新卡静态出现 |

一句话：**主动反馈 0ms；首次视觉变化 = 1 个 PATCH 往返 + 2 个 GET 往返；卡片离场 0ms（`innerHTML` 瞬时替换）。**

`RTT1/RTT2` 是本机回环 / Chaquopy 内部 HTTP，未在真机测；这里只能确定「没有任何设计时长，全部由网络往返决定」。`[U]`

未来测量方法：在 `toggleMaster` 入口 `performance.mark('master-click')`，用 `MutationObserver` 监听 `#cards-container`，记录 `click → first childList mutation`；再用 CDP Performance 看长任务。

### 1.4 触屏与鼠标两条路径的差别

| 维度 | 触屏 | 鼠标 |
| --- | --- | --- |
| 视觉按压 | 无 | 无（只有 hover，点击后 hover 仍可能停留） |
| hover | 不触发 | `@media (hover:hover)` 生效 |
| 手势 | Pointer Events；`touch-action: pan-y`；`[onclick]` 目标被 `closest` 过滤，斩不会触发翻面/切卡 | 同一条 Pointer Events 路径；点击目标同样被过滤 |
| 双击 | `toggleDeckFlip` 有 200ms 防抖（`cards.js:456`）；`toggleMaster` **没有** | 双击可发两次 PATCH |
| 触觉 | `navigator.vibrate` 仅在支持的 Android 上有效；iOS Safari/WebView 不支持 | 桌面 no-op |
| 目标尺寸 | `font-size .6875rem` + `padding .25rem .625rem` + 1px border ≈ 23–25px 高，低于 44pt/48dp | 鼠标精度高，问题较小 |

### 1.5 与 ADR-0030 的对齐审计

| 项 | 现状 | 判定 |
| --- | --- | --- |
| token | `.card-master-btn { transition: all 0.15s ease }`（[style.css:4747](file:///d:/Code/DeLector/static/style.css#L4747)） | 硬编码 150ms，不是 `--motion-*` |
| token | `.deck-active-card` 用 `0.5s cubic-bezier(...)` / `0.2s ease`（[style.css:4347-4350](file:///d:/Code/DeLector/static/style.css#L4347-L4350)） | 硬编码，且 500ms 超过一次性 260ms 预算；属既有滑动例外 |
| 循环 | 本次三档都不新增常驻循环 | 合规，不新增第 8 处白名单 |
| reduce | 全局 reduce 只把 `.btn:active` 的 `transform` 置 none（[style.css:12813-12816](file:///d:/Code/DeLector/static/style.css#L12813-L12816)），`.card-master-btn` 不在内 | 新动画必须自己写 reduce 分支 |
| 位移预算 | `translateY(≤4px)`、`scale(0.95–1.0)`、一次性 `≤260ms`（ADR §2.5） | 中档的 180ms + `scale 0.96→1` 合规；重档的飞出不合规 |

---

## 2. 头部实践

### 2.1 卡片学习产品

| 产品 | 相关机制 | 反馈方式 | 对「斩」的启示 |
| --- | --- | --- | --- |
| **Anki** | Suspend（手动解除）/ Bury（次日自动回来）；按钮上显示下次间隔 | 无逐卡庆祝；可选 Feedback Ticks；桌面有 Reduce motion | 安静确认 + 可撤销 + 可降级，而不是庆祝 |
| **AnkiMobile** | 四向滑动可配置；**竖向滑动必须从屏幕最左/最右边缘开始**，避免和滚动冲突 | Feedback Ticks 在右上角闪勾/叉 | 手势要有防误触边界；确认可以很小 |
| **AnkiDroid** | 点击/滑动手势可配置 | 振动设置主要针对通知，不是复习评分 | 学习流里触觉不是默认必选项 |
| **Quizlet** | Learn 用 `Got it / Study again`；Progress 分 `Not Studied / Still Learning / Mastered` | Mastered 是由答题记录**推导**出来的状态 | 「掌握」不该是一个一键自报按钮 |
| **Duolingo** | 白皮书：每道练习后给「愉悦音效 + 简短庆祝动画」，整节结束再给更大奖励 | 多感官、游戏化 | 庆祝属于「一节课/一个里程碑」，不属于「归档一张卡」 |
| **Memrise** | `I already know this` / ignore 跳过词；`Difficult` 提升优先级 | 忽略是队列操作；平台可用性历史上不一致 | 忽略/归档要写清「去了哪里、怎么回来」 |
| **RemNote** | 四档评分：Forgot / Partially recalled / Recalled with effort / Easily recalled；按钮上写下次间隔 | 反馈是信息性的，不是表演性的 | 先让用户看到后果，再谈动效 |
| **Bunpro** | Undo 按钮；Ghost Reviews 针对错题加练 | 撤销是复习回路的标配 | `斩` 没有 undo，是明显缺口 |
| **WaniKani** | 九阶段 SRS；Burned 后退出复习，可 unburn | Burn 是长期连续答对后到达的终点，不是一次点击 | 终态应该「挣来」，不是「一键封存」 |
| **SuperMemo** | `Dismiss` 移出学习但保留在集合；`Forget` 重置；0–5 评分 | 语义区分明确 | `斩` 更接近 Dismiss/Archive，不是 Forget，也不是「学会」 |

### 2.2 反馈三层

**视觉**

- Material 3：`short1–4 = 50/100/150/200ms`，`medium1–4 = 250/300/350/400ms`，`long1–4 = 450–600ms`；入场用 emphasized decelerate 400ms，退场用 emphasized accelerate 200ms；Expressive 更新后转向 spring physics，旧 easing/duration 体系「不再维护」。`[B]`
- Apple HIG：动效要「有目的、可关闭、不能是传达重要信息的唯一方式」，并建议用触觉/音频补充。`[B]`
- 对 DeLector 的含义：180ms 落在 M3 `short4` 同一档；不需要引入 spring，也不需要新的时长 token。

**触觉**

- Android `HapticFeedbackConstants`：`CONFIRM`（API 30，确认/成功）、`REJECT`（API 30，拒绝/失败）、`CLOCK_TICK`、`CONTEXT_CLICK`、`VIRTUAL_KEY`、`KEYBOARD_TAP` 等。`[B]`
- AOSP 短原语：`CLICK` / `TICK` / `LOW_TICK` 通常在 20ms 以内；双击原语是 30ms 振 + 100ms 停 + 30ms 振。`[B]`
- Web 只有 `navigator.vibrate(duration | pattern)`，拿不到语义常量、振幅、sharpness。`[B]`
- iOS：`UIImpactFeedbackGenerator`（light/medium/heavy/soft/rigid）、`UINotificationFeedbackGenerator`（success/warning/error）、`UISelectionFeedbackGenerator`；HIG 要求按系统既定语义使用，避免滥用。`[B]`
- 对 DeLector 的含义：`vibrate(15)` 与 Android `CLICK/TICK` 的短促语义一致；`斩` 应该是一次 tick，不是一段节奏。

**听觉**

- Apple HIG：静音开关下，非必要音效（键盘声、游戏音效、UI 反馈）应当静音；音量设置要全局生效，不要私自调总音量。`[B]`
- 行业实践：点击类 30–120ms，确认类 100–300ms，通知类 150–500ms；短促、低音量、不要每个动作都响。`[C]`
- 对 DeLector 的含义：如果以后要加，最多是一个 ≤100ms 的合成 tick，默认关闭，独立开关，且不能和 TTS/ShadowPlayer 抢音频焦点。

### 2.3 Android WebView 里 `navigator.vibrate` 到底可不可用

| 事实 | 结论 | 来源 |
| --- | --- | --- |
| MDN 兼容表：WebView Android 自 4.4.3 起 Full support；需要 sticky user activation；静音/DND 可能抑制；返回 boolean | 引擎层可用 | `[B]` MDN |
| Chrome for Developers《WebView overview》：Vibration API 在 WebView v33/v55 均支持，**需要 `android.permission.VIBRATE`** | 宿主必须声明权限 | `[B]` Chrome |
| 本仓 `android/app/src/main/AndroidManifest.xml`：只有 `INTERNET` / `ACCESS_NETWORK_STATE`，**没有 `VIBRATE`** | 当前 APK 预期静默 no-op | `[S]` |
| 真机未测 | 不能把「no-op」写成已证实结论 | `[U]` |

**是否需要原生桥？**

- 基础「振一下」：**不需要**。加一行 `<uses-permission android:name="android.permission.VIBRATE"/>`，重新打包即可；`VIBRATE` 是普通权限，无运行时弹窗。
- 想要 Android 的语义常量（`CONFIRM`/`REJECT`/`TICK`）、振幅、sharpness，或绕开某些 OEM WebView 的兼容问题：**需要原生桥**（`@JavascriptInterface` → `Vibrator` / `performHapticFeedback`）。
- iOS Safari/WebView：`navigator.vibrate` 从未支持；iPhone 上网页拿不到触觉。`[B]`

**真机验证清单（未来）**

1. 打包含 `VIBRATE` 的 APK。
2. 在 `斩` 的 click handler 里 `navigator.vibrate(15)`，记录返回值。
3. 分别在正常、静音、DND、省电模式下各测 3 次。
4. 若返回 `true` 但无振动，再判断是 OEM 限制还是 WebView 版本问题。

---

## 3. 三档方案

| 档 | 内容 | 成本 | 原生依赖 | 用户能感知到什么 | ADR 判定 |
| --- | --- | --- | --- | --- | --- |
| **轻** | 按压 `scale(.98)` + 按钮文案即时切换 + 可选 15ms 触觉 | CSS ~10 行；0 JS | 触觉需 `VIBRATE`，否则 no-op | 「按下去有回应」，但卡片仍瞬移 | 合规 |
| **中（推荐）** | 轻 + 卡面 180ms「已掌握」朱印 + 计数 520ms 递增 | CSS ~25 行 + JS ~25 行 + 3 处模板加 `data-*` | 同上 | 「这一下被盖章收走了」 | 合规（180ms / scale .96） |
| **重** | 中 + 斜切墨线 + 卡片退场 + 音效 + 更丰富触觉 | CSS ~35 行 + JS ~60 行 + manifest + 音效开关 + ADR 例外 | 基础触觉仍不需桥；语义触觉/振幅需桥 | 「斩得爽」，但每张都爽会累 | 需 ADR 例外 |

### 3.1 轻档：先让手指有回应

- 按下：`scale(0.98)`，`var(--motion-press)`（100ms）。
- 点击后：按钮文案/颜色由现有重渲染负责；如果希望「立刻」变，可在 handler 里先 `btn.textContent = '↺ 重返待复习'`，但要注意失败回滚。
- 触觉：`navigator.vibrate(15)`，与评分/翻面一致。
- **感知**：手指下陷一下，然后卡片换掉。比现在好，但「为什么它没了」仍然靠用户自己推断。
- **成本**：只改 `style.css` 的 `.card-master-btn` 规则；无 JS、无模板改动、无新 token。
- **适合**：想用一个最小 PR 先止血。

### 3.2 中档：落印（推荐）

时间线：

```text
t0        pointerdown       按钮 scale .98（100ms）
t0        click             给牌加 .is-mastering；PATCH 开始；可选 vibrate(15)
t0..180ms                   卡面「已掌握」朱印淡入 + 轻微下压回弹
t0+180ms 或 数据返回        计数 countUp 520ms；重渲染，换下一张 / 空态
```

- **为什么是印章，不是刀光**：卡片已经有 `KARTEIKARTE` 印章语言（`.deck-seal-stamp`），「已掌握」朱印是同一套视觉语汇；它表达「收进档案」，而不是「打败敌人」。
- **为什么不做退场**：退场需要位移/旋转，越过 ADR 预算；而且卡片必须等 API 返回才能换，退场会和网络时序打架。印章本身就是 closure。
- **为什么先不加音效**：没有音效资源、没有开关、没有音频焦点策略；先加会制造新的产品债。
- **感知**：按下去有压感 → 卡面落一个绿色印章 → 数字从旧值跳到新值 → 下一张卡/完成态出现。用户第一次能明确看到「我刚才做了什么」。
- **成本**：`style.css` 一个 keyframe + 一个 `::after`；`cards.js` 一个 class + 一个最短展示时间；3 处模板加 `data-master-key`；`loadCards` 的计数改成 `countUp`。
- **依赖**：无原生桥；触觉需要 `VIBRATE` 权限（可后置）。

### 3.3 重档：斩击退场（不推荐首发）

- 斜切墨线（`scaleX(0→1)`）+ 卡片 `translateY/rotate + opacity` 退场 + 80–100ms 合成音效 + 双击触觉原语。
- **能买到什么**：更强的「斩」隐喻、更强的单次爽感。
- **代价**：
  - 位移/旋转超出 ADR 预算，需要登记例外；
  - 音效需要资源、开关、静音策略、和 TTS 的音频焦点协调；
  - 每张卡都演一遍会拖慢复习，100 张卡 × 300ms ≈ 30s；
  - 低端机上 3D 卡 + 退场 + 重渲染叠加，掉帧风险最高。
- **更值得放的地方**：把「重档」的预算花在 **今日复习完成态**（空态 `cards-empty`）或一次会话结束，而不是每张卡。Duolingo 的白皮书也是「每题小反馈、整节大奖励」；WaniKani 的庆祝在升级，不在每张卡。

### 3.4 推荐

**先做中档，重档留给完成态。** 中档解决的是「没有确认」这个真问题；重档解决的是「不够爽」这个伪问题。

---

## 4. 可直接抄的模板（只用现有 token）

> 以下为示意代码，未落地。所有时长只引用 `--motion-enter`（180ms）、`--motion-press`（100ms）、`--motion-count`（520ms）；不新增时长字面量。

### 4.1 CSS

```css
/* 1) 按压：桌面与触屏同一条规则；100ms，scale 在 ADR 预算内 */
.card-master-btn {
  /* 把 transition: all 收窄，避免顺带动到布局属性 */
  transition:
    transform var(--motion-press) var(--ease-editorial),
    background-color var(--motion-enter) ease,
    border-color var(--motion-enter) ease,
    color var(--motion-enter) ease;
}
.card-master-btn:active {
  transform: scale(0.98);
}

/* 2) 落印：只作用于牌盒正面；180ms，scale 0.96→1，不位移 */
@keyframes dl-master-seal {
  from { opacity: 0; transform: scale(0.96) rotate(-2deg); }
  70%  { opacity: 1; transform: scale(0.96) rotate(-2deg); }
  to   { opacity: 1; transform: scale(1) rotate(-2deg); }
}

.deck-active-card.is-mastering .card-front::after {
  content: "已掌握";
  position: absolute;
  right: 1.25rem;
  bottom: 4.75rem;
  z-index: 3;
  pointer-events: none;
  padding: 0.2rem 0.55rem;
  border: 2px solid var(--moss);
  border-radius: 2px;
  background: var(--paper);
  color: var(--moss);
  font-family: var(--mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  transform: rotate(-2deg);
  animation: dl-master-seal var(--motion-enter) var(--ease-editorial) both;
}

/* 3) reduce：不缩放、不播放；印章直接落终态 */
@media (prefers-reduced-motion: reduce) {
  .card-master-btn:active { transform: none; }
  .deck-active-card.is-mastering .card-front::after {
    animation: none;
    opacity: 1;
    transform: rotate(-2deg);
  }
}
```

说明：

- `.card-front` 自带 `transform`，会成为绝对定位伪元素的包含块；不需要额外改布局。
- 如果实现时发现 `::after` 被裁切，再给 `.deck-card-face.card-front` 加 `position: relative`，不要改成容器级绝对定位（会进入 3D 层，层叠不可控）。
- 印章文案用「已掌握」与现有按钮一致；如果想更准确表达 archive，可改成「已归档」，但那是产品措辞决策，不在本次调研范围内。

### 4.2 JS：最短展示时间 + 失败回滚

模板调用点（三处）加一个唯一 key：

```html
<button class="card-master-btn ..."
        data-master-key="${card._type}-${card.id}"
        onclick="toggleMaster('${card._type}', ${card.id}, ${card.mastered ? 1 : 0})">
  ${card.mastered ? "↺ 重返待复习" : "斩 (已掌握)"}
</button>
```

```js
import { countUp, prefersReducedMotion } from "./motion.js";

/** 读取 CSS token 的毫秒值；不要在这里写 180 / 260 之类的字面量 */
const motionMs = (name) =>
  parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;

export async function toggleMaster(type, id, currentMastered) {
  const btn = document.querySelector(`.card-master-btn[data-master-key="${type}-${id}"]`);
  if (btn?.disabled) return;
  if (btn) btn.disabled = true;

  const cardEl = btn?.closest(".deck-active-card"); // 网格卡没有落印，只保留按压/触觉
  const reduced = prefersReducedMotion();
  const sealMs = reduced ? 0 : motionMs("--motion-enter");
  if (cardEl && !reduced) cardEl.classList.add("is-mastering");

  // 与评分/翻面同一条触觉语义：一次短 tick。
  // 注意：当前 APK 未声明 VIBRATE，真机上预期 no-op；见 §2.3。
  if (navigator.vibrate) navigator.vibrate(15);

  const started = performance.now();
  try {
    await api(`/api/cards/${type}/${id}/master`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mastered: !currentMastered }),
    });

    // 数据快于印章时，补足一个「能看见」的最短展示时间；
    // 数据慢于印章时，不额外等待。
    const rest = sealMs - (performance.now() - started);
    if (rest > 0) await new Promise((r) => setTimeout(r, rest));

    await loadCards();
  } catch (e) {
    cardEl?.classList.remove("is-mastering");
    if (btn) btn.disabled = false;
    alert("更新卡片状态失败: " + e.message);
  }
}
```

计数改为：

```js
// loadCards() 内，替换 seg-mastered-count 的直接赋值
const sm = document.getElementById("seg-mastered-count");
if (sm && sm.textContent !== String(totalMastered)) countUp(sm, totalMastered);
```

说明：

- `data-master-key` 用 `type-id`，避免词汇/语法同 id 在网格里互相选中。
- 不新增模块级可变状态（`cards.js` 有「零顶层可变状态」契约）；用 `btn.disabled` 做在途保护。
- `prefersReducedMotion()` 必须参与判断：全局 reduce 只把动画时长压到 0.01ms，不会阻止 `setTimeout` 等 180ms。
- 如果担心连点，可在 handler 开头临时禁用所有 `.card-master-btn`，失败时统一恢复。

### 4.3 可选：计数器（中档）

`countUp` 内部已经读取 `--motion-count`（520ms），直接复用即可；它在 reduce 下应当走即时赋值（以 `motion.js` 现有实现为准）。不要给计数器写 `setInterval` 循环。

### 4.4 可选：音效（仅重档）

```js
function playMasterTick() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  const ctx = new Ctx();
  const ms = motionMs("--motion-press") || 100; // 用按压 token，不新增音效时长
  const t = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "triangle";
  osc.frequency.setValueAtTime(720, t);
  osc.frequency.exponentialRampToValueAtTime(360, t + ms / 1000);

  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.06, t + 0.004); // 4ms attack，合成参数，不是动效时长
  gain.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);

  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + ms / 1000);
  osc.onended = () => ctx.close();
}
```

落地前必须补：独立音效开关、静音模式检测、与 TTS/ShadowPlayer 的音频焦点协调、不要每次 `new AudioContext()`（复用单例）。

---

## 5. 背词流程的借鉴判断

### 5.1 现状

- `doRate(g)`（[wb-rate.js:135-149](file:///d:/Code/DeLector/static/js/wb-rate.js#L135-L149)）：FSRS 更新 → 保存 → 记录 → `revIdx++` → `renderReview()`。没有动效、没有触觉、没有音效、没有 toast。
- `browsePrev`（`workbench.html:1200`）只做浏览上一张，不会撤销 FSRS 评分。
- 评分按钮已经用「不认识 / 模糊 / 认识」把语义写清（`workbench.html:74-76`），但没有像 Anki/RemNote 那样把下次间隔写在按钮上。
- 工作台的强项就是快：每张卡 3–8 秒。任何逐卡演出都会直接变成时间成本。

### 5.2 值得抄

| 借鉴点 | 来源 | 在 DeLector 的落点 | 成本 |
| --- | --- | --- | --- |
| **撤销最近一次操作** | Anki（Undo）、Bunpro（Undo） | `斩` 后 toast 提供「撤销」；工作台撤销上一次评分 | 中：需要一次反向 PATCH + 重渲染 |
| **统一短触觉** | AnkiMobile / Android 短原语 | 翻面、评分、`斩` 都用一次 15ms tick | 低：已有调用，补 `斩` 即可 |
| **可关闭反馈** | Apple HIG（make motion optional）、Anki（Reduce motion） | 一个「触觉/音效」设置；动效尊重系统 reduce | 低：一个开关 + 条件 |
| **说清后果** | Anki 按钮上的下次间隔、RemNote 四档 | `斩` toast：「已移入已掌握 · 可随时重返」 | 低 |
| **手势防冲突** | AnkiMobile 竖向滑动必须从边缘开始 | 保持现有 `touch-action: pan-y` + 70px 水平阈值，不劫持竖向滚动 | 0：现状已对齐 |
| **把庆祝留给完成态** | Duolingo 白皮书、WaniKani 升级 | 重档动画放到「今日复习完成」空态/会话总结 | 中 |

### 5.3 看着好但会拖慢复习

| 做法 | 为什么在 DeLector 里不划算 |
| --- | --- |
| 每张卡 confetti / XP / 连击 | Duolingo 的练习约 10–30 秒一道，DeLector 卡片 3–8 秒一张；300ms × 100 张 ≈ 30s |
| 每张卡都落印 | 印章是「终态」语义，评分为「中间态」；每张都盖会让印章贬值 |
| 每张卡都播音效 | 听觉疲劳；静音模式下违反用户预期；还会和 TTS 抢焦点 |
| 500ms 卡片飞出 | Anki 的核心优势是速度；100 张就是 50s |
| `斩` 前弹确认框 | 比 undo 更慢、更烦；Anki/Bunpro 都给 undo，不给确认框 |

### 5.4 移动端根本用不了

| 能力 | 移动端现实 |
| --- | --- |
| iOS 触觉 | Safari / WKWebView 不支持 `navigator.vibrate`；网页拿不到 Taptic Engine |
| Android 触觉 | 引擎支持，但宿主 APK 必须声明 `VIBRATE`；本仓当前没有 |
| 桌面触觉 | 无 |
| 触屏 hover | 不存在；按压反馈必须靠 `:active` 或 pointer 事件 |
| 富触觉（振幅/语义） | Web API 不暴露；需要原生桥 |
| 音效 | 静音开关会静音非必要音效；音频焦点可能被 TTS 占用 |

### 5.5 推荐落地顺序

1. **轻档 + `VIBRATE` 权限 + 真机验证**（最小 PR，先止血）。
2. **中档落印 + `countUp` + `斩` 的 undo toast**（核心体验）。
3. **工作台统一触觉 + 撤销上次评分**（背词流程，不动物效）。
4. **重档只用于完成态**，如果确实需要，再单独走 ADR。

---

## 6. 风险

| 风险 | 触发条件 | 缓解 |
| --- | --- | --- |
| **低端机掉帧** | 3D 卡 + 伪元素动画 + 整卡 `innerHTML` 同时发生 | 只动 `opacity` / `transform`；不要动画 `box-shadow` / `filter`；不常驻 `will-change`；6x CPU 降速跑一遍 |
| **`reduce` 下退化** | 全局 reduce 只压动画时长，JS 仍在等 180ms | JS 读 `prefersReducedMotion()`，`sealMs = 0`；CSS 显式 `animation: none` |
| **误触 / 手势冲突** | 按钮约 23–25px 高；卡片本身可点击翻面 | 把可点区域做到 44pt/48dp（视觉内缩，padding 外扩）；保留 `event.stopPropagation()`；Pointer 监听已过滤 `[onclick]` |
| **双击重复 PATCH** | `toggleMaster` 没有防抖 | `btn.disabled` 或在途锁；失败时恢复 |
| **音效无法关闭** | 直接 `play()`，没有开关 | 默认关闭；独立设置；尊重静音；不和 TTS 抢焦点 |
| **触觉权限缺失** | manifest 无 `VIBRATE` | 加权限 + 重新打包；真机验证；失败则静默降级 |
| **语义误导** | 印章写「已掌握」，但实际可一键重返 | toast 说明「已移入已掌握，可随时重返」；文案可改为「已归档」 |
| **ADR 漂移** | 重档新增 500ms/位移 | 重档必须登记 ADR 例外；否则只做中档 |
| **循环动画** | 想加「印章呼吸/发光」 | 不新增第 8 处循环；若坚持，必须说明为什么现有 7 处白名单不够 |

---

## 7. 验收建议（未来实现时）

- **视觉**：截 0ms / 100ms / 180ms 三帧；印章可见；`#cards-container` 无布局跳动（CLS ≈ 0）。
- **性能**：DevTools Performance + 6x CPU throttle；无 >50ms 长任务；目标机 ≥50fps。
- **探针**：扩展 `tests/test_cards_deck_tap_probe.py`，钉住「斩按钮不触发翻面/切卡」（现有 `interactiveTargetIgnored` 已覆盖 `.card-master-btn`），再加「`is-mastering` 不影响滑动」。
- **触觉**：带 `VIBRATE` 的真机，`navigator.vibrate(15)` 返回 `true` 且能感知；记录静音/DND/省电模式行为。
- **reduce**：模拟 `prefers-reduced-motion: reduce`，无印章动画、无 180ms 等待、卡片立即替换。
- **撤销**：`斩` → 撤销 → 卡片回到原分段，计数回退。

---

## 8. 来源

> 抓取日期均为 **2026-11-07**（Asia/Shanghai）。

| 类型 | 来源 | 用途 |
| --- | --- | --- |
| `[B]` | [MDN – Navigator.vibrate()](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/vibrate) | WebView Android 支持；sticky activation；静音/DND |
| `[B]` | [Chrome for Developers – WebView overview](https://developer.chrome.com/docs/webview) | Vibration API 需要 `android.permission.VIBRATE` |
| `[B]` | [W3C – Vibration API Implementation Report](https://w3c.github.io/vibration/reports/implementation.html) | Blink 实现现状；WebKit 从未支持 |
| `[B]` | [Material 3 – Easing and duration tokens](https://m3.material.io/styles/motion/easing-and-duration/tokens-specs) | short/medium/long 时长与 easing |
| `[B]` | [Material 3 – Motion overview](https://m3.material.io/styles/motion/overview/specs) | Expressive spring physics |
| `[B]` | [Apple HIG – Motion](https://developer.apple.com/design/human-interface-guidelines/motion) | 动效要有目的、可关闭、用触觉/音频补充 |
| `[B]` | [Apple HIG – Playing haptics](https://developer.apple.com/design/human-interface-guidelines/playing-haptics) | 触觉语义、不要滥用 |
| `[B]` | [Apple HIG – Playing audio](https://developer.apple.com/design/human-interface-guidelines/playing-audio) | 静音开关、音量、非必要音效 |
| `[B]` | [Apple HIG – Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) / [UI Design Tips](https://developer.apple.com/design/tips/) | 44×44pt 触控目标 |
| `[B]` | [Android – HapticFeedbackConstants](https://developer.android.com/reference/android/view/HapticFeedbackConstants) | CONFIRM/REJECT/CLOCK_TICK 等语义 |
| `[B]` | [AOSP – Haptics constants and primitives](https://source.android.com/docs/core/interaction/haptics/haptics-constants-primitives) | CLICK/TICK <20ms；双击原语 |
| `[B]` | [Android – VibrationEffect](https://developer.android.com/reference/android/os/VibrationEffect) | `createOneShot` / predefined effects |
| `[B]` | [Anki Manual – Studying](https://docs.ankiweb.net/studying.html) | Bury/Suspend；按钮上的下次间隔 |
| `[B]` | [Anki Manual – Preferences](https://docs.ankiweb.net/preferences.html) | Reduce motion |
| `[B]` | [AnkiMobile Manual – Preferences](https://docs.ankimobile.net/preferences.html) | Feedback Ticks；四向滑动；竖向需从边缘开始 |
| `[B]` | [AnkiDroid Manual](https://docs.ankidroid.org/) | 手势可配置；振动主要针对通知 |
| `[B]` | [Quizlet Help – Studying with Learn mode](https://help.quizlet.com/hc/en-au/articles/360030986971) | Got it / Study again |
| `[B]` | [Quizlet Help – Using Progress](https://help.quizlet.com/hc/en-us/articles/360048803491-Using-Progress-for-targeted-studying) | Not Studied / Still Learning / Mastered |
| `[B]` | [Duolingo Method whitepaper (PDF)](http://duolingo-papers.s3.amazonaws.com/reports/duolingo-method-whitepaper.pdf) | 每题音效 + 简短庆祝；整节更大奖励 |
| `[B]` | [Duolingo Blog – Building character](https://blog.duolingo.com/building-character/) | 答对动画与 mid-lesson 奖励 |
| `[B]` | [Memrise Support – Can I ignore words or entire levels?](https://memrise.zendesk.com/hc/en-us/articles/360015973918-Can-I-ignore-words-or-entire-levels) | ignore 的平台差异 |
| `[B]` | [Memrise – Can I ignore words I already know?](https://memrisebeta.zendesk.com/hc/en-us/articles/4963156179601-Can-I-ignore-words-I-already-know) | 「I already know this」 |
| `[B]` | [RemNote Help – Understanding spaced repetition](https://help.remnote.com/en/articles/9337171-understanding-spaced-repetition) | 四档评分与下次间隔 |
| `[B]` | [Bunpro – Pricing](https://bunpro.jp/pricing) / [Bunpro Community – Undo](https://community.bunpro.jp/t/question-regarding-the-srs-and-making-mistakes/65057) | Undo、Ghost reviews |
| `[B]` | [WaniKani Knowledge – SRS Stages](https://knowledge.wanikani.com/wanikani/srs-stages/) | Burned 语义与解除 |
| `[B]` | [SuperMemo Help – Glossary (Dismiss)](https://help.supermemo.org/wiki/Glossary) | Dismiss vs Forget |
| `[B]` | [W3C WCAG 2.3.3 – Animation from Interactions](http://w3c.github.io/wcag/understanding/animation-from-interactions.html) | 交互动画可关闭 |
| `[C]` | [DesignSystems.one – Duration & easing](https://www.designsystems.one/foundations/duration-and-easing) | 微交互 50–150ms 等实践值 |
| `[C]` | [Envato – UI sound design](https://elements.envato.com/learn/ui-sound-design-ai) | UI 音效 80–300ms |
| `[B]` | [Material 3 – Structure / touch targets](https://m3.material.io/foundations/designing/structure) | 48×48dp 触控目标 |
