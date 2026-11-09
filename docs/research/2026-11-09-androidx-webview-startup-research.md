# AndroidX WebView 异步启动（`startUpWebView`）可行性调研

> 结论先行：**升级到 `androidx.webkit:webkit:1.16.0` 不需要动 compileSdk / AGP / Gradle / Chaquopy**。
> 该 AAR 的元数据要求 `minCompileSdk=33`、`minAGP=7.2.0`、`minSdk=24`，本项目（compileSdk 34 / AGP 8.4.2 / minSdk 24）已满足。
> 真正的风险不在构建链，而在：新增 Kotlin 运行时依赖、把 WebView 初始化时机从 UI 线程挪到后台后的行为回归、以及收益必须由 TTFD 证明而不一定存在。
>
> 取证时间：2026-11-09。所有构建链数值均给出来源；无法证实的地方明确标「未证实」。

---

## 1. 要解决的问题

`docs/plans/2026-11-09-androidx-webview-startup-upgrade.md` 的靶子是 #320 暴露的回归：

| 构建（x86_64 模拟器，同会话 A/B，各 7 次） | TTFD 中位数 | 范围 | `Displayed`（旁证） |
|---|---|---|---|
| 改前（master 含 #317） | 3966 ms | 3857–4932 | 824 ms |
| #320（WebView 延后到首帧后创建） | 4704 ms | 4133–4894 | 638 ms |

机制判断：`new WebView(this)` 首次调用会同步加载 Chromium 提供方与网络栈；把它从「进程启动后立即」挪到「首帧之后」，就落进了 Chaquopy + 静态资源解压占满 CPU 的窗口，Chromium 初始化与 Python 启动互相拖慢。
`startUpWebView` 正是把这个初始化搬到后台线程并尽早开始的官方手段。

---

## 2. `startUpWebView` 的 API 形态与调用时机

### 2.1 API（1.16.0 起稳定）

```java
WebViewStartUpConfig cfg = new WebViewStartUpConfig.Builder(
        Executors.newSingleThreadExecutor())
        .shouldRunUiThreadStartUpTasks(false)   // 可只跑后台任务
        .build();

WebViewCompat.startUpWebView(
        context,
        cfg,
        new WebViewOutcomeReceiver<WebViewStartUpResult, WebViewStartupException>() {
            @Override public void onResult(WebViewStartUpResult result) {
                // 保证在主线程回调；此后可安全创建 WebView
            }
            @Override public void onError(WebViewStartupException error) {
                // 降级：直接 new WebView(context)，走同步路径
            }
        });
```

来源（官方）：
- 优化指南 <https://developer.android.com/develop/ui/views/layout/webapps/optimize-webview-startup>（页面标注 Last updated 2026-10-23）
- 发布说明 <https://developer.android.com/jetpack/androidx/releases/webkit>：1.16.0 起 `startUpWebView` 与 `ProcessGlobalConfig` / `WebViewStartUpConfig` 中的异步启动配置从 experimental 转 stable，同时库的 minSdk 提到 24。

本地实证（下载 AAR 后检查，非文档转述）：

```
webkit-1.16.0.aar
  META-INF/.../aar-metadata.properties:
    minCompileSdk=33
    minAndroidGradlePluginVersion=7.2.0
    coreLibraryDesugaringEnabled=false
  AndroidManifest.xml: <uses-sdk android:minSdkVersion="24" />
  classes.jar 含 WebViewCompat.startUpWebView、WebViewStartUpConfig$Builder、
              WebViewCompat$WebViewStartUpCallback（Javadoc 示例用 WebViewOutcomeReceiver）
```

### 2.2 调用时机（官方原文要点）

- 「If your app doesn't need to load a WebView immediately, you can hide the initialization cost completely. Call `startUpWebView` early in your app's lifecycle and wait for the success callback to fire.」
- 「If you trigger `startUpWebView` but don't wait for it to finish before touching other WebView components, the system blocks the UI thread while waiting for the initialization to complete.」
- 「defer instantiating a WebView or calling WebView APIs until there are no other critical-path UI thread operations left to run (such as inflating layout hierarchies, initializing other SDKs, or **drawing the initial frame**).」
- 可多次调用；官方建议不要写 naive retry loop。
- 提供 `shouldRunUiThreadStartUpTasks(false)`：先只跑后台任务，之后再以 `true` 调一次补完 UI 线程部分。

对本项目：WebView 不在启动关键路径上（首屏只需要 splash，WebView 要等服务就绪 ≈2.3s 才 `loadUrl`），所以可以「早调用 + 等回调再创建」，正好与 #320 的「首帧后创建」衔接。

### 2.3 失败降级

- `onError(WebViewStartupException)`：不得让应用起不来。降级路径就是现有同步创建 `new WebView(context)`，并把异常写入可见日志（沿用本仓「失败可见」不变量）。
- 若 `startUpWebView` 失败但随后创建 WebView 仍会触发隐式同步初始化：用户看到的是「慢」，不是「坏」；不得因此重试循环。
- 审计能力：`WebViewStartUpResult.getUiThreadBlockingStartUpLocations()` 可定位「谁在首帧前碰了 WebView API」。

---

## 3. 构建链约束（逐条核实）

### 3.1 compileSdk / AGP / Gradle

| 事实 | 来源 |
|---|---|
| `compileSdk 36` 官方要求 **最低 AGP 8.9.1** | <https://developer.android.com/build/releases/gradle-plugin>「Minimum versions of tools for Android API level」 |
| AGP 8.9 自述「maximum API level … is API level 35」，最低 Gradle 8.11.1、JDK 17 | <https://developer.android.com/build/releases/past-releases/agp-8-9-0-release-notes> |
| AGP 8.13 支持 API 36，最低 Gradle 8.13、JDK 17 | 同上总表「AGP 8.13 / Gradle 8.13」「maximum API level … 36」 |
| **webkit 1.16.0 只要求 `minCompileSdk=33` / `minAGP=7.2.0` / `minSdk=24`** | 下载 `webkit-1.16.0.aar` 读 `aar-metadata.properties` 与 `AndroidManifest.xml`（本地实证） |

**推论**：本项目 compileSdk 34 / AGP 8.4.2 / Gradle 8.6 / JDK 17 已经满足 webkit 1.16.0 的全部硬性要求。
「compileSdk 34→36 + AGP→8.9+ + Gradle→8.11+」只在**另有原因**要上 API 36 时才需要，不是本路线的前置条件。

### 3.2 minSdk

- 库侧 minSdk 24（AAR manifest 实证）；本项目 minSdk 24 → **不受影响，但也没有余量**。若将来把 minSdk 降到 23，会与 webkit 1.16.0 冲突。

### 3.3 Chaquopy（仅在同时升 AGP 时才成为硬约束）

官方版本表 <https://chaquo.com/chaquopy/doc/current/versions.html>：

| Chaquopy | Python | 支持的 AGP | 最低 API |
|---|---|---|---|
| 17.2 | 3.10–3.15 | 7.3–9.5 | 24 |
| 16.1 | 3.8–3.13 | 7.0–8.13 | 24 |
| 16.0 | 3.8–3.13 | 7.0–8.8 | 24 |
| **15.0.1（本项目现值）** | 3.8–3.12 | **7.0–8.5** | 21 |

- 本项目 Chaquopy 15.0.1 + AGP 8.4.2 在官方支持范围内（8.4 ≤ 8.5）。
- **若**将来升到 AGP ≥8.9，15.0.1 即超出支持上限，必须升 Chaquopy：至少 16.0（≤AGP 8.8）不够，需 **16.1（≤AGP 8.13）**；16.1 的 minSdk 24 与本项目一致，Python 3.10 仍在支持列表内。
- Chaquopy 16.x 对插件 API / 打包流程的具体变更**本轮未核实**（未查到官方迁移说明的源码级依据）→ 标记**未证实**，留到真要做 AGP 升级时单独立项验证。

### 3.4 新增的传递依赖（本路线唯一的「引运行时依赖」风险）

`webkit-1.16.0.pom` 声明的 compile 依赖：

```
org.jetbrains.kotlin:kotlin-stdlib:2.1.20
org.jspecify:jspecify:1.0.0
androidx.core:core:1.1.0
androidx.annotation:annotation:1.8.1
androidx.annotation:annotation-experimental:1.3.0
```

- 现用 1.10.0 的依赖集明显更小；1.16.0 是 Kotlin 实现，会引入 `kotlin-stdlib`。
- 影响面：方法数 / APK 体积（release 由 R8 裁剪未使用的 stdlib 部分）、首次加载的类校验成本。**具体增量未实测 → 未证实**，需在升级 PR 里量 APK 体积与 TTFD 两侧数据。
- 本项目是纯 Java 源（无 Kotlin 编译），不存在 Kotlin 编译器版本冲突；`kotlin-stdlib` 只作运行时库。

---

## 4. 未证实 / 待验证清单（不得当作结论）

1. 本项目在 AGP 8.4.2 + compileSdk 34 下实际解析并链接 webkit 1.16.0 的构建结果——**未实测**（本轮按要求只调研，不升级、不动构建脚本）。
2. `kotlin-stdlib` 2.1.20 引入后的 APK 体积与 dex 方法数增量——**未实测**。
3. `startUpWebView` 在本项目「服务就绪 ≈2.3s 才 loadUrl」的时序下能否把 Chromium 初始化压到就绪之前——**机制推断，未实测**。
4. Chaquopy 16.1 与 AGP 8.13 / Gradle 8.13 的实际构建兼容性——**官方版本表声明支持，但本项目未验证**。

---

## 5. 对方案的影响

- 升级成本从「构建链大手术」下调为「一行依赖 + 一次回归」：`androidx.webkit:webkit:1.10.0 → 1.16.0`。
- 因此本路线可以先做**最小验证**：只升依赖、只接 `startUpWebView`，用 TTFD 判定是否值得继续；不值得就回滚一行依赖即可。
- 真正需要谨慎的是**行为回归**（下载监听、深链、TTS 桥、渲染进程崩溃处理）和**降级路径**（`onError` → 同步创建），不是构建工具版本。
