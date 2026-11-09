# Android 启动耗时压缩（就绪检测 + WebView 并行）Implementation Plan

> **Goal**: 在**不改 Python 引擎加载时机、不改打包方式**的前提下，压缩两段可测的启动固定开销：① 服务就绪检测的轮询空转（本轮 Task ③）；② Python 启动期间 WebView 完全空转的串行窗口（本轮 Task ②）。每项独立 PR、独立实测验收。
> **Tech Stack**: Android(Java, AGP 8.4.2 / Gradle 8.6) + Chaquopy + WebView；纯 Java 零依赖单测（javac 直跑）+ pytest 静态守卫；x86_64 模拟器实测。
> **Spec Reference**: 本文档；取证来源为本轮启动剖析（x86_64 模拟器，基线 master `78dda1b` / v5.22.0）。
> **Global Constraints**:
> - 硬件条件不许改：**不加打包步骤、不改 ABI、不引新依赖**。
> - 主工作树 `d:\Code\DeLector` 不写文件、不跑构建；全部工作在独立 worktree。
> - 每项一个 PR，**不混**、不自动合并；分支从 `origin/master` 开。
> - 所有数字必须标明「x86_64 模拟器」，**绝对不可外推真机**；真机未验证的结论要在 PR 里写明。
> - 验收方法固定：同一台模拟器、`am force-stop` + 清 `cache/WebView` 与 `Service Worker/CacheStorage`、3–7 次取中位数并给范围；与下表基线逐项对照。
> - 不写死端口、不改静态资源 marker 语义、不改 Python 降级语义（见「不变量清单」）。
> - 不 force push、不改历史、不直推 `master`。

---

## [NOTE] 基线（x86_64 模拟器；每次验收都跟这组比）

设备：`Medium_Phone_API_37.0`（API 37，WebView 145.0.7632.218），包名 `org.delector.app.emulator`，APK 由基线 `78dda1b` 构建（versionCode 52200）。
单位 ms，中位数（括号为实测范围）。时刻基准 = `ActivityManager: Start proc`。

| 阶段 | 首次安装后第一次启动 | 常规启动 | 依据来源 |
|---|---|---|---|
| 进程创建 → splash 首帧（`Displayed`） | 734 / 737 | 726（669–951） | ActivityManager `Displayed`；`am start -W` TotalTime 750（685–985） |
| `Displayed` → Python banner | ~280–340 | 190（178–253） | logcat `[DeLector]` banner |
| banner → `NLP 引擎` 行 | ~1550–1700 | 1235（1190–1311） | logcat + spaCy `DeprecationWarning` 分界 |
| `NLP 引擎` 行 → `Application startup complete` | ~230–240 | 154（152–157） | uvicorn stderr |
| **startup complete → 首个 `GET /`** | ~610–800 | **550（420–595）** | `python.stdout` 访问日志 |
| 导航 → FCP | 332 / 880 | 824（424–900） | CDP Paint Timing |
| 导航 → DOMContentLoaded | 1344 / 1024 | 1237（1147–1344） | CDP Navigation Timing |
| 导航 → load | 1482 / 1193 | 1289（1193–1736） | CDP Navigation Timing |
| 导航 → 首条 `.article-row` 可见 | ~1400 / ~1060 | 1159–1375 | CDP DOM 轮询 |
| 模型预热（后台，不阻塞首屏） | 1234 / 1011 | 1000（980–1133） | `模型预热：完成` 日志 |

**端到端（按中位数相加的近似，非单次实测）**：
- 常规启动：进程创建 → 首条文章可见 ≈ **4.0 s**
- 首次安装：≈ **4.6–5.0 s**

**已知的段间关系（本轮两项改动的靶子）**：
- 就绪检测窗口 `startup complete → GET /` = 550 ms，其中轮询间隔 600 ms、探测请求本身 < 30 ms ⇒ **绝大部分是空转对齐**。
- `0 → startup complete`（约 2.3 s）期间 WebView 已创建但**未发生任何导航**，完全串行；首屏渲染的 WebView 冷启动成本（渲染进程拉起等）全部压在服务就绪之后。

---

## [NOTE] 不变量清单（本计划核心）

| # | 不变量 | 本轮怎么保证不被破坏 |
|---|---|---|
| I1 | **端口文件是唯一端口真相**：Python 写 `files/server-port.txt`（`DELECTOR_PORT_FILE`），Java 只读不猜；`8000` 不得写死 | ③ 只改「读文件的频率」，不动 `readServerPort()` / `serverBaseUrl()` / 环境变量名；沿用并扩展 `tests/test_android_webview_policy.py` 的静态断言（禁止 `http://127.0.0.1:8000`、必须 `serverBaseUrl(serverPort)`）。② 不新增任何端口来源。 |
| I2 | **静态资源 marker 校验**：`files/static.version` = `versionCode` 或 `versionCode:assetFingerprint`；不匹配才整目录重解包 | ③/② 都不触碰 `syncStaticAssets()` / `copyAssetFolder()` / marker 读写；PR diff 用 `git diff --stat` 证明未改。 |
| I3 | **失败可见**：Python 异常必须让 `fatalError` 原文可选中、不被「超时」文案覆盖 | ③ 保留 `if (fatalError != null) return;` 的循环早退与超时分支判断；② 的静态壳必须能被 `reportFatal` 的终端态覆盖（fatal 时强制显示原生 splash 层）。 |
| I4 | **红线 1 降级语义**：spaCy 缺失 ⇒ `pure_python`；运行期模型加载失败 ⇒ 硬失败 | 本轮**完全不碰** `delector/` 下任何 Python 文件；PR diff 中 `delector/` 必须为 0 文件。 |
| I5 | **冷启动不得出现空白页**：splash 必须覆盖到首屏有内容 | ③ 不改 splash 显隐时序；② 的本地壳在视觉上与 splash 同源（同色 `#FAF8F5`、同文案、同进度条），且壳未绘制完成前原生 splash 不隐藏；实测用逐帧截图对照。 |
| I6 | **不新增构建面** | 不新增 Gradle 任务、不加依赖、不改 ABI；单测沿用「纯 Java + javac 直跑 + pytest 包装」的既有形态（参考 `tests/test_android_webview_policy.py`）。 |
| I7 | **CI 分片全量覆盖** | 新增 pytest 文件必须登记进 `tools/ci_shards.py`，否则 `tests/test_ci_hardening_governance.py` 会红。 |

---

## [NOTE] 本轮不做

1. **① `import spacy` 挪到监听之后** —— 会改变 `processor` 导入期的引擎判定时机（红线 1 的判据点），不是纯工程改动，**需单独 ADR，暂缓**。
2. **静态资源解包优化** —— 实测整目录重解包仅 +85~120 ms / 107 文件 / 2.74 MB，收益不足。
3. **ES module 打包 / 预加载** —— 与 `delector/server.py` 的 `no-cache` 回源校验策略冲突，需重新设计缓存语义。
4. **Perfetto / systrace / Choreographer 帧级取证** —— 模拟器上 trace 开销会扰动被测对象；本轮继续用 logcat 时间戳 + CDP Timing 双侧交叉。
5. 真机（arm64）验证 —— 环境不具备，所有结论只在模拟器成立。

---

## [NOTE] File-Occupancy Partitioning

| Task | 独占写集 |
|---|---|
| T1–T3（PR-③） | `android/app/src/main/java/org/delector/app/StartupReadinessPolicy.java`（新增）、`android/app/src/test/java/org/delector/app/StartupReadinessPolicyTest.java`（新增）、`tests/test_android_startup_readiness_policy.py`（新增）、`tools/ci_shards.py`、`android/app/src/main/java/org/delector/app/MainActivity.java`（仅 `pollServerReadiness` 区域） |
| T4–T6（PR-②） | `android/app/src/main/assets/shell/startup.html`（新增，随 APK 打包，非 `static/` 同步产物）、`MainActivity.java`（`onCreate` / WebViewClient 区域）、`tests/test_android_startup_shell.py`（新增）、`tools/ci_shards.py` |
| 测量 | 只读（脚本在 `%TEMP%`，产物不入库） |

> 两 PR 均改 `MainActivity.java` 但区域不重叠；② 从 `origin/master` 开分支（不叠在 ③ 上），必要时 rebase。

---

## Task 1（PR-③ 的 RED）：抽出可单测的就绪轮询策略

**Files:**
- Create: `android/app/src/main/java/org/delector/app/StartupReadinessPolicy.java`
- Create: `android/app/src/test/java/org/delector/app/StartupReadinessPolicyTest.java`
- Create: `tests/test_android_startup_readiness_policy.py`
- Modify: `tools/ci_shards.py`（登记到 `unit-1`）

**Interfaces（先写测试钉住）:**
- `static int pollIntervalMs(int attempt)`：`attempt < 50` 返回 `120`；否则 `600`。
- `static int maxAttempts()`：返回 `100`（前 50 次快轮询 6 s + 后 50 次 30 s ≈ 保持既有 36 s 总预算）。
- `static boolean isReadyStatus(int httpCode)`：`200 <= code < 400`。

**TDD 步骤:**
1. 先写 `StartupReadinessPolicyTest`（零依赖 main，输出 `PASS/FAIL <name>` + `checks=N failed=M`，与 `WebUrlPolicyTest` 同格式）。
2. 写 `tests/test_android_startup_readiness_policy.py`：javac 直编直跑 + 静态断言（策略类零 `android.*` 导入）+ 断言 `MainActivity` 已改为调用该策略。
3. `pytest tests/test_android_startup_readiness_policy.py -q` 必须 **RED**（策略类尚不存在）。

## Task 2（PR-③ GREEN）：MainActivity 接入

**Files:** Modify `MainActivity.java`（仅 `pollServerReadiness`）

**改动点:**
- 循环上限 `60` → `StartupReadinessPolicy.maxAttempts()`。
- `Thread.sleep(600)` → `Thread.sleep(StartupReadinessPolicy.pollIntervalMs(i))`。
- 就绪判定 `code >= 200 && code < 400` → `StartupReadinessPolicy.isReadyStatus(code)`。
- **不动**：端口文件读取、`serverBaseUrl`、fatalError 早退、200 ms splash 延迟、超时分支。

**验收:**
- `pytest tests/test_android_startup_readiness_policy.py tests/test_android_webview_policy.py -q` 全绿。
- 模拟器 5 轮冷启动：`startup complete → GET /` 中位数应从 **550 ms** 降到 **≤ 300 ms**（目标省 200–400 ms）；`Displayed` 与 Python 各段不得劣化超过离散范围。
- splash 视觉回归：每轮在 `loadUrl+0/100/200/400/800 ms` 截图，与基线同刻截图逐张比对；结论必须来自截图，不得凭判断。

## Task 3（PR-③ 收尾）：提交与报告

- 单独 PR（base `master`），PR 正文贴改前/改后对照表 + 截图证据 + 逐 job CI 结论（区分 failure / cancelled / skipped）。
- 不自动合并。

---

## Task 4（PR-② 的 RED）：启动静态壳

**Files:**
- Create: `android/app/src/main/assets/shell/startup.html`
- Create: `tests/test_android_startup_shell.py`
- Modify: `tools/ci_shards.py`

**壳的定义（回答「本地静态壳是什么」）:**
- 一个自包含 HTML（内联 CSS，无外链、无 JS 依赖），视觉与现有原生 splash 完全一致：背景 `#FAF8F5`、`DeLector` 标题、副标题、不确定进度条、状态文案区。
- 通过 `webView.loadUrl("file:///android_asset/shell/startup.html")` 在 `onCreate` 末尾立即加载；**不是** `static/` 同步产物，不参与 marker 指纹（避免 I2 被连带改动）。

**TDD 步骤:**
1. `tests/test_android_startup_shell.py` 先断言：文件存在、无 `http://`/`https://` 外链、含 `#FAF8F5`、`MainActivity` 中存在 `android_asset/shell/startup.html` 引用、且该 `loadUrl` 出现在 `initAndStartServer` 启动线程之前。
2. RED：壳文件不存在。

## Task 5（PR-② GREEN）：时序与水合

**时序设计（回答「怎么水合 / API 未就绪怎么重试 / fatalError 怎么保留」）:**
1. `onCreate`：创建 WebView → 立即 `loadUrl(shell)` → 原生 splash 覆盖在 WebView 之上（不变）。
2. 背景线程：`syncStaticAssets` → 清端口文件 → `Python.start` → Python `main` → 轮询就绪（沿用 ③ 的策略）。
3. 就绪：`webView.loadUrl(serverBaseUrl(port))` → **首次 `onPageFinished` 或壳后第一次主框架 `onPageCommitVisible`** 时隐藏 splash（替代固定 200 ms 作为过渡，若实测有白屏则回退保留 200 ms）。
4. **API 未就绪**：壳不发起任何 API 请求；应用页面只在服务就绪后加载 ⇒ 不存在「页面对未就绪服务发请求」的窗口。导航后的偶发失败继续走既有 `onReceivedError → checkAndReloadServer()`（上限 10 次）。
5. **fatalError**：`reportFatal` 保持原路径；fatal 时 `mainHandler.post` 强制 `splashLayout.setVisibility(VISIBLE)`、`webView.setVisibility(GONE)`，错误文本可选中，不被壳或超时文案覆盖。

**收益假设:** WebView 渲染进程拉起、Chromium 网络栈初始化从「服务就绪后」提前到「onCreate 后」，预期把导航 → 首条可见的 **1159–1375 ms** 压低 100–300 ms（模拟器）。**这是待验证假设，不是承诺**。

**验收:**
- 模拟器 5 轮冷启动，与 PR-③ 合并后的基线比：`导航 → FCP / DCL / 首条可见` 三段各给中位数与范围。
- 视觉：壳 → 应用页切换逐帧截图，不得出现空白帧或闪色。
- `pytest tests/test_android_startup_shell.py tests/test_android_webview_policy.py -q` 全绿。

## Task 6（PR-② 收尾）：提交与报告

- 单独 PR（base `master`），PR 正文写清「改了什么 / 实测对照 / 已知边界（仅模拟器）/ 逐 job CI 真实结论」。
- 不自动合并。

---

## [NOTE] 验收报告模板（每项必填）

1. 改了什么（文件 + 机制一句话）。
2. 改前 / 改后实测表：同机、同冷启动控制、次数、中位数、范围。
3. splash / 切换视觉证据（截图路径或结论，说明是否逐帧比对）。
4. PR 链接 + 每个 CI job 的真实结论（failure / cancelled / skipped 必须区分，不得笼统写「CI 通过」）。
5. 已知边界：仅 x86_64 模拟器；真机未验证。
