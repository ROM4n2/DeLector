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

- [x] Step 1: 探针 ia_dom_mount_probe.mjs（RED 证据：exit 1 共 48 条问题 + pytest 9 failed）
- [x] Step 2: index.html 原子搬移（ledger 边界表；id 唯一性 7 关键 id 各恰 1 次）
- [x] Step 3: js 引用修改 + GREEN（a1CardsHost/setExamWritingTab/setExamModule/懒加载守卫；探针 4 场景绿）
- [x] Step 4: 测试同步（seg-a1→exam-card-vocab、writer-mode-a1-*→exam-tab-*）+ 全量探针 10/10 绿 + 537 passed
- [x] Step 5: 原子 commit `db80212`（评审 PASS：悬空标识符 165 handler 交叉核对/变异两向验证/no-op 防悬空）

**偏差注记**：
- 新增 main.js `setExamModule` mediator（页签⇄面板路由住根模块，因 a1_cards/a1_writer 互不 import）——计划未预见，评审认可。
- a1_cards.js 自管 view toggle（`a1ViewMode` + `setA1CardViewMode`）而非复用主站 setCardViewMode（避免双 toggle querySelector 冲突）——按计划「择简」授权。
- writer.js/cards.js 间 `export *` 转发链保留，cards.js 删自身 A1Cards import（转发达成后属死 import）。
- 评审 nit（不阻塞）：test_exam_domain.py:43 TOOL_VIEW_FORBIDDEN 死常量；探针 JSON 部分键为自报常量非测量值（真门禁在 problems[]）。

## Task 3: exam catalog 目录化

- [x] Step 1: test_exam_catalog.py RED（6 用例 collection error 必红；含 A2 扩展点变异 + count 防御）
- [x] Step 2: exam_catalog.py + routes_exam.py + include GREEN（count 数据推导 18/5/6/54/702）
- [x] Step 3: 前端 initExamCatalog 数据驱动（失败静态回退 + 幂等守卫 + show('exam') 惰性；新页签「待接入」标注防死按钮）
- [x] Step 4: 旧端点回归 6 passed + 定向 37 passed + commit `9ec0355`

**偏差注记**：
- panel 实测只有两个 section：exam-writing + exam-cards-family（听力/阅读/口语/词表共用宿主由 setA1Mode 切换）——catalog panel 字段按实测写，测试钉「panel 必须真实存在于 DOM」。
- 初轮评审 REVISE 两处已修：_safe_count 静默吞异常→logger.warning + caplog 钉死；_LEVEL_ORDER 死代码删。
- 评审 nit（已接线）：非静态新等级页签 no-op + aria-disabled + title「待接入」（v5.1.0 死按钮纪律）。

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
