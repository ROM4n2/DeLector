# ADR-0033: 把 Python 从首屏关键路径上彻底拿掉——宿主原生静态承载 + 快照首屏、后端只做数据接管

- **状态**：Proposed（待批准，未实施）
- **日期**：2026-11-10
- **决策者**：席皓宇 (Haoyu Xi)
- **关联 ADR**：
  - [[0032-python-off-first-screen-path]]（缓存优先 + store + 就绪重试；本 ADR 是它的叠加与阶段三的提前兑现）
  - [[0031-python-import-migration]]（方案 A / B 判负；本 ADR 不重走启动期搬移）
  - [[0018-performance-measurement-before-runtime-swap]]（先测量、再换运行时）
  - [[0021-stay-on-python-language-choice-criteria]]（语言选择以运行时/交付为判据；本 ADR 不换语言）
  - [[0020-windows-desktop-shell-pywebview]]（桌面壳边界：pywebview + Python 进程；本 ADR 不换壳）
  - [[0019-windows-desktop-pwa-first-and-data-dir-externalization]]（桌面交付边界；不新增安装包）
  - [[0008-go-agent-runtime-architecture]]（Go 侧现状的唯一依据；本 ADR 不扩大 Go 职责）
- **关联计划**：
  - `docs/plans/2026-11-09-first-screen-store-and-cache.md`（阶段一/二，已交付）
  - `docs/plans/2026-11-10-android-local-shell.md`（安卓壳页，已交付；本 ADR 的基线数字来源）

---

## 1. 决策

> **首屏（页面本身 + 首帧所需数据）由宿主承载，Python 只做后台数据接管。**

具体含义：

1. **页面与静态资源不再由 Python 提供**：安卓由 WebView 在宿主侧直接交付 APK 内的 `assets/static/`（与仓库 `static/` 同一份，已受资产指纹闸守卫）；Python 只提供 `/api/*`。
2. **首帧数据不向 Python 要**：文章列表 5 键全部来自本地快照（内置快照或 `localStorage` 副本），真实列表在 Python 就绪后静默接管。
3. **Python 不再挡在任何一次导航之前**：页面加载时机与 Python 启动解耦，就绪重试（PR #329）从「防御性兜底」升级为**首屏接管的主路径**。
4. **NLP 仍只在 Python**：本 ADR 不迁移语言、不改 API 语义、不把句法树/CEFR 计算搬到别处。

### 1.1 桌面端的边界（必须先说清）

桌面壳是 pywebview（ADR-0020），**Python 运行时本身就在首屏链路上**（窗口由 Python 创建）。因此桌面端本 ADR 能达到的是「**Python 后端 app（FastAPI/uvicorn）撤出首屏**」，不是「Python 运行时消失」；后者需要换壳或先起一个非 Python 的可执行体，超出本 ADR 与 ADR-0019/0020 的边界。

**结论：本 ADR 的「彻底」指首屏不依赖 Python 后端；桌面端按此口径判定，不按「无 Python 进程」判定。**

---

## 2. 已知事实（引用既有实测，不重测）

### 2.1 安卓（x86_64 模拟器 `Medium_Phone_API_37.0`，**真机未覆盖**）

| 指标 | 数值 | 口径/来源 |
| --- | --- | --- |
| 首个可见内容帧 M1 | **1361.5ms** | 自包含壳页（PR #330，merge `6d38ddf`）；`docs/plans/2026-11-10-android-local-shell.md` §8C |
| TTFD（首条 `.article-row` 首次绘制） | **4301.5ms**（同会话基线 4105.5 / 4136.5） | 同上 §8B；进程零点（`Process.getStartElapsedRealtime`） |
| Python 首行 → uvicorn 监听 | **2147ms**（2119–2157），占首帧全过程 **53%** | 同上 §8B 分段表 |
| `loadUrl` → WebView 主框架 commit | **630ms**（602–669） | 同上；S1 只能提前开始，不能消除 |
| 壳页 `loadUrl` 时点 | `python_start_done`（1127.5ms）之后 | 立即加载会与 Chaquopy 抢 CPU，实测 TTFD **+95.5ms** |
| 阶段一缓存提前量 | **24.5ms**（22–39） | ADR-0032 §9；页面在服务就绪后才加载，缓存/真实数据几乎同时 |

改造前的安卓时序（可核对代码）：`onCreate` → 后台线程 `initAndStartServer()`（资源拷贝 → `Python.start()`，`python_start_done`）→ `loadShell()` → 壳页首内容帧（M1）→ 就绪轮询通过 → `loadUrl(真实页)` → TTFD。

### 2.2 桌面（Win11 / R9 8945X / Py3.11.8）

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| `import delector.server` | **1153ms**（分支值） | 服务可响应 **~1341ms** |
| 阶段一「缓存首帧」 | **615ms**（610–709，进程零点） | **测量条件是独立 gateway 提供静态页**，非生产桌面壳 |
| 阶段一「真实数据接管」 | **4161ms**（3738–4310） | 同上（快速拒绝 + 就绪重试路径） |

**口径警告**：生产桌面壳（[desktop.py](file:///d:/Code/DeLector/desktop.py) L756-794）是 `await_ready` 之后才 `main.load_url(...)`，因此 **615ms 不能当作生产桌面首帧**；生产环境「进程启动 → 首条文章行可见」的基线**尚未测量**（见 §9）。615ms 与安卓 TTFD 零点相同但承载条件不同，**不可比**。

### 2.3 已判负、不再重走的路

- ADR-0031 方案 A（import 后移）：桌面首次点词 +905ms，双指标不可抵消。
- ADR-0031 方案 B（seed 后移）：安卓 TTFD 最好 −61ms、合并样本 +52ms，天花板 72ms。
- 安卓并行预初始化 WebView：prestartup 负结果已记录，TTFD 无稳定收益（ADR-0032 §7 C）。

---

## 3. 首屏最小数据集（所有选项的分母）

打开首页到「首条文章行可见」，前端只消费 `GET /api/articles` 返回的**每行 5 键**：

| 数据 | 字段 | 来源 | 首帧是否需要实时算 |
| --- | --- | --- | --- |
| 行标识 | `id` | `articles.id`（DB 列投影） | 否 |
| 标题 | `title` | `articles.title`（DB 列投影） | 否 |
| 创建时间 | `created_at` | `articles.created_at`（DB 列投影） | 否 |
| 字符数 | `char_count` | SQL `length(raw_text)`（DB 内计算，非 NLP） | 否 |
| CEFR 统计 | `stats.cefr_counts` / `cefr_percentages` / `word_count` / `est_reading_minutes` / `recommended_level` | `stats_json` 小列：**ingest 时算好并落库**，列表路径只投影、不解析 `processed_json` | 否 |

依据：`delector/routes/articles.py` L106-144 的列表实现与 P1-6 注释（2000 行 × 36KB 基准：改前 945ms → 改后 9.5ms，99.6×）；`static/js/api-types.js` 的 `ArticleListItem` 五键契约；`static/js/reader.js` L243-273 只读 `title / created_at / char_count / stats`。

**结论**：

1. **没有任何首屏字段需要后端实时计算**；列表是纯读，每行约 200B。
2. 首帧数据只有两种**来源**：
   - **预置 4 篇**：可构建期/安装期导出（与 `PRESET_ARTICLES`、`preset_processed.json` 同源）；
   - **用户导入的文章**：只存在于本机 SQLite，**构建期不可知**，只能来自 `localStorage` 上次成功列表或后端。
3. 因此「构建期导出」不能单独撑起首屏：它只解决首装 4 行与快照漂移；**真正卡首帧的是「页面由谁交付」**，不是数据计算。
4. 不需要为首页加载的（不得混入分母）：`/api/settings`（安卓就绪探针用，非渲染必需）、`/api/cards`、`/api/progress/stats`、`/api/exams/catalog`（模块徽标，异步）、`/api/companion/*`、`/api/articles/{id}`（含 NLP，首次打开文章才用）。

---

## 4. 选项对照

### 4.1 A. 构建期/安装期预计算导出

| 项 | 内容 |
| --- | --- |
| 做法 | 构建期从 `PRESET_ARTICLES` + `preset_processed.json` 生成列表快照（建议生成 JS 模块，避免首帧多一次网络请求），`static/js/article-seed.js` 改为消费生成物；安卓同步脚本随 `static/` 一起带进 APK。 |
| 改动面 | `tools/` 新增生成脚本；`static/js/article-seed.js` 变为生成物/薄包装；`tools/sync_android_sources.py` 重新生成并纳入指纹；`tests/test_articles_list_contract.py` 增加「生成物 == 契约」断言。 |
| 收益上限 | 消除「内置快照 vs DB 预置」双源漂移与首装 4 行正确性；**对 TTFD 单独贡献 ≈ 0**。安卓实测缓存相对真实数据的全部可拿量只有 24.5ms（页面已在屏前提下），A 不改变页面交付方。 |
| 风险 | 生成物进 `static/` 会改变资产指纹：若不同步重跑 `sync_android_sources.py`，`--check` 直接变红（这是特性，不是误报）；生成脚本与 DB 常量的字段漂移需契约测试兜住。 |
| 不可逆点 | 无；退回手写快照即可。 |

**判定**：单独不达标（收益落在数据正确性，不落在首帧）；作为其余选项的**配套**保留。

### 4.2 B. 非 Python 的只读前置层

#### B0 先核实 Go 侧现状（不假设）

| 事实 | 证据 |
| --- | --- |
| Go 是**伴学 Agent Runtime**，不是 Web 服务器 | `agent/internal/companion/server.go` L15-24：只有 `/api/companion/health` 与 `/api/companion/chat` |
| Go **由 Python 在 Python 之后启动**，不是首屏前置 | `start.py` L607-626：`main()` 里 `GoAgentSupervisor(python_port=port).start()`；失败即降级 Python 内核 |
| Go 二进制查找/构建都在桌面路径 | `delector/core/go_agent_supervisor.py` L104-156（`agent/delector.exe` 或系统 `go`） |
| **安卓侧没有 Go** | `android/app/build.gradle` 无 Go/gomobile 依赖；APK 资产只有 Python 源集与 `assets/static`、`assets/shell` |
| CI 的 `Go Gates` / `Go↔Python Integration Gate` 只构建/测试与验证链路 | `.github/workflows/ci.yml`；Go 端口 8001 还是保留端口（`start.py` L129） |

**结论**：Go 今天**不能**提供静态资源或 `/api/articles`。要让它当首屏前置层，需要「反转启动顺序 + 新增静态/proxy handler + 桌面包内随附二进制」；安卓要么引入 gomobile（新构建面、APK 体积），要么写等价的 Java 网关。本轮不采用。

#### B1 宿主原生静态拦截（安卓，推荐）

| 项 | 内容 |
| --- | --- |
| 做法 | `WebViewClient.shouldInterceptRequest` 在**应用自身 origin**（`http://127.0.0.1:8000/…`）上把静态请求（`/`、`/style.css`、`/js/*`、`/manifest.json`…）从 APK 的 `assets/static/` 直接返回；`/api/*` **不拦截**，走真实网络。Python 没起来时首个请求连接被拒，store 退避重试，就绪后静默接管。 |
| 为什么可行（已核对） | ① `assets/static/` 已由 `tools/sync_android_sources.py` 全量同步，并有资产指纹闸；② `index.html` 用绝对路径（`/style.css`、`/js/...`），与 assets 目录 1:1 映射；③ `core.js` 的 `api()` 用**相对路径** `fetch(url)`（L97-109），同 origin 下无需改 API 客户端；④ 就绪重试已在 PR #329 合入。 |
| 改动面 | 仅 `MainActivity.java`（+ 可单测的纯 Java 拦截映射类）；不新增依赖、不改构建脚本、不改 API、不改 DB；资产同步/指纹闸沿用。 |
| 收益上限 | TTFD ≤ 4301.5 −（assets 页首行绘制）。理论上界 ≈ **2.9s**（4301.5 − 1361.5）；工程目标 **≥1s**。 |
| 风险 | ① **最高风险**：页面与 Chaquopy 并行时的 CPU 争抢。既有实测只证明「壳页立即加载 TTFD +95.5ms」，**整页**未测；② 就绪重试在安卓真实冷启中从未当过主路径（此前是 CDP 人为拦截，非冷启证据）；③ 8000 被别的程序占用时 origin 与实际端口不一致，需回落到「等就绪再 loadUrl」；④ MIME/Cache 头映射错误会让 module script 不执行。 |
| 不可逆点 | 无。**必须保持 origin 不变**：换 origin 会丢掉该 origin 下的 `localStorage`（列表快照、主题、偏好），对既有用户不可逆。 |

#### B2 桌面壳内 stdlib 静态 + 反代（桌面，待测）

| 项 | 内容 |
| --- | --- |
| 做法 | 桌面壳先在同一端口起一个仅用 stdlib 的最小静态服务器（不 import `delector.server`），页面立刻可绘制；后台 import FastAPI/uvicorn，就绪后把 `/api/*` 反代给后端。保持端口/origin 不变，`localStorage` 不迁移。 |
| 改动面 | `desktop.py` 启动顺序 + 一个薄反代模块；打包脚本不变；无需 CORS。 |
| 收益上限 | 受「服务可响应 ~1341ms」约束，乐观上限 ≈ **1.2s**；但生产桌面壳的基线**未测**（§9），能否拿到 300ms 以上未知。 |
| 风险 | 反代要覆盖 SSE（伴学聊天）、下载导出、大请求体；与单实例锁/端口顺延的交互；「代理已起但后端未起」是新的失败形态。 |
| 不可逆点 | 无代码级不可逆，但反代一旦成为所有流量的单点，回滚需整体撤。 |

#### B3 原生网关（Java `ServerSocket`，不选）

同 origin 完整静态 + 反代，页面零改动；但要自己实现 HTTP 转发（含 SSE、下载、头部语义），代码量与风险显著高于 B1，且没有额外收益（B1 已保住 origin 与 `localStorage`）。**不选**。

### 4.3 C. 常驻服务（冷启变热启）

| 平台 | 评估 |
| --- | --- |
| 桌面 | 单实例锁已让「再次双击」复用运行中的服务（`start.py::claim_instance`）；这改善的是**重开**，不是**冷启动**。首次开机后启动仍要付 1153/1341ms。 |
| 安卓 | 前台服务可让 Chaquopy 进程保活，但需要常驻通知、耗电，且 Doze/厂商清理会杀；**首次安装、清数据、重启后仍是冷启**，2147ms 一分不少。新增生命周期与电池风险，换不到首屏指标。 |

**判定**：不是首屏方案，最多作为「重开」体验优化，另案评估。

### 4.4 汇总

| 选项 | 改动面 | 首帧收益上限 | 主要风险 | 不可逆点 | 本轮结论 |
| --- | --- | --- | --- | --- | --- |
| A 构建期导出 | 小（工具+快照+同步闸） | ≈0（只修数据正确性） | 双源/指纹漂移 | 无 | 作为配套 |
| B0 Go 前置层 | 大（启动反转+静态/proxy+打包；安卓另起炉灶） | 桌面 ≈1.2s；安卓需新构建面 | 新交付面、体积、维护 | 打包面变更 | 不采用 |
| B1 安卓静态拦截 | 中（仅 MainActivity + 测试） | **≈2.9s 理论上界，目标 ≥1s** | CPU 争抢、重试主路径未验证 | 无（保持 origin） | **推荐首先做** |
| B2 桌面 stdlib 静态+反代 | 中（desktop.py + 反代模块） | ≈1.2s（基线未测） | SSE/下载/失败形态 | 无 | 待基线测量后决定 |
| B3 Java 网关 | 大 | 同 B1 | HTTP 转发正确性 | 无 | 不选 |
| C 常驻服务 | 中（前台服务/桌面托盘） | 冷启为 0 | 电池/生命周期 | 无 | 不选 |

---

## 5. 与 ADR-0032 的关系：叠加，不替代

| ADR-0032 产物 | 新方案下的去留 |
| --- | --- |
| 薄 store + adapter（唯一后端知情点） | **保留**，且 B1/B2 的接管全靠它；不改契约 |
| 缓存优先渲染（`hydrateSnapshot` → 真实请求 → 回写） | **保留**，成为首屏唯一数据来源 |
| 就绪退避重试（PR #329） | **保留，并升级为主路径**：安卓不再「等就绪才 loadUrl」，首次请求天然可能被拒 |
| 双账度量（`articles-cache-first-paint` / `articles-data-ready`） | **保留**；本 ADR 另加 M1 与 TTFD 的独立记账 |
| I1（旧数据在屏必须有形状/图标 + 文案） | **保留**；「同步中 / 重试中 / 未连接」不变 |
| §4.1「先读本地快照」 | 不变 |
| §4.3 阶段三触发条件 | **部分提前兑现**：只搬「静态资源 + 只读列表」；NLP 仍留在 Python，触发条件对其余路径继续有效 |
| 「安卓等就绪再 loadUrl」（`MainActivity` 的 gate） | **废除** |
| 「静态页由 Python 提供」 | **废除**（安卓）；桌面按 B2 单独判定 |
| `assets/shell/boot.html` 自包含壳 | **已删除**（落地 PR）：`loadShell()` / `ShellBridge` / `WebViewAssetLoader` 调用链与资产一并移除，见 §14.7 |

**一句话**：ADR-0032 解决「数据先到不等后端」，ADR-0033 解决「页面先到不等 Python」；两者叠起来才是「首屏不碰 Python 后端」。

---

## 6. 不能重犯的错（写进判据）

> **任何候选只要把成本搬到用户的另一条路径——首次点词、首次分析、首次打开文章、首次编辑——即判不合格；不得用启动指标去抵消交互指标的损失。**

配套要求：

1. 每次判定必须**同会话成对测量**：启动账（TTFD / 首次可用）+ 首次交互账（首次打开文章、首次点词、首次分析、首次保存）。
2. 首次交互账的判负线：任一动作 **>50ms 且 >5%** 的回退即判负（沿用 ADR-0031 的双指标不可抵消原则，阈值按本项目交互量级收紧）。
3. 不接受「预热/预热后测」冒充首次交互；预热必须单列，且首测值本身仍要报。
4. 不允许用「另外一条路径变快」解释本条路径变慢。

---

## 7. 判据与判负阈值

### 7.1 分平台、分零点（禁止跨平台/跨零点混算）

| 平台 | 主指标 | 零点 | 采样条件 | 通过线 | 判负线 |
| --- | --- | --- | --- | --- | --- |
| 安卓 | TTFD（首条 `.article-row` 首次绘制） | 进程启动（与 `StartupProbe` TTFD 同源） | ≥5 次冷启 × 2 轮，`force-stop` + `pm clear`，报中位数与范围 | 中位数改善 **≥1000ms**，两轮方向一致 | 改善 <1000ms 或任一轮反向 |
| 安卓（辅助） | M1 首个内容帧 | 进程启动 | 同上 | 单列报告，**不计入** TTFD 收益 | 不适用 |
| 安卓（接管） | uvicorn 就绪 → 真实列表在屏 | uvicorn 监听成功 | 同一次冷启 | ≤1000ms，`navCount == 1` | 需要刷新/切页才算接管 |
| 桌面 | 首次可用（首条文章行可见，**生产壳**） | 打包壳进程启动 | ≥5 次冷启，报中位数与范围 | 先测基线，改善 **≥300ms** | 基线未测不得先实施 |

### 7.2 噪声与可比性

- 每组报中位数 + 范围；**run-to-run 极差即噪声下限**，小于噪声下限的差异不算收益（安卓导航零点已知噪声下限 63ms）。
- 零点不同不得同栏：桌面 615ms（gateway 条件）与安卓 4301.5ms（生产冷启）、安卓 M1 与 TTFD 均**不可比**；不可比就标「不可比」，不取平均。

### 7.3 附加硬判据

1. `navCount == 1`：不得靠刷新/二次导航拿到内容。
2. 首次请求被拒时，退避重试必须**无人干预**接管；预算耗尽必须落「未连接，显示本地快照」+ 可点重试，且首帧行仍在。
3. TTFD 不得回退 **>50ms**（B1 引入并行启动后重点盯）。
4. 旧数据在屏必须有 I1 痕迹（形状/图标 + 文案），不得只靠颜色。
5. 首次交互账不得触犯 §6。

---

## 8. 改动面、不可逆点与回滚锚点

### 8.1 预计改动面

| 阶段 | 文件/构建环节 | 是否触碰静态双源闸 | 是否影响 CI 打包判据 |
| --- | --- | --- | --- |
| S1（B1） | `android/app/src/main/java/org/delector/app/MainActivity.java`（+ 纯 Java 映射类）、`tests/test_android_webview_policy.py` 类静态断言 | 否（只读 `assets/static/`，同步与指纹不变） | 否（Android job 照旧 sync + assemble）；`Detect packaging-surface changes` 可能触发 Windows smoke，属预期 |
| S2（A） | 新生成脚本、`static/js/article-seed.js`（生成物）、`tools/sync_android_sources.py`、契约测试 | **是**（生成物进 `static/` → 指纹变化） | 否（`--check` 会在未重跑同步时变红，正是期望） |
| S3（B2） | `desktop.py` 启动顺序 + 薄反代模块 + 单测 | 否 | 是（桌面壳/打包面变化会触发 Windows Portable Smoke，属预期） |

### 8.2 不可逆点

1. **页面 origin 不可变**：B1/B2 都保持在 `http://127.0.0.1:<port>`；一旦换 origin（例如改用 `appassets` 虚拟域），该 origin 下的 `localStorage`（列表快照、主题、偏好）对既有用户永久丢失。**本 ADR 明确禁止换 origin**。
2. 无 DB 迁移、无 API 语义变更、无新增联网依赖。
3. 生成物（A）可随时退回手写快照。

### 8.3 回滚锚点

| 阶段 | 回滚动作 |
| --- | --- |
| S1 | 壳页已随落地 PR 删除，**不做部分回退**：要回到「等就绪再 loadUrl」需 `git revert` 整个 PR（拦截、提前导航、就绪钩子、壳页删除同进同出） |
| S2 | 恢复 `article-seed.js` 手写版，删除生成脚本（无运行时残留） |
| S3 | 恢复 `await_ready` 后再 `load_url`，撤掉反代模块（单次提交回退） |

---

## 9. 未核实项与核实方法

> **2026-11-10 更新（S1 测量切片）**：B1 的安卓 TTFD/M1、真实冷启退避接管已实测并写进 §13 与 `docs/plans/2026-11-10-adr-0033-s1-static-intercept.md`；下表保留原始风险清单，其中「B1 收益」「真实冷启重试接管」两项已闭合，arm64 真机与桌面基线仍未覆盖。

| 未核实项 | 为什么不能推断 | 怎么核实 |
| --- | --- | --- |
| B1 的安卓真实 TTFD | 页面与 Chaquopy 并行，CPU 争抢幅度未知；既有 +95.5ms 只测了壳页 | 实现最小拦截后，`force-stop` + `pm clear`，≥5 次 × 2 轮，读 `StartupProbe` 的 TTFD/M1，同会话与当前基线对照 |
| 真实冷启下重试能否无人干预接管 | 此前证据是 CDP 人为拦截（已标注非冷启证据） | 首帧出现后观察 `/api/articles` 首次失败 → 退避 → 就绪后接管；记录请求次数、`navCount`、接管耗时；预算耗尽场景单独跑一次 |
| 生产桌面壳首次可用基线 | 615ms 是 gateway 条件，生产壳 `await_ready` 后 `load_url` | 打包 exe 冷启，用 `desktop.py` 的 `loaded` 事件与页面 mark，零点=进程启动；不得拿 gateway 数字代填 |
| 桌面 B2 的收益是否 ≥300ms | 受 1341ms 服务就绪约束，窗口/页面成本未测 | 先测基线；再看静态服务器可提前多少；不达标即判负 |
| 8000 被占用时的回落行为 | 未构造该场景 | 占用 8000 后冷启，验证是否回落「等就绪再 loadUrl」且不出现错误 origin |
| arm64 真机 / 低端机 | 本机 `adb devices` 为空，无真机 | 明确写「未覆盖」，不做外推；有真机后按同一脚本复测 |
| WebView 拦截对 module MIME/缓存的影响 | 只在模拟器可验 | 用 CDP 看控制台与网络，断言 `text/javascript`、`no-store`/`no-cache` 行为符合预期 |

---

## 10. 分阶段最小路径（每阶段各自能拿多少、风险最高在哪）

### S1（安卓 B1）：页面从 APK 交付 + 快照首帧 + 就绪接管

- **做什么**：`shouldInterceptRequest` 把应用 origin 的静态请求映射到 `assets/static/`；页面加载不再等 `python_start_done`；`/api/*` 直连 Python；保留现有重试与 I1 痕迹。
- **能拿到**：TTFD 理论上界 ≈2.9s，工程目标 ≥1s；M1 单列。
- **风险最高项**：与 Chaquopy 并行加载整页的 CPU 争抢（可能吃掉一部分收益，甚至触发 §7.3 的 >50ms 回退线）。
- **停止条件**：若两轮中位数改善 <1000ms，直接写「安卓首帧收益不成立」，不进入 S3。

### S2（A 构建期导出）：快照单一来源

- **做什么**：生成预置列表快照并让同步脚本纳入指纹。
- **能拿到**：首装 4 行与 DB 预置不再漂移；不改首帧时序。
- **风险最高项**：生成物与 DB 常量字段漂移；由契约测试 + 指纹闸兜住。

### S3（桌面 B2）：生产壳的静态先到

- **前置条件**：§9 的生产桌面基线已测，且剩余可拿收益 ≥300ms。
- **能拿到**：桌面首屏不 import `delector.server`；上限 ≈1.2s。
- **风险最高项**：反代对 SSE/下载的正确性；失败形态「代理在、后端不在」。
- **否则**：明确写「桌面首屏收益由 ADR-0032 缓存层覆盖，进入 B2 不成立」，不硬做。

---

## 11. 不做（明确排除）

1. 换语言重写后端（Go/Rust 重写 Python 主体）；不把 Go 扩成 Web 服务器。
2. 改变 API 语义、DB schema 或数据目录。
3. 更换页面 origin（会丢 `localStorage`）。
4. 引入 bundler/前端框架/新运行时依赖。
5. 用前台服务/常驻进程冒充首屏方案。
6. 把 NLP（spaCy 句法树、CEFR 分级）搬出 Python 或提前到首屏。
7. 在未测生产桌面基线的情况下实施 B2。

---

## 12. 批准后第一步

只做 S1 的**测量切片**：实现静态拦截 + 解除「等就绪再导航」的 gate，先按 §7 的冷启口径出两组数字（TTFD / M1 / 接管），**不合并、不动桌面**；数字不达标即按 §10 停止条件判负并回退。

---

## 13. S1 测量切片结果（2026-11-10，x86_64 模拟器；真机未覆盖）

> 详细协议、逐轮明细与证明材料见 `docs/plans/2026-11-10-adr-0033-s1-static-intercept.md`。实现未提交、未合并。

### 13.1 数字（官方两轮 C/D，各 5 次冷启，0 弃跑，`force-stop` + `pm clear`）

| 指标 | 中位数 | 范围 | 极差 |
| --- | --- | --- | --- |
| M1 首个内容帧（进程零点，commit+1 帧） | **835.5ms** | 803–967 | 164ms |
| M1 首个内容帧（导航零点） | **350.5ms** | 334–388 | 54ms |
| TTFD（进程零点，与 `TTFD_FIRST_ARTICLE_MS` 同源） | **1065ms** | 1053–1232 | **179ms** |
| TTFD（导航零点） | **588ms** | 558–647 | 89ms |
| 接管（进程零点） | **4238.5ms** | 4210–4406 | 196ms |
| 接管（导航零点） | **3769ms** | 3724–3851 | 127ms |
| 接管 − uvicorn 监听 | **1382.5ms** | 1368–1535 | 167ms |

- 噪声下限：TTFD 进程零点极差 **179ms**；小于它的差异不算收益。
- 每次冷启 `/api/articles` **5 条**资源条目：首次在导航 ~432ms 失败（4–29ms，连接被拒），退避间隔实测 **256/426/806/1610ms**，末次 200（305ms），随后 `articles-data-ready`。
- 接管全自动：`skip_reload` 1 条、无第二次 `loadurl`、**`navCount == 1`**；接管后 4 行、chip 空、无重试按钮。
- 预算耗尽（CDP 人为挂起，**非冷启证据**）：14s 落「未连接，显示本地快照」+「重试」，首帧 4 行仍在；点重试后 16.0s 接管，无重新导航。
- 白屏/露底：6 帧连续抓取（~0.33s 间隔）只见「系统启动图 → 原生 splash → 真实页」，未见空白帧；短于 0.33s 的闪帧未排除。
- 解耦确认：导航在进程 ~450ms 开始，`python_start_begin` 在 ~950ms。

### 13.2 判负核对

| 判负项 | 结论 |
| --- | --- |
| TTFD 改善不足（1000ms 线） | 未触发（两轮中位数 1105 / 1062ms，均低于基线减 1000ms 的通过线；按口径不给跨构建差值） |
| TTFD 劣化 >50ms | 未触发 |
| 白屏/露底 | 未见（采样局限见上） |
| 接管需用户干预 / `navCount > 1` | 未触发 |
| 预算耗尽 UI | 通过（人为场景） |

**未闭合项**：`接管 − uvicorn 监听` 中位 **1382.5ms**，高于本文 §7.1 的候选 1000ms 线 382.5ms；根因是退避末档 1600ms 恰好跨过就绪点（末次失败 ~1920ms，uvicorn ~2870ms，重试落到 ~3530ms）。是否在下一步加「就绪信号触发一次立即重试」，待批准。

### 13.3 口径声明

- M1 与 ADR-0032 阶段一壳页 M1（1361.5ms）**不可比**（真实页 commit+1 帧 vs 壳页 3 次 rAF）。
- 本批 TTFD 与 #330 的 4301.5ms 只做阈值判定，**不报告差值**；不同零点不同栏、不取平均。
- A/B 两轮试点（各 5 次）因未采集 uvicorn 监听时点、接管零点无法对齐而整轮弃用；安装后首次启动作 warm-up 弃跑（ART/dex 首次预热）。
- arm64 真机未覆盖；8000 被占用的端口顺延场景未构造。

---

## 14. S2 结果：就绪信号重试 (b) + 同构建 TTFD A/B (a)（2026-11-10）

> 协议、逐轮明细与作废批次理由见 `docs/plans/2026-11-10-adr-0033-s2-ready-signal-and-ab.md`。实现未提交、未开 PR、未合并。

### 14.1 (b) 就绪信号驱动重试

- 信号源：Java `pollServerReadiness` 的 `/api/settings` 200（端口 8000）→
  `webView.evaluateJavascript("window.notifyServerReady()")`（页面已加载时）。
- 页面侧只调用 `articleStore.retryIfWaiting()`：取消**待触发**的退避 timer、`attempts+1`、立刻发下一次请求。
  **不新建 cycle、不改退避序列、不动在途请求**；用户可见的 `retryNow()` 与预算耗尽重试不变，
  没有第二套重试机制。
- 同钩子顺带**补注册 Service Worker**（见 14.2）。
- 归因：钩子在 `settings_200`（~3.0s）后执行，B 组 TTFD 中位 1034ms 全部早于它，**不影响 TTFD**。

### 14.2 Service Worker 与拦截层（上一轮漏答项，结论 + 实测验证）

- 拦截响应会被 SW 缓存，但 `sw.js` 是 network-first（`cache:"no-cache"`），拦截层 200 视为最新网络值
  覆盖缓存；只有网络失败才回落 Cache Storage。拦截响应另加 `Cache-Control: no-cache`。
- `/sw.js` **不在拦截白名单**，始终来自 Python（Android 上即 APK `assets/static` 解包后的同一份），
  `CACHE_NAME` 与资产同版本；APK 升级 → 重新解包 → activate 清旧缓存。**不会吃旧资产、不会被旧 SW 钉死。**
- 但 S1 引入了一个真实回归：页面先于 Python 加载时 `window.load` 的 `register("/sw.js")` 必然失败且被
  `.catch` 吞掉 → SW 永远注册不上，安卓离线能力静默丢失。**修复**：在同一个就绪钩子里补注册一次。
  实测：冷启后 `navigator.serviceWorker.getRegistrations()` = 1，scope `http://127.0.0.1:8000/`，controller=true。
- 测量期不禁用 SW：每次 `pm clear` 清空 SW 存储与 Cache Storage，A/B 同条件。

### 14.3 (a) 同构建 A/B：TTFD 正式判定

A = 旧行为（等就绪再导航、静态页由 Python 提供，`navCount=2`）；B = 新路径（提前导航 + 拦截 + (b)，`navCount=1`）。
同一 commit，仅一个编译期常量不同；常量已在测后整体删除。

| 组 | 进程零点中位 | 范围 | 导航零点中位 |
| --- | --- | --- | --- |
| A Round 1 | 3411ms | 3216–3607 | 406ms |
| B Round 1 | **1026ms** | 1010–1131 | 568ms |
| **改善 R1** | **2385ms** | — | — |
| A Round 2 | 3410ms | 3344–3539 | 389ms |
| B Round 2 | **1042ms** | 971–1227 | 579ms |
| **改善 R2** | **2368ms** | — | — |
| 合并 A / B | 3410.5 / **1034ms** | 3216–3607 / 971–1227 | 401 / 573.5ms |

- **噪声下限 391ms**（同组极差上限；轮间中位漂移 A 1ms / B 16ms）。改善是噪声的 6.1 倍。
- 两轮方向一致；每轮内 B 的 5 个样本全部快于 A 的 5 个样本（无交叉）。
- **判定：通过**（≥1000ms，两轮同向）。M1 单列（A 壳页 1077.5ms / B 真实页 805.5ms，仪器不同不可比），
  未用于抵扣 TTFD。

### 14.4 接管（B 组 10 次）

- `articles-data-ready` − uvicorn 监听：中位 **80.5ms**（45–132），**≤1000ms 通过**。
- 每次 5 条 `/api/articles`（初始 1 + 退避 3 + 就绪钩子 1），`ready_notify=true` 10/10；
  `skip_reload=1`、无二次导航、**`navCount == 1`**、4 行、无重试按钮。
- 机制说明：末档 1600ms 被就绪钩子提前打断，否则下一次尝试在就绪后约 +1.6s。该 +1.6s 为代码路径推断，
  不是对照实测；**不与 S1 的 1382.5ms 相减**。
- S1 §13 的未闭合项（接管 1382.5ms > 1000ms）**在本切片闭合**（同口径接管中位 80.5ms）。

### 14.5 首次交互（只测「首次打开文章」）

- A 中位 119ms（37–140）、B 中位 23ms（22–24），B 快 96ms；**未触发 >50ms 且 >5% 的回退判负**。
- 首次点词 / 首次分析 / 首次编辑**未实测**（本次改动未触碰这些路径，且 A/B 用同一后端）。
- 单轮、顺序 B→A 未交替，A 偏慢的成因未核实，改善不作收益主张。

### 14.6 口径与限制

- 全部差值来自同批同构建 A/B；与 S1、#330 的数字不跨构建相减。
- 作废批次：首批在无头 + swiftshader 环境采集，绝对 TTFD 漂移到 3.8–12.4s 且缺导航零点列，整批弃用；
  换窗口模式重测后 B 的 TTFD（1034ms）与 S1（1065ms）一致。
- arm64 真机、低端机、8000 端口顺延场景：未覆盖，不推断。
- 白屏与预算耗尽 UI 本切片未重测（渲染路径与 `retryNow` 未改），S1 结论继续有效。

### 14.7 落地 PR：壳页死代码清理

S1 起壳页只作「防回归兜底」，但代码里已无调用点（`onCreate` 直接导航真实页）。落地 PR 一并删除：

| 删除项 | 原因 |
| --- | --- |
| `MainActivity.loadShell()` + `SHELL_URL` / `ASSET_DOMAIN` | 无调用点 |
| `assetLoader` 字段、`WebViewAssetLoader` 初始化与拦截分支 | 唯一用途是壳页虚拟 origin |
| `ShellBridge`（`ShellHost`）与 `shell_frame` 探针标记 | 只服务壳页的首内容帧回报 |
| `android/app/src/main/assets/shell/boot.html` | 3.3 KB，全仓无引用 |
| `androidx.webkit:webkit:1.10.0` | 删除 `WebViewAssetLoader` 后无引用 |

验证：`loadShell|SHELL_URL|ASSET_DOMAIN|assetLoader|ShellBridge|ShellHost|shell_frame|loadurl_shell|boot\.html|assets/shell|WebViewAssetLoader` 在 `android/`、`static/`、`tests/`、`tools/` 零命中；`assets/static` 同步指纹不变（`sync_android_sources.py --check` 通过），打包面只少 `assets/shell`；
测量开关 `LEGACY_READY_GATE` 在最终代码中不存在。

**代价**：回滚不再能做单文件部分回退（见 §8.3），整份 PR 同进同出。
