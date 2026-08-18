# DeLector Phase 3: 文本 CEFR 难度评估与等级雷达 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DeLector 引入全自动文本 CEFR 难度分析、加权分级评估、学习者精读时间估算，并在文稿库与阅读器中提供多色难度分布条与一键考点等级聚焦（Focus Filter）联动交互。

**Architecture:**
- 后端：在 `server.py` 的 `process_german_text` 中增加全量词汇统计与 CEFR 难度加权定级算法，计算各级别（A1-C1）词汇频次与百分比、精读用时（90 wpm）及综合建议等级（A1-B2+）；在 `/api/articles` 与 `/api/articles/{id}` 接口中返回完整 `stats` 载荷。
- 前端：
  - 首页文稿行集成迷你多色 CEFR 进度条（Mini Segment Bar）与推荐级别徽章。
  - 阅读器顶部集成横向 CEFR 分布热力条（带各等级百分比）、预计精读时间与词数。
  - 核心交互：点击顶部热力条分段，正文中该等级全部生词触发高亮聚焦脉冲（Pulse Focus），其他词汇柔和淡化，支持备考专项攻坚。

**Tech Stack:** Python 3.11, FastAPI, spaCy (`de_core_news_sm`), SQLite, Vanilla JS/CSS (CSS Keyframe Animations & Flexbox).

## Global Constraints

- 不引入额外前端或图表库，保持单进程极简与极致加载速度。
- 难度分级算法使用加权非 A1 词汇密度模型（<15% A1, 15-30% A2, 30-50% B1, >50% B2+）。
- 严格遵循 `docs/design-system.md` 的色彩定义与便签质感（A1 天蓝、A2 草绿、B1 暖黄、B2 桃粉、C1 薰衣草紫）。
- 所有功能均需编写 `pytest` 自动化测试并通过。

---

### Task 1: 后端 CEFR 难度统计与加权定级算法实现 (Backend Stats & Scoring)

**Files:**
- Modify: `server.py:140-180`
- Test: `test_server.py`

**Interfaces:**
- Produces: `stats` in `process_german_text` return value:
  ```python
  {
      "word_count": int,
      "est_reading_minutes": int,
      "recommended_level": str, # "A1", "A2", "B1", "B2+"
      "cefr_counts": Dict[str, int], # {"A1": 35, "A2": 10, "B1": 5, "B2": 2, "C1": 0}
      "cefr_percentages": Dict[str, float] # {"A1": 67.3, "A2": 19.2, "B1": 9.6, "B2": 3.8, "C1": 0.0}
  }
  ```
- Ensures: `/api/articles` 列表接口返回 `stats` 供首页文库展示。

- [ ] **Step 1: Write the failing test**

在 `test_server.py` 中添加难度统计与分级测试：

```python
def test_cefr_text_difficulty_stats():
    from server import process_german_text
    
    # Simple A1 text
    a1_text = "Hallo! Ich heiße Lukas. Ich lerne Deutsch und trinke Kaffee."
    res_a1 = process_german_text(a1_text)
    assert "stats" in res_a1
    assert res_a1["stats"]["word_count"] > 0
    assert res_a1["stats"]["recommended_level"] == "A1"
    assert res_a1["stats"]["cefr_percentages"]["A1"] > 60.0
    
    # Advanced B2/C1 text
    b2_text = "Die Digitalisierung und Transformation werfen ethische Fragestellungen von existenzieller Tragweite auf."
    res_b2 = process_german_text(b2_text)
    assert res_b2["stats"]["recommended_level"] in ("B1", "B2+", "C1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_cefr_text_difficulty_stats -v`  
Expected: FAIL with `KeyError: 'stats'`.

- [ ] **Step 3: Implement difficulty computation in `server.py`**

在 `server.py` 的 `process_german_text` 中统计词汇并计算分级：

```python
def calculate_cefr_stats(tokens_list: list) -> Dict[str, Any]:
    counts = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
    words = [t for t in tokens_list if t["cefr_level"]]
    total_words = len(words)
    
    for w in words:
        lvl = w["cefr_level"]
        if lvl in counts:
            counts[lvl] += 1
            
    percentages = {}
    for lvl, cnt in counts.items():
        percentages[lvl] = round((cnt / total_words * 100), 1) if total_words > 0 else 0.0
        
    non_a1_count = total_words - counts["A1"]
    non_a1_ratio = (non_a1_count / total_words) if total_words > 0 else 0.0
    
    if non_a1_ratio < 0.15:
        recommended = "A1"
    elif non_a1_ratio < 0.30:
        recommended = "A2"
    elif non_a1_ratio < 0.50:
        recommended = "B1"
    else:
        recommended = "B2+"
        
    est_minutes = max(1, round(total_words / 90)) # 90 words/min 精读标准
    
    return {
        "word_count": total_words,
        "est_reading_minutes": est_minutes,
        "recommended_level": recommended,
        "cefr_counts": counts,
        "cefr_percentages": percentages
    }
```

并在 `process_german_text` 返回结果中加入 `"stats": stats`。
在 `/api/articles` 列表中把 `stats` 字段一并解析或返回。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(nlp): add CEFR text difficulty analyzer and weighted grading algorithm"
```

---

### Task 2: 首页文稿库迷你多色难度条展示 (Library Mini CEFR Bar)

**Files:**
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- UI: 在文稿列表行（`.article-row`）中，右侧显示迷你 CEFR 占比分段条（`.mini-cefr-bar`）与推荐等级徽章（`.mini-level-badge`）。

- [ ] **Step 1: Add CSS for Mini CEFR Bar in `static/style.css`**

```css
/* Mini CEFR Bar on Article Rows */
.mini-bar-wrap {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.35rem;
}
.mini-cefr-bar {
  display: flex;
  height: 6px;
  width: 110px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--rule);
}
.mini-seg { height: 100%; }
.mini-seg.A1 { background: var(--hl-A1-ink); }
.mini-seg.A2 { background: var(--hl-A2-ink); }
.mini-seg.B1 { background: var(--hl-B1-ink); }
.mini-seg.B2 { background: var(--hl-B2-ink); }
.mini-seg.C1 { background: var(--hl-C1-ink); }

.mini-level-badge {
  font-family: var(--mono);
  font-size: 0.625rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 0.06em;
}
.mini-level-A1 { background: var(--hl-A1); color: var(--hl-A1-ink); }
.mini-level-A2 { background: var(--hl-A2); color: var(--hl-A2-ink); }
.mini-level-B1 { background: var(--hl-B1); color: var(--hl-B1-ink); }
.mini-level-B2 { background: var(--hl-B2); color: var(--hl-B2-ink); }
```

- [ ] **Step 2: Update `loadArticles()` in `static/app.js` to render mini bar**

```javascript
function renderMiniBar(stats) {
  if (!stats || !stats.cefr_percentages) return '';
  const p = stats.cefr_percentages;
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl => 
    p[lvl] > 0 ? `<div class="mini-seg ${lvl}" style="width:${p[lvl]}%" title="${lvl}: ${p[lvl]}%"></div>` : ''
  ).join('');
  
  const rec = stats.recommended_level || 'A1';
  const recClass = rec.startsWith('B2') ? 'mini-level-B2' : `mini-level-${rec}`;
  
  return `
    <div class="mini-bar-wrap">
      <span class="mini-level-badge ${recClass}">${rec} 推荐</span>
      <div class="mini-cefr-bar">${segs}</div>
      <span style="font-size:0.6875rem;color:var(--pencil);font-family:var(--mono);">约 ${stats.est_reading_minutes || 1} 分钟</span>
    </div>
  `;
}
```

- [ ] **Step 3: Verify in browser**

打开 `http://localhost:8000`，确认首页 4 篇样文（A1/A2/B1/B2）各自拥有正确的推荐等级徽章与彩色分布比例条。

- [ ] **Step 4: Commit**

```bash
git add static/style.css static/app.js
git commit -m "feat(ui): render mini CEFR difficulty bars and badges on article list"
```

---

### Task 3: 阅读器顶部 CEFR 难度热力条与统计栏 (Reader Header CEFR Heatbar)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- UI: 在阅读器顶部 Bar 下方呈现完整的 CEFR 难度横向分布热力条，显示各等级的百分比与词数，并右对齐展示预估精读时间。

- [ ] **Step 1: Update `static/index.html` Reader Header**

在 `static/index.html` 的 `#view-reader` 顶部加入 `#reader-stats-bar`：

```html
<div id="view-reader" class="view">
  <div class="reader-topbar">
    <button class="btn btn-ghost" onclick="show('home')">← 返回文库</button>
    <h2 id="reader-title"></h2>
    <div id="reader-meta-badge" class="mini-level-badge mini-level-A1">A1</div>
  </div>

  <!-- CEFR Distribution Heatbar & Info -->
  <div id="reader-heatbar-wrap" class="reader-heatbar-wrap">
    <div class="heatbar-label">
      <span>欧标难度分布 · CEFR SPECTRUM</span>
      <span id="heatbar-time" style="font-family:var(--mono);color:var(--pencil);font-size:0.75rem;"></span>
    </div>
    <div id="reader-heatbar" class="reader-heatbar"></div>
  </div>

  <div id="reader-content" lang="de"></div>
</div>
```

- [ ] **Step 2: Add CSS for Reader Heatbar in `static/style.css`**

```css
/* Reader CEFR Distribution Heatbar */
.reader-heatbar-wrap {
  margin-bottom: 1.5rem;
  background: var(--paper-tint);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 0.875rem 1rem;
}
.heatbar-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: var(--mono);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--pencil);
  margin-bottom: 0.625rem;
}
.reader-heatbar {
  display: flex;
  height: 24px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--rule);
  background: #fff;
}
.heatbar-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
  transition: opacity 0.15s, transform 0.15s;
  white-space: nowrap;
  padding: 0 4px;
}
.heatbar-seg:hover { opacity: 0.88; }
.heatbar-seg.A1 { background: var(--hl-A1); color: var(--hl-A1-ink); }
.heatbar-seg.A2 { background: var(--hl-A2); color: var(--hl-A2-ink); }
.heatbar-seg.B1 { background: var(--hl-B1); color: var(--hl-B1-ink); }
.heatbar-seg.B2 { background: var(--hl-B2); color: var(--hl-B2-ink); }
.heatbar-seg.C1 { background: var(--hl-C1); color: var(--hl-C1-ink); }
```

- [ ] **Step 3: Update `openReader()` in `static/app.js` to render heatbar**

```javascript
function renderReaderHeatbar(stats) {
  if (!stats || !stats.cefr_percentages) return;
  const p = stats.cefr_percentages;
  const counts = stats.cefr_counts;
  const segs = ['A1', 'A2', 'B1', 'B2', 'C1'].map(lvl => {
    if (p[lvl] <= 0) return '';
    return `<div class="heatbar-seg ${lvl}" style="width:${p[lvl]}%" onclick="toggleCefrFocus('${lvl}')" title="点击聚焦 ${lvl} 级别生词 (${counts[lvl]} 词)">${lvl} ${p[lvl]}%</div>`;
  }).join('');

  document.getElementById('reader-heatbar').innerHTML = segs;
  document.getElementById('heatbar-time').textContent = `预计精读 ${stats.est_reading_minutes || 1} 分钟 · 共 ${stats.word_count || 0} 词`;
  
  const rec = stats.recommended_level || 'A1';
  const badge = document.getElementById('reader-meta-badge');
  badge.textContent = `建议级别: ${rec}`;
  badge.className = `mini-level-badge mini-level-${rec.startsWith('B2') ? 'B2' : rec}`;
}
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): add reader header CEFR heatbar and reading time estimation"
```

---

### Task 4: 等级聚焦高亮联动与脉冲动效 (Interactive Focus Filter)

**Files:**
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- Produces: `toggleCefrFocus(level: string)`
- UI Animation: 点击分段时，该等级所有生词产生脉冲高亮（`animation: tokenPulse 0.6s infinite alternate`），非该等级词汇柔和淡化（`opacity: 0.35`），支持再次点击或按 `Esc` 退出聚焦。

- [ ] **Step 1: Add Focus Filter CSS in `static/style.css`**

```css
/* Focus Filter Mode */
.heatbar-seg.focused {
  outline: 2px solid var(--ink);
  outline-offset: -2px;
  font-weight: 800;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,0.2);
}

body.focus-mode .tok {
  opacity: 0.28;
  transition: opacity 0.25s, transform 0.25s;
}

body.focus-mode .tok.focus-active {
  opacity: 1 !important;
  transform: scale(1.06);
  display: inline-block;
  box-shadow: 0 0 0 2px var(--ink);
  animation: tokenPulse 0.7s ease-in-out infinite alternate;
}

@keyframes tokenPulse {
  0% { transform: scale(1.02); }
  100% { transform: scale(1.1); box-shadow: 0 0 8px rgba(216, 72, 43, 0.5); }
}
```

- [ ] **Step 2: Implement `toggleCefrFocus` in `static/app.js`**

```javascript
let currentFocusedLevel = null;

function toggleCefrFocus(level) {
  if (currentFocusedLevel === level) {
    clearCefrFocus();
    return;
  }
  
  currentFocusedLevel = level;
  document.body.classList.add('focus-mode');
  
  // Highlight heatbar segment
  document.querySelectorAll('.heatbar-seg').forEach(el => {
    el.classList.toggle('focused', el.classList.contains(level));
  });

  // Focus tokens of this level
  document.querySelectorAll('.tok').forEach(el => {
    const matches = el.classList.contains(level);
    el.classList.toggle('focus-active', matches);
  });
}

function clearCefrFocus() {
  currentFocusedLevel = null;
  document.body.classList.remove('focus-mode');
  document.querySelectorAll('.heatbar-seg').forEach(el => el.classList.remove('focused'));
  document.querySelectorAll('.tok').forEach(el => el.classList.remove('focus-active'));
}
```

并将 `clearCefrFocus()` 挂载至 `Escape` 键盘监听器与视图切换。

- [ ] **Step 3: Run pytest and manual verification**

Run: `pytest`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add static/style.css static/app.js
git commit -m "feat(interaction): add CEFR level focus filter with pulse animation"
```

---

### Task 5: 全链路验收与回归测试 (End-to-End Verification)

**Files:**
- Test: `test_server.py`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest -v`  
Expected: 100% PASS with 0 errors.

- [ ] **Step 2: Secret key scan check**

Run secret key scan check.

- [ ] **Step 3: Live UI flow verification**

打开 `http://localhost:8000`：
1. 首页直接呈现 4 篇样文的迷你多色 CEFR 条与预估精读时间。
2. 点击进入任意文章，顶部展示完整的 CEFR 难度热力条与百分比。
3. 点击顶部热力条中的 `B1` 或 `B2`，正文中所有对应等级生词产生脉冲发光高亮，其他词汇柔和淡化。
4. 按 `Esc` 或再次点击该分段，平滑恢复正常阅读模式。
