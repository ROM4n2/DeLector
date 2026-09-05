# A2 词汇与全域背词系统扩展实施执行台账 (Ledger)

> **计划路径**：[`docs/plans/2026-09-05-a2-vocab-expansion-implementation-plan.md`](file:///d:/Code/DeLector/docs/plans/2026-09-05-a2-vocab-expansion-implementation-plan.md)
> **目标特性**：A2 词汇与全域背词系统扩展 (方案 B：全域贯通方案)
> **创建时间**：2026-09-05 16:35
> **基线状态**：pytest 全量 574 passed (109.26s)，Node.js 行为探针 10/10 全绿通过（含 13/13 处切片护栏 100% 保护）。

---

## 任务执行清单

| 任务序号 | 任务描述 | 责任角色 | 状态 | 关联提交 | 验证结果 |
|:---|:---|:---|:---|:---|:---|
| **Task 1** | A2 词汇格式化函数与数据契约扩展 (`database.py` + `test_a2_vocab_data.py`) | Backend TDD Builder | 完成 | `3344408` | `test_a2_vocab_data.py` 4 passed |
| **Task 2** | 服务端 A2 考纲端点与 Catalog 注册 (`routes_a2.py` + `exam_catalog.py` + `server.py`) | Backend TDD Builder | 完成 | `f7c7ef3` | `test_get_a2_vocab_endpoint` + catalog 7 passed |
| **Task 3** | 背词工作台 4 档范围扩展与 13 处切片护栏保护 (`workbench.html`) | Frontend TDD Builder | 完成 | `e09dc72` | 88 passed, `wb_queue_probe.mjs` 13/13 护栏通过 |
| **Task 4** | 备考域前端 A2 考纲词表与卡盒激活 (`main.js` & `a1_cards.js`) | Frontend TDD Builder | 完成 | `e95562c` | 39 passed, `ia_dom_mount_probe.mjs` 通过 |
| **Task 5** | 打包同步、回归闭环与台账归档 | Guard Subagent | 完成 | 待提交 | pytest 582 全绿 (137.53s), 10/10 探针全绿 |

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

### 1. pytest 全量测试回归验证
- **执行命令**：`python -m pytest -q`
- **验证结果**：`582 passed, 1 warning in 137.53s` (基线 574 -> 582, +8 个新契约测试，零失败、零回归)
- **新增契约测试**：
  - `test_a2_vocab_data.py` (4 passed): A2 974 词条全量提取、名词首字母大写与冠词拼装、动词/形容词小写与字段完整性。
  - `test_server.py::test_get_a2_vocab_endpoint` (1 passed): `GET /api/a2/vocab` 端点契约、结构完整性与查询过滤。
  - `test_exam_catalog.py` (更新 1 passed): Catalog 注册 A2 考纲词表模块与 974 题量推导。
  - `test_workbench_tokens.py` (1 passed): 工作台 `#scopeSeg` 4 档位与 `syncA2CardsFromServer` 绑定。
  - `test_german_workbench.py` (更新 2 passed): 顶栏 4 档位与全局单源契约验证。
  - `test_exam_domain.py` (2 passed): `test_exam_catalog_activates_a2_tab_interactivity` + `test_a1_cards_supports_a2_vocab_level`。

### 2. Node.js 10/10 动态行为探针验证
- **执行命令**：`Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }`
- **验证结果**：
  1. `ia_dom_mount_probe.mjs`: PASS (A1/A2 备考域容器挂载、旧视图干净、vm 沙箱渲染验证)
  2. `wb_clean_probe.mjs`: PASS
  3. `wb_pair_persist_probe.mjs`: PASS
  4. `wb_pair_push_probe.mjs`: PASS
  5. `wb_phone_pull_probe.mjs`: PASS
  6. `wb_phone_pull_silent_probe.mjs`: PASS
  7. `wb_queue_probe.mjs`: PASS (13/13 处关键代码切片护栏 100% 通过)
  8. `wb_rtc_connect_probe.mjs`: PASS
  9. `wb_rtc_reconnect_probe.mjs`: PASS
  10. `wb_sync_probe.mjs`: PASS

### 3. 打包注册守卫验证
- **执行命令**：`python -m pytest test_server.py -k test_all_backend_modules_registered_in_all_packaging_targets -q`
- **验证结果**：`1 passed, 225 deselected in 2.33s` (`routes_a2` 已正确登记在 `package_windows.py` 的 `--hidden-import` 中)。

