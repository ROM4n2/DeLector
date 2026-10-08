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
钉绝对阈值 ⇒ CI 假红。故本文件**只钉可解析 + 正区间 + 分段之间的物理包含关系**：
- `app_ready_ms > init_db_ms`：`create_app()` 内部就调用 `init_db()`，还多了路由
  注册、预置文章导入与静态挂载 ⇒ 必然更大。谁把 `app_ready_ms` 打桩成 0，这里红。
- `import_ms > app_ready_ms`：`import delector.server` 除 spaCy 模型加载外，模块级
  就 `app = create_app()` ⇒ 必然更大。
- `model_load_ms <= import_ms`：模型加载发生在 `import delector.server` **之内**
  （`processor.py:81-111` 在导入期加载），是它的**子集** ⇒ 不可能更大。
这三条是**结构关系**而非绝对阈值，既不假红，也不是「能跑就绿」。

门禁跑的是快档（`BENCH_COLD_START_ROUNDS=5`，下限也是 5）。
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Pattern

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_cold_start.py"

# 契约行：与基准脚本的输出一一对应。缺任一 ⇒ 分段拆解塌回单段数字。
NUMERIC_KEYS = ("import_ms", "init_db_ms", "app_ready_ms", "health_200_ms", "model_load_ms")
POSITIVE_KEYS = NUMERIC_KEYS

GATE_ROUNDS = "5"

SUPPRESSION_RES: tuple[Pattern[str], ...] = (
    re.compile(r"type:\s*ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"mypy:\s*disable-error-code"),
)

# Android 侧已知口径（docs/agents/architecture.md:100-101）：Chaquopy 首次启动解包
# 约 30MB、启动页轮询上限约 84 秒。verdict 必须点名它们，且本机不可测要写明。
ANDROID_TOKENS = ("Android", "30MB", "84000", "android=unmeasured")


def _run_bench(tmp_path: Path) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文。"""
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
    for key in (*NUMERIC_KEYS, "rounds", "nlp_path", "verdict", "android"):
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


def test_segments_satisfy_physical_containment(bench_out: str) -> None:
    """⑫ 分段之间的物理包含关系（**这才是防恒真的那条**，见模块 docstring）。

    三条关系任一反转就说明某段被打了桩、或测的已不是它自称的东西。
    """
    import_ms = _number(bench_out, "import_ms")
    init_db_ms = _number(bench_out, "init_db_ms")
    app_ready_ms = _number(bench_out, "app_ready_ms")
    model_load_ms = _number(bench_out, "model_load_ms")
    assert app_ready_ms > init_db_ms, (
        f"app_ready_ms({app_ready_ms:.3f}) 未大于 init_db_ms({init_db_ms:.3f})："
        f"create_app() 内部就含 init_db()，还多了路由注册与预置内容导入\n{bench_out}"
    )
    assert import_ms > app_ready_ms, (
        f"import_ms({import_ms:.3f}) 未大于 app_ready_ms({app_ready_ms:.3f})："
        f"import delector.server 含 spaCy 模型加载与模块级 create_app()\n{bench_out}"
    )
    assert model_load_ms <= import_ms, (
        f"model_load_ms({model_load_ms:.3f}) 大于 import_ms({import_ms:.3f})："
        f"模型加载发生在 import 之内，是它的子集\n{bench_out}"
    )


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


def test_model_load_caliber_is_declared(bench_out: str) -> None:
    """⑮ `model_load_ms` 的口径必须写明：它是 import_ms 的**子集**，不可直接相减。"""
    note = re.search(r"^model_load_note=(.+)$", bench_out, re.MULTILINE)
    assert note is not None, f"缺少 model_load_note 口径行\n{bench_out}"
    assert "子集" in note.group(1), f"必须写明 model_load_ms 是 import_ms 的子集：{note.group(1)}"
