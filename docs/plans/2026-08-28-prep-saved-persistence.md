# 介词矩阵「已入卡」持久化计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 介词矩阵的「已入卡」状态从 session-only Set 改为服务端持久化。重进该段、刷新页面、换设备（导入备份后）都能看到哪些搭配已经存过卡。

**Architecture:** 新增 `prep_saved` 表存 `(lemma, praep, kasus)` 三元组。前端 `_prepSavedKeys` 从 `GET /api/prep/saved` 初始化（不再空 Set）。`savePrepCardFromMatrix` 成功后额外 `POST /api/prep/saved` 写入。备份/恢复时带上该表数据。

**Tech Stack:** SQLite, FastAPI, vanilla JS

**验收标准:** 316 测试全绿（+新增 2-3 条），`_prepSavedKeys` 不再是空 Set 起步，介词矩阵段重进后按钮状态保持。

---

## 数据流

```
加载介词矩阵 → GET /api/prep/saved → 填充 _prepSavedKeys → 按钮 disabled
点击「入卡」  → POST /api/cards/vocab + POST /api/prep/saved → 按钮变「✓ 已存」
重进矩阵段   → GET /api/prep/saved → 按钮状态恢复
备份/恢复    → prep_saved 表随 vocab_cards 一起备份
```

---

## 文件变更

| 文件 | 改动 |
|---|---|
| `database.py` | 新增 `prep_saved` 表定义 + `init_prep_saved()` + `get_prep_saved()` + `add_prep_saved()` |
| `server.py` | 新增 `GET /api/prep/saved` + `POST /api/prep/saved` 路由；备份 payload 带上 `prep_saved` |
| `static/js/cards.js` | `loadPrepMatrix` 后调 `GET /api/prep/saved` 填充 `_prepSavedKeys`；`savePrepCardFromMatrix` 成功后调 `POST /api/prep/saved` |
| `test_server.py` | 新增 2 条测试 |

---

### Task 1: 数据库层 — prep_saved 表 + CRUD

**Files:**
- Modify: `database.py`（init_db 内加表定义 + 新增函数）

**Interfaces:**
- Produces: `get_prep_saved() -> Set[str]`, `add_prep_saved(lemma, praep, kasus)`, `init_prep_saved()`

- [ ] **Step 1: 在 `database.py` 的 `init_db()` 里加表定义**

在 `grammar_cards` 表定义之后（约 line 155），加：

```python
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prep_saved (
                lemma TEXT NOT NULL,
                praep TEXT NOT NULL,
                kasus TEXT NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (lemma, praep, kasus)
            );
        """)
```

主键 `(lemma, praep, kasus)` 天然防重复插入。

- [ ] **Step 2: 新增 `get_prep_saved()` 函数**

在 `database.py` 末尾加：

```python
def get_prep_saved() -> set:
    """返回所有已入卡的 (lemma, praep, kasus) 三元组 key。"""
    conn = get_db()
    rows = conn.execute("SELECT lemma, praep, kasus FROM prep_saved").fetchall()
    return {f"{r['lemma']}|{r['praep']}|{r['kasus']}" for r in rows}
```

- [ ] **Step 3: 新增 `add_prep_saved()` 函数**

```python
def add_prep_saved(lemma: str, praep: str, kasus: str):
    """记录一条搭配已入卡。幂等：重复插入被主键忽略。"""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO prep_saved (lemma, praep, kasus) VALUES (?, ?, ?)",
        (lemma, praep, kasus),
    )
    conn.commit()
```

- [ ] **Step 4: 测试**

```bash
python -m pytest -q test_server.py -k "prep" 2>&1 | tail -5
```

---

### Task 2: API 层 — GET/POST /api/prep/saved

**Files:**
- Modify: `server.py`（新增两个路由）

**Interfaces:**
- Consumes: `get_prep_saved()`, `add_prep_saved()` from database.py
- Produces: `GET /api/prep/saved` 返回 `{"keys": ["lemma|praep|kasus", ...]}`；`POST /api/prep/saved` 写入

- [ ] **Step 1: 新增 GET 路由**

在 `api_prep_matrix()` 之后加：

```python
@app.get("/api/prep/saved")
def api_prep_saved():
    """返回当前用户已入卡的搭配 key 列表。"""
    from database import get_prep_saved
    return {"keys": sorted(get_prep_saved())}
```

- [ ] **Step 2: 新增 POST 路由**

```python
class PrepSavedReq(BaseModel):
    lemma: str
    praep: str
    kasus: str

@app.post("/api/prep/saved")
def api_add_prep_saved(req: PrepSavedReq):
    from database import add_prep_saved
    add_prep_saved(req.lemma, req.praep, req.kasus)
    return {"status": "ok"}
```

- [ ] **Step 3: 测试**

```bash
python -m pytest -q -k "version_is_consistent" 2>&1 | tail -3
```

---

### Task 3: 前端 — 从服务端初始化 + 保存时写入

**Files:**
- Modify: `static/js/cards.js`

**Interfaces:**
- Consumes: `GET /api/prep/saved` 返回 `{"keys": [...]}`；`POST /api/prep/saved`
- Produces: `_prepSavedKeys` 从服务端数据初始化

- [ ] **Step 1: `loadPrepMatrix` 成功后加载已存 key**

在 `loadPrepMatrix` 的 try 块内，`_prepMatrixCache = data` 之后加：

```javascript
      // 从服务端加载已入卡状态，替代空 Set
      try {
        const savedData = await api('/api/prep/saved');
        if (savedData && Array.isArray(savedData.keys)) {
          _prepSavedKeys.clear();
          savedData.keys.forEach(k => _prepSavedKeys.add(k));
        }
      } catch { /* 首次访问无数据，忽略 */ }
```

- [ ] **Step 2: `savePrepCardFromMatrix` 成功后写入服务端**

在 `_prepSavedKeys.add(...)` 之后加：

```javascript
    // 异步写入服务端，不阻塞 UI
    api('/api/prep/saved', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lemma, praep, kasus })
    }).catch(() => {});  // 写入失败不阻塞，下次加载会重新查询
```

- [ ] **Step 3: `node --check` 验证语法**

- [ ] **Step 4: 全量测试**

```bash
python -m pytest -q
```

---

### Task 4: 备份兼容 — prep_saved 随备份走

**Files:**
- Modify: `server.py`（`build_backup_payload`）
- Modify: `server.py`（`restore_database_backup`）

**Interfaces:**
- Consumes: `prep_saved` 表
- Produces: 备份 JSON 里含 `prep_saved` 字段；恢复时写入

- [ ] **Step 1: `build_backup_payload` 带上 prep_saved**

在 `build_backup_payload()` 里，跟 `vocab_cards` 一起查：

```python
    prep_saved = [dict(r) for r in conn.execute("SELECT * FROM prep_saved").fetchall()]
```

返回值里加 `"prep_saved": prep_saved`。

- [ ] **Step 2: `restore_database_backup` 恢复 prep_saved**

在 restore 的 `_replace_tables` 调用或单独处理里，恢复 `prep_saved` 表：

```python
    if "prep_saved" in data:
        conn.executemany(
            "INSERT OR IGNORE INTO prep_saved (lemma, praep, kasus, saved_at) VALUES (?, ?, ?, ?)",
            [(r["lemma"], r["praep"], r["kasus"], r.get("saved_at")) for r in data["prep_saved"]]
        )
```

- [ ] **Step 3: 全量测试**

```bash
python -m pytest -q
```

---

### Task 5: 新增回归测试

**Files:**
- Modify: `test_server.py`

**Interfaces:**
- Consumes: `GET /api/prep/saved`, `POST /api/prep/saved`

- [ ] **Step 1: 测试 GET /api/prep/saved 返回结构**

```python
def test_prep_saved_endpoint_returns_keys():
    """GET /api/prep/saved 返回 {"keys": [...]} 结构。"""
    resp = client.get("/api/prep/saved")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert isinstance(data["keys"], list)
```

- [ ] **Step 2: 测试 POST + GET 往返**

```python
def test_prep_saved_post_and_get_roundtrip():
    """POST 一条搭配后 GET 能查到。"""
    resp = client.post("/api/prep/saved", json={"lemma": "freuen", "praep": "auf", "kasus": "Akk"})
    assert resp.status_code == 200
    resp = client.get("/api/prep/saved")
    data = resp.json()
    assert "freuen|auf|Akk" in data["keys"]
```

- [ ] **Step 3: 测试幂等性**

```python
def test_prep_saved_idempotent():
    """重复 POST 同一条搭配不会出错（主键约束）。"""
    client.post("/api/prep/saved", json={"lemma": "warten", "praep": "auf", "kasus": "Akk"})
    client.post("/api/prep/saved", json={"lemma": "warten", "praep": "auf", "kasus": "Akk"})
    resp = client.get("/api/prep/saved")
    assert resp.json()["keys"].count("warten|auf|Akk") == 1
```

- [ ] **Step 4: 全量测试**

```bash
python -m pytest -q
```

Expected: 319 passed（316 + 3 新增）

---

### Task 6: 文档 + 版本 bump

**Files:**
- Modify: `AGENTS.md`（HEAD + 版本历史 + 测试计数）
- Modify: `FEATURES.md`（里程碑行）

- [ ] **Step 1: 版本 bump**（如需发版）

`sw.js` / `index.html` / `build.gradle` 三处同步到 v4.6.4 / 40604。

- [ ] **Step 2: AGENTS.md 回填**

HEAD → tag，测试 316 → 319，版本历史加 v4.6.4 行。

- [ ] **Step 3: FEATURES.md 加行**

- [ ] **Step 4: 全量测试**

```bash
python -m pytest -q
```

- [ ] **Step 5: Commit + push + tag**

---

## 手动验证清单

1. 进介词矩阵 → 点几条「入卡」 → 按钮变「✓ 已存」
2. 刷新页面 → 重进介词矩阵 → 之前入卡的按钮仍然显示「✓ 已存」
3. `GET /api/prep/saved` 返回正确的 key 列表
4. 备份 → 还原 → 介词矩阵已入卡状态恢复
