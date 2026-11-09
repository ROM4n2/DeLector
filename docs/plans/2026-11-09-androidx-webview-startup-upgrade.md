# AndroidX `startUpWebView` 落地与 TTFD 验收 Implementation Plan

> **Goal**: 用 `androidx.webkit` 1.16.0 的 `WebViewCompat.startUpWebView` 把 Chromium 初始化提前到后台线程，取消 #320 暴露的「首帧后创建 WebView」的 +738ms TTFD 代价（3966 → 4704 ms），并让「延后创建」成立。
> **Tech Stack**: Android(Java, AGP 8.4.2 / Gradle 8.6 / compileSdk 34 / minSdk 24) + Chaquopy 15.0.1 + `androidx.webkit` 1.10.0→1.16.0；pytest 静态守卫；x86_64 模拟器实测。
> **Spec Reference**: `docs/research/2026-11-09-androidx-webview-startup-research.md`（版本约束与 AAR 元数据实证）；TTFD 口径见 `docs/agents/architecture.md`「启动指标 TTFD」。
> **Global Constraints**:
> - 不变量不变：端口文件唯一真相（`files/server-port.txt` + `DELECTOR_PORT_FILE`）、marker 校验（`versionCode:assetFingerprint`）、失败可见、红线 1 降级语义、冷启动不得空白页。
> - 不碰 `delector/` 业务语义；不新增打包步骤、不改 ABI。
> - **收益只认 TTFD**（首条 `.article-row` 可见）；`am start -W` / `Displayed` 只作旁证，不得作为「改善」依据。
> - 所有数字标明「x86_64 模拟器」，不可外推真机。
> - 每步一个 PR，不自动合并；验收为同会话 A/B 交替重装 3–7 次取中位数与范围。
> - 本计划 PR 只含文档，不改 `build.gradle`。

---

## [NOTE] 基线（x86_64 模拟器，medium_phone API 37 / WebView 145）

| 构建 | TTFD 中位数 | 范围 | 来源 |
|---|---|---|---|
| master 含 #317（当前） | 3966 ms | 3857–4932（7 次） | #320 验收 |
| #320（WebView 首帧后创建） | 4704 ms | 4133–4894（7 次） | #320 验收 |
| 正常启动（#319 前基线，另一轮） | 4891 ms | 4808–5008（5 次） | `architecture.md` TTFD 章节 |

`Displayed` 参考值：824 ms（master）。它只证明壳上屏时刻，不证明用户看到内容。

**判定基准**：升级目标不是「比 4704 好」，而是「不劣于 3966（当前 master）」——否则用户侧没有收益，只赚了实现复杂度。

---

## 任务拆分

### Task 1（独立 PR，先做）：依赖升级 + 静态守卫

- [ ] `android/app/build.gradle`：`androidx.webkit:webkit:1.10.0 → 1.16.0`（**只此一行**，不动 compileSdk / AGP / Gradle / Chaquopy）。
- [ ] 构建验证：`assembleEmulatorDebug` 通过；`checkAarMetadata` 无 minCompileSdk 冲突（预期 `minCompileSdk=33` ≤ 34）。
- [ ] 量增量：APK 体积、`classes*.dex` 方法数（R8 前后），记入 PR；不得靠估计。
- [ ] 新增 pytest 静态守卫 `tests/test_android_webkit_dependency.py`：断言版本为 1.16.0、断言 compileSdk 仍为 34（防止顺手改构建链）、断言未新增 Chaquopy 之外的运行时依赖坐标。
- [ ] 回归清单（人工，模拟器）：本地服务就绪、列表加载、外链下载监听、TTS 桥、渲染进程崩溃（`chrome://crash` 或 `onRenderProcessGone` 注入）、冷启动无空白页。
- [ ] 该 PR **不接** `startUpWebView`，只升依赖。验收指标：TTFD 不劣于基线（预计无变化），证明「升依赖本身无损」。

> 为什么先拆这一步：把「依赖带来的风险」与「初始化时机带来的风险」分开记账。任一 PR 出问题都能单独回滚。

### Task 2（独立 PR，依赖 Task 1 合并）：接入 `startUpWebView`

- [ ] 在 `Application.onCreate`（若当前无自定义 Application，则在 `MainActivity.onCreate` 最前、**splash inflate 之前**）调用：
  - `WebViewStartUpConfig.Builder(单线程 Executor).shouldRunUiThreadStartUpTasks(false).build()`
  - `WebViewCompat.startUpWebView(...)`，`onResult` 置 `webViewStartupDone=true`，`onError` 记可见日志并置 `webViewStartupFailed=true`。
- [ ] `ensureWebView()`（#320 已引入）先从 `startUpWebView` 回调 / 就绪回调二选一触发；**保留 `OnDrawListener` 的首帧门控**，即：首帧已提交 **且** 后台初始化已完成（或失败降级）才创建 WebView。
- [ ] 失败降级：`onError` 后直接同步 `new WebView(context)`，不重试、不吞异常；错误文本仍可见。
- [ ] 在 `onResult` 里读 `getUiThreadBlockingStartUpLocations()`，若非空则 `Log.w` 打出栈——用于发现「谁在首帧前碰了 WebView」。
- [ ] pytest 守卫 `tests/test_android_webview_startup_async.py`：断言 `startUpWebView` 调用点早于 splash inflate、断言 `shouldRunUiThreadStartUpTasks(false)`、断言 `onError` 分支会记录并降级、断言创建仍受首帧门控、断言未引入 retry 循环。
- [ ] 实测：同会话 A/B（master vs Task 2 构建）各 7 次，报 TTFD 中位数与范围 + `Displayed` 旁证。

### Task 3（仅在 Task 2 未达标时考虑，可选）：UI 线程分片

- [ ] `shouldRunUiThreadStartUpTasks(true)` 二次调用，安排在 splash 首帧之后、`loadUrl` 之前，观察是否比一次性 UI 分片更平滑。
- [ ] 若 Task 2 已达标，本任务不做（YAGNI）。

---

## 验收与判定

| 场景 | 通过条件 |
|---|---|
| Task 1 | TTFD 中位数与基线差 ≤ 噪声带（当前观测噪声约 ±4–5%，即 3966 ± 200ms）；回归清单全过 |
| Task 2 | TTFD 中位数 **≤ 3966ms**，且范围上界不高于基线范围上界 + 噪声；冷启动 0 纯白帧（沿用 #319 的逐帧法） |
| 放弃条件 | Task 2 连续两轮（各 7 次）TTFD 中位数仍 > 4166ms（基线 +5%），或出现任何行为回归 → **放弃该路线**，回滚 Task 2（并视情况回滚 Task 1），在报告中写明「AndroidX 异步启动在本项目无效」，不继续加码 |

**绝不接受**「`Displayed` 变好但 TTFD 不变差」当作通过——这正是 #320 被判为遮盖型的原因。

---

## 迁移风险矩阵

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| webkit 1.16.0 引入 `kotlin-stdlib` 2.1.20，APK 变大 / 方法数上升 | 高 | 低–中 | Task 1 实测 dex/体积；release 依赖 R8 裁剪；超预算则放弃或加 proguard 规则 |
| 1.10→1.16 行为变化（下载监听、深链、深色模式、`WebSettingsCompat`） | 中 | 中 | Task 1 回归清单；逐项手测 + 静态守卫；不合并未过清单的版本 |
| `startUpWebView` 与 Chaquopy 启动争 CPU，TTFD 不升反降 | 中 | 高 | 严格按「放弃条件」执行，两轮不过即回滚；不做无限调参 |
| 第三方/系统组件在首帧前隐式触发 WebView 初始化，收益归零 | 低–中 | 中 | `getUiThreadBlockingStartUpLocations()` 审计；若发现调用点，先修调用方再评估 |
| `onError` 降级路径被吞，用户无感但慢 | 中 | 中 | 守卫测试断言「错误必记录 + 必降级到同步创建」；日志进 logcat 的 `[DeLector]` 通道 |
| 升级触发 AGP/compileSdk 连锁（若有人顺手升） | 低 | 高 | Task 1 守卫断言 compileSdk 仍为 34、无 AGP/Gradle 变更；真要升另立 ADR（涉及 Chaquopy 16.1） |
| 真机表现与模拟器不同 | 确定 | 中 | 报告标注「x86_64 模拟器」，不外推；若上真机需另做一轮同口径测量 |

---

## 回滚点

| 回滚点 | 触发条件 | 操作 | 影响面 |
|---|---|---|---|
| R1：回滚 `startUpWebView` 接入 | Task 2 未达标或行为回归 | revert Task 2 的 PR；`ensureWebView` 回到 #320 的首帧门控（TTFD 4704）或进一步回滚 #320 | 仅 Android 壳，Python 无关 |
| R2：回滚依赖版本 | 体积/dex 超预算，或行为回归定位到 webkit | `webkit` 回到 1.10.0（一行） | 极小 |
| R3：整体放弃路线 | R1 + R2 后仍无收益 | 关闭 #320（其前提消失），保持 master 现状（#319 已解决白屏根因） | 无用户可见变化 |
| 数据回退 | 任何回滚后 | 重跑同会话 A/B，确认 TTFD 回到 3966 档位 | 记账闭合 |

**回滚不需要动 Chaquopy**：本路线不要求升级 AGP；只有未来另有原因升 AGP ≥8.9 时才需要 Chaquopy 16.1（见调研 §3.3）。

---

## 与 #320、#319 的关系

- #319（splash 撤场时机）已合并，白屏根因已修，**与本计划正交**，不因本计划回滚。
- #320（WebView 首帧后创建）保持 draft：它是本计划的**代码前置**，只有在 Task 2 达标后才可能转 ready；Task 2 放弃则一并关闭。
- #313（启动壳）已按「被 #319 取代」关闭，本计划不再依赖它。
