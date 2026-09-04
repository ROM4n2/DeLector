# -*- coding: utf-8 -*-
"""
Contract and regression tests for Goethe-Zertifikat A1 Schreiben Workshop.
Teil 1 (Formular-Training) + Teil 2 (30-Wort E-Mail & Brief Lab).
"""
import os
from pathlib import Path
import pytest
os.environ.setdefault("DATABASE_PATH", "test_delector_goethe_a1_writing.db")
from fastapi.testclient import TestClient
from server import app
import a1_writing_dict
from writing_rules import analyze_a1_email, check_a1_formular_answer


def test_a1_writing_dict_dataset_integrity():
    """验证 A1 写作题库数据集完整性与规范。"""
    assert len(a1_writing_dict.A1_SCHREIBEN_TEIL1) >= 8
    for ex in a1_writing_dict.A1_SCHREIBEN_TEIL1:
        assert "id" in ex
        assert "title" in ex
        assert "passage" in ex
        assert len(ex["passage"]) > 20
        assert "fields" in ex
        assert len(ex["fields"]) == 5, f"Teil 1 表格必须严格包含 5 个填空题: {ex['id']}"
        for fld in ex["fields"]:
            assert "label" in fld
            assert "answer" in fld
            assert "aliases" in fld
            assert isinstance(fld["aliases"], list)
            assert "tip" in fld

    assert len(a1_writing_dict.A1_SCHREIBEN_TEIL2) >= 10
    for ex in a1_writing_dict.A1_SCHREIBEN_TEIL2:
        assert "id" in ex
        assert "scenario" in ex
        assert "prompt" in ex
        assert "leitpunkte" in ex
        assert len(ex["leitpunkte"]) == 3, f"Teil 2 考题必须严格包含 3 个导向点: {ex['id']}"
        assert "sample_email" in ex
        assert len(ex["sample_email"]) > 30
        assert "sample_translation" in ex


def test_a1_formular_answer_checker():
    """验证填表答案校验器：支持大小写不敏感、别名容错与数字/日期变体。"""
    # 姓名大小写与空格
    res1 = check_a1_formular_answer("Müller", "Müller", ["Mueller", "MÜLLER"])
    assert res1["correct"] is True

    res2 = check_a1_formular_answer(" mueller ", "Müller", ["Mueller"])
    assert res2["correct"] is True

    # 日期容错 (15.03. vs 15. März vs 15.3.)
    res3 = check_a1_formular_answer("15. März", "15.03.", ["15. März", "15.3", "15.3."])
    assert res3["correct"] is True

    # 错误答案
    res4 = check_a1_formular_answer("Berlin", "München", ["Munich"])
    assert res4["correct"] is False
    assert res4["expected"] == "München"


def test_a1_email_analyzer_greeting_and_lowercase_start():
    """验证短电邮称呼语与正文首字母小写规则。"""
    # 正确写法：称呼 + 逗号 -> 换行后正文首字母小写
    good_email = (
        "Liebe Maria,\n"
        "ich lade dich herzlich zu meiner Geburtstagsparty ein. "
        "Die Party beginnt am Samstag um 18 Uhr bei mir zu Hause. "
        "Kannst du einen Kuchen mitbringen?\n"
        "Viele Grüße\n"
        "Anna"
    )
    report_good = analyze_a1_email(good_email, ["Geburtstagsparty", "Samstag", "Kuchen"])
    assert report_good["greeting"]["valid"] is True
    assert report_good["greeting"]["type"] == "informal"
    assert report_good["has_lowercase_start_error"] is False
    assert report_good["has_valediction_comma_error"] is False

    # 错误写法：称呼后逗号，但正文首字母大写
    bad_start_email = (
        "Liebe Maria,\n"
        "Ich lade dich zu meiner Party ein.\n"
        "Viele Grüße\n"
        "Anna"
    )
    report_bad_start = analyze_a1_email(bad_start_email, [])
    assert report_bad_start["has_lowercase_start_error"] is True


def test_a1_email_analyzer_valediction_and_comma_rule():
    """验证德语书信结尾祝福不得带逗号（德语与英语习惯不同）。"""
    # 德语书信结尾带逗号错误
    bad_comma_email = (
        "Lieber Max,\n"
        "wie geht es dir? Ich komme morgen um 15 Uhr.\n"
        "Viele Grüße,\n"
        "Thomas"
    )
    report = analyze_a1_email(bad_comma_email, [])
    assert report["has_valediction_comma_error"] is True
    assert report["valediction"]["valid"] is True

    # 正式尊称与结语
    formal_email = (
        "Sehr geehrte Damen und Herren,\n"
        "ich möchte ein Doppelzimmer reservieren. Ich komme am 12. Mai an.\n"
        "Mit freundlichen Grüßen\n"
        "Hans Schmidt"
    )
    rep_formal = analyze_a1_email(formal_email, ["Doppelzimmer", "12. Mai"])
    assert rep_formal["greeting"]["type"] == "formal"
    assert rep_formal["valediction"]["valid"] is True
    assert rep_formal["has_valediction_comma_error"] is False


def test_a1_email_analyzer_word_count_and_leitpunkte():
    """验证词数统计区间与 Leitpunkte 导向点覆盖检测。"""
    short_text = "Liebe Anna,\nkomm bitte morgen.\nViele Grüße\nMax"
    rep_short = analyze_a1_email(short_text, ["morgen kommen", "Party", "Essen"])
    assert rep_short["word_count"] < 20
    assert rep_short["word_count_status"] == "too_short"

    # 标准 30 词范文
    perfect_text = (
        "Lieber Herr Meyer,\n"
        "ich kann am Montag leider nicht zum Deutschkurs kommen, weil ich krank bin und zum Arzt muss. "
        "Was sind die Hausaufgaben für Dienstag?\n"
        "Mit freundlichen Grüßen\n"
        "Li Wei"
    )
    rep_perfect = analyze_a1_email(
        perfect_text,
        ["nicht kommen", "warum / krank", "Hausaufgaben"]
    )
    assert 25 <= rep_perfect["word_count"] <= 40
    assert rep_perfect["word_count_status"] == "optimal"
    assert rep_perfect["leitpunkte_matches"] >= 2


def test_api_a1_schreiben_teil1_endpoints():
    """验证 /api/a1/schreiben/teil1 列表获取与智能判分 API。"""
    client = TestClient(app)

    # GET 列表
    res = client.get("/api/a1/schreiben/teil1")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 8
    first_ex = data[0]

    # POST 提交判分
    payload = {
        "exercise_id": first_ex["id"],
        "answers": {
            fld["key"]: fld["answer"] for fld in first_ex["fields"]
        }
    }
    check_res = client.post("/api/a1/schreiben/teil1/check", json=payload)
    assert check_res.status_code == 200
    check_data = check_res.json()
    assert check_data["score"] == 5
    assert check_data["total"] == 5
    assert check_data["all_correct"] is True


def test_api_a1_schreiben_teil2_endpoints():
    """验证 /api/a1/schreiben/teil2 模板获取与诊断 API。"""
    client = TestClient(app)

    # GET 题目与模板
    res = client.get("/api/a1/schreiben/teil2")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 10

    # POST 智能诊断
    payload = {
        "text": (
            "Liebe Sarah,\n"
            "danke für die Einladung. Ich komme sehr gern zu deinem Fest. "
            "Ich bringe einen leckeren Salat mit.\n"
            "Herzliche Grüße\n"
            "Lin"
        ),
        "leitpunkte": ["Bedanken", "Zusagen", "Was mitbringen"]
    }
    diag_res = client.post("/api/a1/schreiben/teil2/diagnose", json=payload)
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    assert "word_count" in diag_data
    assert "greeting" in diag_data
    assert "valediction" in diag_data
    assert "suggestions" in diag_data


def test_a1_writing_frontend_html_and_css():
    """验证 static/index.html 与 static/style.css 中 A1 写作工坊 DOM 与样式契约。

    ADR-0005 Task 2 起写作工坊迁入备考域：writer-mode-a1-* 按钮删除，
    页签改名 exam-tab-*（宿主 view-exam）；面板 id 不变、原样搬移。
    """
    root = Path(__file__).resolve().parent
    html = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="exam-tab-formular"' in html
    assert 'id="exam-tab-email"' in html
    assert 'id="a1-formular-view"' in html
    assert 'id="a1-email-view"' in html

    css = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert ".a1-formular-table" in css or ".a1-formular-card" in css
    assert ".a1-leitpunkte-box" in css or ".a1-leitpunkt-item" in css


@pytest.fixture(autouse=True, scope="module")
def _m5_isolated_db_teardown():
    """M5-1: 模块结束时回收句柄并删除隔离临时库，防残留串入下次运行。"""
    yield
    import gc, os as _os
    gc.collect()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        try:
            _os.remove("test_delector_goethe_a1_writing.db" + _suffix)
        except OSError:
            pass
