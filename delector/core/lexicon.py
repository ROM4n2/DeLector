# -*- coding: utf-8 -*-
"""词汇主干加载器（ADR-0012 / R3）：分片注册表 + provenance + 来源优先级。

**来源分层**（分片 = 模块边界表达来源，不引入 schema 字段，守 5 元组冻结红线）：
    - ``ai``       <- ``delector.data.core_dict_ext.CORE_VOCAB_EXT``   （AI 批量生成）
    - ``manual``   <- ``delector.data.core_dict.CORE_VOCAB_MANUAL``    （手编核心）
    - ``official`` <- ``delector.data.official_vocab.OFFICIAL_VOCAB``  （官方歌德词表）

**优先级语义**（由合并顺序表达，见 ``SOURCE_PRIORITY``）：
    低 -> 高 = ``ai < manual < official``；同 lemma 冲突时高优先来源覆盖低优先，
    即官方 > 手编 > AI。这样 AI 与官方对同一 lemma 的 cefr/释义不一致时，
    难度标注与考纲词集以官方权威为准。

**provenance 是运行期旁路**：``PROVENANCE`` 记录每个 lemma 由哪些来源贡献，
仅供加载后查询「仅官方精选」等来源感知视图；它是内存中的 ``frozenset``，
**不进存储 schema**（5 元组冻结不变）。

**加载期零副作用**：纯内存合并（零网络 / 零 IO / 零 SQLite 写入）。
消费端统一走本模块（``LEXICON`` / ``view`` / ``sources_of``），禁止再直连分片。
注意：本模块刻意 **不** 加进 ``delector/core/__init__.py``，保持惰性导入
（与 ``database`` / ``security`` 同策略），避免无关导入触发重依赖。
"""

from typing import Dict, Iterable, Mapping, Optional, Sequence

from delector.data.core_dict import CORE_VOCAB_MANUAL
from delector.data.core_dict_ext import CORE_VOCAB_EXT
from delector.data.official_vocab import (
    OFFICIAL_A1_AUGMENT,
    OFFICIAL_A1_VOCAB,
    OFFICIAL_A2B1_VOCAB,
    OFFICIAL_VOCAB,
)

# 来源优先级：低 -> 高（后者覆盖前者）。
SOURCE_PRIORITY: tuple = ("ai", "manual", "official")

# 分片注册表：键 = 来源名，值 = 该来源的 5 元组分片（直接引用，只读消费）。
FRAGMENTS: Dict[str, Dict[str, tuple]] = {
    "ai": CORE_VOCAB_EXT,
    "manual": CORE_VOCAB_MANUAL,
    "official": OFFICIAL_VOCAB,
}


def merge_fragments(
    fragments: Mapping[str, Mapping[str, tuple]],
    priority: Sequence[str],
) -> Dict[str, tuple]:
    """按 ``priority``（低 -> 高）顺序合并分片，高优先来源覆盖同 lemma 的低优先值。

    纯函数、零副作用：只读传入的 ``fragments``，返回全新 dict（key=lemma 唯一，
    插入顺序 = 各片首次出现顺序，与逐片 ``update`` 语义一致，故与旧内联推导式的
    产物逐字相等）。

    单独抽出来是为「中间层优先级」留一个可单测的接缝 —— 真实分片里 ai 与 manual
    恰好没有同 lemma 冲突，因此 ``SOURCE_PRIORITY`` 若被误写为
    ``("manual", "ai", "official")``（= ai 覆盖 manual，语义反转），主干的
    ``LEXICON`` 不会有任何可见差异；只有用人工构造的 ``fragments`` 直接调本函数，
    才能把这段顺序语义钉死。
    """
    result: Dict[str, tuple] = {}
    for source in priority:
        result.update(fragments[source])
    return result


# 按 SOURCE_PRIORITY 顺序合并（高优先覆盖低优先），key=lemma 唯一。
LEXICON: Dict[str, tuple] = merge_fragments(FRAGMENTS, SOURCE_PRIORITY)

# provenance：lemma -> 贡献该 lemma 的来源集合（同 lemma 在几片出现就含几个来源名）。
_all_lemmas = {lemma for fragment in FRAGMENTS.values() for lemma in fragment}
PROVENANCE: Dict[str, frozenset] = {
    lemma: frozenset(source for source in SOURCE_PRIORITY if lemma in FRAGMENTS[source])
    for lemma in _all_lemmas
}


def sources_of(lemma: str) -> frozenset:
    """返回贡献该 lemma 的来源集合（未登记 lemma 返回空集）。"""
    return PROVENANCE.get(lemma, frozenset())


def view(sources: Optional[Iterable[str]] = None) -> Dict[str, tuple]:
    """按来源过滤返回子视图（不复制数据以外的结构）。

    ``None`` 表示全部来源（等价于 ``LEXICON``）；否则仅合并选中的来源，
    并保持 ``SOURCE_PRIORITY`` 顺序，使覆盖语义与主干一致。
    """
    if sources is None:
        return dict(LEXICON)
    selected = set(sources)
    result: Dict[str, tuple] = {}
    for source in SOURCE_PRIORITY:
        if source in selected:
            result.update(FRAGMENTS[source])
    return result


def official_level(cefr: str) -> Dict[str, tuple]:
    """官方某等级的**原样**词表视图（各档保留官方原样、容忍跨档重叠）。

    - ``"A1"`` -> ``OFFICIAL_A1_VOCAB`` ⊕ ``OFFICIAL_A1_AUGMENT``（670）
    - ``"A2"`` -> ``OFFICIAL_A2B1_VOCAB`` 中 ``cefr == "A2"``（736）
    - ``"B1"`` -> ``OFFICIAL_A2B1_VOCAB`` 中 ``cefr == "B1"``（1617）
    - 其它 -> ``{}``

    注意：**不要**用 ``OFFICIAL_VOCAB``——那是按低等级优先合并后的全量视图，
    A2/B1 会因 291 条跨档重叠被 A1 覆盖而变少。本函数各档保留官方原样、
    容忍跨档重叠（A1 与 A2/B1 同 lemma 各留其自带的 cefr 值）。

    大小写不敏感：``cefr.strip().upper()``。纯函数、零副作用（只读分片常量）。
    """
    level = (cefr or "").strip().upper()
    if level == "A1":
        a1_view: Dict[str, tuple] = {}
        a1_view.update(OFFICIAL_A1_VOCAB)
        a1_view.update(OFFICIAL_A1_AUGMENT)
        return a1_view
    if level in ("A2", "B1"):
        return {lemma: val for lemma, val in OFFICIAL_A2B1_VOCAB.items() if val[0] == level}
    return {}
