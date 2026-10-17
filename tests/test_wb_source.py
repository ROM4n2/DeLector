"""tests/wb_source.py 的单测（C7 · Task 1：探针读取公共层）。

计划 Task 1 点名要覆盖的四件事：

  1. **Fail-Loud** —— 标记缺失 ⇒ 抛 AssertionError，且错误信息里带**所查标记原文**。
     禁止返回空串：空串会让下游 `assert "x" in segment(...)` 静默通过（假绿，红线 11）。
  2. **read_source** 多文件按**给定顺序**拼接（拆分后跨文件锚定用）。
  3. **decl_body** 大括号配平：嵌套函数正确、注释 / 字符串 / 模板插值里的花括号不干扰。
  4. **same_line** 边界：同行 / 不同行 / 首标记缺失 ⇒ 抛（不是静默 False）。

另测两个为「判别力只许升不许降」而新增的辅助：
**depth_at**（顶层语句 vs 嵌在块里）、**occurs_before**（A 类相对位置序的结构化写法）。
"""

from pathlib import Path

import pytest
import wb_source

# ── 固定样本（行下标见右侧注释，断言里的数字都指它）──────────────────────────
# 0  const A = 1;
# 1  function outer() {
# 2    const s = "{ not a brace }";   // } 也不是
# 3    function inner() {
# 4      return { k: 1 };
# 5    }
# 6    return inner();
# 7  }
# 8  const B = 2;
SAMPLE = (
    "const A = 1;\n"
    "function outer() {\n"
    '  const s = "{ not a brace }";   // } 也不是\n'
    "  function inner() {\n"
    "    return { k: 1 };\n"
    "  }\n"
    "  return inner();\n"
    "}\n"
    "const B = 2;\n"
)

# ── read_source ─────────────────────────────────────────────────────────────


def test_read_source_missing_file_raises(tmp_path: Path) -> None:
    """缺失必须炸，且错误信息带文件名 —— 不许退化成空串让下游静默通过。"""
    with pytest.raises(FileNotFoundError) as exc:
        wb_source.read_source(str(tmp_path / "nope.js"))
    assert "nope.js" in str(exc.value)


def test_read_source_concatenates_in_given_order(tmp_path: Path) -> None:
    """多文件必须按**实参顺序**拼接：拆分后跨文件锚定依赖这个顺序契约。"""
    a = tmp_path / "a.js"
    b = tmp_path / "b.js"
    a.write_text("AAA", encoding="utf-8")
    b.write_text("BBB", encoding="utf-8")
    assert wb_source.read_source(str(a), str(b)) == "AAA\nBBB"
    assert wb_source.read_source(str(b), str(a)) == "BBB\nAAA"


def test_read_source_single_file_reads_whole_text(tmp_path: Path) -> None:
    p = tmp_path / "x.js"
    p.write_text("const a = 1;\nconst b = 2;\n", encoding="utf-8")
    assert wb_source.read_source(str(p)) == "const a = 1;\nconst b = 2;\n"


def test_read_source_relative_path_falls_back_to_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CWD 未命中 ⇒ 回落到仓库根 —— 探针不该依赖「必须从仓库根跑 pytest」。

    比照对象是 `tests/wb_source.py` **自身**（本仓必有），断言的是**整份文本相等**，
    不牵扯任何第三方配置文件的内容 —— ruff 配置搬进 pyproject / 改名 / 去掉
    line-length 都不会让这条自测红（红因只可能是读取层，不会污染后续 Task 的红因归因）。

    注：`_resolve` 是 **CWD 优先**，所以在 CWD 里放同名诱饵**测不到**回落（会被 CWD
    命中）；要测回落必须让 CWD **没有**该文件 —— 故这里 chdir 到空的 tmp 目录。
    """
    monkeypatch.chdir(tmp_path)  # CWD 里没有 tests/ ⇒ 只能靠回落到仓库根命中
    expected = (wb_source.REPO_ROOT / "tests/wb_source.py").read_text(encoding="utf-8")
    assert wb_source.read_source("tests/wb_source.py") == expected


# ── segment ─────────────────────────────────────────────────────────────────


def test_segment_returns_text_between_markers() -> None:
    seg = wb_source.segment(SAMPLE, "const A = 1;", "const B = 2;")
    assert "function outer()" in seg
    assert "function inner()" in seg
    assert "const A = 1;" not in seg
    assert "const B = 2;" not in seg


def test_segment_missing_start_marker_raises_and_prints_marker() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.segment(SAMPLE, "<<NO_SUCH_START>>", "const B = 2;")
    assert "<<NO_SUCH_START>>" in str(exc.value)


def test_segment_missing_end_marker_raises_and_prints_marker() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.segment(SAMPLE, "const A = 1;", "<<NO_SUCH_END>>")
    assert "<<NO_SUCH_END>>" in str(exc.value)


def test_segment_inverted_markers_raise_instead_of_empty_string() -> None:
    """结束标记在起始标记之前 ⇒ 必须抛。返回空串会让下游存在性断言静默假绿。"""
    with pytest.raises(AssertionError):
        wb_source.segment(SAMPLE, "const B = 2;", "const A = 1;")


# ── decl_body ───────────────────────────────────────────────────────────────


def test_decl_body_balances_nested_functions() -> None:
    """外层体的配对不得被内层函数的花括号提前闭合，也不得一路吃到文件尾。"""
    body = wb_source.decl_body(SAMPLE, "function outer()")
    assert "function inner()" in body  # 嵌套函数在外层体内
    assert "return inner();" in body  # 外层体的最后一条语句仍在体内
    assert "const B = 2;" not in body  # 没越过外层体的右花括号
    assert "const A = 1;" not in body


def test_decl_body_of_inner_function_stops_at_its_own_brace() -> None:
    """内层体的右花括号不得被误认成外层的 —— 体必须正好是那一条 return。"""
    body = wb_source.decl_body(SAMPLE, "function inner()")
    assert body.strip() == "return { k: 1 };"


def test_decl_body_ignores_braces_in_strings_and_comments() -> None:
    """字符串 / 注释里的**不成对**花括号不得干扰配平（朴素计数会在此切歪）。

    `"{{{"` 净 +3、`// }}` 净 -2、`/* { */` 净 +1 —— 朴素计数扫到文本尾都回不到 0。
    """
    src = (
        "function f() {\n"
        '  const s = "{{{";            // }}\n'
        "  /* { 块注释里的半个花括号 */\n"
        "  return s;\n"
        "}\n"
        "const AFTER = 1;\n"
    )
    body = wb_source.decl_body(src, "function f()")
    assert "return s;" in body
    assert "const AFTER = 1;" not in body


def test_decl_body_balances_template_interpolation() -> None:
    """模板插值 `${ ... }` 里的花括号要计入配平，模板外的 `//` 注释仍要跳过。"""
    src = (
        "function f() {\n"
        "  const t = `x${ obj.k }y`;  // ${} 这里的花括号是注释\n"
        "  return t;\n"
        "}\n"
        "const Z = 9;\n"
    )
    body = wb_source.decl_body(src, "function f()")
    assert "const t = " in body
    assert "return t;" in body
    assert "const Z = 9;" not in body


def test_decl_body_missing_decl_raises_and_prints_decl() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.decl_body(SAMPLE, "function nope()")
    assert "function nope()" in str(exc.value)


def test_decl_body_without_opening_brace_raises_and_prints_decl() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.decl_body(SAMPLE, "const B = 2;")
    assert "const B = 2;" in str(exc.value)


def test_decl_body_unbalanced_raises_and_points_back_to_decl() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.decl_body("function f() {\n  return 1;\n", "function f()")
    assert "function f()" in str(exc.value)


# ── line_of / same_line ─────────────────────────────────────────────────────


def test_line_of_returns_line_index_of_first_match() -> None:
    assert wb_source.line_of(SAMPLE, "function inner()") == 3


def test_line_of_start_offset_skips_earlier_matches() -> None:
    """`return` 首次在第 4 行；从第 5 行起查必须命中第 6 行。"""
    assert wb_source.line_of(SAMPLE, "return", start=5) == 6


def test_line_of_missing_needle_raises_and_prints_needle() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.line_of(SAMPLE, "<<NOPE>>")
    assert "<<NOPE>>" in str(exc.value)


def test_same_line_true_when_b_sits_on_the_line_of_a() -> None:
    assert wb_source.same_line(SAMPLE, "function inner() {", "inner()") is True


def test_same_line_false_when_b_sits_on_another_line() -> None:
    assert wb_source.same_line(SAMPLE, "function outer() {", "function inner()") is False


def test_same_line_missing_a_raises_instead_of_silent_false() -> None:
    """首标记缺失时静默返回 False 会让 `assert not same_line(...)` 反向假绿。"""
    with pytest.raises(AssertionError) as exc:
        wb_source.same_line(SAMPLE, "<<NOPE>>", "anything")
    assert "<<NOPE>>" in str(exc.value)


# ── depth_at ────────────────────────────────────────────────────────────────


def test_depth_at_top_level_statement_is_zero() -> None:
    body = "  if (A) return;\n  localStorage.setItem(K.words, JSON.stringify(S.words));\n  wbsync.push();\n"
    assert wb_source.depth_at(body, body.index("wbsync.push()")) == 0


def test_depth_at_inside_callback_is_one() -> None:
    """推进行被塞进回调 ⇒ 不再是「保存即推」，深度必须把它抓出来。"""
    body = "  setTimeout(() => {\n    wbsync.push();\n  }, 0);\n"
    assert wb_source.depth_at(body, body.index("wbsync.push()")) == 1


def test_depth_at_ignores_braces_inside_string_literals() -> None:
    body = '  const s = "}}";\n  wbsync.push();\n'
    assert wb_source.depth_at(body, body.index("wbsync.push()")) == 0


# ── occurs_before ───────────────────────────────────────────────────────────


def test_occurs_before_true_when_needle_precedes_marker() -> None:
    assert wb_source.occurs_before("S.words = 1; wbsync.push(); await sync();", "wbsync.push()", "await") is True


def test_occurs_before_false_when_needle_follows_marker() -> None:
    assert wb_source.occurs_before("await sync(); wbsync.push();", "wbsync.push()", "await") is False


def test_occurs_before_true_when_marker_absent() -> None:
    """没有 await 就无从「推晚于 IO」，视为满足（不是缺失导致的假绿）。"""
    assert wb_source.occurs_before("wbsync.push();", "wbsync.push()", "await") is True


def test_occurs_before_missing_needle_raises_and_prints_needle() -> None:
    with pytest.raises(AssertionError) as exc:
        wb_source.occurs_before("await sync();", "wbsync.push()", "await")
    assert "wbsync.push()" in str(exc.value)
