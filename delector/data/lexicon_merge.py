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

import re
from typing import Any, Dict, FrozenSet, Iterator, Mapping, Sequence, Set, Tuple

# 5 元组字段顺序：与存储 schema（ADR-0011 #6 冻结）逐位对应，勿改。
FIELD_ORDER: Tuple[str, ...] = ("cefr", "pos", "gender", "plural", "def_zh")

# 字段级优先级（每字段列出「从高到低」的来源名）。
#   - cefr：官方 > 手编 > AI（难度等级以官方考纲为权威）；
#   - 富字段：手编 > 官方 > AI（官方 plural 列约 30% 是占位 '-'，覆盖手编会劣化）。
#   - ADR-0015：goethe-a1 / workbench-a1 并入后，gender/plural/def_zh 为
#     goethe-a1 > manual > official > workbench-a1 > ai（考纲人工元数据优先于官方占位，
#     仍保留 manual > official 以护 ADR-0012 人工质量）。
#   - pos 保持 manual > official > ai：A1 考纲/工作台的 pos 标签是 **view-owned** 展示层
#     （`NOUN` vs `f.`），不进共享 5 元组强行统一。
FIELD_PRIORITY: Dict[str, Tuple[str, ...]] = {
    "cefr": ("official", "goethe-a1", "workbench-a1", "manual", "ai"),
    "pos": ("manual", "official", "ai"),
    # gender 值域兼容（Masc/Fem/Neut）；plural 位是**后缀标记**，GOETHE 完整复数形
    # （`die Abfahrten`）禁止写入，故 goethe-a1 不参与 plural（view-owned，走考纲卡）。
    "gender": ("goethe-a1", "manual", "official", "workbench-a1", "ai"),
    "plural": ("manual", "official", "ai"),
    "def_zh": ("goethe-a1", "manual", "official", "workbench-a1", "ai"),
}

# 富字段 side-car 字段级优先级（ADR-0015 §4-3）：人工 IPA/例句 > 考纲 > g2p rich。
# 语义 = **只补空**（first non-empty wins），非空永不被低优先级覆盖。
RICH_FIELD_PRIORITY: Dict[str, Tuple[str, ...]] = {
    "ipa": (
        "workbench-a1",
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    ),
    "example_de": (
        "workbench-a1",
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    ),
    "example_zh": (
        "workbench-a1",
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    ),
    "examples": (
        "workbench-a1",
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    ),
    "topic": (
        "goethe-a1",
        "official_rich_a1",
        "official_rich_a2",
        "official_rich_b1",
    ),
}

# lemma 规范化（ADR-0015 §2.2 唯一实现；禁第二份）。
_RE_SPICH = re.compile(r"^\(sich\)\s*", re.IGNORECASE)
_RE_ARTICLE = re.compile(r"^(?:der|die|das|ein|eine)\s+", re.IGNORECASE)
_RE_COMMA_TAIL = re.compile(r",.*$")
_RE_EDGE_DASH = re.compile(r"[\s\-]+$")
_RE_SPACES = re.compile(r"[\s\-]+")
_RE_MULTI_DASH = re.compile(r"-{2,}")


def lemma_key(raw: str) -> str:
    """把表层词形 / lemma 收成稳定查找键（小写、连字符分词、无冠词）。

    步骤顺序固定（幂等）：
      1. 去 ``(sich)`` 类前缀；2. 去前置冠词；3. 去逗号后屈折尾巴；
      4. 去尾部连字符（``all-`` → ``all``）；5. 空白/连字符折叠为 ``-`` 并小写
      （``an sein`` → ``an-sein``，与 official 一致）。
    """
    s = (raw or "").strip()
    s = _RE_SPICH.sub("", s)
    s = _RE_ARTICLE.sub("", s)
    s = _RE_COMMA_TAIL.sub("", s)
    s = _RE_EDGE_DASH.sub("", s)
    s = _RE_SPACES.sub("-", s)
    s = _RE_MULTI_DASH.sub("-", s).strip("-").lower()
    return s


def _iter_lemmas(fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]]) -> Iterator[str]:
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


def _field_nonempty(value: Any) -> bool:
    """5 元组字段「非空」：``None`` / 空白串视为可跳过（占位 ``"-"`` 仍算有值，护 ADR-0012）。

    字符串 ``"None"`` **是**非空：主干用字面量 ``"None"`` 表示「无性别」（官方 5 元组
    规约，842 条），契约层再归一化为 ``None``（见 ``database._a1_noun_meta``）。
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def merge_fragments(
    fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]],
    field_priority: Mapping[str, Sequence[str]] = FIELD_PRIORITY,
) -> Dict[str, Tuple[Any, ...]]:
    """逐字段合并：对每个 lemma 的每个字段，取 ``field_priority[字段]`` 中
    第一个含该 lemma **且该字段非空** 的来源值；全空则 ``None``（显式缺省）。

    纯函数、零副作用：只读传入的 ``fragments``，返回全新 ``dict``；key = 分片
    lemma 并集，value = 5 元组（按 ``FIELD_ORDER`` 逐位取来源值拼回）。

    单独抽成共享纯函数，是为让「主干 LEXICON」与「core_dict 兼容视图 CORE_VOCAB_DB」
    走**同一段**合并逻辑 —— 否则两份常量各写一份合并，稍有不慎就会静默分叉成双真值
    （ADR-0012 明令单真值）。

    非空跳过是 ADR-0015 引入的（A1 分片字段稀疏）：空值不得挡住低优先级补全；
    占位 ``"-"`` **不是空**（官方 plural 语义，保留 ADR-0012 人工占位优先）。
    """
    merged: Dict[str, Tuple[Any, ...]] = {}
    for lemma in _iter_lemmas(fragments):
        values = []
        for position, field in enumerate(FIELD_ORDER):
            field_value = None
            for source in field_priority[field]:
                fragment = fragments.get(source)
                if fragment is not None and lemma in fragment:
                    candidate = fragment[lemma][position]
                    if _field_nonempty(candidate):
                        field_value = candidate
                        break
            values.append(field_value)
        merged[lemma] = tuple(values)
    return merged


def provenance_of(
    fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]],
) -> Dict[str, FrozenSet[str]]:
    """``lemma -> 含该 lemma 的来源集合``（``frozenset``）。

    运行期旁路：记录每个 lemma 由哪些来源贡献，仅供加载后查询「仅官方精选」等
    来源感知视图；它是内存中的 ``frozenset``，**不进存储 schema**（5 元组冻结不变）。
    纯函数、零副作用（只读传入的 ``fragments``）。
    """
    contributors: Dict[str, Set[str]] = {}
    for source, fragment in fragments.items():
        for lemma in fragment:
            contributors.setdefault(lemma, set()).add(source)
    return {lemma: frozenset(sources) for lemma, sources in contributors.items()}


def _rich_nonempty(value: Any) -> bool:
    """富字段「非空」判定：``None`` / 空串 / 空列表 / 空 dict 视为空。"""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return len(value) > 0
    return True


def merge_rich_fragments(
    fragments: Mapping[str, Mapping[str, Mapping[str, Any]]],
    field_priority: Mapping[str, Sequence[str]] = RICH_FIELD_PRIORITY,
) -> Dict[str, Dict[str, Any]]:
    """富字段 side-car 的**只补空**字段级合并（ADR-0015）。

    对每个 lemma 的每个富字段，取 ``field_priority[字段]`` 中第一个**非空**值；
    全空则该字段为 ``None``（显式缺省，禁止编造）。不抹高优先级非空值。
    纯函数、零副作用。key 插入顺序 = 各分片首次出现顺序。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()
    order: list[str] = []
    for fragment in fragments.values():
        for lemma in fragment:
            if lemma not in seen:
                seen.add(lemma)
                order.append(lemma)
    for lemma in order:
        row: Dict[str, Any] = {}
        for field, sources in field_priority.items():
            chosen: Any = None
            for source in sources:
                shard = fragments.get(source)
                if shard is None:
                    continue
                entry = shard.get(lemma)
                if entry is None:
                    continue
                value = entry.get(field)
                if _rich_nonempty(value):
                    chosen = value
                    break
            row[field] = chosen
        merged[lemma] = row
    return merged
