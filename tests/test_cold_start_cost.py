# -*- coding: utf-8 -*-
"""冷启动基准 `tools/bench_cold_start.py` 的输出结构与隔离门禁。

钉住什么
--------
Task 4（冷启动基准）的交付物是「进程起到**可服务**」的各段耗时，其中
`health_200_ms`（子进程真实起 uvicorn + 轮询 `/api/health` 到 200 的墙钟）是
**用户体感主指标**（双击 exe 之后多久能用）。故本文件把五件事钉成断言：

1. 脚本存在，且输出含**五个可解析的正数分段**（`import_ms` / `init_db_ms` /
   `app_ready_ms` / `health_200_ms` / `model_load_ms`）；
2. **轮数 ≥ 5**（`MIN_ROUNDS`），中位数口径才站得住；
3. **端口不硬编码 8000**：会撞用户正在跑的实例、并发跑测试也会互撞 ⇒ 必须动态取
   空闲端口（源码级断言：`bind(("127.0.0.1", 0))` + `getsockname`，且全文无 8000）；
4. **子进程也要隔离**：三个数据环境变量必须由父进程传给子进程（源码级断言子进程
   环境构造函数），并由**行为**佐证 —— 子进程确实把 `.cache/audio` 建在了临时数据
   目录里（`child_isolation_verified=yes`），且仓库根真实 `delector.db` 未被改动
   （`repo_db_untouched` 不得为 `no`）；
5. `nlp_path` 可解析为 `spacy|pure`，`android=unmeasured` 明写（`[Instinct:
   No-Silent-Conclusion]`：本机无 Android SDK，30MB 解包不可测，**不得编造**）。

为什么**不钉绝对毫秒阈值**（`[Instinct: Flaky-Aware]`）
------------------------------------------------------
冷启动对磁盘缓存 / 杀毒软件 / 机器负载极敏感，同一台机器相邻两次能差 2 倍以上。
钉绝对阈值 ⇒ CI 假红。故本文件**只钉可解析 + 正区间 + 状态无关的不变式**：
- `import_ms` 与 `app_ready_ms` 的**同进程**关系（二者都在 probe B 内测得，`[Instinct:
  Flaky-Aware]`），钉**无条件**严格不等式 `import_ms > app_ready_ms`（见 ⑫
  `_assert_segment_containment`）。**为什么无条件成立**（结构性理由，照抄不删）：
  `import_ms` = `import delector.server` 的墙钟 = 【**整个模块图导入**】 + 模块级
  `app = create_app()`（`server.py:356`）；`app_ready_ms` = 其后对全新库的**第二次**
  `create_app()` ⇒ 只含 1 次 `create_app()`、不含模块图。故
  `import_ms − app_ready_ms ≈ T_模块图 + (两次 create_app 的成本差 ≈ 0) ≈ T_模块图 > 0`。
  `T_模块图` 恒为正且非噪声级（几百 ms，含 fastapi/starlette/pydantic 与整个 `delector`
  包），**与 spaCy 是否可用无关** —— spaCy 模型加载只是模块图里的一块，去掉它只是让余量
  从 ~1.5s 降到 ~670ms，**不改变符号**。
  **为什么不分叉（本次纠错，勿再改回）**：曾误以为 pure 路径余量会塌到噪声级、转而钉
  「同量级比值带 `import_ms / app_ready_ms ∈ [0.2, 10.0]`」。但该上界要求
  `T_模块图 ≤ 9 × T_create_app`，而二者由**完全不同的资源**决定（模块图 ∝ 模块数 × 每模块
  成本，不随库/盘变快等比缩小；`create_app` ∝ SQLite DDL + 预置导入，对 tmpfs / 暖缓存极
  敏感）⇒ **无结构耦合**，健康机器上也可能 ratio > 10 打红（反例：`T_create_app≈60ms`、
  `T_模块图≈600ms` ⇒ ratio≈11；历史 CI 数据里 `app_ready_ms` 会从本机 250ms 掉到 95ms，
  模块图开销却不跟着缩）。实测也推翻该假设：pure 下比值 ≈4.6、余量 ≈670ms 仍稳健 ⇒ 撤回
  比值带，回到无条件严格不等式。
- `app_ready_db_tables >= 1` / `app_ready_progress_tables >= 1` / `init_db_tables >= 1` /
  `init_db_progress_tables >= 1` / `app_ready_fresh_db_used == yes`：
  probe A 的 `init_db()` 与 probe B 的第二次 `create_app()` 都必须在**全新库**上真建出表
  （守卫**对称**：probe A / probe B 两侧都设，避免只在一侧无设防）。表要么在、要么不在，与
  机器 / 缓存无关 —— `0` 就说明那段被打了桩、或「冷库装配」的标注在撒谎，**必须红**。这才是
  **防恒真**的那条。

刻意**不钉**跨进程量级关系（`app_ready_ms > init_db_ms`、`model_load_ms <= import_ms`）：
`init_db_ms` / `model_load_ms` 来自 probe A，`app_ready_ms` / `import_ms` 来自 probe B，是
**两个进程、不同前置状态**（probe B 在 import 期已跑过一次完整 `create_app()`，进程级与文件
系统级缓存已热），**不存在必然的大小关系**（本机同向、CI 反向，见 `segments_note`）。

一条**例外**（⑬ `test_health_200_covers_whole_startup`）：它是**跨进程**比较（`health_200_ms`
来自 probe C、`import_ms` 来自 probe B），本不属"同进程不变式"。之所以保留，是因为 `health_200_ms`
的那一次起服务里**本就含一次冷 import**，故它必须 ≥ import 段的一半；机器抖动用 `0.5` 松弛兜底，
只钉 `> import_ms * 0.5` 这一条**弱下界**、不钉绝对量级。这是"`health_200` 不是空转"的唯一守卫，
故不删。

门禁跑的是快档（`BENCH_COLD_START_ROUNDS=5`，下限也是 5）。
"""

import ast
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Pattern

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_cold_start.py"

# 契约行：与基准脚本的输出一一对应。缺任一 ⇒ 分段拆解塌回单段数字。
NUMERIC_KEYS = ("import_ms", "init_db_ms", "app_ready_ms", "health_200_ms", "model_load_ms")
POSITIVE_KEYS = NUMERIC_KEYS

GATE_ROUNDS = "5"

# Task 5b 新增：health_200 的 p95 必须与中位数同批样本（样本行供独立重算分位）。
SAMPLES_HEALTH_RE = re.compile(r"^samples_health_200_ms=([0-9.]+(?:,[0-9.]+)+)$", re.MULTILINE)
# 冷启动是秒级量，p95 按 2 位小数打印（与 health_200_ms 同精度）⇒ 容差取 0.01ms。
QUANTILE_ABS_TOL_MS = 1e-2

SUPPRESSION_RES: tuple[Pattern[str], ...] = (
    re.compile(r"type:\s*ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"mypy:\s*disable-error-code"),
)

# Android 侧已知口径（docs/agents/architecture.md:100-101）：Chaquopy 首次启动解包
# 约 30MB、启动页轮询上限约 84 秒。verdict 必须点名它们，且本机不可测要写明。
ANDROID_TOKENS = ("Android", "30MB", "84000", "android=unmeasured")


def _run_bench(tmp_path: Path, env_extra: Optional[Dict[str, str]] = None) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文。

    `env_extra` 用于注入额外环境（如用 `raise ImportError` 的假 `spacy` 桩逼出纯 Python
    降级路径，见 `test_segment_containment_is_visible_on_pure_python_path`）：环境由
    `dict(os.environ)` 派生，故注入的键会随 env 传播到基准的每个子进程。
    """
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "BENCH_COLD_START_ROUNDS": GATE_ROUNDS,
            # 双保险：即便脚本自身有 bug，父进程这一层也把库路径钉在临时目录。
            "DELECTOR_DATA_DIR": str(tmp_path / "outer_data"),
            "DATABASE_PATH": str(tmp_path / "outer_delector.db"),
            "PROGRESS_DB_PATH": str(tmp_path / "outer_progress.db"),
        }
    )
    if env_extra:
        env.update(env_extra)
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
    return _run_bench(tmp_path_factory.mktemp("bench_cold_start_gate"))


def _number(out: str, key: str) -> float:
    match = re.search(rf"^{key}=(-?[0-9]+(?:\.[0-9]+)?)$", out, re.MULTILINE)
    assert match is not None, f"输出缺少可解析的 `{key}=N.NN`\n{out}"
    return float(match.group(1))


def _top_level_imports(tree: ast.Module) -> List[str]:
    names: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"


def test_script_declares_contract_lines() -> None:
    """① 输出行必须真被 `print(f"...")` 打印出来（docstring 里的契约块不算）。

    钉 `print(f"` 前缀而不是裸字面量：后者在模块 docstring 里也出现 ⇒ 即使 print 行
    被删，断言照样绿（半恒真）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for key in (
        *NUMERIC_KEYS,
        "init_db_tables",
        "init_db_progress_tables",
        "rounds",
        "nlp_path",
        "verdict",
        "android",
        "health_200_p95_ms",
        "samples_health_200_ms",
    ):
        assert f'print(f"{key}=' in src, f"源码没有真实打印 `{key}=`"


def test_script_isolated_before_delector_import_and_cleans_up() -> None:
    """② 隔离纪律（`[Instinct: Isolated-DB]`）：delector 只能在函数内导入。

    本脚本的 delector 导入**全部发生在子进程**，父进程一个都不做，故用 AST 断言
    「模块级没有 delector 导入」——这是比「源码含 mkdtemp」更强的证据。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert not any(name.split(".")[0] == "delector" for name in _top_level_imports(tree)), (
        f"模块级不得 import delector（会抢在 _bootstrap_env 之前跑）：{_top_level_imports(tree)}"
    )
    assert "tempfile.mkdtemp" in src, "必须用 tempfile.mkdtemp() 建隔离数据目录"
    assert all(key in src for key in ("DELECTOR_DATA_DIR", "DATABASE_PATH", "PROGRESS_DB_PATH"))
    assert "shutil.rmtree" in src and "finally:" in src, "必须在 finally 里清理临时目录"


def test_probe_paths_require_inherited_isolation() -> None:
    """③ 子进程自己也要自检隔离环境：父进程漏传 env 时子进程必须响亮失败。

    只钉「父进程构造了 env」不够 —— 那不能证明子进程真的收到了。故要求每个会
    import delector 的子进程入口函数**第一行**就调 `_require_isolated_env()`。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "_require_isolated_env()" in src
    for fn in ("_probe_model_and_initdb", "_probe_import_and_app_ready", "_serve"):
        assert f"def {fn}(" in src, f"缺少子进程入口函数 {fn}"
        body = src.split(f"def {fn}(", 1)[1]
        guard = body.index("_require_isolated_env()")
        imports = min(
            index
            for index in (
                body.find('import_module("delector'),
                body.find('import_module(\n'),
                len(body) - 1,
            )
            if index >= 0
        )
        assert guard < imports, f"{fn} 必须先自检隔离环境再 import delector"


def test_child_env_carries_all_three_paths() -> None:
    """④ 子进程环境必须带上三个数据路径（否则污染仓库根 `.cache/audio` 与真实库）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "_child_env(" in src, "缺少子进程环境构造函数"
    segment = src.split("def _child_env(", 1)[1][:800]
    for key in ("DELECTOR_DATA_DIR", "DATABASE_PATH", "PROGRESS_DB_PATH"):
        assert key in segment, f"子进程环境没有带上 {key}"


def test_port_is_dynamic_not_8000() -> None:
    """⑤ 端口不得硬编码 8000：会撞用户正在跑的实例，并发跑测试也会互撞。

    只搜**代码**不搜 docstring：docstring 里必须解释「为什么不能用 8000」，那句话
    本身就含 8000（搜全文会让这条断言恒红，逼人删掉这条有用的说明）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(src)) or ""
    code = src.replace(docstring, "", 1)
    assert re.search(r"\b8000\b", code) is None, "代码里出现硬编码端口 8000"
    assert 'bind((_HOST, 0))' in src or 'bind(("127.0.0.1", 0))' in src, "必须 bind 到 port 0 取系统分配端口"
    assert "getsockname" in src, "必须从 bind(0) 的 socket 取回实际端口"


def test_new_files_have_no_type_check_suppressions() -> None:
    for path in (SCRIPT, Path(__file__)):
        src = path.read_text(encoding="utf-8")
        for pattern in SUPPRESSION_RES:
            assert pattern.search(src) is None, f"{path.name} 含禁用豁免：{pattern.pattern}"


@pytest.mark.parametrize("key", POSITIVE_KEYS)
def test_required_numeric_values_are_positive(key: str, bench_out: str) -> None:
    """⑥ 五个分段都必须可解析且为正 —— 值为 0 说明那段根本没跑到（防恒真的底座）。"""
    assert _number(bench_out, key) > 0.0, f"`{key}` 必须为正\n{bench_out}"


def test_rounds_at_least_five(bench_out: str) -> None:
    """⑦ 中位数口径要求 ≥ 5 轮（[Instinct: Median-Not-Mean]）。"""
    assert _number(bench_out, "rounds") >= 5.0, f"轮数不足 5\n{bench_out}"


def test_nlp_path_is_declared(bench_out: str) -> None:
    """⑧ 不声明 NLP 路径，冷启动数字在降级机器上会被误读成 spaCy 口径。"""
    match = re.search(r"^nlp_path=(spacy|pure)$", bench_out, re.MULTILINE)
    assert match is not None, f"nlp_path 不可解析（只接受 spacy|pure）\n{bench_out}"


def test_nlp_path_label_matches_between_probes(bench_out: str) -> None:
    """⑧' 路径标签与计时必须**同源**：A/B 两个探针各自报自己的标签，且必须一致。

    为什么钉：`import_ms` / `app_ready_ms` 来自 **probe B**，而汇总输出的 `nlp_path` 只由
    **probe A** 计算。若两进程判定分叉（例如模型自动下载在 A 成功、B 失败），门禁会拿 **A 的
    标签**去判 **B 的时序**而无人知晓。故这里要求 probe B 也打印**它自己的**标签，并断言 A 与 B
    **一致** —— 不一致即红。

    这是**类别一致性**断言（比的是标签 `spacy|pure`，不是量级），与「跨进程量级比较」（本文件
    刻意不钉的那类）不是同类问题，故允许且应该钉。
    """
    labels = {}
    for probe in ("a", "b"):
        match = re.search(rf"^nlp_path_probe_{probe}=(spacy|pure)$", bench_out, re.MULTILINE)
        assert match is not None, (
            f"缺少可解析的 `nlp_path_probe_{probe}=(spacy|pure)` 行：无法证明标签与计时同源\n{bench_out}"
        )
        labels[probe] = match.group(1)
    top = re.search(r"^nlp_path=(spacy|pure)$", bench_out, re.MULTILINE)
    assert top is not None, f"nlp_path 不可解析（只接受 spacy|pure）\n{bench_out}"
    assert labels["a"] == labels["b"], (
        f"probe A 标签 nlp_path_probe_a={labels['a']} 与 probe B 标签 nlp_path_probe_b={labels['b']} "
        f"不一致：门禁会拿 A 的标签去判 B 的时序，标签与计时不同源\n{bench_out}"
    )
    assert top.group(1) == labels["a"], (
        f"顶层 nlp_path={top.group(1)} 与 nlp_path_probe_a={labels['a']} 不一致\n{bench_out}"
    )


def test_android_is_declared_unmeasured(bench_out: str) -> None:
    """⑨ Android 侧本机不可测 ⇒ 必须明写 `android=unmeasured` 并给原因，不得编造。"""
    assert re.search(r"^android=unmeasured$", bench_out, re.MULTILINE) is not None, (
        f"缺少 `android=unmeasured` 行\n{bench_out}"
    )
    note = re.search(r"^android_note=(.+)$", bench_out, re.MULTILINE)
    assert note is not None, f"缺少 android_note 原因行\n{bench_out}"
    assert "Android SDK" in note.group(1), f"android_note 必须写明本机缺 Android SDK：{note.group(1)}"


def test_child_process_isolation_is_verified_behaviourally(bench_out: str) -> None:
    """⑩ 子进程隔离要靠**行为**佐证：它必须把 `.cache/audio` 建在临时数据目录里。

    源码里有三个 env 键 ≠ 子进程收到了（父进程漏传就会静默写回仓库根）。本断言用
    脚本自报的 `child_isolation_verified=yes`（父进程在清理 tmpdir 前检查该目录是否
    被子进程创建）把这条纪律变成可执行断言。
    """
    match = re.search(r"^child_isolation_verified=(yes|no)$", bench_out, re.MULTILINE)
    assert match is not None, f"缺少 child_isolation_verified 行\n{bench_out}"
    assert match.group(1) == "yes", f"子进程未使用临时数据目录（隔离失效）\n{bench_out}"


def test_repo_root_db_is_untouched(bench_out: str) -> None:
    """⑪ 仓库根真实 `delector.db` 不得被基准改动（桌面端是用户数据）。

    值为 `absent` 表示 CI 上根本没有这个库文件（那就无从改动，不算失败）。
    """
    match = re.search(r"^repo_db_untouched=(yes|no|absent)$", bench_out, re.MULTILINE)
    assert match is not None, f"缺少 repo_db_untouched 行\n{bench_out}"
    assert match.group(1) != "no", f"仓库根真实 delector.db 被基准改动了\n{bench_out}"


def _assert_segment_containment(out: str) -> None:
    """分段自检的**唯一**判据（spaCy 与纯 Python 两条路径共用同一断言，见模块 docstring）。

    钉**无条件**严格不等式 `import_ms > app_ready_ms`。两者同为 probe B **同一进程**内测得：
    `import_ms` = `import delector.server` 的墙钟 = 【**整个模块图导入**】 + 模块级
    `app = create_app()`（`server.py:356`）；`app_ready_ms` 只是其后的**第二次**
    `create_app()` ⇒ 只含 1 次 `create_app()`、不含模块图。故
    `import_ms − app_ready_ms ≈ T_模块图 + (两次 create_app 的成本差 ≈ 0) ≈ T_模块图 > 0`。
    `T_模块图` 恒为正且非噪声级（几百 ms），**与 spaCy 是否可用无关** —— 模型加载只是模块图
    里的一块，去掉它只是让余量从 ~1.5s 降到 ~670ms，**不改变符号**。

    **本次纠错（勿再改回分叉 / 比值带）**：曾误以为 pure 路径余量会塌到噪声级、改钉同量级
    比值带；但比值带上界要求 `T_模块图 ≤ 9 × T_create_app`，二者由完全不同资源决定
    （模块图 ∝ 模块数 × 每模块成本；`create_app` ∝ SQLite DDL + 预置导入，对 tmpfs / 暖缓存
    极敏感）⇒ 无结构耦合，健康机器也可能 ratio > 10 打红。实测 pure 下比值 ≈4.6、余量
    ≈670ms 仍稳健 ⇒ 撤回比值带。

    表数类不变式（`*_tables >= 1` / `fresh_db_used == yes`）与机器 / 缓存无关，两条路径共用。
    """
    import_ms = _number(out, "import_ms")
    app_ready_ms = _number(out, "app_ready_ms")
    assert import_ms > app_ready_ms, (
        f"import_ms({import_ms:.3f}) 未大于 app_ready_ms({app_ready_ms:.3f})：同一进程内 "
        f"import delector.server 含【整个模块图导入 T_模块图】+ 模块级 create_app()（server.py:356），"
        f"而 app_ready_ms 只是其后的第二次 create_app() ⇒ 差值 ≈ T_模块图 > 0，与 spaCy 是否可用无关"
        f"（模型加载只是模块图里的一块）\n{out}"
    )
    init_db_tables = _number(out, "init_db_tables")
    assert init_db_tables >= 1.0, (
        f"probe A 的 init_db() 后全新库 initdb/init.db 的 sqlite_master 表数为 {init_db_tables:.0f}："
        f"没有建表 ⇒ env 未生效或 init_db() 落到了热库（守卫不能只设在 probe B 一侧）\n{out}"
    )
    init_db_progress_tables = _number(out, "init_db_progress_tables")
    assert init_db_progress_tables >= 1.0, (
        f"probe A 的 init_db() 后全新库 initdb/init_progress.db 的 sqlite_master 表数为 "
        f"{init_db_progress_tables:.0f}：没有建进度表 ⇒ init_db() 没走完整初始化\n{out}"
    )
    db_tables = _number(out, "app_ready_db_tables")
    assert db_tables >= 1.0, (
        f"第二次 create_app() 后全新库 appready/second.db 的 sqlite_master 表数为 {db_tables:.0f}："
        f"没有建表 ⇒ 门上标的『冷库装配』不成立\n{out}"
    )
    progress_tables = _number(out, "app_ready_progress_tables")
    assert progress_tables >= 1.0, (
        f"第二次 create_app() 后全新库 appready/second_progress.db 的 sqlite_master 表数为 "
        f"{progress_tables:.0f}：没有建进度表 ⇒ 第二次 create_app() 没走完整 init_db()\n{out}"
    )
    fresh = re.search(r"^app_ready_fresh_db_used=(yes|no)$", out, re.MULTILINE)
    assert fresh is not None, f"缺少 `app_ready_fresh_db_used=yes|no` 自检行\n{out}"
    assert fresh.group(1) == "yes", (
        f"app_ready_fresh_db_used=no：第二次 create_app() 没有写在新库路径上"
        f"（可能又写回了 main_db）\n{out}"
    )


def test_segments_satisfy_physical_containment(bench_out: str) -> None:
    """⑫ 分段自检（**这才是防恒真的那条**，见模块 docstring 与 `_assert_segment_containment`）。

    这里执行**无条件**严格不等式 `import_ms > app_ready_ms`（与 `nlp_path` 无关）；纯 Python
    路径由 `test_segment_containment_is_visible_on_pure_python_path` 注入假 `spacy` 桩真实覆盖
    —— 二者复用同一断言，保证严格不等式在 pure 下也成立。

    刻意**不再**钉跨进程量级关系（`app_ready_ms > init_db_ms`、`model_load_ms <= import_ms`）：
    probe A / probe B 是两个进程、前置状态不同，跨进程不存在必然的大小关系（本机同向、CI 反向）。
    """
    _assert_segment_containment(bench_out)


def test_segment_containment_is_visible_on_pure_python_path(tmp_path: Path) -> None:
    """⑫' 纯 Python 回退路径必须**真实到达**且严格不等式在其上仍成立（不得用 `pytest.skip` 回避）。

    这里用 `PYTHONPATH` 注入一个 `raise ImportError` 的假 `spacy.py`（子进程 env 由
    `dict(os.environ)` 派生 ⇒ 桩会传播到基准的每个子进程），强制 processor 走纯 Python 降级，
    再复用同一判据 `_assert_segment_containment`。它的价值是同时证明两件事：pure 路径**真实可达**，
    且**无条件严格不等式在 pure 下也成立**（余量来自模块图导入，与 spaCy 无关）。

    若桩未生效（`nlp_path` 仍为 `spacy`）本断言立刻红 —— 绝不静默通过，从而杜绝「pure 路径
    未被覆盖却无人知晓」。
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "spacy.py").write_text(
        "raise ImportError('gate stub: spacy unavailable')\n", encoding="utf-8"
    )
    env_extra = {"PYTHONPATH": str(stub_dir) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    out = _run_bench(tmp_path, env_extra)
    nlp_match = re.search(r"^nlp_path=(spacy|pure)$", out, re.MULTILINE)
    assert nlp_match is not None, f"nlp_path 不可解析（只接受 spacy|pure）\n{out}"
    assert nlp_match.group(1) == "pure", (
        f"假 spacy 桩未生效，基准仍走 `nlp_path={nlp_match.group(1)}` ⇒ 纯 Python 分支未被覆盖\n{out}"
    )
    _assert_segment_containment(out)


def test_health_200_covers_whole_startup(bench_out: str) -> None:
    """⑬ `health_200_ms` 是用户体感主指标，必须覆盖 import 段（进程起 → 可服务）。"""
    assert _number(bench_out, "health_200_ms") > _number(bench_out, "import_ms") * 0.5, (
        f"health_200_ms 小于 import_ms 的一半：它没在测「进程起 + 起服务 + 首请求」\n{bench_out}"
    )


def test_verdict_names_android_baseline(bench_out: str) -> None:
    """⑭ 结论必须点名 Android 已知口径（`[Instinct: No-Silent-Conclusion]`）。

    84000 ms 是「启动页轮询上限」而不是实测首启耗时，30MB 是解包量 —— 结论里必须
    把它们与桌面数字的关系讲清楚，否则下游会把两个不可比的数直接相减。
    """
    verdict = re.search(r"^verdict=(.+)$", bench_out, re.MULTILINE)
    assert verdict is not None, f"缺少 verdict 结论行\n{bench_out}"
    text = verdict.group(1)
    for token in ANDROID_TOKENS:
        assert token in text, f"verdict 缺少 `{token}`：{text}"
    assert "health_200_ms=" in text or "桌面" in text, f"verdict 必须带上桌面侧数字：{text}"


def test_health_200_p95_comes_from_the_same_sample_batch(bench_out: str) -> None:
    """⑯ `health_200_p95_ms` 必须与 `health_200_ms`（中位数）取自同一批样本。

    冷启动是**跨进程**测量（每轮一个全新解释器 + 一次起服务），重算分位只能靠脚本
    自己吐出的样本行 —— 没有样本行就无从复核 p95 是不是拿中位数冒充的。
    物理边界同另两个基准：median ≤ p95 ≤ max。
    """
    samples_match = SAMPLES_HEALTH_RE.search(bench_out)
    assert samples_match is not None, (
        f"输出缺少 `samples_health_200_ms=<逗号分隔>` 样本行（无样本则 p95 不可复核）\n{bench_out}"
    )
    samples = [float(item) for item in samples_match.group(1).split(",")]
    assert len(samples) == int(_number(bench_out, "rounds")), (
        f"`samples_health_200_ms` 样本数 {len(samples)} ≠ rounds\n{bench_out}"
    )
    p95 = _number(bench_out, "health_200_p95_ms")
    expected = statistics.quantiles(sorted(samples), n=100, method="inclusive")[94]
    assert p95 == pytest.approx(expected, abs=QUANTILE_ABS_TOL_MS), (
        f"health_200_p95_ms={p95} 与样本重算值 {expected} 不符：不是同批样本算出来的\n{bench_out}"
    )
    median = _number(bench_out, "health_200_ms")
    assert p95 >= median - QUANTILE_ABS_TOL_MS, f"p95={p95} 低于中位数 {median}\n{bench_out}"
    assert p95 <= max(samples) + QUANTILE_ABS_TOL_MS, f"p95={p95} 超过样本最大值\n{bench_out}"


def test_p95_rounds_are_env_tunable() -> None:
    """⑰ 轮数必须可提：冷启动抖动最大，判"条件②不成立"需要 n≥20 的样本量。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "BENCH_P95_ROUNDS" in src, "基准脚本必须支持 BENCH_P95_ROUNDS 提高 p95 样本量"


def test_model_load_caliber_is_declared(bench_out: str) -> None:
    """⑮ `model_load_ms` 的口径必须写明：它是 import_ms 的**子集**，不可直接相减。"""
    note = re.search(r"^model_load_note=(.+)$", bench_out, re.MULTILINE)
    assert note is not None, f"缺少 model_load_note 口径行\n{bench_out}"
    assert "子集" in note.group(1), f"必须写明 model_load_ms 是 import_ms 的子集：{note.group(1)}"
