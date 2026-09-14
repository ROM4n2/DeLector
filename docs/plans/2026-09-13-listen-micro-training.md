# 听力微训工坊 Implementation Plan

> **Goal**: 构建统一听力微训引擎——精听/影子跟读（L）、听写诊断（D）、听力填空（C）三模式，复用 encounter 分级短文与 a1_hoeren 音频句库，成绩落 `listen_trials`。
> **Tech Stack**: Python 3.10+（FastAPI/SQLite）、原生 JS ES Modules（零构建）
> **Spec Reference**: [`docs/specs/2026-09-13-listening-micro-training-design.md`](file:///d:/Code/DeLector/docs/specs/2026-09-13-listening-micro-training-design.md)
> **Global Constraints**:
> - 零新依赖（桌面/Android 双端兼容）；Python 3.10+；UTF-8
> - 红线 10：切句仅用 `syntax_tree.split_sentences_pure_python()`，不造第二份
> - 红线 11：前端 body↔后端模型契约必须行为探针验证，字符串存在断言是死测
> - 红线 7：写操作守 `_require_localhost` 纪律（diagnose/trials 为本地数据非敏感，无需闸；新增端点遵守既有分类）
> - 门禁：`ruff check .` 零告警、Mypy 适度严格档零错误、全量 pytest 0 FAILED、模块图守卫、打包注册守卫（route/service 集更新）
> - 分支 `feature/listen-micro-training`，逐 Task 原子 commit，Conventional Commits 中文，禁 `--no-verify`；master 保持干净
> - maker-checker：vault-exec 派发（CPE maker 可写码跑测试 / CRV checker 只读红黄牌），主线程负责 git commit 与全量回归
> - 执行期不 push 远端；收尾 1 个 PR 合 master

---

### Task 1: 听写诊断引擎 `diagnose_diktat` [Role: TDD Builder]

**Files:**
- Create: `delector/services/listen.py`
- Test: `tests/test_listen_engine.py`

**Interfaces:**
- Consumes: 无（纯函数）；词级 LCS DP 思路参照 `static/js/writer.js:1040-1068`（Uint16 二维 DP）
- Produces:
  - `diagnose_diktat(expected: str, actual: str) -> ListenDiagnosis`
  - `ListenDiagnosis`（Pydantic）：`{expected, actual, tokens: list[TokenResult], correct: int, total: int, score: float}`
  - `TokenResult`：`{token: str, status: Literal["correct","umlaut","case","inflection","missing","extra"], hint: str}`

**行为规格**（照 v4.8.0 设计 §3.3 的 Umlaut/Case/Spelling/Missing 归因）：
- 词级切分：按空白分词；每词剥离首尾标点后比对（原始形式保留在 `token`）
- LCS 对齐（动态规划）→ 逐对归因：
  - 完全相同 → `correct`
  - 仅变音差（ü↔u、ä↔a、ö↔o、ß↔ss、é↔e）→ `umlaut`
  - 仅大小写差 → `case`
  - 词干相同、仅词尾差（去常见屈折尾 -en/-e/-er/-es/-n/-s 后一致）→ `inflection`
  - 期望有输入无 → `missing`；输入有期望无 → `extra`
- 归因优先级：完全匹配 > 变音 > 大小写 > 屈折 > missing/extra
- `hint` 给人话（如「变音：ü→u」「大小写」「词尾」「缺少」「多余」）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 1: 听写诊断引擎 diagnose_diktat。
> Goal: 在 `delector/services/listen.py` 实现词级 LCS 对齐 + 逐字分类归因纯函数。
> Target Files: Create `delector/services/listen.py`，Test `tests/test_listen_engine.py`。
> 规格：`docs/specs/2026-09-13-listening-micro-training-design.md` §3；归因行为见上文；Pydantic 模型输出；词级 LCS DP 参照 `static/js/writer.js:1040-1068`。
> TDD Steps:
> 1. 写失败测试 `tests/test_listen_engine.py`（RED）：覆盖 ü→u / der→Der / -en→-e / 缺漏 / 多余 / 完全正确 / 顺序错乱各一例，断言 status 与 hint。
> 2. 跑 `python -m pytest tests/test_listen_engine.py -q` 验证红。
> 3. 实现最小代码 `delector/services/listen.py`（GREEN）：纯标准库，不 import spacy/database；Pydantic v2 模型。
> 4. 全部绿后扁平化 guard clause（≤2 层）。
> Return: Summary with test execution evidence（红→绿输出）。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** — 七类归因各一例
- [ ] **Step 2: 跑测试验证红**
- [ ] **Step 3: 实现最小代码（GREEN）**
- [ ] **Step 4: 跑测试验证全绿**
- [ ] **Step 5: 扁平化 guard clause（≤2 层）**
- [ ] **Step 6: git 原子 commit**（`feat(listen): 听写诊断引擎 diagnose_diktat（词级 LCS 逐字归因）`）

---

### Task 2: 听力填空挖空 `make_cloze` [Role: TDD Builder]

**Files:**
- Modify: `delector/services/listen.py`（追加）
- Test: `tests/test_listen_engine.py`（追加）

**Interfaces:**
- Produces: `make_cloze(sentence: str, level: str) -> ClozeItem | None`
  - `ClozeItem`：`{text_with_blanks: str, answer: str, source: str, blank_index: int}`
  - 句子 <5 词或无可挖目标 → 返回 `None`

**行为规格**：
- 候选权重：句中非句首大写词（名词）优先，其次动词（常见词尾 -en/-n/-e + 非功能词）；功能词停用表（der/die/das/ein/und/ist…）排除
- 每次挖 1 个空（`___` 占位，原词保留为 `answer`）；`blank_index` = 原句词位
- `level` 预留（A1 只挖高频动词，A2 可挖名词），当前版本两档同策略、参数留口

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 2: 听力填空挖空 make_cloze。
> Goal: 在 `delector/services/listen.py` 追加 `make_cloze(sentence, level) -> ClozeItem | None`。
> Target Files: Modify `delector/services/listen.py`，Test `tests/test_listen_engine.py`。
> 规格：`docs/specs/2026-09-13-listening-micro-training-design.md` §3；行为见上文。
> TDD Steps:
> 1. 写失败测试（RED）：短句(<5词)返回 None；名词句挖名词；动词句挖动词；功能词不被挖；返回含 text_with_blanks/answer/blank_index。
> 2. 跑 `python -m pytest tests/test_listen_engine.py -q` 验证红。
> 3. 实现（GREEN）：纯标准库启发式，无 POS 依赖。
> 4. 全绿后扁平化。
> Return: Summary with test execution evidence。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 跑测试验证红**
- [ ] **Step 3: 实现最小代码（GREEN）**
- [ ] **Step 4: 跑测试验证全绿**
- [ ] **Step 5: 扁平化 guard clause**
- [ ] **Step 6: git 原子 commit**（`feat(listen): 听力填空挖空 make_cloze（启发式动词/名词优先）`）

---

### Task 3: `listen_trials` 表 + `/api/listen` 路由 [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py`（init_db 主库加 `listen_trials` 建表，幂等；backup/restore schema 清单 `"listen_trials"` 条目）
- Create: `delector/routes/listen.py`
- Modify: `delector/routes/__init__.py`（register_routes 挂 listen，在 main 之前）
- Test: `tests/test_listen_api.py`

**Interfaces:**
- 表 `listen_trials(id, mode, source_type, source_id, level, total, correct, score, duration_sec, created_at)` — 对齐 `exam_trials` 迁移/建表模式（`database.py:131`）
- 路由（prefix `/api/listen`）：
  - `GET /materials?level=` → `{items: [{source_type, source_id, title, level}]}`：聚合 encounter 短文（复用 encounter DB 查询：`encounter_texts` 表，title/level/content）+ a1_hoeren 音频句库（`a1_hoeren_dict` 题面 `audio_text_de`；**Step 0 侦察 `get_hoeren_set_by_id(sanitize=...)` 是否剥 audio_text_de，剥则走非 sanitize 数据路径**）
  - `GET /materials/{source_type}/{source_id}` → `{source_type, source_id, title, level, sentences: [str]}`：content 用 `syntax_tree.split_sentences_pure_python()` 切句（红线 10）
  - `POST /diagnose` body `{expected, actual}` → `ListenDiagnosis`（纯本地调用 `diagnose_diktat`，不挂闸）
  - `POST /trials` body `{mode, source_type, source_id, level, total, correct, duration_sec}` → `{trial_id}`（本地成绩记录，非敏感，不挂闸；字段校验 Pydantic）
  - `GET /trials?limit=50` → 最近历史（`{items: [...]}`）
- 打包注册守卫：routes 集追加 `listen`、services 集追加 `listen`（找到 `APP_NEEDLES`/注册守卫所在测试并更新）

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 3: listen_trials 表 + /api/listen 路由。
> Goal: 落 `listen_trials` 表与四端点（materials 聚合 / materials 详情切句 / diagnose 本地诊断 / trials 落盘查询）。
> Target Files: Modify `delector/core/database.py`、`delector/routes/__init__.py`，Create `delector/routes/listen.py`，Test `tests/test_listen_api.py`。
> 规格：`docs/specs/2026-09-13-listening-micro-training-design.md` §3/§4/§5。
> TDD Steps:
> 1. Step 0（侦察）：读 `delector/data/a1_hoeren_dict.py` 的 `get_hoeren_set_by_id`，确认 sanitize 对 `audio_text_de` 的影响；读 encounter DB 查询函数名（`encounter_texts` 表）。
> 2. 写失败测试（RED）：materials 聚合含 encounter+hoeren 且 level 过滤；详情返回切句 sentences；diagnose 形状；trials POST→GET 回读；TestClient host 必须 `("127.0.0.1", 54321)`（默认 testclient 会被本机闸拒，若挂闸）。测试隔离纪律：env 用 `setdefault`，不得删库文件（`delector/server.py:339` 模块级单例 app）。
> 3. 跑 `python -m pytest tests/test_listen_api.py -q` 验证红。
> 4. 实现（GREEN）：数据库建表（幂等）+ 路由挂载（`register_routes` 在 main 之前）+ 契约模型。
> 5. 更新打包/路由注册守卫测试（route 集 + service 集）。
> 6. 全绿后扁平化。
> Return: Summary with test execution evidence（含侦察结论）。

**Step Breakdown:**
- [ ] **Step 1: 侦察材料源可达性（hoeren sanitize 参数 / encounter DB 函数名）**
- [ ] **Step 2: 写失败测试（RED）**
- [ ] **Step 3: 跑测试验证红**
- [ ] **Step 4: 实现建表 + 路由 + 契约模型（GREEN）**
- [ ] **Step 5: 更新注册/打包守卫**
- [ ] **Step 6: 跑测试验证全绿**
- [ ] **Step 7: 扁平化 guard clause**
- [ ] **Step 8: git 原子 commit**（`feat(listen): listen_trials 表 + /api/listen 四端点（materials/diagnose/trials）`）

---

### Task 4: 前端微训工坊 `listen-lab.js` + 挂载 [Role: TDD Builder]

**Files:**
- Create: `static/js/listen-lab.js`
- Modify: `static/index.html`（备考域入口 + 容器）、`static/js/main.js`（视图映射）

**Interfaces:**
- 导出：`initListenLab()`、`selectMaterial(sourceType, id)`、`selectMode(mode)`、`startSession()`、`submitDictation()`、`renderDiagnosis(res)`、`finishSession(stats)` 等
- Consumes: `playGermanAudio(text, rate)`（`player.js`，三层 TTS 兜底）、`api(path, opts)`（`core.js`）
- 自管播放队列（不重构 reader ShadowPlayer）；会话令牌防陈旧响应（参照 `_reqToken` 语义）
- 三模式：
  - L 精听/影子跟读：句子列表逐句播 + 当前句高亮 + 变速(0.75x–1.25x)/重复/循环 + 跟读停顿
  - D 听写：隐藏文本 → 逐句播 → 输入框 → `POST /api/listen/diagnose` → 逐字六色胶囊反馈（correct/umlaut/case/inflection/missing/extra）
  - C 填空：`GET /api/listen/materials/...` 句子 → `POST /api/listen/diagnose`（或本地 make_cloze 镜像）挖空渲染 → 填答校验
- 会话结束：汇总 total/correct/duration → `POST /api/listen/trials`（失败静默降级不阻断）
- UI 对齐 Academic Modern Editorial token（tokens.css），移动端触控目标 ≥44px

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 4: 前端听力微训工坊 listen-lab.js。
> Goal: 三模式（L/D/C）控制器 + 材料选择 + 播放队列 + 逐字反馈渲染，挂进备考域。
> Target Files: Create `static/js/listen-lab.js`，Modify `static/index.html`、`static/js/main.js`。
> 规格：`docs/specs/2026-09-13-listening-micro-training-design.md` §2/§3/§4。
> 纪律：
> - 只复用 `playGermanAudio`（player.js）与 `api`（core.js），**不得重构 reader 的 ShadowPlayer**；播放队列在 listen-lab 内自管
> - 跨边界契约形状与后端模型逐字段一致（红线 11）
> - ES Module 命名导出；不新增 async IIFE 顶替定位记号（`test_german_workbench.py` 首现语义 —— 若 index.html 改动避免提前引入 `(async () => {` 等记号）
> - Editorial token 样式；不引入外部依赖
> Return: Summary with manual verification（起服务 `python start.py` 后手测三模式）。

**Step Breakdown:**
- [ ] **Step 1: 实现材料选择器 + 模式切换（L/D/C）**
- [ ] **Step 2: 实现播放队列（复用 playGermanAudio + 会话令牌）**
- [ ] **Step 3: 实现 Mode D 听写输入 + diagnose 提交 + 逐字反馈渲染**
- [ ] **Step 4: 实现 Mode C 填空渲染与校验 + Mode L 跟读停顿**
- [ ] **Step 5: 会话成绩汇总 + trials 落盘（静默降级）**
- [ ] **Step 6: 挂载 index.html + main.js**
- [ ] **Step 7: git 原子 commit**（`feat(listen): 前端微训工坊三模式（精听/听写/填空）+ 备考域挂载`）

---

### Task 5: 前端行为探针 + 模块图守卫 [Role: TDD Builder]

**Files:**
- Create: `tests/test_listen_lab_probe.mjs`（node:vm 直跑真源码，桩 fetch，参照既有 `tools/wb_sync_probe.mjs` 模式）
- Modify: `tests/test_frontend_module_graph.py`（纳入 `listen-lab.js` 依赖检查：非孤岛、无循环）

**契约钉死点（红线 11）：**
- `POST /api/listen/diagnose` body `{expected, actual}` / 响应 `{tokens:[{token,status,hint}], correct, total, score}`
- `POST /api/listen/trials` body 七字段 / 响应 `{trial_id}`
- `GET /api/listen/materials` 响应 `{items:[{source_type,source_id,title,level}]}`
- 模式切换/听写提交/反馈渲染/成绩汇总行为路径

**Subagent Prompt Scaffold (for /vault-exec):**
> Implement Task 5: 前端行为探针 + 模块图守卫。
> Goal: 用 node:vm 直跑 `static/js/listen-lab.js` 真源码，桩 fetch 钉死前端↔后端契约；更新模块图守卫。
> Target Files: Create `tests/test_listen_lab_probe.mjs`，Modify `tests/test_frontend_module_graph.py`。
> 纪律：契约形状逐字段断言；含「退回旧实现必红」变异验证（如改 diagnose 响应字段名应红）。
> Return: Summary with probe execution evidence。

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED，契约形状钉死）**
- [ ] **Step 2: 跑 node 探针验证**
- [ ] **Step 3: 更新模块图守卫并验证**
- [ ] **Step 4: git 原子 commit**（`test(listen): 前端行为探针 + 模块图守卫（红线 11 契约钉死）`）

---

### Task 6: 全量回归 + 文档回填 [Role: VERIFY]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态/测试基线/开放待办）、`WORKMEMORY/work.log`（WORK_END）、`FEATURES.md`（特性全览补听力微训）、`README.md` Roadmap（若到里程碑）

**验证命令：**
- `python -m pytest -q` 全量 → 0 FAILED
- `ruff check .` → 零告警
- `mypy` → 零错误
- `python -m pytest tests/test_frontend_module_graph.py tests/test_writer_mobile.py -q` → 守卫不退化
- Go 三门禁（未涉及 agent 代码则确认不受影响）
- 起服务手测三模式冒烟

**Step Breakdown:**
- [ ] **Step 1: 全量回归（pytest/ruff/mypy/守卫）**
- [ ] **Step 2: 起服务三模式手测冒烟**
- [ ] **Step 3: 文档回填（OVERVIEW/work.log/FEATURES）**
- [ ] **Step 4: git 原子 commit**（`docs(listen): 听力微训收官回填`）
- [ ] **Step 5: 收尾 1 个 PR 合 master**（maker-checker 证据齐）

---

## 阶段划分（vault-exec 派发粒度）

- **Phase 1**：Task 1–2（引擎，纯函数）
- **Phase 2**：Task 3（DB+API）
- **Phase 3**：Task 4–5（前端 + 探针）
- **Phase 4**：Task 6（回归 + 回填 + PR）

每 Task 由 CPE maker 实现 + CRV checker 只读验收，黄牌折入下 Task Step 0；主线程负责 git commit 与分片全量回归。

## 风险与边界

- **真机 TTS 未验证**：Android Chaquopy 真机 TTS 链路属发版后真机点检项（既有遗留并入）
- **hoeren 材料可达性**：Task 3 Step 0 侦察决定 sanitize 路径，若 `audio_text_de` 被剥则材料源仅 encounter
- **make_cloze 无 POS**：启发式可能误挖（功能词停用表兜底）；A2 名词策略留参数口
- **不扩大**：不建独立材料库、不预合成音频、不改 a1_hoeren 考试模式、不做波形可视化

---

## 执行状态（2026-09-14 收官，T1–T6 全绿）

- **门禁**：全量 pytest **788 passed + 1 skipped**（基线 751→788，净增 35：引擎 21 + API 9 + 探针 2 + 模块图 3）；`ruff check .` 零告警；mypy 零错误；模块图 / 切片 / 打包注册守卫全过；Go 三门禁不受影响。
- **maker-checker**：5/5 APPROVED（T4 一次 REWORK 已修复）。
- **逐 Task commit**：
  - T1 听写诊断引擎 `diagnose_diktat`（词级 LCS 逐字归因）→ `afc85e1`
  - T2 听力填空挖空 `make_cloze` → `809a335`（含黄卡修复：umlaut 大小写守卫 / 屈折最短词长）
  - T3 `listen_trials` 表 + `/api/listen` 四端点（materials/diagnose/trials）→ `ffe5daa`
  - T4 前端微训工坊三模式 + 备考域挂载 → `12220f7`
  - T5 前端行为探针 + 模块图守卫 → `2671588`
  - T6 全量回归 + 文档回填（本计划 + OVERVIEW / work.log / FEATURES / spec 同步）
- **偏差记录**：
  1. **Mode C 挖空实现为「前端本地镜像」而非服务端 `make_cloze` 调用**：`listen-lab.js` 在前端本地镜像同策略挖空（避免每句往返），行为等价，已由行为探针钉死契约（红线 11）；服务端 `make_cloze` 保留为纯函数供后端/工具复用，spec §3 已同步注明。
  2. **hoeren 材料经 sanitize 路径可取 `audio_text_de`**：Task 3 Step 0 侦察确认 `get_hoeren_set_by_id(sanitize=...)` 不剥 `audio_text_de`，材料源 encounter + hoeren 双源齐备，无需非脱敏路径。
- **遗留**：Android 真机 TTS 点检（发版后并入既有点检清单）；B 候选「语料长难句强化」待试用反馈拍板。
