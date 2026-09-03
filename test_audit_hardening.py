# -*- coding: utf-8 -*-
"""审计修复（M1–M5）回归测试。

模块级 env 必须在 import server 之前设好：server 模块顶层（server.py:245-246）
会执行 init_db() + seed_preset_articles()，落到真实库会造成数据污染。
本模块自用独立的临时库文件名，避免与 test_server.py 的 test_delector.db 冲突。
"""
import os
import gc
import pytest

os.environ["DATABASE_PATH"] = "test_audit_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_audit_progress.db"

from fastapi.testclient import TestClient  # noqa: E402

from server import app, get_setting, set_setting  # noqa: E402
from database import (  # noqa: E402
    BACKUP_SETTINGS_WHITELIST,
    BACKUP_SETTINGS_EXPORT_WHITELIST,
    BACKUP_SETTINGS_IMPORT_WHITELIST,
    verify_wb_key,
)


@pytest.fixture
def client():
    # 显式 127.0.0.1 来源：备份/删除等端点有 _require_localhost 闸，
    # TestClient 默认 host 是 "testclient"，会被拒。
    return TestClient(app, client=("127.0.0.1", 54321))


@pytest.fixture
def lan_client():
    return TestClient(app, client=("192.168.1.77", 54321))


@pytest.fixture(autouse=True)
def clean_db():
    gc.collect()
    for f in ("test_audit_delector.db", "test_audit_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    from server import init_db, init_progress_db
    init_db("test_audit_delector.db")
    init_progress_db("test_audit_progress.db")
    yield
    gc.collect()
    for f in ("test_audit_delector.db", "test_audit_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass


# ── M1-1: 还原备份不导入 API_BASE_URL / API_MODEL ──────────────────────────

def test_restore_does_not_import_api_base_url_or_model(client):
    """恶意备份可把 API_BASE_URL 指向攻击者服务器，让下一次 AI 调用把真实
    DEEPSEEK_API_KEY 发过去。还原必须只导入可信设置键（TTS_*），不碰
    API_BASE_URL / API_MODEL，也不能动库里已有的 DEEPSEEK_API_KEY。"""
    set_setting("DEEPSEEK_API_KEY", "sk-must-survive", db_path="test_audit_delector.db")
    set_setting("API_BASE_URL", "https://existing.example", db_path="test_audit_delector.db")
    set_setting("API_MODEL", "keep-model", db_path="test_audit_delector.db")
    set_setting("TTS_VOICE", "de-DE-KatjaNeural", db_path="test_audit_delector.db")

    res = client.post("/api/backup/restore", json={
        "version": 2,
        "app_settings": [
            {"key": "API_BASE_URL", "value": "http://evil.example"},
            {"key": "API_MODEL", "value": "evil-model"},
            {"key": "TTS_VOICE", "value": "de-DE-ConradNeural"},
        ],
    })
    assert res.status_code == 200

    assert get_setting("DEEPSEEK_API_KEY", db_path="test_audit_delector.db") == "sk-must-survive"
    assert get_setting("API_BASE_URL", db_path="test_audit_delector.db") == "https://existing.example"
    assert get_setting("API_MODEL", db_path="test_audit_delector.db") == "keep-model"
    assert get_setting("TTS_VOICE", db_path="test_audit_delector.db") == "de-DE-ConradNeural"


def test_backup_whitelist_split_semantics():
    """导出仍包含 API_BASE_URL/API_MODEL（非机密、供诊断），但还原导入白名单
    只允许 TTS_VOICE/TTS_RATE——这是防 API Key 外泄的结构保证。"""
    assert BACKUP_SETTINGS_EXPORT_WHITELIST == BACKUP_SETTINGS_WHITELIST
    assert "API_BASE_URL" in BACKUP_SETTINGS_EXPORT_WHITELIST
    assert "API_MODEL" in BACKUP_SETTINGS_EXPORT_WHITELIST
    assert BACKUP_SETTINGS_IMPORT_WHITELIST == ("TTS_VOICE", "TTS_RATE")


# ── M1-2: X-WB-Key 恒定时间比较 ────────────────────────────────────────────

def test_verify_wb_key_uses_compare_digest(monkeypatch):
    """X-WB-Key 校验必须走 secrets.compare_digest（恒定时间），不能回退成 `!=`。"""
    calls = []

    def fake_compare(a, b):
        calls.append((a, b))
        return a == b

    monkeypatch.setattr("database.secrets.compare_digest", fake_compare)
    assert verify_wb_key("deadbeef", "deadbeef") is True
    assert calls, "verify_wb_key 未调用 compare_digest"
    assert verify_wb_key("deadbeef", "cafebabe") is False


def test_wb_state_put_requires_valid_key(client):
    """PUT /api/wb/state 正确 key 放行、错误 key 403。key 走本机端点获取。"""
    key_res = client.get("/api/wb/state/key")
    assert key_res.status_code == 200
    real_key = key_res.json()["key"]

    ok = client.put("/api/wb/state", json={"payload": {"k": "v"}},
                    headers={"X-WB-Key": real_key})
    assert ok.status_code == 200

    bad = client.put("/api/wb/state", json={"payload": {"k": "v"}},
                     headers={"X-WB-Key": "00000000000000000000000000000000"})
    assert bad.status_code == 403

    none = client.put("/api/wb/state", json={"payload": {"k": "v"}})
    assert none.status_code == 403
