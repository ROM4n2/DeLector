# 路线 B 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-04-workbench-design-token-and-scope-contract.md`
> **设计参考**：`docs/specs/2026-09-04-workbench-design-token-and-scope-contract-design.md`
> **创建时间**：2026-09-04 20:25
> **基线状态**：pytest 559 通过，Node.js 探针 10/10 通过。

---

## 任务执行清单

| 任务       | 目标                                    | 状态   | Commit      | 验证证据                      |
| :--------- | :-------------------------------------- | :----- | :---------- | :---------------------------- |
| **Task 0** | 建立回归基线与 Ledger 台账              | 完成   | 当前 commit | 559 pytest + 10/10 探针全绿   |
| **Task 1** | 共享设计 Token 层抽取 (`tokens.css`)    | 进行中 | 待提交      | `test_workbench_tokens.py`    |
| **Task 2** | 背词工作台视觉体系重塑 (Editorial 风格) | 待开始 | 待提交      | 13 项探针切片护栏全绿         |
| **Task 3** | CEFR 考纲词库数据契约端点扩展           | 待开始 | 待提交      | `test_server.py` 词库接口测试 |
| **Task 4** | 工作台范围选择器扩展与词表契约接入      | 待开始 | 待提交      | 探针队列过滤与离线 fallback   |
| **Task 5** | 全量回归闭环、Ledger 收口与交付报告     | 待开始 | 待提交      | 全量全绿报告                  |

---

## 偏差与关键注记 (Deviations & Notes)

- 严密监控 `tools/wb_queue_probe.mjs` 中的 13 处代码切片，任何样式或 HTML 改动不破坏切片边界。
