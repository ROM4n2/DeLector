# -*- coding: utf-8 -*-
"""卡片 / 词库域的端点测试（C6 Task 4 自 `tests/test_server.py` 逐字搬出）。

搬出的三段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `3170`-`3377`  GET /api/cards/vocab（CEFR 考纲词库数据契约端点；同段头下另有
          A2 词库与 /api/syntax/stats 相关用例，逐字随段搬出）
  `3378`-`3398`  exam catalog B1 注册（ADR-0011 Task 6：count 动态推导）
  `3399`-`3551`  GET /api/cards/known-lemmas 的「已学」口径

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client）
住在 `tests/server_helpers.py` 与 `tests/conftest.py`，按名即可见。
"""

import os

from server_helpers import ROOT, _insert_vocab_card
from server_helpers import clean_db as clean_db

from delector.core.database import db_conn
from delector.core.lexicon import lemma_key

# ── GET /api/cards/vocab（Task 3: CEFR 考纲词库数据契约端点）──


def test_get_vocab_by_cefr_level(client):
    """验证 GET /api/cards/vocab 端点契约（A1 核心/全量/精读生词与分级词库）。"""
    # 1. 默认参数：cefr=A1, scope=core
    r1 = client.get("/api/cards/vocab")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["cefr"] == "A1"
    assert data1["scope"] == "core"
    assert "total" in data1
    assert "words" in data1
    assert isinstance(data1["words"], list)
    assert data1["total"] == len(data1["words"])
    assert data1["total"] in (213, 235)
    first = data1["words"][0]
    for key in ("id", "hw", "pos", "de", "zh", "ipa", "example_zh", "core", "cefr", "letter"):
        assert key in first, f"缺少字段: {key}"
    assert first["core"] is True
    assert first["cefr"] == "A1"

    # 2. A1 全量：scope=all，词数应 >= 600
    r2 = client.get("/api/cards/vocab?cefr=A1&scope=all")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["cefr"] == "A1"
    assert data2["scope"] == "all"
    assert data2["total"] >= 600
    assert len(data2["words"]) == data2["total"]

    # 3. 精读生词：scope=reader，从 vocab_cards 读取卡片
    post_res = client.post(
        "/api/cards/vocab",
        json={
            "article_id": 1,
            "word": "Haus",
            "lemma": "Haus",
            "pos": "NOUN",
            "gender": "Neut",
            "plural": "-..er",
            "cefr_level": "A1",
            "definition_zh": "房子",
            "sentence_context": "Das Haus ist groß.",
        },
    )
    assert post_res.status_code == 200
    card_id = post_res.json()["id"]

    r3 = client.get("/api/cards/vocab?scope=reader")
    assert r3.status_code == 200
    data3 = r3.json()
    assert data3["scope"] == "reader"
    assert data3["total"] >= 1
    match = [w for w in data3["words"] if w["id"] == f"card-{card_id}"]
    assert len(match) == 1
    reader_word = match[0]
    assert reader_word["hw"] == "Haus"
    assert reader_word["pos"] == "NOUN"
    assert reader_word["de"] == "Das Haus ist groß."
    assert reader_word["zh"] == "房子"
    assert reader_word["core"] is False
    assert reader_word["cefr"] == "A1"

    # 4. 其他级别分级词库回退（如 A2 / B1）
    r4 = client.get("/api/cards/vocab?cefr=A2&scope=core")
    assert r4.status_code == 200
    data4 = r4.json()
    assert data4["cefr"] == "A2"
    assert data4["total"] > 0
    assert all(w["cefr"] == "A2" for w in data4["words"])

    # 5. 非法 scope 拒绝 400
    r5 = client.get("/api/cards/vocab?scope=unknown_scope")
    assert r5.status_code == 400


def test_corpus_syntax_stats_db_contract(tmp_path):
    from delector.core.database import get_all_corpus_syntax_stats, init_progress_db, upsert_corpus_syntax_stats

    test_db = tmp_path / "test_syntax_progress.db"
    init_progress_db(db_path=str(test_db))

    # 1. 验证空库默认统计值
    empty_stats = get_all_corpus_syntax_stats(db_path=str(test_db))
    assert empty_stats["total_articles"] == 0
    assert empty_stats["avg_sent_count"] == 0.0
    assert empty_stats["avg_clause_depth"] == 0.0
    assert empty_stats["avg_passive_rate"] == 0.0
    assert empty_stats["avg_konjunktiv_rate"] == 0.0
    assert empty_stats["avg_vl_rate"] == 0.0

    # 2. 插入第一篇文献句法统计
    art1_stats = {
        "sent_count": 10,
        "avg_clause_depth": 1.8,
        "passive_rate": 0.2,
        "konjunktiv_rate": 0.1,
        "vl_rate": 0.3,
    }
    success = upsert_corpus_syntax_stats(1, art1_stats, db_path=str(test_db))
    assert success is True

    # 3. 验证单篇统计均值
    stats1 = get_all_corpus_syntax_stats(db_path=str(test_db))
    assert stats1["total_articles"] == 1
    assert stats1["avg_sent_count"] == 10.0
    assert stats1["avg_clause_depth"] == 1.8
    assert stats1["avg_passive_rate"] == 0.2
    assert stats1["avg_konjunktiv_rate"] == 0.1
    assert stats1["avg_vl_rate"] == 0.3

    # 4. 更新第 1 篇文献数据（ON CONFLICT 覆盖）
    art1_updated = {
        "sent_count": 20,
        "avg_clause_depth": 2.0,
        "passive_rate": 0.1,
        "konjunktiv_rate": 0.2,
        "vl_rate": 0.4,
    }
    assert upsert_corpus_syntax_stats(1, art1_updated, db_path=str(test_db)) is True

    # 5. 插入第 2 篇文献
    art2_stats = {
        "sent_count": 10,
        "avg_clause_depth": 1.0,
        "passive_rate": 0.3,
        "konjunktiv_rate": 0.0,
        "vl_rate": 0.2,
    }
    assert upsert_corpus_syntax_stats(2, art2_stats, db_path=str(test_db)) is True

    # 6. 验证多篇覆盖与均值计算准确性
    stats2 = get_all_corpus_syntax_stats(db_path=str(test_db))
    assert stats2["total_articles"] == 2
    assert stats2["avg_sent_count"] == 15.0
    assert stats2["avg_clause_depth"] == 1.5
    assert stats2["avg_passive_rate"] == 0.2
    assert stats2["avg_konjunktiv_rate"] == 0.1
    assert stats2["avg_vl_rate"] == 0.3


def test_syntax_stats_endpoints(client):
    # 1. 验证 POST /api/syntax/stats
    payload = {
        "article_id": 999,
        "stats": {
            "sent_count": 12,
            "avg_clause_depth": 2.4,
            "passive_rate": 0.25,
            "konjunktiv_rate": 0.15,
            "vl_rate": 0.35,
        },
    }
    resp = client.post("/api/syntax/stats", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # 2. 验证 GET /api/syntax/stats 返回全量聚合统计
    get_resp = client.get("/api/syntax/stats")
    assert get_resp.status_code == 200
    data = get_resp.json()
    for key in (
        "total_articles",
        "avg_sent_count",
        "avg_clause_depth",
        "avg_passive_rate",
        "avg_konjunktiv_rate",
        "avg_vl_rate",
    ):
        assert key in data
    assert data["total_articles"] >= 1
    assert data["avg_sent_count"] == 12.0
    assert data["avg_clause_depth"] == 2.4
    assert data["avg_passive_rate"] == 0.25
    assert data["avg_konjunktiv_rate"] == 0.15
    assert data["avg_vl_rate"] == 0.35


def test_get_a2_vocab_endpoint(client):
    """验证 GET /api/a2/vocab 默认返回 A2 考纲官方精选词条（sources=official），结构完整且支持搜索。"""
    from delector.core.database import get_vocab_by_cefr

    res = client.get("/api/a2/vocab")
    assert res.status_code == 200
    words = res.json()
    # 默认即官方视图（sources=official）；count 动态推导，禁止硬编码词条数
    assert len(words) == len(get_vocab_by_cefr("A2", sources={"official"})["words"])
    # 抽查关键字段与格式
    w0 = words[0]
    for key in ("id", "word", "hw", "lemma", "pos", "zh", "cefr"):
        assert key in w0
        assert w0[key]
    assert w0["cefr"] == "A2"

    # 抽查名词包含冠词
    apotheke = next((w for w in words if "Apotheke" in w["word"]), None)
    assert apotheke is not None
    assert apotheke["word"] == "die Apotheke"
    assert apotheke["pos"] == "NOUN"

    # 抽查搜索过滤
    search_res = client.get("/api/a2/vocab?q=Apotheke")
    assert search_res.status_code == 200
    s_words = search_res.json()
    assert any("Apotheke" in w["word"] for w in s_words)


# ── exam catalog B1 注册（ADR-0011 Task 6：count 动态推导，禁硬编码词条数）──


def test_exam_catalog_b1_registered_with_dynamic_count():
    """catalog 注册 B1 vocab 模块，count_fn 动态推导 == 数据层实测长度。"""
    from delector.core.database import get_vocab_by_cefr
    from delector.services import exam_catalog

    assert "B1" in exam_catalog.EXAM_CATALOG, "exam_catalog 必须注册 B1 等级"
    b1_mods = exam_catalog.EXAM_CATALOG["B1"]["modules"]
    assert "vocab" in b1_mods, "B1 必须有 vocab 模块"
    assert b1_mods["vocab"]["count_fn"]() == len(get_vocab_by_cefr("B1", sources={"official"})["words"]), (
        "B1 count 必须动态推导（len(get_vocab_by_cefr('B1', sources={'official'})['words'])，官方精选口径），"
        "禁止硬编码词条数"
    )

    src = open(os.path.join(ROOT, "delector", "services", "exam_catalog.py"), encoding="utf-8").read()
    for banned in ("1712", "974"):
        assert banned not in src, f"exam_catalog.py 硬编码了词条数 {banned}（权威词表接入后即漂移）"


# ── GET /api/cards/known-lemmas 的「已学」口径（含背词工作台 FSRS 标记）────────
#
# 背景（2026-09-28 审计 P1 的另一半）：i+1 覆盖率的「已知词」来源就是本端点
# （前端 encounter.js fetchKnownLemmas → mergeKnownLemmas）。ADR-0016 Phase 3 的
# 统一池投影把工作台 FSRS 卡映射进池时，**只写 fsrs_s / fsrs_d / fsrs_lapses，
# MUST NOT 写 repetition_count**（FSRS≠DSR 硬规则），mastered 也从不写 ⇒ 只在工作台
# 背过的词，其 repetition_count 仍是 0、mastered 仍是 0。若 known-lemmas 只认
# mastered / repetition_count，则这批词永远漏在「已知」之外 —— 下列用例钉死修复。


def _put_wb_deck(client, payload):
    """取 key 后带 X-WB-Key 写入工作台 deck 镜像（走真实投影路径），返回 PUT 响应。"""
    key = client.get("/api/wb/state/key").json()["key"]
    return client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})


def _known_lemma_keys(client) -> set:
    """GET known-lemmas 的 lemma 列表 → 归一（lemma_key）后集合（与前端 mergeKnownLemmas 同口径）。"""
    r = client.get("/api/cards/known-lemmas")
    assert r.status_code == 200, r.text
    return {lemma_key(lem) for lem in r.json()["lemmas"]}


def test_known_lemmas_includes_fsrs_projected_word(client):
    """① 工作台背过的词经统一池投影（只写 fsrs_s）后必须算已知（修复前必红）。

    真实路径：PUT /api/wb/state → project_wb_deck 写 fsrs_s（不写 repetition_count / mastered）。
    """
    payload = {
        "words": [{"id": "u-haus", "hw": "Haus", "pos": "NOUN", "gloss": "房子"}],
        "cards": {"u-haus": {"reps": 1, "s": 2.3065, "d": 4.5, "lapses": 0}},
    }
    res = _put_wb_deck(client, payload)
    assert res.status_code == 200, res.text

    # 前提：投影确实把该词写进了池，且只写 fsrs_s（未写 rep / mastered）。
    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE lemma = 'haus'").fetchone())
    assert row["fsrs_s"] == 2.3065, f"投影必须把卡的 s 写进 fsrs_s：{row}"
    assert row["repetition_count"] == 0 and row["mastered"] == 0, "FSRS≠DSR：投影不得写 rep / mastered"

    assert "haus" in _known_lemma_keys(client), "工作台背过（fsrs_s>0）的词必须出现在 known-lemmas"


def test_known_lemmas_excludes_unstudied_seed_word(client):
    """② 未学、非自建的种子词即使随 deck 一起 PUT 也不得算已知。"""
    payload = {
        "words": [
            {"id": "u-haus", "hw": "Haus", "pos": "NOUN", "gloss": "房子"},
            {"id": "u-baum", "hw": "Baum", "pos": "NOUN", "gloss": "树"},
        ],
        "cards": {"u-haus": {"reps": 1, "s": 2.3065, "d": 4.5, "lapses": 0}},
    }
    res = _put_wb_deck(client, payload)
    assert res.status_code == 200, res.text

    keys = _known_lemma_keys(client)
    assert "haus" in keys, f"背过的 Haus 应在（夹具对照）：{keys}"
    assert "baum" not in keys, f"无卡、非自建的 Baum（未学冷种子）不得算已知：{keys}"


def test_known_lemmas_excludes_added_but_unreviewed_card(client):
    """③ 仅在卡盒入卡（reader 存词）不算已知 —— 既有约定「加入 ≠ 已知」不回归。

    POST /api/cards/vocab 写入的行：repetition_count=0、mastered=0、fsrs_s 为空。
    """
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "lesen",
            "lemma": "lesen",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "读",
            "sentence_context": "Ich lese.",
        },
    )
    assert res.status_code == 200, res.text

    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE lemma = 'lesen'").fetchone())
    assert row["repetition_count"] == 0 and row["mastered"] == 0, "前提：入卡未复习"
    assert row["fsrs_s"] is None, "reader 入卡不得带 fsrs_s"

    assert "lesen" not in _known_lemma_keys(client), "仅入卡未复习不得算已知"


def test_known_lemmas_includes_dsr_reviewed_card(client):
    """④ 卡盒（DSR）复习过的词仍算已知（旧语义不回归）。"""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "gehen",
            "lemma": "gehen",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "走，去",
            "sentence_context": "Ich gehe.",
        },
    )
    card_id = res.json()["id"]
    with db_conn("test_delector.db") as conn:
        conn.execute("UPDATE vocab_cards SET repetition_count = 1 WHERE id = ?", (card_id,))

    assert "gehen" in _known_lemma_keys(client), "卡盒复习过（repetition_count>0）的词仍应算已知"


def test_known_lemmas_includes_mastered_card(client):
    """⑤ 手动置「已掌握」(mastered=1) 的词仍算已知（旧语义不回归）。"""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "schreiben",
            "lemma": "schreiben",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "写",
            "sentence_context": "Ich schreibe.",
        },
    )
    card_id = res.json()["id"]
    with db_conn("test_delector.db") as conn:
        conn.execute("UPDATE vocab_cards SET mastered = 1 WHERE id = ?", (card_id,))

    assert "schreiben" in _known_lemma_keys(client), "mastered=1 的词仍应算已知"


def test_known_lemmas_excludes_zero_fsrs_row(client):
    """⑥ 边界：fsrs_s = 0 的行不得算已知（钉住 `> 0` 而非 `IS NOT NULL`）。

    `IS NOT NULL` 在「行有 fsrs 列但值退化（0 / 空串）」时更宽；只有 `> 0` 才等价于
    「该行真有工作台卡」（卡一旦存在，fsrsReview 首评即置 s = fsrsInitS(g) ≥ 0.1，
    后续转移一律 clamp 到 S_MIN = 0.001，故恒 s > 0）。
    """
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "alt",
            "lemma": "alt",
            "pos": "ADJ",
            "cefr_level": "A1",
            "definition_zh": "旧的",
            "sentence_context": "Das ist alt.",
        },
    )
    card_id = res.json()["id"]
    # 手工构造退化行：fsrs_s 有列但值为 0（并非「真有卡」）。
    with db_conn("test_delector.db") as conn:
        conn.execute("UPDATE vocab_cards SET fsrs_s = 0 WHERE id = ?", (card_id,))

    assert "alt" not in _known_lemma_keys(client), "fsrs_s=0 不是『真有卡』，不得算已知"


def _insert_grammar_card(**over: object) -> int:
    """直插一行 grammar_cards（照 `test_due_cards_grammar_branch_untouched` 的手法）。

    最小必填列：sentence_context / grammar_name / cefr_level / explanation_zh。
    """
    row: dict[str, object] = {
        "sentence_context": "Er geht nach Hause.",
        "grammar_name": "Akkusativ",
        "cefr_level": "A1",
        "explanation_zh": "第四格带冠词的定语从句",
    }
    row.update(over)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO grammar_cards "
            "(sentence_context, grammar_name, cefr_level, explanation_zh, mastered, due_date) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (
                row["sentence_context"],
                row["grammar_name"],
                row["cefr_level"],
                row["explanation_zh"],
                row.get("mastered", 0),
            ),
        )
        return int(cur.lastrowid or 0)


def test_card_counts_empty_db_returns_zero_not_null(client):
    """① 空库 ⇒ 五个字段全为 ``0``；**尤其 mastered 必须是 ``0`` 而不是 ``null``**。

    ``SUM(mastered = 1)`` 在空表上返回 ``NULL``（不是 ``0``）⇒ 若端点不写 ``or 0``，
    本用例必红。``null`` 会顺着 ``${n} 张卡`` 的模板串渲染成字面量 ``null张卡``。

    修复前本请求 404（端点不存在）⇒ 端点一旦落地，此用例即钉住「诚实留 0」。
    """
    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    data = res.json()
    for key in ("vocab_total", "vocab_mastered", "grammar_total", "grammar_mastered", "total"):
        assert key in data, f"计数端点缺字段 {key}：前端角标会渲染出 undefined"
        assert data[key] == 0, f"空库时 {key} MUST 为 0，实际 {data[key]!r}（null 会渲染成字面量 null）"


def test_card_counts_reports_per_table_totals_and_mastered(client):
    """② 2 张 vocab（1 张 ``mastered=1``）+ 1 张 grammar（``mastered=0``）⇒ 逐字段断言。

    非空基线：若端点返回全 0（假绿），本用例会红；``total`` 另钉「两表之和」。
    """
    _insert_vocab_card(word="Haus", lemma="haus", mastered=0)
    _insert_vocab_card(word="Baum", lemma="baum", mastered=1)
    _insert_grammar_card(grammar_name="Akkusativ", mastered=0)

    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    data = res.json()
    assert data["vocab_total"] == 2, f"vocab_total 应为 2，实际 {data['vocab_total']!r}"
    assert data["vocab_mastered"] == 1, f"vocab_mastered 应为 1，实际 {data['vocab_mastered']!r}"
    assert data["grammar_total"] == 1, f"grammar_total 应为 1，实际 {data['grammar_total']!r}"
    assert data["grammar_mastered"] == 0, f"grammar_mastered 应为 0，实际 {data['grammar_mastered']!r}"
    assert data["total"] == 3, f"total 应为两表之和 3，实际 {data['total']!r}"


def test_card_counts_does_not_run_fsrs_next_intervals(client, monkeypatch):
    """③ 计数端点 **MUST NOT** 做逐卡 FSRS 递推（端点存在的全部理由）。

    ``GET /api/cards`` 对每张卡跑 ``get_fsrs_next_intervals``；计数端点只要两个整数，
    递推纯属浪费。把模块属性换成抛异常的桩后仍 MUST 200。

    端点改成 ``SELECT *`` 再取 ``len`` ⇒ 桩被调用 ⇒ 本用例必红。
    """
    from delector.routes import main as routes_main

    def _boom(*args: object, **kwargs: object):
        raise AssertionError("计数端点调用了 get_fsrs_next_intervals：它只数个数，不该逐卡递推 FSRS")

    monkeypatch.setattr(routes_main, "get_fsrs_next_intervals", _boom)
    _insert_vocab_card(word="Haus", lemma="haus", mastered=1)

    res = client.get("/api/cards/counts")
    assert res.status_code == 200
    assert res.json()["vocab_total"] == 1

