# -*- coding: utf-8 -*-
r"""tools/*.mjs 探针「防漏接线」守卫（2026-10-05 清债轮 C 组，本组最重要的产出）。

═══ 为什么需要这条守卫 ═══
`tools/` 下是一批 `.mjs` 行为探针（切真源码进 node:vm 沙箱真跑）。但：

  * pytest 的自动发现只对 `test_*.py` / `*_test.py` 生效，`.mjs` **不是测试**；
  * `tests/` 下没有任何 `rglob("*.mjs")` 式的自动发现机制兜底。

⇒ **一个没有 pytest wrapper 的探针，永远不会进 CI**，它的回归只能在手工门禁里发现。
历史上正是这样漏掉了 8 个探针（2026-10-05 实测：24 个 `.mjs` 里 8 个零引用），
其中包括守「白复习」P0 回归的 `cards_workbench_no_review_probe.mjs`。
本守卫把「漏接线」从事后考古变成**立刻红**。

═══ 判据：为什么用「纯文本子串引用」而不是「引号字面量」 ═══
匹配口径是：某个 `tools/<name>.mjs` 的**文件名**（不含 `.mjs`）是否作为
**纯文本子串**出现在任一 `tests/**/*.py` 的内容里。

试过更严的「必须以引号字面量出现」，但会**误伤既有 16 个已接线的 wrapper**
（实测 QUOTED-MISS 15 个）：它们多以 `PROBE = ROOT / "tools" / "xxx.mjs"` 路径拼接
或注释形式引用，被引号包裹的名字未必独立成词。守卫的职责是「不漏接」，
不是「统一既有 wrapper 的写法」⇒ 采用子串口径，宁松不误伤既有接线。

═══ 排除清单与理由 ═══
本守卫只扫 `tools/`，故下述文件**根本不在扫描范围内**，无需进排除清单：

  * `tests/test_hard_sentences_probe.mjs` —— 长难句精读工坊前端行为探针的
    **runner 本体**（自陈"前端行为探针（红线 11 契约钉死）"），位于 `tests/`
    而非 `tools/`；且已有 Python wrapper `tests/test_hard_sentences_probe.py` 引用它。
  * `tests/test_listen_lab_probe.mjs` —— 听力微训工坊前端行为探针的 runner 本体，
    同上；已有 `tests/test_listen_lab_probe.py` 引用。

`tools/` 下经 2026-10-05 全量核实（逐个 `grep -qi "探针\|probe"`，零命中即非探针，
结果无一例外全部自陈"行为探针"），**24 个 `.mjs` 全是探针**，故 `_NOT_PROBES` 为空。
保留该集合而非删掉：它是"将来有人在 tools/ 放非探针脚本"时的登记位 ——
让新增排除**必须显式改代码**（可 review），而不是靠放宽判据静默通过。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
TESTS_DIR = REPO_ROOT / "tests"

# `tools/` 下**不是**行为探针的文件名（不含 .mjs）。当前为空 —— 见上文的核实记录。
# 键是文件名，值是排除理由（强制写理由，防止将来无声无息地往里塞条目）。
_NOT_PROBES: dict[str, str] = {}

# 探针文件名约定：xxx_probe.mjs。刻意要求 `_probe` 后缀 —— 将来在 tools/ 下放
# 一次性脚本 / 迁移工具时，命名上就不会被误认成"必须有 wrapper 的探针"。
_PROBE_GLOB = "*_probe.mjs"

# 探针文件内容里的自陈标记（用于反向交叉核对，见 test_probe_naming_covers_all_probes）
_SELF_DECLARED = ("探针", "probe")


def _corpus_files() -> list[Path]:
    """tests/ 下参与「已接线证据」的文件，按路径排序。

    **只收 `test_*.py`，刻意不收全部 `*.py`**（2026-10-05 fix-round 修正）：
    pytest 自身的收集规则就是 `test_*.py` / `*_test.py`
    ⇒ **一个不可能被 pytest 收集的文件，本来就不可能是 wrapper**。
    把不参与收集的 helper（`probe_runner.py` / `db_cleanup.py` 之类）计入
    "已接线证据"是逻辑错误 —— 它们不会被 CI 收集，凭什么当 someone's wrapper。

    实测过的真实假绿：原口径下 `tests/probe_runner.py` 的 docstring 点名了某族真实
    探针名，于是 `mv` 走对应真 wrapper 后 `test_every_tools_probe_has_pytest_wrapper`
    **照样绿**。收窄后该探针只剩真 wrapper 引用，删了就红。

    收窄不误伤既有接线的核实（2026-10-05 实测，非推断）：`tools/` 下 24 个
    `*_probe.mjs`，每一个的名字都能在**某个 `test_*.py` 里**查到
    （`ls tests/**/*.py` 全量确认：tests/ 下只有 `db_cleanup.py` 与 `probe_runner.py`
    两个文件不叫 `test_*.py`，二者都是纯 helper，无一个探针引用只靠它们支撑）。
    该核实已固化为 `test_wiring_corpus_excludes_non_test_py_files`。
    """
    return sorted(TESTS_DIR.rglob("test_*.py"))


def _all_tests_py_text() -> str:
    """把 corpus 源（`_corpus_files()`）拼成一个大字符串，供子串匹配。"""
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in _corpus_files()
    )


def _probe_files() -> list[Path]:
    """tools/ 下全部探针文件（已应用排除清单），按文件名排序。"""
    files = sorted(TOOLS_DIR.glob(_PROBE_GLOB))
    return [p for p in files if p.name not in _NOT_PROBES]


def test_every_tools_probe_has_pytest_wrapper() -> None:
    """每个 tools/*_probe.mjs 都 MUST 有 pytest wrapper 引用它，否则本守卫红。

    漏接的后果不是"少测一点"，而是**该探针的契约回归从此只能在手工门禁里发现**：
    它的 `.mjs` 不会进 CI，pytest 的自动发现也扫不到它。
    """
    probes = _probe_files()
    assert probes, f"{TOOLS_DIR} 下没扫到任何 {_PROBE_GLOB}：探针命名约定或目录位置变了？"

    corpus = _all_tests_py_text()
    unwired = [p.name[: -len(".mjs")] for p in probes if p.name[: -len(".mjs")] not in corpus]

    assert not unwired, (
        "以下 tools/ 探针没有任何 pytest wrapper 引用它们，会**永远不进 CI**"
        "（pytest 只发现 test_*.py，tests/ 下也无 .mjs 自动发现机制）：\n"
        + "\n".join(f"  - tools/{n}.mjs" for n in unwired)
        + "\n修法：为每个补一个 tests/test_*.py wrapper（跑 `node tools/X.mjs --json` 并"
        "断言 failures/ok、场景数下界、关键场景名存在），而不是删掉本守卫或加进排除清单。"
    )


def test_guard_still_sees_a_nonempty_probe_corpus() -> None:
    """守卫自身的有效性：必须真的扫到了非空探针集，且排除清单没被悄悄放宽。

    防的是"守卫空转"——若 `tools/` 改名 / 移走导致扫到 0 个探针，
    上面的守卫会恒绿（vacuous pass），等于白写。
    """
    scanned = [p.name for p in _probe_files()]

    assert len(scanned) >= 20, (
        f"守卫只扫到 {len(scanned)} 个探针（{scanned}）："
        "预期 tools/ 下有二十余个 *_probe.mjs。数量骤降说明命名约定或目录变了，"
        "本守卫可能正在空转（vacuous pass）。"
    )
    # 排除清单必须逐条带理由，且条目必须真实存在（死条目会让排除面无声扩大）
    for name, why in _NOT_PROBES.items():
        assert why.strip(), f"排除清单条目 {name!r} 没写理由"
        assert (TOOLS_DIR / name).exists(), (
            f"排除清单里的 {name!r} 在 tools/ 下已不存在：删掉这条死条目，别让排除面无声扩大"
        )


def test_exclusion_list_contains_only_unwired_probes() -> None:
    """排除清单 MUST 只含「确实没有 pytest wrapper」的探针。

    反假绿护栏（2026-10-05 变异验证② 实测踩到）：把一个**已接线**的探针塞进
    `_NOT_PROBES` 时，扫描集虽缩小，但该探针仍被 tests/ 引用 ⇒ `unwired` 仍为空 ⇒
    上一条守卫**照样绿**。即排除清单原本是"往里塞什么都行"的单向门，
    等于给漏接线开了一条静默旁路。

    故补这条：清单里的每个条目都 MUST 在 tests/ 下零引用。已接线的探针被排除 ⇒
    立刻红（要么删掉这条多余排除，要么它本身就是真漏接、该补 wrapper）。
    """
    corpus = _all_tests_py_text()
    wrongly_excluded = [name for name in _NOT_PROBES if name[: -len(".mjs")] in corpus]

    assert not wrongly_excluded, (
        f"排除清单里这些探针其实**已被 tests/ 引用**（已接线）：{wrongly_excluded}\n"
        "把它们排除掉不会让上面那条守卫变红（unwired 仍为空）⇒ 排除清单成了漏接线的静默旁路。\n"
        "修法：从 _NOT_PROBES 里删掉这些条目。排除清单只保留真正没有 wrapper 的非探针文件。"
    )


def test_wiring_corpus_excludes_non_test_py_files() -> None:
    """corpus 源 MUST 只含 `test_*.py`：不参与 pytest 收集的 helper 不是「已接线证据」。

    为什么这条要单独钉住（2026-10-05 fix-round 实测踩到的假绿漏洞）：
    `_all_tests_py_text()` 原本收 `tests/**/*.py`，而 `tests/probe_runner.py` 是抽出来的
    纯 helper，**不叫 `test_*.py`、pytest 不会收集它**。可它的模块 docstring 里点了
    真实探针名的族 ⇒ 那些名字在 corpus 里"被提到" ⇒ 守卫把它们误判成"已接线"。
    实测：把某个真 wrapper 整个移走，`test_every_tools_probe_has_pytest_wrapper`
    **照样绿**（真 wrapper 已经不在 CI 里了，漏接线静默逃逸）。

    判据本身也站在同一条逻辑上：pytest 的收集规则就是 `test_*.py` / `*_test.py`
    ⇒ **一个不可能被 pytest 收集的文件，本来就不可能是 wrapper**。把 helper
    （`probe_runner.py` / `db_cleanup.py` 之类）计入"已接线证据"是逻辑错误。

    这条守卫是防"将来有人把 glob 放宽回 `*.py`"——看着更"通用"，实际是给假绿开门。
    """
    sources = _corpus_files()
    names = {p.name for p in sources}

    non_test_py = sorted(
        p.name
        for p in sources
        if not p.name.startswith("test_") and not p.name.endswith("_test.py")
    )
    assert not non_test_py, (
        f"corpus 源里混进了非 `test_*.py` 的 .py：{non_test_py}\n"
        "后果：这些文件**不会被 pytest 收集**，它们的 docstring / 注释里哪怕只是"
        "'提到'某个探针名，也会让漏接线守卫误判成'已接线'⇒ 删掉真 wrapper 也不红。\n"
        "修法：把 `_corpus_files()` 的 glob 收窄回 `test_*.py`，"
        "并把 helper 文档里的真实探针名改成 `<family>_probe` 之类的占位形式。"
    )
    # 定点钉住被点名的那个 helper：它是这个漏洞的真实来源，名字写死防"换个文件再犯"
    assert "probe_runner.py" not in names, (
        "corpus 源里又出现了 tests/probe_runner.py（纯 helper，不叫 test_*.py）："
        "它的模块 docstring 分类说明会点名真实探针名 ⇒ 文档即证据 ⇒ 漏接线守卫假绿"
    )


def test_probe_naming_covers_all_self_declared_probes() -> None:
    """反向交叉核对：自陈「探针」却不叫 `*_probe.mjs` 的文件，不该存在。

    若将来有人在 `tools/` 放一个自陈"探针"却改了命名的文件，上面的 glob 会扫不到它
    ⇒ 漏接线照样逃逸。这里按文件内容里的自陈标记交叉核对，把命名漂移也暴露出来。
    """
    offenders: list[str] = []
    for path in sorted(TOOLS_DIR.glob("*.mjs")):
        if path.name in _NOT_PROBES:
            continue
        if not path.name.endswith("_probe.mjs"):
            head = path.read_text(encoding="utf-8", errors="replace")[:2000].lower()
            if any(marker.lower() in head for marker in _SELF_DECLARED):
                offenders.append(path.name)

    assert not offenders, (
        f"以下 tools/*.mjs 自陈是探针、却不叫 *_probe.mjs，会被本守卫的 glob 漏掉："
        f"{offenders}\n修法：改名为 xxx_probe.mjs，或在 _NOT_PROBES 里登记并写明理由。"
    )
