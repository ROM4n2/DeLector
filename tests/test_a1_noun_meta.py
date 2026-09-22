# -*- coding: utf-8 -*-
"""A1 卡片名词 gender / plural 补齐（S7 / ADR-0012 §4-4 派生；契约层 join）。

背景：A1 卡片的 ``gender`` / ``plural`` 长期为空（``_contract_from_a1_row`` 硬编码
``None`` / ``""``），因 ``A1_WORKBENCH_SEED`` 无这两字段。本任务在**视图层补全**
（不改存储、不改 id）：
- ``lexicon`` 提供只读视图 ``A1_LEMMA_META`` / ``a1_lemma_meta_of``（原始元数据）；
- ``database`` 把 seed ``hw`` 归一化后 join 该视图，**直取** gender / plural。

数据源（S7c 修正）：``delector.core.lexicon.LEXICON`` —— **主干**（字段级合并的唯一
入口，ADR-0012 §5-1），逐字段优先级为「富字段 ``pos`` / ``gender`` / ``plural`` /
``def_zh`` = 手编 > 官方 > AI」。``gender`` = ``v[2]``、``plural`` = ``v[3]``，
与 A2/B1 分支（``_contract_from_core_entry`` 亦读 ``LEXICON``）**同源**。

（S7b 旧源 ``official_level("A1")`` 已弃用：官方 Wortliste 的 ``plural`` 列质量粗 ——
``apfel`` 官方 ``"Ä"`` **连前导 ``-`` 都没有**、约 30% 是占位 ``"-"``；而主干 LEXICON
由字段级优先级产出（``apfel`` 取手编 ``"-.."``），值精确且格式统一。改走主干后 A1 与
A2/B1 完全同源，符合 ADR-0012 §5-1「主干唯一入口」。）
"""

from typing import Any, Dict

import pytest

from delector.core import database
from delector.core.database import get_vocab_by_cefr
from delector.core.lexicon import A1_LEMMA_META, LEXICON, a1_lemma_meta_of
from delector.data.a1_workbench_dict import A1_WORKBENCH_CUSTOM, A1_WORKBENCH_SEED

# 契约 gender 值域（与主干 5 元组一致，None = 无性别 / 非名词）
# 含主干字面量哨兵 "None"（非名词 / 无性别，契约层归一化为 None）。
_VALID_GENDERS = {None, "None", "Masc", "Fem", "Neut", "Plur"}

# 名词判据：``hw`` 首词为定冠词（seed 名词 hw 形如 ``die Adresse,-en`` / ``der Apfel, -Ä``）。
_A1_NOUN_ARTICLES = {"der", "die", "das"}

# plural 惯例（主干 5 元组）：空串 或 **后缀标记**（以 ``-`` 开头）。
# 例外（LEXICON 已知数据瑕疵）：``Firma`` → ``"Firmen"`` / ``Studium`` → ``"Studien"``
# 是不规则**完整形式**，无法用「前缀 ``-`` 后缀标记」表达，故显式登记放行；其余仍须满足惯例。
_IRREGULAR_PLURALS = {"Firmen", "Studien"}


def _is_valid_plural(p: str) -> bool:
    """plural 是否满足主干 5 元组惯例（``""`` | ``-...``），含已登记的不规则例外。"""
    return p == "" or p.startswith("-") or p in _IRREGULAR_PLURALS


@pytest.fixture(autouse=True)
def fresh_a1_cache():
    """隔离模块级缓存，防跨测试/跨文件泄漏。"""
    database._reset_a1_workbench_cache()
    yield
    database._reset_a1_workbench_cache()


def _contract_by_hw() -> Dict[str, Dict[str, Any]]:
    """A1 all 契约条目，按 ``hw``（seed 词头原样）索引。"""
    res = get_vocab_by_cefr(cefr="A1", scope="all")
    return {w["hw"]: w for w in res["words"]}


def _is_noun_hw(hw: str) -> bool:
    """``hw`` 是否带定冠词（名词判据，仅看首词）。"""
    parts = (hw or "").strip().split(None, 1)
    return bool(parts) and parts[0].lower() in _A1_NOUN_ARTICLES


# ── 1. lexicon 视图：覆盖度 + 原子性 ────────────────────────────────────────


def test_a1_lemma_meta_view_backs_lexicon():
    """``A1_LEMMA_META`` 是主干 ``LEXICON`` 的薄封装：键集/条数 == LEXICON，逐条直取。"""
    assert len(A1_LEMMA_META) == len(LEXICON)
    assert set(A1_LEMMA_META) == set(LEXICON)
    for lemma in ("apfel", "adresse", "absender", "schule", "haus", "zurzeit"):
        meta = A1_LEMMA_META[lemma]
        assert set(meta) == {"gender", "plural"}
        assert meta == {"gender": LEXICON[lemma][2], "plural": LEXICON[lemma][3]}
        assert meta["gender"] in _VALID_GENDERS


def test_a1_lemma_meta_raw_values_are_not_transformed():
    """直取主干 5 元组 ``v[2]`` / ``v[3]``（零推导 / 零转换）。

    ``apfel`` 主干 plural = ``"-.."``（手编后缀标记，前缀 ``-`` + ``..`` = 元音变音）；
    这**不是**官方 A1 分片的 ``"Ä"`` —— 来源不同、质量不同（字段级优先级：手编胜官方）。
    """
    assert a1_lemma_meta_of("absender") == {"gender": "Masc", "plural": "-"}
    assert a1_lemma_meta_of("adresse") == {"gender": "Fem", "plural": "-en"}
    assert a1_lemma_meta_of("apfel") == {"gender": "Masc", "plural": "-.."}


def test_a1_lemma_meta_of_unknown_returns_none():
    """未知 lemma → ``None``（不抛错、不编造）。"""
    assert a1_lemma_meta_of("__definitiv_nicht_vorhanden__") is None


# ── 2. database 归一化 / 直取（纯函数单测）────────────────────────────────


def test_normalize_a1_headword_rules():
    """``hw`` 归一化：小写 → 剥冠词 → 去括号 → 逗号前 → 去尾 '-' → 去空白。"""
    assert database._normalize_a1_headword("die Adresse,-en") == "adresse"
    assert database._normalize_a1_headword("der Apfel, -Ä") == "apfel"
    assert database._normalize_a1_headword("(sich) anmelden") == "anmelden"
    assert database._normalize_a1_headword("zum Beispiel/z. B.") == "zum beispiel/z. b."
    assert database._normalize_a1_headword("all-") == "all"
    assert database._normalize_a1_headword("Achtung") == "achtung"


def test_a1_noun_meta_directly_mirrors_lexicon():
    """名词样例：``_a1_noun_meta`` 逐字等价于主干 ``LEXICON`` ``v[2]`` / ``v[3]``。

    命中即原样透传（唯一的规约化：主干非名词条目的字面量 ``"None"`` → ``None`` / ``""``，
    与 ``_contract_from_core_entry`` 同规约）；未命中 → ``(None, "")``。
    """
    for hw in ("der Absender", "die Adresse,-en", "die Schule", "der Apfel, -Ä"):
        lemma = database._normalize_a1_headword(hw)
        val = LEXICON[lemma]
        assert database._a1_noun_meta(hw) == (val[2], val[3])
    # 未命中（不在主干 LEXICON）→ 显式空值，绝不编造
    assert database._a1_noun_meta("das Miniwort") == (None, "")
    assert database._a1_noun_meta("") == (None, "")


def test_a1_noun_meta_normalizes_literal_none_string():
    """主干以**字面量** ``"None"`` 表示「无性别」（非名词条目，842 条），契约层须归一化。

    这是 S7c 换源后暴露的规约：主干沿用官方 5 元组把无性别存为字符串 ``"None"``，
    与 ``_contract_from_core_entry`` 同规约必须 ``"None"`` → ``None``，否则 PRON/ADJ
    条目会把字符串 ``"None"`` 泄漏进契约（违反 gender 值域）。
    """
    assert LEXICON["kein"][2] == "None"  # 样本前提：主干确有字面量 "None"
    assert database._a1_noun_meta("kein") == (None, "")


# ── 3. 契约抽样（含 ``-`` / ``-en`` / 手编 ``-..`` 三例）──────────────────


def test_a1_contract_noun_gender_plural_samples():
    """抽样：命中即直取（gender/plural 与主干 LEXICON 逐字一致）。"""
    by_hw = _contract_by_hw()

    absender = by_hw["der Absender"]
    assert absender["gender"] == "Masc"
    assert absender["plural"] == "-"

    adresse = by_hw["die Adresse,-en"]
    assert adresse["gender"] == "Fem"
    assert adresse["plural"] == "-en"

    schule = by_hw["die Schule"]
    assert schule["gender"] == "Fem"
    assert schule["plural"] == "-n"

    # 手编精确值：主干 ``"-.."``（替换 S7b 官方源 ``"Ä"``）
    apfel = by_hw["der Apfel, -Ä"]
    assert apfel["gender"] == "Masc"
    assert apfel["plural"] == "-.."


# ── 4. 覆盖率下界（动态表达式断言，防静默劣化）─────────────────────────────


def test_a1_contract_noun_gender_plural_coverage_lower_bounds():
    """A1 名词（``hw`` 带冠词）条目的 gender 非空率 / plural 非空率须高于下界。

    S7c 实测（主干 LEXICON 源）：名词 344 条，gender 非空 336/344 ≈ 97.67%，
    plural 非空 336/344 ≈ 97.67%（对比 S7b 官方源 94.8%：覆盖率不降反升，且值质量更优）。
    阈值取 0.94 留余量：既仍高于 S7b 的 94.8%，又拦「视图 join 被回退成恒空」的回归。
    用动态表达式而非写死条数。
    """
    words = get_vocab_by_cefr(cefr="A1", scope="all")["words"]
    assert len(words) == len(A1_WORKBENCH_SEED) + len(A1_WORKBENCH_CUSTOM)

    nouns = [w for w in words if _is_noun_hw(w["hw"])]
    assert nouns, "样本前提失效：A1 无 hw 带冠词的名词"

    gender_non_null = sum(1 for w in nouns if w["gender"])
    plural_non_empty = sum(1 for w in nouns if w["plural"])

    assert gender_non_null / len(nouns) >= 0.94, (
        "A1 名词 gender 覆盖率过低：%d/%d" % (gender_non_null, len(nouns))
    )
    assert plural_non_empty / len(nouns) >= 0.94, (
        "A1 名词 plural 覆盖率过低：%d/%d" % (plural_non_empty, len(nouns))
    )


# ── 5. 未命中 → None / ""（不编造）─────────────────────────────────────────


def test_a1_contract_never_fabricates_gender_plural():
    """未命中 → 显式 None / ""（绝不猜测）。

    不变量：全部 A1 条目的 gender ∈ 值域；plural 为 str 且满足主干 5 元组惯例
    （``""`` | ``-...``，含登记的不规则例外）——搬运完整形式 / 编造值即被拦下。
    """
    words = get_vocab_by_cefr(cefr="A1", scope="all")["words"]
    for w in words:
        assert w["gender"] in _VALID_GENDERS, "%s gender 非法：%r" % (w["id"], w["gender"])
        assert isinstance(w["plural"], str), w["id"]
        assert _is_valid_plural(w["plural"]), (
            "%s plural 不符主干 5 元组惯例：%r" % (w["id"], w["plural"])
        )

    by_hw = {w["hw"]: w for w in words}
    # 动词（主干非名词条目：gender None / plural ""）→ None / ""
    verb = by_hw["abfahren"]
    assert verb["gender"] is None
    assert verb["plural"] == ""
