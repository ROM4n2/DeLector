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
- 递延项：tests `--strict`；`tools/vault-proactive-scan.py` 的三条版本正则**本身无自动化守卫**（Task 2 修掉的那个"正则永不命中"缺陷恰是无人守的类型）。
- **⚠️ 红 master 事故已修（分支 `fix/cold-start-segment-gate`，2 commit `c36d420`/`5c85c13`）**：PR #117 **在 CI 未跑完时被合并**（04:28:53）⇒ 红色提交进了 master。根因：`test_segments_satisfy_physical_containment` 把**跨进程/不同前置状态**的两个量（probe A 的独立 `init_db()` vs probe B import 后再调第二次 `create_app()`）的**大小关系**当成了不变式（本机 148/245 同向通过、CI 210/95 反转）。已删两条跨进程量级断言、改为**机器无关自检**（`init_db_tables`/`app_ready_db_tables`/`app_ready_fresh_db_used` 等，取最小轮、**probe A 与 probe B 对称**），口径文本据实改写为"不可按大小关系解读"。**教训：合并 MUST 等 CI 绿；凡"不同进程/不同前置状态测得的两量"的任何大小关系，默认都不是不变式。**
- 递延项（本轮测量挖出）：① ~~迁移闸条件① `isfile` 不看 `size`（新位置 0 字节 + 旧位置有数据 ⇒ 静默放行）~~ → ✅ **已修**（判据对称化：新位置也要求**非空**；补 3 条用例含"桌面端同地 + 共享库 0 字节"这条新可达路径；**连带**把 `bench_cold_start` 的中和手法从"预置 0 字节库"改为"摆一个非空合法 SQLite 库"，并同步 `docs/agents/ops.md` 的旧表述）；② ~~`rank_sentences`/`analyze_syntax_tree` 纯函数单价未测~~ → ✅ **已补测**（新增 `tools/bench_rank_sentences.py` + 27 条门禁：`analyze_syntax_tree` **≈7~8ms/句**、`rank_sentences` **≈8ms/句**（`sm`，`model=` 行可复核）⇒ **2.1ms 低估约 3.6~4 倍**、**42ms 无法由纯函数口径解释**、与端到端 ≈10ms/句**同量级**；20 倍成因收窄为三候选（md / 冷启动摊薄 / 别语料-别函数），见 ADR §8 `Unknown 7`）；③ ~~`target_*` 假设目标值未确认~~ → ✅ **已解决**（2026-10-09 用户拍板：冷启动 2.0s / 卡盒 1.0s / 长文冷读 1.5s / 热读为**哨兵**不参与判定）⇒ 条件② 已按确认目标复算 = **不成立**，且门已补**修法路由**（仅冷启动超标 ⇒ O0 杠杆惰性加载，非 O2）；④ ~~`import_ms > app_ready_ms` 在纯 Python 回退下余量塌陷~~ → ✅ **已解决**（PR #119 证明该式是**结构性**不变式：余量来自**模块图导入**而非模型加载，与 spaCy 是否可用无关；已改为无条件断言 + 补路径标签同源守卫）；⑤ **冷启动端到端 p95 → ⏸ 已决定暂缓**（2026-10-10，用户：**不引入新依赖，收益不大**）—— 现 2.6s 是"到 `/api/health` 200"的**代理口径**（非首屏可用）；补测需引入**浏览器自动化基线**（本仓无）⇒ **不做**，故 **O0 结论建立在代理口径上**（该限制已在 ADR §7.5 / §8 `Unknown 8` 与输出 `scenario_scope_note` 声明）；若将来重开，按 ADR §7.6 修法路由：端到端 >4s 走 **O0 杠杆（惰性加载）而非 O2**。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
