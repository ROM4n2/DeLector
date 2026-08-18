# DeLector (Ponytail Edition) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Build DeLector in 2 core files (`server.py` + `static/index.html`): Tablet-first German reader with spaCy CEFR highlights, on-demand DeepSeek Goethe grammar analysis, and 1-click Anki `.apkg` export.

**Architecture:** Single FastAPI backend (`server.py`) with stdlib `sqlite3` + spaCy + DeepSeek API + `genanki`, serving a single static frontend SPA (`static/index.html`) using Tailwind CDN and native browser JS. Zero Node.js build steps, zero CORS, single command startup.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, spaCy (`de_core_news_sm`), httpx, genanki, SQLite (`sqlite3`), HTML5/JS/Tailwind CDN.

## Global Constraints
- No Node.js / npm build step. Everything served directly by FastAPI.
- Never commit API keys. Load `DEEPSEEK_API_KEY` from `.env`.
- Tablet touch targets ≥ 44px, sliding right drawer on tap.
- 2 Anki Note models in exported `.apkg`: Vocab Note & Goethe Grammar Note.

---

### Task 1: Environment & Server Core (`server.py` + `test_server.py`)

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `server.py`
- Test: `test_server.py`

**Interfaces:**
- `GET /` -> Serves `static/index.html`
- `POST /api/articles/ingest` -> `{title, raw_text, url}` -> `{id, title}`
- `GET /api/articles` -> List articles
- `GET /api/articles/{id}` -> Processed tokens with CEFR
- `POST /api/lookup/grammar` -> DeepSeek Goethe breakdown
- `POST /api/cards/vocab` & `POST /api/cards/grammar` -> Save cards
- `GET /api/cards` & `GET /api/cards/export/apkg` -> Download `.apkg`

- [ ] **Step 1: Write `.gitignore` and `requirements.txt`**

`.gitignore`:
```gitignore
__pycache__/
*.pyc
.env
*.db
*.apkg
.pytest_cache/
```

`requirements.txt`:
```text
fastapi>=0.110.0
uvicorn>=0.28.0
spacy>=3.7.4
httpx>=0.27.0
genanki>=0.13.1
pytest>=8.0.0
```

- [ ] **Step 2: Write failing test in `test_server.py`**

```python
import os
import pytest
from fastapi.testclient import TestClient

# Ensure test DB
os.environ["DATABASE_PATH"] = "test_delector.db"
from server import app, init_db, get_cefr_level, export_anki_deck

@pytest.fixture(autouse=True)
def clean_db():
    if os.path.exists("test_delector.db"):
        os.remove("test_delector.db")
    init_db("test_delector.db")
    yield
    if os.path.exists("test_delector.db"):
        os.remove("test_delector.db")

def test_cefr_lookup():
    assert get_cefr_level("gehen") == "A1"
    assert get_cefr_level("beeinträchtigen") in ("B2", "C1")

def test_full_api_flow():
    client = TestClient(app)
    
    # 1. Ingest text
    text = "Nachdem er die Prüfung bestanden hatte, fuhr er nach Berlin."
    res = client.post("/api/articles/ingest", json={"title": "Test Goethe", "raw_text": text})
    assert res.status_code == 200
    art_id = res.json()["article_id"]

    # 2. Get article with tokens
    res = client.get(f"/api/articles/{art_id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["sentences"]) > 0
    words = [t["text"] for t in data["sentences"][0]["tokens"]]
    assert "Prüfung" in words

    # 3. Add vocab card
    v_res = client.post("/api/cards/vocab", json={
        "article_id": art_id,
        "word": "Prüfung",
        "lemma": "Prüfung",
        "pos": "NOUN",
        "gender": "Fem",
        "cefr_level": "A2",
        "definition_zh": "考试",
        "sentence_context": text
    })
    assert v_res.status_code == 200

    # 4. Add grammar card
    g_res = client.post("/api/cards/grammar", json={
        "article_id": art_id,
        "sentence_context": text,
        "grammar_name": "Plusquamperfekt mit nachdem",
        "cefr_level": "B1",
        "explanation_zh": "过去完成时表示过去发生之前的动作",
        "rule_formula": "nachdem + Partizip II + hatte/war"
    })
    assert g_res.status_code == 200

    # 5. Export APKG
    apkg_res = client.get("/api/cards/export/apkg")
    assert apkg_res.status_code == 200
    assert len(apkg_res.content) > 1000
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest test_server.py -v`
Expected: FAIL

- [ ] **Step 4: Implement minimal single-file `server.py`**

```python
import os
import json
import sqlite3
import random
import tempfile
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
import spacy
import genanki

DB_PATH = os.environ.get("DATABASE_PATH", "delector.db")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# --- 1. Database Layer (stdlib sqlite3) ---
def get_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DB_PATH):
    with get_db(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_url TEXT,
                raw_text TEXT NOT NULL,
                processed_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vocab_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                word TEXT NOT NULL,
                lemma TEXT NOT NULL,
                pos TEXT,
                gender TEXT,
                plural TEXT,
                cefr_level TEXT,
                definition_zh TEXT NOT NULL,
                sentence_context TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS grammar_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                sentence_context TEXT NOT NULL,
                grammar_name TEXT NOT NULL,
                cefr_level TEXT NOT NULL,
                explanation_zh TEXT NOT NULL,
                rule_formula TEXT,
                examples_zh TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

# --- 2. NLP & CEFR Tagging ---
try:
    nlp = spacy.load("de_core_news_sm")
except OSError:
    from spacy.cli import download
    download("de_core_news_sm")
    nlp = spacy.load("de_core_news_sm")

CEFR_DICT = {
    "ich": "A1", "du": "A1", "er": "A1", "sie": "A1", "es": "A1", "wir": "A1", "sein": "A1", "haben": "A1",
    "können": "A1", "müssen": "A1", "lernen": "A1", "arbeiten": "A1", "gut": "A1", "tag": "A1",
    "erzählen": "A2", "erklären": "A2", "bestehen": "A2", "prüfung": "A2", "beruf": "A2", "reise": "A2",
    "entscheiden": "B1", "entwickeln": "B1", "zusammenhang": "B1", "gesellschaft": "B1", "meinung": "B1",
    "beeinträchtigen": "B2", "gewährleisten": "B2", "hervorheben": "B2", "voraussetzen": "B2",
    "implizieren": "C1", "fungieren": "C1", "paradigma": "C1", "unabdingbar": "C1"
}

def get_cefr_level(lemma: str) -> str:
    low = lemma.lower()
    if low in CEFR_DICT:
        return CEFR_DICT[low]
    if any(low.endswith(s) for s in ["ität", "ismus", "schaft", "ung"]):
        return "B2" if len(low) > 10 else "B1"
    if len(low) > 11: return "B2"
    if len(low) > 7: return "B1"
    if len(low) > 4: return "A2"
    return "A1"

def process_german_text(text: str) -> Dict[str, Any]:
    doc = nlp(text)
    sentences = []
    for sent_idx, sent in enumerate(doc.sents):
        tokens = []
        for t in sent:
            morph = t.morph.to_dict()
            is_word = not t.is_punct and not t.is_space
            tokens.append({
                "id": t.i,
                "text": t.text,
                "lemma": t.lemma_,
                "pos": t.pos_,
                "gender": morph.get("Gender", ""),
                "case": morph.get("Case", ""),
                "cefr_level": get_cefr_level(t.lemma_) if is_word else "",
                "is_punct": t.is_punct,
                "is_space": t.is_space
            })
        sentences.append({"id": sent_idx, "text": sent.text, "tokens": tokens})
    return {"sentence_count": len(sentences), "sentences": sentences}

# --- 3. Anki Exporter ---
VOCAB_MODEL = genanki.Model(
    1607392319, 'DeLector Vocab',
    fields=[{'name': 'Front'}, {'name': 'Word'}, {'name': 'Lemma'}, {'name': 'Meta'}, {'name': 'Definition'}],
    templates=[{
        'name': 'Card',
        'qfmt': '<div style="font-family:sans-serif;font-size:20px;padding:20px;">{{Front}}</div>',
        'afmt': '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;color:#1e293b;"><b>{{Definition}}</b><br><span style="color:#64748b;font-size:14px;">{{Lemma}} ({{Meta}})</span></div>'
    }]
)

GRAMMAR_MODEL = genanki.Model(
    1607392320, 'DeLector Goethe Grammar',
    fields=[{'name': 'Sentence'}, {'name': 'GrammarName'}, {'name': 'CEFR'}, {'name': 'Explanation'}, {'name': 'Formula'}],
    templates=[{
        'name': 'Card',
        'qfmt': '<div style="font-family:sans-serif;font-size:20px;padding:20px;"><span style="background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:99px;font-size:12px;">Goethe {{CEFR}}</span><br><br>{{Sentence}}</div>',
        'afmt': '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;"><b>{{GrammarName}}</b><br><code style="background:#f1f5f9;color:#0369a1;padding:4px 8px;">{{Formula}}</code><p style="color:#334155;">{{Explanation}}</p></div>'
    }]
)

def export_anki_deck(output_path: str, db_path: str = DB_PATH) -> str:
    with get_db(db_path) as conn:
        vocab_rows = conn.execute("SELECT * FROM vocab_cards").fetchall()
        grammar_rows = conn.execute("SELECT * FROM grammar_cards").fetchall()

    deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), "DeLector::Goethe Deck")
    for r in vocab_rows:
        styled_front = r["sentence_context"].replace(r["word"], f'<b style="color:#2563eb;">{r["word"]}</b>')
        meta = f'{r["pos"]} · {r["gender"] or ""} · {r["cefr_level"]}'
        deck.add_note(genanki.Note(model=VOCAB_MODEL, fields=[styled_front, r["word"], r["lemma"], meta, r["definition_zh"]]))

    for r in grammar_rows:
        deck.add_note(genanki.Note(model=GRAMMAR_MODEL, fields=[r["sentence_context"], r["grammar_name"], r["cefr_level"], r["explanation_zh"], r["rule_formula"] or ""]))

    genanki.Package(deck).write_to_file(output_path)
    return output_path

# --- 4. FastAPI Application ---
app = FastAPI(title="DeLector")
init_db()

class IngestReq(BaseModel):
    title: Optional[str] = "Untitled"
    raw_text: str

class VocabCardReq(BaseModel):
    article_id: Optional[int] = None
    word: str
    lemma: str
    pos: Optional[str] = ""
    gender: Optional[str] = ""
    cefr_level: Optional[str] = "A1"
    definition_zh: str
    sentence_context: str

class GrammarCardReq(BaseModel):
    article_id: Optional[int] = None
    sentence_context: str
    grammar_name: str
    cefr_level: str
    explanation_zh: str
    rule_formula: Optional[str] = ""

class GrammarLookupReq(BaseModel):
    sentence: str
    target_phrase: str

@app.post("/api/articles/ingest")
def ingest(req: IngestReq):
    processed = process_german_text(req.raw_text)
    with get_db() as conn:
        cur = conn.execute("INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
                           (req.title, req.raw_text, json.dumps(processed, ensure_ascii=False)))
        art_id = cur.lastrowid
    return {"article_id": art_id, "title": req.title}

@app.get("/api/articles")
def list_articles():
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, created_at, length(raw_text) as char_count FROM articles ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row: raise HTTPException(404, "Article not found")
        data = dict(row)
        data.update(json.loads(data["processed_json"]))
        return data

@app.post("/api/lookup/grammar")
async def lookup_grammar(req: GrammarLookupReq):
    key = os.environ.get("DEEPSEEK_API_KEY", DEEPSEEK_KEY)
    if not key:
        return {
            "grammar_name": f"语法考点辨析 ({req.target_phrase})",
            "cefr_level": "B1",
            "explanation_zh": "请在 .env 中配置 DEEPSEEK_API_KEY 获取实时歌德大纲 AI 分析。",
            "rule_formula": "Grammar Pattern",
            "collocations": [f"{req.target_phrase} (常用释义)"]
        }

    prompt = f"句子: \"{req.sentence}\"\n目标词/短语: \"{req.target_phrase}\"\n请按照歌德欧标考试(Profile deutsch)解析语法考点。返回 JSON: {{\"grammar_name\": \"...\", \"cefr_level\": \"B1\", \"explanation_zh\": \"...\", \"rule_formula\": \"...\", \"collocations\": [\"...\"]}}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }
        )
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

@app.post("/api/cards/vocab")
def add_vocab_card(req: VocabCardReq):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO vocab_cards (article_id, word, lemma, pos, gender, cefr_level, definition_zh, sentence_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.article_id, req.word, req.lemma, req.pos, req.gender, req.cefr_level, req.definition_zh, req.sentence_context)
        )
    return {"status": "ok"}

@app.post("/api/cards/grammar")
def add_grammar_card(req: GrammarCardReq):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO grammar_cards (article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula) VALUES (?, ?, ?, ?, ?, ?)",
            (req.article_id, req.sentence_context, req.grammar_name, req.cefr_level, req.explanation_zh, req.rule_formula)
        )
    return {"status": "ok"}

@app.get("/api/cards")
def get_cards():
    with get_db() as conn:
        v = [dict(r) for r in conn.execute("SELECT * FROM vocab_cards ORDER BY id DESC").fetchall()]
        g = [dict(r) for r in conn.execute("SELECT * FROM grammar_cards ORDER BY id DESC").fetchall()]
        return {"vocab_cards": v, "grammar_cards": g}

@app.get("/api/cards/export/apkg")
def export_apkg():
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "DeLector_Deck.apkg")
    export_anki_deck(path)
    return FileResponse(path, filename="DeLector_Deck.apkg", media_type="application/octet-stream")

# Mount Static UI
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

- [ ] **Step 5: Run tests and verify PASS**

Run: `pytest test_server.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt server.py test_server.py
git commit -m "feat: complete minimal single-file backend server with nlp, db and anki export"
```

---

### Task 2: Single-File Tablet UI (`static/index.html`)

**Files:**
- Create: `static/index.html`

**Interfaces:**
- Article Dashboard (Import modal, article list)
- Immersive Reader (CEFR colored spans with touch/click handlers)
- Sliding Drawer (Morphology, on-demand DeepSeek Goethe analysis, 1-tap Vocab/Grammar card creation)
- Card Manager & 1-click `.apkg` Download

- [ ] **Step 1: Write `static/index.html` (Responsive, Tablet-first SPA)**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>DeLector - 德语欧标沉浸阅读与考点分析</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #fcfbf9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .de-token { display: inline; padding: 2px 3px; border-radius: 4px; cursor: pointer; transition: all 0.15s; }
    .de-token:hover { background-color: #e7e5e4; }
    .de-token.selected { background-color: #3b82f6 !important; color: white !important; }
    .cefr-A2 { color: #0d9488; background: #f0fdfa; border-bottom: 1.5px solid #99f6e4; }
    .cefr-B1 { color: #d97706; background: #fffbeb; border-bottom: 1.5px solid #fde68a; }
    .cefr-B2 { color: #e11d48; background: #fff1f2; border-bottom: 1.5px solid #fecdd3; }
    .cefr-C1 { color: #7c3aed; background: #faf5ff; border-bottom: 1.5px solid #e9d5ff; }
  </style>
</head>
<body class="text-stone-900 min-h-screen flex flex-col">

  <!-- Header Nav -->
  <header class="sticky top-0 z-30 flex items-center justify-between border-b border-stone-200 bg-stone-50/90 px-6 py-3.5 backdrop-blur-md">
    <div class="flex items-center gap-3 cursor-pointer" onclick="showView('home')">
      <span class="text-2xl">📖</span>
      <span class="font-serif text-xl font-bold text-stone-900">DeLector</span>
    </div>
    <div class="flex items-center gap-3">
      <button onclick="showView('cards')" class="rounded-lg border border-stone-300 bg-white px-3.5 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50">
        🗂️ 卡片库 (<span id="card-count">0</span>)
      </button>
      <a href="/api/cards/export/apkg" class="rounded-lg bg-amber-700 px-3.5 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-amber-800">
        ⬇️ 导出 Anki
      </a>
    </div>
  </header>

  <!-- View 1: Home Dashboard -->
  <main id="view-home" class="max-w-4xl mx-auto px-6 py-10 flex-1 w-full">
    <div class="mb-8 flex flex-col md:flex-row md:items-center justify-between gap-6 rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50 p-8 shadow-sm">
      <div>
        <span class="text-xs font-bold uppercase tracking-wider text-amber-800">歌德证书备考工作台</span>
        <h2 class="mt-1 font-serif text-3xl font-bold">德语欧标沉浸阅读与考点生成</h2>
        <p class="mt-2 text-sm text-stone-600">导入任意德语课文/新闻，实时标注 CEFR 等级，一键生成 Anki 考点卡片。</p>
      </div>
      <button onclick="openImportModal()" class="rounded-xl bg-amber-700 px-6 py-3.5 text-sm font-semibold text-white shadow hover:bg-amber-800 whitespace-nowrap">
        + 导入德语文章
      </button>
    </div>

    <h3 class="font-serif text-xl font-bold mb-4">文稿库</h3>
    <div id="article-list" class="space-y-3"></div>
  </main>

  <!-- View 2: Reader Workspace -->
  <main id="view-reader" class="max-w-3xl mx-auto px-6 py-10 flex-1 w-full hidden">
    <div class="mb-6 flex items-center justify-between border-b pb-4">
      <button onclick="showView('home')" class="text-sm font-medium text-stone-600 hover:text-stone-900">← 返回文稿列表</button>
      <h2 id="reader-title" class="font-serif text-xl font-bold truncate max-w-md"></h2>
    </div>
    <div id="reader-content" class="text-xl leading-relaxed space-y-4"></div>
  </main>

  <!-- View 3: Cards List -->
  <main id="view-cards" class="max-w-4xl mx-auto px-6 py-10 flex-1 w-full hidden">
    <div class="mb-6 flex items-center justify-between border-b pb-4">
      <button onclick="showView('home')" class="text-sm font-medium text-stone-600 hover:text-stone-900">← 返回文稿列表</button>
      <h2 class="font-serif text-2xl font-bold">待复习卡片库</h2>
    </div>
    <div id="cards-container" class="space-y-4"></div>
  </main>

  <!-- Sliding Right Drawer -->
  <aside id="drawer" class="fixed inset-y-0 right-0 z-40 w-full max-w-md bg-white border-l border-stone-200 shadow-2xl p-6 flex flex-col transform translate-x-full transition-transform duration-300">
    <div class="flex items-center justify-between border-b pb-4">
      <h3 class="font-serif text-lg font-bold">考点与词汇工作台</h3>
      <button onclick="closeDrawer()" class="text-stone-400 hover:text-stone-700 text-xl font-bold">✕</button>
    </div>

    <div class="flex-1 overflow-y-auto py-4 space-y-6">
      <!-- Fast Info -->
      <div class="rounded-xl border border-stone-200 bg-stone-50 p-4">
        <div class="flex justify-between items-baseline">
          <span id="d-word" class="text-2xl font-bold text-stone-900"></span>
          <span id="d-cefr" class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800"></span>
        </div>
        <div id="d-meta" class="mt-2 text-xs text-stone-600"></div>
        <div class="mt-3">
          <input id="d-def" type="text" placeholder="输入中文释义..." class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm">
        </div>
        <button onclick="saveVocab()" id="btn-save-vocab" class="mt-3 w-full rounded-lg bg-stone-900 py-2 text-sm font-medium text-white hover:bg-stone-800">
          + 加入 Anki 词汇卡
        </button>
      </div>

      <!-- DeepSeek Goethe Grammar Layer -->
      <div class="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4 space-y-3">
        <div class="flex items-center justify-between">
          <span class="font-serif font-bold text-stone-900">歌德考点深度解析</span>
          <button onclick="analyzeGrammar()" id="btn-analyze" class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700">
            AI 深度剖析
          </button>
        </div>
        <div id="grammar-res" class="hidden space-y-2 text-sm">
          <div class="font-bold text-indigo-950" id="g-name"></div>
          <div class="font-mono text-xs bg-white p-2 rounded border border-indigo-100" id="g-formula"></div>
          <p class="text-stone-700" id="g-exp"></p>
          <button onclick="saveGrammar()" id="btn-save-grammar" class="w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700">
            + 加入 Anki 语法卡
          </button>
        </div>
      </div>

      <!-- Context -->
      <div class="rounded-xl border border-stone-200 p-4 text-xs text-stone-600">
        <span class="font-bold">原句上下文：</span>
        <p id="d-sent" class="mt-1 italic"></p>
      </div>
    </div>
  </aside>

  <!-- Import Modal -->
  <div id="import-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4 backdrop-blur-sm hidden">
    <div class="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
      <h3 class="font-serif text-lg font-bold mb-4">导入德语材料</h3>
      <input id="imp-title" type="text" placeholder="标题 (可选)" class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm mb-3">
      <textarea id="imp-text" rows="6" placeholder="粘贴德语课文/新闻..." class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm mb-4"></textarea>
      <div class="flex justify-end gap-2">
        <button onclick="closeImportModal()" class="rounded-lg border px-4 py-2 text-sm">取消</button>
        <button onclick="submitImport()" class="rounded-lg bg-amber-700 px-5 py-2 text-sm font-medium text-white hover:bg-amber-800">开始阅读</button>
      </div>
    </div>
  </div>

  <script>
    let currentArticle = null;
    let selectedToken = null;
    let selectedSentence = null;
    let grammarData = null;

    async function loadArticles() {
      const res = await fetch('/api/articles');
      const data = await res.json();
      const el = document.getElementById('article-list');
      if (data.length === 0) {
        el.innerHTML = '<div class="p-8 text-center text-stone-400 border rounded-xl">暂无文稿，点击上方按钮导入</div>';
        return;
      }
      el.innerHTML = data.map(a => `
        <div onclick="openReader(${a.id})" class="cursor-pointer flex justify-between items-center rounded-xl border border-stone-200 bg-white p-5 shadow-sm hover:border-amber-600 transition">
          <div>
            <h4 class="font-serif text-lg font-bold text-stone-900">${a.title}</h4>
            <div class="text-xs text-stone-400 mt-1">${a.created_at} · ${a.char_count} 字符</div>
          </div>
          <span class="text-stone-400">→</span>
        </div>
      `).join('');
    }

    async function openReader(id) {
      const res = await fetch(`/api/articles/${id}`);
      currentArticle = await res.json();
      document.getElementById('reader-title').textContent = currentArticle.title;
      
      const content = document.getElementById('reader-content');
      content.innerHTML = currentArticle.sentences.map(sent => `
        <p class="mb-4">
          ${sent.tokens.map(t => {
            if (t.is_space) return ' ';
            if (t.is_punct) return `<span>${t.text}</span>`;
            const cefrClass = t.cefr_level ? `cefr-${t.cefr_level}` : '';
            return `<span class="de-token ${cefrClass}" onclick="inspectToken(${t.id}, ${sent.id})">${t.text}</span>`;
          }).join('')}
        </p>
      `).join('');
      showView('reader');
    }

    function inspectToken(tokenId, sentId) {
      const sent = currentArticle.sentences.find(s => s.id === sentId);
      const token = sent.tokens.find(t => t.id === tokenId);
      selectedToken = token;
      selectedSentence = sent;
      grammarData = null;

      document.getElementById('d-word').textContent = token.text;
      document.getElementById('d-cefr').textContent = token.cefr_level || 'A1';
      document.getElementById('d-meta').textContent = `原型: ${token.lemma} · 词性: ${token.pos} ${token.gender ? '· ' + token.gender : ''}`;
      document.getElementById('d-def').value = '';
      document.getElementById('d-sent').textContent = sent.text;
      document.getElementById('grammar-res').classList.add('hidden');
      document.getElementById('btn-save-vocab').textContent = '+ 加入 Anki 词汇卡';
      document.getElementById('drawer').classList.remove('translate-x-full');
    }

    async function analyzeGrammar() {
      const btn = document.getElementById('btn-analyze');
      btn.textContent = '分析中...';
      try {
        const res = await fetch('/api/lookup/grammar', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({sentence: selectedSentence.text, target_phrase: selectedToken.text})
        });
        grammarData = await res.json();
        document.getElementById('g-name').textContent = grammarData.grammar_name;
        document.getElementById('g-formula').textContent = grammarData.rule_formula || '';
        document.getElementById('g-exp').textContent = grammarData.explanation_zh;
        if (!document.getElementById('d-def').value && grammarData.collocations?.length) {
          document.getElementById('d-def').value = grammarData.collocations[0];
        }
        document.getElementById('grammar-res').classList.remove('hidden');
      } finally {
        btn.textContent = 'AI 深度剖析';
      }
    }

    async function saveVocab() {
      const def = document.getElementById('d-def').value.trim();
      if (!def) return alert('请输入中文释义');
      await fetch('/api/cards/vocab', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          article_id: currentArticle.id,
          word: selectedToken.text,
          lemma: selectedToken.lemma,
          pos: selectedToken.pos,
          gender: selectedToken.gender,
          cefr_level: selectedToken.cefr_level || 'A1',
          definition_zh: def,
          sentence_context: selectedSentence.text
        })
      });
      document.getElementById('btn-save-vocab').textContent = '✓ 已保存';
      updateCardCount();
    }

    async function saveGrammar() {
      if (!grammarData) return;
      await fetch('/api/cards/grammar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          article_id: currentArticle.id,
          sentence_context: selectedSentence.text,
          grammar_name: grammarData.grammar_name,
          cefr_level: grammarData.cefr_level || 'B1',
          explanation_zh: grammarData.explanation_zh,
          rule_formula: grammarData.rule_formula
        })
      });
      document.getElementById('btn-save-grammar').textContent = '✓ 已加入语法卡';
      updateCardCount();
    }

    async function updateCardCount() {
      const res = await fetch('/api/cards');
      const data = await res.json();
      document.getElementById('card-count').textContent = data.vocab_cards.length + data.grammar_cards.length;
    }

    async function showView(view) {
      ['home', 'reader', 'cards'].forEach(v => document.getElementById(`view-${v}`).classList.add('hidden'));
      document.getElementById(`view-${view}`).classList.remove('hidden');
      closeDrawer();
      if (view === 'cards') loadCardsView();
      if (view === 'home') loadArticles();
    }

    async function loadCardsView() {
      const res = await fetch('/api/cards');
      const data = await res.json();
      const el = document.getElementById('cards-container');
      el.innerHTML = `
        <h3 class="font-bold text-lg text-stone-800">词汇卡 (${data.vocab_cards.length})</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
          ${data.vocab_cards.map(c => `
            <div class="p-4 bg-white border rounded-xl">
              <div class="flex justify-between font-bold"><span>${c.word}</span><span class="text-amber-700">${c.cefr_level}</span></div>
              <div class="text-stone-700 mt-1">${c.definition_zh}</div>
              <div class="text-xs text-stone-400 mt-1">${c.lemma} (${c.pos})</div>
            </div>
          `).join('')}
        </div>
        <h3 class="font-bold text-lg text-stone-800">歌德语法卡 (${data.grammar_cards.length})</h3>
        <div class="space-y-3">
          ${data.grammar_cards.map(c => `
            <div class="p-4 bg-white border border-indigo-100 rounded-xl space-y-1">
              <div class="flex justify-between font-bold text-indigo-950"><span>${c.grammar_name}</span><span>Goethe ${c.cefr_level}</span></div>
              <div class="text-sm text-stone-700">${c.explanation_zh}</div>
              <div class="text-xs italic text-stone-500">${c.sentence_context}</div>
            </div>
          `).join('')}
        </div>
      `;
    }

    function openImportModal() { document.getElementById('import-modal').classList.remove('hidden'); }
    function closeImportModal() { document.getElementById('import-modal').classList.add('hidden'); }
    function closeDrawer() { document.getElementById('drawer').classList.add('translate-x-full'); }

    async function submitImport() {
      const text = document.getElementById('imp-text').value.trim();
      const title = document.getElementById('imp-title').value.trim() || 'Untitled';
      if (!text) return alert('请输入文本');
      const res = await fetch('/api/articles/ingest', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, raw_text: text})
      });
      const data = await res.json();
      closeImportModal();
      openReader(data.article_id);
    }

    loadArticles();
    updateCardCount();
  </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add static/index.html
git commit -m "feat(ui): implement single-file responsive tablet reader with CEFR highlights and drawer"
```

---

### Task 3: Verification & Launch

- [ ] **Step 1: Run pytest suite**

Run: `pytest test_server.py -v`
Expected: PASS

- [ ] **Step 2: Start server**

Run: `uvicorn server:app --host 0.0.0.0 --port 8000`
Visit `http://localhost:8000` on Tablet / Browser.
