# -*- coding: utf-8 -*-
"""wb 快照 → 统一词池 `vocab_cards` 的幂等投影（ADR-0016 Phase 3 / Task 1）。

契约面（``delector.core.vocab_pool.project_wb_deck``，纯存储层，无路由）：
- ``project_wb_deck(conn, payload) -> {"inserted", "updated", "unchanged", "skipped"}``，**不 commit**
  （事务交调用方，便于与镜像 blob 同事务原子提交）。
- **范围闸**：只投影「自建（``custom is True``）」或「已学（``reps > 0``）」的词条；自动加载的
  A1/A2/B1 种子词不入池，计入 ``skipped``。

钉住注入不变量（Vault 规则）：
① 首投影 ``inserted == len(words)``（**仅当全部词条可投影**；否则 ``inserted + skipped == len(words)``）；
② 二次同 payload ``inserted==0, updated==0, unchanged==N``，且**零写盘**（行快照不变）；
③ 已存在行**只补空、不覆盖**（用户手编 ``definition_zh`` 保持不变；空 ``sentence_context`` 被补）；
④ ``reps``（FSRS）**不写** ``repetition_count``（DSR）：``repetition_count==0`` 且 ``fsrs_s/d/lapses`` 有值；
⑤ 坏 payload 不抛且返回全 0（缺键 / words 非数组 / cards 非 dict）；
⑥ ``source`` 正确落定（真实词表词经 ``primary_source`` 命中 official/manual/ai；自造词 → user）。

与 ``test_encounter_store.py`` 同款隔离纪律：一律喂 **tmp_path 一次性 SQLite 文件**
（含 progress 库），绝不触碰真实 ``delector.db`` / ``progress.db``。
"""

import gc
import os
from typing import Any, Dict, List

import pytest

import delector.core.database as database  # noqa: E402
from delector.core.database import db_conn
from delector.core.lexicon import lemma_key, primary_source
from delector.core.vocab_pool import project_wb_deck


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 下的 throwaway DB（vocab_pool + progress 双文件）。"""
    _db = str(tmp_path / "vocab_pool_test.db")
    _pdb = str(tmp_path / "vocab_pool_test_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path 上
    yield {"db": _db, "pdb": _pdb}
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _payload(words: List[Dict[str, Any]], cards: Dict[str, Any]) -> Dict[str, Any]:
    """最小 wb 快照：words/cards 是投影关心的两组，其余键原样透传（本投影不读）。"""
    return {"words": words, "cards": cards, "log": {}, "wrong": {}, "settings": {}}


def _dump(conn: Any) -> List[Any]:
    """整表行快照（按 id 排序），用于断言「二次运行零写盘」。"""
    return [tuple(r) for r in conn.execute("SELECT * FROM vocab_cards ORDER BY id").fetchall()]


# ── ① 首投影：inserted == len(words) ─────────────────────────────────────────


def test_first_projection_inserts_all(clean_db):
    words = [
        {
            "id": "a1-0004",
            "hw": "die Abfahrt",
            "pos": "f.",
            "gloss": "出发；发车",
            "ipa": "diː ˈapfaːɐt",
            "ex": [{"de": "Vor der Abfahrt rufe ich an.", "zh": "出发前我打个电话。"}],
            "letter": "A",
            "page": 9,
            "custom": True,  # 范围闸前提：自建词方可入池
        },
        {
            "id": "a1-0005",
            "hw": "Haus",
            "pos": "n.",
            "gloss": "房子",
            "ipa": "das hˈaʊs",
            "ex": [{"de": "Das Haus ist groß.", "zh": "这房子很大。"}],
            "letter": "H",
            "page": 12,
            "custom": True,  # 范围闸前提：自建词方可入池
        },
    ]
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards={}))
    assert result == {"inserted": 2, "updated": 0, "unchanged": 0, "skipped": 0}

    with db_conn(clean_db["db"]) as conn:
        rows = {r["lemma"]: r for r in conn.execute("SELECT * FROM vocab_cards").fetchall()}
    assert set(rows.keys()) == {lemma_key("die Abfahrt"), lemma_key("Haus")}
    # 身份列：word = 原 hw，lemma = 归一键
    assert rows[lemma_key("Haus")]["word"] == "Haus"
    assert rows[lemma_key("Haus")]["lemma"] == "haus"
    # 工作台语义槽：gloss → definition_zh，ex[0].de → sentence_context
    assert rows[lemma_key("Haus")]["definition_zh"] == "房子"
    assert rows[lemma_key("Haus")]["sentence_context"] == "Das Haus ist groß."


# ── ② 二次同 payload：幂等且零写盘 ──────────────────────────────────────────


def test_second_projection_is_idempotent(clean_db):
    words = [
        {
            "id": "a1-0001",
            "hw": "ab",
            "gloss": "从…起",
            "ex": [{"de": "Ab morgen.", "zh": "从明天起。"}],
            "custom": True,  # 范围闸前提：自建词方可入池
        },
        {
            "id": "a1-0003",
            "hw": "abfahren",
            "gloss": "出发",
            "ex": [{"de": "Wir fahren ab.", "zh": "我们出发。"}],
            "custom": True,  # 范围闸前提：自建词方可入池
        },
    ]
    payload = _payload(words, cards={})

    with db_conn(clean_db["db"]) as conn:
        first = project_wb_deck(conn, payload)
    assert first == {"inserted": 2, "updated": 0, "unchanged": 0, "skipped": 0}

    with db_conn(clean_db["db"]) as conn:
        before = _dump(conn)
    with db_conn(clean_db["db"]) as conn:
        second = project_wb_deck(conn, payload)
    with db_conn(clean_db["db"]) as conn:
        after = _dump(conn)

    assert second == {"inserted": 0, "updated": 0, "unchanged": 2, "skipped": 0}
    assert before == after  # 二次运行不写盘


# ── ③ 已存在行：只补空、不覆盖 ──────────────────────────────────────────────


def test_existing_row_not_overwritten_only_fill_empty(clean_db):
    # 预置一行（模拟用户手编/其它路径写入）：lemma = "haus"、definition_zh 非空、sentence_context 空。
    with db_conn(clean_db["db"]) as conn:
        conn.execute(
            "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context) VALUES (?, ?, ?, ?)",
            ("Haus", "haus", "用户手编释义", ""),
        )

    words = [
        {
            "id": "x",
            "hw": "Haus",
            "gloss": "房子【自动】",
            "ex": [{"de": "Das Haus ist groß.", "zh": "这房子很大。"}],
            "custom": True,  # 范围闸前提：自建词方可入池
        }
    ]
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards={}))

    with db_conn(clean_db["db"]) as conn:
        row = conn.execute(
            "SELECT definition_zh, sentence_context FROM vocab_cards WHERE lemma = ?",
            ("haus",),
        ).fetchone()
    assert row["definition_zh"] == "用户手编释义"  # 非空 → 不被覆盖
    assert row["sentence_context"] == "Das Haus ist groß."  # 空 → 被补
    assert result == {"inserted": 0, "updated": 1, "unchanged": 0, "skipped": 0}


# ── ④ reps（FSRS）不写 repetition_count（DSR）───────────────────────────────


def test_reps_not_written_to_repetition_count(clean_db):
    words = [
        {"id": "a1-0003", "hw": "abfahren", "gloss": "出发", "ex": [{"de": "Wir fahren ab.", "zh": "我们出发。"}]}
    ]
    cards = {"a1-0003": {"s": 12.3, "d": 5.1, "due": 1690000000000, "last": 1680000000000, "reps": 7, "lapses": 1}}

    with db_conn(clean_db["db"]) as conn:
        project_wb_deck(conn, _payload(words, cards=cards))

    with db_conn(clean_db["db"]) as conn:
        row = conn.execute(
            "SELECT repetition_count, fsrs_s, fsrs_d, fsrs_lapses FROM vocab_cards WHERE lemma = ?",
            (lemma_key("abfahren"),),
        ).fetchone()
    assert row["repetition_count"] == 0  # DSR 语义列：reps 绝不写进来
    assert row["fsrs_s"] == 12.3
    assert row["fsrs_d"] == 5.1
    assert row["fsrs_lapses"] == 1


# ── ⑤ 坏 payload：不抛且返回全 0 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"words": "nope", "cards": {}},
        {"words": [], "cards": []},
        {"words": [1, 2], "cards": {}},
        {"cards": {}},
    ],
)
def test_bad_payload_returns_zeros_without_raising(clean_db, bad):
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, bad)
    assert result == {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    with db_conn(clean_db["db"]) as conn:
        count = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    assert count == 0


# ── ⑥ source 落定正确 ───────────────────────────────────────────────────────


def test_source_settled_by_primary_source(clean_db):
    hw_real = "Haus"
    hw_unknown = "Zzqxyzgg"
    # 前置断言：确保本用例真的有区分度（真实词表命中 ≠ 自造词）。
    assert primary_source(hw_real) in ("official", "manual", "ai")
    assert primary_source(hw_unknown) == "user"

    words = [
        {
            "id": "r",
            "hw": hw_real,
            "gloss": "房子",
            "ex": [{"de": "Das Haus ist groß.", "zh": "这房子很大。"}],
            "custom": True,  # 范围闸前提：自建词方可入池
        },
        {
            "id": "u",
            "hw": hw_unknown,
            "gloss": "自造词",
            "ex": [{"de": "Zzq xyz.", "zh": "自造。"}],
            "custom": True,  # 范围闸前提：自建词方可入池
        },
    ]
    with db_conn(clean_db["db"]) as conn:
        project_wb_deck(conn, _payload(words, cards={}))

    with db_conn(clean_db["db"]) as conn:
        rows = {r["lemma"]: r["source"] for r in conn.execute("SELECT lemma, source FROM vocab_cards").fetchall()}
    assert rows[lemma_key(hw_real)] == primary_source(hw_real)
    assert rows[lemma_key(hw_unknown)] == primary_source(hw_unknown)
    assert rows[lemma_key(hw_unknown)] == "user"


# ── ⑦ 范围闸：只收「用户自己的词」（自建 custom is True / 已学 reps > 0）──────────
# 自动加载的 A1/A2/B1 种子词（非自建且未学）MUST NOT 入池，跳过并计入 ``skipped``。


def _vocab_count(db: Any) -> int:
    with db_conn(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0])


def test_scope_gate_skips_seed_word_without_card(clean_db):
    """非自建 + 无卡（种子未学）⇒ 不入池、``skipped`` 计数 +1、零落库。"""
    words = [{"id": "a1-0001", "hw": "Haus", "gloss": "房子"}]
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards={}))
    assert result == {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 1}
    assert _vocab_count(clean_db["db"]) == 0


def test_scope_gate_skips_seed_word_reps_zero(clean_db):
    """非自建 + ``reps == 0``（有卡但未学）⇒ 不入池、``skipped`` 计数 +1。"""
    words = [{"id": "a1-0001", "hw": "Haus", "gloss": "房子"}]
    cards = {"a1-0001": {"reps": 0, "s": 1.0}}
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards=cards))
    assert result == {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 1}
    assert _vocab_count(clean_db["db"]) == 0


def test_scope_gate_includes_learned_card(clean_db):
    """非自建 + ``reps > 0``（已学）⇒ **入池**。"""
    words = [{"id": "a1-0001", "hw": "Haus", "gloss": "房子"}]
    cards = {"a1-0001": {"reps": 1, "s": 1.0}}
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards=cards))
    assert result == {"inserted": 1, "updated": 0, "unchanged": 0, "skipped": 0}
    assert _vocab_count(clean_db["db"]) == 1


def test_scope_gate_includes_custom_word_without_card(clean_db):
    """``custom is True`` + 无卡（自建未学）⇒ **入池**。"""
    words = [{"id": "u-1", "hw": "Zzqxyzgg", "gloss": "自造词", "custom": True}]
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards={}))
    assert result == {"inserted": 1, "updated": 0, "unchanged": 0, "skipped": 0}
    assert _vocab_count(clean_db["db"]) == 1


def test_scope_gate_custom_is_strict_true_not_truthy(clean_db):
    """``custom`` 严格 ``is True``：truthy 非 ``True``（如 ``1``）不算自建 ⇒ 跳过。"""
    words = [{"id": "a1-0001", "hw": "Haus", "gloss": "房子", "custom": 1}]
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards={}))
    assert result == {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 1}
    assert _vocab_count(clean_db["db"]) == 0


def test_scope_gate_conservation_inserted_plus_skipped(clean_db):
    """守恒：所有词条均为可作键的合法 dict ⇒ ``inserted + skipped == len(words)``。"""
    words: List[Dict[str, Any]] = [
        {"id": "a1-0001", "hw": "Haus", "gloss": "房子"},  # 种子未学 → skip
        {"id": "u-1", "hw": "Tisch", "gloss": "桌子", "custom": True},  # 自建 → insert
        {"id": "a1-0003", "hw": "Stuhl", "gloss": "椅子"},  # 未学 → skip
        {"id": "a1-0004", "hw": "Bahn", "gloss": "铁路"},  # 已学 → insert
    ]
    cards = {"a1-0004": {"reps": 2}}
    with db_conn(clean_db["db"]) as conn:
        result = project_wb_deck(conn, _payload(words, cards=cards))
    assert result == {"inserted": 2, "updated": 0, "unchanged": 0, "skipped": 2}
    assert result["inserted"] + result["skipped"] == len(words)
