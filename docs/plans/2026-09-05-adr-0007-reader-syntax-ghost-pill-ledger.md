# ADR-0007 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-05-adr-0007-reader-syntax-ghost-pill.md`
> **设计参考**：`docs/specs/2026-09-05-adr-0007-reader-syntax-ghost-pill-explicit-trigger.md` / `D:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0007-reader-syntax-ghost-pill-explicit-trigger.md`
> **目标特性**：ADR-0007 (精读句法拓扑行内幽灵微胶囊主动触发与心流保护)
> **创建时间**：2026-09-05 16:02
> **基线状态**：pytest 全量 574 passed (110.75s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
|:---|:---|:---|:---|:---|:---|
| **Task 1** | 契约测试更新: `test_grammatik_radar.py` 与 `test_frontend_security.py` | Frontend TDD Builder | 进行中 | 待提交 | 待验证 |
| **Task 2** | 前端代码实现: `reader.js` 移除定时器+恢复幽灵胶囊按钮，`style.css` 幽灵样式细化 | Frontend TDD Builder | 待开始 | 待提交 | 待验证 |
| **Task 3** | 独立代码审查与全量回归闭环 (574+ pytest & 10/10 探针) | Guard | 待开始 | 待提交 | 待验证 |