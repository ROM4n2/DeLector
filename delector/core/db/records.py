# -*- coding: utf-8 -*-
r"""考试 / 训练记录读写（exam_trials / a1_* / listen_trials / hard_sentence_trials）。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 4）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.records import X` 再导出，公开面零变化。

本片承载的整组职责：
- 泛化模考成绩：`record_exam_trial` / `get_exam_history`
- A1 双模块透传：`record_a1_hoeren_trial` / `get_a1_hoeren_history` /
  `record_a1_lesen_trial` / `get_a1_lesen_history`
- 听力微训：`record_listen_trial` / `list_listen_trials`
- 长难句精读：`record_hard_sentence_trial` / `list_hard_sentence_trials`

成绩表迁移 `migrate_a1_records_to_exam_trials` **不在此片**：它与建表函数同住
`db/schema.py`（共享被迁移表结构、是 init_progress_db 建库路径的一环，见 schema.py）。
"""

from typing import Any, Dict, List, Optional

from delector.core.db.connection import db_conn, db_progress_conn, log_study_event


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
    return record_id  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


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
        return cur.lastrowid  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


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
        return cur.lastrowid  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


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
