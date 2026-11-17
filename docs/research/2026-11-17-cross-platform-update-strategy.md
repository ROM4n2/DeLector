# DeLector 全平台更新机制核查与升级方案

> 性质：只读调研 + 方案设计。**未改代码、未提交**。
> 日期：2026-11-17 ｜ 当前版本：`5.23.5`（`delector/core/version.py:15`）
> 证据口径：仓内文件与行号；平台行为（Android/Windows/macOS/Linux）标注为平台事实，不冒充仓内实证。

---

## 0. 结论摘要

| 平台 / 形态 | 现状 | 自动更新真实上限 | 建议 |
| --- | --- | --- | --- |
| Windows 安装版（Setup.exe） | 免管理员 per-user 安装，未签名 | **可接近全自动**：下载 → 校验 → 退出应用 → 静默安装 → 重启；无 UAC，SmartScreen 可能多一步 | **优先做**。CI 已实证 `/VERYSILENT` 可装 |
| Windows 便携版（zip） | 解压即用，`DeLector.exe` + `_internal` | **可全自动**，但运行中的 exe/DLL 不能被自身覆盖，必须靠临时目录里的 helper 等进程退出后换目录 | 第二优先，复杂点在目录交换与回滚 |
| Linux 便携版（tar.gz） | 解压后跑裸二进制 | **可全自动**：版本目录 + 符号链接切换；运行中文件可替换，重启生效 | 成本最低，但需先建立受管安装布局 |
| macOS（tar.gz 裸二进制） | 非 `.app`、未签名、未公证 | 技术上可换目录重启，但 Gatekeeper/公证缺失使“正规自动更新”不成立 | **暂缓**，先维持跳转 Release 页；要做得先改 `.app` + Developer ID + 公证 |
| Android（APK） | GitHub 直发 APK，pinned keystore 签名 | **不可能静默**：至少 2–3 步用户确认（未知来源 + 系统安装确认，部分 OEM 再加一步） | 做“自动下载 + 校验 + 一键拉起安装”，不做静默 |
| Docker / 源码运行 | `docker compose up --build` / `python start.py` | 不适用（重建或 git pull 即更新） | 不纳入应用内更新 |

**一句话结论**：桌面三平台（Windows/Linux，macOS 需先补签名）可以把“下载、校验、替换、重启”做成应用内自动化；Android 只能把“找包、搬包、验包”自动化，**最后一步系统确认永远省不掉**。Android 的三条路径里，Play In-App Updates 因未上架 Play 不可用，静默安装对第三方应用在平台层面不成立，只剩“自建下载 + `PackageInstaller`”。

**治理前提**：ADR-0017 已显式否决应用内下载与安装（`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:79-83,188-196`），并写明升级到 Option B 必须另开 ADR（同文件 `:164-165`）。本方案落地前需先有新的 ADR，不得悄悄增量。

---

## 1. 现状：一套检查，多种分发

### 1.1 检测链路（全平台共用）

| 问题 | 事实 | 证据 |
| --- | --- | --- |
| 查什么源 | GitHub `repos/ROM4n2/DeLector/releases/latest`，匿名请求 | `delector/routes/update.py:34` |
| 比对哪些字段 | 只取 `tag_name` 与 `html_url`；tag 去 `v` 后按 versionCode 语义与 `APP_VERSION` 比较。**完全不读 `assets`** | `delector/routes/update.py:82-111,114-136` |
| 多久检测一次 | 服务端 TTL：成功 6h、失败 60s；出网超时 3s | `delector/routes/update.py:37,41-42` |
| 什么时机触发 | 前端页面加载后延迟 3s 自动查一次（一次性 `setTimeout`，不轮询）；用户点顶栏 `System · vX.Y.Z` 手动再查 | `static/js/update.js:22,129-135`；`static/index.html:34-45` |
| 失败语义 | `has_update: null` 且 `error_reason` 非空，绝不伪装成“已是最新” | `delector/routes/update.py:139-149`；`tests/test_update_check_endpoint.py:326` 起 |
| 响应契约 | **恰好 7 个键**，测试逐字冻结 | `tests/test_update_check_endpoint.py:29-37,221-230` |
| 桌面托盘入口 | “检查更新”直接打开 Releases 页，不查接口 | `desktop.py:103-104` |

要点：

1. **当前只能“知道落后”，不能“取回安装包”**。端点没有返回 APK/zip/tar.gz 的地址、大小或哈希，`page_url` 是 Release 页而非资产直链（`delector/routes/update.py:126-136`；ADR 同款设计见 `docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:112`）。
2. **7 键契约是冻结的**。要暴露资产元数据，应新增独立端点（如 `GET /api/update/artifact`），不要往 `/api/update/check` 里塞第 8 个键，否则 `tests/test_update_check_endpoint.py:221-230` 必红，前端 `static/js/update.js:4-5` 与探针也要同步改。
3. **缓存是服务端全局缓存**，不区分平台；新增资产端点应沿用同样的 TTL 与错误分类，避免每个启动都打 GitHub（未鉴权 60 次/小时，见 `delector/routes/update.py:44-48`）。

### 1.2 各平台分发形态与 Release 产物

| 平台 | 产物 | 形态 | 体积（Release 实测） | 签名 / 公证 | 数据落点 |
| --- | --- | --- | --- | --- | --- |
| Windows x64 | `DeLector-<tag>-Windows-x64-Portable.zip` | PyInstaller `--onedir --windowed`，解压出 `DeLector.exe` + 依赖目录 | 85.8 MB（v5.17.0） | **未做代码签名** | `%LOCALAPPDATA%\DeLector` |
| Windows x64 | `DeLector-<tag>-Windows-x64-Setup.exe` | Inno Setup 6，per-user 装到 `%LOCALAPPDATA%\Programs\DeLector`，带卸载器 | 约 95–120 MB（LZMA2 压缩后，见 `.iss:47` 注释） | **未做代码签名** | 同上，卸载不删数据 |
| macOS | `DeLector-<tag>-macOS.tar.gz` | PyInstaller `--onedir`，裸可执行文件 `./DeLector`，**不是 `.app`** | 58.1 MB（v5.17.0） | **未签名、未公证** | 用户数据目录（ADR-0019 外置） |
| Linux x64 | `DeLector-<tag>-Linux-x64.tar.gz` | PyInstaller `--onedir`，裸可执行文件 `./DeLector` | 118.5 MB（v5.17.0） | 无签名 | 用户数据目录 |
| Android | `DeLector-<tag>-Android.apk` | 直发 APK，arm64-v8a，Chaquopy 内嵌 Python + spaCy | 58.9 MB（v5.17.0）；本地 device debug 构建 66,562,997 B | pinned keystore 签名；CI 校验证书指纹 | 应用私有目录 |
| Docker | 本地 `docker compose up --build` | 源码构建镜像，未发布镜像 | 未记录 | 不适用 | `./data` 挂载 |

证据：

- 产物上传列表：`.github/workflows/build-release.yml:705-709`。
- Windows 便携版构建参数：`package_windows.py:316-323`；产物目录与构建指纹：`package_windows.py:418-436`。
- 安装器 per-user / `PrivilegesRequired=lowest` / `CloseApplications=yes` / 未签名：`installer/DeLector.iss:8-16,39-44,53-54`。
- 安装器静默安装并真启验包：`.github/workflows/build-release.yml:177-188`。
- macOS/Linux 的“裸二进制、未签名/未公证、需 `xattr -d com.apple.quarantine`”：`README.md:76-77`；发布正文同款说明：`build-release.yml:727-728`。
- Android 只出 arm64：`android/app/build.gradle:145-151`；三 ABI 体积 106.3 MB 的对比：`docs/agents/architecture.md:81`。
- 体积四平台实测：`FEATURES.md:167`。
- 签名配置：`android/app/build.gradle:47-66`（pinned keystore、显式开 v1）；CI 指纹闸：`build-release.yml:547-582`，期望值 `:555`。
- Docker 入口与构建：`Dockerfile:1-18`；使用方式：`README.md:51`。

### 1.3 版本号与 versionCode 递增

- 单一真相源：`delector/core/version.py:15` 的 `APP_VERSION = "5.23.5"`。
- 编码规则：`major*10000 + minor*100 + patch`，由 `version_code()` 唯一定义（`delector/core/version.py:22-41`），`build.gradle` 只保留 fallback（`android/app/build.gradle:8-9,72-77`）。
- 发版时 CI 从 git tag `vX.Y.Z` 推导 `versionName/versionCode` 并以环境变量注入（`build-release.yml:474-500`）。
- 守卫：`tests/test_writer_mobile.py:71-134` 钉住 `sw.js`、`index.html`、`build.gradle`、`README` 与 `APP_VERSION` 一致；`versionCode` 不得回拨，降级会被系统拒绝（`CHANGELOG.md:55`）。
- 真机覆盖安装已实证：v5.23.4 → v5.23.5（Redmi Note 8 / Android 11，`CHANGELOG.md:44`）。

---

## 2. 各平台“自动更新”的真实上限

> 核心区别：**桌面平台，应用对自己的安装目录有写权限，可以自己完成替换；Android 的安装动作由系统包管理器独占，应用只能“请求安装”。**

### 2.1 Windows

**当前形态**

- 便携版：解压目录，双击 `DeLector.exe`；`--onedir` 意味着 exe 启动时会加载同目录 `_internal` 下的 DLL/Python 运行时（`package_windows.py:316-323`）。
- 安装版：Inno Setup per-user 安装，`CloseApplications=yes`、`RestartApplications=no`，静默参数已在 CI 验证（`installer/DeLector.iss:53-54`；`build-release.yml:177-188`）。

**硬约束**

1. **运行中的 `DeLector.exe` 与已加载 DLL 被 Windows 文件锁占用**，不能原地覆盖、删除或改名。应用不能“自己替换自己”，必须二选一：
   - 让安装器代劳：Inno 的 `CloseApplications=yes` 可通过 Restart Manager 关闭应用后再替换（`installer/DeLector.iss:53`）；
   - 或者由应用主动退出，再让 `%TEMP%` 里的 helper 等进程完全退出后换目录。
2. **便携版没有安装器**，只能走 helper 换目录；helper 不能放在被打包替换的目录里（否则自己也被锁/被删），必须放 `%TEMP%`。
3. **安装版与便携版是两条升级路径**：安装版用户应下载 `Setup.exe`；便携版用户应下载 `Portable.zip`。若给便携版用户跑 Setup，会变成“另装一份”，产生两个副本。需要判定安装形态（Inno 默认卸载注册项 `{AppId}_is1`，或安装目录标记）。
4. **未做 Authenticode 签名**（`installer/DeLector.iss:16`）。用户从浏览器下载时 SmartScreen 会提示“未知发布者”；应用内用 HTTP 客户端下载的文件通常不带 Mark-of-the-Web，程序化启动时未必触发 SmartScreen，但**不能把“不触发”当作保证**。
5. 单实例/版本冲突：旧版仍在运行时启动新版会报“版本冲突，请先退出旧版本”（`desktop.py:993-998`），因此更新流程必须先让旧进程退出，再启动新进程。

**能到什么程度**

- 安装版：用户点一次“更新” → 应用下载 `Setup.exe` → 校验 → 退出 → helper 静默安装（无 UAC，`PrivilegesRequired=lowest`，`.iss:43`）→ 自动重启。**确认步数 1**（SmartScreen 视下载来源可能 +1）。
- 便携版：用户点一次“更新” → 下载 zip → 校验 → 退出 → helper 解压到临时目录 → 旧目录改名备份 → 新目录改名到位 → 重启 → 清理备份。**确认步数 1**。
- 理论上可以做到 0 步（自动检查 + 自动下载 + 自动重启），但建议保留一次显式确认：更新会中断当前学习会话。

### 2.2 macOS

**当前形态**

- `tar.gz` 里是 PyInstaller `--onedir` 的裸 Mach-O 可执行文件与依赖目录，**不是 `.app` bundle**（`README.md:76`；`build-release.yml:402-404`）。
- 未做代码签名与公证；README 让用户右键“打开”或 `xattr -d com.apple.quarantine`（`README.md:76`；`build-release.yml:727`）。

**硬约束**

1. **Sparkle 等标准自动更新框架不适用**：它们要求 `.app` bundle、`Info.plist`、代码签名与 appcast/EdDSA 签名。当前分发形态不具备这些前提。
2. **POSIX 允许替换运行中的可执行文件**（unlink/rename 后旧进程继续持有旧 inode），所以“换目录 + 重启”技术上可行；但不能在运行中原地写同一个文件。
3. **Gatekeeper / quarantine**：用户从浏览器下载会带 quarantine 属性；应用自己用 Python 下载通常不会设置该属性，因此替换后的新二进制未必被 Gatekeeper 拦截。但这是“实现细节上的侥幸”，不是可承诺的安全模型。
4. **未公证**是根本问题：即便自建更新成功，新版本仍是未签名/未公证的裸二进制，用户换机或首次运行仍会遇到 Gatekeeper。
5. 当前也没有 `.app`，没有 `Contents/MacOS` 布局，无法使用 macOS 的原地升级惯例。

**能到什么程度**

- 现状：只能“检查 + 打开 Release 页”，与 Android 现状同级。
- 若接受“裸二进制 + 临时目录 helper 换目录 + 重启”，可做到 1 步确认；但这是自定义更新器，且不能解决 Gatekeeper/公证问题。
- **正规做法**：先改成分发 `.app`（含 `Info.plist`），补 Developer ID 签名与公证，再上 Sparkle 或自建 appcast。成本包括 Apple Developer 年费、CI 签名/公证步骤、首次改造打包布局。对当前“未验证的次要平台”不划算。

### 2.3 Linux

**当前形态**

- `tar.gz`，解压出 `DeLector-<tag>-Linux-x64/`，运行 `./DeLector`（`README.md:77`；`build-release.yml:294-296`）。
- 没有 `.deb`/`.rpm`/AppImage/Flatpak，也没有受管安装目录。

**硬约束**

1. **运行中的可执行文件可以被 rename/unlink**（与 Windows 不同），所以“下载新目录 → 切换 → 重启”很容易；但正在运行的进程仍用旧文件，必须重启才生效。
2. **没有受管安装布局**：用户可能解压到任意目录。要做自动更新，需要先定义一个稳定布局，例如 `~/.local/share/DeLector/versions/<version>/` + `~/.local/bin/DeLector` 符号链接（或启动器）。这会改变当前“解压即用”的分发语义。
3. **无签名体系**：没有系统级签名校验，防替换只能靠 HTTPS + 哈希（或自建 minisign）。
4. **发行版差异**：包在 Ubuntu runner 构建，README 明确“未在其他发行版验证”（`README.md:77`）。自动更新会把“能否在该发行版运行”的风险从“用户手动选择”变成“自动推给用户”。

**能到什么程度**

- 可做到接近 0–1 步确认的全自动更新：检查 → 下载 → 校验 → 解压到新版本目录 → 原子切换符号链接 → 提示重启/自动重启 → 失败回滚到上一版本目录。
- 代价是引入“版本目录 + 启动器/符号链接”的受管布局；不做布局改造就只能覆盖用户当前目录，风险更高。

### 2.4 Android

**当前形态**

- 直发 APK，`device` flavor 只出 arm64-v8a（`android/app/build.gradle:145-151`）；`emulator` flavor 带 `.emulator` 后缀与 x86_64，两者不能互相覆盖安装（`:154-162`）。
- 无 Play Core、无 FileProvider、无 `REQUEST_INSTALL_PACKAGES`、无 `PackageInstaller` 代码（`AndroidManifest.xml:4-32`；`android/app/build.gradle:187-190`）。
- WebView 的所有下载统一进入 `ExportSaver`，落 MediaStore 的 `Download/`（`MainActivity.java:343-344`；`ExportSaver.java:36-51`）。

**硬约束**

1. **安装动作由系统 `PackageInstaller` 独占**。普通应用只能发起安装请求，系统安装确认界面不可绕过。
2. **Android 8+ “未知来源”是按应用授权的**（`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`）；Android 7.x（minSdk 24 覆盖）是全局开关。首次需要用户去设置页授权，之后每次安装仍有系统确认。
3. **OEM 可能再加一步**：仓库自己的 `tools/install_apk.py:6` 记录了 MIUI 的 USB 安装确认页会让 `adb install` 报 `INSTALL_FAILED_USER_RESTRICTED`；应用内安装同样可能遇到厂商安装器的额外扫描/确认。
4. **签名必须一致**：覆盖安装要求新 APK 与已装应用签名相同，否则 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`；这是系统强制的，应用层校验只是提前给出可读原因。
5. **versionCode 必须严格递增**：降级会被拒绝（`CHANGELOG.md:55`）。
6. **进程可能在下载中被杀**：应用进程同时承载 Python 服务与 WebView，切后台后没有前台服务/DownloadManager 的保护。

**能到什么程度**

- 最少 2 步确认：首次“允许安装未知应用” + 每次“系统安装确认”；部分 OEM 3 步。
- 可自动化的部分：检查、下载（可断点/可取消）、哈希校验、包名/versionCode/签名预检、拉起系统安装、结果回读与失败文案。
- **静默安装不可能**，详见 §3.3。

### 2.5 Docker / 源码运行

- Docker：镜像从源码构建，未发布镜像；更新 = `git pull` + `docker compose up -d --build`（`Dockerfile:1-18`；`README.md:51`）。没有“应用内自更新”的语义，也不建议引入 Watchtower 这类自动重建。
- 源码运行：`python start.py` / `python desktop.py`，更新 = 拉代码 + 重启；前端 `static/` 刷新即生效，Python 改动需重启进程。不属于分发包更新。

---

## 3. Android 三条路径对照

### 3.1 路径 A：Play In-App Updates API

**结论：当前不可用。**

| 前提 | DeLector 现状 |
| --- | --- |
| 应用必须通过 Google Play 分发并由 Play 安装 | 只经 GitHub Releases 直发 APK（`build-release.yml:705-709`；`README.md:78`） |
| 必须引入 Play Core（`com.google.android.play:app-update`） | 依赖只有 `appcompat` 与 `material`（`android/app/build.gradle:187-190`） |
| 需要 Play App Signing / 正式 release 签名 | 当前发的是 pinned keystore 签名的 **debug** 变体（`build-release.yml:522-534`；`build.gradle:47-66`） |
| 需要 AAB、Play Console、政策与 targetSdk 合规、审核周期 | 均不存在；且审核节奏与当前“数天一版”冲突 |

即使未来上架 Play，In-App Updates 也只有两种形态：immediate（全屏阻塞）与 flexible（后台下载 + 用户确认重启），**都不是静默安装**，且只对“Play 安装的副本”有效。对侧载 APK 无效。

**代价**：引入 Play 分发是产品/合规级变更（开发者账号、AAB、Play App Signing、隐私政策、targetSdk 跟进、审核等待），远大于“更新体验”本身的收益。

### 3.2 路径 B：自建下载 + `PackageInstaller` / `ACTION_VIEW` + `REQUEST_INSTALL_PACKAGES`

**结论：可行，推荐；这是 Android 唯一现实的路径。**

两种拉起安装的实现：

| 方式 | 机制 | 优点 | 代价 |
| --- | --- | --- | --- |
| `PackageInstaller` Session | 应用创建 session，把 APK 字节写入 session，`commit()` 后系统弹安装确认 | 不需要 FileProvider、不暴露 `file://` URI、能拿到安装结果回调 | 要把 60MB 再写一遍（磁盘 I/O 翻倍）；需要处理 session 状态与广播接收 |
| `ACTION_VIEW` + FileProvider | 通过 `FileProvider` 暴露缓存里的 APK，发 `ACTION_VIEW` | 实现简单、代码少 | 需要新增 provider 与 `file_paths.xml`；安装结果只能靠下次启动比对版本；URI 授权面更大 |

**新增权限面**：`REQUEST_INSTALL_PACKAGES`（manifest）+ 用户授权“安装未知应用”。这是 ADR-0017 否决 Option B 的主要理由之一（`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:79-83`），重新开启需要新 ADR 明确接受。

**实现代价**：

1. 后端新增资产元数据端点（不能改 7 键契约）。
2. Java 侧新增下载器（断点、取消、进度、哈希）、校验策略（包名/versionCode/签名/ABI）、安装会话与结果接收。
3. 前端 chip 从“外链”升级为“状态机”（可更新/下载中/校验中/待安装/失败），并保留“打开 Release 页”兜底。
4. WebView ↔ Java 需要桥接。仓内已有 `@JavascriptInterface` 先例（`MainActivity.java:292-294`），可复用该模式；也可用自定义 scheme 在 `shouldOverrideUrlLoading` 拦截，避免扩大 JS 接口面。
5. 失败路径显著增多：见 §4.5 的失败矩阵。

### 3.3 路径 C：静默安装

**结论：普通第三方应用做不到，且不是取舍问题。**

具体原因（平台事实）：

1. **权限不可得**：静默安装依赖 `android.permission.INSTALL_PACKAGES`，其保护级别是 `signature|privileged`。普通 APK 即使在 manifest 里声明也拿不到；只有系统应用、特权应用（预置到 `/system/priv-app` 等）或持有平台签名的应用才有。
2. **调用者身份不够**：`adb install` / `pm install` 之所以能装，是因为 shell UID 持有该特权；普通应用没有等价的执行通道。
3. **`PackageInstaller` 对非特权调用者始终展示系统安装界面**。`commit()` 只是“提交安装请求”，不是“执行安装”。
4. **企业受管设备**的静默下发走 Managed Google Play / EMM，需要设备被企业纳管并由组织推送，不是应用自己能声明的能力；普通用户设备不适用。
5. **root 设备**可以 `su -c pm install`，但这要求用户已 root，不能作为产品路径。

**能达成的最优形态**：自动下载 + 自动校验 + 一键拉起系统安装 + 安装结果回读 + 失败可读提示。把“找包/搬包/验包”从用户手里拿走，但“系统确认”永远保留。

---

## 4. 推荐方案与最小可用版本

### 4.1 共用底座（Phase 0，所有平台受益，改动最小）

1. **新 ADR**：明确从 ADR-0017 Option A 升级到“应用内下载 + 平台各自安装”，并逐平台写清确认步数与失败回退。不得修改 ADR-0017 原文，只能新开或追加 Amendment（遵循仓内“历史 ADR 不回头改”的约束，见 `docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:164-165`）。
2. **CI 为每个 Release 资产生成 `.sha256`**：在 `build-release.yml` 的上传步骤前对 `dist/DeLector-*` 逐个 `sha256sum` 并作为 release asset 上传。这是所有平台校验和的最简来源。
   - 注意：`.sha256` 与 APK/zip 同属“仓库写入方可改”的信任域，只能防传输损坏，不能防仓库被攻陷；真正的防替换锚点是平台签名（Android）或未来的代码签名（Windows/macOS）。
3. **新增 `GET /api/update/artifact`**（独立端点，不复用 7 键契约）：
   - 入参：`platform`（`windows` / `macos` / `linux` / `android`）、可选 `install_kind`（`setup` / `portable`）。
   - 出参：`current`、`latest`、`has_update`（三态）、`version_code`、`artifact_url`、`size_bytes`、`sha256`、`page_url`、`checked_at`、`cached`、`error_reason`。
   - 实现：后端读 `releases/latest` 的 `assets`，按文件名后缀选资产（`.apk` / `-Setup.exe` / `-Portable.zip` / `-macOS.tar.gz` / `-Linux-x64.tar.gz`），再读同名 `.sha256` 资产内容。
   - 保持 ADR-0017 的失败语义：查不到就是 `has_update: null` + `error_reason`，不得伪装成最新（`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:133-139`）。
   - 缓存与超时沿用 6h/60s/3s（`delector/routes/update.py:37,41-42`），避免打爆 GitHub 未鉴权限速。
4. **前端能力探测**：桌面浏览器版与 Android 共用同一套 chip；只有在检测到原生更新桥（Android）或桌面端更新 API 时才显示“应用内更新”，否则保持“打开 Release 页”。

### 4.2 Windows 安装版（Phase 1，建议最先做）

**流程**：

```
点“更新”
  → GET /api/update/artifact?platform=windows&install_kind=setup
  → 下载 Setup.exe 到 %TEMP%\DeLector-update\（支持 Range 续传、可取消）
  → 校验 sha256
  → 写入 helper 脚本（PowerShell，放 %TEMP%）
  → 应用主动退出
  → helper 等 PID 退出 → 运行 Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
  → 检查退出码 → 启动 %LOCALAPPDATA%\Programs\DeLector\DeLector.exe
  → 失败则保留日志并提示“打开 Release 页手动更新”
```

关键点：

- **不要依赖 Restart Manager 关应用**：虽然 `CloseApplications=yes`（`installer/DeLector.iss:53`）可以关，但让应用自己退出更可控，也避免静默模式下被锁文件卡住。
- **无 UAC**：`PrivilegesRequired=lowest` 且装到 `%LOCALAPPDATA%`（`installer/DeLector.iss:39-44`）。
- **静默安装已被 CI 验证**：`build-release.yml:177-188` 用 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...` 安装并真启验包。
- **安装形态判定**：先查 Inno 默认卸载注册项（`{AppId}_is1`）或安装目录，决定下载 Setup 还是 Portable。
- **回退**：安装器退出码非 0 / 新版本启动失败 → 提示手动运行安装器或打开 Release 页；旧版本已被替换时，无法原地回滚，但用户数据在 `%LOCALAPPDATA%\DeLector` 不受影响（`.iss:11-13`）。

### 4.3 Windows 便携版（Phase 2）

**流程**：

```
点“更新”
  → 下载 Portable.zip 到 %TEMP%\DeLector-update\
  → 校验 sha256
  → 解压到 %TEMP%\DeLector-update\new\
  → 校验新目录里的 DeLector.exe / .build-info.json（版本、commit）
  → 应用退出
  → helper 等 PID 退出
  → 旧目录改名 <dir>.old-<ts>
  → 新目录改名到原路径
  → 启动新 exe
  → 成功则删除旧目录；失败则把旧目录改回
```

关键点：

- helper 必须在 `%TEMP%`，不能位于被替换目录内。
- 目录改名可能因杀毒软件/资源管理器占用短暂失败，需要**有界重试**。
- 用户可能把便携版放在只读位置（如 `Program Files`）或可移动盘；先做写权限探测，失败则回退到“打开 Release 页”。
- 便携版与安装版共用数据目录，换目录不影响学习数据。

### 4.4 Linux（Phase 3）

**流程**：

```
点“更新”（或用户开启自动更新）
  → 下载 tar.gz → 校验 sha256
  → 解压到 ~/.local/share/DeLector/versions/<version>/
  → 校验新目录可执行文件
  → 原子切换 ~/.local/bin/DeLector 符号链接 → 新版本目录
  → 提示重启（或自动重启）
  → 失败/启动失败 → 符号链接切回上一版本
```

关键点：

- 必须先定义受管布局；否则只能覆盖用户当前解压目录，风险高。
- 保留上一版本目录作为回滚点（至少保留 1 个）。
- 无签名体系；校验和只能防损坏。若用户从源码运行，则不参与该更新器。
- 发行版兼容性风险不因自动更新而消失，反而会“自动推给用户”；建议默认关闭自动更新，仅提供“检查 + 一键更新”。

### 4.5 Android（Phase 4）

**流程（检测 → 下载 → 校验 → 拉起安装 → 失败回退）**：

1. **检测**：前端已有 3s 后自动检查与手动检查（`static/js/update.js:22,129-135`）。新增资产端点后，chip 显示“可更新 vX.Y.Z”。
2. **预检**：
   - 跳过 `applicationId` 以 `.emulator` 结尾的模拟器包（与正式包不能互相覆盖，`android/app/build.gradle:154-162`）。
   - 检查设备 ABI 为 arm64-v8a；否则提示“本包不支持当前设备”。
   - 检查剩余空间：需要 APK 大小 + 安装会话复制余量（约 2×APK），不足则直接提示，不开始下载。
   - 检查网络是否计费（`ConnectivityManager.isActiveNetworkMetered()`），移动网络下先确认。
3. **下载**：
   - 独立线程/`Executor`，`HttpURLConnection` GET，`Range: bytes=<已下载>` 续传；服务端返回 200 时从头开始，206 时追加。
   - 写到应用私有 `getCacheDir()/updates/app-<version>.apk.part`，完成后改名 `.apk`。
   - 进度回调节流（如 200ms 一次），支持取消；取消保留 `.part` 以便下次续传。
   - 只接受 `https://`；不信任 `Content-Disposition` 文件名，使用固定本地文件名。
   - MVP 阶段限制“应用在前台下载”；若要做到切后台继续，需要前台服务（`FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_DATA_SYNC`，Android 13+ 还需 `POST_NOTIFICATIONS`）或系统 `DownloadManager`。这两者都会扩大权限面，建议后续按实际反馈再加。
4. **校验**：
   - `MessageDigest` 流式计算 sha256，与资产端点返回值比对；不一致 → 删除文件，提示“安装包校验失败”。
   - `PackageManager.getPackageArchiveInfo(path, GET_SIGNING_CERTIFICATES)` 读取下载包的包名、versionCode、签名。
   - 断言包名 == `org.delector.app`；versionCode > 当前安装的 versionCode；签名证书集合 == 当前已安装应用的签名证书集合（自锚定，不依赖硬编码指纹）。
   - 任一失败 → 删除文件，给出具体原因，**不拉起安装器**。
5. **拉起安装**：
   - 检查 `packageManager.canRequestPackageInstalls()`；为 false 时跳 `Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`（`package:org.delector.app`），返回后继续。
   - 优先 `PackageInstaller` Session：`createSession(MODE_FULL_INSTALL)` → `openWrite()` 写入 APK → `commit(PendingIntent)`；注册结果接收，把 `INSTALL_FAILED_*` 映射成人话。
   - 备选 `ACTION_VIEW` + FileProvider（若不想做 session 复制，但需接受结果回读弱）。
6. **失败与回退矩阵**：

| 失败 | 处理 |
| --- | --- |
| 下载中断 / 网络切换 | 保留 `.part`，下次 Range 续传；Wi-Fi→移动网络时暂停并询问 |
| 服务端不支持 Range | 从 0 重下，提示“重新下载” |
| sha256 不符 | 删除，提示校验失败，保留“打开 Release 页” |
| 签名不符 | 删除并拒绝安装，提示“安装包签名与当前应用不一致” |
| versionCode 不递增 | 拒绝，提示“该版本不高于当前版本” |
| 用户拒绝“未知来源” | 回退到 Release 页；不反复弹设置 |
| 空间不足 | 下载前拦截，提示所需 MB |
| 系统安装被取消 | 保留已校验 APK，允许重试；不自动重复弹窗 |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | 提示签名不一致，禁止建议卸载（会丢数据） |
| `INSTALL_FAILED_VERSION_DOWNGRADE` | 提示版本回退，引导打开 Release 页 |
| `INSTALL_FAILED_NO_MATCHING_ABIS` | 提示设备架构不匹配（主要是模拟器/异架构设备） |
| MIUI 等 OEM 额外确认 | 文案提示“系统可能还会要求确认/扫描”，不承诺一步完成 |
| 进程在安装中被杀 | 下次启动比对 versionCode；未变化则提示“上次安装未完成”，提供重试 |

7. **失败回退的边界**：安装失败时旧版本仍在（系统保证），用户数据不受影响；不要建议“卸载重装”，因为卸载会清应用私有数据（`CHANGELOG.md:55`）。

**最小可用版本的取舍**：

- 只做 `device` arm64 渠道；模拟器渠道直接隐藏应用内更新。
- 只做前台下载；不做前台服务/DownloadManager。
- 只做 `PackageInstaller`；不做 FileProvider。
- 只做“用户点更新才下载”；不自动下载 60MB。
- 保留 `page_url` 作为所有失败路径的兜底。

### 4.6 macOS（暂缓）

**前置条件（缺一不可）**：

1. 分发改成 `.app` bundle（当前是裸二进制，`README.md:76`）。
2. Developer ID Application 签名 + notarization + stapling。
3. 决定更新框架：Sparkle（成熟，但引入依赖与 appcast 签名）或自建 helper。
4. CI 增加签名/公证步骤与密钥管理。

在这些完成前，macOS 维持“检查 + 打开 Release 页”。自建“换目录”更新器虽然技术可行，但会把未签名/未公证的风险自动化放大，不建议先做。

---

## 5. 体积与增量更新

### 5.1 体积事实

| 平台 | 体积 | 说明 |
| --- | --- | --- |
| Windows 便携 zip | 85.8 MB | PyInstaller onedir + Python 运行时 + spaCy 模型 |
| Windows Setup.exe | 约 95–120 MB | LZMA2 压缩（`.iss:47` 注释） |
| macOS tar.gz | 58.1 MB | onedir |
| Linux tar.gz | 118.5 MB | onedir，最大 |
| Android APK | 58.9 MB（Release） / 66.6 MB（本地 device debug） | arm64 单 ABI；三 ABI 会到 106.3 MB（`docs/agents/architecture.md:81`） |

来源：`FEATURES.md:167`；本地 APK 实测 `android/app/build/outputs/apk/device/debug/app-device-debug.apk` = 66,562,997 B（2026-11-13）。

### 5.2 增量更新（bsdiff / archive-patcher）评估

**结论：MVP 不做，先做断点续传。**

理由：

1. **载荷本身已压缩**：Android 的大头是 Chaquopy `.imy` 容器与原生 `.so`，Windows/Linux/macOS 是 PyInstaller 的压缩归档与 DLL。bsdiff 对已压缩字节的差分效果很差；每次构建的时间戳/顺序变化还会让差分退化。
2. **archive-patcher 理论上更适合 APK**（按 zip entry 解压、差分、重压缩），但要求构建可复现、entry 压缩参数稳定；当前没有 reproducible build 约束，收益不确定。
3. **分发是静态 GitHub Releases**：差分包必须由 CI 针对“上一版 → 本版”预生成并作为资产上传。N 个历史版本意味着 N 份补丁，资产膨胀、维护成本上升。
4. **客户端要引入补丁应用器**：Android 需要 `archive-patcher` 或 bsdiff JNI；桌面需要 bsdiff/zstd 补丁工具；每一端都增加失败路径（补丁应用失败、源包不匹配、校验失败）。
5. **当前更痛的是可达性与中断**：大陆网络到 GitHub 不稳，60–120MB 下载中断比“总量大”更常见。**Range 续传 + 明确进度 + 可取消**的收益高于差分。
6. **收益上限有限**：对自用/小规模分发，节省几十 MB 不如减少一次失败重试。

**若将来要做，先测量**：取两个相邻 tag 的 APK/zip，实跑 `bsdiff` 与 `archive-patcher`，记录补丁大小/原包大小、应用耗时、失败率；只有补丁稳定小于原包 30% 且发布频率足够高时才立项。不要凭直觉引入。

---

## 6. 安全面

### 6.1 校验和从哪里来

| 来源 | 可信度 | 适用 |
| --- | --- | --- |
| CI 生成 `.sha256` 并作为 Release 资产 | 与产物同一信任域（仓库写入方可改） | 所有平台，推荐作为传输完整性校验 |
| GitHub Releases API 的 asset `digest` | 同上；实现时以实际 API 响应为准 | 可选，减少一次资产请求 |
| 应用内硬编码期望哈希 | 每次发版都要改代码，必然漂移 | 不推荐 |
| 平台签名（Android APK 证书） | 强：攻击者没有私钥就无法伪造可覆盖安装的包 | Android，必须用 |

### 6.2 如何防替换

- **Android（最强）**：下载后比较“下载包签名证书”与“已安装应用签名证书”；系统在安装时也会强制校验。即使 Release 资产被替换，攻击者没有原签名私钥，安装会失败。CI 另有证书指纹闸（`build-release.yml:547-582`），防止构建期换 keystore。
- **Windows**：当前无 Authenticode，系统不提供发布者身份校验；只能 HTTPS + sha256。若未来做代码签名，可在 helper 里用 `Get-AuthenticodeSignature` 校验发布者，但签名证书成本与 CI 复杂度要单独决策。
- **macOS**：当前无 Developer ID/公证；`codesign --verify` 只能验证 ad-hoc 完整性，不能证明发布者。正规方案必须先补签名/公证。
- **Linux**：无系统签名体系；HTTPS + sha256，必要时可加 minisign/Ed25519 清单（需要引入验证库或二进制）。
- **通用**：只接受 `https://`；校验重定向终点仍是 https；固定本地文件名；校验 `size_bytes` 上限，防止磁盘被写满。

### 6.3 Release 资产被篡改时如何发现

1. **Android**：签名不匹配 → 系统拒绝安装；应用预检也会拒绝并给出原因。
2. **所有平台**：sha256 与 `.sha256` 资产不一致 → 拒绝使用；但这要求 `.sha256` 本身未被同时替换。
3. **构建指纹**：Windows 产物含 `.build-info.json`（版本/commit/构建时间，`package_windows.py:243-259`），可在解压后核对版本与 commit；它不是密码学证明，但能发现“旧包冒充新包”。
4. **发布记录**：把每个 Release 资产的 sha256 追加到 `CHANGELOG.md` 或 Release 正文。CHANGELOG 是追加式历史，第三方可对照发现“同一版本资产被替换”。
5. **CI 审计**：GitHub Actions 日志与 Release 编辑历史；若仓库/账号被攻陷，唯一可靠的剩余防线是 Android 的签名私钥与（未来的）Windows/macOS 代码签名私钥。

**建议的取舍**：Android 用签名自锚定；桌面三平台先做 sha256 + HTTPS，不引入 minisign 这类新信任链（收益低于维护成本）。若将来桌面用户规模上来，再评估代码签名（Windows Authenticode、macOS Developer ID）而不是自建签名体系。

---

## 7. 跨平台对照表

| 平台 / 形态 | Release 产物 | 自动程度（用户确认步数） | 后台下载 | 替换/安装机制 | 需要的签名/权限 | 实现复杂度 | 增量更新值得？ | 主要风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Windows 安装版 | `Setup.exe` | **1 步**（SmartScreen 可能 +1；无 UAC） | 容易（Python 线程，应用可继续运行） | helper 等退出 → 静默安装 → 重启 | 无强制；当前未签名，可选 Authenticode | 中（3/5） | 否 | 安装器退出码/SmartScreen/安装形态误判 |
| Windows 便携版 | `Portable.zip` | **1 步** | 容易 | helper 等退出 → 目录交换 → 重启 | 需要安装目录写权限 | 中高（4/5） | 否 | 文件锁、目录占用、只读路径、回滚 |
| macOS | `macOS.tar.gz` | 现状 1 步（跳浏览器）；自建换目录 1 步但 Gatekeeper 可能额外拦截 | 容易（POSIX） | 换版本目录 + 重启（需先改 `.app` 才正规） | 正规方案需 Developer ID + 公证 | 高（4/5，含打包改造） | 否 | 未签名/未公证、裸二进制、Gatekeeper |
| Linux | `Linux-x64.tar.gz` | **0–1 步** | 容易 | 版本目录 + 符号链接原子切换 + 重启 | 无 | 中低（2.5/5） | 否（体积大但用户少） | 受管布局缺失、发行版差异、回滚 |
| Android | `Android.apk` | **2–3 步**（未知来源 + 系统安装确认 [+ OEM]） | 前台可行；后台需前台服务/DownloadManager | `PackageInstaller` 或 `ACTION_VIEW` + FileProvider | `REQUEST_INSTALL_PACKAGES` + 用户授权；APK 签名已有 | 中高（4/5） | 否（MVP）；移动数据痛时再测 | 签名/versionCode/ABI/OEM 确认/进程被杀 |
| Docker | 本地构建 | 不适用（手动 rebuild） | 不适用 | `docker compose up -d --build` | 无 | - | 否 | 数据卷、镜像未发布 |
| 源码运行 | git 工作树 | 不适用 | 不适用 | `git pull` + 重启 | 无 | - | 否 | 环境差异 |

自动程度的口径：**“用户点几下”**，不含等待下载的时间。Windows/Linux 的“0 步”指用户开启“自动更新”后无需每次确认；默认仍建议保留一次确认。

---

## 8. 风险清单

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 新 ADR 未立就先写代码 | 违反 ADR-0017 的显式约束，后续审计不通过 | 先立 ADR，再排期 |
| 往 `/api/update/check` 加字段 | 7 键契约测试必红、前端/探针连锁改动 | 新增独立资产端点 |
| Windows 安装版/便携版混用升级包 | 产生两个副本或更新失败 | 启动时判定安装形态（注册项/目录标记），只给对应包 |
| helper 放在被替换目录 | 自身被锁/被删，更新中断 | helper 固定在 `%TEMP%`，独立于应用目录 |
| 静默安装被误当成可行 | 做出永远无法交付的功能 | 明确“系统确认不可绕过”，只承诺自动下载与预检 |
| Android 模拟器渠道收到 arm64 包 | `INSTALL_FAILED_NO_MATCHING_ABIS` | 检测 `applicationId` 后缀与 ABI，模拟器隐藏入口 |
| 移动网络下自动下载 60MB | 流量投诉 | 默认只在 Wi-Fi 下载；计费网络先确认 |
| 进程在下载/安装中被杀 | 半包、安装未完成 | Range 续传 + 下次启动版本比对 + 可重试 |
| 签名/版本校验缺失 | 安装失败原因不可读，或误装错包 | 包名/versionCode/签名/ABI 四道预检 |
| macOS 自动更新放大未签名风险 | Gatekeeper 拦截、用户困惑 | 暂缓；先补 `.app` + 签名/公证 |
| Linux 自动更新破坏发行版兼容 | 新版本无法启动 | 保留上一版本目录 + 启动失败自动回滚 |
| 增量更新引入新失败路径 | 补丁应用失败、维护成本 | 暂不引入；先测量再决策 |
| `.sha256` 与产物同时被替换 | 哈希校验失效 | 明确其定位为传输校验；Android 依赖签名，桌面依赖代码签名（未来） |
| 发版频率高导致提示疲劳 | 用户关闭更新 | 默认静默检查、仅落后时提示；不做强制弹窗 |

---

## 9. 需要拍板的决策点

1. **是否接受新 ADR**：从“只检查不安装”升级为“应用内下载 + 平台安装”。这是所有后续工作的前置。
2. **平台顺序**：建议 Windows 安装版 → Android → Windows 便携版 → Linux → macOS（暂缓）。若更看重手机端体验，可把 Android 提到第一位。
3. **Windows 安装版与便携版的优先级**：安装版路径更简单、CI 已验证静默安装；便携版用户可能更多（当前主推 zip），需要确认实际用户分布。
4. **Android 的确认体验**：是否接受“最少 2 步确认 + 新增 `REQUEST_INSTALL_PACKAGES` 权限面”。若不接受，就只能维持现状（跳 Release 页）。
5. **macOS 是否投入签名/公证**：不投入则不做应用内更新；投入则需 Developer ID、公证流程与 `.app` 改造。
6. **是否发布 `.sha256` 资产**：这是所有平台校验的基础，成本极低，建议无条件做。
7. **增量更新**：明确“暂不做”，先测量；避免在 MVP 里引入补丁应用器。

---

## 10. 证据索引（文件:行号）

### 更新检测与版本

- `delector/routes/update.py:34` — GitHub `releases/latest` 地址。
- `delector/routes/update.py:37,41-42` — 3s 超时；成功缓存 6h、失败 60s。
- `delector/routes/update.py:82-111` — 只取 `tag_name`/`html_url`。
- `delector/routes/update.py:114-136` — tag → versionCode 比较；`page_url` 为 Release 页。
- `delector/routes/update.py:186-193` — `GET /api/update/check` 端点。
- `delector/core/version.py:15,22-41` — `APP_VERSION` 与 versionCode 规则。
- `static/js/update.js:22,73-116,129-135` — 3s 延迟、仅落后显示 chip、手动检查。
- `static/index.html:34-45` — 顶栏版本自证串与 chip 挂载点。
- `tests/test_update_check_endpoint.py:29-37,221-230` — 7 键契约冻结。
- `desktop.py:103-104` — 托盘“检查更新”打开 Releases 页。
- `docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:79-83,164-165,188-196` — Option B 被否决；升级需另开 ADR；明确 NOT doing 清单。

### Android 分发与能力

- `android/app/build.gradle:8-9,68-77` — 版本 fallback、applicationId、minSdk 24、targetSdk 34、versionCode 规则。
- `android/app/build.gradle:47-66` — pinned keystore 签名；显式 v1。
- `android/app/build.gradle:100` — Chaquopy `extractPackages`。
- `android/app/build.gradle:145-163` — device 仅 arm64；emulator 带 `.emulator` 后缀与 x86_64。
- `android/app/build.gradle:187-190` — 依赖只有 appcompat/material（无 Play Core）。
- `android/app/src/main/AndroidManifest.xml:4-6` — 仅 INTERNET/ACCESS_NETWORK_STATE/VIBRATE。
- `android/app/src/main/AndroidManifest.xml:14-32` — 无 `REQUEST_INSTALL_PACKAGES`、无 FileProvider。
- `android/app/src/main/java/org/delector/app/MainActivity.java:292-294` — 已有 `@JavascriptInterface` 桥。
- `android/app/src/main/java/org/delector/app/MainActivity.java:343-344` — 下载统一进 `ExportSaver`。
- `android/app/src/main/java/org/delector/app/MainActivity.java:514-524` — 外链交给系统。
- `android/app/src/main/java/org/delector/app/ExportSaver.java:36-51` — 弃用 DownloadManager 的理由。
- `android/app/src/main/java/org/delector/app/ExportSaver.java:211-224` — 自建 HTTP GET（无 Range）。
- `.github/workflows/build-release.yml:474-500` — tag → versionName/versionCode。
- `.github/workflows/build-release.yml:522-545` — 只构建 `assembleDeviceDebug` 并重命名 APK。
- `.github/workflows/build-release.yml:547-582` — keytool 证书指纹闸；`:555` 为期望 SHA256。
- `.github/workflows/build-release.yml:696-709` — Release 资产列表（zip/Setup.exe/tar.gz/apk）。
- `FEATURES.md:165,167` — APK 58.8/58.9 MB；四平台体积。
- `docs/agents/architecture.md:81` — arm64 约 57MB vs 三 ABI 106.3MB。
- `CHANGELOG.md:44` — v5.23.4→v5.23.5 真机覆盖安装验证。
- `CHANGELOG.md:55` — 降级被系统拒绝，`adb install -r -d` 才可。
- `tools/install_apk.py:6` — MIUI USB 安装确认导致 `INSTALL_FAILED_USER_RESTRICTED`。

### Windows / macOS / Linux 分发

- `package_windows.py:316-323` — PyInstaller `--onedir --windowed`。
- `package_windows.py:418-436` — 产物目录、`.build-info.json`、README。
- `installer/DeLector.iss:8-16` — per-user、数据分离、未签名。
- `installer/DeLector.iss:35-44` — AppId、安装目录、`PrivilegesRequired=lowest`。
- `installer/DeLector.iss:53-54` — `CloseApplications=yes`、`RestartApplications=no`。
- `installer/DeLector.iss:82-83` — 静默安装不自动启动。
- `.github/workflows/build-release.yml:76-87` — Windows zip。
- `.github/workflows/build-release.yml:89-194` — Setup.exe 构建与静默安装验包。
- `.github/workflows/build-release.yml:294-296` — Linux tar.gz。
- `.github/workflows/build-release.yml:402-404` — macOS tar.gz。
- `.github/workflows/build-release.yml:727-728` — macOS/Linux 裸二进制说明。
- `README.md:75-78` — 四平台下载说明、未签名/未公证、数据目录。
- `desktop.py:993-998` — 旧版本仍在运行时的“版本冲突”提示。
- `Dockerfile:1-18` — 容器入口。
- `README.md:51` — Docker 使用方式。
