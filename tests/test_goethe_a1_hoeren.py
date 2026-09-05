import os
import pytest
os.environ.setdefault("DATABASE_PATH", "test_delector_goethe_a1_hoeren.db")
from starlette.testclient import TestClient
from server import app
from a1_hoeren_dict import (
    A1_HOEREN_SETS,
    get_hoeren_set_list,
    get_hoeren_set_by_id,
    grade_hoeren_answers
)

client = TestClient(app)


def test_hoeren_sets_structure():
    """验证 5 套 A1 官方听力模考卷结构完整性（每套 15 题，共 75 题）"""
    assert len(A1_HOEREN_SETS) == 5, f"Expected 5 hoeren sets, got {len(A1_HOEREN_SETS)}"

    total_q_count = 0
    for s in A1_HOEREN_SETS:
        assert "set_id" in s
        assert "title_de" in s
        assert "title_zh" in s
        assert s["total_questions"] == 15

        parts = s["parts"]
        assert "teil_1" in parts and len(parts["teil_1"]) == 6, "Teil 1 must have 6 questions"
        assert "teil_2" in parts and len(parts["teil_2"]) == 4, "Teil 2 must have 4 questions"
        assert "teil_3" in parts and len(parts["teil_3"]) == 5, "Teil 3 must have 5 questions"

        # 检查 Teil 1 题目
        for q in parts["teil_1"]:
            assert q["teil"] == 1
            assert q["repeat_count"] == 2, "Teil 1 must repeat 2 times"
            assert len(q["options"]) == 3, "Teil 1 must have 3 options (A, B, C)"
            assert q["answer_key"] in ("A", "B", "C")
            assert len(q["audio_text_de"]) > 10
            assert len(q["transcript_de"]) > 10
            assert len(q["transcript_zh"]) > 5
            assert len(q["explanation_zh"]) > 5
            assert isinstance(q.get("key_vocabulary", []), list)
            total_q_count += 1

        # 检查 Teil 2 题目 (Richtig/Falsch)
        for q in parts["teil_2"]:
            assert q["teil"] == 2
            assert q["repeat_count"] == 1, "Teil 2 must repeat only 1 time"
            assert len(q["options"]) == 2, "Teil 2 must have 2 options (R, F)"
            assert q["answer_key"] in ("R", "F")
            assert len(q["audio_text_de"]) > 10
            assert len(q["transcript_de"]) > 10
            total_q_count += 1

        # 检查 Teil 3 题目 (A/B/C)
        for q in parts["teil_3"]:
            assert q["teil"] == 3
            assert q["repeat_count"] == 2, "Teil 3 must repeat 2 times"
            assert len(q["options"]) == 3, "Teil 3 must have 3 options (A, B, C)"
            assert q["answer_key"] in ("A", "B", "C")
            assert len(q["audio_text_de"]) > 10
            assert len(q["transcript_de"]) > 10
            total_q_count += 1

    assert total_q_count == 75, f"Expected 75 total questions, got {total_q_count}"


def test_hoeren_sanitization():
    """验证做题模式下不泄露 answer_key 与 transcript"""
    clean_set = get_hoeren_set_by_id(1, sanitize=True)
    assert clean_set is not None
    assert clean_set["set_id"] == 1

    for q in clean_set["parts"]["teil_1"]:
        assert "answer_key" not in q, "answer_key must be sanitized in exam mode"
        assert "transcript_de" not in q, "transcript_de must be sanitized in exam mode"
        assert "transcript_zh" not in q, "transcript_zh must be sanitized in exam mode"
        assert "explanation_zh" not in q, "explanation_zh must be sanitized in exam mode"
        assert "audio_text_de" in q, "audio_text_de is required for TTS playback"

    raw_set = get_hoeren_set_by_id(1, sanitize=False)
    assert "answer_key" in raw_set["parts"]["teil_1"][0]


def test_hoeren_grading_algorithm():
    """验证 25 分制评分与等级评定算法"""
    # 构造全对答案
    raw_set = get_hoeren_set_by_id(1, sanitize=False)
    perfect_answers = {}
    for part in ("teil_1", "teil_2", "teil_3"):
        for q in raw_set["parts"][part]:
            perfect_answers[q["id"]] = q["answer_key"]

    res_perfect = grade_hoeren_answers(1, perfect_answers)
    assert res_perfect["score_raw"] == 15
    assert res_perfect["score_official"] == 25.0
    assert res_perfect["rating"] == "Sehr gut"
    assert len(res_perfect["wrong_questions"]) == 0
    assert len(res_perfect["details"]) == 15

    # 构造部分正确 (12/15 正确 -> 20.0/25.0)
    partial_answers = dict(perfect_answers)
    keys = list(partial_answers.keys())
    partial_answers[keys[0]] = "X"
    partial_answers[keys[1]] = "X"
    partial_answers[keys[2]] = "X"

    res_partial = grade_hoeren_answers(1, partial_answers)
    assert res_partial["score_raw"] == 12
    assert res_partial["score_official"] == 20.0
    assert res_partial["rating"] == "Sehr gut"
    assert len(res_partial["wrong_questions"]) == 3

    # 构造全错 (0/15 -> 0.0/25.0)
    res_zero = grade_hoeren_answers(1, {})
    assert res_zero["score_raw"] == 0
    assert res_zero["score_official"] == 0.0
    assert res_zero["rating"] == "Nicht bestanden"


def test_hoeren_api_endpoints():
    """验证 A1 听力 REST API 端点契约"""
    # 1. 列表端点
    r_list = client.get("/api/a1/hoeren/sets")
    assert r_list.status_code == 200
    sets = r_list.json().get("sets", [])
    assert len(sets) == 5
    assert sets[0]["set_id"] == 1

    # 2. 单卷获取端点 (脱敏)
    r_set = client.get("/api/a1/hoeren/set/1")
    assert r_set.status_code == 200
    s_data = r_set.json()
    assert s_data["set_id"] == 1
    assert "answer_key" not in s_data["parts"]["teil_1"][0]

    # 3. 判分端点
    grade_payload = {
        "set_id": 1,
        "duration_seconds": 780,
        "answers": {"a1_h_01_t1_q01": "B"}
    }
    r_grade = client.post("/api/a1/hoeren/grade", json=grade_payload)
    assert r_grade.status_code == 200
    grade_res = r_grade.json()
    assert "score_official" in grade_res
    assert "rating" in grade_res
    assert "details" in grade_res

    # 4. 历史记录端点
    r_hist = client.get("/api/a1/hoeren/history")
    assert r_hist.status_code == 200
    assert isinstance(r_hist.json().get("history", []), list)


@pytest.fixture(autouse=True, scope="module")
def _m5_isolated_db_teardown():
    """M5-1: 模块结束时回收句柄并删除隔离临时库，防残留串入下次运行。"""
    yield
    import gc, os as _os
    gc.collect()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        try:
            _os.remove("test_delector_goethe_a1_hoeren.db" + _suffix)
        except OSError:
            pass
