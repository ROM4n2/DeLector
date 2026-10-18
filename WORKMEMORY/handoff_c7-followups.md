---
to: any
from: codebuddy
created: 2026-10-18 13:10
role: FIX | VERIFY
status: open
---
# Handoff: C7 收尾的两项遗留（`--extract` 地雷 · `doRate` 行为覆盖）

> C7（`workbench.html` 拆分）已全部交付并合并（PR #152 / #153，master `80dae6b`）。本包只含**两项独立、互不耦合**的遗留，可分开做、也可并行。

---

## 任务上下文

两项都**不在** C7 的范围内，是拆分过程中发现并按要求登记下来的。
基线：master `80dae6b`；`static/german/workbench.html` 现已 2840 行。

---

## 一、`--extract` 会覆写手工维护的模块（**优先级高，危险**）

**现象**：跑 `python tools/build_workbench_seed.py --extract` 会把 `delector/data/a1_workbench_dict.py` 从 **45 行**覆盖成 **764 行**生成物。

**为什么危险**：该文件实际是**手工维护的 membership 投影入口**（`ADR-0015 T2`，内容/身份单源在 `a1_sidecar` / `a1_fragments`），而工具 docstring 却写「该文件是**唯一真相**、禁止手工改」——**两处文档自相矛盾**。任何人跑一次 `--extract` 就会静默毁掉它（我在 C7 期间误触发过一次，已完整还原）。

**建议做法**（小改动，单独 PR）：
1. 让 `--extract` 默认**只打印 diff / 拒绝执行**，真写必须显式 `--i-know-this-overwrites`；
2. 校正 `tools/build_workbench_seed.py` 的 docstring（说明该文件是投影入口、`--extract` 仅供 bootstrap）；
3. 若可行，加一条守卫：`a1_workbench_dict.py` 若无 `from ... a1_sidecar` 导入则判定为被生成物覆盖 ⇒ 测试红。

**验收**：① 默认执行 `--extract` 时**不改写**该文件（贴 `git status` 空）；② 显式 flag 下才写；③ 新守卫用变异自证（删掉 a1_sidecar 导入 ⇒ 红）。

---

## 二、`doRate` 的评分分支无行为断言（**优先级中**）

**现象**：`static/js/wb-rate.js` 的 `doRate(...)` 有评分分支（`t.good++` / `t.hard++` / `t.again++`、`addWrong`），但**没有任何行为断言**覆盖它——C7 期间只为它加了「必须住在 `wb-rate.js`」的**静态所有权钉子**。

**为什么值得做**：这是「用户点评分 ⇒ 词条状态与错词本更新」的核心路径，回归会直接影响学习数据。

**建议做法**：仿 `tools/wb_queue_probe.mjs` 的形态加一个 node 探针（假 `t`/`addWrong`/DOM 桩，断言三个档位各自的自增与错词登记），并按 `tests/probe_wiring_guard.py` 的约定接线（每个 `.mjs` 必须被 witness）。

**验收**：① 新探针 `exit 0` 且被判据覆盖；② **变异自证**：把 `t.good++` 改成 `t.hard++` ⇒ 探针红；③ 全量用例数 **+N**（这是**新增行为覆盖**，与 C7 的守恒要求不同，需在 PR 里说明 +N 的正当性）。

---

## 已完成（C7 侧，供背景）

- PR #152（Task 1~6）→ `0b5758b`；PR #153（Task 5 剩余 5 块）→ `80dae6b`。
- 全量 **2352 passed / 3 skipped**（与拆分前逐字相同）；28 组变异自证；18 探针全绿；8 项门禁全绿。
- 接续笔记（含全部模板与陷阱）：`WORKMEMORY/notes/NOTES-2026-10-18-c7-blocks-resume.md`。

---

## 风险与坑

1. **别再跑 `--extract`**（在第一项修好之前）——这是本包存在的首要原因。
2. 两项都可独立 PR，**不要**混进同一个提交。
3. 第二项新增的是**行为用例**（非等价迁移），用例数会涨；本仓惯例要求 PR 里写明 +N 的理由。
4. 提交纪律：`git commit -F <file>`，禁 `-m`；禁 `--no-verify`；实现类必须走分支 + PR，不直推 master。
