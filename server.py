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

def get_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("DATABASE_PATH", "delector.db")

# --- 1. Database Layer (stdlib sqlite3) ---
def get_db(db_path: Optional[str] = None):
    conn = sqlite3.connect(get_db_path(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Optional[str] = None):
    target_path = get_db_path(db_path)
    with get_db(target_path) as conn:
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
    seed_preset_articles(target_path)

PRESET_ARTICLES = [
    {
        "title": "【A1 入门篇】Hallo Berlin! Mein erster Tag in Deutschland",
        "text": "Guten Tag! Ich heiße Lukas und ich komme aus China. Jetzt wohne ich in Berlin und lerne Deutsch an einer Sprachschule. Jeden Morgen trinke ich einen Kaffee, esse ein Brötchen und fahre mit der U-Bahn zum Deutschkurs. Der Unterricht macht viel Spaß. Am Nachmittag gehe ich in den Supermarkt und kaufe frisches Obst und Brot."
    },
    {
        "title": "【A2 进阶篇】Eine Reise nach München: Hotel und Freizeit",
        "text": "Letztes Wochenende bin ich mit dem Zug nach München gefahren. Ich habe ein kleines Zimmer im Stadtzentrum reserviert. Das Wetter war sehr schön, deshalb habe ich den ganzen Nachmittag im Englischen Garten verbracht. Am Abend habe ich typische bayerische Spezialitäten in einem traditionellen Restaurant probiert."
    },
    {
        "title": "【B1 提升篇】Klimaschutz im Alltag: Was jeder tun kann",
        "text": "Der Klimawandel ist eine der größten Herausforderungen unserer Zeit. Viele Menschen fragen sich, wie sie im Alltag einen Beitrag zum Umweltschutz leisten können. Experten empfehlen, öfter auf das Fahrrad umzusteigen und Energie im Haushalt zu sparen. Eine bewusste Ernährung mit regionalen Lebensmitteln spielt ebenfalls eine wichtige Rolle."
    },
    {
        "title": "【B2 高级篇】Die Transformation der modernen Arbeitswelt: Homeoffice",
        "text": "Die fortschreitende Digitalisierung hat die Arbeitsbedingungen grundlegend verändert. Immer mehr Unternehmen stellen ihren Mitarbeitern flexible Arbeitszeitmodelle zur Verfügung. Obwohl das Arbeiten von zu Hause aus die Vereinbarkeit von Beruf und Familie erleichtert, stehen viele Beschäftigte vor der Herausforderung, klare Grenzen zwischen Arbeit und Freizeit zu ziehen."
    }
]

def ingest_article(title: str, text: str, db_path: Optional[str] = None) -> int:
    processed = process_german_text(text)
    target_path = get_db_path(db_path)
    with get_db(target_path) as conn:
        cur = conn.execute("INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
                           (title or "Untitled", text, json.dumps(processed, ensure_ascii=False)))
        return cur.lastrowid

def seed_preset_articles(db_path: Optional[str] = None):
    target = get_db_path(db_path)
    with get_db(target) as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count == 0:
            for art in PRESET_ARTICLES:
                ingest_article(art["title"], art["text"], db_path=target)

# --- 2. NLP & CEFR Tagging ---
try:
    nlp = spacy.load("de_core_news_sm")
except OSError:
    from spacy.cli import download
    download("de_core_news_sm")
    nlp = spacy.load("de_core_news_sm")

CEFR_DICT = {
    "ich": "A1", "du": "A1", "er": "A1", "sie": "A1", "es": "A1", "wir": "A1", "sein": "A1", "haben": "A1",
    "können": "A1", "müssen": "A1", "lernen": "A1", "arbeiten": "A1", "gut": "A1", "tag": "A1", "gehen": "A1", "nach": "A1",
    "erzählen": "A2", "erklären": "A2", "bestehen": "A2", "prüfung": "A2", "beruf": "A2", "reise": "A2", "fahren": "A2",
    "entscheiden": "B1", "entwickeln": "B1", "zusammenhang": "B1", "gesellschaft": "B1", "meinung": "B1",
    "beeinträchtigen": "B2", "gewährleisten": "B2", "hervorheben": "B2", "voraussetzen": "B2",
    "implizieren": "C1", "fungieren": "C1", "paradigma": "C1", "unabdingbar": "C1"
}

def get_cefr_level(lemma: str) -> str:
    if not lemma:
        return "A1"
    low = lemma.lower()
    if low in CEFR_DICT:
        return CEFR_DICT[low]
    if any(low.endswith(s) for s in ["ität", "ismus", "schaft", "ung"]):
        return "B2" if len(low) > 10 else "B1"
    if len(low) > 11:
        return "B2"
    if len(low) > 7:
        return "B1"
    if len(low) > 4:
        return "A2"
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

def export_anki_deck(output_path: str, db_path: Optional[str] = None) -> str:
    target_path = get_db_path(db_path)
    with get_db(target_path) as conn:
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
    art_id = ingest_article(req.title or "Untitled", req.raw_text)
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
        if not row:
            raise HTTPException(404, "Article not found")
        data = dict(row)
        data.update(json.loads(data["processed_json"]))
        return data

SYSTEM_GRAMMAR_PROMPT = """你是一位精通德语欧标（Goethe-Zertifikat A1-C1）的资深德语教学与考点解析专家。
用户会提供一个德语完整句子，以及他们点击的目标词汇或短语（用户可能是 A1-A2 零基础/初学者）。

请详细分析该词或短语在句中的关键语法考点，特别关照初学者的痛点（如：冠词四格变化、三格动词、动词现在时变位、可分动词前缀、从句动词置后、固定介词搭配）。

以严格的 JSON 格式输出，字段如下：
{
  "grammar_name": "考点名称（如：Akkusativ mit bestimmtem Artikel / Trennbare Verben / Nomen-Verb-Verbindung / Präposition mit Dativ）",
  "cefr_level": "考点对应的欧标等级，只能是 A1/A2/B1/B2/C1 之一",
  "explanation_zh": "面向初学者的通俗精炼中文解析（1-3句话，解释在句中的语法作用、为什么用这个格/变位，指出考试高频错点）",
  "rule_formula": "语法规则或公式（如：trinken + Akkusativ: den Kaffee (m.) / fahren mit + Dativ: der U-Bahn (f.)）",
  "collocations": ["高频用法1", "高频用法2"]
}
不要输出除 JSON 以外的任何文字。"""

@app.post("/api/lookup/grammar")
async def lookup_grammar(req: GrammarLookupReq):
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {
            "grammar_name": f"语法考点辨析 ({req.target_phrase})",
            "cefr_level": "A1",
            "explanation_zh": "请在 .env 中配置 DEEPSEEK_API_KEY 获取实时歌德大纲 AI 分析。",
            "rule_formula": "Grammar Pattern",
            "collocations": [f"{req.target_phrase} (常用释义)"]
        }

    user_content = f"句子: \"{req.sentence}\"\n目标词/短语: \"{req.target_phrase}\""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_GRAMMAR_PROMPT},
                    {"role": "user", "content": user_content}
                ],
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
