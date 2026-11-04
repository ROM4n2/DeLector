# -*- coding: utf-8 -*-
"""Unit and integration tests for CompanionSessionService and CompanionProposalService."""

from __future__ import annotations

import sqlite3
from typing import Any, Generator

import pytest

from delector.core.db.companion import init_companion_tables
from delector.services.companion_proposal import CompanionProposalService
from delector.services.companion_session import CompanionSessionService


@pytest.fixture
def test_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Sets up an isolated SQLite test database with schema initialized."""
    db_file = str(tmp_path / "companion_services_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_file)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    init_companion_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vocab_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            lemma TEXT NOT NULL,
            pos TEXT,
            gender TEXT,
            plural TEXT,
            cefr_level TEXT,
            definition_zh TEXT NOT NULL,
            sentence_context TEXT NOT NULL,
            source TEXT DEFAULT 'companion',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mastered INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()
    yield db_file


def test_session_service_get_or_create_new(test_db: str) -> None:
    svc = CompanionSessionService(db_path=test_db)
    session = svc.get_or_create_session(article_id="art_01", title="文章伴学")
    assert session is not None
    assert session["id"].startswith("ses_")
    assert session["article_id"] == "art_01"
    assert session["title"] == "文章伴学"


def test_session_service_get_or_create_existing(test_db: str) -> None:
    svc = CompanionSessionService(db_path=test_db)
    s1 = svc.get_or_create_session(article_id="art_02", title="首个会话")
    s2 = svc.get_or_create_session(article_id="art_02", title="重复会话")
    assert s1["id"] == s2["id"]
    assert s2["title"] == "首个会话"


def test_session_service_scope_isolation(test_db: str) -> None:
    """不同 scope 不会互相取到会话；同 scope 重复取到同一个会话。"""
    svc = CompanionSessionService(db_path=test_db)
    article_s = svc.get_or_create_session(article_id="art_scope", scope_key="article:art_scope")
    cards_s = svc.get_or_create_session(scope_key="view:cards")

    assert article_s["id"] != cards_s["id"]
    again = svc.get_or_create_session(article_id="art_scope", scope_key="article:art_scope")
    assert again["id"] == article_s["id"]

    assert [s["id"] for s in svc.list_recent_sessions(scope_key="article:art_scope")] == [article_s["id"]]
    assert [s["id"] for s in svc.list_recent_sessions(scope_key="view:cards")] == [cards_s["id"]]


def test_session_service_save_turn_and_history(test_db: str) -> None:
    svc = CompanionSessionService(db_path=test_db)
    session = svc.get_or_create_session(article_id="art_03")
    sid = session["id"]

    u_msg, a_msg = svc.save_turn(
        session_id=sid,
        user_content="Was bedeutet anfallen?",
        assistant_content="Anfallen hat mehrere Bedeutungen...",
        thought="Linguistische Analyse...",
        reasoning_effort="high",
        token_usage={"prompt_tokens": 15, "completion_tokens": 30},
    )

    assert u_msg["role"] == "user"
    assert u_msg["content"] == "Was bedeutet anfallen?"
    assert a_msg["role"] == "assistant"
    assert a_msg["content"] == "Anfallen hat mehrere Bedeutungen..."
    assert a_msg["thought"] == "Linguistische Analyse..."
    assert a_msg["reasoning_effort"] == "high"
    assert a_msg["token_usage"] == {"prompt_tokens": 15, "completion_tokens": 30}

    history = svc.get_history(sid)
    assert len(history) == 2
    assert history[0]["id"] == u_msg["id"]
    assert history[1]["id"] == a_msg["id"]


def test_save_turn_rolls_back_user_when_assistant_append_fails(
    test_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from delector.services import companion_session

    svc = CompanionSessionService(db_path=test_db)
    sid = svc.get_or_create_session()["id"]
    real_append_message = companion_session.append_message

    def _fail_assistant(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("role") == "assistant":
            raise RuntimeError("injected assistant append failure")
        return real_append_message(*args, **kwargs)

    monkeypatch.setattr(companion_session, "append_message", _fail_assistant)
    with pytest.raises(RuntimeError, match="injected assistant append failure"):
        svc.save_turn(sid, "Hallo", "Eule")

    assert [message["role"] for message in svc.get_history(sid)] == []


def test_save_turn_snapshot_rolls_back_messages_when_proposal_fails(
    test_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from delector.services import companion_session

    svc = CompanionSessionService(db_path=test_db)
    sid = svc.get_or_create_session()["id"]

    def _fail_proposal(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("injected proposal failure")

    monkeypatch.setattr(companion_session, "create_proposal", _fail_proposal)
    with pytest.raises(RuntimeError, match="injected proposal failure"):
        svc.save_turn_snapshot(
            sid,
            "Hallo",
            "Eule",
            proposals=[
                {
                    "id": "prop_atomic_failure",
                    "action": "create_vocab_cards",
                    "title": "die Eule",
                    "payload": {"cards": [{"word": "die Eule"}]},
                }
            ],
        )

    assert svc.get_history(sid) == []
    assert CompanionProposalService(db_path=test_db).list_proposals(sid) == []


def test_session_service_list_recent_sessions(test_db: str) -> None:
    svc = CompanionSessionService(db_path=test_db)
    s1 = svc.get_or_create_session(article_id="art_10", title="会话1")
    s2 = svc.get_or_create_session(article_id="art_20", title="会话2")

    all_recent = svc.list_recent_sessions(limit=10)
    assert len(all_recent) >= 2
    session_ids = [s["id"] for s in all_recent]
    assert s1["id"] in session_ids
    assert s2["id"] in session_ids

    art10_recent = svc.list_recent_sessions(article_id="art_10")
    assert len(art10_recent) == 1
    assert art10_recent[0]["id"] == s1["id"]


def test_proposal_service_create_and_list(test_db: str) -> None:
    session_svc = CompanionSessionService(db_path=test_db)
    session = session_svc.get_or_create_session()
    sid = session["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="die Eule",
        payload={"cards": [{"word": "die Eule", "reading": "猫头鹰"}]},
    )
    assert prop["id"].startswith("prop_")
    assert prop["status"] == "pending"
    assert prop["action"] == "create_vocab_cards"

    pending_list = prop_svc.list_proposals(sid, status="pending")
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == prop["id"]

    accepted_list = prop_svc.list_proposals(sid, status="accepted")
    assert len(accepted_list) == 0


def test_proposal_service_execute_success(test_db: str) -> None:
    session_svc = CompanionSessionService(db_path=test_db)
    session = session_svc.get_or_create_session()
    sid = session["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="der Hund",
        payload={
            "cards": [
                {
                    "word": "der Hund",
                    "reading": "[hʊnt]",
                    "definition_zh": "狗",
                    "context_sentence": "Der Hund bellt.",
                    "lemma": "Hund",
                    "pos": "noun",
                    "gender": "masculine",
                }
            ]
        },
    )

    res = prop_svc.execute_proposal(
        proposal_id=prop["id"],
        action="create_vocab_cards",
        payload=prop["payload"],
    )
    assert res["status"] == "ok"
    assert res["proposal_id"] == prop["id"]
    assert res["action"] == "create_vocab_cards"
    assert res["created_count"] == 1

    # Check status changed to accepted
    proposals = prop_svc.list_proposals(sid, status="accepted")
    assert len(proposals) == 1
    assert proposals[0]["id"] == prop["id"]

    # Verify SQLite vocab_cards table contains the card
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM vocab_cards WHERE word = ?", ("der Hund",)).fetchone()
    conn.close()
    assert row is not None
    assert row["lemma"] == "Hund"
    assert row["definition_zh"] == "狗"


def test_proposal_service_never_stores_reading_as_definition(test_db: str) -> None:
    """只有 reading（读音/音标）时，definition_zh 必须留空，绝不用音标冒充中文释义。"""
    session_svc = CompanionSessionService(db_path=test_db)
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="der Witwer",
        payload={
            "cards": [
                {
                    "word": "der Witwer",
                    "reading": "[ˈvɪtvɐ]",
                    "context_sentence": "Der Witwer trauert.",
                }
            ]
        },
    )

    res = prop_svc.execute_proposal(prop["id"], "create_vocab_cards", prop["payload"])
    assert res["status"] == "ok"
    assert res["created_count"] == 1

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM vocab_cards WHERE word = ?", ("der Witwer",)).fetchone()
    conn.close()
    assert row is not None
    assert row["definition_zh"] == ""
    assert row["definition_zh"] != "[ˈvɪtvɐ]"


def test_proposal_service_execute_single_card_action(test_db: str) -> None:
    session_svc = CompanionSessionService(db_path=test_db)
    session = session_svc.get_or_create_session()
    sid = session["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_card",
        title="die Katze",
        payload={
            "word": "die Katze",
            "definition_zh": "猫",
            "reading": "[ˈkaːtsə]",
            "sentence_context": "Die Katze schläft.",
        },
    )

    res = prop_svc.execute_proposal(
        proposal_id=prop["id"],
        action="create_vocab_card",
        payload=prop["payload"],
    )
    assert res["status"] == "ok"
    assert res["created_count"] == 1

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM vocab_cards WHERE word = ?", ("die Katze",)).fetchone()
    conn.close()
    assert row is not None
    assert row["definition_zh"] == "猫"


def test_proposal_service_execute_idempotence(test_db: str) -> None:
    session_svc = CompanionSessionService(db_path=test_db)
    session = session_svc.get_or_create_session()
    sid = session["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="Idempotent Card",
        payload={"cards": [{"word": "das Buch", "reading": "书"}]},
    )

    res1 = prop_svc.execute_proposal(prop["id"], "create_vocab_cards", prop["payload"])
    assert res1["status"] == "ok"
    assert res1["created_count"] == 1

    # Re-executing the same accepted proposal should be idempotent (prevent replay)
    res2 = prop_svc.execute_proposal(prop["id"], "create_vocab_cards", prop["payload"])
    assert res2["status"] == "ok"
    assert res2["created_count"] == 0

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM vocab_cards WHERE word = 'das Buch'").fetchone()[0]
    conn.close()
    assert count == 1


def test_proposal_service_execute_rejects_empty_cards(test_db: str) -> None:
    """空 cards 列表不得被确认成 accepted：报错、状态保持 pending、零写卡。"""
    session_svc = CompanionSessionService(db_path=test_db)
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]
    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="暂无可制卡语料",
        payload={"cards": []},
    )

    with pytest.raises(ValueError, match="没有可入库的词条"):
        prop_svc.execute_proposal(prop["id"], "create_vocab_cards", prop["payload"])

    assert [p["status"] for p in prop_svc.list_proposals(sid)] == ["pending"]
    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    conn.close()
    assert count == 0


def test_proposal_service_execute_rejects_card_without_word(test_db: str) -> None:
    """cards 里没有任何有效 word 同样视为畸形提议，不得写库或置 accepted。"""
    session_svc = CompanionSessionService(db_path=test_db)
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]
    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="畸形提议",
        payload={"cards": [{"definition_zh": "狗"}, "not-a-dict"]},
    )

    with pytest.raises(ValueError, match="没有可入库的词条"):
        prop_svc.execute_proposal(prop["id"], "create_vocab_cards", prop["payload"])
    assert [p["status"] for p in prop_svc.list_proposals(sid)] == ["pending"]


def test_proposal_service_unsupported_action(test_db: str) -> None:
    prop_svc = CompanionProposalService(db_path=test_db)
    with pytest.raises(ValueError, match="不支持的提议动作类型"):
        prop_svc.execute_proposal("prop_xyz", "unsupported_action", {})


def test_proposal_service_create_reuses_sse_proposal_id(test_db: str) -> None:
    """聊天流里的 proposal id 必须原样复用，前端确认/拒绝才能命中同一行。"""
    session_svc = CompanionSessionService(db_path=test_db)
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="扩展 die Eule 相关生词",
        payload={"cards": [{"word": "die Nacht", "definition_zh": "夜晚"}]},
        proposal_id="prop_chat_01",
    )
    assert prop["id"] == "prop_chat_01"
    assert [p["id"] for p in prop_svc.list_proposals(sid)] == ["prop_chat_01"]


def test_proposal_service_reject_does_not_write_cards(test_db: str) -> None:
    """拒绝只流转状态：rejected；绝不向 vocab_cards 写卡，重复拒绝不再生效。"""
    session_svc = CompanionSessionService(db_path=test_db)
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]

    prop_svc = CompanionProposalService(db_path=test_db)
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="扩展 die Eule 相关生词",
        payload={"cards": [{"word": "das Insekt", "definition_zh": "昆虫"}]},
    )

    res = prop_svc.reject_proposal(prop["id"])
    assert res["rejected"] is True
    assert res["status"] == "ok"

    assert [p["id"] for p in prop_svc.list_proposals(sid, status="rejected")] == [prop["id"]]
    assert prop_svc.list_proposals(sid, status="pending") == []

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    conn.close()
    assert count == 0

    again = prop_svc.reject_proposal(prop["id"])
    assert again["rejected"] is False
    assert again["status"] == "not_found"


def test_routes_sessions_and_history_endpoints(test_db: str) -> None:
    """Verifies GET/POST /api/companion/sessions and history endpoints."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from delector.routes.companion import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Create a session
    resp = client.post("/api/companion/sessions", json={"article_id": "art_api", "title": "API测试会话"})
    assert resp.status_code == 200
    ses_data = resp.json()
    assert ses_data["status"] == "ok"
    sid = ses_data["session"]["id"]
    assert sid.startswith("ses_")

    # 2. List sessions
    resp_list = client.get("/api/companion/sessions?article_id=art_api")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert list_data["status"] == "ok"
    assert any(s["id"] == sid for s in list_data["sessions"])

    # 3. Query history (initially empty)
    resp_hist = client.get(f"/api/companion/sessions/{sid}/history")
    assert resp_hist.status_code == 200
    assert resp_hist.json()["status"] == "ok"
    assert resp_hist.json()["messages"] == []

    # 4. Query proposals
    resp_props = client.get(f"/api/companion/sessions/{sid}/proposals")
    assert resp_props.status_code == 200
    assert resp_props.json()["status"] == "ok"
    assert resp_props.json()["proposals"] == []


def test_chat_endpoint_saves_turns_to_session(test_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies POST /api/companion/chat saves turns when session_id is provided or generated."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from delector.routes.companion import router

    async def _mock_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "thought": "深层句法依存推演",
            "reply_de": "Auf Wiedersehen!",
            "reply_zh": "这是伴学解答。",
        }

    monkeypatch.setattr("delector.services.companion_agent.llm_client.chat", _mock_chat)
    monkeypatch.setattr("delector.services.companion_agent.get_effective_api_key", lambda: "mock-api-key")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    session_svc = CompanionSessionService(db_path=test_db)
    session = session_svc.get_or_create_session(article_id="art_turn", title="Turn测试")
    sid = session["id"]

    req_body = {
        "session_id": sid,
        "messages": [{"role": "user", "content": "Tschüss!"}],
    }

    with client.stream("POST", "/api/companion/chat", json=req_body) as response:
        assert response.status_code == 200
        # Drain stream to ensure turn persistence runs
        _ = list(response.iter_lines())

    # Verify message turn is saved in session history
    history = session_svc.get_history(sid)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Tschüss!"
    assert history[1]["role"] == "assistant"
    assert "这是伴学解答" in history[1]["content"]
    assert "深层句法依存推演" in history[1]["thought"]


def _init_multi_action_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS essays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            cefr_level TEXT,
            error_count INTEGER DEFAULT 0,
            sentence_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def test_weekly_goal_execute_is_idempotent(test_db: str) -> None:
    _init_multi_action_tables(test_db)
    sid = CompanionSessionService(db_path=test_db).get_or_create_session(scope_key="view:progress")["id"]
    svc = CompanionProposalService(db_path=test_db)
    prop = svc.create_proposal(
        session_id=sid,
        action="set_weekly_goal",
        title="本周学习目标",
        payload={"goal": "本周完成 20 张卡片复习"},
        proposal_id="prop_weekly_goal_idempotency",
    )

    first = svc.execute_proposal(prop["id"], prop["action"], prop["payload"])
    second = svc.execute_proposal(prop["id"], prop["action"], prop["payload"])

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'companion_weekly_goal'").fetchone()
    conn.close()
    assert row[0] == "本周完成 20 张卡片复习"


def test_writing_revision_execute_updates_essay_once(test_db: str) -> None:
    _init_multi_action_tables(test_db)
    sid = CompanionSessionService(db_path=test_db).get_or_create_session(scope_key="view:writer")["id"]
    conn = sqlite3.connect(test_db)
    essay_id = conn.execute(
        "INSERT INTO essays (title, content, analysis_json) VALUES (?, ?, ?)",
        ("Draft", "Der Hund bellt. Die Katze schläft.", "{}"),
    ).lastrowid
    conn.commit()
    conn.close()
    svc = CompanionProposalService(db_path=test_db)
    prop = svc.create_proposal(
        session_id=sid,
        action="apply_writing_revision",
        title="修订选中句子",
        payload={
            "essay_id": essay_id,
            "original_text": "Der Hund bellt.",
            "revised_text": "Der kleine Hund bellt laut.",
        },
        proposal_id="prop_writing_revision_idempotency",
    )

    first = svc.execute_proposal(prop["id"], prop["action"], prop["payload"])
    second = svc.execute_proposal(prop["id"], prop["action"], prop["payload"])

    assert first["created_count"] == 1
    assert first["content"] == "Der kleine Hund bellt laut. Die Katze schläft."
    assert second["created_count"] == 0
    conn = sqlite3.connect(test_db)
    content = conn.execute("SELECT content FROM essays WHERE id = ?", (essay_id,)).fetchone()[0]
    conn.close()
    assert content == "Der kleine Hund bellt laut. Die Katze schläft."


def test_rejected_multi_action_cannot_be_confirmed(test_db: str) -> None:
    _init_multi_action_tables(test_db)
    sid = CompanionSessionService(db_path=test_db).get_or_create_session(scope_key="view:progress")["id"]
    svc = CompanionProposalService(db_path=test_db)
    prop = svc.create_proposal(
        session_id=sid,
        action="set_weekly_goal",
        title="本周学习目标",
        payload={"goal": "每天复习 10 分钟"},
    )
    assert svc.reject_proposal(prop["id"])["rejected"] is True

    with pytest.raises(ValueError, match="已拒绝"):
        svc.execute_proposal(prop["id"], prop["action"], prop["payload"])

    assert svc.list_proposals(sid)[0]["status"] == "rejected"
    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM app_settings WHERE key = 'companion_weekly_goal'").fetchone()[0]
    conn.close()
    assert count == 0


@pytest.mark.parametrize(
    ("action", "payload", "message"),
    [
        ("set_weekly_goal", {"goal": "  "}, "学习目标不能为空"),
        ("apply_writing_revision", {"essay_id": 1, "original_text": "Alt.", "revised_text": ""}, "改写文本不能为空"),
        ("apply_writing_revision", {"original_text": "Alt.", "revised_text": "Neu."}, "essay_id"),
    ],
)
def test_multi_action_malformed_payload_stays_pending(
    test_db: str, action: str, payload: dict[str, Any], message: str
) -> None:
    _init_multi_action_tables(test_db)
    sid = CompanionSessionService(db_path=test_db).get_or_create_session()["id"]
    svc = CompanionProposalService(db_path=test_db)
    prop = svc.create_proposal(session_id=sid, action=action, title="畸形提议", payload=payload)

    with pytest.raises(ValueError, match=message):
        svc.execute_proposal(prop["id"], action, payload)

    assert svc.list_proposals(sid)[0]["status"] == "pending"
