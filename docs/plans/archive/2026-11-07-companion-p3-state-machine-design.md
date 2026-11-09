# 伴读桌宠 P3：生机状态机设计

> 日期：2026-11-07　|　性质：**只出设计，不写实现、不改 `static/`、不开 PR**
> 依赖：P2「禁停区让位」（worktree `D:\Code\DeLector-companion-p2`，分支 `fix/companion-p2-no-parking`，**尚未合并**；本文引用其代码时行号会漂移）
> 关联：[气泡与生机调研](../research/2026-11-07-companion-bubble-and-vitality-research.md)、[ADR-0030 动效系统](../adr/2026-11-07-adr-0030-frontend-motion-system.md)、[ADR-0029 §16](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)

---

## 0. 结论先行

**最小可用版本 = 5 个状态：`idle` / `thinking` / `speaking` / `dragging` / `error`。**

- 它只依赖今天已经存在的信号：默认态、agent turn 在途、`say()` 气泡、pointer 拖拽、stream error。
- 不新增任何常驻循环动画，不新增 `setInterval` / `rAF`，不改 P2 的让位算法。
- 新增的只有两个短定时器：turn 看门狗（120s）与 error 驻留（30s）；speaking 复用现有 6.5s 气泡定时器。

**晚点做，按依赖顺序：**

| 批次 | 内容 | 为什么可以晚 |
| --- | --- | --- |
| P3.1 | `acting` / `waiting` | 需要把 `tool_start` / `proposal` 接进状态机；两者都已有 SSE 事件，但 P2 合并前不宜同时改 `cp-drawer.js` |
| P3.2 | `sleeping` | 需要空闲时钟 + 功耗裁决；MVP 没有它也不影响「状态不说谎」 |
| 不做 | 自由移动、姿势 morph、口型、多 agent、按工具区分的 acting | 与「不遮挡 / 不打扰 / 不新增常驻循环」直接冲突，见 §8 |

**三条不可协商的约束：**

1. **单一真相源**：任一时刻 `#companion` 只有一 个 `data-state`，由纯函数 `resolveState(conditions)` 求值；禁止用散落的 `classList.add` 拼状态。
2. **不新增 `infinite`**：ADR-0030 §2.6 的白名单仍是 7 处；新状态动画全部是有限次或静态姿势。
3. **肉眼可辨**：状态必须在不打开控制台时看出来（状态点颜色 + 姿势 + `title` 文字），不能只存在于 `data-*` 或 `window` 对象里。这是「静默失败、控件说谎」的直接对策。

---

## 1. 现状与边界

### 1.1 已存在的相关事实

| 事实 | 位置 | 对状态机的含义 |
| --- | --- | --- |
| 默认常驻动画 3 条：`companionIdle` 4s infinite + `charBlink` 4.2s infinite ×2（双眼） | `static/style.css:8219`、`:8509`；调研 §2.6 实测 `getAnimations()` = 3 | `idle` 的基线成本已存在；新状态不能叠加，只能替换 |
| `idle` 动画**无条件**挂在 `.companion-char` 上 | `static/style.css:8210-8222` | 加状态动画前必须把 idle 收进 `[data-state="idle"]`，否则两条 `animation` 争同一个属性 |
| 拖拽只有 `.is-dragging`（关 transition），**不暂停** idle / blink | `static/style.css:8176-8181` | `dragging` 需要显式 `animation-play-state: paused` |
| 无 `visibilitychange` 监听 | 调研 §2.6 | 新增暂停层，不改状态值 |
| `say()` 显示气泡 6.5s 后加 `.hidden` | `static/js/companion.js:975-1002` | `speaking` 的时长直接复用这个定时器，不另起一套 |
| `triggerEmotion()` 用 `is-happy` / `is-wiggle` / `is-sad`，1200ms 后摘类，CSS 带 `!important` | `static/js/companion.js:1026-1036`；`style.css:8542-8584` | 情绪是**表达层**，不是状态；必须规定它与状态动画谁让谁 |
| `cp-state.js` 声明了 `streamStage`，但全仓**从未赋值** | `static/js/cp-state.js:26` | 典型「字段看着像真相、实际恒 null」；P3 不得复用它，见 §6.5 |
| `#companion` 是 `role="status" aria-live="polite"` | `static/index.html:3236` | 不要把状态文本写进这个 live region，否则每次状态切换都被朗读 |
| P2 新增 `is-settling` 260ms 滑动 + `refreshTimer` 120/160/240/280ms | P2 `cp-drawer-capsule.js`、`style.css` | 状态切换与气泡求解必须排在 settle 之后，否则对着旧锚点算位置 |
| P2 新增 `is-over-no-park`（拖拽期半透明 + 虚线） | P2 `style.css` | 它只是拖拽期反馈，不参与状态判定 |

### 1.2 本轮边界

- 不改 P2 三个文件（`companion.js` / `cp-drawer-capsule.js` / `companion-obstacles.js`）；本文只定义接口与规则。
- 不实现 agent 状态 UI、不在气泡里放按钮、不做选区操作条。
- 不把「设计完成」记成「已验证」；所有未实测项集中在 §8.3。

---

## 2. 状态与事件

### 2.1 状态集合

沿用调研的 8 个名字，不多造同义词：

| 状态 | 含义 | 数据条件（布尔） |
| --- | --- | --- |
| `idle` | 默认；无 agent 活动、无气泡 | 所有条件为假 |
| `thinking` | turn 在途，但当前没有工具在跑 | `turnInFlight && !toolActive` |
| `acting` | 某个工具正在执行 | `turnInFlight && toolActive` |
| `speaking` | 气泡正在展示（含 `done` 后的庆祝） | `bubbleVisible` |
| `waiting` | 有 proposal 等待用户确认 | `proposalPending` |
| `dragging` | 用户正在拖拽角色本体 | `dragging` |
| `sleeping` | 长时间无任何交互（P3.2） | `sleeping` |
| `error` | 本轮失败 / 连接中断 / 看门狗超时 | `errorLatched` |

> 条件不是「事件」，而是「当前是否成立」。状态是条件的纯函数，见 §2.2。

### 2.2 求值方式：条件求值，不是事件链

```js
// 拟新增 static/js/companion-lifecycle.js —— 纯函数，零 DOM、零定时器
export function resolveState(c) {
  if (c.dragging) return 'dragging';
  if (c.errorLatched) return 'error';
  if (c.proposalPending) return 'waiting';
  if (c.turnInFlight && c.toolActive) return 'acting';
  if (c.turnInFlight) return 'thinking';
  if (c.bubbleVisible) return 'speaking';
  if (c.sleeping) return 'sleeping';
  return 'idle';
}
```

为什么不用「from → to」硬编码：现有 UI 的信号本来就是条件式的（`inFlight`、工具在跑、气泡在不在）。用事件链会立刻出现「done 之后忘了清 thinking」「error 后 proposal 永远被盖住」这类说谎。条件求值只有一处真相，且可以在 Node 里穷举测试。

实现时由 `companion.js` 维护条件对象，任何事件只改条件，然后统一调用 `applyState()` 写一次 `data-state`。

### 2.3 优先级

```
dragging (100)
  > error    (90)
  > waiting  (80)
  > acting   (70)
  > thinking (60)
  > speaking (50)
  > idle     (10)
  > sleeping (0)
```

与调研 §5.3 的差异只有一条：**error 提到 waiting 之前**。理由：proposal 停在那里时如果新一轮请求失败，把失败藏在「等待确认」后面就是控件说谎。error 不清除 `proposalPending`；error 条件解除后，`waiting` 会自动回来（条件求值的好处）。

### 2.4 完整转移表

| # | 触发 | 条件变化 | 从 | 到 | 可被打断 | 超时 / 回落 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 用户按下并移动 >5px | `dragging=true` | 任意（含 error / speaking） | `dragging` | 是（pointerup） | 无；pointerup 立即重算 |
| 2 | 用户松手 | `dragging=false` | `dragging` | `resolveState()` | — | 不盲目回 idle；若 `errorLatched` 仍在则进 `error` |
| 3 | 发送 prompt / 流开始 | `turnInFlight=true` | `idle` / `speaking` / `waiting` | `thinking` | 是 | 看门狗 120s |
| 4 | `tool_start` | `toolActive=true` | `thinking` | `acting` | 是 | 看门狗重置；`tool_end` 回落 |
| 5 | `tool_end`（成功） | `toolActive=false` | `acting` | `thinking` | 是 | 回到 turn 态 |
| 6 | `tool_end`（工具报错） | `toolActive=false` | `acting` | `thinking` | 是 | **不进入 error**；错误只留在工具 chip 里（见 §8.2） |
| 7 | `proposal` 事件 | `proposalPending=true` | `thinking` / `acting` / `speaking` | `waiting` | 是 | 无超时；静态点，无循环成本 |
| 8 | 用户发送新 prompt | `proposalPending=false`；`turnInFlight=true` | `waiting` | `thinking` | 是 | 旧 proposal 仍留在卡片里，但不再代表「当前阻塞」 |
| 9 | `done` 且有正文 | `turnInFlight=false`；`bubbleVisible=true` | `thinking` / `acting` | `speaking` | 是 | 6.5s 气泡定时器 |
| 10 | 气泡定时器到期 / 被焦点抑制 | `bubbleVisible=false` | `speaking` | `resolveState()` | — | 通常为 `idle` |
| 11 | `error` 事件 / 连接中断 | `errorLatched=true` | 除 `dragging` 外的任意 | `error` | 是 | 1.2s 动画 + 30s 状态点驻留 |
| 12 | `error` 发生在拖拽中 | `errorLatched=true`，但 `dragging` 仍为真 | `dragging` | `dragging`（视觉不变） | — | pointerup 后立即显示 `error` |
| 13 | 看门狗：在途 120s 无任何 SSE 字节 | `errorLatched=true` | `thinking` / `acting` | `error` | 是 | 见 §2.6 |
| 14 | 用户点击角色确认 / 新 turn 开始 | `errorLatched=false` | `error` | `resolveState()` | — | 30s 到期也自动解除 |
| 15 | 180s 无指针 / 键盘 / 滚动 / agent（P3.2） | `sleeping=true` | `idle` | `sleeping` | 是 | 任意输入唤醒 |
| 16 | 任意输入 / agent 事件 | `sleeping=false` | `sleeping` | `resolveState()` | — | — |
| 17 | `visibilitychange` → hidden | **无状态变化** | 任意 | 同一状态 | — | 只加 `data-paused`，见 §5.3 |
| 18 | `say()` 但气泡被模态 / 拖拽挂起 | `bubbleVisible` 保持 false | 当前状态 | 不变 | — | 松开 / 模态关闭后再决定是否显示 |
| 19 | 编辑框 `focusin` | `bubbleVisible=false`（抑制） | `speaking` | `resolveState()` | — | 失焦后不补播，见 §4.4 |

### 2.5 必须允许抢占的转移（硬要求）

任何实现都必须通过下面这组用例，否则状态机不予合入：

1. **`speaking` 期间用户拖动** → 立刻 `dragging`，气泡隐藏；松手后若气泡定时器未过期才恢复 `speaking`，否则回 `idle`。
2. **`thinking` / `acting` 期间 error** → 立刻 `error`；不得等 turn 结束。
3. **`dragging` 期间 error** → 视觉保持 `dragging`（避免拖拽中角色突然换姿势），`errorLatched` 挂起，松手后立刻显示 `error`。
4. **`waiting` 期间用户发新 prompt** → `thinking`；proposal 不再阻塞当前状态，但卡片不删除。
5. **`error` 期间用户拖动** → `dragging` 优先；松手后回到 `error`，直到确认 / 30s。
6. **`speaking` 期间下一轮开始** → `thinking`，气泡文字可以继续显示（文字与姿态是两个通道）。
7. **`pointerup` 后禁止直接写 `idle`** → 必须重新求值，防止把在途 turn 或未确认 proposal 抹掉。
8. **`visibilitychange` 不得改状态** → 只暂停动画；回到前台仍然是同一个状态。

### 2.6 超时与回落

| 机制 | 值 | 起点 | 取消条件 | 说明 |
| --- | --- | --- | --- | --- |
| 气泡展示 | 6500ms | `say()` | 新 `say()` / 拖拽 / 模态 / 焦点抑制 | 已有，复用；不新增定时器 |
| turn 看门狗 | 120000ms | `turnInFlight=true` 或任意 SSE 事件 | 收到 `done` / `error` / 任一新事件 | 重置点是**任意字节**，不只是 `delta` |
| error 动画 | 1200ms | `errorLatched=true` | — | 复用 `companionDroop` |
| error 驻留 | 30000ms | `errorLatched=true` | 用户点击角色 / 新 turn | 到期后 `errorLatched=false`，退回 `resolveState()` |
| sleeping 计时 | 180000ms | 最后一次输入 / agent 事件，且页面可见（P3.2） | 任意输入 / agent / 页面隐藏 | 页面隐藏时暂停计时，不累计 |
| waiting | 无 | — | 用户处理或发新 prompt | 静态点，不耗电；不设超时，避免假装「已读」 |

看门狗数值是初值，不是定论：`tool_start` 到 `tool_end` 之间可能包含一次完整 LLM 调用。落地前必须量一次真实最长工具耗时；若超过 90s，上移到 180s 而不是缩小。判据是「有字节就不算卡死」。

---

## 3. 动效映射

### 3.1 逐状态映射

所有状态都通过 `#companion[data-state="..."]` 选择，不新增状态 class。`data-state` 是唯一开关。

| 状态 | CSS 钩子 | 动画 / 表达 | 循环？ | reduce 降级 | 运行时动画数上限 |
| --- | --- | --- | --- | --- | --- |
| `idle` | `[data-state="idle"] .companion-char` + `.char-eye` | 复用 `companionIdle` 4s infinite、`charBlink` 4.2s infinite | **是**（白名单原有 2 项） | `animation: none`，静止睁眼 | 3（现状实测值，不增加） |
| `thinking` | `[data-state="thinking"] .companion-char` | 新 `companionThink`：2.4s，±2° 只动角色；**3 次后停在终态** | 否（有限次） | `animation: none` + 静态 `rotate(2deg)` | 1 → 0（7.2s 后） |
| `acting` | `[data-state="acting"] .companion-char` | 复用 `companionWiggle` keyframe，0.6s × 1 | 否 | `animation: none` | 1 → 0 |
| `speaking` | `[data-state="speaking"] .companion-char` + 气泡 | 复用 `companionJump` keyframe，1.1s × 1；气泡 `pop-anim` 0.3s（已有） | 否 | 只保留气泡文字，无跳跃 | 2 → 1 → 0 |
| `waiting` | `[data-state="waiting"]` + 状态点 | 无角色动画；状态点用 `--motion-enter` 180ms 淡入一次 | 否 | 静态点 + 文字 | 0 |
| `dragging` | `.is-dragging` + `[data-state="dragging"]` | 现有 `scale(1.06)` + 阴影；**所有后代 `animation-play-state: paused`** | 否 | 同左（瞬时缩放属于直接操作） | 0（暂停） |
| `sleeping` | `[data-state="sleeping"]` | 静态闭眼（`.char-eye { transform: scaleY(.1) }`），角色不呼吸 | 否 | 同左 | 0 |
| `error` | `[data-state="error"] .companion-char` | 复用 `companionDroop` keyframe，1.2s × 1，之后静态 | 否 | `animation: none` + 静态下垂 | 1 → 0 |

**只新增 1 个 keyframe：`companionThink`。** `companionWiggle` / `companionJump` / `companionDroop` 都复用，只换时长与次数。

### 3.2 为什么没有第 8 个 `infinite`

ADR-0030 §4 的失败信号第 4 条是「新增第 8 处 `infinite` 且不在白名单」。本设计用两个决定规避：

1. `thinking` 用 **有限次**（3 × 2.4s），之后停在倾斜姿势。思考通常几十秒内结束；超过 7.2s 的部分没有动画，但姿态仍是「思考」，不是 idle。
2. `sleeping` **不做 8s 呼吸循环**，只做静态闭眼。呼吸循环正是「用户睡着时机器还在出帧」的典型，收益低、功耗不确定。

因此 `infinite` 仍是 7 处，ADR-0030 不需要重开。若未来一定要给 `waiting` 加呼吸点，必须作为独立决策改 ADR，而不是在本设计里顺手加。

### 3.3 token 使用

| token | 用在哪 | 不用在哪 |
| --- | --- | --- |
| `--motion-enter`（180ms） | 状态点淡入、状态点颜色过渡 | 不用于角色姿势切换（姿势是瞬时替换） |
| `--ease-editorial` | 上面两个过渡 | — |
| `--motion-press` | 不使用 | 状态不是按压反馈 |
| `--motion-count` / `--motion-stagger-step` | 不使用 | — |

`companionThink 2.4s` / `acting 0.6s` / `error 1.2s` 是**角色动画时长**，不是 ADR-0030 那 5 个 UI 一次性动效 token。为避免数值漂移，在 `style.css` 的状态区块顶部用一张注释表登记三个数值，禁止各处手写；不把它们塞进 token 集合。

### 3.4 情绪类与状态的关系

现有 `is-happy` / `is-wiggle` / `is-sad` 用 `animation ... !important` 直接抢 `.companion-char` 的 `animation` 属性。若不处理，`thinking` 时触发一次 `wiggle` 会把思考姿势顶掉。

规则：

- 情绪类是**表达层**，不是状态；它不写 `data-state`。
- 只允许在 `idle` / `speaking` 下挂情绪类；进入其他状态时由 `applyState()` 统一摘掉 `is-happy/is-wiggle/is-sad`。
- `error` / `dragging` / `sleeping` 下**禁止**挂情绪类（情绪会掩盖真实状态）。
- 情绪结束仍由原 1200ms 定时器摘类，不改 API。

这样「姿态」只有两个来源：`data-state` 与情绪类，且后者被前者约束；不会出现两个 `animation` 同时跑。

---

## 4. 与 P2 让位规则的交互

P2 的核心是「胶囊落点 / 气泡四侧求解都避开运行时禁停区」，并新增了 `is-settling`（260ms 滑动）、`is-over-no-park`（拖拽期反馈）、`settleIfNeeded()` 与 `notifyBubble()`。状态机必须与它们排好时序。

### 4.1 `dragging`：约束失效，落点不失效

| 问题 | 结论 |
| --- | --- |
| 拖拽时禁停区是否失效？ | **约束失效**：允许手指拖过、允许瞬间压在编辑区上，不做硬阻挡（与「自由摆放」心智一致）。 |
| 松手后呢？ | **落点不失效**：`settleIfNeeded()` 把角色滑到最近安全位；这是 P2 已有逻辑，状态机不重复实现。 |
| 视觉反馈 | 保留 P2 的 `is-over-no-park` 半透明 + 虚线；它不是状态，不与 `data-state` 冲突。 |
| 状态动画 | `dragging` 期间所有角色动画暂停；拖拽结束且 settle 完成后再恢复。 |
| 气泡 | 拖拽开始立即隐藏；不要在每帧 `move` 里 `repositionBubble()`（P2 现在每次 move 都调，P3 应改为松手后一次）。 |

### 4.2 `is-settling`：气泡求解必须等落点稳定

P2 的 `applyVisualPosition()` 在写入坐标后**立即** `notifyBubble()`，而滑动动画持续 260ms（类名 320ms 后摘除）。这意味着气泡会在滑动起点算一次位置，然后胶囊继续移动。

规则：

1. 胶囊在拖拽结束 / 自动让位时派发 `companion:settle-start` 与 `companion:settle-end`（或在 `is-settling` 摘除时派发一次）。
2. 状态机在 `settle-start` 到 `settle-end` 之间**不求解气泡**；把 `bubbleVisible` 的展示请求挂起。
3. `settle-end` 后再调用一次 `repositionBubble()`；若气泡定时器已过期，则直接回 `idle`。
4. 这条同样适用于「状态切换导致胶囊被联合让位」的情况（P2 `companion.js` 里的锚点候选逻辑）。

### 4.3 `speaking`：用户又在打字怎么办

- 编辑框 `focusin`（`EDITABLE_SELECTOR`）时，气泡**立即隐藏**并取消 6.5s 定时器；`bubbleVisible=false`，状态回落到 `thinking` 或 `idle`。
- 理由：气泡会盖住输入行 / 标题；键盘弹起时 `visualViewport` 变矮，继续显示只会增加让位计算与视觉噪声。
- 失焦后**不补播**；下一次 `say()` 正常显示。用户已经在打字，补播一条旧消息是打扰。
- P2 的禁停区已经把输入框算进去，气泡会优先选不压输入框的一侧；但「不压」不等于「不挡视线」，所以仍用隐藏作为硬规则。

### 4.4 模态 sheet：P2 的气泡挂起有一个过期复活风险

P2 在 `repositionBubble()` 里检测 `.writer-sidebar.mobile-panel-open`：打开时给气泡加 `.hidden` 并置 `bubbleSuspendedByModal = true`；关闭后无条件 `classList.remove('hidden')`。

风险：若模态打开超过 6.5s，`bubbleTimer` 已经把气泡标记为过期；关模态时 P2 仍会把它显示出来，于是**一条早已过期的消息复活**。这正是「控件说谎」的另一种形态。

P3 的接口要求（供 P2 合并前对齐，或 P3 落地时修）：

- 挂起时不要只记布尔，要记「挂起时的剩余展示时间 / 是否已过期」。
- 关闭时只有 `bubbleTimer` 未过期才恢复；已过期则保持隐藏并回 `idle`。
- 状态机侧：模态打开期间 `bubbleVisible` 必须为 false，不能因为 DOM 里气泡元素存在就判为 speaking。

### 4.5 事件时序表

| 时刻 | 胶囊 | 气泡 | `data-state` |
| --- | --- | --- | --- |
| pointerdown | 记录起点，收集禁停区 | 不变 | 不变（未过 5px 阈值） |
| 拖拽开始（>5px） | 加 `.is-dragging` | 隐藏 + 取消展示请求 | `dragging` |
| pointermove | clamp + 半透明提示 | 保持隐藏 | `dragging` |
| pointerup | 摘 `.is-dragging`，`settleIfNeeded()` | 挂起 | `dragging`（直到 settle 完成） |
| settle 260ms | `.is-settling` 滑到安全位 | 挂起 | 重新求值；如 `errorLatched` 则 `error` |
| settle 结束 | 摘 `.is-settling`，派发 `settle-end` | 若未过期则恢复并求解 | `resolveState()` |
| 编辑框 focusin | 照常让位 | 隐藏 | `speaking` → `idle`/`thinking` |
| 页面 hidden | 不改位置 | 不改 DOM | 不变，加 `data-paused` |

---

## 5. 性能与功耗

### 5.1 定时器清单（全量）

| 定时器 | 值 | 归属 | 是否新增 | 清理点 |
| --- | --- | --- | --- | --- |
| 气泡展示 | 6500ms | 现有 `say()` | 否 | 新 `say()` / 隐藏时 |
| 情绪摘类 | 1200ms | 现有 `triggerEmotion()` | 否 | 类已摘；无副作用 |
| settle 滑动 | 320ms | P2 | 否 | `destroy()` |
| 让位合并刷新 | 120/160/240/280ms | P2 | 否 | `destroy()` |
| turn 看门狗 | 120000ms | 状态机 | **是** | 收到任意事件 / `done` / `error` / `destroy()` |
| error 驻留 | 30000ms | 状态机 | **是** | 确认 / 新 turn / `destroy()` |
| sleeping 计时 | 180000ms | P3.2 | 延后 | 任意输入 / 页面隐藏 |

硬规则：

- **禁止 `setInterval`**；所有周期行为用「单次 `setTimeout` + 事件重置」表达。
- **禁止 `requestAnimationFrame` 驱动角色**；CSS 动画负责全部帧。
- 同一时刻最多 2 个状态机定时器（看门狗 + error 驻留）；它们不重叠触发动画。
- `destroy()` 必须清掉全部定时器与事件监听；页面切视图不销毁胶囊，但离开应用（PWA 关闭）无泄漏。

### 5.2 单循环约束

运行时动画数量上限（`document.getAnimations()`，验收直接断言）：

| 状态 | 上限 | 说明 |
| --- | --- | --- |
| `idle` | 3 | 现状基线；不增加 |
| `thinking` | 1（7.2s 后 0） | 有限次 |
| `acting` | 1（0.6s 后 0） | 一次性 |
| `speaking` | 2（1.1s 后 1，6.5s 后 0） | 跳跃 + 气泡 pop |
| `waiting` | 0 | 静态点 |
| `dragging` | 0（running） | 全部 paused |
| `sleeping` | 0 | 静态 |
| `error` | 1（1.2s 后 0） | 一次性 |
| reduce（任意） | 0 | 全局兜底 |

「不允许多个常驻动画同时跑」的实现保证：`companionIdle` 与 `charBlink` 只在 `[data-state="idle"]` 下声明；其他状态的选择器覆盖 `animation` 属性；情绪类由 `applyState()` 摘除。三者互斥，不靠运气。

### 5.3 页面隐藏

- 监听 `visibilitychange`：hidden → `#companion[data-paused="true"]`；visible → 移除。
- CSS：`[data-paused="true"] .companion-char, [data-paused="true"] .char-eye, [data-paused="true"] .companion-bubble { animation-play-state: paused; }`
- **不改 `data-state`**：agent 可能在后台继续跑，回到前台应显示真实状态，而不是被强制 idle。
- 回到前台时重新求值一次（防止隐藏期间 `done` 已让条件变化）。
- 隐藏期间不启动 sleeping 计时；已 sleeping 则保持睡姿。
- 现有气泡 6.5s 定时器继续走：隐藏期间到期就直接过期，回前台不补播。

### 5.4 低电量 / 省流

- 不接 Battery Status API（可用性差、隐私敏感、Chrome 已收紧）。
- 用 `navigator.connection && navigator.connection.saveData === true` 作为「省流 = 静止」的信号：此时按 reduce 处理（无状态动画、静态姿势、状态点仍保留）。
- `saveData` 在会话中途变化不补播（与 ADR-0030 §2.7.4 一致）。
- 低电量策略不做额外分支：`sleeping` 本身就是静态姿势，没有可省的循环。

### 5.5 明确禁止

- 用 `width / height / top / left / margin / filter` 做状态动画（触发布局或重绘）。
- 在 `pointermove` 里求解气泡或遍历禁停区（P2 已收集一次；状态机不得再加）。
- 用 `transition: all`（读取终态时的经典坑，见 `docs/agents/motion-verification.md`）。
- 在页面隐藏时启动新的定时器 / 动画。
- 给每个工具新增一条动画。

---

## 6. 可观测性

目标：用户或验收者**只靠肉眼和一次悬停**就能说出当前状态；不打开控制台、不读源码。

### 6.1 单一真相源

- `#companion` 上只有一个 `data-state`，取值固定为 §2.1 的 8 个字符串之一。
- 不在其他元素上写第二份状态 class；CSS 一律用 `[data-state="..."]`。
- `window.Companion.state` 提供只读 getter，供探针与调试；它不是第二份真相，而是同一个字段的投影。
- 每次变化派发 `companion:statechange`（`detail: {from, to, reason}`），便于探针记录，不驱动 UI。

### 6.2 视觉编码（肉眼可辨）

用 `.companion-char::after` 做一个 7px 状态点（`pointer-events: none`），不新增 DOM，不改 `index.html`：

| 状态 | 点的颜色 | 姿势 | 点的可见性 |
| --- | --- | --- | --- |
| `idle` | `var(--muted)` | 基线呼吸 + 眨眼 | 常显（灰） |
| `thinking` | `var(--ink)` | 2° 侧头 | 常显（墨） |
| `acting` | `var(--ink)` | 0.6s wiggle | 常显（墨） |
| `speaking` | `var(--accent)` | 1.1s 跳跃 + 气泡 | 常显（橙） |
| `waiting` | `var(--amber)` | 静止直立 + 点 | 常显（琥珀） |
| `dragging` | `var(--ink)` | 放大 1.06 + 阴影 | 拖拽期常显 |
| `sleeping` | `var(--muted)` | 闭眼、整体降透明度 | 常显（灰，更暗） |
| `error` | `var(--coral)` | 1.2s 下垂 | 常显（珊瑚红） |

关键：**idle 也有点**（灰色）。如果 idle 不显示点，用户无法区分「空闲」与「状态机坏了没渲染」，又会回到静默失败。

颜色不足以覆盖色盲用户，所以还有姿势与文字两层（§6.3），颜色只是最快的通道。

### 6.3 文字与无障碍

- `#companion-char` 的 `title` 更新为「伴读 · 思考中」这类短语；桌面悬停可读。
- `#companion-avatar` 的 `aria-label` 同步状态（例如「伴读角色设置与对话 · 正在思考」）。它是按钮，不是 live region，不会每次切换都朗读。
- **不要**把状态文字写进 `#companion` 本身：它是 `role="status" aria-live="polite"`，每次状态切换都会被读屏播报，打断阅读。
- 气泡文字继续走现有 `say()`；状态变化不自动改气泡文案，避免「两套文案打架」。

### 6.4 探针与验收判据

1. **纯函数单测**（Node，无 DOM）：覆盖 §2.5 的 8 条抢占用例 + 条件穷举；`resolveState` 必须对每个组合返回确定值。
2. **DOM 探针**：模拟事件序列，断言 `data-state`、状态点颜色（`getComputedStyle(el, '::after').backgroundColor`）、`document.getAnimations().length` 上限（§5.2）。
3. **截图验收**：1440×900 与 393×852 各截 8 个状态；不看代码能凭点色 + 姿势说出状态。截图存 `_artifacts/`，不入 git。
4. **隐藏页**：CDP 切 hidden 后断言所有动画 `playState === 'paused'`，且 `data-state` 不变。
5. **reduce**：`Emulation.setEmulatedMedia` 后断言 `getAnimations().length === 0`，姿势仍与状态对应。
6. **看门狗**：假定时器推进 120s，断言 `data-state="error"` 且 `reason="watchdog"`。
7. **过期不复活**：模态挂起超过 6.5s，关闭后气泡必须仍隐藏。

### 6.5 已知说谎点（P3 必须处理或明确绕开）

| 说谎点 | 现状 | 处理 |
| --- | --- | --- |
| `streamStage` | `cp-state.js:26` 声明，全仓从未赋值 | 不复用；P3.0 顺手删除或改成 `resolveState` 的派生值，避免下一个人以为它在工作 |
| P2 模态挂起 | 关闭时无条件 `remove('hidden')` | 按 §4.4 补过期判断 |
| `.is-dragging` 不暂停动画 | `style.css:8176` 只关 transition | 用 `[data-state="dragging"]` 统一暂停 |
| `#companion` 的 `aria-live` | 状态文字若写进去会被播报 | 状态只写 `title` / avatar `aria-label` |
| 情绪类 `!important` | 可覆盖状态动画 | 非 idle/speaking 状态由 JS 摘类 |

---

## 7. 实施切分（P2 合并后再动）

> 以下只是计划，不是本轮交付。每批都必须通过 §6.4 的对应判据。

### P3.0 —— MVP（5 状态）

| 任务 | 写集 | 验收 |
| --- | --- | --- |
| 纯函数状态求值 | 新增 `static/js/companion-lifecycle.js` | 单测覆盖 8 条抢占 + 条件穷举 |
| 条件容器与 `data-state` 写入 | `static/js/companion.js` | DOM 探针；`window.Companion.state` |
| SSE → 条件桥（仅 turn / error） | `static/js/cp-drawer.js` | 真实/模拟流：start → thinking，error → error |
| 拖拽 / settle 事件 | `static/js/cp-drawer-capsule.js`（P2 文件，合并后改） | 拖拽期 `dragging`，settle 后重算 |
| 样式与状态点 | `static/style.css` | 8 状态截图；`infinite` 仍为 7；reduce 0 动画 |
| 看门狗 + error 驻留 | `companion.js` | 假定时器；真实流不误报 |

### P3.1 —— `acting` / `waiting`

- 接 `tool_start` / `tool_end` / `proposal`；
- `waiting` 的 proposal 生命周期：新 prompt 清除阻塞语义，卡片保留；
- 工具报错**不**升级为 `error`；
- 不新增状态点呼吸循环。

### P3.2 —— `sleeping`

- 180s 空闲时钟；页面隐藏暂停计时；
- 静态闭眼，不做 8s 呼吸；
- `saveData` 下等同 reduce；
- 任意输入 / agent 事件立即唤醒，不播「惊醒」动画。

### P3.3 —— 明确不在本线

姿势 morph、按工具区分的动画、多 agent 来源、自由移动、气泡内交互。见 §8。

---

## 8. 风险与不做项

### 8.1 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 看门狗数值定错 | 长工具调用被误判为卡死 | 先量真实最长工具耗时；120s 起步，宁可放宽 |
| 状态点改变默认视觉 | 用户觉得桌宠「多了个点」 | 7px、低饱和、idle 用 `--muted`；落地前视觉签字 |
| `data-state` 与情绪类争 `animation` | 姿势闪烁 | §3.4 的摘类规则 + 截图验收 |
| P2 未合并导致接口漂移 | 拖拽 / settle 事件对不上 | 以 P2 合并后的实际 API 为准，先对齐再接 |
| 页面隐藏时 CSS 动画是否真停 | 合成器行为未在真机验证 | 用 `getAnimations().playState` 验收；真机另测 |
| `saveData` 判定不可靠 | 省流用户仍看到动画 | 只作为增强，不作为唯一降级；reduce 才是硬闸 |
| 状态点颜色对比度不足 | 低视力 / 色盲无法分辨 | 姿势 + `title` 兜底；必要时用形状差异（未定） |

### 8.2 明确不做

| 不做项 | 理由 |
| --- | --- |
| 自由移动 / 漫游 | 调研 §6：默认关闭；与不遮挡输入区直接冲突；需要额外时钟与禁停区重抽 |
| 重力 / 抛掷 / 惯性 | 需要持续物理循环，功耗与打扰都不可控 |
| 跟随鼠标 | 移动端无 hover 语义，持续分散注意力 |
| `waiting` 的呼吸点 | 会引入第 8 个 `infinite`，必须单独改 ADR-0030 |
| `sleeping` 的 8s 呼吸 | 同上；静态闭眼已足够表达 |
| 姿势 morph / 状态间补间 | 单 SVG 无法低成本 morph；伪平滑不如瞬时替换诚实 |
| 按工具区分的 `acting` 动画 | 工具数量会增长，动画数量跟着增长；一个 wiggle 足够 |
| 口型同步 / 语音驱动 | 需要音频分析常驻循环，明确违反功耗约束 |
| 多 agent 来源 / 多宠物 | 无产品需求；先留 `data-agent-source`，不实现 |
| 工具报错 → `error` 状态 | 工具失败是可恢复的，升级为全局错误会狼来了；错误留在 chip |
| 把状态写进 `aria-live` 区域 | 每次切换都打断读屏 |
| 持久化状态到 localStorage | 刷新后必须是 idle；旧状态复活就是说谎 |
| 在气泡里放确认按钮 | 确认走 drawer / 未来写作条，桌宠不是操作入口 |

### 8.3 未验证项

- 真实 Android WebView 的 `visibilitychange` 与合成器暂停行为。
- 最长工具调用的真实耗时（决定看门狗值）。
- P2 合并后的最终事件接口（当前基于 worktree 未提交代码）。
- 状态点在 393px 窄屏、深色系统主题下的对比度。
- 读屏软件对 avatar `aria-label` 频繁更新的实际体验（未做无障碍专项）。

---

## 9. 参考

- [伴读桌宠：气泡自适配、遮挡冲突、生机状态机与自由移动调研](../research/2026-11-07-companion-bubble-and-vitality-research.md) §2.6、§5、§7
- [ADR-0030：前端动效系统](../adr/2026-11-07-adr-0030-frontend-motion-system.md) §2.5–§2.7、§4
- [ADR-0029：前端去 Emoji 与编辑节奏重构](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md) §16
- [动效验证方法](../agents/motion-verification.md)
- 代码：`static/js/companion.js`、`static/js/cp-drawer-capsule.js`、`static/js/cp-state.js`、`static/js/cp-drawer.js`、`static/style.css`
- P2 未合并实现：worktree `D:\Code\DeLector-companion-p2`，`static/js/companion-obstacles.js`
