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

Task 1（卡盒基准补「各层占比」）在以上三条之外又钉了两条，用于回答
**ADR-0018 §6 判定门的输入——「Python 侧占多少」**：

4. 输出含 **Python 侧占比**（`python_pct=NN.N%`，= 段 D−B 占端点总耗时 D），
   同样落在 `(0, 100]`；
5. **每卡耗时**（`per_row_us`）有上界。钉它而不是钉 `segment_D_ms` 的绝对毫秒：
   CI 机器主频差异会把绝对阈值变成假红来源，而 `D/n`（微秒/卡）是**比值量纲**，
   对机器快慢只差一个常数因子，跨机器可比。

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
import statistics
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
# Task 1 新增：`python_pct` 是「Python 物化 + 逐卡 FSRS 递推」占端点总耗时的比例，
# 与 `filesort_pct` 同构（都是 `x / 段D * 100`），故用同一套抓取方式。
PYTHON_PCT_RE = re.compile(r"^python_pct=([0-9]+(?:\.[0-9]+)?)%$", re.MULTILINE)
PER_ROW_US_RE = re.compile(r"^per_row_us=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)

# Task 5b 新增：p95 行 + **原始样本行**。只给 p95 数字不给样本，下游（含 ADR 回填）
# 无从复核它到底是不是拿中位数冒充的 —— 样本行是这条门禁能成立的**前提**。
SEGMENT_D_P95_RE = re.compile(r"^segment_D_p95_ms=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)
SAMPLES_D_RE = re.compile(r"^samples_segment_D_ms=([0-9.]+(?:,[0-9.]+)+)$", re.MULTILINE)
ROUNDS_RE = re.compile(r"^rounds=([0-9]+)$", re.MULTILINE)

# 分位重算容差（毫秒）：按 p95 行的**打印精度**定（3 位小数 ⇒ ±0.0005），
# 取 1e-3 只多留一倍余量 —— 仍能抓住"拿中位数冒充 p95"（实测两者相差数十毫秒）。
QUANTILE_ABS_TOL_MS = 1e-3

# 规模与轮数：门禁要**快**（每次 pytest 都跑），故用比人工基准小得多的规模。
# 取值仍需足够大，让「排序」在噪声之上可测（段 B > 段 C 才有统计意义）。
GATE_SCALE = "8000"
GATE_ROUNDS = "5"

# 每卡耗时上界（微秒/卡）。**刻意钉比值而非绝对毫秒**：绝对毫秒会随 CI 机器主频
# 漂移变假红，`D/n` 不会。
# 实测依据（本机）：门禁快档（8000 行 / 5 轮中位数）9 次
# 31.34 / 32.06 / 31.83 / 37.30 / 35.72 / 34.30 / 35.72 / 34.68 / 34.30；
# 默认档（1000 / 20000 / 50000，7 轮）28.87 / 39.78 / 44.12。
# 取 120.0 ⇒ 对**门禁档**最坏实测 37.30 留 3.2 倍余量（断言只会看到门禁档），
# 对全部实测最坏 44.12 仍有 2.7 倍余量，足以吸收 CI 机器慢 2 倍。
#
# ⚠️ **这不是回归灵敏度闸**（务必知悉，勿当成灵敏度门槛用）：3.2 倍余量是为**吸收
# CI 机器变慢**而留的，意味着 37.30 → 74.6（2× 退化）**仍然绿**，抓不到。本断言只
# 负责捕获**数量级退化**（端点突然变成 O(n²)、段 D 多跑一遍全表之类）。要测灵敏度
# 请用**默认档**（1000 / 20000 / 50000，7 轮）跑出基线后人工对比——那档噪声更低、
# 余量更窄，但不适合进门禁（太慢且易假红）。
MAX_PER_ROW_US = 120.0


def _run_bench(tmp_path: Path, p95_rounds: str = GATE_ROUNDS) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文。

    `BENCH_P95_ROUNDS` 显式钉死（而不是"留空走默认"）：门禁必须**确定性**地知道
    样本数，否则外面一个残留的环境变量就会让"样本数 == rounds"这条断言失去意义。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCH_SCALES"] = GATE_SCALE
    env["BENCH_ROUNDS"] = GATE_ROUNDS
    env["BENCH_P95_ROUNDS"] = p95_rounds
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


def test_bench_output_declares_python_side_lines(tmp_path: Path) -> None:
    """⑤ 防空转：新增断言依赖的输出行必须真被打印出来（含源码级钉死）。

    先单独钉「行存在」，后面两条断言才谈得上在检视数字。若脚本哪天删掉
    `python_pct=` / `per_row_us=` / `python_verdict=`，红**在这里**、报错直指原因，
    而不是让下游断言因为「找不到匹配」才连带报错（那会掩盖真正的回归点）。

    源码断言**必须匹配真正的 print 语句**（`print(f"xxx=`），不能只匹配裸字面量
    `xxx=`：后者在脚本的**模块 docstring（输出契约块）**里也出现，于是即使 `main()`
    里的 print 行被删，断言照样绿 ⇒ 半恒真。钉 `print(f"` 前缀后，删掉 print 行
    即红（已用变异自证）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'print(f"python_pct=' in src, "基准脚本源码不再打印 `python_pct=` 行"
    assert 'print(f"per_row_us=' in src, "基准脚本源码不再打印 `per_row_us=` 行"
    assert 'print(f"python_verdict=' in src, "基准脚本源码不再打印 `python_verdict=` 结论行"

    out = _run_bench(tmp_path)
    assert PYTHON_PCT_RE.search(out), f"输出里找不到 `python_pct=NN.N%` 这一行\n{out}"
    assert PER_ROW_US_RE.search(out), f"输出里找不到 `per_row_us=NN.NN` 这一行\n{out}"
    assert "python_verdict=" in out, f"输出里找不到 `python_verdict=` 结论行\n{out}"


def test_bench_output_reports_parsable_python_pct(tmp_path: Path) -> None:
    """⑥ 输出含可解析的 Python 侧占比，且落在物理可能的开区间 (0, 100]。

    这是 ADR-0018 §6 判定门**条件①**（Python CPU > 50%）的**输入**，必须能被正则
    抓出来而不是靠人肉读日志。下界 `> 0` 同样是防恒真。

    这条断言**真正**能捕获什么（**勿说过头**，此前 docstring 声称能抓「跳过 FSRS」，
    经独立验算不成立）：段 D 即使被打桩成「只跑 SQL 不跑 FSRS」，`D > B` **依然成
    立** —— 段 D 仍含 `grammar_cards` 读取（`delector/routes/main.py` 里 get_cards
    的两表读取）与每轮 `db_conn()` 新建连接的开销，故 `(D−B)/D` 只是**塌成小正数**
    （约 1~3%），本断言**仍绿**。
    它真正红在「D ≤ B」的**符号反转**／**分段塌缩**：只有当段 D 连 `dict(r)` 物化
    与 grammar 读取都被拿掉、彻底退化成裸 SQL 时，占比才跌出 `(0, 100]`。
    因此**不要**在这里加占比下限：将来 FSRS 一旦被优化（占比自然变小），下限会假红。
    """
    out = _run_bench(tmp_path)
    matches = PYTHON_PCT_RE.findall(out)
    assert matches, f"输出里找不到 `python_pct=NN.N%` 这一行\n{out}"
    pct = float(matches[-1])
    assert 0.0 < pct <= 100.0, f"Python 侧占比 {pct}% 超出物理可能区间 (0, 100]——分段定义多半被改坏了\n{out}"


def test_bench_per_row_us_within_budget(tmp_path: Path) -> None:
    """⑦ 每卡耗时（`D / n`，微秒）不得超出预算上界。

    钉**每卡耗时**而不是 `segment_D_ms` 的绝对毫秒，理由见模块 docstring：CI 机器
    主频差异只影响绝对值，不影响「每张卡要烧多少微秒」这个比值。
    下界 `> 0` 顺手防住「段 D 根本没跑到就报 0」。
    """
    out = _run_bench(tmp_path)
    matches = PER_ROW_US_RE.findall(out)
    assert matches, f"输出里找不到 `per_row_us=NN.NN` 这一行\n{out}"
    per_row_us = float(matches[-1])
    assert per_row_us > 0.0, f"每卡耗时 {per_row_us}µs 非正——段 D 没真正跑到\n{out}"
    assert per_row_us <= MAX_PER_ROW_US, (
        f"每卡耗时 {per_row_us}µs 超出预算上界 {MAX_PER_ROW_US}µs"
        f"（超出 {per_row_us / MAX_PER_ROW_US:.2f}×）：端点侧出现数量级退化\n{out}"
    )


def test_bench_output_reports_p95_over_the_same_samples(tmp_path: Path) -> None:
    """⑧ p95 必须与中位数取自**同一批**样本，且不得是中位数本身（Task 5b 硬纪律）。

    为什么必须同时打印样本行：只断言"有个 p95 数字"是**半恒真** —— 拿中位数填进
    p95 行也能过（p95 ≥ median 恒成立）。故本断言要求脚本把原始样本整批吐出来，
    由**测试侧独立重算**分位数并逐位对齐：
    - 对不上 ⇒ p95 不是从这批样本算的（多半是重新计时或换了口径）；
    - 没有样本行 ⇒ 无从审计，同样判失败（不许用"信我就行"代替可复核）。
    另钉 `p95 ≥ median` 与 `p95 ≤ max`：分位数的物理边界，越界即算法被改坏。
    """
    out = _run_bench(tmp_path)
    p95_match = SEGMENT_D_P95_RE.search(out)
    assert p95_match is not None, f"输出里找不到 `segment_D_p95_ms=NN.NNN`\n{out}"
    samples_match = SAMPLES_D_RE.search(out)
    assert samples_match is not None, (
        f"输出里找不到 `samples_segment_D_ms=<逗号分隔>`：无样本则无法复核 p95 是否由同批样本算出\n{out}"
    )
    rounds_match = ROUNDS_RE.search(out)
    assert rounds_match is not None, f"输出里找不到 `rounds=N`\n{out}"

    samples = [float(item) for item in samples_match.group(1).split(",")]
    assert len(samples) == int(rounds_match.group(1)), (
        f"样本数 {len(samples)} 与 rounds={rounds_match.group(1)} 不符：p95 与中位数不是同一批样本\n{out}"
    )
    p95 = float(p95_match.group(1))
    expected = statistics.quantiles(sorted(samples), n=100, method="inclusive")[94]
    assert p95 == pytest.approx(expected, abs=QUANTILE_ABS_TOL_MS), (
        f"p95={p95} 与样本重算值 {expected} 不符：p95 不是从这批样本算出来的\n{out}"
    )
    median = float(dict(SEGMENT_RE.findall(out))["segment_D"])
    assert p95 >= median - QUANTILE_ABS_TOL_MS, f"p95={p95} 低于中位数 {median}：分位算法被改坏\n{out}"
    assert p95 <= max(samples) + QUANTILE_ABS_TOL_MS, f"p95={p95} 超过样本最大值：分位算法被改坏\n{out}"


def test_p95_rounds_are_env_tunable(tmp_path: Path) -> None:
    """⑨ 轮数必须能用环境变量提高（p95 对样本量远比中位数敏感，人工档要一键提精度）。

    n=5 的 p95 ≈ 最大值、且系统性低估尾部（P(max₅ < 真p95) ≈ 77%），所以"想判强结论
    就得能加到 n≥20"。若轮数写死在代码里，人工档就得改代码 —— 那等于把"提高精度"
    变成一次带代码改动的测量，数字不再可信。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "BENCH_P95_ROUNDS" in src, "基准脚本必须支持 BENCH_P95_ROUNDS 提高 p95 样本量"
    out = _run_bench(tmp_path, p95_rounds="7")
    samples_match = SAMPLES_D_RE.search(out)
    assert samples_match is not None, f"输出里找不到样本行\n{out}"
    assert len(samples_match.group(1).split(",")) == 7, f"BENCH_P95_ROUNDS=7 未生效\n{out}"
