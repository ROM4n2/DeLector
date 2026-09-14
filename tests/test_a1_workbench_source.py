# -*- coding: utf-8 -*-
"""A1 工作台词库单一真相（Task 1 / ADR-0011）。

- 单一真相 = ``delector/data/a1_workbench_dict.py``（本测试按路径加载，不复用其代码）。
- ``static/german/workbench.html`` 内联的四个 ``const`` 是它的**构建产物**，
  由 ``tools/build_workbench_seed.py`` 注入。

本测试钉住三件事（行为断言，非整文件字符串存在性）：
1. 模块四个常量存在且条数/内容精确（682 / 213 / 22 / 别名表精确映射）；
2. 模块 ↔ HTML 内联块**双向 JSON 等价**（数组逐条 + id 顺序；核心词集合按升序）；
3. 注入**幂等**，且对当前 HTML **零漂移**（注入一遍与原文件字节一致）——
   否则每次构建都产生假 diff，"HTML 是构建产物"这句话就落不了地。
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parent.parent
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


def _html_text() -> str:
    return WORKBENCH_HTML.read_text(encoding="utf-8")


def _html_const(name: str, open_ch: str, close_ch: str):
    """真解析 workbench.html 里的某个 `const <name> = <literal>`。"""
    text = _html_text()
    decl = "const " + name
    assert decl in text, "workbench.html 缺少 %s 常量" % decl
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


# ── 2. 模块 ↔ HTML 双向等价 ─────────────────────────────────────────────


def test_seed_module_equals_html_inline_verbatim():
    """种子词逐条 JSON 等价，且 id 顺序一致（顺序变了 = 页面词序变 = 行为变）。"""
    mod = _load_dict_module()
    html_seed = _html_const("SEED_WORDS", "[", "]")
    assert [w["id"] for w in mod.A1_WORKBENCH_SEED] == [w["id"] for w in html_seed], (
        "模块与 HTML 的种子词 id 顺序不一致"
    )
    assert mod.A1_WORKBENCH_SEED == html_seed, "模块与 HTML 的种子词内容不等价"


def test_custom_module_equals_html_inline_verbatim():
    """核心新词逐条 JSON 等价，且 id 顺序一致。"""
    mod = _load_dict_module()
    html_custom = _html_const("CORE_CUSTOM_WORDS", "[", "]")
    assert [w["id"] for w in mod.A1_WORKBENCH_CUSTOM] == [w["id"] for w in html_custom], (
        "模块与 HTML 的核心新词 id 顺序不一致"
    )
    assert mod.A1_WORKBENCH_CUSTOM == html_custom, "模块与 HTML 的核心新词内容不等价"


def test_core_ids_module_equals_html_inline_sorted():
    """核心词 id 集合等价，且 HTML 内联顺序正是升序（Set 无序，用升序钉住书写顺序）。"""
    mod = _load_dict_module()
    html_core = _html_const("CORE_WORD_SEED_IDS", "[", "]")
    assert sorted(mod.A1_WORKBENCH_CORE_IDS) == html_core, "模块与 HTML 的核心词 id 集合/顺序不一致"


def test_aliases_module_equals_html_inline():
    """别名表与 HTML 内联块等价。"""
    mod = _load_dict_module()
    assert mod.A1_WORKBENCH_ID_ALIASES == _html_const("SEED_ID_ALIASES", "{", "}"), (
        "模块与 HTML 的别名表不一致"
    )


# ── 3. 构建工具：抽取 / 注入 ─────────────────────────────────────────────


def test_extract_is_faithful_to_module_constants():
    """工具 parse_html(当前 HTML) 必须等于模块四个常量 —— --extract 是逐字搬运。"""
    tool = _load_tool()
    parsed = tool.parse_html(_html_text())
    mod = _load_dict_module()
    assert parsed["seed"] == mod.A1_WORKBENCH_SEED
    assert parsed["core_ids"] == sorted(mod.A1_WORKBENCH_CORE_IDS)
    assert parsed["custom"] == mod.A1_WORKBENCH_CUSTOM
    assert parsed["aliases"] == mod.A1_WORKBENCH_ID_ALIASES


def test_injection_into_current_html_is_byte_identical():
    """用模块反向注入当前 HTML：必须字节一致（零漂移，HTML 确为模块的构建产物）。

    这条同时钉住"注入不得触碰 HTML 其他任何部分"：任何多改/少改都会破坏字节一致。
    """
    tool = _load_tool()
    mod = _load_dict_module()
    html = _html_text()
    injected = tool.render_html(
        html,
        seed=mod.A1_WORKBENCH_SEED,
        core_ids=mod.A1_WORKBENCH_CORE_IDS,
        custom=mod.A1_WORKBENCH_CUSTOM,
        aliases=mod.A1_WORKBENCH_ID_ALIASES,
    )
    assert injected == html, "注入当前 HTML 产生了漂移（不是字节一致）"


def test_injection_is_idempotent():
    """连注两次字节一致 —— 否则每次构建都产生假 diff。"""
    tool = _load_tool()
    mod = _load_dict_module()
    html = _html_text()
    kwargs = dict(
        seed=mod.A1_WORKBENCH_SEED,
        core_ids=mod.A1_WORKBENCH_CORE_IDS,
        custom=mod.A1_WORKBENCH_CUSTOM,
        aliases=mod.A1_WORKBENCH_ID_ALIASES,
    )
    once = tool.render_html(html, **kwargs)
    twice = tool.render_html(once, **kwargs)
    assert once == twice, "注入不幂等（第二次结果与第一次不同）"
