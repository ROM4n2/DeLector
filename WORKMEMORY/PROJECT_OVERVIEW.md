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

- **最新发布 v5.17.0（2026-10-11）** —— **首个原生桌面壳**（`pywebview` 走系统 WebView2 + `pystray` 托盘 + splash + 统一退出收尸；`v5.16.0` 里 `desktop.py` 根本不存在）**+ 首次数据落点外置**（默认 `%LOCALAPPDATA%\DeLector` + 一次性迁移，修掉唯一真会丢东西的摩擦「升级时解压覆盖 = 学习记录全空且零提示」）**+ 更新可见性上桌面端**（chip + `/api/update/check`）**+ 发版门守卫**（tag 必须 == `v`+`APP_VERSION`）**+ 真启产物闸 / 前端跨边界契约闸**（PR #111~#129，111 个提交；完整条目见 `CHANGELOG.md` 含回滚段）。已装用户拿不到那 6 条可感知修复（`static/` 内嵌在产物里），随本版到达。**known-issues 已明文进发行说明**：~2s 端口/身份校验（本版新引入，不当提速卖点）、`launch.log` 已知整行丢失（≈3%，整行非半行）、Android `versionCode` 不可回滚（`51700`）、Win10 需先装 WebView2。
- **上一版 v5.16.0（2026-10-06）** —— **修掉长期潜伏的性能缺陷 + 三处守卫加固**（PR #108/#109/#110）。**每次 GET 文章都重跑完整 spaCy**（Fog 2 根因：判据写死 `"3.4.0"` 而写入端两条路径都写 `"3.5.0"` ⇒ 判据恒真 ⇒ 惰性迁移退化成每次迁移；修法＝`PROCESSED_JSON_VERSION` 单一真相源，语义完整保留）。**CI 必需运行时清单显式化**（`rm` 全仓不存在、`bash` 判为平台相关，两者均不进清单）。**localhost 守卫加固**（关掉三个「将来会漏」的洞：字面 `router` 变量名、per-router prefix、闸调用别名；allowlist 20 条逐字未动）。**安全 posture：内网可信**（不加固 LAN 写端点）。Fog 3 的 16 处形式统一经裁决不做（其收益论证已被实测推翻）。
- **测试 / 门禁基线（截至 v5.17.0）**：全量 **1768 passed + 2 skipped**（分半：非 server **1471** + `test_server` **297**）；`ruff check .` 零告警；`mypy --follow-imports=skip tests`（**121** files）、`mypy --strict delector tools`（**87** files）、入口面 `--platform win32 --strict`（**4** files：`desktop.py package_windows.py conftest.py start.py`）零错误；`tools/*.mjs` 探针 **29/29** 零漂移；`test_writer_mobile.py`（发版守护）**30 passed**；**六条守卫**：`test_probe_wiring_guard.py`（防漏接线 5）、`test_probe_json_contract.py`（契约冻结 5）、`test_localhost_guard.py`（受保护路由集合 20 条 allowlist 7）、`test_get_endpoints_with_writes.py`（带写 GET 白名单 7）、`test_ci_hardening.py`（CI 必需运行时清单 33）、`test_app_version_source.py`（发版门 tag↔`APP_VERSION` 等 21）。
- **v5.13.0 批次的其它改动（历史留档）**：
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

## 开放待办（活项）

> 已接受 / 已推翻的历史裁决（ADR-0018~0021、登记项 1A~5A、红 master 事故、冷启动 2.0s 口径、性能路线 O0 结论等）已整体下沉至 [`cold/2026-10-12-settled-todos.md`](cold/2026-10-12-settled-todos.md)，此处只留活项。

1. **真实用户试用 + 宣传开闸门槛（2026-10-12 DECISION，`/dfs-grill` Track 1 收敛、不落 ADR）**：产品种草帖**延后**到四条门槛全绿 —— ① **≥5 份真实三问反馈**（入口已随 2026-10-12 批次落地：`.github/ISSUE_TEMPLATE/feedback.md` + README 下载表下直达链接；零门槛：不强制 `bug(scope):` 前缀、三道判断题、可选吐槽）② 新手「下载 → 打开 → 读到第一篇短文」连续无协助成功 ③ README 首屏含截图/GIF 与 Win10 WebView2 前置（见第 3 条）④ Android 真机点检通过（见第 2 条）。**内容先行不受限**：备考方法论 / 开发理念类帖子现在就能发；**产品演示类冻结至门槛绿**。宣传载体已定：**独立薄壳站点**（独立仓库 + 零构建纯静态 + `github.io`，版本运行时取 GitHub Releases API、不复述功能清单），域名后置。
2. **Android 真机点检**：凡含 `static/` 改动的版本需覆盖安装验证（清单见 `docs/agents/ops.md`）；同时验证 Android 更新 chip 的两条假设（Chaquopy 能否完成公网 HTTPS、WebView 点外链是否交系统浏览器）——即门槛④。**未验证前不得把「代码已合并」记成「双端已验证」**。
3. **README 首屏改造**（宣传线，门槛③剩余部分）：截图/GIF + 一句话价值 + 30 秒上手；当前首屏对非技术用户仍是代码仓库脸（badge 墙 + 版本摘要墙）。
4. **预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY` 缺失；`import_encounter_pack` 按 `pack_id` 幂等**不更新**既有行。
5. **递延项（未立项）**：tests `--strict`；`tools/vault-proactive-scan.py` 三条版本正则无自动化守卫；PWA 安装提示验证 / 192-512 PNG 图标；桌面单实例文件锁（pid+版本+数据目录 + `/api/health` 身份校验 + 顺延 8001–8010）；发布链路 runbook（Publish 被跳过 / 孤儿 tag 的恢复路径：Vault v5.4.0 复盘 + **v5.1.1 孤儿 tag 在案**；`gh workflow run --ref <tag>` 理论可补发但**本仓未实证**，判据只能是 release 资产清单）。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
