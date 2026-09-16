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

# 富字段应恰含这四个键（ADR-0013 schema）。
_RICH_KEYS = {"ipa", "example_de", "example_zh", "topic"}


# ── 1. RICH = 三分片 lemma 并集（无遗漏）──────────────────────────────────


def test_rich_fragments_registers_three_shards():
    """富字段分片注册表恰含 A1/A2/B1 三片（与常量逐字同源）。"""
    assert set(RICH_FRAGMENTS) == {"official_rich_a1", "official_rich_a2", "official_rich_b1"}
    assert RICH_FRAGMENTS["official_rich_a1"] is OFFICIAL_RICH_A1
    assert RICH_FRAGMENTS["official_rich_a2"] is OFFICIAL_RICH_A2
    assert RICH_FRAGMENTS["official_rich_b1"] is OFFICIAL_RICH_B1


def test_rich_is_union_of_all_shards():
    """``RICH`` 的 key 集合 == 三片并集（集合实算，不写死猜测数）。"""
    union = set(OFFICIAL_RICH_A1) | set(OFFICIAL_RICH_A2) | set(OFFICIAL_RICH_B1)
    assert set(RICH) == union
    assert len(RICH) == len(union)


# ── 2. 命中 lemma 的 schema ────────────────────────────────────────────────


def test_rich_of_returns_entry_with_exact_schema():
    """``rich_of('abfahrt')`` 是 dict 且键集恰为四富字段。"""
    entry = rich_of("abfahrt")
    assert isinstance(entry, dict)
    assert set(entry) == _RICH_KEYS


# ── 3. 覆盖优先级：A2/B1 覆盖 A1 ───────────────────────────────────────────


def test_rich_priority_a2b1_overrides_a1():
    """A1 与 A2/B1 跨档重叠时，``RICH`` 取 A2/B1 值（非 A1）。"""
    overlap_b1 = set(OFFICIAL_RICH_A1) & set(OFFICIAL_RICH_B1)
    assert overlap_b1, "预期存在 A1 与 B1 的跨档重叠 lemma"

    # 全量不变式：所有「A1 ∩ (A2∪B1)」重叠 lemma，RICH 取值来自 A2/B1（更高优先）。
    for lemma in set(OFFICIAL_RICH_A1) & (set(OFFICIAL_RICH_A2) | set(OFFICIAL_RICH_B1)):
        expected = (
            OFFICIAL_RICH_B1[lemma]
            if lemma in OFFICIAL_RICH_B1
            else OFFICIAL_RICH_A2[lemma]
        )
        assert RICH[lemma] == expected, lemma

    # 可观测性：找一条 A1 与 A2/B1 取值确实不同的重叠，证明覆盖真实生效，非碰巧相等。
    observable = None
    for lemma in overlap_b1:
        higher = OFFICIAL_RICH_B1[lemma]
        if OFFICIAL_RICH_A1[lemma] != higher:
            observable = lemma
            break
    if observable is not None:
        assert RICH[observable] == OFFICIAL_RICH_B1[observable]
        assert RICH[observable] != OFFICIAL_RICH_A1[observable]


# ── 4. 未知 lemma ──────────────────────────────────────────────────────────


def test_rich_of_unknown_lemma_is_none():
    """未登记 lemma 返回 ``None``（不抛错）。"""
    assert rich_of("不存在的词") is None
    assert rich_of("zzzznichtimrich") is None


# ── 5. IPA 无 tie-bar 残留 ─────────────────────────────────────────────────


def test_no_tie_bar_left_in_ipa():
    """遍历 ``RICH`` 的 ipa，``\\u0361`` 计数为 0（ADR-0013 §4-4）。"""
    total = sum(entry["ipa"].count("\u0361") for entry in RICH.values())
    assert total == 0


# ── 6. 纯内存 · 确定性 ─────────────────────────────────────────────────────


def test_rich_of_is_deterministic():
    """同一输入两次调用结果相等（纯只读，无副作用）。"""
    assert rich_of("abfahrt") == rich_of("abfahrt")
    assert rich_of("abfahrt") == RICH["abfahrt"]
