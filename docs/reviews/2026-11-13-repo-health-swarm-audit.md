# 多专家群体审计报告：DeLector 整体健康度

> **报告性质**：一次性审计快照（不随代码演进更新）。所有 `file:line` 以 **2026-11-13 的 `master` / `5342ace` / tag `v5.23.4`** 为准；代码改动后行号与结论会漂移，**活文档须同步，历史报告保持不动**。
> **审计方法**：`/dfs-team` 六席位全量只读审计（分两批各 3 席，遵守每 swarm 并发上限）+ 2 个独立 skeptic 席位对全部 P1 做反驳式核验。
> **数字口径**：`56` 条原始席位 finding、`17` 条 P1、`20` 条折叠后 finding 均为本轮逐条统计；测试基线 `3040 passed / 3054 collected` **不是本轮实测**，引自 `README.md:10-23` 记录的 v5.23.4 本地全量实测（本轮为纯只读审计，未跑测试）。
> **配套计划**：`docs/plans/2026-11-13-repo-health-remediation.md`

**日期**：2026-11-13
**目标范围**：整个仓库（repo 级）；工作树干净，项目处于 2026-11-10 起的阶段性暂停
**派出席位**：6 席全跑，分两批各 3 席——批一 `code-reviewer` / `dba-optimizer` / `sre-resilience`，批二 `frontend-architect` / `product-ux` / `perf-profiler`；另派 2 个独立 skeptic 席位做 P1 反证
**跳过席位**：**无**。repo 级目标六类制品面俱全：SQL/schema（`delector/core/db/`）、前端 DOM/CSS（`static/`）、热路径与 Go 并发（`agent/`）、用户可见文档与 CLI（`README.md` / `FEATURES.md`）、超时重试与 CI（`.github/workflows/`）、代码质量闸（`tools/`）。故不裁剪，改为分批。
**Findings**：**20 条，由 56 条原始席位 finding 折叠而来（其中 17 条 P1 → 5 条）**；20 < 56
**读取范围**：6 席合计约 300 次文件读取，含 `.github/workflows/ci.yml` 全 698 行、`build-release.yml` 全 615 行、`MainActivity.java` 全 1106 行、`delector/core/db/` 全量、`static/js/` 关键模块、`tests/` 门禁守卫族、`README` / `CHANGELOG` / `FEATURES` / `WORKMEMORY`。全部只读，未跑测试、未改文件。

---

## 结论先行

**整体 3.5 / 5，无 P0，不需要叫停。** 该综合分不是六域评分的算术平均（算术均值约 3.2），而是 skeptic 将 12 条 P1 降级后对实际风险面的上调。工程底座（CI 门禁矩阵、Go 并发、计时基准、密钥隔离、分支闸）显著强于平均水平；短板集中在三处：**持久化边界的数据安全**、**静态资源缓存失效机制**、**交付链护栏与活文档口径的不对称**。4 条 CONFIRMED P1 都是「可达但不高频」的失败路径，不是日常使用必现故障。项目暂停期内，建议只做数据安全与护栏/文档两类，其余留作恢复推进时排期。

各域自评：`code-reviewer` 4/5、`perf-profiler` 4/5、`dba-optimizer` 3/5、`sre-resilience` 3/5、`product-ux` 3/5、`frontend-architect` 2/5。

**严重度被系统性高估**：产品席位的 5 条 P1 经反证后 1 条 PLAUSIBLE、4 条降级；数据席位的 5 条 P1 有 3 条降级（其中一条证据本身有误）。这印证了本仓那条纪律——「未验证」不等于「已坏」，缺陷性质必须先复现再定级。

---

## 关键发现（P0 / P1）

**1. `[dba-optimizer]` [CONFIRMED] 还原失败时的快照整库回写会抹掉事务间隙里的合法写入** — `delector/routes/backup.py:311-365` + `delector/core/db/backup.py:467-514`
- *失败场景*：还原拆成 4 个独立事务（`:314` / `:337` / `:346` / `:360`），`_db_snapshot_guard` 的 `yield` 期间不持任何锁；任一步失败 → `snap.backup(live)` 覆盖活库 → 这期间用户存的一张词卡、一条 `PUT /api/wb/state` 全部消失，接口返回 5xx。
- *Impact*：**数据丢失**。单实例锁只拦第二进程，不拦同进程并发请求（skeptic 逐一核过 `delector/` 全部 `threading.Lock`，无覆盖 restore 路由的串行化）。
- *Verification Status*：CONFIRMED via skeptic read — 反驳失败；guard 是纯 `contextmanager`，`:494` yield 与 `:500` 回写之间无互斥。证据订正：快照回写在 `delector/core/db/backup.py:495-512`，原席位误标为 routes 文件（该文件仅 365 行）。

**2. `[dba-optimizer]` [CONFIRMED] 数据目录迁移漏 `progress.db`，旧进度库静默不搬且新位置重建空库** — `delector/core/db/connection.py:121-141` + `delector/core/data_dir_bootstrap.py:134,213-214`
- *失败场景*：显式 `DELECTOR_DATA_DIR=/new`（容器 / 手动 DATA_DIR）且 `/new/delector.db` 已存在 → `preflight` 提前 return（不判 `progress.db`），`_has_data()` 只要目标目录**有任一库**即返回 True 并整体 `return False` 不搬 → 新位置重建空 `study_log` / `quiz_log` / `daily_summary` / `exam_trials`，零提示。
- *Impact*：**学习记录全空**。桌面默认路径由 `DB_FILE_NAMES` 成套搬，不受影响；触发面限容器 / 显式 DATA_DIR。
- *Verification Status*：CONFIRMED via skeptic read — `DB_FILE_NAMES` 虽含 `progress.db`，但被 `_has_data()` 的粒度短路。

**3. `[sre-resilience]` [CONFIRMED] 发布侧真启闸没有 CI 侧那套挂死可分辨加固** — `.github/workflows/build-release.yml:63-69`（折叠 `build-agent.yml:17-29` 三 job 无超时）
- *失败场景*：`tools/verify_windows_portable.py` 挂住 → 唯一护栏是 job 级 `timeout-minutes: 30` → 结论 `cancelled`，无相位日志可归因，白烧 30 分钟；同 job Build 步也无心跳。`build-agent.yml` 全文无任何 `timeout-minutes`，挂死可烧满默认 360 分钟。
- *Impact*：发布可观测性缺口；`publish-github-release` 的 `needs` 链会阻断外发坏产物，故不外溢到用户。
- *Verification Status*：CONFIRMED via skeptic read — 对照 `ci.yml:354-373` 已接 `ci_heartbeat.py --deadline-seconds 480` + 步骤级 `timeout-minutes: 10`，并有 2026-11-04 run 41833602180 的事故取证。订正：发布侧无 `concurrency`，所以「与『被顶掉』同形」只在 ci.yml 成立，不影响主结论。

**4. `[frontend-architect]` [CONFIRMED] SW `networkFirst` 的 catch 无条件回落旧缓存，旧静态资源被当 200 交付** — `static/sw.js:94-101`
- *失败场景*：覆盖安装后旧 SW 仍控制首帧、新 `CACHE_NAME` 的 `activate` 尚未跑；首帧 `fetch` 失败 → catch 直接 `caches.match` 返回上一轮 `reader.js`，无版本/fingerprint 校验；`main.js` 的补注册 SW 注释明写「不参与首帧路径」，`initBuildStamp` 需 DOMContentLoaded + 在线 `/api/health` + stamps 非空，冷启动三条都不成立。
- *Impact*：用户在新版本上跑旧 JS，与 v5.23.1 白屏 / v5.23.2 阅读页失效同族；CHANGELOG 已登记「SW 冷启动瞬间短暂遮蔽新静态文件」但未修。
- *同根因折叠*：原 P1-12「桌面 / Windows 便携版无构建戳 ⇒ `static/js/build-stamp.js:119-121` 的 `stale` 恒 false、资源自证整条失效」（skeptic 降 P2，理由：无戳=开发态是明示契约）与 P2 #11 的「`cache.put` 无容量上限」均归入本条，不单列 finding；实施计划中统一由 T4 承接。
- *Verification Status*：CONFIRMED via skeptic read — 场景按 skeptic 订正**缩窄为「SW 已接管后的退出重进 / 再次启动」**（`CHANGELOG.md:53` 的实发场景），非「全新安装首次冷启动」。CACHE_NAME 绑版本号 + 红线 5 发版必 bump 也限制了同版本内热修的面。

**5. `[product-ux]` [PLAUSIBLE] README 把桌面导出写成已交付亮点，而冻结 exe 未验证** — `README.md:63` vs `CHANGELOG.md:33`
- *Verification Status*：**PLAUSIBLE（反驳成功，保留但不驱动任何阻断结论）** — README 描述的是代码机制，全文无「已在冻结 exe / macOS / Linux 验证」字样；同版 CHANGELOG 逐项列明未验证、README:69 指向 CHANGELOG。用户拿到的是「未验证」，不是坏产物。此项按纪律降级看待，不得当作缺陷立项。

---

## 改进项（P2，全部 UNVERIFIED）

| # | 折叠后根因 | 主要席位 / 位置 |
|---|---|---|
| 1 | **门禁清单未随扩容同步**：`FRONTEND_GATE_STEP_NAMES` 漏第 5 条 css sync 步、`MECHANICAL_STDLIB_GATE_SCRIPTS` 漏 `check_docs_layout`、`ci.yml` 注释仍写「六分片 / 4 条探针 / 三个判定器」（实为 7 / 5 / 4） | `code-reviewer` · `tests/test_ci_hardening_workflow_wiring.py:285-290`、`test_ci_hardening_core.py:287-291`、`ci.yml:206,171,643` |
| 2 | **判据恒真 / 死测族**：`setup-go@v5` 子串只命中注释（真实 action 已是 @v7）、`test_frontend_guards.py` 纯字符串断言 + 越界切片（把约 200 行邻函数切进 body）、模块图判据正则回溯 + 循环依赖只钉 3 个模块 + 无 node 时静默 skip、`wb_export_probe.mjs` 锚点配平不跳模板串、`check_layer_invariants.py` 空扫描面恒绿（skeptic 降级：同 job 的 silent-degradation 闸会拦语法错，仅「`delector/` 为空」时 return 0） | `code-reviewer` + `frontend-architect` |
| 3 | **lock 可解性无机械闸**：CI / 发布全链路只装 `requirements.txt`，`uv pip install --dry-run -r requirements.lock.txt` 仍是文档里的人工约定；dependabot 的 numpy 解除条件同为注释。skeptic 降级理由：lock 从不进 CI/发布链路，历史事故已在 #352 修复，残余影响仅开发者本地安装 | `sre-resilience` · `ci.yml:85` |
| 4 | **发布链路 runbook 缺失**：`workflow_dispatch` 下 `publish-github-release` 因 `if: refs/tags/v` 静默跳过，孤儿 tag 恢复路径 `gh workflow run --ref <tag>` 本仓未实证 | `sre-resilience` · `WORKMEMORY/PROJECT_OVERVIEW.md:72` |
| 5 | **写路径缺统一事务边界 / 连接生命周期**：wb 投影 `SELECT→INSERT` 窄窗口、FSRS 四列 read-modify-write、跨主库/progress 库无补偿、18 处裸 `with get_db()` 只 commit 不 close。skeptic 订正：`cards.py:542-550` 只更新 6 列且 `correct_count` 是 SQL 原子增，「整行覆盖/无原子增」的原始数据证据有误 | `dba-optimizer` · `routes/backup.py:358`、`routes/cards.py:515-570`、`services/companion_session.py` |
| 6 | **索引与 schema 治理**：UDF 全表扫描跑在 `BEGIN IMMEDIATE` 内、`source` 无索引、due 队列 TEMP B-TREE、无 `PRAGMA user_version`、方案稿 `docs/plans/2026-11-09-vocab-card-duplicate-merge.md` 的 Step 2/3 前提未随 Step 1 更新。已有正式裁决：2 万行实测 35.86 ms 远低于 `busy_timeout=5s`，本版不加索引，归 Step 2/3 | `dba-optimizer` + `perf-profiler` |
| 7 | **`.env` 覆盖显式注入的环境变量**：`delector/server.py:23` `load_dotenv(override=True)` 与 `start.py:570` 的 `k not in os.environ` 口径相反；残留 `.env` 可改写 `DEEPSEEK_API_KEY` / `DELECTOR_DATA_DIR`，无告警。Docker 面已由 `.dockerignore` 排除 | `sre-resilience` |
| 8 | **失败路径的资源清理与降级可见性**：`/api/wb/backup/save` 写盘中途失败留下半截 JSON 且 500 detail 带绝对路径、`instance_lock` 降级为无互斥句柄、Android 补载探针只认 `"missing"` 且 `readyHookInjected` 不复位 | `sre-resilience` + `frontend-architect` + `dba-optimizer` |
| 9 | **阅读页状态机残留**：占位标题「⏳ 载入中…」可被自身写回（skeptic 订正：令牌已防真正的跨文章串台）、`processed_stale` 前端零消费（503 分支已有「正在准备分词模型」提示，旧结果快退是刻意设计）、退避 `setTimeout` 无 `clearTimeout` | `frontend-architect` |
| 10 | **失败终态缺失族**：Android 就绪预算耗尽后文案「正在重试连接…」但 Java 侧已 return 不再重试、`exportAndReport` 外层无 try/catch 且两个 click 监听无 `.catch()`、Release 自动正文无 v5.23.1/2 警示 | `sre-resilience` + `frontend-architect` + `product-ux` |
| 11 | **资源无界与重复代价**：SW `cache.put` 无容量上限/淘汰、长文一次性 `innerHTML` + 每 `.tok` 两个闭包监听器、模型加载失败不写全局状态致每请求重跑三级回退、Go companion HTTP 每请求直跑 `RunLoop` 无背压（本机单用户影响有限） | `perf-profiler` |
| 12 | **活文档版本/数字/状态漂移**：`FEATURES.md:7` 停在 v5.22.1、`WORKMEMORY/PROJECT_OVERVIEW.md:69` 门槛③写 2962/2967（实为 3040/3054）、README 徽章宣称 Python 3.10 但仓内零 3.10 job、`CHANGELOG.md:111` 「真机点验」与同版「arm64 未点检」并存、`requirements-desktop.txt` 注释与 pin 不一致 | `code-reviewer` + `product-ux` + `sre-resilience` |
| 13 | **用户自助信息与状态披露**：App 内「已知限制·脱网可见」把未验证项指向 CHANGELOG 却无外链、门槛②「读到第一篇」无上手指引、项目暂停未进入任何用户可见文档而 `README.md:118` 承诺「反馈决定下一个版本」、Win10 WebView2 文案低估实际弹窗能力、开发者「三步」实为 6 行且端口写死 8000 | `product-ux` |
| 14 | **死代码与红线例外未登记**：`check_docs_layout.py` 的 `_rel_dirs` 全仓无调用、`tools/bench_judge_fp.py:454` 的第二份离线切句未在红线 10 登记例外、`check_release_docs.py` 未机械校验格式规则 2 | `code-reviewer` |
| 15 | **基准口径残留**：`tests/test_cold_start_cost.py:485-489` 全仓唯一保留的跨进程量级比较 `health_200_ms > import_ms * 0.5`（0.5 为经验余量，docstring 自承同机相邻两次可差 2 倍）、`tests/test_first_screen_from_log.py` 秒级单样本与同日志毫秒精度错配 | `perf-profiler` |

---

## 共识行动计划（按优先级排序）

1. **数据安全先修（接手前必修）**：给 restore 全程加同进程互斥（`threading.Lock`，stdlib）并把 4 段改为单一事务；或给「快照回写」加「期间无并发写」的判据，否则拒绝回写并显式报错。补一条「restore 中途失败 + 并发存词」的回归测试，做变异自证（去掉锁必须变红）。
2. **修数据目录迁移**：`data_dir_bootstrap._has_data()` 从「目标目录有任一库」改为**逐库判定**，缺 `progress.db` 时按 `DB_FILE_NAMES` 逐库搬或显式报错，禁止静默重建空库；`preflight_data_dir` 同步纳入 `progress.db`。补容器/显式 DATA_DIR 场景用例。
3. **发布护栏对齐**：把 `ci.yml:354-373` 的 `ci_heartbeat.py --deadline-seconds 480` + 步骤级 `timeout-minutes: 10` 原样接到 `build-release.yml:63-69`（及 Build 步）；给 `build-agent.yml` 三个 job 补 `timeout-minutes`。
4. **SW 缓存失效**：`networkFirst` 的 catch 增加 `CACHE_NAME` / fingerprint 校验——旧版本缓存不得作为首帧 200 交付；或把 `activate` 的旧缓存清理提到首帧之前。补「旧 SW 仍控制时」的行为探针（现有 `tests/test_static_cache_fingerprint.py` 只覆盖 Android 注入面）。
5. **门禁清单同步**：把 css sync 步补进 `FRONTEND_GATE_STEP_NAMES`、`check_docs_layout` 补进 `MECHANICAL_STDLIB_GATE_SCRIPTS`；`setup-go@v5` 子串断言改为解析 YAML 后校验 `uses:` 真实值；`ci.yml` 注释改 7 / 5 / 4；给 `check_layer_invariants.py` 补「扫描面为空 → 退 2」与环境错误路径用例。
6. **补 lock 求解闸**：在 `unit-2` 或 `static-invariants` 加一步 `uv pip install --dry-run -r requirements.lock.txt`（README 已要求开发者装 `uv`，无新依赖），把 dependabot 的 numpy 解除条件做成机械判定。
7. **文档口径一次性收口**：FEATURES 版本标注、`PROJECT_OVERVIEW` 门槛③数字、README 3.10 徽章、CHANGELOG「真机点验」措辞、App 内已知限制脱网可达、项目暂停状态对外披露。
8. **恢复推进时再排**：写锁统一、UNIQUE 与 Step 2/3、SW 容量上限、长文分段渲染、计时口径清理、`dotenv override` 统一。

> 全部为「接手前必修 / 恢复推进时再排」两档，无阻断发版或阻断合入的闸——`/dfs-team` 输出报告，不叫停提交。完整 Task 拆分、TDD 步骤与验收判据见 `docs/plans/2026-11-13-repo-health-remediation.md`。

### 复用阶梯检查

| 提案 | 阶梯评估 |
|---|---|
| restore 进程级互斥 | 复用 stdlib `threading.Lock` 即可；跨进程已有 `delector/core/instance_lock.py`，**不要**复用它（粒度不符，且它可降级）。零新依赖 |
| 数据目录逐库搬运 | 复用现有 `DB_FILE_NAMES` / `isfile` + `size>0` / `_norm_path`，仅改 `_has_data()` 判定粒度，不新建迁移模块 |
| 发布护栏 | 直接复用仓内 `tools/ci_heartbeat.py` 与 `tools/verify_windows_portable.py`，**不新增脚本**；这是把已有加固复制到发布侧 |
| SW 版本校验 | 复用 `delector/core/assets_manifest.py` 的 fingerprint 与 `/api/health` 的 `assets_fingerprint`，前端已有 `static/js/build-stamp.js` 消费同样字段，无需新协议 |
| lock 求解闸 | 复用 README 已要求的 `uv` + stdlib `subprocess`；或纯文本一致性判定器放 `tools/`，不引入 pip-compile 等新工具链 |
| 门禁清单补全 | 只改现有测试常量与 `ci.yml` 注释，无新代码 |

---

## 两处诚实性更正与局限

- **编排者背景错误（已由 skeptic 实证纠正）**：派单时把另一项目 `agent-api` 的实现（`Enqueue` 的 `select+default` 快速失败 / `ErrQueueFull` / 503）误写成本仓 `agent/` 的背景。`agent/` 62 个 `.go` 中这些符号**均不存在**；本仓 `worker-pool` 只存在于 `agent/internal/job/runner.go`（离线包固定并发 + ctx 零泄露），`select+default` 是错误去重，`503` 是 `/api/health` 的库坏状态。因此 perf 席位那条「Go 无背压」已去掉「与既有队列不一致」的措辞，仅保留「本机单用户场景无背压」的观察并降为 P2。**本仓没有请求入队快速失败/过载拒绝机制**，勿据旧背景立项。
- **未实证项**：本次纯只读，未跑全量 pytest / ruff / mypy / Go 门禁（沿用 README 的 3040/3054 实测记录）；线上 Release 正文是否被 `gh release edit` 覆盖、GitHub Issues 是否已收到 ≥5 份反馈，仓库内无法核实，相应条目均标注了不确定点。
- **不构成立项依据的项**：第 5 条 PLAUSIBLE 发现、以及所有标 UNVERIFIED 的 P2，按本仓纪律须先物理复现（`negative search` / 行为探针）再决定是否修复；本报告只提供线索，不代替 `/dfs-verify`。
