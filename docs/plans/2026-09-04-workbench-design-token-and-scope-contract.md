# 背词工作台视觉 Token 归一与考纲词表契约实施计划

> **Goal**: 抽离主站 Academic Modern Editorial 共享设计 Token（`static/css/tokens.css`），在维持 iframe 物理沙箱隔离的前提下重塑背词工作台视觉体验（暖纸底色、深碳墨水、自然植物矿物记忆反馈色、衬线排印）；扩展顶栏范围选择器对接 CEFR 考纲词库契约，实现多等级/生词流无缝刷词，全程保持 10 个 Node.js 探针（尤其是 13 条切片护栏）100% 全绿。
> **Tech Stack**: 原生 CSS（Custom Properties 设计 Token）、原生 JavaScript（单文件 SPA + iframe 容器）、FastAPI + SQLite（服务端词库端点）、node:vm 行为探针。
> **Spec Reference**: [`docs/specs/2026-09-04-workbench-design-token-and-scope-contract-design.md`](file:///d:/Code/DeLector/docs/specs/2026-09-04-workbench-design-token-and-scope-contract-design.md)
> **ADR Reference**: `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0005-navigation-exam-domain-and-level-scalability.md` (§4.5 背词工作台形态与词表契约)
> **Global Constraints**:
>
> - **切片护栏红线 (MUST)**：`static/german/workbench.html` 必须严格保护 `tools/wb_queue_probe.mjs` 等探针依赖的代码切片。切片行与其内部实现绝不可随意破坏。改动前后必须运行探针。
> - **iframe 隔离边界 (MUST)**：维持 iframe 独立单文件运行能力，主站与工作台不强行代码合并，只通过共享 CSS Token 与数据端点对齐。
> - **单机离线兜底 (MUST)**：工作台内置 `SEED_WORDS` 保持离线兜底，网络请求失败时静默回退，不阻断离线刷词。
> - **TDD 纪律**：每个任务遵循 Red -> Verify Red -> Green -> Verify Green -> Refactor -> Commit。

---

### Task 0: 建立回归基线与 Ledger 台账 [Role: Guard]

**Files:**

- Create: `docs/plans/2026-09-04-workbench-design-token-and-scope-contract-ledger.md`

**Interfaces:**

- Consumes: master @ HEAD (`62fac6c`), 现有测试套件与探针
- Produces: 任务台账 ledger，基线测试记录（全量 559 pytest + 10/10 tools/\*.mjs）

**Subagent Prompt Scaffold:**

> Implement Task 0: 建立回归基线与 Ledger。
> Goal: 记录基线测试结果（pytest 559 passed + 10/10 tools/\*.mjs 探针全绿），初始化实施台账。
> TDD Steps:
>
> 1. 运行 `pytest -q` 并记录通过数。
> 2. 运行 `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }` 确认探针全部通过。
> 3. 创建 `docs/plans/2026-09-04-workbench-design-token-and-scope-contract-ledger.md`。
>    Return: 基线通过记录与 ledger 路径。

**Step Breakdown:**

- [ ] **Step 1: 运行全量测试套件与探针确认基线**
- [ ] **Step 2: 创建并初始化 ledger 台账**
- [ ] **Step 3: Git 原子提交 `docs(plan): 初始化路线 B 实施计划与 ledger`**

---

### Task 1: 共享设计 Token 层抽取与主站无缝引入 [Role: Design System Builder]

**Files:**

- Create: `static/css/tokens.css`
- Modify: `static/style.css:1-35`
- Create: `test_workbench_tokens.py`

**Interfaces:**

- Consumes: `static/style.css` 现有的 Academic Modern Editorial 变量定义
- Produces: `static/css/tokens.css` 独立 Token 库；`style.css` 顶部 `@import "css/tokens.css";`

**Subagent Prompt Scaffold:**

> Implement Task 1: 共享设计 Token 层抽取。
> Goal: 将主站核心 `:root` 设计变量抽离为独立复用的 `static/css/tokens.css`，供主站与子应用无缝共享。
> Target Files: Create `static/css/tokens.css`, `test_workbench_tokens.py`; Modify `static/style.css`.
> TDD Steps:
>
> 1. 编写测试 `test_workbench_tokens.py`（RED）：断言 `tokens.css` 存在且导出 `--paper`, `--ink`, `--rule`, `--accent`, `--moss`, `--mustard`, `--cherry`, `--sans`, `--serif` 等核心变量；断言 `style.css` 正确引入。
> 2. 运行测试确认失败（RED）。
> 3. 抽取变量创建 `static/css/tokens.css`，并在 `static/style.css` 头部引入（GREEN）。
> 4. 运行 `pytest test_workbench_tokens.py` 与 `pytest test_frontend_security.py` 确认通过。
> 5. Git 原子提交 `feat(style): 抽离 Academic Modern Editorial 共享设计 Token 层`。
>    Return: 测试输出证据与文件路径。

**Step Breakdown:**

- [ ] **Step 1: 编写 Token 存在性与变量映射测试 (RED)**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 提取并创建 `static/css/tokens.css`，在 `style.css` 引入 (GREEN)**
- [ ] **Step 4: 验证测试全绿**
- [ ] **Step 5: Git 原子提交**

---

### Task 2: 背词工作台视觉体系重塑 (暖纸墨水 Editorial 风移植) [Role: Frontend TDD Builder]

**Files:**

- Modify: `static/german/workbench.html:1-85` (head 引入 tokens.css、`:root` 与 `[data-theme="dark"]` 变量映射、按钮与顶栏样式温润化)
- Test: `tools/wb_queue_probe.mjs`, `tools/wb_sync_probe.mjs`, `test_workbench_tokens.py`

**Interfaces:**

- Consumes: `static/css/tokens.css` 导出的设计变量
- Produces: 采用 Editorial 暖纸墨水调色板的 `workbench.html`；13 项切片护栏 100% 保持通过

**Subagent Prompt Scaffold:**

> Implement Task 2: 背词工作台视觉体系重塑。
> Goal: 为 `workbench.html` 引入 `tokens.css`，将其冷灰蓝变量映射至暖纸、深碳墨水、苔藓绿与樱桃红，全面消除视觉跳脱感。
> Target Files: Modify `static/german/workbench.html`.
> Invariants: 严禁触碰或破坏任何由 `tools/wb_queue_probe.mjs` 监控的函数（如 pad2, todayStr, buildReviewQueue 等）。
> TDD Steps:
>
> 1. 在 `test_workbench_tokens.py` 增补断言：断言 `workbench.html` 包含 `tokens.css` 引用且使用 `--paper` / `--ink` 等映射。
> 2. 运行测试确认失败（RED）。
> 3. 修改 `workbench.html` `<style>` 部分，对齐变量映射矩阵（GREEN）。
> 4. 运行 `node tools/wb_queue_probe.mjs` 确保 13 项切片护栏全绿；运行全部 `tools/*.mjs` 探针确保全绿。
> 5. 运行 `pytest test_workbench_tokens.py` 确保通过。
> 6. Git 原子提交 `feat(workbench): 引入共享 Token，重塑背词工作台为 Academic Editorial 暖纸视觉`。
>    Return: 探针验证证据与修改摘要。

**Step Breakdown:**

- [ ] **Step 1: 编写 workbench 引入 token 与变量对齐测试 (RED)**
- [ ] **Step 2: 验证测试失败**
- [ ] **Step 3: 修改 `workbench.html` 样式变量与材质映射 (GREEN)**
- [ ] **Step 4: 运行全部 10 个 Node.js 探针确认切片无破坏**
- [ ] **Step 5: 验证测试全绿**
- [ ] **Step 6: Git 原子提交**

---

### Task 3: CEFR 考纲词库数据契约端点扩展 [Role: Backend TDD Builder]

**Files:**

- Modify: `server.py` (新增 `GET /api/cards/vocab` 过滤端点)
- Modify: `database.py` (新增按 `cefr_level` 与 `core` 筛选词汇的方法)
- Test: `test_server.py` (新增测试 `test_get_vocab_by_cefr_level`)

**Interfaces:**

- Consumes: `delector.db` 中的 `vocab_cards` 表与 `core_dict.py` / `a1_dict.py`
- Produces: `GET /api/cards/vocab?cefr={level}&scope={core|all}` 标准 JSON 契约

**Subagent Prompt Scaffold:**

> Implement Task 3: CEFR 考纲词库数据契约端点。
> Goal: 服务端提供按 CEFR 等级及核心范围查询词汇的端点，供工作台或外部组件拉取分级生词表。
> Target Files: Modify `database.py`, `server.py`; Test `test_server.py`.
> TDD Steps:
>
> 1. 编写测试 `test_get_vocab_by_cefr_level`（RED）：测试 `GET /api/cards/vocab?cefr=A1&scope=core` 返回格式与状态码。
> 2. 运行测试确认失败（RED）。
> 3. 在 `database.py` 中增加查询函数，在 `server.py` 挂载端点（GREEN）。
> 4. 运行 `pytest test_server.py -k test_get_vocab_by_cefr_level` 确认通过。
> 5. 检查是否需要更新 packaging 守卫（端点在已有的 server.py / database.py 中，无需新增文件）。
> 6. Git 原子提交 `feat(api): 增加按 CEFR 等级与核心范围获取词汇的 API 端点`。
>    Return: 测试输出证据。

**Step Breakdown:**

- [ ] **Step 1: 编写词库接口测试 (RED)**
- [ ] **Step 2: 验证接口测试失败**
- [ ] **Step 3: 实现数据库查询与路由端点 (GREEN)**
- [ ] **Step 4: 验证测试通过**
- [ ] **Step 5: Git 原子提交**

---

### Task 4: 工作台范围选择器扩展与考纲词表契约接入 [Role: Fullstack TDD Builder]

**Files:**

- Modify: `static/german/workbench.html:50-120,3400-3600` (顶栏分段控件选项扩展、按需拉取服务端分级词库、降级兜底)
- Test: `tools/wb_queue_probe.mjs`, `tools/wb_sync_probe.mjs`

**Interfaces:**

- Consumes: `/api/cards/vocab` 端点，内置 `SEED_WORDS`
- Produces: 支持 `A1 核心` / `A1 全量` / `精读生词` 多模式刷词，自动重构复习队列

**Subagent Prompt Scaffold:**

> Implement Task 4: 工作台范围选择器扩展与词表契约接入。
> Goal: 顶栏分段器支持切词库范围，优先从服务端拉取对应等级词汇，失败自动降级内置种子词；复习队列自适应过滤。
> Target Files: Modify `static/german/workbench.html`.
> Invariants: 严禁破坏 `tools/wb_queue_probe.mjs` 中的 `refilterReviewQueueForScope` 与队列去重逻辑。
> TDD Steps:
>
> 1. 增补探针断言或测试用例，覆盖新分段模式的队列过滤与离线 fallback（RED）。
> 2. 在 `workbench.html` 实现分段器渲染与词表加载逻辑（GREEN）。
> 3. 运行 `node tools/wb_queue_probe.mjs` 与全部 `tools/*.mjs` 验证探针全绿。
> 4. 运行全量 `pytest` 确认端点与前端契约一致。
> 5. Git 原子提交 `feat(workbench): 顶栏分段器接入 CEFR 考纲词表契约与离线降级`。
>    Return: 探针通过证据。

**Step Breakdown:**

- [ ] **Step 1: 编写多模式范围与回退断言 (RED)**
- [ ] **Step 2: 实现工作台分段扩展与词表拉取/过滤 (GREEN)**
- [ ] **Step 3: 运行 10 个探针断言切片与队列算法正常**
- [ ] **Step 4: 运行测试套件验证通过**
- [ ] **Step 5: Git 原子提交**

---

### Task 5: 全量回归闭环、Ledger 收口与交付报告 [Role: Guard]

**Files:**

- Modify: `docs/plans/2026-09-04-workbench-design-token-and-scope-contract-ledger.md`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`
- Modify: `WORKMEMORY/work.log`

**Interfaces:**

- Consumes: 全部先前任务改动
- Produces: 100% 全绿全量测试报告、更新完毕的 WORKMEMORY 与 Ledger

**Subagent Prompt Scaffold:**

> Implement Task 5: 全量回归与交付收口。
> Goal: 跑全量 pytest（560+）与全量 10 个探针，更新 ledger 与工作记忆，确认无未提交文件，准备交付。
> Steps:
>
> 1. 运行 `pytest -q`，确认全绿。
> 2. 运行 `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`，确认 10/10 全绿。
> 3. 回填 `docs/plans/2026-09-04-workbench-design-token-and-scope-contract-ledger.md`。
> 4. 更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 与 `WORKMEMORY/work.log`。
> 5. Git 原子提交 `docs: 路线 B 实施计划完成与全量测试全绿`。
>    Return: 全量回归证据。

**Step Breakdown:**

- [ ] **Step 1: 运行全量 pytest 与探针套件**
- [ ] **Step 2: 回填 ledger 任务台账**
- [ ] **Step 3: 更新 WORKMEMORY 概览与日志**
- [ ] **Step 4: Git 原子提交**
