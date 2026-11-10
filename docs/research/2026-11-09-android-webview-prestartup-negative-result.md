# androidx.webkit `startUpWebView` 预初始化 Chromium：负结果存档

> **结论先行**：把 Chromium 初始化提前到后台线程（`androidx.webkit` 1.16.0 的
> `WebViewCompat.startUpWebView`）**没有改善 TTFD**。两轮各 7 次实测的中位数
> 4067ms / 4005ms，对比同会话基线 4095ms / 3938ms，属持平到轻微回退（+0.4%～+1.7%），
> 未达计划中的通过线 3966ms。因此该路线**不合并**，实现只作为证据留在
> `archive/negative-webview-prestartup` 分支，不进入生产代码。
>
> 所有数字均为 **x86_64 模拟器**（Medium_Phone_API_37.0 / WebView 145.0.7632.218），
> 不可外推真机。

---

## 1. 假设与来源

2026-11-09 的立项文档 [androidx-webview-startup-upgrade 计划](../plans/2026-11-09-androidx-webview-startup-upgrade.md)
与 [专项调研](2026-11-09-androidx-webview-startup-research.md) 提出：

- #320 把 `new WebView` 从 `onCreate` 前段挪到 splash 首帧之后，TTFD 从 3966ms 回退到
  4704ms（+19%，x86_64 模拟器）。归因是 Chromium 初始化被推迟到「Python 启动已经在抢
  CPU」的窗口里，同步创建成本反而更高。
- 推断：若用 `startUpWebView` 把 Chromium 初始化提前放到后台线程、早于 Python 就绪，
  那么这笔初始化成本就能与 Python 启动重叠，抵消 #320 暴露的 +738ms；
  若同时保留「首帧后创建」，则既不阻塞首帧、也不再付同步初始化成本。

这是一个**机制推断**，不是测量结论。本实验就是为了证伪它。

## 2. 实验设置

| 项 | 值 |
| --- | --- |
| 设备 | x86_64 模拟器 Medium_Phone_API_37.0（1080×2400） |
| WebView | 145.0.7632.218 |
| 基线构建 | `a6a93d7`（#319 已入，WebView 仍在 `onCreate` 前段创建） |
| 实验构建 | 基线 + `webkit 1.10.0→1.16.0` + `startUpWebView` + 首帧门控（commit `8fe7e08`） |
| 冷启动口径 | 每次 `am force-stop` → `pm clear`（清应用数据，含 WebView/SW 缓存）→ `am start -W` |
| 样本 | 每轮每个构建 7 次；共 2 轮；A/B 交替重装 |
| 预热 | 第 2 轮每个构建先弃跑 1 次（首启 dexopt 不计入样本） |
| 动画 | 三个 animation scale 置 0 |
| 指标 | TTFD = 首条 `.article-row` 完成首次绘制（应用内 `TTFD_FIRST_ARTICLE_MS`） |

`Displayed` / `am start -W` 的 `TotalTime` 只作旁证，不参与判定。

## 3. TTFD 实测

| 轮次 | 基线中位数（范围） | Task 2 中位数（范围） | 差值 |
| --- | --- | --- | --- |
| 第 1 轮 | **4095ms**（3957–4183） | **4067ms**（3939–5079） | −28ms（−0.7%） |
| 第 2 轮 | **3938ms**（3884–4250） | **4005ms**（3949–4857） | +67ms（+1.7%） |

- 第 1 轮基线的首次启动为 9926ms（模拟器冷启 dexopt），已从范围中剔除；完整范围
  3957–9926ms。
- 两轮基线合并中位数 ≈4016ms，与立项时「预期基线 ~4020ms」一致，说明测量环境未漂移。
- 通过线 **3966ms** 的来源：立项时同口径基线中位数（#320 会话），即「不劣于 #319 后
  的现状」；放弃线 **4166ms** = 基线 +5%，容忍噪声上限。
- 结论：Task 2 两轮中位数均 **高于** 通过线（未达标），但都在放弃线以内——不是灾难性
  回归，而是**没有收益**。

## 4. 代价

| 项 | 基线 | Task 2 | 增量 |
| --- | --- | --- | --- |
| APK | 96,829,120 B | 96,911,296 B | +82,176 B（+0.08%） |
| `classes*.dex` 合计 | 10,107,960 B | 10,300,884 B | +192,924 B（+1.9%） |
| dex 方法数 | 59,235 | 60,527 | +1,292（+2.18%） |

`checkAarMetadata` 通过（AAR 元数据 `minCompileSdk=33` / `minAGP=7.2.0` / `minSdk=24`），
即：**只升依赖这一行是可行的**，不需要连带升 compileSdk / AGP / Gradle / Chaquopy。
但「可行」不等于「值得」——付出上述体积与方法数增量，换来 0 收益。

## 5. 为什么假设错

三个机制叠加，使「并行」没有变成「更快」：

1. **TTFD 的下界已经不在 WebView 上。** #319 把 splash 撤场改成 `onPageCommitVisible`
   + `postOnAnimation` 后，首帧不再等 WebView，`Displayed` 从 ~800ms 降到 ~600ms；
   此时 TTFD 由「本地服务就绪 + 首屏数据渲染」决定。Chromium 初始化只是与这段串行链
   争 CPU，而不是串行链本身。
2. **CPU 是共享的，不是免费的并行。** 模拟器只有少量 vCPU。Chromium 初始化从 UI 线程
   挪到后台线程，并没有消失：它改为与 Python 的 `fastapi` / `delector.core.database` /
   `import spacy`（合计约 1.2s）争同一份 CPU。后台线程的收益被 Python 启动的拖慢抵消。
3. **初始化可后台化的部分有限。** `setShouldRunUiThreadStartUpTasks(false)` 只提前
   WebView 提供方/网络栈中**允许后台执行**的任务；首次 `new WebView` 仍要在 UI 线程
   跑完剩余启动任务。实测 `getTotalTimeInUiThreadMillis()` 在该 provider 上返回 null，
   也无「首帧前 UI 线程启动任务」告警——说明后台部分确实跑了，但剩下的部分本来也不大。

## 6. #320 被吸收：正面证据（也是这条路线唯一的确定收益）

在同一 Task 2 构建里保留「首帧后创建」，TTFD ≈4005ms；对照 #320 当时的 4704ms，
**+738ms 的回退消失了**。机制：后台预初始化把 Chromium 的活提前做完，首帧后再
`new WebView` 几乎没有同步成本。

但这个证据的含义是**否定**，不是肯定：

- 「挪创建位置」这条路本身没有用户价值。它在没有 `startUpWebView` 时**有害**（#320，
  +738ms），在有 `startUpWebView` 时**无害但也无益**（本实验，≈基线）。
- 因此不要把它理解为「等条件成熟再做」。#320 不应以「等 androidx」为理由挂起，
  它就是不需要。

## 7. 代码证据

- 归档：annotated tag `archive/negative-webview-prestartup` → `8fe7e08`（2026-11-10 打 tag 后删除原分支；远程副本已在远程分支清理中删除，本地 tag 是唯一副本，**不开 PR 合并**）
- Commit：`8fe7e08`（5 个文件：`android/app/build.gradle`、
  `MainActivity.java`、`tests/test_android_webkit_dependency.py`、
  `tests/test_android_webview_startup_async.py`、`tools/ci_shards.py`）
- 该分支的形态：`startUpWebView` 在 splash inflate 前调用；`onError` / `catch (Throwable)`
  都降级为同步创建并写 `Log.w`；WebView 创建仍受「首帧 &&（后台完成 || 失败）」双门；
  #319 的撤场逻辑未改。静态守卫 21 passed。

## 8. 复现要点

1. 构建基线（master）与实验分支的 emulatorDebug APK，先运行
   `python tools/sync_android_sources.py` 保证两包资产指纹一致。
2. 启动 x86_64 模拟器，关闭三个动画 scale，`input keyevent KEYCODE_WAKEUP` 并解除锁屏。
3. 每个构建先弃跑 1 次预热；随后每轮 7 次：`force-stop` → `pm clear` → `am start -W`
   → 轮询 `logcat -s DeLector:I` 取 `TTFD_FIRST_ARTICLE_MS`。
4. 交替安装两个构建；报告每轮中位数与范围，只认 TTFD。

## 9. 边界与未证实项

- 只测了 x86_64 模拟器；真机（尤其低核数设备）上的 CPU 竞争结构不同，结论不可外推。
- 未测 arm64 变体，也未测不同 WebView 版本。
- 「后台线程被 Python 抢 CPU」是机制解释，未单独做 CPU profile 归因（没有逐线程
  采样证据）。
- `getTotalTimeInUiThreadMillis()` 在该 provider 返回 null，UI 线程启动成本的绝对值未知。
