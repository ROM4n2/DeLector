"""
Unit tests for companion SQLite persistence (sessions, messages, proposals).
"""
import sqlite3
import pytest
from delector.core.db.companion import (
    init_companion_tables,
    create_session,
    get_session,
    list_sessions,
    append_message,
    get_messages,
    create_proposal,
    get_proposals,
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
