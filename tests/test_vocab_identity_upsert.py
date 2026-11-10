# -*- coding: utf-8 -*-
"""Step 1（只堵新增）：词卡同一性收敛 + 写入侧幂等 upsert。

钉住四件事：

1. **唯一归一入口**：词卡身份 = ``(lemma_key(lemma), word_key(word))``，读写两侧共用
   ``delector.core.vocab_identity``；SQL 侧走 ``card_identity(lemma, word)`` 行级 UDF，
   与参数侧的空值回退完全同源。``Haus`` / ``haus`` 视为同一张卡，``lemma=''`` 的
   旧备份行也能被命中。台账（``GET /api/cards/vocab/ledger/{lemma}``）不再按原始串比对。
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

import pytest
from server_helpers import _insert_vocab_card
from server_helpers import clean_db as clean_db
from server_helpers import test_db_path as test_db_path

from delector.core.database import db_conn
from delector.core.lexicon import lemma_key
from delector.core.vocab_identity import find_card_id as real_find_card_id
from delector.core.vocab_identity import vocab_identity
from delector.core.vocab_pool import project_wb_deck
from delector.services.companion_proposal import CompanionProposalService
from delector.services.companion_session import CompanionSessionService

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


def _new_proposal(svc: CompanionProposalService, sessions: CompanionSessionService) -> str:
    """按生产形状落一条 pending 提议，返回真实 proposal id（不是凭空捏的 id）。"""
    sid = str(sessions.get_or_create_session()["id"])
    prop = svc.create_proposal(
        session_id=sid,
        action="create_vocab_cards",
        title="Haus",
        payload={"cards": [{"word": "Haus", "lemma": "Haus"}]},
    )
    return str(prop["id"])


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
    # 直接钉住 word 维度：lemma 相同、只有 word 不同也必须拆成两张。
    assert vocab_identity("bestehen", "bestehen auf") != vocab_identity("bestehen", "bestehen über")


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


def test_post_empty_lemma_is_idempotent(client, test_db_path):
    """空 lemma 时参数侧回退到 word；SQL 侧必须同样回退，否则每次提交都长一张新卡。"""
    first = _post(client, word="Haus", lemma="")
    second = _post(client, word="Haus", lemma="")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert _count(test_db_path) == 1
    ledger = client.get("/api/cards/vocab/ledger/Haus").json()
    assert ledger["card"] is not None, "台账也要按同一空值回退命中这一行"
    assert ledger["card"]["id"] == first.json()["id"]


def test_legacy_empty_lemma_row_is_reused(client, test_db_path):
    """旧备份还原出的 lemma='' 行：后续 POST 必须命中它，而不是再长一行。"""
    legacy_id = _insert_vocab_card(word="Haus", lemma="")
    res = _post(client, word="Haus", lemma="")
    assert res.status_code == 200
    assert res.json()["id"] == legacy_id
    assert _count(test_db_path) == 1


# ── ③ 合法多卡：反向断言写死 ────────────────────────────────────────────────


def test_preposition_collocations_remain_three_cards(client, test_db_path):
    """生产 payload 形状：lemma 是裸词干，介词只进 word（cards.js 的矩阵入口）。"""
    ids = set()
    for praep in ("auf", "aus", "in"):
        res = _post(client, word=f"bestehen {praep}", lemma="bestehen")
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
    sessions = CompanionSessionService(db_path=test_db_path)
    payload = {"cards": [{"word": "Haus", "lemma": "Haus", "cefr_level": "A1", "definition_zh": "房子"}]}
    p1 = _new_proposal(svc, sessions)
    p2 = _new_proposal(svc, sessions)
    first = svc.execute_proposal(p1, "create_vocab_cards", payload)
    second = svc.execute_proposal(p2, "create_vocab_cards", payload)
    assert first["created_count"] == 1
    assert second["created_count"] == 0, "同一身份第二次确认不得再记新增"
    assert _count(test_db_path) == 1


def test_companion_proposal_failure_rolls_back_status_and_cards(test_db_path, monkeypatch):
    """插入循环中途失败 → 状态与卡片整事务回滚，重放必须能把卡片补回来。

    这是 P1 的判别式：若 ``update_proposal_status`` 在插卡前自己 ``conn.commit()``，
    ``accepted`` 会单独落盘，重放被幂等早退挡住 ⇒ 卡片永久丢失。
    """
    svc = CompanionProposalService(db_path=test_db_path)
    sessions = CompanionSessionService(db_path=test_db_path)
    prop_id = _new_proposal(svc, sessions)
    payload = {
        "cards": [
            {"word": "Haus", "lemma": "Haus", "definition_zh": "房子"},
            {"word": "Wohnung", "lemma": "Wohnung", "definition_zh": "公寓"},
        ]
    }
    calls = 0

    def flaky(conn: Any, lemma: str, word: str) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected mid-loop failure")
        return real_find_card_id(conn, lemma, word)

    monkeypatch.setattr("delector.services.companion_proposal.find_card_id", flaky)
    with pytest.raises(RuntimeError, match="injected"):
        svc.execute_proposal(prop_id, "create_vocab_cards", payload)

    assert _count(test_db_path) == 0, "插卡必须随状态一起回滚"
    with db_conn(test_db_path) as conn:
        row = conn.execute("SELECT status FROM companion_proposals WHERE id = ?", (prop_id,)).fetchone()
    assert row[0] == "pending", "accepted 不能在插卡前单独提交"

    monkeypatch.undo()
    replay = svc.execute_proposal(prop_id, "create_vocab_cards", payload)
    assert replay["created_count"] == 2, "失败后必须可重放"
    assert _count(test_db_path) == 2


def test_companion_distinct_proposals_concurrently_collapse_to_one_row(test_db_path):
    """两个不同 proposal 并发确认同一身份：写锁必须把「查重 → 插入」串行化。"""
    svc = CompanionProposalService(db_path=test_db_path)
    sessions = CompanionSessionService(db_path=test_db_path)
    p1 = _new_proposal(svc, sessions)
    p2 = _new_proposal(svc, sessions)
    payload = {"cards": [{"word": "Haus", "lemma": "Haus", "definition_zh": "房子"}]}
    barrier = threading.Barrier(2)

    def run(pid: str) -> Dict[str, Any]:
        barrier.wait(timeout=10)
        return svc.execute_proposal(pid, "create_vocab_cards", payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (p1, p2)))
    assert all(r["status"] == "ok" for r in results)
    assert sum(r["created_count"] for r in results) == 1
    assert _count(test_db_path) == 1


# ── ⑥ 并发：BEGIN IMMEDIATE 能挡什么、挡不住什么 ──────────────────────────


def test_concurrent_duplicate_posts_collapse_to_one_row(client, test_db_path):
    """8 个线程同一身份同时提交：全部 200，且只落一行。

    机制：``POST /api/cards/vocab`` 在单个 ``BEGIN IMMEDIATE`` 内完成「查重 → 插入」，
    SQLite 写锁让并发请求串行化，后到者能看到先到者已提交的行。
    结论边界（**不要**把它读成唯一索引）：只覆盖走本 helper 的写入；绕过 helper 的
    直接 INSERT / 旧备份还原仍可重复（见下一条用例）。并发度由 Barrier + 线程池构造，
    真实独立连接并发由上面的伴学用例补强。
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
    """Step 1 过渡期反向证据：无 UNIQUE，绕过 find_card_id 的写入仍能写出重复行。

    这是**临时**护栏：Step 3 按方案稿 §6.3 建唯一索引时必须同步删除/改写本用例，
    不要把「缺陷仍在」钉成长期契约。
    """
    _insert_vocab_card(word="Haus", lemma="Haus")
    _insert_vocab_card(word="Haus", lemma="Haus")
    assert _count(test_db_path) == 2, "无 UNIQUE 约束 ⇒ 直接 INSERT 必须如实写出两行（不得假装幂等）"


# ── ⑦ 响应契约：created / skipped_fields ───────────────────────────────────


def test_post_response_reports_created_and_skipped_fields(client, test_db_path):
    """命中既有卡时，响应必须说清「这次没新增」以及「哪些字段没写进去」。"""
    first = _post(client, definition_zh="房子", sentence_context="Das Haus ist alt.")
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert first.json()["skipped_fields"] == []

    second = _post(client, definition_zh="公寓", sentence_context="Das Haus ist neu.")
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created"] is False
    skipped = second.json()["skipped_fields"]
    assert "definition_zh" in skipped and "sentence_context" in skipped

    with db_conn(test_db_path) as conn:
        row = conn.execute(
            "SELECT definition_zh, sentence_context FROM vocab_cards WHERE id = ?",
            (first.json()["id"],),
        ).fetchone()
    assert row[0] == "房子" and row[1] == "Das Haus ist alt.", "只补空，绝不覆盖用户已填内容"


def test_post_response_skipped_fields_empty_when_existing_columns_blank(client, test_db_path):
    """既有列全空 ⇒ 本次全部写入，skipped_fields 必须为空（不能误报跳过）。"""
    _post(
        client,
        pos="",
        gender="",
        plural="",
        cefr_level="",
        definition_zh="",
        sentence_context="",
    )
    second = _post(client, definition_zh="房子", sentence_context="Das Haus ist alt.")
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["skipped_fields"] == []
    with db_conn(test_db_path) as conn:
        row = conn.execute(
            "SELECT definition_zh FROM vocab_cards WHERE id = ?", (second.json()["id"],)
        ).fetchone()
    assert row[0] == "房子", "空列应被补上"
