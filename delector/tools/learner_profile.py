# -*- coding: utf-8 -*-
"""Domain-native tool: get_learner_profile.

Inspects the user's progress database (vocab_cards) to compute learning statistics:
- total_known_words: count of mastered cards or cards with stability >= 21.0
- fsrs_due_count: count of cards due for review (due_date <= date('now') and mastered = 0)
- current_level_estimate: A1 (<500), A2 (<1200), B1 (<2500), else B2
- weakest_roots: top 3-5 lemmas with highest wrong_count > 0
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from delector.core.database import get_progress_db


def _calc_level_estimate(total_known: int) -> str:
    """Map total known words to estimated CEFR level."""
    if total_known < 500:
        return "A1"
    if total_known < 1200:
        return "A2"
    if total_known < 2500:
        return "B1"
    return "B2"


def _extract_profile_from_conn(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Execute queries against open connection and return profile data."""
    # Check if vocab_cards table exists
    table_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'vocab_cards'"
    ).fetchone()
    if not table_row:
        return {
            "status": "ok",
            "total_known_words": 0,
            "current_level_estimate": "A1",
            "fsrs_due_count": 0,
            "weakest_roots": [],
        }

    # Inspect columns
    pragma_rows = conn.execute("PRAGMA table_info(vocab_cards)").fetchall()
    cols = {row[1] for row in pragma_rows}

    # 1. Total known words: mastered = 1 or stability >= 21.0 (or fsrs_s >= 21.0)
    known_clauses: List[str] = []
    if "mastered" in cols:
        known_clauses.append("mastered = 1")
    if "stability" in cols:
        known_clauses.append("stability >= 21.0")
    if "fsrs_s" in cols:
        known_clauses.append("fsrs_s >= 21.0")

    total_known = 0
    if known_clauses:
        where_expr = " OR ".join(known_clauses)
        row = conn.execute(f"SELECT COUNT(*) FROM vocab_cards WHERE {where_expr}").fetchone()
        if row and row[0] is not None:
            total_known = int(row[0])

    level_estimate = _calc_level_estimate(total_known)

    # 2. FSRS due count: due_date <= date('now') and mastered = 0
    fsrs_due_count = 0
    if "due_date" in cols and "mastered" in cols:
        row = conn.execute(
            "SELECT COUNT(*) FROM vocab_cards WHERE due_date <= date('now') AND mastered = 0"
        ).fetchone()
        if row and row[0] is not None:
            fsrs_due_count = int(row[0])

    # 3. Weakest roots: top 3-5 lemmas with highest wrong_count > 0
    weakest_roots: List[str] = []
    if "wrong_count" in cols and "lemma" in cols:
        rows = conn.execute(
            """
            SELECT lemma
            FROM vocab_cards
            WHERE wrong_count > 0 AND lemma IS NOT NULL AND TRIM(lemma) != ''
            GROUP BY lemma
            ORDER BY MAX(wrong_count) DESC, SUM(wrong_count) DESC, lemma ASC
            LIMIT 5
            """
        ).fetchall()
        weakest_roots = [str(r[0]) for r in rows if r[0]]

    return {
        "status": "ok",
        "total_known_words": total_known,
        "current_level_estimate": level_estimate,
        "fsrs_due_count": fsrs_due_count,
        "weakest_roots": weakest_roots,
    }


def get_learner_profile(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Inspect user's progress database and return learner profile."""
    db_path = payload.get("db_path") if isinstance(payload, dict) else None

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_progress_db(db_path) if db_path else get_progress_db()
        return _extract_profile_from_conn(conn)
    except Exception:
        return {
            "status": "ok",
            "total_known_words": 0,
            "current_level_estimate": "A1",
            "fsrs_due_count": 0,
            "weakest_roots": [],
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


async def run(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Async wrapper for agent tool invocation."""
    return get_learner_profile(payload)
