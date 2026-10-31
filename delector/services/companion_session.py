# -*- coding: utf-8 -*-
"""伴学智能体会话生命周期与消息历史持久化服务 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from delector.core.database import get_db
from delector.core.db.companion import (
    append_message,
    create_session,
    get_messages,
    init_companion_tables,
    list_sessions,
)
from delector.core.db.companion import (
    get_session as db_get_session,
)


class CompanionSessionService:
    """伴学会话持久化服务，封装会话初始化、历史消息提取与多轮对话沉淀。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        try:
            init_companion_tables(conn)
        except Exception:
            pass

    def get_or_create_session(
        self,
        article_id: Optional[str] = None,
        title: str = "新伴学会话",
    ) -> Dict[str, Any]:
        """查询关联文章（或全局）的最新活跃会话；若不存在则创建新会话。"""
        norm_article_id = article_id.strip() if article_id else None
        title = title.strip() or "新伴学会话"

        with get_db(self.db_path) as conn:
            try:
                sessions = list_sessions(conn, article_id=norm_article_id, limit=20)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                sessions = list_sessions(conn, article_id=norm_article_id, limit=20)

            if norm_article_id is not None:
                if sessions:
                    return sessions[0]
            else:
                for s in sessions:
                    if s.get("article_id") is None:
                        return s
            return create_session(conn, article_id=norm_article_id, title=title)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查询伴学会话元数据。"""
        with get_db(self.db_path) as conn:
            try:
                return db_get_session(conn, session_id=session_id)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return db_get_session(conn, session_id=session_id)

    def save_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        thought: str = "",
        reasoning_effort: str = "medium",
        token_usage: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """向指定会话追加一轮用户与助手结构化消息，并刷新更新时间。"""
        with get_db(self.db_path) as conn:
            try:
                user_msg = append_message(
                    conn,
                    session_id=session_id,
                    role="user",
                    content=user_content,
                )
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                user_msg = append_message(
                    conn,
                    session_id=session_id,
                    role="user",
                    content=user_content,
                )
            assistant_msg = append_message(
                conn,
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                thought=thought,
                reasoning_effort=reasoning_effort,
                token_usage=token_usage,
            )
            return user_msg, assistant_msg

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """按时序获取指定会话的完整消息与思维链历史。"""
        with get_db(self.db_path) as conn:
            try:
                return get_messages(conn, session_id=session_id)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return get_messages(conn, session_id=session_id)

    def list_recent_sessions(
        self,
        article_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """查询指定文章或全局的最新活跃伴学会话。"""
        norm_article_id = article_id.strip() if article_id else None
        with get_db(self.db_path) as conn:
            try:
                return list_sessions(conn, article_id=norm_article_id, limit=limit)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return list_sessions(conn, article_id=norm_article_id, limit=limit)

    def get_context_summary(self) -> Dict[str, Any]:
        """返回当前学习与视口上下文摘要 (生词总量与已掌握数)。"""
        today_str = date.today().isoformat()
        total, mastered = 0, 0
        with get_db(self.db_path) as conn:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM vocab_cards"
                ).fetchone()
                if row:
                    total = row["total"] or 0
                    mastered = row["mastered"] or 0
            except Exception:
                pass
        return {
            "date": today_str,
            "vocab_total": total,
            "vocab_mastered": mastered,
        }
