# -*- coding: utf-8 -*-
"""词汇主干 lexicon 的契约测试（ADR-0012 / R3 + R5-v2 字段级合并）。

锁死五件事，任何一件被改回去都必须让本文件变红：
  1. 分片注册表恰含 {ai, manual, official} 三片；
  2. 主干 LEXICON 是三片并集（无遗漏），且**逐字段**按 FIELD_PRIORITY 取来源值；
  3. PROVENANCE 如实记录「同 lemma 出现在哪些分片」（运行期旁路，不进存储）；
  4. view() 能按来源过滤出子视图（「仅官方精选」的底座）；
  5. CORE_VOCAB_DB 与 LEXICON 逐字相等（单真值，杜绝两份合成分叉）。

为什么必须钉住字段级优先级：官方 Wortliste 的 cefr 权威，但 plural 列约 30% 是占位 '-'
（haus 手编 '-..er' → 官方 '-ä'、schule '-n' → '-'、arzt '-..e' → 'Ä'）。若合并被退回
「官方整条覆盖」，手编质量会被静默劣化、且不会有任何报错，只有本文件能拦。
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
from delector.data.lexicon_merge import FIELD_ORDER, FIELD_PRIORITY
from delector.data.official_vocab import OFFICIAL_VOCAB

# 字段 -> 5 元组下标（FIELD_ORDER 与存储 schema 逐位对应）。
_FIELD_POSITION = {field: i for i, field in enumerate(FIELD_ORDER)}

# ── 1. 分片注册表 ──────────────────────────────────────────────────────────


def test_fragments_has_exactly_three_sources():
    """分片注册表键必须恰为 {ai, manual, official}。"""
    assert set(FRAGMENTS) == {"ai", "manual", "official"}


def test_priority_order_is_low_to_high():
    """SOURCE_PRIORITY 自低到高：ai -> manual -> official（保留供 provenance/子视图）。"""
    assert tuple(SOURCE_PRIORITY) == ("ai", "manual", "official")


def test_field_priority_is_field_level():
    """FIELD_PRIORITY 逐字段规则：cefr 官方优先；pos/gender/plural/def_zh 手编优先。"""
    assert FIELD_PRIORITY["cefr"] == ("official", "manual", "ai")
    for field in ("pos", "gender", "plural", "def_zh"):
        assert FIELD_PRIORITY[field] == ("manual", "official", "ai"), field
    assert set(FIELD_PRIORITY) == set(FIELD_ORDER)


# ── 2. 并集无遗漏 + 字段级取值 ─────────────────────────────────────────────


def test_lexicon_is_union_of_all_fragments():
    """LEXICON 的 key 集合 == 三片 key 的并集（不丢任何 lemma），且条数钉死。

    仅断言集合相等检测力偏弱：``len(LEXICON)`` 精确到条，能抓住「并集成立，
    但补丁顺手多塞/漏塞了 key」这类肉眼看不出的静默漂移。
    """
    union = set(FRAGMENTS["ai"]) | set(FRAGMENTS["manual"]) | set(FRAGMENTS["official"])
    assert set(LEXICON) == union
    assert len(LEXICON) == len(union)
    assert len(LEXICON) == 4763


def test_lexicon_takes_each_field_from_designated_source():
    """抽样：每个 lemma 的每个字段 == 该字段优先级里第一个含该 lemma 的来源值。

    「无遗漏 + 字段级取值」的联合不变式 —— **逐字段**比对取值能拦住「并集对、
    但某字段选错了来源（取了低优先值）」这类只有比较值才看得出的错误，
    只断言 key 集合是抓不到的。
    """

    def expected_field(lemma: str, field: str):
        for source in FIELD_PRIORITY[field]:
            fragment = FRAGMENTS[source]
            if lemma in fragment:
                return fragment[lemma][_FIELD_POSITION[field]]
        raise AssertionError(f"{lemma}.{field} 在 FIELD_PRIORITY 里无任何来源")

    # 覆盖多片冲突（zurzeit/abfahren）与单片/普通 lemma
    for lemma in ("zurzeit", "abfahren", "gehen", "haus", "abflug", "tag"):
        assert lemma in LEXICON, lemma
        for field in FIELD_ORDER:
            assert LEXICON[lemma][_FIELD_POSITION[field]] == expected_field(lemma, field), (
                lemma,
                field,
            )


# ── 3. 字段级优先级：cefr 官方权威 / 富字段手编质量 ────────────────────────


def test_cefr_prefers_official_over_ai_for_same_lemma():
    """zurzeit 同现 ai(B1) 与 official(A1)：cefr 取官方 A1。"""
    assert "zurzeit" in CORE_VOCAB_EXT and "zurzeit" in OFFICIAL_VOCAB
    assert LEXICON["zurzeit"][0] == OFFICIAL_VOCAB["zurzeit"][0] == "A1"
    # 明确不等于 AI 的低优先值，证明「不是碰巧相等」
    assert LEXICON["zurzeit"][0] != CORE_VOCAB_EXT["zurzeit"][0]


def test_rich_fields_prefer_manual_over_official_for_same_lemma():
    """abfahren 同现 manual(A2) 与 official(A1)：cefr 取官方，富字段取手编。

    这是「字段级」与旧「整条覆盖」的分界点：若退回整条官方覆盖，
    ``LEXICON['abfahren']`` 会等于官方整条，下面的释义断言立即变红。
    """
    assert "abfahren" in CORE_VOCAB_MANUAL and "abfahren" in OFFICIAL_VOCAB
    assert LEXICON["abfahren"][0] == OFFICIAL_VOCAB["abfahren"][0] == "A1"  # cefr 官方权威
    assert LEXICON["abfahren"][_FIELD_POSITION["def_zh"]] == CORE_VOCAB_MANUAL["abfahren"][4]
    assert LEXICON["abfahren"][_FIELD_POSITION["def_zh"]] != OFFICIAL_VOCAB["abfahren"][4]


def test_real_conflict_plural_kept_from_manual():
    """真实冲突样例（一手实测）：官方 plural 列约 30% 是占位 '-'，字段级合并后
    haus/schule/arzt 的 plural 保留手编值，cefr 仍取官方权威。"""
    assert LEXICON["haus"][0] == "A1"
    assert LEXICON["haus"][3] == "-..er"  # 手编 '-..er' 胜官方占位 '-ä'
    assert LEXICON["haus"][3] != OFFICIAL_VOCAB["haus"][3]
    assert LEXICON["schule"][3] == "-n"  # 手编 '-n' 胜官方占位 '-'
    assert LEXICON["schule"][3] != OFFICIAL_VOCAB["schule"][3]
    assert LEXICON["arzt"][3] == "-..e"  # 手编 '-..e' 胜官方 'Ä'
    assert LEXICON["arzt"][3] != OFFICIAL_VOCAB["arzt"][3]


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


def test_provenance_matches_fragment_membership():
    """provenance 如实：lemma 出现在哪几片，集合就含哪几个来源名（抽样逐片核对）。"""
    for lemma in ("zurzeit", "abfahren", "haus", "abflug"):
        expected = frozenset(source for source in SOURCE_PRIORITY if lemma in FRAGMENTS[source])
        assert PROVENANCE[lemma] == expected, lemma


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


# ── 7. 字段级合并纯函数（cefr 官方 / 富字段手编 的关键守卫）─────────────────


def _fragments(**by_source: dict) -> dict:
    """构造完整的三源分片字典（未给出的来源补空片），与真实 FRAGMENTS 同形。

    ``merge_fragments`` 对每个字段遍历 ``field_priority`` 里列出的来源（真实
    FRAGMENTS 三源齐备），故手工分片也须补齐三键。
    """
    return {source: by_source.get(source, {}) for source in SOURCE_PRIORITY}


def test_merge_fragments_cefr_prefers_official():
    """同 lemma 三源齐备：cefr 取 official（即使 manual/ai 值不同）。"""
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", None, None, "AI 释义")},
        manual={"wort": ("A2", "NOUN", None, None, "手编释义")},
        official={"wort": ("A1", "NOUN", None, None, "官方释义")},
    )
    merged = merge_fragments(fragments)
    assert merged["wort"][0] == "A1"
    assert merged["wort"][0] != fragments["ai"]["wort"][0]


def test_merge_fragments_rich_fields_prefer_manual():
    """同 lemma 三源齐备：富字段（pos/gender/plural/def_zh）取 manual。"""
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", "Masc", "-e", "AI 释义")},
        manual={"wort": ("A2", "NOUN", "Masc", "-..er", "手编释义")},
        official={"wort": ("A1", "NOUN", "Masc", "-ä", "官方释义")},
    )
    merged = merge_fragments(fragments)
    # cefr 官方、其余手编 —— 同一 lemma 的不同字段各取不同来源（字段级铁证）
    assert merged["wort"] == ("A1", "NOUN", "Masc", "-..er", "手编释义")


def test_merge_fragments_rich_fields_fall_back_to_official_without_manual():
    """手编缺该 lemma 时，富字段回退到 official。"""
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", "Masc", "-e", "AI 释义")},
        official={"wort": ("A1", "NOUN", "Masc", "-ä", "官方释义")},
    )
    merged = merge_fragments(fragments)
    assert merged["wort"] == ("A1", "NOUN", "Masc", "-ä", "官方释义")


def test_merge_fragments_falls_back_to_ai_when_only_source():
    """仅 AI 含该 lemma 时，全字段回退到 AI。"""
    fragments = _fragments(ai={"wort": ("B1", "NOUN", "Masc", "-e", "AI 释义")})
    merged = merge_fragments(fragments)
    assert merged["wort"] == ("B1", "NOUN", "Masc", "-e", "AI 释义")


def test_merge_fragments_accepts_custom_field_priority():
    """可传自定义 field_priority（可单测接缝）：反转 cefr 优先级应改变结果。"""
    fragments = _fragments(
        ai={"wort": ("B1", "NOUN", None, None, "AI")},
        official={"wort": ("A1", "NOUN", None, None, "官方")},
    )
    custom = {**FIELD_PRIORITY, "cefr": ("ai", "official")}
    assert merge_fragments(fragments, custom)["wort"][0] == "B1"


def test_source_priority_index_relations():
    """SOURCE_PRIORITY 的索引关系：ai < manual < official（供 provenance/子视图）。

    不写死整条元组（那是顺序全等的强断言），而是断言相对次序。
    """
    assert SOURCE_PRIORITY.index("manual") > SOURCE_PRIORITY.index("ai")
    assert SOURCE_PRIORITY.index("official") == max(
        SOURCE_PRIORITY.index(source) for source in ("ai", "manual", "official")
    )


def test_source_priority_covers_all_fragments():
    """优先级元组必须与分片注册表键集一致：既不漏来源也不含未知来源。"""
    assert set(SOURCE_PRIORITY) == set(FRAGMENTS)


# ── 8. core_dict 分片计数 + 主干单真值守卫 ────────────────────────────────


def test_core_dict_shard_sizes_are_frozen():
    """CORE_VOCAB_DB 及相关分片的精确条数：合并顺序/分片被误改会静默漂移。

    字段级合并三分片：手编 443 + AI 3969 + 官方 2732，去重后并集 = 4763；
    ``CORE_VOCAB_DB`` 与主干 ``LEXICON`` 条数恒等（单真值）。
    """
    assert len(CORE_VOCAB_MANUAL) == 443
    assert len(CORE_VOCAB_EXT) == 3969
    assert len(OFFICIAL_VOCAB) == 2732
    assert len(CORE_VOCAB_DB) == len(LEXICON)


def test_core_dict_db_equals_lexicon():
    """单真值守卫：CORE_VOCAB_DB 与主干 LEXICON 逐字相等（含键集与取值）。

    ``CORE_VOCAB_DB`` 只是主干的兼容入口/等价视图，两份常量不得各自成为真值
    （ADR-0012）。逐条比对取值能拦住「键集对、但某字段取错来源」这类只有比取值
    才看得出的错误；额外断言冲突 lemma 双方都取官方 cefr，钉住字段级语义未被反转。
    """
    assert set(CORE_VOCAB_DB) == set(LEXICON)
    assert CORE_VOCAB_DB == LEXICON
    # 抽样冲突 lemma：两常量的 cefr 都必须取官方值（证明「不是碰巧相等」）。
    for lemma in ("zurzeit", "abfahren"):
        assert CORE_VOCAB_DB[lemma][0] == LEXICON[lemma][0] == OFFICIAL_VOCAB[lemma][0], lemma
