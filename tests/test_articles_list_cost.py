# -*- coding: utf-8 -*-
"""``tools/bench_articles_list.py`` 的存在性、隔离与结论门禁（P1-6）。

钉住什么
--------
P1-6 的交付物是「列表成本与文章数解耦」的**量测结论**。本文件钉四件事：

1. 脚本存在且可跑（子进程实跑，CLI 形态独立可用）；
2. 输出含三段可解析正数（``segment_before_ms`` / ``segment_A_ms`` /
   ``segment_B_ms``）与样本行（p95 可独立复核，与 test_cards_endpoint_cost 同纪律）；
3. **结构性事实**：Python 侧 ``json.loads`` 的输入字节量（``py_parse_bytes_*``）
   在改后比改前至少小一个数量级（10×）——这是"列表不再解析整列 blob"的
   机器无关证据；绝对毫秒会随 CI 机器漂移打假红，字节量不会；
4. 同库同数据下方案 A 严格快于改前（同机同数据比值，结构性成立：改前必须把
   N×36KB 逐行喂给 json.loads，改后只解析 N_limit×~200B）。

隔离纪律：子进程 + 临时 CWD 环境变量钉库（[Instinct: Isolated-DB]），脚本自身
``tempfile.mkdtemp`` + 三环境变量（源码级断言，同 test_cards_endpoint_cost.py）。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_articles_list.py"

NUMERIC_RE = re.compile(
    r"^(segment_before_ms|segment_A_ms|segment_B_ms"
    r"|py_parse_bytes_before|py_parse_bytes_after)=([0-9]+(?:\.[0-9]+)?)$",
    re.MULTILINE,
)
SAMPLES_RE = re.compile(r"^samples_segment_A_ms=([0-9.]+(?:,[0-9.]+)+)$", re.MULTILINE)
ROWS_RE = re.compile(r"^rows=([0-9]+)$", re.MULTILINE)

# 门禁快档：2000 行（贴近审计实测规模）、5 轮中位数。再大会拖慢每次 pytest。
GATE_ROWS = "2000"
GATE_ROUNDS = "5"


def _run_bench(tmp_path: Path) -> str:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCH_ARTICLE_ROWS"] = GATE_ROWS
    env["BENCH_ROUNDS"] = GATE_ROUNDS
    # 双保险：即便脚本自身 bug 也把库路径钉死在临时目录。
    env["DATABASE_PATH"] = str(tmp_path / "gate_articles.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "gate_progress.db")
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "gate_data")
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
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"


def test_bench_script_isolated_from_repo_db() -> None:
    """源码级隔离断言（同 test_cards_endpoint_cost 的 [Instinct: Isolated-DB]）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "tempfile.mkdtemp" in src, "基准脚本必须用 tempfile.mkdtemp() 建隔离库目录"
    assert "DATABASE_PATH" in src and "PROGRESS_DB_PATH" in src and "DELECTOR_DATA_DIR" in src
    assert "shutil.rmtree" in src, "基准脚本必须在 finally 里清理临时目录"


def test_bench_output_segments_parsable(tmp_path: Path) -> None:
    """三段（改前/A/B）+ 样本行 + 规模行都可解析且为正。"""
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    for key in ("segment_before_ms", "segment_A_ms", "segment_B_ms", "py_parse_bytes_before", "py_parse_bytes_after"):
        assert key in found and float(found[key]) > 0.0, f"输出缺 {key} 或非正数\n{out}"
    samples = SAMPLES_RE.search(out)
    assert samples is not None, f"输出缺样本行（p95 无法独立复核）\n{out}"
    assert len(samples.group(1).split(",")) == int(GATE_ROUNDS), f"样本数与 rounds={GATE_ROUNDS} 不符\n{out}"
    assert ROWS_RE.search(out), f"输出缺 rows= 规模行\n{out}"


def test_bench_python_parse_bytes_decoupled_from_blob(tmp_path: Path) -> None:
    """结构性事实：改后 Python 侧 json.loads 输入字节量 ≤ 改前的 1/10。

    改前每行把整列 blob（~36KB）喂给 json.loads；改后只解析 ~200B 的 stats 投影
    （且只解析 LIMIT 行）。10× 是数量级断言——不钉绝对毫秒，跨机器可比。
    """
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    before_bytes = float(found["py_parse_bytes_before"])
    after_bytes = float(found["py_parse_bytes_after"])
    assert after_bytes * 10.0 < before_bytes, (
        f"改后 Python 解析字节量 {after_bytes} 未比改前 {before_bytes} 小一个数量级："
        "列表路径又在解析整列 blob 了？\n" + out
    )


def test_bench_plan_a_beats_baseline_same_data(tmp_path: Path) -> None:
    """同库同数据：方案 A 严格快于改前。

    结构性成立（非机器巧合）：改前必须完成 N×blob 的 Python json.loads（实测
    ~900ms 量级），改后只有 LIMIT 行 × ~200B（~10ms 量级），任何机器上比值都在
    数量级以上，故符号断言不会因机器漂移假红。
    """
    out = _run_bench(tmp_path)
    found = dict(NUMERIC_RE.findall(out))
    before = float(found["segment_before_ms"])
    plan_a = float(found["segment_A_ms"])
    plan_b = float(found["segment_B_ms"])
    assert plan_a < before, f"方案 A({plan_a:.1f}ms) 未快于改前({before:.1f}ms)\n{out}"
    assert plan_b < before, f"方案 B({plan_b:.1f}ms) 未快于改前({before:.1f}ms)\n{out}"
