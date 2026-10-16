# 未决项登记表（Open Items Backlog）

> **快照时间**：2026-10-16 · **基线**：master `dac3a8b`（PR #138/#139/#140/#141 全部合入后），本地全量套件 **2135 passed + 2 skipped**。
> **为什么放 `reviews/` 而不是 `plans/`**：`docs/README.md` 规定 `plans/` 只放**在途**实施计划；本表是四份评审报告 + ADR-0023/0024 的**汇总登记**，多数项尚未开工、其中 5 项还等用户拍板 —— 放进 `plans/` 会让人误以为 18 项都在动。
> **维护规则**：某项开工 ⇒ 按 `docs/README.md` 另立 `plans/<日期>-<主题>.md` 并在本表对应行标注「已转计划」；完成后划掉并写进 `CHANGELOG.md` / ADR；每次评审或 ADR 更新后回填本表。

---

## 0. 已闭项（对照，防重复劳动）

裁判集扩充 8/8（`wortstellung`/`artikel`/`kasus`/`rektion`/`numerus` error 级 + `tempus` advisory）· 对照实验 8/8（60 局真跑，阴性对照 A2≡A3=0.974）· 内核接缝加固（dispatch 超时 / 同步裁判移出事件循环 / 不可达 except）· ADR-0023 §10/§11 与 ADR-0024 回写 · 非在途面评估 4 份报告 · 卫生修正批次 1（`.gitignore` 运行态产物缺口、`.superpowers/`、`.env.example`、`CLAUDE.md` 路由、`08-Inbox→99-Inbox` + 守卫测试）· 根目录陈旧库文件改名（`.db.bak-20261016-175607`，真实数据在 `%LOCALAPPDATA%\DeLector` 未动）· worktree 与已合并分支清理。

---

## A 档：已定案、可直接开工（无决策依赖）

> **本轮结算（2026-10-16，计划 `docs/plans/2026-10-16-audit-fixes-a-series.md`）**：**A1 / A2 / A3 / A5 / A6 / A8 已落地**；**A4 = 过期条目**（详见该行）；**A7** 归 `/dfs-inbox-consolidate`，不在本计划。

| ID | 事项 | 依据（可取证） | 成本 / 风险 | 前置依赖 |
| --- | --- | --- | --- | --- |
| **A1** | **P0-1：`/api/backup/restore` 静默清空 `listen_trials` + `hard_sentence_trials`**。修法：`RestoreReq` 补 2 字段 + `_replace_tables` 加前向兼容闸（`name not in payload ⇒ continue`）+ 契约测试断言 `set(_BACKUP_TABLES) - set(RestoreReq.model_fields) == set()` | `docs/reviews/2026-10-15-swarm-audit-master.md` P0-1；CONFIRMED 且已用真实 `_replace_tables` 复现。锚点：`database.py:1573/:1598`（清单 10 表）vs `routes/main.py:1747-1768`（8 字段）+ `database.py:1901`（无条件 DELETE） | 小。**唯一「用户数据不可逆丢失且零提示」的缺陷**；与 `database.py:1492-1496` 修过的同类 bug 是第二次发生 ⇒ 缺的是「清单 ↔ 还原模型」一致性守卫 | 无 |
| **A2** | **P0-2：退出路径挂死 + 假成功日志**。修法：`build_server` 加 `timeout_graceful_shutdown=5`；`start.py:186-187` 改为尊重 `shutdown()` 返回值（失败 ⇒ stderr + `sys.exit(1)`）；`start.py:180` 的 `thread.join()` 加超时 | 同报告 P0-2；质疑席**纠正了机制**：真因是 `start.py:180` 无超时 join + `server_lifecycle.py:60` 非 daemon 线程 + `start.py:186` 丢弃返回值 + `start.py:232` 裸调 `main()` 无 `SystemExit`（**不是**席位原报的 `Server.shutdown()` 无限等） | 小。⚠️ **必须按纠正后的机制修**，别照原说法改。与历史「孤儿 uvicorn 让门禁假绿」同形 | 无 |
| **A3** | **P1-1：备份 JSON 带走 `wb.pair.v1`（长期 `wb_sync_key` + 内网 host）**。修法：`cards.js` 备份/还原**双侧**过滤该键 + 后端 `main.py:1636` 按键名黑名单过滤（权威闸必须在后端）+ 契约守卫 | 同报告 P1-1；code-reviewer 与 dba 两席**合并**为同一缺陷，CONFIRMED。锚点：`database.py:806`（不轮换）/ `cards.js:1005-1020`（`wb.` 前缀全扫无 exclude）/ `main.py:1636`（原样透传）/ `database.py:1444`（后端白名单明确排除）/ `encounter.js:1295`（键确含 key） | 中。⚠️ **必须同步改 `tests/test_server.py:1031`** —— 它把「local_storage 原样透传」钉成了契约，不改则新守卫与旧契约对撞 | 无 |
| ~~**A4**~~ **✅ 已闭（过期条目）** | 裁判 FP 三类修复 | **2026-10-16 核验：三类修复早已在 `39e6d79`（裁判集扩充 Task 3/4/5）落地** —— 本轮实跑 12/12 误报句零违规、7/7 负样本仍报、官方 10 篇 + 51 句硬门 + `tools/bench_judge_fp.py` 复跑一致、三组变异证明守卫有判别力、**净零改动**。⚠️ 本条是编排者写登记表时未核基线造成的**过期条目**（教训：登记"待修"前 MUST 先在基线复跑一次目标句） | — | **已闭** |
| **A5** | **测试库落点改绝对路径**：`conftest.py:30-31` 与 `tests/test_get_endpoints_with_writes.py:37-38` 的裸相对文件名 ⇒ `tmp_path_factory`/显式临时目录；`tests/db_cleanup.py:72` 的 `ROOT_DB_NAMES` 扩为含 `test_*.db` | `docs/reviews/2026-10-16-repo-structure-and-docs-audit.md` P1-1。⚠️ 2026-10-16 只改了**症状**（根目录库改名），病因未修 ⇒ 下次任何人跑测试又会造出来 | 小。修完后「本地红 / CI 绿」分歧根治 | 无 |
| **A6** | **文档三处漂移对齐**（纯文档，零代码）：① `docs/agents/ops.md:53-57` 数据目录口径与 v5.17.0 事实相反（且与本文件 47-51 自相矛盾）② `docs/agents/architecture.md:202/:93-94` 称 `POST /api/settings` 无鉴权（实测 `routes/main.py:1500-1502` 第一行就是 `_require_localhost`）③ 门禁基线与前端模块数改「现读口径」（实测 122 测试文件 / 1986→2135 条 / 探针 29 / `static/js` 23 个，停更在 2026-08/09 的 352/719/10 与 10~11 个） | 同报告 P1-2 / P1-3 / P1-4 | 小。②③ 会直接把后续 agent 引向错误动作（重复加固 / 漏验 19 个探针 / 漏整块前端模块） | 无 |
| **A7** | **vault 两张草稿过 `/dfs-inbox-consolidate`**：`99-Inbox/2026-10-15-规则引擎硬门必须按「类」覆盖正样本…md`（附「自动化接线三证」「UNVERIFIED 逐条核销」两条既有规则的新实例）与 `99-Inbox/2026-10-15-bash-standards-§5.3-缺的一条…md`（嵌入 ASCII 双引号会提前闭合 `git commit -m` 参数） | 本会话沉淀产物；查重时确认两条规则本体已存在 ⇒ 草稿已注明「归档时并入对应规则，勿另立新规」 | 小 | 无 |
| **A8** | **收尾簿记两件**：① `WORKMEMORY/INDEX.md` 里 status: closed 的 handoff 仍占位，与 `INDEX.md:16`「仅当存在活跃交接时才存在」矛盾 ⇒ 移入 `WORKMEMORY/archive/` 或补清理事件；② 根目录 4 个 `test_*.db` 残留清理（测试产物，`*.db` 已忽略，不影响门禁） | 结构 audit P2-8 | 极小 | 无 |

---

## B 档：需要你拍板才能动

| ID | 事项 | 要你定什么 | 依据 |
| --- | --- | --- | --- |
| **B1** | **P1-1 分支纪律机械闸**：pre-push hook 或 CI job 断言「master 上非 merge 提交的改动面 ⊆ {WORKMEMORY/, docs/, README.md, CHANGELOG.md, static/index.html, static/sw.js, android/app/build.gradle, delector/core/version.py}，否则 fail」 | ① 白名单口径；② 接受「合并得走 SSH 本地 `--no-ff`」（本仓 `gh` token 无 `workflow` scope，#136/#137 已演示过该路径） | `docs/reviews/2026-10-16-commit-rhythm-and-git-management-audit.md` P1-1。2026-10-09~14 有 **25 个实现类提交直推 master**，已有实发事故 `f49d359`（直推把 master 推红才回头补）；规则 2026-10-14 才进可见文档 ⇒ 此前 agent 按 `AGENTS.md` 读不到 |
| **B2** | **P2-7 `.gitattributes` CRLF 契约**：加 `* text=auto eol=crlf`（置于 `*.go text eol=lf` **之前**，让具体规则覆盖通用规则） | 要把「行尾 CRLF 是纪律」从**本机 `core.autocrlf=true` 的副作用**升级为**仓库契约**吗？副作用：Linux/macOS clone 也会拿到 CRLF（这正是意图），但属跨平台行为变更 | 同报告 P2-7。现状：`.py/.md/.js` 无 attr，实测 `attr/` 空 + `w/crlf`；9 个跟踪文件工作区 `w/mixed`（历史干净） |
| **B3** | **P2-3 `docs/design-system.md` 定夺**（606 行） | 二选一：① 在 `AGENTS.md` 路由表补入口并同步 token 表现在值；② 把状态改为「历史设计稿（v3.0 · 2026-08，未随 tokens.css 同步）」 | 结构 audit P2-4。现状：被 `docs/README.md:16` 列为**顶层常青规范**但全仓零入口；`--bone`/`--ink-blue`/`--paper-dark` 等 7 token 与 5 个色值在 CSS 里**逐个 grep 零命中** |
| **B4** | **`core/database.py` 按职责切分**（2809 行 / 86 def / 9 组职责 / 32 处被 import） | 时机：报告建议 **A1 修完并补契约测试之后**再切（否则切模块会顺手丢掉「清单 ↔ 还原模型」这类不变量） | `docs/reviews/2026-10-15-refactor-candidates.md` 候选 #1；已知与 `nlp_engine/processor` 有双向耦合 |
| **B5** | **实验 harness 工程前置**（7 件）：逐篇落盘+断点续跑 / 有界重试（429/5xx/传输层，2 次+退避+jitter）/ `temperature` 显式钉定并记入 `RunRecord` / `--real` 连通预检 / 成本硬闸 / rater 补可执行入口 / `llm_client.chat` 透出 `usage` | 只在「要重跑或续跑实验」时才值得全做；不跑的话至少做 **temperature 钉定 + usage 透出**两项（成本记账要用，现在走 `ceil(len/3.0)` 且只计 completion、不计 prompt，系数登记 UNVERIFIED） | ADR-0024 Consequences「已知未决」；`docs/reviews/2026-10-16-judge-gaming-control-experiment.md` |

---

## C 档：阻塞 / 暂缓（等外部条件或已登记不急）

| ID | 事项 | 状态与硬依赖 |
| --- | --- | --- |
| **C1** | **下一子计划：裁判结论回灌（verifier-in-the-loop）** | **无条件下一步**（P1/P2 两种结局下都是同一笔代码），但有四条硬依赖（ADR-0024）：① **A4 先完成**（裁判 FP 修完）② 回灌内容 MUST 过同一道适用性闸（`violations_for`/`_polish_violations_of`）与同一道双限截断（`truncate_evidence`：40 行 / 4000 字节）③ 定三角一致性（循环裁判带 nlp / `writing_check` **不带** nlp / 回灌源）④ 阴性对照 `last_candidate(A2)≈last_candidate(A3)` MUST 在动产品之前先跑成基线。另：回灌一旦落地，本实验阈值与结论只对「准入式裁判」有效 ⇒ **必须重跑或明确分域**（ADR-0024 已登记资产折旧） |
| **C2** | **swarm audit P1-2 / P1-3 / P1-4 / P1-5** | P1-2 备份非一致快照（`database.py:1734-1765` 无 `BEGIN`，两库独立连接）—— 低危，`BEGIN DEFERRED` 三行可解。P1-3~P1-5 **三条均 UNVERIFIED**：抓取无总截止（`core/security.py:177-237`，最多 6 跳 × 15s）/ Go supervisor 无累积重启上界（`supervisor.go:245-267,:279`）/ DeepSeek 退避无 jitter（`deepseek.go:76,:96-106,:160`）—— **需按报告给的精确命令补证后再定级，不得据此下阻塞结论** |
| **C3** | **真轮次分布与真 token 计数回测** | ADR-0023 §6 Unknown 2 未决；`polish_loop.py` 的 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 仍是 UNVERIFIED 假设。与 B5 的「usage 透出」同源 |
| **C4** | **Android 真机点检**（含新 API 在 WebView 的 `fetch`/`ReadableStream` 表现，跑不了会降级一次性 JSON，降级路径本身要真机确认） | 你 2026-10-15 指示暂缓 |
| **C5** | **Pi 式分层重构**（`Tool → AgentTool extends Tool → ToolDefinition` 三态递进 + 依赖单向 + 层序声明 + 业务知识上提） | 你已拍板暂缓；目标形态登记在 `docs/agents/architecture.md` |
| **C6** | **测试文件按被测面切分**（`tests/test_server.py` 7271 行 / `test_german_workbench.py` 3913 / `test_desktop_shell.py` 2664） | 只搬归属、不改用例；`test_server.py` 须避开 ai-polish 测试段（在途面） |
| **C7** | **`static/german/workbench.html` 拆分**（4730 行单文件 PWA：种子数据/g2p/存储/wbsync/WebRTC/IndexedDB/TTS/FSRS/短码同步/导入导出/PWA） | **先做「整文件/行级探针改按段读入」**，否则 4 个测试文件全红（含 `index("const tryServer")<index("const tryOnline")` 这类全文位置断言与按行号钉 `wbsync.push()` 的探针） |
| **C8** | **其余 P2 批次** | `git gc`（松散对象 49.10 MiB，`gc.auto` 疑似未生效）· 9 个文件 `git add --renormalize`（工作区 `w/mixed`，历史干净）· `*.spec` 收窄为 `/DeLector.spec`（当前无害）· `android/gradle/wrapper/gradle-wrapper.jar` 未入库（待确认 CI 是否依赖）· TTS 三连（重试零退避 / 30s 连接超时偏长 / **静默**退回未验证 SSL context）/ encounter 抓取无大小闸（可复用 `security.py` 的 2MB 闸）/ `GET /api/settings` 非回环来源不掩码 `api_key_masked` / `clear_audio_cache` 静默吞错且 `freed_mb` 用清理前的 info / CI 无密钥扫描 / `test_desktop_shell.py:2109` 恒真断言 |

---

## 建议顺序（如果只做三件）

**A1 → A2 → A3**：两个 P0 + 一个 P1，全部「已证实 + 低成本 + 消真实事故」，且彼此无依赖，可一个分支串行交付。
A4 紧随其后（它是 C1 回灌子计划的硬门）。B 档里 **B1** 我个人认为最值得先拍 —— 它是本仓唯一「已经实发过事故、且规则本身没有机械闸」的纪律缺口。

## 追踪提示

- 本表**不替代**计划：任何一项开工，按 `docs/README.md` 另立 `docs/plans/<日期>-<主题>.md`，并在本表对应行标注「已转计划 → `<路径>`」。
- 判据表第 8 条（§4.3）已由对照实验回答（结论：**P1 本形态下无发生机制**，见 ADR-0024 与 `docs/reviews/2026-10-16-judge-gaming-control-experiment.md`）—— **不再是待办项**，勿重复排期。
