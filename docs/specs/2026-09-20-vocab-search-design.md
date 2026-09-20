# 例句 / 搭配 / 语料 全文检索（内存扫描版）设计

- **日期**：2026-09-20
- **状态**：设计已定，待 `/vault-plan` 生成实施计划
- **类别**：Architectural（新检索子系统）
- **前置决策**：ADR-0014（词表存储边界：FTS5 仅作"超出内存全量读能力"时的派生索引例外）
- **Spike 依据**：见 §6

---

## 1. 问题与用户价值 (Problem Statement & User Value)

**现状**：词库只能按**词头**搜（工作台 `wordFilters.q` 对 `hw`/`lemma`/`def_zh` 做 `includes`），主站无跨域检索入口。

**被埋没的资产**：
| 素材 | 规模 | 当前位置 |
|---|---|---|
| 词条（cefr/pos/gender/plural/释义） | 4762 | `lexicon.LEXICON` |
| 例句 + 音标（德/中） | 2722 | `lexicon.RICH` |
| 介词搭配（介词/格/中文/例句） | 552 词条 / 691 条 | `delector.data.prep_dict.PREP_COLLOCATIONS` |
| 语料全文（文章 / 分级短文） | 随用户增长 | `articles.raw_text` / `encounter_texts.content` |

**目标场景**：学习者遇到一个**搭配、例句片段或中文意思**，想反查"哪个词/哪条搭配/哪篇文章出现过"。

**用户价值**：把已入库但只能逐条翻的例句与搭配变成**可反查的检索资产**。不做不致致命，但 2722 条例句与 691 条搭配的复用价值被浪费。

**规模判据（否决 FTS5 的理由）**：单用户 local-first，固定词库侧 ≈ 8175 条，语料侧 ≤ 数百 KB。**全量内存扫描 < 50ms**，远未达到 ADR-0014 允许 FTS5 的"超出内存全量读能力"门槛（实测见 §6）。

### 非目标 (Non-goals)
- **不做 FTS5**（中文分词硬伤 + Android 内嵌 sqlite 不确定性 + 索引收益≈0；按 ADR-0014 记录为"日后语料涨大再上的派生索引"）。
- 不做语义/向量检索、不做模糊纠错（拼写容错）。
- 不改动词库输出契约（ADR-0011/0013）、不把词表源头写入 SQLite。
- 不新建卡种表；命中词条复用既有「加入 FSRS 盒」入口。

---

## 2. 用户旅程与核心流程 (User Journey & Core Flow)

**主流程（≤3 步，TTV 本地 <50ms）**：
1. 顶栏进入「🔍 检索」视图（`view-search`）。
2. 输入 ≥2 字符（**300ms 防抖**）→ 结果分四组呈现：**词条 / 例句 / 搭配 / 语料**。
3. 逐条操作：
   - **词条**：命中字段高亮；🔊 发音（复用 `playGermanAudio`）；「+ 加入 FSRS 盒」（复用既有入口）。
   - **例句**：显示德/中；🔊 朗读德文例句。
   - **搭配**：`lemma + 介词 + 格 + 中文`；🔊 朗读搭配例句。
   - **语料**：`标题 + 命中片段（上下文 ±N 字）`；点击跳转阅读视图并定位到该文（复用既有 `show('reader')` + 文章 id）。

**范围过滤**：视图内提供 `全部 / 词条 / 例句 / 搭配 / 语料` 分段控件（对应 `scope` 参数）。输入框状态**不持久化**（与工作台 `wordFilters.scope` 同纪律，避免陈旧状态）。

---

## 3. 架构与数据模型 (Architecture & Data Models)

### 3.1 分层
```
代码常量（真值，随发布走）           SQLite（用户数据，可变）
  lexicon.LEXICON  (4762)             articles.raw_text / title
  lexicon.RICH     (2722)             encounter_texts.content / title / level
  prep_dict.PREP_COLLOCATIONS (691)
            \\                              /
             \\                            /
        delector/services/search.py  ← 纯函数：fold / iter_docs / search（运行期内存扫描，不落库）
                      |
        delector/routes/search.py    → GET /api/search?q=&scope=&limit=
                      |
        static/js/search.js + view-search（static/index.html）+ main.js 注册
```

**不落库**：派生结果无状态 → 无需迁移、无需备份、Android 零新依赖、语料新增后**下次查询自动可见**（每请求现算）。

### 3.2 服务端纯函数（`delector/services/search.py`，全量类型注解，mypy `--strict`）
- `fold(s: str) -> str`：小写 + 德语变音折叠（`ä→a`、`ö→o`、`ü→u`、`ß→ss`）+ 压缩空白。**仅用于匹配**，展示用原文。
- `iter_docs() -> Iterator[SearchDoc]`：把四类源规范成统一 doc：
  ```python
  SearchDoc = {
    "kind": "vocab" | "example" | "colloc" | "corpus",
    "id": str,            # 稳定标识（词条=lemma；搭配=lemma+prep；语料=表名:id）
    "lemma": str, "hw": str, "pos": str, "cefr": str,
    "fields": {"hw","def_zh","example_de","example_zh","prep","case","colloc_zh","title","text"},
    "payload": {...},     # 供前端渲染的最小字段集
  }
  ```
- `search(q, *, scope="all", limit=20) -> dict`：`fold(q)` 后逐 doc 逐字段子串匹配 → 计分 → 排序 → 分组截断。

**计分（字段权重，用于排序）**：
| 命中位置 | 分 |
|---|---|
| `hw` 精确 / `lemma` 精确 | 100 |
| `hw`/`lemma` 前缀 | 60 |
| `hw`/`lemma` 子串 | 40 |
| `def_zh` | 25 |
| `example_de` | 15 |
| `example_zh` | 12 |
| 搭配字段（prep/case/colloc_zh） | 20 |
| 语料 `title` / `text` | 18 / 8 |

同分排序：`kind` 固定序（vocab→example→colloc→corpus）+ `id` 升序（**稳定**，便于测试断言）。

### 3.3 API 契约（`GET /api/search`）
- 参数：`q: str`（必填）、`scope: str = "all"`（`all|vocab|example|colloc|corpus`，非法 400）、`limit: int = 20`（钳制 `1..100`）。
- 响应：
  ```json
  { "q": "...", "scope": "all", "total": 12,
    "groups": { "vocab": [], "example": [], "colloc": [], "corpus": [] },
    "truncated": false }
  ```
- `fold(q)` 后长度 `< 2` → `total=0` + 四组空数组（**不报错、不 500**）。
- 只读、无副作用；语料扫描有单请求上限（见 §4）。

### 3.4 前端
- `static/index.html` 新增 `<main id="view-search" class="view">`（顶栏搜索框 + 分段控件 + 四组结果容器 + 空态）。
- `static/js/search.js`：请求 `/api/search`、渲染四组、**所有展示字段经 `esc()`**、防抖、空态、点击跳转/发音/进卡。
- `main.js`：import 模块 + 注册视图路由（照 `hard-sentences.js` / `listen-lab.js` 既有模式）+ 顶栏导航项。

### 3.5 注册面
- `delector/routes/search.py` 的 router 在 `delector/routes/__init__.py::register_routes` 中于 **`main` 之前** include（保持"分域路由在前、通用 handler 垫底"纪律）。

---

## 4. 边界与韧性 (Edge Cases & Resilience)

| 场景 | 行为 |
|---|---|
| 空 / 单字符 q | 返回空结果（`total=0`），不报错 |
| 无结果 | 前端空态文案（不白屏） |
| **中文两字词**（例句/公寓/搭配） | 子串匹配直接命中（**这正是放弃 FTS5 的原因**：FTS5 trigram 要求 ≥3 字符） |
| **德语变音** | `fold` 后 `schon↔schön`、`wohnung↔Wohnung`、`strasse↔straße` 均可命中 |
| 语料过大 | 单请求语料扫描 hard cap（如最多 N 篇 / 总字符上限），超出置 `truncated=true` 并在前端提示"结果已截断" |
| 并发 | 只读短连接 `db_conn()`；语料扫描请求内完成，**不加缓存**（YAGNI，实测慢再加进程内 TTL 缓存） |
| XSS / 注入 | 前端一律 `esc()`；后端 SQLite 参数化查询，绝不拼 SQL |
| `file://` 直开 / 服务未起 | 检索视图显示"需本地服务"提示（与既有 http 守卫同纪律），不白屏 |
| 去重 | 同一 `lemma` 的"词条命中 + 例句命中"合并为一条（词条优先），避免同词刷屏 |
| 前后端版本错位（Android 覆盖安装不一致） | 端点缺失时前端 `try/catch` 降级为"检索不可用"，不影响其它功能 |

---

## 5. 测试策略 (Test Strategy)

- **单元（纯函数）** `tests/test_search_service.py`：
  - `fold`：变音/大小写/`ß`/空白；
  - 计分排序：构造已知输入断言**确定顺序**（含同分稳定序）；
  - `scope` 过滤、`limit` 钳制（0/负/超大）、去重合并；
  - 中文两字词命中、德语变音命中、无结果。
- **API** `tests/test_search_api.py`：TestClient 打 `/api/search`（真词库 + **临时语料库**，env 钉 `tmp_path`，**不碰仓库根 `delector.db`**）；断言分组键集、`q` 过短空结果、非法 `scope` 400、`limit` 上限。
- **性能守卫**：断言全量（8175 词库 + 注入 ~200KB 语料）单次 `search()` **< 50ms**（宽松阈值防环境抖动）——把"内存扫描够快"从假设变成回归断言。
- **前端行为探针** `tools/wb_search_probe.mjs`（真实函数体切片 + `node:vm` 真跑，禁重抄实现，含 `--json`）：高亮**转义安全**（`<script>` 不注出）、四组渲染、空态；接入 pytest。
- **注册守卫**：`routes/__init__.py` 中 `search` 在 `main` 之前注册（照既有模块图测试风格）。
- **回归**：分半 pytest + 全 `tools/*.mjs` 探针零漂移 + `ruff` / `mypy --strict`。
- **变异验证（写测试时必做）**：把计分权重写反 / 把 `fold` 的变音折叠删掉 / 把 `q<2` 守卫删掉 → 对应断言必须变红（防死断言）。

---

## 6. Spike 结论（FTS5 可行性，2026-09-20）

| 检项 | 结果 |
|---|---|
| 本机 FTS5 | 可用（SQLite 3.43.1） |
| `unicode61` + 中文 | **不可用**：`MATCH '例句'` / `'检索'` 恒 0（CJK 不切词） |
| `trigram` + 中文 | **不可靠**：要求查询 ≥3 字符 → **两字词全废**（`打交道` 命中 / `公寓` 不命中） |
| `unicode61 remove_diacritics 2` + 德文 | 良好（`schon↔schön`、`wohnung↔Wohnung` 均命中） |
| Android 内嵌 sqlite（Chaquopy Python 3.10） | **无法离线确定** FTS5 是否编译内置 |
| 规模 | 词库 ≈ 8175 固定 + 语料（单用户）≤ 数百 KB → 内存扫描 < 50ms |

**结论**：FTS5 对中文需"预分词"额外复杂度，且背 Android 不确定性；而规模根本用不上索引。→ **采用内存扫描（本设计）**，FTS5 作为 ADR-0014 的"日后例外"记录在案。
