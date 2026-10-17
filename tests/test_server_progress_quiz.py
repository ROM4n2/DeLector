# -*- coding: utf-8 -*-
"""进度 / 测验 / FSRS 复习 / 形态学域的端点测试（C6 Task 3 自 `tests/test_server.py` 逐字搬出）。

搬出的五段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `1461`-`1546`  Phase A: Delete & Master
  `1549`-`1604`  Phase B: Quiz Record
  `1607`-`1646`  Phase C: Progress Stats
  `1649`-`1962`  v3.0 / v3.8: FSRS Spaced Repetition & Cloze Exercises
  `2075`-`2319`  v3.4.0 Phase: Morphology & Separable Verbs Engine

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client）与
helper（ROOT / _insert_vocab_card）住在 `tests/server_helpers.py` 与 `tests/conftest.py`，
按名即可见，无需本文件重复定义。
"""

import os

from server_helpers import ROOT, _insert_vocab_card
from server_helpers import clean_db as clean_db

from delector.core.database import db_conn, db_progress_conn

# ── Phase A: Delete & Master ─────────────────────────────────────────────────


def test_delete_vocab_card(client):
    """Hard-delete removes card from DB."""
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
    assert res.status_code == 200
    card_id = res.json()["id"]

    del_res = client.delete(f"/api/cards/vocab/{card_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_id"] == card_id

    cards = client.get("/api/cards").json()
    ids = [c["id"] for c in cards["vocab_cards"]]
    assert card_id not in ids


def test_delete_nonexistent_card_returns_404(client):
    res = client.delete("/api/cards/vocab/99999")
    assert res.status_code == 404


def test_master_vocab_card(client):
    """Mastering a card marks it and logs to progress DB."""
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

    patch_res = client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": True})
    assert patch_res.status_code == 200
    assert patch_res.json()["mastered"] is True

    with db_conn("test_delector.db") as conn:
        row = conn.execute("SELECT mastered, mastered_at FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["mastered"] == 1
        assert row["mastered_at"] is not None

    with db_progress_conn("test_progress.db") as conn:
        row = conn.execute(
            "SELECT event_type FROM study_log WHERE ref_id=? AND event_type='master_card'", (card_id,)
        ).fetchone()
        assert row is not None
        assert row["event_type"] == "master_card"


def test_unmaster_card(client):
    """Unmastering resets mastered flag."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "fahren",
            "lemma": "fahren",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "驾驶",
            "sentence_context": "Er fährt.",
        },
    )
    card_id = res.json()["id"]

    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": True})
    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": False})

    with db_conn("test_delector.db") as conn:
        row = conn.execute("SELECT mastered FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["mastered"] == 0


# ── Phase B: Quiz Record ──────────────────────────────────────────────────────


def test_quiz_record_correct(client):
    """Correct answer increments correct_count and logs to quiz_log."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "hören",
            "lemma": "hören",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "听",
            "sentence_context": "Ich höre Musik.",
        },
    )
    card_id = res.json()["id"]

    quiz_res = client.post(
        "/api/quiz/record", json={"card_id": card_id, "card_type": "vocab", "mode": "flashcard", "correct": True}
    )
    assert quiz_res.status_code == 200

    with db_conn("test_delector.db") as conn:
        row = conn.execute("SELECT correct_count, wrong_count FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["correct_count"] == 1
        assert row["wrong_count"] == 0

    with db_progress_conn("test_progress.db") as conn:
        row = conn.execute("SELECT correct FROM quiz_log WHERE card_id=?", (card_id,)).fetchone()
        assert row["correct"] == 1


def test_quiz_record_wrong(client):
    """Wrong answer increments wrong_count."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "sehen",
            "lemma": "sehen",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "看",
            "sentence_context": "Ich sehe dich.",
        },
    )
    card_id = res.json()["id"]

    client.post(
        "/api/quiz/record", json={"card_id": card_id, "card_type": "vocab", "mode": "dictation", "correct": False}
    )

    with db_conn("test_delector.db") as conn:
        row = conn.execute("SELECT correct_count, wrong_count FROM vocab_cards WHERE id=?", (card_id,)).fetchone()
        assert row["wrong_count"] == 1
        assert row["correct_count"] == 0


# ── Phase C: Progress Stats ───────────────────────────────────────────────────


def test_progress_stats_empty(client):
    """Progress stats returns expected keys even with no data."""
    res = client.get("/api/progress/stats")
    assert res.status_code == 200
    data = res.json()
    for key in ("total_cards", "total_mastered", "streak", "cefr_counts", "trend", "milestones", "accuracy_pct"):
        assert key in data, f"Missing key: {key}"
    assert len(data["trend"]) == 30
    assert data["streak"] >= 0
    assert data["total_cards"] >= 0  # seeded articles may produce vocab cards via NLP
    assert data["total_articles"] >= 0


def test_progress_stats_after_adding_cards(client):
    """Progress reflects added and mastered cards."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "sprechen",
            "lemma": "sprechen",
            "pos": "VERB",
            "cefr_level": "B1",
            "definition_zh": "说",
            "sentence_context": "Ich spreche Deutsch.",
        },
    )
    card_id = res.json()["id"]
    client.patch(f"/api/cards/vocab/{card_id}/master", json={"mastered": True})

    stats = client.get("/api/progress/stats").json()
    assert stats["total_cards"] >= 1
    assert stats["total_mastered"] >= 1
    assert stats["cefr_counts"]["B1"] >= 1
    # first_card milestone unlocked
    milestones = {m["id"]: m for m in stats["milestones"]}
    assert milestones["first_card"]["unlocked"] is True
    assert milestones["master_10"]["unlocked"] is False  # only 1 mastered


# ── v3.0 / v3.8: FSRS Spaced Repetition & Cloze Exercises ──────────────────


def test_fsrs_algorithm_calculation():
    """Verify modern FSRS DSR calculation mathematics and gradients."""
    from delector.routes.main import calculate_fsrs, get_fsrs_next_intervals

    # 1. Initial review gradients for all 4 grades
    intervals_init = get_fsrs_next_intervals(rep=0, interval=1, ef=2.5)
    assert intervals_init[1] == 1  # Again: 1d
    assert intervals_init[2] == 2  # Hard: 2d
    assert intervals_init[3] == 4  # Good: 4d
    assert intervals_init[4] == 9  # Easy: 9d

    # 2. First time review (Grade 3 - Good)
    rep1, iv1, ef1, due1, next_ivs1 = calculate_fsrs(grade=3, rep=0, interval=1, ef=2.5)
    assert rep1 == 1
    assert iv1 == 4
    assert ef1 == 4.4
    assert isinstance(next_ivs1, dict)
    assert len(next_ivs1) == 4

    # 3. Second consecutive success (Grade 3 - Good)
    rep2, iv2, ef2, due2, next_ivs2 = calculate_fsrs(grade=3, rep=rep1, interval=iv1, ef=ef1)
    assert rep2 == 2
    assert iv2 == 9
    assert ef2 == 4.4

    # 4. Third success (Grade 4 - Easy)
    rep3, iv3, ef3, due3, next_ivs3 = calculate_fsrs(grade=4, rep=rep2, interval=iv2, ef=ef2)
    assert rep3 == 3
    assert iv3 >= 20
    assert ef3 < 4.4  # Difficulty decreased for easy card

    # 5. Lapse / Failure (Grade 1 - Forgot) resets repetition smoothly
    rep_f, iv_f, ef_f, due_f, next_ivs_f = calculate_fsrs(grade=1, rep=rep3, interval=iv3, ef=ef3)
    assert rep_f == 0
    assert iv_f <= 2
    assert ef_f > ef3  # Difficulty increased


def test_sm2_backward_compatibility():
    """Verify legacy calculate_sm2 wrapper returns 4-tuple and works seamlessly."""
    from delector.routes.main import calculate_sm2

    rep, interval, ef, due = calculate_sm2(grade=3, rep=0, interval=1, ef=2.5)
    assert rep == 1
    assert interval == 4
    assert ef == 4.4
    assert isinstance(due, str)


def test_card_review_fsrs_endpoint(client):
    """Test POST /api/cards/{card_type}/{card_id}/review updates FSRS schedule and returns next_intervals."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "verstehen",
            "lemma": "verstehen",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "理解",
            "sentence_context": "Ich verstehe.",
        },
    )
    card_id = res.json()["id"]

    # Review with Grade 3 (Good)
    rev_res = client.post(f"/api/cards/vocab/{card_id}/review", json={"grade": 3})
    assert rev_res.status_code == 200
    card_data = rev_res.json()
    assert card_data["repetition_count"] == 1
    assert card_data["interval_days"] == 4
    assert "due_date" in card_data
    assert "next_intervals" in card_data
    assert card_data["next_intervals"]["1"] == 1 or card_data["next_intervals"][1] == 1
    assert card_data["next_intervals"]["3"] == 9 or card_data["next_intervals"][3] == 9


def test_get_cards_includes_next_intervals(client):
    """Test GET /api/cards and GET /api/cards/due populate next_intervals for cards."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "behalten",
            "lemma": "behalten",
            "pos": "VERB",
            "cefr_level": "B1",
            "definition_zh": "保留，记住",
            "sentence_context": "Ich behalte das Wort.",
        },
    )
    assert res.status_code == 200

    cards_res = client.get("/api/cards")
    assert cards_res.status_code == 200
    cards_data = cards_res.json()
    assert len(cards_data["vocab_cards"]) > 0
    first_card = cards_data["vocab_cards"][0]
    assert "next_intervals" in first_card
    assert 1 in first_card["next_intervals"] or "1" in first_card["next_intervals"]


def test_due_cards_endpoint(client):
    """Test GET /api/cards/due returns cards due today or earlier."""
    res = client.post(
        "/api/cards/vocab",
        json={
            "word": "lernen",
            "lemma": "lernen",
            "pos": "VERB",
            "cefr_level": "A1",
            "definition_zh": "学习",
            "sentence_context": "Ich lerne.",
        },
    )
    assert res.status_code == 200  # 建卡失败会让下面的断言变成空转

    due_res = client.get("/api/cards/due")
    assert due_res.status_code == 200
    data = due_res.json()
    assert "due_vocab" in data
    assert "due_grammar" in data
    assert "due_count" in data
    assert data["due_count"] >= 1


def _due_vocab_lemmas(client) -> list:
    res = client.get("/api/cards/due")
    assert res.status_code == 200
    return [c["lemma"] for c in res.json()["due_vocab"]]


def test_due_cards_excludes_workbench_projection_without_deck_progress(client):
    """① 工作台投影行（有 fsrs_s，卡盒 repetition_count=0）MUST NOT 进「今日到期」。

    投影侧只写 fsrs_* / 不写 due_date ⇒ due_date 为 NULL ⇒ 旧谓词把它全收进来，
    卡面还显示「0 正 / 0 误」，对用户说谎。

    **非空基线（同用例内的对照卡）**：本断言是纯否定断言，若端点因任何原因返回空
    ``due_vocab``，它会空转通过。故同时候插一张 reader 普通卡（``fsrs_s`` NULL），
    断言它**在** ``due_vocab`` 里 —— 「端点返空」会让本用例的红灯更早、更准。
    """
    _insert_vocab_card(word="Kirche", lemma="Kirche", fsrs_s=None, repetition_count=0, due_date=None)
    _insert_vocab_card(word="Fenster", lemma="Fenster", fsrs_s=12.3, repetition_count=0, due_date=None)
    lemmas = _due_vocab_lemmas(client)
    assert "Kirche" in lemmas, "非空基线：对照卡（fsrs_s NULL）必须在 due_vocab，否则本用例空转通过"
    assert "Fenster" not in lemmas


def test_due_cards_keeps_degenerate_fsrs_s_zero_row(client):
    """⑤ ``fsrs_s = 0``（退化值：行有 fsrs 列但值退化）⇒ **仍进** due。

    判别契约（不是注释里的口头约定）：due 排除谓词 MUST 用 ``fsrs_s > 0``，MUST NOT 用
    ``fsrs_s IS NOT NULL`` —— 后者更宽，把退化行（``0`` / 空串）也排除，而
    ``/api/cards/known-lemmas``（同文件姊妹端点）只认 ``> 0``（见其 docstring），故这类行
    会**既不被算「已学」、又被 due 排除** ⇒ 对用户彻底不可见（两头都看不见）。
    退化值能从哪来：``core/database.py`` 的备份还原原样回灌 ``fsrs_s``，而该列**非 STRICT**
    ⇒ legacy / 手改备份里的 ``0`` 或 ``""`` 都能落盘。

    把谓词改回 ``IS NOT NULL`` ⇒ 本用例必红。
    """
    _insert_vocab_card(word="Zug", lemma="Zug", fsrs_s=0, repetition_count=0, due_date=None)
    assert "Zug" in _due_vocab_lemmas(client), "fsrs_s 退化（=0）≠ 有工作台卡：不得被 due 排除"


def test_due_cards_keeps_workbench_projection_reviewed_in_deck(client):
    """② 同一行但 repetition_count=2（用户曾在卡盒复习过）⇒ 仍进 due（旧语义不回归）。"""
    _insert_vocab_card(word="Tuer", lemma="Tuer", fsrs_s=12.3, repetition_count=2, due_date=None)
    assert "Tuer" in _due_vocab_lemmas(client)


def test_due_cards_keeps_plain_reader_card(client):
    """③ reader 存的普通卡（fsrs_s NULL / repetition_count=0）⇒ 仍进 due。

    「入卡未复习也进今日到期」是既有行为，本次 MUST NOT 顺手改掉。
    """
    _insert_vocab_card(word="Buch", lemma="Buch", fsrs_s=None, repetition_count=0, due_date=None)
    assert "Buch" in _due_vocab_lemmas(client)


def test_due_cards_grammar_branch_untouched(client):
    """④ grammar_cards 分支 MUST NOT 受该谓词影响（该表根本没有 fsrs_s 列）。"""
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO grammar_cards "
            "(sentence_context, grammar_name, cefr_level, explanation_zh, mastered, due_date) "
            "VALUES (?, ?, ?, ?, 0, NULL)",
            ("Er geht nach Hause.", "Akkusativ", "A1", "第四格带冠词的定语从句"),
        )
    res = client.get("/api/cards/due")
    assert res.status_code == 200
    data = res.json()
    assert any(c["grammar_name"] == "Akkusativ" for c in data["due_grammar"])


def test_due_cards_still_includes_custom_workbench_word_never_rated(client):
    """⑥ **已知缺口**：工作台自建词（``custom: True``）但从未在工作台评级过 ⇒ 投影行的
    ``fsrs_s`` 为 NULL ⇒ 与 reader 普通卡不可区分 ⇒ **仍在** ``due_vocab``。

    这是**已知缺口，本任务不修**：``vocab_pool._is_projectable`` 对 ``custom is True``
    **立即** return True、不检查卡是否存在 ⇒ ``_desired_fields`` 拿到 ``card = {}`` ⇒
    ``fsrs_s = None``。故「``fsrs_s > 0`` ⇒ 有工作台卡」这个方向的蕴含成立，但**反向不成立**：
    ``fsrs_s IS NULL`` **不能**推出「来自 reader」，它也可能是尚未评级的工作台词。

    要真修它就得改投影写入语义（给自建词编造一个 FSRS ``s``），那是**编造 FSRS 状态**、
    违反 FSRS≠DSR（``vocab_pool`` 注入不变量 4），也越出本任务范围（ADR-0016 收尾）。
    本用例的作用是让缺口**显式可测**：将来若有人真去修了，本用例必红、提醒同步更新谓词注释。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    payload = {
        # custom=True ⇒ 过范围闸（_is_projectable 立即 True），即便它根本没有卡
        "words": [{"id": "u-neu", "hw": "Neuschule", "gloss": "新学校", "custom": True}],
        # 卡存在但从未评级：reps=0、无 s ⇒ 投影落 fsrs_s = NULL
        "cards": {"u-neu": {"reps": 0}},
    }
    res = client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})
    assert res.status_code == 200, res.text

    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE lemma = ?", ("neuschule",)).fetchone())
    assert row["fsrs_s"] is None, f"自建未评级词投影后 fsrs_s 应为 NULL（缺口前提）：{row}"

    lemmas = _due_vocab_lemmas(client)
    assert "neuschule" in lemmas, "已知缺口（未修）：自建未评级的工作台词仍会进 due_vocab"


def test_cloze_exercise_generation_and_eval(client):
    """Test Cloze exercise generation for grammar, vocab, ctest, and evaluation."""
    # Ingest test passage
    text = "In Deutschland lernen viele Studenten Deutsch, weil sie an einer Universität studieren möchten."
    art_res = client.post("/api/articles/ingest", json={"title": "Cloze Test Passage", "raw_text": text})
    art_id = art_res.json()["article_id"]

    # 1. Grammar Cloze Generation
    g_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "grammar"})
    assert g_res.status_code == 200
    g_data = g_res.json()
    assert g_data["mode"] == "grammar"
    assert len(g_data["items"]) > 0
    assert "masked_text" in g_data

    # 2. C-Test Cloze Generation
    c_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "ctest"})
    assert c_res.status_code == 200
    c_data = c_res.json()
    assert c_data["mode"] == "ctest"
    assert len(c_data["items"]) > 0

    # 3. Evaluate Answers
    first_item = g_data["items"][0]
    eval_res = client.post(
        "/api/exercise/cloze/evaluate",
        json={"article_id": art_id, "mode": "grammar", "answers": {str(first_item["index"]): first_item["original"]}},
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "score" in eval_data
    assert "total" in eval_data
    assert "accuracy_pct" in eval_data
    assert eval_data["results"][0]["correct"] is True


def test_cloze_evaluation_vocab_and_incorrect(client):
    """Test vocab mode cloze generation and evaluation, including incorrect answer."""
    text = "Deutsch ist eine schöne Sprache, die viele Menschen lernen."
    art_res = client.post("/api/articles/ingest", json={"title": "Vocab Cloze", "raw_text": text})
    art_id = art_res.json()["article_id"]

    v_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "vocab"})
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["mode"] == "vocab"
    assert len(v_data["items"]) > 0

    first_item = v_data["items"][0]
    correct_ans = first_item["original"]
    eval_res = client.post(
        "/api/exercise/cloze/evaluate",
        json={"article_id": art_id, "mode": "vocab", "answers": {str(first_item["index"]): correct_ans}},
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["results"][0]["correct"] is True

    if len(v_data["items"]) > 1:
        second = v_data["items"][1]
        eval_res2 = client.post(
            "/api/exercise/cloze/evaluate",
            json={"article_id": art_id, "mode": "vocab", "answers": {str(second["index"]): "wronganswer"}},
        )
        assert eval_res2.status_code == 200
        eval_data2 = eval_res2.json()
        assert eval_data2["results"][0]["correct"] is False


def test_cloze_evaluation_ctest(client):
    """Test ctest mode generation and evaluation."""
    text = "Die Universität bietet viele Kurse an, die Studenten können wählen."
    art_res = client.post("/api/articles/ingest", json={"title": "Ctest Cloze", "raw_text": text})
    art_id = art_res.json()["article_id"]
    c_res = client.post(f"/api/articles/{art_id}/exercise/cloze", json={"mode": "ctest"})
    assert c_res.status_code == 200
    c_data = c_res.json()
    assert c_data["mode"] == "ctest"
    assert len(c_data["items"]) > 0
    answers = {str(item["index"]): item["original"] for item in c_data["items"][:3]}
    eval_res = client.post(
        "/api/exercise/cloze/evaluate", json={"article_id": art_id, "mode": "ctest", "answers": answers}
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "score" in eval_data
    assert eval_data["score"] >= 0


# ── v3.4.0 Phase: Morphology & Separable Verbs Engine ─────────────────────────


def test_separable_verbs_extraction():
    """Verify spaCy dependency extraction for German separable verbs."""
    from delector.server import process_german_text

    text = "Er steigt jeden Morgen in den Zug ein."
    res = process_german_text(text)
    assert res["sentence_count"] >= 1
    sent = res["sentences"][0]
    tokens = sent["tokens"]

    verb_tok = next((t for t in tokens if t["text"] == "steigt"), None)
    prefix_tok = next((t for t in tokens if t["text"] == "ein"), None)

    assert verb_tok is not None, "Verb token 'steigt' not found"
    assert prefix_tok is not None, "Prefix token 'ein' not found"

    assert "separable" in verb_tok, "separable info missing on verb token"
    assert verb_tok["separable"]["sep_prefix_id"] == prefix_tok["id"]
    assert verb_tok["separable"]["sep_lemma"] == "einsteigen"

    assert "separable" in prefix_tok, "separable info missing on prefix token"
    assert prefix_tok["separable"]["sep_verb_id"] == verb_tok["id"]
    assert prefix_tok["separable"]["sep_lemma"] == "einsteigen"


def test_irregular_verb_stammformen_lookup():
    """Verify Goethe irregular/strong verb Stammformen reverse lookup."""
    from delector.nlp_engine.linguistics import lookup_irregular_verb

    # 1. Base infinitive
    res_gehen = lookup_irregular_verb("gehen")
    assert res_gehen is not None
    assert res_gehen["infinitiv"] == "gehen"
    assert res_gehen["praeteritum"] == "ging"
    assert res_gehen["partizip2"] == "gegangen"
    assert res_gehen["hilfsverb"] == "ist"

    # 2. Conjugated / past reverse lookup
    res_ging = lookup_irregular_verb("ging")
    assert res_ging is not None
    assert res_ging["infinitiv"] == "gehen"

    res_gegangen = lookup_irregular_verb("gegangen")
    assert res_gegangen is not None
    assert res_gegangen["infinitiv"] == "gehen"

    # 3. Separable compound irregular verb
    res_einsteigen = lookup_irregular_verb("einsteigen")
    assert res_einsteigen is not None
    assert res_einsteigen["infinitiv"] == "einsteigen"
    assert "stieg" in res_einsteigen["praeteritum"]
    assert res_einsteigen["partizip2"] == "eingestiegen"
    assert res_einsteigen["hilfsverb"] == "ist"


def test_komposita_splitting():
    """Verify German compound noun splitting with Fugenelemente."""
    from delector.nlp_engine.linguistics import split_komposita

    # 1. Two-part compound
    klima_parts = split_komposita("Klimaschutz")
    assert len(klima_parts) == 2
    assert klima_parts[0]["lemma"] == "klima"
    assert klima_parts[1]["lemma"] == "schutz"

    # 3. Plural compound noun with linking -s- and plural -en
    klima_massnahmen = split_komposita("Klimaschutzmaßnahmen")
    assert len(klima_massnahmen) >= 2
    assert any("klima" in p["lemma"] for p in klima_massnahmen)

    # 4. Two-part compound with linking -s-
    bund_reg = split_komposita("Bundesregierung")
    assert len(bund_reg) == 2
    assert bund_reg[0]["lemma"] == "bund"
    assert bund_reg[1]["lemma"] == "regierung"


def test_vocab_lookup_with_linguistics_stammformen_and_komposita(client):
    """Test /api/lookup/vocab includes stammformen for verbs and komposita for compounds."""
    # 1. Verb lookup returns stammformen
    res_verb = client.post("/api/lookup/vocab", json={"sentence": "Er ging gestern nach Hause.", "target_word": "ging"})
    assert res_verb.status_code == 200
    data_verb = res_verb.json()
    assert "stammformen" in data_verb
    assert data_verb["stammformen"]["infinitiv"] == "gehen"
    assert data_verb["stammformen"]["praeteritum"] == "ging"
    assert data_verb["stammformen"]["partizip2"] == "gegangen"
    assert data_verb["stammformen"]["hilfsverb"] == "ist"

    # 2. Compound lookup returns komposita
    res_comp = client.post(
        "/api/lookup/vocab", json={"sentence": "Klimaschutz ist eine globale Aufgabe.", "target_word": "Klimaschutz"}
    )
    assert res_comp.status_code == 200
    data_comp = res_comp.json()
    assert "komposita" in data_comp
    assert len(data_comp["komposita"]) >= 2
    assert data_comp["komposita"][0]["lemma"] == "klima"

    # 3. Plural compound lookup returns komposita
    res_plural_comp = client.post(
        "/api/lookup/vocab",
        json={
            "sentence": "Die Bundesregierung plant neue Klimaschutzmaßnahmen.",
            "target_word": "Klimaschutzmaßnahmen",
        },
    )
    assert res_plural_comp.status_code == 200
    data_plural_comp = res_plural_comp.json()
    assert "komposita" in data_plural_comp
    assert len(data_plural_comp["komposita"]) >= 2


def test_vocab_lookup_returns_prep_collocations(client):
    """查词响应要带 praepositionen：抽屉的第四个 banner 就靠它。

    bestehen 是这个数据集存在的理由：auf/aus/in 三个介词三个意思，
    值必须是列表，单值 schema 会静默丢掉两个义项。
    """
    res = client.post(
        "/api/lookup/vocab",
        json={"sentence": "Das Team besteht aus fünf Personen.", "target_word": "besteht", "lemma": "bestehen"},
    )
    assert res.status_code == 200
    rows = res.json().get("praepositionen")
    assert rows, "bestehen 必须有介词搭配"
    preps = {r["praeposition"] for r in rows}
    assert {"auf", "aus", "in"} <= preps
    for r in rows:
        assert r["kasus"] in ("Akk", "Dat", "Gen")
        assert r["bedeutung_zh"] and r["beispiel"]


def test_vocab_lookup_omits_prep_key_when_no_collocation(client):
    """没有固定搭配的词不能带空 praepositionen 键——前端按键存在与否决定是否渲染。"""
    res = client.post(
        "/api/lookup/vocab", json={"sentence": "Das Haus ist groß.", "target_word": "Haus", "lemma": "haus"}
    )
    assert res.status_code == 200
    assert "praepositionen" not in res.json()


def test_prep_lookup_falls_back_to_surface_form(client):
    """lemma 缺失时用表面形兜底：前端不总能给出 lemma（点击非动词位置时）。"""
    res = client.post("/api/lookup/vocab", json={"sentence": "Ich warte auf den Bus.", "target_word": "warten"})
    assert res.status_code == 200
    assert res.json()["praepositionen"][0]["praeposition"] == "auf"


def _load_build_prep():
    """加载生成器模块（tools/ 不是 package，只能按路径加载）。"""
    import importlib.util

    path = os.path.join(ROOT, "tools", "build_prep.py")
    spec = importlib.util.spec_from_file_location("build_prep_under_test", path)
    # 仓库内固定路径的真实文件，spec 与 loader 必然能生成（None 仅是 API 签名的防御面）
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prep_dataset_integrity():
    """数据集自检：键小写、值是元组的元组、格合法、例句真的用上了该介词。

    最后一条是本数据集唯一的自动幻觉检测 —— AI 编出 "warten für" 时，
    例句里往往还是 auf。判定用生成器的 `_accepted_surface_forms`，**不复制**
    那张缩合表：两份各自维护的话，一边认 zum 一边不认，正确数据会在这里被
    判成幻觉（实遇：animieren zu → "zum Nachdenken" 把测试挂掉）。
    """
    from delector.data.prep_dict import PREP_COLLOCATIONS

    accepted = _load_build_prep()._accepted_surface_forms
    assert len(PREP_COLLOCATIONS) >= 40
    for lemma, rows in PREP_COLLOCATIONS.items():
        assert lemma == lemma.lower(), f"{lemma} 不是小写，查词链会 miss"
        assert isinstance(rows, tuple) and rows, f"{lemma} 的值必须是非空元组"
        for row in rows:
            assert isinstance(row, tuple) and len(row) == 4, f"{lemma}: {row}"
            prep, kasus, zh, example = row
            assert kasus in ("Akk", "Dat", "Gen"), f"{lemma}: 非法格 {kasus}"
            assert zh and example, f"{lemma}: 缺中文义或例句"
            words = {w.strip(".,!?;:»«\"'").lower() for w in example.split()}
            assert words & accepted(prep), f"{lemma}: 例句没用上 {prep} —— {example}"
        # 同一介词允许出现两次 —— 靠反身性区分的两个义项就是这样：
        # ausgeben für 花费 / (sich) 冒充，einfügen in 插入 / (sich) 融入。
        # 真正要拦的是 AI 把同一条重复两遍，所以按 (介词, 中文义) 判重。
        senses = {(r[0], r[2]) for r in rows}
        assert len(senses) == len(rows), f"{lemma} 有完全重复的搭配 {[r[0] for r in rows]}"


def test_prep_contractions_cover_all_dative_accusative_pairs():
    """缩合表漏一个介词 = 那个介词的正确搭配被当幻觉丢进「确认没有搭配」名单。

    这条负例名单会被 --resume 当成已答过而永不重问，缺口从此静默。
    所以缩合形式必须成表维护，并在这里逐条钉住。
    """
    bp = _load_build_prep()
    for prep, expected in [
        ("an", "am"),
        ("an", "ans"),
        ("in", "im"),
        ("in", "ins"),
        ("zu", "zum"),
        ("zu", "zur"),
        ("bei", "beim"),
        ("von", "vom"),
        ("auf", "aufs"),
        ("für", "fürs"),
        ("um", "ums"),
        ("über", "übers"),
    ]:
        forms = bp._accepted_surface_forms(prep)
        assert prep in forms, f"{prep} 自身必须被接受"
        assert expected in forms, f"{prep} 缺缩合形式 {expected}"


def test_prep_dataset_keys_all_exist_in_dictionary():
    """prep 词头必须是词库里真有的词，否则查词链永远碰不到它。

    实遇：词库把 rätseln 错拼成 ratseln，缓存照错拼问了 AI，词库修好后
    prep_dict 仍带着 ratseln —— 查 rätseln 没搭配、查 ratseln 有，两边
    看起来都正常。生成器的 prune_unknown_lemmas 负责剔除，这里守住结果。
    """
    from delector.data.core_dict import CORE_VOCAB_DB
    from delector.data.prep_dict import PREP_COLLOCATIONS

    seed = set(_load_build_prep().SEED_COLLOCATIONS)
    orphans = [w for w in PREP_COLLOCATIONS if w not in CORE_VOCAB_DB and w not in seed]
    assert not orphans, f"这些词头不在词库里: {orphans[:10]}"


def test_prep_dict_registered_in_all_package_targets():
    """漏注册任一处 = 打包后 ModuleNotFoundError（或安卓上静默没有该功能）。"""
    root = ROOT
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert "--hidden-import=delector.data.prep_dict" in pkg
    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert wf.count("--hidden-import=delector.data.prep_dict") == 2, "Windows/Linux 两个构建都要"
    cp_lines = [ln for ln in wf.splitlines() if "android/app/src/main/python/" in ln]
    assert any("cp -r start.py" in ln for ln in cp_lines), "安卓缺 start.py 拷贝"
    assert any("cp -r delector" in ln for ln in cp_lines), "安卓应整目录拷入 delector/（prep_dict.py 在包内）"
