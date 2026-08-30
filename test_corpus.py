# -*- coding: utf-8 -*-
"""官方真题语料库单元与契约测试 (Corpus Engine Test Suite)"""
import pytest
from starlette.testclient import TestClient


def test_corpus_collection_volume_and_coverage():
    """验证语料库包含 12 篇权威篇章，覆盖 A1~B2/TestDaF 以及 4 大主题分类。"""
    from corpus_dict import OFFICIAL_CORPUS, get_corpus_list, get_corpus_by_id

    assert len(OFFICIAL_CORPUS) >= 12, f"语料库篇章数不足 12 篇，当前为 {len(OFFICIAL_CORPUS)}"

    cefr_levels = {item["cefr"] for item in OFFICIAL_CORPUS}
    assert {"A1", "A2", "B1", "B2"}.issubset(cefr_levels), f"CEFR 等级覆盖缺失：{cefr_levels}"

    categories = {item["category"] for item in OFFICIAL_CORPUS}
    expected_categories = {"Campus & Studium", "Wissenschaft & Technik", "Gesellschaft & Kultur", "Beruf & Alltag"}
    assert expected_categories.issubset(categories), f"分类覆盖缺失：{categories}"

    # 验证 ID 唯一性
    ids = [item["id"] for item in OFFICIAL_CORPUS]
    assert len(ids) == len(set(ids)), "语料库存在重复 ID"


def test_corpus_entry_schema_and_hygiene():
    """验证每篇语料字段完整性、正文字数合理性以及题目有效性。"""
    from corpus_dict import OFFICIAL_CORPUS

    for item in OFFICIAL_CORPUS:
        cid = item.get("id")
        assert cid, "语料缺少 id"
        assert item.get("title"), f"语料 {cid} 缺少 title"
        assert item.get("cefr") in {"A1", "A2", "B1", "B2", "C1"}, f"语料 {cid} CEFR 等级无效: {item.get('cefr')}"
        assert item.get("category"), f"语料 {cid} 缺少 category"
        assert item.get("source_exam"), f"语料 {cid} 缺少 source_exam"
        assert item.get("summary_zh"), f"语料 {cid} 缺少 summary_zh"

        content = item.get("content", "").strip()
        assert len(content) > 60, f"语料 {cid} 正文过短（{len(content)} 字符）"
        assert item.get("word_count") > 20, f"语料 {cid} 词数无效"

        lexemes = item.get("key_lexemes", [])
        assert isinstance(lexemes, list) and len(lexemes) >= 2, f"语料 {cid} 重点考点词至少 2 个"

        questions = item.get("reading_questions", [])
        assert isinstance(questions, list) and len(questions) >= 1, f"语料 {cid} 至少包含 1 道阅读理解验证题"
        for q in questions:
            assert q.get("question"), f"语料 {cid} 题目无题干"
            opts = q.get("options", [])
            assert len(opts) >= 2, f"语料 {cid} 选项至少 2 项"
            ans_idx = q.get("answer_idx")
            assert 0 <= ans_idx < len(opts), f"语料 {cid} 答案索引越界: {ans_idx}"
            assert q.get("explanation_zh"), f"语料 {cid} 题目缺少中文解析"


def test_get_corpus_filter_helpers():
    """验证按 CEFR 和 Category 过滤查询助手。"""
    from corpus_dict import get_corpus_list, get_corpus_by_id

    # 查全部（只返回目录元数据，不含完整 content）
    all_list = get_corpus_list()
    assert len(all_list) >= 12
    assert "content" not in all_list[0], "目录列表不应冗余包含完整正文以提高性能"

    # 按 CEFR 过滤
    b1_list = get_corpus_list(cefr="B1")
    assert all(item["cefr"] == "B1" for item in b1_list)
    assert len(b1_list) >= 2

    # 按 Category 过滤
    campus_list = get_corpus_list(category="Campus & Studium")
    assert all(item["category"] == "Campus & Studium" for item in campus_list)
    assert len(campus_list) >= 2

    # 单篇详情查询
    first_id = all_list[0]["id"]
    detail = get_corpus_by_id(first_id)
    assert detail is not None
    assert detail["id"] == first_id
    assert "content" in detail

    # 不存在的 ID
    assert get_corpus_by_id("non_existent_id") is None


def test_corpus_api_endpoints():
    """验证 GET /api/corpus/list 与 GET /api/corpus/{id} 契约。"""
    from server import app
    client = TestClient(app)

    # 1. 列表端点
    resp = client.get("/api/corpus/list")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 12
    assert "title" in items[0]
    assert "content" not in items[0]

    # 2. 过滤查询
    resp_b1 = client.get("/api/corpus/list?cefr=B1")
    assert resp_b1.status_code == 200
    for it in resp_b1.json():
        assert it["cefr"] == "B1"

    # 3. 详情端点
    first_id = items[0]["id"]
    resp_detail = client.get(f"/api/corpus/{first_id}")
    assert resp_detail.status_code == 200
    data = resp_detail.json()
    assert data["id"] == first_id
    assert "content" in data
    assert len(data["reading_questions"]) >= 1

    # 4. 404 测试
    resp_404 = client.get("/api/corpus/invalid_non_existent")
    assert resp_404.status_code == 404
