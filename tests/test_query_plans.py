# -*- coding: utf-8 -*-
"""P1-7 索引与查询计划回归锁（EXPLAIN QUERY PLAN 断言）。

钉住什么
--------
审计实测（dba 席）：
- ``GET /api/cards`` 的 ``ORDER BY mastered ASC, wrong_count DESC, id DESC`` 落
  ``USE TEMP B-TREE FOR RIGHT PART OF ORDER BY``（``idx_vocab_srs(mastered,due_date)``
  覆盖不到右段），20k 卡 118ms；
- ``exam_trials`` 的 ``WHERE level=? AND module=? ORDER BY id DESC`` 全表 SCAN
  （``migrate_a1_records_to_exam_trials`` 每次启动还跑 2 次全表 COUNT）。

本文件用 **EXPLAIN QUERY PLAN 的结构性事实**钉住（不钉毫秒——计划漂移对毫秒的
改变是渐变、对计划形态的改变是跳变，后者才是防回归的尺子）：

1. ``/api/cards`` 两条查询（vocab + grammar）必须走队列索引且**无 TEMP B-TREE**；
2. ``get_exam_history`` 与 ``migrate_a1_records_to_exam_trials`` 的 COUNT 必须
   ``SEARCH ... idx_exam_lm``、无 ``SCAN exam_trials``；
3. ``/api/cards/due``（``mastered=0`` 选择性差）**刻意不设计划断言**：实测加队列
   索引后仍 TEMP B-TREE（排序键 ``wrong_count DESC, id ASC`` 与索引方向不符），
   帮不到就如实说明、不硬凑——见模块尾的记录用例。

隔离纪律：tmp 库 + init_db（全真 schema 与索引），不碰真实库。
"""

import os
import sqlite3
import sys
from typing import Iterator, List, Tuple

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from delector.core.database import init_db, init_progress_db  # noqa: E402

# 与 delector/routes/main.py::get_cards 逐字对齐的查询（改一边必须同步另一边）
CARDS_SQL = "SELECT * FROM {tbl} ORDER BY mastered ASC, wrong_count DESC, id DESC"
# 与 get_due_cards 对齐（仅 vocab 版；grammar 版排序相同）
DUE_SQL = (
    "SELECT * FROM vocab_cards WHERE mastered = 0 "
    "AND (due_date IS NULL OR due_date <= ?) "
    "AND NOT (COALESCE(fsrs_s, 0) > 0 AND repetition_count = 0) "
    "ORDER BY wrong_count DESC, id ASC"
)
# 与 get_exam_history / migrate COUNT 对齐
EXAM_HISTORY_SQL = (
    "SELECT id, set_id, score_raw FROM exam_trials WHERE level = ? AND module = ? ORDER BY id DESC LIMIT ?"
)
EXAM_COUNT_SQL = "SELECT COUNT(*) FROM exam_trials WHERE level = ? AND module = ?"


@pytest.fixture
def main_conn(tmp_path) -> Iterator[sqlite3.Connection]:
    db = str(tmp_path / "plans.db")
    init_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def progress_conn(tmp_path) -> Iterator[sqlite3.Connection]:
    db = str(tmp_path / "plans_progress.db")
    init_progress_db(db)
    conn = sqlite3.connect(db)
    yield conn
    conn.close()


def _plan(conn: sqlite3.Connection, sql: str, params: Tuple[object, ...] = ()) -> List[str]:
    return [row[-1] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]


# ── ① /api/cards：队列索引吃下排序，无 TEMP B-TREE ────────────────────────────
@pytest.mark.parametrize("tbl", ["vocab_cards", "grammar_cards"])
def test_cards_orderby_uses_queue_index_no_temp_btree(main_conn, tbl: str) -> None:
    plan = _plan(main_conn, CARDS_SQL.format(tbl=tbl))
    joined = " | ".join(plan)
    assert "TEMP B-TREE" not in joined, f"{tbl} 排序退化回 TEMP B-TREE：{plan}"
    assert f"USING INDEX idx_{tbl.split('_')[0]}_queue" in joined, f"{tbl} 未走队列索引：{plan}"


def test_vocab_queue_index_exists(main_conn) -> None:
    rows = main_conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_vocab_queue'").fetchall()
    assert rows, "idx_vocab_queue 不存在（init_db 未建或被删）"


# ── ② exam_trials：不再全表 SCAN ─────────────────────────────────────────────
def test_exam_history_uses_idx_exam_lm(progress_conn) -> None:
    plan = _plan(progress_conn, EXAM_HISTORY_SQL, ("A1", "hoeren", 50))
    joined = " | ".join(plan)
    assert "SCAN exam_trials" not in joined, f"exam 历史查询仍全表扫描：{plan}"
    assert "idx_exam_lm" in joined, f"exam 历史查询未走 idx_exam_lm：{plan}"


def test_exam_count_uses_idx_exam_lm(progress_conn) -> None:
    """migrate_a1_records_to_exam_trials 启动路径的 2 次全表 COUNT 必须走索引。"""
    plan = _plan(progress_conn, EXAM_COUNT_SQL, ("A1", "hoeren"))
    joined = " | ".join(plan)
    assert "SCAN exam_trials" not in joined, f"exam COUNT 仍全表扫描：{plan}"
    assert "idx_exam_lm" in joined, f"exam COUNT 未走 idx_exam_lm：{plan}"


# ── ③ /api/cards/due：如实记录（不硬凑） ──────────────────────────────────────
def test_due_query_plan_honestly_recorded(main_conn) -> None:
    """登记用例：due 查询在队列索引下的真实计划形态。

    实测（SQLite 3.43）：队列索引 (mastered, wrong_count DESC, id DESC) 对
    ``WHERE mastered=0`` 可作 SEARCH（等值段可用），但排序键 ``wrong_count DESC,
    id ASC`` 与索引右段方向不一致 ⇒ 仍有 TEMP B-TREE。加"正确方向"的第二索引
    （mastered, wrong_count DESC, id ASC）对 mastered=0（未掌握占多数）选择性太差，
    扫的行数不比全表少多少，收益接近零 —— 故**刻意不加**，本用例只把计划形态
    钉成快照供未来改动时对照；若有人改谓词/排序使计划变化，会在这里现形。
    """
    plan = _plan(main_conn, DUE_SQL, ("2026-10-11",))
    assert plan, "EXPLAIN 无输出"
    # 快照断言：只要别动谓词/排序，形态稳定；动了 ⇒ 人工复核这里该改成什么。
    assert any("mastered=?" in p for p in plan), f"due 查询计划形态变了（人工复核）：{plan}"
