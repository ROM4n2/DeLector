# static/index.html 前端大单体切分与模态组件化实施计划

> **Goal**: 遵循 C7「探针先行 + 无损分段」模式，将 3,158 行的 `static/index.html` 前端大单体安全切分为结构化分块模板（`static/views/*.html` 与 `static/modals/*.html`），建设基于标准库的无损构建器与 CI 门禁，实现全仓 2,367 个测试与 26 个 DOM 探针 100% 绿灯守恒。
> **Tech Stack**: 原生 HTML5 / CSS3, 原生 ES Modules, Python 3.11+ 标准库, Node.js MJS 探针
> **Spec Reference**: [[99-Inbox/2026-10-18-契约探针驱动的单文件拆分：先现代化探针、再动产物]] · ADR-0005 · ADR-0006
> **Global Constraints**: 0 运行时新依赖，UTF-8 CRLF 卫生，严格双向所有权钉子，禁止异步运行时 HTML 拼接，CI 零破坏。
> **Branch**: `refactor/index-html-split` — 从 `master` 切出，全套门禁通过后单 PR 合入。

---

## Decisions So Far

- **拒绝运行时网络 fetch 异步拼装**：避免 Android WebView 与桌面 WebView2 首屏白屏闪烁、DOM 监听器挂载时序竞态；
- **确定性分段编译方案**：构建期采用纯 Python 标准库拼接机制，`tools/build_index_html.py` 合成 `static/index.html`，保留 `static/index.html` 物理文件的存在以完全向后兼容现存 26 个测试套件；
- **双向同步守护闸**：设立 `tools/check_index_html_sync.py` 并在 CI 与 `pre-commit` 中强制校验分块拼装结果与 `static/index.html` 字节严格一致。

---

## Active Frontier (Unblocked Tasks)

### Task 1: 建设 index.html DOM 结构与视图切片基线探针 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/index_dom_probe.mjs`
- Create: `tests/test_index_dom_probe.py`

**Interfaces:**
- Consumes: `static/index.html`
- Produces: `tools/index_dom_probe.mjs` (CLI: `--json` 输出结构完整性, exit 0 / 1)

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 建设 index.html DOM 结构与视图切片基线探针。
> 编写 Node.js 探针 `tools/index_dom_probe.mjs`，利用纯原生字符串与正则分析 `static/index.html`，
> 覆盖 9 大 `<main>` 视图、2 大 `<aside>` 抽屉、6 大 Modal 浮层、顶部 `<header>`、导航 `<nav>`、底部 `<nav id=\"mobile-bottom-nav\">` 的开闭闭合边界。
> 编写 Python 测试 `tests/test_index_dom_probe.py` 包装该探针，并提供变异测试证明破坏 DOM 标签必红。
> Return: 探针运行收据与通过的测试日志。"

**Step Breakdown:**
- [ ] Step 1: 编写 `tests/test_index_dom_probe.py`（RED）
- [ ] Step 2: 实现 `tools/index_dom_probe.mjs`，校验全量 17 个关键顶层 DOM 块（GREEN）
- [ ] Step 3: 运行 `python3 -m pytest tests/test_index_dom_probe.py` 确认通过
- [ ] Step 4: 注入标签缺失变异，证明探针能精准拦截（变异自证）
- [ ] Step 5: Git 原子提交

---

### Task 2: 实现无损模板拼接构建器与同步一致性机械闸 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/build_index_html.py`
- Create: `tools/check_index_html_sync.py`
- Create: `tests/test_check_index_html_sync.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `static/views/*.html`, `static/modals/*.html`, `static/layout/*.html`
- Produces: `tools/build_index_html.py --check` / `tools/check_index_html_sync.py` (exit 0: 完全同步, exit 1: 漂移)

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 实现无损模板拼接构建器与一致性门禁。
> 遵循纯 Python 标准库编写 `tools/build_index_html.py`，支持从骨架文件 `static/index.skeleton.html`
> 按占位符 `<!-- @include: path -->` 自动装配各组件。
> 实现校验脚本 `tools/check_index_html_sync.py`，校验失败时给出明确行差并退出码 1。
> 在 `tests/test_check_index_html_sync.py` 中增加单元测试与变异测试。
> 在 `.github/workflows/ci.yml` 接入该检查门禁。"

**Step Breakdown:**
- [ ] Step 1: 编写测试 `tests/test_check_index_html_sync.py`（RED）
- [ ] Step 2: 实现 `tools/build_index_html.py` 与 `tools/check_index_html_sync.py`（GREEN）
- [ ] Step 3: 运行测试并执行变异探测
- [ ] Step 4: 接入 CI 配置文件
- [ ] Step 5: Git 原子提交

---

### Task 3: 切出通用布局与框架组件 (Layout & Navs) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/layout/head.html` (Lines 1~20: Meta, Title, CSS Links)
- Create: `static/layout/header.html` (Lines 21~49: Topbar, Version Chip, Brand)
- Create: `static/layout/nav_desktop.html` (Lines 50~106: Desktop Sidebar Nav)
- Create: `static/layout/nav_mobile.html` (Lines 2941~3006: Mobile Bottom Dock)
- Create: `static/layout/companion.html` (Lines 3009~3155: Mascot & Color Picker)
- Create: `static/index.skeleton.html` (主装配骨架文件)
- Modify: `static/index.html` (通过 build 脚本重新编译输出)

**Interfaces:**
- Consumes: 切片文件
- Produces: 生成的 `static/index.html` 保持逐字节与原文件相等（sha256 一致）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 提取框架与布局组件。
> 将 head, topbar, nav_desktop, nav_mobile, companion 从 index.html 无损抽离至 `static/layout/`。
> 配置 `static/index.skeleton.html`，执行 `python3 tools/build_index_html.py` 生成 `static/index.html`。
> 运行 `python3 tools/check_index_html_sync.py` 与 `tests/test_writer_mobile.py`，验证版本标签和布局断言完全通过。
> 确认 `git diff static/index.html` 净变更几乎为 0 或完全受控。"

**Step Breakdown:**
- [ ] Step 1: 提取各布局子文件至 `static/layout/`
- [ ] Step 2: 配置 `static/index.skeleton.html`
- [ ] Step 3: 运行 `build_index_html.py` 并执行同步比对
- [ ] Step 4: 运行相关测试（`test_writer_mobile.py`, `test_update_chip_ui.py`）
- [ ] Step 5: Git 原子提交

---

### Task 4: 切出业务视图层切片 (Views 1~9) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/views/home.html` (`#view-home`, 41 行)
- Create: `static/views/encounter.html` (`#view-encounter`, 84 行)
- Create: `static/views/reader.html` (`#view-reader`, 87 行)
- Create: `static/views/cards.html` (`#view-cards`, 154 行)
- Create: `static/views/progress.html` (`#view-progress`, 447 行)
- Create: `static/views/writer.html` (`#view-writer`, 286 行)
- Create: `static/views/exam.html` (`#view-exam`, 339 行)
- Create: `static/views/german.html` (`#view-german`, 13 行)
- Create: `static/views/search.html` (`#view-search`, 74 行)
- Modify: `static/index.skeleton.html`
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `static/views/*.html`
- Produces: 9 个 `<main class="view">` 独立切片模块；`build_index_html.py` 完美合成

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 提取 9 大业务视图。
> 按照各 `<main id=\"view-*\"></main>` 边界将业务视图抽离为 `static/views/` 下的独立 HTML 片段。
> 更新 `static/index.skeleton.html`，调用 `python3 tools/build_index_html.py` 生成 index.html。
> 运行全量视图测试：`test_encounter_*.py`, `test_exam_domain.py`, `test_search_ui.py`, `test_german_workbench.py`，
> 确保所有 DOM 相对位置、ID 唯一性以及 MJS 探针（`ia_dom_mount_probe.mjs`）100% 通过。"

**Step Breakdown:**
- [ ] Step 1: 抽取 9 个视图到 `static/views/`
- [ ] Step 2: 在 `index.skeleton.html` 注册引入
- [ ] Step 3: 重新生成并验证 `tools/check_index_html_sync.py`
- [ ] Step 4: 运行 `python3 -m pytest tests/test_exam_domain.py tests/test_encounter_ui_probes.py tests/test_search_ui.py`
- [ ] Step 5: Git 原子提交

---

### Task 5: 切出侧边栏抽屉与所有模态弹窗/覆盖层 (Drawer & Modals) [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/modals/drawer.html` (`#drawer`, 339 行)
- Create: `static/modals/import_modal.html` (`#modal-overlay`, 154 行)
- Create: `static/modals/settings_modal.html` (`#settings-overlay`, 247 行)
- Create: `static/modals/polish_modal.html` (`#polish-overlay`, 75 行)
- Create: `static/modals/version_preview_modal.html` (`#version-preview-overlay`, 64 行)
- Create: `static/modals/player_and_tooltip.html` (`#shadow-player`, `#selection-tooltip`, 151 行)
- Create: `static/modals/quiz_overlay.html` (`#quiz-overlay`, 160 行)
- Create: `static/modals/cloze_overlay.html` (`#cloze-overlay`, 94 行)
- Modify: `static/index.skeleton.html`
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `static/modals/*.html`
- Produces: 弹窗与悬浮层全量切分；`index.skeleton.html` 降至 ~80 行极简装配清单

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 提取侧边栏抽屉与弹窗/浮层模块。
> 将抽屉 `#drawer` 与全部 7 组弹窗抽离至 `static/modals/`。
> 在 `index.skeleton.html` 补全 include 指令，编译合成 `static/index.html`。
> 运行全量语法雷达和精读批注测试：`test_grammatik_radar.py`, `test_prep_matrix.py`, `test_audit_hardening.py`，
> 确保 `check_index_html_sync.py` 退出码 0。"

**Step Breakdown:**
- [ ] Step 1: 抽取抽屉与所有 Modals 到 `static/modals/`
- [ ] Step 2: 更新骨架装配清单并生成
- [ ] Step 3: 运行 `check_index_html_sync.py`
- [ ] Step 4: 运行 `tests/test_grammatik_radar.py tests/test_prep_matrix.py`
- [ ] Step 5: Git 原子提交

---

### Task 6: 全量回归门禁核验与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`
- Test: 全量 CI 测试矩阵

**Interfaces:**
- Consumes: Task 1~5 全部交付产物
- Produces: 交付 PR，全仓 2,367+ 单元测试守恒全绿，前端大单体彻底结构化解耦。

**Step Breakdown:**
- [ ] Step 1: 运行全量门禁：
  - `python3 tools/check_layer_invariants.py`
  - `python3 tools/check_mock_drift.py`
  - `python3 tools/check_silent_degradation.py`
  - `python3 tools/check_index_html_sync.py`
  - `python3 -m ruff check .`
  - `python3 -m mypy --strict delector tools`
  - `python3 -m mypy --follow-imports=skip tests`
  - `cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] Step 2: 全量 pytest 跑通（2,367+ 测试 100% 绿灯）
- [ ] Step 3: 检查 UTF-8 CRLF 卫生（0 lone LF）
- [ ] Step 4: 追加 `WORKMEMORY/work.log`
- [ ] Step 5: 推送分支并创建 GitHub PR

---

## 迷雾区与后续规划 (Fog of War)

- [x] **Task 1~6: 前端大单体 static/index.html 模块化拆分与同步机械闸**（2026-10-18 已完成，PR 待合并）
- [x] **[Unknown 1: 前端业务脚本 (`writer.js`, `cards.js`) 内部状态与 DOM 绑定的解耦]**—— **`writer.js` 已由 `docs/plans/2026-10-19-writer-js-modularization.md` 交付**（PR #160）：切出 L1 纯层 `wr-format.js` 与 L2 持久化层 `wr-api.js`，`writer.js` 1657→1526 行，并新增前端分层机械闸 `tools/check_frontend_layers.py` 把边界钉成 CI 契约。**剩余面转登记**：`cards.js`（1335 行）/ `reader.js`（1403 行）的同构切分 —— 见该计划 Fog of War Unknown 2。

---

## Out of Scope

- 引入 Webpack, Vite, Rollup 等外部前端打包构建工具（违背 0 复杂前端构建依赖原则）；
- 改动任何 DOM 节点 ID 或 class 名称（防止引发静默的前端或测试回归）；
- 重写 CSS 规则或设计 Token。
