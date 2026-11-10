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
from delector.core.db.stats import get_progress_stats
from delector.core.lexicon import lemma_key, primary_source
from delector.core.utils import _attachment_headers
from delector.core.vocab_identity import (
    fill_empty_columns,
    find_card_id,
    register_identity_functions,
)

router = APIRouter()
__all__ = ["get_progress_stats", "router"]


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
    skipped_fields: list[str] = []
    with db_conn() as conn:
        # Step 1（只堵新增）：身份 = (lemma_key(lemma), word_key(word))，见
        # delector/core/vocab_identity.py。存量重复未知，故**不建 UNIQUE**；
        # 用 BEGIN IMMEDIATE 把「查重 → 插入」收成一个写事务，收窄并发窗口。
        # 这不是唯一索引：绕过本函数的写入（旧客户端 / 直接 SQL / 备份还原）
        # 仍可产生重复。
        conn.execute("BEGIN IMMEDIATE")
        card_id = find_card_id(conn, req.lemma, req.word)
        if card_id is None:
            created = True
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
        else:
            created = False
            # upsert 的「update」只补空，不覆盖用户已填内容（合法多卡靠 word 区分，
            # 不会被这里合并，见方案 §5.3）。返回被跳过的列名，让响应体能说明
            # 「这次填的内容没写进去」，而不是一律回报「已保存」。
            skipped_fields = fill_empty_columns(
                conn,
                card_id,
                {
                    "pos": req.pos,
                    "gender": req.gender,
                    "plural": req.plural,
                    "cefr_level": req.cefr_level,
                    "definition_zh": req.definition_zh,
                    "sentence_context": req.sentence_context,
                },
            )
    if created:
        # 只有真正新增才记事件，避免重复提交把学习日志刷爆。
        log_study_event("add_card", card_id, req.word)
    # 响应语义：created=false 表示命中既有卡、什么都没新增；skipped_fields 列出
    # 「本次有值、但既有列已非空因而未写入」的列。前端据此区分「已保存」与
    # 「已在词卡中 / 你填的内容保留了原值」，不再把幂等命中渲染成一次成功新增。
    return {
        "status": "ok",
        "id": card_id,
        "word": req.word,
        "plural": req.plural or "",
        "created": created,
        "skipped_fields": skipped_fields,
    }


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


# 词卡抽屉「复习台账」取数：按 lemma 去重，**一条 SQL 决定代表卡**。
#
# 为什么必须在 SQL 里定序：`vocab_cards` 的 `word` / `lemma` 没有 UNIQUE，裸 INSERT
# 会产生同一 lemma 的多张卡。若把候选数组交给前端取 `[0]`，实际就是让 SQLite 的
# 隐式扫描顺序决定状态——索引或查询计划一变，抽屉显示就会漂移，且无法证明稳定。
#
# `last_signal_day` = 「最近一次用户动作」的日期，两段合并：
# - `mastered_at`：用户在卡盒手动置「已掌握」的时间（显式裁决）；
# - `date(due_date, '-interval_days days')`：最近复习日。这不是估价，而是写入公式
#   `due_date = 复习当天 + interval_days`（`_calc_fsrs_step`）的精确逆运算。
# SQLite 的 DESC 把 NULL 排最后 ⇒ 从未复习的新卡不会盖过有真实动作的卡。
# 并列时依次用 `created_at DESC`、`id DESC` 收口，保证同一输入永远同一行。
_LEDGER_SQL = """
WITH ranked AS (
    SELECT
        id, mastered, due_date, interval_days, repetition_count,
        correct_count, wrong_count, fsrs_s, created_at,
        CASE WHEN COALESCE(fsrs_s, 0) > 0 THEN 1 ELSE 0 END AS is_workbench,
        CASE
            WHEN mastered = 1 AND mastered_at IS NOT NULL AND mastered_at <> ''
                THEN substr(mastered_at, 1, 10)
            WHEN due_date IS NOT NULL AND due_date <> ''
             AND interval_days IS NOT NULL AND interval_days > 0
                THEN date(due_date, '-' || CAST(interval_days AS TEXT) || ' days')
            ELSE NULL
        END AS last_signal_day
    FROM vocab_cards
    WHERE card_lemma_key(lemma, word) = ?
)
SELECT *, COUNT(*) OVER () AS card_count
FROM ranked
ORDER BY last_signal_day DESC, created_at DESC, id DESC
LIMIT 1
"""


@router.get("/api/cards/vocab/ledger/{lemma}")
def get_vocab_card_ledger(lemma: str) -> Dict[str, Any]:
    """抽屉复习台账：同一 lemma 多卡只返回一张代表卡（读侧去重，不写库）。

    只暴露既有列：`mastered / due_date / interval_days / repetition_count /
    correct_count / wrong_count / fsrs_s`，外加 `is_workbench` 与 `card_count`。
    `is_workbench` 口径与 `/api/cards/known-lemmas` 的 `fsrs_s > 0` 一致；前端据此
    切换文案，**不再复制数值阈值**（`reader.js` 不得 import `cards.js`，否则成环）。

    无卡返回 200 空态，不返回 404：抽屉每次点词都会查一次，「没入卡」是正常结果。
    lemma 走路径参数而非 query：前端网络层闸门要求 `api()` 的路径可静态归一
    （query 字符串无法与后端路由对账），路径参数折算为 `/ledger/{}` 可对账。
    """
    lemma_norm = (lemma or "").strip()
    if not lemma_norm:
        return {"lemma": "", "card_count": 0, "card": None}
    with db_conn() as conn:
        # 台账是按 lemma_key 聚合的读侧视图（card_count + 代表卡），与写入侧
        # (lemma_key, word_key) 双列身份不同，别把这里当成「两张合法卡被合并」。
        # 归一走 vocab_identity 的行级 UDF：零 DDL、不回填存量行，且 `Haus` / `haus` /
        # `die Wohnung` / `Wohnung` / 旧备份的 lemma='' 行都按同一空值回退命中。
        register_identity_functions(conn)
        row = conn.execute(_LEDGER_SQL, (lemma_key(lemma_norm),)).fetchone()
    if row is None:
        return {"lemma": lemma_norm, "card_count": 0, "card": None}
    return {
        "lemma": lemma_norm,
        "card_count": int(row["card_count"]),
        "card": {
            "id": int(row["id"]),
            "mastered": bool(row["mastered"]),
            "due_date": row["due_date"] or None,
            "interval_days": row["interval_days"],
            "repetition_count": row["repetition_count"] or 0,
            "correct_count": row["correct_count"] or 0,
            "wrong_count": row["wrong_count"] or 0,
            "fsrs_s": row["fsrs_s"],
            "is_workbench": bool(row["is_workbench"]),
        },
    }


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


# ``get_progress_stats`` 的实现已下沉到 ``delector.core.db.stats``（本层只注册路径 + re-export）。
router.get("/api/progress/stats")(get_progress_stats)


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
