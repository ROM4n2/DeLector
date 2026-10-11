# -*- coding: utf-8 -*-
"""五个 AI 端点的本机闸（_require_localhost）行为级回归锁（P1-5）。

背景：/api/lookup/grammar、/api/lookup/vocab、/api/ai/note-assist、
/api/writing/ai-polish、/api/writing/ai-polish/diff 五个 handler 会真实出网烧
DeepSeek 配额，但此前未挂本机闸 —— 桌面端有意绑 0.0.0.0（start.py 的
get_bind_host），同网段任意设备可无鉴权调用它们烧光 API Key 配额。

本文件用**行为证据**钉住（对齐 test_localhost_guard.py 的 AST 守卫：AST 只能
钉「闸已挂」，这里钉「闸真的拦得住 + 放行时业务不坏」）：
- 非本机来源（TestClient 默认 host="testclient"，不在回环白名单）⇒ 403；
- 本机来源（127.0.0.1）⇒ 200 + 业务 stub 响应（monkeypatch 掉 effective key，
  走「未配 key」的既有 stub 分支 —— **绝不出网**）。

隔离纪律：对齐 test_encounter_routes.py —— env 钉 tmp_path throwaway 双库
（DATABASE_PATH/PROGRESS_DB_PATH），先钉 env 再 import server；Windows 句柄
释放：删文件前 gc.collect()（本文件用 tmp 目录不删文件，仍 gc 以防连接残留）。
"""

import gc
import os
import sys
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 五个补闸端点：方法 + 路径 + 合法 payload（全部走既有 stub 分支，不出网）。
AI_ENDPOINTS = [
    ("/api/lookup/grammar", {"sentence": "Der Hund läuft schnell.", "target_phrase": "laufen"}),
    ("/api/lookup/vocab", {"sentence": "Der Hund läuft schnell.", "target_word": "laufen"}),
    ("/api/ai/note-assist", {"sentence": "Der Hund läuft.", "selected_text": "Hund"}),
    ("/api/writing/ai-polish", {"text": "Ich gestern kaufe ein Buch."}),
    ("/api/writing/ai-polish/diff", {"text": "Ich gestern kaufe ein Buch."}),
]

# 断言「正常业务响应」用的最小形状：各 stub 分支的关键字段。
_STUB_ASSERTIONS = {
    "/api/lookup/grammar": lambda body: "grammar_name" in body,
    "/api/lookup/vocab": lambda body: "definition_zh" in body and "source" in body,
    "/api/ai/note-assist": lambda body: body.get("_stub") is True and "summary_zh" in body,
    "/api/writing/ai-polish": lambda body: body.get("status") == "ok" and "result" in body,
    "/api/writing/ai-polish/diff": lambda body: body.get("status") == "ok" and "result" in body,
}


@pytest.fixture
def app():
    """先钉 env 再显式 create_app()（模块级 `server.app` 在 import 期已用旧 env 建好，
    不能用——那正是上面首轮 RED 时 `no such table: app_settings` 的根因）。"""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="ai_gate_test_")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH", "DELECTOR_DATA_DIR")}
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "ai_gate.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmp, "ai_gate_progress.db")
    os.environ["DELECTOR_DATA_DIR"] = tmp
    from delector import server

    yield server.create_app()
    gc.collect()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def lan_client(app) -> Iterator[TestClient]:
    """默认 host="testclient"，不在回环白名单 ⇒ 命中 _require_localhost 拒绝分支。"""
    yield TestClient(app)


@pytest.fixture
def local_client(app, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """显式本机来源；同时把 effective key 摘空 ⇒ 走既有「未配 key」stub 分支，
    保证用例绝不真实出网（stub 掉 AI 调用）。"""
    from delector.routes import main as routes_main

    monkeypatch.setattr(routes_main, "get_effective_api_key", lambda *a, **k: "")
    yield TestClient(app, client=("127.0.0.1", 54321))


@pytest.mark.parametrize("path,payload", AI_ENDPOINTS, ids=[p for p, _ in AI_ENDPOINTS])
def test_ai_endpoint_denies_non_local(lan_client: TestClient, path: str, payload: dict) -> None:
    """非本机来源 ⇒ 403（既有闸语义：HTTPException(403, '该接口仅允许本机访问')）。"""
    resp = lan_client.post(path, json=payload)
    assert resp.status_code == 403, f"{path} 非本机来源未被拒，实际 {resp.status_code}"
    assert "仅允许本机" in resp.json()["detail"]


@pytest.mark.parametrize("path,payload", AI_ENDPOINTS, ids=[p for p, _ in AI_ENDPOINTS])
def test_ai_endpoint_allows_local(local_client: TestClient, path: str, payload: dict) -> None:
    """本机来源 ⇒ 200 + 正常业务形状（stub 分支），闸不放行失败（false positive）。"""
    resp = local_client.post(path, json=payload)
    assert resp.status_code == 200, f"{path} 本机来源被误拒：{resp.status_code} {resp.text}"
    assert _STUB_ASSERTIONS[path](resp.json())
