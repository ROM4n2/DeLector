# 安卓静态壳本地化（WebView 先画、Python 后到）Design Plan

> **Goal**: 让 WebView 在 Python 服务就绪**之前**就拥有可绘制的内容，把「冷启首个可见应用帧」从
> **3234.5 ms**（x86_64 AVD `Medium_Phone_API_37.0`，2 轮 × 3 次，噪声下限 63 ms）压到**几百毫秒级**。
> **本文件只出方案，不写代码**；批准后按 §8 的阶段实施。
>
> **Tech Stack**: Android(Java, AGP 8.4.2 / Gradle 8.6 / minSdk 24) + Chaquopy 15.0.1 +
> 已有 `androidx.webkit:webkit:1.10.0`（`android/app/build.gradle:190`）+ WebView 145。
>
> **Global Constraints**（用户拍板，不可放宽）:
> - 不做语言迁移、不动后端 API 语义、不动 WebView 版本升级线（`androidx.webkit 1.10.0 → 1.16.0`
>   属于 `docs/plans/2026-11-09-androidx-webview-startup-upgrade.md`，与本线**互不阻塞**）。
> - 本机无 arm64 真机（`adb devices` 为空）⇒ 只在 x86_64 模拟器验；真机项一律写「未覆盖」。
> - 收益必须量在**首帧可见**上；不得拿 `am start -W` / `Displayed` 当收益证据（见 §7）。
> - 不写死端口、不改 `static.version` marker 语义、不改 Python 降级语义、不改 CI 打包判据。

---

## [NOTE] 已确认的事实（本轮勘察，全部带证据）

| # | 事实 | 证据 |
|---|---|---|
| F1 | **APK 里已经躺着完整的 `static/`**：107 个文件 / 2.62 MB，`assets/static/index.html` 内含构建期指纹 `<meta name="delector-assets" content="200fe5b643d3">` | 实测解包 `app-emulator-debug.apk`；同步入口 `tools/sync_android_sources.py:121-179` |
| F2 | 安装后首次运行会把 assets/static 解包到 `filesDir/static`，用 `static.version`（`versionCode[:fingerprint]`）做整目录换入，失败保留旧目录 | `MainActivity.java:659-712` |
| F3 | 前端所有资源都是**绝对根路径**：`/style.css`、`/manifest.json`、`/js/main.js`（module） | `static/index.html:14,20,3601` |
| F4 | WebView 目前**只加载后端 origin**：`http://127.0.0.1:<port>`（端口只来自端口文件） | `MainActivity.java:498-500,519-572` |
| F5 | splash 撤场时机 = 「`isServerReady` **且** 主框架是本地服务 URL」的 `onPageCommitVisible` → 下一动画帧 | `MainActivity.java:317-322,506-517` |
| F6 | 就绪轮询：前 50 次 120 ms、之后 600 ms，共 100 次；失败 10 次后显示「本地服务无法连接」 | `MainActivity.java:519-600` |
| F7 | **后端没有 Cookie / CSRF**：全仓无 `Set-Cookie`、无 `csrf`、无 `SameSite`；CORS 只对 `/api/wb/*` 反射回环/私网 origin | `delector/server.py:251-309`；grep 无命中 |
| F8 | 静态资源响应强制 `Cache-Control: no-cache`；`app.mount("/", StaticFiles(..., html=True))` 是最后一条 catch-all 路由 | `delector/server.py:211-248,369` |
| F9 | SW 只在 `/sw.js` 注册（scope `/`，`updateViaCache:"none"`），缓存名 `delector-static-v5.22.1`，策略 network-first 且放行 `/api/` | `static/js/main.js:1418-1422`；`static/sw.js:2-3,65-103` |
| F10 | `/api/settings` **不含**资源指纹/版本字段（只有 settings 与 NLP 状态） | `delector/routes/settings.py:47-79` |
| F11 | APK 明文 HTTP 已放行 | `AndroidManifest.xml:21 usesCleartextTraffic="true"` |
| F12 | CI 打包面 = `android/**`、`static/**`、`tools/sync_android_sources.py`、`delector/core/assets_manifest.py`；命中即**真跑** Windows Portable Smoke | `.github/workflows/ci.yml:259-300` |
| F13 | 已有一条旧计划把「本地壳」当 splash 的复刻（`file:///android_asset/shell/startup.html`，预期只省 100–300 ms）；其 Task 4–5 **尚未实施**（APK 内无 `assets/shell/`） | `docs/plans/2026-11-09-android-startup-latency.md:121-155`；APK 实测无 `assets/shell` |

---

## §1 静态资源从哪来：三种方案的逐项裁决

| 维度 | A. `WebViewAssetLoader`（推荐） | B. `file:///android_asset/` | C. APK 内 mini server |
|---|---|---|---|
| origin | `https://appassets.androidplatform.net`（可用自定义域名） | `file://`（不透明 origin，`Origin: null`） | `http://127.0.0.1:<assetPort>` |
| 安全上下文 / SW 可注册 | **可以**（https 安全上下文，SW 限 http(s) 且需安全上下文） | **不可以**（SW 规范不接受 `file:`） | **可以**（loopback 视为 potentially trustworthy） |
| 同源策略 | 页面内相对/根路径请求都落在本 origin；`/api/*` 会 404，除非另做映射 | 同上，且 `fetch` 到 `http://127.0.0.1` 属跨源，`Origin: null` 会被后端 CORS 拒绝；`localStorage/IndexedDB` 在 `file://` 下不可靠 | **完全同源**（若同时反代 `/api/*`） |
| fetch 到 127.0.0.1 后端 | 跨源 ⇒ 需 CORS 或代理 | 跨源且 origin 为 `null` ⇒ 必须放开 `null`（安全上不可接受） | 同源 ⇒ 无需 CORS |
| 依赖 | 已有 `androidx.webkit:1.10.0`（**不新增依赖、不升版本**） | 零依赖 | 需自研 `ServerSocket` 或引入 NanoHTTPD（**违反「不新增依赖」**） |
| 与既有 `static/` 同步闸 | 直接吃 `assets/static`，指纹/marker 语义不变 | 同 A | 同 A，但多一个端口与生命周期 |
| 主要风险 | `/api` 404（必须显式处理）、`shouldInterceptRequest` 的 MIME/编码细节 | SW 全废、存储隔离、CORS `null` | 端口不变量 I1 被破坏、进程内代理的流式/上传/下载全要自己实现 |

**结论**：
1. **B（`file://`）直接排除**：SW 不可用、`Origin: null` 会逼后端放开任意源、`file://` 下存储不可靠。
2. **C（mini server）本轮不做**：它唯一不可替代的能力是「同源」，而先启动一个抢占端口的服务会撞上
   「端口文件是唯一真相」这条不变量（`docs/plans/2026-11-09-android-startup-latency.md:49` 的 I1），
   还要自研代理；风险/收益比最差。
3. **选 A**：`WebViewAssetLoader` 把 `assets/static` 挂到根，页面 origin 变成 appassets；
   壳页**不发起任何 `/api` 请求**（见 §4），因此不存在 404 问题。

**SW 的精确结论**：`static/sw.js` 的 scope 是 origin 级——新 origin 下会**重新注册一份空缓存**，
旧 origin（127.0.0.1:port）的 CacheStorage 不会迁移，相当于首次访问。**因此阶段一不在 appassets
origin 注册任何 SW**（壳页不加载 `main.js`，自然不触发 `main.js:1418` 的注册）；
一旦未来在壳里跑真实 `main.js`，必须先把 `register("/sw.js")` 收窄到后端 origin，否则会多出一份
只缓存本地壳、且可能把旧壳长期钉住的 SW。

---

## §2 API 跨源：最小改动方案

前提事实：**没有 Cookie、没有 CSRF token**（F7），所以「SameSite / Cookie 会不会丢」这一问的答案是
**不适用**——本项目不存在会话 Cookie。

若壳页要调后端，只有三条路：

| 方案 | 改动 | 代价/风险 |
|---|---|---|
| **A2. 壳页零 API（推荐，阶段一）** | 后端零改动、前端零改动 | 壳只能画骨架/缓存快照；真实数据仍靠导航到后端页 |
| B2. 绝对 URL + CORS | `server.py` 增加仅对 `https://appassets.androidplatform.net` 的 ACAO（含 `OPTIONS` 预检，JSON POST 必触发） | 等于给 WebView 开一个受控例外；要写死在允许清单里，不能反射任意 origin；`/api/wb` 的现有 LAN 中间件不能被顺手放宽 |
| C2. 同源反代 | 由 mini server 反代 `/api/*` | 同 §1 的 C，本轮不做 |

**裁决**：阶段一只走 **A2**。若阶段二确需壳内直连，再加 **B2**，且必须满足：
- 允许清单**硬编码** `https://appassets.androidplatform.net`（不做通配、不回显 `Origin`）；
- 只加 `Access-Control-Allow-Origin` + `Vary: Origin`，不引入 credentials；
- 用现有 CORS 测试面扩一条用例，证明 LAN 来源行为未变。

---

## §3 版本一致性与双源闸：**不需要新增机制**

现状（已足够）：`static/` 是唯一真相 → `sync_android_sources.py` 把它拷进 `assets/static` 并写入
内容指纹（`delector/core/assets_manifest.py:113-150`）→ 构建期把指纹注入 `index.html` 的
`<meta name="delector-assets">` 与 `static/js/build-stamp.js`；运行时 `syncStaticAssets()` 用
`versionCode:fingerprint` 决定是否整目录换入（F2），`check()` 在 CI 里比对仓库与 assets 的指纹。

因此：
- **壳页必须复用同一份 `assets/static`**，不得另建第二份 `assets/shell/static`——否则立刻产生
  「双份镜像」漂移面；壳页本身（`assets/shell/boot.html`）自包含、无外链，不参与指纹。
- **「APK 壳 vs 后端壳」漂移在架构上不可能发生**：两者来自同一个 APK、同一次解包。唯一的失配是
  「APK 升级了但数据目录还是旧 static」，这已被 marker 覆盖（失败保留旧目录并写
  `static.version.error`，见 `MainActivity.java:707-711`）。
- **不新增版本校验接口**：`/api/settings` 目前没有指纹字段（F10），加字段属于扩 API 面，
  在阶段一没有消费方，**不做**。

失败可见性要求（阶段一补一条）：`static.version.error` 目前只落盘 + logcat，壳页要能读到它并在
壳上显示「静态资源解包失败，正在使用旧版本」，不允许静默。

---

## §4 时序接力：壳先画，何时交给真实页

目标时序（`onCreate` 内，全部主线程，毫秒为模拟器预期）：

```
t=0    onCreate → 建 WebView（已 GONE）+ 原生 splash（覆盖在上）
t≈20   webView.loadUrl(壳 URL)                      ← 零点 B 从这里开始
t≈150  onCreate 末尾：启动后台线程（syncStaticAssets → Python.start → 就绪轮询）
t≈200  onPageCommitVisible(壳) → postOnAnimation(撤原生 splash，露出 WebView)
t≈2300 轮询命中 200 → loadUrl(http://127.0.0.1:port/)
t≈3200 真实页首条文章可见（TTFD，与现状持平或略升）
```

关键裁决：

1. **就绪轮询必须保留**（`MainActivity.java:519-572` 不动）：它是「何时导航到真实页」的唯一闸门，
   壳页不承担任何就绪判定。壳只改变「这段时间用户看到什么」。
2. **撤 splash 的唯一信号改为「壳页主框架 commit」**：现在的条件 `isServerReady && isLocalServerUrl(url)`
   （F5）在壳阶段永远是 false，会导致 splash 一直盖着、壳白画。改为「主框架 URL == 壳 URL」时撤；
   真实页 commit 时不再撤（已经撤过）。fatal 时仍按 I3 强制回到原生错误层。
3. **壳不发起 API 请求、不注册 SW、不写业务存储**（跨 origin 的存储本来也不通，见 §1）。
4. **双导航的闪跳要单独设计**：壳与应用页的顶栏/背景必须同色同构（`#FAF8F5`），
   且应用页导航开始到 commit 期间**不能**重新显示 splash——这是本方案最大的视觉风险（见 §6 风险 R1）。

---

## §5 失败可见路径（逐场景）

| 场景 | 用户看到什么 | 实现要点 |
|---|---|---|
| Python 起不来（100 次轮询耗尽） | 壳页切成错误态：「本地服务启动失败（端口 N），请查看日志」，文本可选中 | Java 通过 `addJavascriptInterface` 注入 `shell.setState('timeout', detail)`；同时保留现有超时分支文案 |
| Python 抛 fatal | 原生 splash 覆盖壳，显示 `fatalError` 原文 | 沿用 `reportFatal` 路径 + I3：fatal 时 `webView.GONE`、`splash.VISIBLE` |
| APK 壳与后端版本不匹配 | **不存在该状态**（同一 APK）；只有「旧 static 残留」，由 marker 处理并在壳上提示解包失败 | 见 §3 |
| SW 缓存旧壳 | **不存在该状态**：阶段一不在 appassets origin 注册 SW；后端 origin 的 SW 仍按 `CACHE_NAME` 版本清旧缓存 | 见 §1 的 SW 结论 |
| 壳页自身加载失败（assets 损坏） | 原生 splash 不撤，显示「界面资源损坏」+ 重试按钮 | 壳 URL 的 `onReceivedError(isForMainFrame)` 捕获，走 fatal 分支 |

**红线**：任何一条路径都不允许出现「白屏 + 无限转圈」。

---

## §6 打包面、收益与风险

**APK 体积**：`assets/static` 已在包里（2.62 MB / 107 文件）；新增一个自包含 `boot.html`（预计 3–6 KB）
⇒ **增量 ≈ 0–10 KB**。不新增依赖（`WebViewAssetLoader` 来自已有 `androidx.webkit:1.10.0`，**不升 1.16.0**）。

**构建面**：无新 Gradle 任务、不改 ABI、不改 Chaquopy 源集；`sync_android_sources.py` 不用改
（它已经把 `static/` 同步好了）。

**CI**：改动落在 `android/**`（和阶段二的 `static/**`）⇒ `Detect packaging-surface changes` 判 true
⇒ **Windows Portable Smoke 会真跑**（这是预期，不是噪音）；不新增 workflow。

**桌面端**：完全不受影响——`MainActivity`、`WebViewAssetLoader`、`assets/shell` 都不进桌面打包面。

**收益分层（必须分开说，不许混）**：
- 首帧可见：**4053 ms → ~1823 ms**（S0 实测，见 §8A；原“3234.5 → 300–700 ms”的估计作废）。
- 首条文章可见（TTFD，真正可用）：**不降**是目标；S0 的 R1 诊断构建实测 **+470~+490 ms**（与 Python 抢 CPU），
  见 §8A F-B，这是 S1 必须压回去的项。
- 缓存快照能否提前用：**阶段一不能**（跨 origin 存储隔离）；阶段二通过 Java 桥导 Snapshot 才能提前。

**风险排序**：
- **R1（最高）：撤 splash 的双导航闪跳** —— 壳 commit 撤 splash、真实页导航时又出现一次 commit，
  中间可能出现「壳已撤 → 应用页未画」的空窗。对策：壳与应用页同底色 + 真实页 commit 前不回退到 splash + 逐帧截图闸。
- **R2：WebView 提前创建的内存/CPU 争用**（低端机尤甚，真机未覆盖）。
- **R3：壳与应用页的视觉不一致**（字体、顶栏）被用户感知为「闪了一下旧界面」。
- **R4：`WebViewAssetLoader` 的 MIME/编码细节**（`.js` module 的 MIME 必须是 `text/javascript`，否则 module 拒绝执行；阶段一壳页无外链，故只影响阶段二）。

---

## §7 判据（零点写清，禁用 `am start -W` / `Displayed`）

| 指标 | 零点 A（进程） | 零点 B（导航） | 终点 |
|---|---|---|---|
| **M1 首帧可见**（判定主指标） | `Process.getStartElapsedRealtime()`（`StartupReportBridge` 已有同源时钟，`MainActivity.java:211-221`） | `loadUrl(壳)` 调用前一刻（`SystemClock.elapsedRealtime()`） | 壳页主框架 `onPageCommitVisible` + `revealWebView()` 后下一帧 |
| **M2 真实首屏** | 同上 | `loadUrl(真实页)` 前一刻 | 应用页 `onPageCommitVisible` |
| **M3 TTFD**（不得劣化） | 同上 | — | 现有 `TTFD_FIRST_ARTICLE_MS`（`MainActivity.java:217-220`） |
| **M4 白屏帧** | — | — | 每轮 `loadUrl+0/50/100/200/400/800/1600 ms` 截图，与基线同刻对比 |

采样：同机同 AVD、`am force-stop` + 清 WebView cache/SW、2 轮 × 7 次、每轮前弃跑 2 次、中位数 + 范围。

**判负条件**（任一成立即判负、不合入）：
1. M1 改善 **< 1000 ms**（基线 4053 ms ⇒ 即 M1 中位数 > 3053 ms；M1 终点按「壳页首个内容帧」，见 §8A F-A）；
2. M3 相对基线劣化 **> 300 ms**；
3. M4 出现任意一帧纯白/纯色空屏（逐帧截图证据，不接受口述；**范围含 splash→壳 与 壳→真实页 两段**）；
4. 出现「壳→真实页」可感知的闪跳（同刻截图对比不一致即为证）。

---

## §8 阶段化实施（每步独立 PR，独立实测）

| 阶段 | 内容 | 预计收益 | 风险 | 涉及文件 |
|---|---|---|---|---|
| **S0 仪器化** | 在 `MainActivity` 增加 M1/M2 两个零点日志（复用 `StartupReportBridge` 的时钟）；跑一轮基线切分 | 0（只买可判定性） | 极低 | `MainActivity.java`（日志）、`tests/test_android_webview_policy.py` |
| **S1 本地壳（最小可用）** | `assets/shell/boot.html` 自包含壳 + `WebViewAssetLoader` + **撤 splash 改为「壳页首个内容帧之后」**（三帧 rAF + `JavascriptInterface` 回报）+ 壳页静态无动画 + `loadUrl(壳)` 延后到 `python_start_done`。实测见 §8B | **首帧 4053 → ~1361 ms**；TTFD +196 ms（判据 ≤300） | 中（R1/R3） | `MainActivity.java`、`assets/shell/boot.html`、`StartupProbe.java`（S0） |
| **S2 快照桥（可选）** | 真实页经 `addJavascriptInterface` 导出文章快照 JSON → Java 落 `filesDir` → 壳启动时 `evaluateJavascript` 注入并渲染「上次的阅读清单」 | 壳从骨架变「有内容」，感知接近秒开；TTFD 仍 3.2 s | 中高（数据格式耦合、隐私落盘） | `static/js/article-store.js`（另一条线的 WIP）、`MainActivity.java`、壳页 |
| **S3 同源反代（不做）** | mini server / `shouldInterceptRequest` 代理 `/api/*` | 让 SW/IndexedDB 复用 | **最高**（破坏 I1、自研代理） | — |

**最高风险项**：S1 的「撤 splash 边界 + 双导航闪跳」（R1）——它决定用户是「更快看到界面」还是
「看到两次界面切换」。S1 必须先出逐帧截图，再谈数字。

---

## §8A S0 实测结果（2026-11-10，x86_64 模拟器）

> 本节是 S0 的交付物，只买可判定性，**不改产品行为**。真机项未覆盖（见 §10）。
> 设备：AVD `Medium_Phone_API_37.0`（API 37，WebView 145.0.7632.218），包名 `org.delector.app.emulator`，
> APK 由独立 worktree 分支 `perf/android-startup-instrument`（基于 `origin/master` `88c15c6`）构建。

### S0-a 分段仪器化

**零点（两栏，绝不混）**

- 零点 A：`Process.getStartElapsedRealtime()` → 探针输出 `t_proc_ms`。
- 零点 B：`loadUrl(http://127.0.0.1:<port>/)` 调用前一刻 → 探针输出 `t_nav_ms`（只对导航后的段有意义）。

**探针**：新增 `android/app/src/main/java/org/delector/app/StartupProbe.java`，`BuildConfig.DEBUG` 才输出，
tag `DeLectorProbe`，格式 `PROBE ev=<name> t_proc_ms=<> [t_nav_ms=<>] detail=<url>`。纯日志、无控制流改动；
删掉该文件与调用点即回原状（`git diff` 可直接审）。

**重复条件**：每轮 `am force-stop` + `pm clear` + `logcat -c`；每轮先弃跑 2 次；有效 7 次 × 2 轮。
下表“两轮差”= 两轮中位数之差，作为**噪声下限**（≥ 该值的改善才算可判定）。

| 分段（零点 A 起算） | 轮 1 中位 | 轮 1 范围 | 轮 2 中位 | 轮 2 范围 | 两轮差 |
|---|---|---|---|---|---|
| 进程 → `onCreate` 入口 | 303 | 292–313 | 305 | 287–325 | 2 |
| `onCreate` → WebView 挂载 | 241 | 233–260 | 241 | 232–252 | 0 |
| WebView 挂载 → `setContentView` | 21 | 20–24 | 23 | 21–24 | 2 |
| `setContentView` → 后台线程起跑 | 1 | 0–1 | 1 | 0–1 | 0 |
| 后台线程 → assets 解包完成 | 173 | 139–219 | 174 | 138–197 | 1 |
| assets → `Python.start` | 0 | 0–1 | 0 | 0–0 | 0 |
| `Python.start` → Chaquopy 解释器就绪 | 321 | 297–349 | 308 | 292–345 | 13 |
| → Python 入口被调用 | 1 | 0–1 | 1 | 1–1 | 0 |
| → Python 首行输出 | 49 | 48–60 | 50 | 46–54 | 1 |
| Python 首行 → **uvicorn 监听就绪**（import + init_db + bind） | **2174** | 2146–2222 | **2147** | 2119–2157 | 27 |
| uvicorn 就绪 → 端口文件读到 | 75 | 35–103 | 16 | −16–105 | 59¹ |
| 端口文件 → `/api/settings` **首个 200** | 21 | 19–23 | 23 | 20–146 | 2 |
| `settings` 200 → `loadUrl`（零点 B） | 1 | 1–2 | 1 | 1–2 | 0 |
| `loadUrl` → **WebView 主框架 commit** | 644 | 604–766 | 630 | 602–669 | 14 |
| commit → 撤 splash（`revealWebView`） | 15 | 6–18 | 9 | 3–17 | 6 |
| **进程 → 首帧可见**（reveal） | **4053** | 3983–4215 | **4044** | 3862–4089 | 9 |
| **进程 → TTFD** | 4038 | 3961–4192 | 4018 | 3849–4082 | 20 |

¹ 该段跨 Java/Python 两个线程写 logcat，出现 `−16 ms` 的日志乱序；本段应以轮 1 的 75 ms 为准，
噪声按 ±60 ms 计。

**关键结论**

1. 唯一的大块是 **Python 首行 → uvicorn 就绪 ≈ 2.15–2.17 s**，占首帧全过程 53%——这段与 S1 无关，
   S1 只能改变“这段期间用户看到什么”，不能缩短它。
2. `loadUrl → commit ≈ 630–644 ms` 是 WebView 自身冷启动成本，S1 无法消除，只能**提前开始**（把这段
   藏进 Python 启动期）。
3. `commit → reveal` 只有 9–15 ms；首帧可见实际由 commit 决定。
4. **口径修正**：本方案原先引用的“首帧 3234.5 ms”出自 `feat/article-store-readiness-retry` 分支的
   **快照首帧**口径（2 轮 × 3 次），与本线基线不是同一个构建。本线基线（`88c15c6` + 仅埋点）在本口径下是
   **4053 / 4044 ms**（同日 14 次有效）。两者**不可混用**；S1 一律以 4053 ms 为基线。
5. 顺序细节：`ttfd` 比 `commit` 回调早约 11 ms（JS 侧双 rAF 先于 `onPageCommitVisible` 触发），
   即 TTFD 不是“更晚”的指标，两者不可当成两个独立阶段。

### S0-b R1 逐帧验证（「壳 commit 就撤 splash」）

**临时诊断构建（不入库，验证后已还原）**：`assets/shell/boot.html`（自包含，底色 `#FAF8F5`）+
`WebViewAssetLoader` + `onPageCommitVisible` 中「URL == 壳 URL 即撤 splash」；壳页底部加 8 px 绿色条，
仅作**帧分类标记**（不属于方案设计）。`loadUrl(壳)` 在 `setContentView` 之后、后台线程起跑之前调用。

**取证方法**：`adb shell screenrecord --time-limit 10 --bit-rate 12000000` → `ffprobe` 取 `pts_time` →
`ffmpeg -vsync 0` 抽帧 → Pillow 逐帧统计（正文区域裁掉状态栏/导航栏后计暗像素；绿条计“是否壳页”）。
帧间隔中位 ≈ 17–20 ms；空白判定 = 正文暗像素 < 5（状态栏文字不计）。采样 2 轮 × （弃跑 2 + 有效 5）。

| run | loadUrl(壳) | 壳 commit | reveal | **壳首内容帧** | 空白累计 | 单帧最长 | 末壳帧 | 首应用帧 | 壳→应用静止 |
|---|---|---|---|---|---|---|---|---|---|
| r1a_3 | 652 | 1355 | 1373 | 1840 | 85 | 68 | 3.606 | 4.739 | 1133 |
| r1a_4 | 612 | 1475 | 1489 | 1892 | 79 | 68 | 3.677 | 4.625 | 948 |
| r1a_5 | 560 | 1290 | 1302 | 1790 | 102 | 86 | 3.537 | 4.672 | 1134 |
| r1a_6 | 578 | 1463 | 1479 | 1864 | 50 | 34 | 3.680 | 4.847 | 1167 |
| r1a_7 | 552 | 1252 | 1263 | 1757 | 116 | 101 | 3.493 | 4.741 | 1248 |
| r1b_3 | 610 | 1608 | 1702 | 2079 | 66 | 49 | 3.862 | 4.562 | 700 |
| r1b_4 | 562 | 1282 | 1295 | 1763 | 83 | 65 | 3.530 | 4.646 | 1116 |
| r1b_5 | 602 | 1301 | 1320 | 1806 | 83 | 67 | 3.573 | 4.675 | 1102 |
| r1b_6 | 653 | 1458 | 1469 | 1906 | 66 | 51 | 3.724 | 5.006 | 1282 |
| r1b_7 | 572 | 1289 | 1300 | 1764 | 0 | 0 | 3.531 | 4.610 | 1080 |
| **中位** | 590 | 1328 | 1346 | **1823** | 81 | 66 | 3.58 | 4.74 | **1124** |

前六列为毫秒，`末壳帧`/`首应用帧` 为秒（录屏内时间），`壳→应用静止` 为毫秒。

**代表性帧序列（r1a_3，时间轴相对录屏起点；录屏比 `am start` 早 0.4 s）**

| 时间 | 界面 | 持续 |
|---|---|---|
| 0.000–0.421 | 启动器/前态（暗） | 421 ms |
| 0.433–1.573 | 原生 splash（logo + “正在启动…” + spinner） | 1140 ms |
| 1.573–1.755 | splash 淡出（文字透明度下降） | 182 ms |
| **1.755–1.840** | **纯底色，无任何内容** | **85 ms（2 帧）** |
| 1.840–3.606 | 壳页（logo + “正在准备本地资源…” + 绿条） | 1766 ms |
| 3.606–4.739 | 画面静止 = 壳页（该段无新帧；screenrecord 仅在画面变化时出帧） | 1133 ms |
| 4.739– | 应用页，**首帧即完整内容**（顶栏/hero/卡片/底栏俱全） | — |

截图见 `docs/reviews/2026-11-10-android-shell-s0-images/`（`r1a3-splash-to-shell.png`、
`r1a3-shell-to-app.png`、`r1b4-*` 同构）。

**逐条回答**

1. **「壳已撤、应用页未画」的白屏/空白帧：不存在。10/10 次均为 0 帧。** 末个壳帧（3.49–3.86 s）
   一直到应用页首帧（4.56–5.01 s）之间屏幕**静止在壳页**，间隔 700–1282 ms（中位 1124 ms）。
   机制：这是第二次导航，WebView 合成器把旧画面保持到新页首帧就绪才交换，且交换时应用页已完整绘制
   （不是渐进式补白）。所以「双导航闪跳」在这个边界上**没有出现**。
2. **但「splash → 壳」之间出现了内容空洞：9/10 次、每次 2 帧、累计 50–116 ms（中位 81 ms），
   单帧最长 34–101 ms；1 次（r1b_7）为 0。** 这 2 帧是纯 `#FAF8F5` 底色（连 logo 都没有），
   不是白屏（底色与两侧一致），但确实是「旧界面已撤、新界面未画」。
3. 成因可定位到**撤场信号选错**：`reveal` 发生在壳页 `commit`（1.25–1.71 s），而壳页**首个内容帧**在
   1.76–2.08 s，差 400–500 ms 全靠 splash 淡出盖住；淡出一结束（~1.75 s）就露出底色，直到壳页首帧。
   这正是 §6 风险 R1 描述的形态，只是发生在 splash→壳，而不是壳→应用。

**两条必须写进 S1 计划的额外发现**

- **F-A：壳页首帧中位 1823 ms，不是 §6 预估的 300–700 ms。** 首次导航要付 WebView 渲染器冷启动：
  `loadUrl→commit` 中位 730 ms，`commit→首帧` 再 ~485 ms。M1 若按“reveal 时刻”记会高估约 480 ms，
  S1 的 M1 必须改按“**首个内容帧**”定义。
- **F-B：这个诊断构建的 TTFD 中位 4508 ms，比基线（4038 / 4018）差 +470~+490 ms**；同步观测到
  `python_start_done` 1069→1460（+390）、`settings_200` 3391→3988（+597）。即“提前 `loadUrl`”让
  WebView 渲染器与 Python/Chaquopy **抢 CPU**，把 Python 侧整体推后。已超 §7 判负条件 2（>300 ms）。
  构建差异不止一处（壳页 + asset loader + 双导航），此处只报观测值，未做单项归因。

### S0 判据对照与 S1 放行建议

| 判据 | 基线 | R1 诊断构建 | 结论 |
|---|---|---|---|
| M1 首帧可见 | 4053 | 1823（首个内容帧） | 改善 2230 ms，过 1000 ms 线（但远低于预估的 300–700 ms 目标） |
| M3 TTFD | 4038 / 4018 | 4508 | **劣化 ~480 ms，不过**（判负条件 2） |
| M4 白屏帧 | — | 9/10 次出现 2 帧纯色空屏（85 ms 级） | **不过**（判负条件 3；发生在 splash→壳） |

**明确建议：S1 不放行“壳 commit 即撤 splash”这一形态，但可放行修正形态。** 三条前置必须先做：

1. **撤场信号改为“壳页首个内容帧之后”**，不是 commit。可选实现：壳页 `requestAnimationFrame` 双帧后
   经 `JavascriptInterface` 回报（与现有 `DeLectorStartup` 桥同构），Java 收到后再 `revealWebView`；
   这样 splash 淡出全程盖着已有内容的壳页，S0 观测到的 2 帧空洞应消失。改后必须**重新逐帧复验**，
   不接受推断。
2. **把 F-B 的 +480 ms 压回 300 ms 内**，否则 M3 直接判负。这是 S1 的主要工程风险，不是小项：
   候选手段（按代价排序）——壳 `loadUrl` 延后到 `python_start_done` 之后；壳页更轻（去掉图片/字体）；
   真机复测确认是否只是模拟器 CPU 争用。
3. **M4 的可视闸把“splash→壳”也纳入**，且判据改按“首个内容帧”计时；否则 S1 会带着 85 ms 空洞合入。

若坚持原形态（commit 即撤）→ 按 §7 判负条件 2 与 3 **判负**。


---

## §8B S1 实测结果（2026-11-10，x86_64 模拟器）

> 本节是 S1 **修正形态**的交付物，只做两件事：①撤场信号改为「壳页首个内容帧之后」；
> ②把提前 `loadUrl` 造成的 TTFD 劣化压回 300 ms 内。真机项未覆盖（见 §10）。
> 设备/构建/包名同 §8A；全部为**窗口模式** AVD（`-no-window` 变体实测整体慢 35%+，同构建不可比，已弃用）。

### S1-a 实现形态

- `android/app/src/main/assets/shell/boot.html`：自包含（无外链、无图片、无字体请求），底色 `#FAF8F5`；
  **无任何 CSS 动画**（归因 A1）。
- `MainActivity`：
  - `WebViewAssetLoader` 把 `/assets/` 映射到 APK assets；壳 URL =
    `https://appassets.androidplatform.net/assets/shell/boot.html`。不新增第二份静态镜像、不注册 SW。
  - `shouldInterceptRequest` 只拦 appassets；真实页（`127.0.0.1:<port>`）原样放行。
  - 壳阶段 WebView 保持 **VISIBLE**（GONE/INVISIBLE 会停止绘制、rAF 不回调），由后加的 splash 整层遮住。
  - 壳页 `requestAnimationFrame` **三帧**后经 `ShellHost.onFirstContentFrame()` 回报 → 主线程
    `revealWebView()`；真实页原有 `onPageCommitVisible + isServerReady` 路径保留且幂等。
  - `loadUrl(壳)` 从 `onCreate` 移到 `python_start_done` 之后（主线程 post），见归因 A2。
- 归因用的测量开关（`SHELL_ENABLED` / `SHELL_LOAD_EAGER`）**已在合入前删除**：行为固定为
  「启用 + `python_start_done` 后加载」，`loadShell()` 只剩一个调用点，其幂等标记一并移除。
  下文 §8B 数字均来自 `SHELL_ENABLED=true / SHELL_LOAD_EAGER=false` 的等价形态（`private static final`
  常量在编译期内联，删分支不改变执行路径），复验见 §8C。
- 壳页状态是 **I1 三层**：inline SVG 图标（`aria-hidden`）+ 文案「正在启动本地服务…」+ 描边胶囊形状；
  无假卡片/假文章行/假计数，无 CSS 动画。`≤360px` 断点下三层同时保留（§8C）。

### S1-b TTFD：基线、单项归因、最终值

口径：每批 `am force-stop` + `pm clear` + `logcat -c` → `am start`，批首弃跑 2 次，有效 8 次取中位；
零点一律 `Process.getStartElapsedRealtime()`。**基线在同一模拟器会话内重建**（`SHELL_ENABLED=false`，
其余代码与 S1 相同）：两轮中位 4105.5 / 4136.5，两轮差 **31 ms** 视作噪声下限；不再引用 §8A 的
4038 / 4018（不同构建，不混用）。

| 变体 | `loadUrl(壳)` 时机 | 壳内动画 | TTFD 中位 | 范围 | 与基线差 |
|---|---|---|---|---|---|
| 基线（无壳）轮 1 | — | — | **4105.5** | 3975–4177 | 0 |
| 基线（无壳）轮 2 | — | — | **4136.5** | 4027–4187 | +31 |
| B | `onCreate` 立即 | 60fps 转圈 | 4421 | 4334–4876 | +315.5 |
| D | `python_start_done` 后 | 60fps 转圈 | 4423 | 4251–4485 | +317.5 |
| E | `onCreate` 立即 | 静态 | 4266.5 | 4124–4482 | +161 |
| F | `python_start_done` 后 | 静态 | 4171 | 4048–4320 | +65.5 |
| **最终（F + 三帧 rAF）** | `python_start_done` 后 | 静态 | **4301.5** | 4213–4347 | **+196** |

**单项归因（每次只改一项，同口径中位相减）**

| # | 只改这一项 | 对比 | Δ TTFD | 结论 |
|---|---|---|---|---|
| A1 | 去掉壳页持续 CSS 动画 | E − B | **−154.5 ms** | 60fps 重绘与 Chaquopy/uvicorn 抢 CPU 是主因之一 |
| A1' | 同上（延迟加载下） | F − D | **−252.0 ms** | 与 A1 同向，量级更大（延迟后动画覆盖了更长的 Python 段） |
| A2 | `loadUrl` 延后到 `python_start_done` | F − E | **−95.5 ms** | 避开与 `Python.start`/assets 解包的正面重叠 |
| A2' | 同上（带动画） | D − B | +2.0 ms | 动画存在时延后基本无效——只砍动画不延后仍会 +161 |
| — | **A1 + A2 合计** | F − B | **−250.0 ms** | 4421 → 4171 |

**最终值与基线的分段对照（中位，零点 A）**

| 段 | 基线轮 1 | 最终 | Δ |
|---|---|---|---|
| `python_start_done` | 1074.5 | 1127.5 | +53 |
| `/api/settings` 首个 200 | 3436 | 3718 | +282 |
| 真实页 `loadUrl → commit`（零点 B 起算） | 645.5 | 206 | **−439.5** |
| 真实页 `loadUrl → TTFD`（零点 B 起算） | 644.5 | 552.5 | −92 |
| **进程 → TTFD** | **4105.5** | **4301.5** | **+196** |

读法：残余劣化全部落在「uvicorn 就绪」这一段（+282 ms，渲染器与 Python 抢 CPU），但真实页 commit
因渲染器已热而快了 440 ms，两者相抵后 TTFD 只 +196 ms。**未用 M1 的改善抵扣。**

> 最终批次比 F 批次高 +130.5 ms，已核实为批次漂移而非三帧 rAF：两次批次的
> `commit_real` 相同（206 vs 207），差量全部在 `settings_200`（3718 vs 3620，+98）。
> 另有 1 批（8 次）因模拟器整体退化（`python_start_done` 2234、`settings_200` 6242，各段≈2×）
> 按「弃跑」作废，不计入中位。

### S1-c M1（首个可见内容帧）

- 壳 `loadUrl` 在 `python_start_done`（1127.5）发出，`shell_frame` 回报在 +234 ms ⇒ **M1 ≈ 1361.5 ms**。
- 相对 §7 基线 4053 ms：**−2691.5 ms**，远超 1000 ms 判据。
- 注：变体 E（立即加载）M1 ≈ 1187 ms，但 TTFD +161；最终形态选择 M1 稍晚、TTFD 更低的 F 形态。
  这**不是**为 M1 调时序。

### S1-d M4 逐帧复验（含 splash→壳）

方法同 §8A S0-b：`screenrecord 9–12 s` → `ffprobe pts_time` → `ffmpeg -vsync 0` 抽帧 → 逐帧分类。
分类新增「壳页底色帧」判定（有判帧条但无文字 = `SHELL_BARE`，等价于露底）；最终形态另去掉判帧条，
只按 `BLANK`（正文区纯 `#FAF8F5` 且无暗像素）判定。

| 构建 | 有效 runs | 露底/空白 | 单帧时长 | 说明 |
|---|---|---|---|---|
| 双帧 rAF + 判帧条 | 10 | **7/10 次各 1 帧** | 49.2 / 68.5 / 99.1 / 67.2 / 70.1 / 67.7 / 64.7 ms（3 次为 0） | 壳页只画出底色+判帧条，文字晚一帧 |
| **三帧 rAF + 判帧条** | 11（2 轮：6 + 5） | **0/11** | — | splash→壳 直切；壳→应用页 0 空白 |
| **三帧 rAF、无判帧条（合入形态）** | 5 | **0/5** | — | 同上，且证明结论不依赖判帧条 |

- **splash → 壳**：最终形态全部为「原生 splash 最后一帧 → 壳页完整内容帧」直切，中间无纯底色帧。
- **壳 → 真实页**：全部 runs 为「末个壳帧 → 应用页完整首帧」直切，0 帧空白（与 §8A S0-b 一致）。
- 双帧 rAF 的 1 帧空洞成因：rAF 第 2 帧回调发生在内容帧**提交**时，Java 撤场可先于该帧**上屏**；
  第 3 帧回调时内容帧已显示。该结论在 10 次中被 7 次复现、3 次未出现（时序竞争），因此必须用三帧。

### S1-e 判据对照与结论

| 判据（§7） | 基线 | 最终形态 | 结论 |
|---|---|---|---|
| M1 改善 ≥ 1000 ms | 4053 | 1361.5（首个内容帧） | 改善 2691.5 ms，**过** |
| M3 TTFD 劣化 ≤ 300 ms | 4105.5（同会话轮 1） | 4301.5 | +196 ms，**过** |
| M4 两段均无白屏/露底 | — | splash→壳 0 帧、壳→应用 0 帧（11 + 5 次） | **过** |
| 壳→真实页无闪跳 | — | 直切，无中间帧 | **过** |

**结论：S1 修正形态三项判据全部通过，按合入形态清理后开 PR（测量开关已删除、壳页过 I1，见 §8C）。**
真机（arm64）未覆盖，`-no-window` 与退化批次的数字已明确作废，不外推。

---

## §8C 合入形态（删开关 + I1）与复验

> 落地：PR **#330**（`feat/android-local-shell`，merge commit `6d38ddf`，2026-11-10）。

### S1-f 合入形态改动

| 项 | 改动 | 判据 |
|---|---|---|
| 测量开关 | 删除 `SHELL_ENABLED` / `SHELL_LOAD_EAGER` 及其 `if` 分支；`webView` 恒 `VISIBLE`；`loadShell()` 只剩 `python_start_done` 一个调用点，`shellLoadStarted` 幂等标记一并删除 | 行为锁定「启用 + 延后」，无默认值可配、不进 BuildConfig / 资源 |
| 壳页 I1 | 状态从「一句文字 + 圆环」改为 **inline SVG 图标（`aria-hidden`）+ 文案 + 描边胶囊（形状）** 三层；无假卡片/假文章行/假计数；仍无任何 CSS 动画 | 删掉任一通道后剩两层仍有语义；320 px 渲染与 411 dp 设备截图三层均在 |

### S1-g 删开关后的复验（同构建，x86_64）

- 构建：`sync_android_sources.py` + `gradle assembleEmulatorDebug` 成功；APK 安装成功；冷启 2 批
  （每批弃 2 + 有效 5，`force-stop` + `pm clear` + `logcat -c`）。
- 功能信号与 §8B 一致：`python_start_done` → `shell_frame` → 真实页 commit → `TTFD_FIRST_ARTICLE_MS`
  全序列存在，壳页均命中（`shell_frame` 2031–2833 ms）。
- **数字不可比**：该会话整体变慢（`python_start_done` 1712–2232 vs §8B 1127.5；
  `settings_200` 4515–5653 vs 3718），两批 TTFD 中位 6266 / 7579 ms。按 §7「不跨会话 / 不跨构建比较」，
  这两批**不作为 TTFD 证据**，只用来说明行为未变（常量内联 ⇒ 删分支的执行路径与
  `SHELL_ENABLED=true / SHELL_LOAD_EAGER=false` 逐字节等价）。
- 逐帧（540×960 screenrecord）：52 帧内 0 段纯底色；1080 宽录制 59 帧内出现 1 帧纯底色（21 ms，
  位于启动早期）。该会话 screenrecord 仅 4–5 fps（宿主 CPU 93%），**不足以复验帧级结论**；
  合入依据仍是 §8B 的 60 fps 复验（双 rAF 7/10 露底判死、三帧 rAF 11/11 + 5/5 为 0）。
- 设备截图（壳页阶段）：标题 + 副标题 + 「图标 + 文案 + 胶囊」状态，三层齐全。

---

## §9 与既有计划的关系

- `docs/plans/2026-11-09-android-startup-latency.md` 的 **Task 4–5（splash 复刻壳，`file://`）** 与本线
  S1 目标重叠但方案不同：它只复刻 splash 视觉、预期省 100–300 ms；本线要求用
  `WebViewAssetLoader` + 真实壳语义（撤场、失败态、快照）。**建议**：该 Task 4–5 标记为「被本线 S1
  取代」，PR-③（就绪轮询策略）与本线无冲突，可独立先合。
- `docs/adr/2026-11-09-adr-0032-python-off-first-screen-path.md` §9 已判定「缓存优先首屏在安卓只有
  24.5 ms 提前量」——本线不改这个结论，反而解释原因：cache-first 的前提是「页面已经能加载」，
  而安卓上页面本身要等服务。本线把「页面能加载」这一步本地化，是 §9 结论的补集，不是反例。

---

## §10 未覆盖（真机才能验，禁止外推）

1. arm64 真机的首帧与 TTFD（本机 `adb devices` 为空）。
2. 低端机（2–4 GB）上「WebView 提前创建」的内存峰值与是否触发 LMK。
3. Chaquopy 在真机上的 asset 解压成本（录入机型差异极大）。
4. 真机 WebView 版本对 `WebViewAssetLoader` / SW 行为差异（模拟器是 145.0.7632.218）。
5. 厂商 ROM 对 `https://appassets.androidplatform.net` 的拦截或代理策略。
