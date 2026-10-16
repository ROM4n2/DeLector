# `core/database.py` 按职责切分（B4）

> **Goal**: 把 `delector/core/database.py`（**2809 行 / 86 个顶层 def / 9 组职责 / 32 处被 import**）按职责切成包，**公开面零变化**（32 个 import 点一行不改），并让"导出集对账"成为机械闸。
> **Tech Stack**: Python 3.11 / SQLite(WAL) / pytest（无 pytest-asyncio）/ `delector/core` 现有导入图
> **Spec Reference**: `docs/reviews/2026-10-15-refactor-candidates.md`（候选 #1：切分轴与"先补契约测试"的要求）· `docs/reviews/2026-10-15-swarm-audit-master.md`（P0-1/P1-2，备份面刚被 A1 动过）· `docs/plans/2026-10-16-audit-fixes-a-series.md`（A1 落地的清单↔字段集契约测试）
> **Global Constraints**:
> - **公开面冻结（MUST）**：`delector/core/database.py` 切分后 MUST 仍导出**切分前**的全部公开名（函数/常量/类），且 `import delector.core.database as database` 的既有调用语法（`database.get_setting(...)`）逐字可用 ⇒ 32 个 import 点**零改动**。
> - **导出集对账是机械闸（MUST）**：先固化"切分前公开名清单"（从源码 AST 现读，不手抄），切分后 MUST 断言 `set(切分前) ⊆ set(façade 导出)`；**任何一处遗漏 ⇒ 测试红**。
> - **模块级全局状态 MUST 随其函数同迁**，或显式改为共享持有者；**禁止**把持有全局缓存的函数留在 A 模块却让 B 模块读同一缓存的两份副本（本仓 `database.py` 有词库缓存 / 两份 pending backup 槽 / `_nlp_*` 相邻耦合）。
> - **切片 MUST 一次只动一组职责**（每切片一个原子提交 + 跑定向测试）；**MUST NOT** 顺手改行为（纯搬运 + 显式 re-export）。
> - 反向依赖登记：`delector/core/database.py:23 ⇄ delector/nlp_engine/processor.py:16` 的**已知双向耦合**在本计划**不解决**（只登记），避免把重构与解耦混在一起。
> - 零新依赖 / CRLF / `ruff check .` 零告警 / `mypy --strict delector` / 中文注释 / **本地只跑定向文件，全量交 CI**。
> **Branch**: `refactor/database-split`（从 `fix/audit-a-series` 开 —— 依赖 #143 里的 A1 契约测试；**PR 应在 #143 之后合并**）

---

### Task 1: 契约测试先行（切分的安全网） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Create `tests/test_core_database_public_surface.py` · Create `tools/dump_module_public_names.py`（可选：把 AST 提取器独立成可复用工具）

**Interfaces:**
- Consumes: `delector/core/database.py` 的模块对象与源码（AST）
- Produces: ① `python tools/dump_module_public_names.py delector/core/database.py` 输出公开名清单（JSON）；② 固化基线清单到测试（**从当前源码现读生成**，并在测试里断言 facade 是**超集**）；③ 关键不变量往返测试（备份→还原、设置读写、训练记录读写、词库契约）——若既有测试已覆盖则不重复造，改为**点名引用**既有用例名

**Subagent Prompt Scaffold (for /dfs-exec):**
> "给即将切分的 `delector/core/database.py` 造安全网。① 写 `tools/dump_module_public_names.py`（AST 扫顶层 `def`/`Assign`/`ClassDef`，排除 `_` 前缀与 `if __name__`，输出 JSON）；② 用它对**当前**文件生成基线清单并**固化进测试**（`tests/test_core_database_public_surface.py`），测试断言「facade 导出集 ⊇ 基线集」——切分时任何漏搬都会红；③ 复核关键不变量是否已有既有用例覆盖（备份往返、设置读写、训练记录、词库契约），**有就点名引用，没有才补**（禁止为凑覆盖造重复测试）。RED 先行：先写清单断言（此时 facade 就是原文件 ⇒ 应绿），再用『临时从清单删一个名字』证明它非真空。"

**Step Breakdown:**
- [ ] Step 1: 写 AST 工具 + 生成基线清单（贴清单大小与抽样）
- [ ] Step 2: 固化断言（应绿）+ **非真空自证**（临时删一个名字 ⇒ 红；还原 ⇒ 绿）
- [ ] Step 3: 复核既有不变量覆盖，列出「已覆盖（点名）/ 缺（补）」两清单
- [ ] Step 4: 定向套件 + ruff + mypy + CRLF + 原子提交

---

### Task 2: 切 `db/backup.py`（备份/还原/白名单） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Create `delector/core/db/__init__.py` · Create `delector/core/db/backup.py` · Modify `delector/core/database.py`（改为显式 re-export）· Test 沿用既有备份测试

**Interfaces:**
- Consumes: `_BACKUP_TABLES` / `_PROGRESS_TABLES` / `BACKUP_SETTINGS_WHITELIST` / `build_backup_payload` / `_replace_tables` / `restore_*` / 两份 pending backup 槽（`_pending_backup*`）
- Produces: 同签名函数与常量迁入 `delector/core/db/backup.py`；`database.py` 显式 `from .db.backup import ...`（**不吞名字、不用 `*`**）；**pending 槽等模块级状态随迁**并在 `backup.py` 内保持单份

**Step Breakdown:**
- [ ] Step 1: 搬运（纯移动 + 显式 re-export；git diff 应表现为"移动"而非"改写"）
- [ ] Step 2: 定向测试（`tests/test_ci_hardening.py -k "backup or restore"`、`tests/test_server.py -k "backup or restore"`）
- [ ] Step 3: 公开面断言（Task 1 的安全网）MUST 绿
- [ ] Step 4: 变异自证（临时把某 re-export 删掉 ⇒ 公开面断言红；还原）
- [ ] Step 5: ruff + mypy + CRLF + 原子提交

---

### Task 3: 切 `db/settings.py` + `db/schema.py` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Interfaces:**
- Consumes: 设置持久化与鉴权（`get_setting`/`set_setting`/`get_effective_api_key`/`wb_auth` 相关）· 建表 + 索引 + 内联 `ALTER TABLE` 迁移（`:317-579`、`:2004-2051`）
- Produces: 两模块 + `database.py` 显式 re-export；**迁移函数与建表函数必须同模块**（它们共享表结构常量）

**Step Breakdown:**
- [ ] Step 1~5: 同 Task 2 的形态（搬 → 定向测试 → 公开面断言 → 变异 → 门禁）

---

### Task 4: 切 `db/records.py` + `db/content.py` + `db/vocab.py` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Interfaces:**
- Consumes: 考试/训练记录（含 A1 成绩迁移 `:2004-2051`）· 文章与 encounter 种子（`:846-1209`）· Anki 与音频缓存（`:1212-1432`）· 词汇契约与富字段（`lookup_core_vocab` 等）
- Produces: 三模块 + `database.py` 显式 re-export；**词库缓存随 `vocab.py` 同迁**（严禁两份缓存）

**Step Breakdown:**
- [ ] Step 1~5: 同上；额外确认 `nlp_engine/processor.py` 的**反向 import 未被打断**（登记的双向耦合不许在本计划里解耦，但 MUST NOT 打断）

---

### Task 5: façade 收口与对账 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Modify `delector/core/database.py` · Test `tests/test_core_database_public_surface.py`

**Interfaces:**
- Produces: `database.py` 成为**纯 façade**（零实现、只剩 re-export + 模块 docstring 说明切片去向）；公开面断言从"⊇ 基线"升级为**逐名对账**（差集为空并打印）；`delector/core/db/__init__.py` 导出各切片

**Step Breakdown:**
- [ ] Step 1: façade 收口（删掉搬空的实现，只留 re-export）
- [ ] Step 2: 差集断言（基线 − façade ⇒ 必须为空）+ 打印对账表
- [ ] Step 3: 定向全套（core 相关测试）+ ruff + mypy + CRLF + 原子提交
- [ ] Step 4: **HITL**：把"公开面零变化 + 32 import 点零改动 + 全量交 CI"的证据交用户，决定 PR 何时合

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A] `database.py` 里是否存在"跨职责共享的模块级可变状态"**：已知候选 = 词库缓存、两份 pending backup 槽、`_nlp_*` 相邻耦合。**由 Task 2 的 Step 1 毕业**（搬运时若发现某全局被两组职责共读 ⇒ 停下来报告，而不是硬拆）。
- **[Unknown B] 是否有调用方依赖"模块级副作用"**（例如 `import database` 即建表/建目录）：**由 Task 1 的清单 + Task 3 的定向测试毕业**。
- **[Unknown C] 切分后 `mypy --strict` 是否会暴露既有的隐式 `Any`**（跨模块搬运常让推断变严）：**由 Task 2 毕业**；若暴露 ⇒ 只做最小注解，不改逻辑。

## 🚫 Out of Scope

- **不解决** `core ⇄ nlp_engine` 的双向耦合（只登记）。
- **不改行为**：纯搬运 + re-export；任何"顺手优化"一律另立计划。
- **不重命名**任何公开名（先冻结，命名整理是下一轮的事）。
- C 档全部（详见未决项登记表）。
