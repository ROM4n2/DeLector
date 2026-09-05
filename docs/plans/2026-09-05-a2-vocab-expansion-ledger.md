# A2 词汇与全域背词系统扩展实施执行台账 (Ledger)

> **计划路径**：[`docs/plans/2026-09-05-a2-vocab-expansion-implementation-plan.md`](file:///d:/Code/DeLector/docs/plans/2026-09-05-a2-vocab-expansion-implementation-plan.md)  
> **目标特性**：A2 词汇与全域背词系统扩展 (方案 B：全域贯通方案)  
> **创建时间**：2026-09-05 16:35  
> **基线状态**：pytest 全量 574 passed (109.26s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
|:---|:---|:---|:---|:---|:---|
| **Task 1** | A2 词汇格式化函数与数据契约扩展 (`database.py` + `test_a2_vocab_data.py`) | Backend TDD Builder | 待执行 | 待提交 | 待验证 |
| **Task 2** | 服务端 A2 考纲端点与 Catalog 注册 (`routes_a2.py` + `exam_catalog.py` + `server.py`) | Backend TDD Builder | 待执行 | 待提交 | 待验证 |
| **Task 3** | 背词工作台 4 档范围扩展与 13 处切片护栏保护 (`workbench.html`) | Frontend TDD Builder | 待执行 | 待提交 | 待验证 |
| **Task 4** | 备考域前端 A2 考纲词表与卡盒激活 (`main.js` & `a1_cards.js`) | Frontend TDD Builder | 待执行 | 待提交 | 待验证 |
| **Task 5** | 打包同步、回归闭环与台账归档 | Guard Subagent | 待执行 | 待提交 | 待验证 |

---

## 回归基线证据记录 (Baseline Verification Evidence)

### 1. pytest 全量测试回归基线
- **执行命令**：`python -m pytest -q --tb=short`
- **执行基线**：`574 passed, 1 warning in 109.26s`
- **说明**：所有历史功能与测试 100% 绿色通过，当前处于基线锁定状态。

### 2. Node.js 行为级探针回归基线
- **执行命令**：`Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
- **执行基线**：10/10 探针全部 PASS（含 `wb_queue_probe.mjs` 13/13 处代码切片护栏 100% 保护）。

---

## 实施后验证证据 (Post-Implementation Verification Evidence)

*(待实施完成后填充)*
