# -*- coding: utf-8 -*-
"""A1 工作台词库单一真相（Task 1 / ADR-0011）。

- 单一真相 = ``delector/data/a1_workbench_dict.py``（本测试按路径加载，不复用其代码）。
- ``static/js/wb-seed-data.js`` 里声明的四个 ``const`` 是它的**构建产物**，
  由 ``tools/build_workbench_seed.py`` 注入。

C7 Task 4 变更面：这四个 ``const`` 原先内联在 ``static/german/workbench.html``，
现已抽到上述 JS 数据模块（HTML 侧只剩一个普通 ``<script src>``）。本文件因此把
「构建产物」的落点从 HTML 改成 JS 数据模块，**两条 D 类断言的强度不变**：

本测试钉住三件事（行为断言，非整文件字符串存在性）：
1. 模块四个常量存在且条数/内容精确（682 / 213 / 22 / 别名表精确映射）；
2. 模块 ↔ JS 数据模块**双向 JSON 等价**（数组逐条 + id 顺序；核心词集合按升序），
   且这四个声明在 workbench.html 里**不再内联**（数据只有一份真相源）；
3. 注入**幂等**，且对当前数据模块**零漂移**（注入一遍与原文件字节一致）——
   否则每次构建都产生假 diff，"数据模块是构建产物"这句话就落不了地。
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import pytest

from delector.core import database

_ROOT = Path(__file__).resolve().parent.parent
# 构建产物的落点（C7 Task 4 起是 JS 数据模块，不再是 workbench.html 内联块）
SEED_DATA_JS = _ROOT / "static" / "js" / "wb-seed-data.js"
WORKBENCH_HTML = _ROOT / "static" / "german" / "workbench.html"
DICT_MODULE = _ROOT / "delector" / "data" / "a1_workbench_dict.py"
BUILD_TOOL = _ROOT / "tools" / "build_workbench_seed.py"

EXPECTED_SEED_COUNT = 682
EXPECTED_CORE_COUNT = 213
EXPECTED_CUSTOM_COUNT = 22
EXPECTED_ALIASES = {"a1-0544": "a1-0034", "a1-0545": "a1-0052"}


def _slice_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str:
    """从 start 起找第一个 open_ch，返回到其配对 close_ch 的闭合切片。

    与 tests/test_german_workbench.py 同款括号计数（种子/核心词常量里没有含括号的
    字符串字面量）；这里刻意独立实现，避免"测试复用被测代码"的自证循环。
    """
    begin = text.index(open_ch, start)
    depth = 0
    for i in range(begin, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
            continue
        if ch != close_ch:
            continue
        depth -= 1
        if depth == 0:
            return text[begin : i + 1]
    raise AssertionError("括号未闭合：%s ... %s" % (open_ch, close_ch))


def _seed_js_text() -> str:
    assert SEED_DATA_JS.exists(), "%s 尚未创建（C7 Task 4 交付物）" % SEED_DATA_JS.relative_to(_ROOT)
    return SEED_DATA_JS.read_text(encoding="utf-8")


def _product_const(name: str, open_ch: str, close_ch: str):
    """真解析构建产物（JS 数据模块）里的某个 `const <name> = <literal>`。"""
    text = _seed_js_text()
    decl = "const " + name
    assert decl in text, "static/js/wb-seed-data.js 缺少 %s 常量" % decl
    return json.loads(_slice_balanced(text, text.index(decl), open_ch, close_ch))


def _load_by_path(path: Path, alias: str) -> ModuleType:
    assert path.exists(), "%s 尚未创建（Task 1 交付物）" % path.relative_to(_ROOT)
    spec = importlib.util.spec_from_file_location(alias, str(path))
    # 仓库内固定路径的真实文件，spec/loader 必然可生成（None 仅是 API 签名的防御面）
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_dict_module() -> ModuleType:
    return _load_by_path(DICT_MODULE, "a1_workbench_dict_under_test")


def _load_tool() -> ModuleType:
    return _load_by_path(BUILD_TOOL, "build_workbench_seed_under_test")


# ── 1. 模块自身的契约 ────────────────────────────────────────────────────


def test_module_exports_four_constants():
    """模块必须导出四个常量，且核心词 id 是不可变集合（计划规定的类型）。"""
    mod = _load_dict_module()
    for name in (
        "A1_WORKBENCH_SEED",
        "A1_WORKBENCH_CORE_IDS",
        "A1_WORKBENCH_CUSTOM",
        "A1_WORKBENCH_ID_ALIASES",
    ):
        assert hasattr(mod, name), "a1_workbench_dict 缺少 %s" % name
    assert isinstance(mod.A1_WORKBENCH_CORE_IDS, frozenset), "A1_WORKBENCH_CORE_IDS 必须是 FrozenSet"
    assert isinstance(mod.A1_WORKBENCH_ID_ALIASES, dict), "A1_WORKBENCH_ID_ALIASES 必须是 Dict"


def test_module_counts_are_682_213_22():
    """条数精确：种子 682 / 核心词 id 213 / 核心新词 22（既有 test_german_workbench 同口径）。"""
    mod = _load_dict_module()
    assert len(mod.A1_WORKBENCH_SEED) == EXPECTED_SEED_COUNT, (
        "A1_WORKBENCH_SEED 应为 %d 条，实际 %d" % (EXPECTED_SEED_COUNT, len(mod.A1_WORKBENCH_SEED))
    )
    assert len(mod.A1_WORKBENCH_CORE_IDS) == EXPECTED_CORE_COUNT, (
        "A1_WORKBENCH_CORE_IDS 应为 %d 个，实际 %d" % (EXPECTED_CORE_COUNT, len(mod.A1_WORKBENCH_CORE_IDS))
    )
    assert len(mod.A1_WORKBENCH_CUSTOM) == EXPECTED_CUSTOM_COUNT, (
        "A1_WORKBENCH_CUSTOM 应为 %d 条，实际 %d" % (EXPECTED_CUSTOM_COUNT, len(mod.A1_WORKBENCH_CUSTOM))
    )


def test_module_aliases_are_exact():
    """别名表精确等于两条重复条目下架的归并映射（多一条/少一条都算漂移）。"""
    mod = _load_dict_module()
    assert mod.A1_WORKBENCH_ID_ALIASES == EXPECTED_ALIASES, (
        "别名表不一致：%s" % mod.A1_WORKBENCH_ID_ALIASES
    )


def test_module_ids_are_unique_and_resolvable():
    """种子词 id 唯一无重复；每个核心词 id 都真在种子词表里（挡住拼错/幻觉 id）。

    核心词集合是 FrozenSet（语义上无序），其"升序书写"由注入的字节一致断言钉住。
    """
    mod = _load_dict_module()
    seed_ids = {w["id"] for w in mod.A1_WORKBENCH_SEED}
    assert len(seed_ids) == EXPECTED_SEED_COUNT, "种子词 id 有重复"
    assert len(mod.A1_WORKBENCH_CORE_IDS) == EXPECTED_CORE_COUNT, "核心词 id 有重复"
    missing = sorted(set(mod.A1_WORKBENCH_CORE_IDS) - seed_ids)
    assert not missing, "这些核心词 id 不在种子词表里：%s" % missing


# ── 1b. IPA 无 tie-bar 残留（ADR-0013 §5-4）─────────────────────────────

# tie-bar = COMBINING DOUBLE INVERTED BREVE（U+0361）。
_TIE_BAR = "\u0361"


def test_seed_ipa_has_no_tie_bar_residue():
    """``A1_WORKBENCH_SEED`` 的 ipa 无 tie-bar 残留：U+0361 计数为 0（ADR-0013 §5-4）。

    ADR-0013「IPA 表示法唯一：全局无 tie-bar」——任一条 seed 词 ipa 回归 tie-bar
    连写写法（塞擦音连字符）即失败。
    """
    mod = _load_dict_module()
    total = sum((w.get("ipa") or "").count(_TIE_BAR) for w in mod.A1_WORKBENCH_SEED)
    assert total == 0, "A1_WORKBENCH_SEED 仍有 tie-bar 残留（实测命中 %d）" % total


def test_custom_ipa_has_no_tie_bar_residue():
    """``A1_WORKBENCH_CUSTOM`` 的 ipa 无 tie-bar 残留：U+0361 计数为 0（ADR-0013 §5-4）。

    ADR-0013 §5-4 是「全局无 tie-bar」：核心新词（custom）与种子词同受约束。任一条
    custom 词 ipa 回归 tie-bar 连写写法（塞擦音连字符，如 ``t\u0361s``）即失败。
    """
    mod = _load_dict_module()
    total = sum((w.get("ipa") or "").count(_TIE_BAR) for w in mod.A1_WORKBENCH_CUSTOM)
    assert total == 0, "A1_WORKBENCH_CUSTOM 仍有 tie-bar 残留（实测命中 %d）" % total


# ── 2. 模块 ↔ 构建产物（JS 数据模块）双向等价 ────────────────────────────


def test_seed_module_equals_js_product_verbatim():
    """种子词逐条 JSON 等价，且 id 顺序一致（顺序变了 = 页面词序变 = 行为变）。"""
    mod = _load_dict_module()
    product_seed = _product_const("SEED_WORDS", "[", "]")
    assert [w["id"] for w in mod.A1_WORKBENCH_SEED] == [w["id"] for w in product_seed], (
        "模块与 JS 数据模块的种子词 id 顺序不一致"
    )
    assert mod.A1_WORKBENCH_SEED == product_seed, "模块与 JS 数据模块的种子词内容不等价"


def test_custom_module_equals_js_product_verbatim():
    """核心新词逐条 JSON 等价，且 id 顺序一致。"""
    mod = _load_dict_module()
    product_custom = _product_const("CORE_CUSTOM_WORDS", "[", "]")
    assert [w["id"] for w in mod.A1_WORKBENCH_CUSTOM] == [w["id"] for w in product_custom], (
        "模块与 JS 数据模块的核心新词 id 顺序不一致"
    )
    assert mod.A1_WORKBENCH_CUSTOM == product_custom, "模块与 JS 数据模块的核心新词内容不等价"


def test_core_ids_module_equals_js_product_sorted():
    """核心词 id 集合等价，且产物里的书写顺序正是升序（Set 无序，用升序钉住书写顺序）。"""
    mod = _load_dict_module()
    product_core = _product_const("CORE_WORD_SEED_IDS", "[", "]")
    assert sorted(mod.A1_WORKBENCH_CORE_IDS) == product_core, "模块与 JS 数据模块的核心词 id 集合/顺序不一致"


def test_aliases_module_equals_js_product():
    """别名表与 JS 数据模块里的声明等价。"""
    mod = _load_dict_module()
    assert mod.A1_WORKBENCH_ID_ALIASES == _product_const("SEED_ID_ALIASES", "{", "}"), (
        "模块与 JS 数据模块的别名表不一致"
    )


# ── 3. 构建工具：抽取 / 注入 ─────────────────────────────────────────────


def test_extract_is_faithful_to_module_constants():
    """工具 parse_source(当前数据模块) 必须等于模块四个常量 —— --extract 是逐字搬运。

    附带钉住「数据只有一份真相源」：workbench.html 里不得再内联这四个声明。
    同一条数据若存在两个落点，注入只会更新其中一个，另一处会静默腐坏成第二个真相。
    """
    html = WORKBENCH_HTML.read_text(encoding="utf-8")
    for name in ("SEED_WORDS", "CORE_WORD_SEED_IDS", "CORE_CUSTOM_WORDS", "SEED_ID_ALIASES"):
        assert "const " + name not in html, "%s 又被内联回 workbench.html 了（数据必须只有一份）" % name

    tool = _load_tool()
    parsed = tool.parse_source(_seed_js_text())
    mod = _load_dict_module()
    assert parsed["seed"] == mod.A1_WORKBENCH_SEED
    assert parsed["core_ids"] == sorted(mod.A1_WORKBENCH_CORE_IDS)
    assert parsed["custom"] == mod.A1_WORKBENCH_CUSTOM
    assert parsed["aliases"] == mod.A1_WORKBENCH_ID_ALIASES


def test_injection_into_data_module_is_byte_identical():
    """用模块反向注入当前数据模块：必须字节一致（零漂移，数据模块确为模块的构建产物）。

    这条同时钉住"注入不得触碰数据模块其他任何部分"：任何多改/少改（其余三个声明、
    文件头注释、EMBEDDED_AUDIO、行尾）都会破坏字节一致。

    C7 Task 4：目标文件从 workbench.html 换成 static/js/wb-seed-data.js，断言仍是
    **逐字节等价**（不是「文件存在」），故「内联 const 是构建产物」这条契约继续约束
    真实产物。另加一道往返：注入结果必须能**再解析**回同样的四个值 —— 渲染器与解析器
    互为逆，挡住「字节碰巧相同但语义已歪」的假绿。
    """
    tool = _load_tool()
    mod = _load_dict_module()
    src = _seed_js_text()
    injected = tool.render_source(
        src,
        seed=mod.A1_WORKBENCH_SEED,
        core_ids=mod.A1_WORKBENCH_CORE_IDS,
        custom=mod.A1_WORKBENCH_CUSTOM,
        aliases=mod.A1_WORKBENCH_ID_ALIASES,
    )
    assert injected == src, "注入当前数据模块产生了漂移（不是字节一致）"

    reparsed = tool.parse_source(injected)
    assert reparsed["seed"] == list(mod.A1_WORKBENCH_SEED), "注入结果再解析的种子词与模块不等价"
    assert reparsed["core_ids"] == sorted(mod.A1_WORKBENCH_CORE_IDS), "注入结果再解析的核心词 id 与模块不等价"
    assert reparsed["custom"] == list(mod.A1_WORKBENCH_CUSTOM), "注入结果再解析的核心新词与模块不等价"
    assert reparsed["aliases"] == dict(mod.A1_WORKBENCH_ID_ALIASES), "注入结果再解析的别名表与模块不等价"


def test_injection_is_idempotent():
    """连注两次字节一致 —— 否则每次构建都产生假 diff。"""
    tool = _load_tool()
    mod = _load_dict_module()
    src = _seed_js_text()
    kwargs = dict(
        seed=mod.A1_WORKBENCH_SEED,
        core_ids=mod.A1_WORKBENCH_CORE_IDS,
        custom=mod.A1_WORKBENCH_CUSTOM,
        aliases=mod.A1_WORKBENCH_ID_ALIASES,
    )
    once = tool.render_source(src, **kwargs)
    twice = tool.render_source(once, **kwargs)
    assert once == twice, "注入不幂等（第二次结果与第一次不同）"
    assert once == src, "第一次注入就与当前数据模块不同（幂等的前提是零漂移）"


# ── 4. 服务端消费侧（Task 2 / ADR-0011 红线 2）───────────────────────────
#
# 服务端 `_load_a1_workbench_words()` 必须直接 import 数据模块：
# - 不再正则解析 workbench.html（前端文件不是数据源）；
# - 数据模块缺失/形状坏必须抛清晰异常（不得返回空表、不得静默回退）；
# - 对外输出 `{id, hw, pos, de, zh, core, cefr}` 与改造前逐条一致。

DATABASE_PY = _ROOT / "delector" / "core" / "database.py"

# monkeypatch 数据模块常量用的迷你数据（覆盖 de/zh 两种派生路径 + core/custom 两分支）。
# S1（ADR-0014 §6-S1）起 seed 带 letter（透传原值）：a1-0001 有 "A"、a1-0002 缺键（→ ""）、
# custom core-001 有 "M"。
MINI_SEED: List[Dict[str, Any]] = [
    {
        "id": "a1-0001",
        "hw": "ab",
        "pos": "Präp",
        "gloss": "迷你释义A",
        "ipa": "ˈmiːni",
        "ex": [{"de": "Mini de.", "zh": "迷你中文"}],
        "letter": "A",
    },
    {"id": "a1-0002", "hw": "aber", "pos": "Konj", "zh": "纯zh释义"},
]
MINI_CUSTOM: List[Dict[str, Any]] = [
    {"id": "core-001", "hw": "Miniwort", "pos": "N", "gloss": "迷你新词", "letter": "M"}
]
MINI_CORE_IDS = frozenset({"a1-0001"})

# 改造前（正则解析版）对真实数据模块产出的 20 条样本：前 10 条种子词 + 前 10 条自定义词。
# 由改造前实现现场导出固化于此，钉住"输出逐条不变"。
_SNAPSHOT_FIELDS = ("id", "hw", "pos", "de", "zh", "core", "cefr")
_SNAPSHOT_ROWS = [
    ("a1-0001", "ab", "Präp", "Ab morgen muss ich arbeiten.", "从…起；自…起", False, "A1"),
    ("a1-0002", "aber", "Konj", "Ich bin oft im Büro, aber nur für wenige Stunden.", "但是；可是", False, "A1"),
    ("a1-0003", "abfahren", "V", "Wir fahren um zwölf Uhr ab.", "出发；驶离", True, "A1"),
    ("a1-0004", "die Abfahrt", "f.", "Vor der Abfahrt rufe ich an.", "出发；发车", True, "A1"),
    ("a1-0005", "abgeben", "V", "Ich muss meine Schlüssel abgeben.", "交还；交出", False, "A1"),
    ("a1-0006", "abholen", "V", "Wann kann ich den Schrank bei dir abholen?", "取；接（人/物）", False, "A1"),
    ("a1-0007", "der Absender", "m.", "Da ist ein Brief für dich ohne Absender.", "寄件人", True, "A1"),
    ("a1-0008", "Achtung", "Int", "Achtung! Das dürfen Sie nicht tun.", "注意！当心！", False, "A1"),
    ("a1-0009", "die Adresse,-en", "f.", "Können Sie mir seine Adresse sagen?", "地址", True, "A1"),
    ("a1-0010", "all-", "Pron", "Alles Gute!", "全部；所有（构成 alle, alles 等）", False, "A1"),
    ("core-001", "der Wohnort", "m.", "Mein Wohnort ist Berlin.", "居住地", True, "A1"),
    ("core-002", "die Staatsangehörigkeit", "f.", "Staatsangehörigkeit: Chinesisch.", "国籍", True, "A1"),
    ("core-003", "die Nationalität", "f.", "Meine Nationalität ist chinesisch.", "国籍", True, "A1"),
    ("core-004", "geschieden", "Adj", "Er ist seit gestern geschieden.", "离异的", True, "A1"),
    ("core-005", "verwitwet", "Adj", "Meine Oma ist verwitwet.", "丧偶的", True, "A1"),
    ("core-006", "das Mittagessen", "n.", "Wann gibt es Mittagessen?", "午餐", True, "A1"),
    ("core-007", "das Abendessen", "n.", "Das Abendessen ist fertig.", "晚餐", True, "A1"),
    ("core-008", "der Käse", "m.", "Ein Brötchen mit Käse bitte.", "奶酪", True, "A1"),
    ("core-009", "der Zucker", "m.", "Der Kaffee braucht Zucker.", "糖", True, "A1"),
    ("core-010", "der Stuhl", "m.", "Ist der Stuhl noch frei?", "椅子", True, "A1"),
]
EXPECTED_SNAPSHOT = [dict(zip(_SNAPSHOT_FIELDS, row)) for row in _SNAPSHOT_ROWS]


@pytest.fixture
def fresh_a1_cache():
    """隔离模块级缓存：测试前后都清空，防止迷你数据泄漏给其他测试。"""
    database._reset_a1_workbench_cache()
    yield
    database._reset_a1_workbench_cache()


def test_database_no_longer_references_workbench_html():
    """(a) 源码级：服务端不得再把前端 HTML 当数据源（全文无 workbench.html 字样）。"""
    src = DATABASE_PY.read_text(encoding="utf-8")
    assert "workbench.html" not in src, "database.py 仍引用 workbench.html（必须改 import 数据模块）"


def test_load_reads_data_module_constants(monkeypatch, fresh_a1_cache):
    """(b) 行为级：monkeypatch 数据模块常量后输出随之变化 —— 证明真读模块而非缓存。"""
    import delector.data.a1_workbench_dict as wb_dict

    # mock-drift-ok: 常量是模块公开数据出口；消费方 db/vocab.py:141-143 于调用期经 a1_wb 模块属性读取，补丁即时生效
    monkeypatch.setattr(wb_dict, "A1_WORKBENCH_SEED", MINI_SEED)
    # mock-drift-ok: 消费方 db/vocab.py:141-143 于调用期经 a1_wb 模块属性读取该常量，补丁即时生效
    monkeypatch.setattr(wb_dict, "A1_WORKBENCH_CUSTOM", MINI_CUSTOM)
    # mock-drift-ok: 消费方 db/vocab.py:141-143 于调用期经 a1_wb 模块属性读取该常量，补丁即时生效
    monkeypatch.setattr(wb_dict, "A1_WORKBENCH_CORE_IDS", MINI_CORE_IDS)

    words = database._load_a1_workbench_words()
    assert [w["id"] for w in words] == ["a1-0001", "a1-0002", "core-001"]
    # de 派生：ex[0].de 优先；zh 派生：gloss 优先
    assert words[0]["de"] == "Mini de."
    assert words[0]["zh"] == "迷你释义A"
    assert words[0]["core"] is True  # id ∈ core_ids
    # 无 ex/gloss：de 落空串，zh 落 zh 字段
    assert words[1]["de"] == ""
    assert words[1]["zh"] == "纯zh释义"
    assert words[1]["core"] is False
    # custom 全部 core=True
    assert words[2]["core"] is True
    assert words[2]["zh"] == "迷你新词"
    # S4 新增 ipa / example_zh：ipa 取自 seed 的 ipa（缺则空串）；example_zh 取自 ex[0].zh
    assert words[0]["ipa"] == "ˈmiːni"
    assert words[0]["example_zh"] == "迷你中文"
    assert words[1]["ipa"] == ""  # 无 ipa → 空串
    assert words[1]["example_zh"] == ""  # 无 ex → 空串
    # S7 新增 gender / plural：由 hw 归一化 join lexicon 视图（主干 LEXICON）直取
    # （迷你数据均未命中 → None/""）
    assert words[0]["gender"] is None
    assert words[0]["plural"] == ""
    assert words[2]["gender"] is None  # "Miniwort" 不在官方 A1 分片 → None/""（不编造）
    assert words[2]["plural"] == ""
    # S1 新增 letter：A1 分支 = seed 原值**逐字透传**（不派生）；缺键 → ""
    assert words[0]["letter"] == "A"  # seed a1-0001 带 letter "A"
    assert words[1]["letter"] == ""  # seed a1-0002 缺 letter 键 → ""
    assert words[2]["letter"] == "M"  # custom core-001 带 letter "M"
    for w in words:
        assert set(w.keys()) == {
            "id",
            "hw",
            "pos",
            "gender",
            "plural",
            "de",
            "zh",
            "ipa",
            "example_zh",
            "core",
            "cefr",
            "letter",
        }
        assert w["cefr"] == "A1"


def test_missing_data_module_raises(monkeypatch, fresh_a1_cache):
    """(c) 失败必须炸：数据模块 import 失败 → 抛 RuntimeError，绝不返回空表。"""
    monkeypatch.setitem(sys.modules, "delector.data.a1_workbench_dict", None)
    with pytest.raises(RuntimeError) as ei:
        database._load_a1_workbench_words()
    assert "a1_workbench_dict" in str(ei.value)


def test_bad_shape_raises(monkeypatch, fresh_a1_cache):
    """(c) 失败必须炸：常量形状坏（SEED 非列表）→ 抛 TypeError 而非静默容错。"""
    import delector.data.a1_workbench_dict as wb_dict

    # mock-drift-ok: 消费方 db/vocab.py:141-143 于调用期经模块属性读取，本用例正靠此面炸出 TypeError，补丁即时生效
    monkeypatch.setattr(wb_dict, "A1_WORKBENCH_SEED", "not-a-list")
    with pytest.raises(TypeError) as ei:
        database._load_a1_workbench_words()
    assert "A1_WORKBENCH_SEED" in str(ei.value)


def test_a1_cache_is_reused(fresh_a1_cache):
    """缓存语义保持：同一进程内二次调用直接命中缓存（同一对象）。"""
    first = database._load_a1_workbench_words()
    second = database._load_a1_workbench_words()
    assert second is first


def test_output_snapshot_matches_pre_refactor(fresh_a1_cache):
    """(d) 等价性快照：改造后对同一数据模块的产出与改造前逐条完全一致（20 条样本）。

    S4 起内部行新增 ipa / example_zh 两键（契约 9 → 11）；本快照仍钉住改造前
    ``_SNAPSHOT_FIELDS``（7 个存储行字段）逐条不变 —— 按字段投影比较，既不改快照
    字段集、也不放宽为子集（新两键由 test_load_reads_data_module_constants 单独钉住）。
    """
    words = database._load_a1_workbench_words()
    got = words[:10] + words[-22:-12]  # 前 10 条种子词 + 前 10 条自定义词
    projected = [{k: w[k] for k in _SNAPSHOT_FIELDS} for w in got]
    assert projected == EXPECTED_SNAPSHOT


# ── 5. 投影入口形态与 --extract 护栏（handoff_c7-followups）─────────────────────


def test_a1_workbench_dict_is_projection_module_not_flat_literal_artifact():
    """a1_workbench_dict.py 必须是 membership 投影入口，严禁被生成物覆盖成扁平字面量。

    契约（ADR-0015 T2）：
    - 内容/身份单源在 a1_sidecar，必须显式 import 它；
    - 严禁被 build_workbench_seed.py --extract 覆盖为 760+ 行字面量（正常为 ~45 行）。
    """
    text = DICT_MODULE.read_text(encoding="utf-8")
    assert "from delector.data.a1_sidecar import" in text, (
        "a1_workbench_dict.py 丢失了 a1_sidecar 导入 —— 疑似被 --extract 扁平生成物覆写！"
    )
    assert "WORKBENCH_MEMBERSHIP" in text, "a1_workbench_dict.py 缺少 WORKBENCH_MEMBERSHIP"
    line_count = len(text.splitlines())
    assert line_count < 100, (
        "a1_workbench_dict.py 行数为 %d（期望 <100 行投影入口）：已被生成物覆盖！" % line_count
    )


def test_extract_without_override_flag_refuses_to_overwrite_existing_module(capsys):
    """build_workbench_seed.py --extract 对已存在文件默认必须拒绝执行（退出码非 0 且文件未改动）。"""
    tool = _load_tool()
    mtime_before = DICT_MODULE.stat().st_mtime_ns
    rc = tool.main(["--extract"])
    captured = capsys.readouterr()
    assert rc != 0, "--extract 缺少 --i-know-this-overwrites 时应当拒绝并返回非 0 退出码"
    assert "拒绝执行" in captured.err
    assert "--i-know-this-overwrites" in captured.err
    assert DICT_MODULE.stat().st_mtime_ns == mtime_before, "--extract 不得修改已存在的模块"


def test_extract_with_override_flag_proceeds_in_temp_dir(tmp_path):
    """带 --i-know-this-overwrites 时允许完成 extract 动作（隔离在临时目录测试，不碰主库）。"""
    tool = _load_tool()
    temp_mod = tmp_path / "temp_dict.py"
    temp_mod.write_text("# existing dummy\n", encoding="utf-8")

    # 未带 flag：拒绝
    rc_refuse = tool.main(["--extract", "--module", str(temp_mod)])
    assert rc_refuse != 0
    assert temp_mod.read_text(encoding="utf-8") == "# existing dummy\n"

    # 带 flag：执行生成
    rc_ok = tool.main(["--extract", "--i-know-this-overwrites", "--module", str(temp_mod)])
    assert rc_ok == 0
    content = temp_mod.read_text(encoding="utf-8")
    assert "A1_WORKBENCH_SEED" in content
    assert len(content.splitlines()) > 500

