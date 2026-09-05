# 仓库根目录扁平化 · Phase 1 实施计划（测试归位 + 杂物清场）

> **Goal**: 把根目录 27 个测试收进 `tests/`、删除过时 `HANDOFF.md`、把 orphan 的 `front.jpg` 归位 `static/`、物理清掉 gitignore 已覆盖的构建/缓存/数据库残留——零功能风险的一次性整理。
> **Tech Stack**: Python 3.11（仅文件重组 + 路径常量修正，无新运行时逻辑）
> **Spec Reference**: 仓库结构现状清单（2026-09-05 会话产出）；Phase 2（业务模块收进 `delector/` 包）单独立项，不在本计划。
> **Global Constraints**:
> - 版本面五件套不涉及（无发版）。
> - 红绿验证用根目录 `pytest -v`（与 CI `.github/workflows/build-release.yml` 调用一致）。
> - 本环境无写码子代理：`Subagent Prompt Scaffold` 仅作模板，实际由主线程直写 + TDD + 每 Task 原子提交。
> - `rm` 触发 safe-delete 守卫：物理清理用 `git rm`（已跟踪）或留作未跟踪文件并明示（gitignore 覆盖项）。
> - 移动文件**必须保留 git 历史** → 用 `git mv`，禁止 `cp`+`rm`。
> - 含 `__file__` 相对根读取的测试 **不能直接 `git mv`**，必须先修正路径再移动（见 Task 4/5/6）。

---

### Task 0: 预检与基线采集 [Role: TDD Builder]

**Files:**
- Read: 根目录 27 个 `test_*.py` 中 `__file__` 用法的精确行号（重点 `test_server.py`、`test_source_hygiene.py`）
- Read: `.github/workflows/build-release.yml`（确认 `pytest -v` 调用方式，已确认）
- Test: （无新测试）采集全量基线

**Interfaces:** Consumes: 现有 `pytest` 发现机制 / Produces: 基线 passed 总数 + 待改路径文件清单

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 0: 预检与基线。Goal: 拿到移动前的全量测试绿底数与含 `__file__` 的精确行号。Target: 运行 `pytest -v` 记录 passed 总数；`grep -n '__file__' test_*.py` 输出每个文件的行号清单。Return: 基线数字 + 清单文本。"

**Step Breakdown:**
- [ ] **Step 1: 跑全量 `pytest -v`**，记录基线 passed 总数（用于 Task 11 对比，回归即用红）。
- [ ] **Step 2: `grep -rn '__file__' test_*.py`**，列出每个含 `__file__` 文件及行号（已知 13 个，见 Global 备注）。
- [ ] **Step 3: 确认根目录无 `conftest.py`**（移动后需新建，Task 2）。
- [ ] **Step 4: 写 `docs/plans/2026-09-05-root-flatten-phase1-precheck.md`** 记录基线数字与待改行号表，commit。

---

### Task 1: 根 `conftest.py` 注入 sys.path + REPO_ROOT [Role: TDD Builder]

**Files:**
- Create: `conftest.py`（仓库根）
- Test: 临时 `tests/_smoke_import_server.py`（验证用，Task 3 后可删）

**Interfaces:** Consumes: 无 / Produces: `sys.path` 前置根目录，使 `tests/` 下 `import server` 等扁平模块可用；暴露 `REPO_ROOT = Path(__file__).parent`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 根 conftest。Goal: 让 tests/ 下测试能 import 根目录扁平模块。Target: Create 根 `conftest.py`，`sys.path.insert(0, str(Path(__file__).parent))` + `REPO_ROOT = Path(__file__).parent`。Test: 建 `tests/_smoke_import_server.py` 写 `from server import app; assert app` (RED if path wrong)。Run `pytest tests/_smoke_import_server.py`，GREEN 后保留该文件作回归哨兵（或 Task 11 删）。Return: 测试证据。"

**Step Breakdown:**
- [ ] **Step 1: 写失败哨兵** `tests/_smoke_import_server.py`：`import server` + `assert server.app`（此时 tests/ 不存在，RED）。
- [ ] **Step 2: 建 `conftest.py`** 注入 sys.path（GREEN）。
- [ ] **Step 3: 跑哨兵验证 GREEN。**
- [ ] **Step 4: 原子 commit**（`conftest.py` + 哨兵）。

---

### Task 2: 低风险测试 `git mv`（不含 `__file__` 的 14 个）[Role: TDD Builder]

**Files:**
- Move (git mv): 以下 14 个根 `test_*.py` → `tests/`：
  `test_a2_vocab_data.py`、`test_audit_regressions.py`、`test_corpus.py`、`test_core_dict_ext.py`、`test_dict_pipeline.py`(⚠见注)、`test_edge_tts_mini.py`、`test_essay_diff.py`、`test_exam_trials.py`、`test_frontend_module_graph.py`、`test_goethe_a1.py`、`test_goethe_a1_hoeren.py`、`test_goethe_a1_lesen.py`、`test_start.py`、`test_syntax_tree.py`、`test_writing_rules.py`
  （注：上述为不含 `__file__` 的候选；若 Task 0 grep 显示某文件其实含 `__file__`，挪到 Task 4。）

**Interfaces:** Consumes: 根 `conftest.py` / Produces: `tests/` 下 14 个测试模块

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 低风险测试搬家。Goal: git mv 14 个不含 __file__ 的测试到 tests/。Target: `git mv <f> tests/` 逐个执行。TDD: 每移完一批跑 `pytest tests/<f>` 确认 GREEN（靠 conftest 注入的 import）。Return: 每个文件移动后绿的证据。"

**Step Breakdown:**
- [ ] **Step 1: `git mv`** 逐个移到 `tests/`（保留历史）。
- [ ] **Step 2: 跑 `pytest tests/`** 确认这批全 GREEN（import 解析正常）。
- [ ] **Step 3: 原子 commit**（这批移动）。

---

### Task 3: 含 `__file__` 测试的 `git mv` + 路径修正（除 test_server / test_source_hygiene）[Role: TDD Builder]

**Files:**
- Move + Modify: 以下 11 个（均含 `__file__` 相对根读取）：
  `test_writer_mobile.py`、`test_workbench_tokens.py`、`test_prep_matrix.py`、`test_grammatik_radar.py`、`test_goethe_a1_writing.py`、`test_german_workbench.py`、`test_frontend_security.py`、`test_exam_domain.py`、`test_exam_catalog.py`、`test_dict_pipeline.py`、`test_audit_hardening.py`
- 每文件把 `os.path.dirname(__file__)`（用于读 `server.py`/`static/`/`tools/`/`.github/`/`android/` 等）改为 `os.path.dirname(os.path.dirname(__file__))`；或顶部定义 `ROOT = Path(__file__).resolve().parent.parent` 并替换。

**Interfaces:** Consumes: 根 `conftest.py` / Produces: `tests/` 下 11 个测试，路径回指仓库根

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 含 __file__ 测试搬家+改路径。Goal: 11 个测试移 tests/ 且相对根读取仍正确。Target: 每文件 grep `__file__`，凡读取仓库资源的 `dirname(__file__)` 改为 `dirname(dirname(__file__))` 或统一 `ROOT=parent.parent`。TDD: 每改完一个 `git mv` 一个，跑 `pytest tests/<f>` GREEN 再下一个。Return: 逐文件证据。"

**Step Breakdown:**
- [ ] **Step 1: 逐文件** 定位 `__file__` 行，判断读取目标是仓库资源还是测试兄弟文件。
- [ ] **Step 2: 改路径**（仓库资源 → `parent.parent`；测试兄弟 → 保持 `dirname(__file__)` 或相对调整）。
- [ ] **Step 3: `git mv`** 到 `tests/`。
- [ ] **Step 4: 跑 `pytest tests/<f>`** GREEN（尤其 `test_german_workbench.py` 的 static HTML first-occurrence 解析不能破）。
- [ ] **Step 5: 原子 commit**（这批）。

---

### Task 4: `test_server.py` 路径修正 + 移动 [Role: TDD Builder / 最高风险]

**Files:**
- Modify: `test_server.py`（28 处 `os.path.dirname(__file__)` 读 `server.py`/`static/`/`tools/`/`.github/`/`android/`/`.githooks/`/`.gitignore`/`nlp.py` 等）
- Move (git mv): `test_server.py` → `tests/`

**Interfaces:** Consumes: 根 `conftest.py` / Produces: `tests/test_server.py`，全部相对根路径回指正确

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: test_server 搬家（最高风险）。Goal: 28 处 __file__ 改 parent.parent 后移 tests/。Target: 顶部加 `HERE=Path(__file__).resolve().parent; ROOT=HERE.parent`，全局替换 `os.path.dirname(__file__)` 读仓库资源处为 `ROOT`（注意：读兄弟测试临时文件的保持 HERE）。TDD: 改完跑 `pytest tests/test_server.py -k 'static or gradle or hook'` 抽样 GREEN，再全量。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: 读 Task 0 行号表**，逐处判定（仓库资源 vs 测试内临时文件 `test_delector.db` 等——后者留 `dirname(__file__)`）。
- [ ] **Step 2: 替换** 仓库资源处为 `ROOT`；临时文件处保持 `HERE`。
- [ ] **Step 3: `git mv`** 到 `tests/`。
- [ ] **Step 4: 抽样 `pytest tests/test_server.py -k 'static or gradle or hook or backup'`** GREEN。
- [ ] **Step 5: 原子 commit**（单独，便于 bisect）。

---

### Task 5: `test_source_hygiene.py` ROOT 修正 + 移动 [Role: TDD Builder]

**Files:**
- Modify: `test_source_hygiene.py:17` `ROOT = Path(__file__).parent` → `Path(__file__).parent.parent`；`_SKIP_DIRS` 增 `"tests"`（避免扫测试自身 dict 字面量噪音，保持只审业务代码语义）。
- Move (git mv): `test_source_hygiene.py` → `tests/`

**Interfaces:** Consumes: 无 / Produces: `tests/test_source_hygiene.py` 仍全仓扫重复键

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: test_source_hygiene 搬家。Goal: 移动后卫生棘轮不漏扫。Target: 改 ROOT=parent.parent，_SKIP_DIRS 加 'tests'。TDD: 跑 `pytest tests/test_source_hygiene.py` 确认 offenders 列表与移动前一致（对比 Task 0 基线，应为 0）。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: 改 `ROOT` 与 `_SKIP_DIRS`。**
- [ ] **Step 2: `git mv`** 到 `tests/`。
- [ ] **Step 3: 跑测试** 确认结果 == Task 0 基线（0 offenders）。
- [ ] **Step 4: 原子 commit**。

---

### Task 6: 删除过时 `HANDOFF.md` [Role: TDD Builder]

**Files:**
- Delete: `HANDOFF.md`（11KB，2026-09-02 生成，HEAD 停 v5.0.1、基线 451，已被 `WORKMEMORY/PROJECT_OVERVIEW.md` 覆盖）

**Interfaces:** Consumes: 无 / Produces: 无（删除冗余文档）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: 删 HANDOFF.md。Goal: 移除过时交接卡。Target: `git rm HANDOFF.md`。TDD: grep 全仓确认无其他文件引用 HANDOFF.md（已知仅 docstring/历史提及，无硬依赖）。Return: grep 证据。"

**Step Breakdown:**
- [ ] **Step 1: `grep -rn 'HANDOFF' --include='*.py' --include='*.md'`** 确认无运行期依赖。
- [ ] **Step 2: `git rm HANDOFF.md`。**
- [ ] **Step 3: 原子 commit。**

---

### Task 7: `front.jpg` 归位 `static/` [Role: TDD Builder]

**Files:**
- Move (git mv): `front.jpg` → `static/front.jpg`

**Interfaces:** Consumes: 无 / Produces: `static/front.jpg`（全仓 0 引用，移动无行为影响；安卓真实封面在 `res/mipmap/ic_launcher`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 7: front.jpg 归位。Goal: 把 orphan 封面图移入 static/。Target: `git mv front.jpg static/front.jpg`。TDD: `grep -rn 'front.jpg'` 全仓 0 匹配，确认无引用破坏。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: `grep -rn 'front.jpg'`** 确认 0 引用。
- [ ] **Step 2: `git mv front.jpg static/front.jpg`。**
- [ ] **Step 3: 原子 commit。**

---

### Task 8: 物理清理 gitignore 已覆盖的残留 [Role: TDD Builder]

**Files:**
- Delete (物理, gitignore 已忽略，不入版本库):
  `artifact*.html` ×4、`delector.db`、`progress.db`、`probe_fsrs.db`、`probe_fsrs_progress.db`、`test_snap.db`、`test_tmp.db`、`test_tmp_p.db`、`build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`.cache/`

**Interfaces:** Consumes: `.gitignore` 规则 / Produces: 干净工作树（上述本就不入库）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 8: 清理已忽略残留。Goal: 删掉 gitignore 覆盖的构建/缓存/db 残留。Target: 对未跟踪项直接删（safe-delete 守卫可能拦截 rm → 改 `git clean -fdxn` 预览后 `git clean -fdx` 谨慎执行，或逐个删并明示）。TDD: 删后 `git status` 应只剩本次有意改动，无意外。Return: git status 证据。"

**Step Breakdown:**
- [ ] **Step 1: `git status --ignored`** 列出确实被忽略的项，核对清单。
- [ ] **Step 2: 删除**（用 `git clean -fdx` 或逐个 `rm`；守卫拦截则留未跟踪并明示用户）。
- [ ] **Step 3: 不单独 commit**（物理清理不进版本库，随 Task 11 工作树收尾）。

---

### Task 9: 更新文档指向（AGENTS / PROJECT_OVERVIEW 测试清单）[Role: TDD Builder]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（测试位置说明 → `tests/`）、`AGENTS.md`（若含测试清单行）、`README.md`（若有 `test_*.py` 行内注释指向，如 276/278 行）
- Modify: `docs/agents/architecture.md` / `ops.md`（若提及根目录测试布局）

**Interfaces:** Consumes: 移动后的 `tests/` 结构 / Produces: 文档与现状一致

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 9: 文档同步。Goal: 文档里测试位置指向 tests/。Target: grep 'test_*.py' 在 md 中，改为 'tests/test_*.py' 或 'tests/'。TDD: 无自动化测试，人工核对后 commit。"

**Step Breakdown:**
- [ ] **Step 1: `grep -rn 'test_.*\.py' --include='*.md'`** 列出需改处。
- [ ] **Step 2: 改路径指向。**
- [ ] **Step 3: 原子 commit。**

---

### Task 10: 收尾验证 + 原子提交 [Role: TDD Builder]

**Files:**
- Verify: 全量 `pytest -v`（根目录，等同 CI）
- Commit: Phase 1 总收口（若前面已分 commit，此处仅补遗漏；建议保留 Task 1-9 各原子 commit，本 Task 只跑最终验证）

**Interfaces:** Consumes: 全部已移动测试 / Produces: 绿证明 + 工作树干净

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 10: 收尾验证。Goal: 确认移动后全量测试 == Task 0 基线。Target: 根目录 `pytest -v`，对比 passed 总数；`git status` 干净。Return: 对比表。"

**Step Breakdown:**
- [ ] **Step 1: 全量 `pytest -v`**，passed 总数 == Task 0 基线（回归即 RED，回查对应 Task）。
- [ ] **Step 2: `git status`** 确认无遗漏/无意外未跟踪。
- [ ] **Step 3: 若前面未逐 Task commit，此处补总 commit；否则仅记录验证证据。

---

## Phase 3: 下游执行

计划已生成（含 Subagent Prompt Scaffold 模板）。**本环境无写码子代理**，`vault-exec` 降级为「主线程直写 + TDD + 每 Task 原子提交」，Scaffold 仅作步骤参照。

回复 **「执行 Phase 1」** 即按 Task 0→10 顺序开始（Task 0 先采基线，Task 4 `test_server.py` 为最高风险单独立项）。Phase 2（业务模块收进 `delector/` 包）不在此计划，单独立项。
