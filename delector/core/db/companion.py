"""
Companion study agent SQLite persistence layer (sessions, messages, proposals).
"""
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def init_companion_tables(conn: sqlite3.Connection) -> None:
    """幂等创建伴学智能体会话表、消息表与提议生命周期表。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS companion_sessions (
            id TEXT PRIMARY KEY,
            article_id TEXT,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_archived INTEGER DEFAULT 0
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_companion_sessions_article
        ON companion_sessions(article_id, updated_at DESC);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS companion_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES companion_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            thought TEXT DEFAULT '',
            reasoning_effort TEXT DEFAULT 'medium',
            token_usage_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_companion_messages_session
        ON companion_messages(session_id, created_at ASC);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS companion_proposals (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES companion_sessions(id) ON DELETE CASCADE,
            message_id TEXT REFERENCES companion_messages(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            resolved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_companion_proposals_session
        ON companion_proposals(session_id, status);
        """
    )
    conn.commit()


def create_session(
    conn: sqlite3.Connection,
    article_id: Optional[str] = None,
    title: str = "新伴学会话",
) -> Dict[str, Any]:
    """创建新的伴学会话。"""
    session_id = f"ses_{uuid.uuid4().hex[:16]}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO companion_sessions (id, article_id, title, created_at, updated_at, is_archived)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (session_id, article_id, title, now, now),
    )
    conn.commit()
    return {
        "id": session_id,
        "article_id": article_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "is_archived": 0,
    }


def get_session(
    conn: sqlite3.Connection, session_id: str
) -> Optional[Dict[str, Any]]:
    """按 ID 查询伴学会话。"""
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT id, article_id, title, created_at, updated_at, is_archived
        FROM companion_sessions
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def list_sessions(
    conn: sqlite3.Connection,
    article_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """查询指定文章或全局的伴学会话列表。"""
    cursor = conn.cursor()
    if article_id:
        rows = cursor.execute(
            """
            SELECT id, article_id, title, created_at, updated_at, is_archived
            FROM companion_sessions
            WHERE article_id = ? AND is_archived = 0
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (article_id, limit),
        ).fetchall()
    else:
        rows = cursor.execute(
            """
            SELECT id, article_id, title, created_at, updated_at, is_archived
            FROM companion_sessions
            WHERE is_archived = 0
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def append_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    thought: str = "",
    reasoning_effort: str = "medium",
    token_usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """向指定会话追加一条结构化消息，并刷新会话的 updated_at。"""
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    usage_json = json.dumps(token_usage or {}, ensure_ascii=False)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO companion_messages (
            id, session_id, role, content, thought, reasoning_effort, token_usage_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg_id,
            session_id,
            role,
            content,
            thought,
            reasoning_effort,
            usage_json,
            now,
        ),
    )
    cursor.execute(
        """
        UPDATE companion_sessions
        SET updated_at = ?
        WHERE id = ?
        """,
        (now, session_id),
    )
    conn.commit()
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "thought": thought,
        "reasoning_effort": reasoning_effort,
        "token_usage": token_usage or {},
        "created_at": now,
    }


def get_messages(
    conn: sqlite3.Connection, session_id: str
) -> List[Dict[str, Any]]:
    """获取指定会话的完整时序消息列表。"""
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT id, session_id, role, content, thought, reasoning_effort, token_usage_json, created_at
        FROM companion_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["token_usage"] = json.loads(d.pop("token_usage_json") or "{}")
        results.append(d)
    return results


def create_proposal(
    conn: sqlite3.Connection,
    session_id: str,
    action: str,
    title: str,
    payload: Dict[str, Any],
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """记录单项提议（生词卡/完形填空），初始状态为 pending。"""
    prop_id = f"prop_{uuid.uuid4().hex[:16]}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    payload_json = json.dumps(payload, ensure_ascii=False)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO companion_proposals (
            id, session_id, message_id, action, title, payload_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (prop_id, session_id, message_id, action, title, payload_json, now),
    )
    conn.commit()
    return {
        "id": prop_id,
        "session_id": session_id,
        "message_id": message_id,
        "action": action,
        "title": title,
        "payload": payload,
        "status": "pending",
        "created_at": now,
        "resolved_at": None,
    }


def get_proposals(
    conn: sqlite3.Connection,
    session_id: str,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """查询指定会话的提议列表，可按 status 过滤。"""
    cursor = conn.cursor()
    if status:
        rows = cursor.execute(
            """
            SELECT id, session_id, message_id, action, title, payload_json, status, resolved_at, created_at
            FROM companion_proposals
            WHERE session_id = ? AND status = ?
            ORDER BY created_at ASC
            """,
            (session_id, status),
        ).fetchall()
    else:
        rows = cursor.execute(
            """
            SELECT id, session_id, message_id, action, title, payload_json, status, resolved_at, created_at
            FROM companion_proposals
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
        results.append(d)
    return results


def update_proposal_status(
    conn: sqlite3.Connection, proposal_id: str, status: str
) -> bool:
    """原子更新提议状态（pending -> accepted/rejected）。"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE companion_proposals
        SET status = ?, resolved_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (status, now, proposal_id),
    )
    conn.commit()
    return cursor.rowcount > 0
