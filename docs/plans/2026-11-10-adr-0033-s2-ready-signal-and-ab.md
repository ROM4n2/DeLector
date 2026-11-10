# ADR-0033 S2 测量切片：就绪信号驱动重试 (b) + 同构建 TTFD A/B (a)

- **日期**：2026-11-10
- **状态**：已测；已开 PR（范围见 §7.1），**未合并**，等 CI 全绿
- **上游**：[[ADR-0033]](../adr/2026-11-10-adr-0033-python-out-of-first-screen-completely.md) §6/§7
- **前序**：`docs/plans/2026-11-10-adr-0033-s1-static-intercept.md`（S1 已测）

---

## 1. 范围

### 1.1 (b) 就绪信号驱动的重试

- 触发者：**Java 侧就绪轮询**（`pollServerReadiness` 拿到 `/api/settings` 200 且端口 == 8000 时）。
- 载体：`webView.evaluateJavascript("window.notifyServerReady()")`，只在页面已加载时执行。
- 页面侧：`window.notifyServerReady()` → `articleStore.retryIfWaiting()`。
- 与 #329 的关系：**同一个 cycle、同一串退避间隔、同一个 `runAttempt`**；`retryIfWaiting()` 只做
  「取消待触发的 timer → attempts+1 → 立刻发下一次请求」，**不新建 cycle**。用户可见的
  `retryNow()`（强制重开一轮预算）保持原样，也没有第二套重试代码。
- 归因分离：该钩子只在 `settings_200` 之后执行；B 组 10 次样本的 TTFD（中位 1034ms）**全部早于**
  `settings_200`（~3.0s），因此它不可能改变 TTFD。

### 1.2 (a) 同构建 A/B

- 同一 commit、同一份 JS/后端，只有 `MainActivity` 一个编译期常量
  `LEGACY_READY_GATE` 不同：
  - **A（旧行为）**：`onCreate` 不加载；`python_start_done` 后上壳页；服务就绪后导航真实页
    （静态页由 Python 提供，拦截层不生效）。`navCount = 2`（壳页 + 真实页）。
  - **B（新路径）**：S1 的提前导航 + 应用 origin 静态拦截 + 本次 (b) 就绪钩子。`navCount = 1`。
- 该常量**只存在于两个临时 APK**；测完已从代码中整体删除（无开关、无死分支进入最终代码）。

### 1.3 不动的

后端、构建脚本、桌面、API 语义、重试参数（退避序列仍是 200/400/800/1600/3200，预算 12000ms）。

---

## 2. Service Worker 与拦截层（动手前结论，本轮补测验证）

| 问题 | 结论 |
| --- | --- |
| 拦截响应会被 SW 缓存住吗 | 会，但 `sw.js` 是 **network-first**（`fetch(request,{cache:"no-cache"})`），拦截层返回 200 后 SW 视为最新网络值覆盖缓存；只有网络失败才回落 Cache Storage。拦截响应另加 `Cache-Control: no-cache`，HTTP 缓存也不会复用旧副本。 |
| 发版后会不会吃 APK 旧资产 / 被旧 SW 钉死 | 不会。`/sw.js` **不在拦截白名单**，永远来自 Python（Android 上即 APK `assets/static` 解包后的同一份），`CACHE_NAME` 与资产同版本；APK 升级 → `syncStaticAssets` 重解包 → activate 清旧缓存。 |
| 新路径引入的真实回归 | **有**：页面先于 Python 加载时，`window.load` 里的 `register("/sw.js")` 必然因连接被拒失败且被 `.catch` 吞掉 → 新路径下 SW 永远注册不上，安卓离线能力静默丢失。 |
| 处置（最终形态） | 把「注册 SW」挂到同一个就绪钩子上补一次（`window.notifyServerReady()` 内 `register("/sw.js",{updateViaCache:"none"})`）。验证：冷启后 CDP `navigator.serviceWorker.getRegistrations()` = **1 条，scope `http://127.0.0.1:8000/`，controller=true**。不改白名单、不按版本串跳过、不改 SW 缓存策略。 |
| 处置（测量期） | **不禁用**。每次样本 `pm clear` 清空 SW 存储与 Cache Storage，A/B 两侧同条件；network-first 不遮蔽。 |

---

## 3. 测量协议

- 设备：`Medium_Phone_API_37.0`（x86_64 模拟器，窗口模式）。**arm64 真机未覆盖**（`adb devices` 无真机）。
- 每次样本：`am force-stop` → `pm clear` → `logcat -c` → `am start`（非阻塞）→ 等 18s → 采集。
- 每个 APK 安装后先跑 1 次 warm-up 弃跑（ART/dex 与资产首次解包）。
- 交替：Round 1 = A×5 → B×5；Round 2 = B×5 → A×5。
- 采集：logcat（`DeLectorProbe` / `TTFD_FIRST_ARTICLE_MS` / `Uvicorn running on`）+ WebView CDP
  （`performance` marks、`/api/articles` 资源条目、`.article-row`、SW 注册）。
- 零点：
  - **进程零点**：`Process.getStartElapsedRealtime()`。
  - **导航零点**：`StartupProbe.navZero()`，A 取真实页 `loadurl`、B 取 `loadurl_first_paint`；
    M1 取**其上一条导航**（A=壳页 `loadurl_shell`，B=`loadurl_first_paint`）。
- 接管零点换算：`articles-data-ready`（相对 navigationStart）+ 该导航的 `t_proc_ms`；
  uvicorn 监听时点 = `python_start_done.t_proc + (logcat Δt)`，同一次冷启内只用时间差。
- 作废批次（写明理由）：首批 10+5 次在**无头 + swiftshader** 环境采集，绝对 TTFD 漂移到 3.8–12.4s、
  A 组多次 18s 内未完成，且缺少导航零点列 → 整批作废，换窗口模式重测；窗口模式下 B 的 TTFD
  与 S1（1065ms）一致，说明该环境才是可复现基线。

---

## 4. 结果

### 4.1 TTFD（首条 `.article-row` 首次绘制）

| 组 | 进程零点中位 | 范围 | 导航零点中位 | 范围 |
| --- | --- | --- | --- | --- |
| A Round 1（5 次） | **3411ms** | 3216–3607 | 406ms | 400–423 |
| B Round 1（5 次） | **1026ms** | 1010–1131 | 568ms | 558–642 |
| **改善（R1）** | **2385ms** | — | — | — |
| A Round 2（5 次） | **3410ms** | 3344–3539 | 389ms | 382–438 |
| B Round 2（5 次） | **1042ms** | 971–1227 | 579ms | 507–620 |
| **改善（R2）** | **2368ms** | — | — | — |
| 合并 A（10 次） | **3410.5ms** | 3216–3607 | 401ms | 382–438 |
| 合并 B（10 次） | **1034ms** | 971–1227 | 573.5ms | 507–642 |
| **合并改善** | **2376.5ms** | — | — | — |

- 两轮方向一致；每轮内 **B 的 5 个样本全部快于 A 的 5 个样本**（无交叉）。
- **噪声下限** = 同组极差上限 **391ms**（A 合并组）；轮间中位漂移 A 1ms / B 16ms。
  2376.5ms 的改善是噪声下限的 **6.1 倍**，不靠噪声。

### 4.2 M1 首个内容帧（辅助，不计入 TTFD 收益）

| 组 | 进程零点中位 | 范围 | 导航零点中位 | 范围 | 事件 |
| --- | --- | --- | --- | --- | --- |
| A（10 次） | 1077.5ms | 999–1214 | 159ms | 134–272 | `shell_frame`（壳页 3 次 rAF） |
| B（10 次） | 805.5ms | 756–985 | 341ms | 304–463 | `content_frame`（真实页 commit+1 帧） |

两类 M1 **仪器不同、不可比**，只单列，不用 M1 抵 TTFD。

### 4.3 接管（B 组 10 次；A 组同列但语义不同，不可比）

| 指标 | 值 |
| --- | --- |
| uvicorn 监听（进程零点，B） | 中位 **3022ms**（2977–3063） |
| `articles-data-ready` − uvicorn 监听 | 中位 **80.5ms**（45–132） |
| `/api/articles` 请求数 | 每次 **5 条**（初始 1 + 退避 3 + 就绪钩子 1） |
| `ready_notify` 返回值 | 10/10 为 `true`（确有待触发的 timer 被打断） |
| `skip_reload` / 二次导航 | 1 / 无 |
| `navCount` | **1**（10/10） |
| 接管后 DOM | `.article-row` = 4，无重试按钮 |

A 组同口径 `data-ready − uvicorn` 为 437–537ms，但它在 uvicorn 就绪后还要导航 + 加载页面，
**与 B 不同语义，不得相减或取平均**。

### 4.4 首次交互（首次打开文章：调用 `openReader` → `#reader-content` 首个段落节点插入）

| 组 | 中位 | 范围 | 同请求 `fetchMs` 中位 |
| --- | --- | --- | --- |
| A（5 次） | 119ms | 37–140 | 115ms |
| B（5 次） | 23ms | 22–24 | 18ms |

B 比 A **快 96ms**（方向为改善，非回退）。单轮、顺序 B→A，未做交替；A 偏慢的成因**未核实**
（候选：A 的首个文章请求更贴近 uvicorn 就绪点、服务端首次 NLP 请求开销），不作为收益主张。

---

## 5. 阈值重述与逐条判定

ADR-0033 §7 原文口径：
- 安卓 TTFD 中位数改善 **≥1000ms**，≥5 次冷启 × 2 轮，两轮方向一致；M1 单列、不计入 TTFD 收益。
- 安卓接管：uvicorn 就绪 → 真实列表在屏 **≤1000ms**，**`navCount == 1`**；需刷新/切页即判负。
- 首次交互回退 **>50ms 且 >5%** 即判负。
- 桌面：生产壳基线未测，不实施（本切片未动桌面）。
- 禁止跨构建相减、跨零点混算、用 M1 抵 TTFD。

| 判据 | 结论 |
| --- | --- |
| TTFD 改善 ≥1000ms、两轮同向 | **通过**：2385ms / 2368ms，两轮同向，组内无交叉；合并 2376.5ms |
| TTFD 劣化 >50ms | 未发生 |
| 接管 ≤1000ms 且 `navCount == 1` | **通过**：中位 80.5ms、最大 132ms，10/10 `navCount == 1` |
| 首次交互回退 >50ms 且 >5% | **未触发**（B 快 96ms；该指标只判回退，改善不作收益主张） |
| 白屏/露底 | 本切片未重测（渲染路径与 S1 相同）；S1 的 6 帧结论继续有效 |
| 预算耗尽 UI | 本切片未重测（`retryNow` 与 UI 未改）；S1 人为场景结论继续有效 |

**关于 (b) 的机制证据**：10/10 样本均出现 5 条 `/api/articles` 且 `ready_notify=true`，说明第 5 次
请求是被就绪钩子从「待触发的 1600ms 末档」提前触发的；若不打断，下一次尝试在 uvicorn 就绪后约
+1.6s。该「+1.6s」是**代码路径推断，不是对照实测**，不与 S1 的 1382.5ms 相减。

---

## 6. 未覆盖 / 不可比

- arm64 真机、低端机：未覆盖，不推断。
- 8000 被占用的端口顺延：未构造；该场景仍是二次导航，不计入 `navCount == 1`。
- 首次交互只测「打开文章」，未测首次点词 / 首次分析 / 首次编辑；后三者在本次改动里没有新增
  成本（均发生在 Python 就绪后，与 A/B 用同一后端），但**未实测**。
- 桌面：未动、未测。
- 与 S1、#330 的数字**不跨构建相减**；本报告所有差值都来自同批同构建的 A/B。

---

## 7. 代码改动（未提交）

| 文件 | 改动 |
| --- | --- |
| `android/.../MainActivity.java` | 新增 `notifyServerReadyInPage()`（就绪且端口 8000 时注入、`readyHookInjected` 幂等、`missing` 时复位交给 `onPageFinished` 兜底）；就绪分支调用；`onPageFinished` 兜底；临时常量 `LEGACY_READY_GATE` 已在测后删除 |
| `static/js/article-store.js` | 新增 `retryIfWaiting()`（只打断待触发 timer） |
| `static/js/reader.js` | 新增 `retryArticlesIfWaiting()` 包装 |
| `static/js/main.js` | 新增 `window.notifyServerReady()`（打断退避 + 补注册 SW） |
| `tools/article_store_probe.mjs` | 新增 R11–R13：只打断等待中的退避、在途请求不被二次触发、打断后仍按原序列继续（25/25 通过） |

`tools/sync_android_sources.py` 已重跑并 `--check` 通过；docs 闸 39 passed。

### 7.1 PR 范围：三块功能 + 壳页死代码清理

进 PR 的功能改动：

1. **静态拦截**：`shouldInterceptRequest` 只拦 `/`、`/style.css`、`/js/*`，从 APK `assets/static/` 返回；`/api/*` 一个字节都不拦。
2. **就绪信号驱动重试**：Java `/api/settings` 200 → `notifyServerReady()` → `retryIfWaiting()`。
3. **SW 就绪补注册**：修复 S1 引入的「页面先于 Python 加载 → `register("/sw.js")` 必失败且被 `.catch` 吞掉」的静默回归。

同 PR 删除的壳页死代码（S1 起壳页只作兜底资产，实际已无调用点）：

| 删除项 | 说明 |
| --- | --- |
| `MainActivity.loadShell()` | 无调用点；连同其 javadoc 一并删除 |
| `SHELL_URL` / `ASSET_DOMAIN` / `assetLoader` 字段与初始化 | `WebViewAssetLoader` 的唯一用途就是壳页虚拟 origin |
| `ShellBridge`（`ShellHost` JS 接口） | 只服务壳页的 `onFirstContentFrame()` 回报，且 `shell_frame` 探针标记随之消失 |
| `shouldInterceptRequest` 里的 `assetLoader` 分支 | 只剩 `maybeServeAppStatic` 一条拦截路径 |
| `android/app/src/main/assets/shell/boot.html` | 3.3 KB 自包含壳页；全仓无引用后删除，`assets/shell/` 目录随之消失 |
| `androidx.webkit:webkit:1.10.0` | 删除 `WebViewAssetLoader` 后成为无引用依赖 |

- **grep 无残留证明**：`loadShell|SHELL_URL|ASSET_DOMAIN|assetLoader|ShellBridge|ShellHost|shell_frame|loadurl_shell|boot\.html|assets/shell|WebViewAssetLoader` 在 `android/`、`static/`、`tests/`、`tools/` 中零命中（仅历史文档与 `work.log` 保留记录）。
- **打包面**：`assets/static` 同步产物不变（指纹一致），只少了 `assets/shell` 一个文件；APK 少 3.3 KB 资产 + 一个未使用依赖。
- **测量开关**：`LEGACY_READY_GATE` 已不存在于最终代码，全仓 grep 零命中。

## 8. 回滚锚点

- Java：撤 `notifyServerReadyInPage` 及其两处调用即可回到 S1 行为（拦截与提前导航保留）。
- JS：撤 `retryIfWaiting` / `notifyServerReady` 与 R11–R13；重跑 `sync_android_sources.py`。
- 无数据迁移、无构建面变更、无 API 变更。

## 9. 清理与 worktree

- 模拟器 `adb emu kill`；`adb forward --remove-all`；临时 APK（A/B）、采集脚本、结果文件全部删除。
- worktree：`MainActivity.java`、`static/js/{article-store,reader,main}.js`、`tools/article_store_probe.mjs`、
  `android/app/src/main/assets/static/**`（同步产物）、本文档、ADR-0033、`INDEX.md`、
  `docs/agents/android-local-runtime.md`、`WORKMEMORY/work.log` 未提交。未开 PR、未合并。
