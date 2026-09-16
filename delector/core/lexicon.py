# -*- coding: utf-8 -*-
"""词汇主干加载器（ADR-0012 / R3）：分片注册表 + provenance + 来源优先级。

**来源分层**（分片 = 模块边界表达来源，不引入 schema 字段，守 5 元组冻结红线）：
    - ``ai``       <- ``delector.data.core_dict_ext.CORE_VOCAB_EXT``   （AI 批量生成）
    - ``manual``   <- ``delector.data.core_dict.CORE_VOCAB_MANUAL``    （手编核心）
    - ``official`` <- ``delector.data.official_vocab.OFFICIAL_VOCAB``  （官方歌德词表）

**优先级语义是「字段级」而非「整条覆盖」**（规则集中在 ``delector.data.lexicon_merge``）：
    - ``cefr``：``official > manual > ai`` —— 难度等级以官方考纲为权威；
    - ``pos`` / ``gender`` / ``plural`` / ``def_zh``：``manual > official > ai``
      —— 富字段保留人工质量（官方 ``plural`` 列约 30% 是占位 ``-``，
      整条用官方覆盖手编会劣化：``haus`` ``-..er``→``-ä``、``schule`` ``-n``→``-``）。
    ``SOURCE_PRIORITY`` 仍保留（``ai < manual < official``），仅用于 provenance / 子视图
    的「来源顺序」说明；真正的逐字段取值规则由 ``FIELD_PRIORITY`` 表达。

**provenance 是运行期旁路**：``PROVENANCE`` 记录每个 lemma 由哪些来源贡献，
仅供加载后查询「仅官方精选」等来源感知视图；它是内存中的 ``frozenset``，
**不进存储 schema**（5 元组冻结不变）。

**加载期零副作用**：纯内存合并（零网络 / 零 IO / 零 SQLite 写入）。
消费端统一走本模块（``LEXICON`` / ``view`` / ``sources_of``），禁止再直连分片。
注意：本模块刻意 **不** 加进 ``delector/core/__init__.py``，保持惰性导入
（与 ``database`` / ``security`` 同策略），避免无关导入触发重依赖。
"""

from typing import Dict, Iterable, Optional

from delector.data.core_dict import CORE_VOCAB_MANUAL
from delector.data.core_dict_ext import CORE_VOCAB_EXT
from delector.data.lexicon_merge import FIELD_PRIORITY, merge_fragments, provenance_of
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


# 逐字段合并（字段级优先级见 lexicon_merge.FIELD_PRIORITY）：key=lemma 唯一，
# 取值按字段分别取权威来源 —— cefr 官方优先、富字段手编优先。
# ``merge_fragments`` 与 ``provenance_of`` 是 lexicon_merge 的共享纯函数（零内部依赖），
# core_dict.CORE_VOCAB_DB 亦复用同一段逻辑，保证主干单真值（CORE_VOCAB_DB == LEXICON）。
LEXICON: Dict[str, tuple] = merge_fragments(FRAGMENTS, FIELD_PRIORITY)

# provenance：lemma -> 贡献该 lemma 的来源集合（同 lemma 在几片出现就含几个来源名）。
PROVENANCE: Dict[str, frozenset] = provenance_of(FRAGMENTS)


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
