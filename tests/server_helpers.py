# -*- coding: utf-8 -*-
"""tests/ 侧共享 helper：跨域共用的模块级常量与纯函数（C6 Task 1 提取）。

为什么要这一层
--------------
`test_server.py` 正按被测面切分为多个 `tests/test_server_<domain>.py`。符号若只靠
「同文件隐式可见性」被多个域共用，切分后即断裂；本模块把这类**跨域**项显式化，
各域文件按名 import，不再依赖隐式可见性。

纪律
----
- 只收跨域共用项：单一域内使用的 helper 留在各测试文件里、随其域搬迁。
- 测试文件 MUST 显式 `from server_helpers import ...`；禁止 import * / re-export 桥。
- 本模块不得 import 任何 `test_*.py`（依赖方向：测试文件 → 本模块 → 被测代码）。

夹具也住这里（C6 Task 3 追加）
------------------------------
`clean_db`（autouse）/ `lan_client` / `test_db_path` 被多个域文件共用 ⇒ 定义上收到这里，
成为**唯一实现**（Task 2 已在 `test_server_packaging.py` 逐字复制过一份 `clean_db`；
再复制第三、四份必漂移）。夹具按名 import 进测试模块的命名空间即在该模块注册，
autouse 也只对注册它的模块生效——两个方向都经探针实测（导入者命中夹具 / 只导入其它
符号者不受影响）。

夹具体内的 `delector.server`（以及 `fastapi.testclient`）import 刻意留在函数内：本模块被
多个测试文件在**收集期**导入，顶层 import server 会把「导入即 `init_db()`」的既有暴露面
提前到收集期（与 `tests/conftest.py` 的 `client` 夹具同一纪律）。

桌面域共用（C6 Task 6 追加）
--------------------------
`test_desktop_shell.py` 按被测面切成 4 个新域文件后，跨域共用项上收到本模块（唯一实现）：
autouse 夹具 `_isolate_data_dir`、`REPO_ROOT`、惰性 `_mod()`、`ast` 工具
（`_parse_desktop` / `_funcs_by_name` / `_calls` / `_call_label` / `_is_main_guard`）与桌面替身
（`_stub_server_build` / `_RecordingCtypes`）。`_mod()` 刻意惰性 import（`desktop` 不存在时
逐条报 ModuleNotFoundError，而非收集期中断——原理由见原文件 module docstring）。
残余 `test_desktop_shell.py` 仍保留自己的 `_isolate_data_dir` 文件内定义：它的元测试
`test_all_dispatch_tests_isolate_the_data_dir` 静态扫描**本模块源码**找 autouse fixture 定义，
改成 import 注册会把它判红（该文件内注释同述）。
"""

import ast
import gc
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest
from db_cleanup import remove_db_files

from delector.core.database import db_conn

# 仓库根：凡读仓库资源（server.py / static / tools / android / .github / .githooks /
# nlp.py / package_windows.py）一律经 ROOT。别再写 os.path.dirname(__file__) 相对测试
# 文件推 —— tests/ 比仓库根深一层，那会指到 tests/。
ROOT = os.path.dirname(os.path.dirname(__file__))


def _insert_vocab_card(**over: object) -> int:
    """直插一行 vocab_cards（绕过建卡端点，以便精确摆出 fsrs_*/repetition_count 组合）。

    最小必填列：word / lemma / definition_zh / sentence_context。
    """
    row: Dict[str, Any] = {
        "word": "Haus",
        "lemma": "Haus",
        "definition_zh": "房子",
        "sentence_context": "Das Haus ist alt.",
    }
    row.update(over)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards "
            "(word, lemma, definition_zh, sentence_context, fsrs_s, repetition_count, mastered, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["word"],
                row["lemma"],
                row["definition_zh"],
                row["sentence_context"],
                row.get("fsrs_s"),
                row.get("repetition_count", 0),
                row.get("mastered", 0),
                row.get("due_date"),
            ),
        )
        return int(cur.lastrowid or 0)


# ── 跨域夹具（C6 Task 3：自 `test_server.py` / `test_server_packaging.py` 上收的唯一实现）──


@pytest.fixture(autouse=True)
def clean_db():
    # sqlite3.Connection 与内部 statement 互为引用环：`with get_db(...)` 只提交
    # 事务不 close，文件句柄要等循环 GC 才释放。Windows 上句柄未释放时 os.remove
    # 抛 PermissionError（被吞），旧 DB 带着上一测试的数据残留下来 → 隔离失效。
    # 删除前先 gc.collect()，把上一测试遗留的连接环清掉，删除才确定成功。
    # 前后双钉 env：database.get_db_path() 每次调用都读 os.environ（不是 import
    # 时冻结），全量 pytest 时更晚收集的文件（test_audit_hardening.py 等）在
    # 模块顶层改写 DATABASE_PATH，收集顺序若让本文件先 import、用例后执行，
    # 默认路径就会命中未建表的别家库 → 「no such table」成片假失败。
    from delector.server import init_db

    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = "test_delector.db"
    os.environ["PROGRESS_DB_PATH"] = "test_progress.db"
    # 连带删除 WAL 旁文件（-wal/-shm）：启用 WAL 后它们与主库同生共死，只删主库会把
    # 陈旧 -shm 留给下个用例 → 打开即 `disk I/O error`。其它测试模块早已按三件套清理。
    gc.collect()
    remove_db_files("test_delector.db", "test_progress.db")
    init_db("test_delector.db")
    yield
    gc.collect()
    remove_db_files("test_delector.db", "test_progress.db")
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def lan_client():
    """模拟同 Wi-Fi 的另一台设备，用于验证备份端点的局域网闸。"""
    from fastapi.testclient import TestClient

    from delector.server import app

    return TestClient(app, client=("192.168.1.77", 54321))


@pytest.fixture
def test_db_path():
    return "test_delector.db"


def _package_windows_build_windows_fn() -> ast.FunctionDef:
    """取出 `package_windows.py` 的 `build_windows` 函数节点（供调用点守卫共用）。"""
    tree = ast.parse(open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read())
    build_fn = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_windows"),
        None,
    )
    assert build_fn is not None, "package_windows.py 必须定义 build_windows()"
    return build_fn


def _calls_named(body: ast.AST, name: str) -> bool:
    """`body` 内是否出现对 `name(...)` 的调用（支持裸名或属性形式）。"""

    def _is_match(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return node.func.id == name
        return isinstance(node.func, ast.Attribute) and node.func.attr == name

    return any(_is_match(node) for node in ast.walk(body))


# ── 桌面壳跨域共用（C6 Task 6：自 `test_desktop_shell.py` 上收的唯一实现）────────────────
# 使用方：test_desktop_bootstrap.py · test_desktop_tray_exit.py · test_desktop_startup_guards.py
# · test_desktop_window_lifecycle.py。残余 test_desktop_shell.py 的 `_isolate_data_dir` 定义
# 刻意留在原文件（其元测试静态扫描本模块源码找 autouse fixture 定义，import 注册会被判红）；
# 本模块的副本是四个新域文件的唯一来源，两处注释互相指认。


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """任何用例默认把 `DELECTOR_DATA_DIR` 钉到 `tmp_path`：**绝不**落到开发者真实数据目录。

    为什么 autouse：`dispatch()` 的 `--server-only` 路径会读 `os.environ` 解析日志/地址落点
    （`resolve_log_path` → `ensure_streams` → `rotate_log_if_needed`）—— 个别用例漏写 `tmp_path`
    就会滚动真 `launch.log`、写出真 `lan-address.txt`（Task 5 前还会删真 `lan-address.txt`），落进
    `%LOCALAPPDATA%\\DeLector` / `~/.local/share/DeLector`。逐条加易漏，故用**全局兜底**：新增用例
    不写都安全。`resolve_log_path` 的既有用例都显式传 dict（不走 `os.environ`），不受影响；需要别的
    落点的用例自行 `monkeypatch.setenv` 覆盖即可（后设生效）。
    """
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))


REPO_ROOT = Path(__file__).resolve().parent.parent


# 惰性导入（刻意，理由见模块 docstring）：模块不存在时逐条报 ModuleNotFoundError。
def _mod() -> Any:
    import desktop

    return desktop


# ── Task 3 起共用的建服段替身（_after_start 里的 import/build/serve 已搬进事件循环）──────
def _stub_server_build(
    monkeypatch: pytest.MonkeyPatch, mod: Any, order: Optional[List[str]] = None
) -> None:
    """把 `_after_start` 的建服段（Task 3 搬入）换成替身：不起真服务、不 import 真
    `delector.server`。

    两个理由，缺一不可：
    1. **不起真服务**：`build_server` / `serve_in_thread` 会真绑端口起 uvicorn —— 测试纪律
       （不起真实服务/建窗）禁止；
    2. **不 import 真 `delector.server`**：那一跑会把 DATA_DIR 按仓库根落定（desktop.py 的
       ⚠️ 注释即为此），直接污染测试隔离（正是测试卫生要防的雷）。

    `order` 非空时把两次调用记进去（供阶段顺序断言观测"建服晚于 webview.start()"）。
    """
    fake_server: Any = types.ModuleType("delector.server")
    fake_server.app = object()  # `from delector.server import app` 只取这个属性
    monkeypatch.setitem(sys.modules, "delector.server", fake_server)

    def _fake_build_server(*_a: Any, **_k: Any) -> str:
        if order is not None:
            order.append("build_server")
        return "FAKE_SERVER"

    def _fake_serve_in_thread(*_a: Any, **_k: Any) -> str:
        if order is not None:
            order.append("serve_in_thread")
        return "FAKE_THREAD"

    monkeypatch.setattr(mod, "build_server", _fake_build_server)
    monkeypatch.setattr(mod, "serve_in_thread", _fake_serve_in_thread)


# ── `desktop.py` 源码解析助手（C6 Task 6 上收，多域共用）─────────────────────────────


def _parse_desktop() -> ast.Module:
    return ast.parse((REPO_ROOT / "desktop.py").read_text(encoding="utf-8"))


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or not test.comparators:
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


# ── AST 调用图小工具（C6 Task 6 上收，多域共用）──────────────────────────────────────


def _funcs_by_name(tree: ast.Module) -> Dict[str, ast.FunctionDef]:
    """模块顶层函数名 → 定义节点（本文件所有相关函数都在顶层）。"""
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            yield child


def _call_label(call: ast.Call) -> Optional[str]:
    """调用的"可读名"：`a.b()` → attr `b`；`f()` → id `f`；其余返回 None。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


# ── 记录型假 ctypes（C6 Task 6 上收，多域共用）：`__getattr__` 只记账**不抛**─────────────
# （哨兵版会被实现里的 `except Exception` 吞掉 ⇒ 假绿；原注释见 test_desktop_startup_guards.py 段头。）


class _RecordingCtypes(types.ModuleType):
    """记录型假 ctypes：属性访问记账（`touched`）、调用记账并返回 0（`calls`），**绝不抛**。"""

    def __init__(self, name: str, touched: List[str], calls: List[Any]) -> None:
        super().__init__(name)
        self._touched = touched
        self._calls = calls

    def __getattr__(self, name: str) -> Any:
        self._touched.append(name)
        return _RecordingCtypes(name, self._touched, self._calls)

    def __call__(self, *args: Any, **_kwargs: Any) -> int:
        self._calls.append(args)
        return 0
