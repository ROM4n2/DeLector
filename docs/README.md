# docs/ 目录约定

> 本目录是**仓库内的文档中枢**。每层单一职责；新文档按下表归位，**不要**再新建平行的工作流目录。
> 约定只在「约定本身」失真时才改——改这里等于改全仓文档的落位规则。

## 分层

| 目录 | 放什么 | 归档约定 |
|---|---|---|
| `plans/` | **在途**实施计划（vault-plan schema：Goal / Tech Stack / Spec Reference / Global Constraints + Task 拆分 + TDD 步骤） | 交付后 `git mv` 进 `plans/archive/` |
| `plans/archive/` | 已交付的历史计划，含成对的 `-ledger.md`（vault-exec 执行台账）与 `-review.md`（评审子产物） | 只进不出 |
| `specs/` | **设计稿**：统一命名 `<日期>-<主题>-design.md` | 无归档层（设计意图长期有效） |
| `adr/` | **仓内 ADR 副本**：`<日期>-adr-XXXX-<主题>.md`（正式件在 Vault） | 无归档层 |
| `reviews/` | 审计 / 评审报告（一次性、带日期） | — |
| `agents/` | 面向 agent 的常青文档：`architecture.md`（架构与跨端契约）、`ops.md`（运维）、以及需人工/agent 逐项填写的复测清单 | — |
| 顶层 `*.md` | 跨领域的常青规范：`design-system.md`（设计系统；token / 排印现值以 `static/css/tokens.css` 为准）、`svg-character-spec.md`（角色 SVG 规格） | — |

## 放置规则（速查）

1. **要实现一个功能** → 计划写 `plans/<日期>-<主题>.md`；**做完并进入某个发布版本后**，`git mv` 到 `plans/archive/`。
   - 判据是「成果已发版」，不是「我感觉做完了」。
2. **要写设计稿** → `specs/<日期>-<主题>-design.md`；**要放 ADR 副本** → `adr/<日期>-adr-XXXX-<主题>.md`。
3. **要交一份审计 / 评审结论** → `reviews/`。
4. **不要再开平行目录**：历史上的 `docs/superpowers/plans/`（15 份 2026-08-18~22 的最早期计划）与 `docs/compose/spec/`（1 份 YAML frontmatter 格式的 spec）已分别并入 `plans/archive/` 与 `specs/`；`specs/` 里混放的 4 份 ADR 副本也已拆到 `adr/`。

## 归档待办（下次发版时执行，2026-10-16 登记）

> 判据重申：计划进 `plans/archive/` 的条件是**成果已发版**，不是"做完了"。下列 9 份已交付（台账均 100%），但都发生在 **v5.17.0（2026-10-11 发版）之后** ⇒ 目前 master 上属于**未发版**状态，按规则**先留在 `plans/`**。
> **v5.18.0（或下一个包含它们的版本）发版时**，执行批量 `git mv` 到 `plans/archive/`（一并更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 与 INDEX 的引用路径）：

| 计划（现位于 `plans/`） | 交付状态 | 入 master 的 PR |
| --- | --- | --- |
| `2026-10-12-release-pipeline-and-docs-consolidation.md` | WORK_END 10-12 | （随 10-12 批次） |
| `2026-10-13-windows-no-console-desktop-polish.md` | WORK_END 10-13 | （随 10-13 批次） |
| `2026-10-14-interactive-agent-loop.md` | Task 0~6 全交付 | #136 |
| `2026-10-14-no-console-feedback-gaps.md` | WORK_END 10-14 | #131（真机双击验收项仍 open） |
| `2026-10-15-a1-judge-expansion.md` | 8/8 | #137 |
| `2026-10-15-judge-gaming-experiment.md` | 8/8（含 60 局真跑） | #139 |
| `2026-10-16-audit-fixes-a-series.md` | 5/5 | #143 |
| `2026-10-16-audit-fixes-b-series.md` | 4/4 | #143 |
| `2026-10-16-database-split.md` | 5/5 | #144 |

**命名豁免（历史既成事实，不改）**：`plans/archive/` 里 4 份**早于 `<日期>-` 命名规则**的文件（`workbench-scope-control-and-live-settings.md`、`workbench-progress-server-sync.md`、`workbench-core-words-mode.md`、`plan-companion-mascot.md`）**保留原名**——改名会打断既有引用（含 vault 侧），收益不足以抵风险。此后新增的归档件一律带 `<日期>-` 前缀。

## 与别处的关系

- **发版历史**以根目录 `CHANGELOG.md` 为唯一正主（single source of truth）；本目录**不放**发布说明。
  - 2026-10-02 清理：v2.1 时代的一次性发布总结 `release-v2.1.md` 已移除——内容既已被 CHANGELOG 的 v2.1 路线图条目覆盖，又与现实矛盾（写着「测试 20/20」、Docker「挂载当前目录」，而 #69 已改为 `./data` 目录挂载）。原件在 git 历史里可取回。
- **ADR 正式件**在 Obsidian Vault `08-Projects/DeLector/01-ADR/`；`adr/` 里的是**仓内副本**，便于随代码一起检索引证。
- **计划/设计稿被代码、测试或注释引用**时，写**相对仓库根**的完整路径（如 `docs/plans/archive/2026-09-09-ci-hardening.md`），这样 `grep` 与「路径存在性校验」都能覆盖到。
