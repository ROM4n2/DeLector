# -*- coding: utf-8 -*-
"""Task R7：官方词表来源对账工具（tools/audit_official_vocab.py）的行为测试。

TDD 口径：用**小型人工 fixture** 断言纯函数 :func:`audit` 的四类输出与确定性，
不依赖真实大数据（避免脆弱）。每条断言都能在「实现写错」时变红（无恒真死断言）。

``tools/`` 不是 package（见 tests/test_server.py 的 _load_build_prep），故按路径加载被测模块。
"""

import copy
import importlib.util
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_auditor():
    """按路径加载 tools/audit_official_vocab.py（tools/ 不是 package）。"""
    path = os.path.join(_ROOT, "tools", "audit_official_vocab.py")
    spec = importlib.util.spec_from_file_location("audit_official_vocab_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_auditor = _load_auditor()


# 小型人工 fixture：构造已知交集 / 已知 cefr 冲突 / 已知噪声（合法词 + 英语词 + 坏字符）。
_FRAGMENTS = {
    "ai": {
        "haus": ("A1", "NOUN", "Neut", "-..er", "房子"),
        "laufen": ("A2", "VERB", None, "", "跑"),
        "dishwasher": ("A2", "NOUN", "Masc", "-", "洗碗机"),
        "haus2": ("B1", "NOUN", "Neut", "-", "坏字符"),
        "schreiben": ("B1", "VERB", None, "", "写"),
    },
    "manual": {
        "haus": ("A1", "NOUN", "Neut", "-..er", "房屋"),
        "laufen": ("B1", "VERB", None, "", "奔跑"),
        "lesen": ("A1", "VERB", None, "", "读"),
    },
    "official": {
        "haus": ("A2", "NOUN", "Neut", "-", "家"),
        "laufen": ("A2", "VERB", None, "", "跑"),
        "gehen": ("A1", "VERB", None, "", "走"),
    },
}


def test_counts():
    """各来源条数：ai=5 / manual=3 / official=3。"""
    report = _auditor.audit(_FRAGMENTS)
    assert report["counts"] == {"ai": 5, "manual": 3, "official": 3}


def test_pairwise_intersection_and_deltas():
    """两两来源的 intersection / only_a / only_b 必须精确。"""
    report = _auditor.audit(_FRAGMENTS)
    pw = report["pairwise"]
    # ai ∩ manual = {haus, laufen}；only_ai = {dishwasher, haus2, schreiben}；only_manual = {lesen}
    assert pw["ai|manual"]["intersection"] == 2
    assert pw["ai|manual"]["only_a"] == 3
    assert pw["ai|manual"]["only_b"] == 1
    # ai ∩ official = {haus, laufen}；only_official = {gehen}
    assert pw["ai|official"]["intersection"] == 2
    assert pw["ai|official"]["only_a"] == 3
    assert pw["ai|official"]["only_b"] == 1
    # manual ∩ official = {haus, laufen}；only_manual = only_official = 1
    assert pw["manual|official"]["intersection"] == 2
    assert pw["manual|official"]["only_a"] == 1
    assert pw["manual|official"]["only_b"] == 1


def test_cefr_conflicts_detected():
    """同 lemma 不同 cefr 必须命中，且明细按来源记录 cefr。"""
    report = _auditor.audit(_FRAGMENTS)
    cc = report["cefr_conflicts"]
    assert cc["count"] == 2
    flagged = {d["lemma"] for d in cc["details"]}
    assert flagged == {"haus", "laufen"}
    haus = next(d for d in cc["details"] if d["lemma"] == "haus")
    assert haus["by_source"] == {"ai": "A1", "manual": "A1", "official": "A2"}
    laufen = next(d for d in cc["details"] if d["lemma"] == "laufen")
    assert laufen["by_source"] == {"ai": "A2", "manual": "B1", "official": "A2"}


def test_cefr_no_conflict_when_sources_agree():
    """同 lemma 同 cefr（即来源一致）不得命中 —— 与上一条形成对照（防恒真）。"""
    same = {
        "ai": {"haus": ("A1", "NOUN", "Neut", "-", "房子")},
        "manual": {"haus": ("A1", "NOUN", "Neut", "-", "房屋")},
        "official": {"haus": ("A1", "NOUN", "Neut", "-", "家")},
    }
    report = _auditor.audit(same)
    assert report["cefr_conflicts"]["count"] == 0
    assert report["cefr_conflicts"]["details"] == []


def test_noise_candidates_detect_and_no_false_positive():
    """英语词黑名单 + 非德语字符命中；合法德语词不得误报。"""
    report = _auditor.audit(_FRAGMENTS)
    nc = report["noise_candidates"]
    flagged = {(d["lemma"], d["source"]) for d in nc["details"]}
    assert ("dishwasher", "ai") in flagged  # 英语黑名单命中
    assert ("haus2", "ai") in flagged  # 非德语字符集外字符命中
    legal = {"haus", "laufen", "schreiben", "lesen", "gehen"}
    assert not (legal & {d["lemma"] for d in nc["details"]})  # 合法德语词零误报
    assert nc["count"] == 2


def test_pure_and_deterministic():
    """纯函数：两次调用结果相等（确定性），且不改写输入。"""
    snapshot = copy.deepcopy(_FRAGMENTS)
    first = _auditor.audit(_FRAGMENTS)
    second = _auditor.audit(_FRAGMENTS)
    assert first == second  # 确定性
    assert _FRAGMENTS == snapshot  # 无副作用（未改动输入）
    # 等值但独立的输入 → 结果一致
    assert _auditor.audit(copy.deepcopy(_FRAGMENTS)) == first
