# 项目结构与文档质量评估（DeLector，master @ `bb70c5f` 之前）

**Date**: 2026-10-16 · 分支 `chore/swarm-audit-master`（评估专用，不碰在途分支）
**席位**：`code-explorer`（结构清点）+ `code-reviewer`（文档/README 质量）。两席均只读、未改任何文件。
**Findings**：**13** 条（合并后）← 原始 **18** 条（结构 4 / 文档 14）。**无 P0**：入口文档的版本面与 `APP_VERSION`/git tag 一致且有机械闸守护。

---

## 一、P1（4 条，都会把后续 agent/用户引向错误动作）

### P1-1 · 测试库写进仓库根：相对路径副作用 + 会话守卫看不见 `test_*.db`
**[code-explorer]** 证据：`conftest.py:30-31` `os.environ.setdefault("DATABASE_PATH", "test_conftest_default.db")`（相对路径 ⇒ 解析到 CWD）；`tests/test_get_endpoints_with_writes.py:37-38` 同样裸文件名；而 `tests/db_cleanup.py:72` 的 `ROOT_DB_NAMES = ("delector.db","progress.db")` 与 `tests/conftest.py:38-56` 的会话守卫**只比这两个名字** ⇒ `test_*.db` 完全在守卫视野外，而 `*.db` 被 `.gitignore` 挡住 ⇒ 泄漏可无限期无人发现。
失败场景：① `delector.db`/`progress.db` 落根是**已知旧落点**（`core/data_dir_bootstrap.py:108-115` `legacy_data_dir()`，首启会被搬去 `%LOCALAPPDATA%`），但 `test_*.db` **没有任何设计理由**落在根；② 仓库根有库会让 `test_save_wb_state_cost.py` **拒绝运行**（`tests/conftest.py:16-19` 明写）⇒ **本地红 / CI 绿**的迁移闸假象。
修法：`conftest.py:30-31` 与 `test_get_endpoints_with_writes.py:37-38` 改 `tmp_path_factory`/显式临时目录**绝对路径**；`db_cleanup.ROOT_DB_NAMES` 扩为含 `test_*.db` 让会话守卫看住。

### P1-2 · `docs/agents/ops.md:53-57` 数据目录口径与 v5.17.0 事实相悖（且与本文件 47-51 自相矛盾）
**[code-reviewer]** 漂移：`ops.md:54-55` 写「桌面端 `DATA_DIR` = 仓库根、桌面端不设该变量」；但同文件 `:47-51` 写着「真实跑 `start.py` 会触发数据外置迁移，把仓库根的库改名 `.bak-<时间戳>` 并复制到 `%LOCALAPPDATA%\DeLector`」，`README.md:101-105` 亦同。
失败场景：agent 按 `:54` 判断"桌面数据在仓库根"→ 在仓库里跑 `start.py` 做 dev 验证 → 触发 `bootstrap_data_dir` 把**真实 `delector.db` 改名成 `.bak`** 并复制走 ⇒ 工作区被污染 + 用户侧看到"数据丢了"（正是 `:47-51` 自己警告过、且"已多次在任务实跑时发生"的事故）。
修法：改为「桌面默认 `%LOCALAPPDATA%\DeLector`；`DELECTOR_PORTABLE=1` 或 `DELECTOR_DATA_DIR` 才回落程序目录」，Docker 段保留。

### P1-3 · `docs/agents/architecture.md:202/:93-94` 宣称 `POST /api/settings` **无鉴权** —— 与代码相反
**[code-reviewer]** 实测 `routes/main.py:1500-1502`：`update_app_settings` 第一行就是 `_require_localhost(request)`；`ops.md:26-29` 与 `PROJECT_OVERVIEW.md:47`（红线 7）也都写「仅 127.0.0.1 可写、局域网 403」。
失败场景：agent 以 `:202` 为架构事实 → 给一个**已经有闸**的端点重复加鉴权，或反向推断「API Key 可被局域网改写」而做多余加固/误报安全结论。
修法：两处改为「`POST /api/settings` 与 `/api/settings/test-key` 挂 `_require_localhost`（v4.4.0 起）；`GET /api/settings` 保持可读」。

### P1-4 · 测试与探针基线停在 2026-08/09；前端模块清单三处漂移
**[code-reviewer]** ① `architecture.md:26`「17 个测试文件共 **352**（2026-08-29）」、`ops.md:41`「pytest **719 passed**」、`ops.md:42`「`tools/*.mjs` **10 个**，发布闸要求 10/10」—— 实测 **122** 个测试文件 / `--collect-only` **1986** 条 / 探针 **29** 个（`README.md:23` 与 `CHANGELOG.md:35` 都写 29/29）。失败场景：agent 拿 `ops.md` 当门禁基线 → 只验 10 个探针就宣称「发布闸绿」，漏掉 19 个。
② 前端模块数三处三个数：`README.md:137`「11 模块」/ `architecture.md:19`「10 个模块」（括号里其实列了 11 个名字）/ 实测 `static/js/*.js` = **23**，漏掉 `listen-lab`、`hard-sentences`、`enc-i1`、`search`、`update` 等整块。失败场景：agent 建立前端心智模型时不知道这些文件存在 → 新建第二模块或改错文件（`architecture.md:339-341` 自己记载过「两份逐字相同的错误实现」同族事故）。
修法：数字一律改为「以 `pytest --collect-only -q | tail -1` / `ls static/js | wc -l` 为准」或直接删枚举只留目录指引，**别再手抄**。

---

## 二、P2（9 条）

| # | 发现 | 证据 | 修法 |
|---|---|---|---|
| P2-1 | `CLAUDE.md` 是「缺路由的短桩」——15 行只有 vault 路径 + WORKMEMORY 读序，**无一处提到 `AGENTS.md`**，也无 architecture/ops 入口；而 `AGENTS.md:3` 自称「同 CLAUDE.md 形态」、`GEMINI.md:11` 却明确「读 AGENTS.md」。Claude Code 会话只自动加载 CLAUDE.md ⇒ 全程不知道 architecture/ops 存在 | 两席独立命中（**已合并**） | CLAUDE.md 加一行「文档路由见 `AGENTS.md` 的表格」，**别造第三份** |
| P2-2 | **Inbox 路径两套写法**：`CLAUDE.md:9` 与 `GEMINI.md:17` 写 `d:\Obsidian\Coding\99-Inbox\…`，而 `.cursorrules:7` 与 `.agent-rules.md:7` 写 `…\08-Inbox\…` —— 同一件事四个文件两个地址，必有一错 | 结构席实测 | 统一成一个值，其余改为引用 |
| P2-3 | `docs/plans/archive/` 4 份文件违反命名规则（无 `<日期>-` 前缀，而 `docs/README.md:20` 规定 `plans/<日期>-<主题>.md`）：`workbench-scope-control-and-live-settings.md`、`workbench-progress-server-sync.md`、`workbench-core-words-mode.md`、`plan-companion-mascot.md`。归档判据「只进不出」本身是明示取舍（**不是疏漏**），但命名应一致 | 结构席 | 改名或在该节加豁免说明 |
| P2-4 | `docs/design-system.md`（606 行）被 `docs/README.md:16` 列为**顶层常青规范**，但 `AGENTS.md` 路由表与 `README.md:39-50` 导航都**没有它** ⇒ 全仓零入口；且其 §4 token 表与 CSS 脱节：`--bone`、`--ink-blue`、`--paper-dark`、`--paper-dark-box`、`--rule-dashed`、`--shadow-exhibit`、`--reveal-delay` 七个 token 及 `#F7F1DE`/`#DDD2B6`/`#15140F`/`#2A528A`/`#C8BFA9` 五个色值，在 `static/style.css`、`static/css/tokens.css`、`static/german/` 里**逐个 grep 零命中** | 文档席逐个 grep 实测 | 要么补入口并同步 token 表现在值，要么把状态改成「历史设计稿（v3.0 · 2026-08，未随 tokens.css 同步）」——**不能继续既无人可达、又看起来是现行规范** |
| P2-5 | `README.md:5` Python badge「3.10 丨 3.11」无任何事实支撑：`pyproject.toml:20`/`Dockerfile:1`/CI 6 处全钉 **3.11**，且 `FEATURES.md:295` 已明文点名过 README 的版本数字会漂 | 文档席 | 确认 3.10 是否真支持（无证据）；不支持就改成 3.11 |
| P2-6 | 根目录/包结构描述缺项：`architecture.md:12` 漏 `desktop.py`/`start.bat`/`requirements-desktop.txt`；`:18` 写 `start.py` 86 行（实测 **232**）；`README.md:136` 的 `delector/` 分层漏 `delector/tools/`（正是 `polish_tools.py` 所在、最近两批 PR 主战场）；`README.md:141` 的 `docs/` 说明漏 `adr/` 与 `reviews/`（而 `:50` 自己又指向 `docs/adr/`） | 文档席 | 按 `ls` 实况补三处；行数类数字改为不写或标注量取日 |
| P2-7 | `scratch/` 50MB 纯本地堆积、无修剪约定（CI 输出快照/复现探针/PR 正文草稿/变异夹具/陈旧 `wr_old.py`）；`agent/`（Go agent runtime）与 `AGENTS.md`/`.agent-rules.md`（AI agent 规范）**同一个词三种指涉** | 结构席 | scratch 加「超 N 天/超 X MB 即清」本地约定；`README` 或 `architecture` 用一句话说明 `agent/` 是 Go runtime、与 AI agent 规范无关 |
| P2-8 | `WORKMEMORY/INDEX.md:16` 说 `handoff_*.md`「仅当存在活跃交接时才存在」vs `:39` 把 `handoff_interactive-agent-loop.md` 标 closed 却仍留着 ⇒ 按 `:16` 语义下一个 agent 会以为存在的 handoff 都是活的 | 文档席 | 关闭的 handoff 移入 `WORKMEMORY/archive/`（协议 §4 允许），或补一条清理事件 |
| P2-9 | `README.md:10` Tests 徽章「1768/1770」是 v5.17.0 发版实测，而 master 在 PR #136/#137 后已是 **1984+2**（本地 collect 1986）——徽章被 `README.md:81` 当成**当前**套件规模读，口径未定义 | 文档席 | 定口径（跟发版 or 跟 master）；若跟 master，按 `ops.md:152-153`「测试数变化须同批更新版本面」它已欠 218 条 |

---

## 三、合理、别动的部分（两席共识，值得保留）

1. **README 版本面是全仓最健康的一块**：`:4` badge、`:32-35` 下载表、`:23-25` 摘要全部等于 `APP_VERSION` v5.17.0，与 `static/index.html:40`、`static/sw.js:3`、`CHANGELOG.md:7`、git tag 一致，且有 `tests/test_writer_mobile.py:61`（四处落点钉版本）与 `:127`（v4.9.0「下载表指向 v4.8.3」事故的产物）**机械守护**。
2. **单一真相源纪律执行到位**：`README.md:153-155` 明言「完整版本历史的正主是 CHANGELOG，此处不再复制第二份」；`docs/README.md` 把发版历史钉在根 CHANGELOG 并记录了 2026-10-02 清理 `release-v2.1.md` 的理由。**未发现同一件事两处描述会互相漂移的重复文档**（ADR 件 vs 同名实施计划已比对：是决策件与计划件，不是副本）。
3. **`docs/README.md` 就是「文档该放哪」的单一契约**（分层表 + 放置规则 + 与别处的关系 + 历史合并记录），AGENTS.md 无死链（逐个校验其指向均存在）。
4. **`.gitignore` 分层设防、几乎每条带理由**（`*.db*` 四件套 / 迁移备份 / 签名材料「丢失=包名永久无法升级」/ 本地 agent 工具态），并显式声明 `WORKMEMORY/` 不许忽略。
5. **诚实表述**：`PROJECT_OVERVIEW.md:28-30` 与 `FEATURES.md:283-288` 对未发版功能均用限定表述，没有把未完成写成已完成（§4.3 纪律守住）。
6. **测试隔离基础设施方向正确**：根 `conftest.py` 只做 sys.path + env setdefault（尊重 CI 显式值），重活在 `tests/conftest.py` 与 `tests/db_cleanup.py`（失败必抛、绝不被吞）；唯一漏口就是 P1-1 的 `test_*.db`。

---

## 四、建议顺序

1. **P1-1/P1-2 优先**（两条都会造成**真实数据/工作区事故**，且 P1-2 是文档误导 agent 去踩已知事故）。
2. **P1-3/P1-4 同批**（文档与代码/实测对齐，把"手抄数字"改成"现读口径"）。
3. P2 里 **P2-1/P2-2** 顺手修（入口桩与路径统一，纯收益）；**P2-4**（design-system 无人可达 + token 脱节）建议单独一次定夺；其余登记待办。

**未核（UNVERIFIED）**：vault 侧文件（`01-Rules/*`、ADR-0023 正式件）本机不可达；`docs/design-system.md` 其余 500 行版式/组件章节未逐条比对 CSS；`android/` 与 `agent/` 的内部互相引用；`build/`/`dist/` 实际内容；archive 内各文件最后修改时间（判断是否仍在更新）。
