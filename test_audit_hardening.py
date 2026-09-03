# -*- coding: utf-8 -*-
"""审计修复（M1–M5）回归测试。

模块级 env 必须在 import server 之前设好：server 模块顶层（server.py:245-246）
会执行 init_db() + seed_preset_articles()，落到真实库会造成数据污染。
本模块自用独立的临时库文件名，避免与 test_server.py 的 test_delector.db 冲突。
"""
import os
import gc
import sqlite3
import pytest

os.environ["DATABASE_PATH"] = "test_audit_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_audit_progress.db"

from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402

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


# ── M2-3: list_articles 只读减载 + review 去回查 ────────────────────────────

def test_list_articles_readonly_no_stats_recompute(client, monkeypatch):
    """文章列表是只读路径：stats 缺失的行不得在列表期间做逐行 NLP 重算 + UPDATE
    （N+1 副作用），返回空 stats 即可；惰性迁移只留在单篇 GET。"""
    import json as _json
    conn = sqlite3.connect("test_audit_delector.db")
    try:
        conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            ("NoStats", "Hallo Welt. Der Mann liest.", _json.dumps(
                {"version": "3.4.0", "sentences": []}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

    calls = []

    def spy(raw_text):
        calls.append(raw_text)
        return {"stats": {"sentences": 99}}

    monkeypatch.setattr("server.process_german_text", spy)
    data = client.get("/api/articles").json()
    assert calls == [], "list_articles 不应触发 stats 重算"
    row = next(x for x in data if x["title"] == "NoStats")
    assert row["stats"] == {}


def test_review_has_no_post_update_requery():
    """复习接口一次 SELECT 拿行 + UPDATE 即返回：不得再回查整行
    （UPDATE 后所有列都是内存已算值，回查纯浪费）。"""
    from pathlib import Path
    src = Path("server.py").read_text(encoding="utf-8")
    start = src.index("def review_card_sm2(")
    end = src.index('@app.get("/api/cards/due")')
    body = src[start:end]
    # 初始取卡 SELECT 恰 1 次；出现第 2 次 = UPDATE 后整行回查
    assert body.count("SELECT * FROM") == 1, "review 存在 UPDATE 后整行回查"


# ── M2-2: progress stats 单次扫描语义锁定（重构后仍必须成立）────────────────

def _insert_study_log(date_iso: str, minutes: int = 10):
    conn = sqlite3.connect("test_audit_progress.db")
    try:
        conn.execute(
            "INSERT INTO study_log (event_type, logged_at) VALUES (?, ?)",
            ("master_card", f"{date_iso} 10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_streak_semantics_preserved(client):
    """打卡语义必须原样保留：today 无记录 → 0（即使昨天连续）；today 有 →
    从 today 回溯连续天数；断档之外的历史不再延长。"""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    _insert_study_log((today - timedelta(days=1)).isoformat())
    _insert_study_log((today - timedelta(days=2)).isoformat())
    assert client.get("/api/progress/stats").json()["streak"] == 0

    _insert_study_log(today.isoformat())
    assert client.get("/api/progress/stats").json()["streak"] == 3

    # 断档（-3 缺失）之前的历史天不向后延长
    _insert_study_log((today - timedelta(days=4)).isoformat())
    assert client.get("/api/progress/stats").json()["streak"] == 3


def test_trend_keeps_zero_shape_for_missing_days(client):
    """30 天趋势补零形状不变：只有实际存在的天带真实值，缺的天是精确的零形状。"""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    present = (today - timedelta(days=5)).isoformat()
    conn = sqlite3.connect("test_audit_progress.db")
    try:
        conn.execute(
            "INSERT OR REPLACE INTO daily_summary "
            "(date, cards_added, cards_mastered, articles_read, quiz_sessions, study_minutes) "
            "VALUES (?, 3, 2, 1, 4, 25)",
            (present,),
        )
        conn.commit()
    finally:
        conn.close()

    data = client.get("/api/progress/stats").json()
    trend = data["trend"]
    assert len(trend) == 30
    zero_shape = {"date", "cards_added", "cards_mastered", "articles_read",
                  "quiz_sessions", "study_minutes"}
    for entry in trend:
        assert set(entry.keys()) == zero_shape, "trend 项字段漂移"
        if entry["date"] == present:
            assert (entry["cards_added"], entry["study_minutes"]) == (3, 25)
        else:
            assert entry["cards_added"] == 0 and entry["study_minutes"] == 0


def test_stats_condition_aggregates_match_single_values(client):
    """主库统计由多次 COUNT 改为条件聚合后，产出必须与既有语义一致：
    empty 库 0；造 1 mastered + 1 due 后 total/mastered/accuracy 成立。"""
    empty = client.get("/api/progress/stats").json()
    assert empty["total_cards"] == empty["total_mastered"]  # 空库相等（都为 0）
    assert empty["accuracy_pct"] in (0, 0.0)

    client.post("/api/cards/vocab", json={
        "word": "sprechen", "lemma": "sprechen", "pos": "VERB", "cefr_level": "B1",
        "definition_zh": "说", "sentence_context": "Ich spreche Deutsch.",
    })
    client.post("/api/cards/vocab", json={
        "word": "lesen", "lemma": "lesen", "pos": "VERB", "cefr_level": "A2",
        "definition_zh": "读", "sentence_context": "Er liest ein Buch.",
    })
    # 标记 mastered 会记录 correct_count 递增 → accuracy 有值
    r = client.post("/api/cards/vocab", json={
        "word": "hallo", "lemma": "hallo", "pos": "INTJ", "cefr_level": "A1",
        "definition_zh": "你好", "sentence_context": "Hallo!",
    })
    client.patch(f"/api/cards/vocab/{r.json()['id']}/master", json={"mastered": True})

    stats = client.get("/api/progress/stats").json()
    assert stats["total_cards"] >= 3
    assert stats["total_mastered"] >= 1
    assert stats["cefr_counts"]["B1"] >= 1 and stats["cefr_counts"]["A2"] >= 1
    assert stats["total_vocab"] == stats["total_cards"]


# ── M2-1: SRS / 关联 / 日志查询索引 ─────────────────────────────────────────

def _created_index_columns(db_path: str, table: str):
    """返回 {index_name: (columns…)}，只统计显式 CREATE INDEX（origin='c'）。"""
    conn = sqlite3.connect(db_path)
    try:
        result = {}
        for _, name, _, origin, _ in conn.execute(f"PRAGMA index_list('{table}')").fetchall():
            if origin == "c":
                result[name] = tuple(
                    row[2] for row in conn.execute(f"PRAGMA index_xinfo('{name}')").fetchall() if row[2]
                )
        return result
    finally:
        conn.close()


def test_main_db_reading_path_indexes():
    """复习到期队列与文章维度查询在长库上不得全表扫：主库需有 SRS+article 索引。"""
    vocab = _created_index_columns("test_audit_delector.db", "vocab_cards")
    assert any(c == ("mastered", "due_date") for c in vocab.values())
    assert any(c == ("article_id",) for c in vocab.values())
    grammar = _created_index_columns("test_audit_delector.db", "grammar_cards")
    assert any(c == ("mastered", "due_date") for c in grammar.values())
    assert any(c == ("article_id",) for c in grammar.values())
    notes = _created_index_columns("test_audit_delector.db", "reading_notes")
    assert any(c == ("article_id",) for c in notes.values())


def test_progress_db_log_indexes():
    """进度库按卡/按日期的聚合与去重须有索引，避免每次统计全表扫。"""
    quiz = _created_index_columns("test_audit_progress.db", "quiz_log")
    assert any(c == ("card_id",) for c in quiz.values())
    study = _created_index_columns("test_audit_progress.db", "study_log")
    assert any(c == ("logged_at",) for c in study.values())


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


# ── M1-5: Anki 导出 HTML 转义 ───────────────────────────────────────────────

def test_vocab_anki_note_escapes_user_html():
    """用户词/句子可注入 HTML：导出到 .apkg 的字段必须先转义，
    否则 Anki 打开牌组时 `<img onerror>` 这类标签会执行。"""
    from database import _vocab_anki_note, _grammar_anki_note
    row = {
        "word": '<img src=x onerror=alert(1)>', "lemma": "x", "pos": "NOUN",
        "gender": None, "cefr_level": "B1",
        "definition_zh": "<script>alert(2)</script>",
        "sentence_context": 'Das <img src=x onerror=alert(1)> ist gefährlich <script>x</script>.',
    }
    note = _vocab_anki_note(row)
    blob = "\n".join(note.fields)
    assert "<img" not in blob and "<script" not in blob
    assert "&lt;img" in blob and "&lt;script" in blob


def test_vocab_anki_note_keeps_highlight_feature():
    """转义不能破坏原有的词高亮功能。"""
    from database import _vocab_anki_note
    row = {
        "word": "Mann", "lemma": "Mann", "pos": "NOUN", "gender": "Masc",
        "cefr_level": "A1", "definition_zh": "男人",
        "sentence_context": "Der Mann liest ein Buch.",
    }
    note = _vocab_anki_note(row)
    assert '<b style="color:#2563eb;">Mann</b>' in note.fields[0]


def test_grammar_anki_note_escapes_user_html():
    from database import _grammar_anki_note
    row = {
        "sentence_context": "<img src=x onerror=alert(1)>",
        "grammar_name": "Akkusativ", "cefr_level": "A2",
        "explanation_zh": "<script>alert(2)</script>",
        "rule_formula": "N+V+Akk",
    }
    note = _grammar_anki_note(row)
    blob = "\n".join(note.fields)
    assert "<img" not in blob and "<script" not in blob
    assert "&lt;img" in blob and "&lt;script" in blob


# ── M1-4: TTS 收敛（voice 白名单 / 错误文案 / 输入上限）──────────────────────

def test_tts_rejects_unknown_voice_before_synthesis(client, monkeypatch):
    """voice 必须在命中合成器之前被白名单拦下（400），任意串不得透传后端。"""
    calls = []

    async def fake_gen(text, voice, rate):
        calls.append(voice)
        raise HTTPException(500, "should-not-be-reached")

    monkeypatch.setattr("server.generate_edge_tts_audio", fake_gen)
    res = client.post("/api/audio/tts", json={"text": "Hallo", "voice": "evil-voice"})
    assert res.status_code == 400
    assert calls == []


def test_tts_unexpected_error_hides_internal_detail(client, monkeypatch):
    """非 HTTP 异常不得把内部栈/路径透传给 LAN 客户端；文案固定，细节仅服务端日志。"""
    async def fake_gen(text, voice, rate):
        raise RuntimeError("C:\\secret\\inner\\path boom")

    monkeypatch.setattr("server.generate_edge_tts_audio", fake_gen)
    res = client.post("/api/audio/tts", json={"text": "Hallo", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 500
    detail = res.text
    assert "secret" not in detail
    assert "inner" not in detail


def test_note_and_noteassist_length_limits(client):
    """阅读批注与 AI 随笔请求设输入上限：超长直接 422，而不是吞进库/送 LLM。"""
    r = client.post("/api/articles/ingest", json={"title": "Len", "raw_text": "Der Mann liest."})
    art_id = r.json()["article_id"]

    long = "x" * 30000
    n = client.post(f"/api/articles/{art_id}/notes", json={"selected_text": long})
    assert n.status_code == 422

    a = client.post("/api/ai/note-assist", json={"sentence": long, "selected_text": "liest"})
    assert a.status_code == 422


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


def test_delete_note_rejects_lan(client, lan_client):
    """批注删除须与本机写操作同闸：LAN 端删除 403，本机删除 200。"""
    r = client.post("/api/articles/ingest", json={"title": "Note Gate", "raw_text": "Der Mann liest ein Buch."})
    assert r.status_code == 200
    art_id = r.json()["article_id"]
    n = client.post(f"/api/articles/{art_id}/notes", json={"selected_text": "liest"})
    assert n.status_code == 200
    note_id = n.json()["id"]

    assert lan_client.delete(f"/api/notes/{note_id}").status_code == 403
    assert client.delete(f"/api/notes/{note_id}").status_code == 200

    notes = client.get(f"/api/articles/{art_id}/notes").json()
    assert all(x["id"] != note_id for x in notes)


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
