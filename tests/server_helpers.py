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
"""

import ast
import gc
import os
from typing import Any, Dict

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
