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
from delector.core.vocab_pool import project_wb_deck, reconcile_report


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


# ── ⑧ 只读对账：deck 应入池 vs 池中实际存在（ADR-0016 Phase 3 / Task 4）──────────────
# reconcile_report 只读量化「deck→池」缺口：按 **lemma 集合**对账（禁计数对账）；
# 复用范围闸 `_is_projectable`（口径与 project_wb_deck.skipped 对齐）；不抛、绝不写盘、
# 刻意不产 ``extra``（池内无法区分 deck 行与阅读流用户卡——诚实留空）。


def _reconcile_snapshot(conn: Any) -> List[Any]:
    """vocab_cards 的只读快照（id, lemma, definition_zh, source, fsrs_s），按 id 排序。"""
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT id, lemma, definition_zh, source, fsrs_s FROM vocab_cards ORDER BY id"
        ).fetchall()
    ]


def test_reconcile_reports_missing_gap(clean_db):
    """① 缺口命中：deck 2 个可投影（1 已在池、1 缺失）⇒ projectable=2, in_pool=1, missing=[缺失]。"""
    words = [
        {"id": "u-1", "hw": "Haus", "gloss": "房子", "custom": True},
        {"id": "u-2", "hw": "Tisch", "gloss": "桌子", "custom": True},
    ]
    payload = _payload(words, cards={})
    with db_conn(clean_db["db"]) as conn:
        project_wb_deck(conn, payload)  # 两条都入池
    # 造缺口：删掉池里的 Tisch（保留 Haus）
    with db_conn(clean_db["db"]) as conn:
        conn.execute("DELETE FROM vocab_cards WHERE lemma = ?", (lemma_key("Tisch"),))

    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, payload)

    assert report["deck_projectable"] == 2
    assert report["deck_in_pool"] == 1
    assert report["missing"] == [lemma_key("Tisch")]
    assert report["pool_total"] == 1  # 池中现剩 Haus 一行


def test_reconcile_missing_is_sorted(clean_db):
    """② missing 排序稳定：≥2 个缺失 ⇒ missing == sorted(missing)。"""
    words = [
        {"id": "u-1", "hw": "Zebra", "gloss": "", "custom": True},
        {"id": "u-2", "hw": "Apfel", "gloss": "", "custom": True},
        {"id": "u-3", "hw": "Maus", "gloss": "", "custom": True},
    ]
    payload = _payload(words, cards={})
    # 池内只手工插一条 Apfel → 缺 Maus / Zebra 两条
    with db_conn(clean_db["db"]) as conn:
        conn.execute(
            "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context) VALUES (?, ?, ?, ?)",
            ("Apfel", lemma_key("Apfel"), "", ""),
        )
    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, payload)

    assert report["deck_projectable"] == 3
    assert report["deck_in_pool"] == 1
    assert report["missing"] == sorted(report["missing"])
    assert report["missing"] == [lemma_key("Maus"), lemma_key("Zebra")]


def test_reconcile_dedups_deck_by_lemma(clean_db):
    """③ lemma 去重：deck 两个不同 id 但同 lemma 的可投影词 ⇒ deck_projectable 只算 1。"""
    words = [
        {"id": "u-1", "hw": "Haus", "gloss": "房子", "custom": True},
        {"id": "u-99", "hw": "Haus", "gloss": "房子（重复条目）", "custom": True},
    ]
    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, _payload(words, cards={}))

    assert report["deck_projectable"] == 1  # 按 lemma 集合，非按词条计数
    assert report["deck_in_pool"] == 0
    assert report["missing"] == [lemma_key("Haus")]


def test_reconcile_scope_gate_matches_projection(clean_db):
    """④ 范围闸一致性：非 custom 且未学（无卡 / reps 0）的词不计入 deck_projectable。"""
    words: List[Dict[str, Any]] = [
        {"id": "a1-0001", "hw": "Haus", "gloss": "房子"},  # 非自建 + 无卡 → 挡下
        {"id": "a1-0002", "hw": "Tisch", "gloss": "桌子"},  # 非自建 + reps 0 → 挡下
        {"id": "u-1", "hw": "Stuhl", "gloss": "椅子", "custom": True},  # 自建 → 计入
    ]
    cards = {"a1-0002": {"reps": 0}}
    payload = _payload(words, cards=cards)

    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, payload)
    assert report["deck_projectable"] == 1  # 仅自建词

    # 与 project_wb_deck 的 skipped 口径对齐：同一 payload 只 1 条可投影、2 条被挡
    with db_conn(clean_db["db"]) as conn:
        projected = project_wb_deck(conn, payload)
    assert projected == {"inserted": 1, "updated": 0, "unchanged": 0, "skipped": 2}
    assert report["deck_projectable"] == projected["inserted"]


def test_reconcile_is_read_only(clean_db):
    """⑤ 只读（关键）：调用前后 vocab_cards 快照逐字未变（含行数）；两次调用结果相同。"""
    words = [
        {"id": "u-1", "hw": "Haus", "gloss": "房子", "custom": True},
        {"id": "u-2", "hw": "Tisch", "gloss": "桌子", "custom": True},
    ]
    payload = _payload(words, cards={})
    with db_conn(clean_db["db"]) as conn:
        project_wb_deck(conn, payload)  # 池中先有 2 行

    with db_conn(clean_db["db"]) as conn:
        before = _reconcile_snapshot(conn)
        before_changes = conn.total_changes
        first = reconcile_report(conn, payload)
        after = _reconcile_snapshot(conn)
        after_changes = conn.total_changes
        second = reconcile_report(conn, payload)
        after_second = _reconcile_snapshot(conn)

    assert before  # 快照非空，断言才有区分度
    assert before == after == after_second  # 逐字未变（含行数）
    assert after_changes == before_changes  # 零写盘：SQLite total_changes 不增（SELECT 不计）
    assert first == second  # 幂等：同一 payload 连调结果一致


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"words": "x", "cards": {}},
        {"words": [], "cards": []},
        {"words": [1, 2], "cards": {}},
        {"cards": {}},
    ],
)
def test_reconcile_bad_payload_returns_zeros(clean_db, bad):
    """⑥ 坏 payload：不抛且返回全 0（missing==[]；空库 pool_total==0）。"""
    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, bad)
    assert report == {"deck_projectable": 0, "deck_in_pool": 0, "missing": [], "pool_total": 0}


def test_reconcile_bad_payload_still_reports_pool_total(clean_db):
    """⑥+ 坏 payload 仍如实查库给出真实 pool_total（其余为 0 / 空），不编造。"""
    with db_conn(clean_db["db"]) as conn:
        conn.execute(
            "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context) VALUES (?, ?, ?, ?)",
            ("Haus", lemma_key("Haus"), "", ""),
        )
    with db_conn(clean_db["db"]) as conn:
        report = reconcile_report(conn, {"words": "x", "cards": {}})
    assert report == {"deck_projectable": 0, "deck_in_pool": 0, "missing": [], "pool_total": 1}
