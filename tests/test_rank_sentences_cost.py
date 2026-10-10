# -*- coding: utf-8 -*-
"""`tools/bench_rank_sentences.py` 的输出契约与**纯函数单价**回归闸（ADR-0018 §8 `Unknown 5`）。

背景（为什么需要这层门禁）
--------------------------
同一路径 `rank_sentences → analyze_syntax_tree` 上戴着两个互相矛盾、且都**不可复跑**的旧值：

- `delector/routes/syntax_hard.py:9` 注释**曾写的** `spaCy ~42ms/句`（2026-10-09 移除）
- `docs/reviews/2026-09-28-swarm-audit-master.md:36`：`rank_sentences 实测 ~2.1 ms/句`

差 20 倍。`tools/bench_long_read.py` 覆盖的是**端到端**冷读（≈10ms/句，**含端点开销**），
仍缺「无端点开销的纯函数单价」。本文件把这个缺失值钉成断言。

钉住什么（防恒真）
------------------
1. 脚本**存在且可跑**（子进程实跑：契约要在真实 CLI 形态下成立，"可复跑"才不是空话）；
2. 输出**逐行可解析**：`analyze_*` / `rank_*` / `sentences` / `tokens` / `rounds` 各数值行
   存在、为正；
3. **两条口径都要测**（`analyze_syntax_tree` 单句调用 + `rank_sentences` 整段归一到每句）——
   只测一条就退回"单一不可复跑值"的老路；
4. **p95 与中位数同批样本**：p95 必须由 `samples_analyze_ms` / `samples_rank_ms` 重算得到
   （复用 `tools/bench_stats.py` 的口径，**不重新计时**）；
5. **句长是主自变量**：三档耗时与三档 token 数都要单调；
6. `verdict=` 必须**点名对照三个数**（42ms / 2.1ms / 端到端≈10ms），并写明口径不可相除；
7. **实际生效模型可复核**：`model=` 必出、可解析为非空字符串（否则 verdict 里"md 口径未测"
   这一前提不可复核 —— `get_spacy_nlp()` 先试 md、失败才退 sm，本就可能在 md 上测）；
8. **两条 p95 不可比 + 源码顺序不变量**：`p95_note=` 显式声明两条 p95 聚合单元/样本量不同、
   不可相除；并用 AST 钉「`get_spacy_nlp()` 调用早于计时段」与「脚本体不含 `_material_text`」
   （纯函数口径、不经 DB/端点）两条目前只靠人读代码的不变量。

为什么这些断言不是恒真
----------------------
- **源码级断言**（`print(f"xxx=`）：只匹配输出里的 `xxx=` 是半恒真的 —— 脚本模块 docstring
  里也写着输出契约。故每条契约行都**额外**钉源码里真实的 print 语句（照抄
  `tests/test_spacy_unit_cost.py` 的教训）。
- **数值正值**：计时段被改坏（空跑、样本恒空）时值会塌成 0 ⇒ 红。
- **p95 重算 + 物理边界**（p95 ≥ median、p95 ≤ max、样本数 == `*_p95_n`）：只给 p95 数字
  不给样本 = 不可复核；重算什么都没做也过不了。
- **语料真实性**（白名单而非黑名单）：用 AST 抽出 `CORPUS_*` 字面量（docstring/注释里的
  德语词不算），要求德语功能词 + 变音符号/ß；`"lorem" not in src` 是黑名单（换英文照样绿）。
- **不钉绝对毫秒阈值**：机器差异会让绝对阈值变成假红来源 —— 钉**比值/关系**。
- **禁类型检查豁免**（本任务硬要求 6）：新文件里出现任何豁免注释一律红。

隔离纪律（`[Instinct: Isolated-DB]`）
-------------------------------------
基准脚本 MUST NOT 触碰仓库根的真实 `delector.db`。这里做**源码级**静态断言（跑后比对 mtime
需要仓库根存在真实 db，CI 上不存在 ⇒ 断言恒真）。源码里出现 `mkdtemp` + 三个环境变量 +
`shutil.rmtree`，才是这条纪律真正被写下的证据。
"""

import ast
import importlib.util
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Pattern, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_rank_sentences.py"

# 契约数值行（脚本 MUST 逐条打印，且值为正）。
NUM_KEYS = (
    "analyze_per_sentence_ms",
    "analyze_p95_ms",
    "analyze_per_token_us",
    "rank_per_sentence_ms",
    "rank_p95_ms",
    "rank_per_token_us",
    "sentences",
    "tokens",
    "rounds",
)

# p95 与样本行配对：(p95 键, 样本键, 中位数键, p95 样本数键)。
# 两条口径各占一对 —— 只测一条会退回"单一不可复跑值"。
P95_PAIRS = (
    ("analyze_p95_ms", "samples_analyze_ms", "analyze_per_sentence_ms", "analyze_p95_n"),
    ("rank_p95_ms", "samples_rank_ms", "rank_per_sentence_ms", "rank_p95_n"),
)

BUCKETS = ("short", "mid", "long")
# 样本行形如 `key=1.2,3.4,...`（至少两个样本才谈得上分位）。
SAMPLES_RE_TEMPLATE = r"^{key}=([0-9.]+(?:,[0-9.]+)+)$"
QUANTILE_ABS_TOL_MS = 1e-5

# 本任务要收口的三个对照值（verdict 必须点名，否则等于没结论）。
LEGACY_SYNTAX_HARD = "42ms"  # 原 syntax_hard.py:9 注释（2026-10-09 移除）
LEGACY_AUDIT = "2.1ms"  # docs/reviews/2026-09-28-swarm-audit-master.md:36
LEGACY_LONG_READ = "10ms"  # tools/bench_long_read.py 端到端冷读 ≈10ms/句

# 防豁免：写成正则而非裸字面量，避免本文件自身被"检索豁免"的 grep 误命中。
# 注意 `mypy:\s*disable-error-code`（带 `\s` 转义）而非裸 `disable-error-code`：
# 后者会命中本文件里那行 `re.compile(r"disable-error-code")` 的**字面量自身**（自匹配假红）。
SUPPRESSION_RES: tuple[Pattern[str], ...] = (
    re.compile(r"type:\s+ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"mypy:\s*disable-error-code"),
)

GATE_ROUNDS = "5"


def _run_bench(tmp_path: Path) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文（失败时把 stdout/stderr 全吐出来）。"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "BENCH_RANK_ROUNDS": GATE_ROUNDS,
            # 双保险：即便脚本自身有 bug，也把库/数据路径钉在临时目录里。
            "DELECTOR_DATA_DIR": str(tmp_path / "gate_data"),
            "DATABASE_PATH": str(tmp_path / "gate_delector.db"),
            "PROGRESS_DB_PATH": str(tmp_path / "gate_progress.db"),
        }
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, (
        f"基准脚本退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


@pytest.fixture(scope="module")
def bench_out(tmp_path_factory: pytest.TempPathFactory) -> str:
    """整个模块只实跑一次基准（模型加载 + 多轮采样不便宜），各断言共享输出。"""
    return _run_bench(tmp_path_factory.mktemp("bench_rank_gate"))


def _number(out: str, key: str) -> float:
    match = re.search(rf"^{key}=([0-9]+(?:\.[0-9]+)?)$", out, re.MULTILINE)
    assert match is not None, f"输出缺少 `{key}=N.NN`\n{out}"
    return float(match.group(1))


def _raw_value(out: str, key: str) -> str:
    match = re.search(rf"^{key}=(\S+)$", out, re.MULTILINE)
    assert match is not None, f"输出缺少单行 `{key}=<值>`\n{out}"
    return match.group(1)


def _samples(out: str, key: str) -> List[float]:
    match = re.search(SAMPLES_RE_TEMPLATE.format(key=key), out, re.MULTILINE)
    assert match is not None, f"输出缺少 `{key}=<逗号分隔>` 样本行\n{out}"
    return [float(item) for item in match.group(1).split(",")]


def _corpus_text() -> str:
    """用 AST 抽出 `CORPUS_{SHORT,MID,LONG}` 里的字面量（只看语料，不看注释）。

    刻意不对**整个源码**做关键词匹配：模块 docstring / 注释里同样写着德语词和变音符号，
    会把白名单喂饱 ⇒ 语料被整段换掉也照样绿。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    chunks: List[str] = []
    for node in tree.body:
        name = ""
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name not in ("CORPUS_SHORT", "CORPUS_MID", "CORPUS_LONG") or value is None:
            continue
        chunks.extend(
            item.value
            for item in ast.walk(value)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    assert chunks, "AST 里抽不到 CORPUS_* 语料字面量——语料被删除或改名"
    return "\n".join(chunks)


def _module_level_delector_imports(tree: ast.Module) -> List[str]:
    """模块层（非函数体内）的 delector 导入。"""
    found: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if alias.name.split(".")[0] == "delector")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "delector":
                found.append(node.module or "")
    return found


def _first_call_line(tree: ast.Module, func_name: str) -> int:
    """返回源码里对 `func_name` 的**第一次真实调用**行号（AST，忽略 docstring/注释文本）。

    刻意不走 `src.index("xxx")`：那会被模块 docstring / 注释里的同名文本喂饱（本文件
    `test_script_declares_contract_lines` 已记录这个教训），得到一个与真实执行顺序无关的
    假绿。AST 只认 `ast.Call` 节点，故拿到的是真调用点。
    """
    linenos = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name)
        )
    ]
    assert linenos, f"源码里找不到对 `{func_name}` 的调用"
    return min(linenos)


def test_script_exists() -> None:
    """① 脚本存在 —— 「纯函数单价」的载体不能被静默删除。"""
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"


def test_script_isolated_before_delector_import_and_cleans_up() -> None:
    """①' 源码自带临时目录隔离（`[Instinct: Isolated-DB]` 的可执行化）。

    本路径不碰 DB（DB 只在 `syntax_hard._material_text` 读正文），但 `import delector`
    仍会在 `DATA_DIR` 下建 `.cache/audio` ⇒ 隔离纪律照样要守。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert not _module_level_delector_imports(tree), (
        f"基准脚本在模块层导入了 delector：{_module_level_delector_imports(tree)}——"
        f"`_bootstrap_env()` 会晚于它执行，真实 db/数据目录将在隔离生效前被触碰"
    )
    assert "tempfile.mkdtemp" in src, "基准脚本必须用 tempfile.mkdtemp() 建隔离目录"
    assert "DELECTOR_DATA_DIR" in src, "基准脚本必须重定向 DELECTOR_DATA_DIR"
    assert "DATABASE_PATH" in src, "基准脚本必须重定向 DATABASE_PATH"
    assert "PROGRESS_DB_PATH" in src, "基准脚本必须重定向 PROGRESS_DB_PATH"
    assert "finally:" in src and "shutil.rmtree" in src, "基准脚本必须在 finally 里清理临时目录"
    assert src.index("_bootstrap_env(tmpdir)") < src.index("from delector"), (
        "`_bootstrap_env()` 必须排在 delector 导入之前（隔离顺序）"
    )


def test_script_declares_contract_lines() -> None:
    """② 源码里真有这些 print 语句（**不是**只出现在 docstring 的契约块里）。

    照抄 `tests/test_spacy_unit_cost.py` 的教训：只匹配裸字面量会被模块 docstring 里的
    输出契约块喂饱 ⇒ 删掉 print 行照样绿。钉 `print(f"` 前缀后，删 print 即红。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for key in NUM_KEYS:
        assert f'print(f"{key}=' in src, f"基准脚本源码不再打印 `{key}=` 行"
    for key in (
        "unit",
        "nlp_path",
        "samples_analyze_ms",
        "samples_rank_ms",
        "verdict",
        "model",
        "p95_note",
    ):
        assert f'print(f"{key}=' in src, f"基准脚本源码不再打印 `{key}=` 行"
    # p95 样本数行：两条口径各一条，钉 print 语句本身。
    assert 'print(f"analyze_p95_n=' in src, "基准脚本源码不再打印 `analyze_p95_n=` 行"
    assert 'print(f"rank_p95_n=' in src, "基准脚本源码不再打印 `rank_p95_n=` 行"
    # 三档耗时 / 三档 token 数同样出现在 docstring 的补充行里 ⇒ 一样要钉 print 语句本身。
    assert 'print(f"bucket_{bucket}_ms=' in src, "基准脚本源码不再打印 `bucket_*_ms=` 行"
    assert 'print(f"tokens_per_bucket_{bucket}=' in src, "基准脚本源码不再打印 `tokens_per_bucket_*=` 行"


def _processor_path_reads_and_compares() -> Tuple[set[str], List[ast.Compare]]:
    """解析 `_processor_path` 的**真实代码**：返回（属性读名集合, 静态引擎比较列表）。

    用 AST 而非子串：docstring 里提到字段名（``_nlp_resolved`` 等）也会命中子串，那样的门禁对
    「是否真读状态」无证明力（="随便含个词就过"）—— 故只在**属性访问 / 比较**节点上判定。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_processor_path" in funcs, (
        "processor 侧判据必须收在 _processor_path（与 bench_cold_start / bench_long_read 同口径）"
    )
    node = funcs["_processor_path"]
    reads = {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    static_compares = [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Compare)
        and isinstance(child.left, ast.Attribute)
        and child.left.attr == "NLP_ENGINE"
    ]
    return reads, static_compares


def test_nlp_path_uses_production_judgement_not_reimplemented() -> None:
    """③ 路径判定必须复用**生产自己的判据**，且 processor 侧按**真实加载状态**判。

    processor 侧**不再**断言 `NLP_ENGINE`（惰性化后它是导入期声明值、恒为 "spacy"，拿它判等于
    恒真、探测不到加载失败 —— 这正是 bench_cold_start / bench_long_read 已修、本文件曾漏改的同类
    缺陷）。改钉**真实**判据（AST 属性读，非子串——docstring 提到字段名不算数）：
      - `_processor_path` 体内必须**真读** `processor.nlp` / `_nlp_resolved` / `_nlp_model`；
      - **不得**出现 `processor.NLP_ENGINE == ...` 这种静态声明值比较。
    对「改回读 NLP_ENGINE 静态值」与「让未解析分支假装已解析」两类变异都**必红**（见 3A′ 回执）。
    """
    reads, static_compares = _processor_path_reads_and_compares()
    for field in ("nlp", "_nlp_resolved", "_nlp_model"):
        assert field in reads, f"_processor_path 必须真读 `processor.{field}`（惰性化后不能读导入期声明值）"
    assert static_compares == [], (
        "不得拿导入期声明值 processor.NLP_ENGINE 做判据（恒真，探测不到 processor 侧加载失败）"
    )

    src = SCRIPT.read_text(encoding="utf-8")
    assert "get_spacy_nlp()" in src, "必须用生产 syntax_tree 自己的判定"
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(name.split(".")[0] == "spacy" for name in imported), (
        f"基准不得自行 import spacy 另判一套：{sorted(imported)}"
    )


class _FakeProcessor:
    """`_processor_path` 的注入替身：只提供它读的三个字段（不碰真实模型 / 不触发加载）。"""

    def __init__(self, nlp: object, resolved: bool, model: object) -> None:
        self.nlp = nlp
        self._nlp_resolved = resolved
        self._nlp_model = model


def _load_bench_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """按路径加载 tools/bench_rank_sentences.py（tools/ 非包，只能按路径加载）。

    它顶层 `from bench_stats import ...`，故先把 tools/ 临时放进 sys.path（monkeypatch 自动还原）。
    """
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("bench_rank_sentences_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_processor_path_reflects_real_load_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """③' 行为级：`_processor_path` 必须按**真实解析状态**判，而非导入期声明值。

    这是对 AST 结构门禁的**行为**补强：两类变异都会被它打红 ——
      - 改回读 `processor.NLP_ENGINE` 静态值 ⇒ 替身没有该属性 ⇒ 抛错转红；
      - 让「未解析」分支假装已解析 ⇒ 下一条「未解析须标声明值」不成立 ⇒ 断言转红。
    """
    mod = _load_bench_module(monkeypatch)
    processor_path = mod._processor_path

    assert processor_path(_FakeProcessor(nlp=None, resolved=False, model=None))[0] == "pure", (
        "nlp=None（红线 1 / Android）必须判为纯 Python"
    )

    declared_kind, declared_state = processor_path(_FakeProcessor(nlp=object(), resolved=False, model=None))
    assert declared_kind == "spacy", "未解析时按声明值标 spacy"
    assert "声明值" in declared_state and "未加载" in declared_state, (
        f"未解析必须**如实**标注为「声明值(模型未加载)」，实际：{declared_state}"
    )

    loaded_kind, loaded_state = processor_path(_FakeProcessor(nlp=object(), resolved=True, model=object()))
    assert loaded_kind == "spacy" and "已加载" in loaded_state, f"解析成功须标已加载：{loaded_state}"

    failed_kind, failed_state = processor_path(_FakeProcessor(nlp=object(), resolved=True, model=None))
    assert failed_kind == "pure" and "加载失败" in failed_state, (
        f"已解析为 None（加载失败）必须判为纯 Python：{failed_state}"
    )


def test_script_reuses_bench_stats() -> None:
    """③' p95/中位数口径必须来自 `tools/bench_stats.py`，不许各写一份（口径漂移）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "from bench_stats import" in src, "基准脚本必须复用 tools/bench_stats.py 的分位口径"
    assert "p95_ms" in src and "median_ms" in src, "必须用 bench_stats 的 p95_ms / median_ms"


def test_new_files_have_no_type_check_suppressions() -> None:
    """③'' 硬要求 6：新增文件里不得出现任何类型检查 / lint 豁免。"""
    for path in (SCRIPT, Path(__file__)):
        src = path.read_text(encoding="utf-8")
        for pattern in SUPPRESSION_RES:
            assert pattern.search(src) is None, f"{path.name} 含被禁的豁免注释：{pattern.pattern}"


def test_rounds_at_least_min(bench_out: str) -> None:
    """④ 采样轮数 ≥ 5（[Instinct: Median-Not-Mean]：少于 5 轮噪声压不住）。"""
    assert _number(bench_out, "rounds") >= 5.0, f"轮数 < 5，中位数口径不成立\n{bench_out}"


def test_unit_is_analyze_syntax_tree(bench_out: str) -> None:
    """④' 主口径必须是 `analyze_syntax_tree`（纯函数最小口径），两条口径都要在场。"""
    match = re.search(r"^unit=(analyze_syntax_tree|rank_sentences)$", bench_out, re.MULTILINE)
    assert match is not None, f"`unit=` 不可解析（只接受 analyze_syntax_tree|rank_sentences）\n{bench_out}"
    assert match.group(1) == "analyze_syntax_tree", f"主口径应为 analyze_syntax_tree：{match.group(1)}"
    for key in ("analyze_per_sentence_ms", "rank_per_sentence_ms"):
        assert _number(bench_out, key) > 0.0, f"`{key}` 非正：该口径没被测\n{bench_out}"


@pytest.mark.parametrize("key", NUM_KEYS)
def test_required_numeric_values_are_positive(key: str, bench_out: str) -> None:
    """⑤ 每条契约数值行都存在、可解析、且为正（防「计时段塌成 0」的恒真）。"""
    assert _number(bench_out, key) > 0.0, f"`{key}` 非正——计时段没真正跑到\n{bench_out}"


def test_p95_comes_from_the_same_sample_batch(bench_out: str) -> None:
    """⑥ p95 必须与中位数取自**同一批**样本，且样本数 == `*_p95_n`。

    逐条对照见 `tests/test_long_read_cost.py::test_p95_comes_from_the_same_sample_batch`：
    重算分位 + 物理边界（p95 ≥ median、p95 ≤ max）+ 样本数一致。
    """
    for p95_key, samples_key, median_key, n_key in P95_PAIRS:
        samples = _samples(bench_out, samples_key)
        n = int(_number(bench_out, n_key))
        assert len(samples) == n, (
            f"`{samples_key}` 样本数 {len(samples)} ≠ `{n_key}`={n}——p95 的 n 与样本行不一致\n{bench_out}"
        )
        p95 = _number(bench_out, p95_key)
        expected = statistics.quantiles(sorted(samples), n=100, method="inclusive")[94]
        assert p95 == pytest.approx(expected, abs=QUANTILE_ABS_TOL_MS), (
            f"`{p95_key}`={p95} 与样本重算值 {expected} 不符：不是同批样本算出来的\n{bench_out}"
        )
        median = _number(bench_out, median_key)
        assert p95 >= median - QUANTILE_ABS_TOL_MS, f"`{p95_key}`={p95} 低于中位数 {median}\n{bench_out}"
        assert p95 <= max(samples) + QUANTILE_ABS_TOL_MS, f"`{p95_key}`={p95} 超过样本最大值\n{bench_out}"


def test_sample_batch_sizes_match_rounds(bench_out: str) -> None:
    """⑥' 样本批量纲：analyze=rounds×sentences（逐句调用），rank=rounds（整段归一到每句）。"""
    rounds = int(_number(bench_out, "rounds"))
    sentences = int(_number(bench_out, "sentences"))
    assert len(_samples(bench_out, "samples_analyze_ms")) == rounds * sentences, (
        f"`samples_analyze_ms` 样本数应等于 rounds×sentences\n{bench_out}"
    )
    assert len(_samples(bench_out, "samples_rank_ms")) == rounds, (
        f"`samples_rank_ms` 样本数应等于 rounds（整段归一到每句）\n{bench_out}"
    )


def test_bucket_ms_ordering_is_sane(bench_out: str) -> None:
    """⑦ 句长三档都在，且长句档必须贵于短句档（句长是本路径的主自变量）。"""
    found: Dict[str, float] = {}
    for bucket in BUCKETS:
        found[bucket] = _number(bench_out, f"bucket_{bucket}_ms")
    assert found["short"] > 0.0, f"短句档耗时非正\n{bench_out}"
    assert found["long"] > found["short"], (
        f"长句档 {found['long']:.3f}ms 未贵于短句档 {found['short']:.3f}ms：句长分档或计时对象多半被改坏\n{bench_out}"
    )


def test_bucket_tokens_are_monotonic(bench_out: str) -> None:
    """⑦' 三档 **token 数** 必须单调（短 < 中 < 长）。

    只断言耗时单调有个洞：耗时差可能只是噪声。token 数才是句长的直接刻度。
    """
    counts: Dict[str, float] = {}
    for bucket in BUCKETS:
        counts[bucket] = _number(bench_out, f"tokens_per_bucket_{bucket}")
    assert counts["short"] > 0.0, f"短档 token 数非正：{counts}\n{bench_out}"
    assert counts["short"] < counts["mid"] < counts["long"], (
        f"档位 token 数不单调（短/中/长 = {counts['short']:.0f}/{counts['mid']:.0f}/"
        f"{counts['long']:.0f}）——三档句长这个自变量没被真正钉住\n{bench_out}"
    )


def test_corpus_is_real_german(bench_out: str) -> None:
    """⑧ 语料是真实德语：白名单式形态标记（德语功能词 + 变音符号/ß）。"""
    lower = _corpus_text().lower()
    hits = [w for w in ("der", "die", "das", "und", "ist") if re.search(rf"\b{w}\b", lower)]
    assert len(hits) >= 3, f"语料里德语功能词只命中 {hits}（少于 3 个）——语料疑似被换成非德语\n{bench_out}"
    assert re.search(r"[äöüß]", lower), "语料里没有 ä/ö/ü/ß ——不像德语语料"
    assert _number(bench_out, "sentences") >= 9.0, f"语料句数少于 9（三档各 ≥3 句）\n{bench_out}"


def test_nlp_path_is_parsable(bench_out: str) -> None:
    """⑨ `nlp_path` 必出且可解析（spaCy 不可用时静默降级为纯 Python）。"""
    match = re.search(r"^nlp_path=(spacy|pure)$", bench_out, re.MULTILINE)
    assert match is not None, f"`nlp_path` 不可解析（只接受 spacy|pure）\n{bench_out}"
    path = match.group(1)
    verdict = re.search(r"^verdict=(.+)$", bench_out, re.MULTILINE)
    assert verdict is not None, bench_out
    text = verdict.group(1)
    assert f"nlp_path={path}" in text, f"verdict 必须带上 nlp_path 标注：{text}"
    if path == "pure":
        for required in ("spaCy 不可用", "纯 Python", "对照不成立"):
            assert required in text, f"pure 下 verdict 必须明说对照不成立（缺 `{required}`）：{text}"


def test_model_line_present_and_parsable(bench_out: str) -> None:
    """⑨' `model=` 必出、可解析为**非空**字符串（实际生效模型口径必须可复核）。

    ② 席位红线：脚本此前**从不**打印实际生效的模型名，而 verdict 里"md（带词向量）口径
    未测"这一措辞隐含"本环境不是 md"。可 `get_spacy_nlp()`（``syntax_tree.py``）先试
    ``de_core_news_md``、失败才退 ``de_core_news_sm`` ⇒ 本环境**很可能本来就在 md 上测**，
    这个前提此前**不可复核**。故必须照抄 ``bench_spacy_unit.py`` 的口径打印 ``model=``。
    """
    match = re.search(r"^model=(.+)$", bench_out, re.MULTILINE)
    assert match is not None, f"输出缺少 `model=<实际生效模型名>` 行\n{bench_out}"
    model = match.group(1).strip()
    assert model, f"`model=` 为空串：模型口径不可复核\n{bench_out}"
    assert model == "pure-python" or model.startswith("de_core_news_"), (
        f"`model=` 不可解析为已知口径（应为 de_core_news_* 或 pure-python）：{model!r}\n{bench_out}"
    )


def test_p95_note_declares_incomparable_aggregation(bench_out: str) -> None:
    """⑨'' `p95_note=` 必须显式声明两条 p95 **不可直接比较/相除**。

    两条 p95 的**聚合单元**与**样本量**都不同：``analyze_p95_ms`` 是单句调用的尾部
    （n=rounds×sentences），``rank_p95_ms`` 是整段归一每句的尾部（n=rounds）。verdict
    只引中位数（正确），但相邻两行 p95 会引诱读者相除 ⇒ 必须就地声明不可比。
    """
    match = re.search(r"^p95_note=(.+)$", bench_out, re.MULTILINE)
    assert match is not None, f"输出缺少 `p95_note=` 行\n{bench_out}"
    note = match.group(1)
    for required in ("聚合", "样本", "不可"):
        assert required in note, f"`p95_note` 未声明两条 p95 不可比（缺 `{required}`）：{note}"


def test_model_load_precedes_timing_and_body_is_pure() -> None:
    """⑨''' 源码顺序：模型加载（``get_spacy_nlp()``）必须早于**计时段**；脚本体不碰 DB。

    两条不变量此前只靠人读代码：

    1. **模型加载在计时之外**：若把 ``get_spacy_nlp()`` 挪进计时段，单句单价会把一次性
       模型加载摊进去、与历史值对照失真 ⇒ 用 AST 取真实**调用**行号，断言它在
       ``_measure_analyze`` 计时段之前（用 AST 而非 ``src.index``：docstring/注释里的同名
       文本会喂出假绿）。
    2. **纯函数口径**：脚本**不**出现 ``_material_text``（端点读 DB 正文的入口）⇒ 本基准
       不经 DB/端点，与端到端口径的分野由此钉住。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    nlp_line = _first_call_line(tree, "get_spacy_nlp")
    measure_line = _first_call_line(tree, "_measure_analyze")
    assert nlp_line < measure_line, (
        f"`get_spacy_nlp()` 调用（第 {nlp_line} 行）必须早于 `_measure_analyze` 计时段"
        f"（第 {measure_line} 行）——否则模型冷加载会被摊进单句单价"
    )
    assert "_material_text" not in src, (
        "脚本体出现 `_material_text`（端点读 DB 正文的入口）：纯函数口径被破"
    )


def test_verdict_names_three_legacy_values_and_scope(bench_out: str) -> None:
    """⑩ `verdict=` 必须点名三个对照数（42ms / 2.1ms / 端到端≈10ms）并写明口径不可相除。

    只报区间不给判定等于把活推回给读者；且必须**明说**本测值落在哪一侧、以及是否足以解释
    那个 20 倍差距（不足以定案就明说不足）。
    """
    matches = re.findall(r"^verdict=(.+)$", bench_out, re.MULTILINE)
    assert matches, f"输出里找不到 `verdict=` 结论行\n{bench_out}"
    verdict = matches[-1]
    for required in (
        LEGACY_SYNTAX_HARD,
        LEGACY_AUDIT,
        LEGACY_LONG_READ,
        "不可直接相除",
        "rank_sentences",
        "analyze_syntax_tree",
        "process_german_text",
        "20 倍",
        "足以",
        "落在",
    ):
        assert required in verdict, f"结论缺少 `{required}`：{verdict}"
    assert "见上文" not in verdict and "见下文" not in verdict, f"结论是空话，不是可判定结论\n{verdict}"
