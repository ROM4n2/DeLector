# 路线 C — Grammatik-Radar: 精读语法雷达 实施计划

> **Goal**: 在精读视图中将已有的句法五场域抽屉升级为"光标悬停自动触发"体验，新增语料语法统计写入 `progress.db`，并在抽屉内加入蜘蛛图雷达展示历史语法复杂度分布。
> **Tech Stack**: Python 3.10+ (FastAPI + SQLite), 原生 ES Modules JS (无框架)
> **Spec Reference**: `/vault-spark` 对话（2026-09-04），用户选定 Option B
> **Global Constraints**: Conventional Commits, no `--no-verify`, 569 pytest 不退, 10/10 Node 探针不退, `wb_queue_probe.mjs` 13/13 切片护栏不受影响（本次改动仅涉及 `reader.js` / `index.html` / `database.py` / `server.py`）

---

## ⚠️ User Review Required

> [!IMPORTANT]
> **已有代码比预期多得多**：`renderFelderSpectrum`、`renderDetailedFelderGrid`、`openSyntaxDrawerForSentence`、`renderClauseTreeNode`、`highlightClauseTokens` **已全部实现**，`#syntax-felder-grid`、`#syntax-tree-container`、`#drawer-syntax-section` DOM 也已就绪。
> 因此本次任务实际上是：
> 1. **接通 hover 自动触发**（把手动点「🌳 句法」按钮改为光标停留 600ms debounce 自动打开抽屉并渲染）
> 2. **新增语料语法统计**（progress.db 新表 + 后端写入路由 + 前端雷达图 SVG）
> 预计 3 天交付，而不是原来估计的 4–5 天。

> [!WARNING]
> 语法统计表写入是异步后台任务——前端不等后端统计完成才显示抽屉；服务端写入失败不应影响前端 UX。

---

## Open Questions

无。用户已确认全部设计决策。

---

## Proposed Changes

### 🗂 Component 1 — Hover 自动触发（reader.js + index.html 轻量改动）

#### [MODIFY] [reader.js](file:///d:/Code/DeLector/static/js/reader.js)

**改动范围：Lines 258–276**（Setup separable verb hover 区域后紧接新增句子 hover 监听器）

- 新增全局变量 `let _syntaxHoverTimer = null`
- 在 `renderArticle` 完成 DOM 构建后遍历 `.reader-sent-unit`：
  - `mouseenter` → clearTimeout → `_syntaxHoverTimer = setTimeout(() => openSyntaxDrawerForSentence(sentId), 600)`
  - `mouseleave` → clearTimeout（不取消已打开的抽屉）
- 删除每句后 `<button class="sent-syntax-btn">` 的手动触发按钮（UI 整洁化）
- `openSyntaxDrawerForSentence` 本身无需改动（已实现）

#### [MODIFY] [index.html](file:///d:/Code/DeLector/static/index.html)

- 删除 `#d-tab-syntax` 标签切换按钮（hover 自动打开，抽屉不再需要手动选 tab）
  - 保留 `#drawer-syntax-section` div 本身不变
- 在 `#drawer-syntax-section` 底部新增「**语料语法雷达**」折叠区（`<details>` 元素，默认收起）：
  ```html
  <details id="grammar-radar-panel" style="margin-top:1.25rem">
    <summary>📡 语料语法复杂度雷达</summary>
    <svg id="grammar-radar-svg" width="220" height="220" ...></svg>
    <div id="grammar-radar-stats" class="radar-legend"></div>
  </details>
  ```

---

### 🗂 Component 2 — 语料语法统计 DB（database.py）

#### [MODIFY] [database.py](file:///d:/Code/DeLector/database.py)

**新增到 `init_progress_db()` 的 DDL**（追加在现有 `executescript` 内）：

```sql
CREATE TABLE IF NOT EXISTS corpus_syntax_stats (
    article_id    INTEGER PRIMARY KEY,
    sent_count    INTEGER NOT NULL DEFAULT 0,
    avg_clause_depth   REAL NOT NULL DEFAULT 0.0,
    passive_rate       REAL NOT NULL DEFAULT 0.0,
    konjunktiv_rate    REAL NOT NULL DEFAULT 0.0,
    vl_rate            REAL NOT NULL DEFAULT 0.0,
    analyzed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**新增函数** `upsert_corpus_syntax_stats(article_id, stats_dict)` → `INSERT OR REPLACE`。

**新增函数** `get_all_corpus_syntax_stats()` → 返回所有行的均值，供雷达图前端读取。

---

### 🗂 Component 3 — 后端语法统计路由（server.py）

#### [MODIFY] [server.py](file:///d:/Code/DeLector/server.py)

**新增两个端点**（紧接现有 `POST /api/syntax/analyze`，约 Line 1963）：

```python
class SyntaxStatsReq(BaseModel):
    article_id: int
    stats: dict  # {sent_count, avg_clause_depth, passive_rate, konjunktiv_rate, vl_rate}

@app.post("/api/syntax/stats")
async def api_syntax_stats_save(req: SyntaxStatsReq, background_tasks: BackgroundTasks):
    background_tasks.add_task(upsert_corpus_syntax_stats, req.article_id, req.stats)
    return {"ok": True}

@app.get("/api/syntax/stats")
def api_syntax_stats_get():
    return get_all_corpus_syntax_stats()
```

---

### 🗂 Component 4 — 前端语法统计聚合与雷达图（reader.js）

#### [MODIFY] [reader.js](file:///d:/Code/DeLector/static/js/reader.js)

**新增函数** `computeArticleSyntaxStats(sentences)` (~30 行)：
- 遍历所有 `sent.clause_tree`，统计 `avg_clause_depth`, `passive_rate`, `konjunktiv_rate`, `vl_rate`
- 返回 `stats` 对象

**新增函数** `saveAndRenderSyntaxRadar(articleId, stats)` (~50 行)：
1. 调用 `POST /api/syntax/stats` 异步保存（fire-and-forget，不 await）
2. 调用 `GET /api/syntax/stats` 获取全部语料均值
3. 调用 `renderRadarSvg(current, historical)` 填充 `#grammar-radar-svg`

**新增函数** `renderRadarSvg(current, historical)` (~80 行)：
- 四维蜘蛛图（纯 SVG，无外部依赖）
- current 值用实线多边形 + `var(--accent)` 填充（半透明）
- historical 均值用虚线轮廓 + `var(--rule)` 描边
- 轴标签：`嵌套深度 / 被动率 / Konj.II率 / VL句式`

**改动 `openSyntaxDrawerForSentence`** (~10 行)：在渲染 felder + tree 后，调用 `saveAndRenderSyntaxRadar`（不阻塞显示速度）。

---

### 🗂 Component 5 — CSS Editorial 样式（style.css）

#### [MODIFY] [static/style.css](file:///d:/Code/DeLector/static/style.css)

新增约 60 行：
- `.radar-legend` 图例布局
- `#grammar-radar-panel summary` 折叠箭头样式
- Konjunktiv II 场域颜色（`--kj2: #efe2fa`）
- 被动语态场域颜色（`--passiv: #fde0d7`）
- `.field-passive`, `.field-konjunktiv` class 样式（`renderDetailedFelderGrid` 已生成这些节点）

---

### 🗂 Component 6 — 测试

#### [MODIFY] [test_server.py](file:///d:/Code/DeLector/test_server.py)

新增 2 个测试：
- `test_syntax_stats_save_and_get()` — 验证 `POST /api/syntax/stats` 写入，`GET /api/syntax/stats` 读取均值格式正确
- `test_corpus_syntax_stats_schema()` — 验证 DB schema 已正确创建（4 个浮点字段存在）

#### [NEW] `test_grammatik_radar.py`

- `test_reader_sent_hover_btn_removed()` — 验证 `index.html` 中不再存在 `sent-syntax-btn` 类（hover 化后清理旧按钮）
- `test_radar_panel_present_in_syntax_drawer()` — 验证 `#grammar-radar-panel` 存在于 `#drawer-syntax-section` 内
- `test_syntax_stats_endpoint_returns_radar_fields()` — E2E：初始化后 `GET /api/syntax/stats` 返回 4 个必要字段

---

## Verification Plan

### Automated Tests
```bash
pytest test_grammatik_radar.py test_server.py -q -x    # 新测试必须全绿
pytest -q --tb=short                                    # 全量 569 → 574+ 不退
node tools/wb_queue_probe.mjs                           # 13/13 护栏不变
node tools/wb_merge_probe.mjs
node tools/wb_sync_probe.mjs
```

### Manual Verification
- 在精读视图打开一篇文章，光标移到句子 → 600ms 后右侧抽屉自动切换到「句法」标签并展示五场域 + AST 树
- 点开「📡 语料语法复杂度雷达」折叠区，看到四维蜘蛛图（需先有多篇文章数据）

---

## Task Summary (6 Tasks, est. ~3 days)

| Task | 描述 | TDD | 预计时间 |
|------|------|-----|--------|
| **T1** | DB schema + `upsert_corpus_syntax_stats` + `get_all_corpus_syntax_stats` | pytest RED→GREEN | 30 min |
| **T2** | `POST /api/syntax/stats` + `GET /api/syntax/stats` 路由 | pytest RED→GREEN | 30 min |
| **T3** | `index.html` — 清理旧按钮 + 新增 `#grammar-radar-panel` | pytest RED→GREEN | 20 min |
| **T4** | `reader.js` — hover debounce 自动触发 + `computeArticleSyntaxStats` | pytest RED→GREEN | 60 min |
| **T5** | `reader.js` — `renderRadarSvg` + `saveAndRenderSyntaxRadar` + `style.css` radar 样式 | pytest RED→GREEN | 90 min |
| **T6** | 全量回归：`pytest -q` + 10/10 探针 + 人工验证 hover 体验 | 569→574+ 全绿 | 30 min |
