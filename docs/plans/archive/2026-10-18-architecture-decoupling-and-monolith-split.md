# DeLector 分层依赖解耦与巨石文件模块化实施计划

> **Goal**: 消除 DeLector 核心子模块的循环与跨层反向依赖，引入自动化分层机械闸，并将后端最大巨石单体 `delector/routes/main.py`（3,201 行）按业务领域完全切分收敛。
> **Tech Stack**: Python 3.11.8 (FastAPI, spaCy, pytest, mypy strict, ruff) / Go 1.24+
> **Spec Reference**: `docs/agents/architecture.md` (Layer 0~5 层序声明) · `01-Rules/LAYERED-ARCHITECTURE.md` · `ADR-0008` (分域路由架构)
> **Global Constraints**: 严禁引入任何新三方库；全量测试用例数严格守恒（或仅允许新增反向依赖门禁单测）；文件编码严格 UTF-8 CRLF（0 lone LF）；保持 FastAPI 路由注册优先级与公开 API 契约 100% 字节兼容。
> **Branch**: `refactor/decoupling-and-monolith-split` — opened from `master` before Task 1, landed via PR.

---

## 决策背景与已决事项 (Decisions So Far)

- **[C5 层序规范确立]**（2026-10-18）：在 `docs/agents/architecture.md` 固化 Layer 0（data）到 Layer 5（routes/server）的单向调用约束，并已拔除 `core/database.py` 对 `nlp_engine/processor.py` 的顶层引用。
- **[Façade 对账网成熟]**（2026-10-16 B4）：`tests/test_core_database_public_surface.py` 建立了双向差集对账机制，确保任何内部切片重构对外部调用方零破坏。
- **[路由注册单一出口]**（ADR-0008）：`delector/routes/__init__.py::register_routes(app)` 是全仓唯一的路由挂载点，`server.py` 不再散落 `include_router`，领域路由切分只需要在 `routes/` 子包内闭环。

---

## 实施阶段任务分解 (Active Frontier)

### Task 1: 消除 `core/db/*.py` 6 子模块对外层门面的反向引用 [Tier: 1-Light] [Mode: AFK] [Role: Refactorer]

**Files:**
- Modify: `delector/core/db/backup.py:35`
- Modify: `delector/core/db/content.py:36`
- Modify: `delector/core/db/records.py:23`
- Modify: `delector/core/db/schema.py:31`
- Modify: `delector/core/db/settings.py:27`
- Modify: `delector/core/db/vocab.py:24`
- Test: `tests/test_core_database_public_surface.py`

**Interfaces:**
- Consumes: `delector.core.db.connection.{db_conn, db_progress_conn, get_db_path, preflight_data_dir, log_study_event}`
- Consumes: `delector.core.db.settings.{get_setting, set_setting}`
- Produces: 6 个子模块内部零 `from delector.core.database import`，彻底解开 `façade ⇄ 子切片` 循环依赖。

**Injected Instincts:**
- [ ] `[Instinct: Import-Precision]`: 逐个子模块核实其从 `database` 导入的符号，改向精确导入至 `delector.core.db.connection` 或对应的同级子模块，不得绕回顶层门面。
- [ ] `[Instinct: Public-Surface-Conservation]`: 保持 `tests/test_core_database_public_surface.py` 全绿，门面对账表数量不得漂移。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 解耦 core/db/*.py 对 core/database.py 的反向引用。
> Mode: AFK | Role: Refactorer
> Goal: 修改 6 个 core/db/*.py 文件，将所有的 `from delector.core.database import ...` 替换为 `from delector.core.db.connection import ...` 或相应的同级子切片模块。
> 验证:
> 1. 运行 `python3 -m pytest tests/test_core_database_public_surface.py` 保持 4 passed；
> 2. 检查 `grep -rn "from delector.core.database import" delector/core/db/` 输出必须为空；
> 3. 运行 `python3 -m ruff check delector/core/db/` 与 `mypy --strict delector/core/db` 0 错误。
> Return: 变更摘要与物理执行输出（grep 零命中 + pytest 全绿）。"

**Step Breakdown:**
- [ ] Step 1: 扫描 6 个文件中的所有 `from delector.core.database import` 引用符号
- [ ] Step 2: 逐文件改向为 `delector.core.db.connection` 或对应同级子模块
- [ ] Step 3: 运行 `test_core_database_public_surface.py` 验证门面对账不变
- [ ] Step 4: Physical Evidence Gate: grep 验证 `delector/core/db/` 内部无反向导入
- [ ] Step 5: Git 原子提交 (refactor: decouple core.db submodules from database facade)

---

### Task 2: 将 `polish_tools.py` 归位至 `tools/` 消除 Layer 3 逆流 [Tier: 1-Light] [Mode: AFK] [Role: Refactorer]

**Files:**
- Create: `delector/tools/polish.py` (搬入 `POLISH_TOOL_ALLOWLIST` 与 `call_tool`)
- Modify: `delector/services/polish_tools.py` (保留纯薄包装或转发，标注弃用期，避免外部导入中断)
- Modify: `delector/routes/main.py:136` (改从 `delector.tools.polish` 导入)
- Test: `tests/test_polish_tools.py`

**Interfaces:**
- Consumes: `delector.tools.{analyze, vocab_stats, writing_check}.run`
- Produces: `delector.tools.polish.POLISH_TOOL_ALLOWLIST`, `delector.tools.polish.call_tool`
- Invariant: Layer 3 (`services/`) 核心源码不再顶层 import Layer 4 (`tools/`)。

**Injected Instincts:**
- [ ] `[Instinct: Clean-Deprecate]`: `services/polish_tools.py` 仅保留从 `delector.tools.polish` 导入并再导出的兼容垫片，附带重构注释。
- [ ] `[Instinct: Mock-Drift-Safe]`: `tests/test_polish_tools.py` 的 mock 目标同步核实，确保 `check_mock_drift.py` 保持 exit 0。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 将 polish_tools.py 归位至 tools/ 消除 Layer 3 逆流。
> Mode: AFK | Role: Refactorer
> Goal: 创建 `delector/tools/polish.py`，承载任务级工具白名单与调度钩子；`services/polish_tools.py` 转为兼容再导出；更新 `routes/main.py` 调用点。
> 验证:
> 1. `python3 -m pytest tests/test_polish_tools.py` 全绿；
> 2. `python3 tools/check_mock_drift.py` exit 0；
> 3. `python3 -m ruff check .` 与 `mypy --strict delector/tools/polish.py` 0 错误。
> Return: 变更摘要与物理执行输出。"

**Step Breakdown:**
- [ ] Step 1: 创建 `delector/tools/polish.py`，迁入白名单定义与 `call_tool` 执行器
- [ ] Step 2: `delector/services/polish_tools.py` 改为再导出垫片，标明架构归位
- [ ] Step 3: 更新 `routes/main.py` 的 import 路径至 `delector.tools.polish`
- [ ] Step 4: 运行 `tests/test_polish_tools.py` 与 `tools/check_mock_drift.py` 验证
- [ ] Step 5: Git 原子提交 (refactor: move polish tools dispatcher to tools layer)

---

### Task 3: 持久层与引擎层单向解耦：解耦 `content.py` 和 `vocab.py` 对 `nlp_engine` 的硬依赖 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/db/content.py:46-51,176-193`
- Modify: `delector/core/db/vocab.py:375-385`
- Test: `tests/test_core_database_public_surface.py`
- Test: `tests/test_server_android_fallback.py`
- Test: `tests/test_a1_workbench_source.py`

**Interfaces:**
- Consumes: `process_german_text`, `_process_german_text_pure_python`, `PROCESSED_JSON_VERSION` (通过依赖注入/调用期传入或惰性加载)
- Produces: `delector.core.db.content` 顶层不再有 `from delector.nlp_engine.processor import ...`；`delector.core.db.vocab` 顶层与局部消除对 `nlp_engine.linguistics` 的反向穿透。

**Injected Instincts:**
- [ ] `[Instinct: Pure-Layer-1]`: 持久层（Layer 1）只负责数据的读写与事务保证，不主动在顶层绑定重量级 NLP 库。`ingest_article` 允许入参传入预处理结果 `processed: Optional[Dict[str, Any]] = None`，若未提供才在函数体内调用/回退，杜绝模块加载期循环。
- [ ] `[Instinct: Android-Cold-Start-Preserved]`: 绝不触碰冷启动回退机制（纯 Python 切词与惰性加载模型契约不得受损）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 解耦 content.py 和 vocab.py 对 nlp_engine 的硬依赖。
> Mode: AFK | Role: TDD Builder
> Goal: 将 `core/db/content.py` 顶层对 `nlp_engine.processor` 的导入改为调用期惰性解析或允许外部注入；将 `core/db/vocab.py` 局部的 `linguistics.lookup_irregular_verb` 依赖收敛。
> 验证:
> 1. 静态 AST 检查 `core/db/` 顶层不再包含 `delector.nlp_engine` 导入；
> 2. `python3 -m pytest tests/test_core_database_public_surface.py tests/test_server_android_fallback.py` 全绿；
> 3. `mypy --strict delector/core/db` 0 错误。
> Return: 变更摘要与物理执行输出。"

**Step Breakdown:**
- [ ] Step 1: 编写检查用例，断言 `core/db/` 模块顶层 AST 中无 `nlp_engine` 引用（RED）
- [ ] Step 2: 重构 `content.py`，将 `process_german_text` 与 `PROCESSED_JSON_VERSION` 改为调用期加载或可选注入
- [ ] Step 3: 重构 `vocab.py`，解耦不规则动词反向穿透
- [ ] Step 4: 运行全部相关单测验证全绿（GREEN）
- [ ] Step 5: 验证 `test_server_android_fallback.py` 确认无模型时的降级路径完好
- [ ] Step 6: Git 原子提交 (refactor: remove top-level nlp_engine imports from core.db)

---

### Task 4: 新增分层依赖与循环引用自动化机械闸 [Tier: 2-Standard] [Mode: AFK] [Role: Gate Author]

**Files:**
- Create: `tools/check_layer_invariants.py`
- Create: `tests/test_check_layer_invariants.py`
- Modify: `.github/workflows/ci.yml` (新增 `layer-invariants` 门禁步骤)

**Interfaces:**
- Consumes: AST 静态解析 `delector/` 树下所有 `.py` 文件
- Produces: 
  - 1. 检测全仓同层/跨层强双向循环依赖（A ⇄ B），命中即 exit 1；
  - 2. 检测严格单向层序（Layer 0~5），低层顶层导入高层即 exit 1；
  - 3. 严格受控豁免机制（同 `check_mock_drift.py`，仅允许显式带理由注释抑制）。

**Injected Instincts:**
- [ ] `[Instinct: Mutation-Tested-Gate]`: 机械闸自身必须经过变异自证测试（在测试中构造反向导入与双向环，断言必须红）。
- [ ] `[Instinct: Display-Encoding-Safe]`: 必须符合 `check_silent_degradation.py` 的编码守卫，退出码与判定不依赖 stdout 编码。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 新增分层依赖与循环引用自动化机械闸。
> Mode: AFK | Role: Gate Author
> Goal: 编写 `tools/check_layer_invariants.py` 及配套单测 `tests/test_check_layer_invariants.py`，挂入 CI。
> 验证:
> 1. 本地执行 `python3 tools/check_layer_invariants.py` 返回 exit 0；
> 2. `python3 -m pytest tests/test_check_layer_invariants.py` 全绿（含变异自证）；
> 3. `tools/check_silent_degradation.py` 检查通过。
> Return: 完整的工具运行收据与变异测试结果。"

**Step Breakdown:**
- [ ] Step 1: 编写 `tests/test_check_layer_invariants.py` 定义循环与逆向导入的拦截用例（RED）
- [ ] Step 2: 实现 `tools/check_layer_invariants.py` 完整 AST 解析与分层判定逻辑（GREEN）
- [ ] Step 3: 对真实 `delector/` 执行扫描，验证当前仓内 0 违规
- [ ] Step 4: 接驳 CI workflow
- [ ] Step 5: Git 原子提交 (feat(tools): add check_layer_invariants mechanical gate)

---

### Task 5: 切出设置与备份域路由 `routes/settings.py` 与 `routes/backup.py` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/routes/settings.py` (迁入 `/api/settings*` 3 个端点)
- Create: `delector/routes/backup.py` (迁入 `/api/backup/*`, `/api/wb/backup/*`, `/api/wb/state*`, `/api/wb/lan-info` 10 个端点)
- Modify: `delector/routes/main.py` (移除对应端点及不再使用的 helper)
- Modify: `delector/routes/__init__.py` (引入并注册新路由)
- Test: `tests/test_server_settings_security.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `_require_localhost`, `get_setting`, `set_setting`, `build_backup_payload`, `_replace_tables`
- Produces: `settings.router`, `backup.router`；挂载至 `app`；`routes/main.py` 缩减 ~600 行。

**Injected Instincts:**
- [ ] `[Instinct: Localhost-Guard-Locked]`: `/api/settings` 与 `/api/backup/restore` 等敏感端点迁移前后，必须严格保留 `_require_localhost` 保护，通过 `test_localhost_guard.py`。
- [ ] `[Instinct: Route-Order-Preserved]`: `register_routes` 中挂载顺序保持：`settings` 与 `backup` 放在 `main.router` 之前挂载。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 切出设置与备份域路由 routes/settings.py 与 routes/backup.py。
> Mode: AFK | Role: TDD Builder
> Goal: 从 `routes/main.py` 抽取 settings 与 backup 域的所有端点，保持断言和依赖逐字搬迁，在 `routes/__init__.py` 注册。
> 验证:
> 1. `python3 -m pytest tests/test_server_settings_security.py tests/test_server.py` 全绿；
> 2. 全量 `--collect-only` 用例数严格守恒；
> 3. `python3 tools/check_layer_invariants.py` exit 0。
> Return: 变更摘要、代码行数缩减对比与 pytest 运行收据。"

**Step Breakdown:**
- [ ] Step 1: 创建 `delector/routes/settings.py`，迁入 3 个 settings 端点
- [ ] Step 2: 创建 `delector/routes/backup.py`，迁入 10 个 backup 与 wb/state 端点
- [ ] Step 3: 更新 `delector/routes/__init__.py` 注册这两个新路由
- [ ] Step 4: 清理 `routes/main.py` 中的对应代码段与无用 import
- [ ] Step 5: 验证 `test_server_settings_security.py` 与 `test_server.py`，核验用例数守恒
- [ ] Step 6: Git 原子提交 (refactor(routes): extract settings and backup domain routers)

---

### Task 6: 切出卡片与词汇域路由 `routes/cards.py` 与音频域 `routes/audio.py` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/routes/cards.py` (迁入 `/api/cards/*`, `/api/quiz/*` 12 个端点)
- Create: `delector/routes/audio.py` (迁入 `/api/audio/*` 4 个端点)
- Modify: `delector/routes/main.py`
- Modify: `delector/routes/__init__.py`
- Test: `tests/test_server_cards_vocab.py`
- Test: `tests/test_cards_endpoint_cost.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `delector.core.db.vocab`, `delector.core.db.records`, `delector.services.tts`
- Produces: `cards.router`, `audio.router`；`routes/main.py` 缩减 ~850 行。

**Injected Instincts:**
- [ ] `[Instinct: FSRS-Light-Preserved]`: `GET /api/cards/counts` 绝不触发逐卡 FSRS 递推的强契约保持（`test_card_counts_does_not_run_fsrs_next_intervals` 必须通过）。
- [ ] `[Instinct: TTS-Backoff-Preserved]`: 音频端点的重试退避与 mini client 降级逻辑必须逐字保持。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6: 切出卡片与词汇域路由 routes/cards.py 与音频域 routes/audio.py。
> Mode: AFK | Role: TDD Builder
> Goal: 从 `routes/main.py` 抽取 cards 与 audio 域的所有端点，挂载至 `routes/__init__.py`。
> 验证:
> 1. `python3 -m pytest tests/test_server_cards_vocab.py tests/test_server.py` 全绿；
> 2. 全量 `--collect-only` 用例数严格守恒；
> 3. `python3 tools/check_mock_drift.py` 与 `tools/check_layer_invariants.py` exit 0。
> Return: 变更摘要与物理执行输出。"

**Step Breakdown:**
- [ ] Step 1: 创建 `delector/routes/cards.py`，迁入全部卡片生词与复习端点
- [ ] Step 2: 创建 `delector/routes/audio.py`，迁入 TTS 与音频缓存端点
- [ ] Step 3: 更新 `delector/routes/__init__.py` 进行路由注册
- [ ] Step 4: 从 `routes/main.py` 中切除对应代码块
- [ ] Step 5: 运行定向单测并验证全量用例数守恒
- [ ] Step 6: Git 原子提交 (refactor(routes): extract cards and audio domain routers)

---

### Task 7: 切出文章与阅读域路由 `routes/articles.py` 与写作域 `routes/writing.py` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/routes/articles.py` (迁入 `/api/articles/*`, `/api/feed/*` 11 个端点)
- Create: `delector/routes/writing.py` (迁入 `/api/writing/*`, `/api/essays/*` 12 个端点)
- Modify: `delector/routes/main.py` (收敛为 ~300 行残余通用路由：syntax/prep/health)
- Modify: `delector/routes/__init__.py`
- Test: `tests/test_server_ai_polish.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `ingest_article`, `fetch_remote_html`, `run_polish_loop`, `analyze_a1_email`, `db_conn`
- Produces: `articles.router`, `writing.router`；`routes/main.py` 从 3,200+ 行骤降至 300+ 行。

**Injected Instincts:**
- [ ] `[Instinct: Frozen-Surface]`: 润色循环流式契约（SSE 逐帧、取消、`converged` 字段）断言逐字不变。
- [ ] `[Instinct: SSRF-Gate-Pinned]`: `ingest_from_url` 必须在发请求前调用 `is_safe_public_url`，保持 F1 根治成果。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 7: 切出文章与写作域路由 routes/articles.py 与 routes/writing.py。
> Mode: AFK | Role: TDD Builder
> Goal: 抽取 articles 和 writing 域端点至独立路由模块，使 `routes/main.py` 彻底收敛为极简通用残余层。
> 验证:
> 1. `python3 -m pytest tests/test_server_ai_polish.py tests/test_server.py` 全绿；
> 2. `python3 -m pytest tests/ --collect-only -q | tail -1` 严格守恒；
> 3. `ruff check .` 与 `mypy --strict delector/routes` 0 错误。
> Return: 变更摘要、`main.py` 最终行数与执行收据。"

**Step Breakdown:**
- [ ] Step 1: 创建 `delector/routes/articles.py`，迁入文章 CRUD、URL 抓取、Feed 订阅端点
- [ ] Step 2: 创建 `delector/routes/writing.py`，迁入写作批改、AI 润色、作文版本链端点
- [ ] Step 3: 更新 `delector/routes/__init__.py` 注册路由
- [ ] Step 4: 清理 `routes/main.py`，仅保留语法分析与通用健康检测残余
- [ ] Step 5: 全量运行路由相关测试，比对收集总数
- [ ] Step 6: Git 原子提交 (refactor(routes): extract articles and writing domain routers)

---

### Task 8: 全量门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log`
- Modify: `docs/reviews/2026-10-16-open-items-backlog.md`
- Test: Full CI Command Matrix

**Interfaces:**
- Consumes: Task 1~7 的全部产物
- Produces: 交付 PR，全仓 0 双向依赖环，0 逆向跨层导入，`routes/main.py` 彻底解体。

**Step Breakdown:**
- [ ] Step 1: 运行全套门禁矩阵：
  - `python3 tools/check_layer_invariants.py` (exit 0)
  - `python3 tools/check_mock_drift.py` (exit 0)
  - `python3 tools/check_silent_degradation.py` (exit 0)
  - `python3 -m ruff check .` (All checks passed)
  - `python3 -m mypy --strict delector tools` (0 errors)
  - `python3 -m mypy --follow-imports=skip tests` (0 errors)
  - `cd agent && go test ./... -count=1 && gofmt -l .` (All passed)
- [ ] Step 2: 全量 pytest 回归：`python3 -m pytest tests/ -q`，确认通过用例数 ≥ 基线 (2,360)
- [ ] Step 3: CRLF 卫生核验（所有触碰文件 0 lone LF）
- [ ] Step 4: 追加 `WORKMEMORY/work.log` DONE 事件
- [ ] Step 5: 推送分支并开启 GitHub PR (base=master)

---

## 迷雾区与后续规划 (Fog of War)

- [x] **Task 1~8: 架构解耦与 routes/main.py 巨石拆分**（2026-10-18 已完成，PR 待合并）
- [ ] **[Unknown 1: 前端大单体 `static/index.html` (3,158 行) 的解耦路径]**：
  - 前端目前是单页无构建体系架构，直接切分组件易引发 DOM 节点挂载时序问题。
  - **解耦前提**：必须严格遵循 C7 的成功模式——**“探针先行，分段比对”**。在给主界面关键交互（Tab 切换、文章渲染、生词高亮）建立无头 node 探针前，严禁盲目切开 HTML 文件。
- **[Unknown 2: 前端业务脚本（`writer.js`, `encounter.js`, `reader.js`）的模块化]**：
  - 目前这些脚本各在 1,300~1,600 行之间。切成 ES Module 需依赖 Android Chaquopy/WebView 环境的真机兼容性验证（C4 门槛）。在真机验证前，保持单文件纯声明脚本是最稳健的做法。

---

## 明确不纳入范围 (Out of Scope)

- 不重写或改动前端 API 通信协议（URL 路径、入参 Request 结构、出参 JSON 格式 100% 字节等价）。
- 不触碰 `delector/data/` 目录下的超大考纲字典与种子文件（如 `official_vocab.py`, `core_dict_ext.py`，这些是纯静态数据表，不是逻辑臃肿）。
- 不引入任何外部架构编排框架或三方依赖。
