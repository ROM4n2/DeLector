import pytest
from starlette.testclient import TestClient
from server import app
from a1_lesen_dict import (
    A1_LESEN_SETS,
    get_lesen_set_list,
    get_lesen_set_by_id,
    grade_lesen_answers
)

client = TestClient(app)


def test_lesen_sets_structure():
    """验证 6 套 A1 官方阅读全真模考卷结构完整性（每套 15 题，共 90 题）"""
    assert len(A1_LESEN_SETS) == 6, f"Expected 6 lesen sets, got {len(A1_LESEN_SETS)}"

    total_q_count = 0
    for s in A1_LESEN_SETS:
        assert "set_id" in s
        assert "title_de" in s
        assert "title_zh" in s
        assert s["total_questions"] == 15

        parts = s["parts"]
        assert "teil_1" in parts and len(parts["teil_1"]) == 5, "Teil 1 must have 5 questions"
        assert "teil_2" in parts and len(parts["teil_2"]) == 5, "Teil 2 must have 5 questions"
        assert "teil_3" in parts and len(parts["teil_3"]) == 5, "Teil 3 must have 5 questions"

        # 检查 Teil 1 (便条/邮件理解)
        for q in parts["teil_1"]:
            assert q["teil"] == 1
            assert len(q["reading_text_de"]) > 10
            assert len(q["statement_de"]) > 5
            assert q["answer_key"] in ("R", "F")
            assert len(q["explanation_zh"]) > 5
            total_q_count += 1

        # 检查 Teil 2 (网页/广告需求二选一)
        for q in parts["teil_2"]:
            assert q["teil"] == 2
            assert len(q["user_need_zh"]) > 5
            assert "ad_a" in q and "ad_b" in q
            assert len(q["ad_a"]["text_de"]) > 10
            assert len(q["ad_b"]["text_de"]) > 10
            assert q["answer_key"] in ("A", "B", "X")
            total_q_count += 1

        # 检查 Teil 3 (公共告示与标牌)
        for q in parts["teil_3"]:
            assert q["teil"] == 3
            assert len(q["sign_text_de"]) > 5
            assert len(q["statement_de"]) > 5
            assert q["answer_key"] in ("R", "F")
            total_q_count += 1

    assert total_q_count == 90, f"Expected 90 total questions, got {total_q_count}"


def test_lesen_sanitization():
    """验证做题模式下不泄露 answer_key 与 explanation"""
    clean_set = get_lesen_set_by_id(1, sanitize=True)
    assert clean_set is not None
    assert clean_set["set_id"] == 1

    for q in clean_set["parts"]["teil_1"]:
        assert "answer_key" not in q
        assert "explanation_zh" not in q
        assert "reading_text_de" in q

    raw_set = get_lesen_set_by_id(1, sanitize=False)
    assert "answer_key" in raw_set["parts"]["teil_1"][0]


def test_lesen_grading_algorithm():
    """验证阅读 25 分制评分与等级评定算法"""
    raw_set = get_lesen_set_by_id(1, sanitize=False)
    perfect_answers = {}
    for part in ("teil_1", "teil_2", "teil_3"):
        for q in raw_set["parts"][part]:
            perfect_answers[q["id"]] = q["answer_key"]

    res_perfect = grade_lesen_answers(1, perfect_answers)
    assert res_perfect["score_raw"] == 15
    assert res_perfect["score_official"] == 25.0
    assert res_perfect["rating"] == "Sehr gut"
    assert len(res_perfect["wrong_questions"]) == 0
    assert len(res_perfect["details"]) == 15

    # 构造 10/15 正确 -> 16.7/25.0 (Befriedigend)
    partial_answers = dict(perfect_answers)
    keys = list(partial_answers.keys())
    for i in range(5):
        partial_answers[keys[i]] = "WRONG"

    res_partial = grade_lesen_answers(1, partial_answers)
    assert res_partial["score_raw"] == 10
    assert res_partial["score_official"] == 16.7
    assert res_partial["rating"] == "Befriedigend"
    assert len(res_partial["wrong_questions"]) == 5


def test_lesen_api_endpoints():
    """验证 A1 阅读 REST API 端点契约"""
    # 1. 列表端点
    r_list = client.get("/api/a1/lesen/sets")
    assert r_list.status_code == 200
    sets = r_list.json().get("sets", [])
    assert len(sets) == 6
    assert sets[0]["set_id"] == 1

    # 2. 单卷获取端点 (脱敏)
    r_set = client.get("/api/a1/lesen/set/1")
    assert r_set.status_code == 200
    s_data = r_set.json()
    assert s_data["set_id"] == 1
    assert "answer_key" not in s_data["parts"]["teil_1"][0]

    # 3. 判分端点
    grade_payload = {
        "set_id": 1,
        "duration_seconds": 900,
        "answers": {"a1_l_01_t1_q01": "R"}
    }
    r_grade = client.post("/api/a1/lesen/grade", json=grade_payload)
    assert r_grade.status_code == 200
    grade_res = r_grade.json()
    assert "score_official" in grade_res
    assert "rating" in grade_res
    assert "details" in grade_res

    # 4. 历史记录端点
    r_hist = client.get("/api/a1/lesen/history")
    assert r_hist.status_code == 200
    assert isinstance(r_hist.json().get("history", []), list)
