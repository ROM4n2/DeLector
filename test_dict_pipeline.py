# -*- coding: utf-8 -*-
"""词库/搭配生成流水线的契约测试。

这些测试锁的都是「AI 明明答了，流水线自己把答案丢掉」这一类 bug ——
它的症状是静默的：缺口被记成「AI 始终不作答」，重问只是白花钱，
而正确答案一直躺在 raw 缓存里。没有测试兜底的话改回去不会有任何报错。
"""
import os
import sys

os.environ.setdefault("DATABASE_PATH", "test_delector.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_progress.db")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))

import build_dict  # noqa: E402
import build_prep  # noqa: E402
from prep_dict import PREP_COLLOCATIONS  # noqa: E402
from core_dict import CORE_VOCAB_DB  # noqa: E402


# ── 搭配流水线：词头归一化回映射 ─────────────────────────────────────────

def test_reflexive_answer_maps_back_to_requested_key():
    """提示词要求反身动词答不带 sich 的形式，所以问 sich-freuen 必然答 freuen。

    原先按 `lemma not in asked` 直接丢弃，于是 25 个 sich-* 词头整批落空
    （collocations 与 none 双空），被记成「AI 始终不作答」。
    """
    assert build_prep._resolve_requested("freuen", {"sich-freuen"}) == ["sich-freuen"]
    # sich-<介词>-<动词> 这种三段键同样要能推回去
    assert build_prep._resolve_requested(
        "informieren", {"sich-über-informieren"}) == ["sich-über-informieren"]


def test_adjective_inflection_maps_back_to_requested_key():
    """AI 把形容词屈折还原成词元；词元的介词搭配对屈折形同样成立。"""
    assert build_prep._resolve_requested("ungünstig", {"ungünstigen"}) == ["ungünstigen"]


def test_umlaut_is_not_folded_so_minimal_pairs_stay_separate():
    """**不做变音折叠**：drucken(印刷)/drücken(按压) 是真实最小对立对。

    折叠 ä→a 能多捞回 `ubergreifen ← übergreifen` 这一个漏变音符的源词表拼写错误，
    代价是让这两个词互相领走对方的搭配 —— 张冠李戴（错数据当对的写进词库）
    比漏检和误杀都更糟，漏检至少留个看得见的缺口。
    """
    assert build_prep._resolve_requested("drücken", {"drucken"}) == []
    assert build_prep._resolve_requested("vertraglich", {"verträglich"}) == []
    # 反方向也不许
    assert build_prep._resolve_requested("drucken", {"drücken"}) == []


def test_unrelated_lemma_is_never_claimed():
    """推不出来就不认领，不能瞎挂。"""
    assert build_prep._resolve_requested("gehen", {"sich-freuen", "ungünstigen"}) == []


def test_recovered_reflexive_collocations_are_in_prep_dict():
    """回收结果真的落进了 prep_dict（不只是 matcher 单测过）。"""
    freuen = PREP_COLLOCATIONS.get("sich-freuen")
    assert freuen, "sich-freuen 的搭配应已从 raw 缓存回收"
    preps = {row[0] for row in freuen}
    assert {"auf", "über"} <= preps, f"sich freuen auf/über 都该在: {preps}"
    # 提示词要求反身义在 bedeutung_zh 里标 (sich)，回收时要保留这个标记
    assert any("(sich)" in row[2] for row in freuen)
    assert PREP_COLLOCATIONS.get("sich-bewerben"), "sich-bewerben 也该回收到"


def test_misattributed_collocations_absent_from_prep_dict():
    """变音折叠误挂的三个词头必须不在表里。

    断言直接跑 load_cache() 重新解析原始响应，而不是读已生成的 prep_dict.py：
    读产物的话，只要没人重新 emit，折叠逻辑被加回来这条也照样绿 —— 那就是个
    装饰性断言。跑解析器才能真的把回归拦住。
    """
    fresh, _ = build_prep.load_cache()
    for wrong in ("drucken", "vertraglich", "ubergreifen"):
        assert wrong not in fresh, f"{wrong} 是变音折叠误挂的产物"
        assert wrong not in PREP_COLLOCATIONS, f"{wrong} 不该留在已生成的搭配表里"


# ── 词库流水线：缓存隔离与尾缺口 ─────────────────────────────────────────

def test_refill_cache_dir_is_isolated_from_full_run():
    """缓存文件按批次序号命名，refill 的 batch_0 与整包跑的 batch_0 内容完全不同。

    共用一个目录会覆盖掉整包跑的原始响应（不可重放，只能重新付费问），
    且 --resume 会读到上一次整包跑的 batch_0，拿回一批毫不相干的词。
    """
    assert build_dict.REFILL_RAW_DIR != build_dict.RAW_DIR


def test_generate_parallel_accepts_cache_dir():
    """_generate_parallel 必须能被指定缓存目录，否则隔离无从实现。"""
    import inspect
    assert "raw_dir" in inspect.signature(build_dict._generate_parallel).parameters


def test_tail_gap_words_landed_in_dict():
    """尾缺口那批屈折形已进词库。

    这些词是「单词请求触发词元归一化」的受害者：问 zustände 答 Zustand，
    原先按 wort != 请求词直接丢，连丢 3 轮后记成「AI 从未返回」。
    """
    for w in ("zustände", "waldbrände", "tatsachen", "zwischenrufe", "symbole"):
        entry = CORE_VOCAB_DB.get(w)
        assert entry, f"{w} 应已补进词库"
        assert entry[4], f"{w} 的中文释义不该为空"


def test_nouns_always_carry_plural():
    """名词必须带复数形，不允许为补缺口而伪造/留空。

    校验器拒收 plural 为 null 的名词，这条不变量在整个 ext 上成立；
    放宽它会让「补上了」和「补了个残条」看起来一样。
    """
    bad = [w for w, t in CORE_VOCAB_DB.items()
           if t[1] == "NOUN" and not t[3]]
    assert not bad, f"这些名词缺复数形: {bad[:20]}"
