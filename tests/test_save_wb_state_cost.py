# -*- coding: utf-8 -*-
"""``tools/bench_save_wb_state.py`` 的可复跑门禁（P1-7：save_wb_state 先量再改）。

量测结论（2026-10-11，2979 词 / 0.88MB payload）：
- blob upsert 单独 ≈ 8.8ms；首存（~3k INSERT）≈ 78ms；日常重复保存（幂等
  unchanged）≈ 46ms；``_pool_index`` 全表 SELECT ≈ 7.2ms。
- **登记：不改**。理由（结构性）：
  1. 日常路径 46ms 低于可感知阈值（50ms），executemany 改造要动 ``_project_word``
     的两条关键不变量（INSERT lastrowid 回填映射 / UPDATE 后同步刷新映射元组），
     且 UPDATE 列集是动态的，executemany 需按列集分组——风险大于收益；
  2. ``_pool_index`` 全表 SELECT 只占 ~7ms（单次、非逐词查库），无可挤水分；
  3. 拆事务/分批提交会破坏"状态要么全有要么全无"的原子性语义——红线，禁改。

本文件钉**结构性事实**（不钉绝对毫秒）：脚本可跑、五段输出可解析、
repeat（幂等路径）不慢于 first（全 INSERT 路径）——后者是"幂等投影零写语句"
的结构必然，若反转说明投影的幂等性被破坏（真回归）。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_save_wb_state.py"

KEYS = ("payload_mb", "words", "segment_blob_ms", "segment_first_ms", "segment_repeat_ms", "segment_pool_index_ms")
NUMERIC_RE = re.compile(
    r"^(" + "|".join(KEYS) + r")=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE
)


def _run_bench(tmp_path: Path) -> str:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATABASE_PATH"] = str(tmp_path / "gate_wb.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "gate_wb_progress.db")
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "gate_wb_data")
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


def test_save_wb_state_bench_parsable(tmp_path: Path) -> None:
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    missing = [k for k in KEYS if k not in found]
    assert not missing, f"输出缺段：{missing}\n{out}"
    for k in ("segment_blob_ms", "segment_first_ms", "segment_repeat_ms", "segment_pool_index_ms"):
        assert float(found[k]) > 0.0, f"段 {k} 非正——计时段没真正跑到\n{out}"


def test_save_wb_state_repeat_not_slower_than_first(tmp_path: Path) -> None:
    """结构性事实：幂等重复保存（几乎全 unchanged、零写语句）不慢于全 INSERT 首存。

    反转 ⇒ 投影幂等性被破坏（repeat 路径又写起来了），或计时口径被改坏。
    """
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    first_ms = float(found["segment_first_ms"])
    repeat_ms = float(found["segment_repeat_ms"])
    assert repeat_ms <= first_ms, (
        f"幂等重复保存({repeat_ms:.1f}ms) 慢于首存({first_ms:.1f}ms)：投影幂等性被破坏？\n{out}"
    )
