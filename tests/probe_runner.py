# -*- coding: utf-8 -*-
"""tools/*.mjs 行为探针的 pytest 接线共用件（2026-10-05 清债轮 C 组）。

背景：仓库的 `tools/` 下有一批 `.mjs` 行为探针（切真源码进 node:vm 沙箱真跑）。
历史上只有一部分被 pytest wrapper 引用，其余**永远不会进 CI**（`tests/` 的
自动发现只对 `test_*.py` 生效，`.mjs` 本身不是测试）⇒ 回归只能在手工门禁里发现。
本模块把「跑探针 --json → 校验输出形状」这段**完全同构**的样板抽成一处，
避免每个 wrapper 各抄一份 `_run_probe`（七份副本改一处漏一处 = 静默漂移）。

本文件**刻意不叫 `test_*.py`**，且不含任何 `test_` 前缀函数 ⇒ pytest 不会收集它，
它是纯 helper（同 `tests/db_cleanup.py` 的既有做法）。

═══ 关于探针输出形状的重要事实 ═══
`--json` 的输出契约并**不统一**。实测 24 个探针分三类：

  A. 标准契约 `{ok, failures, total, cases:[{name, ok}], samples}`
     —— 仅 4 个（cards_wb_source / cards_workbench_no_review / wb_enc_i1 /
        wb_enc_read）。判据用 `failures == 0` + `total >= N` + `cases[].name`。
  B. 扁平「场景名 → 一句人话」：`{ok, "A": "...", "B": "..."}`
     —— 如 enc_known_same_source / enc_open_race / enc_popover_clamp。
        顶层键**就是**场景名，值为该场景的自陈。
  C. 扁平「探针结论」：`{ok, <若干布尔/结构字段>}`
     —— 如 cards_count_probe / wb_rtc_* / wb_pair_persist。顶层键是被测维度。

B/C 两类**没有** `failures` / `total` / `cases` 字段。因此本模块的
`assert_probe_clean` 对 A 类断言 `failures == 0`，对 B/C 类断言 `ok is True`。

**为什么 `ok is True` 够严格（不是放水）**：B/C 类探针的裁决逻辑一律是
「problems 非空 → 写 stderr 并 `process.exit(1)`；problems 为空才构造
`out = { ok: true, ... }`」。即 `ok` 字段**只有全绿时才存在**，
`ok is True` 与 `failures == 0` 严格等价，且 `run_json_probe` 额外断言了
`returncode == 0`（契约破坏时退出码 1），合起来比只看 `failures` 更紧。

`scenario_keys` 把三类统一成「场景名集合」，让各 wrapper 的
「防删场景换全绿」守卫写起来一致：有 `cases` 就取 `cases[].name`，
否则取顶层键（去掉恒为真的 `ok`）。这样 B 类的场景名与 C 类的被测维度
都能被同一条 `>= N` / 关键名存在性断言覆盖。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent
TOOLS_DIR = ROOT / "tools"


def require_node() -> None:
    """node 不在 PATH 上就 skip。

    刻意 skip 而非 fail：本地开发机可能没装 node（纯 Python 改动不该因此红），
    但 CI 上 node 由 `.github/workflows/ci.yml` 的 setup-node 步骤**显式**装上
    （消除对 runner 预装的隐式依赖），所以 CI 上这条 skip 不会成为逃逸口。
    """
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过 .mjs 动态探针")


def probe_path(probe_name: str) -> Path:
    """返回 `tools/<probe_name>.mjs` 的路径（调用方 MUST NOT 传扩展名）。"""
    return TOOLS_DIR / f"{probe_name}.mjs"


def run_json_probe(probe_name: str) -> dict[str, Any]:
    """跑 `node tools/<probe_name>.mjs --json` 并返回解析后的输出。

    三道关：
      1. 探针文件存在（缺失 ⇒ 报清是哪个探针，不是 node 的问题）；
      2. 退出码 0（契约破坏时探针 exit 1，详情在 stderr）；
      3. stdout 是合法 JSON（探针写坏输出时给出 stdout/stderr 前 500 字）。
    """
    probe = probe_path(probe_name)
    assert probe.exists(), f"缺少 tools/{probe_name}.mjs 动态探针（文件缺失，无法接线）"

    res = subprocess.run(
        ["node", str(probe), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, (
        f"探针 {probe_name} 执行失败（退出码 {res.returncode}）：\n{res.stdout}\n{res.stderr}"
    )
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"探针 {probe_name} 的 --json 输出不是合法 JSON：{exc}\n"
            f"stdout(前 500 字):\n{res.stdout[:500]}\nstderr(前 500 字):\n{res.stderr[:500]}"
        ) from exc
    assert isinstance(out, dict), f"探针 {probe_name} 的 --json 输出顶层不是对象：{type(out)!r}"
    return out


def assert_probe_clean(probe_name: str, out: dict[str, Any]) -> None:
    """断言「探针自陈全绿」。

    A 类（带 `cases`）走标准契约的 `failures == 0`；B/C 类断言 `ok is True`
    （见模块 docstring：这两个字段在 B/C 类里是等价的，且 exit 码已另行断言）。
    """
    if "failures" in out:
        assert out["failures"] == 0, f"探针 {probe_name} 有失败场景：{out.get('cases')!r}"
    else:
        assert out.get("ok") is True, (
            f"探针 {probe_name} 未自陈通过（缺 ok:true 字段）：{sorted(out)}"
        )


def scenario_keys(out: dict[str, Any]) -> set[str]:
    """抽出「场景名集合」，把 A / B / C 三类输出形状统一。

    - A 类（`cases` 是 list of {name, ok}）⇒ 取 `cases[].name`；
    - B / C 类 ⇒ 取顶层键，去掉恒为真的 `ok`（它不是场景，是裁决结果）。
    """
    cases = out.get("cases")
    if isinstance(cases, list):
        return {str(c["name"]) for c in cases if isinstance(c, dict) and "name" in c}
    return {k for k in out if k != "ok"}


def assert_scenarios_present(
    probe_name: str,
    out: dict[str, Any],
    needles: tuple[str, ...],
    *,
    exact: bool = True,
) -> None:
    """断言关键场景名仍然存在（防「删掉关键场景换全绿」）。

    `exact=True` 时按场景名**逐字**相等匹配（场景名形如 `A` / `A1-工作台词不渲染DSR复习按钮`
    这类稳定标识，逐字钉死最严）；`exact=False` 时退化为子串包含。
    """
    keys = scenario_keys(out)
    if exact:
        missing = [n for n in needles if n not in keys]
    else:
        missing = [n for n in needles if not any(n in k for k in keys)]
    assert not missing, f"探针 {probe_name} 缺少关键场景 {missing}，现有场景：{sorted(keys)}"
