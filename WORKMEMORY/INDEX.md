## Configuration

- HOT_RETENTION_EVENTS: 50 # work.log 热层保留事件数；轮转阈值 = 本值 × 1.5

## 文件清单

| 文件                  | 职责                                                          |
| --------------------- | ------------------------------------------------------------- |
| `PROTOCOL.md`         | 协议本体（读一次即可，之后按本索引工作）                      |
| `PROJECT_OVERVIEW.md` | 60 秒项目 primer（新 agent 第二读）                           |
| `work.log`            | HOT 事件流（append-only，最近 50 条；第三读）                 |
| `archive/`            | WARM 层（按日分片 `work-YYYY-MM-DD.log`，只按下方索引按需加载） |
| `cold/`               | COLD 层（按月 digest；现有 `digest-2026-09.md` · **`digest-2026-10.md`**（2026-10-16 生成，覆盖 v5.14.0~v5.17.0 / ADR-0017~0024 / 审计修正 A/B 批）） |
| `notes/`              | 超限事件正文（`NOTES-<日期>-<时间>-<slug>.md`，协议 §1.4；2026-10-17 从顶层收拢进本目录）。⚠️ 旧事件里以**文件名**引用的 NOTES 现在位于本目录——按名检索即可命中，事件正文按追加制不回改 |
| `handoff_*.md`        | 跨 agent 交接包（**按需出现**：仅当存在活跃交接时才存在，非常驻文件；协议 §4）。**closed 的 MUST 移入 `archive/handoff_*.md`** 并在下方「已归档 handoffs」登记 |


> **主题索引与蒸馏登记已下沉**：见 `INDEX-topics.md`（WARM 层，按需加载；协议 §3）。**本文件是 HOT 索引，MUST 保持极小**——只留配置、文件清单、Active handoffs、已归档 handoffs。

**新 agent 先看这里**：最近一份交接包 = [`archive/handoff_audit-fixes-a-b.md`](archive/handoff_audit-fixes-a-b.md)（closed 2026-10-17，**内容仍有效**，含 12 条风险与坑 + 本日进展补充）—— C 档 8 项的完整上下文在里面。

## Active handoffs

- 2026-10-14 → [`handoff_no-console-feedback-gaps.md`](handoff_no-console-feedback-gaps.md)（to: any · role: VERIFY/TEST · status: open）— 真机双击验收 + digest 归一历史 header
- 2026-10-18 → [`handoff_c7-workbench-html-split.md`](handoff_c7-workbench-html-split.md)（to: any · role: IMPLEMENT · status: open · **2026-10-18 已接手执行中**：worktree `D:\Code\DeLector-c7` / 分支 `refactor/c7-workbench-html-split` / 台账 0/6，Task-1 开工）— C7 `workbench.html` 拆分：含 **140 个耦合探针的实测盘点**（A91/B4/C21/D12/E12）+ 13 个 `.mjs` 探针断裂清单 + 入口路径不可改名的 5 处钉死点 + 迁移依赖顺序 + **并行文件占面契约**；计划正本 `docs/plans/2026-10-18-c7-workbench-html-split.md`

## 已归档 handoffs
> 协议 §4：关闭后 MUST 移入 `WORKMEMORY/archive/`；`handoff_*.md` 只保留**活跃**交接。
- 2026-10-15 → `archive/handoff_judge-gaming-experiment.md`（**closed 2026-10-16**）— §4.3 第 8 条对照实验：60 局真跑 + 全景报告 + ADR-0024 签批 + PR #139 已合入 master。剩余边界（不是待办）：P1 本形态下无发生机制；回灌子计划见 ADR-0024 硬依赖
- 2026-10-16 → `archive/handoff_audit-fixes-a-b.md`（**closed 2026-10-17**）— 审计修正 A 档 8 项 + B 档 5 项均已合入 master（#143 `459343b` / #144 `c79e764`）；WORKMEMORY 已轮转并生成 10 月 COLD digest；**唯一待办入口 = `docs/reviews/2026-10-16-open-items-backlog.md` 的 C 档 8 项**
- 2026-10-14 → `archive/handoff_interactive-agent-loop.md`（**closed 2026-10-15**）— ADR-0023 交互层循环 Task 3~6 + CI 半 + PR #136 均已交付
