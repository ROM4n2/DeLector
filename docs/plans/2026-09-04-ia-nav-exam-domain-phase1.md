# ADR-0005 首刀实施计划：备考域 IA 重布局（Phase 1）

> **Goal**: 按 ADR-0005 把 DeLector 前端从「场景工具混入 A1 考纲素材」重排为「场景工具 + 独立备考域（等级页签顶层、catalog 驱动）」，并落地目录/成绩第一刀，跑通 A1 全部练习在备考域内可用。
> **Tech Stack**: Python 3.11 FastAPI + SQLite（server.py/database.py）；原生 ES Modules 前端（index.html 单文件 SPA + main.js 根 module）；node:vm 探针（仿 tools/wb_sync_probe.mjs）
> **Spec Reference**: `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0005-navigation-exam-domain-and-level-scalability.md`
> **Global Constraints**:
> - **分支/PR 流程 (用户指令, MUST)**：基线上 **master @ v5.1.1**（已推送远端）。Task 0 建分支 `feat/ia-nav-exam-domain`；**本计划全部 commit 只落在该分支**，严禁直接写 master；收口 Task 5 push 分支并在远端开 PR（`gh pr create` 或网页）合入 master。
> - **范围边界**：本计划 = ADR §4 决策 1/2/3 的首刀（导航单源 + 备考域 + A1 四模块迁移 + catalog 目录第一刀 + 成绩泛化第一刀）。**不属于本计划**：听/读组件 level 参数化提取、写作判分提取、`/api/a1/*` 全量切 `/api/exams/{level}/{module}`、背词工作台 token 壳/词表契约——后述 §9 作为后继 sub-plan 触发点（建议 A2 立项或独立 short-plan 再排）。
> - **跨边界契约纪律 (MUST)**：任何端点/前端 body 契约变更配行为探针（node:vm 桩 fetch），单侧字符串存在断言不算数；需「退回旧实现必红」变异验证。
> - **字符串断言纪律 (MUST)**：搬 index.html 大 DOM 前先 grep 定位解析 index.html/main.js/a1_*.js 特征串的测试与 tools/*.mjs 探针，迁移同 commit 内同步特征串。
> - **DB 纪律**：改 database.py 函数用 try/finally + `conn.close()` 确定性关闭；迁移脚本防重入；测试隔离沿用 clean_db + `gc.collect()`，跑前设 `DATABASE_PATH` 防写真实 `delector.db`。
> - **提交约定**：`feat|fix|test|refactor|docs(ia): 中文描述`，每个 Task 原子提交。
> - **TDD**：每 Task Red→Verify Red→Green→Verify Green→Refactor→Commit。
> - 执行环境降级：本会话无写码子代理，`/vault-exec` 降级为「编排者主线程直写 + TDD」；Task 的 Subagent Prompt Scaffold 供有子代理环境或人工核对使用。

---

### Task 0: 建立分支与回归基线 [Role: Guard]

**Files:**
- 无源码改动。产出基线记录 `docs/plans/2026-09-04-ia-nav-exam-domain-phase1-ledger.md`。

**Interfaces:**
- Consumes: master @ v5.1.1；现有测试套件
- Produces: 分支 `feat/ia-nav-exam-domain`；基线测试报告（全量服务端 + 前端字符串/探针定向）

**Subagent Prompt Scaffold:**
> Implement Task 0: 建分支 + 回归基线。
> Goal: 在 v5.1.1 上开 `feat/ia-nav-exam-domain`，跑一次全量回归并记录通过/失败清单作为本计划基线。
> TDD Steps:
> 1. `git checkout -b feat/ia-nav-exam-domain v5.1.1` 并确认分支。
> 2. `export PYTHONIOENCODING=utf-8` 后跑服务端定向子集（a1/hoeren/lesen/cards/writer + 全量 TestClient 主套件），记录数量。
> 3. 跑依赖 index.html/main.js/workbench.html 特征串的字符串断言与 tools/*.mjs 探针，记录绿/红。
> 4. 把结果写入 ledger（含“迁移前绿、任务 X 迁移后必须仍绿”的断言清单）。
> Return: 分支名 + 基线通过计数 + 需在 Task 2/3 同步特征串的断言文件清单。

**Step Breakdown:**
- [ ] Step 1: `git checkout -b feat/ia-nav-exam-domain v5.1.1`
- [ ] Step 2: 服务端 + 前端字符串/探针回归，产出基线
- [ ] Step 3: 建 ledger 并登记「迁移敏感断言」清单
- [ ] Step 4: 原子 commit `docs(ia): Phase1 基线回归 + ledger`

---

### Task 1: 导航数据化 + 备考域骨架 [Role: Frontend TDD Builder]

**Files:**
- Modify: `static/js/main.js:150-215`（show/view 切换与点亮）、`static/index.html` 桌面 `nav#nav`(41-89)、移动 dock(2647-2696)
- Create: `static/js/nav.js`（NAV config 与双端渲染，仅被 main.js import）
- Modify: `static/index.html` view 区新增 `<main id="view-exam" class="view">`（置于 view-writer 之后，含等级页签条 `#exam-level-tabs` 与模块卡片区 `#exam-module-grid`）
- Test: 前端字符串断言所在测试文件（Task 0 定位）+ 新增特征断言

**Interfaces:**
- Consumes: `main.js show(view)`（view id → `.active`、nav-btn/mob-btn 点亮）
- Produces: `NAV_ITEMS=[{id,label,de,onclick}…]`（含 exam）；`renderNav()` 单源渲染桌面 `.nav-links` 与移动 `.mobile-dock`；`renderExamShell(levels)`（本 Task levels 常量 `['A1']`，模块卡片占位入口四张：写作/听力/阅读/口语）
- 语义约束：保留文案标识（SCHREIBTISCH/KARTEI/VOKABELN 及中文文案）以免字符串断言大面积失配；`show('exam')` 须点亮对应 nav/dock 按钮并允许 empty view 显示。

**Subagent Prompt Scaffold:**
> Implement Task 1: 导航数据化 + 备考域骨架。
> Goal: nav config 单源渲染桌面导航与移动 dock，新增「备考」入口与 view-exam 壳（A1 等级页签 + 四模块占位卡片），view 切换可进入。
> Target Files: Create `static/js/nav.js`；Modify `static/js/main.js` show()、`static/index.html` 导航两处 + 新增 view-exam 容器。
> TDD Steps:
> 1. RED：更新前端字符串断言（nav 出现「备考/Prüfung」入口；view-exam 容器存在；nav 双端渲染后原有五入口文案仍在）。
> 2. Verify Red：跑对应断言确认失败信息为“备考入口/容器缺失”。
> 3. GREEN：最小实现 nav.js + main.js 引入 + index.html 容器；nav 双端渲染。
> 4. REFACTOR：guard-clause 扁平化；nav config 与 view 初始化联动（show('exam') 无副作用）。
> 5. 跑 Task 0 登记的全量字符串/探针，确认除“新增入口”预期外无意外失配。
> 6. 原子 commit `feat(ia): 导航单源化并新增备考域骨架`。
> Return: 测试执行证据 + 遗留失配清单。

**Step Breakdown:**
- [ ] Step 1: nav.js NAV config + 双端渲染，index.html 增 view-exam（等级页签壳 + 4 占位卡片）(RED 测试先行)
- [ ] Step 2: 断言失配验证（仅“缺备考入口/容器”类）
- [ ] Step 3: show('exam') 联动与点亮；最小 GREEN
- [ ] Step 4: 跑全量字符串/探针回归，同步意外失配
- [ ] Step 5: REFACTOR 扁平化 + 原子 commit

---

### Task 2: A1 四模块 UI 迁入备考域 + 工具视图清理 [Role: Frontend TDD Builder — 高风险 DOM 迁移]

**Files:**
- Modify: `static/index.html`：
  - 删除 `view-writer` 内 A1 区：`.writer-mode-switcher-bar` A1 两按钮(944-970 内 a1 项)、`#a1-formular-view`(973-1037)、`#a1-email-view`(1040-1147)
  - 删除 `view-cards` 内 A1 tabs（含 a1-tab-teil2/teil3 等，Task 0 定位的精确行区间；口语问答数据面板）
  - 在 `view-exam` 内按模块挂 4 个面板容器：`exam-writing`（formular+email）、`exam-hoeren`、`exam-lesen`、`exam-sprechen`（teil2/teil3）——**DOM 从原 view 同 commit 内搬移，杜绝同 id 双现**
- Modify: `static/js/writer.js:7-29`（若 main.js 不再经 writer.js 导入 a1_writer，调整 re-export 但保留 window 挂载来源）、`static/js/main.js:146-147,726-892`（window 挂载聚合与 import，必要时改引用）、`static/js/cards.js:26-27`
- Create: `tools/ia_dom_mount_probe.mjs`（node:vm 切 index.html+main.js，桩 fetch，断言「a1 面板 DOM 存在于 view-exam、旧 view 内已无 a1 容器、A1Hoeren/A1Lesen window 挂载可达」）
- Test: 前端字符串断言测试 + 探针

**Interfaces:**
- Consumes: `window.A1Writer/A1Cards/A1Hoeren/A1Lesen`（a1_*.js 自挂 + main.js 聚合）；既有 `/api/a1/*` 端点（本 Task 不改后端契约，前端迁 UI 后仍调原端点取题）
- Produces: view-exam 内 4 面板；`view-writer`=纯 essay 工具（mode-switcher 移除）；`view-cards`=纯复习；探针新增并全绿
- 风险：a1 面板事件由渲染函数注入 `onclick="A1Hoeren.xxx()"`；迁移后 window 挂载必须保持。id 唯一性约束：迁移必须“同一次替换原子完成”。

**Subagent Prompt Scaffold:**
> Implement Task 2: A1 四模块 UI 迁入备考域 + 工具视图清理。
> Goal: A1 写作/听力/阅读/口语面板全部迁到 view-exam 对应容器，旧 view-writer/view-cards 移除 A1 区块；同 id 不得双现；window 挂载与事件注入不破；字符串断言同步。
> Target Files: Modify `static/index.html`（4 段搬移 + 旧区块删除）；Modify `static/js/{writer,cards,main}.js`；Create `tools/ia_dom_mount_probe.mjs`。
> TDD Steps:
> 1. RED：写 `ia_dom_mount_probe.mjs`——断言“view-exam 内存在 a1 面板、旧 writer/cards view 无 a1 容器、A1 window 挂载键存在”；先跑必红。
> 2. Verify Red：探针失败信息 = “新位置缺失 / 旧位置仍存在”。
> 3. GREEN：单次原子替换搬 DOM（先同 commit 里“新增 view-exam 副本 + 删除旧块”一次 diff 完成）；修 main.js/writer.js/cards.js 引用。
> 4. 全量字符串断言回归 + 探针绿；旧 view 清理（mode-switcher 移除 A1 项；cards A1 tab 移除）。
> 5. REFACTOR + 原子 commit `feat(ia): A1 四模块迁入备考域并清理工具视图`。
> Return: 探针输出 + 回归结果 + 任何仍调旧 UI 的引用清单。

**Step Breakdown:**
- [ ] Step 1: 探针 ia_dom_mount_probe.mjs（RED 必红）
- [ ] Step 2: index.html 原子搬移 4 面板（一次 diff：新容器插入 + 旧块删除），确保同 id 无双现
- [ ] Step 3: 修 js 引用/挂载，GREEN + 探针绿
- [ ] Step 4: 字符串断言回归；view-writer/view-cards 清理确认（纯工具语义）
- [ ] Step 5: 原子 commit（含探针文件）

---

### Task 3: exam catalog 目录化（数据模块注册 + catalog 端点 + 等级页签数据驱动）[Role: Backend TDD Builder]

**Files:**
- Create: `routes_exam.py`（`APIRouter(prefix="/api/exams")`，本 Task 仅 catalog 端点）；`exam_catalog.py`（等级目录注册表：`EXAM_CATALOG = {"A1": {"writing":{title,panel,api_prefix:"/api/a1"}, "hoeren":…, "lesen":…, "sprechen":…}, …}`；引用 `a1_writing_dict/a1_dict/a1_hoeren_dict/a1_lesen_dict` 的模块级常量并声明 `{level}_{module}` 归位别名）
- Modify: `server.py`（include exam router；若文件已按 M-split 组织则并入对应模块）——依现状 server.py:234 区 include
- Modify: `static/js/nav.js` 或新增 `exam.js`：Task1 的静态等级/卡片改由 `GET /api/exams/catalog` 渲染（A1 模块卡片的跳转锚 → 对应面板容器）
- Test: `test_exam_catalog.py`（catalog 返回等级 A1、模块含 writing/hoeren/lesen/sprechen；旧 `/api/a1/*` 取题端点照常可用——catalog 只提供导航/发现，**不迁移取题端点**）

**Interfaces:**
- Consumes: `a1_*_dict` 模块常量（词表/题库/题集元数据）；前端 view-exam 渲染
- Produces: `GET /api/exams/catalog → {levels:[{id,title,modules:[{id,title,type,panel}]}]}`；前端等级页签与模块卡片完全数据驱动
- 决策（相对 ADR 的实现细化，需用户点头）：**题库数据暂不入 SQLite**——catalog 是「代码注册目录」（`exam_catalog.py` 单源，未来 A2 = 追加 `A2` key + 数据模块），YAGNI 于题量级；ADR 的 `exam_sets/exam_items` 表留作“题库规模/服务端出题”触发后的升级路径；**成绩泛化表**才是本计划必落库项（Task 4）。

**Subagent Prompt Scaffold:**
> Implement Task 3: exam catalog 目录化。
> Goal: 新增 /api/exams/catalog 由代码注册目录 EXAM_CATALOG 提供等级→模块导航；前端备考域等级页签与卡片改由 catalog 渲染；旧 /api/a1 取题端点不动。
> Target Files: Create `routes_exam.py`, `exam_catalog.py`；Modify `server.py` include、前端等级页签渲染源。
> TDD Steps:
> 1. RED：`test_exam_catalog.py`（catalog 200，含 A1 与四模块；加「插一行 A2 注册 → catalog 多一级」的变异式断言证明扩展点）先跑必红。
> 2. GREEN：exam_catalog.py + routes_exam.py + server include。
> 3. 前端把 Task1 占位等级/卡片切到 fetch catalog 渲染（无 catalog 或失败时保留静态回退）。
> 4. 回归：a1 取题/判分端点子集全绿（确认未动旧契约）。
> 5. REFACTOR + 原子 commit `feat(ia): exam catalog 目录化驱动备考域导航`。
> Return: 测试证据 + “加级成本”演示（临时注册 A2 的 catalog 输出或注释说明）。

**Step Breakdown:**
- [ ] Step 1: test_exam_catalog.py RED（含 A2 扩展点变异断言）
- [ ] Step 2: exam_catalog.py + routes_exam.py + include GREEN
- [ ] Step 3: 前端等级页签/卡片数据驱动（静态回退兜底）
- [ ] Step 4: 旧端点回归全绿 + 原子 commit

---

### Task 4: 成绩表泛化第一刀 + 旧行迁移 [Role: DB TDD Builder]

**Files:**
- Modify: `database.py`：新增 `exam_trials(level,module,set_id,score_raw,score_official,details_json,created_at)`（init 建表处 ~database.py:94-105 邻近）；新增 `record_exam_trial()`/`get_exam_history(level,module)`；`record_a1_hoeren_trial`/`record_a1_lesen_trial`/`get_a1_hoeren_history`/`get_a1_lesen_history`（database.py:909-956）改为内部透传泛化函数并保留签名（**不删旧名**，避免前端/测试大面积契约变更）
- Modify: 一次性迁移函数 `migrate_a1_records_to_exam_trials()`：把 `a1_hoeren_records/a1_lesen_records` 存量行写入 exam_trials(level='A1')，防重入（存在则跳过）；旧表保留（读历史兼容期），不物理删除——ADR 语境下旧表退役放 Phase 2 端点切完再删
- Test: `test_exam_trials.py`（迁移后计数一致、字段映射正确、防重入幂等；新 trial 写入即读回；旧 record_a1_* 函数行为不变——透传契约）

**Interfaces:**
- Consumes: 既有 `record_a1_*_trial/get_a1_*_history` 调用方（routes_a1_hoeren/lesen 内部）
- Produces: `exam_trials` 表 + 泛化读写 + 幂等迁移；旧函数透传不破契约
- 风险：迁移 SQL 在 test clean_db 与真实库都要跑；沿用 `gc.collect()`/确定性 close 纪律；迁移函数幂等（重复跑无副作用）。

**Subagent Prompt Scaffold:**
> Implement Task 4: 成绩表泛化 + 旧行迁移。
> Goal: exam_trials(level,…) 泛化表上线；存量 a1_hoeren/a1_lesen 成绩幂等迁入；旧 record/get 函数透传泛化实现，契约不破。
> Target Files: Modify `database.py`；Create `test_exam_trials.py`。
> TDD Steps:
> 1. RED：test_exam_trials（写读回 + 旧函数行为保持 + 迁移幂等）。
> 2. GREEN：建表/函数/迁移；旧函数改透传。
> 3. 回归：routes_a1_hoeren/lesen 提交判分子集 + 历史读回全绿；`test_server` 受影响 `-k` 定向。
> 4. REFACTOR + 原子 commit `refactor(db): 成绩表泛化 exam_trials 并幂等迁移 A1 存量`。
> Return: 迁移幂等验证 + 定向回归证据。

**Step Breakdown:**
- [ ] Step 1: test_exam_trials RED（迁移幂等/旧函数透传/新写读回）
- [ ] Step 2: 泛化表 + 函数 + 幂等迁移 GREEN
- [ ] Step 3: 旧 record/get 透传；hoeren/lesen 提交与历史回归
- [ ] Step 4: 原子 commit

---

### Task 5: 收口：全量回归 + ledger + 分支上传 + PR [Role: Guard]

**Files:**
- Modify: `docs/plans/2026-09-04-ia-nav-exam-domain-phase1-ledger.md`（勾选全部 Step、记录偏差与证据）
- Modify（如适用）: 废弃/停用标注遗留 UI 或死按钮（若 Task 2 后出现不可达入口，走“禁用标注”而非静默保留）

**Interfaces:**
- Consumes: master 基线（Task 0 记录）
- Produces: 与基线对比的回归报告；已 push 分支 + PR

**Subagent Prompt Scaffold:**
> Implement Task 5: 收口回归 + 分支上传 + PR。
> Goal: 全量回归对比 Task 0 基线；ledger 回填勾选；push `feat/ia-nav-exam-domain` 到 origin；在远端开 PR 到 master（描述引用 ADR-0005，标题 `feat(ia): 备考域重布局 + catalog/成绩第一刀`）。
> Steps:
> 1. 服务端全量 + 前端字符串/探针定向回归，输出与基线差异表。
> 2. ledger 勾选 Task 0-4 Step + 偏差注记。
> 3. `git push -u origin feat/ia-nav-exam-domain`。
> 4. 开 PR：`gh pr create --base master` 可用则 CLI，否则给出网页链接与 PR 描述草稿（含测试证据、ADR-0005 引用、Phase 2 范围声明）。
> 5. commit `docs(ia): Phase1 ledger 收口 + PR 就绪`（在分支上）。
> Return: PR URL 或待开 PR 的完整描述。

**Step Breakdown:**
- [ ] Step 1: 回归差异表（对比 Task 0）
- [ ] Step 2: ledger 勾选/偏差注记
- [ ] Step 3: push 分支
- [ ] Step 4: PR 就绪（CLI 或草稿）
- [ ] Step 5: 文档 commit

---

## 9. 后继 sub-plan 触发点（不在本计划执行）

| 触发 | 内容 | ADR 引用 |
|---|---|---|
| A2 立项时 | 听/读组件 level 参数化提取（先听/读，写作判分延后）；`/api/a1/*` 全量切 `/api/exams/{level}/{module}`；旧 a1 端点与旧成绩表退役删除 | ADR-0005 §4.3 后续刀 |
| 独立 short-plan（可在本计划 PR 合并后随时启动） | 背词工作台视觉统一：共享设计 token（主站 `style.css` 暖纸 `--paper/--ink/--rule` 体系 vs workbench 冷灰 `--bg/--accent`——**色系冷暖相反且 token 名异构，需先出视觉小样定语义**，保留 good/hard/again 状态色）+ 词表来源契约 `vocab_cards.cefr_level` 过滤 | ADR-0005 §4.5/Q4C |

---

*计划 schema 依据 vault-plan；ADR 依据 vault-grill 共识（ADR-0005, status=proposed, 2026-09-04）。*
