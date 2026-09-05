# 路线 C — Grammatik-Radar: 精读语法雷达 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-04-grammatik-radar-implementation-plan.md`
> **目标特性**：路线 C Grammatik-Radar（精读五场域/从句树 Hover 触发 + 语料语法统计 + 蜘蛛图雷达）
> **创建时间**：2026-09-05 15:20
> **基线状态**：pytest 全量 569 passed (118.88s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
|:---|:---|:---|:---|:---|:---|
| **Task 1** | DB schema: `corpus_syntax_stats` 表 + `upsert_corpus_syntax_stats` + `get_all_corpus_syntax_stats` | Backend TDD Builder | 进行中 | 待提交 | 待验证 |
| **Task 2** | 后端路由: `POST /api/syntax/stats` + `GET /api/syntax/stats` | Backend TDD Builder | 待开始 | 待提交 | 待验证 |
| **Task 3** | `index.html`: 清理 `sent-syntax-btn` + 新增 `#grammar-radar-panel` | Frontend TDD Builder | 待开始 | 待提交 | 待验证 |
| **Task 4** | `reader.js`: hover debounce 600ms + `computeArticleSyntaxStats` | Frontend TDD Builder | 待开始 | 待提交 | 待验证 |
| **Task 5** | `reader.js` & `style.css`: `renderRadarSvg` + `saveAndRenderSyntaxRadar` + radar 样式 | Frontend TDD Builder | 待开始 | 待提交 | 待验证 |
| **Task 6** | 全量回归闭环、Ledger 收口与交付报告 | Guard | 待开始 | 待提交 | 待验证 |

---

## 回归基线证据记录 (Baseline Verification Evidence)

### 1. pytest 全量测试回归基线
- **执行命令**：`python -m pytest -q --tb=short`
- **执行结果**：`569 passed, 1 warning in 118.88s`
- **说明**：Git Bash 检测逻辑在 `test_server.py` 已修复，基线 569 项 100% 通过。

### 2. Node.js 行为级探针回归基线
- **执行命令**：`Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
- **执行结果**：10/10 探针全部 PASS（含 `wb_queue_probe.mjs` 13/13 处代码切片护栏 100% 保护）。