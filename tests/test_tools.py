# -*- coding: utf-8 -*-
"""T7：delector/tools/ 接口层 + POST /api/tools/{name} 端点。

Go Agent（Phase 2）经此 HTTP 契约调用 Python 业务能力。覆盖：
- 路由分发（列表 / 未知 tool 404 / 5 个 tool 端点可达）
- 每个 tool.run 的薄包装语义（网络/外网依赖一律 monkeypatch 脱敏）
"""
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

from delector.server import app
from delector.tools import TOOL_REGISTRY

client = TestClient(app, client=("127.0.0.1", 54321))


# ---------- 路由分发 ----------
def test_list_tools_exposes_all_five():
    resp = client.get("/api/tools/")
    assert resp.status_code == 200
    assert set(resp.json()["tools"]) == set(TOOL_REGISTRY.keys())


def test_unknown_tool_returns_404():
    resp = client.post("/api/tools/nope", json={"payload": {}})
    assert resp.status_code == 404


def test_analyze_tool_via_http():
    resp = client.post(
        "/api/tools/analyze",
        json={"payload": {"text": "Der Hund beißt den Mann."}},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_writing_check_tool_via_http():
    resp = client.post(
        "/api/tools/writing_check",
        json={"payload": {"text": "Lieber Herr Müller, ich schreibe Ihnen ..."}},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_tts_tool_via_http(monkeypatch):
    monkeypatch.setattr(
        "delector.tools.tts_tool.synthesize",
        lambda text, voice="de-DE-KatjaNeural", rate="+0%": b"FAKE_MP3",
    )
    resp = client.post("/api/tools/tts", json={"payload": {"text": "Hallo Welt"}})
    assert resp.status_code == 200
    assert base64.b64decode(resp.json()["audio_b64"]) == b"FAKE_MP3"


def test_ingest_tool_via_http(monkeypatch):
    async def fake_fetch(url):
        return "<html>hi</html>"

    monkeypatch.setattr("delector.tools.ingest.fetch_remote_html", fake_fetch)
    resp = client.post(
        "/api/tools/ingest", json={"payload": {"url": "http://example.com/a"}}
    )
    assert resp.status_code == 200
    assert resp.json()["html"] == "<html>hi</html>"


def test_export_tool_via_http(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "delector.tools.export.export_anki_deck",
        lambda out, db=None: str(tmp_path / "x.apkg"),
    )
    resp = client.post(
        "/api/tools/export",
        json={"payload": {"output_path": str(tmp_path / "out.apkg")}},
    )
    assert resp.status_code == 200
    assert resp.json()["path"].endswith("x.apkg")


# ---------- tool.run 单元（网络/外网依赖脱敏） ----------
def test_ingest_run(monkeypatch):
    async def fake_fetch(url):
        return "<html>x</html>"

    monkeypatch.setattr("delector.tools.ingest.fetch_remote_html", fake_fetch)
    from delector.tools.ingest import run

    out = asyncio.run(run({"url": "u"}))
    assert out == {"url": "u", "html": "<html>x</html>"}


def test_tts_run(monkeypatch):
    monkeypatch.setattr(
        "delector.tools.tts_tool.synthesize",
        lambda text, voice="de-DE-KatjaNeural", rate="+0%": b"ABCD",
    )
    from delector.tools.tts_tool import run

    out = asyncio.run(run({"text": "Hallo", "voice": "v", "rate": "r"}))
    assert base64.b64decode(out["audio_b64"]) == b"ABCD"
    assert out["voice"] == "v" and out["rate"] == "r"


def test_export_run_requires_output_path():
    from delector.tools.export import run

    with pytest.raises(ValueError, match="output_path"):
        asyncio.run(run({}))


def test_export_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "delector.tools.export.export_anki_deck",
        lambda out, db=None: str(tmp_path / "y.apkg"),
    )
    from delector.tools.export import run

    out = asyncio.run(run({"output_path": str(tmp_path / "y.apkg")}))
    assert out["path"].endswith("y.apkg")


def test_analyze_run_local():
    from delector.tools.analyze import run

    out = asyncio.run(run({"text": "Die Katze schläft."}))
    assert isinstance(out, dict)


def test_writing_check_run_local():
    from delector.tools.writing_check import run

    out = asyncio.run(run({"text": "Lieber Herr Müller, ..."}))
    assert isinstance(out, dict)
