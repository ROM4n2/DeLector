# 仓库整体健康度修复实施计划（2026-11-13 群体审计后续）

> **Goal**: 把 `docs/reviews/2026-11-13-repo-health-swarm-audit.md` 的 **20 条折叠 finding（4 条 CONFIRMED P1 + 1 条 PLAUSIBLE + 15 条 P2）** 全部转成可执行、可验收、可回滚的 Task，按「暂停期必修 / 恢复推进时再排」两档排序，并给出 20/20 全覆盖追溯表。**本文件只出方案，不写代码**；批准后按 §3 的 Stage 顺序实施。
>
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL, 单文件双库) / pytest（无 pytest-asyncio）/ 原生 JS ES Modules + Service Worker / Android Java (Chaquopy + WebView) / Go 1.26 agent runtime / GitHub Actions（7 分片 + 4 档 mypy + 前端探针 + Go 三闸）。
>
> **Spec Reference**: `docs/reviews/2026-11-13-repo-health-swarm-audit.md`（唯一缺陷清单正主）· `WORKMEMORY/PROJECT_OVERVIEW.md`（红线 1~13、开放待办 1~7）· `WORKMEMORY/PROTOCOL.md`（分支 / 记忆纪律）· `docs/agents/ops.md`（Agent 工作惯例）· `docs/README.md`（文档归置与归档判据）· `docs/agents/ci-speed-budget.md`（闸门成本预算）· `docs/plans/2026-11-09-vocab-card-duplicate-merge.md`（Step 2/3 既有方案稿，本计划不重复立项）。
>
> **Global Constraints**（MUST，逐条可判定）:
> - **GC1 缺陷性质先复现**：CONFIRMED 项也须 RED 先行（先写复现用例跑红再改实现）；PLAUSIBLE 与 UNVERIFIED 项不得当缺陷立项，须先走 `/dfs-verify` 拿物理证据。禁止把「未验证」写成「已坏」，也禁止把「代码已合并」写成「双端已验证」。
> - **GC2 分支隔离**：Stage 0 为纯文档（报告 / 本计划 / 索引 / 记忆簿记），属 `PROTOCOL.md §1.8` 白名单，可直推 `master`（须用户批准）；**Stage 1 起每个 Stage 独立分支 + PR，禁止直推 `master`**。含 `.github/workflows/**` 的 PR **不能**用 `gh pr merge`（token 缺 `workflow` scope），改走 SSH 本地 `--no-ff` 合并后 push；`tools/check_master_commit_scope.py` 用 `--first-parent`，PR 分支提交不会误判。
> - **GC3 决策文档先行**：Stage 0 的决策文档必须先合入 `master`，**再**开 Stage 1 执行分支——两者都会改 `WORKMEMORY/work.log` / `PROJECT_OVERVIEW.md`，并行会撞车。
> - **GC4 HITL 授权门**：T1 / T2 / T3 涉及数据写入、迁移与不可逆动作，开工前须用户逐项确认影响面、不可逆风险、回退方式；任何写库动作默认 dry-run，服务启动路径不得静默改用户数据。
> - **GC5 零新依赖**：优先 stdlib 与仓内既有模块（复用阶梯见审计报告）；新增依赖或工具链须单独报备。`uv` 仅在其已成为 README 明示的开发者工具前提下可用。
> - **GC6 数字纪律**：写进 README / CHANGELOG / PROJECT_OVERVIEW 的测试数、耗时、命中数 MUST 本轮自己实测并标注时点；本次审计**未跑全量**，`3040 passed / 3054 collected` 只许作为「引自 `README.md:10-23` 的 v5.23.4 实测记录」引用，不得记成本计划实测。
> - **GC7 守卫纪律**：新守卫 MUST 变异自证（写回旧实现立即红）；跨边界契约 MUST 行为探针，字符串存在断言是死测；「锚点 + 括号配平」切片须配平到 `)` 后要求下一个字符是 `{`，失败具名报错、不得返回短切片（红线 13 两型静默失效）；静态层已红不得再跑 `node:vm`；沙箱不得同时留手写桩与真实源码切片两个真相源。
> - **GC8 门禁全档**：改了哪个文件就把覆盖它的**每一档**门禁跑全；mypy 四档参数各异，复跑 MUST 从 `.github/workflows/ci.yml` 复制 `run:` 整行；核验输出禁用 `head`/`tail` 截断（会漏看失败项，管道还会吃掉上游退出码）。搬家类改动（如调整 CI step 挂载点）会作废别的套件的契约，须跑全量 pytest + mypy 四档。
> - **GC9 CI 纪律**：触发流水线后单次查状态即汇报，**不长轮询阻塞等 CI**；等用户说「看结果」再复查。
> - **GC10 发版纪律**：tag 必须打在含 bump 的提交上；`versionCode = major*10000+minor*100+patch` 不得回拨；优先零 DDL / 零迁移，若必须改 schema 则在 CHANGELOG「回滚」段写明；CHANGELOG 新条目插在 FORMAT RULES 注释块之后、首个 `## vX.Y.Z` 之前（降序）。
> - **GC11 暂停期边界**：项目自 2026-11-10 阶段性暂停。Stage 1（数据安全）判为「接手前必修」；Stage 2~4 默认排到恢复推进后，**是否在暂停期执行由用户拍板**（见 §0 待拍板 D1）。
> - **GC12 文档归置**：`docs/reviews/` 新文件 MUST 以精确文件名登记进 `docs/reviews/README.md`（`tools/check_docs_layout.py` 机械判红）；计划命名 `<日期>-<主题>.md`；本计划在「成果随某 tag 发版」后才 `git mv` 进 `docs/plans/archive/`。
>
> **EXECUTION ADDENDUM · 2026-11-13 用户裁决（权威覆盖，优先于下文所有原条款）**
> 1. **禁止全量 test（硬约束）**：本地**禁止**运行 `pytest tests` 全量套件，也禁止按 `ci.yml` 的 7 分片全部跑一遍；只允许跑覆盖本次改动文件的**对点测试**（具体测试文件 / 用例 / 关联套件）。下文的 **GC8、`§0` 表格完成判据、`§2` 第 5 条、`§5` 验证矩阵「pytest 7 分片」行、`§6` 里程碑、以及各 Task 的 TDD ⑤ 步**中所有「全量 pytest / 全量套件 / 全量门禁 / 7 分片 / 跑全量」表述，一律以本节为准改为对点。静态闸（`ruff check .` / `tools/check_*.py`）与 mypy 各档仍按「改了哪个文件就跑覆盖它的每档」执行（GC8 原意保留，仅去掉全量 pytest）。每个 Task 的完成报告 MUST 标注「未跑全量、存在未覆盖回归风险」。
> 2. **D1 裁决**：火力全开 = **Stage 1~4 全部执行**（不再限于「暂停期必修的 Stage 1」）；GC11 的「默认排到恢复推进后」被覆盖。
> 3. **D2 裁决**：取 **A** —— 同进程 `threading.Lock` 包住 restore 全程；改动面最小、回滚最易，不重排跨库调用。
> 4. **D3 裁决**：取 **B** —— 保持 `tests/test_static_cache_fingerprint.py:71` 的「无戳=开发态」明示契约，不改 `package_windows.py` 打包注入；桌面自证缺失只在 CHANGELOG 已知限制登记。
> 5. **D4 裁决**：取 **B** —— `tools/` 加纯 stdlib 版本一致性判定器，零新工具链；文档 MUST 写明「非真实依赖求解」的判据边界。
> 6. **D5 裁决**：取 **B** —— 不对外披露项目暂停；仅 WORKMEMORY / handoff 记录，README 反馈承诺不动（产品策略需用户单独拍板）。
> 7. **执行形态裁决（已被 2026-11-13 15:xx 用户新约束覆写，见第 11 条）**：用户批准「可使用 dfs 系列工作流」，`/dfs-exec` 的 VCS 隔离硬闸优先于本计划 GC2 —— **任何实现不得落在 `master`**。首批曾采用**单一执行分支** `fix/repo-health-remediation`（从 `master` 开）：Stage 0 决策文档作为该分支**首个原子提交**（以提交顺序满足 GC3 的「决策先行」），其后按 Stage 原子提交。因 `/dfs-exec` 要求「batch landing MUST end in a PR」，该批次以 **PR-ready 形态**停在本地分支，**不 push、不开 PR、不直接合 master**。该分支是**历史遗留的混合分支**（11 提交含 7 个 Task + 审查修复 + 文档），不再往里追加。
> 8. **Tier 分级**：T1/T2/T3 = `[Tier: 3-Critical]`（HITL 授权由用户本次「批准 + 火力全开」覆盖）；T4/T5/T6/T9/T10/T11/T13/T14/T15 = `[Tier: 2-Standard]`；T7/T12/T16 与 Stage 0 = `[Tier: 1-Light]`。
> 9. **能力边界登记（执行偏差）**：本环境只有只读 `code-explorer` 子代理，无法派实现型 Maker 子代理；故实现在编排者线程完成，**每个 Stage 结束派独立只读 reviewer 子代理对抗审查 + 编排者在父树物理复现至少 1 组变异自证**，以满足 `/dfs-exec` 的「independent reviewer dispatch」与 `/dfs-orchestrate` 的「child self-report 不是证据」。登记为技术债。
> 10. **Ledger**：`/dfs-exec` 的 `vault_exec_state.py init` 用 `--tasks` 显式登记 T1~T16（本计划 Task 标题为 `#### T1 · ...` 格式，不匹配 CLI 的 `### Task N:` 正则，不能只传 `--plan-file`）。
> 11. **一 PR 只做一件事（2026-11-13 15:11 用户新约束，覆写第 7 条的单一分支裁决）**：剩余每个 Task 各占一条**独立分支 + 独立 PR**（stacked，PR 的 base 指向 `fix/repo-health-remediation`，故每个 PR 的 diff 只含自己这一件事）；并行子代理 MUST 用**独立 git worktree** 隔离，绝不共享工作区。首批 11 提交留在 `fix/repo-health-remediation` 作为**历史遗留混合分支**，不再往里追加 Task 改动。合并按主题逐个进行，不打包；首批合并后其余分支 rebase 到新 `master` 并把 PR base 改回 `master`。
>
> **Branch / 状态**：首批 = `fix/repo-health-remediation`（历史遗留混合分支，已停）；剩余 Task 各自独立分支（见 `.worktrees/`）。**当前状态：实施中（2026-11-13），未 push、未开 PR。**

---

## 0. 摘要：分档裁决、完成判据与待拍板项

| Stage | 覆盖 finding | 定位 | 何时做 | 完成判据 |
|---|---|---|---|---|
| **0** | — | 决策文档先行（本轮产出） | 立即 | 报告 + 本计划 + `reviews/README.md` 索引 + `work.log` 事件合入；`check_docs_layout.py` 绿 |
| **1** | P1-1 / P1-2 / P2-5 | 数据安全（可致数据丢失） | **暂停期必修** | 3 条复现用例 RED→GREEN + 变异自证；全量 pytest + mypy 四档绿 |
| **2** | P1-3 / P1-4 / P2-3 / P2-4 / P2-7 / P2-8 / P2-11(部分) | 缓存失效与交付链护栏 | 建议恢复推进后（D1 待拍板） | Windows 冒烟 + 发布 dry-run + SW 行为探针绿 |
| **3** | P2-1 / P2-2 / P2-14 / P2-15 | 门禁自证与基准口径 | 恢复推进后 | 每个新守卫有阳性/阴性/变异三类用例；CI 13 项绿 |
| **4** | P2-6 / P2-9 / P2-10 / P2-11(其余) / P2-12 / P2-13 / P1-5(PLAUSIBLE) | 前端状态机、运行时、对外口径 | 恢复推进后 | 行为探针 + 文档一致性闸绿；真机项保持「未验证」标注 |
| **5** | 不立项 | 延后指针（词卡 Step 2/3、真机四门槛、性能深水区） | 不排期 | 仅在 §8 登记指针，不写 Task |

**总完成判据**：§7 追溯表 20/20 每条有明确归属（Task 或「不立项 + 理由」）；所有 Task 的变异自证留痕；全量门禁绿；CHANGELOG 与 PROJECT_OVERVIEW 同步；无一条「未验证」被写成「已验证」。

### 待拍板项（不替用户决策）

| ID | 问题 | 备选与代价 | 影响 |
|---|---|---|---|
| **D1** | 暂停期只做 Stage 1，还是 Stage 1+2 一起做？ | 只做 1：风险面最小、改动 3 个 Task；做 1+2：把 4 条 CONFIRMED P1 一次收口，但触及 `static/sw.js` + `.github/workflows/**`，需覆盖安装验证 | 决定分支数与发版节奏 |
| **D2** | T1 的 restore 互斥取哪一层？ | A：同进程 `threading.Lock` 包住整段（改动小、只拦同进程）；B：4 段合为单一 `BEGIN IMMEDIATE` 事务（更彻底，但改动面大、需重排 `migrate_a1_records_to_exam_trials` 等跨库调用） | T1 实现与测试形态 |
| **D3** | 桌面 / Windows 便携版的资源自证怎么做？ | A：在 `package_windows.py` 打包期也注入 `delector-assets` meta（会改变 `tests/test_static_cache_fingerprint.py:71` 把空串钉成「开发态契约」的现状）；B：保持该明示契约，只在文档登记「桌面无自愈提示」 | T4 是否触碰守卫契约 |
| **D4** | lock 求解闸用什么？ | A：CI 装 `uv` 跑 `uv pip install --dry-run -r requirements.lock.txt`（真求解，runner 增一步安装）；B：`tools/` 加纯 stdlib 版本一致性判定器（快、无新工具，但不做真实依赖求解） | T6 的判据强度 |
| **D5** | 项目暂停状态是否对外披露？ | A：README 加一段（诚实但影响宣传）；B：仅在 PROJECT_OVERVIEW / handoff 记录（现状） | T16 的对外口径范围 |

> 按本仓惯例，目标值 / 收益类待拍板项宜由对应领域席位独立评估后再收敛；本计划只列备选与代价，不预设立场。

---

## 1. 基线（快照，2026-11-13）

| 项 | 值 | 来源 |
|---|---|---|
| 分支 / 提交 / tag | `master` / `5342ace` / `v5.23.4`（2026-11-11） | 本轮 `git status` / `git log` / `git tag` 实读 |
| 工作树 | 干净 | 本轮 `git status --short` 实读 |
| 项目状态 | 2026-11-10 起阶段性暂停 | `WORKMEMORY/PROJECT_OVERVIEW.md:43,75` |
| 改动面参考 | `v5.23.0..master` = 41 文件 / +1522 / -100 | 本轮 `git diff --stat` 实读 |
| 测试基线 | 3040 passed / 3054 collected（含本机 2 failed + 3 errors 噪声） | **引自 `README.md:10-23` 的 v5.23.4 实测，本轮未复跑** |
| 原始 / 折叠 finding | 56 条 → 20 条（17 条 P1 中 4 CONFIRMED / 1 PLAUSIBLE / 12 降级） | 本轮逐条统计 + 2 席 skeptic 结论 |
| CI 拓扑 | 7 个 pytest 分片 / 4 档 mypy / 5 条前端探针 / 4 条静态不变量 / Go 三闸 / 真链路零 SKIP / Windows 冒烟 / 直推范围闸 / gitleaks | `.github/workflows/ci.yml` 全 698 行实读 |

**行号漂移声明**：本计划所有 `file:line` 均为上述快照的行号；实施时以当前代码为准重新定位，禁止照抄行号改错文件。

---

## 2. 全局执行纪律（每个 Task 开工前逐条对照）

1. 先判分支：实现 / 多步任务走分支 + PR；仅发版类、WORKMEMORY 簿记类、纯文档类可直推 `master`（`PROTOCOL.md §1.8`）。Stage 0 属第三类，Stage 1+ 不属。
2. 开工前重读 `WORKMEMORY/work.log` 尾部，确认无他方未闭合 `WORK_START`；按协议追加事件（≤4KB、UTF-8、不回改历史、不含密钥字面量）。
3. RED 先行：先写会失败的用例，记录**预期失败原文**，再改实现。
4. 变异自证：把缺陷写回（或删掉新判据）用例必须立即变红，并把红的输出贴进 PR / work.log 摘要。
5. 关联套件 → 全量套件：先跑覆盖该文件的档位，再跑全量；复跑命令从 `ci.yml` 复制 `run:` 整行（§5）。
6. 核验输出不截断、不用管道吞退出码；保存原始退出码。
7. 门禁触发后单次查状态即汇报，不长轮询。
8. 每个 Stage 收尾：更新 `CHANGELOG.md`（若为发版批次）、`WORKMEMORY/PROJECT_OVERVIEW.md` 活项、`work.log` 事件；文档数字自己实测。
9. 任何「更快 / 更少 / 更省」的收益声明，先查工具分辨率与计时窗口；跨进程 / 跨状态的量级比较不是不变式，禁止用作阈值。
10. 含 `static/` 改动的版本须覆盖安装才在 Android 生效；未真机点检不得记成「双端已验证」。

---

## 3. Stage 0：决策文档先行（本轮已完成写盘，待合入）

**Files**：`docs/reviews/2026-11-13-repo-health-swarm-audit.md`（新增）· `docs/reviews/README.md`（补索引条目）· `docs/plans/2026-11-13-repo-health-remediation.md`（本文件）· `WORKMEMORY/work.log`（追加 1 条 `DECISION` 事件）。

**验收**：
- `python3 tools/check_docs_layout.py` → 退出码 0（新报告已按精确文件名登记；新计划符合 `PLAN_RE`）。
- `pytest -q tests/test_docs_layout_gate.py` → 绿。
- `git status --short` 只含上述 4 个文件；无生产源码 / CI 定义 / 测试文件被卷入（历史事故：`git add -A` 曾把并行工作线卷进发版提交，本 Stage 必须逐文件 add）。
- 合入 `master` 并确认 CI 绿后，**才**允许从新 `master` 开 Stage 1 分支（GC3）。

**回滚**：纯文档，`git revert` 即可；不影响数据与运行时。

---

## 4. Task 清单

> 每个 Task 的 `Files` 均为**预期改动面**，实施时以当前代码重新定位；`TDD` 五步为固定形态，不再逐条解释。所有 Task 均须遵守 §2 全部纪律。

### Stage 1 — 数据安全（暂停期必修，HITL）

#### T1 · [P1 CONFIRMED] 还原失败时快照整库回写抹掉并发合法写入
- **Finding**：审计报告 §关键发现 #1 · `delector/routes/backup.py:311-365` + `delector/core/db/backup.py:467-514`
- **Files**：Modify `delector/core/db/backup.py`（`_db_snapshot_guard` / `_restore_db_file`）· Modify `delector/routes/backup.py`（restore 路由编排）· Test `tests/test_backup_restore_concurrency.py`（新增）
- **Consumes → Produces**：4 个独立 `with conn` 事务 + `snap.backup(live)` 整库覆盖 → 整段受同进程互斥保护、或合为单一事务；异常分支改为「拒绝回写 + 显式 5xx 文案」，保留失败前已提交的合法写入
- **修法**：按 **D2** 裁决选 A/B。A：`threading.Lock` 包住 restore 全程（含 guard 的 yield），锁粒度限 restore、不影响普通请求；B：把 `:314/:337/:346/:360` 合进一个 `BEGIN IMMEDIATE` 事务，跨库步骤单独留补偿。**不得**复用 `delector/core/instance_lock.py`（跨进程、可降级、粒度不符）。
- **TDD**：① RED：用例「restore 中途注入失败 + 另一线程并发 `POST /api/cards/vocab` ⇒ 该词卡仍在库中且接口非 ok」，先跑红并记录原文；② 记录预期失败；③ GREEN 实现；④ 变异自证 2 组（去掉锁 / 恢复无条件 `snap.backup(live)` ⇒ 用例红）；⑤ 关联套件 + `pytest -q tests` 全量 + ruff + mypy 三档
- **验收**：`_require_localhost` 仍挂在 restore 路由（`tests/test_localhost_guard.py:49` allowlist 不放松）；单实例锁不被改动；测试最坏耗时 <5s（禁无超时 `join`）
- **回滚**：`git revert` 恢复原事务划分；无 DDL、无数据格式变化
- **依赖**：Stage 0 合入；D2 拍板；GC4 授权

#### T2 · [P1 CONFIRMED] 数据目录迁移漏 `progress.db`
- **Finding**：审计报告 §关键发现 #2 · `delector/core/db/connection.py:121-141` + `delector/core/data_dir_bootstrap.py:134,213-214`
- **Files**：Modify `delector/core/db/connection.py`（`preflight_data_dir`）· Modify `delector/core/data_dir_bootstrap.py`（`_has_data` / 搬运循环）· Test `tests/test_data_dir_migration.py`（新增或并入既有）
- **Consumes → Produces**：`_has_data()` 只看「目标目录有任一库」→ **逐库判定**；`preflight` 只判 `delector.db` → 同时判 `progress.db`
- **修法**：按 `DB_FILE_NAMES` 逐个检查 `(name, size>0)`；缺任一库时走既有「先 wal_checkpoint(TRUNCATE) → 成套复制 -wal/-shm → 先复制再改名」路径；两者都缺或都不许搬时 **具名报错**（禁止静默重建空库）。桌面默认路径行为必须保持不变。
- **TDD**：① RED：用例「显式 `DELECTOR_DATA_DIR=<tmp>` 且已放 `delector.db`、仓库根有 `progress.db` ⇒ 迁移后 `quiz_log` 行数不丢 / 或缺库时抛具名异常」；② 记录；③ GREEN；④ 变异自证（`_has_data` 写回「有任一库即 True」⇒ 红；`preflight` 去掉 progress 判定 ⇒ 红）；⑤ 关联 + 对点
- **验收**：Docker / `docker-compose.yml` 显式 DATA_DIR 场景实测；`schema.py:135-141` 的 `init_db` 预检顺序不变；不改动 `start.py` 的 bootstrap 时序
- **回滚**：`git revert`；迁移工具默认 dry-run，未授权不写用户数据
- **依赖**：Stage 0；GC4 授权（涉及用户数据搬移）

#### T3 · [P2 UNVERIFIED] 写路径事务边界与连接生命周期统一
- **Finding**：审计报告 P2 #5（含 4 子项，且已吸收 skeptic 的证据订正）
- **Files**：Modify `delector/routes/backup.py`（wb 投影 `:358`）· Modify `delector/routes/cards.py`（FSRS `:515-550`、跨库 `:565-570`）· Modify `delector/services/companion_session.py` / `companion_proposal.py`（18 处裸 `with get_db()` → `db_conn()`）· Test 分别在 `tests/test_vocab_identity_upsert.py` / `tests/test_cards_fsrs.py` / `tests/test_db_connection_lifecycle.py`
- **Consumes → Produces**：`SELECT→INSERT` 无事务窗口 / FSRS 四列 read-modify-write / 主库与 progress 两独立事务 / 裸 `with conn` 不 close → 统一 `BEGIN IMMEDIATE`（或 `db_conn()`）与确定性 close
- **修法**：① wb 投影首条语句前显式 `BEGIN IMMEDIATE`；② FSRS 的 `repetition_count/interval/ease/due_date` 改 SQL 原子表达式或整段加锁（**注意**：`correct_count`/`wrong_count` 已是原子增，不要照原始证据误改）；③ 跨库写加补偿或显式错误文案；④ 18 处改用 `connection.py:283-312` 已有 `db_conn`/`db_progress_conn`
- **TDD**：① RED 四条（并发同卡双评级不丢、投影并发不产生重复卡、跨库失败有可见错误、连接 close 可观测）；② 记录；③ GREEN；④ 变异自证每子项 1 组；⑤ 关联 + 对点
- **验收**：`tests/test_vocab_identity_upsert.py:284-302` 的 PRAGMA 过渡护栏**不放宽**（Step 3 前仍须无 UNIQUE）；`busy_timeout=5000` / WAL PRAGMA 不变
- **回滚**：逐子项 `git revert`；不改 schema
- **依赖**：T1（同属写锁边界，避免两次改同一文件互相冲突）；GC4 授权

### Stage 2 — 缓存失效与交付链护栏

#### T4 · [P1 CONFIRMED + 同根因 P2] SW 旧缓存回落 + 桌面资源自证失效 + 缓存无界
- **Finding**：审计报告 §关键发现 #4（含被 skeptic 降级的 build-stamp 项）+ P2 #11 的 `cache.put` 无界
- **Files**：Modify `static/sw.js`（`networkFirst` catch / `activate` / `cache.put`）· Modify `static/js/build-stamp.js`（按 D3 决定）· 可能 Modify `package_windows.py` / `tools/sync_android_sources.py`（按 D3）· Test `tests/test_sw_cache_invalidation.mjs` + `tests/test_static_cache_fingerprint.py`
- **Consumes → Produces**：catch 无条件 `caches.match` → 带 `CACHE_NAME` / `assets_fingerprint` 校验的回落策略；`activate` 只清旧 key → 首帧前可判定的失效；`cache.put` 无上限 → 容量上限 + FIFO 淘汰
- **修法**：① 回落前比对响应/缓存条目的版本标记，旧版本缓存不得作为首帧 200 交付；② 复用 `delector/core/assets_manifest.py` 的 fingerprint 与 `/api/health` 的 `assets_fingerprint`，不新增协议；③ D3 选 A 则在打包期注入 meta 并**同步改** `test_static_cache_fingerprint.py:71` 的契约断言（写明为何强化），选 B 则只在 CHANGELOG 已知限制登记；④ 缓存条目数上限与淘汰用现有 `sync.py` 的 FIFO+TTL 形态，不放任单调增长
- **TDD**：① RED：行为探针「旧 SW 控制 + 新 `CACHE_NAME` 未 activate + fetch 失败 ⇒ 不把旧 `reader.js` 当成功交付」；② 记录；③ GREEN；④ 变异自证（把 catch 写回无条件 `caches.match` ⇒ 红；把容量上限去掉 ⇒ 红）；⑤ 前端 5 条探针 + 对点
- **验收**：场景**缩窄为「SW 已接管后的退出重进 / 再次启动」**（skeptic 订正），不得宣称修复「全新安装首次冷启动」；`?v=` 保持退役；`Cache-Control: no-cache` 中间件不动；含 `static/` 改动 ⇒ 按 GC2/§2.10 需覆盖安装验证，未真机点检就写「未验证」
- **回滚**：`git revert` 前端文件；SW 版本号随下次发版 bump（红线 5 五件套）
- **依赖**：D3 拍板；T9（若改了 CI 前端探针清单需同步）

#### T5 · [P1 CONFIRMED] 发布侧真启闸挂死不可分辨 + `build-agent.yml` 无超时
- **Finding**：审计报告 §关键发现 #3
- **Files**：Modify `.github/workflows/build-release.yml`（`:59-61` Build、`:63-69` Verify）· Modify `.github/workflows/build-agent.yml`（三个 job）· Test `tests/test_ci_hardening_workflow_wiring.py`（新增发布侧护栏接线守卫）
- **Consumes → Produces**：裸 `python tools/verify_windows_portable.py` → `ci_heartbeat.py --stage verify --deadline-seconds 480 -- ...` + 步骤级 `timeout-minutes: 10`；Build 步加 `--stage build` 心跳；`build-agent.yml` 三 job 加 `timeout-minutes`
- **修法**：**直接复制** `ci.yml:354-373` 的既有写法（含 `--expect-commit ${{ github.sha }}`），不新增脚本；接线守卫用解析 YAML 后断言 `uses`/`run`/`timeout-minutes` 真值，不做子串存在断言
- **TDD**：① RED：守卫「发布 Verify 步必须带 `ci_heartbeat` 与步骤级 timeout」先红；② 记录；③ GREEN；④ 变异自证（删掉 deadline / 删掉 `timeout-minutes` ⇒ 红）；⑤ `pytest -q tests/test_ci_hardening_workflow_wiring.py` + 对点
- **验收**：`publish-github-release` 的 `needs` 链不变；`build-release.yml` 仍仅 tag 触发；**合并方式按 GC2 走 SSH 本地 `--no-ff`**（含 workflows 的 PR 用 `gh pr merge` 必被拒）
- **回滚**：`git revert` workflow 定义；不触碰产物
- **依赖**：Stage 0；D1 若批准 Stage 2

#### T6 · [P2 UNVERIFIED] lock 可解性机械闸 + dependabot 解除条件
- **Finding**：审计报告 P2 #3
- **Files**：Modify `.github/workflows/ci.yml`（挂 `unit-2` 或 `static-invariants`，与静态闸同宿主）· 可能 Add `tools/check_lock_solvability.py`（D4 选 B 时）· Modify `.github/dependabot.yml`（解除条件注释 → 可判定说明）· Test `tests/test_lock_solvability_gate.py`
- **Consumes → Produces**：人工约定「合并依赖 PR 前真跑 `uv pip install --dry-run -r requirements.lock.txt`」→ 机械闸
- **修法**：按 **D4** 选 A（CI 装 `uv` 真求解，判据最强）/ B（纯 stdlib 解析 `==` pin 并校验 Python 版本标记与 pydantic↔pydantic-core 精确约束，快但非真求解）。**B 必须在文档里写明判据边界**，不得宣称等价于求解。闸失败要响亮（禁 `continue-on-error`）。
- **TDD**：① RED：把 lock 篡改成 `numpy==2.5.4`（Py≥3.12）或 `pydantic-core==2.50.4` ⇒ 闸红；② 记录；③ GREEN；④ 变异自证（把闸的 `if` 写成恒假 ⇒ 红）；⑤ 关联 + 对点
- **验收**：CI 三处 `pip install -r requirements.txt`（`:85` / `:334-338` / `:427-428`）保持不动（双清单口径有意设计）；`requirements.lock.txt` 只被文档与新闸引用
- **回滚**：`git revert`；不影响已发布产物
- **依赖**：D4 拍板；GC2（含 workflows）

#### T7 · [P2 UNVERIFIED] 发布 runbook 与孤儿 tag 恢复路径实证
- **Finding**：审计报告 P2 #4 · `WORKMEMORY/PROJECT_OVERVIEW.md:72`
- **Files**：Add `docs/agents/release-runbook.md`（或并入 `docs/agents/ops.md`，按 `docs/README.md` §分层选其一）· Modify `WORKMEMORY/PROJECT_OVERVIEW.md`（活项 6 收口）· 可能 Modify `.github/workflows/build-release.yml`（`publish-github-release` 的 `if` 与 dispatch 说明）
- **Consumes → Produces**：「`gh workflow run --ref <tag>` 理论可补发、本仓未实证」→ 有实证记录或明确标注「不可补发 + 替代路径」
- **修法**：在一个**废弃测试 tag** 上真跑 `workflow_dispatch`，以 **release 资产清单**为唯一判据记录结果；把「Publish 被跳过 / 孤儿 tag」的恢复步骤、判据、已知不可行点写成 runbook。**不得**把「理论可行」改写成「已验证」。
- **TDD**：本 Task 为文档 + 实证，无常规 RED；以「实证记录含命令、run id、资产清单原文、结论」为验收物
- **验收**：`tools/check_docs_layout.py` 绿（若新增 `docs/agents/*.md` 无需索引登记，但目录须在 §分层 内）；PROJECT_OVERVIEW 活项 6 状态更新须与实际一致
- **回滚**：文档 `git revert`；废弃 tag 删除须用户批准（不删也不影响）
- **依赖**：D1；实证需 GitHub 权限与用户批准

#### T8 · [P2 UNVERIFIED] 运行时三处静默降级：`.env` 覆盖 / 备份半截文件 / 单实例锁降级
- **Finding**：审计报告 P2 #7 + #8（部分）
- **Files**：Modify `delector/server.py:23`（`load_dotenv(override=...)`）· Modify `start.py:557-573`（口径对齐）· Modify `delector/routes/backup.py:73-93`（`xb` 写盘的 finally 清理 + 500 detail 脱敏）· Modify `delector/core/instance_lock.py:288-329`（降级时可见告警）· Test `tests/test_env_precedence.py` / `tests/test_wb_export_save.py` / `tests/test_instance_lock.py`
- **Consumes → Produces**：`override=True` 覆写显式 env → 与 `start.py` 一致的 `override=False`；`write` 中途失败留半截 JSON → `finally` 清理 + 具名错误（不回带绝对路径）；锁降级无提示 → stderr 可见告警
- **修法**：① 统一口径为「显式环境变量优先」，磁盘 `.env` 只补缺；② 写盘用「临时文件 + `os.replace`」或异常时 `unlink(target)`，500 detail 只回错误类别不含路径（本机闸已在，仍不泄露）；③ 降级路径打 warning，不改变「锁是加固层、不是启动前置」的既定语义
- **TDD**：① RED 三条（显式 env 不被旧 `.env` 覆写、ENOSPC 注入后半截文件不残留、锁降级有可见告警）；② 记录；③ GREEN；④ 变异自证各 1 组；⑤ 关联 + 对点
- **验收**：`.dockerignore` 排除 `.env` 的既有守卫不放松；`_require_localhost` 不放松；`tests/test_localhost_guard.py:243-254` AST 恒等断言不放松
- **回滚**：逐项 `git revert`
- **依赖**：无（可与 Stage 1 并行，但为减少冲突建议排其后）

### Stage 3 — 门禁自证与基准口径

#### T9 · [P2 UNVERIFIED] 门禁清单随扩容同步 + `check_layer_invariants` fail-loud
- **Finding**：审计报告 P2 #1（含 skeptic 降级的 P1-01）
- **Files**：Modify `tests/test_ci_hardening_workflow_wiring.py:285-290`（补 `Frontend style.css source sync gate`）· Modify `tests/test_ci_hardening_core.py:287-291`（补 `check_docs_layout.py`）· Modify `.github/workflows/ci.yml`（注释 6→7 分片 / 4→5 探针 / 3→4 判定器，含 `:643,:649,:683` 与 `:206,:171` 自相矛盾处）· Modify `tools/check_layer_invariants.py:262-297`（空扫描面 → 退 2；解析异常 → `ScanEnvironmentError`）· Test `tests/test_check_layer_invariants.py`（补环境错误路径用例）
- **Consumes → Produces**：清单漏项 + 注释漂移 + 空扫描面恒绿 → 与同族 `check_silent_degradation.py` / `check_mock_drift.py` 一致的 0/1/2 退出码语义
- **修法**：清单常量按 `ci.yml` 真实 step 名逐项对齐；`run_gate` 增加 `total_mods == 0` 与解析异常两条拒止（复用同族 `ScanEnvironmentError` 形态）；注释数字改成当前值，历史叙述保留「原先」措辞
- **TDD**：① RED：删 css sync 步 / 删 docs layout 步 / 把 `delector/` 置空 ⇒ 三条用例分别变红；② 记录；③ GREEN；④ 变异自证各 1 组；⑤ **搬家类改动按 GC8 跑全量 pytest + mypy 四档**
- **验收**：`tools/ci_shards.py` 7 键集合相等守卫仍绿；`test_ci_hardening_core.py` 的 unit-2 host 存在性守卫仍绿；静态不变量 job 的 4 步不得声明 `continue-on-error`
- **回滚**：`git revert`；CI 定义改动按 GC2 合并
- **依赖**：T6（同改 `ci.yml`，合并顺序先 T6 后 T9 或同分支一次改完，避免两次 rebase）

#### T10 · [P2 UNVERIFIED] 判据恒真 / 死测族替换
- **Finding**：审计报告 P2 #2（4 处）
- **Files**：Modify `tests/test_ci_hardening_core.py:32`（`setup-go@v5` 子串）· Modify `tests/test_frontend_guards.py:45-75`（字符串断言 + 越界切片）· Modify `tests/test_frontend_module_graph.py:44,209,609-620,753-757`（正则回溯 / 全文件声明即绑定 / 循环只钉 3 模块 / 无 node 时 skip）· Modify `tools/wb_export_probe.mjs:31-36`（锚点配平）· 对应 Test 各自补阴性用例
- **Consumes → Produces**：字符串存在断言 → 解析 YAML / 真链接 / 行为探针；越界切片 → 配平到 `)` 后要求下一个字符是 `{`，失败具名报错（红线 13）；`shutil.which("node")` 缺失时静默 skip → 在 CI 环境按 `conftest.py` 的 `pytest.exit(returncode=1)` 口径响亮失败
- **修法**：① `setup-go` 断言改为解析 `ci.yml` 的 `uses:` 真实值；② `openReader` 守卫改为 node 真跑行为探针（复用 `tools/article_store_probe.mjs` 的既有形态），`_extract_function` 切片按红线 13 修；③ 模块图正则加 `from` 边界、循环依赖改为全图遍历、`_module_local_bindings` 只收顶层声明；④ `sliceFunction` 跳过字符串/注释/模板
- **TDD**：① RED 每处一条阴性用例（把守卫保护物删掉/改错必须红）；② 记录；③ GREEN；④ 变异自证每处 1 组，共 ≥4 组；⑤ 前端 5 条探针 + 对点
- **验收**：`node --check` / 桩模块 / set 化导出三层**不重复建设**（历史教训：判据必须是「真链接整张图」）；静态层已红不得再跑 `node:vm`；沙箱不留两个真相源
- **回滚**：逐文件 `git revert`
- **依赖**：T9（避免同改 `test_ci_hardening_core.py` 冲突）

#### T11 · [P2 UNVERIFIED] 死代码、红线例外与发布文档规则 2
- **Finding**：审计报告 P2 #14
- **Files**：Modify `tools/check_docs_layout.py`（`_rel_dirs` 要么接线做空目录检查、要么删除；docstring 与实现对齐）· Modify `WORKMEMORY/PROJECT_OVERVIEW.md:58`（红线 10 登记 `tools/bench_judge_fp.py:454` 的离线例外及适用域）· Modify `tools/check_release_docs.py`（把 CHANGELOG FORMAT RULES 第 2 条「至少一个 `### 新增/修复/内部/文档`」做成机械校验）· Modify `docs/plans/2026-11-09-vocab-card-duplicate-merge.md`（§0 现状与 Step 2/3 前提随 Step 1 落地更新）· Test `tests/test_docs_layout_gate.py` / `tests/test_release_docs_gate.py`
- **Consumes → Produces**：docstring 承诺与实现不符 / 红线例外未登记 / 规则 2 无闸 / 方案稿现状过期 → 四处口径与代码一致
- **修法**：`_rel_dirs` 若接线，须注意 git 不跟踪空目录（CI 上难触发），只做本地自查能力并写明边界；红线 10 明确「只约束生产运行时路径，`bench_judge_fp.py` 是离线 FP 标定工具」；方案稿更新只改现状描述，**不替用户改策略选择**
- **TDD**：① RED：规则 2 缺小节 ⇒ 闸红；`_rel_dirs` 若接线则空目录 ⇒ 红；② 记录；③ GREEN；④ 变异自证；⑤ 关联 + 对点
- **验收**：`check_release_docs.py` 现有 10 例与 8 类变异自证不放宽；文档改动不进生产源码
- **回滚**：`git revert`
- **依赖**：Stage 0（本 Task 会改 PROJECT_OVERVIEW，须在 GC3 之后）

#### T12 · [P2 UNVERIFIED] 基准口径残留：跨进程比较与秒级单样本
- **Finding**：审计报告 P2 #15
- **Files**：Modify `tests/test_cold_start_cost.py:485-489` · Modify `tests/test_first_screen_from_log.py:62-71,218-250` · 可能 Modify `tools/bench_cold_start.py`
- **Consumes → Produces**：`health_200_ms > import_ms * 0.5` 的跨进程经验余量 → 同进程不变式或删除该断言；秒级单样本 → 明示「只能比总和、不得用于跨提交快慢判据」的口径声明
- **修法**：**删除或改写**跨进程量级比较（本仓已两次因此红 master），改用同进程内可复跑的不变式；`test_first_screen_from_log.py` 保持「解析器单测」定位，在 docstring 写清分辨率与不可用于量级比较；沿用现有「解析 + 由打印精度推导容差」口径，禁止 `pytest.approx(rel=)` 与格式化字符串相等
- **TDD**：① RED：构造抖动样本使旧断言假红（证明其非不变式）；② 记录；③ GREEN；④ 变异自证（写回 `0.5` 比值 ⇒ 新判据红）；⑤ `cost-guards` / `cost-cold-start` 两专项分片 + 对点
- **验收**：`bench_stats.py` 的 p95/median/`format_samples .6f` 口径不变；三个 bench 的容差与打印精度仍匹配
- **回滚**：`git revert`
- **依赖**：无

### Stage 4 — 前端状态机、运行时与对外口径

#### T13 · [P2 UNVERIFIED] 阅读页状态机残留
- **Finding**：审计报告 P2 #9（3 子项）
- **Files**：Modify `static/js/reader.js:410-454`（`finally` 复原）· `:443-444`（退避定时器）· `:456-468`（`processed_stale` 消费）· 可能 Modify `delector/routes/articles.py:206-213`（若需补后台重拉契约）· Test `tests/test_reader_state_probe.mjs` 或并入 `tests/test_frontend_guards.py` 的行为探针
- **Consumes → Produces**：占位串可被写回 / 退避 `setTimeout` 无句柄 / `processed_stale` 零消费 → 三项各自有确定行为
- **修法**：① `finally` 仅在当前 title 仍为占位串时复原为**空或上一篇真实标题**，且失败态不清空错误内容；保留既有 `token === _readerOpenToken` 防串台（skeptic 已证实它有效，不要重写）；② 保存 timer 句柄并在切换/卸载时 `clearTimeout`；③ 前端消费 `processed_stale`：显示「分词正在升级」提示并在完成后重拉一次（或按 D5/产品裁决只加提示）
- **TDD**：① RED 三条行为探针（失败后标题不留「载入中」、切换后无残留回调、`processed_stale=true` 时有可见提示）；② 记录；③ GREEN；④ 变异自证各 1 组；⑤ 前端 5 条探针 + 对点
- **验收**：`tests/test_article_readiness_fallback.py:112` 的后端断言不放宽；503 分支「正在准备德语分词模型」提示保留；`Retry-After` 与 `RETRY_BUDGET_MS` 不变
- **回滚**：`git revert` 前端文件；含 `static/` 改动需覆盖安装验证（§2.10）
- **依赖**：T10（守卫切片修好后行为探针才有可信判据）

#### T14 · [P2 UNVERIFIED] 失败终态缺失族
- **Finding**：审计报告 P2 #10 + #8 的 Android 探针子项
- **Files**：Modify `android/app/src/main/java/org/delector/app/MainActivity.java:652-660,686-695,789-799`（超时文案 / 探针返回值 / `readyHookInjected` 复位）· Modify `static/german/workbench.html:2605-2628`（`exportAndReport` try/catch + 两个 click 的 `.catch()`）· Modify `.github/workflows/build-release.yml:596-612`（Release 自动正文警示）· Test `tools/wb_export_probe.mjs` 补 `download()` 整体 reject 场景 · Android 侧补 Java 单元或模拟器点验
- **Consumes → Produces**：「正在重试」但不再重试 / unhandled rejection 零反馈 / 探针只认 `"missing"` / 旧版 tag 正文无警示 → 每条失败路径都有可见终态
- **修法**：① 预算耗尽后给终态文案 + 可点重试入口（不要假进行中）；② `exportAndReport` 外层 try/catch 并把失败 toast 纳入既有 `error` kind；③ 探针 `'err'` / 非预期值也要 `set(false)` 复位 CAS；④ Release 自动 body 加「请勿使用 v5.23.1 / v5.23.2」的静态警示（人工 `gh release edit` 覆盖的正文另行核对）
- **TDD**：① RED：导出 `download()` 整体 reject ⇒ 有失败 toast；就绪预算耗尽 ⇒ 文案为终态；② 记录；③ GREEN；④ 变异自证；⑤ `pytest -q tests/test_wb_export_save.py` + 前端探针 + 模拟器点验（x86_64）
- **验收**：**不得把模拟器结论写成真机已验证**；`tools/wb_export_probe.mjs` 的 6 场景名集合守卫 `tests/test_wb_export_save.py:156-168` 同步更新（新增场景须补进集合，防删段换绿）
- **回滚**：`git revert`；Android `versionCode` 不回拨
- **依赖**：T10（探针切片）、D1

#### T15 · [P2 UNVERIFIED] 资源无界、重复代价与索引治理登记
- **Finding**：审计报告 P2 #11（长文 DOM / 模型加载失败重复回退 / Go HTTP 背压）+ P2 #6（索引与 schema 治理，仅登记不改 DDL）
- **Files**：Modify `static/js/reader.js:510-544`（长文分段渲染，可选）· Modify `delector/nlp_engine/model_loader.py:334-365`（失败负缓存，与 `:207-253` 的成功 single-flight 语义对齐）· Modify `agent/internal/companion/server.go:52-105`（并发上限，按产品裁决）· Test 各自关联套件 · 文档：`WORKMEMORY/PROJECT_OVERVIEW.md` 活项 3 登记索引结论
- **Consumes → Produces**：无界增长 / 每请求重复三级回退 / 无背压 → 有界或明确登记为「本机单用户可接受」
- **修法**：① 模型加载失败写 `_nlp_error` 并置位「不反复重试」（与 `_resolve_nlp_model` 的既有语义对齐，注意别让首次分析永远拿不到重试机会）；② 长文改分段 `innerHTML` 或事件委托（减少每 `.tok` 两个闭包）；③ Go 背压**先评估**：本机单用户、无外层反代，若判定不改则在 CHANGELOG 已知限制登记，不要为了「看起来完整」硬加队列；④ 索引治理**不改 DDL**，只把「2 万行实测 35.86 ms / 本版不加索引 / 归 Step 2/3」的裁决写进活文档并补 `tests/test_query_plans.py` 的覆盖说明
- **TDD**：① RED：模型失败连续两次请求只加载一次（计数探针）；长文节点数有上限；② 记录；③ GREEN；④ 变异自证；⑤ Go `go test -race ./...` + 对点
- **验收**：**本仓 `agent/` 没有 `Enqueue` / `ErrQueueFull` / 队列满 503 机制**（审计报告已更正派单背景误套），不得照另一项目的形态立项；`go test -race` 覆盖不放松
- **回滚**：逐项 `git revert`；零 DDL
- **依赖**：无（性能项可延后至 Stage 5）

#### T16 · [P2 UNVERIFIED + P1 PLAUSIBLE] 对外口径一次性收口
- **Finding**：审计报告 P2 #12 + #13，以及 P1 #5（PLAUSIBLE，**只做口径核对，不当缺陷修**）
- **Files**：Modify `FEATURES.md:7,11,285`（版本标注与「刻意冻结快照」声明）· `WORKMEMORY/PROJECT_OVERVIEW.md:69`（门槛③数字 2962/2967 → 3040/3054，须先自己实测后写入）· `README.md:5,37-52,63,118,209`（3.10 徽章 / 「读到第一篇」指引 / 导出亮点措辞 / 反馈承诺 / WebView2 文案 / 开发者三步与端口）· `CHANGELOG.md:111`（「真机点验」措辞）· `requirements-desktop.txt:14,22`（注释与 pin）· `static/modals/settings_modal.html:261` 与 `static/index.html:2225`（脱网可达的本地说明）· `docs/README.md:31`（「plans/ 根目录已无在途计划」自 2026-11-09 起已失效）· `.github/ISSUE_TEMPLATE/feedback.md` 位置（门槛① 入口）
- **Consumes → Produces**：版本/数字/状态漂移、未验证被读成已验证、脱网自助信息不可达 → 四处口径同源；暂停状态是否披露按 **D5** 裁决
- **修法**：① 所有数字先实测再写（GC6），历史数字标时点而非删除；② README 首屏补「打开后读到第一篇」的最短路径与卡住时的自助处置（白屏 / 点开无反应 / Webpage not available 三种历史故障各一行）；③ App 内「已知限制」把关键未验证项**本地写出**，不再只指 CHANGELOG（注释明写「不放外链、不依赖 `/api/`」）；④ FEATURES 明确「特性全景快照、版本史正主是 CHANGELOG」，或按发版批次同步版本标注；⑤ `CHANGELOG.md:111` 区分「问题在真机点验时发现」与「修复在真机验证」；⑥ `docs/README.md:31` 更新为当前在途计划状态
- **TDD**：本 Task 为文档，验收物 = 一致性检查清单 + 机械闸：`python tools/check_release_docs.py`、`python tools/check_index_html_sync.py`、`python3 tools/check_docs_layout.py`、`pytest -q tests/test_writer_mobile.py tests/test_release_docs_gate.py tests/test_app_version_source.py`；`settings_modal.html` 与 `index.html` 的同文副本须由 `tools/build_index_html.py` + `tests/test_check_index_html_sync.py` 保持逐字一致
- **验收**：**不把「未验证」改成「已验证」**；门槛①（≥5 份反馈）、②（无协助成功）、④（真机点检）的开放状态如实保留；项目暂停表述按 D5；README 版本历史表仍只留 ≤3 行（CHANGELOG 格式规则 5）
- **回滚**：`git revert` 文档；若重算了测试数，同步分子与分母并标注时点
- **依赖**：T11（同改 PROJECT_OVERVIEW）、Stage 0（GC3）

---

## 5. 验证矩阵（命令从 `.github/workflows/ci.yml` 复制 `run:` 整行）

> 复跑 MUST 从 `ci.yml` 复制整行，不凭记忆拼参数；输出不截断、不用管道吞退出码（GC8）。

| 档位 | 命令 | 覆盖的 Task |
|---|---|---|
| Ruff | `ruff check .` | 全部 Python 改动 |
| mypy ① | `mypy --strict delector tools` | T1/T2/T3/T6/T8/T9/T11/T15 |
| mypy ② | `mypy --follow-imports=skip tests` | 全部新增/修改测试 |
| mypy ③ | `mypy --platform win32 --strict --follow-imports=skip desktop.py package_windows.py conftest.py start.py` | T4/T8（桌面入口面） |
| mypy ④ | `npx --yes -p typescript@5.6.3 tsc --noEmit` | T4/T13/T14 的前端边界 |
| 前端 5 探针 | `python tools/check_frontend_api_contract.py` · `python tools/check_index_html_sync.py` · `python tools/check_css_sync.py` · `python tools/check_frontend_layers.py` + 上面的 tsc | T4/T9/T10/T13/T14/T16 |
| pytest 7 分片 | `pytest -q $(python tools/ci_shards.py unit-1)` …（`unit-1..4` / `integration-heavy` / `cost-guards` / `cost-cold-start`） | 全部；T12 必跑两个 cost 专项 |
| 静态不变量 | `python3 tools/check_silent_degradation.py` · `python3 tools/check_mock_drift.py` · `python3 tools/check_layer_invariants.py` · `python3 tools/check_docs_layout.py` | T9/T10/T11/Stage 0 |
| 发布文档 | `python tools/check_release_docs.py`（经 `tests/test_release_docs_gate.py`） | T11/T16 |
| Go 三闸 | `gofmt -l .`（空即过）· `go vet ./...` · `go test -race ./...` | T15 |
| 真链路 | `go test -count=1 -json -tags integration ./...` + 零 SKIP / PASS>0 判据（整段 bash 从 `ci.yml:477-564` 复制） | T3/T8 改动后端时 |
| Windows 冒烟 | `pytest -q tests/test_server_packaging.py tests/test_server_health.py tests/test_desktop_port_guard.py tests/test_start.py` + `python tools/ci_heartbeat.py --stage build -- python package_windows.py` + verify 步 | T4/T5/T8（打包面命中时 CI 自动点亮） |
| 直推范围 | `python tools/check_master_commit_scope.py --range "<before>..<sha>"` | Stage 0 直推时（CI 自动） |

**本机既有噪声**（`README.md:17-21`）：`test_frontend_layers` 的 GBK 控制台解码、`test_player_tray_probe`、`test_probe_json_contract` 3 条 ERROR 在纯 `master` 上同样红，CI(Linux) 全绿；记录时须注明「本机噪声、非回归」，不得据此放宽断言。

---

## 6. 里程碑、发版与归档

| 里程碑 | 内容 | 出口判据 |
|---|---|---|
| M0 | Stage 0 决策文档合入 | `check_docs_layout.py` 绿；CI 绿；`master` 干净 |
| M1 | Stage 1 三个 Task 收口 | 3 条复现用例 + 变异自证留痕；全量门禁绿；**数据安全类改动须经 HITL 授权与 dry-run** |
| M2 | Stage 2 收口 | 发布 dry-run / SW 行为探针 / 覆盖安装验证（真机未点检则如实标注） |
| M3 | Stage 3 收口 | 每个新守卫阳性+阴性+变异三类用例齐；CI 13 项绿 |
| M4 | Stage 4 收口 | 文档一致性闸绿；20/20 追溯表全部闭合；CHANGELOG / PROJECT_OVERVIEW 同步 |

- **发版**：按 `WORKMEMORY/PROJECT_OVERVIEW.md` 红线 5，先跑「版本面五件套」（`sw.js` / `index.html` / `build.gradle` / `README` / `PROJECT_OVERVIEW` 当前状态），`tests/test_writer_mobile.py` 两条锁死；tag 打在含 bump 的合并提交上；`versionCode` 不回拨。
- **本计划归档**：成果随某 tag 发版后 `git mv` 进 `docs/plans/archive/`，并按 `docs/README.md` 归档待办表补登记；若拆成多版交付，按批次逐段登记，不要提前归档。
- **执行台账**：开工时按 `/dfs-exec` 生成 `2026-11-13-repo-health-remediation-ledger.md`（与归档计划成对），本方案稿阶段不建。

---

## 7. 追溯表（20 / 20 全覆盖）

| 折叠 finding | 严重度 / 徽章 | 归属 | 处置 |
|---|---|---|---|
| 关键 #1 restore 快照回写 | P1 CONFIRMED | **T1** | 修 |
| 关键 #2 数据目录漏 `progress.db` | P1 CONFIRMED | **T2** | 修 |
| 关键 #3 发布真启闸无硬截止 | P1 CONFIRMED | **T5**（+T7 补 runbook） | 修 |
| 关键 #4 SW 旧缓存回落（含 build-stamp / cache 无界同根） | P1 CONFIRMED | **T4** | 修 |
| 关键 #5 README 导出亮点 vs 冻结 exe 未验 | P1 **PLAUSIBLE** | **T16** | **仅口径核对，不当缺陷修**；真机点验归 Stage 5 门槛 |
| P2 #1 门禁清单未同步 | P2 UNVERIFIED | **T9** | 修 |
| P2 #2 判据恒真 / 死测族 | P2 UNVERIFIED | **T10** | 修 |
| P2 #3 lock 可解性无闸 | P2 UNVERIFIED | **T6** | 修（D4 定判据强度） |
| P2 #4 发布 runbook 缺失 | P2 UNVERIFIED | **T7** | 实证或明确登记不可行 |
| P2 #5 写路径事务边界 / 连接生命周期 | P2 UNVERIFIED | **T3** | 修 |
| P2 #6 索引与 schema 治理 | P2 UNVERIFIED | **T15**（登记）+ Stage 5 指针 | 不改 DDL，归 Step 2/3 |
| P2 #7 `.env` 覆盖显式 env | P2 UNVERIFIED | **T8** | 修 |
| P2 #8 失败路径资源清理与降级可见性 | P2 UNVERIFIED | **T8**（backup / 锁）+ **T14**（Android 探针） | 修 |
| P2 #9 阅读页状态机残留 | P2 UNVERIFIED | **T13** | 修 |
| P2 #10 失败终态缺失族 | P2 UNVERIFIED | **T14** | 修 |
| P2 #11 资源无界与重复代价 | P2 UNVERIFIED | **T4**（cache.put）+ **T15**（其余） | 修或明确登记 |
| P2 #12 活文档版本/数字/状态漂移 | P2 UNVERIFIED | **T16** | 修 |
| P2 #13 用户自助信息与状态披露 | P2 UNVERIFIED | **T16**（D5 定对外范围） | 修 |
| P2 #14 死代码与红线例外未登记 | P2 UNVERIFIED | **T11** | 修 |
| P2 #15 基准口径残留 | P2 UNVERIFIED | **T12** | 修 |

**校验**：折叠 finding 20 条全部有归属；`Task 数 = 16`，`20 < 56`（原始席位 finding 数），满足审计报告的折叠规则。

---

## 8. 不做范围 / 延后指针

- **词卡 Step 2 / 3**（存量重复 G/S/M 合并、建 UNIQUE、三套计数口径统一、`prep_saved` 缺 `refl`、备份还原 / wb 投影写锁统一）：已有方案稿 `docs/plans/2026-11-09-vocab-card-duplicate-merge.md`，本计划**不重复立项**；T3 的写锁统一不得提前改写 `tests/test_vocab_identity_upsert.py:284-302` 的 PRAGMA 过渡护栏。
- **宣传开闸四门槛**（≥5 份真实三问反馈 / 新手无协助读到第一篇 / README 首屏 / Android 真机点检）：属产品运营决策，T16 只补文档指引，不代用户宣布门槛达成。
- **ADR-0024 重跑 / 预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY`，不在本计划。
- **性能深水区**（长文虚拟滚动、Go 背压体系、SW 容量策略）：T15 只做有界化与登记；若需体系化改造，另开设计稿。
- **本计划不改的东西**：不新增依赖（除非 D4 选 A 并获批准）、不改 API 契约字段、不改 `app.mount("/", StaticFiles)` 的路由顺序（红线 2）、不改 import 期行为（红线 9）、不新增第二份切句实现（红线 10）、不放宽 `_require_localhost`（红线 7）、不启用 `?v=`（红线 6）、不禁用 pre-commit 密钥扫描、不用 `--no-verify`（红线 8）。
- **未验证项保持未验证**：冻结 exe 导出点击、macOS/Linux 导出、真实磁盘写失败、arm64 真机、PWA 安装提示、`gh workflow run --ref <tag>` 补发，均不得因本计划被写成「已验证」。
