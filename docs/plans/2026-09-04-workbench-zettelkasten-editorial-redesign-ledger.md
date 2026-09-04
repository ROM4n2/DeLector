# ADR-0006 实施计划执行台账 (Ledger)

> **计划路径**：`docs/plans/2026-09-04-workbench-zettelkasten-editorial-redesign.md`
> **设计参考**：`docs/specs/2026-09-04-adr-0006-workbench-zettelkasten-editorial-redesign.md` / `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0006-workbench-zettelkasten-editorial-redesign.md`
> **目标特性**：ADR-0006 (Zettelkasten Academic Card & Editorial Focus-First Redesign)
> **创建时间**：2026-09-04 21:30
> **基线状态**：pytest 全量 565 项全绿通过 (112.00s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Task 1** | 建立实施计划执行台账与回归基线 | Guard | 完成 | `4ec0734` | pytest 全量 565 passed (112.00s) + Node.js 探针 10/10 全绿（含 13/13 切片护栏） |
| **Task 2** | 全局字体族体系与画布排版规范化 | Frontend TDD Builder | 待开始 | - | 待执行（消除硬编码中文字体与 Georgia，引入 tokens.css） |
| **Task 3** | 心流优先轻量化出版物导航与顶栏重塑 | Frontend TDD Builder | 待开始 | - | 待执行（出版物下划线导航，顶栏精细收敛） |
| **Task 4** | Zettelkasten 实体学术卡片箱与矿物印章评分座重塑 | Frontend TDD Builder | 待开始 | - | 待执行（纯白纸张层叠、40px 衬线词头、浅柔印章评分底座） |
| **Task 5** | 自测题与词库辅助视图 Editorial 风格细化 | Frontend TDD Builder | 待开始 | - | 待执行（自测选项卡、拼写输入框、KPI 与词库表墨水化） |
| **Task 6** | 全量回归闭环、Ledger 收口与交付报告 | Guard | 待开始 | - | 待执行（全量回归全绿、工作记忆同步） |

---

## 回归基线证据记录 (Baseline Verification Evidence)

### 1. pytest 全量测试回归基线
- **执行命令**：`pytest -q`
- **执行耗时**：`112.00s (0:01:51)`
- **执行结果**：`565 passed, 1 warning in 112.00s`
- **结论**：后端与工作台核心契约测试 100% 全绿，无历史遗留失败。

### 2. Node.js 行为级探针回归基线
- **执行命令**：`Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
- **执行结果**：10/10 探针全部 PASS：
  1. `ia_dom_mount_probe.mjs` - PASS
  2. `wb_merge_probe.mjs` - PASS
  3. `wb_pair_persist_probe.mjs` - PASS
  4. `wb_pair_push_probe.mjs` - PASS
  5. `wb_phone_pull_probe.mjs` - PASS
  6. `wb_phone_pull_silent_probe.mjs` - PASS
  7. `wb_queue_probe.mjs` - PASS（13/13 处代码切片护栏 100% 校验通过，7 组动态状态机场景全部验证通过）
  8. `wb_rtc_connect_probe.mjs` - PASS
  9. `wb_rtc_reconnect_probe.mjs` - PASS
  10. `wb_sync_probe.mjs` - PASS
- **结论**：动态状态机行为与离线切片契约完整保持。

---

## 关键不变式与切片护栏注记 (Invariants & Guardrails)

1. **切片护栏绝对红线 (MUST)**：`static/german/workbench.html` 必须严格保护 `tools/wb_queue_probe.mjs` 中的 13 处代码切片（`pad2`, `buildReviewQueue`, `refilterReviewQueueForScope`, `renormalizeQueueTail` 等），严禁修改被测函数签名或内部大括号结构。
2. **DOM ID 稳定性 (MUST)**：保留 `#cardFlip`, `#revBoard`, `#scopeSeg`, `#tabs`, `#cardHw`, `#cardIpa`, `#cardPos`, `#cardGloss`, `#cardEx`, `#dueBadge`, `#rate-btn` 等所有交互 ID。
3. **iframe 物理沙箱隔离 (MUST)**：维持工作台单文件离线运行与 iframe 沙箱边界，不并入主站 SPA。
4. **TDD 流程**：Red -> Verify Red -> Green -> Verify Green -> Refactor -> Commit。
