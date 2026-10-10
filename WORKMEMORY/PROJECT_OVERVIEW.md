# PROJECT_OVERVIEW — DeLector（60 秒 primer）

> 首次生成：2026-09-04（bootstrap 会话从 AGENTS.md / README / ADR-0005 提炼）。
> 维护约定：交接或重大里程碑后由当前 agent 就地更新，不追加副本；**细节下沉 `WORKMEMORY/cold/digest-YYYY-MM.md`**（按月 COLD 蒸馏）——本文件只留「全局认知 + 当前状态要点 + 红线 + 待办」。

## 一句话定位

**DeLector** = 德语精读 + 歌德/德福备考 Web App。FastAPI + spaCy + SQLite 单文件后端，原生 JS ES Modules 单页前端，
`python start.py` → `http://localhost:8000`。
三种形态共用同一后端：桌面 Python / Windows 便携版（PyInstaller）/ Android（Chaquopy）。技术栈细节与跨端互锁见 `docs/agents/architecture.md`。

## 必读锚点（按需深入）

- `AGENTS.md`（项目根）：**纯路由入口**（~30 行）——只有 WORKMEMORY 约定与文档路由，勿往它回填内容。
- `docs/README.md`：**docs 目录约定的正主**（分层与归档规则）。架构在 `docs/agents/architecture.md`，安全 / 环境 / 工作惯例在 `docs/agents/ops.md`。
- `FEATURES.md`：产品特性全览。
- `CHANGELOG.md`：**版本历史正主**（每次发版追加条目）。
- `docs/plans/`：在途实施计划；已交付的进 `docs/plans/archive/`（含 `-ledger.md` 执行台账）。
- `docs/specs/`：设计稿（`<日期>-<主题>-design.md`）；`docs/adr/`：仓内 ADR 副本（正式件在 vault `08-Projects/DeLector/01-ADR/`）。
- `WORKMEMORY/cold/`：COLD 层月度蒸馏（当前 `digest-2026-09.md`）；WARM 层 `archive/` 按 INDEX 主题索引按需加载。
- `.vault-exec-ledger.json`：/dfs-exec 任务台账。

## 当前状态

- **最新发布 v5.16.0（2026-10-06）** —— **修掉长期潜伏的性能缺陷 + 三处守卫加固**（PR #108/#109/#110）。**每次 GET 文章都重跑完整 spaCy**（Fog 2 根因：判据写死 `"3.4.0"` 而写入端两条路径都写 `"3.5.0"` ⇒ 判据恒真 ⇒ 惰性迁移退化成每次迁移；修法＝`PROCESSED_JSON_VERSION` 单一真相源，语义完整保留）。**CI 必需运行时清单显式化**（`rm` 全仓不存在、`bash` 判为平台相关，两者均不进清单）。**localhost 守卫加固**（关掉三个「将来会漏」的洞：字面 `router` 变量名、per-router prefix、闸调用别名；allowlist 20 条逐字未动）。**安全 posture：内网可信**（不加固 LAN 写端点）。Fog 3 的 16 处形式统一经裁决不做（其收益论证已被实测推翻）。
- **测试 / 门禁基线（截至 v5.16.0）**：全量 **1317 passed + 1 skipped**（分半：非 server **1053** + `test_server` **264**）；`ruff check .` 零告警；`mypy --follow-imports=skip tests`（**93** files）、`mypy --strict delector tools`（**70** files）零错误；`tools/*.mjs` 探针 **28/28** 零漂移；`test_writer_mobile.py`（发版守护）**30 passed**；**五条守卫**：`test_probe_wiring_guard.py`（防漏接线 5）、`test_probe_json_contract.py`（契约冻结 5）、`test_localhost_guard.py`（受保护路由集合 20 条 allowlist 7）、`test_get_endpoints_with_writes.py`（带写 GET 白名单 7）、`test_ci_hardening.py`（CI 必需运行时清单 21）。
- **本批已随 v5.13.0 发布的其它改动**：
  - **i+1 已知词池打通（#72）**：`known-lemmas` 补 `OR fsrs_s > 0`（工作台已学词纳入覆盖率），列表 + 详情同口径；`deck-bridge.js` / `encounter.js` 打通 i+1 与主背词路径。
  - **测试库隔离收口（#78）**：共享 `tests/db_cleanup.py::remove_db_files` + `db_conn` 取代 17 份复制粘贴，44 处句柄泄漏清扫；决定性变异证明旧实现**静默残留**（假红/假绿）。
  - **Docker/WAL 修复（#69）**：`Dockerfile` CMD 改 `delector.server:app` + `PRAGMA journal_mode=WAL`；备份/还原改 SQLite backup API（WAL 下文件级拷贝必 `disk I/O error`）。
  - **docs 约定 + 三层记忆（#81–#85）**：`docs/plans/` 归档分层（52+15 份进 `archive/`）、`docs/README.md` 立为**目录约定正主**、ADR 副本拆入 `docs/adr/`、移除失真的 `release-v2.1.md`；HOT/WARM/COLD 三层真正跑起来（逾期轮转 + 首份九月 digest + primer 瘦身）。
  - 另有：**#70** Android pydantic-v1 运行时契约守卫、**#71** 长难句 `source=all` 热请求不再读正文 + `_RANK_CACHE` 容量上限（实测推翻原 P1 严重度）、**#76** 统一池身份键口径修正（归一在**比较侧**，不改动双用途 `lemma`）、依赖 `starlette 1.7.0` / `uvicorn >=0.54.0`。
- **产品能力（截至 v5.14.0）**：精读（分词 + 语法雷达）+ 词汇/卡片工作台（FSRS；A1/A2/B1 + 核心/生词档，**工作台与主背词共享统一池**）+ 备考域（A1 读写听说、听力微训、长难句精读）+ 遇见区分级短文（7 篇，已背词高亮 + i+1 就近选材 + 已读状态 + 已知词池与主路径同口径）+ 检索（词条/例句/搭配/语料）+ 写作润色台 + LAN 静默同步。各功能细节见 `FEATURES.md` 与 `WORKMEMORY/cold/digest-2026-09.md`。

## 红线速查（详情见 `docs/agents/architecture.md` / `ops.md`）

1. NLP 降级路径**静默**切到纯 Python 时语法标注会**给错**（不是精度低，是错）——改标注逻辑前看 `nlp_engine` 字段。
2. `app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由，否则全 API 405。
3. Android 五项互锁（py3.10 / minSdk24 / spacy3.8.7 / CI spaCy pin / arm64-only）动一个查全部；`spacy.load("名称")` 在 Android 必炸，要用 `importlib.import_module(名称).load()`；`extractPackages` 三包缺一不可。
4. versionCode 编码 `major*10000+minor*100+patch`，有测试守卫；keystore 只从环境变量读，丢失即包名报废。
5. 发版先跑「版本面五件套」（sw.js / index.html / build.gradle / README / 本文件当前状态），`test_writer_mobile.py` 两条测试锁死；tag 必须打在含 bump 的 commit 上。
6. `?v=` 查询串已退役：缓存闸 = 服务端 `Cache-Control: no-cache` + 安卓 `static.version` 重解包。
7. 敏感设置与删除操作仅 127.0.0.1 可写（`_require_localhost`），局域网 403；新端点遵守该闸。
8. pre-commit 密钥扫描必须启用，禁 `--no-verify`。
9. import 期不得联网、不得抛异常（Android 启动卡死的历史根因）。
10. 切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现，别造第二份。
11. 跨边界契约（前端 body ↔ 后端模型）必须行为探针验证，字符串存在断言是死测（2026-09-02 事故）。
12. 「上游 → 本地词表/精读生词」同步 MUST 只增 + 只补空 + 幂等，闸门按「能力」判定（MUST NOT 按历史来源标记）；补字段 MUST NOT 跨语义来源混用（生词原句 vs 官方例句）。详情见 `docs/agents/ops.md`「存量富字段回填规范」+ Coding Vault `01-Rules/STORED-DATA-BACKFILL`。

## 开放待办

- **真实用户试用（当前最高价值动作）**：手机端开箱即有 7 篇 A1/A2/B1 分级短文——收三问反馈（分级是否合适 / 已背词高亮与一键进卡是否顺手 / 本地词典释义够不够用），用反馈决定下一步。
- **Android 真机点检**：凡改动含 `static/` 的版本需覆盖安装验证（清单见 `docs/agents/ops.md`）。
- **预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY` 缺失；注意 `import_encounter_pack` 按 `pack_id` 幂等**不更新**既有行。
- **⏸ 更新可见性（ADR-0017）：桌面端已上线 / Android 端暂缓**（用户 2026-10-08 决定"先暂缓安卓"）。代码**已合入 master**（PR #115/#116 → `ee68ec8`，master CI success）：`delector/core/version.py: APP_VERSION` 单一真相源、`GET /api/update/check`（GitHub Releases 唯一真相源 + 成功 6h / **失败 60s** TTL + 3s 超时 + **不挂本机闸**＝ADR §4.3 显式决定）、顶栏 chip + `wb_update_chip_probe.mjs`（11 场景）。实测基线：半 A **1106** / 半 B **264**+1 skipped / 探针文件 **29** / mypy **96**+**72**；**桌面侧真实出网已验证**（4.04s 取到 `v5.16.0`）。
  **⚠️ 暂缓 ≠ 已验证：Android 端能力未知**（两条假设从未验证）——① Chaquopy 上 httpx 能否完成到公网 `api.github.com` 的 **HTTPS**（手机现有出网是 **LAN HTTP**，不是证据）；② Android WebView 点 chip 外链是否交给系统浏览器。**不得**把"代码已合并"记为"双端已验证"；恢复验证时见 work.log 2026-10-08 事件与 ADR §7.3。
- **✅ 性能路线（ADR-0018 D1 已执行完毕 → 结论 O0）**：判定门定案 —— 条件① **成立**（加权 Python CPU 代理占比 **85.9%**）／条件② **不成立**（四场景 p95 距 2× 目标余量 0.35×~0.0001×）⇒ **AND 不成立 ⇒ 走 O0（维持现状 + 便宜杠杆）**，**不做**热点下沉也不用扩 ADR-0008 边界。**"换 HTTP 主体"永久否决**（三条依据 + 三条翻盘条件见 ADR-0018 §3.2）。分支 `perf/measurement-baseline`（6 commit）：五个基准 + 五个门禁（`bench_cards_endpoint` / `bench_spacy_unit` / `bench_long_read` / `bench_cold_start` / `bench_profile_layers` + `bench_stats`）。实测：卡盒 p95 0.696s（Python 侧 84%）、长文冷读 122ms 热读 17.7µs（缓存生效）、spaCy 稳态 7.1ms/句、冷启 2.6s（其中 spaCy 模型加载 1.47s 占 57%）。
- **✅ Windows 桌面端（ADR-0019，2026-10-10 拍板：Q1-A / Q2-A / Q3-B）**：**不换壳、不做安装包、不改技术栈**。要的"独立窗口 + 任务栏图标"由**仓库里现成的 PWA** 零代码提供（`static/manifest.json` 已 `display: standalone`；`static/js/main.js:1138-1140` 注册 `/sw.js`）⇒ **先在 Edge/Chrome「安装此站点为应用」试用一周**；**若装不上，第一件事是补 192/512 的 PNG 图标**（当前是内联 SVG，Chrome/Edge 通常要 PNG 才给安装提示）。本轮**唯一真动的是数据目录外置**到 `%LOCALAPPDATA%\DeLector`（默认外置 + 保留便携开关可回退到"数据随程序目录"）—— 因为 `database.py:35` 桌面端无 `DELECTOR_DATA_DIR` 兜底 ⇒ 数据落在解压目录，而迁移闸条件④桌面端恒等 ⇒ **"升级时解压覆盖/删目录 = 学习记录全空且零提示"**（四项摩擦里唯一真会丢东西的）。**明确不做**：原生窗口壳（webview，会丢 DevTools/扩展且退出不保证 uvicorn 收尸）、安装器（与 Vault 里 Hermes「提权安装器 + OWNER RIGHTS ACL 失守」事故同构，且卸载器会连 `_internal` 一起删走数据）、开机自启（沉浸阅读是主动场景 + LAN 面无鉴权）、`--windowed`（须先配齐 `launch.log` + 失败弹窗 + 托盘，否则是静默失败）。
- **✅ Windows 桌面壳（ADR-0020，2026-10-10 拍板：Q5-A / Q6-A）**：**用户试用现成 PWA 后判定"独立窗口不够用"** ⇒ **ADR-0019 Q1 的前提被实测推翻**，外壳议题独立成篇。采纳 **`pywebview`（走系统 Edge WebView2）+ `pystray`（托盘）**，**Python + FastAPI 仍是 HTTP 主体 ⇒ 不违反 ADR-0018**（那条否决的是"换主体"，不是"换宿主"）。**约 350 行**（`desktop.py` ~150 / `start.py` ~50 / 打包+CI ~30 / 测试 ~120）；体积 75MB → **80–90MB**；冷启动 2.6s → **3.5–5s**（首次建档 5–8s）。**四个必须一起做的前置**：① **退出收尸**（现 `start.py:86-102` 只有 `server.run()`，退不干净 ⇒ 下次盲复用端口 = "以为升级了其实跑旧进程"的静默失败）⇒ 改为 webview 主线程 + 同进程非 daemon server 线程 + 退出统一 `should_exit` + 5s graceful + join，且 health 要校验 DeLector 身份与版本；② **启动反馈**（原生 splash + 分阶段；health 轮询要有单次超时/退避/总截止时间，现端口探测无超时）；③ **WebView2 运行时检测**（Win11 通常自带、**Win10 不保证** ⇒ 打破"零依赖/解压即用"，需启动前检测+引导）；④ **日志与失败弹窗**（桌面形态下 stdout 不可见）。打包要点：复用现有 Windows 产物**不新增第 5 个位点**（前提是**不另建 spec / 不产第二产物**），但需 `--collect-all=webview` + hidden-import + **验包 `WebView2Loader.dll`**（漏了就白屏，与既有事故同款）。**执行顺序（Q6-A）**：① 数据外置 → ② 手动检查更新入口 → ③ 桌面壳。**YAGNI**：Tauri/Electron、CEF（+100MB）、安装器、开机自启、应用内安装更新、多窗口。
- **✅ 语言选型（ADR-0021，2026-10-10 拍板：Q1-A / Q2-A）**：**继续 Python 主体**（FastAPI + uvicorn + spaCy + 原生 JS + pywebview 桌面壳），**不换 Rust/Go 主体、不做 Python→sidecar 降级**。判据写死：**语言选择以"运行时/交付"为判据；"编辑期少犯错"用工具纪律（闸/类型覆盖率/CI）解决，不作为换语言的判据**（补上 ADR-0018 §3.2 只看运行时性能的判据缺口）。**核心证据（可复跑）**：把本会话 **14 条真实缺陷**逐条判定"编译器/类型系统能否在编译期抓住" ⇒ **a+b = 3 条（21%：① 全量类型覆盖 ② 平台条件编译 ③ 模块登记面）**，**c = 11 条（79% 换语言照样犯：P0 GUI 时序死锁 / 窗口塞错 / 数据目录策略 / 红 master 的测试设计错 / 双重舍入 / 不可证伪结论 / 假引用 / 陈旧构建 / GBK 编码 / shell 转义）**。**三条硬否决**：① spaCy 无 Go/Rust 等价物 ⇒ 换主体只退化出"两套 runtime + IPC"（vault 已判 `cgo` = 交叉编译噩梦 + Windows DLL 链接地狱）；② **Android 端永久否决** —— `android/app/build.gradle:83-93` 显示 **Chaquopy 只能装纯 Python 依赖、编译不了原生扩展**（`pydantic v2` 因 `pydantic-core` 是 Rust 被锁回 v1）⇒ "Rust/Go 主体 + spaCy" 无落地路径，ADR-0018 §3.2 条件③**不可满足**；③ 换语言会**削弱交付物自省**（本仓多数事故靠读产物/读构建脚本/读注册表发现，静态二进制下产物是 blob）。**机会成本**：100–300 人日 ≈ 3–10 个月，期间产品 0 前进，且**移植期失去 1505 条测试的安全网**（65 个测试文件白盒 `import delector.*`）。**替代投资（=本 ADR 的实施，按优先级）**：① **⭐ CI 真启产物闸**（`build-release.yml` 目前对产物**零验证**，只 pytest 后打包 ⇒ 这是唯一能在作者双击前抓住本次 P0 的闸：启动 → 校验 DeLector 身份 → 断言 ≤N 秒干净退出）；② `mypy --strict` 收尾（需先换掉 `start.py` 两处 `unused-ignore`）；③ `static/`（33k 行）加类型检查（JS↔Python 才是真跨边界）；④ spaCy 惰性加载。**Fog**：CI 无 GUI ⇒ "真启产物闸"能否覆盖**窗口形态**未验（可能需 `--server-only` 口径 + 真机 HITL）。
- **✅ 登记项处置（2026-10-10，用户拍板 1A/2A/3A/4A/5A）**：① **冷启动 2.0s 未达 → 接受并改口径**：本机 2128ms（−32% 后），残余是 **`import spacy` 库导入本身**（≈1.09s），**机器依赖**（磁盘缓存/杀毒/负载敏感），不再为 125ms 投入；**惰性化 `syntax_tree.py` 不做**（会动运行时 `isinstance` 与红线 1 的降级判据，收益不完整）。② **难度跳变 → 构建期预生成**（已实测 4 篇预置里 **2 篇会降一级**：A2→A1、B1→A2；粗估**偏难**）：新增 `tools/gen_preset_processed.py` ⇒ `delector/data/preset_processed.json`（456KB/4 条目/按文本哈希索引/含 `version`）⇒ 落库直接 spaCy 口径 ⇒ **跳变消失**；未命中 ⇒ **可见 WARNING** 回退（不许静默降级）；三个打包位点显式 `--add-data`，产物闸加"真产物内含该文件"断言。③ **基准 `proc_path` 静态声明值**三处（`bench_cold_start` / `bench_long_read` / `bench_rank_sentences`）全部改为**按真实加载状态判定**（不主动触发加载），门禁升级为 AST+行为级。④ **Win10 WebView2 → 已知限制**：检测+官方 Evergreen 短链已有，Win10 需先装运行时（**打破"解压即用"**，不捆绑固定运行时以免 +100–150MB）。⑤ **首屏数字 → 加真口径**：`desktop.py` 落"进程级计时起点" + pywebview **`loaded` 事件**的"真实 UI 已加载（首屏可用）"，新增 `tools/first_screen_from_log.py` 解析 `launch.log` 算端到端首屏 ⇒ **双击一次即可取得真实首屏**（Defender 待扫一次）。
- 递延项：tests `--strict`；`tools/vault-proactive-scan.py` 的三条版本正则**本身无自动化守卫**（Task 2 修掉的那个"正则永不命中"缺陷恰是无人守的类型）。
- 递延项（ADR-0019 登记，**未开 frontier**）：① PWA 安装提示是否出现（一次性验证即可消除，不出现就补 PNG）；② `start.py:61-67` 端口 8000「被占用则复用」**不校验对方是不是 DeLector** ⇒ 单实例应靠**文件锁**（pid + 版本 + 数据目录）+ `/api/health` 身份校验 + 顺延 8001–8010，而非端口探测；③ 桌面端 LAN 绑 `0.0.0.0` **维持现状不改**（"同 Wi-Fi 手机可访问"是有意特性），**已知该面无鉴权、部分写端点不打 `_require_localhost` 闸** ⇒ 这正是"开机自启被否决"的理由；将来若做常驻/自启，必须先改为默认 `127.0.0.1` + 显式开关；④ 数据自动迁移的 **WAL 边界**（只搬 `delector.db` 不带 `-wal`/`-shm` 会丢最近写入）⇒ 实施前必须验证。
- **⚠️ 红 master 事故已修（分支 `fix/cold-start-segment-gate`，2 commit `c36d420`/`5c85c13`）**：PR #117 **在 CI 未跑完时被合并**（04:28:53）⇒ 红色提交进了 master。根因：`test_segments_satisfy_physical_containment` 把**跨进程/不同前置状态**的两个量（probe A 的独立 `init_db()` vs probe B import 后再调第二次 `create_app()`）的**大小关系**当成了不变式（本机 148/245 同向通过、CI 210/95 反转）。已删两条跨进程量级断言、改为**机器无关自检**（`init_db_tables`/`app_ready_db_tables`/`app_ready_fresh_db_used` 等，取最小轮、**probe A 与 probe B 对称**），口径文本据实改写为"不可按大小关系解读"。**教训：合并 MUST 等 CI 绿；凡"不同进程/不同前置状态测得的两量"的任何大小关系，默认都不是不变式。**
- 递延项（本轮测量挖出）：① ~~迁移闸条件① `isfile` 不看 `size`（新位置 0 字节 + 旧位置有数据 ⇒ 静默放行）~~ → ✅ **已修**（判据对称化：新位置也要求**非空**；补 3 条用例含"桌面端同地 + 共享库 0 字节"这条新可达路径；**连带**把 `bench_cold_start` 的中和手法从"预置 0 字节库"改为"摆一个非空合法 SQLite 库"，并同步 `docs/agents/ops.md` 的旧表述）；② ~~`rank_sentences`/`analyze_syntax_tree` 纯函数单价未测~~ → ✅ **已补测**（新增 `tools/bench_rank_sentences.py` + 27 条门禁：`analyze_syntax_tree` **≈7~8ms/句**、`rank_sentences` **≈8ms/句**（`sm`，`model=` 行可复核）⇒ **2.1ms 低估约 3.6~4 倍**、**42ms 无法由纯函数口径解释**、与端到端 ≈10ms/句**同量级**；20 倍成因收窄为三候选（md / 冷启动摊薄 / 别语料-别函数），见 ADR §8 `Unknown 7`）；③ ~~`target_*` 假设目标值未确认~~ → ✅ **已解决**（2026-10-09 用户拍板：冷启动 2.0s / 卡盒 1.0s / 长文冷读 1.5s / 热读为**哨兵**不参与判定）⇒ 条件② 已按确认目标复算 = **不成立**，且门已补**修法路由**（仅冷启动超标 ⇒ O0 杠杆惰性加载，非 O2）；④ ~~`import_ms > app_ready_ms` 在纯 Python 回退下余量塌陷~~ → ✅ **已解决**（PR #119 证明该式是**结构性**不变式：余量来自**模块图导入**而非模型加载，与 spaCy 是否可用无关；已改为无条件断言 + 补路径标签同源守卫）；⑤ **冷启动端到端 p95 → ⏸ 已决定暂缓**（2026-10-10，用户：**不引入新依赖，收益不大**）—— 现 2.6s 是"到 `/api/health` 200"的**代理口径**（非首屏可用）；补测需引入**浏览器自动化基线**（本仓无）⇒ **不做**，故 **O0 结论建立在代理口径上**（该限制已在 ADR §7.5 / §8 `Unknown 8` 与输出 `scenario_scope_note` 声明）；若将来重开，按 ADR §7.6 修法路由：端到端 >4s 走 **O0 杠杆（惰性加载）而非 O2**。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
