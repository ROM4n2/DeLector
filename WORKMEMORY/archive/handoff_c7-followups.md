---
to: any
from: codebuddy
created: 2026-10-18 13:10
closed: 2026-10-18 17:30
role: FIX | VERIFY
status: closed
---
# Handoff: C7 收尾的两项遗留（`--extract` 地雷 · `doRate` 行为覆盖）[CLOSED]

> C7（`workbench.html` 拆分）已全部交付并合并（PR #152 / #153，master `80dae6b`）。本包所含**两项独立、互不耦合**的遗留已全部交付并合并入 master（PR #155 / #156）。

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

## 响应与闭环记录 (2026-10-18)

两项遗留均已通过独立分支与 PR 交付并合入 master，全量测试与 CI 门禁全绿：

### 一、`--extract` 覆写护栏（PR #155 · commit `b1bff1f`）
1. `tools/build_workbench_seed.py`：默认执行 `--extract` 时检查目标 Python 模块是否存在，已存在时拒绝覆写并返回退出码 2；必须显式传入 `--i-know-this-overwrites` 护栏参数才允许覆写；校正模块 docstring 与 `_MODULE_HEADER`，消除自相矛盾说明。
2. `tests/test_a1_workbench_source.py`：
   - 新增 `test_a1_workbench_dict_is_projection_module_not_flat_literal_artifact` 守卫（变异自证通过：删掉 `from delector.data.a1_sidecar import` 即红）；
   - 新增 `test_extract_without_override_flag_refuses_to_overwrite_existing_module` 拒绝行为验证；
   - 新增 `test_extract_with_override_flag_proceeds_in_temp_dir` 护栏放行验证。
3. 验证：默认跑 `--extract` 退出码 2 且 `a1_workbench_dict.py` 字节未改；全量用例数 +3（2355 → 2358）。

### 二、`doRate` 行为覆盖动态探针与接线（PR #156 · commit `1cbc4f3`）
1. `tools/wb_rate_probe.mjs`：
   - 真实切取 `static/js/wb-rate.js` 中 `doRate(g)` 函数体（带 `t.good++` / `t.hard++` / `t.again++` / `addWrong` 等 token 切片护栏）；
   - 在 `node:vm` 沙箱中驱动测试 5 组真实行为场景（良好 3 累加/写盘、困难 2 复习卡累加、遗忘 1 错词登记、未翻面拦截、越界拦截）；
   - 输出标准三键契约 `{ failures, total, cases }`，通过 `test_probe_json_contract.py`；
   - 变异自证通过（改动评分分支逻辑，探针与测试立刻报红并精准指出失败场景）。
2. `tests/test_wb_rate_probe.py`：
   - 提供 pytest wrapper，接入 CI 流水线；
   - 通过 `test_probe_wiring_guard.py` 漏接线守卫。
3. 验证：全量用例数 +2（2358 → 2360），全套门禁全绿。
