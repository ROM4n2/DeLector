import os
import json
import sqlite3
import random
import tempfile
import re
import html
import socket
import ipaddress
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime
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

def ingest_article(title: str, text: str, db_path: Optional[str] = None, source_url: Optional[str] = None) -> int:
    processed = process_german_text(text)
    target_path = get_db_path(db_path)
    with get_db(target_path) as conn:
        cur = conn.execute("INSERT INTO articles (title, raw_text, processed_json, source_url) VALUES (?, ?, ?, ?)",
                           (title or "Untitled", text, json.dumps(processed, ensure_ascii=False), source_url or ""))
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
    # A1 core
    "ich": "A1", "du": "A1", "er": "A1", "sie": "A1", "es": "A1", "wir": "A1", "ihr": "A1",
    "mein": "A1", "dein": "A1", "sein": "A1", "haben": "A1", "werden": "A1",
    "können": "A1", "müssen": "A1", "wollen": "A1", "sollen": "A1", "dürfen": "A1", "möchten": "A1",
    "lernen": "A1", "arbeiten": "A1", "gut": "A1", "tag": "A1", "gehen": "A1", "nach": "A1",
    "kommen": "A1", "wohnen": "A1", "heißen": "A1", "hallo": "A1", "deutsch": "A1", "deutschkurs": "A1",
    "trinken": "A1", "essen": "A1", "kaffee": "A1", "brot": "A1", "brötchen": "A1", "obst": "A1",
    "kaufen": "A1", "frisch": "A1", "supermarkt": "A1", "unterricht": "A1", "spaß": "A1", "viel": "A1",
    "morgen": "A1", "nachmittag": "A1", "abend": "A1", "u-bahn": "A1", "bahn": "A1", "kurs": "A1",
    "jetzt": "A1", "sprachschule": "A1", "schule": "A1", "jeder": "A1", "groß": "A1", "klein": "A1",
    "neu": "A1", "alt": "A1", "schön": "A1", "eins": "A1", "zwei": "A1", "drei": "A1", "jahr": "A1",
    "mann": "A1", "frau": "A1", "kind": "A1", "haus": "A1", "stadt": "A1", "zimmer": "A1",
    "der": "A1", "die": "A1", "das": "A1", "ein": "A1", "eine": "A1", "in": "A1", "an": "A1",
    "auf": "A1", "aus": "A1", "mit": "A1", "zu": "A1", "zum": "A1", "zur": "A1", "von": "A1",
    "bei": "A1", "für": "A1", "über": "A1", "unter": "A1", "vor": "A1", "hinter": "A1",
    "und": "A1", "oder": "A1", "aber": "A1", "denn": "A1", "nicht": "A1", "kein": "A1",
    "wie": "A1", "was": "A1", "wo": "A1", "woher": "A1", "wohin": "A1", "wann": "A1", "wer": "A1",
    
    # A2
    "erzählen": "A2", "erklären": "A2", "bestehen": "A2", "prüfung": "A2", "beruf": "A2", "reise": "A2",
    "fahren": "A2", "wochenende": "A2", "zug": "A2", "reservieren": "A2", "stadtzentrum": "A2",
    "wetter": "A2", "deshalb": "A2", "ganz": "A2", "garten": "A2", "verbringen": "A2",
    "typisch": "A2", "bayerisch": "A2", "spezialität": "A2", "traditionell": "A2", "restaurant": "A2", "probieren": "A2",
    "besuchen": "A2", "helfen": "A2", "treffen": "A2", "beginnen": "A2", "verstehen": "A2",
    
    # B1
    "entscheiden": "B1", "entwickeln": "B1", "zusammenhang": "B1", "gesellschaft": "B1", "meinung": "B1",
    "klimawandel": "B1", "klimaschutz": "B1", "herausforderung": "B1", "beitrag": "B1", "leisten": "B1",
    "umweltschutz": "B1", "experte": "B1", "empfehlen": "B1", "umsteigen": "B1", "energie": "B1",
    "haushalt": "B1", "sparen": "B1", "bewusst": "B1", "ernährung": "B1", "regional": "B1",
    "lebensmittel": "B1", "ebenfalls": "B1", "rolle": "B1", "spielen": "B1", "alltag": "B1",
    
    # B2
    "beeinträchtigen": "B2", "gewährleisten": "B2", "hervorheben": "B2", "voraussetzen": "B2",
    "digitalisierung": "B2", "transformation": "B2", "arbeitsbedingung": "B2", "grundlegend": "B2",
    "unternehmen": "B2", "mitarbeiter": "B2", "flexibel": "B2", "arbeitszeitmodell": "B2",
    "verfügung": "B2", "vereinbarkeit": "B2", "beschäftigte": "B2", "grenze": "B2", "fortschreitend": "B2",
    "arbeitswelt": "B2", "homeoffice": "B2", "ethisch": "B2", "fragestellung": "B2", "existenziell": "B2",
    "tragweite": "B2",
    
    # C1
    "implizieren": "C1", "fungieren": "C1", "paradigma": "C1", "unabdingbar": "C1",
    "differenzieren": "C1", "konstatieren": "C1", "ambivalent": "C1", "sukzessive": "C1"
}

def get_cefr_level(lemma: str) -> str:
    if not lemma:
        return "A1"
    low = lemma.lower().strip()
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

def calculate_cefr_stats(tokens_list: list) -> Dict[str, Any]:
    counts = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
    words = [t for t in tokens_list if t.get("cefr_level")]
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
        
    est_minutes = max(1, round(total_words / 90))  # 90 words/min 精读标准
    
    return {
        "word_count": total_words,
        "est_reading_minutes": est_minutes,
        "recommended_level": recommended,
        "cefr_counts": counts,
        "cefr_percentages": percentages
    }

def process_german_text(text: str) -> Dict[str, Any]:
    doc = nlp(text)
    sentences = []
    all_tokens = []
    for sent_idx, sent in enumerate(doc.sents):
        tokens = []
        for t in sent:
            morph = t.morph.to_dict()
            is_word = not t.is_punct and not t.is_space
            tok = {
                "id": t.i,
                "text": t.text,
                "lemma": t.lemma_,
                "pos": t.pos_,
                "gender": morph.get("Gender", ""),
                "case": morph.get("Case", ""),
                "cefr_level": get_cefr_level(t.lemma_) if is_word else "",
                "is_punct": t.is_punct,
                "is_space": t.is_space
            }
            tokens.append(tok)
            all_tokens.append(tok)
        sentences.append({"id": sent_idx, "text": sent.text, "tokens": tokens})
    stats = calculate_cefr_stats(all_tokens)
    return {"sentence_count": len(sentences), "sentences": sentences, "stats": stats}

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

class IngestUrlReq(BaseModel):
    url: str
    title: Optional[str] = ""

def is_safe_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False
            
        ip_str = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip_str)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return False
        return True
    except Exception:
        return False

def clean_html_to_article(raw_html: str) -> Tuple[str, str]:
    title_match = re.search(r'<title>(.*?)</title>', raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1).strip()) if title_match else "Extracted Article"
    title = re.split(r'[-|–]\s*(?:DER SPIEGEL|DW|Tagesschau|ZEIT ONLINE|ZDF|FAZ|SZ|Süddeutsche)', title)[0].strip()
    
    cleaned = re.sub(r'<(script|style|nav|header|footer|svg|aside|form|button|noscript)[^>]*>.*?</\1>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', cleaned, flags=re.IGNORECASE | re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        txt = re.sub(r'<[^>]+>', '', p)
        txt = html.unescape(txt).strip()
        if len(txt) > 25 and not any(k in txt.lower() for k in ["cookie", "datenschutz", "abonnieren", "newsletter", "all rights reserved"]):
            clean_paras.append(txt)
            
    if not clean_paras:
        raw_text = re.sub(r'<[^>]+>', ' ', cleaned)
        clean_paras = [html.unescape(line).strip() for line in raw_text.split('\n') if len(line.strip()) > 30]

    body_text = "\n\n".join(clean_paras)
    return title, body_text

async def fetch_remote_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(400, f"无法抓取该网页 (HTTP {resp.status_code})")
        if not is_safe_public_url(str(resp.url)):
            raise HTTPException(400, "禁止访问内网或保留地址 (SSRF Protection)")
        return resp.text

@app.post("/api/articles/ingest-url")
async def ingest_from_url(req: IngestUrlReq):
    if not is_safe_public_url(req.url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")
    
    raw_html = await fetch_remote_html(req.url)
    title, body_text = clean_html_to_article(raw_html)
    if not body_text or len(body_text.strip()) < 30:
        raise HTTPException(400, "未能从该网页提取到有效的德语正文，请尝试直接复制粘贴")
        
    final_title = req.title.strip() if req.title else title
    art_id = await asyncio.to_thread(ingest_article, final_title, body_text, None, req.url)
    with get_db() as conn:
        row = conn.execute("SELECT processed_json FROM articles WHERE id = ?", (art_id,)).fetchone()
        pj = json.loads(row["processed_json"]) if row else {}
    return {"article_id": art_id, "title": final_title, "char_count": len(body_text), "stats": pj.get("stats", {})}

@app.post("/api/articles/ingest")
def ingest(req: IngestReq):
    art_id = ingest_article(req.title or "Untitled", req.raw_text)
    return {"article_id": art_id, "title": req.title}

@app.get("/api/articles")
def list_articles():
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, created_at, length(raw_text) as char_count, raw_text, processed_json FROM articles ORDER BY id DESC").fetchall()
        result = []
        for r in rows:
            d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
            try:
                pj = json.loads(r["processed_json"])
                if "stats" not in pj:
                    pj = process_german_text(r["raw_text"])
                    conn.execute("UPDATE articles SET processed_json = ? WHERE id = ?", (json.dumps(pj, ensure_ascii=False), r["id"]))
                d["stats"] = pj.get("stats", {})
            except Exception:
                d["stats"] = {}
            result.append(d)
        return result

@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        data = dict(row)
        pj = json.loads(data["processed_json"])
        if "stats" not in pj:
            pj = process_german_text(data["raw_text"])
            conn.execute("UPDATE articles SET processed_json = ? WHERE id = ?", (json.dumps(pj, ensure_ascii=False), article_id))
        data.update(pj)
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

# --- Backup & Restore Endpoints ---
@app.get("/api/backup/export")
def export_database_backup():
    with get_db() as conn:
        articles = [dict(r) for r in conn.execute("SELECT * FROM articles").fetchall()]
        vocab = [dict(r) for r in conn.execute("SELECT * FROM vocab_cards").fetchall()]
        grammar = [dict(r) for r in conn.execute("SELECT * FROM grammar_cards").fetchall()]
        
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "articles": articles,
        "vocab_cards": vocab,
        "grammar_cards": grammar
    }

class RestoreReq(BaseModel):
    version: Optional[int] = 1
    articles: List[Dict[str, Any]] = []
    vocab_cards: List[Dict[str, Any]] = []
    grammar_cards: List[Dict[str, Any]] = []

@app.post("/api/backup/restore")
def restore_database_backup(req: RestoreReq):
    with get_db() as conn:
        for a in req.articles:
            conn.execute(
                "INSERT OR REPLACE INTO articles (id, title, raw_text, processed_json, source_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (a.get("id"), a.get("title", "Untitled"), a.get("raw_text", ""), a.get("processed_json", "{}"), a.get("source_url", ""), a.get("created_at"))
            )
        for v in req.vocab_cards:
            conn.execute(
                "INSERT OR REPLACE INTO vocab_cards (id, article_id, word, lemma, pos, gender, cefr_level, definition_zh, sentence_context, plural, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (v.get("id"), v.get("article_id"), v.get("word", ""), v.get("lemma", ""), v.get("pos", ""), v.get("gender", ""), v.get("cefr_level", "A1"), v.get("definition_zh", ""), v.get("sentence_context", ""), v.get("plural", ""), v.get("created_at"))
            )
        for g in req.grammar_cards:
            conn.execute(
                "INSERT OR REPLACE INTO grammar_cards (id, article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula, examples_zh, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (g.get("id"), g.get("article_id"), g.get("sentence_context", ""), g.get("grammar_name", ""), g.get("cefr_level", "A1"), g.get("explanation_zh", ""), g.get("rule_formula", ""), g.get("examples_zh", ""), g.get("created_at"))
            )
    return {"status": "ok", "message": "全量备份恢复成功"}

# Mount Static UI
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
