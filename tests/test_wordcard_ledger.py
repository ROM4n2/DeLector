# -*- coding: utf-8 -*-
"""抽屉「复习台账」端点与前端接线（方案 B）。

钉住四件事：

1. **一行一 lemma**：同一 lemma 多卡只返回一张代表卡，且 `card_count` 如实计数；
2. **确定性**：代表性由 SQL 的 `ORDER BY last_signal_day DESC, created_at DESC, id DESC`
   决定——换插入顺序、重跑请求，结果逐字段一致（不依赖扫描顺序）；
3. **不编造**：空态返回 `card: null`；工作台来源用 `is_workbench` 标注，不透出 0 正 / 0 误；
4. **契约不漂移**：`GET /api/cards/vocab?scope=reader` 仍严格是 12 字段
   （既有 `test_vocab_contract_uniform.py` 的断言原样有效）。
"""

from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from server_helpers import ROOT
from server_helpers import clean_db as clean_db
from server_helpers import test_db_path as test_db_path

from delector.core.database import db_conn

REPO_ROOT = Path(ROOT)
JS_DIR = REPO_ROOT / "static" / "js"

READER_CONTRACT_FIELDS = {
    "id",
    "hw",
    "pos",
    "gender",
    "plural",
    "de",
    "zh",
    "ipa",
    "example_zh",
    "core",
    "cefr",
    "letter",
}


def _insert_card(**over):
    """直插一行 vocab_cards，显式控制复习列与时间戳（端点测试要精确摆状态）。"""
    row = {
        "word": "Haus",
        "lemma": "Haus",
        "definition_zh": "房子",
        "sentence_context": "Das Haus ist alt.",
        "mastered": 0,
        "mastered_at": None,
        "due_date": None,
        "interval_days": 1,
        "repetition_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "fsrs_s": None,
        "created_at": "2026-11-01 10:00:00",
    }
    row.update(over)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards "
            "(word, lemma, definition_zh, sentence_context, mastered, mastered_at, "
            " due_date, interval_days, repetition_count, correct_count, wrong_count, "
            " fsrs_s, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["word"],
                row["lemma"],
                row["definition_zh"],
                row["sentence_context"],
                row["mastered"],
                row["mastered_at"],
                row["due_date"],
                row["interval_days"],
                row["repetition_count"],
                row["correct_count"],
                row["wrong_count"],
                row["fsrs_s"],
                row["created_at"],
            ),
        )
        return int(cur.lastrowid or 0)


def _ledger(client, lemma="Haus"):
    res = client.get(f"/api/cards/vocab/ledger/{quote(lemma, safe='')}")
    assert res.status_code == 200
    return res.json()


# ── 空态与计数 ──────────────────────────────────────────────────────────────


def test_ledger_empty_state(client):
    """没入卡是正常结果：200 + card=null，不是 404。"""
    data = _ledger(client, "nichtvorhanden")
    assert data == {"lemma": "nichtvorhanden", "card_count": 0, "card": None}


def test_ledger_whitespace_lemma_returns_empty_state(client):
    """全空白 lemma（路径参数 %20）strip 后为空，不做全表扫描。"""
    assert _ledger(client, "   ")["card"] is None


def test_ledger_counts_duplicates_but_returns_one_row(client):
    """同一 lemma 两张卡 → 只返回一张，card_count=2。"""
    _insert_card(due_date="2026-11-12", interval_days=4, repetition_count=3)
    _insert_card(due_date="2026-10-01", interval_days=2, repetition_count=1)
    data = _ledger(client)
    assert data["card_count"] == 2
    assert data["card"] is not None
    # 最近复习的是 2026-11-08（11-12 倒退 4 天）那张
    assert data["card"]["due_date"] == "2026-11-12"
    assert data["card"]["interval_days"] == 4


# ── 确定性去重 ──────────────────────────────────────────────────────────────


def test_ledger_dedupe_is_deterministic_across_insertion_order(client):
    """同一组卡换插入顺序，代表卡逐字段一致（证明不看扫描顺序）。"""
    cards: List[Dict[str, Any]] = [
        dict(
            due_date="2026-11-12",
            interval_days=4,
            repetition_count=3,
            correct_count=3,
            created_at="2026-11-08 09:00:00",
        ),
        dict(
            due_date="2026-10-01",
            interval_days=2,
            repetition_count=1,
            correct_count=9,
            created_at="2026-10-01 09:00:00",
        ),
        dict(due_date=None, interval_days=1, repetition_count=0, created_at="2026-11-07 09:00:00"),
    ]
    for card in cards:
        _insert_card(**card)
    first = _ledger(client)["card"]

    # 清空后按相反顺序重建（id 会变，因此只比语义字段）
    with db_conn() as conn:
        conn.execute("DELETE FROM vocab_cards")
    for card in reversed(cards):
        _insert_card(**card)
    second = _ledger(client)["card"]

    keys = ("mastered", "due_date", "interval_days", "repetition_count", "correct_count", "wrong_count", "fsrs_s")
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}
    assert first["due_date"] == "2026-11-12"


def test_ledger_tie_breaks_by_created_at_then_id(client):
    """同一天动作时取最近创建；创建时间也相同时取 id 最大。"""
    _insert_card(due_date="2026-11-12", interval_days=4, correct_count=1, created_at="2026-11-01 08:00:00")
    _insert_card(due_date="2026-11-12", interval_days=4, correct_count=2, created_at="2026-11-05 08:00:00")
    assert _ledger(client)["card"]["correct_count"] == 2  # created_at 最新

    with db_conn() as conn:
        conn.execute("DELETE FROM vocab_cards")
    _insert_card(due_date="2026-11-12", interval_days=4, correct_count=3, created_at="2026-11-05 08:00:00")
    newest_id = _insert_card(
        due_date="2026-11-12", interval_days=4, correct_count=4, created_at="2026-11-05 08:00:00"
    )
    data = _ledger(client)
    assert data["card"]["id"] == newest_id
    assert data["card"]["correct_count"] == 4


def test_ledger_mastered_participates_as_signal(client):
    """手动「已掌握」是用户动作：最近掌握日高于更早的复习日。"""
    _insert_card(due_date="2026-11-12", interval_days=4, created_at="2026-11-01 08:00:00")  # 复习日 11-08
    _insert_card(mastered=1, mastered_at="2026-11-09T10:00:00", created_at="2026-11-01 08:00:00")
    data = _ledger(client)
    assert data["card"]["mastered"] is True
    assert data["card"]["due_date"] is None


def test_ledger_older_mastered_does_not_beat_recent_review(client):
    """更早的「已掌握」不会盖过更近的复习：状态词取最近动作那张。"""
    _insert_card(mastered=1, mastered_at="2026-09-01T10:00:00", created_at="2026-09-01 10:00:00")
    _insert_card(
        due_date="2026-11-12",
        interval_days=4,
        correct_count=2,
        wrong_count=1,
        created_at="2026-11-01 08:00:00",
    )
    data = _ledger(client)
    assert data["card"]["mastered"] is False
    assert data["card"]["due_date"] == "2026-11-12"
    assert data["card"]["correct_count"] == 2
    assert data["card"]["wrong_count"] == 1


# ── 工作台来源 ──────────────────────────────────────────────────────────────


def test_ledger_flags_workbench_source(client):
    """fsrs_s > 0 即工作台来源（与 known-lemmas 同口径）；不写 due/正误。"""
    _insert_card(fsrs_s=4.2, created_at="2026-11-02 08:00:00")
    card = _ledger(client)["card"]
    assert card["is_workbench"] is True
    assert card["fsrs_s"] == 4.2
    assert card["correct_count"] == 0 and card["wrong_count"] == 0


def test_ledger_zero_fsrs_is_not_workbench(client):
    """fsrs_s=0 / NULL 都不是工作台来源（不得用 IS NOT NULL）。"""
    _insert_card(fsrs_s=0)
    assert _ledger(client)["card"]["is_workbench"] is False
    with db_conn() as conn:
        conn.execute("DELETE FROM vocab_cards")
    _insert_card(fsrs_s=None)
    assert _ledger(client)["card"]["is_workbench"] is False


# ── 契约不漂移 ──────────────────────────────────────────────────────────────


def test_reader_scope_contract_stays_12_fields(client):
    """新端点不得顺手扩 reader 的 12 字段契约。"""
    _insert_card()
    res = client.get("/api/cards/vocab?scope=reader")
    assert res.status_code == 200
    words = res.json()["words"]
    assert words, "reader 档至少应有刚插入的一张卡"
    for word in words:
        assert set(word.keys()) == READER_CONTRACT_FIELDS, sorted(word.keys())


# ── 前端接线（静态） ────────────────────────────────────────────────────────


def test_drawer_has_ledger_slot_and_index_is_generated():
    drawer = (REPO_ROOT / "static" / "modals" / "drawer.html").read_text(encoding="utf-8")
    assert 'id="d-ledger"' in drawer
    assert 'class="wordcard-ledger"' in drawer
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="d-ledger"' in index, "index.html 必须由模板重建（build_index_html.py）"


def test_reader_consumes_ledger_endpoint_without_innerHTML():
    api_src = (JS_DIR / "rd-api.js").read_text(encoding="utf-8")
    reader_src = (JS_DIR / "reader.js").read_text(encoding="utf-8")
    assert "/api/cards/vocab/ledger" in api_src
    assert "fetchVocabLedger" in reader_src
    # 台账是纯文本，不得用 innerHTML 拼（列值来自 DB，仍按最小暴露面约束）
    render_body = reader_src.split("function renderVocabLedger", 1)[1].split("\n}", 1)[0]
    assert "textContent" in render_body
    assert "innerHTML" not in render_body


def test_ledger_css_uses_currentColor_border_not_line_token():
    css = (REPO_ROOT / "src" / "css" / "04-drawer-wordcard.css").read_text(encoding="utf-8")
    block = css.split(".wordcard-ledger {", 1)[1].split("}", 1)[0]
    assert "border-left: 2px solid currentColor" in block
    assert "var(--line)" not in block, "边框不得用 --line（叠白底 1.43:1，低于 SC 1.4.11）"
    built = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".wordcard-ledger" in built, "src/css 改动必须经 build_css.py 落进 style.css"
