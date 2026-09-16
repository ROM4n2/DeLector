# -*- coding: utf-8 -*-
"""字段级词汇合并的共享纯函数（ADR-0012 主干单真值 / R5-v2）。

**为什么字段级而非整条覆盖**：官方 Goethe Wortliste 是权威来源，但只在 ``cefr`` 一列
可堪依赖；其富字段（``pos`` / ``gender`` / ``plural`` / ``def_zh``）质量参差 —— 尤其
``plural`` 列约 30% 是占位 ``-``，直接用官方整条覆盖手编会**劣化**（一手实测：
``haus`` 手编 ``-..er`` → 官方 ``-ä``、``schule`` 手编 ``-n`` → 官方 ``-``、
``arzt`` 手编 ``-..e`` → 官方 ``Ä``、``apfel`` 手编 ``-..`` → 官方 ``Ä``）。
故按字段分别取权威来源：「等级用官方权威，富字段保留人工质量」。

**字段级优先级**（``FIELD_PRIORITY``）：
    - ``cefr``：``official > manual > ai`` —— 难度等级以官方考纲为权威。
    - ``pos`` / ``gender`` / ``plural`` / ``def_zh``：``manual > official > ai``
      —— 富字段保留人工质量，官方仅补手编缺失处。

**纯函数 · 零内部依赖**：本模块只依赖 ``typing``，不 import 任何 ``delector`` 内部模块。
这使它可被 ``delector.core.lexicon``（权威主干）与 ``delector.data.core_dict``
（兼容等价视图）**共用同一份合并实现**，既避免循环依赖，也杜绝「两处各写一份合并」
导致的双真值漂移（单真值守卫 ``CORE_VOCAB_DB == LEXICON`` 即钉死此点）。
"""

from typing import Dict, Iterator, Mapping, Sequence, Tuple

# 5 元组字段顺序：与存储 schema（ADR-0011 #6 冻结）逐位对应，勿改。
FIELD_ORDER: Tuple[str, ...] = ("cefr", "pos", "gender", "plural", "def_zh")

# 字段级优先级（每字段列出「从高到低」的来源名）。
#   - cefr：官方 > 手编 > AI（难度等级以官方考纲为权威）；
#   - 富字段：手编 > 官方 > AI（官方 plural 列约 30% 是占位 '-'，覆盖手编会劣化）。
FIELD_PRIORITY: Dict[str, tuple] = {
    "cefr": ("official", "manual", "ai"),
    "pos": ("manual", "official", "ai"),
    "gender": ("manual", "official", "ai"),
    "plural": ("manual", "official", "ai"),
    "def_zh": ("manual", "official", "ai"),
}


def _iter_lemmas(fragments: Mapping[str, Mapping[str, tuple]]) -> Iterator[str]:
    """按分片注册顺序产出全部 lemma（首次出现即产出，去重、保序）。

    保序是刻意的：合并结果的 key 插入顺序 = 各分片首次出现顺序，与旧逐片 ``update``
    推导式一致，从而 ``merge_fragments`` 的产物逐字稳定（不依赖 set 的哈希顺序）。
    """
    seen = set()
    for fragment in fragments.values():
        for lemma in fragment:
            if lemma not in seen:
                seen.add(lemma)
                yield lemma


def merge_fragments(
    fragments: Mapping[str, Mapping[str, tuple]],
    field_priority: Mapping[str, Sequence[str]] = FIELD_PRIORITY,
) -> Dict[str, tuple]:
    """逐字段合并：对每个 lemma 的每个字段，取 ``field_priority[字段]`` 中
    第一个含该 lemma 的来源在该字段位置的值。

    纯函数、零副作用：只读传入的 ``fragments``，返回全新 ``dict``；key = 三分片
    lemma 并集，value = 5 元组（按 ``FIELD_ORDER`` 逐位取来源值拼回）。

    单独抽成共享纯函数，是为让「主干 LEXICON」与「core_dict 兼容视图 CORE_VOCAB_DB」
    走**同一段**合并逻辑 —— 否则两份常量各写一份合并，稍有不慎就会静默分叉成双真值
    （ADR-0012 明令单真值）。
    """
    merged: Dict[str, tuple] = {}
    for lemma in _iter_lemmas(fragments):
        values = []
        for position, field in enumerate(FIELD_ORDER):
            field_value = None
            for source in field_priority[field]:
                fragment = fragments.get(source)
                if fragment is not None and lemma in fragment:
                    field_value = fragment[lemma][position]
                    break
            values.append(field_value)
        merged[lemma] = tuple(values)
    return merged


def provenance_of(
    fragments: Mapping[str, Mapping[str, tuple]],
) -> Dict[str, frozenset]:
    """``lemma -> 含该 lemma 的来源集合``（``frozenset``）。

    运行期旁路：记录每个 lemma 由哪些来源贡献，仅供加载后查询「仅官方精选」等
    来源感知视图；它是内存中的 ``frozenset``，**不进存储 schema**（5 元组冻结不变）。
    纯函数、零副作用（只读传入的 ``fragments``）。
    """
    contributors: Dict[str, set] = {}
    for source, fragment in fragments.items():
        for lemma in fragment:
            contributors.setdefault(lemma, set()).add(source)
    return {lemma: frozenset(sources) for lemma, sources in contributors.items()}
