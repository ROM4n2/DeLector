# -*- coding: utf-8 -*-
"""Phase 2 · Task S1 契约测试：富字段分片 `delector.data.official_vocab_rich`（ADR-0013）。

守卫 3 个常量（OFFICIAL_RICH_A1 660 / OFFICIAL_RICH_A2 736 / OFFICIAL_RICH_B1 1617）的：
1. 各分片条数精确；
2. 每条为 dict 且键集恰为 {ipa, example_de, example_zh, topic}；
3. IPA 无 tie-bar 残留（U+0361 归一化，ADR-0013 §4-4）；
4. 与官方 5 元组分片的 join 完整性（join key = lemma，零差）；
5. 富字段覆盖统计（防回归；实测校准为精确下界）；
6. 纯数据性（除 import 的 typing 类型对象外，模块内零可调用成员）。

Schema（ADR-0013）：lemma -> {"ipa","example_de","example_zh","topic"}
"""

from delector.data import official_vocab_rich as rich
from delector.data.official_vocab import OFFICIAL_A1_VOCAB, OFFICIAL_A2B1_VOCAB

# 键集冻结：任何字段增减都会触发失败（side-car schema 由 ADR-0013 钉死）。
_ENTRY_KEYS = {"ipa", "example_de", "example_zh", "topic"}

# tie-bar = COMBINING DOUBLE INVERTED BREVE（U+0361）。
_TIE_BAR = "\u0361"
_TIE_BAR_DIGRAPHS = ("t\u0361s", "t\u0361\u0283", "p\u0361f")

# 公有名字集合被冻结：只允许 3 个数据常量 + 唯一 import 名 Dict。
_EXPECTED_PUBLIC_NAMES = {
    "OFFICIAL_RICH_A1",
    "OFFICIAL_RICH_A2",
    "OFFICIAL_RICH_B1",
    "Dict",
}
# typing 导入的类型对象白名单：callable 但属类型注解，不算「可调用逻辑」。
_ALLOWED_CALLABLE_IMPORTS = {"Dict"}


def test_fragment_counts_exact():
    """三常量条数精确（S1 交付物规格）。"""
    assert len(rich.OFFICIAL_RICH_A1) == 660
    assert len(rich.OFFICIAL_RICH_A2) == 736
    assert len(rich.OFFICIAL_RICH_B1) == 1617


def test_every_entry_is_dict_with_frozen_keyset():
    """每条为 dict，键集恰为 {ipa, example_de, example_zh, topic}，值均为 str。"""
    for name, db in (
        ("A1", rich.OFFICIAL_RICH_A1),
        ("A2", rich.OFFICIAL_RICH_A2),
        ("B1", rich.OFFICIAL_RICH_B1),
    ):
        for lemma, entry in db.items():
            assert isinstance(entry, dict), f"{name}:{lemma} 值非 dict"
            assert set(entry.keys()) == _ENTRY_KEYS, f"{name}:{lemma} 键集漂移 {sorted(entry)}"
            for field, value in entry.items():
                assert isinstance(value, str), f"{name}:{lemma}.{field} 非 str"


def test_no_tie_bar_residue_in_ipa():
    """IPA 归一化：三常量全部 ipa 值不含 U+0361，且 tie-bar 连写形式均不出现。

    反恒真：不只看「无残留」，还钉住已知 lemma 的**归一化后**字面值 —— 若归一化写成
    「把整个 ipa 清空」或「漏改某片」，这些精确断言会变红。
    """
    db = {
        "A1": rich.OFFICIAL_RICH_A1,
        "A2": rich.OFFICIAL_RICH_A2,
        "B1": rich.OFFICIAL_RICH_B1,
    }
    total_hits = sum(v["ipa"].count(_TIE_BAR) for d in db.values() for v in d.values())
    assert total_hits == 0, f"ipa 仍有 tie-bar 残留（实测命中 {total_hits}）"

    for name, d in db.items():
        for lemma, v in d.items():
            for digraph in _TIE_BAR_DIGRAPHS:
                assert digraph not in v["ipa"], f"{name}:{lemma} ipa 残留 tie-bar：{v['ipa']!r}"

    # 归一化后字面值（源为 tie-bar 版本，此处须为去 tie-bar 版本）。
    assert rich.OFFICIAL_RICH_A1["ankreuzen"]["ipa"] == "ˈaŋkʁɔɪtsən"
    assert rich.OFFICIAL_RICH_A1["apfel"]["ipa"] == "deːɐ ˈapfəl"
    assert rich.OFFICIAL_RICH_A1["entschuldigen"]["ipa"] == "ɛntʃˈʊldɪçən"


def test_join_integrity_with_official_fragments():
    """join key = lemma：与官方 5 元组分片逐等级零差（ADR-0013）。

    A1 恰等于 OFFICIAL_A1_VOCAB（660，即**不含** OFFICIAL_A1_AUGMENT 的 10 条表外词）。
    """
    a2_keys = {k for k, v in OFFICIAL_A2B1_VOCAB.items() if v[0] == "A2"}
    b1_keys = {k for k, v in OFFICIAL_A2B1_VOCAB.items() if v[0] == "B1"}

    assert len(a2_keys) == 736
    assert len(b1_keys) == 1617
    assert set(rich.OFFICIAL_RICH_A2) == a2_keys
    assert set(rich.OFFICIAL_RICH_B1) == b1_keys
    assert set(rich.OFFICIAL_RICH_A1) == set(OFFICIAL_A1_VOCAB)


def test_field_coverage_ratchet():
    """富字段覆盖统计（防回归；实测校准为精确下界，源数据缺口为「不编造」语义）。"""
    a2 = rich.OFFICIAL_RICH_A2
    b1 = rich.OFFICIAL_RICH_B1

    assert sum(1 for v in a2.values() if v["ipa"]) >= 733
    assert sum(1 for v in a2.values() if v["example_zh"]) >= 729
    assert sum(1 for v in b1.values() if v["ipa"]) >= 1616
    assert sum(1 for v in b1.values() if v["example_zh"]) == 1617


def _is_typing_type_object(value):
    """typing.Dict 这类导入的类型对象（callable 但非模块自带数据逻辑）。"""
    return getattr(value, "__module__", None) == "typing"


def test_pure_data_no_callables():
    """纯数据：除 import 的 typing 类型对象（Dict）外，模块内零可调用成员；
    且公有名字集合被冻结（新增函数/类/变量即失败）。
    """
    # 1) 公有名字集合精确冻结
    public_names = {name for name in vars(rich) if not name.startswith("_")}
    assert public_names == _EXPECTED_PUBLIC_NAMES, (
        f"公有名字集合漂移: {sorted(public_names ^ _EXPECTED_PUBLIC_NAMES)}"
    )

    # 2) 排除 typing 导入的类型对象后，模块内不得存在任何可调用成员
    unexpected_callables = [
        name
        for name, value in vars(rich).items()
        if not name.startswith("__")
        and callable(value)
        and not (name in _ALLOWED_CALLABLE_IMPORTS and _is_typing_type_object(value))
    ]
    assert unexpected_callables == [], f"模块含非数据可调用成员: {unexpected_callables}"
