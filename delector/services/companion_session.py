# -*- coding: utf-8 -*-
"""伴学智能体会话生命周期与消息历史持久化服务 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from delector.core.database import db_conn
from delector.core.db.companion import (
    append_message,
    create_proposal,
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
        except Exception:  # silent-ok: 幂等初始化伴学表，并发重试或已存在时无需中断
            pass

    def get_or_create_session(
        self,
        article_id: Optional[str] = None,
        title: str = "新伴学会话",
        scope_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询指定 scope / 文章 / 全局的最新活跃会话；若不存在则创建新会话。"""
        norm_article_id = article_id.strip() if article_id else None
        norm_scope_key = scope_key.strip() if scope_key else None
        title = title.strip() or "新伴学会话"

        with db_conn(self.db_path) as conn:
            try:
                if norm_scope_key is not None:
                    sessions = list_sessions(conn, scope_key=norm_scope_key, limit=20)
                else:
                    sessions = list_sessions(conn, article_id=norm_article_id, limit=20)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                if norm_scope_key is not None:
                    sessions = list_sessions(conn, scope_key=norm_scope_key, limit=20)
                else:
                    sessions = list_sessions(conn, article_id=norm_article_id, limit=20)

            if norm_scope_key is not None:
                if sessions:
                    return sessions[0]
            elif norm_article_id is not None:
                if sessions:
                    return sessions[0]
            else:
                for s in sessions:
                    if s.get("article_id") is None:
                        return s
            return create_session(
                conn,
                article_id=norm_article_id,
                title=title,
                scope_key=norm_scope_key,
            )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查询伴学会话元数据。"""
        with db_conn(self.db_path) as conn:
            try:
                return db_get_session(conn, session_id=session_id)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return db_get_session(conn, session_id=session_id)

    def save_turn_snapshot(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        thought: str = "",
        reasoning_effort: str = "medium",
        token_usage: Optional[Dict[str, Any]] = None,
        proposals: Optional[List[Dict[str, Any]]] = None,
        save_messages: bool = True,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """在同一事务保存断点消息与 proposals；proposal-only 不伪造空消息。"""
        user_msg: Optional[Dict[str, Any]] = None
        assistant_msg: Optional[Dict[str, Any]] = None
        with db_conn(self.db_path) as conn:
            if save_messages:
                try:
                    user_msg = append_message(
                        conn,
                        session_id=session_id,
                        role="user",
                        content=user_content,
                        commit=False,
                    )
                except sqlite3.OperationalError:
                    self._ensure_tables(conn)
                    user_msg = append_message(
                        conn,
                        session_id=session_id,
                        role="user",
                        content=user_content,
                        commit=False,
                    )
                assistant_msg = append_message(
                    conn,
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    thought=thought,
                    reasoning_effort=reasoning_effort,
                    token_usage=token_usage,
                    commit=False,
                )

            for prop in proposals or []:
                raw_payload = prop.get("payload")
                payload_dict: Dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
                create_proposal(
                    conn,
                    session_id=session_id,
                    action=str(prop.get("action") or "create_vocab_cards"),
                    title=str(prop.get("title") or "加入核心生词卡"),
                    payload=payload_dict,
                    message_id=assistant_msg["id"] if assistant_msg is not None else None,
                    proposal_id=str(prop.get("id") or "") or None,
                    commit=False,
                )
            return user_msg, assistant_msg

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
        user_msg, assistant_msg = self.save_turn_snapshot(
            session_id=session_id,
            user_content=user_content,
            assistant_content=assistant_content,
            thought=thought,
            reasoning_effort=reasoning_effort,
            token_usage=token_usage,
            proposals=[],
        )
        assert user_msg is not None and assistant_msg is not None
        return user_msg, assistant_msg

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """按时序获取指定会话的完整消息与思维链历史。"""
        with db_conn(self.db_path) as conn:
            try:
                return get_messages(conn, session_id=session_id)
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return get_messages(conn, session_id=session_id)

    def list_recent_sessions(
        self,
        article_id: Optional[str] = None,
        limit: int = 20,
        scope_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询指定 scope / 文章或全局的最新活跃伴学会话。"""
        norm_article_id = article_id.strip() if article_id else None
        norm_scope_key = scope_key.strip() if scope_key else None
        with db_conn(self.db_path) as conn:
            try:
                return list_sessions(
                    conn,
                    article_id=norm_article_id,
                    scope_key=norm_scope_key,
                    limit=limit,
                )
            except sqlite3.OperationalError:
                self._ensure_tables(conn)
                return list_sessions(
                    conn,
                    article_id=norm_article_id,
                    scope_key=norm_scope_key,
                    limit=limit,
                )

    def get_context_summary(self) -> Dict[str, Any]:
        """返回当前学习与视口上下文摘要 (生词总量与已掌握数)。"""
        today_str = date.today().isoformat()
        total, mastered = 0, 0
        with db_conn(self.db_path) as conn:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS total, SUM(mastered = 1) AS mastered FROM vocab_cards"
                ).fetchone()
                if row:
                    total = row["total"] or 0
                    mastered = row["mastered"] or 0
            except Exception:  # silent-ok: 空库或生词卡表尚未就绪时安全回退至零统计值
                pass
        return {
            "date": today_str,
            "vocab_total": total,
            "vocab_mastered": mastered,
        }
