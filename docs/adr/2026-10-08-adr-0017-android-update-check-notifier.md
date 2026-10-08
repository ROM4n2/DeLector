# ADR-0017: Android 更新可见性（检查 + 提示，不做应用内安装）

> **正式件:** `08-Projects/DeLector/01-ADR/0017-android-update-check-notifier.md`（vault）。本文件是仓内副本，内容与正式件同源。
> **决策者:** Haoyu Xi ｜ **产出方式:** `/dfs-grill` 双镜拷问（product-ux + sre-resilience 席位）

- **状态**: Accepted（2026-10-08）
- **实施**: **已完成**（2026-10-08，分支 `feat/update-visibility`，6 个 commit `b2f191c`/`cf69bf2`/`efee426`/`1acdcf7`/`051ed7d`/`c335215`，**未发版**）。Android 真机两条假设仍待验证，见 §7.3。
- **日期**: 2026-10-08
- **领域**: 发布工程 / Android 分发 / 前端可用性 / 本地优先
- **决策者**: Haoyu Xi
- **关联**: ADR-0005（导航与备考域）、`WORKMEMORY/work.log` v5.16.0 发版事件、vault `08-Projects/DeLector/POST-MORTEM-V5.5.2-VERSION-NUMBER-SCATTER.md`（版本号散布必漏改）、红线 4/5/6/7/11

---

## 1. Context

### 1.1 提案原文

> 「安卓能不能更新一个可以直接更新的功能？现在还是要覆盖安装。」

即：Android 端希望**应用内直接更新**，替代手动下载 APK 再覆盖安装。

### 1.2 拷问推翻的第一个前提：痛点不在"安装这个动作"

| 环节 | 现状 | 应用内更新能否消除 |
| --- | --- | --- |
| ① 意识到存在新版 | **完全不可达** —— 全仓无任何版本检查端点，顶栏 `static/index.html:35` 的 `System · v5.16.0 Online` 是 APK 内**静态字符串** | ❌ **吃不掉，而且这才是真瓶颈** |
| ② 去 GitHub 找 release asset | 手动开浏览器/文件管理器 | ✅ |
| ③ 下载 56.7MB（arm64-only） | 手动搬运到手机 | ✅ |
| ④ 允许「安装未知应用」 | 系统权限页 | ❌ 平台硬约束 |
| ⑤ 系统安装确认对话框 | 系统对话框 | ❌ 平台硬约束（无静默安装） |

**结论**：应用内更新只能吃掉中段两环，代价是新增权限面与三条新失败路径；而**一天一版**的发版节奏（v5.13.0 → 2026-10-03 至 v5.16.0 → 2026-10-06）意味着用户大多数时间在跑旧代码**而不自知**。

### 1.3 已核实的事实（证据，非推测）

| 事实 | 证据 |
| --- | --- |
| Android 无安装权限、无 FileProvider | `android/app/src/main/AndroidManifest.xml:4-31` 仅 `INTERNET` / `ACCESS_NETWORK_STATE` |
| WebView 的**所有**下载被统一接进导出管线 | `android/app/src/main/java/org/delector/app/MainActivity.java:257-258`（`DownloadListener` → `ExportSaver`）⇒ APK 若走这条路会以"导出失败/HTTP 错误"的文案报错，且无安装 Intent 接续 |
| 顶栏版本是静态字面量，且"Online"在单机回环下字面撒谎 | `static/index.html:35`；Android 端只绑 `127.0.0.1`（ADR 与 `docs/agents/architecture.md` 「Android 独立单机版」） |
| 后端**没有**版本常量 | 全仓无 `__version__`；现版本散落在 `static/index.html`、`static/sw.js`、`android/app/build.gradle`（`DELECTOR_VERSION_NAME`）等**多个表面** |
| 覆盖安装**不丢数据** | Android app 内部存储随覆盖安装保留 ⇒ 痛点不是数据安全 |
| 分发只经 GitHub Releases | `.github/workflows/build-release.yml`（tag 触发，四平台产物） |
| CI 已 pin 签名证书指纹 | `build-release.yml:380` 的 `EXPECTED_SHA256`（本 ADR 不用，但记录为将来 Option B 的现成信任锚） |
| 桌面端永不需重装 | 桌面端绑 `0.0.0.0`，`python start.py` + 刷新即生效 |

### 1.4 为什么"用手机浏览器连桌面端"不是答案

该路径确实永不重装，但覆盖不了需要**独立运行**的真实场景：通勤地铁无 Wi-Fi、桌面机未开机或不同网、异地只带手机。因此 LAN 不是替代品，**"知道落后了"才是缺失的那一环**。

---

## 2. Decision Drivers

### 2.1 用户与产品（User & Product）

- **U1 消除盲区**：一天一版节奏下，用户必须能**自动**知道存在新版（手动检查会退化回今天的盲区）。
- **U2 零打扰**：无新版不提示；检查失败不弹错；绝不主动弹窗（地铁无网/快速刷两张卡时弹窗会迅速变成"烦到我关掉它"）。
- **U3 失败要人类可读**：不能把 `HTTP 404` / `fetch failed` 当主文案；「连不上 GitHub，请检查网络」才是主文案。
- **U4 顺带修掉假状态**：`System · vX.Y.Z Online` 中的 `Online` 在单机回环场景是错的，应改为真实版本 + 真实检查结果。

### 2.2 技术与工程（Technical & Systems）

- **T1 可测**：判据必须能被 pytest / 行为探针真跑（红线 11：字符串存在断言是死测）。
- **T2 不扩大攻击面**：不新增 Android 权限、不引入供应链校验链路。
- **T3 隔离外部不确定性**：GitHub 匿名限速（60 req/h/IP）、CORS、大陆网络不稳，全部隔离在服务端。
- **T4 不重演"版本号散布"事故**：新判据不得再造一个硬编码版本点（vault `POST-MORTEM-V5.5.2-VERSION-NUMBER-SCATTER`；同类陷阱即 v5.16.0 修掉的 `PROCESSED_JSON_VERSION` 判据漂移）。
- **T5 零新依赖、零 APK 结构变化**：`static/` 仍自包含，离线单机模型不破。

---

## 3. Considered Options

### 3.1 Option A（**采纳**）—— 版本检查 + 提示

新增 `GET /api/update/check`：服务端请求 GitHub Releases API，返回规约后的版本对比结果；前端在落后时显示一条可点 chip，点击跳 GitHub Release 页面，**下载与安装全交系统**。

### 3.2 Option B（**否决**）—— A + 应用内下载 + 唤起安装器

在 A 之上增加：系统 `DownloadManager`（抗杀进程/自带重试）+ 签名锚校验（下载包 signer SHA256 ≠ 已装 app 自身 signer 即删除拒绝）+ versionCode 严格递增预判 + FileProvider + `ACTION_VIEW` 安装 Intent + `PackageInstaller` 结果回调。

**否决理由**：增量收益仅"少开一次浏览器"，代价是 `REQUEST_INSTALL_PACKAGES` 权限、FileProvider、`DownloadListener` 分流、签名/哈希/版本三条新失败路径、`INSTALL_FAILED_UPDATE_INCOMPATIBLE` 的自诊断负担。对**自用单机版**是负收益。（保留为将来钩子：若真要做，信任锚必须用 `build-release.yml:380` 的 `EXPECTED_SHA256` 或用 `PackageManager` 读已装 app 自身签名——**只校验随包发布的 `.sha256` 是假防线**，因为能换 APK 的人也能换那个哈希。）

### 3.3 Option C（**否决**）—— 不写代码，装现成侧载更新器（Obtainium 类）

**否决理由**：它同样依赖 GitHub 可达（大陆不稳），同样要吃系统确认框，而且**治不了盲区**——它自己也不知道你落后了，除非你主动去看它。可作为零成本对照实验，但不能作为决策终点。

### 3.4 Option D（**否决**）—— 热更新 `static/`（前端改动免重装）

**否决理由**：`static/` 与 Python 后端是**强耦合契约**（红线 11 的同类跨边界风险）。热更新前端而后端仍旧，会静默破坏前端 body ↔ 后端模型契约；且破坏"APK 内 static 自包含"的离线单机模型（红线 6 的缓存闸语义亦基于此）。Python 侧改动无法热更新 ⇒ 收益上限很低。

### 3.5 Option E（**否决**）—— 检查请求委托 LAN 桌面端代理（原 Q2-B）

**否决理由**：新增桌面端点 + 缓存 + 一层"信任 LAN 内任一主机"的信任面，换来的只是"桌面网络可能更稳"这一**未经证实的假设**（桌面同样可能被墙，除非挂了代理）；而真正需要更新的场景（通勤/异地只带手机）恰恰是**桌面不在线**时，该方案在那时退化回 Option A。

---

## 4. Decision Outcome

### 4.1 四条锁定决策

| 编号 | 决策 | 内容 |
| --- | --- | --- |
| **Q1-A** | 切口 | **只做「版本检查 + 提示」**，不做应用内下载与安装唤起 |
| **Q2-A** | 真相源 | **GitHub Releases API**（`/repos/ROM4n2/DeLector/releases/latest`）为**唯一**真相源；不可达时明确告知，**不得伪装成"已是最新"** |
| **Q3-A** | 调用位置 | **后端端点** `GET /api/update/check` 代查（超时 + TTL 缓存 + 规约），**非**前端直连 GitHub |
| **Q4-A** | 时机与打扰 | **启动后延迟自动检查 + TTL 缓存**；仅落后时显示可点 chip；无新版或检查失败**均静默**（失败仅在手动手动检查时给人话原因）；另留手动检查入口 |

**附带默认（用户未反对，随本 ADR 生效）**：

- 点击 chip 跳 **GitHub Release 页面**（`html_url`，人可见、含四平台产物与说明），而非 APK 直链。
- 顶栏 `System · vX.Y.Z Online` 改为**真实版本 + 真实检查结果**（消灭"永远 Online"的假状态）。
- 桌面端与 Android 端**共用**该端点与 UI（桌面刷新即生效，但"存在新版"对桌面同样有意义）。
- **手动下载 + 覆盖安装永久保留为一级退路**（不是兼容模式）。

### 4.2 端点契约（草案，落地时以行为探针冻结）

```jsonc
// GET /api/update/check
// 200 —— 成功（无论有没有新版）
{
  "current": "5.16.0",          // 来自版本单一真相源
  "latest": "5.17.0",           // null 当检查失败
  "has_update": true,           // true | false | null
  "page_url": "https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0",
  "checked_at": 1759900000,     // epoch 秒（缓存写入时刻）
  "cached": false,              // 是否命中 TTL 缓存
  "error_reason": null          // null | "network" | "timeout" | "rate_limited" | "not_found"
}
```

**关键不变式（MUST，行为探针钉死）**：

1. `has_update === null ⇔ error_reason !== null` —— 「**没查到**」与「**已是最新**」在契约层必须可区分。
2. 检查失败**不得**返回 `has_update: false`（伪装成最新是本次要消灭的缺陷类型）。
3. `current` 必须来自**单一真相源**（见 §6.1），不得在端点内硬编码版本串。
4. `has_update` 判定用 **versionCode 语义**（`major*10000 + minor*100 + patch`，红线 4），不得用字符串比较。

### 4.3 安全与闸门

- `/api/update/check` **不挂 `_require_localhost`**：这是**显式决定**，理由是 LAN 浏览器版用户同样需要更新可见性；它只读、不写数据、不出网以外无副作用。代价：LAN 设备可消耗主机 GitHub 配额 —— 由 **TTL 缓存**（建议 6h）与出网超时（建议 3s）共同兜住。**该决定 MUST 与本 ADR 同处可查**，避免将来被当成漏网重审。
- 端点内**不得**引入任何写入、不得记录外网响应到 DB。
- 红线 9 不受影响：仅在端点被调用时联网，import 期仍不联网。

---

## 5. Consequences

### 5.1 正向

- 消除唯一被证实存在的瓶颈（盲区），且**零 Android 权限变更、零新依赖、零 APK 结构变化**。
- 顺带修掉 `System · vX.Y.Z Online` 的假状态（一个长期存在的认知噪声）。
- 判据可在 pytest / 行为探针里真跑（T1），并把 GitHub 限速、CORS、墙的不确定性全部隔离在服务端（T3）。

### 5.2 负向 / 代价

- **新增一个出网端点**：必须实现超时 + TTL 缓存，否则每次进前端都打 GitHub（限速 60/h）。
- **一天一版时"可更新"可能长期挂在界面上**：由 U2（无新版静默）+ 手动可关闭/忽略的 chip 设计缓解；若实际造成提示疲劳，后续可加"忽略此版本"（本 ADR 暂不做，避免过度设计）。
- **仍无法根治"墙外真相源不可达"**：GitHub 不可达时用户依旧不知道落后。这是 Option E 被否决后接受的代价。

### 5.3 中立 / 将来钩子

- 若将来确要升级到 Option B（应用内下载），本 ADR 的 Option B 章节已记录必须的信任锚与全部新增失败路径，需**另开 ADR**，不得悄悄增量。
- `EXPECTED_SHA256`（`build-release.yml:380`）在 Option B 之前**没有运行时用途**，保持现状。

---

## 6. 落地要点与验收

### 6.1 前置依赖（MUST 先解决）

**后端当前没有版本单一真相源**（全仓无 `__version__`，版本散落在 `index.html` / `sw.js` / `build.gradle` 多表面）。若直接在新端点里硬编码 `"5.16.0"`，就是把 v5.16.0 刚修掉的"判据写死"缺陷原样再造一次（T4）。

⇒ 落地第一步：建立**一个**版本常量（例如 `delector/core/version.py` 的 `APP_VERSION`），并让检查端点与既有版本表面（`sw.js` cache 名、`index.html` 指示、`build.gradle` fallback）与之保持一致，另加守卫防漂移。

### 6.2 验收判据

| 类型 | 判据 |
| --- | --- |
| 行为（探针） | 网络成功 + 有新版 → `has_update: true` 且 `page_url` 为 Release 页；网络成功 + 无新版 → `false` 且静默；网络失败 → `null` + `error_reason` 非空，**绝不为 `false`** |
| 行为（探针） | TTL 内二次调用命中缓存（`cached: true`），且**不发出**第二次外网请求（可注入计数器断言） |
| 契约 | `has_update === null ⇔ error_reason !== null`（不变式 1）双向断言 |
| 静态/守卫 | 端点源码内**不含**硬编码版本串；`current` 来自版本常量 |
| 前端 | 失败时主文案是人类可读原因，不含 `HTTP <code>` 直出；无新版时无任何提示 |
| 回归 | 既有五条守卫（防漏接线 / 契约冻结 / localhost 集合 / 带写 GET 白名单 / CI 必需运行时）全绿；本端点不进 localhost allowlist 是本 ADR 的**显式决定** |

### 6.3 明确 NOT doing

- ❌ 应用内下载 APK、唤起安装器、`REQUEST_INSTALL_PACKAGES`、FileProvider、`DownloadManager` 分流
- ❌ 静默安装（平台不允许，不是取舍问题）
- ❌ 自建更新服务 / 差分更新 / 恢复三 ABI
- ❌ 前端直连 GitHub API（Q3-B）
- ❌ 热更新 `static/`（Option D）
- ❌ 检查请求委托 LAN 桌面端代理（Option E）
- ❌ 自动安装 / 自动下载

---

## 7. 实施记录（2026-10-08）

### 7.1 交付物

| 层 | 交付 |
| --- | --- |
| 版本真相源 | `delector/core/version.py`（`APP_VERSION` + `version_code()`，叶模块零 import） |
| 守卫升级 | `tests/test_writer_mobile.py` 两条发版守卫基准从"三面互等"改为"每面 == `APP_VERSION`"；顺带修掉 `tools/vault-proactive-scan.py:260` 的**真 bug**（原正则要求 `,` 分隔而实际是 `?:` ⇒ 永不命中，该脚本的版本一致性判定实际只覆盖两端，靠 `len(versions) < 2` 恰好躲过 WARN） |
| 端点 | `delector/routes/update.py` + `__init__.py` 三处挂载（`main.router` 之前） |
| 契约守卫 | `tests/test_update_check_endpoint.py`：穷举 iff 双向（4 类 error_reason + 2 类成功态）、结构证不写库（AST：无 sqlite3/aiosqlite/`delector.core.database` 前缀、无写动词字面量 SQL）、无本机闸 |
| 前端 | `static/js/update.js`、`static/index.html` chip 锚点、`static/js/main.js` 接线、`static/style.css` |
| 行为探针 | `tools/wb_update_chip_probe.mjs`（11 场景）+ `tests/test_update_chip_ui.py` |

### 7.2 实施中据实修正的两处决策细节

1. **§4.1 附带默认被**收窄**（重要）**：原文写"顶栏 `System · vX.Y.Z Online` 改为真实版本 + 真实检查结果"。实施时发现该静态串是**用户判断"前端资源刷没刷新"的唯一肉眼指标**（`tests/test_writer_mobile.py:75-79` 记录了 v4.4.5 漏 bump 的事故）。若改成由 `/api/version` 动态渲染，该指标立刻失效（服务端版本只反映**后端代码**，证明不了前端资源是否刷新）。⇒ 裁决：**静态 `System · vX.Y.Z` 保留**并由守卫继续钉死等于 `APP_VERSION`；只去掉在单机回环下**字面撒谎**的 `Online`；动态更新状态**只**由新 chip 承载（`#update-chip`）。
2. **chip 的 DOM 位置是被守卫倒逼的**：`tests/test_writer_mobile.py:96` 的正则锚定 `System · vX.Y.Z</span`，所以 chip 必须做成**兄弟元素**而**不能**插进版本号与其 `</span>` 之间（否则该守卫立刻失配）。此约束已写进 `static/index.html` 的注释与本文档，避免后人"顺手"挪动。

### 7.3 实际验证与剩余未验证

- **已验证（桌面侧真实出网）**：`_fetch_latest_release(3.0)` 成功取到 `tag_name=v5.16.0`（4.04s），`check_for_update()` 真实返回 `has_update=false`（当前 = latest）；缓存真实路径正确（首调出网、二/三调 `cached=true` 且 `checked_at` 保持原值、TTL 21600s、计数出网 1 次）。**注意** `_HTTP_TIMEOUT=3.0` 是 httpx **各阶段**超时而非总时长，实测总耗时 4.04s 仍成功。
- **仍未验证（阻塞，需真机）**：① **Chaquopy 上 httpx 能否完成到公网 `api.github.com` 的 HTTPS**（`delector/routes/encounter.py:381` 的手机出网是**手机→桌面的 LAN HTTP**，不能作为公网 TLS 可用的证据）；② **Android WebView 点击 chip 外链是否被交给系统浏览器**（若被吞，需改 `MainActivity` 的 URL 拦截，而 Java 侧本机无 Android SDK ⇒ 只能靠 CI 验证）。二者任一失败都会改变本 ADR 的可行性判断（可能需重议 Option E）。
- **⏸ 状态（2026-10-08 用户裁决）**：**Android 侧验证暂缓**。**桌面端已可用并已上线 master**（端点 + chip + 桌面侧真实出网验证通过）；**Android 端能力仍未验证，不得记为"双端已验证"**，执行台账 `Task 6` 保持 `blocked`。恢复时按上面①②逐条真机确认。
- **未做**：发版（发布面五件套未动，README 未 bump）。

---

## 8. 关联

- **上游**：本 ADR 由 `/dfs-grill` 双镜拷问产出（`product-ux` 镜头：瓶颈定位在"不知道有新版"；`sre-resilience` 镜头：实核 manifest / workflow / MainActivity，给出 Option B 的信任锚与失败模式清单）。
- **相关**：`docs/agents/architecture.md`（Android 独立单机版一节）、`docs/agents/ops.md`（打包与真机点检）、红线 4（versionCode 编码）、红线 6（缓存闸）、红线 9（import 期不联网）、红线 11（跨边界契约须行为探针验证）。
- **知识**：vault `08-Projects/DeLector/POST-MORTEM-V5.5.2-VERSION-NUMBER-SCATTER.md`（版本号散布必漏改 ⇒ §6.1 的依据）。
