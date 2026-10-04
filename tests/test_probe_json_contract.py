# -*- coding: utf-8 -*-
r"""`tools/*_probe.mjs` 的 `--json` 契约守卫（冻结轮）。

═══ 守卫什么 ═══
**新增探针即标准**：不在 `LEGACY_NONSTANDARD` 过渡清单里的探针，MUST 输出**精确**
`{failures, total, cases}`。多一个键（超集）/ 少一个键 / 键名走形（`fail` 代替
`failures`）/ 扁平业务键 —— 一律红。

═══ 判的是实跑输出，不是源码文本 ═══
每条判定都先 `node tools/X.mjs --json` 真跑一遍再取顶层键：改注释、改源码里的
字样、改 docstring 都影响不了判定结果；只有真正改掉 stdout 上的 JSON 才会红。
（变异验证③ 就是按这条设计的：改的是探针**吐出的对象**，不是它的注释。）

═══ 为什么清单「只减不增」 ═══
过渡清单是**显式豁免位**。若允许它变长，"冻结"就会退化成"永久豁免"：任何人加
一个新探针都可以随手登记进去。故条目数 MUST NOT 超过 `LEGACY_BASELINE_COUNT`，
且每个条目 MUST 真的是非标准（将来某个探针被迁移成标准，它 MUST 从清单里删掉）。
"""

from __future__ import annotations

from typing import Any

import pytest
from probe_json_contract import (
    LEGACY_BASELINE_COUNT,
    LEGACY_NONSTANDARD,
    LEGACY_REASONS,
    STANDARD_KEYS,
    TOOLS_DIR,
    probe_names,
    run_probe_json,
)
from probe_runner import require_node

# 守卫自身的有效性下界：扫不到这么多探针说明命名约定 / 目录变了，守卫在空转
_MIN_PROBE_COUNT = 20


@pytest.fixture(scope="session")
def probe_outputs() -> dict[str, dict[str, Any]]:
    """逐个实跑所有探针，返回 `{探针名: 解析后的输出}`（session 内只跑一遍）。"""
    require_node()
    names = probe_names()
    assert len(names) >= _MIN_PROBE_COUNT, (
        f"只扫到 {len(names)} 个探针（{names}）：预期 tools/ 下有二十余个 "
        "*_probe.mjs。数量骤降说明命名约定或目录变了，本守卫可能正在空转。"
    )
    return {name: run_probe_json(name) for name in names}


def test_unregistered_probes_emit_standard_contract(
    probe_outputs: dict[str, dict[str, Any]],
) -> None:
    """不在过渡清单里的探针 MUST 输出精确 `{failures, total, cases}`。

    这是本轮的核心断言：新增探针即标准。超集（多了 `ok` / `samples`）、
    `fail` 代替 `failures`、扁平业务键 —— 都是非标准，都会被这条钉住。
    """
    offenders: dict[str, list[str]] = {}
    for name, out in probe_outputs.items():
        if name in LEGACY_NONSTANDARD:
            continue
        keys = frozenset(out)
        if keys != STANDARD_KEYS:
            offenders[name] = sorted(keys)

    assert not offenders, (
        "以下探针**不在**过渡清单里，却没输出标准契约 "
        f"{sorted(STANDARD_KEYS)}（实测顶层键附后）：\n"
        + "\n".join(f"  - tools/{n}.mjs → {sorted(keys)}" for n, keys in sorted(offenders.items()))
        + "\n修法二选一：① 把该探针的 --json 改成标准三键（**同时**改其 wrapper）；"
        "② 确认是存量后登记进 tests/probe_json_contract.py 的 LEGACY_NONSTANDARD 并写明理由。"
        "\n（注意：登记只减不增 —— 新增探针请走①。）"
    )


def test_legacy_list_must_not_grow() -> None:
    """过渡清单长度 MUST NOT 超过冻结基线 —— 否则"登记"会退化成永久豁免。

    变异验证② 实测：往清单里塞一个**不存在的**探针名，本条立刻红
    （23 → 24 > 23），把"虚增清单"挡在门外。
    """
    assert len(LEGACY_NONSTANDARD) <= LEGACY_BASELINE_COUNT, (
        f"过渡清单有 {len(LEGACY_NONSTANDARD)} 条，超过冻结基线 {LEGACY_BASELINE_COUNT}："
        f"{sorted(LEGACY_NONSTANDARD)}\n"
        "过渡清单**只减不增**：新增探针 MUST 直接写标准契约，不许登记。"
        "若确有存量需要登记，应先把等量（或更多）的条目迁移成标准后从清单删掉，"
        "再下调 LEGACY_BASELINE_COUNT —— 净长度不许涨。"
    )


def test_legacy_entries_are_real_reasoned_and_not_dead() -> None:
    """清单每条 MUST：文件真实存在 + 理由非空 + 理由表无游离条目。

    存在性检查是变异验证② 的第二道锁：凭空编一个探针名塞进来，
    连 `tools/<name>.mjs` 都不存在 ⇒ 当场红。
    """
    for name in sorted(LEGACY_NONSTANDARD):
        assert (TOOLS_DIR / f"{name}.mjs").exists(), (
            f"过渡清单里的 {name!r} 在 tools/ 下并不存在：删掉这条幽灵条目，"
            "别让过渡面无声扩大"
        )
        why = LEGACY_REASONS.get(name, "").strip()
        assert why, f"过渡清单条目 {name!r} 没写登记理由（无理由的登记 = 永久豁免）"

    dead = sorted(set(LEGACY_REASONS) - LEGACY_NONSTANDARD)
    assert not dead, (
        f"LEGACY_REASONS 里有过渡清单中不存在的游离条目：{dead}\n"
        "它们不会让任何断言变红（清单里没有对应的探针），纯属死代码 —— 删掉。"
    )


def test_legacy_entries_are_actually_nonstandard(
    probe_outputs: dict[str, dict[str, Any]],
) -> None:
    """清单里的每个探针 MUST 真的非标准 —— 反向锁死「只减不增」。

    将来某个存量探针被迁移成标准三键后，它**必须**从清单里删掉，否则本条红。
    没有这条，清单就会变成"登记过就永远豁免"的单向门。
    """
    already_standard = sorted(
        name
        for name in LEGACY_NONSTANDARD
        if name in probe_outputs and frozenset(probe_outputs[name]) == STANDARD_KEYS
    )

    assert not already_standard, (
        f"以下探针已输出标准契约 {sorted(STANDARD_KEYS)}，却仍留在过渡清单里："
        f"{already_standard}\n"
        "过渡清单只减不增：从 LEGACY_NONSTANDARD 与 LEGACY_REASONS 里删掉它们。"
    )


def test_every_probe_emits_a_json_object(
    probe_outputs: dict[str, dict[str, Any]],
) -> None:
    """全部探针都真跑成功并吐出 JSON 对象 —— 否则上面的判定会在空集上假绿。"""
    assert len(probe_outputs) >= _MIN_PROBE_COUNT, (
        f"只实跑成功 {len(probe_outputs)} 个探针，契约判定可能建立在空集上"
    )
    for name, out in probe_outputs.items():
        assert isinstance(out, dict), f"探针 {name} 的 --json 顶层不是对象：{type(out)!r}"
