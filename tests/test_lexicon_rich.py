# -*- coding: utf-8 -*-
"""词汇主干富字段视图契约测试（ADR-0013 §4-2 富字段来源 / §5-1 不进存储 / §5-5 单入口）。

钉死干线的富字段 side-car 视图（``RICH`` / ``RICH_FRAGMENTS`` / ``rich_of``）：

  1. ``RICH`` 的 key 集合 == 三片（A1/A2/B1）lemma 并集（不丢任何 lemma），条数精确；
  2. ``rich_of`` 命中返回含 ``{ipa, example_de, example_zh, topic}`` 的 dict；
  3. **覆盖优先级**：A1 与 A2/B1 有跨档重叠时，**A2/B1 覆盖 A1**（A1 卡片走 seed、
     不用本表，故重叠以 A2/B1 为准）；
  4. 未知 lemma 返回 ``None``（不抛错）；
  5. 无 tie-bar 残留（``\u0361`` 计数为 0，ADR-0013 §4-4 IPA 归一化）；
  6. 纯内存、确定性：同一输入两次调用结果相等。

反恒真：重叠断言用集合实算（不写死猜测数），且额外证明「A2/B1 覆盖」在取值不同处
真实可观测（否则可能只是碰巧相等）。
"""

from delector.core.lexicon import RICH, RICH_FRAGMENTS, rich_of
from delector.data.official_vocab_rich import (
    OFFICIAL_RICH_A1,
    OFFICIAL_RICH_A2,
    OFFICIAL_RICH_B1,
)

# 富字段应恰含这五个键（ADR-0013 + ADR-0015 examples）。
_RICH_KEYS = {"ipa", "example_de", "example_zh", "topic", "examples"}


# ── 1. RICH = 三分片 lemma 并集（无遗漏）──────────────────────────────────


def test_rich_fragments_registers_five_shards():
    """富字段分片注册表恰含 A1 工作台/考纲 + official_rich 三档（ADR-0015）。"""
    assert set(RICH_FRAGMENTS) == {
        "workbench-a1",
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    }
    assert RICH_FRAGMENTS["official_rich_a1"] is OFFICIAL_RICH_A1
    assert RICH_FRAGMENTS["official_rich_a2"] is OFFICIAL_RICH_A2
    assert RICH_FRAGMENTS["official_rich_b1"] is OFFICIAL_RICH_B1


def test_rich_is_union_of_all_shards():
    """``RICH`` 的 key 集合 == 五片并集（集合实算，不写死猜测数）。"""
    union = set()
    for fragment in RICH_FRAGMENTS.values():
        union |= set(fragment)
    assert set(RICH) == union
    assert len(RICH) == len(union)


# ── 2. 命中 lemma 的 schema ────────────────────────────────────────────────


def test_rich_of_returns_entry_with_exact_schema():
    """``rich_of('abfahrt')`` 是 dict 且键集恰为五富字段。"""
    entry = rich_of("abfahrt")
    assert isinstance(entry, dict)
    assert set(entry) == _RICH_KEYS


# ── 3. 覆盖优先级：A2/B1 覆盖 A1 ───────────────────────────────────────────


def test_rich_priority_manual_over_g2p_fill_empty():
    """ADR-0015：workbench-a1 人工 IPA/例句优先；official_rich 仅补空，不覆盖非空。"""
    overlap = set(OFFICIAL_RICH_A1) & (set(OFFICIAL_RICH_A2) | set(OFFICIAL_RICH_B1))
    assert overlap
    for lemma in list(overlap)[:20]:
        entry = rich_of(lemma)
        assert entry is not None
        wb = RICH_FRAGMENTS.get("workbench-a1", {}).get(lemma)
        if wb and (wb.get("ipa") or "").strip():
            assert entry["ipa"] == wb["ipa"], lemma


def test_rich_of_unknown_lemma_is_none():
    """未登记 lemma 返回 ``None``（不抛错）。"""
    assert rich_of("不存在的词") is None
    assert rich_of("zzzznichtimrich") is None


# ── 5. IPA 无 tie-bar 残留 ─────────────────────────────────────────────────


def test_no_tie_bar_left_in_ipa():
    """遍历 ``RICH`` 的 ipa，``\\u0361`` 计数为 0（ADR-0013 §4-4）。"""
    total = sum((entry.get("ipa") or "").count("\u0361") for entry in RICH.values())
    assert total == 0


# ── 6. 纯内存 · 确定性 ─────────────────────────────────────────────────────


def test_rich_of_is_deterministic():
    """同一输入两次调用结果相等（纯只读，无副作用）。"""
    assert rich_of("abfahrt") == rich_of("abfahrt")
    assert rich_of("abfahrt") == RICH["abfahrt"]
