# Workbench 词库数据架构收敛 Implementation Plan

> **Goal**: 把背词工作台词库从「前端 HTML 内联种子 + 服务端正则解析 HTML」收敛为「数据模块单一真相 + 构建期注入」，统一词对象契约、把等级判定改为数据驱动，并据此打开 B1 入口——使"加一个等级 = 改数据，不改逻辑"。
> **Tech Stack**: Python 3.11 / FastAPI / 原生 JS ES Modules（`workbench.html` 单文件）/ pytest + Node 探针 / PyInstaller + Android Chaquopy
> **Spec Reference**: Vault `ADR-0011`（词库单一真相化与等级判定数据驱动，用户拍板 Q1=A / Q2=A）；上游 `ADR-0002`（scope 控制 + 进度零丢失）、`ADR-0005`（多等级可扩展 / `exam_catalog`）、`01-Rules/DATABASE-MIGRATION-IDEMPOTENCY`（幂等迁移对账谓词）
> **Global Constraints**:
> - **id 只增不改**：`wb.cards.v1`/`wb.wrong.v1` 以词 id 为键，任何改动不得变更既有 `a1-NNNN` / `a2-*` / `b1-*` id；需要变更只能走别名表（沿用 `SEED_ID_ALIASES` 机制）。**违反即否决。**
> - **存储 schema 冻结**：`lemma -> (cefr, pos, gender, plural, definition_zh)` 5 元组本轮不变；"统一契约"只作用于 `get_vocab_by_cefr` 的**输出侧**。扩展存储字段须另立 ADR。
> - **禁止把非数据文件当数据源**：服务端不得从 HTML/JS/CSS 正则提取业务数据；解析/导入失败**不得静默降级**（红线 1 精神）。
> - **行为探针优先**：跨边界契约（前端 ↔ 后端）用行为探针验证，字符串存在断言视为死测（红线 11）。
> - **HTML 内联块必须保留**：`workbench.html` 的 `const SEED_WORDS/CORE_WORD_SEED_IDS/CORE_CUSTOM_WORDS/SEED_ID_ALIASES` 继续以内联形式存在于文件中（file:// 离线单文件模式依赖它，且 `test_german_workbench.py` 数十条测试直接解析它）——只把"谁是源头"从 HTML 改为数据模块。
> - **门禁**：每 Task 结束 `pytest` 零回归 + `ruff check .` 零告警 + `python -m mypy` 零错误；JS 侧 `node tools/wb_queue_probe.mjs` 13/13 + `tools/*.mjs` 探针全绿。
> - 禁 `--no-verify`；Conventional Commits；每 Task 原子 commit。

---

## 现状锚点（实施前必读）

| 锚点 | 位置 | 说明 |
|---|---|---|
| A1 词库真源头 | `static/german/workbench.html`（`SEED_WORDS` 682 条 / `CORE_WORD_SEED_IDS` 213 / `CORE_CUSTOM_WORDS` 22 / `SEED_ID_ALIASES`） | id 形如 `a1-0001`；富字段 `gloss/ipa/ex[]/letter/page/tags/custom` |
| 服务端正则解析 HTML | `delector/core/database.py:1699-1783` `_load_a1_workbench_words()` | `re.search` 三处 + `except Exception: pass` + `a1_dict` 静默回退 |
| A2 特判 | `delector/core/database.py:1809-1844` `_load_a2_vocab_words()` + `:1892-1899` | 产出与通用分支同形，仅多 `de` 与缓存 |
| 通用等级分支 | `delector/core/database.py:1901-1960` | `id = f"{lvl.lower()}-{lemma.lower()}"` |
| 存储 5 元组 | `delector/data/core_dict.py` ⊕ `core_dict_ext.py` | **本轮冻结，不动** |
| scope 判定 | `static/german/workbench.html:1619` `inScopeWord` | 四分支嵌套三元 + 三路 OR 冗余 |
| 档位控件 | `static/german/workbench.html:341-345`（`#scopeSeg`）、`:3049-3164`（`syncScopeControls` / 切换写入口 / `syncA2CardsFromServer`） | |
| 前端持久化 | `workbench.html:1022-1135`（`K` 键表 / `loadAll` / `saveWords` / `wbsync`） | local-first + 幂等合并 |
| 备考域注册 | `delector/services/exam_catalog.py:27-76` | 仅 A1/A2 |
| 备考域页签 | `static/js/main.js:252-269`（`setExamLevel`，`["a1","a2"]` 硬编码 + A2 徽标硬编码 `"974"`）、`:374-391`（新等级页签"待接入"分支） | |
| A2 词卡渲染 | `static/js/a1_cards.js:23-45`（`_examVocabLevel === "A2"` → `/api/a2/vocab`）、`:205-213` | 硬编码等级 |
| 数据模块打包注册 | `package_windows.py:60-72`、`.github/workflows/build-release.yml`、守卫 `tests/test_server.py:4327-4337` | **新增数据模块必须同步三处**，否则打包后 `ModuleNotFoundError` 而本地全绿 |

---

### Task 1: A1 工作台词库数据模块化 + 双向构建工具 [TDD Builder]

**Files:**
- Create: `delector/data/a1_workbench_dict.py`（纯数据模块；由工具生成，禁手工改）
- Create: `tools/build_workbench_seed.py`（双向：`--extract` HTML→模块；默认 模块→HTML 注入）
- Create: `tests/test_a1_workbench_source.py`
- Modify: `package_windows.py:60-72`（hiddenimports 增 `delector.data.a1_workbench_dict`）
- Modify: `.github/workflows/build-release.yml`（Linux/macOS hidden-import 同步）
- Modify: `tests/test_server.py:4327-4337`（`data_dict_modules` 集合增一项）

**Interfaces:**
- Consumes: `workbench.html` 内联 `const SEED_WORDS` / `CORE_WORD_SEED_IDS` / `CORE_CUSTOM_WORDS` / `SEED_ID_ALIASES`
- Produces: `A1_WORKBENCH_SEED: List[Dict[str, Any]]`、`A1_WORKBENCH_CORE_IDS: FrozenSet[str]`、`A1_WORKBENCH_CUSTOM: List[Dict[str, Any]]`、`A1_WORKBENCH_ID_ALIASES: Dict[str, str]`

**要点**:
- `--extract` 从当前 HTML 一次性生成模块，**内容逐字等价**（682 条 / 213 id / 22 custom / 别名表精确映射）；此为 bootstrap，确保零行为差异。
- 默认模式反向注入：以模块为准重写 HTML 内联块，**幂等**（连跑两次字节一致），且不得触碰 HTML 其他部分。
- 模块文件头注明 auto-generated + 重跑命令（对齐 `core_dict_ext.py` / `encounter_seed_dict.py` 既有风格）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: A1 工作台词库数据模块化 + 双向构建工具。
> Goal: 让 `delector/data/a1_workbench_dict.py` 成为 A1 工作台词库的单一真相，HTML 内联块降级为其构建产物。
> Target Files: Create `delector/data/a1_workbench_dict.py`、`tools/build_workbench_seed.py`、`tests/test_a1_workbench_source.py`；Modify `package_windows.py`、`.github/workflows/build-release.yml`、`tests/test_server.py`。
> TDD Steps:
> 1. 先写 `tests/test_a1_workbench_source.py`（RED）：断言模块存在且 `len(A1_WORKBENCH_SEED)==682`、`len(A1_WORKBENCH_CORE_IDS)==213`、`len(A1_WORKBENCH_CUSTOM)==22`、`A1_WORKBENCH_ID_ALIASES == {'a1-0544':'a1-0034','a1-0545':'a1-0052'}`，并断言模块内容与 HTML 内联块**双向等价**（json 逐条比较）。
> 2. 跑 `python -m pytest tests/test_a1_workbench_source.py -q` 验证失败。
> 3. 实现 `tools/build_workbench_seed.py --extract` 生成模块；再实现默认注入模式；补齐打包三处注册。
> 4. 跑新测试 + `python -m pytest tests/test_german_workbench.py -q`（既有 682/213/22 断言必须全绿）+ `ruff check .` + `python -m mypy`。
> 5. 用卫语句展平，单函数不超过 2 层缩进。
> 6. `git commit`。
> 严禁：改变 HTML 内联数据的任何字段/id/顺序；手工编辑生成物。
> Return: 测试执行证据（命令 + 结果行）+ 变更文件清单。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 等价性 + 682/213/22/别名 断言
- [ ] **Step 2: 跑测试确认红**（模块尚不存在）
- [ ] **Step 3: 实现 `--extract`（HTML→模块）并生成模块**
- [ ] **Step 4: 实现默认注入（模块→HTML），连跑两次验证字节一致**
- [ ] **Step 5: 打包三处注册同步 + 新测试全绿 + 既有 workbench 测试全绿**
- [ ] **Step 6: REFACTOR（卫语句展平）+ ruff/mypy 零告警**
- [ ] **Step 7: 原子 commit**

---

### Task 2: 服务端改 import 数据模块，删除正则解析与静默回退 [TDD Builder]

**Files:**
- Modify: `delector/core/database.py:1699-1783`
- Test: `tests/test_a1_workbench_source.py`（追加用例）

**Interfaces:**
- Consumes: `delector.data.a1_workbench_dict` 的四个常量（Task 1 产出）
- Produces: `_load_a1_workbench_words() -> List[Dict[str, Any]]`（**输出逐条不变**，仍为 `{id, hw, pos, de, zh, core, cefr}`）

**要点**:
- 删除三处 `re.search`、`os.path.join(DATA_DIR, "static", ...)` 读文件、`except Exception: pass`。
- 直接 `from delector.data.a1_workbench_dict import ...`，**失败必须抛清晰异常**（不得返回空表、不得静默回退 `a1_dict`）。若保留 `a1_dict` 路径，只能作为**显式**参数分支且带日志，不得自动触发。
- `de`/`zh` 派生规则**保持不变**（`de = ex[0].de or de or ""`；`zh = gloss or zh or ex[0].zh or ""`），并用快照断言钉住：改造前后同一 id 的输出完全一致。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 服务端 A1 词库改 import 数据模块，删除正则解析与静默回退。
> Goal: 消除「把前端 HTML 当数据库」与解析失败的静默降级（ADR-0011 红线 2）。
> Target Files: Modify `delector/core/database.py:1699-1783`；Test 追加于 `tests/test_a1_workbench_source.py`。
> TDD Steps:
> 1. 先写失败测试（RED）：(a) 源码级断言 `database.py` 不再出现 `workbench.html` 字样；(b) 行为断言——`monkeypatch` 模块常量内容后 `_load_a1_workbench_words()` 随之变化（证明真读模块而非缓存 HTML）；(c) 形状坏/模块缺失时抛异常而非返回空表。
> 2. 跑测试验证红。
> 3. 改实现：直接 import + 删 regex/删除静默回退 + 保持 `de`/`zh` 派生规则不变。
> 4. 跑 `python -m pytest tests/test_german_workbench.py tests/test_a1_workbench_source.py tests/test_server.py -q` 全绿；另加「改造前后输出快照一致」断言（用 fixture 固定 20 条）。
> 5. REFACTOR + ruff/mypy 零告警。
> 6. `git commit`。
> 严禁：改变 `_load_a1_workbench_words()` 的对外输出；保留任何自动静默回退。
> Return: 测试执行证据 + 变更前后输出等价性证明。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 三组断言（源码、行为、失败必须炸）
- [ ] **Step 2: 跑测试确认红**
- [ ] **Step 3: 改为 import 数据模块，删 regex 与静默回退**
- [ ] **Step 4: 输出等价性快照断言全绿**
- [ ] **Step 5: REFACTOR + 门禁**
- [ ] **Step 6: 原子 commit**

---

### Task 3: 词对象契约统一（输出侧）+ A2 特判并入 [TDD Builder]

**Files:**
- Modify: `delector/core/database.py:1809-1960`
- Test: `tests/test_vocab_contract_uniform.py`（新建）

**Interfaces:**
- Produces: `get_vocab_by_cefr(cefr, scope)` 各分支产出**同一字段集** `{id, hw, pos, gender, plural, de, zh, core, cefr}`（缺失字段显式为空值，不留"有些等级有、有些没有"）

**要点**:
- 定义唯一字段集常量并在所有分支复用；A2 专用分支（`_load_a2_vocab_words`）并入通用路径（可保留缓存，但产出同一契约）。
- 补齐 A2/B1 的 `gender/plural`（通用分支已有）与 A1 的 `gender/plural`（当前 A1 输出**没有**这两字段）——若补齐会影响前端，先用契约测试锁定差异，再由 Task 4 的前端 normalize 吸收。
- **存储 5 元组不动**（ADR §5-#6）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: 词对象契约统一（输出侧）。
> Goal: 让 `get_vocab_by_cefr('A1'|'A2'|'B1', scope)` 各分支产出同一字段集，消除 A2 特判。
> Target Files: Modify `delector/core/database.py:1809-1960`；Create `tests/test_vocab_contract_uniform.py`。
> TDD Steps:
> 1. 写失败测试（RED）：对 A1/A2/B1 各取 ≥10 条，断言 `set(item.keys())` 完全一致且等于约定契约集。
> 2. 跑测试验证红（A1 缺 gender/plural，A2 走独立分支）。
> 3. 实现统一：抽公共构造函数，各分支只负责取「存储视图」再交公共函数映射。
> 4. 跑 `python -m pytest tests/test_vocab_contract_uniform.py tests/test_a2_vocab_data.py tests/test_server.py -q`。
> 5. REFACTOR + ruff/mypy 零告警。
> 6. `git commit`。
> 严禁：改动存储 5 元组 schema；改动 `id` 生成规则；改动既有 `hw` 拼装逻辑。
> Return: 契约一致性测试证据 + 各等级条数（A1/A2/B1）。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 三等级字段集一致
- [ ] **Step 2: 跑测试确认红**
- [ ] **Step 3: 抽公共映射函数，各分支收敛**
- [ ] **Step 4: A2 特判并入通用路径（缓存保留）**
- [ ] **Step 5: 全量相关测试 + 门禁**
- [ ] **Step 6: 原子 commit**

---

### Task 4: 前端 normalizeWord + 存量数据幂等迁移 [TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（`loadAll()` 段 `:1032-1119`、`applyMerge` 入口）
- Test: `tests/test_german_workbench.py`（追加）、`tools/wb_merge_probe.mjs`（扩展场景）

**Interfaces:**
- Produces: `normalizeWord(w) -> w'`（幂等、字段别名归一到契约字段名）；迁移版本标记 `wb.schema.v1`

**要点**:
- 老用户 localStorage 里的 `wb.words.v1` 对象形状不统一（A1 的 `gloss/ipa/ex`，A2/B1 的 `zh/de/gender/plural`）→ 启动时归一。
- **不得改 id**；**不得删除 `wb.cards.v1`/`wb.wrong.v1` 的任何键**；迁移必须幂等（连跑两次结果一致）。
- 失败必须不损坏数据（读写分离：先在内存归一，全部成功后才落盘）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 前端 normalizeWord + 存量数据幂等迁移。
> Goal: 让本地已存词对象收敛到统一契约字段名，同时保持 id 与 FSRS 进度零丢失。
> Target Files: Modify `static/german/workbench.html`（loadAll/applyMerge）；Test 追加 `tests/test_german_workbench.py`、扩展 `tools/wb_merge_probe.mjs`。
> TDD Steps:
> 1. 先写行为探针（RED）：喂一份「旧形状」words JSON（含 A1 `gloss/ex` 与 A2 `zh/de` 混存）→ 断言归一后 (a) id 集合逐一不变、(b) 字段名统一、(c) `cards`/`wrong` 键集合不变、(d) 连跑两次结果一致。
> 2. 跑 `python -m pytest tests/test_german_workbench.py -q` 与 `node tools/wb_merge_probe.mjs` 验证红。
> 3. 实现 `normalizeWord()` + 一次性迁移（幂等、全成功才落盘）。
> 4. 全绿回归 + 「旧 user 存量不被清空」断言。
> 5. REFACTOR（卫语句展平，避免深层嵌套）。
> 6. `git commit`。
> 严禁：变更任何既有 id；触碰 cards/wrong 的键；迁移中直接写 localStorage 后中途失败。
> Return: 探针输出 + 迁移前后 id/键集合对照。"

**Step Breakdown:**
- [ ] **Step 1: 写失败探针（RED）** —— 旧形状输入的四条断言
- [ ] **Step 2: 跑测试验证红**
- [ ] **Step 3: 实现 `normalizeWord()`（幂等）**
- [ ] **Step 4: 接入启动迁移（全成功才落盘）**
- [ ] **Step 5: 回归 + 扩展 `wb_merge_probe.mjs` 场景**
- [ ] **Step 6: 原子 commit**

---

### Task 5: scope 判定数据驱动（SCOPE_PREDICATES + isInScope / cefrOf） [TDD Builder]

**Files:**
- Modify: `static/german/workbench.html:1619`（`inScopeWord`）、`:3049-3164`（控件与切换）
- Test: `tests/test_german_workbench.py`（把特征串断言改为行为断言）、`tools/wb_queue_probe.mjs`（13 条切片护栏必须零漂移）

**Interfaces:**
- Produces: `cefrOf(w) -> string|null`、`isInScope(w, scope) -> bool`、配置表 `SCOPE_PREDICATES = { core, all, a2, b1?, reader }`

**要点**:
- 每个 scope 一条声明式谓词；`all` 的"排除其他等级 + 排除精读生词"由配置生成，不手写 OR 链。
- **对既有 scope 的对外行为必须逐字节等价**（core/all/a2/reader 三个既有范围）；`tools/wb_queue_probe.mjs` 13/13 是硬门禁。
- 为 Task 6 预留 `b1` 谓词（本 Task 可先不暴露档位）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: scope 判定数据驱动。
> Goal: 用 `SCOPE_PREDICATES` + `isInScope(w, scope)` 替换 `inScopeWord` 的嵌套三元与三路 OR，新增等级只加一行配置。
> Target Files: Modify `static/german/workbench.html`（`inScopeWord` 及其全部调用点）；Test 改 `tests/test_german_workbench.py`、跑 `tools/wb_queue_probe.mjs`。
> TDD Steps:
> 1. 先跑 `node tools/wb_queue_probe.mjs` 记录现状 13/13 绿（作为行为基线）。
> 2. 新增行为断言测试（RED）：同一批词在 core/all/a2/reader 四范围下的进出结果必须与改造前完全一致（用固定 fixture 快照）。
> 3. 实现 `cefrOf`/`isInScope`/`SCOPE_PREDICATES`；把既有的字符串特征断言（如断言源码里出现某表达式）改为**行为**断言（红线 11）。
> 4. 跑 `node tools/wb_queue_probe.mjs`（必须 13/13）+ `python -m pytest tests/test_german_workbench.py -q` 全绿。
> 5. REFACTOR：删除所有重复的三路 OR 判定，确保全文件只有一处等级判定入口。
> 6. `git commit`。
> 严禁：改变既有四范围对外的筛选结果；保留第二处等级判定副本。
> Return: 探针 13/13 证据 + 四范围行为快照一致性证明。"

**Step Breakdown:**
- [ ] **Step 1: 记录 13/13 行为基线**
- [ ] **Step 2: 写行为快照测试（RED）**
- [ ] **Step 3: 实现配置表 + `cefrOf`/`isInScope`**
- [ ] **Step 4: 替换所有调用点，删冗余判定**
- [ ] **Step 5: 13/13 + 全量测试 + 门禁**
- [ ] **Step 6: 原子 commit**

---

### Task 6: B1 入口（工作台档位 + 备考域页签） [TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（`#scopeSeg` markup `:341-345`；新增 B1 sync 函数，紧邻 `syncA2CardsFromServer` `:3102-3142`；切换处理 `:3152-3164`）
- Modify: `delector/services/exam_catalog.py`（注册 B1 等级 + vocab 模块）
- Modify: `static/js/main.js:252-269`（`["a1","a2"]` → 含 `b1`；**A2 徽标硬编码 `"974"` 改为从 catalog 动态取**）
- Modify: `static/js/a1_cards.js:23-45`、`:205-213`（`_examVocabLevel === "A2"` 硬编码泛化为按等级取数）
- Test: `tests/test_exam_domain.py`、`tests/test_server.py`、`tests/test_german_workbench.py`

**Interfaces:**
- Consumes: `GET /api/cards/vocab?cefr=B1&scope=all`（**既有端点**，`get_vocab_by_cefr` 已支持 B1，返回 1712 条）、`GET /api/exams/catalog`
- Produces: workbench `data-scope="b1"` 档位；`exam_catalog.EXAM_CATALOG["B1"]`

**要点**:
- 服务端**零新增端点**（`/api/cards/vocab` 直接可用）；`exam_catalog` 的 `count_fn` 用 `len(get_vocab_by_cefr("B1")["words"])` 动态推导，**不得硬编码 1712**（权威词表接入后条数会变）。
- 备考域页签：`main.js:382-389` 目前只对 `key === "a2"` 接线，其余标"待接入"（no-op）——B1 必须**真接线**，不得留死按钮（v5.1.0 前科纪律）。
- 徽标必须动态：既有的 `"974"` 硬编码属技术债，一并改为读 catalog `count`。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: B1 入口（工作台档位 + 备考域页签）。
> Goal: 让 B1（当前 1712 词，数据层已就绪）在工作台可刷、在备考域可看，且条数一律动态推导。
> Target Files: Modify `static/german/workbench.html`、`delector/services/exam_catalog.py`、`static/js/main.js`、`static/js/a1_cards.js`；Test `tests/test_exam_domain.py`、`tests/test_server.py`、`tests/test_german_workbench.py`。
> TDD Steps:
> 1. 写失败测试（RED）：(a) `GET /api/exams/catalog` 含 B1 且 vocab count == `len(get_vocab_by_cefr('B1')['words'])`；(b) workbench 源码含 `data-scope=\"b1\"` 与 B1 sync 调用；(c) 断言 `main.js` 中 A2 徽标**不再硬编码**数字。
> 2. 跑测试验证红。
> 3. 实现：`exam_catalog` 注册 B1；`main.js` 泛化等级站点与徽标；`a1_cards.js` 按等级取数；workbench 加档位 + sync + 切换处理。
> 4. 跑 `python -m pytest tests/test_exam_domain.py tests/test_server.py tests/test_german_workbench.py -q` + `node tools/wb_queue_probe.mjs` 全绿；手动验证 `/api/cards/vocab?cefr=B1&scope=all` 返回 1712。
> 5. REFACTOR：等级相关逻辑不得出现第二处硬编码等级列表。
> 6. `git commit`。
> 严禁：新增后端端点；硬编码词条数；留 no-op 死页签。
> Return: 测试证据 + catalog 输出（含 B1 count）+ 三处硬编码等级清单（已消除）。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— catalog 含 B1 + 档位存在 + 徽标去硬编码
- [ ] **Step 2: 跑测试确认红**
- [ ] **Step 3: `exam_catalog` 注册 B1（动态 count_fn）**
- [ ] **Step 4: `main.js` / `a1_cards.js` 等级逻辑泛化 + 徽标动态**
- [ ] **Step 5: workbench B1 档位 + sync + 切换**
- [ ] **Step 6: 全量测试 + 探针 + 门禁**
- [ ] **Step 7: 原子 commit**

---

### Task 7: 收官验证 [Verifier]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`、本计划「执行状态」块

**要点**:
- 全量门禁：`pytest`（基线 753+1 不回退）/ `ruff check .` 零告警 / `python -m mypy` 零错误 / `node tools/*.mjs` 探针全绿 / Go 三门禁（`gofmt -l` 空、`go vet`、`go test -race ./...`）。
- 双端点检：桌面 `python start.py` → 工作台四档 + B1 档位可见可刷；Android 覆盖安装后 B1 档位可见、进度不丢。
- 开 PR（PR CI 真验证）；确认 `test_writer_mobile.py` 版本面锁死测试不受影响。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 7: 收官验证。
> Goal: 全门禁零回归 + 双端可用 + 文档回填 + 开 PR。
> Target Files: Modify `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`、本计划执行状态块。
> Steps:
> 1. 跑全量 `python -m pytest -q` 并记录通过数（基线 753 passed + 1 skipped）。
> 2. 跑 `ruff check .`、`python -m mypy`、`node tools/wb_queue_probe.mjs`、`node tools/wb_merge_probe.mjs`。
> 3. 跑 Go 三门禁（`gofmt -l .`、`go vet ./...`、`go test -race ./...` 于 `agent/`）。
> 4. 回填 OVERVIEW（状态/决策/测试基线）+ work.log（SESSION 事件）+ 本计划执行状态。
> 5. 开 PR，标题 `refactor(workbench): 词库单一真相化 + 等级判定数据驱动（ADR-0011）`。
> Return: 各门禁命令与结果行 + PR 链接。"

**Step Breakdown:**
- [ ] **Step 1: 全量 pytest + 记录基线**
- [ ] **Step 2: ruff / mypy / Node 探针**
- [ ] **Step 3: Go 三门禁**
- [ ] **Step 4: 双端点检（桌面 + Android 覆盖安装）**
- [ ] **Step 5: 文档回填（OVERVIEW / work.log / 本计划）**
- [ ] **Step 6: 开 PR**

---

## 任务依赖与并行度

```
T1 ──► T2 ──┐
            ├──► T3 ──► T5 ──► T6 ──► T7
T4 ◄────────┘（T4 可与 T2/T3 并行）
```

- **T1 必须先做**（数据模块是 T2 的前提）。
- **T4（前端迁移）可与 T2/T3 并行**（只依赖 T1 产出的契约字段名）。
- **T5 依赖 T3**（契约统一后判定才稳定）；**T6 依赖 T5**。

## 并行工作流（不在本计划任务内）

**权威 A2/B1 词表整理**（由用户交给外部 agent）——交付物 = 可直接粘贴进 `delector/data/core_dict.py` 的 5 元组片段（提示词 v2 已就绪，见 `.codebuddy/memory/2026-09-15.md`）。与 T1–T3 **完全解耦**（存储 schema 冻结，ADR §5-#6）；落地窗口在 T6 之后（权威条目落库后 B1 条数变化由动态 `count_fn` 自动吸收）。
> ⚠️ 交接给外部 agent 时必须带上三条：**范围限 A2/B1**、**lemma 即主键不得改名**、**cefr 必须是字面量 `"A2"`/`"B1"`**。

---

## 执行状态（收官时回填）

- 状态：**PENDING**
- 已知边界（不进本轮）：
  - **A2/B1 的 `ipa` / 例句（`ex`）补齐**：属"富字段扩展"，会触碰存储 schema → 须另立 ADR（本轮 A2/B1 卡片信息量仍低于 A1）。
  - **`--strict` / 其他静态债**：无关，不动。
  - **手机端 B1 内容分发**：B1 词库随包内已有数据即可用，WiFi 拉取（ADR-0004 复用）不涉及。
  - **精读域 CEFR 标注对 B1 的联动**：`core_dict` 的 B1 条目本就参与 CEPR 查询，本轮不改。
