# 首屏启动业界实践调研

> 2026-11-09 · 只读调研，未改代码、未开 PR。
> 对象：DeLector（本地 Python 服务 + Android WebView / 桌面浏览器）。
> 基线：`docs/plans/2026-11-09-android-startup-latency.md` 的 5 轮模拟器实测；#312/#313 为在途 PR，本文按“未合并”评估。

## 0. 先给判断

1. **我们这 2.3s 不是“Web 首屏”问题，是“壳等 sidecar”问题。** 4.0s 里真正与浏览器渲染相关的只有约 0.8–1.4s；2.3s 是 Python 进程从启动到可服务，WebView 只是被迫在等。
2. **业界不是“并行 vs 遮盖”二选一，而是固定顺序：先把能搬离关键路径的搬走，再用稳定的视觉状态盖住不可消除的剩余。** 公开资料里没有“为了遮盖而放弃并行”的主流做法，也没有“为了并行而让用户看 2.3s 空白”的主流做法。
3. **对我们，可并行的余量已经不多**：约 0.55s 的轮询对齐（#312 已处理）、WebView 预热（#313 已处理）；剩下的 1.2s 是 Python 进程内 import，属于结构性成本，靠线程并行消不掉（GIL + 进程边界），只能削减 import 或遮盖。
4. **遮盖是主手段，但“遮盖物”必须是稳定壳，不是假进度。** 我们的自定义 splash 方向正确；问题在撤得太早（`loadUrl` 后 200ms）和没有 TTFD 口径，而不是“不该有 splash”。
5. **一句话回答**：对这 2.3s，业界更倾向**遮盖**；代价是可能掩盖回归、要求壳必须稳定且诚实；纯并行化的代价是 GIL/进程边界下收益有限，且“惰性化”容易把成本推到首次交互（我们自己 ADR-0028 已经踩过）。

---

## 1. 我们的启动链路（事实锚点）

计划文档的 5 轮中位数：

| 阶段 | 实测 | 说明 |
| --- | --- | --- |
| 进程 → splash 首帧（`Displayed`） | 726ms | 含 Activity/主题/首帧；TTID 被 splash “美化” |
| splash → Python banner | 190ms | Chaquopy 起 Python 解释器 |
| banner → NLP engine 行 | **1235ms** | 就是用户说的“约 1.2s 重依赖 import” |
| NLP 行 → startup complete | 154ms | `build_server` + uvicorn 就绪 |
| startup complete → 首个 `GET /` | **550ms** | 600ms 固定轮询的对齐损耗 |
| `loadUrl` → FCP | 824ms | WebView 首帧内容 |
| `loadUrl` → 首条文章可见 | 1159–1375ms | 含 JS module 求值 + API 数据 |
| 端到端 | **≈4.0s** | |

关键代码事实：

- WebView 在 splash inflate 之前、`onCreate` 里就 `new WebView(this)`，且默认在 UI 线程完成隐式初始化：[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L210-L217)。
- splash 是 Activity 内手搭的 `LinearLayout` + 不定进度条，不是 Android 12 `SplashScreen` API：[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L315-L350)。
- 就绪握手 = 端口文件 + `GET /api/settings` 健康检查，60 次 × 600ms，800ms 超时：[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L460-L500)。
- `loadUrl` 后 200ms 就撤 splash 并显示 WebView，`onPageFinished` 再撤一次（此时通常已撤）：[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L484-L488)、[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L275-L279)。
- Python 侧 1.2s import 发生在 `write_port_file` 之前、`serve_in_thread` 之前，是真正的串行段：[start.py](file:///d:/Code/DeLector/start.py#L634-L640)。桌面端另有一个 **固定 `sleep(1.2)` 再开浏览器**：[start.py](file:///d:/Code/DeLector/start.py#L415-L421)。
- Web 侧：单张 314,470B 的阻塞样式表、148,097B 的 HTML、`main.js` 20 个直接静态 import：[index.html](file:///d:/Code/DeLector/static/index.html#L19)、[index.html](file:///d:/Code/DeLector/static/index.html#L3601)、[main.js](file:///d:/Code/DeLector/static/js/main.js#L4-L204)。
- 静态资源是 `no-cache + ETag`，不是 `no-store`；304 可复用缓存体：[server.py](file:///d:/Code/DeLector/delector/server.py#L210-L247)。
- 原生构建：`minifyEnabled false`、`androidx.webkit:webkit:1.10.0`：[build.gradle](file:///d:/Code/DeLector/android/app/build.gradle#L167)、[build.gradle](file:///d:/Code/DeLector/android/app/build.gradle#L190)。

这组事实决定了后文的判断边界：**我们优化的是“本地 sidecar 就绪”，不是“网络首屏”。**

---

## 2. 原生端：官方口径与可用性

### 2.1 指标：TTID / TTFD / `Displayed` / `reportFullyDrawn`

Android 官方把启动指标拆成两层 [S1]：

- **TTID（Time to Initial Display）**：应用显示第一帧的时间，对应 `Displayed`/`am start -W` 的口径；`Displayed` **不包含异步资源**（网络、懒加载内容）。
- **TTFD（Time to Full Display）**：应用“完全可绘制”的时间，包含异步资源；需要应用主动 `reportFullyDrawn()` 才能被系统记录。
- Android vitals 的“启动时间过长”阈值是 **冷启动 ≥5s、温启动 ≥2s、热启动 ≥1.5s**（TTID 口径）[S1]。

官方对 `reportFullyDrawn()` 的误用警告很直接：**如果在第一帧之前调用，TTID 和 TTFD 会相同**，这个指标就失去意义；必须在所有资源和视图层级完成绘制后再调用 [S1]。

**落到我们：**

- 我们的 `Displayed` ≈726ms，看起来很好，但那是**我们自己的 splash 首帧**，不是用户可用的首屏。真实用户等待是 TTFD ≈4.0s。
- 我们**没有调用 `reportFullyDrawn()`**，所以系统/TTFD 口径里我们可能“很快”；这会让后续优化只盯 TTID，继续美化错误指标。
- 结论：**先把 TTFD 定义成“首条文章可见/首屏可交互”，再谈优化**。这不是代码任务，但它是所有取舍的前提。

### 2.2 `SplashScreen` API（Android 12+）

官方文档 [S2] 的关键约束：

- Android 12+ 系统强制有 splash；自定义 splash 应迁移到 `SplashScreen` API，而不是继续手搭。
- `setKeepOnScreenCondition` 只适合**很短、少量本地数据**的等待（官方举例是“从本地磁盘异步加载应用设置”）；条件在**每一帧前**求值，必须保持轻量。
- splash 动画时长**不超过 1000ms**；如果启动超过 1000ms，应使用**循环动画**，而不是让画面停住。
- 官方明确：用户研究显示**观看动画时感知启动时间更短**；splash 应在视觉稳定后撤，**不要撤到一个还需要额外 spinner 的不完整界面**，“引入不完整界面会显得突兀”。

**落到我们：**

- 2.3s 不是“少量本地数据”，用 `setKeepOnScreenCondition` 强行压住系统 splash 2.3s 不符合官方适用条件；我们的手搭 splash 至少是“自己的画面”，比压系统 splash 更可控。
- 我们 targetSdk 34，Android 12+ 会先显示系统 splash（应用图标），再显示我们的品牌 splash，存在**双 splash 连续性**问题；这影响观感，不影响 2.3s。
- 我们的 splash 有不定进度条，方向是对的（2–10s 的等待适合 spinner）；问题在撤场时机（见 3.2）。

### 2.3 Baseline Profile / R8 / App Startup

- **Baseline Profile**：官方称可带来约 **30% 的代码执行速度提升**，但这是“代码执行速度”，不是端到端墙钟；Startup Profile 的 DEX 布局优化还要求开启 R8 [S3]。
- **R8/资源收缩**：官方文档的主叙事是**包体/代码/资源体积**，不是启动墙钟；`minifyEnabled false` 时拿不到 Startup Profile 的 DEX 布局优化 [S7]。
- **App Startup**：解决的是“多个 `ContentProvider` 各自初始化”的合并与排序问题 [S4]；它不改变初始化本身的工作量。

**落到我们：**

- 1.2s 是 **Python import**，Baseline Profile 覆盖的是 Java/Kotlin 字节码，**覆盖不到 Chaquopy/Python**；726ms 的 `Displayed` 里也可能含 WebView 初始化，而 WebView 是独立 APK，同样不在我们的 profile 里。
- 我们 Java 壳很薄，App Startup 也没有“provider 一窝蜂”的问题；这两项对 2.3s **不是杠杆**。
- **延迟初始化**：官方启动文档把“Application/Activity 里做重初始化”列为常见问题；我们已经把 Python 起服务放到后台线程，原生侧没有更多可延后的重活。再往下延，只会把成本推到首次使用——ADR-0028 的 spaCy 惰性化就是现成教训。
- `minifyEnabled false` 是稳定性选择（Chaquopy/反射风险）；为了启动去开 R8 不划算。**不建议把这三项当银弹。**

### 2.4 WebView 预热：官方支持路径与我们踩的位置

这是本次调研最“可落地”的一条。Android 官方专门有《Optimize WebView startup》[S5]：

- WebView 启动是耗时操作；默认会在 UI 线程**隐式启动**，造成卡顿/ANR。
- 官方提供的受支持 API 是 **`startUpWebView`**，要求 **androidx.webkit 1.16.0+**；它把大量启动工作移到后台线程，并把必须在 UI 线程的部分**分块**执行。
- 关键路径（WebView 马上要用）的用法：在 **`Application.onCreate` 尽早调用，不要等待**；然后把 `WebView` 实例化**推迟到没有其他关键 UI 工作之后**。
- 非关键路径：可以提前把启动成本“藏”掉，但同样用这个 API。
- 官方明确把“用 UA 字符串等 trick 强制后台初始化”的旧 workaround 标为**不受支持**，并提供 `getUiThreadBlockingStartUpLocations` 诊断 UI 线程阻塞点。

**落到我们：**

- 我们用的是 **1.10.0**，没有 `startUpWebView`；且 `new WebView(this)` 发生在 splash inflate 之前，等于官方说的“关键路径 + UI 线程隐式启动”最坏组合。
- #313 用本地静态壳在 `onCreate` 末尾 `loadUrl` 预热 WebView，方向与“先显示壳”一致，实测也有效（FCP 364→276ms、DCL 1242→766ms、首条可见 1450→1259ms）；但它仍是在 UI 线程创建 WebView。**更贴近官方做法的版本是：升级 webkit 到 1.16.0+，在 `Application.onCreate` 调 `startUpWebView`，把 `new WebView` 推到 splash 首帧之后。**
- **实例复用**：同一个 WebView 先加载本地壳、再 `loadUrl` 真实地址，比“壳一个 WebView、正文再一个”更省，也避开多实例状态预算；#313 走的就是受控复用。行业里没有“池化多个 WebView 能省多少”的官方数字，且多实例会放大内存与 1MB state 风险，**不建议池化**。
- 收益区间：官方没有给“预热 WebView 能省多少 ms”的数字；不同 WebView 版本/设备差异很大。**这一项标为“方向确定、数值未核实”**，只能用我们自己的 `Displayed`/FCP 前后对比来验收。
- 代价：预热会让 WebView 渲染进程更早常驻，内存上升；`saveState` 受 **1MB `savedInstanceState` 共享预算**约束，多实例会挤占并可能 `TransactionTooLargeException` [S6]。我们只有一个 WebView，风险低；但不要再为“壳”额外造第二个 WebView。

---

## 3. 混合架构：先出壳，还是等就绪

### 3.1 公开的一手取舍

- **Electron** 官方给了最直白的二选一 [S8]：
  - 默认推荐 `show: false` + `ready-to-show`，首帧渲染后再显示，避免白闪；
  - 但明确补了一句：**“对复杂应用，`ready-to-show` 可能来得太晚，让应用显得慢；这种情况下建议立即显示窗口，并用 `backgroundColor` 盖住。”**
  - 这是“等就绪”与“先出壳”的官方分界线：**白闪/半成品比短暂等待更糟时，才等；否则先出壳。**
- **VS Code**：扩展模型是**壳先出、能力后激活**。`onStartupFinished` 的官方描述是“在 VS Code 启动完成后触发，**不会拖慢启动**”；语言/命令能力用 `onLanguage`/`onCommand` 按需激活 [S10]。
- **Tauri**：sidecar 官方文档只提供 `spawn` + 读取 `stdout` 事件的机制，**没有内建“就绪”协议** [S9]。这意味着“等 sidecar 就绪”必须自建：解析 stdout 的 ready 行，或轮询端口/健康检查。Tauri 本身不替你做这个决定。

**落到我们：**

- 我们不是 Electron 的“单个渲染进程”，而是“壳 + 独立 Python 进程”；Electron 的分界线同样适用：**如果壳能稳定显示，就先出壳**。我们的 splash 已经是壳，不需要等 Python 才显示。
- VS Code 的 `onStartupFinished` 说明：**把非首屏能力延后激活**是主流；但它是“延后能力”，不是“把启动成本推给用户第一次点击”。这与 ADR-0028 的教训一致（见 6.2）。
- Tauri 的空白说明：**sidecar 就绪没有标准答案**；端口文件 + 健康检查是合理自建方案，不必追求“官方协议”。

### 3.2 壳的设计约束：停留多久、何时撤、如何不假

NN/g 的三条时间阈值 [S11]：

- **0.1s**：感觉“立即响应”；
- **1.0s**：思维流不被打断；超过 1s 就应给“正在工作”的反馈；
- **10s**：注意力上限；超过 10s 需要百分比进度 + 可中断。

NN/g 对进度指示器的具体建议 [S12]：

- 超过 **1s** 才需要指示器；**2–10s 用 spinner/不定进度**即可，真正的百分比进度在 2–10s 反而“过度”；
- **≥10s** 才需要百分比 + 明确的可中断出口；
- 用户会注意到速度变化；**卡在最后一个百分比的假进度会摧毁信任**，抵消进度条带来的耐心。
- 骨架屏适合**整页加载**，不适合局部；**<1s 的等待不要用骨架屏**（会闪）；**>10s 用百分比** [S13]。

两个方向相反的反例，正好对应“不遮盖”和“遮盖坏了”：

- **不遮盖的反例**：NN/g 指出，系统没有任何视觉变化时，多数用户会认为操作没被注册，于是**再点一次** [S12]。2.3s 的纯空白/静止画面就是这种风险。
- **遮盖坏了的反例**：百分比进度会让用户形成速度预期；如果进度快速走到最后 1% 后卡住，用户会**沮丧**，进度条带来的耐心被抵消 [S12]。

Android 侧还有两条硬约束 [S2]：动画 ≤1000ms；超过 1000ms 用循环动画；撤 splash 时必须是视觉稳定态，不要撤到“还要再转一个 spinner”的半成品。

**落到我们：**

- 2.3s 正好落在 **spinner/不定进度** 的适用区间：**不需要百分比，也不该造百分比**。我们的不定进度条是对的。
- 壳的撤场不应是 `loadUrl + 200ms` 的定时器，而应是**首帧内容已提交**（`onPageCommitVisible`/首条文章可见）。当前 200ms 定时器在慢设备上会把用户直接甩到白屏/半成品，正好踩中 Android 的“不要撤到不完整界面”。
- 如果要做“阶段文案”（复制资源→Python 启动→import→监听→健康检查），**只能由真实事件驱动**，不能按时间假装推进；这比百分比诚实，也比静态“正在启动”更有信息量。
- 双 splash（系统图标 + 品牌 splash）是连续性问题，不是性能问题；优先级低于撤场时机。

### 3.3 Sidecar 就绪握手：端口文件 vs 健康检查 vs 信号

三种做法的分工：

| 方式 | 回答的问题 | 我们的用法 | 判断 |
| --- | --- | --- | --- |
| 端口文件 | “端口是多少” | `write_port_file` 在 `build_server` 之后、`serve` 之前 | 正确；它不该被当成“已就绪” |
| 健康检查 | “现在能服务吗” | `GET /api/settings` 200 + 800ms 超时 | 正确；这是真正的 readiness |
| 就绪信号 | “sidecar 主动说 ready” | 未用；Tauri 文档示例是 stdout 事件 [S9] | 可选；跨进程更直接，但要处理 stdout 缓冲/解析 |

**为什么不建议固定 sleep：**

- 桌面端 `open_browser()` 先 `sleep(1.2)` 再开浏览器 [start.py](file:///d:/Code/DeLector/start.py#L415-L421)。这是**用时间猜就绪**：import 变快时浏览器可能早于监听（连接拒绝），变慢时用户多等；换设备/冷热启动都会漂移。
- 正确做法是 `write_port_file` + 健康检查/端口可连接后再开浏览器；或者先开一个本地“启动中”页，由页面轮询到 200 再跳转。**信号驱动，不是时间驱动。**
- 重试/退避：AWS 的指数退避 + jitter 解决的是**多客户端竞争/远程服务**的拥塞 [S22]；我们是**单等待者 + 回环**，指数退避只会增加延迟，jitter 没有意义。**600ms 固定轮询不是“错误”，只是粗**；#312 改成前 50 次 120ms，方向正确。更彻底的是监听端口文件（`FileObserver`）或长轮询，但复杂度更高；#312 之后剩余收益只是把 120ms 轮询再压到事件触发，量级更小，需权衡。
- 我们已有“60 次后报错”的硬截止，这是对的：**有界重试 + 明确失败**，比无限等好。

---

## 4. Web 侧：指标与手段

### 4.1 指标口径与目标值

| 指标 | 定义（一手来源） | good | poor |
| --- | --- | --- | --- |
| FCP | 首次渲染任何文本/图片/非空 SVG 的时间 [S14] | ≤1.8s | >3.0s |
| LCP | 视口内最大图片/文本块的渲染时间 [S15] | ≤2.5s | >4.0s |
| INP | 交互到下一帧呈现的延迟；2024-05 起取代 FID 成为 Core Web Vital [S16] | ≤200ms | >500ms |
| TTFB | 首字节时间 | ≤0.8s | >1.8s |
| CLS | 累积布局偏移 | ≤0.1 | >0.25 |
| TTI | Lighthouse 实验室指标：FCP 后首个 ≥5s 的 CPU/网络静默窗口；不是 Core Web Vital [S18] | —（移动 p10=3.785s） | —（median=7.3s） |

FCP/LCP/INP/TTFB/CLS 的数值来自 Google `web-vitals` 5.1.0 源码中的阈值常量（`[1800,3000]`、`[2500,4000]`、`[200,500]`、`[800,1800]`、`[0.1,0.25]`）[S17]；TTI 来自 Lighthouse 12.8.2 的 `interactive` 审计源码（移动 p10=3785ms、median=7300ms）[S18]。

**重要限定：** 这些是**真实用户 p75 的 Web 口径**，不是“本地单机 App 的启动预算”。我们不该拿 LCP≤2.5s 当发布门禁；它们只适合当“用户感知锚点”。对我们真正有意义的是：**WebView 内容 FCP/LCP、首条文章可见时间、以及原生 TTFD**。

### 4.2 首屏手段：哪些成立，哪些不成立

- **Critical CSS**：MDN 明确 CSS 是**渲染阻塞**的，浏览器要等 CSSOM 完成才构建渲染树 [S20]。我们是一张 314KB 的阻塞样式表，理论上是最典型的 critical CSS 目标。但回环传输几乎免费，**真正成本是解析/样式计算**；是否值得拆，必须先测 FCP 里 CSS 占多少。**方向可用，收益未测。**
- **`modulepreload`**：MDN 说明它解决的是“模块按依赖顺序被发现，导致串行下载/处理”的问题；可以提前并行 fetch + parse/compile [S19]。我们 `main.js` 有 20 个直接静态 import，还有传递依赖，属于典型 module 瀑布。回环下传输便宜，但**发现/编译的串行**仍在，所以 `modulepreload` 是结构性可用的。**收益需用 CDP 测，不要凭感觉加 20 个 link。**
- **Skeleton**：NN/g 的适用条件是**整页加载**、等待 ≥1s；<1s 不要用 [S13]。它应该出现在 **WebView 内容层**，而不是原生 2.3s 等待层；我们的原生 splash 已经是更好的“壳”。
- **流式渲染 / SSR / 预渲染**：我们的 `index.html` 是 148KB 静态文件，已经是“预渲染”的壳；SSR 只会把服务端渲染时间加到首字节前，**不划算**。流式渲染对“服务端慢、HTML 大”有意义，对本地静态文件意义很小。**不成立/低优先。**
- **首屏数据**：`loadUrl → 首条文章可见` 的 1159–1375ms 里，包含 JS module 求值 + `/api/*` 数据。真正的 Web 侧杠杆是**减少首屏 JS 图 + 把首屏数据前置**（内联 bootstrap JSON 或更小的首屏接口，需测），不是 SSR。

### 4.3 “禁缓存、每次回源”与 `modulepreload` 的冲突：被高估了

我们的中间件是 `Cache-Control: no-cache` + `ETag`，304 时复用缓存体 [server.py](file:///d:/Code/DeLector/delector/server.py#L210-L247)。MDN 对 `no-cache` 的定义是“**可以存储，但每次复用前必须向源服务器验证**”；真正禁止存储的是 `no-store` [S21]。

因此：

- `no-cache + ETag` **不与 `modulepreload` 冲突**：preload 仍会发请求，命中 304 后用缓存体；它优化的是“发现/并行”，不是“绕过缓存”。
- 会冲突的是 `no-store`（完全不能复用）或“每次换 URL/加 hash 的 immutable 策略”；我们不是。
- 计划里“ES module 打包/预加载与禁缓存冲突”的判断**偏重了**：不需要为了 preload 去改缓存策略；如果未来改成 `no-store`，那才是真冲突。

---

## 5. 可迁移性判断表

| 业界做法 | 解决什么 | 我们能不能用 | 判断/原因 |
| --- | --- | --- | --- |
| `SplashScreen` API / 主题 splash | 系统级启动连续性 | 部分 | 只能改善双 splash 观感，不能缩短 2.3s；`keepOnScreenCondition` 不适用于长等待 |
| `reportFullyDrawn` / TTFD | 度量真实可用时间 | **能，优先** | 我们目前只有 TTID；不测 TTFD 会继续优化错指标 |
| Baseline Profile | Java/Kotlin 代码执行 | 低 | Python/Chaquopy 不在覆盖范围；Java 壳很薄 |
| R8 / 资源收缩 | 包体与代码体积 | 低/有风险 | `minifyEnabled false` 是稳定性选择；对 1.2s import 无帮助 |
| App Startup | 合并 ContentProvider 初始化 | 否 | 我们没有 provider 一窝蜂；重活已在显式后台线程 |
| `startUpWebView` | WebView 初始化移出 UI 线程 | **能，高价值** | 需 webkit 1.16.0+；当前 1.10.0；配合“推迟 `new WebView`” |
| WebView 预创建/复用 | 提前暖渲染进程 | 部分 | #313 已验证有效；官方不把“后台强制初始化 workaround”列为支持路径；有内存/1MB state 成本 |
| 先出壳（shell-first） | 遮住 sidecar 等待 | **能，主手段** | #313 方向正确；壳必须稳定，撤场看首帧而非定时器 |
| Skeleton | Web 内容层占位 | 能，但次要 | 只适用于 service ready 之后的 Web 内容；不解决 2.3s |
| Critical CSS | 降低阻塞 CSS 成本 | 可能 | 314KB 阻塞 CSS 是目标，但回环传输便宜；先测解析成本 |
| `modulepreload` | 消除 module 发现瀑布 | **能** | 20 个静态 import；与 `no-cache+ETag` 兼容 |
| SSR / 流式 / 预渲染 | 降低服务端/网络首字节 | 否/低 | 静态本地 HTML 已是预渲染；SSR 反而加服务端时间 |
| CDN / preconnect / HTTP2/3 / Brotli | 网络传输优化 | 否 | 回环、无 TLS、无跨地域；全是噪声 |
| 端口文件 + 健康检查 | sidecar 就绪 | **已在用，保留** | 端口文件答“在哪”，健康检查答“好了没”，分工正确 |
| 固定 sleep | 等就绪 | 否 | 桌面 `sleep(1.2)` 是猜；应改为信号驱动 |
| 指数退避 + jitter | 多客户端/远程拥塞 | 否 | 单等待者 + 回环；只会增加延迟 |

---

## 6. 最终回答：业界更倾向并行还是遮盖？

### 6.1 不是二选一，而是“先削串行，再诚实遮盖”

公开资料的一致模式是：

1. **能搬离关键路径的，搬走**：Android `startUpWebView` 把 WebView 初始化分块到后台 [S5]；VS Code 用 activation events 延后能力 [S10]；Baseline Profile 减少代码执行 [S3]。
2. **搬不走的，用稳定视觉状态盖住**：Electron 在 `ready-to-show` 太晚时“立即显示窗口 + `backgroundColor`” [S8]；NN/g 的 spinner 覆盖 2–10s [S12]；骨架屏覆盖整页加载 [S13]。
3. **绝不伪造进度**：NN/g 明确“卡在最后一个百分比的假进度”会摧毁信任 [S12]；Android 明确不要撤到“还要再转 spinner”的不完整界面 [S2]。

### 6.2 我们这 2.3s 的具体取舍

**可以并行的：**

- 550ms 轮询对齐 → #312（120ms 前 50 次）已把首个 `GET /` 从 550ms 降到 170ms，属于“减少空转”，方向正确。
- WebView 预热 → #313 用本地壳把 WebView 渲染进程提前暖起来，实测 FCP/DCL/首条可见都改善；属于“把 WebView 启动从 `loadUrl` 之后挪到之前”。
- 1.2s import → **只能在 Python 进程内削减**（更少的顶层 import、按路由惰性加载、预编译），线程并行消不掉（GIL + import lock）。而且 ADR-0028 已经证明：把 spaCy 惰性化只是把 1.2s 从启动挪到首次分析，冷启到首次分析完成从 2.8s 升到 4.0s [ADR-0028 §4.2]。**“并行化”不等于“延后化”；延后到首次点击是更糟的遮盖。**

**必须遮盖的：**

- Python 解释器启动 + 不可削减的 import + uvicorn 就绪，是跨进程的结构性等待。业界没有“让 Python 进程瞬间就绪”的通用办法；这一段的正确姿势就是**稳定的壳 + 真实阶段反馈**。
- 遮盖的代价：
  - 会**掩盖回归**：2.3s 变成 3.5s，用户感知变化不大，团队容易失去痛感；需要 TTFD 看门。
  - 壳如果不稳定/不可交互，用户会点、会以为卡死；需要明确“正在启动”且不要放可点击的假控件。
  - 假进度/假百分比会**反向摧毁信任**（NN/g 的“卡在最后一个百分比”）。
- 纯并行化的代价：
  - Python 进程内并行收益有限；真正能并行的只有 UI 侧预热和轮询。
  - 惰性 import 会把成本推到首次交互，伤害 INP/首次分析（我们已踩过）。
  - 预创建 WebView 有内存/状态成本；官方也不推荐非受支持的 workaround。

### 6.3 结论

**对这 2.3s，业界更倾向“遮盖”，但前提是把可并行的 0.5s 级空转和 WebView 预热先做掉；遮盖物必须是稳定的壳，不是假进度。** 我们的 #312/#313 正好走在这条路上；下一步真正缺的不是“更多优化技巧”，而是：

1. 用 `reportFullyDrawn` 把 TTFD 定义成“首条文章可见”，别再拿 726ms 的 TTID 当成绩；
2. 把 splash 撤场从 `loadUrl+200ms` 改成“首帧内容已提交”；
3. 评估 `androidx.webkit 1.16.0+` + `startUpWebView`，把 `new WebView` 从 `onCreate` 前段推到 splash 首帧之后；
4. 不要为这 2.3s 去开 R8/上 App Startup/做 SSR；它们打不到 Python；
5. 桌面端把 `sleep(1.2)` 换成“端口文件 + 健康检查”后再开浏览器。

---

## 7. 未核实与边界

- **web.dev 原文本次抓取失败**（本地抓取器返回空）。FCP/LCP/INP/TTFB/CLS 的阈值改用 Google `web-vitals` 5.1.0 源码常量核对；TTI 用 Lighthouse 12.8.2 源码核对；FCP/LCP/INP 定义用 MDN。若要与 web.dev 逐字对齐，需人工复核原文。
- **WebView 预热收益区间**：官方未公布统一数字；本文只采用我们自己的模拟器实测（#313），不外推到真机/低端机。
- **Baseline Profile 的 30%** 是“代码执行速度”，不是我们的端到端启动；对我们的实际收益未测。
- **4.0s / 2.3s / 1.2s** 来自计划文档与用户口径，本次未重新开模拟器复测；x86_64 模拟器，未覆盖 arm64/低端机。
- **Tauri 的 sidecar 就绪协议**：官方文档只展示 stdout 事件，没有“ready 协议”的规范；本文把它当作“自建就绪信号”的示例，不声称是官方推荐。
- **R8 对启动的影响**：本次抓取的 R8 文档主叙事是体积，未给出启动墙钟数字；本文只说“不是杠杆”，不声称“会变慢”。

---

## 8. 来源

- [S1] Android Developers, *App startup time* — https://developer.android.com/topic/performance/vitals/launch-time
- [S2] Android Developers, *Splash screens* — https://developer.android.com/develop/ui/views/launch/splash-screen
- [S3] Android Developers, *Baseline Profiles overview* — https://developer.android.com/topic/performance/baselineprofiles/overview
- [S4] Android Developers, *App Startup* — https://developer.android.com/topic/libraries/app-startup
- [S5] Android Developers, *Optimize WebView startup* — https://developer.android.com/develop/ui/views/layout/webapps/optimize-webview-startup
- [S6] Android Developers, *Manage WebView state efficiently* — https://developer.android.com/develop/ui/views/layout/webapps/manage-state
- [S7] Android Developers, *Enable app optimization with R8* — https://developer.android.com/topic/performance/app-optimization/enable-app-optimization
- [S8] Electron, *BrowserWindow*（“Showing the window gracefully”） — https://www.electronjs.org/docs/latest/api/browser-window
- [S9] Tauri, *Embedding External Binaries (sidecar)* — https://tauri.app/develop/sidecar/
- [S10] VS Code, *Activation Events* — https://code.visualstudio.com/api/references/activation-events
- [S11] NN/g, *Response Times: The 3 Important Limits* — https://www.nngroup.com/articles/response-times-3-important-limits/
- [S12] NN/g, *Progress Indicators Make a Slow System Less Insufferable* — https://www.nngroup.com/articles/progress-indicators/
- [S13] NN/g, *Skeleton Screens 101* — https://www.nngroup.com/articles/skeleton-screens/
- [S14] MDN, *First Contentful Paint (FCP)* — https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint
- [S15] MDN, *Largest Contentful Paint (LCP)* — https://developer.mozilla.org/en-US/docs/Glossary/Largest_contentful_paint
- [S16] MDN, *Interaction to Next Paint (INP)* — https://developer.mozilla.org/en-US/docs/Glossary/Interaction_to_next_paint
- [S17] GoogleChrome, *web-vitals 5.1.0 source*（阈值常量） — https://cdn.jsdelivr.net/npm/web-vitals@5.1.0/dist/web-vitals.js
- [S18] GoogleChrome, *Lighthouse 12.8.2 `interactive` audit*（TTI 定义与 p10/median） — https://cdn.jsdelivr.net/npm/lighthouse@12.8.2/core/audits/metrics/interactive.js
- [S19] MDN, *`rel="modulepreload"`* — https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/modulepreload
- [S20] MDN, *Critical rendering path* — https://developer.mozilla.org/en-US/docs/Web/Performance/Critical_rendering_path
- [S21] MDN, *Cache-Control* — https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control
- [S22] AWS Architecture Blog, *Exponential Backoff And Jitter* — https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
