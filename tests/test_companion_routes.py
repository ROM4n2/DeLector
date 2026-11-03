# -*- coding: utf-8 -*-
"""伴学路由与 SSE 流式契约测试 (Task 2).

依据: docs/plans/archive/2026-10-31-companion-study-agent.md Task 2.
"""

from __future__ import annotations

import json
import random
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from delector.routes.companion import _SSEEventAccumulator
from delector.routes.companion import router as companion_router


@pytest.fixture
def companion_app() -> FastAPI:
    app = FastAPI()
    app.include_router(companion_router)
    return app


def test_companion_context_endpoint(companion_app: FastAPI) -> None:
    """GET /api/companion/context 返回当前学情上下文."""
    client = TestClient(companion_app)
    resp = client.get("/api/companion/context")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "context" in data
    assert "date" in data["context"]


def test_companion_chat_sse_stream(companion_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/companion/chat 产生合法的 text/event-stream 流式帧 (桩隔离，不出网)."""
    async def _mock_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "thought": "测试语法结构推演",
            "reply_de": "Hallo!",
            "reply_zh": "这是测试解答。",
        }

    monkeypatch.setattr("delector.services.companion_agent.llm_client.chat", _mock_chat)

    client = TestClient(companion_app)
    req_body = {
        "messages": [{"role": "user", "content": "Hallo Eule!"}],
    }

    with client.stream("POST", "/api/companion/chat", json=req_body) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = []
        current_event = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line.replace("event: ", "").strip()
            elif line.startswith("data: "):
                raw_data = line.replace("data: ", "").strip()
                payload = json.loads(raw_data)
                events.append({"event": current_event, "data": payload})

        assert len(events) > 0
        event_types = [e["event"] for e in events]
        assert "done" in event_types
        assert any(e["event"] in ("delta", "thought") for e in events)


@pytest.mark.parametrize(
    "blank_line",
    [b"\r\n\r\n", b"\r\n\n", b"\n\r\n"],
    ids=["crlf", "crlf-lf", "lf-crlf"],
)
def test_sse_accumulator_crlf_multiline_waits_for_blank_line(blank_line: bytes) -> None:
    """CRLF 只是单个换行；多行 data 必须等真正空行到达后一次解析."""
    accumulator = _SSEEventAccumulator()
    incomplete_frame = (
        b"event: delta\r\n"
        b'data: {"event":"delta",\r\n'
        b'data: "text":"Hallo"}'
    )

    assert accumulator.feed(incomplete_frame) == []
    assert accumulator.feed(blank_line) == [{"event": "delta", "text": "Hallo"}]


@pytest.mark.parametrize("strategy", ["json-middle", "three", "n", "byte", "random"])
def test_companion_chat_sse_fragmentation_preserves_events_and_persistence(
    companion_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
) -> None:
    """任意网络分片不得改变转发字节、事件聚合或持久化次数."""

    def _frame(event: str, payload: dict[str, Any]) -> bytes:
        body = {"event": event, **payload}
        return (
            f"event: {event}\ndata: ".encode("utf-8")
            + json.dumps(body, ensure_ascii=False).encode("utf-8")
            + b"\n\n"
        )

    proposal = {
        "id": "prop_fragmented_01",
        "action": "create_vocab_cards",
        "title": "加入核心生词卡",
        "payload": {"cards": [{"word": "die Eule", "definition_zh": "猫头鹰"}]},
    }
    other_proposal = {**proposal, "id": "prop_fragmented_02"}
    stream = b"".join(
        [
            _frame("thought", {"text": "分析语序"}),
            _frame("delta", {"text": "Hallo "}),
            _frame("delta", {"text": "Eule."}),
            _frame("proposal", {"proposal": proposal}),
            _frame("proposal", {"proposal": proposal}),
            _frame("proposal", {"proposal": other_proposal}),
            _frame("done", {"reason": "ok"}),
        ]
    )

    if strategy == "json-middle":
        marker = b'"text": "Hallo '
        cut = stream.index(marker) + len(marker) + 1
        chunks = [stream[:cut], stream[cut:]]
    elif strategy == "three":
        first, second = len(stream) // 3, 2 * len(stream) // 3
        chunks = [stream[:first], stream[first:second], stream[second:]]
    elif strategy == "n":
        chunks = [stream[offset : offset + 17] for offset in range(0, len(stream), 17)]
    elif strategy == "byte":
        chunks = [stream[offset : offset + 1] for offset in range(len(stream))]
    else:
        rng = random.Random(20261103)
        chunks = []
        offset = 0
        while offset < len(stream):
            size = rng.randint(1, 23)
            chunks.append(stream[offset : offset + size])
            offset += size

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        for chunk in chunks:
            yield chunk

    save_calls: list[dict[str, Any]] = []
    proposal_calls: list[dict[str, Any]] = []

    def _fake_save_turn(session_id: str, user: str, assistant: str, thought: str = ""):
        save_calls.append(
            {"session_id": session_id, "user": user, "assistant": assistant, "thought": thought}
        )
        return {"id": "user-msg"}, {"id": "assistant-msg"}

    def _fake_create_proposal(**kwargs: Any):
        proposal_calls.append(kwargs)
        return {"id": kwargs.get("proposal_id")}

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)
    monkeypatch.setattr("delector.routes.companion._session_svc.save_turn", _fake_save_turn)
    monkeypatch.setattr("delector.routes.companion._proposal_svc.create_proposal", _fake_create_proposal)

    client = TestClient(companion_app)
    body = {
        "session_id": "session-fragmented",
        "messages": [{"role": "user", "content": "Hallo"}],
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        assert b"".join(response.iter_bytes()) == stream

    assert save_calls == [
        {
            "session_id": "session-fragmented",
            "user": "Hallo",
            "assistant": "Hallo Eule.",
            "thought": "分析语序",
        }
    ]
    assert [call["proposal_id"] for call in proposal_calls] == [
        "prop_fragmented_01",
        "prop_fragmented_02",
    ]
    assert proposal_calls[0]["session_id"] == "session-fragmented"
    assert proposal_calls[0]["message_id"] == "assistant-msg"
    assert proposal_calls[0]["payload"] == proposal["payload"]
    assert proposal_calls[1]["payload"] == other_proposal["payload"]


def test_companion_proposal_execute_localhost_gate(companion_app: FastAPI) -> None:
    """POST /api/companion/proposal/execute 仅限 localhost 执行 (403 闸)."""
    # TestClient 默认 client.host 为 "testclient"，非 127.0.0.1
    # 模拟外部 IP 触发 403 闸
    client = TestClient(companion_app, client=("192.168.1.100", 50000))
    proposal_req = {
        "proposal_id": "prop_test_01",
        "action": "create_vocab_cards",
        "payload": {
            "cards": [
                {"word": "die Eule", "reading": "猫头鹰", "context_sentence": "Die Eule ist klug."}
            ]
        },
    }
    resp = client.post("/api/companion/proposal/execute", json=proposal_req)
    assert resp.status_code == 403


def test_companion_proposal_execute_success(
    companion_app: FastAPI, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/companion/proposal/execute 在 localhost 成功落盘生词卡."""
    import sqlite3
    db_file = tmp_path / "test_delector.db"
    conn = sqlite3.connect(db_file)
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

    # 将 DATABASE_PATH 指向临时库
    monkeypatch.setenv("DATABASE_PATH", str(db_file))

    client = TestClient(companion_app, client=("127.0.0.1", 50000))
    proposal_req = {
        "proposal_id": "prop_test_02",
        "action": "create_vocab_cards",
        "payload": {
            "cards": [
                {"word": "das Abenteuer", "reading": "冒险", "context_sentence": "Ein großes Abenteuer."}
            ]
        },
    }
    resp = client.post("/api/companion/proposal/execute", json=proposal_req)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data.get("status") == "ok"
    assert res_data.get("created_count") == 1


def test_companion_chat_scope_isolation_and_session_header(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """scope_key 隔离会话；无 session_id 时用响应头 X-Session-ID 稳定命中同一会话。"""
    db_file = tmp_path / "scope_isolation.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))

    captured_contexts: list[Any] = []

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        captured_contexts.append(kwargs.get("context"))
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app)

    def _chat(scope_key: str, extra: dict[str, Any] | None = None) -> str:
        body = {"messages": [{"role": "user", "content": "Hallo"}], "scope_key": scope_key}
        body.update(extra or {})
        with client.stream("POST", "/api/companion/chat", json=body) as response:
            assert response.status_code == 200
            sid = response.headers.get("x-session-id")
            assert sid
            list(response.iter_lines())
        return sid

    sid_cards_1 = _chat("view:cards", {"view": "cards", "context_source": "none"})
    sid_cards_2 = _chat("view:cards")
    sid_progress = _chat("view:progress")

    assert sid_cards_1 == sid_cards_2
    assert sid_progress != sid_cards_1
    assert captured_contexts[0] == {"view": "cards", "context_source": "none"}

    scoped = client.get("/api/companion/sessions/scoped/view:cards")
    assert scoped.status_code == 200
    scoped_ids = [s["id"] for s in scoped.json()["sessions"]]
    assert scoped_ids == [sid_cards_1]


def test_companion_sessions_global_list_and_scoped_default_unchanged(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全局列表覆盖所有 scope；scoped 端点缺省行为不变（仍只回本 scope）。"""
    from delector.services.companion_session import CompanionSessionService

    db_file = tmp_path / "global_sessions.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    svc = CompanionSessionService(db_path=str(db_file))
    article = svc.get_or_create_session(article_id="3", scope_key="article:3")
    cards = svc.get_or_create_session(scope_key="view:cards")

    client = TestClient(companion_app)
    all_sessions = client.get("/api/companion/sessions").json()["sessions"]
    ids = {s["id"] for s in all_sessions}
    assert {article["id"], cards["id"]} <= ids

    scoped = client.get("/api/companion/sessions/scoped/view:cards").json()["sessions"]
    assert [s["id"] for s in scoped] == [cards["id"]]


def test_companion_chat_without_new_fields_keeps_legacy_context(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不填 view/context_source/scope_key 时，context 原样透传（缺省路径不变）。"""
    db_file = tmp_path / "legacy_context.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))

    captured: dict[str, Any] = {}

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        captured["context"] = kwargs.get("context")
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app)
    body = {
        "messages": [{"role": "user", "content": "Hallo"}],
        "context": {"selected_text": "Der Satz.", "article_title": "T", "cefr_level": "B1"},
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        list(response.iter_lines())

    assert captured["context"] == {
        "selected_text": "Der Satz.",
        "article_title": "T",
        "cefr_level": "B1",
    }


def test_companion_chat_forwards_draft_text(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """draft_text 可选字段必须原样进入 context，供 writing_check 使用。"""
    db_file = tmp_path / "writer_draft.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    captured: dict[str, Any] = {}
    draft = "Ich habe hunger und gehe in der Schule."

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        captured["context"] = kwargs.get("context")
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app)
    body = {
        "messages": [{"role": "user", "content": "检查当前草稿"}],
        "view": "writer",
        "context_source": "writer-draft",
        "draft_text": draft,
        "scope_key": "view:writer",
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        list(response.iter_lines())

    assert captured["context"] == {
        "view": "writer",
        "context_source": "writer-draft",
        "draft_text": draft,
    }


def test_companion_chat_forwards_card_context(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """card_context 可选字段必须原样进入 context，供 propose_vocab_cards 使用。"""
    db_file = tmp_path / "card_context.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    captured: dict[str, Any] = {}
    card_context = "【当前卡盒词条】\n分段: due\n词: die Eule\n词元: Eule\n释义: 猫头鹰"

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        captured["context"] = kwargs.get("context")
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app)
    body = {
        "messages": [{"role": "user", "content": "基于当前卡盒词条扩展生词"}],
        "view": "cards",
        "context_source": "card-current",
        "card_context": card_context,
        "scope_key": "view:cards",
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        list(response.iter_lines())

    assert captured["context"] == {
        "view": "cards",
        "context_source": "card-current",
        "card_context": card_context,
    }


def test_companion_chat_persists_proposal_for_query(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产 chat 路径产生的 proposal 必须落库，GET /sessions/{id}/proposals 可查。"""
    db_file = tmp_path / "chat_proposals.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))

    proposal = {
        "id": "prop_chat_01",
        "action": "create_vocab_cards",
        "title": "扩展 die Eule 相关生词",
        "payload": {"cards": [{"word": "die Nacht", "definition_zh": "夜晚"}]},
    }
    proposal_chunk = (
        b'event: proposal\ndata: '
        + json.dumps({"event": "proposal", "proposal": proposal}, ensure_ascii=False).encode("utf-8")
        + b"\n\n"
    )

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        yield proposal_chunk
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app)
    body = {
        "messages": [{"role": "user", "content": "基于当前卡盒词条扩展生词"}],
        "view": "cards",
        "context_source": "card-current",
        "scope_key": "view:cards",
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        sid = response.headers.get("x-session-id")
        list(response.iter_lines())

    assert sid
    resp = client.get(f"/api/companion/sessions/{sid}/proposals")
    assert resp.status_code == 200
    proposals = resp.json()["proposals"]
    assert [p["id"] for p in proposals] == ["prop_chat_01"]
    assert proposals[0]["status"] == "pending"
    assert proposals[0]["action"] == "create_vocab_cards"
    assert proposals[0]["payload"]["cards"][0]["word"] == "die Nacht"


def test_companion_chat_persists_weekly_goal_proposal(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新 action 仍复用同一 SSE proposal 帧与 proposal.id 落库。"""
    db_file = tmp_path / "weekly_goal_sse.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    proposal = {
        "id": "prop_weekly_goal_sse",
        "action": "set_weekly_goal",
        "title": "本周学习目标",
        "payload": {"goal": "本周完成 20 张卡片复习"},
    }

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        yield (
            b'event: proposal\ndata: '
            + json.dumps({"event": "proposal", "proposal": proposal}, ensure_ascii=False).encode("utf-8")
            + b"\n\n"
        )
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)
    client = TestClient(companion_app)
    body = {"messages": [{"role": "user", "content": "生成本周目标"}], "scope_key": "view:progress"}
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        sid = response.headers.get("x-session-id")
        list(response.iter_lines())

    proposals = client.get(f"/api/companion/sessions/{sid}/proposals").json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["id"] == "prop_weekly_goal_sse"
    assert proposals[0]["action"] == "set_weekly_goal"
    assert proposals[0]["payload"]["goal"] == "本周完成 20 张卡片复习"
    assert proposals[0]["status"] == "pending"


def test_companion_proposal_reject_marks_status_without_writing_cards(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拒绝提议：状态流转为 rejected，不写任何卡片；重复拒绝返回 404。"""
    import sqlite3

    db_file = tmp_path / "reject_proposal.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    conn = sqlite3.connect(db_file)
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

    async def _fake_dispatch(*args: Any, **kwargs: Any):
        proposal = {
            "id": "prop_chat_reject",
            "action": "create_vocab_cards",
            "title": "扩展 die Eule 相关生词",
            "payload": {"cards": [{"word": "das Insekt", "definition_zh": "昆虫"}]},
        }
        yield (
            b'event: proposal\ndata: '
            + json.dumps({"event": "proposal", "proposal": proposal}, ensure_ascii=False).encode("utf-8")
            + b"\n\n"
        )
        yield b'event: done\ndata: {"event":"done","reason":"ok"}\n\n'

    monkeypatch.setattr("delector.routes.companion.dispatch_companion_stream", _fake_dispatch)

    client = TestClient(companion_app, client=("127.0.0.1", 50000))
    body = {
        "messages": [{"role": "user", "content": "基于当前卡盒词条扩展生词"}],
        "scope_key": "view:cards",
    }
    with client.stream("POST", "/api/companion/chat", json=body) as response:
        assert response.status_code == 200
        sid = response.headers.get("x-session-id")
        list(response.iter_lines())
    assert sid

    resp = client.post("/api/companion/proposal/reject", json={"proposal_id": "prop_chat_reject"})
    assert resp.status_code == 200
    assert resp.json()["rejected"] is True

    rejected = client.get(
        f"/api/companion/sessions/{sid}/proposals", params={"status": "rejected"}
    ).json()["proposals"]
    assert [p["id"] for p in rejected] == ["prop_chat_reject"]

    conn = sqlite3.connect(db_file)
    count = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    conn.close()
    assert count == 0

    again = client.post("/api/companion/proposal/reject", json={"proposal_id": "prop_chat_reject"})
    assert again.status_code == 404


def test_companion_proposal_execute_empty_cards_returns_400(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空提议 execute 返回 400，且提议保持 pending（不得被标成 accepted）。"""
    from delector.services.companion_proposal import CompanionProposalService
    from delector.services.companion_session import CompanionSessionService

    db_file = tmp_path / "empty_cards.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    session_svc = CompanionSessionService(db_path=str(db_file))
    sid = session_svc.get_or_create_session(scope_key="view:cards")["id"]
    prop_svc = CompanionProposalService(db_path=str(db_file))
    prop = prop_svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="暂无可制卡语料",
        payload={"cards": []},
    )

    client = TestClient(companion_app, client=("127.0.0.1", 50000))
    resp = client.post(
        "/api/companion/proposal/execute",
        json={"proposal_id": prop["id"], "action": "create_vocab_cards", "payload": {"cards": []}},
    )
    assert resp.status_code == 400
    assert "没有可入库的词条" in resp.json()["detail"]
    assert [p["status"] for p in prop_svc.list_proposals(sid)] == ["pending"]


def test_companion_proposal_reject_localhost_gate(companion_app: FastAPI) -> None:
    """POST /api/companion/proposal/reject 仅限 localhost。"""
    client = TestClient(companion_app, client=("192.168.1.100", 50000))
    resp = client.post("/api/companion/proposal/reject", json={"proposal_id": "prop_test_01"})
    assert resp.status_code == 403


def test_companion_chat_proxies_to_go_agent_when_available(
    companion_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当 DELECTOR_GO_AGENT_URL 就绪时，FastAPI 路由优先流式反代 Go Agent SSE 帧并同步设置."""
    import httpx

    captured_headers: dict[str, str] = {}

    class _MockGoTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            content = (
                b"event: delta\ndata: {\"event\": \"delta\", \"text\": \"From Go Agent\"}\n\n"
                b"event: done\ndata: {\"event\": \"done\", \"reason\": \"ok\"}\n\n"
            )
            return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    # 替换 httpx.AsyncClient 的 transport
    orig_async_client = httpx.AsyncClient

    def _mock_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = _MockGoTransport()
        return orig_async_client(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _mock_async_client)
    monkeypatch.setenv("DELECTOR_GO_AGENT_URL", "http://127.0.0.1:8002")
    monkeypatch.setattr("delector.core.db.settings.get_effective_api_key", lambda: "sk-synced-test-key")

    client = TestClient(companion_app)
    req_body = {
        "messages": [{"role": "user", "content": "Hallo!"}],
    }

    with client.stream("POST", "/api/companion/chat", json=req_body) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
        combined = "\n".join(lines)
        assert "From Go Agent" in combined
        assert "done" in combined
        assert captured_headers.get("x-api-key") == "sk-synced-test-key"


def test_companion_weekly_goal_empty_execute_returns_400_and_pending(
    companion_app: FastAPI,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空周目标走统一 ValueError→400，状态保持 pending。"""
    from delector.services.companion_proposal import CompanionProposalService
    from delector.services.companion_session import CompanionSessionService

    db_file = tmp_path / "empty_weekly_goal.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    sid = CompanionSessionService(db_path=str(db_file)).get_or_create_session(scope_key="view:progress")["id"]
    svc = CompanionProposalService(db_path=str(db_file))
    prop = svc.create_proposal(
        session_id=sid,
        action="set_weekly_goal",
        title="本周学习目标",
        payload={"goal": " "},
    )

    client = TestClient(companion_app, client=("127.0.0.1", 50000))
    resp = client.post(
        "/api/companion/proposal/execute",
        json={"proposal_id": prop["id"], "action": prop["action"], "payload": prop["payload"]},
    )

    assert resp.status_code == 400
    assert "学习目标不能为空" in resp.json()["detail"]
    assert svc.list_proposals(sid)[0]["status"] == "pending"
