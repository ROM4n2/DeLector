# -*- coding: utf-8 -*-
"""数据库连接、初始化、CRUD、配置存储、音频缓存管理与备份还原底层。"""

import html as _html
import json
import logging
import os
import random
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import genanki
from fastapi import HTTPException, Request

from delector.nlp_engine.processor import process_german_text

# 本文件现在位于 delector/core/database.py（Phase 1 Task 6 搬入 core/）。DATA_DIR
# 必须指向**仓库根**（delector/ 的父目录），不能落到 delector/ 包目录。用「向上走到
# 不再是 Python 包目录（无 __init__.py）」的方式求仓库根，避免硬编码 dirname 层数 ——
# 下次再搬也不会静默指错。delector.db / progress.db 都挂在它下面，指错一级 = 换个地方
# 重建：桌面端没有 DELECTOR_DATA_DIR 兜底（Android 由 MainActivity 注入），用户看到
# "升级之后数据全没了"，本地测试照样全绿。这条语义由
# tests/test_backend_package_layout.py 钉住，别改回去。
_PKG_DIR = os.path.dirname(__file__)
_REPO_ROOT = _PKG_DIR
while os.path.exists(os.path.join(_REPO_ROOT, "__init__.py")):
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", _REPO_ROOT)
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


_INITIALIZED_PROGRESS_DBS: set = set()


def get_progress_db(db_path: Optional[str] = None):
    target_path = get_progress_db_path(db_path)
    if target_path not in _INITIALIZED_PROGRESS_DBS:
        init_progress_db(target_path)
    conn = sqlite3.connect(target_path)
    return _configure_sqlite_conn(conn)


def init_progress_db(db_path: Optional[str] = None):
    target_path = get_progress_db_path(db_path)
    conn = sqlite3.connect(target_path)
    _configure_sqlite_conn(conn)
    try:
        # executescript 支持多语句 DDL（conn.execute 只允许单语句）
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS study_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ref_id INTEGER,
                note TEXT DEFAULT '',
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS quiz_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                card_type TEXT NOT NULL,
                mode TEXT NOT NULL,
                correct INTEGER NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                cards_added INTEGER DEFAULT 0,
                cards_mastered INTEGER DEFAULT 0,
                articles_read INTEGER DEFAULT 0,
                quiz_sessions INTEGER DEFAULT 0,
                study_minutes INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS a1_hoeren_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_id INTEGER NOT NULL,
                score_raw INTEGER NOT NULL,
                score_official REAL NOT NULL,
                total_questions INTEGER NOT NULL,
                duration_seconds INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                wrong_questions_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS a1_lesen_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_id INTEGER NOT NULL,
                score_raw INTEGER NOT NULL,
                score_official REAL NOT NULL,
                total_questions INTEGER NOT NULL,
                duration_seconds INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                wrong_questions_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS exam_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                module TEXT NOT NULL,
                set_id INTEGER NOT NULL,
                score_raw INTEGER NOT NULL,
                score_official REAL NOT NULL,
                total_questions INTEGER NOT NULL,
                duration_seconds INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                wrong_questions_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS corpus_syntax_stats (
                article_id         INTEGER PRIMARY KEY,
                sent_count         INTEGER NOT NULL DEFAULT 0,
                avg_clause_depth   REAL NOT NULL DEFAULT 0.0,
                passive_rate       REAL NOT NULL DEFAULT 0.0,
                konjunktiv_rate    REAL NOT NULL DEFAULT 0.0,
                vl_rate            REAL NOT NULL DEFAULT 0.0,
                analyzed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_quiz_card ON quiz_log(card_id);
            CREATE INDEX IF NOT EXISTS idx_study_logged ON study_log(logged_at);
        """)
    finally:
        # init 阶段不能用 db_progress_conn（会递归回自身自动建表），此处确定关闭
        _close_db_conn(conn)
    _INITIALIZED_PROGRESS_DBS.add(target_path)
    # 泛化成绩表上线即迁移存量 A1 行；函数自身行数对账幂等，重复调用无害
    migrate_a1_records_to_exam_trials(db_path=target_path)


def log_study_event(
    event_type: str,
    ref_id: Optional[int] = None,
    note: str = "",
    minutes: int = 0,
    db_path: Optional[str] = None,
):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        with db_progress_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO study_log (event_type, ref_id, note) VALUES (?, ?, ?)", (event_type, ref_id, note)
            )
            conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
            if event_type == "add_card":
                conn.execute(
                    "UPDATE daily_summary SET cards_added = cards_added + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(1, minutes), today),
                )
            elif event_type == "master_card":
                conn.execute(
                    "UPDATE daily_summary SET cards_mastered = cards_mastered + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(1, minutes), today),
                )
            elif event_type == "read_article":
                conn.execute(
                    "UPDATE daily_summary SET articles_read = articles_read + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(3, minutes), today),
                )
            elif event_type == "quiz_session":
                conn.execute(
                    "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(2, minutes), today),
                )
            elif event_type in ("a1_hoeren", "a1_lesen"):
                conn.execute(
                    "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(2, minutes), today),
                )
    except Exception as e:
        print(f"[Warn] Failed to log study event: {e}")


def init_db(db_path: Optional[str] = None):
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
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
        # Workbench 背词进度 server 镜像：单行表，payload 存整份
        # {words, cards, log, wrong, settings} JSON。单用户无账号，行 id 钉死 1。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wb_state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # 遇见区 i+1 手选分级短文本（阅读域，与 articles 同库同批次）。pack_id 为
        # job#1 import-pack 的来源标识（手工文本为 NULL）；pack_json 存整份
        # encounter-pack/v1 元数据。level 规一（A1/A2/B1 白名单）由 A2 的
        # validate_pack 负责，此处只存输入原值。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS encounter_texts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id TEXT UNIQUE,
                title TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'A2',
                source TEXT DEFAULT '',
                content TEXT NOT NULL,
                pack_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_encounter_level ON encounter_texts(level)")

        # 听力微训工坊会话成绩（Task 3）：本地单用户记录，非敏感不挂闸。
        # created_at 用 TEXT DEFAULT (datetime('now'))，与材料表时间戳形态一致。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listen_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT,
                source_type TEXT,
                source_id INTEGER,
                level TEXT,
                total INTEGER,
                correct INTEGER,
                score REAL,
                duration_sec INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)

        # 长难句精读训练记录（Task 3）：本地单用户记录，非敏感不挂闸（红线 7）。
        # 对齐 listen_trials 模式；source ∈ article/encounter，sentence_index 为句在
        # 材料中的序号，revealed 为是否揭示过句法树（0/1）。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hard_sentence_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                source_id INTEGER,
                sentence_index INTEGER,
                level TEXT,
                score REAL,
                revealed INTEGER,
                duration_sec INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)

        # 读路径查询索引（幂等，旧库启动自动补）：SRS 到期队列 + 文章维度
        # 过滤/级联。缺失时「到期复习」「某文相关卡」「删文连带」在长库全表扫。
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_srs ON vocab_cards(mastered, due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_grammar_srs ON grammar_cards(mastered, due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_article ON vocab_cards(article_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_grammar_article ON grammar_cards(article_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_article ON reading_notes(article_id)")

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
            today_init = datetime.now().strftime("%Y-%m-%d")
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
        with db_conn(db_path) as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if row and row["value"] is not None and row["value"] != "":
                return row["value"]
    except Exception:
        pass
    return os.environ.get(key, default)


def set_setting(key: str, value: str, db_path: Optional[str] = None):
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
            (key, value),
        )


def _close_db_conn(conn):
    """确定性关闭 get_db 打开的连接。

    裸 `with conn`（sqlite3.Connection 自带的上下文管理）只提交/回滚事务并不会
    close：sqlite3.Connection 会因内部 statement 缓存形成引用环，文件句柄要等
    循环 GC 才释放。Windows 上 clean_db 的 os.remove 靠 busy 重试可绕过，但正确
    做法是主动 close，不依赖 GC 时机——`db_conn`/`db_progress_conn` 已经做了。
    """
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def db_conn(db_path: Optional[str] = None):
    """`with db_conn(...) as conn:` —— 语义与旧 `with get_db(...) as conn:` 等价
    （成功 commit / 异常 rollback），但 finally 确定性 close，不再依赖循环 GC。
    """
    conn = get_db(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _close_db_conn(conn)


@contextmanager
def db_progress_conn(db_path: Optional[str] = None):
    """同 db_conn，面向 progress 库。注意 init_progress_db 内部不得使用本函数。"""
    conn = get_progress_db(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _close_db_conn(conn)


def get_wb_state(db_path: Optional[str] = None) -> dict:
    """读 workbench 背词进度 server 镜像；无记录或解析失败一律返回 {}。"""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT payload FROM wb_state WHERE id = 1").fetchone()
    finally:
        _close_db_conn(conn)
    if not row:
        return {}
    try:
        data = json.loads(row["payload"])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_wb_state(payload: dict, db_path: Optional[str] = None) -> str:
    """单行 upsert workbench 背词进度镜像（id 恒为 1），返回本次写入的 updated_at。"""
    updated_at = datetime.now().isoformat()
    text = json.dumps(payload, ensure_ascii=False)
    conn = get_db(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO wb_state (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
            """,
                (text, updated_at),
            )
    finally:
        _close_db_conn(conn)
    return updated_at


def list_encounter_texts(level: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """遇见区短文列表：可选按建议阅读等级过滤，行按 id 倒序（新→旧）。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        if level is not None:
            rows = conn.execute(
                "SELECT * FROM encounter_texts WHERE level = ? ORDER BY id DESC",
                (level,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM encounter_texts ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_encounter_text(text_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 id 取单篇短文；不存在返回 None。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        row = conn.execute("SELECT * FROM encounter_texts WHERE id = ?", (text_id,)).fetchone()
        return dict(row) if row else None


def create_encounter_text(
    title: str,
    level: str,
    source: str,
    content: str,
    pack_id: Optional[str] = None,
    pack_json: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """手工/导入新增一篇短文，返回新行自增 id。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        cur = conn.execute(
            "INSERT INTO encounter_texts (title, level, source, content, pack_id, pack_json) VALUES (?, ?, ?, ?, ?, ?)",
            (title or "", level or "A2", source or "", content or "", pack_id, pack_json),
        )
        return cur.lastrowid


def import_encounter_pack(pack: dict, db_path: Optional[str] = None) -> int:
    """把 job#1 encounter-pack/v1 整包落库为一行短文；幂等。

    契约：pack_id 已存在时直接返回既有行的 id（不新增）。缺必需键
    （schema / pack_id / article{title, raw_text}）抛 ValueError。level 不做
    规一（A2 的 validate_pack 负责），本函数只存包中原值（缺省 'A2'）。
    """
    if not isinstance(pack, dict):
        raise ValueError("import_encounter_pack: pack 必须是 dict")
    article = pack.get("article")
    missing = [k for k in ("schema", "pack_id") if not pack.get(k)]
    if article is None or not isinstance(article, dict):
        missing.append("article")
    if missing:
        raise ValueError("import_encounter_pack: 缺少必需键 " + ", ".join(sorted(set(missing))))
    # 类型收窄（运行时恒真）：上面的守卫已保证 article 是 dict —— None/非 dict 都会被计入
    # missing 并由此抛错。用 assert 而非重构报错分支，是为了保持「多键缺失合并成一条
    # 错误信息」的既有语义。
    assert isinstance(article, dict)
    if not article.get("title") or not article.get("raw_text"):
        raise ValueError("import_encounter_pack: article 需含 title 与 raw_text")

    target_path = get_db_path(db_path)
    pack_id = pack["pack_id"]
    with db_conn(target_path) as conn:
        existing = conn.execute("SELECT id FROM encounter_texts WHERE pack_id = ?", (pack_id,)).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO encounter_texts (pack_id, title, level, content, pack_json) VALUES (?, ?, ?, ?, ?)",
            (
                pack_id,
                article["title"],
                pack.get("estimated_cefr") or "A2",
                article["raw_text"],
                json.dumps(pack, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def get_wb_sync_key(db_path: Optional[str] = None) -> str:
    """workbench server 同步密钥：读 app_settings，缺则生成 32 位 hex 并持久化。

    独立于 DEEPSEEK_API_KEY；单用户自用，明文 header 传输即够。
    幂等：同一库重复调用返回同一把 key（手机从电脑拿一次就能长期用）。
    """
    key = get_setting("wb_sync_key", "", db_path=db_path)
    if not key:
        key = secrets.token_hex(16)
        set_setting("wb_sync_key", key, db_path=db_path)
    return key


def regenerate_wb_sync_key(db_path: Optional[str] = None) -> str:
    """作废旧同步密钥并生成新的一把（= 撤销配对）：旧 key 立即失效。

    持久凭证敢长期有效的前提是「随时能一键作废」：泄露或换设备时重新生成，
    所有仍持旧 key 的端立即 403，必须重新配对。
    """
    key = secrets.token_hex(16)
    set_setting("wb_sync_key", key, db_path=db_path)
    return key


def verify_wb_key(provided: Optional[str], expected: Optional[str]) -> bool:
    """X-WB-Key 恒定时间校验统一入口。

    `secrets.compare_digest` 是恒定时间比较（长度与内容不产生可观测时序差），
    直接 `!=` 会让 key 校验成为时序侧信道。所有使用 X-WB-Key 鉴权的位置
    （wb state PUT / sync 信令 / rtc 信令）都必须走这里，禁止再写裸 `!=`。
    """
    return secrets.compare_digest(str(provided or ""), str(expected or ""))


def get_effective_api_key(db_path: Optional[str] = None) -> str:
    return get_setting("DEEPSEEK_API_KEY", "", db_path=db_path)


def get_effective_api_base_url(db_path: Optional[str] = None) -> str:
    return get_setting("API_BASE_URL", "https://api.deepseek.com", db_path=db_path)


def get_effective_api_model(db_path: Optional[str] = None) -> str:
    return get_setting("API_MODEL", "deepseek-v4-flash", db_path=db_path)


PRESET_ARTICLES = [
    {
        "title": "【A1 入门篇】Hallo Berlin! Mein erster Tag in Deutschland",
        "text": (
            "Guten Tag! Ich heiße Lukas und ich komme aus China. Jetzt wohne ich in Berlin und lerne "
            "Deutsch an einer Sprachschule. Jeden Morgen trinke ich einen Kaffee, esse ein Brötchen "
            "und fahre mit der U-Bahn zum Deutschkurs. Der Unterricht macht viel Spaß. Am Nachmittag "
            "gehe ich in den Supermarkt und kaufe frisches Obst und Brot."
        ),
    },
    {
        "title": "【A2 进阶篇】Eine Reise nach München: Hotel und Freizeit",
        "text": (
            "Letztes Wochenende bin ich mit dem Zug nach München gefahren. Ich habe ein kleines "
            "Zimmer im Stadtzentrum reserviert. Das Wetter war sehr schön, deshalb habe ich den "
            "ganzen Nachmittag im Englischen Garten verbracht. Am Abend habe ich typische bayerische "
            "Spezialitäten in einem traditionellen Restaurant probiert."
        ),
    },
    {
        "title": "【B1 提升篇】Klimaschutz im Alltag: Was jeder tun kann",
        "text": (
            "Der Klimawandel ist eine der größten Herausforderungen unserer Zeit. Viele Menschen "
            "fragen sich, wie sie im Alltag einen Beitrag zum Umweltschutz leisten können. Experten "
            "empfehlen, öfter auf das Fahrrad umzusteigen und Energie im Haushalt zu sparen. Eine "
            "bewusste Ernährung mit regionalen Lebensmitteln spielt ebenfalls eine wichtige Rolle."
        ),
    },
    {
        "title": "【B2 高级篇】Die Transformation der modernen Arbeitswelt: Homeoffice",
        "text": (
            "Die fortschreitende Digitalisierung hat die Arbeitsbedingungen grundlegend verändert. "
            "Immer mehr Unternehmen stellen ihren Mitarbeitern flexible Arbeitszeitmodelle zur "
            "Verfügung. Obwohl das Arbeiten von zu Hause aus die Vereinbarkeit von Beruf und Familie "
            "erleichtert, stehen viele Beschäftigte vor der Herausforderung, klare Grenzen zwischen "
            "Arbeit und Freizeit zu ziehen."
        ),
    },
]


def ingest_article(title: str, text: str, db_path: Optional[str] = None, source_url: Optional[str] = None) -> int:
    processed = process_german_text(text)
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json, source_url) VALUES (?, ?, ?, ?)",
            (title or "Untitled", text, json.dumps(processed, ensure_ascii=False), source_url or ""),
        )
        return cur.lastrowid


def seed_preset_articles(db_path: Optional[str] = None):
    target = get_db_path(db_path)
    with db_conn(target) as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count == 0:
            for art in PRESET_ARTICLES:
                ingest_article(art["title"], art["text"], db_path=target)


def seed_preset_encounter_texts(db_path: Optional[str] = None) -> int:
    """把预置遇见区卡包（encounter-pack/v1）灌入空库；返回本次实际导入的行数。

    幂等与守卫（三重，缺一不可）
    ---------------------------
    1. **空库守卫**：先数 `encounter_texts` 行数，`count == 0` 才导入；非空库直接
       返回 0，**绝不动用户已有内容**（预置内容只是「首次启动的默认供给」，不是
       每次启动都要补齐的资材）。
    2. **逐包幂等**：逐包走既有 `import_encounter_pack`（按 `pack_id` 去重），
       不自己写 INSERT —— 即便守卫被绕过，第二次调用也不会插入重复行。
    3. **逐包异常隔离**：单包导入失败不得让整个启动崩（离线数据损坏/约束冲突
       时仍要起得来）。失败包记录到日志并计入 `failed`，**绝不静默吞掉**导致
       数据半残而无从观测：有失败即 `logging.error` 汇总，返回值 = 成功导入行数
       （失败数与包总数可从日志与「返回值 < 包数」推知）。

    为何不进 `init_db()`
    -------------------
    既有契约测试（`tests/test_encounter_routes.py::test_get_list_empty` 等 6 条）
    把「空库 = 空列表」钉成遇见区的**空态语义**；测试夹具调用 `init_db()` 建库，
    若 seed 塞进 `init_db`，这些用例会集体由「空」变「含 4 篇」而变红，语义被
    削弱为「包含」。预置内容属**产品默认内容**而非 schema 事务，schema 建表
    （`init_db`）与默认内容供给（`create_app`）必须分权：由唯一的生产装配入口
    `create_app()` 在 `seed_preset_articles()` 之后调用本函数。
    """
    # 延迟导入：数据模块只应在真正 seed 时被拉起（导入期零副作用，项目红线 9）。
    from delector.data.encounter_seed_dict import PRESET_ENCOUNTER_PACKS

    target = get_db_path(db_path)
    with db_conn(target) as conn:
        count = conn.execute("SELECT COUNT(*) FROM encounter_texts").fetchone()[0]
    if count != 0:
        return 0

    imported = 0
    failed = 0
    for pack in PRESET_ENCOUNTER_PACKS:
        try:
            import_encounter_pack(pack, db_path=target)
            imported += 1
        except Exception as exc:  # noqa: BLE001 —— 单包失败不得崩启动
            failed += 1
            logging.error(
                "seed_preset_encounter_texts: 预置包导入失败 pack_id=%r: %r",
                (pack or {}).get("pack_id"),
                exc,
            )
    if failed:
        logging.error(
            "seed_preset_encounter_texts: %d/%d 预置包导入失败（成功 %d）",
            failed,
            len(PRESET_ENCOUNTER_PACKS),
            imported,
        )
    return imported


VOCAB_MODEL = genanki.Model(
    1607392319,
    "DeLector Vocab",
    fields=[{"name": "Front"}, {"name": "Word"}, {"name": "Lemma"}, {"name": "Meta"}, {"name": "Definition"}],
    templates=[
        {
            "name": "Card",
            "qfmt": '<div style="font-family:sans-serif;font-size:20px;padding:20px;">{{Front}}</div>',
            "afmt": (
                '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;'
                'color:#1e293b;"><b>{{Definition}}</b><br><span style="color:#64748b;font-size:14px;">'
                "{{Lemma}} ({{Meta}})</span></div>"
            ),
        }
    ],
)

GRAMMAR_MODEL = genanki.Model(
    1607392320,
    "DeLector Goethe Grammar",
    fields=[
        {"name": "Sentence"},
        {"name": "GrammarName"},
        {"name": "CEFR"},
        {"name": "Explanation"},
        {"name": "Formula"},
    ],
    templates=[
        {
            "name": "Card",
            "qfmt": (
                '<div style="font-family:sans-serif;font-size:20px;padding:20px;">'
                '<span style="background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:99px;'
                'font-size:12px;">Goethe {{CEFR}}</span><br><br>{{Sentence}}</div>'
            ),
            "afmt": (
                '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;">'
                '<b>{{GrammarName}}</b><br><code style="background:#f1f5f9;color:#0369a1;'
                'padding:4px 8px;">{{Formula}}</code><p style="color:#334155;">{{Explanation}}</p></div>'
            ),
        }
    ],
)


def _anki_esc(value) -> str:
    """用户/可编辑数据进 Anki HTML 字段前一律转义。

    genanki 不自动转义，裸标签（如 `<img onerror>`）在 Anki 打开牌组时会执行，
    是存储型 XSS。quote=True 一并转义引号，防 attribute 注入。
    """
    return _html.escape(str(value or ""), quote=True)


def _vocab_anki_note(r) -> genanki.Note:
    """构造词汇卡 note：先转义再高亮替换，顺序不可颠倒（先转义否则破坏 <b> 结构）。"""
    word = _anki_esc(r["word"])
    sentence = _anki_esc(r["sentence_context"])
    styled_front = sentence.replace(word, f'<b style="color:#2563eb;">{word}</b>')
    meta = f"{_anki_esc(r['pos'])} · {_anki_esc(r['gender'] or '')} · {_anki_esc(r['cefr_level'])}"
    return genanki.Note(
        model=VOCAB_MODEL,
        fields=[
            styled_front,
            word,
            _anki_esc(r["lemma"]),
            meta,
            _anki_esc(r["definition_zh"]),
        ],
    )


def _grammar_anki_note(r) -> genanki.Note:
    """构造语法卡 note：五个模板字段全部来自句库/卡片数据，逐字段转义。"""
    return genanki.Note(
        model=GRAMMAR_MODEL,
        fields=[
            _anki_esc(r["sentence_context"]),
            _anki_esc(r["grammar_name"]),
            _anki_esc(r["cefr_level"]),
            _anki_esc(r["explanation_zh"]),
            _anki_esc(r["rule_formula"] or ""),
        ],
    )


def export_anki_deck(output_path: str, db_path: Optional[str] = None) -> str:
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        vocab_rows = conn.execute("SELECT * FROM vocab_cards").fetchall()
        grammar_rows = conn.execute("SELECT * FROM grammar_cards").fetchall()

    deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), "DeLector::Goethe Deck")
    for r in vocab_rows:
        deck.add_note(_vocab_anki_note(r))
    for r in grammar_rows:
        deck.add_note(_grammar_anki_note(r))

    genanki.Package(deck).write_to_file(output_path)
    return output_path


A1_VOCAB_MODEL = genanki.Model(
    1607392321,
    "DeLector Goethe A1 Wortliste",
    fields=[
        {"name": "Front"},
        {"name": "Word"},
        {"name": "Lemma"},
        {"name": "POS"},
        {"name": "Plural"},
        {"name": "Definition"},
        {"name": "ExampleDe"},
        {"name": "ExampleZh"},
        {"name": "Topic"},
    ],
    templates=[
        {
            "name": "Goethe A1 Card",
            "qfmt": (
                '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;'
                'text-align:center;"><div style="display:inline-block;background:#e0e7ff;color:#3730a3;'
                'padding:3px 10px;border-radius:99px;font-size:12px;font-weight:600;margin-bottom:12px;">'
                'Goethe A1 · {{Topic}}</div><div style="font-size:26px;font-weight:700;color:#1e293b;'
                'margin:12px 0;">{{Front}}</div>{{#Plural}}<div style="font-size:14px;color:#64748b;">'
                "Plural: {{Plural}}</div>{{/Plural}}</div>"
            ),
            "afmt": (
                '{{FrontSide}}<hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">'
                '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
                'padding:0 24px 24px;text-align:left;"><div style="font-size:18px;font-weight:600;'
                'color:#0f172a;margin-bottom:8px;">{{Definition}}</div><div style="font-size:13px;'
                'color:#64748b;margin-bottom:16px;">词性: {{POS}}</div><div style="background:#f8fafc;'
                'border-left:3px solid #6366f1;padding:10px 14px;border-radius:0 6px 6px 0;">'
                '<div style="font-size:15px;color:#1e293b;font-weight:500;">{{ExampleDe}}</div>'
                '<div style="font-size:13px;color:#64748b;margin-top:4px;">{{ExampleZh}}</div></div></div>'
            ),
        }
    ],
)


def export_a1_anki_deck(output_path: str) -> str:
    from delector.data import a1_dict

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

        word_esc = _anki_esc(word)
        front_html = f'<span style="color:{color};">{word_esc}</span>'
        note = genanki.Note(
            model=A1_VOCAB_MODEL,
            fields=[
                front_html,
                word_esc,
                _anki_esc(lemma),
                _anki_esc(pos),
                _anki_esc(plural),
                _anki_esc(defn),
                _anki_esc(ex_de),
                _anki_esc(ex_zh),
                _anki_esc(topic_label),
            ],
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
    return {"file_count": count, "total_size_mb": round(total_size / (1024 * 1024), 2), "total_size_bytes": total_size}


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
#
# 导出/还原白名单刻意**拆成两份**：
# - 导出（BACKUP_SETTINGS_WHITELIST / BACKUP_SETTINGS_EXPORT_WHITELIST）保留
#   API_BASE_URL/API_MODEL —— 它们不是机密，导出带上是正常的设备间配置迁移。
# - 还原（BACKUP_SETTINGS_IMPORT_WHITELIST）**只允许 TTS_***：API_BASE_URL 若从
#   恶意备份导入，会把库里真实 DEEPSEEK_API_KEY 的下一次 AI 调用（带 Bearer 头）
#   指向攻击者服务器 → 密钥外泄。还原时这两项一律保留本机现值。
BACKUP_SETTINGS_WHITELIST = ("TTS_VOICE", "TTS_RATE", "API_BASE_URL", "API_MODEL")
BACKUP_SETTINGS_EXPORT_WHITELIST = BACKUP_SETTINGS_WHITELIST
BACKUP_SETTINGS_IMPORT_WHITELIST = ("TTS_VOICE", "TTS_RATE")

_SRS_COLUMNS = (
    "mastered",
    "mastered_at",
    "correct_count",
    "wrong_count",
    "due_date",
    "interval_days",
    "ease_factor",
    "repetition_count",
)

# 缺列时回落到与建表 DDL 一致的默认值，这样 v1 备份（或手工编辑过的文件）
# 也能被读进来而不是炸掉。
_SRS_DEFAULTS = {
    "mastered": 0,
    "mastered_at": None,
    "correct_count": 0,
    "wrong_count": 0,
    "due_date": None,
    "interval_days": 1,
    "ease_factor": 2.5,
    "repetition_count": 0,
}

_BACKUP_TABLES = {
    "articles": (
        ("id", "title", "source_url", "raw_text", "processed_json", "created_at"),
        {"title": "Untitled", "source_url": "", "raw_text": "", "processed_json": "{}"},
    ),
    "vocab_cards": (
        (
            "id",
            "article_id",
            "word",
            "lemma",
            "pos",
            "gender",
            "plural",
            "cefr_level",
            "definition_zh",
            "sentence_context",
            "created_at",
        )
        + _SRS_COLUMNS,
        dict(
            _SRS_DEFAULTS,
            word="",
            lemma="",
            pos="",
            gender="",
            plural="",
            cefr_level="A1",
            definition_zh="",
            sentence_context="",
        ),
    ),
    "grammar_cards": (
        (
            "id",
            "article_id",
            "sentence_context",
            "grammar_name",
            "cefr_level",
            "explanation_zh",
            "rule_formula",
            "examples_zh",
            "corrected_form",
            "error_type",
            "created_at",
        )
        + _SRS_COLUMNS,
        dict(
            _SRS_DEFAULTS,
            sentence_context="",
            grammar_name="",
            cefr_level="A1",
            explanation_zh="",
            rule_formula="",
            examples_zh="",
            corrected_form="",
            error_type="",
        ),
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
        (
            "id",
            "title",
            "content",
            "analysis_json",
            "cefr_level",
            "error_count",
            "sentence_count",
            "created_at",
            "updated_at",
        ),
        {"title": "", "content": "", "analysis_json": "{}", "cefr_level": "A1", "error_count": 0, "sentence_count": 0},
    ),
    "essay_versions": (
        ("id", "essay_id", "content", "analysis_json", "message", "created_at"),
        {"essay_id": 0, "content": "", "analysis_json": "{}", "message": ""},
    ),
    # 遇见区短文（Task A1 起入同库）；pack_json 存整份 encounter-pack/v1 元数据。
    # 备份/还原缺失该表会让换机还原后遇见区全丢（vault-team 评审 ②）。
    "encounter_texts": (
        ("id", "pack_id", "title", "level", "source", "content", "pack_json", "created_at"),
        {"pack_id": None, "title": "", "level": "A2", "source": "", "content": "", "pack_json": None},
    ),
    # 听力微训成绩（Task 3）：备份/还原缺失该表会让换机还原后听力记录全丢。
    "listen_trials": (
        (
            "id",
            "mode",
            "source_type",
            "source_id",
            "level",
            "total",
            "correct",
            "score",
            "duration_sec",
            "created_at",
        ),
        {
            "mode": "",
            "source_type": "",
            "source_id": 0,
            "level": "",
            "total": 0,
            "correct": 0,
            "score": 0.0,
            "duration_sec": 0,
        },
    ),
    # 长难句精读训练记录（Task 3）：备份/还原缺失该表会让换机还原后训练记录全丢。
    "hard_sentence_trials": (
        (
            "id",
            "source",
            "source_id",
            "sentence_index",
            "level",
            "score",
            "revealed",
            "duration_sec",
            "created_at",
        ),
        {
            "source": "",
            "source_id": 0,
            "sentence_index": 0,
            "level": "",
            "score": 0.0,
            "revealed": 0,
            "duration_sec": 0,
        },
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
        {"cards_added": 0, "cards_mastered": 0, "articles_read": 0, "quiz_sessions": 0, "study_minutes": 0},
    ),
    "a1_hoeren_records": (
        (
            "id",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
    ),
    "a1_lesen_records": (
        (
            "id",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
    ),
    "exam_trials": (
        (
            "id",
            "level",
            "module",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "level": "A1",
            "module": "hoeren",
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
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


def _rows_to_tuples(rows: List[Dict[str, Any]], columns: Tuple[str, ...], defaults: Dict[str, Any]) -> List[Tuple]:
    return [tuple(r.get(c, defaults.get(c)) for c in columns) for r in rows]


def build_backup_payload() -> Dict[str, Any]:
    """组装 v2 备份。local_storage 由前端在 /prepare 时填入——后端读不到浏览器存储。"""
    conn = get_db()
    try:
        tables = {name: [dict(r) for r in conn.execute(f"SELECT * FROM {name}").fetchall()] for name in _BACKUP_TABLES}
        placeholders = ",".join("?" for _ in BACKUP_SETTINGS_WHITELIST)
        settings = [
            dict(r)
            for r in conn.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                BACKUP_SETTINGS_WHITELIST,
            ).fetchall()
        ]
    finally:
        conn.close()

    pconn = get_progress_db()
    try:
        progress = {
            name: [dict(r) for r in pconn.execute(f"SELECT * FROM {name}").fetchall()] for name in _PROGRESS_TABLES
        }
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
    with db_conn(db_path) as conn:
        rows = conn.execute("SELECT lemma, praep, kasus FROM prep_saved").fetchall()
        return {f"{r['lemma']}|{r['praep']}|{r['kasus']}" for r in rows}


def add_prep_saved(lemma: str, praep: str, kasus: str, db_path: Optional[str] = None):
    """记录一条搭配已入卡。幂等：重复插入被主键忽略。"""
    with db_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO prep_saved (lemma, praep, kasus) VALUES (?, ?, ?)",
            (lemma, praep, kasus),
        )


def record_exam_trial(
    level: str,
    module: str,
    set_id: int,
    score_raw: int,
    score_official: float,
    total_questions: int,
    duration_seconds: int,
    answers_json: str,
    wrong_questions_json: str,
    db_path: Optional[str] = None,
) -> int:
    """写入一次泛化模考成绩（exam_trials：level × module 维度）。

    与旧 A1 专用表不同，同一张表承载所有等级/模块（A1 听力、A1 阅读，
    未来 A2…），备份/restore 也在同一张表上通用。
    """
    with db_progress_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO exam_trials (
                level, module, set_id, score_raw, score_official,
                total_questions, duration_seconds, answers_json, wrong_questions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                level,
                module,
                set_id,
                score_raw,
                score_official,
                total_questions,
                duration_seconds,
                answers_json,
                wrong_questions_json,
            ),
        )
        record_id = cur.lastrowid
    # log_study_event opens its own connection — must be OUTSIDE the with block
    # to avoid SQLITE_BUSY from nested locks on progress.db.
    # A1 双模块沿用旧 event_type（test_a1_grade_populates_study_log 契约）；
    # 其余组合的 daily_summary 映射留待 Phase 2 端点切换时扩展。
    if level == "A1":
        event_type = "a1_hoeren" if module == "hoeren" else "a1_lesen"
    else:
        event_type = f"{level.lower()}_{module}"
    log_study_event(
        event_type,
        ref_id=record_id,
        note=f"Set {set_id}: {score_official}/25.0",
        minutes=max(1, duration_seconds // 60),
        db_path=db_path,
    )
    return record_id


def get_exam_history(level: str, module: str, limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询泛化模考历史；返回结构与旧 get_a1_*_history 逐字段等价。

    显式投影 9 个旧列而非 SELECT *：表里多出的 level/module 是存储维度，
    不是 API 字段——透传契约下调用方（routes_a1_*）不应看到它们。
    """
    with db_progress_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, set_id, score_raw, score_official, total_questions,
                   duration_seconds, answers_json, wrong_questions_json, created_at
            FROM exam_trials
            WHERE level = ? AND module = ?
            ORDER BY id DESC LIMIT ?
        """,
            (level, module, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def migrate_a1_records_to_exam_trials(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """把 a1_hoeren_records / a1_lesen_records 存量行迁入 exam_trials(level='A1')。

    幂等策略是**行数对账**：对每个 module，若 exam_trials 里该 (level='A1',
    module) 的行数 **≥** 旧表行数则整个跳过——重复执行零副作用。

    为什么用 ≥ 而不是 ==：旧表在迁移后冻结（透传模式只写 exam_trials），
    legacy_count 恒定，而 exam_trials 随每次新成绩提交单调增。若用 ==，
    「迁移后又做了一次新成绩」再重启时 general=legacy+1 ≠ legacy 会误判为
    「未迁移」，把旧表整行再插一遍 → 重复。≥ 在「旧表冻结 + 新表单调增」下
    天然满足：一次迁入后 general ≥ legacy 恒成立，永不再迁。

    原子性：db_progress_conn 单事务，迁移中途异常整体回滚，不会留下半迁状
    态；重跑从 0 迁，无剩余行。故 ≥ 对「迁移中断」也安全。

    旧表本身保留不删，读历史兼容期后由 Phase 2 退役。

    Returns: {"hoeren": {"migrated": n, "skipped": bool}, "lesen": {...}}
    """
    report: Dict[str, Dict[str, Any]] = {}
    sources = {
        "hoeren": "a1_hoeren_records",
        "lesen": "a1_lesen_records",
    }
    with db_progress_conn(db_path) as conn:
        for module, table in sources.items():
            legacy_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            general_count = conn.execute(
                "SELECT COUNT(*) FROM exam_trials WHERE level = ? AND module = ?", ("A1", module)
            ).fetchone()[0]
            if general_count >= legacy_count:
                report[module] = {"migrated": 0, "skipped": True}
                continue
            conn.execute(
                f"""
                INSERT INTO exam_trials (
                    level, module, set_id, score_raw, score_official,
                    total_questions, duration_seconds, answers_json,
                    wrong_questions_json, created_at
                )
                SELECT 'A1', ?, set_id, score_raw, score_official, total_questions,
                       duration_seconds, answers_json, wrong_questions_json, created_at
                FROM {table}
            """,
                (module,),
            )
            report[module] = {"migrated": legacy_count, "skipped": False}
    return report


def record_a1_hoeren_trial(
    set_id: int,
    score_raw: int,
    score_official: float,
    total_questions: int,
    duration_seconds: int,
    answers_json: str,
    wrong_questions_json: str,
    db_path: Optional[str] = None,
) -> int:
    """持久化一次 A1 听力模考记录

    透传泛化实现（exam_trials level='A1' module='hoeren'）：签名与返回
    结构不变，调用方零改动；旧行由 migrate_a1_records_to_exam_trials 迁入。
    """
    return record_exam_trial(
        "A1",
        "hoeren",
        set_id,
        score_raw,
        score_official,
        total_questions,
        duration_seconds,
        answers_json,
        wrong_questions_json,
        db_path=db_path,
    )


def get_a1_hoeren_history(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询 A1 听力模考历史记录（透传泛化实现，返回结构不变）"""
    return get_exam_history("A1", "hoeren", limit=limit, db_path=db_path)


def record_a1_lesen_trial(
    set_id: int,
    score_raw: int,
    score_official: float,
    total_questions: int,
    duration_seconds: int,
    answers_json: str,
    wrong_questions_json: str,
    db_path: Optional[str] = None,
) -> int:
    """持久化一次 A1 阅读模考记录（透传泛化实现，签名与返回结构不变）"""
    return record_exam_trial(
        "A1",
        "lesen",
        set_id,
        score_raw,
        score_official,
        total_questions,
        duration_seconds,
        answers_json,
        wrong_questions_json,
        db_path=db_path,
    )


def get_a1_lesen_history(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询 A1 阅读模考历史记录（透传泛化实现，返回结构不变）"""
    return get_exam_history("A1", "lesen", limit=limit, db_path=db_path)


def record_listen_trial(
    mode: str,
    source_type: str,
    source_id: int,
    level: str,
    total: int,
    correct: int,
    score: float,
    duration_sec: int,
    db_path: Optional[str] = None,
) -> int:
    """写入一次听力微训会话成绩（listen_trials，主库），返回新行 id。

    本地单用户成绩记录，非敏感数据，不参与 _require_localhost 闸。
    score 由调用方按 correct/total 计算传入（total 为 0 时取 0）。
    """
    with db_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO listen_trials (
                mode, source_type, source_id, level, total, correct, score, duration_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (mode, source_type, source_id, level, total, correct, score, duration_sec),
        )
        return cur.lastrowid


def list_listen_trials(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询听力微训历史；created_at 倒序（同秒以 id 倒序打平），limit 钳制在 1..100。"""
    with db_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM listen_trials
            ORDER BY created_at DESC, id DESC LIMIT ?
        """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(r) for r in rows]


def record_hard_sentence_trial(
    source: str,
    source_id: int,
    sentence_index: int,
    level: str,
    score: float,
    revealed: int,
    duration_sec: int,
    db_path: Optional[str] = None,
) -> int:
    """写入一次长难句精读训练记录（hard_sentence_trials，主库），返回新行 id。

    本地单用户训练记录，非敏感数据，不参与 _require_localhost 闸（红线 7）。
    对齐 listen_trials 模式；score/level/revealed 由调用方（前端会话汇总）传入。
    """
    with db_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO hard_sentence_trials (
                source, source_id, sentence_index, level, score, revealed, duration_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (source, source_id, sentence_index, level, score, revealed, duration_sec),
        )
        return cur.lastrowid


def list_hard_sentence_trials(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """查询长难句精读训练历史；created_at 倒序（同秒以 id 倒序打平），limit 钳制在 1..100。"""
    with db_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM hard_sentence_trials
            ORDER BY created_at DESC, id DESC LIMIT ?
        """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(r) for r in rows]


_A1_WORKBENCH_WORDS_CACHE: Optional[List[Dict[str, Any]]] = None
_A2_VOCAB_CACHE: Optional[List[Dict[str, Any]]] = None

# A1 名词元数据补全（S7 / ADR-0012 §4-4 派生）：seed 的 ``hw`` 归一化后到主干视图
# ``lexicon.A1_LEMMA_META`` join gender / plural。冠词剥离集合（仅剥离**首个词**）。
_A1_ARTICLE_PREFIXES = ("der", "die", "das", "den", "dem", "des", "ein", "eine")


def _normalize_a1_headword(hw: str) -> str:
    """把 A1 seed 的 ``hw`` 归一化为可 join ``lexicon`` 的 lemma 键。

    规则（严格顺序）：小写 → 剥首个词冠词（``der/die/das/den/dem/des/ein/eine``）
    → 去除括号内容（如 ``(sich)`` / ``(pl.)``）→ 取**逗号前**首段 → 去尾 ``-``
    → 去首尾空白。例：``die Adresse,-en``→``adresse``；``der Apfel, -Ä``→``apfel``；
    ``(sich) anmelden``→``anmelden``；``zum Beispiel/z. B.``→``zum beispiel/z. b.``。

    纯函数、只读入参（不触碰任何全局状态）。
    """
    s = (hw or "").strip().lower()
    parts = s.split(None, 1)  # 仅按首个空白切一次：剥「首个词」冠词
    if parts and parts[0] in _A1_ARTICLE_PREFIXES:
        s = parts[1] if len(parts) > 1 else ""
    s = re.sub(r"\([^)]*\)", "", s)  # 去括号内容，如 (sich) / (pl.)
    s = s.split(",", 1)[0]  # 取逗号前首段（逗号后是复数/变音标记）
    s = s.rstrip("-")  # 去尾 '-'，如 all- / ander-
    return s.strip()


def _a1_noun_meta(hw: str) -> Tuple[Optional[str], str]:
    """归一化 ``hw`` → join ``lexicon.A1_LEMMA_META`` → 返回 ``(gender, plural)``。

    A1 名词元数据的唯一真相来自**主干 LEXICON**（``lexicon.A1_LEMMA_META`` 是其只读薄封装，
    ``{"gender", "plural"}`` 直取主干 5 元组 ``v[2]`` / ``v[3]``）——两端格式同构，
    故本层**直接取用**（唯一的规约化：主干以字面量 ``"None"`` 表示「无性别 / 无复数」，
    与 ``_contract_from_core_entry`` 同规约，须归一化为 ``None`` / ``""``）：

    - gender = ``meta["gender"]``（``Masc/Fem/Neut/Plur``；``"None"`` / 缺 → ``None``）；
    - plural = ``meta["plural"]``（后缀标记，如 ``"-en"`` / ``"-.."`` / ``"-"``；
      ``"None"`` / 缺 → ``""``）。

    未命中（lemma 不在主干 LEXICON）→ ``(None, "")``，**绝不编造**。

    惰性导入主干视图（与 ``_contract_from_core_entry`` 的 ``rich_of`` 同策略，
    导入期零副作用）；主干缺失 = 打包损坏，直接 ImportError 炸出（红线 2）。
    """
    from delector.core.lexicon import a1_lemma_meta_of

    lemma = _normalize_a1_headword(hw)
    if not lemma:
        return None, ""
    meta = a1_lemma_meta_of(lemma)
    if meta is None:
        return None, ""
    # 与 _contract_from_core_entry 同规约：主干非名词条目（PRON/ADJ 等）以字面量 "None"
    # 表示无性别 / 无复数（842 条），契约层须归一化，禁止把字符串 "None" 泄漏进契约。
    gender = meta.get("gender")
    plural = meta.get("plural")
    if gender == "None":
        gender = None
    if plural in (None, "None"):
        plural = ""
    return gender, plural


def _a1_workbench_row(w: Dict[str, Any], core: bool) -> Dict[str, Any]:
    """把数据模块的一条 A1 词条映射为内部行
    {id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr, letter}。

    de/zh 派生规则与改造前逐字相同（ADR-0011：输出逐条不变，除新增字段）：
    de = (ex and ex[0].de) or de or ""；zh = gloss or zh or (ex and ex[0].zh) or ""。
    新增字段（S3，供契约 9 → 11）：
    ipa = w.ipa or ""（seed 逐条带音标）；example_zh = ex[0].zh or ""（种子 682/682 全覆盖）。
    新增字段（S7，A1 卡片补齐）：gender/plural 由 ``hw`` 归一化后 join
    ``lexicon.A1_LEMMA_META``（源 = 主干 LEXICON，格式同构）**直取**（见 ``_a1_noun_meta``）；
    未命中 → None/""（不编造）。
    新增字段（S1，ADR-0014 §6-S1）：letter = w.letter or "" —— **seed 原值逐字透传，
    绝不派生**（前端 letterOf 派生会在 10 条上与内联 seed 值漂移，导致字母分组静默错位）。
    """
    ex = w.get("ex")
    gender, plural = _a1_noun_meta(w.get("hw", ""))
    return {
        "id": w.get("id", ""),
        "hw": w.get("hw", ""),
        "pos": w.get("pos", ""),
        "gender": gender,
        "plural": plural,
        "de": (ex and ex[0].get("de")) or w.get("de") or "",
        "zh": w.get("gloss") or w.get("zh") or (ex and ex[0].get("zh")) or "",
        "ipa": w.get("ipa") or "",
        "example_zh": (ex and ex[0].get("zh")) or "",
        "core": core,
        "cefr": "A1",
        "letter": w.get("letter") or "",
    }


def _load_a1_workbench_dict_module() -> Any:
    """导入 A1 词库数据模块（单一真相）；缺失即抛清晰异常，绝不静默回退（ADR-0011 红线 2）。"""
    try:
        import delector.data.a1_workbench_dict as a1_wb
    except ImportError as exc:
        raise RuntimeError(
            "A1 词库数据模块 delector.data.a1_workbench_dict 导入失败：它是 A1 工作台词库"
            "的单一真相，缺失说明安装/打包不完整。禁止静默回退（ADR-0011 红线 2）。"
        ) from exc
    return a1_wb


def _load_a1_workbench_words() -> List[Dict[str, Any]]:
    """加载并缓存 A1 词库（单一真相 = delector.data.a1_workbench_dict 数据模块）。"""
    global _A1_WORKBENCH_WORDS_CACHE
    if _A1_WORKBENCH_WORDS_CACHE is not None:
        return _A1_WORKBENCH_WORDS_CACHE

    a1_wb = _load_a1_workbench_dict_module()
    seeds = a1_wb.A1_WORKBENCH_SEED
    customs = a1_wb.A1_WORKBENCH_CUSTOM
    core_ids = a1_wb.A1_WORKBENCH_CORE_IDS
    if not isinstance(seeds, list) or not isinstance(customs, list):
        raise TypeError(
            "a1_workbench_dict 形状损坏：A1_WORKBENCH_SEED / A1_WORKBENCH_CUSTOM "
            "必须是 List，实际 %s / %s" % (type(seeds).__name__, type(customs).__name__)
        )
    if not isinstance(core_ids, (set, frozenset)):
        raise TypeError(
            "a1_workbench_dict 形状损坏：A1_WORKBENCH_CORE_IDS 必须是 Set/FrozenSet，"
            "实际 %s" % type(core_ids).__name__
        )

    words = [_a1_workbench_row(w, w.get("id", "") in core_ids) for w in seeds]
    words.extend(_a1_workbench_row(w, True) for w in customs)
    _A1_WORKBENCH_WORDS_CACHE = words
    return words


def _reset_a1_workbench_cache() -> None:
    """清空 A1 词库缓存（测试在 monkeypatch 数据模块常量后用它重置，保证可测试性）。"""
    global _A1_WORKBENCH_WORDS_CACHE
    _A1_WORKBENCH_WORDS_CACHE = None


GENDER_ARTICLE_MAP: Dict[str, str] = {
    "Masc": "der",
    "Fem": "die",
    "Neut": "das",
}


def format_vocab_headword(lemma: str, pos: str, gender: Optional[str] = None) -> str:
    """对德语词条进行规范化展示格式拼装。
    名词首字母大写并前缀定冠词 (如 'das Abenteuer')；动词/形容词等保持小写。
    """
    if not lemma:
        return ""
    pos_upper = (pos or "").upper()
    if pos_upper == "NOUN" and gender in GENDER_ARTICLE_MAP:
        art = GENDER_ARTICLE_MAP[gender]
        cap_lemma = lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
        return f"{art} {cap_lemma}"
    elif pos_upper == "NOUN":
        return lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
    return lemma.lower()


# ── 词对象契约统一（ADR-0011 决策 2，仅作用输出侧；存储 5 元组 schema 冻结 §5-#6）──


def _contract_item(
    vocab_id: str,
    hw: str,
    pos: str,
    gender: Optional[str],
    plural: str,
    de: str,
    zh: str,
    ipa: str,
    example_zh: str,
    core: bool,
    cefr: str,
    letter: str,
) -> Dict[str, Any]:
    """「存储视图 → 契约条目」的唯一映射点：所有分支产出同一 **12 字段**集
    ``{id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr, letter}``，
    缺失字段显式空值（ADR-0013 §4-1：契约 9 → 11；ADR-0014 §6-S1：契约 11 → 12）。

    - ``de`` 语义 = **德语例句**；``zh`` = 中文释义；``example_zh`` = 例句中文对照。
    - ``ipa`` = 音标（主干富字段，未登记 lemma 显式空串）。
    - ``letter`` = 字母分组建表键（A1 首装靠它做字母分组）。**各分支口径不同**：
      A1 = seed 原值逐字透传（``A1_WORKBENCH_SEED[*].letter``，缺失空串，**不派生** ——
      派生会在 10 条上与内联 seed 漂移）；非 A1 = 与前端现行派生逐字一致的首字母大写
      （``(hw or " ")[0].toUpperCase()``，对应 ``syncB1CardsFromServer`` / reader sync）。
      本参数由各分支算好后传入，``_contract_item`` 只做原样落键。
    """
    return {
        "id": vocab_id,
        "hw": hw,
        "pos": pos,
        "gender": gender,
        "plural": plural,
        "de": de,
        "zh": zh,
        "ipa": ipa,
        "example_zh": example_zh,
        "core": core,
        "cefr": cefr,
        "letter": letter,
    }


def _contract_from_a1_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """A1 内部行（S1 起 12 键：新增 letter）→ 契约条目。

    gender/plural 由 ``_a1_workbench_row``（S7）从 ``hw`` 归一化后 join
    ``lexicon.A1_LEMMA_META``（源 = 主干 LEXICON）**直取**（命中即用；未命中 → None/""），
    此处原样透传（不再硬编码空值）。
    ipa / example_zh 由 ``_a1_workbench_row``（S3）取自 seed 的 ``ipa`` / ``ex[0].zh``
    （682/682 全覆盖），此处原样透传。
    letter 由 ``_a1_workbench_row``（S1，ADR-0014 §6-S1）取自 seed 原值（缺失空串），
    此处原样透传——**绝不在此派生**（派生会漂移那 10 条）。
    """
    return _contract_item(
        vocab_id=row["id"],
        hw=row["hw"],
        pos=row["pos"],
        gender=row["gender"],
        plural=row["plural"],
        de=row["de"],
        zh=row["zh"],
        ipa=row["ipa"],
        example_zh=row["example_zh"],
        core=row["core"],
        cefr=row["cefr"],
        letter=row["letter"],
    )


def _contract_from_core_entry(lemma: str, val: tuple) -> Dict[str, Any]:
    """CORE_VOCAB_DB 5 元组存储视图 → 契约条目（A2/通用等级/官方视图共用）。

    富字段（``de`` 德语例句 / ``ipa`` 音标 / ``example_zh`` 例句中文）取自主干富字段
    side-car ``lexicon.rich_of(lemma)``（ADR-0013 §5-5 单入口）；未登记 lemma 一律
    显式空串，**禁止编造 / 静默降级**（ADR-0013 §5-3）。
    """
    lvl = val[0].upper()
    pos = val[1] or ""
    gender = val[2] if len(val) > 2 and val[2] != "None" else None
    plural = val[3] if len(val) > 3 and val[3] != "None" else ""
    zh = val[4] if len(val) > 4 else ""

    # 惰性导入富字段 side-car：与既有 `from delector.core.lexicon import ...` 同风格，
    # 避免模块级循环 / 重依赖（导入期零副作用，红线 9）。
    from delector.core.lexicon import rich_of

    rich = rich_of(lemma)
    de = (rich or {}).get("example_de", "") or ""
    ipa = (rich or {}).get("ipa", "") or ""
    example_zh = (rich or {}).get("example_zh", "") or ""

    hw = format_vocab_headword(lemma, pos, gender)
    # letter（S1，ADR-0014 §6-S1）：非 A1 分支取「与前端现行派生逐字一致」的首字母大写。
    # 依据：前端 syncB1CardsFromServer / reader sync 现行写法 = ``(rw.hw && rw.hw[0] ?
    # rw.hw[0] : "?").toUpperCase()``（取 hw 首字母大写）；非 A1 的 hw 恒非空
    # （format_vocab_headword 对非空 lemma 恒返回非空），故 (hw or " ")[0] 恒等于 hw[0]。
    return _contract_item(
        vocab_id=f"{lvl.lower()}-{lemma.lower()}",
        hw=hw,
        pos=pos,
        gender=gender,
        plural=plural,
        de=de,
        zh=zh,
        ipa=ipa,
        example_zh=example_zh,
        core=True,
        cefr=lvl,
        letter=(hw or " ")[0].upper(),
    )


def _load_a2_vocab_words() -> List[Dict[str, Any]]:
    """加载并缓存 A2 词库（取 core_dict 的 A2 存储视图，经同一映射函数产出契约条目）。

    A2 专用分支已并入通用路径：本函数只剩「过滤 A2 视图 + 缓存」，字段拼装与
    通用等级分支共用 ``_contract_from_core_entry``。core_dict 是包内必然存在的
    第 1 个数据模块，缺失 = 打包损坏 —— ImportError 直接炸，绝不静默回退（红线 2）。
    """
    global _A2_VOCAB_CACHE
    if _A2_VOCAB_CACHE is not None:
        return _A2_VOCAB_CACHE

    from delector.core.lexicon import LEXICON as CORE_VOCAB_DB

    words = [
        _contract_from_core_entry(lemma, val)
        for lemma, val in CORE_VOCAB_DB.items()
        if val[0].upper() == "A2"
    ]

    _A2_VOCAB_CACHE = words
    return words


def get_vocab_by_cefr(
    cefr: str = "A1",
    scope: str = "core",
    db_path: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """按 CEFR 等级与核心范围获取词汇（供工作台与外部组件拉取）。

    ``sources`` 语义（ADR-0012，纯增量）：
    - ``None``（默认）→ **完全走既有分支**，输出逐字不变（A1 workbench /
      A2 core_dict / B1 core_dict / ALL / reader）。
    - 含 ``"official"`` → 官方原样视图 ``lexicon.official_level(cefr)``，逐条经
      既有 ``_contract_from_core_entry`` 产出 11 字段契约。官方视图是「该级全量」，
      故 ``scope``（core/all/reader）只做合法性校验、不影响条数。
    - 非 ``None`` 但不含 ``"official"``（未知来源名）→ **降级为 ``None`` 默认视图**
      （绝不静默返回空表）：sources 是「官方源」开关，无法识别的来源名一律退回
      既有默认分支，保证默认行为与调用方预期不被静默破坏。
    """
    cefr_norm = (cefr or "A1").strip().upper()
    scope_norm = (scope or "core").strip().lower()

    if scope_norm not in ("core", "all", "reader"):
        raise ValueError(f"Invalid scope: {scope}. Must be 'core', 'all', or 'reader'")

    if sources is not None and "official" in set(sources):
        # 惰性导入：lexicon 只依赖 data 分片常量，导入期零重依赖（红线 9）。
        from delector.core import lexicon

        words = [
            _contract_from_core_entry(lemma, val) for lemma, val in lexicon.official_level(cefr_norm).items()
        ]
        return {
            "cefr": cefr_norm,
            "scope": scope_norm,
            "total": len(words),
            "words": words,
        }

    if scope_norm == "reader":
        target_path = get_db_path(db_path)
        with db_conn(target_path) as conn:
            rows = conn.execute("SELECT * FROM vocab_cards ORDER BY id ASC").fetchall()
        words = []
        for r in rows:
            hw = r["word"]
            # reader 卡片无富字段：gender/plural/ipa/example_zh 显式空值，经
            # ``_contract_item`` 统一产出同一 12 字段集（ADR-0011 决策 2 / ADR-0013 §4-1 /
            # ADR-0014 §6-S1），保证各产出点字段集一致。
            # letter 口径 = 与前端 ``syncReaderCardsFromServer`` 现行派生逐字一致：
            # ``(rw.hw && rw.hw[0] ? rw.hw[0] : "?").toUpperCase()``（hw = 卡片 word 字段）。
            words.append(
                _contract_item(
                    vocab_id=f"card-{r['id']}",
                    hw=hw,
                    pos=r["pos"] or "",
                    gender=None,
                    plural="",
                    de=r["sentence_context"] or "",
                    zh=r["definition_zh"] or "",
                    ipa="",
                    example_zh="",
                    core=False,
                    cefr=r["cefr_level"] or "A1",
                    letter=(hw or " ")[0].upper(),
                )
            )
        return {
            "cefr": cefr_norm,
            "scope": scope_norm,
            "total": len(words),
            "words": words,
        }

    if cefr_norm == "A1":
        a1_words = _load_a1_workbench_words()
        filtered = [w for w in a1_words if w["core"]] if scope_norm == "core" else a1_words
        words = [_contract_from_a1_row(w) for w in filtered]
    else:
        # A2 并入通用路径（经 _load_a2_vocab_words 薄函数 + 缓存）；其余级别读 core_dict
        from delector.core.lexicon import LEXICON as CORE_VOCAB_DB

        if cefr_norm == "A2":
            words = _load_a2_vocab_words()
        elif cefr_norm == "ALL":
            a1_words = _load_a1_workbench_words()
            a1_view = [w for w in a1_words if w["core"]] if scope_norm == "core" else a1_words
            words = [_contract_from_a1_row(w) for w in a1_view]
            words.extend(_load_a2_vocab_words())
            words.extend(
                _contract_from_core_entry(lemma, val)
                for lemma, val in CORE_VOCAB_DB.items()
                if val[0].upper() not in ("A1", "A2")
            )
        else:
            words = [
                _contract_from_core_entry(lemma, val)
                for lemma, val in CORE_VOCAB_DB.items()
                if val[0].upper() == cefr_norm
            ]

    return {
        "cefr": cefr_norm,
        "scope": scope_norm,
        "total": len(words),
        "words": words,
    }


def upsert_corpus_syntax_stats(article_id: int, stats: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """插入或更新单篇文献的 24 维句法雷达聚合统计数据。"""
    try:
        sent_count = int(stats.get("sent_count", 0))
        avg_clause_depth = float(stats.get("avg_clause_depth", 0.0))
        passive_rate = float(stats.get("passive_rate", 0.0))
        konjunktiv_rate = float(stats.get("konjunktiv_rate", 0.0))
        vl_rate = float(stats.get("vl_rate", 0.0))
        with db_progress_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO corpus_syntax_stats (
                    article_id, sent_count, avg_clause_depth, passive_rate, konjunktiv_rate, vl_rate, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(article_id) DO UPDATE SET
                    sent_count=excluded.sent_count,
                    avg_clause_depth=excluded.avg_clause_depth,
                    passive_rate=excluded.passive_rate,
                    konjunktiv_rate=excluded.konjunktiv_rate,
                    vl_rate=excluded.vl_rate,
                    analyzed_at=CURRENT_TIMESTAMP
                """,
                (article_id, sent_count, avg_clause_depth, passive_rate, konjunktiv_rate, vl_rate),
            )
        return True
    except Exception as e:
        print(f"[Warn] Failed to upsert corpus syntax stats: {e}")
        return False


def get_all_corpus_syntax_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """查询全量文献的句法雷达统计均值。"""
    try:
        with db_progress_conn(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), AVG(sent_count), AVG(avg_clause_depth), AVG(passive_rate), "
                "AVG(konjunktiv_rate), AVG(vl_rate) FROM corpus_syntax_stats"
            ).fetchone()
            if row:
                count, avg_sc, avg_cd, avg_pr, avg_kr, avg_vr = row
                return {
                    "total_articles": count or 0,
                    "avg_sent_count": round(float(avg_sc or 0.0), 2),
                    "avg_clause_depth": round(float(avg_cd or 0.0), 2),
                    "avg_passive_rate": round(float(avg_pr or 0.0), 4),
                    "avg_konjunktiv_rate": round(float(avg_kr or 0.0), 4),
                    "avg_vl_rate": round(float(avg_vr or 0.0), 4),
                }
    except Exception as e:
        print(f"[Warn] Failed to get all corpus syntax stats: {e}")
    return {
        "total_articles": 0,
        "avg_sent_count": 0.0,
        "avg_clause_depth": 0.0,
        "avg_passive_rate": 0.0,
        "avg_konjunktiv_rate": 0.0,
        "avg_vl_rate": 0.0,
    }


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
    "get_wb_state",
    "save_wb_state",
    "get_wb_sync_key",
    "list_encounter_texts",
    "get_encounter_text",
    "create_encounter_text",
    "import_encounter_pack",
    "get_effective_api_key",
    "get_effective_api_base_url",
    "get_effective_api_model",
    "PRESET_ARTICLES",
    "ingest_article",
    "seed_preset_articles",
    "seed_preset_encounter_texts",
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
    "record_a1_hoeren_trial",
    "get_a1_hoeren_history",
    "record_a1_lesen_trial",
    "get_a1_lesen_history",
    "record_exam_trial",
    "get_exam_history",
    "migrate_a1_records_to_exam_trials",
    "record_listen_trial",
    "list_listen_trials",
    "record_hard_sentence_trial",
    "list_hard_sentence_trials",
    "get_vocab_by_cefr",
    "upsert_corpus_syntax_stats",
    "get_all_corpus_syntax_stats",
]
