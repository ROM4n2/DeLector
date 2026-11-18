# ADR-0034: 跨平台应用内更新——桌面自替换、Android 走系统安装确认

- **状态**：Accepted（2026-11-17；M0–M5 代码已实施，**真机/真装验证未执行**，逐项边界见实施计划 §8）
- **日期**：2026-11-17
- **决策方式**：2026-11-17 方案评审后拍板（D1–D8 全部采纳）
- **取代/修订**：**部分取代 ADR-0017**。ADR-0017 的「检查链路」继续有效；其「只检查、不安装」的核心切口（§4.1 Q1-A）、对 Option B 的否决（§3.2）与 §6.3 的 NOT doing 清单被本 ADR 修订。逐条范围见 §4.3。
- **关联**：
  - `docs/research/2026-11-17-cross-platform-update-strategy.md`（本 ADR 的事实底稿与证据索引）
  - ADR-0017-android-update-check-notifier（检测链路、7 键契约、失败语义；本 ADR 不改这些）
  - ADR-0019-windows-desktop-pwa-first-and-data-dir-externalization（数据目录外置，更新不碰用户数据）
  - ADR-0020-windows-desktop-shell-pywebview（桌面壳边界）
  - ADR-0022-release-gate-v5.17.0（发版门与产物验证）
  - 红线 4（versionCode 编码）、红线 6（缓存闸）、红线 9（import 期不联网）、红线 11（跨边界契约须行为探针验证）

---

## 1. Context

### 1.1 现状：能「知道落后」，不能「取回并安装」

现有一切检测能力都围绕 `GET /api/update/check`：

- 查询 GitHub `releases/latest`，只读 `tag_name` 与 `html_url`（`delector/routes/update.py:82-111`）。
- 按 versionCode 语义与 `APP_VERSION` 比较（`delector/routes/update.py:114-136`；`delector/core/version.py:15,22-41`）。
- 前端页面加载 3s 后自动查一次，或用户点顶栏手动查；仅落后时显示 chip，点击打开 Release 页（`static/js/update.js:22,73-116`；`static/index.html:34-45`）。
- 响应契约**恰好 7 个键**且被测试冻结（`tests/test_update_check_endpoint.py:29-37,221-230`）。
- **完全不读 release assets**，因此没有安装包地址、大小、哈希。

结论：当前链路能消灭「不知道有新版」的盲区，但「下载—搬运—覆盖安装」仍全部由用户手工完成。

### 1.2 分发形态决定了各平台上限不同

| 平台 | 现状产物 | 应用能否自替换 | 真正的卡点 |
| --- | --- | --- | --- |
| Windows 安装版 | Inno Setup `Setup.exe`，per-user | 可以（退出后由 helper 静默安装） | 运行中的 exe/DLL 被锁；未签名可能触发 SmartScreen |
| Windows 便携版 | `Portable.zip`，PyInstaller onedir | 可以（helper 等退出后换目录） | 目录交换与回滚；helper 必须在 `%TEMP%` |
| Linux | `Linux-x64.tar.gz`，裸二进制 | 可以（换版本目录 + 符号链接） | 当前没有受管安装布局 |
| Android | `Android.apk`，arm64 | **不可以**（系统独占安装） | 未知来源授权 + 系统安装确认，最少 2–3 步 |
| macOS | `macOS.tar.gz`，非 `.app`、未签名/未公证 | 技术上可换目录，但不正规 | Gatekeeper/公证；本 ADR 决定暂缓 |

### 1.3 为什么现在改写 ADR-0017

ADR-0017 在 2026-10-08 否决 Option B 的理由是「增量收益仅是少开一次浏览器，代价是新增权限面与三条新失败路径」（`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:79-83`）。当时的前提是：桌面端刷新即生效、Android 侧两条关键假设（公网 HTTPS、外链交给系统浏览器）尚未真机验证。

现在前提已变化：

1. Android 覆盖安装已在 arm64 真机验证（v5.23.4 → v5.23.5，Redmi Note 8 / Android 11，`CHANGELOG.md:44`），检测链路可用。
2. 分发形态已稳定为「GitHub Releases 四平台产物」，且 Windows 安装版已具备静默安装能力并在 CI 真装真启验证（`.github/workflows/build-release.yml:177-188`）。
3. 用户明确选择接受 Android 新增 `REQUEST_INSTALL_PACKAGES` 权限面，并接受「Android 最少 2–3 步确认」的平台事实。
4. 跨平台对照后，桌面三平台可以做到接近全自动，收益不再只是「少开一次浏览器」。

因此本 ADR 正式把「只检查不安装」修订为「检查 + 应用内下载 + 分平台安装」，并保留 ADR-0017 的检测链路与失败语义。

---

## 2. Decision Drivers

- **U1 闭环**：把「找包—下载—搬运—覆盖安装」从用户手里拿走，至少做到「一键下载 + 一键安装」。
- **U2 零打扰**：无新版不提示；检查失败不弹错；不在用户未确认时自动下载几十 MB。
- **U3 平台诚实**：不把 Android 的「系统确认」包装成「静默」；不把 macOS 的未签名更新包装成「正规自动更新」。
- **T1 契约冻结**：`/api/update/check` 的 7 键契约、`has_update` 三态与失败语义不得改动。
- **T2 最小权限面**：只新增 Android `REQUEST_INSTALL_PACKAGES`；不引入 `DownloadManager`、FileProvider、前台服务（MVP 不做后台下载）。
- **T3 不新建信任链**：继续以 GitHub Releases 为唯一真相源；不自建更新服务器；Android 用签名自锚定，桌面用 HTTPS + sha256。
- **T4 不碰用户数据**：更新只替换程序目录/安装目录；学习数据目录保持不变。
- **T5 可验证性**：在当前「不跑全量测试、不做真机、不下载资产、不 push」的约束下，优先把可单测的纯逻辑（资产选择、哈希、版本/签名判定、错误映射）与真实网络/安装动作分离。

---

## 3. Considered Options

### 3.1 Option A：维持 ADR-0017（只检查 + 提示）

- 优点：零新权限、零新失败路径、零维护；现状已可用。
- 缺点：Android 仍需用户手动开浏览器、找资产、下载、搬运、安装；桌面包 58–118MB，同样手工。
- 结论：**不采纳**。它解决的是「不知道」，不解决「拿到并装上」。

### 3.2 Option B：应用内下载 + 分平台安装（采纳，修订形态）

- 优点：桌面可接近全自动；Android 可把找包/搬包/验包自动化；保留 Release 页作为永久退路。
- 缺点：新增 Android 权限面；新增下载、校验、安装、回滚等失败路径；Windows/Linux 需要 helper；macOS 无法正规化。
- 结论：**采纳**，但按平台分别定义上限与回退，不做「一套说法套所有平台」。

### 3.3 Option C：Play In-App Updates API

- 前提：应用经 Google Play 分发并由 Play 安装、引入 Play Core、使用 Play App Signing、AAB 与审核。
- 现状：DeLector 只经 GitHub Releases 直发 APK，依赖仅 `appcompat`/`material`，发的是 pinned keystore 签名的 debug 变体（`android/app/build.gradle:47-66,187-190`；`.github/workflows/build-release.yml:522-545`）。
- 优点：若上架 Play，更新体验最标准。
- 缺点：引入 Play 分发是产品/合规级变更；审核节奏与当前发版频率冲突；对侧载 APK 无效；仍然不是静默安装。
- 结论：**不采纳**。未来若上架 Play，另开 ADR。

### 3.4 Option D：静默安装

- 优点：用户零确认。
- 缺点：平台层面不成立。`android.permission.INSTALL_PACKAGES` 是 `signature|privileged`；普通第三方应用即使声明也拿不到；`PackageInstaller` 对非特权调用者始终展示系统确认；只有系统/特权应用、root/ADB shell、或企业 Managed Google Play 能免确认。
- 结论：**不采纳**。这是平台硬约束，不是取舍问题；不得在文案或计划里暗示可以做到。

### 3.5 Option E：依赖现成侧载更新器（Obtainium 等）

- 优点：零开发。
- 缺点：同样依赖 GitHub 可达；同样要吃系统确认；治不了「不知道自己落后」；把更新信任交给第三方应用。
- 结论：**不采纳**。

### 3.6 Option F：增量更新（bsdiff / archive-patcher）

- 优点：移动网络下省流量。
- 缺点：APK 的主要载荷（Chaquopy `.imy`、原生 `.so`）与桌面归档本身已压缩，差分收益不确定；GitHub 静态托管要求 CI 按版本对预生成补丁；客户端需引入补丁应用器与新失败路径。
- 结论：**MVP 不采纳**。先做断点续传；若将来要做，先用相邻两版实测补丁占比再立项。

### 3.7 Option G：热更新 `static/`

- 结论：**继续不采纳**。理由沿用 ADR-0017 Option D：前端与 Python 后端是强耦合契约，热更新会静默破坏跨边界契约与离线自包含模型（`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md:89-91`）。

---

## 4. Decision Outcome

### 4.1 锁定决策

| 编号 | 决策 | 内容 |
| --- | --- | --- |
| **D1** | 引入应用内更新 | 检查 → 下载 → 校验 → 分平台安装；Release 页永久保留为退路 |
| **D2** | 平台顺序 | **Windows 安装版 → Android → Windows 便携版 → Linux**；macOS 暂缓 |
| **D3** | Android 安装方式 | 新增 `REQUEST_INSTALL_PACKAGES`；优先 `PackageInstaller` Session；不做 FileProvider、不做 DownloadManager、不做静默安装 |
| **D4** | 元数据契约 | 新增独立 `GET /api/update/artifact`；`/api/update/check` 的 7 键契约**原样不动** |
| **D5** | 校验和来源 | CI 为每个 Release 资产生成并上传 `.sha256`；应用运行时校验 |
| **D6** | macOS | 不投入签名与公证；维持「检查 + 打开 Release 页」，不做应用内安装 |
| **D7** | 增量更新 | MVP 不做；先做 Range 断点续传、取消与进度 |
| **D8** | 安全锚点 | Android 用「下载包签名 == 已安装应用签名」自锚定；桌面用 HTTPS + sha256；不新增自建签名体系 |

### 4.2 分平台契约

| 平台 | 用户确认步数 | 下载 | 安装/替换 | 失败回退 |
| --- | --- | --- | --- | --- |
| Windows 安装版 | 1 步（SmartScreen 可能 +1） | `Setup.exe`，`%TEMP%`，可续传 | helper 等应用退出 → `/VERYSILENT` 安装 → 重启 | 安装器退出码非 0 → 提示手动安装/打开 Release 页 |
| Android | 最少 2–3 步 | APK 到应用私有缓存，Range 续传 | `PackageInstaller` Session → 系统确认 | 校验失败/用户拒绝/空间不足/安装失败 → 保留旧版 + 可读原因 + Release 页 |
| Windows 便携版 | 1 步 | `Portable.zip`，`%TEMP%`，可续传 | helper 等退出 → 目录交换 → 重启 | 交换失败 → 旧目录改回；只读目录 → Release 页 |
| Linux | 0–1 步 | `tar.gz`，可续传 | 版本目录 + 符号链接原子切换 → 重启 | 启动失败 → 符号链接切回上一版本 |
| macOS | 1 步（跳浏览器） | 不做 | 不做 | 维持现状 |

### 4.3 与 ADR-0017 的取代范围（精确）

| ADR-0017 条目 | 本 ADR 后的状态 |
| --- | --- |
| §1.2 / §1.3 检测链路事实 | **继续有效**（作为历史事实保留） |
| §3.2 Option B「否决」 | **被修订**：应用内下载 + 安装被采纳，但限定为 `PackageInstaller`、无 FileProvider、无 DownloadManager、无静默安装 |
| §4.1 Q1-A「只做检查+提示」 | **被取代**：改为「检查 + 应用内下载 + 分平台安装」 |
| §4.1 Q2-A（GitHub Releases 唯一真相源） | **继续有效** |
| §4.1 Q3-A（后端端点代查，非前端直连） | **继续有效** |
| §4.1 Q4-A（启动后延迟检查、TTL、无新版静默） | **继续有效**；新增「仅在用户点更新时下载」 |
| §4.2 7 键端点契约与四条不变式 | **继续有效，原样冻结** |
| §5.3「将来做 Option B 需另开 ADR」 | **已兑现**：即本 ADR |
| §6.3 NOT doing 清单 | **部分解除**：解除「应用内下载 APK、唤起安装器、`REQUEST_INSTALL_PACKAGES`」；**保留**「静默安装、自建更新服务、差分更新、恢复三 ABI、前端直连 GitHub、热更新 `static/`、LAN 代理、自动安装/自动下载」 |

> ADR-0017 正文不改写；只在其文末追加 Amendment 指针（见该文件 §9）。

### 4.4 必须成立的不变式（落地时逐条守）

1. `/api/update/check` 仍恰好 7 个键；`has_update === null ⇔ error_reason !== null`；失败不得伪装成最新。
2. 新端点失败时同样不得返回 `has_update: false`；资产缺失/不可解析统一给 `error_reason`。
3. 下载 URL 只接受 `https://`；不信任文件名与 `Content-Disposition`，使用固定本地文件名。
4. 下载与安装前必须校验：包名、versionCode 严格递增、签名与已安装应用一致（Android）、sha256 与 CI 资产一致。
5. Android 模拟器渠道（`applicationId` 带 `.emulator`）不提供应用内更新；ABI 不匹配时拒绝。
6. 任何失败都不引导用户「卸载重装」；卸载会清应用私有数据。
7. 更新过程不得触碰用户数据目录；Windows 只替换安装目录，Linux 只切换版本目录。
8. 不在用户未确认时自动下载；移动网络下先询问。

### 4.5 实施与验证边界（本 ADR 生效时的环境约束）

本次落地必须遵守以下约束，**任何一条都不得为了「验证通过」而绕过**：

- 本机不跑全量测试；只跑与改动直接相关的单元测试/探针。
- 不做真机验证；Android 安装相关结论只能来自单测、fixture 与既有 CI 记录。
- 不下载任何安装包或 release 资产；网络行为只允许在单测里用 fixture/假 fetcher 表达。
- 不 push。
- 若某一步必须真下载、真安装或真机运行才能证明，**停下来报告**，不得用模拟结果冒充验证结论。

---

## 5. Consequences

### 5.1 正向

- 桌面三平台可把更新收敛为「一次确认 + 自动重启」；Android 可把找包/搬包/验包自动化。
- 不新建更新服务：继续用 GitHub Releases，后端只做资产元数据规约。
- 契约隔离：新增端点不影响已冻结的 7 键检查契约，前端与探针的既有语义不漂移。
- 安全边界清晰：Android 有真正的签名锚；桌面明确承认「无代码签名」的残余风险，不假装有。

### 5.2 负向 / 代价

- **Android 新增权限面**：`REQUEST_INSTALL_PACKAGES` + 用户「未知来源」授权；这是对 ADR-0017 T2（不扩大攻击面）的显式让步。
- **失败路径显著增多**：下载中断、哈希不符、签名不符、versionCode 不递增、未知来源被拒、空间不足、OEM 额外确认、进程被杀、安装被取消。
- **Windows/Linux 需要 helper**：helper 的路径、重试、回滚、日志都是新维护面。
- **macOS 仍不完整**：不投入签名/公证意味着 macOS 永远停留在「跳 Release 页」。
- **无桌面代码签名**：Windows SmartScreen、macOS Gatekeeper 的体验问题不因本 ADR 消失。
- **不做增量更新**：移动网络下仍需下载完整 59MB APK；用断点续传缓解，但不消除。

### 5.3 回退与关闭开关

- 新端点是纯增量：关闭前端入口即可回到 ADR-0017 的「检查 + 跳转」行为。
- 各平台更新入口应可独立关闭（例如 Android 侧桥不可用/平台未实现时只显示 Release 页）。
- 更新失败不改变旧版本可用性；Android 系统保证安装失败时旧版保留。

---

## 6. 后续（不在本 ADR 内决策）

- macOS：`.app` 化 + Developer ID + 公证 + Sparkle/自建 appcast（需另开 ADR）。
- 增量更新：先测量 bsdiff/archive-patcher 的实际补丁占比，再决定。
- Windows Authenticode、macOS 公证：属于代码签名投入决策，另行评估。
- Android 后台下载：若前台下载体验不足，再评估前台服务或 DownloadManager（会扩大权限面）。
- Play 分发：若未来上架 Play，再评估 Play In-App Updates。

---

## 7. 关联

- 事实底稿与逐文件证据：`docs/research/2026-11-17-cross-platform-update-strategy.md`。
- 被修订的决策：`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md`（文末 §9 Amendment）。
- 桌面数据目录：ADR-0019；桌面壳：ADR-0020；发版门：ADR-0022。
- 守卫：`tests/test_update_check_endpoint.py`（7 键契约与失败语义）、`tests/test_writer_mobile.py`（版本单一真相源）、`.github/workflows/build-release.yml`（签名指纹与产物验证）。
