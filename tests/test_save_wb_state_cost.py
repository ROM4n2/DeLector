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

本文件钉**结构性事实**（不钉绝对毫秒）：脚本可跑、输出可解析、
repeat（幂等路径）不慢于 first（全 INSERT 路径）——后者是"幂等投影零写语句"
的结构必然，若反转说明投影的幂等性被破坏（真回归）。

2026-11-05 flake 复盘（run 41960965296 / unit-4）：`repeat 39.188ms > first 37.527ms`
（+4.4%）随机红。原因：**耗时差是存储性能的函数，不是幂等性的函数** ——
Windows 审计机 `INSERT` 较慢（本地 20 轮实测 repeat/first = 0.594–0.844，中位 0.633），
而 Linux CI 的 tmpfs/ext4 让 ~3k INSERT 变得很便宜，两段耗时收敛到同一量级，
单次中位数的噪声即可反转方向。因此：
- 计时断言保留（阈值显式放宽到 first 的 1.25×，依据见断言处注释），负责"日常路径明显变慢"；
- 幂等性改由**环境无关的写语句条数**钉死（repeat 只允许 1 条 wb_state blob upsert，
  first ≥ words 条）——这才是"投影幂等性被破坏"的直接证据。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_save_wb_state.py"

#: 子进程驱动：把迁移闸看到的「旧位置」换成 tmp 空目录，再原样执行基准脚本。
#: 成本基准只该量 save_wb_state 的耗时与写语句条数，不该依赖开发者仓库根有没有本地库；
#: 而 ``preflight_data_dir(DATA_DIR, _REPO_ROOT)`` 的 ``_REPO_ROOT`` 由脚本自身位置推导，
#: 无法用环境变量改道。故只在本测试的子进程里 patch init_db 所在模块的绑定
#: （``schema._REPO_ROOT``），生产 ``preflight_data_dir`` 的语义**原样保留**——它对真实
#: 旧位置残留继续 fail-loud，这一点另由 ``tests/test_data_dir_migration_gate.py`` 正反钉住。
_ISOLATION_DRIVER = """\
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())
import delector.core.db.schema as schema

schema._REPO_ROOT = sys.argv[1]
runpy.run_path(sys.argv[2], run_name="__main__")
"""

KEYS = (
    "payload_mb",
    "words",
    "segment_blob_ms",
    "segment_first_ms",
    "segment_repeat_ms",
    "segment_pool_index_ms",
    "segment_first_writes",
    "segment_repeat_writes",
)

#: repeat 计时相对 first 的显式容差上限（见 test_save_wb_state_repeat_not_slower_than_first）。
#: 1.25× 依据：CI 实测最差反转 39.188/37.527 = 1.044（2026-11-05 run 41960965296），
#: 本地 20 轮 ratio p95 = 0.692 / max = 0.844；取观察值 1.044 的 ~1.2 倍留噪声余量。
#: 仍能抓住的退化：repeat 路径相对 first 变慢 ≥25%（注入 +50ms 即被拦下）。
REPEAT_SLOWDOWN_TOLERANCE = 1.25
NUMERIC_RE = re.compile(
    r"^(" + "|".join(KEYS) + r")=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE
)


def _run_bench(tmp_path: Path) -> str:
    """跑一次基准脚本；迁移闸的「旧位置」指向 tmp 空目录（与真实仓库根解耦）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATABASE_PATH"] = str(tmp_path / "gate_wb.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "gate_wb_progress.db")
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "gate_wb_data")
    isolated_repo_root = tmp_path / "isolated_repo_root"
    isolated_repo_root.mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-c", _ISOLATION_DRIVER, str(isolated_repo_root), str(SCRIPT)],
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
    """计时闸：重复保存不得比首存慢超过 ``REPEAT_SLOWDOWN_TOLERANCE`` 倍。

    容差不是"凑绿"：耗时差随存储性能漂移（快存储 CI 上 INSERT 很便宜，两段收敛，
    精确 ``<=`` 会随机反转，2026-11-05 实测 39.188ms vs 37.527ms）。幂等性另有
    ``test_save_wb_state_repeat_writes_only_blob`` 以写语句条数环境无关地钉死；
    本闸只负责抓"日常保存路径明显变慢"，≥25% 退化仍会红。
    """
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    first_ms = float(found["segment_first_ms"])
    repeat_ms = float(found["segment_repeat_ms"])
    limit_ms = first_ms * REPEAT_SLOWDOWN_TOLERANCE
    assert repeat_ms <= limit_ms, (
        f"幂等重复保存({repeat_ms:.1f}ms) 超过首存({first_ms:.1f}ms) 的 "
        f"{REPEAT_SLOWDOWN_TOLERANCE:.2f}× 容差上限({limit_ms:.1f}ms)：日常保存路径变慢了 ≥"
        f"{(repeat_ms / first_ms - 1) * 100:.0f}%\n{out}"
    )


def test_save_wb_state_repeat_writes_only_blob(tmp_path: Path) -> None:
    """幂等性直证：repeat 只允许 1 条写语句（wb_state blob upsert），first ≥ words 条。

    与环境无关：不依赖 INSERT 是否比逐词比对慢。投影幂等性被破坏（repeat 又开始
    INSERT/UPDATE ``vocab_cards``）时，条数会从 1 跳到 ~3k。
    """
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    words = int(found["words"])
    first_writes = int(found["segment_first_writes"])
    repeat_writes = int(found["segment_repeat_writes"])
    assert repeat_writes == 1, (
        f"幂等重复保存产生了 {repeat_writes} 条写语句（应只有 1 条 wb_state blob upsert）："
        f"投影幂等性被破坏\n{out}"
    )
    assert first_writes >= words, (
        f"首存只有 {first_writes} 条写语句（应 ≥ words={words}）：首次投影没真正落库，基准失真\n{out}"
    )
