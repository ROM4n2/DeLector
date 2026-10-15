# -*- coding: utf-8 -*-
"""
Contract and regression tests for Goethe-Zertifikat A1 Schreiben Workshop.
Teil 1 (Formular-Training) + Teil 2 (30-Wort E-Mail & Brief Lab).
"""

import os
from pathlib import Path

import pytest
import spacy

os.environ.setdefault("DATABASE_PATH", "test_delector_goethe_a1_writing.db")
from fastapi.testclient import TestClient

from delector.data import a1_writing_dict
from delector.routes.main import violations_for
from delector.server import app
from delector.services.polish_loop import default_violations_of
from delector.services.writing import analyze_a1_email, check_a1_formular_answer, collect_violations


@pytest.fixture(scope="module")
def nlp():
    """真 spaCy 模型（沿用 `tests/test_writing_rules.py` 的 nlp fixture 惯例）；缺失 ⇒ skip。"""
    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


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
    bad_start_email = "Liebe Maria,\nIch lade dich zu meiner Party ein.\nViele Grüße\nAnna"
    report_bad_start = analyze_a1_email(bad_start_email, [])
    assert report_bad_start["has_lowercase_start_error"] is True


def test_a1_email_analyzer_valediction_and_comma_rule():
    """验证德语书信结尾祝福不得带逗号（德语与英语习惯不同）。"""
    # 德语书信结尾带逗号错误
    bad_comma_email = "Lieber Max,\nwie geht es dir? Ich komme morgen um 15 Uhr.\nViele Grüße,\nThomas"
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
    rep_perfect = analyze_a1_email(perfect_text, ["nicht kommen", "warum / krank", "Hausaufgaben"])
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
    payload = {"exercise_id": first_ex["id"], "answers": {fld["key"]: fld["answer"] for fld in first_ex["fields"]}}
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
        "leitpunkte": ["Bedanken", "Zusagen", "Was mitbringen"],
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
    root = Path(__file__).resolve().parent.parent
    html = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="exam-tab-formular"' in html
    assert 'id="exam-tab-email"' in html
    assert 'id="a1-formular-view"' in html
    assert 'id="a1-email-view"' in html

    css = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert ".a1-formular-table" in css or ".a1-formular-card" in css
    assert ".a1-leitpunkte-box" in css or ".a1-leitpunkt-item" in css


_ESSAY_TEXT = "Ich habe ein Hund. Er ist gut."  # 非书信体（普通作文）
# 书信体：正文首词小写已对，但结语后带逗号 ⇒ 恰好 1 条 error 级违规
_LETTER_TEXT = "Liebe Maria,\nich lade dich ein.\nViele Grüße,\nAnna"


def test_a1_violations_gate_format_family_still_letter_only():
    """闸门（Task 7 收窄后的口径）：格式/字数族只对书信体生效；无语法违规的非书信文本 ⇒ 零计数。

    - 非书信体 `_ESSAY_TEXT` 的裁决体只有格式族违规（无 nlp ⇒ 语法族未跑）⇒
      `violations_for("prose", ·)` 为 [] —— 但这**不等于**「裁判判定无错」：语义是
      「格式族对本文本不适用 + 语法族没有可计的东西」，与旧文档的措辞不同、结论按本次输入相同。
    - 书信体照常计数（闸门必须**有选择性**，一律返回 [] 是关掉裁判，不是闸门）。
    """
    verdict_letter = analyze_a1_email(_LETTER_TEXT)
    verdict_essay = analyze_a1_email(_ESSAY_TEXT)

    assert verdict_letter["greeting"]["valid"] is True
    assert verdict_essay["greeting"]["valid"] is False

    # 无闸门时：非书信体被判「缺少称呼语」= error ⇒ v_0 = 1 ⇒ 循环会误判「改不动」
    assert len(default_violations_of(verdict_essay)) >= 1
    # 收窄后的闸门：格式族对非书信体不计数（此处裁决体无语法违规 ⇒ 结果为空）
    assert violations_for("prose", verdict_essay) == []
    # 书信体照常计数
    assert len(violations_for("letter", verdict_letter)) >= 1


def test_a1_violations_gate_counts_grammar_for_non_letter_text(nlp):
    """★ Task 7 闸门收窄（**旧钉子的显式改写**）：非书信体 + 语法错 ⇒ 语法违规**真被计数**。

    这枚钉子此前钉住"非书信体 MUST 仍不计数"，目的就是让「闸门被收窄」不可能被静默做掉；
    2026-10-15 用户拍板收窄后，本用例**翻转口径**成为新行为的守卫（谁把闸门改回
    "非书信体一律零违规"，这条立刻红 —— 变异自证②）。

    判别力来源：先证语法错**真实存在**于裁决体（"ein Hund" ⇒ `artikel` 违规），
    再证闸门**现在**对它计数（不是「没有违规可挡」的空转），且格式族不被顺带带进来。
    """
    verdict_essay = analyze_a1_email(_ESSAY_TEXT, nlp=nlp)

    # 前提①：非书信体（称呼语不合法 ⇒ 文本族 = prose）。
    assert verdict_essay["greeting"]["valid"] is False

    # 前提②：语法族**确实**报出了违规（否则这条用例就是空转 —— 验了个不存在的东西）。
    essay_violations = collect_violations(verdict_essay)
    assert any(v["rule"] == "artikel" for v in essay_violations), (
        f"冠词格错必须被语法族捕获（夹具失效？实际={essay_violations}）"
    )

    counted = violations_for("prose", verdict_essay)
    assert any(v["rule"] == "artikel" for v in counted), "非书信体的语法违规 MUST 被计数（闸门收窄）"
    assert all(not v["rule"].startswith("a1_") for v in counted), "格式/字数族 MUST 只对书信体生效"


def test_a1_violations_gate_letter_counts_format_and_grammar(nlp):
    """闸门对照：书信体 ⇒ 格式/字数族 + 语法族**全计**（收窄不误伤书信体）。"""
    letter = "Liebe Maria,\nich habe ein Hund.\nViele Grüße,\nAnna"
    verdict = analyze_a1_email(letter, nlp=nlp)
    assert verdict["greeting"]["valid"] is True

    rules = [v["rule"] for v in violations_for("letter", verdict)]
    assert "a1_valediction_comma" in rules, "书信体的格式错 MUST 照旧计数"
    assert "artikel" in rules, "书信体的语法错 MUST 照旧计数"


def test_ai_polish_endpoint_keeps_non_letter_polish(monkeypatch):
    """契约断言：非书信文本**不会**被回退成原文（端点级，走真链路）。

    这是把循环接进通用润色端点的**设计前提** —— 没有适用性闸门时
    v_0 = v_1 = 1 ⇒ no_improvement ⇒ 回退原文 ⇒ 用户点了润色拿回原文。
    """
    polished = "Ich habe einen Hund. Er ist sehr lieb."

    async def _fake_chat(**_kwargs):
        return {"corrected_text": polished, "notes_zh": ["ein → einen (Akkusativ)"], "error_count": 1}

    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda *a, **k: "sk-stub")
    monkeypatch.setattr("delector.routes.main.llm_client.chat", _fake_chat)

    client = TestClient(app, client=("127.0.0.1", 54321))
    res = client.post("/api/writing/ai-polish/diff", json={"text": _ESSAY_TEXT})

    assert res.status_code == 200
    result = res.json()["result"]
    assert result["original"] == _ESSAY_TEXT
    assert result["corrected"] == polished, "非书信文本不得被回退成原文"
    assert result["converged"] is True
    assert result["unconverged_reason"] is None


@pytest.fixture(autouse=True, scope="module")
def _m5_isolated_db_teardown():
    """M5-1: 模块结束时回收句柄并删除隔离临时库，防残留串入下次运行。"""
    yield
    import gc
    import os as _os

    gc.collect()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        try:
            _os.remove("test_delector_goethe_a1_writing.db" + _suffix)
        except OSError:
            pass
