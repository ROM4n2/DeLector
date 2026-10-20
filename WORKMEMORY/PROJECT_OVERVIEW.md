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
- `WORKMEMORY/archive/handoff_audit-fixes-a-b.md`：**最近一份交接包**（closed 2026-10-17，含 12 条风险与坑 + 2026-10-17 进展补充）—— 新 agent 接手先看它。
- `WORKMEMORY/cold/`：COLD 层月度蒸馏（**当前 `digest-2026-10.md`**，覆盖 2026-10-02~10-16；另有 `digest-2026-09.md`）；WARM 层 `archive/` 按 INDEX 主题索引按需加载；超限事件正文在 `notes/`。
- `.vault-exec-ledger.json`：/dfs-exec 任务台账。

## 当前状态

- **最新发布 v5.18.0（2026-10-19）** —— **单体架构与前端视图全面解耦**（`database.py` 拆解为领域模块、`routes/main.py` 拆为 6 个领域路由；`workbench.html` 模块化、`index.html` 拆解为 layout/views/modals 并由轻量同步闸守护；`writer.js`/`reader.js` 纯逻辑闭包提取并冻结导出面）**+ 交互式智能体闭环**（ADR-0023 / 确定性裁判终审 / AI 润色与对齐）**+ A1 裁判集扩充与真题配对回测**（ADR-0024 / 60 局真跑标定真 token 与轮次分布）**+ 六道自动化机械闸矩阵落地**（分层契约闸 · 反向依赖闸 · Mock 漂移闸 · 禁止静默降级闸等）。全量测试从 v5.17.0 的 1,768 增长至 **2,438 passed + 3 skipped**（净增 670 条测试），探针 **31/31** 零漂移。
- **历史发布 v5.17.0（2026-10-11）** —— **首个原生桌面壳**（`pywebview` 走系统 WebView2 + `pystray` 托盘 + splash + 统一退出收尸；`v5.16.0` 里 `desktop.py` 根本不存在）**+ 首次数据落点外置**（默认 `%LOCALAPPDATA%\DeLector` + 一次性迁移，修掉唯一真会丢东西的摩擦「升级时解压覆盖 = 学习记录全空且零提示」）**+ 更新可见性上桌面端**（chip + `/api/update/check`）**+ 发版门守卫**（tag 必须 == `v`+`APP_VERSION`）**+ 真启产物闸 / 前端跨边界契约闸**（PR #111~#129，111 个提交；完整条目见 `CHANGELOG.md` 含回滚段）。已装用户拿不到那 6 条可感知修复（`static/` 内嵌在产物里），随本版到达。**known-issues 已明文进发行说明**：~2s 端口/身份校验（本版新引入，不当提速卖点）、`launch.log` 已知整行丢失（≈3%，整行非半行）、Android `versionCode` 不可回滚（`51700`）、Win10 需先装 WebView2。
- **上一版 v5.16.0（2026-10-06）** —— **修掉长期潜伏的性能缺陷 + 三处守卫加固**（PR #108/#109/#110）。**每次 GET 文章都重跑完整 spaCy**（Fog 2 根因：判据写死 `"3.4.0"` 而写入端两条路径都写 `"3.5.0"` ⇒ 判据恒真 ⇒ 惰性迁移退化成每次迁移；修法＝`PROCESSED_JSON_VERSION` 单一真相源，语义完整保留）。**CI 必需运行时清单显式化**（`rm` 全仓不存在、`bash` 判为平台相关，两者均不进清单）。**localhost 守卫加固**（关掉三个「将来会漏」的洞：字面 `router` 变量名、per-router prefix、闸调用别名；allowlist 20 条逐字未动）。**安全 posture：内网可信**（不加固 LAN 写端点）。Fog 3 的 16 处形式统一经裁决不做（其收益论证已被实测推翻）。
- **测试 / 门禁基线（截至 v5.17.0）**：全量 **1768 passed + 2 skipped**（分半：非 server **1471** + `test_server` **297**）；`ruff check .` 零告警；`mypy --follow-imports=skip tests`（**121** files）、`mypy --strict delector tools`（**87** files）、入口面 `--platform win32 --strict`（**4** files：`desktop.py package_windows.py conftest.py start.py`）零错误；`tools/*.mjs` 探针 **29/29** 零漂移；`test_writer_mobile.py`（发版守护）**30 passed**；**六条守卫**：`test_probe_wiring_guard.py`（防漏接线 5）、`test_probe_json_contract.py`（契约冻结 5）、`test_localhost_guard.py`（受保护路由集合 20 条 allowlist 7）、`test_get_endpoints_with_writes.py`（带写 GET 白名单 7）、`test_ci_hardening.py`（CI 必需运行时清单 33）、`test_app_version_source.py`（发版门 tag↔`APP_VERSION` 等 21）。
- **未发版（已进 master，2026-10-20）：前端单体继续解耦 + 分层闸纳管面扩展**（PR **#161** / **#164** / **#165** / **#166**，计划 `docs/plans/2026-10-19-reader-js-layer-split.md` · `2026-10-19-reader-api-layer-split.md` · `2026-10-20-cards-state-container.md`，设计稿 `docs/specs/2026-10-20-cards-state-view-decoupling-design.md`）。`reader.js` 抽出 `rd-syntax.js`（纯语法层）与 `rd-api.js`（L2 持久化层，14 个端点函数）；`cards.js` 的 **15 个模块级可变状态**收进 `cd-state.js` 纯状态容器，视图层顶层 `let` **15 → 0**（首次把视图层纳入机械约束，闸规则 ⑦）。导出面全程冻结（`reader.js` 40 个具名、`cards.js` 36 个 + 1 条 barrel 逐字不变），错误轨守恒（`reader.js` 10/10、`cards.js` 12/12）。
  ⚠️ **本批真正的产出不是解耦，是挖出两条与重构无关的既有静默失效**：① `ia_dom_mount_probe.mjs` 有 **4 条守卫一直是死的**（切片锚点只到函数名 ⇒ 切片里没有函数体 ⇒ 断言恒真），② 探针静态层已红时仍照样跑 `node:vm`，空源撞出的 `ReferenceError` 排在真实具名问题**后面**、把诊断引向渲染链（#166 修）。两者形态相同：**判据看着在跑，实际恒真**。纪律已写进 `docs/agents/architecture.md`「前端模块分层契约」节，动探针/守卫前必读。
  ⚠️ **计划写法教训（已在计划里更正）**：变异用例的注入锚点必须按**最终状态树**普查 —— Task 1 新造的锚点钉在 `let cardSegment = "due";` 上，而那正是 Task 3 要删的行，于是两条用例挂在「锚点命中 0 次」而不是挂在闸上。另：同一主机上并行子代理曾三次落在**错误血统**的 worktree 上并据此给出与事实相反的汇报，故后续派单一律要求「先 merge 目标分支并核实 HEAD」。
- **现测基线（2026-10-20，master `07139ac`；本次实测重算）**：全量 155 个文件 · 8 批串行全绿 = 收集 **2513**（**2511 passed + 2 skipped**）· `static/js` **36** 个模块 · `tests/test_*.py` **155** 个文件 · `tools/*.mjs` 探针 **31** 个 · `ruff` 零告警 · `mypy --strict delector tools`（**118** files）/ `mypy --follow-imports=skip tests`（**159** files）零错误 · 六道机械闸全 exit 0。
  - 重算：`python3 -m pytest tests/ --collect-only -q | tail -1`；`ls static/js/*.js | wc -l`；`ls tests/test_*.py | wc -l`；`ls tools/*.mjs | wc -l`。
  - ⚠️ 全量 MUST **分批串行**跑（本主机并行 python 会争抢数据目录守卫导致假红）。
- **现测基线（2026-10-19，master `4646a67` 发版基线；由本次发版实测）**：收集 **2441** 用例（**2438 passed + 3 skipped**，全量单条串行分批全绿）·`ruff check .` 零告警 · `mypy --strict delector tools`（**118** files）· `mypy --follow-imports=skip tests`（**157** files）· 入口面 `--platform win32 --strict`（**4** files）零错误 · `tools/*.mjs` 探针 **31** 个 · `static/js` **34** 个模块 · `tests/test_*.py` **153** 个文件。**六道机械闸**：`check_layer_invariants` · `check_mock_drift` · `check_silent_degradation` · `check_frontend_api_contract` · `check_frontend_layers` · `check_index_html_sync` 全 exit 0。
  - 重算：`python3 -m pytest tests/ --collect-only -q | tail -1`；`python3 -m mypy --strict delector tools | tail -1`；`ls tools/*.mjs | wc -l`；`ls static/js/*.js | wc -l`。
  - ⚠️ **本行已不是当前值**（v5.18.0 发版快照，收集 2441）。当前值看**上面那条「现测基线（2026-10-20）」**。v5.17.0 的 1768 passed 同理是历史快照 —— 读到时 MUST 以 2026-10-20 那条为准，MUST NOT 拿旧值做判断。
- **未发版（已进 master，2026-10-15）**：**ADR-0023 交互层「验证驱动 agent 循环」Task 0~6**（PR #136，7 个任务单元经 maker-checker 双席位评审）—— Go 门禁三红灯修复并接入 CI（含执行期新发现的「硬编码 8001 且不校验身份 ⇒ 真实风险是假绿」）、LLM 出网收口到 `delector/services/llm_client.py`（5 处裸 HTTP + 补 `max_tokens`）、循环内核 `delector/services/polish_loop.py`（收尾终审 / 不降即停 + argmin 回退 / 循环级 token+deadline 预算 / 零静默失败）、工具白名单 `polish_tools.py`（恰好 3 项只读 + 前置钩子）、`ai-polish` 返回契约新增 `converged`/`unconverged_reason` + SSE 逐轮进度/取消 + 未收敛 toast。**⚠️ 按 ADR-0023 §4.3 不得宣称「已实现」**：裁判集一行未扩，适用性闸门使循环的真实迭代价值目前只覆盖 A1 书信体。剩余活项：① 裁判集扩充（Unknown 1，第一瓶颈）② Android 真机点检（本批动了 `static/`，且 **SSE 的 `fetch`+`ReadableStream` 在 WebView 未验证**）③ 有 Key 后回测真实轮次分布与真 token 计数（折算系数 3.0 是 UNVERIFIED 假设）。
- **未发版（已进 master，2026-10-15 第二批）**：**ADR-0023 §4.3 第 ④ 步「裁判集扩充」**（计划 `docs/plans/2026-10-15-a1-judge-expansion.md`，8 任务全交付，PR **#137**）。裁判从 6 条书信格式/字数浅规则扩到 A1 语法层：**动词位置**（主句 V2 + 8 豁免）· **格的使用**（冠词-名词一致 / 介词支配格 / 动词支配格，29 条人工登记动词→格表）三条 error 级；**时态一致性**接线为 **advisory**（用户拍板）；**语序（情态框架）经实测评审判定不做**（FP 与 FN 同源）。同时把**闸门按规则族分流** ⇒ 语法族对**任意德语文本**生效（循环价值面不再只覆盖 A1 书信体），并把提示词按文本族参数化。§4.3 判据表 8 条实测后经用户签批：**采用限定表述，无条件「已实现」继续禁用**（第 8 条对照实验缺 Key 未做）。**排障经验已沉淀**：vault `99-Inbox/2026-10-15-规则引擎硬门必须按「类」覆盖正样本…md`（含"三次误报类全被官方样本集放过"与两条既有规则的新实例）。
  ⚠️ 本批最值得复看的产品语义变更：**非书信文本模型修不动语法错 ⇒ `no_improvement` ⇒ 回退原文**（前端给人话原因码；用户签批保持）。
- **未发版（已进 master，2026-10-16 第三批）**：**§4.3 第 8 条对照实验完成并签批**（计划 `docs/plans/2026-10-15-judge-gaming-experiment.md`，8/8；PR #139）。三臂配对 + 20 篇种子（每篇 1 信号 + ≥3 held-out 探针），**60 局真跑**（612s / 16,008 token）。**结论（ADR-0024，vault 正式件 + `docs/adr/2026-10-16-adr-0024-*.md` 镜像）**：阴性对照成立 —— `R_uncovered(last_candidate)` 的 **A2 ≡ A3 = 0.974（差 0.000）** ⇒ 裁判信号**只影响循环的验收、不影响模型行为**；**P1（奖励黑客）本形态下无发生机制**（非"未发现"）；§4.3 维持**限定表述**、无条件「已实现」继续禁用；「裁判结论回灌（verifier-in-the-loop）」设为**无条件**下一子计划。
- **未发版（已进 master，2026-10-16 第四批：审计修正 A + B）**：`docs/reviews/2026-10-15-swarm-audit-master.md`（2 P0 / 5 P1 / 10 P2）等 5 份评估报告 + `docs/reviews/2026-10-16-open-items-backlog.md`（18 项登记）。**A 档 8 项**（PR #143）：P0-1 `/api/backup/restore` 静默丢训练记录（已复现）、P0-2 退出挂死 + 假成功、P1-1 凭据键随备份外泄、测试库落点治因（**并拆除一颗无界递归进程炸弹**）、文档三处漂移对齐。**B 档 5 项**：B1 master 直推机械闸（#143 + #144）、B2 `.gitattributes` CRLF 契约、B3 design-system 补入口与过时更新、B5 harness 七件前置、以及 **B4（`docs/plans/2026-10-16-database-split.md`，PR #144）：`delector/core/database.py` 2809 → 359 行切分（公开面零变化，32 个 import 点未改）**。
- **⚠️ 调试口诀（本批两条，本地全绿、只在外部暴露）**：① **本地验证 MUST 逐字复刻 CI 门禁命令**（`mypy --strict delector tools` 与 `mypy --follow-imports=skip tests`；"单文件 + 相似 flags"不算复刻）；② **`__file__` 派生路径在模块搬家后会静默偏层**，只在干净 checkout 暴露 —— 搬包后 MUST 重核所有路径常量（守卫：`tests/test_backend_package_layout.py`）。
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
13. **探针 / 守卫的「锚点 + 括号配平」切片有两型静默失效**，形态都是**判据看着在跑、实际恒真**：① 锚点只到函数名 ⇒ 切片里没有函数体（`ia_dom_mount_probe` 曾有 4 条守卫如此死了很久，与任何重构无关）；② 用 `[^{]*`「吃掉参数表」的写法遇解构参数 `f({a}={})` 会停在参数的花括号上 ⇒ 同样切出无体片段（修好①后曾以为解决，实测仍死）。MUST 配平到 `)` 之后**要求下一个字符是 `{`**，任一步失败 MUST 具名报错、MUST NOT 返回短切片；注入式变异的锚点同理 MUST `assert == 1`。另两条同源纪律：静态层已红 MUST NOT 再跑 `node:vm`（空源撞出的 `ReferenceError` 会埋掉真实问题）；沙箱 MUST NOT 同时留手写桩与真实源码切片两个真相源。详情见 `docs/agents/architecture.md`「前端模块分层契约」。

## 开放待办（活项）

> 已接受 / 已推翻的历史裁决（ADR-0018~0021、登记项 1A~5A、红 master 事故、冷启动 2.0s 口径、性能路线 O0 结论等）已整体下沉至 [`cold/2026-10-12-settled-todos.md`](cold/2026-10-12-settled-todos.md)，此处只留活项。

1. **真实用户试用 + 宣传开闸门槛（2026-10-12 DECISION，`/dfs-grill` Track 1 收敛、不落 ADR）**：产品种草帖**延后**到四条门槛全绿 —— ① **≥5 份真实三问反馈**（入口已随 2026-10-12 批次落地：`.github/ISSUE_TEMPLATE/feedback.md` + README 下载表下直达链接；零门槛：不强制 `bug(scope):` 前缀、三道判断题、可选吐槽）② 新手「下载 → 打开 → 读到第一篇短文」连续无协助成功 ③ README 首屏含截图/GIF 与 Win10 WebView2 前置（见第 3 条）④ Android 真机点检通过（见第 2 条）。**内容先行不受限**：备考方法论 / 开发理念类帖子现在就能发；**产品演示类冻结至门槛绿**。宣传载体已定：**独立薄壳站点**（独立仓库 + 零构建纯静态 + `github.io`，版本运行时取 GitHub Releases API、不复述功能清单），域名后置。
2. **Android 真机点检**：凡含 `static/` 改动的版本需覆盖安装验证（清单见 `docs/agents/ops.md`）；同时验证 Android 更新 chip 的两条假设（Chaquopy 能否完成公网 HTTPS、WebView 点外链是否交系统浏览器）——即门槛④。**未验证前不得把「代码已合并」记成「双端已验证」**。
3. **README 首屏改造**（宣传线，门槛③剩余部分）：截图/GIF + 一句话价值 + 30 秒上手；当前首屏对非技术用户仍是代码仓库脸（badge 墙 + 版本摘要墙）。
4. **预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY` 缺失；`import_encounter_pack` 按 `pack_id` 幂等**不更新**既有行。
5. **C 档 8 项（当前唯一待办入口）**：`docs/reviews/2026-10-16-open-items-backlog.md`。其中 **C1「裁判结论回灌（verifier-in-the-loop）」为无条件下一步**（ADR-0024 四条硬依赖：① ~~裁判 FP 先修完~~ 已确认基线完成 ② 回灌内容 MUST 过同一道适用性闸与双限截断 ③ 定三角一致性（循环裁判带 nlp / `writing_check` **不带** nlp / 回灌源）④ 阴性对照 MUST 在动产品之前先跑成基线）。⚠️ 回灌落地后，§4.3 实验的阈值与结论**只对"准入式裁判"有效** ⇒ 必须重跑或明确分域（ADR-0024 已登记资产折旧，不留给下一任发现）。
6. **递延项（未立项）**：tests `--strict`；`tools/vault-proactive-scan.py` 三条版本正则无自动化守卫；PWA 安装提示验证 / 192-512 PNG 图标；桌面单实例文件锁（pid+版本+数据目录 + `/api/health` 身份校验 + 顺延 8001–8010）；发布链路 runbook（Publish 被跳过 / 孤儿 tag 的恢复路径：Vault v5.4.0 复盘 + **v5.1.1 孤儿 tag 在案**；`gh workflow run --ref <tag>` 理论可补发但**本仓未实证**，判据只能是 release 资产清单）。
7. **`check_master_commit_scope.py` 把 squash 合并误判成直推（当前 master CI 红的真因，非纪律违规）**：squash 合并产出的提交是**非 merge、父提交 = 上一个 master tip** ⇒ 落进 `--no-merges --first-parent` 的「直推」口径，于是它审的改动面其实是**整个 PR 的文件集**。实测：#165 与 #166 两条 PR 事件全绿、合并后 master push 的 `Master Direct-Push Scope Gate` 判红（#166 出界文件 `tests/test_exam_domain.py` · `tools/ia_dom_mount_probe.mjs`）。
   - ⚠️ **修法必须能区分「PR 合并」与「人工直推」，且 MUST NOT 退化成「凡带 `(#NNN)` 标题就放行」** —— 那等于让人在提交标题里写 `(#1)` 就能绕过整道闸（本闸存在的理由正是审计 P1-1：25 个含生产代码的提交曾直推 master）。候选判据：合并提交的 PR 编号回查 `gh`/API 的 `merge_commit_sha` 集合；或改由「同一 PR 的所有 sha 是否都经由 pull_request 事件验证过」判定。判据解析不出来时 MUST fail-closed。
   - 附带事实：该闸只看本次推送范围（`github.event.before..github.sha`），所以历史红不会阻塞后续推送 —— 但**latest master CI badge 会是红的**，得靠下一次 push 覆盖。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
