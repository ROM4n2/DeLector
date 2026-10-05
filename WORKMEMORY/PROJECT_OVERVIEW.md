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

- **最新发布 v5.14.0（2026-10-05）** —— **韧性 / 前端竞态 / KARTEI 去复习化**（6 席 swarm 审计落地 5 子计划 + 3 组清债，含两个 P0）：卡盒「白复习」消除（#98，工作台词**可见但不可复习**：收走四个 DSR 按钮、保留 `mastered` 徽记 + 去工作台跳转）；`openText` 重入守卫 / 弹层向上翻转 / 列表详情 deck 同源（#97）；TTS 并发闸 `Semaphore(k=4)` + 429（#95）；真健康端点 `/api/health`（原探针拼错 `/api/tools/`）；目录视图改用 `cardStatsTag`、`fetchKnownLemmas` in-flight 去重、覆盖率行标注降级来源（#99/#100）；27 个探针全接进 pytest + 显式装 Node 20 + 防漏接线守卫（#101/#102）。**含 `static/` 改动 ⇒ Android 需覆盖安装**。
- **测试 / 门禁基线（当前 master，v5.14.0 之后）**：全量 **1299 passed + 1 skipped**（分半：非 server **1035** + `test_server` **264**）；`ruff check .` 零告警；`mypy --strict delector tools`（**70** files）、`mypy --follow-imports=skip tests`（**92** files）零错误；`tools/*.mjs` 探针 **28/28** 零漂移；`test_writer_mobile.py`（发版守护）**30 passed**；**新增守卫**：`test_probe_wiring_guard.py`（防漏接线，**5 passed**）、`test_probe_json_contract.py`（探针 `--json` 契约冻结，**5 passed**）、`test_localhost_guard.py`（受 `_require_localhost` 保护路由集合，**20 条** allowlist）。
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
- 递延项：tests `--strict`、检索 `_highlight` 的 HTML 实体边界、残留 worktree / 已合并本地分支清理。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
