# -*- coding: utf-8 -*-
"""长文精读冷/热读基准的可执行输出门禁。"""

import ast
import importlib.util
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Pattern, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_long_read.py"
NUMERIC_KEYS = (
    "cold_ms",
    "warm_ms",
    "cache_speedup",
    "sentences",
    "tokens",
    "spacy_ms",
    "other_ms",
    "rounds",
)
POSITIVE_KEYS = (
    "cold_ms",
    "warm_ms",
    "cache_speedup",
    "sentences",
    "tokens",
    "spacy_ms",
    "rounds",
)
# Task 5b 新增：p95 必须与中位数同批样本，且样本行可独立重算分位（同
# test_cards_endpoint_cost.py 的纪律：只给 p95 数字不给样本 = 不可复核）。
P95_PAIRS = (("cold_p95_ms", "samples_cold_ms", "cold_ms"), ("warm_p95_ms", "samples_warm_ms", "warm_ms"))
SAMPLES_RE_TEMPLATE = r"^{key}=([0-9.]+(?:,[0-9.]+)+)$"
QUANTILE_ABS_TOL_MS = 1e-5

SUPPRESSION_RES: tuple[Pattern[str], ...] = (
    re.compile(r"type:\s*ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"mypy:\s*disable-error-code"),
)


def _run_bench(tmp_path: Path) -> str:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "BENCH_LONG_READ_ROUNDS": "5",
            "DELECTOR_DATA_DIR": str(tmp_path / "outer_data"),
            "DATABASE_PATH": str(tmp_path / "outer_delector.db"),
            "PROGRESS_DB_PATH": str(tmp_path / "outer_progress.db"),
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
        f"基准退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


@pytest.fixture(scope="module")
def bench_out(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _run_bench(tmp_path_factory.mktemp("bench_long_read_gate"))


def _number(out: str, key: str) -> float:
    # 数值段仍须严格可解析，但允许科学计数法（cache_speedup 只报 2 位有效数字）与
    # 行尾中文注解（other_ms 等被标成近似值时不改键名，避免破坏既有门禁）。
    match = re.search(
        rf"^{key}=(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?:\s|$)",
        out,
        re.MULTILINE,
    )
    assert match is not None, f"输出缺少 `{key}=N`\n{out}"
    return float(match.group(1))


def _raw_value(out: str, key: str) -> str:
    match = re.search(rf"^{key}=(\S+)$", out, re.MULTILINE)
    assert match is not None, f"输出缺少单行 `{key}=<值>`\n{out}"
    return match.group(1)


def _significant_digits(raw: str) -> int:
    """有效数字位数：用于钉住"不许打印伪精度"（cache_speedup 曾给到 .017）。"""
    mantissa = raw.lower().split("e")[0].lstrip("+-").replace(".", "").lstrip("0")
    return len(mantissa.rstrip("0")) or 1


def _called_names(tree: ast.AST) -> set[str]:
    """收集被调用的名字：既收 `f(...)`，也收 `a.f(...)` 的属性名。

    只收 `ast.Name` 时 `database.ingest_article(...)` 这类属性调用能整体绕过门禁，
    门禁会假绿——故属性调用形式必须一并收集。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _corpus_text(src: str) -> str:
    tree = ast.parse(src)
    chunks: List[str] = []
    for node in tree.body:
        name = ""
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name != "LONG_ARTICLE_SENTENCES" or value is None:
            continue
        chunks.extend(
            item.value
            for item in ast.walk(value)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    assert chunks, "脚本中找不到 LONG_ARTICLE_SENTENCES 字面量"
    return " ".join(chunks)


def test_script_exists_and_declares_contract() -> None:
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"
    src = SCRIPT.read_text(encoding="utf-8")
    for key in (
        *NUMERIC_KEYS,
        "cache_effective",
        "spacy_pct",
        "verdict",
        "nlp_path",
        "cache_items_identical",
        "cache_clear_verified",
        "approx_note",
        "cold_p95_ms",
        "warm_p95_ms",
        "samples_cold_ms",
        "samples_warm_ms",
    ):
        assert f'print(f"{key}=' in src, f"源码没有真实打印 `{key}=`"


def test_script_isolated_before_delector_import_and_cleans_up() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("delector")
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith("delector") for alias in node.names)
    assert "tempfile.mkdtemp" in src
    assert all(key in src for key in ("DELECTOR_DATA_DIR", "DATABASE_PATH", "PROGRESS_DB_PATH"))
    assert "finally:" in src and "shutil.rmtree" in src
    assert src.index("_bootstrap_env(tmpdir)") < src.index('import_module("delector.')


def test_seed_is_direct_sql_and_does_not_call_ingest() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert "INSERT INTO articles" in src, "造数必须直接写 articles，绕开 NLP"
    assert not any("ingest" in name.lower() for name in _called_names(ast.parse(src)))


def test_ingest_guard_covers_attribute_calls() -> None:
    """门禁自身的回归：属性调用形式必须被收集，否则上一条门禁会假绿。

    只收集 `ast.Name` 的实现对 `database.ingest_article(...)` 完全失明——
    门禁通过不等于造数真的绕开了 NLP，故这条钉的是收集器本身。
    """
    names = _called_names(ast.parse("import database\ndatabase.ingest_article(1)\n"))
    assert "ingest_article" in names


def _processor_path_reads_and_compares() -> Tuple[set[str], List[ast.Compare]]:
    """解析 `_processor_path` 的**真实代码**：返回（属性读名集合, 静态引擎比较列表）。

    用 AST 而非子串：docstring 里提到字段名（``_nlp_resolved`` 等）也会命中子串，那样的门禁
    对"是否真读状态"无证明力（="随便含个词就过"）—— 故只在**属性访问 / 比较**节点上判定。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_processor_path" in funcs, "processor 侧判据必须收在 _processor_path（与 bench_cold_start 同口径）"
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
    """路径判定必须复用生产判据：基准自己 import spacy 判一次会与生产分叉。

    processor 侧**不再**断言 `NLP_ENGINE`（惰性化后它是导入期声明值、恒为 "spacy"，拿它判
    等于恒真、探测不到加载失败 —— 这正是本文件曾漏改的缺陷）。改钉**真实**判据（AST 属性读，
    非子串——docstring 提到字段名不算数）：
      - `_processor_path` 体内必须**真读** `processor.nlp` / `_nlp_resolved` / `_nlp_model`；
      - **不得**出现 `processor.NLP_ENGINE == ...` 这种静态声明值比较。
    对"改回读 NLP_ENGINE 静态值"与"让未解析分支假装已解析"两类变异都**必红**（见 3A 回执）。
    """
    reads, static_compares = _processor_path_reads_and_compares()
    for field in ("nlp", "_nlp_resolved", "_nlp_model"):
        assert field in reads, (
            f"_processor_path 必须真读 `processor.{field}`（惰性化后不能读导入期声明值）"
        )
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
    """按路径加载 tools/bench_long_read.py（tools/ 非包，只能按路径加载）。

    它顶层 `from bench_stats import ...`，故先把 tools/ 临时放进 sys.path（monkeypatch 自动还原）。
    """
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("bench_long_read_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_processor_path_reflects_real_load_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """行为级：`_processor_path` 必须按**真实解析状态**判，而非导入期声明值。

    这是对 AST 结构门禁的**行为**补强：两类变异都会被它打红 ——
      - 改回读 `processor.NLP_ENGINE` 静态值 ⇒ 替身没有该属性 ⇒ 抛错转红；
      - 让"未解析"分支假装已解析 ⇒ 下一条「未解析须标声明值」不成立 ⇒ 断言转红。
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


def test_new_files_have_no_type_check_suppressions() -> None:
    for path in (SCRIPT, Path(__file__)):
        src = path.read_text(encoding="utf-8")
        for pattern in SUPPRESSION_RES:
            assert pattern.search(src) is None, f"{path.name} 含禁用豁免：{pattern.pattern}"


@pytest.mark.parametrize("key", POSITIVE_KEYS)
def test_required_numeric_values_are_positive(key: str, bench_out: str) -> None:
    assert _number(bench_out, key) > 0.0, f"`{key}` 必须为正\n{bench_out}"


def test_rounds_and_real_german_article(bench_out: str) -> None:
    assert _number(bench_out, "rounds") >= 5.0
    assert _number(bench_out, "sentences") >= 8.0
    assert _number(bench_out, "tokens") >= 200.0
    corpus = _corpus_text(SCRIPT.read_text(encoding="utf-8")).lower()
    hits = [word for word in ("der", "die", "das", "und", "ist") if re.search(rf"\b{word}\b", corpus)]
    assert len(hits) >= 3 and re.search(r"[äöüß]", corpus)


def test_cache_classification_matches_measured_relationship(bench_out: str) -> None:
    cold = _number(bench_out, "cold_ms")
    warm = _number(bench_out, "warm_ms")
    match = re.search(r"^cache_effective=(yes|no|unknown)$", bench_out, re.MULTILINE)
    assert match is not None, f"cache_effective 不可解析\n{bench_out}"
    effective = match.group(1)
    if warm < cold * 0.9:
        assert effective == "yes" and warm < cold * 0.9
    elif warm >= cold:
        assert effective == "no" and "缓存未生效" in bench_out
    else:
        assert effective == "unknown" and cold * 0.9 <= warm < cold
    speedup = _number(bench_out, "cache_speedup")
    assert speedup == pytest.approx(cold / warm, rel=0.03)


def test_cost_breakdown_and_verdict_are_honest(bench_out: str) -> None:
    cold = _number(bench_out, "cold_ms")
    spacy = _number(bench_out, "spacy_ms")
    other = _number(bench_out, "other_ms")
    pct_match = re.search(r"^spacy_pct=([0-9]+(?:\.[0-9]+)?)%$", bench_out, re.MULTILINE)
    assert pct_match is not None, f"spacy_pct 不可解析\n{bench_out}"
    assert other == pytest.approx(cold - spacy, abs=0.01)
    assert float(pct_match.group(1)) == pytest.approx(spacy / cold * 100.0, abs=0.2)
    verdict = re.search(r"^verdict=(.+)$", bench_out, re.MULTILINE)
    assert verdict is not None
    text = verdict.group(1)
    for required in ("syntax_hard.py:9", "42ms/句", "process_german_text", "rank_sentences", "不可直接比较"):
        assert required in text, f"verdict 缺少 `{required}`：{text}"


def test_p95_comes_from_the_same_sample_batch(bench_out: str) -> None:
    """冷/热读 p95 必须与各自中位数取自同一批样本，且不得是中位数本身。

    逐条对照见 `test_cards_endpoint_cost.py::test_bench_output_reports_p95_over_the_
    same_samples` 的说明：重算分位 + 物理边界（p95 ≥ median、p95 ≤ max）。
    """
    rounds = int(_number(bench_out, "rounds"))
    for p95_key, samples_key, median_key in P95_PAIRS:
        samples_match = re.search(
            SAMPLES_RE_TEMPLATE.format(key=samples_key), bench_out, re.MULTILINE
        )
        assert samples_match is not None, f"输出缺少 `{samples_key}=<逗号分隔>` 样本行\n{bench_out}"
        samples = [float(item) for item in samples_match.group(1).split(",")]
        assert len(samples) == rounds, f"`{samples_key}` 样本数 {len(samples)} ≠ rounds={rounds}\n{bench_out}"
        p95 = _number(bench_out, p95_key)
        expected = statistics.quantiles(sorted(samples), n=100, method="inclusive")[94]
        assert p95 == pytest.approx(expected, abs=QUANTILE_ABS_TOL_MS), (
            f"`{p95_key}`={p95} 与样本重算值 {expected} 不符：不是同批样本算出来的\n{bench_out}"
        )
        median = _number(bench_out, median_key)
        assert p95 >= median - QUANTILE_ABS_TOL_MS, f"`{p95_key}`={p95} 低于中位数 {median}\n{bench_out}"
        assert p95 <= max(samples) + QUANTILE_ABS_TOL_MS, f"`{p95_key}`={p95} 超过样本最大值\n{bench_out}"


def test_p95_rounds_are_env_tunable() -> None:
    """轮数必须可提（n=5 的 p95≈最大值、系统性低估尾部 ⇒ 判强结论需要 n≥20）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "BENCH_P95_ROUNDS" in src, "基准脚本必须支持 BENCH_P95_ROUNDS 提高 p95 样本量"


def test_cache_speedup_has_no_false_precision(bench_out: str) -> None:
    """分母 warm_ms 是微秒级 dict 命中（抖动 ±10%），比值不许打印成 .017 这种伪精度。"""
    raw = _raw_value(bench_out, "cache_speedup")
    assert _significant_digits(raw) <= 3, f"cache_speedup 有效数字过多：{raw}"
    note = re.search(r"^approx_note=(.+)$", bench_out, re.MULTILINE)
    assert note is not None, f"缺少分母抖动/近似口径说明\n{bench_out}"
    assert "±10%" in note.group(1) and "数量级" in note.group(1), note.group(1)
    assert "仅量级参考" in note.group(1), note.group(1)


def test_cache_items_identical_is_gated(bench_out: str) -> None:
    """只证"快"不够：热读必须返回与冷读相同的 items，否则缓存是错的（比慢更严重）。"""
    match = re.search(r"^cache_items_identical=(yes|no)$", bench_out, re.MULTILINE)
    assert match is not None, f"cache_items_identical 不可解析\n{bench_out}"
    assert match.group(1) == "yes", "热读与冷读返回不一致：缓存正确性先于性能\n{0}".format(bench_out)


def test_cache_clear_is_verified_as_miss(bench_out: str) -> None:
    """清空后必须能断言该材料键确实 miss，否则"冷读"测的可能不是冷读。"""
    match = re.search(r"^cache_clear_verified=(yes|no)$", bench_out, re.MULTILINE)
    assert match is not None, f"cache_clear_verified 不可解析\n{bench_out}"
    assert match.group(1) == "yes", bench_out


def test_nlp_path_is_declared_and_verdict_carries_it(bench_out: str) -> None:
    """不声明走哪条 NLP 路径，spacy_ms 与历史值 42ms/句的对照就会在无人察觉时整体失真。"""
    match = re.search(r"^nlp_path=(spacy|pure)$", bench_out, re.MULTILINE)
    assert match is not None, f"nlp_path 不可解析（只接受 spacy|pure）\n{bench_out}"
    path = match.group(1)
    verdict = re.search(r"^verdict=(.+)$", bench_out, re.MULTILINE)
    assert verdict is not None, bench_out
    text = verdict.group(1)
    assert f"nlp_path={path}" in text, f"verdict 必须带上 nlp_path 标注：{text}"
    if path == "pure":
        for required in ("spaCy 不可用", "纯 Python 降级", "对照不成立"):
            assert required in text, f"pure 下 verdict 必须明说对照不成立（缺 `{required}`）：{text}"
