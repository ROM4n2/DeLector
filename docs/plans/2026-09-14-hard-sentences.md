# 长难句精读工坊 Implementation Plan

> **Goal**: 构建长难句精读训练闭环——句子级难度评分（双路径分析）→ 跨语料挑选 → 前端句子卡片流（尝试拆解/揭示句法树/查词/入复习盒）→ `hard_sentence_trials` 落盘。
> **Tech Stack**: Python 3.10+（FastAPI/SQLite）、原生 JS ES Modules（零构建）
> **Spec Reference**: [`docs/specs/2026-09-14-hard-sentences-design.md`](file:///d:/Code/DeLector/docs/specs/2026-09-14-hard-sentences-design.md)
> **Global Constraints**:
> - 零新依赖（桌面/Android 双端兼容）；Python 3.10+；UTF-8
> - 红线 10：切句仅用 `syntax_tree.split_sentences_pure_python()`；红线 1：双路径分析必须标注 `path`（spacy/pure），纯路径降级时评分仅参考
> - 红线 11：前端 body↔后端模型契约必须行为探针验证
> - 红线 7：trials 为本地训练记录非敏感，不挂闸；入复习盒复用既有 `saveGrammar` 端点语义
> - 门禁：pytest 全量 0 FAILED、`ruff check .` 零告警、Mypy 零错误、模块图守卫、打包注册守卫（route/service 集更新）
> - 分支 `feature/hard-sentences`，逐 Task 原子 commit，Conventional Commits 中文，禁 `--no-verify`；master 保持干净
> - maker-checker：vault-exec 派发（CPE maker / CRV checker 只读红黄牌），主线程 commit + 全量回归；执行期不 push，收尾 1 个 PR

---

### Task 1: 句子难度评分 `score_sentence` + 级别估算 `estimate_level` [Role: TDD Builder]

**Files:**
- Create: `delector/services/syntax_score.py`
- Test: `tests/test_syntax_score.py`

**Interfaces:**
- Consumes: `analyze_syntax_tree` 输出 dict 形状（Step 0 侦察 `delector/nlp_engine/syntax_tree.py`）
- Produces:
  - `score_sentence(analysis: dict) -> SentenceScore`
  - `SentenceScore`（Pydantic v2）：`{score: float, level: str, dimensions: dict, path: Literal["spacy","pure"]}`
  - `estimate_level(score: float) -> str`（A1/A2/B1/B2 粗分带）

**行为规格**：
- 从 analysis 提取特征：clause_tree 最大深度、clause 数（从句复合度）、被动（is_passive）、虚拟式（is_subjunctive）、VL 句框（topology.sentence_type=="VL" 或 verb-last）、句长（词数）、关系从句
- 加权归一 → 0–100；维度明细进 `dimensions`（供前端 chips）
- `path` 从 analysis 携带（spaCy vs 纯 Python——红线 1 降级标注）
- `estimate_level`：分数带划分（如 <25→A1、25–45→A2、45–70→B1、>70→B2，具体阈值 TDD 定）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 1: 句子难度评分 score_sentence + estimate_level。
> Goal: 在 `delector/services/syntax_score.py` 实现句子级难度评分纯函数。
> Target Files: Create `delector/services/syntax_score.py`，Test `tests/test_syntax_score.py`。
> 规格：`docs/specs/2026-09-14-hard-sentences-design.md` §3。
> TDD Steps:
> 1. Step 0 侦察：读 `d:\Code\DeLector\delector\nlp_engine\syntax_tree.py` 的 `analyze_syntax_tree`/`analyze_sentence_topology` 输出形状（clause_tree/topology/features 字段），用真实小样本（如 `python -c` 跑一句）确认可提取的特征键。
> 2. 写失败测试 `tests/test_syntax_score.py`（RED）：构造最小 analysis fixture，断言各维度特征→分映射（深度↑分↑、被动/虚拟式/VL 命中加分、句长↑分↑）、`estimate_level` 带划分边界、path 透传。
> 3. 跑 `python -m pytest tests/test_syntax_score.py -q`（仓库根，先 `$env:PYTHONIOENCODING="utf-8"`）验证红。
> 4. 实现最小代码（GREEN）：纯标准库 + Pydantic v2，不 import spacy/database。
> 5. 全绿后扁平化 guard clause（≤2 层）。
> 约束：零新依赖；注释中文；`python -m ruff check <两文件>` 与 `python -m mypy <新文件>` 零告警；只改这两个文件，禁止 git commit。
> Return: Summary with test execution evidence（红→绿输出）+ 侦察到的 analysis 特征键清单。

**Step Breakdown:**
- [ ] **Step 1: 侦察 analysis 输出形状（特征键）**
- [ ] **Step 2: 写失败测试（RED）**
- [ ] **Step 3: 跑测试验证红**
- [ ] **Step 4: 实现最小代码（GREEN）**
- [ ] **Step 5: 扁平化 guard clause**
- [ ] **Step 6: git 原子 commit**（`feat(syntax): 句子难度评分 score_sentence + 级别估算 estimate_level`）

---

### Task 2: 全文切句评分 `rank_sentences` [Role: TDD Builder]

**Files:**
- Modify: `delector/services/syntax_score.py`（追加）
- Test: `tests/test_syntax_score.py`（追加）

**Interfaces:**
- Produces: `rank_sentences(text: str) -> list[SentenceScore]`（每项含 `sentence` 原文 + score/level/dimensions/path）

**行为规格**：
- `split_sentences_pure_python(text)` 切句（红线 10，唯一实现）
- 逐句 `analyze_syntax_tree(sent)`（双路径函数）→ `score_sentence` → 降序
- 空文本/单句/异常句容错（异常句跳过或 path="pure" 兜底，不炸整批）
- 返回含原文 `sentence` 字段

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 2: 全文切句评分 rank_sentences。
> Goal: 在 `delector/services/syntax_score.py` 追加 `rank_sentences(text) -> list[SentenceScore]`。
> Target Files: Modify `delector/services/syntax_score.py`，Test `tests/test_syntax_score.py`。
> 规格：`docs/specs/2026-09-14-hard-sentences-design.md` §3。
> TDD Steps:
> 1. 写失败测试（RED）：三段含难句文本 → 断言返回降序、首条为最难、每项含 sentence/score/path；红线 10 断言（内部调用 `split_sentences_pure_python`，用 monkeypatch 或特征串验证无自造切句）。
> 2. 跑 `python -m pytest tests/test_syntax_score.py -q` 验证红。
> 3. 实现（GREEN）：复用 T1 评分。
> 4. 全绿后扁平化。
> 约束：只改两文件；零告警；禁止 git commit。
> Return: Summary with test execution evidence + 性能观察（N 句耗时量级）。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED，含红线 10 断言）**
- [ ] **Step 2: 跑测试验证红**
- [ ] **Step 3: 实现最小代码（GREEN）**
- [ ] **Step 4: 跑测试验证全绿**
- [ ] **Step 5: 扁平化 guard clause**
- [ ] **Step 6: git 原子 commit**（`feat(syntax): 全文切句评分 rank_sentences（红线 10 切句 + 双路径标注）`）

---

### Task 3: `hard_sentence_trials` 表 + `/api/syntax` 三端点 [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py`（init_db 加 `hard_sentence_trials` 幂等建表 + backup/restore schema 清单）
- Create: `delector/routes/syntax_hard.py`
- Modify: `delector/routes/__init__.py`（register_routes 挂 syntax_hard，main 之前）
- Test: `tests/test_syntax_hard_api.py`

**Interfaces:**
- 表 `hard_sentence_trials(id, source, source_id, sentence_index, level, score, revealed, duration_sec, created_at)` — 对齐 `listen_trials` 模式
- 路由（prefix `/api/syntax`）：
  - `GET /hard-sentences?source=&source_id=&level=&min_score=&limit=` → `{items:[{sentence, score, level, dimensions, path, source, source_id, sentence_index}]}`；source ∈ article/encounter/all；进程内存缓存（键=source+id，TTL 短）+ limit 护栏（默认 ≤50）
  - `GET /hard-sentences/detail?source=&source_id=&sentence_index=` → 单句完整分析（clause_tree/topology/词元）；404 人话
  - `POST /hard-sentence/trials` body `{source, source_id, sentence_index, level, score, revealed, duration_sec}` → `{trial_id}`（不挂闸）
- 材料访问：Step 0 侦察 articles（content/processed 字段）与 `encounter_texts` 的 DB 查询函数（复用 encounter 既有 helper）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 3: hard_sentence_trials 表 + /api/syntax 三端点。
> Goal: 落 `hard_sentence_trials` 表与三个端点（hard-sentences 列表 / detail / trials）。
> Target Files: Modify `delector/core/database.py`、`delector/routes/__init__.py`，Create `delector/routes/syntax_hard.py`，Test `tests/test_syntax_hard_api.py`。
> 规格：`docs/specs/2026-09-14-hard-sentences-design.md` §3/§4/§5。
> TDD Steps:
> 1. Step 0 侦察：articles 表与 `encounter_texts` 的 DB helper（列表函数/内容字段）；`syntax_score.rank_sentences` 可复用性。
> 2. 写失败测试（RED）：hard-sentences 列表（article/encounter/all、level 过滤、min_score、limit）、detail 形状与 404、trials POST→GET 回读；TestClient `("127.0.0.1", 54321)`；env `setdefault` 隔离、不删库文件（`server.py:339` 模块级单例）。
> 3. 跑 `python -m pytest tests/test_syntax_hard_api.py -q` 验证红。
> 4. 实现（GREEN）：建表 + 路由 + 内存缓存 + 契约模型（复用 `SentenceScore`）。
> 5. 更新注册/打包守卫（route 集 + service 集 + APP_NEEDLES 若需）。
> 6. 全绿后扁平化。
> 约束：零新依赖；ruff/mypy 零告警（涉及文件全查）；禁止 git commit。
> Return: Summary with test execution evidence + 侦察结论。

**Step Breakdown:**
- [ ] **Step 1: 侦察材料源 DB helper**
- [ ] **Step 2: 写失败测试（RED）**
- [ ] **Step 3: 跑测试验证红**
- [ ] **Step 4: 实现建表 + 路由 + 契约模型（GREEN）**
- [ ] **Step 5: 更新注册/打包守卫**
- [ ] **Step 6: 跑测试验证全绿**
- [ ] **Step 7: 扁平化 guard clause**
- [ ] **Step 8: git 原子 commit**（`feat(syntax): hard_sentence_trials 表 + /api/syntax 三端点 + 守卫同步`）

---

### Task 4: 前端长难句精读工坊 `hard-sentences.js` + 挂载 [Role: TDD Builder]

**Files:**
- Create: `static/js/hard-sentences.js`
- Modify: `static/index.html`（备考域「✍️ 长难句」带 + 容器）、`static/js/main.js`（视图映射）

**Interfaces:**
- 导出：`initHardSentences()`、`selectSource()`、`loadCards()`、`revealSentence(idx)`、`addToReviewBox(item)`、`finishSession(stats)` 等
- Consumes: `api()`（core.js）、`saveGrammar`（既有复习盒流程，Step 0 确认端点路径）、查词链路（`/api/lookup/vocab` 或 reader 查词抽屉形态）
- 句子卡片流：原句（难度分/级别/chips）→「尝试拆解」隐藏句法树 → 揭示（渲染 clause_tree，参照 ADR-0007 抽屉形态）→ 查词 → 「加入复习盒」（同句已入盒显示「已加入」）→ 下一句
- 会话成绩：`POST /api/syntax/hard-sentence/trials`（失败静默降级）
- UI：Editorial token、触控 ≥44px、零外部依赖；A1/A2 门控默认（默认 A2+，可切全部）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 4: 前端长难句精读工坊 hard-sentences.js。
> Goal: 三流程控制器（选源→卡片流→拆解/揭示/查词/入盒）+ 备考域挂载。
> Target Files: Create `static/js/hard-sentences.js`，Modify `static/index.html`、`static/js/main.js`。
> 规格：`docs/specs/2026-09-14-hard-sentences-design.md` §2/§3/§4。
> Step 0 侦察：`saveGrammar` 的端点与卡字段（`static/js/main.js` 导出 + writer.js/reader.js 调用处）；查词链路端点。
> 纪律：
> - 不重构既有模块（reader/encounter/listen-lab 零改动；只 index.html/main.js 追加式修改）
> - 跨边界契约字段与后端模型逐字一致（红线 11）
> - ES Module 命名导出；不引入 `(async () => {` 顶替定位记号（`test_german_workbench.py` 语义——先确认它只解析 german/workbench.html）
> - Editorial token 样式；零外部依赖
> Return: Summary with manual verification（起服务 `python start.py` 手测卡片流）。

**Step Breakdown:**
- [ ] **Step 1: 侦察 saveGrammar 端点/卡字段 + 查词链路**
- [ ] **Step 2: 实现材料源选择 + 句子卡片流（难度分/级别/chips）**
- [ ] **Step 3: 实现尝试拆解→揭示句法树 + 查词**
- [ ] **Step 4: 实现入复习盒（复用 saveGrammar）+ 会话成绩落盘**
- [ ] **Step 5: 挂载 index.html + main.js**
- [ ] **Step 6: git 原子 commit**（`feat(syntax): 前端长难句精读工坊（选源/卡片流/拆解揭示/入盒）+ 备考域挂载`）

---

### Task 5: 前端行为探针 + 模块图守卫 [Role: TDD Builder]

**Files:**
- Create: `tests/test_hard_sentences_probe.mjs`（node:vm 直跑真源码，参照 `tests/test_listen_lab_probe.mjs` 模式）+ `tests/test_hard_sentences_probe.py`（pytest 驱动）
- Modify: `tests/test_frontend_module_graph.py`（纳入 `hard-sentences.js`）

**契约钉死点（红线 11）：**
- `GET /api/syntax/hard-sentences` 响应 `{items:[{sentence, score, level, dimensions, path, source, source_id, sentence_index}]}`
- `GET /api/syntax/hard-sentences/detail` 响应含 `clause_tree`/`topology`
- `POST /api/syntax/hard-sentence/trials` body 七字段 / 响应 `{trial_id}`
- 行为路径：选源 → 卡片流 → 拆解揭示 → 入盒调用（saveGrammar 桩）→ 成绩汇总
- 变异验证 ≥1（改字段名探针必红）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 5: 前端行为探针 + 模块图守卫。
> Goal: node:vm 直跑 `static/js/hard-sentences.js` 真源码钉死契约 + 模块图纳入。
> Target Files: Create `tests/test_hard_sentences_probe.mjs`、`tests/test_hard_sentences_probe.py`，Modify `tests/test_frontend_module_graph.py`。
> 参照：`tests/test_listen_lab_probe.mjs`（vm.SourceTextModule + 桩依赖 + 变异验证）。
> 纪律：逐字段断言；变异 ≥1；桩 saveGrammar/查词依赖；node 缺失显式 skip。
> Return: Summary with probe execution evidence。

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED，契约钉死）**
- [ ] **Step 2: 跑 node 探针验证**
- [ ] **Step 3: 更新模块图守卫并验证**
- [ ] **Step 4: git 原子 commit**（`test(syntax): 前端行为探针 + 模块图守卫（红线 11 契约钉死）`）

---

### Task 6: 全量回归 + 文档回填 + PR [Role: VERIFY]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`（WORK_END）、`FEATURES.md`、`docs/plans/2026-09-14-hard-sentences.md`（执行状态块）、`docs/specs/2026-09-14-hard-sentences-design.md`（偏差注记若有）

**验证命令：**
- `python -m pytest -q` 全量 → 0 FAILED（基线 788+1 + 新增）
- `ruff check .` / `mypy` → 零告警零错误
- `python -m pytest tests/test_frontend_module_graph.py tests/test_writer_mobile.py -q` → 守卫不退化
- 起服务手测卡片流冒烟

**Step Breakdown:**
- [ ] **Step 1: 全量回归**
- [ ] **Step 2: 起服务冒烟**
- [ ] **Step 3: 文档回填（OVERVIEW/work.log/FEATURES/计划状态块）**
- [ ] **Step 4: git 原子 commit**
- [ ] **Step 5: 收尾 1 个 PR 合 master**（maker-checker 证据齐）

---

## 阶段划分（vault-exec 派发粒度）

- **Phase 1**：Task 1–2（评分引擎，纯函数）
- **Phase 2**：Task 3（DB+API）
- **Phase 3**：Task 4–5（前端 + 探针）
- **Phase 4**：Task 6（回归 + 回填 + PR）

每 Task CPE maker + CRV checker，黄牌折入下 Task Step 0；主线程 commit 与分片全量回归。

## 风险与边界

- **红线 1 降级精度**：纯 Python 路径评分仅参考（path 标注），真机/桌面 spaCy 路径为主
- **性能**：全文逐句分析重计算——内存缓存 + limit 护栏；大语料首拉延迟可接受（懒算）
- **复习盒**：复用 `saveGrammar`/`grammar_cards`，不新建卡种表（scope 收敛）
- **不扩大**：不建长难句题库、不持久化句子特征、不改 Grammatik-Radar 既有展示
