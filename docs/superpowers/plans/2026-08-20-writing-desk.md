# v3.11.0 德语写作润色台（Schreibwerkstatt）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DeLector 里加一个「德语写作润色台」：粘贴德语作文 → 本地规则即时标出冠词/格位一致与介词支配格错误（行内下划线 + 侧栏纠错）→ CEFR 评级 → 任一错误一键存成 Anki 语法卡（含正确形式）→ 显式「AI 润色全文」按钮走 DeepSeek。

**Architecture:** 混合引擎。新模块 `writing_rules.py` 在已捆绑的 spaCy 德语模型上跑两条高置信规则（移植 MrGrammar 的一致检测基底 + 自写介词格规则，参考 LanguageTool 介词映射数据），`nlp=None` 时优雅降级为零错误。后端 `server.py` 加 essays 草稿库 CRUD + analyze/cards/ai-polish 端点；前端新视图 `#view-writer` 用纯 CSS span 切分做行内下划线 + 侧栏（抄 MrGrammar 前端模式，零编辑器依赖）。

**Tech Stack:** Python 3.10+ / FastAPI / spaCy (de_core_news_sm|md) / SQLite / vanilla JS ESM + PWA。**不引入** LanguageTool（Java/LGPL 太重）、`language_tool_python`（GPL-3 陷阱）、任何新 pip 依赖。

**Spec:** 见本文件「已锁定的决策（grilling 访谈结论）」与「开源调研结论」。本方案从该 spec 推演，executor 需两者都读。

## Global Constraints

- 现有 114 测试必须保持全绿（test_server 84 / test_syntax_tree 15 / test_core_dict_ext 5 / test_edge_tts_mini 10）。
- **FP 守卫（最高准则）**：规则只报高置信错误，宁可漏报不可误报。双侧 morph 值必须都在；`corrected_form` 必须可算；双格介词（in/an/auf/über/unter/vor/hinter/neben/zwischen）整组跳过；`nlp=None` 时返回零错误。
- **AI 不缓存**：`/api/writing/ai-polish` 无缓存（显式付费按钮）。不建 ai_cache 表。
- **不嵌 LanguageTool**，不引 GPL 依赖。MrGrammar（MIT）可移植/抄模式；LanguageTool 的介词映射是事实数据，可参考。
- 错误分类封闭集合：`artikel / kasus / praeposition / andere`。
- 版本：本功能作为 **v3.11.0**（android versionCode `31100`、versionName `"3.11.0"`），bump `static/index.html` 与 `static/sw.js` 的 `?v=` / `CACHE_NAME`。
- 提交守卫 `.githooks/pre-commit` 生效，commit message 祈使句讲「为什么」。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `writing_rules.py` | 新建 | 规则引擎：`analyze_essay_text` + 两条检测 + `decline_determiner` 变格表（纯函数，`nlp` 参数注入） |
| `server.py` | 修改 | `init_db` 加 `essays` 表 + `grammar_cards` 迁移；`GrammarCardReq` 加两字段；7 个新端点 |
| `test_writing_rules.py` | 新建 | 规则引擎单测（正反句 + FP 守卫 + nlp=None） |
| `test_server.py` | 修改 | 迁移/CRUD/端点/存卡 测试 |
| `static/index.html` | 修改 | `#view-writer` 视图 + 桌面/移动导航 + `?v=` bump |
| `static/js/writer.js` | 新建 | 行内下划线渲染 + 侧栏 + 存卡 + AI 润色 + 作文库 |
| `static/js/main.js` | 修改 | 路由 + writer 导出挂 window |
| `static/style.css` | 修改 | `.writer-*` 样式 |
| `static/sw.js` | 修改 | CACHE_NAME + STATIC_ASSETS bump 3.11.0 |
| `android/app/build.gradle` | 修改 | versionCode/versionName |

---

## Task 1: Schema —— `essays` 表 + `grammar_cards` 迁移

**Files:**
- Modify: `server.py:133`（`init_db`）、`server.py:170-228`（DDL + 自动迁移循环）
- Test: `test_server.py`

**Interfaces:**
- Produces: `essays` 表列 `id/title/content/analysis_json/cefr_level/error_count/sentence_count/created_at/updated_at`；`grammar_cards` 新增列 `corrected_form TEXT`、`error_type TEXT`（默认空串）。

- [x] **Step 1: 写失败测试**（断言迁移后新列存在）

在 `test_server.py` 新增（放在 `clean_db` fixture 之后）：
```python
def test_grammar_cards_migration_adds_columns():
    import sqlite3
    conn = sqlite3.connect("test_delector.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(grammar_cards)")}
    assert "corrected_form" in cols and "error_type" in cols, f"缺列: {cols}"

def test_essays_table_created():
    import sqlite3
    conn = sqlite3.connect("test_delector.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(essays)")}
    assert {"id", "title", "content", "analysis_json",
            "cefr_level", "error_count", "created_at"} <= cols
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_server.py::test_grammar_cards_migration_adds_columns test_server.py::test_essays_table_created -v`
Expected: FAIL（`init_db` 尚不建表/不加列）

- [x] **Step 3: 实现**

`server.py` `init_db`（:133 起）的 `grammar_cards` DDL 加两列：
```python
# grammar_cards 表 DDL 内（:170-189 现有列之后）：
#   corrected_form TEXT DEFAULT '',
#   error_type TEXT DEFAULT '',
```
在自动迁移循环（:210-228）的 `for table in [...]` 内加：
```python
if table == "grammar_cards":
    for col in ("corrected_form", "error_type"):
        if col not in cols:
            conn.execute(f"ALTER TABLE grammar_cards ADD COLUMN {col} TEXT DEFAULT ''")
```
`essays` 新表 DDL 加在 `grammar_cards` 块之后：
```sql
CREATE TABLE IF NOT EXISTS essays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    cefr_level TEXT,
    error_count INTEGER DEFAULT 0,
    sentence_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_server.py -q`
Expected: 全绿

- [x] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(writer): essays 表 + grammar_cards 加 corrected_form/error_type 列"
```

---

## Task 2: 规则引擎 `writing_rules.py`

**Files:**
- Create: `writing_rules.py`
- Test: `test_writing_rules.py`（新建）

**Interfaces:**
- Consumes: `linguistics.lookup_prep_collocations`（linguistics.py:1325，返回 `[{praeposition,kasus,...}]`）、`core_dict.lookup_core_vocab`（可选 gender 兜底）、`server.calculate_cefr_stats`（server.py:455，测试里直接复用或传入 tokens）。
- Produces: `analyze_essay_text(text, nlp=None) -> dict`，shape：
```python
{"version": "3.11.0", "cefr": {...}, "error_count": 3,
 "sentences": [{"text": "...", "spans": [
    {"error_type": "artikel"|"kasus"|"praeposition"|"andere",
     "corrected_form": str, "explanation_zh": str, "start": int, "end": int}]}]}
```
`start/end` 为**句内相对字符 offset**。

- [x] **Step 1: 写失败测试**

新建 `test_writing_rules.py`：
```python
import spacy
import pytest
from writing_rules import analyze_essay_text

@pytest.fixture(scope="module")
def nlp():
    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm 未安装")

def _spans(text, nlp):
    return [s for s in analyze_essay_text(text, nlp)["sentences"] for s in s["spans"]]

def test_agreement_wrong_case(nlp):
    spans = _spans("Ich sehe der Mann.", nlp)
    assert spans and spans[0]["error_type"] == "artikel"
    assert "den Mann" in spans[0]["corrected_form"]

def test_agreement_correct_sentence_clean(nlp):
    assert _spans("Ich sehe den Mann.", nlp) == []

def test_prep_governed_case_dativ(nlp):
    spans = _spans("Ich fahre mit der Auto.", nlp)
    assert spans and spans[0]["error_type"] == "kasus"
    assert "dem Auto" in spans[0]["corrected_form"]

def test_prep_one_case_correct_clean(nlp):
    assert _spans("Ich fahre mit dem Auto.", nlp) == []

def test_two_case_preposition_skipped(nlp):
    assert _spans("Ich gehe in der Stadt.", nlp) == []

def test_no_determiner_not_flagged(nlp):
    assert _spans("Ich fahre mit Auto.", nlp) == []

def test_no_spacy_returns_empty():
    r = analyze_essay_text("Ich sehe der Mann.", None)
    assert r["error_count"] == 0
    assert "cefr" in r
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_writing_rules.py -v`
Expected: FAIL（`ModuleNotFoundError: writing_rules`）

- [x] **Step 3: 实现最小可用版本**

`writing_rules.py`（核心逻辑，FP 守卫内嵌）：
```python
# -*- coding: utf-8 -*-
"""德语写作本地规则引擎：冠词/格位一致 + 介词支配格。

只报高置信错误（宁可漏报不可误报）。nlp=None 时优雅返回零错误 + CEFR。
spaCy 模型由调用方注入（server 传 Android 安全加载的 nlp；测试直传 spacy.load）。
"""
import hashlib

_TWO_WAY_PREPS = {"in", "an", "auf", "über", "unter", "vor", "hinter",
                  "neben", "zwischen"}
# 固定单格介词 → 支配格（事实数据，参考 LanguageTool PrepositionToCases）
_PREP_CASE = {
    "mit": "Dat", "bei": "Dat", "nach": "Dat", "seit": "Dat",
    "aus": "Dat", "von": "Dat", "zu": "Dat", "gegenüber": "Dat", "entlang": "Akk",
    "ohne": "Akk", "für": "Akk", "gegen": "Akk", "durch": "Akk", "um": "Akk",
    "wegen": "Gen", "trotz": "Gen", "während": "Gen",
}
# 冠词变格表：(lemma → gender → case → 表面形式)
_DECLINE = {
    "der": {"Masc": {"Nom": "der", "Akk": "den", "Dat": "dem", "Gen": "des"},
            "Fem":  {"Nom": "die", "Akk": "die", "Dat": "der", "Gen": "der"},
            "Neut": {"Nom": "das", "Akk": "das", "Dat": "dem", "Gen": "des"}},
    "die": {"Masc": {"Nom": "der", "Akk": "die", "Dat": "der", "Gen": "der"},
            "Fem":  {"Nom": "die", "Akk": "die", "Dat": "der", "Gen": "der"},
            "Neut": {"Nom": "das", "Akk": "die", "Dat": "der", "Gen": "der"}},
    "das": {"Masc": {"Nom": "der", "Akk": "das", "Dat": "dem", "Gen": "des"},
            "Fem":  {"Nom": "die", "Akk": "das", "Dat": "der", "Gen": "der"},
            "Neut": {"Nom": "das", "Akk": "das", "Dat": "dem", "Gen": "des"}},
    "ein": {"Masc": {"Nom": "ein", "Akk": "einen", "Dat": "einem", "Gen": "eines"},
            "Fem":  {"Nom": "eine", "Akk": "eine", "Dat": "einer", "Gen": "einer"},
            "Neut": {"Nom": "ein", "Akk": "ein", "Dat": "einem", "Gen": "eines"}},
}
_DET_LEMMAS = {"der", "die", "das", "ein", "eine", "einen", "einem", "einer", "eines"}


def decline_determiner(lemma, gender, number, case):
    """返回该冠词在 (gender,number,case) 下应取的表面形式；算不出返回 None。"""
    if number != "Sing" or gender not in _DECLINE.get(lemma, {}):
        return None
    return _DECLINE[lemma][gender].get(case)


def _tok_off(tok, base):
    """句内相对字符 offset。tok.idx 是文档级，需减去句首偏移。"""
    return tok.idx - base, tok.idx + len(tok.text) - base


def _np_det(noun_tok):
    """返回名词的限定词子节点（dep 为 det/nk/pnc），没有返回 None。"""
    for c in noun_tok.children:
        if c.pos_ == "DET":
            return c
    return None


def detect_determiner_noun_agreement(tokens, base):
    """规则 A：DET 与 head NOUN 的 case/gender 一致。"""
    spans = []
    for tok in tokens:
        if tok.pos_ != "DET" or tok.dep_ not in ("det", "nk", "pnc"):
            continue
        head = tok.head
        if head.pos_ != "NOUN":
            continue
        dc, dg = tok.morph.get("Case"), tok.morph.get("Gender")
        nc, ng = head.morph.get("Case"), head.morph.get("Gender")
        # FP 守卫：双侧 case 必须都在；gender 在 Nom 下不可靠，跳过 Nom 误报
        if not dc or not nc or (dc != nc and not ng):
            continue
        if dc != nc:
            form = decline_determiner(tok.lemma_, ng or dg, head.morph.get("Number") or "Sing", nc)
            if not form:
                continue
            start, end = _tok_off(head, base)
            spans.append({
                "error_type": "artikel",
                "corrected_form": f"{form} {head.text}",
                "explanation_zh": f"「{head.text}」是{ng or dg}性{nc}格，冠词应为「{form}」而非「{tok.text}」。",
                "start": start, "end": end,
            })
    return spans


def detect_preposition_case(tokens, base):
    """规则 B：固定单格介词 vs 介宾名词短语的实际格。"""
    spans = []
    for tok in tokens:
        if tok.pos_ != "ADP":
            continue
        prep = tok.text.lower()
        if prep in _TWO_WAY_PREPS:
            continue
        expected = _PREP_CASE.get(prep)
        if expected is None:
            from linguistics import lookup_prep_collocations
            rows = lookup_prep_collocations(tok.head.lemma_)
            match = next((r for r in rows if r["praeposition"] == prep), None)
            if match:
                expected = match["kasus"]
            else:
                continue
        # 取介宾名词：ADP 的子节点里 dep 是 pobj/op/nk 的那个
        obj = next((c for c in tok.children if c.dep_ in ("pobj", "op", "nk")), None)
        if obj is None:
            continue
        actual = obj.morph.get("Case")
        if not actual:
            det = _np_det(obj)
            if det is not None:
                actual = det.morph.get("Case")
        if not actual or expected == actual:
            continue
        det = _np_det(obj)
        if det is None:
            continue
        form = decline_determiner(det.lemma_, obj.morph.get("Gender") or det.morph.get("Gender"),
                                  obj.morph.get("Number") or "Sing", expected)
        if form is None:
            continue
        start, end = _tok_off(det, base) if det.i < obj.i else _tok_off(obj, base)
        end = max(_tok_off(det, base)[1], _tok_off(obj, base)[1])
        spans.append({
            "error_type": "kasus",
            "corrected_form": f"{form} {obj.text}",
            "explanation_zh": f"介宾「{prep}」要求{expected}格，名词「{obj.text}」前应为「{form}」。",
            "start": start, "end": end,
        })
    return spans


def analyze_essay_text(text, nlp=None):
    """入口。nlp=None 时零错误 + 空 CEFR。"""
    sentences = []
    error_count = 0
    if nlp is not None:
        doc = nlp(text)
        for sent in doc.sents:
            toks = list(sent)
            base = toks[0].idx
            spans = (detect_determiner_noun_agreement(toks, base)
                     + detect_preposition_case(toks, base))
            sentences.append({"text": sent.text, "spans": spans})
            error_count += len(spans)
    cefr = _cefr_basic(text)
    return {"version": "3.11.0", "cefr": cefr, "error_count": error_count,
            "sentences": sentences}


def _cefr_basic(text):
    """词汇频率估测（MVP 简化：词数 + 平均长度启发）。完整版复用 calculate_cefr_stats。"""
    words = [w for w in text.split() if any(ch.isalpha() for ch in w)]
    return {"word_count": len(words), "recommended_level": "A1",
            "note_zh": "词汇频率估测，非写作能力分"}
```
> 注：MVP 的 CEFR 用简化的 `_cefr_basic` 占位（词数 + 固定 A1）。接入真实 `calculate_cefr_stats` 放 Task 3（server 侧已有 token 列表时更准）。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_writing_rules.py -v`
Expected: 全绿。若 `mit der Auto` 未命中（spaCy 把 `Auto` 标成 Dat 而 det `der` 是 Fem/Dat），需按实测调整 `_DECLINE`/判定；FP 守卫保证零误报测试（`den Mann`、`mit dem Auto`）必须空。

- [x] **Step 5: Commit**

```bash
git add writing_rules.py test_writing_rules.py
git commit -m "feat(writer): 本地规则引擎——冠词一致 + 介词格检测，FP 守卫内嵌"
```

---

## Task 3: 后端端点 —— analyze + essays CRUD + cards + ai-polish

**Files:**
- Modify: `server.py`（`GrammarCardReq` :659 附近、`add_grammar_card` :1262、新端点区）
- Test: `test_server.py`

**Interfaces:**
- Consumes: `writing_rules.analyze_essay_text`（Task 2）、`calculate_cefr_stats`（server.py:455）、`add_grammar_card`、`get_effective_api_*`（server.py:251-258）。
- Produces:
  - `POST /api/writing/analyze` `{text}` → `{analysis_json}`
  - `POST/GET/PUT/DELETE /api/essays[/{id}]` → CRUD，content 变更重分析
  - `POST /api/writing/cards` `{essay_id, sentence_id, span_index}` → `{status, id}`
  - `POST /api/writing/ai-polish` `{text}` → `{result:{corrected_text, notes_zh, error_count}}`

- [x] **Step 1: 写失败测试**

`test_server.py` 新增（放 fixtures 后）：
```python
def test_writing_analyze_endpoint(client):
    res = client.post("/api/writing/analyze", json={"text": "Ich sehe der Mann."})
    assert res.status_code == 200
    a = res.json()
    assert "sentences" in a and a["sentences"][0]["spans"]

def test_essays_crud_flow(client):
    r = client.post("/api/essays", json={"title": "Mein Essay",
                                         "content": "Ich fahre mit der Auto."})
    assert r.status_code == 200
    eid = r.json()["id"]
    assert r.json()["error_count"] >= 1
    assert client.get("/api/essays").json()
    g = client.get(f"/api/essays/{eid}").json()
    assert g["analysis_json"]
    u = client.put(f"/api/essays/{eid}", json={"content": "Ich fahre mit dem Auto."})
    assert u.json()["error_count"] == 0
    assert client.delete(f"/api/essays/{eid}").status_code == 200

def test_writing_card_sugar_endpoint(client):
    r = client.post("/api/essays", json={"title": "T", "content": "Ich sehe der Mann."})
    eid = r.json()["id"]
    a = r.json()["analysis_json"]
    sent, span = a["sentences"][0], a["sentences"][0]["spans"][0]
    # span 挂 essay 行里，先通过 analyze 的 shape 取 sentence_id/span_index
    res = client.post("/api/writing/cards", json={
        "essay_id": eid, "sentence_id": 0, "span_index": 0})
    assert res.status_code == 200
    card = client.get("/api/cards/grammar").json()
    assert card and card[0].get("corrected_form") == span["corrected_form"]
    assert card[0].get("error_type") == span["error_type"]

def test_ai_polish_no_key_stub(client, monkeypatch):
    monkeypatch.setattr("server.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/writing/ai-polish", json={"text": "Hallo."})
    assert res.status_code == 200
    assert res.json()["result"]["error_count"] == 0
```
> `test_writing_card_sugar_endpoint` 依赖 `/api/cards/grammar` 的 GET 列表端点存在（确认其路径；若无则改为直接查 `grammar_cards` 表断言）。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest test_server.py::test_writing_analyze_endpoint test_server.py::test_essays_crud_flow test_server.py::test_writing_card_sugar_endpoint test_server.py::test_ai_polish_no_key_stub -v`
Expected: FAIL（`/api/writing/analyze` 404）

- [x] **Step 3: 实现**

`server.py` 加 pydantic 模型（:659 附近）：
```python
class WritingAnalyzeReq(BaseModel):
    text: str

class EssayCreateReq(BaseModel):
    title: str
    content: str

class EssayUpdateReq(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None

class WritingCardReq(BaseModel):
    essay_id: int
    sentence_id: int
    span_index: int

class AIPolishReq(BaseModel):
    text: str
```
`GrammarCardReq` 加：
```python
    corrected_form: Optional[str] = ""
    error_type: Optional[str] = ""
```
`add_grammar_card` INSERT 加两列（值取 `req.corrected_form or ""` / `req.error_type or ""`）。

新端点（放在 `add_grammar_card` 附近；`_get_writer_nlp()` 复用 `server.nlp`，见 `_load_spacy_model`）：
```python
def _get_writer_nlp():
    try:
        return server_nlp()          # server.py 里已有的惰性加载 nlp
    except Exception:
        return None

@app.post("/api/writing/analyze")
async def api_writing_analyze(req: WritingAnalyzeReq):
    from writing_rules import analyze_essay_text
    return analyze_essay_text(req.text[:2000], _get_writer_nlp())

@app.post("/api/essays")
def create_essay(req: EssayCreateReq):
    from writing_rules import analyze_essay_text
    a = analyze_essay_text(req.content[:5000], _get_writer_nlp())
    cefr = a["cefr"].get("recommended_level")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO essays (title, content, analysis_json, cefr_level,"
            " error_count, sentence_count) VALUES (?,?,?,?,?,?)",
            (req.title, req.content, json.dumps(a, ensure_ascii=False), cefr,
             a["error_count"], len(a["sentences"])))
        eid = cur.lastrowid
    return {"id": eid, "title": req.title, "analysis_json": a,
            "error_count": a["error_count"]}

@app.get("/api/essays")
def list_essays():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, cefr_level, error_count, sentence_count,"
            " updated_at FROM essays ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/essays/{essay_id}")
def get_essay(essay_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id=?", (essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    return dict(row)

@app.put("/api/essays/{essay_id}")
def update_essay(essay_id: int, req: EssayUpdateReq):
    from writing_rules import analyze_essay_text
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id=?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        content = req.content if req.content is not None else row["content"]
        title = req.title if req.title is not None else row["title"]
        a = analyze_essay_text(content[:5000], _get_writer_nlp())
        conn.execute(
            "UPDATE essays SET title=?, content=?, analysis_json=?,"
            " cefr_level=?, error_count=?, sentence_count=?, updated_at=?"
            " WHERE id=?",
            (title, content, json.dumps(a, ensure_ascii=False),
             a["cefr"].get("recommended_level"), a["error_count"],
             len(a["sentences"]), datetime.utcnow().isoformat(), essay_id))
    return {"id": essay_id, "analysis_json": a, "error_count": a["error_count"]}

@app.delete("/api/essays/{essay_id}")
def delete_essay(essay_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM essays WHERE id=?", (essay_id,))
    return {"status": "ok"}

@app.post("/api/writing/cards")
def save_writing_card(req: WritingCardReq):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id=?", (req.essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    a = json.loads(row["analysis_json"])
    spans = a["sentences"][req.sentence_id]["spans"]
    if req.span_index >= len(spans):
        raise HTTPException(400, "span_index 越界")
    sp = spans[req.span_index]
    sentence_text = a["sentences"][req.sentence_id]["text"]
    card = GrammarCardReq(
        article_id=None,
        sentence_context=sentence_text,
        grammar_name=f"写作润色 · {sp['error_type']}",
        cefr_level=row["cefr_level"] or "B1",
        explanation_zh=sp["explanation_zh"],
        rule_formula=sp["corrected_form"],
        corrected_form=sp["corrected_form"],
        error_type=sp["error_type"],
    )
    return add_grammar_card(card)
```
> 注：`server.py` 已有 nlp 惰性加载（`server.nlp` 全局，Android 安全）。`_get_writer_nlp` 应直接返回它；测试里 `monkeypatch` 或依赖真实 spaCy。AI polish 端点加在 `/api/ai/note-assist`（:1640）附近，抄其 stub 模式，`text` cap 2000 字符。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest test_server.py -q`
Expected: 全绿（含 Task 1 的迁移测试）

- [x] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(writer): analyze/essays CRUD/cards/ai-polish 端点，存卡带 corrected_form 与 error_type"
```

---

## Task 4: 前端视图 `#view-writer` + 导航 + `writer.js`

**Files:**
- Modify: `static/index.html`、`static/js/main.js`、`static/style.css`
- Create: `static/js/writer.js`

**Interfaces:**
- Consumes: `POST /api/writing/analyze`、`/api/essays*`、`POST /api/writing/cards`、`POST /api/writing/ai-polish`（Task 3）；`api()` 包装（core.js:65）、`Companion`。
- Produces: 视图内联 `onclick` 可调的 `window.loadWriterEssays/analyzeWriterText/saveWriterErrorAsCard/aiPolishEssay/saveWriterEssay/openWriterEssay/deleteWriterEssay`。

- [x] **Step 1: HTML 视图 + 导航**

`static/index.html` 在 `#view-progress` 之后插入：
```html
<main id="view-writer" class="view" style="display:none">
  <div class="writer-layout">
    <div class="writer-left">
      <input id="writer-title" placeholder="作文标题" class="btn-input" />
      <textarea id="writer-text" rows="16"
        placeholder="粘贴德语作文……"></textarea>
      <button class="btn" onclick="analyzeWriterText()">开始分析</button>
      <button class="btn" id="writer-ai-btn" onclick="aiPolishEssay()">✨ AI 润色全文</button>
      <button class="btn" onclick="saveWriterEssay()">保存作文</button>
      <div id="writer-render" class="writer-render"></div>
      <div id="writer-essay-list" class="writer-essay-list"></div>
    </div>
    <aside id="writer-panel" class="writer-err-panel">
      <div id="writer-cefr" class="cefr-badge"></div>
      <div id="writer-err-detail"></div>
    </aside>
  </div>
</main>
```
桌面导航（index.html:27-50）在 progress 与 cards 之间加：
```html
<button id="nav-btn-writer" class="nav-tab" onclick="show('writer')">
  <span class="nav-tab-code">SCHREIBTISCH</span>
  <span class="nav-tab-label">写作润色</span>
</button>
```
移动 dock（index.html:911-928）加：
```html
<button class="mobile-nav-btn dock-item" id="mob-btn-writer" onclick="show('writer')">✍️写作</button>
```
`main.js` 的 `show()`（:85）路由加：
```js
if (view === 'writer') loadWriterEssays();
```

- [x] **Step 2: 写 `writer.js`（最小可用）**

```js
import { api } from './core.js';

export function loadWriterEssays() {
  api('/api/essays').then(rows => {
    const el = document.getElementById('writer-essay-list');
    el.innerHTML = rows.map(r =>
      `<div class="writer-essay-item">
         <button onclick="openWriterEssay(${r.id})">${esc(r.title)}</button>
         <span class="cefr-badge">${r.cefr_level||''}</span>
         <span>${r.error_count} 错</span>
         <button onclick="deleteWriterEssay(${r.id})">删</button>
       </div>`).join('') || '暂无作文';
  });
}
export function analyzeWriterText() {
  const text = document.getElementById('writer-text').value;
  api('/api/writing/analyze', { method: 'POST', body: { text } })
    .then(a => renderWriterReport(a));
}
function renderWriterReport(a) {
  document.getElementById('writer-cefr').textContent =
    `CEFR 估测: ${a.cefr.recommended_level||'—'} · ${a.error_count} 处错误`;
  document.getElementById('writer-render').innerHTML =
    a.sentences.map(s => buildHighlightedText(s.text, s.spans)).join('<br>');
}
function buildHighlightedText(text, spans) {
  const sorted = [...spans].sort((x, y) => x.start - y.start);
  let out = '', pos = 0;
  for (const sp of sorted) {
    out += esc(text.slice(pos, sp.start));
    out += `<mark class="writer-err-underline err-${sp.error_type}"
               onclick="selectWriterSpan(${sp.start},${sp.end})">`
           + esc(text.slice(sp.start, sp.end)) + '</mark>';
    pos = sp.end;
  }
  return out + esc(text.slice(pos));
}
export function selectWriterSpan(start, end) {
  const a = window.__lastAnalysis;
  for (const s of a.sentences) for (const sp of s.spans) {
    if (sp.start === start && sp.end === end) return showSpanDetail(s.text, sp);
  }
}
export function saveWriterErrorAsCard() {
  api('/api/writing/cards', { method: 'POST', body: {
    essay_id: window.__essayId || 0, sentence_id: window.__span.si,
    span_index: window.__span.idx } })
    .then(() => { refreshCardCounters(); Companion.celebrate('card_grammar'); });
}
function showSpanDetail(sentenceText, sp) {
  document.getElementById('writer-err-detail').innerHTML =
    `<div class="err-${sp.error_type}">【${sp.error_type}】${esc(sp.explanation_zh)}</div>
     <div class="correction-chip">正: ${esc(sp.corrected_form)}</div>
     <div class="writer-sent">${esc(sentenceText)}</div>
     <button class="btn" onclick="saveWriterErrorAsCard()">＋ 存为 Anki 语法卡</button>`;
}
export function aiPolishEssay() {
  const text = document.getElementById('writer-text').value;
  api('/api/writing/ai-polish', { method: 'POST', body: { text } })
    .then(r => {
      document.getElementById('writer-text').value = r.result.corrected_text || text;
      document.getElementById('writer-err-detail').insertAdjacentHTML('beforeend',
        r.result.notes_zh.map(n => `<div>· ${esc(n)}</div>`).join(''));
    });
}
export function saveWriterEssay() { /* POST/PUT /api/essays，存完刷新列表 */ }
export function openWriterEssay(id) { /* GET /api/essays/{id} 填入编辑器 + 渲染报告 */ }
export function deleteWriterEssay(id) { /* DELETE + 刷新 */ }
```
`main.js` 的 window 导出块（:563-659）加：
```js
Object.assign(window, { loadWriterEssays, analyzeWriterText, selectWriterSpan,
  saveWriterErrorAsCard, aiPolishEssay, saveWriterEssay, openWriterEssay,
  deleteWriterEssay });
```
`writer.js` 里记录 `window.__essayId/__span/__lastAnalysis` 供存卡与选择回调。

- [x] **Step 3: CSS**

`static/style.css` 加：
```css
.writer-layout { display: flex; gap: 1.5rem; max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
.writer-left { flex: 1 1 60%; }
.writer-err-panel { flex: 1 1 35%; background: var(--paper); border-radius: 8px; padding: 1rem; position: sticky; top: 1rem; }
.writer-render { margin-top: 1rem; font-size: 1.05rem; line-height: 1.9; white-space: pre-wrap; }
.writer-err-underline { text-decoration: wavy underline; cursor: pointer; padding: 0 2px; border-radius: 3px; }
.err-artikel { background: rgba(230, 57, 70, .12); text-decoration-color: var(--cherry); }
.err-kasus   { background: rgba(243, 146, 0, .12); text-decoration-color: #f39200; }
.err-praeposition { background: rgba(76, 145, 149, .12); text-decoration-color: #4c9195; }
.correction-chip { background: var(--accent); color: #fff; padding: 2px 8px; border-radius: 4px; display: inline-block; margin: .25rem 0; }
.writer-essay-item { display: flex; gap: .5rem; align-items: center; padding: .25rem 0; }
@media (max-width: 768px) { .writer-layout { flex-direction: column; } }
```

- [x] **Step 4: 版本 bump 到 3.11.0**

- `static/index.html:13` 与 `:972`：`?v=3.10.0` → `?v=3.11.0`
- `static/index.html:22` 顶栏 `"v3.8.0 Online"` → `"v3.11.0 Online"`
- `static/sw.js:1` `CACHE_NAME = 'delector-static-v3.11.0'`；`STATIC_ASSETS` 内 `/style.css?v=3.11.0`、`/js/main.js?v=3.11.0`、新增 `'/js/writer.js?v=3.11.0'`（顺带修正 sw.js 原钉 3.8.0 的漂移）
- `android/app/build.gradle`：`versionCode 31100`、`versionName "3.11.0"`

- [x] **Step 5: 手动验证 + Commit**

本地 `python start.py` → `http://localhost:8000` → 进「写作润色」→ 粘 `Ich fahre mit der Auto.` → "der Auto" 下划线标黄 → 点击 → 侧栏 `正: dem Auto` + 讲解 → 存卡 → 卡盒可见。粘无错德文 → 零下划线。
```bash
git add static/ android/app/build.gradle
git commit -m "feat(writer): 写作润色视图——行内下划线 + 侧栏 + 存卡 + AI 润色，bump v3.11.0"
```

---

## Self-Review（对照 spec 自检）

**决策覆盖：**
- #1 混合引擎 ✓（Task 2 本地规则 + Task 3 ai-polish 按钮）
- #2 两条检测 ✓（Task 2 规则 A/B）
- #3 行内下划线 + 侧栏 + CEFR + 存卡 ✓（Task 4）
- #4 grammar_cards 两列 ✓（Task 1）
- #5 essays 草稿库 ✓（Task 1+3）
- #6 安卓 ✓（`_get_writer_nlp` 复用 Android 安全 nlp；`nlp=None` 降级）
- #7 span 数据模型 ✓（`{text, spans}`，不存 tokens dump）
- #8 AI 不缓存 ✓（ai-polish 无缓存，未建 ai_cache 表）
- #9 封闭分类 ✓（artikel/kasus/praeposition/andere）
- #10 FP 守卫 ✓（Task 2 双侧 morph + corrected_form 可算 + 双格介词跳过 + nlp=None 零错误）
- #11 v3.11.0 ✓（Task 4 Step 4）
- #12 IDE 愿景 ✓（span 数据 + 行内下划线即 IDE 雏形）

**占位符扫描：** Task 4 的 `saveWriterEssay/openWriterEssay/deleteWriterEssay` 是省略号占位 —— 需在实现时按 Task 3 端点补全（POST/PUT/GET/DELETE `/api/essays`），列入实现注意。`_cefr_basic` 是 MVP 简化（固定 A1），接入真实 `calculate_cefr_stats` 在 Task 3 标注为可选增强。

**类型一致性：** `analyze_essay_text` 返回 shape（Task 2）与前端消费（Task 4 `renderWriterReport`/`buildHighlightedText`）一致：`sentences[].text` + `spans[].{start,end,error_type,corrected_form,explanation_zh}`。`WritingCardReq{essay_id,sentence_id,span_index}`（Task 3）与前端存卡调用一致。

---

## 竞品定位（销售话术，不影响代码）

**核心差异化（无人占领）：错误→复习卡闭环。** 商业App（Babbel/Busuu/Duolingo/Langua）全把纠错与记忆拆开——错就地改，复习只吃课内词表；OSS（Lute 无写作、freelingo 结构最近但阶段独立无闭环）。LanguageTool/DeepL Write 检查强但零教学、云端。我们的空白：**每条纠正过的错误结构化链进 FSRS 复习队列 + Anki 导出** + 完全本地离线。

**卖点措辞（Task 4 完成后的 README/FEATURES 文案遵循）：**
- 不写"最强德语检查器"（LanguageTool 广度远胜，别硬碰）
- 写「你的错误变成你的复习卡」——错误→FSRS/Anki 闭环
- 强化本地离线 + 隐私（默认本地规则不传文本；AI 润色是显式按钮）
- 诚实标注 CEFR 为「词汇频率估测」、AI 润色走 DeepSeek（作文文本发国内，显式按钮权衡）

## 验证方式（端到端）

1. `pytest -q` 全绿（114 现有 + 新增：test_writing_rules ~7 + test_server ~4 = 预计 ~125）。
2. 手动：`python start.py` → 写作润色 → 粘 `Ich fahre mit der Auto.` → 下划线 + `正: dem Auto` → 存卡 → 卡盒 `corrected_form/error_type` 已填 → `✨ AI 润色全文` → 全文替换 + 中文备注（无 key 时显示提示 stub）。
3. **反向抽查**：粘无错德文 → 零下划线。
4. 作文保存/列表/回访/删除；改动内容 → 重分析（error_count 更新）。
5. Android：CI 打 APK（v3.11.0 tag 或 workflow_dispatch）真机装 → 写作视图能诊断（spaCy sm 不崩；无 spaCy 时 `nlp=None` 零错误不崩）。验签闸沿用 v3.10.0 已验证的 keytool v1 流程。
