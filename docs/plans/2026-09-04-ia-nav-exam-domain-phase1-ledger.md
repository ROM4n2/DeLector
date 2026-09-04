# ADR-0005 Phase 1 Ledger

> 计划：`docs/plans/2026-09-04-ia-nav-exam-domain-phase1.md`（修订版）。分支：`feat/ia-nav-exam-domain`。基线：master @ e2cc2a2 (v5.1.1)。

## Task 0: 分支 + 修复收编 + 基线 [Role: Guard]

- [x] Step 1: 建分支 `feat/ia-nav-exam-domain`（commit `2ae2bc2`：test 修复收编 + 计划入库）
- [x] Step 2: 全量 pytest 基线 + 前端定向基线
- [x] Step 3: 迁移敏感断言清单登记
- [x] Step 4: 原子 commit ledger

### 基线回归证据

| 套件 | 结果 |
|---|---|
| 前端定向（test_german_workbench + test_goethe_a1 + test_goethe_a1_writing + test_prep_matrix + test_frontend_module_graph） | 117 passed |
| wb_*.mjs 动态探针（9 个） | 全绿 |
| 全量 pytest | 518 passed (98.95s) |

### 迁移敏感断言清单（Task 2 同步项）

| 文件:行 | 断言 | 迁移后命运 |
|---|---|---|
| test_goethe_a1.py:128 | `id="seg-a1"` 存在 | **失效**——seg-a1 按钮删除，断言改为 exam 入口 |
| test_goethe_a1.py:129-133 | `a1-toolbar`/`a1-topic-pills`/`a1-tab-vocab|teil2|teil3` 存在 | id 不变，搬进 view-exam 后仍绿 |
| test_goethe_a1_writing.py:205-206 | `writer-mode-a1-formular/email` | **失效**——按钮改名 `exam-tab-formular/email`，测试同 commit 更新 |
| test_goethe_a1_writing.py:207-208 | `a1-formular-view`/`a1-email-view` | id 不变，搬进 view-exam 后仍绿 |
| test_german_workbench.py:71-73 | `nav-btn-german`/`mob-btn-german` 顺序 | 不动（静态加按钮方案），天然绿 |
| test_german_workbench.py:64 | `view-german` 块 split | view-exam 置于 view-german **之前**，不破 split |
| test_writer_mobile.py:415 | show() 调 closeWriterMobilePanel | 不动，天然绿 |
| test_frontend_module_graph.py:358-368 | main.js 必须 star-import + exposer A1Hoeren/A1Lesen | DOM 迁移不改挂载，天然绿 |

### index.html 搬移边界（执行精确锚点）

| 区块 | 行区间 | 去处 |
|---|---|---|
| writer mode 按钮条（essay 外两项） | 944-970（删 a1 两按钮，保留 essay） | view-exam `exam-writing` 头部 |
| `#a1-formular-view` | 973-1037 | view-exam `exam-writing` |
| `#a1-email-view` | 1040-1146 | view-exam `exam-writing` |
| cards `seg-a1` 按钮 | 305-316 | **删除**（备考域入口替代） |
| cards `a1-toolbar` 整块 | 379-433 | view-exam `exam-vocab` 头部 |
| cards `a1-hoeren-container`/`a1-lesen-container` | 436-437 | view-exam `exam-hoeren`/`exam-lesen` |
| view-exam 新建 | — | view-german(:2637) 之前 |

（边界行号基于 v5.1.1 工作区，Task 2 执行时以 grep 重定位为准。）

## Task 1: 备考域骨架 + 静态导航入口

- [x] Step 1: RED 测试（test_exam_domain.py 11 条，RED 证据 FFFFFFFFFFF）
- [x] Step 2: index.html 静态双端按钮 + view-exam 壳（纯插入 +110 行）
- [x] Step 3: GREEN + 定向回归 128 passed（基线 117 + 新增 11）
- [x] Step 4: 原子 commit `692e8ea`（评审 PASS：纯插入零删除/断言防恒真切片/配平验证）

## Task 2: A1 五模块迁入备考域

- [ ] Step 1: 探针 ia_dom_mount_probe.mjs（RED 必红）
- [ ] Step 2: index.html 原子搬移（上表边界）
- [ ] Step 3: js 引用修改 + GREEN
- [ ] Step 4: 测试同步（上表失效项）+ 全量探针回归
- [ ] Step 5: 原子 commit

## Task 3: exam catalog 目录化

- [ ] Step 1: test_exam_catalog.py RED（含 A2 扩展点变异）
- [ ] Step 2: exam_catalog.py + routes_exam.py + include GREEN
- [ ] Step 3: 前端页签/卡片 catalog 渲染（静态回退）
- [ ] Step 4: 旧端点回归 + commit

## Task 4: exam_trials 泛化表

- [ ] Step 1: test_exam_trials.py RED（幂等/透传/备份往返）
- [ ] Step 2: 表 + 函数 + 迁移 + _PROGRESS_TABLES + RestoreReq GREEN
- [ ] Step 3: routes_a1_hoeren/lesen 回归
- [ ] Step 4: commit

## Task 5: 收口

- [ ] Step 1: 全量回归差异表
- [ ] Step 2: ledger 回填
- [ ] Step 3: push
- [ ] Step 4: PR
- [ ] Step 5: docs commit
