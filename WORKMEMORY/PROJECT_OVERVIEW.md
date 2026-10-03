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

- **最新发布 v5.12.1（2026-09-26）** —— 工程债收口（**无用户可见改动**，四平台制品功能等同 v5.12.0）：路由守卫改 **HTTP 语义键** `(path, METHOD)` 比对、mypy 覆盖扩至 `tools/build_*.py`、`fastapi 0.136.3 → 0.141.1` + 撤销 dependabot `ignore`、测试库跨模块 env 串扰修复。
- **测试 / 门禁基线（截至 v5.12.1）**：全量 **1124 passed + 1 skipped**（分半：非 server **896** + `test_server` **228**）；`ruff check .` 零告警；`mypy --strict delector tools`（68 files）零错误 + tests 适度档；Go `vet` / `gofmt -l` / `test -race`（8 包）全绿；`tools/*.mjs` 探针零漂移；pre-commit 密钥守卫有效。
- **v5.12.1 之后的未发版批量（PR #69–#84，已合入 master 即 HEAD=`e61a409`，尚未发版）**：
  - **ADR-0016 统一池 Phase 3（#75）**：把「我的词汇」改为统一池的**幂等派生态**（范围闸只收已学 `reps>0` 或自建），接进 `save_wb_state` 同事务（投影失败则 blob 也不写），新增只读对账；顺带修两处备份/还原真 bug（漏 Phase 1 新列 → 静默丢 `source`/`fsrs_*`）；T3 跳过（与 wbsync local-first 冲突）。
  - **i+1 known-lemmas（#77）**：`known-lemmas` 端点补 `OR fsrs_s > 0`——Phase 3 只把词「放进池」、消费面看不见，工作台背过的词仍不算「已知」。
  - **测试库隔离收口（#78）**：共享 `tests/db_cleanup.py::remove_db_files` + `db_conn` 取代 17 份复制粘贴；决定性变异证明旧实现**静默残留**（假红/假绿）。
  - **Docker/WAL 修复（#69）**：`Dockerfile` CMD 改 `delector.server:app`（原 `server:app` 容器启动即死）+ `PRAGMA journal_mode=WAL`；备份/还原改 SQLite backup API（WAL 下文件级拷贝必 `disk I/O error`）。
  - **docs 约定收口（#81–#84）**：`.gitignore` 忽略 `.worktrees/` 与 mypy/ruff 缓存；`docs/plans/` 归档分层（52+15 份进 `archive/`）；`docs/README.md` 立为**目录约定正主**；ADR 副本拆入 `docs/adr/`；移除失真的 `release-v2.1.md`。
  - 另有：**#70** Android pydantic-v1 运行时契约守卫、**#71** 长难句 `source=all` 热请求不再读正文 + `_RANK_CACHE` 容量上限（实测推翻原 P1 严重度）、**#76** 统一池身份键口径修正（归一在**比较侧**，避免改动双用途 `lemma`）。
- **产品能力（截至 v5.12.1）**：精读（分词 + 语法雷达）+ 词汇/卡片工作台（FSRS；A1/A2/B1 + 核心/生词档）+ 备考域（A1 读写听说、听力微训、长难句精读）+ 遇见区分级短文（7 篇，已背词高亮 + i+1 就近选材 + 已读状态）+ 检索（词条/例句/搭配/语料）+ 写作润色台 + LAN 静默同步。各功能细节见 `FEATURES.md` 与 `WORKMEMORY/cold/digest-2026-09.md`。

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
- **本批未发版改动**（见上「当前状态」）待发版决策（含 `static/` 者需五件套 + Android 覆盖安装）。
- 递延项：tests `--strict`、检索 `_highlight` 的 HTML 实体边界、残留 worktree / 已合并本地分支清理。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
