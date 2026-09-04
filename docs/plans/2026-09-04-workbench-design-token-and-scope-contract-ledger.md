# 路线 B 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-04-workbench-design-token-and-scope-contract.md`
> **设计参考**：`docs/specs/2026-09-04-workbench-design-token-and-scope-contract-design.md`
> **创建时间**：2026-09-04 20:25
> **基线状态**：pytest 559 通过，Node.js 探针 10/10 通过。

---

## 任务执行清单

| **Task 0** | 建立回归基线与 Ledger 台账              | 完成 | `b37b86a` | 559 pytest + 10/10 探针全绿                           |
| **Task 1** | 共享设计 Token 层抽取 (`tokens.css`)    | 完成 | `a5c72d4` | `test_workbench_tokens.py` (2 passed) + Reviewer PASS |
| **Task 2** | 背词工作台视觉体系重塑 (Editorial 风格) | 完成 | `fd3afcb` | 13 项探针切片护栏全绿 + Reviewer PASS                 |
| **Task 3** | CEFR 考纲词库数据契约端点扩展           | 完成 | `37a74e0` | `test_server.py` 词库接口测试 + Reviewer PASS         |
| **Task 4** | 工作台范围选择器扩展与词表契约接入      | 完成 | `b9df963` | 13 项探针切片全绿 + 10/10 探针 PASS + Reviewer PASS   |
| **Task 5** | 全量回归闭环、Ledger 收口与交付报告     | 完成 | 本次提交  | 全量 565 pytest 全绿 (0 失败) + 10/10 Node.js 探针全绿 |

---

## 偏差与关键注记 (Deviations & Notes)

- 严密监控 `tools/wb_queue_probe.mjs` 中的 13 处代码切片，任何样式或 HTML 改动不破坏切片边界。
