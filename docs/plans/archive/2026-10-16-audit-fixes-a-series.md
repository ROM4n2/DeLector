# A 系列未决项实施计划（审计修正批次 2）

> **Goal**: 把 `docs/reviews/2026-10-16-open-items-backlog.md` 的 **A 档 8 项**全部落地：两个 P0（还原丢表 / 退出挂死）、一个 P1（凭据外泄）、一组裁判误报修复、测试库落点病因、三处文档漂移、以及收尾簿记。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite(WAL) / pytest（无 pytest-asyncio）/ 原生 JS（无构建链路）/ PyInstaller 打包面
> **Spec Reference**: `docs/reviews/2026-10-15-swarm-audit-master.md`（P0-1/P0-2/P1-1）· `docs/reviews/2026-10-16-repo-structure-and-docs-audit.md`（P1-1~P1-4）· ADR-0024（A4 的硬依赖地位）· `docs/plans/2026-10-15-a1-judge-expansion.md`（裁判集接线缝）
> **Global Constraints**:
> - **Tier 3 三项开工前 MUST 过 HITL 授权门**（dfs-exec Gear 3）：影响面、不可逆风险、回退方式先交用户确认。
> - **只增不改的边界**：A1/A2/A3 都是**修缺陷**，不是加功能；凡改动既有契约处（`tests/test_server.py:1031`）MUST 同批改并写明理由。
> - **零新依赖**；行尾 **CRLF**（`git add` 前 `python` bytes 判别，别猜）；`ruff check .` 零告警；`mypy --strict delector`；测试文件 `--follow-imports=skip`。
> - **反挂死纪律**：任何 sleep 必须有 `wait_for`/固定次数兜底；禁 `join` 线程无超时；单用例最坏 <5s。
> - **密钥纪律**：任何输出/日志/提交/报告 MUST NOT 含 key 本体，只允许布尔或长度。
> - 每个 Task 完成后跑**关联套件**再跑全量；全量基线 **2135 passed + 2 skipped**（master `dac3a8b`）。
> **Branch**: `fix/audit-a-series`（从 master 开；实现类任务全部经 PR 落地，**不直推 master**）

---

### Task 1: P0-1 —— `/api/backup/restore` 静默清空 `listen_trials` 与 `hard_sentence_trials` [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:** Modify `delector/core/database.py`（`_replace_tables` 前向兼容闸）· Modify `delector/routes/main.py`（`RestoreReq` 补两字段）· Test `tests/test_ci_hardening.py` 或 `tests/test_server.py`（契约守卫，择一）

**Interfaces:**
- Consumes: `_BACKUP_TABLES`（`database.py:1573` 含 `listen_trials`、`:1598` 含 `hard_sentence_trials`，共 10 表）· `RestoreReq`（`routes/main.py:1747-1768`，现仅 8 个主库表字段）· `_replace_tables`（`database.py:1895-1909`，`:1901` 无条件 `DELETE FROM`）
- Produces: `RestoreReq.listen_trials: list[dict] = []` 与 `.hard_sentence_trials: list[dict] = []`；`_replace_tables` 改为「`name not in payload ⇒ continue`」（**原样保留而非清空**）；契约测试断言 `set(_BACKUP_TABLES) - set(RestoreReq.model_fields) == set()`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修一个**已复现的数据丢失缺陷**：还原备份会静默清空 `listen_trials` 与 `hard_sentence_trials`（`_BACKUP_TABLES` 10 表 vs `RestoreReq` 8 字段 + pydantic v2 `extra=ignore` + `_replace_tables` 无条件 DELETE ⇒ 删光零回灌，接口仍返回 ok）。三处都要改：① `RestoreReq` 补两字段；② `_replace_tables` 加前向兼容闸 `if name not in payload: continue`（让"新增备份表忘加字段"退化成"原样保留"而不是"清空"）；③ 契约测试断言清单与字段集一致。**RED 先行**：先写"payload 缺键 ⇒ 表不被清空"的用例并跑红。变异自证：把闸删掉 ⇒ 用例红；把两字段删掉 ⇒ 契约测试红。"

**Step Breakdown:**
- [ ] Step 1: RED（缺键不清空 + 清单↔字段一致性两条用例）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 三处实现（GREEN）
- [ ] Step 4: 变异自证 2 组
- [ ] Step 5: 关联套件 + ruff + mypy + CRLF + 原子提交

---

### Task 2: P0-2 —— 退出路径挂死 + 假成功日志 [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:** Modify `delector/core/server_lifecycle.py`（`timeout_graceful_shutdown`）· Modify `start.py`（尊重 `shutdown()` 返回值 + `join()` 超时）· Test `tests/test_desktop_shell.py`（退出路径用例）

**Interfaces:**
- Consumes: `build_server`（`server_lifecycle.py:50`，未设 `timeout_graceful_shutdown`）· `shutdown(server, thread, grace_s=5.0)`（`:65-76`，`should_exit=True` + `thread.join(5.0)`，有界且如实返回 False）· `start.py:180` `thread.join()` 无超时 · `start.py:186-187` 丢弃返回值并无条件 `print("[提示] 服务已停止。")` · `start.py:232` 裸调 `main()` 无 `SystemExit` · `server_lifecycle.py:60` uvicorn 线程 `daemon=False`
- Produces: `uvicorn.Config(..., timeout_graceful_shutdown=5)`；`start.py` 改为 `if not shutdown(...): print(..., file=sys.stderr); sys.exit(1)`；`thread.join()` 带超时；退出码语义用例（干净退出 0 / 未干净退出 1）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修退出路径：真因**不是** `Server.shutdown()` 无限等（本仓没调它），而是 `start.py:180` 的 `thread.join()` 无超时 + 非 daemon uvicorn 线程 + `start.py:186` 丢弃 `shutdown()` 返回值 + 无条件打印「服务已停止」+ `start.py:232` 裸调 `main()` 无 `SystemExit` ⇒ 进程挂住、8000 仍占、下次启动连到旧实例。修四处并加退出码用例（干净 0 / 不干净 1，人话进 stderr）。⚠️ 不要照'uvicorn wait_for(None)'的旧说法改。"

**Step Breakdown:**
- [ ] Step 1: RED（退出码与"假成功"两条用例）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证（把 `sys.exit(1)` 删掉 ⇒ 用例红；把 join 超时删掉 ⇒ 挂死探针红）
- [ ] Step 5: 关联套件 + ruff + mypy + CRLF + 原子提交

---

### Task 3: P1-1 —— 备份 JSON 带走 `wb.pair.v1`（长期 `wb_sync_key`） [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:** Modify `static/js/cards.js`（导出/还原双侧过滤）· Modify `delector/routes/main.py:1636`（后端键名黑名单）· Modify `tests/test_server.py:1031`（**必须同批改**）· Test 契约守卫

**Interfaces:**
- Consumes: `database.py:806`（`wb_sync_key = secrets.token_hex(16)`，不轮换）· `static/js/encounter.js:1295`（`wb.pair.v1 = {host, key}`）· `static/js/cards.js:1005-1020`（`wb.` 前缀全扫、无 exclude；`BACKUP_LS_TRANSIENT` 只管 `delector_` 前缀）· `main.py:1636`（`payload["local_storage"] = req.local_storage or {}` 原样透传）· `database.py:1444`（`BACKUP_SETTINGS_WHITELIST` 明确排除 `wb_sync_key`）
- Produces: 前端 `BACKUP_LS_EXCLUDE = {"wb.pair.v1"}`（**导出与还原两侧都过滤**）；后端 `_BACKUP_LS_DENYLIST` 按键名过滤（**权威闸**，前端可被绕过）；契约守卫：带 `wb.pair.v1` 打 `/api/backup/prepare` ⇒ 下载体不含该键且 `delector_voice` 仍在

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修凭据外泄：`cards.js` 备份把全部 `wb.*` localStorage 写进 DeLector JSON 备份，而配对对象里带长期 `wb_sync_key` 与内网 host（后端白名单明确排除它 ⇒ localStorage 侧门绕过后端）。纵深两道：① 前端 `backupLocalStorageKeys()` 加 `BACKUP_LS_EXCLUDE`，**导出与还原两侧都过滤**（还原侧 `cards.js:1075-1076` 现在还会写回本机）；② 后端 `main.py:1636` 按键名黑名单过滤（权威闸必须在后端）。**必须同步改 `tests/test_server.py:1031`** —— 它把「原样透传」钉成了契约，不改则新守卫与旧契约对撞，提交信息里写明"改的是哪条断言、为什么这是强化"。契约守卫：带 `wb.pair.v1` ⇒ 下载体不含该键且 `delector_voice` 仍在。"

**Step Breakdown:**
- [ ] Step 1: RED（后端过滤 + 双侧过滤 + 契约守卫三条用例）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证（把后端黑名单删掉 ⇒ 契约守卫红；只改导出不改还原 ⇒ 还原侧用例红）
- [ ] Step 5: 关联套件 + ruff + mypy + 契约闸 + CRLF + 原子提交

---

### Task 4: 裁判 FP 三类修复 + 回归标定 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Modify `delector/services/writing.py`（三处判据收窄）· Test `tests/test_writing_rules.py`（边界用例）

**Interfaces:**
- Consumes: 已实证的三类误报（A 系列登记表 A4）：① 严格 Acc 动词遇自由第三格（`Ich öffne meinem Bruder die Tür.`）② V2 把主语 NP 内修饰当独立前置成分（`Meine sehr große Familie wohnt in Berlin.`）③ V2 漏豁免焦点小词（`Auch meine Familie…`）+ rektion 把自由第三格当违规（`Ich lese meinem Bruder das Buch.`）
- Produces: ① `detect_verb_case_government` 只检查被支配格位（Acc 动词只看 `oa` 宾语）② `_is_inside_subject_np` 的 ADJ 条件/焦点小词封闭词表（时间副词 MUST NOT 入表）③ 每类 ≥2 条边界用例 + 官方 10 篇 + `COMMON_CORRECT_SENTENCES`（51 句）硬门仍绿 + `tools/bench_judge_fp.py` 复跑零误报

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修三类已实证误报（每条都有实跑证据，见登记表 A4）。判据收窄而非删规则：① rektion 对 Acc 动词只检查 `oa` 宾语（自由第三格合法句不报）② V2 的 NP 内部豁免补焦点小词封闭词表（`auch/nur/sogar/…`；时间副词 MUST NOT 入表，否则负样本漏报）③ 相应 FP 守卫各 ≥2 用例。硬门：官方 10 篇 + `COMMON_CORRECT_SENTENCES`（51 句）+ `bench_judge_fp.py` 复跑 MUST 全绿。RED 先行；变异自证：抽掉任一守卫 ⇒ 对应用例红。"

**Step Breakdown:**
- [ ] Step 1: RED（三类误报句 + 对应负样本）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证 3 组 + `bench_judge_fp.py` 复跑
- [ ] Step 5: 关联套件 + ruff + mypy + CRLF + 原子提交

---

### Task 5: 测试库落点改绝对路径（治因） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Modify `conftest.py:30-31` · Modify `tests/test_get_endpoints_with_writes.py:37-38` · Modify `tests/db_cleanup.py:72`（`ROOT_DB_NAMES` 扩为含 `test_*.db`）· Test `tests/conftest.py` 守卫用例

**Interfaces:**
- Consumes: 根 `conftest.py` 只做 sys.path + env setdefault（尊重 CI 显式值）· `tests/conftest.py:38-56` 会话守卫（只比 `delector.db`/`progress.db`）· `tests/db_cleanup.py`（单一实现，失败必抛）
- Produces: 测试库路径基于 `tmp_path_factory`/显式临时目录（**绝对路径**）；`ROOT_DB_NAMES` 含 `test_*.db`；用例断言「跑完测试后仓库根不新增任何 `*.db`」

**Subagent Prompt Scaffold (for /dfs-exec):**
> "治因：`conftest.py:30-31` 与 `test_get_endpoints_with_writes.py:37-38` 用裸相对文件名 ⇒ 解析到 CWD ⇒ 本地 pytest 从仓库根跑就落在仓库根；而 `db_cleanup.ROOT_DB_NAMES` 只比 `delector.db`/`progress.db` ⇒ `test_*.db` 在守卫视野外（`*.db` 被 ignore ⇒ 可无限期无人发现）。改成 `tmp_path_factory`/显式临时目录的**绝对路径**，并把 `ROOT_DB_NAMES` 扩成含 `test_*.db`。⚠️ 根 `conftest.py` 的 env setdefault MUST 继续尊重 CI 显式值（`setdefault` 语义别改）。"

**Step Breakdown:**
- [ ] Step 1: RED（跑测试后根目录无新增 `*.db` 的守卫）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证（改回相对路径 ⇒ 守卫红）
- [ ] Step 5: 关联套件 + ruff + mypy + CRLF + 原子提交

---

### Batch 1: 文档漂移对齐 + 收尾簿记 [Tier: 1-Light] [Mode: AFK] [Role: Orchestrator 直执行]

**Files:** Modify `docs/agents/ops.md:53-57`（数据目录口径）· Modify `docs/agents/architecture.md:202/:93-94`（`/api/settings` 鉴权表述）+ `:26`（门禁基线改现读口径）· Modify `WORKMEMORY/INDEX.md`（closed handoff 移 archive）· 根目录 `test_*.db` 残留改名 `.bak-<ts>`（与 10-16 既有做法一致，可恢复）

**Interfaces:**
- Consumes: 实测口径（`resolve_data_dir({})` = `%LOCALAPPDATA%\DeLector`；`routes/main.py:1500-1502` 第一行 `_require_localhost`；测试 122 文件 / 2135 条 / 探针 29 / `static/js` 23 个）
- Produces: 三处文档与代码/实测一致；`INDEX.md` 与其 `:16` 语义自洽；根目录无 `test_*.db`

**Step Breakdown:**
- [ ] Step 1: 逐处改写（**每个数字都来自本次实测**，禁手抄）
- [ ] Step 2: 物理取证（`grep` 断言新口径在位、旧口径为零；`ls` 断言根目录无 `test_*.db`）
- [ ] Step 3: 批量提交（Tier 1 允许 batch commit）

---

## 🚫 Out of Scope

- **A7**（vault 两张 `99-Inbox` 草稿过 consolidate）—— 属 `/dfs-inbox-consolidate` 工作流，不在本计划。
- **B/C 档全部**（见登记表）：分支纪律机械闸、`.gitattributes`、design-system 定夺、`database.py` 切分、harness 工程前置、回灌子计划、Android 真机、Pi 重构、测试文件切分、`workbench.html` 拆分。
- 不顺手改 `tools/bench_judge_fp.py`（Task 6 冻结的标定记录）。
