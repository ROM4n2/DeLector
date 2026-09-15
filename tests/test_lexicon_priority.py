# -*- coding: utf-8 -*-
"""词汇主干 lexicon 的契约测试（ADR-0012 / R3）。

锁死四件事，任何一件被改回去都必须让本文件变红：
  1. 分片注册表恰含 {ai, manual, official} 三片；
  2. 主干 LEXICON 是三片并集（无遗漏），且高优先来源覆盖同 lemma；
  3. PROVENANCE 如实记录「同 lemma 出现在哪些分片」（运行期旁路，不进存储）；
  4. view() 能按来源过滤出子视图（「仅官方精选」的底座）。

为什么必须钉住优先级：AI 与官方对同一 lemma 的 cefr/释义不一致
（如 zurzeit AI=B1↔官方=A1）。若合并顺序被无意反转，症状是静默的 ——
难度标注与考纲词集会悄悄错档，不会有任何报错，只有本文件能拦。
"""

import inspect

from delector.core import lexicon
from delector.core.lexicon import (
    FRAGMENTS,
    LEXICON,
    PROVENANCE,
    SOURCE_PRIORITY,
    merge_fragments,
    sources_of,
    view,
)
from delector.data.core_dict import CORE_VOCAB_DB, CORE_VOCAB_EXT, CORE_VOCAB_MANUAL
from delector.data.official_vocab import OFFICIAL_VOCAB

# ── 1. 分片注册表 ──────────────────────────────────────────────────────────


def test_fragments_has_exactly_three_sources():
    """分片注册表键必须恰为 {ai, manual, official}。"""
    assert set(FRAGMENTS) == {"ai", "manual", "official"}


def test_priority_order_is_low_to_high():
    """SOURCE_PRIORITY 自低到高：ai -> manual -> official（后者覆盖前者）。"""
    assert tuple(SOURCE_PRIORITY) == ("ai", "manual", "official")


# ── 2. 并集无遗漏 ──────────────────────────────────────────────────────────


def test_lexicon_is_union_of_all_fragments():
    """LEXICON 的 key 集合 == 三片 key 的并集（不丢任何 lemma），且条数钉死。

    仅断言集合相等检测力偏弱：``len(LEXICON)`` 精确到条，能抓住「并集成立，
    但补丁顺手多塞/漏塞了 key」这类肉眼看不出的静默漂移。
    """
    union = set(FRAGMENTS["ai"]) | set(FRAGMENTS["manual"]) | set(FRAGMENTS["official"])
    assert set(LEXICON) == union
    assert len(LEXICON) == len(union)
    assert len(LEXICON) == 4763


def test_lexicon_takes_value_from_highest_priority_hit():
    """抽样：每个 lemma 的 LEXICON 取值 == 命中它的最高优先分片的取值。

    「无遗漏 + 覆盖语义」的联合不变式 —— 逐条比对取值能拦住「并集对、
    但合并时选错了来源（取了低优先值）」这类只有比较值才看得出的错误，
    只断言 key 集合是抓不到的。
    """

    def highest_priority_value(lemma: str) -> tuple:
        return next(
            FRAGMENTS[source][lemma]
            for source in reversed(SOURCE_PRIORITY)
            if lemma in FRAGMENTS[source]
        )

    # 覆盖多片冲突（zurzeit/abfahren）与单片/普通 lemma
    for lemma in ("zurzeit", "abfahren", "gehen", "haus", "abflug", "tag"):
        assert lemma in LEXICON, lemma
        assert LEXICON[lemma] == highest_priority_value(lemma), lemma


# ── 3. 优先级：官方覆盖同 lemma ───────────────────────────────────────────


def test_official_overrides_ai_for_same_lemma():
    """zurzeit 同时存在于 ai(B1) 与 official(A1)：主干必须取官方 A1 值。"""
    assert "zurzeit" in CORE_VOCAB_EXT and "zurzeit" in OFFICIAL_VOCAB
    assert LEXICON["zurzeit"] == OFFICIAL_VOCAB["zurzeit"]
    assert LEXICON["zurzeit"][0] == "A1"
    # 明确不等于 AI 的低优先值，证明「不是碰巧相等」
    assert LEXICON["zurzeit"] != CORE_VOCAB_EXT["zurzeit"]


def test_official_overrides_manual_for_same_lemma():
    """abfahren 同现于 manual(A2) 与 official(A1)：主干必须取官方 A1 值。"""
    assert "abfahren" in CORE_VOCAB_MANUAL and "abfahren" in OFFICIAL_VOCAB
    assert LEXICON["abfahren"] == OFFICIAL_VOCAB["abfahren"]
    assert LEXICON["abfahren"][0] == "A1"
    # 明确不等于手编的低优先值，证明「不是碰巧相等」
    assert LEXICON["abfahren"] != CORE_VOCAB_MANUAL["abfahren"]


# ── 4. provenance 正确性 ──────────────────────────────────────────────────


def test_provenance_multi_source_lemma():
    """zurzeit 同现于 official 与 ai：sources_of 恰为两者。"""
    assert sources_of("zurzeit") == frozenset({"official", "ai"})


def test_provenance_single_source_lemma():
    """abflug 只现于 official：sources_of 恰为 {official}。"""
    assert "abflug" in OFFICIAL_VOCAB
    assert "abflug" not in CORE_VOCAB_MANUAL and "abflug" not in CORE_VOCAB_EXT
    assert sources_of("abflug") == frozenset({"official"})


def test_provenance_unknown_lemma_is_empty():
    """未登记 lemma 的 provenance 为空集（不抛异常）。"""
    assert sources_of("zzzznichtimlexikon") == frozenset()


def test_provenance_values_are_frozensets():
    """PROVENANCE 每条值都应是 frozenset[str]（旁路只读结构）。"""
    assert PROVENANCE
    assert all(isinstance(v, frozenset) for v in PROVENANCE.values())


# ── 5. view 按来源过滤 ────────────────────────────────────────────────────


def test_view_official_equals_official_vocab():
    """view({'official'}) 逐字等于 OFFICIAL_VOCAB（「仅官方精选」底座）。"""
    assert view({"official"}) == OFFICIAL_VOCAB


def test_view_none_equals_lexicon():
    """view(None) / view() 覆盖全部来源：键集 == 三片并集，逐条值 == LEXICON。

    原写法 ``view() == LEXICON`` 是自等断言 —— ``view(None)`` 内部就是
    ``dict(LEXICON)``，恒真、检测力为零。改为独立推导键集（三片并集）与逐条对值，
    这样 view 的实现若换成「只取某一片」或「复制时串了值」都会变红。
    """
    union = set(FRAGMENTS["ai"]) | set(FRAGMENTS["manual"]) | set(FRAGMENTS["official"])
    for sub in (view(), view(None)):
        assert sub  # 非空
        assert set(sub) == union
        assert len(sub) == len(LEXICON)
        assert all(sub[lemma] == LEXICON[lemma] for lemma in LEXICON)


def test_view_excludes_only_official_lemmas():
    """view({'manual','ai'}) 不含「只在 official 出现」的 lemma。"""
    only_official = (
        set(FRAGMENTS["official"]) - set(FRAGMENTS["ai"]) - set(FRAGMENTS["manual"])
    )
    sub = view({"manual", "ai"})
    assert not (set(sub) & only_official)
    assert "abflug" not in sub  # abflug 只在 official


# ── 6. 加载期零副作用（纯数据 · 无 IO）────────────────────────────────────


def test_fragments_are_plain_data():
    """分片是纯数据结构：dict -> dict -> 5 元组。"""
    for name, frag in FRAGMENTS.items():
        assert isinstance(frag, dict), name
        for lemma, entry in frag.items():
            assert isinstance(lemma, str)
            assert isinstance(entry, tuple) and len(entry) == 5


def test_module_source_has_no_io():
    """源码静态守卫：lexicon 加载路径不得出现 open()/sqlite/网络调用。"""
    src = inspect.getsource(lexicon)
    for banned in ("open(", "sqlite3", "urllib", "requests", "socket."):
        assert banned not in src, f"lexicon 加载路径不得含 {banned!r}"


# ── 7. 合并优先级纯函数（中间层 manual > ai 的关键守卫）─────────────────────


def _fragments(**by_source: dict) -> dict:
    """构造完整的三源分片字典（未给出的来源补空片），与真实 FRAGMENTS 同形。

    ``merge_fragments`` 严格遍历 ``priority`` 的每个来源（与原内联推导式一致，
    真实 FRAGMENTS 三源齐备），故手工分片也须补齐三键。
    """
    return {source: by_source.get(source, {}) for source in SOURCE_PRIORITY}


def test_merge_fragments_manual_overrides_ai():
    """同 lemma 命中 ai 与 manual 且值不同 -> 取 manual（中间层优先级）。

    真实分片里 ai 与 manual 恰好没有同 lemma 冲突，所以 #4/#5 只覆盖了
    ``official`` 对 ai / manual 的覆盖；本用例是唯一能拦住
    ``SOURCE_PRIORITY`` 被误写成 ``("manual", "ai", "official")``
    （= ai 覆盖 manual，语义反转）的地方。
    """
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", None, None, "AI 版")},
        manual={"wort": ("A2", "NOUN", None, None, "手编版")},
    )
    merged = merge_fragments(fragments, SOURCE_PRIORITY)
    assert merged["wort"] == fragments["manual"]["wort"]
    assert merged["wort"] != fragments["ai"]["wort"]


def test_merge_fragments_official_overrides_manual():
    """同 lemma 命中 manual 与 official 且值不同 -> 取 official。"""
    fragments = _fragments(
        manual={"wort": ("A2", "NOUN", None, None, "手编版")},
        official={"wort": ("A1", "NOUN", None, None, "官方版")},
    )
    merged = merge_fragments(fragments, SOURCE_PRIORITY)
    assert merged["wort"] == fragments["official"]["wort"]
    assert merged["wort"] != fragments["manual"]["wort"]


def test_merge_fragments_official_overrides_ai():
    """同 lemma 命中 ai 与 official 且值不同 -> 取 official。"""
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", None, None, "AI 版")},
        official={"wort": ("A1", "NOUN", None, None, "官方版")},
    )
    merged = merge_fragments(fragments, SOURCE_PRIORITY)
    assert merged["wort"] == fragments["official"]["wort"]
    assert merged["wort"] != fragments["ai"]["wort"]


def test_source_priority_index_relations():
    """SOURCE_PRIORITY 的索引关系：ai < manual < official（后者覆盖前者）。

    不写死整条元组（那是顺序全等的强断言），而是断言相对次序 —— 只要
    manual 被排到 ai 之前（语义反转），本断言即变红。
    """
    assert SOURCE_PRIORITY.index("manual") > SOURCE_PRIORITY.index("ai")
    assert SOURCE_PRIORITY.index("official") == max(
        SOURCE_PRIORITY.index(source) for source in ("ai", "manual", "official")
    )


def test_source_priority_covers_all_fragments():
    """优先级元组必须与分片注册表键集一致：既不漏来源也不含未知来源。"""
    assert set(SOURCE_PRIORITY) == set(FRAGMENTS)


# ── 8. core_dict 分片计数回归守卫（精确到条）──────────────────────────────


def test_core_dict_shard_sizes_are_frozen():
    """CORE_VOCAB_DB 及相关分片的精确条数：合并顺序/分片被误改会静默漂移。

    DB 由 ``{**EXT, **MANUAL}`` 合并（base 手编优先）：443 + 3969 - 1 = 4411，
    说明恰有 1 个 lemma 同时落在 EXT 与 MANUAL（合并冲突面只有这一处）。
    """
    assert len(CORE_VOCAB_MANUAL) == 443
    assert len(CORE_VOCAB_EXT) == 3969
    assert len(CORE_VOCAB_DB) == 4411
