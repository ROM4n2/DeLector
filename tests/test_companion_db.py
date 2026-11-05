"""
Unit tests for companion SQLite persistence (sessions, messages, proposals).
"""
import sqlite3

import pytest

from delector.core.db.companion import (
    append_message,
    create_proposal,
    create_session,
    get_messages,
    get_proposals,
    get_session,
    init_companion_tables,
    list_sessions,
    update_proposal_status,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_companion_tables(c)
    yield c
    c.close()


def test_init_tables_idempotent(conn):
    # Calling it again shouldn't fail
    init_companion_tables(conn)
    cursor = conn.cursor()
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "companion_sessions" in tables
    assert "companion_messages" in tables
    assert "companion_proposals" in tables


def test_create_and_get_session(conn):
    s = create_session(conn, article_id="art_123", title="Test Session")
    assert s["id"].startswith("ses_")
    assert s["article_id"] == "art_123"
    assert s["title"] == "Test Session"

    fetched = get_session(conn, s["id"])
    assert fetched is not None
    assert fetched["id"] == s["id"]
    assert fetched["title"] == "Test Session"


def test_list_sessions(conn):
    s1 = create_session(conn, article_id="art_1", title="Session 1")
    s2 = create_session(conn, article_id="art_1", title="Session 2")
    s3 = create_session(conn, article_id="art_2", title="Session 3")

    art1_sessions = list_sessions(conn, article_id="art_1")
    assert len(art1_sessions) == 2
    assert {s["id"] for s in art1_sessions} == {s1["id"], s2["id"]}

    all_sessions = list_sessions(conn, article_id=None)
    assert len(all_sessions) == 3
    assert {s["id"] for s in all_sessions} == {s1["id"], s2["id"], s3["id"]}


def test_append_and_get_messages(conn):
    s = create_session(conn, article_id="art_1", title="Chat")
    sid = s["id"]

    m1 = append_message(
        conn,
        session_id=sid,
        role="user",
        content="Was bedeutet anfallen?",
    )
    assert m1["id"].startswith("msg_")
    assert m1["role"] == "user"

    m2 = append_message(
        conn,
        session_id=sid,
        role="assistant",
        content="Anfallen hat mehrere Bedeutungen...",
        thought="Linguistische Analyse...",
        reasoning_effort="high",
    )
    assert m2["role"] == "assistant"
    assert m2["thought"] == "Linguistische Analyse..."
    assert m2["reasoning_effort"] == "high"

    msgs = get_messages(conn, session_id=sid)
    assert len(msgs) == 2
    assert msgs[0]["id"] == m1["id"]
    assert msgs[1]["id"] == m2["id"]


def test_deferred_message_and_proposal_writes_roll_back_together(conn):
    s = create_session(conn, article_id="art_1", title="Atomic Chat")
    sid = s["id"]

    append_message(conn, session_id=sid, role="user", content="Hallo", commit=False)
    create_proposal(
        conn,
        session_id=sid,
        action="create_vocab_cards",
        title="die Eule",
        payload={"cards": [{"word": "die Eule"}]},
        proposal_id="prop_deferred",
        commit=False,
    )
    conn.rollback()

    assert get_messages(conn, session_id=sid) == []
    assert get_proposals(conn, session_id=sid) == []


def test_scope_key_additive_migration_and_legacy_history_readable():
    """老库没有 scope_key 列：init 必须补列，旧会话归入 view:global 且历史可读。"""
    legacy = sqlite3.connect(":memory:")
    legacy.row_factory = sqlite3.Row
    legacy.execute(
        """
        CREATE TABLE companion_sessions (
            id TEXT PRIMARY KEY,
            article_id TEXT,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_archived INTEGER DEFAULT 0
        )
        """
    )
    legacy.execute(
        "INSERT INTO companion_sessions (id, article_id, title) VALUES ('ses_legacy', 'art_old', '旧会话')"
    )
    legacy.commit()

    init_companion_tables(legacy)

    columns = {row[1] for row in legacy.execute("PRAGMA table_info(companion_sessions)").fetchall()}
    assert "scope_key" in columns

    row = legacy.execute(
        "SELECT scope_key FROM companion_sessions WHERE id = 'ses_legacy'"
    ).fetchone()
    assert row["scope_key"] == "view:global"

    fetched = get_session(legacy, "ses_legacy")
    assert fetched is not None
    assert fetched["title"] == "旧会话"
    legacy.close()


def test_scope_key_filter_and_creation(conn):
    """scope_key 为加法字段：写入/查询按 scope 隔离，旧 article_id 查询仍可用。"""
    s1 = create_session(conn, article_id="art_1", title="Article", scope_key="article:art_1")
    s2 = create_session(conn, article_id=None, title="Cards", scope_key="view:cards")

    assert s1["scope_key"] == "article:art_1"
    assert s2["scope_key"] == "view:cards"

    assert [s["id"] for s in list_sessions(conn, scope_key="article:art_1")] == [s1["id"]]
    assert [s["id"] for s in list_sessions(conn, scope_key="view:cards")] == [s2["id"]]
    assert [s["id"] for s in list_sessions(conn, article_id="art_1")] == [s1["id"]]


def test_proposals_lifecycle(conn):
    s = create_session(conn, article_id="art_1", title="Proposal Chat")
    sid = s["id"]

    p = create_proposal(
        conn,
        session_id=sid,
        action="create_vocab_card",
        title="anfallen",
        payload={"word": "anfallen", "reading": "发生，产生"},
    )
    assert p["id"].startswith("prop_")
    assert p["status"] == "pending"
    assert p["payload"]["word"] == "anfallen"

    props = get_proposals(conn, session_id=sid, status="pending")
    assert len(props) == 1
    assert props[0]["id"] == p["id"]

    # Update status to accepted
    ok = update_proposal_status(conn, proposal_id=p["id"], status="accepted")
    assert ok is True

    # Now pending should be empty and accepted should have 1
    assert len(get_proposals(conn, session_id=sid, status="pending")) == 0
    accepted = get_proposals(conn, session_id=sid, status="accepted")
    assert len(accepted) == 1
    assert accepted[0]["status"] == "accepted"
