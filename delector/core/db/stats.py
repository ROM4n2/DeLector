# -*- coding: utf-8 -*-
"""学习进度统计查询（从 ``delector/routes/cards.py`` 下沉，Layer 4 数据访问层）。

为什么存在
----------
``get_progress_stats`` 原先住在路由层：单函数 150 行、CC 18、33 处裸 SQL，同时跨主库
（卡片 / 文章）与 progress 库（每日摘要 / 学习日志）聚合。HTTP 层不该承担统计查询本身，
故整体下沉到本切片；路由层只保留路径注册与 re-export。

搬移纪律
--------
**纯移动 + 显式 re-export，SQL 一行不改** —— 查询语句、排序、``LIMIT``、聚合口径、
``None`` 兜底与返回结构逐字保持；``delector.routes.cards.get_progress_stats`` 与
``delector.core.db.stats.get_progress_stats`` 仍是同一个函数对象（路由注册与模板引用不变）。
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from delector.core.db.connection import db_conn, db_progress_conn


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

