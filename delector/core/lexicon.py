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

**富字段是输出层 side-car**（ADR-0013 §5-1）：``RICH`` / ``rich_of`` 提供
``lemma -> {ipa, example_de, example_zh, topic}`` 的**展示用**富字段视图，
来源为 ``delector.data.official_vocab_rich`` 三常量（A1/A2/B1）。它**只服务输出层**
（前端富卡片 / 例句 / 音标），**不进 5 元组存储**、不改 ``LEXICON`` / ``PROVENANCE``
语义（单入口见 §5-5：消费端统一走本模块）。加载期零网络 / 零 IO（纯内存合并）。

**加载期零副作用**：纯内存合并（零网络 / 零 IO / 零 SQLite 写入）。
消费端统一走本模块（``LEXICON`` / ``view`` / ``sources_of``），禁止再直连分片。
注意：本模块刻意 **不** 加进 ``delector/core/__init__.py``，保持惰性导入
（与 ``database`` / ``security`` 同策略），避免无关导入触发重依赖。
"""

from typing import Any, Dict, Iterable, Optional

# 主干对外 API（re-export，唯一实现仍在 delector.data.core_dict）：
# ``get_core_cefr_level`` / ``lookup_core_vocab`` 是主干对外 API，实现唯一、禁止再复制，
# 消费端统一 ``from delector.core.lexicon import ...``、不再直连分片（ADR-0012）。
from delector.data.core_dict import CORE_VOCAB_MANUAL, get_core_cefr_level, lookup_core_vocab  # noqa: F401
from delector.data.core_dict_ext import CORE_VOCAB_EXT
from delector.data.lexicon_merge import FIELD_PRIORITY, merge_fragments, provenance_of
from delector.data.official_vocab import (
    OFFICIAL_A1_AUGMENT,
    OFFICIAL_A1_VOCAB,
    OFFICIAL_A2B1_VOCAB,
    OFFICIAL_VOCAB,
)
from delector.data.official_vocab_rich import (
    OFFICIAL_RICH_A1,
    OFFICIAL_RICH_A2,
    OFFICIAL_RICH_B1,
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


# 富字段 side-car 分片注册表：来源 official_rich（A1/A2/B1 三常量，纯数据 · 只读消费）。
# 不进 5 元组存储（ADR-0013 §5-1），仅供输出层富卡片 / 例句 / 音标。
RICH_FRAGMENTS: Dict[str, Dict[str, dict]] = {
    "official_rich_a1": OFFICIAL_RICH_A1,
    "official_rich_a2": OFFICIAL_RICH_A2,
    "official_rich_b1": OFFICIAL_RICH_B1,
}


def _merge_rich(fragments: Dict[str, Dict[str, dict]]) -> Dict[str, Dict[str, Any]]:
    """按分片注册顺序平面合并富字段（后者覆盖前者，key = lemma）。

    纯函数、零副作用：只读传入分片，返回全新 ``dict``。合并顺序由 ``fragments``
    插入顺序决定（此处为 A1 -> A2 -> B1）。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for fragment in fragments.values():
        merged.update(fragment)
    return merged


# 富字段视图：lemma -> {ipa, example_de, example_zh, topic}。
# 合并顺序 A1 -> A2 -> B1：**A2/B1 的 lemma 覆盖 A1**（A1 与 A2B1 有 291 条跨档重叠，
# A1 卡片走 seed / GOETHE_A1_VOCAB 不用本表，故重叠时以 A2/B1 为准）。
RICH: Dict[str, Dict[str, Any]] = _merge_rich(RICH_FRAGMENTS)


def rich_of(lemma: str) -> Optional[Dict[str, Any]]:
    """返回该 lemma 的富字段（``{ipa, example_de, example_zh, topic}``）。

    未知 lemma 返回 ``None``（不抛错）。只读视图（输出层 side-car，不进存储）。
    """
    return RICH.get(lemma)


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


def core_ids_by_level() -> Dict[str, frozenset]:
    """多级核心词白名单（预留结构）。

    现状：仅 A1 有名单（213，来自 ``a1_workbench_dict.A1_WORKBENCH_CORE_IDS``）；
    ``A2`` / ``B1`` / ``B2`` 为**空集占位**，表示「该级尚未定义核心词」。
    扩展方式（纯数据）：在此登记该级 id 集 + 前端 ``#scopeSeg`` 加一个 ``data-scope``
    按钮并在 ``SCOPE_PREDICATES`` 加一行谓词（见 ``workbench.html`` 既有数据驱动机制）。

    纯只读：A1 名单惰性取自 ``delector.data.a1_workbench_dict``（保持单一真相，
    不复制一份名单过来），每次返回全新的 ``frozenset`` 副本，不修改任何全局名单。
    """
    # 惰性导入：a1_workbench_dict 是较大的纯数据模块，避免 lexicon 顶层加载期连带
    # 导入（与 database / security 的惰性策略一致）；此处只用其 A1 核心 id 的单一真相。
    from delector.data.a1_workbench_dict import A1_WORKBENCH_CORE_IDS

    return {
        "A1": frozenset(A1_WORKBENCH_CORE_IDS),
        "A2": frozenset(),
        "B1": frozenset(),
        "B2": frozenset(),
    }
