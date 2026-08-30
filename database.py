# -*- coding: utf-8 -*-
"""数据库连接、初始化、CRUD、配置存储、音频缓存管理与备份还原底层。"""
import os
import json
import sqlite3
import shutil
import tempfile
import random
import secrets
import time
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from fastapi import HTTPException, Request
import genanki

from nlp import process_german_text

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


def _configure_sqlite_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def get_db(db_path: Optional[str] = None):
    conn = sqlite3.connect(get_db_path(db_path))
    return _configure_sqlite_conn(conn)


def get_progress_db(db_path: Optional[str] = None):
    conn = sqlite3.connect(get_progress_db_path(db_path))
    return _configure_sqlite_conn(conn)



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
                corrected_form TEXT DEFAULT '',
                error_type TEXT DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS prep_saved (
                lemma TEXT NOT NULL,
                praep TEXT NOT NULL,
                kasus TEXT NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (lemma, praep, kasus)
            );
        """)
        conn.execute("""
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
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS essay_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                essay_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_essay_versions_essay_id ON essay_versions(essay_id, id DESC);
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
            if tbl == "grammar_cards":
                for col in ("corrected_form", "error_type"):
                    if col not in cols:
                        conn.execute(f"ALTER TABLE grammar_cards ADD COLUMN {col} TEXT DEFAULT ''")

        conn.execute("""
            INSERT INTO essay_versions (essay_id, content, analysis_json, message)
            SELECT id, content, analysis_json, '初始快照' FROM essays
            WHERE id NOT IN (SELECT DISTINCT essay_id FROM essay_versions);
        """)

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


A1_VOCAB_MODEL = genanki.Model(
    1607392321, 'DeLector Goethe A1 Wortliste',
    fields=[
        {'name': 'Front'},
        {'name': 'Word'},
        {'name': 'Lemma'},
        {'name': 'POS'},
        {'name': 'Plural'},
        {'name': 'Definition'},
        {'name': 'ExampleDe'},
        {'name': 'ExampleZh'},
        {'name': 'Topic'}
    ],
    templates=[{
        'name': 'Goethe A1 Card',
        'qfmt': '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;text-align:center;"><div style="display:inline-block;background:#e0e7ff;color:#3730a3;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:600;margin-bottom:12px;">Goethe A1 · {{Topic}}</div><div style="font-size:26px;font-weight:700;color:#1e293b;margin:12px 0;">{{Front}}</div>{{#Plural}}<div style="font-size:14px;color:#64748b;">Plural: {{Plural}}</div>{{/Plural}}</div>',
        'afmt': '{{FrontSide}}<hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;"><div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:0 24px 24px;text-align:left;"><div style="font-size:18px;font-weight:600;color:#0f172a;margin-bottom:8px;">{{Definition}}</div><div style="font-size:13px;color:#64748b;margin-bottom:16px;">词性: {{POS}}</div><div style="background:#f8fafc;border-left:3px solid #6366f1;padding:10px 14px;border-radius:0 6px 6px 0;"><div style="font-size:15px;color:#1e293b;font-weight:500;">{{ExampleDe}}</div><div style="font-size:13px;color:#64748b;margin-top:4px;">{{ExampleZh}}</div></div></div>'
    }]
)


def export_a1_anki_deck(output_path: str) -> str:
    import a1_dict
    deck = genanki.Deck(1607392321, "DeLector::Goethe A1 Wortliste")
    topic_map = dict((k, label) for k, label, _ in a1_dict.A1_TOPICS)

    for lemma, entry in a1_dict.GOETHE_A1_VOCAB.items():
        word = entry.get("word", lemma)
        topic_label = topic_map.get(entry.get("topic", "personal"), entry.get("topic", "A1"))
        pos = entry.get("pos", "")
        plural = entry.get("plural", "")
        defn = entry.get("definition_zh", "")
        ex_de = entry.get("example_de", "")
        ex_zh = entry.get("example_zh", "")
        gender = entry.get("gender")

        if gender == "Masc":
            color = "#2563eb"
        elif gender == "Fem":
            color = "#dc2626"
        elif gender == "Neut":
            color = "#16a34a"
        else:
            color = "#475569"

        front_html = f'<span style="color:{color};">{word}</span>'
        note = genanki.Note(
            model=A1_VOCAB_MODEL,
            fields=[
                front_html,
                word,
                lemma,
                pos,
                plural,
                defn,
                ex_de,
                ex_zh,
                topic_label,
            ]
        )
        deck.add_note(note)

    genanki.Package(deck).write_to_file(output_path)
    return output_path



def get_cache_info(cache_dir: Optional[str] = None) -> Dict[str, Any]:
    target_dir = cache_dir or AUDIO_CACHE_DIR
    total_size = 0
    count = 0
    if os.path.exists(target_dir):
        for fname in os.listdir(target_dir):
            fpath = os.path.join(target_dir, fname)
            if os.path.isfile(fpath):
                count += 1
                total_size += os.path.getsize(fpath)
    return {
        "file_count": count,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "total_size_bytes": total_size
    }


def prune_audio_cache(max_files: int = 300, cache_dir: Optional[str] = None):
    target_dir = cache_dir or AUDIO_CACHE_DIR
    if not os.path.exists(target_dir):
        return
    files = []
    for fname in os.listdir(target_dir):
        fpath = os.path.join(target_dir, fname)
        if os.path.isfile(fpath):
            files.append((fpath, os.path.getmtime(fpath)))
    if len(files) > max_files:
        files.sort(key=lambda x: x[1])
        for fpath, _ in files[: len(files) - max_files + 30]:
            try:
                os.remove(fpath)
            except Exception:
                pass


BACKUP_FORMAT_VERSION = 2

# app_settings 的**正向**白名单。用白名单而非黑名单：将来新增敏感设置项时，
# 黑名单会默认泄露，白名单会默认安全。DEEPSEEK_API_KEY 绝不在列 ——
# 备份 JSON 是用户会分享、上传、丢进网盘的文件。
BACKUP_SETTINGS_WHITELIST = ("TTS_VOICE", "TTS_RATE", "API_BASE_URL", "API_MODEL")

_SRS_COLUMNS = ("mastered", "mastered_at", "correct_count", "wrong_count",
                "due_date", "interval_days", "ease_factor", "repetition_count")

# 缺列时回落到与建表 DDL 一致的默认值，这样 v1 备份（或手工编辑过的文件）
# 也能被读进来而不是炸掉。
_SRS_DEFAULTS = {"mastered": 0, "mastered_at": None, "correct_count": 0,
                 "wrong_count": 0, "due_date": None, "interval_days": 1,
                 "ease_factor": 2.5, "repetition_count": 0}

_BACKUP_TABLES = {
    "articles": (
        ("id", "title", "source_url", "raw_text", "processed_json", "created_at"),
        {"title": "Untitled", "source_url": "", "raw_text": "", "processed_json": "{}"},
    ),
    "vocab_cards": (
        ("id", "article_id", "word", "lemma", "pos", "gender", "plural", "cefr_level",
         "definition_zh", "sentence_context", "created_at") + _SRS_COLUMNS,
        dict(_SRS_DEFAULTS, word="", lemma="", pos="", gender="", plural="",
             cefr_level="A1", definition_zh="", sentence_context=""),
    ),
    "grammar_cards": (
        ("id", "article_id", "sentence_context", "grammar_name", "cefr_level",
         "explanation_zh", "rule_formula", "examples_zh", "corrected_form", "error_type", "created_at") + _SRS_COLUMNS,
        dict(_SRS_DEFAULTS, sentence_context="", grammar_name="", cefr_level="A1",
             explanation_zh="", rule_formula="", examples_zh="", corrected_form="", error_type=""),
    ),
    "reading_notes": (
        ("id", "article_id", "sentence_id", "selected_text", "color", "note_content", "created_at"),
        {"selected_text": "", "color": "yellow", "note_content": ""},
    ),
    "prep_saved": (
        ("lemma", "praep", "kasus", "saved_at"),
        {"lemma": "", "praep": "", "kasus": "", "saved_at": None},
    ),
    "essays": (
        ("id", "title", "content", "analysis_json", "cefr_level", "error_count", "sentence_count", "created_at", "updated_at"),
        {"title": "", "content": "", "analysis_json": "{}", "cefr_level": "A1", "error_count": 0, "sentence_count": 0},
    ),
    "essay_versions": (
        ("id", "essay_id", "content", "analysis_json", "message", "created_at"),
        {"essay_id": 0, "content": "", "analysis_json": "{}", "message": ""},
    ),
}

_PROGRESS_TABLES = {
    "study_log": (
        ("id", "event_type", "ref_id", "note", "logged_at"),
        {"event_type": "", "note": ""},
    ),
    "quiz_log": (
        ("id", "card_id", "card_type", "mode", "correct", "attempted_at"),
        {"card_type": "vocab", "mode": "", "correct": 0},
    ),
    "daily_summary": (
        ("date", "cards_added", "cards_mastered", "articles_read", "quiz_sessions", "study_minutes"),
        {"cards_added": 0, "cards_mastered": 0, "articles_read": 0,
         "quiz_sessions": 0, "study_minutes": 0},
    ),
}


def _require_localhost(request: Request):
    """敏感接口仅允许本机访问。

    桌面端有意绑 0.0.0.0（start.py 的 get_bind_host，同 Wi-Fi 的手机/平板可读文章），
    但「导出整个数据库」「清空数据库再灌」和「改写 API Key / base_url」从来不该被局域网触达 ——
    后者在改成真覆盖语义后等于「局域网内一个 POST 清空你的数据」或「悄悄改写你的模型网关」。
    读文章期望被共享，备份与设置不期望，所以闸下在端点粒度而不是改绑定地址。

    接受 127.0.0.1、::1、localhost 与等价的 IPv4-mapped 回环 ::ffff:127.0.0.1；
    无法确认来源（client 为 None 或 host 缺失/空）时拒绝，不默认放行。
    """
    host = ""
    if request.client is not None:
        host = getattr(request.client, "host", None) or ""
    if host not in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        raise HTTPException(403, "该接口仅允许本机访问")


def _rows_to_tuples(rows: List[Dict[str, Any]], columns: Tuple[str, ...],
                    defaults: Dict[str, Any]) -> List[Tuple]:
    return [tuple(r.get(c, defaults.get(c)) for c in columns) for r in rows]


def build_backup_payload() -> Dict[str, Any]:
    """组装 v2 备份。local_storage 由前端在 /prepare 时填入——后端读不到浏览器存储。"""
    conn = get_db()
    try:
        tables = {name: [dict(r) for r in conn.execute(f"SELECT * FROM {name}").fetchall()]
                  for name in _BACKUP_TABLES}
        placeholders = ",".join("?" for _ in BACKUP_SETTINGS_WHITELIST)
        settings = [dict(r) for r in conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
            BACKUP_SETTINGS_WHITELIST,
        ).fetchall()]
    finally:
        conn.close()

    pconn = get_progress_db()
    try:
        progress = {name: [dict(r) for r in pconn.execute(f"SELECT * FROM {name}").fetchall()]
                    for name in _PROGRESS_TABLES}
    finally:
        pconn.close()

    return {
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "app_settings": settings,
        "local_storage": {},
        **tables,
        **progress,
    }


# prepare→download 之间的暂存槽。单用户本地服务，一份就够。
# 不落盘：避免在磁盘留下用户全库的明文副本，也免去一套失效时会静默的清理逻辑。
# 可接受的失效模式——用户始终不点下载时，一份 JSON 占内存到进程重启。
_pending_backup: Dict[str, Any] = {"token": None, "payload": None, "filename": None, "expires_at": 0.0}

# ── Workbench backup (同理，Android WebView 对 blob: URL 静默失败) ────────
_pending_wb: Dict[str, Any] = {"token": None, "payload": None, "filename": None, "expires_at": 0.0}

# token 有效期。原来是「单次有效」——端点返回前就把槽位清空，这与 WebView 的
# 真实行为冲突：WebView 为了嗅探 Content-Disposition 会先发一次 GET（这一次就把
# token 烧掉），App 侧再发第二次必然 404，落盘的是一个
# {"detail": "备份链接已失效"} 的错误 JSON。用户拿到一份假备份且全程无报错，
# 比直接报错更糟（v4.7.3 修）。改成 TTL 内可重复取后，两次 GET 都拿到真备份。
BACKUP_TOKEN_TTL_SEC = 600


def _issue_pending(pending: Dict[str, Any], payload: Any, filename: str) -> str:
    """装填暂存槽并返回新 token。同一槽位重复调用会让上一个 token 立即作废。"""
    pending.update(
        token=secrets.token_urlsafe(16),
        payload=payload,
        filename=filename,
        expires_at=time.time() + BACKUP_TOKEN_TTL_SEC,
    )
    return pending["token"]


def _take_pending(pending: Dict[str, Any], token: str) -> Tuple[Any, str]:
    """TTL 内可重复取，取用后**不**清除槽位。

    安全性没有因此下降：端点仍受 _require_localhost 保护（只放行 127.0.0.1/::1），
    token 是 128 位随机值，窗口只有 10 分钟。换来的收益是「同一个 URL 被取两次」
    这种完全正常的行为不再把导出变成一份假备份。
    """
    if not pending["token"] or not secrets.compare_digest(str(token), pending["token"]):
        raise HTTPException(404, "备份链接无效，请重新导出")
    if time.time() > pending.get("expires_at", 0.0):
        pending.update(token=None, payload=None, filename=None, expires_at=0.0)
        raise HTTPException(410, f"备份链接已过期（{BACKUP_TOKEN_TTL_SEC // 60} 分钟），请重新导出")
    return pending["payload"], pending["filename"]


@contextmanager
def _db_snapshot_guard():
    """还原前给两个库做文件级快照，任一步失败就整体拷回。

    delector.db 与 progress.db 是两个**独立** SQLite 文件，无法共处一个事务。
    还原已改成「清库再灌」，所以清空之后、灌完之前若失败（JSON 损坏、磁盘满、
    进程被杀），数据就「已删而备份没进去」——把丢复习进度的 bug 换成丢全部数据的 bug。
    单库事务保护不了跨文件操作，只能在文件层再兜一层。
    """
    paths = [p for p in (get_db_path(), get_progress_db_path()) if os.path.exists(p)]
    tmpdir = tempfile.mkdtemp(prefix="delector_restore_")
    snapshots: Dict[str, str] = {}
    try:
        for p in paths:
            dst = os.path.join(tmpdir, os.path.basename(p))
            shutil.copy2(p, dst)
            snapshots[p] = dst
        yield
    except BaseException:
        # 连 KeyboardInterrupt 也要回滚——半个还原比不还原更糟
        for original, snapshot in snapshots.items():
            try:
                shutil.copy2(snapshot, original)
            except Exception:
                pass
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _replace_tables(conn, spec: Dict[str, Tuple], payload: Dict[str, List[Dict[str, Any]]]):
    for name, (columns, defaults) in spec.items():
        conn.execute(f"DELETE FROM {name}")
        rows = payload.get(name) or []
        if not rows:
            continue
        placeholders = ",".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO {name} ({','.join(columns)}) VALUES ({placeholders})",
            _rows_to_tuples(rows, columns, defaults),
        )


def get_prep_saved(db_path: Optional[str] = None) -> set:
    """返回所有已入卡的 (lemma, praep, kasus) 三元组 key 集合。"""
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT lemma, praep, kasus FROM prep_saved").fetchall()
        return {f"{r['lemma']}|{r['praep']}|{r['kasus']}" for r in rows}


def add_prep_saved(lemma: str, praep: str, kasus: str, db_path: Optional[str] = None):
    """记录一条搭配已入卡。幂等：重复插入被主键忽略。"""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO prep_saved (lemma, praep, kasus) VALUES (?, ?, ?)",
            (lemma, praep, kasus),
        )


__all__ = [
    "DATA_DIR",
    "AUDIO_CACHE_DIR",
    "PROGRESS_DB_PATH",
    "get_db_path",
    "get_progress_db_path",
    "get_db",
    "get_progress_db",
    "init_progress_db",
    "log_study_event",
    "init_db",
    "get_setting",
    "set_setting",
    "get_effective_api_key",
    "get_effective_api_base_url",
    "get_effective_api_model",
    "PRESET_ARTICLES",
    "ingest_article",
    "seed_preset_articles",
    "VOCAB_MODEL",
    "GRAMMAR_MODEL",
    "A1_VOCAB_MODEL",
    "export_anki_deck",
    "export_a1_anki_deck",
    "get_cache_info",
    "prune_audio_cache",
    "BACKUP_FORMAT_VERSION",
    "BACKUP_SETTINGS_WHITELIST",
    "_BACKUP_TABLES",
    "_PROGRESS_TABLES",
    "_require_localhost",
    "_rows_to_tuples",
    "build_backup_payload",
    "_pending_backup",
    "_pending_wb",
    "BACKUP_TOKEN_TTL_SEC",
    "_issue_pending",
    "_take_pending",
    "_db_snapshot_guard",
    "_replace_tables",
    "get_prep_saved",
    "add_prep_saved",
]
