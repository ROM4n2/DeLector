# -*- coding: utf-8 -*-
"""伴学路由与 SSE 流式契约测试 (Task 2).

依据: docs/plans/2026-10-31-companion-study-agent.md Task 2.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_companion_chat_sse_stream(companion_app: FastAPI) -> None:
    """POST /api/companion/chat 产生合法的 text/event-stream 流式帧."""
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
