# -*- coding: utf-8 -*-
"""`tools/bench_judge_fp.py` 的行为契约测试（Task 6 的 AFK 半）。

钉住什么（为什么这些断言不是恒真）
--------------------------------
1. **样本集有效性判据**：标注缺失 / 空样本 ⇒ ``validate_samples`` 非空、
   ``measure_candidates`` 抛 ValueError、CLI 退出码 1（"样本集自身无效"的语义锚）。
2. **计数的可证伪性**：用两个方向相反的桩探测（永不报 / 永远报）喂同一批样本，
   断言 FP/FN 计数在两端都正确 —— 只断言"永不报 ⇒ FP=0"是恒真死断言
   （实现写坏时 0 == 0 照样成立），必须配"永远报 ⇒ FP=全部期望不报句"的反向断言。
3. **Report 形状**：``fp_samples`` / ``fn_samples`` 键必须存在，且装载误报/漏报句
   全文（带来源前缀、顺序确定）—— "只报比例无法证伪判据"是本任务的红线。
4. **确定性**：同输入两次测量输出逐字节一致（"可复跑"的硬条件）。
5. **内置样本集自洽**：10 篇官方范文 + 每维 ≥5 定向错误句 + ≥5 正确对照组、
   标注齐全（防后续有人删样本让标定失真）。
6. **环境不可用 = 退出码 2**：spaCy 缺失（ImportError 原始形态）/ 模型加载失败
   （RuntimeError）都归口 ``probe_environment`` 映射为 2，不与"样本集无效 = 1"
   撞语义（注入桩 loader，不真删包、不真坏环境）。
7. **样本外追补必须出现在产物**：A 维 3 句样本外误报的原文 + 实测结果必须在
   verdict（text 与 ``--json`` 同源）与 CLI 区块可寻，且**不得**混入冻结样本集
   —— 防退化成"只住 docstring"的系统性乐观（评审 RED）。

反挂死纪律：本文件无 sleep / 无线程 / 无循环等待；唯一的子进程调用带固定
timeout（防挂死防线，实测 ~1.5s）。
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "tools" / "bench_judge_fp.py"

# 桩探测的触发标记（样本句里含它就被"报"）。
_MARKER = "FALSCH"


def _load_bench_module() -> types.ModuleType:
    """按路径加载 ``tools/bench_judge_fp.py``（tools/ 不是 package，同 tests/test_audit_official_vocab.py 模式）。

    注意 MUST 先注册 ``sys.modules``：被测脚本用 ``from __future__ import annotations``，
    dataclasses 在 exec 期会查 ``sys.modules[cls.__module__]`` 解析字符串注解 ——
    不注册时动态加载直接 AttributeError（2026-10-15 实测踩坑，别再省这一步）。
    """
    spec = importlib.util.spec_from_file_location("bench_judge_fp_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_bench_module()


def _stub(name: str, reports: bool) -> Any:
    """构造桩候选：``reports=True`` ⇒ 永远报；False ⇒ 永不报。"""
    return bench.Candidate(name=name, description=f"stub(always={reports})", detect=lambda _s: reports)


def _stub_by_marker() -> Any:
    """构造桩候选：句含 ``FALSCH`` 才报（用来钉"定向错误句被报"）。"""
    return bench.Candidate(name="stub", description="含 FALSCH 才报", detect=lambda s: _MARKER in s)


def test_missing_label_invalidates_samples() -> None:
    """标注缺失（expected=None）⇒ 样本集无效：validate 报错 + measure 抛 ValueError。"""
    candidates = [_stub("stub", reports=False)]
    negatives = {"stub": [bench.LabeledSentence("Ein Satz ohne Label.", None, "nolabel")]}
    errors = bench.validate_samples(candidates, ["Ein korrekter Satz."], negatives)
    assert errors, "缺标注必须被 validate_samples 判为无效"
    assert any("缺标注" in e for e in errors)
    try:
        bench.measure_candidates(candidates, ["Ein korrekter Satz."], negatives)
    except ValueError as exc:
        assert "样本集无效" in str(exc)
    else:  # pragma: no cover - 防御：不抛就是契约破坏
        raise AssertionError("measure_candidates 对缺标注样本集必须抛 ValueError")


def test_empty_samples_invalidate() -> None:
    """空正样本 / 空负样本维度 ⇒ validate 非空（"空样本"一类的退出码 1 锚点）。"""
    candidates = [_stub("stub", reports=False)]
    ok_neg = {"stub": [bench.LabeledSentence("Ein Satz.", False, "ctrl")]}
    assert bench.validate_samples(candidates, [], ok_neg), "空正样本必须被判无效"
    assert bench.validate_samples(candidates, ["Ein Satz."], {}), "空负样本集必须被判无效"
    assert bench.validate_samples(candidates, ["Ein Satz."], {"stub": []}), "空的负样本维度必须被判无效"


def test_cli_missing_label_exits_nonzero(tmp_path: Path) -> None:
    """CLI 层：--negatives 指向缺 expected 的 JSON ⇒ 退出码 1（非零 = 标定未完成）。"""
    bad = tmp_path / "bad_negatives.json"
    bad.write_text(
        json.dumps(
            {
                "a_modal_frame_order": [{"text": "Ich muss gehen heute nach Hause.", "note": "nolabel"}],
                "b_past_anchor_tense_conflict": [{"text": "Gestern gehe ich zur Schule.", "expected": True}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--negatives", str(bad)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        env=env,
        cwd=str(_ROOT),
    )
    assert proc.returncode == 1, f"缺标注必须退出码 1（实际 {proc.returncode}）\nstderr={proc.stderr}"
    assert "样本集无效" in proc.stderr


def test_all_correct_samples_zero_fp() -> None:
    """全部正确样本（期望不报）⇒ FP 计数 0 —— 并配"永远报"的反向断言防恒真。"""
    positives = ["Ein voellig korrekter Satz."]
    negatives = {"stub": [bench.LabeledSentence("Noch ein korrekter Satz.", False, "ctrl1")]}

    never = bench.measure_candidates([_stub("stub", reports=False)], positives, negatives)
    entry = never["per_candidate"][0]
    assert entry["fp"] == 0
    assert entry["fn"] == 0
    assert entry["fp_samples"] == []
    assert entry["fn_samples"] == []

    # 反向对照（防恒真）：同一批全正确样本，"永远报"必须把每句都记成 FP。
    always = bench.measure_candidates([_stub("stub", reports=True)], positives, negatives)
    entry_always = always["per_candidate"][0]
    assert entry_always["fp"] == 2, "1 句正样本 + 1 句对照组，全部应为 FP"
    assert len(entry_always["fp_samples"]) == 2


def test_targeted_wrong_samples_zero_fn() -> None:
    """定向错误样本（期望报）⇒ 被正确报出时 FN 计数 0；配"永不报"的反向断言。"""
    positives = ["Ein korrekter Satz."]
    negatives = {
        "stub": [
            bench.LabeledSentence("FALSCH Satz eins.", True, "err1"),
            bench.LabeledSentence("FALSCH Satz zwei.", True, "err2"),
        ]
    }
    always = bench.measure_candidates([_stub("stub", reports=True)], positives, negatives)
    entry = always["per_candidate"][0]
    assert entry["fn"] == 0
    assert entry["fn_samples"] == []

    never = bench.measure_candidates([_stub("stub", reports=False)], positives, negatives)
    entry_never = never["per_candidate"][0]
    assert entry_never["fn"] == 2, "两句定向错误句全部漏报"
    assert len(entry_never["fn_samples"]) == 2


def test_report_contains_sample_keys_with_full_text() -> None:
    """Report 形状契约：per_candidate 键集合 + 样例行 = 带来源前缀的句全文（顺序确定）。"""
    positives = ["Ein Satz."]
    negatives = {
        "stub": [
            bench.LabeledSentence("Zwei Satz.", False, "ctrl"),
            bench.LabeledSentence("Drei Satz.", True, "err"),
        ]
    }
    always = bench.measure_candidates([_stub("stub", reports=True)], positives, negatives)
    entry = always["per_candidate"][0]
    assert set(entry.keys()) == {"name", "fp", "fn", "fp_samples", "fn_samples"}
    assert entry["name"] == "stub"
    # 误报样例 = 正样本句 + 对照组句（各带来源前缀；顺序 = 正样本在前、负样本按输入序）。
    assert entry["fp_samples"] == ["[positive#1] Ein Satz.", "[ctrl] Zwei Satz."]
    # 定向错误句被报 ⇒ 不进 fn_samples。
    assert entry["fn_samples"] == []
    # verdict 是 dict[str, str]（只含量与阈值对照）。
    assert isinstance(always["verdict"], dict)
    assert isinstance(always["verdict"]["stub"], str)
    assert "阈值" in always["verdict"]["stub"]

    # 反向：永"不漏"的另一端 —— 永不报时 fn_samples 装载的是漏报句全文。
    never = bench.measure_candidates([_stub("stub", reports=False)], positives, negatives)
    entry_never = never["per_candidate"][0]
    assert entry_never["fn_samples"] == ["[err] Drei Satz."]
    assert entry_never["fp_samples"] == []


def test_determinism_same_input_same_output() -> None:
    """同输入两次测量，输出必须逐字节一致（可复跑纪律）。"""
    candidate = _stub_by_marker()
    positives = ["Ein korrekter Satz. Und FALSCH ein zweiter."]
    negatives = {
        "stub": [
            bench.LabeledSentence("FALSCH hier.", True, "err1"),
            bench.LabeledSentence("Alles gut.", False, "ctrl1"),
        ]
    }
    first = bench.measure_candidates([candidate], positives, negatives)
    second = bench.measure_candidates([candidate], positives, negatives)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


def test_default_dataset_is_valid_and_meets_min_size() -> None:
    """内置样本集自洽：10 篇范文 + 每维 ≥5 定向错误 + ≥5 对照组、标注齐全。"""
    pairs = bench.load_positives()
    assert len(pairs) == 10, "正样本 = A1_SCHREIBEN_TEIL2 全部 10 篇"
    assert all(entry_id and text for entry_id, text in pairs)
    texts = [text for _, text in pairs]
    assert bench.validate_samples(bench.CANDIDATES, texts, bench.NEGATIVES) == []
    for name in ("a_modal_frame_order", "b_past_anchor_tense_conflict"):
        items = bench.NEGATIVES[name]
        errs = [it for it in items if it.expected is True]
        ctrls = [it for it in items if it.expected is False]
        assert len(errs) >= 5, f"{name} 的定向错误句不足 5 条"
        assert len(ctrls) >= 5, f"{name} 的正确对照组不足 5 条"


def _raiser(exc: BaseException) -> Any:
    """构造"调用即抛指定异常"的桩 loader（注入环境探测，不真删包、不真坏环境）。"""

    def _raise() -> Any:
        raise exc

    return _raise


def test_environment_unavailable_maps_to_exit_code_2(monkeypatch: Any, capsys: Any) -> None:
    """环境不可用 ⇒ 退出码 2（与"样本集无效 = 1"分语义）；注入桩，不真删包/不真坏环境。"""
    # 1) 探测函数是"rc=2"的单一归口：可用 ⇒ None；两类环境故障都返回原因文本。
    assert bench.probe_environment(lambda: object()) is None, "环境可用时探测必须返回 None"
    import_err = bench.probe_environment(_raiser(ImportError("No module named 'spacy'")))
    assert import_err is not None and "spacy" in import_err
    runtime_err = bench.probe_environment(_raiser(RuntimeError("德语模型加载失败")))
    assert runtime_err is not None and "德语模型加载失败" in runtime_err

    # 2) CLI 主路径：spaCy 缺失的原始形态（ImportError 直接外泄）必须被转成 2，
    #    而不是未捕获异常（rc=1，与"样本集无效"撞语义）。
    monkeypatch.setattr(bench, "_load_nlp", _raiser(ImportError("No module named 'spacy'")))
    rc = bench.main([])
    assert rc == 2, f"环境不可用必须退出码 2（实际 {rc}）"
    captured = capsys.readouterr()
    assert "环境不可用" in captured.err


def test_out_of_sample_supplement_is_in_product(monkeypatch: Any, capsys: Any) -> None:
    """RED 修复钉：A 维样本外追补的原文+结果必须进产物，且**不得**混入冻结样本集。

    无模型依赖：verdict 走合成输入、CLI 区块注入桩结果（不真跑 spaCy）。
    """
    # 1) 追补集形状：3 句、第 1 句 = 评审记录句、逐句非空、与冻结样本集**零重叠**
    #    （混入会改动 fp/fn 计数，破坏"计数冻结"纪律）。
    assert len(bench.OUT_OF_SAMPLE_A) == 3
    assert bench.OUT_OF_SAMPLE_A[0] == "Ich kann nicht kommen, ich muss arbeiten."
    assert all(text.strip() for text in bench.OUT_OF_SAMPLE_A)
    frozen = {item.text for items in bench.NEGATIVES.values() for item in items}
    assert not (set(bench.OUT_OF_SAMPLE_A) & frozen), "追补句不得混入冻结样本集"

    # 2) verdict（text 与 --json 同源）：A 维必须带追补句与翻档结论；B 维不得带。
    outcomes = [bench.SentenceOutcome("TN", "positive", "p1", False, False, "Ein Satz.")]
    oos = [(text, True) for text in bench.OUT_OF_SAMPLE_A]
    a_verdict = bench._verdict_text(outcomes, oos)
    assert "样本外追补" in a_verdict
    assert "未入本冻结集" in a_verdict
    assert "3 个变体中 3 个报 True" in a_verdict
    assert "warning 档条件亦不成立" in a_verdict, "3 句报 True 计入对照组时必须翻掉 warning 档条件"
    b_verdict = bench._verdict_text(outcomes, None)
    assert "样本外追补" not in b_verdict

    # 3) CLI 独立区块：注入桩结果 ⇒ 必须打印 3 句原文与结果（含 err7 族结构性边界）。
    monkeypatch.setattr(bench, "_out_of_sample_a_results", lambda: [(text, True) for text in bench.OUT_OF_SAMPLE_A])
    report = {
        "per_candidate": [
            {"name": "a_modal_frame_order", "fp": 0, "fn": 0, "fp_samples": [], "fn_samples": []},
            {"name": "b_past_anchor_tense_conflict", "fp": 0, "fn": 0, "fp_samples": [], "fn_samples": []},
        ],
        "verdict": {},
    }
    details: dict[str, list[Any]] = {"a_modal_frame_order": [], "b_past_anchor_tense_conflict": []}
    bench._print_text_report(report, details, bench.CANDIDATES, 1, 0)
    out = capsys.readouterr().out
    assert "样本外追补（不入计数）" in out
    for text in bench.OUT_OF_SAMPLE_A:
        assert text in out, f"区块缺原文：{text}"
    assert "[报=True]" in out
    assert "err7" in out
