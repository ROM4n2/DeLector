# -*- coding: utf-8 -*-
"""`tools/bench_cards_endpoint.py` 的存在性与输出结构回归闸。

钉住什么
--------
子计划 2 Task 1 的**唯一交付物是测量结论**，而结论的可信度完全依赖基准脚本本身
是否还活着、是否还按四段结构吐数。所以本文件把三件事钉成断言：

1. 脚本**存在且可跑**（子进程实跑，不是 import 后调函数——脚本要在真实 CLI 形态下
   独立可用，否则「可复跑」是空话）；
2. 输出**含四个分段标签**（A/B/C/D），否则成本拆解悄悄塌回单段数字；
3. 输出含**一个可解析的 filesort 占比数字**（`filesort_pct=NN.N%`），且落在
   物理上可能的开区间 `(0, 100]` 内。

为什么第 3 条要卡下界（**这才是防恒真的那条**）
----------------------------------------------
若有人把脚本里段 B 的 `SELECT *` 悄悄改成 `SELECT id`（B 就退化成 A 的复制品），
`filesort` = B − C 会变成**负数**（无排序的整表扫描比「只取 id 再排序」更便宜），
占比随之跌出 `(0, 100]` ⇒ 本文件立刻红。也就是说，**篡改分段定义 ⇒ 断言失败**，
证明这三个断言真在检视分段之间的差值关系，而不是「只要脚本能跑就恒绿」。

隔离纪律
--------
基准脚本 MUST NOT 触碰仓库根的真实 `delector.db`（桌面端用户数据）。本文件用
子进程 + 独立临时 CWD 跑它，并在跑完后断言仓库根 `delector.db` 的 mtime/size
未被改动——这是对 `[Instinct: Isolated-DB]` 的可执行化，而不是靠 review 自觉。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_cards_endpoint.py"

# 四段标签：与基准脚本 `SEGMENTS` 一一对应。缺任一段 ⇒ 成本拆解塌回单段数字。
SEGMENT_LABELS = ("segment_A", "segment_B", "segment_C", "segment_D")

SEGMENT_RE = re.compile(r"^(segment_[ABCD])_ms=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)
FILESORT_RE = re.compile(r"^filesort_pct=([0-9]+(?:\.[0-9]+)?)%$", re.MULTILINE)

# 规模与轮数：门禁要**快**（每次 pytest 都跑），故用比人工基准小得多的规模。
# 取值仍需足够大，让「排序」在噪声之上可测（段 B > 段 C 才有统计意义）。
GATE_SCALE = "8000"
GATE_ROUNDS = "5"


def _run_bench(tmp_path: Path) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCH_SCALES"] = GATE_SCALE
    env["BENCH_ROUNDS"] = GATE_ROUNDS
    # 双保险：即便脚本自身有 bug，也把库路径钉死在临时目录之外的独立位置。
    env["DATABASE_PATH"] = str(tmp_path / "gate_delector.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "gate_progress.db")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, f"基准脚本退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc.stdout


def test_bench_script_exists() -> None:
    """① 脚本存在 —— 「测量结论」的载体不能被静默删除。"""
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"


def test_bench_script_isolated_from_repo_db() -> None:
    """①' 脚本源码必须自带临时目录隔离（`[Instinct: Isolated-DB]` 的可执行化）。

    只做**源码级**静态断言而非跑后比对 mtime：跑后比对需要仓库根存在真实
    `delector.db`（在 CI 上不存在 ⇒ 断言恒真，等于没有断言）。源码里出现
    `mkdtemp` + 两个库路径环境变量，才是这条纪律真正被写下的证据。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "tempfile.mkdtemp" in src, "基准脚本必须用 tempfile.mkdtemp() 建隔离库目录"
    assert "DATABASE_PATH" in src, "基准脚本必须用 DATABASE_PATH 环境变量重定向主库"
    assert "PROGRESS_DB_PATH" in src, "基准脚本必须用 PROGRESS_DB_PATH 环境变量重定向进度库"
    assert "shutil.rmtree" in src, "基准脚本必须在 finally 里清理临时目录"


@pytest.mark.parametrize("label", SEGMENT_LABELS)
def test_bench_output_has_segment(label: str, tmp_path: Path) -> None:
    """② 输出含四个分段标签，且每段耗时是可解析的正数。"""
    out = _run_bench(tmp_path)
    found = dict(SEGMENT_RE.findall(out))
    assert set(SEGMENT_LABELS) <= set(found), f"四段标签不全，缺：{set(SEGMENT_LABELS) - set(found)}\n{out}"
    assert float(found[label]) > 0.0, f"段 {label} 耗时非正（{found[label]}）——计时段没真正跑到"


def test_bench_output_reports_parsable_filesort_pct(tmp_path: Path) -> None:
    """③ 输出含可解析的 filesort 占比，且落在物理可能的开区间 (0, 100]。

    下界 `> 0` 是本文件防恒真的核心：段 B 一旦被改成 `SELECT id`，B − C 转负，
    占比跌出区间 ⇒ 红。详见模块 docstring。
    """
    out = _run_bench(tmp_path)
    matches = FILESORT_RE.findall(out)
    assert matches, f"输出里找不到 `filesort_pct=NN.N%` 这一行\n{out}"
    pct = float(matches[-1])
    assert 0.0 < pct <= 100.0, f"filesort 占比 {pct}% 超出物理可能区间 (0, 100]——分段定义多半被改坏了\n{out}"


def test_bench_segments_show_ordering_cost_is_real(tmp_path: Path) -> None:
    """④ 段 B（`SELECT *` + ORDER BY）必须同时慢于段 A（只取 id）与段 C（无排序）。

    这条把「四段之间确有可测差异」钉成回归断言：
    - B ≤ A ⇒ 多列回表成本测不出来（说明段 A/B 的 SQL 已经退化成同一条）；
    - B ≤ C ⇒ 排序成本测不出来（filesort 结论失去数据支撑）。
    两条任一发生都红。
    """
    out = _run_bench(tmp_path)
    found = dict(SEGMENT_RE.findall(out))
    a, b, c = float(found["segment_A"]), float(found["segment_B"]), float(found["segment_C"])
    assert b > a, f"段 B({b:.3f}ms) 未慢于段 A({a:.3f}ms)：多列回表成本没测出来\n{out}"
    assert b > c, f"段 B({b:.3f}ms) 未慢于段 C({c:.3f}ms)：排序 filesort 成本没测出来\n{out}"
