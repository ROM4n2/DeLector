# -*- coding: utf-8 -*-
"""Step 1（只堵新增）：词卡同一性收敛 + 写入侧幂等 upsert。

钉住四件事：

1. **唯一归一入口**：词卡身份 = ``(lemma_key(lemma), word_key(word))``，读写两侧共用
   ``delector.core.vocab_identity``；``Haus`` / ``haus`` 视为同一张卡。
   台账（``GET /api/cards/vocab/ledger/{lemma}``）不再按原始 ``lemma`` 串比对。
2. **写入幂等**：``POST /api/cards/vocab``、wb 投影、伴学提议确认三条生产写入路径对同一
   身份只留一行，重复提交不报错、不重复记 ``add_card``。
3. **合法多卡不误伤**：``bestehen auf/aus/in`` 仍是三张、``die Wohnung`` 与 ``Wohnung``
   仍是两张 —— 身份键里的 ``word`` 维度就是为它们保留的。
4. **如实标注 Step 1 的边界**：没有 UNIQUE 约束，绕过 helper 的直接 INSERT 仍能写出重复行；
   并发由 ``BEGIN IMMEDIATE`` 串行化「查重 → 插入」，**不等价于唯一索引**。

约束（本 PR）：不删、不改任何存量 ``vocab_cards`` 行；不写迁移脚本；零 DDL。
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from server_helpers import _insert_vocab_card
from server_helpers import clean_db as clean_db
from server_helpers import test_db_path as test_db_path

from delector.core.database import db_conn
from delector.core.lexicon import lemma_key
from delector.core.vocab_identity import vocab_identity
from delector.core.vocab_pool import project_wb_deck
from delector.services.companion_proposal import CompanionProposalService

CARD: Dict[str, Any] = {
    "word": "Haus",
    "lemma": "Haus",
    "pos": "NOUN",
    "gender": "Neut",
    "plural": "-..er",
    "cefr_level": "A1",
    "definition_zh": "",
    "sentence_context": "",
}


def _post(client: Any, **over: Any) -> Any:
    payload = dict(CARD)
    payload.update(over)
    return client.post("/api/cards/vocab", json=payload)


def _count(db_path: str, **where: Any) -> int:
    sql = "SELECT COUNT(*) FROM vocab_cards"
    params: List[Any] = []
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
        params = list(where.values())
    with db_conn(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


# ── ① 归一契约：读写共用的唯一实现 ──────────────────────────────────────────


def test_identity_is_single_normalized_definition():
    """身份 = (lemma_key, word_key)；大小写/空白差异不许拆成两张。"""
    assert vocab_identity("Haus", "Haus") == vocab_identity(" haus ", " HAUS ")
    assert vocab_identity("Haus", "Haus") == (lemma_key("Haus"), "haus")


def test_identity_keeps_article_and_preposition_in_word():
    """word 侧刻意不去冠词：``die Wohnung`` 与 ``Wohnung`` 是两张合法卡。"""
    assert lemma_key("die Wohnung") == lemma_key("Wohnung") == "wohnung"
    assert vocab_identity("die Wohnung", "die Wohnung") != vocab_identity("Wohnung", "Wohnung")
    assert vocab_identity("bestehen auf", "bestehen auf") != vocab_identity("bestehen aus", "bestehen aus")


# ── ② 同一身份重复提交：只留一行、不报错 ────────────────────────────────────


def test_post_same_identity_twice_keeps_single_row(client, test_db_path):
    first = _post(client)
    second = _post(client)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"], "重复提交应命中同一张卡"
    assert _count(test_db_path) == 1


def test_post_normalized_variants_hit_same_row(client, test_db_path):
    """``Haus`` 与 `` haus `` 归一后同一身份 —— 这是「另一形态又长一张」的回归护栏。"""
    first = _post(client)
    second = _post(client, word=" haus ", lemma=" haus ")
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert _count(test_db_path) == 1


# ── ③ 合法多卡：反向断言写死 ────────────────────────────────────────────────


def test_preposition_collocations_remain_three_cards(client, test_db_path):
    ids = set()
    for praep in ("auf", "aus", "in"):
        res = _post(client, word=f"bestehen {praep}", lemma=f"bestehen {praep}")
        assert res.status_code == 200
        ids.add(res.json()["id"])
    assert len(ids) == 3, f"bestehen auf/aus/in 必须是三张不同的卡，实际 id={sorted(ids)}"
    assert _count(test_db_path) == 3


def test_article_variant_remains_two_cards(client, test_db_path):
    """听力卡面 ``die Wohnung`` 与正文 ``Wohnung`` 是两张（word 维度不可省）。"""
    res1 = _post(client, word="die Wohnung", lemma="die Wohnung")
    res2 = _post(client, word="Wohnung", lemma="Wohnung")
    assert res1.status_code == 200 and res2.status_code == 200
    assert res1.json()["id"] != res2.json()["id"]
    assert _count(test_db_path) == 2


# ── ④ 两套口径统一：台账与工作池读到同一行 ──────────────────────────────────


def test_ledger_and_wb_pool_read_the_same_row(client, test_db_path):
    """POST 入卡 → wb 投影不另插一行 → 台账按小写形态仍命中同一张卡。"""
    created = _post(client, word="Wohnung", lemma="Wohnung")
    card_id = created.json()["id"]

    payload = {
        "words": [{"id": "u-wohnung", "hw": "Wohnung", "gloss": "公寓"}],
        "cards": {"u-wohnung": {"reps": 1, "s": 3.0, "d": 4.0, "lapses": 0}},
    }
    with db_conn(test_db_path) as conn:
        result = project_wb_deck(conn, payload)
    assert result["inserted"] == 0, f"wb 投影不得另插一行：{result}"
    assert _count(test_db_path) == 1

    ledger = client.get("/api/cards/vocab/ledger/wohnung").json()
    assert ledger["card"] is not None
    assert ledger["card"]["id"] == card_id, "台账与工作池必须指向同一行"
    assert ledger["card_count"] == 1


# ── ⑤ 伴学提议确认：同一身份不重复计数 ──────────────────────────────────────


def test_companion_proposal_confirm_is_idempotent_per_identity(test_db_path):
    svc = CompanionProposalService(db_path=test_db_path)
    payload = {"cards": [{"word": "Haus", "lemma": "Haus", "cefr_level": "A1", "definition_zh": "房子"}]}
    first = svc.execute_proposal("proposal-a", "create_vocab_cards", payload)
    second = svc.execute_proposal("proposal-b", "create_vocab_cards", payload)
    assert first["created_count"] == 1
    assert second["created_count"] == 0, "同一身份第二次确认不得再记新增"
    assert _count(test_db_path) == 1


# ── ⑥ 并发：BEGIN IMMEDIATE 能挡什么、挡不住什么（实测口径）────────────────


def test_concurrent_duplicate_posts_collapse_to_one_row(client, test_db_path):
    """8 个线程同一身份同时提交：全部 200，且只落一行。

    结论边界（**不要**把它读成唯一索引）：这条只证明「走本 helper 的并发写」被
    ``BEGIN IMMEDIATE`` 串行化；绕过 helper 的写入仍可重复（见下一条用例）。

    实测（2026-11-09，本机）：去掉 ``BEGIN IMMEDIATE`` 后同一用例 8 个请求全部 200，
    却落下 5 行 —— 说明本用例不是空转的，它钉住的正是那个竞态窗口。
    """
    workers = 8
    barrier = threading.Barrier(workers)

    def submit(_i: int) -> Any:
        barrier.wait(timeout=10)
        return _post(client)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(submit, range(workers)))

    codes = [r.status_code for r in results]
    assert codes == [200] * workers, f"并发提交不应报错：{codes}"
    assert _count(test_db_path) == 1, "BEGIN IMMEDIATE 串行化后应只留一行"


def test_direct_insert_bypass_still_duplicates(test_db_path):
    """反向证据：Step 1 没有 UNIQUE，绕过 find_card_id 的写入仍能写出重复行。"""
    _insert_vocab_card(word="Haus", lemma="Haus")
    _insert_vocab_card(word="Haus", lemma="Haus")
    assert _count(test_db_path) == 2, "无 UNIQUE 约束 ⇒ 直接 INSERT 必须如实写出两行（不得假装幂等）"
