# -*- coding: utf-8 -*-
r"""建表 / 索引 / 内联列迁移（主库 `delector.db` + progress 库 `progress.db`）。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 3）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.schema import X as X` 再导出，公开面零变化。

本片承载的整组职责：
- progress 库建表 + 索引：`init_progress_db`
- 主库建表 + 索引 + 现有库的内联列迁移（`ALTER TABLE ...`）：`init_db`
- 成绩表迁移：`migrate_a1_records_to_exam_trials`（由 `init_progress_db` 调用）

为什么 `migrate_a1_records_to_exam_trials` 与建表函数**同模块**
---------------------------------------------------------------
建表函数与它共享被迁移表的**结构定义**（`exam_trials` / `a1_*_records` 的列集由
`init_progress_db` 的 DDL 钉定），且它是建表路径的一环（`init_progress_db` 末尾
无条件调用、`init_progress_db` 又是 `get_progress_db` 的自动建库入口）。拆分二者
会让「加/改一列」与「迁移它」分散两处、极易漏改 —— 故不拆。

模块级可变状态：`_INITIALIZED_PROGRESS_DBS` 仍住 `database.py`（`get_progress_db`
的持有者），本模块只 import 其**引用**（同一对象，非副本）。
"""

import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from delector.core.db.connection import (
    _INITIALIZED_PROGRESS_DBS,
    _REPO_ROOT,
    DATA_DIR,
    _close_db_conn,
    _configure_sqlite_conn,
    db_conn,
    db_progress_conn,
    get_db_path,
    get_progress_db_path,
    preflight_data_dir,
)
from delector.core.db.content import seed_preset_articles


def init_progress_db(db_path: Optional[str] = None) -> None:
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
            -- P1-7：泛化模考表此前无任何索引 ⇒ get_exam_history 的
            -- WHERE level=? AND module=? ORDER BY id DESC 与启动路径
            -- migrate_a1_records_to_exam_trials 的 2 次全表 COUNT 均落 SCAN exam_trials。
            -- (level, module, id DESC) 与查询方向逐段一致 ⇒ SEARCH + 零排序
            -- （EXPLAIN 证据：tests/test_query_plans.py）。
            CREATE INDEX IF NOT EXISTS idx_exam_lm ON exam_trials(level, module, id DESC);
        """)
    finally:
        # init 阶段不能用 db_progress_conn（会递归回自身自动建表），此处确定关闭
        _close_db_conn(conn)
    _INITIALIZED_PROGRESS_DBS.add(target_path)
    # 泛化成绩表上线即迁移存量 A1 行；函数自身行数对账幂等，重复调用无害
    migrate_a1_records_to_exam_trials(db_path=target_path)


def init_db(db_path: Optional[str] = None) -> None:
    # 迁移闸必须**在建表之前**跑：一旦 `CREATE TABLE` 执行，空库文件就落盘了，
    # 用户看到的正是「功能正常、数据全空」且此后更难分辨的静默失败。抛错即中止，
    # 不留下任何半成品。传显式 db_path（测试夹具）时数据目录不参与判据，故直接跳过。
    if db_path is None:
        preflight_data_dir(DATA_DIR, _REPO_ROOT)
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_url TEXT,
                raw_text TEXT NOT NULL,
                processed_json TEXT NOT NULL,
                -- P1-6：列表投影列（~200B 的 stats 子 JSON）。与 processed_json 在全部
                -- 三条写入路径同步写（ingest_article / seed_preset_articles / 惰性迁移），
                -- 列表查询只投影本列，不再捞整列 blob（改前 2000 篇列表 ≈950ms）。
                stats_json TEXT,
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
                -- ADR-0016 Phase 1（统一池）：source 记词条来源（official/manual/ai/user），
                -- fsrs_* 承载背词工作台的 FSRS-6 卡参数。加性、零行为变化（无人读写）。
                source TEXT DEFAULT 'user',
                fsrs_s REAL,
                fsrs_d REAL,
                fsrs_lapses INTEGER DEFAULT 0,
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
            if tbl == "vocab_cards":
                # ADR-0016 Phase 1：旧库自动补统一池列（加性、幂等、零行为变化）。
                # source 有常量默认值 ⇒ 存量行自动回填 'user'（官方/手编/AI 由 Phase 2 派生投影写）。
                if "source" not in cols:
                    conn.execute("ALTER TABLE vocab_cards ADD COLUMN source TEXT DEFAULT 'user'")
                if "fsrs_s" not in cols:
                    conn.execute("ALTER TABLE vocab_cards ADD COLUMN fsrs_s REAL")
                if "fsrs_d" not in cols:
                    conn.execute("ALTER TABLE vocab_cards ADD COLUMN fsrs_d REAL")
                if "fsrs_lapses" not in cols:
                    conn.execute("ALTER TABLE vocab_cards ADD COLUMN fsrs_lapses INTEGER DEFAULT 0")
            if tbl == "grammar_cards":
                for col in ("corrected_form", "error_type"):
                    if col not in cols:
                        conn.execute(f"ALTER TABLE grammar_cards ADD COLUMN {col} TEXT DEFAULT ''")

        # P1-6：旧库补列表投影列 + **一次性** SQL 侧回填。回填策略 = 一次性（迁移时点，
        # 列刚补上的这次 init_db 里执行），**不在列表路径给全表回填**、也不在每次启动重跑
        # （列已存在 ⇒ 分支跳过，幂等）。回填用 json_extract 在 SQLite C 侧完成，Python 零
        # 解析；缺 stats / processed_json 损坏的行回填为 NULL，由列表查询的 COALESCE 兜底
        # （回填成本实测：2000 行 × 36KB ≈ 7ms，见 tools/bench_articles_list.py 的 backfill_ms）。
        article_cols = [col[1] for col in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "stats_json" not in article_cols:
            conn.execute("ALTER TABLE articles ADD COLUMN stats_json TEXT")
            # json_valid 守卫必须带：SQLite 的 json_extract 对**损坏 JSON 是抛错**而非
            # 返回 NULL，裸 UPDATE 会让一行脏数据炸掉整次启动迁移。
            conn.execute(
                "UPDATE articles SET stats_json = json_extract(processed_json, '$.stats') "
                "WHERE stats_json IS NULL AND json_valid(processed_json)"
            )

        # 读路径查询索引（幂等）：**必须在补列之后**——旧库可能缺 mastered/due_date，
        # 先建索引会 `no such column: mastered` 直接炸启动（ADR-0016 Phase 1 暴露的次序 bug）。
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_srs ON vocab_cards(mastered, due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_grammar_srs ON grammar_cards(mastered, due_date)")
        # P1-7 卡盒队列索引：/api/cards 的 ORDER BY mastered ASC, wrong_count DESC, id DESC
        # 原落 TEMP B-TREE（20k 卡 118ms）。**必须用混合方向列**：ASC 变体
        # (mastered, wrong_count, id) 实测仍触发 TEMP B-TREE（SQLite 单方向索引吃不下
        # 混合方向排序），DESC 列（SQLite 支持）与查询方向逐段一致 ⇒ EXPLAIN 零排序
        # （证据：tests/test_query_plans.py 的 EXPLAIN 断言）。
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vocab_queue ON vocab_cards(mastered, wrong_count DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_grammar_queue ON grammar_cards(mastered, wrong_count DESC, id DESC)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_article ON vocab_cards(article_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_grammar_article ON grammar_cards(article_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_article ON reading_notes(article_id)")

        conn.execute("""
            INSERT INTO essay_versions (essay_id, content, analysis_json, message)
            SELECT id, content, analysis_json, '初始快照' FROM essays
            WHERE id NOT IN (SELECT DISTINCT essay_id FROM essay_versions);
        """)

    init_progress_db()
    seed_preset_articles(target_path)


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
