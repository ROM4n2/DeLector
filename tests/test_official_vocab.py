# -*- coding: utf-8 -*-
"""Task R2 契约测试：官方词表分片数据模块 `delector.data.official_vocab`。

守卫 4 个常量（OFFICIAL_A1_VOCAB 660 / OFFICIAL_A1_AUGMENT 10 /
OFFICIAL_A2B1_VOCAB 2353 / OFFICIAL_VOCAB 2732）的：
1. 各分片条数精确；2. 每条为长度 5 的 tuple；3. cefr 取值域；
4. 名词 gender 合法、非名词 gender 为 None；
5. 合并冲突「低等级优先」；6. 跨片重合 291 与 A2/B1 等级拆分（736/1617）；
7. 纯数据性（除 import 的 typing 类型对象外，模块内零可调用成员）。

Schema（ADR-0011 #6 冻结）：lemma -> (cefr, pos, gender, plural, definition_zh)
"""

from delector.data import official_vocab as ov

_VALID_GENDER = {"Masc", "Fem", "Neut", "Plur"}

# 公有名字集合被冻结：只允许 4 个数据常量 + 唯一 import 名 Dict。
_EXPECTED_PUBLIC_NAMES = {
    "OFFICIAL_A1_VOCAB",
    "OFFICIAL_A1_AUGMENT",
    "OFFICIAL_A2B1_VOCAB",
    "OFFICIAL_VOCAB",
    "Dict",
}
# typing 导入的类型对象白名单：callable 但属类型注解，不算「可调用逻辑」。
_ALLOWED_CALLABLE_IMPORTS = {"Dict"}


def _assert_schema(db):
    """逐条校验 5 元组形态、lemma 小写、gender 规则。"""
    for lemma, entry in db.items():
        assert isinstance(lemma, str), f"lemma 非 str: {lemma!r}"
        assert lemma == lemma.lower(), f"lemma 未小写: {lemma!r}"
        assert isinstance(entry, tuple), f"{lemma}: 值非 tuple"
        assert len(entry) == 5, f"{lemma}: 元组长度 {len(entry)} != 5"

        cefr, pos, gender, plural, definition = entry
        assert isinstance(cefr, str) and cefr, f"{lemma}: cefr 非法 {cefr!r}"
        assert isinstance(pos, str) and pos, f"{lemma}: pos 非法 {pos!r}"
        assert isinstance(plural, str), f"{lemma}: plural 非 str {plural!r}"
        assert isinstance(definition, str), f"{lemma}: definition 非 str"

        if pos == "NOUN":
            assert gender in _VALID_GENDER, f"{lemma}: 名词 gender 非法 {gender!r}"
        else:
            assert gender is None, f"{lemma}: 非名词 gender 应为 None，实为 {gender!r}"


def _is_typing_type_object(value):
    """typing.Dict 这类导入的类型对象（callable 但非模块自带数据逻辑）。"""
    return getattr(value, "__module__", None) == "typing"


def test_partition_counts_and_cross_fragment_integrity():
    """各分片精确计数 + 跨片重合 291 + A2/B1 等级拆分（替换原恒真死断言）。

    原 `len(db) == len(set(db))` 对 dict 恒真、无检测力，现改为对分片规模、
    跨片重合与片内等级拆分做精确锚定。
    """
    # 各分片精确计数
    assert len(ov.OFFICIAL_A1_VOCAB) == 660
    assert len(ov.OFFICIAL_A1_AUGMENT) == 10
    assert len(ov.OFFICIAL_A2B1_VOCAB) == 2353
    assert len(ov.OFFICIAL_VOCAB) == 2732

    # 跨片重合精确值：A1 与 A2B1 有 291 条同 lemma 跨档重复
    assert len(set(ov.OFFICIAL_A1_VOCAB) & set(ov.OFFICIAL_A2B1_VOCAB)) == 291

    # A2B1 片内等级拆分：A2 736 + B1 1617 恰为该片总数
    a2_count = sum(1 for v in ov.OFFICIAL_A2B1_VOCAB.values() if v[0] == "A2")
    b1_count = sum(1 for v in ov.OFFICIAL_A2B1_VOCAB.values() if v[0] == "B1")
    assert a2_count == 736
    assert b1_count == 1617
    assert a2_count + b1_count == len(ov.OFFICIAL_A2B1_VOCAB)


def test_values_are_five_tuples():
    """每条值为长度 5 的 tuple，且 lemma 小写、gender 规则成立。"""
    _assert_schema(ov.OFFICIAL_A1_VOCAB)
    _assert_schema(ov.OFFICIAL_A1_AUGMENT)
    _assert_schema(ov.OFFICIAL_A2B1_VOCAB)
    _assert_schema(ov.OFFICIAL_VOCAB)


def test_cefr_domains():
    """cefr 合法：前两片全 A1；A2/B1 片仅含 A2/B1。"""
    assert {v[0] for v in ov.OFFICIAL_A1_VOCAB.values()} == {"A1"}
    assert {v[0] for v in ov.OFFICIAL_A1_AUGMENT.values()} == {"A1"}
    assert {v[0] for v in ov.OFFICIAL_A2B1_VOCAB.values()} <= {"A2", "B1"}
    assert {v[0] for v in ov.OFFICIAL_VOCAB.values()} <= {"A1", "A2", "B1"}


def test_merge_priority_low_level_wins():
    """合并冲突时低等级（A1）胜出：ruhig A1↔A2、zurzeit A1↔B1。"""
    assert ov.OFFICIAL_VOCAB["ruhig"][0] == "A1"
    assert ov.OFFICIAL_VOCAB["zurzeit"][0] == "A1"
    # A1 分片的值必须逐字胜出（不是仅 cefr 相同）
    assert ov.OFFICIAL_VOCAB["ruhig"] == ov.OFFICIAL_A1_VOCAB["ruhig"]
    assert ov.OFFICIAL_VOCAB["zurzeit"] == ov.OFFICIAL_A1_VOCAB["zurzeit"]


def test_merged_equals_low_level_first_expansion():
    """合并规则精确：{**A2B1, **A1, **A1_AUGMENT}（A1 覆盖 A2B1）。"""
    expected = {**ov.OFFICIAL_A2B1_VOCAB, **ov.OFFICIAL_A1_VOCAB, **ov.OFFICIAL_A1_AUGMENT}
    assert ov.OFFICIAL_VOCAB == expected


def test_pure_data_no_callables():
    """纯数据：除 import 的 typing 类型对象（Dict）外，模块内零可调用成员；
    且公有名字集合被冻结（新增函数/类/变量即失败）。
    """
    # 1) 公有名字集合精确冻结：任何新增的模块级函数/类/变量都会触发失败。
    public_names = {name for name in vars(ov) if not name.startswith("_")}
    assert public_names == _EXPECTED_PUBLIC_NAMES, (
        f"公有名字集合漂移: {sorted(public_names ^ _EXPECTED_PUBLIC_NAMES)}"
    )

    # 2) 排除 typing 导入的类型对象后，模块内不得存在任何可调用成员
    #    （涵盖函数、类、可调用 import、functools.partial 等）。
    unexpected_callables = [
        name
        for name, value in vars(ov).items()
        if not name.startswith("__")
        and callable(value)
        and not (name in _ALLOWED_CALLABLE_IMPORTS and _is_typing_type_object(value))
    ]
    assert unexpected_callables == [], f"模块含非数据可调用成员: {unexpected_callables}"
