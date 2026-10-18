# -*- coding: utf-8 -*-
"""卡片与词汇复习路由模块（Layer 5 运行装配层）。

涵盖卡片 CRUD、FSRS 间隔复习调度器、打卡与学习进度统计、Anki APKG 导出。
"""

import math
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from delector.core.database import (
    _require_localhost,
    db_conn,
    db_progress_conn,
    export_anki_deck,
    get_vocab_by_cefr,
    log_study_event,
)
from delector.core.lexicon import primary_source
from delector.core.utils import _attachment_headers

router = APIRouter()


class VocabCardReq(BaseModel):
    article_id: Optional[int] = None
    word: str
    lemma: str
    pos: Optional[str] = ""
    gender: Optional[str] = ""
    plural: Optional[str] = ""
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
    corrected_form: Optional[str] = ""
    error_type: Optional[str] = ""


class MasterReq(BaseModel):
    mastered: bool


class QuizRecordReq(BaseModel):
    card_id: int
    card_type: str  # 'vocab' | 'grammar'
    mode: str  # 'flashcard' | 'dictation' | 'choice'
    correct: bool


class ReadLogReq(BaseModel):
    article_id: int
    title: Optional[str] = ""


class CardReviewReq(BaseModel):
    grade: int  # 1: Forgot, 2: Hard, 3: Good, 4: Easy
    card_type: Optional[str] = None


# ── FSRS (Free Spaced Repetition Scheduler) DSR Engine ────────────────────────


def _calc_fsrs_step(
    grade: int,
    rep: int = 0,
    interval: int = 1,
    ef: float = 2.5,
    elapsed_days: Optional[int] = None,
    target_retention: float = 0.90,
) -> Tuple[int, int, float, str]:
    """
    Core single-step FSRS mathematical state transition based on DSR model:
    grade: 1 (Forgot/Again), 2 (Hard), 3 (Good), 4 (Easy)
    """
    grade = max(1, min(4, int(grade)))
    target_retention = max(0.70, min(0.98, float(target_retention)))

    if rep <= 0:
        # Initial review calibration
        s0_map = {1: 0.5, 2: 1.8, 3: 3.6, 4: 8.5}
        d0 = max(1.0, min(10.0, 8.0 - (grade - 1) * 1.8))
        s_prime = s0_map.get(grade, 3.6)
        d_prime = d0
        new_rep = 1 if grade >= 2 else 0
    else:
        # Subsequent review transition
        s = max(0.1, float(interval))
        d = max(1.0, min(10.0, float(ef)))
        t = max(1.0, float(elapsed_days if elapsed_days is not None else interval))

        # Retrievability power-law decay
        r = (1.0 + (19.0 / 81.0) * (t / s)) ** (-0.5)
        r = max(0.01, min(0.99, r))

        # Difficulty update with mean reversion to D0(3) = 4.4
        d0_3 = 4.4
        delta_d = -(grade - 3) * 0.8
        d_prime = max(1.0, min(10.0, 0.1 * d0_3 + 0.9 * (d + delta_d)))

        if grade == 1:
            # Lapse / Forgot
            new_rep = 0
            s_prime = max(0.4, min(s, 0.6 * (d_prime**-0.3) * ((s + 1.0) ** 0.4)))
        else:
            # Successful recall
            new_rep = rep + 1
            penalty_map = {2: 0.6, 3: 1.0, 4: 1.4}
            penalty = penalty_map.get(grade, 1.0)
            factor = math.exp(1.0) * (11.0 - d_prime) * (s**-0.2) * (math.exp((1.0 - r) * 0.9) - 1.0) * penalty
            s_prime = max(0.4, s * (1.0 + factor))

    # Calculate scheduled interval based on target retention
    if abs(target_retention - 0.90) < 1e-6:
        scheduled_days = s_prime
    else:
        scheduled_days = s_prime * (81.0 / 19.0) * (target_retention ** (-2.0) - 1.0)

    new_interval = max(1, int(round(scheduled_days + 1e-9)))
    new_ef = round(d_prime, 2)
    due_date = (datetime.now() + timedelta(days=new_interval)).strftime("%Y-%m-%d")
    return new_rep, new_interval, new_ef, due_date


def get_fsrs_next_intervals(
    rep: int = 0, interval: int = 1, ef: float = 2.5, elapsed_days: Optional[int] = None, target_retention: float = 0.90
) -> Dict[int, int]:
    """
    Precalculate scheduled intervals for all 4 rating grades (1: Again, 2: Hard, 3: Good, 4: Easy).
    """
    return {g: _calc_fsrs_step(g, rep, interval, ef, elapsed_days, target_retention)[1] for g in (1, 2, 3, 4)}


def calculate_fsrs(
    grade: int,
    rep: int = 0,
    interval: int = 1,
    ef: float = 2.5,
    elapsed_days: Optional[int] = None,
    target_retention: float = 0.90,
) -> Tuple[int, int, float, str, Dict[int, int]]:
    """
    Calculate next FSRS schedule state.
    Returns: (new_rep, new_interval, new_ef, due_date, next_intervals)
    """
    new_rep, new_interval, new_ef, due_date = _calc_fsrs_step(grade, rep, interval, ef, elapsed_days, target_retention)
    next_intervals = get_fsrs_next_intervals(new_rep, new_interval, new_ef, target_retention=target_retention)
    return new_rep, new_interval, new_ef, due_date, next_intervals


def calculate_sm2(grade: int, rep: int = 0, interval: int = 1, ef: float = 2.5) -> Tuple[int, int, float, str]:
    """
    Backward-compatible SM-2 wrapper over modern FSRS scheduler.
    Returns: (new_rep, new_interval, new_ef, due_date)
    """
    new_rep, new_interval, new_ef, due_date, _ = calculate_fsrs(grade, rep, interval, ef)
    return new_rep, new_interval, new_ef, due_date


@router.post("/api/cards/vocab")
def add_vocab_card(req: VocabCardReq) -> Dict[str, Any]:
    # ADR-0016 Phase 2（懒物化）：词条进统一池时按主干 provenance 落定 `source`
    # （official/manual/ai；主干未收录的自定义词 = user）。全部前端存词入口
    # （reader / a1_cards / a1_hoeren / search）都打本端点 ⇒ 一处覆盖。
    source = primary_source(req.lemma or req.word)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards "
            "(article_id, word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                req.article_id,
                req.word,
                req.lemma,
                req.pos,
                req.gender,
                req.plural or "",
                req.cefr_level,
                req.definition_zh,
                req.sentence_context,
                source,
            ),
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.word)
    return {"status": "ok", "id": card_id, "word": req.word, "plural": req.plural or ""}


@router.post("/api/cards/grammar")
def add_grammar_card(req: GrammarCardReq) -> Dict[str, Any]:
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO grammar_cards "
            "(article_id, sentence_context, grammar_name, cefr_level, explanation_zh, "
            "rule_formula, corrected_form, error_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                req.article_id,
                req.sentence_context,
                req.grammar_name,
                req.cefr_level,
                req.explanation_zh,
                req.rule_formula or "",
                req.corrected_form or "",
                req.error_type or "",
            ),
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.grammar_name)
    return {"status": "ok", "id": card_id}


@router.get("/api/cards")
def get_cards() -> Dict[str, Any]:
    with db_conn() as conn:
        v = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM vocab_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
            ).fetchall()
        ]
        g = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM grammar_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
            ).fetchall()
        ]
        for card in v + g:
            card["next_intervals"] = get_fsrs_next_intervals(
                card.get("repetition_count") or 0, card.get("interval_days") or 1, card.get("ease_factor") or 2.5
            )
        return {"vocab_cards": v, "grammar_cards": g}


@router.get("/api/cards/counts")
def get_card_counts() -> Dict[str, int]:
    """只要「有多少张卡」时的轻量计数端点（替代「为了拿计数而拉全量卡片」这一用法）。

    **它替代的用法**：前端角标（`refreshCardCounters`）过去为了显示一个 ``length`` 而请求
    ``GET /api/cards`` —— 那条路径是 ``SELECT *`` 全表 + **逐卡** ``get_fsrs_next_intervals``
    递推（O(N) 行物化 + O(N) 次递推），而它挂在 7 个「每次存卡后」的调用点上 ⇒ 存 N 张卡是
    **O(N²)** 的写路径放大。本端点把它压成每表 1 次聚合、共 2 次查询。
    """
    with db_conn() as conn:
        vc = conn.execute("SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM vocab_cards").fetchone()
        gc = conn.execute("SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM grammar_cards").fetchone()

    v_total = int(vc["total"] or 0)
    v_mastered = int(vc["mastered"] or 0)
    g_total = int(gc["total"] or 0)
    g_mastered = int(gc["mastered"] or 0)

    return {
        "vocab_total": v_total,
        "vocab_mastered": v_mastered,
        "grammar_total": g_total,
        "grammar_mastered": g_mastered,
        "total": v_total + g_total,
    }


@router.get("/api/cards/known-lemmas")
def get_known_lemmas() -> Dict[str, Any]:
    """i+1 覆盖率用的「已学」词原形列表（跨背词路径打通，2026-09-28 swarm 审计 P1）。

    取**已学过**的主卡，三条来源任一成立即算已知——**三者量纲不同、不可互相替代**：
    1. `mastered = 1`：用户在**卡盒**手动置「已掌握」；
    2. `repetition_count > 0`：在**卡盒**（DSR 复习）复习过至少一次；
    3. `fsrs_s > 0`：在**背词工作台**（FSRS）评级过至少一次。
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT lemma FROM vocab_cards "
            "WHERE mastered = 1 OR repetition_count > 0 OR fsrs_s > 0"
        ).fetchall()
    return {"lemmas": [r["lemma"] for r in rows if r["lemma"]]}


@router.get("/api/cards/vocab")
def get_cards_vocab(cefr: str = "A1", scope: str = "core", sources: Optional[str] = None) -> Any:
    scope_norm = (scope or "core").lower().strip()
    if scope_norm not in ("core", "all", "reader"):
        raise HTTPException(400, "scope must be 'core', 'all', or 'reader'")
    sources_set = {s.strip() for s in sources.split(",") if s.strip()} if sources else None
    return get_vocab_by_cefr(cefr=cefr, scope=scope_norm, sources=sources_set)


@router.delete("/api/cards/{card_type}/{card_id}")
def delete_card(card_type: str, card_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with db_conn() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (card_id,))
    log_study_event("delete_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "deleted_id": card_id, "card_type": card_type}


@router.patch("/api/cards/{card_type}/{card_id}/master")
def toggle_master(card_type: str, card_id: int, req: MasterReq) -> Dict[str, Any]:
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    now_ts = datetime.now().isoformat() if req.mastered else None
    with db_conn() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(
            f"UPDATE {tbl} SET mastered = ?, mastered_at = ? WHERE id = ?", (1 if req.mastered else 0, now_ts, card_id)
        )
    if req.mastered:
        log_study_event("master_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "id": card_id, "mastered": req.mastered}


@router.post("/api/quiz/record")
def record_quiz(req: QuizRecordReq) -> Dict[str, Any]:
    if req.card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if req.card_type == "vocab" else "grammar_cards"
    with db_conn() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (req.card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {req.card_id} not found")
        if req.correct:
            conn.execute(f"UPDATE {tbl} SET correct_count = correct_count + 1 WHERE id = ?", (req.card_id,))
        else:
            conn.execute(f"UPDATE {tbl} SET wrong_count = wrong_count + 1 WHERE id = ?", (req.card_id,))
    with db_progress_conn() as conn:
        conn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (req.card_id, req.card_type, req.mode, 1 if req.correct else 0),
        )
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
        conn.execute(
            "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, "
            "study_minutes = study_minutes + 1 WHERE date = ?",
            (today,),
        )
    return {"status": "ok"}


@router.post("/api/progress/log-read")
def log_article_read(req: ReadLogReq) -> Dict[str, Any]:
    log_study_event("read_article", req.article_id, req.title or "", minutes=8)
    return {"status": "ok"}


@router.get("/api/progress/stats")
def get_progress_stats() -> Dict[str, Any]:
    # --- main db ---
    with db_conn() as conn:
        vc = conn.execute("SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM vocab_cards").fetchone()
        gc = conn.execute("SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM grammar_cards").fetchone()
        total_vocab = vc["total"]
        total_grammar = gc["total"]
        mastered_vocab = vc["mastered"] or 0
        mastered_grammar = gc["mastered"] or 0
        total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

        # CEFR breakdown (both tables combined)：UNION ALL 聚合，一次遍历两表
        cefr_counts: Dict[str, int] = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
        for row in conn.execute(
            "SELECT COALESCE(cefr_level, 'A1') AS lvl, COUNT(*) AS cnt FROM ("
            "  SELECT cefr_level FROM vocab_cards"
            "  UNION ALL SELECT cefr_level FROM grammar_cards"
            ") GROUP BY lvl"
        ):
            if row["lvl"] in cefr_counts:
                cefr_counts[row["lvl"]] += row["cnt"]

        # Quiz accuracy from card tables
        vc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM vocab_cards").fetchone()
        gc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM grammar_cards").fetchone()
        total_correct = (vc_row["c"] or 0) + (gc_row["c"] or 0)
        total_wrong = (vc_row["w"] or 0) + (gc_row["w"] or 0)
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
    with db_progress_conn() as conn:
        today = datetime.now().date()
        first_day = (today - timedelta(days=29)).isoformat()
        summary_rows = conn.execute(
            "SELECT * FROM daily_summary WHERE date BETWEEN ? AND ?",
            (first_day, today.isoformat()),
        ).fetchall()
        by_date = {r["date"]: dict(r) for r in summary_rows}
        trend = []
        for i in range(29, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            if d in by_date:
                trend.append(by_date[d])
            else:
                trend.append(
                    {
                        "date": d,
                        "cards_added": 0,
                        "cards_mastered": 0,
                        "articles_read": 0,
                        "quiz_sessions": 0,
                        "study_minutes": 0,
                    }
                )

        # Streak：1 次 DISTINCT 范围查 + Python 回溯
        active_days = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT substr(logged_at, 1, 10) FROM study_log WHERE logged_at >= ?",
                ((today - timedelta(days=365)).isoformat(),),
            )
        }
        streak = 0
        check_date = today
        while check_date.isoformat() in active_days:
            streak += 1
            check_date = check_date - timedelta(days=1)

        total_quiz_sessions = conn.execute("SELECT SUM(quiz_sessions) FROM daily_summary").fetchone()[0] or 0
        total_study_minutes = conn.execute("SELECT SUM(study_minutes) FROM daily_summary").fetchone()[0] or 0

    total_cards = total_vocab + total_grammar
    total_mastered = mastered_vocab + mastered_grammar

    milestones = [
        {
            "id": "first_card",
            "title": "初临纸页",
            "desc": "制作了第一张卡片",
            "icon": "🌱",
            "unlocked": total_cards >= 1,
        },
        {
            "id": "first_article",
            "title": "开卷有益",
            "desc": "研读了第一篇德语文章",
            "icon": "📖",
            "unlocked": total_articles >= 1,
        },
        {
            "id": "master_10",
            "title": "小试牛刀",
            "desc": "斩获 10 张已掌握卡片",
            "icon": "⚔️",
            "unlocked": total_mastered >= 10,
        },
        {
            "id": "master_50",
            "title": "千锤百炼",
            "desc": "斩获 50 张已掌握卡片",
            "icon": "🛡️",
            "unlocked": total_mastered >= 50,
        },
        {
            "id": "master_100",
            "title": "博闻强记",
            "desc": "斩获 100 张已掌握卡片",
            "icon": "🏅",
            "unlocked": total_mastered >= 100,
        },
        {
            "id": "master_200",
            "title": "词海无涯",
            "desc": "斩获 200 张已掌握卡片",
            "icon": "👑",
            "unlocked": total_mastered >= 200,
        },
        {"id": "streak_3", "title": "三日不绝", "desc": "连续打卡 3 天", "icon": "🔥", "unlocked": streak >= 3},
        {"id": "streak_7", "title": "一周常胜", "desc": "连续打卡 7 天", "icon": "⚡", "unlocked": streak >= 7},
        {"id": "streak_30", "title": "月光苦读者", "desc": "连续打卡 30 天", "icon": "🌙", "unlocked": streak >= 30},
    ]

    return {
        "total_cards": total_cards,
        "total_vocab": total_vocab,
        "total_grammar": total_grammar,
        "total_mastered": total_mastered,
        "mastered_vocab": mastered_vocab,
        "mastered_grammar": mastered_grammar,
        "total_articles": total_articles,
        "streak": streak,
        "total_quiz_sessions": total_quiz_sessions,
        "total_study_minutes": total_study_minutes,
        "total_attempts": total_attempts,
        "accuracy_pct": accuracy_pct,
        "cefr_counts": cefr_counts,
        "top_errors": top_errors,
        "trend": trend,
        "milestones": milestones,
    }


@router.get("/api/cards/export/apkg")
def export_apkg() -> Any:
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "DeLector_Deck.apkg")
    export_anki_deck(path)
    return FileResponse(
        path,
        filename="DeLector_Deck.apkg",
        media_type="application/octet-stream",
        headers=_attachment_headers("DeLector_Deck.apkg"),
    )


@router.post("/api/cards/{card_type}/{card_id}/review")
def review_card_sm2(card_type: str, card_id: int, req: CardReviewReq) -> Dict[str, Any]:
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with db_conn() as conn:
        row = conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")

        rep = row["repetition_count"] if "repetition_count" in row.keys() and row["repetition_count"] is not None else 0
        interval = row["interval_days"] if "interval_days" in row.keys() and row["interval_days"] is not None else 1
        ef = row["ease_factor"] if "ease_factor" in row.keys() and row["ease_factor"] is not None else 2.5

        elapsed = None
        if "due_date" in row.keys() and row["due_date"]:
            try:
                due_dt = datetime.strptime(str(row["due_date"])[:10], "%Y-%m-%d")
                sched_dt = due_dt - timedelta(days=interval)
                today_dt = datetime.now()
                elapsed = max(1, (today_dt - sched_dt).days)
            except Exception:
                elapsed = None

        new_rep, new_interval, new_ef, due_date, next_intervals = calculate_fsrs(
            req.grade, rep, interval, ef, elapsed_days=elapsed
        )

        is_correct = req.grade >= 2
        correct_incr = 1 if is_correct else 0
        wrong_incr = 1 if not is_correct else 0

        conn.execute(
            f"""
            UPDATE {tbl}
            SET repetition_count = ?, interval_days = ?, ease_factor = ?, due_date = ?,
                correct_count = correct_count + ?, wrong_count = wrong_count + ?
            WHERE id = ?
        """,
            (new_rep, new_interval, new_ef, due_date, correct_incr, wrong_incr, card_id),
        )

        updated = dict(row)
        updated.update(
            {
                "repetition_count": new_rep,
                "interval_days": new_interval,
                "ease_factor": new_ef,
                "due_date": due_date,
                "correct_count": (row["correct_count"] or 0) + correct_incr,
                "wrong_count": (row["wrong_count"] or 0) + wrong_incr,
            }
        )
        updated["next_intervals"] = next_intervals

    with db_progress_conn() as pconn:
        pconn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (card_id, card_type, "fsrs_review", 1 if is_correct else 0),
        )
    log_study_event("quiz_session", card_id, f"fsrs:{card_type}:{card_id}")
    return updated


@router.get("/api/cards/due")
def get_due_cards() -> Dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    with db_conn() as conn:
        v = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM vocab_cards WHERE mastered = 0 "
                "AND (due_date IS NULL OR due_date <= ?) "
                "AND NOT (COALESCE(fsrs_s, 0) > 0 AND repetition_count = 0) "
                "ORDER BY wrong_count DESC, id ASC",
                (today,),
            ).fetchall()
        ]
        g = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM grammar_cards WHERE mastered = 0 "
                "AND (due_date IS NULL OR due_date <= ?) ORDER BY wrong_count DESC, id ASC",
                (today,),
            ).fetchall()
        ]
        for card in v + g:
            card["next_intervals"] = get_fsrs_next_intervals(
                card.get("repetition_count") or 0, card.get("interval_days") or 1, card.get("ease_factor") or 2.5
            )
        return {"due_vocab": v, "due_grammar": g, "due_count": len(v) + len(g), "today": today}
