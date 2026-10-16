---
to: any
from: codebuddy (GLM-5.2)
created: 2026-10-16
role: IMPLEMENT | TEST | VERIFY | REVIEW
required_capability: python-3.11 / spaCy(de_core_news_sm) / 真实 DEEPSEEK_API_KEY（只在 C1 之后的真跑才用）
status: open
---

# 交接包：审计修正 A/B 两批已合入 master；C 档 8 项与「裁判结论回灌」子计划待接手

## 一、任务上下文（60 秒读完）

- **本会话起点**：§4.3 第 8 条对照实验（60 局真跑）已由另一 agent 交付，结论 = **P1（奖励黑客）在本形态下无发生机制**（阴性对照 `last_candidate(A2) ≡ (A3) = 0.974`，判据见 **ADR-0024**）。
- **用户随后交办**：① 对**非在途面**做专家团队评估 → ② 出「未决项登记表」→ ③ 按 **A 档 → B 档** 施工（"1 2 3 补入口…4 切分 5 做前置"）。
- **现状**：**5 份评估报告 + 18 项未决项登记表 + A 档 8 项 + B 档 5 项全部落地**；A+B 前四项已合入 master。
- **唯一待办入口**：`docs/reviews/2026-10-16-open-items-backlog.md`（A/B 已标完成，**C 档 8 项待做**）。
- **计划正本**（均已 100%）：`docs/plans/2026-10-16-audit-fixes-a-series.md`（5/5）· `docs/plans/2026-10-16-audit-fixes-b-series.md`（4/4）· `docs/plans/2026-10-16-database-split.md`（5/5）。
- **分支/PR**：**两个 PR 均已 MERGED** —— `#143`（A 档 + B1/B2/B3/B5）@ `459343b`（SSH 本地 `--no-ff`，因它改了 `.github/` 而 `gh` 无 workflow scope）；`#144`（B4 database.py 切分）@ `c79e764`（`gh pr merge` 直接成功，因 B4 未碰 `.github/`）。**master 当前 = `c79e764`**，两个 feature 分支已删。

## 二、已完成（含可取证证据）

| 项 | 提交 | 关键证据 |
|---|---|---|
| **A1** P0-1 还原静默丢训练记录 | `0b0509b` | `RestoreReq` 补两表 + `_replace_tables` 前向兼容闸（判据=键存在性，不写 `if not rows`）· 3 条守卫（41→44 passed）· 2 组变异双杀 · CRV **PASS** |
| **A2** P0-2 退出挂死 + 假成功 | `2219481` | `SHUTDOWN_GRACE_S=5` **单源三处共用** · `join` 改有界轮询 · 尊重 `shutdown()` 返回值（stderr + `exit 1`）· 4 用例全用桩、零真线程 · 92 passed · CRV **PASS** |
| **A3** P1-1 凭据随备份外泄 | `41f7626` | 前端 `BACKUP_LS_EXCLUDE` 导出/还原**双侧**过滤 + 后端 `_BACKUP_LS_DENYLIST` 权威闸 + `test_server.py:1031` 契约**强化** · 24 passed · 变异①②双杀 · CRV **PASS** |
| **A5** 测试库落点治因 | `2124f1e` | 绝对临时路径（保留 `setdefault` 语义）· `ROOT_DB_NAMES` 扩含 `test_*.db` · 守卫复用既有 helper · **拆除无界递归进程炸弹**（两道冗余防线，各自独立充分） |
| **A6+A8** 文档漂移 + 簿记 | `311466d` | `ops.md` 数据目录口径 · `architecture.md` 的 `/api/settings` 鉴权/门禁基线/前端模块数/`start.py` 行数 · `README` 目录结构 · 2 份 handoff 归档 · `INDEX.md` 新增「已归档 handoffs」段 |
| **A4** = 过期条目 | — | 三类裁判 FP 修复**早已在 `39e6d79` 落地**；本轮实跑核验净零改动（12/12 误报句零违规 + 7/7 负样本仍报 + 硬门 + 基准脚本一致） |
| **B1** master 直推机械闸 | `25e45ce` | 判定器 + `.githooks/pre-push` + `ci.yml` job；**纠正计划**：`--no-merges` → `--no-merges --first-parent`（否则每次正常 PR 合并都会误判，有实测铁证）；真历史窗口报 **33 条违规**（含 `f49d359`） |
| **B2** CRLF 仓库契约 | `9bac801` | `* text=auto eol=crlf` 置于 `*.go eol=lf` 之前；抽查确认 Go 未被反转、blob 未重写 |
| **B3** design-system 入口 + 过时更新 | `8b8f469` | 三处入口 + token 表按 `tokens.css` 现值重写（逐条带行号）+ 失效条目改「历史稿」保留 |
| **B5** harness 七件前置 | `c385ea7` | JSONL+`--resume` / 有界重试 / `temperature` 钉定并记录 / 连通预检 / 成本闸 `exit 3` / rater 入口 / `include_usage` opt-in；`--dry-run` 60 records 全绿 |
| **B4** `database.py` 切分 | `8c81d8b`→`fda6f6a` | **2809 → 359 行（-87%）**；切出 `db/{connection,backup,schema,content,vocab,records,settings}`；**公开面零变化（32 import 点未改）**；安全网升级为**双向差集对账**；`mypy --strict` 76 files 0 |

## 三、未完成与下一步（按建议顺序）

1. **C1（无条件下一步）**：**裁判结论回灌（verifier-in-the-loop）** 子计划。ADR-0024 登记了四条硬依赖：① ~~裁判 FP 先修完~~（**已确认基线已完成**）② 回灌内容 MUST 过同一道适用性闸（`violations_for`/`_polish_violations_of` 单参口径）与同一道双限截断（`truncate_evidence`：40 行/4000 字节）③ 定三角一致性（循环裁判带 nlp / `writing_check` **不带** nlp / 回灌源）④ 阴性对照 `last_candidate(A2)≈(A3)` MUST 在动产品之前先跑成基线。⚠️ 回灌一旦落地，§4.3 实验的阈值与结论**只对"准入式裁判"有效** ⇒ 必须重跑或明确分域（ADR-0024 已登记资产折旧）。
2. **C2**：swarm audit 的 **P1-3~P1-5 三条 UNVERIFIED** 按报告给的精确命令补证后再定级（抓取无总截止 / Go supervisor 无累积重启上界 / DeepSeek 退避无 jitter）；P1-2（备份非一致快照，低危，`BEGIN DEFERRED` 三行）。
3. **C3**：真轮次分布与**真 token 计数回测**（ADR-0023 §6 Unknown 2；`CHARS_PER_TOKEN_ESTIMATE=3.0` 仍 UNVERIFIED）—— 与 B5 的 `include_usage` 透出同源，可直接用。
4. **C6/C7/C8**：测试文件按被测面切分 · `workbench.html`（4730 行单文件 PWA）拆分（**先做"整文件/行级探针改按段读入"**，否则 4 个测试文件全红）· 其余 P2 批次（`git gc` / `renormalize` / `*.spec` 收窄 / `gradle-wrapper.jar` / TTS 三连 / encounter 大小闸 / settings 掩码 / CI 密钥扫描 / 恒真断言）。
5. **C4/C5**：Android 真机点检 · Pi 式分层重构（用户已拍板暂缓）。

## 四、风险与坑（本会话血泪，务必读）

1. **进程炸弹范式**（已拆，但**范式必须沿用**）：嵌套 `pytest` 跑整个模块且无递归哨兵 ⇒ **无界进程链**（实测每 2~3 秒一代、稳态约 240 个重型进程、命令永不返回，**曾致用户设备卡死**）。任何子进程调用 MUST 有超时 + **两道冗余防线**（env 令牌哨兵 + 命令行 `-k` 排除自身），范式见 `tests/test_get_endpoints_with_writes.py`。⚠️ 哨兵 MUST **令牌化**（`str(os.getpid())` vs `str(os.getppid())`，不匹配即 `fail`），否则外部残留变量会把守卫变成**永远不跑的假绿**。
2. **"本地红 / CI 绿"的成因**：仓库根只要存在 `*.db`，`tests/test_save_wb_state_cost.py` 的迁移闸就**拒绝运行**（`tests/conftest.py:16-19` 明文）。本会话已把根目录库改名 `delector.db.bak-20261016-175607` / `progress.db.bak-20261016-175607`（**可恢复，别删**）。**给 subagent 的 `DATABASE_PATH`/`PROGRESS_DB_PATH` MUST 用仓库外绝对路径**（我一度用相对路径 `.tmp-tX.db`，在仓库根造出 9 个残留）。
3. **patch 触达失联**（B4 迁移的真实代价，累计 **12 处 / 5 个测试文件**）：`monkeypatch.setattr` 必须命中「**被调用方所在模块**」；搬模块后 MUST **逐切片重新扫查**（`grep -rnE "setattr|patch\.object" tests/`）。**安全网只覆盖公开名（排 `_` 前缀）⇒ 私有名的触达性不在网内**。
4. **CI 触发只认 `base=master`**（`.github/workflows/ci.yml:24-28`）：给 feature 分支开 PR **不会跑 CI**；改 base 也**不触发**（`edited` 不在默认 trigger 里）——需 push 或 **close→reopen**。**栈式 PR（feature→feature）在前一个合入后 MUST 显式 `gh pr edit <n> --base master`**，否则它一直没 CI。
5. **`gh` token 无 `workflow` scope**：凡是改了 `.github/` 的 PR，`gh pr merge` 会被服务端拒绝 ⇒ 只能 **SSH 本地 `--no-ff` 合并**（#136/#137/#143 都是这条路径）。注意 Git 远端是 `ssh://ssh.github.com:443`（22 端口不通）。
6. **`.gitattributes` 新契约的可见副作用**：工作区现有 **49 个文件是 `w/lf`**（含 `docs/design-system.md`）⇒ **下次 checkout 会变 CRLF**，届时可能出现"莫名其妙的行尾 diff"，**属预期**（B2 的意图）；未做 `--renormalize`（刻意避免全量 diff）。
7. **B1 机械闸的语义边界**：拦的是「**直推 master 的非 merge 提交的改动面出白名单**」；它**不拦**"删改"（只按改动面判）。白名单 = `WORKMEMORY/` · `docs/` · `README.md` · `CHANGELOG.md` · `static/index.html` · `static/sw.js` · `android/app/build.gradle` · `delector/core/version.py`。
8. **`database.py` 的残留**：只剩 `_require_localhost` 一个 `def`（**非 DB 关注点，刻意留在持久层包之外**）。要达成"纯 façade"需另开 `core/net_guard.py`（属命名/分层整理，本轮 out of scope）。
9. **版本面待同步**：本批新增了不少测试（A1 3 条 / B1 14 条 / B4 2 条 / B5 若干）⇒ **下次发版**须按 `ops.md` 的口径同步版本面数字（当前 master **未发版**，故未动）。
10. **vault 侧**：`99-Inbox` 还有 **2 张草稿**待 `/dfs-inbox-consolidate`（登记表 A7，已注明"并入既有规则、勿另立新规"）。
11. **本地验证 MUST 逐字复刻 CI 的门禁命令**（本轮两连红的第二红 = 我只跑了"单文件 + 相似 flags"，而 CI 是 `mypy --follow-imports=skip tests` **整目录** + `--strict delector tools` **含 tools/**）。**不许用近似代替**：CI 的确切两条是 `mypy --strict delector tools` 与 `mypy --follow-imports=skip tests`（`.github/workflows/ci.yml:90-94`）。
12. **`__file__` 相对路径在模块搬家后会静默偏层**（本轮 B4 的第一红，**只在干净 checkout 暴露**）：`_PKG_DIR` 的值 = `delector/core`（切分前 `dirname(database.py)`）是**冻结面**，搬进 `delector/core/db/` 后必须取**两级** dirname 才能保持同值；否则 `preset_processed_data_path()` 会多出一层 `core/`，而**本地若恰有散落文件则全绿**（本轮就是这样骗过我和两个 maker 的）。守卫：`tests/test_backend_package_layout.py::test_preset_processed_data_path_survives_module_moves`（与既有 `DATA_DIR`/`STATIC_DIR` 两条同族）。**今后任何搬包 MUST 顺带重核所有 `__file__` 派生路径**（`delector/core/db/` 内现已只有这一处，且 `_REPO_ROOT` 用的是抗搬家的"向上走到非包目录"写法）。

## 五、环境与凭据

- `.env` 已配 `DEEPSEEK_API_KEY`（**gitignored 且未跟踪**）；harness 经 `delector.server.load_env()` 载入。**真实 API 调用需用户确认**（B5 只补了前置，**未真跑**）。任何输出/报告 MUST NOT 含 key 本体。
- 台账 `.vault-exec-ledger.json` 是**未跟踪的工作文件**（当前内容 = B4 计划 5/5）。A 系列与 B 系列台账曾被覆盖，备份在 `/tmp/ledger-*.json`（**临时路径，多半已失效，勿依赖**）。
- 自动化脚本：`python /d/Obsidian/Coding/scripts/vault_exec_state.py {init --plan-file <p> | start-task --task-id <t> | complete-task --task-id <t> --commit <sha> --reviewer PASS | status}`。
- 提交信息**禁 inline `-m`**（中文 + 引号会截断/静默缺字）⇒ 一律 `git commit -F <file>`，消息文件用 `python - <<'PYEOF'`（**定界符带引号**）生成。行尾统一 **CRLF**（改完自查 `lone_LF=0`）。
- **负载纪律**（用户明确要求）：**本地不跑全量套件**（全量交 CI）；只跑定向文件；不并发起多个重负载 python 进程（用户同机还有别的 agent 在跑）。
