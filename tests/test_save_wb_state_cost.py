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

本文件钉**结构性事实**（不钉绝对毫秒）：脚本可跑、输出可解析、repeat（幂等路径）
只做固定量的 DB 工作（1 次全表索引 SELECT + 1 次 blob upsert）且不随词数增长——
若条数跳升说明投影幂等性被破坏，或在重复路径上又跑起了逐词查询 / 重复全表扫描（真回归）。

2026-11-05 flake 复盘（run 41960965296 / unit-4）：`repeat 39.188ms > first 37.527ms`
（+4.4%）随机红。原因：**耗时差是存储性能的函数，不是幂等性的函数** ——
Windows 审计机 `INSERT` 较慢（本地 20 轮实测 repeat/first = 0.594–0.844，中位 0.633），
而 Linux CI 的 tmpfs/ext4 让 ~3k INSERT 变得很便宜，两段耗时收敛到同一量级，
单次中位数的噪声即可反转方向。当时保留计时断言（1.25× 容差）并新增写语句条数判据。

2026-11-06 二次治理：计时闸本身被证明不可靠，删除时间断言。证据：
- 本机 24 次独立采样（每次子进程内 5 轮取中位数）：repeat/first = 0.592–0.665，
  中位 0.625，**0/24 超过 1.25**；first 中位 72.9ms、repeat 中位 45.6ms。
- 同一份结构性代码在 CI 上历史观测到 1.044（2026-11-05）与 1.59（本轮 unit-4 误报，
  first 59.7ms / repeat 95.0ms）。跨环境比值漂移 0.59→1.59（约 2.7 倍），
  说明两段耗时之间的差是**存储/负载的函数**，不是幂等性或复杂度的函数。
  任何固定倍数（1.25 / 3）都无法同时满足「真实变慢时红」与「runner 抖动时不红」。
故本文件改钉**环境无关的 DB 工作量**（见 ``test_save_wb_state_repeat_db_work_constant``）：
- repeat 每次保存只允许 1 条全表索引 SELECT + 1 条 wb_state blob upsert（合计 2 条数据语句），
  且该条数在 300 / 1200 词两种规模下**完全相同**（不随词数增长）；
- first 的写语句数随词数线性增长（≥ words），用来证伪「探针没真正跑到保存路径」。
这能抓住的真实回归：重复保存又跑起逐词查询（每词 +1 条 SELECT）、重复全表扫描
（+1 条 SELECT），或又开始投影写库（writes 从 1 跳到 ~N）。
bench 脚本的耗时输出保留为人类可读的可观测指标，不再参与断言。
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

#: 子进程驱动：直接在真实保存路径上挂 SQL trace，统计每条语句的**结构量**。
#: 与 ``_ISOLATION_DRIVER`` 同款隔离（``schema._REPO_ROOT`` 指向 tmp 空目录），
#: 但不跑 bench 的计时段——只关心 save_wb_state 发出了多少条 DB 语句。
#: 计数口径：排除 BEGIN/COMMIT/ROLLBACK/SAVEPOINT/RELEASE 这类事务控制语句
#: （它们与数据工作量无关，且随 Python sqlite3 的事务实现变化）；其余语句按
#: SELECT / 写语句（INSERT/UPDATE/DELETE/REPLACE）分类统计。
_WORK_PROBE_DRIVER = """\
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tools"))
import bench_save_wb_state as bench

tmpdir = tempfile.mkdtemp(prefix="wb_work_")
bench._bootstrap_env(tmpdir)

import delector.core.db.schema as schema

schema._REPO_ROOT = sys.argv[1]

from delector.core.db import connection as conn_mod
from delector.core.database import init_db, save_wb_state

words = int(sys.argv[2])
_TX = frozenset(("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"))
_WRITE = frozenset(("INSERT", "UPDATE", "DELETE", "REPLACE"))

try:
    init_db()
    payload = bench._build_payload(words, random.Random(7))
    counts = {"statements": 0, "selects": 0, "writes": 0}
    real_get_db = conn_mod.get_db

    def traced_get_db(*args, **kwargs):
        conn = real_get_db(*args, **kwargs)

        def cb(sql):
            head = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
            if not head or head in _TX:
                return
            counts["statements"] += 1
            if head == "SELECT":
                counts["selects"] += 1
            elif head in _WRITE:
                counts["writes"] += 1

        conn.set_trace_callback(cb)
        return conn

    conn_mod.get_db = traced_get_db
    try:
        for phase in ("first", "repeat"):
            counts.update(statements=0, selects=0, writes=0)
            save_wb_state(payload)
            for metric, value in counts.items():
                print(f"probe_{phase}_{metric}={value}")
    finally:
        conn_mod.get_db = real_get_db
    print(f"probe_words={words}")
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
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

PROBE_KEYS = (
    "probe_words",
    "probe_first_statements",
    "probe_first_selects",
    "probe_first_writes",
    "probe_repeat_statements",
    "probe_repeat_selects",
    "probe_repeat_writes",
)

#: repeat（幂等重复保存）允许的 DB 数据语句总数：1 条 ``_pool_index`` 全表 SELECT
#: + 1 条 wb_state blob upsert。它是「重复保存没有多做全量工作」的结构性证据，
#: 与环境速度无关（对比已被删除的 1.25× 计时闸，原因见模块 docstring）。
REPEAT_STATEMENTS_BUDGET = 2

#: 结构闸的两档规模：repeat 的 DB 语句数必须与词数无关（300 / 1200 相同）。
PROBE_SMALL_WORDS = 300
PROBE_LARGE_WORDS = 1200

NUMERIC_RE = re.compile(
    r"^(" + "|".join(KEYS) + r")=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE
)
PROBE_RE = re.compile(r"^(" + "|".join(PROBE_KEYS) + r")=([0-9]+)$", re.MULTILINE)


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


def _run_work_probe(tmp_path: Path, words: int) -> dict:
    """在子进程里保存 ``words`` 词的快照两次，返回首存 / 重复保存的 DB 语句计数。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATABASE_PATH"] = str(tmp_path / "probe_wb.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "probe_wb_progress.db")
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "probe_wb_data")
    isolated_repo_root = tmp_path / "isolated_repo_root"
    isolated_repo_root.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-c", _WORK_PROBE_DRIVER, str(isolated_repo_root), str(words)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, (
        f"DB 工作量探针退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    found = dict(PROBE_RE.findall(proc.stdout))
    missing = [k for k in PROBE_KEYS if k not in found]
    assert not missing, f"探针输出缺段：{missing}\n{proc.stdout}"
    return {k: int(v) for k, v in found.items()}


def test_save_wb_state_bench_parsable(tmp_path: Path) -> None:
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    missing = [k for k in KEYS if k not in found]
    assert not missing, f"输出缺段：{missing}\n{out}"
    for k in ("segment_blob_ms", "segment_first_ms", "segment_repeat_ms", "segment_pool_index_ms"):
        assert float(found[k]) > 0.0, f"段 {k} 非正——计时段没真正跑到\n{out}"


def test_save_wb_state_repeat_db_work_constant(tmp_path: Path) -> None:
    """结构闸：重复保存的 DB 工作量恒定，不随 payload 词数增长。

    判据（全部环境无关，只数 SQL 语句）：
    1. repeat 每次保存恰好 2 条数据语句：1 条 ``_pool_index`` 全表 SELECT
       + 1 条 wb_state blob upsert；
    2. 该条数在 ``PROBE_SMALL_WORDS`` / ``PROBE_LARGE_WORDS`` 两档规模下**相同**
       ——若重复路径又跑起逐词查询（每词 +1 条 SELECT）或重复全表扫描，条数会随规模跳升；
    3. first 的写语句数 ≥ words（首存确实是全量 INSERT），用来反证探针真的跑到了保存路径。

    为什么不用耗时闸：见模块 docstring 的 2026-11-06 采样数据——同一份代码在 Windows
    本机 repeat/first 中位 0.625，Linux CI 上历史观测 1.044 与 1.59，跨环境漂移约 2.7 倍，
    固定倍数阈值必然在「漏判真实变慢」与「被 runner 抖动打红」之间二选一。
    """
    small = _run_work_probe(tmp_path / "small", PROBE_SMALL_WORDS)
    large = _run_work_probe(tmp_path / "large", PROBE_LARGE_WORDS)

    for label, probe in (("small", small), ("large", large)):
        assert probe["probe_repeat_statements"] == REPEAT_STATEMENTS_BUDGET, (
            f"[{label}] 重复保存发出 {probe['probe_repeat_statements']} 条 DB 数据语句"
            f"（应恰好 {REPEAT_STATEMENTS_BUDGET} 条：1 次全表索引 SELECT + 1 次 blob upsert）："
            f"重复路径多了额外 DB 工作\n{probe}"
        )
        assert probe["probe_repeat_selects"] == 1, (
            f"[{label}] 重复保存发出 {probe['probe_repeat_selects']} 条 SELECT（应恰好 1 条全表索引）："
            f"疑似逐词查询或重复全表扫描\n{probe}"
        )
        assert probe["probe_repeat_writes"] == 1, (
            f"[{label}] 重复保存发出 {probe['probe_repeat_writes']} 条写语句（应只有 1 条 blob upsert）："
            f"投影幂等性被破坏\n{probe}"
        )
        assert probe["probe_first_writes"] >= probe["probe_words"], (
            f"[{label}] 首存只有 {probe['probe_first_writes']} 条写语句"
            f"（应 ≥ words={probe['probe_words']}）：首次投影没真正落库，探针失真\n{probe}"
        )

    assert small["probe_repeat_statements"] == large["probe_repeat_statements"], (
        f"重复保存的 DB 语句数随词数增长：{PROBE_SMALL_WORDS} 词="
        f"{small['probe_repeat_statements']} 条，{PROBE_LARGE_WORDS} 词="
        f"{large['probe_repeat_statements']} 条 —— 重复路径存在 O(n) DB 工作\n"
        f"small={small}\nlarge={large}"
    )
    # 反证：若探针没真正执行保存路径，first 的语句数不会随词数线性增长。
    assert (
        large["probe_first_statements"] - small["probe_first_statements"]
        == PROBE_LARGE_WORDS - PROBE_SMALL_WORDS
    ), (
        f"首存语句数未随词数线性增长（small={small['probe_first_statements']}, "
        f"large={large['probe_first_statements']}）：探针未真正执行全量投影\n"
        f"small={small}\nlarge={large}"
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
