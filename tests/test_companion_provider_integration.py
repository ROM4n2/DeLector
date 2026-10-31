# -*- coding: utf-8 -*-
"""伴学 Agent 多模型供应商抽象与全链路集成测试 (Task 4).

依据: docs/plans/2026-10-31-companion-provider-abstraction-and-pi-compaction.md Task 4.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from delector.routes.companion import router as companion_router


@pytest.fixture
def companion_app() -> FastAPI:
    app = FastAPI()
    app.include_router(companion_router)
    return app


def test_companion_deepseek_2026_model_header_forwarding(
    companion_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证当页面有效设置配置为 deepseek-flash 时，反代正确携带供应商 Header 转发给 Go Agent."""
    captured_headers: dict[str, str] = {}

    monkeypatch.setattr("delector.core.db.settings.get_effective_api_key", lambda: "sk-deepseek-test-redacted")
    monkeypatch.setattr("delector.core.db.settings.get_effective_api_base_url", lambda: "https://api.deepseek.com")
    monkeypatch.setattr("delector.core.db.settings.get_effective_api_model", lambda: "deepseek-flash")

    sse_lines = [
        b"event: thought\n",
        b'data: {"event":"thought","text":"\xe5\x8f\xa5\xe6\xb3\x95\xe6\x8e\xa8\xe6\xbc\x94"}\n\n',
        b"event: delta\n",
        b'data: {"event":"delta","text":"Hallo!"}\n\n',
        b"event: done\n",
        b'data: {"event":"done","turns":1,"reason":"stop"}\n\n',
    ]

    class MockStreamResponse:
        status_code = 200

        async def aiter_bytes(self):  # type: ignore[no-untyped-def]
            for line in sse_lines:
                yield line

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            pass

    class MockAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def stream(self, method: str, url: str, **kwargs: Any) -> MockStreamResponse:
            nonlocal captured_headers
            captured_headers = kwargs.get("headers", {})
            return MockStreamResponse()

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            pass

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = TestClient(companion_app)
    req_body = {
        "messages": [{"role": "user", "content": "Erkläre mir das Verbalklammer-Konzept."}],
    }

    with client.stream("POST", "/api/companion/chat", json=req_body) as response:
        assert response.status_code == 200
        content = response.read().decode("utf-8")
        assert "delta" in content
        assert "Hallo!" in content

    # 验证 Header 透传
    assert captured_headers.get("X-Model") == "deepseek-flash"
    assert captured_headers.get("X-Base-URL") == "https://api.deepseek.com"
    assert captured_headers.get("X-API-Key") == "sk-deepseek-test-redacted"


def test_companion_ollama_provider_header_forwarding(
    companion_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证当页面有效设置配置为本地 Ollama 时，Header 正确携带本地 BaseURL 与 qwen3.5:4b 模型."""
    captured_headers: dict[str, str] = {}

    monkeypatch.setattr("delector.core.db.settings.get_effective_api_key", lambda: "ollama-local")
    monkeypatch.setattr("delector.core.db.settings.get_effective_api_base_url", lambda: "http://127.0.0.1:11434/v1")
    monkeypatch.setattr("delector.core.db.settings.get_effective_api_model", lambda: "qwen3.5:4b")

    class MockStreamResponse:
        status_code = 200

        async def aiter_bytes(self):  # type: ignore[no-untyped-def]
            yield b"event: delta\ndata: {\"event\":\"delta\",\"text\":\"[Ollama Local]\"}\n\n"
            yield b"event: done\ndata: {\"event\":\"done\",\"turns\":1,\"reason\":\"stop\"}\n\n"

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            pass

    class MockAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def stream(self, method: str, url: str, **kwargs: Any) -> MockStreamResponse:
            nonlocal captured_headers
            captured_headers = kwargs.get("headers", {})
            return MockStreamResponse()

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            pass

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = TestClient(companion_app)
    req_body = {
        "messages": [{"role": "user", "content": "Guten Tag"}],
    }

    with client.stream("POST", "/api/companion/chat", json=req_body) as response:
        assert response.status_code == 200
        content = response.read().decode("utf-8")
        assert "[Ollama Local]" in content

    assert captured_headers.get("X-Model") == "qwen3.5:4b"
    assert captured_headers.get("X-Base-URL") == "http://127.0.0.1:11434/v1"
