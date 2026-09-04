# 背词工作台实体学术卡片箱 (Zettelkasten) 与心流优先重塑实施计划

> **Goal**: 依据 ADR-0006 裁决，彻底剔除背词工作台 2018 年 Bootstrap / 后台管理工具的粗糙视觉骨架；将全局字体、画布、Tab 导航与卡片体系重塑为与 DeLector 主站同源共生的 **Oxford / Zettelkasten 实体学术抽认卡** 与 **心流优先出版物轻量导航**；评分区全面替换为高质感的矿物植物墨水印章键，并全程严格守护 `tools/wb_queue_probe.mjs` 中的 13 处代码切片与既有测试套件 100% 全绿。
> **Tech Stack**: 原生 CSS（Custom Properties 设计 Token、CSS 3D Transform）、原生 JavaScript（单文件 SPA + iframe 容器）、node:vm 行为级动态探针。
> **ADR Reference**: [`d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0006-workbench-zettelkasten-editorial-redesign.md`](file:///d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0006-workbench-zettelkasten-editorial-redesign.md) / [`docs/specs/2026-09-04-adr-0006-workbench-zettelkasten-editorial-redesign.md`](file:///d:/Code/DeLector/docs/specs/2026-09-04-adr-0006-workbench-zettelkasten-editorial-redesign.md)
> **Global Constraints**:
> - **切片护栏绝对红线 (MUST)**：`static/german/workbench.html` 必须严格保护 `tools/wb_queue_probe.mjs` 中的 13 处代码切片（`pad2`, `buildReviewQueue`, `refilterReviewQueueForScope`, `renormalizeQueueTail` 等）。严禁修改被测函数签名或内部大括号结构。
> - **DOM ID 稳定性 (MUST)**：保留 `#cardFlip`, `#revBoard`, `#scopeSeg`, `#tabs`, `#cardHw`, `#cardIpa`, `#cardPos`, `#cardGloss`, `#cardEx`, `#dueBadge`, `#rate-btn` 等所有交互 ID。
> - **iframe 物理沙箱隔离 (MUST)**：维持工作台单文件离线运行与 iframe 沙箱边界，不并入主站 SPA。
> - **TDD 流程**：Red -> Verify Red -> Green -> Verify Green -> Refactor -> Commit。

---

## User Review Required

> [!IMPORTANT]
> - **视觉风格蜕变**：卡片底部原有的「粗厚纯红/纯黄/纯绿实色大色块」将彻底废除，全面升级为「浅柔底色 + 细墨水边框 + 键盘快捷键角标」的典雅矿物印章风格；Tab 导航栏从大圆角实色块进化为主站同款极简下划线出版物目录。
> - **测试守卫**：全过程由 `test_german_workbench.py` 79 项静态契约测试与 10 个 Node.js 行为级探针实时守卫，确保 0 破坏、0 回归。

---

## Proposed Tasks Breakdown

### Task 1: 建立实施计划执行台账与回归基线 [Role: Guard]

**Files:**
- Create: `docs/plans/2026-09-04-workbench-zettelkasten-editorial-redesign-ledger.md`
- Create: `docs/plans/2026-09-04-workbench-zettelkasten-editorial-redesign.md`

**Interfaces:**
- Consumes: master @ HEAD (`4ec0734`), 现有 565 项测试与 10/10 探针
- Produces: 任务执行台账 ledger，基线测试记录

**Subagent Prompt Scaffold:**
> Implement Task 1: 建立 ADR-0006 实施台账与基线。
> Goal: 记录基线测试结果（pytest 565 passed + 10/10 tools/*.mjs 探针全绿），初始化实施台账。
> TDD Steps:
> 1. 运行 `pytest -q` 并确认 565 passed。
> 2. 运行 `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }` 确认 10/10 探针通过。
> 3. 初始化 `docs/plans/2026-09-04-workbench-zettelkasten-editorial-redesign-ledger.md`。
> Return: 基线通过记录与 ledger 路径。

---

### Task 2: 全局字体族体系与画布排版规范化 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:50-120` (CSS reset, font-family, wrap layout)
- Modify: `test_workbench_tokens.py` (新增字体与画布规范断言)

**Interfaces:**
- Consumes: `static/css/tokens.css` 导出的 `--serif`, `--sans`, `--mono`, `--paper`, `--ink`, `--rule`
- Produces: 规范使用 Editorial 字体体系的 `workbench.html`，彻底消除 `"Microsoft YaHei"` 与 `Georgia` 硬编码

**Subagent Prompt Scaffold:**
> Implement Task 2: 全局字体族体系与画布排版规范化。
> Goal: 消除 `static/german/workbench.html` 中的硬编码中文字体与 Georgia，全面接入 `--sans`, `--serif`, `--mono`；将 `.wrap` 容器宽度由生硬的 1060px 优化为更具杂志聚焦感的 960px，并调优呼吸感留白。
> Target Files: Modify `static/german/workbench.html`, `test_workbench_tokens.py`.
> TDD Steps:
> 1. 在 `test_workbench_tokens.py` 编写 `test_workbench_editorial_typography_contract`（RED）：断言 `body` 使用 `var(--sans)`，不再硬编码 `Microsoft YaHei`；断言 `.kbd` 或快捷键使用 `var(--mono)`。
> 2. 运行测试确认失败（RED）。
> 3. 修改 `workbench.html` 中的 CSS 基础重置与排版规则（GREEN）。
> 4. 运行 `node tools/wb_queue_probe.mjs` 确认 13 条切片护栏通过。
> 5. 运行 `pytest test_workbench_tokens.py test_german_workbench.py` 确认全绿。
> Return: 测试输出证据。

---

### Task 3: 心流优先轻量化出版物导航与顶栏重塑 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:75-120` (`header.top`, `.seg`, `nav.tabs`, `.progress`)
- Test: `test_german_workbench.py`, `tools/wb_queue_probe.mjs`

**Interfaces:**
- Consumes: Academic Modern Editorial 导航设计标准
- Produces: 出版物下划线滑动导航（Subtle Underline Tabs）与紧凑收敛顶栏；既有 DOM 事件无损保留

**Subagent Prompt Scaffold:**
> Implement Task 3: 心流优先轻量化出版物导航与顶栏重塑。
> Goal: 重塑 `header.top`、`#scopeSeg` 与 `nav.tabs`。将粗重大圆角实色 Tab 栏改为典雅的出版物下划线导航（无粗厚背景，深碳墨水文字，激活项展示 2px `--accent` 赤陶红细下划线）；顶栏分段控件与待学徽标精细收敛，降低视觉压迫感。
> Target Files: Modify `static/german/workbench.html`.
> Invariants: 严禁修改 `#scopeSeg` 和 `#tabs` 内部按钮的 `data-scope` / `data-view` 属性及 DOM 树关键结构，确保 `test_german_workbench.py` 79 项契约全部通过。
> TDD Steps:
> 1. 验证 `pytest test_german_workbench.py` 当前通过。
> 2. 在 `test_workbench_tokens.py` 增补下划线导航样式与紧凑排版断言（RED）。
> 3. 更新 `workbench.html` `<style>` 中关于 `header.top`, `.seg`, `nav.tabs`, `.progress` 的样式规则（GREEN）。
> 4. 运行 `node tools/wb_queue_probe.mjs` 与 `pytest test_german_workbench.py` 确保 100% 全绿。
> Return: 探针与测试输出证据。

---

### Task 4: Zettelkasten 实体学术卡片箱与矿物印章评分座重塑 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:120-170` (`.flip`, `.face`, `.rate-row`, `.rate-btn`, `.arrow`)
- Test: `test_workbench_tokens.py`, `tools/wb_queue_probe.mjs`

**Interfaces:**
- Consumes: `--paper-card`, `--rule`, `--shadow-card`, `--good-soft`, `--moss`, `--hard-soft`, `--mustard`, `--again-soft`, `--cherry`
- Produces: 极具实体书写与卡片箱质感的单词卡片、优雅的矿物墨水印章键，彻底告别粗笨大纯色块

**Subagent Prompt Scaffold:**
> Implement Task 4: Zettelkasten 实体学术卡片箱与矿物印章评分座重塑。
> Goal:
> 1. 重构 `.face`: 使用纯白 `#ffffff` 叠放于 `#faf8f5` 暖纸画布，1px `--rule` 精致细边框，`--shadow-card` 纸张微悬浮；德语词头 40px `Playfair Display` 衬线排版；例句使用出版物双行对照。
> 2. 重构 `.rate-btn`: 废弃大红大绿粗暴实色！改为浅柔底色（`--good-soft`, `--hard-soft`, `--again-soft`）+ 细墨水边框与深字（`--moss`, `--mustard`, `--cherry`），内嵌 `[1] [2] [3]` 等宽快捷键小标，带微抬升动效。
> 3. 重构 `.arrow`: 弱化为与卡片边缘呼应的轻质悬浮微交互，不再突兀。
> Target Files: Modify `static/german/workbench.html`.
> Invariants: 严禁破坏 `tools/wb_queue_probe.mjs` 的 13 项切片护栏及 `test_german_workbench.py`。
> TDD Steps:
> 1. 在 `test_workbench_tokens.py` 编写卡片纸张材质与印章评分键样式契约测试（RED）。
> 2. 运行测试确认失败（RED）。
> 3. 在 `workbench.html` 更新卡片与评分底座样式规则（GREEN）。
> 4. 运行 `node tools/wb_queue_probe.mjs` 确保 13 条切片护栏全绿。
> 5. 运行 `pytest test_german_workbench.py test_workbench_tokens.py` 确保全绿。
> Return: 探针验证证据与截图/代码对比。

---

### Task 5: 自测题与词库辅助视图 Editorial 风格细化 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:170-250` (`.qopt`, `.wtab`, `.kpi`, `.mode-card`)
- Test: `tools/wb_queue_probe.mjs`, `test_german_workbench.py`

**Interfaces:**
- Consumes: Editorial 表格与表单控件 Token
- Produces: 自测题卡与词库表格视觉统筹，完全对齐主站学术期刊质感

**Subagent Prompt Scaffold:**
> Implement Task 5: 自测题与词库辅助视图 Editorial 风格细化。
> Goal: 将自测视图的 `.qopt`（自测选择题项）、`.spell-input`（拼写输入框）、统计视图 `.kpi` 与词库视图 `.wtab` 细化为 Editorial 墨水装订风，消除刺眼的色块与生硬的虚线。
> Target Files: Modify `static/german/workbench.html`.
> TDD Steps:
> 1. 在 `test_workbench_tokens.py` 增补辅助视图样式契约测试（RED）。
> 2. 优化 `workbench.html` 中 `.qopt`, `.wtab`, `.kpi` 样式（GREEN）。
> 3. 运行 `node tools/wb_queue_probe.mjs` 确保 13 条切片护栏全绿。
> 4. 运行全部 10 个 Node.js 探针确保全绿。
> Return: 测试输出证据。

---

### Task 6: 全量回归闭环、Ledger 收口与交付报告 [Role: Guard]

**Files:**
- Modify: `docs/plans/2026-09-04-workbench-zettelkasten-editorial-redesign-ledger.md`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`
- Modify: `WORKMEMORY/work.log`

**Interfaces:**
- Consumes: 全部任务的视觉重构产物
- Produces: 全量测试全绿证据报告、更新完毕的工作记忆与执行台账

**Subagent Prompt Scaffold:**
> Implement Task 6: 全量回归与交付收口。
> Goal: 运行全量 565+ 项 pytest 与 10/10 动态探针，验证 100% 全绿且零回归，更新台账与 WORKMEMORY。
> Steps:
> 1. 运行 `pytest -q`，确认全部通过。
> 2. 运行 `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }` 确认 10/10 探针通过。
> 3. 回填执行台账。
> 4. 更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 与 `WORKMEMORY/work.log`。
> 5. Git 原子提交 `docs: 完成背词工作台 Zettelkasten 实体卡片与心流优先重塑`。
> Return: 全量通过证据报告。

---

## Verification Plan

### Automated Tests
- `pytest test_workbench_tokens.py -v`: 验证字体族、卡片材质与矿物印章键样式契约
- `pytest test_german_workbench.py -q`: 验证 79 项工作台静态架构与逻辑契约未受任何破坏
- `node tools/wb_queue_probe.mjs`: 验证 13 项核心切片护栏及 7 组动态状态机场景全部通过
- `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`: 验证 10 个动态行为探针全部通过
- `pytest -q`: 全量测试全绿验证（565+ 项零失败）

### Manual / Browser Verification
- 检查桌面与移动端视口下卡片居中感与呼吸感；
- 验证翻转动画与 `1` / `2` / `3` 键盘快捷键高频打卡的心流体验；
- 验证暗黑模式下的低眩光学术研读质感。
