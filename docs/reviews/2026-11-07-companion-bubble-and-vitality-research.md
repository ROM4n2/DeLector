# 伴读桌宠：气泡自适配、遮挡冲突、生机状态机与自由移动调研

> 日期：2026-11-07　|　性质：只调研与出方案，**不改任何代码 / 不改写作页布局**　|　范围：`static/` 现有桌宠 + 移动端写作页实测
>
> **证据标记约定**
> - `[A]` 本次 headless Chromium + CDP 实测（Edge 旧 headless，两个视口）
> - `[B]` 官方文档 / 项目 README
> - `[C]` 二手资料（媒体、教程、社区帖）
> - `[U]` 未验证或无法在本次环境复现
>
> **一句话结论**：气泡问题是「固定左上方 + 无碰撞检测」的结构性问题，正解是 Floating UI 同构的 **优先侧 → 翻面 → 沿轴夹取 → 尺寸封顶** 求解器；桌宠遮挡输入区是第二类独立冲突，靠 **禁停区 + 拖拽期半透明 + 落点自动避让** 解决；生机与自由移动必须以 **默认关闭、可中断、reduce 降级、页面不可见即停** 为前提。

---

## 0. 结论速览（推荐路线）

| 优先级 | 问题 | 推荐方案 | 不推荐 |
| --- | --- | --- | --- |
| P0 | 气泡在左上 / 左下 / 右上被吞；移动端居中已左溢 | 四侧放置求解器：`top → bottom → left → right`，放不下翻面，横向夹取，箭头跟随；高度封顶 `45vh` 内部滚动 | 只把 `right:0` 改成动态百分比 |
| P0 | 桌宠本体压住写作输入区 | 禁停区（可编辑元素 + 抽屉/sheet）+ 落点自动避让 + **仅拖拽期**半透明 | 永久缩小 / 永久半透明 / 硬禁止停放 |
| P1 | 移动端右下角可拖出视口 8.63px | 把 `scale(0.88)` 从定位容器移到角色本体，clamp 使用布局尺寸 | 继续用 `getBoundingClientRect()` 当布局尺寸 |
| P1 | 软键盘弹起后坐标不跟随 | `visualViewport` 的 `resize/scroll` + 视觉视口 clamp + 焦点期冻结 | 只监听 `window.resize` |
| P1 | 只有 idle + blink，缺少生机 | 单一状态机：idle / thinking / acting / speaking / waiting / dragging / sleeping / error；**只有 idle 允许常驻循环** | 多套动画叠加、JS 逐帧驱动 |
| P2 | 自由移动 | **默认关闭**；仅 agent 空闲 + 长时间无操作 + 仅沿安全边带移动；一键召回 | 跟随鼠标 / 重力抛掷 / 随机穿过正文 |
| P2 | 未来 agent 桥梁 | 预留 `data-state` + 事件适配器 + 叠层优先级接口，现在不实现 UI | 现在就把 SSE 事件直接绑到动画 |

---

## 1. 取证方法与边界

### 1.1 方法

- 服务：本仓 `uvicorn delector.server:app`，`http://127.0.0.1:8000/`。
- 浏览器：Microsoft Edge `--headless=old`（`--headless=new` 在本机启动即退出，旧 headless 可稳定连 CDP）。
- 驱动：`websocket-client` 直连 CDP；`Emulation.setDeviceMetricsOverride` 设置 1440×900 / 393×852；`Input.dispatchMouseEvent` 模拟真实拖拽。
- 截图：`Page.captureScreenshot`；几何：`getBoundingClientRect()` + `getComputedStyle()`；帧率：2s `requestAnimationFrame` 计数；主线程成本：`Performance.getMetrics` 3s 差值；reduce：`Emulation.setEmulatedMedia`。
- 证据目录：[`_artifacts/2026-11-07-companion-shots/`](file:///d:/Code/DeLector/_artifacts/2026-11-07-companion-shots/)（**未入 git**）。

### 1.2 本次无法验证的边界

- 真实 Android WebView / iOS Safari 的软键盘行为（Chrome 桌面模拟只能做 `adjustResize` 近似，无法只缩 `visualViewport`）。
- GPU / 合成器实际功耗；rAF 计数只是 vsync 次数，不等于重绘次数。
- 屏幕阅读器、键盘 Tab 顺序、系统级「减少动态效果」之外的无障碍偏好。
- 写作页本身的布局问题（另行调研），本文只记录与桌宠的几何/层级冲突。

---

## 2. 现状实测（A）

### 2.1 定位与拖动

| 项 | 事实 | 证据 |
| --- | --- | --- |
| 定位方式 | `position: fixed` + `right: 24px; bottom: 24px`，**不是** `transform` / 百分比 | [style.css:7852](file:///d:/Code/DeLector/static/style.css#L7852-L7867) |
| 拖动后坐标 | 写内联 `style.left/top`，同时把 `right/bottom` 置 `auto` | [cp-drawer-capsule.js:61-75](file:///d:/Code/DeLector/static/js/cp-drawer-capsule.js#L61-L75) |
| 刷新是否复位 | **复位**。实测：拖到 `(0,0)` 后刷新，回到 `(1344, 804)`（1440×900，72×72） | `measurements.json → drag.reload_*` |
| 持久化 | 无位置键。`localStorage` 只有 `delector_companion_sound`、`delector_visit_date` 等 | `measurements.json → localStorage.positionKeys = []` |
| 拖动实现 | Pointer Events，`pointerdown` 在容器、`pointermove/up` 挂 window；5px 阈值区分点击/拖拽；`pointerCapture` | [cp-drawer-capsule.js:77-207](file:///d:/Code/DeLector/static/js/cp-drawer-capsule.js#L77-L207) |
| 边界限制 | 有 clamp，但用的是 `getBoundingClientRect()` 的**视觉尺寸** | [cp-drawer-capsule.js:48-58](file:///d:/Code/DeLector/static/js/cp-drawer-capsule.js#L48-L58) |
| 拖动时暂停待机 | **不暂停**。`.is-dragging` 只关闭 transition / 开启 pointer-events，没有 `animation-play-state` | [style.css:7868-7875](file:///d:/Code/DeLector/static/style.css#L7868-L7875) |
| 松手吸附 | **不吸附**，停在松手位置 | `cp-drawer-capsule.js:179-200` |
| 惯性/抛掷 | 无 | 同上 |
| 窗口 resize | 只监听 `window.resize`，重算并贴边；**不监听 `visualViewport`** | [cp-drawer-capsule.js:219-227](file:///d:/Code/DeLector/static/js/cp-drawer-capsule.js#L219-L227)；全站 grep `visualViewport` = 0 命中 |
| 拖动中的层级 | `z-index: 70`；存在 `.companion.ontop { z-index: 1001 }`，但全站无任何代码添加 `ontop`，是**未使用规则** | [style.css:7875-7879](file:///d:/Code/DeLector/static/style.css#L7875-L7879) |

**移动端实测缺陷（A）**：`@media (max-width: 768px)` 给 `.companion` 加了 `transform: scale(0.88)` 且 `transform-origin: bottom right`（[style.css:8249-8258](file:///d:/Code/DeLector/static/style.css#L8249-L8258)）。`clampPosition()` 读到的是缩放后的 63.36px，而布局盒仍是 72px，于是：

- `setPosition(9999,9999)` 后视觉矩形为 `(338.27, 788.27) – (401.63, 860.63)`，**右/下各溢出 8.63px**；
- 拖动到极限时角色右侧被裁掉（`mobile-H6-clamp-bottom-right.png`）；
- 反过来，`setPosition(0,0)` 时角色视觉左上也不是 0，而是 `(8.64, 8.64)`。

> 结论：缩放不应加在「定位容器」上。把 `scale(0.88)` 移到 `.companion-char`（角色本体）即可让容器保持 72×72 的布局锚点，同时让气泡坐标 1:1 映射。

### 2.2 气泡与面板的定位规则

| 项 | 事实 | 证据 |
| --- | --- | --- |
| 定位 | `position: absolute; right: 0; bottom: calc(100% + 12px)`，**始终右上/左上对齐，写死在 CSS** | [style.css:7950-7964](file:///d:/Code/DeLector/static/style.css#L7950-L7964) |
| 尺寸 | `width: max-content; max-width: 280px`；实测常规内容 **280×79.34**（桌面） | `measurements.json → desktop A` |
| 间距 | 气泡底边到容器顶边 **12px**；箭头 9×9、`right: 28px`、`bottom: -6px` | [style.css:7966-7976](file:///d:/Code/DeLector/static/style.css#L7966-L7976) |
| 弹出动画 | `pop-anim` 0.3s，`transform-origin: bottom right`；四侧翻转后原点必须同步改 | [style.css:8229-8238](file:///d:/Code/DeLector/static/style.css#L8229-L8238) |
| 边界检测 | **无**。没有 flip / shift / clamp / 视口判断 | 全文件无相关逻辑 |
| 指针事件 | 气泡 `pointer-events: none`，文字可被遮挡但点击可穿透 | `getComputedStyle → none` |
| 面板 | 与气泡同一锚点：`right:0; bottom: calc(100% + 12px); width: 250px`；实测常规 **250×212.13** | [style.css:7994](file:///d:/Code/DeLector/static/style.css#L7994)；`measurements.json` |
| 显示时机 | `Companion.say()` 显示，6.5s 后加 `.hidden` | [companion.js:791-817](file:///d:/Code/DeLector/static/js/companion.js#L791-L817) |

### 2.3 四角复现（桌面 1440×900）

固定参数：角色 72×72；气泡常规 280×79.34；无任何视口 padding（现状）。坐标为 `getBoundingClientRect()` 左上角。

| 用例 | 角色位置 | 气泡矩形 | 溢出（左/上/右/下） | 结果 | 截图 |
| --- | --- | --- | --- | --- | --- |
| 默认右下 | `(1344, 804)` | `(1136, 712.66) 280×79.34` | 0 / 0 / 0 / 0 | 正常 | `desktop-A-default.png` |
| 左上 | `(0, 0)` | `(-208, -91.34)` | **208 / 91.34** / 0 / 0 | 气泡完全被吞 | `desktop-B1_top_left.png` |
| 左下 | `(0, 828)` | `(-208, 736.66)` | **208** / 0 / 0 / 0 | 气泡左半被吞 | `desktop-B2_bottom_left.png` |
| 右上 | `(1368, 0)` | `(1160, -91.34)` | 0 / **91.34** / 0 / 0 | 气泡完全在视口上方 | `desktop-B3_top_right.png` |
| 右下（贴边） | `(1368, 828)` | `(1160, 736.66)` | 0 / 0 / 0 / 0 | 正常 | `desktop-B4_bottom_right.png` |
| 正中 | `(684, 414)` | `(476, 322.66)` | 0 / 0 / 0 / 0 | 正常 | `desktop-B5_center.png` |
| 近顶居中 | `(684, 8)` | `(476, -83.34)` | 0 / **83.34** / 0 / 0 | 气泡在视口上方 | `desktop-B6_near_top_center.png` |
| 长内容 + 近顶 | `(684, 8)` | `(476, -350.22) 280×346.22` | 0 / **350.22** / 0 / 0 | 完全不可见 | `desktop-C1_long_top_center.png` |
| 长内容 + 左上 | `(0, 0)` | `(-208, -350.22)` | **208 / 350.22** | 完全不可见 | `desktop-C2_long_top_left.png` |
| 超长内容 + 右下 | `(1368, 828)` | `(1160, 8.3) 280×807.70` | 0 / 0 / 0 / 0 | 勉强不溢出，占视口 **89.7%** 高 | `desktop-C3-long-bottom-right.png` |

**可复现判据**：左上/左下/右上三处，气泡可见面积均为 0；近顶时可见面积为 0；长内容把「近顶溢出」从 91.34px 放大到 350.22px。

### 2.4 四角复现（移动端 393×852）

移动端 `scale(0.88)` 同时缩放气泡：常规气泡视觉尺寸 **246.4×69.82**，角色视觉 **63.36×63.36**。

| 用例 | 角色视觉位置 | 气泡矩形 | 溢出 | 结果 | 截图 |
| --- | --- | --- | --- | --- | --- |
| 默认（页面加载后） | `(322.89, 781.89)` | 略 | 右 6.75 / 下 6.75 | 默认就不在 14px 设计位 | `mobile-H0-default.png` |
| 左上 | `(8.64, 8.64)` | `(-174.4, -71.74)` | **174.4 / 71.74** | 完全被吞 | `mobile-H1_top_left.png` |
| 左下 | `(8.64, 788.64)` | `(-174.4, 706.9)` | **174.4** / 0 | 左半被吞 | `mobile-H2_bottom_left.png` |
| 右上 | `(329.64, 8.64)` | `(146.6, -71.74)` | 0 / **71.74** / **8** | 顶部被吞 + 右侧裁切 | `mobile-H3_top_right.png` |
| 右下（贴边） | `(329.64, 788.64)` | `(146.6, 706.9)` | 0 / 0 / **8** | 右侧裁切 8px | `mobile-H4_bottom_right.png` |
| 正中 | `(168.64, 713.27)` | `(-14.4, 631.91)` | **14.4** / 0 / 0 | **居中就已左溢** | `mobile-H5_center.png` |
| 右下极限 | `(338.27, 788.27)` | 右/下贴边 | 右 **8.63** / 下 **8.63** | 角色本体被裁 | `mobile-H6-clamp-bottom-right.png` |
| 超长内容 + 右下 | 同上 | `(146.6, 75.93) 246.4×710.78` | 0 / 0 / 0 / 0 | 占视口 **83.4%** 高 | `mobile-H7-long-bottom-right.png` |
| 面板 + 左上 | `(8.64, 8.64)` | 面板 220×186.67 `(-148, -188.59)` | **148 / 188.59** | 面板同样被吞 | `mobile-H8-panel-top-left.png` |

**关键结论**：移动端因为气泡是「右对齐」而不是「相对角色居中」，**角色只要离左边不足 246.4px，气泡就会左溢**；在 393px 视口里，居中也必然左溢 14.4px。这不是角落特例，是常态。

### 2.5 第二类冲突：桌宠遮挡写作区（本次新增实测）

用户提供的真机截图：`c:\Users\Haoyu\.trae-cn\attachments\f58ab0c9-f9fc-4ccb-8dbc-9807c81cdad3_689ce394-cd70-42c8-a03c-ed24c299be2b_image.png`（只读，未改动）。在写作页 393×852 下复现并测量：

写作页关键矩形（同时刻）：标题 `#writer-title` `(45, 531.38) 303×44`；正文 `#ide-editor` `(45, 587.38) 303×240`；卡片 `.writer-card-box` `(24, 475.38) 345×420`；底部 sheet `#writer-panel`（`.writer-sidebar`）桌面端 z-index **1100**。

| 场景 | 角色视觉矩形 | 与输入区重叠 | `elementFromPoint` 命中 | 截图 |
| --- | --- | --- | --- | --- |
| 写作页默认（未拖动） | `(315.64, 709.23) 63.36×63.36` | 正文 **32.36×63.36 = 2050.33px²**；卡片 3380.89px² | `BUTTON #wtab-btn-versions`（**点到的是底部 sheet，不是桌宠**） | — |
| 拖到编辑器右上角 | `(329.64, 574.31) 63.36×63.36` | 正文 **18.36×50.29 = 923.32px²**；标题 19.65px² | `polygon`（桌宠 SVG）→ **点击被桌宠吃掉** | `mobile-writer-01-overlap.png` |
| 拖到编辑器正中 | `(169.14, 713.27) 63.36×63.36` | 正文 **63.36×63.36 = 4014.49px²（全覆盖）** | `BUTTON #wtab-btn-problems`（**桌宠被 sheet 盖住，点击落到 sheet 上**） | `mobile-writer-03-center-overlap.png` |

同一场景的气泡：`(146.6, 495.63) 246.4×69.82`，覆盖标题（y=531–575）与状态 pill（y=496–514）；因为 `pointer-events: none`，点击能穿透，但**文字被视觉遮挡**。

**层级事实（A）**：

- `.companion` `z-index: 70`，气泡 `75`；写作页 `.writer-sidebar` 在移动端 `position: fixed; z-index: 1100`。
- 未展开的 sheet 仍有 **132.5px 可见条**：基类 `.writer-sidebar` 的 `top: 4.5rem` 没有被移动端覆盖，`height: min(76vh, 680px)` + `transform: translateY(100%)` 后矩形为 `(19.5, 719.5) 354×647.5`，即 **y=719.5–852 这一段在视口内**。
- 因此默认右下角的桌宠下半身被 sheet 盖住；用户看到的「桌宠压住编辑器」与「桌宠突然消失」是同一组几何在不同 z 层的两种表现。
- 写出这一点不代表要改写作页；它的根因（`top: 4.5rem` 残留 / closed sheet 露头）属于写作页另行调研。桌宠侧应把「任何可见且 z-index 更高的浮层矩形」当作避让区。

> 实测限制：以上重叠是 headless 视口下的几何与命中测试；用户真机截图的滚动位置、输入法状态可能不同，但「角色本体覆盖正文右上角」已被真机截图与本次几何双向确认。

### 2.6 常驻动画与主线程成本（A）

| 指标 | 默认状态 | `prefers-reduced-motion: reduce` |
| --- | --- | --- |
| `document.getAnimations()` | **3 条**：`companionIdle` 4s infinite、`charBlink` 4.2s infinite ×2（双眼） | **0 条** |
| 2s rAF 帧数 | 121 帧（约 60fps vsync） | 121 帧 |
| 3s 主线程 `TaskDuration` | **2.7ms**（约 0.09%） | — |
| 3s `ScriptDuration` | 0.2ms | — |
| 3s `LayoutDuration` / `RecalcStyleDuration` | 0 / 0 | — |
| 页面不可见处理 | **无 `visibilitychange` 监听**；CSS 动画通常继续跑在合成器上 `[U]` | — |
| 拖动时 | idle 与 blink **继续播放** | — |

结论：现有常驻动画的主线程成本极低，问题是「合成器是否持续出帧」本次无法直接测 `[U]`；新增状态机不应引入 JS 逐帧循环，也不应增加新的常驻循环。

---

## 3. 外部机制对照（B/C）

> 外部资料只抄「机制」，不抄视觉；下表明确区分来源等级。

| 机制 / 来源 | 做什么 | 解决什么问题 | 代价 / 副作用 | 等级 |
| --- | --- | --- | --- | --- |
| **Floating UI `flip`** | 优先侧放不下时翻到对侧；可指定 `fallbackPlacements`、`fallbackAxisSideDirection` | 角落/窄视口的主轴溢出 | 每次 show/resize 需重算；箭头与 `transform-origin` 要跟着改 | [B] |
| **Floating UI `shift`** | 沿对齐轴平移，把浮层夹进视口；`limitShift` 防止「脱离锚点」 | 横向/纵向边缘溢出 | 夹取后箭头不再指向锚点中心，需要单独算箭头；`crossAxis` 可能造成重叠 | [B] |
| **Floating UI `size`** | 用 `availableWidth/Height` 设 `maxWidth/maxHeight`，内容内部滚动 | 内容超长导致溢出 | 出现内部滚动；关闭时要清掉 `maxHeight`，否则下次展不开 | [B] |
| **Floating UI `offset`** | 锚点与浮层的间距（gutter） | 统一 12px 间距 | 只负责间距，不解决边界 | [B] |
| **Floating UI 定位建议** | 用 `transform: translate(x,y)` 替代 `top/left`，按 DPR 取整；fixed 策略可跳出裁剪祖先；大内容用 `max-width: calc(100vw - Npx)` | 性能、裁剪、窄视口 | 3D transform 在部分 Windows 缩放设备上文字发虚；仍建议 portal 处理极端裁剪 | [B] |
| **Codex Pets（OpenAI 官方）** | 可选桌宠；可拖动；方向键移动、`Esc` 回位；位置与选择持久化；右键 Hide；状态优先级 **Needs input > Blocked > Ready > Running**；reduce motion 时用**静止帧**；纯展示，不影响任务 | 让用户不切窗口就能看到 agent 状态；位置可控、可关闭 | 需要原生级 always-on-top 浮层；社区报告 Windows 上出现过「hover 有反应但拖不动」`[C]`；仍可能遮挡内容（官方未提供自动避让） | [B] + [C] |
| **Hermes Pets（Nous Research 官方）** | 纯装饰；**默认关闭**；CLI/TUI/桌面三端同一套 6 状态映射（idle / review / run / wave / jump / failed / waiting）；`Roam` 默认关闭，只在 agent 空闲时漫游，任何 agent 状态立即接管；Settings → Appearance 开关 | 用低成本状态表达 agent 活动；不打扰 | 纯展示、无交互；终端无 TTY 时隐藏；桌面端是 canvas 浮层 | [B] |
| **Shimeji / Shimeji-ee** | 角色自治：走、爬、从天花板掉下、抓窗口边缘、被拖拽、被抛掷；行为由 XML 频率控制；托盘 **Dismiss All** 可一键清场；`Fall / Dragged / Thrown` 是必需动作，隐含重力与惯性 | 「活着」的感觉、桌面漫游 | 高打扰；窗口交互可能误触；需要常驻 CPU/动画；必须提供关闭/频率设置 | [B] + [C] |
| **Desktop Goose** | 随机漫游 + 捣乱；`config.goos` 可调 `GooseAggression`、`CanAttackMouse`、`HonkVolume`、最小/最大漫游间隔等；`Esc` 退出 | 强娱乐性 | 设计上就是打扰；必须靠配置/退出开关兜底 | [C] |

### 3.1 该抄与不该抄

**该抄的机制**

1. `flip → shift → size` 的顺序与语义（Floating UI）：先保优先侧，再翻面，再沿轴夹取，最后用尺寸封顶。
2. 「状态优先级」而不是「所有事件都触发动画」（Codex / Hermes）：同一时刻只表达一个最重要的状态。
3. 「reduce motion = 静止帧 + 语义文字」（Codex）：不是简单把动画时长改成 0.01ms。
4. 「位置持久化 + 一键回位 + 明确隐藏」（Codex）：`Esc` / 双击 / 面板按钮召回。
5. 「自由移动默认关闭，且只在 agent 空闲时」（Hermes）：这是本次「自由移动」开关最重要的先例。
6. 「必须有 Dismiss All / 总开关」（Shimeji / Goose）：桌宠是可选装饰，用户随时能清场。

**不该抄的机制**

- Shimeji 的重力、抛掷、窗户攀爬：会与「不遮挡输入区」直接冲突，且需要持续物理循环。
- Goose 的抢鼠标 / 随机弹窗：与写作、阅读场景的目标相反。
- 跟随鼠标：移动端没有 hover 语义，且会持续分散注意力。
- 把桌宠抬到 modal / drawer 之上：会遮挡必须处理的确认框和底部 sheet。

---

## 4. 方案 A：气泡自适应（推荐）

### 4.1 目标与非目标

**目标**

- 四角、屏幕正中、近顶、窄视口、超长内容六类场景下，气泡**完整可见**（或内容内部可滚动）。
- 默认右下角的外观与现在**逐像素一致**（`280×79.34`、12px 间距、箭头指向角色）。
- 求解器是**纯函数**，可在 Node/Vitest 或浏览器探针里单测，不依赖 DOM 布局。

**非目标**

- 不引入 Floating UI 依赖（见 4.5）。
- 不改气泡视觉样式、不改文案、不改现有动效白名单。
- 不解决写作页布局本身。

### 4.2 算法（推荐：四侧放置 + 跨轴夹取 + 尺寸封顶）

输入：

```
anchor   = 角色本体视觉矩形 (char.getBoundingClientRect())
bubble   = 气泡自然尺寸（先按 maxWidth 测量）
viewport = 视觉视口 {left, top, width, height}（优先 visualViewport）
gap      = 12
padding  = 12（桌面） / 8（移动端）
maxWidth = min(280, viewport.width - 2*padding)
maxHeight= min(0.45 * viewport.height, viewport.height - 2*padding)
```

步骤：

1. **先定尺寸**：给气泡设 `max-width` / `max-height`；高度超过 `maxHeight` 时内部 `overflow-y:auto`，不把整颗球顶出屏幕。
2. **算四侧可用空间**：
   - `top = anchor.top - gap - padding`
   - `bottom = viewport.bottom - padding - (anchor.bottom + gap)`
   - `left = anchor.left - gap - padding`
   - `right = viewport.right - padding - (anchor.right + gap)`
3. **选侧**：按 `top → bottom → left → right` 取第一个满足 `space >= 所需尺寸` 的侧。主内容优先上下；只有视口极矮（横屏键盘态）才落到左右。
4. **跨轴对齐 + 夹取**：
   - `top/bottom`：先右对齐 `x = anchor.right - bubble.width`，再夹到 `[padding, viewport.right - padding - bubble.width]`。
   - `left/right`：先底对齐 `y = anchor.bottom - bubble.height`，再夹到 `[padding, viewport.bottom - padding - bubble.height]`。
5. **箭头**：
   - `top/bottom`：`arrowX = clamp(anchor.centerX - x, 16, bubble.width - 16)`；箭头 DOM 的 `right` 改成由 `--arrow-x` 驱动。
   - `left/right`：同理算 `arrowY`；箭头旋转 90°。
6. **翻转时同步 `transform-origin`**：`top → bottom right`，`bottom → top right`，`left → bottom left`，`right → bottom right`；否则 `pop-anim` 会从错误角落放大。
7. **重算时机**：`say()`、拖动结束、`window.resize`、`visualViewport.resize/scroll`、面板开合、内容 `ResizeObserver`、字体加载完成。拖动过程中**隐藏气泡**，松手后再显示（避免每帧 layout + 视觉噪声）。

伪代码：

```
function placeBubble(anchor, bubble, viewport, {gap=12, padding=12}) {
  const w = Math.min(bubble.w, 280, viewport.w - 2*padding);
  const h = Math.min(bubble.h, viewport.h * 0.45, viewport.h - 2*padding);
  const spaces = {
    top:    anchor.top - gap - padding,
    bottom: viewport.h - padding - (anchor.bottom + gap),
    left:   anchor.left - gap - padding,
    right:  viewport.w - padding - (anchor.right + gap),
  };
  const order = ['top','bottom','left','right'];
  const side = order.find(s => spaces[s] >= (s === 'top' || s === 'bottom' ? h : w))
            || order.sort((a,b) => spaces[b] - spaces[a])[0];

  let x, y;
  if (side === 'top')    { x = anchor.right - w; y = anchor.top - gap - h; }
  if (side === 'bottom') { x = anchor.right - w; y = anchor.bottom + gap; }
  if (side === 'left')   { x = anchor.left - gap - w; y = anchor.bottom - h; }
  if (side === 'right')  { x = anchor.right + gap; y = anchor.bottom - h; }

  x = clamp(x, padding, viewport.w - padding - w);
  y = clamp(y, padding, viewport.h - padding - h);
  return {side, x, y, w, h,
          arrowX: clamp(anchor.centerX - x, 16, w - 16),
          arrowY: clamp(anchor.centerY - y, 16, h - 16)};
}
```

### 4.3 四角预期表现（按上述算法计算）

#### 桌面 1440×900（气泡 280×79.34，gap/padding 12）

| 场景 | 侧 | 气泡位置 | 箭头中心（距气泡左边） | 对比现状 |
| --- | --- | --- | --- | --- |
| 默认右下 `(1344,804)` | top | `(1136, 712.66)` | 244 | 完全一致 |
| 左上 `(0,0)` | bottom | `(12, 84)` | 24 | 从「完全不可见」变为完整可见 |
| 左下 `(0,828)` | top | `(12, 736.66)` | 24 | 从「左溢 208」变为完整可见 |
| 右上 `(1368,0)` | bottom | `(1148, 84)` | 256 | 从「上溢 91.34」变为完整可见 |
| 右下贴边 `(1368,828)` | top | `(1148, 736.66)` | 256 | 从「贴右」变为留 12px |
| 正中 `(684,414)` | top | `(476, 322.66)` | 244 | 不变 |
| 近顶居中 `(684,8)` | bottom | `(476, 92)` | 244 | 从「上溢 83.34」变为完整可见 |

#### 移动端 393×852（把 scale 移到角色本体后，气泡 280×79.34；padding 12）

| 场景 | 侧 | 气泡位置 | 箭头中心 | 说明 |
| --- | --- | --- | --- | --- |
| 左上 | bottom | `(12, 84)` | 28.3 | 角色视觉左 8.64，箭头仍指向头部 |
| 左下 | top | `(12, 776.64-79.34=697.3)` | 28.3 | 完整可见 |
| 右上 | bottom | `(101, 84)` | 260.3 | 右侧留 12 |
| 右下 | top | `(101, 697.3)` | 260.3 | 完整可见 |
| 正中 | top | `(12, 621.93)` | 188.8 | 修复现状 14.4px 左溢 |

> 移动端如果保留现有 `scale(0.88)` 在容器上，问题会变成「坐标要除以 0.88」；因此推荐同时做 5.2 的「缩放与定位分离」。

### 4.4 三个必须处理的边界

1. **浮球在屏幕正中**：`top` 通常放得下；跨轴右对齐后会左溢，必须 `clamp` 到 `padding`；箭头不能跟着被夹到气泡外，要单独夹到 `[16, w-16]`。
2. **浮球靠近顶部**：`top` 可用高度 < 气泡高度 + gap → 翻到 `bottom`；翻转时同时改 `transform-origin`，否则弹出动画会从顶部而不是底部放大。
3. **内容超长**：先设 `max-height = min(45vh, availableHeight)`；超过就内部滚动。实测 5×/3× 文案高度 346.22px（<405，正常展开），12×/8× 文案高度 807.70px（>405，进入滚动）——这组数据正好可以作为 45vh 的校准依据。
4. **移动端极窄 + 居中**：气泡宽度必须 `min(280, 100vw - 2*padding)`；393px 下仍为 280，但夹取后从 `x=12` 开始，不再左溢。
5. **z 层更高的 sheet / drawer**：放置前把「可见且 z-index > 1000 的浮层矩形」加入禁停区；如果能见条只有 132.5px，也按完整矩形避让，避免钻到 sheet 底下。

### 4.5 备选方案与取舍

| 方案 | 做法 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- | --- |
| **B. 最小修补** | 只保留 `top/bottom` 翻面 + 横向 clamp + 高度封顶 | 约 40 行；能解决四角与移动端居中 | 极矮视口（< 200px）仍可能上下都放不下；长内容只能滚动，无法侧放 | 可作为第一步，但不作为终态 |
| **A. 四侧求解器（推荐）** | 上述完整算法，纯函数 + `data-side` | 覆盖六类场景；可单测；无依赖 | 需要处理箭头、`transform-origin`、滚动内容与重算时机 | **推荐** |
| **C. vendor Floating UI** | 引入 `flip/shift/size/offset/arrow` | 成熟、边界情况经过大量验证 | 当前项目是零构建的静态 ES module，引入 UMD/ESM 需要额外 vendor 与升级策略；为一个锚点引入整套定位库偏重；仍要处理 0.88 缩放容器 | **不引入**，只借用其顺序与语义 |

### 4.6 落地形态（本次不实现）

- 抽 `static/js/companion-bubble-placement.js`：纯函数 + 常量，不碰 DOM。
- `companion.js` 在 `say()` / `togglePanel()` / 拖动结束 / `ResizeObserver` 回调里调用；写 `data-side` 与 CSS 变量 `--bubble-x/--bubble-y/--arrow-x/--arrow-y`。
- CSS 只需把气泡的 `right/bottom` 改成 `left: var(--bubble-x); top: var(--bubble-y)`（或保持 absolute，由 JS 写内联值），并把 `transform-origin` 按 `data-side` 切换。
- 单测至少覆盖：四角、正中、近顶、393px 居中、长内容、视口 500px 高、箭头夹取。

---

## 5. 方案 B：待机与生机状态机

### 5.1 设计约束

- 不制造常驻重绘：除 `idle` 外，所有状态动画都是「状态存续期间的临时循环」，状态结束立即移除。
- 不做 JS 逐帧驱动：只用 CSS animation / transition；JS 只切 `data-state`。
- 所有状态可被更高优先级事件打断。
- `prefers-reduced-motion: reduce` 下退化为**静态姿势 + 语义文字**，不是 0.01ms 动画。
- 页面不可见时暂停，不是隐藏（避免回到前台时重新布局）。

### 5.2 状态表

| 状态 | 触发 | 动画表现 | 时长 | 可被谁打断 | reduce 降级 | 页面不可见 |
| --- | --- | --- | --- | --- | --- | --- |
| `idle` | 默认；无 agent 活动 | 现有 `companionIdle` 4s（translateY -4px）+ `charBlink` 4.2s | 常驻（唯一白名单） | 任何状态 | 静止 + 睁眼 | `animation-play-state: paused` |
| `thinking` | agent `thought` / turn in flight | 头部 ±2° 轻摆（只动头部 group，不动整颗球） | 2.4s 循环，状态结束即停 | `waiting` / `dragging` / `error` | 静态侧头 + 气泡文字「思考中」 | 暂停 |
| `acting` | `tool_start` | 0.6s 一次性 wiggle（复用 `is-wiggle`） | 0.6s × 每次工具 | `waiting` / `error` / `dragging` | 无动画 | 不补播 |
| `speaking` | `say()` / `done` | 气泡 pop 0.3s + 1.2s happy（复用 `is-happy`） | 跟气泡 6.5s | `dragging` / `waiting` | 只显示气泡文字 | 暂停 |
| `waiting` | `proposal` / 需要用户确认 | 静止「注意」姿势 + 状态点 2.4s 呼吸（只动 opacity） | 持续到用户响应 | `dragging` 临时接管，松手恢复 | 静态点 + 文字 | 暂停 |
| `dragging` | pointerdown + 5px | 暂停所有动画；`scale(1.06)` + 阴影 | 拖拽期间 | pointerup | 同左（缩放可保留，纯 transform） | — |
| `sleeping` | 180s 无输入、无 agent、页面可见 | 闭眼 + 8s 极慢呼吸 | 持续到唤醒 | 任何指针/键盘/agent 活动 | **静态睡姿**，不循环 | 暂停并保持睡姿 |
| `error` | `error` 事件 | 1.2s 下垂，然后静态错误点 | 1.2s + 持续点 | 用户操作 / 新 turn | 静态下垂 + 文字 | 暂停 |

### 5.3 优先级与转移

```
dragging (100)
  > waiting (90)
  > error (80)
  > acting (70)
  > thinking (60)
  > speaking (50)
  > idle (10)
  > sleeping (0)
```

- `dragging` 是「用户直接操作」，最高优先级；松手后按「保存的 agent 状态」恢复（waiting/thinking/error），没有则回 idle。
- agent 状态永远压过 sleeping；sleeping 只在真正的空白期出现。
- 同一时刻只允许一个 `data-state`；CSS 用属性选择器，不叠 class。
- 状态切换统一 180–260ms，避免闪跳。

### 5.4 性能与可访问性规则

- 只动 `transform` / `opacity`；不动 `width/height/top/left/filter`。
- `will-change: transform` 只在状态激活时加，结束移除。
- `idle` 已有 3 条动画（本体 + 双眼）；`thinking/sleeping` 不要新增第三条以上。
- `visibilitychange` → 给根节点加 `data-paused`，CSS `animation-play-state: paused`；回到前台恢复原 `data-state`。
- reduce：整块 `@media` 关闭新增循环，状态用静态姿势 + 气泡/`aria-label` 文本表达；参考 Codex 的「reduce 时用静止帧」。
- sleeping 期间不播放眨眼；`charBlink` 由状态控制，而不是永久挂在 `.char-eye` 上。

### 5.5 为 agent 桥梁预留的口子（现在不实现）

现有 `cp-drawer` 已有 SSE 事件：`thought`、`tool_start`、`tool_end`、`proposal`、`done`、`error`、`delta`（[companion_agent.py:349-409](file:///d:/Code/DeLector/delector/services/companion_agent.py#L349-L409)）。

预留一个薄适配器即可，不改现有 UI：

```js
// 现在不实现，只定义接口
CompanionAgentBridge.onEvent({ type, payload }) {
  // thought  -> thinking
  // tool_start -> acting
  // tool_end -> thinking | idle
  // proposal -> waiting
  // done -> speaking/celebrate -> idle
  // error -> error
}
```

要求：

- 事件合并/节流：`delta` 不逐条切动画；只按「turn 开始 / 工具开始 / 等待确认 / 结束 / 失败」五类切。
- 状态只影响 `data-state`，不直接写气泡文案；文案仍由现有 `say()` 控制。
- 预留 `data-agent-source="local|agent"` 与 `data-agent-detail`（不渲染），未来接更多 agent 时不必改状态机。
- 出现 `waiting` 时，桌宠本体只做静态提示；**不要在气泡里塞确认按钮**，确认仍走现有 drawer / 未来写作条。

---

## 6. 方案 C：「自由移动」开关

### 6.1 默认值：关闭

理由不是保守，而是实测与外部先例都指向同一结论：

- 本仓实测：写作页默认右下角就与正文重叠 2050.33px²，且被 z-index 1100 的 sheet 盖住；自由移动只会扩大冲突面。
- Hermes：`Roam` 默认关闭，且只在 agent 空闲时运行 `[B]`。
- Codex Pets：只提供拖拽 / 方向键 / 回位，不做随机漫游 `[B]`。
- Shimeji / Desktop Goose：都以高打扰著称，且都提供 Dismiss / 退出 / 频率配置 `[B][C]`。

### 6.2 开启后的行为

| 规则 | 值 |
| --- | --- |
| 开关位置 | 伴读面板 → 「自由移动」，默认关；`localStorage: delector_companion_roam = off|on` |
| 允许移动的条件 | agent 空闲 + 页面可见 + 无输入框聚焦 + 气泡/面板未展开 + reduce 未开启 + 距上次交互 ≥ 90s |
| 移动范围 | 只沿视口边缘「安全边带」（距边 12–72px），禁止穿过正文/编辑器/卡片中心 |
| 目标 | 每 20–40s 随机一个边带点；目标落在禁停区则重抽，最多 8 次，失败就原地不动 |
| 速度 | 12–24px/s，CSS transition 1.2–2.4s，不用 rAF |
| 立即停止 | 指针按下 / 键盘 / 滚轮 / 滚动 / 输入框 focus / 气泡出现 / agent 开始 / 页面隐藏 |
| 召回 | 双击角色 / `Esc` / 面板「回原位」→ 260ms 回默认角 |
| 关闭 | 面板开关；关闭时立刻停止并回到默认角（或保留当前位置，由用户选择） |

### 6.3 明确不做的移动

- 不跟随鼠标 / 触摸点。
- 不做重力、抛掷、惯性、窗户攀爬。
- 不随机弹气泡；漫游只动身体，不说话。
- 不在阅读正文时移动；宁可长时间静止。
- 不在低电量 / `saveData` / reduce 下自动开启。

---

## 7. 第二类冲突：桌宠遮挡输入区（新增章节）

### 7.1 问题定义

不是「气泡被吞」，而是「角色本体（可点击、可拖动）覆盖了可输入/可点击区域」。实测三种后果：

1. **点击被吃掉**：编辑器右上角重叠 923.32px²，`elementFromPoint` 返回桌宠 SVG，点击桌面宠而不是正文。
2. **点击落错对象**：编辑器正中重叠 4014.49px²，但角色被 z-index 1100 的 sheet 盖住，点击落到 `#wtab-btn-problems`，会误切写作页 tab。
3. **视觉遮挡**：气泡覆盖标题与状态 pill（`146.6,495.63 – 393,565.46`），点击虽可穿透，但文字看不见。

### 7.2 问题一：拖到输入区上怎么处理？

**推荐：自动避让（落点吸附到最近安全位）+ 拖拽期半透明；不做永久缩小，不做硬禁止。**

| 选项 | 评估 | 结论 |
| --- | --- | --- |
| 自动避让 | 松手后若与禁停区相交，260ms 滑到最近的安全边位；用户仍可把宠物放在输入区旁边，只是不压在文字上 | **主规则** |
| 拖拽期半透明 | 拖动经过输入区时 opacity 0.35 + 虚线描边，提示「这里不能停」；松手恢复 | **辅助反馈**，只在拖拽期 |
| 永久半透明 | 仍然吃掉点击（除非同时 `pointer-events:none`），且降低可读性；`pointer-events:none` 又会让宠物不可点/不可拖 | 不采用 |
| 永久缩小 | 移动端角色视觉已经只有 63.36px，再缩小会让点击目标低于 44px 可访问下限；且会恶化现有 0.88 缩放的坐标问题 | 不采用 |
| 硬禁止停在输入区 | 与「自由摆放」心智冲突；用户想把宠物放在编辑器旁边也会被弹开；边界判断容易误伤 | 不单独采用 |

**禁停区定义（建议）**

```
input, textarea, select,
[contenteditable=""], [contenteditable="true"], [role="textbox"],
#ide-editor, #writer-title,
.writer-sidebar, .drawer, [role="dialog"], .modal,
以及任何「可见且 z-index > 1000」的浮层矩形
```

- 取 `getBoundingClientRect()`，裁到当前 `visualViewport`，外扩 8px（移动端）/ 12px（桌面）。
- 只对「可见、未 `display:none`、未 `visibility:hidden`」的元素生效；不要遍历全 DOM，按选择器 + 当前视图缓存。
- 输入框 `focusin` 时把该元素标记为「活跃禁停区」，直到 `focusout`。

**落点规则**

- 松手时若角色与任一禁停区相交：在「上 / 下 / 左 / 右」四个候选位里找最近的不相交位置；没有则退到最近视口角。
- 滑动 260ms，`cubic-bezier(0.16,1,0.3,1)`；不要瞬移。
- 不自动回弹到原位；避免「刚拖过去又被弹回」的挫败感。
- 用户仍可把角色放在编辑器上方的空白带、左右边距、卡片外沿。

### 7.3 问题二：软键盘弹起、可视区变矮时坐标怎么跟随？

**现状（A）**

- 位置存的是内联 `left/top`，相对 **layout viewport**。
- 只监听 `window.resize`；**没有任何 `visualViewport` 监听**（全站 0 命中）。
- 模拟 `852 → 500`（adjustResize 近似）并派发 `resize` 后：角色被 clamp 到 `(338.27, 445.27) – (401.63, 508.63)`，**底部仍溢出 8.63px**；正文仍在 `y=587.38`，完全在 500px 视口之外。
- 如果真实设备只缩 `visualViewport` 而不触发 `window.resize`（Android Chrome 常见行为），当前代码**不会做任何跟随**，角色会停在原来的 `y≈576`，整个落在 500px 可视区之外 `[U]`。

**推荐规则**

1. 统一用 `window.visualViewport` 作为可见边界：`offsetLeft / offsetTop / width / height`，而不是 `innerWidth/innerHeight`。
2. 监听 `visualViewport.resize` 与 `visualViewport.scroll`；键盘弹起/收起、页面缩放、地址栏收起都走同一套 clamp。
3. 坐标模型改为「锚点 + 比例」：
   ```
   { mode: 'docked', corner: 'bottom-right' } 或
   { mode: 'free', xRatio: 0..1, yRatio: 0..1 }
   ```
   每次 clamp 后写回实际像素；键盘关闭时用保存的锚点恢复，避免累计漂移。
4. 输入框聚焦时：
   - 若角色与焦点元素相交 → 移到最近的安全边（优先左右边距，其次顶部），**不要停在键盘上方遮挡输入行**；
   - 冻结自由移动与气泡；只保留静态状态点；
   - 键盘关闭且焦点离开后，恢复到键盘弹起前的位置（若用户没有手动移动过）。
5. 视口高度小到放不下角色 + 气泡时：角色 dock 到顶部，气泡**不显示**，改用 `aria-label` / 状态点表达；不要强行把气泡压在键盘上。
6. 验收判据：`visualViewport.height=500` 时角色矩形必须满足 `bottom ≤ 500` 且 `right ≤ 393`；键盘关闭后回到原位置 ±1px；过程中不产生页面滚动跳变。

### 7.4 问题三：未来写作区「选中文本 → 就地 agent 操作条」怎么不打架？

**原则：操作条优先级高于桌宠；桌宠让位，不允许两个浮层抢同一个角。**

建议的叠层优先级：

| 层 | z-index / 优先级 | 元素 |
| --- | --- | --- |
| 模态 / 确认 | 最高（现有 drawer/sheet 1100+） | 必须处理的弹窗 |
| 选区操作条 | 90 | 未来写作区的就地 agent 条 |
| 桌宠气泡 | 80 | 当前 `companion-bubble` |
| 桌宠本体 | 70 | 当前 `.companion` |
| 正文 / 编辑器 | 0 | 内容 |

**规则**

1. 选区激活时，桌宠进入 `waiting` 静态态，暂停自由移动；气泡**立即隐藏**，避免和操作条抢文字上方空间。
2. 操作条放置时，把桌宠本体矩形作为**可选障碍**：优先在选区上方/下方找空位；若唯一空位与桌宠重叠，操作条优先，桌宠在 180ms 内滑到最近安全边。
3. 桌宠不要「主动凑近选区」；它是环境陪伴，不是操作入口。
4. 未来引入统一浮层注册表：
   ```js
   OverlayRegistry.register({ id, priority, getRect, avoid });
   OverlayRegistry.unregister(id);
   OverlayRegistry.relocate(lowerPriorityId, around);
   ```
   气泡求解器、选区操作条、sheet 都从同一个注册表取矩形；禁止各自写一套 `elementFromPoint` 碰撞。
5. 写作页布局本身不在本文修改范围；这里只定义「谁让谁、谁先占位」的规则。

### 7.5 z-index 契约

- 桌宠本体 `70`、气泡 `75` 是**内容层之上的环境层**，不是模态层。
- 不要把 `.companion.ontop = 1001` 重新启用去压过 drawer / sheet；那会遮挡确认框，且与 `.writer-sidebar` 的 1100 继续军备竞赛。
- 正确做法：**检测到更高的可见浮层 → 桌宠避让**，而不是抬自己的 z-index。
- 如果未来必须让桌宠在 modal 之上（例如通话小窗），单独定义 `z-index: 1200` 的「通话层」，并且该层必须带「一键隐藏 / 退出」。
- 写作页 closed sheet 仍有 132.5px 可见条是上层布局问题；桌宠侧只按「可见矩形」避让，不替写作页修 `top: 4.5rem`。

---

## 8. 推荐落地顺序（后续执行用）

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| 0. 坐标基线 | 把移动端 `scale(0.88)` 从 `.companion` 移到 `.companion-char`；clamp 使用布局尺寸；补 8.63px 越界测试 | 393×852 下四角拖动后 `right ≤ 393`、`bottom ≤ 852`；默认位置仍为右 14 / 下 76 |
| 1. 气泡求解器 | 纯函数 + `data-side` + 箭头变量 + 高度封顶 | 四角、正中、近顶、长内容、393 居中全部无溢出；默认右下角像素不变 |
| 2. 禁停区 | 选择器清单 + focusin/focusout + 落点吸附 + 拖拽期半透明 | 写作页三种重叠场景不再遮挡正文；点击命中正文而非桌宠/sheet |
| 3. 键盘跟随 | `visualViewport` + 锚点模型 + 焦点期冻结 | 500px 视口内角色完整可见；关闭后回位 ±1px |
| 4. 状态机 | idle / thinking / acting / speaking / waiting / dragging / sleeping / error | 任一时刻只有 1 个 `data-state`；reduce 下无循环；隐藏页暂停 |
| 5. 自由移动 | 默认关闭 + 安全边带 + 召回 | 默认不动；开启后只在安全区动；输入/agent/隐藏立即停 |
| 6. agent 桥梁 | 只接事件适配器，不做 UI | `thought/tool_start/proposal/error/done` 能映射到状态；不改现有 drawer |

> 以上均为后续计划，不在本次调研中实施。

---

## 9. 明确不做清单

- 不改 `static/` 下任何文件；不跑 pytest；不碰 ADR、`docs/plans`、`WORKMEMORY`。
- 不改写作页布局、底部 sheet、编辑器几何；不替写作页修 `top: 4.5rem`。
- 不引入 Floating UI 或任何新依赖；不 vendor 图标集；不做角色 SVG 化。
- 不做重力 / 抛掷 / 惯性 / 窗户攀爬 / 跟随鼠标。
- 不做多宠物、宠物聊天、口型同步、语音唤醒。
- 不新增常驻循环动画；`idle` 仍是唯一常驻循环。
- 不通过抬高 z-index 压过 drawer / sheet / modal。
- 不做永久半透明、永久缩小、硬禁止停放。
- 不在本轮实现 agent 状态 UI、选区操作条、OverlayRegistry。
- 不把本轮结论写成「已在真机验证」；所有未验证项必须保留在 §10。

---

## 10. 未验证项与风险

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 真机软键盘（Android WebView / iOS Safari） | `[U]` | headless 只能模拟 `adjustResize`；只缩 `visualViewport` 的行为未实测 |
| 合成器 / GPU 实际功耗 | `[U]` | `Performance.getMetrics` 只测主线程；CSS 合成动画的 GPU 帧未测 |
| `visibilitychange` 后 CSS 动画是否完全停 | `[U]` | 代码无监听；浏览器合成器行为未在真机验证 |
| 写作页真机滚动位置 | `[U]` | 本次固定 `scrollTo(0,0)`；用户截图可能在不同滚动位置 |
| 阅读器 / 屏幕阅读器 | `[U]` | 气泡 `pointer-events:none`、无 `aria-live` 结论；需单独无障碍评审 |
| 外部产品行为 | `[B]/[C]` | Codex / Hermes / Shimeji / Goose 均为文档或二手资料，不是本机实测 |
| 0.88 缩放迁移的视觉回归 | 风险 | 移动端角色视觉尺寸不变，但气泡/面板会从 246.4 变回 280；需要视觉签字 |
| 禁停区性能 | 风险 | 每次 focus/resize 遍历选择器；应缓存 + 只查当前视图，不要全 DOM |
| 自动避让的可预期性 | 风险 | 用户拖到输入区会被滑走；需要拖拽期半透明 + 260ms 动画降低突兀感 |
| 未来操作条与桌宠 | 风险 | 当前无操作条；规则需在写作区重构时一起落地，不能各自为政 |

---

## 11. 证据文件

### 11.1 截图（`_artifacts/2026-11-07-companion-shots/`，未入 git）

| 文件 | 内容 |
| --- | --- |
| `desktop-A-default.png` | 桌面默认右下角，气泡正常 |
| `desktop-B1_top_left.png` | 左上角，气泡完全被吞 |
| `desktop-B2_bottom_left.png` | 左下角，气泡左溢 208px |
| `desktop-B3_top_right.png` | 右上角，气泡上溢 91.34px |
| `desktop-B4_bottom_right.png` | 右下角贴边，正常 |
| `desktop-B5_center.png` | 正中，正常 |
| `desktop-B6_near_top_center.png` | 近顶，气泡在视口上方 |
| `desktop-C1_long_top_center.png` | 长内容 + 近顶，溢出 350.22px |
| `desktop-C2_long_top_left.png` | 长内容 + 左上，双轴溢出 |
| `desktop-C3-long-bottom-right.png` | 超长内容 + 右下，占视口 89.7% 高 |
| `desktop-D-panel-top-left.png` | 设置面板在左上，溢出 178 / 224.13px |
| `desktop-D-panel-center.png` | 设置面板在中央，正常 |
| `mobile-H0-default.png` | 移动端默认，右下 6.75px 偏差 |
| `mobile-H1_top_left.png` | 移动端左上，气泡完全被吞 |
| `mobile-H2_bottom_left.png` | 移动端左下，左溢 174.4px |
| `mobile-H3_top_right.png` | 移动端右上，上溢 + 右裁 8px |
| `mobile-H4_bottom_right.png` | 移动端右下，右裁 8px |
| `mobile-H5_center.png` | 移动端居中，左溢 14.4px |
| `mobile-H6-clamp-bottom-right.png` | 拖到右下极限，角色本体被裁 8.63px |
| `mobile-H7-long-bottom-right.png` | 超长内容，占视口 83.4% 高 |
| `mobile-H8-panel-top-left.png` | 移动端面板左上，溢出 148 / 188.59px |
| `mobile-writer-01-overlap.png` | 写作页编辑器右上角遮挡，点击被桌宠吃掉 |
| `mobile-writer-02-keyboard-resize.png` | 视口 500px 近似键盘态，角色仍右下越界 |
| `mobile-writer-03-center-overlap.png` | 编辑器正中全覆盖，桌宠被 sheet 盖住、点击落到 tab |

### 11.2 数据与脚本

- `measurements.json`：桌面/移动四角、中心、近顶、长内容、面板、拖拽、刷新、动画、性能。
- `measurements-extra.json`：移动端右下极限、超长内容、移动端面板、桌面超长内容。
- `measurements-writer.json`：写作页默认/右上/正中、键盘 500px、重叠面积与 `elementFromPoint`。
- `measurements-zorder.json`：写作页 sheet / 桌宠层级链与 9 点命中栈。
- `cdp_probe.py` / `cdp_probe_extra.py` / `cdp_probe_writer.py` / `cdp_probe_zorder.py`：可复跑探针。
- `NOTES.md`：证据保留说明与删除时间点。

---

## 12. 外部资料

- [Floating UI — flip](https://floating-ui.com/docs/flip)
- [Floating UI — shift](https://floating-ui.com/docs/shift)
- [Floating UI — size](https://floating-ui.com/docs/size)
- [Floating UI — offset](https://floating-ui.com/docs/offset)
- [Floating UI — Misc（clipping / large content / transform positioning）](https://floating-ui.com/docs/misc)
- [ChatGPT / Codex — Pets（官方帮助）](https://learn.chatgpt.com/docs/pets)
- [Hermes Agent — Pets 官方文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/pets)
- [Shimeji-ee / Shimeji-Desktop README](https://github.com/DalekCraft2/Shimeji-Desktop)
- [Shimejis FAQ（二手）](https://shimejis.xyz/faq)
- [Desktop Goose 更新与配置（二手汇总）](https://desktopgoose.net/blog/updates/)
- [Desktop Goose 配置项说明（二手）](https://www.codegenes.net/blog/desktop-goose-download/)

> 外部资料只用于机制对照；Codex / Hermes 为 2026 年产品，具体行为可能随版本变化，落地前应以当时官方文档为准。
