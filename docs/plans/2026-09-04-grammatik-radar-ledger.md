# 路线 C — Grammatik-Radar: 精读语法雷达 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-04-grammatik-radar-implementation-plan.md`
> **目标特性**：路线 C Grammatik-Radar（精读五场域/从句树 Hover 触发 + 语料语法统计 + 蜘蛛图雷达）
> **创建时间**：2026-09-05 15:20
> **基线状态**：pytest 全量 569 passed (118.88s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
|:---|:---|:---|:---|:---|:---|
| **Task 1** | DB schema: `corpus_syntax_stats` 表 + `upsert_corpus_syntax_stats` + `get_all_corpus_syntax_stats` | Backend TDD Builder | 已完成 | `06a40d2` | `test_corpus_syntax_stats_db_contract` PASS |
| **Task 2** | 后端路由: `POST /api/syntax/stats` + `GET /api/syntax/stats` | Backend TDD Builder | 已完成 | `e4e068d` | `test_syntax_stats_endpoints` PASS |
| **Task 3** | `index.html`: 清理 `sent-syntax-btn` + 新增 `#grammar-radar-panel` | Frontend TDD Builder | 已完成 | `2b4e229` | `test_radar_panel_present_in_syntax_drawer` PASS |
| **Task 4** | `reader.js`: hover debounce 600ms + `computeArticleSyntaxStats` | Frontend TDD Builder | 已完成 | `c0cdeb8` | `test_reader_compute_article_syntax_stats_and_hover_binding` PASS |
| **Task 5** | `reader.js` & `style.css`: `renderRadarSvg` + `saveAndRenderSyntaxRadar` + radar 样式 | Frontend TDD Builder | 已完成 | `09c6d34` | `test_render_radar_svg_and_radar_panel_integration` PASS |
| **Task 6** | 全量回归闭环、Ledger 收口与交付报告 | Guard | 已完成 | 本地工作树 | 全量 574 passed (109.26s) + 10/10 探针 PASS |

---

## 回归基线证据记录 (Baseline Verification Evidence)

### 1. pytest 全量测试回归基线
- **执行命令**：`python -m pytest -q --tb=short`
- **执行结果**：`569 passed, 1 warning in 118.88s`
- **说明**：Git Bash 检测逻辑在 `test_server.py` 已修复，基线 569 项 100% 通过。

### 2. Node.js 行为级探针回归基线
- **执行命令**：`Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
- **执行结果**：10/10 探针全部 PASS（含 `wb_queue_probe.mjs` 13/13 处代码切片护栏 100% 保护）。

---

## 实施后验证证据 (Post-Implementation Verification Evidence)

### 1. pytest 全量回归验证
- **执行命令**：`python -m pytest -q --tb=short`
- **执行结果**：`574 passed, 1 warning in 109.26s`
- **净增测试**：+5 项语法雷达端到端与契约测试（`test_grammatik_radar.py` 3 项 + `test_server.py` 新增 2 项：`test_syntax_stats_endpoints`、`test_radar_panel_present_in_syntax_drawer`），100% 通过。

### 2. Node.js 行为级探针回归验证
- **执行命令**：`pwsh -Command "Get-ChildItem tools/*.mjs | ForEach-Object { node `$_.FullName }"`
- **执行结果**：10/10 探针全部 PASS，`wb_queue_probe.mjs` 13/13 处代码切片护栏 100% 保护通过，零漂移、零破坏。