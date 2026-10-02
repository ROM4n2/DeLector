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
| 顶层 `*.md` | 跨领域的常青规范：`design-system.md`（设计系统）、`svg-character-spec.md`（角色 SVG 规格） | — |

## 放置规则（速查）

1. **要实现一个功能** → 计划写 `plans/<日期>-<主题>.md`；**做完并进入某个发布版本后**，`git mv` 到 `plans/archive/`。
   - 判据是「成果已发版」，不是「我感觉做完了」。
2. **要写设计稿** → `specs/<日期>-<主题>-design.md`；**要放 ADR 副本** → `adr/<日期>-adr-XXXX-<主题>.md`。
3. **要交一份审计 / 评审结论** → `reviews/`。
4. **不要再开平行目录**：历史上的 `docs/superpowers/plans/`（15 份 2026-08-18~22 的最早期计划）与 `docs/compose/spec/`（1 份 YAML frontmatter 格式的 spec）已分别并入 `plans/archive/` 与 `specs/`；`specs/` 里混放的 4 份 ADR 副本也已拆到 `adr/`。

## 与别处的关系

- **发版历史**以根目录 `CHANGELOG.md` 为唯一正主（single source of truth）；本目录**不放**发布说明。
  - 2026-10-02 清理：v2.1 时代的一次性发布总结 `release-v2.1.md` 已移除——内容既已被 CHANGELOG 的 v2.1 路线图条目覆盖，又与现实矛盾（写着「测试 20/20」、Docker「挂载当前目录」，而 #69 已改为 `./data` 目录挂载）。原件在 git 历史里可取回。
- **ADR 正式件**在 Obsidian Vault `08-Projects/DeLector/01-ADR/`；`adr/` 里的是**仓内副本**，便于随代码一起检索引证。
- **计划/设计稿被代码、测试或注释引用**时，写**相对仓库根**的完整路径（如 `docs/plans/archive/2026-09-09-ci-hardening.md`），这样 `grep` 与「路径存在性校验」都能覆盖到。
