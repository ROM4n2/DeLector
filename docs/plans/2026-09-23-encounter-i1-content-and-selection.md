# 遇见区 i+1 补齐：内容放量 + 就近选材 实施计划

> **Goal**: 把遇见区从「4 篇一次性内容」升级为「按本机背词进度动态排序的阅读队列」——A 阶段把预置分级短文 4 → 7 篇并以**版本化增量补装**让存量设备零操作升级；B 阶段新增轻量索引端点 + 前端纯函数，使列表在**不点开任何一篇**的前提下标出「哪篇正好读（i+1）」并置顶。
> **Tech Stack**: Python 3.10+（FastAPI + stdlib sqlite3，**零新依赖**）/ 原生 ES Modules 前端（零构建）/ Node `node:vm` 行为探针
> **Spec Reference**: `docs/specs/2026-09-23-encounter-i1-content-and-selection-design.md`
> **Global Constraints**:
> - **known 判定永远本机**（ADR 红线）：服务端只提供「每篇的逐 token lemma 序列」，覆盖率一律前端算；**MUST NOT** 在服务端算覆盖率或改此语义
> - **存量数据回填规范**（Vault `01-Rules/STORED-DATA-BACKFILL` / 项目红线 12）：补装 MUST 只增 + 只补空 + 幂等，MUST NOT 覆盖用户非空字段，MUST NOT 跨语义来源混用
> - **不改** `annotate` 端点及其「P0 直跑、禁缓存」策略；**不扩** `_ALLOWED_LEVELS`（B2/TestDaF 出范围）；不动 `workbench.html` / FSRS / 词库 12 字段契约
> - **零新依赖**（仅 stdlib + spaCy 既有链路）；索引端点**只读**、无 DB 写入
> - **mypy `--strict` 零 error**（`delector` + `tools`）；`ruff check .` 零告警
> - **前端安全**：所有展示字段一律 `esc()`；探针必须切**真实源码**（`node:vm`），禁止字符串存在式死断言
> - **打包注册面**：`encounter_seed_dict` 已在三处清单内，本次**只改内容不改注册**；新增 `static/js/enc-i1.js` 由 `encounter.js` import，须过 `tests/test_frontend_module_graph.py` 可达性
> - **环境**：Windows / bash；Python 命令前 `export PYTHONIOENCODING=utf-8`；全量 pytest 用**分半跑**（`--ignore=tests/test_server.py` + 单跑 `tests/test_server.py`）
> - **纪律**：子代理**不 git add / commit / push / 切分支**（由主线程统一执行）；每 Task 收尾必跑 目标测试 → 全探针零漂移 → ruff → mypy --strict

---

### Task 1: 产包脚本扩容 + 预计算 `lemma_seq` + 重跑产物（Phase A）[Role: TDD Builder]

**Files:**
- Modify: `tests/test_encounter_seed.py`（数据契约段：篇数 4 → 7、白名单加 B1、新增 `lemma_seq` 结构断言）
- Modify: `tools/build_encounter_seed.py`（`_DEFAULT_LEVELS` → `"A1,A2,B1"`；`build_packs()` 增写 `analysis.lemma_seq`）
- Regenerate: `delector/data/encounter_seed_dict.py`（**由脚本重跑产出，禁止手工编辑**）

**Interfaces:**
- Consumes: `delector/data/corpus_dict.py::OFFICIAL_CORPUS`（12 篇 / A1–B2）、`delector/nlp_engine.process_german_text`、`delector/tools/vocab_stats.run`
- Produces: `PRESET_ENCOUNTER_PACKS: list[dict]`（7 包），每包 `analysis` 新增字段
  - `analysis["lemma_seq"]: list[str]` —— 该篇正文按 **annotate 同口径**（剔除 `is_space`）的逐 token lemma 有序列表（**含重复**）
  - 不变量：`len(pack["analysis"]["lemma_seq"]) == pack["analysis"]["tokens_total"]`（本机实测：`delector` 的 spaCy 分词 `space_tokens == 0`，两者同源同值）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 产包脚本扩容 + 预计算 lemma_seq + 重跑产物。
> Goal: 让预置遇见区卡包从 4 篇（A1×2/A2×2）扩到 7 篇（A1×2/A2×2/B1×3），并为每包写入 annotate 口径的逐 token lemma 序列，供 B 阶段前端本机算覆盖率。
> Target Files: Modify `tests/test_encounter_seed.py`, Modify `tools/build_encounter_seed.py`, Regenerate `delector/data/encounter_seed_dict.py`.
> TDD Steps:
> 1. 先改 `tests/test_encounter_seed.py` 数据契约断言（RED）：`len(PRESET_ENCOUNTER_PACKS) == 7`；`estimated_cefr ⊆ {"A1","A2","B1"}`；每包 `analysis["lemma_seq"]` 为非空 `list[str]` 且 `len(lemma_seq) == analysis["tokens_total"]`。跑 `export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_seed.py -q` 确认按预期变红（篇数与缺字段）。
> 2. 改 `tools/build_encounter_seed.py`：`_DEFAULT_LEVELS = "A1,A2,B1"`；在 `build_packs()` 构造 `analysis` 时加入 `lemma_seq = [tok["lemma"] for s in parsed["sentences"] for tok in s["tokens"] if not tok.get("is_space")]`（**逐字照此口径**，与 `routes/encounter.py::_annotate_tokens` 的 `is_space` 剔除规则一致）。
> 3. 重跑产物（GREEN）：`export PYTHONIOENCODING=utf-8 && python tools/build_encounter_seed.py --created-at 2026-09-23`（**禁止手改生成物**）；确认 stdout 打印 `产出包数: 7; levels 分布: A1:2, A2:2, B1:3`。
> 4. 跑 `python -m pytest tests/test_encounter_seed.py -q` 全绿（含既有 `test_build_script_deterministic` 仍绿——新增字段不得引入非确定性）。
> 5. REFACTOR：把 `lemma_seq` 的抽取抽成一个带 docstring 的模块级纯函数（如 `_annotate_lemma_seq(parsed)`），注释写明「与 annotate 的 is_space 口径同源，改动需同步路由」。
> **变异验证（必做并回报）**：① 把 `if not tok.get("is_space")` 改成不过滤 → 若 `space_tokens == 0` 则不红，此时改用「构造一篇含连续空白的正文」在测试里断言剔除生效（不得以"不红"结案）；② 把 `--levels` 默认改回 `A1,A2` → 篇数断言必红。
> Return: Summary with test execution evidence + 变异验证结论。"
>
> **注意**：`build_packs()` 里 `analysis` 的既有键（`tokens_total/known_count/known_rate/unknown_lemmas/level_hint`）**一个都不能删或改名**——`unknown_lemmas` 与考纲口径相关，`tokens_total` 是 B 阶段分母的权威来源。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 篇数 7 / CEFR 含 B1 / `lemma_seq` 类型与长度不变量
- [ ] **Step 2: 跑测试确认按预期失败**
- [ ] **Step 3: 改脚本（levels + `lemma_seq`）并重跑产物（GREEN）**
- [ ] **Step 4: 跑测试全绿 + 执行变异验证（剔除规则 / levels 默认值）**
- [ ] **Step 5: 抽纯函数 + docstring 标注口径同源（REFACTOR）**
- [ ] **Step 6: 收尾门禁**（`python -m pytest tests/test_encounter_seed.py tests/test_encounter_store.py tests/test_encounter_routes.py -q` / ruff / mypy --strict / 全探针零漂移）

---

### Task 2: 版本化增量补装（Phase A，核心）[Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py`（模块级 `PRESET_SEED_VERSION = 2`；重写 `seed_preset_encounter_texts`；按需新增 `_get_app_setting` / `_set_app_setting`）
- Test: `tests/test_encounter_seed.py`（行为段：空库 / 非空库补装 / 幂等 / 不复活 / 只补空 / 不覆盖非空）

**Interfaces:**
- Consumes: `app_settings(key TEXT PRIMARY KEY, value TEXT)`、`encounter_texts(pack_id TEXT UNIQUE, title, level, source, content, pack_json, created_at)`、`import_encounter_pack(pack, db_path) -> int`（幂等：同 pack_id 返回既有 id）
- Produces:
  - `PRESET_SEED_VERSION: int = 2`
  - `seed_preset_encounter_texts(db_path: Optional[str] = None) -> int`（**返回值 = 本次实际新建的行数**，语义与现状一致）
  - `_get_app_setting(key: str, default: Optional[str] = None, db_path=None) -> Optional[str]` / `_set_app_setting(key: str, value: str, db_path=None) -> None`（参数化 SQL；若已存在等价的 app_settings 读写 helper 则复用，**不要重复造**）

**行为契约（决策表，逐条落测试）:**

| 场景 | 期望 |
|---|---|
| `app_settings["encounter_seed_version"] >= 2` | 返回 0，**一次 DB 读取即返回**（热路径） |
| 无版本记录 且 `encounter_texts` 为空 | 全量导入 7 行、写入版本 2（保留既有空态语义） |
| 无版本记录 且 库非空 | **只增**补装缺失 pack_id；用户已有行**逐字段不变**；写入版本 2 |
| 版本已 2 后再调用 | 返回 0，行数与内容零变化（幂等） |
| 删除某预置包后再次调用 | 返回 0，**不复活** |
| 已存在 pack_id 且其 `pack_json.analysis` 缺 `lemma_seq`、新包有 | **只补该字段**（UPDATE `pack_json`），其余列与其余键逐字段不变 |
| 已存在 pack_id 且 `lemma_seq` 非空（哪怕是哨兵值） | **不覆盖**（能力闸门：只补空） |
| 单个包导入失败 | 记 `logging.error` 汇总，其余包继续，**不崩启动**（沿用既有逐包隔离） |

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 版本化增量补装。
> Goal: 把 `seed_preset_encounter_texts` 的空库守卫升级为「版本闸 + 只增 + 只补空 + 幂等」，让存量非空库设备在升级后**零操作**获得新增的 3 篇 B1 预置，并且旧 4 篇的 `pack_json` 被补上 `analysis.lemma_seq`。
> Target Files: Modify `delector/core/database.py`, Test `tests/test_encounter_seed.py`.
> TDD Steps:
> 1. 写失败测试（RED）：覆盖决策表全部 8 行。关键断言要**具值**：非空库补装后总行数 == 8（1 手工 + 7 预置）、用户行 `title/level/content/source/created_at` 与补装前逐个 `==`；`_count_encounter_rows` 二次调用不变；删除一包后 `SELECT COUNT(*)` 不回升；旧行 `pack_json` 补空后 `analysis["lemma_seq"]` 非空且 `title` 未变；哨兵值不被覆盖。
>    - 构造「旧行」的方法：先 `import_encounter_pack` 一个**手工剥掉 `analysis["lemma_seq"]` 的包副本**，再调用 seeder。
> 2. 跑 `export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_seed.py -q` 确认 RED。
> 3. 实现（GREEN）：读版本 → 早退 → 逐包 `import_encounter_pack` → 对已存在行做「只补空字段」的 `pack_json` 合并 UPDATE → 写版本。**只补空**实现要点：解析旧 `pack_json`；若 `analysis` 中无 `lemma_seq`（或为空）且新包有 → 浅拷贝新包该字段后 `json.dumps(..., ensure_ascii=False)` 写回；任何解析失败一律跳过该行并 `logging.error`。
> 4. 跑测试全绿（含既有 `test_seed_idempotent` / `test_create_app_*` 不回归）。
> 5. REFACTOR：把决策表拆成 Guard Clause 小函数（版本读取 / 空库全量 / 非空补装 / 只补空），每层 ≤2 层缩进；`PRESET_SEED_VERSION` 带注释说明「升版本号才会再触发一次补装」。
> **变异验证（必做并回报）**：① 删掉版本早退 → 幂等用例必红；② 把「只补空」改成无条件覆盖 → 哨兵值用例必红；③ 把 7 包循环改成只补第一包 → 行数断言必红。**用 `cp` 备份还原，禁 `git checkout --`。**
> Return: Summary with test execution evidence + 变异验证结论。"
>
> **注意**：`delector/server.py` 的调用点与调用顺序**不需要改动**（既有 AST 守卫 `test_create_app_calls_seed_encounter_texts` / `test_create_app_seed_order_after_articles` 必须继续通过）。**不要**把 seeder 挪进 `init_db()`（既有理由见函数 docstring）。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 决策表 8 行逐条覆盖
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现版本闸 + 只增补装 + 只补空（GREEN）**
- [ ] **Step 4: 跑测试全绿 + 执行三项变异验证**
- [ ] **Step 5: Guard Clause 拆分 + 常量注释（REFACTOR）**
- [ ] **Step 6: 收尾门禁**（含 `tests/test_encounter_store.py` / `tests/test_server.py` 单跑）

---

### Task 3: `GET /api/encounter/texts/index` 索引端点（Phase B）[Role: TDD Builder]

**Files:**
- Modify: `delector/routes/encounter.py`（新增 `api_list_index`，**同 router、注册顺序不变**）
- Test: Create `tests/test_encounter_index.py`

**Interfaces:**
- Consumes: `delector.core.database.list_encounter_texts`、`encounter_texts.pack_json`
- Produces: `GET /api/encounter/texts/index` → `{"items": [{"id": int, "title": str, "level": str, "word_count": int, "total_tokens": Optional[int], "lemma_seq": Optional[list[str]]}, ...]}`
  - `total_tokens` 取 `pack_json["analysis"]["tokens_total"]`；`lemma_seq` 取 `pack_json["analysis"]["lemma_seq"]`
  - 任一缺失 / `pack_json` 为空或非法 JSON / 类型不符 → 该行两字段均为 `null`（**行仍返回**）
  - **MUST NOT** 返回 `content` / `pack_json` / `source`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: `GET /api/encounter/texts/index` 索引端点。
> Goal: 为前端提供「每篇短文的 annotate 口径词序列」，供本机算覆盖率并排序；端点只读、零 spaCy、零写库、不挂本机闸（手机/局域网端要能用）。
> Target Files: Modify `delector/routes/encounter.py`, Create `tests/test_encounter_index.py`.
> TDD Steps:
> 1. 写失败测试（RED，TestClient 全链路，env 钉 tmp_path 临时库，**不碰仓库根 `delector.db`**）：① 空库 → `{"items": []}`；② 导入一个带 `analysis.lemma_seq` 的包 → 该行 `total_tokens` 与 `len(lemma_seq)` 均与包内一致；③ `create_encounter_text` 手工短文（无 pack_json）→ 该行 `total_tokens is None and lemma_seq is None` **且仍在 items 内**；④ 手工写入 `pack_json="{bad"` 的行 → 该行两字段 `null` 且整体 200（**不 500**）；⑤ 响应键集断言 `set(items[0].keys()) == {"id","title","level","word_count","total_tokens","lemma_seq"}`（**字段集合相等**，不是"不含某字符串"）。
> 2. 跑 `export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_index.py -q` 确认 RED。
> 3. 实现（GREEN）：遍历 `list_encounter_texts()`、逐行 try/except 解析 `pack_json`、映射字段。抽出 `_index_entry(row) -> dict` 纯映射函数（与既有 `_shelf_entry` 同风格，含 docstring 说明降级语义）。
> 4. 跑测试；**并跑全量路由相关测试**：`python -m pytest tests/test_encounter_routes.py tests/test_encounter_pull.py tests/test_routes_register.py -q`（项目有 fastapi 依赖漂移 post-mortem——新增端点后必须验证既有路由守卫不回归）。
> 5. REFACTOR：Guard Clause 扁平化（缺失 → 早退填 `None`），端点函数体 ≤25 行。
> **变异验证（必做并回报）**：① 把逐行 try/except 去掉 → 坏 JSON 用例必红；② 返回里加上 `content` → 字段集用例必红；③ 给端点挂上 `Depends(_require_localhost)` → 用**默认 TestClient**（host `testclient`）打的用例必 403 而红（该端点是手机/局域网只读需求，**MUST NOT** 挂本机闸）。
> Return: Summary with test execution evidence + 变异验证结论。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 空库 / 正常行 / 手工行 / 坏 JSON / 字段集 / 鉴权语义
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `_index_entry` + 端点（GREEN）**
- [ ] **Step 4: 跑目标测试 + 全量路由守卫测试**
- [ ] **Step 5: Guard Clause 扁平化 + docstring（REFACTOR）**
- [ ] **Step 6: 收尾门禁**

---

### Task 4: 前端 i+1 纯函数 + 行为探针（Phase B）[Role: TDD Builder]

**Files:**
- Create: `static/js/enc-i1.js`（纯逻辑，**零 import / 不碰浏览器全局 / 不抛异常**，与 `deck-bridge.js` 同纪律）
- Create: `tools/wb_enc_i1_probe.mjs`（`node:vm` 切真实源码，4 场景，支持 `--json`）
- Create: `tests/test_enc_i1_probe.py`（跑探针，`--json` 有失败即红——对齐 `test_rich_backfill_probe_reports_no_failures` 模式）

**Interfaces:**
- Consumes: 无（`knownSet` 由调用方注入；模块**不得** import `deck-bridge.js`，由 `encounter.js` 负责组装）
- Produces:
  - `I1_BANDS = { i1: [0.85, 0.97), easy: [0.97, +∞), hard: (-∞, 0.85) }`（常量单点定义，UI 与探针共用）
  - `bandOf(rate: number) -> "i1" | "easy" | "hard"`
  - `coverageOf(knownSet: Set<string>, entry) -> {available: boolean, knownTokens: number, totalTokens: number, rate: number, band: string|null}`
  - `rankEntries(knownSet: Set<string>, entries: Array) -> Array`（**返回新数组，不改入参**；band 优先级 i1 > easy > hard，组内 `rate` 降序、同分 `id` 升序，`available=false` 排最后）
  - `topPick(ranked) -> object | null`（首条 `band === "i1"`，无则 `null`）
  - `hasCoverage(knownSet) -> boolean`（`knownSet.size === 0` → false，供 UI 决定是否显示推荐条/引导文案）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 前端 i+1 纯函数 + 行为探针。
> Goal: 把「按本机 knownSet 算覆盖率 → 分区间 → 排序 → 取推荐」实现为零依赖纯函数，并用 `node:vm` 切真实源码的行为探针钉死契约。
> Target Files: Create `static/js/enc-i1.js`, Create `tools/wb_enc_i1_probe.mjs`, Create `tests/test_enc_i1_probe.py`.
> TDD Steps:
> 1. 先写探针（RED）：`tools/wb_enc_i1_probe.mjs` 读 `static/js/enc-i1.js` **真实源码**，用 `node:vm`（`SourceTextModule` 或去 `export` 后注入沙箱，**照抄 `tools/wb_rich_backfill_probe.mjs` 的既有切法**）执行，注入桩 `knownSet`，覆盖 4 场景：① 区间边界（rate = 0.84 / 0.85 / 0.96 / 0.97 → `hard / i1 / i1 / easy`）；② 排序（i1 组在 easy 前、hard 后；组内 rate 降序；同分按 id 升序；`available=false` 最后）；③ `topPick`（有 i1 返回首条；只有 easy/hard 返回 null）；④ 幂等/纯度（`rankEntries` 不改入参数组与其元素）；另含 `hasCoverage`（空 Set → false）。输出 `--json` 结果，有失败时非零退出或 JSON 里 `failures > 0`。
> 2. 跑 `node tools/wb_enc_i1_probe.mjs` 确认 RED（模块不存在 → 探针报失败）。
> 3. 实现 `static/js/enc-i1.js`（GREEN）：零 import、无 `localStorage`/`document`/`window`、坏输入返回降级值不抛。覆盖率算法**逐字为**：`knownTokens = entry.lemma_seq.filter((l) => knownSet.has(String(l).toLowerCase())).length; rate = knownTokens / entry.total_tokens;`（**分母用 `entry.total_tokens`，MUST NOT 用 `lemma_seq.length`**）。
> 4. 跑 `node tools/wb_enc_i1_probe.mjs` 全绿；再写 `tests/test_enc_i1_probe.py` 跑探针并断言 `failures == 0`，接入 pytest；跑 `python -m pytest tests/test_enc_i1_probe.py -q`。
> 5. REFACTOR：阈值只在 `I1_BANDS` 定义一次（`bandOf` 内不得出现裸露的 `0.85`/`0.97` 字面量）；每个导出函数带 docstring 说明语义与边界。
> **变异验证（必做并回报）**：① 把 `bandOf` 的 `0.85` 改成 `0.8` → 边界场景必红；② 把 `rankEntries` 改成就地排序（`entries.sort`）→ 纯度断言必红；③ 把分母换成 `lemma_seq.length` 并在探针里构造 `totalTokens ≠ lemma_seq.length` 的场景 → 必红。
> Return: Summary with test execution evidence + 变异验证结论。"

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED）** —— 4 场景 + `hasCoverage`，输出 `--json`
- [ ] **Step 2: 跑探针确认失败**
- [ ] **Step 3: 实现 `enc-i1.js`（GREEN）** —— 零依赖 / 不抛 / 不改入参
- [ ] **Step 4: 跑探针全绿 + 写 pytest 接线并跑通 + 执行三项变异验证**
- [ ] **Step 5: 阈值单点化 + docstring（REFACTOR）**
- [ ] **Step 6: 收尾门禁**（全探针零漂移 / ruff / mypy --strict）

---

### Task 5: 前端集成（列表徽章 / 排序 / 推荐条）[Role: TDD Builder]

**Files:**
- Modify: `static/index.html`（`view-encounter` 内 `#encounter-text-list` 之前新增 `<div id="enc-i1-hint" class="enc-i1-hint" style="display:none"></div>`）
- Modify: `static/js/encounter.js`（`fetchIndex()` / `renderTextList` 接受排序后条目 / `renderI1Hint` / `showView` 并发取数 + 降级）
- Modify: `static/style.css`（`.enc-i1-badge` 三态 + `.enc-i1-hint`；移动端断点内补规则）
- Test: Modify `tests/test_encounter_ui_probes.py`（结构 + `esc()` + 降级路径断言）

**Interfaces:**
- Consumes: `GET /api/encounter/texts`（既有）、`GET /api/encounter/texts/index`、`deck-bridge.js::{loadDeck, buildKnownSet}`、`enc-i1.js::{rankEntries, topPick, hasCoverage}`
- Produces:
  - `fetchIndex() -> Promise<Array>`（失败时由调用方兜底，**本函数不吞异常**）
  - `renderTextList(texts, ranked)`（`ranked` 为 `null`/缺省 → 保持既有行为，逐字兼容）
  - `renderI1Hint(ranked)`（无 i1 或无覆盖率 → 隐藏容器；空 `knownSet` → 显示引导文案）
  - 徽章 DOM：`<span class="enc-i1-badge enc-i1-${band}">${label} ${pct}%</span>`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: 前端集成。
> Goal: 让遇见区列表在**不点开任何一篇**的前提下，按本机已背词覆盖率分组排序并标出 i+1 推荐；索引失败时**完全退回**既有列表行为。
> Target Files: Modify `static/index.html`, Modify `static/js/encounter.js`, Modify `static/style.css`, Modify `tests/test_encounter_ui_probes.py`.
> TDD Steps:
> 1. 写失败测试（RED，追加到 `tests/test_encounter_ui_probes.py`）：① `index.html` 的 `view-encounter` 段内存在 `id="enc-i1-hint"`；② `encounter.js` import 了 `./enc-i1.js` 与 `deck-bridge.js`（**可达性契约**，同时满足 `tests/test_frontend_module_graph.py`）；③ 徽章渲染路径调用 `esc(` 且 `band` 经白名单映射（断言 `enc-i1-badge` 与三态 class 名出现）；④ 降级：`Promise.allSettled` 出现且索引 rejected 分支不抛（断言「索引失败 → 仍调用 renderTextList」的代码路径存在，且 `renderTextList` 的 `ranked` 为可选参数）。跑 `python -m pytest tests/test_encounter_ui_probes.py -q` 确认 RED。
> 2. 跑测试确认失败。
> 3. 实现（GREEN）：
>    - `index.html`：加 `#enc-i1-hint` 容器（默认 `display:none`）。
>    - `encounter.js`：`showView()` 用 `Promise.allSettled([fetchTexts(), fetchIndex()])`；索引成功 → `rankEntries(buildKnownSet(loadDeck(window.localStorage)), indexItems)` 与 `texts` 按 `id` 合并（**以 `texts` 为全集**：索引缺失的条目 `available=false` 仍要出现）；索引失败 → `ranked = null`，走原文顺序；`renderI1Hint` 只在 `hasCoverage(knownSet)` 且 `topPick` 非空时显示。
>    - `style.css`：`.enc-i1-badge` 三态配色（沿用既有 Editorial token，**不得新造硬编码色值**）；`.enc-i1-hint` 沿用 `.encounter-list` 的排版尺度；移动端断点补 `font-size`/`padding`，保证触屏目标与不贴边（参照 `.search-panel` 的移动端口径）。
> 4. 跑 `python -m pytest tests/test_encounter_ui_probes.py tests/test_frontend_module_graph.py tests/test_encounter_ui.py -q` 全绿；跑全探针零漂移。
> 5. REFACTOR：把「合并 texts 与 index」抽成具名函数（`mergeListWithIndex(texts, indexItems)`）并加 docstring；三态文案常量集中定义。
> **变异验证（必做并回报）**：① 让索引失败分支 rethrow → 降级用例必红；② 去掉 `esc()` → 断言必红；③ 把 `ranked` 当必需参数（无默认值）→ 降级路径用例必红。
> Return: Summary with test execution evidence + 变异验证结论。"
>
> **注意**：**不得**触碰 `workbench.html`（`test_german_workbench.py` 的字符串切片护栏）；**不得**改 `renderCoverage` / 阅读视图 / 进卡逻辑。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— 容器 / import 可达性 / `esc()` / 降级路径
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `index.html` + `encounter.js` + CSS（GREEN）**
- [ ] **Step 4: 跑 UI 契约 + 模块图测试全绿 + 执行三项变异验证**
- [ ] **Step 5: 抽具名函数 + 常量集中（REFACTOR）**
- [ ] **Step 6: 收尾门禁**（全探针零漂移 / ruff / mypy --strict）

---

### Task 6: 口径一致性端到端 + 收官回写（Phase B）[Role: TDD Builder]

**Files:**
- Create: `tests/test_encounter_i1_consistency.py`
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态节 + 测试基线）
- Modify: `CHANGELOG.md`（版本条目，**升序追加**）
- Modify: `FEATURES.md`（遇见区小节补 i+1 选材特性）

**Interfaces:**
- Consumes: `GET /api/encounter/texts/index`、`GET /api/encounter/texts/{id}/annotate`、`static/js/deck-bridge.js` 的判定规则（剥冠词 + 小写 + `reps>0`）
- Produces: 硬不变量 **I-1** 的自动化证据——同篇短文下，索引侧复算的 `rate` 与 annotate 侧复算的 `known_rate` **逐位相等**

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: 口径一致性端到端 + 收官回写。
> Goal: 用一条端到端测试钉死「预计算 lemma_seq 的口径 == 阅读视图 annotate 的口径」，防止未来任何一侧漂移；随后按项目文档纪律回写状态。
> Target Files: Create `tests/test_encounter_i1_consistency.py`, Modify `WORKMEMORY/PROJECT_OVERVIEW.md`, `CHANGELOG.md`, `FEATURES.md`.
> TDD Steps:
> 1. 写失败测试（RED）：TestClient 全链路。取一个预置包 → ① 打 `/annotate` 得 `sentences[].tokens[]`；② 用**纯 Python 复算** deck-bridge 规则（`stripGermanArticle` 同规则 + 小写 + `reps>0`）造 knownSet；③ 算 `annotate_rate = known_tokens / total_tokens`（标点计入分母、空白本就为空）；④ 打 `/texts/index` 取该篇 `total_tokens` / `lemma_seq`，用**同一个** knownSet 算 `index_rate`；⑤ `assert index_rate == annotate_rate`（**`==` 逐位，不用近似**）；⑥ 断言 `index["total_tokens"] == annotate["total_tokens"]`。先在**未实现**状态跑 → 必红（端点/字段缺失）。
> 2. 跑测试确认失败。
> 3. 若红源于真实口径差异（**不是**缺失），停下来把差异回报给编排者（**禁止**用近似/容差"修好"它——这正是本 Task 要抓的漂移）。
> 4. 全绿后收尾门禁：分半跑全量 pytest——
>    `export PYTHONIOENCODING=utf-8 && python -u -m pytest -q --ignore=tests/test_server.py`（半 A）+ `python -u -m pytest -q tests/test_server.py`（半 B）；再跑全探针、ruff、`python -m mypy --strict delector tools`。
> 5. 文档回写（**只改事实，不写过程**）：`PROJECT_OVERVIEW.md` 当前状态节的版本/测试基线/预置篇数（4 → 7）与新增能力；`CHANGELOG.md` 追加条目（升序，勿改历史）；`FEATURES.md` 遇见区小节补「i+1 就近选材」与「预置 7 篇」。
> Return: Summary with test execution evidence（含分半跑两段产物行）+ 文档改动清单。"
>
> **注意**：本 Task 完成后，**发版与 Android 覆盖安装不在本计划范围内**（改动含 `static/`，需走发版五件套，由主线程另行决策）。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** —— `index_rate == annotate_rate` + `total_tokens` 相等
- [ ] **Step 2: 跑测试确认失败**（或抓到真实漂移 → 立即上报，不得容差化）
- [ ] **Step 3: 修至全绿（若为缺失则无需生产代码改动，只补测试）**
- [ ] **Step 4: 分半跑全量 pytest + 全探针 + ruff + mypy --strict**
- [ ] **Step 5: 回写 `PROJECT_OVERVIEW.md` / `CHANGELOG.md` / `FEATURES.md`**
- [ ] **Step 6: 收尾门禁复核**

---

## 范围外 (Out of Scope)

- **B2 / TestDaF 语料预置**：`_ALLOWED_LEVELS` 保持 `("A1","A2","B1")`；B2 语料仍在仓库（`corpus_dict.py`），属 v4.8+「真题语料库预置」候选。
- **Go job#1 产包带 `lemma_seq`**：Go 侧契约不变；其产物在索引端点返回 `null`（降级不参与排序）。
- **服务端算覆盖率 / 把 knownSet 上传服务端**：违反已知判定本机红线，明确不做。
- **`annotate` 缓存化**：不动其「P0 直跑」策略。
- **阅读进度表 / 收藏 / 排序偏好持久化**：无状态派生，不做持久化。
- **发版与 Android 覆盖安装**：本计划只到"代码 + 测试 + 文档"；发版走五件套另行执行。

## 验证基线 (Verification Baseline)

| 阶段 | 命令 | 期望 |
|---|---|---|
| 每 Task | `python -m pytest <目标文件> -q` | 全绿 |
| 每 Task | `for f in tools/*.mjs; do node "$f" >/dev/null 2>&1 || echo FAIL $f; done` | 无 FAIL（零漂移） |
| 每 Task | `python -m ruff check .` / `python -m mypy --strict delector tools` | 0 告警 / 0 error |
| 收官 | 分半跑 pytest（半 A `--ignore=tests/test_server.py` + 半 B `tests/test_server.py`） | 基线 **1081 passed + 1 skipped** → 预计 **≈ 1100 passed + 1 skipped**（净增 6 Task 的用例；2 条既有 `exam_trials` Windows 环境失败在半 A 中保留，属既有） |
| 收官 | 预置篇数 | `PRESET_ENCOUNTER_PACKS` 长度 **7**，`levels 分布 A1:2, A2:2, B1:3` |
| 发版后（人工） | Android 覆盖安装 v 新版本 | 手机端可见 7 篇、徽章与推荐条正常、点开后覆盖率与列表徽章一致 |

## 回滚 (Rollback)

- **代码**：Task 1–6 逐 Task 原子提交（由主线程执行），任一步可 `git revert <sha>` 单点回滚。
- **数据模块**：`encounter_seed_dict.py` 为生成物 → 回滚只需 `python tools/build_encounter_seed.py --levels A1,A2 --created-at <原日期>` 重跑，或 revert 该文件提交。
- **存量库**：补装是**只增**语义，无 schema 迁移；若需撤销已补装的 3 篇，删除对应 `pack_id` 行即可，用户数据从未被修改。`app_settings["encounter_seed_version"]` 若需重触发补装，删除该键（或降 `PRESET_SEED_VERSION`）。
- **前端**：`renderTextList(texts)` 在**不传 `ranked`** 时逐字保持既有行为 → 索引端点异常/回退时前端自然退化，无需回滚代码。

## 关联索引

- `docs/specs/2026-09-23-encounter-i1-content-and-selection-design.md`（本计划的设计出处）
- `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态 / 红线速查）
- `08-Projects/DeLector/01-ADR/0010-encounter-zone-layered-go-agent-producer.md`
- `08-Projects/DeLector/01-ADR/0014-vocabulary-storage-boundary-and-a1-server-fetch.md`
- `01-Rules/STORED-DATA-BACKFILL.md` / `01-Rules/TESTING-PATTERNS.md`
