# 遇见区 i+1 补齐：内容放量 + 就近选材 设计

- **日期**：2026-09-23
- **状态**：设计已定，待 `/vault-plan` 生成实施计划
- **类别**：Architectural（既有子系统能力补齐，两阶段）
- **前置决策**：ADR-0010（遇见区分层与 Go Agent 内容生产）、ADR-0014（词表存储边界与 A1 取数统一）
- **前置规范**：Coding Vault `01-Rules/STORED-DATA-BACKFILL`（读取期派生 / 只增 + 只补空 + 幂等 / 禁跨语义来源混用）；项目侧 `WORKMEMORY/PROJECT_OVERVIEW.md` 红线 12
- **来源**：`/vault-spark` 2026-09-23 方向裁定（先 A 后 B）

---

## 1. 问题与用户价值 (Problem Statement & User Value)

**北星回顾**：DeLector 的产品北星是「遇见区」**i+1 阅读桥**——让用户从"背 A1/A2 词"过渡到"读分级短文"，已背词高亮、生词一键进卡。真实用户（作者女友）主用安卓端背词工作台，下一步就是这条桥。

**现状取证**（读代码，非推测）：

| 事实 | 证据 |
|---|---|
| 遇见区**可读素材只有 4 篇**（A1×2 / A2×2） | `delector/data/encounter_seed_dict.py`；`tools/build_encounter_seed.py` 默认 `--levels A1,A2` |
| 仓库语料库实有 **12 篇 / A1–B2**，其中 A1–B1 共 **7 篇** | `delector/data/corpus_dict.py::OFFICIAL_CORPUS`（A1×2 / A2×2 / B1×3 / B2×4） |
| 列表**只支持 `?level=` 过滤**，无覆盖率、无难度排序、无推荐 | `delector/routes/encounter.py:114 _to_list_payload`；`static/js/encounter.js:180 renderTextList` |
| 覆盖率**只在打开某篇之后**才出现 | `encounter.js:290 renderCoverage`（"已背词覆盖 X/Y（Z%）"） |
| known 判定**永远本机**（deck = localStorage `wb.words.v1`+`wb.cards.v1` 且 `reps>0`） | `static/js/deck-bridge.js::buildKnownSet`；ADR 红线 |

**两个独立缺口**：
1. **量不够** —— 4 篇读完就没有下一篇，桥的另一端是空的。
2. **没有匹配** —— 打开列表不知道读哪篇，只能逐篇点开试错；"i+1"（内容难度**恰好比当前水平高一档**）在系统里**完全不存在**。

**目标场景**：用户在手机上打开遇见区（或从工作台背完词切换过来），**在不点开任何一篇的前提下**，立刻看到"哪几篇正好适合我现在读"。

**用户价值**：把 4 篇一次性内容变成"**按我的进度动态变化的阅读队列**"。只做量（A）是仓库补货；只做匹配（B）是 4 篇里的排序。**A 是 B 的前提**（可选目标太少时排序无意义），**B 是 A 的意义**（7 篇裸列表仍然不知道读哪篇）。

**成本不对称（决定了顺序）**：
- A 的素材侧近乎零成本——语料已在仓库，脚本改一个参数重跑即可（零 LLM、零网络、确定性可复现）。真正的工程点是**存量设备如何吃到新预置**（§3.1.2）。
- B 的服务端侧也近乎零成本——覆盖率所需数据可在**发布期**预计算进卡包（§3.1.1），运行期零 spaCy。

### 非目标 (Non-goals)

- **不扩 B2/TestDaF 语料**：`_ALLOWED_LEVELS = ("A1","A2","B1")` 保持不变。B2 对当前真实用户（A1/A2）无价值，扩白名单会牵动表契约/前端等级筛选/测试断言面；语料仍在仓库，作为后续候选（真题语料库预置，v4.8+ roadmap ⚪）。
- **不改 `annotate` 端点与其"P0 直跑、禁缓存"策略**：索引走独立端点，互不干扰。
- **不在服务端计算覆盖率**：known 判定必须本机（ADR 红线），服务端只提供"每篇的词序列"，判定在前端完成。
- **不动 Go job#1 产包链路**：`encounter-pack/v1` 新增字段为**可选**；Go 产的包不带 `lemma_seq` → 索引返回 `null` → 该篇不参与排序但不丢失（§4）。
- **不新建卡种表 / 不改 FSRS 语义 / 不改 workbench**。
- **不做收藏、排序偏好持久化、阅读进度表**（无状态派生，每次进入现算）。

---

## 2. 用户旅程与核心流程 (User Journey & Core Flow)

### Phase A：升级即得 7 篇（零操作）

1. 用户升级到新版本 → 启动。
2. `create_app()` 装配期发现"预置版本记录 < 当前版本" → **只增**补装缺失的 3 篇 B1 包（已有 4 篇原样保留，不重复、不覆盖）。
3. 打开遇见区 → 列表出现 A1×2 / A2×2 / B1×3。

超过 3 步的部分由系统承担（用户侧零操作）——这是本阶段的核心体验承诺。

### Phase B：列表直接告诉你读哪篇（≤3 步）

1. 用户进入遇见区（`view-encounter`）。
2. 列表项按**覆盖区间**分组排序，每条带徽章（`✅ 正好读 91%` / `偏简单 99%` / `偏难 78%`），列表顶部一条**推荐条**："👉 建议先读《Ein Tag auf dem Wochenmarkt》（已背词覆盖 91%）"。
3. 用户点开推荐那条 → 进入既有的已背词高亮阅读视图（现状能力，不变）。

**空态旅程（新用户 / 未背任何词）**：`knownSet` 为空 → 所有条目均为"偏难" → 列表顶部改为**引导文案**："先在背词工作台背一些词，这里就会告诉你哪篇正好适合你。"（不显示推荐条，避免把 0% 覆盖的短文推给用户）。

### 与既有能力的关系

- 阅读视图、逐词释义、一键进卡、会话小复习**全部不变**（`encounter.js` 既有 A4–A6 逻辑不动）。
- 「📥 从电脑导入」（WiFi 拉取）不变，且同样受益：从桌面拉来的包若带 `lemma_seq`，在手机端同样参与排序。

---

## 3. 架构与数据模型 (Architecture & Data Models)

### 3.1 Phase A：内容放量 + 版本化增量补装

#### 3.1.1 发布期：脚本产包扩容 + 预计算词序列

**`tools/build_encounter_seed.py`** 两处改动：

1. **默认分级** `_DEFAULT_LEVELS`：`"A1,A2"` → `"A1,A2,B1"`（CLI `--levels` 覆盖能力保留）。
   - `_ALLOWED_LEVELS` 已含 `B1`，路由 `_normalize_level` 无需改动。
2. **新增预计算字段** `analysis.lemma_seq`：该篇正文按 `annotate` 同口径的**逐 token lemma 有序列表（含重复）**。

```python
# build_packs() 内，构造 analysis 时新增：
lemma_seq = [tok["lemma"] for s in parsed["sentences"] for tok in s["tokens"] if not tok.get("is_space")]
# -> pack["analysis"]["lemma_seq"] = lemma_seq
```

**口径实测结论（2026-09-23，本机 spaCy 3.8.16 + de_core_news_sm）**：对 `goethe_a1_alltag_01`，`process_german_text` 产出的 `space_tokens = 0`，因此
`sum(len(s["tokens"]))` = `去除 is_space 后的 token 数` = `vocab_stats.tokens_total` = `annotate.total_tokens` = **59，四者同值**。
⇒ **`analysis.tokens_total` 可直接复用，无需重算**；`lemma_seq` 长度与该值一致（59 项 / 约 520 字节 JSON）。

**为何预计算而不是运行期算**：`annotate` 是逐篇跑 spaCy 的 P0 直跑端点（无缓存）；列表要为 N 篇算覆盖率就需要 N 次 spaCy 调用（移动端首屏数秒级）。预计算把成本移到发布期，运行期只读 `pack_json`。

**确定性**：`lemma_seq` 由同一脚本、同一输入确定性产出 → 保持"同输入两次产物字节一致"（既有测试 `test_build_script_deterministic` 继续成立）。

#### 3.1.2 装配期：版本化增量补装（seed 语义升级）

**问题**：`seed_preset_encounter_texts` 现有语义是**空库守卫**——`count != 0` 直接返回 0，且 docstring 明写"预置内容只是首次启动的默认供给，不是每次启动都要补齐的资材"。真实用户与作者的设备都是**非空库**，因此**永远不会**拿到新增的 B1 三篇。

**决策**：把空库守卫升级为**版本闸 + 只增补装**，语义严格遵循 `01-Rules/STORED-DATA-BACKFILL`：

```python
PRESET_SEED_VERSION = 2   # delector/core/database.py 模块级常量（不放进生成物数据模块）
```

| 条件 | 行为 |
|---|---|
| `app_settings["encounter_seed_version"] >= 2` | 立即返回 0（**热路径**：每次启动只读 1 行） |
| 记录缺失 且 `encounter_texts` 为空 | 全量导入全部 7 包（**保留既有空态语义**） |
| 记录缺失 且 库非空 | **只增**：逐包 `import_encounter_pack` 幂等落库；缺失的 pack_id 新建，已存在的**不动行** |
| 无论哪条路径 | 成功走完后写入 `app_settings["encounter_seed_version"] = 2` |

**同时执行"只补空字段"**（红线 12 的下半条）：对**已存在**的 pack_id，若库内 `pack_json` 的 `analysis` 缺 `lemma_seq`、而新包里**有**，则**仅补写该字段**（读旧 JSON → 合并该键 → UPDATE 该行的 `pack_json`），**绝不触碰** `title / level / content / source / created_at` 与任何用户数据。

> 这一步是 B 能否对**存量 4 篇**生效的关键：老包是 v1 格式（无 `lemma_seq`），不补空则用户在 Phase B 看不到任何排序。

**为何不引入删除墓碑**：版本闸天然只补"这一次"，用户主动删除的预置短文**不会在后续每次启动复活**（记录已是 2）。代价：升级那一次会把用户删过的预置包补回来一次——可接受，且行为可解释（"随版本发布的内容资产"与"用户数据"分离）。

**读写 `app_settings`**：复用既有表（`key TEXT PRIMARY KEY, value TEXT`）。实现时优先复用 `database.py` 内已有的 app_settings 读写 helper（`get_wb_sync_key` 即走此表）；若无通用 helper 则新增 `_get_app_setting(key)` / `_set_app_setting(key, value)` 两个参数化薄函数。

#### 3.1.3 数据面

- `PRESET_ENCOUNTER_PACKS`：4 → **7**（A1×2 / A2×2 / B1×3），`pack_id` 升序不变。
- `encounter_texts` 表结构**零改动**。
- 打包注册面**零改动**（`encounter_seed_dict` 已在 `package_windows.py` / `build-release.yml` / `tests/test_server.py::data_dict_modules` 三处清单内，本次只改其内容）。

### 3.2 Phase B：轻量索引端点 + 前端就近选材

#### 3.2.1 服务端：`GET /api/encounter/texts/index`

- **位置**：`delector/routes/encounter.py`（同域路由，注册顺序不变）。
- **鉴权**：与 `GET /texts` 同级——**只读、不挂本机闸**（局域网/手机端要能用）。
- **响应**：

```json
{
  "items": [
    {"id": 3, "title": "...", "level": "A2", "word_count": 96,
     "total_tokens": 59, "lemma_seq": ["jeder", "Samstag", ...]}
  ]
}
```

- **数据源**：遍历 `list_encounter_texts()` → 从 `pack_json` 解析 `analysis.tokens_total` / `analysis.lemma_seq`。
- **缺字段回退**：无 `pack_json`（手工短文）或 `analysis.lemma_seq` 缺失（Go job#1 包 / 未补空的旧行）→ `total_tokens: null, lemma_seq: null`（**不跳过该行**，前端据此降级展示）。
- **不返回** `content` / `pack_json` / `source`（最小暴露面）。
- **零 spaCy、零 DB 写入**：纯读取 + JSON 解析。

#### 3.2.2 前端：纯逻辑模块 `static/js/enc-i1.js`

与 `deck-bridge.js` 同纪律（**零 import、模块顶层不碰浏览器全局、不抛异常**），供 `node:vm` 探针直接切片运行：

```js
// 半开区间（单点定义，渲染层不得散落字面量）：i1 = [0.85, 0.97) / easy = [0.97, +∞) / hard = (-∞, 0.85)
export const I1_BANDS = { i1: [0.85, 0.97], easy: [0.97, Infinity], hard: [-Infinity, 0.85] };
export function bandOf(rate);                  // -> "i1" | "easy" | "hard"
export function coverageOf(knownSet, entry);   // -> {available, knownTokens, totalTokens, rate, band}
export function rankEntries(knownSet, entries); // -> 排序后的新数组（不改原数组）
export function topPick(ranked);               // -> 首条 i1（无则 null）
```

**覆盖率算法**（必须与阅读视图逐位一致）：

```js
knownTokens = entry.lemma_seq.filter((lemma) => knownSet.has(String(lemma).toLowerCase())).length;
rate = knownTokens / entry.total_tokens;
```

- `knownSet` 复用 `deck-bridge.js::buildKnownSet(loadDeck(localStorage))`（剥冠词 + 小写，不是裸小写）。
- `totalTokens` 用服务端给的 `total_tokens`（含标点、不含空白）——**不是** `lemma_seq.length`（两者在实测中同值，但语义上前者是分母的权威来源，不得混用）。

#### 3.2.3 阈值与排序

| 区间 | `band` | 徽章文案 | 排序优先级 |
|---|---|---|---|
| `0.85 ≤ rate < 0.97` | `i1` | `✅ 正好读` | 1（最前） |
| `rate ≥ 0.97` | `easy` | `偏简单` | 2 |
| `rate < 0.85` | `hard` | `偏难` | 3 |

- 组内按 `rate` **降序**（同分按 `id` 升序，保证确定性）。
- `available === false`（无 `lemma_seq`）的条目排在**最后**，无徽章，仅显示既有元信息（`N 词 · 日期 · 来源`）。
- 阈值以常量 `I1_BANDS` 单点定义，探针与 UI 共用，禁止在渲染层散落字面量。

#### 3.2.4 UI 落点

- **列表卡片**（`encounter.js::renderTextList`）：在既有 `.encounter-card` 内追加
  `<span class="enc-i1-badge enc-i1-${band}">${label} ${pct}%</span>`，所有文本字段仍一律 `esc()`。
- **推荐条**：列表容器 `#encounter-text-list` 之前新增 `<div id="enc-i1-hint" class="enc-i1-hint">`（`static/index.html` 的 `view-encounter` 内），由 `renderI1Hint(ranked)` 填充；无 `i1` 命中或无 `knownSet` 时不渲染。
- **数据获取**：`showView()` 在 `fetchTexts()` 之后追加 `fetchIndex()`；两次请求并发（`Promise.allSettled`），**索引失败不得影响列表**（降级为原文顺序 + 无徽章）。
- **样式**：`static/css/style.css` 内新增 `.enc-i1-badge` / `.enc-i1-hint`；移动端沿用既有触屏目标与 padding 口径（`@media` 断点内补规则，不退化为贴边）。

### 3.3 硬不变量

> **I-1（口径一致性）**：对任一篇短文，前端用 `lemma_seq` 算出的 `rate` 必须与打开该篇后 `renderCoverage` 显示的 `known_rate` **逐位一致**（同一 `deck`、同一 `annotate` 响应）。

这条不变量是 B 的**唯一真值锚**：它同时钉住服务端口径（`tokens_total` / `lemma_seq` 必须来自 annotate 同源）、前端算法（`buildKnownSet` 复用）与预计算正确性。落地为 T-B4。

---

## 4. 边界与韧性 (Edge Cases & Resilience)

| 场景 | 行为 |
|---|---|
| 条目无 `lemma_seq`（手工短文 / Go job#1 包 / 未补空旧行） | `available=false` → 无徽章、排最后、仍可点开阅读 |
| `knownSet` 为空（新用户） | 全部 `hard` → 列表显示引导文案，**不显示推荐条**（不推 0% 短文） |
| `total_tokens` 缺失或为 0 | `available=false`（**不做除零**；`rate` 不参与排序） |
| 索引请求失败 / 超时 / `file://` 离线 | `Promise.allSettled` 兜底 → 原文顺序（按 `id DESC`）+ 无徽章；阅读功能完全不受影响 |
| 版本闸已置 2 后用户删除某预置包 | **不复活**（不再补装） |
| 用户已手工添加同名/同类短文 | 补装只按 `pack_id` 判重，**绝不覆盖或删除**用户行 |
| `pack_json` 损坏（非法 JSON） | 逐行 try/except → 该行 `lemma_seq: null`（**不 500**） |
| 单包补装失败（数据损坏/约束冲突） | 沿用既有逐包异常隔离：记 `logging.error`，其余包继续，**不崩启动** |
| 局域网/手机端访问索引端点 | 允许（只读、无写路径）；`_require_localhost` 不适用于此 |
| Android 独立实例 | 改动含 `static/` → **必须覆盖安装新 APK 才生效**（存量不自动更新） |

---

## 5. 测试策略 (Test Strategy)

### 5.1 数据契约（Phase A）

- 预置包数 **7**、`estimated_cefr ⊆ {A1,A2,B1}`、`pack_id` 全局唯一、每包过 `validate_pack`、正文德语特征、`glosses == []`（既有 `tests/test_encounter_seed.py` 更新而非删除）。
- **新增**：每包 `analysis.lemma_seq` 为非空 `list[str]`，且 `len(lemma_seq) == analysis.tokens_total`（两条口径同源的结构证据）。
- 脚本确定性：既有 `test_build_script_deterministic` 继续通过（新增字段不得引入非确定性）。

### 5.2 补装行为（Phase A，核心）

- 空库 + 无版本记录 → 导入 7 行、写入版本 2。
- **非空库**（含 1 篇手工短文）+ 无版本记录 → 补装 7 行（总 8 行）、用户那篇**逐字段不变**、写入版本 2。
- 幂等：版本已 2 → 返回 0、行数与内容零变化。
- **不复活**：删除其中一个预置包后再次调用 → 返回 0、行数不回升。
- **只补空**：预置旧行（`pack_json` 无 `lemma_seq`）→ 补装后该行 `pack_json.analysis.lemma_seq` 非空，且 `title/level/content/source/created_at` **逐字段不变**。
- **不覆盖非空**：人为把某行的 `lemma_seq` 改成哨兵值 → 补装后**仍是哨兵值**（能力闸门：只补空）。
- 既有 `test_create_app_calls_seed_encounter_texts` / `test_create_app_seed_order_after_articles` 保持通过。

### 5.3 索引端点（Phase B）

- TestClient 打 `GET /api/encounter/texts/index`：条数、字段集、`lemma_seq` 与库内 `pack_json` 一致。
- 手工短文行 → `total_tokens: null, lemma_seq: null` 且**仍在列表内**。
- `pack_json` 损坏行 → 该行 `null`，响应 200（不 500）。
- 响应**不含** `content` / `pack_json`（用字段集合断言，不是"不出现某字符串"）。
- 局域网语义：不挂本机闸（既有闸测试风格对齐）。

### 5.4 前端行为探针（Phase B）

- `tools/wb_enc_i1_probe.mjs`：`node:vm` 切**真实源码** `static/js/enc-i1.js`（与 `deck-bridge.js` 同法），注入桩 `knownSet`：
  - 区间边界：`rate` = 0.84 / 0.85 / 0.96 / 0.97 → `hard / i1 / i1 / easy`（**边界值逐条钉死**）。
  - 排序：`i1` 组在 `easy` 之前、`hard` 之后；组内 `rate` 降序；`available=false` 排最后。
  - `topPick`：有 `i1` 返回首条；只有 `easy`/`hard` 返回 `null`。
  - 不改原数组（入参 `entries` 引用与内容不变）。
- 接入 pytest：`tests/test_enc_i1_probe.py`（发现 `--json` 失败即红，沿用 `test_rich_backfill_probe_reports_no_failures` 模式）。
- UI 契约：`tests/test_encounter_ui_probes.py` 追加断言——`#enc-i1-hint` 容器存在于 `view-encounter`；徽章渲染走 `esc()`；索引失败降级路径存在。

### 5.5 口径一致性（Phase B，硬不变量 I-1）

- `tests/test_encounter_i1_consistency.py`：端到端（TestClient 全链路）——
  1. 取一预置包的 `analyze/annotate` 响应，用纯 Python 复算 `known_rate`（与 `deck-bridge` 同规则）；
  2. 取索引端点该篇的 `total_tokens` / `lemma_seq`，用同一 known 集合复算 `rate`；
  3. 断言两者**逐位相等**（`==`，不用近似）。
- **变异验证（三条，缺一不可）**：① 把 `lemma_seq` 的 `is_space` 过滤规则去掉（测试内构造含连续空白的正文）→ 长度不变量断言必红；② 把前端覆盖率分母从 `entry.totalTokens` 换成 `entry.lemma_seq.length`（探针内构造 `totalTokens ≠ lemma_seq.length` 的样本）→ 必红；③ `bandOf` 阈值 `0.85 → 0.8` → 边界用例必红。三条均在行为探针 / 单元测试内完成，**不接受"不红"结案**。

### 5.6 收尾门禁

- 全量 `pytest`（分半跑：`--ignore=tests/test_server.py` + 单跑 `tests/test_server.py`）。
- `ruff check .` 零告警；`python -m mypy --strict delector tools` 零 error。
- `for f in tools/*.mjs; do node "$f" ...` 全探针零漂移。
- Android 覆盖安装点检（人工，发版后）。

---

## 6. 关联索引

- `docs/plans/2026-09-23-encounter-i1-content-and-selection.md`（实施计划）
- `docs/plans/2026-09-10-encounter-content-supply.md`（预置内容供给侧首建：本设计的直接前身）
- `docs/specs/2026-09-05-a2-vocab-expansion-design.md`（等级扩展的先例形态）
- `08-Projects/DeLector/01-ADR/0010-encounter-zone-layered-go-agent-producer.md`
- `08-Projects/DeLector/01-ADR/0014-vocabulary-storage-boundary-and-a1-server-fetch.md`
- `01-Rules/STORED-DATA-BACKFILL.md`（存量数据回填规范：本设计 A 阶段语义的规范出处）
- `01-Rules/TESTING-PATTERNS.md`（行为探针 / 变异验证纪律）
