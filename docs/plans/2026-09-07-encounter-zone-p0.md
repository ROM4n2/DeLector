# Sub-Plan A: 遇见区 P0 最小版（Python + 原生 ES 前端）

> **Goal**: 「遇见区」P0 上线——手选分级短文本 → 阅读视图把**已背词**高亮（按本机背词工作台 deck 判定）→ 生词点选看本地词典释义 → 一键进卡（写回 deck + wb 同步）→ 读完新词小复习。桌面源码实例与 Android Chaquopy 实例同源可用。
> **Tech Stack**: Python 3.11 / FastAPI / spaCy / SQLite（读侧沿用既有 `nlp_engine` + `articles` 同库表纪律）/ 原生 ES（index.html + `static/js/*.js`）
> **Spec Reference**: ADR-0010 §4 北星 / §5 边界（交互留 Python）；Master `docs/plans/2026-09-07-encounter-zone-and-dag-job1-program.md`
> **Global Constraints**:
> - **交互不离开本机**：已背词判定只在本机 deck（localStorage `wb.words.v1`/`wb.cards.v1`，服务端镜像 `GET /api/wb/state` 兜底）；任何写操作过本机既有 `_require_localhost` / `X-WB-Key` 闸。
> - **不碰既有测试切片**：`test_german_workbench.py` 对 workbench.html 的字符串切片断言（禁 async IIFE 定位记号）；改/加 index.html 与 JS 后必须全量 `pytest -v` + 前端模块图测试（`test_frontend_module_graph.py`）通过。
> - **analyze/既有 NLP 契约零漂移**：A3 annotate 若需暴露 per-token lemma，只能**加法新增**函数/字段，不得改 `process_german_text` 返回结构（`tests/test_tools.py` 钉 analyze 形状）。
> - 语料持久化与 `articles` 同库（阅读域）；新增表/函数放置位置以 CPE 读代码为准，遵循同库同文件注释风格。
> - 全部 Task：`export PYTHONIOENCODING=utf-8`；`pytest -v` 于仓库根。

---

## Task A1: `encounter_texts` 表 + 存储层 [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py`（与 `articles` 同 schema 块加建表 + 幂等索引；镜像 `get_wb_state` 风格加 CRUD 函数）
- Test: `tests/test_encounter_store.py`（新建）

**Interfaces:**
- Consumes: 既有 db conn/路径注入约定（与 articles/vocab_cards 同源；测试用临时库）
- Produces:
  ```python
  # 建表（progress/阅读库，与 articles 同 conn 同批次）
  encounter_texts(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pack_id TEXT UNIQUE,          -- job#1 import 来源标识，手工文本为 NULL
      title TEXT NOT NULL,
      level TEXT NOT NULL DEFAULT 'A2',   -- A1/A2/B1 建议阅读等级
      source TEXT DEFAULT '',
      content TEXT NOT NULL,              -- 纯文本（按段落 \n\n 存）
      pack_json TEXT,                     -- import-pack 附带的 cardpack 元数据
      created_at TEXT DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_encounter_level ON encounter_texts(level);
  ```
  ```python
  def list_encounter_texts(level: Optional[str]=None, db_path=None) -> list[dict]
  def get_encounter_text(text_id: int, db_path=None) -> dict | None
  def create_encounter_text(title, level, source, content, pack_id=None, pack_json=None, db_path=None) -> int
  def import_encounter_pack(pack: dict, db_path=None) -> int   # 幂等：pack_id 已存在直接返回既有 id
  ```

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task A1: encounter_texts 存储层.
> Goal: 建表 + 4 个纯 DB 函数，供后续 /api/encounter 路由与 job#1 import-pack 使用.
> Target Files: Modify `delector/core/database.py`（先读文件定位 articles 的建表块与读写函数风格，新表放同库同批次，索引幂等）, Test 新建 `tests/test_encounter_store.py`.
> TDD Steps:
> 1. 先写测试（临时库 fixture，参照同文件既有 db 测试的临时库/close 纪律，含 Windows gc.collect 句柄教训）：list 空、create→get 回读、level 过滤、import 幂等（同 pack_id 两次返回同一 id）。
> 2. 跑 `pytest tests/test_encounter_store.py` 验证 RED。
> 3. 实现最小代码（函数级 Guard Clause 最多 2 层）。
> 4. 跑测试验证 GREEN；再跑全量 `pytest -v`（确认建表幂等不与既有库冲突）。
> Return: 测试执行证据（点名 + 通过数）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 跑 `pytest tests/test_encounter_store.py` 验证失败
- [ ] Step 3: database.py 最小实现（GREEN）
- [ ] Step 4: 单文件 + 全量 pytest 验证
- [ ] Step 5: Guard Clause 拍平 + 幂等复查
- [ ] Step 6: git 原子提交 push

---

## Task A2: `/api/encounter/*` 路由模块 [Role: TDD Builder]

**Files:**
- Create: `delector/routes/encounter.py`（镜像 `corpus.py`：`APIRouter(prefix="/api/encounter", tags=["Encounter"])`）
- Modify: `delector/routes/__init__.py`（import 列表 + `register_routes` 中 `include_router(encounter.router)`，**放在 main 之前**，与 corpus 相邻）
- Test: `tests/test_encounter_routes.py`（新建，TestClient 全链路）

**Endpoints:**
```text
GET  /api/encounter/texts                       → {"texts":[{id,title,level,source,word_count,created_at}]}
GET  /api/encounter/texts/{text_id}             → {id,title,level,source,content,pack_json}
POST /api/encounter/texts  (_require_localhost) → 手工加文本 {title,level,source,content} → 201 {id}
```

**Interfaces / 契约:** word_count = 简单空白分词计数（测试断言用）；404 语义与既有模块一致；POST body 用 Pydantic model；`_require_localhost` 从 `delector.core.database` 导入做 `Depends`（与 `tools.py` 同法）。**同时把 cardpack JSON schema `encounter-pack/v1` 定在这里（两端一致契约，Master §跨子计划契约）**：写清必填键并在本 Task 内用一个纯校验函数 `validate_pack(pack)->None`（抛 ValueError）+ 测试；import 落库函数体在 A6/B 侧由 route 复用（B 完成前可先只实现 validate + 返回 501 stub？——不：为让 B 集成先行，本 Task 即实现完整 `POST /api/encounter/import-pack`（_require_localhost），走 database.import_encounter_pack；A7/B 门禁共用）。

**Subagent Prompt Scaffold:**
> "Implement Task A2: /api/encounter 路由 + import-pack.
> Goal: 文本列表/详情/本机新增 3 端点 + import-pack（校验 encounter-pack/v1 后落库）.
> Target Files: Create `delector/routes/encounter.py`, Modify `delector/routes/__init__.py`, Test 新建 `tests/test_encounter_routes.py`.
> 关键既有事实：路由模块样板在 `delector/routes/corpus.py`；注册点在 routes/__init__.py register_routes（main 必须最后）；_require_localhost 用法见 routes/tools.py；cardpack schema 字段：schema=encounter-pack/v1, pack_id, source{...}, article{title,raw_text,char_count}, analysis{tokens_total,known_count,known_rate,level_hint,unknown_lemmas[]}, glosses[{lemma,gloss_zh,cefr}], estimated_cefr。import 时 title/article.title, level=estimated_cefr 归一(大写化+仅 A1/A2/B1 白名单), content=article.raw_text, pack_json=整包序列化。
> TDD Steps:
> 1. 写失败测试（TestClient + 临时库 autouse fixture 参照 tests/test_server.py clean_db 纪律；_require_localhost 用 127.0.0.1 client）。
> 2. RED → 3. 最小实现 → 4. GREEN + `pytest -v`（确认 register 守卫 test_register_routes_covers_every_module_in_routes_package 过）。
> Return: 测试证据 + 守卫测试名确认。"

**Step Breakdown:**（同 A1 六步，RED→GREEN→REFACTOR→提交）

---

## Task A3: 逐词注解端点 `GET /api/encounter/texts/{id}/annotate` [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/encounter.py`（加端点）
- Modify（加法）: `delector/nlp_engine/`（若 processor 未暴露 per-token lemma：新增只读函数，如 `tokenize_with_lemma(text) -> [{text,lemma,pos}]`，**不改既有返回值结构**）
- Test: `tests/test_encounter_annotate.py`（新建）+ 确保 `tests/test_tools.py` analyze 契约不变

**Response shape（定死，供前端 Task A4/A5 用）:**
```json
{ "text_id": 1, "total_tokens": 120,
  "sentences": [ {"idx": 0, "tokens": [ {"text":"geht","lemma":"gehen","pos":"VERB"} ] } ] }
```
失败语义：text 不存在 404。性能：P0 直跑 spaCy，可接受；禁引入缓存复杂度。

**Subagent Prompt Scaffold:**
> "Implement Task A3: annotate 端点.
> Goal: 对 encounter_texts 正文产出逐句逐 token lemma+pos，前端据此做已背词匹配.
> Target Files: Modify `delector/routes/encounter.py` + `delector/nlp_engine/`（加法新增, 绝不动 analyze 依赖的返回值形状）; Test 新建 `tests/test_encounter_annotate.py`.
> TDD Steps:
> 1. 测：先看 nlp_engine.processor 现返回 sentences 里是否已含 per-token lemma/pos——若有直接映射到新 shape（无处理器改动）；若没有，给处理器加只读导出函数并单测它。红灯先钉响应 shape 与 'geht'→lemma 'gehen'（de_core_news_sm 真实词形）。
> 2. RED → 3. GREEN → 4. `pytest tests/test_encounter_annotate.py tests/test_tools.py` + 全量。
> Return: 是否需改 nlp_engine 的结论 + 测试证据。"

---

## Task A4: 遇见区 SPA 视图骨架（列表/详情/加文本表单）[Role: TDD Builder]

**Files:**
- Modify: `static/index.html`（德语文库 view-home 内加「遇见区 i+1 短文」入口卡 + 新 `<main id="view-encounter" class="view">`；不新增顶部 nav 按钮，避免导航拥挤与切片漂移）
- Create: `static/js/encounter.js`（ES module：`fetchTexts()/fetchText(id)/submitAddText()` + `renderTextList/renderTextDetail`；页面显隐回调挂到 main.js 的 show() 约定——先读 `static/js/main.js` 看 view 切换与模块挂载约定）
- Modify: `static/js/main.js`（import './encounter.js' 并注册视图初始化，满足 `test_frontend_module_graph.py` 可达性）
- Test: `tests/test_frontend_module_graph.py` 兼容 + 新增字符串探针（在 `tests/test_encounter_ui_probes.py`：断言 index.html 含 view-encounter 入口、encounter.js 被 main.js import；**勿加 async IIFE 定位记号**）

**UI 最低规格（P0，朴素可用，不引入新设计体系）:** 列表卡（title + level 徽 + word_count）→ 点开详情页：标题 + 段落正文（纯 `<p>`）→ 顶栏「＋ 加一篇短文」表单（title/level/source/content textarea）→ 提交调本地 POST（失败提示非 500 页）。

**Subagent Prompt Scaffold:**
> "Implement Task A4: 遇见区视图骨架.
> Goal: index.html 加 view-encounter 与入口，encounter.js 提供列表/详情/加文本，串通 main.js.
> Target Files: Modify static/index.html + static/js/main.js, Create static/js/encounter.js, Test 新建 tests/test_encounter_ui_probes.py.
> TDD 纪律：前端不可跑 pytest 单测体，用字符串探针 + 手动 smoke（见 Step 5）。注意 test_german_workbench.py 是对 workbench.html 的（勿动）；test_frontend_module_graph.py 要求新增 module 被 main 引用可达。
> Steps:
> 1. 探针测试 RED（断言 index.html 有 #view-encounter、main.js 引用 ./encounter.js、入口元素存在）。
> 2. 实现 index.html 结构 + main.js import/挂载 + encounter.js 最小列表/详情/表单（fetch + innerHTML 模板串）。
> 3. 探针 GREEN + `pytest -v`（重点 test_frontend_module_graph / test_server / test_german_workbench 不漂移）。
> 4. 手工 smoke：`python start.py` 后浏览器开列表→详情→表单提交（TestClient 亦可模拟 POST 建行后断言渲染数据源接口正确）。
> Return: 探针与全量 pytest 证据 + smoke 结论。"

---

## Task A5: 已背词高亮 + 覆盖统计（本机 deck 桥）[Role: TDD Builder]

**Files:**
- Create: `static/js/deck-bridge.js`（纯逻辑 module，无 DOM，便于断言）
- Modify: `static/js/encounter.js`（详情渲染接 deck-bridge + A3 annotate 数据）
- Test: `tests/test_encounter_deck_bridge.py`（新建：把 deck-bridge 纯函数以 `node --input-type=module` 或既有 tools/*.mjs 探针方式跑断言——先读现有 `tools/wb_sync_probe.mjs` 的 node:vm 切真源码模式复用）

**Deck 桥语义（定死，两端一致）:**
- deck 权威 = localStorage `wb.words.v1`（word 数组，元素 `{id,hw,...}`）+ `wb.cards.v1`（`{wordId: {s,d,reps,lapses,due,last}}`）；兜底源 = `GET /api/wb/state` 的 payload.words/cards（本地存空时用）。
- **known(lemma)** = 存在 word 且 `cards[word.id].reps > 0`（归一：lemma 小写、德语 ß/ss 不特殊处理、hw 与 lemma 直接比对）。
- annotate 返回 token.lemma → 客户端命中 known → 高亮 class `enc-known`；未命中记为 unknown。给出 per-text 覆盖统计：`{total_tokens, known_tokens, known_rate, unknown_lemmas_top:[...]}`。
- 纯函数 API（全部可测）：`loadDeck()`, `isKnown(deck, lemma)`, `annotateWithDeck(deck, annotateResp) -> {tokens_classified, stats}`, `mergeKnownFromServer(deck, wbStatePayload)`。

**Subagent Prompt Scaffold:**
> "Implement Task A5: deck-bridge + 高亮.
> Goal: 纯 JS 层把 A3 annotate lemma 流按本机 deck 判定 known 并给统计；encounter.js 据此渲染高亮.
> Target Files: Create static/js/deck-bridge.js, Modify static/js/encounter.js, Test 新建 tests/test_encounter_deck_bridge.py（用 tools/ 既有 mjs 探针执行风格：node:vm 载入真源码 + 桩 fetch/localStorage）.
> TDD Steps:
> 1. RED：已知夹具（words:[{id:'a1-0001',hw:'gehen'}] + cards:{'a1-0001':{reps:3}}）对 'geht'(lemma gehen) 判 known、reps=0 判 unknown、无卡判 unknown、覆盖统计精确值。
> 2. 实现 deck-bridge 纯函数。
> 3. GREEN + 探针全绿。
> 4. encounter.js 接上高亮渲染（token span class + 统计行），手工 smoke 一篇短文。
> Return: 探针证据 + 渲染 smoke 结论。"

---

## Task A6: 生词释义弹层 → 一键进卡 → 读完小复习 [Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js`（未知 token 点击→弹层；「加入卡片」按钮；读完底部小复习区）
- Modify（如需）: `delector/routes/encounter.py`（不预期新增端点——释义复用既有 `POST /api/lookup/vocab` 词典查询；进卡复用既有 `PUT /api/wb/state`（X-WB-Key，从本机 GET /api/wb/state/key 取的既有流程））
- Test: `tests/test_encounter_addcard.py`（新建：探针断言 进卡=写入 deck 存储 keys 正确形状 + 触发同步；纯函数层面测）

**P0 语义（定死）:**
- 点击未知词 → 弹层调 `POST /api/lookup/vocab`（既有词典管线）取 gloss；无命中则显示「未收录」+ 鼓励仍可进卡（gloss 留空待背词台补）。
- 「加入卡片」= 写 deck：word 不存在则追加 `{id: genId('en-'+hash8), hw:lemma, pos, gloss:查得或'', custom:true}`；cards 建初始 `{reps:0, due:今天ISO}`（保证下次开工作台进复习队列）；随后触发 `PUT /api/wb/state` 同步本机服务端镜像（沿用 workbench 既有 payload 组装，勿重造）。
- 小复习 = 本会话加入词列表底卡：正面词 / 反面 gloss + 发音（`GET /api/audio/tts?text=..` 既有端点）翻转即可，不进 FSRS（FSRS 在背词台）。

**Subagent Prompt Scaffold:**
> "Implement Task A6: 释义/进卡/小复习.
> Goal: 未知词点开见本地词典释义，一键写回 deck（含触发 wb 同步），读完回顾新词.
> Target Files: Modify static/js/encounter.js（主要）; Test 新建 tests/test_encounter_addcard.py（纯函数 + 探针；参考 A5 mjs 探针法, deck 写入形状与 PUT 触发为断言点）.
> TDD Steps:
> 1. RED（纯函数：加词→新 word/card 形状正确、幂等不重复加、PUT 触发条件）。
> 2. 实现 + 接线既有 /api/lookup/vocab、/api/wb/state 语义（先读 workbench.html 里 add 自定义词与 wb payload 组装的真实代码，别发明新协议）。
> 3. GREEN + `pytest -v` + 手工双端 smoke。
> Return: 证据 + 进卡落 deck 的 smoke 结论（含重开工作台可见）。"

---

## Task A7: 收尾——全量回归 + 双端清单 + 文档 [Role: TDD Builder]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（状态节加遇见区 P0）、README 路线图（若该节存在）、Master 状态块回填
- Test: 全量 `pytest -v`（含模块图/切片守卫/register 守卫）

**交付物:** 验收门 A 侧全部勾绿（除依赖 B 的 import-pack 真链路，留 B 门禁）；Android Chaquopy 手工清单写入手工 smoke 文档（步骤：装 App→工作台背 3 词（≥reps 1）→遇见区加一篇短文→打开→断言已背词高亮与覆盖数→生词进卡→重开工作台见卡）。

**Subagent Prompt Scaffold:**
> "Implement Task A7: 收尾.
> Goal: 全量回归绿 + 双端手工清单 + 状态文档.
> Target Files: WORKMEMORY/PROJECT_OVERVIEW.md、README（如含路线图）、Master plan 状态块.
> Steps: 全量 pytest -v 截证据；核对前端守卫/模块图/register 守卫；文档就地更新（不追加副本）；无代码逻辑改动不单独加测试。
> Return: pytest 全文证据（总数+失败 0）+ 文档 diff 摘要。"

---

## Sub-Plan A 验收（交 B 前）

> 收官勾绿见文末「执行状态（Sub-Plan A 收官）」。master 全门禁（含 Go DAG job#1 import-pack 真链路 + 双端手工）仍留 Sub-Plan B。

- [x] `pytest -v` 全绿（实际 **673 全绿 + 1 skipped**，零回退，净增 encounter 测试）
- [x] 手工/TestClient 冒烟：加文本 → 列表 → 详情 → annotate → 高亮 → 进卡 → wb_state 镜像更新（API 侧 7/7 PASS；前端高亮/进卡/wb 镜像由 A5/A6 探针 + 双端手工清单覆盖，双端手工仍列 Sub-Plan B 门禁）
- [x] `POST /api/encounter/import-pack`（schema `encounter-pack/v1`）可用（B 门禁前置依赖已就绪；真链路对接 Go DAG job#1 留 Sub-Plan B）

---

## 执行状态（Sub-Plan A 收官）

> 追加于 A7（2026-09-07）。Sub-Plan A 六任务（A1–A6）已在分支 `feature/encounter-job1`
> 落地并经各自 CRV（Code Review Verdict）通过后提交；A7 收尾任务将验收门 A 侧勾绿。

**逐任务提交哈希：**

| Task | 提交 | 说明 |
| --- | --- | --- |
| A1 | `d5c1155` | `encounter_texts` 存储层 + CRUD + import 幂等（8 测试，CRV APPROVED） |
| A2 | `fd4378f` | `/api/encounter` 路由 + import-pack 契约（26 测试，CRV APPROVED） |
| A3 | `602ed21` | `/api/encounter/texts/{id}/annotate` 逐词注解（5 测试，CRV APPROVED；Y1 见偏差） |
| A4 | `9956cf4` | 遇见区 SPA 骨架 + encounter.js + 入口卡（7 探针测试，CRV APPROVED；Y2 见偏差） |
| A5 | `71d3d0e` | deck 桥已背词高亮 + 覆盖统计（11 测试，CRV APPROVED） |
| A6 | `3b4242e` | 释义弹层一键进卡（仅入词不建卡）+ 会话小复习（17 测试，CRV APPROVED 含 REWORK 闭环） |

**Reviewer 判定：** A1–A6 均 CRV APPROVED；A7 收尾将 A3/A4 两个 reviewer yellow（Y1/Y2）闭环（见偏差记录）。

**偏差记录：**

- **A3 Y1（此处闭环）**：`tests/test_encounter_annotate.py` 的德语真实词形用例 `geht`→`gehen`（依赖 spaCy 德模真实还原）原无降级保护——德模缺席时处理器静默降级纯 Python，`geht` lemma 退化成 `geht`，用例会误报。A7 已加守卫：镜像 `test_writing_rules.py` 对 `de_core_news_sm` 缺席 `pytest.skip` 的纪律，改为断言 processor 的 `NLP_ENGINE == "spacy"` 且 `nlp` 非空，否则 `pytest.mark.skipif` 干净跳过；未改任何断言。
- **A4 Y2（此处闭环）**：`#view-encounter` 内联 `<style>`（A4–A6 期间累加的视图/按钮/弹层/小复习/已背词高亮 `.enc-*`/`.encounter-*` 规则）内联在前端 HTML 里不利维护。A7 已整体迁入 `static/style.css` 尾部单段 `/* 遇见区 encounter (P0) */` 注释区块并删除 index.html 内联块；**未改任何 id/class/HTML 结构**（`#view-encounter`/`#enc-popover`/`#enc-review`/`#enc-coverage`/`.enc-tok`/`.enc-known` 等探针锚点原样保留）。
- **A6 REWORK RED-1（根因）**：一键进卡初版写 `cards` 带 `reps:0` 会造成「新词 reps=0 却已被预建卡」，与背词工作台队列语义相悖（工作台只把 `reps:0` 视为未背、卡不该提前出现）。根因即**卡（card）与工作台队列语义不一致**。修正后语义：**仅入词不建卡**——新词只追加到 word 存储（`reps` 由工作台真正背出后才置 >0），首次开工作台才进新词池/复习队列。见 A6 提交 `3b4242e`。

**Sub-Plan A 验收门 A 侧：** 全绿勾选见上（import-pack/annotate/冒烟 API 侧 done；master 全门禁含 Go DAG job#1 import-pack 真链路与双端手工清单留 Sub-Plan B）。
