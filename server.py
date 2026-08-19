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
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
try:
    import spacy
except ImportError:
    spacy = None
import genanki

def load_env():
    try:
        import dotenv
        dotenv.load_dotenv(override=True)
    except Exception:
        pass
    for base_dir in [os.path.dirname(__file__), os.getcwd()]:
        env_file = os.path.join(base_dir, ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'").strip('"')
                            if k:
                                os.environ[k] = v
            except Exception:
                pass

load_env()

DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", os.path.dirname(__file__))
AUDIO_CACHE_DIR = os.path.join(DATA_DIR, ".cache", "audio")
try:
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
except Exception:
    pass

PROGRESS_DB_PATH = os.path.join(DATA_DIR, "progress.db")

def get_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("DATABASE_PATH", os.path.join(DATA_DIR, "delector.db"))

def get_progress_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("PROGRESS_DB_PATH", PROGRESS_DB_PATH)

# --- 1. Database Layer (stdlib sqlite3) ---
def get_db(db_path: Optional[str] = None):
    conn = sqlite3.connect(get_db_path(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def get_progress_db(db_path: Optional[str] = None):
    conn = sqlite3.connect(get_progress_db_path(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def init_progress_db(db_path: Optional[str] = None):
    target_path = get_progress_db_path(db_path)
    with get_progress_db(target_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS study_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ref_id INTEGER,
                note TEXT DEFAULT '',
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                card_type TEXT NOT NULL,
                mode TEXT NOT NULL,
                correct INTEGER NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                cards_added INTEGER DEFAULT 0,
                cards_mastered INTEGER DEFAULT 0,
                articles_read INTEGER DEFAULT 0,
                quiz_sessions INTEGER DEFAULT 0,
                study_minutes INTEGER DEFAULT 0
            );
        """)

def log_study_event(event_type: str, ref_id: Optional[int] = None, note: str = "", minutes: int = 0, db_path: Optional[str] = None):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        with get_progress_db(db_path) as conn:
            conn.execute(
                "INSERT INTO study_log (event_type, ref_id, note) VALUES (?, ?, ?)",
                (event_type, ref_id, note)
            )
            conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
            if event_type == "add_card":
                conn.execute("UPDATE daily_summary SET cards_added = cards_added + 1, study_minutes = study_minutes + ? WHERE date = ?", (max(1, minutes), today))
            elif event_type == "master_card":
                conn.execute("UPDATE daily_summary SET cards_mastered = cards_mastered + 1, study_minutes = study_minutes + ? WHERE date = ?", (max(1, minutes), today))
            elif event_type == "read_article":
                conn.execute("UPDATE daily_summary SET articles_read = articles_read + 1, study_minutes = study_minutes + ? WHERE date = ?", (max(3, minutes), today))
            elif event_type == "quiz_session":
                conn.execute("UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, study_minutes = study_minutes + ? WHERE date = ?", (max(2, minutes), today))
    except Exception as e:
        print(f"[Warn] Failed to log study event: {e}")

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
                mastered INTEGER DEFAULT 0,
                mastered_at TIMESTAMP,
                correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                due_date TEXT,
                interval_days INTEGER DEFAULT 1,
                ease_factor REAL DEFAULT 2.5,
                repetition_count INTEGER DEFAULT 0,
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
                mastered INTEGER DEFAULT 0,
                mastered_at TIMESTAMP,
                correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                due_date TEXT,
                interval_days INTEGER DEFAULT 1,
                ease_factor REAL DEFAULT 2.5,
                repetition_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reading_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                sentence_id INTEGER,
                selected_text TEXT NOT NULL,
                color TEXT DEFAULT 'yellow',
                note_content TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Migrations for existing databases
        for tbl in ["vocab_cards", "grammar_cards"]:
            cols = [col[1] for col in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            if "mastered" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN mastered INTEGER DEFAULT 0")
            if "mastered_at" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN mastered_at TIMESTAMP")
            if "correct_count" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN correct_count INTEGER DEFAULT 0")
            if "wrong_count" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN wrong_count INTEGER DEFAULT 0")
            today_init = datetime.now().strftime('%Y-%m-%d')
            if "due_date" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN due_date TEXT DEFAULT '{today_init}'")
            if "interval_days" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN interval_days INTEGER DEFAULT 1")
            if "ease_factor" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN ease_factor REAL DEFAULT 2.5")
            if "repetition_count" not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN repetition_count INTEGER DEFAULT 0")

    init_progress_db()
    seed_preset_articles(target_path)

def get_setting(key: str, default: str = "", db_path: Optional[str] = None) -> str:
    try:
        with get_db(db_path) as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if row and row["value"] is not None and row["value"] != "":
                return row["value"]
    except Exception:
        pass
    return os.environ.get(key, default)

def set_setting(key: str, value: str, db_path: Optional[str] = None):
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, (key, value))

def get_effective_api_key(db_path: Optional[str] = None) -> str:
    return get_setting("DEEPSEEK_API_KEY", "", db_path=db_path)

def get_effective_api_base_url(db_path: Optional[str] = None) -> str:
    return get_setting("API_BASE_URL", "https://api.deepseek.com", db_path=db_path)

def get_effective_api_model(db_path: Optional[str] = None) -> str:
    return get_setting("API_MODEL", "deepseek-v4-flash", db_path=db_path)

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
import importlib
from pathlib import Path
from start import is_android

# md 带词向量、标注更准，是桌面端首选；sm 体积小，Android 包里装的和自动下载兜底都用它。
# 按顺序取第一个能加载的。
SPACY_MODEL_CANDIDATES = ("de_core_news_md", "de_core_news_sm")
AUTO_DOWNLOAD_MODEL = "de_core_news_sm"

def _load_spacy_model(name: str):
    """加载指定德语模型，返回 (nlp, 加载方式描述)；全部策略失败则抛 RuntimeError。

    为什么不能只用 spacy.load(name)：它走 spacy.util.is_package()，查的是
    importlib.metadata 的 .dist-info 元数据。Android 上模型是被直接拷进 Chaquopy
    的 Python 源码目录的（见 CI 的 sync 步骤），没有 dist-info，于是即便这个包
    import 得动，也只会报 "[E050] Can't find model"——真机上就是这么退化成纯
    Python 路径的。所以按名称失败后要退到模块自身的 load()，最后退到数据目录路径。
    """
    errors = []
    try:
        return spacy.load(name), name
    except Exception as e:
        errors.append(f"spacy.load({name!r}) -> {e}")

    try:
        module = importlib.import_module(name)
    except Exception as e:
        errors.append(f"import {name} -> {e}")
        raise RuntimeError("; ".join(errors))

    try:
        # 等价于 load_model_from_init_py(module.__file__)，绕开 is_package 检查
        return module.load(), f"{name}(module.load)"
    except Exception as e:
        errors.append(f"{name}.load() -> {e}")

    try:
        # meta.json 里的版本与实际数据目录名不一致时，上一步会失败，这里直接找目录
        root = Path(module.__file__).parent
        data_dirs = sorted(root.glob(f"{name}-*"))
        if not data_dirs:
            raise FileNotFoundError(f"{root} 下没有 {name}-* 数据目录")
        return spacy.load(data_dirs[-1]), f"{name}({data_dirs[-1].name})"
    except Exception as e:
        errors.append(f"path load -> {e}")

    raise RuntimeError("; ".join(errors))

nlp = None
# 记录实际生效的引擎，便于在真机上（adb logcat / GET /api/settings）确认
# 到底是 spaCy 还是纯 Python 降级路径在跑——降级本身是静默的。
NLP_ENGINE = "pure_python"
NLP_ENGINE_DETAIL = "spaCy 未安装，使用纯 Python 降级路径（无依存句法/格标注）"

if spacy is not None:
    load_errors = []
    for candidate in SPACY_MODEL_CANDIDATES:
        try:
            nlp, how = _load_spacy_model(candidate)
            NLP_ENGINE = "spacy"
            NLP_ENGINE_DETAIL = f"spaCy {spacy.__version__} + {how}"
            break
        except Exception as e:
            load_errors.append(str(e))

    if nlp is None:
        # 自动下载模型只在桌面端有意义。Android 上 spacy.cli.download 会起 pip
        # 子进程去拉模型：Chaquopy 里必然失败，却会在 import 期阻塞启动。
        if is_android():
            NLP_ENGINE_DETAIL = "spaCy 已装但模型加载失败，降级为纯 Python：" + " | ".join(load_errors)
        else:
            try:
                from spacy.cli import download
                download(AUTO_DOWNLOAD_MODEL)
                nlp, how = _load_spacy_model(AUTO_DOWNLOAD_MODEL)
                NLP_ENGINE = "spacy"
                NLP_ENGINE_DETAIL = f"spaCy {spacy.__version__} + {how}（自动下载）"
            except Exception as e:
                NLP_ENGINE_DETAIL = f"spaCy 已装但模型不可用，降级为纯 Python：{e}"

print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)

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

from core_dict import lookup_core_vocab, get_core_cefr_level
from linguistics import lookup_irregular_verb, split_komposita
from syntax_tree import analyze_sentence_topology, build_clause_tree, analyze_syntax_tree, split_sentences_pure_python

def get_cefr_level(lemma: str) -> str:
    if not lemma:
        return "A1"
    low = lemma.lower().strip()
    
    # 1. Exact core dictionary lookup
    dict_lvl = get_core_cefr_level(low)
    if dict_lvl:
        return dict_lvl

    # 2. Hardcoded fallback list
    if low in CEFR_DICT:
        return CEFR_DICT[low]
        
    # 3. Suffix and length heuristics
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

def _process_german_text_pure_python(text: str) -> Dict[str, Any]:
    raw_sents = split_sentences_pure_python(text)
    sentences = []
    all_tokens = []
    global_tok_id = 0
    for sent_idx, sent_text in enumerate(raw_sents):
        tokens = []
        raw_toks = re.findall(r'\w+|[^\w\s]', sent_text, re.UNICODE)
        for raw_tok in raw_toks:
            is_punct = bool(re.match(r'^[^\w\s]+$', raw_tok))
            # 无 spacy 时靠核心词库反查词元，命中则用词典词元覆盖朴素小写形
            dict_entry = lookup_core_vocab(raw_tok) or {}
            lemma = dict_entry.get("lemma") or raw_tok.lower()
            pos = dict_entry.get("pos") or ("PUNCT" if is_punct else ("NOUN" if raw_tok[0].isupper() else "ADV"))
            gender = dict_entry.get("gender", "")
            cefr = dict_entry.get("cefr_level") or ("" if is_punct else get_cefr_level(lemma))
            tok = {
                "id": global_tok_id,
                "text": raw_tok,
                "lemma": lemma,
                "pos": pos,
                "gender": gender,
                "case": "",
                "cefr_level": cefr,
                "is_punct": is_punct,
                "is_space": False
            }
            tokens.append(tok)
            all_tokens.append(tok)
            global_tok_id += 1
        sentences.append({
            "id": sent_idx,
            "text": sent_text,
            "tokens": tokens,
            "topology": {"vorfeld": [], "linke_klammer": [], "mittelfeld": [t["text"] for t in tokens if not t["is_punct"]], "rechte_klammer": [], "nachfeld": []},
            "clause_tree": {"id": "root", "type": "hauptsatz", "label": "Hauptsatz", "label_zh": "主句核心", "connector": "", "finite_verb": "", "token_ids": list(range(len(tokens))), "formula": "", "children": []}
        })
    stats = calculate_cefr_stats(all_tokens)
    return {"version": "3.5.0", "sentence_count": len(sentences), "sentences": sentences, "stats": stats}

def process_german_text(text: str) -> Dict[str, Any]:
    if nlp is None:
        return _process_german_text_pure_python(text)
    doc = nlp(text)
    sentences = []
    all_tokens = []
    for sent_idx, sent in enumerate(doc.sents):
        tokens = []
        token_map = {}
        spacy_tokens = list(sent)
        for t in spacy_tokens:
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
            token_map[t.i] = tok
            all_tokens.append(tok)

        # Detect separable verb prefixes in sentence (compound:prt or svp or PTKVZ)
        for t in spacy_tokens:
            if t.dep_ in ("compound:prt", "svp", "ptkv") or t.tag_ == "PTKVZ":
                head = t.head
                if head and head.i in token_map:
                    prefix_str = (t.lemma_ or t.text).lower().strip()
                    verb_lemma = (head.lemma_ or head.text).lower().strip()
                    if verb_lemma.startswith(prefix_str):
                        sep_lemma = verb_lemma
                    else:
                        sep_lemma = f"{prefix_str}{verb_lemma}"
                    
                    verb_tok = token_map[head.i]
                    prefix_tok = token_map[t.i]
                    
                    verb_tok["separable"] = {
                        "sep_prefix_id": t.i,
                        "sep_lemma": sep_lemma
                    }
                    prefix_tok["separable"] = {
                        "sep_verb_id": head.i,
                        "sep_lemma": sep_lemma
                    }

                    # Re-evaluate CEFR level based on full separable verb (e.g. einsteigen -> A1 instead of steigen -> B1)
                    sep_cefr = get_cefr_level(sep_lemma)
                    verb_tok["cefr_level"] = sep_cefr
                    prefix_tok["cefr_level"] = sep_cefr
        # Compute topological 5 fields and clause AST tree for each sentence
        top = analyze_sentence_topology(sent)
        tree = build_clause_tree(sent)
        sentences.append({
            "id": sent_idx,
            "text": sent.text,
            "tokens": tokens,
            "topology": top,
            "clause_tree": tree
        })
    stats = calculate_cefr_stats(all_tokens)
    return {"version": "3.5.0", "sentence_count": len(sentences), "sentences": sentences, "stats": stats}



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
    title = re.split(r'[-|–]\s*(?:DER SPIEGEL|DW|Tagesschau|ZEIT ONLINE|ZDF|FAZ|SZ|Süddeutsche|Deutschlandfunk)', title)[0].strip()
    
    # Remove script, style, nav, header, footer, etc.
    cleaned = re.sub(r'<(script|style|nav|header|footer|svg|aside|form|button|noscript|figure)[^>]*>.*?</\1>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    
    # Prefer <article> block if available
    article_match = re.search(r'<article[^>]*>(.*?)</article>', cleaned, flags=re.IGNORECASE | re.DOTALL)
    scope_html = article_match.group(1) if article_match else cleaned

    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', scope_html, flags=re.IGNORECASE | re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        txt = re.sub(r'<[^>]+>', '', p)
        txt = html.unescape(txt).strip()
        if len(txt) > 20 and not any(k in txt.lower() for k in ["cookie", "datenschutz", "abonnieren", "newsletter", "all rights reserved", "impressum", "urheberrecht"]):
            clean_paras.append(txt)
            
    if not clean_paras:
        raw_text = re.sub(r'<[^>]+>', ' ', scope_html)
        clean_paras = [html.unescape(line).strip() for line in raw_text.split('\n') if len(line.strip()) > 30]

    body_text = "\n\n".join(clean_paras)
    return title, body_text

async def fetch_remote_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

# --- RSS & News Feeds Integration ---
PRESET_FEEDS = [
    {
        "id": "tagesschau_news",
        "name": "Tagesschau · 德国权威时事",
        "level": "B2-C1",
        "category": "Aktuell",
        "url": "https://www.tagesschau.de/xml/rss2/",
        "description": "德国第一电视台权威时政要闻"
    },
    {
        "id": "tagesschau_ausland",
        "name": "Tagesschau · 国际与环球",
        "level": "B2-C1",
        "category": "Ausland",
        "url": "https://www.tagesschau.de/ausland/index~rss2.xml",
        "description": "全球时事与地缘观察精读"
    },
    {
        "id": "dw_deutsch",
        "name": "DW · 德语时事综合",
        "level": "B1-B2",
        "category": "Lernen",
        "url": "https://rss.dw.com/rdf/rss-de-all",
        "description": "德国之声精选德语新闻文章"
    },
    {
        "id": "dlf_news",
        "name": "Deutschlandfunk · 每日整点新闻",
        "level": "B2-C1",
        "category": "Nachrichten",
        "url": "https://www.deutschlandfunk.de/nachrichten-100.rss",
        "description": "标准德语广播权威每日简讯"
    },
    {
        "id": "spiegel_politik",
        "name": "Spiegel · 政治与深度",
        "level": "C1",
        "category": "Politik",
        "url": "https://www.spiegel.de/politik/index.rss",
        "description": "明镜周刊深度时政报道与分析"
    },
    {
        "id": "zeit_online",
        "name": "Zeit Online · 精选社论",
        "level": "C1",
        "category": "Kultur",
        "url": "https://newsfeed.zeit.de/index",
        "description": "时代周报文化与学术随笔"
    }
]

import xml.etree.ElementTree as ET

def parse_rss_feed(xml_text: str) -> List[Dict[str, Any]]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        found_items = [el for el in root.iter() if el.tag.split("}")[-1] == "item"]
        if found_items:
            for item in found_items:
                title = ""
                link = ""
                desc = ""
                pub_date = ""
                for child in item:
                    tag = child.tag.split("}")[-1]
                    if tag == "title" and not title:
                        title = child.text or ""
                    elif tag == "link" and not link:
                        link = child.text or child.get("href", "")
                    elif tag in ("description", "encoded", "summary") and not desc:
                        desc = child.text or ""
                    elif tag in ("pubDate", "date", "updated", "published") and not pub_date:
                        pub_date = child.text or ""
                clean_desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
                if title and link:
                    items.append({
                        "title": html.unescape(title.strip()),
                        "link": link.strip(),
                        "summary": clean_desc[:220] + ("…" if len(clean_desc) > 220 else ""),
                        "pub_date": pub_date.strip()
                    })
        else:
            found_entries = [el for el in root.iter() if el.tag.split("}")[-1] == "entry"]
            for entry in found_entries:
                title = ""
                link = ""
                desc = ""
                pub_date = ""
                for child in entry:
                    tag = child.tag.split("}")[-1]
                    if tag == "title" and not title:
                        title = child.text or ""
                    elif tag == "link" and not link:
                        link = child.get("href", "") or child.text or ""
                    elif tag in ("summary", "content") and not desc:
                        desc = child.text or ""
                    elif tag in ("updated", "published", "date") and not pub_date:
                        pub_date = child.text or ""
                clean_desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
                if title and link:
                    items.append({
                        "title": html.unescape(title.strip()),
                        "link": link.strip(),
                        "summary": clean_desc[:220] + ("…" if len(clean_desc) > 220 else ""),
                        "pub_date": pub_date.strip()
                    })
    except Exception:
        pass
    return items


@app.get("/api/feed/sources")
def get_feed_sources():
    return {"sources": PRESET_FEEDS}

@app.get("/api/feed/items")
async def get_feed_items(url: str):
    if not is_safe_public_url(url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")
    raw_xml = await fetch_remote_html(url)
    items = parse_rss_feed(raw_xml)
    return {"url": url, "count": len(items), "items": items}

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
        if "stats" not in pj or pj.get("version") != "3.4.0":
            pj = process_german_text(data["raw_text"])
            conn.execute("UPDATE articles SET processed_json = ? WHERE id = ?", (json.dumps(pj, ensure_ascii=False), article_id))
        data.update(pj)
        return data

@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        conn.execute("DELETE FROM reading_notes WHERE article_id = ?", (article_id,))
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        return {"deleted": True, "article_id": article_id}



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
    key = get_effective_api_key()
    if not key:
        return {
            "grammar_name": f"语法考点辨析 ({req.target_phrase})",
            "cefr_level": "A1",
            "explanation_zh": "请在右上角「⚙️ 设置」中配置 API Key 获取实时歌德大纲 AI 分析。",
            "rule_formula": "Grammar Pattern",
            "collocations": [f"{req.target_phrase} (常用释义)"]
        }

    base_url = get_effective_api_base_url().rstrip('/')
    model = get_effective_api_model()
    user_content = f"句子: \"{req.sentence}\"\n目标词/短语: \"{req.target_phrase}\""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_GRAMMAR_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if resp.status_code != 200:
                return {
                    "grammar_name": f"考点辨析 ({req.target_phrase})",
                    "cefr_level": "B1",
                    "explanation_zh": f"AI 接口响应异常 ({resp.status_code})，请检查「⚙️ 设置」中的 API Key 余额或网络连接。",
                    "rule_formula": "",
                    "collocations": []
                }
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        return {
            "grammar_name": f"考点辨析 ({req.target_phrase})",
            "cefr_level": "B1",
            "explanation_zh": f"AI 连接超时或异常: {str(e)}",
            "rule_formula": "",
            "collocations": []
        }

SYSTEM_VOCAB_PROMPT = """你是一位精通德汉词典编纂的德语专家。
请根据给定的德语句子上下文和目标词汇，给出该词在当前句中的精准中文简明释义（1-8个字）、复数形式（如果是名词）、常用同义词等。
以严格的 JSON 格式输出：
{
  "definition_zh": "精准中文简明释义（如：挑战 / 减少 / 气温）",
  "plural": "复数形式（如：die Herausforderungen，若非名词留空）",
  "synonyms": ["同义词1", "同义词2"]
}
不要输出除 JSON 以外的任何文字。"""

class VocabLookupReq(BaseModel):
    sentence: str
    target_word: str

@app.post("/api/lookup/vocab")
async def lookup_vocab(req: VocabLookupReq):
    # Tier 1: Local core dictionary hit (0ms zero-latency, 100% offline)
    res = {}
    local_hit = lookup_core_vocab(req.target_word)
    if local_hit:
        res = {
            "definition_zh": local_hit.get("definition_zh", ""),
            "plural": local_hit.get("plural", ""),
            "gender": local_hit.get("gender"),
            "pos": local_hit.get("pos"),
            "cefr_level": local_hit.get("cefr_level"),
            "synonyms": [],
            "source": "local_dict"
        }
    else:
        # Tier 2: DeepSeek AI contextual lookup if API key is configured
        key = get_effective_api_key()
        if not key:
            res = {
                "definition_zh": "",
                "plural": "",
                "synonyms": [],
                "source": "none"
            }
        else:
            base_url = get_effective_api_base_url().rstrip('/')
            model = get_effective_api_model()
            user_content = f"句子: \"{req.sentence}\"\n目标词汇: \"{req.target_word}\""
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": SYSTEM_VOCAB_PROMPT},
                                {"role": "user", "content": user_content}
                            ],
                            "response_format": {"type": "json_object"}
                        }
                    )
                    if resp.status_code != 200:
                        res = {
                            "definition_zh": "",
                            "plural": "",
                            "synonyms": [],
                            "source": "ai_error"
                        }
                    else:
                        content = resp.json()["choices"][0]["message"]["content"]
                        res = json.loads(content)
                        res["source"] = "ai"
            except Exception:
                res = {
                    "definition_zh": "",
                    "plural": "",
                    "synonyms": [],
                    "source": "ai_exception"
                }

    # Morphology & Linguistics Layer:
    # 1. Irregular / Strong verbs Stammformen
    stamm = lookup_irregular_verb(req.target_word)
    if stamm:
        inf = getattr(stamm, "infinitiv", None) or (stamm.get("infinitiv") if hasattr(stamm, "get") else "")
        praet = getattr(stamm, "praeteritum", None) or (stamm.get("praeteritum") if hasattr(stamm, "get") else "")
        p2 = getattr(stamm, "partizip2", None) or (stamm.get("partizip2") if hasattr(stamm, "get") else "")
        hilf = getattr(stamm, "hilfsverb", None) or (stamm.get("hilfsverb") if hasattr(stamm, "get") else "")
        stamm_def = getattr(stamm, "definition_zh", None) or (stamm.get("definition_zh") if hasattr(stamm, "get") else "")

        res["stammformen"] = {
            "infinitiv": inf,
            "praeteritum": praet,
            "partizip2": p2,
            "hilfsverb": hilf
        }
        if not res.get("definition_zh") and stamm_def:
            res["definition_zh"] = stamm_def
            if res.get("source") == "none":
                res["source"] = "linguistics"

    # 2. Komposita compound word decomposition
    target_clean = req.target_word.strip()
    if len(target_clean) >= 7:
        parts = split_komposita(target_clean)
        if len(parts) >= 2:
            res["komposita"] = []
            for p in parts:
                p_copy = dict(p)
                if "definition_zh" not in p_copy and "def_zh" in p_copy:
                    p_copy["definition_zh"] = p_copy["def_zh"]
                if "def_zh" not in p_copy and "definition_zh" in p_copy:
                    p_copy["def_zh"] = p_copy["definition_zh"]
                res["komposita"].append(p_copy)
            if not res.get("definition_zh"):
                sub_defs = [p.get("definition_zh") or p.get("def_zh") for p in parts if (p.get("definition_zh") or p.get("def_zh"))]
                if sub_defs:
                    res["definition_zh"] = " + ".join(sub_defs)
                    if res.get("source") == "none":
                        res["source"] = "linguistics"

    return res


@app.post("/api/cards/vocab")
def add_vocab_card(req: VocabCardReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards (article_id, word, lemma, pos, gender, cefr_level, definition_zh, sentence_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.article_id, req.word, req.lemma, req.pos, req.gender, req.cefr_level, req.definition_zh, req.sentence_context)
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.word)
    return {"status": "ok", "id": card_id}

@app.post("/api/cards/grammar")
def add_grammar_card(req: GrammarCardReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO grammar_cards (article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula) VALUES (?, ?, ?, ?, ?, ?)",
            (req.article_id, req.sentence_context, req.grammar_name, req.cefr_level, req.explanation_zh, req.rule_formula)
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.grammar_name)
    return {"status": "ok", "id": card_id}

@app.get("/api/cards")
def get_cards():
    with get_db() as conn:
        v = [dict(r) for r in conn.execute(
            "SELECT * FROM vocab_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
        ).fetchall()]
        g = [dict(r) for r in conn.execute(
            "SELECT * FROM grammar_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
        ).fetchall()]
        return {"vocab_cards": v, "grammar_cards": g}

# --- Phase A: Delete & Master ---

@app.delete("/api/cards/{card_type}/{card_id}")
def delete_card(card_type: str, card_id: int):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (card_id,))
    log_study_event("delete_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "deleted_id": card_id, "card_type": card_type}

class MasterReq(BaseModel):
    mastered: bool

@app.patch("/api/cards/{card_type}/{card_id}/master")
def toggle_master(card_type: str, card_id: int, req: MasterReq):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    now_ts = datetime.now().isoformat() if req.mastered else None
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(
            f"UPDATE {tbl} SET mastered = ?, mastered_at = ? WHERE id = ?",
            (1 if req.mastered else 0, now_ts, card_id)
        )
    if req.mastered:
        log_study_event("master_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "id": card_id, "mastered": req.mastered}

# --- Phase B: Quiz Record ---

class QuizRecordReq(BaseModel):
    card_id: int
    card_type: str  # 'vocab' | 'grammar'
    mode: str       # 'flashcard' | 'dictation' | 'choice'
    correct: bool

@app.post("/api/quiz/record")
def record_quiz(req: QuizRecordReq):
    if req.card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if req.card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (req.card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {req.card_id} not found")
        if req.correct:
            conn.execute(f"UPDATE {tbl} SET correct_count = correct_count + 1 WHERE id = ?", (req.card_id,))
        else:
            conn.execute(f"UPDATE {tbl} SET wrong_count = wrong_count + 1 WHERE id = ?", (req.card_id,))
    with get_progress_db() as conn:
        conn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (req.card_id, req.card_type, req.mode, 1 if req.correct else 0)
        )
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
        conn.execute(
            "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, study_minutes = study_minutes + 1 WHERE date = ?",
            (today,)
        )
    return {"status": "ok"}

# --- Phase C: Progress Stats ---

class ReadLogReq(BaseModel):
    article_id: int
    title: Optional[str] = ""

@app.post("/api/progress/log-read")
def log_article_read(req: ReadLogReq):
    log_study_event("read_article", req.article_id, req.title or "", minutes=8)
    return {"status": "ok"}

@app.get("/api/progress/stats")
def get_progress_stats():
    from datetime import timedelta
    # --- main db ---
    with get_db() as conn:
        total_vocab   = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
        total_grammar = conn.execute("SELECT COUNT(*) FROM grammar_cards").fetchone()[0]
        mastered_vocab   = conn.execute("SELECT COUNT(*) FROM vocab_cards WHERE mastered=1").fetchone()[0]
        mastered_grammar = conn.execute("SELECT COUNT(*) FROM grammar_cards WHERE mastered=1").fetchone()[0]
        total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

        # CEFR breakdown (both tables combined)
        cefr_counts: Dict[str, int] = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
        for row in conn.execute("SELECT cefr_level, COUNT(*) as cnt FROM vocab_cards GROUP BY cefr_level"):
            lvl = row["cefr_level"] or "A1"
            if lvl in cefr_counts:
                cefr_counts[lvl] += row["cnt"]
        for row in conn.execute("SELECT cefr_level, COUNT(*) as cnt FROM grammar_cards GROUP BY cefr_level"):
            lvl = row["cefr_level"] or "A1"
            if lvl in cefr_counts:
                cefr_counts[lvl] += row["cnt"]

        # Quiz accuracy from card tables
        vc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM vocab_cards").fetchone()
        gc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM grammar_cards").fetchone()
        total_correct = (vc_row["c"] or 0) + (gc_row["c"] or 0)
        total_wrong   = (vc_row["w"] or 0) + (gc_row["w"] or 0)
        total_attempts = total_correct + total_wrong
        accuracy_pct = round(total_correct / total_attempts * 100, 1) if total_attempts > 0 else 0.0

        # Top error-prone cards (wrong_count > 2× correct_count, limit 5)
        top_errors = []
        for row in conn.execute(
            "SELECT id, word, definition_zh, wrong_count, correct_count FROM vocab_cards "
            "WHERE wrong_count > 0 ORDER BY (wrong_count * 1.0 / MAX(correct_count+1, 1)) DESC LIMIT 5"
        ):
            top_errors.append(dict(row))

    # --- progress db ---
    with get_progress_db() as conn:
        # 30-day daily trend
        today = datetime.now().date()
        trend = []
        for i in range(29, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            row = conn.execute("SELECT * FROM daily_summary WHERE date = ?", (d,)).fetchone()
            if row:
                trend.append(dict(row))
            else:
                trend.append({"date": d, "cards_added": 0, "cards_mastered": 0,
                               "articles_read": 0, "quiz_sessions": 0, "study_minutes": 0})

        # Streak calculation
        streak = 0
        check_date = today
        # treat today as active if it has any study_log entries
        for _ in range(365):
            ds = check_date.isoformat()
            entry = conn.execute("SELECT 1 FROM study_log WHERE date(logged_at)=? LIMIT 1", (ds,)).fetchone()
            if entry:
                streak += 1
                check_date = check_date - timedelta(days=1)
            else:
                break

        total_quiz_sessions = conn.execute("SELECT SUM(quiz_sessions) FROM daily_summary").fetchone()[0] or 0
        total_study_minutes = conn.execute("SELECT SUM(study_minutes) FROM daily_summary").fetchone()[0] or 0

    total_cards    = total_vocab + total_grammar
    total_mastered = mastered_vocab + mastered_grammar

    # Milestones
    milestones = [
        {"id": "first_card",     "title": "初临纸页",   "desc": "制作了第一张卡片",       "icon": "🌱", "unlocked": total_cards >= 1},
        {"id": "first_article",  "title": "开卷有益",   "desc": "研读了第一篇德语文章",   "icon": "📖", "unlocked": total_articles >= 1},
        {"id": "master_10",      "title": "小试牛刀",   "desc": "斩获 10 张已掌握卡片",   "icon": "⚔️", "unlocked": total_mastered >= 10},
        {"id": "master_50",      "title": "千锤百炼",   "desc": "斩获 50 张已掌握卡片",   "icon": "🛡️", "unlocked": total_mastered >= 50},
        {"id": "master_100",     "title": "百词斩将",   "desc": "斩获 100 张已掌握卡片",  "icon": "🏆", "unlocked": total_mastered >= 100},
        {"id": "master_200",     "title": "词海无涯",   "desc": "斩获 200 张已掌握卡片",  "icon": "👑", "unlocked": total_mastered >= 200},
        {"id": "streak_3",       "title": "三日不绝",   "desc": "连续打卡 3 天",          "icon": "🔥", "unlocked": streak >= 3},
        {"id": "streak_7",       "title": "一周常胜",   "desc": "连续打卡 7 天",          "icon": "⚡", "unlocked": streak >= 7},
        {"id": "streak_30",      "title": "月光苦读者", "desc": "连续打卡 30 天",         "icon": "🌙", "unlocked": streak >= 30},
    ]

    return {
        "total_cards":    total_cards,
        "total_vocab":    total_vocab,
        "total_grammar":  total_grammar,
        "total_mastered": total_mastered,
        "mastered_vocab":   mastered_vocab,
        "mastered_grammar": mastered_grammar,
        "total_articles": total_articles,
        "streak":         streak,
        "total_quiz_sessions": total_quiz_sessions,
        "total_study_minutes": total_study_minutes,
        "total_attempts": total_attempts,
        "accuracy_pct":   accuracy_pct,
        "cefr_counts":    cefr_counts,
        "top_errors":     top_errors,
        "trend":          trend,
        "milestones":     milestones,
    }

@app.get("/api/cards/export/apkg")
def export_apkg():
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "DeLector_Deck.apkg")
    export_anki_deck(path)
    return FileResponse(path, filename="DeLector_Deck.apkg", media_type="application/octet-stream")

# --- Edge Neural TTS Audio Endpoints ---
class TTSReq(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-KatjaNeural"
    rate: Optional[str] = "+0%"

def get_cache_info() -> Dict[str, Any]:
    total_size = 0
    count = 0
    if os.path.exists(AUDIO_CACHE_DIR):
        for fname in os.listdir(AUDIO_CACHE_DIR):
            fpath = os.path.join(AUDIO_CACHE_DIR, fname)
            if os.path.isfile(fpath):
                count += 1
                total_size += os.path.getsize(fpath)
    return {
        "file_count": count,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "total_size_bytes": total_size
    }

def prune_audio_cache(max_files: int = 300):
    if not os.path.exists(AUDIO_CACHE_DIR):
        return
    files = []
    for fname in os.listdir(AUDIO_CACHE_DIR):
        fpath = os.path.join(AUDIO_CACHE_DIR, fname)
        if os.path.isfile(fpath):
            files.append((fpath, os.path.getmtime(fpath)))
    if len(files) > max_files:
        files.sort(key=lambda x: x[1])
        for fpath, _ in files[: len(files) - max_files + 30]:
            try:
                os.remove(fpath)
            except Exception:
                pass

async def generate_edge_tts_audio(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> str:
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(400, "Text cannot be empty")
        
    cache_key = hashlib.sha256(f"{voice}_{rate}_{clean_text}".encode("utf-8")).hexdigest()
    cache_file = os.path.join(AUDIO_CACHE_DIR, f"{cache_key}.mp3")
    
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 100:
        return cache_file
        
    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice=voice, rate=rate)
        await communicate.save(cache_file)
        prune_audio_cache()
        return cache_file
    except Exception as e:
        # Multi-provider pure-Python httpx fallback (accessible in mainland China)
        from urllib.parse import quote
        q = quote(clean_text[:250])
        candidate_urls = [
            f"https://dict.youdao.com/dictvoice?audio={q}&le=de",
            f"https://fanyi.baidu.com/gettts?lan=de&text={q}&spd=3&source=web",
            f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=de&client=tw-ob"
        ]
        for tts_url in candidate_urls:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(tts_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    if resp.status_code == 200 and len(resp.content) > 200:
                        with open(cache_file, "wb") as f:
                            f.write(resp.content)
                        prune_audio_cache()
                        return cache_file
            except Exception:
                continue
        raise HTTPException(500, f"TTS synthesis failed: {str(e)}")

@app.post("/api/audio/tts")
async def get_audio_tts(req: TTSReq):
    try:
        audio_path = await generate_edge_tts_audio(req.text, req.voice or "de-DE-KatjaNeural", req.rate or "+0%")
        return FileResponse(audio_path, media_type="audio/mpeg", filename="speech.mp3")
    except Exception as e:
        raise HTTPException(500, f"TTS synthesis failed: {str(e)}")

@app.get("/api/audio/cache")
def get_audio_cache():
    return get_cache_info()

@app.post("/api/audio/cache/clear")
def clear_audio_cache():
    info = get_cache_info()
    cleared_count = 0
    if os.path.exists(AUDIO_CACHE_DIR):
        for fname in os.listdir(AUDIO_CACHE_DIR):
            fpath = os.path.join(AUDIO_CACHE_DIR, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    cleared_count += 1
            except Exception:
                pass
    return {
        "status": "ok",
        "cleared_count": cleared_count,
        "freed_mb": info["total_size_mb"]
    }

# --- Reading Notes & AI Assist Endpoints ---
class ReadingNoteReq(BaseModel):
    sentence_id: Optional[int] = None
    selected_text: str
    color: Optional[str] = "yellow"
    note_content: Optional[str] = ""

@app.get("/api/articles/{article_id}/notes")
def list_article_notes(article_id: int):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/articles/{article_id}/notes")
def create_article_note(article_id: int, req: ReadingNoteReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO reading_notes (article_id, sentence_id, selected_text, color, note_content) VALUES (?, ?, ?, ?, ?)",
            (article_id, req.sentence_id, req.selected_text, req.color or "yellow", req.note_content or "")
        )
        return {"id": cur.lastrowid, "status": "ok"}

@app.delete("/api/notes/{note_id}")
def delete_article_note(note_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM reading_notes WHERE id = ?", (note_id,))
        return {"status": "ok"}

SYSTEM_NOTE_PROMPT = """你是一位精通德语阅读与考点剖析的资深私教。
请根据学习者给出的德语句子和选中的文本，为学习者生成一份简洁精准的中文精读随笔备忘要点（包括句法结构简析、高频固定搭配及地道中文翻译）。
以严格的 JSON 格式输出：
{
  "summary_zh": "中文一句话精读解析",
  "key_points": ["核心要点1", "核心要点2"]
}
不要输出除 JSON 以外的任何文字。"""

class NoteAssistReq(BaseModel):
    sentence: str
    selected_text: str

@app.post("/api/ai/note-assist")
async def note_assist(req: NoteAssistReq):
    key = get_effective_api_key()
    if not key:
        import logging
        logging.warning("[note-assist] API Key not set — returning stub response. Set in Settings.")
        return {
            "summary_zh": f"精读重点：{req.selected_text}",
            "key_points": ["请在右上角「⚙️ 设置」中配置 API Key 获取深度 AI 语法与搭配解析。"],
            "_stub": True
        }

    base_url = get_effective_api_base_url().rstrip('/')
    model = get_effective_api_model()
    user_content = f"整句: \"{req.sentence}\"\n划选部分: \"{req.selected_text}\""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_NOTE_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception:
        return {
            "summary_zh": f"精读重点：{req.selected_text}",
            "key_points": []
        }

# --- Settings & Configuration API ---
class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    api_model: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_rate: Optional[str] = None

@app.get("/api/settings")
def get_app_settings():
    key = get_effective_api_key()
    masked = ""
    if key:
        if len(key) > 8:
            masked = key[:4] + "•" * (len(key) - 8) + key[-4:]
        else:
            masked = "••••••••"
    return {
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "api_base_url": get_effective_api_base_url(),
        "api_model": get_effective_api_model(),
        "tts_voice": get_setting("TTS_VOICE", "de-DE-KatjaNeural"),
        "tts_rate": get_setting("TTS_RATE", "+0%"),
        "nlp_engine": NLP_ENGINE,
        "nlp_engine_detail": NLP_ENGINE_DETAIL
    }

@app.post("/api/settings")
def update_app_settings(settings: SettingsUpdate):
    if settings.api_key is not None and settings.api_key.strip() != "":
        set_setting("DEEPSEEK_API_KEY", settings.api_key.strip())
    if settings.api_base_url is not None and settings.api_base_url.strip() != "":
        set_setting("API_BASE_URL", settings.api_base_url.strip())
    if settings.api_model is not None and settings.api_model.strip() != "":
        set_setting("API_MODEL", settings.api_model.strip())
    if settings.tts_voice is not None and settings.tts_voice.strip() != "":
        set_setting("TTS_VOICE", settings.tts_voice.strip())
    if settings.tts_rate is not None and settings.tts_rate.strip() != "":
        set_setting("TTS_RATE", settings.tts_rate.strip())
    return {"success": True, "message": "偏好与 API 设置已保存！"}

@app.post("/api/settings/test-key")
async def test_api_key(settings: SettingsUpdate):
    key = settings.api_key.strip() if (settings.api_key and settings.api_key.strip()) else get_effective_api_key()
    if not key:
        return {"success": False, "error": "请先输入 API Key"}
    base_url = (settings.api_base_url.strip() if settings.api_base_url else get_effective_api_base_url()).rstrip('/')
    model = settings.api_model.strip() if settings.api_model else get_effective_api_model()
    
    import time
    start_t = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Sag 'OK'."}],
                    "max_tokens": 5
                }
            )
            latency = int((time.time() - start_t) * 1000)
            if resp.status_code == 200:
                return {"success": True, "latency_ms": latency, "message": f"连接成功！响应延迟: {latency}ms"}
            else:
                return {"success": False, "error": f"连接返回错误代码: {resp.status_code} ({resp.text[:100]})"}
    except Exception as e:
        return {"success": False, "error": f"连接失败: {str(e)}"}

# --- Study Guide Export (Markdown) ---
@app.get("/api/articles/{article_id}/export-guide")
def export_study_guide(article_id: int):
    with get_db() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Article not found")
        notes = conn.execute("SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        vocab = conn.execute("SELECT * FROM vocab_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        grammar = conn.execute("SELECT * FROM grammar_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()

    md = [f"# {art['title']} — DeLector 精读讲义\n"]
    md.append(f"> 导出日期: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 字符数: {len(art['raw_text'])}\n")
    
    if notes:
        md.append("## 📝 精读随笔与重点批注\n")
        for n in notes:
            md.append(f"- **高亮原句**: *{n['selected_text']}*")
            if n['note_content']:
                md.append(f"  - 💡 **随笔笔记**: {n['note_content']}")
        md.append("")

    if vocab:
        md.append("## 🗂️ 核心生词表\n")
        md.append("| 单词 | 原型 | 词性 | CEFR | 中文释义 | 原文语境 |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for v in vocab:
            md.append(f"| **{v['word']}** | {v['lemma']} | {v['pos']} | {v['cefr_level']} | {v['definition_zh']} | *{v['sentence_context']}* |")
        md.append("")

    if grammar:
        md.append("## 🎓 歌德考点深度解析\n")
        for g in grammar:
            md.append(f"### ✦ {g['grammar_name']} ({g['cefr_level']})")
            if g['rule_formula']:
                md.append(f"- **语法公式**: `{g['rule_formula']}`")
            md.append(f"- **解析**: {g['explanation_zh']}")
            md.append(f"- **例句**: *{g['sentence_context']}*\n")

    content = "\n".join(md)
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=study_guide_{article_id}.md"}
    )

# --- Backup & Restore Endpoints ---
@app.get("/api/backup/export")
def export_database_backup():
    with get_db() as conn:
        articles = [dict(r) for r in conn.execute("SELECT * FROM articles").fetchall()]
        vocab = [dict(r) for r in conn.execute("SELECT * FROM vocab_cards").fetchall()]
        grammar = [dict(r) for r in conn.execute("SELECT * FROM grammar_cards").fetchall()]
        notes = [dict(r) for r in conn.execute("SELECT * FROM reading_notes").fetchall()]
        
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "articles": articles,
        "vocab_cards": vocab,
        "grammar_cards": grammar,
        "reading_notes": notes
    }

class RestoreReq(BaseModel):
    version: Optional[int] = 1
    articles: List[Dict[str, Any]] = []
    vocab_cards: List[Dict[str, Any]] = []
    grammar_cards: List[Dict[str, Any]] = []
    reading_notes: List[Dict[str, Any]] = []

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
        for n in req.reading_notes:
            conn.execute(
                "INSERT OR REPLACE INTO reading_notes (id, article_id, sentence_id, selected_text, color, note_content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (n.get("id"), n.get("article_id"), n.get("sentence_id"), n.get("selected_text", ""), n.get("color", "yellow"), n.get("note_content", ""), n.get("created_at"))
            )
    return {"status": "ok", "message": "全量备份恢复成功"}




# ── v3.0 Phase 1: SuperMemo SM-2 & Cloze Exercise Engine ──────────────────────

def calculate_sm2(grade: int, rep: int = 0, interval: int = 1, ef: float = 2.5) -> Tuple[int, int, float, str]:
    """
    SuperMemo SM-2 algorithm with progressive interval scheduling:
    grade: 1 (Forgot/Again), 2 (Hard), 3 (Good), 4 (Easy)
    """
    quality_map = {1: 1, 2: 3, 3: 4, 4: 5}
    q = quality_map.get(grade, 3)
    
    if q < 3:
        new_rep = 0
        new_interval = 1
    else:
        if rep == 0:
            if grade == 4:
                new_interval = 4
            elif grade == 3:
                new_interval = 3
            elif grade == 2:
                new_interval = 2
            else:
                new_interval = 1
        elif rep == 1:
            if grade == 4:
                new_interval = 8
            elif grade == 3:
                new_interval = 6
            elif grade == 2:
                new_interval = 3
            else:
                new_interval = 1
        else:
            if grade == 4:
                new_interval = max(interval + 2, round(interval * ef * 1.3))
            elif grade == 3:
                new_interval = max(interval + 1, round(interval * ef))
            elif grade == 2:
                new_interval = max(interval + 1, round(interval * 1.2))
            else:
                new_interval = 1
        new_rep = rep + 1
    
    new_ef = max(1.3, ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    due_date = (datetime.now() + timedelta(days=new_interval)).strftime('%Y-%m-%d')
    return new_rep, new_interval, round(new_ef, 2), due_date

class CardReviewReq(BaseModel):
    grade: int  # 1: Forgot, 2: Hard, 3: Good, 4: Easy
    card_type: Optional[str] = None

@app.post("/api/cards/{card_type}/{card_id}/review")
def review_card_sm2(card_type: str, card_id: int, req: CardReviewReq):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        
        rep = row["repetition_count"] if "repetition_count" in row.keys() and row["repetition_count"] is not None else 0
        interval = row["interval_days"] if "interval_days" in row.keys() and row["interval_days"] is not None else 1
        ef = row["ease_factor"] if "ease_factor" in row.keys() and row["ease_factor"] is not None else 2.5
        
        new_rep, new_interval, new_ef, due_date = calculate_sm2(req.grade, rep, interval, ef)
        
        is_correct = req.grade >= 2
        correct_incr = 1 if is_correct else 0
        wrong_incr = 1 if not is_correct else 0
        
        conn.execute(f"""
            UPDATE {tbl} 
            SET repetition_count = ?, interval_days = ?, ease_factor = ?, due_date = ?,
                correct_count = correct_count + ?, wrong_count = wrong_count + ?
            WHERE id = ?
        """, (new_rep, new_interval, new_ef, due_date, correct_incr, wrong_incr, card_id))
        
        updated = dict(conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (card_id,)).fetchone())
    
    with get_progress_db() as pconn:
        pconn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (card_id, card_type, "sm2_review", 1 if is_correct else 0)
        )
    log_study_event("quiz_session", card_id, f"sm2:{card_type}:{card_id}")
    return updated

@app.get("/api/cards/due")
def get_due_cards():
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as conn:
        v = [dict(r) for r in conn.execute(
            "SELECT * FROM vocab_cards WHERE mastered = 0 AND (due_date IS NULL OR due_date <= ?) ORDER BY wrong_count DESC, id ASC",
            (today,)
        ).fetchall()]
        g = [dict(r) for r in conn.execute(
            "SELECT * FROM grammar_cards WHERE mastered = 0 AND (due_date IS NULL OR due_date <= ?) ORDER BY wrong_count DESC, id ASC",
            (today,)
        ).fetchall()]
        return {
            "due_vocab": v,
            "due_grammar": g,
            "due_count": len(v) + len(g),
            "today": today
        }

def generate_cloze_exercise(text: str, mode: str = "grammar", article_id: Optional[int] = None) -> Dict[str, Any]:
    if nlp is None:
        # Simple pure-Python cloze fallback
        words = re.findall(r'\w+|[^\w\s]+|\s+', text, re.UNICODE)
        items = []
        tokens_output = []
        blank_counter = 0
        for w in words:
            if w.isalpha() and len(w) >= 4 and blank_counter < 5 and blank_counter % 2 == 0:
                first_letter = w[0]
                items.append({
                    "index": blank_counter,
                    "original": w,
                    "first_letter": first_letter,
                    "lemma": w.lower(),
                    "pos": "NOUN" if w[0].isupper() else "VERB",
                    "hint": f"首字母: {first_letter}...",
                    "type": mode,
                    "sent_idx": 0
                })
                tokens_output.append(f"[[BLANK_{blank_counter}]]")
                blank_counter += 1
            else:
                tokens_output.append(w)
        return {
            "version": "3.5.0",
            "mode": mode,
            "article_id": article_id,
            "masked_text": "".join(tokens_output),
            "blanks_count": len(items),
            "items": items
        }
    doc = nlp(text)
    items = []
    tokens_output = []
    blank_counter = 0

    if mode == "grammar":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                is_grammar_target = (
                    token.pos_ in ("ADP", "SCONJ", "CCONJ") or 
                    (token.pos_ == "AUX" and token.text.lower() in ("wurde", "worden", "werden", "wäre", "hätte", "könnte", "müsste", "sollte")) or
                    (token.pos_ == "ADJ" and len(token.text) > 3)
                )
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_grammar_target and len(sent_blanks) < 2 and len(token.text) >= 2:
                    first_letter = token.text[0]
                    items.append({
                        "index": blank_counter,
                        "original": token.text,
                        "first_letter": first_letter,
                        "lemma": token.lemma_,
                        "pos": token.pos_,
                        "hint": f"首字母: {first_letter}...",
                        "type": "grammar",
                        "sent_idx": sent_idx
                    })
                    tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                    blank_counter += 1
                else:
                    tokens_output.append(token.text_with_ws)

    elif mode == "vocab":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                lvl = get_cefr_level(token.lemma_)
                is_vocab_target = token.pos_ in ("NOUN", "VERB") and lvl in ("A2", "B1", "B2", "C1") and len(token.text) >= 3
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_vocab_target and len(sent_blanks) < 2:
                    first_letter = token.text[0]
                    items.append({
                        "index": blank_counter,
                        "original": token.text,
                        "first_letter": first_letter,
                        "lemma": token.lemma_,
                        "pos": token.pos_,
                        "hint": f"首字母: {first_letter}... ({token.lemma_})",
                        "type": "vocab",
                        "sent_idx": sent_idx
                    })
                    tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                    blank_counter += 1
                else:
                    tokens_output.append(token.text_with_ws)

    elif mode == "ctest":
        for sent_idx, sent in enumerate(doc.sents):
            word_in_sent_idx = 0
            for token in sent:
                if token.is_alpha and len(token.text) >= 3:
                    word_in_sent_idx += 1
                    if sent_idx >= 1 and word_in_sent_idx % 2 == 0:
                        cut_len = (len(token.text) + 1) // 2
                        prefix = token.text[:cut_len]
                        suffix = token.text[cut_len:]
                        items.append({
                            "index": blank_counter,
                            "original": token.text,
                            "prefix": prefix,
                            "suffix": suffix,
                            "first_letter": prefix,
                            "hint": f"词首: {prefix}...",
                            "type": "ctest",
                            "sent_idx": sent_idx
                        })
                        tokens_output.append(f"{prefix}[[BLANK_{blank_counter}]]{token.whitespace_}")
                        blank_counter += 1
                        continue
                tokens_output.append(token.text_with_ws)

    if len(items) == 0:
        for token in doc:
            if token.is_alpha and len(token.text) >= 4 and blank_counter < 3:
                first_letter = token.text[0]
                items.append({
                    "index": blank_counter,
                    "original": token.text,
                    "first_letter": first_letter,
                    "lemma": token.lemma_,
                    "hint": f"首字母: {first_letter}...",
                    "type": mode,
                    "sent_idx": 0
                })
                tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                blank_counter += 1
            else:
                tokens_output.append(token.text_with_ws)

    masked_text = "".join(tokens_output)
    return {
        "mode": mode,
        "items": items,
        "total_blanks": len(items),
        "masked_text": masked_text
    }

class ClozeGenReq(BaseModel):
    mode: Optional[str] = "grammar"

@app.post("/api/articles/{article_id}/exercise/cloze")
def get_article_cloze_exercise(article_id: int, req: ClozeGenReq):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Article {article_id} not found")
        raw_text = row["raw_text"]
        title = row["title"]
    
    data = generate_cloze_exercise(raw_text, mode=req.mode or "grammar", article_id=article_id)
    data["article_id"] = article_id
    data["title"] = title
    return data

class ClozeEvalReq(BaseModel):
    article_id: int
    mode: str
    answers: Dict[str, str]

@app.post("/api/exercise/cloze/evaluate")
def evaluate_cloze_exercise(req: ClozeEvalReq):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (req.article_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Article {req.article_id} not found")
        raw_text = row["raw_text"]
    
    exercise = generate_cloze_exercise(raw_text, mode=req.mode, article_id=req.article_id)
    items = exercise["items"]
    
    results = []
    correct_count = 0
    for item in items:
        idx_str = str(item["index"])
        user_ans = req.answers.get(idx_str, "").strip()
        expected = item["original"]
        
        if item.get("type") == "ctest":
            expected_suffix = item.get("suffix", "")
            is_correct = (user_ans.lower() == expected_suffix.lower()) or (user_ans.lower() == expected.lower())
        else:
            is_correct = (user_ans.lower() == expected.lower())
        
        if is_correct:
            correct_count += 1
        
        results.append({
            "index": item["index"],
            "correct": is_correct,
            "user_answer": user_ans,
            "expected": expected,
            "hint": item.get("hint", ""),
            "type": item.get("type", "grammar")
        })
    
    total = len(items)
    accuracy_pct = round((correct_count / total * 100)) if total > 0 else 0
    
    log_study_event("quiz_session", req.article_id, f"cloze:{req.mode}:{req.article_id}", minutes=3)
    
    return {
        "score": correct_count,
        "total": total,
        "accuracy_pct": accuracy_pct,
        "results": results
    }

class SyntaxAnalyzeReq(BaseModel):
    text: str

@app.post("/api/syntax/analyze")
def api_syntax_analyze(req: SyntaxAnalyzeReq):
    return analyze_syntax_tree(req.text)

# Mount Static UI (Catch-all must be at the very end)
STATIC_DIR = os.environ.get("STATIC_DIR")
if not STATIC_DIR or not os.path.exists(STATIC_DIR):
    for candidate in [
        os.path.join(DATA_DIR, "static"),
        os.path.join(os.path.dirname(__file__), "static"),
        os.path.join(os.getcwd(), "static"),
        "static"
    ]:
        if os.path.exists(candidate) and os.path.isdir(candidate):
            STATIC_DIR = candidate
            break

if STATIC_DIR and os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
