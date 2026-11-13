# 更新日志 (Changelog)

> 本项目**版本历史的正主（single source of truth）**：每次发版在此追加条目。
> 桌面 / Android 四平台发布资产见 [GitHub Releases](https://github.com/ROM4n2/DeLector/releases)；
> 开发决策细节见 `docs/plans/archive/` 与 Obsidian Vault `08-Projects/DeLector/01-ADR/`。

<!--
格式规则（agent 与人类均 MUST 遵守；tests/test_release_docs_gate.py 机械校验 1-3 条）：
1. 降序排列：最新版本在最上。新条目插在本注释块之后、当前第一个 `## vX.Y.Z` 之前。
2. 每版固定结构：`## vX.Y.Z - YYYY-MM-DD` → `### 新增` / `### 修复` / `### 内部` / `### 文档`
   （按需，至少一个）→ `### 已知限制（Known Limitations）` → `### 回滚（Rollback）`；
   版本之间用一行 `---` 分隔。
3. 不使用 emoji；不写相对表述（如「上一版之后累积」），只写本版做了什么。
4. v5.22.1 及更早版本的小节标题保留历史格式，不要为了统一而重写历史正文。
5. README.md 的「版本历史」表只保留最近 3 版，旧版只进本文件。
-->

## v5.23.5 - 2026-11-13

### 修复

- **还原备份会抹掉并发写入**（2026-11-13 整体健康度审计 P1）：还原拆成 4 段独立事务，`_db_snapshot_guard` 的 `yield` 期间不持锁；任一步失败时整库回写快照，会把间隙里其它请求提交的合法写入（新存词卡、`PUT /api/wb/state`）一并抹掉。现在还原期间对所有 HTTP 请求置写屏障：新请求立即 503 + `Retry-After`（不排队），等在途请求排空后才开始；「检查屏障 + 登记在途」在同一把锁内原子完成，另加 owner 互斥保证同时只有一次还原，`finally` 无条件复位状态。
- **数据目录迁移静默重建空进度库**（审计 P1）：迁移闸只看 `delector.db`，新位置已有非空主库就提前放行，`progress.db` 被留在旧位置，`study_log` / `quiz_log` / `exam_trials` 在新位置重建为空。现在逐库判定，缺任一库即 fail-loud 并打印可复制的拷贝命令。
- **覆盖安装后可能跑旧前端资源**（审计 P1）：Service Worker 的 `networkFirst` catch 无条件 `caches.match`，会跨 cache 命中上一版本资源并当 200 交付。现在只从当前 `CACHE_NAME` 回落；导航请求仍回落应用外壳——实测 Android 首帧（≈0.5s）早于进程内服务就绪（≈1.4s），不回落会直接停在 `net::ERR_FAILED`。
- **写路径事务边界**（审计 P2）：wb 投影 `SELECT → INSERT`、FSRS 复习 `SELECT → 计算 → UPDATE` 补显式 `BEGIN IMMEDIATE`；跨 `progress.db` 写失败改显式 500，不再静默半写；11 处裸 `with get_db()` 改为确定性 `close()`。
- **导出失败不再假成功**：`exportAndReport` 外层补 try/catch，两个导出按钮的 click 链补 `.catch()`，失败一律走 `error` toast；写盘中途失败不再留下半截 JSON，500 的 detail 不再回传绝对路径。
- **Android 启动失败终态**：就绪预算耗尽后文案改为「…已停止连接。」并给出独立「重试」按钮——此前重试监听挂在 `setTextIsSelectable(true)` 的文本上，首次触摸被文本选择态吞掉，用户要点两下才生效。
- **首屏「句子解剖台」冷启动报「本地引擎暂不可用」**：页面约 2.9s 就绘制完成，而进程内 uvicorn 约 9.7s 才监听，窗口内 `/api/*` 全是网络层 `Failed to fetch`；该卡片此前失败只报错、不自动恢复。现在把「服务还没监听」与「服务回了错误」分开提示，并把待重试状态挂到宿主就绪钩子，服务就绪后自动补一次（不再要求手点重试）。
- **阅读页状态机**：占位标题不再被自身写回成永久「⏳ 载入中…」；503 退避定时器保存句柄并在切换文章 / `pagehide` 时撤销；消费后端 `processed_stale` 显示「分词正在升级」提示。
- **NLP 加载失败负缓存**：无下载加载失败后写 TTL 负缓存，TTL 内不再每个请求重跑三级回退。
- **运行时静默降级**：`.env` 不再覆盖显式注入的环境变量（`override=False`）；实例锁降级为无互斥句柄时打可见告警。

### 内部

- 新增机械闸：`requirements.lock.txt` 可解性（`pip install --dry-run`）、`master` 直推范围闸、发布侧验包硬截止与心跳、pytest 分片注册补齐、空扫描面退 2、CHANGELOG 格式规则 2。
- 判据从「字符串在场断言」改为行为探针：前端守卫 15 场景、模块图真链接整张图、wb 导出切片括号配平、Android 就绪策略；并补「删掉保护物必红」的变异自证。
- 新增 `tools/install_apk.py`：真机安装时自动点掉 MIUI 的 USB 安装确认页（否则 `adb install` 恒报 `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`）。
- Android 增加 **debug-only** 故障注入开关（`--ez delector_fake_stuck[_once] true`），用于点验启动失败终态与重试接线；release 包由 R8 折叠，不含该路径。
- 依赖：`pydantic 2.14.2→2.14.3` 且 `pydantic-core 2.50.2→2.50.4`（2.14.3 要求 core 精确 2.50.4，lock 同步；Android 侧仍用 `pydantic<2.0.0`，不受影响）。
- 删除跨进程量级比较的基准断言（同机相邻两次可差 2 倍，曾随机打红 `master`）、清理死代码、活文档版本/数字口径收口。

### 已知限制（Known Limitations）

- **Android 点检口径（本版实测）**：arm64 真机（Redmi Note 8 / Android 11）做了 `v5.23.4 → v5.23.5` 覆盖安装验证——不白屏、首页完整渲染、`ttfd` 3.6s、零 `FATAL` / `ERR_FAILED`、`ready_notify` 链路正常。**阅读页未在真机点开**：Android 侧文本导入受 `_require_localhost` 限制（设计如此），空库设备上没有可读文章；该页由 pytest 与 node 探针覆盖，**不算真机已验证**。
- **Windows 冻结 exe（本版实测）**：打包产物能启动、渲染桌面版界面、`/api/health` 返回 `nlp: ready`、`POST /api/wb/backup/save` 真实落盘（77 字节，内容与请求一致）。**WebView2 中点击导出按钮的链路未驱动验证**；导出主路径已不经浏览器下载（走服务端落盘），只有 blob 兜底才涉及 WebView2 的下载处理器。
- **覆盖安装后第一次启动仍是旧页面**：新资产在**下次启动**解包，而首次打开时页面可能来自上一版 Service Worker 缓存，界面仍显示旧版本（本次实测为 `V5.23.4`），需点「立即刷新」或再启动一次；全新安装不受影响。
- **macOS / Linux 未验证**（与历史版本一致）。
- **首页 LIVE 演示卡冷启动时可能显示「本地引擎暂不可用」**：页面首帧（≈3.6s）早于 Python 服务就绪（≈12s），该卡自动请求必然失败。**v5.23.4 在同一设备上表现完全相同**（已对照确认），不是本版回归；待下一版定位。
- **本地未跑全量 pytest**（按 2026-11-13 起的约束只跑对点）：README 徽章的 `3040 passed / 3054 collected` 仍是 **v5.23.4 时点**的实测记录，本版未复跑，不得当作本版实测。

### 回滚（Rollback）

- 代码回滚：`git revert` 本版合并提交，或检出 `v5.23.4` tag 重新打包。
- 数据面：本版只改事务边界与迁移闸，**无 schema 变更、无 DDL**，回滚不需要数据库迁移。
- 覆盖安装回滚：Android 上 `versionCode` 递减（52305→52304）会被系统拒绝，需 `adb install -r -d`（允许降级）或先卸载；**卸载会清数据**，优先用前者。

---

## v5.23.4 - 2026-11-11

### 修复

- **桌面壳导出「假成功」**（PR #344）：桌面版点导出时磁盘上没有文件，界面却弹「已导出」。根因是 pywebview / WebView2 默认不放行下载（`ALLOW_DOWNLOADS` 为假时 `DownloadStarting` 被静默取消），前端 `download()` 后无条件报成功。改为 `POST /api/wb/backup/save` 由 Python 显式落盘并返回真实 path / bytes，前端只在拿到 path 时提示成功；Android 仍保持 501 回退系统下载。
- **`requirements.lock.txt` 装不上**（PR #352）：两个依赖冲突让锁文件不可解——`numpy==2.5.4` 要求 Python>=3.12 而项目 `.venv` 固定 3.11，`pydantic-core==2.50.4` 与 `pydantic==2.14.2` 精确要求的 `2.50.2` 冲突。已分别回退到 `2.4.6` 与 `2.50.2`。

### 内部

- **批量依赖升级**（PR #351）：fastapi 0.162.0→0.162.2、click 8.5.0→8.5.1、typer 0.27.3→0.28.0、typing-inspection 0.4.4→0.4.5；`actions/cache` v4→v6（8 处）。六个 dependabot PR 合成一笔，避免逐个把 lock 文件整文件重写。
- **依赖治理**：`.github/dependabot.yml` 对 numpy 暂缓 minor/major（解除条件=项目最低 Python 升到 3.12）。dependabot 对 `requirements*.txt` 的单包升级不做整体一致性求解，CI 又只装 `requirements.txt`（不读 lock），因此合并此类 PR 前必须真跑 `uv pip install --dry-run -r requirements.lock.txt`。
- **新增守卫**：`tools/wb_export_probe.mjs`（5 场景，钉「无 path 不报成功」）+ `tests/test_wb_export_save.py`（6 用例）。

### 已知限制（Known Limitations）

- **桌面导出只在 `desktop.py` 实跑验证**：冻结后的 exe、真实磁盘写失败路径、macOS / Linux 均未验证。
- **arm64 真机仍未点检**：v5.23.3 的两处修复（阅读页模板、退出重进补载）只在 x86_64 模拟器（`emulator` 渠道 debug 包）验证；本版 Android 侧无功能变化，但含 `static/` 改动 ⇒ 仍需覆盖安装才生效。
- **本地测试环境有既有噪声**：本机全量为 3040 passed，另有 2 failed + 3 errors 属环境问题——`test_frontend_layers` 的 GBK 控制台解码，以及 `test_player_tray_probe` / `test_probe_json_contract`（在未改动的 master 上同样失败）。CI 上全部通过。
- **重复卡存量未合并**：写入侧已幂等，未建 UNIQUE，历史重复仍在库中。

### 回滚（Rollback）

- **代码 / 产物**：可回退至 `v5.23.3` 发布包（`v5.23.1` 白屏、`v5.23.2` 阅读页不可用，均不宜作为回退目标）；`build-release.yml` 由 tag 触发。
- **Android**：`versionCode` 由 `52303` 升至 `52304`，不可回滚；只能卸载重装旧 APK（会清应用私有数据，须先备份）；`versionCode` 不得回拨。
- **数据位置 / 格式**：未搬移数据目录、未改变数据文件格式。
- **Schema**：零 DDL、零迁移，旧版可直接读同一 SQLite。
- **配置 / 发布通道**：无新增必需配置或密钥；git revert 可回退代码。桌面导出改由 Python 落盘后，回退版本会恢复「导出假成功」的旧行为。

---

## v5.23.3 - 2026-11-11

### 修复

- **点开文章毫无反应：阅读页模板引用了已删除的变量**（v5.23.1 / v5.23.2 两版均带）。`static/js/reader.js` 的 `_readerStateHtml` 删掉 `const bar = ...` 后，模板里仍留着 `${bar}`，一进阅读页就抛 `ReferenceError: bar is not defined`；全局兜底弹一条提示后交互静默失效，用户看到的是「点了没反应」。模块本身能解析，所以 `node --check`、模块图守卫、前端桩探针全部看不见。修法：删掉该插值。
- **Android 退出重进后停在「Webpage not available」**。首帧导航发生在本地服务 listening 之前，Service Worker 的 network-first 用 `fetch` 取页面——SW 发起的请求**不经过** `shouldInterceptRequest`，因此拿不到 APK 内的静态骨架，直接以 `ERR_FAILED` 结束；Chromium 错误页的 URL 仍是应用 origin、且不会触发 `onPageFinished`，旧的「已在应用 origin 就跳过重载」判据把它当成加载成功，服务就绪后也不重试。修法：就绪信号注入后发现窗口里根本没有 `window.notifyServerReady`（即不是我们的页面）时再确认一次，仍没有就补载一次（一次性，防抖成循环）；同时把主帧加载失败记入 `mainFrameLoadFailed`，就绪后强制重载。
- 两处均用 x86_64 模拟器（`emulator` 渠道 debug 包）实测通过：首次启动、退出重进、点开文章渲染正文与 CEFR 光谱均正常。

### 内部

- 新增守卫 `test_reader_state_template_uses_only_declared_vars`：核对阅读页状态模板里 `${名字}` 形式的纯标识符必须在本函数内声明过（做过变异自证：把 `${bar}` 写回立即变红）。

### 已知限制（Known Limitations）

- **arm64 真机仍未点检**：本版修复在 x86_64 模拟器（`emulator` 渠道 debug 包）验证，正式 arm64-v8a 包只验证到「能构建、能发布」；覆盖安装后的真机表现未测。
- **模拟器包与正式包不同源**：`emulator` 渠道 `applicationId` 带 `.emulator` 后缀、含 x86_64 ABI，静态资源与 Python 代码同源但构建类型为 debug；结论不能等同于 release 包已验证。
- **SW 缓存可能短暂遮蔽新静态文件**：若启动瞬间服务未就绪，SW 会回落到上一轮缓存；本版靠「就绪后补载一次」恢复，但没有做「版本不一致即清缓存」的强制校验。
- **v5.23.1 / v5.23.2 应视为不可用版本**：v5.23.1 全平台白屏、v5.23.2 阅读页点开无反应；请使用本版。
- **重复卡存量未合并**：写入侧已幂等，未建 UNIQUE，历史重复仍在库中。

### 回滚（Rollback）

- **代码 / 产物**：可回退至 `v5.23.0` 发布包（`v5.23.1` 白屏、`v5.23.2` 阅读页不可用，均不宜作为回退目标）；`build-release.yml` 由 tag 触发。
- **Android**：`versionCode` 由 `52302` 升至 `52303`，不可回滚；只能卸载重装旧 APK（会清应用私有数据，须先备份）；`versionCode` 不得回拨。
- **数据位置 / 格式**：未搬移数据目录、未改变数据文件格式。
- **Schema**：零 DDL、零迁移，旧版可直接读同一 SQLite。
- **配置 / 发布通道**：无新增必需配置或密钥；git revert 可回退代码。

---

## v5.23.2 - 2026-11-10

### 修复

- **v5.23.1 全平台白屏：前端模块图在解析期即崩溃**。`static/js/article-store.js` 里 `RETRY_DELAYS_MS` / `RETRY_BUDGET_MS` / `isRetryableError` 被同时写成 `export const` / `export function` 并又列进文件底部的 `export { ... }`，触发 `SyntaxError: Duplicate export of ...`。ES 模块在**解析/链接期**就失败，`main.js` 一行都不执行，页面只剩静态骨架的文字块（Android 上表现为「退出重进后前端完全无法显示，只剩文字方框」）。桌面与 Android 同源同崩。
  - 修法：声明处去掉 `export`，公开面只在文件底部 `export { ... }` 列一次（保持该文件原有形态）。
  - 为什么 v5.23.1 发得出去：`node --check` 只做单文件语法检查、不解析 import/export 绑定；前端探针用桩模块替换真实 import 图；既有模块图守卫用 set 收集导出名、重复被静默折叠。三层都看不见重复导出。
- **新增机械守卫**：`tests/test_frontend_module_graph.py` 补两条用例 —— ① 结构化检查「同一符号是否被导出两次」；② 让 node 真 import 每个 `static/js/*.js`，把 `SyntaxError` / `ERR_MODULE_NOT_FOUND` / 缺失导出判为失败（浏览器专有全局缺失等运行期错误不计）。两条都做过变异自证：把重复导出写回去立即变红。

### 已知限制（Known Limitations）

- **v5.23.1 应视为不可用版本**：桌面与 Android 安装包打开后只剩静态骨架文字，请回退 `v5.23.0` 或安装本版；`v5.23.1` 的 tag / 资产保留用于追溯，不再推荐下载。
- **arm64 真机未覆盖**：本版含 `static/` 与后端改动，需覆盖安装验证；arm64-v8a 真机未安装、未启动、未点检。
- **Android 首开仍可能等待**：快退只在后台预热已接手加载时生效；若预热被 `DELECTOR_MODEL_PREWARM` 关闭或线程未启动，首次打开陈旧文章仍可能在请求内同步等模型加载。
- **本版未覆盖真实页面渲染回归**：仓库内没有浏览器自动化环境（无 Chrome/Playwright），修复后仅以「node 能解析并链接整张模块图」与本地服务 200 响应作为证据，未做像素级截图比对。
- **重复卡存量未合并**：写入侧已幂等，未建 UNIQUE，历史重复仍在库中。

### 回滚（Rollback）

- **代码 / 产物**：四平台可回退至 `v5.23.1` 或 `v5.23.0` 发布包；但 `v5.23.1` 为白屏版本，实际可用回退点是 `v5.23.0`。
- **Android**：`versionCode` 由 `52301` 升至 `52302`，不可回滚；只能卸载重装旧 APK（会清应用私有数据，须先备份）；`versionCode` 不得回拨。
- **数据位置 / 格式**：未搬移数据目录、未改变数据文件格式。
- **Schema**：零 DDL、零迁移，旧版可直接读同一 SQLite。
- **配置 / 发布通道**：无新增必需配置或密钥；git revert 可回退代码。

---

## v5.23.1 - 2026-11-10

> 注意：本版前端模块图在解析期即崩溃（白屏），请使用 `v5.23.2`。详见上一条的「修复」。

### 修复

- **阅读页把「尚未就绪」显示成「加载错误」（问题形态由 Android 真机点验定位；本版修复未在真机复验）**：页面进入速度已达标，但进入阅读页时文章正文与 spaCy 分词尚未就绪，界面直接显示加载错误。根因是文章详情首次 GET 会触发 `processed_json` 惰性迁移，在请求线程内同步等 spaCy 模型加载（Android 上数十秒），前端 fetch 超时后只弹一条「打开文章失败」。现在分三层处理：
  - 存在旧分词结果时先返回旧结果，并在响应里标 `processed_stale` / `nlp_state=loading`，用户立刻能读；
  - 无可用旧结果且后台预热已在加载时返回 `503 nlp_loading`（带 `Retry-After: 2`），前端显示「正在准备德语分词模型」并按有限退避自动重试，不再显示红色错误；
  - 退避预算耗尽或遇不可重试错误（404 / 权限 / 服务不可用 / 连接中断）时，正文区降级为带「重试」按钮的常驻提示，文案按状态码翻译，不再是一条会消失的 toast。
- **快速切换文章时的标题串台**：详情加载的占位标题改在 `finally` 中按打开令牌复原，后打开的调用不会被前一次覆盖。

### 内部

- **零副作用就绪探针**：`model_loader.get_nlp_readiness()` 只读返回 `state`（ready / loading / error / unavailable）与 `prewarm_started`，不触发加载、不下模型；`GET /api/health` 的 200 与 503 两个分支都带 `nlp` 字段。
- **快退边界只对预热生效**：仅当后台预热已接手加载时才 503——预热占着模型加载锁，请求同步等只是白占一个 worker；预热未启动（裸建 app 的测试、显式关闭预热）时仍走原同步惰性迁移，否则 single-flight 迁移通道会被挡死。
- **前端策略复用**：`article-store.js` 导出既有的退避常量与 `isRetryableError`，文章列表与详情共用同一份策略，不再各写一套。
- **新增行为锁**：`tests/test_article_readiness_fallback.py`（旧结果打标 / 503 快退 / 预热未启动仍迁移 / 就绪时不误伤）；`openReader` 守卫放宽为「notify 通知或正文区错误态」，try / catch / finally / 加载占位断言全部保留。

### 已知限制（Known Limitations）

- **arm64 真机未覆盖**：本版含 `static/` 与后端改动，需覆盖安装验证；arm64-v8a 真机未安装、未启动、未点检。真机不是发版前置，但不得记为已验证。
- **Android 首开仍可能等待**：快退只在后台预热已接手时生效；预热被 `DELECTOR_MODEL_PREWARM` 关闭或线程未启动时，首次打开陈旧文章仍可能在请求内同步等模型加载。
- **就绪等待时长未量化**：本版未在真机测量「未就绪到就绪」区间的实际耗时，只验证了不再显示错误且能自动恢复。
- **低端机 OOM 未覆盖**：无低端机设备，内存峰值未测量。
- **iOS 键盘态未覆盖**：无 iOS 设备与 Safari 环境。
- **重复卡存量未合并**：写入侧已幂等，未建 UNIQUE，历史重复仍在库中。

### 回滚（Rollback）

- **代码 / 产物**：四平台可回退至 `v5.23.0` 发布包；`build-release.yml` 由 tag 触发，回退不依赖分支。
- **Android**：`versionCode` 由 `52300` 升至 `52301`，不可回滚；只能卸载重装旧 APK（会清应用私有数据，须先备份）；`versionCode` 不得回拨。
- **数据位置 / 格式**：未搬移数据目录、未改变数据文件格式。
- **Schema**：零 DDL、零迁移，旧版可直接读同一 SQLite。
- **配置 / 发布通道**：无新增必需配置或密钥；git revert 可回退代码。回退后文章详情恢复「请求内同步迁移」的旧行为（能出内容但速度慢），不丢数据。

---

## v5.23.0 - 2026-11-10

### 新增

- **Android 冷启动静态壳（PR #330 / #331）**：首屏改为静态骨架先行、数据就绪后接管，就绪信号带退避重试。提交 6b829c6 记录的本机实测 TTFD 3410.5 ms → 1034 ms（同一测量脚本；arm64 真机未点检）。
- **桌面页面提前加载（ADR-0033 B2，PR #333）**：静态层先起、socket 交接、就绪钩子复位；同时修复 WebView2 持久化存储缺失导致的每次启动缓存空转。
- **App 内「已知限制」本地说明（#337）**：设置页新增随包发布的静态分组，说明存量重复卡与「共 N 张」口径、幂等命中反馈与「只补空不覆盖」；抽屉台账就地解释。脱网可见。
- **存卡反馈语义（#334 / #335）**：`POST /api/cards/vocab` 返回 `created` 与 `skipped_fields`；5 个前端入口在幂等命中时改显示「已在词卡中」、不再播放庆祝动画，字段被跳过时提示「本次填写未覆盖原有释义」。

### 修复

- **伴学落卡事务边界（#332）**：`update_proposal_status` 增加 `commit=False`，把「状态流转 → 查重 → 插入」收回同一个 `BEGIN IMMEDIATE`；`accepted` 不再先于插卡单独落盘，插入失败可重放。学习事件埋点移出写锁事务，避免跨库 I/O 占锁。
- **词卡身份归一与空 lemma（#332）**：新增行级 UDF `card_identity` / `card_lemma_key`，让参数侧与存储列共用同一空值回退；台账改走同一归一，旧库 `lemma=''` 行不再每次提交都长新卡。
- **台账注释口径（#332）**：改为「按 `lemma_key` 聚合的读侧视图，与写侧双列身份不同」，不再写「读写共用同一身份」。

### 内部

- **发布文档规范化（#336 / #338）**：CHANGELOG 版本头统一为 `## vX.Y.Z - YYYY-MM-DD`、版本间统一 `---`、已知限制/回滚升级为三级小节、顶部新增 FORMAT RULES；README 版本表钉住 ≤3 行；新增发布文档守卫 `tools/check_release_docs.py` 与 `tests/test_release_docs_gate.py`（10 例，unit-2 分片）。
- **Release 文案**：`build-release.yml` 正文移除每版重复的能力长列表，改为能力概览 + `FEATURES.md` 指针；新增 `.github/release-notes-template.md`（无 emoji、新增/修复/内部/文档 分类、已知限制 + 回滚四轴）。
- **审计收尾（#336）**：补记性能核验结论（2 万行临时库：查重 35.86 ms、台账 34.30 ms、普通索引对 UDF 无效），裁决本版不加索引。

### 文档

- `docs/agents/ops.md` 第 8/9 条改为降序插入规则与 Release 文案规范；清掉装饰性 emoji。

### 已知限制（Known Limitations）

- **arm64 真机仍未覆盖**：本版含 `static/` 改动（Android 静态壳、存卡反馈、已知限制文案），需覆盖安装验证；arm64-v8a 真机未安装、未启动、未点检。真机不是发版前置，但不得记为已验证。
- **低端机 OOM 未覆盖**：无低端机设备，内存峰值未测量。
- **iOS 键盘态未覆盖**：无 iOS 设备与 Safari 环境。
- **重复卡存量未合并**：写入侧已幂等，但未建 UNIQUE，历史重复仍在库中；读侧按「共 N 张」聚合显示，存量合并待真实重复统计。
- **大文章首次打开的重算可能阻塞**：`PROCESSED_JSON_VERSION` 3.6.0 的惰性重算仍在单篇 GET 内同步执行，10 万字符级约 4–5 s。
- **桌面提前加载与 WebView2 缓存修复未真机复验**：仅本机与 x86_64 模拟器点检。
- **性能结论的边界**：查重/台账耗时来自 2 万行临时库的 Windows 桌面实测，Android 低端机未测。

### 回滚（Rollback）

- **代码 / 产物**：四平台可回退至 `v5.22.1` 发布包；`build-release.yml` 由 tag 触发，回退不依赖分支。
- **Android**：`versionCode` 由 `52201` 升至 `52300`，不可回滚；只能卸载重装旧 APK（会清应用私有数据，须先备份）；`versionCode` 不得回拨。
- **数据位置 / 格式**：未搬移数据目录、未改变数据文件格式。
- **Schema**：零 DDL、零迁移，旧版可直接读同一 SQLite。
- **配置 / 发布通道**：无新增必需配置或密钥；git revert 可回退代码。

---

## v5.22.x 及更早（表格化）

> 2026-11-13 精简：**v5.23.0 及之后保留完整条目**（修复 / 内部 / 已知限制 / 回滚）；更早版本只留「版本 / 日期 / 里程碑」一行，里程碑直接复用各版原有小节标题。
> 完整原文（含各版「已知限制」「回滚」小节）没有删除，可 `git show <tag>:CHANGELOG.md` 或看对应 GitHub Release 取回。

| 版本 | 发布日期 | 里程碑 |
| :--- | :--- | :--- |
| **v5.22.1** | 2026-11-09 | 文章详情响应体去重（-57%） · Android 启动系列（TTFD 口径与 splash 根因修复） · 词卡写入幂等（部分修复） · 制度闸（把约定变成机械检查） · 文档与跨平台说明 |
| **v5.22.0** | 2026-11-08 | 发布收口：v5.21.1 之后累积的用户可见修复 |
| **v5.21.1** | 2026-11-03 | 伴学 SSE 跨 chunk 分帧修复（PR #199） · Go RunLoop 与 submitPrompt 内部重构（行为不变） |
| **v5.21.0** | 2026-11-03 | 伴学 Agent 页面级能力分区、HITL 生词提议闭环与跨页历史恢复 · 卡盒测验 choice 模式缺释义空白选项修复 · PWA 安装图标补齐 · 桌宠眨眼眼球错位修复与 README 产品图刷新（PR #197） |
| **v5.20.2** | 2026-11-01 | 自然段排版重塑 + CEFR 视力透视胶囊 + 句法抽屉实时联动同步与 CI 极限加速 |
| **v5.20.1** | 2026-11-01 | Android 桌宠拖拽手势修复 + 句法默认显示清除 + CI Pytest Matrix 矩阵提速 |
| **v5.20.0** | 2026-11-01 | 伴学导学 Agent 运行时 + SQLite 业务持久化 + 洋葱中间件与安卓可调工作台（PR #179） |
| **v5.19.0** | 2026-10-22 | 桌面单实例锁 + 端口顺延 + 前端继续解耦（PR #172 · #164~#166） |
| **v5.18.0** | 2026-10-19 | 架构与前端单体彻底解耦 + 交互式智能体闭环 + 六道自动化机械闸（PR #131~#161） |
| **v5.17.0** | 2026-10-11 | 首个原生桌面壳 + 首次数据落点外置 + 发版门（PR #111~#129） |
| **v5.16.0** | 2026-10-06 | 修掉一个长期潜伏的性能缺陷 + 三处守卫加固（PR #108/#109/#110） |
| **v5.15.0** | 2026-10-05 | 登记项收口第二轮：三条新守卫 + 降级串味修复 + LAN posture 裁决（PR #103~#107） |
| **v5.14.0** | 2026-10-05 | 韧性 / 前端竞态 / KARTEI 去复习化（swarm 审计 5 子计划 + 清债轮，PR #93~#102） |
| **v5.13.0** | 2026-10-03 | 统一词库池（ADR-0016）+ P0 数据真相修复（PR #73/#74/#75/#88） |
| **v5.12.1** | 2026-09-26 | 已发版内容（供参考）：Docker 数据目录迁移闸（fail-loud） |

---

## 路线图 (Roadmap)

- [x] **v1.0**：德语文章分词、欧标高亮与词汇卡片库

- [x] **v2.0**：Gutenberg Broadsheet 学术社论设计系统重构与 Edge TTS 神经伴读

- [x] **v2.1**：3D 物理扑克卡盒、Leporello Folio 三折风琴学术台账、三大考验自测模式

- [x] **v3.0**：智能完形填空实战引擎 (Lückentext / C-Test) + SuperMemo SM-2 艾宾浩斯排程

- [x] **v3.2**：前端原生 ES Modules 模块化拆分 + 歌德 A1-B2 核心离线词库 (0ms 查词)

- [x] **v3.3**：权威德语外刊 RSS 一键订阅与正文提取 (Tagesschau, DW, DLF, Spiegel, Zeit)

- [x] **v3.4**：556+ 强变化三态表 + 复合词智能拆解 + 框形可分动词双向联动高亮

- [x] **v3.5**：德语拓扑五场域 (Felder-Modell) 与 5 大从句 AST 句法树引擎 + 全局设置面板 (deepseek-v4-flash)

- [x] **v3.7**：德语伴读宠物（Eule & 伙伴）+ 自定义 SVG 角色工坊 + 严格 DOMParser 递归消毒

- [x] **v3.8**：FSRS 现代自适应记忆排程器升级（DSR 三维认知模型，消除 Ease Hell，4 级下一轮间隔预计算）

- [x] **v3.9**：离线词库 443→4300 词（DeepSeek 批量生成中文释义）+ 查词链 lemma 优先 / 形态学接线 / 现在时反查 / UX 诚实显示

- [x] **v3.9.1**：安卓真机修复——TTS 无声（stdlib 版 Edge TTS 客户端 `edge_tts_mini`）、倍速按钮点不到（移动端三行布局）、单词抽屉白色遮挡（55vh + 阅读区全宽）

- [x] **v3.10**：固定介词搭配（Verben/Adjektive + Präposition + Kasus）——数据集 **531 词条 / 660 条搭配**（AI 批量生成 + 人工 seed 兜底），查词抽屉第四张卡片逐条展示并可直接存成词汇卡；**备份改全量真往返**，堵住三处静默丢数据（含 API Key 被吞）；**安卓签名迁移**——CI 钉死 keystore + keytool 验签闸（显式 v1 签名），versionCode 编码规则修正（`major*10000+minor*100+patch`，修 3.10.0 与 4.0.0 撞车）

- [x] **v3.11**：**德语写作润色台 (Schreibwerkstatt)**——本地规则引擎（spaCy 上冠词/格位一致 + 介词支配格，零误报准则），行内下划线 + 侧栏纠错，错误一键存 Anki 语法卡（你的错误变成你的复习卡），essays 作文草稿库，CEFR 词汇估测，显式 AI 润色全文按钮；「按介词浏览」的独立矩阵视图留待后续（数据集已就位，零成本增量）

- [x] **v3.12**：写作台 IDE 化：句子级 diff 引擎 + AI 润色逐 hunk 并排审查 + `essay_versions` 类 git 快照管理 + 侧栏诊断/历史双 Tab 联动

- [x] **v4.0**：内联 IDE 编辑器（contenteditable + TreeWalker 光标记忆 + 400ms 实时诊断 + 悬浮气泡 + 一键修正 + 句子导航）+ 版本管理完善（只读预览不产生检查点 + 单项删除）+ 动词固定介词优先

- [x] **v4.1.1**：VSCode 级真实 Inline Inlay Hints（CSS `::before` 伪元素无 text node + 随文本推开 + TreeWalker 纯净正文 0 污染）

- [x] **v4.2**：Problems 问题清单面板（severity 分级 + 双格介词 warning + 联动定位/高亮/修正）

- [x] **v4.3**：Android/移动端写作台适配（bottom-sheet、触屏纠错、Android 默认关闭 Inlay Hints）+ **安全加固**：存储型 XSS 全量修复（`jsAttr`）、SSRF 加固、TTS 长度闸

- [x] **v4.4**：**可靠性与安全收口**——敏感设置/备份仅回环可写（局域网 403）、pre-commit 编码 keystore 拦截、CI 真 Gradle 构建与验签闸、写作零误报加固、备份/AI 失败回归；测试 **230 全绿**，仅 14 条 linguistics 重复键既有告警；词库 110 词缺口盘点（30 缓存待合入，80 需 API，401 暂缓，不伪造）

- [x] **v4.4.5**：**安卓升级后前端不更新根治**——覆盖安装不清 `filesDir` 而解包逻辑见文件已存在即跳过，旧前端永不被覆盖、新增文件却照常拷入，设备停在「新旧混合」状态（此前只能卸载重装）；改为按 `versionCode` 比对标记文件决定是否整目录重解包，删除范围硬编码校验以确保用户学习数据不受影响。缓存闸移到服务端 `Cache-Control: no-cache`，退役从未真正生效的 `?v=` 查询串与 `sw.js` 死清单。**写作台三 Tab 交互统一**：整行点击 = 定位/预览，行内按钮 = 破坏性操作，结果落在编辑器时自动收起移动端面板；测试 **238 全绿**

- [x] **v4.4.6**：**修顶栏版本指示灯** + **移动端写作台面板位移/底部滚不到根治**——v4.4.5 漏 bump `index.html` 顶栏 `System · vX.Y.Z Online`，使修好的升级链路看起来像没生效（拆 APK 验证：包内 `sw.js`、`writer.js`、去掉 `?v=` 的 `index.html` 全是新的，只有那一句字面量是旧的），版本自洽测试纳入该标签；移动端 `.writer-sidebar` 用 `position: fixed` + `bottom` 锚点却只给 `max-height`、没 `top` 也没 `height`，高度跟内容走而盒子锚在底边只能向上长 —— 切 tab、填错误卡、清单从空变 N 条都把顶边挪到新位置（三个 Tab 都在跳，诊断分析跳得最狠），改用 `height: min(76vh, 680px)` 固定几何；内层三个列表（220/460/320px）原本各自开滚动区在 600px sheet 里几乎占满可见区域、吃掉外层滚动，统一 `max-height: none; overflow-y: visible` 归 sheet 一人管；`.writer-pane` 补 `flex-shrink: 0` 防父容器压扁。测试 **239 全绿**

- [x] **v4.4.7**：**桌面端侧栏几何收口 + 三行触屏按压反馈**——v4.4.6 移动端修复的同族另一半：`.writer-sidebar` 基规则 `position: sticky; top: 4.5rem` 在 `align-items: start` 的 grid 列里高度跟内容走，既无 `max-height` 也无 `overflow-y`，内容一长就整列溢出、底部永远滚不到；改为内部滚动 + tab 条吸顶。三种可点击行（错误卡/清单项/版本行）补 `:active` 按压反馈——触屏没有 hover，此前按下去毫无回馈。测试 **242 全绿**

- [x] **v4.4.8**：**离线词库补齐 + SSRF 闸判定修正**——① 两处「AI 始终不作答」其实**AI 每次都答了**：提示词要求反身动词 `wort` 不带 `sich`，匹配器却按 `lemma not in asked` 把返回值丢掉；单词请求会让模型「纠正」成词元（问 `zustände` 答 `Zustand`）而词库按表层形查，于是任何屈折形必然连丢 3 轮。改为把答案回映射到请求键：搭配 **531/660 → 552/691**（零 API 花费），词库尾缺口 **110 → 0**。刻意不做变音折叠——`drucken`/`drücken` 会互相领走搭配，**张冠李戴比漏检更糟**。② SSRF 闸拿**外层 IPv6 旗标**判定，而 IPv4-mapped/6to4/Teredo 的真实目的主机是**内嵌的 IPv4**：`2002:c0a8:0101::1` 外层 `is_global` 为真却路由到 `192.168.1.1`（旧写法一路放行），而 Teredo 落在 `2001::/23` 私有段清单里使开着隧道的 Windows 用户 URL 导入对所有站点全废。③ **首次打 tag 时 CI 红、Release 没发出去**：新加的那条断言在本机靠 `ipaddress` 私有段表一条粗粒度的 `2001::/23` 条目**顺手兜住**才绿，CI 的 Python 换成细粒度条目后 `2001:20::/28` 掉了出来 —— 同一个 3.11 大版本、判定相反。改法是自己钉住那些段，不是删断言。测试 **266 全绿**

- [x] **v4.4.9**：**按钮 token 体系补全 + 移动端 sheet 闭合态几何修正**——`.btn-xs` / `.btn-del` / `.btn-secondary` 三条规则**从未在 CSS 里定义过**而模板里到处在用，无声降级成裸 `.btn` 尺寸配色（删除类按钮和主按钮长得一样）；补齐并分出 `--danger` token。移动端 sheet 闭合几何 `bottom: 4.75rem` 抬起 76px 而位移只推走「自身高度 + 16px」，**差额 60px 的条带永远留在屏幕内**盖住底部 dock，改为 `bottom: 0` + `translateY(100%)` 与 reader drawer 同构。另加全仓库 dict 字面量重复键棘轮。测试 **280 全绿**

- [x] **v4.5.0**：**Präpositionen-Matrix 介词矩阵视图**——把 552 词 / 691 条搭配**倒过来**按介词分组（21 组，按搭配数降序），Dat/Akk/Gen 过滤 + 防抖子串搜索 + CEFR 标签 + 逐条一键入卡盒。分层上纯函数内核**不认识 CEFR**（会成循环导入），CEFR 注入与组排序留在服务端。本轮变异验证抓到**三条空转断言**：组内排序断言在数据本身有序时删掉 `sort` 也绿、payload 字段名在别处到处出现、端点测试两端读同一份缓存对象导致比较**恒真** —— 分别改为喂乱序输入 / 切进函数体逐字段断言 / 从数据集直接构造期望多重集。测试 **298 全绿**

- [x] **v4.6.0**：**德语背词工作台集成 + 手机端无声根治**——684 词单文件工作台（FSRS-6 / 卡片复习 / 自测 / 统计 / 词库）以 iframe 嵌入而非合并代码：同源共享 localStorage 与 `/api/`（零 CORS），同时与主应用 2449 行强耦合全局 JS 完全隔离。**移动端无声的两个根因**：`file://` 下 Web Speech 被协议禁掉 + 设备没装德语语音包；修法是新增 `GET /api/audio/tts`（服务端 edge-tts）并设为最高优先级音频源。两处 CSS 陷阱：`body` 的 `padding-bottom` **不在** **`.view`** **的 flex 高度链里**，fixed dock 会直接盖住填满视图的 iframe（移动端必须显式扣掉 nav + dock 高度）；裸 `#view-german { display: flex }`（特异性 1,0,0）会压过 `.view { display: none }`（0,1,0），显示规则**必须** `.active` 作用域。备份覆盖 `wb.*` 进度键。测试 **314 全绿**

- [x] **v4.6.1**：**背词台 TTS 修复：点一下不出声、再点一下读两遍**——两个独立成因叠在一起。① 入口清理在 `removeAttribute('src')` 之后多调了一次 `load()`，这会给 `<audio>` **排一个异步 error 事件**，它在当前同步块跑完后才派发，正好命中同一 tick 里刚装上的 `onerror` —— 首次点击被自己的清理判成失败而静默无声。② `_ttsAudio` 是两条链路共用的**全局单例**，per-attempt 的闭包标志管不住**上一次**尝试的回调：旧 timer 醒来会清掉新播放，旧 `onplaying` 又把新尝试判成已完成 —— 连点于是交叉干扰、重复出声；改为全局递增的 `_ttsAttemptId`，stale handler 自己认出该退出。**教训：共享媒体单例上，per-attempt 的闭包标志不足以做互斥，需要一个全局的 attempt 身份。** 测试 **316 全绿**

- [x] **v4.6.2**：**卡盒交互修复 + 伴读宠物 + 自测范围**——① 伴读宠物在背词台视图自动隐藏（不盖住设置按钮）；② 自测新增「复习不认识（评过 Again）」范围，`addWrong` 写入 `rv` 标记；③ 卡盒翻转 onclick 从容器移到正面，背面评分按钮加 `stopPropagation`，Android 3D 变换下不再误触翻转；④ `toggleDeckFlip` 加 200ms 防抖，阻断 Android 双击事件抖动导致的「翻了又翻回来」。测试 **316 全绿**

- [x] **v4.6.3**：**工作台导出 Android 修复 + 卡盒背面 swipe 拦截**——工作台用 `Blob + URL.createObjectURL + <a download>` 导出备份，但 Android WebView 的 DownloadListener 对 `blob:` URL **永不触发**（无报错，用户以为成功了）。改为走服务端下载通道：`download()` 先 POST 到 `/api/wb/backup/prepare` 换 token，再 `location.href` 到 `/api/wb/backup/download/{token}`（跟主应用备份同款机制），独立打开 HTML 时无 `/api/` 则走 blob 兜底。服务端新增 `/api/wb/backup/prepare` 和 `/api/wb/backup/download/{token}` 两个端点。② **卡盒背面评分按钮被 swipe 吞掉**：`attachDeckSwipeListener` 绑在整个卡片容器上，背面按钮的触摸也被捕获，手指轻抖就超 70px 阈值触发 `stepDeck`。改为 `deckFlipped` 时跳过 `onTouchMove` / `onTouchEnd`。测试 **316 全绿**

- [x] **v4.6.4**：**介词矩阵已入卡持久化**——新增 `prep_saved` 表（主键 `(lemma, praep, kasus)`）与 `GET/POST /api/prep/saved` 端点，前端 `_prepSavedKeys` 从服务端初始化（不再空 Set 起步），`savePrepCardFromMatrix` 成功后异步写入。备份/恢复带上该表。测试 **319 全绿**

- [x] **v4.6.5**：**局域网同步 6 位短码**——WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 文本改为 6 位短码：A 存 SDP 到服务端拿到 `K7M2X9` 大字码，B 输入取出 SDP，生成回执后同样拿到短码。`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`，内存缓存 5 分钟 TTL，一次性消费。测试 **322 全绿**

- [x] **v4.7.0**：**歌德 A1 备考工坊全面落地 (Goethe-Zertifikat A1 Werkstatt)**——702 官方考纲词汇（15 大真实主题、全量地道例句、准确复数、0 模板句）+ 8 套填表真题 (Schreiben Teil 1) + 10 套短电邮工坊 (Schreiben Teil 2 导向点诊断与满分范文) + 口语 Teil 2/3 考场题卡 + 3D 纸牌堆叠控制栏居中与响应式 UI 抛光。测试 **350 全绿**

- [x] **v4.7.1**：**修复安卓交互全死回归**——v4.7.0 模块化拆分把 `a1_cards.js`/`a1_writer.js` 以空文件提交，`cards.js`/`writer.js` 具名 import 导致 ES module 链接期 SyntaxError、整个模块图失败（`main.js` 永不求值，全 App 只剩 CSS 点击效果）。复原两空模块 + 补抽取后悬空引用 + 新增 `test_frontend_module_graph.py` 模块图结构性回归测试。测试 **352 全绿**

- [x] **v4.7.2**：**修复安卓卡片段标签栏被裁切**——5 个段按钮合计约 527px 超出一屏，被 `.view` 的 `overflow-x: hidden` 移动端守卫裁掉，最后的「歌德 A1」tab 不可见；改为移动端媒体块内 `.cards-seg-bar` 自身 `overflow-x: auto` 横滑到达（桌面内容列较窄，滚动规则必须 scoped 到移动端避免裁桌面 A1 右缘）。测试 **353 全绿**

- [x] **v4.7.3**：**修复 Android 16 导出下载失败**——`DownloadManager.enqueue()` 在 Android 16 上同步抛异常被 catch 吞成 Toast；且备份 token 原为「单次有效」，WebView 嗅探 Content-Disposition 的预取 GET 会烧掉 token，第二次 GET 拿到 404 错误 JSON 被静默存成「备份」。修法：弃用 DownloadManager，新增 `ExportSaver.java`（HttpURLConnection 自取 + MediaStore.Downloads 零权限落盘 + `{"detail"` 错误体内容自检）；后端 token 改为 10 分钟 TTL 内可重复取（`_issue_pending`/`_take_pending`），四个下载端点统一走 `_attachment()` 助手（Content-Disposition + no-store）。另含 pre-commit 密钥扫描性能优化。测试 **359 全绿**

- [x] **v4.8.0**：**歌德 A1 听力与阅读全真考场工坊 (Goethe A1 Hörverstehen & Lesen)**——① **听力考场工坊 (Hörverstehen)**：5 套官方标准试卷 (75 题) 覆盖日常对话 (Teil 1, 放2遍)、公共广播 (Teil 2, 仅1遍)、电话留言 (Teil 3, 放2遍)；考场流程状态机、25.0 换算得分评级、双语 Transkript 复盘与考点生词一键入盒；② **阅读实战工坊 (Lesen)**：6 套官方全真试卷 (90 题) 覆盖便条邮件 (Teil 1, R/F)、网页广告双选比对 (Teil 2, A/B)、公共标牌告示 (Teil 3, R/F)；25 分钟全真倒计时与答题卡全景矩阵；③ **模块化与可靠性加固**：新增 `a1_hoeren_dict.py`, `a1_lesen_dict.py`, `routes_a1_hoeren.py`, `routes_a1_lesen.py`, `a1_hoeren.js`, `a1_lesen.js`；会话令牌守卫消除异步竞态，`a1_hoeren_records`/`a1_lesen_records` 数据表与备份自动联动。测试 **367 全绿**

- [x] **v4.8.1**：**修复 Android 打包遗漏 6 个 Python 路由/语料模块**——Chaquopy 打包清单未纳入 `routes_corpus.py` 等 6 个模块，APK 启动时 import 失败导致引擎直接崩溃。补 hidden-import + APK 拷贝清单 + APP_NEEDLES 资产验证。

- [x] **v4.8.2**：**修复 Android 预设文章为空 + 首次进入交互无响应**——`server.py` 只建表未调 `seed_preset_articles()`，全新装无预设文章；且 seed 的 spaCy 冷启动阻塞在请求链上造成「前端版本号已显但交互无响应」感知。将 seed 移到应用构造阶段立即执行（count>0 不重复）。

- [x] **v4.8.3**：**修复安卓交互全死回归（`main.js`** **窗口回调未定义）**——`main.js` 底部 `Object.assign(window,{…})` 引用 `clearA1Email` 此名却已从 `from "./writer.js"` import 列表悄然删除，模块求值时抛 `ReferenceError`，整个回调挂载中断（无 handler 接线、仅 CSS 点击效果），页面照常渲染但点击无反应。`test_frontend_module_graph.py` 原先只验证「已 import 的名字能解析」，对这种「用了但没 import」的裸标识符看不见 —— 新增 `test_window_hook_exposer_identifiers_are_bound` 静态解析 `Object.assign` 块每个裸标识符、`test_writer_a1_email_functions_present_in_main_imports` 钉住 A1 helper 全量 import。测试 **373 全绿**

- [x] **v4.9.0**：**背词台核心词模式 + 导入按词头去重**——① **核心词模式**：235 词核心子集与 704 词全量一键切换，核心标记打在既有词条上而非复制词表（复制会分叉出两套 FSRS 卡），每日新词额度全局共享，复习途中切换只静默过滤**当前位置之后**的队列；老设备走幂等回填补 tag 并注入缺失核心新词，`S.cards`/`S.log`/`S.wrong` 一律不碰。② **导入去重**：`applyMerge` 原先只按 id 合并，同一个词在别的设备上是自定义词、在本机是内建核心词时会并排塞进词表 —— 两张独立 FSRS 卡、复习队列里同一个词出现两次；补归一词头二级索引。归一刻意**保留大小写、不带 pos**：德语里大小写承载语义，`sie`（她/他们）与 `Sie`（您）只差首字母且同为 Pron，`toLowerCase` 会把敬称并掉。③ 下架 `a1-0544`/`a1-0545` 两条既有重复种子词（684 → 682），配幂等 `migrateSeedIdAliases()` 把被删 id 下的进度搬到留存 id（两边都有按 reps、reps 相同按 due 取多者），零进度丢失、零孤儿卡。④ 新增动态探针 `tools/wb_merge_probe.mjs`，把真实 `normHw`/`applyMerge`/迁移函数从 `workbench.html` 切片出来在 `node:vm` 里真跑、用真实词库连导两次证明二次导入是 no-op —— **静态正则只能证明「代码长这样」，证明不了「二次导入是 no-op」**；探针对切片有护栏断言（切歪即抛错而非静默假绿），`added`/`merged` 从 `applyMerge` 真实吐出的 toast 解析而非自己算，否则 `merged+added==incoming` 会退化成恒真。本轮六发变异全部致红。测试 **409 全绿**

- [x] **v5.0.0**：**核心词模式切换前置 + 设置即时生效**——工作台顶栏新增紧凑分段控件（`核心` / `全部`），scope 从词库视图的 `<select>` 迁移至 review 视图唯一写入口；搜索框旁路 scope（核心模式下搜非核心词能命中）；`renormalizeQueueTail()` 实现 dailyNew / newOrder 设置即时生效（手动追加的词豁免裁剪）；`buildReviewQueue()` 体首 `manualExtraIds.clear()` 确保豁免集跨重建不残留。测试 **428 全绿**

- [x] **v5.0.1**：**多领域专家缺陷修复与安全加固 (Multi-Expert Audit Hardening)**——① **存储与 FSRS**：补全 `RestoreReq` A1 听力/阅读还原字段（彻底根治还原清空 A1 历史），`review_card_sm2` 动态计算 `elapsed_days` 激活 FSRS 幂律遗忘曲线；② **安全与可靠性**：桌面端所有破坏性 DELETE 接口加 `_require_localhost` 回环鉴权，`security.py` 增加 2MB 流式体积拦截与合法端口限制，修复安卓 Edge TTS stdlib 异常降级链；③ **语言学与句法**：修复过去时动词反查碰撞（`standen` 准确反查 `stehen`，`gingen` 反查 `gehen`），句法拓扑识别介词从句后场边界，`writing_rules.py` 修复 `euer`/`eur` 屈折脱落与 `entlang` 前后置格位；④ **前端加固**：`a1_hoeren` 词汇卡全面改用 `jsAttr()` 杜绝单引号 XSS，`main.js` 显式导出 A1 命名空间并绑定切页停止模考。测试 **452 全绿**

- [x] **v5.0.2**：**审计修复与 XSS 消毒 (Post-Audit Fix)**——① **reader.js XSS sink 全消毒**：14 处 raw interpolation 改用 `Number()` / `safeCefr()` / `esc()` / regex strip / `safeTokens()`，彻底关闭通过 backup/restore 导入 crafted processed_json 后在 localhost origin 触发的 DOM XSS；② **A1 模考统计修复**：`log_study_event` 补充 `a1_hoeren` / `a1_lesen` 分支，模考次数与学习时长正确计入 `daily_summary`；③ **德语动词反查修复**：过去时词干拼后缀前先剥 `-e`（`wusste → wusst + en = wussten`），修复弱变化/混合变化动词复数形式索引遗漏；④ **DeLector.spec 测试改进**：CI 干净 checkout 下显式 `pytest.skip` 替代静默跳过。测试 **453 全绿**

- [x] **v5.1.0**：**局域网随时静默同步 Stage B（WebRTC 自动化）**——① 信令端点补 `X-WB-Key` 鉴权并修 POST 预检放行；② **持久配对凭证 + 一键撤销**（撤销即换新 key，替代每会话短码）；③ WebRTC 信令中继 `/api/wb/rtc/signal`（按配对密钥建邮箱、sender 过滤防重放）；④ 前端 `wbsync.rtc` 建连与 DataChannel **静默同步**（信封与 HTTP PUT 同构）；⑤ 断线自动重连 + HTTP 轮询兜底降级（连续失败停手保可达）。Stage A HTTP 轮询保留为兜底。全量 pytest **487 全绿**；9 wbsync 探针 + 40 定向测试无回归。

- [x] **v5.2.0**：**备考域重布局 + 等级可扩展（ADR-0005 Phase 1）**——① **主导航加「备考 (Prüfung)」顶层域**：A1 写作/听力/阅读/口语/词表五模块从「写作润色」「复习卡片」工具容器迁入独立备考域，工具视图回归纯工具语义（写作=纯 essay、卡片=纯复习）；② **exam catalog 目录化**：`/api/exams/catalog` 代码注册目录单源，等级页签与模块卡片数据驱动，加 A2/B1 = 插一行数据（问卷库不入库，YAGNI）；③ **成绩表泛化**：`exam_trials(level,module,…)` 表 + 幂等迁移 A1 存量（旧 `a1_hoeren_records`/`a1_lesen_records` 保留兼容），备份/还原接线收编；④ **导航单源静态入口 + 备考域骨架**、`tools/ia_dom_mount_probe.mjs` 行为级 DOM 探针（node:vm 真跑，回退必红）。测试 **559 全绿**。

- [x] **v5.1.1**：**审计修复收口 + 性能与稳定性 (M1–M5 + M4)**——① **审计修复（M1–M5）**：旧 6 位短码 LAN 面板停用标注并整体禁用（端点已强制配对密钥，死 UI 明示）；AI 判分/成功提示类残余 `alert` 收敛为 notify（写路径保留 + 双面黑白名单护栏）；wb pull 指数退避、RTC 瞬态不累计、阅读计时器防叠；② **性能（M4）**：查词/判题热路径常量模块级提升、复合词拆解与核心词查表缓存、句切分缩写保护正则提升；③ **稳定性**：PWA 版本更新改温和提示不硬刷窗口、TTS blob URL 统一撤销 + 播放请求令牌防错句覆盖、Reader 陈旧响应守卫、AI 请求输入上限与 TTS voice 白名单；④ **安全补漏**：批注删除纳入本机写闸、X-WB-Key 统一 `secrets.compare_digest` 消除时序侧信道、还原不导入 API 配置防 Key 外泄、Anki 导出 HTML 转义防存储型 XSS；⑤ 测试库隔离与断言护栏补齐。**本版同时回补 v5.0.2 → v5.1.1 的版本面同步**（sw.js 缓存键 / index.html 顶栏 / build.gradle / README / AGENTS）。

- [x] **v5.3.0**：**背词工作台全域 Editorial 重塑 + 精读语法雷达 + A2 词汇全域贯通**——① **共享设计系统 Token 层抽离**（`static/css/tokens.css`）并全量接入背词工作台：统一 Academic Modern Editorial 暖纸墨水调色板、`--serif/--sans/--mono` 字体族与 960px 实体期刊画布，彻底消除硬编码中文字体与 Georgia；考纲词表只读契约 `GET /api/cards/vocab` 上线（CEFR/范围过滤 + 内存解析缓存），工作台顶栏扩展 3 档「A1 核心 / A1 全量 / 精读生词」范围选择；② **ADR-0006 背词工作台 Zettelkasten 实体学术卡箱与心流优先重塑**：出版物下划线轻量 Tab 导航与聚焦顶栏、剥离厚重阴影与大圆角容器、纯白学术抽认卡纸张层叠翻转（40px 衬线词头）、矿物植物印章式四级柔色评分座（键盘快捷键角标），自测题选项/拼写输入框/KPI 统计/词库浏览表全量 Editorial 化；③ **Grammatik-Radar 精读语法雷达（ADR-0007）**：消除 600ms hover 被动弹出，改行内幽灵微胶囊（Quiet Ghost Pill）显式点击触发句法抽屉（零心流打扰、保护查词抽屉状态）；语料语法 6 维指标（从句复合度/五场域展开率/句框跨度比/关系从句率/虚拟语气率/被动被动态率）落盘 `corpus_syntax_stats` 表 + `POST/GET /api/syntax/stats` 端点，句法抽屉内嵌零外部依赖 SVG 蛛网雷达图对比「本文维度 vs 语料平均基准」；④ **A2 词汇与全域背词系统扩展**：歌德 A2 **974 词全量规范化**（`format_vocab_headword` 精确拼装 497 名词定冠词如 `das Abenteuer` 并首字母大写，动词/形容词保持小写），`GET /api/a2/vocab` + `exam_catalog` 注册 A2 词表模块（动态推导 974 题量，打包 hidden-import 守卫），工作台顶栏第 4 档「A2 词库」异步按需同步持久化，备考域激活 A2 考纲 Tab（3D 扑克翻转/例句发音/网格模式/搜索过滤/加入复习盒）。测试 **582 全绿**（基线 559 → 582）；10/10 Node.js 行为探针全绿（含 13/13 切片护栏 100% 保护）。

- [x] **v5.4.0**：**遇见区 i+1 阅读桥 + Go DAG job#1 内容生产引擎（ADR-0010，PR #25–#27）**——① **遇见区 P0（A1–A7）**：`encounter_texts` 存储 + `/api/encounter` 路由与 `import-pack` 契约（`encounter-pack/v1`，幂等）+ 逐词注解 + `view-encounter` SPA + deck 桥已背词高亮（剥冠词 lemma 判定）+ 生词一键进卡（IndexedDB `wb/words` 双写）+ 会话小复习；② **Go DAG job#1 真执行（B1–B9）**：`delector job run encounter-pack` 本地语料→分级卡包——corpus 两阶段有界扫描（`--max-articles/--max-file-bytes` 护栏）、Pack schema + TokenBudget（含 Release）、DeepSeek gloss（429/5xx 退避）、worker-pool runner（共享预算 + 墙钟 2h 兜底）、cobra CLI 默认护栏，工具注册升至 **6**（新增 `vocab_stats`），`-tags integration` 真链路 `TestEncounterRealChain` PASS；③ **vault-team 评审 8 条修复**：备份/还原纳入 `encounter_texts`、进卡 IDB 双写、403 人话提示等；④ 同期合入 PR #25 备考域独立域迁移（ADR-0005）与 PR #26 自托管字体/弹窗修复。测试基线 **686 passed + 1 skipped**；Go `go test -race ./...` 与 `-tags integration` 全绿。

- [x] **v5.5.0**：**内容供给侧 —— 遇见区开箱即读 + A7 验收自动化**（PR #39，2026-09-10）——① **A7 双端手工冒烟退役**，改由自动化接管：`tests/test_encounter_journey_e2e.py`（6 用例：deck 镜像 / 加短文 / annotate 已知-未知**双向**断言 / 本地词典离线取义（AI tier 打桩抛错）/ 进卡后镜像回读 / 无 key PUT 403）+ `tests/test_encounter_journey_probe.py`（5 用例：**真实 annotate JSON** 驱动逐字节拷贝的 `deck-bridge.mjs`，钉高亮 / 覆盖 / `unknown_top` 排除已背词 / word-only 进卡 / `DECK_KEYS` 常量），真机部分记为发版后一次性点检；② **预置分级短文**：`tools/build_encounter_seed.py` 离线读 `OFFICIAL_CORPUS` → spaCy 分词 + `vocab_stats` 同源分析 → `encounter-pack/v1`，产物 `delector/data/encounter_seed_dict.py`（纯数据第 9 个 data dict，**4 篇 A1×2/A2×2**，零 LLM 零网络，两次生成字节一致）；③ **启动即 seed**：`seed_preset_encounter_texts`（空库守卫 + `pack_id` 幂等 + 逐包异常隔离）由 `create_app()` 在 `seed_preset_articles` 之后调用（**不进 `init_db`**，守住「空库=空列表」6 条既有契约）→ 新装/空库首启即可读，用户已有内容不被动；④ 打包面三处注册同步（data dict 8→9）+ 守卫逐条钉死；⑤ 同期基建：PR CI 门禁 `ci.yml` + dependabot 三生态周更 + `.gitattributes` 锁 `*.go eol=lf`（查明「11 个 gofmt 不洁文件」系 autocrlf 假阳性）。测试基线 **715 passed + 1 skipped**；PR CI（ubuntu，含 node 探针）1m53s 绿。

- [x] **v5.5.1**：**修复 PWA 更新提示不可交互与常驻遮挡**（PR #40，2026-09-13）——① 「新版本已就绪」提示的刷新动作原先绑在 `#wb-notify` 上，而 `.wb-notify` 带 `pointer-events: none`（toast 的非阻断语义，用于不拦截下层点击）→ `onclick` 物理不可达（用户报障「点了没用」）；② 该提示用 `sticky: true` 且无任何关闭入口 → 常驻遮挡界面（「一直站在那里」）。修法：独立的 `#wb-update-bar`（`pointer-events: auto`）+ 两条明确出路「立即刷新」/「稍后」；新增 `tests/test_pwa_update_notice.py` 两条可用性契约（先红后绿），并以真实浏览器 `elementFromPoint` 命中测试验证点击可达（非字符串断言）。测试基线 **717 passed + 1 skipped**。**本版必须覆盖安装才能让 Android 端生效**（static 打包在 APK 内）。

- [x] **v5.5.2**：**Ruff + Mypy 双静态门禁 + WiFi 手机拉取式内容分发**（PR #41/#43/#42，2026-09-13）——① **Ruff 清账**：`select = ["E","F","I"]` + `line-length = 120`（数据字典 E501 豁免），存量 2265 告警 → 零（E501 占 93%），`ruff format` 全量 106 文件，`ci.yml` 接入门禁（不进 requirements，Android 纯净），守卫测试钉死规则集与豁免面；② **Mypy 适度严格档**（`check_untyped_defs`+`no_implicit_optional`+`warn_unused_ignores`+`warn_redundant_casts`+`ignore_missing_imports`，配置落 `pyproject.toml` 的 `[tool.mypy]`——不放 mypy.ini 以免 GBK 解码崩），138→0 错误（VerbTrio 类级注解一次消 20 处、spaCy 降级带理由豁免），**顺带修 2 处真实缺陷**（`start.py` 给已不存在的 `install_signal_handlers` 赋值致 Android 禁信号防护静默失效；`test_audit_regressions.py` 传 3 个不存在字段名），`ci.yml` 接入门禁；③ **遇见区内容分发改为手机拉取式（WiFi）**：因 `start.py` 中 Android 实例有意绑 `127.0.0.1`（避免无鉴权 `POST /api/settings` 暴露局域网）致「桌面推手机」不可达，反转方向——桌面绑 `0.0.0.0` 作只读货架（`GET /api/encounter/packs` 清单 + `/packs/{id}` 完整 v1，绝不提供写操作、不泄露正文），手机 `POST /api/encounter/pull-pack`（localhost 闸 + 5s 超时）拉取 → `validate_pack` → `import_encounter_pack` 幂等落库，前端「从电脑导入」只调本机相对路径（同源零跨域）；Go 侧与 Android 打包面零改动。测试基线 **788 passed + 1 skipped**（含 WiFi 32 + Ruff 5 + A7 22）；本版 static 打包在 APK 内，Android 需覆盖安装生效。

- [x] **v5.6.0**：**听力微训工坊 —— 备考域三模式听练**（PR #44，2026-09-14）——① **L 精听 / 影子跟读**：逐句播放 + 变速/重复/循环 + 跟读停顿；② **D 听写诊断**：隐藏文本逐句听写 → `diagnose_diktat` 词级 LCS 逐字归因（correct/umlaut/case/inflection/missing/extra 六色胶囊）；③ **C 听力填空**：动词/名词启发式挖空 + 填答校验。材料源复用遇见区分级短文（encounter）+ A1 听力音频句库（`a1_hoeren` 的 `audio_text_de`）；后端 `delector/services/listen.py`（`diagnose_diktat` + `make_cloze` 纯函数）+ `delector/routes/listen.py`（`/api/listen` materials/diagnose/trials 四端点）+ `listen_trials` 表（对齐 `exam_trials` 模式，随备份还原）；前端 `static/js/listen-lab.js` 挂进备考域。测试基线 **788 passed + 1 skipped**（基线 751→788，净增 35：引擎 21 + API 9 + 探针 2 + 模块图 3）；Android 真机 TTS 链路留发版后一次性真机点检。

- [x] **v5.7.0**：**长难句精读工坊 —— 备考域句子级攻坚**（PR #45，2026-09-14）——① **句子难度评分引擎**：`delector/services/syntax_score.py` 7 维加权评分 0–100（从句深度/从句复合度/被动/虚拟式/VL 句框/关系从句/句长）+ `estimate_level` CEFR 带估算 + `rank_sentences` 全文切句评分（复用红线 10 唯一切句 `split_sentences_pure_python`，spaCy/纯 Python 双路径带 `path` 降级标注，红线 1）；② **跨语料挑句**：`GET /api/syntax/hard-sentences` 按 source（article/encounter/all）× level × min_score × limit 挑句，进程内存缓存 + limit 护栏；`GET /api/syntax/hard-sentence/<sid>/detail` 句法树+原句+源元信息；③ **拆解→揭示句法树**：句卡先"尝试拆解"（默认隐藏句法树）→ 揭示渲染 clause_tree/topology + 查词链路（`/api/lookup/vocab`）；④ **入复习盒 + 成绩落盘**：「加入复习盒」复用 `saveGrammar` 语义写 `grammar_cards`（不新建卡种表，同句已入盒显示"已加入"）；会话成绩 `POST /api/syntax/hard-sentence/<sid>/trials` 落 `hard_sentence_trials` 表（对齐 `listen_trials`，随备份还原）；⑤ **等级门控适配过渡期**：默认 A2+ 门控（可切全部），`path="pure"` 句显示"近似分析"提示，评分仅参考。测试基线 **828 passed + 1 skipped**（基线 788→828，净增 40：引擎 16 + API 11 + 探针 5 + 模块图 8）；Android 端 static 打包在 APK 内，需覆盖安装生效。

- [x] **v5.7.1**：**长难句工坊 Android 真机 500 热修**（2026-09-14）——v5.7.0 真机点检报「长难句清单加载失败 Internal Server Error」：Android 环境（spaCy/数据差异）某句 `analyze_syntax_tree` 抛异常，而 detail 端点是唯一无容错路径（`rank_sentences` 有逐句 try/except 跳过坏句，detail 没有）→ 点击揭示句法树 500；`source=all` 全语料榜整榜遍历任一材料异常 → 空态。修法：① detail 单句分析失败降级 **404「该句暂无法分析」**（不 500，对齐 rank_sentences 容错纪律）；② `_rank_source` 切句异常 → 单材料空榜；③ `source=all` **逐材料隔离**（坏材料 SQL/切句异常只丢自身，不炸整榜）。回归测试 +3（detail 分析抛→404 人话 / 切句崩→空榜 200 / all 坏材料→其余材料仍上榜）。测试基线 **831 passed + 1 skipped**（828→831）；Android 需覆盖安装生效。

- [x] **v5.7.2**：**长难句工坊 500 真根因修复 —— Android pydantic 1.x 兼容**（2026-09-14，vault-debug 4 步）——v5.7.1 复测仍报「长难句清单加载失败 Internal Server Error」：Android Chaquopy 打包 `pydantic<2.0.0`（1.10.x）+ `fastapi<0.100.0` + Python 3.10（build.gradle:84-92），而 `syntax_score.rank_sentences` 用了 **`model_copy()`（pydantic v2 专属 API，1.x 不存在）** → AttributeError → `/api/syntax/hard-sentences` 全源 500（桌面 pydantic 2.x 无法复现，上轮 detail 容错/all 隔离未触碰此行故无效）。修法：`model_copy` 改为直接构造 `SentenceScore`（v1/v2 通用，对齐 `routes/main.py` 既有 `hasattr` 兼容纪律）；全仓排查确认仅此 1 处 v2 专属 API；新增**跨端打包兼容守卫** `test_syntax_score_no_pydantic_v2_only_api`（regex 钉死 syntax_score.py 无 `.model_x(` 调用，落实 DELECTOR-DEV-RULES §2.4）。验证：临时 venv（pydantic 1.10.26 + fastapi 0.99.1）复现 `model_copy` 缺失 + 修复后 `rank_sentences` 正常出句；测试基线 **832 passed + 1 skipped**（831→832）。Android 需覆盖安装生效。

- [x] **v5.7.3**：**揭示句法树 `[object Object]` 渲染修复 + 难度分文案消歧**（2026-09-14，vault-debug）——v5.7.2 复测报：揭示句法树只能看到 `[object Object],[object Object]`（用户简记 [object, object]）。根因：`_topologyHtml` 的 `Array.isArray(ft) ? ft.join(" ") : topo[key]` —— `field_texts` 在 spaCy 与纯 Python 双路径恒为**字符串**，恒走 else → `vals = topo[key]`（原始 token 数组）→ `String(数组)` 渲染成 `[object Object]`；**探针 fixture 误用数组 field_texts（与真实 API 形状不符）→ 恒走 join 分支 → 漏检**。修法：`_topologyHtml` 优先取 `field_texts` 字符串原文，缺失才退化顶层 token 数组 join；探针 fixture 改真实形状 + 新增 2 断言（无 `[object Object]` / 渲染字符串原文），46 断言 + 3 变异全绿。附带消歧：「当前 x/100」实为**难度分**（非句次序，进度在卡面"句 x/y"；列表按难度降序 → 点上一句分数变大属正常），文案改「当前句难度 x/100」。测试基线 **832 passed + 1 skipped**；Android 需覆盖安装生效。

- [x] **v5.7.4**：**pure 降级评分增强 + 前端字号 + spaCy 诊断**（2026-09-14）——① **pure 路径评分增强**：v5.7.3 真机反馈纯 Python 降级句"普遍 5/100 无区分度"（pure 树单节点无 features，只剩句长维度）。`syntax_score` 新增 `_pure_text_hints` 文本启发式（逗号/从属连词 → clause_count 粗估；`wird/wurde` → 被动；`würde/hätte` → 虚拟式；`, weil/dass` → VL 句框；`, der/die` → 关系从句），`score_sentence` 在 `path="pure"` 时注入，难度榜恢复排序依据（**评分仍是内部启发式非权威，排序供参考**）；② **前端字号优化**（字小又累）：材料卡片 13→15px、原句 17→18px、揭示树/拓扑 13→15px+行高 1.85、树节点类型 11→12px、卡片留白加大；③ **文案软化**：`近似分析（纯 Python 降级路径，评分仅供参考）` → `轻量分析：难度画像为粗估，排序供参考，不必当真`；④ **spaCy 加载诊断**（免 adb）：`GET /api/syntax/spacy-status` 返回 `{path, error}`（spaCy import/模型加载失败的具体异常），前端「轻量分析」提示旁自动展示——用于定位 Android 打包 spacy+de_core_news_sm 却仍走 pure 的根因。测试基线 **838 passed + 1 skipped**（832→838：pure 启发式 +5、spacy-status +1）；Android 需覆盖安装生效。

- [x] **v5.7.5**：**spaCy 诊断竞态修复**（2026-09-14）——v5.7.4 复测：长难句工坊显示「轻量分析」但诊断小字不出现。根因：`enterHardSentences` 里 `_loadSpacyDiag()` **未 await**，`_renderAll()` 在诊断请求返回前抢先渲染，`_q.spacyError` 仍是空串 → 诊断永不渲染。修法：await 诊断就绪后再渲染 + `path="pure"` 且 error 空时显示占位「未捕获到加载异常（需进一步排查）」。探针 46 断言全绿；测试基线 **838 passed + 1 skipped**；Android 需覆盖安装生效。

- [x] **v5.7.6**：**spaCy 诊断 error 永远为空修复**（2026-09-15）——v5.7.5 真机：`/api/syntax/spacy-status` 返回 `path:"pure"` 但 `error:""`，前端兜底显示「未捕获到加载异常（需进一步排查）」。根因：**Python from-import 按值拷贝不可变对象**——`syntax_hard.py` 用 `from syntax_tree import _spacy_load_error` 拿到的是导入时的初始空串；`get_spacy_nlp()` 内 `global` 重绑定只改 `syntax_tree` 模块命名空间，route 持有的旧引用不变 → error 永远空（**spaCy 实际并未加载成功**，`path:"pure"` 即铁证）。修法：`syntax_tree` 新增 `get_spacy_load_error()` getter，route 改调函数实时读取；回归测试 `test_spacy_status_reports_live_error_on_pure_path` 锁定（mock get_spacy_nlp→None + 设实时错误，断言 endpoint error 等于实时值）。测试基线 **839 passed + 1 skipped**（838→839）；Android 需覆盖安装 v5.7.6 后诊断小字才显示真实 spaCy 加载异常，用于定位 Android 走 pure 的根因。

- [x] **v5.7.7**：**真机 spaCy E050 根因修复 —— dist-info 缺失**（2026-09-15，vault-debug）——v5.7.6 诊断小字首次显示真实错误：`E050 Can't find model (md 与 sm 双模型)`。根因排查：APK 解包显示模型文件 44 项全完整、`extract_packages` 生效、spaCy import 正常——但 spaCy 3.8 的 `is_package()` 实现是 `importlib.metadata.distribution(name)`，**只认 pip 元数据（.dist-info）不碰文件系统**；CI 把 `de_core_news_sm` 包目录 `cp -r` 进 APK 时**漏拷了平级的 `de_core_news_sm-3.8.0.dist-info`** → 真机判定"不是 Python 包" → E050。用独立 venv 干净复现：仅包目录 `is_package=False + E050`；补上 dist-info 后 `is_package=True + spacy.load OK`。修法：① CI "Sync Python Backend" 步骤用 glob 定位 dist-info 并连拷进 `src/main/python`；② CI APK 探针加 `dist-info-complete` 精确守卫（v5.7.6 旧 APK 被正确拦截、新 APK 放行，本地用真实 APK 验证）。测试基线不变（纯 CI 打包层修复）；Android 需覆盖安装 v5.7.7、长难句工坊从「轻量分析」切回 spaCy 完整解析。

- [x] **v5.8.0**：**ADR-0011 词库单一真相化 + 等级判定数据驱动正式发布**（2026-09-15，PR #46）——① 背词工作台词库改为**单一数据真相**（`delector/data/a1_workbench_dict.py` 682 词 / 213 核心 / 22 自定义，A1 704 / A2 974 / B1 1712 同契约），根除 HTML 正则解析与静默回退（服务端直接 import 数据模块，缺失抛 RuntimeError）；② 四路径契约统一（9 字段集 `{id,hw,pos,gender,plural,de,zh,core,cefr}`）；③ 前端 `normalizeWord` 幂等归一 + `wb.schema.v1` 一次性迁移（id/进度零丢失，merge 探针全绿）；④ scope 判定数据驱动（`SCOPE_PREDICATES` + `isInScope`/`cefrOf` 唯一入口，13/13 切片护栏零漂移）；⑤ **新增 B1 入口**（工作台第 5 档 + 备考域 B1 页签 + 徽标动态化，catalog `count_fn` 动态推导零硬编码）+ `/api/cards` 信封解包修复。测试基线 **883 passed + 1 skipped**（838→883 净增 44）；Android 需覆盖安装 v5.8.0 生效（B1 入口 + normalizeWord 迁移）。

- [x] **v5.9.0**：**词库富字段与主干分层正式发布**（2026-09-16，PR #54/#55/#56/#57）——① **ADR-0012 词汇主干落地**：`delector/core/lexicon.py`（分片注册表 + provenance + 字段级优先级「cefr 官方 > 手编 > AI、富字段 手编 > 官方 > AI」；`CORE_VOCAB_DB == LEXICON == 4762` 单真值）+ 官方歌德 A1/A2/B1 词表迁入 `delector/data/official_vocab.py`（备考域/工作台 A2 **736**、B1 **1617** 官方精选；`/api/a2/vocab` 默认官方）；② **ADR-0013 输出契约 9→11 字段**（新增 `ipa` / `example_zh`，`de` 语义统一为德语例句）+ 富字段分片 `delector/data/official_vocab_rich.py`（A1 660 / A2 736 / B1 1617，join 零差），**A2/B1 卡片首次具备音标 + 双语例句**；③ **IPA 表示法全局统一**（去 tie-bar，全仓词表 0 残留：A1 seed/custom 10 条归一 + rich 空 IPA 10 条从 A1 seed 回填）；④ **A1 卡片补齐名词 gender/plural**（336/344 = **97.67%**，此前 0%；源 = 主干 LEXICON，与 A2/B1 同源）；⑤ 新增词表来源对账工具 `tools/audit_official_vocab.py` + 归档生成脚本 `tools/gen_rich.py`。测试基线 **972 passed + 1 skipped**（883→972 净增 89）；**Android 需覆盖安装 v5.9.0 生效**（改动含 `static/`）。

- [x] **v5.9.1**：**词库等级标签补齐 + 入口文档瘦身**（2026-09-16，PR #59/#60）——① **工作台词库补 A1 等级标签 `a1`**：此前 A1 只有 `core`（核心语义）而缺等级语义，导致词库工具栏「全部标签」下拉**筛不出 A1**（A2/B1 恰好有 `a2`/`b1`，且词库浏览只在 `core` 档按 scope 过滤，其余档显示全库 → 按标签筛等级是唯一手段）；标签语义统一为 **`a1`/`a2`/`b1` = 等级、`core` = 核心词、`reader` = 精读生词**，种子建表 / `CORE_CUSTOM_WORDS` / 存量 `backfillCoreWords()` 幂等迁移（**不动 FSRS 进度**）。② **修 `reader` 谓词的 `w.custom` 兜底**：22 条 `core-*` 补缺词（`der Wohnort`/`die Nationalität`…）此前被误判为「精读生词」而**同时出现在两档**；收窄为 `tags.includes("reader") || id.startsWith("card-")`。③ **README 瘦身 433 → 131 行（DOC-GOVERNANCE 合规）**：版本历史迁出为 **`CHANGELOG.md`**（70 条历史零丢失，成为版本历史正主）；核心特性 12 子节 → 摘要 + 指针 `FEATURES.md`；目录结构 → 顶层树 + 指针 `docs/agents/architecture.md`；快速启动精简 → 指针 `docs/agents/ops.md`；新增「文档导航」路由表。④ 顺带修正既有滞后：`linguistics`/`syntax_tree` 路径补 `nlp_engine/` 前缀、测试模块数 27 → 60+。测试基线 **973 passed + 1 skipped**；**Android 需覆盖安装 v5.9.1 生效**（改动含 `static/`）。

- [x] **v5.9.2**：**A1 取数统一（ADR-0014）+ 词表富字段回填修复**（2026-09-17，PR #61 + `e2d5504`）——① **A1 取数统一（ADR-0014 S1–S3）**：A1 首装改走 `GET /api/cards/vocab?cefr=A1&scope=all`（API 优先 + 内联降级为 `file://` 离线 fallback + localStorage 缓存 + 失败可恢复重试 + 挂起期占位），输出契约 11→12 字段（+`letter`，服务端下发 seed 原值、不派生——实测 `letterOf` 会在 10 条上漂移 `O↔Ö`/`U↔Ü`）；三条守卫钉死「内联绝不当主路径」。② **A2/B1 富字段回填**：`sync{A2,B1}CardsFromServer` 由 **append-only 升级为「只增 + 只补空字段」**（幂等、绝不覆盖非空、不碰 `cards/log/wrong`）——根治「A2/B1 只有部分词有例句」（根因＝存量词条在首次同步后永久冻结，`ex:[]` 再不刷新；进 A2/B1 档即自愈）；备考域卡片空例句块改**条件渲染**（空值不输出孤立标签）。③ **A1 早退闸修复**：`bootstrapA1Words` 早退闸不再依赖来源标记（旧 `lastSrc !== "inline"` → 改 `!canUseServer`），已以 `server` 落盘的设备**每次启动重新合并** A1 富字段——修「`anbieten`/`allein` 等存量 A1 条目无例句无音标」（旧版构建首装时服务端/种子尚无富字段，裸条目被永久冻结；实测用户 `localStorage` 中 `a1-0011`/`a1-0016` `exLen=0`、`ipa=''`，而 A2 同源条目齐全）。行为级探针新增 A1 早退闸场景 B2 + A2/B1 回填 19 场景（真实源码切片 + `node:vm` 真跑，接入 pytest/CI）。测试基线 **987 passed + 1 skipped**（759 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`，工作区 A/B 证实为既有）；13+ `tools/*.mjs` 探针零漂移；ruff 全绿。**Android 需覆盖安装 v5.9.2 生效**（改动含 `static/`）。

- [x] **v5.9.3**：**类型门禁全仓 `--strict` 清账 + CI 门禁升级 + 工具链修复**（2026-09-18，纯工程治理、**无用户可见变更**）——① **mypy `--strict` 全仓 250→0 清账**（三阶段：`routes/main.py`(62) + `core/database.py`(24) 补注解 → 全仓 133 → `tools/` 108→0），CI 门禁升级为**双轨 strict**（`delector`+`tools` 走 strict、`tests` skip）+ 修正门禁路径拼写（`deletor`→`delector`）；设计见 `docs/specs/2026-09-18-mypy-strict-annotation-sweep-design.md`。② **工具链修复**：`tools/vault-proactive-scan.py` 两缺陷修复、`tools/check_security` 排除 `node_modules`（消除 WASM base64 误报）。测试基线 **987 passed + 1 skipped**（与 v5.9.2 持平；2 条既有 Windows 环境失败 `no such table: exam_trials`）。**本次无 `static/` 改动** → 桌面端即时生效；Android 覆盖安装为可选（无前端变更）。

- [x] **v5.9.4**：**精读生词（reader 档）富字段回填 + 原句优先**（2026-09-20，`a7801ec`）——补最后一个同型缺口：**reader 生词卡此前永远裸**（服务端 `scope=reader` 显式置空富字段 + 前端 `syncReaderCardsFromServer` append-only → 存量永不刷新），与 A1/A2/B1 三档信息量不对齐。① **服务端**：新增 `_reader_lemma_key`（去冠词 + 小写归一——`RICH`/`LEXICON` 键 100% 小写，而写入侧 `lemma` 可能大写/带冠词）+ `_reader_rich_fields`（`rich_of` 取 `ipa`/例句、`a1_lemma_meta_of` 取 `gender`/`plural`——源 = 主干 LEXICON 4762 全量、覆盖非 A1、`lookup_irregular_verb` 屈折形兜底 `ging→gehen`），reader 分支改「**命中才补，未命中留空不编造**」；`de` 语义 = **原句优先**（有 `sentence_context` 保留生词原句且不补 `example_zh`，避免「德文原句 + 官方例句中文」文不对题）。② **前端**：`syncReaderCardsFromServer` 由 append-only 升级为「**只增 + 只补空**」（`ipa`/`ex`/`gender`/`plural`），不覆盖非空、不碰 `cards`/`log`/`wrong`、幂等 → 进「生词」档即自愈。③ 行为级探针 `tools/wb_reader_rich_backfill_probe.mjs`（13 场景，真实源码切片 + `node:vm` 真跑，含防死测守卫）接入 pytest。测试基线 **993 passed + 1 skipped**（765 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`）；15 个 `tools/*.mjs` 探针零漂移；ruff 全绿 / mypy `--strict` 0 error。**Android 需覆盖安装 v5.9.4 生效**（改动含 `static/`）。

- [x] **v5.10.0**：**A1 富结构收敛（FRAGMENTS 单源 + membership side-car）**（2026-09-21，PR #62，ADR-0015，`/vault-grill` + `/compose-next`）——落地 ADR-0013/0014 明确 defer 的 A1 三源收敛：① **成员清单 + 共享字段单源**（seed∩GOETHE ≈391，非同一表；membership side-car 按 id 承载）；② **字段级优先级**（同形异义 bitte/essen/leben/sie 按 id 带 `ipa`/`ex`，主干 `"None"` 为无性别哨兵）；③ **专有词全部进 FRAGMENTS**；④ **考纲 A1 露出 IPA**；GOETHE plural 完整形不入 5 元组后缀位。门禁：pytest **1081+1** / ruff 0 / mypy `--strict` 0 / Go 全绿 / 探针 16/16。**Android 需覆盖安装 v5.10.0 生效**（改动含 `static/`）。
- [x] **v5.9.5**：**例句 / 搭配 / 语料 全文检索（内存扫描版）**（2026-09-21，分支 `feature/vocab-search`，/vault-exec **6 Task 全绿**）——新增「检索」子系统：对 **词条 4762 + 例句 2722 + 介词搭配 691 + 语料全文**（文章/分级短文）做检索，四组结果（词条 / 例句 / 搭配 / 语料）。① **服务端**：`delector/services/search.py`（纯函数 `fold`/`iter_vocab_docs`/`iter_corpus_docs`/`match_score`/`search`——德语变音折叠 `ä→a ö→o ü→u ß→ss` + **中文子串**匹配；字段加权排序；`groups_total` 每组命中数）+ `delector/routes/search.py`（`GET /api/search?q=&scope=&limit=`，注册于 `main` **之前**）。② **前端**：`view-search` + `static/js/search.js`（顶栏 `nav-btn-search` **+ 移动 dock `mob-btn-search`**、四组渲染、**高亮先 `esc()` 再 `<mark>`**、空态/降级、语料 source 分叉跳转）。③ **截断语义拆分（T6）**：`truncated` **仅**表"语料 hard cap 未扫完"（真异常）；`limit` 每组限量由 `groups_total` 表达（组尾「仅显示前 N 条（命中 M）」）——修「几乎每次搜索都弹 结果已截断」的噪音。④ **测试工程**：行为探针 `tools/wb_search_probe.mjs`（**真实切片 `node:vm`**，4 场景 7 断言：XSS / 四组 / 空态 / 截断提示）+ **性能守卫**（8175 词库 + ~195KB 语料，单次 min≈**21.7ms** < 50ms）+ **注册守卫**（AST）接入 CI。**技术路线 = 内存扫描（不落库）**；**FTS5 被 Spike 否决**（`unicode61` 对 CJK 不切词 / `trigram` 要求查询 ≥3 字符致中文**两字词全废** / Android 内嵌 sqlite FTS5 不确定 / 规模远未达 ADR-0014 门槛）——见 ADR-0014 与 `docs/specs/2026-09-20-vocab-search-design.md`。测试基线 **1071 passed + 1 skipped**（843 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`）；全 `tools/*.mjs` 探针零漂移；ruff 全绿 / mypy 双轨（strict + skip tests）0 error。**Android 需覆盖安装 v5.9.5 生效**（改动含 `static/`）。**已知小限制**：`_highlight` 在 `esc()` 后定位，查询恰为 HTML 实体名子串时 `<mark>` 误插实体内部（**非 XSS**，待后续修）。

- [x] **v5.11.0**：**遇见区 i+1 补齐（内容放量 + 就近选材）**（2026-09-23，PR #64，`/vault-spark` → `/vault-plan` → `/vault-exec` **6 Task 全绿 + 2 轮 REVISE**）——补齐北星「遇见区 i+1 阅读桥」的两个缺口。① **内容放量**：预置分级短文 **4 → 7 篇**（A1×2/A2×2/B1×3；复用仓库既有 `OFFICIAL_CORPUS`，`build_encounter_seed.py` 默认分级 `A1,A2` → `A1,A2,B1`），并为每包**预计算** `analysis.lemma_seq`（annotate 口径：剔除 `is_space`、保留标点）→ 运行期零 spaCy 即可算覆盖率。② **存量可升级**：`seed_preset_encounter_texts` 由**空库守卫**升级为**版本闸 + 只增 + 只补空 + 幂等**（`PRESET_SEED_VERSION = 2` + `app_settings["encounter_seed_version"]`）——非空库设备**零操作**补装新增 3 篇，并对旧行**只补空** `lemma_seq`（其余列与其余键逐字段不动）；**不引墓碑**（升级只补一次，用户删除的预置包不会每次启动复活）。语义遵循 Vault `01-Rules/STORED-DATA-BACKFILL` / 项目红线 12。③ **就近选材**：新增只读端点 `GET /api/encounter/texts/index`（零 spaCy、零写库、**不挂**本机闸、未分析行两字段 `null` 但**不丢行**）+ 前端零依赖纯函数 `static/js/enc-i1.js`（`I1_BANDS`/`bandOf`/`coverageOf`/`rankEntries`/`topPick`/`hasCoverage`）+ 遇见区列表**徽章（正好读 / 偏简单 / 偏难）与「建议先读」推荐条**；索引失败**完全降级**回原列表，未背词显示引导文案。**已背词判定仍永远在本机**（ADR 红线：服务端只给词序列，覆盖率一律前端算）。④ **硬不变量 I-1**：索引 `lemma_seq` 与 `annotate` 逐 token 序列**全序列逐元素相等** + 分母相等 + rate **逐位相等**（反绿变异「让 annotate 也丢标点」→ 7 篇全红）。⑤ **测试工程**：行为探针 `tools/wb_enc_i1_probe.mjs`（`node:vm` 切**真实源码**，38 断言，三处变异实红）+ `tests/test_encounter_i1_consistency.py` 端到端一致性。门禁：**1109 passed + 1 skipped**（非 server 半 881 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`）；ruff 0 / mypy `--strict` 0 / Go 8 包全绿 / 全 `tools/*.mjs` 零漂移。**Android 需覆盖安装 v5.11.0 生效**（改动含 `static/`）。**已知小限制（非阻塞）**：I-1 测试的 known 集合未按 `deck-bridge` 剥冠词规则构造（强形式断言已覆盖口径一致性）；`pyproject.toml` 的 mypy `exclude` 含裸子串 `build` 致 `tools/build_*.py` 目录模式漏检（既有配置缺陷，待单独立项）。

- [x] **v5.12.0**：**遇见区「已读状态 + 推荐顺延」**（2026-09-24，PR #65，`/vault-spark` → `/vault-plan` → `/vault-exec` **3 Task 全绿 + 3 轮 REVISE**）——补上 v5.11.0 推荐机制**自造的新需求**：「读过没」此前不是一等状态，而推荐基于覆盖率、与读没读过无关 → 用户按推荐读完那篇后推荐**不顺延**（可能反复推同一篇）、列表也看不出进度（4 篇时不明显，7 篇起是主诉求）。① **打开即记已读**：`openText` 渲染成功后写 `localStorage["delector_encounter_read_v1"]`；键名用 `delector_` 前缀是**有意的**——`static/js/cards.js` 的**前缀即备份契约**（`delector_`/`wb.` 随备份导出+还原，`enc.` 是设备本地偏好），故已读**自动随备份迁移**且 `cards.js` 零改动；存时间戳（`{v:1, read:{id: tsMs}}`）为「最近读过/读几次」留扩展位。② **列表显示**：卡片带 `已读` + `.is-read` 轻降权；标记置于 `.encounter-card-meta` **段内部**（**不新增 `.encounter-card` 的 grid 子项**，避免破坏 v5.11.0 的 4 列布局）；**排序不变**（不叠第二层排序）。③ **推荐顺延**：`renderI1Hint` 改用 `pickUnread` 跳过已读——i+1 读完 → 「i+1 都读完了，试试《X》（偏简单 96%）」；本就一篇 i+1 都没有 → 中性「试试下一篇：《X》」；全部读完 → 「N 篇都读过了」；未背词 → 引导文案**优先**；`ranked` 空/非数组 → 隐藏（回到 v5.11.0 行为）。④ **工程**：新增零依赖纯函数 `static/js/enc-read.js`（`loadRead`/`markRead`/`isRead`/`unmarkRead`/`pickUnread`，与 `enc-i1.js` 同纪律）+ 行为探针 `tools/wb_enc_read_probe.mjs`（`node:vm` 切**真实源码**，35 断言；三项变异实红：去幂等早退 / `pickUnread` 返首条 / `loadRead` 坏 JSON 改 throw）。⑤ **服务端零改动**（无新端点/表/迁移）；**已读本机判定**（不走 LAN 同步，跨端不一致为已知限制）。门禁：**1119 passed + 1 skipped**（891 + 228；2 条既有 Windows 环境失败 `no such table: exam_trials`）/ ruff 0 / mypy `--strict` 0 / Go 8 包全绿 / 全 `tools/*.mjs` 零漂移。**Android 需覆盖安装 v5.12.0 生效**（改动含 `static/`）。**已知限制**：`backToList()` / `refreshList()` 复用列表渲染时只补 `readState`、不重算 i+1 排序与徽章（保持 v5.11.0 既有行为，属有意的最小修复）。

- [x] **v5.12.1**：**工程债收口（真门禁 + 依赖升级 + 测试隔离）**（2026-09-26，PR #66 / #67 / #68）——**本版无用户可见改动**（`static/` 相对 v5.12.0 **零差异**，四平台制品功能等同 v5.12.0），发版目的是把"门禁在跑、但判别力是假的"这一类缺陷连同依赖面一起收干净。① **路由守卫去对象身份**（`chore/toolchain-guards`）：比对键从「端点函数**对象**」改为 **HTTP 语义键** `(完整 path, METHOD)`（已注册侧取自 `app.openapi()["paths"]`，文档化契约、跨版本稳定）→ 对上游 `include_router` / `APIRoute` 实现漂移**免疫**；判别力反证：临时从 `delector/routes/__init__.py` 摘掉一个模块的 `include_router` → 守卫必红且 `missing` **只列该模块 5 条**（改造前是"全量 115 条"**误报**），`cp` 还原后逐字节一致。② **mypy 真覆盖**：`pyproject.toml` 的 `exclude` 从**裸子串** `build` 锚定为 `(^|/)build(/|$)` → `tools/` 全部 **11** 个 `.py` 纳入 `mypy --strict`（覆盖 **62 → 68** files），4 个产包脚本的 **47** 个注解债清账至 0（**仅注解、零行为**）。③ **依赖升级 + 撤销 dependabot ignore**：`fastapi 0.136.3 → 0.141.1`（starlette 保持 `1.6.0`，唯一变量是 fastapi）——**前置是"守卫已免疫 + 基线真绿"**，因此 2026-09-09 v5.4.0 发版 CI 三平台全炸的那类漂移不再复现；同时**撤销** `.github/dependabot.yml` 对 fastapi/starlette 的 `ignore`，恢复"周更提 PR + `ci.yml` 全量门禁兜底"，并在注释里留下立场：**再遇同类问题优先修守卫，而不是加 ignore**。④ **测试库隔离（真根因）**：消除跨模块 `DATABASE_PATH` / `PROGRESS_DB_PATH` 环境串扰（模块级 env 抢占 + 删库 → 空库 `no such table: exam_trials`）→ **半 A 首次 `0 failed`**；并新增**根因级 AST 守卫**（禁止测试模块在模块级直赋库 env），防止同类回归。⑤ **黄牌收口**：I-1 一致性测试的 known 集合改按 `deck-bridge.js` 生产语义构造（**剥冠词 + 小写**）+ 冠词表**双向同源守卫**（改任一侧即红）；变异自检表去重；`android/app/build.gradle` 补写 `fastapi<0.100.0` / `pydantic<2.0.0` 的**分离理由**（Chaquopy 只能装纯 Python 依赖 → pydantic v2 需 Rust 的 `pydantic-core` → 锁 v1 → fastapi 连带 <0.100；**勿照桌面 `requirements.txt` 对齐**）。门禁：**1124 passed + 1 skipped**（分半：非 server **896** + `test_server` **228**）/ `ruff check .` 0 / mypy **两道**（`delector`+`tools` 68 files、`tests` 69 files）均 0 error / 全 `tools/*.mjs` 探针零漂移 / Go 8 包全绿。**无需 Android 覆盖安装**（无 `static/` 改动）；桌面端亦无行为变化。

- [x] **`server.py`** **拆分重构**（v4.6.4）：3053 行单文件拆为 `nlp.py`（NLP/CEFR/文本分析）、`database.py`（DB/CRUD/备份）、`security.py`（SSRF/URL 安全），`server.py` 保留路由骨架。依赖图无环，319 测试全绿。

- [x] **介词矩阵「已入卡」持久化**（v4.6.4）：新增 `prep_saved` 表 + `GET/POST /api/prep/saved`，前端 `_prepSavedKeys` 从服务端初始化，重进矩阵段按钮状态保持。

- [x] **局域网同步 6 位短码**（v4.6.5）：WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 改为 6 位短码中转（`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`），手机上只需输入 6 个字符。

- [x] **歌德 A1 备考工坊**（v4.7.0）：官方考纲 702 词 + 15 大交际主题 + 8 篇官方填表真题与评分容错 + 10 篇 30 词短电邮写作工坊与 3 大导向点合规诊断 + 口语 Teil 2/3 考场题卡。

- [x] **Phase 2b（2026-09）：Go Agent Runtime 绿色便携包**——`delector run` 起 Python NLP 服务（supervisor 退避重启 + 健康探针 + Unix SIGTERM 优雅关闭 / Windows Kill）；自研 goroutine/channel DAG 调度 article-analysis 预设（4 层口径 ingest→[analyze,tts]→writing_check→export）；5 工具注册（golden 防漂移）；go-openai DeepSeek 客户端。**分发形态**：Go 单二进制 × Python venv 跨平台便携包（`agent/scripts/package_agent.py`，产物 `delector-agent/{delector,python,delector-src}`，压缩 ~65MB），三平台 CI `build-agent.yml` 自动出 artifact（**预览通道**，不打 tag 不发布；替换桌面版决策留 Phase 3）。Go 1.26.5；`go test -race ./...` 与 `go test -tags integration` 真实 uvicorn→spaCy 全链路为门禁。

- [x] **遇见区 P0 · Sub-Plan A（2026-09-07，分支 `feature/encounter-job1`，A1–A7 `d5c1155..2d78c09`）**：手选分级短篇 → 阅读视图按本机 deck 把**已背词高亮** + 覆盖统计 → 生词点选本地词典释义 → 一键进卡（写回 deck + wb 同步）→ 读完会话小复习。落地：`encounter_texts` 库 + `/api/encounter{list,detail,add,annotate,import-pack}`（`encounter-pack/v1` 契约，import 幂等）+ `view-encounter` SPA（`encounter.js`/`deck-bridge.js`）。测试基线 **673 全绿 + 1 skipped**。master 门禁（含 Go DAG job#1 import-pack 真链路）留 Sub-Plan B。

- [x] **Go DAG job#1 真执行 · Sub-Plan B（2026-09-07，分支 `feature/encounter-job1`，B1–B8 `a1e4245..13d8535`）**：agent 从「只装配」变**首个真执行 job**——`delector job run encounter-pack` 扫本地语料 → 去重/限量/并发逐篇 DAG（analyze→vocab_stats→DeepSeek gloss→export_pack）→ 可选投递 `POST /api/encounter/import-pack`。落地：`internal/corpus` / `internal/job`（Pack schema、TokenBudget、gloss、DAG、runner）/ cobra 接线 / `-tags integration` 真链路门禁（`TestEncounterRealChain` PASS）。Go registry + Python 工具清单升至 **6 工具**（新增 `vocab_stats`）。Python 全量 **686 passed + 1 skipped** 零回退；`go test -race ./...` 与 `-tags integration` 全绿；CLI dry-run + 真实 run（stub LLM）冒烟退出 0。真实 DeepSeek 冒烟档 PENDING-作者（桌面无 key）。
