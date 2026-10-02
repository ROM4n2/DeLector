# 后端业务模块收包 · Phase 2 实施计划

> **Goal**: 把根目录 26 个业务模块收进 `delector/` 包，根目录只留入口与工具，同时保证「数据目录 / 静态资源 / 打包清单 / Android 拷贝」四处语义完全不变。
> **Tech Stack**: Python 3.11（PyInstaller 桌面 + Chaquopy Android）
> **Spec Reference**: 仓库结构现状清单（2026-09-05）；Phase 1（测试归位 `tests/` + 根 `conftest.py`）已完成并落地 8 个 commit
> **Global Constraints**:
> - **平铺方案**：只加包层级，**不改文件名、不建子包**（`delector/routes_a1.py`、`delector/core_dict.py`…）。控风险优先；子包化（`delector/routes/`、`delector/dicts/`）与重命名列为 Phase 2b，单独立项。
> - **绝对 import**：包内统一 `from delector.xxx import ...`，不用相对 import（PyInstaller / Chaquopy / tools / tests 四处行为一致）。
> - **数据目录语义必须等价**：`DATA_DIR` 默认值迁移前后都必须是「仓库根」，不得变成 `delector/`（否则 `delector.db` / `progress.db` 搬家，用户数据表现为全部消失）。
> - 根目录保留：`start.py`（入口）、`package_windows.py`（打包工具）、`conftest.py`（pytest 需要，注释里「Phase 2 后可删」是错的，本次一并更正）。
> - 本环境未挂载 Coding Vault（无 `omni_search` / `get_code_template`），且**无写码子代理**：`Subagent Prompt Scaffold` 仅作模板，实际主线程直写 + TDD + 每 Task 原子提交。
> - 全量 `pytest` 会触发 safe-delete 守卫（pytest 清自己的临时目录，累计 >750 文件），统计行拿不到时**用进度条点数推算**（每行 72 个点）。
> - APK 真机验证挂下次发版；本地只做全量 pytest + 可选 PyInstaller 烟测。

---

## 已侦查确定的风险面（执行前必读）

| 点 | 位置 | 风险 | 处置 |
|---|---|---|---|
| **数据目录** | `database.py:21` `DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", os.path.dirname(__file__))` | 进包后 `dirname(__file__)` 变 `delector/` → **桌面端 db 整体搬家**（Android 有 `MainActivity:341` 注入环境变量，不受影响） | Task 3 修正为回指一级 + Task 0 加守卫测试钉住 |
| 静态资源 | `server.py:2405` `os.path.join(os.path.dirname(__file__), "static")` | 进包后指向 `delector/static`（不存在），靠 CWD 兜（桌面 CWD=根侥幸命中，Android 靠 `STATIC_DIR` 环境变量） | Task 5 显式加回退项，不依赖 CWD |
| 工作台 HTML | `database.py:1082` `dirname(__file__)/static/german/workbench.html` | 同上，路径错位 | Task 3 一并修正 |
| `nlp.py:53` | `Path(module.__file__).parent` | **不受影响**（`module` 是 spaCy 模型模块，不是本仓库文件） | 不动 |
| 打包清单 | `package_windows.py:59-75`、`.github/workflows/build-release.yml:95-110 / 171-186` | 3 处 `--hidden-import=扁平名` 全部失效 | Task 8 统一加 `delector.` 前缀 |
| Android 拷贝 | `build-release.yml:245` 逐个 `cp` 26 个 .py | 扁平清单失效；且**当前漏了 `routes_a2.py`**（既有缺陷） | Task 8 改整目录 `cp -r delector start.py`，顺带修复 |
| APK 校验 | `build-release.yml:382` `APP_NEEDLES` | 子串匹配仍命中 `delector/server.py`，但应更新为包路径更严谨 | Task 8 |
| 断言测试 | `test_server.py:1713 / 3830 / 3851` | 断言 `--hidden-import=core_dict` 等扁平名 | Task 9 |
| tools | `tools/build_dict.py:45-46`、`tools/build_prep.py:49` | import `core_dict` / `linguistics`（含 `sys.path` hack） | Task 6 |
| 测试 | 9 个测试 `import server` / `from server import` | 改 `from delector import server` | Task 7 |

---

### Task 0: 预检与守卫测试（钉住数据目录与静态资源语义）[Role: TDD Builder]

**Files:**
- Create: `tests/test_backend_package_layout.py`
- Read: `database.py:21` / `server.py:2401-2411` / `build-release.yml:245,382`

**Interfaces:** Consumes: `database.DATA_DIR`、`server.STATIC_DIR` / Produces: 两条迁移守卫

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 0: 预检守卫。Goal: 在动手迁移前先钉住「DATA_DIR / STATIC_DIR 必须指向仓库根」这一语义，让后续任何一步改错立刻变红。Target: Create `tests/test_backend_package_layout.py`，两条断言：①`Path(database.DATA_DIR).resolve() == REPO_ROOT`（若 `DELECTOR_DATA_DIR` 已设置则 skip）；②`server.STATIC_DIR` 解析到 `REPO_ROOT/static` 且该目录含 `index.html`。Run `pytest tests/test_backend_package_layout.py -q`，迁移前应为 GREEN。Return: 测试证据。"

**Step Breakdown:**
- [ ] **Step 1: 写守卫测试**（两条，迁移前应为绿）。
- [ ] **Step 2: 跑 `pytest tests/test_backend_package_layout.py -q`** 确认 GREEN。
- [ ] **Step 3: 记录全量基线**（当前 583 passed）。
- [ ] **Step 4: 原子 commit**（只加测试，不改生产代码）。

---

### Task 1: 建 `delector/` 包 + 迁数据/词典层（叶子模块）[Role: TDD Builder]

**Files:**
- Create: `delector/__init__.py`
- Move (git mv): `core_dict.py` `core_dict_ext.py` `a1_dict.py` `a1_hoeren_dict.py` `a1_lesen_dict.py` `a1_writing_dict.py` `corpus_dict.py` `prep_dict.py` → `delector/`
- Modify: `nlp.py:14-15`、`writing_rules.py:9`、`exam_catalog.py:17-20`、`routes_a1.py:12-13`、`routes_a1_hoeren.py:10`、`routes_a1_lesen.py:10`、`routes_corpus.py:8`、`server.py:228`（改 `from delector.xxx import`）

**Interfaces:** Consumes: 原扁平 `import core_dict` / Produces: `from delector.core_dict import ...`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 建包并迁词典数据层。Goal: 8 个零内部依赖的词典模块进 delector/，且所有引用者改用包路径。Target: Create `delector/__init__.py`；git mv 8 个 dict 模块；全局把 `import core_dict` / `from core_dict import` 改为 `from delector.core_dict import`（注意 `import xxx` 形式要改成 `from delector import xxx`）。TDD: 先跑 `pytest tests/test_dict_pipeline.py tests/test_a2_vocab_data.py -q` 拿绿基线，迁完再跑必须仍绿。Return: 前后对比证据。"

**Step Breakdown:**
- [ ] **Step 1: 跑受影响测试**拿绿基线。
- [ ] **Step 2: `git mv`** 8 个模块进 `delector/` + 建 `__init__.py`。
- [ ] **Step 3: 改全部引用者**的 import 为 `delector.` 前缀。
- [ ] **Step 4: 跑测试**确认绿（RED 则回查遗漏的 import）。
- [ ] **Step 5: 原子 commit。**

---

### Task 2: 迁算法层 [Role: TDD Builder]

**Files:**
- Move: `syntax_tree.py` `security.py` `linguistics.py` `writing_rules.py` `essay_diff.py` `edge_tts_mini.py` `nlp.py` → `delector/`
- Modify: `database.py:19`、`server.py:103,114,229-231`、`essay_diff.py:8`、`nlp.py:14-15`、`routes_a1.py:15`、`writing_rules.py:9` 等的内部 import

**Interfaces:** Consumes: 扁平算法模块 / Produces: `delector.syntax_tree` 等

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 迁算法层。Goal: 7 个算法模块进 delector/。Target: git mv；把所有 `from syntax_tree import` / `from nlp import` / `from security import` / `from linguistics import` / `from writing_rules import` / `from essay_diff import` 改成 `delector.` 前缀（含 server.py 与模块相互引用）。注意 `database.py:19` 也 import 了 nlp。TDD: 迁前跑 `pytest tests/test_syntax_tree.py tests/test_writing_rules.py tests/test_essay_diff.py -q` 拿基线，迁后必须一致。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: 基线**（受影响测试）。
- [ ] **Step 2: `git mv`** 7 个模块。
- [ ] **Step 3: 改 import**（含相互引用与 server.py）。
- [ ] **Step 4: 跑测试**确认绿。
- [ ] **Step 5: 原子 commit。**

---

### Task 3: 迁 `database.py` 并修正 DATA_DIR（最高风险）[Role: TDD Builder]

**Files:**
- Move: `database.py` → `delector/database.py`
- Modify: `delector/database.py:21`（`DATA_DIR` 回指一级）、`:1082`（workbench.html 路径回指一级）、`:19`（`from delector.nlp import`）
- Modify: 所有 `from database import ...` 的引用者（`server.py:45`、`exam_catalog.py:21`、`routes_a1.py:14`、`routes_a1_hoeren.py:15`、`routes_a1_lesen.py:15`、`routes_a2.py:8`、`routes_rtc.py:19`、`routes_sync.py:14`）

**Interfaces:** Consumes: `database.DATA_DIR` 当前语义（= 仓库根）/ Produces: 迁移后 `DATA_DIR` 仍 = 仓库根

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 迁 database 并保住数据目录语义（最高风险）。Goal: database.py 进 delector/ 后 DATA_DIR 仍然指向仓库根。Target: git mv；把 `os.path.dirname(__file__)` 的两处（21 行 DATA_DIR、1082 行 workbench.html）改为回指一级（`os.path.dirname(os.path.dirname(__file__))`）；所有引用者改 `from delector.database import`。TDD: Task 0 的 `test_backend_package_layout.py::test_data_dir_defaults_to_repo_root` 在不修正时会 RED（这正是要看到的），修正后 GREEN。额外验证：`python -c "import delector.database as d; print(d.DATA_DIR)"` 打印的是仓库根而非 delector/。Return: 打印输出 + 测试证据。"

**Step Breakdown:**
- [ ] **Step 1: 跑 Task 0 守卫**确认当前绿。
- [ ] **Step 2: `git mv` database.py。**
- [ ] **Step 3: 改引用者 import。**
- [ ] **Step 4: 修正 21 行与 1082 行**（回指一级），加注释说明为什么不能再用 `dirname(__file__)`。
- [ ] **Step 5: 跑守卫 + 全量相关测试**确认绿，并打印 `DATA_DIR` 实证。
- [ ] **Step 6: 原子 commit。**

---

### Task 4: 迁 `exam_catalog.py` 与 8 个 routes [Role: TDD Builder]

**Files:**
- Move: `exam_catalog.py` `routes_a1.py` `routes_a2.py` `routes_a1_hoeren.py` `routes_a1_lesen.py` `routes_corpus.py` `routes_sync.py` `routes_rtc.py` `routes_exam.py` → `delector/`
- Modify: `server.py:232-239`（全部改 `from delector.routes_a1 import router as a1_router` 等）

**Interfaces:** Consumes: 扁平 routes / Produces: `delector.routes_*`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 迁 exam_catalog 与 8 个 routes。Goal: 路由层进包。Target: git mv 9 个模块；`server.py:232-239` 的 9 行 import 全改 `delector.` 前缀；routes 之间与对 database/dicts/exam_catalog 的引用同样改。TDD: 迁前跑 `pytest tests/test_exam_catalog.py tests/test_exam_domain.py tests/test_exam_trials.py -q` 拿基线，迁后必须一致。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: 基线。**
- [ ] **Step 2: `git mv`** 9 个模块。
- [ ] **Step 3: 改 import**（含 server.py 与 routes 互引）。
- [ ] **Step 4: 跑测试**确认绿。
- [ ] **Step 5: 原子 commit。**

---

### Task 5: 迁 `server.py` + 修 static 回退链 + 改 `start.py` 入口 [Role: TDD Builder]

**Files:**
- Move: `server.py` → `delector/server.py`
- Modify: `delector/server.py:2403-2408`（回退链显式加「包上一级」项，不再只靠 CWD 兜）
- Modify: `start.py:74`（`from server import app` → `from delector.server import app`）

**Interfaces:** Consumes: `STATIC_DIR` 环境变量 / `DATA_DIR/static` / CWD / Produces: 静态目录在任意 CWD 下都能解析到仓库根 `static/`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: 迁 server 并修 static 回退链。Goal: server.py 进包后静态资源不依赖 CWD 侥幸命中。Target: git mv server.py；`2403-2408` 的候选列表里在 `os.path.dirname(__file__)/static` 之后显式插入 `os.path.dirname(os.path.dirname(__file__))/static`；`start.py:74` 改 `from delector.server import app`。TDD: 在仓库根以外的 CWD 下跑 `pytest tests/test_server.py -k 'static or staticfiles' -q`，修正前会红（CWD 兜不住），修正后绿。Return: 两种 CWD 下的对比证据。"

**Step Breakdown:**
- [ ] **Step 1: 基线。**
- [ ] **Step 2: `git mv` server.py。**
- [ ] **Step 3: 修回退链** + 改 start.py 入口。
- [ ] **Step 4: 在异 CWD 下验证**静态资源仍解析正确。
- [ ] **Step 5: 跑 `tests/test_server.py` 全量**确认绿。
- [ ] **Step 6: 原子 commit。**

---

### Task 6: tools 适配 [Role: TDD Builder]

**Files:**
- Modify: `tools/build_dict.py:45-46`（`from delector.core_dict import CORE_VOCAB_DB`、`from delector.linguistics import ...`）
- Modify: `tools/build_prep.py:49`（同上）
- Check: 两文件顶部的 `sys.path` hack（若有）在包化后是否仍需要

**Interfaces:** Consumes: 扁平 `core_dict` / Produces: `delector.core_dict`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: tools 适配。Goal: 构建脚本能继续 import 词典模块。Target: 改 3 处 import 为 `delector.` 前缀；检查顶部 sys.path hack（这些脚本从仓库根运行时根已在 sys.path，包化后通常不再需要，但先确认再删）。TDD: `pytest tests/test_dict_pipeline.py -q`（它按路径加载 tools/build_prep.py）确认绿。Return: 证据。"

**Step Breakdown:**
- [ ] **Step 1: 读两文件顶部**确认 sys.path hack 形态。
- [ ] **Step 2: 改 import。**
- [ ] **Step 3: 跑 `tests/test_dict_pipeline.py`** 确认绿。
- [ ] **Step 4: 原子 commit。**

---

### Task 7: 测试适配 + 更正 conftest 注释 [Role: TDD Builder]

**Files:**
- Modify: 9 个 `import server` / `from server import` 的测试（`tests/` 下）
- Modify: `conftest.py`（更正「Phase 2 后可删」的错误注释 —— 包化后 `import delector` 依然需要根在 sys.path）

**Interfaces:** Consumes: 扁平 `server` / Produces: `from delector import server`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 7: 测试适配。Goal: 9 个测试改走包路径，并修掉 conftest 里那句错误注释。Target: `grep -rlE '^(from server import|import server)' tests/*.py` 列出的文件全部改为 `from delector import server` / `from delector.server import ...`（`import server` 后用到 `server.xxx` 的，改成 `from delector import server` 即可保持写法）。TDD: 逐个跑改过的文件确认绿。Return: 逐文件证据。"

**Step Breakdown:**
- [ ] **Step 1: 列出 9 个文件。**
- [ ] **Step 2: 改 import**（保持 `server.xxx` 用法不变，用 `from delector import server`）。
- [ ] **Step 3: 逐个跑**确认绿。
- [ ] **Step 4: 更正 conftest 注释**（说明包化后为何仍需它）。
- [ ] **Step 5: 原子 commit。**

---

### Task 8: 打包联动（3 处 hidden-import + Android 拷贝 + APK 校验）[Role: TDD Builder]

**Files:**
- Modify: `package_windows.py:59-75`（17 个业务 hidden-import 加 `delector.` 前缀）
- Modify: `.github/workflows/build-release.yml:95-110`（Linux）、`:171-186`（macOS）同样加前缀
- Modify: `.github/workflows/build-release.yml:245`（逐个 `cp` 26 个 .py → `cp -r delector start.py android/app/src/main/python/`）
- Modify: `.github/workflows/build-release.yml:382`（`APP_NEEDLES` 改包路径，并补上 `routes_a2.py`）

**Interfaces:** Consumes: 扁平模块名 / Produces: `delector.*` 包路径

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 8: 打包联动。Goal: 三端打包清单与 Android 拷贝全部跟上包路径。Target: 3 处 hidden-import 加 `delector.` 前缀；Android 拷贝改整目录（这样顺带修掉当前漏拷 `routes_a2.py` 的既有缺陷）；APP_NEEDLES 更新为 `delector/server.py` 等并补 `delector/routes_a2.py`。TDD: 无本地 CI，靠 Task 9 的断言测试守护 + 人工核对 yml 文本。Return: diff 证据。"

**Step Breakdown:**
- [ ] **Step 1: 改 `package_windows.py`** 的 hidden-import。
- [ ] **Step 2: 改 yml 的 Linux/macOS 两处**（注意两处内容应完全一致）。
- [ ] **Step 3: 改 Android 拷贝**为整目录 `cp -r delector start.py`。
- [ ] **Step 4: 更新 APP_NEEDLES**（包路径 + 补 routes_a2）。
- [ ] **Step 5: 原子 commit。**

---

### Task 9: 更新打包注册断言测试 [Role: TDD Builder]

**Files:**
- Modify: `tests/test_server.py:1713`（`test_prep_dict_registered_in_all_package_targets`）、`:3830`（corpus_dict）、`:3851`（`test_all_backend_modules_registered_in_all_packaging_targets`）
- 断言字符串从 `--hidden-import=core_dict` 改为 `--hidden-import=delector.core_dict`；`wf.count(...) == 2` 逻辑保持

**Interfaces:** Consumes: 新的 hidden-import 命名 / Produces: 断言与打包清单一致

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 9: 更新打包断言。Goal: 让注册守卫测试钉住新的包路径，任何一处漏改都变红。Target: 改 3 个测试里的模块名字符串为 `delector.` 前缀（注意 `test_all_backend_modules_registered_in_all_packaging_targets` 有一个 `required_modules` 列表，整体加前缀）。TDD: 先确认改之前是红的（证明断言真的在生效），改完变绿。Return: 红→绿两段证据。"

**Step Breakdown:**
- [ ] **Step 1: 改前跑**确认红（断言生效）。
- [ ] **Step 2: 改断言字符串**为包路径。
- [ ] **Step 3: 跑**确认绿。
- [ ] **Step 4: 变异验证**（故意改回一个扁平名，确认变红，再改回）。
- [ ] **Step 5: 原子 commit。**

---

### Task 10: 文档同步 [Role: TDD Builder]

**Files:**
- Modify: `README.md`（目录树：26 个模块 → `delector/`，保留 `start.py` / `package_windows.py` / `conftest.py` / `tests/`）
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态补一条：后端模块已收包）
- Modify: `docs/agents/architecture.md`（模块布局描述）

**Interfaces:** Consumes: 新目录结构 / Produces: 文档与现状一致

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 10: 文档同步。Goal: 文档里的模块位置不再骗人。Target: README 目录树把 26 个模块收进 `delector/` 条目；PROJECT_OVERVIEW 补状态；architecture.md 更新模块布局。TDD: 无自动化，人工核对后 commit。"

**Step Breakdown:**
- [ ] **Step 1: 改 README 目录树。**
- [ ] **Step 2: 改 PROJECT_OVERVIEW / architecture.md。**
- [ ] **Step 3: 原子 commit。**

---

### Task 11: 收尾验证 [Role: TDD Builder]

**Files:**
- Verify: 全量 `pytest -q`（根目录，等同 CI）、`tests/test_backend_package_layout.py`
- Optional: 本地 PyInstaller 烟测（Windows，耗时长，可跳过，APK 验证挂下次发版）

**Interfaces:** Consumes: 全部迁移后代码 / Produces: 绿证明

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 11: 收尾验证。Goal: 确认迁移后全量测试与 Task 0 基线一致。Target: 根目录 `pytest -q`，passed 总数 == 583；`git status` 干净；确认 `delector/` 下无 `static/` 子目录被误建。Return: 对比表 + `python -c "import delector.database as d; print(d.DATA_DIR)"` 输出。"

**Step Breakdown:**
- [ ] **Step 1: 全量 `pytest -q`**，passed == 583（守卫截断统计时用进度条点数推算）。
- [ ] **Step 2: 跑 `tests/test_backend_package_layout.py`** 确认数据目录与静态目录语义未漂。
- [ ] **Step 3: `git status`** 干净。
- [ ] **Step 4: 记录验证证据**（本任务通常无需新增 commit）。

---

## Phase 3: 下游执行

计划已生成（含 Subagent Prompt Scaffold 模板）。**本环境无写码子代理**，`vault-exec` 降级为「主线程直写 + TDD + 每 Task 原子提交」，Scaffold 仅作步骤参照。

**必须先看懂的风险**：Task 3 的 `DATA_DIR` 是整个计划里唯一能造成**用户数据丢失**的步骤，它的守卫测试在 Task 0 就先立好。

回复 **「执行 Phase 2」** 即从 Task 0 开始。Phase 2b（包内子包化 `delector/routes/`、`delector/dicts/` 与文件重命名）不在本计划，单独立项。
